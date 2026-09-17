"""How Claude Code says it is done — and the command-line door for anything else.

Three jobs, one stdlib-only script, exit code ALWAYS 0 and nothing on
stdout, because a Claude Code hook that exits non-zero or prints is a
hook that blocks or edits the turn it was told about:

    notify_hook.py                       hook mode: one JSON event on stdin
    notify_hook.py --title T [--body B] [--source S] [--kind K] ...
    notify_hook.py --install-hook [--settings PATH]

Hook mode maps a `Stop` event to "Claude finished" (kind done) and a
`Notification` for idle_prompt / permission_prompt / elicitation_dialog /
agent_needs_input to "Claude is waiting" (kind input); everything else,
SubagentStop included, is ignored — a subagent finishing is not the
owner's business, and a Stop with `stop_hook_active` set is a turn that
is already being continued by a hook. The event is posted to the
running app's `/notify` route on 127.0.0.1:[server] port with the
phone bearer token from the secret store (secretstore.py, a DPAPI blob
the app writes at start). If the app is not running, the post fails
and the script exits 0 in silence — a hook must never make Claude wait
on a card.

Every payload also names the window the notification CAME FROM (`hwnd`
and `app`), because a click on the card now raises it — see
`owner_window` below for how that is resolved and why — and the SESSION
it came from (`link`), because that window holds every session at once
and raising it lands wherever the app happened to be; see
`session_link` for the one door into the desktop app that is not
bolted.

`--install-hook` writes the two entries into ~/.claude/settings.json,
replacing any earlier entry that names this script and leaving every
other key and every foreign hook alone, so it can be run again after a
move or a python <-> pythonw change. The default interpreter is the
venv's pythonw.exe: Claude Code runs hooks through a shell, and a
console-subsystem python would flash a window on every turn.
"""
from __future__ import annotations

import argparse
import copy
import ctypes
import json
import os
import re
import sys
import tomllib
import urllib.error
import urllib.request
from pathlib import Path

import paths

HERE = Path(__file__).resolve().parent
DEFAULT_PORT = 8756
DEFAULT_SETTINGS = Path.home() / ".claude" / "settings.json"
TOKEN_FILE = paths.PHONE_TOKEN     # the pre-2026-09-17 plaintext file
BODY_MAX = 300
SOURCE = "claude-code"

# notification_type -> title. Everything not here is not for the owner.
INPUT_TITLES = {
    "idle_prompt": "Claude is waiting for you",
    "permission_prompt": "Claude needs a permission",
    "elicitation_dialog": "Claude needs you",
    "agent_needs_input": "Claude needs you",
}


def _collapse(value) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())


# ---------------------------------------------------------------------------
# whose window is this? — the parent-process walk
# ---------------------------------------------------------------------------
# WHY THE PARENT CHAIN AND NOT A SEARCH FOR A WINDOW CALLED "Claude".
# A click on the notification card now raises the window that sent it, so
# the sender has to NAME that window. Matching on a title would be a
# guess: a title is the app's to change without telling anybody, several
# windows can carry the same one, and with two projects open the guess is
# wrong exactly when it matters. This script does not have to guess,
# because it is a CHILD of the process that owns the window — Claude Code
# runs its hooks — so walking up the parent chain and asking each ancestor
# what visible top-level windows it owns is STRUCTURAL: the answer is the
# process that actually sent the notification, whatever it calls itself.
#
# Measured 2026-09-04, from a process spawned inside Claude Code (a
# stdlib ctypes probe: CreateToolhelp32Snapshot for the chain, EnumWindows
# + GetWindowThreadProcessId for each ancestor's windows):
#
#      pid  exe            windows
#   522112  python.exe     []
#   529080  python.exe     []
#   167784  bash.exe       []
#   524732  bash.exe       []
#   495256  bash.exe       []
#   231024  claude.exe     []
#  1613168  claude.exe     [(43779834, 'Claude')]
#
# Six ancestors owning nothing and the seventh owning exactly one window.
# Hence the depth cap: the chain is long, and a walk that never ends is a
# hook that hangs a turn.

TH32CS_SNAPPROCESS = 0x00000002
WALK_DEPTH = 12


class _PROCESSENTRY32(ctypes.Structure):
    """kernel32's process record. Only the two pids are read, but every
    field has to be declared: dwSize is validated against the whole."""

    _fields_ = [("dwSize", ctypes.c_ulong),
                ("cntUsage", ctypes.c_ulong),
                ("th32ProcessID", ctypes.c_ulong),
                ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
                ("th32ModuleID", ctypes.c_ulong),
                ("cntThreads", ctypes.c_ulong),
                ("th32ParentProcessID", ctypes.c_ulong),
                ("pcPriClassBase", ctypes.c_long),
                ("dwFlags", ctypes.c_ulong),
                ("szExeFile", ctypes.c_char * 260)]


def _parents() -> dict:
    """pid -> parent pid, from one snapshot of every process. {} on any
    failure. The handles get restypes because a 64-bit HANDLE does not
    fit the c_int ctypes assumes — and they are set on a PRIVATE
    ctypes.WinDLL, never on ctypes.windll, which is process-global and
    shared with every other module here (AGENTS.md)."""
    out: dict = {}
    try:
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateToolhelp32Snapshot.argtypes = [ctypes.c_ulong,
                                                 ctypes.c_ulong]
        k32.CreateToolhelp32Snapshot.restype = ctypes.c_void_p
        k32.Process32First.argtypes = [ctypes.c_void_p,
                                       ctypes.POINTER(_PROCESSENTRY32)]
        k32.Process32Next.argtypes = [ctypes.c_void_p,
                                      ctypes.POINTER(_PROCESSENTRY32)]
        k32.CloseHandle.argtypes = [ctypes.c_void_p]
        snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
        if not snap:
            return out
        try:
            entry = _PROCESSENTRY32()
            entry.dwSize = ctypes.sizeof(_PROCESSENTRY32)
            if k32.Process32First(snap, ctypes.byref(entry)):
                while True:
                    out[int(entry.th32ProcessID)] = \
                        int(entry.th32ParentProcessID)
                    if not k32.Process32Next(snap, ctypes.byref(entry)):
                        break
        finally:
            k32.CloseHandle(snap)
    except Exception:                     # noqa: BLE001
        return {}
    return out


def _windows_of(u32, pid: int) -> list:
    """Every visible, titled, top-level window owned by `pid`. EnumWindows
    walks only top-level windows, so nothing here has to filter children;
    a window with a blank caption is skipped because a card cannot name
    it and the owner would not recognise it."""
    found: list = []
    proto = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_void_p,
                               ctypes.c_void_p)
    u32.EnumWindows.argtypes = [proto, ctypes.c_void_p]
    u32.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p,
                                             ctypes.POINTER(ctypes.c_ulong)]
    u32.IsWindowVisible.argtypes = [ctypes.c_void_p]
    u32.GetWindowTextLengthW.argtypes = [ctypes.c_void_p]
    u32.GetWindowTextW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p,
                                   ctypes.c_int]

    @proto
    def collect(hwnd, _param):
        try:
            owner = ctypes.c_ulong()
            u32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
            if owner.value == pid and u32.IsWindowVisible(hwnd):
                n = int(u32.GetWindowTextLengthW(hwnd))
                buf = ctypes.create_unicode_buffer(n + 1)
                u32.GetWindowTextW(hwnd, buf, n + 1)
                if buf.value.strip():
                    found.append((int(hwnd), buf.value.strip()))
        except Exception:                 # noqa: BLE001
            pass
        return 1

    u32.EnumWindows(collect, None)
    return found


def owner_window(depth: int = WALK_DEPTH) -> tuple[int, str]:
    """(hwnd, title) of the window this notification is coming FROM.

    The first visible, titled, top-level window owned by this process or
    by any of its `depth` nearest ancestors — see the block above for why
    the chain and not the title. (0, "") when nothing in the chain owns a
    window, and (0, "") on ANY error: this script never fails and always
    exits 0, so a machine that answers none of these questions simply
    sends a notification that cannot be clicked open.
    """
    try:
        u32 = ctypes.WinDLL("user32", use_last_error=True)
        parents = _parents()
        pid = os.getpid()
        for _ in range(max(1, int(depth))):
            found = _windows_of(u32, pid)
            if found:
                return found[0]
            parent = parents.get(pid, 0)
            if not parent or parent == pid or parent not in parents:
                break
            pid = parent
    except Exception:                     # noqa: BLE001
        return 0, ""
    return 0, ""


# ---------------------------------------------------------------------------
# which SESSION is this? — the desktop app's own store, and the one door
# into it that is not bolted
# ---------------------------------------------------------------------------
# ONE WINDOW HOLDS EVERY SESSION, so raising it is only half an answer.
# Every notification this hook has ever sent carries the same handle
# (43779834): the desktop app keeps all of its Claude Code sessions in a
# single window and switches between them INSIDE it, so a click that
# raises the window lands wherever the app happened to be — the owner's
# report on 2026-09-04, and not something a better window search can fix.
#
# The app does have doors for this: `claude://code/<cse_…>` and
# `claude://code/continue?session=local_…`. Both were fired at it that
# day and both were refused, by a feature flag on its side, in its own
# log (%LOCALAPPDATA%\Claude\logs\main.log):
#
#   16:44:49 claudeURLHandler: code session deep link gated off
#   16:45:48 claudeURLHandler: code entry deep link gated off
#
# `claude://resume?session=<uuid>` is not gated. It exists to ADOPT a CLI
# session the app has never seen, and it looks the id up as
# `local_<uuid>` before importing anything — so handing it the uuid of a
# session the app already owns imports nothing and simply goes there:
#
#   16:54:41 Resume deep link: importing CLI session 6abc45c7-…
#   16:54:41 CLI session 6abc45c7-… already imported as local_6abc45c7-…
#   16:54:41 [CCD] LocalSessions.setFocusedSession: local_6abc45c7-…
#
# THAT UUID IS NOT THE ONE A HOOK IS GIVEN. `session_id` names the CLI
# transcript of the CURRENT episode and a resume starts a new one; the
# app's id was minted when the session was created and never moves. The
# map between them is the app's own store, one JSON per session, which
# names both:
#
#   %APPDATA%\Claude\claude-code-sessions\<account>\<org>\local_<id>.json
#       {"sessionId": "local_6abc45c7-…",
#        "cliSessionId": "add068f2-…",
#        "priorCliSessionIds": ["ec9cf336-…", …], …}
#
# so the walk is: our `session_id`, found as `cliSessionId` or among
# `priorCliSessionIds`, gives `sessionId`, gives the link. Nothing is
# written and nothing is asked of the app. A store that has moved, that
# will not parse, or that has never heard of this session is no link at
# all — and no link is the behaviour this hook had before: raise the
# window and let the owner find the tab.

SESSIONS = Path(os.environ.get("APPDATA", "")) / "Claude" / "claude-code-sessions"
LOCAL = "local_"
STORE_MAX = 40                    # session files opened before giving up
UUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}"
                  r"-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


def session_link(session_id, root=None) -> str:
    """`claude://resume?session=<uuid>` for one CLI session, or "".

    `root` is the store's folder, a parameter only so a test can hand
    over one it built; left None it is the app's own. The files are read
    newest first — a live session's file is written constantly — and the
    id is looked for as text before anything is parsed, because these
    are 400 KB documents and the id is a 36-character needle. A text hit
    is not the answer, though: the id can appear anywhere in the file,
    so the two fields that MEAN it are checked after the parse. The
    comparison is exact, case included — both sides of it are written by
    Claude Code, which mints these ids in one shape.

    "" on anything unexpected. This is a hook: it may not raise, and a
    machine that answers none of these questions simply sends a
    notification that opens no session.
    """
    ident = str(session_id or "").strip()
    if not UUID.match(ident):
        return ""
    try:
        root = Path(root) if root is not None else SESSIONS
        files = sorted(root.glob(f"*/*/{LOCAL}*.json"),
                       key=lambda p: p.stat().st_mtime, reverse=True)
        for path in files[:STORE_MAX]:
            try:
                text = path.read_text("utf-8")
            except OSError:
                continue
            if ident not in text:
                continue
            try:
                data = json.loads(text)
            except ValueError:
                continue
            if not isinstance(data, dict):
                continue
            prior = data.get("priorCliSessionIds")
            prior = prior if isinstance(prior, list) else []
            if data.get("cliSessionId") != ident and ident not in prior:
                continue              # the id was IN the file, but not as
                                      # one of this session's own episodes
            local = str(data.get("sessionId") or "")
            uuid = local[len(LOCAL):] if local.startswith(LOCAL) else ""
            if not UUID.match(uuid):
                continue              # `local_ditto_…` — a cloud session,
                                      # whose id resume will not take
            return f"claude://resume?session={uuid}"
    except Exception:                 # noqa: BLE001
        return ""
    return ""


def payload_from_hook(event: dict, window=None, link=None) -> dict | None:
    """The /notify body for one hook event, or None when it is nobody's
    business (a subagent, a continued turn, an unknown notification).

    `window` is the (hwnd, title) the card will raise; left None it is
    resolved by `owner_window()` — a parameter only so a test can say
    what the answer is instead of taking whatever is on the desktop.
    `link` is the same arrangement for `session_link()`.
    """
    if not isinstance(event, dict):
        return None
    if event.get("stop_hook_active") is True:
        return None
    name = str(event.get("hook_event_name") or "")
    if name == "Stop":
        kind, title = "done", "Claude finished"
    elif name == "Notification":
        title = INPUT_TITLES.get(str(event.get("notification_type") or ""))
        if title is None:
            return None
        kind = "input"
    else:
        return None
    body = (_collapse(event.get("last_assistant_message"))
            or _collapse(event.get("message")) or "")[:BODY_MAX]
    cwd = event.get("cwd")
    project = Path(str(cwd)).name if isinstance(cwd, str) and cwd else ""
    hwnd, app = owner_window() if window is None else window
    session = str(event.get("session_id") or "")
    if link is None:
        link = session_link(session)
    return {"source": SOURCE, "kind": kind, "title": title, "body": body,
            "project": project, "session": session,
            "hwnd": int(hwnd), "app": str(app), "link": str(link or "")}


def server_port() -> int:
    """The port the app answers on: state.json (the port it actually
    bound), else settings.toml, else defaults.toml, else 8756 — the same
    three layers config.py reads, without importing config.py, because a
    hook must stay stdlib-light and never wait on the app's imports."""
    try:
        state = json.loads(paths.STATE_FILE.read_text("utf-8"))
        if state.get("server.port"):
            return int(state["server.port"])
    except Exception:                     # noqa: BLE001
        pass
    for path in (paths.SETTINGS_FILE, paths.DEFAULTS_FILE):
        try:
            data = tomllib.loads(path.read_text("utf-8"))
        except Exception:                 # noqa: BLE001
            continue
        port = data.get("server", {}).get("port")
        if port:
            return int(port)
    return DEFAULT_PORT


def server_url() -> str:
    """http://127.0.0.1:<port>/notify — see server_port."""
    return f"http://127.0.0.1:{server_port()}/notify"


def read_token(path=None) -> str | None:
    """The phone bearer: from the secret store, or — while an older app
    has not yet moved it — the plaintext file; ``--token-file`` names a
    file explicitly. Anything failing is None, never an exception."""
    if path is None:
        try:
            import secretstore
            token = secretstore.get("phone_token")
            if token:
                return token
        except Exception:                 # noqa: BLE001
            pass
        path = TOKEN_FILE
    try:
        token = Path(path).read_text("utf-8").strip()
    except Exception:                     # noqa: BLE001
        return None
    return token or None


def post(payload: dict, url: str, token: str, timeout: float = 3.0) -> bool:
    """One POST; True on a 2xx. Any failure — no app, wrong port, bad
    token, a slow reply — is False, never an exception."""
    try:
        req = urllib.request.Request(
            url, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Authorization": f"Bearer {token}",
                     "Content-Type": "application/json; charset=utf-8"},
            method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return 200 <= resp.status < 300
    except Exception:                     # noqa: BLE001
        return False


def hook_entries(python: str, script: str) -> dict:
    command = f'"{python}" "{script}"'
    hook = {"type": "command", "command": command, "timeout": 10}
    return {
        "Stop": [{"hooks": [dict(hook)]}],
        "Notification": [{"matcher": "idle_prompt|permission_prompt",
                          "hooks": [dict(hook)]}],
    }


def _is_ours(entry) -> bool:
    if not isinstance(entry, dict):
        return False
    for hook in entry.get("hooks") or []:
        if isinstance(hook, dict) and "notify_hook.py" in str(
                hook.get("command", "")):
            return True
    return False


def install_hook(settings_path, python: str | None = None,
                 script: str | None = None) -> bool:
    """Write our two hook entries into settings.json; True if the file
    changed. Idempotent: an entry naming notify_hook.py is replaced,
    everything else in the file is kept byte for byte in meaning."""
    settings_path = Path(settings_path)
    python = python or str(HERE / ".venv" / "Scripts" / "pythonw.exe")
    script = script or str(HERE / "notify_hook.py")
    try:
        data = json.loads(settings_path.read_text("utf-8"))
    except FileNotFoundError:
        data = {}
    if not isinstance(data, dict):
        data = {}
    before = copy.deepcopy(data)
    hooks = data.get("hooks")
    if not isinstance(hooks, dict):
        hooks = {}
        data["hooks"] = hooks
    for event, entries in hook_entries(python, script).items():
        existing = hooks.get(event)
        if not isinstance(existing, list):
            existing = []
        hooks[event] = [e for e in existing if not _is_ours(e)] + entries
    if data == before and settings_path.exists():
        return False
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = settings_path.with_name(f"{settings_path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                   "utf-8")
    os.replace(tmp, settings_path)
    return True


def _read_stdin_json() -> dict | None:
    """The hook event, or None. pythonw has no stdin at all (sys.stdin is
    None), and a console python's stdin is decoded in the console's code
    page — so the bytes are read and decoded as UTF-8 here."""
    stream = sys.stdin
    if stream is None:
        return None
    try:
        buf = getattr(stream, "buffer", None)
        raw = buf.read() if buf is not None else stream.read().encode("utf-8")
    except Exception:                     # noqa: BLE001
        return None
    if not raw or not raw.strip():
        return None
    try:
        event = json.loads(raw.decode("utf-8", "replace"))
    except ValueError:
        return None
    return event if isinstance(event, dict) else None


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="notify_hook.py", add_help=True,
        description="Send a notification to the running dictation app.")
    p.add_argument("--title")
    p.add_argument("--body", default="")
    p.add_argument("--source", default="cli")
    p.add_argument("--kind", default="info")
    p.add_argument("--project", default="")
    p.add_argument("--session", default="")
    # The window a click on the card raises. Resolved the same way as in
    # hook mode unless a caller names its own — a program that knows its
    # HWND should say so rather than let a walk find its console's.
    p.add_argument("--hwnd", default=None)
    p.add_argument("--app", default=None)
    # The session a click on the card goes to. Left unsaid it is looked
    # up from --session the way the hook looks it up from the event, so
    # a caller that already knows the CLI session id gets the link for
    # free; --link "" is how a caller says "no session, just the window".
    p.add_argument("--link", default=None)
    p.add_argument("--install-hook", action="store_true")
    p.add_argument("--settings", default=None)
    p.add_argument("--url", default=None)
    p.add_argument("--token-file", default=None)
    return p


def _main(argv) -> None:
    args = _parser().parse_args(argv)
    if args.install_hook:
        path = Path(args.settings) if args.settings else DEFAULT_SETTINGS
        changed = install_hook(path)
        sys.stderr.write(f"{'hooks written to' if changed else 'unchanged:'}"
                         f" {path}\n")
        return
    if args.title is not None:
        hwnd, app = owner_window()
        if args.hwnd is not None:
            try:
                hwnd = max(0, int(str(args.hwnd), 0))
            except (TypeError, ValueError):
                hwnd = 0
            app = args.app or ""
        if args.app is not None:
            app = args.app
        link = args.link if args.link is not None \
            else session_link(args.session)
        payload = {"source": args.source, "kind": args.kind,
                   "title": args.title, "body": args.body,
                   "project": args.project, "session": args.session,
                   "hwnd": int(hwnd), "app": str(app), "link": str(link)}
    else:
        event = _read_stdin_json()
        payload = payload_from_hook(event) if event is not None else None
        if payload is None:
            return
    token = read_token(args.token_file)
    if token is None:
        return
    post(payload, args.url or server_url(), token)


def main(argv=None) -> int:
    """Exit 0 whatever happened: a hook that fails must fail silently,
    and the CLI form inherits the rule because it shares the code."""
    try:
        _main(sys.argv[1:] if argv is None else list(argv))
    except (Exception, SystemExit):       # noqa: BLE001 — argparse exits
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
