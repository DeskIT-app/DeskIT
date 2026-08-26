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

The hook swallows two things and nothing else. The latch key, and only
while it is acting as the latch; and whatever `on_key_down` claims, which
is how the lookup box — a window that never takes focus and so never
receives a keystroke of its own — gets its Esc and its Ctrl+C. Everything
else, including the hotkey itself, passes through to the focused app
untouched. Both are PTTStateMachine's to explain.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as w
import threading
from typing import Callable, NamedTuple

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

# The two physical keys behind each unsided modifier VK.
_SIDES: dict[int, tuple[int, int]] = {
    0x11: (0xA2, 0xA3),      # ctrl  -> left, right
    0x10: (0xA0, 0xA1),      # shift
    0x12: (0xA4, 0xA5),      # alt
    # Windows has no unsided VK_WIN — both Win keys are already sided — so
    # the LEFT one stands for the group, the way 0x11 stands for ctrl. It
    # is the only entry here whose group id is also one of its sides, and
    # nothing downstream cares: side_down probes the pair, _MOD_GROUP maps
    # both to the group, and binding_name writes the group's own name.
    0x5B: (0x5B, 0x5C),      # win
}

# Every modifier VK -> the unsided VK standing for its group, so that a
# chord asking for "ctrl" can be matched against what the hook reports.
# The hook reports SIDED codes and nothing else: measured here by
# injecting each modifier BY SCAN CODE (wVk = 0, so Windows derives the VK
# exactly as it does for a real keyboard) under a throwaway hook — left
# ctrl arrived as 0xA2, left shift as 0xA0, left alt as 0xA4, never
# 0x11/0x10/0x12. A chord matcher that compared vk_for("ctrl") = 0x11
# against what is down would therefore never fire, silently, forever.
_MOD_GROUP: dict[int, int] = {}
for _unsided, (_left, _right) in _SIDES.items():
    _MOD_GROUP[_unsided] = _MOD_GROUP[_left] = _MOD_GROUP[_right] = _unsided

# The order modifiers are written in, so one chord has exactly one
# spelling: "ctrl+shift+f6", never "shift+ctrl+f6". Without this the
# config could hold both and the duplicate check would miss it. Win comes
# first because that is how Windows itself writes them — "Win+Shift+S" is
# on the label of the feature this exists to take over.
_MOD_ORDER: dict[int, int] = {0x5B: -1, 0x11: 0, 0x10: 1, 0x12: 2}

# What a GROUP is called in a chord. Needed because _VK_NAMES maps 0x5B to
# "left win" (last write wins, and "left win" is written after "win"),
# while the group that 0x5B stands for is "win". Sided modifiers are not
# in here on purpose: written sided, they stay sided.
_MOD_NAME: dict[int, str] = {0x11: "ctrl", 0x10: "shift", 0x12: "alt",
                             0x5B: "win"}

# Named so a chord can refuse them by name rather than by discovery.
_WIN_VKS = (0x5B, 0x5C)


def side_down(vk: int) -> int | None:
    """For an unsided modifier VK, which of its two keys is physically down
    right now — or None if neither is (or it is not a modifier).

    Asked of Windows rather than worked out from the key event, because the
    key event does not say. Windows puts the UNSIDED VK_CONTROL (0x11) in
    the message for both control keys and hides the difference in an lParam
    bit that Tk does not pass on. Measured on this machine: a synthesised
    keycode-17 key event arrives at Tk as "Control_L" whichever key it
    stands for. Getting that wrong would bind the app's main hotkey to the
    wrong control key, silently.

    GetAsyncKeyState is the right question here because the capture dialog
    asks it while the key is still held: the high bit means "down now".
    """
    pair = _SIDES.get(vk)
    if not pair:
        return None
    left, right = pair
    try:
        for candidate in (right, left):
            if user32.GetAsyncKeyState(candidate) & 0x8000:
                return candidate
    except Exception:
        pass
    return None


# Tk keysym -> the name used here, as a FALLBACK for the sided modifiers
# when nothing was still held by the time the event was handled. Everything
# else is resolved from the event's keycode, which on Windows is the
# virtual-key code itself — and unlike the keysym, that does not change
# with the active keyboard layout. (Measured: with a Hebrew layout active,
# the physical P key reports keysym "Arabic_lam"; its keycode is still
# 0x50, which is what the hook matches on.)
_KEYSYM_NAMES: dict[str, str] = {
    "Control_L": "left ctrl", "Control_R": "right ctrl",
    "Shift_L": "left shift", "Shift_R": "right shift",
    "Alt_L": "left alt", "Alt_R": "right alt",
    "Super_L": "left win", "Super_R": "right win",
    "Prior": "page up", "Next": "page down",
    "Escape": "esc", "Return": "enter", "BackSpace": "backspace",
    "Caps_Lock": "caps lock", "Scroll_Lock": "scroll lock",
    "Num_Lock": "num lock", "Print": "print screen", "Menu": "menu",
    "Pause": "pause", "space": "space", "Tab": "tab",
    "Insert": "insert", "Delete": "delete", "Home": "home", "End": "end",
    "Left": "left", "Right": "right", "Up": "up", "Down": "down",
}


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


def key_name_from_event(keysym: str, keycode: int,
                        probe=side_down) -> str | None:
    """A Tk key event -> a name config.toml would accept, or None.

    None means "this key cannot be a hotkey" — a media key, a dead key, or
    anything else outside the table above. The dashboard says so and keeps
    listening, rather than binding something the app would reject at its
    next start.

    The keycode is trusted over the keysym because it is the virtual-key
    code, which is what the hook actually matches on and what survives a
    change of keyboard layout. `probe` is the exception and comes first:
    only Windows knows which SIDE of a modifier is down.
    """
    keycode = int(keycode)
    if keycode in _SIDES:
        sided = probe(keycode) if probe else None
        if sided:
            return _VK_NAMES[sided]
        named = _KEYSYM_NAMES.get(keysym)     # Tk's guess, if it has one
        if named:
            return named
    name = _VK_NAMES.get(keycode)
    if name:
        return name
    named = _KEYSYM_NAMES.get(keysym)
    if named:
        return named
    lowered = (keysym or "").strip().lower()
    return lowered if lowered in _VK else None


def parse_chord(chord: str) -> list[int]:
    """'ctrl+v' -> [0x11, 0x56]. Raises ValueError on unknown or malformed
    chords ('ctrl+' would otherwise silently paste nothing)."""
    parts = [p.strip() for p in chord.split("+")]
    if not parts or any(not p for p in parts):
        raise ValueError(f"malformed chord {chord!r}")
    return [vk_for(p) for p in parts]


# --------------------------------------------------------- chord bindings

class Binding(NamedTuple):
    """One thing to watch for: modifiers that must be held, and the key
    that fires it. `mods` empty is a plain key, which is what every
    binding was before chords existed.

    A modifier written UNSIDED ("ctrl") is satisfied by either physical
    key; written sided ("left ctrl") only by that one. Both are kept as
    they were named — widening a sided binding to its group would answer a
    question the user did not ask, and the hook can tell the difference.
    """
    mods: frozenset[int]
    trigger: int


def parse_binding(text: str) -> Binding:
    """'ctrl+f6' -> Binding({0x11}, 0x75); 'f6' -> Binding(set(), 0x75).

    Not an extension of parse_chord, because the two describe opposite
    directions and only look alike. parse_chord describes keys to SEND, in
    order, where "ctrl+shift" is a perfectly good thing to send; this
    describes a key to WATCH FOR, where the last part is the trigger and
    everything before it is a condition on what is already held. One
    parser doing both would have to accept the union of two vocabularies,
    which means silently accepting nonsense in whichever direction it was
    not being used for.

    Raises ValueError on anything that could not fire: an unknown name, a
    trailing '+', a chord that is all modifiers and has no trigger, the
    same modifier twice, and the Windows key as a modifier.
    """
    parts = [p.strip() for p in str(text).split("+")]
    if not parts or any(not p for p in parts):
        raise ValueError(f"malformed binding {text!r}")
    trigger = vk_for(parts[-1])
    # THE WINDOWS KEY IS A MODIFIER AND NEVER A TRIGGER. As a trigger it
    # is a key nothing can take: a tap of Win that nothing consumed opens
    # Start, and swallowing it to stop that would cost the Start menu.
    # As a MODIFIER it is fine, and that was measured rather than reasoned
    # — see the note above parse_binding's caller in AGENTS.md, and the
    # three runs behind it:
    #   Win+Shift+S, hook watching only  -> "Snipping Tool Overlay" opens
    #   Win+Shift+S, hook eats the S     -> nothing opens; the chord is ours
    #   Win tapped alone, same hook up   -> Start opens, exactly as before
    # So a Win chord is takeable, and taking one costs nothing else.
    if trigger in _WIN_VKS:
        raise ValueError(
            "the Windows key cannot be the key a chord fires on — it can "
            "only be held. A tap of Win that nothing consumed opens Start, "
            "and the only way to stop that is to swallow the key that "
            "opens the Start menu")
    mods: list[int] = []
    for part in parts[:-1]:
        vk = vk_for(part)
        if vk not in _MOD_GROUP:
            raise ValueError(
                f"{part!r} is not a modifier, so it cannot come before the "
                f"key in {text!r} — only ctrl, shift and alt can (either "
                f"side, or name a side)")
        if any(_MOD_GROUP[m] == _MOD_GROUP[vk] for m in mods):
            raise ValueError(
                f"{vk_name(_MOD_GROUP[vk])} appears twice in {text!r}")
        mods.append(vk)
    if mods and trigger in _MOD_GROUP:
        # "ctrl+shift" is two conditions and nothing to fire on. Refused
        # here rather than bound, because bound it would be a key that
        # never fires and says nothing about why.
        raise ValueError(
            f"{text!r} is all modifiers — a chord needs a key to fire on")
    return Binding(frozenset(mods), trigger)


def binding_name(binding: Binding) -> str:
    """A Binding -> the single spelling config.toml is allowed to hold for
    it. Canonical so that 'ctrl+f6' and 'f6+ctrl' cannot both be written
    into the file and pass the duplicate check as two different keys."""
    ordered = sorted(binding.mods,
                     key=lambda vk: (_MOD_ORDER[_MOD_GROUP[vk]], vk))
    return "+".join([_MOD_NAME.get(vk, vk_name(vk)) for vk in ordered]
                    + [vk_name(binding.trigger)])


def _takes_the_key(binding: Binding) -> bool:
    """Must this chord be taken AWAY from whatever has focus?

    Only a Windows-key chord. Every one of them is a shortcut the shell
    already answers, so binding one and letting it through would fire this
    app AND Windows — bind Win+Shift+S and you would get the capture
    overlay and the Snipping Tool. Ctrl/Shift/Alt chords stay unswallowed,
    which is the rule the rest of this app is built on: a tap key fires
    the action and still reaches the app underneath.
    """
    return any(_MOD_GROUP.get(m) == 0x5B for m in binding.mods)


def is_modifier_key(keycode: int) -> bool:
    """Is this key-down only ever the FIRST half of a chord?

    For the capture dialog: the first key event of ctrl+F6 is the ctrl,
    and a dialog that binds the first key it sees would record "left ctrl"
    and close before the user reached F6.
    """
    return int(keycode) in _MOD_GROUP or int(keycode) in _WIN_VKS


def held_modifier_groups(probe=None) -> frozenset[int]:
    """Which modifier GROUPS Windows says are physically down right now.

    Asked of Windows, not of a key event, for the same reason side_down()
    is: the event does not say, and Tk's `state` bitmask describes the
    moment BEFORE the event. Only the capture dialog may call this — the
    hook's matcher must not (see PTTStateMachine).

    Groups, not sides: a chord the dialog captured should fire from
    whichever hand is free next time.
    """
    if probe is None:
        probe = lambda vk: user32.GetAsyncKeyState(vk) & 0x8000
    held = set()
    for group, (left, right) in _SIDES.items():
        try:
            if probe(left) or probe(right):
                held.add(group)
        except Exception:
            pass
    return frozenset(held)


def binding_name_from_event(keysym: str, keycode: int, probe=side_down,
                            mods=None) -> str | None:
    """A Tk key event + what is held -> a name config.toml would accept.

    The chord form of key_name_from_event, and the whole of what the
    capture dialog needs beyond it. None still means "this key cannot be a
    hotkey".

    A modifier pressed on its own is returned bare and sided ("right
    ctrl"): binding a modifier is a capability the dashboard has today,
    and a modifier is never its own chord. `mods` is injected for tests;
    None means ask Windows now.
    """
    name = key_name_from_event(keysym, keycode, probe)
    if name is None:
        return None
    if keycode in _WIN_VKS:
        # Win alone is not offered as a hotkey, even though the dialog
        # will happily bind any other bare modifier: parse_binding refuses
        # it as a trigger, so binding it here would write a key into
        # config.toml that the next launch throws a message box about.
        return None
    if is_modifier_key(keycode):
        return name
    held = held_modifier_groups() if mods is None else frozenset(mods)
    return binding_name(Binding(held, vk_for(name)))


# ------------------------------------------------------------ state machine

class PTTStateMachine:
    """Decides what each key event means for push-to-talk.

    More than one hotkey may be registered, each bound to a language — or
    to None, which declares nothing and leaves the choice to the
    transcriber (Config.auto_language, the default since it was measured
    on 50 real recordings: see config.py). A key bound to a language is
    still always right, and stays available for anyone who prefers it.

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

    A tap may ask for MODIFIERS as well: `{Binding({0x11}, VK_F6):
    "punctuate"}` means ctrl+F6. Bare keys ran out — the owner lives in
    Chrome, which has taken F6 for the address bar and F7 for caret
    browsing, and the key he moved lookup to was a literal "j". A key
    accepted through `taps` is therefore either a bare vk (what every
    caller passed before chords existed, and still the whole of what the
    hold hotkeys accept) or a Binding.

    The rules, all of which follow from "a chord is only worth having if
    it is a DIFFERENT key from its trigger":

    - a chord matches EXACTLY. ctrl+F6 does not fire on ctrl+shift+F6:
      the extra modifier makes it another chord, which something else may
      want to be.
    - either side of a modifier counts, unless the binding named a side.
    - a BARE binding is the catch-all for its trigger: it fires whatever
      is held, which is what every tap key does today and must keep doing
      byte-identically. So "f6" and "ctrl+f6" can both be bound, exactly
      one of them fires for any press, and the chord wins when it matches.
    - the modifiers are read on the TRIGGER'S key-down and nowhere else.
      Ctrl-then-F6 fires; F6-then-ctrl does not, and cannot fire on a
      later auto-repeat either, because the press is marked spent when it
      happens whether or not anything matched. That is the intended
      reading of "one press, one action", not an accident of ordering.
    - which modifiers are down is tracked from the events this class is
      fed, never asked of Windows. Deliberate: this class is pure logic
      driven straight from tests, and the hook callback has a 300 ms
      budget (exceed it and Windows silently unhooks, whose symptom is
      "my hotkey stopped working" with no error anywhere). The price is
      that a key-up lost by the OS — an alt-tab away mid-chord — leaves a
      phantom modifier held, and this class cannot know; pressing and
      releasing that modifier clears it.
    - INJECTED modifier presses do not count as held, by the same rule the
      abort test below is built on: what the app types is not what the
      user typed. The app's own paste chord puts ctrl down and up again
      inside one SendInput batch, and that must not be able to complete a
      chord for a keystroke that happens to land inside it.

    Only taps take chords. Not the hold hotkeys: a chord there would mean
    holding ctrl in Chrome for the twenty seconds of a dictation, which
    changes what the scroll wheel, a click and a drag all mean. Not the
    latch, which is pressed mid-recording and swallowed — a chord would
    mean swallowing two keys and leaving the modifier's release to guess
    at. Not pause, which is the get-me-out key and stays bare and dumb.

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

    `pause_vk` makes every key above inert without unloading anything. It
    exists because the alternative — quitting the app — costs the ~25 s of
    loading two Whisper models back onto the GPU, so "I am about to play a
    game and do not want Right Ctrl starting recordings" had no cheap
    answer. Two rules follow from what it is for:

    - it is checked BEFORE the paused test, so it is the one key that still
      works while paused. A key that only worked when the app was already
      listening could never turn listening back on.
    - it never falls through to any other rule. It is not a tap key, it
      cannot abort a recording, it just toggles.

    `on_key_down` is the one thing here that is not about recording at
    all. The lookup box (popup.py) never takes focus — that is what lets
    it appear over a web page without stealing the caret — and a window
    that never takes focus never receives WM_KEYDOWN. This hook is the
    only thing in the process that sees a key at all, so it is the only
    way a keystroke can ever reach that box. It is given every REAL
    key-down, before any other rule and in every state, and what it
    returns is OR-ed into the swallow decision.

    Two keys come back True, and which two is popup.py's to decide, not
    this module's: Esc, which closes the box, and Ctrl+C, which copies
    what is selected in it. The box used to close on ANY keystroke, which
    meant it could not be read with a hand on the keyboard — press Shift
    and the answer was gone — and the owner reported that as the box
    vanishing at random. Every other key passes through and leaves the box
    alone.

    Injected key-downs are still not offered to it, and that gate is now
    load-bearing again. It was added because a dictation finishing over an
    open box closed it with the app's own Ctrl+V (measured 2026-08-19,
    and with three synthetic backspaces as well). Since the box began
    taking Ctrl+C the gate protects something larger: the copy chord this
    app sends to READ a selection (injector.read_selection, and grab()
    before it) is a Ctrl+C, and offered to a box that is already holding
    a selection it would be swallowed — the chord would never reach the
    window it was aimed at, and the lookup key would answer "nothing
    selected" for a selection that was there all along. The rule has not
    changed: the app typing is not the user typing, which is the same
    rule the abort test below is built on.

    Callbacks run on the hook thread — keep them fast.
    """

    def __init__(self, hotkeys: int | dict[int, str],
                 on_start: Callable[[str], None],
                 on_stop: Callable[[str], None],
                 on_abort: Callable[[str], None],
                 taps: dict[int | Binding, str] | None = None,
                 on_tap: Callable[[str], None] | None = None,
                 latch_vk: int | None = None,
                 on_latch: Callable[[], None] | None = None,
                 cancel_vk: int | None = 0x1B,   # Esc
                 pause_vk: int | None = None,
                 on_pause: Callable[[bool], None] | None = None,
                 on_key_down: Callable[[int], bool] | None = None):
        self._on_start = on_start
        self._on_stop = on_stop
        self._on_abort = on_abort
        self._on_tap = on_tap
        self._on_latch = on_latch
        self._on_pause = on_pause
        self._on_key_down = on_key_down
        self._cancel_vk = cancel_vk
        self._state = IDLE
        self._paused = False
        self._active_vk: int | None = None
        self._tap_held: set[int] = set()
        self._down: set[int] = set()      # physically-down keys, for repeat
        # Modifiers only, physical only. Kept apart from `_down` because
        # the two answer different questions: `_down` holds every key
        # including whatever the app injected, and a chord must not be
        # completed by the app's own paste.
        self._mods_down: set[int] = set()
        self._swallow_latch_up = False
        self._swallow_tap_up: set[int] = set()
        self._lock = threading.Lock()
        (self._hotkeys, self._taps,
         self._latch_vk, self._pause_vk) = self._checked(
            hotkeys, taps, latch_vk, pause_vk)

    def _checked(self, hotkeys: int | dict[int, str],
                 taps: dict[int | Binding, str] | None,
                 latch_vk: int | None, pause_vk: int | None):
        """Validate a whole binding set and return it normalised.

        Deliberately pure: rebind() calls this BEFORE it touches anything,
        so a rejected key change leaves the keys that were working still
        working, rather than half-applied.

        Taps come out keyed by TRIGGER, each with the list of bindings on
        that trigger, because that is the question handle() asks: a key
        went down, is there anything on it. The list is what lets "f6" and
        "ctrl+f6" coexist; exact matching is what stops the list ever
        being ambiguous.
        """
        # A bare vk keeps the original single-hotkey form working.
        keys = ({hotkeys: "he"} if isinstance(hotkeys, int)
                else dict(hotkeys or {}))
        if not keys:
            raise ValueError("at least one hotkey is required")
        tap_keys: dict[int, list[tuple[Binding, str]]] = {}
        for key, action in dict(taps or {}).items():
            if isinstance(key, tuple):      # Binding, or the plain pair
                if len(key) != 2:
                    raise ValueError(
                        f"a tap binding is (modifiers, trigger), got {key!r}")
                bound = Binding(frozenset(key[0]), int(key[1]))
            else:
                bound = Binding(frozenset(), int(key))
            bad = [m for m in bound.mods if m not in _MOD_GROUP]
            if bad:
                # Checked here so the matcher, which runs inside the hook
                # callback, can index _MOD_GROUP without a guard.
                raise ValueError(f"{vk_name(bad[0])} is not a modifier and "
                                 f"cannot be part of a chord")
            on_trigger = tap_keys.setdefault(bound.trigger, [])
            if any(other.mods == bound.mods for other, _a in on_trigger):
                raise ValueError(
                    f"{binding_name(bound)} is bound twice — one key "
                    f"cannot mean two things")
            on_trigger.append((bound, action))
        clash = set(tap_keys) & set(keys)
        if clash:
            # Chords included, unlike the latch below: the hold branch in
            # handle() is tested before the tap branch, so a chord sharing
            # a hold hotkey's trigger could never fire. Refused loudly
            # rather than accepted and silently dead.
            raise ValueError(
                f"{vk_name(next(iter(clash)))} is both a hold hotkey and a "
                f"tap key — one key cannot mean two things")
        for vk, label in ((latch_vk, "latch"), (pause_vk, "pause")):
            if vk is None:
                continue
            on_trigger = tap_keys.get(vk, [])
            # The pause key is tested first, in every state, so anything
            # else on it is dead — chords included. The latch key is inert
            # while idle, which is the only time taps fire, so only the
            # BARE binding on it is a real collision: ctrl+left and left
            # are two different keys and the app can tell them apart.
            taken = (on_trigger if label == "pause"
                     else [b for b, _a in on_trigger if not b.mods])
            if vk in keys or taken:
                raise ValueError(
                    f"{vk_name(vk)} is already a hotkey or tap key, so it "
                    f"cannot also be the {label} key — one key cannot mean "
                    f"two things")
        if latch_vk is not None and pause_vk is not None \
                and latch_vk == pause_vk:
            raise ValueError(f"{vk_name(latch_vk)} cannot be both the latch "
                             f"key and the pause key — one key cannot mean "
                             f"two things")
        if tap_keys and self._on_tap is None:
            raise ValueError("taps were registered without an on_tap handler")
        if latch_vk is not None and self._on_latch is None:
            raise ValueError("a latch key was registered without an on_latch "
                             "handler")
        if pause_vk is not None and self._on_pause is None:
            raise ValueError("a pause key was registered without an on_pause "
                             "handler")
        return keys, tap_keys, latch_vk, pause_vk

    def _match_tap(self, vk: int) -> tuple[Binding, str] | None:
        """(the binding that matched, the action) — or None for "nothing on
        that key with those modifiers held".

        The BINDING and not just the action, because the caller has one
        more question to ask of it: whether this chord is one the app has
        to take away from Windows (see `_takes_the_key`). Called with the
        lock held,
        from inside the hook callback: set arithmetic on at most three
        elements, no syscall, nothing that can block.

        Two comparisons, and both are needed. The GROUPS held must equal
        the groups required — that is what rejects an extra modifier
        (ctrl+shift+F6 is not ctrl+F6) and what makes "either ctrl" true
        without making "both ctrls down" false. Then any modifier that was
        named with a side must be that exact key.
        """
        # The trigger's own group is not a condition on itself: a bare
        # binding on "right alt" would otherwise never match, because
        # pressing it is what put alt down.
        trigger_group = _MOD_GROUP.get(vk)
        held = {m for m in self._mods_down
                if _MOD_GROUP[m] != trigger_group}
        held_groups = {_MOD_GROUP[m] for m in held}
        fallback = None
        for bound, action in self._taps.get(vk, ()):
            if not bound.mods:
                if not held_groups:
                    return bound, action
                fallback = (bound, action)   # the catch-all; see above
                continue
            if held_groups != {_MOD_GROUP[m] for m in bound.mods}:
                continue
            if all(m in _SIDES or m in held for m in bound.mods):
                return bound, action
        return fallback

    @property
    def state(self) -> str:
        return self._state

    @property
    def paused(self) -> bool:
        return self._paused

    @property
    def language(self) -> str | None:
        """Language of the recording in progress, if any."""
        vk = self._active_vk
        return self._hotkeys.get(vk) if vk is not None else None

    def _reset_locked(self) -> None:
        """Back to idle. The caller holds the lock and is responsible for
        telling the app about any recording this threw away."""
        self._state = IDLE
        self._active_vk = None
        self._swallow_latch_up = False

    def set_paused(self, paused: bool) -> bool:
        """Pause or resume from somewhere other than the pause key (the
        dashboard). Returns True if this changed anything.

        A recording in progress is ABORTED rather than transcribed: pausing
        means "stop listening", and a half-sentence pasted at the cursor a
        moment after the user asked for silence is the opposite of that.
        """
        paused = bool(paused)
        aborted = False
        with self._lock:
            if paused == self._paused:
                return False
            self._paused = paused
            aborted = self._state != IDLE
            self._reset_locked()
        if aborted:
            self._on_abort("paused")
        if self._on_pause is not None:
            self._on_pause(paused)
        return True

    def rebind(self, hotkeys: int | dict[int, str],
               taps: dict[int | Binding, str] | None = None,
               latch_vk: int | None = None,
               pause_vk: int | None = None) -> None:
        """Change every binding at once, live. Raises ValueError (leaving
        the current keys untouched) if the new set is not coherent.

        All four at once, not one at a time, because the collision rules
        are between them: swapping the latch key onto what is currently the
        translate key is only legal in the same breath as moving translate
        somewhere else.

        Every key that is physically DOWN right now is marked spent, not
        cleared. Clearing it re-armed a key the user had not let go of, and
        Windows was still auto-repeating: capture ctrl+F8 in the dashboard
        without lifting the finger and the rebind landed under the repeat,
        so `correct` fired again on every one of them — thirty times a
        second, each firing a ctrl+a/ctrl+c into whatever had focus and a
        request to Gemini. A key is armed by its RELEASE, here as
        everywhere else in this class.
        """
        with self._lock:
            checked = self._checked(hotkeys, taps, latch_vk, pause_vk)
            (self._hotkeys, self._taps,
             self._latch_vk, self._pause_vk) = checked
            aborted = self._state != IDLE
            self._reset_locked()
            self._tap_held = set(self._down)
        if aborted:
            # The key it was recording under may not exist any more, so
            # there would be no key-up to end it: discard rather than leave
            # a recording nothing can stop.
            self._on_abort("keys changed")

    def handle(self, event_type: str, vk: int, injected: bool) -> bool:
        """Feed one key event. Returns True when the hook should SWALLOW it
        (the latch key, for presses this consumed, and whatever
        `on_key_down` claims)."""
        fire: Callable[[], None] | None = None
        swallow = False
        # First, in every state, and OUTSIDE the lock. First because the
        # Esc that closes a box on screen has to reach it whether or not a
        # recording is running, and while paused too. Outside the lock
        # because this is somebody else's code on the OS hook thread: it
        # must not be able to deadlock against a rebind, and it must not be
        # able to stop a key reaching the focused app by raising.
        #
        # `not injected`, for the same reason the abort rule below has it:
        # what the app types is not what the user typed. See the class
        # docstring — it is the app's own copy chord that gate is keeping
        # out of the box now, not just its paste.
        eaten = False
        if event_type == "down" and not injected \
                and self._on_key_down is not None:
            try:
                eaten = bool(self._on_key_down(vk))
            except Exception:
                eaten = False
        with self._lock:
            # Auto-repeat bookkeeping, done whatever the state: a tap key
            # pressed mid-recording aborts without being marked held, and
            # must still be armed again by its release.
            was_down = vk in self._down
            if not injected and vk in _MOD_GROUP:
                # Physical modifiers only, and both halves ignored when
                # injected: the app's paste chord presses ctrl and
                # releases it inside one SendInput batch, and half of that
                # landing in here would leave a modifier held that nobody
                # is holding.
                if event_type == "up":
                    self._mods_down.discard(vk)
                else:
                    self._mods_down.add(vk)
            if event_type == "up":
                self._tap_held.discard(vk)
                self._down.discard(vk)
                if vk in self._swallow_tap_up:
                    # Its key-DOWN was taken; the release must not arrive
                    # on its own either, or an app watching key state sees
                    # a key come up that never went down.
                    self._swallow_tap_up.discard(vk)
                    swallow = True
                if vk == self._latch_vk and self._swallow_latch_up:
                    # Its key-DOWN was swallowed; releasing it must not
                    # reach the app on its own either.
                    self._swallow_latch_up = False
                    swallow = True
            else:
                self._down.add(vk)
                if vk in self._swallow_tap_up and was_down:
                    # Auto-repeat of a chord we took: holding Win+Shift+S
                    # down must not start leaking S into whatever has
                    # focus once the first press has fired.
                    swallow = True
                if vk == self._latch_vk and was_down and self._swallow_latch_up:
                    # Auto-repeat of a press whose key-down we swallowed —
                    # holding it down must not leak arrows into the app.
                    swallow = True

            if eaten:
                # A keystroke the box on screen consumed is spent: nothing
                # below may act on it as well. Esc is the whole reason this
                # line exists, because Esc already meant "throw the locked
                # recording away" — measured against the real state machine
                # 2026-08-19, one Esc aimed at a lookup box both closed the
                # box AND discarded a latched recording. The bookkeeping
                # above still ran, so the key is still armed for its release.
                return True

            if self._pause_vk is not None and vk == self._pause_vk:
                # First, and in every state. See the class docstring: this
                # is the one key that has to keep working while paused, and
                # it never means anything else.
                if event_type == "down" and not was_down:
                    self._paused = not self._paused
                    now_paused = self._paused
                    aborted = self._state != IDLE
                    self._reset_locked()

                    def fire(now_paused=now_paused, aborted=aborted):
                        if aborted:
                            self._on_abort("paused mid-recording")
                        self._on_pause(now_paused)
            elif self._paused:
                pass    # every other key is inert, and passes through
            elif self._state == IDLE:
                if vk in self._hotkeys and event_type == "down":
                    self._state = RECORDING
                    self._active_vk = vk
                    language = self._hotkeys[vk]
                    fire = lambda: self._on_start(language)
                elif vk in self._taps and event_type == "down" \
                        and vk not in self._tap_held:
                    # Marked spent whether or not anything matched, so a
                    # press that missed cannot be rescued by a modifier
                    # arriving later and an auto-repeat firing on it.
                    self._tap_held.add(vk)   # ignore Windows auto-repeat
                    matched = self._match_tap(vk)
                    if matched is not None:
                        bound, action = matched
                        fire = lambda: self._on_tap(action)
                        if _takes_the_key(bound):
                            # The ONE exception to "tap keys are not
                            # swallowed", and it is what makes a Win chord
                            # possible at all: bind Win+Shift+S and both
                            # this app and the Snipping Tool would answer
                            # it. Measured 2026-08-26 — with the S eaten
                            # here, the overlay never opens and the Start
                            # menu still works, because Win itself is
                            # untouched.
                            swallow = True
                            self._swallow_tap_up.add(vk)
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
                    # A modifier counts as "any other key" here and always
                    # has: pressing ctrl mid-hold is the user reaching for
                    # a combo, and chords do not change that. They only
                    # ever matter while idle, so nothing here has to know
                    # about them — do not "fix" this to hold fire for a
                    # chord that has not been pressed yet.
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
        return swallow or eaten


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
                injected = bool(ks.flags & LLKHF_INJECTED)
                if event and self._machine.handle(
                        event, ks.vkCode, injected):
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
