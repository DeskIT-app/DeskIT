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
 * so the pictures he judges are these very widgets and not a drawing of them.
 * AccountActivity and the account card on Settings put them on screen; the
 * debug build's ProtoActivity shows them with made-up data.
 *
 * Written for every phone: English and left to right whatever the phone's
 * language (the app is English end to end, and the page sets the direction),
 * the code on one line however narrow the screen and however large the fonts,
 * and a device's name in its own direction, because a name is whatever its
 * owner typed.
 */
class AccountScreens(private val c: Context) {

    /** One device of the account, as the Settings card draws it. */
    class Row(val id: String, val name: String, val kind: String, val seen: String,
              val mine: Boolean, val linked: Boolean)

    /** A device asking to join; no code when two requests claim to be it. */
    class Ask(val id: String, val name: String, val code: String)

    private fun s(id: Int, vararg args: Any): String = c.getString(id, *args)

    private fun match(): LinearLayout.LayoutParams = LinearLayout.LayoutParams(
        ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT)

    private fun title(text: String, sp: Float = 24f): TextView =
        Skin.text(c, text, sp, Skin.FG, heavy = true).apply {
            setLineSpacing(0f, 1.15f)
            layoutParams = match().apply { bottomMargin = Skin.dp(c, 10) }
        }

    private fun body(text: String, colour: Int = Skin.DIM, sp: Float = 15f): TextView =
        Skin.text(c, text, sp, colour).apply {
            setLineSpacing(0f, 1.25f)
            layoutParams = match()
        }

    private fun note(text: String): TextView = body(text, Skin.FAINT, 13f).apply {
        layoutParams = match().apply { topMargin = Skin.dp(c, 12) }
    }

    private fun word(text: String): TextView = body(text, Skin.RED, 14f).apply {
        layoutParams = match().apply { bottomMargin = Skin.dp(c, 12) }
    }

    /** A name somebody typed: any script, read in its own direction. */
    private fun named(text: String, sp: Float, colour: Int, heavy: Boolean = false): TextView =
        Skin.text(c, text, sp, colour, heavy).apply {
            textDirection = View.TEXT_DIRECTION_FIRST_STRONG
            textAlignment = View.TEXT_ALIGNMENT_VIEW_START
        }

    /** Two buttons of one height: a word that wraps on a narrow screen stretches both. */
    private fun row2(left: View, right: View): LinearLayout = LinearLayout(c).apply {
        orientation = LinearLayout.HORIZONTAL
        isBaselineAligned = false
        addView(left, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.MATCH_PARENT, 1f)
            .apply { marginEnd = Skin.dp(c, 10) })
        addView(right, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.MATCH_PARENT, 1f))
    }

    private fun lampLine(colour: Int, text: String, breathing: Boolean): LinearLayout =
        LinearLayout(c).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            layoutParams = match().apply { topMargin = Skin.dp(c, 16) }
            addView(LampView(c).apply {
                this.colour = colour
                halo = true
                breathe(breathing)
                val side = Skin.dp(c, 30)
                layoutParams = LinearLayout.LayoutParams(side, side)
                    .apply { marginEnd = Skin.dp(c, 10) }
            })
            addView(Skin.text(c, text, 15f, Skin.FG))
        }

    /**
     * The code both screens show. One line whatever the screen and the font
     * scale, left to right on a phone that reads right to left (the dash
     * would otherwise move), and read letter by letter by a screen reader.
     */
    fun codeBox(code: String): TextView = TextView(c).apply {
        text = code
        typeface = Skin.fontBold(c)
        setTextColor(Skin.ACCENT_TEXT)
        gravity = Gravity.CENTER
        includeFontPadding = false
        letterSpacing = 0.06f
        maxLines = 1
        textDirection = View.TEXT_DIRECTION_LTR
        layoutDirection = View.LAYOUT_DIRECTION_LTR
        setAutoSizeTextTypeUniformWithConfiguration(14, 34, 1, TypedValue.COMPLEX_UNIT_SP)
        background = Skin.face(c, Skin.PANE, Skin.ACCENT_EDGE, 16)
        val px = Skin.dp(c, 14)
        val py = Skin.dp(c, 18)
        setPadding(px, py, px, py)
        layoutParams = LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, Skin.dp(c, 84))
            .apply { topMargin = Skin.dp(c, 16) }
        contentDescription = code.toList().joinToString(" ")
    }

    // ---- the road in ----

    fun signIn(word: String, onSignIn: () -> Unit): View = Skin.card(c).apply {
        addView(title(s(R.string.sign_in_title)))
        if (word.isNotEmpty()) addView(word(word))
        addView(body(s(R.string.sign_in_line)).apply {
            layoutParams = match().apply { bottomMargin = Skin.dp(c, 18) }
        })
        addView(Skin.button(c, s(R.string.sign_in_google), primary = true) { onSignIn() })
        addView(note(s(R.string.sign_in_note)))
    }

    fun preparing(email: String): View = Skin.card(c).apply {
        addView(title(s(R.string.approve_title)))
        addView(lampLine(Skin.TRANSCRIBING, s(R.string.preparing), true))
        addView(note(s(R.string.signed_in_as, email)))
    }

    fun waiting(code: String, email: String, word: String, onOther: () -> Unit): View =
        Skin.card(c).apply {
            addView(title(s(R.string.approve_title)))
            if (word.isNotEmpty()) addView(word(word))
            addView(body(s(R.string.approve_line)))
            addView(codeBox(code))
            addView(lampLine(Skin.TRANSCRIBING, s(R.string.approve_wait), true))
            addView(note(s(R.string.approve_note)))
            addView(signedInAs(email, onOther))
        }

    fun noLock(email: String, word: String, onOther: () -> Unit): View = Skin.card(c).apply {
        addView(title(s(R.string.no_lock_title)))
        if (word.isNotEmpty()) addView(word(word))
        addView(body(s(R.string.no_lock_line)))
        addView(lampLine(Skin.TRANSCRIBING, s(R.string.approve_wait), true))
        addView(signedInAs(email, onOther))
    }

    fun declined(email: String, onAgain: () -> Unit, onOther: () -> Unit): View =
        Skin.card(c).apply {
            addView(title(s(R.string.declined_title)))
            addView(body(s(R.string.declined_line)).apply {
                layoutParams = match().apply { bottomMargin = Skin.dp(c, 18) }
            })
            addView(Skin.button(c, s(R.string.ask_again), primary = true) { onAgain() })
            addView(signedInAs(email, onOther))
        }

    /** Whose account this is, and the way out if it is the wrong one. */
    private fun signedInAs(email: String, onOther: () -> Unit): View = LinearLayout(c).apply {
        orientation = LinearLayout.VERTICAL
        layoutParams = match().apply { topMargin = Skin.dp(c, 16) }
        addView(Skin.rule(c))
        addView(named(s(R.string.signed_in_as, email), 14f, Skin.DIM))
        addView(Skin.text(c, s(R.string.use_another_account), 14f, Skin.ACCENT_TEXT).apply {
            setPadding(0, Skin.dp(c, 10), 0, Skin.dp(c, 6))
            isClickable = true
            isFocusable = true
            setOnClickListener { onOther() }
        })
    }

    fun ready(pcs: List<String>, onDone: () -> Unit): View = Skin.card(c).apply {
        addView(LampView(c).apply {
            colour = Skin.GREEN
            halo = true
            val side = Skin.dp(c, 64)
            layoutParams = LinearLayout.LayoutParams(side, side)
                .apply { bottomMargin = Skin.dp(c, 12) }
        })
        addView(title(s(R.string.ready_title)))
        addView(body(s(R.string.ready_line)))
        if (pcs.isNotEmpty()) addView(named(s(R.string.ready_pcs, pcs.joinToString(" · ")),
                                            15f, Skin.FG).apply {
            layoutParams = match().apply { topMargin = Skin.dp(c, 10) }
        })
        addView(Skin.gap(c, 18))
        addView(Skin.button(c, s(R.string.done), primary = true) { onDone() })
    }

    /** No answer, or Keystore said no: a sentence and another go. */
    fun trouble(words: String, onAgain: () -> Unit): View = Skin.card(c).apply {
        addView(body(words, Skin.FG).apply {
            layoutParams = match().apply { bottomMargin = Skin.dp(c, 16) }
        })
        addView(Skin.button(c, s(R.string.try_again)) { onAgain() })
    }

    // ---- the lock changed ----

    fun changed(onNotMe: () -> Unit, onMe: () -> Unit): View = Skin.card(c).apply {
        background = Skin.face(c, Skin.CARD, Skin.RED)
        addView(title(s(R.string.changed_title)))
        addView(body(s(R.string.changed_line)).apply {
            layoutParams = match().apply { bottomMargin = Skin.dp(c, 18) }
        })
        addView(row2(Skin.button(c, s(R.string.it_wasnt_me), primary = true) { onNotMe() },
                     Skin.button(c, s(R.string.it_was_me)) { onMe() }))
    }

    fun refused(): View = Skin.card(c).apply {
        background = Skin.face(c, Skin.CARD, Skin.RED)
        addView(title(s(R.string.refused_title)))
        addView(body(s(R.string.refused_line)))
        addView(note(s(R.string.refused_note)))
    }

    // ---- what Settings draws ----

    /** A device asking to join: Home's row on the desk, in the phone's widgets. */
    fun asking(ask: Ask, onApprove: () -> Unit, onNotNow: () -> Unit): View = Skin.card(c).apply {
        background = Skin.face(c, Skin.ACCENT_SOFT, Skin.ACCENT_EDGE)
        if (ask.code.isEmpty()) {
            addView(named(s(R.string.twins_title, ask.name), 18f, Skin.FG, heavy = true))
            addView(body(s(R.string.twins_line, ask.name)).apply {
                layoutParams = match().apply {
                    topMargin = Skin.dp(c, 8)
                    bottomMargin = Skin.dp(c, 16)
                }
            })
            addView(Skin.button(c, s(R.string.not_now)) { onNotNow() })
            return@apply
        }
        addView(named(s(R.string.asking_title, ask.name), 18f, Skin.FG, heavy = true))
        addView(body(s(R.string.asking_line)).apply {
            layoutParams = match().apply { topMargin = Skin.dp(c, 8) }
        })
        addView(codeBox(ask.code))
        addView(note(s(R.string.asking_note)))
        addView(Skin.gap(c, 16))
        addView(row2(Skin.button(c, s(R.string.approve), primary = true) { onApprove() },
                     Skin.button(c, s(R.string.not_now)) { onNotNow() }))
    }

    /** One line of the devices: this phone has no Forget, it has Sign out. */
    fun deviceRow(d: Row, onForget: (() -> Unit)?): View = LinearLayout(c).apply {
        orientation = LinearLayout.HORIZONTAL
        gravity = Gravity.CENTER_VERTICAL
        setPadding(0, Skin.dp(c, 10), 0, Skin.dp(c, 10))
        layoutParams = match()
        val lines = LinearLayout(c).apply {
            orientation = LinearLayout.VERTICAL
            layoutParams = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f)
                .apply { marginEnd = Skin.dp(c, 12) }
        }
        lines.addView(named(d.name, 16f, Skin.FG).apply {
            maxLines = 2
            ellipsize = android.text.TextUtils.TruncateAt.END
        })
        val sub = if (d.mine) s(R.string.this_phone)
                  else if (!d.linked) s(R.string.device_not_linked, d.kind)
                  else s(R.string.device_seen, d.kind, d.seen)
        lines.addView(Skin.text(c, sub, 13f, Skin.FAINT).apply {
            setPadding(0, Skin.dp(c, 3), 0, 0)
        })
        addView(lines)
        if (onForget != null) addView(smallButton(s(R.string.forget), onForget))
    }

    private fun smallButton(text: String, onTap: () -> Unit): TextView =
        Skin.button(c, text) { onTap() }.apply {
            val px = Skin.dp(c, 14)
            val py = Skin.dp(c, 9)
            setPadding(px, py, px, py)
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 13f)
        }

    /** Asked in the row itself, so nothing floats over the page. */
    fun forgetQuestion(name: String, onForget: () -> Unit, onKeep: () -> Unit): View =
        LinearLayout(c).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(0, Skin.dp(c, 10), 0, Skin.dp(c, 10))
            layoutParams = match()
            addView(named(s(R.string.forget_title, name), 16f, Skin.FG, heavy = true))
            addView(body(s(R.string.forget_line), Skin.DIM, 14f).apply {
                layoutParams = match().apply {
                    topMargin = Skin.dp(c, 6)
                    bottomMargin = Skin.dp(c, 12)
                }
            })
            addView(row2(Skin.button(c, s(R.string.forget), primary = true) { onForget() },
                         Skin.button(c, s(R.string.keep_it)) { onKeep() }))
        }

    fun signOutQuestion(recordings: Int, onSignOut: () -> Unit, onStay: () -> Unit): View =
        LinearLayout(c).apply {
            orientation = LinearLayout.VERTICAL
            layoutParams = match()
            addView(title(s(R.string.sign_out_title), 18f))
            addView(body(s(R.string.sign_out_line), Skin.DIM, 14f))
            if (recordings > 0) addView(body(c.resources.getQuantityString(
                R.plurals.sign_out_recordings, recordings, recordings), Skin.RED, 14f).apply {
                layoutParams = match().apply { topMargin = Skin.dp(c, 8) }
            })
            addView(Skin.gap(c, 14))
            addView(row2(Skin.button(c, s(R.string.sign_out), primary = true) { onSignOut() },
                         Skin.button(c, s(R.string.stay_signed_in)) { onStay() }))
        }

    /** The card on Settings: who, the devices, the way out. */
    fun accountCard(email: String, word: String, rows: List<View>, foot: View): LinearLayout =
        Skin.card(c).apply {
            addView(Skin.eyebrow(c, s(R.string.your_account)))
            addView(Skin.gap(c, 10))
            addView(named(email, 17f, Skin.FG, heavy = true))
            if (word.isNotEmpty()) addView(body(word, Skin.RED, 14f).apply {
                layoutParams = match().apply { topMargin = Skin.dp(c, 8) }
            })
            addView(Skin.rule(c))
            addView(Skin.eyebrow(c, s(R.string.your_devices)))
            addView(Skin.gap(c, 4))
            for (r in rows) addView(r)
            addView(Skin.rule(c))
            addView(foot)
        }
}
