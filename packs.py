"""Packs: the wheels the base installer does not carry, fetched on
demand into a folder the person can delete (DISTRIBUTION_PLAN.md 6.5,
D14, D19, D24).

Two packs exist. `gpu` is NVIDIA's own CUDA runtime — cuBLAS, cuDNN and
NVRTC, the three wheels the owner's venv holds — 1.37 GB that a machine
without an NVIDIA card would never use and the installer therefore
never carries (D24: no NVIDIA binary in the installer). `skin` is
skia-python, the one library the painted look needs; without it every
window is the plain Tk look and nothing else changes. The plan's third
pack, `recording`, does not exist: PyAV comes with faster-whisper and is
in the base lock already.

`packs.lock`, beside the code, names each pack's wheels — version,
file name, PyPI URL, size, SHA-256, the licence links the card shows —
written by the owner (`python packs.py --lock`) from the versions his
venv holds and PyPI's own metadata (D34: what he runs is what ships).

Installing is two halves, and the first is the reason pip never talks
to PyPI here: the wheels come down through `net.download()` — the one
door out, `files.pythonhosted.org` on the allowlist, a row per file
under `pack-install`, resumed from a `.part` after a pause, hashed
against the lock — and then `python -m pip install --no-index
--find-links <the wheels> --target <the pack> --require-hashes
--no-deps` puts them in place with no network at all. That closes the
chapter's open point 1: every outbound byte of the app passes the
chokepoint, pip included. `--no-deps` because the lock IS the
dependency resolution; `--require-hashes` so pip checks the same
hashes a second time.

What goes where: `DATA_DIR\\packs\\<name>\\site` holds the installed
packages, `packs.lock` beside it records what was installed (versions,
when, which app version) and is what `state()` compares with the app's
lock — `ok`, `stale` when a release moved a version, `missing`; the
wheels are deleted once installed. `activate("gpu")` puts the pack's
`nvidia\\*\\bin` folders on the DLL search path exactly the way the
checkout's `_register_cuda_dlls()` does for its venv — `add_dll_directory`
AND a PATH prepend, because CTranslate2 loads cuBLAS with a plain
LoadLibrary that only reads PATH; `activate("skin")` appends the pack to
`sys.path`. A GPU pack that is there but does not run (the ladder's
silent inference fails on cuda) is written down as `failed:<first line>`
in state.json by `note_failure()`, the tier drops to cpu until the next
install or removal, and the Home card of chapter 9 says so.

The checkout never installs a pack: its venv has the wheels, `state()`
answers `venv`, and `activate()` does nothing (D4).
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import config as config_mod
import net
import paths
import steps
from steps import human

log = logging.getLogger("app")

PURPOSE = "pack-install"
NAMES = ("gpu", "skin")
RECORD = "packs.lock"
CREATE_NO_WINDOW = 0x08000000
#: The distributions each pack holds; the versions come from the
#: owner's venv at lock time (D34), never from here.
PINS: dict[str, tuple[str, ...]] = {
    "gpu": ("nvidia-cublas-cu12", "nvidia-cudnn-cu12", "nvidia-cuda-nvrtc-cu12"),
    "skin": ("skia-python",),
}
LICENSES: dict[str, list[tuple[str, str]]] = {
    "gpu": [("NVIDIA CUDA EULA", "https://docs.nvidia.com/cuda/eula/index.html"),
            ("cuDNN SLA", "https://docs.nvidia.com/deeplearning/cudnn/backend/latest/reference/eula.html")],
    "skin": [("skia-python licence (BSD-3)", "https://github.com/kyamagu/skia-python/blob/main/LICENSE")],
}
#: The wheel tag the product runs: the embeddable 3.11, 64-bit.
TAGS = ("cp311", "py3")
PLATFORM = "win_amd64"
STATES = ("ok", "stale", "missing", "unknown", "venv")

DownloadError = net.DownloadError


class InstallError(DownloadError):
    """pip did not finish. `reason` is `install`; str(e) is pip's own
    last complaint, one line."""

    def __init__(self, message: str):
        super().__init__("install", message)


# ---------------------------------------------------------------- the lock

@dataclass(frozen=True)
class Wheel:
    name: str
    version: str
    filename: str
    url: str
    size: int
    sha256: str


@dataclass(frozen=True)
class Pack:
    name: str
    wheels: tuple[Wheel, ...] = ()
    licenses: tuple[tuple[str, str], ...] = field(default_factory=tuple)

    @property
    def bytes(self) -> int:
        return sum(w.size for w in self.wheels)

    @property
    def versions(self) -> dict[str, str]:
        return {w.name: w.version for w in self.wheels}

    @property
    def folder(self) -> Path:
        return paths.PACKS_DIR / self.name

    @property
    def site(self) -> Path:
        return self.folder / "site"

    @property
    def wheels_dir(self) -> Path:
        return self.folder / "wheels"

    @property
    def record(self) -> Path:
        return self.folder / RECORD


def read_lock(path: Path | None = None) -> dict[str, Pack]:
    path = paths.PACKS_LOCK if path is None else path
    try:
        data = json.loads(path.read_text("utf-8"))
    except (OSError, ValueError) as e:
        log.warning("packs.lock could not be read (%s)", e)
        return {}
    out: dict[str, Pack] = {}
    for name, raw in (data.get("packs") or {}).items():
        try:
            wheels = tuple(Wheel(str(w["name"]), str(w["version"]), str(w["filename"]),
                                 str(w["url"]), int(w["size"]), str(w["sha256"]).lower())
                           for w in raw["wheels"])
            licenses = tuple((str(a), str(b)) for a, b in raw.get("licenses") or [])
            out[name] = Pack(name, wheels, licenses)
        except (KeyError, TypeError, ValueError) as e:
            log.warning("packs.lock: the entry for %s is malformed (%s)", name, e)
    return out


def pack(name: str, path: Path | None = None) -> Pack | None:
    return read_lock(path).get(name)


def write_lock(packs: list[Pack], path: Path | None = None) -> Path:
    path = paths.PACKS_LOCK if path is None else path
    data = {
        "_": "The wheels an installed copy may download (packs.py, plan 6.5): "
             "per pack, each wheel's version, file, PyPI URL, size and SHA-256, "
             "and the licence links the card shows. Written by "
             "`python packs.py --lock` from the owner's venv, never by hand.",
        "packs": {
            p.name: {
                "bytes": p.bytes,
                "licenses": [list(x) for x in p.licenses],
                "wheels": [{"name": w.name, "version": w.version, "filename": w.filename,
                            "url": w.url, "size": w.size, "sha256": w.sha256}
                           for w in p.wheels],
            }
            for p in packs
        },
    }
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return path


def size_line(p: Pack) -> str:
    return f"{human(p.bytes)} from files.pythonhosted.org into {p.folder}"


def requirements_text(p: Pack) -> str:
    """What pip is handed: every wheel pinned and hashed, so
    `--require-hashes` checks the lock a second time."""
    return "".join(f"{w.name}=={w.version} --hash=sha256:{w.sha256}\n" for w in p.wheels)


# --------------------------------------------------------------- the state

def _recorded(p: Pack) -> dict | None:
    try:
        return json.loads(p.record.read_text("utf-8"))
    except (OSError, ValueError):
        return None


def failure(name: str) -> str:
    """The reason the pack last failed to run, or '' (state.json)."""
    state = config_mod.read_state(paths.STATE_FILE)
    return str(state.get(f"hardware.{name}_pack_failed") or "")


def note_failure(name: str, reason: str) -> None:
    """The pack is there and does not run: written down for the tier
    and the Home card, cleared by the next install or removal."""
    line = (reason or "unknown").splitlines()[0][:160]
    try:
        config_mod.save({f"hardware.{name}_pack_failed": line})
    except Exception:                                        # noqa: BLE001
        log.debug("packs: the failure was not written", exc_info=True)


def clear_failure(name: str) -> None:
    try:
        config_mod.save({f"hardware.{name}_pack_failed": None})
    except Exception:                                        # noqa: BLE001
        log.debug("packs: the failure was not cleared", exc_info=True)


def state(name: str, path: Path | None = None) -> str:
    """`venv` in the checkout and a portable copy (the wheels are the
    interpreter's own); `unknown` for a pack the lock does not name;
    `missing` with nothing installed; `stale` when the installed
    versions are not the lock's; `ok`."""
    if paths.PORTABLE:
        return "venv"
    p = pack(name, path)
    if p is None:
        return "unknown"
    rec = _recorded(p)
    if rec is None or not p.site.is_dir():
        return "missing"
    return "ok" if rec.get("versions") == p.versions else "stale"


def standing(name: str) -> str:
    """state(), or `failed:<reason>` when the pack is there and was seen
    not to run — what hardware.py records as `gpu_pack`."""
    word = state(name)
    if word in ("ok", "stale"):
        why = failure(name)
        if why:
            return f"failed:{why}"
    return word


# ------------------------------------------------------------- installing

def pip_command(p: Pack, requirements: Path) -> list[str]:
    """pip with no network: the wheels already on disk, hashes checked
    again, no dependency walk (the lock is the resolution)."""
    return [sys.executable, "-m", "pip", "install", "--no-index",
            "--find-links", str(p.wheels_dir), "--target", str(p.site),
            "--require-hashes", "--no-deps", "--no-warn-script-location",
            "--disable-pip-version-check", "-r", str(requirements)]


def _run_pip(p: Pack, requirements: Path) -> str:
    done = subprocess.run(pip_command(p, requirements), capture_output=True,
                          creationflags=CREATE_NO_WINDOW, encoding="utf-8",
                          errors="replace", timeout=1800)
    out = (done.stdout or "") + (done.stderr or "")
    if done.returncode != 0:
        lines = [ln for ln in out.splitlines() if ln.strip()]
        errors = [ln for ln in lines if "error" in ln.lower()]
        raise InstallError((errors or lines or ["pip failed"])[-1].strip()[:200])
    return out


def install(p: Pack, *, progress=None, cancel=None, stage=None) -> Path:
    """The wheels through net.download() (resumed from a part), then pip
    with no network into the pack's `site`, then the record beside it
    and the wheels deleted. Raises DownloadError (net's reasons) or
    InstallError. Returns the site folder."""
    import shutil

    p.wheels_dir.mkdir(parents=True, exist_ok=True)
    total = p.bytes
    base = 0
    if stage is not None:
        stage("downloading")
    for w in p.wheels:
        dest = p.wheels_dir / w.filename
        if not (dest.exists() and dest.stat().st_size == w.size):
            net.download(w.url, dest, PURPOSE, size=w.size, sha256=w.sha256,
                         progress=progress, cancel=cancel, base=base, total=total)
        base += w.size
        if progress is not None:
            progress(base, total)
    if stage is not None:
        stage("installing")
    requirements = p.folder / "requirements.txt"
    requirements.write_text(requirements_text(p), encoding="utf-8")
    if p.site.exists():
        shutil.rmtree(p.site, ignore_errors=True)
    _run_pip(p, requirements)
    p.record.write_text(json.dumps({
        "pack": p.name, "versions": p.versions,
        "installed_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "app_version": _app_version(),
    }, indent=2) + "\n", encoding="utf-8")
    shutil.rmtree(p.wheels_dir, ignore_errors=True)
    requirements.unlink(missing_ok=True)
    clear_failure(p.name)
    log.info("packs: %s installed (%s) in %s", p.name,
             ", ".join(f"{k} {v}" for k, v in p.versions.items()), p.site)
    return p.site


def _app_version() -> str:
    try:
        import version
        return version.VERSION
    except Exception:                                        # noqa: BLE001
        return ""


def remove(name: str) -> bool:
    """The whole pack folder; the failure note with it."""
    import shutil

    folder = paths.PACKS_DIR / name
    clear_failure(name)
    if not folder.exists():
        return False
    shutil.rmtree(folder, ignore_errors=True)
    return not folder.exists()


# ------------------------------------------------------------- activating

_active: set[str] = set()


def dll_dirs(p: Pack) -> list[str]:
    """The pack's `nvidia\\*\\bin` folders, sorted — what the DLL search
    path needs for cuBLAS and cuDNN."""
    root = p.site / "nvidia"
    if not root.is_dir():
        return []
    return [str(d) for d in sorted(root.glob("*/bin")) if d.is_dir()]


def activate(name: str) -> bool:
    """Make the pack importable / loadable in this process. True when
    the pack is there (ok or stale) and was put on the path; False in
    the checkout, for a missing pack, or for one written down as
    failed. Idempotent."""
    if paths.PORTABLE or name in _active:
        return name in _active
    if state(name) not in ("ok", "stale") or failure(name):
        return False
    p = pack(name)
    if p is None:
        return False
    if name == "gpu":
        found = dll_dirs(p)
        if not found:
            return False
        for bin_dir in found:
            try:
                os.add_dll_directory(bin_dir)
            except OSError:
                pass
        os.environ["PATH"] = os.pathsep.join(
            dict.fromkeys(found + os.environ.get("PATH", "").split(os.pathsep)))
        log.debug("packs: %d CUDA library dirs from the gpu pack", len(found))
    else:
        site = str(p.site)
        if site not in sys.path:
            sys.path.append(site)
    _active.add(name)
    return True


# ----------------------------------------------------------------- the step

TEXT = {
    "gpu": {
        "title": "מהירות עם הכרטיס הגרפי",
        "body": ("נמצא כרטיס אנבידיה. כדי שהתמלול ירוץ עליו — מהר פי כמה עשרות מאשר על המעבד — "
                 "צריך להוריד פעם אחת את ספריות החישוב של אנבידיה: {size} מהמאגר של פייתון, "
                 "החבילות של אנבידיה עצמה, לתיקייה של דסק-איט. הרישיון של אנבידיה בקישורים למטה."),
        "done": "הספריות הותקנו. מהפעם הבאה התמלול רץ על הכרטיס.",
    },
    "skin": {
        "title": "המראה המצויר",
        "body": ("החלונות של דסק-איט יודעים להיראות טוב יותר עם ספרייה אחת קטנה ({size}). "
                 "בלי זה הכל עובד, רק במראה הפשוט."),
        "done": "הספרייה הותקנה.",
    },
}


def step(p: Pack, installer=None) -> steps.Step:
    words = TEXT.get(p.name, TEXT["skin"])
    work = installer or install
    return steps.Step(
        title=words["title"], body=words["body"].format(size=human(p.bytes)),
        size_line=size_line(p), total=p.bytes, work=lambda **kw: work(p, **kw),
        links=list(p.licenses), button="Install", said={"done": words["done"]},
    )


def wanted(cfg, facts: dict | None) -> bool:
    """Does this start offer the GPU pack? An installed copy, the switch
    on, an NVIDIA card with a driver new enough, and no pack yet (or a
    stale one)."""
    if paths.PORTABLE or facts is None or not cfg.setup.offer_gpu_pack:
        return False
    if int(facts.get("cuda_devices") or 0) < 1 or not facts.get("driver_ok"):
        return False
    return state("gpu") in ("missing", "stale")


def decline(name: str) -> None:
    """[Not now] at start: the person's choice, into settings.toml; the
    Speed page keeps a one-line offer (chapter 9)."""
    if name == "gpu":
        try:
            config_mod.save({"setup.offer_gpu_pack": False})
        except Exception:                                    # noqa: BLE001
            log.debug("packs: the decline was not written", exc_info=True)


def offer(name: str, installer=None) -> str:
    """The step for `name`: `done`, `declined` ([Not now], written
    down), or `later`. Never raises."""
    p = pack(name)
    if p is None:
        log.warning("packs: %s is not in packs.lock — nothing to offer", name)
        return "later"
    outcome = steps.show(step(p, installer))
    if outcome == "declined":
        decline(name)
    return outcome


# ------------------------------------------------------------- the owner

def _pypi_wheel(name: str, version: str) -> Wheel:
    """PyPI's record of the wheel the product runs — through net.py."""
    status, _h, body = net.request("GET", f"https://pypi.org/pypi/{name}/{version}/json",
                                   PURPOSE, timeout_s=30)
    if status != 200:
        raise RuntimeError(f"PyPI answered {status} for {name} {version}")
    data = json.loads(body.decode("utf-8"))
    for f in data.get("urls") or []:
        fn = str(f.get("filename") or "")
        if not fn.endswith(".whl"):
            continue
        if PLATFORM not in fn and not fn.endswith("-none-any.whl"):
            continue
        if not any(f"-{tag}-" in fn or f"-{tag}-none" in fn for tag in TAGS) \
                and not fn.endswith("py3-none-any.whl"):
            continue
        return Wheel(name, version, fn, str(f["url"]), int(f["size"]),
                     str(f["digests"]["sha256"]).lower())
    raise RuntimeError(f"no {PLATFORM} wheel for {name} {version} on PyPI")


def lock_pack(name: str) -> Pack:
    """The pack from the versions THIS interpreter holds (the owner's
    venv) and PyPI's metadata for those exact files."""
    from importlib import metadata

    wheels = []
    for dist in PINS[name]:
        wheels.append(_pypi_wheel(dist, metadata.version(dist)))
    return Pack(name, tuple(wheels), tuple(LICENSES.get(name, [])))


def _main(argv: list[str]) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="DeskIT's pack lock and pack folders.")
    parser.add_argument("--lock", action="store_true",
                        help="write packs.lock from this venv's versions and PyPI")
    parser.add_argument("--state", metavar="NAME", help="print the pack's standing")
    parser.add_argument("--install", metavar="NAME", help="run the pack's step window")
    parser.add_argument("--remove", metavar="NAME")
    args = parser.parse_args(argv)
    if args.lock:
        packs = [lock_pack(n) for n in NAMES]
        path = write_lock(packs)
        for p in packs:
            print(f"{p.name}: {', '.join(w.filename for w in p.wheels)} — {human(p.bytes)}")
        print(f"wrote {path}")
        return 0
    if args.state:
        print(standing(args.state))
        return 0
    if args.install:
        print(offer(args.install))
        return 0
    if args.remove:
        print("removed" if remove(args.remove) else "nothing to remove")
        return 0
    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
