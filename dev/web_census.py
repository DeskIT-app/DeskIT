"""Every socket the web desk's window opens — the census behind
webdesk.BASE_ARGS and NETWORK.md's WebView2 section (2026-10-23).

WebView2 has a network stack of its own and Windows' HTTP stack inside
its browser process besides, so neither net.py nor a Chromium netlog can
say what the window sends: the 2026-09-22 netlog was clean while the
browser process held two TLS connections to substrate.office.com. This
asks the OPERATING SYSTEM instead: it opens deskweb's Home exactly as
the desk does (webdesk.run, BASE_ARGS, the real page, the pipe narrowed
to `status`), and four times a second lists every TCP and UDP socket of
every process under this one — the WebView2 tree — for SECONDS, then ten
seconds more after the window closes. When a socket to another machine
appears it records the DNS cache's name for that address, at that
moment, and the browser's loaded DLLs. For comparison it also lists
every other msedgewebview2 on the PC that holds an outside connection,
with the program that hosts it (six other programs ran WebView2 on the
owner's PC that day — Windows Search, Widgets, WhatsApp, Spotify, PC
Manager, Ollama — and explorer.exe itself holds connections to the same
Microsoft 365 addresses: a census that does not separate them blames
the desk for their traffic).

Run it HIDDEN (house rule 8) and from the venv that has pywebview:

    .venv\\Scripts\\python.exe -c "import tests_quiet as q, pathlib; q.run_hidden(r'.venv\\Scripts\\python.exe dev\\web_census.py OUT 180', pathlib.Path('.'), desktop='DeskITCensus')"

    OUT                 a NEW folder: OUT\\profile is the WebView2 profile,
                        OUT\\census.json the result (a folder that already
                        holds a profile is refused: it would be a warm start
                        reported as a first one)
    SECONDS             how long to watch after the page has loaded
    --warm FOLDER       start from a copy of an earlier run's profile (the
                        second start of a copy is the one that talked)
    --features a,b      add these to --disable-features, to bisect
    --control           the positive control: the window also opens a
                        loopback debugging port, which this must see as a
                        listening socket of the browser (exit 0 only if it
                        did) — so a zero from the real run means "nothing",
                        not "the census went blind"

MEASURED 2026-10-23, runtime 155.0.4283.62 (numbers in NETWORK.md): with
the flags of 2026-09-22 a fresh profile held no socket for 180 s, and
each of 6 warm starts held two TLS connections to substrate.office.com
2-4 s after load — Edge's OneAuth sign-in through Windows' account broker
(encrypted, not read; msedge.dll names the Windows account's profile and
photo on that host); msOneAuthWAM stops it. Re-run after a runtime
update before quoting this.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

# muted before anything of the app is imported (house rule 8)
import winsound

winsound.PlaySound = lambda *a, **k: None
winsound.Beep = lambda *a, **k: None

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

LOOPBACK = {"127.0.0.1", "::1", "0.0.0.0", "::", ""}


def dns_cache() -> list[str]:
    """`name|address` for every record in Windows' DNS client cache."""
    out = subprocess.run(["powershell", "-NoProfile", "-Command",
                          "Get-DnsClientCache | ForEach-Object { $_.Entry + '|' + $_.Data }"],
                         capture_output=True, text=True, timeout=60,
                         creationflags=0x08000000)
    return sorted({line.strip() for line in out.stdout.splitlines() if line.strip()})


def _role(proc) -> str:
    try:
        parts = proc.cmdline()
    except Exception:                      # noqa: BLE001
        return "?"
    for part in parts:
        if part.startswith("--type="):
            kind = part[7:]
            sub = [p for p in parts if p.startswith("--utility-sub-type=")]
            return kind + (":" + sub[0].split("=", 1)[1] if sub else "")
    return "browser"


def _host(proc) -> str:
    try:
        while proc is not None and proc.name().lower() == "msedgewebview2.exe":
            proc = proc.parent()
        return f"{proc.name()}({proc.pid})" if proc else "?"
    except Exception:                      # noqa: BLE001
        return "?"


def _addr(a) -> str:
    return f"{a.ip}:{a.port}" if a else ""


class Census:
    def __init__(self) -> None:
        import psutil
        self.psutil = psutil
        self.me = psutil.Process()
        self.ours: dict = {}
        self.others: dict = {}
        self.samples = 0
        self.tree_max = 0
        self.t0 = time.time()

    def sample(self) -> None:
        now = time.time() - self.t0
        tree = {p.pid: p for p in self.me.children(recursive=True)}
        self.tree_max = max(self.tree_max, len(tree))
        for pid, proc in tree.items():
            try:
                conns = proc.net_connections(kind="inet")
            except Exception:              # noqa: BLE001 — it exited
                continue
            for c in conns:
                key = (pid, _addr(c.laddr), _addr(c.raddr), int(c.type))
                row = self.ours.get(key)
                if row is None:
                    row = self.ours[key] = {
                        "pid": pid, "role": _role(proc), "type": "tcp" if c.type == 1 else "udp",
                        "laddr": _addr(c.laddr), "raddr": _addr(c.raddr),
                        "first_s": round(now, 2), "states": []}
                    if c.raddr and c.raddr.ip not in LOOPBACK:
                        row["dns"] = [e for e in dns_cache() if e.endswith("|" + c.raddr.ip)]
                        try:
                            row["dlls"] = sorted({Path(m.path).name.lower() for m in proc.memory_maps()
                                                  if m.path.lower().endswith(".dll")})
                        except Exception as e:  # noqa: BLE001
                            row["dlls"] = repr(e)
                row["last_s"] = round(now, 2)
                if c.status not in row["states"]:
                    row["states"].append(c.status)
        for c in self.psutil.net_connections(kind="inet"):
            if not c.pid or c.pid in tree or not c.raddr or c.raddr.ip in LOOPBACK:
                continue
            try:
                proc = self.psutil.Process(c.pid)
                if proc.name().lower() != "msedgewebview2.exe":
                    continue
            except Exception:              # noqa: BLE001
                continue
            row = self.others.setdefault((c.pid, _addr(c.raddr)), {
                "host": _host(proc), "role": _role(proc), "raddr": _addr(c.raddr),
                "first_s": round(now, 2)})
            row["last_s"] = round(now, 2)
        self.samples += 1

    def external(self) -> list:
        return [r for r in self.ours.values()
                if r["raddr"] and r["raddr"].rsplit(":", 1)[0].strip("[]") not in LOOPBACK]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("out")
    parser.add_argument("seconds", type=float)
    parser.add_argument("--warm", help="an earlier run's folder whose profile to start from")
    parser.add_argument("--features", default="", help="more names for --disable-features")
    parser.add_argument("--control", action="store_true",
                        help="positive control: open a loopback debugging port the census must see")
    ns = parser.parse_args(argv)

    out = Path(ns.out)
    if (out / "profile").exists():
        parser.error(f"{out} already holds a profile: a re-run there is a warm start; "
                     "use a new folder (and --warm to start from an old one)")

    import control
    import deskweb
    import webdesk

    if ns.features:
        webdesk.BASE_ARGS = (webdesk.BASE_ARGS[0] + "," + ns.features, *webdesk.BASE_ARGS[1:])
    extra = ("--remote-debugging-port=0",) if ns.control else ()
    out.mkdir(parents=True, exist_ok=True)
    if ns.warm:
        shutil.copytree(Path(ns.warm) / "profile", out / "profile")

    def status_only(command, timeout_ms=2000, **args):
        # the pipe of a checkout is the owner's LIVE app: it is asked for
        # its status and nothing else
        if command != "status":
            return {"ok": False, "error": "census: status only"}
        return control.send("status", timeout_ms=timeout_ms)

    census = Census()
    note: dict = {"args": webdesk.browser_args(extra), "seconds": ns.seconds,
                  "warm": bool(ns.warm), "control": ns.control}

    def on_ready(desk):
        started = time.time()
        while time.time() - started < ns.seconds:
            census.sample()
            time.sleep(0.25)
        note["page_read"] = desk.js("document.body.dataset.read || null")
        note["env"] = dict(desk.env_info)
        note["blocked"] = list(desk.blocked)
        note["errors"] = list(desk.errors)

    note["code"] = webdesk.run(
        title="DeskIT census", api=deskweb.Api(deskweb.Model(send=status_only)),
        width=deskweb.CLIENT_W + 16, height=deskweb.CLIENT_H + 39,
        storage=out / "profile", on_ready=on_ready, on_form=deskweb._on_form,
        extra_args=extra)
    closed = time.time()
    while time.time() - closed < 10:       # anything said on the way out
        census.sample()
        time.sleep(0.25)
    ext = census.external()
    listening = [r for r in census.ours.values() if "LISTEN" in r["states"]]
    note.update(samples=census.samples, tree_max=census.tree_max,
                ours=sorted(census.ours.values(), key=lambda r: r["first_s"]),
                ours_external=len(ext), listening=len(listening),
                others=list(census.others.values()))
    (out / "census.json").write_text(json.dumps(note, indent=1, default=str), "utf-8")
    print(f"{len(ext)} outside socket(s) in the window's tree over {census.samples} samples "
          f"of up to {census.tree_max} processes; {len(census.others)} of other WebView2 hosts")
    if ns.control:
        print(f"control: {len(listening)} listening socket(s) seen in the window's tree "
              f"({'the census sees sockets' if listening else 'BLIND — do not trust a zero'})")
        return 0 if listening else 2
    return 1 if ext else 0


if __name__ == "__main__":
    sys.exit(main())
