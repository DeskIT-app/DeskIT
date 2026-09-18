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

The provider sentences are the providers' own, in their language, from
the terms research/legal read (Groq Services Agreement 2026-06-22,
Gemini API terms 2026-04-28). They are quoted, not paraphrased, because
a paraphrase is a promise this app cannot keep on someone else's behalf.

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
LABELS = {TURN_ON: "הפעל", NOT_NOW: "לא עכשיו"}

FOOTER = ("כל חיבור שהאפליקציה יוצרת רשום תחת Settings > Privacy > "
          "EVERY CONNECTION ובקובץ network.log.")

# The five labels, in the order the plan lists them.
WHAT, WHOM, ACCOUNT, TERMS, OFF = ("מה יוצא", "לאן", "על חשבון מי",
                                   "מה הספק אומר", "איך מכבים")

_GROQ = ('Groq: "not permitted to use Inputs or Outputs for training"; '
         'בלי שמירה כברירת מחדל, יומני ניטור עד 30 יום אלא אם הפעלת '
         'Zero Data Retention בקונסולה של Groq. גיל 18 ומעלה.')
_GEMINI = ('Google (Gemini, המסלול החינמי): התוכן משמש "to provide, improve, '
           'and develop Google products"; "human reviewers may read, '
           'annotate, and process your API input and output"; "Do not '
           'submit sensitive, confidential, or personal information". '
           'המכסה החינמית אינה מותרת ללקוחות API באיחוד האירופי, בבריטניה '
           'ובשווייץ. גיל 18 ומעלה.')
_KEY = ("עם המפתח שאתה הדבקת. אתה הלקוח שלהם — DeskIT הוא הכלי שלך, "
        "ולא עוברת דרכו שום שרת של DeskIT.")
_OFF = "הגדרות > פרטיות > ביטול, או הסרת המפתח."

#: kind -> the card's words. ``version`` is privacy.TEXT_VERSIONS[kind]
#: spelled here too, so a change to the words and a bump of the version
#: land in the same file (a test holds the two equal).
TEXTS: dict[str, dict] = {
    "cloud_text": {
        "version": "groq-2026-06-22+gemini-2026-04-28",
        "title": "לשלוח טקסט לענן?",
        "blocks": (
            (WHAT, "הטקסט שהכתבת או סימנת, עד 5,000 תווים בבקשה. תיקון "
                   "ההכתבה שולח קטעים גם בזמן שהמקש עדיין לחוץ; זוגות "
                   "המילים שלמדת ושמופיעים בטקסט נוסעים איתו; הקריאה "
                   "השנייה מצרפת גם את המשפטים שהוכתבו רגע לפני."),
            (WHOM, "Groq ו/או Google — תיקון, פיסוק, תרגום, חיפוש מילה, "
                   "הקריאה השנייה."),
            (ACCOUNT, _KEY),
            (TERMS, _GROQ + " " + _GEMINI),
            (OFF, _OFF),
        ),
    },
    "cloud_audio": {
        "version": "groq-2026-06-22+gemini-2026-04-28",
        "title": "לשלוח הקלטות לענן?",
        "blocks": (
            (WHAT, "ההקלטה של מה שאמרת עכשיו, כקובץ WAV, עם הנחיית תמלול "
                   "קבועה."),
            (WHOM, "Google (Gemini) או Groq, לתמלול."),
            (ACCOUNT, _KEY),
            (TERMS, _GEMINI + " " + _GROQ),
            (OFF, _OFF + " המנוע חוזר להיות מקומי."),
        ),
    },
    "cloud_screenshots": {
        "version": "groq-2026-06-22+gemini-2026-04-28",
        "title": "לשלוח תמונת מסך לענן?",
        "blocks": (
            (WHAT, "תמונת JPEG של האזור שסימנת (צלע ארוכה עד 1,344 פיקסלים "
                   "ל-Google, 896 ל-Groq), השאלה שלך, והשאלות והתשובות "
                   "הקודמות באותו כרטיס. תמונת מסך יכולה להכיל דואר, בנק, "
                   "כל מה שהיה על המסך."),
            (WHOM, "Groq ו/או Google, לשאלה על המסך."),
            (ACCOUNT, _KEY),
            (TERMS, _GROQ + " " + _GEMINI),
            (OFF, _OFF),
        ),
    },
    "account": {
        "version": "deskit-terms-0",
        "title": "לפתוח חשבון?",
        "blocks": (
            (WHAT, "מזהה חשבון — אנונימי, או כתובת הדוא\"ל של חשבון Google "
                   "שבחרת להיכנס איתו; שם המחשב הזה; גרסת האפליקציה, גרסת "
                   "Windows, דרגת החומרה."),
            (WHOM, "השרת של DeskIT (Supabase, פרנקפורט) — השרת היחיד של "
                   "DeskIT."),
            (ACCOUNT, "על חשבון הפרויקט של DeskIT; המפתחות שלך לעולם לא "
                      "נוסעים לשם — אין להם אפילו עמודה בבסיס הנתונים."),
            (TERMS, "תנאי השימוש בעמוד אחד, ומדיניות הפרטיות."),
            (OFF, "הנתונים שלי > מחיקת החשבון."),
        ),
    },
    "report_upload": {
        "version": "deskit-terms-0",
        "title": "לשלוח דיווחי בעיות?",
        "blocks": (
            (WHAT, "רק מה שהתצוגה המקדימה של הדיווח הראתה — אחרי ניקוי."),
            (WHOM, "השרת של DeskIT (Supabase, פרנקפורט)."),
            (ACCOUNT, "על חשבון הפרויקט של DeskIT, דרך החשבון האנונימי שלך."),
            (TERMS, "תנאי השימוש בעמוד אחד, ומדיניות הפרטיות."),
            (OFF, "לשמור על המחשב הזה במקום, או הגדרות > פרטיות > ביטול."),
        ),
    },
    "settings_sync": {
        "version": "deskit-terms-0",
        "title": "לסנכרן הגדרות ומילים?",
        "blocks": (
            (WHAT, "השינויים שלך בהגדרות והמילים שלמדת (מה נשמע ומה "
                   "התכוונת) — לעולם לא מפתחות, מקשים, מכשירים, תיקיות "
                   "או מיקומים; לעולם לא שמע, היסטוריה או דיווחים."),
            (WHOM, "השרת של DeskIT (Supabase, פרנקפורט), וממנו לכל מחשב "
                   "שתיכנס אליו עם אותו חשבון."),
            (ACCOUNT, "על חשבון הפרויקט של DeskIT, דרך החשבון שלך."),
            (TERMS, "תנאי השימוש בעמוד אחד, ומדיניות הפרטיות."),
            (OFF, "הגדרות > פרטיות > ביטול."),
        ),
    },
    "history_sync": {
        "version": "deskit-terms-0",
        "title": "לסנכרן את מה שאמרת?",
        "blocks": (
            (WHAT, "כל מה שהכתבת, תרגמת, פיסקת וחיפשת — הטקסט, לא ההקלטה "
                   "— כדי שעמוד \"נאמר\" יהיה זהה בכל מחשב שלך."),
            (WHOM, "השרת של DeskIT (Supabase, פרנקפורט). הוא נשמר בחשבון "
                   "שלך; המפתח של DeskIT יכול טכנית לקרוא אותו — ההגנה "
                   "מפרידה בין משתמשים, לא מפני מנהל הפרויקט."),
            (ACCOUNT, "על חשבון הפרויקט של DeskIT, דרך החשבון שלך."),
            (TERMS, "תנאי השימוש בעמוד אחד, ומדיניות הפרטיות."),
            (OFF, "הגדרות > פרטיות > ביטול; \"מחיקת החשבון\" מוחקת גם את "
                  "מה שכבר סונכרן."),
        ),
    },
}


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
                       rtl=True, single=False)
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
    title = _text(cache, card["title"], TITLE_PT * s, weight=600)
    items = [("title", title, y)]
    y += title.height + 8 * s
    for label, text in card["blocks"]:
        lab = _text(cache, label, LABEL_PT * s, colour=INK_FAINT, weight=600)
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
    for kind, piece, y in lay["items"]:
        img.alpha_composite(piece, (int(right - piece.width), int(y)))
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
