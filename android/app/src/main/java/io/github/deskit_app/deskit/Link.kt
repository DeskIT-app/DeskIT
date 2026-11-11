package io.github.deskit_app.deskit

import android.content.Context
import android.net.ConnectivityManager
import android.net.LinkProperties
import android.net.Network
import android.net.NetworkCapabilities
import android.os.SystemClock
import android.util.Log
import org.json.JSONException
import org.json.JSONObject
import java.io.IOException
import java.net.HttpURLConnection
import java.net.Inet4Address
import java.net.Proxy
import java.net.URL
import java.util.concurrent.LinkedBlockingQueue
import java.util.concurrent.TimeUnit
import javax.net.ssl.HttpsURLConnection
import javax.net.ssl.SSLContext
import kotlin.concurrent.thread

/**
 * The way to a PC of this account (PHONE_LINK_PLAN.md stage 1, chapter 4.1, rung
 * one): straight to it, on the home network, both ends pinned, with nobody in
 * between and no internet needed.
 *
 * **Where the PCs are** lives in the account, sealed: each PC's `link` row names
 * its certificate, its addresses and its port. [Lock] keeps those rows sealed on
 * the phone, so none of this needs the internet after the first read. They are
 * read again when they run out: nobody answered, or a PC's row names no address.
 * A row with none is a PC that said no, or has its switch off, or that wrote it
 * before the phone arrived, so it is a fact of a moment and never of the PC.
 *
 * **Which address** is the one that answered last on this network, so the common
 * case has no race at all. Otherwise everything is tried at once and the first
 * that answers wins: every address of every PC, on every network that could
 * carry it, because which of them is right is a fact about tonight's router and
 * a stale address costs nothing but a thread that gives up.
 *
 * **The race is bound to the Wi-Fi `Network`.** With mobile data on, Android
 * keeps an app off a Wi-Fi that has no internet, and "no internet needed" would
 * fail for exactly the house it is promised to (M13). So Wi-Fi and Ethernet are
 * asked for by name, and the phone's default road after them: a VPN keeps an app
 * off everything else, and a PC reached by hand may be on a routable address.
 * A connection never takes a proxy: it would be asked to reach a LAN address.
 *
 * Android can also put that Wi-Fi in the background, where binding to it fails
 * with EPERM for an app holding only ACCESS_NETWORK_STATE, and CHANGE_NETWORK_STATE
 * is what opens it. Measured on Android 14, 2026-11-07, Wi-Fi with no internet and
 * mobile data the default: not bound, ConnectException; bound, in the foreground,
 * the door; bound, in the background, EPERM without that permission and the door
 * with it, with no request for the network.
 *
 * **A PC can answer "not now"**: its model is off, or it is signed out. Then the
 * next PC of the account gets the turn, and the sentence that comes back, if none
 * takes it, is that PC's own.
 *
 * **The old road** is the pasted address and token, beside all this until stage 6:
 * [Pasted], and tried when no door answers.
 *
 * [Sealed.NotNow] here is a phone that cannot open its own rows right now, locked
 * above all. It is never a sign-in problem and nothing here treats it as one: the
 * recording waits, and the screen says to unlock.
 *
 * Never logged: an address, a port, a pin, a name.
 */
object Link {
    /** Sealed, because it says where somebody's PC is. Goes with the words: [forget]. */
    private const val ROUTES = "link_routes"
    /** Networks remembered: a phone sees few homes. */
    private const val ROUTES_KEPT = 8

    /** Remembered, a LAN answers in milliseconds: this is what a stale address costs. */
    private const val QUICK_MS = 1200
    /** The race's connect: a slow Wi-Fi's first packet. All a dead address ever costs. */
    private const val KNOCK_MS = 2500
    /**
     * Once a socket is up somebody is there, and a process just started pays for
     * TLS and Keystore here: 1.1 s measured on the emulator, cold. "Nobody home"
     * must not be a slow phone's first handshake.
     */
    private const val ANSWER_MS = 6000
    private const val RACE_MS = 7000L
    /** Threads are cheap and this is bounded by what one row holds. */
    private const val MOST_KNOCKS = 16
    /** How long a dictation waits for the account's rows. A dead network must not hold it. */
    private const val READ_WAIT_MS = 5000L
    private const val READ_EVERY_MS = 30_000L
    /** With a pasted line beside it, a door that just did not answer is not asked again yet. */
    private const val NOBODY_MS = 20_000L
    /**
     * A door that answered this recently is used with no knock first: a knock is a
     * whole TLS connection, and sentence after sentence pays for it each time. One
     * that fails after all is knocked on before it is given up.
     */
    private const val FRESH_MS = 60_000L

    /** An address, and never a name: a row names no host to look up. */
    private val IP = Regex("""(\d{1,3}\.){3}\d{1,3}|[0-9a-fA-F]{0,4}(:[0-9a-fA-F]{0,4}){2,7}""")
    private val PIN = Regex("[0-9a-f]{64}")

    /** One way to one PC: makes connections that have not connected yet. */
    abstract class Road(val unreached: String) {
        abstract val connectMs: Int
        /** How long a question that takes no thought gets. */
        abstract val readMs: Int
        abstract fun open(path: String): HttpURLConnection
        /** What this road says about who is asking. */
        open fun prove(conn: HttpURLConnection) {}
    }

    /** The pasted address and token: the road beside the door until stage 6. */
    class Pasted(private val url: String, private val token: String, unreached: String) :
        Road(unreached) {
        override val connectMs = 15000
        override val readMs = 15000

        override fun open(path: String) = URL(url + path).openConnection() as HttpURLConnection

        override fun prove(conn: HttpURLConnection) =
            conn.setRequestProperty("Authorization", "Bearer $token")
    }

    /** A PC of the account, its row opened. */
    class Pc(val id: String, val pin: String, val addrs: List<String>, val port: Int,
             val wordsSync: Boolean) {
        val sig: String get() = "$id|$pin|$port|$addrs"
    }

    /** A network a connection can be bound to. [handle] null: the phone's default road. */
    private class Net(val handle: Network?, val key: String, val word: String)

    /** One address of one PC on one network. No bearer: the handshake is the proof. */
    private class Door(val pc: Pc, val addr: String, val net: Net, private val ssl: SSLContext,
                       override val connectMs: Int, unreached: String,
                       val fresh: Boolean = false) : Road(unreached) {
        override val readMs = ANSWER_MS

        /** Who this is, wherever it was made: the same PC, address, port and network. */
        val mark: String get() = "${net.key}|${pc.id}|$addr|${pc.port}|${pc.pin}"

        fun quickly(ms: Int, fresh: Boolean = false) = Door(pc, addr, net, ssl, ms, unreached, fresh)

        override fun open(path: String): HttpURLConnection {
            val url = URL("https", if (':' in addr) "[$addr]" else addr, pc.port, path)
            val raw = net.handle?.openConnection(url, Proxy.NO_PROXY)
                ?: url.openConnection(Proxy.NO_PROXY)
            return (raw as HttpsURLConnection).apply {
                sslSocketFactory = ssl.socketFactory
                hostnameVerifier = Pin.Names(pc.pin)
                instanceFollowRedirects = false
                // The door answers HTTP/1.0 and hangs up, and each Network handle has
                // a pool of its own that keeps the socket it can never use again: 24
                // half-closed sockets after ten dictations, measured, until this.
                setRequestProperty("Connection", "close")
            }
        }
    }

    private fun unreached(c: Context) = c.getString(R.string.unreachable)

    // ---- may it ask at all ----

    /** A device of the account, with a session and its key. No network and no Keystore. */
    fun joined(c: Context): Boolean = Lock.holdsKey(c) && Account.held(c)

    /** The pasted line, if there is one. */
    fun pasted(c: Context): Pasted? {
        val token = Prefs.token(c)
        return if (token.isEmpty()) null else pasted(c, Prefs.url(c), token)
    }

    fun pasted(c: Context, url: String, token: String) = Pasted(url, token, unreached(c))

    /**
     * Can this phone ask a PC anything? What every door of the keyboard asks
     * first. Quick, and on any thread: it says nothing about whether a PC answers.
     */
    fun ready(c: Context): Boolean = joined(c) || Prefs.token(c).isNotEmpty()

    /** What to do about not being [ready]: one of Home's steps, which a tap leads to. */
    fun step(c: Context): Int = when {
        !Account.held(c) -> R.string.step_sign_in
        Lock.lockChanged(c) -> R.string.step_changed
        else -> R.string.step_approve
    }

    // ---- the account's PCs ----

    private fun pcOf(d: Lock.Device): Pc? {
        val link = d.link ?: return null
        if (!d.isPc || link.optString("kind") != "pc" || !PIN.matches(d.cert)) return null
        val addrs = link.optJSONArray("addrs")
        val list = (0 until (addrs?.length() ?: 0))
            .mapNotNull { addrs?.optString(it) }
            .filter { IP.matches(it) }
        return Pc(d.id, d.cert, list, link.optInt("port", 0), link.optBoolean("words_sync", false))
    }

    /** The account's PCs, from the rows on this phone. No network. */
    fun pcs(c: Context): List<Pc> = try {
        Lock.cachedDevices(c).mapNotNull { pcOf(it) }
    } catch (e: Account.Failed) {
        emptyList()
    }

    private var lastRead = 0L

    /** The account's rows again, for at most [READ_WAIT_MS]. True when they came. */
    private fun read(c: Context): Boolean {
        val now = SystemClock.elapsedRealtime()
        synchronized(this) {
            if (lastRead != 0L && now - lastRead < READ_EVERY_MS) return false
            lastRead = now
        }
        val reader = thread(name = "link-read") {
            try {
                Lock.devices(c)
            } catch (e: Account.Failed) {
                Log.i("DeskIT", "link: the account's rows were not read")
            } catch (e: Sealed.NotNow) {
                Log.i("DeskIT", "link: the account's rows wait for the seal")
            }
        }
        reader.join(READ_WAIT_MS)
        return !reader.isAlive
    }

    // ---- the networks ----

    private fun keyOf(cm: ConnectivityManager, n: Network?): String {
        val lp: LinkProperties = n?.let { cm.getLinkProperties(it) } ?: return "none"
        val gateway = lp.routes.firstOrNull { it.isDefaultRoute }?.gateway?.hostAddress.orEmpty()
        val own = lp.linkAddresses.firstOrNull { it.address is Inet4Address }
        return "$gateway/${own?.prefixLength ?: 0}"
    }

    /**
     * What a connection could be bound to, Wi-Fi first. A network has no name an
     * app may read without the location permission, and a home's router and
     * prefix tell one home from another well enough: two homes that share them
     * only cost a race.
     */
    private fun nets(c: Context): List<Net> {
        val cm = c.getSystemService(ConnectivityManager::class.java)
        val out = ArrayList<Net>()
        @Suppress("DEPRECATION")
        for (n in cm.allNetworks) {
            val caps = cm.getNetworkCapabilities(n) ?: continue
            val word = when {
                caps.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) -> "wifi"
                caps.hasTransport(NetworkCapabilities.TRANSPORT_ETHERNET) -> "ethernet"
                else -> continue
            }
            out.add(Net(n, "$word|${keyOf(cm, n)}", word))
        }
        val active = cm.activeNetwork
        if (out.none { it.handle == active }) out.add(Net(null, "default|${keyOf(cm, active)}", "default"))
        return out
    }

    /**
     * The phone is on no Wi-Fi, and has no pasted line, which goes over any network:
     * then, when nobody answers, the phone is the thing to fix, and the keyboard says
     * so (the owner, 2026-11-10). Wi-Fi or Ethernet, the networks [nets] binds a door
     * to, and never a VPN's network, which can report the transport under it. Quick,
     * on any thread, and nothing about a PC: the doors are still tried on the default
     * road, for a PC with an address that road reaches.
     */
    fun noWifi(c: Context): Boolean {
        if (pasted(c) != null) return false
        return try {
            val cm = c.getSystemService(ConnectivityManager::class.java) ?: return false
            @Suppress("DEPRECATION")
            NoAnswer.offLocal(cm.allNetworks.mapNotNull { n ->
                cm.getNetworkCapabilities(n)?.let {
                    NoAnswer.Net(wifi = it.hasTransport(NetworkCapabilities.TRANSPORT_WIFI),
                                 ethernet = it.hasTransport(NetworkCapabilities.TRANSPORT_ETHERNET),
                                 vpn = it.hasTransport(NetworkCapabilities.TRANSPORT_VPN))
                }
            })
        } catch (e: RuntimeException) {
            false                   // a phone that cannot tell is not said to be off its Wi-Fi
        }
    }

    // ---- what answered last ----

    private var routes: JSONObject? = null

    private fun routes(c: Context): JSONObject = routes ?: try {
        JSONObject(Sealed.getText(c, ROUTES) ?: "{}")
    } catch (e: JSONException) {
        JSONObject()
    }.also { routes = it }

    /** [wipes]: a wipe that has come since takes this answer with it. */
    @Synchronized
    private fun remember(c: Context, door: Door, wipes: Int) {
        if (wipes != Traces.wipes) return
        try {
            val all = routes(c)
            val was = all.optJSONObject(door.net.key)
            if (was?.optString("device") == door.pc.id && was.optString("addr") == door.addr) return
            all.remove(door.net.key)
            all.put(door.net.key, JSONObject().put("device", door.pc.id).put("addr", door.addr))
            while (all.length() > ROUTES_KEPT) all.remove(all.keys().next())
            Sealed.putText(c, ROUTES, all.toString())
        } catch (e: Sealed.NotNow) {
            // the next one that answers writes it: a door that answered is no less found
        }
    }

    /** The door that answered last on a network it could be reached on now, if it stands. */
    @Synchronized
    private fun remembered(c: Context, doors: List<Door>): Door? = try {
        val all = routes(c)
        doors.firstOrNull {
            val r = all.optJSONObject(it.net.key)
            r != null && r.optString("device") == it.pc.id && r.optString("addr") == it.addr
        }
    } catch (e: Sealed.NotNow) {
        null
    }

    /** On every road out of the account: [Traces]. Where the PCs are goes with the words. */
    @Synchronized
    fun forget(c: Context) {
        routes = null
        lastRead = 0L
        nobodyUntil = 0L
        answered = null
        Sealed.delete(c, ROUTES)
        Lock.dropRows(c)
    }

    // ---- finding a PC ----

    private fun doors(c: Context, pcs: List<Pc>, nets: List<Net>): List<Door> {
        val s = Account.session(c) ?: return emptyList()
        val mine = ClientKey.forDoor(c, Lock.deviceId(c, s.uid)) ?: return emptyList()
        val out = ArrayList<Pair<Int, Door>>()
        for (pc in pcs) {
            if (pc.port !in 1..65535) continue
            val ssl = Pin.context(Pin.Trust(pc.pin), mine)
            for ((rank, addr) in pc.addrs.withIndex()) for (net in nets) {
                out.add(Pair(rank, Door(pc, addr, net, ssl, KNOCK_MS, unreached(c))))
            }
        }
        // Each PC's best address before anyone's second: [MOST_KNOCKS] must not
        // leave a PC out for the sake of another's fifth adapter.
        return out.sortedBy { it.first }.map { it.second }
    }

    /** The door that answered last, and when, in this process. */
    @Volatile private var answered: Pair<String, Long>? = null

    /** A door answered in the last minute, in this process: the next find is immediate. */
    fun answeredRecently(): Boolean =
        answered?.let { SystemClock.elapsedRealtime() - it.second < FRESH_MS } ?: false

    private fun heard(door: Door) {
        answered = Pair(door.mark, SystemClock.elapsedRealtime())
    }

    private fun answers(door: Door): Boolean = (Transcriber.health(door) != null).also {
        if (it) heard(door)
    }

    /** Everything at once, and the first that answers. */
    private fun race(doors: List<Door>): Door? {
        val runners = doors.take(MOST_KNOCKS)
        if (runners.isEmpty()) return null
        val finish = LinkedBlockingQueue<Any>()
        for (d in runners) thread(name = "link-knock") {
            finish.put(if (answers(d)) d else Unit)
        }
        val end = SystemClock.elapsedRealtime() + RACE_MS
        repeat(runners.size) {
            val left = end - SystemClock.elapsedRealtime()
            if (left <= 0) return null
            val got = finish.poll(left, TimeUnit.MILLISECONDS) ?: return null
            if (got is Door) return got
        }
        return null
    }

    /**
     * A PC that answers, leaving out [skip]: first the address that answered last,
     * then all of them, then, if the rows might have moved, all of them again. A
     * row with no address, or no row yet, is a race of nobody and the same read.
     */
    private fun find(c: Context, skip: Set<String>, wipes: Int): Door? {
        val pcs = pcs(c)
        val nets = nets(c)
        val doors = doors(c, pcs, nets).filter { it.pc.id !in skip }
        remembered(c, doors)?.let { last ->
            val when_ = answered?.takeIf { it.first == last.mark }?.second
            if (when_ != null && SystemClock.elapsedRealtime() - when_ < FRESH_MS) {
                Log.i("DeskIT", "link: the address from a moment ago, on ${last.net.word}")
                return last.quickly(QUICK_MS, fresh = true)
            }
            val it = last.quickly(QUICK_MS)
            if (answers(it)) {
                Log.i("DeskIT", "link: the address from last time answered, on ${it.net.word}")
                return it
            }
        }
        if (wipes != Traces.wipes) return null
        val t0 = SystemClock.elapsedRealtime()
        race(doors)?.let { return won(c, it, t0, wipes) }
        // Nobody answered, and the rows may say why: an address written since, a
        // new certificate, a PC this phone has not read yet.
        if (wipes != Traces.wipes || !read(c)) return null
        val fresh = pcs(c)
        if (fresh.map { it.sig } == pcs.map { it.sig }) return null
        return race(doors(c, fresh, nets).filter { it.pc.id !in skip })?.let { won(c, it, t0, wipes) }
    }

    private fun won(c: Context, door: Door, t0: Long, wipes: Int): Door {
        Log.i("DeskIT", "link: a race, won on ${door.net.word} in " +
            "${SystemClock.elapsedRealtime() - t0} ms")
        remember(c, door, wipes)
        return door
    }

    @Volatile private var nobodyUntil = 0L

    /**
     * Every road there is, best first, until [stop] says that is enough: true when
     * it is, false when the PC answered and cannot, null when nothing answered. A
     * PC that answered and cannot (its model off, say) is left out of what comes
     * next at once: sent the same recording again, it would only say no again. One
     * that did not answer is left out too, unless it was the door from a moment
     * ago, which is knocked on before it is given up. [Sealed.NotNow] only when
     * there was no other road to take.
     */
    private inline fun roads(c: Context, stop: (Road) -> Boolean?) {
        val wipes = Traces.wipes
        val pasted = pasted(c)
        var sealed: Sealed.NotNow? = null
        val quiet = pasted != null && SystemClock.elapsedRealtime() < nobodyUntil
        if (joined(c) && !quiet) {
            try {
                val skip = HashSet<String>()
                while (true) {
                    if (wipes != Traces.wipes) return
                    val door = find(c, skip, wipes)
                    if (door == null) {
                        if (skip.isEmpty()) nobodyUntil = SystemClock.elapsedRealtime() + NOBODY_MS
                        break
                    }
                    val said = stop(door)
                    if (said == true) {
                        heard(door)
                        return
                    }
                    if (said == null && door.fresh) {
                        answered = null             // knock first, the next time round
                        continue
                    }
                    skip.add(door.pc.id)
                }
            } catch (e: Sealed.NotNow) {
                sealed = e
            }
        }
        if (wipes != Traces.wipes) return
        if (pasted != null) {
            stop(pasted)
            return
        }
        sealed?.let { throw it }
    }

    // ---- asking ----

    /**
     * Which DeskIT answers, or null when nobody does. Blocking. [Sealed.NotNow] from
     * a phone that cannot look, which says nothing about the PC.
     */
    fun reach(c: Context): String? {
        var got: String? = null
        roads(c) { road ->
            got = Transcriber.health(road)
            if (got != null) true else null
        }
        return got
    }

    /** What the PC knows about keyboard builds. Null when nobody answered. Blocking. */
    fun versions(c: Context): Transcriber.Versions? {
        var got: Transcriber.Versions? = null
        try {
            roads(c) { road ->
                got = Transcriber.versions(road)
                if (got != null) true else null
            }
        } catch (e: Sealed.NotNow) {
            return null
        }
        return got
    }

    /** [Transcriber.Result]'s best answer from the first PC that gives one. Blocking. */
    fun ask(c: Context, work: (Road) -> Transcriber.Result): Transcriber.Result {
        var best: Transcriber.Result.Err? = null
        var done: Transcriber.Result? = null
        try {
            roads(c) { road ->
                var r = work(road)
                if (road is Pasted && r is Transcriber.Result.Err && r.why == Transcriber.Why.UNREACHED &&
                    Transcriber.refused(road)) {
                    r = Transcriber.Result.Err(Transcriber.BAD_TOKEN)
                }
                val moveOn = r is Transcriber.Result.Err && r.why != Transcriber.Why.REFUSED
                if (!moveOn) {
                    done = r
                } else if (best == null || best?.why == Transcriber.Why.UNREACHED) {
                    best = r as Transcriber.Result.Err
                }
                if (!moveOn) true
                else if ((r as Transcriber.Result.Err).why == Transcriber.Why.UNREACHED) null
                else false
            }
        } catch (e: Sealed.NotNow) {
            return Transcriber.Result.Err(Sealed.words(c, e), Transcriber.Why.BUSY)
        }
        return done ?: best ?: Transcriber.Result.Err(unreached(c), Transcriber.Why.UNREACHED)
    }

    /** One recording, to whichever PC takes it. */
    fun dictate(c: Context, item: SpoolFiles.Item): Transcriber.Result {
        val wav = try {
            item.bytes()
        } catch (e: IOException) {
            return Transcriber.Result.Err(unreached(c), Transcriber.Why.REFUSED)
        }
        return ask(c) { Transcriber.send(it, wav) }
    }

    /** The second reading's proposals, or null when no PC could be asked. Blocking. */
    fun proposals(c: Context): List<Transcriber.Proposal>? {
        var got: List<Transcriber.Proposal>? = null
        try {
            roads(c) { road ->
                got = Transcriber.reviewPending(road)
                if (got != null) true else null
            }
        } catch (e: Sealed.NotNow) {
            return null
        }
        return got
    }
}

/**
 * What the keyboard's line says of a try nobody answered, decided when the line is
 * drawn, so that it is never a fact of a network the phone has since left. Apart
 * from [Link], so the JVM can hold it with nothing of Android's in it.
 */
object NoAnswer {
    /** One network as Android describes it: what carries it, and whether it is a VPN's. */
    class Net(val wifi: Boolean, val ethernet: Boolean, val vpn: Boolean)

    /** None of [nets] is one a door at home could be reached on. */
    fun offLocal(nets: List<Net>): Boolean = nets.none { !it.vpn && (it.wifi || it.ethernet) }

    enum class Say {
        /** The phone is on no Wi-Fi now: whatever the try met, that is the phone's to fix. */
        NO_WIFI,
        /** On a Wi-Fi when it was tried and now, and nobody answered. */
        NO_ANSWER,
        /** Tried off any Wi-Fi and on one now: the try says nothing about the PC. */
        NOT_SENT,
    }

    /** [offThen]: the try was made with the phone on no Wi-Fi. [offNow]: it is on none now. */
    fun say(offThen: Boolean, offNow: Boolean): Say = when {
        offNow -> Say.NO_WIFI
        offThen -> Say.NOT_SENT
        else -> Say.NO_ANSWER
    }
}
