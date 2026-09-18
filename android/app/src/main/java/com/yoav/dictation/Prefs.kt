package com.yoav.dictation

import android.content.Context

/**
 * Where the PC is and how to prove we are allowed to talk to it.
 *
 * The defaults are this user's own machine, baked in so the keyboard works
 * the moment it is enabled — the APK is served over their private Tailscale
 * link and installed on their own phone, so there is no one else to leak a
 * token to. Both remain editable in the setup screen.
 */
object Prefs {
    private const val FILE = "dictation"
    private const val KEY_URL = "url"
    private const val KEY_TOKEN = "token"
    private const val KEY_SWITCH_BACK = "switch_back"
    private const val KEY_ORDER = "key_order"
    private const val KEY_SAID = "said"
    private const val KEY_NOTIFIED = "notified"

    /** How many of the phone's own dictations the home screen keeps. */
    const val SAID_KEEP = 30

    /**
     * Shown as the URL field's hint on a fresh install and used until a
     * real address is typed: a placeholder that resolves nowhere, not
     * the owner's own machine (it was, until the repository went public;
     * D22's QR pairing replaces this field altogether).
     */
    const val DEFAULT_URL = "https://your-pc.your-tailnet.ts.net"

    /**
     * The eight small keys, in the order they were designed: positions
     * 0–3 are the top row, 4–7 the bottom. Ids, not labels — the action
     * key's face changes per field and the order must not care.
     */
    val DEFAULT_ORDER = listOf(
        "backspace", "space", "period", "undo",
        "translate", "punctuate", "action", "switch")

    /**
     * The user's arrangement, or the default. Anything that is not a
     * permutation of exactly today's eight ids — a stale save from a
     * version with different keys — falls back whole rather than being
     * repaired, because a half-guessed layout moves keys the user placed.
     */
    fun keyOrder(c: Context): List<String> {
        val got = sp(c).getString(KEY_ORDER, null)?.split(',')
            ?: return DEFAULT_ORDER
        return if (got.sorted() == DEFAULT_ORDER.sorted()) got
        else DEFAULT_ORDER
    }

    fun saveKeyOrder(c: Context, order: List<String>) {
        sp(c).edit().putString(KEY_ORDER, order.joinToString(",")).apply()
    }

    private fun sp(c: Context) = c.getSharedPreferences(FILE, Context.MODE_PRIVATE)

    fun url(c: Context): String =
        sp(c).getString(KEY_URL, DEFAULT_URL)!!.trimEnd('/')

    fun token(c: Context): String = sp(c).getString(KEY_TOKEN, "") ?: ""

    /**
     * After the text lands, hop straight back to the everyday keyboard.
     *
     * Off by default. It sounded right in theory and was wrong in use:
     * the keyboard already has a Keyboard key, leaving is one deliberate
     * tap, and jumping away on its own breaks dictating two sentences in a
     * row — and breaks the translate key, which needs the keyboard to
     * still be there afterwards.
     */
    fun switchBack(c: Context): Boolean = sp(c).getBoolean(KEY_SWITCH_BACK, false)

    fun save(c: Context, url: String, token: String, switchBack: Boolean) {
        sp(c).edit()
            .putString(KEY_URL, url.trim().trimEnd('/'))
            .putString(KEY_TOKEN, token.trim())
            .putBoolean(KEY_SWITCH_BACK, switchBack)
            .apply()
    }

    /**
     * The phone's own "Said": every transcript this keyboard put into a
     * field, newest first, kept on the phone alone. The PC has the full
     * record in transcripts.log; this is the short one you read on the
     * sofa to copy a sentence again. A JSON array of [epoch-ms, text].
     */
    fun said(c: Context): List<Pair<Long, String>> {
        val raw = sp(c).getString(KEY_SAID, null) ?: return emptyList()
        return try {
            val arr = org.json.JSONArray(raw)
            (0 until arr.length()).map {
                val row = arr.getJSONArray(it)
                Pair(row.getLong(0), row.getString(1))
            }
        } catch (e: Exception) {
            emptyList()
        }
    }

    fun addSaid(c: Context, text: String) {
        val rows = listOf(Pair(System.currentTimeMillis(), text)) +
                said(c).take(SAID_KEEP - 1)
        val arr = org.json.JSONArray()
        for ((t, s) in rows) arr.put(org.json.JSONArray().put(t).put(s))
        sp(c).edit().putString(KEY_SAID, arr.toString()).apply()
    }

    fun clearSaid(c: Context) {
        sp(c).edit().remove(KEY_SAID).apply()
    }

    /**
     * Proposals of the second reading the phone has already rung for, so a
     * poll never rings twice for one sentence. A bounded set: ids are
     * timestamps, and a hundred of them is weeks.
     */
    fun wasNotified(c: Context, id: String): Boolean =
        (sp(c).getString(KEY_NOTIFIED, "") ?: "").split(',').contains(id)

    fun markNotified(c: Context, id: String) {
        val had = (sp(c).getString(KEY_NOTIFIED, "") ?: "")
            .split(',').filter { it.isNotEmpty() }
        val now = (listOf(id) + had).distinct().take(100)
        sp(c).edit().putString(KEY_NOTIFIED, now.joinToString(",")).apply()
    }

    /**
     * Accepts the whole URL the PC prints, token and all
     * ("https://host/#t=abc"), because retyping a 32-character secret on a
     * phone keyboard is how setup fails.
     */
    fun parsePasted(text: String): Pair<String, String>? {
        val s = text.trim()
        if (!s.startsWith("http")) return null
        val hash = s.indexOf("#t=")
        return if (hash < 0) Pair(s.trimEnd('/'), "")
        else Pair(s.substring(0, hash).trimEnd('/'), s.substring(hash + 3).trim())
    }
}
