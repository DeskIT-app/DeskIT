package io.github.deskit_app.deskit

import android.content.Context
import android.graphics.drawable.GradientDrawable
import android.os.Handler
import android.os.SystemClock
import android.util.Log
import android.util.TypedValue
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.TextView
import java.io.ByteArrayOutputStream
import java.util.Locale

/**
 * PROTOTYPE, phase 1 of "keep the recording when the keyboard closes", for the owner's
 * yes. Debug builds only, and nothing of it is the keyboard's yet: no hide keeps a
 * thing. It draws the proposed row on the RUNNING keyboard's own views, with the
 * keyboard's own pieces (its key face, its round X, its lamp), and for Continue and Send
 * it runs the keyboard's own code: the real recorder locked, the real road to the PC.
 * The words are the proposal and live here, not in strings.xml.
 *
 *   --es ime proto:paused:A|B:<seconds>[:<older waiting>]
 *       A: the row grows a third key, Continue, beside Send and the X; the mic says Paused.
 *       B: the mic IS Continue; the row is the waiting row's shape: words, Send, the X.
 *   --es ime proto:continue:<seconds>   the real recorder, locked, the clock from <seconds>
 *   --es ime proto:send:<seconds>       a recording that long, down the keyboard's real road
 *   --es ime proto:measure              what the line and its keys fit, for the report
 */
object ProtoKeep {
    private const val TAG = "proto-continue"

    private fun field(name: String) =
        DictationIme::class.java.getDeclaredField(name).apply { isAccessible = true }

    private fun <T> get(k: DictationIme, name: String): T {
        @Suppress("UNCHECKED_CAST")
        return field(name).get(k) as T
    }

    private fun call(k: DictationIme, method: String, vararg args: Any) {
        val types = args.map {
            when (it) {
                is Int -> Int::class.javaPrimitiveType!!
                is Boolean -> Boolean::class.javaPrimitiveType!!
                else -> it.javaClass
            }
        }
        DictationIme::class.java.getDeclaredMethod(method, *types.toTypedArray())
            .apply { isAccessible = true }.invoke(k, *args)
    }

    private fun dp(c: Context, v: Float): Int =
        TypedValue.applyDimension(TypedValue.COMPLEX_UNIT_DIP, v, c.resources.displayMetrics).toInt()

    private fun clock(s: Int) = String.format(Locale.US, "%d:%02d", s / 60, s % 60)

    fun draw(c: Context, k: DictationIme, what: String) {
        val parts = what.split(':')
        when (parts[0]) {
            "paused" -> paused(c, k, parts[1], parts.getOrNull(2)?.toInt() ?: 42,
                               parts.getOrNull(3)?.toInt() ?: 0, parts.getOrNull(4) == "fit")
            "continue" -> resume(k, parts.getOrNull(1)?.toInt() ?: 42)
            "send" -> send(c, k, parts.getOrNull(1)?.toInt() ?: 42)
            "measure" -> measure(c, k)
        }
        Log.i("DeskIT", "probe: proto ${parts[0]}")
    }

    /** The extra key arrangement A puts on the line, taken off again for anything else. */
    private fun dropContinueKey(k: DictationIme) {
        val status = get<TextView>(k, "status")
        val row = status.parent as LinearLayout
        row.findViewWithTag<View>(TAG)?.let { row.removeView(it) }
    }

    /**
     * The mic's word made smaller until it fits, never below 60 % of its size, instead of
     * cut with an ellipsis: on a 320 dp phone at the largest text the cut took the clock.
     */
    private fun fit(c: Context, k: DictationIme) {
        val button = get<TextView>(k, "button")
        val pill = get<FrameLayout>(k, "pill")
        val lamp = get<LampView>(k, "lamp")
        val room = pill.width - pill.paddingLeft - pill.paddingRight - lamp.width - dp(c, 14f) - dp(c, 4f)
        val base = button.textSize
        val wants = button.paint.measureText(button.text.toString())
        if (room > 0 && wants > room) {
            button.setTextSize(TypedValue.COMPLEX_UNIT_PX, maxOf(base * room / wants, base * 0.6f))
        }
    }

    private fun paused(c: Context, k: DictationIme, arrangement: String, seconds: Int, older: Int,
                       shrink: Boolean = false) {
        // the keyboard's own timers stopped, so its line does not come back over the picture
        get<Handler>(k, "ui").removeCallbacksAndMessages(null)
        dropContinueKey(k)
        call(k, "room", true)
        val status = get<TextView>(k, "status")
        val send = get<TextView>(k, "sendKey")
        val button = get<TextView>(k, "button")
        val lamp = get<LampView>(k, "lamp")
        val pill = get<FrameLayout>(k, "pill")
        val levelTrack = get<View>(k, "levelTrack")
        levelTrack.visibility = View.INVISIBLE
        button.setTextSize(TypedValue.COMPLEX_UNIT_SP, 19f)     // the keyboard's own, portrait
        val time = clock(seconds)
        val more = if (older > 0) " · $older older not sent" else ""
        if (arrangement == "A") {
            // The mic says what it is and nothing else; a tap on it would do what Continue does.
            lamp.colour = Skin.PAUSED
            lamp.halo = false
            lamp.breathe(false)
            (pill.background as? GradientDrawable)?.setStroke(dp(c, 1f), Skin.LINE)
            button.text = "Paused"
            status.text = "Recording paused · $time$more"
            val row = status.parent as LinearLayout
            val cont = TextView(c).apply {
                tag = TAG
                text = "Continue"
                gravity = Gravity.CENTER
                typeface = Skin.fontLabel(c)
                includeFontPadding = false
                setTextColor(Skin.FG)
                setTextSize(TypedValue.COMPLEX_UNIT_SP, 13.5f)
                maxLines = 1
                background = Skin.smallKey(c, 26)
                setPadding(dp(c, 12f), 0, dp(c, 12f), 0)
                minWidth = dp(c, 48f)
                layoutParams = LinearLayout.LayoutParams(
                    ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.MATCH_PARENT
                ).apply { marginStart = dp(c, 8f) }
            }
            row.addView(cont, row.indexOfChild(send))
        } else {
            // The mic is the way on: the recording's own red, held still (no halo, no breath:
            // nothing is listening), and its clock where the locked clock stands.
            lamp.colour = Skin.RECORDING
            lamp.halo = false
            lamp.breathe(false)
            (pill.background as? GradientDrawable)?.setStroke(dp(c, 1f), Skin.RECORDING)
            button.text = "Continue  $time"
            status.text = "Recording paused$more"
        }
        status.setTextColor(Skin.DIM)
        call(k, "rowKeys", true, true)
        send.text = "Send"
        send.contentDescription = "Send the paused recording"
        if (shrink) fit(c, k)
    }

    /** Continue: the keyboard's own locked recording, its buffer already [seconds] long. */
    private fun resume(k: DictationIme, seconds: Int) {
        get<Handler>(k, "ui").removeCallbacksAndMessages(null)
        dropContinueKey(k)
        call(k, "rowKeys", false, false)
        call(k, "room", false)
        call(k, "startLocked")
        val recorder = get<Recorder>(k, "recorder")
        val buffer = Recorder::class.java.getDeclaredField("buffer").apply { isAccessible = true }
            .get(recorder) as ByteArrayOutputStream
        synchronized(buffer) { buffer.write(ByteArray(seconds * Recorder.SAMPLE_RATE * 2)) }
        // what was said before the hide was loud: the finish must not read it as no sound
        Recorder::class.java.getDeclaredField("loudest").apply { isAccessible = true }
            .setFloat(recorder, 1f)
    }

    /** Send: a recording [seconds] long down the keyboard's real road, as a release sends one. */
    private fun send(c: Context, k: DictationIme, seconds: Int) {
        get<Handler>(k, "ui").removeCallbacksAndMessages(null)
        dropContinueKey(k)
        call(k, "rowKeys", false, false)
        call(k, "reset")
        val wav = wav(seconds)
        val app = c.applicationContext
        val item: () -> SpoolFiles.Item = { Spool.keep(app, wav) }
        DictationIme::class.java.getDeclaredMethod("go", String::class.java,
                                                   Long::class.javaPrimitiveType, Function0::class.java)
            .apply { isAccessible = true }
            .invoke(k, c.getString(R.string.transcribing), SystemClock.elapsedRealtime(), item)
    }

    private fun wav(seconds: Int): ByteArray {
        val pcm = ByteArray(seconds * Recorder.SAMPLE_RATE * 2)
        val out = ByteArrayOutputStream(44 + pcm.size)
        fun i32(v: Int) = out.write(byteArrayOf(v.toByte(), (v shr 8).toByte(), (v shr 16).toByte(),
                                                (v shr 24).toByte()))
        fun i16(v: Int) = out.write(byteArrayOf(v.toByte(), (v shr 8).toByte()))
        out.write("RIFF".toByteArray()); i32(36 + pcm.size)
        out.write("WAVE".toByteArray())
        out.write("fmt ".toByteArray()); i32(16); i16(1); i16(1)
        i32(Recorder.SAMPLE_RATE); i32(Recorder.SAMPLE_RATE * 2); i16(2); i16(16)
        out.write("data".toByteArray()); i32(pcm.size)
        out.write(pcm)
        return out.toByteArray()
    }

    /** Whether the words fit: the line's lines and any cut, each key's word cut or whole, sizes in dp. */
    private fun measure(c: Context, k: DictationIme) {
        val d = c.resources.displayMetrics.density
        val status = get<TextView>(k, "status")
        val row = status.parent as LinearLayout
        val keys = listOfNotNull(row.findViewWithTag<TextView>(TAG), get<TextView>(k, "sendKey"))
        fun cut(t: TextView) = t.visibility == View.VISIBLE &&
            t.paint.measureText(t.text.toString()) + t.paddingLeft + t.paddingRight > t.width + 1
        val button = get<TextView>(k, "button")
        val buttonCut = button.layout?.let { it.getEllipsisCount(0) > 0 } ?: false
        val ellipsis = status.layout?.let { it.getEllipsisCount(it.lineCount - 1) > 0 } ?: false
        val drop = get<View>(k, "dropKey")
        Log.i("DeskIT", "probe: measure lines=${status.lineCount} ellipsis=$ellipsis " +
            "line_dp=${(status.width / d).toInt()} " +
            keys.joinToString(" ") { "${it.text.toString().replace(' ', '_')}=${(it.width / d).toInt()}dp" +
                (if (cut(it)) ",cut" else "") } +
            " x=${(drop.width / d).toInt()}x${(drop.height / d).toInt()}dp" +
            " mic=${button.text.toString().replace(' ', '_')} mic_word_cut=$buttonCut mic_dp=${(get<View>(k, "pill").height / d).toInt()}" +
            " board_dp=${((row.parent as View).height / d).toInt()}")
    }
}
