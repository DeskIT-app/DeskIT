package io.github.deskit_app.deskit

import android.content.Context
import android.os.SystemClock
import android.util.Log
import org.json.JSONException
import org.json.JSONObject
import java.io.IOException
import java.net.HttpURLConnection
import kotlin.concurrent.thread

/**
 * One recording on its way to a PC while it is still being spoken (PHONE_LINK_PLAN.md
 * stage 2, the owner's choice of 2026-11-27): the same sentence, at the desk's speed.
 * Until stage 2 the whole recording crossed after the release and the PC decoded the
 * whole of it then, so a minute spoken was a minute's upload and decode waited for.
 * The PC decodes a stream as it arrives (phonestream.py, the desk's rolling.py), so at
 * the release only the tail is left, on either road.
 *
 * **Which road.** The ladder's own, decided while the person speaks: the door at home
 * that answered the knock ([Link.freshDoor]), if its PC reads `/stream` (its row says
 * so); else, once the door has had its second ([Road.ASK_MS]) and said nothing, the PC
 * that answered through the account ([Relay.view] READY), if its row says the same.
 * A PC from before stage 2 gets the whole recording at the release. Nothing is streamed before
 * then, so a dictation shorter than the question goes whole at the release, as it
 * always did, and at home nothing goes through the account.
 *
 * **Nothing new to lose.** Streaming is only ever an optimisation over a road that
 * already works. The recording stays the phone's own the whole time (the spool has it
 * from the release on); at the release the ladder ([Backup.dictate], [Link.dictate])
 * asks [onDoor] or [onRelay] for the stream's answer, and null means the stream did not
 * carry it (it broke, the PC wanted it whole, the ladder chose another road): the
 * recording then goes whole on the same rung, then the ladder as before. A pause or a
 * discard [cancel]s it, said to the PC and never left to look like a break. Nothing
 * reaches the field early: the PC answers once, at the end, with the whole text.
 *
 * **A Continue** goes on from a kept recording whose PCM is already in the recorder's
 * buffer, so its stream simply starts at the buffer's first byte: the kept part crosses
 * first, at once, then the rest as it is spoken. A stream that was going when the
 * keyboard closed was cancelled then, so the PC holds nothing of it twice.
 *
 * Never logged: a word, an address, a key. Numbers only.
 */
class LiveStream private constructor(private val app: Context, private val source: Recorder,
                                     private val since: Long) {

    companion object {
        /** server.STREAM_PROTO, and what a PC's row says it reads. */
        const val PROTO = 1
        /** How often the recording is looked at while it is spoken. */
        private const val EVERY_MS = 100L
        /** Transcriber.send's own read timeout: a cold model may take its time. */
        private const val READ_MS = 120_000
        /**
         * The recorder stopped and nobody said whether the recording went or was thrown
         * away: after this long the stream gives itself up, so no pump is left behind.
         */
        private const val ORPHAN_MS = 3000L

        /**
         * A stream for the recording that just began, or null on a phone that is not a
         * device of the account (the pasted line streams nothing). [askedAt] is when
         * the knock and the ping went (the press); 0 when none did.
         */
        fun begin(c: Context, recorder: Recorder, askedAt: Long): LiveStream? {
            if (askedAt <= 0 || !Link.joined(c)) return null
            return LiveStream(c.applicationContext, recorder, askedAt).also { it.watch() }
        }
    }

    @Suppress("PLATFORM_CLASS_MAPPED_TO_KOTLIN")
    private val gate = java.lang.Object()
    /** The recording's PCM at the release: from then on the stream sends from this. */
    private var final: ByteArray? = null
    private var cancelled = false
    /** The ladder took the stream's answer, or let it go: nothing more happens to it. */
    private var used = false
    private var door: Link.Road? = null
    private var relay: Relay.Streaming? = null
    private var answered = false
    private var answer: Transcriber.Result? = null
    private var pumpedWhileSpoken = 0
    /** The relay's pump has stopped sending: its end may go now. */
    private var pumped = false
    private var stoppedAt = 0L

    /** The PC the stream goes to through the account, while it does (for [Road.next]). */
    val relayTarget: String? get() = synchronized(gate) { relay?.takeIf { !cancelled && !it.failed }?.target }

    // ---- while it is spoken ----

    private fun watch() = thread(name = "stream-watch") {
        while (true) {
            synchronized(gate) { if (cancelled || final != null || door != null || relay != null) return@thread }
            try {
                // a door that answered the knock a moment ago: the one a release would use
                (if (Link.answeredRecently()) Link.freshDoor(app) else null)?.let { d ->
                    if (d.streams) {
                        synchronized(gate) {
                            if (cancelled || final != null) return@thread
                            door = d
                        }
                        pumpDoor(d)
                        return@thread
                    }
                }
                val now = SystemClock.elapsedRealtime()
                if (now - since >= Road.ASK_MS && Relay.usable(app)) {
                    val v = Relay.view(app, since, now)
                    if (v.state == Road.Relay.READY && v.target != null && Link.streamsTo(app, v.target)) {
                        val r = Relay.stream(app, v.target)
                        if (r != null) {
                            synchronized(gate) {
                                if (cancelled || final != null) { r.cancel(); return@thread }
                                relay = r
                            }
                            pumpRelay(r)
                            return@thread
                        }
                    }
                }
            } catch (e: Sealed.NotNow) {
                return@thread                       // the release says so
            } catch (e: RuntimeException) {
                Log.w("DeskIT", "stream: ${e.javaClass.simpleName}")
                return@thread
            }
            Thread.sleep(EVERY_MS)
        }
    }

    /** What is there to send now, from [sent]: the recording as it grows, or its end. */
    private fun next(sent: Int): Pair<ByteArray, Boolean>? = synchronized(gate) {
        if (cancelled) return null
        val fin = final
        if (fin == null) {
            gate.wait(EVERY_MS)
            if (cancelled) return null
            val f = final
            if (f == null) {
                if (!source.recording) {
                    val now = SystemClock.elapsedRealtime()
                    if (stoppedAt == 0L) stoppedAt = now
                    else if (now - stoppedAt >= ORPHAN_MS) {
                        cancelled = true
                        return null
                    }
                }
                return Pair(source.since(sent), false)
            }
            Pair(f.copyOfRange(minOf(sent, f.size), f.size), true)
        } else Pair(fin.copyOfRange(minOf(sent, fin.size), fin.size), true)
    }

    private fun pumpDoor(road: Link.Road) {
        var conn: HttpURLConnection? = null
        var result: Transcriber.Result? = null
        val t0 = SystemClock.elapsedRealtime()
        var ended = 0L
        try {
            conn = road.open("/stream").apply {
                requestMethod = "POST"
                doOutput = true
                connectTimeout = road.connectMs
                readTimeout = READ_MS
                road.prove(this)
                setRequestProperty("Content-Type", "application/octet-stream")
                setChunkedStreamingMode(0)
            }
            val out = conn.outputStream
            out.write(StreamWire.head())
            out.flush()
            var sent = 0
            while (true) {
                val (more, last) = next(sent) ?: run {
                    out.write(StreamWire.cancel())
                    out.flush()
                    out.close()
                    conn.responseCode
                    Log.i("DeskIT", "stream: cancelled on the door after ${sent / 32} ms of audio")
                    return
                }
                for (f in StreamWire.audio(more)) out.write(f)
                if (more.isNotEmpty()) out.flush()
                sent += more.size
                if (!last) {
                    pumpedWhileSpoken = sent
                    continue
                }
                val fin = synchronized(gate) { final!! }
                out.write(StreamWire.end(fin.size, RelayWire.sha256Hex(fin)))
                out.flush()
                out.close()
                ended = SystemClock.elapsedRealtime()
                val code = conn.responseCode
                val body = (if (code in 200..299) conn.inputStream else conn.errorStream)
                    ?.bufferedReader()?.use { it.readText() } ?: ""
                result = if (code !in 200..299 && wantsWhole(body)) null else Transcriber.answer(code, body)
                Log.i("DeskIT", "stream: the door, ${pumpedWhileSpoken / 32} ms of audio while spoken, " +
                    "${(fin.size - pumpedWhileSpoken) / 32} ms after the release, answered " +
                    "${SystemClock.elapsedRealtime() - ended} ms after the end" +
                    if (result == null) " (wants it whole)" else "")
                break
            }
        } catch (e: IOException) {
            Log.i("DeskIT", "stream: the door broke after ${SystemClock.elapsedRealtime() - t0} ms " +
                "(${e.javaClass.simpleName})")
            result = null
        } catch (e: JSONException) {
            result = Transcriber.Result.Err(Transcriber.UNREADABLE)
        } finally {
            conn?.disconnect()
            synchronized(gate) {
                answer = result
                answered = true
                gate.notifyAll()
            }
        }
    }

    private fun wantsWhole(body: String): Boolean = try {
        JSONObject(body).optBoolean("whole", false)
    } catch (e: JSONException) {
        false
    }

    private fun pumpRelay(r: Relay.Streaming) {
        var sent = 0
        try {
            while (true) {
                val (more, last) = next(sent) ?: run {
                    r.cancel()
                    return
                }
                // whole pieces only while it is spoken; the end sends the rest
                val whole = if (last) 0 else more.size - more.size % RelayWire.FRAME_BYTES
                var at = 0
                while (at < whole) {
                    if (!r.piece(sent, more.copyOfRange(at, at + RelayWire.FRAME_BYTES))) return
                    sent += RelayWire.FRAME_BYTES
                    at += RelayWire.FRAME_BYTES
                }
                synchronized(gate) { pumpedWhileSpoken = sent }
                if (last) return
            }
        } finally {
            synchronized(gate) {
                pumped = true
                gate.notifyAll()
            }
        }
    }

    // ---- at the release ----

    /** The release: the recording as it ended. The stream sends the rest and its end. */
    fun ended(pcm: ByteArray) {
        synchronized(gate) {
            if (final == null) final = pcm
            gate.notifyAll()
        }
    }

    /** The keyboard closed on it, or it was thrown away: the PC is told, and holds nothing. */
    fun cancel() {
        val r = synchronized(gate) {
            if (cancelled || used) return
            cancelled = true
            gate.notifyAll()
            relay
        }
        r?.cancel()
    }

    /**
     * The ladder's PC road reached [road] with [wav]: the stream's own answer when it
     * went to that very door, or null and the recording goes whole (Link.send).
     */
    fun onDoor(road: Link.Road, wav: ByteArray): Transcriber.Result? {
        val d = synchronized(gate) { door }
        if (d == null || road.key.isEmpty() || d.key != road.key) {
            cancel()
            return null
        }
        ended(Recorder.pcm(wav))
        synchronized(gate) {
            val until = SystemClock.elapsedRealtime() + READ_MS + 10_000L
            while (!answered && !cancelled && SystemClock.elapsedRealtime() < until) gate.wait(200)
            used = true
            return if (answered) answer else null
        }
    }

    /**
     * The ladder sends [wav] through the account to [target]: the stream's end and its
     * answer when the stream went there, or null and the recording goes whole
     * ([Relay.send]). [moved] as Relay.send's.
     */
    fun onRelay(target: String, wav: ByteArray, moved: (took: Boolean) -> Unit): Transcriber.Result? {
        val r = synchronized(gate) { relay }
        if (r == null || r.target != target || r.failed) {
            cancel()
            return null
        }
        ended(Recorder.pcm(wav))
        val from = synchronized(gate) {
            // the pump finishes the piece it is on, then stops: the end goes after it
            val until = SystemClock.elapsedRealtime() + Relay.PIECE_WAIT_MS
            while (!pumped && SystemClock.elapsedRealtime() < until) gate.wait(50)
            used = true
            if (pumped) pumpedWhileSpoken else -1
        }
        if (from < 0) {
            // a link stuck under a piece: this request goes, and the recording whole
            r.cancel()
            return null
        }
        return r.finish(wav, from, moved)
    }
}
