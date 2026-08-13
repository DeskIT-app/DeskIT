package com.yoav.dictation

import android.content.pm.PackageManager
import android.graphics.Color
import android.graphics.drawable.GradientDrawable
import android.inputmethodservice.InputMethodService
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.util.TypedValue
import android.view.Gravity
import android.view.KeyEvent
import android.view.MotionEvent
import android.view.View
import android.view.ViewGroup
import android.view.inputmethod.ExtractedTextRequest
import android.widget.LinearLayout
import android.widget.TextView
import kotlin.concurrent.thread

/**
 * A keyboard that is one microphone button.
 *
 * This is the only kind of app Android lets put text into someone else's
 * text field, which is the whole point: a floating button or a Quick
 * Settings tile can record just fine, but neither can do anything with the
 * result except leave it on the clipboard. Here the transcript is
 * committed straight into whatever field has the cursor, in any app.
 *
 * Recording happens on the phone; transcription happens on the PC, over
 * Tailscale, on the Hebrew fine-tune that lives there. A phone cannot run
 * that model at a useful speed, and its accuracy is the point of the whole
 * project.
 *
 * The face is in English deliberately. It sits directly under a Hebrew
 * text field, and two scripts in one glance is harder to read, not easier.
 */
class DictationIme : InputMethodService() {

    private val recorder = Recorder()
    private val ui = Handler(Looper.getMainLooper())
    private lateinit var button: TextView
    private lateinit var status: TextView
    private var busy = false
    private var holding = false
    private var locked = false
    private var downY = 0f

    private val idleColor = Color.parseColor("#2d6cdf")
    private val recColor = Color.parseColor("#d6392f")
    private val lockColor = Color.parseColor("#b02a21")
    private val busyColor = Color.parseColor("#4a5262")

    /** Drag distance that means "lock it on", in pixels. */
    private val lockDistance by lazy {
        TypedValue.applyDimension(
            TypedValue.COMPLEX_UNIT_DIP, 48f, resources.displayMetrics
        )
    }

    override fun onCreateInputView(): View {
        val dp = { v: Int ->
            TypedValue.applyDimension(
                TypedValue.COMPLEX_UNIT_DIP, v.toFloat(), resources.displayMetrics
            ).toInt()
        }

        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            gravity = Gravity.CENTER
            setBackgroundColor(Color.parseColor("#10131a"))
            setPadding(dp(14), dp(12), dp(14), dp(14))
            layoutParams = ViewGroup.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, dp(250)
            )
        }

        button = TextView(this).apply {
            text = getString(R.string.hold_and_talk)
            gravity = Gravity.CENTER
            setTextColor(Color.WHITE)
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 17f)
            background = GradientDrawable().apply {
                shape = GradientDrawable.RECTANGLE
                cornerRadius = dp(20).toFloat()
                setColor(idleColor)
            }
            layoutParams = LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, dp(124)
            )
        }
        root.addView(button)

        status = TextView(this).apply {
            gravity = Gravity.CENTER
            setTextColor(Color.parseColor("#8b97ad"))
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 13f)
            setPadding(0, dp(8), 0, dp(4))
        }
        root.addView(status)

        val row = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER
            layoutParams = LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT
            )
        }
        row.addView(backspaceKey(dp))
        row.addView(secondaryKey(R.string.translate_btn, dp) { translateField() })
        row.addView(secondaryKey(R.string.back_to_keyboard, dp) { goBack() })
        root.addView(row)

        button.setOnTouchListener { _, e ->
            when (e.action) {
                MotionEvent.ACTION_DOWN -> { downY = e.rawY; press(); true }
                MotionEvent.ACTION_MOVE -> { maybeLock(e.rawY); true }
                MotionEvent.ACTION_UP, MotionEvent.ACTION_CANCEL -> {
                    // Locked recordings survive the finger leaving; the
                    // next tap is what ends them.
                    if (!locked) release(e.action == MotionEvent.ACTION_CANCEL)
                    true
                }
                else -> false
            }
        }
        return root
    }

    /**
     * Backspace with hold-to-repeat: fixing one wrong letter must not mean
     * switching keyboards. Sent as a DEL key event rather than
     * deleteSurroundingText(1, 0), because the latter counts UTF-16 units
     * and would cut an emoji in half; the key event lets the editor do its
     * own grapheme-aware delete, and it clears a selection too.
     */
    private fun backspaceKey(dp: (Int) -> Int): TextView =
        TextView(this).apply {
            text = "⌫"
            gravity = Gravity.CENTER
            setTextColor(Color.parseColor("#c6cfdd"))
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 19f)
            background = GradientDrawable().apply {
                shape = GradientDrawable.RECTANGLE
                cornerRadius = dp(12).toFloat()
                setColor(Color.parseColor("#1d2330"))
            }
            layoutParams = LinearLayout.LayoutParams(0, dp(48), 1f).apply {
                marginStart = dp(4); marginEnd = dp(4)
            }
            setOnTouchListener { _, e ->
                when (e.action) {
                    MotionEvent.ACTION_DOWN -> {
                        deleteOnce()
                        ui.postDelayed(deleteRepeat, 350)
                        true
                    }
                    MotionEvent.ACTION_UP, MotionEvent.ACTION_CANCEL -> {
                        ui.removeCallbacks(deleteRepeat)
                        true
                    }
                    else -> false
                }
            }
        }

    private val deleteRepeat = object : Runnable {
        override fun run() {
            deleteOnce()
            ui.postDelayed(this, 50)
        }
    }

    private fun deleteOnce() {
        sendDownUpKeyEvents(KeyEvent.KEYCODE_DEL)
    }

    private fun secondaryKey(res: Int, dp: (Int) -> Int, onTap: () -> Unit) =
        TextView(this).apply {
            text = getString(res)
            gravity = Gravity.CENTER
            setTextColor(Color.parseColor("#c6cfdd"))
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 15f)
            background = GradientDrawable().apply {
                shape = GradientDrawable.RECTANGLE
                cornerRadius = dp(12).toFloat()
                setColor(Color.parseColor("#1d2330"))
            }
            layoutParams = LinearLayout.LayoutParams(0, dp(48), 1f).apply {
                marginStart = dp(4); marginEnd = dp(4)
            }
            setOnClickListener { onTap() }
        }

    override fun onStartInputView(
        info: android.view.inputmethod.EditorInfo?, restarting: Boolean
    ) {
        super.onStartInputView(info, restarting)
        say(
            when {
                !hasMic() -> getString(R.string.needs_permission)
                Prefs.token(this).isEmpty() -> getString(R.string.needs_setup)
                else -> getString(R.string.slide_to_lock)
            }
        )
    }

    private fun hasMic() =
        checkSelfPermission(android.Manifest.permission.RECORD_AUDIO) ==
                PackageManager.PERMISSION_GRANTED

    // ---- recording ----

    private fun press() {
        if (busy) return
        if (locked) { finishLocked(); return }   // tap while locked = stop
        if (!hasMic()) { say(getString(R.string.needs_permission)); return }
        if (Prefs.token(this).isEmpty()) { say(getString(R.string.needs_setup)); return }
        try {
            recorder.start()
        } catch (e: Exception) {
            say(e.message ?: "microphone error"); return
        }
        holding = true
        tint(recColor)
        button.text = getString(R.string.recording)
        say(getString(R.string.slide_to_lock))
    }

    /**
     * Slide up to keep recording after letting go — the same escape hatch
     * the desktop has on the left-arrow key. Holding a button is fine for
     * a sentence and miserable for a paragraph.
     */
    private fun maybeLock(y: Float) {
        if (!holding || locked) return
        if (downY - y >= lockDistance) {
            locked = true
            tint(lockColor)
            button.text = getString(R.string.locked)
            say("")
        }
    }

    private fun finishLocked() {
        locked = false
        holding = false
        deliverRecording()
    }

    private fun release(cancelled: Boolean) {
        if (!holding) return
        holding = false
        if (cancelled) {
            recorder.cancel()
            reset()
            return
        }
        deliverRecording()
    }

    private fun deliverRecording() {
        val wav = recorder.stop()
        reset()
        if (wav == null) { say(getString(R.string.too_short)); return }
        busy = true
        tint(busyColor)
        say(getString(R.string.transcribing))
        val url = Prefs.url(this)
        val token = Prefs.token(this)
        thread {
            val result = Transcriber.send(url, token, wav)
            ui.post { deliver(result) }
        }
    }

    private fun deliver(result: Transcriber.Result) {
        busy = false
        tint(idleColor)
        when (result) {
            is Transcriber.Result.Ok -> {
                val text = result.text.trim()
                if (text.isEmpty()) { say(getString(R.string.no_speech)); return }
                // The whole reason this is a keyboard and not a floating
                // button: straight into the field, no clipboard involved.
                // The glue space matters now that the keyboard stays put:
                // two dictations in a row would otherwise weld into
                // "משפטראשוןמשפטשני".
                val ic = currentInputConnection
                val before = ic?.getTextBeforeCursor(1, 0)
                val glue = if (before.isNullOrEmpty()
                    || before.last().isWhitespace()) "" else " "
                ic?.commitText(glue + text, 1)
                // A decoder loop means words were LOST, not garbled — say
                // so now, not after the gap is discovered in reading.
                say(result.warning ?: "")
                if (Prefs.switchBack(this)) goBack()
            }
            is Transcriber.Result.Err -> say(result.message)
        }
    }

    // ---- translate what is already in the field ----

    /**
     * The phone-side twin of the desktop's F9 key, selection rules
     * included: a selection translates just the selection, no selection
     * translates the whole field. Reads through the same InputConnection
     * it writes with, so nothing touches the clipboard.
     */
    private fun translateField() {
        if (busy) return
        val ic = currentInputConnection ?: return
        val selected = ic.getSelectedText(0)?.toString().orEmpty()
        val wholeField = selected.isBlank()
        val existing = if (wholeField)
            ic.getExtractedText(ExtractedTextRequest(), 0)
                ?.text?.toString().orEmpty()
        else selected
        if (existing.isBlank()) {
            say(getString(R.string.nothing_to_translate)); return
        }
        busy = true
        tint(busyColor)
        say(getString(R.string.translating))
        val url = Prefs.url(this)
        val token = Prefs.token(this)
        thread {
            val result = Transcriber.translate(url, token, existing)
            ui.post {
                busy = false
                tint(idleColor)
                when (result) {
                    is Transcriber.Result.Ok -> {
                        val out = result.text.trim()
                        if (out.isEmpty()) { say(getString(R.string.no_speech)); return@post }
                        // Replace, not append. commitText overwrites the
                        // current selection — for the whole-field case we
                        // select everything first; for a user selection it
                        // is already exactly the range to replace.
                        currentInputConnection?.let { conn ->
                            if (wholeField) {
                                conn.performContextMenuAction(
                                    android.R.id.selectAll)
                            }
                            conn.commitText(out, 1)
                        }
                        say("")
                    }
                    is Transcriber.Result.Err -> say(result.message)
                }
            }
        }
    }

    // ---- plumbing ----

    /**
     * Back to the everyday keyboard. This one exists to dictate a
     * sentence, not to be the keyboard you live in.
     */
    private fun goBack() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
            if (switchToPreviousInputMethod()) return
        }
        @Suppress("DEPRECATION")
        (getSystemService(INPUT_METHOD_SERVICE)
                as android.view.inputmethod.InputMethodManager)
            .showInputMethodPicker()
    }

    private fun reset() {
        locked = false
        tint(idleColor)
        button.text = getString(R.string.hold_and_talk)
    }

    private fun tint(color: Int) {
        (button.background as? GradientDrawable)?.setColor(color)
    }

    private fun say(msg: String) {
        status.text = msg
    }

    override fun onFinishInput() {
        super.onFinishInput()
        ui.removeCallbacks(deleteRepeat)   // field gone mid-hold: stop deleting
        if (holding || locked) {
            holding = false; locked = false
            recorder.cancel()
        }
    }
}
