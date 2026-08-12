"""Global push-to-talk hotkey + synthetic key sending, via raw Win32
(ctypes): WH_KEYBOARD_LL for listening, SendInput for the paste chord.

Why not the `keyboard` library (the original plan): its event delivery
proved unobservable in this environment while a raw hook demonstrably
worked, and the raw hook exposes the LLKHF_INJECTED flag, which allows a
clean self-paste rule with no timing heuristics:

- The HOTKEY triggers whether pressed physically or injected — automated
  tests (and tools like AutoHotkey) can drive it.
- Only PHYSICAL other-key presses abort a recording. Our own synthetic
  paste chord is injected, so it can never abort a recording the user just
  started. (Known corner: over RDP all input arrives injected, so the
  abort-on-combo rule is inert there.)

PTTStateMachine is pure logic (unit-testable). HookThread runs the OS hook
and its message pump.

The hook swallows exactly one thing — the latch key, and only while it is
acting as the latch (see PTTStateMachine). Everything else, including the
hotkey itself, passes through to the focused app untouched.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as w
import threading
from typing import Callable

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

IDLE = "idle"
RECORDING = "recording"
LATCHED = "latched"

# ---------------------------------------------------------------- key names

_VK: dict[str, int] = {
    "ctrl": 0x11, "left ctrl": 0xA2, "right ctrl": 0xA3,
    "shift": 0x10, "left shift": 0xA0, "right shift": 0xA1,
    "alt": 0x12, "left alt": 0xA4, "right alt": 0xA5,
    "win": 0x5B, "left win": 0x5B, "right win": 0x5C, "menu": 0x5D,
    "space": 0x20, "enter": 0x0D, "tab": 0x09, "esc": 0x1B,
    "backspace": 0x08, "caps lock": 0x14, "scroll lock": 0x91,
    "num lock": 0x90, "pause": 0x13, "print screen": 0x2C,
    "insert": 0x2D, "delete": 0x2E, "home": 0x24, "end": 0x23,
    "page up": 0x21, "page down": 0x22,
    "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27,
}
for _i in range(1, 25):  # f1..f24
    _VK[f"f{_i}"] = 0x70 + _i - 1
for _c in "abcdefghijklmnopqrstuvwxyz":
    _VK[_c] = 0x41 + ord(_c) - ord("a")
for _d in "0123456789":
    _VK[_d] = 0x30 + ord(_d) - ord("0")

_VK_NAMES = {vk: name for name, vk in _VK.items()}  # last write wins — fine

# Keys whose scan code needs KEYEVENTF_EXTENDEDKEY when synthesized.
_EXTENDED = {0xA3, 0xA5, 0x2D, 0x2E, 0x21, 0x22, 0x23, 0x24,
             0x25, 0x26, 0x27, 0x28, 0x5B, 0x5C, 0x5D, 0x6F, 0x90, 0x2C}


def vk_for(name: str) -> int:
    """Friendly key name -> virtual-key code. Raises ValueError."""
    key = name.strip().lower()
    if key not in _VK:
        raise ValueError(
            f"unknown key name {name!r}. Use one of: right ctrl, left ctrl, "
            f"right shift, right alt, f1..f24, a..z, 0..9, insert, home, "
            f"page up/down, caps lock, scroll lock, pause, ...")
    return _VK[key]


def vk_name(vk: int) -> str:
    return _VK_NAMES.get(vk, f"vk 0x{vk:02X}")


def parse_chord(chord: str) -> list[int]:
    """'ctrl+v' -> [0x11, 0x56]. Raises ValueError on unknown or malformed
    chords ('ctrl+' would otherwise silently paste nothing)."""
    parts = [p.strip() for p in chord.split("+")]
    if not parts or any(not p for p in parts):
        raise ValueError(f"malformed chord {chord!r}")
    return [vk_for(p) for p in parts]


# ------------------------------------------------------------ state machine

class PTTStateMachine:
    """Decides what each key event means for push-to-talk.

    More than one hotkey may be registered, each bound to a language. That
    is deliberately an explicit choice rather than automatic detection:
    language detection measured badly on real microphone audio (a Hebrew
    sentence scored "English 0.57"), whereas a dedicated key is always
    right.

    - a hotkey down while idle      -> on_start(language)
    - that hotkey down while recording -> ignored (Windows auto-repeat)
    - that hotkey up while recording   -> on_stop(language)
    - any other PHYSICAL key-down while recording -> on_abort(reason):
      the user is typing a combo (e.g. holding Right Ctrl for Ctrl+C),
      not dictating. Injected key-downs (our own paste chord, test
      drivers) never abort. Key-UPs of other keys never abort either.
      The OTHER hotkey counts as "any other key" — pressing both aborts
      rather than silently picking a language.

    `taps` registers keys that ACT on a press instead of being held, for
    things that are not recordings (translating what is already at the
    cursor). A tap key fires once per physical press — auto-repeat is
    swallowed — and only while idle: pressed mid-recording it falls
    through to the abort rule above, like any other key.

    `latch_vk` is the escape hatch from holding. Holding a key is fine for
    a sentence and miserable for a paragraph, so tapping the latch key
    mid-recording LOCKS the recording on: the hotkey can then be released
    and the recording keeps running until the latch key (or a hotkey) is
    tapped again. While latched:

    - other keys do NOT abort. In hold mode a stray key means "the user is
      typing a combo, not dictating"; latched, their hands are free by
      design, and letting one stray keystroke destroy several minutes of
      speech would be far worse than recording a few extra seconds.
    - `cancel_vk` (Esc) discards the recording — the deliberate way out.

    The latch key is the one key this class asks the hook to SWALLOW, and
    only for the presses it actually consumes: it usually has a job of its
    own in the focused app (an arrow key moves the caret, and the caret is
    exactly where the transcript is about to be pasted). While idle it is
    left alone completely.

    Callbacks run on the hook thread — keep them fast.
    """

    def __init__(self, hotkeys: int | dict[int, str],
                 on_start: Callable[[str], None],
                 on_stop: Callable[[str], None],
                 on_abort: Callable[[str], None],
                 taps: dict[int, str] | None = None,
                 on_tap: Callable[[str], None] | None = None,
                 latch_vk: int | None = None,
                 on_latch: Callable[[], None] | None = None,
                 cancel_vk: int | None = 0x1B):   # Esc
        # A bare vk keeps the original single-hotkey form working.
        self._hotkeys = ({hotkeys: "he"} if isinstance(hotkeys, int)
                         else dict(hotkeys))
        if not self._hotkeys:
            raise ValueError("at least one hotkey is required")
        self._taps = dict(taps or {})
        clash = set(self._taps) & set(self._hotkeys)
        if clash:
            raise ValueError(
                f"{vk_name(next(iter(clash)))} is both a hold hotkey and a "
                f"tap key — one key cannot mean two things")
        if latch_vk is not None and latch_vk in (set(self._hotkeys)
                                                 | set(self._taps)):
            raise ValueError(
                f"{vk_name(latch_vk)} is already a hotkey or tap key — one "
                f"key cannot mean two things")
        if self._taps and on_tap is None:
            raise ValueError("taps were registered without an on_tap handler")
        if latch_vk is not None and on_latch is None:
            raise ValueError("a latch key was registered without an on_latch "
                             "handler")
        self._on_start = on_start
        self._on_stop = on_stop
        self._on_abort = on_abort
        self._on_tap = on_tap
        self._on_latch = on_latch
        self._latch_vk = latch_vk
        self._cancel_vk = cancel_vk
        self._state = IDLE
        self._active_vk: int | None = None
        self._tap_held: set[int] = set()
        self._down: set[int] = set()      # physically-down keys, for repeat
        self._swallow_latch_up = False
        self._lock = threading.Lock()

    @property
    def state(self) -> str:
        return self._state

    @property
    def language(self) -> str | None:
        """Language of the recording in progress, if any."""
        vk = self._active_vk
        return self._hotkeys.get(vk) if vk is not None else None

    def handle(self, event_type: str, vk: int, injected: bool) -> bool:
        """Feed one key event. Returns True when the hook should SWALLOW it
        (only ever the latch key, and only for presses this consumed)."""
        fire: Callable[[], None] | None = None
        swallow = False
        with self._lock:
            # Auto-repeat bookkeeping, done whatever the state: a tap key
            # pressed mid-recording aborts without being marked held, and
            # must still be armed again by its release.
            was_down = vk in self._down
            if event_type == "up":
                self._tap_held.discard(vk)
                self._down.discard(vk)
                if vk == self._latch_vk and self._swallow_latch_up:
                    # Its key-DOWN was swallowed; releasing it must not
                    # reach the app on its own either.
                    self._swallow_latch_up = False
                    swallow = True
            else:
                self._down.add(vk)
                if vk == self._latch_vk and was_down and self._swallow_latch_up:
                    # Auto-repeat of a press whose key-down we swallowed —
                    # holding it down must not leak arrows into the app.
                    swallow = True

            if self._state == IDLE:
                if vk in self._hotkeys and event_type == "down":
                    self._state = RECORDING
                    self._active_vk = vk
                    language = self._hotkeys[vk]
                    fire = lambda: self._on_start(language)
                elif vk in self._taps and event_type == "down" \
                        and vk not in self._tap_held:
                    self._tap_held.add(vk)   # ignore Windows auto-repeat
                    action = self._taps[vk]
                    fire = lambda: self._on_tap(action)
                # The latch key is inert while idle — it keeps its normal
                # job in whatever app has focus.
            elif self._state == RECORDING:
                if vk == self._active_vk:
                    if event_type == "up":
                        self._state = IDLE
                        language = self._hotkeys[vk]
                        self._active_vk = None
                        fire = lambda: self._on_stop(language)
                    # down = auto-repeat while held: ignore
                elif vk == self._latch_vk and event_type == "down":
                    # `was_down` means it was already held before the
                    # recording started (the user was holding an arrow):
                    # not a deliberate latch, so leave their input alone.
                    if not was_down:
                        self._state = LATCHED
                        self._swallow_latch_up = True
                        swallow = True
                        fire = self._on_latch
                elif event_type == "down" and not injected:
                    self._state = IDLE
                    self._active_vk = None
                    reason = f"'{vk_name(vk)}' pressed mid-hold"
                    fire = lambda: self._on_abort(reason)
            elif self._state == LATCHED:
                # `not was_down` is load-bearing for BOTH: the hotkey is
                # still physically held at the moment of latching, and
                # Windows keeps auto-repeating its key-down — without this
                # the recording would stop the instant it locked.
                finish = not was_down and (vk == self._latch_vk
                                           or vk in self._hotkeys)
                if finish and event_type == "down":
                    self._state = IDLE
                    language = self._hotkeys[self._active_vk]
                    self._active_vk = None
                    fire = lambda: self._on_stop(language)
                    if vk == self._latch_vk:
                        self._swallow_latch_up = True
                        swallow = True
                elif vk == self._cancel_vk and event_type == "down" \
                        and not injected:
                    self._state = IDLE
                    self._active_vk = None
                    fire = lambda: self._on_abort("esc pressed while locked")
                # Anything else is ignored on purpose: latched, the user's
                # hands are free, and a stray keystroke must not throw away
                # minutes of speech.
        if fire is not None:
            fire()  # outside the lock
        return swallow


# ------------------------------------------------------------- the OS hook

WH_KEYBOARD_LL = 13
LLKHF_INJECTED = 0x10
WM_KEYDOWN, WM_KEYUP = 0x0100, 0x0101
WM_SYSKEYDOWN, WM_SYSKEYUP = 0x0104, 0x0105
WM_QUIT = 0x0012

LRESULT = ctypes.c_ssize_t
_HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, w.WPARAM, w.LPARAM)

user32.SetWindowsHookExW.argtypes = [ctypes.c_int, _HOOKPROC, w.HINSTANCE,
                                     w.DWORD]
user32.SetWindowsHookExW.restype = w.HHOOK
user32.CallNextHookEx.argtypes = [w.HHOOK, ctypes.c_int, w.WPARAM, w.LPARAM]
user32.CallNextHookEx.restype = LRESULT
user32.UnhookWindowsHookEx.argtypes = [w.HHOOK]


class _KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [("vkCode", w.DWORD), ("scanCode", w.DWORD),
                ("flags", w.DWORD), ("time", w.DWORD),
                ("dwExtraInfo", ctypes.c_size_t)]


class HookThread:
    """Runs WH_KEYBOARD_LL + message pump; feeds a PTTStateMachine.

    Suppresses only what the state machine asks it to — the latch key, for
    the presses that lock and unlock a recording. Everything else passes
    through to the focused app, the hotkey included (a bare Ctrl
    press/release is harmless in ordinary apps).
    """

    def __init__(self, machine: PTTStateMachine):
        self._machine = machine
        self._thread: threading.Thread | None = None
        self._thread_id: int | None = None
        self._hook = None
        self._ready = threading.Event()
        self._error: int | None = None
        # Pin the callback object — if it gets GC'd, the process crashes.
        self._proc = _HOOKPROC(self._on_event)

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name="keyboard-hook")
        self._thread.start()
        self._ready.wait(timeout=5)
        if self._error is not None:
            raise OSError(f"SetWindowsHookEx failed (WinError "
                          f"{self._error}) — cannot listen for the hotkey")
        if self._hook is None:
            raise OSError("keyboard hook thread did not start in time")

    def stop(self) -> None:
        if self._thread_id is not None:
            user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
            self._thread.join(timeout=2)

    def _run(self) -> None:
        self._thread_id = kernel32.GetCurrentThreadId()
        hook = user32.SetWindowsHookExW(WH_KEYBOARD_LL, self._proc, None, 0)
        if not hook:
            self._error = ctypes.get_last_error()
            self._ready.set()
            return
        self._hook = hook
        self._ready.set()
        msg = w.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        user32.UnhookWindowsHookEx(hook)

    def _on_event(self, n_code: int, w_param: int, l_param: int) -> int:
        if n_code >= 0:
            try:
                ks = ctypes.cast(l_param,
                                 ctypes.POINTER(_KBDLLHOOKSTRUCT)).contents
                event = None
                if w_param in (WM_KEYDOWN, WM_SYSKEYDOWN):
                    event = "down"
                elif w_param in (WM_KEYUP, WM_SYSKEYUP):
                    event = "up"
                if event and self._machine.handle(
                        event, ks.vkCode, bool(ks.flags & LLKHF_INJECTED)):
                    return 1   # swallowed: never reaches the focused app
            except Exception:
                pass  # never blow up inside the OS hook
        return user32.CallNextHookEx(None, n_code, w_param, l_param)


# --------------------------------------------------------------- SendInput

KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
MAPVK_VK_TO_VSC = 0
INPUT_KEYBOARD = 1


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", w.WORD), ("wScan", w.WORD), ("dwFlags", w.DWORD),
                ("time", w.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class _INPUT(ctypes.Structure):
    class _U(ctypes.Union):
        _fields_ = [("ki", _KEYBDINPUT), ("_pad", ctypes.c_byte * 32)]
    _anonymous_ = ("u",)
    _fields_ = [("type", w.DWORD), ("u", _U)]


def _key_input(vk: int, up: bool) -> _INPUT:
    flags = KEYEVENTF_KEYUP if up else 0
    if vk in _EXTENDED:
        flags |= KEYEVENTF_EXTENDEDKEY
    scan = user32.MapVirtualKeyW(vk, MAPVK_VK_TO_VSC)
    item = _INPUT(type=INPUT_KEYBOARD)
    item.ki = _KEYBDINPUT(vk, scan, flags, 0, 0)
    return item


def _send(seq: list[_INPUT]) -> None:
    if not seq:
        return
    arr = (_INPUT * len(seq))(*seq)
    sent = user32.SendInput(len(seq), arr, ctypes.sizeof(_INPUT))
    if sent != len(seq):
        raise OSError(f"SendInput injected {sent}/{len(seq)} events "
                      f"(WinError {ctypes.get_last_error()})")


def send_chord(chord: str) -> None:
    """Press a chord like 'ctrl+v': downs in order, ups in reverse."""
    vks = parse_chord(chord)
    seq = [_key_input(vk, up=False) for vk in vks]
    seq += [_key_input(vk, up=True) for vk in reversed(vks)]
    _send(seq)


def send_key_times(name: str, times: int) -> None:
    """Tap one key N times — used to erase the placeholder before the real
    transcript is pasted over it. Sent as a single SendInput batch so no
    other input can interleave between the taps."""
    if times <= 0:
        return
    vk = vk_for(name)
    seq: list[_INPUT] = []
    for _ in range(times):
        seq.append(_key_input(vk, up=False))
        seq.append(_key_input(vk, up=True))
    _send(seq)
