"""The skin: everything this app looks like, in one folder you can delete.

DELETING THIS RESTORES THE OLD LOOK EXACTLY. That is the whole design
constraint, and it is why the hooks in the rest of the app are shaped the
way they are. Nothing outside this folder was rewritten — four files gained
a guarded early return that reads

    try:
        import skin
    except Exception:
        skin = None
    ...
    if skin is not None and skin.on():
        return skin.something(...)

and the original body sits underneath, untouched. Remove the folder and
every one of those imports fails, every hook goes to None, and the app
paints itself with the code it always had. There is no migration, no
config to unset, and no half state.

Three ways to turn it off, in increasing order of permanence:

    set HD_SKIN=0              for one run
    ENABLED = False, below     for good, keeping the code
    rmdir /s skin              gone

WHAT IT NEEDS. skia-python, for the one thing Tk and Pillow together
cannot do: antialiased vector light composited per-pixel over the live
desktop. If the import fails the skin reports off and the app runs on its
original path, so a missing wheel is a downgrade and never a crash.
"""
from __future__ import annotations

import logging
import os

ENABLED = True

_log = logging.getLogger("app")
_state = {"checked": False, "ok": False}


def on() -> bool:
    """Is the skin live? Cached: this is called on hot paths.

    Answers False rather than raising for every reason it could fail —
    switched off, no skia, no Windows — because a decoration that can take
    the app down with it is not a decoration.
    """
    if _state["checked"]:
        return _state["ok"]
    _state["checked"] = True
    ok = False
    try:
        if not ENABLED:
            _log.debug("skin: switched off in skin/__init__.py")
        elif os.environ.get("HD_SKIN", "1") in ("0", "off", "false", "no"):
            _log.info("skin: off (HD_SKIN)")
        else:
            import skia                    # noqa: F401
            from . import glass            # noqa: F401
            ok = True
    except Exception as e:
        _log.info("skin unavailable, using the original look: %r", e)
    _state["ok"] = ok
    return ok


def reset() -> None:
    """Forget the cached answer — for tests that toggle ENABLED."""
    _state["checked"] = False
    _state["ok"] = False


# --------------------------------------------------------------- palette
def repaint(namespace: dict) -> None:
    """Overwrite a module's colour constants in place.

    Called from the bottom of ui.py's palette block, before anything has
    imported a name out of it. `from ui import CARD` binds the value at
    import time, so this has to happen while ui.py is still executing —
    which is exactly where the hook sits.

    Only names the module already defines are touched. A palette that
    could INVENT a constant would let a typo here paint a widget that
    nobody has ever looked at.
    """
    if not on():
        return
    try:
        from .palette import UI_NAMES
        for name, value in UI_NAMES.items():
            if name in namespace:
                namespace[name] = value
    except Exception:
        _log.debug("skin: could not repaint a palette", exc_info=True)


# ------------------------------------------------------------- the boot
def splash_run(splash) -> bool:
    """Take over overlay.Splash's thread. False means "not mine, carry on".

    Given the Splash object itself rather than its arguments so the queue,
    the closing Event and the finish() protocol stay exactly where they
    were: the skin swaps the PICTURE, never the lifecycle that main.py and
    three tests depend on.
    """
    if not on():
        return False
    try:
        from .boot import run
        run(splash)
        return True
    except Exception:
        _log.info("skin splash failed, falling back", exc_info=True)
        return False


def dot_run(dot) -> bool:
    """The same trade for the status dot."""
    if not on():
        return False
    try:
        from .dot import run
        run(dot)
        return True
    except Exception:
        _log.info("skin dot failed, falling back", exc_info=True)
        return False


def hint_run(card) -> bool:
    """And for the hint card, whose fallback is a real one.

    The splash and the dot fall back to a picture that is merely older.
    This one falls back to the same card without the glass — Tk cannot
    composite per-pixel alpha over the desktop at all — so returning False
    here is a downgrade in looks and nothing else. That is the point of
    the folder being deletable.
    """
    if not on():
        return False
    try:
        from .hint import run
        run(card)
        return True
    except Exception:
        _log.info("skin hint card failed, falling back", exc_info=True)
        return False


def paint_wave(card) -> bool:
    """The microphone wave in the ask-the-screen card.

    NOT NAMED `wave`, and that is the whole point of the name. Python binds
    a submodule onto its parent package the first time it is imported, so a
    hook called wave() whose body says `from .wave import paint` OVERWRITES
    ITSELF on its first call: skin.wave stops being this function and
    becomes skin\\wave.py. The second call then raises "'module' object is
    not callable" — from the CALL, outside the try/except below, where the
    "a decoration cannot take the app down" promise above cannot reach it.

    It cost the ask-the-screen card. This runs on a 15 ms tick and only
    while a dictation is in flight, so the card died on the second tick of
    every question the owner tried to SPEAK into it — the window closing
    the instant he started talking (four tracebacks in app.log,
    2026-08-27). splash_run and dot_run avoid the trap by the same means:
    a name no file in this folder can take. tests.py asserts it for every
    hook so the next one cannot re-learn this.
    """
    if not on():
        return False
    try:
        from .wave import paint
        return paint(card)
    except Exception:
        _log.debug("skin wave failed", exc_info=True)
        return False
