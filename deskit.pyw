"""The installed copy's entry — what the Start-menu shortcut, the Run
value and the dashboard's relaunch all point at (DISTRIBUTION_PLAN.md
10.2, D19):

    python\\pythonw.exe app\\deskit.pyw            # the app
    python\\pythonw.exe app\\deskit.pyw --dashboard  # the window

Nothing but main.main(): the flags are main.py's, and so is everything
else. It exists so the shortcut has a stable name that is not main.py
and so the tree has one entry to point every launcher at. The checkout
keeps its .vbs launchers and never runs this file.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import main  # noqa: E402

sys.exit(main.main())
