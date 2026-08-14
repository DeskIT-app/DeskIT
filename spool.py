"""Durable holding area for recordings that could not be transcribed yet.

The original failure mode this fixes: a 429 (or any backend error) made the
worker drop the WAV on the floor, so 20 seconds of speech vanished with
nothing but an error cue. Now every failed recording is written here first
and only deleted once its text has actually been produced.

The directory survives restarts on purpose — audio captured while the daily
quota was spent is still there tomorrow, and `--drain` turns it into text.
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path

log = logging.getLogger("app")

STAMP = "%Y%m%d-%H%M%S"


class SpooledItem:
    """One saved recording: the WAV plus the sidecar JSON describing it."""

    def __init__(self, wav_path: Path):
        self.wav_path = wav_path
        self.meta_path = wav_path.with_suffix(".json")

    @property
    def meta(self) -> dict:
        try:
            return json.loads(self.meta_path.read_text("utf-8"))
        except Exception:
            return {}

    @property
    def seconds(self) -> float:
        return float(self.meta.get("seconds", 0.0))

    def read(self) -> bytes:
        return self.wav_path.read_bytes()

    def bump(self, note: str) -> None:
        """Record another failed attempt without losing the audio."""
        meta = self.meta
        meta["attempts"] = int(meta.get("attempts", 0)) + 1
        meta["last_error"] = note
        meta["last_attempt"] = time.strftime("%Y-%m-%d %H:%M:%S")
        try:
            self.meta_path.write_text(json.dumps(meta, ensure_ascii=False,
                                                 indent=2), "utf-8")
        except OSError:
            pass

    def discard(self) -> None:
        """Transcribed successfully (or given up on) — remove both files."""
        for p in (self.wav_path, self.meta_path):
            try:
                p.unlink()
            except OSError:
                pass

    def __repr__(self) -> str:
        return f"<spooled {self.wav_path.name} {self.seconds:.1f}s>"


class Spool:
    def __init__(self, directory: Path, keep: int = 100):
        self.dir = directory
        self.keep = keep

    def save(self, wav: bytes, seconds: float, note: str,
             extra: dict | None = None) -> SpooledItem:
        """`extra` is merged into the sidecar. Used by the recent-recordings
        ring (see main.py) to store the transcript alongside its audio, which
        is what later turns a user correction into an (audio, truth) pair
        that hotword changes can actually be measured against."""
        self.dir.mkdir(parents=True, exist_ok=True)
        stem = f"{time.strftime(STAMP)}-{int(seconds * 10):04d}"
        wav_path = self.dir / f"{stem}.wav"
        n = 1
        while wav_path.exists():           # same-second recordings
            wav_path = self.dir / f"{stem}-{n}.wav"
            n += 1
        wav_path.write_bytes(wav)
        item = SpooledItem(wav_path)
        item.meta_path.write_text(json.dumps({
            "seconds": round(seconds, 2),
            "saved": time.strftime("%Y-%m-%d %H:%M:%S"),
            "attempts": 1,
            "last_error": note,
            **(extra or {}),
        }, ensure_ascii=False, indent=2), "utf-8")
        self._trim()
        return item

    def update(self, item: SpooledItem, **fields) -> None:
        """Merge fields into an item's sidecar, leaving the audio alone."""
        meta = item.meta
        meta.update(fields)
        try:
            item.meta_path.write_text(json.dumps(meta, ensure_ascii=False,
                                                 indent=2), "utf-8")
        except OSError as e:
            log.warning("could not update %s: %s", item.meta_path.name, e)

    def pending(self) -> list[SpooledItem]:
        """Oldest first — speech is replayed in the order it was spoken."""
        if not self.dir.exists():
            return []
        return [SpooledItem(p) for p in sorted(self.dir.glob("*.wav"))]

    def _trim(self) -> None:
        """Never let the spool grow without bound; drop the oldest."""
        items = self.pending()
        for item in items[:max(0, len(items) - self.keep)]:
            log.warning("spool full — dropping oldest recording %s",
                        item.wav_path.name)
            item.discard()
