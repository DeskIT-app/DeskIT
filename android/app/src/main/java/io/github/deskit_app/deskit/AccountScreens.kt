package io.github.deskit_app.deskit

import android.content.Context
import android.util.TypedValue
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.widget.LinearLayout
import android.widget.TextView

/**
 * The account's faces, each one a function of what it shows and nothing else,
 * so the pictures he approved on 2026-11-06 are these very widgets and not a
 * drawing of them. AccountActivity and the account card on Settings put them on
 * screen; the debug build's ProtoActivity shows them with made-up data, for the
 * next round of pictures.
 *
 * His rule, 2026-11-06: keep what a person must have to act and drop the rest.
 * A code screen is the code and one short line. A question is the question and
 * its answers. What explains how the lock works sits behind one More link, on
 * the two screens where a person may really want it.
 *
 * Written for every phone: left to right whatever the phone's language (the app
 * is English end to end, and the page sets the direction), the code on one line
 * however narrow the screen and however large the fonts, and a device's name in
 * its own direction, because a name is whatever its owner typed.
 */
class AccountScreens(private val c: Context) {

    /** One device of the account, as the Settings card draws it. */
    class Row(val id: String, val name: String, val isPc: Boolean, val line: String)

    /** A device asking to join; no code when two requests claim to be it. */
    class Ask(val id: String, val name: String, val code: String)

    private fun s(id: Int, vararg args: Any): String = c.getString(id, *args)

    private fun match(): LinearLayout.LayoutParams = LinearLayout.LayoutParams(
        ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT)

    private fun title(text: String, sp: Float = 22f): TextView = Skin.title(c, text, sp).apply {
        setLineSpacing(0f, 1.15f)
        layoutParams = match()
    }

    private fun body(text: String, colour: Int = Skin.DIM, sp: Float = 15f): TextView =
        Skin.text(c, text, sp, colour).apply {
            setLineSpacing(0f, 1.25f)
            layoutParams = match()
        }

    private fun below(view: View, dp: Int): View = view.apply {
        (layoutParams as? LinearLayout.LayoutParams ?: match()).let {
            it.topMargin = Skin.dp(c, dp)
            layoutParams = it
        }
    }

    private fun alert(text: String): TextView = body(text, Skin.RED, 14f)

    /** A name somebody typed: any script, read in its own direction. */
    private fun named(text: String, sp: Float, colour: Int): TextView =
        Skin.text(c, text, sp, colour).apply {
            typeface = Skin.fontLabel(c)
            textDirection = View.TEXT_DIRECTION_FIRST_STRONG
            textAlignment = View.TEXT_ALIGNMENT_VIEW_START
        }

    /** Two buttons of one height: a word that wraps on a narrow screen stretches both. */
    private fun row2(left: View, right: View): LinearLayout = LinearLayout(c).apply {
        orientation = LinearLayout.HORIZONTAL
        isBaselineAligned = false
        layoutParams = match()
        addView(left, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.MATCH_PARENT, 1f)
            .apply { marginEnd = Skin.dp(c, 10) })
        addView(right, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.MATCH_PARENT, 1f))
    }

    private fun lampLine(colour: Int, text: String): LinearLayout = LinearLayout(c).apply {
        orientation = LinearLayout.HORIZONTAL
        gravity = Gravity.CENTER_VERTICAL
        layoutParams = match()
        addView(LampView(c).apply {
            this.colour = colour
            halo = true
            breathe(true)
            val side = Skin.dp(c, 28)
            layoutParams = LinearLayout.LayoutParams(side, side)
                .apply { marginEnd = Skin.dp(c, 8) }
        })
        addView(Skin.text(c, text, 15f, Skin.DIM))
    }

    /** One More link, and what it opens. For the two places a person may want it. */
    private fun more(detail: String): View = LinearLayout(c).apply {
        orientation = LinearLayout.VERTICAL
        layoutParams = match()
        val line = body(detail, Skin.MUTED, 14f).apply { visibility = View.GONE }
        addView(Skin.link(c, s(R.string.more)) { })
        val link = getChildAt(0) as TextView
        link.setOnClickListener {
            (rootView as? ViewGroup)?.let { Skin.settle(it) }
            link.visibility = View.GONE
            line.visibility = View.VISIBLE
        }
        addView(line)
    }

    /**
     * The code both screens show. One line whatever the screen and the font
     * scale, left to right on a phone that reads right to left (the dash
     * would otherwise move), and read letter by letter by a screen reader.
     */
    fun codeBox(code: String): TextView = TextView(c).apply {
        text = code
        typeface = Skin.fontLabel(c)
        setTextColor(Skin.FG)
        gravity = Gravity.CENTER
        includeFontPadding = false
        letterSpacing = 0.05f
        maxLines = 1
        textDirection = View.TEXT_DIRECTION_LTR
        layoutDirection = View.LAYOUT_DIRECTION_LTR
        setAutoSizeTextTypeUniformWithConfiguration(14, 32, 1, TypedValue.COMPLEX_UNIT_SP)
        background = Skin.face(c, Skin.WELL, rgba(170, 175, 220, .12f), 16)
        val px = Skin.dp(c, 14)
        val py = Skin.dp(c, 16)
        setPadding(px, py, px, py)
        layoutParams = LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, Skin.dp(c, 76))
        contentDescription = code.toList().joinToString(" ")
    }

    // ---- the road in ----

    fun signIn(word: String, onSignIn: () -> Unit): View = Skin.card(c).apply {
        addView(title(s(R.string.sign_in_title)))
        if (word.isNotEmpty()) addView(below(alert(word), 8))
        addView(below(body(s(R.string.sign_in_line)), 8))
        addView(below(Skin.button(c, s(R.string.sign_in_google), primary = true) { onSignIn() }, 18))
    }

    fun preparing(): View = Skin.card(c).apply {
        addView(lampLine(Skin.TRANSCRIBING, s(R.string.preparing)))
    }

    /** Whose account this is, and the way out if it is the wrong one. */
    private fun whose(email: String, onOther: () -> Unit): View = LinearLayout(c).apply {
        orientation = LinearLayout.VERTICAL
        layoutParams = match()
        gravity = Gravity.CENTER_HORIZONTAL
        addView(named(email, 13f, Skin.MUTED))
        addView(Skin.link(c, s(R.string.use_another_account)) { onOther() })
    }

    /**
     * The code and one short line. Both sides press, the way Bluetooth pairs:
     * Approve on the PC, Same code here, in either order. The press is this
     * screen's one button, and nothing that arrived is opened until it.
     */
    fun waiting(code: String, email: String, word: String, pressed: Boolean,
                onSame: () -> Unit, onOther: () -> Unit): View = LinearLayout(c).apply {
        orientation = LinearLayout.VERTICAL
        layoutParams = match()
        addView(Skin.card(c).apply {
            if (word.isNotEmpty()) addView(LinearLayout(c).apply {
                orientation = LinearLayout.VERTICAL
                addView(alert(word))
                setPadding(0, 0, 0, Skin.dp(c, 12))
            })
            if (pressed) addView(lampLine(Skin.TRANSCRIBING, s(R.string.approve_on_pc)))
            else addView(title(s(R.string.same_code_q), 20f))
            addView(below(codeBox(code), 14))
            if (!pressed) addView(below(Skin.button(c, s(R.string.same_code), primary = true) {
                onSame()
            }, 14))
        })
        addView(whose(email, onOther))
    }

    fun noLock(email: String, onOther: () -> Unit): View = LinearLayout(c).apply {
        orientation = LinearLayout.VERTICAL
        layoutParams = match()
        addView(Skin.card(c).apply {
            addView(title(s(R.string.no_lock_title)))
            addView(below(lampLine(Skin.TRANSCRIBING, s(R.string.waiting_pc)), 12))
        })
        addView(whose(email, onOther))
    }

    fun declined(email: String, onAgain: () -> Unit, onOther: () -> Unit): View =
        LinearLayout(c).apply {
            orientation = LinearLayout.VERTICAL
            layoutParams = match()
            addView(Skin.card(c).apply {
                addView(title(s(R.string.declined_title)))
                addView(below(Skin.button(c, s(R.string.ask_again), primary = true) { onAgain() }, 18))
            })
            addView(whose(email, onOther))
        }

    fun ready(onDone: () -> Unit): View = Skin.card(c, 22).apply {
        addView(LampView(c).apply {
            colour = Skin.GREEN
            halo = true
            val side = Skin.dp(c, 60)
            layoutParams = LinearLayout.LayoutParams(side, side)
                .apply { bottomMargin = Skin.dp(c, 8) }
        })
        addView(title(s(R.string.ready_title)))
        addView(below(Skin.button(c, s(R.string.done), primary = true) { onDone() }, 18))
    }

    fun trouble(words: String, onAgain: () -> Unit): View = Skin.card(c).apply {
        addView(body(words, Skin.FG))
        addView(below(Skin.button(c, s(R.string.try_again)) { onAgain() }, 16))
    }

    // ---- the lock changed ----

    private fun red(): Glass = Glass(c, rimFoot = rgba(255, 110, 126, .30f))

    fun changed(onNotMe: () -> Unit, onMe: () -> Unit): View = Skin.card(c).apply {
        background = red()
        addView(title(s(R.string.changed_title)))
        addView(below(row2(Skin.button(c, s(R.string.it_wasnt_me), primary = true) { onNotMe() },
                           Skin.button(c, s(R.string.it_was_me)) { onMe() }), 18))
        addView(more(s(R.string.changed_more)))
    }

    fun refused(): View = Skin.card(c).apply {
        background = red()
        addView(title(s(R.string.refused_title)))
        addView(below(body(s(R.string.refused_line)), 8))
    }

    // ---- what Settings draws ----

    /** A device asking to join: Home's row on the desk, cut to the question. */
    fun asking(ask: Ask, onApprove: () -> Unit, onNotNow: () -> Unit): View = Skin.card(c).apply {
        background = Glass(c, Skin.GLASS_LEAD)
        if (ask.code.isEmpty()) {
            addView(title(s(R.string.twins_title, ask.name), 18f))
            addView(below(Skin.button(c, s(R.string.not_now)) { onNotNow() }, 14))
            return@apply
        }
        addView(title(s(R.string.asking_title, ask.name), 18f))
        addView(below(codeBox(ask.code), 14))
        addView(below(row2(Skin.button(c, s(R.string.approve), primary = true) { onApprove() },
                           Skin.button(c, s(R.string.not_now)) { onNotNow() }), 14))
        addView(more(s(R.string.asking_more)))
    }

    /** One line of the devices: this phone has no Forget, it has Sign out. */
    fun deviceRow(d: Row, onForget: (() -> Unit)?): View = LinearLayout(c).apply {
        orientation = LinearLayout.HORIZONTAL
        gravity = Gravity.CENTER_VERTICAL
        setPadding(0, Skin.dp(c, 8), 0, Skin.dp(c, 8))
        layoutParams = match()
        addView(View(c).apply {
            background = DeviceMark(c, phone = !d.isPc)
            val side = Skin.dp(c, 34)
            layoutParams = LinearLayout.LayoutParams(side, side)
                .apply { marginEnd = Skin.dp(c, 12) }
        })
        val lines = LinearLayout(c).apply {
            orientation = LinearLayout.VERTICAL
            layoutParams = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f)
                .apply { marginEnd = Skin.dp(c, 10) }
        }
        lines.addView(named(d.name, 15f, Skin.FG).apply {
            maxLines = 2
            ellipsize = android.text.TextUtils.TruncateAt.END
        })
        lines.addView(Skin.text(c, d.line, 13f, Skin.MUTED).apply {
            setPadding(0, Skin.dp(c, 3), 0, 0)
        })
        addView(lines)
        if (onForget != null) addView(Skin.smallButton(c, s(R.string.forget), onForget))
    }

    /** Asked in the row itself, so nothing floats over the page. */
    fun forgetQuestion(name: String, onForget: () -> Unit, onKeep: () -> Unit): View =
        LinearLayout(c).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(0, Skin.dp(c, 8), 0, Skin.dp(c, 8))
            layoutParams = match()
            addView(named(s(R.string.forget_title, name), 15f, Skin.FG))
            addView(below(row2(Skin.button(c, s(R.string.forget), primary = true) { onForget() },
                               Skin.button(c, s(R.string.keep_it)) { onKeep() }), 12))
        }

    fun signOutQuestion(recordings: Int, onSignOut: () -> Unit, onStay: () -> Unit): View =
        LinearLayout(c).apply {
            orientation = LinearLayout.VERTICAL
            layoutParams = match()
            addView(title(s(R.string.sign_out_title), 17f))
            if (recordings > 0) addView(below(alert(c.resources.getQuantityString(
                R.plurals.sign_out_recordings, recordings, recordings)), 6))
            addView(below(row2(Skin.button(c, s(R.string.sign_out), primary = true) { onSignOut() },
                               Skin.button(c, s(R.string.stay_signed_in)) { onStay() }), 12))
        }

    /** The card on Settings: who, the devices, the way out. */
    fun accountCard(email: String, word: String, rows: List<View>, foot: View): LinearLayout =
        Skin.card(c).apply {
            addView(named(email, 15f, Skin.FG))
            if (word.isNotEmpty()) addView(below(alert(word), 6))
            addView(Skin.rule(c))
            for (r in rows) addView(r)
            addView(Skin.rule(c))
            addView(foot)
        }
}
