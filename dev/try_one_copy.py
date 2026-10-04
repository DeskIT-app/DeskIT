"""See "DeskIT is on this PC twice" on your own screen — nothing is removed.

The window only ever appears in a released copy that finds the other one
(onecopy.checks_here is False in this checkout, by design), so the Dev
copy never shows it. This opens the REAL window against the Store copy
really installed on this PC, with every action that would change
anything replaced by a line saying what it would have done:

    .venv\\Scripts\\python.exe dev\\try_one_copy.py           as the website copy sees it
    .venv\\Scripts\\python.exe dev\\try_one_copy.py --store   as the Store copy sees it

Real: finding the Store copy, the window and its four faces, and the
Windows Settings pages the buttons open (opening one removes nothing —
only its own Uninstall button would). Printed instead of done: every
uninstall, every start of another copy, the Claude Code hook lines, a
quit. The data folder is a fresh scratch one, so nothing of the Dev
copy's is read or written.
"""
from __future__ import annotations

import argparse
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--store", action="store_true",
                        help="as the Store copy sees it (the website copy is made up)")
    args = parser.parse_args()
    os.environ["DESKIT_HOME"] = tempfile.mkdtemp(prefix="deskit-try-one-copy-")
    import onecopy
    import onecopy_window

    def say(text: str) -> None:
        print(f"  would have: {text}", flush=True)

    class Safe:
        store_copy = staticmethod(onecopy.store_copy)            # real: is it still there?
        open_store_settings = staticmethod(onecopy.open_store_settings)   # real, removes nothing
        open_uri = staticmethod(onecopy_window.Actions.open_uri)          # real, removes nothing

        @staticmethod
        def remove_website(copy, **_k):
            say(f"run {copy.uninstaller} /VERYSILENT (data kept) and wait for it to go")
            time.sleep(3)
            return True

        @staticmethod
        def uninstall_self_then_open_store(copy, **_k):
            say(f"uninstall this copy silently ({copy.uninstaller}), then open DeskIT App")
            return True

        @staticmethod
        def start_website_waiting(copy, **_k):
            say(f"start the website copy ({copy.folder}) already waiting for DeskIT App to go")
            return True

        @staticmethod
        def move_claude_door(to, website, **_k):
            say(f"give Claude Code's hook lines to the {to} copy, if a released copy held them")
            return False

        @staticmethod
        def quit_running(**_k):
            say("ask a running released DeskIT to quit")
            return True

    store = onecopy.store_copy()
    if store is None:
        print("No Store copy is installed for this Windows user: the window would never "
              "open on this PC. A made-up one stands in.")
        store = onecopy.Copy("store", "1.0.6")
    folder = os.path.expandvars(r"%LOCALAPPDATA%\Programs\DeskIT")
    website = onecopy.Copy("website", onecopy_window._own_version() or "1.0.7", channel="github",
                           folder=folder, uninstaller=folder + r"\unins000.exe")
    if args.store:
        print(f"As the Store copy ({store.version}) sees it, beside a made-up website copy.")
        window = onecopy_window.Window("store", website, actions=Safe())
    else:
        print(f"As a website copy sees it, beside the Store copy really installed here ({store.version}).")
        window = onecopy_window.Window("website", store, website, actions=Safe())
    print("Press any button; nothing on this PC is removed.\n", flush=True)
    window.root.mainloop()
    print(f"\nthe window ended with: {window.result} "
          f"({'DeskIT would start now' if window.result == 'start' else 'nothing would start'})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
