"""Hebrew push-to-talk dictation for Windows.

Hold the hotkey (default: Right Ctrl), speak Hebrew, release — the cleaned
transcript is pasted into whatever window has focus. See README.md.

Normally launched by double-clicking "Hebrew Dictation.vbs", which runs it
windowless via pythonw.exe. With no console there is no Ctrl+C, so a second
launch is refused (single-instance mutex) and "Stop Dictation.vbs" (i.e.
--stop) asks the running instance to exit.

Flags:
  --fake          use the fake backend (no API key, no speech needed)
  --check         validate the Gemini key/model with one tiny request, exit
  --list-devices  print audio input devices, exit
  --stop          tell a running instance to quit, exit
"""
from __future__ import annotations

import argparse
import ctypes
import dataclasses
import inspect
import logging
import logging.handlers
import queue
import sys
import threading
import time
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent

import config as config_mod
import cues
import injector
import singleton
from config import ConfigError
from hotkey import HookThread, PTTStateMachine, parse_chord, vk_for
from recorder import Recorder
from spool import Spool
from transcribers import RateLimitError, TranscriptionError, get_transcriber

log = logging.getLogger("app")
transcript_log = logging.getLogger("transcripts")

# pythonw.exe (the windowless launcher) gives the process no stdout at all.
HAS_CONSOLE = sys.stdout is not None


def report_fatal(message: str) -> None:
    """Startup failures must be visible even with no console — otherwise
    double-clicking the shortcut just silently does nothing."""
    log.error("%s", message)
    if not HAS_CONSOLE:
        ctypes.windll.user32.MessageBoxW(
            None, message, "Hebrew Dictation — cannot start", 0x10)


def beep(kind: str) -> None:
    """Fire-and-forget cue (see cues.py — plays through the audio mixer,
    not the inaudible legacy beep path)."""
    cues.play(kind)


class App:
    def __init__(self, cfg: config_mod.Config):
        self.cfg = cfg
        parse_chord(cfg.paste_chord)  # fail fast on a bad chord name
        self.queue: queue.Queue[tuple[bytes, float, int, str]] = queue.Queue()
        self.transcriber = get_transcriber(cfg)  # fail fast (e.g. no key)
        self.spool = Spool(APP_DIR / "pending")
        self._local = None       # lazily built local fallback, if enabled
        self.recorder = Recorder(cfg.audio.sample_rate, cfg.audio.device,
                                 cfg.max_seconds, self._on_overflow)
        hotkeys = {vk_for(cfg.hotkey): "he"}
        if cfg.english_hotkey:
            hotkeys[vk_for(cfg.english_hotkey)] = "en"
        taps = {}
        if cfg.translate_hotkey:
            parse_chord(cfg.translate.copy_chord)        # fail fast, as above
            parse_chord(cfg.translate.select_all_chord)
            taps[vk_for(cfg.translate_hotkey)] = "translate"
        self.machine = PTTStateMachine(
            hotkeys,
            on_start=self._on_start, on_stop=self._on_stop,
            on_abort=self._on_abort,
            taps=taps, on_tap=self._on_tap)
        self.hook = HookThread(self.machine)
        self.worker = threading.Thread(target=self._worker, daemon=True,
                                       name="transcribe-worker")
        # Translation gets its own queue and thread: it is an independent
        # action on text that is already on screen, and must not wait behind
        # a 40 s transcription retry (or make one wait behind it).
        self.translate_queue: queue.Queue[int] = queue.Queue()
        self._translator = None
        self._translating = threading.Event()
        self.translate_worker = threading.Thread(
            target=self._translate_worker, daemon=True,
            name="translate-worker")

    def start(self) -> None:
        self.recorder.start_stream()
        self.worker.start()
        self.translate_worker.start()
        self.hook.start()

    def stop(self) -> None:
        self.hook.stop()
        self.recorder.close()

    # ---- hook-thread callbacks: keep them fast ----

    def _on_start(self, language: str = "he") -> None:
        self.recorder.begin()
        beep("start")
        log.info("recording %s... (release to transcribe)",
                 "ENGLISH" if language == "en" else "Hebrew")

    def _on_stop(self, language: str = "he") -> None:
        wav, seconds = self.recorder.end()
        if wav is None:
            # overflowed at max_seconds — beep already fired at cap time
            log.info("discarded: hit the %.0f s cap", self.cfg.max_seconds)
            transcript_log.info("DISCARDED | %.1fs | hit max_seconds cap",
                                seconds)
            return
        if seconds < self.cfg.min_seconds:
            log.info("discarded: %.2f s hold is under min_seconds=%.2f "
                     "(accidental tap?)", seconds, self.cfg.min_seconds)
            return
        beep("stop")
        # Remember WHERE the user was speaking. Everything slow (placeholder
        # paste, transcription) happens on the worker: this callback runs
        # inside the OS keyboard hook, and blocking here would make Windows
        # drop the hook and freeze input.
        self.queue.put((wav, seconds, injector.foreground_window(), language))
        log.info("captured %.1f s of %s -> transcribing (%s)...", seconds,
                 "English" if language == "en" else "Hebrew",
                 self.transcriber.name)

    def _on_abort(self, reason: str) -> None:
        self.recorder.abort()
        log.info("aborted, nothing recorded — %s", reason)

    def _on_tap(self, action: str) -> None:
        if action != "translate":
            return
        # Remember WHERE the text is before anything slow happens, for the
        # same reason _on_stop does: this runs inside the OS keyboard hook.
        if self._translating.is_set():
            log.info("already translating — ignoring the extra press")
            return
        self._translating.set()
        self.translate_queue.put(injector.foreground_window())

    def _on_overflow(self) -> None:  # PortAudio callback thread
        beep("error")
        log.warning("recording passed max_seconds=%.0f — discarding. "
                    "Release the key.", self.cfg.max_seconds)

    # ---- worker thread ----

    def _local_backend(self):
        """Build the local backend on first need. Returns None when it is
        unavailable (not installed, or still the stub) — the caller then
        reports the original cloud error rather than a confusing one."""
        if self._local is not None:
            return self._local or None
        if not self.cfg.fallback_to_local or self.cfg.backend == "local":
            self._local = False
            return None
        try:
            from transcribers.local_whisper import LocalWhisperTranscriber
            log.info("cloud quota spent — loading the local model (first "
                     "run downloads it; this takes a while)...")
            self._local = LocalWhisperTranscriber(self.cfg.local.model,
                                                  self.cfg.local.language,
                                                  self.cfg.local.device,
                                                  self.cfg.local.cleanup,
                                                  self.cfg.local.extra_fillers,
                                                  self.cfg.local.english_model,
                                                  self.cfg.local
                                                  .english_threshold,
                                                  self.cfg.local
                                                  .initial_prompt)
            log.info("local backend ready — dictation continues offline")
        except Exception as e:
            log.warning("no local fallback available: %s", e)
            self._local = False
            return None
        return self._local

    @staticmethod
    def _call(backend, wav: bytes, language: str | None) -> str:
        """Pass the chosen language through when the backend supports it.

        The signature is inspected rather than catching TypeError, so a
        genuine TypeError raised *inside* a backend is not silently retried
        as if the backend simply lacked the parameter.
        """
        try:
            takes_language = "language" in inspect.signature(
                backend.transcribe).parameters
        except (TypeError, ValueError):
            takes_language = False
        if takes_language:
            return backend.transcribe(wav, language=language)
        return backend.transcribe(wav)

    def _transcribe(self, wav: bytes,
                    language: str | None = None) -> tuple[str, str]:
        """Cloud first; local only once every cloud model is out of quota."""
        try:
            return (self._call(self.transcriber, wav, language),
                    self.transcriber.name)
        except RateLimitError:
            local = self._local_backend()
            if local is None:
                raise
            return self._call(local, wav, language), local.name

    def _worker(self) -> None:
        while True:
            wav, seconds, hwnd, language = self.queue.get()
            try:
                self._handle(wav, seconds, hwnd, language)
            except Exception:
                beep("error")
                log.exception("unexpected failure handling a recording")

    # ---- translate worker ----

    def _translate_worker(self) -> None:
        while True:
            hwnd = self.translate_queue.get()
            try:
                self._translate(hwnd)
            except Exception:
                beep("error")
                log.exception("unexpected failure translating")
            finally:
                self._translating.clear()

    def _translate(self, hwnd: int) -> None:
        """Replace the selection — or the whole field — with its English.

        The clipboard is saved once around the whole thing and restored on
        every exit path, including the failures: grabbing the text is what
        overwrites it, so an early return without a restore would leave the
        user's own clipboard silently destroyed.
        """
        import translate as translate_mod

        tcfg = self.cfg.translate
        state = injector.snapshot()
        keep_clipboard = False
        try:
            text, had_selection = injector.grab(tcfg.copy_chord,
                                                tcfg.select_all_chord,
                                                tcfg.settle_ms / 1000)
        except injector.ClipboardBusyError as e:
            beep("error")
            log.error("could not read the text to translate: %s", e)
            return

        try:
            what = "the selection" if had_selection else "the whole field"
            if not text.strip():
                beep("error")
                log.info("nothing to translate — %s is empty", what)
                return
            if len(text) > tcfg.max_chars:
                beep("error")
                log.warning(
                    "refusing to translate %d chars from %s (max_chars=%d) "
                    "— that looks like a whole document, not a message. "
                    "Select the part you want and press the key again.",
                    len(text), what, tcfg.max_chars)
                return
            if not translate_mod.needs_translation(text, tcfg.target):
                beep("error")
                log.info("no Hebrew in %s — already %s, leaving it alone",
                         what, tcfg.target)
                return

            beep("translating")
            log.info("translating %d chars from %s to %s...", len(text),
                     what, tcfg.target)
            # The original goes to the log BEFORE it is replaced on screen:
            # this file is the recovery path if the paste goes wrong.
            transcript_log.info("TRANSLATE-IN  | %s | %s", what, text)

            started = time.monotonic()
            if self._translator is None:
                self._translator = translate_mod.Translator(self.cfg)
            try:
                english, backend = self._translator.translate(text)
            except TranscriptionError as e:
                beep("error")
                log.error("translation failed: %s — your text is untouched",
                          e)
                return
            latency = time.monotonic() - started
            transcript_log.info("TRANSLATE-OUT | %.1fs | %s | %s", latency,
                                backend, english)

            if hwnd and injector.foreground_window() != hwnd:
                # The selection belongs to a window that is no longer
                # focused. Pasting now would overwrite whatever the user
                # switched to.
                injector.set_text(english)
                keep_clipboard = True   # restoring would take it back away
                beep("stop")
                log.warning("you moved to another window — the translation "
                            "is on your clipboard, press %s to paste it: %s",
                            self.cfg.paste_chord, english)
                return

            injector.paste_text(english, self.cfg.paste_chord,
                                self.cfg.restore_delay_ms)
            beep("translated")
            log.info("translated %d chars in %.1f s via %s: %s", len(english),
                     latency, backend, english)
        except injector.ClipboardBusyError as e:
            beep("error")
            log.error("paste failed: %s — the translation is in "
                      "transcripts.log", e)
        finally:
            if not keep_clipboard:
                try:
                    injector.restore(state, "translation")
                except injector.ClipboardBusyError as e:
                    log.warning("could not restore your clipboard: %s", e)

    def _handle(self, wav: bytes, seconds: float, hwnd: int,
                language: str | None = None) -> None:
        fb = self.cfg.feedback
        placeholder = fb.placeholder
        shown = False
        if fb.enabled and hwnd and injector.foreground_window() == hwnd:
            try:
                injector.show_placeholder(placeholder, self.cfg.paste_chord,
                                          self.cfg.restore_delay_ms)
                shown = True
            except injector.ClipboardBusyError as e:
                log.warning("could not show the placeholder: %s", e)

        started = time.monotonic()
        deadline = started + fb.retry_seconds
        item = None          # set once the audio is safely on disk
        last_error = ""
        attempt = 0
        text = backend = None

        while True:
            attempt += 1
            try:
                text, backend = self._transcribe(wav, language)
                break
            except TranscriptionError as e:
                last_error = str(e)
                # Save the audio BEFORE deciding whether to retry, so a
                # crash or a quit between attempts still cannot lose it.
                if item is None:
                    item = self.spool.save(wav, seconds, last_error)
                    log.error("%s — audio saved to %s", e,
                              item.wav_path.name)
                else:
                    item.bump(last_error)
                    log.error("retry %d failed: %s", attempt, e)
                wait = getattr(e, "retry_after", 0.0) or 3.0
                left = deadline - time.monotonic()
                if left <= 0 or wait > left:
                    break
                time.sleep(min(wait, left))
            except Exception as e:
                last_error = f"unexpected: {e}"
                if item is None:
                    item = self.spool.save(wav, seconds, last_error)
                log.exception("unexpected transcription failure")
                break

        latency = time.monotonic() - started

        if text is None:
            # Nothing to paste. Take the marker back down so the user is not
            # left with a stray "..." in their document.
            if shown:
                injector.clear_placeholder(placeholder, hwnd)
            beep("error")
            transcript_log.info("ERROR | %.1fs | %s | %s | kept: %s", seconds,
                                self.transcriber.name, last_error,
                                item.wav_path.name if item else "NOT SAVED")
            log.error("gave up after %.0f s — the recording is kept in "
                      "pending\\, run --drain to turn it into text later",
                      latency)
            return

        # Raw backend return goes to the log BEFORE any guard decides not to
        # paste it — this file is the recovery path.
        transcript_log.info("OK | %.1fs | %s | %.1fs latency | %s",
                            seconds, backend, latency, text)
        cleaned = text.strip()
        if not cleaned:
            if shown:
                injector.clear_placeholder(placeholder, hwnd)
            log.info("empty transcript (no speech heard) — not pasting")
            if item:
                item.discard()
            return

        try:
            if shown:
                status = injector.replace_placeholder(
                    placeholder, cleaned, self.cfg.paste_chord,
                    self.cfg.restore_delay_ms, hwnd)
            elif hwnd and injector.foreground_window() != hwnd:
                # No placeholder because focus had already moved when the
                # worker picked this up. Pasting now would drop the text into
                # a window the user never dictated into.
                raise injector.FocusChangedError(
                    "focus moved before the transcript was ready")
            else:
                status = injector.inject(cleaned, self.cfg.paste_chord,
                                         self.cfg.restore_delay_ms)
        except injector.FocusChangedError:
            # Do NOT fire backspaces into whatever the user switched to.
            injector.set_text(cleaned)
            beep("stop")
            log.warning("you moved to another window — the transcript is on "
                        "your clipboard, press %s to paste it: %s",
                        self.cfg.paste_chord, cleaned)
            if item:
                item.discard()
            return
        except injector.ClipboardBusyError as e:
            beep("error")
            log.error("paste failed: %s — the text is in transcripts.log", e)
            return

        if item:                      # transcribed at last: audio no longer
            item.discard()            # needed, drop it from the spool
        log.info("pasted %d chars (%.1f s round trip via %s; %s): %s",
                 len(cleaned), latency, backend, status, cleaned)


def setup_logging() -> None:
    handlers: list[logging.Handler] = []
    if HAS_CONSOLE:
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
        console = logging.StreamHandler(sys.stdout)
        console.setFormatter(logging.Formatter("%(asctime)s  %(message)s",
                                               "%H:%M:%S"))
        handlers.append(console)
    # Always mirror the status log to a file: when launched windowless this
    # is the only place errors can be read.
    app_file = logging.handlers.RotatingFileHandler(
        APP_DIR / "app.log", maxBytes=500_000, backupCount=2,
        encoding="utf-8")
    app_file.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | "
                                            "%(message)s"))
    handlers.append(app_file)
    logging.basicConfig(level=logging.INFO, handlers=handlers)
    file_handler = logging.handlers.RotatingFileHandler(
        APP_DIR / "transcripts.log", maxBytes=1_000_000, backupCount=3,
        encoding="utf-8")
    file_handler.setFormatter(logging.Formatter("%(asctime)s | %(message)s"))
    transcript_log.addHandler(file_handler)
    transcript_log.propagate = False  # transcripts.log only


def drain(cfg: config_mod.Config) -> int:
    """Turn recordings kept in pending\\ into text.

    These are utterances the backend refused at the time (almost always the
    free-tier daily cap). The audio was never thrown away, so this recovers
    the speech once quota is back.
    """
    spool = Spool(APP_DIR / "pending")
    items = spool.pending()
    if not items:
        print("Nothing pending — no recordings were lost.")
        return 0
    print(f"{len(items)} recording(s) waiting. Transcribing oldest first...\n")
    transcriber = get_transcriber(cfg)
    recovered = failed = 0
    for item in items:
        label = f"{item.wav_path.name} ({item.seconds:.1f}s)"
        try:
            text = transcriber.transcribe(item.read()).strip()
        except TranscriptionError as e:
            print(f"  [still failing] {label}: {e}")
            item.bump(str(e))
            failed += 1
            continue
        transcript_log.info("DRAINED | %.1fs | %s | %s", item.seconds,
                            transcriber.name, text)
        print(f"  [recovered]     {label}:\n      {text}\n")
        item.discard()
        recovered += 1
    print(f"\n{recovered} recovered, {failed} still waiting.")
    if recovered:
        print("Recovered text is also appended to transcripts.log.")
    if failed:
        print("Still-failing recordings are kept — run --drain again later.")
    return 0


def is_elevated() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Hebrew push-to-talk dictation (hold hotkey, speak, "
                    "release).")
    parser.add_argument("--config", default=str(APP_DIR / "config.toml"))
    parser.add_argument("--fake", action="store_true",
                        help="use the fake backend (no API, no mic quality "
                             "needed)")
    parser.add_argument("--check", action="store_true",
                        help="validate Gemini key + model with one tiny "
                             "request, then exit")
    parser.add_argument("--list-devices", action="store_true",
                        help="list audio input devices, then exit")
    parser.add_argument("--stop", action="store_true",
                        help="ask a running instance to quit, then exit")
    parser.add_argument("--test-sound", action="store_true",
                        help="play every audio cue once, then exit")
    parser.add_argument("--translate", metavar="TEXT",
                        help="translate TEXT and print it, then exit — "
                             "checks the translate backends without "
                             "touching the keyboard or clipboard")
    parser.add_argument("--drain", action="store_true",
                        help="transcribe recordings kept in pending\\ "
                             "(saved when the backend was down), print them, "
                             "then exit")
    args = parser.parse_args()
    setup_logging()

    if args.test_sound:
        cues.ensure_files(force=True)
        for kind in ("ready", "start", "stop", "translating", "translated",
                     "error", "bye"):
            print(f"playing '{kind}' cue...")
            cues.play(kind)
            time.sleep(1.2)
        print(f"\nHeard nothing? These play through the DEFAULT playback "
              f"device.\nWAV files: {cues.CUE_DIR}\nCheck Settings > System "
              f"> Sound > Volume mixer while this runs.")
        return 0

    if args.stop:
        if singleton.request_quit():
            log.info("stop signal sent to the running instance")
        else:
            log.info("nothing to stop — dictation is not running")
        return 0

    if args.list_devices:
        import sounddevice as sd
        print(sd.query_devices())
        print('\nPut the index or a unique name substring into config.toml '
              '-> [audio] device = "..."')
        return 0

    try:
        cfg = config_mod.load(Path(args.config))
    except ConfigError as e:
        log.error("%s", e)
        return 1
    if args.fake:
        cfg = dataclasses.replace(cfg, backend="fake")

    if args.check:
        try:
            from transcribers.gemini import GeminiTranscriber
            t = GeminiTranscriber(cfg.gemini.model, cfg.gemini.timeout_s)
            print(f"key source: {t.key_source}")
            print(f"checking key + model '{cfg.gemini.model}' with one tiny "
                  "request...")
            reply = t.check()
            print(f"API reply: {reply!r} — key and model look good.")
            return 0
        except TranscriptionError as e:
            print(f"check FAILED: {e}")
            return 1

    if args.translate:
        import translate as translate_mod
        if not translate_mod.needs_translation(args.translate,
                                               cfg.translate.target):
            print(f"no Hebrew in that text — already "
                  f"{cfg.translate.target}, nothing to do.")
            return 0
        started = time.monotonic()
        try:
            text, backend = translate_mod.Translator(cfg).translate(
                args.translate)
        except TranscriptionError as e:
            print(f"translation FAILED: {e}")
            return 1
        print(f"[{backend}, {time.monotonic() - started:.1f}s] {text}")
        return 0

    if args.drain:
        return drain(cfg)

    try:
        lock = singleton.InstanceLock()
    except singleton.AlreadyRunning as e:
        report_fatal(str(e))
        return 1

    try:
        app = App(cfg)
    except TranscriptionError as e:   # missing key, stub backend, ...
        report_fatal(str(e))
        return 1
    except ValueError as e:           # unknown hotkey/chord name
        report_fatal(f"bad key name in config.toml: {e}")
        return 1
    except Exception as e:            # no input device, PortAudio errors
        report_fatal(f"could not start audio capture: {e}\n\nCheck Settings "
                     "> Privacy & security > Microphone, and the device "
                     "index in config.toml (see --list-devices).")
        return 1

    quit_signal = singleton.QuitSignal()
    try:
        app.start()
    except OSError as e:
        report_fatal(str(e))
        return 1
    log.info("ready — hold '%s' for Hebrew%s, release to paste. %s",
             cfg.hotkey,
             f", '{cfg.english_hotkey}' for English" if cfg.english_hotkey
             else "",
             "Ctrl+C here to quit." if HAS_CONSOLE
             else 'Double-click "Stop Dictation.vbs" to quit.')
    if cfg.translate_hotkey:
        log.info("tap '%s' to turn the selection — or the whole field when "
                 "nothing is selected — into %s", cfg.translate_hotkey,
                 cfg.translate.target)
    log.info("mic: %s | backend: %s | transcripts: %s",
             app.recorder.device_label(), cfg.backend,
             APP_DIR / "transcripts.log")
    key_source = getattr(app.transcriber, "key_source", None)
    if key_source:
        log.info("api key from: %s", key_source)
    if not is_elevated():
        log.info("note: running non-elevated — dictation into run-as-admin "
                 "windows will not work (see README)")
    waiting = app.spool.pending()
    if waiting:
        log.warning("%d recording(s) from earlier could not be transcribed "
                    "and are waiting in pending\\ — run "
                    'main.py --drain to turn them into text', len(waiting))
    beep("ready")
    try:
        quit_signal.wait()   # released by --stop; Ctrl+C also lands here
        log.info("stop requested")
    except KeyboardInterrupt:
        log.info("interrupted")
    finally:
        beep("bye")
        app.stop()
        quit_signal.close()
        lock.release()
        time.sleep(0.35)     # let the shutdown cue finish playing
    log.info("bye")
    return 0


if __name__ == "__main__":
    sys.exit(main())
