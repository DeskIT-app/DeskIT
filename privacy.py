"""The gates: nothing personal leaves this PC until the person said so.

DISTRIBUTION_PLAN.md chapter 5.1-5.3, decisions D7 and D11. Every cloud
feature — the repair pass, punctuation, translation, lookup, the second
reading, a cloud transcriber, ask-the-screen, the account, its syncs —
is behind one of seven KINDS, and a kind is open only when three things
are true at once:

1. ``consent.json`` (``paths.CONSENT_FILE``) holds a row for it whose
   ``text_version`` equals the one compiled into its card here. The
   provider changed its terms? The version bumps, the row is stale, the
   gate reads shut and the card comes back on the next use (D11).
2. ``[privacy] <kind>`` in the settings is true. ``grant()`` writes it,
   ``withdraw()`` clears it; a hand-edited ``true`` with no row opens
   nothing, and the Settings page cannot write these keys at all
   (``config.save`` refuses them) — a gate flips only through its card.
3. ``[privacy] offline`` is false. Offline is not a consent, it is a
   veto over all of them (5.9).

Two more keys are plain switches, not gates: ``update_check`` (the
weekly GET to GitHub, chapter 11 — on by default, asked once in the
wizard) and ``offline``.

Who asks: every cloud constructor calls ``require(kind)`` as its first
statement and raises its own ``ConsentRequired`` when the gate is shut,
so a feature's chain simply never contains a cloud leg; and ``net.py``
asks again for every request by its purpose (``kind_for``), which is
what makes a consent withdrawn from the dashboard — another process —
take effect on the app's very next request without anyone restarting
anything. Start-up warm-ups therefore never open a card: a shut gate is
one INFO line, the way a missing key is. NEITHER DOES A KEY PRESS, since
2026-09-19 evening: D7 said "the first key press that needs a cloud pass
opens the card", and the owner, walking a fresh copy, met the card in
the middle of a dictation — "it should not appear here". A shut gate now
refuses quietly everywhere; the card opens only from a BUTTON the
person pressed for it (``request``: the wizard's cloud switch records
the consent itself, Settings > Privacy's [Turn on], the ask card's
"use my own key").

A change runs the registered resets (``on_change``): the punctuator,
the lookup engine and the translator forget the cloud leg they cached —
built OR found unbuildable — so the next press rebuilds it whichever
way the gate now points. Withdraw is the tear-down the plan asks for;
grant needs the same reset, or a leg cached as "unavailable" before the
card was answered would stay local until a restart. Rows that appear
or vanish in the file under this process — the dashboard granted or
withdrew — run the same resets when next noticed.

Nothing here reads a key or opens a socket.
"""
from __future__ import annotations

import contextlib
import inspect
import json
import logging
import os
import threading
import time
import weakref
from pathlib import Path

import paths

log = logging.getLogger("app")

#: The consent gates, in the order the Settings page and the guide list
#: them. Each has a card (5.3) and a text_version below.
KINDS: tuple[str, ...] = ("cloud_text", "cloud_audio", "cloud_screenshots",
                          "account", "report_upload", "settings_sync",
                          "history_sync")

#: Plain switches under [privacy]: no card, no consent row.
SWITCHES: tuple[str, ...] = ("update_check", "offline")

#: The version of the words on each card — the providers' "last updated"
#: dates (research/legal; Gemini terms 2026-04-28, Groq Services
#: Agreement 2026-06-22). A card whose words change bumps its version and
#: every old row goes stale. The four DeskIT-side kinds carry the
#: version of the one-page terms of chapter 13 (docs/terms.md).
TEXT_VERSIONS: dict[str, str] = {
    "cloud_text": "groq-2026-06-22+gemini-2026-04-28+en-2026-09-19",
    "cloud_audio": "groq-2026-06-22+gemini-2026-04-28+en-2026-09-19",
    "cloud_screenshots": "groq-2026-06-22+gemini-2026-04-28+en-2026-09-19",
    "account": "deskit-terms-0+en-2026-09-19",
    "report_upload": "deskit-terms-0+en-2026-09-19",
    "settings_sync": "deskit-terms-0+en-2026-09-19",
    "history_sync": "deskit-terms-0+en-2026-09-19",
}

#: net.py's purpose -> the gate it needs. A purpose absent here (key
#: test, catalog, Ollama, the hook, downloads) needs no consent: it
#: carries nothing the person dictated.
PURPOSE_KINDS: dict[str, str] = {
    "polish": "cloud_text", "punctuate": "cloud_text",
    "translate": "cloud_text", "lookup": "cloud_text",
    "review": "cloud_text", "study": "cloud_text", "reading": "cloud_text",
    "transcribe": "cloud_audio",
    "ask-screen": "cloud_screenshots",
    "account": "account", "report": "report_upload", "sync": "settings_sync",
    "history": "history_sync",
    "update-check": "update_check",
}


class ConsentRequired(Exception):
    """The gate for ``kind`` is shut. Each feature module raises a
    subclass that is ALSO its own error class, so "never raises, failure
    = the local path" keeps holding everywhere it holds today."""

    def __init__(self, kind: str, why: str = "not granted"):
        super().__init__(f"{kind}: {why} — the cloud pass needs the "
                         f"person's consent (its card opens on the next "
                         f"press; from a terminal, main.py --consent {kind})")
        self.kind, self.why = kind, why


# ----------------------------------------------------------- the switches

#: What [privacy] said at start-up (configure) and what grant/withdraw
#: changed since. Defaults match defaults.toml so a process that never
#: called configure — a test, a tool — behaves like a fresh install.
_gates: dict[str, bool] = {k: False for k in KINDS}
_gates.update(update_check=True, offline=False)
_lock = threading.RLock()


def configure(cfg) -> None:
    """Take the [privacy] section of the loaded config; tell net.py about
    offline. Called once by main after the config is built."""
    section = getattr(cfg, "privacy", None)
    with _lock:
        for name in KINDS + SWITCHES:
            _gates[name] = bool(getattr(section, name, _gates[name]))
    try:
        import net
        net.offline = bool(_gates["offline"])
    except Exception:                                        # noqa: BLE001
        log.debug("net.offline not set", exc_info=True)


def offline() -> bool:
    return bool(_gates["offline"])


# ---------------------------------------------------------- consent.json

_rows_cache: dict = {"mtime": None, "rows": []}
_resets: dict[str, list] = {}


def _read_file() -> list[dict]:
    try:
        data = json.loads(paths.CONSENT_FILE.read_text("utf-8"))
    except FileNotFoundError:
        return []
    except Exception as e:                                   # noqa: BLE001
        log.warning("consent.json unreadable (%s) — treated as empty; every "
                    "cloud gate reads shut until its card is answered "
                    "again", e)
        return []
    rows = data.get("consents") if isinstance(data, dict) else data
    return [r for r in (rows or []) if isinstance(r, dict) and r.get("kind")]


def _write_file(rows: list[dict]) -> None:
    path = paths.CONSENT_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps({"consents": rows}, ensure_ascii=False,
                              indent=2) + "\n", "utf-8")
    os.replace(tmp, path)


def rows() -> list[dict]:
    """The consent rows on disk, re-read when the file changed. A row
    that disappeared since the last read — withdrawn from the dashboard,
    another process — runs this process's tear-downs for its kind."""
    with _lock:
        try:
            mtime = paths.CONSENT_FILE.stat().st_mtime_ns
        except OSError:
            mtime = None
        if mtime == _rows_cache["mtime"]:
            return list(_rows_cache["rows"])
        before = {r["kind"] for r in _rows_cache["rows"]}
        fresh = _read_file()
        _rows_cache.update(mtime=mtime, rows=fresh)
        now = {r["kind"] for r in fresh}
        for kind in before - now:
            _gates[kind] = False
            _run_resets(kind)
        for kind in now - before:
            if kind in KINDS:
                # Granted from the dashboard, another process: its
                # settings mirror was written too, so the gate opens
                # here without a restart.
                _gates[kind] = True
                _run_resets(kind)
        return list(fresh)


def consent(kind: str) -> dict | None:
    """The row for ``kind`` if it is current (same text_version), else
    None. Stale rows are kept on disk — the Settings page shows the old
    date — but count for nothing."""
    for row in rows():
        if row.get("kind") == kind \
                and row.get("text_version") == TEXT_VERSIONS.get(kind):
            return row
    return None


def tag(kind: str) -> str | None:
    """``kind@text_version`` for the network log's consent column, or
    None when the gate is not open."""
    row = consent(kind)
    return f"{kind}@{row['text_version']}" if row else None


def allowed(kind: str) -> bool:
    """The one contract (5.1): gate true, offline false, current row."""
    if kind in SWITCHES:
        return bool(_gates[kind]) if kind == "update_check" else False
    if kind not in KINDS:
        raise ValueError(f"unknown consent kind {kind!r}")
    if _gates["offline"] or not _gates[kind]:
        return False
    return consent(kind) is not None


def require(kind: str) -> str:
    """``allowed`` or raise ``ConsentRequired`` with the reason. Returns
    the consent tag so a caller can put it on its network row."""
    if kind in SWITCHES:
        if kind == "update_check" and _gates[kind]:
            return f"{kind}@switch"
        raise ConsentRequired(kind, "switched off")
    if kind not in KINDS:
        raise ValueError(f"unknown consent kind {kind!r}")
    if _gates["offline"]:
        raise ConsentRequired(kind, "offline mode is on")
    row = consent(kind)
    if not _gates[kind] or row is None:
        _ask(kind)
        if row is not None:
            raise ConsentRequired(kind, "gate is off")
        stale = any(r.get("kind") == kind for r in rows())
        raise ConsentRequired(kind, "the card's words changed; consent "
                              "must be given again" if stale else "not granted")
    return f"{kind}@{row['text_version']}"


def kind_for(purpose: str) -> str | None:
    return PURPOSE_KINDS.get(purpose)


# ------------------------------------------------------------- the card

#: Set by main to the consent card's `show(kind)`. Called from whatever
#: thread met the refusal, so it must only enqueue.
_asker = None
#: Kinds already asked in this process. [Not now] leaves the kind here
#: until the next start (D7); [Turn on] takes it out through grant().
_asked: set[str] = set()
#: Is the current thread inside a key press the person made? Only then
#: may a refusal open the card — a start-up warm-up meets the same
#: refusal and must open nothing (plan 5.2).
_press = threading.local()


def set_asker(fn) -> None:
    global _asker
    _asker = fn


@contextlib.contextmanager
def pressed():
    """The controller of a key wraps the work the press does: inside,
    the first refusal of a kind asks its card."""
    before = getattr(_press, "on", False)
    _press.on = True
    try:
        yield
    finally:
        _press.on = before


def in_press() -> bool:
    return bool(getattr(_press, "on", False))


def _ask(kind: str) -> None:
    """A refusal met inside a press: written down, and NO card (the
    owner, 2026-09-19 evening). `request` is the road for a button."""
    if _asker is None or not in_press():
        return
    with _lock:
        if kind in _asked:
            return
        _asked.add(kind)
    log.info("%s: not granted — the switch is in the wizard and Settings > Privacy", kind)


def request(kind: str) -> bool:
    """A button the person pressed that needs ``kind`` (the ask card's
    "use my own key", the Privacy tab's [Turn on]): ask its card now,
    inside a press or not. True when a card was asked; False when the
    gate is already open or no card exists in this process."""
    if kind not in KINDS:
        raise ValueError(f"unknown consent kind {kind!r}")
    if allowed(kind) or _asker is None:
        return False
    with _lock:
        _asked.add(kind)
    try:
        _asker(kind)
        return True
    except Exception:                                        # noqa: BLE001
        log.info("could not open the consent card for %s", kind, exc_info=True)
        return False


def not_now(kind: str) -> None:
    """[Not now]: the local path answers and the card stays down until
    the next start. Recorded, never written — a refusal to consent is
    not a consent row."""
    with _lock:
        _asked.add(kind)
    log.info("consent for %s: not now — the local path answers; the card "
             "asks again after the next start", kind)


def _app_version() -> str:
    try:
        import version
        return version.VERSION
    except Exception:                                        # noqa: BLE001
        return "dev"


def _write_gate(kind: str, value: bool) -> None:
    """Mirror the gate into settings.toml through config.save's one
    consent-aware door; a failure there is logged, never fatal — the row
    is the evidence, the key is the display."""
    try:
        import config as config_mod
        config_mod.save({f"privacy.{kind}": value}, allow_consent=True)
    except Exception as e:                                   # noqa: BLE001
        log.info("could not mirror privacy.%s=%s into settings.toml (%s)",
                 kind, value, e)


def grant(kind: str, text_version: str | None = None) -> dict:
    """The person pressed [Turn on] on the card for ``kind``: one row,
    written atomically, and the gate mirrored into the settings."""
    if kind not in KINDS:
        raise ValueError(f"unknown consent kind {kind!r}")
    version_ = text_version or TEXT_VERSIONS[kind]
    if version_ != TEXT_VERSIONS[kind]:
        raise ValueError(f"{kind}: the card shown was {version_}, the "
                         f"current card is {TEXT_VERSIONS[kind]}")
    row = {"kind": kind, "text_version": version_,
           "when": time.strftime("%Y-%m-%dT%H:%M:%S"),
           "app_version": _app_version()}
    with _lock:
        kept = [r for r in rows() if r.get("kind") != kind]
        _write_file(kept + [row])
        # Remember what was written and re-read on the next ask: a row
        # that then turns out to be missing was removed by someone else.
        _rows_cache.update(mtime=None, rows=kept + [row])
        _gates[kind] = True
    with _lock:
        _asked.discard(kind)
    _write_gate(kind, True)
    _run_resets(kind)
    log.info("consent granted: %s (%s)", kind, version_)
    return row


def sign_in_grants() -> list[str]:
    """The sign-in press is TWO consents (the owner, 2026-09-20: "no
    user should have to press anything — he signs in on the second PC
    and is inside with all his settings"): the account, and the words-
    and-settings sync that the account card itself promises ("your
    learned words and settings follow you to any PC you sign in on").
    Recorded with each card's current text_version; a row already there
    is left alone; Settings > Privacy > Withdraw and the wizard's Ready
    switch still turn the sync off afterwards. Returns what was granted."""
    import consent_card as cc
    granted: list[str] = []
    for kind in ("account", "settings_sync"):
        if consent(kind) is None:
            grant(kind, cc.card_for(kind)["text_version"])
            granted.append(kind)
    return granted


def withdraw(kind: str) -> bool:
    """Settings > Privacy > Withdraw, or the CLI: the row goes, the gate
    is cleared, every registered tear-down runs. True if there was a row
    (stale or not) to remove."""
    if kind not in KINDS:
        raise ValueError(f"unknown consent kind {kind!r}")
    with _lock:
        current = rows()
        kept = [r for r in current if r.get("kind") != kind]
        had = len(kept) != len(current)
        if had:
            _write_file(kept)
        _rows_cache.update(mtime=None, rows=kept)
        was_on = _gates[kind]
        _gates[kind] = False
    if not (was_on or had):
        return False                      # a second Withdraw is a no-op
    _write_gate(kind, False)
    _run_resets(kind)
    log.info("consent withdrawn: %s", kind)
    return had


def on_change(kind: str, fn) -> None:
    """Register ``fn()`` to run whenever ``kind`` opens or closes — a
    feature forgetting the cloud leg it cached. A bound method is held
    weakly: the punctuator is rebuilt whenever its section changes
    (main.LIVE_SECTIONS), and the old one must not be kept alive by
    this list. Idempotent per function object."""
    if kind not in KINDS:
        raise ValueError(f"unknown consent kind {kind!r}")
    ref = weakref.WeakMethod(fn) if inspect.ismethod(fn) else (lambda: fn)
    with _lock:
        refs = _resets.setdefault(kind, [])
        if all(r() is not fn for r in refs):
            refs.append(ref)


def _run_resets(kind: str) -> None:
    with _lock:
        refs = _resets.get(kind, [])
        live = [(r, r()) for r in refs]
        refs[:] = [r for r, fn in live if fn is not None]
    for _r, fn in live:
        if fn is None:
            continue
        try:
            fn()
        except Exception:                                    # noqa: BLE001
            log.info("a reset for %s failed", kind, exc_info=True)


def status() -> list[dict]:
    """One dict per kind for the Settings page and the CLI: open or not,
    when it was granted, the version on file and whether it is stale."""
    on_file = {r.get("kind"): r for r in rows()}
    out = []
    for kind in KINDS:
        row = on_file.get(kind)
        out.append({
            "kind": kind,
            "open": allowed(kind),
            "gate": bool(_gates[kind]),
            "when": (row or {}).get("when", ""),
            "text_version": (row or {}).get("text_version", ""),
            "current_version": TEXT_VERSIONS[kind],
            "stale": bool(row) and row.get("text_version") != TEXT_VERSIONS[kind],
        })
    return out


# ------------------------------------------------------------ the terminal

def cli_list(out=print) -> int:
    out(f"consent file: {paths.CONSENT_FILE}")
    out(f"offline: {'on' if _gates['offline'] else 'off'}   "
        f"update check: {'on' if _gates['update_check'] else 'off'}")
    for s in status():
        if s["open"]:
            state = f"open since {s['when']} ({s['text_version']})"
        elif s["stale"]:
            state = (f"STALE — granted {s['when']} for {s['text_version']}, "
                     f"the card is now {s['current_version']}")
        elif s["when"]:
            state = f"gate off (row from {s['when']})"
        else:
            state = "not granted"
        out(f"  {s['kind']:<18} {state}")
    return 0


def cli_grant(kind: str, out=print) -> int:
    if kind not in KINDS:
        out(f"no such consent kind: {kind} (one of {', '.join(KINDS)})")
        return 2
    row = grant(kind)
    out(f"{kind}: granted {row['when']} ({row['text_version']}); the "
        f"feature uses the cloud from its next press.")
    return 0


def cli_withdraw(kind: str, out=print) -> int:
    if kind not in KINDS:
        out(f"no such consent kind: {kind} (one of {', '.join(KINDS)})")
        return 2
    had = withdraw(kind)
    out(f"{kind}: {'withdrawn' if had else 'was not granted'}; the local "
        f"path answers from the next press.")
    return 0
