"""The parts DeskIT downloads by itself, in the background.

The owner, walking the Store copy on 2026-10-03 (item 6 of that walk):
the install was meant to bring every part, and the Store copy stopped
on a page with a [Download] button instead. Shown the page redrawn, his
answer was that nobody should see such a page at all: every copy — the
Store's, winget's, the website's — gets every part this computer can
use, downloaded in the background, and the one sign of it is a slim bar
with a short English label at the top of the wizard.

So this is the queue with no face of its own. The wizard starts it the
moment it opens and draws the strip from it (firstrun.Wizard); what is
still coming when the person presses Start goes on downloading after
the wizard closes, on a thread of the running app (main.App); and an
installed copy that starts with a part missing — the wizard closed
early, the network gone halfway — resumes it the same way, where the
start used to put up a window with [Download] and [Not now].

What a part IS stays where it was: models.py (the Hebrew model, the
English detector) and packs.py (NVIDIA's libraries, PyAV) — their
locks, their hashes, their `.part` resume, their `.complete`. Which
parts this computer can use is `wanted()`: the Hebrew model always, the
Recording pack always, NVIDIA's libraries with a card the probe says
can run them, the English detector with the card the full tier needs.
A pack the person removed by hand on the desk (`[setup]
offer_gpu_pack` / `offer_recording_pack` = false, packs.decline) stays
removed; installing it by hand turns it back on (packs.accept).

A run that fails is tried again by itself: without a connection, or
while another downloader holds the part (part_lock), every RETRY_S[-1]
seconds for as long as the queue lives; any other failure len(RETRY_S)
times — a file that keeps failing its hash is not fetched forever.
"""
from __future__ import annotations

import contextlib
import logging
import threading
import time
from pathlib import Path

import steps

log = logging.getLogger("app")

#: The order a queue runs in: the model first (the wizard's sentence page
#: waits for it), the rest after.
KINDS = ("model", "pack", "detector", "recording")

#: The plain name of each part — the installer's own words (DeskIT.iss,
#: DlItem_*), for the wizard's strip and the desk's row.
NAMES = {"model": "Hebrew speech", "pack": "Faster with your NVIDIA card",
         "detector": "English detection", "recording": "Screen recording"}

#: Seconds before a stopped run is tried again: the first try, the
#: second, then every later one.
RETRY_S = (10.0, 30.0, 60.0)

#: The file beside a part's folder whose first byte one writer holds.
LOCK_NAME = ".downloading"


class Busy(Exception):
    """Another downloader (a second process: the desk's own button, a
    --setup run) is writing this part right now. `reason` is net's
    vocabulary, so a steps.StepRun reads it like any download error."""

    reason = "busy"


@contextlib.contextmanager
def part_lock(folder: Path):
    """Hold the part in `folder` for one writer, across processes.

    Until 2026-10-03 nothing could start a second writer on purpose:
    the model downloaded in a window that blocked the start. With the
    parts downloading on the app's own thread, the desk's Download
    button, a --setup run or a second copy's wizard can reach the same
    `.part` while it is open — and two writers appending to one part
    make a file that fails its hash at the end. An OS byte lock on a
    file in the folder (msvcrt.locking), released by Windows when the
    holder dies, so a crash wedges nothing."""
    import msvcrt
    folder.parent.mkdir(parents=True, exist_ok=True)
    # beside the folder, not in it: the model's folder is what the
    # decoder loads, and a stray file there is nobody's business
    handle = (folder.parent / f"{folder.name}{LOCK_NAME}").open("a+b")
    try:
        try:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            raise Busy(f"another DeskIT is downloading {folder.name} right now") from None
        try:
            yield
        finally:
            handle.seek(0)
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            except OSError:
                pass
    finally:
        handle.close()


def wanted(cfg, facts: dict | None) -> dict:
    """{kind: thing} for every part this copy still lacks and can use
    (models.Entry for the two models, packs.Pack for the two packs).
    Empty on a portable copy (D4: the global cache, as always) and when
    everything is on the disk."""
    import paths
    out: dict = {}
    if paths.PORTABLE:
        return out
    import models
    import packs
    if cfg.backend == "local" and models.state(cfg.local.model) != "ready":
        e = models.entry(cfg.local.model)
        if e is not None:
            out["model"] = e
    if packs.wanted(cfg, facts):
        p = packs.pack("gpu")
        if p is not None:
            out["pack"] = p
    english = english_model(cfg)
    if (card_tier(facts) == "gpu" and english and cfg.backend == "local"
            and models.state(english) != "ready"):
        e = models.entry(english)
        if e is not None:
            out["detector"] = e
    # PyAV (13.4): the record key, the photo key and the phone's audio.
    # Always — the owner, 2026-09-19: "the software comes with everything"
    # — unless the person removed it by hand (packs.decline; its FFmpeg
    # is a GPL build, D24, and that is theirs to turn down).
    setup = getattr(cfg, "setup", None)
    if (getattr(setup, "offer_recording_pack", True)
            and packs.state("recording") in ("missing", "stale")):
        p = packs.pack("recording")
        if p is not None:
            out["recording"] = p
    return out


def card_tier(facts: dict | None) -> str:
    """The tier the CARD earns once NVIDIA's libraries are there — on a
    first start the pack is not installed yet and hardware.tier_for says
    cpu until it is. "" without a usable card."""
    facts = facts or {}
    if int(facts.get("cuda_devices") or 0) < 1:
        return ""
    if not facts.get("driver_ok", True):
        return ""
    import hardware
    vram = int(facts.get("vram_mb") or 0)
    if vram and vram < hardware.GPU_SMALL_MB:
        return ""
    if vram and vram < hardware.GPU_MB:
        return "gpu-small"
    return "gpu"


def english_model(cfg) -> str:
    """local.english_model as the defaults and settings.toml say — the
    machine layer may hold "" for the cpu tier (hardware.DERIVED), and on
    a first start the pack is not there yet, so the tier says cpu: the
    name is read from the layers UNDER it, never from the layer the tier
    wrote."""
    try:
        import config as config_mod
        import paths
        chosen = config_mod.read_settings(paths.SETTINGS_FILE)
        if "local.english_model" in chosen:
            return str(chosen["local.english_model"] or "")
        return str(config_mod.defaults_flat().get("local.english_model") or "")
    except Exception:                                      # noqa: BLE001
        local = getattr(cfg, "local", None)
        return str(getattr(local, "english_model", "") or "")


def step_for(kind: str, thing) -> steps.Step:
    """The work of one part: models.py's download or packs.py's install."""
    import models
    import packs
    if kind in ("pack", "recording"):
        return packs.step(thing)
    if kind == "detector":
        return models.step(thing, words=models.DETECTOR_TEXT)
    return models.step(thing)


class Queue:
    """The parts of one copy, downloaded one after another.

    `pump()` moves it — from the wizard's Tk tick, or from the app's
    thread (`carry_on`) — and is the only thing that changes it; the
    other methods only read, so the desk's status poll can ask at any
    time. `on_landed(kind)` is told each part that arrived, on the thread
    that pumped it."""

    def __init__(self, things: dict, stepper=None, on_landed=None):
        stepper = stepper or step_for
        self.runs: dict[str, steps.StepRun] = {}
        for kind in KINDS:
            thing = things.get(kind)
            if thing is None:
                continue
            try:
                self.runs[kind] = steps.StepRun(stepper(kind, thing))
            except Exception:                                # noqa: BLE001
                # a lock entry this build cannot read is a part left out,
                # never a wizard or an app that does not start
                log.warning("downloads: %s could not be prepared", kind, exc_info=True)
        self.order = [k for k in KINDS if k in self.runs]
        self.active = -1
        self.on_landed = on_landed
        self._tries = 0                  # stops of the current part: the backoff's step
        self._failures = 0               # of those, the ones that were not offline/busy
        self._retry_at = 0.0
        self.gave_up = False

    # ------------------------------------------------------------ actions
    def start(self) -> bool:
        """The first part starts (once). False with nothing to do."""
        if self.active >= 0 or not self.order:
            return False
        return self._start_next()

    def _start_next(self) -> bool:
        i = self.active + 1
        while i < len(self.order):
            run = self.runs[self.order[i]]
            if run.state != "done":
                self.active, self._tries, self._failures = i, 0, 0
                run.start()
                log.info("downloads: %s started (%d of %d)",
                         self.order[i], i + 1, len(self.order))
                return True
            i += 1
        self.active = len(self.order) - 1
        return False

    def pump(self, now: float | None = None) -> list[tuple[str, str]]:
        """What the threads reported, applied: [(kind, end word)] that
        landed in this call. A part done starts the next; a part stopped
        is started again after RETRY_S (offline: for as long as it takes;
        anything else: len(RETRY_S) times, then the queue gives up and
        says so — the next start tries again)."""
        now = time.monotonic() if now is None else now
        landed: list[tuple[str, str]] = []
        for kind in self.order:
            run = self.runs[kind]
            if run.state == "running":
                for word in run.pump():
                    landed.append((kind, word))
        for kind, word in landed:
            if word == "done":
                log.info("downloads: %s landed", kind)
                if self.on_landed is not None:
                    try:
                        self.on_landed(kind)
                    except Exception:                        # noqa: BLE001
                        log.warning("downloads: after %s landed", kind, exc_info=True)
                self._start_next()
            elif word in ("offline", "failed"):
                self._tries += 1
                # offline, or another downloader holding the part (Busy):
                # worth waiting for, however long; anything else has
                # len(RETRY_S) more tries before the queue gives up
                patient = word == "offline" or self.runs[kind].reason == Busy.reason
                if not patient:
                    self._failures += 1
                if self._failures > len(RETRY_S):
                    self.gave_up = True
                    log.warning("downloads: %s failed %d times — the next start "
                                "tries again", kind, self._failures)
                else:
                    wait = RETRY_S[min(self._tries, len(RETRY_S)) - 1]
                    self._retry_at = now + wait
        current = self.current
        if (current is not None and current.state in ("offline", "failed")
                and not self.gave_up and now >= self._retry_at):
            log.info("downloads: trying %s again", self.order[self.active])
            current.start()
        return landed

    def pause(self) -> None:
        """Every running part stops; its `.part` stays for the next start."""
        for run in self.runs.values():
            if run.running:
                run.pause()

    def join(self, timeout: float = 10.0) -> bool:
        """Wait for the work threads to end (after pause()). True when
        they did — a second writer must never meet a `.part` still open."""
        deadline = time.monotonic() + timeout
        for run in self.runs.values():
            thread = getattr(run, "_thread", None)
            if thread is not None and thread.is_alive():
                thread.join(max(0.0, deadline - time.monotonic()))
                if thread.is_alive():
                    return False
        return True

    # -------------------------------------------------------------- reads
    @property
    def current(self) -> steps.StepRun | None:
        if self.active < 0 or not self.order:
            return None
        return self.runs[self.order[min(self.active, len(self.order) - 1)]]

    @property
    def done(self) -> bool:
        return bool(self.order) and all(r.state == "done" for r in self.runs.values())

    @property
    def total(self) -> int:
        return sum(r.total for r in self.runs.values())

    @property
    def here(self) -> int:
        return sum(r.total if r.state == "done" else r.done_bytes
                   for r in self.runs.values())

    @property
    def fraction(self) -> float:
        total = self.total
        return min(1.0, self.here / total) if total else 1.0

    @property
    def state(self) -> str:
        """idle (not started), running, waiting (stopped, a retry is
        coming), failed (gave up), done."""
        if self.done:
            return "done"
        if self.active < 0:
            return "idle"
        if self.gave_up:
            return "failed"
        current = self.current
        if current is not None and current.running:
            return "running"
        return "waiting"

    @property
    def offline(self) -> bool:
        current = self.current
        return current is not None and current.state == "offline"

    def has(self, kind: str) -> bool:
        return kind in self.runs and self.runs[kind].state != "done"

    def status(self) -> dict:
        """For the app's status(): the desk draws its Home row from it."""
        current = self.current
        return {"state": self.state, "fraction": round(self.fraction, 3),
                "here": self.here, "total": self.total,
                "offline": self.offline,
                "part": self.order[self.active] if current is not None else "",
                "parts": {k: r.state for k, r in self.runs.items()}}


def carry_on(queue: Queue, every: float = 0.5, stop: threading.Event | None = None) -> threading.Thread:
    """Pump `queue` on a thread of its own until it is done or has given
    up — the app's half, after the wizard closed or at a start with a
    part missing. The thread is a daemon: quitting the app stops the
    work where it stands and the next start resumes it."""
    stop = stop or threading.Event()

    def loop() -> None:
        queue.start()
        while not stop.is_set():
            try:
                queue.pump()
            except Exception:                                # noqa: BLE001
                log.warning("downloads: the pump tripped", exc_info=True)
            if queue.state in ("done", "failed"):
                break
            stop.wait(every)
        log.info("downloads: the background queue ended (%s)", queue.state)

    thread = threading.Thread(target=loop, daemon=True, name="downloads")
    thread.start()
    return thread
