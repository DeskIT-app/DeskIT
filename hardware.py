"""What this computer can do, decided once per start and written down
(DISTRIBUTION_PLAN.md 6.2-6.3, D14).

The probe never raises and never asks the network anything but this
PC's own Ollama. The cheap facts — CUDA devices through ctranslate2,
VRAM and the driver through nvidia-smi, cores and RAM — take well under
a second and decide the TIER before any model loads:

    gpu        an NVIDIA card with 6 GB or more and a driver new enough
    gpu-small  4 to 6 GB
    cpu        everything else — no card, no driver, too little memory

The slow facts — Ollama and its models, a Hebrew voice — are gathered
on a thread afterwards, because a PowerShell that lists voices costs a
second or two and dictation must not wait for it.

`apply(tier)` writes the tier's DERIVED defaults (6.3's table) into
state.json, the machine-derived layer, and only for keys the person has
not set in settings.toml — a choice always wins over a probe, and an
update never fights one. The owner's checkout never applies anything:
his settings are the shipped defaults (D34) and his machine is the
reference; the facts are still recorded so a report can carry them.

Everything lands under `hardware.*` in state.json: cuda_devices,
vram_mb, driver, driver_ok, cores, ram_mb, gpu_pack, ollama,
ollama_models, he_voice, tier, probed_at, probe_version. A tier that
changed since the last start (a laptop docked to a card, a driver
update) rewrites the derived keys; the Home card of chapter 9 says so.
"""
from __future__ import annotations

import ctypes
import logging
import os
import subprocess
import threading
import time

import config as config_mod
import paths

log = logging.getLogger("app")

PROBE_VERSION = 1
CREATE_NO_WINDOW = 0x08000000
#: CTranslate2 >= 4.5 needs cuDNN 9, which needs a CUDA >= 12.3 driver:
#: 545.84 on Windows (NVIDIA's CUDA 12.3 release table).
DRIVER_FLOOR = (545, 84)
GPU_MB, GPU_SMALL_MB = 6 * 1024, 4 * 1024
TIERS = ("gpu", "gpu-small", "cpu")

#: 6.3, the columns that differ from the shipped defaults. A key absent
#: from a tier keeps defaults.toml's value (which is tier 1's, D6/D34).
DERIVED: dict[str, dict[str, object]] = {
    "gpu": {
        "local.device": "cuda", "local.compute_type": "float16",
        "local.cpu_threads": 0, "local.beam_size": 5,
    },
    "gpu-small": {
        "local.device": "cuda", "local.compute_type": "int8_float16",
        "local.cpu_threads": 0, "local.beam_size": 5,
        "local.english_model": "",
        "polish.max_wait_s": 6.0, "polish.ollama_model": "gemma3:4b",
        "lookup.model": "gemma3:4b", "lookup.keep_alive": "10m",
        "visual_qa.ollama_model": "gemma3:4b", "visual_qa.ollama_timeout_s": 60,
        "translate.ollama_model": "llama3.2:3b",
    },
    "cpu": {
        "local.device": "cpu", "local.compute_type": "int8",
        "local.beam_size": 2, "review.enabled": False, "study.enabled": False,
        # no English detector: 1.6 GB more RAM and a second full pass
        "local.english_model": "",
        # the repair pass off (config refuses max_wait_s = 0 and an empty
        # model name; "never" is its own switch), the small models named
        # for the day Ollama turns up
        "polish.when": "never", "polish.ollama_model": "gemma3:4b",
        "lookup.model": "gemma3:4b", "visual_qa.ollama_model": "gemma3:4b",
        "visual_qa.ollama_timeout_s": 60, "translate.ollama_model": "llama3.2:3b",
    },
}
#: The keys any tier may have written — cleared when the tier changes,
#: so a machine that lost its card is not left with float16.
DERIVED_KEYS = frozenset(k for keys in DERIVED.values() for k in keys)


# ------------------------------------------------------------- the facts

def cuda_devices() -> int:
    try:
        import ctranslate2
        return int(ctranslate2.get_cuda_device_count())
    except Exception:                                    # noqa: BLE001
        return 0


def nvidia_smi(timeout: float = 5.0) -> tuple[int, str] | None:
    """(vram_mb, driver) of the first NVIDIA card, or None without one."""
    try:
        done = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.total,driver_version",
             "--format=csv,noheader,nounits"],
            capture_output=True, timeout=timeout, creationflags=CREATE_NO_WINDOW,
            encoding="utf-8", errors="replace")
        line = (done.stdout or "").strip().splitlines()[0]
        total, driver = [p.strip() for p in line.split(",")[:2]]
        return int(float(total)), driver
    except Exception:                                    # noqa: BLE001
        return None


def driver_ok(driver: str) -> bool:
    """Whether the driver clears DRIVER_FLOOR; an unparseable version is
    taken as too old, which only costs a CPU tier until it is read."""
    try:
        major, minor = (int(p) for p in driver.strip().split(".")[:2])
    except (ValueError, AttributeError):
        return False
    return (major, minor) >= DRIVER_FLOOR


def ram_mb() -> int:
    class _MemoryStatus(ctypes.Structure):
        _fields_ = [("dwLength", ctypes.c_uint32), ("dwMemoryLoad", ctypes.c_uint32),
                    ("ullTotalPhys", ctypes.c_uint64), ("ullAvailPhys", ctypes.c_uint64),
                    ("ullTotalPageFile", ctypes.c_uint64), ("ullAvailPageFile", ctypes.c_uint64),
                    ("ullTotalVirtual", ctypes.c_uint64), ("ullAvailVirtual", ctypes.c_uint64),
                    ("ullAvailExtendedVirtual", ctypes.c_uint64)]
    try:
        status = _MemoryStatus()
        status.dwLength = ctypes.sizeof(status)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        if kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return int(status.ullTotalPhys // (1024 * 1024))
    except Exception:                                    # noqa: BLE001
        pass
    return 0


def ollama(timeout: float = 1.0) -> tuple[bool, list[str]]:
    """Whether Ollama answers on this PC, and which models it holds —
    through net.py (loopback is always allowed)."""
    import json

    import net
    try:
        status, _h, body = net.request("GET", "http://127.0.0.1:11434/",
                                       "ollama", timeout_s=timeout)
        if status != 200 or b"Ollama" not in body:
            return False, []
        status, _h, body = net.request("GET", "http://127.0.0.1:11434/api/tags",
                                       "ollama", timeout_s=timeout * 3)
        if status != 200:
            return True, []
        data = json.loads(body.decode("utf-8", "replace"))
        return True, sorted(str(m.get("name", "")) for m in data.get("models", [])
                            if m.get("name"))
    except Exception:                                    # noqa: BLE001
        return False, []


_VOICES_PS = (
    "[Windows.Media.SpeechSynthesis.SpeechSynthesizer, Windows.Media, ContentType=WindowsRuntime] > $null; "
    "foreach ($v in [Windows.Media.SpeechSynthesis.SpeechSynthesizer]::AllVoices) "
    "{ if ($v.Language -like 'he*') { Write-Output $v.DisplayName; break } }"
)


def hebrew_voice(timeout: float = 8.0) -> str:
    """The display name of a he-IL WinRT voice, or ''."""
    try:
        done = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", _VOICES_PS],
            capture_output=True, timeout=timeout, creationflags=CREATE_NO_WINDOW,
            encoding="utf-8", errors="replace")
        return (done.stdout or "").strip().splitlines()[0].strip() if (done.stdout or "").strip() else ""
    except Exception:                                    # noqa: BLE001
        return ""


def gpu_pack_state() -> str:
    """The GPU pack's standing (6.5): `venv` in the checkout when the
    CUDA wheels are importable from the interpreter that runs this (the
    owner's venv), else `missing`; on an installed copy what packs.py
    says — ok, stale, missing, or `failed:<reason>` when the pack is
    there and the ladder saw it not run."""
    if not paths.PORTABLE:
        import packs
        return packs.standing("gpu")
    try:
        import nvidia.cublas  # noqa: F401
        import nvidia.cudnn  # noqa: F401
        return "venv"
    except Exception:                                    # noqa: BLE001
        return "missing"


# ----------------------------------------------------------- the decision

def tier_for(facts: dict) -> str:
    if int(facts.get("cuda_devices") or 0) < 1:
        return "cpu"
    if facts.get("driver") and not facts.get("driver_ok"):
        return "cpu"
    pack = str(facts.get("gpu_pack") or "")
    if (pack in ("missing", "unknown") or pack.startswith("failed:")) and not paths.DEVELOPER:
        # the wheels are not there yet, or are there and do not run: the
        # card exists, the tier does not — the pack step (packs.py) or
        # Settings > Speed is where it becomes gpu
        return "cpu"
    vram = int(facts.get("vram_mb") or 0)
    if vram and vram < GPU_SMALL_MB:
        return "cpu"
    if vram and vram < GPU_MB:
        return "gpu-small"
    return "gpu"


def probe() -> dict:
    """The cheap facts and the tier: under a second, never raising."""
    facts: dict = {"cuda_devices": cuda_devices(), "vram_mb": 0, "driver": "",
                   "driver_ok": False, "cores": int(os.cpu_count() or 1),
                   "ram_mb": ram_mb(), "gpu_pack": gpu_pack_state()}
    smi = nvidia_smi() if facts["cuda_devices"] else None
    if smi:
        facts["vram_mb"], facts["driver"] = smi
        facts["driver_ok"] = driver_ok(facts["driver"])
    elif facts["cuda_devices"]:
        facts["driver_ok"] = True          # a card ctranslate2 sees, no nvidia-smi to ask
    facts["tier"] = tier_for(facts)
    facts["probed_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    facts["probe_version"] = PROBE_VERSION
    return facts


def probe_slow() -> dict:
    """Ollama and the Hebrew voice — seconds, so on a thread."""
    on, models = ollama()
    return {"ollama": on, "ollama_models": models, "he_voice": hebrew_voice()}


# --------------------------------------------------------------- the state

def recorded() -> dict:
    """What state.json says about this machine, `hardware.` stripped."""
    state = config_mod.read_state(paths.STATE_FILE)
    return {k[9:]: v for k, v in state.items() if k.startswith("hardware.")}


def record(facts: dict) -> None:
    try:
        config_mod.save({f"hardware.{k}": v for k, v in facts.items()})
    except Exception as e:                               # noqa: BLE001
        log.info("hardware: the facts were not written (%s)", e)


def apply(tier: str, previous: str | None = None) -> dict[str, object]:
    """The tier's derived defaults into the machine layer (state.json),
    only for keys settings.toml does not set. When the tier changed, every
    derived key of the old tier goes first. The checkout applies nothing.
    Returns what was written."""
    if paths.DEVELOPER or tier not in DERIVED:
        return {}
    chosen = set(config_mod.read_settings(paths.SETTINGS_FILE))
    wanted = {k: v for k, v in DERIVED[tier].items() if k not in chosen}
    try:
        if previous is not None and previous != tier:
            config_mod.save({k: None for k in DERIVED_KEYS}, derived=True)
        if wanted:
            config_mod.save(wanted, derived=True)
    except Exception as e:                               # noqa: BLE001
        log.warning("hardware: the tier's defaults were not written (%s)", e)
        return {}
    return wanted


def clear_change() -> None:
    """The Home row's OK: the change was seen."""
    try:
        config_mod.save({"hardware.tier_changed": None, "hardware.tier_changed_at": None})
    except Exception:                                    # noqa: BLE001
        log.debug("hardware: the change note was not cleared", exc_info=True)


TIER_WORDS = {"gpu": "on the graphics card", "gpu-small": "on a small graphics card",
              "cpu": "on the processor"}


def summary(facts: dict | None = None) -> str:
    """One line for the Speed page: what was found and what that
    means — `gpu — NVIDIA card, 16 GB, driver 596.49 · 12 cores, 16 GB RAM`."""
    facts = recorded() if facts is None else facts
    if not facts.get("tier"):
        return "not probed yet"
    parts = [f"{facts['tier']} ({TIER_WORDS.get(facts['tier'], facts['tier'])})"]
    if int(facts.get("cuda_devices") or 0):
        card = "NVIDIA card"
        if facts.get("vram_mb"):
            card += f", {int(facts['vram_mb']) / 1024:.0f} GB"
        if facts.get("driver"):
            card += f", driver {facts['driver']}"
            if not facts.get("driver_ok"):
                card += " (too old for CUDA 12.3)"
        parts.append(card)
    else:
        parts.append("no NVIDIA card")
    if facts.get("cores"):
        parts.append(f"{facts['cores']} cores, {int(facts.get('ram_mb') or 0) / 1024:.0f} GB RAM")
    return " · ".join(parts)


NO_VOICE = ("No Hebrew voice is installed. Add one under Windows Settings > "
            "Time & Language > Speech, then restart DeskIT.")


def apply_voice(he_voice: str) -> str | None:
    """6.8: without a he-IL voice the answer is not read aloud —
    `visual_qa.speak = "off"` into the machine layer, only where
    settings.toml is silent, and taken out again the start a voice is
    found. The checkout is left alone (the owner has Asaf). Returns
    what was written, or None."""
    if paths.DEVELOPER:
        return None
    chosen = set(config_mod.read_settings(paths.SETTINGS_FILE))
    if "visual_qa.speak" in chosen:
        return None
    try:
        if he_voice:
            config_mod.save({"visual_qa.speak": None}, derived=True)
            return None
        config_mod.save({"visual_qa.speak": "off"}, derived=True)
        log.info("hardware: %s", NO_VOICE)
        return "off"
    except Exception as e:                               # noqa: BLE001
        log.warning("hardware: the voice's setting was not written (%s)", e)
        return None


def no_voice() -> bool:
    """Has the probe looked and found no Hebrew voice? (An installed copy
    only; the checkout speaks with Asaf.)"""
    if paths.PORTABLE:
        return False
    facts = recorded()
    return "he_voice" in facts and not facts.get("he_voice")


def ollama_absent() -> bool:
    """Has the probe looked and found no Ollama on this PC? Only an
    installed copy hides its menu entries on that answer."""
    if paths.PORTABLE:
        return False
    facts = recorded()
    return "ollama" in facts and not facts.get("ollama")


def run_at_start(say=None) -> dict:
    """Probe, decide, record, apply — and the slow half on a thread. What
    the caller gets back is the fast facts with the tier."""
    before = recorded()
    facts = probe()
    previous = before.get("tier")
    changed = previous is not None and previous != facts["tier"]
    record(facts)
    written = apply(facts["tier"], previous)
    log.info("hardware: %s — %d CUDA device(s), %s MB VRAM, driver %s, %d cores, "
             "%d MB RAM, gpu pack %s%s", facts["tier"], facts["cuda_devices"],
             facts["vram_mb"] or "?", facts["driver"] or "-", facts["cores"],
             facts["ram_mb"], facts["gpu_pack"],
             f"; {len(written)} derived setting(s) written" if written else "")
    if changed:
        log.info("hardware: the tier changed from %s to %s", previous, facts["tier"])
        # Written down for the Home row (chapter 9, screen 10's "your
        # hardware changed" variant); its [OK] clears it.
        record({"tier_changed": f"{previous} → {facts['tier']}",
                "tier_changed_at": facts["probed_at"]})
        if say is not None:
            say(f"Your hardware changed: DeskIT now runs as {facts['tier']}")

    def slow() -> None:
        try:
            found = probe_slow()
            record(found)
            apply_voice(found.get("he_voice", ""))
        except Exception:                                # noqa: BLE001
            log.debug("hardware: the slow probe tripped", exc_info=True)
    threading.Thread(target=slow, daemon=True, name="hardware-probe").start()
    return facts
