"""Unit tests — run with:  .venv\\Scripts\\python.exe tests.py

Plain asserts, no pytest. Covers the state machine's abort paths, key-name
tables, WAV building, config parsing, the fake backend, and a real
clipboard round-trip (saves and restores whatever is on it).
"""
from __future__ import annotations

import io
import sys
import threading
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

import apikey
import config as config_mod
import injector
import singleton
from hotkey import PTTStateMachine, parse_chord, vk_for, vk_name
from recorder import frames_to_wav
from transcribers.fake import FakeTranscriber

FAILURES: list[str] = []

VK_RCTRL = 0xA3
VK_LCTRL = 0xA2
VK_C = 0x43
VK_V = 0x56
VK_SHIFT = 0x10


def check(name: str, fn) -> None:
    try:
        fn()
        print(f"  PASS  {name}")
    except AssertionError as e:
        FAILURES.append(name)
        print(f"  FAIL  {name}: {e}")
    except Exception as e:  # noqa: BLE001
        FAILURES.append(name)
        print(f"  FAIL  {name}: unexpected {type(e).__name__}: {e}")


class Spy:
    def __init__(self) -> None:
        self.events: list[str] = []

    def machine(self, hotkey_vk=VK_RCTRL) -> PTTStateMachine:
        return PTTStateMachine(
            hotkey_vk,
            on_start=lambda lang: self.events.append("start"),
            on_stop=lambda lang: self.events.append("stop"),
            on_abort=lambda why: self.events.append(f"abort:{why}"))

    def lang_machine(self, hotkeys: dict) -> PTTStateMachine:
        return PTTStateMachine(
            hotkeys,
            on_start=lambda lang: self.events.append(f"start:{lang}"),
            on_stop=lambda lang: self.events.append(f"stop:{lang}"),
            on_abort=lambda why: self.events.append(f"abort:{why}"))


def test_press_release_cycle() -> None:
    spy = Spy()
    m = spy.machine()
    m.handle("down", VK_RCTRL, injected=False)
    m.handle("up", VK_RCTRL, injected=False)
    assert spy.events == ["start", "stop"], spy.events


def test_autorepeat_ignored() -> None:
    spy = Spy()
    m = spy.machine()
    for _ in range(4):  # Windows key auto-repeat while held
        m.handle("down", VK_RCTRL, injected=False)
    m.handle("up", VK_RCTRL, injected=False)
    assert spy.events == ["start", "stop"], spy.events


def test_physical_other_key_down_aborts() -> None:
    spy = Spy()
    m = spy.machine()
    m.handle("down", VK_RCTRL, injected=False)
    m.handle("down", VK_C, injected=False)   # user is doing Ctrl+C
    m.handle("up", VK_C, injected=False)
    m.handle("up", VK_RCTRL, injected=False)  # after abort: no stop
    assert spy.events == ["start", "abort:'c' pressed mid-hold"], spy.events


def test_injected_keys_never_abort() -> None:
    """Our own synthetic paste chord arrives with LLKHF_INJECTED set."""
    spy = Spy()
    m = spy.machine()
    m.handle("down", VK_RCTRL, injected=False)
    m.handle("down", VK_LCTRL, injected=True)   # synthetic ctrl+v begins
    m.handle("down", VK_V, injected=True)
    m.handle("up", VK_V, injected=True)
    m.handle("up", VK_LCTRL, injected=True)
    m.handle("up", VK_RCTRL, injected=False)
    assert spy.events == ["start", "stop"], spy.events


def test_injected_hotkey_still_works() -> None:
    """Test drivers (SendInput) must be able to run the PTT cycle."""
    spy = Spy()
    m = spy.machine()
    m.handle("down", VK_RCTRL, injected=True)
    m.handle("up", VK_RCTRL, injected=True)
    assert spy.events == ["start", "stop"], spy.events


def test_left_ctrl_is_not_the_hotkey() -> None:
    spy = Spy()
    m = spy.machine()  # hotkey = right ctrl
    m.handle("down", VK_LCTRL, injected=False)  # idle: ignored
    m.handle("up", VK_LCTRL, injected=False)
    assert spy.events == [], spy.events
    m.handle("down", VK_RCTRL, injected=False)
    m.handle("down", VK_LCTRL, injected=False)  # recording: physical -> abort
    assert spy.events == ["start", "abort:'left ctrl' pressed mid-hold"], \
        spy.events


def test_other_key_up_does_not_abort() -> None:
    spy = Spy()
    m = spy.machine()
    m.handle("down", VK_RCTRL, injected=False)
    m.handle("up", VK_SHIFT, injected=False)  # lingering shift released
    m.handle("up", VK_RCTRL, injected=False)
    assert spy.events == ["start", "stop"], spy.events


def test_other_key_while_idle_ignored() -> None:
    spy = Spy()
    m = spy.machine()
    m.handle("down", VK_C, injected=False)
    m.handle("up", VK_C, injected=False)
    assert spy.events == [], spy.events


def test_vk_tables() -> None:
    assert vk_for("right ctrl") == VK_RCTRL
    assert vk_for("LEFT CTRL") == VK_LCTRL
    assert vk_for(" f9 ") == 0x78
    assert vk_name(VK_RCTRL) == "right ctrl"
    assert parse_chord("ctrl+v") == [0x11, VK_V]
    assert parse_chord("shift+insert") == [VK_SHIFT, 0x2D]
    for bad in ("ctrl+", "", "hyperkey"):
        try:
            parse_chord(bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"parse_chord({bad!r}) did not raise")


def test_frames_to_wav_format() -> None:
    tone = (np.sin(np.linspace(0, 2 * np.pi * 440, 16000))
            * 8000).astype(np.int16).reshape(-1, 1)
    data = frames_to_wav([tone[:8000], tone[8000:]], 16000)
    with wave.open(io.BytesIO(data)) as w:
        assert w.getnchannels() == 1
        assert w.getsampwidth() == 2
        assert w.getframerate() == 16000
        assert w.getnframes() == 16000, w.getnframes()


def test_config_loads_and_validates() -> None:
    cfg = config_mod.load(Path(__file__).parent / "config.toml")
    assert cfg.hotkey == "right ctrl"
    assert cfg.backend in config_mod.VALID_BACKENDS
    assert cfg.min_seconds < cfg.max_seconds
    assert cfg.audio.device is None or isinstance(cfg.audio.device,
                                                  (int, str))
    assert config_mod._parse_device("") is None  # "" -> system default
    assert config_mod._parse_device("3") == 3
    assert config_mod._parse_device(" Yeti ") == "Yeti"
    vk_for(cfg.hotkey)          # config values must map to keys
    parse_chord(cfg.paste_chord)


def test_fake_transcriber_is_hebrew() -> None:
    fake = FakeTranscriber()
    out = fake.transcribe(b"\x00" * (44 + 32000))  # 1.0 s of audio
    assert "בדיקה 1" in out and "git commit" in out and "1.0" in out, out
    out2 = fake.transcribe(b"\x00" * 44)
    assert "בדיקה 2" in out2, out2


def test_api_key_file_parsing(tmp_lines=None) -> None:
    """The .env fallback must survive comments, quotes, blank lines and a
    UTF-8 BOM — it exists so a broken shell environment can't block us."""
    original = apikey.ENV_FILE
    sample = original.parent / ".env.selftest"
    sample.write_text('﻿# comment\n\nGEMINI_API_KEY = "abc-123" \n',
                      encoding="utf-8")
    try:
        apikey.ENV_FILE = sample
        os_key = apikey._from_env_file()
        assert os_key is not None, "key file not parsed"
        assert os_key[0] == "abc-123", os_key
    finally:
        apikey.ENV_FILE = original
        sample.unlink(missing_ok=True)


def test_real_key_is_discoverable() -> None:
    key, source = apikey.find_api_key()
    assert key, f"no API key found (source={source})"
    assert len(key) > 20, "key looks truncated"


def test_single_instance_guard() -> None:
    """A second instance must be refused: two live instances would both
    paste on every dictation. Uses private object names so a real running
    instance is unaffected."""
    original = singleton.MUTEX_NAME
    singleton.MUTEX_NAME = r"Local\HebrewDictation.selftest.instance"
    lock = None
    try:
        lock = singleton.InstanceLock()
        try:
            singleton.InstanceLock()
        except singleton.AlreadyRunning:
            pass
        else:
            raise AssertionError("second instance was NOT refused")
        lock.release()
        lock = None
        singleton.InstanceLock().release()  # free again after release
    finally:
        if lock is not None:
            lock.release()
        singleton.MUTEX_NAME = original


def test_quit_signal_roundtrip() -> None:
    original = singleton.QUIT_EVENT_NAME
    singleton.QUIT_EVENT_NAME = r"Local\HebrewDictation.selftest.quit"
    signal = None
    try:
        assert not singleton.request_quit(), \
            "request_quit() reported success with nothing running"
        signal = singleton.QuitSignal()
        assert singleton.request_quit(), "could not signal a live instance"
        signal.wait()  # must return immediately, not hang
    finally:
        if signal is not None:
            signal.close()
        singleton.QUIT_EVENT_NAME = original


def test_cue_files_are_valid_wavs() -> None:
    """The cues must be real WAV files: winsound.PlaySound fails silently
    on a malformed one, which is exactly the bug we are fixing."""
    import cues

    paths = cues.ensure_files(force=True)
    assert set(paths) == set(cues.CUES), paths
    for kind, path in paths.items():
        with wave.open(str(path)) as w:
            assert w.getnchannels() == 1
            assert w.getsampwidth() == 2
            assert w.getframerate() == cues.SAMPLE_RATE
            expected = sum(ms for _f, ms in cues.CUES[kind]) / 1000
            actual = w.getnframes() / w.getframerate()
            assert abs(actual - expected) < 0.02, (kind, actual, expected)


def test_launcher_scripts_point_at_the_venv() -> None:
    here = Path(__file__).resolve().parent
    for name, needle in (("Hebrew Dictation.vbs", "main.py"),
                         ("Stop Dictation.vbs", "--stop")):
        script = here / name
        assert script.exists(), f"{name} missing"
        body = script.read_text(encoding="utf-8")
        assert "pythonw.exe" in body, f"{name} would open a console window"
        assert needle in body, f"{name} lost its arguments"


def test_clipboard_roundtrip_and_restore() -> None:
    before = injector.snapshot()
    if before[0] == "other":
        print("        (clipboard holds non-text content — skipping "
              "round-trip so it isn't lost)")
        return
    try:
        marker = "בדיקת לוח — HebrewDictation"
        injector.set_text(marker)
        kind, text = injector.snapshot()
        assert kind == "text" and text == marker, (kind, text)
    finally:
        if before[0] == "text":
            injector.set_text(before[1] or "")
    if before[0] == "text":
        after = injector.snapshot()
        assert after[1] == before[1], "clipboard not restored"


# ------------------------------------------------- quota / spool / recovery

def test_erase_units_counts_utf16() -> None:
    """Backspace deletes UTF-16 code units, so the placeholder must be
    counted that way or the erase leaves debris / eats real text."""
    assert injector.erase_units("...") == 3
    assert injector.erase_units("") == 0
    assert injector.erase_units("שלום") == 4        # BMP: 1 unit each
    assert injector.erase_units("⏳") == 1           # BMP symbol
    assert injector.erase_units("🎤") == 2           # astral: surrogate pair


def test_parse_429_reads_per_day_cap() -> None:
    from google.genai import errors as genai_errors

    from transcribers.gemini import _parse_429

    class FakeAPIError(genai_errors.APIError):
        def __init__(self, message, details=None):
            self.message = message
            self.details = details
            self.code = 429

    msg = ("You exceeded your current quota. * Quota exceeded for metric: "
           "generate_content_free_tier_requests, limit: 20, model: "
           "gemini-2.5-flash\nPlease retry in 17.07s.")
    retry_after, per_day, limit = _parse_429(
        FakeAPIError.__new__(FakeAPIError))
    # message-only path
    err = FakeAPIError.__new__(FakeAPIError)
    err.message, err.details, err.code = msg, None, 429
    retry_after, per_day, limit = _parse_429(err)
    assert abs(retry_after - 17.07) < 0.01, retry_after
    assert limit == 20, limit
    # "PerDay" appears in the structured quotaId, not this message text
    err.details = {"error": {"details": [
        {"@type": "type.googleapis.com/google.rpc.QuotaFailure",
         "violations": [{"quotaId": "GenerateRequestsPerDayPerProjectPerModel"
                                    "-FreeTier", "quotaValue": "20"}]},
        {"@type": "type.googleapis.com/google.rpc.RetryInfo",
         "retryDelay": "16s"}]}}
    retry_after, per_day, limit = _parse_429(err)
    assert per_day is True
    assert retry_after == 16.0, retry_after
    assert limit == 20, limit


def test_rate_limit_error_carries_retry_hint() -> None:
    from transcribers.base import RateLimitError, TranscriptionError
    e = RateLimitError("spent", retry_after=42.0, per_day=True)
    assert isinstance(e, TranscriptionError)   # existing handlers still catch
    assert e.retry_after == 42.0 and e.per_day is True
    assert RateLimitError("x").retry_after == 0.0


def test_gemini_rotates_past_an_exhausted_model() -> None:
    """The whole point of the model list: model 1 out of quota must not end
    the dictation — model 2 answers it."""
    from transcribers.base import RateLimitError
    from transcribers.gemini import GeminiTranscriber

    t = GeminiTranscriber.__new__(GeminiTranscriber)   # no API key needed
    t._models = ["dead", "alive"]
    t._cooldown, t._strikes, t._thinking = {}, {}, {}
    calls: list[str] = []

    def fake_one(model, wav, language=None):
        calls.append(model)
        if model == "dead":
            raise _fake_429()
        return "טקסט"

    t._one = fake_one
    assert t.transcribe(b"wav") == "טקסט"
    assert calls == ["dead", "alive"], calls
    assert t._cooldown["dead"] > 0
    # second call skips the resting model entirely
    calls.clear()
    assert t.transcribe(b"wav") == "טקסט"
    assert calls == ["alive"], calls


def test_gemini_reports_when_every_model_is_spent() -> None:
    from transcribers.base import RateLimitError
    from transcribers.gemini import GeminiTranscriber

    t = GeminiTranscriber.__new__(GeminiTranscriber)
    t._models = ["a", "b"]
    t._cooldown, t._strikes, t._thinking = {}, {}, {}
    t._one = lambda model, wav, language=None: (
        _ for _ in ()).throw(_fake_429())
    try:
        t.transcribe(b"wav")
    except RateLimitError as e:
        assert e.per_day is True
        assert "out of free-tier quota" in str(e), e
    else:
        raise AssertionError("expected RateLimitError when all are spent")


def _fake_429():
    from google.genai import errors as genai_errors
    e = genai_errors.APIError.__new__(genai_errors.APIError)
    e.code = 429
    e.message = ("Quota exceeded for metric: generate_content_free_tier_"
                 "requests, limit: 20, model: x. Please retry in 15s.")
    e.details = {"error": {"details": [
        {"@type": "type.googleapis.com/google.rpc.QuotaFailure",
         "violations": [{"quotaId": "GenerateRequestsPerDayPerProject"
                                    "PerModel-FreeTier"}]}]}}
    return e


def test_spool_saves_and_recovers_audio() -> None:
    """The bug this whole change exists to fix: a failed transcription must
    leave the audio on disk, not drop it."""
    import shutil
    import tempfile

    from spool import Spool

    tmp = Path(tempfile.mkdtemp(prefix="dictation-spool-test-"))
    try:
        spool = Spool(tmp)
        assert spool.pending() == []
        item = spool.save(b"RIFFfake-wav-bytes", 12.5, "429 quota")
        assert item.wav_path.exists() and item.meta_path.exists()

        found = spool.pending()
        assert len(found) == 1, found
        assert found[0].read() == b"RIFFfake-wav-bytes"
        assert abs(found[0].seconds - 12.5) < 0.01
        assert found[0].meta["attempts"] == 1
        assert "429" in found[0].meta["last_error"]

        found[0].bump("still 429")
        assert spool.pending()[0].meta["attempts"] == 2

        found[0].discard()
        assert spool.pending() == []
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_spool_replays_oldest_first_and_trims() -> None:
    import shutil
    import tempfile

    from spool import Spool

    tmp = Path(tempfile.mkdtemp(prefix="dictation-spool-test-"))
    try:
        spool = Spool(tmp, keep=3)
        for i in range(5):
            spool.save(b"x" * (i + 1), float(i), f"err {i}")
        names = [p.wav_path.name for p in spool.pending()]
        assert len(names) == 3, names             # trimmed to keep=3
        assert names == sorted(names), "must replay oldest first"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_config_accepts_model_list_and_legacy_single_model() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "c.toml"
        p.write_text('backend = "gemini"\n[gemini]\n'
                     'models = ["one", "two"]\n', "utf-8")
        cfg = config_mod.load(p)
        assert cfg.gemini.models == ("one", "two"), cfg.gemini.models
        assert cfg.gemini.model == "one"          # first is the primary

        p.write_text('backend = "gemini"\n[gemini]\nmodel = "solo"\n', "utf-8")
        assert config_mod.load(p).gemini.models == ("solo",)

        # an empty placeholder would mean "erase nothing" -> stray marker
        p.write_text('[feedback]\nenabled = true\nplaceholder = ""\n', "utf-8")
        try:
            config_mod.load(p)
        except config_mod.ConfigError:
            pass
        else:
            raise AssertionError("empty placeholder must be rejected")


class _FakeInjector:
    """Stands in for the real typing layer so the worker's DECISIONS can be
    asserted without driving the keyboard. The real paste/backspace path is
    covered separately against a live window."""

    def __init__(self, focus: int = 4242):
        self.calls: list[tuple] = []
        self.focus = focus
        self.ClipboardBusyError = injector.ClipboardBusyError
        self.FocusChangedError = injector.FocusChangedError

    def foreground_window(self):
        return self.focus

    def show_placeholder(self, text, chord, delay):
        self.calls.append(("show", text))
        return self.focus

    def replace_placeholder(self, placeholder, text, chord, delay, hwnd):
        if hwnd and self.foreground_window() != hwnd:
            raise injector.FocusChangedError("moved")
        self.calls.append(("replace", placeholder, text))
        return "old clipboard restored"

    def clear_placeholder(self, placeholder, hwnd):
        self.calls.append(("clear", placeholder))
        return True

    def inject(self, text, chord, delay):
        self.calls.append(("inject", text))
        return "old clipboard restored"

    def set_text(self, text):
        self.calls.append(("clipboard", text))


def _worker_app(backend, spool_dir, retry_seconds=5.0):
    import dataclasses

    import main as main_mod
    from spool import Spool

    cfg = config_mod.load(Path(__file__).resolve().parent / "config.toml")
    cfg = dataclasses.replace(
        cfg,
        feedback=config_mod.FeedbackConfig(placeholder="...", enabled=True,
                                           retry_seconds=retry_seconds),
        fallback_to_local=False)
    app = main_mod.App.__new__(main_mod.App)
    app.cfg, app.transcriber, app._local = cfg, backend, False
    app.spool = Spool(Path(spool_dir))
    app._model_lock = threading.Lock()   # real App builds this in __init__
    return app


class _Flaky:
    name = "flaky"

    def __init__(self, fail_times, text="שלום"):
        self.fail_times, self.calls, self.text = fail_times, 0, text

    def transcribe(self, wav):
        from transcribers.base import RateLimitError
        self.calls += 1
        if self.calls <= self.fail_times:
            raise RateLimitError("simulated 429", retry_after=0.05)
        return self.text


def test_failed_recording_survives_and_is_recovered() -> None:
    """THE regression test: a backend failure must not destroy the speech.
    Audio goes to disk, the retry lands, the text still reaches the cursor,
    and only then is the audio dropped."""
    import shutil
    import tempfile

    import main as main_mod

    tmp = Path(tempfile.mkdtemp(prefix="dictation-e2e-"))
    fake = _FakeInjector()
    real = main_mod.injector
    try:
        main_mod.injector = fake
        app = _worker_app(_Flaky(fail_times=2), tmp)
        app._handle(b"RIFF-audio", 18.4, fake.focus)

        kinds = [c[0] for c in fake.calls]
        assert kinds == ["show", "replace"], fake.calls
        assert fake.calls[0][1] == "...", fake.calls[0]
        assert fake.calls[1][2] == "שלום", fake.calls[1]
        assert app.transcriber.calls == 3, app.transcriber.calls
        # audio was saved during the failures and cleaned up after success
        assert app.spool.pending() == [], app.spool.pending()
    finally:
        main_mod.injector = real
        shutil.rmtree(tmp, ignore_errors=True)


def test_permanent_failure_keeps_audio_and_removes_marker() -> None:
    """When it cannot be transcribed at all, the placeholder must come back
    down and the recording must still be on disk for --drain."""
    import shutil
    import tempfile

    import main as main_mod

    tmp = Path(tempfile.mkdtemp(prefix="dictation-e2e-"))
    fake = _FakeInjector()
    real = main_mod.injector
    try:
        main_mod.injector = fake
        app = _worker_app(_Flaky(fail_times=99), tmp, retry_seconds=0.2)
        app._handle(b"RIFF-audio", 22.0, fake.focus)

        kinds = [c[0] for c in fake.calls]
        assert kinds == ["show", "clear"], fake.calls
        left = app.spool.pending()
        assert len(left) == 1, left            # speech NOT lost
        assert left[0].read() == b"RIFF-audio"
        assert abs(left[0].seconds - 22.0) < 0.01
    finally:
        main_mod.injector = real
        shutil.rmtree(tmp, ignore_errors=True)


def test_moving_window_falls_back_to_clipboard() -> None:
    """If the user switched windows, never fire backspaces at it — leave the
    transcript on the clipboard instead."""
    import shutil
    import tempfile

    import main as main_mod

    tmp = Path(tempfile.mkdtemp(prefix="dictation-e2e-"))
    fake = _FakeInjector()
    real = main_mod.injector
    try:
        main_mod.injector = fake
        app = _worker_app(_Flaky(fail_times=0, text="טקסט"), tmp)
        app._handle(b"RIFF-audio", 5.0, hwnd=fake.focus)
        fake.calls.clear()

        # same recording, but focus has moved on since the placeholder
        fake.focus = 9999
        app._handle(b"RIFF-audio", 5.0, hwnd=1111)
        kinds = [c[0] for c in fake.calls]
        assert "clipboard" in kinds, fake.calls
        assert ("clipboard", "טקסט") in fake.calls, fake.calls
        assert "replace" not in kinds, "must not backspace a foreign window"
    finally:
        main_mod.injector = real
        shutil.rmtree(tmp, ignore_errors=True)


def test_silence_is_not_retried_or_spooled() -> None:
    """An empty transcript means no speech — it must not be treated as a
    failure worth retrying or keeping."""
    import shutil
    import tempfile

    import main as main_mod

    tmp = Path(tempfile.mkdtemp(prefix="dictation-e2e-"))
    fake = _FakeInjector()
    real = main_mod.injector
    try:
        main_mod.injector = fake
        app = _worker_app(_Flaky(fail_times=0, text="   "), tmp)
        app._handle(b"RIFF-audio", 3.0, fake.focus)
        assert [c[0] for c in fake.calls] == ["show", "clear"], fake.calls
        assert app.spool.pending() == []
        assert app.transcriber.calls == 1
    finally:
        main_mod.injector = real
        shutil.rmtree(tmp, ignore_errors=True)


def test_cleanup_removes_fillers_but_not_real_words() -> None:
    from cleanup import clean

    assert clean("אה, אני רוצה את זה") == "אני רוצה את זה"
    assert clean("המ, אולי מחר") == "אולי מחר"
    # "אמ" is a filler; "אמא" contains it but is a word
    assert clean("אמא שלי אמרה") == "אמא שלי אמרה"
    assert clean("תעשה את זה עכשיו") == "תעשה את זה עכשיו"
    # English technical terms must survive untouched — they are the point
    out = clean("אה, תוסיף את ה-commit הזה ל-branch אחר")
    assert "commit" in out and "branch" in out, out
    assert not out.startswith("אה"), out


def test_cleanup_collapses_restarted_phrases() -> None:
    from cleanup import clean

    assert clean("אני אני אני רוצה") == "אני רוצה"
    assert clean("זה זה לא עובד") == "זה לא עובד"
    # the real case from this user's transcripts: a Hebrew prefix is left
    # dangling by the restart and must not block the collapse
    assert (clean("ותשאיר רק את מה ש רק את מה שאנחנו בנינו")
            == "ותשאיר רק את מה שאנחנו בנינו")
    # no repetition -> untouched
    assert clean("הוא אמר לי ש הוא בא") == "הוא אמר לי ש הוא בא"
    assert clean("זה בית ספר טוב") == "זה בית ספר טוב"


def test_cleanup_never_empties_real_content() -> None:
    """A transcript that is all fillers must not vanish silently — better a
    messy paste than a lost one."""
    from cleanup import clean

    assert clean("") == ""
    assert clean("   ") == ""
    assert clean("אה") == "אה"        # nothing left after stripping -> keep
    assert clean("אה אמ המ").strip() != ""


class _StubDetector:
    def __init__(self, lang, prob):
        self.lang, self.prob = lang, prob

    def detect_language(self, audio=None, vad_filter=False):
        return self.lang, self.prob, []


def _router(lang, prob, threshold=0.8):
    from transcribers.local_whisper import LocalWhisperTranscriber
    t = LocalWhisperTranscriber.__new__(LocalWhisperTranscriber)
    t._language = "he"
    t._english_threshold = threshold
    t._english = _StubDetector(lang, prob)
    return t._pick_language(object())


VK_RALT = 0xA5


def test_second_hotkey_selects_english() -> None:
    """A dedicated key is the reliable path: detection scored a Hebrew
    sentence as English 0.57 on the real microphone."""
    spy = Spy()
    m = spy.lang_machine({VK_RCTRL: "he", VK_RALT: "en"})

    m.handle("down", VK_RCTRL, False)
    assert m.language == "he"
    m.handle("up", VK_RCTRL, False)

    m.handle("down", VK_RALT, False)
    assert m.language == "en"
    m.handle("up", VK_RALT, False)

    assert spy.events == ["start:he", "stop:he", "start:en", "stop:en"], \
        spy.events
    assert m.language is None      # nothing recording


def test_pressing_both_hotkeys_aborts() -> None:
    """Rather than silently guess which language was meant."""
    spy = Spy()
    m = spy.lang_machine({VK_RCTRL: "he", VK_RALT: "en"})
    m.handle("down", VK_RCTRL, False)
    m.handle("down", VK_RALT, False)          # physical -> abort
    assert m.state == "idle"
    assert spy.events[0] == "start:he"
    assert spy.events[1].startswith("abort:"), spy.events
    assert m.language is None


def test_english_hotkey_releases_independently() -> None:
    """Releasing the OTHER hotkey must not end an English recording."""
    spy = Spy()
    m = spy.lang_machine({VK_RCTRL: "he", VK_RALT: "en"})
    m.handle("down", VK_RALT, False)
    m.handle("up", VK_RCTRL, False)           # key-ups never abort or stop
    assert m.state == "recording", spy.events
    m.handle("up", VK_RALT, False)
    assert spy.events == ["start:en", "stop:en"], spy.events


def test_hotkeys_must_differ() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "c.toml"
        p.write_text('hotkey = "right ctrl"\n'
                     'english_hotkey = "right ctrl"\n', "utf-8")
        try:
            config_mod.load(p)
        except config_mod.ConfigError as e:
            assert "differ" in str(e), e
        else:
            raise AssertionError("identical hotkeys must be rejected")


def test_explicit_language_beats_detection() -> None:
    """When the user pressed the English key, no detector gets a vote."""
    from transcribers.local_whisper import LocalWhisperTranscriber

    calls = {}

    class FakeModel:
        def __init__(self, tag):
            self.tag = tag

        def transcribe(self, audio, **kw):
            calls["model"] = self.tag
            calls["language"] = kw.get("language")

            class Seg:
                text = "hello"
            return [Seg()], None

        def detect_language(self, audio=None, vad_filter=False):
            calls["detected"] = True
            return "he", 1.0, []

    t = LocalWhisperTranscriber.__new__(LocalWhisperTranscriber)
    t._model, t._english = FakeModel("he"), FakeModel("en")
    t._language, t._english_threshold = "he", 0.8
    t._cleanup, t._fillers = False, ()
    t._initial_prompt = None
    t._guards, t._boilerplate = {}, ()

    assert t.transcribe(b"RIFF", language="en") == "hello"
    assert calls["model"] == "en" and calls["language"] == "en", calls
    assert "detected" not in calls, "must not detect when told explicitly"

    calls.clear()
    assert t.transcribe(b"RIFF", language="he") == "hello"
    assert calls["model"] == "he" and calls["language"] == "he", calls
    assert "detected" not in calls


def test_language_router_is_biased_to_hebrew() -> None:
    """Measured 2026-08-12: the general model mis-detects very short Hebrew
    as pt/ru/nl at LOW confidence, but nails English at ~1.00. So English
    wins only when confident; everything else must stay Hebrew."""
    assert _router("en", 1.00) == "en"
    assert _router("en", 0.80) == "en"          # exactly at the bar
    assert _router("en", 0.79) == "he"          # just under -> safe default
    # the real misdetections that broke short Hebrew
    assert _router("pt", 0.73) == "he"
    assert _router("ru", 0.16) == "he"
    assert _router("nl", 0.67) == "he"
    # a confident non-English language is still not English
    assert _router("fr", 0.99) == "he"
    assert _router("he", 0.99) == "he"


def test_language_router_falls_back_safely() -> None:
    """No detector, or a detector that throws, must not break dictation."""
    from transcribers.local_whisper import LocalWhisperTranscriber

    t = LocalWhisperTranscriber.__new__(LocalWhisperTranscriber)
    t._language, t._english_threshold, t._english = "he", 0.8, None
    assert t._pick_language(object()) == "he"   # English model unavailable

    class Boom:
        def detect_language(self, audio=None, vad_filter=False):
            raise RuntimeError("cuda hiccup")

    t._english = Boom()
    assert t._pick_language(object()) == "he"


def test_initial_prompt_is_set_for_code_switching() -> None:
    """Guards the mixed-language fix: without an initial_prompt the decoder
    drops the English half of a Hebrew+English sentence entirely."""
    cfg = config_mod.load(Path(__file__).resolve().parent / "config.toml")
    prompt = cfg.local.initial_prompt
    assert prompt, "initial_prompt must not be empty"
    assert "commit" in prompt and "branch" in prompt, prompt
    assert any("֐" <= c <= "׿" for c in prompt), \
        "prompt must be Hebrew so the decoder stays in Hebrew"


def test_english_model_gets_no_hebrew_prompt() -> None:
    """A Hebrew initial_prompt would only confuse the English model."""
    from transcribers.local_whisper import LocalWhisperTranscriber

    seen = {}

    class FakeModel:
        def __init__(self, tag):
            self.tag = tag

        def transcribe(self, audio, **kw):
            seen[self.tag] = kw.get("initial_prompt")

            class Seg:
                text = "x"
            return [Seg()], None

    t = LocalWhisperTranscriber.__new__(LocalWhisperTranscriber)
    t._model, t._english = FakeModel("he"), FakeModel("en")
    t._language, t._english_threshold = "he", 0.8
    t._cleanup, t._fillers = False, ()
    t._initial_prompt = "שיחה בעברית עם commit"
    t._guards, t._boilerplate = {}, ()

    t.transcribe(b"RIFF", language="he")
    assert seen["he"] == "שיחה בעברית עם commit", seen
    t.transcribe(b"RIFF", language="en")
    assert seen["en"] is None, seen


VK_F9 = 0x78


def _tap_machine(spy, hotkey_vk=VK_RCTRL, tap_vk=VK_F9):
    return PTTStateMachine(
        {hotkey_vk: "he"},
        on_start=lambda lang: spy.events.append("start"),
        on_stop=lambda lang: spy.events.append("stop"),
        on_abort=lambda why: spy.events.append(f"abort:{why}"),
        taps={tap_vk: "translate"},
        on_tap=lambda action: spy.events.append(f"tap:{action}"))


def test_tap_key_fires_once_per_press() -> None:
    spy = Spy()
    m = _tap_machine(spy)
    m.handle("down", VK_F9, injected=False)
    m.handle("up", VK_F9, injected=False)
    assert spy.events == ["tap:translate"], spy.events


def test_tap_key_ignores_autorepeat() -> None:
    """Holding the key must translate once, not once per repeat — each
    repeat would be another paste over the previous result."""
    spy = Spy()
    m = _tap_machine(spy)
    for _ in range(5):
        m.handle("down", VK_F9, injected=False)
    m.handle("up", VK_F9, injected=False)
    m.handle("down", VK_F9, injected=False)   # a genuine second press
    assert spy.events == ["tap:translate", "tap:translate"], spy.events


def test_tap_key_mid_recording_aborts_and_does_not_translate() -> None:
    """Pressing it while dictating means the user is doing something else —
    it must not fire a translation at a half-finished recording."""
    spy = Spy()
    m = _tap_machine(spy)
    m.handle("down", VK_RCTRL, injected=False)
    m.handle("down", VK_F9, injected=False)
    assert spy.events == ["start", "abort:'f9' pressed mid-hold"], spy.events
    # ...and the key is still armed for a real press afterwards
    m.handle("up", VK_F9, injected=False)
    m.handle("up", VK_RCTRL, injected=False)
    m.handle("down", VK_F9, injected=False)
    assert spy.events[-1] == "tap:translate", spy.events


def test_tap_key_cannot_double_as_a_hotkey() -> None:
    spy = Spy()
    try:
        _tap_machine(spy, hotkey_vk=VK_F9, tap_vk=VK_F9)
    except ValueError as e:
        assert "two things" in str(e), e
    else:
        raise AssertionError("expected ValueError when one key means both")


def test_translate_hotkey_must_not_collide() -> None:
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "config.toml"
        p.write_text('hotkey = "right ctrl"\ntranslate_hotkey = "right ctrl"\n',
                     "utf-8")
        try:
            config_mod.load(p)
        except config_mod.ConfigError as e:
            assert "translate_hotkey" in str(e), e
        else:
            raise AssertionError("expected ConfigError on a colliding key")


VK_LEFT = 0x25
VK_ESC = 0x1B


def _latch_machine(spy, hotkeys=None, latch_vk=VK_LEFT):
    return PTTStateMachine(
        hotkeys or {VK_RCTRL: "he"},
        on_start=lambda lang: spy.events.append("start"),
        on_stop=lambda lang: spy.events.append("stop"),
        on_abort=lambda why: spy.events.append(f"abort:{why}"),
        latch_vk=latch_vk,
        on_latch=lambda: spy.events.append("latch"))


def test_latch_locks_the_recording_and_survives_the_release() -> None:
    spy = Spy()
    m = _latch_machine(spy)
    m.handle("down", VK_RCTRL, injected=False)
    m.handle("down", VK_LEFT, injected=False)    # tapped mid-hold
    m.handle("up", VK_LEFT, injected=False)
    m.handle("up", VK_RCTRL, injected=False)     # let go — keeps recording
    assert spy.events == ["start", "latch"], spy.events
    m.handle("down", VK_LEFT, injected=False)    # tapped again -> transcribe
    assert spy.events == ["start", "latch", "stop"], spy.events


def test_latch_survives_hotkey_autorepeat() -> None:
    """The hotkey is still physically down at the moment of latching, and
    Windows keeps repeating its key-down. Treating those as a fresh press
    would end the recording a few milliseconds after locking it."""
    spy = Spy()
    m = _latch_machine(spy)
    m.handle("down", VK_RCTRL, injected=False)
    m.handle("down", VK_LEFT, injected=False)
    for _ in range(6):                            # still holding right ctrl
        m.handle("down", VK_RCTRL, injected=False)
    m.handle("up", VK_RCTRL, injected=False)
    assert spy.events == ["start", "latch"], spy.events


def test_latch_key_autorepeat_does_not_stop_the_recording() -> None:
    """Same hazard for the latch key itself if it is held rather than
    tapped: repeat #2 would immediately un-latch."""
    spy = Spy()
    m = _latch_machine(spy)
    m.handle("down", VK_RCTRL, injected=False)
    for _ in range(5):
        m.handle("down", VK_LEFT, injected=False)
    assert spy.events == ["start", "latch"], spy.events


def test_latch_key_is_swallowed_only_while_it_latches() -> None:
    """It is an arrow: idle it must still move the caret, because that is
    where the transcript is about to land."""
    spy = Spy()
    m = _latch_machine(spy)
    assert m.handle("down", VK_LEFT, injected=False) is False
    assert m.handle("up", VK_LEFT, injected=False) is False
    m.handle("down", VK_RCTRL, injected=False)
    assert m.handle("down", VK_LEFT, injected=False) is True   # latches
    assert m.handle("down", VK_LEFT, injected=False) is True   # auto-repeat
    assert m.handle("up", VK_LEFT, injected=False) is True     # its own up
    m.handle("up", VK_RCTRL, injected=False)
    assert m.handle("down", VK_LEFT, injected=False) is True   # un-latches
    assert m.handle("up", VK_LEFT, injected=False) is True


def test_stray_keys_do_not_abort_a_latched_recording() -> None:
    """Latched, the user's hands are free by design — the abort rule that
    protects a HELD recording would now throw away minutes of speech."""
    spy = Spy()
    m = _latch_machine(spy)
    m.handle("down", VK_RCTRL, injected=False)
    m.handle("down", VK_LEFT, injected=False)
    m.handle("up", VK_LEFT, injected=False)
    m.handle("up", VK_RCTRL, injected=False)
    for vk in (VK_C, VK_SHIFT, VK_LCTRL, VK_V):
        m.handle("down", vk, injected=False)
        m.handle("up", vk, injected=False)
    assert spy.events == ["start", "latch"], spy.events
    m.handle("down", VK_LEFT, injected=False)
    assert spy.events[-1] == "stop", spy.events


def test_esc_discards_a_latched_recording() -> None:
    spy = Spy()
    m = _latch_machine(spy)
    m.handle("down", VK_RCTRL, injected=False)
    m.handle("down", VK_LEFT, injected=False)
    m.handle("up", VK_RCTRL, injected=False)
    m.handle("down", VK_ESC, injected=False)
    assert spy.events == ["start", "latch", "abort:esc pressed while locked"], \
        spy.events
    m.handle("down", VK_LEFT, injected=False)   # back to idle: no stray stop
    assert len(spy.events) == 3, spy.events


def test_tapping_the_hotkey_again_finishes_a_latched_recording() -> None:
    spy = Spy()
    m = _latch_machine(spy)
    m.handle("down", VK_RCTRL, injected=False)
    m.handle("down", VK_LEFT, injected=False)
    m.handle("up", VK_LEFT, injected=False)
    m.handle("up", VK_RCTRL, injected=False)
    m.handle("down", VK_RCTRL, injected=False)
    assert spy.events == ["start", "latch", "stop"], spy.events


def test_latch_key_already_held_does_not_latch() -> None:
    """Holding left-arrow to move the caret and then reaching for the
    hotkey is not a latch — and their arrows must keep working."""
    spy = Spy()
    m = _latch_machine(spy)
    m.handle("down", VK_LEFT, injected=False)          # held from before
    m.handle("down", VK_RCTRL, injected=False)
    assert m.handle("down", VK_LEFT, injected=False) is False   # repeat
    m.handle("up", VK_RCTRL, injected=False)
    assert spy.events == ["start", "stop"], spy.events


def test_latch_key_cannot_double_as_a_hotkey() -> None:
    spy = Spy()
    try:
        _latch_machine(spy, latch_vk=VK_RCTRL)
    except ValueError as e:
        assert "two things" in str(e), e
    else:
        raise AssertionError("expected ValueError when one key means both")


def test_latch_hotkey_must_not_collide_in_config() -> None:
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "config.toml"
        p.write_text('hotkey = "right ctrl"\nlatch_hotkey = "right ctrl"\n',
                     "utf-8")
        try:
            config_mod.load(p)
        except config_mod.ConfigError as e:
            assert "latch_hotkey" in str(e), e
        else:
            raise AssertionError("expected ConfigError on a colliding key")


def _bare_recorder(max_seconds: float, on_overflow):
    """A Recorder without PortAudio — the buffering logic is what is under
    test, and opening a real input stream needs a device."""
    import threading

    from recorder import IDLE as R_IDLE
    from recorder import Recorder

    r = Recorder.__new__(Recorder)
    r._on_overflow = on_overflow
    r._lock = threading.Lock()
    r._state = R_IDLE
    r._chunks, r._samples = [], 0
    r.sample_rate = 16000
    r._default_max_samples = float(max_seconds * r.sample_rate)
    r._max_samples = r._default_max_samples
    return r


def test_latched_recording_is_not_capped_and_the_cap_comes_back() -> None:
    """The whole point of the latch: max_seconds guards against a key-up
    the OS swallowed, and a latched recording has no key-up to lose."""
    fired: list[str] = []
    r = _bare_recorder(2.0, lambda: fired.append("overflow"))
    one_second = np.zeros(16000, dtype=np.int16)

    r.begin()
    r.set_cap(None)                       # what _on_latch does
    for _ in range(10):                   # 10 s, five times the held cap
        r._callback(one_second, len(one_second), None, None)
    assert fired == [], fired
    wav, seconds = r.end()
    assert wav is not None and abs(seconds - 10.0) < 0.01, seconds

    r.begin()                             # next recording is capped again
    for _ in range(3):
        r._callback(one_second, len(one_second), None, None)
    assert fired == ["overflow"], fired
    assert r.end()[0] is None, "an overflowed recording must be discarded"


def test_real_config_has_a_reachable_latch_key() -> None:
    """Guards the shipped config: without this the app is back to "a long
    dictation means a long hold"."""
    cfg = config_mod.load(Path(__file__).resolve().parent / "config.toml")
    assert cfg.latch_hotkey, "latch_hotkey is off"
    vk_for(cfg.latch_hotkey)              # must be a name the hook knows
    assert cfg.latch_hotkey != cfg.hotkey
    assert cfg.latch_max_seconds == 0, "0 = no cap, which is the point"


def test_the_real_hallucinated_tail_is_dropped() -> None:
    """Verbatim from transcripts.log, 2026-08-12 19:01. The last five words
    were never spoken — the fine-tune was trained on Knesset protocols and
    the decoder ran past the end of the speech."""
    import cleanup as cleanup_mod
    observed = ("סבבה, אני מבין מה אתה אומר. שתי שאלות. יש איזה מיליון "
                "ערים בכל העולם, אז איך נעשה את זה? "
                "אדוני היושב-ראש, חברי הכנסת")
    out, removed = cleanup_mod.strip_trailing_boilerplate(observed)
    assert out.endswith("אז איך נעשה את זה?"), out
    assert removed == ["אדוני היושב-ראש", "חברי הכנסת"], removed


def test_boilerplate_in_the_middle_is_left_alone() -> None:
    """If it is not at the end, the user really said it — stripping real
    speech is a worse bug than the one being fixed."""
    import cleanup as cleanup_mod
    text = "אמרתי לחברי הכנסת שזה לא הגיוני ואז הלכתי הביתה"
    out, removed = cleanup_mod.strip_trailing_boilerplate(text)
    assert out == text and removed == [], (out, removed)


def test_boilerplate_matching_ignores_punctuation_and_quotes() -> None:
    import cleanup as cleanup_mod
    for tail in ("אדוני היושב-ראש", "אדוני היושב ראש", 'אדוני היו"ר'):
        out, removed = cleanup_mod.strip_trailing_boilerplate(
            f"בוא נוסיף את כל הערים. {tail}")
        assert out == "בוא נוסיף את כל הערים.", (tail, out)
        assert removed, tail


def test_longest_boilerplate_phrase_wins() -> None:
    import cleanup as cleanup_mod
    out, removed = cleanup_mod.strip_trailing_boilerplate(
        "זה מה שרציתי. תודה רבה אדוני היושב ראש")
    assert out == "זה מה שרציתי.", out
    assert removed == ["תודה רבה אדוני היושב ראש"], removed


def test_ordinary_speech_survives_the_boilerplate_filter() -> None:
    """The filter must be inert on everything that is not the bug."""
    import cleanup as cleanup_mod
    for text in ("תודה רבה על העזרה",
                 "אני חושב שצריך לשנות את הפיצר הזה",
                 "בוא נוסיף את כל הערים בעולם",
                 "commit the branch and deploy it"):
        out, removed = cleanup_mod.strip_trailing_boilerplate(text)
        assert out == text and removed == [], (text, out, removed)


def test_boilerplate_filter_is_not_fooled_by_a_partial_phrase() -> None:
    import cleanup as cleanup_mod
    text = "הלכתי לכנסת"        # not "חברי הכנסת"
    out, removed = cleanup_mod.strip_trailing_boilerplate(text)
    assert out == text and removed == [], (out, removed)


def test_local_backend_gets_the_guards_and_boilerplate_from_config() -> None:
    """Both construction sites (primary backend and quota fallback) go
    through one helper, so they cannot drift apart."""
    import cleanup as cleanup_mod
    from transcribers import local_kwargs
    cfg = config_mod.load(Path(__file__).resolve().parent / "config.toml")
    kw = local_kwargs(cfg)
    assert kw["guard_hallucinations"] is True
    assert "אדוני היושב ראש" in kw["boilerplate"]
    assert kw["language"] == "he" and kw["initial_prompt"]
    # every shipped phrase must be multi-word: one common word would eat
    # real speech
    for phrase in cleanup_mod.PARLIAMENTARY_BOILERPLATE:
        assert len(phrase.split()) >= 2, phrase


def test_boilerplate_can_be_turned_off() -> None:
    import tempfile
    from transcribers import local_kwargs
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "config.toml"
        p.write_text("backend = 'local'\n[local]\n"
                     "drop_trailing_boilerplate = false\n", "utf-8")
        assert local_kwargs(config_mod.load(p))["boilerplate"] == ()


def test_phone_endpoint_round_trip_and_auth() -> None:
    """The endpoint is reachable from a phone, so the auth boundary is the
    part that matters most: a wrong token must never reach the GPU."""
    import dataclasses
    import wave as wave_mod

    import requests

    import server as server_mod

    cfg = config_mod.load(Path(__file__).resolve().parent / "config.toml")
    cfg = dataclasses.replace(
        cfg, server=config_mod.ServerConfig(enabled=True, host="127.0.0.1",
                                            port=8799))
    calls: list[int] = []

    def fake(wav):
        calls.append(len(wav))
        return "שלום", "fake"

    buf = io.BytesIO()
    with wave_mod.open(buf, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)
        w.writeframes(np.zeros(16000, dtype=np.int16).tobytes())
    clip = buf.getvalue()

    srv = server_mod.PhoneServer(cfg, fake, lambda: "fake")
    srv.start()
    base = "http://127.0.0.1:8799"
    try:
        token = server_mod.load_token()
        bad = requests.post(f"{base}/transcribe", data=clip, timeout=10,
                            headers={"Authorization": "Bearer nope"})
        assert bad.status_code == 401, bad.status_code
        assert not calls, "an unauthorised request reached the transcriber"

        none = requests.post(f"{base}/transcribe", data=clip, timeout=10)
        assert none.status_code == 401, none.status_code

        ok = requests.post(f"{base}/transcribe", data=clip, timeout=30,
                           headers={"Authorization": f"Bearer {token}"})
        assert ok.status_code == 200, ok.status_code
        assert ok.json()["text"] == "שלום", ok.json()
        assert calls, "the transcriber was never called"

        junk = requests.post(f"{base}/transcribe", data=b"xxxx", timeout=10,
                             headers={"Authorization": f"Bearer {token}"})
        assert junk.status_code == 400, junk.status_code
        assert requests.get(f"{base}/nope", timeout=5).status_code == 404
    finally:
        srv.stop()


def test_splash_shuts_down_without_aborting_the_process() -> None:
    """Tk interpreters must be torn down on the thread that created them.
    Left to the GC, the after() callbacks keep root alive in a cycle that
    is collected on some other thread, and freeing Tcl from there aborts
    the process — a clean shutdown was exiting with code 3. Only visible
    at interpreter exit, so this has to be a subprocess."""
    import subprocess
    here = Path(__file__).resolve().parent
    script = (
        "import time, splash;"
        "s = splash.Splash(); s.start();"
        "s.status('loading…'); time.sleep(.3);"
        "s.finish('ready', linger_ms=60); time.sleep(.9);"
        "print('ok')"
    )
    out = subprocess.run([sys.executable, "-c", script], cwd=str(here),
                         capture_output=True, encoding="utf-8",
                         errors="replace", timeout=90)
    assert out.returncode == 0, (out.returncode, out.stdout, out.stderr)
    assert "Tcl_AsyncDelete" not in (out.stderr or ""), out.stderr


def test_splash_off_is_inert_and_nothing_ever_raises() -> None:
    """It is decoration. On a machine with no display, no Tk, or a hostile
    window manager it must degrade to nothing, not take dictation down."""
    import splash as splash_mod
    off = splash_mod.Splash.off()
    off.start(); off.status("x"); off.finish("y")
    assert off._thread is None, "off() started a thread"
    never_started = splash_mod.Splash()
    never_started.status("x"); never_started.finish()   # must not raise


def test_splash_log_forwards_app_messages_and_trims_long_ones() -> None:
    """The phone URL carries a token long enough to reflow the window."""
    import logging

    import main as main_mod

    seen: list[str] = []

    class Fake:
        def status(self, text): seen.append(text)

    handler = main_mod.SplashLog(Fake())
    logger = logging.getLogger("splash-test")
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    try:
        logger.info("local model %s ready on %s", "ivrit", "cuda")
        logger.debug("noise that must not appear")
        logger.info("x" * 400)
    finally:
        logger.removeHandler(handler)
    assert seen[0] == "local model ivrit ready on cuda", seen
    assert len(seen) == 2, seen
    assert len(seen[1]) <= 110 and seen[1].endswith("…"), len(seen[1])


def test_subprocess_output_survives_a_hebrew_locale() -> None:
    """This machine's locale code page is cp1255. subprocess(text=True)
    decodes with it, so a tool emitting UTF-8 raises UnicodeDecodeError in
    the reader thread and returns stdout=None — and because that is a
    ValueError, a broad except reports the tool as absent. Exactly how the
    app came to log "tailscale is not up" while Tailscale was up."""
    import json as json_mod

    import server as server_mod

    # “ is 0x9c in cp1255's undefined range — the real byte that broke it
    payload = {"Self": {"DNSName": "yoav.example.ts.net."},
               "note": "עברית “quoted”"}
    script = ("import sys,io;"
              "sys.stdout=io.TextIOWrapper(sys.stdout.buffer,encoding='utf-8');"
              f"print({json_mod.dumps(json_mod.dumps(payload))})")
    out = server_mod.run_utf8([sys.executable, "-c", script])
    assert out is not None, "utf-8 stdout came back as None"
    assert json_mod.loads(out)["Self"]["DNSName"] == "yoav.example.ts.net."
    assert server_mod.run_utf8(["definitely-not-a-real-binary-xyz"]) is None


def test_phone_token_is_generated_once_and_reused() -> None:
    """It travels in a URL the user bookmarks — regenerating it on every
    start would silently break the phone."""
    import server as server_mod
    first = server_mod.load_token()
    assert len(first) >= 20, first
    assert server_mod.load_token() == first


def test_phone_audio_decode_accepts_a_plain_wav() -> None:
    import wave as wave_mod

    import server as server_mod
    buf = io.BytesIO()
    with wave_mod.open(buf, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)
        w.writeframes(np.zeros(32000, dtype=np.int16).tobytes())
    wav, seconds = server_mod.to_wav(buf.getvalue())
    assert abs(seconds - 2.0) < 0.05, seconds
    with wave_mod.open(io.BytesIO(wav)) as w:
        assert w.getframerate() == 16000 and w.getnchannels() == 1


def test_phone_endpoint_never_binds_anything_but_loopback() -> None:
    """`tailscale serve` proxies to localhost and terminates TLS. Binding
    anywhere else both hides the server from it and puts a socket where the
    home LAN can reach it."""
    import server as server_mod
    assert config_mod.ServerConfig.enabled is False   # opt in, not out
    assert config_mod.ServerConfig.host == ""
    cfg = config_mod.load(Path(__file__).resolve().parent / "config.toml")
    assert cfg.server.host in ("", "127.0.0.1", "localhost"), cfg.server.host
    # the resolution the server actually performs
    assert (cfg.server.host.strip() or "127.0.0.1") == "127.0.0.1"
    # a name lookup must never influence what gets bound
    assert "tailscale_ip" not in dir(server_mod)


def test_needs_translation_skips_text_with_no_hebrew() -> None:
    """Every skipped call is one saved from a 20-per-day bucket."""
    import translate as translate_mod
    assert translate_mod.needs_translation("שלום עולם") is True
    assert translate_mod.needs_translation("git commit -m 'x'") is False
    assert translate_mod.needs_translation("   ") is False
    assert translate_mod.needs_translation("mixed עברית here") is True
    # a non-English target cannot be decided by script alone
    assert translate_mod.needs_translation("hello", "French") is True


def test_translation_output_is_unwrapped() -> None:
    """Small models wrap output despite being told not to; a stray quote
    would be pasted into the user's message."""
    import translate as translate_mod
    assert translate_mod._clean('"Hello there"') == "Hello there"
    assert translate_mod._clean("```\nHello\n```") == "Hello"
    # a quote INSIDE the sentence is content, not a wrapper
    assert translate_mod._clean('He said "hi" to me') == 'He said "hi" to me'


def test_translator_falls_back_to_ollama_when_quota_is_spent() -> None:
    """The whole point of the fallback: a spent daily cap must not make the
    translate key dead until midnight."""
    import translate as translate_mod
    from transcribers.base import RateLimitError

    t = translate_mod.Translator.__new__(translate_mod.Translator)
    t._cfg = None

    class Spent:
        name = "gemini"

        def translate(self, text):
            raise RateLimitError("all models spent", per_day=True)

    class Local:
        name = "ollama"

        def translate(self, text):
            return "translated locally"

    t._cloud, t._local = Spent(), Local()
    t._cloud_backend = lambda: t._cloud
    t._local_backend = lambda: t._local
    assert t.translate("שלום") == ("translated locally", "ollama")


def test_translator_falls_back_on_a_plain_api_error_too() -> None:
    """Observed live: a 499 timeout arrives as a bare TranscriptionError,
    not a RateLimitError. Catching only the quota case left the press
    dead when the local model could have answered."""
    import translate as translate_mod
    from transcribers.base import TranscriptionError

    t = translate_mod.Translator.__new__(translate_mod.Translator)
    t._cfg = None

    class Broken:
        name = "gemini"

        def translate(self, text):
            raise TranscriptionError("Gemini API error 499 on x")

    class Local:
        name = "ollama"

        def translate(self, text):
            return "local answer"

    t._cloud_backend = lambda: Broken()
    t._local_backend = lambda: Local()
    assert t.translate("שלום") == ("local answer", "ollama")


def test_translate_settings_are_present_in_the_real_config() -> None:
    """Guards the shipped config: the fallback timeout must stay well above
    the cloud one or the first local translation times out mid-load."""
    cfg = config_mod.load(Path(__file__).resolve().parent / "config.toml")
    assert cfg.translate_hotkey, "the translate key is not enabled"
    assert cfg.translate_hotkey not in (cfg.hotkey, cfg.english_hotkey)
    assert cfg.translate.ollama_timeout_s >= 120, cfg.translate.ollama_timeout_s
    assert cfg.translate.max_chars > 0


def test_local_backend_is_configured_and_unlimited() -> None:
    """Guards the switch to the local backend: it is the only one without a
    daily cap, so a silent revert to gemini would reintroduce the wall."""
    cfg = config_mod.load(Path(__file__).resolve().parent / "config.toml")
    assert cfg.backend == "local", cfg.backend
    assert cfg.local.language == "he", "autodetect is broken in this fine-tune"
    assert cfg.local.device in ("auto", "cuda", "cpu")
    assert cfg.local.cleanup is True


def test_real_config_has_a_multi_model_runway() -> None:
    """Guards the actual shipped config: a single model means the daily cap
    stops dictation dead, which is the bug users feel."""
    cfg = config_mod.load(Path(__file__).resolve().parent / "config.toml")
    assert len(cfg.gemini.models) >= 2, cfg.gemini.models
    assert cfg.feedback.enabled and cfg.feedback.placeholder
    assert cfg.fallback_to_local is True


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items())
             if n.startswith("test_") and callable(f)]
    print(f"running {len(tests)} tests")
    for test_name, fn in tests:
        check(test_name, fn)
    if FAILURES:
        print(f"\n{len(FAILURES)} FAILED: {', '.join(FAILURES)}")
        sys.exit(1)
    print("\nall tests passed")
