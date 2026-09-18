"""Carrying a pre-2026-09-17 copy into the layered layout, and starting over.

Two commands, both explicit, neither ever run by the app on its own
(DISTRIBUTION_PLAN.md chapter 3.8, decisions D4 and D30):

``main.py --migrate [config.toml or folder]``
    Reads the old single ``config.toml`` and writes what DIFFERS from
    ``defaults.toml`` into the two per-user files: machine things
    (positions, the microphone, the voice, the port) into ``state.json``,
    everything else into ``settings.toml``. Keys the new build no longer
    knows are listed and dropped, not carried. Given a FOLDER instead of
    a file (an old checkout, when the installed copy is set up), the
    personal stores in it are COPIED into ``DATA_DIR`` as well — copied,
    never moved: on the owner's machine the checkout keeps being DeskIT
    Dev and keeps its own data (D30). The joined stores travel by file
    name, so a ``recent\\`` clip is still the id ``review.json`` and a
    problem report point at. A ``.env`` in that folder (or beside the
    app) has its ``GROQ_API_KEY`` / ``GEMINI_API_KEY`` copied into Windows
    Credential Manager (secretstore.py, D3) unless a key is already there;
    the file itself is left for the person to delete, and a
    ``CEREBRAS_API_KEY`` line is reported as no longer read.

``main.py --reset-data --yes``
    The owner's own wish for his first day on the new layout, and the
    "start over" a person can ask for: delete everything the app learned
    or recorded — vocabulary, history, recordings, proposals, reports,
    caches — and keep ONLY the settings (``settings.toml``, ``state.json``,
    the keys). Refuses without ``--yes`` and prints what it would remove.

Both refuse while the app is running: the stores must not change under
a live process, and the app holds ``vocab.json`` in memory and would
write it straight back.
"""
from __future__ import annotations

import shutil
import sys
import tomllib
from pathlib import Path

import config as config_mod
import paths

#: Keys the layered build knows but does not want carried from an old
#: file — retired sections and settings (chapter 3.8 step 5).
DROPPED_PREFIXES = ("tests.",)
DROPPED_KEYS = frozenset({"lookup.dwell_ms",
                          # the screenshot cloud gate is [privacy]
                          # cloud_screenshots since 2026-09-17, opened
                          # only by its consent card (chapter 5)
                          "visual_qa.allow_screenshot_upload"})

#: The personal stores, by paths.py name, in the order a reset lists them.
#: Folders are removed whole; files by name, with their rotated siblings
#: (``app.log.1``) and lock files.
STORES = (
    "VOCAB_FILE", "REVIEW_FILE", "PROBLEMS_FILE", "PROBLEMS_DIR",
    "QUESTIONS_FILE", "NOTIFY_FILE", "LOOKUP_CACHE", "AWAKE_STATE",
    "APP_LOG", "TRANSCRIPTS_LOG", "NOTIFY_LOG", "AWAKE_LOG", "NETWORK_LOG",
    "RECENT_DIR", "PENDING_DIR", "CORPUS_DIR", "SYNC_DIR",
)

#: Never touched by a reset: the person's settings and secrets.
KEPT = ("SETTINGS_FILE", "STATE_FILE", "CONSENT_FILE", "SETUP_MARKER",
        "PHONE_TOKEN", "SECRETS_DIR", "MODELS_DIR", "PACKS_DIR")

#: Never touched by a reset OF THE OWNER'S OWN DATA (paths.OWNER_DATA): the training data
#: — every transcript, every recording, every read-aloud pair. A reset
#: on 2026-09-17 removed 72 read-aloud clips nobody can re-record; the
#: rule since is that the checkout's history is not app data (AGENTS.md).
#: A stranger's copy still removes them: their data is theirs to delete.
TRAINING_DATA = ("TRANSCRIPTS_LOG", "RECENT_DIR", "CORPUS_DIR")

#: Sub-folders of problems\ that belong to the owner's tools, not to the
#: app: the Saturday routine's journal and the nightly test logs. A reset
#: empties problems\ around them (reports, outbox, screenshots go).
OWNER_PROBLEM_DIRS = ("weekly", "nightly")


def _running() -> bool:
    """Is a DeskIT holding this copy's mutex? Skipped under DESKIT_HOME:
    that hatch points at a scratch data folder no running app owns, and
    the mutex is per logon session, so the owner's live checkout would
    otherwise veto every test of these commands."""
    import os
    if os.environ.get("DESKIT_HOME", "").strip():
        return False
    try:
        import singleton
        return singleton.is_running()
    except Exception:            # noqa: BLE001 — no mutex means not running
        return False


# ------------------------------------------------------------ the config diff

def config_diff(legacy: Path, defaults: Path | None = None
                ) -> tuple[dict, dict, list[str]]:
    """(settings overrides, state values, dropped keys) from an old file.

    A key goes into the overrides only when its value differs from
    defaults.toml; a key defaults.toml does not have is kept as an
    override unless it is on the dropped list — a hand-written setting
    is worth more than a tidy file."""
    old = config_mod.flatten(_toml(legacy))
    new = config_mod.defaults_flat(defaults)
    settings: dict = {}
    state: dict = {}
    dropped: list[str] = []
    for name, value in old.items():
        if name in DROPPED_KEYS or name.startswith(DROPPED_PREFIXES):
            dropped.append(name)
            continue
        if name in config_mod.STATE_KEYS:
            if name in new and new[name] == value \
                    and isinstance(new[name], bool) == isinstance(value, bool):
                continue
            state[name] = value
            continue
        if name in new and new[name] == value \
                and isinstance(new[name], bool) == isinstance(value, bool):
            continue
        settings[name] = value
    return settings, state, dropped


def _toml(path: Path) -> dict:
    with Path(path).open("rb") as f:
        return tomllib.load(f)


def find_legacy_config(where: Path | None = None) -> Path | None:
    """The old config.toml, wherever an old copy keeps it: the file given,
    the folder given, or beside the code — under its retired name, or
    the name --migrate gives it afterwards."""
    if where is not None:
        where = Path(where)
        if where.is_file():
            return where
        base = where if where.is_dir() else None
    else:
        base = None
    for folder in ([base] if base else [paths.APP_DIR, paths.DATA_DIR]):
        for name in ("config.legacy.toml", "config.toml"):
            candidate = folder / name
            if candidate.is_file():
                return candidate
    return None


# ------------------------------------------------------------------ migrate

def migrate(where: Path | None = None, *, out=print) -> int:
    """Carry an old copy over. Returns a process exit code."""
    if _running():
        out("DeskIT is running — stop it first (the stores must not move "
            "under a live process).")
        return 2
    legacy = find_legacy_config(where)
    folder = Path(where) if where is not None and Path(where).is_dir() else None
    if legacy is None:
        out("Nothing to migrate: no config.toml found"
            + (f" in {where}" if where else " beside the app"))
        return 0
    if legacy.resolve() == paths.DEFAULTS_FILE.resolve():
        out("That is defaults.toml itself — nothing to migrate.")
        return 1
    settings, state, dropped = config_diff(legacy)
    existing = config_mod.read_settings(paths.SETTINGS_FILE)
    existing.update(settings)
    machine = config_mod.read_state(paths.STATE_FILE)
    machine.update(state)
    # The marker file says the wizard has run; state.json says so too from
    # now on, so an installed copy that inherited only these two files
    # does not ask again.
    if paths.SETUP_MARKER.exists() or (legacy.parent / ".setup-done").exists():
        machine["setup.done"] = True
    # The files this writes are this build's format (11.10): the owner's
    # cutover is step 1 of the migrations, explicit and never automatic.
    import version
    machine["config_version"] = version.CONFIG_VERSION
    try:
        config_mod.build(config_mod._merge(
            config_mod._merge(config_mod.nest(config_mod.defaults_flat()),
                              config_mod.nest(existing)),
            config_mod.nest(machine)))
    except config_mod.ConfigError as e:
        out(f"The old settings would not load on this version: {e}")
        return 1
    config_mod.write_settings(paths.SETTINGS_FILE, existing)
    config_mod.write_state(paths.STATE_FILE, machine)
    out(f"settings.toml: {len(settings)} value(s) that differ from the "
        f"defaults -> {paths.SETTINGS_FILE}")
    out(f"state.json: {len(state)} machine value(s) -> {paths.STATE_FILE}")
    for name in dropped:
        out(f"  dropped (this version has no such setting): {name}")

    copied = 0
    if folder is not None and folder.resolve() != paths.DATA_DIR.resolve():
        copied = _copy_stores(folder, out)
        out(f"stores copied from {folder}: {copied}")
    import secretstore
    import_env_keys(secretstore.env_file_in(folder or legacy.parent), out)

    if legacy.name == "config.toml" and legacy.parent == paths.APP_DIR:
        retired = legacy.with_name("config.legacy.toml")
        if not retired.exists():
            legacy.rename(retired)
            out(f"the old file is kept as {retired.name}; the app reads "
                "defaults.toml + settings.toml + state.json from now on")
    out("done.")
    return 0


def import_env_keys(env_file: Path, out=print) -> int:
    """Copy the API keys of an old ``.env`` into Windows Credential Manager.

    Never overwrites a key already there, never deletes the file (the
    person does, once the app has run on the new copy), never prints a
    value. Returns how many keys were stored.
    """
    import secretstore
    if not env_file.is_file():
        return 0
    found = secretstore.read_env_file(env_file)
    stored = 0
    for name in secretstore.CRED_NAMES:
        value = (found.get(secretstore.LEGACY_ENV_VARS[name])
                 or found.get(secretstore.ENV_VARS[name]))
        if not value:
            continue
        try:
            already = secretstore.get(name)
        except secretstore.SecretError as e:
            out(f"  {name} key: {e}")
            continue
        if already:
            out(f"  {name} key: already in Windows Credential Manager "
                f"({secretstore.target(name)}); the .env line is not read "
                f"while it is there")
            continue
        try:
            secretstore.set(name, value)
        except secretstore.SecretError as e:
            out(f"  {name} key: {e}")
            continue
        stored += 1
        out(f"  {name} key: copied from {env_file.name} into Windows "
            f"Credential Manager ({secretstore.target(name)})")
    if "CEREBRAS_API_KEY" in found:
        out("  CEREBRAS_API_KEY: no longer read by this version (their free "
            "tier ended) — the line can go")
    if "GOOGLE_API_KEY" in found and "GEMINI_API_KEY" not in found:
        out("  GOOGLE_API_KEY: no longer read — this version takes the "
            "Gemini key only as GEMINI_API_KEY / DESKIT_GEMINI_API_KEY, or "
            "from Credential Manager (main.py --set-key gemini)")
    if stored:
        out(f"  {env_file} is now redundant for those keys; delete the "
            f"lines (or the file) when you like")
    return stored


def _legacy_names() -> dict[str, str]:
    """Store name -> its FLAT (old checkout) relative path."""
    return {name: config_pair[0] for name, config_pair in paths._LAYOUTS.items()}


def _copy_stores(folder: Path, out=print) -> int:
    """Copy the personal stores of an old flat checkout into DATA_DIR.
    Existing targets are left alone (a second run copies nothing)."""
    flat = _legacy_names()
    count = 0
    for name in STORES:
        src = folder / flat[name]
        dst = getattr(paths, name)
        if name.endswith("_DIR"):
            # An EMPTY target is as good as absent: paths.ensure() may
            # already have made the folder before this ran.
            if not src.is_dir() or (dst.exists() and any(dst.iterdir())):
                continue
            shutil.copytree(src, dst, dirs_exist_ok=True)
            count += 1
            continue
        for candidate in _with_siblings(src):
            target = dst.parent / candidate.name if candidate != src \
                else dst
            if candidate.is_file() and not target.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(candidate, target)
                count += 1
    return count


def _with_siblings(path: Path) -> list[Path]:
    """A file plus its rotated copies (app.log, app.log.1, ...) and lock."""
    found = [path]
    if path.parent.is_dir():
        found += sorted(path.parent.glob(path.name + ".*"))
        lock = path.with_suffix(".lock")
        if lock != path and lock.exists():
            found.append(lock)
    return found


# --------------------------------------------------------------- reset-data

def reset_targets() -> list[Path]:
    """Everything --reset-data removes, in order, that exists right now."""
    targets: list[Path] = []
    for name in STORES:
        if paths.OWNER_DATA and name in TRAINING_DATA:
            continue
        p = getattr(paths, name)
        if not name.endswith("_DIR"):
            targets += [c for c in _with_siblings(p) if c.is_file()]
        elif not p.is_dir():
            continue
        elif name == "PROBLEMS_DIR":
            targets += [c for c in sorted(p.iterdir())
                        if c.name not in OWNER_PROBLEM_DIRS]
        else:
            targets.append(p)
    # problems.md, the digest regenerated from the store
    digest = paths.PROBLEMS_FILE.with_suffix(".md")
    if digest.is_file():
        targets.append(digest)
    return targets


def reset_data(*, yes: bool, out=print) -> int:
    """Delete what the app learned and recorded; keep the settings."""
    if _running():
        out("DeskIT is running — stop it first.")
        return 2
    targets = reset_targets()
    if not targets:
        out("Nothing to remove — this copy has no history yet.")
        return 0
    out("This removes, keeping settings.toml, state.json and the keys:")
    for p in targets:
        kind = "folder" if p.is_dir() else "file"
        out(f"  {kind:6} {p}")
    if not yes:
        out("Add --yes to do it.")
        return 1
    removed = 0
    for p in targets:
        try:
            if p.is_dir():
                shutil.rmtree(p)
            else:
                p.unlink()
            removed += 1
        except OSError as e:
            out(f"  could not remove {p}: {e}")
    out(f"removed {removed} of {len(targets)}. Settings kept: "
        f"{paths.SETTINGS_FILE.name}, {paths.STATE_FILE.name}.")
    return 0 if removed == len(targets) else 1


if __name__ == "__main__":
    sys.exit(migrate(Path(sys.argv[1]) if len(sys.argv) > 1 else None))
