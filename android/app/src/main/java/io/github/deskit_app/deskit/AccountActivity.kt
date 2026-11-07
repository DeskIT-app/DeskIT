package io.github.deskit_app.deskit

import android.app.Activity
import android.content.Intent
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.widget.LinearLayout
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
    private var queued: (() -> Lock.State)? = null
    private var drawn = ""
    /** A word that came with us, from the browser's way back. */
    private var word = ""

    override fun onCreate(saved: Bundle?) {
        super.onCreate(saved)
        screens = AccountScreens(this)
        word = intent?.getStringExtra(AuthActivity.EXTRA_WORD).orEmpty()
        val col = Skin.page(this)
        col.addView(Skin.header(this, getString(R.string.your_account)) { finish() })
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

    /**
     * One look, on a thread: the pass can take a request or two and a code. A
     * press that lands while a poll is out waits its turn behind it and is
     * never dropped: a poll can come again, a person's press does not.
     */
    private fun look(work: (() -> Lock.State)? = null) {
        if (looking) {
            if (work != null) queued = work
            return
        }
        looking = true
        thread {
            val st = work?.invoke() ?: Lock.look(this) { early -> runOnUiThread { show(early) } }
            if (st is Lock.State.Ready) readRows()
            runOnUiThread {
                looking = false
                val next = queued
                queued = null
                if (next != null) {
                    look(next)
                    return@runOnUiThread
                }
                show(st)
                if (onScreen && waits(st)) ui.postDelayed({ if (onScreen) look() }, Lock.POLL_MS)
            }
        }
    }

    /** The account's rows, cached for the road to the PC. No answer is no harm. */
    private fun readRows() {
        try {
            Lock.devices(this)
        } catch (e: Account.Failed) {
            // the next look reads them
        } catch (e: Sealed.NotNow) {
            // the same
        }
    }

    private fun waits(st: Lock.State): Boolean = when (st) {
        is Lock.State.Waiting, is Lock.State.NoLock, is Lock.State.Preparing -> true
        is Lock.State.Trouble -> st.polls
        else -> false
    }

    /** Only when something changed: a poll must not take the focus off a button. */
    private fun show(st: Lock.State) {
        val key = when (st) {
            is Lock.State.SignedOut -> "out:${st.words}:$word"
            is Lock.State.Preparing -> "preparing"
            is Lock.State.Waiting -> "waiting:${st.code}:${st.word}:${st.pressed}"
            is Lock.State.NoLock -> "nolock"
            is Lock.State.Declined -> "declined"
            is Lock.State.Ready -> "ready"
            is Lock.State.Changed -> "changed:${st.refused}"
            is Lock.State.NotNow -> "notnow:${st.words}"
            is Lock.State.Trouble -> "trouble:${st.words}"
            is Lock.State.Leaving -> "leaving"
        }
        if (key == drawn) return
        if (drawn.isNotEmpty()) Skin.settle(box)
        drawn = key
        box.removeAllViews()
        box.addView(when (st) {
            is Lock.State.SignedOut -> screens.signIn(word.ifEmpty { st.words }) { signIn() }
            is Lock.State.Preparing -> screens.preparing()
            is Lock.State.Waiting -> screens.waiting(st.code, st.email, st.word, st.pressed,
                                                     { same(st) }, { leave() })
            is Lock.State.NoLock -> screens.noLock(st.email) { leave() }
            is Lock.State.Declined -> screens.declined(st.email, { ask() }, { leave() })
            is Lock.State.Ready -> screens.ready { finish() }
            is Lock.State.Changed ->
                if (st.refused) screens.refused(st.email) { leave() }
                else screens.changed({ answer(false) }, { answer(true) })
            is Lock.State.NotNow -> screens.trouble(st.words) { look() }
            is Lock.State.Trouble -> screens.trouble(st.words) { look() }
            is Lock.State.Leaving -> screens.leaving()
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

    /**
     * The screen answers the press at once and the pass catches up behind it. The
     * press carries the code it was made on: if that code has gone by then, the
     * answer is the new one on screen, waiting for a press of its own.
     */
    private fun same(st: Lock.State.Waiting) {
        show(Lock.State.Waiting(st.code, st.email, st.word, true))
        look { Lock.sameCode(this, st.code) { early -> runOnUiThread { show(early) } } }
    }

    /** "Use another account", which is leaving: [Lock.signOut]. */
    private fun leave() {
        show(Lock.State.Leaving)
        look {
            Lock.signOut(this)
            Lock.look(this)
        }
    }
}
