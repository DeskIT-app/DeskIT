package io.github.deskit_app.deskit

import android.app.Activity
import android.content.Context
import android.content.res.ColorStateList
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.Drawable
import android.graphics.drawable.GradientDrawable
import android.graphics.drawable.StateListDrawable
import android.os.Build
import android.transition.ChangeBounds
import android.transition.Fade
import android.transition.TransitionManager
import android.transition.TransitionSet
import android.util.TypedValue
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.view.animation.PathInterpolator
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.Switch
import android.widget.TextView

/**
 * B+, on a phone: the desk's look, one vibe across the apps.
 *
 * Every value here is the desk's: `skin\palette.py` for the ladder and the
 * text, `web\src\bplus.css` for the glass, the pills and the type. The surfaces
 * themselves are in Faces.kt. The keyboard's own bar uses the flat pieces at the
 * top of this file and none of the glass, so it stays light and fast.
 *
 * Rubik is one variable font and every weight comes out of that one file
 * (assets/fonts/rubik.ttf, SIL OFL), at the desk's own weights: 400 words, 420
 * titles, 460 labels and buttons, 500 the one strong word. The two files this
 * replaced were the same font twice, under two names.
 *
 * Built in code and not in res/font, on purpose. Android 8 reads a <font> family
 * from resources with no variation at all, so every word on the phone came out
 * at the file's default, Light 300, while Android 14 looked right. Typeface.Builder
 * has honoured the axis from API 26, which is minSdk.
 */
object Skin {

    // ---- the night, palette.py's ladder ----
    val GROUND = Color.parseColor("#080A14")
    val BG = Color.parseColor("#0B0D19")
    val PANE = Color.parseColor("#121527")
    val CARD = Color.parseColor("#1A1E35")
    val CARD_HI = Color.parseColor("#242944")
    val LINE = Color.parseColor("#30365A")
    val LINE_HI = Color.parseColor("#454C78")

    // ---- text ----
    val FG = Color.parseColor("#EFEDF7")
    val DIM = Color.parseColor("#C0C3D8")
    val MUTED = Color.parseColor("#A4A9C2")
    val FAINT = Color.parseColor("#70758E")

    // ---- the one light: iris ----
    val ACCENT = Color.parseColor("#A597FF")
    val ACCENT_HI = Color.parseColor("#B9AEFF")
    val ACCENT_LO = Color.parseColor("#9486EE")
    val ACCENT_SOFT = Color.parseColor("#262650")
    val ACCENT_EDGE = Color.parseColor("#5D5A9E")
    val ACCENT_TEXT = Color.parseColor("#C2B9FF")
    val ACCENT_ON = Color.parseColor("#140F33")

    // ---- what a mark means ----
    val GREEN = Color.parseColor("#5FDBA6")
    val AMBER = Color.parseColor("#FFB84D")
    val RED = Color.parseColor("#FF6E7E")
    val COOL = Color.parseColor("#4DB8FF")

    // ---- glass ----
    val GLASS_CARD = rgba(24, 29, 52, .56f)
    val GLASS_LEAD = rgba(40, 46, 82, .56f)
    val GLASS_SHEET = rgba(30, 35, 62, .94f)
    val WELL = rgba(6, 8, 18, .42f)
    val TRACK = rgba(10, 13, 24, .55f)

    /** The status lamp, the desk's four meanings. */
    val LISTENING = COOL
    val RECORDING = Color.parseColor("#FF5D6E")
    val LOCKED = RECORDING
    val TRANSCRIBING = AMBER
    val PAUSED = Color.parseColor("#8A93A8")

    /** Under a button: room for the lit one's pool of light. */
    const val BUTTON_FOOT = 8

    private val faces = HashMap<Int, Typeface>()

    @Synchronized
    private fun rubik(c: Context, weight: Int, fallback: Typeface): Typeface =
        faces.getOrPut(weight) {
            try {
                Typeface.Builder(c.assets, "fonts/rubik.ttf")
                    .setWeight(weight)
                    .setFontVariationSettings("'wght' $weight")
                    .build() ?: fallback
            } catch (e: Exception) {
                fallback
            }
        }

    /** Words: --w-body, 400. */
    fun font(c: Context): Typeface = rubik(c, 400, Typeface.SANS_SERIF)

    /** Titles: --w-display, 420. */
    fun fontDisplay(c: Context): Typeface = rubik(c, 420, Typeface.SANS_SERIF)

    /** Labels and buttons: --w-label, 460. */
    fun fontLabel(c: Context): Typeface = rubik(c, 460, Typeface.SANS_SERIF)

    /** The one strong word: --w-strong, 500. */
    fun fontBold(c: Context): Typeface = rubik(c, 500, Typeface.DEFAULT_BOLD)

    fun dp(c: Context, v: Int): Int = TypedValue.applyDimension(
        TypedValue.COMPLEX_UNIT_DIP, v.toFloat(), c.resources.displayMetrics
    ).toInt()

    fun dpF(c: Context, v: Float): Float = TypedValue.applyDimension(
        TypedValue.COMPLEX_UNIT_DIP, v, c.resources.displayMetrics
    )

    // ---- the flat pieces: the keyboard, and anything drawn every frame ----

    /** A flat rounded face with a hairline. */
    fun face(c: Context, fill: Int, edge: Int = LINE, radius: Int = 20,
             stroke: Int = 1): GradientDrawable = GradientDrawable().apply {
        shape = GradientDrawable.RECTANGLE
        cornerRadius = dpF(c, radius.toFloat())
        setColor(fill)
        if (stroke > 0) setStroke(dp(c, stroke), edge)
    }

    fun pressable(c: Context, fill: Int, pressed: Int, edge: Int = LINE,
                  radius: Int = 20, stroke: Int = 1): Drawable =
        StateListDrawable().apply {
            addState(intArrayOf(android.R.attr.state_pressed),
                     face(c, pressed, edge, radius, stroke))
            addState(intArrayOf(), face(c, fill, edge, radius, stroke))
        }

    fun primaryFace(c: Context, radius: Int = 20): Drawable =
        pressable(c, ACCENT, ACCENT_LO, ACCENT, radius, 0)

    fun secondaryFace(c: Context, radius: Int = 20): Drawable =
        pressable(c, CARD, CARD_HI, LINE, radius, 1)

    // ---- words ----

    fun text(c: Context, s: CharSequence, sp: Float, colour: Int = FG,
             heavy: Boolean = false): TextView = TextView(c).apply {
        text = s
        typeface = if (heavy) fontBold(c) else font(c)
        setTextSize(TypedValue.COMPLEX_UNIT_SP, sp)
        setTextColor(colour)
        includeFontPadding = false
    }

    /** A title: --w-display, the desk's tightened tracking. */
    fun title(c: Context, s: CharSequence, sp: Float = 24f): TextView = TextView(c).apply {
        text = s
        typeface = fontDisplay(c)
        setTextSize(TypedValue.COMPLEX_UNIT_SP, sp)
        setTextColor(FG)
        includeFontPadding = false
        letterSpacing = -0.018f
    }

    /** The label over a card: not capitals, the desk stopped shouting. */
    fun eyebrow(c: Context, s: String): TextView = TextView(c).apply {
        text = s
        typeface = fontLabel(c)
        setTextSize(TypedValue.COMPLEX_UNIT_SP, 13f)
        setTextColor(MUTED)
        includeFontPadding = false
    }

    // ---- buttons ----

    private fun pills(c: Context, lit: Boolean): Drawable = StateListDrawable().apply {
        addState(intArrayOf(android.R.attr.state_pressed), Pill(c, lit, pressed = true))
        addState(intArrayOf(), Pill(c, lit, pressed = false))
    }

    fun button(c: Context, s: String, primary: Boolean = false,
               onTap: () -> Unit): TextView = TextView(c).apply {
        text = s
        typeface = if (primary) fontBold(c) else fontLabel(c)
        setTextSize(TypedValue.COMPLEX_UNIT_SP, 15f)
        setTextColor(if (primary) ACCENT_ON else FG)
        gravity = Gravity.CENTER
        includeFontPadding = false
        val padX = dp(c, 20)
        val padY = dp(c, 14)
        setPadding(padX, padY, padX, padY + dp(c, BUTTON_FOOT))
        minHeight = dp(c, 48 + BUTTON_FOOT)
        background = pills(c, primary)
        isClickable = true
        isFocusable = true
        setOnClickListener { onTap() }
    }

    /** A button inside a row: the same pill, smaller. */
    fun smallButton(c: Context, s: String, onTap: () -> Unit): TextView =
        button(c, s) { onTap() }.apply {
            val px = dp(c, 16)
            val py = dp(c, 9)
            setPadding(px, py, px, py + dp(c, BUTTON_FOOT))
            minHeight = dp(c, 36 + BUTTON_FOOT)
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 13.5f)
        }

    /** A quiet word that opens something: Details, More, Use another account. */
    fun link(c: Context, s: String, onTap: () -> Unit): TextView = TextView(c).apply {
        text = s
        typeface = fontLabel(c)
        setTextSize(TypedValue.COMPLEX_UNIT_SP, 14f)
        setTextColor(ACCENT_TEXT)
        includeFontPadding = false
        val p = dp(c, 8)
        setPadding(0, p, p, p)
        isClickable = true
        isFocusable = true
        setOnClickListener { onTap() }
    }

    /** The way back, on the page: a round pane with a drawn arrow in its centre. */
    fun backButton(c: Context, onTap: () -> Unit): View = View(c).apply {
        contentDescription = c.getString(R.string.back)
        background = StateListDrawable().apply {
            addState(intArrayOf(android.R.attr.state_pressed), Disc(c, pressed = true))
            addState(intArrayOf(), Disc(c, pressed = false))
        }
        val side = dp(c, 40)
        layoutParams = LinearLayout.LayoutParams(side, side).apply { marginEnd = dp(c, 14) }
        isClickable = true
        isFocusable = true
        setOnClickListener { onTap() }
    }

    // ---- the page ----

    /**
     * What every screen stands on: the sky behind the whole window, the bars
     * see-through over it, a scrolling column. The sky is the window's, so it
     * stays put while the page scrolls and while a page moves in over another.
     */
    fun page(a: Activity): LinearLayout {
        a.window.setBackgroundDrawable(Sky())
        a.window.statusBarColor = Color.TRANSPARENT
        a.window.navigationBarColor = Color.TRANSPARENT
        if (Build.VERSION.SDK_INT >= 29) a.window.isNavigationBarContrastEnforced = false
        @Suppress("DEPRECATION")
        a.window.decorView.systemUiVisibility = View.SYSTEM_UI_FLAG_LAYOUT_STABLE or
            View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN or View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION
        val col = LinearLayout(a).apply {
            orientation = LinearLayout.VERTICAL
            layoutDirection = View.LAYOUT_DIRECTION_LTR
            val p = dp(a, 20)
            setPadding(p, dp(a, 18), p, dp(a, 28))
        }
        a.setContentView(ScrollView(a).apply {
            isVerticalScrollBarEnabled = false
            overScrollMode = View.OVER_SCROLL_NEVER
            fitsSystemWindows = true       // the sky runs under the bars, the page never does
            addView(col, ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT)
        })
        return col
    }

    /** The head of an inner page: the way back and the place's name. */
    fun header(a: Activity, name: String, onBack: () -> Unit): View = LinearLayout(a).apply {
        orientation = LinearLayout.HORIZONTAL
        gravity = Gravity.CENTER_VERTICAL
        setPadding(0, 0, 0, dp(a, 18))
        addView(backButton(a, onBack))
        addView(title(a, name, 28f))
    }

    /** Something changes inside a page: it fades and settles, it does not jump. */
    fun settle(root: ViewGroup) {
        TransitionManager.beginDelayedTransition(root, TransitionSet().apply {
            ordering = TransitionSet.ORDERING_TOGETHER
            addTransition(Fade())
            addTransition(ChangeBounds())
            duration = 220
            interpolator = PathInterpolator(.22f, .61f, .36f, 1f)     // the desk's own ease
        })
    }

    // ---- panes ----

    /** A card: a pane of glass, padded, vertical. */
    fun card(c: Context, pad: Int = 20): LinearLayout = LinearLayout(c).apply {
        orientation = LinearLayout.VERTICAL
        background = Glass(c)
        val p = dp(c, pad)
        setPadding(p, p, p, p)
        layoutParams = LinearLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT
        ).apply { bottomMargin = dp(c, 12) }
    }

    fun rule(c: Context): View = View(c).apply {
        background = FadeRule()
        layoutParams = LinearLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT, dp(c, 1).coerceAtLeast(1)
        ).apply { topMargin = dp(c, 12); bottomMargin = dp(c, 12) }
    }

    fun gap(c: Context, h: Int): View = View(c).apply {
        layoutParams = LinearLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT, dp(c, h)
        )
    }

    fun tint(colour: Int): ColorStateList = ColorStateList.valueOf(colour)

    /** A field to type in: the desk's dark well, no line under it. */
    fun well(c: Context): Drawable = face(c, WELL, rgba(170, 175, 220, .12f), 14)

    /**
     * The desk's switch: no accent. On, a soft lavender-grey track and a white
     * knob; off, a hollow ring and a small grey knob.
     */
    fun switchLook(c: Context, s: Switch) {
        fun track(fill: Int, edge: Int) = GradientDrawable().apply {
            cornerRadius = dpF(c, 12f)
            setColor(fill)
            setStroke(dp(c, 1).coerceAtLeast(1), edge)
            setSize(dp(c, 42), dp(c, 24))
        }
        fun knob(colour: Int, size: Int) = GradientDrawable().apply {
            shape = GradientDrawable.OVAL
            setColor(colour)
            setSize(dp(c, 24), dp(c, 24))
            setStroke(dp(c, (24 - size) / 2), Color.TRANSPARENT)
        }
        val checked = intArrayOf(android.R.attr.state_checked)
        s.trackTintList = null
        s.thumbTintList = null
        s.trackDrawable = StateListDrawable().apply {
            addState(checked, track(Color.parseColor("#8286AD"), Color.parseColor("#8286AD")))
            addState(intArrayOf(), track(Color.parseColor("#141A2A"), Color.parseColor("#7F86A6")))
        }
        s.thumbDrawable = StateListDrawable().apply {
            addState(checked, knob(Color.WHITE, 18))
            addState(intArrayOf(), knob(Color.parseColor("#A2A8C0"), 14))
        }
        s.showText = false
    }
}
