"""A stand-in for PyAV (`av`) on a copy that does not ship it.

DISTRIBUTION_PLAN.md 13.4, D24: the PyPI `av` wheel bundles an FFmpeg
built with x264 and x265 — a GPL build — and the installer ships no
GPL FFmpeg. faster-whisper imports `av` at the top of its audio.py
even though dictation never decodes anything with it (DeskIT hands
the model 16 kHz PCM as a numpy array, pcm.py), so this package sits
LAST on sys.path (`app\\vendor`, appended by main.py) and answers that
import. Anything that then actually USES av — screen recording, the
camera, a phone upload that is not WAV — gets one sentence naming the
Recording pack instead of a crash.

The hand-over. A real `av` earlier on sys.path wins by itself (the
checkout's venv; the wheelhouse would too if it ever carried one). A
real `av` that arrives LATER — the Recording pack, whose site
packs.activate() appends after this folder — is found on the first
attribute access: the stub looks along sys.path for another `av`
package, loads it in its own place in sys.modules, and hands the
attribute over. So `import av` at start and `av.open(...)` after the
pack landed both work without a restart.
"""
from __future__ import annotations

import importlib.util
import os
import sys

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))    # app\vendor
_real = None

MISSING = ("PyAV (av) is not installed: screen recording, the camera and "
           "non-WAV uploads need the Recording pack — Settings > Screen, or "
           "main.py --install-pack recording")


def _find_real():
    """Another `av` package on sys.path, if one is there."""
    for entry in list(sys.path):
        try:
            if not entry or os.path.abspath(entry) == _HERE:
                continue
            init = os.path.join(entry, "av", "__init__.py")
            if os.path.isfile(init):
                return init
        except (OSError, ValueError):
            continue
    return None


def _load_real():
    """Load the real package in this module's place. Its own submodule
    imports resolve through sys.modules["av"], which is set before its
    code runs, the way the import system does it."""
    global _real
    if _real is not None:
        return _real
    init = _find_real()
    if init is None:
        return None
    location = os.path.dirname(init)
    spec = importlib.util.spec_from_file_location(
        "av", init, submodule_search_locations=[location])
    module = importlib.util.module_from_spec(spec)
    sys.modules["av"] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules["av"] = sys.modules.get("av") or module
        raise
    _real = module
    return module


def __getattr__(name: str):
    real = _load_real()
    if real is not None:
        return getattr(real, name)
    raise ImportError(MISSING)


def is_stub() -> bool:
    """True while no real PyAV has been found — what pcm.py and
    server.py ask before trying a decoder."""
    return _load_real() is None
