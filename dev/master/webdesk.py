"""The desk as a web page: web/dist inside WebView2, in a WinForms window
pywebview owns, talking to the running app through control.py's pipe.

THE SPIKE (2026-09-22). This module is the proof that the React desk can
run the way a release runs it — from the embeddable python\\ of the
installer, with the five packages below in its site-packages — and it
is written so that proof carries over: nothing of pywebview is imported
at the top (the venv the product suite runs in does not have it, and
test_product_suite_imports_no_dev_modules imports every module), and
every decision the preflight named is taken here, in code:

* PRE-CHECK BEFORE IMPORT. pywebview decides its engine at the import of
  webview.platforms.winforms, and when WebView2 or .NET 4.6.2 is missing
  it falls back to MSHTML *silently* and WRITES
  HKCU\\...\\FEATURE_BROWSER_EMULATION on the way. `precheck()` reads the
  same registry values pywebview reads, with the same keys and a
  threshold at least as strict, and `run()` imports nothing of webview
  unless it said yes. Registry reads only; it never writes.
* NO SERVER, NO file://. A URL that is a path starts pywebview's bottle
  server (a random port, CORS *, no token); file:// breaks Vite's module
  scripts; html= is 2 MB and origin null. The folder is mapped onto a
  virtual host with CoreWebView2.SetVirtualHostNameToFolderMapping —
  `https://deskit.example/` — before the first navigation, and every
  request that is not to that host is answered 403 in WebResourceRequested
  and every navigation that is not to it is cancelled.
* OUR OWN ENVIRONMENT. pywebview builds WebView2's environment through
  CoreWebView2CreationProperties, which cannot turn on custom crash
  reporting — so a renderer crash (a minidump of memory that holds
  transcripts and pasted keys) would go to Microsoft. DeskEdgeChrome
  swallows pywebview's implicit `EnsureCoreWebView2Async(None)` (a
  pythonnet subclass of the WinForms control whose Python-side method
  shadows the CLR one) and calls it again with an environment created
  here: IsCustomCrashReportingEnabled, our user data folder, our
  arguments (SmartScreen off), and a controller that is InPrivate.
* THE BRIDGE IS OURS. pywebview's WebView2 dispatcher checks no origin
  and no token (the token is only for its HTTP server), `getattr`s any
  dotted path the page names (`status.__func__.__globals__.clear` is a
  path) and sends a failing call's traceback back to the page.
  DeskEdgeChrome reads every web message itself: {deskit: 1, id, fn,
  args} from our origin for a name in CALLS is answered with
  PostWebMessageAsJson; a pywebview-shaped message is passed on only
  for a name in CALLS; the rest is dropped. The Api object stays flat —
  three methods, nothing else public. (pywebview's own window.pywebview
  .api still comes up under the page's strict CSP: its `new Function`
  runs inside ExecuteScriptAsync, which the CSP does not govern —
  measured: an inline <script> is refused, eval from ExecuteScript is
  not.)
* NOTHING LEAVES, NOTHING SOUNDS, NOTHING PERSISTS. IsMuted, every
  permission request denied, autofill and password saving off, downloads
  cancelled, new windows dropped, pywebview's ALLOW_FILE_URLS (which adds
  --allow-file-access-from-files) off, WEBVIEW2_* / PYWEBVIEW_* /
  PYTHONNET_* scrubbed from the environment before anything reads them.
  The profile is InPrivate on a folder of its own (paths.WEBVIEW_DIR), and
  pywebview's private_mode is OFF on purpose: with it on, pywebview
  rmtree()s the storage folder at every close.

The packages, pinned and hashed from PyPI's JSON (proxy_tools is an sdist
and is BUILT at install time — pip fetches setuptools into an isolated
build env for it, outside --require-hashes):

    pywebview==6.2.1    9d07275f53894ab4d5e2e0e996227193e7187dec276d9b624dccbce029216b46
    pythonnet==3.1.0    7bdd4de03df3547a48122a3989265c8b31d5be0d19dadffa009eec7df8085e0b  (the win32.win_amd64 wheel: it carries netstandard.dll)
    clr_loader==0.3.1   cbad189de20d202a7d621956b0fc38049e13c9bf7ca2923441eff725cd121aa1
    bottle==0.13.4      045684fbd2764eac9cdeb824861d1551d113e8b683d8d26e296898d3dd99a12e
    proxy_tools==0.1.0  ccb3751f529c047e2d8a58440d86b205303cf0fe8146f784d1cbcd94f0a28010  (sdist)

MEASURED 2026-09-22 on the owner's PC — WebView2 153.0.4234.48, the
embeddable 3.11.9 above, a hidden CreateDesktopW desktop, muted, the
spike's page (web\\dist), status() over the pipe of the owner's LIVE app:

* `import clr` loads .NET Framework 4.8.9345.0 (netfx) in 230-440 ms;
  `import webview` 52-139 ms; pywebview's WinForms half another ~150 ms.
  The same from a folder named in Hebrew, page and profile included.
* Process start to first contentful paint: 2083 ms the first time on
  this PC (cold disk), 1232-1355 ms after that (fresh or warm profile).
  WebView2's browser process costs 285-345 ms of it (environment to
  CoreWebView2 ready); navigation to first paint 190-230 ms.
* The bridge: `ping` 0.6 ms median over 50 calls; `status` 1.8-3.7 ms
  (the pipe alone 1.1-2.1 ms from Python). Route switch Home <-> a view
  of 120 rows: 3.5-16 ms to the frame after it is on screen.
* Memory: this python 113 MB working set / 69 MB private; six
  msedgewebview2 processes beside it; 423-468 MB working set and
  227-253 MB private for the whole tree.
* CapturePreviewAsync: 37-87 ms, real pixels (0 % white) on the hidden
  desktop; PrintWindow(PW_RENDERFULLCONTENT) gives real pixels too.
* No listening socket, TCP or UDP, in any process of the tree; with
  BASE_ARGS the netlog has no external host and no socket (see there).
* IsCustomCrashReportingEnabled=True becomes the browser's
  `--edge-webview-disable-crash-reporting=1`, and the Crashpad
  database's settings.dat carries uploads-enabled 0 (1 without it).

    python webdesk.py [--route said] [--dist web\\dist]   # opens the desk (status only)

The render tool for designers is dev\\web_shot.py.
"""
from __future__ import annotations

import dataclasses
import json
import logging
import os
import platform
import sys
import threading
import time
import winreg
from pathlib import Path
from typing import Any, Callable

# The installed interpreter runs under python311._pth, which does not put
# a script's own folder on sys.path (see main.py): the guard every script
# started by path carries, before its first import of ours.
APP_DIR = Path(__file__).resolve().parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

import paths  # noqa: E402

log = logging.getLogger("app")

#: The virtual host web/dist is served from. `.example` is reserved
#: (RFC 2606) and is what Microsoft's own samples use for this mapping:
#: no name the page could ever mean on the real network.
HOST = "deskit.example"
ORIGIN = f"https://{HOST}"
START = f"{ORIGIN}/index.html"

#: What the page may call, over either road. Nothing else is dispatched.
#: An Api object may carry its own allowlist as a CALLS attribute — the
#: master app (dev\master\api.py) has six names of its own and none of
#: these — and then that list is the one the dispatcher checks. A page
#: can never widen it: `api` comes from the process that opened the
#: window, never from the page.
CALLS = ("send", "status", "ping")


def _calls(api) -> tuple:
    names = getattr(api, "CALLS", None) if api is not None else None
    return tuple(names) if names else CALLS

#: LAMPLIGHT's ground (skin/palette.BG): the colour WebView2 paints before
#: the page does, so the first frame is not white.
BACKGROUND = "#14110c"

#: The same registry values pywebview's winforms._is_chromium() reads.
WEBVIEW2_RUNTIME = "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
#: pywebview's floor, compared properly (pywebview compares only the
#: first number, so anything it rejects this rejects too).
RUNTIME_MIN = (86, 0, 622, 0)
#: .NET Framework 4.6.2's Release number — pywebview's floor.
NETFX_MIN = 394802

#: Environment variables that change what WebView2, pywebview or
#: pythonnet do behind this module's back: WEBVIEW2_ADDITIONAL_BROWSER_
#: ARGUMENTS appends flags, WEBVIEW2_BROWSER_EXECUTABLE_FOLDER swaps the
#: runtime, PYWEBVIEW_GUI can force MSHTML, PYTHONNET_RUNTIME the CLR.
SCRUB_PREFIXES = ("WEBVIEW2_", "PYWEBVIEW_", "PYTHONNET_")

#: The Chromium flags every desk starts with. The feature lists are
#: merged by WebView2, so pywebview's ElasticOverscroll is kept here.
#:
#: WebView2 talks to Microsoft on its own, and a netlog shows it
#: (2026-09-22, runtime 153.0.4234.48, a fresh profile, 60 s idle): a GET
#: to config.edge.skype.com/config/v1/Edge/153… carrying a client id, the
#: OS build and the install date, 45 ms after start and again at 1.2 s
#: (Edge's experimentation service), a POST to edge.microsoft.com/
#: componentupdater at 60 s, DNS queries for `wpad` (proxy discovery) at
#: start, at 8 s and at 60 s, and a DNS preconnect for any host a page
#: navigates towards — our own virtual host included, and a foreign one
#: before NavigationStarting has cancelled the navigation. Measured, flag by
#: flag, on the same PC:
#:   --disable-background-networking --disable-component-update
#:       the two Microsoft requests are never made (0 URL requests);
#:   --host-resolver-rules="MAP * ~NOTFOUND" --no-proxy-server
#:       every name fails inside the process — 0 DNS queries, 0 TCP
#:       connects, no wpad — whatever asks. The virtual host needs no DNS.
#: All four: a netlog with no external host and no socket. What is left
#: is a UDP connect() to [2603:1020:201:10::10f]:443 that fails at once
#: (Chromium's IPv6-route probe: connect() on UDP sends no packet), and
#: WebView2's "required diagnostic data", which goes through Windows'
#: own telemetry and not the network service — not measurable here.
BASE_ARGS = (
    "--disable-features=ElasticOverscroll,msSmartScreenProtection",
    "--disable-background-networking",
    "--disable-component-update",
    '--host-resolver-rules="MAP * ~NOTFOUND"',
    "--no-proxy-server",
)

BLANK = "<!doctype html><meta charset=utf-8><title>DeskIT</title>"


# ------------------------------------------------------------ pre-check


@dataclasses.dataclass(frozen=True)
class Precheck:
    ok: bool
    webview2: str          # the runtime's pv, "" when none was found
    where: str             # which key held it
    netfx_release: int     # .NET Framework 4.x Release, 0 when absent
    why: str               # "" when ok


def _read(root, sub: str, name: str):
    try:
        with winreg.OpenKey(root, sub, 0, winreg.KEY_READ) as key:
            return winreg.QueryValueEx(key, name)[0]
    except OSError:
        return None


def _version(text) -> tuple[int, ...]:
    try:
        return tuple(int(p) for p in str(text).strip().split("."))
    except ValueError:
        return ()


def precheck() -> Precheck:
    """Whether pywebview would pick WebView2 here — decided from the
    registry alone, before anything of webview is imported. Never
    writes, never raises."""
    release = _read(winreg.HKEY_LOCAL_MACHINE,
                    r"SOFTWARE\Microsoft\NET Framework Setup\NDP\v4\Full",
                    "Release")
    release = release if isinstance(release, int) else 0
    # pywebview reads HKLM through WOW6432Node on anything but x86, and
    # HKCU without it; reading any other key could say yes where
    # pywebview says no — and then it falls back to MSHTML.
    wow = "" if platform.machine().lower() == "x86" else "WOW6432Node\\"
    keys = (
        ("HKCU", winreg.HKEY_CURRENT_USER,
         "SOFTWARE\\Microsoft\\EdgeUpdate\\Clients\\" + WEBVIEW2_RUNTIME),
        ("HKLM", winreg.HKEY_LOCAL_MACHINE,
         "SOFTWARE\\" + wow + "Microsoft\\EdgeUpdate\\Clients\\" + WEBVIEW2_RUNTIME),
    )
    found, where = "", ""
    for label, root, sub in keys:
        pv = _read(root, sub, "pv")
        if pv and _version(pv) >= RUNTIME_MIN:
            found, where = str(pv), f"{label}\\{sub}"
            break
    if release < NETFX_MIN:
        why = f".NET Framework 4.6.2 or later is missing (Release {release})"
    elif not found:
        why = "the WebView2 Runtime is not installed"
    else:
        why = ""
    return Precheck(ok=not why, webview2=found, where=where,
                    netfx_release=release, why=why)


def scrub_env(environ=None) -> list[str]:
    """Remove every variable in SCRUB_PREFIXES; the NAMES removed, never a
    value. Then pin the one pythonnet needs: the .NET Framework."""
    environ = os.environ if environ is None else environ
    gone = sorted(k for k in list(environ)
                  if k.upper().startswith(SCRUB_PREFIXES))
    for k in gone:
        del environ[k]
    environ["PYTHONNET_RUNTIME"] = "netfx"
    return gone


def browser_args(extra=()) -> str:
    return " ".join((*BASE_ARGS, *extra))


# ------------------------------------------------------------------ API


class Api:
    """What the page may ask of the app — flat, three methods, nothing
    else public. `allow` narrows `send` to a set of verbs (the spike and
    the render tool pass {"status"}: the pipe from a checkout is the
    owner's LIVE app)."""

    def __init__(self, allow=None, timeout_ms: int = 2000) -> None:
        self._allow = None if allow is None else frozenset(allow)
        self._timeout_ms = timeout_ms

    def send(self, verb: str, args: dict | None = None):
        verb = str(verb)
        if self._allow is not None and verb not in self._allow:
            return {"ok": False, "error": f"{verb!r} is not allowed from this desk"}
        import control
        reply = control.send(verb, timeout_ms=self._timeout_ms, **dict(args or {}))
        return _without_phone(reply) if verb == "status" else reply

    def status(self):
        import control
        return _without_phone(control.send("status", timeout_ms=self._timeout_ms))

    def ping(self):
        return {"ok": True}


def _without_phone(reply):
    """status() carries the phone link and its token; the page never
    needs them and a page is not where a secret goes."""
    if isinstance(reply, dict):
        reply = dict(reply)
        reply.pop("phone", None)
    return reply


# -------------------------------------------------------------- the desk


@dataclasses.dataclass
class Options:
    dist: Path
    route: str = ""
    args: str = ""
    crash_local: bool = True
    inprivate: bool = True
    api: Any = None
    #: the .ico the window wears in its title bar, its taskbar button and
    #: Alt-Tab. Without it the window wears pythonw.exe's own — the Python
    #: snake, which is what he saw in the title bar (2026-09-24).
    icon: Path | None = None


class Desk:
    """The running desk, as the code that opened it sees it: the stamps
    of each step, what the guards refused, and three things it can do
    from any thread — run a script, photograph the page, close."""

    def __init__(self, window) -> None:
        self.window = window
        self.edge = None                    # DeskEdgeChrome, set in its __init__
        self.stamps: dict[str, float] = {}  # time.time() of each milestone
        self.blocked: list[str] = []        # what the guards refused (URIs)
        self.dropped: list[str] = []        # web messages not answered
        self.errors: list[str] = []
        self.loaded = threading.Event()     # our page's NavigationCompleted
        self.settings_applied: dict[str, str] = {}
        #: what the environment and the profile said about themselves,
        #: read on the UI thread (a CoreWebView2 object read from any
        #: other thread raises "Unable to cast to ICoreWebView2...")
        self.env_info: dict[str, str] = {}

    def stamp(self, name: str) -> None:
        self.stamps.setdefault(name, time.time())

    # -- from any thread

    def _on_ui(self, fn: Callable[[], None]) -> None:
        from System import Action
        self.edge.form.BeginInvoke(Action(fn))

    def js(self, script: str, timeout: float = 10.0):
        """ExecuteScriptAsync on the UI thread; the JSON result, decoded.
        Our own road, so it does not depend on pywebview's injection."""
        from System import Action, String
        from System.Threading.Tasks import Task
        done, box = threading.Event(), {}

        def finished(task):
            try:
                box["r"] = None if task.IsFaulted else str(task.Result)
                if task.IsFaulted:
                    box["e"] = str(task.Exception)
            finally:
                done.set()

        def start():
            try:
                t = self.edge.webview.CoreWebView2.ExecuteScriptAsync(script)
                t.ContinueWith(Action[Task[String]](finished))
            except Exception as e:           # noqa: BLE001
                box["e"] = repr(e)
                done.set()

        self._on_ui(start)
        if not done.wait(timeout):
            raise TimeoutError(f"script did not answer in {timeout} s")
        if "e" in box:
            raise RuntimeError(box["e"])
        return json.loads(box["r"]) if box.get("r") not in (None, "") else None

    def capture(self, path, timeout: float = 15.0) -> dict:
        """CoreWebView2.CapturePreviewAsync to a PNG — the documented way
        to photograph a WebView2, which works where PrintWindow may not."""
        from Microsoft.Web.WebView2.Core import CoreWebView2CapturePreviewImageFormat
        from System import Action
        from System.IO import FileAccess, FileMode, FileStream
        from System.Threading.Tasks import Task
        path = str(Path(path).resolve())
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        done, box = threading.Event(), {}

        def finished(task):
            try:
                box["stream"].Dispose()
                if task.IsFaulted:
                    box["e"] = str(task.Exception)
            finally:
                done.set()

        def start():
            try:
                box["stream"] = FileStream(path, FileMode.Create, FileAccess.Write)
                t = self.edge.webview.CoreWebView2.CapturePreviewAsync(
                    CoreWebView2CapturePreviewImageFormat.Png, box["stream"])
                t.ContinueWith(Action[Task](finished))
            except Exception as e:           # noqa: BLE001
                box["e"] = repr(e)
                done.set()

        t0 = time.perf_counter()
        self._on_ui(start)
        if not done.wait(timeout):
            raise TimeoutError(f"capture did not finish in {timeout} s")
        if "e" in box:
            raise RuntimeError(box["e"])
        return {"path": path, "bytes": os.path.getsize(path),
                "ms": round((time.perf_counter() - t0) * 1000, 1)}

    def hwnd(self) -> int:
        return int(self.edge.form.Handle.ToInt64())

    def navigate(self, route: str) -> None:
        url = START + (f"#/{route}" if route else "")
        self.loaded.clear()
        self._on_ui(lambda: self.edge.webview.CoreWebView2.Navigate(url))

    def close(self) -> None:
        self.window.destroy()

    def wait_ready(self, timeout: float = 30.0) -> bool:
        """Our page loaded, its fonts settled, and two frames painted
        after that — the moment a photograph is of the finished page."""
        deadline = time.monotonic() + timeout
        if not self.loaded.wait(timeout):
            return False
        self.js("window.__shot = 0; document.fonts.ready.then(() => "
                "requestAnimationFrame(() => requestAnimationFrame(() => "
                "{ window.__shot = 1; })));")
        while time.monotonic() < deadline:
            if self.js("window.__shot === 1") is True:
                return True
            time.sleep(0.03)
        return False


def _install(desks: dict):
    """Import pywebview's WinForms half (the pre-check has said yes) and
    put DeskEdgeChrome where BrowserForm will build it. Returns the
    winforms module."""
    import clr  # noqa: F401 — pythonnet, netfx (PYTHONNET_RUNTIME above)
    from webview.platforms import edgechromium, winforms
    if winforms.renderer != "edgechromium":
        raise RuntimeError(f"pywebview chose {winforms.renderer!r} after the "
                           f"pre-check said WebView2")

    from Microsoft.Web.WebView2.Core import (
        CoreWebView2Environment,
        CoreWebView2EnvironmentOptions,
        CoreWebView2HostResourceAccessKind,
        CoreWebView2PermissionState,
        CoreWebView2WebResourceContext,
    )
    from Microsoft.Web.WebView2.WinForms import WebView2
    from System import Action
    from System.Threading.Tasks import Task

    class DeferredWebView2(WebView2):
        """The WinForms control, with pywebview's implicit initialisation
        (EnsureCoreWebView2Async(None), the last line of EdgeChrome.
        __init__) swallowed: a Python-side method shadows the CLR one for
        Python callers, and DeskEdgeChrome calls the real one with its
        own environment."""

        def EnsureCoreWebView2Async(self, environment=None, controllerOptions=None):
            if environment is None:
                return None
            return WebView2.EnsureCoreWebView2Async(self, environment, controllerOptions)

    base = edgechromium.EdgeChrome

    class DeskEdgeChrome(base):
        def __init__(self, form, window, cache_dir):
            desk: Desk = desks[window.uid]
            desk.stamp("form_ready")
            desk.edge = self
            self._desk = desk
            self._opts: Options = window._deskit_options
            self._env = None
            self._navigated = False
            real = edgechromium.WebView2
            edgechromium.WebView2 = DeferredWebView2
            try:
                super().__init__(form, window, cache_dir)
            finally:
                edgechromium.WebView2 = real
            desk.stamp("control_built")
            if self._opts.icon:
                try:                         # the window's own face, not pythonw's
                    from System.Drawing import Icon as _Icon
                    form.Icon = _Icon(str(self._opts.icon))
                except Exception as e:       # noqa: BLE001 — an icon is not worth a window
                    desk.errors.append(f"icon: {e!r}")
            options = CoreWebView2EnvironmentOptions()
            options.AdditionalBrowserArguments = self._opts.args
            try:
                options.IsCustomCrashReportingEnabled = bool(self._opts.crash_local)
            except Exception as e:           # noqa: BLE001 — an old runtime
                desk.errors.append(f"IsCustomCrashReportingEnabled: {e!r}")
            task = CoreWebView2Environment.CreateAsync(None, cache_dir, options)
            task.ContinueWith(Action[Task[CoreWebView2Environment]](self._env_created),
                              self.syncContextTaskScheduler)

        def _env_created(self, task):
            desk = self._desk
            if task.IsFaulted:
                desk.errors.append(f"environment: {task.Exception}")
                return
            desk.stamp("environment")
            self._env = task.Result
            for name in ("BrowserVersionString", "UserDataFolder", "FailureReportFolderPath"):
                try:
                    desk.env_info[name] = str(getattr(self._env, name))
                except Exception as e:       # noqa: BLE001
                    desk.env_info[name] = f"unavailable: {type(e).__name__}"
            ctrl = self._env.CreateCoreWebView2ControllerOptions()
            ctrl.IsInPrivateModeEnabled = bool(self._opts.inprivate)
            self.webview.EnsureCoreWebView2Async(self._env, ctrl)

        # -- ready: map, lock down, then let pywebview navigate to us

        def on_webview_ready(self, sender, args):
            desk = self._desk
            if not args.IsSuccess:
                desk.errors.append(f"init: {args.InitializationException}")
                return super().on_webview_ready(sender, args)
            desk.stamp("core_ready")
            core = sender.CoreWebView2
            for label, read in (("InPrivate", lambda: core.Profile.IsInPrivateModeEnabled),
                                ("BrowserProcessId", lambda: core.BrowserProcessId)):
                try:
                    desk.env_info[label] = str(read())
                except Exception as e:       # noqa: BLE001
                    desk.env_info[label] = f"unavailable: {type(e).__name__}"
            core.SetVirtualHostNameToFolderMapping(
                HOST, str(self._opts.dist), CoreWebView2HostResourceAccessKind.Deny)
            s = core.Settings
            for name, value in (("IsReputationCheckingRequired", False),
                                ("IsGeneralAutofillEnabled", False),
                                ("IsPasswordAutosaveEnabled", False),
                                ("IsPinchZoomEnabled", False)):
                try:
                    setattr(s, name, value)
                    desk.settings_applied[name] = str(getattr(s, name))
                except Exception as e:       # noqa: BLE001
                    desk.errors.append(f"{name}: {e!r}")
            try:
                core.IsMuted = True
                desk.settings_applied["IsMuted"] = str(core.IsMuted)
            except Exception as e:           # noqa: BLE001
                desk.errors.append(f"IsMuted: {e!r}")
            core.NavigationStarting += self._guard_navigation
            core.FrameNavigationStarting += self._guard_frame
            core.AddWebResourceRequestedFilter("*", CoreWebView2WebResourceContext.All)
            core.WebResourceRequested += self._guard_request
            core.PermissionRequested += self._deny_permission
            core.NavigationCompleted += self._completed
            route = self._opts.route
            self.pywebview_window.real_url = START + (f"#/{route}" if route else "")
            super().on_webview_ready(sender, args)

        def _ours(self, uri: str) -> bool:
            return uri == ORIGIN or uri.startswith(ORIGIN + "/")

        def _guard_navigation(self, sender, args):
            uri = str(args.Uri)
            if self._ours(uri):
                self._desk.stamp("navigation_starting")
                return
            args.Cancel = True
            self._desk.blocked.append(f"navigation {uri[:120]}")

        def _guard_frame(self, sender, args):
            uri = str(args.Uri)
            if not self._ours(uri):
                args.Cancel = True
                self._desk.blocked.append(f"frame {uri[:120]}")

        def _guard_request(self, sender, args):
            uri = str(args.Request.Uri)
            if self._ours(uri):
                return
            args.Response = self._env.CreateWebResourceResponse(None, 403, "Blocked", "")
            self._desk.blocked.append(f"request {uri[:120]}")

        def _deny_permission(self, sender, args):
            args.State = CoreWebView2PermissionState.Deny
            self._desk.blocked.append(f"permission {args.PermissionKind}")

        def _completed(self, sender, args):
            if self._ours(str(sender.Source)):
                self._desk.stamp("navigation_completed")
                self._desk.loaded.set()

        # -- what pywebview would otherwise do on its own

        def on_new_window_request(self, sender, args):
            args.set_Handled(True)
            self._desk.blocked.append(f"new window {str(args.get_Uri())[:120]}")

        def on_download_starting(self, sender, args):
            args.Cancel = True

        def clear_user_data(self):
            """pywebview rmtree()s the storage folder here when private
            mode is on. The folder is a cache and InPrivate already keeps
            nothing; nothing in this app deletes a folder on close."""
            return

        # -- the bridge

        def on_script_notify(self, sender, args):
            source = str(args.Source)
            if not self._ours(source):
                self._desk.dropped.append(f"foreign origin {source[:80]}")
                return
            try:
                message = json.loads(args.WebMessageAsJson)
            except Exception:                # noqa: BLE001
                self._desk.dropped.append("not json")
                return
            if isinstance(message, dict) and message.get("deskit") == 1:
                self._answer(message)
                return
            if (isinstance(message, list) and len(message) == 3
                    and message[0] in _calls(self._opts.api)):
                return super().on_script_notify(sender, args)
            name = message[0] if isinstance(message, list) and message else type(message).__name__
            self._desk.dropped.append(f"pywebview message {str(name)[:60]}")

        def _answer(self, message: dict) -> None:
            mid, fn = message.get("id"), message.get("fn")
            call_args = message.get("args") or {}
            api = self._opts.api

            def work():
                if (api is None or fn not in _calls(api)
                        or not isinstance(call_args, dict)):
                    reply = {"deskit": 1, "id": mid, "ok": False, "error": f"{fn!r} is not a desk call"}
                else:
                    try:
                        value = getattr(api, fn)(**call_args)
                        reply = {"deskit": 1, "id": mid, "ok": True, "value": value}
                    except Exception as e:   # noqa: BLE001 — the page gets words, not a traceback
                        reply = {"deskit": 1, "id": mid, "ok": False, "error": type(e).__name__}
                text = json.dumps(reply, ensure_ascii=False, default=str)
                self._desk._on_ui(lambda: self.webview.CoreWebView2.PostWebMessageAsJson(text))

            threading.Thread(target=work, daemon=True, name="desk-call").start()

    edgechromium.EdgeChrome = DeskEdgeChrome
    winforms.Chromium.EdgeChrome = DeskEdgeChrome
    return winforms


def run(*, dist=None, route: str = "", width: int = 1180, height: int = 760,
        title: str = "DeskIT", storage=None, api=None, extra_args=(),
        on_ready: Callable[[Desk], None] | None = None, crash_local: bool = True,
        inprivate: bool = True, x: int | None = None, y: int | None = None,
        icon=None) -> int:
    """Open the desk and block until it closes. 0 when it ran; 2 when the
    pre-check said no (nothing of webview was imported); 3 when it could
    not start. `on_ready(desk)` runs on a thread of its own once the page
    has loaded; the desk closes when it returns."""
    desk = Desk(None)
    run.last = desk                          # the caller's handle once start() returns
    pre = precheck()
    desk.stamp("precheck")
    if not pre.ok:
        log.info("web desk: %s", pre.why)
        return 2
    dist = Path(dist or paths.WEB_DIST).resolve()
    if not (dist / "index.html").is_file():
        log.info("web desk: no index.html in %s", dist)
        return 3
    storage = Path(storage or paths.WEBVIEW_DIR).resolve()
    storage.mkdir(parents=True, exist_ok=True)
    scrub_env()
    import webview
    desk.stamp("webview_imported")
    webview.settings["ALLOW_FILE_URLS"] = False
    webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = False
    webview.settings["ALLOW_DOWNLOADS"] = False
    webview.settings["SHOW_DEFAULT_MENUS"] = False
    desks: dict[str, Desk] = {}
    _install(desks)
    desk.stamp("winforms_imported")
    api = api if api is not None else Api()
    window = webview.create_window(title, html=BLANK, js_api=api, width=width,
                                   height=height, x=x, y=y,
                                   background_color=BACKGROUND, text_select=False)
    window._deskit_options = Options(dist=dist, route=route, args=browser_args(extra_args),
                                     crash_local=crash_local, inprivate=inprivate, api=api,
                                     icon=Path(icon) if icon else None)
    desk.window = window
    desks[window.uid] = desk
    desk.stamp("start")

    def worker():
        try:
            if not desk.loaded.wait(60):
                desk.errors.append("the page never finished loading")
            elif on_ready is not None:
                on_ready(desk)
        except Exception as e:               # noqa: BLE001
            desk.errors.append(f"on_ready: {type(e).__name__}: {e}")
        finally:
            if on_ready is not None:
                try:
                    desk.close()
                except Exception:            # noqa: BLE001
                    pass

    webview.start(func=worker, private_mode=False, storage_path=str(storage),
                  gui="edgechromium", debug=False)
    return 0


run.last = None


def main(argv=None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description="Open the web desk (status only).")
    parser.add_argument("--dist", help="the built pages (default web\\dist)")
    parser.add_argument("--route", default="", help="open on #/<route>")
    parser.add_argument("--storage", help="WebView2's folder (default paths.WEBVIEW_DIR)")
    ns = parser.parse_args(argv)
    pre = precheck()
    print(f"pre-check: {'yes' if pre.ok else 'no'} — WebView2 {pre.webview2 or 'absent'}, "
          f".NET Release {pre.netfx_release}{'; ' + pre.why if pre.why else ''}")
    return run(dist=ns.dist, route=ns.route, storage=ns.storage,
               api=Api(allow={"status"}))


if __name__ == "__main__":
    sys.exit(main())
