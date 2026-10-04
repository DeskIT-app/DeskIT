"""One cloud key, as a row a person can read: the wizard's cloud-keys
page and Settings > Privacy > Your cloud keys draw the same thing.

The store walk of 2026-10-03 (item 14): after a working Groq key was
saved the field was EMPTY again under an active [Save key] — it read as
if nothing had been saved and invited a second key. So a key that is
stored LOCKS: the field shows a fixed row of dots, cannot be typed into,
and [Change key] stands beside it. Change opens the empty field with
[Save] and [Cancel]; Cancel goes back to the lock with the old key still
saved, and a new key the provider refuses gives the old one back
(secretstore.trial). Removing a key with no new one is Settings >
Privacy's [Remove]; in the wizard the card's switch off already means
"don't use it".

The dots are DOTS — the same string for every key, never derived from
the value (not its length, not its last four). Whether a key is there is
asked of secretstore by name and the value dropped on the floor (AGENTS:
a secret lives in secretstore.py and net.py only). The check is the one
`key-test` request through net.py, by name, on a thread; the answer is
polled from the Tk side so a test driving update() sees it land.
"""
from __future__ import annotations

import json
import logging
import threading
import tkinter as tk

import ui

log = logging.getLogger("app")

#: What a locked field shows. Fixed on purpose: see the docstring.
DOTS = "•" * 16

PROVIDERS = {
    "groq": {"label": "Groq", "get": "https://console.groq.com/keys",
             "get_words": "Get a free key at console.groq.com/keys",
             "shape": "Groq keys start with gsk_ and hold only English letters and digits."},
    "gemini": {"label": "Gemini", "get": "https://aistudio.google.com/apikey",
               "get_words": "Get a free key at aistudio.google.com/apikey",
               "shape": "A key holds only English letters, digits, - and _."},
}

WORDS = {
    "placeholder": "Paste your {label} key here",
    "save": "Save key",
    "save.short": "Save",
    "change": "Change key",
    "cancel": "Cancel",
    "saved": "✓  Key works — saved in {where}.",
    "kept": "Saved in {where}.",
    "checking": "Checking the key with {label}…",
    "checking.saved": "Checking the saved key with {label}…",
    "changing": "The saved key keeps working until a new one is saved. Cancel keeps it.",
    "empty": "Nothing to save — paste the key first.",
    "notkey": "That does not look like a {label} key. {shape} Paste it again.",
    "refused": "{label} did not accept this key — check it and paste it again.",
    "refused.kept": "{label} did not accept that key — the saved one is kept.",
    "offline": ("Could not reach {label} right now — the key is saved and is checked "
                "the first time it is used."),
    "failed": "Could not store the key: {error}",
}


class KeyRefused(Exception):
    """The provider answered, and the answer was no (a 4xx): the key is wrong."""


def looks_like_key(value: str) -> bool:
    """What an API key can be: printable ASCII with no spaces. Not a
    check of the key — the provider does that — a check that it CAN be
    one, so Hebrew or a sentence pasted by mistake is said so at once
    (a non-ASCII value in a header came back as a codec error dressed as
    "could not reach Groq", the owner's walk of 2026-09-19)."""
    return (bool(value) and value.isascii() and value.isprintable()
            and not any(ch.isspace() for ch in value))


def probe(name: str) -> int:
    """How many models the stored key can see — the one `key-test`
    call. KeyRefused on a 4xx (the key itself), any other error for the
    road (offline, a 5xx)."""
    import net
    if name == "groq":
        status, _h, body = net.request(
            "GET", "https://api.groq.com/openai/v1/models", "key-test",
            secret="groq", timeout_s=20)
    else:
        status, _h, body = net.request(
            "GET", f"{net.GEMINI_BASE_URL}v1beta/models?pageSize=200", "key-test",
            secret="gemini", timeout_s=20)
    if 400 <= status < 500:
        raise KeyRefused(f"HTTP {status}")
    if status != 200:
        raise RuntimeError(f"HTTP {status}")
    data = json.loads(body.decode("utf-8"))
    items = data.get("data") if name == "groq" else data.get("models")
    return len(items or [])


def stored(name: str) -> tuple[bool, str]:
    """(is there a key, where) — the value is never kept."""
    import secretstore
    try:
        key, source = secretstore.find_key(name)
    except Exception:                                        # noqa: BLE001
        return False, ""
    there = bool(key)
    del key
    return there, source


def _where(source: str) -> str:
    """'Windows Credential Manager (DeskIT/groq)' → the plain place."""
    return source.split(" (")[0] if source.startswith("Windows") else source


class KeyRow(tk.Frame):
    """The field, its buttons, one line under them and — while no key is
    saved — the way to a free one.

    ``state`` is locked | open | changing | testing; ``verdict`` is the
    last check's word (ok | bad | offline | "" before any). ``on_state``
    is told both whenever either changes — the wizard's Next waits on it.
    ``probe`` is the check (tests hand in a fake); ``show_link`` draws the
    way to a free key under an open field; ``check_saved`` checks
    a key that was already saved when the row is built (the wizard does,
    so its Next is honest; Settings shows the lock and checks on Change).
    """

    POLL_MS = 100

    def __init__(self, parent, name: str, *, width: int, bg: str = ui.CARD,
                 on_state=None, probe=probe, check_saved: bool = False,
                 show_link: bool = True):
        super().__init__(parent, bg=bg)
        self.name = name
        self.words = PROVIDERS[name]
        self._bg = bg
        self._width = width
        self._on_state = on_state
        self._show_link = show_link
        self._probe = probe
        self._answer: tuple[str, str] | None = None
        self._replacing = False
        self.verdict = ""
        self.state = "open"

        self.line = tk.Frame(self, bg=bg)
        self.line.pack(fill="x")
        self.buttons_w = 2 * 100 + 8
        self.field = ui.Field(self.line, w=width - self.buttons_w - 10, h=34, bg=bg,
                              justify="left", pt=10,
                              placeholder=WORDS["placeholder"].format(**self.words))
        self.field.pack(side="left", padx=(0, 10))
        self.field.entry.configure(show="•")
        self.field.bind_entry("<Return>", lambda _e: self.save())
        self.buttons = tk.Frame(self.line, bg=bg)
        self.buttons.pack(side="left")
        self.note = tk.Label(self, text="", bg=bg, fg=ui.DIM, font=(ui.UI, 9),
                             anchor="w", justify="left", wraplength=width)
        self.note.pack(fill="x", pady=(6, 0))
        self.link = tk.Label(self, text=self.words["get_words"], bg=bg,
                             fg=ui.ACCENT_TEXT, font=(ui.UI, 9, "underline"),
                             cursor="hand2", anchor="w")
        self.link.bind("<Button-1>", lambda _e: self._open(self.words["get"]))

        there, source = stored(name)
        if there and check_saved:
            self._lock(say=("checking.saved", ui.DIM))
            self._check()
        elif there:
            self._lock(say=("kept", ui.DIM), where=_where(source))
        else:
            self._open_field()

    # ------------------------------------------------------------ the states
    def _say(self, key: str, colour: str, **fmt) -> None:
        self.note.configure(text=WORDS[key].format(**{**self.words, **fmt}), fg=colour)

    def _set_buttons(self, *specs) -> None:
        for child in self.buttons.winfo_children():
            child.destroy()
        for i, (text, command, primary) in enumerate(specs):
            # one button at the width the owner approved in the picture
            # (2026-10-03); two share the room the field leaves them
            w = 122 if len(specs) == 1 else (self.buttons_w - 8) // 2
            ui.Button(self.buttons, text, command, bg=self._bg, primary=primary,
                      quiet=not primary, w=w, h=34).pack(
                side="left", padx=(0, 8 if i < len(specs) - 1 else 0))

    def _field_locked(self, locked: bool) -> None:
        entry = self.field.entry
        entry.configure(state="normal")
        self.field.set(DOTS if locked else "")
        entry.configure(show="" if locked else "•")
        if locked:
            entry.configure(state="disabled")

    def _lock(self, say: tuple[str, str] | None = None, where: str = "") -> None:
        self.state = "locked"
        self._field_locked(True)
        self._set_buttons((WORDS["change"], self.change, False))
        self.link.pack_forget()
        if say:
            self._say(say[0], say[1],
                      where=where or "Windows Credential Manager")
        self._tell()

    def _open_field(self) -> None:
        self.state = "open"
        self._field_locked(False)
        self._set_buttons((WORDS["save"], self.save, True))
        self.note.configure(text="")
        if self._show_link:
            self.link.pack(fill="x", pady=(6, 0))
        self._tell()

    def change(self) -> None:
        """[Change key]: the empty field, Save and Cancel; the saved key
        keeps working meanwhile."""
        self.state = "changing"
        self._field_locked(False)
        self._set_buttons((WORDS["save.short"], self.save, True),
                          (WORDS["cancel"], self.cancel, False))
        self._say("changing", ui.DIM)
        if self._show_link:
            self.link.pack(fill="x", pady=(6, 0))
        try:
            self.field.entry.focus_set()
        except tk.TclError:
            pass
        self._tell()

    def cancel(self) -> None:
        self.field.set("")
        self._lock(say=("kept", ui.DIM))

    def _tell(self) -> None:
        if self._on_state is not None:
            try:
                self._on_state(self.state, self.verdict)
            except Exception:                                # noqa: BLE001
                log.exception("a key row's listener failed")

    # -------------------------------------------------------- save and check
    def save(self) -> None:
        """The pasted value into the store — never into a file — the
        field emptied either way, and the key checked at once."""
        import secretstore
        if self.state not in ("open", "changing"):
            return
        value = self.field.get().strip()
        self.field.set("")
        if not value:
            self._say("empty", ui.AMBER)
            return
        if not looks_like_key(value):
            del value
            self._say("notkey", ui.RED)
            return
        try:
            self._replacing = secretstore.trial(self.name, value)
        except Exception as e:                               # noqa: BLE001
            del value
            self._say("failed", ui.RED, error=e)
            return
        del value
        self._say("checking", ui.DIM)
        self._check()

    def _check(self) -> None:
        self.state = "testing"
        self._set_buttons()
        self._tell()
        self._answer = None
        probe_ = self._probe

        def work() -> None:
            try:
                probe_(self.name)
            except (KeyRefused, UnicodeEncodeError) as e:
                self._answer = ("bad", str(e))
            except Exception as e:                           # noqa: BLE001
                self._answer = ("offline", str(e)[:120])
            else:
                self._answer = ("ok", "")

        threading.Thread(target=work, daemon=True, name=f"key-test-{self.name}").start()
        self.after(self.POLL_MS, self._poll)

    def _poll(self) -> None:
        if not self.winfo_exists():
            return
        if self._answer is None:
            self.after(self.POLL_MS, self._poll)
            return
        word, detail = self._answer
        self._answer = None
        self.checked(word, detail)

    def checked(self, word: str, detail: str = "") -> None:
        """The provider's answer: ok locks, a refusal gives back the key
        that was saved before (or opens the field when there was none),
        no answer keeps the key — the cloud checks it on first use."""
        import secretstore
        log.info("%s key test said %s (%s)", self.name, word, detail)
        self.verdict = word
        try:
            if word == "bad":
                kept = secretstore.trial_failed(self.name)
            else:
                secretstore.trial_passed(self.name)
                kept = True
        except Exception:                                    # noqa: BLE001
            log.warning("the %s key trial could not be settled", self.name, exc_info=True)
            kept = word != "bad"
        self._replacing = False
        if word == "ok":
            self._lock(say=("saved", ui.GREEN))
        elif word == "offline":
            self._lock(say=("offline", ui.AMBER))
        elif kept:
            self._lock(say=("refused.kept", ui.RED))
        else:
            self._open_field()
            self._say("refused", ui.RED)

    @staticmethod
    def _open(url: str) -> None:
        import webbrowser
        try:
            webbrowser.open(url)
        except Exception:                                    # noqa: BLE001
            log.info("could not open %s", url)
