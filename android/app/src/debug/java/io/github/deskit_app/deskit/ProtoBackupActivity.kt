package io.github.deskit_app.deskit

import android.app.Activity
import android.os.Bundle
import android.text.SpannableString
import android.text.Spanned
import android.text.style.ForegroundColorSpan
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.Switch
import android.widget.TextView

/**
 * PROTOTYPE, stage 2b of PHONE_LINK_PLAN.md, for the owner's yes before anything is
 * built: the cloud backup's screens in the real widgets, with made-up data and
 * buttons that do nothing. Debug builds only (src/debug); it reads and writes
 * nothing of the account, holds no key and calls nothing.
 *
 *   adb shell am start -n <package>/.ProtoBackupActivity --es screen keys
 *
 * The words are the proposal, written here and not in strings.xml, because none of
 * them is the product's yet. dev/android/proto_backup_shots.py photographs them.
 */
class ProtoBackupActivity : Activity() {

    private val c get() = this

    override fun onCreate(saved: Bundle?) {
        super.onCreate(saved)
        val col = Skin.page(this)
        when (val screen = intent.getStringExtra("screen") ?: "keys") {
            "keys", "keys_none", "keys_change", "keys_remove" -> settings(col, screen)
            "welcome" -> welcome(col, haveKey = true)
            "welcome_nokey" -> welcome(col, haveKey = false)
            "home_today", "home_cloud", "home_nokey" -> home(col, screen)
        }
    }

    // ---- the words: every one of them a proposal ----

    private object W {
        const val BACKUP_TITLE = "When your PC can't be reached"
        const val BACKUP_SWITCH = "Use the cloud"
        const val BACKUP_LINE = "If your PC can't be reached, your recording goes to Groq with your own key. " +
            "You can turn this off here or in Settings."
        const val BACKUP_PRICE = "Groq hears the recording, and its words are less accurate than your PC's."
        const val BACKUP_SETTINGS_HELP = "Your recording goes to Groq with your own key. Off, it waits " +
            "for your PC."
        const val NO_KEY_YET = "Your account has no cloud key yet, so nothing is sent."
        const val NO_KEY_SETTINGS = "No key yet. Until you add one, it waits for your PC."
        const val ADD_A_KEY = "Add a key"
        const val KEYS_TITLE = "Your cloud keys"
        const val KEYS_LINE = "Kept in your account, locked. Your PCs use the same keys."
        const val GROQ_WHY = "Carries your dictation when your PC can't be reached."
        const val GEMINI_WHY = "Used only when there's no Groq key."
        const val DOTS = "••••••••••••••••"
        const val CHANGE = "Change"
        const val REMOVE = "Remove"
        const val SAVE_AND_TEST = "Save and test"
        const val SAVE = "Save"
        const val CANCEL = "Cancel"
        const val SAVED = "Saved in your account, locked."
        const val WORKS = "✓  Key works. Saved in your account, locked."
        const val CHANGING = "The saved key keeps working until a new one is saved. Cancel keeps it."
        const val REMOVE_Q = "Remove your Groq key?"
        const val REMOVE_LINE = "It goes from your account, so your PCs stop using it too."
        const val KEEP_IT = "Keep it"
        fun paste(label: String) = "Paste your $label key"
        fun free(host: String) = "Get a free key at $host"
        const val HOME_TITLE = "Can't reach the PC"
        const val HOME_TODAY = "Tap to try again."
        const val HOME_CLOUD = "You can still dictate. It goes to Groq with your key."
        const val HOME_NOKEY = "Add a cloud key, and you can dictate from anywhere."
        const val SAID_CLOUD = "from the cloud"
    }

    // ---- small pieces, the app's own ----

    private fun match() = LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT,
                                                    ViewGroup.LayoutParams.WRAP_CONTENT)

    private fun below(v: View, dp: Int): View = v.apply {
        layoutParams = (layoutParams as? LinearLayout.LayoutParams ?: match()).also {
            it.topMargin = Skin.dp(c, dp)
        }
    }

    private fun body(s: CharSequence, colour: Int = Skin.DIM, sp: Float = 15f): TextView =
        Skin.text(c, s, sp, colour).apply {
            setLineSpacing(0f, 1.25f)
            layoutParams = match()
        }

    private fun row2(left: View, right: View): LinearLayout = LinearLayout(c).apply {
        orientation = LinearLayout.HORIZONTAL
        isBaselineAligned = false
        layoutParams = match()
        addView(left, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.MATCH_PARENT, 1f)
            .apply { marginEnd = Skin.dp(c, 10) })
        addView(right, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.MATCH_PARENT, 1f))
    }

    private fun switchRow(label: String, on: Boolean): LinearLayout = LinearLayout(c).apply {
        orientation = LinearLayout.HORIZONTAL
        gravity = Gravity.CENTER_VERTICAL
        layoutParams = match()
        addView(Skin.text(c, label, 16f, Skin.FG).apply {
            typeface = Skin.fontLabel(c)
            layoutParams = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f)
                .apply { marginEnd = Skin.dp(c, 12) }
        })
        addView(Switch(c).apply {
            isChecked = on
            Skin.switchLook(c, this)
        })
    }

    /** The field, as Settings' old road draws one: the dark well. */
    private fun field(value: String, hint: String, locked: Boolean): EditText = EditText(c).apply {
        setText(value)
        this.hint = hint
        typeface = Skin.font(c)
        setTextSize(android.util.TypedValue.COMPLEX_UNIT_SP, 15f)
        setTextColor(if (locked) Skin.MUTED else Skin.FG)
        setHintTextColor(Skin.FAINT)
        background = Skin.well(c)
        val px = Skin.dp(c, 14)
        val py = Skin.dp(c, 12)
        setPadding(px, py, px, py)
        isSingleLine = true
        isEnabled = !locked
        isFocusable = false
        layoutDirection = View.LAYOUT_DIRECTION_LTR
        textDirection = View.TEXT_DIRECTION_LTR
        layoutParams = match()
    }

    // ---- a: Settings, the switch and the keys ----

    private fun backupCard(on: Boolean, noKey: Boolean): View = Skin.card(c).apply {
        addView(Skin.eyebrow(c, W.BACKUP_TITLE).apply { setPadding(0, 0, 0, Skin.dp(c, 12)) })
        addView(switchRow(W.BACKUP_SWITCH, on))
        addView(below(body(W.BACKUP_SETTINGS_HELP, Skin.DIM, 14f), 8))
        if (noKey) addView(below(body(W.NO_KEY_SETTINGS, Skin.AMBER, 14f), 6))
    }

    private enum class K { SAVED, NONE, CHANGING, WORKS, REMOVING }

    private fun keyRow(label: String, why: String, host: String, state: K, primary: Boolean): View =
        LinearLayout(c).apply {
            orientation = LinearLayout.VERTICAL
            layoutParams = match()
            if (state == K.REMOVING) {
                addView(Skin.title(c, W.REMOVE_Q, 17f).apply { layoutParams = match() })
                addView(below(body(W.REMOVE_LINE, Skin.DIM, 14f), 6))
                addView(below(row2(Skin.button(c, W.REMOVE, primary = true) { },
                                   Skin.button(c, W.KEEP_IT) { }), 12))
                return@apply
            }
            addView(Skin.text(c, label, 16f, Skin.FG).apply { typeface = Skin.fontLabel(c) })
            addView(below(Skin.text(c, why, 13f, Skin.MUTED), 3))
            val locked = state == K.SAVED || state == K.WORKS
            addView(below(field(if (locked) W.DOTS else "", W.paste(label), locked), 10))
            when (state) {
                K.SAVED, K.WORKS -> addView(below(row2(Skin.button(c, W.CHANGE) { },
                                                       Skin.button(c, W.REMOVE) { }), 10))
                K.NONE -> addView(below(Skin.button(c, W.SAVE_AND_TEST, primary = primary) { }, 10))
                K.CHANGING -> addView(below(row2(Skin.button(c, W.SAVE, primary = true) { },
                                                 Skin.button(c, W.CANCEL) { }), 10))
                K.REMOVING -> Unit
            }
            when (state) {
                K.SAVED -> addView(below(body(W.SAVED, Skin.DIM, 13f), 2))
                K.WORKS -> addView(below(body(W.WORKS, Skin.GREEN, 13f), 2))
                K.CHANGING -> addView(below(body(W.CHANGING, Skin.DIM, 13f), 2))
                K.NONE -> addView(Skin.link(c, W.free(host)) { })
                K.REMOVING -> Unit
            }
        }

    private fun settings(col: LinearLayout, screen: String) {
        col.addView(Skin.header(this, getString(R.string.settings)) { })
        val (groq, gemini) = when (screen) {
            "keys_none" -> K.NONE to K.NONE
            "keys_change" -> K.CHANGING to K.WORKS
            "keys_remove" -> K.REMOVING to K.SAVED
            else -> K.SAVED to K.NONE
        }
        col.addView(backupCard(on = true, noKey = screen == "keys_none"))
        col.addView(Skin.card(c).apply {
            addView(Skin.eyebrow(c, W.KEYS_TITLE))
            addView(below(body(W.KEYS_LINE, Skin.DIM, 14f), 6))
            addView(Skin.rule(c))
            addView(keyRow("Groq", W.GROQ_WHY, "console.groq.com/keys", groq, primary = true))
            addView(Skin.rule(c))
            addView(keyRow("Gemini", W.GEMINI_WHY, "aistudio.google.com/apikey", gemini,
                           primary = groq != K.NONE))
        })
    }

    // ---- b: seen once, the switch already on ----

    private fun welcome(col: LinearLayout, haveKey: Boolean) {
        col.addView(Skin.gap(c, 24))
        col.addView(Skin.card(c, 22).apply {
            addView(Skin.title(c, W.BACKUP_TITLE, 22f).apply {
                setLineSpacing(0f, 1.15f)
                layoutParams = match()
            })
            addView(below(switchRow(W.BACKUP_SWITCH, true), 18))
            addView(below(body(W.BACKUP_LINE), 12))
            addView(below(body(W.BACKUP_PRICE, Skin.MUTED, 14f), 10))
            if (haveKey) {
                addView(below(Skin.button(c, getString(R.string.done), primary = true) { }, 20))
            } else {
                addView(below(body(W.NO_KEY_YET, Skin.AMBER, 14f), 10))
                addView(Skin.link(c, W.ADD_A_KEY) { })
                addView(below(Skin.button(c, getString(R.string.done), primary = true) { }, 14))
            }
        })
    }

    // ---- e: Home, away from the PC ----

    private fun home(col: LinearLayout, screen: String) {
        val head = LinearLayout(c).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            layoutParams = match().apply { bottomMargin = Skin.dp(c, 18) }
        }
        val mark = SpannableString("DeskIT").apply {
            setSpan(ForegroundColorSpan(Skin.ACCENT_TEXT), 4, 6, Spanned.SPAN_EXCLUSIVE_EXCLUSIVE)
        }
        head.addView(Skin.title(c, mark, 30f).apply {
            layoutParams = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f)
        })
        head.addView(Skin.smallButton(c, getString(R.string.settings)) { })
        col.addView(head)

        val state = Skin.card(c).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
        }
        state.addView(LampView(c).apply {
            layoutParams = LinearLayout.LayoutParams(Skin.dp(c, 44), Skin.dp(c, 44))
            colour = Skin.PAUSED
            halo = false
        })
        val lines = LinearLayout(c).apply {
            orientation = LinearLayout.VERTICAL
            layoutParams = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f)
                .apply { marginStart = Skin.dp(c, 14) }
        }
        lines.addView(Skin.title(c, W.HOME_TITLE, 19f))
        lines.addView(Skin.text(c, when (screen) {
            "home_cloud" -> W.HOME_CLOUD
            "home_nokey" -> W.HOME_NOKEY
            else -> W.HOME_TODAY
        }, 14f, Skin.DIM).apply {
            setPadding(0, Skin.dp(c, 4), 0, 0)
            setLineSpacing(0f, 1.2f)
        })
        if (screen == "home_nokey") {
            lines.addView(below(Skin.smallButton(c, W.ADD_A_KEY) { }.apply {
                layoutParams = LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT,
                                                         ViewGroup.LayoutParams.WRAP_CONTENT)
            }, 10))
        }
        state.addView(lines)
        col.addView(state)

        // What you said, with the one that went through the cloud marked as such.
        col.addView(Skin.card(c).apply {
            addView(LinearLayout(c).apply {
                orientation = LinearLayout.HORIZONTAL
                gravity = Gravity.CENTER_VERTICAL
                addView(Skin.eyebrow(c, getString(R.string.said_title)).apply {
                    layoutParams = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f)
                })
                addView(Skin.link(c, getString(R.string.clear)) { })
            })
            addView(Skin.gap(c, 6))
            val said = if (screen == "home_cloud")
                listOf("14:32 · ${W.SAID_CLOUD}" to "אני בדרך הביתה, אגיע בעוד עשר דקות",
                       "09:05" to "תזכיר לי לקנות חלב ולחם בדרך")
            else listOf("09:05" to "תזכיר לי לקנות חלב ולחם בדרך")
            for ((stamp, words) in said) addView(LinearLayout(c).apply {
                orientation = LinearLayout.VERTICAL
                setPadding(0, Skin.dp(c, 10), 0, Skin.dp(c, 10))
                addView(Skin.text(c, stamp, 12f, Skin.MUTED))
                addView(Skin.text(c, words, 16f, Skin.FG).apply {
                    textDirection = View.TEXT_DIRECTION_ANY_RTL
                    layoutParams = match()
                    setPadding(0, Skin.dp(c, 4), 0, 0)
                    setLineSpacing(0f, 1.2f)
                })
            })
        })
    }
}
