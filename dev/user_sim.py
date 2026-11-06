"""The user, simulated: a REAL App driven the way a person drives it.

The owner's ask (2026-09-18): "you test through the code, not through
use — build a tool that behaves like a user: when I press Start and
right after it Stop, that is not if/else." So this builds the real
`main.App` (real threads, real hook state machine, real dot on the
desktop it runs on, the fake speech backend so no GPU is touched),
starts it, and then PRESSES THINGS with a person's timing: the desk's
buttons through the same pipe verbs the desk sends, the keys through the
same `machine.handle` the keyboard hook calls. Each scenario asserts
what the person would see — the dot, the status, the sentences said,
the log lines — and the run ends with one table.

Run it on the hidden desktop, never on the owner's screen:

    python dev/user_sim.py            (tests_quiet.run_hidden wraps it)

It never touches the owner's running copy: no singleton, no pipe, and
the paste into the focused window is stubbed — SendInput would land on
the INPUT desktop, which is his.
"""
from __future__ import annotations

import dataclasses
import logging
import os
import sys
import threading
import time
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
APP = HERE.parent
sys.path.insert(0, str(APP))
os.chdir(APP)
os.environ.setdefault("DESKIT_PORTABLE", "1")

# SILENT, before anything of the app's is imported: a hidden desktop
# hides the window and not the beep (AGENTS.md rule 8).
import winsound                      # noqa: E402
winsound.PlaySound = lambda *a, **k: None
winsound.Beep = lambda *a, **k: None
import cues                          # noqa: E402
cues.play = lambda kind: None

import awake as awake_mod            # noqa: E402
import config as config_mod          # noqa: E402
import hotkey as hotkey_mod          # noqa: E402
import injector                      # noqa: E402
import main as main_mod              # noqa: E402
import sb                            # noqa: E402
from hotkey import parse_binding     # noqa: E402

VK_RCTRL, VK_LWIN, VK_LSHIFT, VK_S, VK_ESC = 0xA3, 0x5B, 0xA0, 0x53, 0x1B
VK_LCTRL, VK_LALT, VK_N = 0xA2, 0xA4, 0x4E          # ctrl+alt+n: the screens key

# A person's pace. A press is a down and an up; "at once" is the
# shortest gap a hand can manage between two buttons.
TAP_S = 0.08
AT_ONCE_S = 0.05
THINK_S = 0.4
LOAD_S = 1.0          # the fake model's "25 seconds"


class Log(logging.Handler):
    """Every line the app says, kept, so a scenario can ask "did it say
    'drag the part of the screen'?" the way a person reads the log."""

    def __init__(self) -> None:
        super().__init__(level=logging.INFO)
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        try:
            line = record.getMessage()
            if record.exc_info and record.exc_info[1] is not None:
                line += f"  [{type(record.exc_info[1]).__name__}: {record.exc_info[1]}]"
            self.lines.append(line)
        except Exception:                                    # noqa: BLE001
            pass

    def saw(self, text: str, since: int = 0) -> bool:
        return any(text in line for line in self.lines[since:])

    def wait(self, text: str, since: int = 0, timeout: float = 3.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.saw(text, since):
                return True
            time.sleep(0.02)
        return False


class Sim:
    def __init__(self) -> None:
        sb.REQUIRED = False              # the account lock is not what this measures
        self.log = Log()
        logging.getLogger("app").addHandler(self.log)
        logging.getLogger("app").setLevel(logging.INFO)
        self.said: list[str] = []
        self.pasted: list[str] = []
        # the paste into the focused window: recorded, never sent
        injector.inject = lambda text, chord, delay: self.pasted.append(text) or "ok"
        injector.paste_text = lambda text, chord, delay, **kw: self.pasted.append(text) or "ok"
        # ...and the clipboard fallback (no window to paste into on a
        # hidden desktop): the clipboard is shared with the owner's desk,
        # so it is recorded here and never written
        injector.set_text = lambda text: self.pasted.append(text)
        # THE OWNER'S MONITORS MUST NEVER GO DARK FROM A SIMULATION. The
        # real broadcast raises (and the run says so if it was reached);
        # every engine this sim builds is handed `monitor` instead, a
        # recorder of what WOULD have been sent (see _tame).
        self.monitor: list[int] = []

        def never_for_real(state: int) -> bool:
            raise AssertionError("the sim reached the real monitor broadcast")

        awake_mod.send_monitor_power = never_for_real
        cfg = config_mod.load_layered()
        # No repair pass: it would run the owner's Ollama on his GPU for
        # every simulated sentence, and the second reading likewise. No
        # wake hold either (the process would keep the PC awake), and no
        # watchdog, probe thread or vitals line around the screens mode.
        self.cfg = dataclasses.replace(
            cfg, backend="fake",
            polish=dataclasses.replace(cfg.polish, when="never"),
            review=dataclasses.replace(cfg.review, enabled=False)
            if getattr(cfg, "review", None) is not None else None,
            awake=dataclasses.replace(
                cfg.awake, hold=False, vitals_minutes=0,
                screens_off_again_s=0, keep_screens_off_s=0))
        # The real model takes ~25 s to load; the fake takes none, which
        # would make "Start, then Stop at once" a Stop AFTER the load.
        # A second of load is what gives the person time to press.
        real_get = main_mod.get_transcriber

        def slow_get(cfg, hotwords=None, **kw):
            # **kw: main.py passes english_later= since 3f57289; a fake
            # that refused it made every Start scenario fail (2026-09-21)
            time.sleep(LOAD_S)
            return real_get(cfg, hotwords, **kw)

        main_mod.get_transcriber = slow_get
        self.app: main_mod.App | None = None
        self.results: list[tuple[str, str]] = []

    # ---- what a person does

    def _tame(self, app) -> None:
        """The screens engine of a sim App: the recorder in the sender's
        place, no probe thread. Called BEFORE anything can darken."""
        app.awake._sender = lambda state: self.monitor.append(state) or True
        app.awake._probe_to_log = lambda: None

    def open_the_desk(self) -> None:
        """Nothing running, the desk opens: the app comes up without the
        model (dashboard.bring_up_the_keys → main.py --no-model)."""
        self.app = main_mod.App(self.cfg, model=False)
        self._tame(self.app)
        self.app._say = self.said.append
        self.app.start()
        time.sleep(THINK_S)

    def tap_screens_key(self, app=None) -> None:
        """ctrl+alt+n, the way the hook feeds it to the state machine."""
        m = (app or self.app).machine
        for vk in (VK_LCTRL, VK_LALT, VK_N):
            m.handle("down", vk, injected=False)
            time.sleep(0.01)
        time.sleep(TAP_S)
        for vk in (VK_N, VK_LALT, VK_LCTRL):
            m.handle("up", vk, injected=False)

    @staticmethod
    def until(cond, timeout: float = 5.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if cond():
                return True
            time.sleep(0.02)
        return bool(cond())

    def press(self, name: str) -> dict:
        """A desk button. Start = `load` with the process up, Stop =
        `unload` — the verbs dashboard._toggle_pause/_stop send."""
        verb = {"Start": "load", "Stop": "unload"}[name]
        return self.app.control_command(verb, {})

    def hold_key(self, down: bool) -> None:
        self.app.machine.handle("down" if down else "up", VK_RCTRL, injected=False)

    def tap_screenshot(self) -> None:
        m = self.app.machine
        for vk in (VK_LWIN, VK_LSHIFT, VK_S):
            m.handle("down", vk, injected=False)
            time.sleep(0.01)
        time.sleep(TAP_S)
        for vk in (VK_S, VK_LSHIFT, VK_LWIN):
            m.handle("up", vk, injected=False)

    def wait_model(self, state: str, timeout: float = 30.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.app._model_state == state:
                return True
            time.sleep(0.02)
        return False

    def dot_on_screen(self) -> bool:
        return not self.app.dot.hidden and self.app.dot.rect is not None

    # ---- the scenarios

    def run(self, name, fn) -> None:
        try:
            fn()
            self.results.append((name, "PASS"))
        except Exception as e:                               # noqa: BLE001
            self.results.append((name, f"FAIL: {e}"))
            traceback.print_exc(file=sys.stdout)
            print("  the app's last lines:")
            for line in self.log.lines[-12:]:
                print("   |", line[:140])
            print("  said:", self.said[-4:])

    def s_desk_opens_without_the_model(self) -> None:
        self.open_the_desk()
        st = self.app.status()
        assert st["model"] == "off" and st["backend"] == "off", st
        assert st["activity"] == "paused" and not st["paused"], st
        assert self.app.machine.dictation_off and not self.app.machine.paused
        assert not self.dot_on_screen(), "a dot with no model behind it"
        assert self.log.saw("up without the model")

    def s_screenshot_works_without_the_model(self) -> None:
        n = len(self.log.lines)
        self.tap_screenshot()
        assert self.log.wait("drag the part of the screen to capture", n), \
            "the screenshot key did nothing with the model off"
        self.app.capture._cancel.set()                       # Esc, in effect
        time.sleep(THINK_S)
        for line in self.log.lines[n:]:
            if "fail" in line or "Error" in line:
                print("   (screenshot flow on this desktop:", line[:160], ")")

    def s_hold_key_is_refused_without_the_model(self) -> None:
        n = len(self.said)
        self.hold_key(True)
        time.sleep(TAP_S)
        self.hold_key(True)                                  # Windows' auto-repeat
        self.hold_key(False)
        assert self.said[n:] == [main_mod.App.MODEL_OFF_WORDS], self.said[n:]
        assert self.app.machine.state == hotkey_mod.IDLE
        assert not self.dot_on_screen()

    def s_screens_card_with_the_model_off(self) -> None:
        """The "Screens off" card (2026-10-07) with the model OFF: the key
        puts it up, nothing a person presses takes it down but the mode
        ending, a notification stacks above it and survives its ending."""
        import notify_card as nc
        app = self.app
        card = app.notify_card
        assert app.status()["model"] == "off"
        self.monitor.clear()
        n = len(self.log.lines)

        self.tap_screens_key()
        assert self.until(lambda: app.awake.dark), "the screens key did nothing"
        assert self.until(card.pinned), "no card went up with the screens"
        assert self.until(lambda: card.rect is not None), \
            "the card is pinned but no window drew it"
        assert self.monitor and self.monitor[0] == awake_mod.MONITOR_OFF, \
            self.monitor
        assert "screens off" in self.said[-1], self.said[-1]

        # Esc with the pointer on it, and the dismiss key: neither takes
        # the pin down
        card.hovering = lambda: True
        assert app._popup_key(VK_ESC) is False, "Esc was eaten by the pin"
        app.notify.dismiss(by="key")
        time.sleep(THINK_S)
        assert card.pinned() and card.rect is not None, \
            "something dismissed the card"

        # a notification arrives: it stacks ABOVE the pin
        app._notify_from_outside({"title": "Claude finished", "kind": "done",
                                  "source": "claude-code",
                                  "body": "It is done."})
        assert self.until(card.visible), "the notification never showed"
        with card._state_lock:
            column = [c["id"] for c in card._drawn()]
        assert column[-1] == nc.PIN_ID and len(column) == 2, column

        # Esc over the column dismisses THE NOTIFICATION and not the pin
        assert app._popup_key(VK_ESC) is True
        assert self.until(lambda: not card.visible())
        assert card.pinned() and card.rect is not None, \
            "Esc over the column took the pin with it"

        # one more arrives, and the screens key ends the mode: the pin
        # goes, the notification stays
        app._notify_from_outside({"title": "Another", "kind": "done",
                                  "source": "claude-code", "body": "Again."})
        assert self.until(card.visible)
        self.tap_screens_key()
        assert self.until(lambda: not app.awake.dark)
        assert self.until(lambda: not card.pinned()), "the pin outlived the mode"
        time.sleep(THINK_S)
        assert card.visible() and card.rect is not None, \
            "the notification went down with the pin"
        assert self.said[-1] == "screens on", self.said[-1]
        assert self.until(lambda: awake_mod.MONITOR_ON in self.monitor)
        assert self.monitor.count(awake_mod.MONITOR_OFF) == 1, self.monitor
        assert not self.log.saw("screen broadcast failed", n), \
            "the real monitor broadcast was reached"
        app.notify.dismiss(by="key")
        time.sleep(THINK_S)

    def s_screens_card_button(self) -> None:
        """The pill on the card, with the model ON, the mode started from
        the desk's road (the control verb the Awake screen sends)."""
        import notify_card as nc
        app = self.app
        card = app.notify_card
        assert app.status()["model"] == "on"
        self.monitor.clear()
        r = app.control_command("screens", {"do": "off"})
        assert r["ok"] and r["awake"]["dark"], r
        assert self.until(card.pinned) and self.until(
            lambda: card.rect is not None)
        # a click on the card's body is nothing
        card.pressed("open", nc.PIN_ID)
        card.pressed("dismiss", nc.PIN_ID)
        time.sleep(THINK_S)
        assert card.pinned() and app.awake.dark
        # the pill: the mode ends, the card goes, it says so once
        said = len(self.said)
        card.pressed("button", nc.PIN_ID)
        assert self.until(lambda: not app.awake.dark), "the pill did nothing"
        assert self.until(lambda: not card.pinned()), "the pin outlived the mode"
        assert self.until(lambda: card.rect is None), "the window stayed up"
        assert self.said[said:] == ["screens on"], self.said[said:]
        assert self.monitor == [awake_mod.MONITOR_OFF, awake_mod.MONITOR_ON], \
            self.monitor
        # and the card follows the mode when the PHONE ends it too
        r = app.control_command("screens", {"do": "off"})
        assert r["ok"] and self.until(card.pinned)
        r = app.control_command("screens", {"do": "on"})
        assert r["ok"] and self.until(lambda: not card.pinned())

    def s_start_then_stop_at_once(self) -> None:
        r = self.press("Start")
        assert r["ok"], r
        time.sleep(AT_ONCE_S)
        r = self.press("Stop")
        assert not r["ok"] and "loading" in r["error"], r
        assert self.wait_model("on"), "the model never came"
        time.sleep(THINK_S)
        st = self.app.status()
        assert st["model"] == "on" and st["backend"] == "fake" and st["activity"] == "ready", st
        assert not self.app.machine.dictation_off
        assert self.dot_on_screen(), "no dot with the model loaded"
        assert self.said[-1] == "listening again", self.said[-3:]

    def s_stop_while_recording_is_refused_then_the_dictation_lands(self) -> None:
        self.hold_key(True)
        time.sleep(THINK_S)
        r = self.press("Stop")
        assert not r["ok"] and "microphone" in r["error"], r
        assert self.app.status()["activity"] == "recording"
        n = len(self.pasted)
        self.hold_key(False)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and len(self.pasted) == n:
            time.sleep(0.05)
        assert len(self.pasted) > n, "the dictation never landed"
        time.sleep(THINK_S)
        assert self.app.status()["activity"] == "ready"

    def s_stop_and_start_hammered(self) -> None:
        for _ in range(3):
            r = self.press("Stop")
            assert r["ok"], r
            assert self.wait_model("off", 10), "the unload never finished"
            assert not self.dot_on_screen(), "the dot stayed after Stop"
            assert self.app.machine.dictation_off
            time.sleep(AT_ONCE_S)
            r = self.press("Start")
            assert r["ok"], r
            assert self.wait_model("on"), "the load never finished"
            time.sleep(THINK_S)
            assert self.dot_on_screen(), "no dot after Start"
            assert not self.app.machine.dictation_off
        st = self.app.status()
        assert st["model"] == "on" and st["activity"] == "ready", st

    def s_phone_is_refused_with_the_model_off(self) -> None:
        assert self.press("Stop")["ok"]
        assert self.wait_model("off", 10)
        try:
            self.app._transcribe_for_phone(b"RIFF")
        except RuntimeError as e:
            assert str(e) == main_mod.App.MODEL_OFF_WORDS
        else:
            raise AssertionError("the phone dictated into an unloaded model")
        assert not self.dot_on_screen()

    def s_quit_takes_everything(self) -> None:
        self.app.stop()
        thread = self.app.dot._thread
        assert thread is None or not thread.is_alive(), "the dot outlived the app"
        self.app = None

    def s_screens_card_with_notifications_off(self) -> None:
        """[notify] enabled = false and the screens card on: the column is
        still built for the pin, and the notification engine is handed an
        inert card, so nothing a program POSTs ever shows."""
        import notify as notify_mod
        import notify_card as nc
        cfg = dataclasses.replace(
            self.cfg, notify=dataclasses.replace(self.cfg.notify, enabled=False))
        app = main_mod.App(cfg, model=False)
        self.app = app
        self._tame(app)
        app._say = self.said.append
        app.start()
        time.sleep(THINK_S)
        assert isinstance(app.notify.card, notify_mod.NullCard), \
            "the engine was handed the real column with notifications off"
        card = app.notify_card
        assert hasattr(card, "pin"), "no column was built for the pin"
        r = app.control_command("screens", {"do": "off"})
        assert r["ok"] and self.until(card.pinned) and self.until(
            lambda: card.rect is not None), "no card with notifications off"
        try:
            app._notify_from_outside({"title": "x", "source": "t"})
        except Exception:                                    # noqa: BLE001
            pass                                  # refused is fine; shown is not
        time.sleep(THINK_S)
        with card._state_lock:
            assert [c["id"] for c in card._drawn()] == [nc.PIN_ID]
        assert not card.visible()
        card.pressed("button", nc.PIN_ID)
        assert self.until(lambda: not card.pinned() and not app.awake.dark)
        app.stop()
        self.app = None

    # In the order a person meets them: the desk opens, the keys that
    # need no model, the first Start, dictation, the hammering, the end.
    ORDER = ("desk_opens_without_the_model",
             "screenshot_works_without_the_model",
             "hold_key_is_refused_without_the_model",
             "screens_card_with_the_model_off",
             "start_then_stop_at_once",
             "screens_card_button",
             "stop_while_recording_is_refused_then_the_dictation_lands",
             "stop_and_start_hammered",
             "phone_is_refused_with_the_model_off",
             "quit_takes_everything",
             "screens_card_with_notifications_off")

    def all(self) -> int:
        for name in self.ORDER:
            self.run(name, getattr(self, "s_" + name))
            if self.app is None and name not in ("quit_takes_everything",
                                                 "screens_card_with_notifications_off"):
                break
        if self.app is not None:
            try:
                self.app.stop()
            except Exception:                                # noqa: BLE001
                pass
        width = max(len(n) for n, _ in self.results)
        print()
        for name, verdict in self.results:
            print(f"  {verdict[:4]:5} {name.ljust(width)}  {verdict[6:]}")
        failed = [n for n, v in self.results if not v.startswith("PASS")]
        print(f"\n{len(self.results) - len(failed)} of {len(self.results)} scenarios passed")
        return 1 if failed else 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    code = Sim().all()
    sys.stdout.flush()
    os._exit(code)
