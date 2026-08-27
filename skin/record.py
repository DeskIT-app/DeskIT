"""Film the boot, composited over a real screen grab.

Still frames lie about motion. Every judgement made from a contact sheet in
this folder's history was a judgement about COMPOSITION, and what actually
got rejected was TIMING - "it appears for half a second, you can barely see
it". A contact sheet cannot show that. So the whole moment gets filmed,
over a genuine screenshot of the desktop it plays on, and the film is what
gets looked at.

    python -m skin.record out.mp4                 the load, the wind-up, the reveal
    python -m skin.record out.mp4 --reveal-only   just the release
    python -m skin.record out.mp4 --fps 60 --scale 0.5

PyAV is already here - faster-whisper brings it, with its own libx264 - so
this costs no new dependency. h264 refuses odd-sided frames (yuv420p
subsamples chroma 2x2), so the size is rounded to even first.
"""
from __future__ import annotations

import argparse
import sys
import time


def _even(n: int) -> int:
    return n - (n % 2)


def _desktop(width: int, height: int):
    """One grab of the real desktop, as the ground the reveal plays over."""
    from PIL import Image, ImageGrab
    try:
        shot = ImageGrab.grab((0, 0, width, height), all_screens=True)
        return shot.convert("RGBA").resize((width, height), Image.LANCZOS)
    except Exception:
        return Image.new("RGBA", (width, height), (24, 26, 32, 255))


# The load, compressed. A real boot spends 14-25 s here and the card only
# has seven states worth seeing, so the film gives each one a beat rather
# than filming twenty seconds of a waveform breathing.
SCRIPT = (
    (0.0, "starting up"),
    (0.9, "loading the transcription model"),
    (2.1, "local model ivrit-ai/whisper-large-v3-turbo-ct2 ready on cuda"),
    (3.0, "loading English model deepdml/faster-whisper-large-v3"),
    (4.0, "phone endpoint on 127.0.0.1:8756"),
    (4.7, "groq repair backend is warm"),
    (5.4, "ready - hold 'right ctrl' and speak"),
)


def film(path: str, fps: int = 60, scale: float = 0.5,
         reveal_only: bool = False) -> str:
    import av
    import numpy as np
    import skia
    from PIL import Image

    from . import gl
    from .boot import Card, GATHER_MS, PAD, WAVE_Y, WIN_H, WIN_W
    from .glass import primary_screen

    pw, ph = primary_screen()
    out_w, out_h = _even(int(pw * scale)), _even(int(ph * scale))
    ground = _desktop(pw, ph)

    ctx = gl.acquire()
    if ctx is None:
        print("no GPU context; filming the CPU fallback instead")
    info = skia.ImageInfo.MakeN32Premul(pw, ph)
    screen = (ctx.surface(pw, ph) if ctx is not None
              else skia.Surface.MakeRaster(info))
    card_info = skia.ImageInfo.MakeN32Premul(WIN_W, WIN_H)
    card_surface = (ctx.surface(WIN_W, WIN_H) if ctx is not None
                    else skia.Surface.MakeRaster(card_info))

    card = Card()
    cx, cy, _cw, _ch = card.placement()
    heart = (cx + WIN_W / 2, cy + PAD + WAVE_Y)
    if ctx is not None:
        from .reveal import Reveal, T_DIP, T_END
        shot = Reveal(pw, ph, origin=heart, seed=11)
    else:
        from .burst import Burst, T_DIP, T_END
        shot = Burst(pw, ph, seed=11, came_from=heart)

    load_s = 0.0 if reveal_only else SCRIPT[-1][0] + 0.7
    if reveal_only:
        card.charge = card._floor = 1.0
        card.line = "Ready - hold Right Ctrl and speak"
    release_at = load_s
    end_s = release_at + (GATHER_MS + T_END + 260) / 1000.0

    big = np.empty((ph, pw, 4), dtype=np.uint8)
    small = np.empty((WIN_H, WIN_W, 4), dtype=np.uint8)

    container = av.open(path, mode="w")
    stream = container.add_stream("libx264", rate=fps)
    stream.width, stream.height = out_w, out_h
    stream.pix_fmt = "yuv420p"
    stream.options = {"crf": "16", "preset": "medium"}

    step = 1.0 / fps
    frames, spoken = 0, 0
    began = time.perf_counter()
    t = 0.0
    while t <= end_s:
        while spoken < len(SCRIPT) and not reveal_only and t >= SCRIPT[spoken][0]:
            card.status(SCRIPT[spoken][1])
            spoken += 1
        if t >= release_at and card.released_at is None:
            card.release()
        # the card eases its charge one frame at a time, so the film has to
        # tick it at the film's rate rather than at the wall clock's
        card.charge += (card.target() - card.charge) * 0.06

        frame = ground.copy()

        rel = (t - release_at) * 1000.0 if card.released_at is not None else -1e9
        if rel > -1e8:
            screen.getCanvas().clear(0x00000000)
            shot.draw(screen.getCanvas(), rel - GATHER_MS)
            screen.flushAndSubmit()
            screen.readPixels(info, big, pw * 4, 0, 0)
            frame = Image.alpha_composite(
                frame, Image.fromarray(big[:, :, [2, 1, 0, 3]], "RGBA"))

        card._forced_rel = rel
        alive = _draw_card(card, card_surface, card_info, small, rel)
        if alive:
            layer = Image.fromarray(small[:, :, [2, 1, 0, 3]], "RGBA")
            over = Image.new("RGBA", (pw, ph), (0, 0, 0, 0))
            over.paste(layer, (int(cx), int(cy)))
            frame = Image.alpha_composite(frame, over)

        rgb = frame.convert("RGB").resize((out_w, out_h), Image.LANCZOS)
        packet = av.VideoFrame.from_ndarray(np.asarray(rgb), format="rgb24")
        for encoded in stream.encode(packet):
            container.mux(encoded)
        frames += 1
        t += step

    for encoded in stream.encode():
        container.mux(encoded)
    container.close()
    took = time.perf_counter() - began
    print(f"wrote {path}: {frames} frames, {out_w}x{out_h} @ {fps} fps, "
          f"{end_s:.2f} s of animation, rendered in {took:.1f} s")
    return path


def _draw_card(card, surface, info, buf, rel):
    """Draw the card at a forced release time, so the film's clock and the
    card's agree. The card normally reads its own wall clock; a film has
    to be able to run slower or faster than one."""
    import time as _time
    canvas = surface.getCanvas()
    canvas.clear(0x00000000)
    if rel > -1e8:
        card.released_at = _time.monotonic() - rel / 1000.0
    alive = card.draw(canvas, 4200.0 + rel if rel > -1e8 else 4200.0)
    surface.flushAndSubmit()
    surface.readPixels(info, buf, buf.shape[1] * 4, 0, 0)
    return alive


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="skin.record")
    parser.add_argument("out")
    parser.add_argument("--fps", type=int, default=60)
    parser.add_argument("--scale", type=float, default=0.5)
    parser.add_argument("--reveal-only", action="store_true")
    args = parser.parse_args(argv)
    film(args.out, fps=args.fps, scale=args.scale,
         reveal_only=args.reveal_only)
    return 0


if __name__ == "__main__":
    sys.exit(main())
