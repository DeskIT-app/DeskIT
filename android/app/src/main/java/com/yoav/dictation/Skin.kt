package com.yoav.dictation

import android.content.Context
import android.content.res.ColorStateList
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.Drawable
import android.graphics.drawable.GradientDrawable
import android.graphics.drawable.RippleDrawable
import android.graphics.drawable.StateListDrawable
import android.util.TypedValue
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.widget.LinearLayout
import android.widget.TextView

/**
 * LAMPLIGHT, on a phone.
 *
 * The same palette as the desktop — skin\palette.py is the source, every
 * hex here is copied from it, not tuned — so the two screens read as one
 * app. What is DIFFERENT is the shapes: the desktop is a dense window of
 * rows and hairlines; the phone is a few large rounded faces with air
 * between them, and the status dot that lives in a screen corner on the
 * desk is here a lamp big enough to hold under a thumb. Same light,
 * another desk.
 *
 * Rubik, the desktop's face, is bundled in res/font (SIL OFL) and loaded
 * once. Two weights only, like the desk: through GDI only 400 and 700 are
 * real, and the phone keeps the same discipline so emphasis comes from
 * size and from ACCENT_TEXT, never from a Medium.
 */
object Skin {

    // ---- surfaces (palette.py's ladder) ----
    val BG = Color.parseColor("#14110C")
    val PANE = Color.parseColor("#1C1813")
    val CARD = Color.parseColor("#24201A")
    val CARD_HI = Color.parseColor("#2E2921")
    val LINE = Color.parseColor("#3A342A")
    val LINE_HI = Color.parseColor("#4E4737")

    // ---- text ----
    val FG = Color.parseColor("#F1ECE2")
    val DIM = Color.parseColor("#B2A896")
    val FAINT = Color.parseColor("#7E7564")

    // ---- the accent: the lamp, the one primary action on a surface ----
    val ACCENT = Color.parseColor("#E3A63C")
    val ACCENT_HI = Color.parseColor("#F0B854")
    val ACCENT_DOWN = Color.parseColor("#C68C28")
    val ACCENT_SOFT = Color.parseColor("#332711")
    val ACCENT_EDGE = Color.parseColor("#5A431A")
    val ACCENT_TEXT = Color.parseColor("#F0BA5C")
    val ACCENT_ON = Color.parseColor("#1A1409")

    // ---- semantics ----
    val GREEN = Color.parseColor("#63C88C")
    val RED = Color.parseColor("#F1867A")
    val COOL = Color.parseColor("#8FC0F0")

    // ---- key caps: a secondary face with a lit rim ----
    val KEY_BG = Color.parseColor("#29241D")
    val KEY_EDGE = Color.parseColor("#4E4737")
    val KEY_HI = Color.parseColor("#332D24")

    /**
     * The five states of the desktop's status dot, verbatim. The dot is
     * checked against its own dark backplate on the desk; here it sits on
     * CARD, which is darker still, so every one of them carries.
     */
    val LISTENING = COOL
    val RECORDING = Color.parseColor("#FF5B4E")
    val LOCKED = Color.parseColor("#FF8A7E")
    val TRANSCRIBING = Color.parseColor("#F5C043")
    val PAUSED = Color.parseColor("#6F6F6F")

    private var regular: Typeface? = null
    private var bold: Typeface? = null

    fun font(c: Context): Typeface = regular ?: try {
        c.resources.getFont(R.font.rubik)
    } catch (e: Exception) {
        Typeface.SANS_SERIF
    }.also { regular = it }

    fun fontBold(c: Context): Typeface = bold ?: try {
        c.resources.getFont(R.font.rubik_bold)
    } catch (e: Exception) {
        Typeface.DEFAULT_BOLD
    }.also { bold = it }

    fun dp(c: Context, v: Int): Int = TypedValue.applyDimension(
        TypedValue.COMPLEX_UNIT_DIP, v.toFloat(), c.resources.displayMetrics
    ).toInt()

    fun dpF(c: Context, v: Float): Float = TypedValue.applyDimension(
        TypedValue.COMPLEX_UNIT_DIP, v, c.resources.displayMetrics
    )

    /** A rounded face with a hairline. The shape every surface here has. */
    fun face(c: Context, fill: Int, edge: Int = LINE, radius: Int = 20,
             stroke: Int = 1): GradientDrawable = GradientDrawable().apply {
        shape = GradientDrawable.RECTANGLE
        cornerRadius = dpF(c, radius.toFloat())
        setColor(fill)
        if (stroke > 0) setStroke(dp(c, stroke), edge)
    }

    /**
     * A face that darkens or lifts under the finger. A StateListDrawable
     * rather than a ripple: the ripple on Material's dark theme is a
     * white flash, which is the one thing LAMPLIGHT never does.
     */
    fun pressable(c: Context, fill: Int, pressed: Int, edge: Int = LINE,
                  radius: Int = 20, stroke: Int = 1): Drawable =
        StateListDrawable().apply {
            addState(intArrayOf(android.R.attr.state_pressed),
                     face(c, pressed, edge, radius, stroke))
            addState(intArrayOf(), face(c, fill, edge, radius, stroke))
        }

    /** The one gold thing on a surface. */
    fun primaryFace(c: Context, radius: Int = 20): Drawable =
        pressable(c, ACCENT, ACCENT_DOWN, ACCENT, radius, 0)

    fun secondaryFace(c: Context, radius: Int = 20): Drawable =
        pressable(c, KEY_BG, KEY_HI, KEY_EDGE, radius, 1)

    fun text(c: Context, s: CharSequence, sp: Float, colour: Int = FG,
             heavy: Boolean = false): TextView = TextView(c).apply {
        text = s
        typeface = if (heavy) fontBold(c) else font(c)
        setTextSize(TypedValue.COMPLEX_UNIT_SP, sp)
        setTextColor(colour)
        includeFontPadding = false
    }

    /** A Latin small-caps eyebrow — the label over a card. */
    fun eyebrow(c: Context, s: String): TextView =
        text(c, s.uppercase(), 11f, FAINT, heavy = true).apply {
            letterSpacing = 0.12f
        }

    fun button(c: Context, s: String, primary: Boolean = false,
               onTap: () -> Unit): TextView = TextView(c).apply {
        text = s
        typeface = fontBold(c)
        setTextSize(TypedValue.COMPLEX_UNIT_SP, 15f)
        setTextColor(if (primary) ACCENT_ON else FG)
        gravity = Gravity.CENTER
        includeFontPadding = false
        val padX = dp(c, 20)
        val padY = dp(c, 14)
        setPadding(padX, padY, padX, padY)
        background = if (primary) primaryFace(c, 16) else secondaryFace(c, 16)
        isClickable = true
        isFocusable = true
        setOnClickListener { onTap() }
    }

    /** The way back, on the page: a round secondary face with an arrow. */
    fun backButton(c: Context, onTap: () -> Unit): TextView = TextView(c).apply {
        text = "←"
        typeface = font(c)
        setTextSize(TypedValue.COMPLEX_UNIT_SP, 20f)
        setTextColor(FG)
        gravity = Gravity.CENTER
        includeFontPadding = false
        contentDescription = c.getString(R.string.back)
        background = secondaryFace(c, 22)
        val side = dp(c, 44)
        layoutParams = LinearLayout.LayoutParams(side, side).apply { marginEnd = dp(c, 14) }
        isClickable = true
        isFocusable = true
        setOnClickListener { onTap() }
    }

    /** A card: CARD face, padded, vertical. */
    fun card(c: Context, pad: Int = 18): LinearLayout = LinearLayout(c).apply {
        orientation = LinearLayout.VERTICAL
        background = face(c, CARD)
        val p = dp(c, pad)
        setPadding(p, p, p, p)
        layoutParams = LinearLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT
        ).apply { bottomMargin = dp(c, 14) }
    }

    fun rule(c: Context): View = View(c).apply {
        setBackgroundColor(LINE)
        layoutParams = LinearLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT, dp(c, 1)
        ).apply { topMargin = dp(c, 12); bottomMargin = dp(c, 12) }
    }

    fun gap(c: Context, h: Int): View = View(c).apply {
        layoutParams = LinearLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT, dp(c, h)
        )
    }

    fun tint(colour: Int): ColorStateList = ColorStateList.valueOf(colour)
}
