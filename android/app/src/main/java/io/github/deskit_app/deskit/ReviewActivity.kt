package io.github.deskit_app.deskit

import android.app.Activity
import android.graphics.Typeface
import android.os.Bundle
import android.text.SpannableStringBuilder
import android.text.Spanned
import android.text.style.ForegroundColorSpan
import android.text.style.StrikethroughSpan
import android.text.style.StyleSpan
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.widget.LinearLayout
import android.widget.TextView
import android.widget.Toast
import kotlin.concurrent.thread

/**
 * One proposal of the second reading, the whole sentence, and two
 * answers.
 *
 * Reached from the notification, or from the home screen's list. Shows
 * what was pasted with the doubted words struck, what the reading thinks
 * was said with the changed words lit, the reason in a few words, and
 * Keep / No. Keep teaches the PC the pair the way the desktop card does;
 * No records the refusal; Back decides nothing and the proposal waits.
 * When several are waiting the next one follows the answer.
 */
class ReviewActivity : Activity() {

    private lateinit var col: LinearLayout
    private var items: List<Transcriber.Proposal> = emptyList()
    private var at = 0

    override fun onCreate(saved: Bundle?) {
        super.onCreate(saved)
        col = Skin.page(this)
        showLoading()
        load(intent.getStringExtra(Notify.EXTRA_ID))
    }

    /** A second notification tapped while this is open: show that one. */
    override fun onNewIntent(intent: android.content.Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        showLoading()
        load(intent.getStringExtra(Notify.EXTRA_ID))
    }

    private fun showLoading() {
        col.removeAllViews()
        col.addView(Skin.header(this, getString(R.string.did_you_mean)) { finish() })
        col.addView(Skin.text(this, getString(R.string.checking), 16f, Skin.DIM))
    }

    private fun load(wanted: String?) {
        thread {
            val got = Transcriber.reviewPending(Prefs.url(this), Prefs.token(this))
            runOnUiThread {
                if (got == null) {
                    showEmpty(getString(R.string.unreachable)); return@runOnUiThread
                }
                items = got
                at = items.indexOfFirst { it.id == wanted }.let { if (it < 0) 0 else it }
                if (items.isEmpty()) showEmpty(getString(R.string.nothing_waiting))
                else show(items[at])
            }
        }
    }

    private fun showEmpty(why: String) {
        Skin.settle(col)
        col.removeAllViews()
        col.addView(Skin.header(this, getString(R.string.did_you_mean)) { finish() })
        col.addView(Skin.text(this, why, 16f, Skin.DIM))
    }

    private fun show(p: Transcriber.Proposal) {
        Skin.settle(col)
        col.removeAllViews()
        col.addView(LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            addView(Skin.header(this@ReviewActivity, getString(R.string.did_you_mean)) { finish() }
                .apply {
                    layoutParams = LinearLayout.LayoutParams(
                        0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f)
                })
            if (items.size > 1) addView(Skin.text(this@ReviewActivity, "${at + 1} / ${items.size}",
                                                  13f, Skin.MUTED))
        })
        val rtl = p.changes.firstOrNull()?.rtl ?: true
        fun sentence(text: CharSequence, sp: Float, colour: Int) =
            Skin.text(this, text, sp, colour).apply {
                textDirection = if (rtl) View.TEXT_DIRECTION_RTL else View.TEXT_DIRECTION_LTR
                layoutParams = LinearLayout.LayoutParams(
                    ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT)
                gravity = if (rtl) Gravity.END else Gravity.START
                setLineSpacing(0f, 1.25f)
            }
        val card = Skin.card(this)
        card.addView(sentence(struck(p), 16f, Skin.MUTED))
        card.addView(Skin.rule(this))
        card.addView(sentence(lit(p), 20f, Skin.FG))
        col.addView(card)
        val row = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            isBaselineAligned = false
        }
        row.addView(Skin.button(this, getString(R.string.no)) { decide(p, "rejected") }.apply {
            layoutParams = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.MATCH_PARENT, 1f)
                .apply { marginEnd = Skin.dp(this@ReviewActivity, 10) }
        })
        row.addView(Skin.button(this, getString(R.string.keep), primary = true) {
            decide(p, "accepted")
        }.apply {
            layoutParams = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.MATCH_PARENT, 1f)
        })
        col.addView(row)
    }

    /** The pasted sentence with each `before` struck through. */
    private fun struck(p: Transcriber.Proposal): CharSequence {
        val sb = SpannableStringBuilder(p.text)
        for (c in p.changes) mark(sb, c.before) { StrikethroughSpan() }
        return sb
    }

    /** The proposed sentence with each `after` in the accent, bold. */
    private fun lit(p: Transcriber.Proposal): CharSequence {
        val sb = SpannableStringBuilder(p.proposed)
        for (c in p.changes) {
            mark(sb, c.after) { ForegroundColorSpan(Skin.ACCENT_TEXT) }
            mark(sb, c.after) { StyleSpan(Typeface.BOLD) }
        }
        return sb
    }

    private fun mark(sb: SpannableStringBuilder, needle: String, span: () -> Any) {
        if (needle.isBlank()) return
        val i = sb.indexOf(needle)
        if (i < 0) return
        sb.setSpan(span(), i, i + needle.length, Spanned.SPAN_EXCLUSIVE_EXCLUSIVE)
    }

    private fun decide(p: Transcriber.Proposal, verdict: String) {
        thread {
            val r = Transcriber.reviewDecide(Prefs.url(this), Prefs.token(this),
                                             p.id, verdict)
            runOnUiThread {
                when (r) {
                    is Transcriber.Result.Ok -> {
                        Notify.dismiss(this, p.id)
                        Toast.makeText(this, getString(
                            if (verdict == "accepted") R.string.learned else R.string.noted),
                            Toast.LENGTH_SHORT).show()
                        items = items.filter { it.id != p.id }
                        if (items.isEmpty()) finish()
                        else { at = at.coerceAtMost(items.size - 1); show(items[at]) }
                    }
                    is Transcriber.Result.Err -> {
                        Toast.makeText(this, r.message, Toast.LENGTH_LONG).show()
                        if (r.message.contains("no pending")) {
                            Notify.dismiss(this, p.id)
                            items = items.filter { it.id != p.id }
                            if (items.isEmpty()) finish()
                            else { at = at.coerceAtMost(items.size - 1); show(items[at]) }
                        }
                    }
                }
            }
        }
    }
}
