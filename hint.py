"""What the card says while you are holding the key.

Split out of the window that shows it (overlay.HintCard) and the thing
that paints it (skin/hint.py) because this half is the only half with an
opinion, and it is the half that can be wrong in a way nobody notices: a
card that lists a key you have rebound, or claims a key works when the
state machine will refuse it, is worse than no card at all. Pure Python,
no Tk, no Win32 — so a test can read every row.

THE ROWS COME FROM THE SAME PLACE THE BINDINGS DO. Every key here is read
off the live Config under the same condition main.App._bindings uses to
register it (`if cfg.lookup_hotkey`, `if vqa.enabled and vqa.hotkey`, and
so on). Nothing is hardcoded, so rebinding a key in the dashboard moves it
on the card too, and switching a feature off takes its row away.
`tests.py` asserts that this module's key set and the state machine's tap
table are the same set — that is the guard, not this paragraph.

WHICH KEYS ARE LIVE IS main.py's RULE, NOT A SECOND COPY OF IT. The split
is `main._SCREEN_ACTIONS`, imported rather than repeated: the four screen
keys fire mid-hold, the four that read or write text at the cursor are
refused because a hand is on the hotkey and there is no selection to act
on. Latched, everything fires. If that rule moves, this moves with it.
"""
from __future__ import annotations

HOLD = "hold"
LATCHED = "latched"

# action -> what to call it on the card. Hebrew, because the card is read
# at a glance mid-sentence by someone dictating Hebrew, and a glance is
# not the moment to translate.
LABELS: dict[str, str] = {
    "visual_qa": "שאלה על המסך",
    "capture": "צילום מסך",
    "record": "הקלטת וידאו",
    "photo": "מצלמה",
    "translate": "תרגום",
    "punctuate": "פיסוק",
    "correct": "למד מילה שטעה בה",
    "lookup": "חיפוש מילה",
    "screens": "מסכים כבויים",
    "notify_dismiss": "סגור התראה",
    "problem_report": "דווח על תקלה",
    "shelf": "המדף",
}

# The reason a text key is greyed rather than simply missing. Short enough
# to sit on one row; it is the same fact main._allowed logs at length.
NEEDS_A_HAND = "צריך יד פנויה"

_PRETTY = {
    "ctrl": "Ctrl", "shift": "Shift", "alt": "Alt", "win": "Win",
    "right ctrl": "Right Ctrl", "left ctrl": "Left Ctrl",
    "right shift": "Right Shift", "left shift": "Left Shift",
    "right alt": "Right Alt", "left alt": "Left Alt",
    "esc": "Esc", "escape": "Esc", "insert": "Insert", "space": "Space",
    "left": "←", "right": "→", "up": "↑", "down": "↓",
}


def pretty(binding: str) -> str:
    """"ctrl+f10" -> "Ctrl+F10", "left" -> "←".

    Kept here rather than imported from dashboard.py, which cannot be
    imported without building Tk, and this runs on the keyboard thread.
    """
    binding = (binding or "").strip()
    if not binding:
        return ""
    low = binding.lower()
    if low in _PRETTY:
        return _PRETTY[low]
    parts = []
    for piece in low.split("+"):
        piece = piece.strip()
        if not piece:
            continue
        if piece in _PRETTY:
            parts.append(_PRETTY[piece])
        elif len(piece) <= 3 and piece[:1] == "f" and piece[1:].isdigit():
            parts.append(piece.upper())
        else:
            parts.append(piece.title())
    return "+".join(parts)


def bindings(cfg) -> list[tuple[str, str]]:
    """(action, binding) for every feature key that is actually live.

    The conditions mirror main.App._bindings exactly, getattr included:
    `classic`'s Config has no [visual_qa], [capture] or [camera] section
    at all, and this file is one of the ones that must stay byte-identical
    on both branches.
    """
    out: list[tuple[str, str]] = []
    vqa = getattr(cfg, "visual_qa", None)
    if vqa is not None and vqa.enabled and vqa.hotkey:
        out.append(("visual_qa", vqa.hotkey))
    cap = getattr(cfg, "capture", None)
    if cap is not None and cap.enabled:
        if cap.hotkey:
            out.append(("capture", cap.hotkey))
        if cap.record_hotkey:
            out.append(("record", cap.record_hotkey))
    cam = getattr(cfg, "camera", None)
    if cam is not None and cam.enabled and cam.hotkey:
        out.append(("photo", cam.hotkey))
    awake = getattr(cfg, "awake", None)
    if awake is not None and awake.enabled and awake.hotkey:
        out.append(("screens", awake.hotkey))
    ncfg = getattr(cfg, "notify", None)
    if ncfg is not None and ncfg.enabled and ncfg.hotkey:
        out.append(("notify_dismiss", ncfg.hotkey))
    # getattr on the FIELD too, not only the section: the report key is
    # landing with the config half of this feature, and a Config that has
    # [problems] without a hotkey in it must bind nothing here either.
    pcfg = getattr(cfg, "problems", None)
    if pcfg is not None and pcfg.enabled and getattr(pcfg, "hotkey", ""):
        out.append(("problem_report", pcfg.hotkey))
    # The shelf, on the same terms and both by getattr: a Config without
    # a [shelf] section binds nothing and shows nothing, which is what
    # `classic` needs from this file.
    scfg = getattr(cfg, "shelf", None)
    if scfg is not None and scfg.enabled and getattr(scfg, "hotkey", ""):
        out.append(("shelf", scfg.hotkey))
    if cfg.punctuate_hotkey:
        out.append(("punctuate", cfg.punctuate_hotkey))
    if cfg.translate_hotkey:
        out.append(("translate", cfg.translate_hotkey))
    if cfg.correct_hotkey:
        out.append(("correct", cfg.correct_hotkey))
    if cfg.lookup_hotkey:
        out.append(("lookup", cfg.lookup_hotkey))
    return out


def card_for(cfg, state: str, screen_actions=frozenset()) -> dict | None:
    """The whole card as data, or None when nothing should be on screen.

    `screen_actions` is main._SCREEN_ACTIONS, passed in rather than
    imported so this module stays importable on its own and a test can
    hand it a different set to prove the greying follows the rule instead
    of a copy of it.
    """
    if state not in (HOLD, LATCHED):
        return None
    latched = state == LATCHED
    held = pretty(cfg.hotkey)
    latch = pretty(cfg.latch_hotkey) if cfg.latch_hotkey else ""

    top: list[tuple[str, str, bool]] = []
    if latched:
        if latch:
            top.append((latch, "סיים ותמלל", True))
    else:
        top.append(("שחרר", "הטקסט נדבק איפה שהסמן", True))
        if latch:
            top.append((latch, "נעילה — אפשר לעזוב ולדבר", True))
    top.append(("Esc", "ביטול, בלי להדביק כלום", True))

    live, refused = [], []
    for action, binding in bindings(cfg):
        label = LABELS.get(action, action)
        if latched or action in screen_actions:
            live.append((pretty(binding), label, True))
        else:
            refused.append((pretty(binding), f"{label} — {NEEDS_A_HAND}", False))

    return {
        "state": state,
        "dot": "locked" if latched else "recording",
        "title": "נעול" if latched else "מקליט",
        "sub": ("דבר כמה שאתה רוצה" if latched
                else f"עוד מחזיק את {held}"),
        "section": ("כל המקשים פעילים" if latched
                    else "עובד גם באמצע ההקלטה"),
        "rows": top,
        "keys": live + refused,
        "footer": "אל תציג את זה יותר",
    }
