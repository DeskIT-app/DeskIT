package io.github.deskit_app.deskit

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import android.widget.Toast
import kotlin.concurrent.thread

/**
 * The second reading, as a notification.
 *
 * On the desk a proposal is a card in the corner for a few seconds and
 * then a row in the dashboard. On the phone it is this: "Did you mean…"
 * with the proposed sentence, Keep and No right on it, and a tap that
 * opens the review screen for the whole sentence. The PC learns only
 * from Keep — the same rule as the card — and the verdict travels the
 * same path a dashboard verdict does, so nothing here can teach a word
 * the desk would not have.
 *
 * Who polls: the keyboard, a few times after each dictation (the
 * reading takes three decodes and a language model, so the answer is
 * seconds to a minute behind the text), and the home screen when it
 * opens. Not a background service — a service polling all day for a
 * sentence a week is a battery bill with nothing to show for it.
 */
object Notify {
    const val CHANNEL = "second_reading"
    private const val CHANNEL_SAID = "said"
    const val ACTION_DECIDE = "io.github.deskit_app.deskit.DECIDE"
    const val EXTRA_ID = "id"
    const val EXTRA_VERDICT = "verdict"
    const val EXTRA_NOTIFICATION = "notification"

    fun channel(c: Context) {
        val nm = c.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        if (nm.getNotificationChannel(CHANNEL) != null) return
        nm.createNotificationChannel(
            NotificationChannel(CHANNEL, c.getString(R.string.channel_review),
                NotificationManager.IMPORTANCE_DEFAULT).apply {
                description = c.getString(R.string.channel_review_desc)
            })
    }

    fun allowed(c: Context): Boolean =
        Build.VERSION.SDK_INT < 33 ||
                c.checkSelfPermission("android.permission.POST_NOTIFICATIONS") ==
                PackageManager.PERMISSION_GRANTED

    /**
     * Ask the PC what waits and ring for every phone proposal not rung for
     * yet. Blocking; call from a thread. Returns what the PC answered, or
     * null when it could not be asked.
     */
    fun poll(c: Context): List<Transcriber.Proposal>? {
        if (!Link.ready(c)) return null
        val wipes = Traces.wipes
        val items = Link.proposals(c) ?: return null
        if (wipes != Traces.wipes) return null
        // Marked only once shown: with notifications not yet allowed the
        // proposal must still ring the day they are.
        if (allowed(c)) for (p in items) {
            if (!p.fromPhone || p.id.isEmpty() || Prefs.wasNotified(c, p.id)) continue
            Prefs.markNotified(c, p.id)
            show(c, p)
        }
        return items
    }

    private fun notificationId(id: String): Int = id.hashCode() and 0x7fffffff

    /**
     * A dictation came back and the field it was spoken into has gone: the
     * sentence is in Said, and this says so. [since] is [Traces.wipes] as it set
     * out: under the wipe's own lock, so it is either wiped or never shown.
     */
    fun landed(c: Context, text: String, since: Int) {
        if (!allowed(c)) return
        val nm = c.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        if (nm.getNotificationChannel(CHANNEL_SAID) == null) {
            nm.createNotificationChannel(NotificationChannel(
                CHANNEL_SAID, c.getString(R.string.said_title), NotificationManager.IMPORTANCE_DEFAULT))
        }
        val open = PendingIntent.getActivity(
            c, 0,
            Intent(c, HomeActivity::class.java).addFlags(
                Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
        val n = Notification.Builder(c, CHANNEL_SAID)
            .setSmallIcon(R.drawable.ic_stat_lamp)
            .setContentTitle(c.getString(R.string.said_title))
            .setContentText(text)
            .setStyle(Notification.BigTextStyle().bigText(text))
            .setContentIntent(open)
            .setAutoCancel(true)
            .build()
        synchronized(Traces) {
            if (since == Traces.wipes) nm.notify(notificationId("said$text"), n)
        }
    }

    fun show(c: Context, p: Transcriber.Proposal) {
        channel(c)
        val nid = notificationId(p.id)
        val open = PendingIntent.getActivity(
            c, nid,
            Intent(c, ReviewActivity::class.java)
                .putExtra(EXTRA_ID, p.id)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or
                        Intent.FLAG_ACTIVITY_CLEAR_TOP),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)

        fun verdict(v: String, req: Int): PendingIntent = PendingIntent.getBroadcast(
            c, nid * 4 + req,
            Intent(c, ReviewReceiver::class.java).setAction(ACTION_DECIDE)
                .putExtra(EXTRA_ID, p.id).putExtra(EXTRA_VERDICT, v)
                .putExtra(EXTRA_NOTIFICATION, nid),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)

        val why = p.changes.firstOrNull()?.why.orEmpty()
        val n = Notification.Builder(c, CHANNEL)
            .setSmallIcon(R.drawable.ic_stat_lamp)
            .setContentTitle(c.getString(R.string.review_title))
            .setContentText(p.proposed)
            .setStyle(Notification.BigTextStyle().bigText(
                if (why.isEmpty()) p.proposed else "${p.proposed}\n$why"))
            .setContentIntent(open)
            .setAutoCancel(true)
            .addAction(Notification.Action.Builder(null,
                c.getString(R.string.keep), verdict("accepted", 1)).build())
            .addAction(Notification.Action.Builder(null,
                c.getString(R.string.no), verdict("rejected", 2)).build())
            .build()
        (c.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager)
            .notify(nid, n)
    }

    fun dismiss(c: Context, id: String) {
        (c.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager)
            .cancel(notificationId(id))
    }
}

/**
 * Keep or No pressed on the notification itself. The verdict goes to the
 * PC on a thread; the notification comes down when the PC has it, and a
 * toast says which way it went — or that the PC could not be reached, in
 * which case the notification stays so the answer is not lost.
 */
class ReviewReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action != Notify.ACTION_DECIDE) return
        val id = intent.getStringExtra(Notify.EXTRA_ID) ?: return
        val verdict = intent.getStringExtra(Notify.EXTRA_VERDICT) ?: return
        val app = context.applicationContext
        val pending = goAsync()
        thread {
            val r = Link.ask(app) { Transcriber.reviewDecide(it, id, verdict) }
            android.os.Handler(android.os.Looper.getMainLooper()).post {
                when (r) {
                    is Transcriber.Result.Ok -> {
                        Notify.dismiss(app, id)
                        Toast.makeText(app, app.getString(
                            if (verdict == "accepted") R.string.learned
                            else R.string.noted), Toast.LENGTH_SHORT).show()
                    }
                    is Transcriber.Result.Err -> {
                        // 404: answered elsewhere already. Nothing to keep.
                        if (r.message.contains("no pending")) Notify.dismiss(app, id)
                        Toast.makeText(app, r.message, Toast.LENGTH_LONG).show()
                    }
                }
                pending.finish()
            }
        }
    }
}
