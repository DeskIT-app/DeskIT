"""Contact sheets out of proto_keep_shots.py's pictures: what he looks at.

    python proto_keep_sheets.py DIR

The bottom of each picture (the field's keyboard), side by side, labelled.
Pillow only, and nothing opens on screen.
"""
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
FONT = next(iter(sorted((ROOT / "fonts").glob("Rubik*.ttf"))), None)
BG = (40, 40, 44)
INK = (235, 235, 235)


def font(size: int):
    return ImageFont.truetype(str(FONT), size) if FONT else ImageFont.load_default()


def crop(path: Path, keep: int) -> Image.Image:
    im = Image.open(path).convert("RGB")
    return im.crop((0, im.height - keep, im.width, im.height))


def sheet(folder: Path, out: str, cols: list[str], rows: list[tuple[str, list[str | None]]],
          keep: int = 1150, width: int = 520) -> None:
    pad, head, side = 14, 70, 230
    cells = []
    for _, names in rows:
        cells.append([crop(folder / f"{n}.png", keep) if n else None for n in names])
    h = int(keep * width / 1080)
    W = side + len(cols) * (width + pad) + pad
    H = head + len(rows) * (h + pad) + pad
    canvas = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(canvas)
    for i, c in enumerate(cols):
        d.text((side + pad + i * (width + pad), 18), c, font=font(30), fill=INK)
    for r, (label, names) in enumerate(rows):
        y = head + r * (h + pad)
        d.multiline_text((pad, y + 10), label, font=font(26), fill=INK, spacing=6)
        for i, im in enumerate(cells[r]):
            if im is not None:
                canvas.paste(im.resize((width, h), Image.LANCZOS), (side + pad + i * (width + pad), y))
    canvas.save(folder / out)
    print(folder / out)


def main() -> None:
    folder = Path(sys.argv[1])
    sheet(folder, "COMPARE_B_mic_vs_A_row.png",
          ["B: the mic is Continue", "A: Continue on the line"],
          [("The keyboard\ncomes back", ["01_B_paused", "01_A_paused"]),
           ("An older one\nwaits too", ["04_B_paused_and_waiting", "04_A_paused_and_waiting"]),
           ("320 dp phone", ["05_320dp_B_paused", "05_320dp_A_paused"]),
           ("Largest text", ["05_largest_text_B_paused", "05_largest_text_A_paused"]),
           ("320 dp and\nlargest text\n(B's word\nshrunk to fit)", ["05_320dp_largest_text_B_paused_fit",
                                                            "05_320dp_largest_text_A_paused"])])
    sheet(folder, "SHEET_story_B.png",
          ["", ""],
          [("Today", ["00_today_locked", "00_today_discarded"]),
           ("Back, kept\n· Continue", ["01_B_paused", "02_continue_locked"]),
           ("Finished\n· Sent", ["02b_continue_then_finished", "03_after_send"]),
           ("Older waiting\n· paused first", ["04_waiting_today", "04_B_paused_and_waiting"]),
           ("Sent · the\nolder row back", ["04c_sent_the_paused_one", "04d_the_older_one_is_back"])])


if __name__ == "__main__":
    main()
