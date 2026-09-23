"""A problem report is one line the owner types; everything else the app
collects for him.

The alternative was a text file — open notes, write "the recordings tab
shows yesterday's count", close notes — and it was rejected for the same
reason the correction key exists instead of a spreadsheet of mishearings:
by the time a report is worth reading, the thing that would explain it is
gone. The tab he was on, the dictation that came out wrong, the audio
behind it, which backend decoded it, which model, whether vocab was
replacing yet, what branch was checked out — all of that is knowable at
the moment he is annoyed and knowable at no other. So the typed line is
the ONLY thing asked of him, and this module's whole job is to be
standing there with the rest of the form already filled in.

WHAT GETS ATTACHED, AND WHY EACH PIECE. `dictation` joins the report to
the recording it is about: main.App._last knows the raw and the final
text and where the wav is, and the sidecar beside that wav in recent\\
knows the seconds, the backend, the language and the per-word confidence
the live pass produced. The stem of that wav is stored as
dictation["id"], because review.json already uses the same stem as its
own id — so a problem and the second reading of the same clip can be put
side by side later without either store knowing about the other. The wav
itself is COPIED into problems\\, next to a screenshot if one was
offered, because recent\\ is a ring of a hundred and a report the owner
has not resolved yet will outlive it by weeks (study.Corpus.admit copies
for exactly this reason). `env` is the settings that actually explain a
bad dictation, read through getattr chains so a cfg missing a whole
section, or no cfg at all, costs a report nothing. The screenshot is
also handed back small — thumb() decodes it to PNG bytes a Tk row can
show — because an attachment he cannot see is one he cannot check, and
the picture is the difference between a report about the recordings tab
and a report about whatever was actually on the screen.

OPEN ITEMS ARE NEVER TRIMMED. Resolved ones age out at KEEP_RESOLVED; an
open one is a question nobody has answered, and dropping it to save a
kilobyte would make the store lie about what is wrong with the app. That
is review.py's KEEP_DECIDED rule with the same reasoning behind it.

THE ONE THING THAT CAN TAKE A REPORT OFF THE LIST IS HIM. remove()
throws one away for good — and no surface may call it on a single press.
The dashboard's ✕ asks first ("Delete this report?") and deletes only on
the second, deliberate press, because this store has already lost two of
his real reports to a cleanup that did not ask (2026-09-04) and he asked
for the guard in the same breath as the button: "I don't want the
reports to be deleted instantly". A resolution is not a delete either:
resolve() moves a report to FIXED or CLOSED and back to OPEN as often as
he likes, and Reopen on the row is that call.

AND ONLY HE MAY SAY "FIXED". A routine, or a session, that BELIEVES a
change it made has fixed a report does not resolve it: it marks it —
suggest() puts a "fixed?" on the report, with who thinks so, when, and
one line saying what to try. The report stays OPEN, stays on the tab and
in the digest and in every count of open reports, and the mark is drawn
beside it in a colour that is not the green of Fixed. He tries it, and
HIS press on Fixed (or his word in the chat, and a session pressing it
for him) is what turns the mark into FIXED. The weekly routine got this
wrong on 2026-09-12 at 04:12: it CLOSED three reports because changes
pushed the week before looked like they fixed them — "he pushed" taken
for "he checked" — and he found three problems closed that were not
fixed. His decision, in his words: when the routine identifies such
things, "instead of writing 'fix' it writes 'fix?' in a different
colour, not green like now", and it asks him; if he confirms, the status
changes to Fixed. So resolve() is the only way to FIXED or CLOSED, and
whatever it moves a report to it takes the mark off — a reopened report
starts clean, and a fixed one has nothing left to ask.

NOTHING HERE MAY TAKE DICTATION DOWN. The store is the shape review.py
settled on — a lock file beside the json so the app and the dashboard do
not write over each other, a per-process temp name and one rename so a
reader never sees half a file, an unparseable file read as empty — and
every filesystem error in this module is logged and swallowed. A failed
report is a lost report, which is a nuisance; a raised exception in the
middle of a paste is a lost sentence, which is the thing the app exists
to prevent. The single deliberate exception is clean() refusing an empty
line, because a report with no text in it is not a report and the caller
needs to be told before it draws a confirmation.

problems.md is regenerated from scratch every time it is written, open
items first and newest first, because it is read once a week by the owner
and by an agent working through the list — and a file that is appended to
turns into a log, which is the thing he already had.
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path

import paths

log = logging.getLogger("app")

STORE_NAME = "problems.json"
FOLDER_NAME = "problems"        # sibling folder for pinned wavs + screenshots
DIGEST_NAME = "problems.md"

OPEN, FIXED, CLOSED = "open", "fixed", "closed"
RESOLVED = (FIXED, CLOSED)
STATUSES = (OPEN, FIXED, CLOSED)

# The "fixed?" mark: NOT a status, so nothing that counts or lists open
# reports has to know it exists. It is a key on an OPEN report holding
# {"by", "at", "note"} — who believes a change fixed it, when, and one
# line saying what to try — and it is absent, never empty, on a report
# nobody has made that claim about. See the module docstring for why a
# claim is a mark and not a resolution.
MAYBE = "maybe"

# What kind of problem it is, as a closed set: something came out WRONG,
# something is BROKEN, something is SLOW, it is an IDEA, or it is none of
# those and OTHER is the escape hatch. Order is the order he reads them
# in, everywhere — the dashboard builds its chips straight off this
# tuple — so "other" is last, where a fallback belongs, and "wrong" is
# first because KINDS[0] is the default and a wrong transcript is what he
# will be reporting. "other" must never become that default: a report
# filed under it says nothing about what is broken, which is the whole
# point of asking for a kind.
KINDS = ("wrong", "broken", "slow", "idea", "other")

# Resolved reports kept, newest first. Open ones are NEVER trimmed.
KEEP_RESOLVED = 200

TEXT_MAX = 600
WHERE_MAX = 60
BY_MAX = 40

# The note on a "fixed?" mark. One line, not a report: it says what was
# changed and what he should try, and it is drawn on the row under his
# own text in a smaller face — so it gets a third of TEXT_MAX rather than
# all of it, which is a sentence or two of Hebrew and not a paragraph
# that would push the buttons off the row.
MAYBE_MAX = 200

# The long side of a screenshot thumbnail, in pixels. 220 is what a card
# row can give a picture without pushing the typed line off it, and it is
# still enough of the screen to recognise which tab he was on — which is
# the only question a thumbnail has to answer.
THUMB_MAX = 220

# C0 controls minus tab and newline, exactly notify.clean's set: an
# escape sequence in a typed line is at best formatting and at worst a
# way to talk to whatever terminal ends up printing the digest.
_CONTROLS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")

# Sidecar fields worth carrying into a report. Everything else in a
# recent\\ sidecar is bookkeeping.
_SIDECAR_KEYS = ("seconds", "backend", "language", "raw", "text", "words",
                 "attempts", "last_error")

_STAMP = "%Y%m%d-%H%M%S"


# ---------------------------------------------------------------------------
# the input gate
# ---------------------------------------------------------------------------

def _text(value) -> str:
    if isinstance(value, (str, int, float)):
        return str(value)
    return ""


def _cut(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit - 1] + "…"


def _line(value, limit: int) -> str:
    """One line: controls gone, whitespace collapsed, cut to `limit`."""
    text = _CONTROLS.sub("", _text(value).replace("\r", "\n"))
    return _cut(" ".join(text.split()), limit)


def _body(value, limit: int) -> str:
    """Several lines: controls gone, trailing space per line gone, runs of
    blank lines collapsed to one, cut to `limit`. Newlines survive because
    he may paste an error message under his sentence."""
    text = _CONTROLS.sub("", _text(value).replace("\r\n", "\n")
                         .replace("\r", "\n"))
    lines = [ln.rstrip() for ln in text.split("\n")]
    return _cut(re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip(), limit)


def _iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def clean(report: dict) -> dict:
    """The one gate every report passes through, from the card or the
    dashboard or a hotkey.

    Unknown keys are dropped, values are coerced to text, control
    characters go, whitespace is tidied and each field is cut to its
    maximum. `kind` is admitted against KINDS rather than cleaned — a
    kind this module does not know is the first one, not an error.

    Raises ValueError when there is no text left, which is the only
    exception this module raises on purpose: an empty report is not a
    report, and the caller should say so before it saves anything."""
    if not isinstance(report, dict):
        raise ValueError("expected a JSON object")
    text = _body(report.get("text"), TEXT_MAX)
    if not text:
        raise ValueError("a problem report needs a line of text")
    kind = _line(report.get("kind"), 20).lower()
    return {"where": _line(report.get("where"), WHERE_MAX),
            "kind": kind if kind in KINDS else KINDS[0],
            "text": text}


def suggested(item) -> dict | None:
    """The "fixed?" mark on a stored report, as {"by", "at", "note"} with
    text in every field — or None, which is the ordinary answer, because
    most reports have nobody claiming to have fixed them.

    Read through here rather than off the key so the digest and the
    dashboard agree on what a mark looks like, and so a hand-edited
    problems.json with `"maybe": true` in it is a report without a mark
    and not a traceback into a redraw. Only an OPEN report can carry
    one: resolve() takes it off, so a mark on an answered row is a file
    somebody edited, and it is not shown."""
    if not isinstance(item, dict):
        return None
    mark = item.get(MAYBE)
    if not isinstance(mark, dict) or not mark:
        return None
    if (item.get("status") or OPEN) != OPEN:
        return None
    return {"by": _line(mark.get("by"), BY_MAX),
            "at": _line(mark.get("at"), 40),
            "note": _line(mark.get("note"), MAYBE_MAX)}


# ---------------------------------------------------------------------------
# what the app knows and he should not have to type
# ---------------------------------------------------------------------------

def _dig(obj, *names):
    """getattr down a chain, None the moment anything is missing. A cfg
    with no [local] section, or no cfg at all, reads as None."""
    for name in names:
        if obj is None:
            return None
        obj = getattr(obj, name, None)
    return obj


def _plain(value):
    """Whatever came out of a cfg, as something json.dumps will take."""
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    if isinstance(value, dict):
        # The sidecar's "words" is a list of per-word dicts; keeping it
        # as a dict is what makes the invented-tail evidence readable.
        return {str(k): _plain(v) for k, v in value.items()}
    return str(value)


def _consents() -> list[dict]:
    """The [privacy] gates that were open when the report was filed,
    each with the text version the person agreed to (D7) — so the
    owner can tell why a transcript is in the report at all."""
    try:
        import privacy
        return [{"kind": s["kind"], "text_version": s["text_version"]}
                for s in privacy.status() if s["open"]]
    except Exception:                 # noqa: BLE001
        return []


DIAGNOSE_LINES = 50

#: A Hebrew letter or point (the block, and the presentation forms): an
#: app.log line holding one quotes words, and diagnose() leaves it out.
HEBREW = re.compile("[֐-׿יִ-ﭏ]")


def diagnose(cfg=None) -> str:
    """One text block for a bug report (plan 14.7): env()'s whitelist,
    the backend and the model with its standing on disk, the GPU
    pack's, the channel, the phone port, the pack and model folders'
    presence, and the last DIAGNOSE_LINES lines of app.log — every
    line through the redactor. Never transcripts.log, never a key,
    never a path with a user name in it beyond the data folder's own.
    Best effort: a source that fails is one line saying so."""
    import redact

    lines: list[str] = ["DeskIT diagnostics — this contains no transcripts "
                        "and no keys; read it before sending."]
    try:
        for k, v in env(cfg).items():
            lines.append(f"{k}: {v}")
    except Exception as e:                # noqa: BLE001
        lines.append(f"env: failed ({e})")
    try:
        if cfg is None:
            import config as config_mod
            cfg = config_mod.load_layered()
        import models
        import packs
        lines.append(f"backend: {cfg.backend}")
        lines.append(f"model: {cfg.local.model} — {models.state(cfg.local.model)}")
        if cfg.local.english_model:
            lines.append(f"english model: {cfg.local.english_model} — "
                         f"{models.state(cfg.local.english_model)}")
        lines.append(f"device: {cfg.local.device} / {cfg.local.compute_type}")
        lines.append(f"gpu pack: {packs.standing('gpu')}; skin pack: {packs.standing('skin')}")
        lines.append(f"channel: {paths.CHANNEL}; layout: {paths.describe().split(':')[0]}")
        lines.append(f"phone: {'on' if cfg.server.enabled else 'off'}, port {cfg.server.port}")
    except Exception as e:                # noqa: BLE001
        lines.append(f"settings: failed ({e})")
    try:
        tail = paths.APP_LOG.read_text("utf-8", errors="replace").splitlines()[-DIAGNOSE_LINES:]
        # The second belt behind D8: app.log is meant to carry counts and
        # names only, and a line that carries Hebrew anyway is a line that
        # quotes somebody's words — the 2026-09-23 audit counted 136 such
        # lines in six days of the owner's app.log, under a header that
        # says "no transcripts". Left out, and counted, so the block
        # still says how many lines it is not showing.
        kept = [line for line in tail if not HEBREW.search(line)]
        held = len(tail) - len(kept)
        lines.append(f"--- app.log, last {len(tail)} lines ---" if not held else
                     f"--- app.log, last {len(tail)} lines ({held} left out: "
                     f"they held Hebrew words) ---")
        lines.extend(kept)
    except Exception as e:                # noqa: BLE001
        lines.append(f"app.log: unreadable ({e})")
    try:
        logs = sorted(paths.LOGS_DIR.glob("setup-*.log"))
        if logs:
            tail = logs[-1].read_text("utf-8", errors="replace").splitlines()[-20:]
            lines.append(f"--- {logs[-1].name}, last {len(tail)} lines ---")
            lines.extend(tail)
    except Exception:                     # noqa: BLE001
        pass
    return redact.redact("\n".join(lines), stored=False)


def env(cfg=None) -> dict:
    """Best effort, never raises. The whitelist a report carries
    (DISTRIBUTION_PLAN.md 7.8): the app version, the Windows build,
    the consents that were open, the branch only in the checkout, and
    — when cfg is not None — the settings that explain a bad
    dictation. Model names, never a key; no Python version (the build
    pins it). gpu and tier join when the hardware probe lands (ch. 6)."""
    out: dict = {"version": "", "os_build": "", "consents": _consents()}
    try:
        import hardware
        facts = hardware.recorded()
        if facts:
            out["gpu"] = int(facts.get("cuda_devices") or 0) >= 1
            out["tier"] = str(facts.get("tier") or "")
    except Exception:                     # noqa: BLE001
        pass
    try:
        import version
        out["version"] = version.VERSION
        if paths.DEVELOPER and version.BRANCH:
            out["branch"] = version.BRANCH
    except Exception:                     # noqa: BLE001
        pass
    try:
        w = sys.getwindowsversion()
        out["os_build"] = f"{w.major}.{w.minor}.{w.build}"
    except Exception:                     # noqa: BLE001
        pass
    if cfg is None:
        return out
    try:
        out.update({
            "backend": _plain(_dig(cfg, "backend")),
            "local_model": _plain(_dig(cfg, "local", "model")),
            "english_model": _plain(_dig(cfg, "local", "english_model")),
            "beam_size": _plain(_dig(cfg, "local", "beam_size")),
            "gemini_models": _plain(_dig(cfg, "gemini", "models")),
            "vocab_enabled": _plain(_dig(cfg, "vocab", "enabled")),
            "vocab_replace_after_hits":
                _plain(_dig(cfg, "vocab", "replace_after_hits")),
            "polish_when": _plain(_dig(cfg, "polish", "when")),
            "punctuate_auto": _plain(_dig(cfg, "punctuate", "auto")),
            "review_enabled": _plain(_dig(cfg, "review", "enabled")),
            "max_seconds": _plain(_dig(cfg, "max_seconds")),
        })
    except Exception as e:                # noqa: BLE001
        log.info("problems: could not read the settings for a report (%s)", e)
    return out


def _wav_path(raw, app_dir: Path | None) -> Path | None:
    """The wav `last` points at. An absolute path is taken as it is; a
    bare name is looked for in recent\\ under app_dir, which is where the
    ring lives."""
    name = _text(raw).strip()
    if not name:
        return None
    p = Path(name)
    if p.is_absolute():
        return p
    if app_dir is not None:
        for candidate in (Path(app_dir) / "recent" / p, paths.RECENT_DIR / p,
                          Path(app_dir) / p):
            if candidate.exists():
                return candidate
    return p


def _sidecar(wav: Path) -> dict:
    """The recording's json, or {}. Never raises."""
    try:
        data = json.loads(wav.with_suffix(".json").read_text("utf-8"))
    except Exception:                     # noqa: BLE001
        return {}
    return data if isinstance(data, dict) else {}


def dictation(last: dict | None = None, app_dir: Path | None = None) -> dict:
    """What the last dictation was, from `last` plus its sidecar.

    `last` is main.App._last: raw, final, when, wav. The stem of the wav
    becomes "id", which is the id review.json already files the same clip
    under. With no wav this is partial, and with no `last` it is {} —
    neither is an error, because a problem does not have to be about a
    dictation."""
    if not isinstance(last, dict) or not last:
        return {}
    out: dict = {}
    for name in ("raw", "final", "when"):
        value = _text(last.get(name)).strip()
        if value:
            out[name] = value
    wav = _wav_path(last.get("wav"), app_dir)
    if wav is not None:
        out["id"] = wav.stem
        out["wav"] = str(wav)
        for key, value in _sidecar(wav).items():
            if key in _SIDECAR_KEYS and key not in out:
                out[key] = _plain(value)
    return out


def context(*, where: str = "", cfg=None, last: dict | None = None,
            app_dir: Path | None = None) -> dict:
    """The half of a report the owner does not type. Never raises — a
    piece that cannot be read is missing, not fatal."""
    return {"where": _line(where, WHERE_MAX),
            "dictation": dictation(last, app_dir),
            "env": env(cfg)}


# ---------------------------------------------------------------------------
# pinning the evidence out of the ring
# ---------------------------------------------------------------------------

def _rel(folder: Path, path: Path) -> str:
    """How a pinned file is written down: "problems/<name>", relative to
    the folder's parent, so the string survives the app moving."""
    return f"{Path(folder).name}/{Path(path).name}"


def pin_audio(wav: Path | str, folder: Path) -> str:
    """Copy a recording and its sidecar out of recent\\ into problems\\,
    so the audio behind a report survives the ring evicting it.

    Returns the relative path ("problems/<stem>.wav"), or "" when there
    was nothing to copy or the copy failed. Copying twice is a no-op: the
    same clip can be attached to two reports."""
    src = Path(wav)
    folder = Path(folder)
    try:
        if not src.name or not src.is_file():
            return ""
        folder.mkdir(parents=True, exist_ok=True)
        dst = folder / src.name
        if not dst.exists():
            shutil.copy2(src, dst)
        side = src.with_suffix(".json")
        if side.is_file() and not dst.with_suffix(".json").exists():
            shutil.copy2(side, dst.with_suffix(".json"))
        return _rel(folder, dst)
    except OSError as e:
        log.info("problems: could not pin the audio for a report (%s)", e)
        return ""


def pin_shot(folder: Path, ident: str, jpeg: bytes) -> str:
    """Write a screenshot the caller already encoded — bytes in, so
    nothing here needs an imaging library — and return its relative path,
    or "" if there was nothing to write or the write failed."""
    folder = Path(folder)
    if not jpeg:
        return ""
    try:
        folder.mkdir(parents=True, exist_ok=True)
        dst = folder / f"{_line(ident, 40) or 'shot'}.jpg"
        dst.write_bytes(bytes(jpeg))
        return _rel(folder, dst)
    except (OSError, TypeError, ValueError) as e:
        log.info("problems: could not pin the screenshot for a report (%s)", e)
        return ""


# ---------------------------------------------------------------------------
# reading the evidence back: where a shot is, and what it looks like small
# ---------------------------------------------------------------------------
#
# A shot is stored as "problems/<id>.jpg", relative to the folder's
# parent, and _rel above is the only place that convention is written
# down. Resolving it belongs here for the same reason: the dashboard
# should never have to know that the folder is called problems\\ or that
# the string is relative to the store, because the day either changes it
# would change in one file and be wrong in the other.

_THUMB_CACHE: dict[tuple, bytes] = {}
_THUMB_LOCK = threading.Lock()

# Enough for a screenful of rows plus the report box; past that the
# oldest half goes, which is cheaper than tracking real use and is only
# ever a re-decode, never a wrong picture — the key carries the mtime.
_THUMB_KEEP = 64


def _base(store_or_folder) -> Path | None:
    """What a relative shot path is resolved against: the app directory.

    A Store knows it as the parent of problems.json; a bare path is taken
    as the app directory itself, unless it is the problems\\ folder, in
    which case its parent is. Both are things a caller plausibly has in
    its hand, and neither should have to be converted first."""
    if store_or_folder is None:
        return None
    inner = getattr(store_or_folder, "path", None)
    if inner is not None:
        try:
            return Path(inner).parent
        except TypeError:
            return None
    try:
        path = Path(store_or_folder)
    except TypeError:
        return None
    return path.parent if path.name == FOLDER_NAME else path


def shot_path(store_or_folder, item_or_shot) -> Path | None:
    """The screenshot attached to a report, as a path that can be opened.

    Takes the store (or the app directory, or problems\\) and either a
    stored item or the "shot" string out of one. None means the report has
    no screenshot — which most reports do not, so None is the ordinary
    answer and not a failure. An absolute path is returned as it is, so a
    shot written down before the relative convention existed still
    opens."""
    shot = (item_or_shot.get("shot") if isinstance(item_or_shot, dict)
            else item_or_shot)
    shot = _text(shot).strip().replace("\\", "/")
    if not shot:
        return None
    try:
        path = Path(shot)
        if path.is_absolute():
            return path
        base = _base(store_or_folder)
        return path if base is None else base / path
    except (OSError, TypeError, ValueError):
        return None


def thumb(store_or_folder, item_or_shot, *,
          max_side: int = THUMB_MAX) -> bytes | None:
    """The attached screenshot as small PNG bytes, ready for Tk.

    He asked to SEE what got attached — in the report box before he sends
    it and on the row afterwards — and a screenshot is a screen, which is
    an order of magnitude too big for either. So it comes back scaled to
    fit max_side on its long side and encoded as PNG, because that is
    what tkinter.PhotoImage takes as data with no image library in the
    dashboard.

    None for a report with no screenshot, for a file that has been
    deleted, and for anything Pillow will not open — a missing picture is
    a row without a picture, never an exception into a redraw. Pillow is
    imported here rather than at the top so this module still imports on
    a machine that has not got it.

    Results are cached under (path, mtime, max_side): the Problems tab
    redraws every row on every scroll, and decoding the same JPEG a
    hundred times to draw the same 220 pixels is the one cost that would
    make the picture not worth having. The mtime in the key is what makes
    the cache safe — a shot rewritten in place gets a new key rather than
    a stale thumbnail."""
    path = shot_path(store_or_folder, item_or_shot)
    if path is None:
        return None
    try:
        mtime = path.stat().st_mtime_ns
    except OSError:
        return None
    try:
        side = max(16, int(max_side))
    except (TypeError, ValueError):
        side = THUMB_MAX
    key = (str(path), mtime, side)
    with _THUMB_LOCK:
        hit = _THUMB_CACHE.get(key)
    if hit is not None:
        return hit
    try:
        import io

        from PIL import Image

        with Image.open(path) as img:
            img.load()
            # A screenshot is RGB and Tk takes RGBA too; anything more
            # exotic (a palette, CMYK) is converted rather than refused.
            small = img if img.mode in ("RGB", "RGBA", "L") \
                else img.convert("RGB")
            # LANCZOS moved into Image.Resampling; asked for through
            # getattr so both Pillow generations work and neither is
            # pinned by this module.
            filt = getattr(getattr(Image, "Resampling", Image), "LANCZOS",
                           None)
            if filt is None:
                small.thumbnail((side, side))
            else:
                small.thumbnail((side, side), filt)
            buf = io.BytesIO()
            small.save(buf, format="PNG", optimize=True)
        png = buf.getvalue()
    except Exception as e:                # noqa: BLE001
        log.info("problems: could not make a thumbnail of %s (%s)",
                 path.name, e)
        return None
    with _THUMB_LOCK:
        if len(_THUMB_CACHE) >= _THUMB_KEEP:
            for old in list(_THUMB_CACHE)[:_THUMB_KEEP // 2]:
                _THUMB_CACHE.pop(old, None)
        _THUMB_CACHE[key] = png
    return png


# ---------------------------------------------------------------------------
# the store: reports on disk, shared with the dashboard
# ---------------------------------------------------------------------------

class Store:
    """problems.json, edited by two processes.

    A lock file beside it (msvcrt.locking on Windows) serialises the
    read-modify-write between the app and the dashboard; inside one
    process an RLock does the same between threads. Every write lands
    through a per-process temporary file and one rename, so a reader
    never sees half a file and two writers cannot destroy it (the shared
    temp name cost config.toml the whole file, 4 runs out of 4 — see
    config.py). A file that will not parse is read as empty rather than
    fatal: a broken store must cost reports, not dictation."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.lock_path = self.path.with_suffix(".lock")
        self.keep = KEEP_RESOLVED
        self.folder = self.path.with_name(FOLDER_NAME)
        self._lock = threading.RLock()

    # ---- the file ----

    def _load(self) -> dict:
        try:
            data = json.loads(self.path.read_text("utf-8"))
        except FileNotFoundError:
            return {"version": 1, "items": []}
        except Exception as e:            # noqa: BLE001
            log.warning("problems: problems.json unreadable (%s) — "
                        "starting empty", e)
            return {"version": 1, "items": []}
        items = data.get("items") if isinstance(data, dict) else None
        return {"version": 1,
                "items": [i for i in (items or []) if isinstance(i, dict)]}

    def _save(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(f"{self.path.name}.{os.getpid()}.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                       "utf-8")
        os.replace(tmp, self.path)

    @contextmanager
    def _locked(self):
        with self._lock:
            fd = None
            held = False
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                fd = os.open(self.lock_path, os.O_RDWR | os.O_CREAT)
                try:
                    import msvcrt
                    for _ in range(100):           # up to ~5 s
                        try:
                            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                            held = True
                            break
                        except OSError:
                            time.sleep(0.05)
                except ImportError:
                    pass
                if fd is not None and not held:
                    log.info("problems: problems.json lock busy — "
                             "writing anyway")
                yield
            finally:
                if fd is not None:
                    if held:
                        try:
                            import msvcrt
                            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
                        except Exception:  # noqa: BLE001
                            pass
                    os.close(fd)

    def _trim(self, data: dict) -> None:
        """Only resolved reports age out. An open one stays for as long as
        it takes him to fix it."""
        items = data["items"]
        done = [i for i in items if i.get("status") in RESOLVED]
        if len(done) > self.keep:
            extra = len(done) - self.keep
            oldest = sorted(done, key=lambda i: str(i.get("resolved")
                                                    or i.get("at") or ""))
            drop = {id(i) for i in oldest[:extra]}
            data["items"] = [i for i in items if id(i) not in drop]

    def _next_id(self, items: list[dict]) -> str:
        """A timestamp, with a -1/-2 suffix when a second already has a
        report in it — spool.py names recordings the same way."""
        taken = {str(i.get("id")) for i in items}
        base = time.strftime(_STAMP)
        ident, n = base, 1
        while ident in taken:
            ident = f"{base}-{n}"
            n += 1
        return ident

    # ---- reads ----

    def items(self, status: str | None = None) -> list[dict]:
        """Newest first. `status` filters to one of OPEN/FIXED/CLOSED;
        None is everything."""
        with self._lock:
            rows = list(self._load()["items"])
        if status is not None:
            rows = [i for i in rows if i.get("status") == status]
        rows.sort(key=lambda i: (str(i.get("at", "")), str(i.get("id", ""))),
                  reverse=True)
        return rows

    def get(self, ident: str) -> dict | None:
        return next((i for i in self.items() if i.get("id") == ident), None)

    def summary(self) -> dict:
        """What a header says: how many in each state, how many per
        surface, how many of the open ones carry a "fixed?" mark, and
        how long the oldest open one has been waiting.

        "maybe" is a count WITHIN "open", not beside it: a marked report
        is still open, so `open` alone is still the number of reports
        that need him."""
        out: dict = {OPEN: 0, FIXED: 0, CLOSED: 0, MAYBE: 0, "total": 0,
                     "where": {}, "oldest_open": "", "oldest_open_id": ""}
        oldest = None
        for item in self.items():
            status = str(item.get("status") or OPEN)
            out[status] = out.get(status, 0) + 1
            out["total"] += 1
            if status == OPEN:
                if suggested(item) is not None:
                    out[MAYBE] += 1
                where = str(item.get("where") or "?")
                out["where"][where] = out["where"].get(where, 0) + 1
                at = str(item.get("at", ""))
                if oldest is None or at < str(oldest.get("at", "")):
                    oldest = item
        if oldest is not None:
            out["oldest_open"] = str(oldest.get("at", ""))
            out["oldest_open_id"] = str(oldest.get("id", ""))
        return out

    def stamp(self) -> tuple:
        """(size, mtime_ns), or () when there is no file — the
        dashboard's change detector, without reading the file."""
        try:
            st = self.path.stat()
        except OSError:
            return ()
        return (st.st_size, st.st_mtime_ns)

    # ---- writes ----

    def add(self, report: dict) -> dict:
        """Store one report and hand back what was stored, with `id` and
        `at` filled in. `report` is expected to have been through clean()
        and context(); anything missing is defaulted here, so a caller
        that only has a line of text still gets a well-formed item.

        A new report never carries the "fixed?" mark, whatever `report`
        says: the item is built from named fields and MAYBE is not one of
        them. Nobody can have tried to fix a report that did not exist a
        moment ago, and the only way onto a report is suggest()."""
        item = {
            "id": "",
            "at": _iso(),
            "where": _line(report.get("where"), WHERE_MAX),
            "kind": (str(report.get("kind"))
                     if report.get("kind") in KINDS else KINDS[0]),
            "text": _body(report.get("text"), TEXT_MAX),
            "status": (str(report.get("status"))
                       if report.get("status") in STATUSES else OPEN),
            "resolved": None,
            "by": _line(report.get("by"), BY_MAX),
            "dictation": (report.get("dictation")
                          if isinstance(report.get("dictation"), dict)
                          else {}),
            "shot": _text(report.get("shot")).strip(),
            "env": (report.get("env")
                    if isinstance(report.get("env"), dict) else {}),
        }
        # Every string of a report goes through the redactor before it
        # is stored (D8, plan 4.5): a pasted key, a bearer, the phone
        # link. The report stays on this PC today; the copy that will
        # travel (chapter 7) is built from what is stored here.
        import redact
        item = redact.walk(item)
        try:
            with self._locked():
                data = self._load()
                item["id"] = self._next_id(data["items"])
                data["items"].append(item)
                self._trim(data)
                self._save(data)
        except OSError as e:
            log.warning("problems: could not save a report (%s)", e)
            if not item["id"]:
                item["id"] = time.strftime(_STAMP)
        return item

    def _edit(self, ident: str, **fields) -> bool:
        """Merge fields into one stored report. False means nothing
        changed — no such id, or the file could not be written."""
        try:
            with self._locked():
                data = self._load()
                found = next((i for i in data["items"]
                              if i.get("id") == ident), None)
                if found is None:
                    return False
                found.update(fields)
                self._save(data)
                return True
        except OSError as e:
            log.warning("problems: could not update %s (%s)", ident, e)
            return False

    def resolve(self, ident: str, status: str, by: str = "") -> bool:
        """Move one report to FIXED or CLOSED — or back to OPEN, which
        clears the resolution date and reopens the question.

        False means nothing changed: no such id, an unknown status, or the
        file could not be written. It never raises, because the dashboard
        calls this from a request handler.

        Whatever the new status, the "fixed?" mark comes off. To FIXED it
        has been answered — by him, which is the only way it gets
        answered. To CLOSED the question is moot. Back to OPEN the report
        starts clean: a claim made before it was reopened is a claim
        about a report he has since said is not fixed."""
        if status not in STATUSES:
            log.warning("problems: unknown status %r — nothing resolved",
                        status)
            return False
        try:
            with self._locked():
                data = self._load()
                found = next((i for i in data["items"]
                              if i.get("id") == ident), None)
                if found is None:
                    return False
                found["status"] = status
                found["resolved"] = None if status == OPEN else _iso()
                found["by"] = _line(by, BY_MAX)
                found.pop(MAYBE, None)
                self._trim(data)
                self._save(data)
                return True
        except OSError as e:
            log.warning("problems: could not resolve %s (%s)", ident, e)
            return False

    def suggest(self, ident: str, by: str = "", note: str = "") -> bool:
        """Put the "fixed?" mark on one OPEN report: `by` believes a
        change fixed it, and `note` is the one line telling him what to
        try. The status does not move — see the module docstring for the
        three reports that were closed on 2026-09-12 by a routine that
        believed and did not ask.

        False means nothing changed: no such id, a report that is not
        open (there is nothing to suggest about an answered one), or the
        file could not be written. Never raises, resolve()'s contract.
        Suggesting twice replaces the mark, because the newer claim is
        the one about the code as it is now."""
        try:
            with self._locked():
                data = self._load()
                found = next((i for i in data["items"]
                              if i.get("id") == ident), None)
                if found is None:
                    return False
                if (found.get("status") or OPEN) != OPEN:
                    log.info("problems: %s is %s — nothing to suggest",
                             ident, found.get("status"))
                    return False
                found[MAYBE] = {"by": _line(by, BY_MAX), "at": _iso(),
                                "note": _line(note, MAYBE_MAX)}
                self._save(data)
                return True
        except OSError as e:
            log.warning("problems: could not mark %s fixed? (%s)", ident, e)
            return False

    def unsuggest(self, ident: str) -> bool:
        """Take the "fixed?" mark off without answering anything — the
        report is exactly as open as it was. For a claim withdrawn: the
        change was reverted, or he said in the chat that it is not fixed
        and the row should stop saying it might be.

        False means nothing changed: no such id, no mark to take off, or
        the file could not be written."""
        try:
            with self._locked():
                data = self._load()
                found = next((i for i in data["items"]
                              if i.get("id") == ident), None)
                if found is None or MAYBE not in found:
                    return False
                found.pop(MAYBE, None)
                self._save(data)
                return True
        except OSError as e:
            log.warning("problems: could not unmark %s (%s)", ident, e)
            return False

    def remove(self, ident: str) -> dict | None:
        """Throw one report away, and hand back what was thrown.

        None means nothing changed: no such id, or the file could not be
        written — resolve()'s contract, for resolve()'s reason (a
        dashboard button is the caller and a traceback there is a dead
        window). The item comes back rather than a bool so the surface
        that asked can say what it just deleted, and so a caller that
        wants an undo has the row in its hand.

        THE EVIDENCE STAYS ON DISK. The screenshot and the copied wav
        pinned into problems\\ are left exactly where they are, which is
        already what happens when _trim ages an answered report out. A
        row leaving the list is him tidying a list; making a recording of
        his own voice unrecoverable is a different act, and it is not one
        a ✕ on a row should be able to do.

        ASKING IS THE CALLER'S JOB, and it is not optional — see the
        module docstring. This method deletes.
        """
        try:
            with self._locked():
                data = self._load()
                found = next((i for i in data["items"]
                              if i.get("id") == ident), None)
                if found is None:
                    return None
                data["items"] = [i for i in data["items"]
                                 if i.get("id") != ident]
                self._save(data)
                return found
        except OSError as e:
            log.warning("problems: could not delete %s (%s)", ident, e)
            return None


# ---------------------------------------------------------------------------
# the one call a caller makes
# ---------------------------------------------------------------------------

def record(app_dir: Path, report: dict, *, cfg=None, last: dict | None = None,
           jpeg: bytes | None = None) -> dict:
    """Take his typed line and file a complete report under app_dir.

    Cleans the text, collects the context, copies the last recording and
    the screenshot into problems\\, stores the item and returns it. Only
    clean()'s ValueError escapes; everything else degrades to a report
    with less evidence in it."""
    app_dir = Path(app_dir)
    fields = clean(report)                 # ValueError on an empty line
    folder = app_dir / FOLDER_NAME
    store = Store(app_dir / STORE_NAME)
    extra = context(where=fields["where"], cfg=cfg, last=last,
                    app_dir=app_dir)
    got = dict(extra["dictation"])
    if got.get("wav"):
        pinned = pin_audio(got["wav"], folder)
        if pinned:
            got["wav"] = pinned
    item = store.add({**fields, "dictation": got, "env": extra["env"]})
    if jpeg:
        shot = pin_shot(folder, item["id"], jpeg)
        if shot:
            item["shot"] = shot
            if not store._edit(item["id"], shot=shot):
                log.warning("problems: report %s saved without its "
                            "screenshot path", item["id"])
    log.info("problems: filed %s (%s) from %s", item["id"], item["kind"],
             item["where"] or "?")
    return item


# ---------------------------------------------------------------------------
# the copy that travels (DISTRIBUTION_PLAN.md 7.6, 8.4, 8.8; D16, D33)
# ---------------------------------------------------------------------------
#
# A report is filed on this PC exactly as above, always — that copy is
# his, and nothing here touches what it holds. "Send to the developer"
# makes a SECOND thing: the payload, which is the one row problem_reports
# takes and the files the `reports` bucket takes and nothing else, built
# from the stored item and four toggles, shown to him whole before it goes
# (the Preview — "this is everything that leaves your PC"), and then
# written into problems\outbox\ for sb.py to carry. The stored item
# remembers where that copy is: `sent` is one of SENT_STATES, `sent_id`
# the uuid the server row has, `attach` the toggles as he left them, so
# the Problems row can say "waiting to send", "sent" or "failed: <why>"
# and the Preview can be opened again from the row.
#
# The four toggles are ABOUT THE COPY THAT TRAVELS, not about the local
# report: the screenshot OFF by default (a picture of the screen is the
# one piece that may hold somebody else's words), the recording OFF, the
# transcript ON only for a `wrong` (it is what such a report is about),
# the settings ON (model names and switches, never a key — env() is a
# whitelist and the server CHECKs the same list, 7.8). With the settings
# toggle off the row still carries the machine facts every row has
# (ENV_ALWAYS), because "which version, which tier" is what makes a
# report answerable at all.

ATTACH = ("shot", "recording", "transcript", "settings")
ATTACH_WORDS = {"shot": "Screenshot", "recording": "Recording",
                "transcript": "Transcript text",
                "settings": "Settings snapshot"}
PREVIEW, QUEUED, SENT, FAILED = "preview", "queued", "sent", "failed"
SENT_STATES = ("", PREVIEW, QUEUED, SENT, FAILED)
ENV_ALWAYS = ("version", "os_build", "consents", "gpu", "tier", "branch")
#: The files the bucket takes, by toggle (8.4's path convention names).
_FILE_NAMES = {"shot": "shot.jpg", "recording": "dictation.wav",
               "transcript": "sidecar.json"}
OUTBOX_NAME = "outbox"
#: How a Problems row words the copy's state — one place, both surfaces.
SENT_WORDS = {PREVIEW: "not sent yet — preview it", QUEUED: "waiting to send",
              SENT: "sent to the developer", FAILED: "could not be sent"}


def attach_defaults(kind: str) -> dict:
    """7.6's defaults for the copy that travels, by kind."""
    return {"shot": False, "recording": False,
            "transcript": kind == "wrong", "settings": True}


def _clean_attach(attach) -> dict:
    """Four booleans, whatever was handed in."""
    got = attach if isinstance(attach, dict) else {}
    return {name: bool(got.get(name)) for name in ATTACH}


def _wav_of(item: dict, app_dir) -> Path | None:
    """The pinned recording behind a stored report, if it is on disk."""
    got = item.get("dictation") if isinstance(item.get("dictation"), dict) else {}
    wav = _text(got.get("wav")).strip().replace("\\", "/")
    if not wav:
        return None
    try:
        path = Path(wav)
        if not path.is_absolute():
            base = _base(app_dir)
            path = path if base is None else base / path
        return path if path.is_file() else None
    except (OSError, TypeError, ValueError):
        return None


def _transcript_of(item: dict) -> tuple[str | None, str | None]:
    """dictation_raw and dictation_final as the row carries them: the
    stored strings, cut to the column's length, None when absent."""
    got = item.get("dictation") if isinstance(item.get("dictation"), dict) else {}
    raw = _body(got.get("raw"), 4000) or None
    final = _body(got.get("final") or got.get("text"), 4000) or None
    return raw, final


def evidence(item: dict, app_dir) -> dict:
    """What a stored report could send, with a byte size for each toggle
    — the strip's four rows. A piece that is not there is 0 bytes, and
    the surface draws its toggle greyed. Never raises."""
    out = {name: 0 for name in ATTACH}
    try:
        shot = shot_path(app_dir, item)
        if shot is not None and shot.is_file():
            out["shot"] = shot.stat().st_size
    except OSError:
        pass
    try:
        wav = _wav_of(item, app_dir)
        if wav is not None:
            out["recording"] = wav.stat().st_size
    except OSError:
        pass
    raw, final = _transcript_of(item)
    out["transcript"] = len((raw or "").encode("utf-8")) + len((final or "").encode("utf-8"))
    try:
        wav = _wav_of(item, app_dir)
        side = wav.with_suffix(".json") if wav is not None else None
        if side is not None and side.is_file():
            out["transcript"] += side.stat().st_size
    except OSError:
        pass
    env = item.get("env") if isinstance(item.get("env"), dict) else {}
    settings = {k: v for k, v in env.items() if k not in ENV_ALWAYS}
    out["settings"] = len(json.dumps(settings, ensure_ascii=False).encode("utf-8"))
    return out


def sizes_before_filing(*, jpeg: bytes | None = None, last: dict | None = None,
                        cfg=None, app_dir=None) -> dict:
    """The same four sizes for a report that is still being typed — the
    hotkey card has the JPEG bytes, `last` and cfg in its hand and no
    stored item yet. Never raises."""
    item = {"shot": "", "dictation": {}, "env": {}}
    try:
        item["dictation"] = dictation(last, app_dir)
        item["env"] = env(cfg)
    except Exception:                     # noqa: BLE001
        pass
    out = evidence(item, app_dir)
    out["shot"] = len(jpeg) if jpeg else 0
    return out


def payload(item: dict, attach, *, app_dir) -> tuple[dict, list[dict]]:
    """The exact row the server takes and the files that go with it, for
    one stored report and the toggles as ticked — what the Preview shows
    and what the outbox carries, from the same call so the two cannot
    differ. Every string has been through the redactor once at add() and
    goes through it again here (a key-shaped string shows as its
    placeholder, so he can see the filter exists). Files are named as
    8.4 names them; each entry is {"name", "path", "bytes"}."""
    import redact
    import uuid as uuid_mod

    attach = _clean_attach(attach)
    env_all = item.get("env") if isinstance(item.get("env"), dict) else {}
    env_row = dict(env_all) if attach["settings"] else {
        k: v for k, v in env_all.items() if k in ENV_ALWAYS}
    row = {
        "id": str(item.get("sent_id") or uuid_mod.uuid4()),
        "kind": (str(item.get("kind")) if item.get("kind") in KINDS
                 else KINDS[0]),
        "place": _line(item.get("where"), 120),
        "text": _body(item.get("text"), TEXT_MAX),
        "app_version": _line(env_all.get("version"), 32),
        "os_build": _line(env_all.get("os_build"), 32),
        "tier": (str(env_all.get("tier")) if env_all.get("tier")
                 in ("gpu", "gpu_small", "cpu", "cloud") else ""),
        "env": env_row,
    }
    if attach["transcript"]:
        raw, final = _transcript_of(item)
        if raw is not None:
            row["dictation_raw"] = raw
        if final is not None:
            row["dictation_final"] = final
    files: list[dict] = []
    if attach["shot"]:
        shot = shot_path(app_dir, item)
        if shot is not None and shot.is_file():
            files.append({"name": _FILE_NAMES["shot"], "path": str(shot),
                          "bytes": shot.stat().st_size})
    wav = _wav_of(item, app_dir)
    if attach["recording"] and wav is not None:
        files.append({"name": _FILE_NAMES["recording"], "path": str(wav),
                      "bytes": wav.stat().st_size})
    if attach["transcript"] and wav is not None:
        side = wav.with_suffix(".json")
        if side.is_file():
            files.append({"name": _FILE_NAMES["transcript"], "path": str(side),
                          "bytes": side.stat().st_size})
    row["attachments"] = [f["name"] for f in files]
    return redact.walk(row), files


def preview_text(row: dict) -> str:
    """The row as the Preview prints it: pretty JSON, keys in the order
    the server's columns have, Hebrew kept as Hebrew."""
    return json.dumps(row, ensure_ascii=False, indent=2)


def outbox_dir(app_dir) -> Path:
    """problems\\outbox\\ under the app directory: paths.OUTBOX_DIR's own
    shape (the same in both layouts), so a test's scratch root gets the
    same folder the product's DATA_DIR does. sb.py reads paths.OUTBOX_DIR
    and the two meet there."""
    base = _base(app_dir)
    return (Path(base) if base is not None else paths.DATA_DIR) / FOLDER_NAME / OUTBOX_NAME


def queue(store, item: dict, attach, *, app_dir) -> Path | None:
    """Send: write the payload into the outbox and mark the stored report
    QUEUED. The files are COPIED beside the payload (outbox\\<uuid>\\),
    not linked, so a report he deletes from the list a minute later — or
    a purge of its evidence — cannot pull a half-sent upload out from
    under sb.py; the copies go when the report is sent. Returns the
    payload's path, or None when nothing could be written (the report
    stays as it was, and the row says so)."""
    attach = _clean_attach(attach)
    row, files = payload(item, attach, app_dir=app_dir)
    box = outbox_dir(app_dir)
    rid = row["id"]
    try:
        folder = box / rid
        folder.mkdir(parents=True, exist_ok=True)
        carried = []
        for f in files:
            dst = folder / f["name"]
            shutil.copy2(f["path"], dst)
            carried.append({"name": f["name"], "path": str(dst)})
        body = dict(row)
        body["attachments"] = carried
        target = box / f"{rid}.json"
        tmp = target.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_text(json.dumps(body, ensure_ascii=False, indent=2), "utf-8")
        os.replace(tmp, target)
    except OSError as e:
        log.warning("problems: could not queue %s for upload (%s)",
                    item.get("id"), e)
        return None
    if not store._edit(str(item.get("id")), sent=QUEUED, sent_id=rid,
                       sent_why="", attach=attach):
        log.warning("problems: %s queued but the row could not be marked",
                    item.get("id"))
    log.info("problems: %s queued for upload as %s (%s)", item.get("id"), rid,
             ", ".join(row["attachments"]) or "no files")
    return target


def mark_preview(store, ident: str, attach) -> bool:
    """Send ticked on the card: the report is filed here as always and
    waits for his look at the Preview before any copy is made. The
    toggles ride on the row, so the dashboard — another process, when
    the card was the hotkey's — opens the Preview with them as he left
    them."""
    return store._edit(ident, sent=PREVIEW, sent_id="", sent_why="",
                       attach=_clean_attach(attach))


def keep_local(store, ident: str) -> bool:
    """Keep on this PC, after a preview: the copy is not made and the
    row forgets it was ever going to be."""
    return store._edit(ident, sent="", sent_id="", sent_why="")


def awaiting_preview(store) -> dict | None:
    """The newest report waiting for its Preview, or None — what the
    dashboard looks for when it comes up after the hotkey card."""
    rows = [i for i in store.items() if i.get("sent") == PREVIEW]
    return rows[0] if rows else None


def mark_sent(store, rid: str) -> bool:
    """sb.py's on_sent: the row whose copy just went up."""
    return _mark_by_uuid(store, rid, sent=SENT, sent_why="")


def mark_failed(store, rid: str, why: str) -> bool:
    """A poison report (8.8): the server's reason, kept short."""
    return _mark_by_uuid(store, rid, sent=FAILED, sent_why=_line(why, 200))


def _mark_by_uuid(store, rid: str, **fields) -> bool:
    found = next((i for i in store.items() if str(i.get("sent_id")) == rid), None)
    return bool(found) and store._edit(str(found.get("id")), **fields)


def sync_outbox(store, *, app_dir) -> int:
    """Read the outbox's verdicts back into the rows: a QUEUED report
    whose payload is gone was sent (sb.py unlinks it, and the app's
    process may have done that while this one was not looking); one
    with a .failed beside it failed, with the reason the file holds.
    Returns how many rows changed. Never raises."""
    changed = 0
    box = outbox_dir(app_dir)
    for item in store.items():
        if item.get("sent") != QUEUED or not item.get("sent_id"):
            continue
        rid = str(item["sent_id"])
        try:
            failed = box / f"{rid}.failed"
            if failed.is_file():
                why = failed.read_text("utf-8", errors="replace").strip()
                if mark_failed(store, rid, why):
                    changed += 1
            elif not (box / f"{rid}.json").exists():
                if mark_sent(store, rid):
                    changed += 1
        except OSError:
            continue
    return changed


def sent_line(item: dict) -> str:
    """One line for the Problems row about the copy that travels, or ""
    for a report that stays here."""
    state = str(item.get("sent") or "")
    if state not in SENT_WORDS:
        return ""
    line = SENT_WORDS[state]
    why = _line(item.get("sent_why"), 120)
    return f"{line}: {why}" if state == FAILED and why else line


# ---------------------------------------------------------------------------
# the weekly read
# ---------------------------------------------------------------------------

def _dict_line(got: dict) -> list[str]:
    """The dictation evidence, as the lines it is worth reading: raw to
    final, then how it was decoded."""
    if not got:
        return []
    out = []
    raw = str(got.get("raw") or "")
    final = str(got.get("final") or got.get("text") or "")
    if raw or final:
        out.append(f"  - `{raw}` → `{final}`")
    facts = []
    if got.get("id"):
        facts.append(f"clip `{got['id']}`")
    if got.get("backend"):
        facts.append(str(got["backend"]))
    if got.get("language"):
        facts.append(str(got["language"]))
    if got.get("seconds") not in (None, ""):
        try:
            facts.append(f"{float(got['seconds']):.1f}s")
        except (TypeError, ValueError):
            pass
    if got.get("last_error"):
        facts.append(f"error: {got['last_error']}")
    if facts:
        out.append("  - " + " · ".join(facts))
    if got.get("wav"):
        out.append(f"  - wav: `{got['wav']}`")
    return out


def _env_line(row: dict) -> str:
    bits = [f"{k}={row[k]}" for k in ("backend", "local_model", "polish_when",
                                      "branch")
            if row.get(k) not in (None, "")]
    return "  - env: " + ", ".join(bits) if bits else ""


def _maybe_line(mark: dict | None) -> str:
    """The "fixed?" mark as one bullet: who thinks so, since when, and
    what to try. Empty for a report nobody has made that claim about.
    The word is `fixed?` and not `maybe` because it is what the tab
    says, and the agent reading this file and the owner reading the tab
    must be talking about the same thing."""
    if mark is None:
        return ""
    facts = [b for b in (mark.get("by"), mark.get("at")) if b]
    who = f" ({', '.join(facts)})" if facts else ""
    note = mark.get("note") or ""
    return f"  - fixed?{who}" + (f": {note}" if note else "") \
        + " — waiting for his word"


def _item_lines(item: dict) -> list[str]:
    mark = suggested(item)
    head = (f"- **{item.get('at', '')}** · {item.get('kind', '')} · "
            f"`{item.get('id', '')}`"
            # On the head line too, so a reader skimming the headings
            # sees which open reports are waiting on him and not on the
            # code — the same word the tab draws beside the kind.
            + (" · **fixed?**" if mark is not None else ""))
    out = [head, ""]
    for line in str(item.get("text", "")).split("\n"):
        out.append(f"  {line}" if line else "")
    out.append("")
    maybe_line = _maybe_line(mark)
    if maybe_line:
        out.append(maybe_line)
    out.extend(_dict_line(item.get("dictation") or {}))
    if item.get("shot"):
        out.append(f"  - shot: `{item['shot']}`")
    env_line = _env_line(item.get("env") or {})
    if env_line:
        out.append(env_line)
    out.append("")
    return out


def digest(store: Store, path: Path) -> Path:
    """Write problems.md — open reports first, newest first, grouped by
    where they were reported from, each with the evidence the app
    attached; then a short list of what has been resolved.

    Written from scratch every call. Returns the path, even when the
    write failed, because the caller has nothing useful to do about it
    and a report must not take dictation down."""
    path = Path(path)
    counts = store.summary()
    # "fixed?" is named only when there is one, and between open and
    # fixed — the same line the tab's header draws — because it is a
    # part of open that is waiting on him rather than a state of its own.
    maybe = counts.get(MAYBE, 0)
    lines = [
        "# Problems",
        "",
        f"{counts.get(OPEN, 0)} open · "
        + (f"{maybe} fixed? · " if maybe else "")
        + f"{counts.get(FIXED, 0)} fixed · "
        f"{counts.get(CLOSED, 0)} closed · written "
        f"{time.strftime('%Y-%m-%d %H:%M:%S')}",
        "",
    ]
    open_items = store.items(OPEN)
    lines += ["## Open", ""]
    if not open_items:
        lines += ["Nothing open.", ""]
    else:
        groups: dict[str, list[dict]] = {}
        for item in open_items:            # already newest first
            groups.setdefault(str(item.get("where") or "?"), []).append(item)
        for where, rows in groups.items():
            lines += [f"### {where} ({len(rows)})", ""]
            for item in rows:
                lines += _item_lines(item)
    done = [i for i in store.items() if i.get("status") in RESOLVED]
    lines += ["## Resolved", ""]
    if not done:
        lines += ["Nothing resolved yet.", ""]
    else:
        for item in sorted(done, key=lambda i: str(i.get("resolved") or ""),
                           reverse=True):
            lines.append(
                f"- {item.get('resolved') or item.get('at', '')} · "
                f"{item.get('status', '')} · {item.get('where') or '?'} · "
                f"{_line(item.get('text'), 100)}"
                + (f" ({item['by']})" if item.get("by") else "")
                # Named here too, for the same reason as on an open item:
                # the path is relative to problems.md's own folder, so
                # reading the line is enough to open the picture.
                + (f" · shot `{item['shot']}`" if item.get("shot") else ""))
        lines.append("")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(lines).rstrip() + "\n", "utf-8")
    except OSError as e:
        log.warning("problems: could not write %s (%s)", path.name, e)
    return path
