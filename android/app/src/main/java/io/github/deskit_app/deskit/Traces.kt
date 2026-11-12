package io.github.deskit_app.deskit

import android.app.NotificationManager
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.util.Log

/**
 * What a person's words leave on this phone outside the sealed store, and the
 * one way it all goes.
 *
 * A phone is lent and sold, so out of the account means out: nobody holding it
 * next reads what was said on it, and neither does the next account signed in
 * on it. The roads out are Sign out, Use another account, finding itself on the
 * forgotten list, a session the server ended (Forget and Sign out of every PC
 * reach a phone that way, and a phone cannot tell them apart), a session it can
 * no longer open (the screen lock was taken away and the sealed store with it),
 * and another account arriving. Every one of them calls [wipe].
 *
 * What goes: the phone's Said; the second reading's proposals, whole sentences
 * on the notification shade; a sentence copied from here; and the pasted address
 * and token, which are a key to the PC and would put those proposals back on Home
 * at the next look; and where the PCs are: the addresses that answered and the
 * rows they came from ([Link.forget]); the account's cloud keys as this phone kept
 * them, sealed ([CloudKeys.forget]), and the text of a dictation the cloud carried
 * that has not reached the account yet ([Backup.forget]). The keyboard holds a transcript waiting for
 * a field, the recordings the disk refused and why the last try failed, and a
 * dictation can be on its way, a fresh one or one sent again: all of them read
 * [wipes], in this one process, and let go when it has moved.
 *
 * Recordings no PC has yet are not here, because they are the only copy of those
 * words: [Lock.dropRecordings] has the rule. What stays is the phone's own: the
 * keys' order and the switches. Android's own keyboard may have kept a copied
 * sentence in a clipboard history of its own, and nothing here can reach that.
 */
object Traces {
    /** The label on anything this app copies: how it knows its own on the clipboard. */
    const val CLIP = "DeskIT"

    /** How many times the words went, in this process. */
    @Volatile
    var wipes = 0
        private set

    /**
     * Quick, on any thread, and safe to run twice. The clipboard goes to the main
     * thread: Android 8 refuses a thread with no Looper the service itself ("Can't
     * create handler", measured on API 26 on 2026-11-06), and nearly every wipe runs
     * on one. It is owed from the first moment, so that a process that dies before
     * the look has left a note of it.
     */
    @Synchronized
    fun wipe(c: Context) {
        wipes++
        Prefs.forget(c)
        Link.forget(c)
        CloudKeys.forget(c)
        Backup.forget(c)
        // the account's channel, open on this session: it goes with the session
        Relay.forget()
        (c.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager).cancelAll()
        Prefs.clipOwed(c, true)
        val app = c.applicationContext
        Handler(Looper.getMainLooper()).post {
            if (clearClip(app) || Build.VERSION.SDK_INT < 29) Prefs.clipOwed(app, false)
        }
    }

    /**
     * One of our windows has the focus, which is what Android asks of a clipboard
     * read. A wipe with none in front could not look, and it is written down
     * because the process may well be gone by the time one comes.
     */
    fun focused(c: Context) {
        if (!Prefs.clipOwed(c)) return
        Prefs.clipOwed(c, false)
        clearClip(c)
    }

    /**
     * On the main thread. False when there was no answer. Android 10 and up answer
     * only the app with the focus or the keyboard in use, and the same null means an
     * empty clipboard. What anyone else copied is not ours to touch, so an unknown
     * clip stays.
     */
    private fun clearClip(c: Context): Boolean = try {
        val board = c.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
        val on = board.primaryClipDescription
        if (on?.label?.toString() == CLIP) {
            if (Build.VERSION.SDK_INT >= 28) board.clearPrimaryClip()
            else board.setPrimaryClip(ClipData.newPlainText("", ""))
        }
        on != null
    } catch (e: RuntimeException) {
        // A maker's clipboard must not stop a phone from leaving.
        Log.w("DeskIT", "the clipboard would not answer: ${e.javaClass.simpleName}")
        false
    }
}
