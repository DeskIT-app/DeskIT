"""The per-user files across versions — DISTRIBUTION_PLAN.md 11.10 (D2, D21).

`state.json` carries `config_version`, an integer that starts at 1;
`version.CONFIG_VERSION` is what this build writes and
`version.MIN_CONFIG_VERSION` the oldest it can bring forward (published
as `min_config_version` in latest.json, so a copy too old for a release
is told to install an intermediate one instead of the download).

STEPS is the ordered list: `(number, function)`, the function's one-line
docstring saying what changed. `apply()` runs, at the first start after
an update and before anything else reads the config, every step above
the file's version, in order, and writes `config_version` only after
all of them succeeded. A failing step leaves both files as they were,
says so once in the log, and never loops — the next start tries again,
and until then the app runs on the files it has (a step may rename or
split a key, move a store inside DATA_DIR, add a consent kind; it never
deletes personal data and never touches Credential Manager except
through secretstore).

The owner's legacy `config.toml` is not a step: `--migrate` (migrate.py)
is explicit, never automatic (D4), and sets `config_version` to the
current value when it finishes. Nothing to bring forward yet: the first
shipped version writes 1.
"""
from __future__ import annotations

import logging

import config as config_mod
import paths
import version

log = logging.getLogger("app")

def _sync_follows_the_account() -> None:
    """The words-and-settings sync goes with the account (2026-09-20):
    a copy that signed in before this build never saw the Ready page's
    switch and holds no settings_sync row — it is granted now, with
    the card's current text_version, the way the sign-in press grants
    it today. Not signed in, or the row already there (granted or since
    withdrawn and re-granted), nothing happens; a copy that withdrew the
    sync AFTER this step ran is never touched again — steps run once."""
    import privacy
    if privacy.consent("account") is not None and privacy.consent("settings_sync") is None:
        import consent_card as cc
        privacy.grant("settings_sync", cc.card_for("settings_sync")["text_version"])


def _history_follows_the_sync() -> None:
    """The two syncs are one switch (2026-09-20 afternoon): a copy that
    signed in under the earlier build holds the words-and-settings
    consent and no history_sync row — the Said page there stayed this
    PC's own while the account's other PC showed another. Granted now
    where the sync consent is, with the card's current text_version,
    the way the sign-in press grants both today (privacy.SYNC_KINDS).
    No sync consent (withdrawn, or never signed in), or the row already
    there, nothing happens — and a withdrawal after this step ran is
    never undone, because steps run once."""
    import privacy
    if privacy.consent("settings_sync") is not None and privacy.consent("history_sync") is None:
        import consent_card as cc
        privacy.grant("history_sync", cc.card_for("history_sync")["text_version"])


#: (config_version this step PRODUCES, the step). Append, never reorder.
STEPS: list[tuple[int, object]] = [(2, _sync_follows_the_account),
                                   (3, _history_follows_the_sync)]


def current() -> int:
    """The files' version: 1 for a copy that never wrote one."""
    try:
        state = config_mod.read_state(paths.STATE_FILE)
        return int(state.get("config_version") or 1)
    except Exception:                                        # noqa: BLE001
        return 1


def _stamped() -> bool:
    """Is config_version written at all? A copy that never wrote one is
    1 by convention and gets the stamp on its first start, so --diagnose
    and the Update row read a number rather than a convention."""
    try:
        return "config_version" in config_mod.read_state(paths.STATE_FILE)
    except Exception:                                        # noqa: BLE001
        return False


def pending(have: int | None = None) -> list[tuple[int, object]]:
    have = current() if have is None else have
    return [(n, fn) for n, fn in STEPS if n > have]


def apply() -> str | None:
    """Run the pending steps. Returns None when the files are current
    (or were brought current), else one sentence naming the step that
    failed — the files then stay as they were."""
    have = current()
    steps = pending(have)
    if not steps and have >= version.CONFIG_VERSION and _stamped():
        return None
    for number, step in steps:
        try:
            step()
        except Exception as e:                               # noqa: BLE001
            what = (step.__doc__ or "").strip().splitlines()[0] if step.__doc__ else step.__name__
            log.warning("settings could not be upgraded at step %d (%s): %s — running "
                        "on the files as they are; the next start tries again",
                        number, what, e)
            return f"settings could not be upgraded (step {number}: {what})"
    try:
        config_mod.save({"config_version": version.CONFIG_VERSION})
    except Exception as e:                                   # noqa: BLE001
        log.warning("config_version could not be written: %s", e)
        return "config_version could not be written"
    if steps:
        log.info("settings upgraded from config_version %d to %d (%d step(s))",
                 have, version.CONFIG_VERSION, len(steps))
    return None


def too_old_for(min_config_version: int) -> bool:
    """A release whose min_config_version is above this copy's files:
    the Update row says 'install the intermediate version first'."""
    return current() < int(min_config_version or 1)
