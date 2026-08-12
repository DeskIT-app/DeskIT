"""List (and optionally restore) per-app volumes in the Windows mixer.

Written after an hour was lost to "Chrome has no sound": Chrome's slider in
the volume mixer was at 0% while every other app was fine. Windows offers
no obvious warning for that state, so this prints it plainly.

    python audio_check.py                 # show every app's volume
    python audio_check.py --fix chrome    # set matching apps back to 100%
"""
from __future__ import annotations

import argparse
import sys
import warnings

warnings.filterwarnings("ignore")  # pycaw warns about unreadable properties

try:
    from pycaw.pycaw import AudioUtilities
except ImportError:
    sys.exit("pycaw is not installed. Run:  .venv\\Scripts\\pip install "
             "pycaw")

STATE = {0: "inactive", 1: "playing", 2: "expired"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fix", metavar="NAME",
                        help="restore apps whose name contains NAME to 100%%")
    args = parser.parse_args()

    sessions = [s for s in AudioUtilities.GetAllSessions() if s.Process]
    if not sessions:
        print("no per-app audio sessions found")
        return 0

    for session in sessions:
        name = session.Process.name()
        volume = session.SimpleAudioVolume
        level = volume.GetMasterVolume()
        muted = bool(volume.GetMute())
        flag = "  <-- SILENT" if (level < 0.01 or muted) else ""
        print(f"  {name:24s} {level * 100:5.0f}%  "
              f"{'MUTED' if muted else '     '}  "
              f"{STATE.get(session.State, session.State)}{flag}")
        if args.fix and args.fix.lower() in name.lower():
            volume.SetMasterVolume(1.0, None)
            volume.SetMute(0, None)
            print(f"  {'':24s} -> restored to 100%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
