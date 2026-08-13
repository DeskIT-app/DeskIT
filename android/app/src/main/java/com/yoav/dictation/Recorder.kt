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
    }

    private var record: AudioRecord? = null
    @Volatile private var running = false
    private var worker: Thread? = null
    private val buffer = ByteArrayOutputStream()

    /** Throws SecurityException when RECORD_AUDIO was never granted. */
    fun start() {
        if (running) return
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
        record = r
        running = true
        r.startRecording()
        worker = thread(name = "mic") {
            val chunk = ByteArray(4096)
            while (running) {
                val n = r.read(chunk, 0, chunk.size)
                if (n > 0) synchronized(buffer) { buffer.write(chunk, 0, n) }
            }
        }
    }

    /** Stops and returns the utterance as WAV bytes, or null if too short. */
    fun stop(): ByteArray? {
        if (!running) return null
        running = false
        worker?.join(1000)
        worker = null
        record?.let {
            try { it.stop() } catch (_: IllegalStateException) { }
            it.release()
        }
        record = null
        val pcm = synchronized(buffer) { buffer.toByteArray() }
        // Mirrors min_seconds on the desktop: a stray tap is not speech.
        if (pcm.size < SAMPLE_RATE / 2 * 2) return null
        return wav(pcm)
    }

    fun cancel() {
        running = false
        worker?.join(500)
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
