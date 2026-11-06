package io.github.deskit_app.deskit

import android.content.Context
import android.os.Build
import android.provider.Settings
import android.util.Log
import org.json.JSONArray
import org.json.JSONException
import org.json.JSONObject
import java.io.File
import java.net.URLEncoder
import java.security.GeneralSecurityException
import java.security.interfaces.ECPublicKey
import java.time.Instant
import java.time.OffsetDateTime
import java.time.format.DateTimeParseException
import java.util.Base64
import java.util.UUID

/**
 * The account lock on a phone: what sb.py's lock half does for a PC, for a
 * device that has no worker and no socket, and is killed whenever it pleases.
 *
 * **Joining.** A phone never makes a lock: it asks a device that holds the key.
 * In the order sb._request_pairing does it: read `lock_id`, sweep this device's
 * own open requests (two open requests from one device are twins, and nobody
 * can approve a twin), make a P-256 pair, compute the code with the lock in it,
 * write the row, post the `pairing` broadcast, and poll. The key is taken out of
 * `handed`, checked against the lock the code was made with, and kept; the row
 * goes after that, not before, because a delete that fails must not cost the key.
 *
 * **It survives the process.** A PC keeps the join's private half in memory; a
 * phone is killed while its owner walks to the PC. The private half, the request
 * and the code are sealed for the request's fifteen minutes, so the same code is
 * on screen when he is back and the answer still opens. Ten seconds after an
 * approval or two minutes after the fifteen, the same pass reads it.
 *
 * **The server decides nothing.** `lock_id` is compared on every account read. A
 * different one stops everything sealed and asks the person, with the PC's two
 * answers; a row that does not open under the account key is ignored, so the
 * server cannot add a device. The code binds the lock, so a server that lied to
 * this phone gets two different codes on two screens.
 *
 * **Leaving.** Sign out is Forget on itself: a phone is lent and sold as a PC is
 * not. It wipes the key, the certificate and the cached rows, and the next
 * sign-in is a new device. So does finding itself on the `forgotten` list. The
 * session merely ending wipes nothing: the same account back on this phone
 * needs no second Approve.
 *
 * Every state is the answer to [look], which blocks: call it from a thread. A
 * key goes into a variable here and in [Crypt], and is zeroed after use.
 */
object Lock {
    private const val HELD = "account_key"
    private const val ASIDE = "account_key_aside"
    private const val REQUEST = "join_request"
    private const val ROWS = "device_rows"
    private const val DEVICE = "device_id"
    private const val FORGOTTEN = "forgotten"
    private const val FILE = "lock"

    private const val PREF_ROW_SIG = "row_sig"
    private const val PREF_ROW_AT = "row_at"
    private const val PREF_STATE = "state"
    private const val PREF_SERVER = "changed_server"
    private const val PREF_MINE = "changed_mine"
    private const val PREF_REFUSED = "refused"
    private const val PREF_DECLINED = "declined"
    private const val PREF_REMOVED = "removed"
    private const val PREF_FORGOTTEN = "forgotten"
    private const val PREF_EMAIL = "email"

    private const val HAVE = "have"
    private const val CHANGED = "changed"

    /** sb.PAIRING_TTL_S: the migration's default too. */
    const val PAIRING_TTL_S = 15 * 60L
    /** How often a screen that waits looks again: the plan's 3 s. */
    const val POLL_MS = 3000L
    /** sb.DEVICE_SEEN_EVERY_S. */
    private const val ROW_EVERY_S = 24 * 3600L
    /** The `name` and `device_name` columns' own cap, in characters. */
    private const val NAME_MAX = 40
    private const val GENERIC_NAME = "Android phone"
    /** The protocol a phone speaks at the door. */
    private const val PROTO = 1
    /** Where the keyboard keeps recordings no PC has yet. */
    private const val SPOOL = "spool"
    private const val UNREADABLE = "Your account answered with something unreadable. Try again."

    sealed class State {
        /** Not signed in; [words] says why, when the server ended it. */
        class SignedOut(val words: String) : State()

        /** The code is being made: a moment, on a thread. */
        class Preparing(val email: String) : State()

        /** The account has no lock. A phone never makes one: a PC does. */
        class NoLock(val email: String) : State()

        /** This phone asked; both screens show [code]. */
        class Waiting(val code: String, val email: String, val word: String) : State()

        /** The PC said Not now. This phone asks again only when told to. */
        class Declined(val email: String) : State()

        /** This phone holds the key. [first]: it has only just got it. */
        class Ready(val email: String, val first: Boolean, val word: String) : State()

        /** The account's lock is not the one this phone holds. */
        class Changed(val email: String, val server: String, val mine: String,
                      val refused: Boolean) : State()

        /** Locked, or Keystore said no for now. Nothing is lost. */
        class NotNow(val words: String) : State()

        /** No answer from the account, and nothing held to carry on with. */
        class Trouble(val email: String, val words: String) : State()
    }

    /** One device of the account, its row opened. */
    class Device(val id: String, val name: String, val isPc: Boolean, val seen: Long,
                 val linked: Boolean, val cert: String, val link: JSONObject?, val mine: Boolean)

    /** Another device asking to join: [code] is computed here, never read. */
    class Asking(val id: String, val name: String, val code: String, val twins: Boolean)

    private fun sp(c: Context) = c.getSharedPreferences(FILE, Context.MODE_PRIVATE)

    private fun JSONObject.text(k: String): String = if (isNull(k)) "" else optString(k, "")

    private fun enc(s: String): String = URLEncoder.encode(s, "UTF-8")

    private fun nowS(): Long = System.currentTimeMillis() / 1000

    // ---- what is held ----

    private class Held(val uid: String, val key: ByteArray, val created: String)

    private fun read(c: Context): Held? {
        val text = Sealed.getText(c, HELD) ?: return null
        return try {
            val o = JSONObject(text)
            val key = Base64.getDecoder().decode(o.getString("key"))
            if (key.size != Crypt.KEY_BYTES) null
            else Held(o.getString("uid"), key, o.text("created"))
        } catch (e: JSONException) {
            null
        } catch (e: IllegalArgumentException) {
            null
        }
    }

    private fun write(c: Context, h: Held) {
        Sealed.putText(c, HELD, JSONObject()
            .put("uid", h.uid).put("key", Crypt.b64(h.key)).put("created", h.created)
            .put("lock", Crypt.fingerprint(h.key)).toString())
    }

    private fun aside(c: Context): JSONArray = try {
        JSONObject(Sealed.getText(c, ASIDE) ?: "{}").optJSONArray("keys") ?: JSONArray()
    } catch (e: JSONException) {
        JSONArray()
    }

    /** vault._put_aside: kept, never deleted, until this phone leaves. */
    private fun putAside(c: Context, held: Held?, forLock: String, why: String, uid: String) {
        val rows = aside(c)
        rows.put(JSONObject()
            .put("uid", held?.uid ?: uid)
            .put("key", held?.let { Crypt.b64(it.key) } ?: "")
            .put("lock", held?.let { Crypt.fingerprint(it.key) } ?: "")
            .put("created", held?.created ?: "")
            .put("aside_at", Instant.now().toString())
            .put("for_lock", forLock)
            .put("why", why))
        Sealed.putText(c, ASIDE, JSONObject().put("keys", rows).toString())
    }

    /** vault.keep: a different key here is moved aside, never written over. */
    private fun keep(c: Context, uid: String, key: ByteArray) {
        val had = read(c)
        if (had != null && !had.key.contentEquals(key)) putAside(c, had, "", "replaced", had.uid)
        write(c, Held(uid, key, Instant.now().toString()))
    }

    /** vault.confirmed: the lock he last said was his, or null. */
    private fun confirmed(c: Context, uid: String): String? {
        val rows = aside(c)
        for (i in rows.length() - 1 downTo 0) {
            val r = rows.getJSONObject(i)
            if (r.text("uid") == uid && r.text("for_lock").isNotEmpty()) return r.text("for_lock")
        }
        return null
    }

    /** The key, only while the lock says it may be used; zero it after. */
    private fun usable(c: Context, uid: String): ByteArray? {
        if (sp(c).getString(PREF_STATE, "") != HAVE) return null
        return read(c)?.takeIf { it.uid == uid }?.key
    }

    private inline fun <T> keyed(c: Context, uid: String, use: (ByteArray) -> T): T {
        val key = usable(c, uid) ?: throw Account.Failed("This phone doesn't hold your account's key.")
        try {
            return use(key)
        } catch (e: JSONException) {
            throw Account.Failed(UNREADABLE)
        } catch (e: Crypt.Refused) {
            throw Account.Failed(UNREADABLE)
        } finally {
            key.fill(0)
        }
    }

    // ---- who this device is ----

    /**
     * This device's id in [uid]'s account, minted the first time. `devices.id`
     * is a primary key across every account, so another account on this phone
     * needs another id, and a device that left starts again under a new one.
     * Sealed like the key and not a preference, because a preference can be
     * copied to a new phone by a transfer tool and a Keystore key cannot: two
     * phones under one id would write over each other's row for good.
     */
    fun deviceId(c: Context, uid: String): String {
        known?.takeIf { it.first == uid }?.let { return it.second }
        val had = try {
            JSONObject(Sealed.getText(c, DEVICE) ?: "{}")
        } catch (e: JSONException) {
            JSONObject()
        }
        val id = had.text("id").takeIf { it.isNotEmpty() && had.text("uid") == uid } ?: run {
            val fresh = UUID.randomUUID().toString()
            Sealed.putText(c, DEVICE, JSONObject().put("uid", uid).put("id", fresh).toString())
            sp(c).edit().remove(PREF_ROW_SIG).remove(PREF_ROW_AT).commit()
            fresh
        }
        known = Pair(uid, id)
        return id
    }

    /** (uid, device id): a Keystore call is not free and this is asked constantly. */
    @Volatile private var known: Pair<String, String>? = null

    /** At most [n] characters, the way Postgres counts them, never half of one. */
    fun clip(text: String, n: Int): String =
        if (text.codePointCount(0, text.length) <= n) text
        else text.substring(0, text.offsetByCodePoints(0, n)).trim()

    /**
     * The name Home shows. `Build.MODEL` reads "SM-S948B"; the phone's own name
     * needs no permission, and when a maker leaves it empty the model is what
     * there is.
     */
    fun deviceName(c: Context): String {
        val own = try {
            Settings.Global.getString(c.contentResolver, Settings.Global.DEVICE_NAME)
        } catch (e: RuntimeException) {
            null
        }
        val name = own.orEmpty().trim().ifEmpty { Build.MODEL.orEmpty().trim() }
        return clip(name.ifEmpty { GENERIC_NAME }, NAME_MAX)
    }

    private fun appVersion(c: Context): String = try {
        clip(c.packageManager.getPackageInfo(c.packageName, 0).versionName.orEmpty(), 32)
    } catch (e: Exception) {
        ""
    }

    private fun certFingerprint(der: ByteArray): String = Crypt.hex(Crypt.sha256(der))

    private fun ownCert(c: Context, uid: String): String =
        ClientKey.certificate(c, deviceId(c, uid))?.let { certFingerprint(it) }.orEmpty()

    // ---- the request ----

    private class Request(val uid: String, val id: String, val code: String, val lockId: String,
                          val expires: Long, val private: ByteArray, val point: ByteArray)

    private fun saveRequest(c: Context, r: Request) {
        Sealed.putText(c, REQUEST, JSONObject()
            .put("uid", r.uid).put("id", r.id).put("code", r.code).put("lock_id", r.lockId)
            .put("expires", r.expires).put("private", Crypt.b64(r.private))
            .put("point", Crypt.b64(r.point)).toString())
    }

    private fun loadRequest(c: Context): Request? {
        val text = Sealed.getText(c, REQUEST) ?: return null
        return try {
            val o = JSONObject(text)
            val decode = Base64.getDecoder()
            Request(o.getString("uid"), o.getString("id"), o.getString("code"),
                    o.getString("lock_id"), o.getLong("expires"),
                    decode.decode(o.getString("private")), decode.decode(o.getString("point")))
        } catch (e: JSONException) {
            null
        } catch (e: IllegalArgumentException) {
            null
        }
    }

    private fun dropRequest(c: Context) = Sealed.delete(c, REQUEST)

    private fun deleteRow(c: Context, id: String) {
        Account.rest(c, "DELETE", "pairings?id=eq.${enc(id)}")
    }

    private fun refused(r: Account.Reply): Nothing = throw Account.Failed(r.said())

    private fun postRequest(c: Context, uid: String, id: String, device: String, name: String,
                            code: String, point: ByteArray): Account.Reply =
        Account.rest(c, "POST", "pairings", JSONObject()
            .put("id", id).put("user_id", uid).put("device_id", device).put("device_name", name)
            .put("code", Crypt.codeHint(code)).put("applicant", Crypt.publicText(point)),
            "return=minimal")

    /** A new request. The code first, because the row's `code` is not null. */
    private fun ask(c: Context, s: Account.Session, remote: String,
                    progress: (State) -> Unit): State {
        progress(State.Preparing(s.email))
        val device = deviceId(c, s.uid)
        val swept = Account.rest(c, "DELETE", "pairings?device_id=eq.${enc(device)}")
        if (!swept.ok) refused(swept)
        val id = UUID.randomUUID().toString()
        val pair = Crypt.newPair()
        val point = Crypt.pointOf(pair.public as ECPublicKey)
        val code = Crypt.pairingCode(s.uid, id, point, remote)
        // Sealed before the row exists: a kill between the two leaves a request
        // that a sweep clears, and never a row whose private half is gone.
        saveRequest(c, Request(s.uid, id, code, remote, nowS() + PAIRING_TTL_S,
                               pair.private.encoded, point))
        var name = deviceName(c)
        var r = postRequest(c, s.uid, id, device, name, code, point)
        if (r.status == 400 && r.obj()?.optString("code") == "23514" && name != GENERIC_NAME) {
            // The server refuses a name it takes for a key. A phone's name is
            // whatever its owner typed; this one must not stop the join.
            name = GENERIC_NAME
            r = postRequest(c, s.uid, id, device, name, code, point)
        }
        if (!r.ok) {
            dropRequest(c)
            refused(r)
        }
        Account.broadcast(c, "pairing", JSONObject().put("device", device).put("id", id)
            .put("code", code).put("name", name))
        return State.Waiting(code, s.email, removedWord(c))
    }

    private fun removedWord(c: Context): String =
        if (sp(c).getBoolean(PREF_REMOVED, false)) c.getString(R.string.removed_word) else ""

    /** The road for a phone with no key of this lock. */
    private fun join(c: Context, s: Account.Session, remote: String,
                     progress: (State) -> Unit): State {
        if (remote.isEmpty()) {
            dropRequest(c)
            return State.NoLock(s.email)
        }
        val was = confirmed(c, s.uid)
        if (was != null && was != remote) {
            // his key is aside for a lock, and the server now names yet another
            dropRequest(c)
            return State.Changed(s.email, remote, "", isRefused(c, remote))
        }
        var req = loadRequest(c)?.takeIf { it.uid == s.uid }
        if (req != null && req.lockId != remote) {
            // the lock moved while this phone waited: that code asked for another one
            deleteRow(c, req.id)
            dropRequest(c)
            req = null
        }
        if (req != null) {
            val r = Account.rest(c, "GET", "pairings?select=handed,approved_at&id=eq.${enc(req.id)}")
            if (!r.ok) refused(r)
            val rows = r.rows()
            if (rows.length() == 0) {
                dropRequest(c)
                if (nowS() < req.expires) {
                    // Not now on the PC, or a row swept. Asked again by itself,
                    // the 3 s poll would put it straight back on his Home.
                    sp(c).edit().putBoolean(PREF_DECLINED, true).commit()
                }
                req = null
            } else {
                val handed = rows.getJSONObject(0).text("handed")
                if (handed.isNotEmpty()) {
                    val got = taken(c, req, handed, remote, was)
                    if (got != null) return got
                    req = null
                } else if (nowS() >= req.expires) {
                    dropRequest(c)
                    req = null
                } else {
                    return State.Waiting(req.code, s.email, removedWord(c))
                }
            }
        }
        if (sp(c).getBoolean(PREF_DECLINED, false)) return State.Declined(s.email)
        return ask(c, s, remote, progress)
    }

    /**
     * What was handed over, taken: Ready, or null when it did not open or is
     * not the account's key, the row gone and the request dropped either way.
     */
    private fun taken(c: Context, req: Request, handed: String, remote: String,
                      was: String?): State? {
        val aad = Crypt.aadPairing(req.uid, req.id)
        val key = try {
            Crypt.take(Crypt.privateFrom(req.private), req.point, handed, aad)
        } catch (e: Crypt.Refused) {
            Log.w("DeskIT", "lock: what was handed over did not open: asking again")
            null
        } catch (e: GeneralSecurityException) {
            Log.w("DeskIT", "lock: the request's private half is unusable: asking again")
            null
        }
        if (key == null) {
            deleteRow(c, req.id)
            dropRequest(c)
            return null
        }
        try {
            val fp = Crypt.fingerprint(key)
            if (fp != remote || fp != req.lockId || (was != null && fp != was)) {
                Log.w("DeskIT", "lock: the key handed over is not the account's: asking again")
                deleteRow(c, req.id)
                dropRequest(c)
                return null
            }
            keep(c, req.uid, key)
            sp(c).edit().putBoolean(PREF_REMOVED, false).remove(PREF_REFUSED).commit()
            val email = Account.session(c)?.email.orEmpty()
            remember(c, State.Ready(email, true, ""))
            return try {
                deleteRow(c, req.id)
                dropRequest(c)
                Account.session(c)?.let { ensureRow(c, it, key) }
                State.Ready(email, true, "")
            } catch (e: Account.Failed) {
                State.Ready(email, true, e.message.orEmpty())
            }
        } finally {
            key.fill(0)
        }
    }

    // ---- the pass ----

    private fun isRefused(c: Context, remote: String): Boolean =
        remote.isNotEmpty() && sp(c).getString(PREF_REFUSED, "") == remote

    private fun profileLock(c: Context): String {
        val r = Account.rest(c, "GET", "profiles?select=lock_id&limit=1")
        if (!r.ok) refused(r)
        val rows = r.rows()
        return if (rows.length() == 0) "" else rows.getJSONObject(0).text("lock_id")
    }

    private fun pass(c: Context, s: Account.Session, progress: (State) -> Unit): State {
        val held = read(c)?.takeIf { it.uid == s.uid }
        val remote = profileLock(c)
        if (held == null) return join(c, s, remote, progress)
        val mine = Crypt.fingerprint(held.key)
        try {
            // a process killed between keeping the key and deleting the row
            loadRequest(c)?.let {
                deleteRow(c, it.id)
                dropRequest(c)
            }
            if (remote.isEmpty()) return State.NoLock(s.email)
            if (remote != mine) return State.Changed(s.email, remote, mine, isRefused(c, remote))
            if (sp(c).contains(PREF_REFUSED)) sp(c).edit().remove(PREF_REFUSED).commit()
            remember(c, State.Ready(s.email, false, ""))
            if (onTheList(c, s.uid, readForgotten(c, s.uid, held.key))) {
                Log.w("DeskIT", "lock: this phone was forgotten: it starts again as a new device")
                wipe(c)
                sp(c).edit().putBoolean(PREF_REMOVED, true).commit()
                return join(c, s, remote, progress)
            }
            ensureRow(c, s, held.key)
            return State.Ready(s.email, false, "")
        } finally {
            held.key.fill(0)
        }
    }

    private fun remember(c: Context, st: State) {
        val e = sp(c).edit()
        when (st) {
            is State.Ready -> e.putString(PREF_STATE, HAVE).putString(PREF_EMAIL, st.email)
                .remove(PREF_DECLINED)
            is State.Changed -> e.putString(PREF_STATE, CHANGED).putString(PREF_SERVER, st.server)
                .putString(PREF_MINE, st.mine).putString(PREF_EMAIL, st.email)
            is State.Waiting -> e.putString(PREF_STATE, "").putString(PREF_EMAIL, st.email)
            is State.NoLock, is State.Declined, is State.SignedOut -> e.putString(PREF_STATE, "")
            else -> return
        }
        e.commit()
    }

    /** What the pass could not reach: carry on with what is held. */
    private fun unreached(c: Context, s: Account.Session, e: Account.Failed): State {
        val word = e.message.orEmpty()
        val gone = try {
            Account.session(c) == null
        } catch (n: Sealed.NotNow) {
            false
        }
        if (gone) return State.SignedOut(Account.goneWords(c))
        val p = sp(c)
        if (p.getString(PREF_STATE, "") == HAVE) return State.Ready(s.email, false, word)
        if (p.getString(PREF_STATE, "") == CHANGED) {
            val server = p.getString(PREF_SERVER, "").orEmpty()
            return State.Changed(s.email, server, p.getString(PREF_MINE, "").orEmpty(),
                                 isRefused(c, server))
        }
        val req = loadRequest(c)?.takeIf { it.uid == s.uid }
        if (req != null && nowS() < req.expires) return State.Waiting(req.code, s.email, word)
        return State.Trouble(s.email, word)
    }

    /**
     * Where this phone stands, from the account: one or a few requests, and on
     * a new request a code, so a second or more. Blocking. [progress] hears a
     * state worth showing before the answer is ready.
     */
    @Synchronized
    fun look(c: Context, progress: (State) -> Unit = {}): State {
        val s = try {
            Account.session(c)
        } catch (e: Sealed.NotNow) {
            return State.NotNow(Sealed.words(c, e))
        } ?: return State.SignedOut(Account.goneWords(c)).also { remember(c, it) }
        return try {
            pass(c, s, progress).also { remember(c, it) }
        } catch (e: Sealed.NotNow) {
            State.NotNow(Sealed.words(c, e))
        } catch (e: Account.Failed) {
            unreached(c, s, e)
        } catch (e: JSONException) {
            unreached(c, s, Account.Failed(UNREADABLE))
        }
    }

    /** The last thing the pass said, with no network and no Keystore: for a first paint. */
    fun lastEmail(c: Context): String = sp(c).getString(PREF_EMAIL, "").orEmpty()

    fun holdsKey(c: Context): Boolean = sp(c).getString(PREF_STATE, "") == HAVE

    /** Ask Not now's question again: Declined's button. */
    @Synchronized
    fun askAgain(c: Context, progress: (State) -> Unit = {}): State {
        sp(c).edit().remove(PREF_DECLINED).commit()
        return look(c, progress)
    }

    /**
     * The answer to "the lock changed: was it you?". It was: the key moves
     * aside with the lock he confirmed written beside it, and this phone asks
     * to join that lock and no other. It wasn't: nothing moves, the refusal is
     * kept so a restart does not ask again, and the screen points to Sign out
     * of every PC. The lock is read again first: he answered about one lock.
     */
    @Synchronized
    fun answer(c: Context, yes: Boolean, progress: (State) -> Unit = {}): State {
        val s = try {
            Account.session(c)
        } catch (e: Sealed.NotNow) {
            return State.NotNow(Sealed.words(c, e))
        } ?: return State.SignedOut("")
        return try {
            val p = sp(c)
            val asked = p.getString(PREF_SERVER, "").orEmpty()
            val remote = profileLock(c)
            if (p.getString(PREF_STATE, "") != CHANGED || remote.isEmpty() || remote != asked) {
                look(c, progress)
            } else if (!yes) {
                p.edit().putString(PREF_REFUSED, remote).commit()
                Log.w("DeskIT", "lock: the change of lock was refused: the key stays, all paused")
                State.Changed(s.email, remote, p.getString(PREF_MINE, "").orEmpty(), true)
            } else {
                val mine = read(c)?.takeIf { it.uid == s.uid }
                putAside(c, mine, remote, "the lock changed", s.uid)
                if (mine != null) Sealed.delete(c, HELD)
                p.edit().remove(PREF_STATE).remove(PREF_REFUSED).commit()
                look(c, progress)
            }
        } catch (e: Sealed.NotNow) {
            State.NotNow(Sealed.words(c, e))
        } catch (e: Account.Failed) {
            unreached(c, s, e)
        }
    }

    // ---- this device's row ----

    /**
     * sb.ensure_profile's half for a phone: the row, with its sealed `link`
     * and the session's id, when anything in it moved and at most daily
     * otherwise. It is written only under a key the lock said is the account's.
     */
    private fun ensureRow(c: Context, s: Account.Session, key: ByteArray) {
        val device = deviceId(c, s.uid)
        val der = ClientKey.ensure(c, device)
        val sid = Account.sessionId(s)
        val name = deviceName(c)
        val version = appVersion(c)
        val platform = "android-${Build.VERSION.SDK_INT}"
        val lock = Crypt.fingerprint(key)
        val sig = certFingerprint("$lock\u0000$sid\u0000$name\u0000$version\u0000$platform\u0000"
            .toByteArray() + der)
        val p = sp(c)
        if (p.getString(PREF_ROW_SIG, "") == sig && nowS() - p.getLong(PREF_ROW_AT, 0) < ROW_EVERY_S) {
            return
        }
        val link = JSONObject().put("v", 1).put("kind", "phone").put("cert", Crypt.b64(der))
            .put("proto", PROTO).put("backup", true)
        val row = JSONObject().put("id", device).put("user_id", s.uid).put("name", name)
            .put("platform", platform).put("app_version", version).put("tier", "")
            .put("last_seen", Instant.now().toString())
            .put("link", Crypt.sealText(key, link.toString(), Crypt.aadDevice(s.uid, device)))
        if (sid.isNotEmpty()) row.put("session_id", sid)
        val r = Account.rest(c, "POST", "devices?on_conflict=id", row,
                             "resolution=merge-duplicates,return=minimal")
        if (!r.ok) throw Account.Failed(r.said())
        p.edit().putString(PREF_ROW_SIG, sig).putLong(PREF_ROW_AT, nowS()).commit()
        changedDevices(c, device)
    }

    private fun changedDevices(c: Context, device: String) {
        Account.broadcast(c, "changed", JSONObject().put("device", device)
            .put("stores", JSONArray().put("devices")))
    }

    // ---- the forgotten ----

    private fun readForgotten(c: Context, uid: String, key: ByteArray): JSONArray {
        val r = Account.rest(c, "GET", "vault?select=cipher&name=eq.$FORGOTTEN")
        if (!r.ok) refused(r)
        val rows = r.rows()
        val list = if (rows.length() == 0) JSONArray() else try {
            val inside = Crypt.openText(key, rows.getJSONObject(0).text("cipher"),
                                        Crypt.aadVault(uid, FORGOTTEN))
            JSONObject(inside).optJSONArray("v") ?: JSONArray()
        } catch (e: Crypt.Refused) {
            JSONArray()                 // a row that does not open is no row
        } catch (e: JSONException) {
            JSONArray()
        }
        val names = HashSet<String>()
        for (i in 0 until list.length()) {
            val o = list.optJSONObject(i) ?: continue
            if (o.text("device").isNotEmpty()) names.add(o.text("device"))
            if (o.text("cert").isNotEmpty()) names.add(o.text("cert"))
        }
        sp(c).edit().putStringSet(PREF_FORGOTTEN, names).commit()
        return list
    }

    private fun onTheList(c: Context, uid: String, list: JSONArray): Boolean {
        val device = deviceId(c, uid)
        val cert = ownCert(c, uid)
        for (i in 0 until list.length()) {
            val o = list.optJSONObject(i) ?: continue
            if (o.text("device") == device) return true
            if (cert.isNotEmpty() && o.text("cert") == cert) return true
        }
        return false
    }

    /** Device ids and certificate fingerprints that stay out, as of the last pass. */
    fun forgotten(c: Context): Set<String> =
        sp(c).getStringSet(PREF_FORGOTTEN, emptySet()).orEmpty().toSet()

    /**
     * The target on the account's list, with what is there. Entries are unique
     * by (device, cert) and not by device, as on a PC: the list must not shrink.
     * One sealed row holds about 40; past that the oldest give way on the row
     * and stay on every PC that saw them.
     */
    private fun addForgotten(c: Context, uid: String, key: ByteArray, device: String, cert: String) {
        val had = readForgotten(c, uid, key)
        val entries = LinkedHashMap<String, JSONObject>()
        for (i in 0 until had.length()) {
            val o = had.optJSONObject(i) ?: continue
            entries[o.text("device") + "\n" + o.text("cert")] = o
        }
        entries[device + "\n" + cert] = JSONObject().put("device", device).put("cert", cert)
            .put("at", Instant.now().toString())
        val kept = entries.values.toMutableList()
        var text = JSONObject().put("v", JSONArray(kept)).toString()
        while (kept.size > 1 && text.toByteArray().size > Crypt.PLAIN_MAX) {
            kept.removeAt(0)
            text = JSONObject().put("v", JSONArray(kept)).toString()
        }
        val r = Account.rest(c, "POST", "vault?on_conflict=user_id,name", JSONObject()
            .put("user_id", uid).put("name", FORGOTTEN)
            .put("cipher", Crypt.sealText(key, text, Crypt.aadVault(uid, FORGOTTEN))),
            "resolution=merge-duplicates,return=minimal")
        if (!r.ok) refused(r)
    }

    // ---- the devices ----

    private fun whenS(text: String): Long = try {
        OffsetDateTime.parse(text).toEpochSecond()
    } catch (e: DateTimeParseException) {
        0
    }

    private fun parseDevices(c: Context, uid: String, key: ByteArray, rows: JSONArray): List<Device> {
        val me = deviceId(c, uid)
        val out = forgotten(c)
        val devices = ArrayList<Device>()
        for (i in 0 until rows.length()) {
            val r = rows.optJSONObject(i) ?: continue
            val id = r.text("id")
            if (id.isEmpty() || id in out) continue
            val sealed = r.text("link")
            var link: JSONObject? = null
            if (sealed.isNotEmpty()) {
                link = try {
                    JSONObject(Crypt.openText(key, sealed, Crypt.aadDevice(uid, id)))
                } catch (e: Crypt.Refused) {
                    continue            // the server cannot add a device
                } catch (e: JSONException) {
                    continue
                }
            }
            val isPhone = link?.text("kind") == "phone" || r.text("platform").startsWith("android")
            val cert = link?.text("cert").orEmpty().let { field ->
                if (!isPhone) field.lowercase()
                else if (field.isEmpty()) ""
                else try {
                    certFingerprint(Base64.getDecoder().decode(field))
                } catch (e: IllegalArgumentException) {
                    ""
                }
            }
            if (cert.isNotEmpty() && cert in out) continue
            devices.add(Device(id, r.text("name"), !isPhone, whenS(r.text("last_seen")),
                               link != null, cert, link, id == me))
        }
        return devices.sortedWith(compareBy({ !it.mine }, { -it.seen }))
    }

    /** The account's devices, with the rows cached sealed for the road to the PC. */
    @Synchronized
    fun devices(c: Context): List<Device> {
        val s = Account.fresh(c)
        return keyed(c, s.uid) { key ->
            val r = Account.rest(c, "GET", "devices?select=id,name,platform,app_version,last_seen,link")
            if (!r.ok) refused(r)
            val rows = r.rows()
            Sealed.putText(c, ROWS, rows.toString())
            parseDevices(c, s.uid, key, rows)
        }
    }

    /** The same, from the last read: no network at all. */
    @Synchronized
    fun cachedDevices(c: Context): List<Device> {
        val s = Account.session(c) ?: return emptyList()
        val text = Sealed.getText(c, ROWS) ?: return emptyList()
        return keyed(c, s.uid) { key ->
            try {
                parseDevices(c, s.uid, key, JSONArray(text))
            } catch (e: JSONException) {
                emptyList()
            }
        }
    }

    // ---- a device asking to join ----

    /** (uid, pairing id, public key, lock) to its code: slow, and public. */
    private val codes = HashMap<String, String>()

    /** What the screen shows: an approval answers exactly this and nothing else. */
    private var shown: List<Asking> = emptyList()

    private fun codeOf(uid: String, id: String, public: String, lock: String): String =
        codes.getOrPut("$uid\n$id\n$public\n$lock") {
            if (codes.size > 64) codes.clear()
            Crypt.pairingCode(uid, id, Crypt.pointFrom(public), lock)
        }

    /**
     * sb.pending_pairings: the other devices waiting on this one, read off the
     * table. The code each carries is computed here, from the request's own
     * public key and the key this phone holds, and the `code` column is not
     * read. Two open requests from one device are one entry and no code:
     * neither can be approved. "Open" is by the server's clock.
     */
    @Synchronized
    fun asking(c: Context): List<Asking> {
        val s = Account.fresh(c)
        return keyed(c, s.uid) { key ->
            val r = Account.rest(c, "GET", "pairings?select=id,device_id,device_name,applicant," +
                "created_at,expires_at&handed=is.null&order=created_at.asc")
            if (!r.ok) refused(r)
            val rows = r.rows()
            val me = deviceId(c, s.uid)
            val byDevice = LinkedHashMap<String, MutableList<JSONObject>>()
            for (i in 0 until rows.length()) {
                val o = rows.optJSONObject(i) ?: continue
                if (o.text("device_id") == me) continue
                val until = whenS(o.text("expires_at"))
                if (until in 1..r.now) continue
                byDevice.getOrPut(o.text("device_id").ifEmpty { o.text("id") }) { ArrayList() }.add(o)
            }
            val lock = Crypt.fingerprint(key)
            val out = ArrayList<Asking>()
            for (reqs in byDevice.values) {
                val o = reqs.last()
                val id = o.text("id")
                val name = o.text("device_name").ifEmpty { "Another device" }
                if (reqs.size > 1) {
                    out.add(Asking(id, name, "", true))
                    continue
                }
                try {
                    out.add(Asking(id, name, codeOf(s.uid, id, o.text("applicant"), lock), false))
                } catch (e: Crypt.Refused) {
                    // a request with no usable public key
                }
            }
            shown = out
            out
        }
    }

    /**
     * sb.approve_pairing, with its checks: the request is the one the screen
     * showed, its code computed again from the key read NOW is the code on the
     * screen, nobody else claims to be that device, and it has not expired. The
     * one place this phone hands the key over, and it crosses sealed. Returns
     * the device's name.
     */
    @Synchronized
    fun approve(c: Context, pairingId: String): String {
        val s = Account.fresh(c)
        return keyed(c, s.uid) { key ->
            val aid = enc(pairingId)
            val r = Account.rest(c, "GET", "pairings?select=applicant,device_id,device_name," +
                "handed,expires_at&id=eq.$aid")
            if (!r.ok) refused(r)
            val rows = r.rows()
            if (rows.length() == 0) throw Account.Failed(c.getString(R.string.request_gone))
            val row = rows.getJSONObject(0)
            val name = row.text("device_name").ifEmpty { "Another device" }
            val until = whenS(row.text("expires_at"))
            if (until in 1..r.now) throw Account.Failed(c.getString(R.string.request_expired, name))
            val mine = shown.firstOrNull { it.id == pairingId }
            if (mine == null || mine.twins || mine.code.isEmpty()) {
                throw Account.Failed(c.getString(R.string.request_not_shown))
            }
            if (row.text("handed").isEmpty()) {
                val public = row.text("applicant")
                val code = try {
                    codeOf(s.uid, pairingId, public, Crypt.fingerprint(key))
                } catch (e: Crypt.Refused) {
                    throw Account.Failed(c.getString(R.string.request_no_key, name))
                }
                if (code != mine.code) {
                    Log.w("DeskIT", "lock: a request changed after it was shown: not approved")
                    throw Account.Failed(c.getString(R.string.request_changed, name))
                }
                val device = row.text("device_id")
                val same = Account.rest(c, "GET", "pairings?select=id,expires_at&handed=is.null" +
                    "&device_id=eq.${enc(device)}")
                if (!same.ok) refused(same)
                val open = same.rows()
                var count = 0
                for (i in 0 until open.length()) {
                    val u = whenS(open.getJSONObject(i).text("expires_at"))
                    if (u == 0L || u > same.now) count++
                }
                if (count > 1) throw Account.Failed(c.getString(R.string.twins_title, name))
                val handed = Crypt.handOver(key, Crypt.pointFrom(public),
                                            Crypt.aadPairing(s.uid, pairingId))
                val done = Account.rest(c, "PATCH", "pairings?id=eq.$aid", JSONObject()
                    .put("handed", handed).put("approved_at", Instant.now().toString()),
                    "return=minimal")
                if (!done.ok) refused(done)
            }
            shown = shown.filter { it.id != pairingId }
            Account.broadcast(c, "paired", JSONObject().put("device", deviceId(c, s.uid))
                .put("id", pairingId))
            name
        }
    }

    /** sb.decline_pairing: the request goes; the other device asks when it wants to. */
    @Synchronized
    fun decline(c: Context, pairingId: String) {
        val r = Account.rest(c, "DELETE", "pairings?id=eq.${enc(pairingId)}")
        if (!r.ok) refused(r)
        shown = shown.filter { it.id != pairingId }
    }

    // ---- leaving ----

    /**
     * Forget, from this phone: the target goes on the account's list first, so
     * a failure further on leaves it forgotten and never the other way round;
     * then its row and session go (0007, effective at once through 0006); then
     * the others are told.
     */
    @Synchronized
    fun forget(c: Context, d: Device) {
        val s = Account.fresh(c)
        keyed(c, s.uid) { key ->
            addForgotten(c, s.uid, key, d.id, d.cert)
            val r = Account.rest(c, "POST", "rpc/forget_device", JSONObject().put("target", d.id))
            if (!r.ok) refused(r)
        }
        sp(c).edit().putStringSet(PREF_FORGOTTEN, forgotten(c) + setOf(d.id, d.cert) - "").commit()
        changedDevices(c, deviceId(c, s.uid))
    }

    /** How many recordings no PC has yet. Named before Sign out deletes them. */
    fun recordings(c: Context): Int = File(c.filesDir, SPOOL).list()?.size ?: 0

    /** Everything this device holds of the account but the session. */
    private fun wipe(c: Context) {
        for (name in listOf(HELD, ASIDE, REQUEST, ROWS, DEVICE)) Sealed.delete(c, name)
        known = null
        try {
            ClientKey.wipe(c)
        } catch (e: Sealed.NotNow) {
            Log.w("DeskIT", "lock: the client key stays until the next device's: ${e.message}")
        }
        sp(c).edit().clear().commit()
        codes.clear()
        shown = emptyList()
    }

    /**
     * Sign out on a phone is leaving: Forget on itself. The list and the
     * broadcast go first, because the call that ends this session ends the
     * right to say anything after it. Then everything here is wiped, whatever
     * the server answered: a phone being sold must not keep the key because
     * the Wi-Fi was off. False when the account could not be told.
     */
    @Synchronized
    fun signOut(c: Context): Boolean {
        var told = true
        fun step(work: () -> Unit) {
            try {
                work()
            } catch (e: Account.Failed) {
                told = false
            } catch (e: Sealed.NotNow) {
                told = false
            } catch (e: JSONException) {
                told = false
            }
        }
        val s = try {
            Account.fresh(c)
        } catch (e: Account.Failed) {
            told = false
            null
        } catch (e: Sealed.NotNow) {
            told = false
            null
        }
        if (s != null) {
            val device = deviceId(c, s.uid)
            step { Account.rest(c, "DELETE", "pairings?device_id=eq.${enc(device)}") }
            step {
                val key = usable(c, s.uid)
                if (key != null) {
                    try {
                        addForgotten(c, s.uid, key, device, ownCert(c, s.uid))
                    } finally {
                        key.fill(0)
                    }
                    changedDevices(c, device)
                }
            }
            step {
                val r = Account.rest(c, "POST", "rpc/forget_device",
                                     JSONObject().put("target", device))
                if (!r.ok) told = false
            }
        }
        Account.endSession(c)
        wipe(c)
        File(c.filesDir, SPOOL).deleteRecursively()
        return told
    }
}
