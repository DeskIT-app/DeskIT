"""A stamp, said the way the rows say it: a big word and a small one.

Today is the clock ("21:14" / "today"), this week is the day name
("Mon" / "22 Sep"), older is the date ("15 Sep" / "2026"). Nothing here
guesses a locale: the window is English (AGENTS: Tk has no bidi, and the
web desk keeps the chrome English too), so the days and months are the
three-letter English ones.
"""
from __future__ import annotations

import re
import time
from datetime import date, datetime

DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def parse(stamp) -> datetime | None:
    """Every stamp shape this repo writes: "2026-09-23 21:14:03",
    "2026-09-23T21:14:03Z" (the server), "20260923-211403" (a wav's
    stem), and a float of seconds."""
    if isinstance(stamp, (int, float)) and stamp > 0:
        return datetime.fromtimestamp(float(stamp))
    text = str(stamp or "").strip()
    if not text:
        return None
    text = text.replace("T", " ").replace("Z", "").split("+")[0].split(".")[0]
    for shape in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(text.strip(), shape)
        except ValueError:
            pass
    m = re.match(r"^(\d{8})[-_ ](\d{6})", text)
    if m:
        try:
            return datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S")
        except ValueError:
            return None
    return None


def words(stamp, now: datetime | None = None) -> tuple[str, str]:
    """(big, small) for the time column."""
    when = parse(stamp)
    if when is None:
        return ("", "")
    now = now or datetime.now()
    days = (now.date() - when.date()).days
    if days == 0:
        return (when.strftime("%H:%M"), "today")
    if days == 1:
        return (when.strftime("%H:%M"), "yesterday")
    if 2 <= days <= 6:
        return (DAYS[when.weekday()], day_month(when))
    return (day_month(when), str(when.year) if when.year != now.year else "")


def day_month(when: datetime | date) -> str:
    return f"{when.day} {MONTHS[when.month - 1]}"


def sortable(stamp) -> str:
    when = parse(stamp)
    return when.strftime("%Y-%m-%d %H:%M:%S") if when else ""


def ago(stamp, now: datetime | None = None) -> str:
    """"3 days", "2 hours" — for a fact line, never for the time column."""
    when = parse(stamp)
    if when is None:
        return ""
    seconds = max(0, ((now or datetime.now()) - when).total_seconds())
    for size, word in ((86400, "day"), (3600, "hour"), (60, "minute")):
        n = int(seconds // size)
        if n:
            return f"{n} {word}" + ("s" if n != 1 else "")
    return "just now"


def stamp_now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")
