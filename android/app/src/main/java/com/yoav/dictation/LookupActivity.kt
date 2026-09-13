package com.yoav.dictation

import android.app.Activity
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Intent
import android.os.Bundle
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.widget.LinearLayout
import android.widget.TextView
import android.widget.Toast
import kotlin.concurrent.thread

/**
 * The desktop's F8 key, on the phone: select text in ANY app — a page in
 * the browser, a message, a field you cannot edit — pick "DeskIT" from
 * the selection menu, and a small box shows the Hebrew of what you
 * selected, or the English if it was Hebrew already.
 *
 * It is Android's PROCESS_TEXT door, which is why it works with no
 * keyboard open and in apps that have no text field at all. It changes
 * nothing: the box has Copy and Close, and the selection is untouched
 * whatever happens here — the PC is asked, its answer is shown, that is
 * the whole transaction.
 */
class LookupActivity : Activity() {

    private lateinit var answer: TextView
    private var got: String? = null

    override fun onCreate(saved: Bundle?) {
        super.onCreate(saved)
        val selected = intent.getCharSequenceExtra(Intent.EXTRA_PROCESS_TEXT)
            ?.toString()?.trim().orEmpty()

        val col = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            layoutDirection = View.LAYOUT_DIRECTION_LTR
            background = Skin.face(this@LookupActivity, Skin.CARD, Skin.LINE_HI, 24)
            val p = Skin.dp(this@LookupActivity, 22)
            setPadding(p, p, p, p)
        }
        col.addView(Skin.eyebrow(this, getString(R.string.lookup_title)))
        col.addView(Skin.gap(this, 10))
        col.addView(Skin.text(this, selected, 14f, Skin.DIM).apply {
            maxLines = 3
            ellipsize = android.text.TextUtils.TruncateAt.END
            textDirection = View.TEXT_DIRECTION_ANY_RTL
        })
        col.addView(Skin.rule(this))
        answer = Skin.text(this, getString(R.string.looking_up), 18f, Skin.FG).apply {
            setLineSpacing(0f, 1.25f)
            textDirection = View.TEXT_DIRECTION_ANY_RTL
            // A paragraph scrolls inside the box; the box never grows past
            // the screen.
            maxLines = 14
            movementMethod = android.text.method.ScrollingMovementMethod()
        }
        col.addView(answer)
        col.addView(Skin.gap(this, 18))
        val row = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL }
        row.addView(Skin.button(this, getString(R.string.close)) { finish() }.apply {
            layoutParams = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f)
                .apply { marginEnd = Skin.dp(this@LookupActivity, 10) }
        })
        row.addView(Skin.button(this, getString(R.string.copy), primary = true) {
            val text = got ?: return@button
            (getSystemService(CLIPBOARD_SERVICE) as ClipboardManager)
                .setPrimaryClip(ClipData.newPlainText("DeskIT", text))
            Toast.makeText(this, getString(R.string.copied), Toast.LENGTH_SHORT).show()
            finish()
        }.apply {
            layoutParams = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f)
        })
        col.addView(row)

        setContentView(col, ViewGroup.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT))
        window.setLayout(ViewGroup.LayoutParams.MATCH_PARENT,
                         ViewGroup.LayoutParams.WRAP_CONTENT)
        window.setGravity(Gravity.BOTTOM)
        window.setBackgroundDrawableResource(android.R.color.transparent)

        if (selected.isEmpty()) { say(getString(R.string.nothing_selected), Skin.DIM); return }
        if (Prefs.token(this).isEmpty()) { say(getString(R.string.needs_setup), Skin.RED); return }
        thread {
            val r = Transcriber.lookup(Prefs.url(this), Prefs.token(this), selected)
            runOnUiThread {
                when (r) {
                    is Transcriber.Result.Ok -> {
                        got = r.text
                        answer.textDirection =
                            if (r.rtl) View.TEXT_DIRECTION_RTL else View.TEXT_DIRECTION_LTR
                        say(r.text, Skin.FG)
                    }
                    is Transcriber.Result.Err -> say(r.message, Skin.RED)
                }
            }
        }
    }

    private fun say(s: String, colour: Int) {
        answer.text = s
        answer.setTextColor(colour)
    }
}
