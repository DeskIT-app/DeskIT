package io.github.deskit_app.deskit

/**
 * Which rows of the account are this very phone (2026-11-28).
 *
 * A device's id lives in the app's own storage, sealed, so that it cannot be copied
 * to another phone. The price: an install that went without a Sign out (the app
 * removed, or its data cleared) left its row on the account, and the next install
 * was a second row. The owner removed the old keyboard, installed 1.0.7 and paired,
 * and his PC listed his phone twice, one "dictated here yesterday" and one "today".
 * Android tells an app nothing as it is removed, so the row cannot go at that moment.
 *
 * So a row says which phone wrote it. The mark is a hash of the account and of the
 * id Android gives this app on this phone (Settings.Secure.ANDROID_ID: since Android
 * 8 one per signing key, user and device; the same after the app is removed and
 * installed again; another on another phone, in another profile and after a factory
 * reset). It travels inside the sealed `link`, which the server cannot read. Once an
 * install holds the key and has written its own row, it forgets every other phone
 * row that carries its mark, the ordinary way, list first (Lock.retireEarlier).
 *
 * Two installs that are both alive never share a mark: Android allows one install
 * of a package per user and device. A stable device id was the other road and is
 * closed: Sign out on a phone is Forget on itself, the list never lets an id back,
 * and an id that came out the same after every install would be refused for good.
 *
 * Nothing of Android's here, so `gradle jvmChecks` holds it.
 */
internal object SamePhone {
    /** The field in a phone's link. A row from before it has none, and matches nothing. */
    const val FIELD = "same"

    /** A mark's length, in hex characters. */
    const val HEX = 32

    private const val LABEL = "deskit/same-phone/v1"

    /**
     * Not an id: what a broken ROM or an old emulator answers for every phone
     * ("9774d56d682e549c" is the one a batch of Android 2.2 phones shared). A mark
     * made of one would name every such phone as this one.
     */
    private val NOBODY = setOf("9774d56d682e549c", "unknown", "null")

    /** This phone's mark in [uid]'s account, or "" where Android names no id. */
    fun mark(uid: String, androidId: String?): String {
        val id = androidId.orEmpty().trim().lowercase()
        if (uid.isEmpty() || id.length < 8 || id in NOBODY || id.all { it == '0' }) return ""
        return Crypt.hex(Crypt.sha256("$LABEL\u0000$uid\u0000$id".toByteArray(Charsets.UTF_8))).take(HEX)
    }

    /** One row of the account, as far as this needs it. */
    class Row(val id: String, val phone: Boolean, val mark: String)

    /**
     * The rows to forget: every other phone row that carries this phone's mark. A
     * phone with no mark forgets nobody, and so does one that does not know its id.
     */
    fun earlier(me: String, mine: String, rows: List<Row>): List<String> =
        if (mine.length != HEX || me.isEmpty()) emptyList()
        else rows.filter { it.phone && it.id.isNotEmpty() && it.id != me && it.mark == mine }
            .map { it.id }
}
