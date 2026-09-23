"""The Code screen: what is on this PC and not on GitHub, and where the
releases stand.

It reads git and gh. It does not push, merge, tag or undo — the git card
in the Dev desk does that today, and this screen is what replaces it
(MASTER.md rule 2 and §8). The whole verb here is still "take it to a
chat": a branch row exports its commits and its diff against main, which
is what a review question needs.
"""
from __future__ import annotations

import json

from .. import when as W
from ..root import Root
from ..rows import Row, line
from ..run import Failed, lines, out

MAIN = "main"
SKIP = ("weekly/", "worktree-", "claude/")     # branches that are not lanes
#: branches that live here on purpose and are never pushed: dev-all is
#: his Dev's integration branch (AGENTS / the dev-all note), so "not
#: pushed" is what it is for, not something to flag.
LOCAL_ONLY = ("dev-all",)
BODY_MAX = 12000


def rows(root: Root, *, net: bool = True) -> list[Row]:
    return _branches(root) + (_releases(root) if net else [])


def _branches(root: Root) -> list[Row]:
    try:
        raw = lines(["git", "for-each-ref", "refs/heads",
                     "--format=%(refname:short)\t%(upstream:short)\t"
                     "%(committerdate:iso8601)\t%(contents:subject)"], root.dir)
    except Failed as e:
        return [Row(id="code:git", screen="code", title="git did not answer",
                    under=str(e), tone="warn", glyph="warn", at=W.stamp_now(),
                    facts={"Why": str(e)}, came_from=["git for-each-ref"])]
    head = _head(root)
    out_rows = []
    for row_text in raw:
        name, upstream, date, subject = (row_text.split("\t") + ["", "", ""])[:4]
        if name in (MAIN,) or any(name.startswith(p) for p in SKIP):
            continue
        ahead, behind = _counts(root, MAIN, name)
        if ahead == 0 and name != head:
            continue                       # already in main: not waiting for anything
        pushed = bool(upstream)
        unpushed = _counts(root, upstream, name)[0] if upstream else ahead
        big, small = W.words(date)
        local = name in LOCAL_ONLY
        tone, glyph = (("q", "link") if local or (pushed and not unpushed)
                       else ("warn", "warn"))
        out_rows.append(Row(
            id=f"code:branch:{name}",
            screen="code",
            title=f"{name} — {subject.strip() or 'no subject'}",
            under=line(f"{ahead} commit" + ("s" if ahead != 1 else "") + " on top of main",
                       "local on purpose" if local else
                       "not pushed" if not pushed else
                       (f"{unpushed} not pushed" if unpushed else "pushed"),
                       f"{behind} behind main" if behind else "",
                       "this checkout is on it" if name == head else ""),
            tone=tone, glyph=glyph,
            when=big, when_small=small, at=W.sortable(date),
            facts={"Branch": name, "Upstream": upstream or "none",
                   "Commits on top of main": ahead, "Behind main": behind,
                   "Not pushed": unpushed, "Last commit": date,
                   "Checked out here": name == head},
            body=_body(root, name),
            body_title="The commits and the change",
            body_from="machine",
            came_from=[f"git log {MAIN}..{name}", f"git diff {MAIN}...{name}"],
        ))
    out_rows.sort(key=lambda r: r.at, reverse=True)
    return out_rows


def _releases(root: Root) -> list[Row]:
    try:
        raw = out(["gh", "release", "list", "--limit", "5", "--json",
                   "tagName,publishedAt,isDraft,isPrerelease,name"], root.dir)
        rels = json.loads(raw or "[]")
    except (Failed, ValueError) as e:
        return [Row(id="code:releases", screen="code",
                    title="the releases were not read", under=str(e),
                    tone="warn", glyph="warn", at=W.stamp_now(),
                    facts={"Why": str(e)}, came_from=["gh release list"])]
    out_rows = []
    for rel in rels:
        tag = str(rel.get("tagName") or "")
        draft = bool(rel.get("isDraft"))
        big, small = W.words(rel.get("publishedAt"))
        out_rows.append(Row(
            id=f"code:release:{tag}",
            screen="code",
            title=f"{tag} — " + ("draft, waiting for you to publish" if draft
                                      else "published"),
            under=line(rel.get("name"), "pre-release" if rel.get("isPrerelease") else ""),
            tone="warn" if draft else "ok", glyph="warn" if draft else "ok",
            when=big or tag, when_small=small, at=W.sortable(rel.get("publishedAt")),
            facts={"Tag": tag, "Draft": draft,
                   "Pre-release": bool(rel.get("isPrerelease")),
                   "Published": rel.get("publishedAt", ""), "Name": rel.get("name", "")},
            came_from=["gh release list"],
        ))
    return out_rows


# ---------------------------------------------------------------- git bits

def _head(root: Root) -> str:
    try:
        return out(["git", "rev-parse", "--abbrev-ref", "HEAD"], root.dir).strip()
    except Failed:
        return ""


def _counts(root: Root, base: str, branch: str) -> tuple[int, int]:
    """(ahead, behind) of `branch` against `base`."""
    if not base:
        return (0, 0)
    try:
        text = out(["git", "rev-list", "--left-right", "--count",
                    f"{base}...{branch}"], root.dir).split()
    except Failed:
        return (0, 0)
    behind, ahead = (int(text[0]), int(text[1])) if len(text) == 2 else (0, 0)
    return (ahead, behind)


def _body(root: Root, branch: str) -> str:
    """What the export carries for a branch: its commits, then its diff
    against main, cut at a size a chat can still read."""
    try:
        log = out(["git", "log", "--no-merges", "--format=%h %ad  %s",
                   "--date=short", f"{MAIN}..{branch}"], root.dir)
        stat = out(["git", "diff", "--stat", f"{MAIN}...{branch}"], root.dir)
        patch = out(["git", "diff", f"{MAIN}...{branch}"], root.dir)
    except Failed as e:
        return f"(git could not be read: {e})"
    cut = patch[:BODY_MAX]
    if len(patch) > BODY_MAX:
        cut += f"\n\n[... {len(patch) - BODY_MAX:,} more characters of diff ...]"
    return f"Commits\n{log}\nFiles\n{stat}\nThe change\n{cut}"
