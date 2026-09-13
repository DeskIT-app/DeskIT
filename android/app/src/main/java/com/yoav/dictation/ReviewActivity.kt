package com.yoav.dictation

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
import android.widget.ScrollView
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
        col = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            layoutDirection = View.LAYOUT_DIRECTION_LTR
            val p = Skin.dp(this@ReviewActivity, 22)
            setPadding(p, Skin.dp(this@ReviewActivity, 28), p, p)
        }
        setContentView(ScrollView(this).apply {
            setBackgroundColor(Skin.BG)
            addView(col, ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT)
        })
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
        col.addView(Skin.eyebrow(this, getString(R.string.second_reading)))
        col.addView(Skin.gap(this, 16))
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
        col.removeAllViews()
        col.addView(Skin.eyebrow(this, getString(R.string.second_reading)))
        col.addView(Skin.gap(this, 16))
        col.addView(Skin.text(this, why, 17f, Skin.DIM))
        col.addView(Skin.gap(this, 24))
        col.addView(Skin.button(this, getString(R.string.close)) { finish() })
    }

    private fun show(p: Transcriber.Proposal) {
        col.removeAllViews()
        val head = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
        }
        head.addView(Skin.eyebrow(this, getString(R.string.second_reading)).apply {
            layoutParams = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f)
        })
        if (items.size > 1) head.addView(
            Skin.text(this, "${at + 1} / ${items.size}", 12f, Skin.FAINT))
        col.addView(head)
        col.addView(Skin.gap(this, 6))
        col.addView(Skin.text(this, getString(
            if (p.fromPhone) R.string.from_the_phone else R.string.from_the_desk,
            p.whenText.substringAfter(' ').take(5)), 13f, Skin.FAINT))
        col.addView(Skin.gap(this, 18))

        val rtl = p.changes.firstOrNull()?.rtl ?: true

        // What was pasted, the doubted words struck.
        val card = Skin.card(this)
        card.addView(Skin.text(this, getString(R.string.you_said), 11f, Skin.FAINT,
                               heavy = true).apply { letterSpacing = 0.12f })
        card.addView(Skin.gap(this, 8))
        card.addView(Skin.text(this, struck(p), 17f, Skin.DIM).apply {
            textDirection = if (rtl) View.TEXT_DIRECTION_RTL else View.TEXT_DIRECTION_LTR
            gravity = if (rtl) Gravity.END else Gravity.START
            setLineSpacing(0f, 1.25f)
        })
        card.addView(Skin.rule(this))
        card.addView(Skin.text(this, getString(R.string.did_you_mean), 11f, Skin.FAINT,
                               heavy = true).apply { letterSpacing = 0.12f })
        card.addView(Skin.gap(this, 8))
        card.addView(Skin.text(this, lit(p), 20f, Skin.FG).apply {
            textDirection = if (rtl) View.TEXT_DIRECTION_RTL else View.TEXT_DIRECTION_LTR
            gravity = if (rtl) Gravity.END else Gravity.START
            setLineSpacing(0f, 1.25f)
        })
        val why = p.changes.mapNotNull { it.why.ifBlank { null } }.distinct()
        if (why.isNotEmpty()) {
            card.addView(Skin.gap(this, 12))
            card.addView(Skin.text(this, why.joinToString(" · "), 14f, Skin.DIM).apply {
                textDirection = View.TEXT_DIRECTION_ANY_RTL
                gravity = if (rtl) Gravity.END else Gravity.START
            })
        }
        col.addView(card)

        col.addView(Skin.gap(this, 6))
        val row = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL }
        row.addView(Skin.button(this, getString(R.string.no)) { decide(p, "rejected") }.apply {
            layoutParams = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f)
                .apply { marginEnd = Skin.dp(this@ReviewActivity, 10) }
        })
        row.addView(Skin.button(this, getString(R.string.keep), primary = true) {
            decide(p, "accepted")
        }.apply {
            layoutParams = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f)
        })
        col.addView(row)
        col.addView(Skin.gap(this, 14))
        col.addView(Skin.text(this, getString(R.string.later_hint), 13f, Skin.FAINT).apply {
            gravity = Gravity.CENTER
        })
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
