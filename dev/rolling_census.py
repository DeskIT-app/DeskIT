"""Where the rolling transcriber would cut every kept recording, and
whether any seam lost a word. No decoding, nothing written.

rolling.cut_at decides on the audio alone, so replaying a recording
through the Roller at the recorder's own 10 ms chunks gives back the
cuts the live run made — checked on the Store walk's 34.5 s dictation
(2026-10-03): the windows came out at 1.69 s, 28.23 s and a 7.19 s tail,
exactly what app.log said. For each cut it reports

  - whether it fell in a PAUSE (a quiet run of rolling.PAUSE_S or more)
    or was FORCED at MAX_WINDOW_S, and how long the quiet there was;
  - the word either side of it in the paste (the sidecar's `words`), and
    how many words each of the second reading's three whole-recording
    witnesses (`review.variants`) has between those two. A seam that lost
    a word reads 0 in the paste and 1 or more in every witness.

    .venv\\Scripts\\python.exe dev\\rolling_census.py [folder ...]

With no folder it reads this checkout's recent\\. The first run
(2026-10-04, 55 recordings across the Dev and the Store copy) found 55
cuts, 54 in a pause and none of those short of a word where a witness
could tell, and one forced cut — inside "מייקרוסופט", with "הפגישה"
lost after it. That is what changed cut_at's forced branch.
"""
from __future__ import annotations

import json
import re
import sys
import wave
from pathlib import Path

HERE = Path(__file__).resolve().parent
APP = HERE.parent
sys.path.insert(0, str(APP))

import numpy as np                     # noqa: E402

import paths                           # noqa: E402
import rolling                         # noqa: E402

CHUNK = 160          # 10 ms at 16 kHz: what reproduced the live cuts
_TOKEN = re.compile(r"[^\w֐-׿]")


def _norm(word: str) -> str:
    return _TOKEN.sub("", word or "").lower()


def cuts_of(pcm: np.ndarray, rate: int,
            window_s: float = 25.0) -> list[dict]:
    """The Roller over `pcm` as it arrived, polled every POLL_S of audio:
    one {at, quiet_s, kind} per cut, `at` in seconds into the recording."""
    chunks = [pcm[i:i + CHUNK] for i in range(0, len(pcm), CHUNK)]
    clock = {"t": 0.0}
    seen: list[tuple] = []
    real = rolling.cut_at

    def spy(peaks, sizes, rate_, window, **kw):
        k = real(peaks, sizes, rate_, window, **kw)
        if k:
            seen.append((list(peaks), list(sizes), k))
        return k

    roller = rolling.Roller(
        lambda mark: chunks[mark:int(clock["t"] * rate) // CHUNK], rate,
        lambda wav, lead, keep: rolling.Window(0.0, 0.0, "x"), window_s,
        lambda c, r: b"", overlap=False)
    out: list[dict] = []
    rolling.cut_at = spy
    try:
        while clock["t"] < len(pcm) / rate:
            clock["t"] += rolling.POLL_S
            before, offset = len(seen), roller._offset
            roller._step()
            if len(seen) == before:
                continue
            peaks, sizes, k = seen[-1]
            quiet = _quiet_around(peaks, sizes, k) / rate
            out.append(dict(at=(offset + sum(sizes[:k])) / rate,
                            quiet_s=round(quiet, 3),
                            kind="pause" if quiet >= rolling.PAUSE_S
                            else "forced"))
    finally:
        rolling.cut_at = real
    return out


def _quiet_around(peaks, sizes, k) -> int:
    """Samples of quiet in the run the cut went through (0 if none)."""
    threshold = rolling.quiet_threshold(peaks)
    i = k if peaks[k] < threshold else k - 1
    if i < 0 or peaks[i] >= threshold:
        return 0
    j = e = i
    while j > 0 and peaks[j - 1] < threshold:
        j -= 1
    while e + 1 < len(peaks) and peaks[e + 1] < threshold:
        e += 1
    return sum(sizes[j:e + 1])


def _between(text: str, a: str, b: str) -> int | None:
    """Words between `a` and the next `b` within five words, or None."""
    toks = [_norm(t) for t in (text or "").split()]
    for i, t in enumerate(toks):
        if t == a:
            for j in range(i + 1, min(len(toks), i + 6)):
                if toks[j] == b:
                    return j - i - 1
    return None


def census(folders: list[Path]) -> int:
    total = forced = lost = whole = 0
    for folder in folders:
        for wav_path in sorted(folder.glob("*.wav")):
            with wave.open(str(wav_path), "rb") as w:
                rate = w.getframerate()
                pcm = np.frombuffer(w.readframes(w.getnframes()),
                                    dtype=np.int16)
            if len(pcm) / rate < 25.0:
                continue
            side = wav_path.with_suffix(".json")
            meta = json.loads(side.read_text("utf-8")) if side.exists() else {}
            words = meta.get("words") or []
            variants = (meta.get("review") or {}).get("variants") or []
            for cut in cuts_of(pcm, rate):
                total += 1
                forced += cut["kind"] == "forced"
                before = [w for w in words if (w[1] + w[2]) / 2 < cut["at"]]
                after = [w for w in words if (w[1] + w[2]) / 2 >= cut["at"]]
                verdict = ""
                if before and after and variants:
                    a, b = _norm(before[-1][0]), _norm(after[0][0])
                    counts = [_between(v, a, b) for v in variants]
                    if any(n == 0 for n in counts):
                        whole += 1
                    elif any(n for n in counts):
                        lost += 1
                        verdict = f"  WITNESSES HEAR MORE HERE: {counts}"
                if cut["kind"] == "forced" or verdict:
                    print(f"{wav_path.name}: {cut['kind']} cut at "
                          f"{cut['at']:.2f} s (quiet {cut['quiet_s']} s) "
                          f"between {before[-1][0] if before else '-'!r} "
                          f"and {after[0][0] if after else '-'!r}{verdict}")
    print(f"\n{total} cuts: {total - forced} in a pause, {forced} forced; "
          f"{whole} seams a witness confirms whole, {lost} where the "
          f"witnesses hear words the paste does not have")
    return 0


if __name__ == "__main__":
    args = [Path(a) for a in sys.argv[1:]] or [paths.RECENT_DIR]
    sys.exit(census(args))
