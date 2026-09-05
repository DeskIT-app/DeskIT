"""A box that shows you a translation and changes nothing at all.

The lookup key answers a question about text you are READING — a word in
a web page, a line in a PDF, a message in a chat window, a field that is
read-only anyway. So the answer cannot be typed, pasted or written back
anywhere; it has to be drawn on top of whatever you were looking at. That
is all this module is: one small always-on-top window that never takes
focus, never appears in the taskbar, has no keyboard of its own, and goes
away when you close it.

WHY RAW WIN32 AND NOT TK, WHICH THE APP ALREADY HAS
---------------------------------------------------
Tk 8.6 reorders the letters inside a Hebrew run correctly, but it has no
way to set a paragraph's BASE direction, and its base direction is LTR.
Measured on this machine on 2026-08-19, screenshotted and compared glyph
by glyph:

    logical  "א ב ג ד ה."
    Tk       puts the full stop at the far RIGHT   (wrong)
    here     puts the full stop at the far LEFT    (right)

    logical  "אב גד ABC הו כל."
    Tk       renders  גד אב ABC כל הו .
    here     renders  . כל הו ABC גד אב

Read the Tk line as Hebrew and the two halves of the sentence have swapped
around the English term. That is not a cosmetic difference, and it is the
common case here: a Hebrew answer with a model id, a product name or an
acronym sitting in the middle of it.

DrawTextW goes through Uniscribe, so DT_RTLREADING hands the OS's own bidi
algorithm the right base direction and everything downstream of it —
mirrored brackets, trailing punctuation, digit runs, niqqud — comes out
right with no extra dependency. Two things must NOT be added on top of it:
python-bidi (feeding Windows an already-reordered string makes it reorder
a second time and the alphabet comes out backwards) and SetLayout with
LAYOUT_RTL (that mirrors the whole DC, not the text).

The font is created with DEFAULT_CHARSET even though DT_RTLREADING is
documented as needing a Hebrew or Arabic font selected into the DC.
Measured: DEFAULT_CHARSET and HEBREW_CHARSET produced byte-identical PNGs
on all four samples. Nothing here is "missing a charset" — do not add one.

WHY `rtl` IS AN ARGUMENT AND NEVER A GUESS
------------------------------------------
Both earlier prototypes sniffed the direction from the first strong
character of the string. That classifies

    "Whisper הוא מודל תמלול של OpenAI."

as LTR, which puts `Whisper` leftmost and the full stop rightmost —
subject and object inverted for a Hebrew reader. In the owner's own
transcripts.log, 9 of 624 real Hebrew lines (1.4 %) start with a Latin
word, and once wrapping moves a Latin token to the start of a wrapped
line, 66 of the 464 strings that wrap have at least one line flipped. The
caller already knows which language it asked the model to answer in, so
the caller says so, per show(), and the text is never consulted.

`rtl` decides three more things now: which end of the title bar the two
buttons sit at, which end of it the label starts from, and which edge of
the box is pinned to the selection. All three are the reading side.

WHY IT APPEARS AT THE SELECTION AND NOT IN A CORNER
---------------------------------------------------
It used to open bottom-right, on the argument that a box which lands ON
the words you were reading is worse than one out of the way. Both halves
of that were wrong in practice. The corner is 1400 px from what you were
looking at — far enough that finding the answer is a separate act of
attention, which is most of what "it feels slow" turns out to mean — and
"near" does not have to mean "on top of": show(anchor=...) offsets the box
below and to the reading side of the point you asked from, by `gap`
pixels, and flips above or across when there is no room, so the anchor
itself is never covered. It is clamped to the WORK AREA of the monitor the
ANCHOR is on, which matters here: SM_CXVIRTUALSCREEN is a WIDTH and not a
right edge, this machine's left monitor starts at x = -1920 (measured
SM_XVIRTUALSCREEN = -1920, SM_CXVIRTUALSCREEN = 4480), and clamping into
0..width teleports every box opened on the left screen onto the primary
one.

anchor=None keeps the old bottom-right behaviour, which is what the CLI
probe and the tests use, and what the app falls back to when it has no
idea where you were pointing.

WHY THERE IS A TITLE BAR, AND WHY IT IS THE ONLY HANDLE
-------------------------------------------------------
The box used to be draggable from every pixel of itself, which is the
obvious rule for a window with no frame and the wrong one: it made the
answer un-selectable, because a press on the text was already spoken for.
The owner's words were "only the top bar moves it, and everything else I
can just select and copy whatever I choose from it", and that is how every
other window on his screen behaves.

So there is a bar: 30 px, a ground a quarter of the way from BG to EDGE,
a hairline under it, and the buttons in it. A press on the bar takes hold
of the box. A press anywhere below it takes TEXT instead — see the next
section — and the two can never turn into one another, because _zone_at()
decides once, at the press, and the gesture keeps whatever it was for as
long as the button is down.

It carries a caption rather than being empty chrome: the term that was
looked up when the caller passes one (show(term=...)), and the language
the answer came back in when it does not — see _bar_label(). Either way it
is a passenger. The label is painted with DT_END_ELLIPSIS into whatever
room the buttons leave in a width the ANSWER decided, so no caption can
ever make the box wider.

The buttons mirror with `rtl` like everything else here: close at the far
corner on the reading side, copy just inside it, and inside that again
the one that copies the SELECTION, which is invisible until there is a
selection to copy. Its room is reserved from the moment there is an
answer, so nothing in the bar moves under the hand when a line is taken.
Both copy buttons put text on the clipboard through injector.set_text, on
a thread of their own — see _fire_copy — and neither saves and restores
what was there before. Every other clipboard path in this app does; these
must not. A copy the user asked for is meant to survive.

WHY THE ANSWER IS SELECTABLE BY THE LINE AND NOT BY THE LETTER
--------------------------------------------------------------
"Everything else I can just select and copy whatever I choose from it"
was the second half of the owner's sentence, and the unit he chooses
between is a line: the headline, or sense 2 but not sense 3. So a press
in the body takes the line under it, a drag takes the range, a
double-click takes the whole sense it landed in, and the highlight is a
band drawn in the app's own palette — ACCENT taken down to #1d365c —
rather than the system's blue slab, which on this ground would shout.

Character-level selection was measured and turned down. DrawTextW offers
no hit test, so a caret between two letters needs Uniscribe
(ScriptStringXtoCP), which means a SECOND shaping engine deciding where
the lines break while the first one paints them. That mixture is not
survivable, and this is the measurement that says so: a greedy wrap and
DT_WORDBREAK were run over the same 4896 strings (this app's own
transcripts.log, four widths, three faces, 2026-08-20) and disagreed
about the NUMBER OF LINES on 255 of them. Anything measured with one and
painted with the other is wrong on five per cent of long answers.

So there is one engine, and it is _wrap(). The breaks are decided here,
every visual line gets a rectangle of its own, and DrawTextW is handed
one line at a time with DT_SINGLELINE and the same DT_RTLREADING |
DT_RIGHT it always had — the flags that make Hebrew come out in the right
order are untouched, and _layout, _trim, _break_long_tokens and measure()
all go on working on the same strings, because they ask _wrap how tall a
block is instead of asking DT_WORDBREAK. Breaks are taken at spaces and
after a hyphen or a maqaf; with that last rule the two engines agree on
4867 of the 4896 (99.4 %), and where they still differ it is by one line
— a box a line taller than it used to be, never a line painted where it
was not measured.

Hebrew needs nothing special from any of this, and that is the point of
choosing the line. The highlight is a rectangle BEHIND a line, so no bidi
question arises about which glyphs it covers; and what a copy puts on the
clipboard is the same logical string DrawTextW was handed, so a line with
an English term inside Hebrew copies the term where it belongs and not
where it appeared.

The cost, plainly: you cannot take half a line. That is what the copy-all
button is for, and it is why the double-click takes a whole sense rather
than a word — a word would need the hit test that is not here.

WHY THE DRAG IS WRITTEN OUT BY HAND
-----------------------------------
"Near the selection" is a guess made from a mouse point, and a guess
sometimes lands on the next thing you wanted to read. So the box moves:
press the bar and it follows the cursor.

Two lines of WM_NCHITTEST returning HTCAPTION is the usual way to get
that, and it cannot be used here — though not for the reason it is
usually turned down. Measured on this machine on 2026-08-20: the same
window, the same styles, only WM_NCHITTEST overridden, a 200 x 100 px
drag driven with SendInput, twice.

    the foreground window        unchanged, before, during and after
    the box                      moved, exactly as asked
    an update() posted mid-drag  STILL QUEUED after the release

WS_EX_NOACTIVATE holds, so HTCAPTION does not in fact steal the focus.
What it does is hand the gesture to the OS's modal move loop, which runs
a GetMessage of its own on this thread — and a message posted with
PostThreadMessageW has no window to be dispatched to, so the move loop
takes it out of the queue and drops it on the floor. That message IS the
wake-up between the app and this window (_post, below), so the "…" stays
on screen and the answer sits in _cmds, unread until some later lookup
happens to poke the thread. In the probe the box was still showing its
first string after the drag, and only the second post drained both.

SetCapture does none of that. It does not activate, focus or raise
anything; the wndproc returns between every mouse message, so the pump
keeps draining; and the capture is what makes the rest of the gesture
arrive after the pointer has left a box this small, which is a few
pixels of real hand movement. The cost is that everything a move loop
would have given for free is written out here instead: the threshold,
the release, and a capture that can be taken away — _begin_drag,
_drag_to and _end_drag.

Where it was dragged to outlives the answer arriving, and nothing else:
update() re-measures the box and keeps the corner you left it at
(_refit), while a NEW lookup is a new question and opens at the new
anchor.

The box grows from its anchored corner, not from its top-left: the edge
nearest the anchor is the fixed one, so update() replacing the "…" with a
six-line answer extends the box away from your text instead of pushing it
off the screen. Placement is recomputed on every update for that reason.

WHY NOTHING BUT THE BUTTON AND Esc CLOSES IT
--------------------------------------------
Three rules used to close this box on their own: a dwell timer, the next
keystroke, and WM_MOUSELEAVE. The owner's report was "it disappears
randomly, maybe because of the wheel", and the mouse rule is enough on its
own to explain all of it — a box that opens under a stationary cursor is
one twitch away from a leave event, and now that it opens AT the selection
it opens under the cursor almost every time. A box you cannot read is
worse than no box.

So: a close button you click, and Esc. That is the whole list. A click
anywhere else in the box changes what is SELECTED and nothing else — on
the bar it takes hold of the box, but a press that never travels the four
pixels Windows calls a drag lets go of it again; in the body it takes a
line, and a line taken and let go of again is still a box on screen. The
mouse may sit on the box and wander off it, and every key except Esc goes
to whatever you were typing into without the box noticing. `dwell_ms` is
still accepted and still honoured if a caller passes a positive number,
because silently ignoring an argument is worse than not having one — but
the app passes 0 now and the box stays until it is closed.

The cost of that is a box that can be left behind, so every way of taking
one down was checked on 2026-08-19 with a live window: hide() while it is
up, a second show() over a live box (it moves and re-fits), stop() (the
window is gone, IsWindow false), and a process that exits having forgotten
stop() entirely — which the atexit hook in __init__ covers, measured with
a probe registered before the Popup so it runs after the hook: IsWindow
false at the very end of interpreter shutdown.

WHY THE ANSWER IS DRAWN AS STRUCTURE AND NOT AS A BLOB
------------------------------------------------------
lookup.word_prompt() asks for an answer with a shape — the translation
alone on the first line, then numbered sense lines — and drawing that as
one paragraph throws the shape away, which is exactly the information you
tapped the key for. The headline goes in a larger semibold face, a
hairline separates it, and the senses are smaller and dimmer underneath.
A phrase translation has no such shape and is drawn as one block.

The trap in that is drawing what was not measured. Every block's rectangle
is computed ONCE, in _layout(), and _paint() only fills them in: same
strings, same fonts, same flags, no second opinion about how the text
wraps. _flags() is shared for the same reason.

WHY IT OWNS A THREAD INSTEAD OF BORROWING THE HOOK'S
----------------------------------------------------
hotkey.HookThread (hotkey.py:505) already runs a GetMessageW pump, and
this window was measured working on it. It still must not live there.
That thread also runs the WH_KEYBOARD_LL callback, and Windows silently
unhooks a low-level hook whose callback overruns LowLevelHooksTimeout
(300 ms by default) — no exception, no return code, nothing in the log;
every hotkey in the app simply stops working until it is restarted.
WM_PAINT here costs 2.22 ms median and 4.59 ms at worst over 40 repaints
of the word and paragraph answers (2026-08-19; it was 0.78 ms before the
structured layout, which is four DrawTextW calls instead of one plus the
button). Nowhere near 300 ms — but a font fallback being loaded from disk
or a monitor query on an unhappy display driver is not bounded by
anything this repo controls. Twenty lines of thread is a cheap firebreak
in front of "the dictation key did nothing".

WHY IT CANNOT DISMISS ITSELF ON A KEYSTROKE
-------------------------------------------
A window that never takes focus never receives WM_KEYDOWN — there is no
key for it to receive. The keyboard hook is the only thing in the process
that sees one, so on_key() below is called BY the hook, on the hook's
thread, and does no window work of its own: it posts.

That is also the only way Ctrl+C can reach a selection in this box, and
it is why the swallow is gated as hard as it is — five conditions, all of
them in on_key(). The BUTTON is the primary way to copy a selection and
the chord is an accelerator on top of it, because a swallowed Ctrl+C that
was meant for the window underneath is a silent theft: nothing lands on
the clipboard that the user expects, and there is no error to see.

WHY THE ANSWER SHRINKS BEFORE IT IS CUT
---------------------------------------
The box is capped — max_width x max_height, config's knobs, the work-area
argument in _place() says why — and an answer taller than the cap used to
lose its tail to an ellipsis at the normal face, full stop. The owner's
report was a paragraph translation whose last lines never arrived: "the
text doesn't enter the box". His spec, verbatim: there is a maximum size
the box opens to, and the text size should change so everything fits.

So _layout() now descends: measure at the default face; if anything was
trimmed, measure again one step smaller (every role scaled off the same
base, headline and senses together); stop at the first size where nothing
is trimmed, or at min_font_px — 11 px — where Hebrew in Segoe UI stops
being readable and an unreadable whole answer loses to a readable one
with an ellipsis. Only past the floor do words get given up, and they are
given up from the floor-sized layout, which shows strictly more of the
answer than the old default-size trim did.

The descent re-wraps per size because it must: line breaks depend on the
face (measured disagreement between engines at ONE width is the reason
_wrap() exists at all), so there is no honest shortcut from one size's
breaks to another's. Cost is bounded and measured, 2026-08-22 on this
machine: the binary search over every 1 px step from the default down to
the floor — five layouts in the worst case, trim included — runs in
0.7 ms median for a dictionary answer, 2.1 ms for the 60-word sample,
11.9 ms for 180 words, and 21.7 ms median / 24.6 ms worst for a
4056-char answer near lookup.max_chars' guard. That is on this window's
own thread, where latency answers to a human reading and not to a
keyboard hook's 300 ms guillotine — and since the same day, a DRAG never
pays it inline: the frame moves first (see _resize_to) and the search
runs on the _REFIT_MS throttle. It was NOT free to get here either: with
the old word-boundary binary-search _trim the same descent measured
699 ms median, which is why trim now keeps whole wrapped lines (one wrap)
instead of re-wrapping a candidate prefix per probe, and why _run_width
memoizes chunks across one descent.

A hand can buy the rest back: the resizer below sets a bigger cap, and
the gesture refits from the FULL answer (`_answer`), so words an earlier
cap cut off return as the box grows.

WHY THERE IS A RESIZER, AND WHY IT LIVES IN BOTH BOTTOM CORNERS
---------------------------------------------------------------
Auto-fit trades legibility for completeness when the cap is small. The
hand should be allowed to make the opposite trade — more screen, bigger
type — and every other window on this machine offers exactly that grip.
There are TWO of them here, an _RESIZE square in EACH bottom corner, and
that is a correction measured in the field: the first cut had one, in
whichever corner was DIAGONALLY OPPOSITE the close button — bottom-right
on a Hebrew box, bottom-left on an English one — and which corner worked
therefore depended on the ANSWER's language. The same grab on the same
spot grew one box and did nothing at all to the next ("I drag the
bottom-right corner down-down-down and it does nothing. If I move it to
the right, it opens; to the left, it opens and moves it down", the owner,
2026-08-22). Both corners resize now, each against its own fixed top
corner, and pulling OUTWARD is growth everywhere. The press routing is
still the same single-decision function as everything else: _zone_at()
answers once, at the press, and a resize gesture can no more turn into a
selection than a move gesture can.

The first cut of this let the box HUG its text within the requested cap —
every pixel honest, and in the field, broken: once the answer fitted, the
corner stopped under the cursor, and catching up meant dragging far past
where you wanted the edge ("it gets stuck … I have to really go down … it
doesn't go down with me", the owner, 2026-08-22). So now the window IS
the size the hand asked for, verbatim, every move — up to the FULL
monitor rect, again on his words ("any size I want, to the point where
it's full screen"; the old monitor-minus-margin cap was a ceiling he hit
long before the screen ran out) — and auto-fit lays the answer out INSIDE
that frame.

And inside that frame the type ZOOMS. The third report was "I'm trying
to enlarge it, but it's not growing": with the face capped at the 19 px
default, enlarging only piled invisible dark slack under short answers —
the frame obeyed and nothing appeared to happen. So a HAND-SET frame
searches faces on both sides of the default (see _layout): growing the
box grows the type, continuously in 1 px steps up to _FACE_MAX, until
the answer fills what you made or hits the ceiling. Direct manipulation
first, typography second — but typography still follows, which is the
whole point of making the frame bigger.

The size is a property OF THE ANSWER, like the position: kept across
update() (same question, the "…" becoming the reply) and dropped by the
next show(), exactly as a dragged position is dropped by a new anchor. A
box that reopened huge for a two-word answer would be the tail wagging
the dog.

THREE THINGS IT MUST NOT DO, the same list as overlay.py
--------------------------------------------------------
- Steal focus. You may well be typing. WS_EX_NOACTIVATE, plus
  WM_MOUSEACTIVATE answered with MA_NOACTIVATE so even a click straight
  on the close button leaves the caret where it was.
- Land in the taskbar or Alt-Tab. WS_EX_TOOLWINDOW, no WS_EX_APPWINDOW,
  and no owner window.
- Take the app down with it. Every entry point is wrapped. But the
  failure is LOGGED to the "app" logger: a swallowed one is how a box
  that never appeared looks exactly like a box that did.
"""
from __future__ import annotations

import atexit
import collections
import ctypes
import ctypes.wintypes as w
import logging
import re
import threading
import time
import unicodedata

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
try:
    dwmapi: ctypes.WinDLL | None = ctypes.WinDLL("dwmapi")
except OSError:                 # pre-Vista, or a stripped image
    dwmapi = None

log = logging.getLogger("app")

LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, w.HWND, w.UINT, w.WPARAM, w.LPARAM)

CS_HREDRAW, CS_VREDRAW = 0x0002, 0x0001
CS_DBLCLKS = 0x0008
CS_DROPSHADOW = 0x00020000
WS_POPUP = 0x80000000
WS_EX_TOPMOST, WS_EX_TOOLWINDOW = 0x00000008, 0x00000080
WS_EX_LAYERED, WS_EX_NOACTIVATE = 0x00080000, 0x08000000
SW_HIDE, SW_SHOWNOACTIVATE = 0, 4
HWND_TOPMOST = -1
SWP_NOACTIVATE, SWP_SHOWWINDOW = 0x0010, 0x0040
SWP_NOSIZE, SWP_NOZORDER = 0x0001, 0x0004
WM_DESTROY, WM_QUIT, WM_PAINT = 0x0002, 0x0012, 0x000F
WM_ERASEBKGND = 0x0014
WM_TIMER, WM_MOUSEACTIVATE, WM_MOUSEMOVE = 0x0113, 0x0021, 0x0200
WM_LBUTTONDOWN, WM_LBUTTONUP = 0x0201, 0x0202
WM_LBUTTONDBLCLK = 0x0203
MK_LBUTTON = 0x0001
WM_MOUSELEAVE = 0x02A3
WM_SETCURSOR, WM_CAPTURECHANGED = 0x0020, 0x0215
_WM_COMMAND = 0x8000 + 1        # WM_APP + 1: our own, posted to the thread
MA_NOACTIVATE = 3
DT_RIGHT, DT_SINGLELINE = 0x0002, 0x0020
DT_VCENTER = 0x0004
DT_CALCRECT, DT_NOPREFIX = 0x0400, 0x0800
DT_END_ELLIPSIS = 0x00008000
DT_RTLREADING = 0x00020000
TRANSPARENT, LWA_ALPHA = 1, 0x02
DEFAULT_CHARSET, CLEARTYPE_QUALITY = 1, 5
FW_NORMAL, FW_SEMIBOLD = 400, 600
PS_SOLID, NULL_BRUSH, NULL_PEN = 0, 5, 8
TME_LEAVE = 0x0002
MONITOR_DEFAULTTONEAREST = 2
SM_CXSCREEN, SM_CYSCREEN = 0, 1
# The slop Windows itself allows inside a click before calling it a drag,
# asked for rather than assumed: it is a user setting (Explorer's
# DragWidth/DragHeight), 4 px each on a default install.
SM_CXDRAG, SM_CYDRAG = 68, 69
IDC_ARROW, IDC_IBEAM, IDC_SIZEALL = 32512, 32513, 32646
# The two diagonal resize cursors. Which one a grip wears follows the
# corner it lives in: a bottom-right grip drags the south-east edge and
# takes the NWSE cursor, a bottom-left grip the mirror image.
IDC_SIZENWSE, IDC_SIZENESW = 32642, 32643
HTCLIENT = 1
VK_ESCAPE = 0x1B
# The copy chord, and the three modifiers that must NOT be down with it.
# Ctrl+Shift+C is the browsers' inspector, Ctrl+Alt+C is a chord half the
# world binds, and Win+Ctrl+C is Windows' own colour filters: swallowing
# the plain chord and nothing else is the difference between an
# accelerator and a key that goes missing.
VK_C = 0x43
VK_SHIFT, VK_CONTROL, VK_MENU = 0x10, 0x11, 0x12
VK_LWIN, VK_RWIN = 0x5B, 0x5C
_TIMER_ID = 1
# The second timer: how long the copy button wears a tick. Long enough to
# be seen after the eye has left the button, short enough that it is gone
# before the next question is asked.
_FLASH_TIMER_ID = 2
_FLASH_MS = 1400
# The third timer: how often a drag REFLOWS the answer inside the frame
# its grip has already drawn. THE FRAME IS NEVER ON THIS TIMER — it moves
# in the same message the mouse arrives in, verbatim, which is the whole
# lesson of 2026-08-22: re-laying the text out inline made the frame wait
# behind wraps and measures, and a fast hand out-ran it — stick, stick,
# JUMP. Fifty milliseconds is twice a display's refresh budget and a
# quarter of the way to invisible; the text trails the edge by less than
# the eye holds.
_RESIZE_TIMER_ID = 3
_REFIT_MS = 50
# How hard the copy button tries to get the clipboard. See _copy_now: the
# contention this covers is another THREAD OF THIS PROCESS, which
# injector's own retry cannot see.
_COPY_TRIES, _COPY_BACKOFF_S = 6, 0.06

# DwmSetWindowAttribute: rounded corners the compositor draws, which are
# antialiased and get a real shadow, where SetWindowRgn's are stair-cased.
# Windows 11 21H2 and later; the return value is checked and the region
# fallback below runs on anything older.
DWMWA_WINDOW_CORNER_PREFERENCE, DWMWCP_ROUND = 33, 2
DWMWA_BORDER_COLOR = 34

# The one string the module puts on screen itself: the box appears with
# this the instant the key is tapped, and update() replaces it with the
# answer. Shown in DIM, because it is the app talking, not the text.
WAITING = "…"
ELLIPSIS = "…"

# "1. שם תואר - נשבר בקלות" — the shape lookup.word_prompt() asks for. A
# line matching this anywhere below the first is what tells a dictionary
# entry apart from a translated sentence that happens to have two lines.
_SENSE_LINE = re.compile(r"^\d{1,2}[.)]\s*\S")

# One place a line may be broken, plus everything up to it. A match is a
# run of ordinary characters, then any hyphens or maqafs (U+05BE, the
# Hebrew hyphen — "ה-JSON" and "קוד־הדף" are the shapes this repo's own
# text is full of), then any spaces. Concatenated the matches are the
# original string, character for character, which is what lets _wrap()
# make lines out of them without ever inventing or losing one.
#
# Breaking after a hyphen is not decoration: measured 2026-08-20 over
# 4896 strings, adding it took the disagreement with DT_WORDBREAK's own
# line count from 255 down to 29.
_BREAK = re.compile(r"[^\s\u05be-]*[\u05be-]*\s*")

# The twin of injector.CONSOLE_CLASSES, and deliberately a copy. This
# list is read on the OS keyboard-hook thread, where the whole callback
# has 300 ms before Windows silently unhooks it, and importing injector
# there would pull in pywin32 and hotkey the first time somebody pressed
# Ctrl+C. Three strings are cheaper than that risk. Keep them in step.
_CONSOLE_CLASSES = frozenset({
    "CASCADIA_HOSTING_WINDOW_CLASS",   # Windows Terminal
    "ConsoleWindowClass",              # conhost — cmd, PowerShell, ssh
    "PseudoConsoleWindow",             # ConPTY's own hidden host window
})

# The title bar, in pixels. A button is the square you can click and
# _BUTTON_PAD is its inset from the edges of the bar, so the bar's height
# follows from the button rather than being a second number to keep in
# step with it. _BUTTON_GAP separates one button from the next;
# _LABEL_GAP keeps the label off them.
_BUTTON, _BUTTON_PAD, _BUTTON_GAP, _LABEL_GAP = 18, 6, 4, 10
_BAR = _BUTTON + 2 * _BUTTON_PAD
# The narrowest a box may be, so the bar is never buttons edge to edge
# with no room for the label between them. Three buttons' worth, and it
# is spent on every box including the "…", which shows one: a floor that
# changed with the contents would be a second reason for the box to
# resize, and 22 px of extra room on the narrowest box there is buys
# nothing worth that. max_width still wins over it — measure() promises
# never to exceed that and config.py permits 160.
_BAR_MIN = 3 * _BUTTON + 2 * _BUTTON_GAP + 2 * _BUTTON_PAD + 56
# How much bar beside the buttons a drag has to leave on a monitor. The
# rule used to be "the close button stays reachable"; the bar is now the
# only handle, so a box dragged until only the x was on screen would be
# closable and no longer movable. 44 px is a grab, not a pixel hunt.
_GRIP = 44
# How far a selection band reaches past the text it is behind. Into the
# padding, not up to it: a highlight that stops exactly where the glyphs
# do reads as an underline of the widest line rather than as a taken
# line, and the box has 16 px of padding to spend on it.
_SEL_GROW = 4
# The zones that are buttons, as opposed to the handle and the text.
_BUTTONS = ("close", "copy", "copysel")

# AUTO-FIT, or: the answer shrinks before it is cut. An answer taller
# than max_height used to lose its tail to an ellipsis at the normal face,
# full stop. Now the whole layout is re-measured at smaller faces first —
# every role scaled off the same base, so headline and senses shrink
# together — and only when even the floor cannot fit the text does the
# old trim take over. The owner's words: "there is a maximum size the box
# opens to, and the text size should change accordingly so everything
# fits inside".
#
# The floor is a readability line, not a vanity: Segoe UI Hebrew below ~11
# px stops being something you read and becomes something you squint at,
# and an unreadable complete answer loses to a readable one with an
# ellipsis. Measured 2026-08-22 on this machine: three copies of the
# 60-word _PARAGRAPH sample, cut at the default 19 px, fit complete inside
# max_height at 16 px; four copies still do not fit even at the floor —
# too much text, whatever the type — which is why the trim has to survive.
_FONT_FLOOR = 11
# The ZOOM ceiling, for frames the hand set. Auto-fit inside a CONFIGURED
# cap searches downward from the default face only — max_width/max_height
# are maximums, and their whole point was a box that never covers the
# screen. Inside a HAND-SET frame the question inverts: the owner's words
# were "I want to enlarge the text as much as I want, to the point where
# it's full screen", and what he had could not answer them — the face
# stopped at 19 px forever, so enlarging only piled invisible slack under
# the text and looked like the box refusing to grow. So a hand-set frame
# is searched on BOTH sides of the default, and the largest face that
# fits wins, up to this ceiling. 120 px is not a reading size, it is a
# guard: beyond ~400 px a letter is taller than a quarter of a 1440p
# screen — poster size, past which the binary search would spend probes
# and GDI glyph memory on faces nobody can read at reading distance. The
# owner asked for headroom past the old 120 px ceiling he kept hitting;
# 400 gives a fullscreen frame around a short answer room to more than
# triple that.
_FACE_MAX = 400

# THE RESIZER GRIP. A second handle, for size where the bar was for
# position: an _RESIZE square in the bottom corner DIAGONALLY OPPOSITE the
# close button (bottom-right on a Hebrew box, whose close sits top-left;
# bottom-left on an English one). The diagonal keeps the two gestures'
# corners apart — move at the reading end, resize at the far one — the
# same mirror rule every other piece of chrome in this window follows.
_RESIZE = 18
# (The minimum resized size is not a module constant: it follows the bar's
# own furniture and the padding, which are per-instance — see __init__.)


class WNDCLASSW(ctypes.Structure):
    _fields_ = [("style", w.UINT), ("lpfnWndProc", WNDPROC),
                ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
                ("hInstance", w.HINSTANCE), ("hIcon", w.HICON),
                ("hCursor", w.HANDLE), ("hbrBackground", w.HBRUSH),
                ("lpszMenuName", w.LPCWSTR), ("lpszClassName", w.LPCWSTR)]


class PAINTSTRUCT(ctypes.Structure):
    _fields_ = [("hdc", w.HDC), ("fErase", w.BOOL), ("rcPaint", w.RECT),
                ("fRestore", w.BOOL), ("fIncUpdate", w.BOOL),
                ("rgbReserved", ctypes.c_byte * 32)]


class TRACKMOUSEEVENT(ctypes.Structure):
    _fields_ = [("cbSize", w.DWORD), ("dwFlags", w.DWORD),
                ("hwndTrack", w.HWND), ("dwHoverTime", w.DWORD)]


class MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", w.DWORD), ("rcMonitor", w.RECT),
                ("rcWork", w.RECT), ("dwFlags", w.DWORD)]


class GUITHREADINFO(ctypes.Structure):
    _fields_ = [("cbSize", w.DWORD), ("flags", w.DWORD),
                ("hwndActive", w.HWND), ("hwndFocus", w.HWND),
                ("hwndCapture", w.HWND), ("hwndMenuOwner", w.HWND),
                ("hwndMoveSize", w.HWND), ("hwndCaret", w.HWND),
                ("rcCaret", w.RECT)]


class TEXTMETRICW(ctypes.Structure):
    _fields_ = [("tmHeight", ctypes.c_long), ("tmAscent", ctypes.c_long),
                ("tmDescent", ctypes.c_long),
                ("tmInternalLeading", ctypes.c_long),
                ("tmExternalLeading", ctypes.c_long),
                ("tmAveCharWidth", ctypes.c_long),
                ("tmMaxCharWidth", ctypes.c_long),
                ("tmWeight", ctypes.c_long), ("tmOverhang", ctypes.c_long),
                ("tmDigitizedAspectX", ctypes.c_long),
                ("tmDigitizedAspectY", ctypes.c_long),
                ("tmFirstChar", w.WCHAR), ("tmLastChar", w.WCHAR),
                ("tmDefaultChar", w.WCHAR), ("tmBreakChar", w.WCHAR),
                ("tmItalic", ctypes.c_byte),
                ("tmUnderlined", ctypes.c_byte),
                ("tmStruckOut", ctypes.c_byte),
                ("tmPitchAndFamily", ctypes.c_byte),
                ("tmCharSet", ctypes.c_byte)]


# Declared rather than left to ctypes' defaults for the same reason
# hotkey.py declares its hook prototypes: a 64-bit LPARAM overflows the
# default c_int and the call dies with "int too long to convert".
for _fn, _args, _res in [
    ("CreateWindowExW", [w.DWORD, w.LPCWSTR, w.LPCWSTR, w.DWORD]
     + [ctypes.c_int] * 4 + [w.HWND, w.HMENU, w.HINSTANCE, w.LPVOID],
     w.HWND),
    ("DefWindowProcW", [w.HWND, w.UINT, w.WPARAM, w.LPARAM], LRESULT),
    ("DestroyWindow", [w.HWND], w.BOOL),
    ("ShowWindow", [w.HWND, ctypes.c_int], w.BOOL),
    ("IsWindowVisible", [w.HWND], w.BOOL),
    ("InvalidateRect", [w.HWND, ctypes.c_void_p, w.BOOL], w.BOOL),
    ("UpdateWindow", [w.HWND], w.BOOL),
    ("SetWindowPos", [w.HWND, w.HWND] + [ctypes.c_int] * 4 + [w.UINT],
     w.BOOL),
    ("SetLayeredWindowAttributes",
     [w.HWND, w.DWORD, ctypes.c_ubyte, w.DWORD], w.BOOL),
    ("SetWindowRgn", [w.HWND, w.HANDLE, w.BOOL], ctypes.c_int),
    ("BeginPaint", [w.HWND, ctypes.POINTER(PAINTSTRUCT)], w.HDC),
    ("EndPaint", [w.HWND, ctypes.POINTER(PAINTSTRUCT)], w.BOOL),
    ("GetClientRect", [w.HWND, ctypes.POINTER(w.RECT)], w.BOOL),
    ("GetWindowRect", [w.HWND, ctypes.POINTER(w.RECT)], w.BOOL),
    ("DrawTextW", [w.HDC, w.LPCWSTR, ctypes.c_int, ctypes.POINTER(w.RECT),
                   w.UINT], ctypes.c_int),
    ("FillRect", [w.HDC, ctypes.POINTER(w.RECT), w.HBRUSH], ctypes.c_int),
    ("FrameRect", [w.HDC, ctypes.POINTER(w.RECT), w.HBRUSH], ctypes.c_int),
    ("GetDC", [w.HWND], w.HDC),
    ("ReleaseDC", [w.HWND, w.HDC], ctypes.c_int),
    ("SetTimer", [w.HWND, ctypes.c_void_p, w.UINT, ctypes.c_void_p],
     ctypes.c_void_p),
    ("KillTimer", [w.HWND, ctypes.c_void_p], w.BOOL),
    ("TrackMouseEvent", [ctypes.POINTER(TRACKMOUSEEVENT)], w.BOOL),
    ("GetCursorPos", [ctypes.POINTER(w.POINT)], w.BOOL),
    ("MonitorFromPoint", [w.POINT, w.DWORD], w.HANDLE),
    ("GetMonitorInfoW", [w.HANDLE, ctypes.POINTER(MONITORINFO)], w.BOOL),
    ("GetSystemMetrics", [ctypes.c_int], ctypes.c_int),
    ("PostThreadMessageW", [w.DWORD, w.UINT, w.WPARAM, w.LPARAM], w.BOOL),
    ("GetMessageW", [ctypes.POINTER(w.MSG), w.HWND, w.UINT, w.UINT],
     ctypes.c_int),
    ("TranslateMessage", [ctypes.POINTER(w.MSG)], w.BOOL),
    ("DispatchMessageW", [ctypes.POINTER(w.MSG)], LRESULT),
    ("RegisterClassW", [ctypes.POINTER(WNDCLASSW)], w.ATOM),
    ("LoadCursorW", [w.HINSTANCE, ctypes.c_void_p], w.HANDLE),
    ("SetCursor", [w.HANDLE], w.HANDLE),
    ("SetCapture", [w.HWND], w.HWND),
    ("ReleaseCapture", [], w.BOOL),
    ("GetCapture", [], w.HWND),
    ("GetForegroundWindow", [], w.HWND),
    ("GetGUIThreadInfo", [w.DWORD, ctypes.POINTER(GUITHREADINFO)], w.BOOL),
    ("GetWindowThreadProcessId", [w.HWND, ctypes.POINTER(w.DWORD)],
     w.DWORD),
    ("GetAsyncKeyState", [ctypes.c_int], ctypes.c_short),
    ("GetClassNameW", [w.HWND, w.LPWSTR, ctypes.c_int], ctypes.c_int),
    ("ClientToScreen", [w.HWND, ctypes.POINTER(w.POINT)], w.BOOL),
    ("ScreenToClient", [w.HWND, ctypes.POINTER(w.POINT)], w.BOOL),
    ("IsWindow", [w.HWND], w.BOOL),
]:
    getattr(user32, _fn).argtypes = _args
    getattr(user32, _fn).restype = _res

for _fn, _args, _res in [
    ("CreateFontW", [ctypes.c_int] * 8 + [w.DWORD] * 5 + [w.LPCWSTR],
     w.HFONT),
    ("CreateSolidBrush", [w.COLORREF], w.HBRUSH),
    ("CreatePen", [ctypes.c_int, ctypes.c_int, w.COLORREF], w.HANDLE),
    ("CreateRoundRectRgn", [ctypes.c_int] * 6, w.HANDLE),
    ("RoundRect", [w.HDC] + [ctypes.c_int] * 6, w.BOOL),
    ("MoveToEx", [w.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_void_p],
     w.BOOL),
    ("LineTo", [w.HDC, ctypes.c_int, ctypes.c_int], w.BOOL),
    ("SelectObject", [w.HDC, w.HANDLE], w.HANDLE),
    ("GetStockObject", [ctypes.c_int], w.HANDLE),
    ("DeleteObject", [w.HANDLE], w.BOOL),
    ("SetTextColor", [w.HDC, w.COLORREF], w.COLORREF),
    ("SetBkColor", [w.HDC, w.COLORREF], w.COLORREF),
    ("SaveDC", [w.HDC], ctypes.c_int),
    ("RestoreDC", [w.HDC, ctypes.c_int], w.BOOL),
    ("IntersectClipRect", [w.HDC] + [ctypes.c_int] * 4,
     ctypes.c_int),
    ("SetBkMode", [w.HDC, ctypes.c_int], ctypes.c_int),
    ("GetTextMetricsW", [w.HDC, ctypes.POINTER(TEXTMETRICW)], w.BOOL),
]:
    getattr(gdi32, _fn).argtypes = _args
    getattr(gdi32, _fn).restype = _res

if dwmapi is not None:
    dwmapi.DwmSetWindowAttribute.argtypes = [w.HWND, w.DWORD,
                                             ctypes.c_void_p, w.DWORD]
    dwmapi.DwmSetWindowAttribute.restype = ctypes.c_long


# ------------------------------------------------------- uniscribe (usp10)
#
# The character hit test, and the only renderer that draws a selection the
# way a bidi reader expects one.
#
# DrawTextW has no hit test at all: it will put "Whisper הוא מודל" on
# screen but it will not say which letter is under x=213, so a selection
# finer than a whole line cannot be made from it. ScriptStringAnalyse does
# both — ScriptStringXtoCP answers the hit test, and ScriptStringOut draws
# the line AND its selected range.
#
# THAT SECOND HALF IS WHY EVERY LINE IS DRAWN HERE AND NOT ONLY THE
# SELECTED ONE. Two renderers painting alternate lines of the same
# paragraph is how a line comes to shift the moment it is selected, which
# is the one thing the owner asked not to happen. So there is one painter,
# as there is one wrapper.
#
# The switch is free, and that is measured rather than assumed: the same
# line rendered both ways into two identical DIBs and compared byte for
# byte came back IDENTICAL on all 610 samples — ten hand-picked shapes
# (Hebrew, Hebrew with a Latin term, digits, percent, brackets, a maqaf,
# French accents, Indonesian) and 600 real lines out of this app's own
# transcripts.log (2026-08-20). Checked again on the whole window rather
# than a line: every pixel inside the box identical to what DrawTextW
# left there, against a control that rendered the same painter twice and
# differed by nothing. DrawTextW goes through Uniscribe itself, so this
# is not a coincidence; it is the same shaper reached one layer lower
# down.
#
# It is only free if ScriptStringOut is called the way _paint_line calls
# it. Handing it the row rectangle instead of NULL cost 368 pixels of a
# 265 px box, each one value in 255 out — the fill changes the ground
# the glyphs are blended against, and ClearType notices.
#
# A SCRIPT_STRING_ANALYSIS REMEMBERS THE DC IT WAS ANALYSED AGAINST and
# draws through that one. Analysing against a DC that is then released
# paints nothing at all, silently. So every analysis here is made against
# the DC it is about to be used with, and freed before that DC goes.
usp10 = ctypes.WinDLL("usp10", use_last_error=True)

SCRIPT_STRING_ANALYSIS = ctypes.c_void_p
SSA_FALLBACK, SSA_BREAK, SSA_GLYPHS = 0x0020, 0x0040, 0x0080
SSA_RTL = 0x0100
ETO_OPAQUE = 0x0002


class SCRIPT_CONTROL(ctypes.Structure):
    _fields_ = [("bits", ctypes.c_uint32)]


class SCRIPT_STATE(ctypes.Structure):
    _fields_ = [("bits", ctypes.c_uint16)]


usp10.ScriptStringAnalyse.argtypes = [
    w.HDC, ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    w.DWORD, ctypes.c_int, ctypes.POINTER(SCRIPT_CONTROL),
    ctypes.POINTER(SCRIPT_STATE), ctypes.POINTER(ctypes.c_int),
    ctypes.c_void_p, ctypes.POINTER(ctypes.c_byte),
    ctypes.POINTER(SCRIPT_STRING_ANALYSIS)]
usp10.ScriptStringAnalyse.restype = ctypes.c_long
usp10.ScriptStringOut.argtypes = [
    SCRIPT_STRING_ANALYSIS, ctypes.c_int, ctypes.c_int, w.UINT,
    ctypes.POINTER(w.RECT), ctypes.c_int, ctypes.c_int, w.BOOL]
usp10.ScriptStringOut.restype = ctypes.c_long
usp10.ScriptStringXtoCP.argtypes = [SCRIPT_STRING_ANALYSIS, ctypes.c_int,
                                    ctypes.POINTER(ctypes.c_int),
                                    ctypes.POINTER(ctypes.c_int)]
usp10.ScriptStringXtoCP.restype = ctypes.c_long
usp10.ScriptStringCPtoX.argtypes = [SCRIPT_STRING_ANALYSIS, ctypes.c_int,
                                    w.BOOL, ctypes.POINTER(ctypes.c_int)]
usp10.ScriptStringCPtoX.restype = ctypes.c_long
usp10.ScriptString_pSize.argtypes = [SCRIPT_STRING_ANALYSIS]
usp10.ScriptString_pSize.restype = ctypes.POINTER(w.SIZE)
usp10.ScriptStringFree.argtypes = [ctypes.POINTER(SCRIPT_STRING_ANALYSIS)]
usp10.ScriptStringFree.restype = ctypes.c_long


class _Shaped:
    """One analysed line, tied to one DC, freed on the way out of a `with`.

    `width` is what the line measures, which is what right-alignment is
    computed from: DT_RIGHT is a DrawTextW flag and there is no such flag
    here, so the x an RTL line starts at is worked out rather than asked
    for.
    """

    __slots__ = ("ssa", "width", "height")

    def __init__(self, hdc: int, text: str, rtl: bool) -> None:
        self.ssa = SCRIPT_STRING_ANALYSIS()
        buf = ctypes.create_unicode_buffer(text)
        n = len(text)
        hr = usp10.ScriptStringAnalyse(
            hdc, ctypes.cast(buf, ctypes.c_void_p), n,
            # The documented slack for the glyph buffer. A shaped script
            # can emit more glyphs than it was given characters.
            (3 * n) // 2 + 16,
            -1,                                   # -1 = the string is Unicode
            SSA_GLYPHS | SSA_FALLBACK | SSA_BREAK | (SSA_RTL if rtl else 0),
            -1, None, None, None, None, None, ctypes.byref(self.ssa))
        if hr != 0:
            raise OSError(f"ScriptStringAnalyse failed "
                          f"0x{hr & 0xFFFFFFFF:08X}")
        size = usp10.ScriptString_pSize(self.ssa)
        self.width = int(size.contents.cx) if size else 0
        self.height = int(size.contents.cy) if size else 0

    def __enter__(self) -> "_Shaped":
        return self

    def __exit__(self, *_exc) -> None:
        try:
            usp10.ScriptStringFree(ctypes.byref(self.ssa))
        except Exception:
            pass

    def runs(self, lo: int, hi: int) -> list[tuple[int, int]]:
        """Where the characters [lo, hi) actually are, as x spans.

        USUALLY ONE SPAN AND SOMETIMES TWO, and that is the whole point.
        A range that is contiguous in the string need not be contiguous
        on screen: "isper הוא" out of "Whisper הוא מודל" is one run of
        characters and two blocks of pixels, because the English inside
        the Hebrew is laid out the other way round. Asking each character
        where it went and merging what touches is what finds that out,
        and it is why the highlight can be drawn in this app's own colour
        instead of being left to ScriptStringOut — which paints a
        selection in COLOR_HIGHLIGHT, the system's bright blue, with no
        way to ask it for another.
        """
        spans: list[tuple[int, int]] = []
        for cp in range(max(0, lo), max(0, hi)):
            a, b = ctypes.c_int(), ctypes.c_int()
            if usp10.ScriptStringCPtoX(self.ssa, cp, False,
                                       ctypes.byref(a)) != 0:
                continue
            if usp10.ScriptStringCPtoX(self.ssa, cp, True,
                                       ctypes.byref(b)) != 0:
                continue
            spans.append((min(a.value, b.value), max(a.value, b.value)))
        spans.sort()
        merged: list[tuple[int, int]] = []
        for start, end in spans:
            if merged and start <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], end))
            else:
                merged.append((start, end))
        return merged

    def cp_at(self, x: int) -> int:
        """Which character the point `x` (from the line's left edge) is on.

        Returns a position BETWEEN characters, 0..len(text), which is what
        a selection edge is. `trailing` is Uniscribe saying "past the far
        side of that character", and adding it is what makes a click on
        the right half of a glyph take the boundary after it.

        The answer walks the LINE, not the string: in "Whisper הוא מודל"
        laid out right to left, x just inside the right edge is the last
        letter of Whisper and a few pixels further left is its first. That
        looks like the caret jumping to the other side of the word, and it
        is exactly what a browser does with the same text.
        """
        cp, trailing = ctypes.c_int(), ctypes.c_int()
        if usp10.ScriptStringXtoCP(self.ssa, int(x), ctypes.byref(cp),
                                   ctypes.byref(trailing)) != 0:
            return 0
        return max(0, cp.value + trailing.value)


def _rgb(r: int, g: int, b: int) -> int:
    return r | (g << 8) | (b << 16)


# overlay.py's palette, as COLORREFs, so the app looks like one app.
BG = _rgb(0x10, 0x13, 0x1A)         # overlay.BG      #10131a
FG = _rgb(0xE8, 0xEC, 0xF4)         # overlay.FG      #e8ecf4
DIM = _rgb(0x8B, 0x97, 0xAD)        # overlay.DIM     #8b97ad
ACCENT = _rgb(0x2D, 0x6C, 0xDF)     # overlay.ACCENT  #2d6cdf
# The border, the hairline under the headline, and the close button's
# hover fill: BG lifted towards DIM, the same move overlay.py makes for
# its progress trough (#232a36) and its status ring. Not new colours, one
# ramp between two that were already here.
EDGE = _rgb(0x2A, 0x33, 0x42)
HOVER = _rgb(0x1E, 0x25, 0x33)
# The title bar's ground: the same BG-to-EDGE ramp, a quarter of the way
# along instead of half. It has to be visible as a different surface and
# still be quieter than HOVER, or a button under the cursor would stop
# lighting up the moment it moved into the bar.
BAR_BG = _rgb(0x17, 0x1C, 0x25)
# The band behind a selected line: ACCENT taken down until it sits UNDER
# text rather than in front of it. The system's own COLOR_HIGHLIGHT is a
# bright blue slab that would be the loudest thing in a dark box, and a
# selection is not an announcement — it is a note of what you are about
# to copy. It costs contrast, which is why a selected line is also
# lifted to FG: DIM on this ground computes to 4.11:1 against the 6.31:1
# it had on BG — under the 4.5 a 16 px face wants — while FG on it is
# 10.23:1, better than the sense line had unselected. So the band never
# makes anything harder to read, and the lift is the same sentence the
# band is saying twice.
SEL = _rgb(0x1D, 0x36, 0x5C)
# Pressed. overlay.STATES' red, the app's one "this is destructive" colour
# — and the same convention every close button on Windows follows.
PRESSED = _rgb(0xE0, 0x35, 0x2B)

# Brushes and pens for the fixed colours live for the life of the process
# rather than per Popup. They are immutable, they are shared with the
# window class, and one handle each is not a leak — whereas deleting a
# brush a registered class still points at is a dangling handle.
_BRUSHES: dict[int, int] = {}
_PENS: dict[tuple[int, int], int] = {}


def _brush(colour: int) -> int:
    if colour not in _BRUSHES:
        _BRUSHES[colour] = gdi32.CreateSolidBrush(colour)
    return _BRUSHES[colour]


def _pen(colour: int, width: int = 1) -> int:
    key = (colour, width)
    if key not in _PENS:
        _PENS[key] = gdi32.CreatePen(PS_SOLID, width, colour)
    return _PENS[key]


# The OS's own cursors, cached the same way and for the same reason. They
# are shared handles: LoadCursorW hands out the one the system already
# owns, and destroying one would take it away from every other window.
_CURSORS: dict[int, int] = {}


def _cursor(ident: int) -> int:
    if ident not in _CURSORS:
        _CURSORS[ident] = user32.LoadCursorW(None, ctypes.c_void_p(ident))
    return _CURSORS[ident]


# ------------------------------------------------------- window plumbing

_CLASS_NAME = "DeskITLookupPopup"
_class_atom = 0

# A window class is registered once per process but a Popup is an object,
# and the two must not be confused: registering the class with a BOUND
# method would send the second Popup's messages to the first Popup's
# state. So the class holds one module-level wndproc that looks up which
# instance owns the hwnd. _CREATING covers the messages that arrive
# between CreateWindowExW and its return, when the hwnd is not known yet.
_INSTANCES: dict[int, "Popup"] = {}
_CREATING: "Popup | None" = None


def _wndproc(hwnd, msg, wparam, lparam):
    obj = _INSTANCES.get(int(hwnd), _CREATING)
    if obj is not None:
        try:
            handled = obj._on_message(int(hwnd), msg, wparam, lparam)
        except Exception:
            # A wndproc must never raise into the OS; it must also never
            # go quiet, or a popup that stopped repainting is invisible
            # in the log as well as on screen.
            log.exception("lookup popup wndproc (message 0x%04X)", msg)
            handled = None
        if handled is not None:
            return handled
    return user32.DefWindowProcW(hwnd, msg, wparam, lparam)


_PROC = WNDPROC(_wndproc)     # module level, pinned: collected = crash
_CLASS = WNDCLASSW()          # holds _PROC for the class registration


def _register_class() -> None:
    global _class_atom
    if _class_atom:
        return
    # CS_DROPSHADOW is what lifts the box off the page underneath. It is a
    # class style and cannot be added later, which is why it is here and
    # not next to the other window chrome in _create().
    #
    # CS_DBLCLKS is what makes the second of two quick presses arrive as
    # WM_LBUTTONDBLCLK — without it a double-click on a sense is two
    # single clicks and takes the same one line twice. It changes nothing
    # else: WM_LBUTTONDBLCLK is handled exactly as a press everywhere
    # outside the body, so a copy button pressed twice quickly still
    # copies twice.
    _CLASS.style = CS_HREDRAW | CS_VREDRAW | CS_DBLCLKS | CS_DROPSHADOW
    _CLASS.lpfnWndProc = _PROC
    _CLASS.hInstance = kernel32.GetModuleHandleW(None)
    _CLASS.hbrBackground = _brush(BG)
    # Without a class cursor the box inherits whatever the window under it
    # was showing — an I-beam over a close button reads as "still text".
    _CLASS.hCursor = _cursor(IDC_ARROW)
    _CLASS.lpszClassName = _CLASS_NAME
    atom = user32.RegisterClassW(ctypes.byref(_CLASS))
    if not atom:
        err = ctypes.get_last_error()
        if err != 1410:                     # ERROR_CLASS_ALREADY_EXISTS
            raise OSError(f"RegisterClassW failed (WinError {err})")
        atom = 1
    _class_atom = atom


# ------------------------------------------------------------------ text

def _clean(text: str) -> str:
    """Normalise what a model or a clipboard hands us into one paragraph.

    Bidi format characters (RLE, PDF, RLM and friends) are stripped along
    with the other control characters, and that is deliberate: direction
    here is an argument, and a stray embedding mark in a model's answer
    would quietly override the caller's decision from inside the string.
    """
    text = str(text).replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\t", "    ")
    text = "".join(ch for ch in text
                   if ch == "\n" or unicodedata.category(ch)[0] != "C")
    return text.strip()


def _as_rect(anchor) -> tuple[int, int, int, int] | None:
    """A caller's anchor, however they expressed it, as one screen rect.

    A point (x, y) is a rect with no area; a caret or a selection is a
    real one. Anything unreadable comes back as None and the box falls
    back to the corner, because a lookup that shows nothing because its
    anchor was malformed would be the worst possible trade.
    """
    if anchor is None:
        return None
    try:
        if isinstance(anchor, w.RECT):
            vals = [anchor.left, anchor.top, anchor.right, anchor.bottom]
        else:
            vals = [int(v) for v in anchor]
        if len(vals) == 2:
            vals = [vals[0], vals[1], vals[0], vals[1]]
        if len(vals) != 4:
            raise ValueError(f"anchor needs 2 or 4 numbers, got {len(vals)}")
        left, top = min(vals[0], vals[2]), min(vals[1], vals[3])
        right, bottom = max(vals[0], vals[2]), max(vals[1], vals[3])
        return int(left), int(top), int(right), int(bottom)
    except Exception:
        log.debug("lookup popup ignored an unreadable anchor %r", anchor)
        return None


def caret_anchor(hwnd: int | None) -> tuple[int, int, int, int] | None:
    """The text caret of `hwnd`'s thread, in screen pixels, or None.

    GetGUIThreadInfo is the only cross-process way to ask, and what it
    answers depends entirely on whether the app underneath uses a real
    Windows caret. Measured on this machine, 2026-08-19:

        Notepad          rcCaret 1x21 at the insertion point       works
        Explorer search  rcCaret 2x18                              works
        Chrome (address bar and a textarea in a page)  hwndCaret 0  no
        VS Code / any Electron editor                  hwndCaret 0  no

    Chromium draws its own caret and never creates one, so anything built
    on it — Chrome, Edge, VS Code, Slack, Discord — falls through to None
    here and the caller uses the mouse point instead. That is the common
    case, not the exception, which is why the mouse position is the
    primary anchor in main.py and this is only ever an improvement on it.

    Three guards, and every one of them is a real observed shape rather
    than defensive padding: a thread with no caret reports hwndCaret 0
    with a stale rcCaret still in the struct; a minimised or background
    window reports a caret at a plausible-looking client offset that lands
    somewhere else entirely once converted to screen coordinates; and a
    zero-height rect (an app that "has" a caret it never sized) would
    anchor the box to a point that is not on screen.
    """
    try:
        if not hwnd or not user32.IsWindow(w.HWND(hwnd)):
            return None
        tid = user32.GetWindowThreadProcessId(w.HWND(hwnd), None)
        if not tid:
            return None
        gti = GUITHREADINFO()
        gti.cbSize = ctypes.sizeof(GUITHREADINFO)
        if not user32.GetGUIThreadInfo(tid, ctypes.byref(gti)):
            return None
        if not gti.hwndCaret:
            return None
        rc = gti.rcCaret
        high = rc.bottom - rc.top
        wide = rc.right - rc.left
        if high < 4 or high > 200 or wide < 0 or wide > 200:
            return None
        tl, br = w.POINT(rc.left, rc.top), w.POINT(rc.right, rc.bottom)
        if not (user32.ClientToScreen(gti.hwndCaret, ctypes.byref(tl))
                and user32.ClientToScreen(gti.hwndCaret, ctypes.byref(br))):
            return None
        box = w.RECT()
        if not user32.GetWindowRect(w.HWND(hwnd), ctypes.byref(box)):
            return None
        if not (box.left <= tl.x <= box.right
                and box.top <= tl.y <= box.bottom):
            return None
        return int(tl.x), int(tl.y), int(max(br.x, tl.x + 1)), int(br.y)
    except Exception:
        log.debug("lookup popup could not read a caret", exc_info=True)
        return None


def _inside(rect: w.RECT, x: int, y: int) -> bool:
    """Windows' own half-open rule: the right and bottom edges are out."""
    return (rect.left <= x < rect.right and rect.top <= y < rect.bottom)


class _Block:
    """One measured run of text and the exact rectangle it goes in.

    The unit everything upstream of the painting works in: _split makes
    them, _break_long_tokens and _trim cut them about, and the height cap
    is spent on them. Nothing paints a block any more — _Line does that —
    but the block is still what `lay.text` is rebuilt from and what the
    hairline is measured against.
    """

    __slots__ = ("text", "role", "rect")

    def __init__(self, text: str, role: str, rect: w.RECT) -> None:
        self.text, self.role, self.rect = text, role, rect


class _Line:
    """One VISUAL line: what is drawn, and what a press on it takes.

    `rect` is where the glyphs go and what the highlight is drawn behind.
    `hit` is the strip of the body that means this line, and it is not
    the same thing: the strips tile the whole body, meeting halfway
    across the gaps between lines and blocks, so there is nowhere between
    the first line and the last that a press can land and find nothing.
    Below the last line and above the first there IS nothing, and that is
    the only way to let a selection go without closing the box.

    `block` is which _Block it was wrapped out of, which is what a
    double-click takes.
    """

    __slots__ = ("text", "role", "rect", "hit", "block", "size_px")

    def __init__(self, text: str, role: str, rect: w.RECT,
                 block: int, size_px: int) -> None:
        self.text, self.role, self.rect = text, role, rect
        self.block = block
        # The face this line was measured in. One answer can now hold
        # lines from ONE layout only — but that layout's face is not
        # necessarily the instance's default any more (auto-fit), and a
        # line is the unit painting and the hit test both work on, so the
        # size travels with the thing that needs it.
        self.size_px = size_px
        self.hit = (rect.top, rect.bottom)


class _Drag:
    """One press of the mouse that might turn into a move.

    `grab` is the offset from the window's top-left to the point you took
    hold of, and it is what makes the box follow the cursor instead of
    jumping its own corner under it. `start` is where the press landed, in
    screen pixels, and exists only to answer "has this moved far enough to
    be a drag yet" — measuring that from the CURRENT position instead
    would let a slow enough wobble creep the box across the screen a
    sub-threshold pixel at a time.

    `active` is False until the threshold is passed and never goes back:
    once a gesture is a drag it stays one, so a hand that returns to
    within four pixels of where it started mid-drag does not drop the box.
    """

    __slots__ = ("grab_x", "grab_y", "start_x", "start_y", "slop_x",
                 "slop_y", "active")

    def __init__(self, grab_x: int, grab_y: int, start_x: int,
                 start_y: int, slop_x: int, slop_y: int) -> None:
        self.grab_x, self.grab_y = grab_x, grab_y
        self.start_x, self.start_y = start_x, start_y
        self.slop_x, self.slop_y = slop_x, slop_y
        self.active = False


class _Resize:
    """One press on a resize grip that might turn into a resize.

    The move gesture's sibling, built the same way on purpose: SetCapture
    for the gesture, the OS's own DragWidth/DragHeight as the threshold a
    wobble fails, and `active` never going back once set. A press on an
    18 px square shifts a pixel or two as the finger comes down, and that
    is a click, not a resize.

    `grip_right` says WHICH of the two bottom corners is held, because it
    decides two things: the corner the box grows against (`fix_x`/
    `fix_y`, the one diagonally opposite the held grip) and the diagonal
    of the cursor. Every move recomputes the size wanted from the
    cursor's DISTANCE FROM THAT CORNER, not from how far the hand has
    travelled, which is what makes the gesture self-correcting the way
    _drag_to is: a late or coalesced move cannot accumulate error, it
    just lands where the hand is.

    `cap_w`/`cap_h` are the bounds the box's monitor allows — its FULL
    rect, at the owner's request ("any size I want, to the point where
    it's full screen"); the old monitor-minus-margin cap was measured as
    a ceiling he kept hitting before the screen ever ran out.
    """

    __slots__ = ("grip_right", "fix_x", "fix_y", "cap_w", "cap_h",
                 "start_x", "start_y", "slop_x", "slop_y", "active")

    def __init__(self, grip_right: bool, fix_x: int, fix_y: int,
                 cap_w: int, cap_h: int, start_x: int,
                 start_y: int, slop_x: int, slop_y: int) -> None:
        self.grip_right = grip_right
        self.fix_x, self.fix_y = fix_x, fix_y
        self.cap_w, self.cap_h = cap_w, cap_h
        self.start_x, self.start_y = start_x, start_y
        self.slop_x, self.slop_y = slop_x, slop_y
        self.active = False


class _Layout:
    """Everything _paint() is allowed to know. Built once, in _layout().

    `button` is the CLOSE button and keeps that name because it is the
    one rectangle the rest of the module already reasons about. `copy`
    sits beside it and `copysel` inside that, `grip` is the part of the
    bar a drag must leave on a monitor, and `lines` is the body — nothing
    in it overlaps the bar, which is what lets a press below `bar.bottom`
    mean something other than "move me".

    `blocks` and `lines` are two views of the same text and neither is
    redundant: a block is what was MEASURED and trimmed, a line is what
    is painted and what a press selects.

    `size_px` is the base face the whole layout was measured at — the
    default, or whatever auto-fit descended to. `truncated` says whether
    the cap had to cut something off at that size; it is the one bit the
    fit loop reads to decide whether a smaller face would still help.
    `resizer_l`/`resizer_r` are the drag-to-resize squares in BOTH bottom
    corners: whichever the hand grabs, pulling OUTWARD grows, so no answer
    language can make a corner lie about what it does.
    """

    __slots__ = ("text", "rtl", "width", "height", "blocks", "lines",
                 "rule", "bar", "button", "copy", "copysel", "grip",
                 "label", "label_rect", "show_copy", "size_px", "truncated",
                 "resizer_l", "resizer_r")

    def __init__(self, text: str, rtl: bool) -> None:
        self.text, self.rtl = text, rtl
        self.width = self.height = 0
        self.size_px = 0
        self.truncated = False
        self.blocks: list[_Block] = []
        self.lines: list[_Line] = []
        self.rule: w.RECT | None = None
        self.bar = w.RECT(0, 0, 0, 0)
        self.button = w.RECT(0, 0, 0, 0)
        self.copy = w.RECT(0, 0, 0, 0)
        self.copysel = w.RECT(0, 0, 0, 0)
        self.grip = w.RECT(0, 0, 0, 0)
        self.resizer_l = w.RECT(0, 0, 0, 0)
        self.resizer_r = w.RECT(0, 0, 0, 0)
        self.label_rect = w.RECT(0, 0, 0, 0)
        self.label = ""
        self.show_copy = False


class Popup:
    """One always-on-top, never-focused box.

    Create it once, keep it for the life of the app, and call stop() on
    shutdown. Every method is safe to call from any thread — they post to
    the popup's own thread, which is the only one allowed to touch the
    window — and none of them raises: a popup that fails is logged and
    the key it belongs to keeps working without it.
    """

    # role -> (size offset from size_px, weight, colour). The headline is
    # bigger and semibold because it is the answer; the senses are smaller
    # and dimmer because they are the footnotes to it.
    _FACE = {
        "title": (3, FW_SEMIBOLD, FG),
        "body": (0, FW_NORMAL, FG),
        "wait": (0, FW_NORMAL, DIM),
        "sense": (-3, FW_NORMAL, DIM),
        # The bar's label. Smaller than the smallest thing in the answer,
        # because it is a caption on the box and must never be read
        # before the box's contents are.
        "bar": (-5, FW_NORMAL, DIM),
    }

    def __init__(self, *, max_width: int = 460, max_height: int = 520,
                 font: str = "Segoe UI", size_px: int = 19, pad: int = 16,
                 margin: int = 24, alpha: int = 255, corner: int = 10,
                 gap: int = 18, min_font_px: int = _FONT_FLOOR) -> None:
        self.max_width = max(160, int(max_width))
        self.max_height = max(64, int(max_height))
        self.font_name, self.size_px = font, int(size_px)
        # The auto-fit floor. Nothing below this is reading any more; see
        # _FONT_FLOOR above for where the line comes from.
        self.min_font_px = max(9, int(min_font_px))
        self.pad, self.margin = int(pad), int(margin)
        self.alpha, self.corner = int(alpha), int(corner)
        self.gap = max(0, int(gap))
        # How small a hand may make the box: the bar's own
        # three-buttons-and-a-label minimum plus padding across, and the
        # bar plus one line of body plus padding down — exactly the "…"
        # box, so a fully shrunk box is never smaller than the smallest
        # useful one.
        self._min_w = max(self.max_width // 3 + 1,
                          _BAR_MIN + 2 * self.pad)
        self._min_h = max(_BAR + 2 * self.pad + self.size_px,
                          _BAR + 6 + self.min_font_px + self.pad)

        self._hwnd: int | None = None
        self._fonts: dict[tuple[str, int], int] = {}
        # Chunk-width memo for ONE auto-fit descent at a time; see
        # _run_width. None whenever a layout is not running.
        self._wcache: dict[tuple[int, str], int] | None = None
        # The face the last layout was measured at — what a bare
        # _font(role) call means. Real layout and paint paths pass their
        # size explicitly; this only serves callers outside a layout.
        self._active_px = self.size_px
        self._font_lock = threading.Lock()
        self._text, self._rtl = "", True
        # What the clipboard gets: the answer as it ARRIVED, before
        # _layout() trimmed it to fit. A box that had to elide six words
        # off the bottom should still copy all of them — the ellipsis is
        # a property of a 460 px window, not of the answer.
        self._answer = ""
        self._term = ""
        self._dwell_ms = 0
        self._anchor: tuple[int, int, int, int] | None = None
        self._work: w.RECT | None = None
        self._lay: _Layout | None = None
        # Which button the mouse is over and which one a press took hold
        # of: "close", "copy" or None. Strings and not two booleans per
        # button, because exactly one of them can be either at a time.
        self._hover: str | None = None
        self._armed: str | None = None
        # "copied", "busy", or None — what the bar says instead of its
        # label for _FLASH_MS after a copy button was pressed, and which
        # of the two buttons wears the tick.
        self._flash: str | None = None
        self._flash_on = "copy"
        # The selection: two (line, character) points into lay.lines, in
        # document order, or None for "nothing is taken". The character
        # is a position BETWEEN characters, 0..len(line.text), which is
        # what an edge of a selection is.
        #
        # The pair is LOGICAL and not visual, and that is the whole of
        # why a selection in this box behaves the way one does in a
        # browser: drag leftwards through "Whisper הוא" and the range
        # stays contiguous in the string while the highlight on screen
        # breaks into two rectangles, because the English sits inside the
        # Hebrew the other way round. Uniscribe draws that split; nothing
        # here has to know about it.
        #
        # `_sel_from` is the end the drag started at, which is the one
        # that stays put while the other follows the cursor — a range
        # read off the current pair instead would refuse to shrink.
        self._sel: tuple[tuple[int, int], tuple[int, int]] | None = None
        self._sel_from: tuple[int, int] | None = None
        self._selecting = False
        # The window that was in front when the selection was made. The
        # Ctrl+C accelerator is only for the app you were reading IN —
        # see _ctrl_c_is_ours().
        self._sel_fg = 0
        self._drag: _Drag | None = None
        # The resize gesture, the move gesture's sibling — same capture,
        # same threshold, different axis. See _begin_resize.
        self._resizing: _Resize | None = None
        # A content reflow is owed to a running resize (the _REFIT_MS
        # tick is on the clock). The frame never waits for it; this only
        # stops a second timer being set while one is pending.
        self._refit_scheduled = False
        # A size the hand set, overriding (max_width, max_height) as the
        # cap this box fits itself inside. Reset by every NEW question —
        # a fresh lookup is a fresh box at its natural size, exactly as a
        # fresh lookup forgets where the last one was dragged to.
        self._user_size: tuple[int, int] | None = None
        # Where the user put it, once he has. None means "nobody has
        # moved this box", which is what lets update() re-place a box
        # from its anchor and leave a dragged one alone.
        self._moved_to: tuple[int, int] | None = None
        self._rounded_by_dwm = False
        self._hidden_by: str | None = "never shown"
        self._cmds: collections.deque = collections.deque()
        self._tid: int | None = None
        self._ready = threading.Event()
        self._thread: threading.Thread | None = None
        try:
            self._thread = threading.Thread(target=self._run, daemon=True,
                                            name="lookup-popup")
            self._thread.start()
            self._ready.wait(timeout=5)
        except Exception:
            log.exception("lookup popup thread would not start")
        if self._hwnd is None:
            log.warning("lookup popup has no window; lookups will still "
                        "run but nothing will be shown")
        # Nothing dismisses this box on its own any more, so a caller that
        # forgets stop() would leave one on screen for as long as the
        # process lives. atexit runs before daemon threads are killed.
        atexit.register(self.stop)

    # ------------------------------------------------- any thread: public

    def show(self, text: str, *, rtl: bool, dwell_ms: int = 0,
             anchor=None, term: str = "") -> None:
        """Put `text` on screen next to `anchor`, laid out for `rtl`.

        `rtl` is the language the caller asked the model to answer in, not
        a property of the string — see the module docstring.

        `term` is what was looked up, and it goes in the title bar. It is
        the caller's to supply because this module never sees the
        selection — only the answer to it. Omitted, the bar names the
        language the answer came back in instead; see _bar_label().

        `anchor` is where on screen you were pointing when you asked: a
        screen point (x, y), or a rect (left, top, right, bottom) such as
        a caret or a selection. The box is placed beside it and never on
        it. None puts the box bottom-right of the work area, which is what
        the CLI probe and the tests use.

        `dwell_ms` is how long the box waits for you to ignore it. The app
        passes 0 — the box now closes on its button or on Esc and nothing
        else — but a positive value is still honoured, because an argument
        that is quietly ignored is worse than one that was never there.
        """
        try:
            body = _clean(text)
            if body:
                head = _clean(term).split("\n")[0] if term else ""
                self._post("show", body, bool(rtl), max(0, int(dwell_ms)),
                           _as_rect(anchor), head)
        except Exception:
            log.exception("lookup popup show failed")

    def update(self, text: str) -> None:
        """Replace what is in the box, in place — the answer arriving
        where the "…" was.

        Re-measures and re-places from the same anchor, so an answer six
        lines longer than the ellipsis it replaces grows the box AWAY from
        your text rather than off the bottom of the screen: the edge next
        to the anchor is the one that stays put.

        If the box had already closed itself on a dwell, it comes back: a
        cold local model is 25 s to the first token, and losing the answer
        to that race would be the key silently not working. If YOU closed
        it, it stays closed.
        """
        try:
            body = _clean(text)
            if body:
                self._post("update", body)
        except Exception:
            log.exception("lookup popup update failed")

    def hide(self) -> None:
        try:
            self._post("hide", "caller")
        except Exception:
            log.exception("lookup popup hide failed")

    def visible(self) -> bool:
        try:
            return bool(self._hwnd) and bool(
                user32.IsWindowVisible(self._hwnd))
        except Exception:
            log.exception("lookup popup visible() failed")
            return False

    def on_key(self, vk: int) -> bool:
        """Called by the keyboard hook for every key-down. True == swallow.

        Runs on the OS hook thread, where anything that blocks freezes
        every key on the machine, so it does no window work: it reads
        flags and posts. In particular it never touches the clipboard —
        injector's own retry is up to 500 ms and Windows unhooks a
        callback that overruns 300 ms, without a word in the log.

        TWO keys, and the rest of the keyboard is still none of this
        module's business: it used to close the box on any key, which
        meant you could not so much as press Shift while reading an
        answer.

        Esc closes it, and is swallowed because it closed the box and
        should not also reach the app underneath — and only while a box
        is actually up, or this would eat the Esc that belongs to the
        editor you are typing in.

        Ctrl+C copies the selection, and is swallowed under the five
        conditions in _ctrl_c_is_ours(). It is an accelerator on a button
        that is already on screen, never the only way to copy.
        """
        try:
            if vk == VK_ESCAPE:
                if not self.visible():
                    return False
                self._post("hide", "esc")
                return True
            if vk == VK_C and self._ctrl_c_is_ours():
                self._post("copy", "selection")
                return True
            return False
        except Exception:
            log.exception("lookup popup on_key failed")
            return False

    def _ctrl_c_is_ours(self) -> bool:
        """Is this Ctrl+C for the selection in the box, or for the app?

        Five conditions, ordered cheapest first so that every OTHER key
        on the machine costs an attribute read. All five, because a
        Ctrl+C taken from the window underneath is a silent theft: the
        user pastes and gets something they never copied, and there is
        nothing on screen that says why.

        1. Something is selected. A selection only exists because a hand
           dragged inside this box.
        2. The box is on screen.
        3. Plain Ctrl+C — no Shift, no Alt, no Win. Ctrl+Shift+C is the
           browsers' inspector and Win+Ctrl+C is Windows' colour filter.
        4. The window in front is the one that was in front when the
           selection was made. Switch apps and the box stops answering
           for a chord you meant for the app you switched to; switch
           back and it answers again.
        5. It is not a console. injector's own docstring records why the
           mirror image of this is refused there: Ctrl+C in a terminal is
           SIGINT, and eating the one that was meant to stop somebody's
           build is strictly worse than making them click the button.
           Same known gap, too — VS Code's terminal reports
           Chrome_WidgetWin_1 and is indistinguishable from an editor.
        """
        if self._sel is None or not self.visible():
            return False
        down = user32.GetAsyncKeyState
        if not down(VK_CONTROL) & 0x8000:
            return False
        if any(down(vk) & 0x8000
               for vk in (VK_SHIFT, VK_MENU, VK_LWIN, VK_RWIN)):
            return False
        front = int(user32.GetForegroundWindow() or 0)
        if not front or front != self._sel_fg:
            return False
        buf = ctypes.create_unicode_buffer(64)
        user32.GetClassNameW(w.HWND(front), buf, 64)
        return buf.value not in _CONSOLE_CLASSES

    def selection(self) -> str:
        """The selected lines, joined — what a copy would put on the
        clipboard, and "" when nothing is taken.

        Public for the same reason measure() and place_for() are: it is
        the part of a selection that can be asserted without reading a
        screenshot, and the screenshot only says where the band is, not
        which characters are under it.
        """
        try:
            return self._selected_text()
        except Exception:
            log.exception("lookup popup selection() failed")
            return ""

    def stop(self) -> None:
        try:
            if self._tid:
                user32.PostThreadMessageW(self._tid, WM_QUIT, 0, 0)
            if self._thread is not None and self._thread.is_alive():
                self._thread.join(timeout=2)
        except Exception:
            log.exception("lookup popup would not stop")

    @property
    def hwnd(self) -> int | None:
        """The window, for tests that read its style bits back."""
        return self._hwnd

    def measure(self, text: str, *, rtl: bool) -> tuple[int, int]:
        """The window size `text` would need, once auto-fit has had its
        say — every face tried down to the floor, then capped and
        trimmed.

        Never larger than (max_width, max_height): that is the point of
        it. Public because sizing is the one part of a popup that can be
        asserted without a screenshot.
        """
        try:
            lay = self._layout(_clean(text), bool(rtl))
            return lay.width, lay.height
        except Exception:
            log.exception("lookup popup measure failed")
            return self.max_width, self.max_height

    def place_for(self, width: int, height: int, anchor=None,
                  *, rtl: bool = True) -> tuple[int, int]:
        """Where a `width` x `height` box would go for that anchor.

        Public because placement is the other part of a popup that can be
        asserted without a screenshot, and the rules it has to obey — on
        the work area, never over the anchor, flipped rather than clipped
        at an edge — are worth a test each.
        """
        rect = _as_rect(anchor)
        return self._place(int(width), int(height), rect,
                           self._work_area(rect), bool(rtl))

    # ------------------------------------------------ any thread: private

    def _post(self, op: str, *args) -> None:
        if not self._tid:
            return                  # no thread: already logged at start-up
        self._cmds.append((op, args))
        user32.PostThreadMessageW(self._tid, _WM_COMMAND, 0, 0)

    # ------------------------------------------------------ popup thread

    def _run(self) -> None:
        self._tid = kernel32.GetCurrentThreadId()
        try:
            self._create()
        except Exception:
            log.exception("lookup popup window could not be created")
            self._ready.set()
            self._tid = None
            return
        self._ready.set()
        msg = w.MSG()
        try:
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                # Posted to the thread rather than to a window: GetMessage
                # hands those back with a null hWnd and nothing dispatches
                # them, so they are run here.
                if not msg.hWnd and msg.message == _WM_COMMAND:
                    self._drain()
                    continue
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
        except Exception:
            log.exception("lookup popup message loop stopped")
        finally:
            self._teardown()

    def _create(self) -> None:
        global _CREATING
        _register_class()
        # Owner 0 and no WS_EX_APPWINDOW: not Alt-Tab eligible, not in the
        # taskbar. WS_EX_NOACTIVATE and WS_EX_TOOLWINDOW keep it out of
        # the focus chain; WS_EX_LAYERED is what makes the alpha knob and
        # the smooth compositing path available. Read back live, these are
        # 0x08080088.
        _CREATING = self
        try:
            hwnd = user32.CreateWindowExW(
                WS_EX_TOPMOST | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE
                | WS_EX_LAYERED, _CLASS_NAME, "lookup", WS_POPUP,
                0, 0, 10, 10, None, None,
                kernel32.GetModuleHandleW(None), None)
        finally:
            _CREATING = None
        if not hwnd:
            raise OSError("CreateWindowExW failed (WinError "
                          f"{ctypes.get_last_error()})")
        self._hwnd = int(hwnd)
        _INSTANCES[self._hwnd] = self
        # Opaque on purpose. The layered bit is required by the style the
        # design settled on, but the text has to stay readable over
        # whatever it is covering, and ClearType over a translucent window
        # is exactly where Hebrew stops being crisp.
        user32.SetLayeredWindowAttributes(self._hwnd, 0,
                                          max(0, min(255, self.alpha)),
                                          LWA_ALPHA)
        self._rounded_by_dwm = self._ask_dwm_to_round(self._hwnd)

    def _ask_dwm_to_round(self, hwnd: int) -> bool:
        """Rounded corners and a 1 px border, drawn by the compositor.

        Worth asking for rather than doing by hand: DWM antialiases the
        corner, clips the shadow to it, and puts the border OUTSIDE the
        client area so no pixel of text is lost to it. SetWindowRgn — the
        fallback, and what this used to do unconditionally — gives a
        stair-cased corner and eats a pixel row. Returns False on anything
        before Windows 11, where both attributes fail with E_INVALIDARG.
        """
        if dwmapi is None:
            return False
        try:
            pref = ctypes.c_int(DWMWCP_ROUND)
            if dwmapi.DwmSetWindowAttribute(
                    w.HWND(hwnd), DWMWA_WINDOW_CORNER_PREFERENCE,
                    ctypes.byref(pref), ctypes.sizeof(pref)) != 0:
                return False
            colour = w.COLORREF(EDGE)
            dwmapi.DwmSetWindowAttribute(
                w.HWND(hwnd), DWMWA_BORDER_COLOR, ctypes.byref(colour),
                ctypes.sizeof(colour))
            return True
        except Exception:
            log.debug("lookup popup could not ask DWM to round it",
                      exc_info=True)
            return False

    def _drain(self) -> None:
        while True:
            try:
                op, args = self._cmds.popleft()
            except IndexError:
                return
            try:
                getattr(self, "_do_" + op)(*args)
            except Exception:
                log.exception("lookup popup could not %s", op)

    def _do_show(self, text: str, rtl: bool, dwell_ms: int,
                 anchor: tuple[int, int, int, int] | None,
                 term: str = "") -> None:
        if not self._hwnd:
            return
        self._text, self._rtl, self._dwell_ms = text, rtl, dwell_ms
        self._answer, self._term = text, term
        self._anchor = anchor
        # The monitor is decided once, here, from the anchor (or from the
        # cursor when there is none). If update() re-measured it, the
        # answer arriving after the mouse had wandered would move the box
        # to another screen mid-read.
        self._work = self._work_area(anchor)
        self._hover = self._armed = self._flash = None
        self._forget_selection()
        user32.KillTimer(self._hwnd, ctypes.c_void_p(_FLASH_TIMER_ID))
        # A NEW lookup starts fresh at the new anchor: where the LAST
        # answer was dragged to says nothing about where this one belongs,
        # and a box that reopened three screens away from the word you
        # just asked about would be the corner problem all over again.
        self._end_drag()
        self._end_resize()
        self._moved_to = None
        # ...and fresh at the size it fits itself: a size the hand set was
        # for THAT answer, and this one has not been seen yet.
        self._user_size = None
        self._refit_scheduled = False
        self._render()

    def _do_update(self, text: str) -> None:
        if not self._hwnd:
            return
        if not self.visible() and self._hidden_by != "dwell":
            # Dismissed on purpose. The answer is still in the log and the
            # cue already played; putting the box back would be arguing.
            log.debug("lookup answer arrived after the box was dismissed "
                      "(%s)", self._hidden_by)
            return
        self._text = self._answer = text
        # The answer replacing the "…" is a different set of lines, so
        # indices into the old one mean nothing. Silently keeping a range
        # would highlight whatever happened to land on those rows.
        self._forget_selection()
        if self._work is None:
            self._work = self._work_area(self._anchor)
        self._render()

    def _do_hide(self, reason: str = "hidden") -> None:
        if not self._hwnd:
            return
        self._hidden_by = reason
        self._hover = self._armed = self._flash = None
        # Esc can land mid-drag, and a window that is hidden while it
        # still holds the mouse keeps every other window from seeing the
        # button come up. Mid-SELECTION is the same capture and the same
        # problem — and mid-RESIZE the third way to be holding this
        # window's capture, ended here for the same reason.
        self._end_drag()
        self._end_resize()
        self._forget_selection()
        user32.KillTimer(self._hwnd, ctypes.c_void_p(_TIMER_ID))
        user32.KillTimer(self._hwnd, ctypes.c_void_p(_FLASH_TIMER_ID))
        user32.KillTimer(self._hwnd, ctypes.c_void_p(_RESIZE_TIMER_ID))
        user32.ShowWindow(self._hwnd, SW_HIDE)

    def _render(self) -> None:
        lay = self._fit_window(self._text, self._rtl)
        self._lay, self._text = lay, lay.text
        if self._moved_to is None:
            x, y = self._place(lay.width, lay.height, self._anchor,
                               self._work, self._rtl)
        else:
            # Moved by hand, so the anchor has had its say and lost. The
            # top-left is kept and the box grows down and across from
            # there — the answer replacing the "…" is two to four times
            # its height — and _refit pulls it back only by however much
            # of that growth left the screen.
            x, y = self._refit(lay, *self._moved_to)
        if not self._rounded_by_dwm:
            # SetWindowRgn takes ownership of the region — it must not be
            # deleted here, and a new one is needed on every resize.
            user32.SetWindowRgn(self._hwnd, gdi32.CreateRoundRectRgn(
                0, 0, lay.width + 1, lay.height + 1, self.corner,
                self.corner), False)
        user32.SetWindowPos(self._hwnd, HWND_TOPMOST, x, y, lay.width,
                            lay.height, SWP_NOACTIVATE | SWP_SHOWWINDOW)
        user32.ShowWindow(self._hwnd, SW_SHOWNOACTIVATE)
        user32.InvalidateRect(self._hwnd, None, True)
        self._hidden_by = None
        user32.KillTimer(self._hwnd, ctypes.c_void_p(_TIMER_ID))
        if self._dwell_ms:
            user32.SetTimer(self._hwnd, ctypes.c_void_p(_TIMER_ID),
                            self._dwell_ms, None)

    def _teardown(self) -> None:
        try:
            if self._hwnd:
                user32.KillTimer(self._hwnd, ctypes.c_void_p(_TIMER_ID))
                user32.KillTimer(self._hwnd,
                                 ctypes.c_void_p(_FLASH_TIMER_ID))
                user32.KillTimer(self._hwnd,
                                 ctypes.c_void_p(_RESIZE_TIMER_ID))
                _INSTANCES.pop(self._hwnd, None)
                user32.DestroyWindow(self._hwnd)
            self._hwnd = None
            with self._font_lock:
                for handle in self._fonts.values():
                    gdi32.DeleteObject(handle)
                self._fonts.clear()
        except Exception:
            log.exception("lookup popup teardown")
        finally:
            self._tid = None

    # --------------------------------------------------------- placement

    def _work_area(self, anchor=None) -> w.RECT:
        """The work area of the monitor the anchor — or the cursor — is on.

        MonitorFromPoint and not the virtual screen, because
        SM_CXVIRTUALSCREEN is a WIDTH and not a right edge: this machine's
        left monitor starts at x = -1920 (measured SM_XVIRTUALSCREEN =
        -1920, SM_CXVIRTUALSCREEN = 4480), so clamping into 0..width
        teleports every box opened on the left screen over to the primary
        one. rcWork rather than rcMonitor keeps it off the taskbar.

        The anchor and not the cursor whenever there is one: they are
        usually the same point, but a caret rect from GetGUIThreadInfo is
        wherever the text is, and the mouse may by then be on the other
        screen.
        """
        anchor = _as_rect(anchor)       # total, so a bare point works too
        if anchor is not None:
            pt = w.POINT((anchor[0] + anchor[2]) // 2,
                         (anchor[1] + anchor[3]) // 2)
        else:
            pt = w.POINT()
            user32.GetCursorPos(ctypes.byref(pt))
        mi = MONITORINFO()
        mi.cbSize = ctypes.sizeof(MONITORINFO)
        mon = user32.MonitorFromPoint(pt, MONITOR_DEFAULTTONEAREST)
        if mon and user32.GetMonitorInfoW(mon, ctypes.byref(mi)):
            return mi.rcWork
        return w.RECT(0, 0, user32.GetSystemMetrics(SM_CXSCREEN),
                      user32.GetSystemMetrics(SM_CYSCREEN))

    def _place(self, width: int, height: int, anchor, work: w.RECT | None,
               rtl: bool) -> tuple[int, int]:
        """Beside the anchor, inside the work area, never on top of it.

        Vertical first, because that is the axis that keeps the anchor
        uncovered: the box sits a `gap` below what you pointed at, flips
        to a `gap` above it when the bottom of the screen is in the way,
        and only if neither fits does it go alongside instead. With that
        separation guaranteed, the horizontal position is free to slide
        along the edge without ever touching the anchor.

        Sideways it starts on the reading side — a Hebrew answer hangs its
        RIGHT edge under the anchor and runs leftwards, an English one its
        left — and flips to the other side rather than being clipped when
        it would leave the monitor. The clamp after the flip is the last
        resort for a box wider than the space either way.

        anchor=None is the old behaviour, bottom-right of the work area,
        like overlay.py's Splash.

        Swept 2026-08-19 over both monitors on this machine — including
        the one at x = -1920 — every 97 x 89 px of the FULL monitor rect
        and not just the work area, both directions, five box sizes:
        7190 placements, none covering the anchor, and none outside its
        monitor's work area at any of the four sizes that FIT one.
        Sweeping the full rect rather than the work area is the point:
        the first run of that sweep found 376 that hung under the
        taskbar, all of them from an anchor the work area did not
        contain.

        The fifth size is 460 x 1500, taller than either work area here,
        and it does escape — every one of its 1438 placements, out of the
        bottom. That is not a case with a right answer, only a choice of
        which end to lose, and _beside() pins such a box to the TOP so
        the headline is the part still on screen. Nothing the app itself
        builds is that tall (max_height caps every layout, and its
        default is 520), so this is only reachable by raising
        lookup.max_height past the screen, which config.py permits.
        """
        r = work or self._work_area(anchor)
        if anchor is None:
            return (int(max(r.left, r.right - width - self.margin)),
                    int(max(r.top, r.bottom - height - self.margin)))

        left, top, right, bottom = anchor
        gap = self.gap
        if height <= r.bottom - (bottom + gap):
            y = bottom + gap                    # below: the top edge pins
        elif height <= (top - gap) - r.top:
            y = top - gap - height              # above: the bottom pins
        else:
            return self._beside(width, height, anchor, r)
        # Both branches above measure from the ANCHOR, and the anchor is
        # not guaranteed to be inside the work area: cursor_point() hands
        # back wherever the mouse is, and the mouse can be over the
        # taskbar. An anchor at y = 1435 on this 1440 px screen took the
        # "above" branch, put the box's bottom edge at 1417, and left
        # 25 px of it across the Start button (reproduced 2026-08-19,
        # both monitors, 376 placements in the sweep below). Clamping can
        # only ever move the box FURTHER from an anchor that is outside
        # the work area, so it cannot make it cover one.
        y = max(r.top, min(y, r.bottom - height))

        if rtl:
            x = right - gap - width             # the right edge pins
            if x < r.left:
                x = left + gap                  # flipped: grows rightwards
        else:
            x = left + gap                      # the left edge pins
            if x + width > r.right:
                x = right - gap - width         # flipped: grows leftwards
        x = max(r.left, min(x, r.right - width))
        return int(x), int(y)

    def _beside(self, width: int, height: int, anchor,
                r: w.RECT) -> tuple[int, int]:
        """No room above or below: put it to one side, level with it.

        Reachable with a box near max_height on a short work area, or an
        anchor in the middle of a laptop screen with a tall answer. The
        anchor still must not be covered, so this trades the tidy offset
        for the only remaining free axis.
        """
        left, top, right, _ = anchor
        gap = self.gap
        if right + gap + width <= r.right:
            x = right + gap
        elif left - gap - width >= r.left:
            x = left - gap - width
        else:
            # Nowhere on this monitor is clear of it. Sit as far over as
            # the work area allows and say so: this is the one case where
            # the box can overlap what you pointed at.
            x = max(r.left, min(r.right - width, right + gap))
            log.debug("lookup box has no clear side on a %dx%d work area",
                      r.right - r.left, r.bottom - r.top)
        y = max(r.top, min(top, r.bottom - height))
        return int(x), int(y)

    def _button_monitor(self, lay: _Layout, x: int, y: int) -> w.RECT:
        """The FULL rect of the monitor the box's grip is over.

        The grip rather than the box's centre, because it is the one part
        that has to stay reachable and it is the corner the hand is
        already on. It is the buttons plus _GRIP px of the bar beside
        them, and not the close button alone as it once was: the bar is
        now the only place a drag can start, so a box left with nothing
        but its x on screen would be closable and immovable.
        MONITOR_DEFAULTTONEAREST, so a grip dragged past the outside edge
        of the left monitor is measured against that monitor and not the
        primary one.

        rcMonitor and not rcWork, which is the opposite of _place(): this
        window is topmost, so it draws OVER the taskbar instead of being
        hidden behind it, and a box parked low is still entirely readable.
        Using the work area here would make the answer arriving hop the
        box up off the taskbar it was deliberately put on.
        """
        b = lay.grip
        pt = w.POINT(int(x + (b.left + b.right) // 2),
                     int(y + (b.top + b.bottom) // 2))
        mi = MONITORINFO()
        mi.cbSize = ctypes.sizeof(MONITORINFO)
        mon = user32.MonitorFromPoint(pt, MONITOR_DEFAULTTONEAREST)
        if mon and user32.GetMonitorInfoW(mon, ctypes.byref(mi)):
            return mi.rcMonitor
        return w.RECT(0, 0, user32.GetSystemMetrics(SM_CXSCREEN),
                      user32.GetSystemMetrics(SM_CYSCREEN))

    def _on_screen(self, lay: _Layout, x: int,
                   y: int) -> tuple[int, int]:
        """Nudge (x, y) by the least that keeps the grip visible.

        The only rule a drag is held to. The box may hang off any edge it
        is taken to — over the taskbar, half onto the next monitor, three
        quarters off the left of the left screen — as long as the buttons
        and a handful of bar to take hold of are still on a display.
        Anything stricter is a box that argues with the hand moving it.
        """
        m = self._button_monitor(lay, x, y)
        b = lay.grip
        left, right = x + b.left, x + b.right
        top, bottom = y + b.top, y + b.bottom
        if left < m.left:
            x += m.left - left
        elif right > m.right:
            x -= right - m.right
        if top < m.top:
            y += m.top - top
        elif bottom > m.bottom:
            y -= bottom - m.bottom
        return int(x), int(y)

    def _refit(self, lay: _Layout, x: int, y: int) -> tuple[int, int]:
        """Where a box that has already been moved by hand goes.

        Not _place(): that would throw away the move and teleport the box
        back to the anchor at exactly the moment the answer arrived,
        which is the one time the box has to hold still. The top-left
        stays where it was put and the box grows down and across from it.

        What is left to do is only the growth, and it is not small.
        Measured with measure() on this machine, 2026-08-20: the "…" box
        is 145 x 57 px, the two-sense dictionary answer that replaces it
        is 389 x 129, and the 60-word paragraph is 450 x 257 — four and a
        half times the height. A box left against the bottom or the right
        of a screen would push most of that off it. Both axes are clamped
        into the monitor by the overflow and no more, and a box taller
        than the monitor keeps its TOP: the headline is the half worth
        seeing, the same choice _place() makes.

        A box left straddling two monitors is pulled fully onto the one
        its grip is on. That is a real move you did not ask for,
        and still the better half of the trade: the alternative is half
        an answer down a bezel.
        """
        x, y = self._on_screen(lay, x, y)
        m = self._button_monitor(lay, x, y)
        return (int(max(m.left, min(x, m.right - lay.width))),
                int(max(m.top, min(y, m.bottom - lay.height))))

    # ------------------------------------------------------------ layout

    def _font(self, role: str, size_px: int | None = None) -> int:
        # Locked because measure() is callable from any thread while the
        # popup thread is painting: two CreateFontW calls race, the loser's
        # handle is overwritten and never deleted (+1 GDI object over 800
        # calls from 4 threads, measured 2026-08-19).
        #
        # Keyed by (role, size) and not by role alone since auto-fit: one
        # process now measures at several faces across its life, and a
        # cache keyed by role would hand the 13 px layout the 19 px title
        # font and measure it into the wrong box. The size argument is
        # None only for callers outside a layout — the tests' — which get
        # whatever the last laid-out face was.
        if size_px is None:
            size_px = self._active_px
        key = (role, int(size_px))
        with self._font_lock:
            handle = self._fonts.get(key)
            if handle is None:
                delta, weight, _ = self._FACE.get(role, self._FACE["body"])
                px = max(9, key[1] + delta)
                handle = gdi32.CreateFontW(
                    -px, 0, 0, 0, weight, 0, 0, 0,
                    DEFAULT_CHARSET, 0, 0, CLEARTYPE_QUALITY, 0,
                    self.font_name)
                self._fonts[key] = handle
            return handle

    def _flags(self, rtl: bool) -> int:
        """How one LINE is drawn. There is no other kind of drawing here.

        DT_WORDBREAK is gone and its absence is the whole of approach C:
        a line whose break DrawTextW chose is a line whose rectangle
        nobody knows, and a rectangle nobody knows cannot be selected,
        highlighted or hit-tested. _wrap() decides the breaks now, and
        every line is handed over on its own with DT_SINGLELINE.

        DT_RTLREADING sets the line's base direction and DT_RIGHT puts
        the ragged edge on the left, where a Hebrew reader expects it.
        Both are untouched by any of this, and they still come from one
        function so the box cannot be laid out for one direction and
        painted in another.
        """
        f = DT_SINGLELINE | DT_NOPREFIX
        if rtl:
            f |= DT_RTLREADING | DT_RIGHT
        return f

    def _wrap(self, hdc: int, text: str, width: int) -> list[str]:
        """`text` broken into the visual lines it is drawn as.

        Greedy, at the break opportunities _BREAK finds — after a run of
        spaces, and after a hyphen or a maqaf. Existing newlines are hard
        breaks and are kept, which is what carries _break_long_tokens'
        splits of a token too wide to fit.

        WIDTHS ARE SUMMED, NOT RE-MEASURED, and that is not an
        approximation. Measured 2026-08-20 over 66417 prefixes of this
        repo's own text in all three faces: the width of a run of chunks
        equals the sum of the chunks' widths, exactly, 0 of 66417 times
        different. So each chunk is measured once, on its own, instead of
        the line being re-measured as it grows — which matters because
        _trim() wraps the same block seven or eight times looking for the
        cut, and re-measuring a growing string would make that quadratic.

        A chunk's TRAILING SPACES do not count against the line: they are
        added once the chunk is on it, never tested. That is DrawTextW's
        rule too, and without it a line whose last word ends the box
        exactly would break one word early.

        The direction is not a parameter because it does not change a
        width: measured over the same 4896 strings, DT_RTLREADING |
        DT_RIGHT moved no measurement by a single pixel. Bidi decides
        where a glyph goes, not how wide the run is.
        """
        out: list[str] = []
        for para in text.split("\n"):
            line, run = "", 0
            for chunk in _BREAK.findall(para):
                if not chunk:
                    continue
                bare = chunk.rstrip()
                span = self._run_width(hdc, bare)
                full = span if bare == chunk else self._run_width(hdc,
                                                                  chunk)
                if line.strip() and run + span > width:
                    out.append(line.rstrip())
                    line, run = chunk, full
                else:
                    line += chunk
                    run += full
            out.append(line.rstrip())
        return out

    def _block(self, hdc: int, text: str, width: int) -> tuple[int, int]:
        """How wide and how tall `text` comes out at `width`.

        The same _wrap() that will paint it, so there is no second
        opinion to disagree with — everything the caps and the trim are
        measured against is measured by the engine that draws.
        """
        lines = self._wrap(hdc, text, width)
        return (max((self._run_width(hdc, ln) for ln in lines), default=0),
                len(lines) * self._face_height(hdc))

    def _run_width(self, hdc: int, text: str) -> int:
        # The auto-fit descent measures the SAME chunks several times over
        # — _wrap, then _trim's rebuild, then _block's re-check, all at
        # one face — so a descent-wide cache collapses that to one
        # DrawTextW per distinct (face, chunk). Keyed by face because
        # nothing carries over between faces; scoped to ONE _layout()
        # call (set/cleared there) because a process-lifetime cache would
        # grow with every answer ever shown. Concurrent measure() from
        # another thread can interleave resets: worst case it re-measures
        # something, never that a wrong width is served — the key carries
        # the face.
        if self._wcache is not None:
            key = (self._active_px, text)
            hit = self._wcache.get(key)
            if hit is not None:
                return hit
        r = w.RECT(0, 0, 0, 0)
        user32.DrawTextW(hdc, text, -1, ctypes.byref(r),
                         DT_CALCRECT | DT_SINGLELINE | DT_NOPREFIX)
        width = r.right - r.left
        if self._wcache is not None:
            self._wcache[key] = width
        return width

    def _face_height(self, hdc: int) -> int:
        """One line of whatever font is in the DC right now.

        Not _line_height(), which asks about the body face specifically:
        a title line and a sense line are different heights and each
        block is measured in its own.
        """
        tm = TEXTMETRICW()
        gdi32.GetTextMetricsW(hdc, ctypes.byref(tm))
        return max(1, int(tm.tmHeight))

    def _split(self, text: str) -> list[tuple[str, str]]:
        """The answer, cut into the parts it is actually made of.

        A dictionary entry is a headline and its senses; anything else is
        one block. The test is a numbered line BELOW the first, which is
        the shape lookup.word_prompt() asks for and one that a translated
        sentence cannot accidentally have: a numbered list in a
        translation keeps its numbering on the first line too, so the
        headline test fails and it is drawn as prose.
        """
        if text == WAITING:
            return [("wait", text)]
        lines = [ln.strip() for ln in text.split("\n")]
        lines = [ln for ln in lines if ln]
        if len(lines) >= 2 and not _SENSE_LINE.match(lines[0]) \
                and any(_SENSE_LINE.match(ln) for ln in lines[1:]):
            return [("title", lines[0])] + [("sense", ln) for ln in lines[1:]]
        return [("body", "\n".join(lines) or text)]

    def _body_top(self) -> int:
        """The first pixel of the answer, under the bar and its hairline.

        Not a full `pad` under the bar: the hairline is already a hard
        edge, so the space beneath it does less work than the space at
        the sides, and a full one made a two-line answer a fifth taller
        for nothing.
        """
        return _BAR + max(6, self.pad - 5)

    def _caps(self) -> tuple[int, int]:
        """The box this layout has to fit inside: the hand's size when it
        has set one, (max_width, max_height) when it has not."""
        if self._user_size is not None:
            return self._user_size
        return self.max_width, self.max_height

    def _fit_window(self, text: str, rtl: bool) -> _Layout:
        """What the window shows AND the rectangle the window occupies.

        _layout() measures CONTENT: its width and height hug the text,
        capped by but never filled out to the hand's size. A resize built
        on that alone measured beautifully and felt broken — the owner
        pulled the corner down and the box stopped where the words
        stopped ("it gets stuck … it doesn't go down with me",
        2026-08-22) — because a grip that does not stay under the hand is
        not a handle, it is a suggestion. So whenever a hand-set size
        exists, the WINDOW IS that size, the way every window on this
        machine answers an edge drag: the answer lays out inside it from
        the top, auto-fit recovering the face while there is room for it,
        and whatever slack is left at the bottom stays background like an
        editor's page. The bar furniture is recomputed against the real
        frame so the grip sits in the corner of the WINDOW — the pixel
        under the finger — not in the corner of the text.
        """
        lay = self._layout(text, rtl)
        if self._user_size is None:
            return lay
        w, h = self._user_size
        lay.width = max(int(w), self._min_w)
        lay.height = max(int(h), self._min_h)
        # The rectangles were laid out for the hugged frame: the bar's
        # label span and, above all, the resizer's own square are
        # functions of width/height, so they follow the frame here or
        # the hand would be holding a corner the box no longer believes
        # in.
        self._bar(lay)
        return lay

    def _layout(self, text: str, rtl: bool) -> _Layout:
        """What to draw, where, and the window size it all fits in.

        The entry point runs AUTO-FIT and then hands over to
        _layout_at(), which measures ONE face: first at the default, and
        if that had to trim anything — lay.truncated — again smaller,
        because the owner's rule is "there is a maximum size the box opens
        to, and the text size should change accordingly so everything fits
        inside". Only when NO face down to min_font_px fits does anything
        give words up, and then the cut is taken from the FLOOR-sized
        layout: an unreadable-but-whole answer loses to a readable one
        with an ellipsis, but both lose to readable-and-whole.

        WHICH smaller faces get tried matters as much as that any do. A
        descent in coarse lumps (19 -> 15 -> 12 -> floor was the first
        cut) made the text snap between them while the hand dragged:
        nothing, nothing, ten centimetres. So the fit is BINARY-SEARCHED
        over every 1 px step down to the floor and the LARGEST face that
        fits wins — enlarging the box recovers type at the first pixel
        that can hold it, shrinking gives it up the same way. "Fits"
        is treated as monotone in the face (smaller glyphs wrap into no
        more height), which held for every sample measured; if a
        pathological string ever breaks that, the search still returns an
        actually-fitting size, only possibly not the largest one.

        Every role scales off the same base, headline and senses together;
        a layout whose title shrank while its body did not would stop
        looking like one answer.
        """
        limit_w, limit_h = self._caps()
        size = self.size_px
        floor = self.min_font_px
        # A HAND-SET frame inverts the question. Configured caps are
        # maximums, so inside them the search runs DOWNWARD from the
        # default and stops there. Inside a frame the hand drew, the
        # owner's ask was "enlarge the text as much as I want, to the
        # point where it's full screen" — so the search spans BOTH sides
        # of the default up to _FACE_MAX, and the largest face that fits
        # wins: growing the box ZOOMS the type instead of piling
        # invisible slack under it, which is exactly why the first cut
        # looked like a box that refused to grow.
        hi = _FACE_MAX if self._user_size is not None else size
        self._wcache = {}
        try:
            lay = self._layout_at(size, text, rtl, limit_w, limit_h)
            if (lay.truncated or hi != size) and hi > floor:
                best = lay if not lay.truncated else None
                lo, top = floor, hi
                while lo <= top:
                    mid = (lo + top) // 2
                    cand = (lay if mid == size else
                            self._layout_at(mid, text, rtl,
                                            limit_w, limit_h))
                    if cand.truncated:
                        top = mid - 1
                    else:
                        best, lo = cand, mid + 1
                if best is not None:
                    lay = best
                elif lay.truncated:
                    # Nothing anywhere fits: cut from the FLOOR layout,
                    # which shows strictly more than the default-size
                    # trim this used to end at.
                    lay = self._layout_at(floor, text, rtl,
                                          limit_w, limit_h)
        finally:
            self._wcache = None
        return lay

    def _layout_at(self, size_px: int, text: str, rtl: bool,
                   max_w: int, max_h: int) -> _Layout:
        """One candidate layout, measured entirely at `size_px`.

        Everything here is the original single-size layout with two
        numbers made parameters (`max_w`, `max_h` are the caps this pass
        must obey — the hand's resize sets them, config otherwise). The
        one new output bit is `truncated`: whether THIS size had to give
        words up, which is the signal the caller descends on.

        _wrap() asks the function that will do the drawing how tall each
        block wraps, so the box is measured rather than guessed — but
        measured is not the same as bounded, and unbounded is how a
        22-sentence paragraph produced a 456x896 px window, taller than
        some work areas. Both dimensions are capped here and the overflow
        is trimmed with an ellipsis.

        Every block is measured at `inner` and then drawn in a rectangle
        at least as wide as the longest line it produced and never wider
        than `inner`. Greedy wrapping cannot change under that (a word
        that did not fit in the wider rectangle does not fit in the
        narrower one, and every line already fits), which is what lets
        _paint() reuse these rectangles instead of re-measuring and
        disagreeing.

        The block is then cut into the LINES it is drawn as, and they are
        cut here rather than inside DrawTextW for one reason: a line
        whose break DrawTextW chose is a line whose rectangle nobody
        knows, and the selection is made of those rectangles. Both come
        out of the same _wrap() call, so what was measured, what is
        painted and what a press hits cannot come apart.

        Every block is now FULL width, and that is what the title bar
        bought. The buttons used to sit in the top corner of the text, so
        the first block had to give up _BUTTON plus its padding — which a
        one-block translation then gave up on every line, a 33 px
        asymmetry on the commonest shape. With the buttons in a bar of
        their own there is nothing for the text to make room for, and the
        body is a plain stack of equal rectangles.

        GetDC(None) is the desktop DC, so on a genuinely mixed-DPI setup
        the text would be measured at the primary monitor's DPI for a box
        living on another. Untested: no such hardware here.
        """
        lay = _Layout(text, rtl)
        lay.size_px = int(size_px)
        # What a bare _font(role) means until the next layout: see the
        # cache comment. Set before anything selects a font.
        self._active_px = lay.size_px
        pad = self.pad
        top = self._body_top()
        inner = max(40, max_w - 2 * pad)
        cap_h = max(20, max_h - top - pad)

        hdc = user32.GetDC(None)
        sized: list[tuple[str, str, int, int, list[str], int]] = []
        line_h, y, widest, previous = lay.size_px, 0, 0, ""
        try:
            line_h = self._line_height(hdc, lay.size_px)
            for role, body in self._split(text):
                old = gdi32.SelectObject(hdc, self._font(role, lay.size_px))
                try:
                    body = self._break_long_tokens(hdc, body, inner)
                    lead = self._lead(previous, role)
                    room = cap_h - (y + lead)
                    bw, bh = self._block(hdc, body, inner)
                    if bh > room:
                        if room < line_h:
                            # Not even one line left at this size. A
                            # smaller face might still buy a line, so
                            # this is truncation the caller can descend
                            # on — but the block is dropped either way.
                            lay.truncated = True
                            break
                        body = self._trim(hdc, body, inner, room)
                        bw, bh = self._block(hdc, body, inner)
                        lay.truncated = True
                    rows = self._wrap(hdc, body, inner)
                    face = self._face_height(hdc)
                finally:
                    gdi32.SelectObject(hdc, old)
                y += lead
                sized.append((role, body, y, bh, rows, face))
                widest = max(widest, bw)
                y += bh
                previous = role
        finally:
            user32.ReleaseDC(None, hdc)

        # A box narrower than its own bar is a smudge, not a box — but
        # the cap still wins, because measure() promises never to exceed
        # it and config.py lets it go to 160.
        inner_w = max(min(widest, inner),
                      min(max(0, _BAR_MIN - 2 * pad), inner))
        lay.width = min(inner_w + 2 * pad, max_w)
        lay.height = min(top + max(y, line_h) + pad, max_h)
        for role, body, block_top, bh, rows, face in sized:
            block = len(lay.blocks)
            lay.blocks.append(_Block(body, role,
                                     w.RECT(pad, top + block_top,
                                            pad + inner_w,
                                            top + block_top + bh)))
            for i, row in enumerate(rows):
                row_top = top + block_top + i * face
                lay.lines.append(_Line(row, role,
                                       w.RECT(pad, row_top, pad + inner_w,
                                              row_top + face), block,
                                       lay.size_px))
            if role == "title":
                # The hairline sits halfway down the gap under the
                # headline, so the two spaces above and below it are
                # equal and it reads as a separator and not as an
                # underline.
                rule_y = (top + block_top + bh
                          + self._lead("title", "sense") // 2)
                lay.rule = w.RECT(pad, rule_y, pad + inner_w, rule_y + 1)
        lay.text = "\n".join(b.text for b in lay.blocks) or text
        self._bands(lay)
        self._bar(lay)
        return lay

    def _bands(self, lay: _Layout) -> None:
        """Give every line the strip of the body that selects it.

        The strips MEET: each boundary is halfway between one line's
        bottom and the next line's top, so the 5 px between two senses
        and the 20 px the hairline sits in both belong to a line rather
        than to nothing. A gap that selected nothing would be a press
        that silently threw the selection away, and the gaps are where a
        hand aiming at a 21 px line lands.

        Outside the first and last line there is deliberately nothing:
        the padding at the top and bottom of the body is how a selection
        is let go of without closing the box.
        """
        rows = lay.lines
        for i, ln in enumerate(rows):
            top = (ln.rect.top if not i
                   else (rows[i - 1].rect.bottom + ln.rect.top) // 2)
            bottom = (ln.rect.bottom if i + 1 == len(rows)
                      else (ln.rect.bottom + rows[i + 1].rect.top) // 2)
            ln.hit = (top, bottom)

    def _bar(self, lay: _Layout) -> None:
        """The bar's furniture, once the width it spans is known.

        MIRRORED, like everything else in this box. The buttons go to the
        corner the reader's eye ends a line at — top-left for a Hebrew
        answer, top-right for an English one — with close outermost, copy
        inside it and copy-selection inside that, which is the order
        every window on this machine uses and the order an RTL Windows
        shell mirrors to. The label takes the other end, so it starts
        where the reading starts.

        The label is measured for NOTHING. It is given whatever room the
        buttons leave in a width the answer already decided, and painted
        with DT_END_ELLIPSIS — so a bar that says more than it has room
        for elides, and a term nobody expected can never widen the box.

        Both copy buttons are absent while the box holds only the "…":
        there is nothing to copy yet, and a button that does nothing when
        it is pressed teaches that the button does nothing.

        The copy-selection button's ROOM is reserved from the moment
        there is an answer, even though it only appears once a line has
        been taken. That is deliberate: the alternative is a bar whose
        two other buttons shuffle sideways the instant you press on a
        sense, moving the close button out from under a finger that was
        on its way to it.

        The resizers are placed here too, one in EACH bottom corner. They
        used to be a single mirrored square — far corner from the close
        button only — and that mirror was measured in the field as a trap:
        which corner works depends on the ANSWER's language, so the same
        grab on the same spot of the screen grows one box and does nothing
        at all to the next ("I drag the bottom-right down-down-down and it
        does nothing"). Both corners now resize, each against its own
        fixed top corner, and pulling OUTWARD is growth everywhere. They
        are in the body's territory, not the bar's: _zone_at() tests them
        after the bar and before falling through to "body", so they steal
        exactly their own squares from the selection and nothing else.
        """
        lay.bar = w.RECT(0, 0, lay.width, _BAR)
        lay.show_copy = bool(lay.blocks) and lay.text != WAITING
        span = _BUTTON_PAD + _BUTTON
        if lay.show_copy:
            span += 2 * (_BUTTON_GAP + _BUTTON)
        if lay.rtl:
            lay.button = w.RECT(_BUTTON_PAD, _BUTTON_PAD,
                                _BUTTON_PAD + _BUTTON,
                                _BUTTON_PAD + _BUTTON)
            lay.copy = w.RECT(lay.button.right + _BUTTON_GAP, _BUTTON_PAD,
                              lay.button.right + _BUTTON_GAP + _BUTTON,
                              _BUTTON_PAD + _BUTTON)
            lay.copysel = w.RECT(lay.copy.right + _BUTTON_GAP, _BUTTON_PAD,
                                 lay.copy.right + _BUTTON_GAP + _BUTTON,
                                 _BUTTON_PAD + _BUTTON)
            lay.grip = w.RECT(0, 0, min(lay.width, span + _GRIP), _BAR)
            left = span + _LABEL_GAP
            lay.label_rect = w.RECT(left, 0,
                                    max(left, lay.width - _BUTTON_PAD - 2),
                                    _BAR - 1)
        else:
            edge = lay.width - _BUTTON_PAD
            lay.button = w.RECT(edge - _BUTTON, _BUTTON_PAD, edge,
                                _BUTTON_PAD + _BUTTON)
            lay.copy = w.RECT(lay.button.left - _BUTTON_GAP - _BUTTON,
                              _BUTTON_PAD, lay.button.left - _BUTTON_GAP,
                              _BUTTON_PAD + _BUTTON)
            lay.copysel = w.RECT(lay.copy.left - _BUTTON_GAP - _BUTTON,
                                 _BUTTON_PAD, lay.copy.left - _BUTTON_GAP,
                                 _BUTTON_PAD + _BUTTON)
            lay.grip = w.RECT(max(0, lay.width - span - _GRIP), 0,
                              lay.width, _BAR)
            right = lay.width - span - _LABEL_GAP
            lay.label_rect = w.RECT(_BUTTON_PAD + 2, 0,
                                    max(_BUTTON_PAD + 2, right), _BAR - 1)
        lay.label = self._bar_label(lay.rtl)
        lay.resizer_r = w.RECT(lay.width - _RESIZE, lay.height - _RESIZE,
                               lay.width, lay.height)
        lay.resizer_l = w.RECT(0, lay.height - _RESIZE, _RESIZE,
                               lay.height)

    def _bar_label(self, rtl: bool) -> str:
        """What the bar says: the term that was looked up, or failing
        that, the language the answer came back in.

        The term is the useful one and it is the caller's to pass, per
        show(): this module is handed an answer and never sees the
        question, and the box outlives the selection — drag it away from
        the text, or read it after the highlight has gone, and the bar is
        the only thing on screen still saying which word was asked about.

        The fallback is not decoration either. lookup.both_ways means a
        tap can come back in either language, and the bar naming the one
        it chose is the difference between "the model answered in
        English" and "the model ignored the question". It is also the one
        thing this module can always know, since `rtl` is the caller's
        own decision arriving with the text.
        """
        term = (self._term or "").strip()
        if term:
            return term
        return "עברית" if rtl else "English"

    def _lead(self, previous: str, role: str) -> int:
        """The gap above a block, given what came before it."""
        if not previous:
            return 0
        if previous == "title":
            return 20               # room for the hairline, half each side
        return 5 if role == "sense" else 10

    def _line_height(self, hdc: int, size_px: int) -> int:
        """One line of body text, for the "is there room left" test."""
        old = gdi32.SelectObject(hdc, self._font("body", size_px))
        tm = TEXTMETRICW()
        gdi32.GetTextMetricsW(hdc, ctypes.byref(tm))
        gdi32.SelectObject(hdc, old)
        return max(1, int(tm.tmHeight))

    def _break_long_tokens(self, hdc: int, text: str, inner_w: int) -> str:
        """Split any single token too wide to fit, at a character.

        _wrap() breaks between words, and a word with no break in it has
        nowhere to go. The longest such token in the owner's own
        transcripts.log is 223 characters — an "א" followed by 222 "ה",
        the shape a Whisper decoder loop leaves behind — and the same
        shape at 60 characters already measures 3121 px against a 2560 px
        monitor. Rare, but a box that runs off the edge of the screen is
        not a box.

        The length test in front of the measurement is what makes this
        cheap, and it is exact rather than a heuristic: tmMaxCharWidth is
        the widest glyph in the face, so a token of at most
        inner_w / tmMaxCharWidth characters CANNOT be too wide and never
        needs asking about. Measured 2026-08-19 on the 60-word Hebrew
        sample below — the threshold comes out at 8 characters and the
        longest token in it is 7, so all 60 skip the measurement and this
        function goes from 0.777 ms to 0.019 ms, byte-identical output.
        The decoder-loop token still costs its 4.7 ms, because that one
        genuinely has to be measured letter by letter.
        """
        tm = TEXTMETRICW()
        gdi32.GetTextMetricsW(hdc, ctypes.byref(tm))
        safe = max(1, inner_w // max(1, int(tm.tmMaxCharWidth)))
        out = []
        for token in re.split(r"(\s+)", text):
            if (not token or token.isspace() or len(token) <= safe
                    or self._run_width(hdc, token) <= inner_w):
                out.append(token)
                continue
            chunk = ""
            for ch in token:
                if chunk and self._run_width(hdc, chunk + ch) > inner_w:
                    out.append(chunk + "\n")
                    chunk = ch
                else:
                    chunk += ch
            out.append(chunk)
        return "".join(out)

    def _trim(self, hdc: int, text: str, inner_w: int,
              inner_h: int) -> str:
        """Cut to the last whole LINE that fits, and say so with a "…".

        The cut keeps whole visual lines rather than hunting a word
        boundary, and that is a measured necessity, not a shortcut: this
        ran before as a binary search over word cuts, re-wrapping the
        whole candidate from scratch per probe — 2026-08-22, a 4056-char
        paragraph, 699 ms median for ONE auto-fit descent past it, which
        is most of a second of popup thread per mouse move. Wrapping ONCE
        and keeping the lines that fit measures the same strings with the
        same engine and costs one wrap; the disagreement risk the old
        caution was about does not arise because nothing is re-wrapped at
        all — the lines kept are the lines _wrap produced.

        The one place a word boundary still matters is the LAST kept
        line, which carries the "…" and may have to give tokens back
        until both fit the width together. Tokens, so Hebrew niqqud are
        never split from their letters (they are combining marks INSIDE a
        token); a line with no spaces at all falls back to shaving
        characters the way the old cut did.
        """
        lines = self._wrap(hdc, text, inner_w)
        face = self._face_height(hdc)
        keep = max(1, int(inner_h) // max(1, face))
        if len(lines) <= keep:
            return text             # already fits by count; nothing to cut
        kept = lines[:keep]
        tail = kept[-1]
        marker = tail.rstrip() + " " + ELLIPSIS if tail.strip() else ELLIPSIS
        while marker != ELLIPSIS \
                and self._run_width(hdc, marker) > inner_w:
            stripped = marker[:-len(ELLIPSIS)].rstrip()
            cut = stripped.rfind(" ")
            if cut > 0:
                marker = stripped[:cut].rstrip() + " " + ELLIPSIS
                continue
            # No break left in the line: shave characters off the end,
            # never stranding a combining mark on the cut edge.
            i = len(stripped)
            while i > 0:
                if not unicodedata.combining(stripped[i - 1]):
                    cand = stripped[:i].rstrip() + " " + ELLIPSIS
                    if self._run_width(hdc, cand) <= inner_w:
                        marker = cand
                        break
                i -= 1
            if i <= 0:
                marker = ELLIPSIS
        kept[-1] = marker
        return "\n".join(kept)

    # ----------------------------------------------------------- messages

    def _point(self, lparam: int) -> tuple[int, int]:
        """The client point a mouse message carries.

        Mouse messages carry CLIENT coordinates in the LPARAM — the same
        space the layout's rectangles are in — as two SIGNED 16-bit
        halves. Unpacked as unsigned, a point four pixels off the left or
        top edge of the box, which the OS does deliver to whoever holds
        the capture, reads as 65532 and is inside nothing.
        """
        x, y = lparam & 0xFFFF, (lparam >> 16) & 0xFFFF
        return (x - 0x10000 if x >= 0x8000 else x,
                y - 0x10000 if y >= 0x8000 else y)

    def _zone_at(self, x: int, y: int) -> str:
        """"close", "copy", "copysel", "bar", "resize" or "body" for a
        client point.

        The one place the box decides what a press means, and the order
        matters: the buttons are cut out of the bar, so they are tested
        first and a press on one is never also a press on the handle.
        The copy-selection button is only there while there is a
        selection — its rectangle exists either way, so that nothing in
        the bar moves, but a press on an invisible button is a press on
        the bar and takes hold of the box like the rest of it.

        "resize" is the corner grip, and it is cut out of the BODY the
        same way the buttons are cut out of the bar: tested after the bar
        and before the fall-through to text. It costs the selection
        exactly its own 18 px square in one corner of the body and
        nothing else — the same trade every window with a grip makes.

        "body" is everything under the bar that is left, and it takes
        TEXT: a press selects the line under it, and a drag the range. It
        cannot fight the window move or the resize for the gesture,
        because this function has already decided which one the press
        was.
        """
        lay = self._lay
        if lay is None:
            return "body"
        if lay.show_copy:
            if self._sel is not None and _inside(lay.copysel, x, y):
                return "copysel"
            if _inside(lay.copy, x, y):
                return "copy"
        if _inside(lay.button, x, y):
            return "close"
        if _inside(lay.bar, x, y):
            return "bar"
        if _inside(lay.resizer_r, x, y) or _inside(lay.resizer_l, x, y):
            return "resize"
        return "body"

    def _zone(self, lparam: int) -> str:
        return self._zone_at(*self._point(lparam))

    def _cursor_point(self) -> tuple[int, int] | None:
        """Where the cursor is, in this window's client pixels.

        Screen coordinates converted rather than remembered from the last
        WM_MOUSEMOVE: the cursor can enter the window over the bar
        without a move message being handled first, and a stale answer
        there is a move cursor over the text.
        """
        pt = w.POINT()
        if not (self._hwnd and user32.GetCursorPos(ctypes.byref(pt))
                and user32.ScreenToClient(w.HWND(self._hwnd),
                                          ctypes.byref(pt))):
            return None
        return int(pt.x), int(pt.y)

    def _cursor_zone(self) -> str:
        """The zone the cursor is in right now, asked of the OS.

        WM_SETCURSOR carries a hit-test code and no point, and the box is
        one big HTCLIENT, so the position has to be fetched.
        """
        pt = self._cursor_point()
        return "body" if pt is None else self._zone_at(*pt)

    def _set_hot(self, hover: str | None, armed: str | None) -> None:
        """Repaint the buttons only when one of them actually changed.

        WM_MOUSEMOVE arrives for every pixel of a walk across the box; a
        repaint for each of them is a hundred redraws for one gesture.
        """
        if (hover, armed) == (self._hover, self._armed):
            return
        self._hover, self._armed = hover, armed
        lay = self._lay
        if self._hwnd and lay is not None:
            rects = (lay.button, lay.copy, lay.copysel)
            grown = w.RECT(min(r.left for r in rects) - 1,
                           min(r.top for r in rects) - 1,
                           max(r.right for r in rects) + 1,
                           max(r.bottom for r in rects) + 1)
            user32.InvalidateRect(self._hwnd, ctypes.byref(grown), True)
            # Painted now rather than whenever the queue gets to it: a
            # button whose pressed state appears after the mouse comes
            # back up has not been pressed, it has flickered.
            user32.UpdateWindow(self._hwnd)

    # --------------------------------------------------------- selection

    def _point_at(self, x: int, y: int) -> tuple[int, int] | None:
        """The (line, character) a press at client (x, y) lands on.

        None means neither — above the first line or below the last,
        which is the one place a press can let a selection go without
        closing the box.

        The x is answered by Uniscribe against the same shaping the line
        was painted with, so the boundary the hand sees is the boundary
        it gets. Out past either end of a line clamps to that end rather
        than failing, because a drag that runs off the side of the box
        means "to the end of this line" and not "nothing".
        """
        line = self._line_at(y)
        if line is None:
            return None
        return line, self._cp_at(line, x)

    def _cp_at(self, line: int, x: int) -> int:
        """Where along `line` the point `x` falls, as a character index.

        Measured on a scratch DC carrying that line's own font, because
        the answer depends on the face: the headline is 22 pt and the
        senses are 16, and asking one about the other puts the boundary
        in the wrong place. A failure here returns the end of the line
        rather than raising — a hit test that throws would take the whole
        box down for a mouse move.
        """
        lay = self._lay
        if lay is None or not (0 <= line < len(lay.lines)):
            return 0
        row = lay.lines[line]
        # From the line's own left edge, and clamped: past either end is
        # that end, which is what a drag that leaves the box means.
        offset = min(max(int(x) - row.rect.left, 0),
                     max(row.rect.right - row.rect.left, 0))
        hdc = user32.GetDC(None)        # the desktop DC, as _layout uses
        try:
            old = gdi32.SelectObject(hdc,
                                     self._font(row.role, row.size_px))
            try:
                # RTL lines are right-aligned, so the glyphs start a
                # gap in from the left edge of the row rectangle and the
                # offset has to come back off that gap before Uniscribe
                # sees it — it measures from the string's left edge and
                # knows nothing about the rectangle it was put in.
                with _Shaped(hdc, row.text, lay.rtl) as shaped:
                    width = row.rect.right - row.rect.left
                    lead = (width - shaped.width) if lay.rtl else 0
                    return shaped.cp_at(offset - max(lead, 0))
            finally:
                gdi32.SelectObject(hdc, old)
        except Exception as e:
            log.debug("no hit test for %r: %r", row.text[:20], e)
            return len(row.text)
        finally:
            user32.ReleaseDC(None, hdc)

    def _line_at(self, y: int) -> int | None:
        """Which line a press at client `y` is on, or None for neither.

        The y alone: which line, never where along it. _cp_at answers
        that half, and keeping them apart is what lets a drag that has
        left the box sideways still track the right row.
        """
        lay = self._lay
        if lay is None or not lay.show_copy:
            return None                 # the "…": nothing to take yet
        for i, line in enumerate(lay.lines):
            if line.hit[0] <= y < line.hit[1]:
                return i
        return None

    def _selected_text(self) -> str:
        """The lines that are taken, joined with newlines.

        The strings themselves, exactly as they were handed to DrawTextW
        — so a line that mixes Hebrew and a Latin term copies in LOGICAL
        order and not in the order the glyphs appeared. Reversing what
        bidi did on the way to the screen would be the same mistake as
        feeding Windows an already-reordered string (see the module
        docstring): the screen is a rendering of the string, never the
        other way round.
        """
        lay, sel = self._lay, self._sel
        if lay is None or sel is None:
            return ""
        out = []
        for i in range(sel[0][0], sel[1][0] + 1):
            span = self._span_on(i)
            if span is None:
                continue
            out.append(lay.lines[i].text[span[0]:span[1]])
        return "\n".join(out)

    def _span_on(self, line: int) -> tuple[int, int] | None:
        """How much of `line` is taken, as (from, to), or None.

        The two ends come off the selection's endpoints and everything
        between them is whole. Logical positions throughout: what a
        reader sees split across two places on screen is one run here,
        and slicing the string with it is what makes the clipboard agree
        with the highlight.
        """
        lay, sel = self._lay, self._sel
        if lay is None or sel is None or not (0 <= line < len(lay.lines)):
            return None
        (l0, c0), (l1, c1) = sel
        if not l0 <= line <= l1:
            return None
        n = len(lay.lines[line].text)
        start = c0 if line == l0 else 0
        end = c1 if line == l1 else n
        start, end = max(0, min(start, n)), max(0, min(end, n))
        return (start, end) if end > start else None

    def _forget_selection(self) -> None:
        """Drop the selection and whatever gesture was making it.

        Called by show, update and hide — every path where the lines the
        indices point at are about to stop existing. Idempotent, and it
        does not repaint: every caller is on its way to a full render or
        to hiding the window.
        """
        self._end_select()
        self._sel = self._sel_from = None
        self._sel_fg = 0

    def _set_sel(self, sel: tuple[int, int] | None) -> None:
        """Take this range, and repaint only the rows that changed.

        A drag-select sends a WM_MOUSEMOVE per pixel of hand movement, so
        the first test is that anything changed at all. When something
        did, the rows repainted are the UNION of the two ranges and not
        their symmetric difference: with a character-level selection the
        same row can keep its place in the range while the part of it
        that is lit grows or shrinks, and a row that only changed inside
        itself would otherwise never be redrawn.
        """
        old = self._sel
        if sel == old:
            return
        self._sel = sel
        lay = self._lay
        if lay is None or not self._hwnd:
            return
        touched = self._rows(old) | self._rows(sel)
        if touched:
            lo, hi = min(touched), max(touched)
            lo, hi = max(0, lo), min(hi, len(lay.lines) - 1)
            band = w.RECT(0, lay.lines[lo].rect.top - _SEL_GROW, lay.width,
                          lay.lines[hi].rect.bottom + _SEL_GROW)
            user32.InvalidateRect(self._hwnd, ctypes.byref(band), False)
        if (old is None) != (sel is None):
            user32.InvalidateRect(self._hwnd, ctypes.byref(lay.bar), False)
        user32.UpdateWindow(self._hwnd)

    @staticmethod
    def _rows(sel) -> set[int]:
        return set() if sel is None else set(range(sel[0][0], sel[1][0] + 1))

    @staticmethod
    def _ordered(a: tuple[int, int], b: tuple[int, int]):
        """The two ends of a drag, in document order.

        Which end the hand started at is not which end comes first — a
        selection dragged upwards or leftwards arrives here backwards —
        and everything downstream (the slice, the per-line spans, the
        highlight) assumes start <= end.
        """
        return (a, b) if a <= b else (b, a)

    def _begin_select(self, hwnd: int, at: tuple[int, int] | None) -> None:
        """A press in the body: put the caret there, or let go of all of it.

        SetCapture for the same reason the window drag takes it — the
        rest of the gesture has to keep arriving after the pointer has
        left a box this small — and for one more: the button-up must come
        back here even when it happens over the window underneath, or the
        box would still be selecting minutes later.

        Nothing here activates, focuses or raises anything. Measured for
        the prototype of this on 2026-08-20: a click and a 26-step drag
        against a text editor in another process left one distinct
        (foreground, focus) state for the whole gesture, and what was
        typed afterwards still went to the editor.

        The foreground window is noted at the press, and that is what the
        Ctrl+C accelerator is keyed to — see _ctrl_c_is_ours().
        """
        if at is None:
            self._sel_from = None
            self._set_sel(None)
            return
        self._sel_from = at
        self._selecting = True
        self._sel_fg = int(user32.GetForegroundWindow() or 0)
        # An empty range, not a whole line: a press that goes nowhere
        # takes nothing, the way a caret placed in a paragraph does.
        self._set_sel(None)
        user32.SetCapture(hwnd)

    def _select_to(self, x: int, y: int) -> None:
        """Extend the range to whatever character (x, y) is over.

        Out of the body entirely — above the first line or below the last
        — takes the nearest end rather than nothing, which is what makes
        a drag that runs off the bottom of the box select to the bottom
        of the answer instead of stopping at the last row the hand
        happened to cross.
        """
        lay, first = self._lay, self._sel_from
        if lay is None or first is None or not lay.lines:
            return
        here = self._point_at(x, y)
        if here is None:
            if y < lay.lines[0].hit[0]:
                here = (0, 0)
            else:
                last = len(lay.lines) - 1
                here = (last, len(lay.lines[last].text))
        start, end = self._ordered(first, here)
        self._set_sel(None if start == end else (start, end))

    def _select_word(self, at: tuple[int, int] | None) -> None:
        """A double-click: take the word under it.

        Word in the sense a reader means, and the sense that survives
        this box's own text: letters of any script — Hebrew and Latin
        both — plus the digits and the marks that live inside a word
        rather than between words. A double-click on a space or a
        punctuation mark takes that run instead, which is what stops it
        from silently doing nothing.

        Logical positions, so a double-click on an English term inside a
        Hebrew sentence takes the term and not the Hebrew either side of
        where it happens to have been drawn.
        """
        lay = self._lay
        if lay is None or at is None:
            return
        line, cp = at
        text = lay.lines[line].text
        if not text:
            return
        i = min(max(cp, 0), len(text) - 1)

        def wordish(ch: str) -> bool:
            return ch.isalnum() or ch in "'’-־_"

        kind = wordish(text[i])
        start = i
        while start > 0 and wordish(text[start - 1]) == kind:
            start -= 1
        end = i
        while end < len(text) and wordish(text[end]) == kind:
            end += 1
        self._sel_from = (line, start)
        self._set_sel(((line, start), (line, end)))

    def _end_select(self) -> None:
        """The selection gesture is over; the selection itself remains.

        Idempotent, and it gives the capture back only if this window
        still holds it — the same care _end_drag takes, and for the same
        reason: something else may have taken it away without telling us.
        """
        if not self._selecting:
            return
        self._selecting = False
        cap = user32.GetCapture()
        if cap and self._hwnd and int(cap) == self._hwnd:
            user32.ReleaseCapture()

    # -------------------------------------------------------------- copy

    def _do_copy(self, what: str) -> None:
        """Copy, asked for from another thread — the Ctrl+C accelerator.

        on_key() runs on the OS keyboard hook, where the whole callback
        has 300 ms before Windows unhooks it without a word, so it may
        not read a layout, let alone touch a clipboard. It posts, and
        this is where the request comes out: on the popup thread, where
        the selection is, doing exactly what the button does.
        """
        self._fire_copy(what)

    def _fire_copy(self, what: str = "answer") -> None:
        """A copy button was pressed: put text on the clipboard.

        "answer" is the whole answer as it ARRIVED, untrimmed, so a box
        that had to elide still copies everything. "selection" is the
        lines that are highlighted, exactly as they are drawn.

        On a thread of its own, and that is the point of it.
        injector._open_clipboard retries for up to 500 ms when another
        app is holding the clipboard — a clipboard manager after every
        change, which this machine has — and this window's pump is also
        what carries the answer arriving from the model. Half a second of
        a box that has stopped repainting, to copy something, is a bad
        trade for two lines saved.

        NOTHING here saves and restores the old clipboard, unlike every
        other clipboard path in this app. A copy the user asked for is
        meant to survive: injector.set_text and nothing else, no
        snapshot_all/restore_all pair, and no caller of this may add one.
        Windows Clipboard History will record it, which is right here and
        is exactly what the capture path takes care to avoid.
        """
        if what == "selection":
            text, button = self._selected_text().strip(), "copysel"
        else:
            text, button = (self._answer or self._text).strip(), "copy"
        if not text:
            return
        threading.Thread(target=self._copy_now, args=(text, button),
                         daemon=True, name="lookup-copy").start()

    def _copy_now(self, text: str, button: str = "copy") -> None:
        """The clipboard write, off the popup thread. Never raises.

        injector is imported here and not at the top of the module: it
        pulls in pywin32 and hotkey, this file is otherwise a leaf that
        the tests import on its own, and a lookup box that would not load
        because a clipboard dependency was missing would be a box that
        never appears rather than a copy button that does not work.

        WHY THIS RETRIES WHEN injector ALREADY DOES
        -------------------------------------------
        injector._open_clipboard retries OpenClipboard, and against
        ANOTHER PROCESS that is the right guard. It does nothing at all
        against another THREAD OF THIS ONE, which this button is the
        first thing in the app to create: the lookup worker is inside
        read_selection with the clipboard open while the user presses
        copy on the box the last answer is still in.

        Measured 2026-08-20, three threads of one process, 360 operations
        through injector: 18 failures, every one of them

            (1418, 'CloseClipboard', 'Thread does not have a clipboard
             open')

        — OpenClipboard hands the second thread a success (it is
        associated with the task, not the caller), and the EmptyClipboard
        after it is what discovers the thread does not own anything.
        _open_clipboard's retry never fires, because nothing failed.

        The consolation is that the failure is clean: EmptyClipboard is
        the FIRST call and it is the one that raises, so a collision
        writes nothing and destroys nothing. All that is needed is to
        come back — the other thread holds it for a few milliseconds —
        and _COPY_TRIES x _COPY_BACKOFF_S is 360 ms of coming back, on a
        thread where waiting costs nothing.
        """
        try:
            import injector
        except Exception:
            log.exception("lookup popup has no clipboard to copy to")
            self._post("flash", "busy", button)
            return
        for attempt in range(_COPY_TRIES):
            try:
                injector.set_text(text)
                self._post("flash", "copied", button)
                return
            except Exception as e:
                log.debug("lookup popup copy attempt %d: %r", attempt + 1, e)
                time.sleep(_COPY_BACKOFF_S)
        # Said out loud in the bar as well as here: a copy that silently
        # did nothing gets pressed three more times, and then pasted over
        # something.
        log.error("lookup popup could not copy the answer: the clipboard "
                  "would not open in %d tries. Nothing was written and "
                  "your clipboard is untouched.", _COPY_TRIES)
        self._post("flash", "busy", button)

    def _do_flash(self, kind: str, button: str = "copy") -> None:
        """Say in the bar what the button just did, for _FLASH_MS.

        `button` is which of the two wears the tick — the one the finger
        is still on, and never the other, or the confirmation would be
        for a press that never happened.
        """
        if not self._hwnd:
            return
        self._flash, self._flash_on = kind, button
        user32.SetTimer(self._hwnd, ctypes.c_void_p(_FLASH_TIMER_ID),
                        _FLASH_MS, None)
        self._repaint_bar()

    def _repaint_bar(self) -> None:
        lay = self._lay
        if self._hwnd and lay is not None:
            user32.InvalidateRect(self._hwnd, ctypes.byref(lay.bar), True)
            user32.UpdateWindow(self._hwnd)

    def _begin_drag(self, hwnd: int) -> None:
        """Take hold of the box, without taking the focus.

        Called from the BAR and nowhere else. Nothing here is a drag yet:
        the press is only recorded, and it becomes a move in _drag_to()
        or it becomes nothing. SetCapture is what makes the rest of the
        gesture arrive — the pointer leaves a 30 px strip within a few
        pixels of a real hand movement, and every WM_MOUSEMOVE and the
        WM_LBUTTONUP after that would otherwise go to whatever window it
        had wandered onto.

        SetCapture does not activate, focus or raise anything. It is the
        reason this is written out by hand instead of returning HTCAPTION
        — see the module docstring.
        """
        r, pt = w.RECT(), w.POINT()
        if not (user32.GetWindowRect(hwnd, ctypes.byref(r))
                and user32.GetCursorPos(ctypes.byref(pt))):
            return
        self._drag = _Drag(int(pt.x - r.left), int(pt.y - r.top),
                           int(pt.x), int(pt.y),
                           max(1, user32.GetSystemMetrics(SM_CXDRAG)),
                           max(1, user32.GetSystemMetrics(SM_CYDRAG)))
        user32.SetCapture(hwnd)

    def _drag_to(self, hwnd: int) -> None:
        """Follow the cursor, once it has gone far enough to mean it.

        The cursor is read with GetCursorPos instead of being unpacked
        from the message, and that is not a matter of taste: mouse
        messages carry CLIENT coordinates, the client origin is the very
        thing being moved, and a delta measured against a moving origin
        cancels itself out — the box would judder in place. Screen
        coordinates from the OS, minus the offset the box was taken hold
        of at, is the whole calculation, and it is also self-correcting
        if a move message is ever handled late.

        SWP_NOZORDER keeps the topmost band it was created in and
        SWP_NOACTIVATE keeps the focus where it was; SetWindowPos with
        both is the only thing that moves this window.
        """
        d, lay = self._drag, self._lay
        pt = w.POINT()
        if d is None or lay is None:
            return
        if not user32.GetCursorPos(ctypes.byref(pt)):
            return
        if not d.active:
            # SM_CXDRAG/SM_CYDRAG is the slop the rest of the OS allows,
            # and it exists for exactly this: a press on an 18 px close
            # button that shifts a pixel or two as the finger comes down
            # is a click, not a move. Below it the box does not budge.
            if (abs(pt.x - d.start_x) < d.slop_x
                    and abs(pt.y - d.start_y) < d.slop_y):
                return
            d.active = True
            user32.SetCursor(_cursor(IDC_SIZEALL))
        x, y = self._on_screen(lay, pt.x - d.grab_x, pt.y - d.grab_y)
        self._moved_to = (x, y)
        user32.SetWindowPos(hwnd, None, x, y, 0, 0,
                            SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE)

    def _end_drag(self) -> None:
        """Let go — whatever it was that let go for us.

        Four ways in, and the last two are the reason this is a method
        and not two lines inside WM_LBUTTONUP: the button coming up, the
        WM_CAPTURECHANGED that ReleaseCapture sends straight back to us,
        a capture TAKEN AWAY by something else — a menu opening, the
        secure desktop, another window calling SetCapture — and a mouse
        move that arrives with no button in it. A capture lost with no
        mouse-up would otherwise leave the box glued to the cursor with
        no button held down and nothing to press to stop it.

        WM_CAPTURECHANGED is not enough on its own, which is measured
        and not assumed: 2026-08-20, a second thread of this process
        calling SetCapture on a window of its own took the capture —
        GetCapture named the thief — and NO WM_CAPTURECHANGED arrived
        here at all. The button-up still found its way back that time,
        so nothing was stuck; the move test in WM_MOUSEMOVE is what
        covers the case where it does not.

        Idempotent, so the WM_CAPTURECHANGED that arrives from inside
        ReleaseCapture below is a no-op, and so hide() and show() may
        call it without asking whether a drag is going on.
        """
        drag, self._drag = self._drag, None
        if drag is None:
            return
        cap = user32.GetCapture()
        if cap and self._hwnd and int(cap) == self._hwnd:
            user32.ReleaseCapture()
        if drag.active:
            # Only after a real move. The cursor is global: putting the
            # arrow back when nothing changed it would flick whatever
            # cursor the window under the mouse is showing. And it is the
            # ZONE that decides, not the arrow unconditionally — a drag
            # ends with the hand still on the bar almost every time, and
            # an arrow there for the one frame before the next
            # WM_SETCURSOR is a flicker saying the handle has gone.
            user32.SetCursor(_cursor(IDC_SIZEALL
                                     if self._cursor_zone() == "bar"
                                     else IDC_ARROW))

    def _begin_resize(self, hwnd: int, x: int, y: int) -> None:
        """Take hold of a corner, without taking the focus.

        Called from the RESIZER and nowhere else — the discipline
        _begin_drag holds to for the bar. Nothing here resizes anything:
        the press is only recorded, and it becomes a size in _resize_to()
        or it becomes nothing. SetCapture is what makes the rest of the
        gesture arrive after the pointer has left an 18 px square — a few
        pixels of real hand movement — and it activates, focuses and
        raises nothing, for all the same reasons the drag's capture does
        not.

        WHICH grip was grabbed is decided here from the press point,
        because both bottom corners resize and each grows against its own
        fixed top corner. The corner and the bounds of the monitor are
        read NOW, at the press, and carried in the _Resize: mid-gesture
        neither may move under the hand.
        """
        lay = self._lay
        r, pt = w.RECT(), w.POINT()
        if lay is None or not (self._hwnd
                               and user32.GetWindowRect(hwnd,
                                                        ctypes.byref(r))
                               and user32.GetCursorPos(ctypes.byref(pt))):
            return
        if _inside(lay.resizer_l, x, y):
            # Grip bottom-left: the top-right corner stays put.
            grip_right, fix_x, fix_y = False, int(r.right), int(r.top)
        else:
            # Grip bottom-right (and any stray press): top-left stays put.
            grip_right, fix_x, fix_y = True, int(r.left), int(r.top)
        centre = w.POINT((r.left + r.right) // 2, (r.top + r.bottom) // 2)
        mi = MONITORINFO()
        mi.cbSize = ctypes.sizeof(MONITORINFO)
        mon = user32.MonitorFromPoint(centre, MONITOR_DEFAULTTONEAREST)
        if not (mon and user32.GetMonitorInfoW(mon, ctypes.byref(mi))):
            mi.rcMonitor = w.RECT(0, 0,
                                  user32.GetSystemMetrics(SM_CXSCREEN),
                                  user32.GetSystemMetrics(SM_CYSCREEN))
        # The FULL monitor rect, at the owner's request — "any size I
        # want, to the point where it's full screen". A margin here was a
        # ceiling he kept hitting long before the screen ran out.
        cap_w = max(self._min_w, mi.rcMonitor.right - mi.rcMonitor.left)
        cap_h = max(self._min_h, mi.rcMonitor.bottom - mi.rcMonitor.top)
        self._resizing = _Resize(
            grip_right=grip_right, fix_x=fix_x, fix_y=fix_y,
            cap_w=cap_w, cap_h=cap_h,
            start_x=int(pt.x), start_y=int(pt.y),
            slop_x=max(1, user32.GetSystemMetrics(SM_CXDRAG)),
            slop_y=max(1, user32.GetSystemMetrics(SM_CYDRAG)))
        user32.SetCapture(hwnd)

    def _resize_to(self, hwnd: int) -> None:
        """Follow the cursor: grow or shrink against the far corner.

        THE FRAME FIRST, AND ALWAYS. The size the hand asks for is applied
        to the window IN THIS MESSAGE, verbatim, before anything else — a
        SetWindowPos costs microseconds, and applying it first is the
        difference the owner was pointing at when he said a Chrome window
        "really moves millimeter by millimeter with my mouse". The first
        cut re-laid the answer out inline before every move, and whenever
        that work out-lasted the gap between moves — any long answer, any
        fast hand — the moves piled up behind it and the frame caught up
        in bursts: stick, nothing, ten centimetres. A frame that waits on
        typography is not tracking; it is queueing.

        The CONTENT catches up on a throttle instead: at most one reflow
        per _REFIT_MS, always against the LATEST size (earlier requests
        are superseded, never queued), so the text trails the edge by less
        than the eye holds and never costs the frame a pixel. The release
        runs one last exact refit, so what you let go of is what you get.
        Auto-fit still has its say INSIDE the frame — growing recovers
        type toward the default first, shrinking spends the face's slack
        before it spends words — and the refit works from the FULL
        answer, so pulling outward can bring back lines an earlier cap
        cut off.
        """
        rz, pt = self._resizing, w.POINT()
        if rz is None or not user32.GetCursorPos(ctypes.byref(pt)):
            return
        if not rz.active:
            # SM_CXDRAG/SM_CYDRAG, read exactly as the move gesture reads
            # them: a press that wobbles within the slop is a click on
            # nothing, not a resize.
            if (abs(pt.x - rz.start_x) < rz.slop_x
                    and abs(pt.y - rz.start_y) < rz.slop_y):
                return
            rz.active = True
            # Set here and not left to WM_SETCURSOR because Windows sends
            # none while a capture is held — measured and written down in
            # the drag's WM_SETCURSOR case — so the cursor would stick on
            # whatever it was showing at the press.
            user32.SetCursor(_cursor(IDC_SIZENWSE if rz.grip_right
                                     else IDC_SIZENESW))
        wanted_w = pt.x - rz.fix_x if rz.grip_right else rz.fix_x - pt.x
        wanted_h = pt.y - rz.fix_y
        wanted_w = min(max(wanted_w, self._min_w), rz.cap_w)
        wanted_h = min(max(wanted_h, self._min_h), rz.cap_h)
        if self._user_size == (wanted_w, wanted_h):
            return                  # the hand has not asked for anything new
        self._user_size = (wanted_w, wanted_h)
        x = rz.fix_x if rz.grip_right else rz.fix_x - wanted_w
        y = rz.fix_y
        # The frame, THIS message. Nothing stands between the cursor and
        # the edge — least of all a wrap-and-measure of the answer.
        user32.SetWindowPos(hwnd, None, int(x), int(y),
                            int(wanted_w), int(wanted_h),
                            SWP_NOZORDER | SWP_NOACTIVATE)
        if not self._refit_scheduled:
            self._refit_scheduled = True
            user32.SetTimer(hwnd, ctypes.c_void_p(_RESIZE_TIMER_ID),
                            _REFIT_MS, None)

    def _refit_now(self) -> None:
        """Bring the text up to date with the frame the hand has drawn.

        Runs on the popup thread, from the resize tick and from the
        release. The window is ALREADY the right size — this only lays
        the answer out inside it, so nothing here may move the window:
        _fit_window returns the hand's own dimensions and they are
        believed, never re-applied.
        """
        if not (self._hwnd and self.visible()):
            return
        lay = self._fit_window(self._answer or self._text, self._rtl)
        self._lay = lay
        user32.InvalidateRect(self._hwnd, None, True)
        user32.UpdateWindow(self._hwnd)

    def _end_resize(self) -> None:
        """Let go of the corner — whatever it was that let go for us.

        Four ways in, the same list _end_drag keeps: the button coming up,
        the WM_CAPTURECHANGED ReleaseCapture sends straight back, a
        capture TAKEN AWAY by something else, and a button-less mouse
        move. Idempotent like its sibling, so hide() and show() may call
        it blind.

        What survives is the SIZE — keeping it was the point — and never
        the cursor: putting the diagonal away when the hand has moved on
        to the bar or the body hands the arrow back, the same zone rule
        the drag ends under.
        """
        rz, self._resizing = self._resizing, None
        if rz is None:
            return
        if self._refit_scheduled:
            # A tick was still owed when the hand let go: pay it now,
            # once, exactly — what is released must be what is shown.
            user32.KillTimer(self._hwnd, ctypes.c_void_p(_RESIZE_TIMER_ID))
            self._refit_scheduled = False
        cap = user32.GetCapture()
        if cap and self._hwnd and int(cap) == self._hwnd:
            user32.ReleaseCapture()
        if rz.active:
            self._refit_now()
            zone = self._cursor_zone()
            if zone == "resize":
                # Which corner the hand came to rest on decides the
                # diagonal — both are live now, so this is asked of the
                # rects and not of the answer's language.
                cpt = self._cursor_point()
                cur = self._lay
                on_right = _inside(cur.resizer_r, *cpt) \
                    if (cur is not None and cpt is not None) else True
                ident = IDC_SIZENWSE if on_right else IDC_SIZENESW
            elif zone == "bar":
                ident = IDC_SIZEALL
            else:
                ident = IDC_ARROW
            user32.SetCursor(_cursor(ident))

    def _on_message(self, hwnd: int, msg: int, wparam: int, lparam: int):
        """Return None for anything DefWindowProcW should handle."""
        if msg == WM_PAINT:
            self._paint(hwnd)
            return 0
        if msg == WM_ERASEBKGND:
            return 1                    # _paint fills every pixel itself
        if msg == WM_MOUSEACTIVATE:
            return MA_NOACTIVATE        # a click on us must not focus us
        if msg == WM_SETCURSOR:
            # Answered here EVERY time, not only while dragging, and
            # that is what makes the drag cursor stick. Measured
            # 2026-08-20: while the mouse is captured Windows sends no
            # WM_SETCURSOR at all — one before the press, one after the
            # release, none in between across 14 moves — so the size-all
            # can only come from _drag_to. And while the last
            # WM_SETCURSOR was left to DefWindowProcW, the class cursor
            # came back within ~20 ms of every move and the box was
            # dragged under a plain arrow. Answered here instead, TRUE
            # for "handled, stop looking", GetCursorInfo sampled every
            # 4 ms from another thread read the move cursor unbroken for
            # 661-962 ms of a drag that ran 608-965 ms.
            # Non-client hit tests are left to DefWindowProcW; a
            # WS_POPUP with no frame never produces one.
            if (lparam & 0xFFFF) != HTCLIENT:
                return None
            # Three cursors, and each is a promise about what a press is
            # going to do before the press happens: the move cursor on
            # the bar, an I-beam over a line of the answer, and the
            # arrow everywhere else — over the buttons, as it is on
            # every title bar button on this machine, and over the
            # padding, where there is no line to take.
            #
            # The I-beam over-promises by exactly one thing and it is
            # worth it: it says "text", which is true and is the only
            # affordance saying the answer can be taken at all, while
            # what a press actually takes is the whole line. Nothing on
            # Windows has a "line" cursor.
            dragging = self._drag is not None and self._drag.active
            pt = self._cursor_point()
            zone = "bar" if dragging else (self._zone_at(*pt) if pt
                                           else "body")
            if zone == "bar":
                ident = IDC_SIZEALL
            elif zone == "resize":
                # The diagonal that matches the corner held — bottom-right
                # drags the south-east edge (NWSE arrows), bottom-left the
                # mirror. Both corners resize now, so this is decided by
                # WHICH square is under the hand, not by the answer's
                # language.
                cur = self._lay
                on_right = cur is not None and _inside(
                    cur.resizer_r, pt[0], pt[1]) if pt else True
                ident = IDC_SIZENWSE if on_right else IDC_SIZENESW
            elif self._selecting or (zone == "body" and pt is not None
                                     and self._line_at(pt[1]) is not None):
                ident = IDC_IBEAM
            else:
                ident = IDC_ARROW
            user32.SetCursor(_cursor(ident))
            return 1
        if msg == WM_MOUSEMOVE:
            if (self._selecting and not (wparam & MK_LBUTTON)
                    and int(user32.GetCapture() or 0) != hwnd):
                # The same backstop the drag has, one line below, and for
                # the same reason: a capture taken away by something that
                # also swallows the button-up would leave the box
                # extending a selection under a hand that let go long
                # ago. What is already selected stays selected — this
                # ends the GESTURE, not the range.
                self._end_select()
            if self._selecting:
                self._select_to(*self._point(lparam))
                return 0
            if (self._drag is not None and not (wparam & MK_LBUTTON)
                    and int(user32.GetCapture() or 0) != hwnd):
                # Nothing held AND the capture gone: this gesture is over
                # however it ended. The backstop for a capture that went
                # away without saying so — measured 2026-08-20, another
                # window of this process calling SetCapture took it with
                # NO WM_CAPTURECHANGED here, and _drag was still live.
                # That one recovered on the button-up, which still found
                # its way home, but a capture lost to something that also
                # swallows the up (the secure desktop) would have left the
                # box following a cursor with nothing held down and
                # nothing to press to stop it.
                #
                # BOTH conditions, and the second is why: a real drag
                # holds the capture for its whole length, so this cannot
                # fire during one, whatever the message says about the
                # button. On the message alone it did fire — button-less
                # WM_MOUSEMOVEs from the moving cursor arrive in between
                # the ones a test synthesises, and the box stopped
                # following halfway through every drag test there is.
                self._end_drag()
            if self._drag is not None:
                # A gesture that has hold of the box is not also hovering
                # its button: the cursor keeps its position WITHIN the
                # window for the whole drag — except where _on_screen
                # clamps the box against an edge and the cursor slides on
                # without it, which is not worth a repaint mid-move. The
                # first move after the release settles the hover, and
                # re-subscribes the leave this branch skips.
                self._drag_to(hwnd)
                return 0
            if (self._resizing is not None and not (wparam & MK_LBUTTON)
                    and int(user32.GetCapture() or 0) != hwnd):
                # The resize's own copy of the same backstop: a capture
                # taken away by something that also swallowed the
                # button-up must not leave the corner growing under a
                # hand that let go long ago. This ends the GESTURE; the
                # size it reached stays — that was the point of it.
                self._end_resize()
            if self._resizing is not None:
                self._resize_to(hwnd)
                return 0
            # The button being physically down is read off the message
            # rather than remembered, because a release OUTSIDE the window
            # is never delivered to it: without this the box would still
            # be armed minutes later, and the next stray release over the
            # corner would close it out of nowhere.
            zone = self._zone(lparam)
            armed = self._armed if (wparam & MK_LBUTTON) else None
            self._set_hot(zone if zone in _BUTTONS else None, armed)
            # Asked for again on every move: TrackMouseEvent is a
            # one-shot subscription, cancelled by the leave it delivers.
            t = TRACKMOUSEEVENT(ctypes.sizeof(TRACKMOUSEEVENT), TME_LEAVE,
                                hwnd, 0)
            user32.TrackMouseEvent(ctypes.byref(t))
            return 0
        if msg == WM_MOUSELEAVE:
            # This used to CLOSE the box, and that is the "it disappears
            # randomly" the owner reported: the box opens under the
            # cursor, so the first twitch of the mouse dismissed the
            # answer. All it may do now is un-highlight the button — and
            # NOT disarm it, or a press that strays off the box for one
            # pixel and comes back would silently stop being a press.
            self._set_hot(None, self._armed)
            return 0
        if msg in (WM_LBUTTONDOWN, WM_LBUTTONDBLCLK):
            # Three answers. On a button it arms. On the BAR it takes
            # hold of the box — which is still nothing at all until the
            # hand moves past the drag threshold. In the body it takes
            # text: one line, or the whole sense if this is the second
            # press of a double-click.
            #
            # Whichever it is, it is decided HERE and once. That is what
            # keeps the two gestures from fighting: a press that began in
            # the body can never move the window however far it travels,
            # and a press that began on the bar can never select.
            x, y = self._point(lparam)
            zone = self._zone_at(x, y)
            on_button = zone if zone in _BUTTONS else None
            self._set_hot(on_button, on_button)
            if zone == "bar":
                self._begin_drag(hwnd)
            elif zone == "resize":
                # The corner opposite the bar's handle — either one of
                # the two bottom squares now. Same discipline: the press
                # is only recorded, and it becomes a resize in
                # _resize_to or it becomes nothing.
                self._begin_resize(hwnd, x, y)
            elif zone == "body":
                if msg == WM_LBUTTONDBLCLK:
                    self._select_word(self._point_at(x, y))
                else:
                    self._begin_select(hwnd, self._point_at(x, y))
            return 0
        if msg == WM_CAPTURECHANGED:
            # The DRAG only, and the selection deliberately not.
            # Measured 2026-08-20: Windows releases the capture ITSELF at
            # the button-up, and the WM_CAPTURECHANGED that says so
            # arrives one message BEFORE the WM_LBUTTONUP. Ending the
            # selection here would therefore throw the release away, and
            # the release is the one message that says where the hand
            # finally was — 4 of 50 fast drag-selects stopped a line
            # short without it, because mouse moves are coalesced and
            # the last one before the release is not guaranteed to
            # exist. A capture taken away mid-gesture is covered by the
            # button-less move above instead, which is the same backstop
            # the drag has. The resize has no such ordering problem — a
            # corner held mid-gesture keeps nothing the release needs —
            # so it ends here like the drag does.
            self._end_drag()
            self._end_resize()
            return 0
        if msg == WM_LBUTTONUP:
            if self._drag is not None:
                self._end_drag()
                return 0
            if self._resizing is not None:
                # The release is the commit: whatever size the corner
                # reached is the size the box keeps until the next new
                # question. Nothing to fire, unlike a button — a click on
                # the grip that never moved is a no-op either way.
                self._end_resize()
                return 0
            if self._selecting:
                # Where the button came up, from the message rather than
                # from the cursor: by the time this is handled the hand
                # has moved on, and a selection that ran to wherever the
                # pointer happens to be NOW is a selection nobody made.
                self._select_to(*self._point(lparam))
                self._end_select()
                return 0
            # Armed AND released on the SAME button: the rule every push
            # button on Windows follows, which is why sliding off before
            # letting go cancels and sliding back on does not — and why
            # sliding from copy to close does not close the box.
            zone = self._zone(lparam)
            fired = self._armed if self._armed == zone else None
            self._set_hot(zone if zone in _BUTTONS else None, None)
            if fired == "close":
                self._do_hide("close button")
            elif fired == "copy":
                self._fire_copy()
            elif fired == "copysel":
                self._fire_copy("selection")
            return 0
        if msg == WM_TIMER:
            if int(wparam) == _FLASH_TIMER_ID:
                user32.KillTimer(hwnd, ctypes.c_void_p(_FLASH_TIMER_ID))
                self._flash = None
                self._repaint_bar()
                return 0
            if int(wparam) == _RESIZE_TIMER_ID:
                # The content catch-up a running drag owed. The frame
                # itself never waited on this — see _resize_to — so all
                # it does is bring the text to the size the hand has
                # already drawn.
                user32.KillTimer(hwnd, ctypes.c_void_p(_RESIZE_TIMER_ID))
                self._refit_scheduled = False
                self._refit_now()
                return 0
            self._do_hide("dwell")
            return 0
        if msg == WM_DESTROY:
            _INSTANCES.pop(hwnd, None)
            self._hwnd = None
            return 0
        return None

    # ------------------------------------------------------------- paint

    def _paint(self, hwnd: int) -> None:
        ps = PAINTSTRUCT()
        hdc = user32.BeginPaint(hwnd, ctypes.byref(ps))
        try:
            r = w.RECT()
            user32.GetClientRect(hwnd, ctypes.byref(r))
            user32.FillRect(hdc, ctypes.byref(r), _brush(BG))
            if not self._rounded_by_dwm:
                # Only when the compositor is not drawing one for us: its
                # border sits outside the client area, one drawn here sits
                # inside it, and both at once is a two-pixel frame.
                user32.FrameRect(hdc, ctypes.byref(r), _brush(EDGE))
            lay = self._lay
            if lay is None:
                return
            gdi32.SetBkMode(hdc, TRANSPARENT)
            self._paint_bar(hdc, lay)
            self._paint_body(hdc, lay)
            self._paint_resizer(hdc, lay)
            if lay.rule is not None:
                user32.FillRect(hdc, ctypes.byref(lay.rule), _brush(EDGE))
        finally:
            user32.EndPaint(hwnd, ctypes.byref(ps))

    def _paint_body(self, hdc: int, lay: _Layout) -> None:
        """Every line, in the rectangle _layout() measured for it.

        One DrawTextW per visual line with DT_SINGLELINE, where it used
        to be one per block with DT_WORDBREAK. That is the whole change
        the selection needed, and it is cheaper as well: the wrap is
        decided once in _layout() instead of being redone by DrawTextW
        on every repaint.

        A selected line gets the band first and then its text in FG
        rather than its own colour — see SEL for the contrast that buys.
        The band runs the full width of the body and _SEL_GROW past it
        each side, because it says "this line is taken", not "these
        glyphs are".

        The row is clipped to its own rectangle by DrawTextW, so a line
        can only ever be painted where it was measured.
        """
        flags = self._flags(lay.rtl)
        for i, line in enumerate(lay.lines):
            span = self._span_on(i)
            old = gdi32.SelectObject(hdc,
                                     self._font(line.role, line.size_px))
            gdi32.SetTextColor(hdc, self._FACE.get(
                line.role, self._FACE["body"])[2])
            try:
                self._paint_line(hdc, lay, line, span, flags)
            finally:
                gdi32.SelectObject(hdc, old)

    def _paint_resizer(self, hdc: int, lay: _Layout) -> None:
        """Three nested diagonals in EACH bottom corner.

        The glyph every resize grip on this machine draws, at the
        smallest size it stays legible: three 1 px hairlines parallel to
        the corner's hypotenuse, stepping four pixels out from it. DIM,
        and deliberately nothing more: the move handle next door — the
        bar — has no visible affordance either, and this box's handles
        announce themselves with the CURSOR, which arrives the moment
        the hand does. A brighter grip would be a permanent decoration
        on a window whose whole point is to sit quietly over somebody
        else's text.

        BOTH corners carry the glyph, because both corners resize: a
        single mirrored grip was measured in the field as a trap, since
        which corner was live depended on the answer's language and the
        same grab grew one box and did nothing to the next.
        """
        old_pen = gdi32.SelectObject(hdc, _pen(DIM))
        try:
            for b in (lay.resizer_r, lay.resizer_l):
                for k in range(3):
                    if b is lay.resizer_r:
                        x0, y0 = b.right - 5 - k * 4, b.bottom - 1
                        x1, y1 = b.right - 1, b.bottom - 5 - k * 4
                    else:
                        x0, y0 = b.left + 5 + k * 4, b.bottom - 1
                        x1, y1 = b.left + 1, b.bottom - 5 - k * 4
                    gdi32.MoveToEx(hdc, x0, y0, None)
                    gdi32.LineTo(hdc, x1, y1)
        finally:
            gdi32.SelectObject(hdc, old_pen)

    def _paint_line(self, hdc: int, lay: _Layout, line: _Line,
                    span: tuple[int, int] | None, flags: int) -> None:
        """One visual line, and the part of it that is lit.

        ScriptStringOut and not DrawTextW, for every line and not only
        the selected one. The reason is the owner's own condition — the
        text must not move a pixel when it is selected — and two painters
        on alternate lines of one paragraph is exactly how it would. The
        two were compared byte for byte over 610 lines before this was
        written; see the uniscribe section at the top of the file.

        The highlight is drawn by Uniscribe rather than filled in here,
        and that is the whole reason the character selection is worth
        having: ScriptStringOut is given a LOGICAL range and works out
        for itself which rectangles that is on screen. Drag through
        "Whisper הוא" and it lights "isper" and "הוא" as two separate
        blocks with the "Wh" dark between them — one range, two boxes,
        the way every browser draws it, and something a rectangle filled
        behind a range of characters could not do.

        SetBkColor is the SELECTED ground: ScriptStringOut swaps the
        text and background colours for the selected run, so the band is
        this app's own SEL and never the system's blue slab.

        DrawTextW stays as the fallback for the one case Uniscribe can
        refuse — a shaping failure on a string neither of them was
        expecting — because a line drawn slightly differently beats a box
        with a hole in it.
        """
        x, y = line.rect.left, line.rect.top
        try:
            with _Shaped(hdc, line.text, lay.rtl) as shaped:
                if lay.rtl:
                    # DT_RIGHT has no equivalent here: the line is placed
                    # by measuring it and starting that far in from the
                    # right edge.
                    x = line.rect.right - shaped.width
                if span:
                    # The band is filled here and NOT left to
                    # ScriptStringOut's own selection, which paints in
                    # COLOR_HIGHLIGHT — the system's bright blue, which
                    # on this ground shouts, and which no API will trade
                    # for another. runs() says where the selected
                    # characters landed, in one piece or two, so the
                    # highlight keeps the app's own SEL and still breaks
                    # correctly across a change of direction.
                    for a, b in shaped.runs(*span):
                        band = w.RECT(int(x) + a, line.rect.top,
                                      int(x) + b, line.rect.bottom)
                        user32.FillRect(hdc, ctypes.byref(band),
                                        _brush(SEL))
                # THE RECTANGLE IS NOT PASSED TO ScriptStringOut, and
                # that is not an omission. Together with ETO_OPAQUE a
                # rectangle means "fill ALL of this", so handing it the
                # row painted the highlight across the row's whole width
                # — a solid band reaching out past the last letter into
                # the empty half of a short line, which is what it looked
                # like: text selected that was not there. With no
                # rectangle, ETO_OPAQUE fills only the glyphs' own
                # extents, which is what a selection is.
                #
                # The row is still clipped, because a line must not be
                # able to paint outside the rectangle it was measured
                # into — through the DC's clip region, which bounds the
                # drawing without claiming anything about what to fill.
                saved = gdi32.SaveDC(hdc)
                try:
                    gdi32.IntersectClipRect(hdc, line.rect.left,
                                            line.rect.top, line.rect.right,
                                            line.rect.bottom)
                    # No selection range and no ETO_OPAQUE: the band is
                    # already down, and this draws the whole line over
                    # it exactly as it draws an unselected one. That is
                    # what keeps a selected line identical to the same
                    # line unselected, glyph for glyph.
                    usp10.ScriptStringOut(shaped.ssa, int(x), int(y),
                                          0, None, 0, 0, False)
                finally:
                    gdi32.RestoreDC(hdc, saved)
                return
        except Exception as e:
            log.debug("uniscribe would not draw %r: %r", line.text[:20], e)
        box = w.RECT(line.rect.left, line.rect.top,
                     line.rect.right, line.rect.bottom)
        user32.DrawTextW(hdc, line.text, -1, ctypes.byref(box), flags)

    def _paint_bar(self, hdc: int, lay: _Layout) -> None:
        """The strip across the top: a quieter ground, a hairline under
        it, the buttons, and one line of caption.

        Quiet on purpose. This is a 300 px box and not an application
        window, so the bar is BG a quarter of the way to EDGE — enough
        that the eye reads a separate surface and knows where to take
        hold, not so much that it competes with the answer three
        millimetres below it. The hairline is the same EDGE the headline
        separator uses, which is the box saying "a rule means a division"
        in one voice.

        The label goes DIM, and smaller than the smallest line of the
        answer. While a flash is up it is replaced by what the copy
        button just did, in the colour that says which: ACCENT for a copy
        that landed, the app's red for a clipboard that would not open.
        """
        user32.FillRect(hdc, ctypes.byref(lay.bar), _brush(BAR_BG))
        line = w.RECT(lay.bar.left, lay.bar.bottom - 1, lay.bar.right,
                      lay.bar.bottom)
        user32.FillRect(hdc, ctypes.byref(line), _brush(EDGE))

        text, colour = lay.label, DIM
        if self._flash is not None:
            text, colour = self._flash_words(lay.rtl)
        if text:
            old = gdi32.SelectObject(hdc, self._font("bar", lay.size_px))
            gdi32.SetTextColor(hdc, colour)
            box = w.RECT(lay.label_rect.left, lay.label_rect.top,
                         lay.label_rect.right, lay.label_rect.bottom)
            # DT_END_ELLIPSIS and not a measurement: the label is a
            # passenger in a width the ANSWER decided, so anything too
            # long for the room left over is the OS's to shorten. The box
            # never grows for it.
            flags = (DT_SINGLELINE | DT_VCENTER | DT_NOPREFIX
                     | DT_END_ELLIPSIS)
            if lay.rtl:
                flags |= DT_RTLREADING | DT_RIGHT
            user32.DrawTextW(hdc, text, -1, ctypes.byref(box), flags)
            gdi32.SelectObject(hdc, old)

        self._paint_close(hdc, lay)
        if lay.show_copy:
            self._paint_copy(hdc, lay.copy, "copy")
            if self._sel is not None:
                self._paint_copy(hdc, lay.copysel, "copysel")

    def _flash_words(self, rtl: bool) -> tuple[str, int]:
        """What the bar says after the copy button, in the box's own
        language — a box laid out for Hebrew cannot show an English line
        without it coming out in the wrong order (see the module
        docstring), and this is the app talking, so it says it in the
        language the answer is in."""
        if self._flash == "copied":
            return ("הועתק" if rtl else "copied"), ACCENT
        return ("הלוח תפוס" if rtl else "clipboard busy"), PRESSED

    def _chip(self, hdc: int, b: w.RECT, fill: int) -> None:
        """The rounded slab under a button that the mouse is on."""
        old_pen = gdi32.SelectObject(hdc, gdi32.GetStockObject(NULL_PEN))
        old_brush = gdi32.SelectObject(hdc, _brush(fill))
        gdi32.RoundRect(hdc, b.left, b.top, b.right + 1, b.bottom + 1,
                        7, 7)
        gdi32.SelectObject(hdc, old_brush)
        gdi32.SelectObject(hdc, old_pen)

    def _fill_for(self, name: str, pressed: int) -> int | None:
        """A button's chip colour: none, hovered, or held down."""
        if self._hover != name:
            return None
        return pressed if self._armed == name else HOVER

    def _paint_close(self, hdc: int, lay: _Layout) -> None:
        """The x you click, at the outer end of the bar.

        Top-left for a Hebrew answer and top-right for an English one:
        the far corner on the side the reading ends, which is where the
        rest of this box already puts the things you finish with.

        Three states, because a control that does not react to the mouse
        reads as decoration and gets clicked twice: dim on its own, a
        slate chip and a bright glyph under the cursor, and the app's red
        while it is held down — which is where every close button on this
        operating system goes red, and it says "let go here and this
        disappears" before you have committed to it.
        """
        b = lay.button
        fill = self._fill_for("close", PRESSED)
        if fill is not None:
            self._chip(hdc, b, fill)
        old_pen = gdi32.SelectObject(
            hdc, _pen(FG if self._hover == "close" else DIM))
        inset = 5
        left, top = b.left + inset, b.top + inset
        right, bottom = b.right - inset, b.bottom - inset
        gdi32.MoveToEx(hdc, left, top, None)
        gdi32.LineTo(hdc, right + 1, bottom + 1)
        gdi32.MoveToEx(hdc, left, bottom, None)
        gdi32.LineTo(hdc, right + 1, top - 1)
        gdi32.SelectObject(hdc, old_pen)

    def _paint_copy(self, hdc: int, b: w.RECT, name: str) -> None:
        """Two sheets of paper, one behind the other — and a tick for a
        moment after it has been pressed.

        The same treatment as the close button and one deliberate
        difference: held down it goes ACCENT and not red. Red on this
        machine means "this destroys something", and a copy destroys
        nothing; the box's own blue is the colour it uses for the thing
        that just worked.

        BOTH copy buttons are drawn here, and the only difference between
        them is that the copy-selection one's top sheet is FILLED, in the
        selection's own colour. That is the smallest true difference
        there is: same family, same gesture, and the thing it will copy
        is the thing wearing that colour three millimetres below. Two
        unrelated glyphs at ten pixels would only be two glyphs nobody
        can tell apart.

        The tick is the confirmation, drawn in the button the finger is
        still on rather than somewhere the eye would have to go looking,
        and in a 2 px pen so it reads at ten pixels. It stays for
        _FLASH_MS and then the sheets come back. A copy button that shows
        nothing gets pressed three times.
        """
        fill = self._fill_for(name, ACCENT)
        if fill is not None:
            self._chip(hdc, b, fill)
        done = self._flash == "copied" and self._flash_on == name
        if done:
            colour = ACCENT if fill is None else FG
        else:
            colour = FG if self._hover == name else DIM
        # A 10 x 10 glyph box, centred in the 18 px hit rectangle.
        gx, gy = b.left + 4, b.top + 4
        old_pen = gdi32.SelectObject(hdc, _pen(colour, 2 if done else 1))
        if done:
            gdi32.MoveToEx(hdc, gx + 1, gy + 5, None)
            gdi32.LineTo(hdc, gx + 4, gy + 8)
            gdi32.LineTo(hdc, gx + 10, gy + 1)
        else:
            # The sheet underneath, as the corner of it that shows.
            gdi32.MoveToEx(hdc, gx + 6, gy, None)
            gdi32.LineTo(hdc, gx, gy)
            gdi32.LineTo(hdc, gx, gy + 7)
            # And the sheet on top of it. An explicit brush either way,
            # or RoundRect fills the outline with whatever the DC last
            # had — which is the chip's colour when there is one.
            old_brush = gdi32.SelectObject(
                hdc, _brush(SEL) if name == "copysel"
                else gdi32.GetStockObject(NULL_BRUSH))
            gdi32.RoundRect(hdc, gx + 2, gy + 2, gx + 10, gy + 10, 3, 3)
            gdi32.SelectObject(hdc, old_brush)
        gdi32.SelectObject(hdc, old_pen)


# ------------------------------------------------------------------- CLI

_PARAGRAPH = (
    "כאשר המשתמש מסמן טקסט כלשהו על המסך, בין אם מדובר בשדה עריכה ובין "
    "אם בטקסט לקריאה בלבד, ולוחץ על מקש הקיצור שהוגדר, התוכנה מעתיקה את "
    "הבחירה, שולחת אותה למנוע התרגום המקומי, ומציגה את התוצאה בעברית "
    "בתוך תיבה קטנה הצפה ליד הסמן. התיבה אינה נוגעת בטקסט המקורי, אינה "
    "גונבת את הפוקוס מהחלון הפעיל, ונסגרת ברגע שהמשתמש לוחץ על כפתור "
    "הסגירה שלה."
)

# The two shapes lookup.py actually produces, for looking at the layout
# without a model behind it.
_WORD_HE = ("שביר\n"
            "1. שם תואר - נשבר או נסדק בקלות, לא עמיד במאמץ.\n"
            "2. שם תואר - רגיש ומועד לכישלון פתאומי.")
_WORD_EN = ("brittle\n"
            "1. adjective - hard but liable to break or snap.\n"
            "2. adjective - fragile under stress, with no warning.")
_SENTENCE_HE = "המטמון נפסל בכל כתיבה, ולכן הקריאה השנייה איטית."


def _main(argv: list[str] | None = None) -> int:
    """Show one box and wait, so the popup can be looked at on its own.

        python popup.py "הדגם לא ענה"
        python popup.py --word
        python popup.py --ltr "a race condition"
        python popup.py --paragraph --anchor 900,500
        python popup.py --word --anchor-mouse --hold 20

    --anchor-mouse and --anchor 'x,y' put the box where a selection would
    have been, which is the only way to see the placement rules without
    the whole app running. Whatever it opens on, it can then be dragged
    BY ITS TITLE BAR, resized BY THE DIAGONAL GRIP IN THE FAR BOTTOM
    CORNER, and by nothing else: the last line printed says how far it
    ended up from where it opened, so a drag from the body should print
    0,0 and a drag from the bar should not. --delay is the one to run to
    see that an answer arriving does not take the box back, and --term
    fills the bar with a word the way a real lookup will.

    Auto-fit is worth seeing on purpose: text too tall for --height comes
    back at a smaller face instead of trimmed, down to --min-font, past
    which the ellipsis takes over. The chosen face is printed with the
    rect.

    Press on a line of the answer and it is taken; drag down and the
    range is; double-click and the whole sense is. A third button appears
    in the bar while something is selected, and Ctrl+C does the same
    thing while the box is up and you have not switched away from the
    window you were reading. What was selected when the box closed is
    printed at the end.

    The copy button is the second one in from the corner and copies
    everything. Press it and paste somewhere: what lands is the whole
    answer, untrimmed, and the clipboard you had before is gone on
    purpose.
    """
    import argparse

    p = argparse.ArgumentParser(
        prog="popup", description="Show the lookup popup once.")
    p.add_argument("text", nargs="*", help="what to show")
    p.add_argument("--rtl", dest="rtl", action="store_true", default=None,
                   help="lay out for a Hebrew reader (the default)")
    p.add_argument("--ltr", dest="rtl", action="store_false",
                   help="lay out for an English reader")
    p.add_argument("--paragraph", action="store_true",
                   help="use the built-in 60-word Hebrew sample")
    p.add_argument("--word", action="store_true",
                   help="use a built-in two-sense dictionary answer")
    p.add_argument("--sentence", action="store_true",
                   help="use a built-in one-line Hebrew translation")
    p.add_argument("--anchor", metavar="X,Y",
                   help="screen point to open next to, e.g. 1200,700")
    p.add_argument("--anchor-mouse", action="store_true",
                   help="open next to wherever the mouse is now")
    p.add_argument("--anchor-caret", action="store_true",
                   help="probe the foreground window for a caret and "
                        "open next to that, falling back to the mouse")
    p.add_argument("--dwell", type=int, default=0,
                   help="milliseconds on screen (0 = until you close it)")
    p.add_argument("--hold", type=float, default=8.0,
                   help="seconds to keep the process alive so the box can "
                        "be clicked at")
    p.add_argument("--delay", type=int, default=0,
                   help="show '…' first and reveal the text this many "
                        "milliseconds later, as a real lookup does")
    p.add_argument("--term", default="",
                   help="what was looked up, for the title bar (the app "
                        "passes the selection here)")
    p.add_argument("--width", type=int, default=460)
    p.add_argument("--height", type=int, default=520)
    p.add_argument("--min-font", type=int, default=_FONT_FLOOR,
                   help="the smallest face auto-fit may descend to")
    args = p.parse_args(argv)

    if args.word:
        text = _WORD_EN if args.rtl is False else _WORD_HE
    elif args.sentence:
        text = _SENTENCE_HE
    elif args.paragraph:
        text = _PARAGRAPH
    else:
        text = " ".join(args.text)
    if not text:
        p.error("give it some text, or --word, --sentence or --paragraph")
    rtl = True if args.rtl is None else args.rtl

    anchor = None
    if args.anchor:
        anchor = tuple(int(v) for v in args.anchor.replace(" ", "").split(","))
    elif args.anchor_caret:
        front = user32.GetForegroundWindow()
        anchor = caret_anchor(front)
        print(f"caret under 0x{front:X}: {anchor}")
        if anchor is None:
            args.anchor_mouse = True
    if anchor is None and args.anchor_mouse:
        pt = w.POINT()
        user32.GetCursorPos(ctypes.byref(pt))
        anchor = (pt.x, pt.y)

    logging.basicConfig(level=logging.DEBUG,
                        format="%(levelname)s %(message)s")
    box = Popup(max_width=args.width, max_height=args.height,
                min_font_px=args.min_font)
    if args.delay:
        box.show(WAITING, rtl=rtl, dwell_ms=args.dwell, anchor=anchor,
                 term=args.term)
        time.sleep(args.delay / 1000.0)
        box.update(text)
    else:
        box.show(text, rtl=rtl, dwell_ms=args.dwell, anchor=anchor,
                 term=args.term)
    time.sleep(0.25)
    r = w.RECT()
    opened = None
    if box.hwnd:
        user32.GetWindowRect(box.hwnd, ctypes.byref(r))
        opened = (r.left, r.top)
        face = box._lay.size_px if box._lay else 0
        print(f"hwnd 0x{box.hwnd:X}  rect {r.left},{r.top} "
              f"{r.right - r.left}x{r.bottom - r.top}  face {face}px  "
              f"anchor={anchor}  rtl={rtl}  chars={len(text)}")
        print("drag it BY THE TITLE BAR — across monitors if you like; "
              "a press in the body moves nothing, and a wobble in the "
              "bar is not a move either")
        print("resize it by the diagonal grip in EITHER bottom corner — "
              "pull outward and it grows, up to the full screen; the text "
              "zooms with it, and a bigger box can bring back words a "
              "smaller cap cut off")
        print("the copy button is next to the x: press it, watch for the "
              "tick, and paste — the whole answer is on the clipboard "
              "and stays there")
        print("press a line to take it, drag for a range, double-click "
              "for the whole sense; the third button copies just that, "
              "and so does Ctrl+C")
        print("with --delay, drag it while it says '…' and watch the "
              "answer land where you left it")
    # Alive until it is closed or the hold runs out, so a human can hover
    # the button, press it, drag the box about, and watch what does NOT
    # happen when they click anywhere else without moving.
    deadline = time.monotonic() + max(0.5, args.hold)
    taken = ""
    while time.monotonic() < deadline and box.visible():
        # Sampled while the box is up: closing it lets the selection go,
        # so asking afterwards would always answer "nothing".
        taken = box.selection() or taken
        time.sleep(0.05)
    if box.hwnd and opened and user32.GetWindowRect(box.hwnd,
                                                   ctypes.byref(r)):
        print(f"ended at {r.left},{r.top}  moved by "
              f"{r.left - opened[0]},{r.top - opened[1]}")
    print("selected:", repr(taken) if taken else "nothing")
    print("closed by:", box._hidden_by or "nothing — the hold ran out")
    box.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
