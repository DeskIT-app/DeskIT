"""Look at the skin without booting the app.

    python -m skin.preview burst              play the release, full speed
    python -m skin.preview burst --sheet out.png    nine frames, as a file
    python -m skin.preview card               play a whole fake 14 s boot
    python -m skin.preview all                the boot and the release

Made a first-class part of the folder rather than a scratch file because
every visual decision in here was made by looking at a contact sheet, and
the next person to change a timing will want the same tool.
"""
from __future__ import annotations

import argparse
import sys
import time


def _sheet(width, height, path, times):
    import skia
    from PIL import Image
    from .burst import Burst
    shot = Burst(width, height, seed=7)
    cells = []
    for t in times:
        surface = skia.Surface.MakeRasterN32Premul(width, height)
        shot.draw(surface.getCanvas(), t)
        arr = surface.makeImageSnapshot().toarray(
            colorType=skia.kRGBA_8888_ColorType)
        img = Image.fromarray(arr, "RGBA")
        # over a mid-grey ground, so the alpha is judged honestly rather
        # than against black, which flatters every glow ever made
        ground = Image.new("RGBA", img.size, (30, 33, 40, 255))
        cells.append(Image.alpha_composite(ground, img).convert("RGB")
                     .resize((640, 360), Image.LANCZOS))
    sheet = Image.new("RGB", (640 * 3, 360 * ((len(cells) + 2) // 3)), "black")
    for i, cell in enumerate(cells):
        sheet.paste(cell, ((i % 3) * 640, (i // 3) * 360))
    sheet.save(path)
    print("wrote", path, sheet.size)


def _play_burst(seed=None):
    """Play whichever release the app would actually play here.

    reveal.py on a GPU, burst.py without one — the same choice boot.py
    makes, so what this shows is what boots show.
    """
    import statistics
    from .glass import Glass, primary_screen
    pw, ph = primary_screen()
    glass = Glass(0, 0, pw, ph)
    origin = (pw - 250, ph - 150)
    seed = int(time.time()) if seed is None else seed
    if glass.on_gpu:
        from .reveal import Reveal, T_DIP, T_END
        shot = Reveal(pw, ph, origin=origin, seed=seed)
        where = f"GPU ({glass.width}x{glass.height})"
    else:
        from .burst import Burst, T_DIP, T_END
        shot = Burst(pw, ph, seed=seed, came_from=origin)
        where = "CPU raster"
    # pay Skia's lazy pipeline build before the clock starts, the way
    # boot.py does during the model load
    for step in range(24):
        shot.draw(glass.canvas, T_DIP[0] + step * ((T_END - T_DIP[0]) / 24.0))
    glass.canvas.clear(0x00000000)
    glass.show()
    frames = []
    from .clock import Clock
    clock = Clock(T_DIP[0])
    while True:
        t = clock.tick()
        a = time.perf_counter()
        if not shot.draw(glass.canvas, t):
            break
        glass.flush()
        glass.pump()
        frames.append((time.perf_counter() - a) * 1000)
    glass.close()
    if frames:
        frames.sort()
        span = T_END - T_DIP[0]
        note = f"  ({clock.stalls} stalled)" if clock.stalls else ""
        print(f"{where}: {len(frames)} frames over {span:.0f} ms  "
              f"median {statistics.median(frames):.1f} ms  "
              f"p90 {frames[int(len(frames) * .9)]:.1f}  max {frames[-1]:.1f}"
              f"  -> {1000 / statistics.median(frames):.0f} fps{note}")


def _play_card(seconds=9.0):
    from .boot import Card
    from .glass import Glass
    lines = [(0.0, "starting…"),
             (0.6, "loading the transcription model…"),
             (3.2, "local model ivrit-ai/whisper-large-v3-turbo-ct2 ready "
                   "on cuda (float16)"),
             (3.4, "loading English model deepdml/faster-whisper-large-v3…"),
             (9.8, "phone endpoint on 127.0.0.1:8756"),
             (10.2, "groq repair backend is warm"),
             (12.6, "ready — hold 'right ctrl' and speak")]
    from .boot import GATHER_MS
    card = Card()
    glass = Glass(*card.placement())
    glass.show()
    from .clock import Clock
    clock = Clock()
    i = 0
    while True:
        elapsed = clock.tick() / 1000.0
        while i < len(lines) and elapsed >= lines[i][0]:
            card.status(lines[i][1])
            i += 1
        if elapsed > seconds and card.released_at is None:
            card.release()          # show the wind-up too, not just the idle
        if not card.draw(glass.canvas, elapsed * 1000):
            break
        glass.flush()
        glass.pump()
        time.sleep(1.0 / 90.0)
    glass.close()


def main(argv=None):
    parser = argparse.ArgumentParser(prog="skin.preview")
    parser.add_argument("what", choices=("burst", "card", "all"))
    parser.add_argument("--sheet")
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    args = parser.parse_args(argv)
    if args.sheet:
        _sheet(args.width, args.height, args.sheet,
               (-45, 20, 60, 110, 175, 260, 380, 520, 700))
        return 0
    if args.what in ("card", "all"):
        _play_card()
    if args.what in ("burst", "all"):
        _play_burst()
    return 0


if __name__ == "__main__":
    sys.exit(main())
