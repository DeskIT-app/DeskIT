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
import android.view.MotionEvent
import android.view.View
import android.view.ViewGroup
import android.widget.LinearLayout
import android.widget.TextView
import kotlin.concurrent.thread

/**
 * A keyboard that is one microphone button.
 *
 * This is the only kind of app Android lets put text into someone else's
 * text field, which is the whole point: a floating button or a Quick
 * Settings tile can record just fine, but neither can do anything with the
 * result except leave it on the clipboard. Here the transcript is committed
 * straight into whatever field has the cursor, in any app.
 *
 * The recording itself happens on the phone; the transcription happens on
 * the PC, over Tailscale, on the Hebrew fine-tune that lives there. A phone
 * cannot run that model at a useful speed, and the point of this whole
 * project is that particular model's accuracy.
 */
class DictationIme : InputMethodService() {

    private val recorder = Recorder()
    private val ui = Handler(Looper.getMainLooper())
    private lateinit var button: TextView
    private lateinit var status: TextView
    private var busy = false
    private var holding = false

    private val idleColor = Color.parseColor("#2d6cdf")
    private val recColor = Color.parseColor("#d6392f")
    private val busyColor = Color.parseColor("#4a5262")

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
            setPadding(dp(16), dp(14), dp(16), dp(18))
            layoutParams = ViewGroup.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, dp(230)
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
                ViewGroup.LayoutParams.MATCH_PARENT, dp(120)
            )
        }
        root.addView(button)

        status = TextView(this).apply {
            text = ""
            gravity = Gravity.CENTER
            setTextColor(Color.parseColor("#8b97ad"))
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 13f)
            setPadding(0, dp(10), 0, 0)
        }
        root.addView(status)

        val back = TextView(this).apply {
            text = getString(R.string.back_to_keyboard)
            gravity = Gravity.CENTER
            setTextColor(Color.parseColor("#8b97ad"))
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 14f)
            setPadding(dp(10), dp(12), dp(10), dp(4))
            setOnClickListener { goBack() }
        }
        root.addView(back)

        button.setOnTouchListener { _, e ->
            when (e.action) {
                MotionEvent.ACTION_DOWN -> { press(); true }
                MotionEvent.ACTION_UP, MotionEvent.ACTION_CANCEL -> {
                    release(e.action == MotionEvent.ACTION_CANCEL); true
                }
                else -> false
            }
        }
        return root
    }

    override fun onStartInputView(info: android.view.inputmethod.EditorInfo?, restarting: Boolean) {
        super.onStartInputView(info, restarting)
        if (!hasMic()) {
            say(getString(R.string.needs_permission))
        } else if (Prefs.token(this).isEmpty()) {
            say(getString(R.string.needs_setup))
        } else {
            say("")
        }
    }

    private fun hasMic() = checkSelfPermission(android.Manifest.permission.RECORD_AUDIO) ==
            PackageManager.PERMISSION_GRANTED

    private fun press() {
        if (busy) return
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
        say("")
    }

    private fun release(cancelled: Boolean) {
        if (!holding) return
        holding = false
        tint(idleColor)
        button.text = getString(R.string.hold_and_talk)
        if (cancelled) { recorder.cancel(); return }
        val wav = recorder.stop()
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
                currentInputConnection?.commitText(text, 1)
                say("")
                if (Prefs.switchBack(this)) goBack()
            }
            is Transcriber.Result.Err -> say(result.message)
        }
    }

    /**
     * Back to the everyday keyboard. This one exists to dictate a sentence,
     * not to be the keyboard you live in.
     */
    private fun goBack() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
            if (switchToPreviousInputMethod()) return
        }
        // Older Androids, or nothing to go back to: offer the picker rather
        // than stranding the user on a keyboard with no letters.
        @Suppress("DEPRECATION")
        (getSystemService(INPUT_METHOD_SERVICE)
                as android.view.inputmethod.InputMethodManager)
            .showInputMethodPicker()
    }

    private fun tint(color: Int) {
        (button.background as? GradientDrawable)?.setColor(color)
    }

    private fun say(msg: String) {
        status.text = msg
    }

    override fun onFinishInput() {
        super.onFinishInput()
        if (holding) { holding = false; recorder.cancel() }
    }
}
