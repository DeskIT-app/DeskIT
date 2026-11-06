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
 *
 * Also what a person leaves behind, put there for the flows to watch it go: a
 * sentence in Said and a pasted line (`--es say`, `--es url`, `--es token`), and
 * what only a running keyboard holds (`--es ime plant|read|now|late`). The
 * keyboard's fields are private and an emulator has no voice to fill them with,
 * so this reaches the live service by reflection, as LeakCanary does.
 */
class ProbeReceiver : BroadcastReceiver() {

    override fun onReceive(c: Context, intent: Intent) {
        intent.getStringExtra("ime")?.let {
            keyboard(c, it)
            return
        }
        if (intent.hasExtra("wipe")) {
            Traces.wipe(c)
            Log.i("DeskIT", "probe: wiped")
            return
        }
        if (intent.hasExtra("say") || intent.hasExtra("url")) {
            intent.getStringExtra("url")?.let {
                Prefs.save(c, it, intent.getStringExtra("token").orEmpty(), false)
            }
            intent.getStringExtra("say")?.let { Prefs.addSaid(c, it, Traces.wipes) }
            Log.i("DeskIT", "probe: left")
            return
        }
        val done = goAsync()
        val posts = intent.getIntExtra("posts", 0)
        if (posts > 0) {
            // Many real POSTs in a row: a transport failure a flow meets once in
            // a hundred requests shows up here, by class, in the log.
            thread {
                val gap = intent.getLongExtra("gap", 0)
                repeat(posts) {
                    Account.broadcast(c, "stress", org.json.JSONObject().put("i", it))
                    if (gap > 0) Thread.sleep(gap)
                }
                Log.i("DeskIT", "probe: posts done")
                done.finish()
            }
            return
        }
        // What the keyboard pays at its first start in a process: run this right
        // after a kill, or it reads the cache.
        val t0 = System.nanoTime()
        Skin.font(c)
        Skin.fontBold(c)
        val fonts = (System.nanoTime() - t0) / 1_000_000
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
                "locked=${Sealed.locked(c)} lockable=${Sealed.lockable(c)} fonts=${fonts}ms")
            done.finish()
        }
    }

    private fun running(): DictationIme? = try {
        val thread = Class.forName("android.app.ActivityThread")
        val now = thread.getMethod("currentActivityThread").invoke(null)
        val all = thread.getDeclaredField("mServices").apply { isAccessible = true }.get(now)
        (all as Map<*, *>).values.firstOrNull { it is DictationIme } as DictationIme?
    } catch (e: ReflectiveOperationException) {
        Log.w("DeskIT", "probe: ${e.javaClass.simpleName}: ${e.message}")
        null
    }

    private fun held(name: String) =
        DictationIme::class.java.getDeclaredField(name).apply { isAccessible = true }

    /** A dictation coming back: [late] says it set out before the last wipe. */
    private fun comeBack(k: DictationIme, text: String, late: Boolean) {
        val mine = held("session").getInt(k)
        DictationIme::class.java.getDeclaredMethod("deliver", Transcriber.Result::class.java,
                                                   Int::class.java, Int::class.java)
            .apply { isAccessible = true }
            .invoke(k, Transcriber.Result.Ok(text), mine,
                    if (late) Traces.wipes - 1 else Traces.wipes)
    }

    private fun keyboard(c: Context, what: String) {
        val k = running()
        if (k == null) {
            Log.i("DeskIT", "probe: no keyboard is running")
            return
        }
        when (what) {
            "plant" -> {
                held("pending").set(k, "held-words")
                held("lastWav").set(k, ByteArray(8))
            }
            "now" -> comeBack(k, "landed-words", false)
            "late" -> comeBack(k, "late-words", true)
        }
        Log.i("DeskIT", "probe: ime pending=${held("pending").get(k) != null} " +
            "wav=${held("lastWav").get(k) != null} said=${Prefs.said(c).size}")
    }
}
