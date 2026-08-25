"""Unit tests — run with:  .venv\\Scripts\\python.exe tests.py

Plain asserts, no pytest. Covers the state machine's abort paths, key-name
tables, WAV building, config parsing, the fake backend, and a real
clipboard round-trip (saves and restores whatever is on it).
"""
from __future__ import annotations

import contextlib
import dataclasses
import gc
import io
import queue
import sys
import tempfile
import threading
import time
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

import apikey
import config as config_mod
import injector
import singleton
import vocab as vocab_mod
import hotkey as hotkey_mod
from hotkey import (PTTStateMachine, parse_binding, parse_chord,
                    vk_for, vk_name)
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
        os_key = apikey._from_env_file(apikey._GEMINI_NAMES)
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
                         ("Stop Dictation.vbs", "--stop"),
                         ("Dashboard.vbs", "dashboard.py")):
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


def test_a_copy_the_user_took_is_not_restored_over() -> None:
    """A restore may not undo a copy the user made in the middle of it.

    Both text keys hold a save-and-restore pair open for as long as their
    model takes to answer, the lookup key holds one across its capture,
    and the lookup box — which has a copy button on it — is on screen and
    readable through all of them. Measured 2026-08-20 before this: a copy
    taken from the box during a translation was destroyed 5/5 by the
    restore at the end of it, and 5/5 by the sweep inside read_selection.
    The button said "copied" and the clipboard held something else.

    So set_text() claims the clipboard and every restore stands down
    against the mark it took at snapshot time — injector.claim_mark().
    The other half matters just as much and is asserted here too: with
    nobody copying, the user's own content still comes back, or this
    guard has quietly turned every restore off.

    Both doors are called directly and no keys are sent. That is also the
    only way to reach the sweep inside read_selection without a real copy
    chord going into whatever window happens to be in front.
    """
    before = injector.snapshot()
    if before[0] == "other":
        print("        (clipboard holds non-text content — skipping so "
              "it isn't lost)")
        return
    mine, copied = "what the user had", "מה שהתיבה העתיקה"
    try:
        # 1. restore() — the pair the translate, punctuate and correct
        #    keys hold open around their model.
        injector.set_text(mine)
        state, mark = injector.snapshot(), injector.claim_mark()
        injector.set_text(copied)             # the box's copy button
        injector.restore(state, "translation", since=mark)
        assert injector.get_text() == copied, "the copy was restored over"

        injector.set_text(mine)
        state, mark = injector.snapshot(), injector.claim_mark()
        injector._put_text("on its way to a paste chord")
        injector.restore(state, "translation", since=mark)
        assert injector.get_text() == mine, "the user's clipboard was lost"

        # 2. the sweep inside read_selection, which cannot simply believe
        #    the sequence number: a copy taken from the box moves it
        #    exactly as a straggling app's late copy does.
        injector.set_text(mine)
        saved, mark = injector.snapshot_all(), injector.claim_mark()
        seq0 = injector.clipboard_sequence()
        injector.set_text(copied)
        assert injector._restore_if_touched(saved, seq0, 200, mark), \
            "a stand-down was reported as a lost clipboard"
        assert injector.get_text() == copied, "the sweep restored over it"

        injector.set_text(mine)
        saved, mark = injector.snapshot_all(), injector.claim_mark()
        seq0 = injector.clipboard_sequence()
        injector._put_text("what the app copied out of the window")
        assert injector._restore_if_touched(saved, seq0, 200, mark)
        assert injector.get_text() == mine, "the user's clipboard was lost"
    finally:
        if before[0] == "text":
            injector.set_text(before[1] or "")


def test_a_copy_taken_off_the_box_is_not_read_back_as_the_selection()\
        -> None:
    """The box quoting itself, and the two keys that would paste it.

    read_selection watches the clipboard sequence number and takes the
    first move as the answer to the copy chord it just sent. But a box
    from an EARLIER press is still on screen while this one runs, and its
    copy button moves that same number. The claim already existed and the
    restore already consulted it; the wait loop did not, so the app read
    its own answer back as if the user had selected it.

    Harmless-looking for the lookup key — a box quoting itself — and not
    harmless at all for translate and punctuate, which PASTE what they
    read over whatever was selected. Measured 2026-08-20: with the guard
    removed, 1 of 1 immediately; with it, 3 of 3 clean.
    """
    import injector as injector_mod

    box_text = "שביר - נוטה להישבר בקלות"
    injector_mod.set_text("what the user had before")

    def copy_lands_late(_chord):
        # The focused app is slow, the way a browser is; the user presses
        # the box's copy button while this call is still waiting.
        time.sleep(0.05)
        injector_mod.set_text(box_text)

    with _patched(injector_mod, "send_chord", copy_lands_late):
        text, reason = injector_mod.read_selection(
            "ctrl+c", timeout_ms=300, late_sweep_ms=0, skip_consoles=False)

    assert text == "", f"the box's own copy was read as a selection: {text!r}"
    assert reason == "nothing-selected", reason
    # And the copy the user actually took is still theirs.
    assert injector_mod.get_text() == box_text, injector_mod.get_text()


def test_the_claim_is_visible_before_the_copy_is() -> None:
    """The claim must land BEFORE the clipboard sequence moves, not after.

    The test above copies and restores one after the other, so the claim
    has always landed by the time the restore looks — which is the one
    arrangement that cannot fail. In the app they overlap: the restore is
    a loop polling the sequence number every 20 ms while the box's copy
    button runs on a thread of its own.

    So the copy goes on another thread here and the decision is taken
    where _restore_if_touched takes it — at the instant the sequence is
    first seen to move. A claim that is not visible YET reads as
    "somebody else wrote this, put the user's content back", and the copy
    is destroyed with the button still saying "copied".

    The gap is nothing like as narrow as it looks: the sequence moves at
    _put_text's EmptyClipboard and the claim cannot follow until its
    CloseClipboard has returned, so it is the whole clipboard write wide
    — measured 2026-08-20 over 200 writes, median 30.7 ms and worst
    46.8 ms, against that 20 ms poll. Claiming after writing lost this
    298 times out of 300; claiming first, 0.
    """
    before = injector.snapshot()
    if before[0] == "other":
        print("        (clipboard holds non-text content — skipping so "
              "it isn't lost)")
        return
    try:
        for attempt in range(5):
            mark = injector.claim_mark()
            seq0 = injector.clipboard_sequence()
            go = threading.Event()
            copier = threading.Thread(
                target=lambda: (go.wait(),
                                injector.set_text("off the box")),
                daemon=True)
            copier.start()
            go.set()
            claimed = None
            deadline = time.perf_counter() + 3
            while time.perf_counter() < deadline:
                if injector.clipboard_sequence() != seq0:
                    claimed = injector._claimed_since(mark)
                    break
            copier.join(timeout=3)
            assert claimed is not None, "the copy never reached the clipboard"
            assert claimed, (
                "the clipboard moved before the copy was claimed: a "
                "restore polling here would put the user's old content "
                f"back over it (attempt {attempt + 1})")
    finally:
        if before[0] == "text":
            injector.set_text(before[1] or "")


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
        self.claims = 0
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

    def paste_text(self, text, chord, delay):
        # The text keys' paste: no save/restore of its own, because they
        # snapshot the clipboard once around the whole grab-and-replace.
        self.calls.append(("paste", text))

    def set_text(self, text):
        # A copy made FOR the user, and the real one claims the clipboard
        # so that a restore in flight around it stands down rather than
        # putting the old contents back over it (injector.claim_mark()).
        # Counted here so a test can assert the pair the same way.
        self.claims += 1
        self.calls.append(("clipboard", text))

    def claim_mark(self):
        return self.claims

    # -- what the correction key reads off the screen --
    on_screen = ""
    has_selection = False

    def snapshot(self):
        return ("text", "whatever the user had")

    def restore(self, state, what="transcript", *, since=None):
        if since is not None and since != self.claims:
            self.calls.append(("kept", "a copy was taken meanwhile"))
            return "a copy was taken meanwhile; clipboard left as it is"
        self.calls.append(("restore", state[1]))
        return "old clipboard restored"

    def grab(self, copy_chord, select_all_chord, settle_s):
        self.calls.append(("grab", self.on_screen))
        return self.on_screen, self.has_selection

    # -- what the lookup key reads, and gives straight back --
    selection = ""
    selection_reason = "ok"
    on_read = None            # a hook for tests that watch the cursor lock

    def read_selection(self, copy_chord, *, skip_consoles=True, hwnd=0,
                       **_kw):
        # The restore is appended from a finally because the real one is
        # done in a finally — anything raising between the copy and the
        # restore leaves the user's clipboard holding the text that was
        # captured (measured destroyed 3/3 without it). Recording the pair
        # here is what makes "did this exit path give the clipboard back"
        # a question the tests below can ask on every path.
        self.calls.append(("read", self.selection))
        try:
            if self.on_read is not None:
                self.on_read()
            return self.selection, self.selection_reason
        finally:
            self.calls.append(("restore", "whatever the user had"))

    def window_class(self, hwnd):
        return "Notepad"


@contextlib.contextmanager
def _patched(module, name, replacement):
    """Swap a module attribute for the body of a `with`, and put it back
    however the body ends. The worker tests have always done this by hand;
    the deferred-repair tests need it on every path, including the ones that
    raise inside a background thread."""
    real = getattr(module, name)
    setattr(module, name, replacement)
    try:
        yield replacement
    finally:
        setattr(module, name, real)


class _SpyPopup:
    """The lookup box with the window taken out.

    It records the direction as well as the text, because the direction is
    the one thing about this box that a unit test can pin at all: whether
    the glyphs come out in the right order was answered by photographing
    it, but WHICH way it was asked to lay them out is a decision in
    main.py, and a Hebrew answer laid out left-to-right reads inside out —
    subject and object swapped, the full stop on the wrong end.

    It records the anchor and the dwell for the same reason. WHERE the box
    is drawn is popup.py's arithmetic and is proved there; which anchor it
    was handed, and that the dwell it was handed is 0, are main.py's two
    decisions and this is the only place they can be asserted.

    And it records the term, which is the third of them. The box is handed
    an answer and never sees the question, so what its title bar says
    about the word that was looked up is entirely main.py's to pass.
    """

    def __init__(self) -> None:
        self.shown: list[tuple[str, bool]] = []
        self.anchors: list = []
        self.dwells: list[int] = []
        self.terms: list[str] = []
        self.updates: list[str] = []
        self.hidden = 0
        self._visible = False

    def show(self, text, *, rtl, dwell_ms=0, anchor=None, term=""):
        self.shown.append((text, bool(rtl)))
        self.anchors.append(anchor)
        self.dwells.append(int(dwell_ms))
        self.terms.append(term)
        self._visible = True

    def update(self, text):
        self.updates.append(text)
        self._visible = True

    def hide(self):
        self.hidden += 1
        self._visible = False

    def visible(self):
        return self._visible

    def on_key(self, vk):
        return False

    def stop(self):
        pass

    @property
    def last(self):
        """What would be standing on screen now, as (text, rtl): show()
        puts the ellipsis up before the model is asked and update()
        replaces it with the answer."""
        if not self.shown:
            return None
        body = self.updates[-1] if self.updates else self.shown[-1][0]
        return body, self.shown[-1][1]


def _worker_app(backend, spool_dir, retry_seconds=5.0):
    import dataclasses

    import main as main_mod
    from spool import Spool

    cfg = config_mod.load(Path(__file__).resolve().parent / "config.toml")
    cfg = dataclasses.replace(
        cfg,
        feedback=config_mod.FeedbackConfig(placeholder="...", enabled=True,
                                           retry_seconds=retry_seconds),
        # The shipped config runs the context pass on every dictation. A
        # worker test that is not ABOUT that pass must opt out of it, or it
        # spawns a background thread that reaches for a real Ollama and
        # then lands its answer in whatever test happens to be running when
        # it comes back. _polished_app turns it on deliberately.
        polish=config_mod.PolishConfig(when="never"),
        fallback_to_local=False)
    app = main_mod.App.__new__(main_mod.App)
    app.cfg, app.transcriber, app._local = cfg, backend, False
    app.spool = Spool(Path(spool_dir))
    # Everything below is built by the real App.__init__; this helper has to
    # mirror it or the worker path under test dies on a missing attribute.
    app._model_lock = threading.Lock()
    app.recent = None                    # no audio ring in the worker tests
    app.vocab = vocab_mod.Vocab(Path(spool_dir) / "vocab.json")
    app._hotwords = app.vocab.hotwords
    app._polisher = None
    # The two keys that act on text already on screen. One queue and one
    # busy flag between them, because they take turns at the clipboard.
    app._translator = app._punctuator = None
    app.text_queue = queue.Queue()
    app._text_busy = threading.Event()
    app._last, app._last_lock = None, threading.Lock()
    app._note, app._activity = "", "ready"
    app._stats_lock, app._stats = threading.Lock(), main_mod.App._fresh_stats()
    app._cue_lock, app._cue_last = threading.Lock(), {}
    # The cursor is shared with the deferred context pass, the text keys,
    # the correction key and the lookup key, so one lock stands between
    # all of them. (This helper also set app._generation for a month after
    # main.py stopped having one — a fixture describing a program that no
    # longer exists teaches the next reader something untrue.)
    app._cursor_lock = threading.Lock()
    app._correcting = threading.Event()
    # The lookup key gets its own queue and its own busy flag rather than
    # joining the text keys' turn-taking: it borrows the clipboard for a
    # measured 20 ms and gives it straight back, so queueing a paste
    # behind its 1-3 s model call would be seconds of nothing for nothing.
    app.lookup_queue = queue.Queue()
    app._looking_up = threading.Event()
    app._lookup_engine = None
    app._lookup_vk = vk_for("f6")
    app.popup = _SpyPopup()
    # The repair refuses to touch the cursor mid-recording (an injected
    # Shift+Left while Right Ctrl is held arrives as Ctrl+Shift+Left).
    class _Idle:
        state = hotkey_mod.IDLE
    app.machine = _Idle()
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
    t._hotwords = None       # real __init__ sets this; see local_whisper.py

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


def test_the_hold_key_declares_no_language_by_default() -> None:
    """auto_language: the hold key stops meaning "Hebrew" and starts meaning
    "whatever I just said". None is how "nothing was declared" travels — the
    transcribers already read an unset language that way."""
    import dataclasses

    import main as main_mod

    cfg = config_mod.load(Path(__file__).resolve().parent / "config.toml")
    assert cfg.auto_language, "the shipped config.toml must ship it on"
    cfg = dataclasses.replace(cfg, hotkey="right ctrl", english_hotkey="")

    hotkeys, _taps, _latch, _pause = main_mod.App.bindings(cfg)
    assert hotkeys == {VK_RCTRL: None}, hotkeys

    pinned = dataclasses.replace(cfg, auto_language=False)
    hotkeys, _taps, _latch, _pause = main_mod.App.bindings(pinned)
    assert hotkeys == {VK_RCTRL: "he"}, hotkeys

    # A dedicated English key still declares itself, either way.
    both = dataclasses.replace(cfg, english_hotkey="f7")
    hotkeys, _taps, _latch, _pause = main_mod.App.bindings(both)
    assert hotkeys[vk_for("f7")] == "en", hotkeys


def test_auto_language_round_trips_through_config() -> None:
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "config.toml"
        base = 'hotkey = "right ctrl"\nenglish_hotkey = ""\n'
        p.write_text(base, "utf-8")
        assert config_mod.load(p).auto_language is True     # the default
        p.write_text(base + 'auto_language = false\n', "utf-8")
        assert config_mod.load(p).auto_language is False


def test_an_undeclared_language_asks_the_detector() -> None:
    """The other half of test_explicit_language_beats_detection. With the
    hold key declaring nothing, the detector is what stands between a
    English utterance and being transliterated into Hebrew letters."""
    from transcribers.local_whisper import LocalWhisperTranscriber

    calls = {}

    class FakeModel:
        def __init__(self, tag):
            self.tag = tag

        def transcribe(self, audio, **kw):
            calls["model"] = self.tag
            calls["language"] = kw.get("language")

            class Seg:
                text = "Mac mini"
            return [Seg()], None

    class Detector(FakeModel):
        def __init__(self, lang, prob):
            super().__init__("en")
            self.verdict = (lang, prob, [])

        def detect_language(self, audio=None, vad_filter=False):
            calls["detected"] = True
            return self.verdict

    def router(lang, prob):
        calls.clear()
        t = LocalWhisperTranscriber.__new__(LocalWhisperTranscriber)
        t._model, t._english = FakeModel("he"), Detector(lang, prob)
        t._language, t._english_threshold = "he", 0.8
        t._cleanup, t._fillers = False, ()
        t._initial_prompt = "עברית"
        t._guards, t._boilerplate = {}, ()
        t._hotwords = None
        wav = frames_to_wav([np.zeros(1600, dtype=np.int16)], 16000)
        t.transcribe(wav, language=None)
        assert calls["detected"], "an undeclared language must be detected"
        return calls

    # Confident English -> the general model, and NOT carrying the Hebrew
    # initial_prompt, which would only confuse it.
    out = router("en", 0.99)
    assert out["model"] == "en" and out["language"] == "en", out

    # Anything short of confident English stays exactly where it was.
    out = router("en", 0.5)
    assert out["model"] == "he" and out["language"] == "he", out


def test_the_detector_is_warmed_before_the_first_dictation() -> None:
    """The first detect_language on a freshly loaded model cost ~2 s against
    ~0.18 s warm (measured 2026-08-20). With the language left undeclared
    that first pass lands on a real dictation, so it is spent at startup —
    on both paths, and never fatally."""
    from transcribers.local_whisper import LocalWhisperTranscriber

    seen = []

    class Warm:
        def detect_language(self, audio=None, vad_filter=False):
            seen.append(vad_filter)
            return "he", 1.0, []

    t = LocalWhisperTranscriber.__new__(LocalWhisperTranscriber)
    t._english = Warm()
    t._warm_detector()
    # Silero first (its own first-call cost), then the encoder, which only
    # runs at all because VAD is off — it would strip the silence to nothing.
    assert seen == [True, False], seen

    class Boom:
        def detect_language(self, audio=None, vad_filter=False):
            raise RuntimeError("cuda hiccup")

    t._english = Boom()
    t._warm_detector()          # a bad warm-up costs speed, never the load


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
    t._hotwords = None       # real __init__ sets this; see local_whisper.py

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


# ------------------------------------------------------- modifier chords

VK_LCTRL_, VK_LSHIFT_, VK_LALT_ = 0xA2, 0xA0, 0xA4
VK_RCTRL_ = 0xA3
VK_F6, VK_F8 = 0x75, 0x77


def _chord_machine(spy, taps):
    return PTTStateMachine(
        {VK_RCTRL: "he"},
        on_start=lambda lang: spy.events.append("start"),
        on_stop=lambda lang: spy.events.append("stop"),
        on_abort=lambda why: spy.events.append("abort"),
        taps=taps, on_tap=lambda action: spy.events.append(action))


def _strike(m, *vks):
    """Press each key in order, release in reverse — one whole gesture."""
    for vk in vks:
        m.handle("down", vk, injected=False)
    for vk in reversed(vks):
        m.handle("up", vk, injected=False)


def test_a_chord_fires_only_on_the_modifiers_it_names() -> None:
    """ctrl+F6 must not fire on F6 alone, nor on ctrl+shift+F6.

    The owner moved the lookup key to "j" because F6 opens Chrome's
    address bar, and chords exist to give him back the function row. A
    chord that also fired bare would hand him the same collision it was
    bought to avoid, and one that fired with any EXTRA modifier held
    would steal ctrl+shift+F6 from whatever app defines it.
    """
    spy = Spy()
    m = _chord_machine(spy, {parse_binding("ctrl+f6"): "punctuate"})

    _strike(m, VK_LCTRL_, VK_F6)
    assert spy.events == ["punctuate"], spy.events

    spy.events.clear()
    _strike(m, VK_F6)                       # bare: not this binding
    assert spy.events == [], spy.events

    _strike(m, VK_LCTRL_, VK_LSHIFT_, VK_F6)   # one modifier too many
    assert spy.events == [], spy.events

    _strike(m, VK_LALT_, VK_F6)             # the wrong modifier entirely
    assert spy.events == [], spy.events

    # Either side of the named modifier counts — the chord has to be
    # reachable with whichever hand is free. Shown on shift, because on
    # THIS machine right ctrl is the dictation key and pressing it starts
    # a recording before F6 can ever complete a chord (asserted below, so
    # that the trap is recorded rather than merely avoided).
    spy2 = Spy()
    m2 = _chord_machine(spy2, {parse_binding("shift+f6"): "punctuate"})
    _strike(m2, VK_LSHIFT_, VK_F6)
    _strike(m2, 0xA1, VK_F6)                # right shift
    assert spy2.events == ["punctuate"] * 2, spy2.events

    spy.events.clear()
    _strike(m, VK_RCTRL_, VK_F6)
    assert spy.events == ["start", "abort"], spy.events


def test_a_bare_tap_key_still_fires_when_a_modifier_is_held() -> None:
    """Chords must not have narrowed what a bare key already meant.

    Before chords, every tap key fired on its key-down whatever was held
    — and the owner's hand rests on shift often enough that making a bare
    binding mean "and nothing else held" would read as the key randomly
    not working. A bare binding is the catch-all for its trigger.
    """
    spy = Spy()
    m = _chord_machine(spy, {parse_binding("f8"): "lookup"})

    _strike(m, VK_F8)
    assert spy.events == ["lookup"], spy.events

    spy.events.clear()
    _strike(m, VK_LSHIFT_, VK_F8)
    _strike(m, VK_LCTRL_, VK_F8)
    _strike(m, VK_LALT_, VK_F8)
    assert spy.events == ["lookup"] * 3, spy.events


def test_a_chord_and_a_bare_key_can_share_one_trigger() -> None:
    """f8 and ctrl+f8 are two keys, and exactly one of them may fire.

    This is what the shipped config does — lookup on f8, correct on
    ctrl+f8 — so if the exact match ever lost to the catch-all, a ctrl
    the owner really did hold would silently look a word up instead of
    correcting the sentence. Both directions are checked, because a
    dict that kept only the last binding written would pass one of them.
    """
    spy = Spy()
    m = _chord_machine(spy, {parse_binding("f8"): "lookup",
                             parse_binding("ctrl+f8"): "correct"})

    _strike(m, VK_F8)
    assert spy.events == ["lookup"], spy.events

    spy.events.clear()
    _strike(m, VK_LCTRL_, VK_F8)
    assert spy.events == ["correct"], spy.events

    # An unclaimed combination falls back to the bare binding, and the
    # exact one still wins the next time it is pressed.
    spy.events.clear()
    _strike(m, VK_LALT_, VK_F8)
    _strike(m, VK_LCTRL_, VK_F8)
    assert spy.events == ["lookup", "correct"], spy.events


def test_a_chord_with_no_key_to_fire_on_is_refused() -> None:
    """"ctrl+shift" is two conditions and nothing to strike.

    Bound rather than refused it would be a key that never fires and
    never says why — the owner would rebind, watch nothing happen, and
    have no way to tell a dead binding from a broken app. Refused at
    parse time, so it cannot reach config.toml either.
    """
    for text in ("ctrl+shift", "ctrl", "ctrl+left alt"):
        try:
            parse_binding(text)
        except ValueError as e:
            if text != "ctrl":     # a lone modifier IS a legal bare key
                assert "fire" in str(e), (text, e)
        else:
            if text != "ctrl":
                raise AssertionError(f"{text!r} was accepted as a binding")

    # ...and config refuses it on the field the owner would actually type
    # it into, with the field named so he knows which line to fix.
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "config.toml"
        p.write_text('hotkey = "right ctrl"\nenglish_hotkey = ""\n'
                     'lookup_hotkey = "ctrl+shift"\n', "utf-8")
        try:
            config_mod.load(p)
        except config_mod.ConfigError as e:
            assert "lookup_hotkey" in str(e), e
        else:
            raise AssertionError("a chord with no trigger was accepted")


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


def test_decoder_letter_loops_are_collapsed_and_dropped() -> None:
    """Observed live 2026-08-13, three times: a vocalised hesitation became
    a run of up to 222 ה characters. The decoder guards watch for silence
    and this is a sound, so the fix is deterministic cleanup."""
    import cleanup as cleanup_mod
    noise = "אה" + "ה" * 222
    out = cleanup_mod.clean(f"תרשום להם את העמוד טיקטוק שלי {noise} וזהו")
    assert out == "תרשום להם את העמוד טיקטוק שלי וזהו", out
    # the run alone must not survive as a message either
    assert cleanup_mod.clean(noise) in ("", noise.strip()), \
        cleanup_mod.clean(noise)
    only = cleanup_mod.collapse_char_runs(noise)
    assert only == "אהה", only


def test_char_run_collapse_leaves_real_text_alone() -> None:
    import cleanup as cleanup_mod
    for text in ("הכתבתי את זה לוואטסאפ",          # ordinary Hebrew
                 "תיכנס ל-www.example.com עכשיו",  # Latin runs survive
                 "אמממ רגע",                        # 3-run: not touched here
                 "commit לענף feature/aaaa"):       # Latin again
        assert cleanup_mod.collapse_char_runs(text) == text, text


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
        # 3-tuple: (text, backend, warning) — the shape the app returns
        # since decoder-loop warnings; the server must pass it through.
        return "שלום", "fake", "test-warning"

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
        assert ok.json().get("warning") == "test-warning", ok.json()
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
        "import time, overlay as splash;"
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


def test_a_closed_dashboard_buries_its_own_interpreter() -> None:
    """The dashboard had the same wrong-thread abort the ask card had,
    hidden behind an accident.

    ui._cache and ui._FONTS are module globals holding PhotoImages and
    Fonts, and each of those holds the tkapp -- so a closed window's
    interpreter was PINNED rather than garbage, and pinned is safe. But
    the NEXT Dashboard's __init__ calls ui.forget_images(), which drops
    that pin while the old window's cycle is still uncollected. From that
    instant the old interpreter is reachable only through a cycle, and
    whichever thread runs the next full collection calls
    Tcl_DeleteInterp. Tcl aborts when that is not the creating thread:
    exit code 3, no traceback, nothing in any log.

    Two windows and a collection on a third thread, which is the shape
    the suite itself has. Has to be a subprocess: the abort takes the
    whole process with it.
    """
    import subprocess
    here = Path(__file__).resolve().parent
    script = (
        "import gc, threading, ui, dashboard as dash;"
        "gc.disable();"
        "a = dash.Dashboard(); a.root.update(); a._close(); del a;"
        "b = dash.Dashboard(); b.root.update(); b._close(); del b;"
        "t = threading.Thread(target=gc.collect, name='not-the-builder');"
        "t.start(); t.join();"
        "print('ok')"
    )
    out = subprocess.run([sys.executable, "-c", script], cwd=str(here),
                         capture_output=True, encoding="utf-8",
                         errors="replace", timeout=120)
    assert out.returncode == 0, (out.returncode, out.stdout, out.stderr)
    assert "Tcl_AsyncDelete" not in (out.stderr or ""), out.stderr
    # and the burial has to be quiet: the poller and the reopen watcher
    # read self.closing to notice they should stop, so _bury leaves that
    # behind rather than killing them with an AttributeError
    assert "AttributeError" not in (out.stderr or ""), out.stderr


def test_closing_the_splash_cannot_close_the_status_dot() -> None:
    """The splash and the dot are two Tk interpreters alive at once, and
    `quitMainLoop` in _tkinter is a MODULE-LEVEL GLOBAL: quit() sets it and
    whichever mainloop reads it first returns and clears it. Measured over
    ten runs of the real startup sequence, five of them had the splash's
    quit() end the DOT's loop instead — no dot, and a splash left animating
    on screen for the rest of the session with nothing left to stop it.

    Run as a subprocess: it needs two fresh interpreters and it must not
    leave half-torn-down Tk state in the test process.
    """
    import subprocess
    here = Path(__file__).resolve().parent
    script = (
        "import os, time, overlay as ov, win32gui, win32process;"
        "s = ov.Splash(); s.start(); s.status('loading...'); time.sleep(.4);"
        "d = ov.StatusDot(); d.start(); time.sleep(.3);"
        "s.finish('ready', linger_ms=60); time.sleep(1.6);"
        "me = os.getpid(); found = [];"
        "cb = lambda h, _: ("
        "    found.append(win32gui.GetWindowRect(h))"
        "    if win32process.GetWindowThreadProcessId(h)[1] == me"
        "    and win32gui.IsWindowVisible(h)"
        "    and win32gui.GetClassName(h) == 'TkTopLevel' else None);"
        "win32gui.EnumWindows(cb, None);"
        "sizes = [(r[2]-r[0], r[3]-r[1]) for r in found];"
        "print('SPLASH' if any(w > 200 for w, _ in sizes) else '', "
        "      'DOT' if any(w <= 40 for w, _ in sizes) else '', flush=True);"
        "os._exit(0)"
    )
    out = subprocess.run([sys.executable, "-c", script], cwd=str(here),
                         capture_output=True, encoding="utf-8",
                         errors="replace", timeout=120)
    assert out.returncode == 0, (out.returncode, out.stdout, out.stderr)
    shown = (out.stdout or "").strip()
    assert "SPLASH" not in shown, \
        f"the splash never closed — its quit() was eaten ({shown!r})"
    assert "DOT" in shown, \
        f"the dot was destroyed by the splash's quit() ({shown!r})"


def test_the_overlays_never_call_mainloop_or_quit() -> None:
    """The deterministic half of the test above. The race only shows up
    about half the time, so the rule it exists to protect is asserted
    directly: no overlay may touch the shared quit flag."""
    source = (Path(__file__).resolve().parent / "overlay.py").read_text("utf-8")
    # Comments and docstrings NAME both of these on purpose — they explain
    # why not to use them — so look at the code only.
    code = "\n".join(line.split("#", 1)[0] for line in source.splitlines())
    body = code.split('"""', 2)[-1]
    for forbidden in ("root.quit", ".mainloop("):
        assert forbidden not in body, (
            f"overlay.py calls {forbidden} — _tkinter's quit flag is shared "
            f"between interpreters, so this closes whichever overlay looks "
            f"at it first. Use _pump_until() and a per-overlay Event.")


def test_status_dot_is_click_through_and_shuts_down_cleanly() -> None:
    """It sits in the top-right corner, which is the close button of every
    maximised window — without WS_EX_TRANSPARENT it would eat that click.
    Also guards the same Tcl teardown bug as the splash."""
    import subprocess
    import overlay as overlay_mod
    assert overlay_mod.WS_EX_TRANSPARENT == 0x20
    for name, (fill, ring, _) in overlay_mod.STATES.items():
        assert fill.startswith("#") and len(fill) == 7, (name, fill)
        assert ring.startswith("#") and len(ring) == 7, (name, ring)
    here = Path(__file__).resolve().parent
    # The window is checked, not just the exit code. Both real bugs here
    # (an AttributeError inside the thread, then a restyle applied before
    # the window was realised) left a process that exited 0 with either no
    # dot at all or a dot that ate clicks on the close button.
    script = r"""
import ctypes, time, overlay
d = overlay.StatusDot(); d.start(); time.sleep(1.0)
u = ctypes.WinDLL('user32')
class R(ctypes.Structure):
    _fields_ = [('l',ctypes.c_int),('t',ctypes.c_int),
                ('r',ctypes.c_int),('b',ctypes.c_int)]
hits = []
def cb(h, l):
    if u.IsWindowVisible(h):
        rc = R(); u.GetWindowRect(h, ctypes.byref(rc))
        if 10 < rc.r-rc.l < 60 and 10 < rc.b-rc.t < 60:
            hits.append((u.GetWindowLongW(h,-20) & 0xffffffff, rc.l, rc.r))
    return True
u.EnumWindows(ctypes.WINFUNCTYPE(
    ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)(cb), None)
assert hits, 'no dot window'
ex, left, right = hits[0]
assert ex & 0x20, 'not click-through: it would eat the close button'
assert ex & 0x08000000, 'not no-activate: it would steal focus'
assert right >= u.GetSystemMetrics(0) - 40, ('not in the top-right', right)
for s in ('recording','locked','busy','ready'):
    d.set_state(s); time.sleep(.1)
d.stop(); print('ok')
"""
    out = subprocess.run([sys.executable, "-c", script], cwd=str(here),
                         capture_output=True, encoding="utf-8",
                         errors="replace", timeout=90)
    assert out.returncode == 0, (out.returncode, out.stdout, out.stderr)
    assert "ok" in out.stdout, out.stdout
    assert "Tcl_AsyncDelete" not in (out.stderr or ""), out.stderr


def test_status_dot_ignores_states_it_does_not_know() -> None:
    """set_state is called from the keyboard hook. A typo must not raise
    there — an exception inside the hook makes Windows drop it."""
    import overlay as overlay_mod
    dot = overlay_mod.StatusDot.off()
    dot.start(); dot.set_state("recording"); dot.set_state("nonsense")
    dot.stop()
    assert dot._thread is None
    assert overlay_mod._mix("#ffffff", "#000000", 0.5) == "#808080"
    assert overlay_mod._mix("#2d6cdf", "#0b0c0d", 1.0) == "#2d6cdf"


def test_splash_off_is_inert_and_nothing_ever_raises() -> None:
    """It is decoration. On a machine with no display, no Tk, or a hostile
    window manager it must degrade to nothing, not take dictation down."""
    import overlay as overlay_mod
    off = overlay_mod.Splash.off()
    off.start(); off.status("x"); off.finish("y")
    assert off._thread is None, "off() started a thread"
    never_started = overlay_mod.Splash()
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


def test_a_streamed_reply_is_still_bounded_by_the_ollama_timeout() -> None:
    """Streaming took the timeout away, and it had to be handed back.

    urllib's timeout is per socket operation. With stream=false the
    server is silent for the whole generation, so the first recv times
    out and ollama_timeout_s bounds the request — by accident, but it
    bounds it. Streamed, a token lands every ~23 ms, no recv ever waits,
    and nothing bounds anything: measured 2026-08-19 against a server
    that streamed for 8.0 s at timeout=3, 394 chunks arrived and no
    timeout was raised.

    That is not a tidiness point. The lookup key holds `_looking_up` for
    the length of the call, so a model that loops — the failure this
    repo already carries a repetition penalty for — would answer nothing
    and refuse every further press for as long as it kept writing.

    _read is driven directly rather than over a socket because the
    deadline is the only thing under test and a real server would make
    this a timing race. The whole-reply path is checked in the same
    breath: it must NOT have grown a deadline, because the silence it
    waits through is the cold model loading.
    """
    import json
    import time as time_mod

    import translate as translate_mod

    def ndjson(piece):
        return (json.dumps({"message": {"content": piece}}) + "\n").encode()

    class Endless:
        """A model that never stops writing, fast enough that no single
        read would ever time out.

        Its own guard is a CLOCK and not a line count. Counting lines,
        this test still failed when the deadline was removed — after
        eight minutes, which is a suite nobody runs twice. A test for a
        thing that runs too long has to be the first to give up.
        """

        def __init__(self):
            self.lines, self.started = 0, time_mod.monotonic()

        def __iter__(self):
            return self

        def __next__(self):
            self.lines += 1
            assert time_mod.monotonic() - self.started < 5, \
                f"the deadline never fired ({self.lines} lines in 5s)"
            time_mod.sleep(0.005)
            return ndjson("loop ")

    seen = []
    t = translate_mod.OllamaTranslator("m", "http://127.0.0.1:1", 1,
                                       on_chunk=seen.append)
    runaway = Endless()
    started = time_mod.monotonic()
    try:
        t._read(runaway)
        assert False, "an endless stream was allowed to run to completion"
    except TimeoutError as e:
        spent = time_mod.monotonic() - started
        assert 1.0 <= spent < 3.0, f"gave up after {spent:.2f}s, not ~1s"
        assert "still writing" in str(e), e
    assert seen, "nothing was painted before it gave up"

    # It is TimeoutError and not TranslationError on purpose: it is
    # raised inside the caller's `with`, so translate() turns it into a
    # TranslationError like every other way the read can fail, and the
    # caller moves to the next backend instead of keeping a half answer.
    assert issubclass(TimeoutError, Exception)

    # A stream that finishes inside the deadline is untouched.
    quick = translate_mod.OllamaTranslator("m", "http://127.0.0.1:1", 5,
                                           on_chunk=seen.append)
    assert quick._read(iter([ndjson("שביר\n"), b"\n",
                             ndjson("1. שם תואר - נשבר.")])) == \
        "שביר\n1. שם תואר - נשבר."

    # And the un-streamed path — the three keys that pass no on_chunk —
    # has no deadline of its own to trip over while a cold model loads.
    class Whole:
        def read(self):
            time_mod.sleep(0.05)
            return json.dumps({"message": {"content": "whole"}}).encode()

    plain = translate_mod.OllamaTranslator("m", "http://127.0.0.1:1", 0)
    assert plain._read(Whole()) == "whole"


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


def test_the_repair_pass_ships_its_backend_choice_in_the_real_config(
) -> None:
    """Guards the shipped config against the drift that already happened
    once: the fast branch moved the repair pass to Groq in config.py and
    config.toml went on saying nothing about it, so the file the owner
    reads described a local-only pass that had not been local-only for
    days. A default that lives only in code is a default nobody can find.

    The reasoning model is pinned by name here, and not only in
    translate.py's own tests, because its failure is SILENT: gpt-oss-120b
    spends hidden tokens before it answers, and a cap tighter than
    GroqTranslator's floor gets an empty reply rather than an error.
    """
    here = Path(__file__).resolve().parent / "config.toml"
    text = here.read_text(encoding="utf-8")
    cfg = config_mod.load(here)
    assert cfg.polish.prefer == "groq", cfg.polish.prefer
    assert "\nprefer = " in text, (
        "polish.prefer is not written down in config.toml")
    assert "groq_model" in text, (
        "polish.groq_model is not written down in config.toml")
    # A reasoning model, and named as one: see AGENTS.md's trap list.
    assert cfg.polish.groq_model == "openai/gpt-oss-120b", (
        cfg.polish.groq_model)
    assert cfg.polish.groq_timeout_s > 0
    # The fallback under it is what classic runs. Losing that is losing
    # every repair the moment a key expires or the network goes.
    assert cfg.polish.ollama_model, "no local fallback model configured"
    assert cfg.polish.when in ("never", "known", "always")


def _committed_on(branch: str, path: str) -> bytes | None:
    """`path` as `branch` committed it, or None when git cannot say.

    None covers every honest reason a checkout has no answer — a shallow
    or single-branch clone, no git on PATH, not a repository at all — and
    the callers skip rather than fail. A test that goes red on someone
    else's clone teaches them to ignore it.

    CREATE_NO_WINDOW because the suite is meant to be runnable while
    dictation is live and this app runs under pythonw: without the flag
    every git spawn allocates a console and freezes the UI thread. Same
    trap as versions.py and dashboard.py.
    """
    import subprocess
    try:
        out = subprocess.run(
            ["git", "show", f"{branch}:{path}"],
            cwd=str(Path(__file__).resolve().parent),
            capture_output=True, creationflags=0x08000000)
    except (OSError, ValueError):
        return None
    return out.stdout if out.returncode == 0 else None


def test_both_versions_commit_the_same_settings_file() -> None:
    """THE INVARIANT versions.py is built on, and it has been broken once.

    Switching versions is a `git checkout` of this very folder. config.toml
    survives it only because versions.py saves the live bytes and writes
    them back — which works no matter what the branches committed, and is
    exactly why the divergence is silent. What it cannot save you from is
    MEANING: a key whose value is safe on one branch and not on the other.

    That is not hypothetical. lookup.max_chars went 5000 -> 20000 on fast
    together with the chunking in lookup.translate_chunked that makes the
    larger number safe; carried to a classic that had no chunking, the same
    line would have fed 20000 characters to one local request and had them
    silently truncated past the context window. The commit that raised it
    shipped to one branch alone, and nothing here noticed.

    So: byte-identical, or the branches are two programs.
    """
    here = Path(__file__).resolve().parent
    live = (here / "config.toml").read_bytes()
    seen = {}
    for branch in ("fast", "classic"):
        blob = _committed_on(branch, "config.toml")
        if blob is not None:
            seen[branch] = blob
    if len(seen) < 2:
        return                      # single-branch clone: nothing to compare
    (a, one), (b, two) = seen.items()
    assert one == two, (
        f"{a} and {b} commit different config.toml — versions.py promises "
        f"they never do. Mirror the change across before pushing; a "
        f"setting that means one thing on one version and another thing "
        f"on the other is how a version switch loses your work.")
    # And the file on disk should be one of the two, give or take whatever
    # the owner has edited since. Only its SHAPE is checked: a live config
    # missing a section the branches ship means a stale hand-edit.
    for section in (b"[polish]", b"[lookup]", b"[local]", b"[vocab]"):
        assert section in live, f"config.toml has lost {section!r}"


def test_the_shared_half_of_the_app_is_one_file_on_both_versions() -> None:
    """What may differ between the versions is the REPAIR PASS and nothing
    else. Everything here is a file that a version switch would otherwise
    delete a feature out of.

    The owner's rule, in his words: both versions stay "the same
    application, with the same history and the same hot words". The lookup
    box, the paste path and the switcher itself are not part of the
    experiment, so they are not allowed to drift into it — a resizer
    committed to fast alone is a resizer you lose by pressing a button
    labelled "use classic".

    The list is deliberately short and explicit rather than "everything
    except polish.py": a NEW file that belongs to the repair pass should
    not have to be excluded here, and a new shared file should have to be
    added on purpose.
    """
    shared = ("popup.py", "lookup.py", "main.py", "versions.py",
              "injector.py", "hotkey.py", "vocab.py", "singleton.py",
              "config.toml")
    drifted = []
    for name in shared:
        one = _committed_on("fast", name)
        two = _committed_on("classic", name)
        if one is None or two is None:
            return                  # single-branch clone: nothing to compare
        if one != two:
            drifted.append(name)
    assert not drifted, (
        "these are shared between the versions and have drifted apart: "
        + ", ".join(drifted)
        + ". Mirror the change to the other branch (see versions.py) — "
          "switching versions is a checkout, so whatever is missing there "
          "is a feature the owner loses by switching.")


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


# --------------------------------------------------------------------------
# Learning from corrections (vocab.py) and the context pass (polish.py)
# --------------------------------------------------------------------------


def _tmp_vocab(**kw):
    import tempfile
    return vocab_mod.Vocab(Path(tempfile.mkdtemp(prefix="vocab-"))
                           / "vocab.json", **kw)


def test_a_correction_teaches_only_the_words_that_changed() -> None:
    """The whole feature in one assertion: the user fixes two words in a
    sentence and the app learns those two words, not the sentence."""
    raw = "תריץ את השרת של xpogo ואז תעשה Brinth production"
    fixed = "תריץ את השרת של Expo Go ואז תעשה branch production"
    pairs = vocab_mod.diff_corrections(raw, fixed)
    assert ("xpogo", "Expo Go") in pairs, pairs
    assert ("Brinth", "branch") in pairs, pairs
    assert len(pairs) == 2, pairs


def test_insertions_and_deletions_teach_nothing() -> None:
    """A word the model MISSED has no misheard form to key on, and a word it
    invented is the hallucination filter's job. Learning either would put a
    rule in the store that can never match, or worse, one that deletes."""
    assert vocab_mod.diff_corrections("שלום עולם",
                                      "שלום גדול עולם") == []
    assert vocab_mod.diff_corrections("שלום גדול עולם",
                                      "שלום עולם") == []


def test_a_rewritten_sentence_is_not_learned_as_a_word() -> None:
    """Editing the box into a different sentence is the user rewriting, not
    correcting. Learning it would teach the app to swap whole sentences."""
    raw = "אחת שתיים שלוש ארבע חמש שש"
    fixed = "לגמרי משהו אחר לגמרי אחר כאן עכשיו"
    for heard, meant in vocab_mod.diff_corrections(raw, fixed):
        assert len(heard.split()) <= vocab_mod.MAX_SPAN_WORDS, (heard, meant)
        assert len(meant.split()) <= vocab_mod.MAX_SPAN_WORDS, (heard, meant)


def test_repair_waits_for_the_second_correction() -> None:
    """replace_after_hits exists because one correction could be a slip of
    the finger in the box, and this pass rewrites the user's own words."""
    v = _tmp_vocab(replace_after_hits=2)
    v.learn("xpogo", "Expo Go")
    out, applied = v.apply("תריץ את xpogo עכשיו")
    assert out == "תריץ את xpogo עכשיו", "one correction must not be enough"
    assert applied == []
    v.learn("xpogo", "Expo Go")            # same mistake, second time
    out, applied = v.apply("תריץ את xpogo עכשיו")
    assert out == "תריץ את Expo Go עכשיו", out
    assert applied == ["xpogo -> Expo Go"], applied


def test_repair_never_eats_the_middle_of_a_word() -> None:
    """A learned short garble matching inside a longer real word is how a
    replacement pass starts corrupting speech. The end of the match must
    always be a word boundary — even though the START tolerates a Hebrew
    prefix (see the next test)."""
    v = _tmp_vocab(replace_after_hits=1)
    v.learn("הר", "Har")
    out, applied = v.apply("יש הרבה דברים כאן")
    assert out == "יש הרבה דברים כאן", out
    assert applied == [], applied
    out, _ = v.apply("הר אחד")
    assert out == "Har אחד", out


def test_repair_sees_through_a_hebrew_prefix() -> None:
    """The real case from transcripts.log: the app heard "לסירקה", the user
    corrects the bare word "סירקה", and the next transcript says "לסירקה"
    again. Without prefix matching the lesson never fires on the words it
    was actually taught — and the prefix must survive the swap."""
    v = _tmp_vocab(replace_after_hits=1)
    v.learn("סירקה", "סריקה")
    out, applied = v.apply("העלה את זה לסירקה ציבורית")
    assert out == "העלה את זה לסריקה ציבורית", out
    assert applied == ["סירקה -> סריקה"], applied


def test_hotwords_put_the_seeds_first_and_stay_bounded() -> None:
    """The seeds are the user's own stack, hand-written in config.toml. A
    burst of recent corrections must not push them out of the budget."""
    v = _tmp_vocab(seed_terms=("Massif", "TripSync"), max_terms=4)
    for i in range(20):
        v.learn(f"garble{i}", f"Term{i}")
    terms = v.hotwords().split()
    assert terms[:2] == ["Massif", "TripSync"], terms
    assert len(terms) == 4, terms


def test_hotwords_do_not_repeat_a_seeded_term() -> None:
    """Correcting something already seeded must not spend the budget twice
    on the same word."""
    v = _tmp_vocab(seed_terms=("Expo Go",), max_terms=10)
    v.learn("xpogo", "Expo Go")
    assert v.hotwords().split().count("Expo") == 1, v.hotwords()


def test_hits_rank_above_recency_in_the_hotword_list() -> None:
    """A name corrected four times is one the user says often, and it earns
    its slot ahead of a one-off from five minutes ago."""
    v = _tmp_vocab(max_terms=2)
    v.learn("aaa", "Often")
    v.learn("aaa", "Often")
    v.learn("aaa", "Often")
    v.learn("bbb", "Once")
    assert v.hotwords().split()[0] == "Often", v.hotwords()


def test_a_corrupt_vocab_file_does_not_stop_dictation() -> None:
    """Accuracy is allowed to degrade; dictation is not allowed to stop."""
    import tempfile
    path = Path(tempfile.mkdtemp(prefix="vocab-")) / "vocab.json"
    path.write_text("{not json at all", "utf-8")
    v = vocab_mod.Vocab(path, seed_terms=("Massif",))
    assert len(v) == 0
    assert v.hotwords() == "Massif"


def test_the_vocabulary_survives_a_round_trip() -> None:
    import tempfile
    path = Path(tempfile.mkdtemp(prefix="vocab-")) / "vocab.json"
    a = vocab_mod.Vocab(path)
    a.learn_from_edit("תריץ את xpogo", "תריץ את Expo Go")
    b = vocab_mod.Vocab(path)
    assert [(c["heard"], c["meant"]) for c in b.corrections] == \
        [("xpogo", "Expo Go")], b.corrections


# ---- the guard that makes the context pass safe to run at all ----


def test_polish_accepts_a_word_swap() -> None:
    """The case the whole pass exists for: a real Hebrew word swapped for
    another real Hebrew word, which only the sentence disambiguates."""
    import polish as polish_mod
    before = "השדה נשאר למטה וגם מקללת מסתירה את מה שאני כותב"
    after = "השדה נשאר למטה וגם מקלדת מסתירה את מה שאני כותב"
    ok, why = polish_mod._is_safe(before, after)
    assert ok, why


def test_polish_rejects_an_added_sentence() -> None:
    """"שלא ימציא משפטים חדשים" — enforced in code, not just asked for in
    the prompt. A model that helpfully finishes the user's thought is the
    failure mode this pass would otherwise introduce."""
    import polish as polish_mod
    before = "תבדוק לי את הקוד ותגיד אם יש באג בפונקציה הזאת בבקשה"
    after = before + ". אני אשמח אם תוסיף גם בדיקות יחידה ותריץ אותן."
    ok, why = polish_mod._is_safe(before, after)
    assert not ok, "an appended sentence must be rejected"
    assert "writing" in why or "grew" in why, why


def test_polish_rejects_a_reworded_paragraph() -> None:
    """Same length, different words: the model 'improved' the phrasing. That
    is worse than a garble, because a garble is visible and this is not."""
    import polish as polish_mod
    before = "אני רוצה שתעבור על הבאגים האלה ותתקן אותם אחד אחרי השני"
    after = "נא לבדוק את התקלות הללו ולטפל בכל אחת מהן בנפרד ובזו אחר זו"
    ok, why = polish_mod._is_safe(before, after)
    assert not ok, "a reworded paragraph must be rejected"


def test_polish_rejects_dropped_content() -> None:
    """Repetition and half-finished sentences are the speaker's own words.
    A pass that tidies them away is deleting real speech."""
    import polish as polish_mod
    before = ("אני רוצה שתוסיף את הכפתור הזה למעלה ואז גם תוריד את זה "
              "למטה ותסדר את כל העמוד מחדש בבקשה")
    ok, why = polish_mod._is_safe(before, "אני רוצה שתוסיף את הכפתור")
    assert not ok, "a truncated reply must be rejected"
    assert "lost" in why or "dropped" in why, why


def test_polish_rejects_an_empty_reply() -> None:
    import polish as polish_mod
    ok, _ = polish_mod._is_safe("משהו אמיתי שנאמר כאן", "   ")
    assert not ok


def test_polish_only_wakes_up_for_a_known_mistake() -> None:
    """`when = "known"` is what keeps an idle Ollama (76 s cold) from being
    woken on a dictation with nothing to repair."""
    import dataclasses

    import polish as polish_mod

    cfg = config_mod.load(Path(__file__).resolve().parent / "config.toml")
    cfg = dataclasses.replace(cfg, polish=config_mod.PolishConfig(
        when="known", min_chars=5))
    v = _tmp_vocab()
    p = polish_mod.Polisher(cfg, v)
    text = "תריץ את השרת של xpogo בבקשה ותגיד לי מה קרה"
    assert not p.should_run(text), "nothing learned yet — must not run"
    v.learn("xpogo", "Expo Go")
    assert p.should_run(text), "a known garble is present — must run"
    assert not p.should_run("משפט נקי לגמרי בלי שום בעיה ידועה כאן")


def test_a_slow_context_pass_is_abandoned_rather_than_waited_out() -> None:
    """Measured 2026-08-14: a cold Ollama took 53.7 s. The pass no longer
    sits in front of the cursor, so this deadline is a leash on a background
    thread rather than on the user's patience — but a request that never
    comes back must still be given up on, or every dictation leaks a thread
    holding an HTTP connection for translate.ollama_timeout_s."""
    import dataclasses
    import time

    import polish as polish_mod

    cfg = config_mod.load(Path(__file__).resolve().parent / "config.toml")
    cfg = dataclasses.replace(cfg, polish=config_mod.PolishConfig(
        when="always", min_chars=1, max_wait_s=0.3))

    class Molasses:
        name = "molasses"

        def translate(self, text):
            time.sleep(30)              # a cold model loading into VRAM
            return "never gets used"

    p = polish_mod.Polisher(cfg, _tmp_vocab())
    p._backends = lambda text: iter([Molasses()])
    raw = "תריץ את השרת בבקשה ותגיד לי מה קרה שם"
    started = time.monotonic()
    out, by = p.polish(raw)
    waited = time.monotonic() - started

    assert out == raw, "the raw transcript must survive a timeout"
    assert by is None, by
    assert waited < 3, f"waited {waited:.1f}s — the deadline did not hold"


def test_the_context_pass_never_reaches_for_gemini() -> None:
    """The old rule, restated for the fast version: GEMINI is still never a
    repair backend — its 20/model/day bucket belongs to the translate (F9)
    and punctuate (F2) keys. What may appear is Groq (the one cloud free
    tier that exists as of Aug 2026) and Cerebras, with Ollama behind both
    as the fallback classic always had."""
    import apikey as apikey_mod
    import polish as polish_mod

    cfg = config_mod.load(Path(__file__).resolve().parent / "config.toml")
    polisher = polish_mod.Polisher(cfg, _tmp_vocab())
    text = "תריץ את השרת בבקשה ותגיד לי מה קרה שם"
    original = apikey_mod.find_key

    def no_keys(names):
        return None, "not found"

    def all_keys(names):
        return "test-key", "test"

    try:
        # A machine without any cloud key: neither fast backend can be
        # built, so the pass must degrade to exactly what classic ran.
        apikey_mod.find_key = no_keys
        names = [b.name for b in polisher._backends(text)]
        assert "gemini" not in names, names
        assert names == ["ollama"], (
            f"without keys the pass must be classic-shaped: {names}")

        # With keys: groq first (prefer's default), everything behind it.
        apikey_mod.find_key = all_keys
        names = [b.name for b in polisher._backends(text)]
        assert names == ["groq", "cerebras", "ollama"], names
    finally:
        apikey_mod.find_key = original


def test_polish_prefer_ollama_reverses_the_repair_order() -> None:
    """prefer = "ollama" must mean local-first with cloud as the fallback,
    not local-only — the other backends still catch a dead primary."""
    import dataclasses

    import apikey as apikey_mod
    import polish as polish_mod

    cfg = config_mod.load(Path(__file__).resolve().parent / "config.toml")
    cfg = dataclasses.replace(cfg, polish=dataclasses.replace(
        cfg.polish, prefer="ollama"))
    polisher = polish_mod.Polisher(cfg, _tmp_vocab())
    original = apikey_mod.find_key
    try:
        apikey_mod.find_key = lambda names: ("test-key", "test")
        names = [b.name for b in polisher._backends("משפט לבדיקה בבקשה")]
    finally:
        apikey_mod.find_key = original
    assert names == ["ollama", "groq", "cerebras"], names


def test_reply_caps_are_sized_from_the_text() -> None:
    """The honest reply is the input with words swapped; anything longer
    was never going to pass _is_safe. The cap turns that case from an
    unbounded generation into a bounded one the fallback absorbs."""
    from polish import _token_cap

    assert _token_cap("תעשה commit") == 96, "short clips get the floor"
    assert _token_cap(" ".join(["word"] * 500)) == 1024, "the ceiling holds"
    assert 96 < _token_cap(" ".join(["word"] * 100)) < 1024


def test_a_missing_cerebras_key_names_the_fix() -> None:
    """The message must say exactly which line in .env to add — a bare
    'no key' sends someone hunting through three providers."""
    import apikey as apikey_mod
    import translate as translate_mod
    from transcribers.base import TranscriptionError

    original = apikey_mod.find_key
    apikey_mod.find_key = lambda names: (None, "not found")
    try:
        translate_mod.CerebrasTranslator("gpt-oss-120b", 20)
    except TranscriptionError as e:
        assert "CEREBRAS_API_KEY" in str(e), e
        assert ".env" in str(e), e
    else:
        raise AssertionError("a missing key must stop construction")
    finally:
        apikey_mod.find_key = original


def test_ollama_num_predict_stays_out_of_shared_requests() -> None:
    """OllamaTranslator serves four keys. The repair pass may cap its own
    replies; nobody else's request body may change by a byte."""
    import json as json_mod

    import translate as translate_mod

    captured: dict = {}

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return b'{"message":{"content":"ok"}}'

    def fake_urlopen(request, timeout=None):
        captured["body"] = json_mod.loads(request.data.decode("utf-8"))
        return _Resp()

    original = translate_mod.urllib.request.urlopen
    translate_mod.urllib.request.urlopen = fake_urlopen
    try:
        plain = translate_mod.OllamaTranslator(
            "m", "http://127.0.0.1:11434", 5)
        assert plain.translate("x") == "ok"
        assert "num_predict" not in captured["body"]["options"], \
            captured["body"]

        capped = translate_mod.OllamaTranslator(
            "m", "http://127.0.0.1:11434", 5, num_predict=128)
        assert capped.translate("x") == "ok"
        assert captured["body"]["options"]["num_predict"] == 128
    finally:
        translate_mod.urllib.request.urlopen = original


def test_the_fast_knobs_validate_and_default_classic_shaped() -> None:
    """beam_size and the cloud trio must refuse nonsense loudly, and a
    config.toml that predates them entirely must still load — landing on
    the fast defaults without anyone editing it."""
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "c.toml"
        p.write_text('backend = "local"\n', "utf-8")
        cfg = config_mod.load(p)
        assert cfg.polish.prefer == "groq"
        assert cfg.local.beam_size == 5

        for bad, needle in (
                ('[polish]\nprefer = "gemini"\n', "prefer"),
                ('[polish]\nprefer = "groq"\ngroq_model = ""\n',
                 "groq_model"),
                ('[polish]\ngroq_timeout_s = 0\n', "groq_timeout"),
                ('[polish]\nprefer = "cerebras"\ncerebras_model = ""\n',
                 "cerebras_model"),
                ('[polish]\ncerebras_timeout_s = 0\n', "cerebras_timeout"),
                ("[local]\nbeam_size = 0\n", "beam_size")):
            p.write_text(bad, "utf-8")
            try:
                config_mod.load(p)
            except config_mod.ConfigError as e:
                assert needle in str(e), (bad, e)
            else:
                raise AssertionError(f"must be refused: {bad!r}")


def test_the_transcript_is_final_when_it_lands() -> None:
    """THE contract the placeholder makes. The context pass runs BEFORE the
    paste, so what appears at the cursor is finished: nothing rewrites it a
    few seconds later. That ordering was reversed once, for the speed, and
    reversed back — text that might still change is text you cannot send,
    because you never know whether you are looking at the final version."""
    import main as main_mod

    seen = []

    with tempfile.TemporaryDirectory() as tmp:
        app = _worker_app(_Flaky(0, text="המקללת מסתירה את השדה"), tmp)
        app.cfg = dataclasses.replace(app.cfg, polish=config_mod.PolishConfig(
            when="always", min_chars=1, max_wait_s=5))

        import polish as polish_mod

        class Reply:
            name = "stub-model"

            def translate(self, text):
                seen.append(text)
                return "המקלדת מסתירה את השדה"

        polisher = polish_mod.Polisher(app.cfg, app.vocab)
        polisher._backends = lambda text: iter([Reply()])
        app._polisher = polisher

        fake = _FakeInjector()
        with _patched(main_mod, "injector", fake):
            app._handle(b"RIFF-audio", 6.0, fake.focus)

    assert seen, "the context pass never ran before the paste"
    writes = [c for c in fake.calls if c[0] in ("replace", "inject")]
    assert len(writes) == 1, f"the text was written more than once: {fake.calls}"
    assert writes[0][-1] == "המקלדת מסתירה את השדה", writes[0]


def test_word_timestamps_stay_on_because_the_silence_guard_needs_them() -> None:
    """hallucination_silence_threshold does not work without word
    timestamps, so the flag that looks most like a debugging leftover is
    the one holding up the guard against Knesset boilerplate. Nothing
    asserted it before — a refactor could have dropped it with the suite
    still green."""
    from transcribers.local_whisper import hallucination_guards

    guards = hallucination_guards(True)
    assert guards.get("word_timestamps") is True, guards
    assert guards.get("hallucination_silence_threshold") == 2.0, guards
    assert hallucination_guards(False) == {}, "off must mean off"


def test_the_warm_up_never_raises() -> None:
    """Ollama not being installed is a normal state, not a startup error."""
    import dataclasses

    import polish as polish_mod

    cfg = config_mod.load(Path(__file__).resolve().parent / "config.toml")
    cfg = dataclasses.replace(cfg, polish=config_mod.PolishConfig(
        when="known", max_wait_s=0.2))

    class Dead:
        name = "dead"

        def translate(self, text):
            raise OSError("connection refused")

    p = polish_mod.Polisher(cfg, _tmp_vocab())
    p._backends = lambda text: iter([Dead()])
    p.warm()          # must not raise


def test_polish_never_runs_when_switched_off() -> None:
    import dataclasses

    import polish as polish_mod

    cfg = config_mod.load(Path(__file__).resolve().parent / "config.toml")
    cfg = dataclasses.replace(cfg, polish=config_mod.PolishConfig(
        when="never"))
    v = _tmp_vocab()
    v.learn("xpogo", "Expo Go")
    p = polish_mod.Polisher(cfg, v)
    assert not p.should_run("תריץ את xpogo עכשיו בבקשה ותראה מה קורה")


# ---- the plumbing that carries the vocabulary to the decoder ----


def test_hotwords_reach_both_models() -> None:
    """Unlike initial_prompt, which is a Hebrew sentence and is withheld
    from the English model, hotwords is a list of NAMES — and an English
    utterance is if anything the more likely place to say "Expo Go"."""
    from transcribers.local_whisper import LocalWhisperTranscriber

    seen = {}

    class FakeModel:
        def __init__(self, tag):
            self.tag = tag

        def transcribe(self, audio, **kw):
            seen[self.tag] = kw.get("hotwords")

            class Seg:
                text = "x"
            return [Seg()], None

    t = LocalWhisperTranscriber.__new__(LocalWhisperTranscriber)
    t._model, t._english = FakeModel("he"), FakeModel("en")
    t._language, t._english_threshold = "he", 0.8
    t._cleanup, t._fillers = False, ()
    t._initial_prompt = None
    t._guards, t._boilerplate = {}, ()
    t._hotwords = lambda: "Expo Go EAS Cowork"

    t.transcribe(b"RIFF", language="he")
    t.transcribe(b"RIFF", language="en")
    assert seen["he"] == "Expo Go EAS Cowork", seen
    assert seen["en"] == "Expo Go EAS Cowork", seen


def test_a_broken_vocabulary_does_not_break_transcription() -> None:
    """The hotword source is user data resolved at request time. If it
    throws, the dictation still has to come out."""
    from transcribers.local_whisper import LocalWhisperTranscriber

    seen = {}

    class FakeModel:
        def transcribe(self, audio, **kw):
            seen["hotwords"] = kw.get("hotwords")

            class Seg:
                text = "בסדר"
            return [Seg()], None

    t = LocalWhisperTranscriber.__new__(LocalWhisperTranscriber)
    t._model, t._english = FakeModel(), None
    t._language, t._english_threshold = "he", 0.8
    t._cleanup, t._fillers = False, ()
    t._initial_prompt = None
    t._guards, t._boilerplate = {}, ()

    def explode():
        raise RuntimeError("vocab is on fire")

    t._hotwords = explode
    assert t.transcribe(b"RIFF", language="he") == "בסדר"
    assert seen["hotwords"] is None, seen


def test_an_empty_vocabulary_sends_no_hotwords() -> None:
    """None, not "" — an empty string would still open a prompt block and
    spend the sot_prev token for nothing."""
    v = _tmp_vocab()
    assert v.hotwords() == ""

    from transcribers.local_whisper import LocalWhisperTranscriber
    t = LocalWhisperTranscriber.__new__(LocalWhisperTranscriber)
    t._hotwords = v.hotwords
    assert t._current_hotwords() is None


# ---- the shipped config ----


def test_correct_hotkey_must_not_collide() -> None:
    import tempfile
    bad = Path(tempfile.mkdtemp(prefix="cfg-")) / "config.toml"
    bad.write_text('hotkey = "right ctrl"\nenglish_hotkey = ""\n'
                   'correct_hotkey = "f9"\ntranslate_hotkey = "f9"\n',
                   "utf-8")
    try:
        config_mod.load(bad)
    except config_mod.ConfigError as e:
        assert "correct_hotkey" in str(e), e
    else:
        raise AssertionError("a key that both translates and corrects was "
                             "accepted")


def test_polish_when_is_validated() -> None:
    import tempfile
    bad = Path(tempfile.mkdtemp(prefix="cfg-")) / "config.toml"
    bad.write_text('[polish]\nwhen = "sometimes"\n', "utf-8")
    try:
        config_mod.load(bad)
    except config_mod.ConfigError as e:
        assert "polish.when" in str(e), e
    else:
        raise AssertionError('polish.when = "sometimes" was accepted')


def test_the_real_config_seeds_the_names_that_actually_garble() -> None:
    """Guards the shipped config against the measured failures in
    transcripts.log: every one of these was observed coming out wrong."""
    cfg = config_mod.load(Path(__file__).resolve().parent / "config.toml")
    assert cfg.vocab.enabled is True
    assert cfg.correct_hotkey, "with no correction key nothing is ever learned"
    seeded = {t.lower() for t in cfg.vocab.terms}
    for term in ("expo go", "eas", "cowork", "hebrewdictation", "branch"):
        assert term in seeded, f"{term!r} garbles in practice and is not seeded"
    assert cfg.vocab.replace_after_hits >= 2, \
        "one correction must not be enough to start rewriting speech"


def test_the_phone_gets_the_vocabulary_the_desktop_learned() -> None:
    """The phone only records; THIS machine transcribes, with the same
    transcriber the hotwords callable was given. So a word taught with F8 on
    the desktop must stop being misheard on the phone too — with nothing
    implemented on the Android side. Asserts both halves: the hotwords
    reaching the decoder, and the repair pass being applied."""
    import shutil
    import tempfile

    tmp = Path(tempfile.mkdtemp(prefix="dictation-phone-"))
    try:
        app = _worker_app(_Flaky(fail_times=0, text="תריץ את xpogo"), tmp)
        app.vocab.seed_terms = ("Expo Go",)
        # taught twice on the desktop -> past replace_after_hits
        app.vocab.learn("xpogo", "Expo Go")
        app.vocab.learn("xpogo", "Expo Go")

        seen = {}

        class Recording:
            name = "local"

            def transcribe(self, wav, language=None):
                seen["hotwords"] = app._hotwords()
                return "תריץ את xpogo"

        app.transcriber = Recording()
        text, backend, _warning = app._transcribe_for_phone(b"RIFF")

        assert "Expo Go" in seen["hotwords"], seen
        assert text == "תריץ את Expo Go", text
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_word_error_rate_counts_word_edits() -> None:
    import main as main_mod
    assert main_mod.word_error_rate("אחת שתיים שלוש",
                                    "אחת שתיים שלוש") == (0, 3)
    assert main_mod.word_error_rate("אחת שתיים שלוש",
                                    "אחת שבע שלוש") == (1, 3)
    assert main_mod.word_error_rate("אחת שתיים שלוש", "אחת שלוש") == (1, 3)


def test_a_recording_is_kept_and_the_correction_is_attached_to_it() -> None:
    """The loop that makes any of this measurable: audio in, correction on
    top of it, and a labelled pair on disk that --benchmark can replay."""
    import shutil
    import tempfile

    import main as main_mod
    from recorder import frames_to_wav
    from spool import Spool

    tmp = Path(tempfile.mkdtemp(prefix="dictation-learn-"))
    fake = _FakeInjector()
    real_inj = main_mod.injector
    try:
        main_mod.injector = fake
        app = _worker_app(
            _Flaky(fail_times=0, text="תריץ את xpogo ותגיד לי מה קרה"), tmp)
        app.recent = Spool(tmp / "recent", keep=10)
        wav = frames_to_wav([np.zeros(1600, dtype=np.int16)], 16000)

        app._handle(wav, 2.0, hwnd=fake.focus)
        assert app._last and "xpogo" in app._last["final"], app._last
        assert app._last["wav"], "the audio was not kept"

        # The user fixed it in the app it was pasted into, in a chat box
        # that also holds the rest of their message.
        fake.on_screen = ("שלום, יש לי שאלה. תריץ את Expo Go ותגיד לי מה "
                          "קרה. תודה רבה על העזרה")
        app._correct(dict(app._last), hwnd=fake.focus)

        assert [(c["heard"], c["meant"]) for c in app.vocab.corrections] == \
            [("xpogo", "Expo Go")], app.vocab.corrections
        kept = app.recent.pending()
        assert len(kept) == 1, kept
        assert "Expo Go" in kept[0].meta["corrected"], kept[0].meta
        assert kept[0].read() == wav, "the audio must still be replayable"
        assert ("restore", "whatever the user had") in fake.calls, \
            "grab() leaves text on the clipboard — it must be put back"
    finally:
        main_mod.injector = real_inj
        shutil.rmtree(tmp, ignore_errors=True)


def test_a_field_that_lost_the_transcript_teaches_nothing() -> None:
    """The user moved on and the cursor is somewhere else entirely. Diffing
    the transcript against unrelated text would fill the vocabulary with
    pairs of words that have nothing to do with each other."""
    import shutil
    import tempfile

    import main as main_mod

    tmp = Path(tempfile.mkdtemp(prefix="dictation-elsewhere-"))
    fake = _FakeInjector()
    real_inj = main_mod.injector
    try:
        main_mod.injector = fake
        app = _worker_app(_Flaky(fail_times=0), tmp)
        fake.on_screen = "def main():\n    return some_unrelated_python_code"
        app._correct({"final": "תריץ את xpogo בבקשה עכשיו", "raw": "",
                      "wav": ""}, hwnd=fake.focus)
        assert len(app.vocab) == 0, app.vocab.corrections
    finally:
        main_mod.injector = real_inj
        shutil.rmtree(tmp, ignore_errors=True)


def test_unchanged_text_on_screen_teaches_nothing() -> None:
    import shutil
    import tempfile

    import main as main_mod

    tmp = Path(tempfile.mkdtemp(prefix="dictation-nochange-"))
    fake = _FakeInjector()
    real_inj = main_mod.injector
    try:
        main_mod.injector = fake
        app = _worker_app(_Flaky(fail_times=0), tmp)
        fake.on_screen = "תריץ את xpogo בבקשה עכשיו"
        app._correct({"final": "תריץ את xpogo בבקשה עכשיו", "raw": "",
                      "wav": ""}, hwnd=fake.focus)
        assert len(app.vocab) == 0, app.vocab.corrections
    finally:
        main_mod.injector = real_inj
        shutil.rmtree(tmp, ignore_errors=True)


def test_the_transcript_is_found_inside_a_longer_message() -> None:
    """The key is pressed in a chat box holding a whole paragraph, of which
    the last dictation is one sentence. Only that sentence may be diffed."""
    shown = "תריץ את xpogo ואז תעשה Brinth production"
    screen = ("קודם כל שלום. תריץ את Expo Go ואז תעשה branch production. "
              "ואחר כך נמשיך לדבר על משהו אחר לגמרי")
    span, ratio = vocab_mod.locate(shown, screen)
    assert ratio >= vocab_mod.MIN_MATCH, ratio
    assert "Expo Go" in span and "branch production" in span, span
    assert "קודם כל שלום" not in span, span
    assert "לגמרי" not in span, span
    pairs = vocab_mod.diff_corrections(shown, span)
    assert ("xpogo", "Expo Go") in pairs, pairs
    assert ("Brinth", "branch") in pairs, pairs


# ---------------------------------------------------------------- pausing

VK_SCROLL = 0x91
VK_F8 = 0x77


def _pause_machine(spy, pause_vk=VK_SCROLL, latch_vk=VK_LEFT):
    return PTTStateMachine(
        {VK_RCTRL: "he"},
        on_start=lambda lang: spy.events.append("start"),
        on_stop=lambda lang: spy.events.append("stop"),
        on_abort=lambda why: spy.events.append(f"abort:{why}"),
        taps={VK_F9: "translate"},
        on_tap=lambda action: spy.events.append(f"tap:{action}"),
        latch_vk=latch_vk, on_latch=lambda: spy.events.append("latch"),
        pause_vk=pause_vk,
        on_pause=lambda paused: spy.events.append(
            "paused" if paused else "resumed"))


def test_pausing_makes_every_other_key_inert() -> None:
    """The whole point: hold the hotkey during a game and nothing happens.
    Not "the recording is discarded" — it must never start."""
    spy = Spy()
    m = _pause_machine(spy)
    m.handle("down", VK_SCROLL, False)
    m.handle("up", VK_SCROLL, False)
    assert m.paused, "the pause key did not pause it"
    for vk in (VK_RCTRL, VK_F9, VK_LEFT, VK_C):
        m.handle("down", vk, False)
        m.handle("up", vk, False)
    assert spy.events == ["paused"], spy.events
    assert m.state == "idle", m.state


def test_the_pause_key_still_works_while_paused() -> None:
    """A key that only worked while it was listening could never turn
    listening back on."""
    spy = Spy()
    m = _pause_machine(spy)
    m.handle("down", VK_SCROLL, False)
    m.handle("up", VK_SCROLL, False)
    m.handle("down", VK_SCROLL, False)
    m.handle("up", VK_SCROLL, False)
    assert not m.paused, "the second press did not resume"
    assert spy.events == ["paused", "resumed"], spy.events
    m.handle("down", VK_RCTRL, False)
    m.handle("up", VK_RCTRL, False)
    assert spy.events[-2:] == ["start", "stop"], spy.events


def test_pause_swallows_nothing_and_ignores_autorepeat() -> None:
    spy = Spy()
    m = _pause_machine(spy)
    assert m.handle("down", VK_SCROLL, False) is False, \
        "the pause key must reach the app like any other key"
    for _ in range(4):
        m.handle("down", VK_SCROLL, False)      # Windows auto-repeat
    assert spy.events == ["paused"], spy.events


def test_pausing_mid_recording_throws_the_recording_away() -> None:
    """Pausing means stop listening. Transcribing the half sentence that
    was in flight and pasting it a moment later is the opposite."""
    spy = Spy()
    m = _pause_machine(spy)
    m.handle("down", VK_RCTRL, False)
    m.handle("down", VK_SCROLL, False)
    assert spy.events == ["start", "abort:paused mid-recording", "paused"], \
        spy.events
    assert m.state == "idle", m.state


def test_two_writers_cannot_delete_config_between_them() -> None:
    """One shared "config.toml.new" destroyed the real file: the cleanup
    path deletes the temp BY NAME, and a delete marked on a file another
    process is renaming onto config.toml follows it through the rename.
    Reproduced 4 runs of 4. Two writers is not exotic — every launch while
    an instance is running opens another dashboard, and each writes here."""
    import os
    import shutil
    tmp, path = _temp_config()
    try:
        staged: list[Path] = []
        real_replace = os.replace

        def spy(src, dst):
            staged.append(Path(src))
            return real_replace(src, dst)

        os.replace = spy
        try:
            config_mod.set_values(path, {"translate_hotkey": "p"})
        finally:
            os.replace = real_replace
        assert staged, "nothing was staged"
        assert str(os.getpid()) in staged[0].name, (
            f"the staging file {staged[0].name!r} is shared between "
            f"processes — two of them can delete config.toml")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_only_one_dashboard_can_be_open() -> None:
    """It sits behind a .vbs behind a shortcut, which has no notion of
    "already open" — so every double-click used to put another identical
    window on screen, each polling the same app and each able to change the
    same keys."""
    import os

    # A private name: taking the REAL dashboard mutex would fail whenever
    # the dashboard happens to be open, and taking the app's would fail
    # whenever dictation is running. Neither says anything about the code.
    name = rf"Local\HebrewDictation.test.{os.getpid()}.dash"
    assert singleton.DASHBOARD_MUTEX != singleton.MUTEX_NAME, \
        "the dashboard and the app would lock each other out"
    lock = singleton.InstanceLock(name)
    try:
        assert singleton.is_running(name)
        try:
            singleton.InstanceLock(name)
        except singleton.AlreadyRunning:
            pass
        else:
            raise AssertionError("a second dashboard was allowed")
    finally:
        lock.release()
    assert not singleton.is_running(name)


def test_a_second_launch_wakes_the_window_that_exists() -> None:
    """Refusing to open twice is only half of it — the click still has to
    do something, or the shortcut looks broken."""
    import os
    import time

    # Private again: a real dashboard on screen is waiting on the real
    # event, and an auto-reset event wakes exactly ONE waiter — so the live
    # window would eat the poke and this would fail for no reason.
    name = rf"Local\HebrewDictation.test.{os.getpid()}.show"
    show = singleton.Signal(name)
    try:
        woken: list = []
        watcher = threading.Thread(
            target=lambda: woken.append(show.wait(3000)), daemon=True)
        watcher.start()
        time.sleep(0.15)
        assert singleton.signal(name) is True
        watcher.join(timeout=4)
        assert woken == [True], woken
        # Auto-reset: one poke wakes it once, not forever.
        assert show.wait(200) is False, \
            "the event stayed signalled — the window would re-raise itself"
    finally:
        show.close()
    assert singleton.signal(name) is False, \
        "signalling with nothing listening must be a no-op, not a crash"


def test_the_window_carries_the_real_icon() -> None:
    """Tk's iconbitmap() reported success and left WM_GETICON returning 0
    on this machine, so the taskbar kept showing pythonw's generic icon.
    Both sizes are asserted: they are different frames of the .ico, drawn
    differently on purpose."""
    import ctypes

    import dashboard as dash

    assert (Path(__file__).resolve().parent / "icon.ico").exists(), \
        "icon.ico is missing — run make_icon.py"
    try:
        board = dash.Dashboard()
    except Exception as e:                      # no display: nothing to test
        print(f"    (skipped: no Tk window — {e})")
        return
    try:
        board.closing = True
        board.root.update_idletasks()
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        hwnd = (user32.GetParent(int(board.root.winfo_id()))
                or int(board.root.winfo_id()))
        WM_GETICON = 0x007F
        for which, label in ((1, "big"), (0, "small")):
            assert user32.SendMessageW(hwnd, WM_GETICON, which, 0), \
                f"the {label} window icon was never set"
        buf = ctypes.c_wchar_p()
        hr = ctypes.windll.shell32.GetCurrentProcessExplicitAppUserModelID(
            ctypes.byref(buf))
        assert hr == 0 and buf.value == dash.APP_ID, (hr, buf.value)
    finally:
        try:
            board.root.destroy()
        except Exception:
            pass


def test_the_key_dialog_always_undoes_its_own_pause() -> None:
    """It pauses the app to listen for a key. Closing the MAIN window
    destroys the dialog as a child WITHOUT running its close handler, so
    the resume has to be latched and honoured from there too — otherwise
    the app is left inert with no window anywhere saying so."""
    source = (Path(__file__).resolve().parent
              / "dashboard.py").read_text("utf-8")
    assert "_resume_after_capture" in source
    close_at = source.index("def _close(")
    tail = source[close_at:]
    assert "_resume_after_capture()" in tail, \
        "closing the window can strand the app paused"
    assert "self._paused_for_capture = True" in source, \
        "the pause must be latched, not re-derived from a stale status"


def test_the_dot_has_a_colour_for_every_state_the_app_sets() -> None:
    """set_state SILENTLY ignores a name it does not know, so a state added
    in main.py without one here leaves the dot showing the previous thing —
    a paused app that still reads as listening."""
    import re

    import overlay as overlay_mod

    source = (Path(__file__).resolve().parent / "main.py").read_text("utf-8")
    used = set(re.findall(r'_set_state\("(\w+)"\)', source))
    assert used, "no _set_state calls found — has it been renamed?"
    missing = used - set(overlay_mod.STATES)
    assert not missing, f"the dot has no colour for {sorted(missing)}"


def test_pause_from_the_dashboard_is_the_same_pause() -> None:
    spy = Spy()
    m = _pause_machine(spy)
    assert m.set_paused(True) is True
    assert m.set_paused(True) is False, "already paused is not a change"
    m.handle("down", VK_RCTRL, False)
    assert spy.events == ["paused"], spy.events
    assert m.set_paused(False) is True
    assert spy.events == ["paused", "resumed"], spy.events


def test_a_pause_key_cannot_double_as_another_key() -> None:
    spy = Spy()
    for vk, what in ((VK_RCTRL, "hotkey"), (VK_F9, "tap key"),
                     (VK_LEFT, "latch key")):
        try:
            _pause_machine(spy, pause_vk=vk)
        except ValueError as e:
            assert "two things" in str(e), e
        else:
            raise AssertionError(f"pause_vk on the {what} was accepted")


# ------------------------------------------------------ moving keys, live

def test_rebinding_moves_the_keys_without_a_restart() -> None:
    spy = Spy()
    m = _pause_machine(spy)
    m.rebind({VK_LCTRL: "he"}, taps={VK_F8: "correct"}, latch_vk=VK_LEFT,
             pause_vk=VK_SCROLL)
    m.handle("down", VK_RCTRL, False)          # the old key is just a key now
    m.handle("up", VK_RCTRL, False)
    assert spy.events == [], spy.events
    m.handle("down", VK_LCTRL, False)
    m.handle("up", VK_LCTRL, False)
    assert spy.events == ["start", "stop"], spy.events


def test_a_rejected_rebind_leaves_the_working_keys_working() -> None:
    """Validation happens before anything is assigned. Half-applied keys
    would be worse than a refusal — some of them would still fire."""
    spy = Spy()
    m = _pause_machine(spy)
    try:
        m.rebind({VK_RCTRL: "he"}, taps={VK_RCTRL: "translate"})
    except ValueError:
        pass
    else:
        raise AssertionError("one key meaning two things was accepted")
    m.handle("down", VK_RCTRL, False)
    m.handle("up", VK_RCTRL, False)
    assert spy.events == ["start", "stop"], spy.events


def test_rebinding_does_not_re_arm_a_tap_key_still_held() -> None:
    """A key is armed by its RELEASE, and a rebind is not a release.

    The dashboard's capture dialog rebinds the moment it has the key, and
    the finger is still on it: Windows keeps auto-repeating the key-down
    for as long as it is held. rebind() used to clear the whole
    "already fired" set, so every one of those repeats fired the action
    again — thirty a second, each one sending a Ctrl+A and a Ctrl+C into
    whatever had focus and asking Gemini a question. Holding the key must
    do nothing until it has been let go of.
    """
    keys = {parse_binding("ctrl+f8"): "correct"}
    spy = Spy()
    m = _pause_machine(spy)
    m.rebind({VK_RCTRL: "he"}, taps=keys, latch_vk=VK_LEFT,
             pause_vk=VK_SCROLL)
    m.handle("down", VK_LCTRL, False)
    m.handle("down", VK_F8, False)             # ctrl+f8 fires once
    assert spy.events == ["tap:correct"], spy.events
    spy.events.clear()

    # The dialog applies the change with the key still under the finger.
    m.rebind({VK_RCTRL: "he"}, taps=keys, latch_vk=VK_LEFT,
             pause_vk=VK_SCROLL)
    for _ in range(30):                        # Windows keeps repeating it
        m.handle("down", VK_F8, False)
    assert spy.events == [], \
        f"a rebind under a held key re-fired it: {spy.events}"

    m.handle("up", VK_F8, False)               # let go, and it works again
    m.handle("down", VK_F8, False)
    assert spy.events == ["tap:correct"], spy.events


def test_rebinding_mid_recording_discards_it() -> None:
    """The key it is recording under may not exist after the change, so
    there would be no key-up to end the recording."""
    spy = Spy()
    m = _pause_machine(spy)
    m.handle("down", VK_RCTRL, False)
    m.rebind({VK_LCTRL: "he"})
    assert spy.events == ["start", "abort:keys changed"], spy.events
    assert m.state == "idle", m.state


def test_tk_key_events_map_to_names_config_accepts() -> None:
    """The dashboard captures keys through Tk. The keycode is the virtual-
    key code and is what the hook matches on; the keysym is only consulted
    for the sided modifiers, and only when Windows has stopped answering."""
    from hotkey import key_name_from_event
    cases = [
        ("Control_R", 17, "right ctrl"),   # NOT "ctrl": the app's main key
        ("Control_L", 17, "left ctrl"),
        ("F9", 120, "f9"),
        ("Left", 37, "left"),
        ("Scroll_Lock", 145, "scroll lock"),
        ("p", 80, "p"),
        ("Escape", 27, "esc"),
    ]
    for keysym, keycode, expected in cases:
        got = key_name_from_event(keysym, keycode, probe=lambda vk: None)
        assert got == expected, f"{keysym}/{keycode} -> {got!r}"
        vk_for(got)                       # must round-trip back to a vk
    assert key_name_from_event("XF86AudioPlay", 0xB3,
                               probe=lambda vk: None) is None, \
        "a key with no name must be refused, not bound to something else"


def test_the_capture_dialog_waits_for_the_key_after_a_modifier() -> None:
    """The first key event of ctrl+F6 is the ctrl, and binding it would be
    worse than useless.

    "left ctrl" is a name check_hotkeys accepts as an ordinary bare key,
    so the dialog would have closed on it and every Ctrl+C the owner
    pressed afterwards would have fired the action. A modifier may only
    WAIT — and is still bindable on its own release, because that is how
    `hotkey = "right ctrl"` gets set, with the side read on the PRESS
    while GetAsyncKeyState still has something to answer.
    """
    import hotkey as hotkey_mod

    assert hotkey_mod.is_modifier_key(0xA2), "left ctrl is a modifier"
    assert hotkey_mod.is_modifier_key(0x5B), "the Windows key is one too"
    assert not hotkey_mod.is_modifier_key(0x75), "f6 is not a modifier"

    # What the dialog builds once the trigger arrives, with ctrl held.
    assert hotkey_mod.binding_name_from_event(
        "F6", 0x75, mods={0x11}) == "ctrl+f6"
    assert hotkey_mod.binding_name_from_event(
        "F6", 0x75, mods={0x11, 0x10}) == "ctrl+shift+f6"
    assert hotkey_mod.binding_name_from_event("F6", 0x75, mods=()) == "f6"

    # A modifier is returned bare and SIDED, never as half a chord.
    for keysym, keycode, want in (("Control_R", 0xA3, "right ctrl"),
                                  ("Control_L", 0xA2, "left ctrl")):
        got = hotkey_mod.binding_name_from_event(
            keysym, keycode, probe=lambda vk: vk == keycode, mods={0x11})
        assert got == want, f"{keysym} -> {got!r}"
        config_mod.check_hotkeys(dataclasses.replace(
            config_mod.load(Path(__file__).resolve().parent / "config.toml"),
            hotkey=want))          # the name it produces must be bindable


def test_a_hebrew_layout_cannot_change_which_key_gets_bound() -> None:
    """Measured while building the capture dialog: with a non-Latin layout
    active, Tk reports the physical P key as keysym "Arabic_lam". The
    keycode is still 0x50, and the keycode is what the hook matches."""
    from hotkey import key_name_from_event
    assert key_name_from_event("Arabic_lam", 0x50,
                               probe=lambda vk: None) == "p"
    assert key_name_from_event("??", 0x77, probe=lambda vk: None) == "f8"


def test_windows_decides_which_control_key_was_pressed() -> None:
    """Tk's keysym is a fallback, not the answer. A synthesised keycode-17
    event arrives as "Control_L" whichever key it stands for, so trusting
    it would bind the dictation key to the wrong side of the keyboard —
    silently, and only discovered by the hotkey no longer working."""
    from hotkey import key_name_from_event
    assert key_name_from_event("Control_L", 17,
                               probe=lambda vk: 0xA3) == "right ctrl"
    assert key_name_from_event("Control_R", 17,
                               probe=lambda vk: 0xA2) == "left ctrl"
    # Nothing held any more: fall back to whatever Tk thought.
    assert key_name_from_event("Control_R", 17,
                               probe=lambda vk: None) == "right ctrl"


def test_the_side_probe_reads_the_real_keyboard() -> None:
    """It must answer without raising for every modifier, and must not
    claim a key is down when it is not (nothing is held in a test run)."""
    from hotkey import side_down
    for vk in (0x10, 0x11, 0x12):
        assert side_down(vk) in (None, *{0x10: (0xA0, 0xA1),
                                         0x11: (0xA2, 0xA3),
                                         0x12: (0xA4, 0xA5)}[vk])
    assert side_down(0x70) is None, "F1 has no sides"


# ------------------------------------------- writing config.toml back out

def _temp_config():
    import shutil
    import tempfile
    tmp = Path(tempfile.mkdtemp(prefix="dictation-config-"))
    shutil.copy(Path(__file__).resolve().parent / "config.toml",
                tmp / "config.toml")
    return tmp, tmp / "config.toml"


def test_writing_a_key_keeps_every_comment() -> None:
    """config.toml is two thirds comments and most of them are measurements
    that cost hours. A TOML round trip would delete all of them."""
    import shutil
    tmp, path = _temp_config()
    try:
        before = path.read_text("utf-8")
        config_mod.set_values(path, {"translate_hotkey": "p"})
        after = path.read_text("utf-8")
        assert config_mod.load(path).translate_hotkey == "p"
        kept = [line for line in before.splitlines()
                if line.lstrip().startswith("#")]
        assert kept, "the sample config has no comments to protect"
        for line in kept:
            assert line in after, f"comment lost: {line[:60]}"
        assert before.count("\n") == after.count("\n"), "line count changed"
        # The trailing comment on the line that changed must survive too.
        for line in after.splitlines():
            if line.startswith("hotkey ="):
                assert "#" in line or "hold" not in before, line
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_a_write_that_would_not_load_never_replaces_the_file() -> None:
    """Clicking a key in a dashboard must not be able to produce a
    config.toml the next launch refuses — that failure is a message box at
    the moment someone wanted to dictate."""
    import shutil
    tmp, path = _temp_config()
    try:
        before = path.read_text("utf-8")
        try:
            config_mod.set_values(path, {"hotkey": "not a real key"})
        except config_mod.ConfigError:
            pass
        else:
            raise AssertionError("an unknown key name was written")
        assert path.read_text("utf-8") == before, "the file was modified"
        # Glob, not a fixed name: the staging file carries the pid, because
        # a shared one lets two writers delete config.toml between them.
        assert not list(tmp.glob("config.toml.*.new")), "temp file left behind"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_a_setting_that_is_missing_is_added_next_to_the_others() -> None:
    """An older config.toml has no pause_hotkey line at all."""
    import shutil
    tmp, path = _temp_config()
    try:
        text = "\n".join(line for line in path.read_text("utf-8").splitlines()
                         if not line.startswith("pause_hotkey"))
        path.write_text(text, "utf-8")
        config_mod.set_values(path, {"pause_hotkey": "pause"})
        assert config_mod.load(path).pause_hotkey == "pause"
        lines = path.read_text("utf-8").splitlines()
        added = next(i for i, line in enumerate(lines)
                     if line.startswith("pause_hotkey"))
        first_table = next(i for i, line in enumerate(lines)
                           if line.lstrip().startswith("["))
        assert added < first_table, "it landed inside a [table]"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_a_hash_inside_a_value_is_not_read_as_a_comment() -> None:
    import shutil
    tmp, path = _temp_config()
    try:
        config_mod.set_values(path, {"paste_chord": "shift+insert"})
        text = path.read_text("utf-8")
        assert 'paste_chord = "shift+insert"' in text, text[:400]
        assert config_mod.load(path).paste_chord == "shift+insert"
        # A value containing a '#' must survive being rewritten later.
        path.write_text(text.replace('placeholder = "..."',
                                     'placeholder = "#"'), "utf-8")
        config_mod.set_values(path, {"min_seconds": 0.4})
        assert config_mod.load(path).feedback.placeholder == "#"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_colliding_keys_are_refused_before_they_are_written() -> None:
    import dataclasses
    cfg = config_mod.load(Path(__file__).resolve().parent / "config.toml")
    try:
        config_mod.check_hotkeys(
            dataclasses.replace(cfg, correct_hotkey=cfg.hotkey))
    except config_mod.ConfigError as e:
        assert "two things" in str(e), e
    else:
        raise AssertionError("two settings on one key were accepted")


def test_the_real_config_names_keys_the_app_can_bind() -> None:
    """Every key in the shipped config resolves to a virtual-key code, and
    the pause key is one of them (it is what makes gaming survivable).

    The uniqueness half of this has to be spelled out since chords
    arrived. Taps are keyed by Binding now, and a Binding never equals an
    int, so the old `set(hotkeys) | set(taps)` could not collide however
    badly the config was written — it would have passed while the app
    refused to start. Compared on triggers instead, with the one rule
    chords actually changed: two taps MAY share a trigger if their
    modifiers differ (the shipped f8 / ctrl+f8 pair), but nothing may
    share a trigger with a key that is tested before the taps are.
    """
    import main as main_mod
    cfg = config_mod.load(Path(__file__).resolve().parent / "config.toml")
    hotkeys, taps, latch_vk, pause_vk = main_mod.App.bindings(cfg)
    assert hotkeys and pause_vk is not None, (hotkeys, pause_vk)
    names = [hotkey_mod.binding_name(b) for b in taps]
    assert len(set(names)) == len(names), f"two taps are one key: {names}"
    triggers = {b.trigger for b in taps}
    first = set(hotkeys) | {latch_vk, pause_vk}
    assert len(first) == len(hotkeys) + 2, "two settings share a key"
    assert not (triggers & first), \
        f"a tap sits on a key tested before it: {triggers & first}"


# ----------------------------------------------- the dashboard's channel

def test_the_control_channel_answers_and_survives_a_bad_request() -> None:
    import control

    seen = []

    def handler(command, args):
        seen.append((command, args))
        if command == "boom":
            raise RuntimeError("handler exploded")
        return {"ok": True, "echo": args.get("value")}

    restore = _private_pipe(control, "roundtrip")
    server = control.ControlServer(handler)
    assert server.start(), "the control channel did not come up"
    try:
        assert control.send("status", value="שלום") == \
            {"ok": True, "echo": "שלום"}, "unicode did not survive the pipe"
        bad = control.send("boom")
        assert bad and bad.get("ok") is False, bad
        # ...and it is still serving afterwards.
        assert control.send("status", value=2) == {"ok": True, "echo": 2}
        # Asked BEFORE restore(), and that is the point: afterwards
        # PIPE_NAME is the real one again, so a Hebrew Dictation that
        # happens to be RUNNING answers it and this fails for a reason
        # that has nothing to do with the control channel. stop() is
        # idempotent, so the finally below still runs it.
        server.stop()
        assert control.send("status", timeout_ms=200) is None, \
            "the pipe still answers after stop()"
    finally:
        server.stop()
        restore()

    assert [c for c, _ in seen] == ["status", "boom", "status"], seen


def _private_pipe(control, label: str):
    """Point control.py at a pipe name nobody else uses, for the duration.

    Without this these tests talk to the REAL running app: they take the
    production pipe name, and whichever server answers first wins. They
    passed only while dictation happened to be stopped, which is the worst
    kind of test — one that reports on the machine's mood.
    """
    import os
    original = control.PIPE_NAME
    control.PIPE_NAME = rf"\\.\pipe\HebrewDictation.test.{os.getpid()}.{label}"
    return lambda: setattr(control, "PIPE_NAME", original)


def test_a_reply_bigger_than_the_pipe_buffer_survives() -> None:
    """ReadFile RETURNS ERROR_MORE_DATA instead of raising, so dropping it
    truncates a long reply into invalid JSON — and the caller's blanket
    except then reports a perfectly healthy app as "nothing is listening",
    which the dashboard shows as "stop and restart it"."""
    import control

    big = "ש" * 60_000                       # 2 bytes each: ~120 KB of JSON
    restore = _private_pipe(control, "big")
    server = control.ControlServer(lambda c, a: {"ok": True, "text": big})
    assert server.start()
    try:
        reply = control.send("status", timeout_ms=4000)
        assert reply is not None, "an oversized reply was read as 'not running'"
        assert reply["text"] == big, len(reply.get("text", ""))
    finally:
        server.stop()
        restore()


def test_a_command_is_not_lost_to_the_status_poller() -> None:
    """The dashboard always has two clients — the poller every 800 ms and a
    thread per button press. The server takes one at a time, so the loser
    gets ERROR_PIPE_BUSY from CreateFile, which is a different failure from
    "no pipe" and needs the same retry. A lost 'pause' is not cosmetic: it
    leaves the hook live while the key-capture window is open."""
    import control

    restore = _private_pipe(control, "busy")
    server = control.ControlServer(lambda c, a: {"ok": True, "cmd": c})
    assert server.start()
    results: list = []
    try:
        def hammer(name: str) -> None:
            for _ in range(25):
                results.append(control.send(name, timeout_ms=2000))

        threads = [threading.Thread(target=hammer, args=(n,))
                   for n in ("status", "pause", "status")]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=60)
    finally:
        server.stop()
        restore()
    lost = [r for r in results if r is None]
    assert len(results) == 75, len(results)
    assert not lost, f"{len(lost)} of {len(results)} commands were dropped"


def test_stop_works_during_the_model_loading_window() -> None:
    """The mutex is taken first and the quit event must be taken with it.
    Created after the models load instead, every Stop for those ~25 s is a
    silent no-op: the dashboard enables the button (the mutex says an
    instance exists), says "nothing to stop", and the app comes up behind
    it with the hotkey live."""
    import re

    source = (Path(__file__).resolve().parent / "main.py").read_text("utf-8")
    lock_at = source.index("lock = singleton.InstanceLock()")
    event_at = source.index("quit_signal = singleton.QuitSignal()")
    app_at = source.index("app = App(cfg, config_path=")
    assert lock_at < event_at < app_at, (
        "the quit event must be created between taking the mutex and "
        "loading the models — request_quit() is OpenEventW and fails "
        "outright until it exists")
    assert re.search(r"if quit_signal\.is_set\(\)", source), (
        "a stop requested during startup must be honoured before the "
        "hook goes in")


def test_a_quit_asked_for_before_the_wait_is_not_missed() -> None:
    """Under a PRIVATE event name. This test used to create and signal the
    REAL quit event — which a running instance is waiting on — so running
    the suite stopped the app mid-session. Twice observed live."""
    original = singleton.QUIT_EVENT_NAME
    singleton.QUIT_EVENT_NAME = r"Local\HebrewDictation.selftest.quit2"
    signal = None
    try:
        signal = singleton.QuitSignal()
        assert signal.is_set() is False
        assert singleton.request_quit() is True
        assert signal.is_set() is True, \
            "a quit sent before wait() was called would be lost"
    finally:
        if signal is not None:
            signal.close()
        singleton.QUIT_EVENT_NAME = original


def test_nothing_listening_is_not_the_same_as_a_refusal() -> None:
    """None and {"ok": False} mean different things to the dashboard: one
    sends someone to the Start button, the other shows them a reason."""
    import control
    restore = _private_pipe(control, "silent")
    try:
        assert control.send("status", timeout_ms=200) is None
    finally:
        restore()


# ------------------------------------------ the correction key's feedback

def _cue_spy(main_mod):
    played: list[str] = []
    real = main_mod.beep
    main_mod.beep = played.append
    return played, (lambda: setattr(main_mod, "beep", real))


def test_repeated_correction_failures_do_not_pile_up_cues() -> None:
    """Measured in app.log on 2026-08-14: nine presses in five seconds, all
    failing for the same reason, nine error cues. Heard as one long fault
    rather than as nine identical answers — the "tu-tu-tu"."""
    import shutil
    import tempfile

    import main as main_mod

    tmp = Path(tempfile.mkdtemp(prefix="dictation-cues-"))
    fake = _FakeInjector()
    real_inj = main_mod.injector
    played, restore = _cue_spy(main_mod)
    try:
        main_mod.injector = fake
        app = _worker_app(_Flaky(fail_times=0), tmp)
        last = {"final": "תריץ את xpogo בבקשה עכשיו", "raw": "", "wav": ""}
        # The text was sent, so the field holds something else entirely.
        fake.on_screen = "def main():\n    return unrelated_code"
        for _ in range(9):
            app._correct(dict(last), hwnd=fake.focus)
        assert len(app.vocab) == 0, app.vocab.corrections
        assert played == ["noop"], played
    finally:
        restore()
        main_mod.injector = real_inj
        shutil.rmtree(tmp, ignore_errors=True)


def test_a_failed_correction_is_not_reported_as_an_error() -> None:
    """Pressing the key when the text has already been sent is a normal
    thing to do, not a fault, and must not sound like one."""
    import shutil
    import tempfile

    import main as main_mod

    tmp = Path(tempfile.mkdtemp(prefix="dictation-noop-"))
    fake = _FakeInjector()
    real_inj = main_mod.injector
    played, restore = _cue_spy(main_mod)
    try:
        main_mod.injector = fake
        app = _worker_app(_Flaky(fail_times=0), tmp)
        fake.on_screen = ""            # sent: the box is empty now
        app._correct({"final": "תריץ את xpogo", "raw": "", "wav": ""},
                     hwnd=fake.focus)
        assert played == ["noop"], played
        assert "no text where the cursor is" in app._note, app._note
    finally:
        restore()
        main_mod.injector = real_inj
        shutil.rmtree(tmp, ignore_errors=True)


def test_the_translate_key_does_not_pile_up_cues_either() -> None:
    """Same defect one key over: tapping F9 on text that is already English
    used to fire the error cue every time."""
    import shutil
    import tempfile

    import main as main_mod

    tmp = Path(tempfile.mkdtemp(prefix="dictation-f9-"))
    fake = _FakeInjector()
    real_inj = main_mod.injector
    played, restore = _cue_spy(main_mod)
    try:
        main_mod.injector = fake
        app = _worker_app(_Flaky(fail_times=0), tmp)
        app._translator = object()      # must never be reached
        fake.on_screen = "this sentence is already in English"
        for _ in range(6):
            app._translate(fake.focus)
        assert played == ["noop"], played
        assert "already English" in app._note, app._note
    finally:
        restore()
        main_mod.injector = real_inj
        shutil.rmtree(tmp, ignore_errors=True)


def test_one_edit_is_not_learned_twice() -> None:
    """Observed in app.log on 2026-08-14: the same correction learned at
    21:13:44 and again at 21:14:29 from ONE edit, because the app still
    believed it had produced the unfixed text. Two hits is the threshold at
    which a garble starts being repaired automatically, so a single fix was
    confirming itself."""
    import shutil
    import tempfile

    import main as main_mod

    tmp = Path(tempfile.mkdtemp(prefix="dictation-twice-"))
    fake = _FakeInjector()
    real_inj = main_mod.injector
    try:
        main_mod.injector = fake
        app = _worker_app(_Flaky(fail_times=0), tmp)
        shown = "תריץ את xpogo בבקשה"
        app._last = {"final": shown, "raw": shown, "wav": ""}
        fake.on_screen = "תריץ את Expo Go בבקשה"
        for _ in range(3):             # the key pressed again, and again
            app._correct(dict(app._last), hwnd=fake.focus)
        hits = [int(c.get("hits", 1)) for c in app.vocab.corrections]
        assert hits == [1], f"one edit counted {hits} times"
    finally:
        main_mod.injector = real_inj
        shutil.rmtree(tmp, ignore_errors=True)


# ------------------------------------------------------ the punctuate key
#
# The guard is the whole feature. This key REPLACES text the user is about
# to send, on a model's say-so, so "it only added punctuation" cannot be a
# hope — it has to be a check, and these are the cases that check has to
# get right.

def test_punctuation_that_only_adds_marks_is_accepted() -> None:
    import punctuate as punctuate_mod

    before = "תוסיף עוד עיר לאפליקציה ואז תריץ את זה מחדש מה דעתך"
    after = "תוסיף עוד עיר לאפליקציה, ואז תריץ את זה מחדש. מה דעתך?"
    ok, why = punctuate_mod.is_safe(before, after)
    assert ok, why


def test_line_breaks_and_brackets_are_punctuation_too() -> None:
    """Breaking a dictated wall of words into lines is the point, not a
    violation — whitespace has to drop out of the comparison with the
    commas."""
    import punctuate as punctuate_mod

    before = "קודם תעשה commit ואז deploy אחר כך תבדוק את הלוג"
    after = "קודם תעשה commit,\nואז deploy.\nאחר כך תבדוק את הלוג (!)"
    ok, why = punctuate_mod.is_safe(before, after)
    assert ok, why


def test_nikud_passes_the_same_guard() -> None:
    """Hebrew points are combining marks, so str.isalnum() is False for
    them and they fall out of the letters-only comparison exactly like a
    comma does. That is what lets punctuate.nikud = true reuse the guard
    instead of needing a second, weaker one."""
    import punctuate as punctuate_mod

    ok, why = punctuate_mod.is_safe("שלום עולם", "שָׁלוֹם עוֹלָם.")
    assert ok, why


def test_a_swapped_word_is_rejected_and_named() -> None:
    """The failure this exists for: a model that decided to 'improve' a
    word while it was in there. The reason has to name the word, or the
    log line is a verdict with no evidence behind it."""
    import punctuate as punctuate_mod

    before = "המקלדת מסתירה את השדה"
    after = "הלוח מסתיר את השדה."
    ok, why = punctuate_mod.is_safe(before, after)
    assert not ok
    assert "המקלדת" in why, why


def test_added_and_dropped_words_are_both_rejected() -> None:
    import punctuate as punctuate_mod

    before = "תריץ את זה שוב"
    grown = "תריץ את זה שוב, בבקשה."
    shrunk = "תריץ את זה."
    for candidate in (grown, shrunk):
        ok, why = punctuate_mod.is_safe(before, candidate)
        assert not ok, f"accepted {candidate!r}"
        assert "words changed" in why, why


def test_a_model_that_answers_the_text_is_rejected() -> None:
    """These dictations are prompts for a coding assistant, so they are full
    of imperatives. A model that obeys one instead of punctuating it must
    not reach the user's screen."""
    import punctuate as punctuate_mod

    before = "תמחק את הבranch הישן"
    after = "Sure! I have deleted the old branch for you."
    ok, why = punctuate_mod.is_safe(before, after)
    assert not ok, why


def test_an_empty_reply_is_rejected() -> None:
    import punctuate as punctuate_mod

    ok, _ = punctuate_mod.is_safe("שלום עולם", "   ")
    assert not ok


class _FakePunctuateBackend:
    def __init__(self, name, reply=None, error=None):
        self.name, self._reply, self._error = name, reply, error
        self.calls = 0

    def translate(self, text):
        self.calls += 1
        if self._error is not None:
            raise self._error
        return self._reply


def _punctuator(*backends):
    import punctuate as punctuate_mod

    p = punctuate_mod.Punctuator.__new__(punctuate_mod.Punctuator)
    p._backends = lambda: iter(backends)
    return p


def test_an_unsafe_reply_falls_through_to_the_other_backend() -> None:
    """Losing the press because the first model misbehaved would be a worse
    answer than asking the second one — this is a key someone pressed, not
    a pass running on its own."""
    good = "תריץ את זה שוב, בבקשה."
    first = _FakePunctuateBackend("gemini", reply="Sure, running it now!")
    second = _FakePunctuateBackend("ollama", reply=good)
    text, backend = _punctuator(first, second).punctuate("תריץ את זה שוב בבקשה")
    assert (text, backend) == (good, "ollama"), (text, backend)


def test_when_every_backend_rewrites_it_the_text_is_not_touched() -> None:
    import punctuate as punctuate_mod

    first = _FakePunctuateBackend("gemini", reply="something else entirely")
    second = _FakePunctuateBackend("ollama", reply="and something else again")
    try:
        _punctuator(first, second).punctuate("תריץ את זה שוב בבקשה")
    except punctuate_mod.UnsafeReply as e:
        assert "words changed" in str(e), e
    else:
        raise AssertionError("an unsafe reply was returned to the caller")


def test_a_backend_failure_is_not_reported_as_an_unsafe_reply() -> None:
    """Two different things to tell the user: 'Ollama is not running' sends
    them to start it, 'it rewrote your words' does not."""
    import punctuate as punctuate_mod
    from transcribers.base import TranscriptionError

    dead = _FakePunctuateBackend("gemini",
                                 error=TranscriptionError("no key"))
    also_dead = _FakePunctuateBackend(
        "ollama", error=TranscriptionError("cannot reach Ollama"))
    try:
        _punctuator(dead, also_dead).punctuate("שלום עולם")
    except punctuate_mod.UnsafeReply as e:
        raise AssertionError(f"a dead backend reported as unsafe: {e}")
    except TranscriptionError as e:
        assert "Ollama" in str(e), e
    else:
        raise AssertionError("expected the failure to reach the caller")


def test_prefer_ollama_reverses_the_backend_order() -> None:
    """The knob that exists because this key can be tapped after every
    dictation, and the free tier is 20 requests/day/model."""
    import dataclasses

    import punctuate as punctuate_mod

    cfg = config_mod.load(Path(__file__).resolve().parent / "config.toml")
    for prefer, expected in (("gemini", "gemini"), ("ollama", "ollama")):
        p = punctuate_mod.Punctuator(
            dataclasses.replace(
                cfg, punctuate=dataclasses.replace(cfg.punctuate,
                                                   prefer=prefer)))
        p._gemini_backend = lambda: _FakePunctuateBackend("gemini")
        p._ollama_backend = lambda: _FakePunctuateBackend("ollama")
        first = next(iter(p._backends()))
        assert first.name == expected, (prefer, first.name)


def _punctuate_app(tmp, fake_injector, reply):
    """An app whose punctuator is a fixed answer — the paste DECISIONS are
    what these tests are about, not the model."""
    import main as main_mod

    app = _worker_app(_Flaky(fail_times=0), tmp)
    main_mod.injector = fake_injector

    class _Fixed:
        def punctuate(self, text):
            if isinstance(reply, Exception):
                raise reply
            return reply, "fake"

    app._punctuator = _Fixed()
    return app


def test_the_punctuate_key_replaces_the_text_in_place() -> None:
    import shutil
    import tempfile

    import main as main_mod

    tmp = Path(tempfile.mkdtemp(prefix="dictation-punct-"))
    fake = _FakeInjector()
    real_inj = main_mod.injector
    played, restore = _cue_spy(main_mod)
    try:
        fixed = "תוסיף עוד עיר, ואז תריץ מחדש. מה דעתך?"
        app = _punctuate_app(tmp, fake, fixed)
        fake.on_screen = "תוסיף עוד עיר ואז תריץ מחדש מה דעתך"
        app._punctuate(fake.focus)
        pasted = [c for c in fake.calls if c[0] == "paste"]
        assert pasted == [("paste", fixed)], fake.calls
        assert played == ["punctuating", "punctuated"], played
        assert app._stats["punctuations"] == 1, app._stats
        # The clipboard is the user's, not ours, however this went.
        assert ("restore", "whatever the user had") in fake.calls, fake.calls
    finally:
        restore()
        main_mod.injector = real_inj
        shutil.rmtree(tmp, ignore_errors=True)


def test_a_copy_taken_while_the_key_worked_survives_its_restore() -> None:
    """The other half of injector.claim_mark(), from main.py's side.

    This pair is open for as long as the model takes — 1-3 s warm, 25 s
    cold — and the lookup box is on screen and copyable the whole time.
    So the key has to take the mark WITH the snapshot and hand it to the
    restore; taking it later, or not at all, is the version that puts the
    user's old clipboard back over the copy they just made and says
    nothing. Asserted through _punctuate because it is the longest of the
    three pairs, and the shape is identical in _translate and _correct.
    """
    import shutil
    import tempfile

    import main as main_mod

    tmp = Path(tempfile.mkdtemp(prefix="dictation-punct-copy-"))
    fake = _FakeInjector()
    real_inj = main_mod.injector
    played, restore = _cue_spy(main_mod)
    try:
        fixed = "תוסיף עוד עיר, ואז תריץ מחדש. מה דעתך?"
        app = _punctuate_app(tmp, fake, fixed)

        class _CopiesWhileItThinks:
            """The user reading the box, and pressing its copy button."""

            def punctuate(self, text):
                fake.set_text("מה שהתיבה העתיקה")
                return fixed, "fake"

        app._punctuator = _CopiesWhileItThinks()
        fake.on_screen = "תוסיף עוד עיר ואז תריץ מחדש מה דעתך"
        app._punctuate(fake.focus)

        assert ("kept", "a copy was taken meanwhile") in fake.calls, \
            fake.calls
        assert ("restore", "whatever the user had") not in fake.calls, \
            "the restore put the old clipboard back over the user's copy"
        # ...and the key still did its job around it.
        assert [c for c in fake.calls if c[0] == "paste"] == \
            [("paste", fixed)], fake.calls
        assert played == ["punctuating", "punctuated"], played
    finally:
        restore()
        main_mod.injector = real_inj
        shutil.rmtree(tmp, ignore_errors=True)


def test_an_unsafe_reply_never_reaches_the_screen() -> None:
    """The one that matters: when the guard fires, the text the user was
    about to send is still exactly the text they dictated."""
    import shutil
    import tempfile

    import main as main_mod
    import punctuate as punctuate_mod

    tmp = Path(tempfile.mkdtemp(prefix="dictation-unsafe-"))
    fake = _FakeInjector()
    real_inj = main_mod.injector
    played, restore = _cue_spy(main_mod)
    try:
        app = _punctuate_app(
            tmp, fake,
            punctuate_mod.UnsafeReply("the words changed: א -> ב"))
        fake.on_screen = "תוסיף עוד עיר ואז תריץ מחדש"
        app._punctuate(fake.focus)
        assert not [c for c in fake.calls if c[0] == "paste"], fake.calls
        assert played == ["punctuating", "error"], played
        assert "rewrote your words" in app._note, app._note
        assert app._stats["punctuations"] == 0, app._stats
    finally:
        restore()
        main_mod.injector = real_inj
        shutil.rmtree(tmp, ignore_errors=True)


def test_an_already_punctuated_field_is_left_alone_quietly() -> None:
    """Pressing the key on text that needs nothing is a normal thing to do
    and must not sound like a fault — nor paste an identical string over a
    selection, which costs an undo step for no change."""
    import shutil
    import tempfile

    import main as main_mod

    tmp = Path(tempfile.mkdtemp(prefix="dictation-same-"))
    fake = _FakeInjector()
    real_inj = main_mod.injector
    played, restore = _cue_spy(main_mod)
    try:
        same = "כבר יש כאן פיסוק, והכל בסדר."
        app = _punctuate_app(tmp, fake, same)
        fake.on_screen = same
        for _ in range(5):
            app._punctuate(fake.focus)
        assert not [c for c in fake.calls if c[0] == "paste"], fake.calls
        # One "nothing changed" answer, not five: the same reason repeating
        # is one answer to one question. The working cue is per press,
        # because a request really was sent each time.
        assert played.count("noop") == 1, played
        assert played.count("punctuating") == 5, played
    finally:
        restore()
        main_mod.injector = real_inj
        shutil.rmtree(tmp, ignore_errors=True)


def test_the_punctuate_key_does_not_pile_up_cues_either() -> None:
    """Same defect a third key over: pressing it where there is no text
    used to be worth one cue per press."""
    import shutil
    import tempfile

    import main as main_mod

    tmp = Path(tempfile.mkdtemp(prefix="dictation-f7-"))
    fake = _FakeInjector()
    real_inj = main_mod.injector
    played, restore = _cue_spy(main_mod)
    try:
        app = _punctuate_app(tmp, fake, "never reached")
        fake.on_screen = ""            # nothing where the cursor is
        for _ in range(6):
            app._punctuate(fake.focus)
        assert played == ["noop"], played
        assert "is empty" in app._note, app._note
    finally:
        restore()
        main_mod.injector = real_inj
        shutil.rmtree(tmp, ignore_errors=True)


def test_a_whole_document_is_refused_rather_than_rewritten() -> None:
    import shutil
    import tempfile

    import main as main_mod

    tmp = Path(tempfile.mkdtemp(prefix="dictation-big-"))
    fake = _FakeInjector()
    real_inj = main_mod.injector
    played, restore = _cue_spy(main_mod)
    try:
        app = _punctuate_app(tmp, fake, "never reached")
        fake.on_screen = "מילה " * (app.cfg.punctuate.max_chars // 2)
        app._punctuate(fake.focus)
        assert not [c for c in fake.calls if c[0] == "paste"], fake.calls
        assert played == ["error"], played
        assert "too much to punctuate" in app._note, app._note
    finally:
        restore()
        main_mod.injector = real_inj
        shutil.rmtree(tmp, ignore_errors=True)


def test_the_two_text_keys_take_turns() -> None:
    """Both work by copying the selection out and pasting a replacement
    back, and there is one clipboard and one focused window. A second press
    while one is in flight has to be dropped, whichever key it was."""
    import shutil
    import tempfile

    import main as main_mod

    tmp = Path(tempfile.mkdtemp(prefix="dictation-turns-"))
    fake = _FakeInjector()
    real_inj = main_mod.injector
    try:
        main_mod.injector = fake
        app = _worker_app(_Flaky(fail_times=0), tmp)
        app._on_tap("translate")
        app._on_tap("punctuate")       # while the first is still queued
        assert app.text_queue.qsize() == 1, app.text_queue.qsize()
        assert app.text_queue.get() == ("translate", fake.focus)
        app._text_busy.clear()         # the worker finished
        app._on_tap("punctuate")
        assert app.text_queue.get() == ("punctuate", fake.focus)
    finally:
        main_mod.injector = real_inj
        shutil.rmtree(tmp, ignore_errors=True)


def test_the_punctuate_key_is_a_tap_the_state_machine_knows() -> None:
    """The binding table is derived in one place (App.bindings) so that
    adding a key cannot leave the hook behind."""
    import dataclasses

    import main as main_mod

    cfg = config_mod.load(Path(__file__).resolve().parent / "config.toml")
    cfg = dataclasses.replace(cfg, punctuate_hotkey="f7",
                              translate_hotkey="f9")
    _hotkeys, taps, _latch, _pause = main_mod.App.bindings(cfg)
    # Keyed by Binding since chords arrived: parse_binding("f7") is the
    # bare-key Binding, and it must be the SAME key the config produced.
    assert taps[parse_binding("f7")] == "punctuate", taps
    assert taps[parse_binding("f9")] == "translate", taps


def test_punctuate_hotkey_must_not_collide() -> None:
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "config.toml"
        # english_hotkey pinned off: its dataclass default is "f9", and an
        # unset one would collide first and prove the wrong thing.
        p.write_text('hotkey = "right ctrl"\nenglish_hotkey = ""\n'
                     'translate_hotkey = "f9"\npunctuate_hotkey = "f9"\n',
                     "utf-8")
        try:
            config_mod.load(p)
        except config_mod.ConfigError as e:
            assert "punctuate_hotkey" in str(e), e
        else:
            raise AssertionError("expected ConfigError on a colliding key")


def test_a_misspelled_prefer_is_refused_at_load() -> None:
    """Silently meaning "gemini" would send every request to a model the
    user thought they had switched away from."""
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "config.toml"
        p.write_text('hotkey = "right ctrl"\n[punctuate]\nprefer = "gemma"\n',
                     "utf-8")
        try:
            config_mod.load(p)
        except config_mod.ConfigError as e:
            assert "prefer" in str(e), e
        else:
            raise AssertionError("expected ConfigError on a bad prefer")


def test_the_dashboard_lists_the_punctuate_key() -> None:
    """The dashboard, the live rebind and the validation all read
    HOTKEY_FIELDS, so this is the one place a new key has to be added — and
    the one place a test can prove it was."""
    fields = dict(config_mod.HOTKEY_FIELDS)
    assert "punctuate_hotkey" in fields, fields
    assert fields["punctuate_hotkey"], "the row would have no label"


def test_the_punctuate_key_can_be_rebound_and_written_back() -> None:
    import shutil
    tmp, path = _temp_config()
    try:
        # f12 and not f6: the lookup key took f6, and the loader refuses a
        # config where one key means two things. Any free key proves the
        # round trip; this test is about the write-back, not the letter.
        config_mod.set_values(path, {"punctuate_hotkey": "f12"})
        assert config_mod.load(path).punctuate_hotkey == "f12"
        config_mod.set_values(path, {"punctuate_hotkey": ""})
        assert config_mod.load(path).punctuate_hotkey == ""
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_every_cue_the_punctuate_key_plays_exists() -> None:
    """beep() with an unknown kind is silent, and a key whose only feedback
    is a sound it never plays is a key that looks broken."""
    import cues
    for kind in ("punctuating", "punctuated", "noop", "error", "stop",
                 # The context pass rewrites text already on screen without
                 # being asked, so it must not borrow "noop" — that note
                 # means "nothing to do" everywhere else in the app.
                 "repaired"):
        assert kind in cues.CUES, kind



# --------------------------------------------------------- the lookup key
#
# This key is defined by what it does NOT do. It never selects, never
# pastes, never types, and gives the clipboard back byte for byte — so
# most of what follows is a test that something did not happen. The pixels
# are the one part that cannot be checked from here: whether a Hebrew
# reader would call the box correct was answered by photographing it
# (2026-08-19, four samples, including a Latin-first mixed sentence whose
# subject and object a naive direction guess inverts).

def test_the_dashboard_lists_the_lookup_key() -> None:
    """Same reason as the punctuate row: HOTKEY_FIELDS is the one place a
    new key has to be added, and the one place a test can prove it was."""
    fields = dict(config_mod.HOTKEY_FIELDS)
    assert "lookup_hotkey" in fields, fields
    assert fields["lookup_hotkey"], "the row would have no label"


def test_the_lookup_key_is_a_tap_the_state_machine_knows() -> None:
    import dataclasses

    import main as main_mod

    cfg = config_mod.load(Path(__file__).resolve().parent / "config.toml")
    cfg = dataclasses.replace(cfg, lookup_hotkey="f6")
    _hotkeys, taps, _latch, _pause = main_mod.App.bindings(cfg)
    assert taps[parse_binding("f6")] == "lookup", taps
    # _popup_key is handed a raw vk by the hook and compares it against
    # this, so the trigger has to come back out of the Binding too.
    assert main_mod.App._vk_of(taps, "lookup") == vk_for("f6"), taps


def test_lookup_hotkey_must_not_collide() -> None:
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "config.toml"
        p.write_text('hotkey = "right ctrl"\nenglish_hotkey = ""\n'
                     'translate_hotkey = "f9"\nlookup_hotkey = "f9"\n',
                     "utf-8")
        try:
            config_mod.load(p)
        except config_mod.ConfigError as e:
            assert "lookup_hotkey" in str(e), e
        else:
            raise AssertionError("expected ConfigError on a colliding key")


def test_the_lookup_key_can_be_rebound_and_written_back() -> None:
    import shutil
    tmp, path = _temp_config()
    try:
        config_mod.set_values(path, {"lookup_hotkey": "f12"})
        assert config_mod.load(path).lookup_hotkey == "f12"
        config_mod.set_values(path, {"lookup_hotkey": ""})
        assert config_mod.load(path).lookup_hotkey == ""
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_every_cue_the_lookup_key_plays_exists() -> None:
    """beep() with an unknown kind is silent, and a key whose only feedback
    is a sound it never plays is a key that looks broken."""
    import cues
    for kind in ("looking", "looked", "noop", "error"):
        assert kind in cues.CUES, kind


def test_the_lookup_key_never_selects_and_never_writes() -> None:
    """The guarantee the whole design rests on. grab() falls back to
    select-all when a copy comes up empty, and for F9 and F7 that is right
    — they paste over the result a moment later. This key never pastes, so
    the same fallback would leave the user's field fully selected with
    their next keystroke about to wipe it, and would not even be looking up
    what they meant: measured, it takes 188 chars of a web page and 11914
    of terminal scrollback. Grepped rather than mocked, in the style of the
    mainloop/quit grep above."""
    import inspect

    import main as main_mod

    body = inspect.getsource(main_mod.App._lookup)
    body += inspect.getsource(injector.read_selection)
    for forbidden in ("select_all_chord", "paste_text", "injector.inject",
                      "set_text", "send_key_times"):
        assert forbidden not in body, forbidden


def test_the_lookup_direction_counts_words_not_letters() -> None:
    """'תעשה commit לפני ה-merge' is 9 Hebrew letters against 11 Latin, so
    a letter count calls Hebrew prose English and answers it in the
    language it was already in. Hebrew is written without vowels, which
    makes words the only fair unit."""
    import lookup as lookup_mod

    mixed = "תעשה commit לפני ה-merge"
    assert lookup_mod.classify(mixed).target == "English", mixed
    assert lookup_mod.classify("brittle").target == "Hebrew"
    assert lookup_mod.classify("שלום עולם").target == "English"


def test_a_refused_lookup_spends_nothing() -> None:
    """Four different nothings, told apart on purpose: one note for all of
    them would teach nobody why the box did not appear. None of these
    reaches a backend at all."""
    import lookup as lookup_mod

    cases = [
        ("", "nothing-selected"),
        ("   ", "nothing-selected"),
        ("https://example.com/a/b", "nothing-to-translate"),
        ("1234 56.7 %", "nothing-to-translate"),
        ("x" * 6000, "too-much"),
    ]
    for text, reason in cases:
        got = lookup_mod.classify(text, max_chars=5000)
        assert not got.ok, (text[:20], got)
        assert got.reason == reason, (text[:20], got.reason, reason)
    # Hebrew in with both_ways off is a fifth nothing, and saying "already
    # the target language" is not the same as saying there were no words.
    off = lookup_mod.classify("שלום עולם", both_ways=False)
    assert off.reason == "already-target", off


def test_a_prompt_change_retires_the_answers_it_produced() -> None:
    """Otherwise a reworded prompt looks like it did nothing: the cache
    keeps serving the answers the old wording made."""
    import lookup as lookup_mod

    key = lookup_mod.Cache.key("Hebrew", "word", "brittle")
    assert key.startswith(lookup_mod.PROMPT_VERSION + "|"), key
    assert "Hebrew" in key and "word" in key, key
    # Case is not folded on purpose: "US" and "us" are different lookups.
    assert lookup_mod.Cache.key("Hebrew", "word", "US") != \
        lookup_mod.Cache.key("Hebrew", "word", "us")


def test_the_lookup_box_swallows_esc_and_nothing_else() -> None:
    """on_key_down is the only part of this feature that can hurt the
    dictation path: it is the one thing able to stop a keystroke reaching
    the app being typed into. Swept over the real state machine with the
    real window, 2026-08-19: box shut, 0 of 253 keys swallowed; box open,
    only Esc.

    Esc is also the only key that does anything to the box at all. Every
    other key used to DISMISS it while passing through, which meant an
    answer could not be read with a hand on the keyboard — one Shift and
    it was gone — and the owner reported that as the box vanishing at
    random. So the letter below has to leave the box exactly where it is,
    and the assertion that it does is the point of this test now."""
    import main as main_mod
    import popup as popup_mod

    box = popup_mod.Popup()
    if box.hwnd is None:
        print("        (no popup window here — skipping)")
        return
    try:
        app = main_mod.App.__new__(main_mod.App)
        app.popup, app._lookup_vk = box, vk_for("f6")
        fired: list[str] = []
        machine = PTTStateMachine(
            {vk_for("right ctrl"): "he"},
            on_start=lambda lang: None, on_stop=lambda lang: None,
            on_abort=lambda why: None,
            taps={vk_for("f6"): "lookup"}, on_tap=fired.append,
            on_key_down=app._popup_key)

        for vk in range(0x01, 0x100):
            if vk == vk_for("right ctrl"):
                continue
            assert not machine.handle("down", vk, False), hex(vk)
            machine.handle("up", vk, False)

        box.show("שביר", rtl=True, dwell_ms=0)
        time.sleep(0.2)
        assert box.visible(), "the box did not open"
        assert machine.handle("down", 0x1B, False), "Esc was not swallowed"
        time.sleep(0.1)
        assert not box.visible(), "Esc did not close the box"
        assert not machine.handle("down", 0x1B, False), \
            "Esc swallowed with no box on screen — that Esc is the app's"

        box.show("שביר", rtl=True, dwell_ms=0)
        time.sleep(0.2)
        for key in ("a", "left shift", "space", "left", "backspace"):
            assert not machine.handle("down", vk_for(key), False), \
                f"'{key}' was swallowed — it belongs to the app underneath"
            machine.handle("up", vk_for(key), False)
        time.sleep(0.1)
        assert box.visible(), \
            "a keystroke closed the box you were still reading"

        # The lookup key is kept away from the box because that press has
        # a job of its own — it asks a new question. It must reach
        # _tap_lookup rather than being spent here.
        box.show("שביר", rtl=True, dwell_ms=0)
        time.sleep(0.2)
        fired.clear()
        assert not machine.handle("down", vk_for("f6"), False)
        machine.handle("up", vk_for("f6"), False)
        assert fired == ["lookup"], fired
        assert box.visible(), "the popup closed the box behind the tap"

        # The dictation key is a modifier and must not dismiss anything —
        # it is held, and the box has to survive being dictated over.
        assert not machine.handle("down", vk_for("right ctrl"), False)
        time.sleep(0.1)
        assert machine.state == hotkey_mod.RECORDING, machine.state
        assert box.visible(), "starting a dictation closed the box"
        machine.handle("up", vk_for("right ctrl"), False)
    finally:
        box.stop()


def test_the_apps_own_keystrokes_do_not_close_the_lookup_box() -> None:
    """The paste chord is the app typing, not the user.

    hotkey.py has answered "an injected key is not the user" for the abort
    rule since the beginning (test_injected_keys_never_abort); on_key_down
    has to answer it the same way. Measured before this was gated: tap the
    lookup key while a dictation is still transcribing, and the Ctrl+V that
    pastes the transcript a second later closed the box the answer had just
    appeared in — as did the backspaces that erase the placeholder.

    The gate carries more than that now. The chord this app sends to READ
    a selection is a Ctrl+C, and the box takes Ctrl+C when it holds one:
    offered that chord, the box would swallow the app's own copy and the
    lookup key would report "nothing selected" for a selection that was
    there all along. So the copy chord is driven through here as well.
    """
    import main as main_mod
    import popup as popup_mod

    box = popup_mod.Popup()
    if box.hwnd is None:
        print("        (no popup window here — skipping)")
        return
    try:
        app = main_mod.App.__new__(main_mod.App)
        app.popup, app._lookup_vk = box, vk_for("f6")
        machine = PTTStateMachine(
            {vk_for("right ctrl"): "he"},
            on_start=lambda lang: None, on_stop=lambda lang: None,
            on_abort=lambda why: None, on_key_down=app._popup_key)

        box.show("שביר", rtl=True, dwell_ms=0)
        time.sleep(0.2)
        assert box.visible(), "the box did not open"
        for event, vk in (("down", vk_for("left ctrl")),
                          ("down", vk_for("v")), ("up", vk_for("v")),
                          ("up", vk_for("left ctrl"))):
            assert not machine.handle(event, vk, True), (event, hex(vk))
        for _ in range(3):
            assert not machine.handle("down", vk_for("backspace"), True)
        time.sleep(0.2)
        assert box.visible(), \
            "the app's own paste chord closed the box you were reading"

        # The copy chord, which is the one that would cost a selection.
        for event, vk in (("down", vk_for("left ctrl")),
                          ("down", vk_for("c")), ("up", vk_for("c")),
                          ("up", vk_for("left ctrl"))):
            assert not machine.handle(event, vk, True), (event, hex(vk))

        # ...and a real Esc still does, which is the only key that can.
        # An injected one cannot: the gate above is about who typed it,
        # not about which key it was.
        assert not machine.handle("down", 0x1B, True)
        time.sleep(0.2)
        assert box.visible(), "an injected Esc closed the box"
        assert machine.handle("down", 0x1B, False), "a real Esc was not eaten"
        time.sleep(0.2)
        assert not box.visible(), "Esc did not close the box"
    finally:
        box.stop()


def test_an_esc_that_closed_the_box_does_not_discard_a_recording() -> None:
    """One keystroke, one meaning.

    Esc has meant "throw the locked recording away" since the latch
    existed. The lookup box gave it a second, unrelated job, and both ran
    on the same press: driven through the real state machine before this
    was fixed, one Esc aimed at a box on screen closed the box AND fired
    on_abort("esc pressed while locked"), losing however many minutes of
    speech were latched behind it.
    """
    import main as main_mod
    import popup as popup_mod

    box = popup_mod.Popup()
    if box.hwnd is None:
        print("        (no popup window here — skipping)")
        return
    aborted: list[str] = []
    try:
        app = main_mod.App.__new__(main_mod.App)
        app.popup, app._lookup_vk = box, vk_for("f6")
        machine = PTTStateMachine(
            {vk_for("right ctrl"): "he"},
            on_start=lambda lang: None, on_stop=lambda lang: None,
            on_abort=aborted.append, on_key_down=app._popup_key,
            latch_vk=vk_for("left"), on_latch=lambda: None)

        machine.handle("down", vk_for("right ctrl"), False)
        machine.handle("down", vk_for("left"), False)
        assert machine.state == hotkey_mod.LATCHED, machine.state

        box.show("שביר", rtl=True, dwell_ms=0)
        time.sleep(0.2)
        assert box.visible(), "the box did not open"

        swallowed = machine.handle("down", vk_for("esc"), False)
        time.sleep(0.2)
        assert swallowed, "the esc that closed the box reached the app"
        assert not box.visible(), "esc did not close the box"
        assert not aborted, \
            f"closing the box discarded the recording too: {aborted}"
        assert machine.state == hotkey_mod.LATCHED, \
            f"the recording did not survive the esc ({machine.state})"

        # ...and with no box on screen esc still means what it always did.
        machine.handle("down", vk_for("esc"), False)
        assert aborted == ["esc pressed while locked"], aborted
    finally:
        box.stop()


def test_the_console_guard_looks_at_the_window_getting_the_chord() -> None:
    """The remembered window is not the one SendInput delivers to.

    _tap_lookup notes the foreground window on the hook thread; the capture
    then waits for the cursor lock, which the translate worker can hold for
    as long as its model takes — up to ollama_timeout_s. Tap the key in a
    browser while a translation is in flight, alt-tab to a terminal, and
    the copy chord arrives THERE. Testing only the remembered hwnd sent a
    real interrupt into whatever was building.
    """
    import injector as injector_mod

    sent: list[str] = []
    console, browser = 0x1111, 0x2222
    with _patched(injector_mod, "send_chord", sent.append), \
            _patched(injector_mod, "foreground_window", lambda: console), \
            _patched(injector_mod, "is_console_window",
                     lambda hwnd: hwnd == console), \
            _patched(injector_mod, "window_class",
                     lambda hwnd: "CASCADIA_HOSTING_WINDOW_CLASS"):
        text, reason = injector_mod.read_selection("ctrl+c", hwnd=browser)

    assert reason == "console", reason
    assert text == ""
    assert not sent, f"a copy chord was sent at a console anyway: {sent}"


def test_a_clipboard_restore_that_cannot_be_written_is_not_begun() -> None:
    """EmptyClipboard() is the point of no return.

    Emptying first and discovering afterwards that the replacement cannot
    be allocated destroys the user's clipboard outright — the one path on
    which a key that never writes anything could still lose data. Fault
    injected: with the block allocation made to fail, the clipboard came
    back EMPTY, and the caller then reported "the clipboard was locked",
    which names the wrong problem entirely.
    """
    import injector as injector_mod

    emptied: list[int] = []

    def refuse(blob):
        raise OSError("no memory for you")

    with _patched(injector_mod, "_alloc_block", refuse), \
            _patched(injector_mod, "_open_clipboard",
                     lambda *a, **k: None), \
            _patched(injector_mod.win32clipboard, "EmptyClipboard",
                     lambda: emptied.append(1)), \
            _patched(injector_mod.win32clipboard, "CloseClipboard",
                     lambda: None):
        ok = injector_mod.restore_all([(13, b"hello")])

    assert not ok, "a restore that wrote nothing reported success"
    assert not emptied, \
        "the clipboard was emptied before the replacement existed"


def test_a_crash_takes_the_box_down_with_it() -> None:
    """An ellipsis on screen is a promise that an answer is coming.

    Only TranscriptionError is turned into a line the box can show. A bug
    anywhere else unwound to the worker, which played the error cue and
    logged it — and left the box claiming to be thinking for the rest of
    its dwell, while the sound said otherwise.
    """
    import shutil
    import tempfile

    import main as main_mod

    tmp = Path(tempfile.mkdtemp(prefix="dictation-lookup-crash-"))
    fake = _FakeInjector()
    real_inj = main_mod.injector
    played, restore = _cue_spy(main_mod)
    try:
        app = _lookup_app(tmp, fake, "שביר")
        fake.selection = "brittle"
        # Not a TranscriptionError: the engine is not the only thing in
        # this path that can raise, and everything else lands here.
        app._lookup_engine.answer = ValueError("boom")

        worker = threading.Thread(target=app._lookup_worker, daemon=True)
        worker.start()
        app._looking_up.set()
        app.lookup_queue.put((fake.focus, (700, 400)))
        for _ in range(300):
            if app.popup.hidden:
                break
            time.sleep(0.01)

        assert app.popup.hidden, \
            "the box was left up saying it was still thinking"
        assert not app.popup.visible(), app.popup.shown
        assert "error" in played, played
    finally:
        restore()
        main_mod.injector = real_inj
        shutil.rmtree(tmp, ignore_errors=True)


def test_esc_cannot_be_bound_to_a_tap_key() -> None:
    """It already means "discard the locked recording".

    latch_hotkey and pause_hotkey were checked for this from the start; the
    tap keys were not, which stopped being harmless the moment one of them
    opened a window. Bound to esc, the lookup key is excluded from the
    box's own dismissal rule — a key cannot both open a box and close it —
    while still discarding a latched recording.
    """
    import dataclasses

    for field_name in ("translate_hotkey", "punctuate_hotkey",
                       "correct_hotkey", "lookup_hotkey"):
        cfg = dataclasses.replace(config_mod.Config(),
                                  **{field_name: "esc"})
        try:
            config_mod.check_hotkeys(cfg)
        except config_mod.ConfigError as e:
            assert field_name in str(e), str(e)
        else:
            raise AssertionError(f"{field_name} = 'esc' was accepted")


def test_the_lookup_box_is_never_in_the_focus_chain() -> None:
    """It appears over what is being read without taking the caret, and
    these style bits are the whole of that promise. Read back off the live
    window rather than asserted from the constructor call, in the style of
    the status dot's test above."""
    import ctypes

    import popup as popup_mod

    box = popup_mod.Popup()
    if box.hwnd is None:
        print("        (no popup window here — skipping)")
        return
    try:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.GetWindowLongW.restype = ctypes.c_long
        style = user32.GetWindowLongW(box.hwnd, -20) & 0xFFFFFFFF
        assert style & 0x08000000, "WS_EX_NOACTIVATE is not set"
        assert style & 0x00000080, "WS_EX_TOOLWINDOW is not set"
        assert style & 0x00000008, "WS_EX_TOPMOST is not set"
        assert not style & 0x00040000, "WS_EX_APPWINDOW: it is Alt-Tab-able"
        user32.GetWindow.restype = ctypes.c_void_p
        assert not user32.GetWindow(ctypes.c_void_p(box.hwnd), 4), \
            "the box has an owner window"
    finally:
        box.stop()


def test_the_lookup_box_is_capped_at_the_size_it_was_given() -> None:
    """measure() was unbounded once and a 22-sentence paragraph made a
    896 px tall window, taller than some work areas. The longest
    unbreakable token in the real transcript corpus is 223 chars — 3121 px
    against a 2560 px monitor — so the word-breaker has to be able to split
    inside a token and not only between them."""
    import popup as popup_mod

    box = popup_mod.Popup(max_width=460, max_height=520)
    if box.hwnd is None:
        print("        (no popup window here — skipping)")
        return
    try:
        for text in ("x" * 223, popup_mod._PARAGRAPH * 4, "שביר"):
            for rtl in (True, False):
                width, height = box.measure(text, rtl=rtl)
                assert 0 < width <= 460, (len(text), rtl, width)
                assert 0 < height <= 520, (len(text), rtl, height)
    finally:
        box.stop()


def test_the_box_lands_inside_the_work_area_and_never_on_the_anchor() -> None:
    """The two promises placement makes, swept rather than sampled.

    The anchor is NOT guaranteed to be inside the work area: it is either
    a caret rect or wherever main.cursor_point() found the mouse, and the
    mouse can be over the taskbar. That is why the sweep runs over each
    monitor's FULL rect and not over its work area — with an anchor at
    y = 1435 on a 1440 px screen the box took the "there is no room
    below, go above" branch, measured 18 px up from the anchor, and left
    25 px of itself lying across the Start button. 376 placements did
    that. The work area is the oracle here and MonitorInfo is read
    independently, so this compares placement against Windows rather than
    against itself.

    The bottom and right edges are added to the grid by hand: a round
    step size walks straight past the 48 px taskbar strip that is the
    whole point of the test.
    """
    import ctypes
    import ctypes.wintypes as wt

    import popup as popup_mod

    class MONITORINFO(ctypes.Structure):
        _fields_ = [("cbSize", ctypes.c_ulong), ("rcMonitor", wt.RECT),
                    ("rcWork", wt.RECT), ("dwFlags", ctypes.c_ulong)]

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    monitors: list[tuple[tuple, tuple]] = []

    def collect(handle, hdc, lprc, lparam):
        mi = MONITORINFO()
        mi.cbSize = ctypes.sizeof(MONITORINFO)
        user32.GetMonitorInfoW(handle, ctypes.byref(mi))
        full, work = mi.rcMonitor, mi.rcWork
        monitors.append(((full.left, full.top, full.right, full.bottom),
                         (work.left, work.top, work.right, work.bottom)))
        return 1

    user32.EnumDisplayMonitors(None, None, ctypes.WINFUNCTYPE(
        ctypes.c_int, wt.HANDLE, wt.HDC, ctypes.POINTER(wt.RECT),
        wt.LPARAM)(collect), 0)
    if not monitors:
        print("        (no monitors here — skipping)")
        return

    box = popup_mod.Popup()
    if box.hwnd is None:
        print("        (no popup window here — skipping)")
        return
    try:
        def work_area_for(anchor):
            """Which monitor owns this anchor — decided from its CENTRE,
            because an anchor 40 px wide can straddle the seam between two
            screens and only one of them can have it."""
            cx = (anchor[0] + anchor[2]) // 2
            cy = (anchor[1] + anchor[3]) // 2
            for full, work in monitors:
                if (full[0] <= cx < full[2] and full[1] <= cy < full[3]):
                    return work
            return None

        checked = 0
        for full, _ in monitors:
            xs = list(range(full[0] + 3, full[2], 149))
            xs += [full[2] - 60, full[2] - 20, full[2] - 2]
            ys = list(range(full[1] + 3, full[3], 137))
            ys += [full[3] - 60, full[3] - 20, full[3] - 2]
            for ax in xs:
                for ay in ys:
                    anchor = (ax, ay, ax + 40, ay + 20)
                    work = work_area_for(anchor)
                    if work is None:
                        continue    # off the desktop entirely
                    for width, height in ((446, 150), (284, 129),
                                          (460, 520)):
                        if (width > work[2] - work[0]
                                or height > work[3] - work[1]):
                            continue    # no honest answer exists
                        for rtl in (True, False):
                            checked += 1
                            x, y = box.place_for(width, height, anchor,
                                                 rtl=rtl)
                            got = (x, y, x + width, y + height)
                            assert (got[0] >= work[0] and got[1] >= work[1]
                                    and got[2] <= work[2]
                                    and got[3] <= work[3]), \
                                f"{got} escaped the work area {work} " \
                                f"(anchor {anchor}, rtl={rtl})"
                            assert (got[2] <= anchor[0]
                                    or got[0] >= anchor[2]
                                    or got[3] <= anchor[1]
                                    or got[1] >= anchor[3]), \
                                f"{got} covers the anchor {anchor} " \
                                f"(rtl={rtl})"
        assert checked > 500, f"the sweep only made {checked} placements"
    finally:
        box.stop()


def test_only_the_close_button_closes_the_box_when_it_is_clicked() -> None:
    """The button the owner asked for, and the three near-misses.

    He reported the box "disappearing randomly", and the rule that did it
    was dismiss-on-mouse-leave: the box opens under the cursor, so the
    first twitch of the hand took the answer away. Nothing about the
    mouse may close it now except a press and a release both inside the
    button — the rule every push button on Windows follows, which is what
    makes sliding off before letting go a cancel.

    The messages go to the real window with SendMessageW, which returns
    only after the popup thread's handler has run, so there is nothing to
    wait for afterwards. The button's rectangle is read off the live
    layout the window is painted from, so this test cannot drift away
    from the button actually on screen.
    """
    import ctypes
    import time as time_mod

    import popup as popup_mod

    WM_LBUTTONDOWN, WM_LBUTTONUP, WM_MOUSELEAVE = 0x0201, 0x0202, 0x02A3
    MK_LBUTTON = 0x0001

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    box = popup_mod.Popup()
    if box.hwnd is None:
        print("        (no popup window here — skipping)")
        return

    def lparam(x, y):
        return (y << 16) | (x & 0xFFFF)

    def click(down_at, up_at):
        user32.SendMessageW(box.hwnd, WM_LBUTTONDOWN, MK_LBUTTON,
                            lparam(*down_at))
        user32.SendMessageW(box.hwnd, WM_LBUTTONUP, 0, lparam(*up_at))

    try:
        for rtl, text in ((False, "brittle\n1. adjective - easily broken"),
                          (True, "שביר\n1. שם תואר - נשבר בקלות")):
            box.show(text, rtl=rtl, anchor=(900, 500, 940, 520))
            for _ in range(100):
                if box.visible():
                    break
                time_mod.sleep(0.02)
            assert box.visible(), "the box never went up"
            button = box._lay.button          # what _paint draws
            mid = ((button.left + button.right) // 2,
                   (button.top + button.bottom) // 2)
            far = (button.left // 2 if rtl else button.left - 40,
                   button.bottom + 40)

            # The mouse leaving used to be the whole bug.
            user32.SendMessageW(box.hwnd, WM_MOUSELEAVE, 0, 0)
            assert box.visible(), "the mouse leaving closed it again"

            click(far, far)
            assert box.visible(), "a click on the text closed it"

            click(mid, far)
            assert box.visible(), "pressed the button, slid off: closed"

            click(far, mid)
            assert box.visible(), "released on the button it never armed"

            click(mid, mid)
            assert not box.visible(), "the close button did not close it"
            assert box._hidden_by == "close button", box._hidden_by
    finally:
        box.stop()


def _drag_box(box, user32, ctypes, time_mod, from_pt, to_pt):
    """Press inside the box at `from_pt`, walk to `to_pt`, release.

    The REAL cursor has to be moved, not just the message's lparam:
    _drag_to reads GetCursorPos on purpose (mouse messages carry client
    coordinates, and the client origin is the thing being moved). Both
    points are in screen pixels. Returns False if the cursor could not be
    put where it was asked — the owner's pointing device parks it and
    yanks it back, and a probe that could not aim is not a failure.
    """
    WM_LBUTTONDOWN, WM_LBUTTONUP, WM_MOUSEMOVE = 0x0201, 0x0202, 0x0200
    MK_LBUTTON = 0x0001

    class POINT(ctypes.Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

    def place(x, y):
        user32.SetCursorPos(int(x), int(y))
        time_mod.sleep(0.01)
        p = POINT()
        user32.GetCursorPos(ctypes.byref(p))
        return (p.x, p.y) == (int(x), int(y))

    def lparam(pt):
        r = _win_rect(box.hwnd, user32, ctypes)
        x, y = pt[0] - r[0], pt[1] - r[1]
        return ((y & 0xFFFF) << 16) | (x & 0xFFFF)

    if not place(*from_pt):
        return False
    user32.SendMessageW(box.hwnd, WM_LBUTTONDOWN, MK_LBUTTON,
                        lparam(from_pt))
    steps = 12
    for i in range(1, steps + 1):
        x = from_pt[0] + (to_pt[0] - from_pt[0]) * i // steps
        y = from_pt[1] + (to_pt[1] - from_pt[1]) * i // steps
        if not place(x, y):
            user32.SendMessageW(box.hwnd, WM_LBUTTONUP, 0, 0)
            return False
        user32.SendMessageW(box.hwnd, WM_MOUSEMOVE, MK_LBUTTON,
                            lparam((x, y)))
    user32.SendMessageW(box.hwnd, WM_LBUTTONUP, 0, lparam(to_pt))
    return True


def _win_rect(hwnd, user32, ctypes):
    class RECT(ctypes.Structure):
        _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                    ("right", ctypes.c_long), ("bottom", ctypes.c_long)]
    r = RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    return r.left, r.top, r.right, r.bottom


def test_the_box_moves_when_dragged_and_stays_where_it_was_put() -> None:
    """The answer must not cover the sentence it is about.

    The box is placed beside the selection, and beside a selection near
    the bottom of the screen is on top of the next paragraph. Dragging it
    is the whole fix — but only if it STAYS: the answer arrives in a
    second update() call, and re-placing the box from the anchor then
    would snatch it back to the spot the owner just moved it away from,
    which is worse than never having moved it.

    Grabbed by the TITLE BAR, which is the only handle there is now. The
    body used to move the box and no longer does: it is text to be
    selected and copied, like every other window on the machine. So this
    presses where a hand would — the bar, clear of the buttons at its
    far corner — and _BAR is read from popup.py rather than guessed, so a
    taller bar moves this grip with it instead of quietly aiming at the
    text underneath.
    """
    import ctypes
    import time as time_mod

    import popup as popup_mod

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    box = popup_mod.Popup()
    if box.hwnd is None:
        print("        (no popup window here — skipping)")
        return

    class POINT(ctypes.Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

    parked = POINT()
    user32.GetCursorPos(ctypes.byref(parked))
    try:
        box.show("שביר\n1. שם תואר - נשבר בקלות", rtl=True,
                 anchor=(900, 500, 940, 520))
        for _ in range(100):
            if box.visible():
                break
            time_mod.sleep(0.02)
        assert box.visible(), "the box never went up"
        assert box._moved_to is None, "a box nobody moved claims a position"

        before = _win_rect(box.hwnd, user32, ctypes)
        grab = (before[2] - 40, before[1] + popup_mod._BAR // 2)
        target = (grab[0] - 150, grab[1] - 90)
        if not _drag_box(box, user32, ctypes, time_mod, grab, target):
            print("        (the cursor could not be aimed — skipping)")
            return

        after = _win_rect(box.hwnd, user32, ctypes)
        assert (after[0] - before[0], after[1] - before[1]) == (-150, -90), \
            (before, after)
        assert (after[2] - after[0], after[3] - after[1]) == \
            (before[2] - before[0], before[3] - before[1]), "it resized"
        assert box._moved_to == (after[0], after[1]), box._moved_to

        # The answer arriving must not move it back.
        box.update("שביר\n1. שם תואר - נשבר בקלות, כמו זכוכית\n"
                   "2. שם תואר - נוקשה ולא גמיש\n"
                   "3. שורה נוספת כדי שהתיבה תגדל")
        for _ in range(100):
            grown = _win_rect(box.hwnd, user32, ctypes)
            if grown[3] - grown[1] > after[3] - after[1]:
                break
            time_mod.sleep(0.02)
        settled = _win_rect(box.hwnd, user32, ctypes)
        assert settled[:2] == after[:2], (after, settled)
        assert settled[3] - settled[1] > after[3] - after[1], \
            "the box never grew, so update() proved nothing"

        # A fresh question is a fresh box: it goes back to the anchor.
        # hide() and show() are both POSTED to the popup thread, so the
        # hide has to be seen to land before the show is asked for —
        # otherwise this reads the state of the box that is still up.
        box.hide()
        for _ in range(100):
            if not box.visible():
                break
            time_mod.sleep(0.02)
        assert not box.visible(), "the box never came down"
        box.show("commit\n1. פועל - למסור", rtl=True,
                 anchor=(900, 500, 940, 520))
        for _ in range(100):
            if box.visible():
                break
            time_mod.sleep(0.02)
        assert box.visible(), "the box never came back"
        assert box._moved_to is None, "a new box kept the old position"
        assert _win_rect(box.hwnd, user32, ctypes)[:2] != settled[:2], \
            "a new box opened at the dragged position, not at the anchor"
    finally:
        user32.SetCursorPos(parked.x, parked.y)
        box.stop()


def test_a_drag_with_no_button_left_in_it_lets_go() -> None:
    """The box must never be left glued to a cursor with nothing held.

    _end_drag is reached from the button-up and from WM_CAPTURECHANGED,
    and the second was believed to cover a capture TAKEN AWAY by
    something else. It does not always: measured 2026-08-20, a second
    thread of this process calling SetCapture on a window of its own took
    the capture — GetCapture named the thief — and no WM_CAPTURECHANGED
    arrived here at all, leaving the drag live. That one recovered on the
    button-up, which still found its way back; a capture lost to
    something that also swallows the up would not have. So a mouse move
    that carries no button ends the drag, whatever else did or did not
    happen, and this is that rule: it stages the exact state such a loss
    leaves behind and moves the mouse across the box.
    """
    import ctypes
    import time as time_mod

    import popup as popup_mod

    WM_MOUSEMOVE, MK_LBUTTON = 0x0200, 0x0001

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    box = popup_mod.Popup()
    if box.hwnd is None:
        print("        (no popup window here — skipping)")
        return

    def lparam(x, y):
        return ((y & 0xFFFF) << 16) | (x & 0xFFFF)

    try:
        box.show("שביר\n1. שם תואר - נשבר בקלות", rtl=True,
                 anchor=(900, 500, 940, 520))
        for _ in range(100):
            if box.visible():
                break
            time_mod.sleep(0.02)
        assert box.visible(), "the box never went up"
        before = _win_rect(box.hwnd, user32, ctypes)

        # Exactly what a capture lost to something that ate the button-up
        # would leave behind: a live, already-moving drag and no button.
        box._drag = popup_mod._Drag(20, 20, before[0] + 20,
                                    before[1] + 20, 1, 1)
        box._drag.active = True
        for i in range(6):
            user32.SendMessageW(box.hwnd, WM_MOUSEMOVE, 0,
                                lparam(30 + 12 * i, 30))
        assert box._drag is None, "a button-less move kept the drag alive"
        assert _win_rect(box.hwnd, user32, ctypes) == before, \
            "the box followed a cursor with no button held down"

        # And a real drag — the same messages WITH the button — still
        # moves it, or the guard above has simply broken dragging.
        # In the title bar, because that is the only place a drag can
        # start now; the far corner from the buttons, which sit at the
        # reading-side end of it.
        b = box._lay.button
        inside = (before[2] - before[0]) - 40, popup_mod._BAR // 2
        assert not (b.left <= inside[0] <= b.right
                    and b.top <= inside[1] <= b.bottom), "grabbed the button"
        user32.SendMessageW(box.hwnd, 0x0201, MK_LBUTTON, lparam(*inside))
        assert box._drag is not None, "the press took no hold of the box"
        user32.SendMessageW(box.hwnd, WM_MOUSEMOVE, MK_LBUTTON,
                            lparam(inside[0] + 40, inside[1] + 40))
        assert box._drag is not None, "a move WITH the button let go"
        user32.SendMessageW(box.hwnd, 0x0202, 0, lparam(inside[0] + 40,
                                                        inside[1] + 40))
        assert box._drag is None, "the release did not end the drag"
    finally:
        box.stop()


def test_a_click_on_the_close_button_is_not_a_drag() -> None:
    """A finger coming down on an 18 px button shifts a pixel or two.

    The press that closes the box is also a press the box could read as
    "take hold of me", and the two would fight: the button would close a
    box that had crept two pixels sideways first, or worse, arm the drag
    and never close at all. SM_CXDRAG is the slop the rest of Windows
    allows for exactly this, and the button branch is tested before the
    drag branch — so a click on the button starts no drag whatsoever.
    """
    import ctypes
    import time as time_mod

    import popup as popup_mod

    WM_LBUTTONDOWN, WM_LBUTTONUP, WM_MOUSEMOVE = 0x0201, 0x0202, 0x0200
    MK_LBUTTON = 0x0001

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    box = popup_mod.Popup()
    if box.hwnd is None:
        print("        (no popup window here — skipping)")
        return

    def lparam(x, y):
        return ((y & 0xFFFF) << 16) | (x & 0xFFFF)

    try:
        box.show("שביר\n1. שם תואר - נשבר בקלות", rtl=True,
                 anchor=(900, 500, 940, 520))
        for _ in range(100):
            if box.visible():
                break
            time_mod.sleep(0.02)
        assert box.visible(), "the box never went up"

        before = _win_rect(box.hwnd, user32, ctypes)
        b = box._lay.button
        mid = ((b.left + b.right) // 2, (b.top + b.bottom) // 2)

        user32.SendMessageW(box.hwnd, WM_LBUTTONDOWN, MK_LBUTTON,
                            lparam(*mid))
        assert box._drag is None, "the close button took hold of the box"
        # A wobble of a pixel or two, as a real finger makes.
        for dx, dy in ((1, 0), (1, 1), (2, 1), (1, 1)):
            user32.SendMessageW(box.hwnd, WM_MOUSEMOVE, MK_LBUTTON,
                                lparam(mid[0] + dx, mid[1] + dy))
        assert box._drag is None, "the wobble started a drag"
        assert _win_rect(box.hwnd, user32, ctypes) == before, "it moved"

        user32.SendMessageW(box.hwnd, WM_LBUTTONUP, 0,
                            lparam(mid[0] + 1, mid[1] + 1))
        assert not box.visible(), "the wobbled click did not close the box"
        assert box._hidden_by == "close button", box._hidden_by
        assert box._moved_to is None, "a click left the box marked as moved"
    finally:
        box.stop()


def _box_click(box, user32, at, up_at=None, dbl=False):
    """Press and release inside the box, in client pixels.

    SendMessageW and not PostMessageW: it returns only after the popup
    thread's handler has run, so there is nothing to wait for between the
    press and the assertion about what it did.

    The move in the middle is not decoration, and it is not the test
    being lenient about a real defect. A REAL held button puts MK_LBUTTON
    in every WM_MOUSEMOVE the window sees, which is exactly what keeps
    the button armed. This helper injects a press and a release into a
    window the physical cursor is nowhere near, so any real mouse
    movement on the machine — a hand on the desk, another script — sends
    a button-LESS move in between and disarms it. Measured: the copy
    button's test failed once in four consecutive suite runs that way,
    and never in isolation. Sending the move a real mouse would have
    sent makes the synthetic gesture the same shape as the real one, so
    the test measures the product instead of the desk.
    """
    WM_LBUTTONDOWN, WM_LBUTTONUP, WM_LBUTTONDBLCLK = 0x0201, 0x0202, 0x0203
    WM_MOUSEMOVE = 0x0200
    MK_LBUTTON = 0x0001
    user32.SendMessageW(box.hwnd,
                        WM_LBUTTONDBLCLK if dbl else WM_LBUTTONDOWN,
                        MK_LBUTTON, _lp(at))
    user32.SendMessageW(box.hwnd, WM_MOUSEMOVE, MK_LBUTTON, _lp(up_at or at))
    user32.SendMessageW(box.hwnd, WM_LBUTTONUP, 0, _lp(up_at or at))


def _lp(pt):
    """A mouse message's LPARAM: y in the high half, x in the low one."""
    return ((pt[1] & 0xFFFF) << 16) | (pt[0] & 0xFFFF)


def _line_mid(box, i):
    """The centre of the i-th visual line, in client pixels."""
    r = box._lay.lines[i].rect
    return ((r.left + r.right) // 2, (r.top + r.bottom) // 2)


def _select_lines(box, first, last=None):
    """Light lines `first`..`last` whole, without a gesture.

    A press no longer selects anything — it places a caret, the way one
    does in a paragraph — so the tests that are about something ELSE
    (which button appeared, whether Ctrl+C was swallowed) say what they
    want directly instead of miming a drag across the exact pixels.
    """
    last = first if last is None else last
    box._set_sel(((first, 0), (last, len(box._lay.lines[last].text))))


def _shown(box, text, time_mod, rtl=True, term=""):
    """show() and wait for the window to be up with THIS text laid out.

    The head of lay.text and not the whole of it, because a long answer
    is trimmed to fit and only its tail changes — waiting for equality
    would hang on exactly the case worth testing.
    """
    import popup as popup_mod

    head = popup_mod._clean(text)[:20]
    box.show(text, rtl=rtl, anchor=(900, 500, 940, 520), term=term)
    for _ in range(200):
        if (box.visible() and box._lay is not None
                and box._lay.text[:20] == head):
            break
        time_mod.sleep(0.02)
    return box._lay


def _clip(fn, *args):
    """Call one of injector's clipboard functions, retrying the collision
    this process has WITH ITSELF.

    The box copies on a thread of its own — deliberately, so a clipboard
    held by another app cannot freeze the window you are reading — and
    OpenClipboard hands a SECOND THREAD OF THE SAME PROCESS a success it
    cannot honour, so the call after it raises (1418, 'Thread does not
    have a clipboard open'). popup._copy_now retries for exactly this
    reason; a test that reads the clipboard back while that thread is
    still writing has to do the same, or it fails on the app working.

    Measured 2026-08-20 with a thread writing every 4 ms: a reader lost
    1 of 300, a writer 21 of 300. Nothing is destroyed either way —
    EmptyClipboard is the first call and the one that raises.
    """
    for _ in range(20):
        try:
            return fn(*args)
        except Exception:
            time.sleep(0.03)
    return fn(*args)


def test_the_title_bar_is_the_only_handle_and_the_body_is_text() -> None:
    """"Only the top bar moves it" — the owner's second request, in his
    words, and the half of it that is easy to lose.

    The box used to be draggable from anywhere, which is why it could not
    also offer its text: one press cannot both move a window and take a
    line out of it. The decision is made once, in _zone_at, and this pins
    the whole map — in both mirrorings, because the buttons swap corners
    with the reading direction and a copy button on the label's side is a
    button sitting under the word it is meant to name.

    Then the gesture itself, with the REAL cursor: a drag that starts in
    the body must move the box by exactly nothing, however far it
    travels. Nothing weaker will do — a box that creeps a few pixels
    while a line is being selected is a box fighting the hand.
    """
    import ctypes
    import time as time_mod

    import popup as popup_mod

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    box = popup_mod.Popup()
    if box.hwnd is None:
        print("        (no popup window here — skipping)")
        return

    class POINT(ctypes.Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

    parked = POINT()
    user32.GetCursorPos(ctypes.byref(parked))
    try:
        for rtl, text in ((True, "שביר\n1. שם תואר - נשבר בקלות\n"
                                 "2. שם תואר - לא גמיש"),
                          (False, "brittle\n1. adjective - easily broken\n"
                                  "2. adjective - unyielding")):
            lay = _shown(box, text, time_mod, rtl=rtl, term="brittle")
            assert box.visible(), "the box never went up"

            # A strip across the top with the text under it. Nothing may
            # overlap, or one press would mean two things.
            assert (lay.bar.left, lay.bar.top) == (0, 0), lay.bar
            assert lay.bar.right == lay.width, (lay.bar.right, lay.width)
            assert lay.bar.bottom == popup_mod._BAR, lay.bar.bottom
            assert lay.lines[0].rect.top >= lay.bar.bottom, \
                "the first line is under the title bar"

            # Every button lives IN the bar, at the corner the reader's
            # eye ends a line at, close outermost.
            for name in ("button", "copy", "copysel"):
                b = getattr(lay, name)
                assert (popup_mod._inside(lay.bar, b.left, b.top)
                        and popup_mod._inside(lay.bar, b.right - 1,
                                              b.bottom - 1)), \
                    f"{name} is not inside the title bar"
            if rtl:
                assert lay.button.left < lay.copy.left < lay.copysel.left, \
                    "a Hebrew answer must put the x in the top-LEFT corner"
                assert lay.label_rect.left > lay.copysel.right, \
                    "the caption starts under a button"
            else:
                assert lay.button.left > lay.copy.left > lay.copysel.left, \
                    "an English answer must put the x in the top-RIGHT"
                assert lay.label_rect.right < lay.copysel.left, \
                    "the caption runs under a button"

            def zone(rect):
                return box._zone_at((rect.left + rect.right) // 2,
                                    (rect.top + rect.bottom) // 2)

            assert zone(lay.button) == "close", zone(lay.button)
            assert zone(lay.copy) == "copy", zone(lay.copy)
            assert zone(lay.copysel) == "bar", \
                "an invisible copy-selection button ate a press on the bar"
            assert zone(lay.label_rect) == "bar", \
                "the caption is dead space instead of somewhere to grab"
            for i in range(len(lay.lines)):
                assert box._zone_at(*_line_mid(box, i)) == "body", \
                    f"line {i} is not body"

            # BOTH bottom corners are the resizer's own 18 px squares —
            # which corner used to depend on the answer's language, and a
            # grab on the dead one did nothing. Everything between them
            # along the bottom is still body.
            for grip in (lay.resizer_r, lay.resizer_l):
                assert grip.top >= lay.bar.bottom, \
                    "a resize grip reaches into the title bar"
                assert zone(grip) == "resize", zone(grip)
            pad_x = lay.width // 2        # clear of both corner squares
            assert box._zone_at(pad_x, lay.height - 2) == "body", \
                "the padding below the answer is not body"

            # ...and the gesture. The body may not move the window.
            before = _win_rect(box.hwnd, user32, ctypes)
            start = (before[0] + _line_mid(box, 1)[0],
                     before[1] + _line_mid(box, 1)[1])
            if not _drag_box(box, user32, ctypes, time_mod, start,
                             (start[0] + 90, start[1] + 40)):
                print("        (the cursor could not be aimed — skipping)")
                return
            assert _win_rect(box.hwnd, user32, ctypes) == before, \
                "a drag that began in the body moved the box"
            assert box._moved_to is None, \
                "a body drag left the box marked as moved by hand"
            assert box.selection(), "a body drag selected nothing at all"
    finally:
        user32.SetCursorPos(parked.x, parked.y)
        box.stop()


def test_an_answer_that_does_not_fit_shrinks_its_face_instead_of_losing_words()\
        -> None:
    """Auto-fit — the owner's spec, his words: "there is a maximum size
    that the text box opens to, and the text size should change
    accordingly so that everything fits inside the box".

    Three copies of the 60-word sample do not fit 460x520 at the default
    face and used to lose their tail to an ellipsis there, whatever the
    screen behind them could have held. The premise is pinned first, so
    if faces or samples ever change enough that the default pass fits,
    this says so instead of passing for nothing; then the whole answer
    must come back at a smaller face, every word of it, inside the cap.
    """
    import popup as popup_mod

    box = popup_mod.Popup()
    try:
        clean = popup_mod._clean(popup_mod._PARAGRAPH * 3)
        assert box._layout_at(box.size_px, clean, True,
                              box.max_width, box.max_height).truncated, \
            "the default face fits after all; find longer sample text"
        lay = box._layout(clean, True)
        assert not lay.truncated, "words were lost above the floor"
        assert 0 < lay.size_px < box.size_px, \
            f"face {lay.size_px} is not a real descent from {box.size_px}"
        assert lay.width <= box.max_width, lay.width
        assert lay.height <= box.max_height, lay.height
        assert popup_mod.ELLIPSIS not in lay.text, "cut without saying so"
        # The type may shrink; the text may not change by a word.
        want = [t for t in clean.split() if t]
        got = [t for t in lay.text.split() if t]
        assert got == want, f"{len(want)} words in, {len(got)} words out"
    finally:
        box.stop()


def test_past_the_floor_the_ellipsis_takes_over_again() -> None:
    """The floor exists because below ~11 px Segoe UI Hebrew stops being
    reading and starts being squinting: an unreadable whole answer loses
    to a readable one with an ellipsis. Both halves of that rule are
    pinned here — the descent lands EXACTLY on min_font_px and no
    further, and what it hands back is still capped and still says what
    it cut."""
    import popup as popup_mod

    box = popup_mod.Popup(max_height=120)
    try:
        lay = box._layout(popup_mod._clean(popup_mod._PARAGRAPH), True)
        assert lay.truncated, "a 120 px cap held the whole paragraph?"
        assert lay.size_px == box.min_font_px, \
            f"descended to {lay.size_px}, not the floor {box.min_font_px}"
        assert popup_mod.ELLIPSIS in lay.text, "cut without saying so"
        assert lay.height <= box.max_height, lay.height
    finally:
        box.stop()


def test_dragging_the_grip_resizes_and_a_new_lookup_forgets_it() -> None:
    """"I want to be able to enlarge and shrink the text box" — the
    second half of the same request, driven through the REAL corner with
    the REAL cursor, because _resize_to reads GetCursorPos on purpose.

    The gesture's own promises are what get asserted: the release ends
    it; a Hebrew box grows against its top-left corner (the fixed corner
    is the far one, so the answer stays where the eye left it); the hand
    asks for more than the content needs, which is exactly how the face
    recovers; and the size belongs to THIS answer only — the next
    question forgets it, exactly as a fresh lookup forgets where the last
    box was dragged to.
    """
    import ctypes
    import time as time_mod

    import popup as popup_mod

    class POINT(ctypes.Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    box = popup_mod.Popup()
    if box.hwnd is None:
        print("        (no popup window here — skipping)")
        return
    parked = POINT()
    user32.GetCursorPos(ctypes.byref(parked))
    try:
        lay = _shown(box, popup_mod._PARAGRAPH * 3, time_mod)
        assert box.visible(), "the box never went up"
        before = _win_rect(box.hwnd, user32, ctypes)
        b = lay.resizer_r         # the bottom-right square of the box
        start = (before[0] + (b.left + b.right) // 2,
                 before[1] + (b.top + b.bottom) // 2)
        if not _drag_box(box, user32, ctypes, time_mod, start,
                         (start[0] + 160, start[1] + 130)):
            print("        (the cursor could not be aimed — skipping)")
            return
        after = _win_rect(box.hwnd, user32, ctypes)
        assert box._resizing is None, "the release did not end the gesture"
        assert box._user_size is not None, "the drag left no size behind"
        assert box._user_size[0] > before[2] - before[0], \
            f"asked wider than {before[2] - before[0]}, got {box._user_size}"
        assert (after[0], after[1]) == (before[0], before[1]), \
            "a Hebrew box must grow against its top-left corner"
        assert after[2] > before[2], "the box did not actually grow"
        # The window IS the size the hand asked for — verbatim, not
        # whatever the text could use. A corner that stops under the
        # cursor is the bug this pins.
        got_wh = (after[2] - after[0], after[3] - after[1])
        assert got_wh == tuple(box._user_size), \
            f"window {got_wh} is not the size asked for {box._user_size}"
        # The size was this answer's, not the session's.
        _shown(box, "שביר\n1. שם תואר - נשבר בקלות", time_mod)
        assert box._user_size is None, \
            "a new lookup kept the hand-set size"
    finally:
        user32.SetCursorPos(parked.x, parked.y)
        box.stop()


def test_the_corner_follows_the_hand_even_when_the_answer_is_short()\
        -> None:
    """"It gets stuck … I have to really go down … it doesn't go down
    with me" — the owner, 2026-08-22, on a SHORT answer.

    The first cut sized the window to its CONTENT inside the request, so
    enlarging a box whose answer already fitted moved nothing at all: the
    grip detached from the hand the moment it passed the text's edge, and
    catching up meant dragging far past where you wanted the edge. The
    contract now is direct manipulation: whatever the answer needs, the
    window ends up exactly the size the drag asked for — slack becomes
    background below the last line, and the grip sits in the corner of
    the NEW frame, still under the finger.
    """
    import ctypes
    import time as time_mod

    import popup as popup_mod

    class POINT(ctypes.Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    box = popup_mod.Popup()
    if box.hwnd is None:
        print("        (no popup window here — skipping)")
        return
    parked = POINT()
    user32.GetCursorPos(ctypes.byref(parked))
    try:
        lay = _shown(box, "שביר\n1. שם תואר - נשבר בקלות", time_mod)
        assert box.visible(), "the box never went up"
        before = _win_rect(box.hwnd, user32, ctypes)
        b = lay.resizer_r         # the bottom-right square of the box
        start = (before[0] + (b.left + b.right) // 2,
                 before[1] + (b.top + b.bottom) // 2)
        if not _drag_box(box, user32, ctypes, time_mod, start,
                         (start[0] + 150, start[1] + 120)):
            print("        (the cursor could not be aimed — skipping)")
            return
        after = _win_rect(box.hwnd, user32, ctypes)
        want_w = before[2] - before[0]
        want_h = before[3] - before[1]
        got_w, got_h = after[2] - after[0], after[3] - after[1]
        assert got_w >= want_w + 120 and got_h >= want_h + 90, \
            f"the window stayed behind the hand: {got_w}x{got_h} from " \
            f"{want_w}x{want_h}"
        assert (after[0], after[1]) == (before[0], before[1]), \
            "the fixed corner must not move"
        # And the grip is in the corner of the NEW frame.
        r = box._lay.resizer_r
        assert r.right >= got_w and r.bottom >= got_h, \
            "the resizer no longer sits in the window's bottom-right"
    finally:
        user32.SetCursorPos(parked.x, parked.y)
        box.stop()


def test_enlarging_the_frame_zooms_the_text_past_its_normal_size()\
        -> None:
    """"I'm trying to enlarge it, but it's not growing" — 2026-08-22.

    With the face capped at the 19 px default, a hand-set frame could
    only pile invisible dark slack under short answers: the window grew
    and nothing appeared to happen. Inside a HAND-SET frame the fit now
    searches BOTH sides of the default up to _FACE_MAX and takes the
    largest face that fits — bigger frame, bigger type, until the answer
    fills what you made or the ceiling is reached. Configured caps keep
    the old downward-only search: they are maximums, and that is their
    whole point.
    """
    import popup as popup_mod

    box = popup_mod.Popup()
    try:
        clean = popup_mod._clean(popup_mod._WORD_HE)
        plain = box._layout(clean, True)
        assert not plain.truncated and plain.size_px == box.size_px, \
            "the sample must sit untouched at the default face"
        faces = []
        for width, height in ((700, 600), (1100, 900), (1500, 1200)):
            box._user_size = (width, height)
            lay = box._fit_window(clean, True)
            assert not lay.truncated, "zooming lost words"
            assert lay.width <= width and lay.height <= height, \
                (lay.width, lay.height, width, height)
            assert lay.size_px > box.size_px, \
                f"a {width}x{height} frame did not zoom past default"
            faces.append(lay.size_px)
        assert faces[0] <= faces[1] <= faces[2], \
            f"the face did not grow with the frame: {faces}"
    finally:
        box._user_size = None
        box.stop()


def test_either_bottom_corner_grows_against_its_far_corner() -> None:
    """Which corner was live used to depend on the ANSWER's language:
    bottom-right on Hebrew, bottom-left on English — so the same grab on
    the same spot grew one box and did nothing to the next ("I drag the
    bottom-right down-down-down and it does nothing"). Both corners
    resize now, each against its own fixed top corner. This drives the
    LEFT grip of an ENGLISH box outward-left-and-down and pins the two
    promises that makes: the far (top-right) corner holds still, and
    pulling OUTWARD grows.
    """
    import ctypes
    import time as time_mod

    import popup as popup_mod

    class POINT(ctypes.Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    box = popup_mod.Popup()
    if box.hwnd is None:
        print("        (no popup window here — skipping)")
        return
    parked = POINT()
    user32.GetCursorPos(ctypes.byref(parked))
    try:
        lay = _shown(box, "brittle\n1. adjective - easily broken\n"
                          "2. adjective - unyielding", time_mod, rtl=False)
        assert box.visible(), "the box never went up"
        before = _win_rect(box.hwnd, user32, ctypes)
        b = lay.resizer_l         # the bottom-left square of the box
        start = (before[0] + (b.left + b.right) // 2,
                 before[1] + (b.top + b.bottom) // 2)
        if not _drag_box(box, user32, ctypes, time_mod, start,
                         (start[0] - 150, start[1] + 120)):
            print("        (the cursor could not be aimed — skipping)")
            return
        after = _win_rect(box.hwnd, user32, ctypes)
        assert after[2] == before[2], \
            "a left-corner drag must hold the top-RIGHT corner still"
        assert after[0] < before[0], "pulling outward-left did not grow"
        assert after[3] > before[3], "pulling outward-down did not grow"
        assert box._user_size is not None, "the drag left no size behind"
    finally:
        user32.SetCursorPos(parked.x, parked.y)
        box.stop()


def test_a_drag_takes_the_characters_it_crossed_and_not_whole_lines()\
        -> None:
    """The answer has to be takeable a piece at a time.

    It used to come a whole line at a time, because DrawTextW has no hit
    test and a line was the finest unit that could be worked out without
    one. Uniscribe answers the hit test, so a drag now takes exactly what
    it crossed — which is what the owner asked for and what every other
    window on his screen does.

    Five gestures through the real window: a press alone takes NOTHING
    (it places a caret, as a press in a paragraph does), a drag along one
    line takes the characters between its ends, a drag across lines takes
    the tail of the first and the head of the last, a drag off the bottom
    takes everything below, and a press in the padding lets go without
    closing the box.
    """
    import ctypes
    import time as time_mod

    import popup as popup_mod

    WM_LBUTTONDOWN, WM_LBUTTONUP, WM_MOUSEMOVE = 0x0201, 0x0202, 0x0200
    MK_LBUTTON = 0x0001

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    box = popup_mod.Popup()
    if box.hwnd is None:
        print("        (no popup window here — skipping)")
        return

    def sweep(start, points):
        user32.SendMessageW(box.hwnd, WM_LBUTTONDOWN, MK_LBUTTON, _lp(start))
        for pt in points:
            user32.SendMessageW(box.hwnd, WM_MOUSEMOVE, MK_LBUTTON, _lp(pt))
        user32.SendMessageW(box.hwnd, WM_LBUTTONUP, 0, _lp(points[-1]))

    def at(line, frac):
        """A point `frac` of the way across `line`, in client pixels."""
        r = box._lay.lines[line].rect
        return (r.left + int((r.right - r.left) * frac),
                (r.top + r.bottom) // 2)

    text = ("שביר\n1. שם תואר - נשבר או נסדק בקלות, לא עמיד במאמץ.\n"
            "2. שם תואר - רגיש ומועד לכישלון פתאומי.\n"
            "3. Whisper הוא מודל התמלול של OpenAI.")
    try:
        lay = _shown(box, text, time_mod)
        assert box.visible(), "the box never went up"
        lines = [ln.text for ln in lay.lines]
        assert len(lines) >= 4, lines

        # A press alone is a caret, not a line.
        _box_click(box, user32, _line_mid(box, 2))
        assert box.selection() == "", \
            f"a press took something: {box.selection()!r}"
        assert box.visible(), "a press closed the box"

        # A drag along one line takes part of it, and never all of it
        # unless it was dragged all the way.
        sweep(at(2, 0.75), [at(2, 0.35)])
        got = box.selection()
        assert got, "a drag along a line took nothing"
        assert got in lines[2], f"{got!r} is not a piece of {lines[2]!r}"
        assert got != lines[2], "a drag across part of a line took all of it"

        # Across lines: the tail of the first and the head of the last,
        # joined by the newline between them.
        sweep(at(1, 0.5), [at(2, 0.5), at(3, 0.5)])
        got = box.selection()
        assert got.count("\n") == 2, repr(got)
        head, middle, tail = got.split("\n")
        assert head and lines[1].endswith(head), (head, lines[1])
        assert middle == lines[2], (middle, lines[2])
        assert tail and lines[3].startswith(tail), (tail, lines[3])

        # Off the bottom of the box entirely: the rest of the answer.
        sweep(at(1, 0.5), [(30, lay.height + 400)])
        got = box.selection()
        assert got.endswith(lines[-1]), repr(got)
        assert got.count("\n") == len(lines) - 2, repr(got)

        # A press in the padding lets go — and does NOT close the box.
        # Mid-width along the bottom edge: both corners are resize
        # grips now, and a press on one would begin a gesture instead.
        _box_click(box, user32, (lay.width // 2, lay.height - 2))
        assert box.selection() == "", box.selection()
        assert box.visible(), "letting a selection go closed the box"
    finally:
        box.stop()


def test_the_highlight_stops_where_the_text_does() -> None:
    """A band over blank paper reads as text that is not there.

    A line is right-aligned in a rectangle as wide as the widest line, so
    a short line has empty space to its left. ScriptStringOut given the
    row rectangle and ETO_OPAQUE fills ALL of it — the highlight ran the
    full width of the row and out past the last letter, which is what it
    looked like on screen: a solid block selecting nothing.

    Passing no rectangle makes the fill cover the glyphs' own extents,
    which is what a selection is. Counted in pixels off the real window
    rather than asserted from the flags, because the flags were what
    looked right.
    """
    import ctypes
    import time as time_mod

    import popup as popup_mod

    box = popup_mod.Popup()
    if box.hwnd is None:
        print("        (no popup window here — skipping)")
        return
    try:
        # Two lines of very different lengths, so the short one has a
        # wide empty half for a runaway fill to show up in.
        lay = _shown(box, "שביר\n"
                          "1. שם תואר - נוטה להישבר בקלות מאוד וגם נסדק\n"
                          "2. ביטוי - קצר", time_mod)
        short = len(lay.lines) - 1
        row = lay.lines[short]
        assert row.rect.right - row.rect.left > 60, "no empty half to test"

        box._set_sel(((short, 0), (short, len(row.text))))
        time_mod.sleep(0.25)
        lit = _row_pixels(box, row, popup_mod.SEL)
        assert lit, "the selected line was not highlighted at all"

        # Everything lit has to sit within the glyphs, and the glyphs of
        # a right-aligned line start at right - width.
        hdc = popup_mod.user32.GetDC(None)
        try:
            old = popup_mod.gdi32.SelectObject(hdc, box._font(row.role))
            try:
                with popup_mod._Shaped(hdc, row.text, True) as shaped:
                    width = shaped.width
            finally:
                popup_mod.gdi32.SelectObject(hdc, old)
        finally:
            popup_mod.user32.ReleaseDC(None, hdc)

        left_edge = row.rect.right - width
        slack = 6           # the fill rounds outwards by a pixel or two
        assert min(lit) >= left_edge - slack, (
            f"the highlight starts at x={min(lit)}, {left_edge - min(lit)} "
            f"px left of where the text does — it is painting over blank "
            f"space")
        assert max(lit) <= row.rect.right + slack, max(lit)
    finally:
        box.stop()


def _row_pixels(box, row, colour):
    """The x of every pixel of `colour` along the middle of `row`.

    Read off the live window with GetPixel: what the highlight covers is
    a thing about pixels, and the flags that were meant to control it are
    exactly what got this wrong.
    """
    import ctypes

    import popup as popup_mod

    gdi32, user32 = popup_mod.gdi32, popup_mod.user32
    gdi32.GetPixel.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
    gdi32.GetPixel.restype = ctypes.c_uint32
    y = (row.rect.top + row.rect.bottom) // 2
    hdc = user32.GetDC(box.hwnd)
    try:
        return [x for x in range(0, box._lay.width)
                if gdi32.GetPixel(hdc, x, y) == colour]
    finally:
        user32.ReleaseDC(box.hwnd, hdc)


def test_a_double_click_takes_the_word_under_it() -> None:
    """The unit a reader means by "that one".

    It used to take the whole sense — every line the block wrapped to —
    because a word needs to know where one ends, and that is the same
    character hit test a line-at-a-time selection did not have. With the
    hit test in place the double-click can mean what it means everywhere
    else.

    The case worth pinning is the Latin term inside Hebrew: a
    double-click on "Whisper" must take the term and neither of the
    Hebrew words drawn either side of where it happens to sit.
    """
    import ctypes
    import time as time_mod

    import popup as popup_mod

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    box = popup_mod.Popup()
    if box.hwnd is None:
        print("        (no popup window here — skipping)")
        return
    try:
        line = "3. Whisper הוא מודל התמלול של OpenAI."
        lay = _shown(box, "שביר\n" + line, time_mod)
        row = next(i for i, ln in enumerate(lay.lines) if "Whisper" in ln.text)
        text = lay.lines[row].text

        # Straight at the middle of the word, by character rather than by
        # eye: the point a bidi run is drawn at is not where the string
        # says it is, which is the whole reason this needs the hit test.
        box._select_word((row, text.index("Whisper") + 3))
        assert box.selection() == "Whisper", box.selection()

        box._select_word((row, text.index("התמלול") + 2))
        assert box.selection() == "התמלול", box.selection()

        # A double-click on a space takes the run of spaces, not nothing:
        # a gesture that silently does nothing reads as a broken box.
        box._select_word((row, text.index(" הוא")))
        assert box.selection() == " ", repr(box.selection())
    finally:
        box.stop()


def test_nothing_inside_the_answer_is_a_press_that_selects_nothing() -> None:
    """The gaps are where a hand aiming at a 21 px line actually lands.

    A line is about 21 px tall with 5 px between senses and 20 px of
    hairline under the headline, so a press aimed at a line misses it
    nearly as often as it hits. If those gaps belonged to no line the
    press would silently throw away whatever was selected — the worst
    kind of miss, because nothing on screen says why. So the hit strips
    TILE: they meet halfway across every gap and never overlap. Outside
    the first and last line there is deliberately nothing, which is the
    only way to let a selection go without closing the box.
    """
    import popup as popup_mod

    box = popup_mod.Popup()
    try:
        for text in ("שביר\n1. שם תואר - נשבר בקלות\n2. שם תואר - לא גמיש",
                     popup_mod._PARAGRAPH,
                     "brittle\n1. adjective - easily broken",
                     popup_mod._PARAGRAPH * 4):
            lay = box._layout(popup_mod._clean(text), True)
            box._lay = lay
            rows = lay.lines
            assert rows, text[:20]
            for i, ln in enumerate(rows):
                assert (ln.hit[0] <= ln.rect.top
                        and ln.hit[1] >= ln.rect.bottom), \
                    f"line {i} cannot select its own glyphs"
                if i:
                    assert ln.hit[0] == rows[i - 1].hit[1], \
                        f"a gap or an overlap between lines {i - 1} and {i}"
            for y in range(rows[0].hit[0], rows[-1].hit[1]):
                assert box._line_at(y) is not None, \
                    f"y={y} is inside the answer and selects nothing"
            assert box._line_at(rows[0].hit[0] - 1) is None, \
                "the padding above the answer takes a selection"
            assert box._line_at(rows[-1].hit[1]) is None, \
                "the padding below the answer takes a selection"
            assert box._line_at(lay.height + 50) is None, \
                "a press below the box selects a line"

        # The "…" has nothing to take yet, and a button that does nothing
        # when it is pressed teaches that the button does nothing.
        lay = box._layout(popup_mod.WAITING, True)
        box._lay = lay
        assert not lay.show_copy, "the waiting box offered a copy button"
        assert box._line_at(lay.lines[0].rect.top) is None, \
            "the '…' can be selected"
    finally:
        box._lay = None
        box.stop()


def test_the_selection_copies_in_logical_order_not_glyph_order() -> None:
    """A Hebrew line with an English term in it is the case that breaks
    anything reading the screen instead of the string.

    "3. Whisper הוא מודל התמלול של OpenAI." is painted right to left with
    the two Latin runs left to right inside it, so what the eye sees from
    left to right is ". OpenAI ... Whisper .3" — and that, pasted, is
    nonsense no editor can turn back. What goes on the clipboard is the
    string that was handed to DrawTextW, which is the answer's own order,
    and it has to be a contiguous piece of what the model said.
    """
    import popup as popup_mod

    mixed = "3. Whisper הוא מודל התמלול של OpenAI."
    text = "שביר\n1. שם תואר - נשבר בקלות\n" + mixed
    box = popup_mod.Popup()
    try:
        lay = box._layout(popup_mod._clean(text), True)
        box._lay = lay
        found = [n for n, ln in enumerate(lay.lines) if "Whisper" in ln.text]
        assert found, [ln.text for ln in lay.lines]
        box._sel = ((found[0], 0),
                    (found[0], len(lay.lines[found[0]].text)))
        got = box._selected_text()
        assert got == mixed, got
        assert got in text, "the selection is not a piece of the answer"
        assert got.index("Whisper") < got.index("OpenAI"), \
            "the Latin runs came back in the order they were painted"

        box._sel = ((0, 0),
                    (found[0], len(lay.lines[found[0]].text)))
        joined = box._selected_text()
        assert joined.startswith("שביר"), joined[:20]
        assert joined.endswith(mixed), joined[-20:]
        assert joined.count("\n") == found[0], joined
    finally:
        box._lay, box._sel = None, None
        box.stop()


def test_the_copy_button_copies_the_answer_the_box_could_not_show() -> None:
    """"A small button that copies the whole translated text" — the
    owner's first request, and the trap inside it.

    The box is capped at max_height and a long answer is cut to fit.
    Copying what is ON SCREEN would hand back a truncated answer that
    looks complete the moment it is pasted somewhere with room for it —
    the kind of failure nobody notices until it matters. So the button
    copies what arrived, not what fitted.

    Driven through the real window with real messages, and it reads the
    machine's real clipboard back rather than a spy, because surviving
    contact with that clipboard is the whole point of the button.
    """
    import ctypes
    import time as time_mod

    import popup as popup_mod

    before = _clip(injector.snapshot)
    if before[0] == "other":
        print("        (clipboard holds non-text content — skipping so "
              "it isn't lost)")
        return

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    box = popup_mod.Popup(max_width=460, max_height=260)
    if box.hwnd is None:
        print("        (no popup window here — skipping)")
        return

    def wait_for(want):
        for _ in range(250):
            if _clip(injector.get_text) == want:
                return True
            time_mod.sleep(0.02)
        return False

    def press_copy():
        b = box._lay.copy
        _box_click(box, user32, ((b.left + b.right) // 2,
                                 (b.top + b.bottom) // 2))

    try:
        short = "שביר\n1. שם תואר - נשבר בקלות\n2. שם תואר - לא גמיש"
        _shown(box, short, time_mod)
        assert box.visible(), "the box never went up"
        _clip(injector.set_text, "not the answer")
        press_copy()
        assert wait_for(short), repr(_clip(injector.get_text))

        long_answer = short + "\n" + "\n".join(
            f"{i}. שם תואר - עוד הגדרה ארוכה שנועדה למלא את התיבה."
            for i in range(3, 30))
        lay = _shown(box, long_answer, time_mod)
        assert len(lay.text) < len(long_answer), \
            "the box showed the whole thing, so this proves nothing"
        _clip(injector.set_text, "not the answer")
        press_copy()
        assert wait_for(long_answer), \
            f"the clipboard got {len(_clip(injector.get_text))} chars of " \
            f"{len(long_answer)}: the box copied what it could show"

        # And nothing in this app may put the old clipboard back over it.
        time_mod.sleep(0.4)
        assert _clip(injector.get_text) == long_answer, \
            "something restored over the copy the user asked for"
    finally:
        box.stop()
        if before[0] == "text":
            _clip(injector.set_text, before[1] or "")


def test_the_third_button_copies_the_lines_that_are_lit() -> None:
    """A selection that cannot be copied is a highlight, not a selection.

    The third button is what takes it, and it is only there while
    something is taken — but its ROOM is reserved from the moment there
    is an answer, so pressing on a sense cannot shuffle the close button
    out from under a finger already on its way to it. That is what the
    assertion about the other two rectangles is for.
    """
    import ctypes
    import time as time_mod

    import popup as popup_mod

    before = _clip(injector.snapshot)
    if before[0] == "other":
        print("        (clipboard holds non-text content — skipping so "
              "it isn't lost)")
        return

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    box = popup_mod.Popup()
    if box.hwnd is None:
        print("        (no popup window here — skipping)")
        return
    text = ("שביר\n1. שם תואר - נשבר או נסדק בקלות.\n"
            "2. Whisper הוא מודל התמלול של OpenAI.")
    try:
        lay = _shown(box, text, time_mod)
        assert box.visible(), "the box never went up"
        lines = [ln.text for ln in lay.lines]
        was = [(lay.button.left, lay.button.right),
               (lay.copy.left, lay.copy.right)]
        sel_mid = ((lay.copysel.left + lay.copysel.right) // 2,
                   (lay.copysel.top + lay.copysel.bottom) // 2)

        # Nothing selected: that rectangle is bar, and a press on it takes
        # hold of the box instead of copying nothing.
        assert box._zone_at(*sel_mid) == "bar", box._zone_at(*sel_mid)

        _select_lines(box, 2)
        assert box.selection() == lines[2], box.selection()
        assert box._zone_at(*sel_mid) == "copysel", \
            "the third button did not appear with the selection"
        assert [(box._lay.button.left, box._lay.button.right),
                (box._lay.copy.left, box._lay.copy.right)] == was, \
            "the other two buttons moved when the third appeared"

        _clip(injector.set_text, "not the selection")
        _box_click(box, user32, sel_mid)
        for _ in range(250):
            if _clip(injector.get_text) == lines[2]:
                break
            time_mod.sleep(0.02)
        got = _clip(injector.get_text)
        assert got == lines[2], \
            f"the clipboard holds {got!r}, not the line that was lit"
    finally:
        box.stop()
        if before[0] == "text":
            _clip(injector.set_text, before[1] or "")


def test_ctrl_c_is_swallowed_only_when_the_box_has_a_selection() -> None:
    """A Ctrl+C taken from the window underneath is a silent theft.

    The user presses it expecting the app they are typing in to copy,
    pastes, and gets a line of a dictionary answer instead — with nothing
    on screen to say why. So the accelerator answers for five conditions
    at once, and this walks each of them off: no selection, no Ctrl, a
    chord with another modifier in it, a foreground window that is not
    the one the selection was made in front of, and no box at all.

    Real Ctrl, held with keybd_event, because _ctrl_c_is_ours asks
    GetAsyncKeyState and nothing else can answer it. LEFT Ctrl on
    purpose: right Ctrl is this app's own dictation key on this machine.
    Released in the finally, or the machine is left with a modifier stuck
    down.
    """
    import ctypes
    import time as time_mod

    import popup as popup_mod

    KEYEVENTF_KEYUP = 0x0002

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    box = popup_mod.Popup()
    if box.hwnd is None:
        print("        (no popup window here — skipping)")
        return

    def hold(vk, up=False):
        user32.keybd_event(vk, 0, KEYEVENTF_KEYUP if up else 0, 0)
        time_mod.sleep(0.03)

    copies: list[str] = []
    real_post = box._post

    def spy(op, *args):
        # The copy is intercepted rather than done: this test is about
        # what the hook swallows, and it may not touch the clipboard.
        if op == "copy":
            copies.append(args[0] if args else "")
            return
        real_post(op, *args)

    try:
        _shown(box, "שביר\n1. שם תואר - נשבר בקלות", time_mod)
        assert box.visible(), "the box never went up"
        box._post = spy

        hold(VK_LCTRL)
        assert not box.on_key(VK_C), \
            "Ctrl+C was swallowed with nothing selected"
        hold(VK_LCTRL, up=True)

        _select_lines(box, 1)
        assert box.selection(), "nothing was selected"
        box._sel_fg = int(user32.GetForegroundWindow() or 0)

        assert not box.on_key(VK_C), \
            "a bare c was swallowed — it belongs to the app underneath"

        hold(VK_LCTRL)
        assert box.on_key(VK_C), "Ctrl+C was not swallowed"
        assert copies == ["selection"], copies

        hold(VK_SHIFT)
        assert not box.on_key(VK_C), \
            "Ctrl+Shift+C was swallowed — that is the browsers' inspector"
        hold(VK_SHIFT, up=True)

        was, box._sel_fg = box._sel_fg, 0x7FFFFFF0
        assert not box.on_key(VK_C), \
            "the box answered for a window it never saw a selection in"
        box._sel_fg = was
        hold(VK_LCTRL, up=True)

        copies.clear()
        box.hide()
        for _ in range(100):
            if not box.visible():
                break
            time_mod.sleep(0.02)
        hold(VK_LCTRL)
        assert not box.on_key(VK_C), \
            "Ctrl+C was swallowed with no box on screen"
        assert copies == [], copies
    finally:
        for vk in (VK_LCTRL, VK_SHIFT):
            user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)
        box._post = real_post
        box.stop()


def test_the_direction_and_mode_table() -> None:
    """The 34 rows the pure half of this key has to pass, and the only
    part of it a test can pin exactly — everything else needs a model, a
    clipboard or a screen. Each row was chosen because it breaks a simpler
    rule than the one that shipped: the mixed sentence breaks counting
    letters, the Hebrew question breaks trimming punctuation before asking
    whether it is a word, and the five paths and URLs are there because
    refusing identifiers would refuse "commit", which is the word this key
    exists for."""
    import lookup as lookup_mod

    HE, EN = "Hebrew", "English"
    cases = [
        # (selection, the language to answer in, is it a dictionary word)
        ("brittle", HE, True),
        ("commit", HE, True),
        ("race condition", HE, True),
        ("pull request", HE, True),
        ("state-of-the-art", HE, True),
        ("don't", HE, True),
        ("Restore Defaults", HE, True),
        ("café", HE, True),
        ("It is not rocket science.", HE, False),
        ("Save changes before closing?", HE, False),
        ("The cache is invalidated on write.\n"
         "That is why the second read is slow.", HE, False),
        ("// TODO: debounce this handler", HE, False),
        # Nothing a translator would change.
        ("", None, False),
        ("   \n\t ", None, False),
        ("42", None, False),
        ("3.14159", None, False),
        ("1,234.56 %", None, False),
        ("... !!! ---", None, False),
        ("\U0001f642\U0001f642", None, False),
        # Not language at all: one token that is an address, not a word.
        ("https://github.com/anthropics/claude-code", None, False),
        ("www.example.com/a/b?q=1", None, False),
        ("someone@example.com", None, False),
        (r"C:\Users\shimr\Desktop\config.toml", None, False),
        ("/usr/local/bin/python3", None, False),
        ("./src/main.py", None, False),
        # The Hebrew side, which is the half both_ways buys.
        ("מקלדת", EN, True),
        ("האם זה עובד?", EN, False),
        # 9 Hebrew letters against 11 Latin: counted by letters this is
        # "English" and comes back in the language it was already in.
        ("תעשה commit לפני ה-merge", EN, False),
        # And the same rule the other way round.
        ("The word מקלדת means keyboard in Hebrew.", HE, False),
        # Code, which is never a dictionary lookup however short it is.
        ("x = y + 1", HE, False),
        ("foo()", HE, False),
        ("a > b", HE, False),
        ("git push --force", HE, False),
        ("if (ptr == NULL) return;", HE, False),
    ]
    assert len(cases) == 34, len(cases)
    for text, target, word in cases:
        got = lookup_mod.lookup_target(text)
        assert got == target, (ascii(text)[:60], got, target)
        assert lookup_mod.is_word_lookup(text) is word, ascii(text)[:60]
    # needs_hebrew is the strict mirror of translate.needs_translation:
    # English in, Hebrew out, and never the reverse.
    assert lookup_mod.needs_hebrew("brittle")
    assert not lookup_mod.needs_hebrew("מקלדת")
    # The length guard belongs to the same function and costs nothing.
    assert lookup_mod.lookup_target("a" * 6000) is None
    assert lookup_mod.lookup_target("a" * 4999) == HE


def test_the_answer_cache_forgets_the_oldest_and_survives_a_restart() -> None:
    """The cache is why the key is worth pressing twice: measured
    2026-08-19, a repeat goes from 2.27 s to 0.00002 s and costs no
    request. It also removes jitter — gemma3:12b answered "debounce" two
    different ways on two runs at temperature 0.2, and a box that says
    something different every time reads as an app that is unsure. All of
    which is worth nothing if the file grows without bound or does not
    survive a restart."""
    import tempfile

    import lookup as lookup_mod

    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "lookup_cache.json"
        cache = lookup_mod.Cache(path, max_entries=3, max_chars=200)
        for word in ("one", "two", "three"):
            cache.put("Hebrew", "word", word, "answer-" + word)
        assert cache.get("Hebrew", "word", "one") == "answer-one"
        cache.put("Hebrew", "word", "four", "answer-four")
        # "one" was read a moment ago, so the oldest thing here is "two".
        # Least-recently-USED and not least-recently-written: the words you
        # keep looking up are the ones worth keeping.
        assert len(cache) == 3, len(cache)
        assert cache.get("Hebrew", "word", "two") is None
        assert cache.get("Hebrew", "word", "one") == "answer-one"

        # A restart reads the same answers back off disk.
        again = lookup_mod.Cache(path, max_entries=3, max_chars=200)
        assert again.get("Hebrew", "word", "four") == "answer-four"
        assert len(again) == 3, len(again)

        # Whitespace is collapsed, so the same phrase selected across a
        # line break is the same question.
        again.put("Hebrew", "phrase", "race  condition", "תנאי מרוץ")
        assert again.get("Hebrew", "phrase",
                         "race\ncondition") == "תנאי מרוץ"
        # Direction and mode are in the key: the same word asked for as a
        # dictionary entry and as a sentence are two different questions.
        assert again.get("English", "phrase", "race condition") is None
        assert again.get("Hebrew", "word", "race condition") is None

        # A paragraph is a one-off. Keeping it would grow the file for a
        # hit that never comes.
        paragraph = "x" * 201
        again.put("Hebrew", "phrase", paragraph, "never kept")
        assert again.get("Hebrew", "phrase", paragraph) is None


def _lookup_app(tmp, fake_injector, answer):
    """An app whose lookup engine hands back a fixed answer — what these
    tests are about is everything AROUND the model: which way it was
    asked, which note played, what stood in the box and what happened to
    the clipboard."""
    import main as main_mod

    app = _worker_app(_Flaky(fail_times=0), tmp)
    main_mod.injector = fake_injector

    class _Fixed:
        def __init__(self, reply):
            self.answer, self.asked = reply, []

        def look_up(self, text, decision=None, on_status=None,
                    on_chunk=None, on_progress=None):
            self.asked.append(text)
            if isinstance(self.answer, Exception):
                raise self.answer
            import lookup as lookup_mod
            return lookup_mod.Answer(self.answer, decision.target,
                                     decision.mode, "fake", 0.1)

    app._lookup_engine = _Fixed(answer)
    return app


def test_a_lookup_puts_the_answer_on_screen_and_changes_nothing() -> None:
    """The whole key in one test. The box goes up holding an ellipsis
    BEFORE the model is asked, because the answer is 1-3 s warm and 25 s
    cold and a key that shows nothing for that long has already been
    pressed again. The answer replaces it. The direction is the one the
    ANSWER is written in and never the one the selection was. And then the
    part that makes this a lookup rather than a translation: over both
    directions, not one call was made that could change anything on
    screen."""
    import shutil
    import tempfile

    import main as main_mod

    tmp = Path(tempfile.mkdtemp(prefix="dictation-lookup-"))
    fake = _FakeInjector()
    real_inj = main_mod.injector
    played, restore = _cue_spy(main_mod)
    try:
        app = _lookup_app(tmp, fake, "שביר")
        fake.selection = "brittle"
        app._lookup(fake.focus)
        assert app.popup.shown == [("…", True)], app.popup.shown
        assert app.popup.last == ("שביר", True), app.popup.last
        assert played == ["looking", "looked"], played
        assert app._stats["lookups"] == 1, app._stats
        assert app._lookup_engine.asked == ["brittle"], \
            app._lookup_engine.asked

        # Hebrew in, English out, laid out the other way.
        app._lookup_engine.answer = "fragile"
        fake.selection = "שביר"
        app._lookup(fake.focus)
        assert app.popup.shown[-1] == ("…", False), app.popup.shown
        assert app.popup.last == ("fragile", False), app.popup.last
        assert played == ["looking", "looked"] * 2, played
        assert app._stats["lookups"] == 2, app._stats

        assert ("restore", "whatever the user had") in fake.calls
        wrote = [c for c in fake.calls if c[0] not in ("read", "restore")]
        assert not wrote, wrote
    finally:
        restore()
        main_mod.injector = real_inj
        shutil.rmtree(tmp, ignore_errors=True)


def test_the_word_that_was_looked_up_goes_in_the_title_bar() -> None:
    """The box is handed an answer and never sees the question.

    So the word has to travel with it, and it travels on the show() that
    puts the ellipsis up — readable while the model is still thinking,
    and still there afterwards. That matters because the box outlives the
    selection it was opened over: dragged aside, or read once the
    highlight has gone, the bar is the only thing on screen still saying
    which word this is an answer to.

    Cut, because it is a caption and not the selection. lookup.max_chars
    allows 20000 characters and only about 45 Hebrew ones fit in the bar,
    which paints the label with DT_END_ELLIPSIS on every repaint —
    measured 2026-08-20 (at the then-cap of 5000), a maxed-out term costs
    7.3 ms a paint against 0.6 ms for a whole repaint of the box, and a
    repaint happens on every mouse move while a selection is being
    dragged inside it.
    """
    import shutil
    import tempfile

    import main as main_mod

    tmp = Path(tempfile.mkdtemp(prefix="dictation-lookup-term-"))
    fake = _FakeInjector()
    real_inj = main_mod.injector
    played, restore = _cue_spy(main_mod)
    try:
        app = _lookup_app(tmp, fake, "שביר")
        fake.selection = "brittle"
        app._lookup(fake.focus)
        assert app.popup.terms == ["brittle"], app.popup.terms

        fake.selection = "brittle " * 2600        # 20800 chars, refused
        app._lookup(fake.focus)                    # nothing new on screen
        assert len(app.popup.terms) == 1, app.popup.terms

        fake.selection = "brittle " * 60           # 480 chars, allowed
        app._lookup(fake.focus)
        assert len(app.popup.terms[-1]) == 120, len(app.popup.terms[-1])
        assert fake.selection.startswith(app.popup.terms[-1])
    finally:
        restore()
        main_mod.injector = real_inj
        shutil.rmtree(tmp, ignore_errors=True)


def test_five_presses_with_nothing_selected_play_one_note() -> None:
    """Pressing a key that seems not to have worked is exactly what a
    person does next, so the answer has to be given once and not once per
    press — the same defect the correction key had (nine presses in five
    seconds on 2026-08-14, nine cues, heard as one long fault). Nothing is
    shown, nothing is asked of any backend, and the clipboard comes back
    all five times."""
    import shutil
    import tempfile

    import main as main_mod

    tmp = Path(tempfile.mkdtemp(prefix="dictation-lookup-empty-"))
    fake = _FakeInjector()
    real_inj = main_mod.injector
    played, restore = _cue_spy(main_mod)
    try:
        app = _lookup_app(tmp, fake, "never reached")
        fake.selection, fake.selection_reason = "", "nothing-selected"
        for _ in range(5):
            app._lookup(fake.focus)
        assert played == ["noop"], played
        assert app.popup.shown == [], app.popup.shown
        assert app._lookup_engine.asked == [], app._lookup_engine.asked
        assert app._stats["lookups"] == 0, app._stats
        assert "nothing selected" in app._note, app._note
        assert fake.calls.count(("restore", "whatever the user had")) == 5, \
            fake.calls
    finally:
        restore()
        main_mod.injector = real_inj
        shutil.rmtree(tmp, ignore_errors=True)


def test_a_backend_that_will_not_answer_says_so_in_the_box() -> None:
    """A box left holding "…" for ever is the key looking broken rather
    than the model being down. The failure line is written in the language
    the box was OPENED for, because the direction is fixed when it opens
    and a Hebrew line in a left-to-right box comes out backwards."""
    import shutil
    import tempfile

    import main as main_mod
    import translate as translate_mod

    tmp = Path(tempfile.mkdtemp(prefix="dictation-lookup-down-"))
    fake = _FakeInjector()
    real_inj = main_mod.injector
    played, restore = _cue_spy(main_mod)
    try:
        app = _lookup_app(tmp, fake,
                          translate_mod.TranslationError("no model"))
        fake.selection = "brittle"
        for _ in range(5):
            app._lookup(fake.focus)
        assert app.popup.last == ("לא הצלחתי לתרגם — הדגם לא ענה", True), \
            app.popup.last
        # The working note is per press — a request really was sent each
        # time — but the fault is answered once.
        assert played.count("looking") == 5, played
        assert played.count("error") == 1, played
        assert played.count("looked") == 0, played
        assert app._stats["lookups"] == 0, app._stats
        assert "could not look that up" in app._note, app._note
        assert fake.calls.count(("restore", "whatever the user had")) == 5, \
            fake.calls

        # The other direction gets the other line, for the same reason.
        fake.selection = "שביר"
        app._lookup(fake.focus)
        assert app.popup.last == (
            "could not look that up — the model did not answer", False), \
            app.popup.last
    finally:
        restore()
        main_mod.injector = real_inj
        shutil.rmtree(tmp, ignore_errors=True)


def test_a_selection_it_refuses_costs_no_request_at_all() -> None:
    """The refusals are the cheap half of this key: they happen before
    anything is contacted, so a mistaken press spends nothing. They are
    told apart on purpose — "that is 22000 characters" and "that is a URL"
    are two different answers, and each gets its own once-per-4s budget
    even though the note is the same one."""
    import shutil
    import tempfile

    import main as main_mod

    tmp = Path(tempfile.mkdtemp(prefix="dictation-lookup-big-"))
    fake = _FakeInjector()
    real_inj = main_mod.injector
    played, restore = _cue_spy(main_mod)
    try:
        app = _lookup_app(tmp, fake, "never reached")
        fake.selection = "word " * 4400        # past lookup.max_chars
        for _ in range(3):
            app._lookup(fake.focus)
        assert app._lookup_engine.asked == [], app._lookup_engine.asked
        assert app.popup.shown == [], app.popup.shown
        assert played == ["noop"], played
        assert "too much to look up" in app._note, app._note

        fake.selection = "https://example.com/a/b"
        app._lookup(fake.focus)
        assert app._lookup_engine.asked == [], app._lookup_engine.asked
        assert app.popup.shown == [], app.popup.shown
        assert played == ["noop", "noop"], played
        assert "nothing to translate" in app._note, app._note
    finally:
        restore()
        main_mod.injector = real_inj
        shutil.rmtree(tmp, ignore_errors=True)


def test_long_selections_reach_the_local_model_in_parts() -> None:
    """Select-all used to be refused outright at lookup.max_chars = 5000,
    which the owner read as "it didn't translate". Now the LOCAL path
    feeds gemma3 in ~3800-char pieces — inside the runner's context
    window — joined with newlines, with progress between parts. Gemini is
    never chunked: its API takes the whole selection in one request and
    always did.
    """
    import lookup as lookup_mod

    class Backend:
        name = "ollama"

        def __init__(self):
            self.asked = []

        def translate(self, text):
            self.asked.append(len(text))
            return f"[{len(self.asked)}]"

    text = "\n".join(f"paragraph {i} " + "word " * 90
                     for i in range(120))          # ~12k chars of prose
    assert len(text) > lookup_mod._LOCAL_CHUNK * 2, \
        "the sample must force several parts"

    backend = Backend()
    got = lookup_mod.translate_chunked(backend, text)
    assert len(backend.asked) >= 2, "one request for 12k chars"
    assert all(n <= lookup_mod._LOCAL_CHUNK for n in backend.asked), \
        backend.asked
    assert sum(backend.asked) <= len(text), "parts grew beyond the source"
    assert got.startswith("[1]") and got.count("[") == len(backend.asked)

    # Progress fires before each part AFTER the first, never before it.
    seen = []
    second = Backend()
    lookup_mod.translate_chunked(second, text,
                                 lambda i, n: seen.append((i, n)))
    assert seen[0] == (2, len(second.asked)), seen
    assert seen[-1] == (len(second.asked), len(second.asked)), seen

    # A Gemini-shaped backend takes the whole thing in one request.
    class Cloud(Backend):
        name = "gemini"

    cloud = Cloud()
    lookup_mod.translate_chunked(cloud, text)
    assert cloud.asked == [len(text)], cloud.asked


def test_the_local_splitter_cuts_where_prose_allows() -> None:
    """The parts must each fit the request, must never start or end in
    stray whitespace, and — unless a paragraph has no sentence end at all
    — must cut at a sentence boundary rather than mid-word."""
    import lookup as lookup_mod

    limit = 400
    sentences = ("משפט ראשון נגמר כאן. משפט שני בא אחריו. "
                 "והנה משפט שלישי ארוך יחסית במידה זו. ")
    text = sentences * 60                      # ~5k chars, one paragraph
    parts = lookup_mod._split_for_local(text, limit)
    assert len(parts) >= 2, "one part for 5k chars against a 400 limit"
    total = 0
    for part in parts:
        assert 0 < len(part) <= limit, (len(part), limit)
        assert part == part.strip(), repr(part[:20])
        assert part.rstrip().endswith((".")), repr(part[-20:])
        total += len(part)
    assert total >= int(len(text) * 0.9), (total, len(text))

    # No sentence punctuation anywhere: the hard-cut last resort still
    # bounds every piece.
    run = "אבגד" * 1500                         # 6000 chars, no breaks
    hard = lookup_mod._split_for_local(run, limit)
    assert all(len(part) <= limit for part in hard), \
        [len(p) for p in hard]
    assert "".join(hard) == run, "the hard cut lost characters"


def test_the_clipboard_comes_back_on_every_way_out() -> None:
    """Read-only has to mean read-only on the paths that go wrong too.
    Four ways out — an answer, an empty selection, a refusal before any
    request, and a backend that raised — and the clipboard is handed back
    on all four, with nothing else touched on any of them.

    The mechanism underneath is asserted rather than assumed: the restore
    lives in a finally and not after the loop, because anything raising
    between the copy and the restore leaves the user's clipboard holding
    the text that was captured (verified destroyed 3/3 without it,
    survived 2/2 with it)."""
    import ast
    import inspect
    import shutil
    import tempfile

    import main as main_mod
    import translate as translate_mod

    tmp = Path(tempfile.mkdtemp(prefix="dictation-lookup-clip-"))
    real_inj = main_mod.injector
    played, restore = _cue_spy(main_mod)
    try:
        ways_out = [
            ("an answer", "brittle", "שביר"),
            ("nothing selected", "", "never reached"),
            ("nothing to translate", "https://example.com/a",
             "never reached"),
            ("the backend refused", "brittle",
             translate_mod.TranslationError("no model")),
        ]
        for label, selection, answer in ways_out:
            fake = _FakeInjector()
            app = _lookup_app(tmp, fake, answer)
            fake.selection = selection
            fake.selection_reason = "ok" if selection else "nothing-selected"
            app._lookup(fake.focus)
            assert fake.calls.count(
                ("restore", "whatever the user had")) == 1, (label,
                                                             fake.calls)
            assert not [c for c in fake.calls
                        if c[0] not in ("read", "restore")], (label,
                                                              fake.calls)

        source = inspect.getsource(injector.read_selection)
        tree = ast.parse(source)

        def _restores(body):
            return any(isinstance(node, ast.Name)
                       and node.id == "_restore_if_touched"
                       for statement in body
                       for node in ast.walk(statement))

        assert any(isinstance(node, ast.Try) and _restores(node.finalbody)
                   for node in ast.walk(tree)), \
            ("read_selection puts the clipboard back outside a finally — "
             "anything raising between the copy and the restore then "
             "leaves the captured text sitting in the user's clipboard")
    finally:
        restore()
        main_mod.injector = real_inj
        shutil.rmtree(tmp, ignore_errors=True)


def test_a_lookup_holds_the_cursor_only_while_it_reads() -> None:
    """_translate holds _cursor_lock across the whole 1-3 s model call
    because it is going to paste at the end and the cursor has to still be
    where it found it. This key has nothing to paste: holding the lock
    that long would be a dictation waiting seconds on a clipboard nobody
    is using any more. Asserted from inside both halves, because the
    difference is invisible from outside."""
    import shutil
    import tempfile

    import main as main_mod

    tmp = Path(tempfile.mkdtemp(prefix="dictation-lookup-lock-"))
    fake = _FakeInjector()
    real_inj = main_mod.injector
    played, restore = _cue_spy(main_mod)
    try:
        app = _lookup_app(tmp, fake, "שביר")
        fake.selection = "brittle"
        seen: list[tuple[str, bool]] = []
        fake.on_read = lambda: seen.append(
            ("reading", app._cursor_lock.locked()))
        engine = app._lookup_engine
        asked = engine.look_up

        def watched(text, decision=None, on_status=None, on_chunk=None, on_progress=None):
            seen.append(("asking the model", app._cursor_lock.locked()))
            return asked(text, decision, on_status, on_chunk)

        engine.look_up = watched
        app._lookup(fake.focus)
        assert seen == [("reading", True),
                        ("asking the model", False)], seen
        assert not app._cursor_lock.locked(), "the lock was left held"
    finally:
        restore()
        main_mod.injector = real_inj
        shutil.rmtree(tmp, ignore_errors=True)


def test_the_lookup_key_takes_turns_with_itself_and_nobody_else() -> None:
    """One clipboard, so a second press while one is in flight is dropped
    — but a press of a TEXT key is not. They queue separately on purpose:
    by the time the lookup's model answers it has long since given the
    clipboard back, so making F9 wait for it would buy nothing."""
    import shutil
    import tempfile

    import main as main_mod

    tmp = Path(tempfile.mkdtemp(prefix="dictation-lookup-turns-"))
    fake = _FakeInjector()
    real_inj = main_mod.injector
    played, restore = _cue_spy(main_mod)
    try:
        main_mod.injector = fake
        app = _worker_app(_Flaky(fail_times=0), tmp)
        app._on_tap("lookup")
        assert app.lookup_queue.qsize() == 1, app.lookup_queue.qsize()
        # A pair now: the window the selection is in, and the mouse point
        # the answer has to appear beside. Both are read on the hook
        # thread because both are only true at the moment of the press.
        hwnd, anchor = app.lookup_queue.get()
        assert hwnd == fake.focus, hwnd
        assert anchor is None or (len(anchor) == 2
                                  and all(isinstance(v, int)
                                          for v in anchor)), anchor
        app._on_tap("lookup")                  # the first is still running
        assert app.lookup_queue.qsize() == 0, app.lookup_queue.qsize()
        assert played == ["noop"], played

        app._on_tap("translate")               # a different queue entirely
        assert app.text_queue.get() == ("translate", fake.focus)

        app._looking_up.clear()                # the worker finished
        app._on_tap("lookup")
        assert app.lookup_queue.get()[0] == fake.focus
    finally:
        restore()
        main_mod.injector = real_inj
        shutil.rmtree(tmp, ignore_errors=True)


def test_the_box_opens_where_the_key_was_pressed_and_waits_to_be_closed(
) -> None:
    """Two decisions main.py makes on every press, and nowhere else.

    The anchor, because the box used to appear in the bottom-right corner
    of the screen whatever you were reading — an answer about a word in
    the top-left of a browser window, 1500 px away from it. The mouse
    point is what makes it appear beside the word instead: a selection is
    made by dragging across it, so the cursor is left at the end of what
    was selected. WHERE the box then lands is popup.py's arithmetic and is
    proved there; that it is handed the point at all is this.

    And dwell_ms = 0, which is the owner's actual complaint. It used to be
    handed lookup.dwell_ms — 12 s — so an answer he was still reading took
    itself away, and a box that vanishes on a timer is indistinguishable
    from one that vanished because of a bug. It waits to be closed now.
    """
    import shutil
    import tempfile

    import main as main_mod

    tmp = Path(tempfile.mkdtemp(prefix="dictation-lookup-anchor-"))
    fake = _FakeInjector()
    real_inj = main_mod.injector
    played, restore = _cue_spy(main_mod)
    try:
        app = _lookup_app(tmp, fake, "שביר")
        fake.selection = "brittle"
        app._lookup(fake.focus, (1234, 567))
        assert app.popup.anchors == [(1234, 567)], app.popup.anchors
        assert app.popup.dwells == [0], app.popup.dwells

        # And it survives the answer landing on top of the ellipsis:
        # popup.update re-places from the anchor show() was given, so the
        # box grows away from the text rather than moving out from under
        # the eyes reading it. One show, one anchor, however long the
        # answer turns out to be.
        assert app.popup.last == ("שביר", True), app.popup.last
        assert len(app.popup.anchors) == 1, app.popup.anchors

        # No anchor is not a failure. The CLI probe and anything that
        # cannot say where it was pointing get the corner, which is where
        # this box appeared before any of it.
        app._lookup(fake.focus)
        assert app.popup.anchors[-1] is None, app.popup.anchors
    finally:
        restore()
        main_mod.injector = real_inj
        shutil.rmtree(tmp, ignore_errors=True)


def test_a_refusal_takes_down_the_answer_to_the_last_question() -> None:
    """A box that waits to be closed can be left telling a lie.

    Every "nothing to look up" path returns without putting anything in
    the box. That was harmless while a tap closed the box first, and
    stopped being harmless the moment a tap started asking a new question
    instead: select a URL, tap, and the answer to the PREVIOUS word would
    sit there while the cue said nothing had happened. The honest report
    is an empty screen — the key was pressed, there was nothing to look
    up, so there is nothing to see.
    """
    import shutil
    import tempfile

    import main as main_mod

    tmp = Path(tempfile.mkdtemp(prefix="dictation-lookup-refuse-"))
    fake = _FakeInjector()
    real_inj = main_mod.injector
    played, restore = _cue_spy(main_mod)
    try:
        app = _lookup_app(tmp, fake, "שביר")
        fake.selection = "brittle"
        app._lookup(fake.focus, (400, 300))
        assert app.popup.visible(), "the answer never went up"

        # Every refusal, one at a time, each starting from a box that is
        # up: a URL, nothing selected, and more than max_chars.
        for selection in ("https://example.com/a/b", "   ",
                          "word " * 4400):
            before = len(app._lookup_engine.asked)
            fake.selection = selection
            app._lookup(fake.focus, (400, 300))
            assert not app.popup.visible(), \
                f"{selection[:20]!r} left the last answer standing"
            assert len(app._lookup_engine.asked) == before, \
                f"{selection[:20]!r} was sent to the model"
            fake.selection = "brittle"
            app._lookup(fake.focus, (400, 300))
            assert app.popup.visible()
    finally:
        restore()
        main_mod.injector = real_inj
        shutil.rmtree(tmp, ignore_errors=True)


def test_pausing_takes_the_lookup_box_with_it() -> None:
    """Nothing dismisses this box on its own any more, so pausing has to.

    The pause key exists so the owner can start a game without Right Ctrl
    starting recordings, and the fullscreen watcher presses it for him. An
    always-on-top box left sitting over that game is exactly the intrusion
    pausing was asked to stop — and with no dwell to take it away, it
    would sit there for as long as the app ran.

    Driven through _on_pause rather than through the key, because that is
    the one funnel both ways in go through: the pause key reaches it via
    the state machine, and the dashboard's button reaches it via
    set_paused. Putting the take-down anywhere else would cover one of
    them and not the other.
    """
    import shutil
    import tempfile

    import main as main_mod

    tmp = Path(tempfile.mkdtemp(prefix="dictation-lookup-pause-"))
    fake = _FakeInjector()
    real_inj = main_mod.injector
    played, restore = _cue_spy(main_mod)
    try:
        app = _lookup_app(tmp, fake, "שביר")
        app._auto_paused = False
        app.dot = type("_Dot", (), {"set_state": lambda self, s: None})()
        fake.selection = "brittle"
        app._lookup(fake.focus, (400, 300))
        assert app.popup.visible(), "the answer never went up"

        app._on_pause(True)
        assert not app.popup.visible(), \
            "the box outlived the pause it was supposed to get out of"
        assert app.popup.hidden == 1, app.popup.hidden

        # Resuming does not bring it back: there is nothing to bring back,
        # and an answer reappearing minutes later would be a ghost.
        app._on_pause(False)
        assert not app.popup.visible(), app.popup.shown
        assert app.popup.hidden == 1, app.popup.hidden
    finally:
        restore()
        main_mod.injector = real_inj
        shutil.rmtree(tmp, ignore_errors=True)


def test_the_answer_is_painted_by_the_line_and_never_by_the_token() -> None:
    """The box shows the answer arriving, without shaking while it does.

    lookup.py hands over every token the local model writes — one every
    24 ms, measured against real Ollama on 2026-08-19 — and each repaint
    re-lays-out and RESIZES the window. Painted per token, a two-second
    answer resizes the box forty times, which reads as jitter rather than
    as speed. Painted on a newline or after 80 ms, the same answer takes
    12-15 paints and each one is the box gaining a line.

    The last word belongs to the finished answer, not to the last partial:
    on_chunk is given the RAW stream, fences and stray quotes included,
    and the update after look_up returns is what replaces it with the
    cleaned, niqqud-stripped text.
    """
    import shutil
    import tempfile

    import main as main_mod

    tmp = Path(tempfile.mkdtemp(prefix="dictation-lookup-stream-"))
    fake = _FakeInjector()
    real_inj = main_mod.injector
    played, restore = _cue_spy(main_mod)
    try:
        app = _lookup_app(tmp, fake, "שביר")
        fake.selection = "brittle"

        class _Streaming:
            """40 tokens, 24 ms apart, four of them ending a line."""

            asked: list[str] = []

            def look_up(self, text, decision=None, on_status=None,
                        on_chunk=None, on_progress=None):
                import lookup as lookup_mod
                self.asked.append(text)
                so_far = ""
                for i in range(40):
                    so_far += "\n" if i and i % 10 == 0 else "x"
                    on_chunk(so_far)
                    time.sleep(0.024)
                return lookup_mod.Answer("שביר", decision.target,
                                         decision.mode, "fake", 1.0)

        app._lookup_engine = _Streaming()
        app._lookup(fake.focus, (400, 300))

        partials = app.popup.updates[:-1]
        assert 4 <= len(partials) <= 20, \
            f"40 tokens became {len(partials)} paints"
        assert len(partials) < 40, "the box was painted per token"
        # Every partial is a prefix of the next: the box shows the answer
        # growing, never a fragment of it out of order.
        assert partials == sorted(partials, key=len), partials
        for earlier, later in zip(partials, partials[1:]):
            assert later.startswith(earlier), (earlier, later)
        # The finished answer has the last word.
        assert app.popup.updates[-1] == "שביר", app.popup.updates[-1]
        assert app.popup.last == ("שביר", True), app.popup.last
    finally:
        restore()
        main_mod.injector = real_inj
        shutil.rmtree(tmp, ignore_errors=True)


def test_a_second_tap_asks_again_instead_of_closing_the_box() -> None:
    """A reversal, and the reason for it is the whole feature.

    A second tap used to CLOSE the open box and stop there. That was right
    while the box dismissed itself after a dwell — the key that opened it
    was the obvious key to shut it. It became wrong the moment the box
    started waiting to be closed on purpose, because it turned the
    commonest use of this key into a no-op: select a second word, tap, and
    all that happens is the first answer disappearing. The box has a
    button of its own now, and Esc; this key is for asking.

    The busy flag is the only thing that still refuses a press, and it
    means something narrower than "a box is on screen": one clipboard, one
    selection, one answer being written.
    """
    import shutil
    import tempfile

    import main as main_mod

    tmp = Path(tempfile.mkdtemp(prefix="dictation-lookup-toggle-"))
    fake = _FakeInjector()
    real_inj = main_mod.injector
    played, restore = _cue_spy(main_mod)
    try:
        main_mod.injector = fake
        app = _worker_app(_Flaky(fail_times=0), tmp)
        app.popup.show("שביר", rtl=True)
        app._on_tap("lookup")
        assert app.lookup_queue.qsize() == 1, app.lookup_queue.qsize()
        assert app._looking_up.is_set(), "a lookup was queued without the flag"
        assert app.popup.hidden == 0, \
            "the tap closed the box instead of asking a new question"
        assert played == [], played     # the cue belongs to the worker

        # ...and the busy flag, which is what a real second press hits
        # while the first answer is still being written, still refuses.
        app._on_tap("lookup")
        assert app.lookup_queue.qsize() == 1, app.lookup_queue.qsize()
        assert played == ["noop"], played
    finally:
        restore()
        main_mod.injector = real_inj
        shutil.rmtree(tmp, ignore_errors=True)


# ------------------------------------------- reading the log back out
#
# transcripts.log is the record. The history screen is a READER of it, and
# everything below is about the three places where "one line" and "one
# thing that happened" are not the same number.


def _log_with(lines: list[str], monkey=None):
    """A transcripts.log of our own, with history pointed at it."""
    import history as history_mod
    tmp = Path(tempfile.mkdtemp(prefix="dictation-history-"))
    path = tmp / "transcripts.log"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    history_mod.LOG = path
    return tmp, path


def _restore_log(tmp) -> None:
    import shutil

    import history as history_mod
    history_mod.LOG = history_mod.APP_DIR / "transcripts.log"
    shutil.rmtree(tmp, ignore_errors=True)


def test_a_translation_is_one_entry_and_keeps_both_halves() -> None:
    """TRANSLATE-IN and TRANSLATE-OUT are one act — asking for a
    translation — written down twice because that is how a log works."""
    import history as history_mod
    tmp, _path = _log_with([
        "2026-08-20 10:00:00,000 | TRANSLATE-IN  | selection | שלום עולם",
        "2026-08-20 10:00:01,000 | TRANSLATE-OUT | 0.8s | gemini | Hello world",
    ])
    try:
        events = history_mod.load(10)
        assert len(events) == 1, events
        assert events[0].kind == "translate"
        assert events[0].text == "Hello world"
        assert events[0].source == "שלום עולם", events[0].source
        # The row is stamped when it was ASKED for, not when the answer
        # came back: sorted by the reply, a slow translation jumps ahead of
        # the dictation that came after it.
        assert events[0].when.second == 0, events[0].when
    finally:
        _restore_log(tmp)


def test_a_polished_dictation_is_one_entry_not_two() -> None:
    """OK is what Whisper heard and POLISHED is the same sentence with the
    misheard words repaired. Two rows means the sentence twice, one of
    them wrong."""
    import history as history_mod
    tmp, _path = _log_with([
        "2026-08-20 10:00:00,000 | OK | 4.0s | local | 0.5s latency | ראש הממשלה",
        "2026-08-20 10:00:02,000 | POLISHED | 1.2s | ollama | ראש הממשלה נאם",
    ])
    try:
        events = history_mod.load(10)
        assert len(events) == 1, events
        assert events[0].polished, "the row does not say it was polished"
        assert events[0].text == "ראש הממשלה נאם"
        assert events[0].source == "ראש הממשלה", "the raw text was thrown away"
        assert "polished" in events[0].meta()
    finally:
        _restore_log(tmp)


def test_a_correction_becomes_the_words_that_changed() -> None:
    """CORRECTED is two whole sentences that differ in one word. The pair
    is what the eye wants; the sentences are what the file has."""
    import history as history_mod
    tmp, _path = _log_with([
        "2026-08-20 10:00:00,000 | CORRECTED | אני רוצה היוזר || אני רוצה ה-user",
    ])
    try:
        events = history_mod.load(10)
        assert len(events) == 1
        assert events[0].pairs == [("היוזר", "ה-user")], events[0].pairs
        assert events[0].note == "1 word", events[0].note
    finally:
        _restore_log(tmp)


def test_a_rewritten_sentence_claims_no_word_pairs() -> None:
    """Different lengths mean the correction was not a word swap, and
    guessing pairs out of it would put a change on screen that nobody
    made."""
    import history as history_mod
    assert history_mod.changed_words("one two three", "one two") == []
    assert history_mod.changed_words("", "") == []


def test_a_transcript_containing_a_pipe_is_not_cut_in_half() -> None:
    """The fields are separated by pipes and the last field is a sentence
    somebody said out loud. Say "pipe" and Whisper writes one down."""
    import history as history_mod
    tmp, _path = _log_with([
        "2026-08-20 10:00:00,000 | OK | 4.0s | local | 0.5s latency | "
        "run a | b | c and see",
    ])
    try:
        events = history_mod.load(10)
        assert events[0].text == "run a | b | c and see", events[0].text
    finally:
        _restore_log(tmp)


def test_a_dictated_newline_does_not_become_its_own_entry() -> None:
    """A transcript is written raw, newlines and all. A reader that takes
    every line as a record shows half a sentence with the wrong time on
    it."""
    import history as history_mod
    tmp, _path = _log_with([
        "2026-08-20 10:00:00,000 | OK | 4.0s | local | 0.5s latency | first",
        "second line of the same thing",
    ])
    try:
        events = history_mod.load(10)
        assert len(events) == 1, events
        assert "second line" in events[0].text, events[0].text
    finally:
        _restore_log(tmp)


def test_the_newest_thing_that_happened_is_at_the_top() -> None:
    import history as history_mod
    tmp, _path = _log_with([
        "2026-08-20 10:00:00,000 | OK | 1.0s | local | 0.1s latency | older",
        "2026-08-20 11:00:00,000 | OK | 1.0s | local | 0.1s latency | newer",
    ])
    try:
        events = history_mod.load(10)
        assert [e.text for e in events] == ["newer", "older"], events
    finally:
        _restore_log(tmp)


def test_a_phone_dictation_says_where_it_came_from() -> None:
    """The phone route has no backend field, so reading it like a desktop
    dictation puts the latency where the engine goes."""
    import history as history_mod
    tmp, _path = _log_with([
        "2026-08-20 10:00:00,000 | OK | PHONE | 3.1s | 0.4s latency | from afar",
    ])
    try:
        event = history_mod.load(10)[0]
        assert event.phone and "from the phone" in event.meta()
        assert event.text == "from afar", event.text
        assert event.seconds == 3.1 and event.latency == 0.4
    finally:
        _restore_log(tmp)


def test_a_broken_line_is_skipped_rather_than_repaired() -> None:
    """Half a line is what a log looks like when the process died mid
    write. It must cost that entry and nothing else."""
    import history as history_mod
    tmp, _path = _log_with([
        "this is not a log line at all",
        "2026-08-20 99:99:99,000 | OK | 1.0s | local | 0.1s latency | bad stamp",
        "2026-08-20 10:00:00,000 | OK | 1.0s | local | 0.1s latency | good",
    ])
    try:
        events = history_mod.load(10)
        assert [e.text for e in events] == ["good"], events
    finally:
        _restore_log(tmp)


def test_the_filters_only_offer_kinds_the_reader_can_produce() -> None:
    """A chip for a kind nothing is ever tagged with is a filter that
    always comes back empty."""
    import history as history_mod
    for name, kind in history_mod.FILTERS:
        assert name, "a chip with no label"
        assert kind is None or kind in history_mod.KINDS, kind


def test_searching_looks_at_what_went_in_as_well_as_what_came_out() -> None:
    import history as history_mod
    tmp, _path = _log_with([
        "2026-08-20 10:00:00,000 | TRANSLATE-IN  | selection | ברוכים הבאים",
        "2026-08-20 10:00:01,000 | TRANSLATE-OUT | 0.8s | gemini | welcome",
    ])
    try:
        events = history_mod.load(10)
        assert history_mod.filtered(events, None, "welcome")
        assert history_mod.filtered(events, None, "ברוכים"), \
            "the text that was translated is not searchable"
        assert not history_mod.filtered(events, "dictation", "welcome")
    finally:
        _restore_log(tmp)


# ------------------------------------------------- the window's drawing kit


def _tk_or_skip():
    """A Tk root, or None with a note — the same shape as the icon test."""
    import tkinter as tk

    import ui as ui_mod
    try:
        ui_mod.forget_images()
        return tk.Tk()
    except Exception as e:
        print(f"    (skipped: no Tk window — {e})")
        return None


def test_wrapping_never_overflows_the_box_it_was_measured_for() -> None:
    """The whole point of measuring here rather than letting Tk wrap is
    that the height of a row and the text in it agree. A line wider than
    the box it was drawn for is the failure that reaches the screen."""
    import ui as ui_mod
    root = _tk_or_skip()
    if root is None:
        return
    try:
        samples = [
            "אני רוצה שתעשה משהו כזה תסתכל על האפליקציה שלי ותבצע כזה דבר "
            "כרגע היא נראית נורא ישנה",
            "a short one",
            "supercalifragilisticexpialidociousandthensome" * 3,
            "",
        ]
        for text in samples:
            for width in (120, 300, 546):
                shown, lines = ui_mod.clamp(text, ui_mod.TEXT, 11, width, 2)
                assert lines <= 2, (lines, text[:20])
                assert lines == len(shown.split("\n")) or not shown
                for line in shown.split("\n"):
                    got = ui_mod.text_width(line, ui_mod.TEXT, 11)
                    assert got <= width, (got, width, line)
    finally:
        root.destroy()


def test_a_wrapped_line_keeps_every_word_it_started_with() -> None:
    """Estimating where the break goes is only allowed to move the break."""
    import ui as ui_mod
    root = _tk_or_skip()
    if root is None:
        return
    try:
        text = "one two three four five six seven eight nine ten"
        shown, _lines = ui_mod.clamp(text, ui_mod.UI, 9, 400, 4)
        assert shown.replace("\n", " ") == text, shown
    finally:
        root.destroy()


def test_a_hundred_rows_of_the_same_size_share_one_bitmap() -> None:
    """Every rounded rectangle is a decoded image. A hundred history rows
    that each make their own is a hundred times the memory and the wait."""
    import ui as ui_mod
    root = _tk_or_skip()
    if root is None:
        return
    try:
        first = ui_mod.rounded(680, 66, 12, ui_mod.CARD, ui_mod.PANE)
        again = ui_mod.rounded(680, 66, 12, ui_mod.CARD, ui_mod.PANE)
        assert first is again, "the bitmap cache is not being hit"
        assert ui_mod.rounded(680, 67, 12, ui_mod.CARD, ui_mod.PANE) is not first
    finally:
        root.destroy()


def test_the_direction_of_a_line_comes_from_its_first_strong_letter() -> None:
    """Tk cannot be told which way a paragraph runs — the renderer decides
    from the first strong character. Aligning a box by a different rule
    than the one the text is laid out by is how a sentence ends up
    right-aligned and left-to-right at the same time."""
    import ui as ui_mod
    assert ui_mod.is_rtl("שלום עולם")
    assert ui_mod.is_rtl("  \"שלום\" said the man") is True
    assert not ui_mod.is_rtl("Chrome ואז עברית")
    assert not ui_mod.is_rtl("12.5 s")          # no strong letter at all
    assert not ui_mod.is_rtl("")


def _arrows(canvas) -> list[str]:
    """The arrow glyphs on a canvas. itemcget(_, "text") raises on the
    image items, which is most of a pill."""
    return [canvas.itemcget(i, "text") for i in canvas.find_all()
            if canvas.type(i) == "text"
            and canvas.itemcget(i, "text") in ("←", "→")]


def test_a_correction_pill_points_away_from_the_word_that_was_wrong() -> None:
    """Photographed as one "wrong -> right" string, two Hebrew words lay
    out right-to-left, U+2192 came back unmirrored, and the arrow pointed
    at the word it came from. The three runs are drawn separately so the
    direction is chosen here."""
    import tkinter as tk

    import ui as ui_mod
    root = _tk_or_skip()
    if root is None:
        return
    try:
        canvas = tk.Canvas(root, width=400, height=60)
        ui_mod.pair_pill(canvas, 380, 4, "היוזר", "ה-user", "#161b25")
        assert _arrows(canvas) == ["←"], _arrows(canvas)
        canvas.delete("all")
        ui_mod.pair_pill(canvas, 380, 4, "there", "their", "#161b25")
        assert _arrows(canvas) == ["→"], _arrows(canvas)
    finally:
        root.destroy()


# ------------------------------------------------------- the window itself


@contextlib.contextmanager
def _window(log=None):
    """A dashboard with nothing behind it.

    Three things are borrowed and given back: the pipe (an answer of None
    is what "nothing is running" looks like, and it is instant), the
    instance check, and the log reader — because the poller re-reads
    transcripts.log on its own, and a test that sets three rows and then
    counts a hundred is a test measuring this machine's real history.
    """
    import control as control_mod
    import history as history_mod
    import singleton as singleton_mod

    import dashboard as dash
    saved = (control_mod.send, singleton_mod.is_running, history_mod.load)
    control_mod.send = lambda *a, **k: None
    singleton_mod.is_running = lambda *a, **k: False
    history_mod.load = lambda *a, **k: list(log or [])
    board = None
    try:
        try:
            board = dash.Dashboard()
        except Exception as e:
            print(f"    (skipped: no Tk window — {e})")
            yield None
            return
        board.log = list(log or [])
        yield board
    finally:
        if board is not None:
            board.closing = True
            try:
                board.root.destroy()
            except Exception:
                pass
        control_mod.send, singleton_mod.is_running, history_mod.load = saved


def test_every_screen_of_the_window_builds() -> None:
    """Four screens, built by four methods, and only the one you are
    looking at exists at any moment — so a mistake on the Settings screen
    is invisible until somebody clicks Settings."""
    import dashboard as dash
    with _window() as board:
        if board is None:
            return
        for _key, name in dash.NAV:
            board._show(name)
            assert board.screen == name
            assert board.pane.winfo_children(), f"{name} drew nothing"


def test_every_key_in_hotkey_fields_gets_a_row_to_click() -> None:
    """HOTKEY_FIELDS is the one place a new key is registered. The Keys
    screen groups them by hand, so a key added there and not here would
    have no way to be rebound."""
    with _window() as board:
        if board is None:
            return
        board._show("Keys")
        shown = set(board.parts["caps"])
        expected = {field for field, _label in config_mod.HOTKEY_FIELDS}
        assert shown == expected, expected - shown


def test_every_kind_the_log_can_hold_has_a_badge_and_a_colour() -> None:
    """A kind with no icon raises a KeyError while drawing a row, i.e. one
    entry in the middle of the list takes the whole list down."""
    import history as history_mod

    import dashboard as dash
    import ui as ui_mod
    for kind, (label, icon, colour) in history_mod.KINDS.items():
        assert label, kind
        assert icon in ui_mod.ICON, (kind, icon)
        assert colour in dash.COLOURS, (kind, colour)


def test_a_second_window_in_one_process_can_still_draw() -> None:
    """A PhotoImage and a Font belong to the interpreter that made them.
    The caches in ui.py are module-level, so the second Tk in a process —
    which is what this test file is — gets handed images from the first
    unless they are dropped."""
    with _window() as board:
        if board is None:
            return
    with _window() as again:
        if again is None:
            return
        again._show("History")
        assert again.pane.winfo_children()


def test_the_history_screen_filters_and_searches_what_it_was_given() -> None:
    import datetime

    import history as history_mod
    when = datetime.datetime(2026, 8, 20, 10, 0, 0)
    log = [history_mod.Event(when, "dictation", text="hello there"),
           history_mod.Event(when, "lookup", text="שלום"),
           history_mod.Event(when, "learned", text="x y",
                             pairs=[("x", "y")])]
    with _window(log) as board:
        if board is None:
            return

        def rows() -> int:
            # The list is drawn a screenful at a time between frames, so
            # the count is only true once the queue has drained.
            while board._rows_left:
                board.root.update()
            board.root.update()
            return len(board.parts["list"].inner.winfo_children())

        board._show("History")
        assert rows() == 3, rows()
        board._filter_to("lookup")
        assert rows() == 1, rows()
        board._filter_to(None)
        board._search("hello")
        assert rows() == 1, rows()
        board._search("nothing like this")
        assert rows() == 0, rows()
        assert board.parts["empty"].cget("text")


def test_the_window_says_something_when_there_is_no_log_at_all() -> None:
    """A fresh install has no transcripts.log. An empty list with no
    sentence in it reads as a broken screen."""
    with _window([]) as board:
        if board is None:
            return
        board._show("History")
        board.root.update()
        assert board.parts["empty"].cget("text"),             "an empty history says nothing at all"
        board._show("Overview")
        board._paint_overview()
        assert "Nothing dictated yet" in board.parts["last_text"].cget("text")


def test_the_transcript_font_actually_holds_hebrew() -> None:
    """The scrambling of 2026-08-20: "Segoe UI Variable" has no Hebrew
    glyphs, the per-word font fallback breaks bidi reordering, and every
    Hebrew word rendered letter-reversed. The faces ui resolves for user
    text must therefore EXIST and COVER Hebrew, as measured by GDI — not
    merely be names Tk accepts, because Tk accepts anything."""
    import ui as ui_mod
    for face in (ui_mod.TEXT, ui_mod.UI, ui_mod.DISPLAY):
        exists, hebrew = ui_mod._gdi_face(face)
        assert exists, f"{face!r} is not installed"
        assert hebrew, f"{face!r} cannot spell Hebrew"
    assert "variable" not in ui_mod.TEXT.lower(), \
        "a Variable cut has no Hebrew and scrambles words"


def test_face_picking_falls_back_to_segoe() -> None:
    import ui as ui_mod
    assert ui_mod.pick_face(["NoSuchFaceZZZ"]) == "Segoe UI"
    assert ui_mod.pick_face(["Segoe UI Variable Text"]) == "Segoe UI", \
        "a face without Hebrew must be passed over"


def test_drawn_text_matches_the_rtl_reference() -> None:
    """ui.draw_text exists because Tk lays the runs of a mixed line out
    backwards (measured against DrawTextW+DT_RTLREADING, 2026-08-20).
    This compares ui.draw_text's bitmap to that same reference render —
    if the two engines ever disagree, the history screen is showing
    sentences in the wrong order again."""
    import ctypes
    import ctypes.wintypes as cw

    from PIL import Image, ImageTk

    import ui as ui_mod
    root = _tk_or_skip()
    if root is None:
        return
    try:
        LINE = "תתפרע, אני רוצה שהאתר הזה יהיה sick אתה יודע"
        WIDTH = 640
        photo, height, lines = ui_mod.draw_text(
            LINE, pt=12, width=WIDTH, max_lines=1, colour=ui_mod.FG,
            bg=ui_mod.CARD)
        assert lines == 1

        user, gdi = ctypes.windll.user32, ctypes.windll.gdi32
        px = ui_mod._px(12)
        hdc_screen = user.GetDC(0)
        hdc = gdi.CreateCompatibleDC(hdc_screen)
        bmp = gdi.CreateCompatibleBitmap(hdc_screen, WIDTH, height)
        gdi.SelectObject(hdc, bmp)
        rect = cw.RECT(0, 0, WIDTH, height)
        user.FillRect(hdc, ctypes.byref(rect),
                      gdi.CreateSolidBrush(ui_mod._colorref(ui_mod.CARD)))
        font = gdi.CreateFontW(-px, 0, 0, 0, 400, 0, 0, 0, 0, 0, 0, 5, 0,
                               ui_mod.TEXT)
        gdi.SelectObject(hdc, font)
        gdi.SetTextColor(hdc, ui_mod._colorref(ui_mod.FG))
        gdi.SetBkMode(hdc, 1)
        DT = 0x2 | 0x20 | 0x800 | 0x20000   # RIGHT|SINGLELINE|NOPREFIX|RTL
        user.DrawTextW(hdc, LINE, -1, ctypes.byref(rect), DT)

        class Header(ctypes.Structure):
            _fields_ = [("size", cw.DWORD), ("w", cw.LONG), ("h", cw.LONG),
                        ("planes", cw.WORD), ("bits", cw.WORD),
                        ("comp", cw.DWORD), ("imgsize", cw.DWORD),
                        ("xppm", cw.LONG), ("yppm", cw.LONG),
                        ("used", cw.DWORD), ("important", cw.DWORD)]
        info = Header(ctypes.sizeof(Header), WIDTH, -height, 1, 32,
                      0, 0, 0, 0, 0, 0)
        raw = ctypes.create_string_buffer(WIDTH * height * 4)
        gdi.GetDIBits(hdc, bmp, 0, height, raw, ctypes.byref(info), 0)
        gdi.DeleteObject(bmp)
        gdi.DeleteDC(hdc)
        user.ReleaseDC(0, hdc_screen)
        reference = np.array(Image.frombuffer(
            "RGBA", (WIDTH, height), raw.raw, "raw", "BGRA", 0,
            1).convert("L"), dtype=float)

        ours = np.array(ImageTk.getimage(photo).convert("L"), dtype=float)
        # Ink-per-column correlation: word POSITIONS, robust to a pixel
        # of anti-aliasing difference.
        a = np.clip(reference - 40, 0, None).sum(axis=0)
        b = np.clip(ours - 40, 0, None).sum(axis=0)
        a, b = a - a.mean(), b - b.mean()
        denominator = np.sqrt((a * a).sum() * (b * b).sum())
        similarity = float((a * b).sum() / denominator) if denominator else 0
        assert similarity > 0.98, f"run order drifted ({similarity:.3f})"
    finally:
        root.destroy()


def test_pinning_the_window_relaunches_the_dashboard_not_python() -> None:
    """Pin the window and Windows builds the tile from the EXECUTABLE —
    pythonw.exe: Python's icon, "Python" in the menu, a bare interpreter
    on click. The relaunch properties on the HWND are what override that,
    so they have to actually be there, pointing at Dashboard.vbs."""
    import ctypes
    from ctypes import POINTER, wintypes

    from comtypes import COMMETHOD, GUID, HRESULT, IUnknown

    class PROPERTYKEY(ctypes.Structure):
        _fields_ = [("fmtid", GUID), ("pid", wintypes.DWORD)]

    class PROPVARIANT(ctypes.Structure):
        _fields_ = [("vt", wintypes.USHORT), ("r1", wintypes.USHORT),
                    ("r2", wintypes.USHORT), ("r3", wintypes.USHORT),
                    ("pwszVal", wintypes.LPWSTR), ("pad", ctypes.c_void_p)]

    class IPropertyStore(IUnknown):
        _iid_ = GUID("{886d8eeb-8cf2-4446-8d02-cdba1dbdcf99}")
        _methods_ = [
            COMMETHOD([], HRESULT, "GetCount",
                      (["out"], POINTER(wintypes.DWORD), "count")),
            COMMETHOD([], HRESULT, "GetAt",
                      (["in"], wintypes.DWORD, "index"),
                      (["out"], POINTER(PROPERTYKEY), "key")),
            COMMETHOD([], HRESULT, "GetValue",
                      (["in"], POINTER(PROPERTYKEY), "key"),
                      (["out"], POINTER(PROPVARIANT), "value")),
            COMMETHOD([], HRESULT, "SetValue",
                      (["in"], POINTER(PROPERTYKEY), "key"),
                      (["in"], POINTER(PROPVARIANT), "value")),
            COMMETHOD([], HRESULT, "Commit"),
        ]

    with _window() as board:
        if board is None:
            return
        board.root.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(int(board.root.winfo_id()))
        store = POINTER(IPropertyStore)()
        hr = ctypes.windll.shell32.SHGetPropertyStoreForWindow(
            hwnd, ctypes.byref(IPropertyStore._iid_), ctypes.byref(store))
        assert hr == 0, f"no property store: {hr:#x}"
        fmtid = GUID("{9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3}")
        expectations = {2: "Dashboard.vbs", 3: "icon.ico",
                        4: "Hebrew Dictation"}
        for pid, needle in expectations.items():
            value = store.GetValue(PROPERTYKEY(fmtid, pid))
            held = value.pwszVal or ""
            assert needle in held, (pid, needle, held)


def test_the_breathing_lamp_reuses_its_frames() -> None:
    """A breath is a dozen cached bitmaps being swapped, not a bitmap per
    frame — the glow is quantised before it becomes a cache key."""
    import ui as ui_mod
    root = _tk_or_skip()
    if root is None:
        return
    try:
        one = ui_mod.lamp(26, ui_mod.RED, "#131822", 0.301)
        two = ui_mod.lamp(26, ui_mod.RED, "#131822", 0.309)
        other = ui_mod.lamp(26, ui_mod.RED, "#131822", 0.80)
        assert one is two, "nearby glows must share a frame"
        assert one is not other, "far glows must not"
    finally:
        root.destroy()


# -------------------------------------------------------- ask-the-screen
#
# The screenshot is the most sensitive data this app has ever handled — a
# region of the screen can hold mail, banking, anything. So the tests
# below are weighted towards what must NEVER happen: pixels reaching a
# cloud backend while the upload gate is shut, the image touching disk,
# a second spelling of the key drifting out of sync with its section.

def test_bbox_normalization_from_all_four_drag_directions() -> None:
    """A drag is legal in all four directions and every one of them means
    the same rectangle."""
    import visual_qa as vq

    cases = {
        (100, 200, 300, 400): (100, 200, 300, 400),   # down-right
        (300, 400, 100, 200): (100, 200, 300, 400),   # up-left
        (300, 200, 100, 400): (100, 200, 300, 400),   # down-left
        (100, 400, 300, 200): (100, 200, 300, 400),   # up-right
        (5, 5, 5, 5): (5, 5, 5, 5),                   # a click, no drag
    }
    for corners, expected in cases.items():
        assert vq.normalize_bbox(*corners) == expected, corners


def test_downscale_caps_the_long_side_and_never_upscales() -> None:
    """Aspect preserved, long side capped, and a small grab stays small:
    enlarging pixels adds tokens on some providers and sharpness nowhere."""
    import visual_qa as vq

    assert vq.scale_to(4480, 1440, 1344) == (1344, 432)
    assert vq.scale_to(1440, 4480, 1344) == (432, 1344)
    assert vq.scale_to(900, 450, 1344) == (900, 450), "no upscaling"
    assert vq.scale_to(400, 200, 1344) == (400, 200)
    w, h = vq.scale_to(2000, 1500, 1000)
    assert (w, h) == (1000, 750) and abs(w / h - 2000 / 1500) < 1e-9


def test_the_screenshot_pipeline_is_bytes_in_bytes_out() -> None:
    """No file path anywhere in the pipeline's signatures, and encoding
    yields bytes: the screenshot lives in RAM or it does not exist."""
    import inspect

    import visual_qa as vq

    for fn in (vq.encode_jpeg, vq.Chain.ask, vq.Chain._encode_for,
               vq.OllamaVision.ask, vq.GroqVision.ask):
        params = inspect.signature(fn).parameters
        bad = [p for p in params if "path" in p.lower()
               or p.lower() in ("file", "filename")]
        assert not bad, f"{fn.__qualname__} takes {bad}"

    from PIL import Image
    img = Image.new("RGB", (600, 300), (40, 40, 40))
    blob = vq.encode_jpeg(img, 300)
    assert isinstance(blob, bytes) and blob[:2] == b"\xff\xd8"
    again = vq.encode_jpeg(img, 300)
    assert blob == again


def test_screenshot_upload_gate_keeps_cloud_out_of_the_chain() -> None:
    """THE privacy test. With allow_screenshot_upload = false the built
    chain contains NO cloud backend — asserted against the built list,
    never against the flag, because a runtime `if` is exactly the kind of
    guard a refactor silently deletes."""
    import dataclasses

    import visual_qa as vq

    cfg = config_mod.load(Path(__file__).resolve().parent / "config.toml")
    assert cfg.visual_qa.allow_screenshot_upload is False
    shut = [name for name, _build in vq.Chain(cfg)._builders()]
    assert shut == ["ollama"], \
        f"the gate leaked cloud builders into the chain: {shut}"
    # Even a config that PREFERS the cloud cannot build it while shut.
    sneaky = dataclasses.replace(
        cfg, visual_qa=dataclasses.replace(cfg.visual_qa, prefer="groq"))
    assert [n for n, _ in vq.Chain(sneaky)._builders()] == ["ollama"]

    # Gate open: ollama first by default, then groq, then the shared pool.
    open_cfg = dataclasses.replace(
        cfg, visual_qa=dataclasses.replace(cfg.visual_qa,
                                           allow_screenshot_upload=True))
    names = [n for n, _ in vq.Chain(open_cfg)._builders()]
    assert names == ["ollama", "groq", "gemini"], names
    prefer_groq = dataclasses.replace(
        cfg, visual_qa=dataclasses.replace(cfg.visual_qa,
                                           allow_screenshot_upload=True,
                                           prefer="groq"))
    assert [n for n, _ in vq.Chain(prefer_groq)._builders()] == \
        ["groq", "ollama", "gemini"]
    no_gemini = dataclasses.replace(
        cfg, visual_qa=dataclasses.replace(cfg.visual_qa,
                                           allow_screenshot_upload=True,
                                           gemini_fallback=False))
    assert [n for n, _ in vq.Chain(no_gemini)._builders()] == \
        ["ollama", "groq"]


def _bare_groq_vision():
    """A GroqVision without touching .env: every wire fact below is in
    the request builder, not the key lookup."""
    import visual_qa as vq

    g = vq.GroqVision.__new__(vq.GroqVision)
    g._key = "test-key"
    g._model = "qwen/qwen3.6-27b"
    g._timeout = 20
    g._num_predict = 300
    g.key_source = "test"
    return g


def test_groq_vision_request_shape() -> None:
    """"reasoning_effort 'low' is an HTTP 400" and "Cloudflare eats the
    default User-Agent" are both measured facts from 2026-08-25; these
    asserts are where they stay true."""
    import visual_qa as vq

    g = _bare_groq_vision()
    body = g.request_body("B64IMG==", "מה כתוב כאן?",
                          [{"role": "user", "content": "קודמת"},
                           {"role": "assistant", "content": "תשובה"}])
    assert body["model"] == "qwen/qwen3.6-27b"
    assert body["reasoning_effort"] == "none"
    assert body["max_tokens"] == 300
    parts = body["messages"][1]["content"]
    kinds = {part["type"] for part in parts}
    assert kinds == {"image_url", "text"}, kinds
    url = next(p for p in parts if p["type"] == "image_url")[
        "image_url"]["url"]
    assert url.startswith("data:image/jpeg;base64,B64IMG=="), url[:60]
    # History turns carry NO image — only the FIRST user message does.
    assert len(body["messages"]) == 4
    assert isinstance(body["messages"][3]["content"], str)

    headers = g._headers()
    assert headers["User-Agent"] == "hebrew-dictation/1.0", \
        "Cloudflare 403s Python's default UA (error 1010)"
    assert headers["Authorization"] == "Bearer test-key"


def test_ollama_vision_history_reuses_one_image() -> None:
    """The image rides the FIRST user message only; Ollama's prompt-prefix
    cache makes later turns nearly free (0.35 s measured) — but only if
    the prefix really is identical."""
    import visual_qa as vq

    o = vq.OllamaVision("gemma3:12b", "http://127.0.0.1:11434", 120, 400)
    msgs = o._messages("B64IMG==", "וזה?", [{"role": "user",
                                             "content": "ראשונה"},
                                            {"role": "assistant",
                                             "content": "תשובה"}])
    with_images = [m for m in msgs if m.get("images")]
    assert len(with_images) == 1, with_images
    assert with_images[0]["content"] == "ראשונה"
    assert msgs[-1]["role"] == "user" and msgs[-1]["content"] == "וזה?"
    assert "images" not in msgs[-1]
    assert any(m.get("role") == "system" for m in msgs)


def test_tts_command_names_voice_and_never_flashes_a_console() -> None:
    """The PowerShell subprocess is where a console window would flash —
    CREATE_NO_WINDOW (0x08000000) is load-bearing, this repo froze a
    dashboard once without it."""
    import visual_qa as vq

    args = vq.Speaker._powershell_args("speak.ps1", "a.wav", "a.txt",
                                        "Microsoft Asaf")
    assert args[0] == "powershell" and "-NoProfile" in args
    assert "-File" in args
    assert args[args.index("-voice") + 1] == "Microsoft Asaf"
    assert args[args.index("-textfile") + 1] == "a.txt", \
        "the question text travels by UTF-8 file, not the command line"
    assert vq.Speaker.CREATE_NO_WINDOW == 0x08000000


def test_tiny_warmup_image_is_a_real_png_and_needs_no_pillow() -> None:
    """"The warm-up must not import Pillow" is the point of shipping it
    as a constant — the startup path stays stdlib-only. And it must be a
    VALID png: the first draft here was hand-typoed, Ollama answered HTTP
    400, and nothing but a decode check would have caught it (the warm-up
    correctly refused to crash startup)."""
    import base64 as b64mod
    import io
    import struct

    import visual_qa as vq

    raw = b64mod.b64decode(vq._TINY_PNG_B64)
    assert raw[:8] == b"\x89PNG\r\n\x1a\n"
    assert len(raw) < 200
    # stdlib-only integrity walk: signature, IHDR, IEND present and the
    # IHDR length field is exactly 13 bytes.
    assert raw[12:16] == b"IHDR"
    ihdr_len = struct.unpack(">I", raw[8:12])[0]
    assert ihdr_len == 13
    assert raw[-8:-4] == b"IEND"


def test_speak_switch_off_button_auto() -> None:
    """off hides the control, button shows it, auto reads everything —
    and config refuses anything that is not one of the three."""
    import visual_qa as vq

    assert vq.speak_button_visible("button")
    assert vq.speak_button_visible("auto")
    assert not vq.speak_button_visible("off")

    tmp, path = _temp_config()
    try:
        config_mod.set_values(path, {"visual_qa.speak": "auto"})
        assert config_mod.load(path).visual_qa.speak == "auto"
        before = path.read_text("utf-8")
        try:
            config_mod.set_values(path, {"visual_qa.speak": "loudly"})
        except config_mod.ConfigError:
            pass
        else:
            raise AssertionError("'loudly' was accepted as a speak mode")
        assert path.read_text("utf-8") == before, \
            "a rejected value must not touch the file"
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def test_visual_qa_section_parses_with_defaults_and_overrides() -> None:
    import shutil
    import tempfile
    tmp = Path(tempfile.mkdtemp(prefix="vqa-config-"))
    path = tmp / "config.toml"
    try:
        path.write_text(
            'hotkey = "right ctrl"\n'
            "[visual_qa]\n"
            "enabled = false\n"
            'visual_qa_hotkey = "f15"\n'
            "allow_screenshot_upload = true\n"
            'prefer = "groq"\n'
            "max_side_px = 900\n"
            "num_predict = 256\n"
            'speak = "auto"\n',
            "utf-8")
        cfg = config_mod.load(path)
        vq = cfg.visual_qa
        assert vq.enabled is False
        assert vq.hotkey == "f15"          # the TOML key's real name
        assert cfg.visual_qa_hotkey == "f15"   # ...and its public face
        assert vq.allow_screenshot_upload is True
        assert vq.prefer == "groq"
        assert vq.max_side_px == 900
        assert vq.num_predict == 256
        assert vq.speak == "auto"
        assert vq.voice == "Microsoft Asaf"     # untouched default
        assert vq.groq_model == "qwen/qwen3.6-27b"

        defaults = config_mod.VisualQAConfig()
        assert defaults.allow_screenshot_upload is False, \
            "the privacy default is OFF and must stay off"
        assert defaults.hotkey == "ctrl+f10"
        assert defaults.max_side_px == 1344
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_visual_qa_hotkey_write_back_is_nested_and_keeps_comments() -> None:
    """The key lives INSIDE [visual_qa], so the write-back must be dotted;
    set_values' line editor keeps every comment byte while doing it."""
    import shutil
    tmp, path = _temp_config()
    try:
        before = path.read_text("utf-8")
        marker = "# measured-free like the other ctrl+F keys"
        assert marker in before, "the comment this test protects vanished"
        config_mod.set_values(path, {"visual_qa.visual_qa_hotkey": "f16"})
        after = path.read_text("utf-8")
        assert config_mod.load(path).visual_qa.hotkey == "f16"
        assert marker in after
        assert 'visual_qa_hotkey = "f16"' in after
        # Nothing else moved: the top-level hotkey line is byte-identical.
        def hotkey_line(text: str) -> str:
            return next(line for line in text.splitlines()
                        if line.startswith("hotkey "))
        assert hotkey_line(before) == hotkey_line(after)

        # And the section editor refuses to invent keys.
        try:
            config_mod.set_values(path, {"visual_qa.nonexistent": "1"})
        except config_mod.ConfigError:
            assert config_mod.load(path).visual_qa.hotkey == "f16"
        else:
            raise AssertionError("set_values invented visual_qa.nonexistent")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_visual_qa_key_binds_and_the_kill_switch_unbinds_it() -> None:
    """enabled = false unregisters the key ENTIRELY: no tap, nothing in
    the state machine, whatever the key string still says."""
    import dataclasses

    import main as main_mod

    cfg = config_mod.load(Path(__file__).resolve().parent / "config.toml")
    _hotkeys, taps, _latch, _pause = main_mod.App.bindings(cfg)
    assert taps[parse_binding("ctrl+f10")] == "visual_qa", taps
    assert main_mod.App._vk_of(taps, "visual_qa") == vk_for("f10")

    off = dataclasses.replace(cfg, visual_qa=dataclasses.replace(
        cfg.visual_qa, enabled=False))
    _hotkeys, taps_off, _l, _p = main_mod.App.bindings(off)
    assert all(name != "visual_qa" for name in taps_off.values()), taps_off

    unbound = dataclasses.replace(cfg, visual_qa=dataclasses.replace(
        cfg.visual_qa, enabled=True, hotkey=""))
    _hotkeys, taps_empty, _l, _p = main_mod.App.bindings(unbound)
    assert all(name != "visual_qa" for name in taps_empty.values())


def test_visual_qa_key_collision_is_refused_like_every_other() -> None:
    """One key cannot mean two things — including when one of them is
    nested in a section nobody typed at the top level."""
    import dataclasses

    import main as main_mod

    cfg = config_mod.load(Path(__file__).resolve().parent / "config.toml")
    clash = config_mod.with_field(cfg, "visual_qa_hotkey", "ctrl+f8")
    assert clash.visual_qa.hotkey == "ctrl+f8"
    assert cfg.visual_qa.hotkey == "ctrl+f10", "the original changed"
    try:
        config_mod.check_hotkeys(clash)
    except config_mod.ConfigError as e:
        assert "lookup_hotkey" in str(e), e
    else:
        raise AssertionError("ctrl+f8 collided with lookup and was allowed")

    free = config_mod.with_field(cfg, "visual_qa_hotkey", "f14")
    config_mod.check_hotkeys(free)      # must not raise


def test_the_dashboard_lists_the_visual_qa_key() -> None:
    """HOTKEY_FIELDS is the one place a new key is registered — the Keys
    screen, the live rebind and the validation all read it."""
    fields = dict(config_mod.HOTKEY_FIELDS)
    assert "visual_qa_hotkey" in fields, fields
    assert fields["visual_qa_hotkey"], "the row would have no label"


def test_the_thumbnail_caps_both_sides_and_never_upscales() -> None:
    """One arithmetic, three bugs. Capping the WIDTH alone let a tall
    narrow selection decide the card's height before an answer existed,
    and scaling a small grab up handed back a blur of pixels the user
    could already see sharply."""
    import visual_qa as vq

    assert vq.thumb_size(2000, 300) == (190, 28)     # wide: width binds
    assert vq.thumb_size(300, 2000) == (16, 110)     # tall: HEIGHT binds
    assert vq.thumb_size(120, 80) == (120, 80), "no upscaling"
    assert vq.thumb_size(1, 1) == (1, 1)
    w, h = vq.thumb_size(760, 440)
    assert w <= vq.THUMB_MAX_W and h <= vq.THUMB_MAX_H
    assert abs(w / h - 760 / 440) < 0.02, "aspect ratio drifted"


def test_the_selector_says_how_big_the_selection_is() -> None:
    """The readout is the only number on that screen; the sign in it is
    U+00D7, because a letter x at 9 pt reads as part of a word."""
    import visual_qa as vq

    assert vq.selection_readout((10, 20, 522, 308)) == "512 × 288"
    assert "x" not in vq.selection_readout((0, 0, 5, 5))


def test_escape_stops_the_speaking_before_it_closes_the_card() -> None:
    """One key, two jobs, in the order a person wants them: the first Esc
    silences an answer being read aloud, the second closes."""
    import visual_qa as vq

    assert vq.esc_action(True) == "stop"
    assert vq.esc_action(False) == "close"


def test_a_streamed_answer_repaints_on_a_line_or_every_80ms() -> None:
    """The lookup box's measured rule, reused: tokens land ~24 ms apart
    and a window resizing forty times a second reads as jitter, so a
    completed line jumps the queue and 80 ms is the floor for the rest."""
    import visual_qa as vq

    assert vq.should_repaint(1.000, 0.990, "abcd", 0) is False, \
        "10 ms after the last paint, with no newline, is too soon"
    assert vq.should_repaint(1.100, 0.990, "abcd", 0) is True
    assert vq.should_repaint(1.000, 0.990, "ab\ncd", 2) is True, \
        "a completed line must not wait for the 80 ms floor"
    assert vq.should_repaint(9.000, 0.000, "abcd", 4) is False, \
        "text that has not grown is never repainted"
    assert vq.should_repaint(9.000, 0.000, "abc", 4) is False


def test_the_card_goes_back_where_it_was_put() -> None:
    """A card the user parked somewhere is a card they chose the place
    of, and a new selection is not a reason to move it back.

    But it has to earn that twice: fit a REAL monitor, and CLEAR the new
    selection. The owner reported the second one — re-selecting behind an
    already-parked card left the card sitting on the very pixels the
    question was about. Clamping into the virtual screen instead of a
    monitor's work area teleports a window on the left monitor onto the
    primary (popup.py measured that)."""
    import visual_qa as vq

    work = (0, 0, 1920, 1040)
    anchor = (100, 100, 400, 300)

    assert vq.plan_placement(anchor, work, (400, 200)) == (418, 100), \
        "with no memory it sits BESIDE the selection, never over it"
    parked = vq.plan_placement(anchor, work, (400, 200), (900, 600))
    assert parked == (900, 600), parked
    assert vq.plan_placement(anchor, work, (400, 200), (1800, 60)) \
        == (418, 100), "a remembered spot that no longer fits is dropped"
    assert vq.plan_placement(anchor, work, (400, 200), (50, 60)) \
        == (418, 100), "and one that covers the new selection is dropped"

    # The left monitor: negative coordinates are a place, not an error.
    left = (-1920, 0, 0, 1040)
    assert vq.plan_placement((-1800, 100, -1500, 300), left, (400, 200),
                             (-1700, 400)) == (-1700, 400)

    # Flip above when there is no room below, and clamp to the work area.
    high = vq.plan_placement((100, 700, 400, 1000), work, (400, 300))
    assert high[1] + 300 <= 1040, high
    wide = vq.plan_placement((1900, 100, 1910, 300), work, (400, 200))
    assert wide[0] + 400 <= 1920, wide


def test_a_streamed_reply_arrives_a_piece_at_a_time_and_adds_up() -> None:
    """Ollama's streamed shape is line-delimited JSON, and on_chunk is
    handed the WHOLE answer so far rather than the piece — the window
    paints a string, not a diff."""
    import json as json_mod

    import visual_qa as vq

    backend = vq.OllamaVision("gemma3:12b", "http://127.0.0.1:11434", 30,
                              400)
    lines = [json_mod.dumps({"message": {"content": piece}}).encode("utf-8")
             for piece in ("שלום ", "עולם", "")]
    seen: list[str] = []
    whole = backend._read(lines, seen.append, None)
    assert whole == "שלום עולם", whole
    assert seen == ["שלום ", "שלום עולם"], seen

    class Whole:
        @staticmethod
        def read():
            return json_mod.dumps(
                {"message": {"content": "בבת אחת"}}).encode("utf-8")

    assert backend._read(Whole, None, None) == "בבת אחת"


def test_a_stream_that_never_ends_is_cut_by_its_own_deadline() -> None:
    """Streaming disarms urllib's timeout — it is per socket operation,
    and a token every 24 ms means no recv ever waits. translate.py
    measured 8 s of streaming under timeout=3 with nothing raised. So the
    deadline is kept by hand, and a model that loops has to hit it."""
    import json as json_mod

    import visual_qa as vq

    backend = vq.OllamaVision("gemma3:12b", "http://127.0.0.1:11434", 0,
                              400)

    def forever():
        while True:
            yield json_mod.dumps(
                {"message": {"content": "עוד "}}).encode("utf-8")

    try:
        backend._read(forever(), lambda _so_far: None, None)
    except TimeoutError as e:
        assert "still writing" in str(e), e
    else:
        raise AssertionError("the endless stream was never cut off")


def test_speaking_again_cancels_the_answer_mid_token() -> None:
    """Barge-in has to reach the wire, not just the window: the reader
    checks the cancel event per line, which bounds the abort at one
    token."""
    import json as json_mod
    import threading as threading_mod

    import visual_qa as vq

    backend = vq.OllamaVision("gemma3:12b", "http://127.0.0.1:11434", 30,
                              400)
    cancel = threading_mod.Event()
    cancel.set()
    lines = [json_mod.dumps({"message": {"content": "לא"}}).encode("utf-8")]
    try:
        backend._read(lines, lambda _s: None, cancel)
    except vq.Cancelled:
        pass
    else:
        raise AssertionError("a cancelled stream kept reading")

    # ...and the other half of barge-in, which cost a measurement to find:
    # per-line checking cannot reach a request that has not produced a
    # line yet, and a COLD vision projector produces none for 23 s. The
    # watchdog closes the response instead, and the socket dying under a
    # cancel has to read as the cancel arriving rather than as a broken
    # backend — otherwise the chain moves on to the cloud with it.
    class Dying:
        @staticmethod
        def __iter__():
            raise OSError("socket closed under us")

    try:
        backend._read(Dying(), lambda _s: None, cancel)
    except vq.Cancelled:
        pass
    else:
        raise AssertionError("a closed socket under a cancel was not one")

    try:
        backend._read(Dying(), lambda _s: None, threading_mod.Event())
    except OSError:
        pass
    else:
        raise AssertionError("a genuinely broken stream was swallowed")


def test_a_cancelled_question_never_falls_through_to_the_cloud() -> None:
    """Cancelled is not a refusal. QAError means "this backend said no,
    try the next one"; a superseded question must not be re-asked of Groq
    with the user's next sentence already on its way — that would spend a
    cloud request, and a screenshot, on text nobody is waiting for."""
    import visual_qa as vq

    cfg = config_mod.load(Path(__file__).resolve().parent / "config.toml")
    chain = vq.Chain(cfg)
    reached: list[str] = []

    class Superseded:
        name = "ollama"

        @staticmethod
        def ask(*_a, **_kw):
            reached.append("ollama")
            raise vq.Cancelled("superseded while the model was writing")

    class MustNotRun:
        name = "groq"

        @staticmethod
        def ask(*_a, **_kw):
            reached.append("groq")
            return "לא היה צריך לקרות"

    chain._backends = lambda: iter([Superseded(), MustNotRun()])
    from PIL import Image
    try:
        chain.ask(Image.new("RGB", (32, 32)), "שאלה", [])
    except vq.Cancelled:
        pass
    else:
        raise AssertionError("Cancelled was swallowed as a backend failure")
    assert reached == ["ollama"], \
        f"the next backend was consulted anyway: {reached}"


def test_one_image_is_encoded_once_per_backend() -> None:
    """A follow-up asks about the same pixels, and redoing the downscale
    plus the base64 costs ~60 ms and ~143 K characters for a
    byte-identical string. The cache belongs to the CALLER: a Chain
    outlives every card, and a Chain holding a screenshot is the one
    thing this module promises not to do."""
    import inspect

    import visual_qa as vq
    from PIL import Image

    cfg = config_mod.load(Path(__file__).resolve().parent / "config.toml")
    chain = vq.Chain(cfg)
    image = Image.new("RGB", (900, 450), (20, 30, 40))
    cache: dict = {}
    first = chain._encode_for("ollama", image, cache)
    assert list(cache) == [("ollama", cfg.visual_qa.max_side_px)], cache
    assert chain._encode_for("ollama", image, cache) is first, \
        "the second ask re-encoded the same image"
    assert chain._encode_for("ollama", image, None) == first, \
        "no cache must still produce the same bytes"
    assert not [a for a in inspect.signature(vq.Chain).parameters
                if "image" in a], "the Chain must not hold an image"


def test_the_card_never_borrows_the_dashboard_s_bitmaps() -> None:
    """A PhotoImage belongs to the interpreter that made it, and this
    module stands up a fresh Tk per press on its own thread. ui.rounded()
    caches PhotoImages in a module-level dict against whichever root came
    first, so one call from here is "main thread is not in main loop" the
    moment two interpreters exist. ui.rounded_pil() returns pixels
    instead, and every caller wraps them with a master of its own."""
    import io
    import tokenize

    source = (Path(__file__).resolve().parent
              / "visual_qa.py").read_text("utf-8")
    # Tokens, not text: this file EXPLAINS the rule in its comments, and a
    # test that reads prose would fail on the sentence describing itself.
    code = "".join(
        tok.string for tok in
        tokenize.generate_tokens(io.StringIO(source).readline)
        if tok.type not in (tokenize.COMMENT, tokenize.STRING))
    for forbidden in ("ui.rounded(", "ui_mod.rounded(", "ui.Button(",
                      "ui_mod.Button(", "ui.Card(", "ui.draw_text(",
                      "ui_mod.draw_text("):
        assert forbidden not in code, \
            f"visual_qa.py calls {forbidden} — that bitmap has a foreign root"
    assert "rounded_pil" in code, "the PIL-level helper is not being used"
    assert "master=" in code, "a PhotoImage here without a master is a bug"

    import ui as ui_mod
    image = ui_mod.rounded_pil(40, 20, 6, "#161b25", "#10131a", "#2a3242")
    assert image.size == (40, 20), image.size
    assert not hasattr(image, "width_"), "rounded_pil must return a PIL image"
    assert image.getpixel((20, 10)) != image.getpixel((0, 0)), \
        "the corner and the middle came out the same colour"


def test_every_registered_key_has_a_place_on_the_keys_screen() -> None:
    """HOTKEY_FIELDS is the one place a key is registered; KEY_GROUPS is
    where it is shown. A key in the first and not the second lands in an
    "Other keys" catch-all, which is a net for a mistake and not a place
    to leave one — ask-the-screen shipped in it, at a y the fixed window
    could not reach."""
    import dashboard as dash

    named = {field for _title, fields in dash.KEY_GROUPS
             for field in fields}
    for field, _label in config_mod.HOTKEY_FIELDS:
        assert field in named, \
            f"{field} is registered but not named in a KEY_GROUPS group"


def test_the_keys_screen_can_reach_every_key_it_lists() -> None:
    """The assertion the first version of this was missing. Listing a key
    is not showing it: the card holding ask-the-screen was built at y=654
    in a 648 px window that does not scroll, so the row existed, the old
    test passed on the row existing, and the owner could not find the key.

    Asserted against the LAST registered key rather than a named one, so
    it asks the real question — can the bottom of this screen be reached
    — on whichever branch it runs, and keeps asking it when the next key
    is added."""
    import dashboard as dash

    try:
        board = dash.Dashboard()
    except Exception as e:                      # no display: nothing to test
        print(f"    (skipped: no Tk window — {e})")
        return
    try:
        board.closing = True
        board._show("Keys")
        board.root.update()
        caps = board.parts["caps"]
        for field, _label in config_mod.HOTKEY_FIELDS:
            assert field in caps, f"{field} has no key cap on the screen"
        scroller = board.parts["keys_list"]
        scroller.canvas.yview_moveto(1.0)
        board.root.update()
        last = config_mod.HOTKEY_FIELDS[-1][0]
        cap = caps[last]
        top = cap.winfo_rooty() - scroller.canvas.winfo_rooty()
        assert 0 <= top, f"{last} sits above the viewport ({top})"
        assert top + cap.winfo_height() <= scroller.canvas.winfo_height(), \
            (f"{last} ends {top + cap.winfo_height()} px into a "
             f"{scroller.canvas.winfo_height()} px viewport — unreachable")
    finally:
        try:
            board.root.destroy()
        except Exception:
            pass


def test_visual_qa_conversation_knobs_parse_and_are_bounded() -> None:
    """auto_send is what makes the thing a conversation; window_alpha is
    how see-through the card is, and a card you cannot read is not a
    feature."""
    import shutil
    import tempfile

    defaults = config_mod.VisualQAConfig()
    assert defaults.auto_send is True
    assert defaults.window_alpha == 0.93

    tmp = Path(tempfile.mkdtemp(prefix="vqa-talk-"))
    path = tmp / "config.toml"
    try:
        path.write_text('hotkey = "right ctrl"\n[visual_qa]\n'
                        "auto_send = false\nwindow_alpha = 0.6\n", "utf-8")
        cfg = config_mod.load(path)
        assert cfg.visual_qa.auto_send is False
        assert abs(cfg.visual_qa.window_alpha - 0.6) < 1e-9

        path.write_text('hotkey = "right ctrl"\n[visual_qa]\n'
                        "window_alpha = 0.05\n", "utf-8")
        try:
            config_mod.load(path)
        except config_mod.ConfigError as e:
            assert "window_alpha" in str(e), e
        else:
            raise AssertionError("a card at 5% opacity was accepted")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    tmp2, live = _temp_config()
    try:
        config_mod.set_values(live, {"visual_qa.auto_send": False})
        assert config_mod.load(live).visual_qa.auto_send is False
        marker = "# a SPOKEN question sends itself the moment"
        assert marker in live.read_text("utf-8"), \
            "set_values ate the comment that explains the key"
    finally:
        shutil.rmtree(tmp2, ignore_errors=True)


def _run_window_script(body: str) -> None:
    """Run a card-building script as a SUBPROCESS, like the overlay tests.

    The card owns a Tcl interpreter plus widgets and images, and burying
    those from the suite's main thread after the card's thread is gone is
    exactly the Tcl_AsyncDelete abort those tests were written to avoid.
    """
    import subprocess
    import tempfile
    here = Path(__file__).resolve().parent
    with tempfile.NamedTemporaryFile("w", suffix="_vqa_win.py",
                                     dir=str(here), delete=False,
                                     encoding="utf-8") as fh:
        fh.write(body)
        path = Path(fh.name)
    try:
        out = subprocess.run([sys.executable, str(path)], cwd=str(here),
                             capture_output=True, encoding="utf-8",
                             errors="replace", timeout=120)
    finally:
        path.unlink(missing_ok=True)
    assert out.returncode == 0, (out.returncode, out.stdout, out.stderr)
    assert "Tcl_AsyncDelete" not in (out.stderr or ""), out.stderr
    assert "Traceback" not in (out.stderr or ""), out.stderr


def test_a_dictated_question_asks_itself_without_a_keypress() -> None:
    """The whole point of auto_send: a spoken question is COMPLETE when
    the transcript lands — it has been through Whisper and the learned
    vocabulary already — so the Enter that used to follow it was the one
    manual step left in a flow that is otherwise hands-free.

    Also the diversion contract: the transcript reaches the card's entry
    and nothing is pasted into the app underneath."""
    _run_window_script('''
import threading, time, os
from PIL import Image
import visual_qa as vq

img = Image.new("RGB", (320, 160), (30, 30, 30))
asked = []
holder = {}
ready = threading.Event()

def ask(image, question, history, on_chunk=None, cancel=None,
        encoded_cache=None):
    asked.append(question)
    return ("ארבעים ושתיים", "test")

def flow():
    win = vq.AskWindow(img, (100, 100, 600, 400), vq.Speaker(), "off", ask,
                       auto_send=True)
    holder["win"] = win
    ready.set()
    try:
        win.run()
    except Exception:
        pass

t = threading.Thread(target=flow, daemon=True)
t.start()
assert ready.wait(10), "the card never came up"
win = holder["win"]
deadline = time.monotonic() + 10
win.post(("voice", "מה המספר שמופיע בחלון?"))
while not win.answer_text and time.monotonic() < deadline:
    time.sleep(0.02)
assert win.last_voice == "מה המספר שמופיע בחלון?", win.last_voice
assert asked == ["מה המספר שמופיע בחלון?"], asked
assert win.answer_text == "ארבעים ושתיים", win.answer_text
assert len(win.history) == 2, win.history
assert win.history[0]["content"] == "מה המספר שמופיע בחלון?"
win.close_soon()
t.join(5)
assert not t.is_alive(), "the card's thread did not exit on close"
os._exit(0)
''')


def test_talking_over_an_answer_folds_both_sentences_into_one_question() -> None:
    """The phone-call rule the owner asked for. Speaking again while the
    model is writing abandons that answer mid-token, appends what was just
    said to what was already asked, and re-asks the LOT — so the reply
    covers everything said so far instead of half of it.

    Two guarantees are asserted, and both are the kind that rot quietly:
    the abandoned answer must be DROPPED when it finally lands (a
    generation counter, not a flag, because it lands after the new
    question was sent), and the dictated words must never be lost — v1
    put them in the entry and then wiped the entry when the stale answer
    arrived."""
    _run_window_script('''
import threading, time, os
from PIL import Image
import visual_qa as vq

img = Image.new("RGB", (320, 160), (30, 30, 30))
asked, holder = [], {}
ready, gate = threading.Event(), threading.Event()

def ask(image, question, history, on_chunk=None, cancel=None,
        encoded_cache=None):
    asked.append(question)
    if len(asked) == 1:
        # The first answer is still being written when the user speaks
        # again; it must notice the cancel rather than finish and win.
        for _ in range(500):
            if cancel is not None and cancel.is_set():
                raise vq.Cancelled("superseded")
            if gate.wait(0.02):
                break
        return ("התשובה הישנה", "test")
    return ("התשובה על הכל", "test")

def flow():
    win = vq.AskWindow(img, (100, 100, 600, 400), vq.Speaker(), "off", ask,
                       auto_send=True)
    holder["win"] = win
    ready.set()
    try:
        win.run()
    except Exception:
        pass

t = threading.Thread(target=flow, daemon=True)
t.start()
assert ready.wait(10), "the card never came up"
win = holder["win"]

win.post(("voice", "מה כתוב פה"))
deadline = time.monotonic() + 10
while not asked and time.monotonic() < deadline:
    time.sleep(0.02)
while not win.busy and time.monotonic() < deadline:
    time.sleep(0.02)
assert win.busy, "the first question never went out"

win.post(("voice", "ותרגם לאנגלית"))
while len(asked) < 2 and time.monotonic() < deadline:
    time.sleep(0.02)
assert asked[1] == "מה כתוב פה ותרגם לאנגלית", asked
gate.set()                      # let the abandoned answer land, late

while not win.answer_text and time.monotonic() < deadline:
    time.sleep(0.02)
assert win.answer_text == "התשובה על הכל", win.answer_text
assert len(win.history) == 2, win.history
assert win.history[0]["content"] == "מה כתוב פה ותרגם לאנגלית", win.history
time.sleep(0.4)                 # give the stale answer every chance to win
assert win.answer_text == "התשובה על הכל", "the abandoned answer landed"
assert len(win.history) == 2, win.history
win.close_soon()
t.join(5)
assert not t.is_alive(), "the card's thread did not exit on close"
os._exit(0)
''')


def test_the_card_grows_to_fit_a_long_answer_and_then_scrolls() -> None:
    """Tk does NOT grow a toplevel once an explicit geometry has been set
    — measured, a child's requested height went 21 -> 477 and the window
    stayed 21 px tall. v1 pinned its geometry once, before any answer
    existed, which is why every long answer was clipped with no way to
    see the rest. Every content change now re-issues the geometry, and
    the growth stops at a share of the work area rather than running off
    the bottom of the screen."""
    _run_window_script('''
import os
from PIL import Image
import visual_qa as vq

# Built and driven on the MAIN thread: this test never pumps, so the
# interpreter is owned, used and buried by one thread throughout.
img = Image.new("RGB", (320, 160), (30, 30, 30))
win = vq.AskWindow(img, (100, 100, 600, 400), vq.Speaker(), "off",
                   lambda *a, **k: ("", "test"))
try:
    win.root.update()
    # The WINDOW is the whole frozen screen now and never changes
    # size. What grows is the card painted on it, so measure that.
    before = win._h
    win.history.append({"role": "user", "content": "מה כתוב במסך הזה?"})
    win.history.append({"role": "assistant", "content": "שורה. " * 700})
    win._repaint_transcript()
    win._fit_window()
    win.root.update()
    after = win._h
    assert after > before, (before, after)
    assert win._content_h > 0
    cap = win._view_cap()
    assert win._view_h() <= cap + 1, (win._view_h(), cap)
    # taller than it can show, so it scrolls -- and sits at the END
    assert win._content_h > win._view_h(), (win._content_h, win._view_h())
    assert win._scroll == win._content_h - win._view_h(), win._scroll
finally:
    win.root.destroy()
os._exit(0)
''')


def test_a_busy_clipboard_is_a_message_not_a_traceback() -> None:
    """injector.set_text raises ClipboardBusyError when another program
    is holding the clipboard — a thing that happens — and v1 let it out
    of a Tk callback, where it became a traceback on stderr and no
    feedback at all in the window."""
    _run_window_script('''
import os
from PIL import Image
import injector
import visual_qa as vq

img = Image.new("RGB", (320, 160), (30, 30, 30))
win = vq.AskWindow(img, (100, 100, 600, 400), vq.Speaker(), "off",
                   lambda *a, **k: ("", "test"))
try:
    win.root.update()
    win.answer_text = "תשובה להעתקה"

    real = injector.set_text
    injector.set_text = lambda _t: (_ for _ in ()).throw(
        injector.ClipboardBusyError("held by something else"))
    win._copy()
    assert "clipboard busy" in win.status.cget("text"), \\
        win.status.cget("text")
    assert win.status.cget("fg") == vq.AMBER, win.status.cget("fg")

    copied = []
    injector.set_text = copied.append
    win._copy()
    assert copied == ["תשובה להעתקה"], copied
    assert win.status.cget("text") == "copied", win.status.cget("text")
    assert win.status.cget("fg") == vq.GREEN, win.status.cget("fg")
    injector.set_text = real
finally:
    win.root.destroy()
os._exit(0)
''')


def test_a_new_selection_starts_a_new_conversation() -> None:
    """The image rides the FIRST user turn in every backend's message
    list, so history carried across a re-selection would leave the model
    answering about pixels that are no longer on screen — while the card
    showed the new ones. The old encodings go too: they are a screenshot,
    in base64, and this module keeps none of those."""
    _run_window_script('''
import os
from PIL import Image
import visual_qa as vq

img = Image.new("RGB", (320, 160), (30, 30, 30))
fresh = Image.new("RGB", (640, 200), (90, 20, 20))
win = vq.AskWindow(img, (100, 100, 600, 400), vq.Speaker(), "off",
                   lambda *a, **k: ("", "test"),
                   reselect_fn=lambda: (fresh, (0, 0, 640, 200)))
try:
    win.root.update()
    win.history.append({"role": "user", "content": "שאלה ישנה"})
    win.history.append({"role": "assistant", "content": "תשובה ישנה"})
    win.answer_text = "תשובה ישנה"
    win.encoded[("ollama", 1344)] = "stale-base64"
    win._repaint_transcript()
    was = win._thumb.size

    win._on_reselect()
    win.root.update()
    assert win.history == [], win.history
    assert win.answer_text == "", win.answer_text
    assert win.encoded == {}, win.encoded
    assert win.image is fresh
    now = win._thumb.size
    assert now != was, (was, now)
finally:
    win.root.destroy()
os._exit(0)
''')


def test_closing_the_card_mid_answer_does_not_hand_it_to_the_ask_thread() -> None:
    """The half of the crash the first fix missed.

    Esc while the model is still writing is an ordinary thing to do, and
    it used to leave the card owned by the ask thread: a Thread holds its
    target for as long as it runs, and the target WAS `self._ask_worker`,
    a bound method. So _flow's collect found the card still reachable and
    did nothing, and when the model call finally returned - up to
    ollama_timeout_s later - that thread dropped the last reference. Not
    the thread that built the interpreter. Reproduced as exit code 3,
    Tcl_AsyncDelete, before the worker was made a module-level function
    handed a queue.

    The same rule covers the TTS callback, which used to close over the
    window and can sit inside a 60 s subprocess.
    """
    _run_window_script('''
import gc, threading, time
from pathlib import Path
from PIL import Image
import config
import visual_qa as vq

gc.disable()

cfg = config.load(Path("config.toml"))
ctrl = vq.Controller(lambda: cfg)
img = Image.new("RGB", (320, 160), (30, 30, 30))
ctrl._grab_selection = lambda: (img, (100, 100, 420, 260))

answering = threading.Event()
release = threading.Event()

def slow_ask(image, question, history, on_chunk=None, cancel=None,
             encoded_cache=None):
    answering.set()
    release.wait(30)
    return ("a late answer nobody asked for any more", "test")

ctrl._ask = slow_ask

assert ctrl.begin_selection()
deadline = time.monotonic() + 20
while not ctrl.sink_active and time.monotonic() < deadline:
    time.sleep(0.02)
assert ctrl.sink_active, "the card never came up"

ctrl._window.post(("voice", "מה כתוב כאן?"))
assert answering.wait(15), "the ask worker never started"

ctrl.stop()                       # Esc, with the answer still in flight
while ctrl.busy and time.monotonic() < deadline:
    time.sleep(0.02)
assert not ctrl.busy, "the flow never finished"

release.set()                     # the model call returns, far too late
time.sleep(1.0)

# If the ask thread was ever an owner, the card is cyclic garbage now and
# THIS collect is the wrong thread freeing it.
freed = gc.collect()
assert freed == 0, f"the ask thread left {freed} objects behind"
''')


def test_dragging_the_card_redraws_only_what_moved() -> None:
    """The owner called the drag "laggy and stuck", and it was: 63 ms a
    frame, 16 fps, and essentially all of it a fresh Gaussian blur of
    whatever the card had just moved over.

    Three caches fixed it, and this asserts the two that a refactor could
    silently undo. The CONTENT layer - text, chips, icons, composer -
    depends on the state and not on the position, so moving the card must
    reuse the very same object. The blurred backdrop is the whole frozen
    screen blurred ONCE; the screen cannot change while it is frozen, so
    a moving card is a crop of that rather than a new blur.

    Timings are not asserted here - they belong to the machine, not to
    the code. What is asserted is the thing that makes them possible.
    """
    _run_window_script('''
import os
from PIL import Image
import visual_qa as vq

img = Image.new("RGB", (400, 240), (30, 30, 30))
win = vq.AskWindow(img, (200, 200, 600, 440), vq.Speaker(), "off",
                   lambda *a, **k: ("", "test"))
try:
    win.root.update()
    surface = win.surface

    # nothing is blurred until something is about to be dragged
    assert surface._blurred is None, "the blur was paid for before it was needed"
    class E:
        x_root = y_root = 300
    win._drag_start(E)
    assert surface._blurred is not None, "the drag did not prepare the blur"
    assert surface._blurred.size == surface.backdrop.size

    win._repaint()
    content, boxes, plate = surface._content, surface._content_key, surface._plate_key
    assert content is not None

    win._cx += 40                      # exactly what a drag does
    win._repaint()
    assert surface._content is content, "the content was redrawn for a move"
    assert surface._content_key == boxes, "the content signature moved with the card"
    assert surface._plate_key != plate, "the glass was NOT redrawn for a move"

    # and a change of state does redraw it
    win._status("something happened")
    win._repaint()
    assert surface._content is not content, "the content never redraws at all"
finally:
    win.root.destroy()
os._exit(0)
''')


def test_every_painted_control_is_clickable_where_it_is_painted() -> None:
    """The owner reported that the keyboard and the pencil did nothing.

    Both were painted, both had hit boxes, and both were unreachable: the
    composer registers its whole row as a box, the small controls sit
    INSIDE that row, and the hit test returned the first match in dict
    order -- which was the row. Every click was swallowed by the strip it
    landed on.

    Smallest-box-wins fixes it without any ordering discipline, and this
    test is the one that would have caught it: it clicks each control at
    the centre of the rectangle THE PAINTER recorded, so the picture and
    the targets are checked against each other rather than against a
    hand-written table of coordinates.
    """
    _run_window_script('''
import os, time
from PIL import Image
import visual_qa as vq

img = Image.new("RGB", (400, 240), (30, 30, 30))
win = vq.AskWindow(img, (200, 200, 600, 440), vq.Speaker(), "off",
                   lambda *a, **k: ("", "test"))

class E:
    def __init__(self, x, y):
        self.x, self.y = x, y
        self.x_root, self.y_root = x, y

def click(name):
    box = win.surface.boxes.get(name)
    assert box is not None, f"{name} is not painted at all"
    x0, y0, x1, y1 = box
    ev = E(win._cx + (x0 + x1) // 2, win._cy + (y0 + y1) // 2)
    assert win._hit(ev.x, ev.y) == name, (name, win._hit(ev.x, ev.y))
    win._on_press(ev)
    win._on_release(ev)
    win.root.update()

def settle():
    for _ in range(40):
        win._animate()
        win.root.update()
        time.sleep(0.005)

try:
    win.root.update()
    assert win._mode == "voice", win._mode
    assert "talk" in win.surface.boxes, "no circle to talk at"

    click("keyboard")
    settle()
    assert win._mode == "text", win._mode
    assert win._open > 0.9, win._open
    assert "send" in win.surface.boxes, "an open field with no way to send"

    click("pencil")
    assert win._drawing is True, "the pencil did not arm"

    click("keyboard")
    settle()
    assert win._mode == "voice", win._mode
    assert win._open < 0.1, win._open
    # and the field is gone, not merely empty: the entry is parked off
    # the card so no caret can blink in a window that has no field
    assert win.surface.boxes["entry"][0] < -1000, win.surface.boxes["entry"]
finally:
    win.root.destroy()
os._exit(0)
''')


def test_a_closed_card_leaves_no_interpreter_for_another_thread_to_free() -> None:
    """The crash the owner hit twice: dictate for 73 s after using the
    card and the whole app disappears, no traceback, `tcl86t.dll` and
    exception 0x80000003 in the Windows event log.

    A Tk widget tree is CYCLIC, so dropping the last reference to the
    card never frees it — only the generational collector does, on
    whichever thread happens to trip the allocation threshold. Freeing it
    there runs Tcl_DeleteInterp on a thread that did not build the
    interpreter, and Tcl answers that with a panic: abort, no Python
    exception, nothing in app.log. A long transcription allocating on the
    worker thread is exactly such a threshold.

    So the flow's own thread has to do the collecting AFTER every
    reference is gone, which is later than run() can manage — run()
    returns while _open_ask's local and the controller's handle both
    still point at the card.

    Note there is no os._exit(0) here, unlike every other card test. That
    call is what hid this bug: it skips collection entirely, so the suite
    could never have watched the wrong thread do the freeing.
    """
    _run_window_script('''
import gc, sys, time
from pathlib import Path
from PIL import Image
import config
import visual_qa as vq

gc.disable()                 # only explicit collects: we choose the thread

cfg = config.load(Path("config.toml"))
ctrl = vq.Controller(lambda: cfg)
img = Image.new("RGB", (320, 160), (30, 30, 30))
ctrl._grab_selection = lambda: (img, (100, 100, 420, 260))
ctrl._ask = lambda *a, **k: ("ארבעים ושתיים", "test")

assert ctrl.begin_selection()
deadline = time.monotonic() + 20
while not ctrl.sink_active and time.monotonic() < deadline:
    time.sleep(0.02)
assert ctrl.sink_active, "the card never came up"

ctrl.stop()
while ctrl.busy and time.monotonic() < deadline:
    time.sleep(0.02)
assert not ctrl.busy, "the flow never finished"

# Whatever the card left behind, _flow must already have buried it on its
# own thread. If anything Tk is still cyclic garbage here, THIS collect is
# the wrong thread doing the freeing and Tcl aborts the process.
freed = gc.collect()
assert freed == 0, f"the card left {freed} objects for another thread"
''')


def test_an_arriving_answer_never_eats_what_you_typed_while_waiting() -> None:
    """Anything in the box when an answer lands was typed WHILE the model
    was writing, which makes it the next question. v1 cleared the box on
    every answer, so a follow-up dictated a second too early vanished
    without a word — and the box is not disabled any more precisely so
    that typing over an answer works the way talking over one does."""
    _run_window_script('''
import os
from PIL import Image
import visual_qa as vq

img = Image.new("RGB", (320, 160), (30, 30, 30))
win = vq.AskWindow(img, (100, 100, 600, 400), vq.Speaker(), "off",
                   lambda *a, **k: ("", "test"))
try:
    win.root.update()
    assert str(win.entry.cget("state")) == "normal", win.entry.cget("state")

    win.busy = True
    win._gen = 1
    win._pending_q = "מה כתוב פה"
    win.entry.insert(0, "ואיך מתקנים את זה")
    win._on_answer((1, "מה כתוב פה", "ככה וככה", "test", 1.2))
    win.root.update()

    assert win.entry.get() == "ואיך מתקנים את זה", win.entry.get()
    assert win.answer_text == "ככה וככה", win.answer_text
    assert len(win.history) == 2, win.history

    # ...and an answer for a question that was already superseded is
    # dropped on the floor rather than overwriting the real one.
    win._on_answer((0, "שאלה ישנה", "תשובה ישנה", "test", 9.9))
    assert win.answer_text == "ככה וככה", win.answer_text
    assert len(win.history) == 2, win.history
finally:
    win.root.destroy()
os._exit(0)
''')


def test_the_card_is_a_borderless_pane_that_can_be_moved() -> None:
    """It is the lookup box's family, not a dialog: no caption, no
    taskbar button, translucent until the pointer is on it, and dragged
    by its own title strip. Everything Windows used to draw for us is
    hand-built, so each piece is worth one assert."""
    _run_window_script('''
import ctypes, os
from PIL import Image
import visual_qa as vq

img = Image.new("RGB", (320, 160), (30, 30, 30))
win = vq.AskWindow(img, (100, 100, 600, 400), vq.Speaker(), "off",
                   lambda *a, **k: ("", "test"), alpha=0.9)
try:
    win.root.update()
    assert win.root.overrideredirect(), "the card grew a title bar"
    # NOT -alpha any more. Whole-window alpha made the TEXT
    # translucent too, which was half of why the old card was hard
    # to read; the card is opaque pixels now and the see-through
    # is painted into them.
    assert float(win.root.attributes("-alpha")) == 1.0, \\
        win.root.attributes("-alpha")

    WS_CAPTION = 0x00C00000
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    hwnd = user32.GetParent(int(win.root.winfo_id())) or int(win.root.winfo_id())
    style = user32.GetWindowLongW(hwnd, -16)          # GWL_STYLE
    assert not style & WS_CAPTION, hex(style)

    # The window IS the frozen screen; the card is a position
    # painted on it, so a drag moves the painting, not the window.
    vx, vy, _vw, _vh = vq.virtual_screen()
    win._cx, win._cy = 300 - vx, 300 - vy
    win._repaint()

    class E:
        x_root, y_root = 340, 330
    win._drag_start(E)
    E.x_root, E.y_root = 420, 380
    win._drag_move(E)
    win.root.update()
    assert win._screen_xy() == (380, 350), win._screen_xy()

    moved = []
    win.on_move = moved.append
    win._drag_end()
    assert moved == [(380, 350)], moved
finally:
    win.root.destroy()
os._exit(0)
''')


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items())
             if n.startswith("test_") and callable(f)]
    print(f"running {len(tests)} tests", flush=True)
    for test_name, fn in tests:
        check(test_name, fn)
        # Collected HERE, on the main thread, and not left to whenever a
        # worker thread next allocates. The splash/status-dot tests stand
        # up real Tcl interpreters on their own threads, and a Tk object
        # that dies in a GC pass run by ANOTHER thread hard-aborts the
        # process ("Tcl_AsyncDelete: async handler deleted by the wrong
        # thread") — measured 2026-08-22, mid-suite at whatever test came
        # after them once allocation timing shifted. One collect per test
        # makes the thread that owns Tcl the one that buries it.
        gc.collect()
    if FAILURES:
        print(f"\n{len(FAILURES)} FAILED: {', '.join(FAILURES)}")
        sys.exit(1)
    print("\nall tests passed")
