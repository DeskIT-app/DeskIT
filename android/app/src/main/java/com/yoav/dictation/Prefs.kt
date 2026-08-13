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

    const val DEFAULT_URL = "https://yoav.example.ts.net"

    private fun sp(c: Context) = c.getSharedPreferences(FILE, Context.MODE_PRIVATE)

    fun url(c: Context): String =
        sp(c).getString(KEY_URL, DEFAULT_URL)!!.trimEnd('/')

    fun token(c: Context): String = sp(c).getString(KEY_TOKEN, "") ?: ""

    /** After the text lands, hop straight back to the everyday keyboard. */
    fun switchBack(c: Context): Boolean = sp(c).getBoolean(KEY_SWITCH_BACK, true)

    fun save(c: Context, url: String, token: String, switchBack: Boolean) {
        sp(c).edit()
            .putString(KEY_URL, url.trim().trimEnd('/'))
            .putString(KEY_TOKEN, token.trim())
            .putBoolean(KEY_SWITCH_BACK, switchBack)
            .apply()
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
