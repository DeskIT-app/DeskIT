"""What a consent card says, and how it is drawn (plan 5.3, D7, D11).

Split the way review_card.py is split: this half owns the WORDS and the
PICTURE — pure Python plus Pillow, no Tk, no window — and
overlay.ConsentCard owns the thread, the queue and the two answers. One
layout for every kind: a title, five short blocks (what leaves, to whom,
under whose account, the provider's own sentence, how to turn it off),
one last line that is the same on every card, and two buttons. The
words are the whole point of the card, so they live here as data a
test can read, and each kind carries the ``text_version`` privacy.py
writes into consent.json when [Turn on] is pressed: the words change,
the version bumps, the old row goes stale (D11).

The provider sentences are the providers' own, from the terms
research/legal read (Groq Services Agreement 2026-06-22, Gemini API
terms 2026-04-28), cut to the clause that matters; the guide's cloud
chapter carries them whole. They are quoted, not paraphrased, because a
paraphrase is a promise this app cannot keep on someone else's behalf.

Everything geometric is a function of the card dict and the scale;
``regions()`` is what both the painter and the hit test read, which is
what keeps a button drawn where it is pressed. Text is measured by
rendering it (review_card._text through visual_qa.text_pil), so
``measure`` takes the same cache the painter uses and a throwaway one
when nobody passed any.
"""
from __future__ import annotations

from PIL import Image

import review_card as rc
from review_card import (ACCENT, ACCENT_HI, ACCENT_ON, CARD, EDGE, EDGE_HI,
                         HTCAPTION, HTCLIENT, HTTRANSPARENT, INK, INK_DIM,
                         INK_FAINT, LINE, SHADOW, _rr, _text, clamp_scale)

CARD_W = 460
RADIUS = 20
PAD = 18
TITLE_PT = 13.0
LABEL_PT = 8.5
BODY_PT = 10.0
FOOT_PT = 8.5
BLOCK_GAP = 10
BTN_H = 32
BTN_GAP = 8

TURN_ON, NOT_NOW, DRAG = "turn_on", "not_now", "drag"
BUTTONS = ((TURN_ON, 124), (NOT_NOW, 112))       # name, width at 1.0
LABELS = {TURN_ON: "Turn on", NOT_NOW: "Not now"}

FOOTER = ("Every connection DeskIT makes is listed under Settings > Privacy > "
          "Every connection, and in network.log.")

# The labels, in the order the plan lists them. ENGLISH, SHORT, since
# 2026-09-19 evening — the owner met the Hebrew card mid-dictation:
# "make it English and much shorter". The providers' sentences stay
# theirs, cut to the clause that matters; the full quotes are in the
# guide's cloud chapter (docs/en/05-cloud), which the wizard links.
WHAT, WHOM, ACCOUNT, TERMS, OFF = ("What leaves", "To whom", "On whose account",
                                   "The providers say", "Off again")

_GROQ = ('Groq: "not permitted to use Inputs or Outputs for training"; nothing kept '
         'by default. 18+.')
_GEMINI = ('Google (Gemini, free tier): used "to provide, improve, and develop Google '
           'products"; humans may read it. Not for the EU, UK or Switzerland. 18+.')
_KEY = "Your own key. You are their customer; nothing passes through a DeskIT server."
_OFF = "Settings > Privacy, or remove the key."
_DESKIT = "DeskIT's server (Supabase, Frankfurt) — the only server DeskIT has."
_PROJECT = "DeskIT's project, through your account."
_TERMS = "The one-page terms and the privacy policy."

#: kind -> the card's words. ``version`` is privacy.TEXT_VERSIONS[kind]
#: spelled here too, so a change to the words and a bump of the version
#: land in the same file (a test holds the two equal).
TEXTS: dict[str, dict] = {
    "cloud_text": {
        "version": "groq-2026-06-22+gemini-2026-04-28+en-2026-09-19",
        "title": "Send text to the cloud?",
        "blocks": (
            (WHAT, "The text you dictated or selected, up to 5,000 characters a request. "
                   "Never your voice."),
            (WHOM, "Groq and/or Google — repair, punctuation, translation, lookup, the "
                   "second reading."),
            (ACCOUNT, _KEY),
            (TERMS, _GROQ + " " + _GEMINI),
            (OFF, _OFF),
        ),
    },
    "cloud_audio": {
        "version": "groq-2026-06-22+gemini-2026-04-28+en-2026-09-19",
        "title": "Send recordings to the cloud?",
        "blocks": (
            (WHAT, "The recording of what you just said, as a WAV file."),
            (WHOM, "Google (Gemini) or Groq, for transcription."),
            (ACCOUNT, _KEY),
            (TERMS, _GEMINI + " " + _GROQ),
            (OFF, _OFF + " The engine goes back to local."),
        ),
    },
    "cloud_screenshots": {
        "version": "groq-2026-06-22+gemini-2026-04-28+en-2026-09-19",
        "title": "Send a screenshot to the cloud?",
        "blocks": (
            (WHAT, "A JPEG of the area you marked, your question, and the earlier "
                   "questions on the same card. A screenshot can hold mail, a bank, "
                   "anything that was on screen."),
            (WHOM, "Groq and/or Google, for the question about the screen."),
            (ACCOUNT, _KEY),
            (TERMS, _GROQ + " " + _GEMINI),
            (OFF, _OFF),
        ),
    },
    "account": {
        "version": "deskit-terms-0+en-2026-09-19",
        "title": "Open an account?",
        "blocks": (
            (WHAT, "An account id — anonymous, or the e-mail of the Google account you "
                   "chose; this PC's name; the app, Windows and hardware versions."),
            (WHOM, _DESKIT),
            (ACCOUNT, "DeskIT's project; your keys never travel there — they have no "
                      "column in the database."),
            (TERMS, _TERMS),
            (OFF, "Your data > Delete my account."),
        ),
    },
    "report_upload": {
        "version": "deskit-terms-0+en-2026-09-19",
        "title": "Send problem reports?",
        "blocks": (
            (WHAT, "Only what the report's preview showed — after the clean-up."),
            (WHOM, _DESKIT),
            (ACCOUNT, "DeskIT's project, through your anonymous account."),
            (TERMS, _TERMS),
            (OFF, "Keep it on this PC instead, or Settings > Privacy > Withdraw."),
        ),
    },
    "settings_sync": {
        "version": "deskit-terms-0+en-2026-09-19",
        "title": "Sync settings and words?",
        "blocks": (
            (WHAT, "Your settings changes and the words you taught it — never keys, "
                   "hotkeys, devices, folders or positions; never audio, history or "
                   "reports."),
            (WHOM, _DESKIT + " From there to every PC you sign in on."),
            (ACCOUNT, _PROJECT),
            (TERMS, _TERMS),
            (OFF, "Settings > Privacy > Withdraw."),
        ),
    },
    "history_sync": {
        "version": "deskit-terms-0+en-2026-09-19",
        "title": "Sync what you said?",
        "blocks": (
            (WHAT, "Everything you dictated, translated, punctuated and looked up — the "
                   "text, not the recording — so the Said page is the same on every PC."),
            (WHOM, _DESKIT + " Kept in your account; DeskIT's key can technically read "
                   "it — the protection separates users, not the project's admin."),
            (ACCOUNT, _PROJECT),
            (TERMS, _TERMS),
            (OFF, "Settings > Privacy > Withdraw; \"Delete my account\" removes what was "
                  "synced too."),
        ),
    },
}

#: The words' direction, decided from the table: English lays out from
#: the left; a Hebrew table would lay itself out from the right again.
RTL: bool = any("\u0590" <= ch <= "\u05FF"
                for card in TEXTS.values() for _label, text in card["blocks"] for ch in text)


# ---------------------------------------------------------------------------
# the words
# ---------------------------------------------------------------------------

def card_for(kind: str) -> dict:
    """The whole card as data: what overlay.ConsentCard queues and every
    painter consumes."""
    words = TEXTS[kind]
    return {"kind": kind, "text_version": words["version"],
            "title": words["title"], "blocks": list(words["blocks"]),
            "footer": FOOTER}


# ---------------------------------------------------------------------------
# the layout — measured by rendering, which is why every function here
# takes the cache
# ---------------------------------------------------------------------------

def _body(cache: dict, text: str, pt: float, width: int, colour=INK):
    """A wrapped paragraph, right-to-left, cropped to its glyphs."""
    key = ("block", text, round(pt, 2), width, colour)
    img = cache.get(key)
    if img is None:
        from visual_qa import text_pil
        img = text_pil(text, max(40, int(width)), pt=pt, colour=colour,
                       rtl=RTL, single=False)
        box = img.getchannel("A").getbbox()
        # Keep the full WIDTH (the right edge is the margin) and crop
        # only the height, so every paragraph starts at the same x.
        if box:
            img = img.crop((0, box[1], img.width, box[3]))
        cache[key] = img
    return img


def layout(card: dict, scale: float = 1.0, cache: dict | None = None) -> dict:
    """Where everything goes at `scale`: the rendered pieces and their
    y positions, and the card's size. One walk, shared by measure,
    regions and compose."""
    cache = cache if cache is not None else {}
    s = clamp_scale(scale)
    width = int(round(CARD_W * s))
    pad = PAD * s
    inner = int(width - 2 * pad)
    y = pad
    title = _text(cache, card["title"], TITLE_PT * s, weight=600, rtl=RTL)
    items = [("title", title, y)]
    y += title.height + 8 * s
    for label, text in card["blocks"]:
        lab = _text(cache, label, LABEL_PT * s, colour=INK_FAINT, weight=600, rtl=RTL)
        items.append(("label", lab, y))
        y += lab.height + 3 * s
        body = _body(cache, text, BODY_PT * s, inner)
        items.append(("body", body, y))
        y += body.height + BLOCK_GAP * s
    foot = _body(cache, card["footer"], FOOT_PT * s, inner, colour=INK_DIM)
    items.append(("footer", foot, y))
    y += foot.height + 12 * s
    buttons_y = y
    y += BTN_H * s + pad
    return {"scale": s, "width": width, "height": int(round(y)),
            "items": items, "buttons_y": buttons_y, "pad": pad}


def measure(card: dict, scale: float = 1.0,
            cache: dict | None = None) -> tuple[int, int]:
    lay = layout(card, scale, cache)
    return lay["width"], lay["height"]


def regions(card: dict, scale: float = 1.0, cache: dict | None = None) -> dict:
    """The rectangles that take the mouse, window-relative (the window is
    the card plus SHADOW on every side). Buttons right to left along the
    bottom; everything else on the card is the handle you drag it by."""
    lay = layout(card, scale, cache)
    s, width, height = lay["scale"], lay["width"], lay["height"]
    x0 = y0 = SHADOW
    pad = lay["pad"]
    y_top = y0 + lay["buttons_y"]
    y1 = y_top + BTN_H * s
    x = x0 + width - pad
    out = {}
    for name, w in BUTTONS:
        bw = w * s
        out[name] = (x - bw, y_top, x, y1)
        x -= bw + BTN_GAP * s
    out[DRAG] = (x0, y0, x0 + width, y0 + height)
    return out


def hit_test(card: dict, scale: float, x: int, y: int,
             cache: dict | None = None):
    boxes = regions(card, scale, cache)
    for name, _w in BUTTONS:
        if rc._in(boxes[name], x, y):
            return HTCLIENT, name
    if rc._in(boxes[DRAG], x, y):
        return HTCAPTION, DRAG
    return HTTRANSPARENT, None


# ---------------------------------------------------------------------------
# the picture
# ---------------------------------------------------------------------------

def compose(card: dict, scale: float = 1.0, hover: str | None = None,
            cache: dict | None = None):
    """The card's CONTENT as one RGBA image the size of measure(), on a
    transparent ground; the face is the presenter's."""
    cache = cache if cache is not None else {}
    lay = layout(card, scale, cache)
    s, width, height = lay["scale"], lay["width"], lay["height"]
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    right = width - lay["pad"]
    left = lay["pad"]
    for kind, piece, y in lay["items"]:
        img.alpha_composite(piece, (int(right - piece.width) if RTL else int(left), int(y)))
    boxes = regions(card, s, cache)
    for name, _w in BUTTONS:
        bx0, by0, bx1, by1 = (v - SHADOW for v in boxes[name])
        hot = hover == name
        if name == TURN_ON:
            face = _rr((bx1 - bx0, by1 - by0), 9 * s,
                       fill=(ACCENT_HI if hot else ACCENT) + (255,))
            colour = ACCENT_ON
        else:
            face = _rr((bx1 - bx0, by1 - by0), 9 * s,
                       fill=(EDGE_HI if hot else EDGE) + (255,),
                       outline=LINE + (255,))
            colour = INK
        img.alpha_composite(face, (int(bx0), int(by0)))
        lab = _text(cache, LABELS[name], 9.5 * s, colour=colour, weight=600)
        img.alpha_composite(lab, (int((bx0 + bx1) / 2 - lab.width / 2),
                                  int((by0 + by1) / 2 - lab.height / 2)))
    return img


def flat(card: dict, scale: float = 1.0, hover: str | None = None,
         cache: dict | None = None):
    """The card on a solid face — the Tk fallback: a rounded card in the
    fallback palette, the content on top, no shadow, no glass."""
    cache = cache if cache is not None else {}
    width, height = measure(card, scale, cache)
    s = clamp_scale(scale)
    face = Image.new("RGBA", (width, height), CARD + (255,))
    face.alpha_composite(_rr((width, height), RADIUS * s, fill=None,
                             outline=LINE + (255,), width=1))
    face.alpha_composite(compose(card, s, hover, cache))
    return face


__all__ = ["TEXTS", "card_for", "layout", "measure", "regions", "hit_test",
           "compose", "flat", "TURN_ON", "NOT_NOW", "DRAG", "BUTTONS",
           "LABELS", "FOOTER", "SHADOW", "INK", "INK_DIM"]
