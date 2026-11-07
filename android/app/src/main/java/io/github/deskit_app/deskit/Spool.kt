package io.github.deskit_app.deskit

import android.app.job.JobInfo
import android.app.job.JobParameters
import android.app.job.JobScheduler
import android.app.job.JobService
import android.content.ComponentName
import android.content.Context
import android.util.Log
import java.io.File
import java.io.FileOutputStream
import java.io.IOException
import java.util.Locale
import java.util.UUID
import java.util.concurrent.atomic.AtomicBoolean
import kotlin.concurrent.thread

/**
 * The files themselves, with no Android in them, so the JVM can hold the rules.
 *
 * One file per recording, named by when it was made: the oldest sorts first, and
 * a rename makes it appear whole, so a process killed in the middle of a write
 * leaves a `.tmp` and never half a recording. A name that is not ours is left
 * where it is and never sent.
 */
class SpoolFiles(private val dir: File, private val maxBytes: Long = Spool.MAX_BYTES,
                 private val keepMs: Long = Spool.KEEP_MS) {

    /**
     * One recording. [file] is null when the disk took nothing and [wav] is all
     * there is: the dictation still goes, it just would not outlive the process.
     * [dropped] is how many older ones keeping this one cost.
     */
    class Item(val file: File?, val wav: ByteArray?, val dropped: Int = 0) {
        val key: String get() = file?.name.orEmpty()

        /** The recording, from the disk: a wipe can have taken it. */
        fun bytes(): ByteArray = wav ?: file!!.readBytes()
    }

    private fun all(): List<File> = dir.listFiles()?.toList().orEmpty()

    /** Oldest first. Only what this class wrote. */
    fun items(): List<File> = all().filter { NAME.matches(it.name) }.sortedBy { it.name }

    /** What Sign out names: anything that is a recording, ours by name or not. */
    fun count(): Int = all().count { it.name.endsWith(WAV) }

    private fun bytes(): Long = all().sumOf { it.length() }

    /** Kept for good before anything is sent. [IOException] for a phone with no room. */
    fun keep(wav: ByteArray, now: Long): Item {
        dir.mkdirs()
        // Locale.ROOT: a phone set to Arabic or Persian writes its own digits otherwise.
        val name = "%013d-%s".format(Locale.ROOT, now, UUID.randomUUID().toString().take(8)) + WAV
        val tmp = File(dir, name + TMP)
        try {
            FileOutputStream(tmp).use {
                it.write(wav)
                it.fd.sync()
            }
            val whole = File(dir, name)
            if (!tmp.renameTo(whole)) throw IOException("the recording could not be kept")
            return Item(whole, null, prune(now, whole))
        } finally {
            tmp.delete()
        }
    }

    /**
     * Past [keepMs] goes, and past [maxBytes] the oldest go first, never [spare].
     * How many went. A `.tmp` left by a kill goes too and counts for nothing.
     */
    fun prune(now: Long, spare: File? = null): Int {
        for (f in all()) if (f.name.endsWith(TMP)) f.delete()
        var gone = 0
        for (f in items()) {
            if (f == spare) continue
            val made = f.name.take(STAMP).toLongOrNull() ?: continue
            if (now - made > keepMs && f.delete()) gone++
        }
        var left = bytes()
        for (f in items()) {
            if (left <= maxBytes) break
            if (f == spare) continue
            val size = f.length()
            if (f.delete()) {
                left -= size
                gone++
            }
        }
        return gone
    }

    private companion object {
        const val STAMP = 13
        const val WAV = ".wav"
        const val TMP = ".tmp"
        val NAME = Regex("\\d{13}-[0-9a-f]{8}\\.wav")
    }
}

/**
 * Every recording stays on the phone until a PC has it, in app-private storage,
 * so nothing lives in one slot in memory any more, where the next dictation wrote
 * over it and a killed process lost it. Up to 50 MB, about 26 minutes of speech,
 * the oldest going first; a week at most (PHONE_LINK_PLAN.md stage 1).
 *
 * What is here goes on the next link: when the keyboard or Home finds a PC, and in
 * the background on a job that asks for the network and exists only while
 * something waits. Never a service: nothing runs when nothing was said. Its text
 * has no field to go to any more, so it lands in Said with a notification.
 *
 * "A PC has it" means a PC answered with what it heard. A process killed after
 * the PC answered and before the file went sends it once more: a duplicate in
 * transcripts.log, the one failure here that loses nothing.
 *
 * It is the only copy of those words, so [Traces] leaves it: [Lock.dropRecordings]
 * has that rule, and a send stops the moment [Traces.wipes] moves.
 */
object Spool {
    const val DIR = "spool"
    const val MAX_BYTES = 50L * 1024 * 1024
    const val KEEP_MS = 7L * 24 * 3600 * 1000

    private const val JOB = 1
    /**
     * Longer than a dictation takes to come back, so the job asked for at [keep] is
     * called off by the answer, and only a process that died ever gets it.
     */
    private const val SOON_MS = 60L * 1000
    /** How long a recording with no link waits to ask again, on a network that could carry it. */
    private const val AGAIN_MS = 30L * 60 * 1000

    /** Files on their way right now: the keyboard's own send and the background's never cross. */
    private val inHand = HashSet<String>()
    private val draining = AtomicBoolean(false)

    fun files(c: Context) = SpoolFiles(File(c.filesDir, DIR))

    /**
     * On disk before it goes anywhere, and in hand, with a turn in the background
     * already asked for: whatever kills this process now, nothing has to remember
     * the recording but the disk. Never fails: see [SpoolFiles.Item].
     */
    fun keep(c: Context, wav: ByteArray): SpoolFiles.Item = try {
        files(c).keep(wav, System.currentTimeMillis()).also {
            claim(it)
            schedule(c)
        }
    } catch (e: IOException) {
        Log.w("DeskIT", "spool: a recording could not be kept: ${e.javaClass.simpleName}")
        SpoolFiles.Item(null, wav)
    }

    /** False when someone else has it, or it has gone. */
    @Synchronized
    fun claim(item: SpoolFiles.Item): Boolean {
        if (item.file == null) return item.wav != null
        return item.file.exists() && inHand.add(item.key)
    }

    /** Back in the queue, for whoever comes next. */
    @Synchronized
    fun free(item: SpoolFiles.Item) {
        inHand.remove(item.key)
    }

    /** A PC has it, or will never take it. With nothing left, the turn is called off. */
    @Synchronized
    fun done(c: Context, item: SpoolFiles.Item) {
        inHand.remove(item.key)
        item.file?.delete()
        if (!waiting(c)) c.getSystemService(JobScheduler::class.java)?.cancel(JOB)
    }

    fun waiting(c: Context): Boolean = files(c).items().isNotEmpty()

    /** On a thread: what is here, if a PC will take it. True when something still waits. */
    fun drain(c: Context): Boolean {
        val wipes = Traces.wipes
        if (!Link.ready(c)) return false
        if (!draining.compareAndSet(false, true)) return true
        try {
            val store = files(c)
            val gone = store.prune(System.currentTimeMillis())
            if (gone > 0) Log.w("DeskIT", "spool: $gone recording(s) past their time went")
            for (f in store.items()) {
                val item = SpoolFiles.Item(f, null)
                if (wipes != Traces.wipes) return false
                if (!claim(item)) continue
                val r = Link.dictate(c, item)
                if (wipes != Traces.wipes) {
                    free(item)
                    return false
                }
                when {
                    r is Transcriber.Result.Ok -> {
                        val text = r.text.trim()
                        if (text.isNotEmpty()) {
                            Prefs.addSaid(c, text, wipes)
                            Notify.landed(c, text, wipes)
                        }
                        done(c, item)
                    }
                    r is Transcriber.Result.Err && r.why == Transcriber.Why.REFUSED -> {
                        Log.w("DeskIT", "spool: a PC will never take this one: it goes")
                        done(c, item)
                    }
                    else -> {
                        free(item)
                        return true
                    }
                }
            }
            return store.items().isNotEmpty()
        } finally {
            draining.set(false)
        }
    }

    /** Ask for a turn in the background, unless one is already asked for. */
    fun schedule(c: Context, later: Boolean = false) {
        val js = c.getSystemService(JobScheduler::class.java) ?: return
        if (js.getPendingJob(JOB) != null) return
        // A home door is reached on a home network, so a phone out on mobile data
        // wakes for nothing. The pasted line goes wherever its link goes.
        val network = if (Link.pasted(c) == null) JobInfo.NETWORK_TYPE_UNMETERED
                      else JobInfo.NETWORK_TYPE_ANY
        js.schedule(JobInfo.Builder(JOB, ComponentName(c, SpoolJob::class.java))
            .setRequiredNetworkType(network)
            .setMinimumLatency(if (later) AGAIN_MS else SOON_MS)
            .setBackoffCriteria(AGAIN_MS, JobInfo.BACKOFF_POLICY_LINEAR)
            .build())
    }

    /** What the keyboard and Home do when they find a PC: now, on a thread. */
    fun kick(c: Context) {
        val app = c.applicationContext
        if (!waiting(app)) return
        thread(name = "spool") { if (drain(app)) schedule(app, later = true) }
    }
}

/** One turn at the spool, on JobScheduler's say-so: a network has come. */
class SpoolJob : JobService() {
    override fun onStartJob(params: JobParameters): Boolean {
        val app = applicationContext
        thread(name = "spool-job") {
            jobFinished(params, Spool.drain(app))
        }
        return true
    }

    /** The system took the network away: the next turn asks again, whatever this one found. */
    override fun onStopJob(params: JobParameters): Boolean = true
}
