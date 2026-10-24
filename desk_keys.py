"""Keys on the web desk: every binding lit on a drawn keyboard, and the
way to change one — Dashboard._screen_keys and everything it calls,
answered as data for web/src/places/keys.tsx.

SAME SOURCES, SAME WORDS. The bindings are the running app's
(status()["keys"]) or, with nothing running, the files'
(config.load_layered); they are lit on keycaps.py's board by
keycaps.bindings, and a cap's bindings are found by keycaps.caps_for,
exactly as the Tk place does. The words are the Tk place's own: KEY_*
below are copies of dashboard.py's tables, and a test holds every copy
and every sentence to the file they came from (dashboard.py is not
imported: it is the Tk desk, and a process with no Tk window has no
business loading it).

THE BOARD IS KEYCAPS.PY'S, READ AND NOT IMPORTED. `import keycaps`
brings ui.py with it, and ui.py brings Tk, Pillow and skia: measured
2026-10-24 in a process that had already imported deskweb, 183-201 ms
and +14 MB private memory, on the first visit to Keys of every window.
Everything this module needs from keycaps.py is its tables and its pure
functions (ROWS, TALL, HEBREW, bindings, caps_for, cap_for_vk, name_for…),
so _caps() runs the file's top-level statements without its imports
(about 5 ms) — and falls back to the import if that ever fails. A test
holds the two to the same answers.

THE PICTURE'S CAP, KEYCAPS' GAPS. The board is drawn from keycaps.ROWS,
unit by unit, the arithmetic of keycaps.draw; the cap unit is the
approved picture's (design/2026-09-22/design/places/keys: 46 px) and the
gaps are the ones keycaps.draw makes at its own 34 px cap (5 between
caps, 19 under the F row), which is what the picture drew too.

THE REBIND IS THE TK DESK'S (_capture, _resume_after_capture, _apply_key).
While a key is being listened for, the running app is PAUSED, and the
reply is checked — without it, pressing Right Ctrl to bind it would start
a recording, and pressing F9 would translate whatever is selected
underneath. One step stricter than the Tk desk: an app that answers at
all is paused, a starting one too (its hook is up long before it says
"running"), and an app that is there but does not answer is not listened
past — nothing could be paused. The page does the listening (a key pressed in WebView2 reaches
the page as a keydown with the Windows virtual-key code in keyCode and the
side in code, measured on the hidden desktop 2026-10-24 for every key on
the board) and hands the key here; the name is made by
hotkey.binding_name_from_event, as the Tk dialog made it, and nothing the
page sends is trusted: the key code, its side and the modifiers are
checked against fixed lists, the field against config.HOTKEY_FIELDS, and
the name against hotkey.parse_binding before anything is written. Then
`rebind` down the pipe while the app runs, or config.check_hotkeys +
config.save when it does not, answered with config.rebound_sentence — or
with the sentence that refused it.

THE PAUSE COMES BACK ON EVERY PATH. A key, Cancel, Esc, the place left,
the window closed (atexit), the page gone quiet without saying so (a
lease the page renews every second, LEASE_S): each ends the listening
through _end, which resumes exactly once, and only a pause this place
took (a person who had paused the app himself keeps it paused).

AND ONE TRAP OF WEBVIEW2'S. A bare Alt, a bare F10 and Ctrl+F10 put the
desk's WinForms form into the system-menu mode (GetGUIThreadInfo: flags
GUI_INMENUMODE | GUI_SYSTEMMENUMODE, measured 2026-10-24 on the hidden
desktop): the page still sees the key, but nothing it asks Python is
answered until the menu mode ends — and the next key a person presses
goes to the menu, not to the page. One Esc to the form ends it, and is
eaten by the menu, never seen by the page. So while a key is listened for,
and for GRACE_S after, a watcher ends that mode the moment it starts:
Right Alt can be bound as the dictation key here as it can in the Tk desk.
"""
from __future__ import annotations

import __future__
import ast
import atexit
import ctypes
import ctypes.wintypes as wintypes
import importlib.util
import logging
import os
import re
import threading
import time
import weakref
from pathlib import Path

import config as config_mod
import hotkey as hotkey_mod
import paths
import singleton

log = logging.getLogger("app")


# ------------------------------------------------------------- the words
# Copies of dashboard.py's tables and sentences, held to it by a test.

#: dashboard.KEY_LEGEND, said as the picture says it: a capital, and each
#: note broken where the picture breaks it (the words are the Tk desk's).
KEY_LEGEND = (
    ("held", "down the whole time it works", "hold"),
    ("tapped", "fires and still reaches the app underneath", "tap"),
    ("chord", "the modifier lit softly, the key fully", "chord"),
    ("only sometimes", "Esc, while a recording is running", "sometimes"),
    ("unlit", "the app never sees it", None),
)
#: where each legend note breaks into its second line, as in keys.png
LEGEND_BREAK = {"held": "time", "tapped": "the", "chord": "the",
                "only sometimes": "is", "unlit": "sees"}

#: dashboard.KEY_GROUPS
KEY_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Recording", ("hotkey", "english_hotkey", "latch_hotkey")),
    ("What to do with the text", ("translate_hotkey", "punctuate_hotkey",
                                  "correct_hotkey", "lookup_hotkey",
                                  "visual_qa_hotkey")),
    ("What to do with the screen", ("capture_hotkey", "record_hotkey",
                                    "camera_hotkey")),
    ("The app itself", ("pause_hotkey", "screens_hotkey", "dismiss_hotkey",
                        "report_hotkey", "shelf_hotkey")),
)
#: The approved picture's three columns of those groups.
COLUMNS = (("Recording", "What to do with the screen"),
           ("What to do with the text",),
           ("The app itself",))

#: dashboard.KEY_NOTES
KEY_NOTES: dict[str, tuple[str, str]] = {
    "pause_hotkey": (
        "a pause, not a stop",
        "A pause, not a stop. Nothing is unloaded — the models stay on "
        "the card and coming back is instant — and this is the one key "
        "that still works while paused."),
}

#: dashboard.NESTED_HOTKEYS: where config.save writes a key that lives in
#: a section.
NESTED_HOTKEYS = {
    "visual_qa_hotkey": "visual_qa.visual_qa_hotkey",
    "capture_hotkey": "capture.capture_hotkey",
    "record_hotkey": "capture.record_hotkey",
    "camera_hotkey": "camera.camera_hotkey",
    "screens_hotkey": "awake.screens_hotkey",
    "dismiss_hotkey": "notify.dismiss_hotkey",
    "report_hotkey": "problems.report_hotkey",
    "shelf_hotkey": "shelf.shelf_hotkey",
}

#: dashboard._screen_keys' title and its line, in the picture's case
TITLE = "Keys"
SUB = "Press a key, or click one on the board, to see what it does — then change it."
#: dashboard._screen_keys' foot as the approved picture says it: the Tk
#: sentence's own words, its middle clause left out — said whole, the line
#: runs off the window (photographed 2026-10-24) — and the caps drawn
SAFE_LEAD = ("Anything not lit is untouched by this app. The keys it cannot "
             "take at all — the punctuation keys")
SAFE_TAIL = "— are the safe ones."
MISSING = "Bound to a key this board does not draw: {missing}."

#: The one word under a lit cap, for a binding keycaps.CAPTION has no word
#: for: its fallback is the label's first words ("open the shelf"), which a
#: 41 px cap cuts to "open the sh"; the approved picture says "shelf".
CAPTION_MORE = {"shelf_hotkey": "shelf"}

#: dashboard._paint_rebind, _listening_card and _capture's dialog
WORDS = {
    "eyebrow": "This key",
    "none": ("Press a key, or click one on the board, to see what it does — "
             "and to change it."),
    "free": ("{name} is yours — the app never takes it. Pick a binding below "
             "and press this key when it asks."),
    "two": ("Two bindings on this key — the bare one and the one with a "
            "modifier. Change whichever you meant."),
    "numlock": ("On the keypad, and Windows only sends it while Num Lock is ON. "
                "With Num Lock off the same cap sends the navigation key "
                "printed beside the digit."),
    "change": "Change this key",
    "listen": "Press the key you want",
    "modifier": "…and now the key",
    "unusable": "Not a key this can use — try another",
    "esc": "Esc cancels.",
    "off": "Turn this key off",
    "cancel": "Cancel",
    "chord": "chord",
    "bare": "bare key",
    "tap": "tap",
}
LISTENING = "listening for {what}"
PAUSE_FAILED = "could not pause it to listen for a key — try again in a moment"
NOT_RUNNING = "dictation is not running"
#: The dictation key cannot be turned off (the Tk dialog has no button for
#: it; main.rebind says the same in these words).
HOTKEY_ON = "the dictation key cannot be turned off"

# ------------------------------------------------------------- the board

#: The approved picture's cap; keycaps.draw's gaps at its own 34 px cap.
UNIT = 46
GAP = 5
ROW_GAP = 19

#: The page's e.code for the keys whose virtual-key code does not say
#: which cap: the modifiers (keyCode 17 is either Ctrl) and the keypad's
#: Enter (keyCode 13, like the main one). A real key press finds its cap
#: by these first, and by keycaps.cap_for_vk otherwise.
CODE_CAPS = {"ControlLeft": "lctrl", "ControlRight": "rctrl",
             "ShiftLeft": "lshift", "ShiftRight": "rshift",
             "AltLeft": "lalt", "AltRight": "ralt",
             "MetaLeft": "lwin", "MetaRight": "rwin",
             "NumpadEnter": "numenter"}

#: What the page may say about a key it heard: its side, and which
#: modifier groups were down (as hotkey's unsided group codes).
SIDES = ("", "left", "right")
MOD_GROUPS = {"ctrl": 0x11, "shift": 0x10, "alt": 0x12, "win": 0x5B}

#: How long the page may go without a word while it listens, before the
#: listening is taken as over and the app resumed (it renews every 1 s).
LEASE_S = 4.0
#: How long after the listening the menu-mode watcher keeps watching: a
#: key bound on its key-down (F10) puts the form into menu mode on its
#: key-UP, which comes after.
GRACE_S = 2.0
WATCH_S = 0.04

_caps_ns: dict | None = None
_caps_lock = threading.Lock()


def _caps() -> dict:
    """keycaps.py's tables and pure functions, without its imports.

    The module's top-level statements are run in a namespace of their own
    with config and hotkey already in it, every import and every class
    left out (the Tk Board, and the drawing's Pillow and ui, are never
    needed here). Falls back to importing the module if anything in the
    file stops being runnable this way."""
    global _caps_ns
    with _caps_lock:
        if _caps_ns is not None:
            return _caps_ns
        try:
            # the file `import keycaps` would load, found the way the import
            # finds it — and not run
            path = Path(importlib.util.find_spec("keycaps").origin)
            tree = ast.parse(path.read_text("utf-8"), str(path))
            body = [node for node in tree.body
                    if not isinstance(node, (ast.Import, ast.ImportFrom, ast.ClassDef))
                    and not (isinstance(node, ast.Expr)
                             and isinstance(node.value, ast.Constant))]
            module = ast.Module(body=body, type_ignores=[])
            ns: dict = {"__name__": "keycaps_tables", "__file__": str(path),
                        "Path": Path, "paths": paths, "config_mod": config_mod,
                        "hotkey_mod": hotkey_mod}
            # annotations postponed, as the file itself asks: draw's names
            # Pillow's Image, which is not here
            code = compile(module, str(path), "exec", dont_inherit=True,
                           flags=__future__.annotations.compiler_flag)
            exec(code, ns)  # noqa: S102 — the app's own file
            for name in ("ROWS", "TALL", "HEBREW", "UNITS", "GRID_ROWS", "CAPTION",
                         "KEYPAD_NUMLOCK", "bindings", "caps_for", "cap_for_vk",
                         "name_for", "offered", "vk_caps"):
                ns[name]  # noqa: B018 — every name this module reads is there
        except Exception as e:            # noqa: BLE001
            log.info("web desk: keycaps.py read whole instead (%s)", type(e).__name__)
            import keycaps
            ns = vars(keycaps)
        _caps_ns = ns
        return ns


def split_label(label: str) -> tuple[str, str]:
    """'Dictate (hold)' -> ('Dictate', 'hold') — dashboard.split_label."""
    match = re.match(r"^(.*?)\s*\((hold|tap)\)\s*$", label)
    return (match.group(1), match.group(2)) if match else (label, "")


def pretty_key(name: str) -> str:
    """'right ctrl' -> 'Right Ctrl'; '' -> 'off' — dashboard.pretty_key."""
    return name.title() if name else "off"


def cap_title(cap_id: str) -> str:
    """'num5' -> 'NUMPAD 5', 'q' -> 'Q' — dashboard.cap_title."""
    return (_caps()["name_for"](cap_id) or cap_id).upper()


def board(u: float = UNIT, gap: float = GAP, row_gap: float = ROW_GAP,
          pad: float = 0) -> dict:
    """keycaps.ROWS laid out the way keycaps.draw lays them out: each cap
    `units * u` along its row, `gap` short of its neighbour, two rows tall
    where keycaps.TALL says so, and `row_gap` under the F row."""
    k = _caps()
    caps = []
    y = pad
    for index, row in enumerate(k["ROWS"]):
        if index == 1:
            y += row_gap
        x = pad
        for cap_id, label, units in row:
            w = units * u
            if cap_id is None:
                x += w
                continue
            tall = k["TALL"].get(cap_id, 1) * u
            caps.append({"id": cap_id, "label": label,
                         "x": round(x, 2), "y": round(y, 2),
                         "w": round(w - gap, 2), "h": round(tall - gap, 2)})
            x += w
        y += u
    return {"caps": caps, "w": round(k["UNITS"] * u - gap, 2),
            "h": round(k["GRID_ROWS"] * u + row_gap - gap, 2), "u": u}


def _row_caps(field: str, raw: str) -> list[dict]:
    """A binding as the list draws it: one cap a part, the modifiers lit
    softly and the key fully (held for the two dictation keys), "off"
    for none."""
    if not raw:
        return [{"t": "off", "k": "off"}]
    parts = [p.strip() for p in raw.split("+") if p.strip()]
    hold = field in ("hotkey", "english_hotkey")
    out = []
    for i, part in enumerate(parts):
        last = i == len(parts) - 1
        out.append({"t": part.title(), "k": ("hold" if hold else "tap") if last else "soft",
                    "name": part})
    return out


class Place:
    """Keys, as data, and what its buttons do. One per window; its calls
    arrive on threads of their own, so every public method holds the
    lock."""

    def __init__(self, send) -> None:
        self._send = send
        self._lock = threading.RLock()
        self.status: dict = {}
        self.running = False
        #: the field a key is being listened for, and whether this place
        #: paused the app for it (dashboard._capturing, _paused_for_capture)
        self._capturing: str | None = None
        self._paused_for_capture = False
        self._lease = 0.0
        self._watch_until = 0.0
        self._watcher: threading.Thread | None = None
        #: ends the desk's menu mode; a test hands a fake
        self._menu_out = menu_out
        self._fields = dict(config_mod.HOTKEY_FIELDS)
        # The window closed mid-listening: the process ends, and the
        # pause it took must not outlive it (dashboard._close does the
        # same for the Tk desk).
        atexit.register(_at_exit, weakref.ref(self))

    # -- reading

    def _poll(self) -> None:
        reply = self._send("status", timeout_ms=1200)
        if isinstance(reply, dict):
            reply = dict(reply)
            reply.pop("phone", None)          # never the page's
        self.status = reply if isinstance(reply, dict) else {}
        self.running = bool(reply) and self.status.get("stage") == "running"

    def _keys(self) -> dict:
        """dashboard: `self.status.get("keys") or self._read_keys()`."""
        keys = self.status.get("keys")
        if isinstance(keys, dict) and keys:
            return {f: str(keys.get(f) or "") for f in self._fields}
        try:
            cfg = config_mod.load_layered()
        except Exception:                 # noqa: BLE001 — never a blank place
            return {f: "" for f in self._fields}
        return {f: str(getattr(cfg, f, "") or "") for f in self._fields}

    def read(self, **args) -> dict:
        if args:
            return {"ok": False, "error": "Keys reads nothing but itself"}
        with self._lock:
            self._poll()
            return self._place()

    def _place(self) -> dict:
        k = _caps()
        keys = self._keys()
        try:
            lit, unmapped = k["bindings"](keys)
        except Exception:                 # noqa: BLE001 — dashboard: never a blank screen
            lit, unmapped = {}, []
        on: dict[str, list[str]] = {}
        for field, raw in keys.items():
            if raw:
                for cap in k["caps_for"](raw):
                    on.setdefault(cap, []).append(field)
        laid = board()
        for cap in laid["caps"]:
            cid = cap["id"]
            heb = k["HEBREW"].get(cid)
            if heb:
                cap["heb"] = heb
            mine = lit.get(cid) or []
            if mine:
                bare = [b for b in mine if "+" not in (b[3] or "")]
                state, caption, field = (bare or mine)[0][:3]
                if field not in k["CAPTION"]:
                    caption = CAPTION_MORE.get(field, caption)
                cap["state"] = state
                if caption:
                    cap["caption"] = caption
            if on.get(cid):
                cap["on"] = on[cid]
            if cid in k["KEYPAD_NUMLOCK"]:
                cap["numlock"] = True
            cap["title"] = cap_title(cid)
        fields = {}
        for field, label in config_mod.HOTKEY_FIELDS:
            raw = keys.get(field, "")
            what, how = split_label(label)
            first = (k["caps_for"](raw) or [None])[0] if raw else None
            fields[field] = {
                "what": what, "how": how,
                "note": KEY_NOTES[field][0] if field in KEY_NOTES else "",
                "said": KEY_NOTES[field][1] if field in KEY_NOTES else "",
                "shown": pretty_key(raw), "raw": raw,
                "caps": _row_caps(field, raw), "cap": first,
                "state": ("hold" if field in ("hotkey", "english_hotkey") else "tap") if raw else "off",
                "kind": WORDS["chord"] if "+" in raw else WORDS["bare"],
                "may_off": field != "hotkey",
            }
        grouped = {name: [f for f in members if f in fields] for name, members in KEY_GROUPS}
        named = {f for _n, members in KEY_GROUPS for f in members}
        grouped[KEY_GROUPS[-1][0]] += [f for f in fields if f not in named]
        missing = ", ".join(f"{f} = {r!r}" for f, r in unmapped)
        capture = None
        if self._capturing:
            what = split_label(self._fields[self._capturing])[0]
            capture = {"field": self._capturing,
                       "listening": LISTENING.format(what=what.lower()),
                       "may_off": self._capturing != "hotkey"}
        return {
            "ok": True,
            "title": TITLE, "sub": SUB,
            "legend": [{"title": t[:1].upper() + t[1:], "state": s,
                        "lines": _broken(note, LEGEND_BREAK[t])}
                       for t, note, s in KEY_LEGEND],
            "board": laid,
            "fields": fields,
            "columns": [[{"name": g, "rows": grouped[g]} for g in col] for col in COLUMNS],
            "foot": {"lead": SAFE_LEAD, "caps": _safe_caps(), "tail": SAFE_TAIL,
                     "missing": MISSING.format(missing=missing) if missing else ""},
            "words": WORDS,
            "codes": CODE_CAPS,
            "vks": {str(vk): caps[0] for vk, caps in k["vk_caps"]().items()},
            "start": fields["hotkey"]["cap"],
            "capture": capture,
            "running": self.running,
        }

    # -- doing

    def act(self, do: str, arg=None) -> dict:
        """One button. Answers the place again, with the line the page
        shows for a moment (`note`) — and, after a key was taken, the cap
        it landed on (`chosen`)."""
        do = str(do)
        with self._lock:
            extra: dict = {}
            if do == "capture.start":
                note = self._start(arg)
            elif do == "capture.alive":
                if self._capturing:
                    self._lease = time.monotonic() + LEASE_S
                note = ""
            elif do == "capture.key":
                note, extra = self._key(arg)
            elif do == "capture.off":
                if not self._capturing:
                    note = ""
                elif self._capturing == "hotkey":
                    note = HOTKEY_ON
                else:
                    field = self._capturing
                    self._end()
                    note = self._apply(field, "")
            elif do == "capture.cancel":
                self._end()
                note = ""
            else:
                return {"ok": False, "error": f"{do[:40]!r} is not a Keys action"}
            if not self.status:
                self._poll()
            answer = self._place()
            answer.update(extra, note=note)
            return answer

    def _start(self, field) -> str:
        """dashboard._capture: pause the running app — checked — and
        listen for `field`."""
        if not isinstance(field, str) or field not in self._fields:
            return "that is not a key this place changes"
        if self._capturing:
            if self._capturing == field:
                self._lease = time.monotonic() + LEASE_S
                return ""
            self._capturing = field          # the pause it already took stands
            self._lease = time.monotonic() + LEASE_S
            return ""
        self._poll()
        if not self.status and singleton.is_running():
            # The app is there and did not answer: its hook may well be
            # live, and listening without the pause would let the key being
            # chosen fire (the Tk desk paused only an app that answered).
            return PAUSE_FAILED
        if self.status and not bool(self.status.get("paused")):
            # Any app that answers is paused — a starting one too: its hook
            # is up 0.7 s into a start (--no-model), long before "running".
            reply = self._send("pause", timeout_ms=1500)
            if not (isinstance(reply, dict) and reply.get("ok")):
                return PAUSE_FAILED
            self._paused_for_capture = True
        self._capturing = field
        self._lease = time.monotonic() + LEASE_S
        self._watch()
        return ""

    def _key(self, arg) -> tuple[str, dict]:
        """A key the page heard. Its name the Tk dialog's way
        (hotkey.binding_name_from_event), or "not a key this can use" and
        the listening goes on."""
        if not self._capturing:
            return "", {}
        self._lease = time.monotonic() + LEASE_S
        name = key_name(arg)
        if name is None:
            return "", {"refused": WORDS["unusable"]}
        field = self._capturing
        self._end()
        note = self._apply(field, name)
        caps = _caps()["caps_for"](name)
        return note, {"chosen": caps[0] if caps else None}

    def _end(self, resume_only: bool = False) -> None:
        """The listening is over, however it ended: the app gets back the
        pause this place took, once (dashboard._resume_after_capture)."""
        with self._lock:
            if not resume_only:
                self._capturing = None
                self._watch_until = time.monotonic() + GRACE_S
            elif self._capturing:
                self._capturing = None
            if not self._paused_for_capture:
                return
            self._paused_for_capture = False
            try:
                self._send("resume", timeout_ms=1500)
            except Exception as e:        # noqa: BLE001
                log.warning("web desk: could not resume after a key capture: %s",
                            type(e).__name__)

    def _apply(self, field: str, key: str) -> str:
        """dashboard._apply_key: live when it runs, the files when it
        does not — checked first either way, and answered with a
        sentence."""
        if self.running:
            reply = self._send("rebind", timeout_ms=4000, field=field, key=key)
            if reply is None:
                return NOT_RUNNING
            if not reply.get("ok"):
                return str(reply.get("error") or "that did not work")[:300]
            self._poll()                  # the board relights from the app's own keys
            return str(reply.get("message") or config_mod.rebound_sentence(field, key))
        try:
            current = config_mod.load_layered()
            config_mod.check_hotkeys(config_mod.with_field(current, field, key))
        except config_mod.ConfigError as e:
            return str(e)[:300]           # the sentence that refuses the key
        except Exception as e:            # noqa: BLE001
            return f"could not read the settings ({type(e).__name__})"
        try:
            config_mod.save({NESTED_HOTKEYS.get(field, field): key})
        except Exception as e:            # noqa: BLE001
            return f"could not save that ({type(e).__name__})"
        return config_mod.rebound_sentence(field, key)

    # -- the watch: the lease, and the desk's menu mode

    def _watch(self) -> None:
        if self._watcher is not None and self._watcher.is_alive():
            return
        self._watcher = threading.Thread(target=self._watching, daemon=True,
                                         name="keys-capture-watch")
        self._watcher.start()

    def _watching(self) -> None:
        while True:
            with self._lock:
                now = time.monotonic()
                if self._capturing and now > self._lease:
                    log.info("web desk: the page stopped answering mid key capture "
                             "— resuming")
                    self._end()
                listening = bool(self._capturing)
                if not listening and now > self._watch_until:
                    self._watcher = None
                    return
            try:
                self._menu_out()
            except Exception:             # noqa: BLE001
                pass
            time.sleep(WATCH_S)


def _at_exit(ref) -> None:
    """The window closed: give back a pause a listening took. The lock is
    waited for a moment and no longer — a pipe call that is hanging must
    not hold the process open."""
    place = ref()
    if place is None or not place._paused_for_capture:
        return
    if place._lock.acquire(timeout=2.0):
        try:
            place._end(resume_only=True)
        finally:
            place._lock.release()


def key_name(arg) -> str | None:
    """What the page heard -> the name config.toml would hold, or None.

    `arg` is {"vk": e.keyCode, "side": "left"|"right"|"", "mods": [...]}:
    the virtual-key code is what the hook matches on (and what Tk's
    keycode was), the side is what only the event's code knows for a
    modifier, and the modifiers are the groups that were down. Anything
    else — a bad shape, an unknown modifier, a code outside a byte — is
    None, and None is "not a key this can use"."""
    if not isinstance(arg, dict) or set(arg) - {"vk", "side", "mods"}:
        return None
    vk, side, mods = arg.get("vk"), arg.get("side", ""), arg.get("mods", [])
    if isinstance(vk, bool) or not isinstance(vk, int) or not 0 < vk < 255:
        return None
    if side not in SIDES or not isinstance(mods, list) or len(mods) > len(MOD_GROUPS):
        return None
    if any(m not in MOD_GROUPS for m in mods):
        return None
    held = frozenset(MOD_GROUPS[m] for m in mods)
    pair = hotkey_mod._SIDES.get(vk)

    def probe(code: int):
        if pair is None or not side:
            return None
        return pair[1] if side == "right" else pair[0]

    try:
        name = hotkey_mod.binding_name_from_event("", vk, probe=probe, mods=held)
        if name is None:
            return None
        hotkey_mod.parse_binding(name)
    except (ValueError, KeyError):
        return None
    return name


def _broken(text: str, at: str) -> list[str]:
    """A note in two lines, broken before the word `at` (its last use)."""
    words = text.split(" ")
    for i in range(len(words) - 1, 0, -1):
        if words[i] == at:
            return [" ".join(words[:i]), " ".join(words[i:])]
    return [text]


def _safe_caps() -> list[str]:
    """The caps the app cannot bind at all, generated (keycaps.offered)."""
    return [c for c in _caps()["offered"]() if c]


# ------------------------------------------------------- the menu mode

_user32 = None


def _u32():
    """A private user32: argtypes declared on the process-wide windll
    handle change them for every module (AGENTS.md)."""
    global _user32
    if _user32 is None:
        u = ctypes.WinDLL("user32", use_last_error=True)
        u.EnumWindows.argtypes = [_ENUM, wintypes.LPARAM]
        u.GetWindowThreadProcessId.argtypes = [wintypes.HWND,
                                               ctypes.POINTER(wintypes.DWORD)]
        u.GetWindowThreadProcessId.restype = wintypes.DWORD
        u.GetGUIThreadInfo.argtypes = [wintypes.DWORD, ctypes.POINTER(_GUITHREADINFO)]
        u.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM,
                                   wintypes.LPARAM]
        _user32 = u
    return _user32


class _GUITHREADINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("flags", wintypes.DWORD),
                ("hwndActive", wintypes.HWND), ("hwndFocus", wintypes.HWND),
                ("hwndCapture", wintypes.HWND), ("hwndMenuOwner", wintypes.HWND),
                ("hwndMoveSize", wintypes.HWND), ("hwndCaret", wintypes.HWND),
                ("rcCaret", wintypes.RECT)]


_ENUM = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
GUI_INMENUMODE = 0x0004
WM_KEYDOWN, WM_KEYUP, VK_ESCAPE = 0x0100, 0x0101, 0x1B


def menu_out() -> int:
    """End the menu mode a window of THIS process is in, with one Esc to
    the window that owns the menu — what a person's own Esc does. Returns
    how many it ended. Never touches another process's window."""
    u = _u32()
    pid = os.getpid()
    threads: set[int] = set()

    def each(hwnd, _lp):
        owner = wintypes.DWORD()
        thread = u.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == pid:
            threads.add(thread)
        return True

    u.EnumWindows(_ENUM(each), 0)
    ended = 0
    for thread in threads:
        info = _GUITHREADINFO()
        info.cbSize = ctypes.sizeof(info)
        if not u.GetGUIThreadInfo(thread, ctypes.byref(info)):
            continue
        if not (info.flags & GUI_INMENUMODE) or not info.hwndMenuOwner:
            continue
        owner = wintypes.DWORD()
        u.GetWindowThreadProcessId(info.hwndMenuOwner, ctypes.byref(owner))
        if owner.value != pid:
            continue
        u.PostMessageW(info.hwndMenuOwner, WM_KEYDOWN, VK_ESCAPE, 0x00010001)
        u.PostMessageW(info.hwndMenuOwner, WM_KEYUP, VK_ESCAPE, 0xC0010001)
        ended += 1
    if ended:
        log.info("web desk: the window dropped into the menu mode while a key "
                 "was listened for — ended it")
    return ended
