"""Talking to the running instance: one JSON message in, one JSON message
out, over a named pipe.

The dashboard is a SEPARATE process, and it has to be — half its job is to
start the app, which means it must exist while the app does not. So the two
need a channel, and the channel has to answer three different questions:

- is it running, and what is it doing right now (status, polled)?
- do this (pause, resume, rebind a key)?
- did that work, and if not, why (a reply, not a guess)?

singleton.py already solves half of this with named kernel objects, and a
second named EVENT per command was the first design. It was dropped because
events are fire-and-forget: they can ask for a pause and can never report
that the key name was rejected, and "read the state" would have become a
file the app writes and the dashboard polls, with all the half-written-file
races that implies. A named pipe is request/response, which is what this
actually is.

Why a pipe and not a socket on 127.0.0.1: no port to collide with, no
listening TCP socket on a machine where the only other one (server.py) is
deliberately loopback-only and token-guarded, and no port file to keep in
sync. The pipe name IS the address.

Access: a named pipe's default security descriptor grants full control to
its creator and to administrators, and READ-only access to Everyone. Every
command here arrives by WRITING, so another user on this machine cannot
drive the app; this is not a remote surface at all (remote clients are
refused by flag). What the descriptor cannot stop is a program creating
the name FIRST — see FILE_FLAG_FIRST_PIPE_INSTANCE below.

Both halves are deliberately dumb. The server owns no state — it is handed
one callable and forwards to it — and the client returns None for "nothing
answered" rather than raising, because "the app is not running" is the
normal case for a dashboard that exists to start it.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from typing import Callable

import paths

PIPE_NAME = paths.kernel_name(r"\\.\pipe\DeskIT.control")
MAX_MESSAGE = 1 << 16
# pywin32 RETURNS this as ReadFile's status rather than raising it, which
# is exactly how it gets dropped on the floor.
ERROR_MORE_DATA = 234
# Connecting fails in two completely different ways, and telling them
# apart is the whole of the retry policy below.
ERROR_FILE_NOT_FOUND = 2      # there is no pipe: probably nothing running
ERROR_PIPE_BUSY = 231         # there is one, someone else is using it
ERROR_ACCESS_DENIED = 5       # CreateNamedPipe: the name is already taken
# The pipe name is machine-global, so another program — another Windows
# user's included — can create it BEFORE this app does, and then every
# command the desk sends (the recovery key typed on it among them) goes
# to that program (2026-09-23 audit A58; 2026-11-09 security-local 6).
# The first instance is therefore made with FILE_FLAG_FIRST_PIPE_INSTANCE,
# which fails when the name already exists, and the app refuses to serve
# beside it. pywin32 has the value in win32pipe on this build and not in
# win32file, so it is spelled out. Remote clients are refused outright:
# nothing on another machine has any business on this pipe.
FILE_FLAG_FIRST_PIPE_INSTANCE = 0x00080000
PIPE_REJECT_REMOTE_CLIENTS = 0x00000008

log = logging.getLogger("app")


def _pipe_modules():
    """pywin32 bits, imported lazily so importing this module is safe
    anywhere (tests import it on its own, and main.py imports it before it
    knows whether the rest of the environment is sane)."""
    import win32file
    import win32pipe
    return win32pipe, win32file


def _instance(win32pipe, *, first: bool):
    """One pipe instance. `first` adds FILE_FLAG_FIRST_PIPE_INSTANCE, so
    it fails (ERROR_ACCESS_DENIED) when the name already exists."""
    return win32pipe.CreateNamedPipe(
        PIPE_NAME,
        win32pipe.PIPE_ACCESS_DUPLEX
        | (FILE_FLAG_FIRST_PIPE_INSTANCE if first else 0),
        win32pipe.PIPE_TYPE_MESSAGE
        | win32pipe.PIPE_READMODE_MESSAGE | win32pipe.PIPE_WAIT
        | PIPE_REJECT_REMOTE_CLIENTS,
        win32pipe.PIPE_UNLIMITED_INSTANCES,
        MAX_MESSAGE, MAX_MESSAGE, 0, None)


class ControlServer:
    """A small pool of pipe instances, one listener thread each.

    A pool rather than a single instance because a single one is only ever
    listening BETWEEN clients: while it serves the status poll, a button
    press arriving at that moment finds the pipe busy, and in the sliver
    where it has disconnected but not yet re-created the instance the pipe
    does not exist at all. Both look like "nothing is running" to a client
    that does not retry hard. Measured on a single instance under three
    concurrent callers, 8 of 75 commands were lost; with the pool, none.

    Handlers run ON A LISTENER THREAD, not the caller's, and they touch
    live app state — so they must be short and take whatever lock they
    need. None of them may block: a handler that waited on a transcription
    would hang the dashboard's next status poll and make a working app look
    frozen.
    """

    INSTANCES = 4
    #: How long a refused first instance is tried again before the app
    #: believes it. The pipe of a copy that is just leaving can outlive
    #: its mutex by the 0.35 s main() waits for the bye cue, and a restart
    #: that lands in that gap must not lose its channel for the session;
    #: a program that took the name on purpose is still there after this.
    FIRST_WAIT_S = 3.0

    def __init__(self, handler: Callable[[str, dict], dict]) -> None:
        self._handler = handler
        self._threads: list[threading.Thread] = []
        self._stopping = threading.Event()
        self._listening = threading.Event()
        self._warned = False

    def start(self) -> bool:
        """True if the listener came up. A failure is logged and swallowed:
        the dashboard is a convenience, and dictation must not depend on
        it.

        The FIRST pipe instance is made here, before any thread, with
        FILE_FLAG_FIRST_PIPE_INSTANCE: a name that already exists is
        somebody else's pipe, and the answer is to refuse — a WARNING in
        app.log, no channel — not to serve beside it. That is also why
        the first request after a start cannot find "file not found":
        WaitNamedPipe does NOT wait for a pipe that has not been created
        yet, and this one exists before start() returns.
        """
        try:
            win32pipe, _win32file = _pipe_modules()
        except Exception as e:
            log.info("control channel unavailable (%s) — the dashboard will "
                     "not be able to see this instance", e)
            return False
        self._stopping.clear()
        deadline = time.monotonic() + max(0.0, self.FIRST_WAIT_S)
        while True:
            try:
                first = _instance(win32pipe, first=True)
                break
            except Exception as e:
                taken = getattr(e, "winerror", 0) == ERROR_ACCESS_DENIED
                if taken and time.monotonic() < deadline:
                    time.sleep(0.1)
                    continue
                if taken:
                    log.warning(
                        "control channel refused: a pipe named %s already "
                        "exists and this app did not make it — the desk "
                        "will not see or drive this instance until whatever "
                        "holds the name is gone", PIPE_NAME)
                else:
                    log.warning("control channel did not come up (%r)", e)
                return False
        self._listening.set()
        self._threads = [
            threading.Thread(target=self._run, args=(first if i == 0 else None,),
                             daemon=True, name=f"control-{i}")
            for i in range(self.INSTANCES)]
        for thread in self._threads:
            thread.start()
        return self._listening.wait(timeout=3)

    def stop(self) -> None:
        if not self._threads:
            return
        self._stopping.set()
        # ConnectNamedPipe blocks until SOMEONE connects, and there is no
        # way to cancel it from another thread. So connect to it ourselves:
        # the listener wakes, finds _stopping set, and returns. One
        # connection wakes exactly one thread, hence the loop.
        win32pipe, win32file = _pipe_modules()
        for _ in range(len(self._threads)):
            try:
                win32pipe.WaitNamedPipe(PIPE_NAME, 200)
                handle = win32file.CreateFile(
                    PIPE_NAME,
                    win32file.GENERIC_READ | win32file.GENERIC_WRITE,
                    0, None, win32file.OPEN_EXISTING, 0, None)
                win32file.CloseHandle(handle)
            except Exception:
                pass      # already gone, or never came up
        for thread in self._threads:
            thread.join(timeout=2)
        self._threads = []

    # -- control thread --

    def _run(self, handle=None) -> None:
        win32pipe, win32file = _pipe_modules()
        while not self._stopping.is_set():
            if handle is None:
                try:
                    handle = _instance(win32pipe, first=False)
                except Exception as e:
                    # Not a client hanging up: the name would not take
                    # another instance. Said once at WARNING (the first
                    # version said it at DEBUG and spun on it, four
                    # threads at full speed), then a half-second pause.
                    if not self._warned:
                        self._warned = True
                        log.warning("control channel: could not make a pipe "
                                    "instance (%r)", e)
                    self._stopping.wait(0.5)
                    continue
            try:
                self._listening.set()
                win32pipe.ConnectNamedPipe(handle, None)
                if self._stopping.is_set():
                    break
                self._serve_one(win32pipe, win32file, handle)
            except Exception as e:
                if not self._stopping.is_set():
                    # A client that hangs up mid-message is routine (the
                    # instance's own failures are above, at WARNING). Log
                    # and carry on rather than killing the channel for the
                    # rest of the session.
                    log.debug("control channel hiccup: %r", e)
            finally:
                try:
                    win32pipe.DisconnectNamedPipe(handle)
                except Exception:
                    pass
                try:
                    win32file.CloseHandle(handle)
                except Exception:
                    pass
                handle = None
        if handle is not None:            # stopped before it was served
            try:
                win32file.CloseHandle(handle)
            except Exception:
                pass

    def _serve_one(self, win32pipe, win32file, handle) -> None:
        _, data = win32file.ReadFile(handle, MAX_MESSAGE)
        try:
            request = json.loads(bytes(data).decode("utf-8"))
            command = str(request.get("command", ""))
            args = request.get("args") or {}
            reply = self._handler(command, args)
        except Exception as e:
            # Never let a bad request take the channel down — answer with
            # the failure so the dashboard can SAY what went wrong.
            reply = {"ok": False, "error": f"{type(e).__name__}: {e}"}
        payload = json.dumps(reply, ensure_ascii=False).encode("utf-8")
        win32file.WriteFile(handle, payload)
        win32file.FlushFileBuffers(handle)


def send(command: str, timeout_ms: int = 2000, **args) -> dict | None:
    """Ask the running instance something. None = nothing is listening.

    None and {"ok": False} are different answers on purpose: "the app is
    not running" and "the app refused" want different words in front of the
    user, and collapsing them is how a rejected key name comes out as "the
    app is not running" and sends someone restarting it.
    """
    try:
        win32pipe, win32file = _pipe_modules()
    except Exception:
        return None
    # Two different races live here, and they need opposite policies —
    # which is why CreateFile is inside the loop and why the error code
    # matters:
    #
    # - "no pipe at all" (ERROR_FILE_NOT_FOUND). Usually true: nothing is
    #   running, and the dashboard polls this several times a second, so it
    #   has to fail FAST. But it is also the microsecond sliver between the
    #   server closing one instance and creating the next, so it gets a few
    #   quick retries before being believed.
    # - "busy" (ERROR_PIPE_BUSY, or WaitNamedPipe timing out). Something IS
    #   listening, another client just got there first. WaitNamedPipe
    #   succeeding does not RESERVE the instance — it only says one was
    #   free a moment ago — so the loser must keep trying until the
    #   caller's own timeout. The dashboard always has two clients (the
    #   status poller every 800 ms, plus a thread per button press), and a
    #   dropped "pause" is not cosmetic: it leaves the hook live while the
    #   key-capture window is open, so the key being rebound fires for real.
    #
    # Retrying is safe: nothing has been written yet, so no command can be
    # executed twice.
    deadline = time.monotonic() + max(0.05, timeout_ms / 1000)
    handle = None
    missing = 0
    while handle is None:
        try:
            win32pipe.WaitNamedPipe(PIPE_NAME, 50)
            handle = win32file.CreateFile(
                PIPE_NAME, win32file.GENERIC_READ | win32file.GENERIC_WRITE,
                0, None, win32file.OPEN_EXISTING, 0, None)
        except Exception as e:
            if getattr(e, "winerror", 0) == ERROR_FILE_NOT_FOUND:
                missing += 1
                if missing >= 3:
                    return None       # genuinely nothing listening
            if time.monotonic() >= deadline:
                return None
            time.sleep(0.02)
    try:
        win32pipe.SetNamedPipeHandleState(
            handle, win32pipe.PIPE_READMODE_MESSAGE, None, None)
        payload = json.dumps({"command": command, "args": args},
                             ensure_ascii=False).encode("utf-8")
        win32file.WriteFile(handle, payload)
        # ReadFile hands ERROR_MORE_DATA back as the RETURN CODE together
        # with the first MAX_MESSAGE bytes — it does not raise. Discarding
        # it truncates a long reply into invalid JSON, and the except below
        # then reports a perfectly healthy app as "nothing is listening".
        chunks: list[bytes] = []
        while True:
            status, part = win32file.ReadFile(handle, MAX_MESSAGE)
            chunks.append(bytes(part))
            if status != ERROR_MORE_DATA:
                break
        return json.loads(b"".join(chunks).decode("utf-8"))
    except Exception:
        return None
    finally:
        if handle is not None:
            try:
                win32file.CloseHandle(handle)
            except Exception:
                pass
