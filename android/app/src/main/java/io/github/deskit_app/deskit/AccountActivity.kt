package io.github.deskit_app.deskit

import android.app.Activity
import android.content.Intent
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.widget.LinearLayout
import android.widget.ScrollView
import kotlin.concurrent.thread

/**
 * The road into the account, one page whatever the state: sign in, approve,
 * ready, or the lock changed. It asks [Lock] where this phone stands and draws
 * the answer, and while something waits on another device it looks again every
 * three seconds. There is no socket on a phone: this page is the only thing
 * that polls, and only while it is on screen. A phone killed meanwhile picks up
 * here, with the same code.
 */
class AccountActivity : Activity() {

    private lateinit var box: LinearLayout
    private lateinit var screens: AccountScreens
    private val ui = Handler(Looper.getMainLooper())
    private var onScreen = false
    private var looking = false
    private var drawn = ""
    /** A word that came with us, from the browser's way back. */
    private var word = ""

    override fun onCreate(saved: Bundle?) {
        super.onCreate(saved)
        screens = AccountScreens(this)
        word = intent?.getStringExtra(AuthActivity.EXTRA_WORD).orEmpty()
        val col = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            layoutDirection = View.LAYOUT_DIRECTION_LTR
            val p = Skin.dp(this@AccountActivity, 20)
            setPadding(p, Skin.dp(this@AccountActivity, 24), p, Skin.dp(this@AccountActivity, 32))
        }
        setContentView(ScrollView(this).apply {
            setBackgroundColor(Skin.BG)
            isVerticalScrollBarEnabled = false
            addView(col, ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT)
        })
        col.addView(LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            setPadding(0, 0, 0, Skin.dp(this@AccountActivity, 18))
            addView(Skin.backButton(this@AccountActivity) { finish() })
            addView(Skin.text(this@AccountActivity, getString(R.string.your_account), 26f,
                              Skin.FG, heavy = true))
        })
        box = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        col.addView(box)
    }

    /** Back from the browser with this page already open underneath. */
    override fun onNewIntent(next: Intent?) {
        super.onNewIntent(next)
        word = next?.getStringExtra(AuthActivity.EXTRA_WORD).orEmpty()
        drawn = ""
    }

    override fun onResume() {
        super.onResume()
        onScreen = true
        look()
    }

    override fun onPause() {
        super.onPause()
        onScreen = false
        ui.removeCallbacksAndMessages(null)
    }

    /** One look, on a thread: the pass can take a request or two and a code. */
    private fun look(work: (() -> Lock.State)? = null) {
        if (looking) return
        looking = true
        thread {
            val st = work?.invoke() ?: Lock.look(this) { early -> runOnUiThread { show(early) } }
            val pcs = if (st is Lock.State.Ready) names() else emptyList()
            runOnUiThread {
                looking = false
                show(st, pcs)
                if (onScreen && waits(st)) ui.postDelayed({ if (onScreen) look() }, Lock.POLL_MS)
            }
        }
    }

    private fun names(): List<String> = try {
        Lock.devices(this).filter { it.isPc }.map { it.name }
    } catch (e: Account.Failed) {
        emptyList()
    } catch (e: Sealed.NotNow) {
        emptyList()
    }

    private fun waits(st: Lock.State): Boolean = when (st) {
        is Lock.State.Waiting, is Lock.State.NoLock, is Lock.State.Preparing,
        is Lock.State.Trouble -> true
        else -> false
    }

    /** Only when something changed: a poll must not take the focus off a button. */
    private fun show(st: Lock.State, pcs: List<String> = emptyList()) {
        val key = when (st) {
            is Lock.State.SignedOut -> "out:${st.words}:$word"
            is Lock.State.Preparing -> "preparing"
            is Lock.State.Waiting -> "waiting:${st.code}:${st.word}"
            is Lock.State.NoLock -> "nolock"
            is Lock.State.Declined -> "declined"
            is Lock.State.Ready -> "ready:$pcs"
            is Lock.State.Changed -> "changed:${st.refused}"
            is Lock.State.NotNow -> "notnow:${st.words}"
            is Lock.State.Trouble -> "trouble:${st.words}"
        }
        if (key == drawn) return
        drawn = key
        box.removeAllViews()
        box.addView(when (st) {
            is Lock.State.SignedOut -> screens.signIn(word.ifEmpty { st.words }) { signIn() }
            is Lock.State.Preparing -> screens.preparing(st.email)
            is Lock.State.Waiting -> screens.waiting(st.code, st.email, st.word) { leave() }
            is Lock.State.NoLock -> screens.noLock(st.email, "") { leave() }
            is Lock.State.Declined -> screens.declined(st.email, { ask() }, { leave() })
            is Lock.State.Ready -> screens.ready(pcs) { finish() }
            is Lock.State.Changed ->
                if (st.refused) screens.refused()
                else screens.changed({ answer(false) }, { answer(true) })
            is Lock.State.NotNow -> screens.trouble(st.words) { look() }
            is Lock.State.Trouble -> screens.trouble(st.words) { look() }
        })
    }

    private fun signIn() {
        try {
            word = ""
            Account.beginSignIn(this)
        } catch (e: Account.Failed) {
            word = e.message.orEmpty()
            look()
        } catch (e: Sealed.NotNow) {
            word = Sealed.words(this, e)
            look()
        }
    }

    private fun answer(yes: Boolean) {
        look { Lock.answer(this, yes) { early -> runOnUiThread { show(early) } } }
    }

    private fun ask() {
        look { Lock.askAgain(this) { early -> runOnUiThread { show(early) } } }
    }

    /** "Use another account": this phone holds nothing of the account yet. */
    private fun leave() {
        look {
            Lock.signOut(this)
            Lock.look(this)
        }
    }
}
