package com.yoav.dictation

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
        data class Ok(val text: String, val warning: String? = null) : Result()
        data class Err(val message: String) : Result()
    }

    /** Blocking. Call from a background thread. */
    fun send(baseUrl: String, token: String, wav: ByteArray): Result =
        post(baseUrl, "/transcribe", token, "audio/wav", wav, 120000)

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

    /**
     * The version the PC is currently serving, from /health — the one
     * unauthenticated route, which is fine: it exposes nothing but "up"
     * and a version string. null when the PC is unreachable.
     */
    fun serverApkVersion(baseUrl: String): String? {
        var conn: HttpURLConnection? = null
        return try {
            conn = (URL("$baseUrl/health").openConnection() as HttpURLConnection).apply {
                connectTimeout = 10000
                readTimeout = 15000
            }
            val body = conn.inputStream.bufferedReader().use { it.readText() }
            JSONObject(body).optString("apk", "").ifEmpty { null }
        } catch (e: Exception) {
            null
        } finally {
            conn?.disconnect()
        }
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
                        o.optString("warning", "").ifEmpty { null })
                }
            }
        } catch (e: IOException) {
            // By far the most likely failure in real use, and the least
            // obvious from a raw exception string.
            Result.Err("can't reach the PC — is Tailscale on?")
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
