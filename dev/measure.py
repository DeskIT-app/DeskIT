"""The owner's three measuring commands, out of the product (MASTER.md §8).

`--benchmark`, `--study` and `--review` were flags on `main.py` behind a
`paths.DEVELOPER` guard that printed "that command is for the developer's
checkout only" on anybody else's copy. They are his tools, they only ever
had a corpus to work on in this checkout, and a guard inside the product
is exactly what §8 exists to delete: what he runs in Dev has to be what a
user gets. So they live here, in `dev\`, which `.gitattributes` keeps out
of `git archive` and therefore out of every installed copy.

House rule 4 — measure, do not assume — is what these are for:

    .venv\\Scripts\\python.exe dev\\measure.py --benchmark
    .venv\\Scripts\\python.exe dev\\measure.py --study
    .venv\\Scripts\\python.exe dev\\measure.py --review

`benchmark` is moved verbatim from main.py; `word_error_rate` stayed
there, because review.py and study.py both import it and they ship.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
APP = HERE.parent
sys.path.insert(0, str(APP))
os.chdir(APP)

import config as config_mod            # noqa: E402
import paths                           # noqa: E402
import vocab as vocab_mod              # noqa: E402
from main import Spool, word_error_rate  # noqa: E402


def benchmark(cfg: config_mod.Config) -> int:
    """Replay every corrected recording with the vocabulary on and off.

    This is the whole reason recent\\ exists. "It feels better since I added
    those words" is not evidence, and the vocabulary is the kind of feature
    that is very easy to believe in and very hard to notice failing. Every
    recording the user has corrected is a labelled test case: the audio, and
    what it should have said.

    One model, transcribed twice — building two would double the VRAM for
    nothing, since the only difference is a prompt.
    """
    recent = Spool(paths.RECENT_DIR)
    cases = [i for i in recent.pending() if i.meta.get("corrected")]
    if not cases:
        print("No corrected recordings yet, so there is nothing to measure.")
        print(f"Dictate, then tap '{cfg.correct_hotkey}' and fix what it got")
        print("wrong. Each correction becomes a test case here.")
        if cfg.vocab.keep_audio <= 0:
            print("\nNote: [vocab] keep_audio = 0, so no audio is being "
                  "kept — corrections can never be replayed.")
        return 0

    v = vocab_mod.Vocab(paths.VOCAB_FILE, seed_terms=cfg.vocab.terms,
                        max_terms=cfg.vocab.max_terms,
                        replace_after_hits=cfg.vocab.replace_after_hits,
                        hebrew_after_hits=cfg.vocab.hebrew_after_hits)
    on = {"enabled": False}
    from transcribers import local_kwargs
    from transcribers.local_whisper import LocalWhisperTranscriber

    print(f"{len(cases)} corrected recording(s). Loading the model...")
    t = LocalWhisperTranscriber(
        **local_kwargs(cfg, lambda: v.hotwords() if on["enabled"] else ""))

    totals = {False: [0, 0], True: [0, 0]}
    for item in cases:
        truth = item.meta["corrected"]
        audio = item.read()
        line = {}
        for flag in (False, True):
            on["enabled"] = flag
            guess = t.transcribe(audio)
            if flag:                       # the repair pass runs in real use
                guess, _ = v.apply(guess)
            edits, words = word_error_rate(truth, guess)
            totals[flag][0] += edits
            totals[flag][1] += words
            line[flag] = (edits, words, guess)
        before = line[False][0] / max(1, line[False][1])
        after = line[True][0] / max(1, line[True][1])
        flag = "  " if abs(after - before) < 1e-9 else \
               ("->" if after < before else "!!")
        print(f"\n{flag} {item.wav_path.name}  ({item.seconds:.1f}s)  "
              f"WER {before:.1%} -> {after:.1%}")
        if after != before:
            print(f"     off: {line[False][2]}")
            print(f"     on : {line[True][2]}")
            print(f"     want: {truth}")

    off_wer = totals[False][0] / max(1, totals[False][1])
    on_wer = totals[True][0] / max(1, totals[True][1])
    print(f"\n{'=' * 60}")
    print(f"vocabulary OFF: {off_wer:.2%} WER over {totals[False][1]} words")
    print(f"vocabulary ON : {on_wer:.2%} WER over {totals[True][1]} words")
    if on_wer < off_wer:
        print(f"\n{(off_wer - on_wer) / off_wer:.0%} relative improvement.")
    elif on_wer > off_wer:
        print("\nThe vocabulary made it WORSE on this set. Likely causes: a "
              "term seeded that you rarely say (Whisper emits prompted words "
              "unbidden), or too many terms — try lowering max_terms.")
    else:
        print("\nNo difference on this set.")
    print("\nNote: these are the recordings you chose to correct, so they "
          "are the hard ones by construction — not a sample of normal "
          "dictation.")
    return 0


def study(cfg: config_mod.Config) -> int:
    """The study pass over every recording nobody corrected (study.py)."""
    try:
        import study as study_mod
    except ImportError:
        print("study.py is not in this folder, so there is no study "
              "engine to run.")
        return 2
    if getattr(cfg, "study", None) is None:
        print("the settings have no [study] section.")
        return 2
    return study_mod.study_all(cfg, paths.DATA_DIR)


def review(cfg: config_mod.Config) -> int:
    """The second reading over every labelled recording (review.py)."""
    try:
        import review as review_mod
    except ImportError:
        print("review.py is not in this folder, so there is no "
              "second reading to run.")
        return 2
    if getattr(cfg, "review", None) is None:
        print("the settings have no [review] section.")
        return 2
    return review_mod.review_all(cfg, paths.DATA_DIR)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="the owner's measuring commands (MASTER.md §8)")
    parser.add_argument("--benchmark", action="store_true",
                        help="replay every recording you have corrected, "
                             "with the learned vocabulary on and off, and "
                             "report the word error rate of each")
    parser.add_argument("--study", action="store_true",
                        help="study every recording in recent\\ that was "
                             "never corrected: re-decode it several ways, "
                             "adjudicate, and report what the live pass "
                             "got wrong (see study.py)")
    parser.add_argument("--review", action="store_true",
                        help="run the second reading over every recording a "
                             "human has labelled and score its proposals "
                             "against the truth (see review.py)")
    parser.add_argument("--config", default=None,
                        help="one file as the whole configuration, instead "
                             "of the three layers")
    args = parser.parse_args(argv)
    if not (args.benchmark or args.study or args.review):
        parser.print_help()
        return 2
    # THE CORPUS IS THE POINT, and it only exists here: recent\, corpus\
    # and transcripts.log are this checkout's training data
    # (paths.OWNER_DATA). Run from an installed tree there is nothing to
    # measure, so say so rather than loading a model for no reason.
    if not paths.OWNER_DATA:
        print("this is not the checkout, so there is no corpus to measure.")
        return 2
    cfg = (config_mod.load(Path(args.config)) if args.config
           else config_mod.load_layered())
    if args.benchmark:
        return benchmark(cfg)
    if args.study:
        return study(cfg)
    return review(cfg)


if __name__ == "__main__":
    raise SystemExit(main())
