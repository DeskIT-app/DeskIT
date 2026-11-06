package io.github.deskit_app.deskit

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.util.Log
import java.security.Signature
import kotlin.concurrent.thread

/**
 * Debug builds only: can this phone open what it sealed, right now, and can it
 * sign? A receiver runs with the screen locked, which no Activity here does, so
 * it is how "a stolen, locked phone cannot use it" gets tested and not assumed.
 *
 *   adb shell am broadcast -n <package>/.ProbeReceiver
 *
 * One line in the log and nothing else: it says whether, never what.
 */
class ProbeReceiver : BroadcastReceiver() {

    override fun onReceive(c: Context, intent: Intent) {
        val done = goAsync()
        thread {
            val sealed = try {
                if (Sealed.get(c, "session") == null) "none" else "opened"
            } catch (e: Sealed.NotNow) {
                "notnow"
            }
            val signs = try {
                val alias = java.security.KeyStore.getInstance("AndroidKeyStore")
                    .apply { load(null) }
                    .aliases().toList().firstOrNull { it.startsWith("deskit.client.") }
                val key = alias?.let {
                    java.security.KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
                        .getKey(it, null) as java.security.PrivateKey
                }
                if (key == null) "none" else {
                    Signature.getInstance("NONEwithECDSA").run {
                        initSign(key)
                        update(ByteArray(32))
                        sign()
                    }
                    "signed"
                }
            } catch (e: Exception) {
                "refused"
            }
            Log.i("DeskIT", "probe: sealed=$sealed signs=$signs " +
                "locked=${Sealed.locked(c)} lockable=${Sealed.lockable(c)}")
            done.finish()
        }
    }
}
