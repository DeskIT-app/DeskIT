"""The bubble's outline: a rounded rectangle whose tail is part of the
same curve — the shelf's shape since 2026-09-21.

THE OWNER'S ASK, over four pictures that evening. The panel opened
"very far from the dot" and, once the dot had been dragged to the middle
of the screen, still in its corner; he wanted it "to move with the dot",
and "like a speech bubble — the corner nearest the dot sharpens into
it". The first draft glued a triangle onto the rounded rectangle and he
saw the seam at once: "you take one template and apply it to every case
— there is a break here, I want it smooth"; a rounder draft was "too
delicate"; the last word was the drawing in AGENTS.md's words: "a
triangle whose two legs were cut with a circle — a scoop, but one that
blends in — and a relatively SHARP tip", the tail of an iPhone message
bubble at the corner and a smooth scoop along an edge.

ONE PATH, NOT A UNION. A shape glued onto the body has a break where the
two meet, and a tail whose base falls on a corner pokes out of the
corner's curve as a ledge. So the outline is walked once round the whole
shape and the tail is written into the edge it sits on: each side leaves
the edge with the edge's own tangent — or the CORNER ARC's, when the
base sits on the corner, which is what makes the corner itself sweep
out toward the dot — bows in (the "scoop"), and meets a small apex arc
tangentially; the apex is TIP_R across, a hair short of a point. Every
join is G1 and there is nothing to break, on any edge, at any corner.

Built in a local frame where the tail's edge is the BOTTOM of a WL x HL
box (x along the edge from the corner `at` is measured from, y outward)
and then mapped onto whichever edge it really is — one geometry, four
placings, and a test walks all four.

WHAT IT REACHES. The apex is TAIL_L out of the face, which has to stay
inside the window's shadow margin (shelf_card.SHADOW, 26 px) or the tip
would be cut off flat — a test holds the two apart. The face itself is
placed TAIL_L + TAIL_CLEAR from the dot's window (shelf.ShelfCard.
DOT_GAP), so the tip stops just short of the halo.

Pure arithmetic, no skia: `outline()` is a list of path commands a test
can read; `skia_path()` is the same thing as a skia.Path for the
painter; `tail_for()` decides side, place and lean from two rectangles.
"""
from __future__ import annotations

import math

TAIL_L = 24              # how far the apex reaches out of the face
TAIL_W = 28              # half the base's width along the edge
TAIL_CLEAR = 6           # daylight between the tip and the dot's window
TIP_R = 1.2              # the apex arc — a hair short of a point
APEX_DEG = 40.0          # half the apex arc: where the legs meet it
SWEEP = 0.8              # how far a leg bows before the apex (of TAIL_L)
BASE = 0.62              # the take-off control point along the base (of TAIL_W)
CORNER_TAKEOFF = 0.9     # how far round a corner arc a leg may take off (1 = the side)
SIDES = ("top", "bottom", "left", "right")


def _arc(cx, cy, r, a0, a1):
    """One cubic for the arc of a circle from angle a0 to a1 (radians,
    |a1 - a0| <= 90 deg): (c1, c2, end)."""
    k = 4.0 / 3.0 * math.tan((a1 - a0) / 4.0) * r
    p0 = (cx + r * math.cos(a0), cy + r * math.sin(a0))
    p3 = (cx + r * math.cos(a1), cy + r * math.sin(a1))
    t0 = (-math.sin(a0), math.cos(a0))
    t1 = (-math.sin(a1), math.cos(a1))
    return ((p0[0] + k * t0[0], p0[1] + k * t0[1]),
            (p3[0] - k * t1[0], p3[1] - k * t1[1]), p3)


def reach() -> float:
    """How far outside the face the outline can go: the apex."""
    return float(TAIL_L)


def outline(width: float, height: float, radius: float, tail):
    """The shape as a list of ("move"|"line"|"cubic"|"close", points...)
    in FACE coordinates (0, 0 = the face's top-left, y down). `tail` is
    (side, at, lean) — the edge, where along it the base sits (from the
    top or the left), how far the apex leans along the edge — or None
    for the plain rounded rectangle."""
    side, at, lean = ("bottom", None, 0.0) if tail is None else tail
    if side not in SIDES:
        raise ValueError(f"no such side: {side!r}")
    if side in ("top", "bottom"):
        WL, HL = float(width), float(height)
    else:
        WL, HL = float(height), float(width)
    R = float(radius)
    cmds: list = []

    def emit(kind, *pts):
        cmds.append((kind,) + pts)

    if at is not None:
        W, L, r = TAIL_W, TAIL_L, TIP_R
        at = max(W, min(WL - W, float(at)))
        bx0, bx1 = at - W, at + W
        tx = at + max(-W * 0.8, min(W * 0.8, float(lean)))
        beta = math.radians(APEX_DEG)
        acx, acy = tx, HL + L - r                  # the apex arc's centre
        a_l, a_r = math.pi / 2 + beta, math.pi / 2 - beta
        P_l = (acx + r * math.cos(a_l), acy + r * math.sin(a_l))
        P_r = (acx + r * math.cos(a_r), acy + r * math.sin(a_r))
        # travel directions on the apex, from P_r round the tip to P_l
        # (the walk below runs along this edge right to left)
        d_r = (-math.sin(a_r), math.cos(a_r))
        d_l = (-math.sin(a_l), math.cos(a_l))
        k_leg = L * SWEEP
        k_apex = 4.0 / 3.0 * math.tan(beta / 2.0) * r
        # a base on a corner: that leg takes off from the corner's arc
        in_l, in_r = bx0 < R, bx1 > WL - R
        t_l = min(1.0, (R - bx0) / R) * CORNER_TAKEOFF if in_l else 0.0
        t_r = min(1.0, (bx1 - (WL - R)) / R) * CORNER_TAKEOFF if in_r else 0.0

    # the walk, clockwise, from the end of the top-left corner
    emit("move", (R, 0.0))
    emit("line", (WL - R, 0.0))
    emit("cubic", *_arc(WL - R, R, R, -math.pi / 2, 0.0))
    emit("line", (WL, HL - R))
    if at is None or not in_r:
        emit("cubic", *_arc(WL - R, HL - R, R, 0.0, math.pi / 2))
        if at is not None:
            emit("line", (bx1, HL))
            emit("cubic", (bx1 - W * BASE, HL),
                 (P_r[0] - k_leg * d_r[0], P_r[1] - k_leg * d_r[1]), P_r)
    else:
        a_take = math.pi / 2 * (1.0 - t_r)          # 90 = the edge, 0 = the side
        emit("cubic", *_arc(WL - R, HL - R, R, 0.0, a_take))
        J = (WL - R + R * math.cos(a_take), HL - R + R * math.sin(a_take))
        tJ = (-math.sin(a_take), math.cos(a_take))
        emit("cubic", (J[0] + k_leg * 0.8 * tJ[0], J[1] + k_leg * 0.8 * tJ[1]),
             (P_r[0] - k_leg * d_r[0], P_r[1] - k_leg * d_r[1]), P_r)
    if at is not None:
        emit("cubic", (P_r[0] + k_apex * d_r[0], P_r[1] + k_apex * d_r[1]),
             (P_l[0] - k_apex * d_l[0], P_l[1] - k_apex * d_l[1]), P_l)
        if not in_l:
            emit("cubic", (P_l[0] + k_leg * d_l[0], P_l[1] + k_leg * d_l[1]),
                 (bx0 + W * BASE, HL), (bx0, HL))
            emit("line", (R, HL))
            emit("cubic", *_arc(R, HL - R, R, math.pi / 2, math.pi))
        else:
            a_land = math.pi / 2 * (1.0 + t_l)      # 90 = the edge, 180 = the side
            J = (R + R * math.cos(a_land), HL - R + R * math.sin(a_land))
            tJ = (-math.sin(a_land), math.cos(a_land))
            emit("cubic", (P_l[0] + k_leg * d_l[0], P_l[1] + k_leg * d_l[1]),
                 (J[0] - k_leg * 0.8 * tJ[0], J[1] - k_leg * 0.8 * tJ[1]), J)
            emit("cubic", *_arc(R, HL - R, R, a_land, math.pi))
    else:
        emit("line", (R, HL))
        emit("cubic", *_arc(R, HL - R, R, math.pi / 2, math.pi))
    emit("line", (0.0, R))
    emit("cubic", *_arc(R, R, R, math.pi, 1.5 * math.pi))
    emit("close")

    def world(p):
        x, y = p
        if side == "bottom":
            return (x, y)
        if side == "top":
            return (x, height - y)
        if side == "left":
            return (width - y, x)
        return (y, x)                                # right: outward is +x

    return [(c[0],) + tuple(world(p) for p in c[1:]) for c in cmds]


def apex(width: float, height: float, tail) -> tuple[float, float] | None:
    """Where the tip is, in face coordinates — None without a tail."""
    if tail is None:
        return None
    side, at, lean = tail
    W = TAIL_W
    along = float(height if side in ("left", "right") else width)
    at = max(W, min(along - W, float(at)))
    tx = at + max(-W * 0.8, min(W * 0.8, float(lean)))
    if side == "bottom":
        return (tx, height + TAIL_L)
    if side == "top":
        return (tx, -TAIL_L)
    if side == "left":
        return (-TAIL_L, tx)
    return (width + TAIL_L, tx)


def skia_path(width, height, radius, tail, x0: float = 0.0, y0: float = 0.0):
    """`outline` as a skia.Path, its face at (x0, y0)."""
    import skia
    path = skia.Path()
    for cmd in outline(width, height, radius, tail):
        kind, pts = cmd[0], [(x0 + p[0], y0 + p[1]) for p in cmd[1:]]
        if kind == "move":
            path.moveTo(*pts[0])
        elif kind == "line":
            path.lineTo(*pts[0])
        elif kind == "cubic":
            path.cubicTo(*pts[0], *pts[1], *pts[2])
        else:
            path.close()
    return path


def tail_for(face_rect, dot_rect):
    """(side, at, lean) for a face and a dot (both (l, t, r, b), screen
    pixels): the edge that faces the dot, where along it the base sits,
    and how far the apex leans along the edge toward the dot. None when
    the two overlap — then there is nothing to point at."""
    fl, ft, fr, fb = (float(v) for v in face_rect)
    dl, dt, dr, db = (float(v) for v in dot_rect)
    cx, cy = (dl + dr) / 2.0, (dt + db) / 2.0
    w, h = fr - fl, fb - ft
    if db <= ft or dt >= fb:
        side = "top" if db <= ft else "bottom"
        want = cx - fl
        at = max(TAIL_W, min(w - TAIL_W, want))
        return (side, at, want - at)
    if dr <= fl or dl >= fr:
        side = "left" if dr <= fl else "right"
        want = cy - ft
        at = max(TAIL_W, min(h - TAIL_W, want))
        return (side, at, want - at)
    return None


__all__ = ["TAIL_L", "TAIL_W", "TAIL_CLEAR", "TIP_R", "SIDES", "reach",
           "outline", "apex", "skia_path", "tail_for"]
