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
import json
import os
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
import hint as hint_mod
import injector
import overlay as overlay_mod
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
    m.handle("down", VK_LCTRL, injected=False)  # recording: a modifier defers
    assert spy.events == ["start"], spy.events
    m.handle("up", VK_LCTRL, injected=False)
    m.handle("up", VK_RCTRL, injected=False)
    assert spy.events == ["start", "stop"], spy.events


def test_a_modifier_alone_defers_and_the_letter_aborts() -> None:
    """The abort rule reads the COMBO, not the reach for one.

    It used to fire on the modifier's key-down, which is the one moment a
    chord can never be judged from: every chord this app binds starts with
    a modifier, so aborting there made ctrl+F10 and win+shift+s
    unpressable mid-dictation by construction. Deferring costs nothing —
    Ctrl+C still throws the recording away, one key later, on the C.
    """
    spy = Spy()
    m = spy.machine()
    m.handle("down", VK_RCTRL, injected=False)
    m.handle("down", VK_LCTRL, injected=False)   # reaching for a combo
    assert spy.events == ["start"], spy.events
    m.handle("down", VK_C, injected=False)       # ...and there it is
    assert spy.events == ["start", "abort:'c' pressed mid-hold"], spy.events


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
    # The ask card's echo notes: _handle adds to these when a dictation was
    # aimed at the card, and _on_card_closed hands them to the field the
    # card interrupted. [visual_qa] echo_to_field.
    app._echo_lines = []
    app._question_texts = []
    app._field_hwnd = 0
    app._echo_lock = threading.Lock()
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


# --------------------- the app's half of "features in parallel"
#
# hotkey.py decides WHEN a key may fire; these are the answers main.py
# gives it, and the two facts a dictation now has to carry with it.

class _FakeSink:
    """A stand-in ask card. `busy` is what claims Escape, `sink_active` is
    what used to decide where a transcript went."""

    def __init__(self, sink_active=False, busy=False, recording=False,
                 echoing=True):
        self.sink_active = sink_active
        self.busy = busy
        self.recording = recording
        # The switch in the card's title strip: is what is dictated here
        # also going to the field the card was opened over?
        self.echoing = echoing
        self.delivered = []

    def deliver_transcript(self, text):
        self.delivered.append(text)
        return True


class _FakeHint:
    """A stand-in hint card: it only records what it was asked to show.

    Every test that drives _set_state on a hand-built App needs one,
    because the card rides the same state the dot does and is deliberately
    fed from the same line — see main.App._set_state.
    """

    def __init__(self):
        self.shown = []

    def show(self, card):
        self.shown.append(card)

    def start(self):
        pass

    def stop(self):
        pass


def _policy_app():
    import main as main_mod
    app = main_mod.App.__new__(main_mod.App)
    app._cue_lock, app._cue_last = threading.Lock(), {}
    return app


def test_screen_keys_work_mid_hold_and_text_keys_wait() -> None:
    """The split the whole feature turns on, stated once.

    Pixels need no hands and no caret, so they are as true mid-sentence as
    at rest. The keys that read or rewrite the text AT THE CURSOR are a
    different matter, because the cursor is where the transcript being
    recorded is about to land — and while the hotkey is HELD one hand is
    pinned to it, so there is no selection for them to act on anyway.
    """
    app = _policy_app()
    for action in ("visual_qa", "capture", "record", "photo"):
        assert app._tap_allowed(action, hotkey_mod.RECORDING), action
        assert app._tap_allowed(action, hotkey_mod.LATCHED), action
        assert app._tap_allowed(action, hotkey_mod.IDLE), action
    for action in ("translate", "punctuate", "correct", "lookup"):
        assert not app._tap_allowed(action, hotkey_mod.RECORDING), action
        # Latched the hands are FREE — that is what latching is for — and
        # the cursor lock already serialises these against the paste.
        assert app._tap_allowed(action, hotkey_mod.LATCHED), action
        assert app._tap_allowed(action, hotkey_mod.IDLE), action


def test_escape_goes_to_whichever_window_has_the_foreground() -> None:
    """Esc discards a locked recording, and also closes the selector, the
    capture overlay, the clip bar, the camera and the ask card. Exactly
    one per press, and FOCUS is what decides which.

    Asking the controllers whether they were "busy" was the first answer
    and it was wrong in both directions: capture.busy stays set through
    the post-shot toast and the clip toast, neither of which reads Escape
    or takes focus, so for about twelve seconds after a screenshot Esc
    stopped being the way out of a locked recording and nothing consumed
    it instead.
    """
    import main as main_mod

    app = _policy_app()
    app.popup = _SpyPopup()
    real, ours = main_mod.injector, {"mine": False}

    class _Windows:
        ClipboardBusyError = real.ClipboardBusyError
        FocusChangedError = real.FocusChangedError

        @staticmethod
        def foreground_window():
            return 0x1234

        @staticmethod
        def is_our_window(hwnd):
            return ours["mine"]

    try:
        main_mod.injector = _Windows
        assert app._esc_is_claimed() is False, \
            "the user's own window is in front: the recording has the key"
        ours["mine"] = True
        assert app._esc_is_claimed() is True, \
            "one of ours is in front: it gets its own Esc"
        # A busy controller with no window in front — the toasts — must not
        # claim it. That is the whole bug this test exists for.
        ours["mine"] = False
        app._capture = _FakeSink(busy=True)
        app._vqa = _FakeSink(busy=True)
        assert app._esc_is_claimed() is False, \
            "busy is not the same question as on screen"
    finally:
        main_mod.injector = real


def test_esc_guard_never_builds_a_controller() -> None:
    """It runs inside the keyboard hook. Touching the `vqa` or `capture`
    property there would import Tk, Pillow and a vision chain from a
    callback Windows unhooks at 300 ms."""
    app = _policy_app()
    app.popup = _SpyPopup()

    def boom(self):
        raise AssertionError("the esc guard built a controller")

    import main as main_mod
    for name in ("vqa", "capture"):
        assert isinstance(getattr(main_mod.App, name), property), name
    saved = main_mod.App.vqa, main_mod.App.capture
    try:
        main_mod.App.vqa = property(boom)
        main_mod.App.capture = property(boom)
        app._esc_is_claimed()
    finally:
        main_mod.App.vqa, main_mod.App.capture = saved


def test_a_card_opened_mid_dictation_does_not_steal_the_transcript() -> None:
    """WHERE a dictation goes is decided when it STARTS.

    Read at transcription time instead, a card opened while the user was
    still speaking swallowed the paragraph they were dictating into their
    editor — and the '...' marker already in that editor could not even be
    taken back down, because the card had the foreground by then.
    """
    import shutil
    import tempfile

    import main as main_mod

    tmp = Path(tempfile.mkdtemp(prefix="dictation-sink-"))
    fake = _FakeInjector()
    real = main_mod.injector
    try:
        main_mod.injector = fake
        app = _worker_app(_Flaky(fail_times=0), tmp)
        card = _FakeSink(sink_active=True)   # it opened while they spoke
        app._vqa = card

        app._handle(b"RIFF-audio", 4.0, fake.focus, None, False)
        assert card.delivered == [], card.delivered
        assert [c[0] for c in fake.calls] == ["show", "replace"], fake.calls

        # ...and the other way round: a dictation that was AIMED at the
        # card still reaches it, and nothing is pasted at the cursor.
        fake.calls.clear()
        app._handle(b"RIFF-audio", 4.0, fake.focus, None, True)
        assert card.delivered == ["שלום"], card.delivered
        assert fake.calls == [], fake.calls

        # And the case the start-window fallback can produce: NO window at
        # all. Pasting on "no window" means pasting into whatever has focus
        # now, which is most likely the overlay that caused the question.
        # It goes to the clipboard with an explanation instead.
        fake.calls.clear()
        card.sink_active = False
        app._handle(b"RIFF-audio", 4.0, 0, None, False)
        assert [c[0] for c in fake.calls] == ["clipboard"], fake.calls
    finally:
        main_mod.injector = real
        shutil.rmtree(tmp, ignore_errors=True)


def test_a_transcript_is_never_aimed_at_one_of_our_own_windows() -> None:
    """The clip bar of a screen recording takes the foreground when Tk
    realises it and never gives it back, so a dictation can both START and
    END with one of ours in front. Aimed there, the marker and the whole
    transcript are fired into our own window and every focus test in
    _handle passes, so it is reported as a success and the user's real
    target never hears about it. 0 — "nowhere known" — is the only honest
    answer, and _handle turns that into the clipboard.
    """
    import main as main_mod

    app = main_mod.App.__new__(main_mod.App)
    real = main_mod.injector
    ours = {"mine": True}

    class _Windows:
        @staticmethod
        def foreground_window():
            return 0x1111

        @staticmethod
        def is_our_window(hwnd):
            return bool(hwnd) and ours["mine"]

    class _Recorder:
        def begin(self): pass
        def meter(self): return 0.0, True

    class _Cfg:
        max_seconds = 400.0
        hotkey = "right ctrl"
        latch_hotkey = "left"
        visual_qa = None

    try:
        main_mod.injector = _Windows
        app.cfg, app.recorder = _Cfg(), _Recorder()
        app.dot = type("D", (), {"set_state": lambda s, v: None})()
        app.hint = _FakeHint()
        app.machine = type("M", (), {"state": hotkey_mod.RECORDING})()
        app._activity = "ready"
        app._vqa = None
        app._on_start(None)
        assert app._start_hwnd == 0, hex(app._start_hwnd)
        # ...and with the user's own window in front, it is remembered.
        ours["mine"] = False
        app._on_start(None)
        assert app._start_hwnd == 0x1111, hex(app._start_hwnd)
    finally:
        main_mod.injector = real


def test_the_app_actually_hands_its_policy_to_the_state_machine() -> None:
    """Without the wiring, every rule above is inert and the keys go back
    to being dead mid-dictation — which is a silent failure, because
    PTTStateMachine's default for `tap_allowed is None` is exactly the old
    idle-only behaviour. One deleted keyword argument in a merge and the
    whole feature is gone with the suite still green."""
    import inspect

    import main as main_mod

    source = inspect.getsource(main_mod.App.__init__)
    for wiring in ("tap_allowed=self._tap_allowed",
                   "cancel_guard=self._esc_is_claimed"):
        assert wiring in source, wiring
    # ...and that the machine really does consult them, rather than the
    # names merely being accepted and ignored.
    asked = []
    m = PTTStateMachine(
        {VK_RCTRL: "he"},
        on_start=lambda l: None, on_stop=lambda l: None,
        on_abort=lambda w: None,
        taps={parse_binding("ctrl+f10"): "visual_qa"},
        on_tap=lambda a: asked.append(("tap", a)),
        latch_vk=VK_LEFT, on_latch=lambda: None,
        tap_allowed=lambda action, state: asked.append(
            ("allowed?", action, state)) or True,
        cancel_guard=lambda: asked.append(("esc?",)) or False)
    m.handle("down", VK_RCTRL, injected=False)
    m.handle("down", VK_LEFT, injected=False)
    m.handle("up", VK_LEFT, injected=False)
    m.handle("up", VK_RCTRL, injected=False)
    _strike(m, VK_LCTRL_, 0x79)
    m.handle("down", VK_ESC, injected=False)
    assert ("allowed?", "visual_qa", "latched") in asked, asked
    assert ("esc?",) in asked, asked


def test_the_clipboard_is_one_queue_for_the_whole_process() -> None:
    """THE headline fix, and it had no test.

    A screenshot lands its CF_DIB in the ~350 ms between this app staging
    a transcript and the target app asynchronously reading it, and without
    the queue the user gets the picture pasted into their document instead
    of their sentence — measured 39 times out of 40. Every operation that
    reads the clipboard as an inference, or holds it across a paste, has
    to be inside the same lock, and dropping any one `with _board_lock:`
    puts that back silently.
    """
    import inspect

    for name in ("_put_text", "clear", "paste_text", "inject", "grab",
                 "read_selection", "set_text", "snapshot"):
        source = inspect.getsource(getattr(injector, name))
        assert "_board_lock" in source, \
            f"injector.{name} writes or reads the clipboard off the queue"

    import capture as cap
    for name in ("copy_image", "copy_file"):
        source = inspect.getsource(getattr(cap, name))
        assert "_board(" in source, \
            f"capture.{name} writes the clipboard without taking the queue"
    assert "board_held" in inspect.getsource(cap._board)

    # And it really excludes: a second thread cannot get in mid-operation.
    got = []
    with injector.board_held():
        t = threading.Thread(
            target=lambda: got.append(
                injector._board_lock.acquire(timeout=0.05)))
        t.start()
        t.join()
    assert got == [False], got
    # ...and it is reentrant, because inject() holds it across snapshot,
    # paste_text and restore, each of which takes it again.
    with injector.board_held():
        with injector.board_held():
            pass


def test_a_screenshot_survives_the_transcript_that_pastes_after_it() -> None:
    """The headline gesture, end to end: take a screenshot while you talk,
    and the screenshot is still on the clipboard afterwards.

    inject() used to save and restore TEXT only, so a paste over an image
    reported "cannot restore it" and left the transcript where the picture
    had been. That was a fair trade while the screenshot key was dead
    during a dictation; it stopped being one the moment this change made
    "shoot while you speak" the point.
    """
    from PIL import Image

    import capture as cap

    before = injector.snapshot()
    if before[0] == "other":
        print("        (clipboard holds non-text content — skipping so "
              "it isn't lost)")
        return
    real_chord = injector.send_chord
    try:
        if not cap.copy_image(Image.new("RGB", (24, 16), (255, 0, 255))):
            print("        (the clipboard would not take an image — "
                  "skipping)")
            return
        assert injector.snapshot()[0] == "other", "the image never landed"
        injector.send_chord = lambda *_a, **_k: None   # type nothing here
        status = injector.inject("שלום", "ctrl+v", 20)
        assert injector.snapshot()[0] == "other", \
            f"the screenshot was pasted over: {status}"
    finally:
        injector.send_chord = real_chord
        if before[0] == "text":
            injector.set_text(before[1] or "")
        elif before[0] == "empty":
            injector.clear()


def test_a_live_recording_outranks_ready_on_the_indicator() -> None:
    """One string, several threads. The transcription worker's closing
    "ready" — for the PREVIOUS dictation, or for a screen question asked
    over this one — must not report a running microphone as finished."""
    import main as main_mod

    app = main_mod.App.__new__(main_mod.App)
    seen = []

    class _Dot:
        def set_state(self, state):
            seen.append(state)

    class _Machine:
        state = hotkey_mod.LATCHED

    app.dot, app.machine, app._activity = _Dot(), _Machine(), "locked"
    app.hint = _FakeHint()
    app._set_state("ready")
    app._set_state("busy")
    assert app._activity == "locked" and seen == [], (app._activity, seen)
    # "paused" is a statement about the recording itself and still lands.
    app._set_state("paused")
    assert app._activity == "paused", app._activity
    app.machine.state = hotkey_mod.IDLE
    app._set_state("ready")
    assert app._activity == "ready" and seen == ["paused", "ready"], seen


def test_the_study_engine_stands_down_for_the_screen_features() -> None:
    """A screen recording encodes video on the same card the study pass
    wants, and its dropped frames are in a file nobody can re-take."""
    import main as main_mod

    app = main_mod.App.__new__(main_mod.App)
    app._activity = "ready"
    app.queue = queue.Queue()
    app._text_busy = threading.Event()
    app._correcting = threading.Event()
    app._looking_up = threading.Event()
    assert app._learning_quiet() is True
    app._capture = _FakeSink(recording=True)
    assert app._learning_quiet() is False
    app._capture = _FakeSink()
    app._vqa = _FakeSink(busy=True)
    assert app._learning_quiet() is False


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


def test_tap_key_mid_recording_does_not_translate_and_does_not_abort() -> None:
    """Pressing it while dictating must not fire a translation at a
    half-finished recording — and must not destroy the recording either.

    The refusal is the DEFAULT policy (no `tap_allowed` given: taps are an
    idle-only thing, which is what every caller that predates parallel
    features still gets). What changed is the price of the press. It used
    to abort, so a mistimed feature key cost the whole dictation; now the
    key does nothing and the recording finishes normally.
    """
    spy = Spy()
    m = _tap_machine(spy)
    m.handle("down", VK_RCTRL, injected=False)
    m.handle("down", VK_F9, injected=False)
    assert spy.events == ["start"], spy.events
    m.handle("up", VK_F9, injected=False)
    m.handle("up", VK_RCTRL, injected=False)
    assert spy.events == ["start", "stop"], spy.events
    # ...and the key is still armed for a real press afterwards
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

    # The trap that is still real: right ctrl is the DICTATION key on this
    # machine, so it starts a recording rather than acting as the chord's
    # ctrl, and ctrl+F6 cannot be reached with that hand. What changed is
    # what it costs — the recording used to be thrown away for it, and now
    # survives, because a key this app has bound is never a stray
    # keystroke (see PTTStateMachine's abort rule).
    spy.events.clear()
    _strike(m, VK_RCTRL_, VK_F6)
    assert spy.events == ["start", "stop"], spy.events


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


# ------------------------------------ feature keys DURING a dictation
#
# The owner's report, 2026-08-30: "I am dictating this message and I want
# to use ctrl+F10 at the same time — the button has simply vanished, there
# is no such button, because the app is locked onto the audio." It had:
# taps only ever fired in IDLE, so every feature key was dead for as long
# as anyone was speaking. These are the rules that replaced that.

def _parallel_machine(spy, taps, allowed=None, claimed=None):
    """A machine wired the way main.py wires the real one: chords, a latch,
    a policy saying which actions may fire mid-dictation, and a guard that
    can claim Escape for something already on screen."""
    return PTTStateMachine(
        {VK_RCTRL: "he"},
        on_start=lambda lang: spy.events.append("start"),
        on_stop=lambda lang: spy.events.append("stop"),
        on_abort=lambda why: spy.events.append(f"abort:{why}"),
        taps=taps, on_tap=lambda action: spy.events.append(action),
        latch_vk=VK_LEFT, on_latch=lambda: spy.events.append("latch"),
        tap_allowed=allowed, cancel_guard=claimed)


def _screens_only(action, state):
    """main.py's real policy in miniature — see App._tap_allowed."""
    return state != "recording" or action in ("visual_qa", "capture")


def test_a_feature_key_fires_while_latched_and_the_recording_runs_on() -> None:
    """The report this whole section exists for. Latched, the hands are
    free BY DESIGN, so this is the state where every key must work."""
    spy = Spy()
    m = _parallel_machine(
        spy, {parse_binding("ctrl+f10"): "visual_qa"}, allowed=_screens_only)
    m.handle("down", VK_RCTRL, injected=False)
    m.handle("down", VK_LEFT, injected=False)     # latch it on
    m.handle("up", VK_LEFT, injected=False)
    m.handle("up", VK_RCTRL, injected=False)
    _strike(m, VK_LCTRL_, 0x79)                   # ctrl+F10
    assert spy.events == ["start", "latch", "visual_qa"], spy.events
    m.handle("down", VK_LEFT, injected=False)     # ...and it still stops
    assert spy.events[-1] == "stop", spy.events


def test_a_feature_key_fires_mid_hold_and_does_not_abort() -> None:
    """Holding the key is the harder half: every chord starts with a
    modifier, and a modifier used to abort on its own key-down."""
    spy = Spy()
    m = _parallel_machine(
        spy, {parse_binding("ctrl+f10"): "visual_qa"}, allowed=_screens_only)
    m.handle("down", VK_RCTRL, injected=False)
    _strike(m, VK_LCTRL_, 0x79)
    assert spy.events == ["start", "visual_qa"], spy.events
    m.handle("up", VK_RCTRL, injected=False)
    assert spy.events == ["start", "visual_qa", "stop"], spy.events


def test_the_key_holding_a_recording_open_is_not_a_chord_modifier() -> None:
    """Right Ctrl is the dictation key, and while it is holding a recording
    open it is doing that job and not standing in as a ctrl.

    Both halves matter. Counted as held it would make win+shift+s look
    like ctrl+win+shift+s, which the exact-match rule rightly refuses — so
    the capture key would be unreachable for as long as anyone was
    talking, which is the bug. And NOT counting it is what keeps a bare F8
    (correct) from quietly becoming ctrl+F8 (lookup) just because the hand
    on the hotkey happens to be a ctrl.
    """
    spy = Spy()
    m = _parallel_machine(
        spy, {parse_binding("win+shift+s"): "capture"}, allowed=_screens_only)
    m.handle("down", VK_RCTRL, injected=False)
    m.handle("down", 0x5B, injected=False)         # win
    m.handle("down", VK_LSHIFT_, injected=False)   # shift
    assert m.handle("down", 0x53, injected=False) is True, \
        "the S is still taken from Windows mid-dictation"
    assert spy.events == ["start", "capture"], spy.events
    m.handle("up", 0x53, injected=False)
    m.handle("up", VK_LSHIFT_, injected=False)
    m.handle("up", 0x5B, injected=False)
    m.handle("up", VK_RCTRL, injected=False)
    assert spy.events[-1] == "stop", spy.events

    # The other half, on a machine that allows everything so the MATCHER
    # is what is under test rather than the policy: F8 with nothing held
    # but the hotkey is the BARE binding. If the hotkey's ctrl counted,
    # "correct" would silently have become "lookup" — a key that copies
    # the selection out of whatever has focus, fired mid-dictation, by a
    # press that asked for something else entirely.
    spy2 = Spy()
    m2 = _parallel_machine(
        spy2, {parse_binding("f8"): "correct",
               parse_binding("ctrl+f8"): "lookup"},
        allowed=lambda action, state: True)
    m2.handle("down", VK_RCTRL, injected=False)
    _strike(m2, VK_F8)
    assert spy2.events == ["start", "correct"], spy2.events
    # ...and the LEFT ctrl, which is not holding anything open, still
    # completes the chord it names.
    _strike(m2, VK_LCTRL_, VK_F8)
    assert spy2.events == ["start", "correct", "lookup"], spy2.events


def test_holding_and_latched_agree_about_the_same_hand() -> None:
    """The exclusion is not dead in the latched state.

    LATCHED is only ever entered from RECORDING on the latch key, which
    means the hold hotkey is still physically down at that instant — so
    there is a window, until the hand comes off, where Right Ctrl is both
    holding a recording open and sitting in the held-modifier set. Without
    the same exclusion the two states disagree about one hand position:
    measured, F8 gave `correct` while holding and `lookup` one keystroke
    later while latched, and win+shift+s went from firing (and being taken
    from Windows) to matching nothing at all.
    """
    def machine(spy):
        return _parallel_machine(
            spy, {parse_binding("f8"): "correct",
                  parse_binding("ctrl+f8"): "lookup",
                  parse_binding("win+shift+s"): "capture"},
            allowed=lambda action, state: True)

    held, latched = Spy(), Spy()
    for spy, m, latch in ((held, machine(held), False),
                          (latched, machine(latched), True)):
        m.handle("down", VK_RCTRL, injected=False)
        if latch:
            # Latch WITHOUT letting go of the hotkey — the moment this is
            # about.
            m.handle("down", VK_LEFT, injected=False)
            m.handle("up", VK_LEFT, injected=False)
        _strike(m, VK_F8)
        m.handle("down", 0x5B, injected=False)
        m.handle("down", VK_LSHIFT_, injected=False)
        spy.swallowed = m.handle("down", 0x53, injected=False)
        m.handle("up", 0x53, injected=False)
        m.handle("up", VK_LSHIFT_, injected=False)
        m.handle("up", 0x5B, injected=False)

    assert held.events == ["start", "correct", "capture"], held.events
    assert latched.events == ["start", "latch", "correct", "capture"], \
        latched.events
    assert held.swallowed is True and latched.swallowed is True, \
        "the S is taken from Windows in both states or in neither"


def test_a_refused_feature_key_costs_nothing_but_the_press() -> None:
    """A key the policy says no to must not also destroy the recording.
    Silence is the answer, and main.py makes a noise about it."""
    spy = Spy()
    m = _parallel_machine(
        spy, {parse_binding("ctrl+f9"): "translate"}, allowed=_screens_only)
    m.handle("down", VK_RCTRL, injected=False)
    _strike(m, VK_LCTRL_, 0x78)                    # ctrl+F9: not a screen key
    assert spy.events == ["start"], spy.events
    m.handle("up", VK_RCTRL, injected=False)
    assert spy.events == ["start", "stop"], spy.events


def test_ctrl_c_still_throws_a_held_recording_away() -> None:
    """The rule the abort test was bought for, and it has to survive all
    of the above: a combo the app has NOT bound means the user is typing,
    not dictating."""
    spy = Spy()
    m = _parallel_machine(
        spy, {parse_binding("ctrl+f10"): "visual_qa"}, allowed=_screens_only)
    m.handle("down", VK_RCTRL, injected=False)
    m.handle("down", VK_LCTRL_, injected=False)
    m.handle("down", VK_C, injected=False)
    assert spy.events == ["start", "abort:'c' pressed mid-hold"], spy.events


def test_an_overlay_on_screen_owns_escape_and_the_lock_survives() -> None:
    """Esc cancels the region selector, the capture overlay, the camera and
    the ask card — and it also discards a locked recording. One keystroke
    must not do both, and the window that needs it is FOCUSED, so it
    cannot simply be swallowed the way the lookup box's Esc is."""
    spy = Spy()
    claimed = {"now": True}
    m = _parallel_machine(spy, {parse_binding("ctrl+f10"): "visual_qa"},
                          allowed=_screens_only,
                          claimed=lambda: claimed["now"])
    m.handle("down", VK_RCTRL, injected=False)
    m.handle("down", VK_LEFT, injected=False)
    m.handle("up", VK_RCTRL, injected=False)
    assert m.handle("down", VK_ESC, injected=False) is False, \
        "the overlay is focused and has to RECEIVE its own Esc"
    assert spy.events == ["start", "latch"], spy.events
    claimed["now"] = False           # the overlay is gone
    m.handle("up", VK_ESC, injected=False)
    m.handle("down", VK_ESC, injected=False)
    assert spy.events[-1] == "abort:esc pressed while locked", spy.events


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


def test_phone_punctuate_route_and_the_guards_around_it() -> None:
    """The phone's F2 key, and the two refusals that cost nothing.

    The 409 is the load-bearing one. A reply the Punctuator threw away
    because the model rewrote the words is NOT the same event as a backend
    that could not be reached, and the phone has exactly one status line to
    explain itself in — so the two have to be tellable apart by status code
    rather than by reading the sentence. The other assertions are the
    desktop's "refuse rather than spend" rule finally reaching the phone:
    text with no Hebrew in it must not cost a Gemini request, and text with
    no words in it must not cost anything at all.
    """
    import dataclasses

    import punctuate as punctuate_mod
    import requests

    import server as server_mod

    cfg = config_mod.load(Path(__file__).resolve().parent / "config.toml")
    cfg = dataclasses.replace(
        cfg, server=config_mod.ServerConfig(enabled=True, host="127.0.0.1",
                                            port=8798))
    spent: list[str] = []
    unsafe = [False]

    def fake_punctuate(text):
        spent.append(text)
        if unsafe[0]:
            raise punctuate_mod.UnsafeReply("word count moved 40%")
        return text + ".", "fake"

    def fake_translate(text):
        spent.append(text)
        return "translated", "fake"

    srv = server_mod.PhoneServer(cfg, lambda wav: ("", "fake"),
                                 lambda: "fake", fake_translate,
                                 fake_punctuate)
    srv.start()
    base = "http://127.0.0.1:8798"
    auth = {"Authorization": f"Bearer {server_mod.load_token()}"}
    try:
        ok = requests.post(f"{base}/punctuate", timeout=10, headers=auth,
                           json={"text": "שלום עולם מה נשמע"})
        assert ok.status_code == 200, ok.status_code
        assert ok.json()["text"] == "שלום עולם מה נשמע.", ok.json()
        assert ok.json()["changed"] is True, ok.json()

        unsafe[0] = True
        rewrote = requests.post(f"{base}/punctuate", timeout=10, headers=auth,
                                json={"text": "שלום עולם"})
        assert rewrote.status_code == 409, rewrote.status_code
        assert rewrote.json().get("unsafe") is True, rewrote.json()
        unsafe[0] = False

        spent.clear()
        wordless = requests.post(f"{base}/punctuate", timeout=10, headers=auth,
                                 json={"text": "12 34 !!!"})
        assert wordless.status_code == 400, wordless.status_code
        assert not spent, "no words in it, and it still called the model"

        english = requests.post(f"{base}/translate", timeout=10, headers=auth,
                                json={"text": "this is already english"})
        assert english.status_code == 400, english.status_code
        assert not spent, "no Hebrew in it, and it still spent a request"

        hebrew = requests.post(f"{base}/translate", timeout=10, headers=auth,
                               json={"text": "שלום עולם"})
        assert hebrew.status_code == 200, hebrew.status_code
        assert spent, "the translator was never called"

        # The 401 used to name /transcribe whatever had actually been
        # called, which made app.log the wrong place to look for the one
        # thing it is there for.
        denied = requests.post(f"{base}/punctuate", timeout=10,
                               headers={"Authorization": "Bearer nope"},
                               json={"text": "שלום"})
        assert denied.status_code == 401, denied.status_code
    finally:
        srv.stop()


def test_phone_punctuate_is_absent_rather_than_broken_without_it() -> None:
    """A PhoneServer built without the callable answers 503, not a crash.

    The three-argument construction is what the round-trip test above uses
    and what any caller written before this route existed does, so it has
    to keep working — the route just reports itself unavailable.
    """
    import dataclasses

    import requests

    import server as server_mod

    cfg = config_mod.load(Path(__file__).resolve().parent / "config.toml")
    cfg = dataclasses.replace(
        cfg, server=config_mod.ServerConfig(enabled=True, host="127.0.0.1",
                                            port=8797))
    srv = server_mod.PhoneServer(cfg, lambda wav: ("", "fake"),
                                 lambda: "fake")
    srv.start()
    auth = {"Authorization": f"Bearer {server_mod.load_token()}"}
    try:
        r = requests.post("http://127.0.0.1:8797/punctuate", timeout=10,
                          headers=auth, json={"text": "שלום עולם"})
        assert r.status_code == 503, r.status_code
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
        # The wait is derived, not typed. With the skin installed the
        # splash's close is followed by a ~2.7 s release, and the 1.6 s
        # that used to be here reported "the splash never closed" when it
        # was simply still playing.
        "import skin.boot as _b; whole = _b.moment_ms() / 1000.0;"
        "s = ov.Splash(); s.start(); s.status('loading...'); time.sleep(.4);"
        "d = ov.StatusDot(); d.start(); time.sleep(.3);"
        "s.finish('ready', linger_ms=60); time.sleep(whole + 1.6);"
        "me = os.getpid(); found = [];"
        # Two classes, because there are two ways this app draws an
        # overlay. 'TkTopLevel' is the original pair; the skin (skin\) puts
        # the same two windows on a plain CreateWindowExW popup so it can
        # use UpdateLayeredWindow, and that popup registers a class of its
        # own. What is being asserted has not changed — the splash must be
        # gone and the dot must not have gone with it — only the way the
        # two windows are found. Naming both keeps this test honest with
        # the skin installed AND with it deleted.
        "classes = ('TkTopLevel', 'HebrewDictationSkinGlass');"
        "cb = lambda h, _: ("
        "    found.append(win32gui.GetWindowRect(h))"
        "    if win32process.GetWindowThreadProcessId(h)[1] == me"
        "    and win32gui.IsWindowVisible(h)"
        "    and win32gui.GetClassName(h) in classes else None);"
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
              "settings.py", "config.toml")
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


def test_undoing_the_apps_own_repair_teaches_it_nothing() -> None:
    """The 2026-08-28 loop, in one test.

    A bad rule rewrote a correctly-decoded "commit" into "make it". The user
    fixed the screen back. Diffing SCREEN against FIX proposes (make ->
    commit) — the app's own edit, read back to it as a mishearing — and one
    more press would have armed it and turned every "make" into "commit".
    The decoder never said "make", which is the tell.
    """
    heard = "Can you please commit it?"          # what the decoder produced
    shown = "Can you please make it it?"         # after the bad rule fired
    fixed = "Can you please commit it?"          # what the user typed back

    assert ("make", "commit") in vocab_mod.diff_corrections(shown, fixed),         "the diff must still propose it — the guard is what declines it"

    v = _tmp_vocab()
    assert v.learn_from_edit(shown, fixed, heard_in=heard) == []
    assert v.corrections == [], v.corrections


def test_the_guard_still_learns_what_the_decoder_really_said() -> None:
    """The filter must cost nothing on the path it protects: a real
    mishearing IS in the decoder's transcript, so it survives."""
    heard = "תריץ את השרת של xpogo"
    fixed = "תריץ את השרת של Expo Go"
    v = _tmp_vocab()
    assert v.learn_from_edit(heard, fixed, heard_in=heard) ==         [("xpogo", "Expo Go")]


def test_no_transcript_is_not_evidence_against_a_correction() -> None:
    """An empty `raw` must never be the reason a real fix is dropped."""
    assert vocab_mod.heard_by_decoder([("xpogo", "Expo Go")], "") ==         [("xpogo", "Expo Go")]


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
    # "cut off" is the tail guard answering first: this reply is a strict
    # word-prefix of the transcript, which _tail_loss rejects before the
    # ±15% band is even consulted. The band still catches drops that are
    # not prefixes, which is what "lost" covers.
    assert "lost" in why or "dropped" in why or "cut off" in why, why


def test_polish_rejects_a_tail_cut_that_is_small_enough_to_pass_the_band()\
        -> None:
    """The band is a PERCENTAGE, and a truncated reply hides inside it.

    Groq returned a reply that hit max_tokens on 2026-08-27 and the last
    five words of a 94-word transcript never reached the screen: 5% drift,
    comfortably inside ±15%, so nothing objected. A repair swaps words in
    the middle; only a cut answer reproduces the transcript and then stops.
    """
    import polish as polish_mod
    before = " ".join(f"מילה{i}" for i in range(94))
    after = " ".join(f"מילה{i}" for i in range(89))
    growth = (89 - 94) / 94
    assert abs(growth) < polish_mod.MAX_GROWTH, (
        "this test is pointless unless the cut fits inside the band")
    ok, why = polish_mod._is_safe(before, after)
    assert not ok, "a tail cut must be rejected however small it is"
    assert "5 word" in why, why
    # A cap can also land mid-word, leaving a fragment as the last token.
    ok, why = polish_mod._is_safe("שיש לו שיעורי בית לעשות ומסטורוס נוסע",
                                  "שיש לו שיע")
    assert not ok, "a reply cut mid-word must be rejected"
    # And none of this may reject an ordinary repair of the LAST word,
    # which is a swap, not a stop.
    ok, why = polish_mod._is_safe("תסדר את כל העמוד מחדש בבקשה",
                                  "תסדר את כל העמוד מחדש בבקשא")
    assert ok, why


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

        # With keys: groq first (prefer's default), Ollama behind it, and
        # NOT Cerebras — their free tier answers 402 to everything, so as a
        # fallback it can only spend the user's wait to fail. It is opt-in
        # now: only prefer = "cerebras" builds it.
        apikey_mod.find_key = all_keys
        names = [b.name for b in polisher._backends(text)]
        assert names == ["groq", "ollama"], names
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
    assert names == ["ollama", "groq"], names


def test_cerebras_is_opt_in_but_still_reachable() -> None:
    """Out of the fallback chain, not out of the app: whoever still holds
    quota there sets prefer = "cerebras" and gets it first, as before."""
    import dataclasses

    import apikey as apikey_mod
    import polish as polish_mod

    cfg = config_mod.load(Path(__file__).resolve().parent / "config.toml")
    cfg = dataclasses.replace(cfg, polish=dataclasses.replace(
        cfg.polish, prefer="cerebras"))
    polisher = polish_mod.Polisher(cfg, _tmp_vocab())
    original = apikey_mod.find_key
    try:
        apikey_mod.find_key = lambda names: ("test-key", "test")
        names = [b.name for b in polisher._backends("משפט לבדיקה בבקשה")]
    finally:
        apikey_mod.find_key = original
    assert names == ["cerebras", "groq", "ollama"], names


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
        app.hint = _FakeHint()
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
    feedback at all in the window.

    The copy runs on a thread now (the clipboard is a queue shared with
    the whole process, and a card that stopped repainting for two seconds
    because somebody pressed the lookup key would read as a hang), so the
    answer arrives through the pump. What must not change is that it
    arrives at all: both outcomes still reach the status line, in the
    right colour."""
    _run_window_script('''
import os, time
from PIL import Image
import injector
import visual_qa as vq

def settle(win):
    """The copy is on a thread and reports through the card's queue."""
    for _ in range(200):
        win._drain()
        win.root.update()
        if win.status.cget("text"):
            return
        time.sleep(0.01)

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
    settle(win)
    assert "clipboard busy" in win.status.cget("text"), \\
        win.status.cget("text")
    assert win.status.cget("fg") == vq.AMBER, win.status.cget("fg")

    copied = []
    win._status("", vq.DIM)
    injector.set_text = copied.append
    win._copy()
    settle(win)
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


def test_stop_stops_the_voice_without_freezing_the_card() -> None:
    """The owner: "it just crashes, I cannot stop it, I cannot get out."

    The card was not frozen and it was not crashing. winsound.PlaySound
    without SND_ASYNC BLOCKS its thread for the whole sentence, and
    PlaySound is process-global and single-channel -- so SND_PURGE,
    issued by whoever pressed Stop, waited for that call to return before
    it could do anything. The presser was the pump thread, so the card
    could not repaint and could not close until the voice finished by
    itself. Measured: 10.59 s from Stop to quiet. And because esc_action
    reads `playing`, the first Escape went on meaning "stop" the whole
    time, so there was no way out either.

    Three things had to change and each is asserted here: the flag drops
    at once, the synthesis subprocess is killable, and a stop that
    arrives BEFORE any sound does still prevents the sound.
    """
    import visual_qa as vq

    speaker = vq.Speaker()
    try:
        # a stop with nothing playing must be instant and harmless
        started = time.monotonic()
        speaker.stop()
        assert time.monotonic() - started < 0.5, "stop blocked on silence"
        assert not speaker.playing

        # the cancel flag is what makes a stop DURING synthesis stick:
        # the worker checks it before it ever reaches the speaker
        speaker._cancel.set()
        assert speaker._cancel.is_set()
        speaker._cancel.clear()
    finally:
        speaker.shutdown()

    # and the rule Escape follows, which is why a stop that does not take
    # effect also traps you in the card
    assert vq.esc_action(True) == "stop"
    assert vq.esc_action(False) == "close"


def test_a_lasso_sends_only_what_was_lassoed() -> None:
    """Shift-drag draws a shape instead of a box.

    Both gestures stay: a rectangle is one movement and lands exactly on
    a paragraph or a dialog, which is most of what gets asked about; a
    lasso is the only way to ask about something that is not a rectangle
    without dragging its neighbours in with it.

    What matters is that the shape is REAL -- everything outside the path
    is blacked out of the crop that goes to the model, not merely dimmed.
    A dimmed neighbour still gets described.
    """
    _run_window_script('''
import os
from PIL import Image, ImageStat
import visual_qa as vq

# a diamond in the middle of a bright square
size = 240
img = Image.new("RGB", (size, size), (220, 220, 220))
half = size // 2
path = [(500 + half, 500), (500 + size, 500 + half),
        (500 + half, 500 + size), (500, 500 + half)]

win = vq.AskWindow(img, (500, 500, 500 + size, 500 + size), vq.Speaker(),
                   "off", lambda *a, **k: ("", "test"), path=path)
try:
    win.root.update()
    assert win._sel_mask is not None, "the lasso never became a mask"
    marked = win.marked_image()
    assert marked.size == (size, size), marked.size
    # the corners are outside a diamond, the middle is inside
    corner = ImageStat.Stat(marked.crop((0, 0, 20, 20))).mean[0]
    middle = ImageStat.Stat(
        marked.crop((half - 20, half - 20, half + 20, half + 20))).mean[0]
    assert corner < 5, f"outside the lasso survived: {corner}"
    assert middle > 150, f"inside the lasso was blacked out: {middle}"

    # a plain rectangle keeps everything
    plain = vq.AskWindow(img, (500, 500, 500 + size, 500 + size),
                         vq.Speaker(), "off",
                         lambda *a, **k: ("", "test"))
    try:
        plain.root.update()
        assert plain._sel_mask is None
        kept = ImageStat.Stat(plain.marked_image().crop((0, 0, 20, 20))).mean[0]
        assert kept > 150, kept
    finally:
        plain.root.destroy()
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


def test_no_global_keeps_a_card_interpreter_alive_past_its_thread() -> None:
    """The same abort as the test above, by the one route that test is
    blind to: SPEAKING into the card.

    `gc.collect() == 0` only proves nothing is CYCLIC GARBAGE. A module
    global is not garbage — it is reachable — so a global holding a Tk
    object sails past that assertion and still kills the app, later, on
    whichever thread happens to drop the last reference.

    skin\wave.py did exactly that: `_owner = canvas.tk` cached the ring
    sprites against the interpreter they belonged to, and in doing so kept
    THE INTERPRETER. The rings are painted only while the microphone is
    live, so the leak needed a dictation to happen at all — which is why
    the owner only ever saw it when he talked to the card, and why the
    suite never saw it.

    Measured 2026-08-31 on the unfixed file: one card dictated into aborts
    at process exit, and two in a row abort mid-run when the second card's
    pump thread drops the first card's interpreter — "Tcl_AsyncDelete:
    async handler deleted by the wrong thread", exit 3, no traceback and
    nothing in app.log. Both rounds exit 0 once the cache belongs to the
    card.

    Two rounds and not one, because one card only proves the exit path.
    """
    _run_window_script('''
import gc, threading, time
from pathlib import Path
from PIL import Image
import config
import visual_qa as vq

gc.disable()                 # only explicit collects: we choose the thread

cfg = config.load(Path("config.toml"))
ctrl = vq.Controller(lambda: cfg, recording_now=lambda: True)
img = Image.new("RGB", (320, 160), (30, 30, 30))
ctrl._grab_selection = lambda: (img, (100, 100, 420, 260))
ctrl._ask = lambda *a, **k: ("ארבעים ושתיים", "test")

for round_no in (1, 2):
    assert ctrl.begin_selection(), f"round {round_no}: already busy"
    deadline = time.monotonic() + 30
    while not ctrl.sink_active and time.monotonic() < deadline:
        time.sleep(0.02)
    assert ctrl.sink_active, f"round {round_no}: the card never came up"

    # The step the sibling test never takes: the owner holds the dictation
    # key while the card is open. notify_recording starts the wave (main.py
    # hands it the recorder's meter from inside the keyboard hook), and the
    # transcript is delivered ON THE TRANSCRIPTION WORKER, as main.py does.
    ctrl.notify_recording(level=lambda: (0.3, True))
    time.sleep(0.6)                       # let the wave paint some rings
    done = threading.Event()
    threading.Thread(
        target=lambda: (ctrl.deliver_transcript("מה כתוב פה"), done.set()),
        name="transcribe-worker").start()
    done.wait(10)
    time.sleep(1.2)                       # auto_send asks, the answer lands

    ctrl.stop()
    while ctrl.busy and time.monotonic() < deadline:
        time.sleep(0.02)
    assert not ctrl.busy, f"round {round_no}: the flow never finished"
    freed = gc.collect()
    assert freed == 0, f"round {round_no} left {freed} for another thread"
    ctrl._cancel.clear()

# The assertion that would have caught it directly: nothing module-level
# in the skin may hold a Tk object, because module-level outlives every
# thread that could legally free one.
import skin.wave as wave_mod
held = [name for name, value in vars(wave_mod).items()
        if type(value).__module__ == "_tkinter"
        or type(value).__name__ in ("PhotoImage", "Tk", "Canvas")]
assert not held, f"skin.wave still holds Tk objects: {held}"
for name, value in vars(wave_mod).items():
    if isinstance(value, dict) and value:
        kinds = {type(v).__name__ for v in value.values()}
        assert not (kinds & {"PhotoImage", "tkapp"}), (name, kinds)
''')


def test_the_hotkey_asks_the_card_instead_of_ending_a_locked_dictation(
) -> None:
    """The bug the owner kept hitting, and the shape of the fix.

    LATCHED, the dictation hotkey means STOP. That is exactly wrong once
    the ask card is up, because the card tells you to hold that same key
    to speak a question — so reaching for it ended the paragraph he was in
    the middle of dictating instead of asking anything.

    With the card up it means ASK: down starts a question, up ends it, and
    the locked recording underneath is never touched. The latch key is
    deliberately NOT included; it is the one key that has to keep meaning
    "done" whatever is on screen.
    """
    VK_LEFT = 0x25

    def build(card_open):
        seen: list[str] = []
        machine = PTTStateMachine(
            VK_RCTRL,
            on_start=lambda lang: seen.append("start"),
            on_stop=lambda lang: seen.append("stop"),
            on_abort=lambda why: seen.append(f"abort:{why}"),
            latch_vk=VK_LEFT, on_latch=lambda: seen.append("latch"),
            ask_open=lambda: card_open[0],
            on_ask_start=lambda lang: seen.append("ask-start"),
            on_ask_stop=lambda lang: seen.append("ask-stop"))
        return machine, seen

    def latch(machine):
        machine.handle("down", VK_RCTRL, False)
        machine.handle("down", VK_LEFT, False)      # tap: lock it on
        machine.handle("up", VK_LEFT, False)
        machine.handle("up", VK_RCTRL, False)       # the hand comes off
        assert machine.state == hotkey_mod.LATCHED, machine.state

    # No card: the hotkey is the stop key, exactly as it always was.
    card = [False]
    machine, seen = build(card)
    latch(machine)
    machine.handle("down", VK_RCTRL, False)
    assert machine.state == hotkey_mod.IDLE, machine.state
    assert seen == ["start", "latch", "stop"], seen

    # Card up: two questions, and the lock survives both.
    card = [True]
    machine, seen = build(card)
    latch(machine)
    machine.handle("down", VK_RCTRL, False)
    assert machine.state == hotkey_mod.LATCHED, "the dictation was ended"
    machine.handle("up", VK_RCTRL, False)
    machine.handle("down", VK_RCTRL, False)
    machine.handle("up", VK_RCTRL, False)
    assert machine.state == hotkey_mod.LATCHED, machine.state
    machine.handle("down", VK_LEFT, False)       # the latch still finishes
    machine.handle("up", VK_LEFT, False)
    assert machine.state == hotkey_mod.IDLE, machine.state
    assert seen == ["start", "latch", "ask-start", "ask-stop",
                    "ask-start", "ask-stop", "stop"], seen

    # Closed while the key is still held: the UP must still land, or the
    # machine would sit inside a question forever.
    card = [True]
    machine, seen = build(card)
    latch(machine)
    machine.handle("down", VK_RCTRL, False)
    card[0] = False
    machine.handle("up", VK_RCTRL, False)
    assert machine.state == hotkey_mod.LATCHED, machine.state
    assert seen == ["start", "latch", "ask-start", "ask-stop"], seen
    machine.handle("down", VK_RCTRL, False)      # and stop means stop again
    assert machine.state == hotkey_mod.IDLE, machine.state

    # Windows repeats key-down while a key is held; one hold is one
    # question, not six.
    card = [True]
    machine, seen = build(card)
    latch(machine)
    for _ in range(6):
        machine.handle("down", VK_RCTRL, False)
    assert seen.count("ask-start") == 1, seen
    machine.handle("up", VK_RCTRL, False)
    assert machine.state == hotkey_mod.LATCHED, machine.state

    # Esc still throws a locked recording away when nothing claims it.
    card = [False]
    machine, seen = build(card)
    latch(machine)
    machine.handle("down", 0x1B, False)
    assert machine.state == hotkey_mod.IDLE, machine.state
    assert "abort:esc pressed while locked" in seen, seen


def test_the_app_actually_hands_the_machine_the_ask_callbacks() -> None:
    """Every link in this feature is tested on its own, and all of them
    are useless if App.__init__ never wires them up. This is the joint."""
    import inspect

    import main as main_mod

    built = inspect.getsource(main_mod.App.__init__)
    for wire in ("ask_open=self._ask_card_open",
                 "on_ask_start=self._on_ask_start",
                 "on_ask_stop=self._on_ask_stop"):
        assert wire in built, wire

    # the slice is taken and never an end(), or the dictation would stop
    stop = inspect.getsource(main_mod.App._on_ask_stop)
    assert "slice_since" in stop, stop
    assert "recorder.end()" not in stop, stop
    assert "exclude_since" in stop, stop
    start = inspect.getsource(main_mod.App._on_ask_start)
    assert "recorder.mark()" in start, start
    assert "begin()" not in start, start


def test_a_question_is_a_slice_and_the_recording_never_notices() -> None:
    """What makes one continuous paste possible.

    The question spoken into the card is READ out of the recording that is
    still running, not cut out of it: slice_since copies and mutates
    nothing. So the same speech is both the question the card answers and
    part of the sentence still being dictated — and when the latch is
    finally tapped, everything lands at once, with the words said to the
    card sitting where they were said.
    """
    import recorder as recorder_mod

    rec = recorder_mod.Recorder.__new__(recorder_mod.Recorder)
    rec._lock = threading.Lock()
    rec._state = recorder_mod.ACTIVE
    rec.sample_rate = 16000
    rec._chunks = [np.zeros(1600, dtype=np.int16) for _ in range(5)]
    rec._samples = 8000

    before = rec.mark()
    assert before == 5, before
    rec._chunks += [np.ones(1600, dtype=np.int16) for _ in range(3)]

    wav, seconds = rec.slice_since(before)
    assert wav is not None
    assert abs(seconds - 0.3) < 0.01, seconds
    # THE POINT: nothing was consumed.
    assert len(rec._chunks) == 8, len(rec._chunks)
    assert rec._state == recorder_mod.ACTIVE, rec._state
    whole, whole_s = rec.slice_since(0)
    assert abs(whole_s - 0.8) < 0.01, whole_s
    assert len(whole) > len(wav), (len(whole), len(wav))

    # A mark taken when nothing is recording is not a licence to slice.
    rec._state = recorder_mod.IDLE
    assert rec.mark() == 0
    assert rec.slice_since(0) == (None, 0.0)


def test_the_switch_cuts_the_question_out_of_the_dictation_itself(
) -> None:
    """What the card switch has to mean once the question is INSIDE the
    recording.

    There is one microphone and no second channel, so a question spoken
    while a dictation is locked is part of that dictation whether anybody
    likes it or not. "Keep this out of what I am writing" therefore cannot
    mean "do not record it" — it means the finished utterance is assembled
    without those frames. What is on either side still joins seamlessly,
    because whole chunks are dropped.
    """
    import io
    import wave as wave_mod

    import recorder as recorder_mod

    rec = recorder_mod.Recorder.__new__(recorder_mod.Recorder)
    rec._lock = threading.Lock()
    rec._state = recorder_mod.ACTIVE
    rec.sample_rate = 16000
    rec._chunks, rec._excluded, rec._samples = [], [], 0
    rec._questions = []
    # begin() restores the runaway cap, so a hand-built recorder needs the
    # two fields that carry it.
    rec._default_max_samples = rec._max_samples = float('inf')

    def say(value: int, chunks: int) -> None:
        rec._chunks += [np.full(1600, value, dtype=np.int16)
                        for _ in range(chunks)]
        rec._samples += 1600 * chunks

    say(1, 5)                       # what he said before opening the card
    question = rec.mark()
    say(2, 3)                       # what he said to the card
    rec.exclude_since(question)     # ...with the switch turned off
    say(3, 4)                       # and what he said after closing it

    wav, seconds = rec.end()
    assert wav is not None
    assert abs(seconds - 0.9) < 0.01, seconds       # 9 chunks, not 12
    with wave_mod.open(io.BytesIO(wav)) as w:
        pcm = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
    kept = sorted(set(pcm.tolist()))
    assert kept == [1, 3], kept      # the middle is gone, the ends abut

    # With the switch left alone, nothing is dropped: the question is part
    # of the sentence, which is the whole point of the feature.
    rec._state = recorder_mod.ACTIVE
    rec._chunks, rec._excluded, rec._samples = [], [], 0
    rec._questions = []
    say(1, 5)
    say(2, 3)
    say(3, 4)
    wav, seconds = rec.end()
    assert abs(seconds - 1.2) < 0.01, seconds
    with wave_mod.open(io.BytesIO(wav)) as w:
        pcm = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
    assert sorted(set(pcm.tolist())) == [1, 2, 3]

    # begin() and abort() both wipe the exclusions, or the next dictation
    # would be missing a hole punched in the last one.
    rec._excluded = [(0, 1)]
    rec.begin()
    assert rec._excluded == []
    rec._excluded = [(0, 1)]
    rec.abort()
    assert rec._excluded == []


def test_a_question_in_the_middle_is_spliced_not_transcribed_again(
) -> None:
    """The last thing that was still losing words.

    A question asked mid-dictation is a short utterance stranded between
    two long silences — you stop talking, drag a rectangle, say one thing,
    read the answer, carry on — and Whisper drops exactly that shape.
    Measured 2026-08-31 on a real 35 s recording: the owner said "four" to
    the card, and it was in the audio, and correct in the transcript of
    its own slice, and simply absent from the transcript of the whole
    file. vad_filter=False put it back and made everything else worse.

    So the recording is cut at the question and only the stretches around
    it go to Whisper. The question keeps the text it was given the moment
    it was spoken, which is the one transcript of it that can be trusted.
    """
    import main as main_mod

    class Interrupted:
        _question_texts = ["ארבע."]

        def _transcribe(self, wav, language=None):
            return {b"before": "אחת שתיים שלוש", b"after": "חמש"}[wav], "local"

    who = Interrupted()
    text, backend = main_mod.App._transcribe_pieces(
        who, [(False, b"before"), (True, b"asked"), (False, b"after")], None)
    assert text == "אחת שתיים שלוש ארבע. חמש", text
    assert backend == "local", backend
    assert who._question_texts == [], who._question_texts   # consumed

    # Two questions, in order, and the stretches between them.
    class Twice:
        _question_texts = ["ארבע.", "שש."]

        def _transcribe(self, wav, language=None):
            return {b"a": "אחת", b"b": "חמש", b"c": "שבע"}[wav], "local"

    text, _ = main_mod.App._transcribe_pieces(
        Twice(), [(False, b"a"), (True, b"q1"), (False, b"b"),
                  (True, b"q2"), (False, b"c")], None)
    assert text == "אחת ארבע. חמש שש. שבע", text

    # If the remembered text never arrived — nothing was heard, or the
    # card closed before it landed — the audio is transcribed like any
    # other piece. Losing speech is worse than transcribing it twice.
    class Forgot:
        _question_texts = []

        def _transcribe(self, wav, language=None):
            return {b"a": "אחת", b"q": "ארבע", b"b": "חמש"}[wav], "local"

    text, _ = main_mod.App._transcribe_pieces(
        Forgot(), [(False, b"a"), (True, b"q"), (False, b"b")], None)
    assert text == "אחת ארבע חמש", text


def test_the_recording_comes_back_cut_where_the_card_interrupted_it(
) -> None:
    """end_pieces is what makes the splice possible: one wav for the
    spool, and the same audio cut at the questions for the transcript. A
    recording nobody asked anything during is a single piece, so the
    ordinary dictation path is untouched."""
    import recorder as recorder_mod

    def fresh():
        rec = recorder_mod.Recorder.__new__(recorder_mod.Recorder)
        rec._lock = threading.Lock()
        rec._state = recorder_mod.ACTIVE
        rec.sample_rate = 16000
        rec._chunks, rec._excluded, rec._questions, rec._samples = [], [], [], 0
        return rec

    def say(rec, value, chunks):
        rec._chunks += [np.full(1600, value, dtype=np.int16)
                        for _ in range(chunks)]
        rec._samples += 1600 * chunks

    # kept: three pieces, and the whole file still holds all of it
    rec = fresh()
    say(rec, 1, 5)
    at = rec.mark()
    say(rec, 2, 3)
    rec.note_question(at)
    say(rec, 3, 4)
    whole, pieces, seconds = rec.end_pieces()
    assert [q for q, _ in pieces] == [False, True, False], pieces
    assert abs(seconds - 1.2) < 0.01, seconds
    assert whole is not None and len(whole) > max(len(w) for _q, w in pieces)

    # excused: cut out entirely, and what is left is one piece again
    rec = fresh()
    say(rec, 1, 5)
    at = rec.mark()
    say(rec, 2, 3)
    rec.exclude_since(at)
    say(rec, 3, 4)
    _whole, pieces, seconds = rec.end_pieces()
    assert [q for q, _ in pieces] == [False], pieces
    assert abs(seconds - 0.9) < 0.01, seconds

    # nothing asked: exactly what it always was
    rec = fresh()
    say(rec, 1, 5)
    _whole, pieces, seconds = rec.end_pieces()
    assert [q for q, _ in pieces] == [False], pieces
    assert abs(seconds - 0.5) < 0.01, seconds


def test_a_sliced_question_is_never_echoed_twice_into_the_field() -> None:
    """The trap in having both mechanisms.

    A question asked from inside a LOCKED dictation is already in that
    recording — it will be pasted, in place, when the latch is tapped.
    Echoing it as well would put the same sentence in the field twice, and
    the second copy in the wrong place. So `sliced` turns the echo off,
    and only the echo: the card is still handed the question.
    """
    import shutil
    import tempfile

    import main as main_mod

    tmp = Path(tempfile.mkdtemp(prefix="dictation-sliced-"))
    fake = _FakeInjector()
    real = main_mod.injector
    try:
        main_mod.injector = fake
        app = _worker_app(_Flaky(fail_times=0), tmp)
        card = _FakeSink(sink_active=True, echoing=True)
        app._vqa = card

        # An ordinary question, with no dictation underneath it: kept,
        # because nothing else is ever going to deliver it.
        app._handle(b"RIFF-audio", 4.0, 0, None, True)
        assert card.delivered == ["שלום"], card.delivered
        assert app._echo_lines == ["שלום"], app._echo_lines

        # The same question, sliced out of a recording that is still
        # running: delivered to the card, and NOT kept.
        app._echo_lines = []
        app._handle(b"RIFF-audio", 4.0, 0, None, True, sliced=True)
        assert card.delivered == ["שלום", "שלום"], card.delivered
        assert app._echo_lines == [], app._echo_lines
        assert fake.calls == [], fake.calls      # and nothing was pasted
    finally:
        main_mod.injector = real
        shutil.rmtree(tmp, ignore_errors=True)


def test_the_dot_never_says_idle_while_a_locked_recording_runs() -> None:
    """A question asked from inside the card is transcribed while the
    dictation underneath keeps going. The worker puts the dot back when it
    finishes, and putting back the plain blue "running" dot there would
    announce a stop that did not happen — which is the one thing the owner
    reads that dot to know."""
    import main as main_mod

    assert main_mod._DOT_FOR[hotkey_mod.LATCHED] == "locked"
    assert main_mod._DOT_FOR[hotkey_mod.RECORDING] == "recording"
    assert main_mod._DOT_FOR.get(hotkey_mod.IDLE, "ready") == "ready"
    # and every name it can produce is one the dot actually knows
    for state in set(main_mod._DOT_FOR.values()) | {"ready"}:
        assert state in overlay_mod.STATES, state


def test_the_card_has_a_switch_for_where_a_question_also_goes() -> None:
    """The card is opened in the middle of writing to somebody, so what is
    asked of it also lands in what is being written. Not always: some
    questions about the screen have no business in the letter. The switch
    in the title strip is that exception, and it has to be a switch rather
    than a setting because you find out which kind of question it is
    while you are already looking at the card.

    It draws the FIELD, struck through, and not a muted microphone: the
    microphone is live either way — you are still talking to the card —
    and what is being turned off is the second destination.
    """
    _run_window_script('''
import os
from PIL import Image
import visual_qa as vq

img = Image.new("RGB", (320, 160), (30, 30, 30))
win = vq.AskWindow(img, (100, 100, 600, 400), vq.Speaker(), "off",
                   lambda *a, **k: ("", "test"), echo=True)
try:
    win.root.update()
    assert win.echo_on is True

    box = win.surface.boxes.get("echo")
    assert box is not None, sorted(win.surface.boxes)
    assert box != win.surface.boxes["close"], box     # not the X renamed
    # _hit works in WINDOW coordinates and the boxes are card-local, so
    # the card's own offset goes back on before asking (visual_qa:2980).
    x = (box[0] + box[2]) // 2 + win._cx
    y = (box[1] + box[3]) // 2 + win._cy
    assert win._hit(x, y) == "echo", win._hit(x, y)

    win._toggle_echo()
    win.root.update()
    assert win.echo_on is False
    # The rectangle keeps its name when the glyph changes. It draws
    # "echo_off" now, and if the hit key followed the glyph the second
    # click would land on nothing and the switch would be one-way.
    assert win.surface.boxes.get("echo") == box, win.surface.boxes
    assert win._hit(x, y) == "echo", win._hit(x, y)

    win._toggle_echo()
    win.root.update()
    assert win.echo_on is True

    # and both glyphs are real drawings, not one silently reused
    on = vq._icon("echo", 18).tobytes()
    off = vq._icon("echo_off", 18).tobytes()
    assert on != off
finally:
    win.root.destroy()
os._exit(0)
''')


def test_the_switch_is_asked_of_the_card_not_of_the_config() -> None:
    """Where a question ALSO goes is the card's live state, not what
    config.toml said when the app started — config only chooses which way
    the switch starts. And main.py asks at the moment the question lands,
    so turning the switch off does not un-send what was already asked."""
    import inspect
    import visual_qa as vq_mod

    ctrl = vq_mod.Controller(lambda: None)
    assert ctrl.echoing is False, "no card means nothing to echo into"

    class OnlyTheFlag:
        echo_on = True

    ctrl._window = OnlyTheFlag()
    try:
        assert ctrl.echoing is True
        ctrl._window.echo_on = False
        assert ctrl.echoing is False
    finally:
        ctrl._window = None

    # config chooses the starting position, and nothing else
    opened = inspect.getsource(vq_mod.Controller._open_ask)
    assert 'echo=getattr(vq, "echo_to_field", True)' in opened, opened

    # and the reading is done where the question lands, not at the close
    import main as main_mod
    handled = inspect.getsource(main_mod.App._handle)
    assert "self.vqa.echoing" in handled, "main.py never asks the switch"
    closed = inspect.getsource(main_mod.App._on_card_closed)
    assert "echoing" not in closed, closed


def test_a_question_asked_mid_sentence_rejoins_the_field_it_interrupted(
) -> None:
    """[visual_qa] echo_to_field.

    The card is opened in the MIDDLE of writing to somebody more often
    than not, and until now what you asked it went to the card and
    nowhere else — afterwards findable only in transcripts.log, which is
    not where you were typing.

    It cannot be handed over while the card is up: the card owns the
    foreground, so that paste would land in the card itself or tear focus
    off it mid-question. So it is KEPT and given back at the close, and
    only to the window the dictation was actually aimed at — never fired
    at whatever happens to be in front by then.
    """
    import main as main_mod

    class Interrupted:
        _echo_lock = threading.Lock()
        _cursor_lock = threading.Lock()

    who = Interrupted()
    who.cfg = config_mod.load(Path(__file__).resolve().parent / "config.toml")
    who._echo_lines = ["מה כתוב פה", "ומה זה אומר"]
    who._field_hwnd = 4321

    pasted: list[str] = []
    copied: list[str] = []
    saved = (injector.foreground_window, injector.inject, injector.set_text,
             main_mod.beep)
    try:
        injector.foreground_window = lambda: 4321
        injector.inject = lambda text, chord, delay: pasted.append(text)
        injector.set_text = copied.append
        main_mod.beep = lambda _kind: None

        main_mod.App._on_card_closed(who)
        # ONE paste, both sentences: consecutive questions are consecutive
        # sentences as far as the field is concerned.
        assert pasted == ["מה כתוב פה ומה זה אומר"], pasted
        assert copied == [], copied

        # and the notes are torn up, so a second close hands over nothing
        main_mod.App._on_card_closed(who)
        assert len(pasted) == 1, pasted

        # Focus somewhere the owner chose: the clipboard, said out loud,
        # rather than a paste into a window nobody dictated at. Same
        # answer every other homeless transcript in main.py gets.
        who._echo_lines = ["שאלה"]
        injector.foreground_window = lambda: 9999
        main_mod.App._on_card_closed(who)
        assert len(pasted) == 1, pasted
        assert copied == ["שאלה"], copied
    finally:
        (injector.foreground_window, injector.inject, injector.set_text,
         main_mod.beep) = saved


def test_the_echo_is_off_the_card_and_never_holds_it() -> None:
    """on_closed takes NO argument and fires after the flow has buried the
    card — both deliberate. A listener handed the window could keep it,
    and a reference that outlives that collect is the Tcl_AsyncDelete
    abort in AGENTS.md, which skin\wave.py already re-armed once."""
    import inspect
    import visual_qa as vq_mod

    src = inspect.getsource(vq_mod.Controller._closed)
    assert "self._on_closed()" in src, src        # called with nothing
    assert "_cancel.is_set()" in src, src         # silent during shutdown

    for name in ("_flow", "_flow_given"):
        body = inspect.getsource(getattr(vq_mod.Controller, name))
        collect = body.index("gc.collect()")
        clear = body.index("self._busy.clear()")
        told = body.index("self._closed()")
        assert collect < clear < told, (name, collect, clear, told)


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


# ------------------------------------------------------- capture the screen
#
# This feature WRITES pictures of the screen to disk, which nothing else in
# this app does, so the tests below lean on the two things that follow from
# that. The picture on the clipboard and the picture in the file must be the
# same picture (they come from one function, and a test says so). And the
# module must not be able to grow a network call by accident: there is no
# upload path in capture.py and the only route to a model is the ask card's
# own Controller, which owns the upload gate.
#
# The rest is arithmetic — rectangles, filenames, clocks — and it is
# arithmetic on purpose: everything that can be a pure function is one, so
# most of what the feature does is testable with no screen, no encoder and
# no microphone.

def test_a_recording_rectangle_is_always_even_sided() -> None:
    """yuv420p subsamples chroma 2x2, so libx264 refuses an odd side — and
    it refuses at add_stream() time, which is AFTER the user has picked a
    region and thinks they are recording. One pixel off the right and the
    bottom is invisible and cannot fail."""
    import capture as cap

    assert cap.even_box((0, 0, 101, 51)) == (0, 0, 100, 50)
    assert cap.even_box((0, 0, 100, 50)) == (0, 0, 100, 50)
    assert cap.even_box((10, 20, 111, 61)) == (10, 20, 110, 60)
    # A backwards drag is a legal drag, and it means the same rectangle.
    assert cap.even_box((111, 61, 10, 20)) == (10, 20, 110, 60)
    for box in ((0, 0, 999, 777), (-1920, 0, 5, 3), (7, 7, 8, 8)):
        left, top, right, bottom = cap.even_box(box)
        assert (right - left) % 2 == 0 and (bottom - top) % 2 == 0, box


def test_a_rectangle_is_clamped_into_the_screen_it_was_dragged_on() -> None:
    """A drag that ran off the edge of the desktop is legal; a BitBlt that
    starts outside the screen is undefined and PIL's crop pads it black."""
    import capture as cap

    bounds = (-1920, 0, 2560, 1440)
    assert cap.clamp_box((-3000, -50, 100, 200), bounds) == (-1920, 0, 100, 200)
    assert cap.clamp_box((2400, 1300, 3000, 1600), bounds) == \
        (2400, 1300, 2560, 1440)
    inside = (0, 0, 500, 400)
    assert cap.clamp_box(inside, bounds) == inside
    # Entirely outside collapses rather than inverting: right >= left always.
    left, top, right, bottom = cap.clamp_box((5000, 5000, 6000, 6000), bounds)
    assert right >= left and bottom >= top, (left, top, right, bottom)


def test_two_captures_in_one_second_do_not_overwrite_each_other() -> None:
    """The name is the clock to the second and the key repeats faster than
    that. Silently replacing the first shot is the worst available answer."""
    import capture as cap

    first = cap.capture_name("shot", 0, taken=set())
    assert first.startswith("shot ") and first.endswith(".png"), first
    second = cap.capture_name("shot", 0, taken={first})
    assert second.endswith(" (2).png"), second
    third = cap.capture_name("shot", 0, taken={first, second})
    assert third.endswith(" (3).png"), third
    assert cap.capture_name("clip", 0).endswith(".mp4")
    # Sorting the folder by name has to be sorting it by time, so no
    # component may be written in a way that sorts wrong.
    assert cap.stamp(0)[:4].isdigit(), cap.stamp(0)
    assert ":" not in cap.capture_name("shot", 0), "illegal in a filename"


def test_the_clock_on_the_recording_bar_reads_like_a_clock() -> None:
    """Hours only appear once there are any: a recorder that says 0:00:07
    is a recorder that expects to run for hours, and this one mostly does
    not."""
    import capture as cap

    assert cap.elapsed_readout(0) == "0:00"
    assert cap.elapsed_readout(7) == "0:07"
    assert cap.elapsed_readout(71) == "1:11"
    assert cap.elapsed_readout(271) == "4:31"
    assert cap.elapsed_readout(3729) == "1:02:09"
    assert cap.elapsed_readout(-5) == "0:00", "never a negative clock"
    assert cap.size_readout(900) == "900 B"
    assert cap.size_readout(83000) == "81 KB"
    assert cap.size_readout(3_300_000) == "3.1 MB"


def test_a_recording_stops_itself_at_the_cap_and_never_without_one() -> None:
    """A backstop, not a budget: a key tapped by accident must not fill the
    disk overnight, and 0 has to mean 'no cap' rather than 'stop now'."""
    import capture as cap

    assert cap.should_stop(100.0, 100.0 + 1800, 1800) is True
    assert cap.should_stop(100.0, 100.0 + 1799, 1800) is False
    assert cap.should_stop(100.0, 1e9, 0) is False, "0 means no cap"


def test_the_toolbar_is_drawn_where_it_can_be_clicked() -> None:
    """One dict of rectangles feeds both the painter and the hit test. The
    bug this shape exists to prevent is a button drawn a few pixels from
    where it can be pressed: invisible in a screenshot, maddening under
    the hand."""
    import capture as cap

    layout = cap.bar_layout()
    spots = layout["spots"]
    width, height = layout["size"]
    for name, _glyph, _label in cap.TOOLS:
        assert name in spots, name
    for name, _glyph, _label in cap.ACTIONS:
        assert name in spots, name
    for name in ("ink", "undo", "close"):
        assert name in spots, name
    for name, (x0, y0, x1, y1) in spots.items():
        assert 0 <= x0 < x1 <= width, (name, x0, x1, width)
        assert 0 <= y0 < y1 <= height, (name, y0, y1, height)
        if name.startswith("_"):
            continue
        cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
        assert cap.hit(spots, cx, cy) == name, (name, cx, cy)
    assert cap.hit(spots, width - 1, height - 4) is None, "the gap is not a button"
    # Nothing overlaps: two controls sharing a pixel is a press that lands
    # on whichever happened to be enumerated first.
    real = [(n, r) for n, r in spots.items() if not n.startswith("_")]
    for i, (an, a) in enumerate(real):
        for bn, b in real[i + 1:]:
            apart = a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1]
            assert apart, f"{an} overlaps {bn}: {a} {b}"


def test_the_toolbar_goes_under_the_selection_or_over_it_never_off_screen(
) -> None:
    """Under it if it fits, over it if not, inside it as the last resort —
    a 1440-tall selection has no outside. And always inside the MONITOR:
    a bar that hangs off the edge loses buttons."""
    import capture as cap

    screen = (0, 0, 2560, 1440)
    bar = (600, 82)
    below = cap.plan_bar((800, 300, 1400, 700), bar, screen)
    assert below[1] > 700, below
    above = cap.plan_bar((800, 900, 1400, 1400), bar, screen)
    assert above[1] + 82 < 900, above
    squeezed = cap.plan_bar((0, 0, 2560, 1440), bar, screen)
    assert 0 <= squeezed[0] and squeezed[1] + 82 <= 1440, squeezed
    for anchor in ((0, 0, 60, 60), (2500, 1380, 2560, 1440),
                   (1200, 700, 1260, 760)):
        x, y = cap.plan_bar(anchor, bar, screen)
        assert screen[0] <= x and x + bar[0] <= screen[2], (anchor, x)
        assert screen[1] <= y and y + bar[1] <= screen[3], (anchor, y)


def test_undo_puts_back_the_crop_as_well_as_the_ink() -> None:
    """History holds whole STATES rather than inverse operations, because a
    crop is not a mark: an un-crop that did not also restore the marks the
    crop cut off would be a different picture from the one that was
    there."""
    import capture as cap

    empty, history = cap.undo_step([])
    assert empty is None and history == [], "nothing to undo is not a crash"
    first = ((0, 0, 100, 100), None, [])
    second = ((0, 0, 100, 100), None, [{"kind": "pen"}])
    state, rest = cap.undo_step([first, second])
    assert state == second and rest == [first], (state, rest)
    state, rest = cap.undo_step(rest)
    assert state == first and rest == [], (state, rest)


def test_the_quality_names_map_to_the_numbers_they_promise() -> None:
    """Screen content is flat colour and sharp edges, which h264 likes, so
    these are several steps softer than the same names mean for camera
    video. Measured: a 4 s 960x540 clip of a mostly-static screen came out
    31 KB at balanced."""
    import capture as cap

    assert cap.crf_for("small") > cap.crf_for("balanced") > cap.crf_for("sharp")
    for name in ("small", "balanced", "sharp"):
        assert 0 < cap.crf_for(name) < 52, name


# ---- the picture itself: pixels in, pixels out ----

def test_the_capture_pipeline_never_takes_a_file_path() -> None:
    """The same rule visual_qa's screenshot pipeline keeps, for a module
    that DOES write files: everything that touches pixels is bytes in,
    bytes out, and exactly two functions know what a folder is. A helper
    that grew a path argument would be a helper that could log one."""
    import inspect

    import capture as cap

    pure = (cap.draw_marks, cap.cut_to_shape, cap.render_shot, cap.pixelate,
            cap.even_box, cap.clamp_box, cap.plan_bar, cap.bar_layout,
            cap.copy_image, cap._image_formats)
    for fn in pure:
        names = list(inspect.signature(fn).parameters)
        for name in names:
            assert not any(word in name for word in ("path", "file", "dir",
                                                     "folder")), \
                f"{fn.__name__} takes {name!r} — the pixel half writes nothing"


def test_capture_never_touches_the_shared_ctypes_library_objects() -> None:
    """ctypes.windll.user32 is PROCESS-GLOBAL and every module here reaches
    for the same one. Declaring .restype on a function taken from it
    changes that function for everybody: the first version of capture.py
    declared GetDC.restype = c_void_p (correct, and needed there) and the
    next call into visual_qa.text_pil died with "int too long to convert"
    on a line that had worked for months. capture.py owns private
    ctypes.WinDLL handles instead, and this greps to keep it that way."""
    import ctypes

    source = (Path(__file__).resolve().parent / "capture.py").read_text("utf-8")
    offenders = [line.strip() for line in source.splitlines()
                 if "ctypes.windll" in line and not line.strip().startswith("#")]
    assert not offenders, offenders
    import capture  # noqa: F401  — importing it must not change the globals
    assert ctypes.windll.user32.GetDC.restype is ctypes.c_int, \
        "importing capture.py redeclared a shared ctypes function"


def test_the_marks_are_replayed_into_the_picture_not_read_off_the_screen(
) -> None:
    """Every mark lives as POINTS and is drawn into the pristine crop. The
    alternative — grabbing the screen back to read our own ink — races the
    topmost window and returns black, which visual_qa.py records paying
    for."""
    from PIL import Image, ImageStat

    import capture as cap

    base = Image.new("RGB", (400, 300), (30, 34, 44))
    box = (0, 0, 400, 300)
    plain = cap.render_shot(base, box, [], None)
    assert plain.size == (400, 300), plain.size

    red = cap.INKS[0][1]
    for kind, points, solid in (
            ("pen", [(20, 20), (80, 90), (150, 40)], True),
            ("arrow", [(30, 250), (300, 120)], True),
            ("box", [(60, 60), (260, 200)], True),
            ("highlight", [(40, 150), (350, 150)], False)):
        inked = cap.render_shot(base, box, [{"kind": kind, "points": points,
                                             "colour": red}], None)
        assert inked.size == plain.size, kind
        assert inked.convert("RGB").tobytes() != plain.convert("RGB").tobytes(), \
            f"{kind} drew nothing"
        pixels = list(inked.convert("RGB").getdata())
        if solid:
            # ...and it drew in the colour it was asked for, not chrome blue.
            assert [p for p in pixels
                    if p[0] > 150 and p[1] < 110 and p[2] < 110], \
                f"{kind} did not draw in the ink colour"
        else:
            # A highlighter is TRANSLUCENT on purpose — you have to be able
            # to read what is under it — so what is asserted is that the ink
            # moved the pixels towards itself, not that it replaced them.
            # Measured: red (224,53,43) at alpha 92 over this base lifts the
            # red channel from 30 to 100.
            assert [p for p in pixels if p[0] > 55], \
                "the highlighter tinted nothing"
            assert max(p[0] for p in pixels) < 200, \
                "a highlighter that opaque would hide the text under it"

    # A mark outside the crop is clipped, not an error and not a shift.
    off = cap.render_shot(base, (0, 0, 100, 100),
                          [{"kind": "box", "points": [(300, 300), (380, 380)],
                            "colour": red}], None)
    assert off.size == (100, 100)


def test_blurring_something_out_really_destroys_it() -> None:
    """This is the tool people reach for when the thing under it is an
    address or a token, so a Gaussian at any radius a person will accept is
    the wrong answer — it can be sharpened back. A mosaic cannot. 12 px
    blocks were picked by reading the result: at 8 px a 12 pt password was
    still guessable."""
    from PIL import Image, ImageDraw, ImageStat

    import capture as cap

    base = Image.new("RGB", (300, 120), (240, 240, 245))
    d = ImageDraw.Draw(base)
    for x in range(10, 280, 14):
        d.rectangle((x, 40, x + 7, 80), fill=(20, 20, 25))
    before = ImageStat.Stat(base.convert("L")).stddev[0]
    after = ImageStat.Stat(cap.pixelate(base, (0, 0, 300, 120))
                           .convert("L")).stddev[0]
    assert after < before * 0.75, (before, after)
    assert cap.PIXEL_BLOCK >= 10, "measured: below ~8 px the text comes back"
    # Untouched outside the rectangle.
    part = cap.pixelate(base, (0, 0, 100, 120))
    assert part.crop((150, 0, 300, 120)).tobytes() == \
        base.crop((150, 0, 300, 120)).tobytes()
    # A degenerate rectangle is a no-op, not a crash.
    assert cap.pixelate(base, (50, 50, 50, 50)).size == base.size


def test_a_lassoed_shot_is_transparent_outside_the_shape() -> None:
    """Deliberately different from visual_qa, which fills the outside
    BLACK: there the crop goes to a model that would happily describe a
    dimmed neighbour. Here it goes into a document, and transparency is
    what lets it land on whatever colour that document already is."""
    from PIL import Image

    import capture as cap

    base = Image.new("RGB", (200, 200), (200, 60, 60))
    path = [(50, 50), (150, 50), (150, 150), (50, 150)]
    out = cap.render_shot(base, (0, 0, 200, 200), [], path)
    assert out.mode == "RGBA", out.mode
    alpha = out.getchannel("A")
    assert alpha.getpixel((5, 5)) == 0, "outside the lasso must be see-through"
    assert alpha.getpixel((100, 100)) == 255, "inside must be untouched"
    # And the clipboard's bitmap copy flattens it onto WHITE, because
    # CF_DIB has no alpha and a document is where a cut-out gets pasted.
    dib, png = cap._image_formats(out)
    assert dib[:4] and len(png) > 8 and png[1:4] == b"PNG", png[:8]
    assert len(dib) > 0


def test_the_clipboard_and_the_file_get_the_same_picture() -> None:
    """One render function feeds the screen, the clipboard and the file, so
    what you saw is what was written. A second code path for 'the saved
    version' is how the ink ends up in one of them and not the others."""
    import inspect

    from PIL import Image

    import capture as cap

    source = inspect.getsource(cap.ShotWindow)
    assert source.count("def picture(") == 1
    for caller in ("_first_save", "_save_again", "_ask"):
        body = source.split(f"def {caller}(")[1].split("\n    def ")[0]
        assert "self.picture()" in body, \
            f"{caller} builds its own picture instead of calling picture()"

    base = Image.new("RGB", (120, 90), (10, 120, 200))
    once = cap.render_shot(base, (0, 0, 120, 90), [], None)
    twice = cap.render_shot(base, (0, 0, 120, 90), [], None)
    assert once.tobytes() == twice.tobytes(), "the render is not deterministic"


def test_a_shot_is_saved_where_the_config_says_and_reloads(tmp=None) -> None:
    """The folder is made if it is missing, a relative name is relative to
    the APP (this app is launched from a .vbs, a shortcut and a scheduled
    task, and all three disagree about the working directory), and the file
    that comes back is the file that went in."""
    import shutil
    import tempfile

    from PIL import Image

    import capture as cap

    tmp = Path(tempfile.mkdtemp(prefix="capture-folder-"))
    try:
        target = tmp / "nested" / "captures"
        image = Image.new("RGBA", (64, 48), (200, 30, 90, 255))
        path = cap.save_image(image, str(target))
        assert path.exists() and path.parent == target, path
        assert Image.open(path).size == (64, 48)
        again = cap.save_image(image, str(target))
        assert again != path, "two shots must not share a name"
        # A relative folder resolves next to the app, never to os.getcwd().
        app = Path(cap.__file__).resolve().parent
        assert cap.capture_dir("captures") == app / "captures"
        assert cap.capture_dir(str(tmp)) == tmp, "an absolute path is obeyed"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_the_two_settings_that_change_the_gesture_are_actually_read(
) -> None:
    """A setting that is declared and never read is a setting that lies.
    `copy_to_clipboard = false` must stop the clipboard write and nothing
    else; `after_shot` must decide whether the editor opens at all; and
    `always_save` must decide whether the file is written — because the
    editor is an offer and never a step, and after this change so is the
    folder."""
    import inspect

    import capture as cap

    signature = inspect.signature(cap.ShotWindow.__init__).parameters
    for name in ("copy", "edit", "save"):
        assert name in signature, (name, list(signature))

    window = inspect.getsource(cap.ShotWindow)
    saved = window.split("def _first_save(")[1].split("\n    def ")[0]
    assert "if self.copy else False" in saved, \
        "the first save copies whatever the setting says"
    assert "if self.save:" in saved, \
        "always_save = false must be able to skip the file"
    assert saved.index("if self.save:") < saved.index("if self.copy"), \
        "the clipboard is the half that is not negotiable, so it comes " \
        "after the file and a failed save cannot skip it"
    chose = window.split("def _chose(")[1].split("\n    def ")[0]
    assert "self._first_save()" in chose and "if not self.edit" in chose, \
        'the editor is an offer, and after_shot != "editor" declines it'
    assert chose.index("self._first_save()") < chose.index("if not self.edit"), \
        "declining the editor must still copy, and still save when asked"
    assert "self.result" in chose, \
        "a capture the editor did not take has to be handed back, or the " \
        "corner card has nothing to offer"

    flow = inspect.getsource(cap.Controller._shot_flow)
    assert "copy=cfg.copy_to_clipboard" in flow, flow
    assert 'edit=(cfg.after_shot == "editor")' in flow, flow
    assert "save=cfg.always_save" in flow, flow
    # The branch that decides whether a card is offered at all can live in
    # either half — the flow that took the picture, or the _offer it hands
    # to now that offering does not block. What matters is that SOMETHING
    # still reads the setting, so this follows the branch instead of
    # pinning it to one method.
    decides = flow + inspect.getsource(cap.Controller._offer)
    assert 'cfg.after_shot == "toast"' in decides, decides


def test_every_tool_and_action_has_an_icon_that_draws() -> None:
    """The chips are painted from one icon function, and a missing shape is
    an exception in the middle of a paint rather than a blank square."""
    import capture as cap

    names = ([glyph for _n, glyph, _l in cap.TOOLS]
             + [glyph for _n, glyph, _l in cap.ACTIONS]
             + ["undo", "close", "stop", "pause", "play", "record", "folder",
                "copy", "mic", "trash"])
    for name in names:
        img = cap.icon(name, 20)
        assert img.size == (20, 20), name
        assert img.getchannel("A").getextrema()[1] > 0, f"{name} drew nothing"
    try:
        cap.icon("no-such-icon")
    except ValueError:
        pass
    else:
        raise AssertionError("an unknown icon must say so, not draw nothing")


# ---- the [capture] section ----

def test_capture_section_parses_with_defaults_and_overrides() -> None:
    import shutil
    import tempfile
    tmp = Path(tempfile.mkdtemp(prefix="capture-config-"))
    path = tmp / "config.toml"
    try:
        path.write_text(
            'hotkey = "right ctrl"\n'
            "[capture]\n"
            "enabled = false\n"
            'capture_hotkey = "f15"\n'
            'record_hotkey = "f16"\n'
            'folder = "shots"\n'
            "fps = 24\n"
            'quality = "sharp"\n'
            'audio = "mic"\n'
            "max_minutes = 0\n",
            "utf-8")
        cfg = config_mod.load(path)
        cap = cfg.capture
        assert cap.enabled is False
        assert cap.hotkey == "f15"              # the TOML key's real name
        assert cfg.capture_hotkey == "f15"      # ...and its public face
        assert cap.record_hotkey == "f16"
        assert cfg.record_hotkey == "f16"
        assert cap.folder == "shots"
        assert cap.fps == 24
        assert cap.quality == "sharp"
        assert cap.audio == "mic"
        assert cap.max_minutes == 0
        assert cap.cursor is True               # untouched default
        assert cap.copy_to_clipboard is True

        defaults = config_mod.CaptureConfig()
        assert defaults.audio == "off", \
            "a recorder that quietly opens the microphone is a surprise"
        assert defaults.hotkey == "ctrl+f11"
        assert defaults.record_hotkey == "ctrl+f12"
        assert defaults.folder == "captures"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_a_bad_capture_setting_is_refused_and_the_file_is_untouched() -> None:
    """The staged file is load()ed before os.replace, so a section with no
    validation block is a section the dashboard can write nonsense into
    that only bites at the next launch."""
    import shutil
    tmp, path = _temp_config()
    try:
        before = path.read_bytes()
        for key, value in (("capture.quality", "lossless"),
                           ("capture.audio", "system"),
                           ("capture.fps", 200),
                           ("capture.max_minutes", -1)):
            try:
                config_mod.set_values(path, {key: value})
            except config_mod.ConfigError as e:
                assert key.split(".")[1] in str(e) or "capture" in str(e), e
            else:
                raise AssertionError(f"{key}={value!r} was accepted")
            assert path.read_bytes() == before, \
                f"the real file changed while refusing {key}"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_capture_keys_write_back_nested_and_keep_every_comment() -> None:
    """Both keys live INSIDE [capture], so the write-back must be dotted —
    and set_values' line editor keeps every comment byte while doing it,
    because those comments are the measurements."""
    import shutil
    tmp, path = _temp_config()
    try:
        before = path.read_text("utf-8")
        marker = "# a backstop, not a budget: a key tapped by"
        assert marker in before, "the comment this test protects vanished"
        config_mod.set_values(path, {"capture.capture_hotkey": "f13",
                                     "capture.record_hotkey": "f14"})
        after = path.read_text("utf-8")
        cfg = config_mod.load(path)
        assert cfg.capture.hotkey == "f13"
        assert cfg.capture.record_hotkey == "f14"
        assert marker in after, "a measurement was deleted by a key change"
        assert before.count("\n") == after.count("\n"), "line count changed"
        assert 'hotkey = "right ctrl"' in after, "the top-level key moved"
        # There is no insert path for a nested key: everything the dashboard
        # may write has to ship as a literal line in config.toml.
        try:
            config_mod.set_values(path, {"capture.no_such_knob": 1})
        except config_mod.ConfigError:
            pass
        else:
            raise AssertionError("set_values invented a key inside a section")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_the_capture_keys_bind_and_the_kill_switch_unbinds_both() -> None:
    """`enabled = false` is the kill switch and it has to reach the state
    machine, not merely the controller: a key that still fires and then
    does nothing is a key you cannot use for anything else."""
    import dataclasses

    import main as main_mod

    cfg = config_mod.load(Path(__file__).resolve().parent / "config.toml")
    _hot, taps, _latch, _pause = main_mod.App.bindings(cfg)
    assert "capture" in taps.values(), taps
    assert "record" in taps.values(), taps
    assert main_mod.App._vk_of(taps, "capture") is not None
    assert main_mod.App._vk_of(taps, "record") is not None

    off = dataclasses.replace(
        cfg, capture=dataclasses.replace(cfg.capture, enabled=False))
    _hot, taps, _latch, _pause = main_mod.App.bindings(off)
    assert "capture" not in taps.values(), taps
    assert "record" not in taps.values(), taps

    one = dataclasses.replace(
        cfg, capture=dataclasses.replace(cfg.capture, record_hotkey=""))
    _hot, taps, _latch, _pause = main_mod.App.bindings(one)
    assert "capture" in taps.values(), "the other key must survive alone"
    assert "record" not in taps.values(), taps


def test_a_capture_key_collision_is_refused_like_every_other() -> None:
    """with_field has to assign through the property (dataclasses.replace
    cannot), and check_hotkeys has to see the result — otherwise a rebind
    onto an occupied key is written to the file and only fails at the next
    launch."""
    import main as main_mod

    cfg = config_mod.load(Path(__file__).resolve().parent / "config.toml")
    # ctrl+f5, because ctrl+f6 stopped being free the day the camera key
    # took it. Any measured-free key that nothing else in the shipped
    # config claims will do.
    moved = config_mod.with_field(cfg, "capture_hotkey", "ctrl+f5")
    assert moved.capture.hotkey == "ctrl+f5"
    assert moved.capture_hotkey == "ctrl+f5"
    assert moved.capture.record_hotkey == cfg.capture.record_hotkey, \
        "moving one key must not move the other"
    config_mod.check_hotkeys(moved)                     # a free key: fine

    clash = config_mod.with_field(cfg, "record_hotkey", cfg.lookup_hotkey)
    try:
        config_mod.check_hotkeys(clash)
    except config_mod.ConfigError as e:
        assert "record_hotkey" in str(e) or "lookup_hotkey" in str(e), e
    else:
        raise AssertionError("two keys on one binding were accepted")

    assert main_mod.NESTED_HOTKEYS["capture_hotkey"] == "capture.capture_hotkey"
    assert main_mod.NESTED_HOTKEYS["record_hotkey"] == "capture.record_hotkey"


def test_both_capture_keys_are_registered_everywhere_a_key_must_be() -> None:
    """HOTKEY_FIELDS is the single registration point and CHORD_FIELDS is
    what lets a tap carry ctrl. Missing the second makes "ctrl+f11" fail
    check_hotkeys with 'cannot take modifiers' — at load, on a config the
    app shipped."""
    import dashboard as dash_mod

    registered = dict(config_mod.HOTKEY_FIELDS)
    for field in ("capture_hotkey", "record_hotkey"):
        assert field in registered, field
        assert registered[field].endswith("(tap)"), registered[field]
        assert field in config_mod.CHORD_FIELDS, field
        named = {f for _title, fields in dash_mod.KEY_GROUPS for f in fields}
        assert field in named, f"{field} has no group on the Keys screen"
    assert dash_mod.NESTED_HOTKEYS == {
        "visual_qa_hotkey": "visual_qa.visual_qa_hotkey",
        "capture_hotkey": "capture.capture_hotkey",
        "record_hotkey": "capture.record_hotkey",
        "camera_hotkey": "camera.camera_hotkey",
        "screens_hotkey": "awake.screens_hotkey",
    }, dash_mod.NESTED_HOTKEYS


def test_the_shipped_config_carries_the_capture_section() -> None:
    """It is committed to both branches (see the cross-branch test), and
    the values shipped have to be ones both branches can live with — on
    classic the section is simply never read."""
    here = Path(__file__).resolve().parent
    text = (here / "config.toml").read_text("utf-8")
    assert "[capture]" in text
    for key in ("capture_hotkey", "record_hotkey", "folder", "fps",
                "quality", "cursor", "audio", "max_minutes",
                "copy_to_clipboard", "edit_after_shot", "copy_clip_path"):
        assert f"\n{key} = " in text, f"{key} is not a writable line"
    cfg = config_mod.load(here / "config.toml")
    assert cfg.capture.audio == "off", "the shipped default must be off"
    ignored = (here / ".gitignore").read_text("utf-8")
    assert f"{cfg.capture.folder}/" in ignored, \
        "pictures of this screen must not be committable"


def test_the_capture_controller_costs_nothing_until_a_key_is_pressed(
) -> None:
    """main.py builds one behind a lazy property, and the whole point of
    that is that an owner who never presses either key never loads Pillow,
    Tk or a video encoder. Constructing it must be stdlib only."""
    import capture as cap

    calls = []
    controller = cap.Controller(lambda: calls.append(1) or object(),
                                ask_provider=lambda: None)
    assert controller.busy is False
    assert controller.recording is False
    assert calls == [], "the config was read before anything was pressed"
    controller.stop()                       # safe with nothing running
    assert controller.recording is False


def test_a_recording_toggles_off_with_the_key_that_started_it() -> None:
    """The second press of the key is how a recording ENDS. Refusing it as
    'busy' would leave the only way out on a bar that is sitting on top of
    the thing being recorded."""
    import capture as cap

    controller = cap.Controller(lambda: None)

    class FakeRecorder:
        def __init__(self):
            self.stopped = False

        def stop(self):
            self.stopped = True

    fake = FakeRecorder()
    controller._recorder = fake
    controller._busy.set()
    assert controller.recording is True
    assert controller.toggle_clip() is True, "a running clip must accept stop"
    assert controller._stop_clip.is_set(), "the pump was never told"
    controller.stop()
    assert fake.stopped is True

    idle = cap.Controller(lambda: None)
    # Set means a window that OWNS THE SCREEN is up — the selector, the
    # editor, the camera, the clip bar. It stopped meaning "a corner card
    # is up" when the cards learned to stack, and both refusals below are
    # about the screen-owning half, so both still hold.
    idle._busy.set()
    assert idle.toggle_clip() is False, "a second selector must be refused"
    assert idle.begin_shot() is False


def test_the_recorder_declares_its_streams_before_the_first_frame() -> None:
    """An mp4 declares its streams when the container opens, which is at
    the first frame — a track cannot be added later. That is why the bar's
    microphone control MUTES (feeds silence, so the sample clock keeps
    advancing and the picture stays in sync) instead of pretending it can
    add one."""
    import shutil
    import tempfile

    import capture as cap

    tmp = Path(tempfile.mkdtemp(prefix="capture-clip-"))
    try:
        silent = cap.ScreenRecorder((0, 0, 64, 48), tmp / "a.mp4",
                                    audio=False)
        assert silent.has_audio is False
        loud = cap.ScreenRecorder((0, 0, 64, 48), tmp / "b.mp4", audio=True,
                                  audio_device=None)
        assert loud.has_audio is True
        assert loud.muted is False
        assert loud.toggle_mute() is True and loud.muted is True
        assert loud.toggle_mute() is False and loud.muted is False
        # device=None is a LEGAL device (the system default), so the flag
        # and the device must not be the same question.
        assert loud.audio_device is None and loud.audio_rate > 0
        assert silent.audio_rate == 0
        # Nothing was recorded, so nothing is left behind.
        assert silent.finish(timeout=1) is None
        assert not (tmp / "a.mp4").exists(), "an empty clip left a stub file"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_a_paused_recording_holds_its_clock_still() -> None:
    """A pause has to be a CUT, not a freeze-frame: the wall clock that
    stamps every frame must not run while nothing is being captured, or
    the gap plays back as a still image for as long as you were away."""
    import time

    import capture as cap

    recorder = cap.ScreenRecorder((0, 0, 64, 48), Path("unused.mp4"))
    recorder.started_at = time.monotonic() - 2.0
    running = recorder.elapsed
    assert 1.8 < running < 2.3, running
    assert recorder.toggle_pause() is True
    time.sleep(0.25)
    held = recorder.elapsed
    assert abs(held - running) < 0.06, (running, held)
    assert recorder.toggle_pause() is False
    assert recorder.elapsed >= held


def test_a_capture_press_is_refused_while_a_selector_owns_the_screen(
) -> None:
    """Refuse-when-busy, never queue-when-busy: a second OVERLAY while the
    first still owns a Tcl interpreter is the thread-ownership abort
    AGENTS.md spends a paragraph on.

    That reasoning is about the SELECTOR — the frozen, dimmed, whole-screen
    window you drag a box on — and it is as true as it ever was. What is no
    longer true is that it covers the corner card: a card owns a corner and
    not the screen, so a second card is legal and a second press while one
    is up now takes a second capture. That is asserted next door, in
    test_a_second_capture_press_is_a_second_capture. `busy` here means what
    it means now: a window that owns the screen.
    """
    import main as main_mod

    class FakeCapture:
        def __init__(self):
            self.busy = True
            self.recording = False
            self.started = 0

        def begin_shot(self):
            self.started += 1
            return True

        def toggle_clip(self):
            self.started += 1
            return True

    app = main_mod.App.__new__(main_mod.App)
    app._capture = FakeCapture()
    app._cue_lock = threading.Lock()
    app._cue_last = {}
    # PUT BACK, not deleted. `del type(app).capture` removed App's real
    # property for the whole rest of the process — the assignment above
    # replaces the class attribute rather than shadowing it — so every
    # test after this one ran against an App with no `capture` at all.
    # Nothing happened to need it until one did, and then it failed here
    # rather than where the damage was done.
    real_capture = main_mod.App.capture
    type(app).capture = property(lambda self: self._capture)
    try:
        app._tap_capture()
        app._tap_record()
        assert app._capture.started == 0, "a busy overlay was pressed again"
        app._capture.busy = False
        app._tap_capture()
        app._tap_record()
        assert app._capture.started == 2, app._capture.started
        # ...but a RUNNING recording must always accept the stop press.
        app._capture.busy = True
        app._capture.recording = True
        app._tap_record()
        assert app._capture.started == 3, "the stop press was refused"
    finally:
        type(app).capture = real_capture


def test_a_second_capture_press_is_a_second_capture() -> None:
    """THE WHOLE POINT OF THE STACK, in one assertion.

    The key used to go dead for as long as a card sat in the corner: press
    it again inside those five seconds and the app logged "already up" and
    did nothing. That is the app refusing its one job at the exact moment
    you are working fastest — three things off a page, one after another —
    and the reason given was an implementation detail, a Tcl interpreter
    the card owned, which is not the owner's problem.

    A corner card no longer makes the controller busy, so the tap no
    longer refuses. Three presses, three captures, three cards. The
    sibling test above still guards the case that IS refused, which is a
    selector owning the screen.
    """
    import main as main_mod

    class FakeCapture:
        def __init__(self):
            self.busy = False         # a card in a corner is not busy
            self.recording = False
            self.started = 0

        def begin_shot(self):
            self.started += 1
            return True

        def toggle_clip(self):
            self.started += 1
            return True

    app = main_mod.App.__new__(main_mod.App)
    app._capture = FakeCapture()
    app._cue_lock = threading.Lock()
    app._cue_last = {}
    # PUT BACK, not deleted — the same restore dance the test above
    # explains at length. The assignment below replaces App's real
    # property for the whole process, not just for this instance.
    real_capture = main_mod.App.capture
    type(app).capture = property(lambda self: self._capture)
    try:
        app._tap_capture()
        app._tap_capture()
        app._tap_capture()
        assert app._capture.started == 3, (
            f"{3 - app._capture.started} presses were swallowed while a "
            "card was in the corner, which is the behaviour this feature "
            "exists to remove")
    finally:
        type(app).capture = real_capture


def test_the_capture_keys_are_kept_away_from_the_lookup_box() -> None:
    """popup.py decides which keystrokes it swallows, and main.py owns the
    one invariant it cannot: the key that opens a window has to reach the
    code that opens it."""
    import main as main_mod

    app = main_mod.App.__new__(main_mod.App)
    app._lookup_vk = 0x77
    app._vqa_vk = 0x79
    app._capture_vk = 0x7A
    app._record_vk = 0x7B
    swallowed = []

    class FakePopup:
        def on_key(self, vk):
            swallowed.append(vk)
            return True

    app.popup = FakePopup()
    for vk in (0x77, 0x79, 0x7A, 0x7B):
        assert app._popup_key(vk) is False, hex(vk)
    assert swallowed == [], "a key that opens a window was offered to the box"
    assert app._popup_key(0x41) is True
    assert swallowed == [0x41]


def test_a_half_built_app_still_answers_the_popup_without_capture() -> None:
    """The suite builds Apps by hand with no __init__, and classic has no
    [capture] at all. Both have to degrade to 'feature absent' rather than
    AttributeError inside the keyboard hook."""
    import main as main_mod

    app = main_mod.App.__new__(main_mod.App)
    app._lookup_vk = None
    app._vqa_vk = None

    class FakePopup:
        def on_key(self, vk):
            return False

    app.popup = FakePopup()
    assert main_mod.App._capture is None
    assert main_mod.App._capture_vk is None
    assert main_mod.App._record_vk is None
    assert app._popup_key(0x41) is False


def test_every_monitor_is_offered_by_name_not_only_the_virtual_screen(
) -> None:
    """"Record the screen" is not "drag from corner to corner" — that is
    impossible to land exactly and it is the commonest thing anyone wants.
    virtual_screen() answers how big the desktop is, which is a different
    question from which screens there are: this machine's desktop is one
    4480x1440 rectangle made of two monitors at 2560x1440 and 1920x1080,
    and the second one starts at x = -1920."""
    import capture as cap

    screens = cap.monitors()
    assert screens, "no monitors at all"
    assert screens[0]["primary"] is True, "the primary must come first"
    assert [m["label"] for m in screens] == \
        [f"Screen {i}" for i in range(1, len(screens) + 1)], screens
    vx, vy, vw, vh = cap.virtual_screen()
    for entry in screens:
        left, top, right, bottom = entry["rect"]
        assert right > left and bottom > top, entry
        assert left >= vx and top >= vy, entry
        assert right <= vx + vw and bottom <= vy + vh, entry
    # Together they cover the virtual screen's extremes, or one of them is
    # missing and "All screens" would be a lie.
    assert min(m["rect"][0] for m in screens) == vx
    assert max(m["rect"][2] for m in screens) == vx + vw


def test_the_indicator_sits_in_a_corner_of_the_work_area() -> None:
    """A corner and not "beside the region": an indicator that moves when
    the region does is an obstruction, and a corner is somewhere you can
    learn to glance at. The work area, so it is never under a taskbar."""
    import capture as cap

    work = (0, 0, 2560, 1400)
    size = (120, 34)
    corners = {
        "top-left": (18, 18),
        "top-right": (2560 - 120 - 18, 18),
        "bottom-left": (18, 1400 - 34 - 18),
        "bottom-right": (2560 - 120 - 18, 1400 - 34 - 18),
    }
    for corner, expected in corners.items():
        assert cap.corner_at(work, size, corner) == expected, corner
        x, y = cap.corner_at(work, size, corner)
        assert work[0] <= x and x + size[0] <= work[2], corner
        assert work[1] <= y and y + size[1] <= work[3], corner
    # A monitor at negative coordinates is a monitor like any other.
    left = cap.corner_at((-1920, 209, 0, 1250), size, "bottom-right")
    assert left == (0 - 120 - 18, 1250 - 34 - 18), left
    assert "off" in cap.CORNERS, "there has to be a way to have no pill"


def test_the_clip_bar_announces_itself_and_then_gets_out_of_the_way(
) -> None:
    """The failure mode of a screen recorder is not knowing whether it is
    running, so it says "Recording started" — and then it must stop saying
    it, because an announcement that stays is a banner. Hover wins over
    both, or the controls would be unreachable once it shrank."""
    import capture as cap

    assert cap.bar_phase(0.0, False) == "announce"
    assert cap.bar_phase(cap.ANNOUNCE_S - 0.1, False) == "announce"
    assert cap.bar_phase(cap.ANNOUNCE_S, False) == "timer"
    assert cap.bar_phase(600.0, False) == "timer"
    for elapsed in (0.0, 1.0, 600.0):
        assert cap.bar_phase(elapsed, True) == "hover", elapsed

    # timer_corner = "off" means no pill at all — but the announcement
    # still happens, because the question has to be answerable once.
    bar = cap.ClipBar.__new__(cap.ClipBar)
    bar.corner, bar.announce, bar._hovering = "off", True, False
    bar.started = __import__("time").monotonic()
    assert bar.phase() == "announce"
    bar.started -= cap.ANNOUNCE_S + 1
    assert bar.phase() == "hidden"
    bar.announce = False
    bar.started = __import__("time").monotonic()
    assert bar.phase() == "hidden", "announce = false and off means nothing"
    bar.corner = "bottom-right"
    assert bar.phase() == "timer", "no announcement is straight to the pill"


def test_the_pill_grows_for_a_longer_clock_instead_of_clipping_it() -> None:
    """A clock that reads "1:02:0" is worse than a wider pill, and "paused"
    has to fit next to it."""
    import capture as cap

    short = cap.timer_width("0:07")
    hours = cap.timer_width("1:02:09")
    paused = cap.timer_width("0:07  paused")
    assert short >= 88
    assert hours > short, (short, hours)
    assert paused > hours, (hours, paused)
    with_buttons = cap.timer_width("0:07", buttons=4)
    assert with_buttons >= short + 4 * cap.BAR_BTN, with_buttons


def test_the_screen_chips_do_not_overlap_and_click_where_they_are_drawn(
) -> None:
    """One table feeds the painter and the hit test. And the chip's TARGET
    must be read before the hint row is dropped — resolving the label
    afterwards is a KeyError on every click, which is exactly what the
    first version did."""
    import capture as cap

    window = cap.ShotWindow.__new__(cap.ShotWindow)
    window._keep = {}
    window._hint_id = None
    window._chips = {}
    window._chip_hover = None
    window._hint_line = "Drag a box   ·   Esc cancels"
    window._plan_hint(1280, 300)
    chips = window._chips
    # The card holds every chip it planned, or one of them is drawn off
    # the sheet of glass it is supposed to be on.
    card = window._hint_box
    for name, chip in chips.items():
        box = chip["box"]
        assert card[0] <= box[0] and box[2] <= card[2], (name, box, card)
        assert card[1] <= box[1] and box[3] <= card[3], (name, box, card)
    assert len(chips) >= 1, chips
    screens = cap.monitors()
    if len(screens) > 1:
        assert "All screens" in chips, list(chips)
        vx, vy, vw, vh = cap.virtual_screen()
        assert chips["All screens"]["target"] == (vx, vy, vx + vw, vy + vh)
    else:
        assert "All screens" not in chips, \
            "one monitor makes 'all screens' the same button twice"
    boxes = [(name, chip["box"]) for name, chip in chips.items()]
    for i, (an, a) in enumerate(boxes):
        assert a[2] > a[0] and a[3] > a[1], an
        centre = ((a[0] + a[2]) // 2, (a[1] + a[3]) // 2)
        assert window._chip_under(*centre) == an, an
        for bn, b in boxes[i + 1:]:
            apart = a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1]
            assert apart, f"{an} overlaps {bn}"
    assert window._chip_under(-99, -99) is None

    # The ordering bug, as a test rather than as a comment.
    label = list(chips)[0]
    target = chips[label]["target"]
    chosen = []
    window._chose = lambda box, path: chosen.append((box, path))
    window.phase = "select"
    window.canvas = type("C", (), {"delete": lambda *a: None,
                                   "config": lambda *a, **k: None})()

    class Press:
        x, y = (chips[label]["box"][0] + chips[label]["box"][2]) // 2, \
               (chips[label]["box"][1] + chips[label]["box"][3]) // 2
        x_root = y_root = 0
        state = 0

    window._on_press(Press())
    assert chosen == [(target, None)], chosen
    assert window._chips == {}, "the hint row must be gone after the click"


def test_the_recording_indicator_settings_parse_and_are_bounded() -> None:
    """A corner name that is not a corner has to be refused at load, not
    silently turned into one — the pill would appear somewhere the owner
    did not choose and there would be nothing to read that said why."""
    import shutil
    import tempfile
    tmp = Path(tempfile.mkdtemp(prefix="capture-corner-"))
    path = tmp / "config.toml"
    try:
        path.write_text('hotkey = "right ctrl"\n[capture]\n'
                        'timer_corner = "top-left"\nannounce = false\n',
                        "utf-8")
        cfg = config_mod.load(path)
        assert cfg.capture.timer_corner == "top-left"
        assert cfg.capture.announce is False

        defaults = config_mod.CaptureConfig()
        assert defaults.timer_corner == "bottom-right"
        assert defaults.announce is True

        path.write_text('hotkey = "right ctrl"\n[capture]\n'
                        'timer_corner = "middle"\n', "utf-8")
        try:
            config_mod.load(path)
        except config_mod.ConfigError as e:
            assert "timer_corner" in str(e), e
        else:
            raise AssertionError("a corner that is not a corner was accepted")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    here = Path(__file__).resolve().parent
    text = (here / "config.toml").read_text("utf-8")
    for key in ("timer_corner", "announce"):
        assert f"\n{key} = " in text, f"{key} is not a writable line"


# ------------------------------------------------------ a photo, from a lens
#
# A webcam is the one thing a test runner cannot be given, so everything in
# this feature that can be decided without a device is a pure function and
# is checked here as arithmetic. What is left — opening DirectShow,
# decoding frames — is covered by the source-level tests at the end, which
# guard the two rules that make the feature SAFE rather than merely
# working: the lens is released by the shutter, and one press of the key
# leaves exactly one file.


def test_a_camera_size_that_does_not_parse_falls_back_rather_than_fails(
) -> None:
    """config.check() has already refused a bad size out loud at load time.
    By the time the key is pressed, the only useful answer is a camera that
    opens."""
    import capture as cap

    assert cap.parse_size("1280x720") == (1280, 720)
    assert cap.parse_size("1920X1080") == (1920, 1080)
    assert cap.parse_size(" 640 x 480 ") == (640, 480)
    for bad in ("", "720p", "1280*720", None, "0x0", "99999x99999", "x"):
        assert cap.parse_size(bad) == (1280, 720), bad
    assert cap.parse_size("nope", fallback=(640, 480)) == (640, 480)


def test_a_virtual_camera_loses_to_a_real_one() -> None:
    """OBS, Teams, Zoom and NVIDIA Broadcast each install a video device
    that is not a camera, and they sort ahead of the real one as often as
    not — on this machine OBS is second of two, and on another it is
    first. A photo key that opens a black frame from a virtual camera
    nobody is streaming into is a photo key that looks broken."""
    import capture as cap

    both = ["OBS Virtual Camera", "HD Webcam eMeet C960"]
    assert cap.pick_camera(both) == "HD Webcam eMeet C960"
    # ...but a virtual camera is still a camera when it is the only one.
    assert cap.pick_camera(["OBS Virtual Camera"]) == "OBS Virtual Camera"
    assert cap.pick_camera([]) is None
    assert cap.pick_camera(["", None]) is None

    # Asked for by name: a case-insensitive SUBSTRING, because nobody
    # retypes "HD Webcam eMeet C960" into config.toml without a typo.
    assert cap.pick_camera(both, "eMEET") == "HD Webcam eMeet C960"
    assert cap.pick_camera(both, "c960") == "HD Webcam eMeet C960"
    assert cap.pick_camera(both, " obs ") == "OBS Virtual Camera"
    # Asked for and absent is None, not "some other camera": the caller
    # falls back on purpose and says which one it took.
    assert cap.pick_camera(both, "logitech") is None


def test_the_preview_is_one_to_one_when_it_fits_and_shrinks_when_it_does_not(
) -> None:
    """WHAT YOU SEE IS WHAT YOU GET: one image is the preview, the file,
    the clipboard and what the editor opens on, so the preview size IS the
    photo size. 1:1 whenever the monitor can show it — measured true for
    1280x720 on this 2560x1440 desk — and the largest whole picture that
    fits when it cannot."""
    import capture as cap

    roomy = (0, 0, 2560, 1400)
    assert cap.preview_fit((1280, 720), roomy) == (1280, 720)
    assert cap.preview_fit((640, 480), roomy) == (640, 480)

    laptop = (0, 0, 1366, 768)
    width, height = cap.preview_fit((1920, 1080), laptop)
    assert (width, height) != (1920, 1080), "it cannot possibly fit"
    assert abs(width / height - 1920 / 1080) < 0.02, (width, height)
    assert width <= 1366 - 2 * cap.CAM_PAD
    assert height <= 768 - cap.CAM_STRIP_H - cap.CAM_PAD
    assert width % 2 == 0 and height % 2 == 0
    # Never upscaled: a 320x240 camera on a 4K monitor is a small picture,
    # not a blurred big one.
    assert cap.preview_fit((320, 240), (0, 0, 3840, 2160)) == (320, 240)


def test_the_self_timer_counts_whole_seconds_left() -> None:
    """Ceiling, not floor. A timer that floors shows 0 for a whole second
    before anything happens, and a timer that shows 0 for a whole second is
    a timer everybody presses again."""
    import capture as cap

    assert cap.countdown_left(0.0, 0.0, 3) == 3
    assert cap.countdown_left(0.0, 0.4, 3) == 3
    assert cap.countdown_left(0.0, 1.0, 3) == 2
    assert cap.countdown_left(0.0, 2.9, 3) == 1
    assert cap.countdown_left(0.0, 3.0, 3) == 0      # 0 means fire
    assert cap.countdown_left(0.0, 9.0, 3) == 0
    assert cap.countdown_left(0.0, 0.0, 0) == 0      # no timer, no wait


def test_the_timer_chip_cycles_and_comes_back_round() -> None:
    import capture as cap

    assert cap.CAM_TIMERS == (0, 3, 10)
    assert cap.next_in(cap.CAM_TIMERS, 0) == 3
    assert cap.next_in(cap.CAM_TIMERS, 3) == 10
    assert cap.next_in(cap.CAM_TIMERS, 10) == 0
    assert cap.next_in(cap.CAM_TIMERS, 7) == 0       # unknown starts over
    assert cap.next_in((), 5) == 5                   # nothing to cycle
    assert cap.next_in(["a", "b"], "b") == "a"       # and it does cameras


def test_every_camera_control_is_hit_where_it_is_drawn() -> None:
    """The one bug this layout exists to prevent: a button drawn a few
    pixels from where it can be clicked — invisible in a screenshot and
    maddening under the hand. The painter and the hit test read the same
    dict, and this says so."""
    import capture as cap

    # The widest card this desk produces, and the narrowest the window is
    # allowed to build. preview_fit never upscales, so a 160x120 webcam
    # would otherwise ask for a card too narrow for the shutter to sit
    # between the chips — CAM_MIN_W is what stops it, and this is the
    # measurement that says the number is big enough.
    for width in (cap.CAM_MIN_W, 348, 1308):
        spots = cap.camera_bar(width, switchable=True)
        assert set(spots) == {"mirror", "timer", "switch", "close",
                              "shutter"}
        for name, (x0, y0, x1, y1) in spots.items():
            assert cap.hit(spots, (x0 + x1) // 2,
                           (y0 + y1) // 2) == name, (width, name)
            assert 0 <= x0 < x1 <= width, (width, name)
            assert 0 <= y0 < y1 <= cap.CAM_STRIP_H, (width, name)

        # Nothing overlaps anything, or one press would mean two things
        # and the hit test would settle it by dictionary order.
        boxes = list(spots.values())
        for index, a in enumerate(boxes):
            for b in boxes[index + 1:]:
                assert (a[2] <= b[0] or b[2] <= a[0]
                        or a[3] <= b[1] or b[3] <= a[1]), (width, a, b)

    # The shutter is centred on the CARD, not in the gap between the
    # chips: a hand finds a shutter in the middle without looking.
    width = 1308
    spots = cap.camera_bar(width, switchable=True)
    sx0, _sy0, sx1, _sy1 = spots["shutter"]
    assert abs((sx0 + sx1) // 2 - width // 2) <= 1

    # One camera, no switch chip — a control that cannot do anything is
    # a control that has to be explained.
    assert "switch" not in cap.camera_bar(width)


def test_dshow_video_devices_are_read_without_the_microphones() -> None:
    """PyAV hands ffmpeg's listing over as FRAGMENTS, not lines: one device
    arrives as the quoted name, "(video", ")" and a newline, and off the
    main thread the newline is dropped too, so the whole report comes back
    as one run-on string. Both shapes are read here, because both were
    observed on this machine on 2026-08-26."""
    import capture as cap

    run_on = ('"HD Webcam eMeet C960"(video)Alternative name "@device_pnp_x"'
              '"OBS Virtual Camera"(video)Alternative name "@device_sw_y"'
              '"Headset Microphone (Arctis 7 Chat)"(audio)'
              'Alternative name "@device_cm_z"')
    assert cap.read_video_devices(run_on) == ["HD Webcam eMeet C960",
                                              "OBS Virtual Camera"]

    with_lines = ('[dshow @ 0] "HD Webcam eMeet C960" (video)\n'
                  '[dshow @ 0]   Alternative name "@device_pnp_x"\n'
                  '[dshow @ 0] "Microphone (HD Webcam eMeet C960)" (audio)\n')
    assert cap.read_video_devices(with_lines) == ["HD Webcam eMeet C960"]
    assert cap.read_video_devices("") == []


def test_a_photo_and_a_screenshot_share_a_folder_without_colliding() -> None:
    """One folder, three first words. Sorting it by name still groups the
    shots, the photos and the clips, and the uniquifier for one kind never
    counts another kind's files."""
    import shutil
    import tempfile

    import capture as cap
    from PIL import Image

    assert cap.capture_name("photo", 0).startswith("photo ")
    assert cap.capture_name("photo", 0).endswith(".png")
    assert cap.capture_name("photo", 0) != cap.capture_name("shot", 0)
    second = cap.capture_name("photo", 0, taken={cap.capture_name("photo", 0)})
    assert second.endswith(" (2).png"), second

    tmp = Path(tempfile.mkdtemp(prefix="camera-folder-"))
    try:
        picture = Image.new("RGB", (8, 6), (10, 20, 30))
        shot = cap.save_image(picture, str(tmp), when=0, kind="shot")
        photo = cap.save_image(picture, str(tmp), when=0, kind="photo")
        assert shot.exists() and photo.exists()
        assert shot != photo, "one second, two kinds, two files"
        assert photo.name.startswith("photo ")
        # A second photo in the same second does not overwrite the first,
        # and does not count the screenshot beside it either.
        again = cap.save_image(picture, str(tmp), when=0, kind="photo")
        assert again.name.endswith(" (2).png"), again.name
        assert len(list(tmp.glob("*.png"))) == 3
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_the_lens_is_released_by_the_shutter_and_not_by_the_editor() -> None:
    """THE PRIVACY RULE OF THIS FEATURE, and it is worth a source-level
    test because nothing else can see it: the camera is closed by _fire,
    before the flash and before the file is written, so the light beside
    the lens goes out when the picture is taken rather than when the
    editing session ends. And the app's own stop() takes it down too,
    whatever the window was in the middle of."""
    source = (Path(__file__).resolve().parent / "capture.py").read_text(
        "utf-8")

    body = source[source.index("    def _fire(self)"):
                  source.index("    def _freeze_desktop")]
    assert "self.camera.close()" in body, \
        "_fire must let go of the device"
    assert body.index("self.camera.close()") < body.index("save_image("), \
        ("the camera is closed BEFORE the picture is written — everything "
         "after the still is pixels we already hold")

    shutdown = source[source.index("    def stop(self) -> None:"):]
    assert "camera.close()" in shutdown, \
        "quitting the app must close the camera too"

    # And the window's own exit is belt and braces: an exception anywhere
    # in the pump must not leave a webcam streaming.
    # From the class, not from the file: ShotWindow has a "-- painting --"
    # marker of its own and it comes first.
    at = source.index("class CameraWindow:")
    window = source[at:source.index("    # -- painting --", at)]
    pump = window[window.index("    def run(self)"):]
    assert "finally:" in pump and "self.camera.close()" in pump, \
        "the pump must close the camera however it exits"


def test_one_press_of_the_camera_key_leaves_exactly_one_file() -> None:
    """The camera window keeps the promise — saved and copied at the
    instant of the shutter, which is where it belongs — and the editor
    ADOPTS that file rather than writing a second one. Without this, one
    press of one key would drop two identical pngs in the folder."""
    source = (Path(__file__).resolve().parent / "capture.py").read_text(
        "utf-8")

    edit = source[source.index("    def _edit_photo"):]
    edit = edit[:edit.index("    # ---- the recording key ----")]
    assert 'saved=result.get("path")' in edit, edit[-400:]
    assert 'kind="photo"' in edit
    assert "start_box=box" in edit

    begin = source[source.index("    def _begin_at(self, box)"):]
    begin = begin[:begin.index("    # -- the editing phase --")]
    assert "self._pre_saved" in begin
    assert "self._first_save()" in begin, \
        "a picture handed in WITHOUT a file still has to be written once"


def test_the_camera_is_opened_in_exactly_one_place() -> None:
    """Nothing in this app opens the lens but the camera key. A second
    construction site is a second thing to audit every time this file is
    edited, and this feature is the one where that audit matters."""
    source = (Path(__file__).resolve().parent / "capture.py").read_text(
        "utf-8")
    opens = [line.strip() for line in source.splitlines()
             if "Camera(" in line]
    assert len(opens) == 1, opens
    assert opens[0].startswith("camera = Camera("), opens
    assert "def _open_camera" in source
    assert "import cv2" not in source and "cv2" not in source, \
        "the camera arrives through PyAV, which is already installed"


def test_the_camera_key_is_registered_everywhere_a_key_must_be() -> None:
    """HOTKEY_FIELDS is the single registration point, CHORD_FIELDS is what
    lets a tap carry ctrl, KEY_GROUPS is where the dashboard shows it and
    NESTED_HOTKEYS is where a rebind gets written. Missing any one of them
    is a key that half exists."""
    import dashboard as dash_mod
    import main as main_mod

    registered = dict(config_mod.HOTKEY_FIELDS)
    assert "camera_hotkey" in registered
    assert registered["camera_hotkey"].endswith("(tap)"), \
        registered["camera_hotkey"]
    assert "camera_hotkey" in config_mod.CHORD_FIELDS
    named = {f for _title, fields in dash_mod.KEY_GROUPS for f in fields}
    assert "camera_hotkey" in named, "no group on the Keys screen"
    assert main_mod.NESTED_HOTKEYS["camera_hotkey"] == "camera.camera_hotkey"
    assert dash_mod.NESTED_HOTKEYS["camera_hotkey"] == "camera.camera_hotkey"

    cfg = config_mod.load(Path(__file__).resolve().parent / "config.toml")
    moved = config_mod.with_field(cfg, "camera_hotkey", "ctrl+f5")
    assert moved.camera.hotkey == "ctrl+f5"
    assert moved.camera_hotkey == "ctrl+f5"
    assert moved.capture.hotkey == cfg.capture.hotkey, \
        "moving one key must not move another"
    config_mod.check_hotkeys(moved)

    clash = config_mod.with_field(cfg, "camera_hotkey", cfg.capture_hotkey)
    try:
        config_mod.check_hotkeys(clash)
    except config_mod.ConfigError as e:
        assert "camera_hotkey" in str(e) or "capture_hotkey" in str(e), e
    else:
        raise AssertionError("two keys on one binding were accepted")


def test_the_camera_key_binds_and_the_kill_switch_unbinds_it() -> None:
    """enabled = false unregisters the key ENTIRELY — nothing in the state
    machine, whatever the key string still says. For a key that opens a
    lens that is the difference between a setting and a promise."""
    import dataclasses

    import main as main_mod

    cfg = config_mod.load(Path(__file__).resolve().parent / "config.toml")
    _hotkeys, taps, _latch, _pause = main_mod.App.bindings(cfg)
    assert taps[parse_binding(cfg.camera_hotkey)] == "photo", taps

    off = dataclasses.replace(cfg, camera=dataclasses.replace(
        cfg.camera, enabled=False))
    _h, taps_off, _l, _p = main_mod.App.bindings(off)
    assert all(name != "photo" for name in taps_off.values()), taps_off

    unbound = dataclasses.replace(cfg, camera=dataclasses.replace(
        cfg.camera, enabled=True, hotkey=""))
    _h, taps_empty, _l, _p = main_mod.App.bindings(unbound)
    assert all(name != "photo" for name in taps_empty.values())

    # And classic has no [camera] section at all: main.py is byte-identical
    # on both branches, so bindings() must survive a Config without one.
    stripped = dataclasses.replace(cfg)
    object.__setattr__(stripped, "camera", None)
    _h, taps_none, _l, _p = main_mod.App.bindings(stripped)
    assert all(name != "photo" for name in taps_none.values())


def test_camera_section_parses_with_defaults_and_overrides() -> None:
    import shutil
    import tempfile
    tmp = Path(tempfile.mkdtemp(prefix="camera-config-"))
    path = tmp / "config.toml"
    try:
        path.write_text(
            'hotkey = "right ctrl"\n'
            "[camera]\n"
            "enabled = false\n"
            'camera_hotkey = "f14"\n'
            'device = "eMeet"\n'
            'size = "1920x1080"\n'
            "fps = 24\n"
            "mirror = true\n"
            "timer = 10\n"
            'folder = "photos"\n',
            "utf-8")
        cfg = config_mod.load(path)
        cam = cfg.camera
        assert cam.enabled is False
        assert cam.hotkey == "f14"            # the TOML key's real name
        assert cfg.camera_hotkey == "f14"     # ...and its public face
        assert cam.device == "eMeet"
        assert cam.size == "1920x1080"
        assert cam.fps == 24
        assert cam.mirror is True
        assert cam.timer == 10
        assert cam.folder == "photos"
        assert cam.copy_to_clipboard is True  # untouched defaults
        assert cam.edit_after_shot is True

        defaults = config_mod.CameraConfig()
        assert defaults.mirror is False, \
            "the commonest thing held up to a webcam has writing on it"
        assert defaults.timer == 0
        assert defaults.hotkey == "ctrl+f6"
        assert defaults.folder == "captures", "one place to look for pictures"

        for bad, word in ((("timer", "5"), "timer"),
                          (("size", '"720p"'), "size"),
                          (("fps", "0"), "fps"),
                          (("folder", '""'), "folder")):
            key, value = bad
            path.write_text(f'hotkey = "right ctrl"\n[camera]\n'
                            f"{key} = {value}\n", "utf-8")
            try:
                config_mod.load(path)
            except config_mod.ConfigError as e:
                assert word in str(e), (word, e)
            else:
                raise AssertionError(f"camera.{key} = {value} was accepted")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_the_shipped_config_carries_the_camera_section() -> None:
    """Committed to both branches like every other section (see the
    cross-branch test); on classic it is simply never read."""
    here = Path(__file__).resolve().parent
    text = (here / "config.toml").read_text("utf-8")
    assert "[camera]" in text
    section = text[text.index("[camera]"):]
    section = section[:section.index("\n[", 1)]
    for key in ("enabled", "camera_hotkey", "device", "size", "fps",
                "mirror", "timer", "folder", "copy_to_clipboard",
                "edit_after_shot"):
        assert f"\n{key} = " in section, f"{key} is not a writable line"

    cfg = config_mod.load(here / "config.toml")
    assert cfg.camera.mirror is False
    assert cfg.camera.timer == 0
    ignored = (here / ".gitignore").read_text("utf-8")
    assert f"{cfg.camera.folder}/" in ignored, \
        "photographs of this room must not be committable"


def test_the_camera_controller_costs_nothing_until_the_key_is_pressed(
) -> None:
    """Constructing the controller must not import PyAV, Pillow or Tk. An
    owner who never presses the key pays nothing for the idea of it — and
    more to the point, importing a camera stack at startup is how a webcam
    light comes on for reasons nobody can explain."""
    import capture as cap

    controller = cap.Controller(lambda: None)
    assert controller.busy is False
    assert controller.recording is False
    # There is no camera until there is a window.
    assert controller._camera is None
    # A config with no [camera] section is a clear message, not a crash.
    try:
        controller._camera_cfg()
    except cap.CaptureError as e:
        assert "camera" in str(e), e
    else:
        raise AssertionError("a missing [camera] section was accepted")



def test_the_camera_shortcuts_survive_a_hebrew_layout() -> None:
    """`bind_all("<t>")` was measured doing NOTHING on this machine: with a
    non-Latin layout active Tk reports the physical T as a Hebrew letter,
    so three of the four shortcuts on the camera card were dead for the
    only person who has the app. The repo already had this rule written
    down for the dashboard's key capture — the KEYCODE survives a layout
    and the keysym does not — and the camera card obeys it too."""
    import capture as cap

    keys = cap.CameraWindow._KEYS
    assert keys[0x20] == "shoot" and keys[0x0D] == "shoot"
    assert keys[0x54] == "timer"        # T
    assert keys[0x4D] == "mirror"       # M
    assert keys[0x43] == "switch"       # C

    source = (Path(__file__).resolve().parent / "capture.py").read_text(
        "utf-8")
    assert 'bind_all("<KeyPress>"' in source
    for dead in ('bind_all("<t>"', 'bind_all("<m>"', 'bind_all("<c>"'):
        assert dead not in source, f"{dead} is dead on a Hebrew layout"

    class _Fake:
        _KEYS = cap.CameraWindow._KEYS

        def __init__(self):
            self.did = []

        def shoot(self):
            self.did.append("shoot")

        def _cycle_timer(self):
            self.did.append("timer")

        def _flip(self):
            self.did.append("mirror")

        def _switch(self):
            self.did.append("switch")

    class _Event:
        def __init__(self, keycode, keysym):
            self.keycode, self.keysym = keycode, keysym

    fake = _Fake()
    # The keysyms a Hebrew layout really reports, on the keycodes Windows
    # really sends.
    for keycode, keysym in ((0x54, "hebrew_aleph"), (0x4D, "hebrew_zain"),
                            (0x43, "hebrew_bet"), (0x20, "space")):
        cap.CameraWindow._on_key(fake, _Event(keycode, keysym))
    assert fake.did == ["timer", "mirror", "switch", "shoot"], fake.did

    # The numpad Enter, which Tk names and Windows numbers differently.
    cap.CameraWindow._on_key(fake, _Event(0, "KP_Enter"))
    assert fake.did[-1] == "shoot"

    # And a key nothing is bound to does nothing at all.
    before = list(fake.did)
    cap.CameraWindow._on_key(fake, _Event(0x51, "q"))
    assert fake.did == before


def test_one_press_of_escape_on_the_camera_card_is_one_press() -> None:
    """Esc means two things there — cancel the countdown, then close — and
    the pump polls GetAsyncKeyState at 66 Hz while a human tap holds the
    key for eighty milliseconds. Without a latch the first tick cancelled
    the timer and the third closed the window, so "Esc cancels the
    countdown" was true for about fifteen milliseconds. Measured
    2026-08-26 on a scripted 60 ms tap, which closed the window every
    time; this is the guard."""
    source = (Path(__file__).resolve().parent / "capture.py").read_text(
        "utf-8")
    at = source.index("class CameraWindow:")
    pump = source[source.index("    def run(self)", at):
                  source.index("    # -- painting --", at)]
    assert "held = esc_held()" in pump, "nothing remembers the key was down"
    assert "and not held" in pump, "the poll acts on every tick it is down"
    assert "held = down" in pump, "the latch is never released"


def test_the_mirror_flips_the_file_as_well_as_the_preview() -> None:
    """ONE image is the preview and the photo, so a mirror can only be
    applied in one place — the frame, as it arrives. A "mirror the preview
    only" setting is deliberately not offered: a preview that disagrees
    with the file it produces is the bug render_shot exists to prevent,
    wearing a lens."""
    import capture as cap
    from PIL import Image

    picture = Image.new("RGB", (4, 2), (0, 0, 0))
    picture.putpixel((0, 0), (255, 0, 0))       # a corner to follow

    class _Frame:
        """What PyAV hands back, as far as _take is concerned."""

        def reformat(self, width, height, format):   # noqa: A002
            assert (width, height) == (4, 2)
            assert format == "rgb24"

            class _Out:
                @staticmethod
                def to_image():
                    return picture.copy()

            return _Out()

    camera = cap.Camera("fake", size=(4, 2), preview=(4, 2))
    camera._take(_Frame())
    assert camera.live is True
    assert camera.latest.getpixel((0, 0)) == (255, 0, 0)
    assert camera.still().getpixel((0, 0)) == (255, 0, 0)
    assert camera.still() is not camera.latest, \
        "the photo has to be a private copy — the thread replaces the frame"

    camera.mirror = True
    camera._take(_Frame())
    assert camera.latest.getpixel((3, 0)) == (255, 0, 0), \
        "the preview is mirrored"
    assert camera.still().getpixel((3, 0)) == (255, 0, 0), \
        "...and so is the picture that gets written"
    assert camera.frames == 2



# ------------------------------------------------------- ink that has edges
#
# Pillow antialiases nothing, so the first version of this editor drew every
# diagonal as a staircase and every arrowhead with the shaft poking out the
# far side of the point. Both were visible at 1x and neither was caught by a
# test, because nothing here asserts what a picture LOOKS like. These do.


def test_the_ink_is_oversampled_so_a_diagonal_is_not_a_staircase() -> None:
    """The whole reason `_ink_stamp` draws big and shrinks: ImageDraw writes
    hard pixels. A hard-edged diagonal has two alpha values in it, 0 and
    255, and nothing in between — an antialiased one has a spread."""
    import capture as cap
    from PIL import Image

    base = Image.new("RGB", (240, 200), (255, 255, 255))
    diagonal = [{"kind": "pen", "colour": (224, 53, 43),
                 "points": [(20, 180), (220, 20)]}]
    out = cap.draw_marks(base, diagonal, (0, 0)).convert("RGB")
    reds = {px[0] for px in out.getdata()}
    partial = [v for v in reds if 60 < v < 250]
    assert len(partial) > 12, (
        f"only {len(partial)} intermediate values — the ink is not being "
        "antialiased, which is what a staircase looks like in a histogram")


def test_an_arrow_shaft_stops_at_the_notch_and_not_at_the_point() -> None:
    """The nub in the first screenshot of this editor: the line was drawn
    all the way to the tip and a 3 px stroke poked out past it. The shaft
    now ends at the notch, which is behind the tip along the shaft."""
    import math

    import capture as cap

    start, end = (100.0, 100.0), (300.0, 100.0)
    notch, head = cap.arrow_shape(start, end)
    assert len(head) == 4, "tip, two barbs and a notch — not a triangle"
    assert head[0] == end, "the first point of the head is the point"
    assert notch in head, "the notch is part of the outline, not just a stop"
    assert start[0] < notch[0] < end[0], (notch, "the shaft must stop short")
    # The barbs sit either side of the shaft, behind the tip.
    (_tx, _ty), (bx, by), _n, (cx, cy) = head
    assert bx < end[0] and cx < end[0]
    assert (by - 100.0) * (cy - 100.0) < 0, "both barbs on the same side"

    # Proportional to the STROKE...
    thin, _ = cap.arrow_shape(start, end, width=2)
    thick, _ = cap.arrow_shape(start, end, width=8)
    assert (end[0] - thick[0]) > (end[0] - thin[0])
    # ...and capped by the arrow's own LENGTH, so a short one is not a blob.
    short_notch, short_head = cap.arrow_shape((0.0, 0.0), (18.0, 0.0))
    reach = math.hypot(short_head[0][0] - short_head[1][0],
                       short_head[0][1] - short_head[1][1])
    assert reach <= 18.0 * 0.42, (reach, "the head outgrew its arrow")
    assert short_notch[0] > 0.0

    # A zero-length arrow is a click, and has no direction to point in.
    where, nothing = cap.arrow_shape((5.0, 5.0), (5.0, 5.0))
    assert nothing == [] and where == (5.0, 5.0)


def test_the_arrow_you_drag_is_the_arrow_you_get() -> None:
    """Tk draws the live preview and Pillow draws the file. Two arrowheads
    unless one set of numbers feeds both — and the drag is where you decide
    whether the arrow is right, so a preview that lies is worse than no
    preview."""
    import capture as cap

    source = (Path(__file__).resolve().parent / "capture.py").read_text(
        "utf-8")
    assert "arrowshape=tk_arrowshape()" in source, \
        "the canvas preview is back on a hard-coded arrowhead"
    neck, barb, half = cap.tk_arrowshape()
    assert barb == round(max(cap.ARROW_HEAD_MIN, cap.PEN_W * cap.ARROW_HEAD))
    assert 0 < neck < barb, (neck, barb)
    assert 0 < half < barb
    # It moves when the geometry moves, rather than being a second opinion.
    assert cap.tk_arrowshape(12)[1] > cap.tk_arrowshape(2)[1]


def test_one_mark_is_oversampled_once_and_then_reused() -> None:
    """A committed mark never changes — a crop only moves where it is
    pasted — so the expensive half happens once. Without this, every
    repaint of a picture carrying eight marks would redraw all eight at 4x,
    and the editor repaints on every hover."""
    import capture as cap
    from PIL import Image

    cap._INK_CACHE.clear()
    base = Image.new("RGB", (300, 240), (250, 250, 250))
    marks = [{"kind": "arrow", "colour": (224, 53, 43),
              "points": [(20, 220), (280, 30)]},
             {"kind": "box", "colour": (255, 214, 64),
              "points": [(40, 40), (200, 160)]}]
    cap.draw_marks(base, marks, (0, 0))
    assert len(cap._INK_CACHE) == 2, cap._INK_CACHE.keys()
    cap.draw_marks(base, marks, (0, 0))
    assert len(cap._INK_CACHE) == 2, "a second render made new entries"
    # A DIFFERENT origin is the same stamp in a different place.
    cap.draw_marks(base, marks, (25, 25))
    assert len(cap._INK_CACHE) == 2, "a crop re-rendered the ink"
    # And it is bounded, or a long session would keep every stroke for ever.
    assert cap._INK_CACHE_MAX >= 8


def test_the_oversample_backs_off_before_it_allocates_a_screenful() -> None:
    """4x a 2560x1440 rectangle is 59 MB and a third of a second, for one
    arrow. The factor drops as the rectangle grows, and never below 1."""
    import capture as cap

    assert cap.ink_scale(120, 90) == cap.INK_SS
    scales = [cap.ink_scale(w, h) for w, h in
              ((120, 90), (600, 400), (1280, 720), (2560, 1440))]
    assert scales == sorted(scales, reverse=True), scales
    assert min(scales) >= 1
    for width, height in ((120, 90), (600, 400), (1280, 720), (2560, 1440)):
        scale = cap.ink_scale(width, height)
        assert scale == 1 or width * height * scale * scale \
            <= cap.INK_SS_BUDGET, (width, height, scale)


# ------------------------------------------------------- a crop that goes back
#
# Cropping is the one edit that throws pixels away, and the one edit anybody
# ever overshoots. It goes both ways now: the tool works in the whole
# picture that was TAKEN, so what was cut is still there to drag back to.


def test_a_crop_works_in_the_picture_that_was_taken_not_what_is_left() -> None:
    import capture as cap

    class _Stub:
        kind = "photo"
        origin_box = (100, 100, 900, 700)
        box = (300, 250, 600, 500)
        _vx, _vy, _vw, _vh = -1920, 0, 4480, 1440

    stub = _Stub()
    # A PHOTO is bounded by the photo: behind it is the desktop the camera
    # card was sitting on, and re-framing onto that hands you a picture of
    # your own wallpaper.
    assert cap.ShotWindow._crop_stage(stub) == stub.origin_box
    stub.box = stub.origin_box
    assert cap.ShotWindow._crop_stage(stub) == stub.origin_box
    stub.origin_box = None
    assert cap.ShotWindow._crop_stage(stub) == stub.box

    # A SCREEN CAPTURE is bounded by the frozen screen, which is to say
    # not bounded at all: every pixel is still there, so the crop tool is
    # "take the shot again" rather than "make this smaller".
    stub.kind = "shot"
    stub.box = (300, 250, 600, 500)
    stub.origin_box = (100, 100, 900, 700)
    assert cap.ShotWindow._crop_stage(stub) == (-1920, 0, 2560, 1440)
    assert cap.ShotWindow._whole_screen(stub) == (-1920, 0, 2560, 1440)

    source = (Path(__file__).resolve().parent / "capture.py").read_text(
        "utf-8")
    press = source[source.index("    def _edit_press"):
                   source.index("    def _edit_drag")]
    assert "self._crop_stage()" in press, \
        "the crop cannot be STARTED outside the picture it may end outside"
    release = source[source.index("    def _edit_release"):
                     source.index("    def _crop_stage")]
    assert "clamp_box((start[0], start[1], end[0], end[1]),\n" \
           "                            self._crop_stage())" in release, \
        "the crop is still clamped to what is left rather than to the whole"


def test_the_selection_drag_does_not_survive_into_the_first_click() -> None:
    """A real bug, found by driving the editor rather than by reading it.
    `_on_release` ends the selection drag and hands over to the editor
    WITHOUT clearing `_start`, so the very first press afterwards — the
    toolbar button you reach for — released into `_edit_release` with the
    selection's own start point still pending, and drew a stroke from it.
    With the crop tool picked it silently re-cropped the picture to
    somewhere under the toolbar, which is what "the crop does not work"
    looks like from the outside. Once per capture, always on the first
    click."""
    source = (Path(__file__).resolve().parent / "capture.py").read_text(
        "utf-8")
    chose = source[source.index("    def _chose(self, box, path)"):
                   source.index("    def _first_save")]
    assert "self._start = None" in chose,         "the selection drag is left pending after it ends"
    press = source[source.index("    def _edit_press"):
                   source.index("    def _edit_drag")]
    toolbar = press[:press.index("return self._activate(name)")]
    assert "self._start = None" in toolbar,         "a press on the toolbar can still finish a stroke nobody started"


def test_growing_a_crop_brings_back_the_marks_that_were_outside_it() -> None:
    """The reason growing one back is nearly free: marks are stored in
    VIRTUAL-SCREEN coordinates and a crop is one rectangle changing. The
    ink outside it was never deleted, only left out of the render — so it
    comes back with the pixels it was drawn on."""
    import capture as cap
    from PIL import Image

    screen = Image.new("RGB", (400, 300), (255, 255, 255))
    mark = [{"kind": "box", "colour": (224, 53, 43),
             "points": [(30, 30), (110, 110)]}]

    def has_ink(image) -> bool:
        return any(px[0] > px[2] + 40 for px in image.convert("RGB").getdata())

    whole = cap.render_shot(screen, (0, 0, 400, 300), mark, None, (0, 0))
    assert has_ink(whole), "the mark is not on the picture at all"

    # Cropped away from it: the ink is gone from what you can see...
    tight = cap.render_shot(screen, (200, 150, 380, 280), mark, None, (0, 0))
    assert not has_ink(tight), "a crop that excluded the mark still shows it"

    # ...and the moment the rectangle grows back over it, it is there again,
    # in the same place on the pixels it was drawn on.
    grown = cap.render_shot(screen, (20, 20, 380, 280), mark, None, (0, 0))
    assert has_ink(grown), "growing the crop back did not bring the ink back"
    assert grown.size == (360, 260)


# ------------------------------------------------- chords, and the Windows key


def test_three_and_four_key_chords_round_trip() -> None:
    """Nothing had to be added for these — Binding.mods was always a set —
    but nothing said so either, and a capability with no test is a
    capability that gets optimised away."""
    import hotkey as hotkey_mod

    for text, mods in (("ctrl+shift+s", {0x11, 0x10}),
                       ("ctrl+shift+alt+f6", {0x11, 0x10, 0x12}),
                       ("win+shift+s", {0x5B, 0x10})):
        binding = hotkey_mod.parse_binding(text)
        assert set(binding.mods) == mods, (text, binding)
        # One spelling per chord, or config.toml could hold two names for
        # one key and the duplicate check would miss it.
        assert hotkey_mod.binding_name(binding) == text, text
        shuffled = "+".join(reversed(text.split("+")))
        try:
            other = hotkey_mod.parse_binding(shuffled)
        except ValueError:
            continue                    # the trigger moved; fine
        assert hotkey_mod.binding_name(other) != text or other == binding

    # The dialog builds them from what Windows says is held, so it can
    # capture as many modifiers as the keyboard has.
    assert hotkey_mod.binding_name_from_event(
        "s", 0x53, probe=lambda vk: None,
        mods={0x11, 0x10, 0x12}) == "ctrl+shift+alt+s"


def test_the_windows_key_can_be_held_but_never_fired_on() -> None:
    """Held, it is an ordinary modifier. As a TRIGGER it is a key nothing
    can take: a tap of Win that nothing consumed opens Start, and the only
    way to stop that would be to swallow the key that opens Start."""
    import hotkey as hotkey_mod

    assert hotkey_mod.parse_binding("win+shift+s").mods == frozenset(
        {0x5B, 0x10})
    assert hotkey_mod.binding_name(
        hotkey_mod.parse_binding("shift+win+s")) == "win+shift+s", \
        "Win is written first, the way Windows writes it"
    for bad in ("win", "shift+win", "ctrl+alt+win"):
        try:
            hotkey_mod.parse_binding(bad)
        except ValueError as e:
            assert "Windows key" in str(e), e
        else:
            raise AssertionError(f"{bad!r} was accepted as a binding")
    # And the capture dialog will not offer a bare Win either, or it would
    # write a key into config.toml that the next launch refuses.
    assert hotkey_mod.binding_name_from_event(
        "Super_L", 0x5B, probe=lambda vk: 0x5B) is None


def test_a_windows_chord_is_the_one_tap_the_app_takes_away() -> None:
    """THE EXCEPTION TO "tap keys are not swallowed", and the whole reason
    Win+Shift+S can be this app's. Every Windows-key chord is a shortcut
    the shell already answers, so letting one through would fire the app
    AND Windows — the capture overlay and the Snipping Tool, together.

    Measured on this machine 2026-08-26, three runs of a bare hook:
      Win+Shift+S with the hook watching -> "Snipping Tool Overlay" opens
      Win+Shift+S with the S swallowed   -> nothing opens; the chord is ours
      Win tapped alone, same hook up     -> Start opens, exactly as before
    Nothing has to be disabled in Windows for this and no registry key is
    involved. What this test guards is the half that lives here."""
    import hotkey as hotkey_mod

    fired = []
    machine = hotkey_mod.PTTStateMachine(
        {hotkey_mod.vk_for("right ctrl"): "he"},
        on_start=lambda *a: None, on_stop=lambda *a: None,
        on_abort=lambda *a: None,
        taps={hotkey_mod.parse_binding("win+shift+s"): "capture",
              hotkey_mod.parse_binding("ctrl+shift+s"): "record"},
        on_tap=lambda action: fired.append(action))

    # Sided codes, because that is all the hook ever reports.
    assert machine.handle("down", 0x5B, False) is False, "Win itself passes"
    assert machine.handle("down", 0xA0, False) is False, "and so does shift"
    assert machine.handle("down", 0x53, False) is True, "the S is taken"
    assert fired == ["capture"], fired
    assert machine.handle("down", 0x53, False) is True, "auto-repeat leaks"
    assert machine.handle("up", 0x53, False) is True, \
        "a key that never went down must not come up"
    assert machine.handle("up", 0xA0, False) is False
    assert machine.handle("up", 0x5B, False) is False, \
        "swallowing Win itself would cost the Start menu"

    # The same trigger under ordinary modifiers is NOT taken: the house
    # rule is that a tap fires the action and still reaches the app.
    fired.clear()
    machine.handle("down", 0xA2, False)
    machine.handle("down", 0xA0, False)
    assert machine.handle("down", 0x53, False) is False, \
        "a ctrl chord was swallowed — that is not this app's bargain"
    assert fired == ["record"], fired
    assert machine.handle("up", 0x53, False) is False
    machine.handle("up", 0xA2, False)
    machine.handle("up", 0xA0, False)

    # And a bare S, which is nobody's chord, passes through untouched.
    fired.clear()
    assert machine.handle("down", 0x53, False) is False
    assert fired == [], fired


def test_the_shipped_screenshot_key_is_the_one_windows_uses() -> None:
    """It is the point of the exercise: Win+Shift+S opens THIS editor."""
    import main as main_mod

    cfg = config_mod.load(Path(__file__).resolve().parent / "config.toml")
    assert cfg.capture_hotkey == "win+shift+s", cfg.capture_hotkey
    assert "capture_hotkey" in config_mod.CHORD_FIELDS
    _hotkeys, taps, _latch, _pause = main_mod.App.bindings(cfg)
    assert taps[parse_binding("win+shift+s")] == "capture", taps
    # The trigger is a LETTER now, which the lookup box must still be told
    # about — main._popup_key answers for it before popup.py sees it.
    assert main_mod.App._vk_of(taps, "capture") == vk_for("s")



# --------------------------------------------------- the card in the corner
#
# The editor used to open over the whole screen after every capture. That is
# a modal dialog in nicer clothes: it makes the common case — drag, paste,
# carry on — pay for the rare one. It is a corner card now, and the two
# things that make a notification a notification rather than an interruption
# are tested here: it does not take the keyboard, and it does not vanish
# while the hand is reaching for it.
#
# There is more than one of them now. The key used to go DEAD for as long
# as a card was up: press it again inside those five seconds and the app
# answered the screenshot key by logging "already up" and doing nothing —
# and the reason was a Tcl interpreter the card owned, which is nobody's
# business but ours. So the cards STACK: oldest at the top, newest at the
# bottom, each on its own clock. The arithmetic that puts them there is
# pure, and it is tested first, because a stack whose only card is not
# exactly where the only card used to be is a regression in a feature's
# clothes.


def test_a_stack_of_one_is_exactly_the_card_in_the_corner() -> None:
    """The reduction property, and the reason all the rest of this is safe.

    A stack is a GENERALISATION of the card that was already there, so
    with one card in it the answer has to be the old answer, to the pixel,
    in every corner. One capture at a time is the overwhelmingly common
    case; if this holds, nothing about it can have moved, and if it does
    not, nothing else measured here is worth measuring.
    """
    import capture as cap

    size = (cap.TOAST_W, cap.TOAST_H)
    for box in ((0, 0, 2560, 1400), (-1920, 0, 0, 1040), (0, 0, 1366, 728)):
        for corner in ("top-left", "top-right", "bottom-left",
                       "bottom-right"):
            assert cap.stack_at(box, size, corner, 0, 1) == \
                cap.corner_at(box, size, corner), (box, corner)


def test_the_newest_card_takes_the_bottom_corner_and_pushes_the_rest_up(
) -> None:
    """Bottom-right is the shipped corner, and down there the card that
    just appeared is the one IN the corner while the older one moves up.

    That way round because the corner is where the eye already goes — it
    is where the only card has always been — so the capture you just took
    is never the one you have to look for. The gap between them is real
    space and not a border: two cards touching read as one tall card with
    a seam in it.
    """
    import capture as cap

    box, size = (0, 0, 2560, 1400), (cap.TOAST_W, cap.TOAST_H)
    step = cap.TOAST_H + cap.TOAST_GAP
    x0, y0 = cap.stack_at(box, size, "bottom-right", 0, 2)
    x1, y1 = cap.stack_at(box, size, "bottom-right", 1, 2)
    assert x0 == x1, "a stack is one column, not a staircase"
    assert y0 < y1, "the older card must be the higher one"
    assert y1 - y0 == step, (y0, y1, step)
    assert y1 == cap.corner_at(box, size, "bottom-right")[1], \
        "the newest card is not where the only card would have been"
    assert cap.TOAST_GAP > 0, "cards flush against each other read as one"


def test_the_oldest_card_keeps_the_top_corner_and_the_rest_hang_below(
) -> None:
    """The same rule from the other end: a stack grows AWAY from the
    corner it is anchored to, so it can never need room the screen has
    already run out of.

    Oldest at the top and newest at the bottom holds in every corner —
    what the corner decides is which END of the column is pinned. Up here
    the pinned end is the top, so the oldest card is the one that never
    moves and each new one appears below it, which is the direction
    Windows' own notifications grow.
    """
    import capture as cap

    box, size = (0, 0, 2560, 1400), (cap.TOAST_W, cap.TOAST_H)
    step = cap.TOAST_H + cap.TOAST_GAP
    for corner in ("top-left", "top-right"):
        x0, y0 = cap.stack_at(box, size, corner, 0, 2)
        x1, y1 = cap.stack_at(box, size, corner, 1, 2)
        assert x0 == x1, corner
        assert y0 == cap.corner_at(box, size, corner)[1], \
            "the oldest card left the corner it was anchored to"
        assert y1 == y0 + step, (corner, y0, y1)


def test_a_full_stack_stays_inside_the_work_area() -> None:
    """A card is drawn where it is told, so an arithmetic slip here does
    not look like a bug — it looks like a card half under the taskbar, or
    off the top of the screen where it can be neither read nor clicked.

    Checked on the three panels this desk has seen — 1440, 1080 and a
    768-tall laptop screen — in all four corners, at every depth up to the
    shipped `toast_stack` of four. The box IS the work area, which is what
    keeps the bottom corners off the taskbar.
    """
    import capture as cap

    size = (cap.TOAST_W, cap.TOAST_H)
    margin, step = cap.CORNER_MARGIN, cap.TOAST_H + cap.TOAST_GAP
    for width, height in ((2560, 1440), (1920, 1080), (1366, 768)):
        box = (0, 0, width, height)
        for corner in ("top-left", "top-right", "bottom-left",
                       "bottom-right"):
            for count in range(1, 5):
                spots = [cap.stack_at(box, size, corner, i, count)
                         for i in range(count)]
                for x, y in spots:
                    assert x >= margin, (width, corner, x)
                    assert x + cap.TOAST_W <= width - margin, (width, x)
                    assert y >= margin, (height, corner, count, y)
                    assert y + cap.TOAST_H <= height - margin, \
                        (height, corner, count, y)
                ys = [y for _x, y in spots]
                assert ys == sorted(ys), (corner, ys)
                assert all(b - a == step for a, b in zip(ys, ys[1:])), ys


def test_the_stack_on_the_left_hand_monitor_keeps_its_negative_x() -> None:
    """The second monitor on this desk sits to the LEFT of the primary
    one, which puts its entire work area at negative x. That is the layout
    this app documents, because it is the one it was built on.

    Every coordinate in capture.py is virtual-screen, so a clamp to zero —
    the reflex when a number looks wrong — would pile every card taken
    over there onto the left edge of the primary monitor. A card belongs
    to the screen its capture came from, wherever that screen is.
    """
    import capture as cap

    size = (cap.TOAST_W, cap.TOAST_H)
    left = (-1920, 0, 0, 1040)
    right = (0, 0, 1920, 1040)
    for corner in ("bottom-left", "top-left"):
        for index in range(3):
            x, y = cap.stack_at(left, size, corner, index, 3)
            assert x == -1920 + cap.CORNER_MARGIN, (corner, x)
            assert x < 0, "the card was clamped onto the primary monitor"
            # the column is the same height either side of zero
            assert y == cap.stack_at(right, size, corner, index, 3)[1]
    for corner in ("bottom-right", "top-right"):
        for index in range(3):
            x, _y = cap.stack_at(left, size, corner, index, 3)
            assert x == 0 - cap.TOAST_W - cap.CORNER_MARGIN, (corner, x)
            assert x < 0, "the card was clamped onto the primary monitor"


def test_two_monitors_carry_two_stacks_and_not_one() -> None:
    """A card belongs to the monitor its capture came from — that is what
    `corner_at` has always promised — so two screens are two INDEPENDENT
    columns, each counted from its own corner.

    Interleaving is the case that gets this wrong: a capture on the left
    screen, one on the right, one on the left, one on the right. Lay all
    four out as a single column and the second monitor's cards sit a
    card-height too high, over whatever is up there. And the answers come
    back in the order they were asked for, because the caller holds one
    card per position and has no way to re-sort them.
    """
    import capture as cap

    size = (cap.TOAST_W, cap.TOAST_H)
    a = (0, 0, 2560, 1400)
    b = (2560, 0, 4480, 1040)
    corner = "bottom-right"
    out = cap.stack_layout([a, b, a, b], size, corner)
    assert len(out) == 4, out
    assert out[0] == cap.stack_at(a, size, corner, 0, 2), out
    assert out[2] == cap.stack_at(a, size, corner, 1, 2), out
    assert out[1] == cap.stack_at(b, size, corner, 0, 2), out
    assert out[3] == cap.stack_at(b, size, corner, 1, 2), out
    # The columns do not know about each other: take the other screen's
    # cards away entirely and nothing over here moves.
    assert [out[1], out[3]] == cap.stack_layout([b, b], size, corner), out
    assert [out[0], out[2]] == cap.stack_layout([a, a], size, corner), out


def test_a_card_expiring_from_the_middle_closes_the_gap() -> None:
    """Every card has its own clock, so they do not go in the order they
    arrived: hold the pointer on the middle one and the two either side of
    it run out first. What is left has to be a STACK again — one column
    with no hole in it — and the newest card must not jump while that
    happens, because the newest card is the one being looked at.
    """
    import capture as cap

    size = (cap.TOAST_W, cap.TOAST_H)
    box, corner = (0, 0, 2560, 1400), "bottom-right"
    three = cap.stack_layout([box, box, box], size, corner)
    survivors = cap.stack_layout([box, box], size, corner)   # the 1st and 3rd
    assert survivors == [cap.stack_at(box, size, corner, 0, 2),
                         cap.stack_at(box, size, corner, 1, 2)], survivors
    assert survivors[1] == three[2], \
        "the newest card moved when an older one above it went"
    assert survivors[0] == three[1], \
        "the gap the middle card left was not closed"


def test_a_screen_is_told_how_many_cards_it_can_hold() -> None:
    """`toast_stack` caps the deck at one number and the SCREEN caps it at
    another; the smaller wins. What makes that worth a function is that
    the two have to agree with `stack_at`: a screen said to hold n cards
    must be a screen where n are all fully visible and n+1 are not, or the
    cap is a number that means nothing.

    Measured against the panels this runs on. A 1440 and a 1080 monitor
    each hold more than `TOAST_STACK_MAX` allows, so up there the cap is
    the deck's own; a 768-tall laptop screen holds fewer, so down there it
    is the screen's. And it never answers zero however small the box —
    a capture that leaves nothing behind at all is the failure the card
    exists to avoid, so the last card is shown even where it does not fit.
    """
    import capture as cap

    size = (cap.TOAST_W, cap.TOAST_H)
    margin = cap.CORNER_MARGIN
    for height in (1440, 1080, 768):
        box = (0, 0, 1920, height)
        fits = cap.stack_fits(box, size)
        assert fits >= 1, (height, fits)
        for corner in ("top-left", "bottom-right"):
            top = cap.stack_at(box, size, corner, 0, fits)[1]
            last = cap.stack_at(box, size, corner, fits - 1, fits)[1]
            assert top >= margin, (height, corner, fits, top)
            assert last + cap.TOAST_H <= height - margin, \
                (height, corner, fits, last)
            over_top = cap.stack_at(box, size, corner, 0, fits + 1)[1]
            over_end = cap.stack_at(box, size, corner, fits, fits + 1)[1]
            assert (over_top < margin
                    or over_end + cap.TOAST_H > height - margin), \
                f"{height} px was said to hold only {fits} cards"
    assert cap.stack_fits((0, 0, 2560, 1440), size) >= cap.TOAST_STACK_MAX
    assert cap.stack_fits((0, 0, 1920, 1080), size) >= cap.TOAST_STACK_MAX
    assert cap.stack_fits((0, 0, 1366, 768), size) < cap.TOAST_STACK_MAX, \
        "the laptop panel no longer runs out first — check TOAST_STACK_MAX"
    assert cap.stack_fits((0, 0, 200, 100), size) == 1, \
        "a screen with no room was told to show no card at all"


def test_the_corner_card_never_takes_the_keyboard() -> None:
    """A capture taken mid-sentence must not eat the next keystroke.

    Measured while building this: with the window withdrawn, overrideredirect,
    topmost AND carrying WS_EX_NOACTIVATE, the foreground still moved to
    TkTopLevel at `update_idletasks()`. The flag stops a later CLICK from
    activating the card and does not stop that first grab, so the grab is
    undone instead — which is allowed, because at that instant this process
    owns the foreground.

    WITH A STACK UP, "whatever had the keyboard before this card" can be
    ONE OF OUR OWN CARDS: the window in front when the second capture
    lands may well be the first card. Handing the keyboard "back" to that
    would be the deck passing focus round its own windows while the
    sentence being typed underneath goes nowhere — so an HWND the deck
    owns is remembered as nothing at all.
    """
    import ctypes as ct
    import inspect

    import capture as cap
    from PIL import Image

    source = (Path(__file__).resolve().parent / "capture.py").read_text(
        "utf-8")
    build = source[source.index("class ShotToast:"):]
    build = build[build.index("    def _build"):build.index("    # -- layout")]
    assert "GetForegroundWindow()" in build, \
        "nothing remembers what had the keyboard before the card"
    assert build.index("GetForegroundWindow()") < build.index("tk.Canvas"), \
        "read it BEFORE Tk touches anything, or the answer is the card"
    assert "no_activate(root)" in build
    assert build.index("no_activate(root)") < build.index("root.deiconify"), \
        "the flag has to be on the window before it is first shown"
    assert "give_focus_back" in build

    # The two-card case, asserted on the logic rather than by standing up
    # two real windows: a test that needs the foreground to hold still
    # across two window builds fails for reasons nothing to do with this.
    params = inspect.signature(cap.ShotToast.__init__).parameters
    for name in ("master", "owned"):
        assert name in params, (name, list(params))
        assert params[name].kind is inspect.Parameter.KEYWORD_ONLY, name
    assert params["owned"].default == (), params["owned"].default
    assert "owned" in build, "the card cannot tell our windows from yours"
    assert "self._had_focus = 0" in build, \
        "a card that finds one of OUR windows in front has to remember " \
        "nothing, rather than remember a sibling card"
    assert build.index("self._had_focus = 0") < build.index("tk.Canvas"), \
        "the sibling has to be filtered out before the window is built"

    user32 = ct.WinDLL("user32")
    before = user32.GetForegroundWindow()
    toast = cap.ShotToast(Image.new("RGB", (300, 200), (30, 50, 90)),
                          (100, 100, 400, 300), saved=None, seconds=1)
    try:
        after = user32.GetForegroundWindow()
        assert after == before, (
            "the card took the foreground: a notification that steals focus "
            "is an interruption with a countdown on it")
    finally:
        toast.done.set()
        toast.run()


def test_the_cards_clock_pauses_under_the_pointer() -> None:
    """Five seconds is not long when what you are deciding is "did that
    capture the bit I meant". A card that vanishes mid-reach is worse than
    no card, so the clock holds while the pointer is on it — and RESUMES
    rather than restarting, so a card brushed by a passing pointer does not
    outstay its welcome.

    THE CLOCK MOVED, and the slice below is shaped around where it went.
    One frame of one card's countdown is `tick` now, so a deck can drive N
    cards off one pump and each still runs its own clock; `run` keeps its
    body and calls it, and `tick` is defined immediately AFTER `run`. That
    is why this reads from `def run` to the END OF THE FILE instead of to
    the end of a method — narrow it back to `run` alone and it is looking
    at a frame that no longer contains the arithmetic.

    Do not widen it to the whole class either. `_build` contains the
    literal `self._left = float(self.seconds)`, which is a card being
    WOUND UP once when it is made; a class-wide slice would read that as
    the clock restarting and fail on correct code."""
    source = (Path(__file__).resolve().parent / "capture.py").read_text(
        "utf-8")
    at = source.index("class ShotToast:")
    pump = source[source.index("    def run(self)", at):]
    assert "self._left -= elapsed" in pump, "the clock does not drain"
    assert "if not self._inside:" in pump, "it drains under the pointer too"
    assert "self._left = float(self.seconds)" not in pump, \
        "the clock restarts instead of resuming"
    assert "    def tick(self" in pump, \
        "tick is gone, or it is no longer defined after run — either way " \
        "the slice above is measuring the wrong lines"


def test_the_corner_card_does_not_hold_the_screen() -> None:
    """`busy` NARROWED, and this is the line it narrowed to.

    It used to mean "a capture is in progress", and a card in a corner
    counted — so for five seconds after every screenshot the key that
    takes screenshots did nothing. It means "a window that OWNS THE
    SCREEN is up" now: the selector, the editor, the camera, the clip bar.
    A card owns 384x96 pixels of one corner and owns nothing else.

    The mechanism is what is asserted, because it is what made the old
    meaning unavoidable: `_offer` used to call `toast.run()`, and that
    call does not return until the card is gone, so the flag the flow
    holds could not be released before then however it was defined. The
    card goes to the deck and `_offer` returns.
    """
    import inspect

    import capture as cap

    offer = inspect.getsource(cap.Controller._offer)
    assert "toast.run()" not in offer, \
        "_offer still blocks on the card, so the key is dead while it is up"
    for name in ("_take_screen", "_free_screen", "_edit_flow"):
        assert hasattr(cap.Controller, name), name
    assert "_take_screen" in inspect.getsource(cap.Controller.begin_shot), \
        "the screen is claimed somewhere other than where it is taken"
    assert "_free_screen" in inspect.getsource(cap.Controller._shot_flow), \
        "the selector's flow never gives the screen back"
    # The editor a card can still open runs on a thread of its own. Built
    # on the deck's pump it would own the deck's interpreter, which is the
    # Tcl_AsyncDelete abort AGENTS.md spends a paragraph on.
    assert "capture-card-action" in inspect.getsource(cap.Controller), \
        "the card's save/edit branch has no thread of its own"
    for name in ("start", "add", "hush", "unhush", "stop"):
        assert callable(getattr(cap.ShotCards, name)), name
    assert isinstance(cap.ShotCards.count, property), \
        "count has to be readable from the hook thread without a call"
    # Nothing has been pressed, so nothing owns the screen.
    assert cap.Controller(lambda: None).busy is False


def test_the_corner_card_is_not_in_the_next_screenshot() -> None:
    """AGENTS.md's rule, which until now nothing enforced: our own windows
    must not appear in the owner's captures. `hide_from_capture` sets
    WDA_EXCLUDEFROMCAPTURE, the same flag the clip bar and the status dot
    carry, and grep found it in neither this test file nor this card.

    It was survivable while there was only ever one card and the key was
    dead underneath it. It is not survivable now, because pressing the key
    again while a card is up IS the feature: without the flag the second
    screenshot has the first one's card sitting in the corner of it, and
    the third has two.
    """
    source = (Path(__file__).resolve().parent / "capture.py").read_text(
        "utf-8")
    build = source[source.index("class ShotToast:"):]
    build = build[build.index("    def _build"):build.index("    # -- layout")]
    assert "hide_from_capture(" in build, \
        "the card will be photographed by the next capture"


def test_a_closed_deck_of_cards_leaves_no_interpreter_to_free() -> None:
    """The abort AGENTS.md documents, on the one window nothing watches.

    A Tk widget tree is CYCLIC, so dropping the last reference to a card
    never frees it — only the collector does, on whichever thread happens
    to trip the allocation threshold. Freeing it there runs
    Tcl_DeleteInterp on a thread that did not build the interpreter, and
    Tcl answers with a panic: abort, no traceback, nothing in app.log.
    The two tests that assert this already both drive visual_qa's ask
    card. The deck is a NEW long-lived interpreter with N Toplevels
    hanging off it on a thread of its own, which is exactly the shape
    that aborts, and it was covered by nothing at all.

    So the deck's own thread has to bury the deck, and it has to have
    done it by the time `stop()` has returned and that thread has ended.
    What proves it is that the Tk objects are dead HERE with the collector
    switched off — nothing else could have freed them — and that a collect
    run from a thread that never touched Tcl then finds none of ours left.
    The collect is deliberately AFTER that check: if anything were still
    garbage, running it here is the abort rather than a failed assertion.
    """
    import inspect

    import capture as cap
    from PIL import Image

    root = _tk_or_skip()
    if root is None:
        return
    root.destroy()
    del root
    gc.collect()

    def windows() -> int:
        """Tk windows alive in this process right now.

        Counted rather than looked up through the deck's own attributes,
        so this asks the question the crash asks — is an interpreter still
        allocated — without knowing anything about how the deck holds it.
        The list of strong references this builds is dropped with the
        frame, and it frees nothing that was reachable before it.
        """
        found = 0
        for obj in gc.get_objects():
            kind = type(obj)
            if kind.__module__ == "tkinter" and kind.__name__ in (
                    "Tk", "Toplevel"):
                found += 1
        return found

    # The deck reads `toast_stack` off whatever this hands it, fresh, the
    # same way everything else in that module reads its settings.
    cfg = config_mod.load(Path(__file__).resolve().parent / "config.toml")
    deck = cap.ShotCards(lambda: cfg.capture)
    gc.disable()                 # only explicit collects: we pick the thread
    try:
        empty = windows()
        assert deck.start() is True, "the deck would not come up"
        wanted = inspect.signature(cap.ShotCards.add).parameters
        extras = {name: value for name, value in
                  (("saved", None), ("corner", "bottom-right"),
                   ("seconds", 30), ("copied", False))
                  if name in wanted}
        deck.add(Image.new("RGB", (320, 160), (30, 30, 30)),
                 (100, 100, 420, 260), **extras)
        deadline = time.monotonic() + 30
        while deck.count < 1 and time.monotonic() < deadline:
            time.sleep(0.02)
        assert deck.count == 1, "the card never came up"
        assert any(t.name == "capture-cards" for t in threading.enumerate()), \
            [t.name for t in threading.enumerate()]
        # the root that is never shown, and one Toplevel for the card
        assert windows() >= empty + 2, (empty, windows())

        deck.stop()
        while (any(t.name == "capture-cards" for t in threading.enumerate())
               and time.monotonic() < deadline):
            time.sleep(0.02)
        assert not any(t.name == "capture-cards"
                       for t in threading.enumerate()), \
            "the deck's thread outlived stop()"

        left = windows() - empty
        if left:
            print(f"    (leak: {left} Tk windows survived stop())",
                  flush=True)
        assert left == 0, (
            f"{left} Tk objects were still allocated after stop() with the "
            "collector switched off, so the deck did not bury its own "
            "interpreter — whichever thread next trips the GC threshold "
            "will, and Tcl aborts the process with no traceback when it "
            "does")

        # ...and now a thread that never touched Tcl runs a collect. It is
        # deliberately after the check above: if anything WERE still
        # garbage, this line is the abort rather than a failed assertion.
        freed: list = []
        stranger = threading.Thread(target=lambda: freed.append(gc.collect()),
                                    name="not-the-deck")
        stranger.start()
        stranger.join(30)
        assert freed, "the collecting thread never finished"
        assert windows() == empty, (empty, windows())
    finally:
        gc.enable()
        deck = None

    # A module global is not garbage — it is reachable — so it sails past
    # every collect above and still kills the app later, on whichever
    # thread drops the last reference. skin\wave.py did exactly that with
    # one cache line, and the suite could not see it.
    held = [name for name, value in vars(cap).items()
            if type(value).__module__ in ("tkinter", "_tkinter", "PIL.ImageTk")
            or type(value).__name__ in ("Tk", "Toplevel", "PhotoImage")]
    assert not held, f"capture.py still holds Tk objects: {held}"


def test_the_card_offers_save_only_when_there_is_nothing_saved() -> None:
    """A Save button beside a file that already exists is a button that
    lies; with the file already written the useful offer is the folder."""
    import capture as cap

    class _Stub:
        saved = None

    stub = _Stub()
    assert cap.ShotToast._buttons(stub) == ("edit", "save", "copy", "close")
    stub.saved = Path("captures") / "shot 2026-08-26 20-00-00.png"
    assert cap.ShotToast._buttons(stub) == ("edit", "folder", "copy", "close")


def test_every_control_on_the_card_is_hit_where_it_is_drawn() -> None:
    import capture as cap

    class _Stub:
        saved = None
        _buttons = cap.ShotToast._buttons

    spots = cap.ShotToast._spots(_Stub())
    assert set(spots) == {"edit", "save", "copy", "close", "edit_thumb"}
    for name, (x0, y0, x1, y1) in spots.items():
        assert cap.hit(spots, (x0 + x1) // 2, (y0 + y1) // 2) == name, name
        assert 0 <= x0 < x1 <= cap.TOAST_W, name
        assert 0 <= y0 < y1 <= cap.TOAST_H, name
    boxes = list(spots.values())
    for index, a in enumerate(boxes):
        for b in boxes[index + 1:]:
            assert (a[2] <= b[0] or b[2] <= a[0]
                    or a[3] <= b[1] or b[3] <= a[1]), (a, b)
    # The thumbnail is the biggest button on the card, because clicking the
    # picture to work on the picture needs no label.
    thumb = spots["edit_thumb"]
    area = (thumb[2] - thumb[0]) * (thumb[3] - thumb[1])
    for name in ("edit", "save", "copy", "close"):
        x0, y0, x1, y1 = spots[name]
        assert (x1 - x0) * (y1 - y0) < area, name


def test_a_capture_reaches_the_clipboard_even_when_it_reaches_no_disk(
) -> None:
    """`always_save = false` gives up the file and keeps the clipboard, and
    the order matters: the clipboard write comes after the save so a folder
    that cannot be written to cannot also cost you the paste."""
    import shutil
    import tempfile

    import capture as cap
    from PIL import Image

    tmp = Path(tempfile.mkdtemp(prefix="capture-nosave-"))
    try:
        class _Stub:
            folder = str(tmp)
            kind = "shot"
            copy = False          # the clipboard is somebody else's, in a test
            save = False
            saved_path = None
            on_saved = None
            said = []

            def picture(self):
                return Image.new("RGB", (40, 30), (10, 20, 30))

            def say(self, text, ttl_ms=0):
                self.said.append(text)

        stub = _Stub()
        cap.ShotWindow._first_save(stub)
        assert stub.saved_path is None, "a file was written anyway"
        assert list(tmp.glob("*")) == [], list(tmp.glob("*"))
        assert any("not saved" in s for s in stub.said), stub.said

        stub.save = True
        cap.ShotWindow._first_save(stub)
        assert stub.saved_path is not None
        assert stub.saved_path.exists()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_the_after_shot_settings_parse_and_are_bounded() -> None:
    import shutil
    import tempfile
    tmp = Path(tempfile.mkdtemp(prefix="capture-toast-"))
    path = tmp / "config.toml"
    try:
        path.write_text(
            'hotkey = "right ctrl"\n'
            "[capture]\n"
            'after_shot = "editor"\n'
            'toast_corner = "top-left"\n'
            "toast_seconds = 12\n"
            "toast_stack = 8\n"
            "always_save = true\n", "utf-8")
        cap = config_mod.load(path).capture
        assert cap.after_shot == "editor"
        assert cap.toast_corner == "top-left"
        assert cap.toast_seconds == 12
        assert cap.toast_stack == 8
        assert cap.always_save is True

        defaults = config_mod.CaptureConfig()
        assert defaults.after_shot == "toast", \
            "the editor is an offer, not a step"
        assert defaults.always_save is False
        assert defaults.toast_seconds == 5
        # Four, not one and not eight: one is the old dead key back again,
        # and a screen with eight cards on it is a wall. Four is what a
        # 768-tall laptop panel can show without the stack having to be
        # trimmed for the screen instead of for the setting.
        assert defaults.toast_stack == 4

        for key, value, word in (("after_shot", '"maybe"', "after_shot"),
                                 ("toast_corner", '"off"', "toast_corner"),
                                 ("toast_seconds", "0", "toast_seconds"),
                                 ("toast_seconds", "600", "toast_seconds"),
                                 ("toast_stack", "0", "toast_stack"),
                                 ("toast_stack", "9", "toast_stack")):
            path.write_text(f'hotkey = "right ctrl"\n[capture]\n'
                            f"{key} = {value}\n", "utf-8")
            try:
                config_mod.load(path)
            except config_mod.ConfigError as e:
                assert word in str(e), (word, e)
            else:
                raise AssertionError(f"capture.{key} = {value} was accepted")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    here = Path(__file__).resolve().parent
    text = (here / "config.toml").read_text("utf-8")
    section = text[text.index("[capture]"):]
    section = section[:section.index("\n[", 1)]
    for key in ("after_shot", "toast_corner", "toast_seconds", "toast_stack",
                "always_save"):
        assert f"\n{key} = " in section, f"{key} is not a writable line"
    assert "edit_after_shot" not in section, \
        "the setting after_shot replaced is still in the shipped file"



def test_a_stuck_escape_cannot_close_an_overlay_that_just_opened() -> None:
    """THE WORST BUG THIS FEATURE HAS HAD, and it was invisible.

    Every overlay here READS Escape with GetAsyncKeyState rather than
    receiving it, because a borderless topmost window does not get the
    keyboard for free. That has one failure mode you cannot see from the
    outside: if Escape is stuck DOWN — an automation tool that injected a
    key-down without its key-up, a remote desktop session that dropped
    one, a wedged keyboard — every overlay opens and closes inside one
    tick. The crosshair flashes and vanishes, nothing is logged, and the
    app looks broken while dictation keeps working, because dictation is
    the one feature that never asks about Escape.

    It happened on 2026-08-26 and it read as "every feature except the
    transcriber is broken". Reproduced afterwards by wedging the key
    deliberately: with the latch seeded from the keyboard the selector
    stayed up 2.6 s and said why in the log; without it, 0.4 s and
    silence.

    So: a key that was ALREADY down when the window opened is not a
    cancel. Release it and press it again and it cancels exactly as
    before.
    """
    import capture as cap

    assert callable(cap.esc_held)
    source = (Path(__file__).resolve().parent / "capture.py").read_text(
        "utf-8")
    assert "GetAsyncKeyState(0x1B)" in \
        source[source.index("def esc_held("):source.index("def give_focus_back(")]

    for name, marker in (("ShotWindow", "class ShotWindow:"),
                         ("CameraWindow", "class CameraWindow:")):
        at = source.index(marker)
        pump = source[source.index("    def run(self)", at):]
        pump = pump[:pump.index("        finally:")]
        assert "held = esc_held()" in pump, (
            f"{name} still seeds its escape latch from False, so a key "
            "that was already down closes the window on the first tick")
        assert "and not held" in pump, f"{name} acts on a held key"
        assert "held = down" in pump, f"{name} never releases the latch"
        assert "esc is held down" in pump, (
            f"{name} closes silently — the whole cost of this bug was that "
            "it never said anything")



# --------------------------------------------------------------- the skin
#
# The reskin lives in skin\ and is meant to be DELETABLE: remove the folder
# and the app must paint itself exactly as it did before it existed. These
# tests guard that promise from both sides — that the hooks are all
# optional, and that what they hook up to behaves.
#
# Every one of them skips cleanly when skin\ is not there, because "deleted
# and the suite still passes" is the property being protected.

def _skin_or_skip():
    try:
        import skin
    except Exception:
        return None
    return skin


def test_every_skin_hook_is_optional() -> None:
    """The deletion promise, asserted at the source level.

    A hook that imported `skin` bare would turn deleting the folder into an
    ImportError at startup — which is the difference between a reskin you
    can throw away and one you are married to. Every file that reaches into
    skin\\ must do it inside a try/except that leaves the name None, and
    must test that name before calling through.
    """
    here = Path(__file__).resolve().parent
    for name in ("overlay.py", "ui.py", "visual_qa.py"):
        source = (here / name).read_text("utf-8")
        if "skin" not in source:
            continue
        assert "try:\n    import skin" in source or \
               "try:\n    import skin as _skin" in source, (
            f"{name} imports skin outside a try/except — deleting skin\\ "
            f"would stop the app from starting")
        for line in source.splitlines():
            stripped = line.strip()
            if stripped.startswith("if skin") and "skin." in stripped:
                assert "skin is not None" in stripped, (
                    f"{name} calls into skin without checking it exists: "
                    f"{stripped!r}")


def test_the_skin_never_invents_a_colour_it_was_not_asked_for() -> None:
    """repaint() writes only over names the target module already has.

    A palette that could CREATE a constant would let a typo here paint
    something nobody has ever looked at, and — worse — would hide the fact
    that the name it meant to replace no longer exists.
    """
    skin = _skin_or_skip()
    if skin is None:
        return
    from skin.palette import UI_NAMES
    import ui as ui_mod
    missing = [n for n in UI_NAMES if not hasattr(ui_mod, n)]
    assert not missing, (
        f"the skin repaints {missing}, which ui.py does not define — "
        f"either the name was renamed or this is a typo, and in both cases "
        f"the colour it meant to change is still the old one")
    space = {"BG": "#000000", "NOT_A_COLOUR": "#ffffff"}
    skin.repaint(space)
    assert space["NOT_A_COLOUR"] == "#ffffff", "repaint invented a name"


def test_deleting_the_skin_leaves_the_original_palette() -> None:
    """ui.py's own literals must still be the OLD ones.

    The hook overwrites them at import time, so the values in the file are
    what the app falls back to. If someone ever "tidies" them to match the
    skin, deleting skin\\ would silently keep the new colours and the
    revert would no longer be a revert.
    """
    here = Path(__file__).resolve().parent
    source = (here / "ui.py").read_text("utf-8")
    head = source[:source.index("# --- SKIN")]
    for name, was in (("BG", "#0d1017"), ("PANE", "#10131a"),
                      ("CARD", "#161b25"), ("ACCENT", "#2d6cdf"),
                      ("RED", "#e0352b"), ("SIDE_CARD", "#131822")):
        assert f'{name} ' in head and was in head, (
            f"ui.py no longer carries the original {name} = {was}; "
            f"deleting skin\\ would not restore the old look")


def test_the_release_is_one_flash_and_is_over_inside_a_second() -> None:
    """The two hard limits, and neither is a taste question.

    WCAG 2.3.1 exempts content with at most three general flashes per
    second REGARDLESS of area, and a full-screen effect is far past the
    0.006 sr area threshold — so one flash is the only safe design. And
    anything auto-moving past five seconds owes the user a pause control;
    staying under one keeps the whole question out of the app.
    """
    skin = _skin_or_skip()
    if skin is None or not skin.on():
        return
    from skin import burst as burst_mod
    assert burst_mod.T_END <= 1000, burst_mod.T_END
    flash_from, flash_to = burst_mod.T_FLASH
    assert flash_to - flash_from <= 200, "the flash is a decay, not a state"
    source = (Path(__file__).resolve().parent / "skin" / "burst.py").read_text(
        "utf-8")
    assert source.count("T_FLASH") <= 4, (
        "more than one place drives the flash — there must be exactly one")
    assert "FLASH_PEAK_ALPHA = 0.42" in source or \
        float(source.split("FLASH_PEAK_ALPHA = ")[1].split()[0]) <= 0.55, \
        "a flash brighter than 0.55 alpha is glare, not light"


def test_the_burst_holds_its_frame_budget_at_screen_size() -> None:
    """Blending costs ~65 ns a pixel in this Skia build, so the effect is
    priced in BLENDED AREA and the caps are what keep it real-time. This is
    the measurement, run for real, because the numbers in the comments are
    the whole argument for the shape of the code."""
    skin = _skin_or_skip()
    if skin is None or not skin.on():
        return
    import statistics

    import skia

    from skin.burst import Burst
    surface = skia.Surface.MakeRasterN32Premul(2560, 1440)
    canvas = surface.getCanvas()
    shot = Burst(2560, 1440, seed=3)
    for step in range(0, 40):           # warm Skia's lazy pipelines first
        shot.draw(canvas, -100 + step * 25)
    surface.flushAndSubmit()
    times = []
    for step in range(160):
        started = time.perf_counter()
        shot.draw(canvas, -100 + step * 6.5)
        surface.flushAndSubmit()
        times.append((time.perf_counter() - started) * 1000)
    times.sort()
    median = statistics.median(times)
    assert median < 20, f"median frame {median:.1f} ms — under 50 fps"
    assert times[-1] < 90, f"worst frame {times[-1]:.1f} ms — a visible hitch"


def test_the_boot_card_never_echoes_a_line_it_does_not_understand() -> None:
    """The log is not a user interface.

    It carries model ids, cuda dtypes and the phone URL WITH ITS AUTH TOKEN
    in it. The card shows a curated phrase per milestone and shows nothing
    at all for a line it does not recognise, so none of that can reach the
    screen — which matters because this window is on top of everything and
    is exactly what someone screen-shares.
    """
    skin = _skin_or_skip()
    if skin is None or not skin.on():
        return
    from skin.boot import Card
    card = Card()
    before = card.line
    card.status("open this on the phone: https://yoav.example.ts.net/"
                "#t=SECRETTOKENSECRETTOKEN")
    assert "SECRETTOKEN" not in card.line, card.line
    card.status("HTTP Request: GET https://huggingface.co/api/models/x")
    assert "huggingface" not in card.line
    card.status("Processing audio with duration 00:24.336")
    assert card.line in ("Phone link ready", before), card.line
    card.status("local model ivrit-ai/whisper-large-v3-turbo-ct2 ready "
                "on cuda (float16)")
    assert "ivrit" not in card.line and "cuda" not in card.line, card.line


def test_boot_progress_only_ever_goes_forward() -> None:
    """It is read out of log lines, which arrive in whatever order the app
    writes them, and a bar that runs backwards is worse than no bar."""
    skin = _skin_or_skip()
    if skin is None or not skin.on():
        return
    from skin.boot import MILESTONES, Card
    values = [v for _m, v, _p in MILESTONES]
    assert values == sorted(values), "the milestone table is out of order"
    assert max(values) == 1.0 and min(values) > 0, values
    card = Card()
    seen = [card.target()]
    for line in ("phone endpoint on 127.0.0.1:8756",
                 "loading the transcription model…",     # late and stale
                 "starting up",
                 "groq repair backend is warm"):
        card.status(line)
        seen.append(card.target())
    assert seen == sorted(seen), f"progress went backwards: {seen}"
    assert seen[-1] < 1.0, "only the ready line may reach the end"
    card.status("ready — hold 'right ctrl' and speak")
    assert card.target() == 1.0


def test_the_creep_never_reaches_the_next_milestone() -> None:
    """A progress indicator that sits perfectly still reads as a hang, and
    one that arrives before the work does reads as a lie. The drift is
    asymptotic on purpose: it always moves and never gets there."""
    skin = _skin_or_skip()
    if skin is None or not skin.on():
        return
    from skin.boot import CREEP_TO, Card
    card = Card()
    card.status("loading the transcription model…")
    floor, ceiling = card._floor, card._next
    card._since -= 3600.0            # an hour of idling
    drifted = card.target()
    assert drifted > floor, "the card would sit still and read as hung"
    assert drifted <= floor + (ceiling - floor) * CREEP_TO + 1e-9, drifted
    assert drifted < ceiling, "the creep arrived at the next milestone"


def test_every_skin_window_is_click_through_and_never_focusable() -> None:
    """These windows sit on top of everything the owner is doing. One that
    could take a click or the keyboard would be furniture in the way, not
    decoration — and the status dot in particular sits exactly where the
    close button of a maximised window is."""
    skin = _skin_or_skip()
    if skin is None or not skin.on():
        return
    from skin import glass as glass_mod
    from skin.dot import BOX
    assert BOX <= 40, (
        f"the dot's window is {BOX} px; two tests identify it as the "
        f"overlay at most 40 px wide")
    source = (Path(__file__).resolve().parent / "skin" / "glass.py").read_text(
        "utf-8")
    creation = source[source.index("        style = (WS_EX_LAYERED"):]
    creation = creation[:creation.index("if not self.hwnd")]
    for flag in ("WS_EX_LAYERED", "WS_EX_NOACTIVATE", "WS_EX_TOOLWINDOW",
                 "WS_EX_TOPMOST"):
        assert flag in creation, f"a skin window is created without {flag}"
    # Click-through is still the DEFAULT and still unconditional for every
    # window that does not ask for the mouse: the hint card is the only one
    # that does, it takes it in four small rectangles, and everything else
    # it is asked about answers HTTRANSPARENT (see the hit-test test).
    assert "if hit is None:\n            style |= WS_EX_TRANSPARENT" in \
        creation, "a window with no hit test is no longer click-through"
    assert glass_mod.WS_EX_TRANSPARENT == 0x20
    assert glass_mod.WS_EX_NOACTIVATE == 0x08000000
    assert glass_mod.HTTRANSPARENT == -1
    for name in ("dot", "boot", "reveal", "burst"):
        text = (Path(__file__).resolve().parent / "skin"
                / f"{name}.py").read_text("utf-8")
        assert "hit=" not in text, f"skin/{name}.py now takes the mouse"
    # SW_SHOWNOACTIVATE, not deiconify: AGENTS.md measured Tk taking the
    # foreground the instant it realises a window, and the fix there is to
    # take it BACK. A plain popup shown this way never takes it at all.
    assert "SW_SHOWNOACTIVATE" in source and glass_mod.SW_SHOWNOACTIVATE == 4


def test_the_skin_honours_the_windows_reduced_motion_setting() -> None:
    """A full-screen radial expansion is exactly the class of motion that
    triggers vestibular symptoms, and a user-triggered animation with no
    way off is a WCAG 2.3.3 failure. Windows has the setting; the cost of
    honouring it is one call."""
    skin = _skin_or_skip()
    if skin is None or not skin.on():
        return
    from skin.glass import SPI_GETCLIENTAREAANIMATION, wants_motion
    assert SPI_GETCLIENTAREAANIMATION == 0x1042
    assert isinstance(wants_motion(), bool)
    source = (Path(__file__).resolve().parent / "skin" / "boot.py").read_text(
        "utf-8")
    assert "wants_motion()" in source, (
        "boot.py never asks whether motion is wanted")
    assert "if motion" in source, (
        "boot.py asks and then fires the release anyway")


def test_the_skin_leaves_no_window_behind_when_it_is_done() -> None:
    """A leftover topmost click-through layer is invisible and permanent —
    the worst possible failure for a window like this, because nothing on
    screen would ever tell you it was there."""
    skin = _skin_or_skip()
    if skin is None or not skin.on():
        return
    import subprocess
    here = Path(__file__).resolve().parent
    # Waited from the CODE, not from a number typed in here. The moment got
    # longer once (880 ms -> 2580 ms) and this test failed with "the skin
    # left a window on screen", which is exactly the alarm you do not want
    # crying wolf: it was still playing.
    script = r"""
import ctypes, os, time, overlay, skin.boot as boot
whole = boot.moment_ms() / 1000.0
s = overlay.Splash(); s.start()
s.status('loading the transcription model...'); time.sleep(0.5)
s.finish('ready - go', linger_ms=40); time.sleep(whole + 1.2)
u = ctypes.WinDLL('user32')
me = os.getpid()
pid = ctypes.c_ulong()
left = []
def cb(h, _):
    b = ctypes.create_unicode_buffer(64); u.GetClassNameW(h, b, 64)
    u.GetWindowThreadProcessId(h, ctypes.byref(pid))
    if (b.value == 'HebrewDictationSkinGlass' and u.IsWindowVisible(h)
            and pid.value == me):
        left.append(b.value)
    return True
u.EnumWindows(ctypes.WINFUNCTYPE(
    ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)(cb), None)
print('LEFT', len(left))
"""
    out = subprocess.run([sys.executable, "-c", script], cwd=str(here),
                         capture_output=True, encoding="utf-8",
                         errors="replace", timeout=120)
    assert out.returncode == 0, (out.returncode, out.stdout, out.stderr)
    assert "LEFT 0" in out.stdout, (
        f"the skin left a window on screen: {out.stdout!r} {out.stderr!r}")


def test_the_moment_is_mostly_wind_up() -> None:
    """The shape of the reveal, which is the thing that failed twice.

    The first attempt was 880 ms and was described as "it appears for half
    a second, you can barely see it". The second was 420 ms of wind-up
    followed by 2400 ms of aftermath - the right total, the wrong shape.

    A card 24 degrees off screen centre costs a gaze roughly 300 ms to
    even reach, so a wind-up shorter than that is one nobody sees begin.
    And classical timing puts anticipation to action at about 2:1, with
    every real reference pushing further - a slot machine spends four
    seconds of spin on a third of a second of result.

    So: between 40% and 60% of the whole moment must be wind-up, the
    payoff itself must be a small fraction, and the total must stay inside
    the 2-3 s "subjective present" so it is remembered as ONE gesture.
    """
    skin = _skin_or_skip()
    if skin is None or not skin.on():
        return
    from skin import boot
    try:
        from skin.reveal import T_END
    except Exception:
        from skin.burst import T_END
    build = boot.GATHER_MS
    whole = build + T_END
    assert 1900 <= whole <= 3100, f"the whole moment is {whole:.0f} ms"
    share = build / whole
    assert 0.40 <= share <= 0.60, (
        f"wind-up is {share:.0%} of the moment; the researched band is "
        f"45-55% and anything under 40% is the shape that already failed")
    assert boot.SUMMONS_MS >= 200, (
        "the summons is shorter than a saccade to the corner of the screen")
    assert boot.GATHER_MS - boot.CHARGE_MS >= 120, (
        "there is no BREATH before the hit - the hold is what makes the "
        "impact land, and holds are the last thing to cut, never the first")


def test_the_release_cuts_to_an_aftermath_that_is_already_formed() -> None:
    """At the impact the front is CUT to a readable size and held still.

    Starting the expansion from radius zero spends the first tenth of the
    payoff drawing shapes too small to see, and the hitstop right after
    the impact is what lets the eye catch up. Both are asserted on the
    geometry rather than on the source text, so a refactor cannot quietly
    lose them.
    """
    skin = _skin_or_skip()
    if skin is None or not skin.on():
        return
    try:
        from skin.reveal import FRONT_R0, T_HOLD, Reveal
    except Exception:
        return                      # no GPU path on this machine
    assert 0.08 <= FRONT_R0 <= 0.35, FRONT_R0
    assert 60 <= T_HOLD <= 250, f"hitstop {T_HOLD} ms is outside 80-200"

    import numpy as np
    import skia

    from skin import gl
    ctx = gl.acquire()
    if ctx is None:
        return
    W, H = 1280, 720
    surface = ctx.surface(W, H)
    if surface is None:
        return
    info = skia.ImageInfo.MakeN32Premul(W, H)
    canvas = surface.getCanvas()
    shot = Reveal(W, H, origin=(W * 0.86, H * 0.86), seed=3)
    buf = np.empty((H, W, 4), dtype=np.uint8)
    lit = []
    for t in (5, T_HOLD - 20):
        canvas.clear(0x00000000)
        shot.draw(canvas, t)
        surface.flushAndSubmit()
        surface.readPixels(info, buf, W * 4, 0, 0)
        lit.append(int((buf[:, :, 3] > 10).sum()))
    assert lit[0] > 40000, (
        f"the first frame after the impact lights {lit[0]} px - the "
        f"aftermath is not formed, it is still growing from a point")


def test_the_reveal_never_pins_the_screen_to_white() -> None:
    """One flash, and it may not be glare.

    Everything in the reveal is additively blended, and four bright layers
    stacked will silently pin to white and take all the colour with them -
    which is exactly what happened the first time the aurora went in. The
    check is on the rendered pixels, because that is the only place the
    stack is visible.
    """
    skin = _skin_or_skip()
    if skin is None or not skin.on():
        return
    try:
        from skin.reveal import Reveal, T_END
    except Exception:
        return
    import numpy as np
    import skia

    from skin import gl
    # ON THE GPU, because that is the only surface this file ever draws on:
    # boot.py picks reveal.py when the glass is on the GPU and burst.py when
    # it is not. Measured on the CPU rasteriser the same frames blow out to
    # 38% pure white against 2.4% here, which is a real divergence and a
    # good reason not to test a path the app never takes.
    ctx = gl.acquire()
    if ctx is None:
        return
    W, H = 1280, 720
    surface = ctx.surface(W, H)
    if surface is None:
        return
    info = skia.ImageInfo.MakeN32Premul(W, H)
    canvas = surface.getCanvas()
    shot = Reveal(W, H, origin=(W * 0.86, H * 0.86), seed=3)
    buf = np.empty((H, W, 4), dtype=np.uint8)
    ground = np.full((H, W, 3), 30.0, dtype=np.float32)
    worst, hot_frames = 0.0, 0
    for t in range(-300, int(T_END) + 1, 50):
        canvas.clear(0x00000000)
        shot.draw(canvas, t)
        surface.flushAndSubmit()
        surface.readPixels(info, buf, W * 4, 0, 0)
        alpha = buf[:, :, 3:4].astype(np.float32) / 255.0
        out = buf[:, :, [2, 1, 0]].astype(np.float32) + ground * (1.0 - alpha)
        clipped = float((out >= 254.5).all(axis=2).mean())
        worst = max(worst, clipped)
        if clipped > 0.02:
            hot_frames += 1
    assert worst < 0.12, f"{worst:.0%} of a frame went pure white"
    assert hot_frames <= 3, (
        f"{hot_frames} frames are blowing out; there is meant to be ONE "
        f"flash, and everything after it is supposed to have colour")


def test_a_stalled_frame_cannot_skip_the_moment() -> None:
    """The reveal must DEGRADE under a stall, not be abandoned.

    Everything in the reveal is a pure function of one clock, which is what
    makes it look the same at 30 fps and at 240 — but taken straight from
    the wall clock, one long frame moves that clock by the whole length of
    the stall. If the stall is longer than what is left, the next frame
    computes a t past the end, the driver sees "finished", and the moment
    is thrown away.

    That is not hypothetical. It was reported as "it doesn't look like the
    video", and a frame-by-frame read of the screen recording showed
    exactly ONE frame of the reveal — the flash — and then the desktop back
    to normal. Reproduced deliberately with a 2.0 s stall at t=3 ms: the
    whole wind-up drew and then it stopped dead at the flash. The trigger
    was a screen recorder starting to encode, which lands on both the
    busiest moment for the GPU and the heaviest frame of the effect.
    """
    skin = _skin_or_skip()
    if skin is None or not skin.on():
        return
    from skin.clock import MAX_STEP_MS, Clock, absorb

    # the clamp itself
    clock = Clock(0.0)
    clock._last -= 5.0                      # pretend five seconds went by
    stepped = clock.tick()
    assert stepped <= MAX_STEP_MS + 1e-6, (
        f"a 5 s stall advanced the animation {stepped:.0f} ms; the clamp "
        f"is meant to hold it to {MAX_STEP_MS:.0f}")
    assert clock.stalls == 1
    # and a normal frame is NOT clamped, or the animation would run slow
    clock = Clock(0.0)
    clock._last -= 0.016
    assert 10 < clock.tick() < 30, "a 16 ms frame was treated as a stall"
    assert clock.stalls == 0

    now, shift = absorb(time.perf_counter() - 3.0)
    assert shift > 2.0, shift
    _now, shift = absorb(time.perf_counter() - 0.016)
    assert shift == 0.0, shift

    # and the driver that matters actually uses it
    here = Path(__file__).resolve().parent
    boot = (here / "skin" / "boot.py").read_text("utf-8")
    assert "absorb(" in boot, (
        "skin/boot.py drives the moment straight off the wall clock again; "
        "one slow frame will skip the whole release")
    assert "card.released_at += shift" in boot, (
        "the card's release instant is not shifted with the clock, so a "
        "stall will still jump the reveal past its own start")


def test_the_reveal_still_finishes_after_a_two_second_stall() -> None:
    """The same thing, end to end, against the real renderer."""
    skin = _skin_or_skip()
    if skin is None or not skin.on():
        return
    try:
        from skin.reveal import Reveal, T_DIP, T_END
    except Exception:
        return
    import skia

    from skin import gl
    ctx = gl.acquire()
    if ctx is None:
        return
    W, H = 960, 540
    surface = ctx.surface(W, H)
    if surface is None:
        return
    from skin.clock import Clock
    canvas = surface.getCanvas()
    shot = Reveal(W, H, origin=(W * 0.86, H * 0.86), seed=3)
    clock = Clock(T_DIP[0])
    after, stalled = 0, False
    while True:
        t = clock.tick()
        canvas.clear(0x00000000)
        if not shot.draw(canvas, t):
            break
        surface.flushAndSubmit()
        if t > 0:
            after += 1
        if t >= 0 and not stalled:
            stalled = True
            clock._last -= 2.0          # a two-second frame, at the flash
    assert after > 40, (
        f"only {after} frames were drawn after the flash — the stall "
        f"abandoned the reveal instead of slowing it")


def test_a_whole_boot_runs_the_release_without_raising() -> None:
    """The end-to-end check that was missing, and what it cost.

    Everything about the release was tested in pieces - the geometry, the
    exposure, the frame budget, the timings - and every piece passed while
    the thing was completely broken in the actual app. The driver loop in
    skin/boot.py closes the card's window when its wind-up ends and then
    went straight back round and drew the card on it again, so the splash
    thread died with an AttributeError one frame after the flash. It was
    caught, logged to app.log, and silent everywhere else.

    Reported as "when I run the model it doesn't do it, but the preview
    does" - and the preview genuinely did, because it drives the card and
    the release in two separate loops and never touches this path.

    So this runs a REAL Splash through a REAL release and fails if anything
    was raised. It is a subprocess because it stands up windows and a GL
    context on a thread of its own.
    """
    skin = _skin_or_skip()
    if skin is None or not skin.on():
        return
    import subprocess
    here = Path(__file__).resolve().parent
    script = r"""
import logging, sys, time, io
buf = io.StringIO()
h = logging.StreamHandler(buf); h.setLevel(logging.DEBUG)
log = logging.getLogger('app'); log.setLevel(logging.DEBUG); log.addHandler(h)
import overlay, skin.boot as boot
s = overlay.Splash(); s.start()
s.status('loading the transcription model...')
# long enough that the release layer exists the way it does on a
# real 14-25 s boot; a shorter wait exercised a different path and
# was why this test first passed against the broken code
time.sleep(1.6)
s.status('ready - hold right ctrl and speak')
s.finish('ready - hold right ctrl and speak', linger_ms=60)
time.sleep(boot.moment_ms() / 1000.0 + 1.4)
out = buf.getvalue()
print('LOGGED-BEGIN'); print(out[:2000]); print('LOGGED-END')
"""
    out = subprocess.run([sys.executable, "-c", script], cwd=str(here),
                         capture_output=True, encoding="utf-8",
                         errors="replace", timeout=180)
    assert out.returncode == 0, (out.returncode, out.stdout, out.stderr)
    logged = out.stdout
    for bad in ("Traceback", "AttributeError", "stopped early",
                "falling back", "failed"):
        assert bad not in logged, (
            f"the boot logged {bad!r} - the release did not survive:\n"
            f"{logged}")
    assert "Traceback" not in (out.stderr or ""), out.stderr


def test_turning_the_skin_off_really_turns_it_off() -> None:
    """HD_SKIN=0 is the one-run escape hatch, and it has to be complete —
    a half-disabled skin would be harder to diagnose than a broken one."""
    skin = _skin_or_skip()
    if skin is None:
        return
    import os
    was = os.environ.get("HD_SKIN")
    try:
        os.environ["HD_SKIN"] = "0"
        skin.reset()
        assert skin.on() is False
        space = {"BG": "#0d1017"}
        skin.repaint(space)
        assert space["BG"] == "#0d1017", "repaint ran with the skin off"
        assert skin.splash_run(None) is False
        assert skin.dot_run(None) is False
        assert skin.paint_wave(None) is False
    finally:
        if was is None:
            os.environ.pop("HD_SKIN", None)
        else:
            os.environ["HD_SKIN"] = was
        skin.reset()


def test_no_skin_hook_shares_a_name_with_a_file_in_the_folder() -> None:
    """A hook may not be named after the module it imports.

    Python binds a submodule onto its parent package the first time it is
    imported. So a hook `def wave(card)` whose body says `from .wave import
    paint` REPLACES ITSELF the moment it first runs: skin.wave stops being
    the function and becomes skin\\wave.py, and the next call raises
    "'module' object is not callable" — from the call site, outside the
    hook's own try/except, where the skin's "a decoration cannot take the
    app down" promise cannot reach it.

    This is not a style rule. It was a live bug: the ask-the-screen card
    paints its microphone rings on a 15 ms tick, and only while a dictation
    is running, so the card died on the SECOND tick of every question the
    owner tried to speak into it. From his seat the window simply closed
    the instant he started talking, which reads as a hotkey conflict and is
    not one. Four identical tracebacks in app.log, 2026-08-27.

    Read out of the SOURCE rather than off the imported module, on purpose:
    once a colliding hook has been called even once the attribute is a
    module and no longer callable, so an attribute-based check would go
    quiet at exactly the moment the bug became real.
    """
    skin = _skin_or_skip()
    if skin is None:
        return
    import ast
    folder = Path(skin.__file__).resolve().parent
    tree = ast.parse((folder / "__init__.py").read_text("utf-8"))
    hooks = {node.name for node in tree.body
             if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
    modules = {p.stem for p in folder.glob("*.py")} - {"__init__"}
    clash = sorted(hooks & modules)
    assert not clash, (
        f"skin hook(s) {clash} share a name with skin\\<name>.py. Importing "
        f"the submodule rebinds the attribute, so the hook works exactly "
        f"once and then raises \"'module' object is not callable\". Rename "
        f"the function — splash_run/.boot, dot_run/.dot and "
        f"paint_wave/.wave all keep the two apart on purpose.")


def test_a_skin_hook_survives_being_called_twice() -> None:
    """The behaviour the rule above protects, exercised end to end.

    The shadowing bug passed every test there was, because every one of
    them called the hook ONCE. The first call is the one that works.

    THIS ONE IS NOT THE GUARD — the name test above is. With no skia on
    the machine on() returns False, the hook returns before it reaches the
    import that does the shadowing, and both calls below pass against code
    that is still broken. It earns its place by testing the real thing on
    the machine that runs the skin; it must never be the only test of it.
    """
    skin = _skin_or_skip()
    if skin is None:
        return
    # None is not a card, so the hook declines both times — what is being
    # tested is that the second call is still a CALL and not a TypeError.
    assert skin.paint_wave(None) is False
    assert skin.paint_wave(None) is False, (
        "the second call of a skin hook failed — a submodule import has "
        "shadowed the function (see the name-collision test above)")



# --------------------------------------------------------------------------
# The second learning channel (study.py) and machine evidence (vocab.py)
# --------------------------------------------------------------------------


def test_machine_evidence_never_wins_replace_rights() -> None:
    """The rule the whole channel hangs on: no amount of MACHINE agreement
    may ever rewrite the user's text automatically. apply() gates on the
    human hits counter alone, and learn_auto cannot touch it."""
    v = _tmp_vocab(replace_after_hits=2)
    for n in range(5):
        v.learn_auto("סירקה", "סריקה", source=f"rec-{n}")
    out, applied = v.apply("עשיתי סירקה מלאה")
    assert out == "עשיתי סירקה מלאה", out
    assert applied == [], applied
    # Two HUMAN corrections of the same pair — now, and only now, it acts.
    v.learn("סירקה", "סריקה")
    v.learn("סירקה", "סריקה")
    out, applied = v.apply("עשיתי סירקה מלאה")
    assert out == "עשיתי סריקה מלאה", out


def test_the_same_recording_never_testifies_twice() -> None:
    """Re-studying a clip (after an ENGINE bump) must not be counted as new
    independent evidence — auto_hits counts DIFFERENT recordings."""
    v = _tmp_vocab()
    v.learn_auto("xpogo", "Expo Go", source="rec-1")
    v.learn_auto("xpogo", "Expo Go", source="rec-1")
    entry = v.corrections[0]
    assert int(entry["auto_hits"]) == 1, entry
    v.learn_auto("xpogo", "Expo Go", source="rec-2")
    assert int(entry["auto_hits"]) == 2, entry


def test_machine_terms_need_two_recordings_before_hotwords() -> None:
    v = _tmp_vocab()
    v.learn_auto("xpogo", "Expo Go", source="rec-1")
    assert "Expo Go" not in v.terms(), v.terms()
    v.learn_auto("xpogo", "Expo Go", source="rec-2")
    assert "Expo Go" in v.terms(), v.terms()


def test_glossary_only_pairs_stay_out_of_the_hotwords() -> None:
    """Family B: a real Hebrew word swapped for a real Hebrew word. As a
    hotword it would prompt Whisper to emit a common word unbidden; as a
    glossary line the polish model reads the sentence first. So it reaches
    the glossary and never the decoder."""
    v = _tmp_vocab()
    for n in range(3):
        v.learn_auto("קירוב", "קירור", source=f"rec-{n}",
                     glossary_only=True)
    assert "קירור" not in v.terms(), v.terms()
    assert "קירור" not in v.hotwords()
    assert ("קירוב", "קירור") in v.glossary(), v.glossary()


def test_human_terms_outrank_machine_terms() -> None:
    """Budget order: seeds (the user's own hand), then human corrections,
    then machine evidence. max_terms cuts from the back, so the machine
    entries are the first to fall off."""
    v = _tmp_vocab(seed_terms=("Massif",), max_terms=3)
    v.learn("brinth", "branch")
    for n in range(2):
        v.learn_auto("xpogo", "Expo Go", source=f"rec-{n}")
    assert v.terms() == ["Massif", "branch", "Expo Go"], v.terms()
    v2 = _tmp_vocab(seed_terms=("Massif",), max_terms=2)
    v2.learn("brinth", "branch")
    for n in range(2):
        v2.learn_auto("xpogo", "Expo Go", source=f"rec-{n}")
    assert v2.terms() == ["Massif", "branch"], v2.terms()


def test_a_human_correction_upgrades_a_machine_entry() -> None:
    """When the user corrects a pair the machine had already noticed, the
    entry becomes a human one: hits start counting, and the human's meant
    wins any conflict from then on."""
    v = _tmp_vocab(replace_after_hits=2)
    v.learn_auto("brinth", "brunch", source="rec-1")   # machine got it wrong
    v.learn("brinth", "branch")
    entry = v.corrections[0]
    assert int(entry["hits"]) == 1 and entry["meant"] == "branch", entry
    # and machine evidence can no longer move the meant
    v.learn_auto("brinth", "brunch", source="rec-2")
    assert entry["meant"] == "branch", entry


def test_auto_evidence_survives_a_save_and_load() -> None:
    v = _tmp_vocab()
    v.learn_auto("xpogo", "Expo Go", source="rec-1")
    v.learn_auto("xpogo", "Expo Go", source="rec-2")
    v.save()
    v2 = vocab_mod.Vocab(v.path)
    entry = v2.corrections[0]
    assert int(entry["auto_hits"]) == 2, entry
    assert int(entry["hits"]) == 0, entry
    assert "Expo Go" in v2.terms()
    out, applied = v2.apply("תריץ xpogo")
    assert applied == [], "a reload must not invent replace rights"


def test_the_family_split_matches_the_vocab_reasoning() -> None:
    import study as study_mod
    assert study_mod.family("xpogo", "Expo Go") == "term"
    assert study_mod.family("בקו-ורק", "Cowork") == "term"
    assert study_mod.family("קירוב", "קירור") == "context"


def test_consensus_needs_two_independent_agreements() -> None:
    """One decode disagreeing is an anecdote; two agreeing on the SAME
    reading for the SAME span is evidence; two disagreeing with the
    primary AND each other is proof the region is hard, not a vote."""
    import study as study_mod
    primary = "נוזל קירוב למנוע"
    out, pairs = study_mod.consensus(primary, ["נוזל קירור למנוע"])
    assert out == primary and pairs == [], (out, pairs)
    out, pairs = study_mod.consensus(
        primary, ["נוזל קירור למנוע", "נוזל קירור למנוע",
                  "נוזל קירוב למנוע"])
    assert out == "נוזל קירור למנוע", out
    assert pairs == [("קירוב", "קירור")], pairs
    out, pairs = study_mod.consensus(
        primary, ["נוזל קירור למנוע", "נוזל קידוח למנוע"])
    assert out == primary and pairs == [], (out, pairs)


def test_consensus_keeps_the_primary_punctuation() -> None:
    import study as study_mod
    primary = "בסדר, תעשה סירקה עכשיו!"
    out, pairs = study_mod.consensus(
        primary, ["בסדר תעשה סריקה עכשיו", "בסדר, תעשה סריקה עכשיו"])
    assert out == "בסדר, תעשה סריקה עכשיו!", out
    assert pairs == [("סירקה", "סריקה")], pairs


def test_the_adjudicator_cannot_introduce_words_from_nowhere() -> None:
    """The guarantee that turns 'ask an LLM' into 'let an LLM choose': a
    reply word that no decode of the audio ever produced is proof of
    rewriting, and the reply dies in code, not in the prompt."""
    import study as study_mod
    primary = "נוזל קירוב למנוע"
    candidates = ["נוזל קירור למנוע"]
    ok, _ = study_mod._safe_choice(primary, candidates,
                                   "נוזל קירור למנוע")
    assert ok
    ok, why = study_mod._safe_choice(primary, candidates,
                                     "נוזל צינון למנוע")
    assert not ok and "צינון" in why, (ok, why)
    # the Hebrew prefixes are one word, not a new one
    ok, _ = study_mod._safe_choice("הלכתי סירקה", ["הלכתי לסריקה"],
                                   "הלכתי סריקה")
    assert ok, "a decode that heard לסריקה has heard סריקה"


def test_a_reply_that_rewrites_is_rejected_before_word_checks() -> None:
    import study as study_mod
    primary = "אחת שתיים שלוש"
    reply = "אחת שתיים שלוש " + "שלוש " * 10
    ok, _ = study_mod._safe_choice(primary, [reply], reply)
    assert not ok, "growth beyond polish._is_safe must reject"


class _StudyItem:
    """A SpooledItem stand-in: same three members study.py touches."""

    def __init__(self, wav_path, meta, seconds=5.0):
        self.wav_path = wav_path
        self.meta = meta
        self.seconds = seconds

    def read(self):
        return b"RIFF-not-really-audio"


class _StudyAdjudicator:
    """An adjudicator that assents to a fixed reading — no network."""

    def __init__(self, reply):
        self._reply = reply

    def adjudicate(self, primary, candidates):
        return self._reply


class _StudyTranscriber:
    """study_decode by plan: the kwargs are the plan's identity."""

    def __init__(self, wide="", general="", loose=""):
        self._wide, self._general, self._loose = wide, general, loose
        self.calls = 0

    def study_decode(self, audio, **kw):
        self.calls += 1
        if kw.get("general"):
            return self._general
        if kw.get("temperature") is not None:
            return self._loose
        return self._wide


def test_study_skips_what_it_already_studied() -> None:
    import study as study_mod
    assert not study_mod.needs_study(
        _StudyItem(Path("x.wav"), {"text": ""}))
    assert study_mod.needs_study(
        _StudyItem(Path("x.wav"), {"text": "שלום"}))
    assert not study_mod.needs_study(
        _StudyItem(Path("x.wav"),
                   {"text": "שלום", "study": {"engine": study_mod.ENGINE}}))
    assert study_mod.needs_study(
        _StudyItem(Path("x.wav"),
                   {"text": "שלום", "study": {"engine": 0}}))


def test_study_stands_aside_the_moment_the_user_is_back() -> None:
    import study as study_mod
    t = _StudyTranscriber(wide="שלום")
    result = study_mod.study_one(
        _StudyItem(Path("x.wav"), {"text": "שלום"}), t,
        pause=lambda: True)
    assert result is None, "pause=True must abandon the clip whole"
    assert t.calls == 0, "and before any decode, not after"


def test_the_vote_proposes_and_the_adjudicator_disposes() -> None:
    """Measured 2026-08-27 over 48 real clips: consensus-only verdicts
    were mostly orthographic wobble (two of the three decodes share a
    model and its habits) and scored worse than the live text on the
    labelled clips. So an acoustic vote with no adjudicator assent
    teaches NOTHING — and with assent, it teaches the divergence."""
    import study as study_mod
    item = _StudyItem(Path("rec-9.wav"), {"text": "תריץ את xpogo עכשיו"})
    t = _StudyTranscriber(wide="תריץ את Expo Go עכשיו",
                          general="תריץ את Expo Go עכשיו",
                          loose="תריץ את xpogo עכשיו")
    result = study_mod.study_one(item, t)
    assert result["verified"] == "תריץ את xpogo עכשיו", \
        "without assent, verified IS the live text"
    assert result["voted"] == "תריץ את Expo Go עכשיו", result
    assert result["pairs"] == [], "no assent, no learning"
    assert result["llm"] is False
    assented = study_mod.study_one(
        item, t,
        adjudicator=_StudyAdjudicator("תריץ את Expo Go עכשיו"))
    assert assented["llm"] is True
    assert assented["pairs"] == [["xpogo", "Expo Go", "term"]], assented
    # and a clip every decode agrees on teaches nothing either way
    t2 = _StudyTranscriber(wide="שלום עולם", general="שלום עולם",
                           loose="שלום עולם")
    result2 = study_mod.study_one(
        _StudyItem(Path("rec-10.wav"), {"text": "שלום עולם"}), t2,
        adjudicator=_StudyAdjudicator("שלום עולם"))
    assert result2["pairs"] == [], result2
    assert result2["agree"] == 1.0, result2


def test_one_lonely_decode_is_an_anecdote_not_a_study() -> None:
    """Two decodes failing (a broken general model, say) must not leave a
    single opinion rewriting history — and must not leave the clip
    unstudied forever either."""
    import study as study_mod

    class _Flaky(_StudyTranscriber):
        def study_decode(self, audio, **kw):
            if kw.get("general") or kw.get("temperature") is not None:
                raise RuntimeError("boom")
            return "טקסט אחר לגמרי מהמקור שהיה"

    result = study_mod.study_one(
        _StudyItem(Path("x.wav"), {"text": "שלום עולם"}), _Flaky())
    assert result is not None and result["pairs"] == [], result
    assert result["verified"] == "שלום עולם", result
    assert result["engine"] == study_mod.ENGINE


def test_the_corpus_is_capped_and_gold_is_never_downgraded() -> None:
    import json as json_mod
    import tempfile
    import study as study_mod
    root = Path(tempfile.mkdtemp(prefix="corpus-"))
    src = Path(tempfile.mkdtemp(prefix="rec-"))
    corpus = study_mod.Corpus(root / "corpus", keep=2)

    def make(name):
        wav = src / name
        wav.write_bytes(b"RIFFx")
        return _StudyItem(wav, {})

    assert corpus.admit(make("a.wav"), "אחת", "gold")
    assert corpus.admit(make("b.wav"), "שתיים", "silver")
    assert corpus.admit(make("c.wav"), "שלוש", "silver")
    assert len(corpus) == 2, "keep=2 must trim the oldest"
    # a gold label is a human's word; silver evidence must not overwrite it
    item = make("d.wav")
    corpus_keep_all = study_mod.Corpus(root / "corpus2", keep=10)
    assert corpus_keep_all.admit(item, "מילה של בנאדם", "gold")
    assert not corpus_keep_all.admit(item, "ניחוש של מכונה", "silver")
    side = json_mod.loads(
        (root / "corpus2" / "d.json").read_text("utf-8"))
    assert side["tier"] == "gold" and side["text"] == "מילה של בנאדם", side


def test_the_engine_studies_one_clip_and_feeds_the_vocab() -> None:
    """End to end with the LLM leg budgeted to zero: spool in, consensus
    vote, sidecar stamped, vocabulary fed — and a second call finds
    nothing left to do."""
    import dataclasses as dc
    import tempfile
    import threading
    import study as study_mod
    from spool import Spool

    cfg = config_mod.load(Path(__file__).resolve().parent / "config.toml")
    tmp = Path(tempfile.mkdtemp(prefix="study-"))
    recent = Spool(tmp / "recent", keep=10)
    recent.save(b"RIFFx", 5.0, "",
                extra={"text": "נוזל קירוב למנוע",
                       "raw": "נוזל קירוב למנוע"})
    v = _tmp_vocab()
    t = _StudyTranscriber(wide="נוזל קירור למנוע",
                          general="נוזל קירור למנוע",
                          loose="נוזל קירוב למנוע")
    engine = study_mod.Engine(
        cfg, t, v, recent,
        model_lock=threading.Lock(),
        quiet=lambda: True,
        fingerprint=lambda: 0,
        app_dir=tmp,
        adjudicator=_StudyAdjudicator("נוזל קירור למנוע"))
    assert engine.run_once() is True
    item = recent.pending()[0]
    assert item.meta["study"]["engine"] == study_mod.ENGINE
    assert item.meta["study"]["pairs"] == [["קירוב", "קירור", "context"]]
    entry = v.corrections[0]
    assert entry["heard"] == "קירוב" and int(entry["auto_hits"]) == 1
    assert entry["glossary_only"] is True, entry
    out, applied = v.apply("נוזל קירוב")
    assert applied == [], "the engine must never grant replace rights"
    assert engine.run_once() is False, "nothing left to study"


def test_a_spent_llm_budget_waits_instead_of_wasting_clips() -> None:
    """Learning requires the adjudicator's assent, so a clip studied with
    no budget would be stamped while teaching nothing — the engine must
    leave it whole for tomorrow instead."""
    import dataclasses as dc
    import tempfile
    import threading
    import study as study_mod
    from spool import Spool

    cfg = config_mod.load(Path(__file__).resolve().parent / "config.toml")
    cfg = dc.replace(cfg, study=dc.replace(cfg.study, llm_per_day=0))
    tmp = Path(tempfile.mkdtemp(prefix="study-"))
    recent = Spool(tmp / "recent", keep=10)
    recent.save(b"RIFFx", 5.0, "", extra={"text": "שלום עולם"})
    t = _StudyTranscriber(wide="שלום עולם", general="שלום עולם",
                          loose="שלום עולם")
    engine = study_mod.Engine(cfg, t, _tmp_vocab(), recent,
                              model_lock=threading.Lock(),
                              quiet=lambda: True,
                              fingerprint=lambda: 0,
                              app_dir=tmp)
    assert engine.run_once() is False
    assert t.calls == 0, "no decode may be spent without an adjudicator"
    assert "study" not in recent.pending()[0].meta, "and no stamp either"


def test_a_clip_too_long_to_study_is_marked_not_rechewed() -> None:
    import dataclasses as dc
    import tempfile
    import threading
    import study as study_mod
    from spool import Spool

    cfg = config_mod.load(Path(__file__).resolve().parent / "config.toml")
    cfg = dc.replace(cfg, study=dc.replace(cfg.study,
                                           max_clip_seconds=10.0))
    tmp = Path(tempfile.mkdtemp(prefix="study-"))
    recent = Spool(tmp / "recent", keep=10)
    recent.save(b"RIFFx", 99.0, "", extra={"text": "ארוך מאוד"})
    t = _StudyTranscriber()
    engine = study_mod.Engine(cfg, t, _tmp_vocab(), recent,
                              model_lock=threading.Lock(),
                              quiet=lambda: True,
                              fingerprint=lambda: 0,
                              app_dir=tmp)
    assert engine.run_once() is False
    assert t.calls == 0, "no decode may be spent on a skipped clip"
    assert "skipped" in recent.pending()[0].meta["study"]
    assert engine.run_once() is False, "and it is not picked again"


def test_the_shipped_config_carries_the_study_section() -> None:
    cfg = config_mod.load(Path(__file__).resolve().parent / "config.toml")
    scfg = getattr(cfg, "study", None)
    assert scfg is not None and scfg.enabled, scfg
    assert scfg.idle_minutes > 0 and scfg.max_clip_seconds > 0
    assert 0 < scfg.llm_per_day < 500, "must stay well under Groq's ~1,000/day"


def test_the_learning_probes_read_the_app_cheaply() -> None:
    """The study engine polls these every few seconds; they must work on a
    half-built App (the suite's convention) and see both state and
    counters move."""
    import queue as queue_mod
    import threading

    import main as main_mod
    app = main_mod.App.__new__(main_mod.App)
    app._activity = "ready"
    app.queue = queue_mod.Queue()
    app._text_busy = threading.Event()
    app._correcting = threading.Event()
    app._looking_up = threading.Event()
    app._stats_lock = threading.Lock()
    app._stats = {"dictations": 0}
    assert app._learning_quiet()
    before = app._learning_fingerprint()
    app._stats["dictations"] = 1
    assert app._learning_fingerprint() != before, "a dictation must show"
    app._activity = "recording"
    assert not app._learning_quiet(), "recording is never a quiet moment"



def test_the_study_never_relearns_what_the_live_pass_already_fixed() -> None:
    """The backward-learning trap: polish fixed a word, every fresh decode
    of the same audio still hears the original garble, the vote "agrees"
    the fix back out — and the diff would teach the app to un-fix itself,
    (right word -> garble). The heard side of a learnable pair must be
    something the live decoder actually produced."""
    import study as study_mod
    item = _StudyItem(Path("rec-11.wav"),
                      {"raw": "נוזל קירוב למנוע",
                       "text": "נוזל קירור למנוע"})   # polish fixed it
    t = _StudyTranscriber(wide="נוזל קירוב למנוע",
                          general="נוזל קירוב למנוע",
                          loose="נוזל קירוב למנוע")
    result = study_mod.study_one(
        item, t, adjudicator=_StudyAdjudicator("נוזל קירוב למנוע"))
    assert result["llm"] is True, result
    assert result["pairs"] == [], result
    # and that disagreement is NOT silver corpus material either
    assert not study_mod.Engine._silver(item.meta, result), result
    # while a clip where everything agrees still is
    t2 = _StudyTranscriber(wide="נוזל קירור למנוע",
                           general="נוזל קירור למנוע",
                           loose="נוזל קירור למנוע")
    result2 = study_mod.study_one(
        _StudyItem(Path("rec-12.wav"),
                   {"raw": "נוזל קירור למנוע",
                    "text": "נוזל קירור למנוע"}), t2)
    assert study_mod.Engine._silver(
        {"text": "נוזל קירור למנוע"}, result2), result2
    # ...but a clip the vote DISPUTED is not "everything agreed", even
    # though the unendorsed verified text equals the live text
    assert result["disputed"] and not study_mod.Engine._silver(
        item.meta, result), result

def _hint_cfg(**over):
    """The shipped config, with fields replaced, for the card's rows."""
    cfg = config_mod.load(Path(__file__).resolve().parent / "config.toml")
    return dataclasses.replace(cfg, **over) if over else cfg


def test_hint_settings_are_present_in_the_real_config() -> None:
    """A default that lives only in code is a default nobody can find."""
    cfg = _hint_cfg()
    assert cfg.hint.corner in config_mod.HINT_CORNERS, cfg.hint.corner
    # The delay is the whole reason this is not clutter: an ordinary
    # dictation has to finish before the card would have appeared.
    assert 150 <= cfg.hint.after_ms <= 1200, cfg.hint.after_ms
    text = (Path(__file__).resolve().parent / "config.toml").read_text("utf-8")
    assert "[hint]" in text and "after_ms" in text


def test_a_bad_hint_corner_is_refused_at_load() -> None:
    """Refused where it can still be reported, not at the first paint."""
    import shutil

    tmp = Path(tempfile.mkdtemp(prefix="dictation-hint-"))
    try:
        path = tmp / "config.toml"
        base = (Path(__file__).resolve().parent / "config.toml"
                ).read_text("utf-8")
        path.write_text(base.replace('corner = "top-right"',
                                     'corner = "middle"'), "utf-8")
        try:
            config_mod.load(path)
        except config_mod.ConfigError as e:
            assert "corner" in str(e), e
        else:
            raise AssertionError("a nonsense corner loaded happily")
        path.write_text(base.replace("after_ms = 400", "after_ms = -1"),
                        "utf-8")
        try:
            config_mod.load(path)
        except config_mod.ConfigError as e:
            assert "after_ms" in str(e), e
        else:
            raise AssertionError("a negative delay loaded happily")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_the_card_lists_exactly_the_keys_the_state_machine_taps() -> None:
    """The one way this feature can lie without anyone noticing.

    A card naming a key you have rebound, or one this app never bound, is
    worse than no card. Both lists are built from the same Config by
    different code, so this compares them rather than trusting that they
    were written to agree.
    """
    import main as main_mod

    cfg = _hint_cfg()
    _hotkeys, taps, _latch, _pause = main_mod.App.bindings(cfg)
    from_machine = set(taps.values())
    from_card = {action for action, _binding in hint_mod.bindings(cfg)}
    assert from_card == from_machine, (from_card ^ from_machine)
    # and every one of them has a human name, not a bare action string
    for action in from_card:
        assert action in hint_mod.LABELS, action


def test_held_greys_the_text_keys_and_latched_does_not() -> None:
    """main._allowed's rule, read off the card instead of the log."""
    import main as main_mod

    cfg = _hint_cfg()
    held = hint_mod.card_for(cfg, hint_mod.HOLD, main_mod._SCREEN_ACTIONS)
    latched = hint_mod.card_for(cfg, hint_mod.LATCHED,
                                main_mod._SCREEN_ACTIONS)
    assert hint_mod.card_for(cfg, "idle", main_mod._SCREEN_ACTIONS) is None
    live = {k for k, _l, on in held["keys"] if on}
    dead = {k for k, _l, on in held["keys"] if not on}
    assert live and dead, held["keys"]
    # The four screen keys fire mid-hold; the four that read or write text
    # at the cursor do not, and say why rather than going quiet.
    for key, label, on in held["keys"]:
        if not on:
            assert hint_mod.NEEDS_A_HAND in label, label
    assert all(on for _k, _l, on in latched["keys"]), latched["keys"]
    assert live | dead == {k for k, _l, _o in latched["keys"]}
    # Held offers the release and the latch; latched offers neither.
    assert any(k == "שחרר" for k, _l, _o in held["rows"])
    assert not any(k == "שחרר" for k, _l, _o in latched["rows"])
    assert all(any(k == "Esc" for k, _l, _o in c["rows"])
               for c in (held, latched))


def test_rebinding_a_key_moves_it_on_the_card_and_a_kill_switch_removes_it(
) -> None:
    """Built from the live Config, so it cannot describe last week's keys."""
    import main as main_mod

    cfg = dataclasses.replace(_hint_cfg(), punctuate_hotkey="ctrl+f7")
    card = hint_mod.card_for(cfg, hint_mod.LATCHED, main_mod._SCREEN_ACTIONS)
    rows = dict((label, key) for key, label, _on in card["keys"])
    assert rows[hint_mod.LABELS["punctuate"]] == "Ctrl+F7", rows
    gone = dataclasses.replace(cfg, punctuate_hotkey="", lookup_hotkey="")
    card = hint_mod.card_for(gone, hint_mod.LATCHED, main_mod._SCREEN_ACTIONS)
    labels = {label for _key, label, _on in card["keys"]}
    assert hint_mod.LABELS["punctuate"] not in labels, labels
    assert hint_mod.LABELS["lookup"] not in labels, labels


def test_key_names_are_written_the_way_a_person_reads_them() -> None:
    assert hint_mod.pretty("ctrl+f10") == "Ctrl+F10"
    assert hint_mod.pretty("win+shift+s") == "Win+Shift+S"
    assert hint_mod.pretty("right ctrl") == "Right Ctrl"
    # The latch key is an arrow on the keyboard and an arrow on the card.
    assert hint_mod.pretty("left") == "←"
    assert hint_mod.pretty("") == ""


def test_the_card_goes_in_the_corner_it_was_asked_for() -> None:
    """Pure arithmetic, so all four are checked without a screen."""
    screen = (1920, 1080)
    got = {}
    for corner in config_mod.HINT_CORNERS:
        card = overlay_mod.HintCard(corner=corner, margin=10)
        got[corner] = card.origin(300, 400, screen)
    assert got["top-left"] == (10, 10), got
    assert got["bottom-left"] == (10, 1080 - 400 - 10), got
    assert got["bottom-right"] == (1920 - 300 - 10, 1080 - 400 - 10), got
    # top-right alone stops short, so the status dot keeps its own square.
    # The dot is the one thing on screen that says the app is alive, and it
    # does not move for a panel that is only up while a key is held.
    x, y = got["top-right"]
    assert y == 10, got
    assert x == 1920 - 300 - 10 - overlay_mod.HintCard.DOT_ROOM, got


def test_the_shadow_margin_does_not_move_the_visible_edge() -> None:
    """The glass card leaves room around itself for its own shadow and the
    Tk one does not, so the same corner has to put the same PICTURE in the
    same place from two different window sizes."""
    screen = (1920, 1080)
    card = overlay_mod.HintCard(corner="top-left", margin=12)
    plain = card.origin(300, 400, screen)
    padded = card.origin(300 + 52, 400 + 52, screen, inset=26)
    assert plain == (12, 12), plain
    # window corner is 26 px up and left, so the card inside it lands at 12
    assert padded == (12 - 26, 12 - 26), padded


def test_where_it_was_dragged_to_beats_the_corner_and_stays_reachable(
) -> None:
    """A card dragged onto a monitor that is no longer plugged in must not
    come back somewhere nobody can see it."""
    screen = (1920, 1080)
    moved = overlay_mod.HintCard(corner="top-right", x=400, y=250)
    assert moved.moved() and moved.origin(300, 400, screen) == (400, 250)
    lost = overlay_mod.HintCard(corner="top-right", x=5000, y=4000)
    x, y = lost.origin(300, 400, screen)
    assert x < 1920 and y < 1080, (x, y)
    # and far enough on to be grabbed by the strip along its top
    assert x + 300 > 0 and y + 400 > 0, (x, y)
    # nothing saved at all still means the corner
    assert not overlay_mod.HintCard(corner="top-left").moved()


def test_a_card_left_on_the_screen_to_the_LEFT_stays_there() -> None:
    """The bug this is here for, and it shipped.

    A monitor to the left of the primary has NEGATIVE screen coordinates —
    on this machine the virtual desktop starts at x = -1920 — so a card
    dragged there saves a negative x. The sentinel for "never moved" was
    -1, `x >= 0` was the test for "has been moved", and the two collided:
    every drag onto that screen was written to config.toml correctly and
    thrown away on the next read, so the card snapped back beside the dot.
    Only drags that ended at a positive x and more than a shadow's depth
    below the top of the screen survived, which is what "it saves about one
    time in eight" looks like from the outside.
    """
    assert overlay_mod.HINT_UNSET == config_mod.HINT_UNSET
    assert overlay_mod.HINT_UNSET < -32768, (
        "the sentinel has to be past anything a virtual desktop can reach")
    primary = (2560, 1440)
    desktop = (-1920, 0, 4480, 1440)       # a second screen on the left
    for x, y in ((-369, 438), (-1900, 12), (-1, -1), (0, 0), (-26, -26)):
        card = overlay_mod.HintCard(corner="top-right", x=x, y=y)
        assert card.moved(), (x, y)
        got = card.origin(392, 528, primary, 26, desktop)
        assert got == (x - 26, y - 26), (x, y, got)


def test_what_is_saved_is_the_card_you_can_see_not_the_window() -> None:
    """The other half of the same bug. The glass window is bigger than the
    card by the room it leaves for its shadow, so saving the window's
    corner stored a y 26 px higher than anything on screen — negative for
    every drag near the top, which the sentinel then ate."""
    try:
        from skin import hint as skin_hint
    except Exception:
        return
    primary, desktop = (2560, 1440), (0, 0, 2560, 1440)
    inset = skin_hint.SHADOW
    card = overlay_mod.HintCard(corner="top-right")
    # what skin/hint.py does when a drag ends: window corner + the inset
    window_was = (700, -16)
    card.placed(window_was[0] + inset, window_was[1] + inset)
    assert (card.x, card.y) == (726, 10), (card.x, card.y)
    # and it comes back to exactly the window position it was dragged to
    assert card.origin(392, 528, primary, inset, desktop) == window_was


def test_an_unchanged_position_is_not_written_again() -> None:
    """A drag ends in more than one message and this is the line editor's
    most frequent caller."""
    saved = []
    card = overlay_mod.HintCard(on_change=saved.append)
    card.placed(300, 200)
    card.placed(300, 200)
    card.placed(300, 200)
    assert saved == [{"x": 300, "y": 200}], saved
    card.placed(301, 200)
    assert len(saved) == 2, saved


def test_moving_resizing_and_dismissing_are_written_down() -> None:
    """"I moved it" has to outlive the dictation it was moved during."""
    saved = []
    card = overlay_mod.HintCard(on_change=saved.append)
    card.placed(120, 340)
    card.resized(0.8)
    assert (card.x, card.y, card.scale) == (120, 340, 0.8)
    assert saved == [{"x": 120, "y": 340}, {"scale": 0.8}], saved
    # Ticking the box is not "hide it for now": the card stops accepting
    # anything at all, and the reason is written down.
    card.dismissed()
    assert saved[-1] == {"enabled": False}, saved
    card._thread = object()                # pretend it is running
    card.show({"a": 1})
    assert card._q.empty(), "a dismissed card still queued a picture"


def test_a_failed_save_never_reaches_the_keyboard_thread() -> None:
    """The card runs on the overlay thread; config.toml can be read-only,
    locked, or on a disconnected drive. None of that may kill the card."""
    def explode(_fields):
        raise OSError("config.toml is read-only")

    card = overlay_mod.HintCard(on_change=explode)
    card.placed(10, 20)                    # must not raise
    assert (card.x, card.y) == (10, 20)


def test_the_card_takes_the_mouse_in_four_places_and_nowhere_else() -> None:
    """Everything else answers HTTRANSPARENT, so a click aimed at the close
    button of a maximised window underneath still reaches it — the trap the
    status dot paid for once already."""
    try:
        from skin import glass as skin_glass, hint as skin_hint
    except Exception:
        return
    import main as main_mod

    card = hint_mod.card_for(_hint_cfg(), hint_mod.HOLD,
                             main_mod._SCREEN_ACTIONS)
    for scale in (0.6, 1.0, 1.4):
        boxes = skin_hint.regions(card, scale)
        width, height = skin_hint.measure(card, scale)
        pad = skin_hint.SHADOW
        for name, (x0, y0, x1, y1) in boxes.items():
            assert x1 > x0 and y1 > y0, (name, boxes[name])
            assert x0 >= pad - 8 and y0 >= pad - 8, (name, boxes[name])
            assert x1 <= pad + width + 8 and y1 <= pad + height + 8, (
                name, boxes[name], width, height)
            # every claimed rectangle answers something other than "pass
            # this through", and the middle of the card always passes
            code, what = skin_hint.hit_test(
                card, scale, (x0 + x1) / 2, (y0 + y1) / 2)
            assert what == name, (name, what)
            assert code != skin_glass.HTTRANSPARENT, (name, code)
        middle = skin_hint.hit_test(card, scale, pad + width / 2,
                                    pad + height / 2)
        assert middle == (skin_glass.HTTRANSPARENT, None), middle
        # and so does everything outside the card entirely
        assert skin_hint.hit_test(card, scale, 2, 2)[0] == \
            skin_glass.HTTRANSPARENT
    # the size buttons must not sit on top of each other
    boxes = skin_hint.regions(card, 1.0)
    assert boxes[skin_hint.SMALLER][2] <= boxes[skin_hint.BIGGER][0], boxes


def test_the_size_buttons_stop_at_the_ends_of_their_range() -> None:
    try:
        from skin import hint as skin_hint
    except Exception:
        return
    assert skin_hint.clamp_scale(99) == skin_hint.SCALE_MAX
    assert skin_hint.clamp_scale(0.01) == skin_hint.SCALE_MIN
    assert skin_hint.clamp_scale(1.0) == 1.0
    # and the range the card enforces is the range config.py will accept,
    # or a size chosen on screen would refuse to load next time
    assert skin_hint.SCALE_MIN == config_mod.HINT_SCALE_MIN
    assert skin_hint.SCALE_MAX == config_mod.HINT_SCALE_MAX


def test_a_saved_card_position_keeps_every_comment_in_the_config() -> None:
    """It is written from the overlay thread on every drag, so this is the
    line-editor's most frequent caller — a round-trip here would quietly
    delete the measurements the file is made of."""
    import shutil

    tmp = Path(tempfile.mkdtemp(prefix="dictation-hint-save-"))
    try:
        path = tmp / "config.toml"
        base = (Path(__file__).resolve().parent / "config.toml"
                ).read_text("utf-8")
        path.write_text(base, "utf-8")
        before = base.count("#")
        config_mod.set_values(path, {"hint.x": 640, "hint.y": 210,
                                     "hint.scale": 0.8})
        after = path.read_text("utf-8")
        assert after.count("#") == before, "comments were lost"
        cfg = config_mod.load(path)
        assert (cfg.hint.x, cfg.hint.y) == (640, 210), cfg.hint
        assert cfg.hint.scale == 0.8, cfg.hint
        config_mod.set_values(path, {"hint.enabled": False})
        assert config_mod.load(path).hint.enabled is False
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_a_disabled_card_never_starts_a_thread_or_a_window() -> None:
    card = overlay_mod.HintCard.off()
    card.start()
    assert card._thread is None
    card.show({"anything": True})           # must not raise, must not queue
    assert card._q.empty()
    card.stop()                             # and must not hang


def test_the_dot_and_the_card_can_never_disagree_about_a_recording(
) -> None:
    """One line in _set_state feeds both, which is the point.

    The early return that stops a stale "ready" from reporting a live
    microphone as finished has to cover the card as well — a card that
    stayed up after the dictation ended, or vanished while it ran, would
    be the same lie in a different font.
    """
    import main as main_mod

    app = main_mod.App.__new__(main_mod.App)
    app.cfg = _hint_cfg()
    app.hint = _FakeHint()
    seen = []
    app.dot = type("_Dot", (), {"set_state": lambda s, v: seen.append(v)})()
    app.machine = type("_M", (), {"state": hotkey_mod.RECORDING})()
    app._activity = "recording"

    app._set_state("ready")                 # stale, from the last dictation
    assert seen == [] and app.hint.shown == [], (seen, app.hint.shown)
    app._set_state("recording")
    assert app.hint.shown[-1]["state"] == hint_mod.HOLD
    app._set_state("locked")
    assert app.hint.shown[-1]["state"] == hint_mod.LATCHED
    app.machine.state = hotkey_mod.IDLE
    app._set_state("ready")
    assert app.hint.shown[-1] is None, app.hint.shown[-1]
    assert len(app.hint.shown) == len(seen), (app.hint.shown, seen)


def test_the_card_is_measured_from_its_rows_not_a_guess() -> None:
    """Its height decides the window's, so a wrong one clips the footer."""
    try:
        from skin import hint as skin_hint
    except Exception:
        return                              # no skia here: the Tk card runs
    import main as main_mod

    cfg = _hint_cfg()
    full = hint_mod.card_for(cfg, hint_mod.LATCHED, main_mod._SCREEN_ACTIONS)
    fewer = dataclasses.replace(cfg, punctuate_hotkey="", lookup_hotkey="",
                                translate_hotkey="", correct_hotkey="")
    small = hint_mod.card_for(fewer, hint_mod.LATCHED,
                              main_mod._SCREEN_ACTIONS)
    w1, h1 = skin_hint.measure(full)
    w2, h2 = skin_hint.measure(small)
    assert w1 == w2, (w1, w2)
    dropped = len(full["keys"]) - len(small["keys"])
    assert dropped == 4, dropped
    assert h1 - h2 == dropped * skin_hint.ROW_H, (h1, h2)


# --------------------------------------------------------------------------
# The first-run wizard (firstrun.py)
# --------------------------------------------------------------------------


def test_the_wizard_runs_once_per_copy_and_can_say_so_on_a_fresh_one(
) -> None:
    """The bug this is here for, caught before it shipped.

    "Has this been set up" was a line in config.toml for about an hour,
    and could not work there. config.toml is TRACKED, so the committed
    file is what a fresh download gets — `done = true` means nobody ever
    sees the wizard, `done = false` re-runs it on every install that
    updated — and `config.set_values` is a LINE EDITOR that can only
    change a key already in the file, so on any config.toml written before
    the section existed, marking the wizard finished RAISED. It would have
    come back on every launch, for ever, which is the one thing the wizard
    was asked not to do.

    So the record is a gitignored file: a fact about one installation, in
    the same place .env and vocab.json live.
    """
    import shutil

    import firstrun

    tmp = Path(tempfile.mkdtemp(prefix="dictation-setup-"))
    try:
        marker = tmp / ".setup-done"
        fresh = dataclasses.replace(
            config_mod.load(Path(__file__).resolve().parent / "config.toml"),
            setup=config_mod.SetupConfig(done=False))
        assert firstrun.needed(fresh, marker), "a fresh copy skipped setup"
        assert firstrun.mark_done(marker) is True
        assert marker.exists()
        assert not firstrun.needed(fresh, marker), "it asked a second time"
        # the config line is an override, and still works on its own
        off = dataclasses.replace(fresh,
                                  setup=config_mod.SetupConfig(done=True))
        assert not firstrun.needed(off, tmp / "nothing-here")
        # a marker that cannot be written is reported rather than assumed:
        # silently believing it had saved is how it comes back for ever
        assert firstrun.mark_done(tmp / "no-such-dir" / ".setup-done") is False
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_the_shipped_config_lets_a_fresh_download_see_the_wizard() -> None:
    """Whatever is committed here is what someone downloading this gets."""
    cfg = config_mod.load(Path(__file__).resolve().parent / "config.toml")
    assert cfg.setup.done is False, (
        "the committed config switches the wizard off, so no new install "
        "would ever see it — the per-copy record belongs in .setup-done")
    text = (Path(__file__).resolve().parent / ".gitignore").read_text("utf-8")
    assert ".setup-done" in text, "the per-copy marker would be committed"


def test_a_bluetooth_microphone_has_a_name_a_person_can_read() -> None:
    """Windows hands PortAudio the raw registry value for some devices,
    and for Bluetooth that is an unresolved indirect string with a driver
    path, a resource id and an embedded CRLF in it. Rendered as-is the row
    breaks in half and reads as a fault in this program."""
    import firstrun

    raw = ("Headset (@System32\\drivers\\bthhfenum.sys,#2;"
           "%1 Hands-Free%0\r\n;(Nothing Ear))")
    assert firstrun.clean_name(raw) == "Nothing Ear", firstrun.clean_name(raw)
    # an ordinary name is left exactly alone
    for name in ("Headset Microphone (Arctis 7 Chat)",
                 "Microphone (Realtek HD Audio Mic input)"):
        assert firstrun.clean_name(name) == name
    assert firstrun.clean_name("") == "?"
    assert "\n" not in firstrun.clean_name(raw)


def test_the_microphone_you_already_use_is_the_row_at_the_top() -> None:
    """The list is sorted WASAPI-first, and on this machine the device
    config.toml names is an MME one that landed ninth — so the row the
    owner actually uses was off the bottom of a list of their own
    microphones."""
    import firstrun

    listing = [(20, "webcam", "Windows WASAPI"),
               (21, "headset", "Windows WASAPI"),
               (1, "the one in config.toml", "MME"),
               (5, "line in", "Windows WDM-KS")]
    assert firstrun.order_for(listing, "1")[0][0] == 1
    assert len(firstrun.order_for(listing, "1")) == len(listing)
    # nothing selected changes nothing
    assert firstrun.order_for(listing, "") == listing
    assert firstrun.order_for(listing, "999") == listing


def test_the_wizards_test_runs_the_apps_own_backend() -> None:
    """The point of the step is to prove the pipeline the user is about to
    rely on. A wizard that passed on a simpler code path while the app
    failed would be worse than no wizard."""
    import firstrun

    cfg = dataclasses.replace(
        config_mod.load(Path(__file__).resolve().parent / "config.toml"),
        backend="fake")
    text, problem = firstrun.transcribe(cfg, frames_to_wav(
        [np.zeros(16000, dtype=np.int16)], 16000))
    assert not problem, problem
    # It went through transcribers.get_transcriber, so the backend named
    # in the config is the one that answered — here, the fake.
    assert text and "מזויף" in text, text
    # a broken backend is reported, not raised: this runs before the app
    broken = dataclasses.replace(cfg, backend="fake")
    object.__setattr__(broken, "backend", "no-such-backend")
    text, problem = firstrun.transcribe(broken, b"")
    assert text == "" and problem, (text, problem)


def test_the_meter_says_something_moved_before_anyone_gives_up() -> None:
    """Silence is not an error anywhere in Windows' audio API — the stream
    opens, the callbacks arrive, every sample is zero — so nothing
    downstream can report the privacy switch. The threshold has to sit
    above room noise and well below speech, and the wait has to be short
    enough to beat the conclusion that the app is broken."""
    import firstrun

    assert 0.01 < firstrun.SPEECH < 0.15, firstrun.SPEECH
    assert 3.0 <= firstrun.QUIET_S <= 12.0, firstrun.QUIET_S
    assert firstrun.TEST_S >= 2.0, firstrun.TEST_S


# ------------------------------------------------- the settings screen
#
# Nothing on it is typed by hand: settings.py reads config.toml and the
# dashboard draws what it found. The owner's rule, in his words: show all
# of them, so that a setting somebody else uses does not quietly drop off.


def _config_paths() -> set[str]:
    """Every key in the real config.toml as the dotted path set_values
    writes, straight from tomllib — the parser the app trusts."""
    import tomllib

    data = tomllib.loads((Path(__file__).resolve().parent / "config.toml")
                         .read_text("utf-8"))
    paths: set[str] = set()
    for key, value in data.items():
        if isinstance(value, dict):
            paths |= {f"{key}.{inner}" for inner in value}
        else:
            paths.add(key)
    return paths


def test_every_line_of_config_toml_is_a_setting_the_screen_can_draw() -> None:
    """The two parsers agree: the line scan that reads the comments found
    exactly the keys tomllib found, each on the line it sits on, with the
    kind tomllib gave its value."""
    import settings as settings_mod

    here = Path(__file__).resolve().parent
    sections = settings_mod.read(here / "config.toml")
    flat = settings_mod.flatten(sections)
    assert {s.path for s in flat} == _config_paths()
    assert len(flat) == len({s.path for s in flat}), "a key was read twice"
    lines = (here / "config.toml").read_text("utf-8").splitlines()
    for setting in flat:
        line = lines[setting.line - 1]
        assert line.lstrip().startswith(setting.key), (setting.path, line)
        assert setting.kind == settings_mod.kind_of(setting.value)
    names = [s.name for s in sections]
    assert names[:3] == ["", "hint", "setup"], names[:3]


def test_the_help_on_a_setting_is_the_comment_in_the_file() -> None:
    """Three kinds of comment, all read: the block under a header, the
    block above a key, and the key's own — what follows the value plus
    the indented lines under it. A menu at the front of a comment becomes
    the choices and leaves the help."""
    import settings as settings_mod

    sections = settings_mod.read(
        Path(__file__).resolve().parent / "config.toml")

    def find(path):
        setting = settings_mod.find(sections, path)
        assert setting is not None, path
        return setting

    hint = next(s for s in sections if s.name == "hint")
    assert hint.help.startswith("The card that appears while you are still "
                                "holding the key"), hint.help[:80]
    after = find("hint.after_ms")
    assert after.kind == "int" and after.choices == ()
    assert "how long the key must be held" in after.help, after.help
    assert "forgotten what the keys do" in after.help, \
        "the indented lines under the key were dropped"
    above = find("auto_pause_fullscreen")
    assert "Pause by itself while a game" in above.help, \
        "the block above the key was dropped"
    assert find("hotkey").help.startswith("hold = dictate Hebrew")
    for path, choices in (
            ("punctuate.prefer", ("groq", "gemini", "ollama")),
            ("hint.corner", ("top-right", "top-left", "bottom-right",
                             "bottom-left")),
            ("backend", ("gemini", "local", "fake")),
            ("polish.when", ("never", "known", "always")),
            ("local.device", ("auto", "cuda", "cpu"))):
        setting = find(path)
        assert setting.choices == choices, (path, setting.choices)
        assert " | " not in setting.help, (path, setting.help[:60])
    assert find("punctuate.prefer").help.startswith("Whichever goes first")
    general = sections[0]
    assert general.name == "" and general.title == "general"
    assert general.help.startswith("Hebrew push-to-talk dictation"), \
        "the file's preamble is the general section's"
    assert "Hebrew push-to-talk" not in find("hotkey").help
    terms = find("vocab.terms")
    assert terms.kind == "list" and not terms.editable
    prompt = find("local.initial_prompt")
    assert prompt.kind == "str" and not prompt.editable, \
        "Hebrew cannot be edited in a Tk field"
    assert find("audio.device").editable
    assert find("punctuate.auto").kind == "bool"


def test_the_plain_words_name_lines_the_file_has() -> None:
    """settings.TABS is the one hand-written thing on the screen, so it
    is the one thing that can go stale: every path it names must be in
    the file, every menu name must be a value the file allows, and no
    tab may name a line twice."""
    import settings as settings_mod

    sections = settings_mod.read(
        Path(__file__).resolve().parent / "config.toml")
    paths = _config_paths()
    assert settings_mod.TABS[0].name == "Common"
    assert settings_mod.tab_named(settings_mod.EVERYTHING) is None
    for tab in settings_mod.TABS:
        seen: list = []
        for group in tab.groups:
            for row in group.rows:
                assert row.path in paths, (tab.name, row.path)
                assert row.label, row.path
                assert row.path not in seen, (tab.name, row.path)
                seen.append(row.path)
                setting = settings_mod.find(sections, row.path)
                if row.names:
                    assert setting.kind == "str", row.path
                    if setting.choices:
                        assert ({v for v, _ in row.names}
                                == set(setting.choices)), \
                            (row.path, row.names, setting.choices)


def test_the_two_screens_cover_the_whole_file_between_them() -> None:
    """Keys on the Keys screen, every other line on Settings' last tab,
    nothing in neither — and each plain-words tab draws exactly the
    lines the words name. A new line in config.toml is on the screen the
    moment the file is saved; a new hotkey field has to be registered in
    HOTKEY_FIELDS, which the Keys screen tests already hold it to."""
    import settings as settings_mod

    import dashboard as dash

    with _window() as board:
        if board is None:
            return
        board._show("Settings")
        board._settings_go(settings_mod.EVERYTHING)
        board._finish_settings()
        drawn = set(board.parts["rows"])
        keys = dash._keys_screen_paths()
        assert not drawn & keys, drawn & keys
        assert drawn | keys == _config_paths(), \
            sorted(_config_paths() - drawn - keys)
        assert all(len(v) == 1 for v in board.parts["rows"].values())
        for tab in settings_mod.TABS:
            board._settings_go(tab.name)
            board._finish_settings()
            named = {row.path for group in tab.groups for row in group.rows}
            assert set(board.parts["rows"]) == named, \
                (tab.name, set(board.parts["rows"]) ^ named)


def test_the_settings_screen_can_reach_its_last_row() -> None:
    """The assertion the Keys screen once lacked: listing a row is not
    showing it. Scrolled to the end of Everything, the last line of the
    file has its control inside the viewport."""
    import settings as settings_mod

    import dashboard as dash

    try:
        board = dash.Dashboard()
    except Exception as e:                      # no display: nothing to test
        print(f"    (skipped: no Tk window — {e})")
        return
    try:
        board.closing = True
        board._show("Settings")
        board._settings_go(settings_mod.EVERYTHING)
        board._finish_settings()
        board.root.update()
        last = settings_mod.flatten(board.parts["sections"])[-1]
        _kind, widget = board.parts["rows"][last.path][-1]
        scroller = board.parts["settings_list"]
        scroller.canvas.yview_moveto(1.0)
        board.root.update()
        top = widget.winfo_rooty() - scroller.canvas.winfo_rooty()
        assert 0 <= top, f"{last.path} sits above the viewport ({top})"
        assert top + widget.winfo_height() <= scroller.canvas.winfo_height(), \
            f"{last.path} ends past the viewport — unreachable"
    finally:
        try:
            board.root.destroy()
        except Exception:
            pass


def test_a_switch_on_the_settings_screen_writes_one_dotted_line() -> None:
    """The write is config.set_values with the dotted path and nothing
    else — the line editor that keeps the comments. A refused value
    (set_values validates the whole file first) puts the switch back and
    says why, in both places the row is drawn."""
    with _window() as board:
        if board is None:
            return
        board._show("Settings")                 # opens on Common
        board._finish_settings()
        written: list = []
        real = config_mod.set_values
        config_mod.set_values = lambda path, updates: written.append(
            (Path(path).name, dict(updates)))
        try:
            [(kind, switch)] = board.parts["rows"]["punctuate.auto"]
            assert kind == "switch" and switch.get() is False, kind
            switch.toggle()
            assert written == [("config.toml", {"punctuate.auto": True})], \
                written
            assert board.parts["values"]["punctuate.auto"] is True
            assert "punctuate.auto saved" in board._toast_text, \
                board._toast_text
            # The same line on another tab shows the new value.
            board._settings_go("Text")
            board._finish_settings()
            [(kind, again)] = board.parts["rows"]["punctuate.auto"]
            assert again.get() is True, "the Text tab did not follow"

            def refuse(path, updates):
                raise config_mod.ConfigError("punctuate.auto must be a bool")
            config_mod.set_values = refuse
            again.toggle()
            assert again.get() is True, \
                "a refused write left the switch flipped"
            assert "must be a bool" in board._toast_text, board._toast_text
        finally:
            config_mod.set_values = real


def test_a_setting_changed_while_the_app_runs_goes_through_the_app() -> None:
    """One writer for config.toml. With the app running the dashboard
    sends `option` and lets the app write the line and take it live
    where it can; the reply's message is what the owner sees, and a
    refusal puts the control back."""
    import settings as settings_mod

    with _window() as board:
        if board is None:
            return
        board._show("Settings")
        board._settings_go("Text")
        board._finish_settings()
        board.running = True
        asked: list = []

        def ask(command, then=None, **args):
            asked.append((command, args))
            if then is not None:
                then({"ok": True, "message": f"{args['name']} saved"})

        def never(*_a, **_k):
            raise AssertionError("the dashboard wrote the file itself")

        board._ask = ask
        real = config_mod.set_values
        config_mod.set_values = never
        try:
            sections = board.parts["sections"]
            prefer = settings_mod.find(sections, "punctuate.prefer")
            [(kind, menu)] = board.parts["rows"]["punctuate.prefer"]
            assert kind == "dropdown" and menu.get() == "groq", \
                (kind, menu.get())
            assert menu.label_for("groq").startswith("Groq"), \
                "the menu shows the value, not its name"
            board._apply_setting(prefer, "ollama")
            assert asked == [("option", {"name": "punctuate.prefer",
                                         "value": "ollama"})], asked
            assert menu.get() == "ollama"
            assert board.parts["values"]["punctuate.prefer"] == "ollama"
            assert "punctuate.prefer saved" in board._toast_text

            def refuse(command, then=None, **args):
                then({"ok": False, "error": "punctuate.prefer must be one "
                                            "of groq, gemini, ollama"})
            board._ask = refuse
            board._apply_setting(prefer, "gemini")
            assert menu.get() == "ollama", "a refused pick stayed picked"
            assert "must be one of" in board._toast_text

            # A field: what was typed has to parse as what the file holds.
            board._settings_go("Card")
            board._finish_settings()
            after = settings_mod.find(sections, "hint.after_ms")
            [(kind, entry)] = board.parts["rows"]["hint.after_ms"]
            assert kind == "entry"
            entry.delete(0, "end")
            entry.insert(0, "abc")
            board._entry_done(after, entry)
            assert entry.get() == "400", entry.get()
            assert "not an int" in board._toast_text, board._toast_text
            board._ask = ask
            asked.clear()
            entry.delete(0, "end")
            entry.insert(0, "650")
            board._entry_done(after, entry)
            assert asked == [("option", {"name": "hint.after_ms",
                                         "value": 650})], asked
            board._entry_done(after, entry)
            assert len(asked) == 1, "an unchanged field was written again"
        finally:
            config_mod.set_values = real


def test_a_search_narrows_the_settings_to_the_lines_that_match() -> None:
    import settings as settings_mod

    import dashboard as dash

    with _window() as board:
        if board is None:
            return
        board._show("Settings")
        board._settings_open_search()
        assert board._settings_searching
        board._settings_search("punctuat")
        board._finish_settings()
        drawn = set(board.parts["rows"])
        expected = {s.path
                    for s in settings_mod.flatten(board.parts["sections"])
                    if settings_mod.matches(s, "punctuat")}
        expected -= dash._keys_screen_paths()
        assert drawn == expected, drawn ^ expected
        assert "punctuate.auto" in drawn and "hint.after_ms" not in drawn
        assert all(len(v) == 1 for v in board.parts["rows"].values())
        board._settings_search("no such setting anywhere")
        board._finish_settings()
        assert board.parts["rows"] == {}
        # The cross: the tabs come back, on the tab that was up.
        board._settings_close_search()
        board._finish_settings()
        assert not board._settings_searching and not board._settings_query
        common = {row.path for group in settings_mod.TABS[0].groups
                  for row in group.rows}
        assert set(board.parts["rows"]) == common


# ------------------------------------------------- auto punctuation


def test_auto_punctuation_ships_off_and_the_knobs_around_it_validate() -> None:
    """One switch, off. The file says so, the dataclass says so, and the
    validation refuses the two values that would make the switch lie: a
    backend that is not in the chain, and a deadline of nothing."""
    import shutil
    import tempfile

    here = Path(__file__).resolve().parent
    cfg = config_mod.load(here / "config.toml")
    assert cfg.punctuate.auto is False
    assert config_mod.PunctuateConfig().auto is False
    assert cfg.punctuate.max_wait_s > 0
    assert cfg.punctuate.prefer == "groq", cfg.punctuate.prefer
    tmp = Path(tempfile.mkdtemp(prefix="dictation-punct-"))
    try:
        copy = tmp / "config.toml"
        shutil.copy(here / "config.toml", copy)
        config_mod.set_values(copy, {"punctuate.auto": True})
        assert config_mod.load(copy).punctuate.auto is True
        for bad in ({"punctuate.prefer": "cerebras"},
                    {"punctuate.max_wait_s": 0}):
            before = copy.read_bytes()
            try:
                config_mod.set_values(copy, bad)
            except config_mod.ConfigError as e:
                assert "punctuate" in str(e), e
            else:
                raise AssertionError(f"{bad} was accepted")
            assert copy.read_bytes() == before, \
                "a refused value reached the file"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_the_auto_pass_runs_after_the_repair_and_pastes_only_what_the_guard_allows() -> None:  # noqa: E501
    """Between the repair pass and the paste, bounded, and never a reason
    for the transcript not to land: a safe reply is pasted, an unsafe one
    is dropped for the raw text, a slow one is abandoned at the deadline,
    a two-word answer is left alone, and with the switch off the backend
    is never asked."""
    import dataclasses
    import shutil
    import tempfile
    import time as time_mod

    import main as main_mod

    said = "תריץ את זה שוב בבקשה"
    fixed = "תריץ את זה שוב, בבקשה."
    tmp = Path(tempfile.mkdtemp(prefix="dictation-autopunct-"))
    fake = _FakeInjector()
    real = main_mod.injector
    try:
        main_mod.injector = fake

        def app_with(backend, auto=True, max_wait_s=6.0, text=said):
            app = _worker_app(_Flaky(fail_times=0, text=text), tmp)
            app.cfg = dataclasses.replace(
                app.cfg, punctuate=dataclasses.replace(
                    app.cfg.punctuate, auto=auto, max_wait_s=max_wait_s))
            app._punctuator = _punctuator(backend)
            return app

        def pasted():
            texts = [c[2] for c in fake.calls if c[0] == "replace"]
            fake.calls.clear()
            return texts

        good = _FakePunctuateBackend("groq", reply=fixed)
        app = app_with(good)
        app._handle(b"RIFF-audio", 4.0, fake.focus, None, False)
        assert pasted() == [fixed] and good.calls == 1
        assert app._last["final"] == fixed and app._last["raw"] == said, \
            app._last

        bad = _FakePunctuateBackend("groq", reply="Sure, running it again!")
        app_with(bad)._handle(b"RIFF-audio", 4.0, fake.focus, None, False)
        assert pasted() == [said], "an unsafe reply reached the cursor"

        class _Slow:
            name = "ollama"

            def translate(self, text):
                time_mod.sleep(1.5)
                return fixed

        started = time_mod.monotonic()
        app_with(_Slow(), max_wait_s=0.2)._handle(b"RIFF-audio", 4.0,
                                                  fake.focus, None, False)
        assert pasted() == [said]
        assert time_mod.monotonic() - started < 1.2, \
            "the paste waited past the deadline"

        off = _FakePunctuateBackend("groq", reply=fixed)
        app_with(off, auto=False)._handle(b"RIFF-audio", 4.0, fake.focus,
                                          None, False)
        assert pasted() == [said] and off.calls == 0

        short = _FakePunctuateBackend("groq", reply="כן, בטח.")
        app_with(short, text="כן בטח")._handle(b"RIFF-audio", 4.0,
                                                fake.focus, None, False)
        assert pasted() == ["כן בטח"] and short.calls == 0, \
            "two words are an answer, not a sentence"
    finally:
        main_mod.injector = real
        shutil.rmtree(tmp, ignore_errors=True)


def test_set_option_writes_first_and_takes_the_live_ones_into_the_running_app() -> None:  # noqa: E501
    """The dashboard's one path to a running app's settings. The line is
    written and validated before anything else; a live section replaces
    its block of the running Config and throws away the worker built on
    the old one; the rest is written and honestly reported as waiting
    for a restart; a bad value never reaches the file."""
    import shutil
    import tempfile
    import time as time_mod

    import main as main_mod
    import overlay as overlay_mod

    here = Path(__file__).resolve().parent
    tmp = Path(tempfile.mkdtemp(prefix="dictation-option-"))
    try:
        copy = tmp / "config.toml"
        shutil.copy(here / "config.toml", copy)
        app = main_mod.App.__new__(main_mod.App)
        app.cfg = config_mod.load(copy)
        app.config_path = copy
        app._punctuator = app._translator = app._polisher = object()
        app._watcher, app._auto_paused = None, False
        app._note = ""
        app._say = lambda message: None
        stopped: list = []

        class _Hint:
            def stop(self):
                stopped.append(True)

        app.hint = _Hint()

        message = app.set_option("punctuate.auto", True)
        assert "punctuate.auto saved" in message and "next time" not in message, \
            message
        assert config_mod.load(copy).punctuate.auto is True
        assert app.cfg.punctuate.auto is True
        assert app._punctuator is None, \
            "the worker built on the old Config was kept"
        assert app._translator is not None, \
            "an unrelated worker was thrown away"

        message = app.set_option("local.beam_size", 3)
        assert "next time" in message, message
        assert config_mod.load(copy).local.beam_size == 3
        assert app.cfg.local.beam_size == 5, \
            "a setting the app cannot take live was taken anyway"

        before = copy.read_bytes()
        try:
            app.set_option("punctuate.prefer", "cerebras")
        except config_mod.ConfigError:
            pass
        else:
            raise AssertionError("a bad value was accepted")
        assert copy.read_bytes() == before
        assert app.cfg.punctuate.prefer == "groq"

        app.set_option("hint.enabled", False)
        for _ in range(60):
            if stopped and isinstance(app.hint, overlay_mod.HintCard):
                break
            time_mod.sleep(0.05)
        assert stopped, "the old card was not stopped"
        assert isinstance(app.hint, overlay_mod.HintCard), app.hint
        assert not app.hint._enabled and app.cfg.hint.enabled is False
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_the_punctuation_chain_is_prefer_first_then_the_rest_in_order() -> None:
    """groq first by default (measured — see punctuate.ORDER), and whoever
    is preferred, the other two follow; a backend that cannot be built on
    this version — classic's translate.py has no Groq — is left out
    rather than failing the press."""
    import dataclasses

    import punctuate as punctuate_mod
    import translate as translate_mod

    cfg = config_mod.load(Path(__file__).resolve().parent / "config.toml")
    for prefer, expected in (("groq", ["groq", "gemini", "ollama"]),
                             ("gemini", ["gemini", "groq", "ollama"]),
                             ("ollama", ["ollama", "groq", "gemini"])):
        p = punctuate_mod.Punctuator(dataclasses.replace(
            cfg, punctuate=dataclasses.replace(cfg.punctuate, prefer=prefer)))
        p._groq_backend = lambda: _FakePunctuateBackend("groq")
        p._gemini_backend = lambda: _FakePunctuateBackend("gemini")
        p._ollama_backend = lambda: _FakePunctuateBackend("ollama")
        chain = [b.name for b in p._backends()]
        assert chain == expected, (prefer, chain)
    real = translate_mod.GroqTranslator
    del translate_mod.GroqTranslator
    try:
        p = punctuate_mod.Punctuator(cfg)
        p._gemini_backend = lambda: _FakePunctuateBackend("gemini")
        p._ollama_backend = lambda: _FakePunctuateBackend("ollama")
        assert [b.name for b in p._backends()] == ["gemini", "ollama"]
    finally:
        translate_mod.GroqTranslator = real


def test_the_auto_pass_gives_up_at_its_deadline_and_the_key_never_does() -> None:
    import time as time_mod

    class _Slow:
        name = "ollama"

        def translate(self, text):
            time_mod.sleep(1.0)
            return "שלום, עולם."

    started = time_mod.monotonic()
    try:
        _punctuator(_Slow()).punctuate("שלום עולם", max_wait_s=0.2)
    except TimeoutError as e:
        assert "ollama" in str(e), e
    else:
        raise AssertionError("the deadline did not fire")
    assert time_mod.monotonic() - started < 0.8
    text, backend = _punctuator(_Slow()).punctuate("שלום עולם")
    assert (text, backend) == ("שלום, עולם.", "ollama")


def test_a_menu_opens_under_its_pill_and_a_pick_closes_it() -> None:
    """The one control on the Settings screen that is neither a switch
    nor a field. It shows the NAME of a value, not the value; it closes
    on a pick and on Escape; and it tells its owner only when the value
    actually changed."""
    import tkinter as tk

    import ui as ui_mod
    root = _tk_or_skip()
    if root is None:
        return
    try:
        picked: list = []
        menu = ui_mod.Dropdown(root, [("groq", "Groq — fast"),
                                      ("gemini", "Gemini"),
                                      ("ollama", "Ollama")],
                               "groq", command=picked.append)
        menu.pack()
        root.update()
        assert menu.get() == "groq"
        assert menu.label_for("groq") == "Groq — fast"
        assert menu.label_for("something else") == "something else"
        menu.open()
        root.update()
        popup = menu._popup
        assert isinstance(popup, tk.Toplevel), popup
        rows = popup.winfo_children()[0].winfo_children()
        assert [row.cget("text") for row in rows] == ["Groq — fast",
                                                      "Gemini", "Ollama"]
        menu._pick("ollama")
        root.update()
        assert picked == ["ollama"] and menu.get() == "ollama"
        assert menu._popup is None, "the pick did not close the list"
        menu.open()
        root.update()
        menu._pick("ollama")
        assert picked == ["ollama"], "an unchanged pick was reported"
        menu.open()
        root.update()
        assert menu._popup is not None
        menu._popup.event_generate("<Escape>")
        root.update()
        assert menu._popup is None, "Escape did not close the list"
        menu.set("gemini")
        assert menu.get() == "gemini" and picked == ["ollama"], \
            "set() is a repaint, not a pick"
    finally:
        root.destroy()


# --------------------------------------------------------------------------
# The second reading (review.py, review_card.py, overlay.ReviewCard)
# --------------------------------------------------------------------------

# The 2026-09-02 clip: five real words, then 24 the decoder invented and
# stamped into the last 140 ms. Two other decodes of the same audio stop at
# the fifth word.
_INVENTED = ("תעצור, זהו. כבר יש קובץ שואל הרצץ מיוחדים במהלך שלנו ואין לנו "
             "את זה כדי לדבר על איזה תקופת דעתי. אני רוצה להגיד לכם שאלותיי "
             "בעיקרונות נוספות בוועדות הכניסטוריות")
_HEARD_SHORT = ["תעצור זהו, כבר יש קובץ", "תעצור, זהו. כבר יש קובץ."]


def test_the_invented_tail_is_found_from_the_decodes_alone() -> None:
    """No language model needed: an ending no other decode heard is a
    drop, and applying it leaves the five words that were said."""
    import review as review_mod
    change = review_mod.tail_drop(_INVENTED, [], _HEARD_SHORT)
    assert change is not None and change["kind"] == "drop", change
    assert change["span"] == [5, 29], change["span"]
    assert change["before"].startswith("שואל הרצץ"), change["before"]
    fixed = review_mod.apply_changes(_INVENTED, [change])
    assert fixed == "תעצור, זהו. כבר יש קובץ", fixed
    assert review_mod.tail_drop(_INVENTED, [], _HEARD_SHORT[:1]) is None, \
        "one witness is an anecdote"
    assert review_mod.tail_drop(_INVENTED, [], [_INVENTED, _INVENTED]) \
        is None, "decodes that heard the whole thing propose nothing"
    # the card shows how a long tail starts, not all 24 words
    snip = review_mod.snippet(_INVENTED, change)
    assert snip["word"].endswith("…") and len(snip["word"].split()) == 6, snip
    assert snip["was"] == change["before"]


def test_the_decoders_own_confidence_gates_the_drop() -> None:
    """A tail two decodes missed but the live decoder was SURE of is a
    VAD difference, not an invention; a single doubted word is dropped
    only when the decoder barely believed it (שאלות at p=0.21 on silence,
    the second clip of 2026-09-02)."""
    import review as review_mod
    text = "מה אני לא אמרתי את קודם אלא אמרתי רק תעצור זהו כבר יש קובץ שאלות"
    heard = ["מה אני לא אמרתי את קודם אלא אמרתי רק תעצור זהו כבר יש קובץ",
             "מה אני לא אמרתי את קודם אני אמרתי רק תעצר זהו כבר יש קובץ"]
    words = [(w, 0.0, 0.0, 0.95) for w in text.split()]
    words[-1] = ("שאלות", 4.56, 5.26, 0.21)
    change = review_mod.tail_drop(text, words, heard)
    assert change is not None and change["before"] == "שאלות", change
    words[-1] = ("שאלות", 4.56, 5.26, 0.5)
    assert review_mod.tail_drop(text, words, heard) is None, \
        "one word at p=0.5 is a doubt, not an invention"
    sure = [(w, 0.0, 0.0, 0.99) for w in _INVENTED.split()]
    assert review_mod.tail_drop(_INVENTED, sure, _HEARD_SHORT) is None, \
        "a confident tail is kept even when the other decodes lack it"
    plain = _INVENTED.replace(",", "").replace(".", "").split()
    doubted = [(w, 0.0, 0.0, 0.99 if i < 5 else 0.3)
               for i, w in enumerate(plain)]
    change = review_mod.tail_drop(_INVENTED, doubted, _HEARD_SHORT)
    assert change is not None and change["span"] == [5, 29], change


def test_proposals_are_checked_in_code_not_in_the_prompt() -> None:
    """Every rule the prompt states is enforced here: "before" must be in
    the text, spans are bounded, nothing may overlap, and a reply that
    would touch a quarter of the words is a rewrite, discarded whole."""
    import review as review_mod
    text = "טוב, אז הלכתי לאכול מטוס עם החברים ואחר כך חזרנו הביתה ברגל"
    heard = ["טוב אז הלכתי לאכול מנטוס עם החברים ואחר כך חזרנו הביתה ברגל"]
    got = review_mod.validate(text, [
        {"before": "מטוס", "after": "מנטוס", "why": "אוכלים מנטוס"},
        {"before": "אווירון", "after": "מנטוס", "why": "not in the text"},
        {"before": "הלכתי לאכול מטוס עם", "after": "x", "why": "four words"},
        {"before": "ברגל", "after": "ברגל", "why": "no change"},
        {"before": "לאכול מטוס", "after": "לשתות", "why": "overlaps"},
    ], heard, witness=1)
    assert [c["before"] for c in got] == ["מטוס"], got
    assert got[0]["span"] == [4, 5] and got[0]["support"] == 1, got[0]
    assert got[0]["family"] == "context" and got[0]["kind"] == "replace"
    rewrite = [{"before": w, "after": w + "x", "why": ""}
               for w in ("טוב", "אז", "הלכתי", "לאכול", "מטוס")]
    assert review_mod.validate(text, rewrite, heard, max_changes=8,
                               witness=0) == []
    assert review_mod.validate(text, [{"before": "מטוס", "after": ""}],
                               heard) == [], "an empty after is not a change"
    # THE WITNESSES: a word no decode heard is a guess, unless taught;
    # one decode is the general model's own mishearing, two is evidence
    guess = [{"before": "ברגל", "after": "באוטו", "why": "guess"}]
    assert review_mod.validate(text, guess, heard, witness=1) == []
    taught = review_mod.validate(text, guess, heard,
                                 glossary=[("ברגל", "באוטו")])
    assert [c["after"] for c in taught] == ["באוטו"], taught
    loose = review_mod.validate(text, guess, heard, witness=0)
    assert [c["after"] for c in loose] == ["באוטו"], loose
    one = [{"before": "מטוס", "after": "מנטוס", "why": ""}]
    assert review_mod.validate(text, one, heard, witness=2) == [], \
        "one decode heard it: not enough"
    twice = review_mod.validate(text, one, heard * 2, witness=2)
    assert [c["support"] for c in twice] == [2], twice


def test_apply_and_snippet_keep_the_sentence_around_a_change() -> None:
    import review as review_mod
    text = "טוב, אז הלכתי לאכול מטוס עם החברים ואחר כך חזרנו הביתה ברגל"
    change = {"before": "מטוס", "after": "מנטוס", "kind": "replace",
              "span": [4, 5], "why": "x"}
    assert review_mod.apply_changes(text, [change]) == \
        text.replace("מטוס", "מנטוס")
    snip = review_mod.snippet(text, change, side=2)
    assert snip["right"] == "…הלכתי לאכול" and snip["left"] == "עם החברים…", \
        snip
    assert snip["word"] == "מנטוס" and snip["was"] == "מטוס"
    drop = {"before": "הביתה ברגל", "after": "", "kind": "drop",
            "span": [10, 12], "why": "y"}
    assert review_mod.apply_changes(text, [drop]) == \
        "טוב, אז הלכתי לאכול מטוס עם החברים ואחר כך חזרנו"
    both = review_mod.apply_changes(text, [change, drop])
    assert both == "טוב, אז הלכתי לאכול מנטוס עם החברים ואחר כך חזרנו", both


def test_a_reply_is_parsed_with_its_wrappers_and_refused_without_an_array(
        ) -> None:
    import review as review_mod
    one = '[{"before": "a", "after": "b", "why": "c"}]'
    assert review_mod.parse_reply(one) == [{"before": "a", "after": "b",
                                            "why": "c"}]
    assert review_mod.parse_reply("```json\n[]\n```") == []
    assert review_mod.parse_reply(
        'Sure: {"changes": [{"before": "a", "after": "b"}]}') == \
        [{"before": "a", "after": "b"}]
    assert review_mod.parse_reply("I could not find anything.") is None
    assert review_mod.parse_reply("") is None


def test_the_store_keeps_a_proposal_until_someone_answers_it() -> None:
    import shutil
    import review as review_mod
    tmp = Path(tempfile.mkdtemp(prefix="review-"))
    try:
        store = review_mod.Store(tmp / "review.json")
        store.add({"id": "a", "when": "2026-09-02 16:08:31", "text": "x",
                   "proposed": "y", "status": "pending", "learned": False,
                   "changes": [{"before": "x", "after": "y",
                                "kind": "replace", "family": "context"}]})
        assert [i["id"] for i in store.pending()] == ["a"]
        assert store.unlearned() == []
        decided = store.decide("a", "accepted", by="card")
        assert decided and decided["status"] == "accepted" \
            and decided["by"] == "card", decided
        assert store.pending() == []
        assert [i["id"] for i in store.unlearned()] == ["a"]
        assert store.decide("a", "rejected") is None, "decided once"
        store.mark_learned("a")
        assert store.unlearned() == []
        summary = store.summary()
        assert summary["accepted"] == 1 and summary["pending"] == 0, summary
        assert summary["families"]["context"]["accepted"] == 1, summary
        assert summary["top"] == [(("x", "y"), 1)], summary["top"]
        again = review_mod.Store(tmp / "review.json")   # another process
        assert again.decided()[0]["id"] == "a"
        try:
            store.decide("a", "maybe")
        except ValueError:
            pass
        else:
            raise AssertionError("an unknown verdict was accepted")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


class _ReviewRecent:
    """A recent\\ spool stand-in: the members review.Engine touches."""

    def __init__(self, items, root):
        self._items = items
        self.dir = root

    def pending(self):
        return list(self._items)

    def update(self, item, **fields):
        item.meta.update(fields)


class _ReviewReader:
    def __init__(self, proposals):
        self._proposals = proposals
        self.asked = 0

    def ask(self, final, variants, glossary=(), context=()):
        self.asked += 1
        return self._proposals


class _NoCorpus:
    def admit(self, *a, **k):
        return False


def test_the_engine_proposes_on_a_card_and_learns_only_what_was_accepted(
        ) -> None:
    """The whole channel, no models and no network: a clip is read, a
    card goes up, nothing is learned until a verdict — and a rejection
    teaches nothing while an acceptance teaches the pair."""
    import shutil
    import review as review_mod
    text = "טוב, אז הלכתי לאכול מטוס עם החברים"
    tmp = Path(tempfile.mkdtemp(prefix="review-"))
    try:
        item = _StudyItem(tmp / "clip.wav",
                          {"text": text, "raw": text, "seconds": 3.0},
                          seconds=3.0)
        recent = _ReviewRecent([item], tmp)
        v = vocab_mod.Vocab(tmp / "vocab.json")
        shown, applied = [], []
        engine = review_mod.Engine(
            _hint_cfg(),
            _StudyTranscriber(wide="טוב אז הלכתי לאכול מנטוס עם החברים",
                              general="טוב אז הלכתי לאכול מנטוס עם החברים",
                              loose="טוב אז הלכתי לאכול מטוס עם החברים"),
            v, recent, review_mod.Store(tmp / "review.json"),
            model_lock=None, quiet=lambda: True, app_dir=tmp,
            on_suggest=shown.append, on_accept=applied.append,
            reader=_ReviewReader([{"before": "מטוס", "after": "מנטוס",
                                   "why": "אוכלים מנטוס"}]),
            corpus=_NoCorpus())
        engine._read(item, 0, True, 0)
        assert len(shown) == 1, shown
        change = shown[0]["changes"][0]
        assert change["after"] == "מנטוס" and change["support"] == 2, change
        assert shown[0]["proposed"] == text.replace("מטוס", "מנטוס")
        assert item.meta["review"]["engine"] == review_mod.ENGINE
        assert item.meta["review"]["changes"] == 1
        assert not review_mod.needs_review(item), "read once, stamped once"
        sid = shown[0]["id"]
        waiting = engine.store.pending()
        assert waiting[0]["id"] == sid and waiting[0]["shown"], waiting
        assert v.terms() == [] and v.glossary() == [], \
            "a card going up teaches nothing"
        engine._decide(sid, "rejected", "card")
        assert v.glossary() == [] and applied == [], \
            "a rejection teaches nothing"
        engine.store.add(dict(shown[0], id="again", status="pending",
                              learned=False))
        engine._decide("again", "accepted", "dashboard")
        assert ("מטוס", "מנטוס") in v.glossary(), v.glossary()
        assert applied and applied[0]["id"] == "again"
        assert engine.store.unlearned() == []
        assert engine.store.get("again")["by"] == "dashboard"
        # The repair pass had already rewritten the word before the paste:
        # the lesson is keyed on what the DECODER wrote at that spot.
        repaired = dict(shown[0], id="raw", status="pending", learned=False,
                        raw="טוב, אז הלכתי לאכול מאטוס עם החברים")
        engine.store.add(repaired)
        engine._decide("raw", "accepted", "card")
        assert ("מאטוס", "מנטוס") in v.glossary(), v.glossary()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_an_accepted_card_teaches_the_decoders_word_not_the_repairs() -> None:
    """2026-09-02 22:38: the card said קומפלט, the decoder had said קומית
    and the repair pass had rewritten it; accepting must teach קומית."""
    import review as review_mod
    text = "הפעלתי מחדש, במידה וזה יעבוד תעשה קומפלט"
    raw = "הפעלתי מחדש, במידה וזה יעבוד תעשה קומית"
    assert review_mod.decoder_form(text, raw, [6, 7]) == "קומית"
    assert review_mod.decoder_form(text, raw, [0, 1]) == "הפעלתי"
    assert review_mod.decoder_form(text, text, [6, 7]) == "קומפלט"
    # a span the decoder had no words for, or a whole sentence's worth
    assert review_mod.decoder_form(text, "הפעלתי מחדש", [6, 7]) == ""
    assert review_mod.decoder_form("א ב ג ד ה ו", "x y z w v u q r", [0, 6]) == ""


def test_a_hebrew_one_hit_correction_stays_out_of_the_decoder_prompt() -> None:
    """The 2026-09-02 bug, as a rule. Nine Hebrew pairs learned from one
    correction each sat at the tail of the hotword prompt and the decoder
    echoed them into a 2.8 s clip; a name in Latin letters is what the
    prompt is for and still gets in at once."""
    v = _tmp_vocab(seed_terms=("GitHub",), hebrew_after_hits=3)
    for heard, meant in (("אירוע פה", "יש לי ריפו"), ("גיטאבים", "גיטאהאב"),
                         ("ארצות המיליון", "הרצץ מיליון"),
                         ("xpogo", "Expo Go")):
        v.learn(heard, meant)
    assert v.terms() == ["GitHub", "Expo Go"], v.terms()
    assert ("אירוע פה", "יש לי ריפו") in v.glossary(), \
        "the repair pass still hears about it"
    v.learn("גיטאבים", "גיטאהאב")
    v.learn("גיטאבים", "גיטאהאב")
    assert "גיטאהאב" in v.terms(), "three corrections is a name, not a word"
    assert "יש לי ריפו" not in v.terms()
    import study as study_mod
    assert study_mod.family("ארצות המיליון", "הרצץ מיליון") == "context"
    assert study_mod.family("xpogo", "Expo Go") == "term"


def test_the_review_card_is_measured_from_its_rows_and_pressed_where_drawn(
        ) -> None:
    import review_card as rc
    suggestion = {"id": "s", "text": "טוב, אז הלכתי לאכול מטוס עם החברים",
                  "changes": [{"before": "מטוס", "after": "מנטוס",
                               "why": "אוכלים מנטוס", "kind": "replace",
                               "span": [4, 5], "family": "context",
                               "support": 1}]}
    card = rc.card_for(suggestion, seconds=20)
    assert card["id"] == "s" and len(card["rows"]) == 1 and card["more"] == 0
    row = card["rows"][0]
    assert row["word"] == "מנטוס" and row["was"] == "מטוס", row
    assert "במקום: מטוס" in rc.note_for(row), rc.note_for(row)
    w, h = rc.measure(card)
    five = rc.card_for(dict(suggestion, changes=suggestion["changes"] * 5),
                       seconds=20)
    assert len(five["rows"]) == rc.MAX_ROWS and five["more"] == 2, five
    assert rc.measure(five)[1] > h, "more rows, taller card"
    boxes = rc.regions(card)
    for name, _w in rc.BUTTONS:
        x0, y0, x1, y1 = boxes[name]
        assert rc.SHADOW <= x0 < x1 <= rc.SHADOW + w, (name, boxes[name])
        assert rc.SHADOW <= y0 < y1 <= rc.SHADOW + h, (name, boxes[name])
        assert rc.hit_test(card, 1.0, (x0 + x1) / 2, (y0 + y1) / 2) == \
            (rc.HTCLIENT, name), name
    assert rc.hit_test(card, 1.0, rc.SHADOW + 10, rc.SHADOW + 10) == \
        (rc.HTCAPTION, rc.DRAG)
    assert rc.hit_test(card, 1.0, 2, 2) == (rc.HTTRANSPARENT, None), \
        "the shadow margin is not ours"
    img = rc.compose(card, 1.0, 0.5, hover=rc.ACCEPT, cache={})
    assert img.size == (w, h), (img.size, (w, h))
    assert rc.flat(card, 1.2, 1.0).size == rc.measure(card, 1.2)


def test_the_pencil_asks_and_the_typed_word_is_what_is_learned() -> None:
    """The fourth answer: neither yes nor no but "this". The card hands
    the row and its own rect to on_edit; the store swaps the proposal for
    the typed word (or drops the change when the typed word IS the
    pasted one); the engine learns the typed pair."""
    import shutil
    import review as review_mod
    import review_card as rc
    asked = []
    card = overlay_mod.ReviewCard(on_edit=lambda sid, row, rect:
                                  asked.append((sid, row, rect)),
                                  keys={"edit": "e"})
    card._current, card.rect = "s", (10, 20, 30, 40)
    card.pressed("edit1")
    assert asked == [("s", 1, (10, 20, 30, 40))] and not card.visible()
    card._current = "t"
    card.hovering = lambda: True
    assert card.on_key(vk_for("e")) and asked[-1] == ("t", 0, (10, 20, 30, 40)), \
        "the key is the first row's pencil"
    # the geometry: one pencil per row, hit where drawn
    suggestion = {"id": "s", "text": "טוב, אז הלכתי לאכול מטוס עם החברים",
                  "changes": [{"before": "מטוס", "after": "מנטוס",
                               "why": "x", "kind": "replace",
                               "span": [4, 5], "family": "context"}] * 2}
    c = rc.card_for(suggestion, seconds=20)
    boxes = rc.regions(c)
    assert "edit0" in boxes and "edit1" in boxes and "edit2" not in boxes
    x0, y0, x1, y1 = boxes["edit1"]
    assert rc.hit_test(c, 1.0, (x0 + x1) / 2, (y0 + y1) / 2) == \
        (rc.HTCLIENT, "edit1")
    assert c["keys"][rc.EDIT] == "E"
    rc.compose(c, 1.0, 1.0, hover="edit1", cache={})
    # the store and the engine
    tmp = Path(tempfile.mkdtemp(prefix="review-pencil-"))
    try:
        text = "טוב, אז הלכתי לאכול מטוס עם החברים"
        base = {"when": "2026-09-02 22:00:00", "text": text, "raw": text,
                "proposed": text.replace("מטוס", "מנטוס"), "status": "pending",
                "learned": False,
                "changes": [{"before": "מטוס", "after": "מנטוס", "why": "x",
                             "kind": "replace", "span": [4, 5],
                             "family": "context", "support": 2}]}
        store = review_mod.Store(tmp / "review.json")
        store.add(dict(base, id="typed"))
        store.add(dict(base, id="same"))
        done = store.decide("typed", "accepted", by="pencil",
                            edits={0: " מנטוסים "})
        assert done["changes"][0]["after"] == "מנטוסים", done["changes"]
        assert done["changes"][0]["why"] == review_mod.WHY_TYPED
        assert done["proposed"] == text.replace("מטוס", "מנטוסים"), done
        same = store.decide("same", "accepted", by="pencil", edits={0: "מטוס"})
        assert same["status"] == "rejected" and same["changes"] == [], same
        assert same["proposed"] == text
        v = vocab_mod.Vocab(tmp / "vocab.json")
        item = _StudyItem(tmp / "typed.wav", dict(base), seconds=3.0)
        engine = review_mod.Engine(
            _hint_cfg(), _StudyTranscriber(wide=text), v,
            _ReviewRecent([item], tmp), store, model_lock=None,
            quiet=lambda: True, app_dir=tmp, reader=_ReviewReader([]),
            corpus=_NoCorpus())
        store.add(dict(base, id="learn"))
        engine._decide("learn", "accepted", "pencil", {0: "מנטוסים"})
        assert ("מטוס", "מנטוסים") in v.glossary(), v.glossary()
        assert store.get("learn")["learned"]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_the_word_prompt_answers_and_buries_its_window() -> None:
    """The box hands back what it holds when answered, is gone before it
    reports, and takes one question at a time. Answered through the
    hook, never the keyboard: a synthetic Enter aimed at a box that did
    not get the foreground lands in the owner's window (it did, once).
    A subprocess, like every card that owns a Tcl interpreter."""
    _run_window_script('''
import os, threading, time
import overlay

got = []
done = threading.Event()
prompt = overlay.WordPrompt()
assert prompt.ask("מנטוס", (200, 200, 600, 400),
                  lambda t: (got.append(t), done.set()), focus=False)
time.sleep(0.8)
assert prompt.open(), "the box never opened"
assert not prompt.ask("x", None, lambda t: None, focus=False), \
    "one question at a time"
prompt.answer("מנטוסים")
assert done.wait(5), "the answer never came back"
assert got == ["מנטוסים"], got
assert not prompt.open()
done.clear()
assert prompt.ask("a", None, lambda t: (got.append(t), done.set()),
                  focus=False)
time.sleep(0.6)
prompt.answer(None)                  # Escape
assert done.wait(5) and got[-1] is None, got
os._exit(0)
''')


def test_the_review_card_keys_answer_only_under_the_pointer() -> None:
    verdicts = []
    card = overlay_mod.ReviewCard(
        on_verdict=lambda sid, v: verdicts.append((sid, v)),
        keys={"accept": "v", "reject": "x", "later": "l"})
    assert not card.visible() and not card.on_key(vk_for("v"))
    card._current, card.rect = "s", (0, 0, 10, 10)
    card.hovering = lambda: False
    assert not card.on_key(vk_for("v")), "off the card, V is a letter"
    card.hovering = lambda: True
    assert not card.on_key(vk_for("q")), "an unrelated key passes through"
    assert card.on_key(vk_for("v"))
    assert verdicts == [("s", "accepted")] and not card.visible(), verdicts
    card._current = "t"
    assert card.on_key(vk_for("l")) and verdicts == [("s", "accepted")], \
        "later decides nothing"
    card._current = "u"
    assert card.on_key(vk_for("x")) and verdicts[-1] == ("u", "rejected")


def test_the_review_card_sits_mid_height_on_the_right_and_stays_where_put(
        ) -> None:
    card = overlay_mod.ReviewCard(corner="right", margin=14)
    x, y = card.origin(400, 200, (2560, 1440), 26, (-1920, 0, 4480, 1440))
    assert (x, y) == (2560 - 14 - 400 + 26, (1440 - 200) // 2), (x, y)
    left = overlay_mod.ReviewCard(corner="left", margin=14)
    assert left.origin(400, 200, (2560, 1440), 26)[0] == 14 - 26
    moved = overlay_mod.ReviewCard(corner="right", x=-1500, y=300)
    assert moved.origin(400, 200, (2560, 1440), 26,
                        (-1920, 0, 4480, 1440)) == (-1526, 274), \
        "a saved position on the left monitor is kept"
    top = overlay_mod.ReviewCard(corner="top-right", margin=14)
    assert top.origin(400, 200, (2560, 1440), 26)[1] == 14 - 26


def test_review_settings_are_in_the_real_config_and_checked_at_load() -> None:
    import shutil
    cfg = _hint_cfg()
    assert cfg.review.corner in config_mod.REVIEW_CORNERS, cfg.review.corner
    assert cfg.review.card_seconds > 0 and cfg.review.max_changes >= 1
    here = Path(__file__).resolve().parent
    tmp = Path(tempfile.mkdtemp(prefix="dictation-review-"))
    try:
        path = tmp / "config.toml"
        base = (here / "config.toml").read_text("utf-8")
        assert base.count('corner = "right"') == 1, "the [review] corner"
        path.write_text(base.replace('corner = "right"',
                                     'corner = "middle"'), "utf-8")
        try:
            config_mod.load(path)
        except config_mod.ConfigError as e:
            assert "review.corner" in str(e), e
        else:
            raise AssertionError("a nonsense corner loaded happily")
        path.write_text(base.replace("card_seconds = 20",
                                     "card_seconds = -3"), "utf-8")
        try:
            config_mod.load(path)
        except config_mod.ConfigError as e:
            assert "card_seconds" in str(e), e
        else:
            raise AssertionError("a negative clock loaded happily")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    import settings as settings_mod
    sections = {s.name: s for s in settings_mod.read(here / "config.toml")}
    assert "review" in sections, list(sections)
    corner = next(s for s in sections["review"].settings if s.key == "corner")
    assert "right" in corner.choices and "bottom-left" in corner.choices, \
        corner.choices


def test_an_accepted_reading_shows_up_in_the_history_as_learned() -> None:
    import shutil
    import history as history_mod
    tmp = Path(tempfile.mkdtemp(prefix="review-log-"))
    try:
        log = tmp / "transcripts.log"
        log.write_text(
            "2026-09-02 16:08:31,528 | REVIEW | accepted | מטוס || מנטוס\n"
            "2026-09-02 16:08:32,528 | REVIEW | rejected | ברגל || ב-Uber\n",
            "utf-8")
        events = history_mod._events_in(log)
        assert len(events) == 1, events
        assert events[0].kind == "learned", events[0]
        assert events[0].pairs == [("מטוס", "מנטוס")], events[0].pairs
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_the_review_screen_lists_what_waits_and_decides_it() -> None:
    import shutil
    import tkinter as tk
    import dashboard as dash
    import review as review_mod
    tmp = Path(tempfile.mkdtemp(prefix="review-dash-"))
    store = review_mod.Store(tmp / "review.json")
    base = {"when": "2026-09-02 16:08:31", "text": "הלכתי לאכול מטוס",
            "proposed": "הלכתי לאכול מנטוס", "status": "pending",
            "learned": False,
            "changes": [{"before": "מטוס", "after": "מנטוס",
                         "why": "אוכלים מנטוס", "kind": "replace",
                         "family": "context"}]}
    store.add(dict(base, id="p"))
    store.add(dict(base, id="d"))
    store.decide("d", "rejected", by="card")
    saved = dash.Dashboard._review_store
    dash.Dashboard._review_store = lambda self: store
    try:
        with _window() as board:
            if board is None:
                return
            board._show("Review")

            def rows():
                return [w for w in
                        board.parts["review_list"].inner.winfo_children()
                        if isinstance(w, tk.Canvas)]
            assert len(rows()) == 2, len(rows())
            head = board.parts["review_head"].cget("text")
            assert "1 waiting" in head and "1 rejected" in head, head
            board._review_decide("p", "accepted")
            assert store.pending() == [] and store.get("p")["by"] == "dashboard"
            assert len(rows()) == 2, "decided rows stay, greyed"
            assert "0 waiting" in board.parts["review_head"].cget("text")
    finally:
        dash.Dashboard._review_store = saved
        shutil.rmtree(tmp, ignore_errors=True)


# ----------------------------------------------------------------- awake

def test_the_screens_key_is_registered_everywhere_a_key_must_be() -> None:
    """Same five places as the camera key: HOTKEY_FIELDS, CHORD_FIELDS
    (ctrl+alt+n is a chord), KEY_GROUPS, and both NESTED_HOTKEYS."""
    import dashboard as dash_mod
    import main as main_mod

    registered = dict(config_mod.HOTKEY_FIELDS)
    assert "screens_hotkey" in registered
    assert registered["screens_hotkey"].endswith("(tap)"), \
        registered["screens_hotkey"]
    assert "screens_hotkey" in config_mod.CHORD_FIELDS
    named = {f for _title, fields in dash_mod.KEY_GROUPS for f in fields}
    assert "screens_hotkey" in named, "no group on the Keys screen"
    assert main_mod.NESTED_HOTKEYS["screens_hotkey"] == "awake.screens_hotkey"
    assert dash_mod.NESTED_HOTKEYS["screens_hotkey"] == "awake.screens_hotkey"

    cfg = config_mod.load(Path(__file__).resolve().parent / "config.toml")
    assert cfg.awake.hotkey == "ctrl+alt+n", cfg.awake
    assert cfg.screens_hotkey == cfg.awake.hotkey
    moved = config_mod.with_field(cfg, "screens_hotkey", "ctrl+f5")
    assert moved.awake.hotkey == "ctrl+f5" and moved.screens_hotkey == "ctrl+f5"
    assert moved.camera.hotkey == cfg.camera.hotkey, \
        "moving one key must not move another"
    config_mod.check_hotkeys(moved)
    clash = config_mod.with_field(cfg, "screens_hotkey", cfg.capture_hotkey)
    try:
        config_mod.check_hotkeys(clash)
    except config_mod.ConfigError as e:
        assert "screens_hotkey" in str(e) or "capture_hotkey" in str(e), e
    else:
        raise AssertionError("two keys on one binding were accepted")


def test_the_screens_key_binds_and_the_kill_switch_unbinds_it() -> None:
    import dataclasses

    import main as main_mod

    cfg = config_mod.load(Path(__file__).resolve().parent / "config.toml")
    _hotkeys, taps, _latch, _pause = main_mod.App.bindings(cfg)
    assert taps[parse_binding(cfg.screens_hotkey)] == "screens", taps
    off = dataclasses.replace(cfg, awake=dataclasses.replace(
        cfg.awake, enabled=False))
    _h, taps_off, _l, _p = main_mod.App.bindings(off)
    assert all(name != "screens" for name in taps_off.values()), taps_off


def test_the_awake_section_is_in_the_real_config_and_bounded() -> None:
    """The file is the Settings screen's list, so the section has to be
    IN the file, not only in the dataclass defaults — and the hold is on
    by default, because the requirement is "never"."""
    import settings as settings_mod

    here = Path(__file__).resolve().parent
    cfg = config_mod.load(here / "config.toml")
    assert cfg.awake.hold is True, "the machine must never sleep"
    assert cfg.awake.enabled is True
    assert cfg.awake.pin_timeouts is False, "off by default, on purpose"
    assert cfg.awake.screens_off_again_s == 3
    assert cfg.awake.keep_screens_off_s == 10
    assert cfg.awake.vitals_minutes == 10
    sections = {s.name: s for s in settings_mod.read(here / "config.toml")}
    assert "awake" in sections, sorted(sections)
    assert "night" not in sections, "the old section is still in the file"
    keys = {s.key for s in sections["awake"].settings}
    assert keys == {"hold", "enabled", "screens_hotkey", "pin_timeouts",
                    "screens_off_again_s", "keep_screens_off_s",
                    "vitals_minutes"}, keys
    assert sections["awake"].help, "the section has no help text"
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "config.toml"
        p.write_text('[awake]\nscreens_off_again_s = 999\n', "utf-8")
        try:
            config_mod.load(p)
        except config_mod.ConfigError as e:
            assert "screens_off_again_s" in str(e), e
        else:
            raise AssertionError("a 999 s repeat was accepted")


class _FakePowercfg:
    """powercfg as a dict: /query answers from it, /change writes it."""

    def __init__(self, standby: int = 30, hibernate: int = 0) -> None:
        self.values = {"STANDBYIDLE": standby * 60,
                       "HIBERNATEIDLE": hibernate * 60}
        self.calls: list[list[str]] = []

    def __call__(self, args, timeout=15):
        self.calls.append(list(args))
        if args[0] == "/query":
            secs = self.values[args[-1]]
            return 0, (f"    Current AC Power Setting Index: 0x{secs:08x}\n"
                       f"    Current DC Power Setting Index: 0x00000000\n")
        if args[0] == "/change":
            key = {"standby-timeout-ac": "STANDBYIDLE",
                   "hibernate-timeout-ac": "HIBERNATEIDLE"}[args[1]]
            self.values[key] = int(args[2]) * 60
            return 0, ""
        if args[0] == "/requests":
            return 1, "This command requires administrator privileges"
        if args[0] == "/a":
            return 0, ("The following sleep states are available on this "
                       "system:\n    Standby (S3)\n    Hibernate\n"
                       "The following sleep states are not available on "
                       "this system:\n    Standby (S0 Low Power Idle)\n")
        return 1, "unknown"


def _awake_until(cond, timeout: float = 2.0) -> None:
    """The engine hands its broadcasts to threads; wait for one, briefly."""
    deadline = time.monotonic() + timeout
    while not cond() and time.monotonic() < deadline:
        time.sleep(0.02)


def test_the_hold_goes_up_on_a_thread_and_comes_down_on_release() -> None:
    """The execution state is per thread and dies with it (the spec's
    warning), so the hold is a thread that makes the call and waits.
    hold() asks for CONTINUOUS|SYSTEM_REQUIRED and leaves the thread
    standing; release() lets go with CONTINUOUS alone and the thread
    ends. The marker file exists exactly while it is up — and the
    screens are not touched by either."""
    import awake as awake_mod

    calls: list[tuple[int, str]] = []
    def setter(flags: int) -> int:
        calls.append((flags, threading.current_thread().name))
        return 0x80000000            # "previously: continuous only"
    sent: list[int] = []
    with tempfile.TemporaryDirectory() as d:
        eng = awake_mod.Engine(Path(d), None,
                               hold_factory=lambda: awake_mod.Hold(setter=setter),
                               sender=lambda s: sent.append(s) or True,
                               run=_FakePowercfg())
        assert eng.hold_wanted, "the hold is on by default"
        assert not eng.holding and eng.state()["holding"] is False
        state = eng.hold(by="test")
        assert state["holding"] and state["held"], state
        assert not state["dark"], "the hold does not touch the screens"
        assert calls == [(awake_mod.ES_CONTINUOUS
                          | awake_mod.ES_SYSTEM_REQUIRED, "awake-hold")], calls
        assert awake_mod.ES_DISPLAY_REQUIRED & calls[0][0] == 0, \
            "the screens must be allowed to go off"
        assert (Path(d) / awake_mod.STATE_NAME).exists(), "no marker file"
        marker = json.loads((Path(d) / awake_mod.STATE_NAME).read_text("utf-8"))
        assert marker["by"] == "test" and marker["pid"] == os.getpid()
        assert marker["saved"] is None, "timers are not pinned by default"
        time.sleep(0.2)
        assert sent == [], "hold() must not broadcast to the screens"
        eng.hold(by="test")                       # a second hold does not stack
        assert len(calls) == 1
        eng.release()
        assert not eng.holding and eng.state()["holding"] is False
        assert calls[-1][0] == awake_mod.ES_CONTINUOUS, calls
        assert calls[-1][1] == "awake-hold", "released on the holding thread"
        assert not (Path(d) / awake_mod.STATE_NAME).exists(), "marker left"
        record = (Path(d) / awake_mod.LOG_NAME).read_text("utf-8")
        assert "| HOLD by test" in record and "| RELEASE |" in record, record
        eng.release()                             # twice is fine
        assert sent == []


def test_the_screens_go_off_and_come_back_without_touching_the_hold() -> None:
    """darken() broadcasts MONITOR_OFF, lighten() MONITOR_ON, toggle()
    alternates, a second darken() puts them out again — and none of it
    starts or stops the hold. The delayed second MONITOR_OFF (for the
    click's mouse movement) stays home if the screens were brought back
    in the meantime."""
    import awake as awake_mod

    calls: list[int] = []
    sent: list[int] = []
    with tempfile.TemporaryDirectory() as d:
        eng = awake_mod.Engine(Path(d), None,
                               hold_factory=lambda: awake_mod.Hold(
                                   setter=lambda f: calls.append(f) or 0x80000000),
                               sender=lambda s: sent.append(s) or True,
                               run=_FakePowercfg())
        eng.again_s = 0
        eng.vitals_minutes = 0
        eng.keep_off_s = 0
        eng.hold(by="start")
        state = eng.darken(by="test")
        assert state["dark"] and state["holding"] and state["by"] == "test", state
        _awake_until(lambda: len(sent) == 1)
        assert sent == [awake_mod.MONITOR_OFF], sent
        eng.darken(by="test")                     # again: out again, not back
        _awake_until(lambda: len(sent) == 2)
        assert sent == [awake_mod.MONITOR_OFF] * 2 and eng.dark
        state = eng.toggle(by="key")
        assert not state["dark"] and state["holding"], state
        _awake_until(lambda: len(sent) == 3)
        assert sent[-1] == awake_mod.MONITOR_ON, sent
        assert len(calls) == 1, "the screens must not touch the hold"
        assert eng.toggle(by="key")["dark"]
        eng.lighten(by="test")
        assert eng.lighten(by="test")["dark"] is False, "lighten twice is fine"
        record = (Path(d) / awake_mod.LOG_NAME).read_text("utf-8")
        assert "| SCREENS OFF by test" in record, record
        assert "| SCREENS ON by key" in record, record
        assert eng.holding, "still held"
        # The delayed repeat, and the race it must lose.
        sent.clear()
        eng.again_s = 1
        eng.darken(by="test")
        _awake_until(lambda: len(sent) == 1)
        eng.lighten(by="test")
        time.sleep(1.4)
        assert sent.count(awake_mod.MONITOR_OFF) == 1, \
            f"the second broadcast fired after the screens came back: {sent}"
        eng.release()
        assert not eng.holding and not eng.dark


def test_the_process_list_sees_the_processes_it_cannot_open() -> None:
    """The ntdll list, not OpenProcess. THE point of it: a service
    running as SYSTEM is refused to a non-elevated OpenProcess, and a
    leak is exactly where such a process needs naming (2026-09-03:
    nvcontainer.exe, 823,369 handles of the machine's 988,258, invisible
    to the first implementation of this).

    Cross-checked against ntdll's own machine-wide counters rather than
    a hard-coded name: the sum of the per-process handles has to land
    near GetPerformanceInfo's total, which is computed by the kernel by
    a different route. Windows itself is the fixture."""
    import awake as awake_mod

    procs = awake_mod.processes()
    assert len(procs) > 50, f"only {len(procs)} processes"
    assert all(name and ws >= 0 and commit >= 0 and handles >= 0
               for name, ws, commit, handles in procs), procs[:5]
    # The kernel counted the same handles a different way; a few hundred
    # of drift between the two reads is ordinary on a live machine.
    total = sum(handles for _n, _w, _c, handles in procs)
    v = awake_mod.vitals(gpu=False)
    assert abs(total - v["handles"]) < max(2000, v["handles"] // 50), \
        f"per-process sum {total} vs machine total {v['handles']}"
    # And the biggest holder is what the line names.
    biggest = max(procs, key=lambda r: r[3])
    assert v["handles_top"][1] >= biggest[3] // 2, (v["handles_top"], biggest)
    # A process this test can definitely not open, present on every
    # Windows: the kernel itself, pid 4, which has no image name.
    assert any(name == "System" for name, _w, _c, _h in procs), \
        "the ntdll list is missing pid 4 — this is the OpenProcess bug again"


def test_the_vitals_read_this_machine_without_a_subprocess() -> None:
    """vitals() is Win32 through ctypes: RAM, commit, the non-paged pool,
    this process, the heaviest programs by image. The GPU number is the
    one subprocess and is skipped here; the line renders without it."""
    import awake as awake_mod

    t0 = time.perf_counter()
    v = awake_mod.vitals(top=3, gpu=False)
    took = time.perf_counter() - t0
    assert 0 < v["ram_free"] <= v["ram_total"], v
    assert 0 < v["commit"] <= v["commit_limit"], v
    assert v["nonpaged"] > 0 and v["processes"] > 1, v
    assert 0 < v["self_ws"] and 0 < v["self_private"], v
    assert len(v["top"]) == 3 and all(r[0] and r[1] > 0 for r in v["top"]), v
    assert v["gpu"] is None
    # The name that ends the argument: a total says the machine is full
    # of handles, not whose they are (2026-09-03: nvcontainer, 812,918).
    name, count = v["handles_top"]
    assert name and 0 < count <= v["handles"], v["handles_top"]
    assert took < 2.0, f"vitals took {took:.2f} s"
    line = awake_mod.vitals_line(v)
    assert "RAM free" in line and "commit" in line and "heaviest" in line, line
    assert f"{name} holds {count}" in line, line
    assert "GPU" not in line, line
    assert "GPU 5.8 of 15.9 GB" in awake_mod.vitals_line(
        {"gpu": (5903 << 20, 16311 << 20)}), "GiB, like nvidia-smi"
    assert "this app 0.05 GB in RAM" in awake_mod.vitals_line(
        {"self_ws": 50 << 20, "self_private": 3 << 30}), \
        "two decimals under a gigabyte, or a 50 MB process reads as 0.0"


def test_the_screens_off_write_the_vitals_on_the_way_in_and_out() -> None:
    """One line when the screens go off, one every vitals_minutes, one
    when they come back — the record of the time away. The reader is
    injected: the test is about the log, not the machine."""
    import awake as awake_mod

    reads: list[float] = []
    def fake_vitals() -> str:
        reads.append(time.monotonic())
        return f"fake vitals {len(reads)}"
    with tempfile.TemporaryDirectory() as d:
        eng = awake_mod.Engine(Path(d), None,
                               hold_factory=lambda: awake_mod.Hold(
                                   setter=lambda flags: 0x80000000),
                               sender=lambda s: True, run=_FakePowercfg(),
                               vitals_fn=fake_vitals)
        eng.again_s = 0
        eng.keep_off_s = 0
        eng.vitals_minutes = 0
        eng.hold(by="start")
        eng.darken(by="test")
        time.sleep(0.3)
        eng.lighten(by="test")
        time.sleep(0.3)
        assert not reads, "vitals_minutes = 0 must mean no reads at all"
        record = (Path(d) / awake_mod.LOG_NAME).read_text("utf-8")
        assert "vitals" not in record, record

        eng.vitals_minutes = 1
        eng.darken(by="test")
        _awake_until(lambda: len(reads) >= 1)
        eng.lighten(by="test")
        _awake_until(lambda: len(reads) >= 2)
        time.sleep(0.1)
        record = (Path(d) / awake_mod.LOG_NAME).read_text("utf-8")
        assert "|   vitals | screens off: fake vitals 1" in record, record
        assert "|   vitals | screens on: fake vitals 2" in record, record
        on_at = record.index("screens off: fake")
        off_line = record.rindex("| SCREENS ON by test")   # the second cycle's
        assert on_at < off_line < record.index("screens on: fake"), \
            "the coming-back snapshot must follow the SCREENS ON line"
        assert len(reads) == 2, \
            "inside a minute only the two edge snapshots may land"
        eng.release()


def test_the_vitals_watch_spans_the_hold_and_the_alarms_shout() -> None:
    """The watch belongs to the hold, not to the screens. It goes up with
    hold() in broad daylight — the leak measured on 2026-09-03 crawled
    this machine all afternoon with the screens ON, and the one log that
    would have named it only ran at night — and it comes down with
    release(). And a number out of range is no longer merely recorded: it
    gets an ALARM line of its own, with the cure written into it."""
    import awake as awake_mod

    gb = 1 << 30
    healthy = {"commit": 10 * gb, "commit_limit": 44 * gb,
               "nonpaged": 0.9 * gb, "handles_top": ("svchost", 39_100)}
    assert awake_mod.alarms(healthy) == [], awake_mod.alarms(healthy)

    # The real numbers off this machine, 2026-09-03, while it crawled.
    sick = {"commit": 48 * gb, "commit_limit": 50 * gb,
            "nonpaged": 2.47 * gb,
            "handles_top": ("nvcontainer.exe", 825_247)}
    said = awake_mod.alarms(sick)
    assert len(said) == 3, said
    assert "nvcontainer.exe holds 825,247 handles" in said[0], said[0]
    assert "without a reboot" in said[0], said[0]
    assert "non-paged pool 2.5 GB" in said[1], said[1]
    assert "96% of the limit" in said[2], said[2]

    # Each threshold stands alone: no single number may hide behind the
    # other two being fine, which is exactly how this one was missed.
    for key, value in (("handles_top", ("nvcontainer.exe", 825_247)),
                       ("nonpaged", 2.47 * gb),
                       ("commit", 40 * gb)):
        alone = dict(healthy)
        alone[key] = value
        assert len(awake_mod.alarms(alone)) == 1, (key,
                                                   awake_mod.alarms(alone))

    reads: list[int] = []
    def fake_vitals() -> str:
        reads.append(len(reads))
        return "fake vitals"
    with tempfile.TemporaryDirectory() as d:
        eng = awake_mod.Engine(Path(d), None,
                               hold_factory=lambda: awake_mod.Hold(
                                   setter=lambda flags: 0x80000000),
                               sender=lambda s: True, run=_FakePowercfg(),
                               vitals_fn=fake_vitals,
                               alarms_fn=lambda: ["the pool is 2.5 GB"])
        eng.again_s = 0
        eng.keep_off_s = 0
        eng.vitals_minutes = 1
        assert not eng._vitals_watching, "nothing watches before the hold"
        eng.hold(by="start")
        assert eng._vitals_watching, \
            "the watch must go up with the hold, screens lit or not"
        eng.darken(by="test")
        _awake_until(lambda: len(reads) >= 1)
        eng.lighten(by="test")
        assert eng._vitals_watching, \
            "the screens coming back must not end the watch"
        eng.release()
        assert not eng._vitals_watching, "release() is what ends it"
        record = (Path(d) / awake_mod.LOG_NAME).read_text("utf-8")
        assert "|   ALARM | the pool is 2.5 GB" in record, record


def test_the_screens_stay_off_after_input_lights_them() -> None:
    """[awake] keep_screens_off_s: anything that touches the machine
    lights the screens, and that many seconds after the LAST touch they
    are put out again — for as long as the key says, the owner at the
    keyboard included. The input clock is injected: nothing here moves
    the real mouse, and an untouched machine gets no broadcast at all."""
    import awake as awake_mod

    real = awake_mod.last_input()
    assert 0 < real <= time.monotonic(), real
    touched = [0.0]                       # monotonic time of the last input
    sent: list[tuple[int, float]] = []
    def sender(state: int) -> bool:
        sent.append((state, time.monotonic()))
        return True
    with tempfile.TemporaryDirectory() as d:
        eng = awake_mod.Engine(Path(d), None,
                               hold_factory=lambda: awake_mod.Hold(
                                   setter=lambda flags: 0x80000000),
                               sender=sender, run=_FakePowercfg(),
                               input_fn=lambda: touched[0])
        eng.again_s = 0
        eng.vitals_minutes = 0
        eng.keep_off_s = 0
        eng.hold(by="start")
        eng.darken(by="test")
        time.sleep(0.4)
        assert [s for s, _t in sent] == [awake_mod.MONITOR_OFF], \
            "0 must mean the one broadcast only"
        eng.lighten(by="test")
        _awake_until(lambda: len(sent) == 2)      # the MONITOR_ON

        sent.clear()
        eng.keep_off_s = 0.2
        touched[0] = time.monotonic()     # the key that put them out
        eng.darken(by="test")
        assert eng.state()["keep_screens_off_s"] == 0.2
        _awake_until(lambda: bool(sent))
        time.sleep(0.6)
        assert [s for s, _t in sent] == [awake_mod.MONITOR_OFF], \
            "an untouched machine gets no second broadcast"
        touched[0] = time.monotonic()     # the mouse, or a click from the phone
        _awake_until(lambda: len(sent) >= 2)
        assert [s for s, _t in sent] == [awake_mod.MONITOR_OFF] * 2, sent
        assert sent[1][1] - touched[0] >= 0.2, "put out before it was still"
        record = (Path(d) / awake_mod.LOG_NAME).read_text("utf-8")
        assert "screens lit by input, put out again" in record, record
        eng.lighten(by="test")
        touched[0] = time.monotonic()     # the key that brought them back
        time.sleep(0.6)
        assert [s for s, _t in sent].count(awake_mod.MONITOR_OFF) == 2, \
            "lighten() must stop the watchdog"
        eng.release()


def test_a_hold_refused_by_windows_is_reported_not_pretended() -> None:
    import dataclasses

    import awake as awake_mod

    with tempfile.TemporaryDirectory() as d:
        eng = awake_mod.Engine(Path(d), None,
                               hold_factory=lambda: awake_mod.Hold(
                                   setter=lambda flags: 0),
                               sender=lambda s: True, run=_FakePowercfg())
        state = eng.hold(by="test")
        assert state.get("ok") is False and "refused" in state["error"], state
        assert not eng.holding
        assert not (Path(d) / awake_mod.STATE_NAME).exists()
        # The screens still work without a hold, and the log says so.
        eng.again_s = 0
        eng.vitals_minutes = 0
        eng.keep_off_s = 0
        assert eng.darken(by="test")["dark"]
        assert "NOT holding" in (Path(d) / awake_mod.LOG_NAME).read_text("utf-8")
        eng.lighten(by="test")
    quiet = awake_mod.Engine(Path(d), dataclasses.replace(
        config_mod.AwakeConfig(), hold=False))
    assert quiet.hold_wanted is False, "[awake] hold = false must be honoured"


def test_the_hold_pins_the_timers_and_puts_them_back() -> None:
    """[awake] pin_timeouts: read, save, set to never, restore — and the
    saved numbers are in the marker file, which is what recover() reads
    when the app did not live to restore them itself."""
    import dataclasses

    import awake as awake_mod

    cfg = dataclasses.replace(config_mod.AwakeConfig(), pin_timeouts=True,
                              screens_off_again_s=0)
    fake = _FakePowercfg(standby=30, hibernate=0)
    with tempfile.TemporaryDirectory() as d:
        eng = awake_mod.Engine(Path(d), cfg,
                               hold_factory=lambda: awake_mod.Hold(
                                   setter=lambda flags: 1),
                               sender=lambda s: True, run=fake)
        eng.hold(by="test")
        assert fake.values == {"STANDBYIDLE": 0, "HIBERNATEIDLE": 0}, fake.values
        marker = json.loads((Path(d) / awake_mod.STATE_NAME).read_text("utf-8"))
        assert marker["saved"] == {"standby_ac": 30, "hibernate_ac": 0}, marker
        assert eng.state()["pinned"] is True
        eng.release()
        assert fake.values == {"STANDBYIDLE": 1800, "HIBERNATEIDLE": 0}, \
            fake.values
        assert eng.state()["pinned"] is False
        assert not (Path(d) / awake_mod.STATE_NAME).exists(), "marker left"
        record = (Path(d) / awake_mod.LOG_NAME).read_text("utf-8")
        assert "pinned to never" in record and "timers restored" in record, record


def test_a_leftover_awake_marker_is_recovered_at_the_next_start() -> None:
    """A session that died holding with the timers pinned: the hold went
    with it, the pinned timers did not. recover() puts them back from
    the marker, removes it, and writes what it did."""
    import awake as awake_mod

    with tempfile.TemporaryDirectory() as d:
        assert awake_mod.recover(Path(d)) is None, "nothing to recover"
        fake = _FakePowercfg(standby=0, hibernate=0)      # as it was left
        (Path(d) / awake_mod.STATE_NAME).write_text(json.dumps(
            {"since": 1.0, "since_text": "2026-09-02 23:00:00", "pid": 1,
             "by": "start", "saved": {"standby_ac": 30, "hibernate_ac": 0}}),
            "utf-8")
        message = awake_mod.recover(Path(d), run=fake)
        assert message and "restored" in message, message
        assert fake.values == {"STANDBYIDLE": 1800, "HIBERNATEIDLE": 0}, \
            fake.values
        assert not (Path(d) / awake_mod.STATE_NAME).exists(), "marker left"
        assert "RECOVERED" in (Path(d) / awake_mod.LOG_NAME).read_text("utf-8")
        # A marker with nothing saved is cleaned up and says so.
        (Path(d) / awake_mod.STATE_NAME).write_text('{"saved": null}', "utf-8")
        fake.calls.clear()
        message = awake_mod.recover(Path(d), run=fake)
        assert "nothing to restore" in message, message
        assert fake.calls == [], fake.calls


def test_the_screens_command_goes_through_the_control_channel() -> None:
    """The dashboard's button is one pipe message; the reply carries the
    state so the button can repaint without waiting for a poll. And the
    hold is wired to the app's own start and stop, not to any command."""
    import inspect

    import main as main_mod
    import awake as awake_mod

    assert 'self.awake.hold(by="start")' in inspect.getsource(main_mod.App.start)
    assert "self.awake.release()" in inspect.getsource(main_mod.App.stop)
    with tempfile.TemporaryDirectory() as d:
        app = main_mod.App.__new__(main_mod.App)
        app._note = ""
        sent: list[int] = []
        app.awake = awake_mod.Engine(
            Path(d), None,
            hold_factory=lambda: awake_mod.Hold(setter=lambda f: 1),
            sender=lambda s: sent.append(s) or True, run=_FakePowercfg())
        app.awake.again_s = 0
        app.awake.vitals_minutes = 0
        app.awake.keep_off_s = 0
        app.awake.hold(by="start")
        reply = app.control_command("screens", {"do": "off"})
        assert reply["ok"] and reply["awake"]["dark"], reply
        assert reply["awake"]["holding"], "the command must not touch the hold"
        assert "screens off" in app._note, app._note
        reply = app.control_command("screens", {"do": "again"})
        assert reply["ok"] and "screens off again" in reply["message"], reply
        reply = app.control_command("screens", {"do": "toggle"})
        assert reply["ok"] and not reply["awake"]["dark"], reply
        assert "screens on" in app._note, app._note
        reply = app.control_command("screens", {"do": "on"})
        assert reply["ok"] and not reply["awake"]["dark"], "on when on is fine"
        reply = app.control_command("screens", {"do": "sideways"})
        assert not reply["ok"] and "sideways" in reply["error"], reply
        assert not app.awake.dark and app.awake.holding
        app.awake.release()


def test_hours_cover_night_reads_a_window_that_wraps_midnight() -> None:
    import awake as awake_mod

    assert awake_mod.hours_cover_night((9, 2)) is False       # this machine
    assert awake_mod.hours_cover_night((16, 10)) is True
    assert awake_mod.hours_cover_night((22, 8)) is True
    assert awake_mod.hours_cover_night((23, 7)) is True
    assert awake_mod.hours_cover_night((0, 0)) is False
    assert awake_mod.hours_cover_night(None) is None


def test_the_verdict_names_what_can_lose_the_machine_while_away() -> None:
    """Every row the spec lists as a way to be awake and unreachable, in
    words that say what to do, with a tone the screen can colour. The
    hold row reads the HOLD, not the screens: a machine with its screens
    on and the hold standing is fine, one with nothing holding is not."""
    import awake as awake_mod

    probe = {"system_required": True, "display_required": False,
             "requests": None, "standby": "S3",
             "timeouts": {"standby_ac": 30, "hibernate_ac": 0},
             "adapters": [{"name": "Ethernet", "up": True, "saving": True}],
             "active_hours": (9, 2), "claude": 0}
    held = {"holding": True, "held": True, "dark": False}
    rows = {label: (text, tone) for label, text, tone in
            awake_mod.verdict(held, probe)}
    assert rows["Sleep hold"][1] == "good", rows["Sleep hold"]
    assert "administrator" in rows["powercfg /requests"][0]
    assert rows["Sleep after (plugged in)"][1] == "good"
    assert "30 min" in rows["Sleep after (plugged in)"][0]
    assert rows["Standby type"][1] == "good"
    assert rows["Network adapter"][1] == "warn"
    assert "Device Manager" in rows["Network adapter"][0]
    assert rows["Update active hours"][1] == "warn"
    assert "09:00–02:00" in rows["Update active hours"][0]
    assert rows["Claude"][1] == "warn"
    # Nothing holding, and the kernel agrees: the hold row and the timer
    # row both turn amber — this machine WILL sleep.
    probe["system_required"] = False
    rows = {label: tone for label, _text, tone in
            awake_mod.verdict({"holding": False, "held": False}, probe)}
    assert rows["Sleep after (plugged in)"] == "warn", rows
    assert rows["Sleep hold"] == "warn", rows
    # Nothing holding here, but another program is: dim, not amber.
    probe["system_required"] = True
    rows = {label: (text, tone) for label, text, tone in
            awake_mod.verdict({}, probe)}
    assert rows["Sleep hold"][1] == "dim" and "another program" in \
        rows["Sleep hold"][0], rows["Sleep hold"]
    # Asked, but the hold is not standing: red, in words.
    rows = {label: (text, tone) for label, text, tone in
            awake_mod.verdict({"holding": True, "held": False}, probe)}
    assert rows["Sleep hold"][1] == "bad", rows["Sleep hold"]
    # Everything right — with the screens off or on, it makes no difference.
    probe.update(system_required=True, adapters=[{"name": "Ethernet",
                                                   "up": True,
                                                   "saving": False}],
                 active_hours=(16, 10), claude=3)
    for dark in (False, True):
        tones = {tone for _l, _t, tone in
                 awake_mod.verdict({**held, "dark": dark}, probe)}
        assert "warn" not in tones and "bad" not in tones, (dark, tones)


def test_the_screen_broadcast_returns_and_reads_the_kernel_state() -> None:
    """The real APIs, harmlessly: MONITOR_ON is a no-op on a lit screen,
    and the timeout is what stops a hung window from hanging us."""
    import awake as awake_mod

    t0 = time.perf_counter()
    ok = awake_mod.send_monitor_power(awake_mod.MONITOR_ON, timeout_ms=1500)
    took = time.perf_counter() - t0
    assert isinstance(ok, bool)
    assert took < 20, f"the broadcast took {took:.1f} s"
    flags = awake_mod.system_execution_state()
    assert flags is None or isinstance(flags, int), flags
    assert awake_mod.read_timeouts().get("standby_ac") is not None, \
        "powercfg /query could not be read on this machine"


def test_the_dashboard_has_an_awake_screen_that_waits_for_the_app() -> None:
    """With nothing running the switch is disabled and the hint says why;
    the check works regardless, and its rows land on the screen. With
    the app running the hero reads the HOLD, and the switch the SCREENS."""
    import dashboard as dash
    import awake as awake_mod

    saved = dash.AWAKE_AUTO_CHECK
    dash.AWAKE_AUTO_CHECK = False
    try:
        with _window() as board:
            if board is None:
                return
            board._show("Awake")
            p = board.parts
            for name in ("awake_toggle", "awake_screen", "awake_check",
                         "awake_rows", "awake_state"):
                assert name in p, name
            assert not p["awake_toggle"]._enabled, "on with nothing running"
            assert not p["awake_screen"]._enabled
            assert p["awake_check"]._enabled, "the check needs no app"
            assert "NOT RUNNING" in p["awake_state"].cget("text")
            assert "start dictation" in p["awake_hint"].cget("text")
            board._awake_checked({
                "system_required": False, "requests": None, "standby": "S3",
                "timeouts": {"standby_ac": 30}, "adapters": [],
                "active_hours": (9, 2), "claude": 2})
            rows = p["awake_rows"].winfo_children()
            assert len(rows) == len(awake_mod.verdict({}, board._awake_probe)), \
                len(rows)
            assert "checked" in p["awake_checked"].cget("text")
            # A running app, holding, screens on: AWAKE, and the switch
            # offers to put the screens off.
            board.running = True
            now = time.time()
            board.status = {"stage": "running", "awake": {
                "holding": True, "held": True, "hold_since": now - 3600,
                "hold_seconds": 3600, "dark": False, "since": None,
                "seconds": 0, "pinned": False, "keep_screens_off_s": 10}}
            board._paint_awake()
            assert p["awake_state"].cget("text") == "AWAKE"
            assert p["awake_toggle"]._enabled
            assert "held since" in p["awake_meta"].cget("text")
            # Screens off: the hero says so and the meta keeps the hold.
            board.status["awake"].update(dark=True, since=now - 65,
                                         seconds=65, by="key")
            board._paint_awake()
            assert p["awake_state"].cget("text") == "SCREENS OFF"
            meta = p["awake_meta"].cget("text")
            assert "held since" in meta and "screens off for" in meta, meta
            assert "10 s after the last touch" in p["awake_hint"].cget("text")
            # Asked and refused: red, in words.
            board.status["awake"].update(held=False, dark=False)
            board._paint_awake()
            assert p["awake_state"].cget("text") == "NOT HOLDING"
    finally:
        dash.AWAKE_AUTO_CHECK = saved


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items())
             if n.startswith("test_") and callable(f)]
    # `tests.py a b` runs only the tests whose name contains a or b; a
    # leading `-` excludes instead (`tests.py -drag`). tests_quiet.py uses
    # this to run the few that need the real screen in the open and the
    # rest on a hidden desktop.
    picks = [a for a in sys.argv[1:] if not a.startswith("-")]
    skips = [a[1:] for a in sys.argv[1:] if a.startswith("-") and a[1:]]
    if picks:
        tests = [(n, f) for n, f in tests if any(p in n for p in picks)]
    if skips:
        tests = [(n, f) for n, f in tests if not any(s in n for s in skips)]
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
