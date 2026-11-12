package io.github.deskit_app.deskit

import android.content.Context
import android.os.SystemClock
import android.util.Log
import org.json.JSONArray
import org.json.JSONException
import org.json.JSONObject
import java.io.IOException
import kotlin.concurrent.thread

/**
 * The cloud backup (PHONE_LINK_PLAN.md stage 2b, his yes to the pictures 2026-11-11):
 * when no PC of the account answers within about a second, the recording goes to the
 * person's own provider with the person's own key, and the text lands in the field.
 *
 * **On unless turned off, and seen once.** The switch is on from the start; the yes is
 * Done on the one-time screen ([BackupActivity]), or turning the switch on in
 * Settings, which is the same yes. Until one of them the keyboard is what it was. The
 * yes is the phone's own, as every gate is the device's: the desk's `cloud_audio`
 * does not reach it, and the desk shows this switch read from the phone's row.
 *
 * **The road.** [dictate] runs [Road.next]'s table: the PC road as it always was, and
 * beside it, once the table says so, the same recording to the key. The first text
 * lands ([FirstAnswer]); a later one is dropped, so text never lands twice. With the
 * switch off, no yes or no key, it is today's road and nothing else.
 *
 * **After the cloud's text lands** the recording is deleted (the keyboard's
 * `Spool.done`), and only the TEXT goes on to the PCs: sealed, as a row of the
 * account's history store, marked `phone-cloud`, and only where a PC of the account
 * keeps what was said (its row says `history_sync`). That row is the one thing this
 * phone sends without a press, and only right after the press that made it, or at
 * the next look when that try had no answer ([flush]).
 */
object Backup {
    private const val FILE = "backup"
    private const val ON = "on"
    private const val ASKED = "asked"
    private const val YES_VERSION = "yes_version"
    private const val YES_AT = "yes_at"
    private const val YES_WORDS = "yes_words"
    /** Text rows the account has not taken yet, each already sealed. Words: [Traces]. */
    private const val QUEUE = "cloud_rows"
    private const val QUEUE_MAX = 50

    /**
     * The version of the words the yes is given to: the one-time screen's sentence
     * and its price, and Settings' line. A change of words is a new version.
     */
    const val WORDS_VERSION = "phone-cloud-audio-en-2026-11-11"

    private fun sp(c: Context) = c.getSharedPreferences(FILE, Context.MODE_PRIVATE)

    /** The switch: on from the start, his call (2026-11-06). */
    fun switchOn(c: Context): Boolean = sp(c).getBoolean(ON, true)

    /** The yes, as of [WORDS_VERSION]. */
    fun consented(c: Context): Boolean = sp(c).getString(YES_VERSION, "") == WORDS_VERSION

    /** The one-time screen has had its Done. */
    fun asked(c: Context): Boolean = sp(c).getBoolean(ASKED, false)

    /** The backup may run: the switch on and the yes given. */
    fun active(c: Context): Boolean = switchOn(c) && consented(c)

    /** The words the yes was given to, for the record. */
    fun yesWords(c: Context): String = sp(c).getString(YES_WORDS, "") ?: ""

    /**
     * Done on the one-time screen: [on] is the switch as it stands there, and on is
     * the yes to [words]. Either way the screen is not shown again.
     */
    fun answer(c: Context, on: Boolean, words: String) {
        record(c, on, words, asked = true)
    }

    /** The switch in Settings: on is the yes, as on the wizard's Ready page; off takes it back. */
    fun setSwitch(c: Context, on: Boolean, words: String) {
        record(c, on, words, asked = asked(c) || on)
    }

    private fun record(c: Context, on: Boolean, words: String, asked: Boolean) {
        val e = sp(c).edit().putBoolean(ON, on).putBoolean(ASKED, asked)
        if (on) e.putString(YES_VERSION, WORDS_VERSION).putLong(YES_AT, System.currentTimeMillis())
            .putString(YES_WORDS, words)
        else e.remove(YES_VERSION).remove(YES_AT).remove(YES_WORDS)
        e.commit()
        Log.i("DeskIT", "backup: the switch is ${if (on) "on" else "off"}")
        // the PCs read the switch from this phone's row: write it again now
        val app = c.applicationContext
        thread(name = "backup-row") { Lock.republish(app) }
    }

    // ---- the road ----

    private fun classify(r: Transcriber.Result): Road.Pc = when (r) {
        is Transcriber.Result.Ok -> Road.Pc.OK
        is Transcriber.Result.Err -> when (r.why) {
            Transcriber.Why.REFUSED -> Road.Pc.REFUSED
            Transcriber.Why.UNREACHED -> Road.Pc.UNREACHED
            Transcriber.Why.BUSY -> Road.Pc.BUSY
        }
    }

    /**
     * A knock while the person speaks, so the second is spent before the release
     * and a door that answered is used at once ([Link.answeredRecently]), a ping through
     * the account beside it ([Relay.ask], stage 3), and the keys read when they are due
     * and the backup is on. True when the asking began now, so the second counts from
     * the press; false, and it counts from the release, for a PC that must still get
     * its whole second (found on the emulator, 2026-11-11: with no key read yet the
     * knock never went, and the PC up at home lost to the cloud).
     */
    fun knockAhead(c: Context): Boolean {
        if (!Link.joined(c)) return false
        val app = c.applicationContext
        if (active(app) && CloudKeys.stale(app)) thread(name = "backup-keys") { CloudKeys.refreshIfStale(app) }
        if (!Link.answeredRecently()) {
            thread(name = "backup-knock") {
                try {
                    Link.reach(app)
                } catch (e: Sealed.NotNow) {
                    // the release says so
                }
            }
            // and through the account, for a phone away from home (stage 3): the ping's
            // second is spent while the person speaks, as the knock's is
            Relay.ask(app)
        }
        return true
    }

    /** The cloud's answer as the keyboard reads one. */
    private fun asResult(c: Context, a: Cloud.Answer, p: Cloud.Provider, wav: ByteArray): Transcriber.Result =
        when (a) {
            is Cloud.Answer.Text -> {
                // the provider's wait, for the log: the line's number is the recording's length
                Log.i("DeskIT", String.format(java.util.Locale.US, "backup: %s answered in %.1f s",
                                              p.word, a.seconds))
                CloudLine.ok(a.text, c.getString(R.string.from_the_cloud, p.label), p.word, wav, a.seconds)
            }
            is Cloud.Answer.Failed -> when (a.why) {
                Cloud.Why.NO_ANSWER -> Transcriber.Result.Err(c.getString(R.string.unreachable),
                                                              Transcriber.Why.UNREACHED)
                Cloud.Why.KEY -> Transcriber.Result.Err(c.getString(R.string.why_key_refused, p.label))
                Cloud.Why.LIMIT -> Transcriber.Result.Err(c.getString(R.string.why_limit, p.label))
                Cloud.Why.OTHER -> Transcriber.Result.Err(c.getString(R.string.why_cloud, p.label, a.words))
            }
        }

    /** One try at the cloud: the key opened for this request, and once more on a refusal. */
    private fun toCloud(c: Context, p: Cloud.Provider, wav: ByteArray): Transcriber.Result = try {
        var answer = CloudKeys.use(c, p) { key -> Cloud.transcribe(c, p, key, wav) }
        if (answer is Cloud.Answer.Failed && answer.why == Cloud.Why.KEY) {
            // a key changed on a PC since this phone read the rows: read them, try once more
            try {
                CloudKeys.refresh(c)
                CloudKeys.use(c, p) { key -> Cloud.transcribe(c, p, key, wav) }?.let { answer = it }
            } catch (e: Account.Failed) {
                // the first answer stands
            }
        }
        answer?.let { asResult(c, it, p, wav) }
            ?: Transcriber.Result.Err(c.getString(R.string.unreachable), Transcriber.Why.UNREACHED)
    } catch (e: Account.Failed) {
        Transcriber.Result.Err(e.message ?: c.getString(R.string.unreachable), Transcriber.Why.UNREACHED)
    } catch (e: Sealed.NotNow) {
        Transcriber.Result.Err(Sealed.words(c, e))
    }

    /**
     * One recording, to whichever answers first: a PC of the account, or the person's
     * own key, as [Road.next] says. [askingSince] is when the asking began (the press,
     * or Send again), [toCloudNow] is told when the recording sets out for the cloud.
     * Blocking: call it from a thread.
     */
    fun dictate(c: Context, item: SpoolFiles.Item, askingSince: Long,
                toCloudNow: () -> Unit): Transcriber.Result {
        val cloudOn = active(c)
        val relayOn = Relay.usable(c)
        if (!cloudOn && !relayOn) return Link.dictate(c, item)
        val wav = try {
            item.bytes()
        } catch (e: IOException) {
            return Link.dictate(c, item)
        }
        // A key added on a PC since the last read: look, beside the PC road.
        if (cloudOn && CloudKeys.provider(c) == null && CloudKeys.stale(c)) {
            thread(name = "backup-keys") { CloudKeys.refreshIfStale(c) }
        }
        // The account's channel, if the press did not ask it (Send again, a door that
        // answered a minute ago): it is asked when the door at home gives up, below.
        val unreached = Transcriber.Result.Err(c.getString(R.string.unreachable), Transcriber.Why.UNREACHED)
        @Suppress("PLATFORM_CLASS_MAPPED_TO_KOTLIN")
        val gate = java.lang.Object()
        val first = FirstAnswer()
        var door = Road.Door.NOT_YET
        var doorAt = 0L
        var pc = Road.Pc.PENDING
        var pcResult: Transcriber.Result? = null
        var cloud = Road.Cloud.IDLE
        var cloudResult: Transcriber.Result? = null
        var run = Road.Run.IDLE
        var relayMoved = 0L
        var relayPc = Road.Pc.PENDING
        var relayResult: Transcriber.Result? = null
        var relayAsked = false
        // Set once this returns: a road that has not sent the recording yet does not now,
        // so a PC is never handed a recording whose text has nowhere to land.
        var settled = false
        val setOut = SystemClock.elapsedRealtime()
        if (relayOn && !Link.answeredRecently() && !Relay.askedSince(askingSince)) {
            Relay.ask(c)
            relayAsked = true
        } else if (relayOn && Relay.recheck(askingSince)) {
            // a long dictation: the PC said "here" at the press; is it still there, on a socket
            Relay.ask(c)
            relayAsked = true
        }
        thread(name = "backup-pc") {
            val r = Link.ask(c) { road ->
                synchronized(gate) {
                    // the relay has it, or something landed: this road sends nothing
                    if (settled || run != Road.Run.IDLE) return@ask unreached
                    if (door == Road.Door.NOT_YET) {
                        door = Road.Door.ANSWERED
                        doorAt = SystemClock.elapsedRealtime()
                    }
                    gate.notifyAll()
                }
                Transcriber.send(road, wav)
            }
            synchronized(gate) {
                pcResult = r
                // a text that comes after the cloud's has landed goes nowhere
                pc = if (r is Transcriber.Result.Ok && !first.offer("pc")) Road.Pc.UNREACHED else classify(r)
                if (door == Road.Door.NOT_YET) door = Road.Door.NOBODY
                gate.notifyAll()
            }
        }
        try {
            while (true) {
                synchronized(gate) {
                    val now = SystemClock.elapsedRealtime()
                    val p = if (cloudOn) CloudKeys.provider(c) else null
                    var view = if (relayOn) Relay.view(c, askingSince, now) else Relay.View(Road.Relay.OFF)
                    if (relayOn && !relayAsked && !Relay.askedSince(askingSince) && pc == Road.Pc.UNREACHED) {
                        // the door from a moment ago did not answer after all: ask the account now
                        Relay.ask(c)
                        relayAsked = true
                        view = Relay.View(Road.Relay.ASKING)
                    }
                    val step = Road.next(Road.Moment(active = cloudOn, keyed = p != null,
                        askedMs = now - askingSince, roadMs = now - setOut, door = door,
                        silentMs = if (door == Road.Door.ANSWERED) now - doorAt else 0L,
                        pc = pc, cloud = cloud, relay = view.state, run = run,
                        relayQuietMs = if (run == Road.Run.IDLE) 0L else now - relayMoved,
                        relayPc = relayPc))
                    when (step) {
                        Road.Step.WAIT -> gate.wait(50)
                        Road.Step.LAND_PC -> return pcResult!!
                        Road.Step.LAND_RELAY -> return relayResult!!
                        Road.Step.LAND_CLOUD -> return cloudResult!!
                        Road.Step.PC_SAYS -> return pcResult ?: relayResult ?: unreached
                        Road.Step.RELAY_SAYS -> return relayResult
                            ?: Transcriber.Result.Err(view.why.ifEmpty { c.getString(R.string.unreachable) },
                                                      Transcriber.Why.BUSY)
                        Road.Step.CLOUD_SAYS -> {
                            val said = cloudResult as? Transcriber.Result.Err
                            // the cloud not answering either says nothing the PC road did not
                            return if (said == null || said.why == Transcriber.Why.UNREACHED)
                                pcResult ?: said!! else said
                        }
                        Road.Step.RELAY -> {
                            val target = view.target!!
                            run = Road.Run.SENDING
                            relayMoved = now
                            Log.i("DeskIT", "relay: to the PC through the account, the door at home " +
                                "${door.name.lowercase()}, ${now - askingSince} ms asked")
                            thread(name = "backup-relay") {
                                val r = Relay.send(c, wav, target) { took ->
                                    synchronized(gate) {
                                        relayMoved = SystemClock.elapsedRealtime()
                                        if (took) run = Road.Run.TOOK
                                        gate.notifyAll()
                                    }
                                }
                                synchronized(gate) {
                                    relayResult = r
                                    relayPc = if (r is Transcriber.Result.Ok && !first.offer("relay"))
                                        Road.Pc.UNREACHED else classify(r)
                                    gate.notifyAll()
                                }
                            }
                        }
                        Road.Step.CLOUD -> {
                            cloud = Road.Cloud.PENDING
                            Log.i("DeskIT", "backup: to the cloud (${p!!.word}), the PC road " +
                                "${door.name.lowercase()}, the relay ${view.state.name.lowercase()}, " +
                                "${now - askingSince} ms asked")
                            thread(name = "backup-cloud") {
                                val r = toCloud(c, p, wav)
                                synchronized(gate) {
                                    cloudResult = r
                                    cloud = if (r is Transcriber.Result.Ok && first.offer("cloud"))
                                        Road.Cloud.OK else Road.Cloud.FAILED
                                    gate.notifyAll()
                                }
                            }
                            toCloudNow()
                        }
                    }
                }
            }
        } finally {
            synchronized(gate) { settled = true }
        }
    }

    // ---- the text, on to the PCs ----

    /** Does a PC of the account keep what was said? Its own row says so. No network. */
    fun pcsKeep(c: Context): Boolean = try {
        Lock.cachedDevices(c).any { it.isPc && it.link?.optBoolean("history_sync", false) == true }
    } catch (e: Account.Failed) {
        false
    }

    /**
     * The text of a dictation the cloud carried, sealed, to the account's history
     * store, where the PCs' Said pages read it, marked from the phone and from the
     * cloud. Only where a PC keeps what was said. On a thread of its own.
     */
    fun tellPcs(c: Context, text: String, provider: String, audioSeconds: Double, wipes: Int) {
        if (text.isBlank()) return
        val app = c.applicationContext
        val at = System.currentTimeMillis()
        thread(name = "backup-tell") {
            try {
                if (!pcsKeep(app)) {
                    Log.i("DeskIT", "backup: no PC keeps what was said: the text stays on the phone")
                    return@thread
                }
                val s = Account.session(app) ?: return@thread
                val device = Lock.deviceId(app, s.uid)
                val row = Lock.withKey(app) { uid, key ->
                    HistoryRow.build(key, uid, device, at, text, provider, audioSeconds)
                }
                if (wipes != Traces.wipes) return@thread
                enqueue(app, row)
                flush(app)
            } catch (e: Account.Failed) {
                Log.i("DeskIT", "backup: the text waits for the account")
            } catch (e: Sealed.NotNow) {
                Log.i("DeskIT", "backup: the text waits for the seal")
            }
        }
    }

    private fun json(r: HistoryRow.Row): JSONObject = JSONObject()
        .put("user_id", r.uid).put("device_id", r.device).put("ts", r.ts).put("kind", r.kind)
        .put("engine", r.engine).put("seconds", r.seconds).put("cipher", r.cipher)

    private fun queue(c: Context): JSONArray = try {
        JSONArray(Sealed.getText(c, QUEUE) ?: "[]")
    } catch (e: JSONException) {
        JSONArray()
    }

    @Synchronized
    private fun enqueue(c: Context, row: HistoryRow.Row) {
        val q = queue(c)
        q.put(json(row))
        while (q.length() > QUEUE_MAX) q.remove(0)
        Sealed.putText(c, QUEUE, q.toString())
    }

    /**
     * Every text row the account has not taken, oldest first: the try right after a
     * dictation, and the next look's when that one had no answer. A row of another
     * account (a sign-in since) never goes: [Traces] took it.
     */
    @Synchronized
    fun flush(c: Context) {
        val q = queue(c)
        if (q.length() == 0) return
        val s = Account.session(c) ?: return
        var sent = 0
        var stop = false
        val left = JSONArray()
        for (i in 0 until q.length()) {
            val row = q.optJSONObject(i) ?: continue
            if (row.optString("user_id") != s.uid) continue        // another account's: it goes
            if (stop) {
                left.put(row)
                continue
            }
            val r = try {
                Account.rest(c, "POST", "history?on_conflict=user_id,device_id,ts,kind", row,
                             "resolution=merge-duplicates,return=minimal")
            } catch (e: Account.Failed) {
                null
            }
            when {
                r != null && r.ok -> sent++
                r != null && r.status in 400..499 && r.status != 401 ->
                    // the row itself is what the server will not take: sent again, the same no
                    Log.w("DeskIT", "backup: the account refused a text row (${r.status}): dropped")
                else -> {
                    left.put(row)                                     // no answer: the next look
                    stop = true
                }
            }
        }
        Sealed.putText(c, QUEUE, left.toString())
        if (sent > 0) {
            Log.i("DeskIT", "backup: $sent text row(s) went to the account")
            Account.broadcast(c, "changed", JSONObject().put("device", Lock.deviceId(c, s.uid))
                .put("stores", JSONArray().put("history")))
        }
    }

    /** [flush] for a screen's look, swallowing what it says. */
    fun flushQuietly(c: Context) {
        try {
            flush(c)
        } catch (e: Sealed.NotNow) {
            // the next look
        } catch (e: Account.Failed) {
            // the next look
        }
    }

    /** On every road out of the account ([Traces]): rows not yet sent are words. */
    fun forget(c: Context) {
        Sealed.delete(c, QUEUE)
    }
}
