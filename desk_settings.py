"""Settings on the web desk: the forty-odd lines of defaults.toml a person
changes, on eight tabs, each said in plain words — and the cards that sit
between them — as the Tk desk draws them in Dashboard._screen_settings.

THE SAME SOURCES AND THE SAME WORDS. settings.py reads the file for the
values, the choices and the help; settings.TABS says which lines are drawn
at all, with what label, what sentence and what names on the menu (the
owner, 2026-09-18: "I am the user; you are the developer"). LAYOUT says
what each tab draws and in what order, cards and rows together — it is
dashboard.LAYOUT, spelled here so this window never imports the Tk desk,
and a test holds the two equal. Every sentence a card says is the Tk
card's own (dashboard._paint_dot, _paint_account, _paint_lock, ...).

WRITES GO WHERE THE TK DESK SENDS THEM. A line: through the running app's
`option` verb when it runs (it writes the line and takes the change live
where it can, main.set_option), straight into config.save otherwise —
never a TOML round trip (AGENTS rule 6). A key: `rebind`, or
config.check_hotkeys + config.save. The dot, the account, the lock, the
tour, the screens, a test notification: their pipe verbs. A consent gate
is never a setting: it closes with privacy.withdraw, a stale one says yes
again with privacy.grant (Home's own [Turn on]), a shut sync asks the app
for its card — exactly the three doors dashboard._draw_consent_row has.

EVERYTHING FROM THE PAGE IS UNTRUSTED. `do` is one of ACTS; a path must
be a line settings.TABS draws (and not a gate); a value must be the kind
the file holds and, for a menu, one of the menu's own values; a folder
changes only through Windows' own folder dialog, opened here, so no
string from the page ever becomes a place files are written; a provider,
a consent kind, a cue, a paper, a file to open, a URL are each checked
against a fixed list. A failure answers with the exception's type, never
its text. The cloud keys are desk_settings_keys.py; the Network screen
is desk_settings_net.py.

WHAT THE PAGE IS ANSWERED. read() is every tab at once — the page
switches tabs without a round trip — plus the one-shot note (a check that
finished, a key the provider answered, the dot back in its place);
read(q=...) is the search, tab by tab; read(net=1, host=, loopback=) is
the Network screen. act(do, arg) does one button and answers with the
place again (read()), so a press is drawn from the truth at once.

HOW IT IS REACHED. deskweb.Api.place("settings", op, args), one Place per
window with the window's pipe function (`send`, control.send's
signature). Calls come on threads of their own: the Place holds a lock.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from pathlib import Path

import config as config_mod
import paths
import settings as settings_mod

log = logging.getLogger("app")

# ------------------------------------------------------------- the layout

#: The route's sub for each tab: #/settings/privacy.
SLUGS: dict[str, str] = {
    settings_mod.GENERAL: "general", settings_mod.DICTATION: "dictation",
    settings_mod.SCREEN: "screen", settings_mod.MESSAGES: "messages",
    settings_mod.PHONE: "phone", settings_mod.ACCOUNT: "account",
    settings_mod.PRIVACY: "privacy", settings_mod.ABOUT: "about",
}

#: What each tab draws, in order — dashboard.LAYOUT (a test holds them
#: equal). A name in capitals is a group of settings.TABS, drawn as a card
#: of rows; anything else is a card of its own.
LAYOUT: dict[str, tuple[str, ...]] = {
    settings_mod.GENERAL: ("dot", "ON THE SCREEN", "THIS COMPUTER",
                           "WHERE FILES ARE SAVED", "updates", "awake"),
    settings_mod.DICTATION: ("WHERE YOUR SPEECH BECOMES WORDS", "model",
                             "WHEN YOU DICTATE", "WORDS IT LEARNS",
                             "THE TRANSLATE KEY"),
    settings_mod.SCREEN: ("recording", "SCREENSHOTS AND RECORDINGS",
                          "snip", "THE CAMERA", "ASK ABOUT THE SCREEN",
                          "voice"),
    settings_mod.MESSAGES: ("MESSAGES FROM OTHER PROGRAMS", "claude",
                            "sounds"),
    settings_mod.PHONE: ("phone", "DICTATING FROM THE PHONE"),
    settings_mod.ACCOUNT: ("account", "WHAT THE ACCOUNT MAY DO", "lock"),
    settings_mod.PRIVACY: ("keys", "WHAT MAY LEAVE THIS PC",
                           "connections", "said_file", "KEPT ON THIS PC"),
    settings_mod.ABOUT: ("version", "about", "files"),
}

#: The lines a card above the rows draws for itself (dashboard.BLOCK_PATHS).
BLOCK_PATHS: dict[str, frozenset] = {
    settings_mod.GENERAL: frozenset({"dot.corner", "privacy.update_check"}),
}

#: The folder settings: a field for the path as it stands, and [Browse…]
#: (dashboard.FOLDER_SETTINGS).
FOLDER_SETTINGS = frozenset({"capture.folder", "capture.clip_folder"})

#: A card's name in the left column, and its glyph (the page's own map).
#: The words are the Tk card's eyebrow, said in sentence case the way the
#: approved picture says "The dot", "Updates", "Awake".
BLOCK_TITLES: dict[str, tuple[str, str]] = {
    "dot": ("The dot", "monitor"), "updates": ("Updates", "sync"),
    "awake": ("Awake", "moon"), "model": ("The speech model", "chip"),
    "recording": ("Screen recording", "video"),
    "snip": ("The Snipping-Tool key", "keyboard"),
    "voice": ("No Hebrew voice", "warning"), "claude": ("Claude Code", "message"),
    "sounds": ("Every sound it makes", "volume"), "phone": ("The phone", "phone"),
    "account": ("Account", "contact"), "lock": ("The lock", "lock"),
    "keys": ("Your cloud keys", "key"), "connections": ("Every connection", "globe"),
    "said_file": ("What you said", "file"), "version": ("DeskIT", "info"),
    "about": ("About", "help"), "files": ("Files", "folder"),
}
GROUP_GLYPHS: dict[str, str] = {
    "ON THE SCREEN": "eye", "THIS COMPUTER": "laptop",
    "WHERE FILES ARE SAVED": "folder", "WHERE YOUR SPEECH BECOMES WORDS": "mic",
    "WHEN YOU DICTATE": "mic", "WORDS IT LEARNS": "book",
    "THE TRANSLATE KEY": "globe", "SCREENSHOTS AND RECORDINGS": "camera",
    "THE CAMERA": "camera", "ASK ABOUT THE SCREEN": "help",
    "MESSAGES FROM OTHER PROGRAMS": "bell", "DICTATING FROM THE PHONE": "phone",
    "WHAT THE ACCOUNT MAY DO": "contact", "WHAT MAY LEAVE THIS PC": "globe",
    "KEPT ON THIS PC": "history",
}

#: What each cue is FOR (dashboard.SOUND_WORDS; a test holds them equal).
SOUND_WORDS: dict[str, str] = {
    "ready": "Ready to dictate", "start": "Recording started",
    "stop": "Recording ended", "latch": "The key locked on",
    "error": "Something went wrong", "bye": "The app stopped",
    "translating": "Translating", "translated": "Translation in place",
    "punctuating": "Punctuating", "punctuated": "Punctuation in place",
    "looking": "Looking a word up", "looked": "The answer is here",
    "repaired": "A word was fixed for you", "noop": "Nothing to do",
    "paused": "The keys are paused", "resumed": "The keys are back",
    "shot": "Screenshot taken", "recording": "Screen recording started",
    "recorded": "Screen recording saved", "notify": "A message arrived",
}

SNIP_KEY, PLAIN_SNIP_KEY = "win+shift+s", "ctrl+f11"
#: How long the window stays hidden while the dot is dragged
#: (dashboard.DOT_WAIT_S): the app gives up first; this is the backstop.
DOT_WAIT_S = 210.0
PAGES_URL = paths.PAGES_URL
ISSUES_URL = "https://github.com/DeskIT-app/DeskIT/issues/new/choose"
MODEL_CARD_URL = "https://huggingface.co/ivrit-ai/whisper-large-v3-turbo-ct2"
#: dashboard._open_url's allowlist: nothing else is opened in a browser.
URL_PREFIXES = ("https://github.com/", "https://deskit-app.github.io/",
                "https://huggingface.co/", "https://console.groq.com",
                "https://aistudio.google.com")

#: Every button the page may press (the dispatch below is the rest).
ACTS = frozenset({
    "set", "browse", "file.open",
    "dot.move", "dot.corner",
    "update.check", "update.install", "update.winget", "update.notes",
    "awake.screens", "awake.check",
    "model.download", "model.redownload", "model.delete",
    "pack.install", "pack.remove", "pack.retry",
    "snip", "speech.open",
    "claude.flip", "claude.keep", "claude.take",
    "cue.play", "notify.test",
    "phone.copy",
    "account.do", "account.ask", "account.keep",
    "lock.do", "lock.type", "lock.recover", "lock.new", "lock.copy", "lock.done",
    "consent.withdraw", "consent.on", "consent.sync",
    "key.save", "key.change", "key.cancel", "key.remove",
    "net.log", "said.open", "url",
    "paper", "diagnostics.copy", "quit", "tour",
})
#: The account verbs a button may send (dashboard._paint_account).
ACCOUNT_DOS = {"google": "opening the browser",
               "anonymous": "creating an anonymous account",
               "signout": "signing out on this PC",
               "signout_all": "signing out of every PC",
               "delete": "deleting"}
#: The lock verbs (dashboard._paint_lock) and what each says when it worked.
LOCK_DOS = {"approve": "approving", "decline": "declined",
            "lock_answer": None, "lock_restore": "put back"}
#: Files a button opens, by the name the page knows them by.
FILES = ("app_log", "settings", "folder", "transcripts", "network_log")
#: The papers on About (dashboard._about_rows), in its order.
PAPERS = ("Licence", "Trademark", "Third-party notices", "Network",
          "Privacy policy", "Terms", "Report a security issue",
          "Report on GitHub", "Copy diagnostics")
#: Every string in an answer from the page is cut here first: a field's
#: line is a camera name or a language, never an essay.
MAX_TEXT = 300


def _sentence_case(title: str) -> str:
    """'KEPT ON THIS PC' -> 'Kept on this PC' (the approved picture's names:
    "On the screen", "This computer")."""
    words = [w if w in ("PC", "DeskIT") else w.lower() for w in title.split()]
    text = " ".join(words)
    return text[:1].upper() + text[1:]


def _shown(value) -> str:
    """dashboard._shown: repr for a float so 6.0 stays 6.0."""
    if isinstance(value, float):
        return repr(value)
    return str(value)


def _shown_for(path: str, value) -> str:
    """dashboard._shown_for: a save folder as the FULL path it resolves to."""
    if path in FOLDER_SETTINGS and value:
        try:
            return str(paths.resolve_folder(str(value)))
        except Exception:                                    # noqa: BLE001
            pass
    return _shown(value)


def human_time(seconds: float) -> str:
    seconds = int(max(0, seconds))
    if seconds < 90:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m"
    return f"{seconds // 3600}h {(seconds % 3600) // 60:02d}m"


class Refused(ValueError):
    """What the page asked for is not something this place does."""


class Place:
    """Settings, as data, and what its buttons do. One per window."""

    def __init__(self, send) -> None:
        self._send = send
        self._lock = threading.RLock()
        self.status: dict = {}
        self.running = False
        self._silent_since: float | None = None
        self._sections_kept: tuple | None = None
        self._mics: list | None = None
        self._note_id = 0
        self._note_text = ""
        self._dot_waiting = 0.0
        self._update_line = ""          # a check or a download in flight
        self._update_busy = False
        self._awake_probe: dict | None = None
        self._awake_probing = False
        self._awake_checked = ""
        self._account_asking = ""       # "" | "delete" | "everywhere"
        self._lock_mode = ""            # "" | "typing" | "shown"
        self._lock_fresh = ""           # a recovery key just made, until Done
        self._claude_asking = False
        self._claude_state, self._claude_other = "none", None
        self._net = None
        self._keys = None
        # The slow half of a first look — the microphones (PortAudio, and
        # firstrun with Tk's ui behind it), keyrow, git's branch — is
        # imported beside the first read instead of in front of it: 0.57 s
        # of the first answer measured on this PC, 2026-10-24.
        self._warm = threading.Event()
        threading.Thread(target=self._warm_up, daemon=True, name="settings-warm").start()

    def _warm_up(self) -> None:
        try:
            for name in ("version", "hardware", "models", "packs", "updates", "awake",
                         "notify_hook", "cues", "keyrow"):
                try:
                    __import__(name)
                except Exception:                            # noqa: BLE001
                    log.info("web desk: %s did not import", name)
            self._microphones()
        finally:
            self._warm.set()

    # ================================================================ read

    def read(self, q=None, net=None, host="All", loopback=False) -> dict:
        with self._lock:
            if net:
                return self._network().read(host=str(host or "All")[:200],
                                            loopback=loopback is True)
            self._poll()
            sections = self._sections()
            if q is not None:
                return self._search(sections, str(q)[:MAX_TEXT])
            pages = {}
            for name, slug in SLUGS.items():
                pages[slug] = self._page(name, sections)
            return {
                "ok": True,
                "running": self.running,
                # the page asks again soon while the slow half is still coming
                "warming": not self._warm.is_set(),
                "tabs": [{"name": n, "slug": s} for n, s in SLUGS.items()],
                "pages": pages,
                "saved": "Changes are saved as you make them.",
                "note": {"id": self._note_id, "text": self._note_text},
            }

    def _say(self, text: str) -> None:
        """A sentence for the page's toast, delivered by the next read."""
        if text:
            with self._lock:
                self._note_id += 1
                self._note_text = str(text)

    def _poll(self) -> None:
        """The app's status — dashboard._poller's read, phone link and all:
        the phone card copies it from here and never hands it to the page."""
        import singleton
        reply = self._send("status", timeout_ms=1200)
        if reply is None and singleton.is_running():
            if self._silent_since is None:
                self._silent_since = time.monotonic()
            reply = {"ok": True, "stage": "starting", "activity": "starting",
                     "silent_s": time.monotonic() - self._silent_since}
        else:
            self._silent_since = None
        self.status = reply if isinstance(reply, dict) else {}
        self.running = bool(reply) and self.status.get("stage") == "running"

    def _sections(self):
        """settings.read over the person's layers, kept until one of the
        three files changes (it parses defaults.toml, 2 000 lines)."""
        files = (paths.DEFAULTS_FILE, paths.SETTINGS_FILE, paths.STATE_FILE)
        stamp = []
        for f in files:
            try:
                st = Path(f).stat()
                stamp.append((st.st_size, st.st_mtime_ns))
            except OSError:
                stamp.append(None)
        stamp = tuple(stamp)
        if self._sections_kept is not None and self._sections_kept[0] == stamp:
            return self._sections_kept[1]
        sections = settings_mod.read(
            paths.DEFAULTS_FILE,
            overrides=config_mod.read_settings(paths.SETTINGS_FILE)
            | config_mod.read_state(paths.STATE_FILE))
        self._sections_kept = (stamp, sections)
        return sections

    def _page(self, name: str, sections) -> list[dict]:
        groups = {g.title: g for g in settings_mod.groups_for(name)}
        out = []
        for entry in LAYOUT.get(name, ()):
            if not entry.isupper():
                try:
                    block = self._block(entry, sections)
                except Exception as e:                       # noqa: BLE001 — one card, not the page
                    log.warning("web desk: the %s card failed: %s", entry, type(e).__name__)
                    continue
                if block is not None:
                    title, glyph = BLOCK_TITLES[entry]
                    out.append({"id": entry, "title": title, "glyph": glyph, **block})
                continue
            group = groups.get(entry)
            if group is None:
                continue
            rows = [self._row(row, s) for row in group.rows
                    if (s := settings_mod.find(sections, row.path)) is not None
                    and s.path not in BLOCK_PATHS.get(name, frozenset())]
            if rows:
                out.append({"id": f"group:{entry}", "title": _sentence_case(entry),
                            "glyph": GROUP_GLYPHS.get(entry, "settings"),
                            "kind": "rows", "rows": rows})
        return out

    def _search(self, sections, query: str) -> dict:
        """What the magnifier finds (dashboard._fill_settings while
        searching): every drawn line that matches, one card per tab,
        titled with the tab's name so the answer says where it lives."""
        found = []
        for name in settings_mod.tab_names():
            rows = [self._row(row, s) for group in settings_mod.groups_for(name)
                    for row in group.rows
                    if (s := settings_mod.find(sections, row.path)) is not None
                    and settings_mod.matches(s, query)]
            if rows:
                found.append({"id": f"found:{SLUGS[name]}", "title": name,
                              "glyph": "search", "kind": "rows", "rows": rows})
        return {"ok": True, "q": query, "found": found,
                "none": "" if found else f"no setting matches {query!r}"}

    # ------------------------------------------------------------ the rows

    def _row(self, row, setting) -> dict:
        """One line: its plain label, its sentence and its control
        (dashboard._control)."""
        value = setting.value
        if setting.path == "auto_pause_fullscreen" and self.status.get(
                "auto_pause_fullscreen") is not None:
            # the one value the running app changes on its own (_paint_settings)
            value = bool(self.status["auto_pause_fullscreen"])
        out = {"path": setting.path, "label": row.label, "help": row.help}
        if setting.consent:
            out.update(ctl="consent", consent=self._consent_row(setting.key))
        elif setting.kind == "bool":
            out.update(ctl="switch", value=bool(value))
        elif not setting.editable:
            out.update(ctl="file", value=_shown(value))
        else:
            options = self._menu_for(row, setting)
            if options:
                held = self._held_mic(value) if setting.path == "audio.device" else value
                out.update(ctl="menu", value=held,
                           options=[{"v": v, "label": str(n)} for v, n in options])
            elif setting.path in FOLDER_SETTINGS:
                out.update(ctl="folder", value=_shown_for(setting.path, value))
            else:
                out.update(ctl="field", value=_shown(value),
                           num=setting.kind in ("int", "float"))
        return out

    def _microphones(self) -> list:
        """(what the file writes, a name) for every input device — the
        first-run setup's list (dashboard._microphones), asked once per
        window: PortAudio answers the same list until it is restarted.
        Listed by the warm-up; until it has, the menu holds what the file
        says and the system default."""
        if self._mics is None and threading.current_thread().name != "settings-warm":
            return []
        if self._mics is None:
            try:
                import firstrun
                devices = firstrun._devices()
            except Exception:                                # noqa: BLE001
                devices = []
            self._mics = ([("", "System default")]
                          + [(key, f"{name} — {api}")
                             for key, name, api, _index in devices])
        return list(self._mics)

    def _held_mic(self, value):
        """A config still holding a bare index is shown as the device it
        means (dashboard._menu_for)."""
        held = str(value or "")
        if held.isdigit():
            try:
                import firstrun
                for key, _name, _api, index in firstrun._devices():
                    if str(index) == held:
                        return key
            except Exception:                                # noqa: BLE001
                pass
        return held

    def _menu_for(self, row, setting) -> list:
        """(value, label) for a row's menu; [] = a field
        (dashboard._menu_for)."""
        if setting.path == "audio.device":
            mics = self._microphones()
            if len(mics) > 1:
                return mics
            if not self._warm.is_set():
                held = str(setting.value or "")
                return [("", "System default")] + ([(held, held)] if held else [])
        names = (list(row.names) if row is not None and row.names
                 else [(c, c) for c in setting.choices])
        try:
            import hardware as hardware_mod
            if hardware_mod.ollama_absent():
                held = str(setting.value)
                names = [(v, n) for v, n in names if v != "ollama" or held == "ollama"]
        except Exception:                                    # noqa: BLE001
            pass
        return names

    def _consent_row(self, kind: str) -> dict:
        """One of the [privacy] gates (dashboard._draw_consent_row): what
        the consent file says, and the one button that may change it."""
        import privacy
        try:
            row = next(s for s in privacy.status() if s["kind"] == kind)
        except Exception:                                    # noqa: BLE001
            row = {"open": False, "stale": False, "when": "", "gate": False}
        button = None
        if row["open"]:
            text, tone = f"On since {str(row.get('when', ''))[:10]}", "on"
            button = {"label": "Withdraw", "do": "consent.withdraw", "arg": kind}
        elif row.get("stale"):
            text, tone = "Its words changed — Home asks again", "faint"
        elif row.get("when"):
            text, tone = "Off", "faint"
        else:
            text, tone = "Off — its card opens on first use", "faint"
        if not row["open"]:
            if kind in privacy.SYNC_KINDS:
                button = {"label": "Turn on", "do": "consent.sync", "arg": kind}
            elif row.get("stale"):
                button = {"label": "Turn on", "do": "consent.on", "arg": kind}
        return {"text": text, "tone": tone, "button": button}

    # ---------------------------------------------------------- the cards

    def _block(self, key: str, sections) -> dict | None:
        if key == "voice":
            import hardware as hardware_mod
            if not hardware_mod.no_voice():
                return None
        return getattr(self, f"_card_{key}")(sections)

    def _find(self, sections, path: str):
        return settings_mod.find(sections or [], path)

    def _card_dot(self, sections) -> dict:
        """Where the dot sits (dashboard._dot_block / _paint_dot)."""
        info = (self.status.get("dot") or {}) if self.running else {}
        moved = bool(info.get("dragged"))
        if not self.running:
            where = "Not running"
            said = ("The dot is a window the running app owns, so there is "
                    "nothing to drag while it is stopped. The corner is "
                    "saved either way; start dictation and the button "
                    "moves it anywhere you like.")
        elif info.get("moving"):
            where = "Waiting for you"
            said = ("Drag the disc where you want it and let go. If you "
                    "leave it, it gives up on its own and the dot goes "
                    "back to being a button.")
        elif moved:
            where = f"At {info.get('x')}, {info.get('y')}"
            said = ("Where you dropped it, and the panel opens beside it "
                    "there. Move the dot picks it up again; Back to the "
                    "corner sends it home to the "
                    f"{info.get('corner', 'bottom-right')} of your main "
                    "screen.")
        else:
            where = f"In the {info.get('corner', 'bottom-right')} corner"
            said = ("Pick either corner, or press Move the dot: this "
                    "window steps out of the way and waits for you to "
                    "drag the disc — anywhere, on any screen. Let go and "
                    "it stays there, the panel opens beside it, and it "
                    "is remembered.")
        corner = None
        setting = self._find(sections, "dot.corner")
        if setting is not None:
            corner = self._row(settings_mod.words_for(setting), setting)
        return {"kind": "dot", "where": where, "said": said, "live": self.running,
                "corner_at": str(info.get("corner") or (setting.value if setting else "bottom-right")),
                "moved": moved, "row": corner,
                "move": self.running, "home": self.running and moved}

    def _card_updates(self, sections) -> dict:
        """UPDATES (dashboard._updates_block): the last weekly look, Check
        now, the one way to a newer version, and the weekly switch."""
        import updates
        try:
            line = self._update_line or updates.status_line()
        except Exception:                                    # noqa: BLE001
            line = "Not looked yet"
        setting = self._find(sections, "privacy.update_check")
        try:
            newer = updates.status()["available"] is not None
        except Exception:                                    # noqa: BLE001
            newer = False
        return {"kind": "updates", "line": line,
                "fresh": line.startswith("You have the newest"), "newer": newer,
                "buttons": [] if self._update_busy else self._update_buttons(),
                "row": (self._row(settings_mod.words_for(setting), setting)
                        if setting is not None else None)}

    def _update_buttons(self) -> list[dict]:
        """dashboard._update_buttons: Check now always; with a newer
        version known, the one way to it."""
        import updates
        s = updates.status()
        rows = [{"label": "Check now", "do": "update.check"}]
        rel = s["available"]
        if rel is None or s["mode"] in ("store", "off", "offline"):
            return rows
        if self._too_old_for(rel):
            rows.append({"label": "Release notes", "do": "update.notes"})
            return rows
        if s["winget_command"]:
            rows.append({"label": "Copy the winget command", "do": "update.winget"})
        elif not paths.DEVELOPER:
            rows.append({"label": "Download and install", "do": "update.install"})
        return rows

    @staticmethod
    def _too_old_for(release) -> bool:
        try:
            import migrations
            return migrations.too_old_for(release.min_config_version)
        except Exception:                                    # noqa: BLE001
            return False

    def _card_awake(self, sections) -> dict:
        """The machine held awake, and the screens off on a key
        (dashboard._awake_block / _paint_awake / _paint_awake_rows)."""
        import awake as awake_mod
        awake = (self.status.get("awake") or {}) if self.running else {}
        holding, held, dark = (bool(awake.get("holding")), bool(awake.get("held")),
                               bool(awake.get("dark")))
        tone = ("dark" if dark and held else "ok" if held else
                "bad" if holding else "idle")
        if not self.running:
            state = "Not running"
            meta = "the machine sleeps on its own timer"
            hint = ("The hold lives in the running app — the process that "
                    "keeps the machine awake is the one with the hotkey in "
                    "it — so start dictation first.")
        elif holding and not held:
            state = "Not holding"
            meta = "the app asked and Windows refused"
            hint = ("The app asked Windows to stay awake and the hold is "
                    "not standing. Stop and start the app, and check.")
        elif not holding:
            state = "Not held"
            meta = "[awake] hold = false — it sleeps on its own timer"
            hint = ("Turn hold on in Settings and restart the app, and the "
                    "machine stays awake for as long as it runs.")
        else:
            since = awake.get("hold_since")
            when = time.strftime("%H:%M", time.localtime(since)) if since else "?"
            bits = [f"held since {when}", human_time(awake.get("hold_seconds", 0))]
            if awake.get("pinned"):
                bits.append("sleep timers pinned")
            if dark:
                state = "Screens off"
                bits.append("screens off for " + human_time(awake.get("seconds", 0)))
                keep = awake.get("keep_screens_off_s") or 0
                if keep:
                    hint = ("The machine is awake and the screens are off. "
                            "Anything that lights them is put out again "
                            f"{keep:g} s after the last touch; Screens off "
                            "again does it now. Screens on brings them back.")
                else:
                    hint = ("The machine is awake and the screens are off. "
                            "The mouse lights them — Screens off again puts "
                            "them out. Screens on brings them back.")
            else:
                state = "Awake"
                hint = ("The machine will not sleep while this app runs, "
                        "whatever the screens do. One press: the screens go "
                        "dark and stay dark, nothing is locked, and the "
                        "phone can drive it through Claude.")
            meta = "   ·   ".join(bits)
        rows = []
        if self._awake_probe is not None:
            for label, sentence, word in awake_mod.verdict(awake, self._awake_probe):
                rows.append({"label": label, "text": sentence,
                             "tone": {"good": "ok", "warn": "warn", "bad": "bad"}.get(word, "dim")})
        return {"kind": "awake", "state": state, "meta": meta, "hint": hint, "tone": tone,
                "toggle": "Screens on" if dark else "Screens off",
                "live": self.running, "rows": rows,
                "probed": self._awake_probe is not None, "probing": self._awake_probing,
                "checked": "checking…" if self._awake_probing else self._awake_checked,
                "intro": ("Check status reads what is holding the machine "
                          "awake, the sleep timer, whether Windows may "
                          "power the network card down, Windows Update's "
                          "active hours and whether Claude is running — "
                          "so that a machine that would not have stayed "
                          "reachable is found out now, not from the phone.")}

    def _downloads_coming(self) -> set:
        dl = (self.status or {}).get("downloads") if self.running else None
        if dl and dl.get("state") in ("running", "waiting"):
            return {k for k, v in (dl.get("parts") or {}).items() if v != "done"}
        return set()

    def _card_model(self, sections) -> dict:
        """The speech model and the card that runs it (dashboard._model_block
        / _model_lines)."""
        import hardware as hardware_mod
        import models as models_mod
        import packs as packs_mod
        lines: list[dict] = []
        buttons: list[dict] = []
        try:
            pack = packs_mod.standing("gpu")
        except Exception:                                    # noqa: BLE001
            pack = "unknown"
        if paths.PORTABLE:
            lines.append({"name": "The Hebrew model", "text": "ready — this checkout's own"})
            lines.append({"name": "Faster dictation",
                          "text": "on — the work runs on your NVIDIA card" if pack == "venv"
                          else "off — dictation runs on the processor"})
            return {"kind": "model", "lines": lines, "buttons": buttons}
        try:
            repo = config_mod.load_layered().local.model
        except Exception:                                    # noqa: BLE001
            repo = ""
        try:
            model = models_mod.state(repo)
        except Exception:                                    # noqa: BLE001
            model = "unknown"
        e = models_mod.entry(repo)
        size = f" ({models_mod.human(e.bytes)})" if e else ""
        coming = self._downloads_coming()
        if "model" in coming:
            model = "coming"
        lines.append({"name": "The Hebrew model", "text": {
            "ready": f"ready{size}",
            "absent": f"not downloaded yet{size}",
            "incomplete": "the download did not finish — continue it",
            "stale": "there is a newer one to download",
            "unknown": "this copy asks for a model nobody knows",
            "coming": f"downloading in the background{size}",
        }.get(model, "this copy asks for a model nobody knows")})
        if model == "ready":
            buttons.append({"label": "Delete and re-download the model", "do": "model.redownload"})
            buttons.append({"label": "Delete the model", "do": "model.delete"})
        elif model not in ("coming", "unknown"):
            buttons.append({"label": "Download the model" if model == "absent"
                            else "Continue the download", "do": "model.download"})
        facts = hardware_mod.recorded()
        has_card = int(facts.get("cuda_devices") or 0) >= 1
        gp = packs_mod.pack("gpu")
        psize = f" ({packs_mod.human(gp.bytes)})" if gp else ""
        if "pack" in coming:
            pack_said = f"downloading in the background{psize}"
        elif pack.startswith("failed:"):
            pack_said = f"it will not start on this PC ({pack[7:]}) — dictation runs on the processor"
            buttons.append({"label": "Try it again", "do": "pack.retry", "arg": "gpu"})
            buttons.append({"label": f"Download it again{psize}", "do": "pack.install", "arg": "gpu"})
            buttons.append({"label": "Turn off faster dictation", "do": "pack.remove", "arg": "gpu"})
        elif pack == "ok":
            pack_said = "on — the work runs on your NVIDIA card"
            buttons.append({"label": "Turn off faster dictation", "do": "pack.remove", "arg": "gpu"})
        elif pack == "stale":
            pack_said = "on, and there is a newer download for it"
            buttons.append({"label": f"Update faster dictation{psize}", "do": "pack.install", "arg": "gpu"})
            buttons.append({"label": "Turn off faster dictation", "do": "pack.remove", "arg": "gpu"})
        elif not has_card:
            pack_said = "no NVIDIA card in this PC — dictation runs on the processor"
        elif not facts.get("driver_ok", True):
            pack_said = "your NVIDIA driver is too old for it — update it, then come back"
        else:
            pack_said = f"off — it needs one extra download{psize}"
            buttons.append({"label": f"Turn on faster dictation{psize}", "do": "pack.install", "arg": "gpu"})
        lines.append({"name": "Faster dictation", "text": pack_said})
        return {"kind": "model", "lines": lines, "buttons": buttons}

    def _card_recording(self, sections) -> dict:
        """The Recording pack (dashboard._recording_block)."""
        buttons: list[dict] = []
        small = ""
        if paths.PORTABLE:
            said = "Screen recording and the webcam are ready."
        else:
            import packs as packs_mod
            state = packs_mod.state("recording")
            rp = packs_mod.pack("recording")
            size = f" ({packs_mod.human(rp.bytes)})" if rp else ""
            dl = (self.status or {}).get("downloads") if self.running else None
            if (dl and dl.get("state") in ("running", "waiting")
                    and (dl.get("parts") or {}).get("recording") not in (None, "done")):
                said = ("Screen recording and the webcam are downloading in "
                        f"the background{size}.")
            elif state == "ok":
                said = "Screen recording and the webcam are ready."
                buttons.append({"label": "Remove it", "do": "pack.remove", "arg": "recording"})
            elif state == "stale":
                said = ("Screen recording and the webcam work, and there is "
                        f"a newer download for them{size}.")
                small = ("A free video toolkit (FFmpeg) that the installer "
                         "cannot carry, because of its licence.")
                buttons.append({"label": f"Update{size}", "do": "pack.install", "arg": "recording"})
            else:
                said = ("Screen recording and the webcam need one extra "
                        f"download{size}. Dictation, screenshots and asking "
                        "about the screen all work without it.")
                small = ("It is a free video toolkit (FFmpeg) that the "
                         "installer cannot carry, because of its licence.")
                buttons.append({"label": f"Download{size}", "do": "pack.install", "arg": "recording"})
        return {"kind": "line", "line": said, "small": small, "buttons": buttons,
                "ready": said == "Screen recording and the webcam are ready."}

    def _card_snip(self, sections) -> dict | None:
        """The Snipping-Tool key (dashboard._snip_block)."""
        setting = self._find(sections, "capture.capture_hotkey")
        if setting is None:
            return None
        current = str(self._key_now("capture_hotkey", setting.value)).strip().lower()
        return {"kind": "switch", "on": current == SNIP_KEY, "do": "snip",
                "label": "Take over Win+Shift+S for DeskIT's screenshot key",
                "help": ("Windows' own Snipping Tool stops answering that shortcut "
                         "while DeskIT runs; off, the screenshot key is Ctrl+F11. "
                         "Any other key: the Keys place.")}

    def _key_now(self, field: str, fallback):
        keys = self.status.get("keys") if self.running else None
        if isinstance(keys, dict) and keys.get(field) is not None:
            return keys[field]
        return fallback

    def _card_voice(self, sections) -> dict:
        import hardware as hardware_mod
        return {"kind": "line", "line": hardware_mod.NO_VOICE, "tone": "warn",
                "buttons": [{"label": "Open Speech settings", "do": "speech.open"}]}

    def _card_claude(self, sections) -> dict:
        """Connect Claude Code (dashboard._claude_block / _paint_claude)."""
        import notify_hook
        state, other = "none", None
        try:
            state, other = notify_hook.hook_state(script=str(paths.APP_DIR / "notify_hook.py"))
        except Exception:                                    # noqa: BLE001
            pass
        self._claude_state, self._claude_other = state, other
        if state != "other":
            self._claude_asking = False
        tone, buttons = "faint", []
        if self._claude_asking:
            said = (f"Disconnect the other DeskIT copy ({other}) and connect "
                    "this one? Claude Code's cards stop there and start here.")
            tone = "warn"
            buttons = [{"label": "Keep it", "do": "claude.keep"},
                       {"label": "Yes, connect this one", "do": "claude.take"}]
        elif state == "other":
            said = (f"Claude Code is connected to another DeskIT copy "
                    f"({other}). Turn this on to move it here.")
            tone = "warn"
        elif state == "mine":
            said = ("Connected: two hook lines in ~/.claude/settings.json "
                    "name this copy — when Claude Code finishes or asks, "
                    "DeskIT shows a card and plays a cue. Off removes the lines.")
        else:
            said = ("Two hook lines in ~/.claude/settings.json: when Claude "
                    "Code finishes or asks, DeskIT shows a card and plays a "
                    "cue. Off removes the lines.")
        return {"kind": "switch", "on": state == "mine", "do": "claude.flip",
                "label": "Connect Claude Code", "help": said, "tone": tone,
                "buttons": buttons}

    def _card_sounds(self, sections) -> dict:
        """Every cue, each with Play, and the test card (dashboard._sounds_block)."""
        try:
            import cues as cues_mod
            kinds = list(getattr(cues_mod, "CUES", {}))
        except Exception:                                    # noqa: BLE001
            kinds = []
        return {"kind": "sounds", "test": "Send a test notification",
                "cues": [{"kind": k, "label": SOUND_WORDS.get(k, k)} for k in kinds]}

    def _card_phone(self, sections) -> dict:
        """The endpoint the phone keyboard talks to (dashboard._phone_block).
        The link carries the phone's token, so the page is shown it with
        the token as dots; Copy link copies it from here."""
        url = str((self.status or {}).get("phone") or "")
        # whatever follows the address (#t=, or a query) is the token's
        cut = min((i for i in (url.find("#"), url.find("?")) if i >= 0), default=-1)
        shown = url[:cut] + url[cut:cut + 3] + "•" * 12 if cut >= 0 else url
        return {"kind": "phone", "url": shown,
                "none": "DeskIT is not running, or the switch below is off",
                "said": ("Put the DeskIT keyboard on your phone, give it this "
                         "address once, and the phone dictates into this "
                         "computer over your own private network. It is also "
                         "how a message from another program reaches this "
                         "desk.")}

    def _card_account(self, sections) -> dict:
        """ACCOUNT (dashboard._account_block / _paint_account)."""
        info = (self.status.get("account") or {}) if self.running else None
        buttons: list[dict] = []
        tone, said_sub = "", ""
        if info is None:
            said, tone = "start dictation first — the account lives in the running app", "faint"
        elif not info.get("configured"):
            said, tone = "no account server in this build", "faint"
        elif info.get("busy") == "waiting for the browser":
            said = "waiting for Google's sign-in page in your browser…"
            said_sub = "come back here when it says you are signed in"
        elif info.get("signed_in"):
            if info.get("email") and info.get("name"):
                said = f"Signed in with Google as {info['name']} ({info['email']})"
            elif info.get("email"):
                said = f"Signed in with Google as {info['email']}"
            else:
                ident = str(info.get("user_id") or "")
                said = (f"Anonymous account · id {ident[:8]}…{ident[-4:]}" if ident
                        else "Anonymous account")
            bits = [f"this PC: {info.get('device_name') or '?'}",
                    str(info.get("region") or "Frankfurt (Supabase)")]
            if info.get("last_sync"):
                bits.append(f"last sync {str(info['last_sync'])[11:16]} UTC")
            if info.get("live"):
                bits.append("live")
            if info.get("waiting"):
                n = int(info["waiting"])
                bits.append(f"{n} report{'s' if n != 1 else ''} waiting to send")
            said_sub = " · ".join(bits)
            if info.get("last_error"):
                said_sub = f"{info['last_error']}  ·  {said_sub}"
            if self._account_asking == "everywhere":
                said = ("Sign out of every PC? Each one, this one too, stops dictating "
                        "until you sign in on it again.")
                tone = "warn"
                buttons = [{"label": "Stay signed in", "do": "account.keep"},
                           {"label": "Sign out of every PC", "do": "account.do", "arg": "signout_all"}]
            elif self._account_asking:
                said = ("Delete your account on the server? Your reports, synced words, "
                        "settings and history go with it. Your data on this PC stays.")
                tone = "warn"
                buttons = [{"label": "Keep it", "do": "account.keep"},
                           {"label": "Delete", "do": "account.do", "arg": "delete"}]
            else:
                if info.get("anonymous"):
                    buttons.append({"label": "Sign in with Google", "do": "account.do", "arg": "google"})
                buttons += [{"label": "Sign out", "do": "account.do", "arg": "signout"},
                            {"label": "Sign out of every PC", "do": "account.ask", "arg": "everywhere"},
                            {"label": "Delete my account", "do": "account.ask", "arg": "delete"}]
        else:
            said = ("none — sign in to keep your learned words, settings and history "
                    "on every PC you use")
            said_sub = (info.get("last_error") or
                        "Google through Supabase's own sign-in page; nothing about you "
                        "is stored until you press it. Each sync then asks its own card.")
            buttons = [{"label": "Sign in with Google", "do": "account.do", "arg": "google"},
                       {"label": "Anonymous account", "do": "account.do", "arg": "anonymous"}]
        if self._account_asking and not (info or {}).get("signed_in"):
            self._account_asking = ""
        return {"kind": "lines", "line": said, "tone": tone, "sub": str(said_sub),
                "buttons": buttons, "signed_in": bool((info or {}).get("signed_in"))}

    def _lock_info(self) -> dict:
        if not self.running:
            return {}
        return dict(((self.status.get("account") or {}).get("lock") or {}))

    def _card_lock(self, sections) -> dict:
        """THE LOCK (dashboard._lock_block / _paint_lock)."""
        info = (self.status.get("account") or {}) if self.running else None
        lock = (info or {}).get("lock") or {}
        buttons: list[dict] = []
        tone, said_code, said_sub, typing = "", "", "", False
        if info is None or not info.get("configured"):
            said, tone = "start dictation first — the lock lives in the running app", "faint"
        elif not info.get("signed_in"):
            said, tone = "sign in first — the lock is your account's", "faint"
        elif self._lock_mode == "shown":
            said = "Your recovery key. Keep it somewhere safe — it is shown once."
            said_code = self._lock_fresh
            said_sub = ("With it, a PC with no other PC of yours at hand can open your "
                        "account. Making a new one replaces it.")
            tone = "warn"
            buttons = [{"label": "Copy", "do": "lock.copy"}, {"label": "Done", "do": "lock.done"}]
        elif lock.get("state") == "changed":
            ch = lock.get("changed") or {}
            tone = "bad"
            if not ch.get("refused"):
                said = "The lock of your account changed — not on this PC. Was it you?"
                said_sub = ("This PC keeps its key; what you said and your cloud keys stop "
                            "syncing until you answer. It was you: this PC asks to join the new "
                            "lock. It wasn't: nothing here changes.")
                buttons = [{"label": "It wasn't me", "do": "lock.do", "arg": ["lock_answer", "no"]},
                           {"label": "It was me", "do": "lock.do", "arg": ["lock_answer", "yes"]}]
            else:
                said = "Not you — this PC kept its key; what you said and your keys stay paused."
                said_sub = ("Sign out of every PC, above: it ends every session of your account, "
                            "anyone else's too. Sign in again, then put your lock back.")
                buttons = ([{"label": "Put my lock back", "do": "lock.do", "arg": ["lock_restore", ""]}]
                           if ch.get("mine") else [])
            if ch.get("server"):
                said_sub += f"  ·  on the server: lock {ch['server']}, here: lock {ch.get('mine') or '—'}"
        elif lock.get("pending") and lock["pending"][0].get("twins"):
            ask = lock["pending"][0]
            said = (f"Two requests say they are {ask.get('name') or 'another PC'} — "
                    "neither can be approved.")
            said_sub = (f"One of them is not your PC. On {ask.get('name') or 'that PC'}, sign out "
                        "and sign in again to ask afresh.")
            tone = "bad"
            buttons = [{"label": "Not now", "do": "lock.do", "arg": ["decline", str(ask.get("id") or "")]}]
        elif lock.get("pending"):
            ask = lock["pending"][0]
            said = f"{ask.get('name') or 'Another PC'} signed in to your account and asks to join."
            said_code = str(ask.get("code") or "")
            said_sub = ("Its screen shows a code — approve only if it is exactly this one. "
                        "It then gets your account's key: your cloud keys and what you "
                        "said open there too.")
            buttons = [{"label": "Approve", "do": "lock.do", "arg": ["approve", str(ask.get("id") or "")]},
                       {"label": "Not now", "do": "lock.do", "arg": ["decline", str(ask.get("id") or "")]}]
        elif lock.get("state") == "waiting":
            said = "Waiting for your other PC to approve this one."
            said_code = str(lock.get("code") or "")
            typing = self._lock_mode == "typing"
            if typing:
                said_sub = "Your recovery key — 24 letters and digits in six groups:"
                buttons = [{"label": "Open", "do": "lock.recover"}, {"label": "Cancel", "do": "lock.done"}]
            else:
                said_sub = ("Open the desk on your other PC: Home there shows this code — press "
                            "Approve. Until then this PC has your words and settings; "
                            "what you said and your cloud keys stay locked.")
                buttons = [{"label": "Type the recovery key", "do": "lock.type"}]
            if lock.get("error"):
                said_sub = f"{lock['error']}  ·  {said_sub}"
        elif lock.get("state") == "have":
            said = "This PC holds your account's key."
            bits = ["what you said and your cloud keys leave this PC locked",
                    "the server cannot read them"]
            if lock.get("id"):
                bits.append(f"lock {lock['id']}")
            if lock.get("recovery"):
                bits.append("recovery key: made")
            elif lock.get("recovery") is False:
                bits.append("no recovery key yet")
            said_sub = " · ".join(bits)
            buttons = [{"label": ("Replace the recovery key" if lock.get("recovery")
                                  else "Make a recovery key"), "do": "lock.new"}]
        else:
            said = "Looking at the lock…"
            said_sub = lock.get("error") or "the next sync says where this PC stands"
            tone = "faint"
        if self._lock_mode == "typing" and not typing:
            self._lock_mode = ""
        return {"kind": "lines", "line": said, "tone": tone, "code": said_code,
                "sub": str(said_sub), "buttons": buttons, "typing": typing,
                "placeholder": "Your recovery key"}

    def _card_keys(self, sections) -> dict:
        if not self._warm.is_set():
            return {"kind": "keys", "rows": [], "loading": True}
        return {"kind": "keys", "rows": self._keyrows().read()}

    def _card_connections(self, sections) -> dict:
        """EVERY CONNECTION (dashboard._connections_block)."""
        today = self._network().today()
        return {"kind": "lines",
                "line": (f"{today} request{'s' if today != 1 else ''} today, every one "
                         "of them with its host, purpose and consent on the Network "
                         "screen — during plain dictation the table stays empty."),
                "buttons": [{"label": "Open the Network screen", "go": "network"},
                            {"label": "Open the log file", "do": "net.log"}]}

    def _card_said_file(self, sections) -> dict:
        return {"kind": "line",
                "line": ("Every dictation, translation and lookup, on "
                         "this PC only, in a file you can open and "
                         "delete yourself."),
                "buttons": [{"label": "Open the file", "do": "said.open"}]}

    def _card_version(self, sections) -> dict:
        """Which code is running, what this PC is, Quit and the tour
        (dashboard._version_block)."""
        import hardware as hardware_mod
        import version
        branch = version.BRANCH
        return {"kind": "version", "name": "DeskIT",
                "line": f"version {version.VERSION}" + (
                    f" - branch '{branch}' - running now" if branch else ""),
                "machine": hardware_mod.machine_line(),
                "quit": "Quit DeskIT",
                "quit_line": "the whole app, keys included — the bar's Stop only unloads the model",
                "tour": "Show the tour"}

    @staticmethod
    def built_with_llama() -> bool:
        try:
            return any("llama" in str(v).lower()
                       for v in config_mod.defaults_flat().values())
        except Exception:                                    # noqa: BLE001
            return False

    def _card_about(self, sections) -> dict:
        """About (dashboard._about_card): the licence line, the model it
        transcribes with, and a button for every paper."""
        import version
        return {"kind": "about",
                "line": (f"DeskIT {version.VERSION} · Apache License 2.0 · "
                         "Copyright 2026 Yoav Shimron"),
                "model": ("Transcribes Hebrew with ivrit.ai's whisper-large-v3-turbo "
                          "(Apache-2.0)" + (" · Built with Llama" if self.built_with_llama() else "")),
                "papers": list(PAPERS)}

    def _card_files(self, sections) -> dict:
        return {"kind": "files", "rows": [
            {"glyph": "file", "name": "The app's diary",
             "hint": "app.log — what it did and why, for when something looks off",
             "file": "app_log"},
            {"glyph": "settings", "name": "Your settings",
             "hint": ("settings.toml — only what you changed; the help for every "
                      "knob is in defaults.toml beside the app"),
             "file": "settings"},
            {"glyph": "folder", "name": "The app's folder", "hint": str(paths.DATA_DIR),
             "file": "folder"},
        ]}

    def _network(self):
        if self._net is None:
            import desk_settings_net
            self._net = desk_settings_net.Network()
        return self._net

    def _keyrows(self):
        if self._keys is None:
            import desk_settings_keys
            self._keys = desk_settings_keys.Keys(nudge=self._nudge_vault, say=self._say)
        return self._keys

    def _nudge_vault(self) -> None:
        """A key just stored goes on to the account's other PCs, sealed
        (dashboard._key_state)."""
        if self.running:
            self._send("account", timeout_ms=4000, do="nudge", kind="vault")

    # ================================================================ act

    def act(self, do: str, arg=None) -> dict:
        do = str(do)
        if do not in ACTS:
            return {"ok": False, "error": f"{do[:40]!r} is not a Settings action"}
        chosen = None
        if do == "browse":
            # Windows' dialog waits for the person, for as long as he
            # likes: it is opened OUTSIDE the lock, or every poll of the
            # page would wait behind it
            try:
                chosen = self._browse_for(arg)
            except Refused as e:
                return {"ok": False, "error": str(e)}
            except Exception as e:                           # noqa: BLE001
                log.warning("web desk: settings browse failed: %s", type(e).__name__)
                chosen = ""
        with self._lock:
            if not self.status:
                self._poll()
            try:
                if do == "browse":
                    note = self._browsed(arg, chosen or "")
                else:
                    note = getattr(self, "_do_" + do.replace(".", "_"))(arg)
            except Refused as e:
                return {"ok": False, "error": str(e)}
            except Exception as e:                           # noqa: BLE001 — words, not a traceback
                log.warning("web desk: settings %s failed: %s", do, type(e).__name__)
                note = f"that did not work ({type(e).__name__})"
            place = self.read()
            return {"ok": True, "note": note or "", "place": place}

    # -- the helpers every button shares

    def _ask(self, command: str, **args):
        return self._send(command, timeout_ms=4000, **args)

    @staticmethod
    def _announce(reply, fallback: str) -> str:
        if reply is None:
            return "dictation is not running"
        if not reply.get("ok"):
            return str(reply.get("error") or "that did not work")
        return str(reply.get("message") or fallback)

    @staticmethod
    def _copy(text: str) -> None:
        import injector
        injector.set_text(text)

    @staticmethod
    def _open(path) -> bool:
        import launch
        return launch.open_path(Path(path))

    @staticmethod
    def _open_url(url: str) -> None:
        import webbrowser
        if url.startswith(URL_PREFIXES):
            webbrowser.open(url)

    # -- a line of the file

    def _setting(self, path):
        """The setting a row draws, or Refused: a path the page names must
        be a line settings.TABS draws, and never a consent gate."""
        if not isinstance(path, str) or path not in settings_mod.WORDS:
            raise Refused("that is not a setting this page draws")
        if path in config_mod.CONSENT_KEYS:
            raise Refused("a privacy gate is not a setting — it opens only through its card")
        setting = settings_mod.find(self._sections(), path)
        if setting is None:
            raise Refused("that is not a setting this page draws")
        return setting

    def _checked_value(self, setting, value):
        """The value the page sent, as the kind the file holds — or
        Refused. A menu takes only its own values; a folder never comes
        from the page; a field takes a short line of plain text."""
        if setting.path in FOLDER_SETTINGS:
            raise Refused("a folder is picked with Browse…")
        if setting.consent or (setting.kind != "bool" and not setting.editable):
            raise Refused("that line is edited in the file")
        if setting.kind == "bool":
            if not isinstance(value, bool):
                raise Refused("a switch is on or off")
            return value
        row = settings_mod.WORDS.get(setting.path)
        options = self._menu_for(row, setting)
        if options:
            allowed = [v for v, _n in options]
            if value not in allowed or not isinstance(value, str):
                raise Refused("that is not one of the menu's choices")
            return value
        if isinstance(value, bool) or not isinstance(value, (str, int, float)):
            raise Refused("that is not a value this line takes")
        raw = str(value).strip()
        label = settings_mod.label_for(setting.path)
        if len(raw) > MAX_TEXT or any(ord(c) < 32 for c in raw):
            raise Refused(f'"{label}": that is too long a line')
        try:
            if setting.kind == "int":
                return int(raw)
            if setting.kind == "float":
                return float(raw)
        except ValueError:
            raise Refused(f'"{label}": {raw!r} is not '
                          f"a{'n' if setting.kind == 'int' else ''} {setting.kind}") from None
        if settings_mod.is_rtl(raw):
            raise Refused(f'"{label}": a Hebrew line is edited in the file')
        return raw

    def _apply(self, setting, value) -> str:
        """dashboard._apply_setting: through the running app when there is
        one, straight into the file otherwise."""
        if self.running:
            reply = self._ask("option", name=setting.path, value=value)
            if reply is not None:
                if not reply.get("ok"):
                    return str(reply.get("error") or "that did not work")
                self._sections_kept = None
                return str(reply.get("message")
                           or settings_mod.saved_sentence(setting.path, value))
        return self._write(setting, value)

    def _write(self, setting, value) -> str:
        """dashboard._write_setting."""
        try:
            config_mod.save({setting.path: value})
        except Exception as e:                               # noqa: BLE001
            return (f"could not save that ({type(e).__name__})"
                    if not isinstance(e, config_mod.ConfigError) else str(e))
        if setting.path == "setup.autostart":
            import autostart
            autostart.apply(bool(value))
        self._sections_kept = None
        return settings_mod.saved_sentence(setting.path, value, live=False)

    def _do_set(self, arg) -> str:
        if not isinstance(arg, dict):
            raise Refused("set takes a path and a value")
        setting = self._setting(arg.get("path"))
        value = self._checked_value(setting, arg.get("value"))
        current = setting.value
        if value == current and type(value) is type(current):
            return ""
        return self._apply(setting, value)

    def _browse_for(self, arg) -> str:
        """[Browse…]: Windows' own folder dialog, opened where the setting
        points now (dashboard._browse_folder). The page names only WHICH
        of the two folders; the path is the dialog's, never the page's."""
        if arg not in FOLDER_SETTINGS:
            raise Refused("that is not a folder setting")
        with self._lock:
            setting = self._setting(arg)
        try:
            start = paths.resolve_folder(str(setting.value or "captures"))
        except Exception:                                    # noqa: BLE001
            start = paths.DATA_DIR
        return self._pick_folder(settings_mod.label_for(setting.path), Path(start))

    def _browsed(self, arg, chosen: str) -> str:
        """The dialog's answer goes to the file the road a typed path took
        in the Tk desk (dashboard._entry_done)."""
        if not chosen:
            return ""
        setting = self._setting(arg)
        chosen = str(Path(chosen))
        if chosen == _shown_for(setting.path, setting.value):
            return ""
        return self._apply(setting, chosen)

    def _do_browse(self, arg) -> str:
        """Never reached: act() opens the dialog itself, outside the lock."""
        raise Refused("that is not a folder setting")

    def _pick_folder(self, title: str, start: Path) -> str:
        """The folder dialog of the window this page is in (pywebview's,
        WinForms' own), on the call's thread — it waits for the person."""
        window = _window()
        if window is None:
            return ""
        import webview
        folder = str(start) if start.is_dir() else ""
        kind = getattr(getattr(webview, "FileDialog", None), "FOLDER", None)
        if kind is None:
            kind = getattr(webview, "FOLDER_DIALOG")
        chosen = window.create_file_dialog(kind, directory=folder)
        if not chosen:
            return ""
        first = chosen[0] if isinstance(chosen, (list, tuple)) else chosen
        return str(first or "")

    def _do_file_open(self, arg) -> str:
        """One of the app's own files, by the name the page knows it by:
        the Files card on About, and "In the file" beside a line that is a
        list or Hebrew (dashboard._control), which opens settings.toml."""
        which = "settings" if arg is None else arg
        if which not in FILES:
            raise Refused("that is not one of the app's files")
        targets = {"app_log": paths.APP_LOG, "settings": paths.SETTINGS_FILE,
                   "folder": paths.DATA_DIR, "transcripts": paths.TRANSCRIPTS_LOG,
                   "network_log": paths.NETWORK_LOG}
        target = Path(targets[which])
        return "" if self._open(target) else f"could not open {target.name}"

    # -- the dot

    def _do_dot_move(self, arg) -> str:
        """Move the dot (dashboard._move_dot / _dot_moving): the app's
        framed move, and this window out of the way until it is over."""
        if not self.running:
            return "start dictation first — the dot belongs to the running app"
        reply = self._ask("dot", do="move")
        if reply is None or not reply.get("ok"):
            return self._announce(reply, "the dot would not move")
        window = _window()
        if window is not None:
            self._dot_waiting = time.monotonic() + DOT_WAIT_S
            try:
                window.hide()
            except Exception:                                # noqa: BLE001
                self._dot_waiting = 0.0
                return self._announce(reply, "")
            threading.Thread(target=self._dot_wait, args=(window,), daemon=True,
                             name="dot-wait").start()
        return self._announce(reply, "")

    def _dot_wait(self, window) -> None:
        """dashboard._dot_returns: this window back when the drag is
        over, or when the wait has gone on longer than anyone meant."""
        info: dict = {}
        while time.monotonic() < self._dot_waiting:
            time.sleep(0.4)
            reply = self._send("status", timeout_ms=1200)
            if not isinstance(reply, dict) or reply.get("stage") != "running":
                info = {}
                break
            info = reply.get("dot") or {}
            if not info.get("moving"):
                break
        self._dot_waiting = 0.0
        try:
            window.show()
        except Exception:                                    # noqa: BLE001
            log.info("web desk: the window would not come back after the dot")
        self._say(f"the dot is at {info.get('x')}, {info.get('y')} now, and it stays there"
                  if info.get("dragged") else "the dot did not move")

    def _do_dot_corner(self, arg) -> str:
        return self._announce(self._ask("dot", do="corner"), "the dot is back in its corner")

    # -- updates

    def _do_update_check(self, arg) -> str:
        """Check now (dashboard._update_check), on a worker: a request
        through net.py must not hold the page's call."""
        if self._update_busy:
            return ""
        import updates
        self._update_busy = True
        self._update_line = "checking GitHub for a newer version…"

        def work() -> None:
            try:
                updates.check(force=True)
                line = updates.status_line()
            except Exception as e:                           # noqa: BLE001
                line = f"the check failed ({type(e).__name__})"
            with self._lock:
                self._update_busy = False
                self._update_line = ""
            self._say(line)

        threading.Thread(target=work, daemon=True, name="update-check").start()
        return self._update_line

    def _do_update_install(self, arg) -> str:
        """Download, verify, start the installer, and ask the app to
        leave (dashboard._update_install)."""
        import singleton
        import updates
        rel = updates.status()["available"]
        if rel is None or paths.DEVELOPER or self._update_busy or self._too_old_for(rel):
            return ""
        self._update_busy = True
        self._update_line = f"downloading DeskIT {rel.version}…"

        def progress(done: int, total: int) -> None:
            pct = int(done * 100 / total) if total else 0
            self._update_line = f"downloading DeskIT {rel.version}… {pct}%"

        def work() -> None:
            try:
                path = updates.download(rel, on_progress=progress)
                self._update_line = "Installing… DeskIT will close and reopen"
                updates.install(path, rel, quit_app=singleton.request_quit)
            except Exception as e:                           # noqa: BLE001
                with self._lock:
                    self._update_busy = False
                    self._update_line = ""
                self._say(f"the update did not finish ({type(e).__name__})")

        threading.Thread(target=work, daemon=True, name="update-install").start()
        return self._update_line

    def _do_update_winget(self, arg) -> str:
        import updates
        command = updates.status().get("winget_command") or ""
        if not command:
            return ""
        self._copy(command)
        return f"copied: {command}"

    def _do_update_notes(self, arg) -> str:
        import updates
        rel = updates.status()["available"]
        if rel is not None:
            self._open_url(str(rel.notes_url))
        return ""

    # -- awake

    def _do_awake_screens(self, arg) -> str:
        """Screens off / on / again, through the running app
        (dashboard._screens / _screens_answered)."""
        if arg not in ("toggle", "again"):
            raise Refused("screens toggle or again")
        reply = self._ask("screens", do=arg)
        if arg == "again":
            return self._announce(reply, "screens off again")
        state = (reply or {}).get("awake") or {}
        return self._announce(reply, "screens off — they stay off until you tap again"
                              if state.get("dark") else "screens on")

    def _do_awake_check(self, arg) -> str:
        """The probe, on a worker (dashboard._awake_check): two or three
        seconds of powercfg and PowerShell that must not stall the page."""
        if self._awake_probing:
            return ""
        import awake as awake_mod
        self._awake_probing = True

        def work() -> None:
            try:
                result = awake_mod.probe()
            except Exception as e:                           # noqa: BLE001
                result = {"error": type(e).__name__}
            with self._lock:
                self._awake_probing = False
                self._awake_probe = result
                self._awake_checked = f"checked {time.strftime('%H:%M:%S')}"

        threading.Thread(target=work, daemon=True, name="awake-probe").start()
        return ""

    # -- the model and the packs

    def _step(self, flag: str, name: str | None = None) -> str:
        import launch
        return ("the download window is opening…" if launch.run_step(flag, name)
                else "could not start the download window")

    def _repo(self) -> str:
        return config_mod.load_layered().local.model

    def _do_model_download(self, arg) -> str:
        return "" if paths.PORTABLE else self._step("--download-model")

    def _do_model_redownload(self, arg) -> str:
        if paths.PORTABLE:
            return ""
        import models as models_mod
        models_mod.remove(self._repo())
        return self._step("--download-model")

    def _do_model_delete(self, arg) -> str:
        if paths.PORTABLE:
            return ""
        import models as models_mod
        gone = models_mod.remove(self._repo())
        return ("the model was deleted — dictation waits until it is downloaded again"
                if gone else "there was no model folder to delete")

    def _do_pack_install(self, arg) -> str:
        if arg not in ("gpu", "recording") or paths.PORTABLE:
            raise Refused("that is not a download")
        return self._step("--install-pack", arg)

    def _do_pack_remove(self, arg) -> str:
        if arg not in ("gpu", "recording") or paths.PORTABLE:
            raise Refused("that is not a download")
        import packs as packs_mod
        packs_mod.remove(arg)
        # turned down by hand: the background downloads never fetch it again
        packs_mod.decline(arg)
        return ("faster dictation is off — Settings > Dictation offers it again"
                if arg == "gpu" else f"the {arg} pack was removed")

    def _do_pack_retry(self, arg) -> str:
        if arg != "gpu":
            raise Refused("that is not a download")
        import packs as packs_mod
        packs_mod.clear_failure("gpu")
        return "GPU speed will be tried again at the next start"

    # -- the Snipping-Tool key

    def _do_snip(self, arg) -> str:
        """dashboard._snip_flip -> _apply_key("capture_hotkey"): validated
        against the other keys, live through `rebind` when it runs."""
        if not isinstance(arg, bool):
            raise Refused("a switch is on or off")
        key = SNIP_KEY if arg else PLAIN_SNIP_KEY
        field = "capture_hotkey"
        if self.running:
            reply = self._ask("rebind", field=field, key=key)
            if reply is not None:
                return self._announce(reply, config_mod.rebound_sentence(field, key))
        try:
            current = config_mod.load_layered()
            config_mod.check_hotkeys(config_mod.with_field(current, field, key))
            config_mod.save({"capture.capture_hotkey": key})
        except Exception as e:                               # noqa: BLE001
            return str(e) if isinstance(e, config_mod.ConfigError) \
                else f"could not save that ({type(e).__name__})"
        self._sections_kept = None
        return config_mod.rebound_sentence(field, key)

    def _do_speech_open(self, arg) -> str:
        try:
            os.startfile("ms-settings:speech")                # noqa: S606
        except OSError as e:
            return f"could not open the Speech settings ({type(e).__name__})"
        return ""

    # -- Claude Code

    def _claude_connect(self) -> None:
        import launch
        import notify_hook
        notify_hook.install_hook(notify_hook.DEFAULT_SETTINGS, python=launch.pythonw(),
                                 script=str(paths.APP_DIR / "notify_hook.py"))
        config_mod.save({"notify.enabled": True})

    def _do_claude_flip(self, arg) -> str:
        """dashboard._claude_flip: on writes this copy's lines, off removes
        them — unless another copy holds the door, when on only ASKS."""
        if not isinstance(arg, bool):
            raise Refused("a switch is on or off")
        import notify_hook
        self._card_claude(None)                    # the file as it stands now
        if self._claude_state == "other":
            self._claude_asking = arg
            return ""
        try:
            if arg:
                self._claude_connect()
                return "Claude Code connected — the hook lines are in ~/.claude/settings.json"
            notify_hook.uninstall_hook(notify_hook.DEFAULT_SETTINGS)
            return "Claude Code disconnected — the hook lines are gone"
        except Exception as e:                               # noqa: BLE001
            return f"could not write the hook ({type(e).__name__})"

    def _do_claude_keep(self, arg) -> str:
        self._claude_asking = False
        return ""

    def _do_claude_take(self, arg) -> str:
        self._claude_asking = False
        other = self._claude_other
        try:
            self._claude_connect()
        except Exception as e:                               # noqa: BLE001
            return f"could not write the hook ({type(e).__name__})"
        return f"Claude Code connected — the other copy ({other}) is disconnected"

    # -- sounds, the test card, the phone

    def _do_cue_play(self, arg) -> str:
        """One sound, from THIS process (dashboard._play_cue)."""
        import cues as cues_mod
        if not isinstance(arg, str) or arg not in getattr(cues_mod, "CUES", {}):
            raise Refused("that is not a sound this app makes")
        try:
            cues_mod.play(arg)
        except Exception as e:                               # noqa: BLE001
            return f"could not play that ({type(e).__name__})"
        return ""

    def _do_notify_test(self, arg) -> str:
        return self._announce(self._ask("notify", do="test"), "test notification sent")

    def _do_phone_copy(self, arg) -> str:
        url = str((self.status or {}).get("phone") or "")
        if not url:
            return "no phone link — [server] enabled = false, or it is not running"
        self._copy(url)
        del url
        return "phone link copied to the clipboard"

    # -- the account

    def _do_account_do(self, arg) -> str:
        """Every account press is a command to the RUNNING app
        (dashboard._account_do). Delete and Sign out of every PC are only
        sent from the card's own question."""
        if arg not in ACCOUNT_DOS:
            raise Refused("that is not an account action")
        if arg in ("delete", "signout_all") and self._account_asking != (
                "delete" if arg == "delete" else "everywhere"):
            raise Refused("the card asks first")
        self._account_asking = ""
        if not self.running:
            return "start dictation first — the account lives in the running app"
        return self._announce(self._ask("account", do=arg), ACCOUNT_DOS[arg])

    def _do_account_ask(self, arg) -> str:
        if arg not in ("delete", "everywhere"):
            raise Refused("that is not a question this card asks")
        self._account_asking = arg
        return ""

    def _do_account_keep(self, arg) -> str:
        self._account_asking = ""
        return ""

    # -- the lock

    def _do_lock_do(self, arg) -> str:
        """Approve / Not now / It was me / It wasn't me / Put my lock back
        (dashboard._lock_do). The request id is the one the app's own
        status named; the page cannot invent one."""
        if not (isinstance(arg, list) and len(arg) == 2 and arg[0] in LOCK_DOS):
            raise Refused("that is not a lock action")
        do, kind = arg[0], str(arg[1] or "")
        if not self.running:
            return "start dictation first — the lock lives in the running app"
        lock = self._lock_info()
        if do in ("approve", "decline"):
            ids = {str(a.get("id")) for a in (lock.get("pending") or [])}
            if kind not in ids:
                return "that request is not waiting any more"
            said = LOCK_DOS[do]
        elif do == "lock_answer":
            if kind not in ("yes", "no"):
                raise Refused("yes or no?")
            said = "asked" if kind == "yes" else "kept"
        else:
            kind, said = "", LOCK_DOS[do]
        args = {"do": do}
        if kind:
            args["kind"] = kind
        return self._announce(self._ask("account", **args), said)

    def _do_lock_type(self, arg) -> str:
        self._lock_mode = "typing"
        return ""

    def _do_lock_recover(self, arg) -> str:
        """[Open] beside the typed recovery key (dashboard._lock_recover):
        the value goes to the app over the pipe and nowhere else."""
        typed = arg.pop("key", "") if isinstance(arg, dict) else ""
        typed = typed.strip() if isinstance(typed, str) else ""
        if not typed:
            return "type the recovery key first"
        if len(typed) > 80:
            del typed
            return "that is not a recovery key"
        self._lock_mode = ""
        if not self.running:
            del typed
            return "start dictation first — the lock lives in the running app"
        reply = self._ask("account", do="recover", kind=typed)
        del typed
        return self._announce(reply, "opened")

    def _do_lock_new(self, arg) -> str:
        """[Make / Replace the recovery key]: the app makes it and answers
        with it once; the card shows it until Done (dashboard._lock_new_recovery)."""
        if not self.running:
            return "start dictation first — the lock lives in the running app"
        reply = self._ask("account", do="recovery_new")
        if not reply or not reply.get("ok") or not reply.get("recovery"):
            return self._announce(reply, "that did not work")
        self._lock_fresh = str(reply["recovery"])
        self._lock_mode = "shown"
        return "your recovery key is on the card — copy it somewhere safe"

    def _do_lock_copy(self, arg) -> str:
        if not self._lock_fresh:
            return ""
        try:
            self._copy(self._lock_fresh)
        except Exception:                                    # noqa: BLE001
            return "could not reach the clipboard — write it down"
        return "copied — paste it somewhere safe, then press Done"

    def _do_lock_done(self, arg) -> str:
        self._lock_fresh = ""
        self._lock_mode = ""
        return ""

    # -- the consents

    def _kind(self, arg) -> str:
        import privacy
        if not isinstance(arg, str) or arg not in privacy.KINDS:
            raise Refused("that is not a consent")
        return arg

    def _do_consent_withdraw(self, arg) -> str:
        """Withdraw (dashboard._withdraw): privacy.withdraw writes the
        consent file and mirrors the key; the running app notices."""
        import privacy
        kind = self._kind(arg)
        try:
            privacy.withdraw(kind)
        except Exception as e:                               # noqa: BLE001
            return f"could not withdraw that ({type(e).__name__})"
        self._sections_kept = None
        return (f"{kind}: withdrawn — the local path answers from the "
                f"next press; the card will ask again when a feature "
                f"needs the cloud")

    def _do_consent_on(self, arg) -> str:
        """[Turn on] on a row whose words changed (dashboard._turn_on): the
        yes Home's row gives — only for a kind privacy.stale() names."""
        import privacy
        kind = self._kind(arg)
        try:
            privacy.configure(config_mod.load_layered())
            waiting = privacy.stale()
        except Exception as e:                               # noqa: BLE001
            log.warning("could not read the consents: %s", type(e).__name__)
            return "could not record that"
        if kind not in waiting:
            return "that consent is not waiting for an answer"
        try:
            privacy.grant(kind)
        except Exception as e:                               # noqa: BLE001
            log.warning("could not record the consent for %s: %s", kind, type(e).__name__)
            return "could not record that"
        self._sections_kept = None
        return f"{kind}: on — from the next press"

    def _do_consent_sync(self, arg) -> str:
        """[Turn on] beside a shut sync: the running app asks with the
        sync's own card (dashboard._account_do("sync"))."""
        import privacy
        kind = self._kind(arg)
        if kind not in privacy.SYNC_KINDS:
            raise Refused("that is not a sync")
        if not self.running:
            return "start dictation first — the account lives in the running app"
        return self._announce(self._ask("account", do="sync", kind=kind), "asking")

    # -- the cloud keys

    @staticmethod
    def _provider(arg) -> str:
        import desk_settings_keys
        name = arg.get("name") if isinstance(arg, dict) else arg
        if not isinstance(name, str) or name not in desk_settings_keys.NAMES:
            raise Refused("that is not a cloud key")
        return name

    def _do_key_save(self, arg) -> str:
        if not isinstance(arg, dict):
            raise Refused("a key is saved with its provider's name")
        name = self._provider(arg)
        return self._keyrows().save(name, arg)

    def _do_key_change(self, arg) -> str:
        return self._keyrows().change(self._provider(arg))

    def _do_key_cancel(self, arg) -> str:
        return self._keyrows().cancel(self._provider(arg))

    def _do_key_remove(self, arg) -> str:
        return self._keyrows().remove(self._provider(arg))

    # -- files, papers, the end of the road

    def _do_net_log(self, arg) -> str:
        if not paths.NETWORK_LOG.exists():
            return "no network.log yet — nothing has gone out"
        return "" if self._open(paths.NETWORK_LOG) else "could not open network.log"

    def _do_said_open(self, arg) -> str:
        return "" if self._open(paths.TRANSCRIPTS_LOG) else "could not open the file"

    def _do_url(self, arg) -> str:
        """The links on the page: a provider's free key, the model card."""
        import desk_settings_keys
        urls = {name: url for name, _l, url, _w in desk_settings_keys.PROVIDERS}
        urls["model"] = MODEL_CARD_URL
        if arg not in urls:
            raise Refused("that is not a link this page has")
        self._open_url(urls[arg])
        return ""

    def _do_paper(self, arg) -> str:
        """A paper on About (dashboard._about_rows)."""
        if arg not in PAPERS:
            raise Refused("that is not a paper")
        app = paths.APP_DIR
        files = {"Licence": ("LICENSE", "LICENSE is not beside the app"),
                 "Trademark": ("TRADEMARK.md", "TRADEMARK.md is not beside the app"),
                 "Third-party notices": ("THIRD-PARTY-NOTICES.txt",
                                         "the notices file is written by the build; "
                                         "a checkout has dev/notices-extra.txt"),
                 "Network": ("NETWORK.md", "NETWORK.md is not beside the app"),
                 "Report a security issue": ("SECURITY.md", "SECURITY.md is not beside the app")}
        if arg in files:
            name, missing = files[arg]
            path = app / name
            return "" if path.exists() and self._open(path) else missing
        if arg in ("Privacy policy", "Terms"):
            page = "privacy" if arg == "Privacy policy" else "terms"
            local = app / "docs" / f"{page}.md"
            if local.exists():
                self._open(local)
            else:
                self._open_url(f"{PAGES_URL}/{page}")
            return ""
        if arg == "Report on GitHub":
            self._open_url(ISSUES_URL)
            return ""
        return self._do_diagnostics_copy(None)

    def _do_diagnostics_copy(self, arg) -> str:
        import problems as problems_mod
        try:
            block = problems_mod.diagnose()
        except Exception as e:                               # noqa: BLE001
            return f"diagnostics failed ({type(e).__name__})"
        self._copy(block)
        return "diagnostics copied — no transcripts, no keys; read it before sending"

    def _do_quit(self, arg) -> str:
        """Settings > About > Quit DeskIT (dashboard._quit): the named
        event, not the pipe — it works during a start-up too."""
        import singleton
        if singleton.request_quit():
            return "quitting — the next start loads the model again, about 25 seconds"
        return "nothing to stop"

    def _do_tour(self, arg) -> str:
        if not self.running:
            return "start dictation first — the tour is shown beside the running app's dot"
        return self._announce(self._ask("tour"), "the tour is beside the dot")


def _window():
    """The desk's window, when this place is drawn in one (pywebview is
    imported by the shell; a test or CI without it has none)."""
    import sys
    webview = sys.modules.get("webview")
    if webview is None:
        return None
    windows = list(getattr(webview, "windows", None) or [])
    return windows[0] if windows else None
