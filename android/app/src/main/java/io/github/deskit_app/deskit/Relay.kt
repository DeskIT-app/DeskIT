package io.github.deskit_app.deskit

import android.content.Context
import android.os.SystemClock
import android.util.Log
import java.io.IOException
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.LinkedBlockingQueue
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger
import kotlin.concurrent.thread

/**
 * The sealed relay through the account, the phone's end (PHONE_LINK_PLAN.md stage 3,
 * Q1, his "also through the account"). Away from home, with no road to the PC (his
 * carrier's NAT is the hard kind and his home has no IPv6, M2, and so for many), the
 * recording crosses the account's own private channel instead, in pieces, each sealed
 * under the account key, and the PC's text comes back the same way. The PC's model,
 * the PC's learned words: the cloud key is only the rung after this one.
 *
 * **One socket, while it is useful.** [ask] opens a websocket to the account's
 * Realtime, joins `user:<uid>` with this phone's session, and pings every PC of the
 * account; a PC that is there answers with no model involved, so by the release the
 * road is known ([view], [Road.next]). The socket stays for [IDLE_MS] after its last
 * use, so sentence after sentence pays for it once, and goes when the keyboard hides
 * with nothing in flight, on every road out of the account ([forget]) and when its
 * token's hour is nearly up. The relay's own socket ([Ws]), not the WebView the plan
 * first named: see there why.
 *
 * **Who it believes.** A piece opens only under the account key with its own AAD
 * (RelayWire), so a server that lies cannot make one. A pong is taken only from a PC
 * of the account this phone has read and not forgotten ([Lock.cachedDevices]), and a
 * PC's `took` and `text` only from the PC the recording went to, on its own request.
 *
 * **No new way to lose words.** The recording is the spool's ([Spool]) until a text
 * lands: anything here that fails is an answer of UNREACHED, and the road goes on to
 * the next rung or to the waiting row, the recording on the disk.
 *
 * Never logged: a word, a key, a sealed value, an address, a device's id.
 */
object Relay {
    /** A socket that has not joined by then is nobody, this time. */
    const val JOIN_MS = 6000L
    /** A socket unused this long goes. */
    private const val IDLE_MS = 60_000L
    /** A PC's "I am here" is believed this long. */
    private const val PONG_FRESH_MS = 30_000L
    /** One piece's acknowledgement from the server. */
    private const val ACK_MS = 10_000L
    /** After the last piece, the PC says it has the recording. */
    private const val TOOK_MS = 10_000L
    /** After that, the PC's text: Transcriber.send's own read timeout. */
    private const val TEXT_MS = 120_000L
    /** Pieces on the wire at once, unacknowledged. */
    private const val WINDOW = 3
    private const val HEARTBEAT_MS = 25_000L
    /** A token with less than this left is refreshed before a socket opens on it. */
    private const val TOKEN_LEFT_S = 90L
    /** How long a stream's pump may hold the piece it is sending (stage 2). */
    const val PIECE_WAIT_MS = ACK_MS + 2_000L

    /** What the relay can do for the recording now, for [Road.next]. */
    class View(val state: Road.Relay, val target: String? = null, val why: String = "")

    private class Pong(val pc: String, val ready: Boolean, val why: String, val at: Long)

    private class Line(val uid: String, val me: String, val pcs: Set<String>, val expiresAt: Long,
                       val ws: Ws, val askedAt: Long) {
        @Volatile var joinedAt = 0L
        @Volatile var failed = false
        @Volatile var pingAt = 0L
        @Volatile var lastUse = askedAt
        val pongs = ConcurrentHashMap<String, Pong>()
        val pings: MutableSet<String> = ConcurrentHashMap.newKeySet()
        val replies = ConcurrentHashMap<String, LinkedBlockingQueue<RelayWire.Piece>>()
        val acks = ConcurrentHashMap<String, LinkedBlockingQueue<RelayWire.Heard.Reply>>()
        val ref = AtomicInteger(1)
        val inFlight = AtomicInteger(0)
        val joinRef = "1"
        fun nextRef() = ref.incrementAndGet().toString()
        val alive: Boolean get() = !failed && !ws.closed
    }

    @Volatile private var line: Line? = null
    /** Who is opening one now: a second ask while it opens joins this one. */
    @Volatile private var opening: Thread? = null
    private val gate = Any()

    /** May this phone ask through the account at all? No network, no Keystore. */
    fun usable(c: Context): Boolean = Link.joined(c)

    // ---- asking ----

    /**
     * Ask now, beside whatever else is asked: the socket if there is none, and a ping.
     * Quick: the work is on a thread of its own. Nothing happens on a phone that is not
     * a device of the account.
     */
    fun ask(c: Context) {
        val app = c.applicationContext
        if (!usable(app)) return
        synchronized(gate) {
            if (opening?.isAlive == true) return
            lastTry = SystemClock.elapsedRealtime()
            opening = thread(name = "relay-ask") {
                try {
                    val l = ensure(app)
                    if (l != null) ping(app, l)
                } catch (e: Account.Failed) {
                    Log.i("DeskIT", "relay: the account did not answer")
                } catch (e: Sealed.NotNow) {
                    Log.i("DeskIT", "relay: waits for the seal")
                } catch (e: RuntimeException) {
                    Log.w("DeskIT", "relay: ${e.javaClass.simpleName}")
                }
            }
        }
    }

    /** The line, open and joined or on its way, or a new one. Blocking. */
    private fun ensure(app: Context): Line? {
        line?.let { l ->
            val left = l.expiresAt - System.currentTimeMillis() / 1000
            if (l.alive && left > TOKEN_LEFT_S) return l
            close(l, "renewed")
        }
        var s = Account.fresh(app)
        if (s.expiresAt - System.currentTimeMillis() / 1000 <= TOKEN_LEFT_S) s = Account.refreshNow(app)
        val me = Lock.deviceId(app, s.uid)
        val pcs = try {
            Lock.cachedDevices(app).filter { it.isPc && !it.mine }.map { it.id }.toSet()
        } catch (e: Account.Failed) {
            emptySet()
        }
        val at = SystemClock.elapsedRealtime()
        if (pcs.isEmpty()) {
            Log.i("DeskIT", "relay: no PC of the account on this phone yet")
            return null
        }
        val url = Account.base(app).replaceFirst("https://", "wss://").replaceFirst("http://", "ws://") +
            "/realtime/v1/websocket?vsn=1.0.0"
        val ws = try {
            // named, as Cloud's requests are: Cloudflare stands in front of the account too
            Ws.open(url, mapOf("apikey" to Account.PUBLISHABLE_KEY, "User-Agent" to Cloud.userAgent(app)),
                    JOIN_MS.toInt())
        } catch (e: IOException) {
            Log.i("DeskIT", "relay: the account's channel did not open (${e.javaClass.simpleName})")
            return null
        }
        val l = Line(s.uid, me, pcs, s.expiresAt, ws, at)
        line = l
        thread(name = "relay-read") { read(app, l) }
        try {
            ws.send(RelayWire.join(s.uid, s.access, l.joinRef))
        } catch (e: IOException) {
            close(l, "the join did not go")
            return null
        }
        val until = at + JOIN_MS
        while (l.joinedAt == 0L && l.alive && SystemClock.elapsedRealtime() < until) Thread.sleep(20)
        if (l.joinedAt == 0L) {
            Log.i("DeskIT", "relay: the account's channel did not take the join")
            close(l, "no join")
            return null
        }
        Log.i("DeskIT", "relay: joined in ${l.joinedAt - at} ms")
        return l
    }

    /** When the last [ask] set out: one that ended with no socket is nobody, this time. */
    @Volatile private var lastTry = 0L

    /**
     * Has this dictation been asked about through the account: an [ask] since [since]
     * (the press, or Send again)? An open socket's "nobody" from an earlier ping is no
     * answer about a PC that came back since (found on the emulator, 2026-11-12: Send
     * again on a PC up again read the old nobody and never pinged).
     */
    fun askedSince(since: Long): Boolean = lastTry > 0 && lastTry >= since - 50

    /** When the last "here" of any PC came, on any socket. */
    @Volatile private var lastPongAt = 0L

    /**
     * A PC said "here" during this dictation (since [since], the press), and that answer
     * has gone stale since or its socket closed (a minute idle, the network): a long
     * dictation asks once more at the release, so it neither loses its PC to the clock
     * nor sends to one that went while the person spoke. A dictation nobody answered is
     * not asked again here: the cloud would wait a second more for nothing.
     */
    fun recheck(since: Long, now: Long = SystemClock.elapsedRealtime()): Boolean =
        lastPongAt >= since && (line?.alive != true || now - lastPongAt >= PONG_FRESH_MS)

    private fun ping(app: Context, l: Line) {
        val rid = RelayWire.newRid()
        l.pings.add(rid)
        l.pingAt = SystemClock.elapsedRealtime()
        l.lastUse = l.pingAt
        val piece = Lock.withKey(app) { uid, key ->
            RelayWire.seal(key, uid, l.me, RelayWire.EVERY_PC, rid, 0, RelayWire.pingHead())
        }
        try {
            l.ws.send(RelayWire.broadcast(l.uid, piece, l.nextRef(), l.joinRef))
        } catch (e: IOException) {
            close(l, "the ping did not go")
        }
    }

    // ---- reading ----

    private fun read(app: Context, l: Line) {
        var beat = SystemClock.elapsedRealtime()
        while (true) {
            val text = l.ws.next(1000)
            val now = SystemClock.elapsedRealtime()
            if (text == GONE || l.ws.closed) break
            if (now - beat >= HEARTBEAT_MS) {
                beat = now
                try {
                    l.ws.send(RelayWire.heartbeat(l.nextRef()))
                } catch (e: IOException) {
                    break
                }
            }
            if (l.inFlight.get() == 0 && now - l.lastUse > IDLE_MS) {
                close(l, "idle")
                break
            }
            if (text == null) continue
            when (val h = RelayWire.heard(text)) {
                is RelayWire.Heard.Reply -> {
                    if (h.ref == l.joinRef) {
                        if (h.ok) l.joinedAt = now
                        else {
                            Log.i("DeskIT", "relay: the join was refused (${h.why})")
                            close(l, "refused")
                        }
                    } else l.acks[h.ref]?.put(h)
                }
                is RelayWire.Heard.Link -> take(app, l, h.payload, now)
                is RelayWire.Heard.Gone -> {
                    Log.i("DeskIT", "relay: the channel went (${h.why})")
                    close(l, h.why)
                }
                RelayWire.Heard.Other -> {}
            }
        }
        l.failed = true
    }

    /** One piece of another device's. Only what is this phone's is opened. */
    private fun take(app: Context, l: Line, payload: Map<String, Any?>, now: Long) {
        if (payload["to"] != l.me) return
        val from = payload["device"] as? String ?: return
        if (from !in l.pcs) return
        val p = try {
            Lock.withKey(app) { uid, key -> RelayWire.open(key, uid, payload) }
        } catch (e: RelayWire.Refused) {
            Log.i("DeskIT", "relay: a piece did not open")
            return
        } catch (e: Account.Failed) {
            return
        } catch (e: Sealed.NotNow) {
            return
        }
        when (p.kind) {
            "pong" -> if (p.rid in l.pings) {
                l.pongs[from] = Pong(from, p.head["ready"] == true, p.head["why"] as? String ?: "", now)
                lastPongAt = now
            }
            "took", "text" -> l.replies[p.rid]?.put(p)
        }
    }

    private fun close(l: Line, why: String) {
        l.failed = true
        // Never on the caller's thread: the keyboard hiding and every road out of the
        // account come here on the main thread, where Android refuses a socket's write
        // (NetworkOnMainThreadException), and the keyboard died with it (flow_door's
        // small_phone, 2026-11-12: a change of screen density hides and shows it).
        thread(name = "relay-close") { l.ws.close() }
        if (line === l) line = null
        Log.i("DeskIT", "relay: the socket closed ($why)")
        lastClosed = l
    }

    /** The line that closed last, so [view] can still say what it heard. */
    @Volatile private var lastClosed: Line? = null

    // ---- what it says ----

    /**
     * What the relay can do now. [since] is when the asking began (the press, or Send
     * again): a socket that has not joined [JOIN_MS] after it is nobody, and a joined
     * one whose ping [Road.ASK_MS] old has no answer is nobody too.
     */
    fun view(c: Context, since: Long, now: Long = SystemClock.elapsedRealtime()): View {
        if (!usable(c)) return View(Road.Relay.OFF)
        // the asking began at the press, or later if this dictation was asked about later
        // (the door from a moment ago failed after a long dictation): its own second
        val begun = if (lastTry >= since) lastTry else since
        val l = line
        if (l == null || !l.alive) {
            // no socket: one on its way, one that did not come, or nobody asked
            if (opening?.isAlive == true) return View(if (now - begun < JOIN_MS) Road.Relay.ASKING else Road.Relay.NOBODY)
            return View(if (lastTry > 0 && lastTry >= since - JOIN_MS) Road.Relay.NOBODY else Road.Relay.OFF)
        }
        // Once this dictation's own ping went, only an answer to it counts, and for as long
        // as the dictation lasts: a PC that said "here" a minute ago and went away since
        // would cost a stalled send and 8 s, and a 45 s dictation must not lose its PC to
        // the clock (flow_relay's timing, 2026-11-12: it did, at a 30 s limit). A long one
        // asks again at the release ([recheck]).
        val current = l.pingAt >= begun - 50
        val fresh = l.pongs.values.filter { if (current) it.at >= l.pingAt else now - it.at < PONG_FRESH_MS }
        fresh.filter { it.ready }.maxByOrNull { it.at }?.let { return View(Road.Relay.READY, it.pc) }
        fresh.maxByOrNull { it.at }?.let { return View(Road.Relay.BUSY, it.pc, it.why) }
        if (l.joinedAt == 0L) return View(if (now - l.askedAt < JOIN_MS) Road.Relay.ASKING else Road.Relay.NOBODY)
        // joined: the ping's second counts from whichever came last, the join or the ping
        val asked = maxOf(l.pingAt, l.joinedAt)
        if (now - asked < Road.ASK_MS) return View(Road.Relay.ASKING)
        // a ping for this dictation still to go (the ask's thread is on its way)
        if (!current && opening?.isAlive == true && now - begun < JOIN_MS) return View(Road.Relay.ASKING)
        return View(Road.Relay.NOBODY)
    }

    /**
     * Is a PC there through the account? For the keyboard's line when it comes up: a
     * ping and at most [JOIN_MS] and a second of waiting. Blocking.
     */
    fun reach(c: Context): Boolean {
        val app = c.applicationContext
        if (!usable(app)) return false
        val since = SystemClock.elapsedRealtime()
        ask(app)
        val until = since + JOIN_MS + Road.ASK_MS
        while (SystemClock.elapsedRealtime() < until) {
            when (view(app, since).state) {
                Road.Relay.READY -> return true
                Road.Relay.BUSY, Road.Relay.NOBODY, Road.Relay.OFF -> return false
                Road.Relay.ASKING -> Thread.sleep(50)
            }
        }
        return false
    }

    /** The channel joined in the last minutes: the network reaches the account. */
    fun heardLately(now: Long = SystemClock.elapsedRealtime()): Boolean {
        val l = line ?: lastClosed ?: return false
        return l.joinedAt > 0 && now - l.lastUse < 5 * 60_000L
    }

    // ---- sending ----

    /**
     * One recording to the PC that answered, in sealed pieces, and its text. Blocking.
     * [moved] is told each time the recording gets further (a piece acknowledged, the
     * PC took it), so the road can tell a slow link from a dead one.
     */
    fun send(c: Context, wav: ByteArray, target: String, moved: (took: Boolean) -> Unit): Transcriber.Result {
        val app = c.applicationContext
        val unreached = Transcriber.Result.Err(app.getString(R.string.unreachable), Transcriber.Why.UNREACHED)
        val l = line ?: return unreached
        if (!l.alive || target !in l.pcs) return unreached
        val rid = RelayWire.newRid()
        val replies = LinkedBlockingQueue<RelayWire.Piece>()
        l.replies[rid] = replies
        l.inFlight.incrementAndGet()
        val t0 = SystemClock.elapsedRealtime()
        try {
            val pieces = try {
                Lock.withKey(app) { uid, key ->
                    RelayWire.recording(key, uid, l.me, target, rid, wav, System.currentTimeMillis())
                }
            } catch (e: RelayWire.Refused) {
                return Transcriber.Result.Err(app.getString(R.string.unreachable), Transcriber.Why.UNREACHED)
            }
            val out = ArrayDeque<Pair<String, LinkedBlockingQueue<RelayWire.Heard.Reply>>>()
            fun settle(one: Pair<String, LinkedBlockingQueue<RelayWire.Heard.Reply>>): Boolean {
                val r = one.second.poll(ACK_MS, TimeUnit.MILLISECONDS)
                l.acks.remove(one.first)
                if (r == null || !r.ok) {
                    Log.i("DeskIT", "relay: a piece was not taken by the server (${r?.why ?: "no answer"})")
                    return false
                }
                l.lastUse = SystemClock.elapsedRealtime()
                moved(false)
                return true
            }
            for (p in pieces) {
                while (out.size >= WINDOW) if (!settle(out.removeFirst())) return unreached
                val ref = l.nextRef()
                val q = LinkedBlockingQueue<RelayWire.Heard.Reply>()
                l.acks[ref] = q
                try {
                    l.ws.send(RelayWire.broadcast(l.uid, p, ref, l.joinRef))
                } catch (e: IOException) {
                    return unreached
                }
                out.addLast(Pair(ref, q))
            }
            while (out.isNotEmpty()) if (!settle(out.removeFirst())) return unreached
            val sent = SystemClock.elapsedRealtime()
            Log.i("DeskIT", "relay: ${pieces.size} pieces up in ${sent - t0} ms")
            return awaitText(app, l, replies, target, t0, sent, moved)
        } catch (e: Account.Failed) {
            return unreached
        } catch (e: Sealed.NotNow) {
            return Transcriber.Result.Err(Sealed.words(app, e), Transcriber.Why.BUSY)
        } finally {
            l.replies.remove(rid)
            l.inFlight.decrementAndGet()
            l.lastUse = SystemClock.elapsedRealtime()
        }
    }

    /** After the last piece: the PC's `took`, then its `text`, from [target] alone. */
    private fun awaitText(app: Context, l: Line, replies: LinkedBlockingQueue<RelayWire.Piece>, target: String,
                          t0: Long, sent: Long, moved: (took: Boolean) -> Unit): Transcriber.Result {
        val unreached = Transcriber.Result.Err(app.getString(R.string.unreachable), Transcriber.Why.UNREACHED)
        var took = false
        var until = sent + TOOK_MS
        while (true) {
            val left = until - SystemClock.elapsedRealtime()
            if (left <= 0 || (!l.alive && replies.isEmpty())) {
                Log.i("DeskIT", "relay: the PC ${if (took) "took it and said nothing" else "did not take it"}")
                return unreached
            }
            val p = replies.poll(minOf(left, 500L), TimeUnit.MILLISECONDS) ?: continue
            if (p.from != target) continue
            if (p.kind == "took" && !took) {
                took = true
                until = SystemClock.elapsedRealtime() + TEXT_MS
                l.lastUse = SystemClock.elapsedRealtime()
                moved(true)
                Log.i("DeskIT", "relay: the PC took it ${SystemClock.elapsedRealtime() - sent} ms after the last piece")
            } else if (p.kind == "text") {
                Log.i("DeskIT", "relay: the text, ${SystemClock.elapsedRealtime() - t0} ms after the first piece")
                return result(app, p)
            }
        }
    }

    // ---- sending while it is spoken (stage 2) ----

    /** A recording on its way through the account while it is spoken ([LiveStream]). */
    interface Streaming {
        val target: String
        val failed: Boolean
        /** The PCM at [offset] (a whole piece's place), sealed and sent; false: the stream broke. */
        fun piece(offset: Int, pcm: ByteArray): Boolean
        /**
         * The rest from [from], piece 0 (the header, the length known now), the end, then
         * the PC's `took` and `text`, as [send]. Null: the pieces did not get across, and
         * the recording goes whole.
         */
        fun finish(wav: ByteArray, from: Int, moved: (took: Boolean) -> Unit): Transcriber.Result?
        /** Let it go: the PC is told (a `cancel`) and holds nothing of it. Any thread. */
        fun cancel()
    }

    /** A stream to [target] on the socket open now; null when there is none to stream on. */
    fun stream(c: Context, target: String): Streaming? {
        val l = line ?: return null
        if (!l.alive || l.joinedAt == 0L || target !in l.pcs) return null
        return StreamLine(c.applicationContext, l, target)
    }

    private class StreamLine(private val app: Context, private val l: Line,
                             override val target: String) : Streaming {
        private val rid = RelayWire.newRid()
        private val replies = LinkedBlockingQueue<RelayWire.Piece>()
        private val out = ArrayDeque<Pair<String, LinkedBlockingQueue<RelayWire.Heard.Reply>>>()
        @Volatile override var failed = false
        private var released = false
        private var whileSpoken = 0
        private val t0 = SystemClock.elapsedRealtime()

        init {
            l.replies[rid] = replies
            l.inFlight.incrementAndGet()
            l.lastUse = t0
        }

        private fun settle(moved: ((Boolean) -> Unit)?): Boolean {
            val one = out.removeFirst()
            val r = one.second.poll(ACK_MS, TimeUnit.MILLISECONDS)
            l.acks.remove(one.first)
            if (r == null || !r.ok) {
                Log.i("DeskIT", "relay: a streamed piece was not taken by the server (${r?.why ?: "no answer"})")
                return false
            }
            l.lastUse = SystemClock.elapsedRealtime()
            moved?.invoke(false)
            return true
        }

        private fun send(sealed: String, moved: ((Boolean) -> Unit)?): Boolean {
            while (out.size >= WINDOW) if (!settle(moved)) return false
            if (!l.alive) return false
            val ref = l.nextRef()
            val q = LinkedBlockingQueue<RelayWire.Heard.Reply>()
            l.acks[ref] = q
            try {
                l.ws.send(RelayWire.broadcast(l.uid, sealed, ref, l.joinRef))
            } catch (e: IOException) {
                l.acks.remove(ref)
                return false
            }
            out.addLast(Pair(ref, q))
            return true
        }

        private fun sealed(make: (String, ByteArray) -> String): String? = try {
            Lock.withKey(app) { uid, key -> make(uid, key) }
        } catch (e: Account.Failed) {
            null
        } catch (e: Sealed.NotNow) {
            null
        } catch (e: RelayWire.Refused) {
            null
        }

        @Synchronized override fun piece(offset: Int, pcm: ByteArray): Boolean {
            if (failed || released) return false
            val s = sealed { uid, key -> RelayWire.streamed(key, uid, l.me, target, rid, offset, pcm) }
            if (s == null || !send(s, null)) {
                failed = true
                giveUp("a piece did not go")
                return false
            }
            whileSpoken++
            return true
        }

        @Synchronized override fun finish(wav: ByteArray, from: Int,
                                          moved: (took: Boolean) -> Unit): Transcriber.Result? {
            if (failed || released) return null
            try {
                val pcm = Recorder.pcm(wav)
                val rest = ArrayList<String>()
                var at = from
                while (at < pcm.size) {
                    val end = minOf(pcm.size, at + RelayWire.FRAME_BYTES)
                    val chunk = pcm.copyOfRange(at, end)
                    val one = at
                    rest.add(sealed { uid, key -> RelayWire.streamed(key, uid, l.me, target, rid, one, chunk) }
                                 ?: return fail("a piece was not sealed"))
                    at = end
                }
                rest.add(sealed { uid, key -> RelayWire.header(key, uid, l.me, target, rid, pcm.size) }
                             ?: return fail("the header was not sealed"))
                rest.add(sealed { uid, key ->
                    RelayWire.streamedEnd(key, uid, l.me, target, rid, wav, System.currentTimeMillis())
                } ?: return fail("the end was not sealed"))
                val released0 = SystemClock.elapsedRealtime()
                for (p in rest) if (!send(p, moved)) return fail("a piece did not go")
                while (out.isNotEmpty()) if (!settle(moved)) return fail("a piece was not taken")
                val sent = SystemClock.elapsedRealtime()
                Log.i("DeskIT", "relay: streamed, $whileSpoken pieces while spoken and ${rest.size} at the " +
                    "release, up ${sent - released0} ms after it")
                return awaitText(app, l, replies, target, t0, sent, moved)
            } finally {
                release()
            }
        }

        private fun fail(why: String): Transcriber.Result? {
            failed = true
            giveUp(why)
            return null
        }

        /** Said to the PC so it lets the request go now, best effort, and never waited on. */
        private fun giveUp(why: String) {
            Log.i("DeskIT", "relay: a stream let go ($why)")
            val s = sealed { uid, key -> RelayWire.cancel(key, uid, l.me, target, rid) }
            if (s != null && l.alive) {
                try {
                    l.ws.send(RelayWire.broadcast(l.uid, s, l.nextRef(), l.joinRef))
                } catch (e: IOException) {
                    // the request expires on the PC by itself
                }
            }
            release()
        }

        private fun release() {
            if (released) return
            released = true
            for ((ref, _) in out) l.acks.remove(ref)
            out.clear()
            l.replies.remove(rid)
            l.inFlight.decrementAndGet()
            l.lastUse = SystemClock.elapsedRealtime()
        }

        override fun cancel() {
            // never on the caller's thread: the keyboard hiding comes here on the main one
            thread(name = "relay-stream-cancel") {
                synchronized(this) {
                    if (!released) giveUp("cancelled")
                }
            }
        }
    }

    /** The PC's `text`, as Transcriber reads /transcribe's answer. */
    private fun result(c: Context, p: RelayWire.Piece): Transcriber.Result {
        val (status, body) = RelayWire.answer(p)
        val error = (body["error"] as? String).orEmpty().ifEmpty { "server error $status" }
        return when {
            status in 200..299 -> Transcriber.Result.Ok(
                body["text"] as? String ?: "", (body["warning"] as? String)?.ifEmpty { null },
                body["backend"] as? String ?: "", (body["seconds"] as? Number)?.toDouble() ?: 0.0,
                via = c.getString(R.string.via_account))
            status in REFUSED -> Transcriber.Result.Err(error, Transcriber.Why.REFUSED)
            else -> Transcriber.Result.Err(error)
        }
    }

    /** Transcriber's own: sending it again changes nothing. */
    private val REFUSED = setOf(400, 409, 413, 415)

    // ---- letting go ----

    /** The keyboard hid: the socket goes unless something is on its way through it. */
    fun hidden() {
        val l = line ?: return
        if (l.inFlight.get() == 0) close(l, "the keyboard hid")
    }

    /** On every road out of the account ([Traces]): the session's socket goes. */
    fun forget() {
        line?.let { close(it, "out of the account") }
        lastClosed = null
        lastTry = 0L
    }
}
