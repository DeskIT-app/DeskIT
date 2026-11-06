package io.github.deskit_app.deskit

import android.app.Activity
import android.content.ActivityNotFoundException
import android.content.Context
import android.content.Intent
import android.net.Uri
import org.json.JSONArray
import org.json.JSONObject
import java.io.IOException
import java.net.HttpURLConnection
import java.net.URL
import java.net.URLEncoder
import java.util.Base64

/**
 * The account, from the phone: everything sb.py does for a PC that a phone
 * needs too, through HttpURLConnection and nothing else.
 *
 * The sign-in is Supabase's PKCE flow in the phone's own browser, the same
 * request sb.sign_in_google makes, and the answer returns to the custom
 * scheme deskit://auth, which [AuthActivity] catches. The plain browser and
 * no Custom Tabs library; Google refuses embedded WebViews. The verifier is
 * sealed while the browser is in front, because Android may kill us there. An
 * exported scheme means any app can knock on it, and that is why PKCE is here:
 * a code nobody asked for fails the exchange, for want of our verifier.
 *
 * The session is sealed by the Keystore ([Sealed]), read once and kept in
 * memory, and refreshed the way sb._fresh does: under one lock, so that two
 * threads cannot spend one refresh token, ten seconds before its hour is up.
 * A 401 is one refresh and one retry; a second 401, or a refresh the server
 * refuses, is [gone]: the session goes and nothing else does. The key stays,
 * so the same account back on this phone needs no second Approve.
 *
 * The publishable key is public by design: it is in sb.py, in every install
 * and in the keep-alive workflow. Which server this build speaks to is a
 * build-time fact (`-PdeskitAccount=`, debug builds only), never a setting:
 * there is no way for anything on the phone to point it somewhere else.
 *
 * Never logged: a token, a code, an address, a name.
 */
object Account {
    const val PROJECT_REF = "eogvmcbwfthxedcltyrs"
    const val PUBLISHABLE_KEY = "sb_publishable_p3pBXir64azVPAS1wtQoVg_mgi5ZOCt"
    const val REDIRECT = "deskit://auth"

    private const val SESSION = "session"
    private const val PKCE = "pkce"
    private const val FILE = "account"
    private const val KEY_WORDS = "gone_words"

    /** sb.REFRESH_MARGIN_S. */
    private const val REFRESH_MARGIN_S = 10L
    /** sb.TIMEOUT_S. */
    private const val TIMEOUT_MS = 20000

    const val GONE_ELSEWHERE = "Signed out from another device."
    const val GONE_WORDS = "This phone was signed out."

    /** Something the person should read; [offline] when no answer came at all. */
    class Failed(message: String, val offline: Boolean = false) : Exception(message)

    class Session(
        val access: String, val refresh: String, val expiresAt: Long,
        val uid: String, val email: String, val name: String,
    )

    /**
     * What the server answered: the status, the body, and the server's own
     * clock ([date], epoch seconds, 0 without the header).
     */
    class Reply(val status: Int, val body: String, val date: Long = 0) {
        val ok: Boolean get() = status in 200..299

        /** "Now", as the server has it: a phone's own clock can be anywhere. */
        val now: Long get() = if (date > 0) date else System.currentTimeMillis() / 1000

        /**
         * The rows. An answer that is not rows is a [Failed] and never an
         * empty list: "no row" means a request was declined or a lock is not
         * there, and a garbled answer must decide neither.
         */
        fun rows(): JSONArray = try {
            JSONArray(body)
        } catch (e: Exception) {
            throw Failed("Your account answered with something unreadable. Try again.")
        }

        fun obj(): JSONObject? = try {
            JSONObject(body)
        } catch (e: Exception) {
            null
        }

        /** sb._server_said: one readable line, never a token. */
        fun said(): String {
            val o = obj()
            if (o != null) for (k in listOf("msg", "message", "error_description", "error", "hint")) {
                val v = o.optString(k, "")
                if (v.isNotEmpty()) return "HTTP $status: ${v.take(160)}"
            }
            return "HTTP $status"
        }
    }

    private fun sp(c: Context) = c.getSharedPreferences(FILE, Context.MODE_PRIVATE)

    fun base(c: Context): String =
        c.getString(R.string.account_server).ifEmpty { "https://$PROJECT_REF.supabase.co" }

    private fun enc(s: String): String = URLEncoder.encode(s, "UTF-8")

    // ---- the session ----

    @Volatile private var cached: Session? = null

    private fun parse(text: String): Session? = try {
        val o = JSONObject(text)
        val u = o.getJSONObject("user")
        Session(o.getString("access_token"), o.optString("refresh_token", ""),
                o.getLong("expires_at"), u.getString("id"), u.optString("email", ""),
                u.optString("name", ""))
    } catch (e: Exception) {
        null
    }

    /** The session held here, or null. [Sealed.NotNow] while the phone is locked. */
    @Synchronized
    fun session(c: Context): Session? {
        cached?.let { return it }
        val text = Sealed.getText(c, SESSION) ?: return null
        return parse(text).also { cached = it }
    }

    fun signedIn(c: Context): Boolean = session(c) != null

    /**
     * sb._store_session, with one difference: the hour is counted from
     * `expires_in`, on this phone's own clock. `expires_at` is the server's,
     * and a phone whose clock is off (they are, and not only by minutes)
     * would refresh on every call, or never.
     */
    private fun store(c: Context, data: JSONObject): Session {
        val now = System.currentTimeMillis() / 1000
        val expires = data.optLong("expires_in", 0).takeIf { it > 0 }?.let { now + it }
            ?: data.optLong("expires_at", 0).takeIf { it > 0 }
            ?: (now + 3600)
        val user = data.optJSONObject("user") ?: JSONObject()
        val meta = user.optJSONObject("user_metadata") ?: JSONObject()
        val name = meta.optString("name", "").ifEmpty { meta.optString("full_name", "") }.take(40)
        val keep = JSONObject()
            .put("access_token", data.optString("access_token", ""))
            .put("refresh_token", data.optString("refresh_token", ""))
            .put("expires_at", expires)
            .put("user", JSONObject()
                .put("id", user.optString("id", ""))
                .put("email", user.optString("email", ""))
                .put("name", name))
        Sealed.putText(c, SESSION, keep.toString())
        val s = parse(keep.toString()) ?: throw Failed("the server's answer was not a session")
        cached = s
        return s
    }

    @Synchronized
    private fun clear(c: Context) {
        Sealed.delete(c, SESSION)
        cached = null
    }

    /**
     * The session's own id, off the token's `session_id` claim: what the
     * device row carries so that Forget can end this session (0007). Read
     * and never checked: the token's signature is the server's to check.
     */
    fun sessionId(s: Session): String = try {
        val part = s.access.split('.')[1]
        val raw = Base64.getUrlDecoder().decode(part)
        JSONObject(String(raw, Charsets.UTF_8)).optString("session_id", "")
    } catch (e: Exception) {
        ""
    }

    /** Why the phone was signed out, until the next sign-in clears it. */
    fun goneWords(c: Context): String = sp(c).getString(KEY_WORDS, "") ?: ""

    /** sb._account_gone: the session goes, and the key and everything else stay. */
    private fun gone(c: Context, words: String) {
        clear(c)
        sp(c).edit().putString(KEY_WORDS, words).apply()
    }

    // ---- the wire ----

    private fun call(c: Context, method: String, path: String, body: String?,
                     bearer: String?, prefer: String = ""): Reply {
        var conn: HttpURLConnection? = null
        try {
            conn = (URL(base(c) + path).openConnection() as HttpURLConnection).apply {
                requestMethod = method
                connectTimeout = TIMEOUT_MS
                readTimeout = TIMEOUT_MS
                setRequestProperty("apikey", PUBLISHABLE_KEY)
                setRequestProperty("Accept", "application/json")
                if (bearer != null) setRequestProperty("Authorization", "Bearer $bearer")
                if (prefer.isNotEmpty()) setRequestProperty("Prefer", prefer)
            }
            if (body != null) {
                val raw = body.toByteArray(Charsets.UTF_8)
                conn.doOutput = true
                conn.setRequestProperty("Content-Type", "application/json")
                conn.setFixedLengthStreamingMode(raw.size)
                conn.outputStream.use { it.write(raw) }
            }
            val status = conn.responseCode
            val stream = if (status in 200..299) conn.inputStream else conn.errorStream
            return Reply(status, stream?.bufferedReader()?.use { it.readText() } ?: "",
                         conn.getHeaderFieldDate("Date", 0L) / 1000)
        } catch (e: IOException) {
            throw Failed("Can't reach your account. Check the connection.", offline = true)
        } finally {
            conn?.disconnect()
        }
    }

    private fun refresh(c: Context): Session {
        val s = session(c) ?: throw Failed("Not signed in.")
        val r = call(c, "POST", "/auth/v1/token?grant_type=refresh_token",
                     JSONObject().put("refresh_token", s.refresh).toString(), null)
        val data = r.obj()
        if (r.status != 200 || data == null || data.optString("access_token", "").isEmpty()) {
            if (r.status in listOf(400, 401, 403, 404)) {
                // The refresh token was revoked or used elsewhere. "Refresh
                // Token Not Found" is the session deleted on the server: Sign
                // out of every PC, or Forget.
                gone(c, if (r.said().contains("not found", ignoreCase = true))
                            GONE_ELSEWHERE else GONE_WORDS)
                throw Failed("You were signed out. Sign in again.")
            }
            throw Failed("The session could not be refreshed (${r.status}).")
        }
        return store(c, data)
    }

    /** sb._fresh: the session, refreshed first when its hour is (nearly) over. */
    @Synchronized
    fun fresh(c: Context): Session {
        val s = session(c) ?: throw Failed("Not signed in.")
        val now = System.currentTimeMillis() / 1000
        return if (s.expiresAt - now <= REFRESH_MARGIN_S) refresh(c) else s
    }

    /** One refresh now, whatever the clock says. */
    @Synchronized
    fun refreshNow(c: Context): Session = refresh(c)

    /** sb._rest: one PostgREST call under the session. [path] holds the query. */
    fun rest(c: Context, method: String, path: String, payload: Any? = null,
             prefer: String = ""): Reply {
        fresh(c)
        val body = payload?.toString()
        for (attempt in 1..2) {
            val s = session(c) ?: throw Failed("Not signed in.")
            val r = call(c, method, "/rest/v1/$path", body, s.access, prefer)
            if (r.status != 401) return r
            if (attempt == 1) {
                synchronized(this) { refresh(c) }
                continue
            }
            gone(c, GONE_WORDS)
            throw Failed("You were signed out. Sign in again.")
        }
        throw Failed("Not signed in.")
    }

    /**
     * sb._broadcast: one POST on the account's private topic. It carries
     * nothing a stranger could use, and a failure is nothing: the PCs read
     * the same rows at their next pass, this only saves them the wait.
     */
    fun broadcast(c: Context, event: String, payload: JSONObject) {
        try {
            val s = fresh(c)
            val message = JSONObject()
                .put("topic", "user:${s.uid}")
                .put("event", event)
                .put("private", true)
                .put("payload", payload)
            call(c, "POST", "/realtime/v1/api/broadcast",
                 JSONObject().put("messages", JSONArray().put(message)).toString(), s.access)
        } catch (e: Failed) {
            // the next pass carries it
        } catch (e: Sealed.NotNow) {
            // the same
        }
    }

    // ---- signing in and out ----

    /** Open the phone's browser on Google's page. [Failed] with no browser. */
    fun beginSignIn(a: Activity) {
        val verifier = Crypt.pkceVerifier()
        Sealed.putText(a, PKCE, verifier)
        val url = base(a) + "/auth/v1/authorize?provider=google" +
            "&redirect_to=" + enc(REDIRECT) +
            "&code_challenge=" + Crypt.pkceChallenge(verifier) +
            "&code_challenge_method=s256" +
            // The chooser, every time. "Use another account" means nothing if
            // the browser's Google session answers by itself, and the tap on it
            // is the gesture a browser wants before it hands a redirect to an app.
            "&prompt=select_account"
        try {
            a.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url))
                .addCategory(Intent.CATEGORY_BROWSABLE))
        } catch (e: ActivityNotFoundException) {
            Sealed.delete(a, PKCE)
            throw Failed("This phone has no browser to sign in with.")
        }
    }

    /**
     * The browser came back: the exchange, on a thread. Only a sign-in this
     * phone started can finish, since a code without our verifier is refused
     * by the server, and without a verifier it never leaves the phone.
     */
    fun finishSignIn(c: Context, back: Uri): Session {
        val code = back.getQueryParameter("code").orEmpty()
        if (code.isEmpty()) {
            val fragment = Uri.parse("deskit://auth?" + back.encodedFragment.orEmpty())
            val why = back.getQueryParameter("error_description")
                ?: fragment.getQueryParameter("error_description")
                ?: back.getQueryParameter("error")
                ?: fragment.getQueryParameter("error")
            throw Failed(if (why.isNullOrEmpty()) "The browser came back with nothing."
                         else "Google did not sign you in: ${why.take(160)}")
        }
        val verifier = Sealed.getText(c, PKCE)
            ?: throw Failed("That sign-in has ended. Try again.")
        val r = call(c, "POST", "/auth/v1/token?grant_type=pkce",
                     JSONObject().put("auth_code", code).put("code_verifier", verifier).toString(),
                     null)
        val data = r.obj()
        if (r.status != 200 || data == null || data.optString("access_token", "").isEmpty()) {
            throw Failed("The sign-in code was refused (${r.said()}).")
        }
        Sealed.delete(c, PKCE)
        sp(c).edit().remove(KEY_WORDS).apply()
        return store(c, data)
    }

    /** This session and nothing else: scope=local, then forgotten here. */
    fun endSession(c: Context) {
        try {
            val s = session(c)
            if (s != null) call(c, "POST", "/auth/v1/logout?scope=local", "{}", s.access)
        } catch (e: Failed) {
            // it dies at its hour; it is forgotten here either way
        } catch (e: Sealed.NotNow) {
            // the same
        }
        clear(c)
    }
}
