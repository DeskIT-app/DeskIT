"""The account's screens, photographed from the emulator: the real widgets with
made-up data (ProtoActivity, debug builds only).

    python proto_shots.py OUT_DIR [--narrow]

--narrow takes them again on a small screen with large fonts and a phone
language that reads right to left, the case a developer's phone never shows.
It restores what it changes. Nothing opens on the owner's screen.
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import drive  # noqa: E402

SCREENS = ["signin", "signin_gone", "preparing", "waiting", "pressed", "removed", "nolock", "declined",
           "ready", "devices", "forget", "asking", "twins", "changed", "refused", "signout"]


def take(out: Path, prefix: str = "") -> None:
    out.mkdir(parents=True, exist_ok=True)
    drive.OUT = out
    for name in SCREENS:
        drive.shell("am", "start", "-W", "-S", "-n", f"{drive.PKG}/.ProtoActivity",
                    "--es", "screen", name)
        time.sleep(0.7)
        print(drive.shot(prefix + name))


def main() -> None:
    out = Path(sys.argv[1])
    if "--narrow" not in sys.argv:
        take(out)
        return
    drive.shell("wm", "size", "720x1280")
    drive.shell("wm", "density", "320")
    drive.shell("settings", "put", "system", "font_scale", "1.3")
    drive.shell("settings", "put", "global", "force_rtl_layout_all_locales", "1")
    try:
        time.sleep(1.5)
        take(out, "narrow_")
    finally:
        drive.shell("settings", "delete", "global", "force_rtl_layout_all_locales")
        drive.shell("settings", "put", "system", "font_scale", "1.0")
        drive.shell("wm", "density", "reset")
        drive.shell("wm", "size", "reset")


if __name__ == "__main__":
    main()
