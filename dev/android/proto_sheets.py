"""Contact sheets out of proto_shots.py's pictures: what he looks at.

    python proto_sheets.py DIR

Pillow only, and nothing opens on screen.
"""
import sys
from pathlib import Path

from PIL import Image

MAIN = ["signin", "waiting", "pressed", "ready", "devices", "asking", "changed"]
MORE = ["preparing", "removed", "nolock", "declined", "refused", "forget", "signout", "signingout",
        "leaving", "twins", "signin_gone"]
NARROW = ["signin", "waiting", "asking", "changed", "forget", "signout"]


def sheet(folder: Path, items: list[str], out: str, cols: int, width: int) -> None:
    ims = [Image.open(folder / f"{n}.png").convert("RGB") for n in items]
    height = int(ims[0].height * width / ims[0].width)
    rows = (len(ims) + cols - 1) // cols
    canvas = Image.new("RGB", (cols * width + (cols + 1) * 12, rows * height + (rows + 1) * 12),
                       (60, 60, 60))
    for i, im in enumerate(ims):
        canvas.paste(im.resize((width, height), Image.LANCZOS),
                     (12 + (i % cols) * (width + 12), 12 + (i // cols) * (height + 12)))
    canvas.save(folder / out)
    print(folder / out)


def main() -> None:
    folder = Path(sys.argv[1])
    sheet(folder, MAIN, "sheet_main.png", 4, 340)
    sheet(folder, MORE, "sheet_more.png", 5, 300)
    sheet(folder, ["narrow_" + n for n in NARROW], "sheet_narrow.png", 3, 360)


if __name__ == "__main__":
    main()
