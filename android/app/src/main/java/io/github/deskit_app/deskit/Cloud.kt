package io.github.deskit_app.deskit

import android.content.Context
import android.os.SystemClock
import android.util.Log
import org.json.JSONArray
import org.json.JSONObject
import java.io.IOException
import java.net.HttpURLConnection
import java.net.URL
import java.util.Base64
import java.util.UUID

/**
 * The cloud backup's one request (PHONE_LINK_PLAN.md stage 2b): the recording to the
 * person's own provider with the person's own key, from the phone, the PC out of the
 * picture. Groq's `whisper-large-v3-turbo` first (M15, 2026-11-11: 8.1 s of Hebrew in
 * 0.41-0.47 s on the free tier); Gemini only when it is the one key in the account.
 *
 * **The key** is opened from the account's sealed row by [CloudKeys], handed here for
 * one request, and dropped: it is a local of the call and goes nowhere else. Nothing
 * here logs a body, a header or a URL with a query, and a provider's own words pass
 * [Scrub] before they reach a log line or the screen.
 *
 * **The client is named** (`deskit-android/<version>`): Cloudflare in front of Groq
 * refuses some default clients outright (Python's, measured in M15), and a change of
 * its rules must not silently take the backup away. HttpURLConnection, like the rest
 * of the app: no library.
 *
 * The hosts are the real ones; a debug build made for the flows points them at a
 * fake (`-PdeskitCloud=http://10.0.2.2:18793`), a build-time fact like the account's.
 */
object Cloud {
    enum class Provider(val word: String, val label: String) {
        GROQ("groq", "Groq"), GEMINI("gemini", "Gemini");

        companion object {
            fun of(word: String): Provider? = values().firstOrNull { it.word == word }
        }
    }

    /** Why a cloud request came to nothing, which decides the words and the row. */
    enum class Why { NO_ANSWER, KEY, LIMIT, OTHER }

    sealed class Answer {
        class Text(val text: String, val seconds: Double) : Answer()
        class Failed(val why: Why, val words: String) : Answer()
    }

    private const val GROQ_HOST = "https://api.groq.com"
    private const val GEMINI_HOST = "https://generativelanguage.googleapis.com"
    const val GROQ_MODEL = "whisper-large-v3-turbo"
    /** defaults.toml's [gemini] models, the two that new keys may still use. */
    private val GEMINI_MODELS = listOf("gemini-flash-latest", "gemini-flash-lite-latest")

    private const val CONNECT_MS = 10_000
    /** A five-minute recording is 9.6 MB, and a phone on a weak signal is slow. */
    private const val READ_MS = 90_000
    private const val TEST_MS = 15_000

    /** transcribers/gemini.py asks for more than the words; the backup asks for the words. */
    private const val GEMINI_ASK = "Transcribe this recording exactly as spoken. The speech is " +
        "Hebrew, possibly with English words: keep Hebrew as Hebrew and English words in Latin " +
        "letters, never translate. Output only the transcript, with punctuation, and nothing " +
        "else. If nothing is said, output nothing."

    private fun host(c: Context, real: String): String =
        c.getString(R.string.cloud_server).ifEmpty { real }.trimEnd('/')

    fun userAgent(c: Context): String = try {
        "deskit-android/" + c.packageManager.getPackageInfo(c.packageName, 0).versionName
    } catch (e: Exception) {
        "deskit-android"
    }

    private fun open(c: Context, url: String, readMs: Int): HttpURLConnection =
        (URL(url).openConnection() as HttpURLConnection).apply {
            connectTimeout = CONNECT_MS
            readTimeout = readMs
            instanceFollowRedirects = false
            setRequestProperty("User-Agent", userAgent(c))
            setRequestProperty("Accept", "application/json")
        }

    /** The provider's own words for a no, one line, never the key. */
    private fun said(body: String, code: Int, key: String): String {
        val o = try { JSONObject(body) } catch (e: Exception) { null }
        val inner = o?.optJSONObject("error")
        val words = inner?.optString("message").orEmpty().ifEmpty { o?.optString("error").orEmpty() }
        return Scrub.words(words.ifEmpty { "error $code" }, key).take(160)
    }

    private fun failed(p: Provider, code: Int, body: String, key: String): Answer.Failed {
        val why = when (code) {
            401, 403 -> Why.KEY
            429 -> Why.LIMIT
            else -> Why.OTHER
        }
        Log.i("DeskIT", "cloud: ${p.word} answered $code")
        return Answer.Failed(why, said(body, code, key))
    }

    /**
     * One recording to [p], with [key]. Blocking. The words come back trimmed; an
     * empty text is an answer too (nothing was said).
     */
    fun transcribe(c: Context, p: Provider, key: String, wav: ByteArray): Answer =
        if (p == Provider.GROQ) groq(c, key, wav) else gemini(c, key, wav)

    private fun groq(c: Context, key: String, wav: ByteArray): Answer {
        val boundary = "deskit" + UUID.randomUUID().toString().replace("-", "")
        val body = Multipart.body(boundary,
            listOf("model" to GROQ_MODEL, "language" to "he", "response_format" to "json",
                   "temperature" to "0"),
            "file", "dictation.wav", "audio/wav", wav)
        val t0 = SystemClock.elapsedRealtime()
        var conn: HttpURLConnection? = null
        return try {
            conn = open(c, host(c, GROQ_HOST) + "/openai/v1/audio/transcriptions", READ_MS).apply {
                requestMethod = "POST"
                doOutput = true
                setRequestProperty("Authorization", "Bearer $key")
                setRequestProperty("Content-Type", Multipart.contentType(boundary))
                setFixedLengthStreamingMode(body.size)
            }
            conn.outputStream.use { it.write(body) }
            val code = conn.responseCode
            val text = (if (code in 200..299) conn.inputStream else conn.errorStream)
                ?.bufferedReader()?.use { it.readText() } ?: ""
            if (code !in 200..299) return failed(Provider.GROQ, code, text, key)
            val words = JSONObject(text).optString("text", "").trim()
            Answer.Text(words, (SystemClock.elapsedRealtime() - t0) / 1000.0)
        } catch (e: IOException) {
            Log.i("DeskIT", "cloud: groq did not answer: ${e.javaClass.simpleName}")
            Answer.Failed(Why.NO_ANSWER, "")
        } catch (e: org.json.JSONException) {
            Log.i("DeskIT", "cloud: groq's answer is not JSON")
            Answer.Failed(Why.OTHER, "the answer could not be read")
        } finally {
            conn?.disconnect()
        }
    }

    private fun gemini(c: Context, key: String, wav: ByteArray): Answer {
        val payload = JSONObject()
            .put("contents", JSONArray().put(JSONObject().put("role", "user").put("parts", JSONArray()
                .put(JSONObject().put("inlineData", JSONObject().put("mimeType", "audio/wav")
                    .put("data", Base64.getEncoder().encodeToString(wav))))
                .put(JSONObject().put("text", GEMINI_ASK)))))
            .put("generationConfig", JSONObject().put("temperature", 0))
            .toString().toByteArray(Charsets.UTF_8)
        var last: Answer = Answer.Failed(Why.NO_ANSWER, "")
        val t0 = SystemClock.elapsedRealtime()
        for (model in GEMINI_MODELS) {
            var conn: HttpURLConnection? = null
            try {
                conn = open(c, host(c, GEMINI_HOST) + "/v1beta/models/$model:generateContent", READ_MS).apply {
                    requestMethod = "POST"
                    doOutput = true
                    setRequestProperty("x-goog-api-key", key)
                    setRequestProperty("Content-Type", "application/json")
                    setFixedLengthStreamingMode(payload.size)
                }
                conn.outputStream.use { it.write(payload) }
                val code = conn.responseCode
                val text = (if (code in 200..299) conn.inputStream else conn.errorStream)
                    ?.bufferedReader()?.use { it.readText() } ?: ""
                if (code == 404 || code == 429) {        // this model is gone or spent: the next
                    last = failed(Provider.GEMINI, code, text, key)
                    continue
                }
                if (code !in 200..299) return failed(Provider.GEMINI, code, text, key)
                val parts = JSONObject(text).optJSONArray("candidates")?.optJSONObject(0)
                    ?.optJSONObject("content")?.optJSONArray("parts")
                val words = StringBuilder()
                for (i in 0 until (parts?.length() ?: 0)) words.append(parts!!.optJSONObject(i)?.optString("text").orEmpty())
                return Answer.Text(words.toString().trim(), (SystemClock.elapsedRealtime() - t0) / 1000.0)
            } catch (e: IOException) {
                Log.i("DeskIT", "cloud: gemini did not answer: ${e.javaClass.simpleName}")
                return Answer.Failed(Why.NO_ANSWER, "")
            } catch (e: org.json.JSONException) {
                return Answer.Failed(Why.OTHER, "the answer could not be read")
            } finally {
                conn?.disconnect()
            }
        }
        return last
    }

    /** What a key test found: the provider took it, said no to it, or did not answer. */
    enum class Test { OK, REFUSED, OFFLINE }

    /** keyrow.probe's one small request, by the phone: the provider's list of models. */
    fun test(c: Context, p: Provider, key: String): Test {
        var conn: HttpURLConnection? = null
        return try {
            conn = if (p == Provider.GROQ) {
                open(c, host(c, GROQ_HOST) + "/openai/v1/models", TEST_MS).apply {
                    setRequestProperty("Authorization", "Bearer $key")
                }
            } else {
                open(c, host(c, GEMINI_HOST) + "/v1beta/models?pageSize=1", TEST_MS).apply {
                    setRequestProperty("x-goog-api-key", key)
                }
            }
            val code = conn.responseCode
            Log.i("DeskIT", "cloud: the ${p.word} key test said $code")
            when (code) {
                in 200..299 -> Test.OK
                in 400..499 -> if (code == 429) Test.OK else Test.REFUSED   // spent is still a key
                else -> Test.OFFLINE
            }
        } catch (e: IOException) {
            Test.OFFLINE
        } finally {
            conn?.disconnect()
        }
    }
}
