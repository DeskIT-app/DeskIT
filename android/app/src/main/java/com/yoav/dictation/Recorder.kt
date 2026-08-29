package com.yoav.dictation

import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import java.io.ByteArrayOutputStream
import kotlin.concurrent.thread

/**
 * Raw 16 kHz mono PCM, wrapped as a WAV.
 *
 * MediaRecorder would produce a smaller file, but it also decides the
 * sample rate and container for us and throws if stopped too soon after
 * starting — both bad properties for a push-to-talk button. AudioRecord
 * gives exactly the format the server's Whisper model already wants, so
 * nothing transcodes anywhere. A minute costs ~1.9 MB, which over a
 * private Tailscale link is not worth optimising.
 */
class Recorder {

    companion object {
        const val SAMPLE_RATE = 16000

        /**
         * A ceiling on one recording, in seconds.
         *
         * The desktop caps a HELD recording with max_seconds only to guard
         * against a key-up the OS swallowed, and leaves a latched one
         * uncapped because it has no key-up to lose. The phone needs the
         * cap for a different reason: a locked recording that is forgotten
         * grows until the process is killed and every word of it is lost.
         * At 32 KB/s this is 9.6 MB, comfortably inside the server's 32 MB
         * body limit — past that the upload comes back a flat 400 and the
         * whole recording is wasted rather than trimmed.
         */
        const val MAX_SECONDS = 300
    }

    private var record: AudioRecord? = null
    @Volatile private var running = false
    private var worker: Thread? = null
    private val buffer = ByteArrayOutputStream()

    /**
     * Live loudness 0..1, and the loudest this recording ever got.
     *
     * `peak` drives the level bar, so it decays: without that it would sit
     * at whatever the last loud syllable was and read as a frozen meter.
     * `loudest` never decays — it is the evidence behind "was anything
     * recorded at all", which is how a microphone another app is holding
     * gets told apart from a pause in speech.
     */
    @Volatile var peak: Float = 0f
        private set

    @Volatile var loudest: Float = 0f
        private set

    /** Set when MAX_SECONDS ended the recording rather than the user. */
    @Volatile var capped: Boolean = false
        private set

    /**
     * True between start() and stop()/cancel().
     *
     * Deliberately separate from `running`, which the worker clears by
     * itself at the cap. Keying stop() off `running` would make a capped
     * recording return null and throw away the very audio the cap exists
     * to protect.
     */
    @Volatile private var active = false

    val recording: Boolean
        get() = active

    /** Throws SecurityException when RECORD_AUDIO was never granted. */
    fun start() {
        if (active) return
        val minBuf = AudioRecord.getMinBufferSize(
            SAMPLE_RATE,
            AudioFormat.CHANNEL_IN_MONO,
            AudioFormat.ENCODING_PCM_16BIT
        )
        // VOICE_RECOGNITION, not MIC: it is the source Android tunes for
        // speech, and it leaves aggressive music-oriented processing off.
        val r = AudioRecord(
            MediaRecorder.AudioSource.VOICE_RECOGNITION,
            SAMPLE_RATE,
            AudioFormat.CHANNEL_IN_MONO,
            AudioFormat.ENCODING_PCM_16BIT,
            maxOf(minBuf, SAMPLE_RATE) * 2
        )
        if (r.state != AudioRecord.STATE_INITIALIZED) {
            r.release()
            throw IllegalStateException("microphone unavailable")
        }
        buffer.reset()
        peak = 0f
        loudest = 0f
        capped = false
        record = r
        running = true
        active = true
        r.startRecording()
        worker = thread(name = "mic") {
            val chunk = ByteArray(4096)
            val cap = SAMPLE_RATE * 2 * MAX_SECONDS
            while (running) {
                val n = r.read(chunk, 0, chunk.size)
                if (n <= 0) continue
                measure(chunk, n)
                val size = synchronized(buffer) {
                    buffer.write(chunk, 0, n); buffer.size()
                }
                if (size >= cap) {
                    // Stop reading, but leave `active` alone: the audio so
                    // far is good and stop() still has to hand it over.
                    capped = true
                    running = false
                }
            }
        }
    }

    /**
     * Loudest sample in this chunk, as 0..1, decayed into `peak`.
     *
     * Sampled every other frame rather than every one: at 16 kHz that is
     * still ~1000 samples per 4096-byte chunk, far more than a 100 ms
     * repaint can show, and it halves the work on the mic thread — which
     * must never be the reason a read is late.
     */
    private fun measure(chunk: ByteArray, n: Int) {
        var loud = 0
        var i = 0
        while (i + 1 < n) {
            val s = ((chunk[i + 1].toInt() shl 8) or (chunk[i].toInt() and 0xff)).toShort()
            val a = if (s < 0) -s.toInt() else s.toInt()
            if (a > loud) loud = a
            i += 4
        }
        val now = loud / 32768f
        if (now > loudest) loudest = now
        peak = if (now > peak) now else peak * 0.75f
    }

    /** Stops and returns the utterance as WAV bytes, or null if too short. */
    fun stop(): ByteArray? {
        if (!active) return null
        release()
        val pcm = synchronized(buffer) { buffer.toByteArray() }
        // Mirrors min_seconds on the desktop: a stray tap is not speech.
        if (pcm.size < SAMPLE_RATE / 2 * 2) return null
        return wav(pcm)
    }

    fun cancel() {
        release()
    }

    private fun release() {
        running = false
        active = false
        peak = 0f
        worker?.join(1000)
        worker = null
        record?.let {
            try { it.stop() } catch (_: IllegalStateException) { }
            it.release()
        }
        record = null
    }

    val seconds: Float
        get() = synchronized(buffer) { buffer.size() / 2f / SAMPLE_RATE }

    private fun wav(pcm: ByteArray): ByteArray {
        val out = ByteArrayOutputStream(44 + pcm.size)
        fun i32(v: Int) = out.write(
            byteArrayOf(
                (v and 0xff).toByte(), ((v shr 8) and 0xff).toByte(),
                ((v shr 16) and 0xff).toByte(), ((v shr 24) and 0xff).toByte()
            )
        )
        fun i16(v: Int) = out.write(
            byteArrayOf((v and 0xff).toByte(), ((v shr 8) and 0xff).toByte())
        )
        out.write("RIFF".toByteArray()); i32(36 + pcm.size)
        out.write("WAVE".toByteArray())
        out.write("fmt ".toByteArray()); i32(16); i16(1); i16(1)
        i32(SAMPLE_RATE); i32(SAMPLE_RATE * 2); i16(2); i16(16)
        out.write("data".toByteArray()); i32(pcm.size)
        out.write(pcm)
        return out.toByteArray()
    }
}
