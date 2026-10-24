"""YOUR CLOUD KEYS on the web desk's Settings > Privacy — keyrow.KeyRow,
the Tk desk's and the wizard's row, as a state the page draws.

ONE FILE FOR THE ONE SECRET THE PAGE HANDS OVER. A key pasted into the
page travels once — the page's field, the web message, `Keys.save` — and
goes straight into secretstore.trial, the road keyrow.KeyRow.save takes:
the value is held in one local variable for that call and deleted, never
logged, never put in an answer, never kept on the object. Whether a key
is there is asked of secretstore by name (keyrow.stored drops the value
on the floor); the check is keyrow.probe, the one `key-test` request
through net.py BY NAME, on a thread of its own. Nothing here imports a
transport.

The row's states are keyrow's: locked (a key is saved: a fixed row of
dots, [Change key]), open (no key: the field, [Save key]), changing (the
field, [Save] [Cancel] — the saved key keeps working meanwhile), testing
(no buttons until the provider answers). The words are keyrow.WORDS.
keyrow imports tkinter and ui at its top; neither builds a window, and it
is imported only when a key row is first drawn.
"""
from __future__ import annotations

import logging
import threading

log = logging.getLogger("app")

#: The two providers, in the Tk desk's order (dashboard.KEY_PROVIDERS):
#: (name, label, where a free key is, why one would want it).
PROVIDERS = (("groq", "Groq", "https://console.groq.com",
              "recommended first: one key unlocks the repair pass, punctuation, "
              "lookup, translation and, without an NVIDIA card, cloud transcription"),
             ("gemini", "Gemini", "https://aistudio.google.com",
              "for translation and ask-the-screen"))
NAMES = tuple(name for name, *_rest in PROVIDERS)


class Keys:
    """The two rows, for one window. `nudge` is called when a key was
    just stored and is being checked (dashboard._key_state: the account's
    other PCs get it sealed); `say` takes a sentence for the toast."""

    def __init__(self, nudge=None, say=None, probe=None) -> None:
        self._lock = threading.RLock()
        self._rows: dict[str, dict] = {}
        self._nudge = nudge or (lambda: None)
        self._say = say or (lambda text: None)
        self._probe = probe            # None: keyrow.probe (tests hand in a fake)

    # ------------------------------------------------------------ reading

    @staticmethod
    def _keyrow():
        import keyrow
        return keyrow

    def _row(self, name: str) -> dict:
        """The row as it stands, built on its first look: locked when a
        key is stored (where it is kept, never what it is), open when
        not — keyrow.KeyRow's __init__ with check_saved=False, which is
        what Settings draws."""
        row = self._rows.get(name)
        if row is None:
            kr = self._keyrow()
            there, source = kr.stored(name)
            row = {"state": "open", "verdict": "", "say": "", "tone": "dim"}
            if there:
                self._lock_row(row, name, ("kept", "dim"), kr._where(source))
            self._rows[name] = row
        return row

    def _words(self, name: str, key: str, **fmt) -> str:
        kr = self._keyrow()
        words = kr.PROVIDERS[name]
        return kr.WORDS[key].format(**{**words, **fmt})

    def _lock_row(self, row: dict, name: str, say=None, where: str = "") -> None:
        row["state"] = "locked"
        if say:
            row["say"] = self._words(name, say[0], where=where or "Windows Credential Manager")
            row["tone"] = say[1]

    def read(self) -> list[dict]:
        """What the card draws, provider by provider. No value, ever:
        the dots are keyrow.DOTS, the same string for every key."""
        import secretstore
        kr = self._keyrow()
        out = []
        with self._lock:
            for name, label, url, why in PROVIDERS:
                row = self._row(name)
                state = row["state"]
                buttons = {"locked": [("Change key", "key.change", False)],
                           "open": [("Save key", "key.save", True)],
                           "changing": [("Save", "key.save", True),
                                        ("Cancel", "key.cancel", False)],
                           "testing": []}[state]
                out.append({
                    "name": name, "label": label, "get": url, "why": why,
                    "state": state,
                    "dots": kr.DOTS if state in ("locked", "testing") else "",
                    "placeholder": kr.WORDS["placeholder"].format(label=label),
                    "buttons": [{"label": t, "do": d, "primary": p} for t, d, p in buttons],
                    "say": row["say"], "tone": row["tone"],
                    "storage": secretstore.storage_sentence(name),
                })
        return out

    # ------------------------------------------------------------- acting

    def change(self, name: str) -> str:
        with self._lock:
            row = self._row(name)
            if row["state"] != "locked":
                return ""
            row["state"] = "changing"
            row["say"], row["tone"] = self._words(name, "changing"), "dim"
        return ""

    def cancel(self, name: str) -> str:
        with self._lock:
            row = self._row(name)
            if row["state"] != "changing":
                return ""
            self._lock_row(row, name, ("kept", "dim"))
        return ""

    def save(self, name: str, arg: dict) -> str:
        """[Save key] / [Save]: the pasted value into the store — never a
        file — and checked at once (keyrow.KeyRow.save). `arg` is the
        page's {name, value}; the value is taken OUT of it, so nothing
        that outlives this call still holds it."""
        import secretstore
        kr = self._keyrow()
        value = arg.pop("value", "")
        value = value.strip() if isinstance(value, str) else ""
        with self._lock:
            row = self._row(name)
            if row["state"] not in ("open", "changing"):
                del value
                return ""
            if not value:
                row["say"], row["tone"] = self._words(name, "empty"), "warn"
                return ""
            # no provider's key is near 512 characters: a page that pastes
            # a megabyte is answered at once, before any pattern reads it
            if len(value) > 512 or not kr.looks_like_key(value):
                del value
                row["say"], row["tone"] = self._words(name, "notkey",
                                                      shape=kr.PROVIDERS[name]["shape"]), "bad"
                return ""
            try:
                secretstore.trial(name, value)
            except Exception as e:                           # noqa: BLE001
                del value
                row["say"], row["tone"] = self._words(name, "failed", error=type(e).__name__), "bad"
                return ""
            del value
            row["state"] = "testing"
            row["say"], row["tone"] = self._words(name, "checking"), "dim"
        try:
            self._nudge()
        except Exception:                                    # noqa: BLE001
            log.info("could not nudge the account about the %s key", name)
        self._check(name)
        return ""

    def _check(self, name: str) -> None:
        probe = self._probe or self._keyrow().probe
        kr = self._keyrow()

        def work() -> None:
            try:
                probe(name)
            except (kr.KeyRefused, UnicodeEncodeError) as e:
                word, detail = "bad", type(e).__name__
            except Exception as e:                           # noqa: BLE001
                word, detail = "offline", type(e).__name__
            else:
                word, detail = "ok", ""
            self.checked(name, word, detail)

        threading.Thread(target=work, daemon=True, name=f"key-test-{name}").start()

    def checked(self, name: str, word: str, detail: str = "") -> None:
        """The provider's answer (keyrow.KeyRow.checked): ok locks, a
        refusal gives back the key that was saved before (or opens the
        field when there was none), no answer keeps the key — the cloud
        checks it on first use."""
        import secretstore
        log.info("%s key test said %s (%s)", name, word, detail)
        try:
            if word == "bad":
                kept = secretstore.trial_failed(name)
            else:
                secretstore.trial_passed(name)
                kept = True
        except Exception:                                    # noqa: BLE001
            log.warning("the %s key trial could not be settled", name)
            kept = word != "bad"
        with self._lock:
            row = self._row(name)
            row["verdict"] = word
            if word == "ok":
                self._lock_row(row, name, ("saved", "ok"))
            elif word == "offline":
                self._lock_row(row, name, ("offline", "warn"))
            elif kept:
                self._lock_row(row, name, ("refused.kept", "bad"))
            else:
                row["state"] = "open"
                row["say"], row["tone"] = self._words(name, "refused"), "bad"
        self._say(row["say"])

    def remove(self, name: str) -> str:
        """[Remove] (dashboard._key_remove): out of the store, the field
        open again."""
        import secretstore
        with self._lock:
            row = self._row(name)
            try:
                had = secretstore.delete(name)
            except Exception as e:                           # noqa: BLE001
                row["say"], row["tone"] = f"could not remove the key: {type(e).__name__}", "bad"
                return ""
            row["state"] = "open"
            row["say"], row["tone"] = ("no key" if had else "no key to remove"), "faint"
        return (f"{name}: the key is gone from Windows Credential Manager"
                if had else f"{name}: there was no key")
