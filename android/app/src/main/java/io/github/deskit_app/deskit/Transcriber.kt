package io.github.deskit_app.deskit

import android.util.Log
import org.json.JSONObject
import java.io.IOException
import java.net.HttpURLConnection
import java.util.Locale

/**
 * POSTs the audio to the PC and returns its transcript. Every route the PC
 * has, on whichever road [Link] hands over: this file knows what to say to a PC
 * and nothing about how to get to one.
 *
 * HttpURLConnection rather than OkHttp: one fewer dependency to resolve in
 * a build with no IDE behind it, and this makes exactly one kind of
 * request.
 */
object Transcriber {

    /** Why a request came to nothing, which decides what happens to what it carried. */
    enum class Why {
        /** No answer. Another road may have one, and the recording stays. */
        UNREACHED,
        /** A PC answered that it cannot now: the model is off, or it is signed out. */
        BUSY,
        /** A PC answered that it never will, about this: sending it again changes nothing. */
        REFUSED,
    }

    sealed class Result {
        data class Ok(
            val text: String,
            val warning: String? = null,
            /** "local" or "gemini" — which engine on the PC answered. */
            val backend: String = "",
            val seconds: Double = 0.0,
            /** A lookup's answer reads right to left (its target is Hebrew). */
            val rtl: Boolean = false,
            /** The cloud backup carried it: the provider's word ("groq"), "" for a PC. */
            val cloud: String = "",
            /** The recording's length in seconds, for the text the PCs are told. */
            val audio: Double = 0.0,
        ) : Result()

        data class Err(val message: String, val why: Why = Why.BUSY) : Result()
    }

    /** Blocking. Call from a background thread. */
    fun send(road: Link.Road, wav: ByteArray): Result =
        post(road, "/transcribe", "audio/wav", wav, 120000)

    /**
     * Punctuate text already in the field — the phone twin of the desktop's
     * F2 key, wrapping the very same Punctuator on the far end.
     *
     * The interesting reply is 409: the model answered but rewrote the
     * user's words instead of punctuating them, and the far end threw that
     * away. errorFrom() lifts the sentence out of the body like any other
     * failure, so it reaches the status line with nothing special needed
     * here — and stays distinguishable from a dead backend by status code.
     *
     * Same generous read timeout as translate(), for the same reason: a
     * cold Ollama takes over a minute to load the model into VRAM.
     */
    fun punctuate(road: Link.Road, text: String): Result {
        val body = JSONObject().put("text", text)
            .toString().toByteArray(Charsets.UTF_8)
        return post(road, "/punctuate", "application/json; charset=utf-8", body, 180000)
    }

    /**
     * The version of DeskIT the PC is running, from /health — null when it
     * cannot be reached at all. This is what lets the keyboard say "the PC
     * is asleep" BEFORE a paragraph is spoken into it, instead of after a
     * 15 s connect timeout with the audio already gone. /health says
     * {ok, version} and nothing else since 12.3: the engine's name is not
     * for whoever can reach the port, it comes back with each transcript.
     */
    fun health(road: Link.Road): String? {
        val h = getJson(road, "/health") ?: return null
        if (!h.optBoolean("ok", false)) return null
        return h.optString("version", "").ifEmpty { "?" }
    }

    /**
     * Translate text already in the field. The far end reuses the same
     * Gemini-then-Ollama translator the desktop's F9 key uses — and
     * Ollama's first request after idling takes over a minute while the
     * model loads into VRAM, hence the longer read timeout.
     */
    fun translate(road: Link.Road, text: String): Result {
        val body = JSONObject().put("text", text).toString()
            .toByteArray(Charsets.UTF_8)
        return post(road, "/translate", "application/json; charset=utf-8", body, 180000)
    }

    /**
     * What the PC knows about keyboard builds (DISTRIBUTION_PLAN.md 12.9),
     * behind the token so the LAN learns nothing: the PC's own version,
     * the oldest keyboard it still speaks with (`ime_min`), the newest it
     * knows of (`ime_latest`) and where to get it (`apk_url`, `play_url`,
     * `apk_sha256`). The 12.9 rule the callers apply to their own
     * versionCode: below ime_min the keyboard must update to keep
     * dictating; between, one dismissible pill; at latest, nothing.
     */
    class Versions(
        val pc: String, val imeMin: Int, val imeLatest: Int,
        val apkUrl: String, val apkSha256: String, val playUrl: String,
    ) {
        companion object {
            fun from(o: JSONObject) = Versions(
                o.optString("pc", ""), o.optInt("ime_min", 0), o.optInt("ime_latest", 0),
                o.optString("apk_url", ""), o.optString("apk_sha256", ""),
                o.optString("play_url", ""))
        }
    }

    /** /api/version, or null when the PC did not answer or refused the token. */
    fun versions(road: Link.Road): Versions? =
        getJson(road, "/api/version")?.let { Versions.from(it) }

    /**
     * Does the PC refuse who is asking? A long POST cannot say: the PC answers 401
     * before it has read the body and closes, and the phone, still writing, sees a
     * broken pipe. A GET that needs the same proof can.
     */
    fun refused(road: Link.Road): Boolean {
        var conn: HttpURLConnection? = null
        return try {
            conn = road.open("/api/version").apply {
                connectTimeout = road.connectMs
                readTimeout = road.readMs
                road.prove(this)
            }
            conn.responseCode == 401
        } catch (e: IOException) {
            false
        } finally {
            conn?.disconnect()
        }
    }

    /** One GET as JSON, or null. */
    private fun getJson(road: Link.Road, path: String): JSONObject? {
        var conn: HttpURLConnection? = null
        return try {
            conn = road.open(path).apply {
                connectTimeout = road.connectMs
                readTimeout = road.readMs
                road.prove(this)
            }
            if (conn.responseCode !in 200..299) return null
            val body = conn.inputStream.bufferedReader().use { it.readText() }
            JSONObject(body)
        } catch (e: IOException) {
            Log.i("DeskIT", "transcriber: no answer on $path: ${e.javaClass.simpleName}")
            null
        } catch (e: Exception) {
            null
        } finally {
            conn?.disconnect()
        }
    }

    // ---- the second reading, and the lookup ----

    /** One proposal of the second reading, as GET /review hands it over. */
    class Proposal(
        val id: String, val whenText: String, val text: String,
        val proposed: String, val source: String,
        val changes: List<Change>,
    ) {
        class Change(val before: String, val after: String,
                     val kind: String, val why: String, val rtl: Boolean)

        val fromPhone: Boolean get() = source == "phone"

        companion object {
            fun from(o: JSONObject): Proposal {
                val changes = ArrayList<Change>()
                val cs = o.optJSONArray("changes")
                val snips = o.optJSONArray("snippets")
                if (cs != null) for (i in 0 until cs.length()) {
                    val c = cs.getJSONObject(i)
                    val snip = snips?.optJSONObject(i)
                    changes.add(Change(
                        c.optString("before", ""), c.optString("after", ""),
                        c.optString("kind", "replace"), c.optString("why", ""),
                        snip?.optBoolean("rtl", true) ?: true))
                }
                return Proposal(
                    o.optString("id", ""), o.optString("when", ""),
                    o.optString("text", ""), o.optString("proposed", ""),
                    o.optString("source", "desktop"), changes)
            }
        }
    }

    /**
     * Every proposal still waiting on the PC — null when it cannot be
     * asked (unreachable, bad token, the reading switched off). Blocking.
     */
    fun reviewPending(road: Link.Road): List<Proposal>? = try {
        getJson(road, "/review")?.let { o ->
            val items = o.optJSONArray("items")
            if (items == null) emptyList()
            else (0 until items.length()).map { Proposal.from(items.getJSONObject(it)) }
        }
    } catch (e: org.json.JSONException) {
        null
    }

    /** Keep or No on one proposal. "accepted" / "rejected". Blocking. */
    fun reviewDecide(road: Link.Road, id: String, verdict: String): Result {
        val body = JSONObject().put("id", id).put("verdict", verdict)
            .toString().toByteArray(Charsets.UTF_8)
        return post(road, "/review/decide", "application/json; charset=utf-8", body, 30000)
    }

    /**
     * The desktop's F8 key for a selection made on the phone: the Hebrew
     * of an English selection, or the English of a Hebrew one. Never
     * written anywhere by the caller — shown in a box, and that is all.
     * Same long read timeout as translate: the local model may be cold.
     */
    fun lookup(road: Link.Road, text: String): Result {
        val body = JSONObject().put("text", text)
            .toString().toByteArray(Charsets.UTF_8)
        return post(road, "/lookup", "application/json; charset=utf-8", body, 180000)
    }

    private fun post(
        road: Link.Road, path: String, contentType: String, body: ByteArray, readTimeoutMs: Int
    ): Result {
        var conn: HttpURLConnection? = null
        return try {
            conn = road.open(path).apply {
                requestMethod = "POST"
                doOutput = true
                connectTimeout = road.connectMs
                // Generous: a long dictation is a long upload, and the
                // model itself needs a moment on the far end.
                readTimeout = readTimeoutMs
                road.prove(this)
                setRequestProperty("Content-Type", contentType)
                setFixedLengthStreamingMode(body.size)
            }
            conn.outputStream.use { it.write(body) }
            val code = conn.responseCode
            val body = (if (code in 200..299) conn.inputStream else conn.errorStream)
                ?.bufferedReader()?.use { it.readText() } ?: ""
            when {
                code == 401 -> Result.Err(BAD_TOKEN)
                code in REFUSED -> Result.Err(errorFrom(body, code), Why.REFUSED)
                code !in 200..299 -> Result.Err(errorFrom(body, code))
                else -> {
                    val o = JSONObject(body)
                    Result.Ok(o.optString("text", ""),
                        o.optString("warning", "").ifEmpty { null },
                        o.optString("backend", ""),
                        o.optDouble("seconds", 0.0),
                        rtl = o.optString("target", "") == "Hebrew")
                }
            }
        } catch (e: IOException) {
            // By far the most likely failure in real use, and the least
            // obvious from a raw exception string. Its class, because a door
            // that refused this phone reads as nothing else from here.
            Log.i("DeskIT", "transcriber: no answer on $path: ${e.javaClass.simpleName}")
            Result.Err(road.unreached, Why.UNREACHED)
        } catch (e: org.json.JSONException) {
            // Something answered 2xx with what is not the PC's JSON: a portal's
            // page, a proxy's. Its own words would be a parser's.
            Log.i("DeskIT", "transcriber: an answer on $path that is not JSON")
            Result.Err(UNREADABLE)
        } catch (e: Exception) {
            Result.Err(e.message ?: "failed")
        } finally {
            conn?.disconnect()
        }
    }

    /**
     * The answers that say sending it again changes nothing: not audio it can read,
     * or words it will not touch. Everything else is a PC with a reason of the
     * moment, and a recording is the only copy of what was said.
     */
    private val REFUSED = setOf(400, 409, 413, 415)

    /** The pasted line's own failure, as it always read. */
    const val BAD_TOKEN = "bad token — check setup"

    /** An answer that was not the PC's JSON. */
    const val UNREADABLE = "the answer could not be read"

    private fun errorFrom(body: String, code: Int): String = try {
        JSONObject(body).optString("error").ifEmpty { "server error $code" }
    } catch (_: Exception) {
        "server error $code"
    }
}

/**
 * What a PC's own sentence is about, for the few words the keyboard says of it.
 * Apart from [Transcriber], so the JVM can hold it with no org.json.
 */
object PcWords {
    enum class About { MODEL_OFF, SIGNED_OUT, NO_MODEL, ERROR, OTHER }

    /**
     * Read by how the PC opens its sentences: main.py's MODEL_OFF_WORDS and
     * ROOM_OFF_WORDS, its LOCK_WORDS, models.py's _WHY, and Transcriber's own
     * "server error N". Anything else is the PC's to say, word for word.
     */
    fun about(message: String): About {
        val m = message.trim().lowercase(Locale.ROOT)
        return when {
            m.startsWith("the model is off") ||
                m.startsWith("the speech model stepped aside") -> About.MODEL_OFF
            m.startsWith("sign in to use deskit") -> About.SIGNED_OUT
            m.startsWith("the hebrew model") -> About.NO_MODEL
            errorCode(m) != null -> About.ERROR
            else -> About.OTHER
        }
    }

    /** N of "server error N", or null. */
    fun errorCode(message: String): Int? =
        SERVER_ERROR.matchEntire(message.trim())?.groupValues?.get(1)?.toIntOrNull()

    private val SERVER_ERROR = Regex("server error (\\d{3})")
}
