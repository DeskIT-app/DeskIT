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

    /**
     * Kept for good before anything is sent. [IOException] for a phone with no room.
     * [spare] are the names on their way, which making room never takes.
     */
    fun keep(wav: ByteArray, now: Long, spare: Set<String> = emptySet()): Item {
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
            return Item(whole, null, prune(now, spare + name))
        } finally {
            tmp.delete()
        }
    }

    /**
     * Past [keepMs] goes, and past [maxBytes] the oldest go first, never one named in
     * [spare]. How many went. A `.tmp` left by a kill goes too and counts for nothing.
     */
    fun prune(now: Long, spare: Set<String> = emptySet()): Int {
        for (f in all()) if (f.name.endsWith(TMP)) f.delete()
        var gone = 0
        for (f in items()) {
            if (f.name in spare) continue
            val made = made(f) ?: continue
            if (now - made > keepMs && f.delete()) gone++
        }
        var left = bytes()
        for (f in items()) {
            if (left <= maxBytes) break
            if (f.name in spare) continue
            val size = f.length()
            if (f.delete()) {
                left -= size
                gone++
            }
        }
        return gone
    }

    /**
     * When the oldest recording not named in [spare] has had its time, or null when
     * there is none: when the sweep is due.
     */
    fun dueAt(spare: Set<String> = emptySet()): Long? =
        items().firstOrNull { it.name !in spare }?.let { made(it) }?.plus(keepMs)

    private companion object {
        const val STAMP = 13
        const val WAV = ".wav"
        const val TMP = ".tmp"
        val NAME = Regex("\\d{13}-[0-9a-f]{8}\\.wav")

        fun made(f: File): Long? = f.name.take(STAMP).toLongOrNull()
    }
}

/**
 * Every recording stays on the phone until a PC has it, in app-private storage, so
 * a process killed in the middle of a send loses nothing.
 *
 * NOTHING HERE SENDS. A recording that did not reach a PC waits in the keyboard,
 * and it goes only when the person presses Send again, into the field they are in
 * then. Nothing goes behind their back: not in the background, not when Home opens,
 * not when a network comes. In his words (2026-11-10): "if I don't get a dictation at
 * that moment, a minute later I probably no longer want it".
 *
 * An hour after it was made a recording goes, sent or not. Whatever opens first
 * prunes: a keep, the keyboard, Home, Sign out's count. When nothing opens, the
 * sweep does: [SpoolSweep], a job that needs no network because it only deletes.
 * Under it, 50 MB with the oldest going first is a net that says nothing.
 *
 * "A PC has it" means a PC answered with what it heard. A process killed after the
 * PC answered and before the file went offers it again, and a press then is a
 * duplicate in transcripts.log: the one failure here that loses nothing.
 *
 * It is the only copy of those words, so [Traces] leaves it: [Lock.dropRecordings]
 * has that rule, and a send stops the moment [Traces.wipes] moves.
 */
object Spool {
    const val DIR = "spool"
    const val MAX_BYTES = 50L * 1024 * 1024
    /** One hour, his choice (2026-11-10). */
    const val KEEP_MS = 60L * 60 * 1000

    private const val JOB = 1
    /**
     * How long after the hour the system may run the sweep. A doze defers it past
     * this to its next window, and whatever opens first prunes anyway.
     */
    private const val LATE_MS = 60L * 1000
    /**
     * Never sooner than this: one past its hour is swept a moment later, and a file the
     * disk will not delete cannot keep the sweep spinning (a debug build is allowed 250
     * schedules a minute, and then JobScheduler throws).
     */
    private const val SOONEST_MS = 5L * 1000

    /** Files on their way right now: a press never sends one twice, and the hour spares them. */
    private val inHand = HashSet<String>()

    /** When the sweep asked for in this process is due, or 0: it is asked for once per due time. */
    private var sweepAt = 0L

    fun files(c: Context) = SpoolFiles(File(c.filesDir, DIR))

    /**
     * On disk before it goes anywhere, and in hand: whatever kills this process now,
     * nothing has to remember the recording but the disk. Never fails: see
     * [SpoolFiles.Item].
     */
    fun keep(c: Context, wav: ByteArray): SpoolFiles.Item = try {
        synchronized(this) {
            files(c).keep(wav, System.currentTimeMillis(), HashSet(inHand)).also { claim(it) }
        }.also {
            if (it.dropped > 0) Log.w("DeskIT", "spool: ${it.dropped} older recording(s) made room")
            sweepLater(c)
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

    /** Back with what waits, for the next press. */
    fun free(c: Context, item: SpoolFiles.Item) {
        synchronized(this) { inHand.remove(item.key) }
        sweepLater(c)
    }

    /** A PC has it, or will never take it, or the person deleted it. */
    fun done(c: Context, item: SpoolFiles.Item) {
        synchronized(this) {
            inHand.remove(item.key)
            item.file?.delete()
        }
        sweepLater(c)
    }

    /** What waits for a press: on the disk, not on its way, oldest first. */
    @Synchronized
    fun waiting(c: Context): List<SpoolFiles.Item> =
        files(c).items().filter { it.name !in inHand }.map { SpoolFiles.Item(it, null) }

    /**
     * Every recording past its hour goes now, whatever is open, and the sweep moves on
     * to the next one's hour, unless [again] is false: the sweep asks once it is done.
     */
    fun prune(c: Context, again: Boolean = true): Int {
        val gone = synchronized(this) { files(c).prune(System.currentTimeMillis(), HashSet(inHand)) }
        if (gone > 0) Log.i("DeskIT", "spool: $gone recording(s) past their hour went")
        if (again) sweepLater(c)
        return gone
    }

    /**
     * The sweep, due when the oldest recording waiting has had its hour, and none
     * while nothing waits. One on its way is not counted: what becomes of it decides,
     * and [free] and [done] ask again.
     */
    fun sweepLater(c: Context) {
        val js = c.getSystemService(JobScheduler::class.java) ?: return
        synchronized(this) {
            val at = files(c).dueAt(HashSet(inHand))
            if (at == null) {
                if (sweepAt != 0L || js.getPendingJob(JOB) != null) js.cancel(JOB)
                sweepAt = 0L
                return
            }
            if (at == sweepAt && js.getPendingJob(JOB) != null) return
            val wait = (at - System.currentTimeMillis()).coerceAtLeast(SOONEST_MS)
            js.schedule(JobInfo.Builder(JOB, ComponentName(c, SpoolSweep::class.java))
                .setMinimumLatency(wait)
                .setOverrideDeadline(wait + LATE_MS)
                .build())
            sweepAt = at
        }
    }
}

/** The recordings' hour on JobScheduler's say-so: it deletes, and never sends. */
class SpoolSweep : JobService() {
    override fun onStartJob(params: JobParameters): Boolean {
        val app = applicationContext
        thread(name = "spool-sweep") {
            val gone = Spool.prune(app, again = false)
            Log.i("DeskIT", "spool: the sweep took $gone")
            jobFinished(params, false)
            // After it has finished: asked for while it runs, JobScheduler would stop it.
            Spool.sweepLater(app)
        }
        return true
    }

    /** Stopped before it ran: the next open prunes, and asks for it again. */
    override fun onStopJob(params: JobParameters): Boolean = false
}
