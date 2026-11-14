"""Does a page really move? Stills cannot say. This records a page change on the
emulator with animations on and reads the video back: how long the change took
and how many in-between frames it had, and a strip of them to look at.

    python motion_check.py OUT_DIR

It puts the animation scales back, and nothing opens on the owner's screen.
"""
import subprocess
import sys
import time
from pathlib import Path

import av
import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
import drive  # noqa: E402

SCALES = ("window_animation_scale", "transition_animation_scale", "animator_duration_scale")


def frames(path: Path) -> list[tuple[float, np.ndarray]]:
    out = []
    with av.open(str(path)) as box:
        for f in box.decode(video=0):
            out.append((float(f.time), f.to_ndarray(format="gray")[::4, ::4].astype(np.int16)))
    return out


def moves(seen: list[tuple[float, np.ndarray]]) -> list[tuple[float, float, int]]:
    """Each stretch of change: start, end, and how many frames were in it."""
    out, start, count, last = [], None, 0, seen[0][0]
    for (ta, a), (tb, b) in zip(seen, seen[1:]):
        changed = float(np.abs(a - b).mean()) > 0.15
        if changed:
            start = ta if start is None else start
            count += 1
            last = tb
        elif start is not None and tb - last > 0.15:
            out.append((start, last, count))
            start, count = None, 0
    if start is not None:
        out.append((start, last, count))
    return out


def main() -> None:
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    drive.OUT = out
    for s in SCALES:
        drive.shell("settings", "put", "global", s, "1")
    try:
        drive.home()
        drive.wait("^Settings$", 10)
        time.sleep(1.5)
        rec = subprocess.Popen([str(drive.ADB), "shell", "screenrecord", "--time-limit", "5",
                                "--bit-rate", "8000000", "/sdcard/motion.mp4"],
                               creationflags=subprocess.CREATE_NO_WINDOW)
        time.sleep(1.2)
        drive.tap("^Settings$", 5)
        time.sleep(1.5)
        drive.shell("input", "keyevent", "4")
        rec.wait(timeout=20)
        time.sleep(1)
        drive.adb("pull", "/sdcard/motion.mp4", out / "motion.mp4", timeout=60)
    finally:
        for s in SCALES:
            drive.shell("settings", "put", "global", s, "0")
    seen = frames(out / "motion.mp4")
    print(len(seen), "frames")
    for start, end, count in moves(seen):
        print(f"a change from {start:.2f}s to {end:.2f}s: {(end - start) * 1000:.0f} ms, {count} frames")
    # a strip of the first change, to look at
    stretch = moves(seen)[0]
    with av.open(str(out / "motion.mp4")) as box:
        pics = [(float(f.time), f.to_image()) for f in box.decode(video=0)]
    inside = [p for t, p in pics if stretch[0] - 0.02 <= t <= stretch[1] + 0.02]
    picks = [inside[int(i * (len(inside) - 1) / 5)] for i in range(6)]
    w = 240
    h = int(picks[0].height * w / picks[0].width)
    strip = Image.new("RGB", (6 * w + 7 * 8, h + 16), (60, 60, 60))
    for i, p in enumerate(picks):
        strip.paste(p.resize((w, h), Image.LANCZOS), (8 + i * (w + 8), 8))
    strip.save(out / "motion_strip.png")
    print(out / "motion_strip.png")


if __name__ == "__main__":
    main()
