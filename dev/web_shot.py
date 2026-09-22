"""Photograph a web desk page — hidden, muted, the way the release renders it.

    python dev\\web_shot.py --dist web\\dist --out shot.png
    python dev\\web_shot.py --dist web\\dist --out said.png --route said --width 1280 --height 800
    python dev\\web_shot.py --dist web\\dist --out s.png --python C:\\path\\to\\python\\python.exe

What it does. This process — any Python, the venv is fine — starts a
CHILD on a hidden Windows desktop (tests_quiet.run_hidden, the house
rule-8 launcher: nothing appears on the screen, the pointer is never
taken) with the interpreter named by --python. The child silences
winsound and Tk's bell before it imports anything of the app's, opens
webdesk.run() with --dist mapped onto https://deskit.example/ (the same
virtual host, CSP, guards, muted WebView2 and InPrivate profile the desk
uses), waits for the page's load event, `document.fonts.ready` and two
more frames, writes CoreWebView2.CapturePreviewAsync to --out as a PNG,
closes the window and exits. One line of JSON comes back on stdout: the
PNG's size, how long each step took, and every request the guards
refused (a page that tries to reach the network says so here).

--dist      a folder with an index.html — `npm run build` in web\\ makes
            web\\dist; any static folder works (no server, no file://).
--out       the PNG to write (its folder is created).
--width/--height
            the window's size in logical pixels (default 1180 x 760). The
            PNG is the page's viewport, so it is slightly smaller than the
            window — 1164 x 721 for the default at 100 % scaling.
--route X   open on `index.html#/X` (the desk's pages route on the hash).
--python    an interpreter that has the web desk's packages. The venv
            does NOT, on purpose (the product suite imports every module
            without them). Default: %DESKIT_WEB_PYTHON%. How to make one
            — the release's own embeddable python with the five pinned
            wheels, which is also exactly what a release will run:

              copy dist\\stage\\python to a folder of your own, then
              .venv\\Scripts\\python.exe -m pip install --no-deps
                  --require-hashes --target <that>\\Lib\\site-packages
                  -r <the pins in webdesk.py's docstring, one per line,
                  "name==version --hash=sha256:<hash>">

            (proxy_tools is an sdist: pip builds it, fetching setuptools
            into an isolated build environment.)
--status FILE
            what status() answers the page with, as JSON (default: null,
            i.e. "no app"). A render never asks the running app anything
            unless --live is given, and then status() only.
--timeout   seconds before the child gives up (default 60).

Exit codes: 0 the PNG is written; 2 the pre-check said no (WebView2 or
.NET missing — nothing of pywebview was imported); 3 no index.html in
--dist; 4 the page never became ready; 5 the capture failed; 6 bad
arguments or no usable --python.

Measured on the owner's PC (2026-09-22, runtime 153.0.4234.48, the
spike's web\\dist, warm profile, three calls): the page loaded 1.1-1.24 s
after the child started and was ready (fonts + two frames) 0.10-0.14 s
later; CapturePreviewAsync took 53-87 ms; 2.2-2.5 s wall for the whole
call, hidden desktop and exit included (3.6 s for a page whose six
foreign requests the guards refused).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DESKTOP = "DeskITWebShot"


# ------------------------------------------------------------- the child


def _child(ns) -> int:
    t_start = time.time()
    # silence first, before anything of the app's is imported
    import winsound
    winsound.PlaySound = lambda *a, **k: None
    winsound.Beep = lambda *a, **k: None
    try:
        import tkinter
        tkinter.Misc.bell = lambda *a, **k: None
    except Exception:                        # noqa: BLE001 — no Tk is fine
        pass
    sys.path.insert(0, str(REPO))
    import webdesk

    report: dict = {"out": str(Path(ns.out).resolve())}

    def watchdog():
        # run_hidden waits for this process without a timeout of its own:
        # a WebView2 that never comes up must not hang the caller
        time.sleep(ns.timeout + 30)
        report.update(code=4, error=f"gave up after {ns.timeout + 30:.0f} s")
        print(json.dumps(report, ensure_ascii=False))
        sys.stdout.flush()
        os._exit(4)

    import threading
    threading.Thread(target=watchdog, daemon=True).start()
    canned = None
    if ns.status:
        canned = json.loads(Path(ns.status).read_text("utf-8"))

    class ShotApi(webdesk.Api):
        """status() is canned unless --live; send() is refused, always."""

        def send(self, verb, args=None):
            return {"ok": False, "error": "a render sends nothing"}

        def status(self):
            return super().status() if ns.live else canned

    code = {"value": 4}

    def on_ready(desk):
        report["loaded_ms"] = round((time.time() - t_start) * 1000)
        if not desk.wait_ready(ns.timeout):
            report["error"] = "the page never became ready"
            return
        report["ready_ms"] = round((time.time() - t_start) * 1000)
        try:
            report["capture"] = desk.capture(ns.out)
            code["value"] = 0
        except Exception as e:               # noqa: BLE001
            report["error"] = f"capture: {e}"
            code["value"] = 5
        report["blocked"] = list(desk.blocked)
        report["dropped"] = list(desk.dropped)
        report["errors"] = list(desk.errors)

    storage = Path(tempfile.gettempdir()) / "deskit-web-shot" / "profile"
    run_code = webdesk.run(dist=ns.dist, route=ns.route or "", width=ns.width,
                           height=ns.height, storage=storage,
                           api=ShotApi(allow={"status"}), on_ready=on_ready,
                           x=0, y=0)
    if run_code:
        code["value"] = run_code
        report["error"] = {2: "pre-check said no: " + webdesk.precheck().why,
                           3: f"no index.html in {ns.dist}"}.get(run_code, f"run() said {run_code}")
    report["code"] = code["value"]
    report["total_ms"] = round((time.time() - t_start) * 1000)
    print(json.dumps(report, ensure_ascii=False))
    sys.stdout.flush()
    return code["value"]


# ------------------------------------------------------------ the parent


def _parent(ns, argv) -> int:
    python = ns.python or os.environ.get("DESKIT_WEB_PYTHON", "")
    if not python or not Path(python).is_file():
        print("web_shot: no interpreter with the web desk's packages — pass "
              "--python or set DESKIT_WEB_PYTHON (see this file's docstring)",
              file=sys.stderr)
        return 6
    dist = Path(ns.dist).resolve()
    if not (dist / "index.html").is_file():
        print(f"web_shot: no index.html in {dist}", file=sys.stderr)
        return 3
    sys.path.insert(0, str(REPO))
    import tests_quiet
    log = Path(tempfile.mkdtemp(prefix="web-shot-")) / "child.txt"
    child = [f'"{python}"', f'"{Path(__file__).resolve()}"', "--child",
             "--dist", f'"{dist}"', "--out", f'"{Path(ns.out).resolve()}"',
             "--width", str(ns.width), "--height", str(ns.height),
             "--timeout", str(ns.timeout)]
    if ns.route:
        child += ["--route", ns.route]
    if ns.status:
        child += ["--status", f'"{Path(ns.status).resolve()}"']
    if ns.live:
        child.append("--live")
    t0 = time.perf_counter()
    code = tests_quiet.run_hidden(" ".join(child) + f' > "{log}" 2>&1', REPO,
                                  desktop=DESKTOP)
    wall = time.perf_counter() - t0
    text = log.read_text("utf-8", errors="replace") if log.exists() else ""
    try:
        log.unlink()
        log.parent.rmdir()
    except OSError:
        pass
    line = next((ln for ln in reversed(text.splitlines()) if ln.startswith("{")), "")
    if line:
        report = json.loads(line)
        report["wall_s"] = round(wall, 2)
        print(json.dumps(report, ensure_ascii=False))
    else:
        print(text[-2000:] or f"web_shot: the child said nothing (exit {code})",
              file=sys.stderr)
    return code


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dist", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--width", type=int, default=1180)
    parser.add_argument("--height", type=int, default=760)
    parser.add_argument("--route", default="")
    parser.add_argument("--python")
    parser.add_argument("--status")
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--child", action="store_true", help=argparse.SUPPRESS)
    ns = parser.parse_args(argv)
    if ns.width < 200 or ns.height < 100:
        print("web_shot: the window is at least 200 x 100", file=sys.stderr)
        return 6
    return _child(ns) if ns.child else _parent(ns, argv)


if __name__ == "__main__":
    sys.exit(main())
