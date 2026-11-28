"""A phone stream against the whole decode, through the REAL model (PHONE_LINK_PLAN.md
stage 2): what the emulator's stand-in cannot say. AT NIGHT ONLY: it loads the speech
model on the graphics card his Dev copy holds by day.

    <venv python> dev\\stream_bench.py WAV [WAV ...] [--pace 1.0] [--standin]

For each recording (16 kHz mono 16-bit, as a phone records it): (1) the whole decode, as
/transcribe does it today, timed; (2) the same audio fed to phonestream.PhoneStream at
``pace`` times real time (1.0: as he speaks it), a real rolling.Roller reading it with the
model's own decode_window, and at its end transcribe_with_head, timed from the end; (3)
the two texts compared word by word. Prints one line per recording and a table. Opens no
window, sends nothing anywhere, reads nothing of his but the files named, writes nothing.
``--standin``: flow_stream's stand-in model instead, to check the plumbing by day.
"""
from __future__ import annotations

import argparse
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def model(standin: bool):
    if standin:
        sys.path.insert(0, str(ROOT / "dev" / "android"))
        import flow_stream
        return flow_stream.standin()
    import config as config_mod
    from transcribers import get_transcriber
    cfg = config_mod.load_layered()
    return get_transcriber(cfg)


def bench(t, wav: bytes, pace: float, window_s: float) -> dict:
    import numpy as np

    import main as main_mod
    import phonestream
    import rolling
    from recorder import frames_to_wav

    lock = threading.Lock()
    began = time.perf_counter()
    with lock:
        whole = t.transcribe(wav)
    whole_s = time.perf_counter() - began

    pcm = wav[44:]
    stream = phonestream.PhoneStream()

    def decode(w, lead_s, keep_s):
        with lock:
            return t.decode_window(w, lead_s, keep_s)

    roller = rolling.Roller(stream.chunks_since, stream.sample_rate, decode, window_s,
                            frames_to_wav, overlap=bool(getattr(t, "can_overlap", False)))
    roller.start()
    step = 3200                                       # a tenth of a second, as the keyboard sends
    t0 = time.perf_counter()
    for i in range(0, len(pcm), step):
        stream.feed(pcm[i:i + step])
        due = t0 + (i + step) / 32000.0 / pace
        left = due - time.perf_counter()
        if left > 0:
            time.sleep(left)
    end = time.perf_counter()
    roller.close()
    head = roller.finish()
    with lock:
        text = t.transcribe_with_head(stream.wav(), head) if head is not None else t.transcribe(stream.wav())
    after_s = time.perf_counter() - end
    errors, words = main_mod.word_error_rate(whole, text)
    return {"seconds": len(pcm) / 32000.0, "whole_s": whole_s, "after_s": after_s,
            "windows": len(head.windows) if head else 0, "head_s": head.end_s if head else 0.0,
            "busy_s": roller.busy_s, "edits": errors, "words": words, "same": whole == text}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("wavs", nargs="+")
    ap.add_argument("--pace", type=float, default=1.0)
    ap.add_argument("--window", type=float, default=25.0)
    ap.add_argument("--standin", action="store_true")
    a = ap.parse_args()
    t = model(a.standin)
    print("seconds  whole decode  streamed, from its end  windows  word edits (streamed vs whole)")
    for path in a.wavs:
        r = bench(t, Path(path).read_bytes(), a.pace, a.window)
        print(f"{r['seconds']:7.1f}  {r['whole_s']:10.2f} s  {r['after_s']:12.2f} s       "
              f"{r['windows']:3d} to {r['head_s']:5.1f} s  {r['edits']}/{r['words']}"
              f"{'  (the same text)' if r['same'] else ''}", flush=True)


if __name__ == "__main__":
    main()
