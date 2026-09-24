"""The master's window: dev\\master\\web\\dist inside WebView2.

It borrows the product's shell (``webdesk.py``) whole — the pre-check
that keeps pywebview from silently falling back to MSHTML and writing
HKCU on the way, the virtual host instead of a server or file://, our own
CoreWebView2 environment with crash reporting kept local, the muted
InPrivate profile, the scrubbed environment, the hardened bridge — and
gives it a different page and a different Api. That is the whole of the
master being the pilot for the web stack: whatever breaks in the shell
breaks here first, in the one DeskIT window with no users on it.

    .venv\\Scripts\\python.exe -m dev.master.window            # the window
    .venv\\Scripts\\python.exe -m dev.master.window --shot x.png  # photograph it, hidden

The window is its own process and speaks to nothing: the app's pipe is
not opened, the app need not be running, and everything on the screen
comes from files this checkout already holds.
"""
from __future__ import annotations

import sys
from pathlib import Path

if __package__ in (None, ""):                      # run by path, not by -m
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    __package__ = "dev.master"

from .api import Api                                # noqa: E402
from .root import Root                              # noqa: E402
from .store import Store                            # noqa: E402

HERE = Path(__file__).resolve().parent
DIST = HERE / "web" / "dist"
#: WebView2's own folder, beside the master's state and gitignored with it
PROFILE = HERE / "state" / "webview"
#: the title bar, the taskbar and Alt-Tab (dev\master\make_icon is gone;
#: dev\make_logo.py draws this and the app's icon from the one mark)
ICON = HERE / "master.ico"
TITLE = "DeskIT Master"


def open_window(*, root: Root | None = None, dist: Path | None = None,
                net: bool = True, width: int = 1180, height: int = 780,
                on_ready=None, home: Path | None = None) -> int:
    """0 when it ran, 2 when this PC has no WebView2, 3 when the pages
    are not built (npm run build in dev\\master\\web)."""
    root = root or Root.here()
    if str(root.dir) not in sys.path:               # webdesk.py imports paths
        sys.path.insert(0, str(root.dir))
    from . import webdesk                           # noqa: PLC0415

    api = Api(root, Store(root.master_state), home=home, net=net)
    PROFILE.mkdir(parents=True, exist_ok=True)
    return webdesk.run(dist=Path(dist or DIST), title=TITLE, api=api,
                       storage=PROFILE, width=width, height=height,
                       icon=ICON if ICON.is_file() else None,
                       on_ready=on_ready)


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="the DeskIT master app's window")
    ap.add_argument("--root", help="the DeskIT checkout to read (default: this one)")
    ap.add_argument("--dist", help="the built pages (default dev/master/web/dist)")
    ap.add_argument("--no-net", action="store_true", help="do not ask GitHub or the server")
    ap.add_argument("--shot", help="photograph the window into this PNG and close it")
    ap.add_argument("--screen", default="home", help="which screen the shot shows")
    ap.add_argument("--click", help="a selector to press before the shot (e.g. .take)")
    ns = ap.parse_args(argv)
    root = Root(Path(ns.root).resolve()) if ns.root else Root.here()

    on_ready = None
    if ns.shot:
        def on_ready(desk):                          # noqa: ANN001
            import json
            import time
            note = {}
            try:
                if ns.screen != "home":
                    desk.js(f"window.location.hash = '#/{ns.screen}'")
                # wait for the screen's first read rather than guessing at it
                deadline = time.monotonic() + 40
                while time.monotonic() < deadline:
                    time.sleep(0.4)
                    busy = desk.js("!!document.querySelector('.read')"
                                   "?.textContent?.includes('reading')")
                    if not busy:
                        break
                time.sleep(0.5)
                if ns.click:
                    desk.js(f"document.querySelectorAll('{ns.click}')[0]?.click()")
                    time.sleep(1.2)
                note["rows"] = desk.js("document.querySelectorAll('.row,.mrow').length")
                note["title"] = desk.js("document.querySelector('.title')?.textContent")
                note["capture"] = desk.capture(ns.shot)
            except Exception as e:                    # noqa: BLE001
                note["error"] = f"{type(e).__name__}: {e}"
            note.update(errors=desk.errors, dropped=desk.dropped, blocked=desk.blocked,
                        stamps=sorted(desk.stamps), env=desk.env_info)
            print(json.dumps(note, ensure_ascii=False, default=str)[:2000])

    code = open_window(root=root, dist=Path(ns.dist) if ns.dist else None,
                       net=not ns.no_net, on_ready=on_ready)
    if code == 2:
        print("this PC has no WebView2 runtime (or no .NET 4.6.2)", file=sys.stderr)
    if code == 3:
        print(f"no pages built: run  npm install && npm run build  in {DIST.parent}",
              file=sys.stderr)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
