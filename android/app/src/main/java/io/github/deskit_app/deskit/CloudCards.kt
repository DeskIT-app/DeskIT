package io.github.deskit_app.deskit

import android.app.Activity
import android.content.Intent
import android.net.Uri
import android.text.InputType
import android.util.TypedValue
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.view.inputmethod.EditorInfo
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.Switch
import android.widget.TextView
import kotlin.concurrent.thread

/**
 * Settings' two cards for the cloud backup (PHONE_LINK_PLAN.md 2b), as he approved
 * them in pictures on 2026-11-11: the switch, "When your PC can't be reached", and
 * "Your cloud keys", the desk's card (keyrow.KeyRow, desk_settings_keys.py) in the
 * phone's own widgets. A row per provider; a saved key is a fixed row of dots (never
 * derived from the value) with Change and Remove; Save and test makes the provider's
 * one small request first. Remove asks in the row, because on the phone it removes
 * the key from the account and so from every PC.
 *
 * A pasted value lives in its field until the press, then in one local for the test
 * and the seal, and the field is emptied. Nothing else here ever holds it.
 */
class CloudCards(private val a: Activity) {

    /** What one row shows. */
    private enum class S { SAVED, NONE, CHANGING, TESTING, ASKING_REMOVE, REMOVING }

    private class Row(var s: S, var note: String = "", var tone: Int = Skin.DIM)

    val root = LinearLayout(a).apply { orientation = LinearLayout.VERTICAL }
    /** The keys card, for Add a key's scroll. */
    var keysCard: View? = null
        private set

    private val rows = LinkedHashMap<Cloud.Provider, Row>()
    private val fields = HashMap<Cloud.Provider, EditText>()
    private var drawn = false

    private fun s(id: Int, vararg args: Any) = a.getString(id, *args)

    private fun match() = LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT,
                                                    ViewGroup.LayoutParams.WRAP_CONTENT)

    private fun below(v: View, dp: Int): View = v.apply {
        layoutParams = (layoutParams as? LinearLayout.LayoutParams ?: match()).also {
            it.topMargin = Skin.dp(a, dp)
        }
    }

    private fun body(text: CharSequence, colour: Int = Skin.DIM, sp: Float = 15f): TextView =
        Skin.text(a, text, sp, colour).apply {
            setLineSpacing(0f, 1.25f)
            layoutParams = match()
        }

    private fun row2(left: View, right: View): LinearLayout = LinearLayout(a).apply {
        orientation = LinearLayout.HORIZONTAL
        isBaselineAligned = false
        layoutParams = match()
        addView(left, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.MATCH_PARENT, 1f)
            .apply { marginEnd = Skin.dp(a, 10) })
        addView(right, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.MATCH_PARENT, 1f))
    }

    /** The provider the backup would use, by name, for a sentence: Groq when there is none. */
    private fun using(): String = (CloudKeys.provider(a) ?: Cloud.Provider.GROQ).label

    /** The words the yes is given to: the one-time screen's, with the provider in them. */
    fun yesWords(): String = s(R.string.backup_once_line, using()) + " " + s(R.string.backup_price, using())

    // ---- reading ----

    /** The rows from what was last read, then the account read again. */
    fun start() {
        for (p in Cloud.Provider.values()) {
            rows.getOrPut(p) { Row(if (CloudKeys.have(a, p.word)) S.SAVED else S.NONE) }
        }
        draw()
        thread(name = "keys-read") {
            try {
                CloudKeys.refresh(a)
            } catch (e: Account.Failed) {
                // what was last read stands
            } catch (e: Sealed.NotNow) {
                // the same
            }
            a.runOnUiThread {
                for ((p, r) in rows) {
                    if (r.s == S.SAVED || r.s == S.NONE) r.s = if (CloudKeys.have(a, p.word)) S.SAVED else S.NONE
                }
                if (!a.isFinishing) draw()
            }
        }
    }

    // ---- drawing ----

    private fun draw() {
        if (drawn) Skin.settle(root)
        drawn = true
        // a value being typed survives a redraw of its own row
        val typed = fields.mapValues { it.value.text.toString() }
        root.removeAllViews()
        fields.clear()
        root.addView(backupCard())
        val card = Skin.card(a).apply {
            addView(Skin.eyebrow(a, s(R.string.keys_title)))
            addView(below(body(s(R.string.keys_line), Skin.DIM, 14f), 6))
            for ((i, p) in Cloud.Provider.values().withIndex()) {
                addView(Skin.rule(a))
                addView(keyRow(p, primary = i == 0 || rows[Cloud.Provider.GROQ]?.s == S.SAVED))
            }
        }
        keysCard = card
        root.addView(card)
        for ((p, text) in typed) fields[p]?.let { if (it.isEnabled) it.setText(text) }
    }

    private fun backupCard(): View = Skin.card(a).apply {
        addView(Skin.eyebrow(a, s(R.string.backup_title)).apply { setPadding(0, 0, 0, Skin.dp(a, 12)) })
        addView(LinearLayout(a).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            layoutParams = match()
            addView(Skin.text(a, s(R.string.backup_switch), 16f, Skin.FG).apply {
                typeface = Skin.fontLabel(a)
                layoutParams = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f)
                    .apply { marginEnd = Skin.dp(a, 12) }
            })
            addView(Switch(a).apply {
                // what the backup does now: on is the switch on and the yes given
                isChecked = Backup.active(a)
                Skin.switchLook(a, this)
                contentDescription = s(R.string.backup_switch)
                setOnCheckedChangeListener { _, on ->
                    Backup.setSwitch(a, on, yesWords())
                    draw()
                }
            })
        })
        addView(below(body(s(R.string.backup_help, using()), Skin.DIM, 14f), 8))
        if (Backup.active(a) && CloudKeys.provider(a) == null) {
            addView(below(body(s(R.string.backup_no_key), Skin.AMBER, 14f), 6))
        }
    }

    private fun field(p: Cloud.Provider, locked: Boolean): EditText = EditText(a).apply {
        setText(if (locked) DOTS else "")
        hint = s(R.string.key_paste, p.label)
        setTextSize(TypedValue.COMPLEX_UNIT_SP, 15f)
        setTextColor(if (locked) Skin.MUTED else Skin.FG)
        setHintTextColor(Skin.FAINT)
        background = Skin.well(a)
        val px = Skin.dp(a, 14)
        val py = Skin.dp(a, 12)
        setPadding(px, py, px, py)
        isSingleLine = true
        // a key is a password: masked, never learned by any keyboard, never suggested
        inputType = if (locked) InputType.TYPE_NULL
                    else InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_PASSWORD
        imeOptions = EditorInfo.IME_FLAG_NO_PERSONALIZED_LEARNING
        // after the type: a password type puts the face back to monospace
        typeface = Skin.font(a)
        isEnabled = !locked
        layoutDirection = View.LAYOUT_DIRECTION_LTR
        textDirection = View.TEXT_DIRECTION_LTR
        contentDescription = s(R.string.key_paste, p.label)
        layoutParams = match()
    }

    private fun keyRow(p: Cloud.Provider, primary: Boolean): View = LinearLayout(a).apply {
        orientation = LinearLayout.VERTICAL
        layoutParams = match()
        val r = rows.getValue(p)
        if (r.s == S.ASKING_REMOVE) {
            addView(Skin.title(a, s(R.string.key_remove_q, p.label), 17f).apply { layoutParams = match() })
            addView(below(body(s(R.string.key_remove_line), Skin.DIM, 14f), 6))
            addView(below(row2(Skin.button(a, s(R.string.key_remove), primary = true) { remove(p) },
                               Skin.button(a, s(R.string.keep_it)) { set(p, S.SAVED) }), 12))
            return@apply
        }
        addView(Skin.text(a, p.label, 16f, Skin.FG).apply { typeface = Skin.fontLabel(a) })
        addView(below(Skin.text(a, s(if (p == Cloud.Provider.GROQ) R.string.groq_why else R.string.gemini_why),
                                13f, Skin.MUTED), 3))
        val locked = r.s == S.SAVED || r.s == S.TESTING || r.s == S.REMOVING
        val f = field(p, locked)
        if (!locked) fields[p] = f
        addView(below(f, 10))
        when (r.s) {
            S.SAVED -> addView(below(row2(Skin.button(a, s(R.string.key_change)) { set(p, S.CHANGING) },
                                          Skin.button(a, s(R.string.key_remove)) { set(p, S.ASKING_REMOVE) }), 10))
            S.NONE -> addView(below(Skin.button(a, s(R.string.save_and_test), primary = primary) { save(p) }, 10))
            S.CHANGING -> addView(below(row2(Skin.button(a, s(R.string.key_save), primary = true) { save(p) },
                                             Skin.button(a, s(R.string.key_cancel)) { set(p, S.SAVED) }), 10))
            else -> Unit
        }
        val note = when {
            r.note.isNotEmpty() -> r.note
            r.s == S.SAVED -> s(R.string.key_saved)
            r.s == S.CHANGING -> s(R.string.key_changing)
            else -> ""
        }
        if (note.isNotEmpty()) addView(below(body(note, if (r.note.isNotEmpty()) r.tone else Skin.DIM, 13f), 2))
        if (r.s == S.NONE) {
            val url = if (p == Cloud.Provider.GROQ) "https://console.groq.com/keys"
                      else "https://aistudio.google.com/apikey"
            addView(Skin.link(a, s(if (p == Cloud.Provider.GROQ) R.string.key_free_groq
                                   else R.string.key_free_gemini)) {
                try {
                    a.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url)))
                } catch (e: Exception) {
                    // no browser: the words say where
                }
            })
        }
    }

    private fun set(p: Cloud.Provider, to: S, note: String = "", tone: Int = Skin.DIM) {
        rows[p] = Row(to, note, tone)
        draw()
    }

    // ---- acting ----

    /** Save and test, or Save: the provider's one small request, then the account. */
    private fun save(p: Cloud.Provider) {
        val field = fields[p] ?: return
        val was = rows.getValue(p).s
        val value = field.text.toString().trim()
        field.setText("")
        if (value.isEmpty()) {
            set(p, was, s(R.string.key_empty), Skin.AMBER)
            return
        }
        if (!Scrub.looksLikeKey(value)) {
            set(p, was, s(R.string.key_not_key, p.label), Skin.RED)
            return
        }
        set(p, S.TESTING, s(R.string.key_checking, p.label))
        val back = if (was == S.CHANGING) S.SAVED else S.NONE
        thread(name = "keys-save") {
            val verdict = Cloud.test(a, p, value)
            val after: Pair<S, Pair<String, Int>> = if (verdict == Cloud.Test.REFUSED) {
                // a key the provider refuses never reaches the account; one saved before stays
                Pair(back, Pair(s(R.string.key_refused, p.label), Skin.RED))
            } else try {
                CloudKeys.save(a, p.word, value)
                if (verdict == Cloud.Test.OK) Pair(S.SAVED, Pair(s(R.string.key_works), Skin.GREEN))
                else Pair(S.SAVED, Pair(s(R.string.key_offline, p.label), Skin.AMBER))
            } catch (e: Account.Failed) {
                Pair(back, Pair(s(R.string.key_not_now, e.message.orEmpty()), Skin.RED))
            } catch (e: Sealed.NotNow) {
                Pair(back, Pair(Sealed.words(a, e), Skin.RED))
            }
            a.runOnUiThread { if (!a.isFinishing) set(p, after.first, after.second.first, after.second.second) }
        }
    }

    /** The question's Remove: `{"v": ""}` into the account, the PCs told. */
    private fun remove(p: Cloud.Provider) {
        set(p, S.REMOVING, s(R.string.key_removing))
        thread(name = "keys-remove") {
            val after: Pair<S, Pair<String, Int>> = try {
                CloudKeys.remove(a, p.word)
                Pair(S.NONE, Pair("", Skin.DIM))
            } catch (e: Account.Failed) {
                Pair(S.SAVED, Pair(s(R.string.key_not_now, e.message.orEmpty()), Skin.RED))
            } catch (e: Sealed.NotNow) {
                Pair(S.SAVED, Pair(Sealed.words(a, e), Skin.RED))
            }
            a.runOnUiThread { if (!a.isFinishing) set(p, after.first, after.second.first, after.second.second) }
        }
    }

    companion object {
        /** keyrow.DOTS: the same row for every key, never derived from the value. */
        const val DOTS = "••••••••••••••••"
    }
}
