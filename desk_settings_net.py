"""The Network screen on the web desk — D12's window, reached from EVERY
CONNECTION on Settings > Privacy (#/settings/network), as the Tk desk's
dashboard._screen_network draws it: every outbound request, newest first,
read from network.log — the record the app and the desk share, since they
are two processes. A host filter, the loopback toggle (the phone and the
hook knock on 127.0.0.1 and would drown the rest), the file's own button,
the Offline banner, and the sentence that is the point: during plain
dictation this table stays empty.

network.log holds one row per call — host, purpose, bytes, status, the
secret's NAME, the consent tag — never a body or a URL (net.py), so every
cell of it may reach the page. It is re-read only when the file moved.
"""
from __future__ import annotations

import threading
import time

import paths

#: The columns, the Tk desk's NET_COLS names in its order.
COLUMNS = ("when", "host", "purpose", "bytes", "result", "secret", "consent")
#: The newest this many rows are drawn; the file keeps the rest.
ROWS_MAX = 400
LOOPBACK = "127.0.0.1"


class Network:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._kept: tuple | None = None       # (stamp, rows)

    def rows(self) -> list:
        """net.read_log(), once per change of the file."""
        import net
        try:
            stamp = paths.NETWORK_LOG.stat().st_mtime_ns
        except OSError:
            stamp = None
        with self._lock:
            if self._kept is not None and self._kept[0] == stamp:
                return self._kept[1]
        try:
            rows = list(net.read_log())
        except Exception:                                    # noqa: BLE001 — a log being written
            rows = []
        with self._lock:
            self._kept = (stamp, rows)
        return rows

    def today(self) -> int:
        """dashboard._requests_today: today's requests, loopback aside."""
        day = time.strftime("%Y-%m-%d")
        return sum(1 for r in self.rows() if str(r.when).startswith(day) and r.host != LOOPBACK)

    def read(self, host: str = "All", loopback: bool = False) -> dict:
        """The screen (dashboard._paint_network), as data. `host` and
        `loopback` are the page's filter: a host nobody has seen is "All"."""
        rows = self.rows()
        hosts = sorted({r.host for r in rows if r.host != LOOPBACK})
        if host != "All" and host not in hosts:
            host = "All"
        shown = [r for r in rows
                 if (loopback or r.host != LOOPBACK) and (host == "All" or r.host == host)]
        offline = False
        try:
            import config as config_mod
            import privacy
            offline = bool(privacy.offline()) or bool(
                getattr(config_mod.load_layered().privacy, "offline", False))
        except Exception:                                    # noqa: BLE001
            pass
        line = f"{len(shown)} of {len(rows)} rows" if rows else "no request yet"
        if len(shown) > ROWS_MAX:
            line += f", the newest {ROWS_MAX} painted"
        table = [[str(r.when), str(r.host), str(r.purpose), f"{r.up} ↑ {r.down} ↓",
                  str(r.status), str(r.secret), str(r.consent)]
                 for r in reversed(shown[-ROWS_MAX:])]
        return {
            "ok": True,
            "title": "Network", "sub": "every request, newest first · network.log",
            "hosts": ["All"] + hosts, "host": host, "loopback": bool(loopback),
            "banner": "Offline mode: every host but 127.0.0.1 is refused." if offline else "",
            "columns": list(COLUMNS),
            "rows": table,
            "line": line,
            "empty": "During plain dictation this table stays empty — that is the proof.",
            "toggle": "Hide loopback" if loopback else "Show loopback (phone)",
        }
