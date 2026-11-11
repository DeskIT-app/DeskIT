package io.github.deskit_app.deskit

import android.content.Context
import android.util.Log
import org.json.JSONException
import org.json.JSONObject

/**
 * The person's cloud keys on a phone (PHONE_LINK_PLAN.md stage 2b): the account's own
 * `vault` rows, one per name, sealed under the account key exactly as vault.py seals
 * them (`{"v": <key>}` under `vault/<uid>/<name>`), so a key added here is a key every
 * PC of the account pulls through vault.import_keys, and the other way round.
 *
 * **Where a key is.** In the account, sealed. On the phone: the same sealed rows, kept
 * sealed again by Keystore ([Sealed]), and whether each name holds a key, which says
 * nothing about the key. A value is opened in memory for one request ([use]) and
 * dropped. It is never written down, logged or put in a message.
 *
 * **A row is written only on a press** ([save], [remove]): this phone has no slot of
 * its own, so the trap AGENTS.md names, a new empty slot read as "the key was removed",
 * cannot happen here. A removal is `{"v": ""}` through the seal, which import_keys
 * reads as a removal; an empty plaintext would not open and would be skipped.
 */
object CloudKeys {
    private const val CACHE = "cloud_keys"
    private const val FILE = "cloud_keys"
    private const val READ_AT = "read_at"
    /** Read again after this long, when a screen or the keyboard looks. */
    const val STALE_MS = 10 * 60_000L

    val NAMES = listOf("groq", "gemini")

    private fun sp(c: Context) = c.getSharedPreferences(FILE, Context.MODE_PRIVATE)

    /** Does the account hold a key under [name], as of the last read. No network. */
    fun have(c: Context, name: String): Boolean = sp(c).getBoolean("have_$name", false)

    /** The provider the backup would use: Groq first, Gemini only when it is the one there. */
    fun provider(c: Context): Cloud.Provider? = when {
        have(c, "groq") -> Cloud.Provider.GROQ
        have(c, "gemini") -> Cloud.Provider.GEMINI
        else -> null
    }

    fun stale(c: Context): Boolean =
        System.currentTimeMillis() - sp(c).getLong(READ_AT, 0) > STALE_MS

    /**
     * The account's key rows, read and kept. Blocking. [Account.Failed] with no answer,
     * [Sealed.NotNow] on a phone that cannot open its own store now.
     */
    @Synchronized
    fun refresh(c: Context) {
        val wipes = Traces.wipes
        val r = Account.rest(c, "GET", "vault?select=name,cipher,updated_at")
        if (!r.ok) throw Account.Failed(r.said())
        val rows = r.rows()
        val kept = JSONObject()
        for (i in 0 until rows.length()) {
            val o = rows.optJSONObject(i) ?: continue
            val name = o.optString("name")
            if (name in NAMES && o.optString("cipher").isNotEmpty()) kept.put(name, o.optString("cipher"))
        }
        val held = Lock.withKey(c) { uid, key ->
            NAMES.associateWith { name ->
                kept.optString(name).isNotEmpty() && valueOf(key, uid, name, kept.optString(name)).isNotEmpty()
            }
        }
        if (wipes != Traces.wipes) return           // left the account on the way
        Sealed.putText(c, CACHE, kept.toString())
        val e = sp(c).edit().putLong(READ_AT, System.currentTimeMillis())
        for ((name, there) in held) e.putBoolean("have_$name", there)
        e.commit()
        Log.i("DeskIT", "keys: read, ${held.count { it.value }} held")
    }

    /** [refresh] when it is due, swallowing what it says: for a screen or the keyboard. */
    fun refreshIfStale(c: Context) {
        if (!stale(c) || !Link.joined(c)) return
        try {
            refresh(c)
        } catch (e: Account.Failed) {
            Log.i("DeskIT", "keys: not read now")
        } catch (e: Sealed.NotNow) {
            Log.i("DeskIT", "keys: wait for the seal")
        }
    }

    /** One sealed row opened: the key, or "" for a removal or a row that does not open. */
    private fun valueOf(key: ByteArray, uid: String, name: String, cipher: String): String = try {
        JSONObject(Crypt.openText(key, cipher, Crypt.aadVault(uid, name))).optString("v", "")
    } catch (e: Crypt.Refused) {
        Log.i("DeskIT", "keys: the $name row did not open")
        ""
    } catch (e: JSONException) {
        ""
    }

    /**
     * [work] with the key for [p], opened in memory from the kept row, or null when the
     * account holds none. The value goes nowhere but [work], which must not keep it.
     */
    fun <T> use(c: Context, p: Cloud.Provider, work: (String) -> T): T? {
        val cipher = try {
            JSONObject(Sealed.getText(c, CACHE) ?: "{}").optString(p.word)
        } catch (e: JSONException) {
            ""
        }
        if (cipher.isEmpty()) return null
        val value = Lock.withKey(c) { uid, key -> valueOf(key, uid, p.word, cipher) }
        if (value.isEmpty()) return null
        return work(value)
    }

    /**
     * A key into the account: sealed, written to its row, and the PCs told
     * (`changed: vault`), so a running PC pulls it at once. An empty [value] is a
     * removal. Blocking; [Account.Failed] when the account did not take it.
     */
    @Synchronized
    fun save(c: Context, name: String, value: String) {
        require(name in NAMES)
        val wipes = Traces.wipes
        val cipher = Lock.withKey(c) { uid, key ->
            val sealed = Crypt.sealText(key, JSONObject().put("v", value).toString(),
                                        Crypt.aadVault(uid, name))
            val r = Account.rest(c, "POST", "vault?on_conflict=user_id,name", JSONObject()
                .put("user_id", uid).put("name", name).put("cipher", sealed),
                "resolution=merge-duplicates,return=minimal")
            if (!r.ok) throw Account.Failed(r.said())
            sealed
        }
        if (wipes != Traces.wipes) return
        val kept = try {
            JSONObject(Sealed.getText(c, CACHE) ?: "{}")
        } catch (e: JSONException) {
            JSONObject()
        }
        Sealed.putText(c, CACHE, kept.put(name, cipher).toString())
        sp(c).edit().putBoolean("have_$name", value.isNotEmpty()).commit()
        val s = Account.session(c)
        if (s != null) {
            Account.broadcast(c, "changed", JSONObject().put("device", Lock.deviceId(c, s.uid))
                .put("stores", org.json.JSONArray().put("vault")))
        }
        Log.i("DeskIT", "keys: the $name row went out (${if (value.isEmpty()) "removed" else "a key"})")
    }

    fun remove(c: Context, name: String) = save(c, name, "")

    /** On every road out of the account ([Traces]): the rows and what they said. */
    fun forget(c: Context) {
        Sealed.delete(c, CACHE)
        sp(c).edit().clear().commit()
    }
}
