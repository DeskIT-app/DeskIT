package io.github.deskit_app.deskit

import org.json.JSONObject
import java.io.IOException
import java.net.HttpURLConnection
import java.net.URL

/**
 * POSTs the audio to the PC and returns its transcript.
 *
 * HttpURLConnection rather than OkHttp: one fewer dependency to resolve in
 * a build with no IDE behind it, and this makes exactly one kind of
 * request.
 */
object Transcriber {

    sealed class Result {
        data class Ok(
            val text: String,
            val warning: String? = null,
            /** "local" or "gemini" — which engine on the PC answered. */
            val backend: String = "",
            val seconds: Double = 0.0,
            /** A lookup's answer reads right to left (its target is Hebrew). */
            val rtl: Boolean = false,
        ) : Result()

        data class Err(val message: String) : Result()
    }

    /** Blocking. Call from a background thread. */
    fun send(baseUrl: String, token: String, wav: ByteArray): Result =
        post(baseUrl, "/transcribe", token, "audio/wav", wav, 120000)

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
    fun punctuate(baseUrl: String, token: String, text: String): Result {
        val body = JSONObject().put("text", text)
            .toString().toByteArray(Charsets.UTF_8)
        return post(baseUrl, "/punctuate", token,
            "application/json; charset=utf-8", body, 180000)
    }

    /**
     * The version of DeskIT the PC is running, from /health — null when it
     * cannot be reached at all. This is what lets the keyboard say "the PC
     * is asleep" BEFORE a paragraph is spoken into it, instead of after a
     * 15 s connect timeout with the audio already gone. /health says
     * {ok, version} and nothing else since 12.3: the engine's name is not
     * for whoever can reach the port, it comes back with each transcript.
     */
    fun health(baseUrl: String): String? {
        val h = healthJson(baseUrl) ?: return null
        if (!h.optBoolean("ok", false)) return null
        return h.optString("version", "").ifEmpty { "?" }
    }

    /**
     * Translate text already in the field. The far end reuses the same
     * Gemini-then-Ollama translator the desktop's F9 key uses — and
     * Ollama's first request after idling takes over a minute while the
     * model loads into VRAM, hence the longer read timeout.
     */
    fun translate(baseUrl: String, token: String, text: String): Result {
        val body = JSONObject().put("text", text).toString()
            .toByteArray(Charsets.UTF_8)
        return post(baseUrl, "/translate", token,
            "application/json; charset=utf-8", body, 180000)
    }

    /** The whole of /health as JSON, or null if the PC did not answer. */
    fun healthJson(baseUrl: String): JSONObject? = getJson("$baseUrl/health", null)

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
    fun versions(baseUrl: String, token: String): Versions? =
        getJson("$baseUrl/api/version", token)?.let { Versions.from(it) }

    /** One GET as JSON — with the bearer when one is given — or null. */
    private fun getJson(url: String, token: String?): JSONObject? {
        var conn: HttpURLConnection? = null
        return try {
            conn = (URL(url).openConnection() as HttpURLConnection).apply {
                connectTimeout = 10000
                readTimeout = 15000
                if (token != null) setRequestProperty("Authorization", "Bearer $token")
            }
            if (conn.responseCode !in 200..299) return null
            val body = conn.inputStream.bufferedReader().use { it.readText() }
            JSONObject(body)
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
    fun reviewPending(baseUrl: String, token: String): List<Proposal>? {
        var conn: HttpURLConnection? = null
        return try {
            conn = (URL("$baseUrl/review").openConnection() as HttpURLConnection).apply {
                connectTimeout = 10000
                readTimeout = 15000
                setRequestProperty("Authorization", "Bearer $token")
            }
            if (conn.responseCode !in 200..299) return null
            val body = conn.inputStream.bufferedReader().use { it.readText() }
            val items = JSONObject(body).optJSONArray("items") ?: return emptyList()
            (0 until items.length()).map { Proposal.from(items.getJSONObject(it)) }
        } catch (e: Exception) {
            null
        } finally {
            conn?.disconnect()
        }
    }

    /** Keep or No on one proposal. "accepted" / "rejected". Blocking. */
    fun reviewDecide(baseUrl: String, token: String, id: String,
                     verdict: String): Result {
        val body = JSONObject().put("id", id).put("verdict", verdict)
            .toString().toByteArray(Charsets.UTF_8)
        return post(baseUrl, "/review/decide", token,
            "application/json; charset=utf-8", body, 30000)
    }

    /**
     * The desktop's F8 key for a selection made on the phone: the Hebrew
     * of an English selection, or the English of a Hebrew one. Never
     * written anywhere by the caller — shown in a box, and that is all.
     * Same long read timeout as translate: the local model may be cold.
     */
    fun lookup(baseUrl: String, token: String, text: String): Result {
        val body = JSONObject().put("text", text)
            .toString().toByteArray(Charsets.UTF_8)
        return post(baseUrl, "/lookup", token,
            "application/json; charset=utf-8", body, 180000)
    }

    private fun post(
        baseUrl: String, path: String, token: String,
        contentType: String, body: ByteArray, readTimeoutMs: Int
    ): Result {
        var conn: HttpURLConnection? = null
        return try {
            conn = (URL("$baseUrl$path").openConnection() as HttpURLConnection).apply {
                requestMethod = "POST"
                doOutput = true
                // Generous: a long dictation is a long upload, and the
                // model itself needs a moment on the far end.
                connectTimeout = 15000
                readTimeout = readTimeoutMs
                setRequestProperty("Authorization", "Bearer $token")
                setRequestProperty("Content-Type", contentType)
                setFixedLengthStreamingMode(body.size)
            }
            conn.outputStream.use { it.write(body) }
            val code = conn.responseCode
            val body = (if (code in 200..299) conn.inputStream else conn.errorStream)
                ?.bufferedReader()?.use { it.readText() } ?: ""
            when {
                code == 401 -> Result.Err("bad token — check setup")
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
            // obvious from a raw exception string.
            Result.Err("can't reach the PC — is it on, and the link up?")
        } catch (e: Exception) {
            Result.Err(e.message ?: "failed")
        } finally {
            conn?.disconnect()
        }
    }

    private fun errorFrom(body: String, code: Int): String = try {
        JSONObject(body).optString("error").ifEmpty { "server error $code" }
    } catch (_: Exception) {
        "server error $code"
    }
}
