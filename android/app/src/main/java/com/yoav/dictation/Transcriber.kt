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
        data class Ok(val text: String) : Result()
        data class Err(val message: String) : Result()
    }

    /** Blocking. Call from a background thread. */
    fun send(baseUrl: String, token: String, wav: ByteArray): Result {
        var conn: HttpURLConnection? = null
        return try {
            conn = (URL("$baseUrl/transcribe").openConnection() as HttpURLConnection).apply {
                requestMethod = "POST"
                doOutput = true
                // Generous: a long dictation is a long upload, and the
                // model itself needs a moment on the far end.
                connectTimeout = 15000
                readTimeout = 120000
                setRequestProperty("Authorization", "Bearer $token")
                setRequestProperty("Content-Type", "audio/wav")
                setFixedLengthStreamingMode(wav.size)
            }
            conn.outputStream.use { it.write(wav) }
            val code = conn.responseCode
            val body = (if (code in 200..299) conn.inputStream else conn.errorStream)
                ?.bufferedReader()?.use { it.readText() } ?: ""
            when {
                code == 401 -> Result.Err("bad token — check setup")
                code !in 200..299 -> Result.Err(errorFrom(body, code))
                else -> Result.Ok(JSONObject(body).optString("text", ""))
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
