package io.github.deskit_app.deskit

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.util.Log
import java.security.Signature
import kotlin.concurrent.thread

/**
 * Debug builds only: can this phone open what it sealed, right now, and can it
 * sign? A receiver runs with the screen locked, which no Activity here does, so
 * it is how "a stolen, locked phone cannot use it" gets tested and not assumed.
 *
 *   adb shell am broadcast -n <package>/.ProbeReceiver
 *
 * One line in the log and nothing else: it says whether, never what.
 *
 * Also what a person leaves behind, put there for the flows to watch it go: a
 * sentence in Said and a pasted line (`--es say`, `--es url`, `--es token`), and
 * what only a running keyboard holds (`--es ime plant|read|now|late`). The
 * keyboard's fields are private and an emulator has no voice to fill them with,
 * so this reaches the live service by reflection, as LeakCanary does.
 *
 * And two calls a locked phone can be caught making, for a receiver runs under
 * the lock screen: one account read (`--es rest 1`), and a dictation on the old
 * road (`--es dictate 1`), which takes the pasted line and no session.
 *
 * And the road to the PC, which a flow cannot reach by what is on screen, every
 * one the real path: `--es link reach|dictate|keep|prune|sweep|job|count|pcs|soft|plant`.
 * The recording is a second of silence, a real WAV, which the PC's real to_wav reads.
 * `try:<port>` is one raw connect on each network, with nothing of ours in the way.
 * `job` is the sweep JobScheduler holds, as JobScheduler holds it.
 *
 * `--es ime fail:locked|keystore` hands the running keyboard the answer a locked
 * phone's road gives, through its own deliver: the one failure an emulator's
 * keyboard cannot be in front of for real, because a locked phone shows none.
 */
class ProbeReceiver : BroadcastReceiver() {

    override fun onReceive(c: Context, intent: Intent) {
        intent.getStringExtra("ime")?.let {
            keyboard(c, it)
            return
        }
        if (intent.hasExtra("wipe")) {
            Traces.wipe(c)
            Log.i("DeskIT", "probe: wiped")
            return
        }
        if (intent.hasExtra("rest")) {
            val done = goAsync()
            thread {
                val said = try {
                    "${Account.rest(c, "GET", "profiles?select=lock_id&limit=1").status}"
                } catch (e: Account.Failed) {
                    "failed"
                } catch (e: Sealed.NotNow) {
                    "notnow"
                }
                Log.i("DeskIT", "probe: rest=$said")
                done.finish()
            }
            return
        }
        if (intent.hasExtra("dictate")) {
            val done = goAsync()
            thread {
                val r = Link.pasted(c)?.let { Transcriber.send(it, ByteArray(64)) }
                Log.i("DeskIT", "probe: dictated=${r is Transcriber.Result.Ok}")
                done.finish()
            }
            return
        }
        intent.getStringExtra("link")?.let { what ->
            // Not goAsync: a door can take as long as a door takes, and a broadcast
            // that outlives its queue's patience is killed for it. The line is the answer.
            val app = c.applicationContext
            thread {
                val t0 = System.nanoTime()
                val said = try {
                    link(app, what)
                } catch (e: Sealed.NotNow) {
                    "notnow locked=${e.locked}"
                }
                Log.i("DeskIT", "probe: link $said ms=${(System.nanoTime() - t0) / 1_000_000}")
            }
            return
        }
        if (intent.hasExtra("say") || intent.hasExtra("url")) {
            intent.getStringExtra("url")?.let {
                Prefs.save(c, it, intent.getStringExtra("token").orEmpty(), false)
            }
            intent.getStringExtra("say")?.let { Prefs.addSaid(c, it, Traces.wipes) }
            Log.i("DeskIT", "probe: left")
            return
        }
        val done = goAsync()
        val posts = intent.getIntExtra("posts", 0)
        if (posts > 0) {
            // Many real POSTs in a row: a transport failure a flow meets once in
            // a hundred requests shows up here, by class, in the log.
            thread {
                val gap = intent.getLongExtra("gap", 0)
                repeat(posts) {
                    Account.broadcast(c, "stress", org.json.JSONObject().put("i", it))
                    if (gap > 0) Thread.sleep(gap)
                }
                Log.i("DeskIT", "probe: posts done")
                done.finish()
            }
            return
        }
        // What the keyboard pays at its first start in a process: run this right
        // after a kill, or it reads the cache.
        val t0 = System.nanoTime()
        Skin.font(c)
        Skin.fontBold(c)
        val fonts = (System.nanoTime() - t0) / 1_000_000
        thread {
            val sealed = try {
                if (Sealed.get(c, "session") == null) "none" else "opened"
            } catch (e: Sealed.NotNow) {
                "notnow"
            }
            val signs = try {
                val alias = java.security.KeyStore.getInstance("AndroidKeyStore")
                    .apply { load(null) }
                    .aliases().toList().firstOrNull { it.startsWith("deskit.client.") }
                val key = alias?.let {
                    java.security.KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
                        .getKey(it, null) as java.security.PrivateKey
                }
                if (key == null) "none" else {
                    Signature.getInstance("NONEwithECDSA").run {
                        initSign(key)
                        update(ByteArray(32))
                        sign()
                    }
                    "signed"
                }
            } catch (e: Exception) {
                "refused"
            }
            Log.i("DeskIT", "probe: sealed=$sealed signs=$signs " +
                "locked=${Sealed.locked(c)} lockable=${Sealed.lockable(c)} fonts=${fonts}ms")
            done.finish()
        }
    }

    private fun silence(): ByteArray {
        val pcm = ByteArray(Recorder.SAMPLE_RATE * 2)
        val out = java.io.ByteArrayOutputStream()
        fun i32(v: Int) = out.write(byteArrayOf(v.toByte(), (v shr 8).toByte(),
                                                (v shr 16).toByte(), (v shr 24).toByte()))
        fun i16(v: Int) = out.write(byteArrayOf(v.toByte(), (v shr 8).toByte()))
        out.write("RIFF".toByteArray()); i32(36 + pcm.size)
        out.write("WAVE".toByteArray())
        out.write("fmt ".toByteArray()); i32(16); i16(1); i16(1)
        i32(Recorder.SAMPLE_RATE); i32(Recorder.SAMPLE_RATE * 2); i16(2); i16(16)
        out.write("data".toByteArray()); i32(pcm.size)
        out.write(pcm)
        return out.toByteArray()
    }

    private fun link(c: Context, what: String): String = when (what) {
        "reach" -> "reach=" + (Link.reach(c) ?: "nobody")
        "keep" -> Spool.keep(c, silence()).let {
            Spool.free(c, it)
            "kept=${it.file != null} dropped=${it.dropped}"
        }
        "dictate" -> {
            val item = Spool.keep(c, silence())
            when (val r = Link.dictate(c, item)) {
                is Transcriber.Result.Ok -> {
                    Spool.done(c, item)
                    "dictated=${r.text}"
                }
                is Transcriber.Result.Err -> {
                    Spool.free(c, item)
                    "refused=${r.why} ${r.message}"
                }
            }
        }
        "prune" -> "gone=${Spool.prune(c)}"
        "sweep" -> {
            Spool.sweepLater(c)
            "asked"
        }
        "job" -> {
            val j = c.getSystemService(android.app.job.JobScheduler::class.java).getPendingJob(1)
            if (j == null) "job=none"
            else "job=${j.service.className.substringAfterLast('.')} wait=${j.minLatencyMillis} " +
                "network=${j.networkType}"
        }
        "parts" -> {
            // Where a dictation's time goes, one piece at a time.
            fun ms(t: Long) = (System.nanoTime() - t) / 1_000_000
            val wav = silence()
            var t = System.nanoTime()
            val item = Spool.keep(c, wav)
            val keep = ms(t)
            t = System.nanoTime()
            val pcs = Link.pcs(c).size
            val read = ms(t)
            t = System.nanoTime()
            val knock = Link.reach(c)
            val reach = ms(t)
            t = System.nanoTime()
            val r = Link.dictate(c, item)
            val all = ms(t)
            Spool.done(c, item)
            "parts keep=$keep rows=$read($pcs) knock=$reach($knock) dictate=$all ok=${r is Transcriber.Result.Ok}"
        }
        "plant" -> {
            Sealed.putText(c, "link_routes", "{}")
            Sealed.putText(c, "device_rows", "[]")
            "planted"
        }
        "count" -> "waiting=${Spool.files(c).items().size} all=${Spool.files(c).count()}"
        "pcs" -> "pcs=" + Link.pcs(c).joinToString(";") { "${it.addrs.size}:${it.wordsSync}" }
        "soft" -> {
            val s = Account.session(c)
            if (s != null) ClientKey.fallBack(c, Lock.deviceId(c, s.uid))
            "soft=${Lock.look(c).javaClass.simpleName}"
        }
        "recheck" -> {
            // Android's own check, again, on every network: a real answer in place of
            // switching radios off and on, which an emulator's mobile data does not survive.
            val cm = c.getSystemService(android.net.ConnectivityManager::class.java)
            @Suppress("DEPRECATION")
            for (n in cm.allNetworks) {
                val validated = cm.getNetworkCapabilities(n)
                    ?.hasCapability(android.net.NetworkCapabilities.NET_CAPABILITY_VALIDATED) == true
                // Android looks again only when told the opposite of what it believes.
                cm.reportNetworkConnectivity(n, !validated)
            }
            "rechecked"
        }
        else -> when {
            what.startsWith("try:") -> tryPort(c, what.substring(4).toInt())
            what.startsWith("tls:") -> tls(c, what.substring(4).toInt())
            else -> "what=$what"
        }
    }

    /**
     * One raw connect per network and one on the default road: what M13 turns on,
     * with nothing of ours in between.
     */
    private fun tryPort(c: Context, port: Int): String {
        val cm = c.getSystemService(android.net.ConnectivityManager::class.java)
        fun one(net: android.net.Network?): String = try {
            java.net.Socket().use { s ->
                net?.bindSocket(s)
                s.connect(java.net.InetSocketAddress("10.0.2.2", port), 2000)
                "ok"
            }
        } catch (e: java.io.IOException) {
            "${e.javaClass.simpleName}(${e.message?.take(60)})"
        }
        fun all(): String {
            @Suppress("DEPRECATION")
            val nets = cm.allNetworks.map { n ->
                val caps = cm.getNetworkCapabilities(n)
                val word = if (caps?.hasTransport(android.net.NetworkCapabilities.TRANSPORT_WIFI) == true)
                    "wifi" else "other"
                val fg = caps?.hasCapability(19) == true
                "$word fg=$fg ${if (n == cm.activeNetwork) "default" else "-"} ${one(n)}"
            }
            return "$nets unbound ${one(null)}"
        }
        return all()
    }

    /** One TLS handshake by hand, then one GET by HttpsURLConnection: where a knock's time goes. */
    private fun tls(c: Context, port: Int): String {
        val s = Account.session(c) ?: return "no session"
        val mine = ClientKey.forDoor(c, Lock.deviceId(c, s.uid)) ?: return "no key"
        val pin = Link.pcs(c).firstOrNull()?.pin ?: return "no pc"
        val ctx = Pin.context(Pin.Trust(pin), mine)
        fun ms(t: Long) = (System.nanoTime() - t) / 1_000_000
        val out = ArrayList<String>()
        repeat(3) {
            var t = System.nanoTime()
            val raw = java.net.Socket()
            raw.connect(java.net.InetSocketAddress("10.0.2.2", port), 3000)
            val tcp = ms(t)
            t = System.nanoTime()
            val tls = ctx.socketFactory.createSocket(raw, "10.0.2.2", port, true) as javax.net.ssl.SSLSocket
            tls.startHandshake()
            val shake = ms(t)
            t = System.nanoTime()
            tls.outputStream.write("GET /health HTTP/1.0\r\n\r\n".toByteArray())
            tls.outputStream.flush()
            val got = tls.inputStream.readBytes().size
            val answer = ms(t)
            tls.close()
            out.add("by hand: tcp=$tcp tls=$shake (${tls.session.protocol}) get=$answer ($got bytes)")
        }
        repeat(3) {
            val t = System.nanoTime()
            val conn = (java.net.URL("https", "10.0.2.2", port, "/health").openConnection(java.net.Proxy.NO_PROXY)
                as javax.net.ssl.HttpsURLConnection).apply {
                sslSocketFactory = ctx.socketFactory
                hostnameVerifier = Pin.Names(pin)
                setRequestProperty("Connection", "close")
            }
            val code = conn.responseCode
            conn.inputStream.readBytes()
            conn.disconnect()
            out.add("HttpsURLConnection: ${ms(t)} ms ($code)")
        }
        return out.joinToString(" | ")
    }

    private fun running(): DictationIme? = try {
        val thread = Class.forName("android.app.ActivityThread")
        val now = thread.getMethod("currentActivityThread").invoke(null)
        val all = thread.getDeclaredField("mServices").apply { isAccessible = true }.get(now)
        (all as Map<*, *>).values.firstOrNull { it is DictationIme } as DictationIme?
    } catch (e: ReflectiveOperationException) {
        Log.w("DeskIT", "probe: ${e.javaClass.simpleName}: ${e.message}")
        null
    }

    private fun held(name: String) =
        DictationIme::class.java.getDeclaredField(name).apply { isAccessible = true }

    /** A dictation coming back: [late] says it set out before the last wipe. */
    private fun comeBack(k: DictationIme, text: String, late: Boolean) {
        val mine = held("session").getInt(k)
        DictationIme::class.java.getDeclaredMethod("deliver", Transcriber.Result::class.java,
                                                   SpoolFiles.Item::class.java,
                                                   Int::class.java, Int::class.java)
            .apply { isAccessible = true }
            .invoke(k, Transcriber.Result.Ok(text), SpoolFiles.Item(null, ByteArray(8)), mine,
                    if (late) Traces.wipes - 1 else Traces.wipes)
    }

    /** Where a view is on screen, for a real finger: uiautomator cannot see a keyboard. */
    private fun at(k: DictationIme, name: String): String {
        val v = held(name).get(k) as? android.view.View ?: return ""
        val xy = IntArray(2)
        v.getLocationOnScreen(xy)
        return "$name=${xy[0] + v.width / 2},${xy[1] + v.height / 2}"
    }

    /** What a microphone with a voice in it reports: an emulator's hears nothing. */
    private fun loud(k: DictationIme) {
        val recorder = held("recorder").get(k)
        Recorder::class.java.getDeclaredField("loudest").apply { isAccessible = true }
            .setFloat(recorder, 1f)
    }

    private fun keyboard(c: Context, what: String) {
        val k = running()
        if (k == null) {
            Log.i("DeskIT", "probe: no keyboard is running")
            return
        }
        if (what.startsWith("key:")) {
            // A press on one of the small keys, the real listener.
            @Suppress("UNCHECKED_CAST")
            val keys = held("keyViews").get(k) as Map<String, android.view.View>
            keys.getValue(what.substring(4)).performClick()
            Log.i("DeskIT", "probe: pressed")
            return
        }
        if (what.startsWith("say:")) {
            // A picture of words that are not in the app yet: underscores for spaces,
            // because adb's shell splits on them.
            (held("status").get(k) as android.widget.TextView).apply {
                text = what.substring(4).replace('_', ' ')
                setTextColor(Skin.RED)
            }
            Log.i("DeskIT", "probe: said")
            return
        }
        if (what.startsWith("fail:")) {
            // What a locked phone's road answers, through the keyboard's own deliver.
            val words = Sealed.words(c, Sealed.NotNow("probe", locked = what == "fail:locked"))
            val item = Spool.keep(c, silence())
            DictationIme::class.java.getDeclaredMethod("deliver", Transcriber.Result::class.java,
                                                       SpoolFiles.Item::class.java,
                                                       Int::class.java, Int::class.java)
                .apply { isAccessible = true }
                .invoke(k, Transcriber.Result.Err(words), item, held("session").getInt(k), Traces.wipes)
            Log.i("DeskIT", "probe: failed")
            return
        }
        when (what) {
            "plant" -> {
                held("pending").set(k, "held-words")
                @Suppress("UNCHECKED_CAST")
                (held("unsaved").get(k) as ArrayList<SpoolFiles.Item>).add(SpoolFiles.Item(null, ByteArray(8)))
            }
            "now" -> comeBack(k, "landed-words", false)
            "late" -> comeBack(k, "late-words", true)
            "loud" -> loud(k)
            "where" -> {
                Log.i("DeskIT", "probe: ${at(k, "pill")} ${at(k, "status")} ${at(k, "sendKey")} " +
                    at(k, "dropKey"))
                return
            }
            "status" -> {
                fun shown(name: String) = (held(name).get(k) as? android.view.View)?.visibility == android.view.View.VISIBLE
                fun wide(name: String) = shown(name) && (held(name).get(k) as? android.widget.TextView)?.let {
                    // Cut is when the words want more room than the key was given.
                    it.paint.measureText(it.text.toString()) + it.paddingLeft + it.paddingRight > it.width + 1
                } ?: false
                val line = held("status").get(k) as? android.widget.TextView
                val d = c.resources.displayMetrics.density
                fun tall(name: String) = ((held(name).get(k) as? android.view.View)?.height ?: 0) / d
                // The keyboard is the line's row's parent: how tall it stands, in dp.
                val board = (line?.parent?.parent as? android.view.View)?.height ?: 0
                val ellipsis = line?.layout?.let { it.getEllipsisCount(it.lineCount - 1) > 0 } ?: false
                Log.i("DeskIT", "probe: status=${line?.text}" +
                    " reachable=${held("reachable").getBoolean(k)} busy=${held("busy").getBoolean(k)}" +
                    " send=${shown("sendKey")} drop=${shown("dropKey")} cut=${wide("sendKey")}" +
                    " touch=${minOf(tall("sendKey"), tall("dropKey")).toInt()} board=${(board / d).toInt()}" +
                    " ellipsis=$ellipsis lines=${line?.lineCount ?: 0}" +
                    " private=${held("privateField").getBoolean(k)} mic=${tall("pill").toInt()}")
                return
            }
        }
        @Suppress("UNCHECKED_CAST")
        val unsaved = held("unsaved").get(k) as List<SpoolFiles.Item>
        Log.i("DeskIT", "probe: ime pending=${held("pending").get(k) != null} " +
            "wav=${unsaved.isNotEmpty()} said=${Prefs.said(c).size}")
    }
}
