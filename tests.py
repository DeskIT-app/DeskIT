"""Unit tests — run with:  .venv\\Scripts\\python.exe tests.py

Plain asserts, no pytest. Covers the state machine's abort paths, key-name
tables, WAV building, config parsing, the fake backend, and a real
clipboard round-trip (saves and restores whatever is on it).
"""
from __future__ import annotations

import io
import sys
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
