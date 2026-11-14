package io.github.deskit_app.deskit

import java.io.File
import java.nio.file.Files

/**
 * A recording the keyboard closed on (2026-11-12): the paused slot's rules on a real
 * folder, the recorder's arithmetic and the mic's words fitting, with nothing of
 * Android's in them. Run from CryptChecks' main, with its counter, so `gradle jvmChecks`
 * is one run and one exit code.
 */
internal fun keepChecks(check: (String, Boolean) -> Unit) {
    val dir: File = Files.createTempDirectory("keep").toFile()
    val hour = Spool.KEEP_MS
    val t = 1_700_000_000_000L
    fun wav(seconds: Int) = ByteArray(44 + seconds * 32_000)
    try {
        val f = SpoolFiles(dir)
        check("nothing paused, nothing offered", f.paused(t) == null && f.dueAt() == null)

        // ---- kept at the hide, whole ----
        val p = f.keepPaused(wav(42), t)
        check("the hide keeps it on the disk, whole", p.exists() && p.length() == 44L + 42 * 32_000)
        check("and no temporary is left", dir.list()!!.none { it.endsWith(".tmp") })
        check("it is the paused one, 42 s long", f.paused(t) == p && SpoolFiles.seconds(p.length()) == 42)
        check("it is not a waiting row: nothing tried to send it", f.items().isEmpty())
        check("Sign out counts it among what has not reached a PC", f.count() == 1)

        // ---- one at a time ----
        val q = f.keepPaused(wav(50), t + 1000)
        check("a later pause replaces the earlier: one at a time", !p.exists() && q.exists() &&
              dir.list()!!.count { it.startsWith("paused-") } == 1 && f.paused(t + 1000) == q)
        val same = f.keepPaused(wav(51), t + 1000)
        check("even a pause in the same millisecond, written over whole",
              same.exists() && SpoolFiles.seconds(same.length()) == 51 && f.count() == 1)

        // ---- the hour, from the pause ----
        check("the sweep is due at its hour", f.dueAt() == t + 1000 + hour)
        check("a minute short of the hour it is still offered", f.paused(t + 1000 + hour - 60_000) != null)
        check("and a prune then leaves it", f.prune(t + 1000 + hour - 60_000) == 0 && same.exists())
        check("past the hour it is offered no more", f.paused(t + 1000 + hour + 1) == null)
        check("and the prune takes it, and counts it", f.prune(t + 1000 + hour + 1) == 1 && !same.exists())
        check("and the sweep has nothing left to wait for", f.dueAt() == null)

        // ---- beside the waiting ones ----
        val older = f.keep(ByteArray(1000), t + 5_000)
        val paused = f.keepPaused(wav(10), t + 20_000)
        check("the sweep is due at whichever hour comes first", f.dueAt() == t + 5_000 + hour)
        check("a waiting row stays a waiting row", f.items() == listOf(older.file))
        f.prune(t + 5_000 + hour + 1)
        check("the older one's hour does not take the paused one",
              paused.exists() && older.file?.exists() == false)
        check("and then the sweep waits for the paused one", f.dueAt() == t + 20_000 + hour)
        val tight = SpoolFiles(dir, maxBytes = 1000)
        val a = tight.keep(ByteArray(900), t + 21_000)
        check("the 50 MB net never takes the paused one", paused.exists() && a.file?.exists() == true)

        // ---- Send: an ordinary recording on its way ----
        val item = f.adopt(paused, t + 30_000)
        check("Send renames it to a recording on its way", item != null && item.file?.exists() == true &&
              !paused.exists() && f.paused(t + 30_000) == null)
        check("named as a release names one, so it can wait like one",
              f.items().contains(item!!.file) && item.file!!.name.startsWith("%013d-".format(t + 30_000)))
        check("a file already gone is nothing to send", f.adopt(File(dir, "paused-0000000000000.wav"), t) == null)

        // ---- the X ----
        f.keepPaused(wav(3), t + 40_000)
        check("the X deletes it", f.dropPaused() == 1 && f.paused(t + 40_000) == null)

        // ---- a kill in the middle of a write ----
        File(dir, "paused-%013d.wav.tmp".format(t + 50_000)).writeBytes(ByteArray(10))
        check("half a write is never offered", f.paused(t + 50_000) == null)
        f.prune(t + 50_000)
        check("and the next prune clears it", dir.list()!!.none { it.endsWith(".tmp") })
        File(dir, "paused-abc.wav").writeBytes(ByteArray(10))
        check("a name that is not ours is never offered", f.paused(t + 50_000) == null)
    } finally {
        dir.deleteRecursively()
    }

    // ---- the recorder: Continue goes on from what was kept ----
    val kept = ByteArray(44 + 6) { it.toByte() }
    check("Continue takes the kept recording's sound, not its header",
          Recorder.pcm(kept).contentEquals(byteArrayOf(44, 45, 46, 47, 48, 49)))
    check("an empty WAV has no sound to go on from", Recorder.pcm(ByteArray(44)).isEmpty())
    check("the clock is whole seconds of 16 kHz mono 16-bit",
          SpoolFiles.seconds(44L + 32_000 * 42 + 31_999) == 42 && SpoolFiles.seconds(10) == 0)

    // ---- the mic's words: shrunk to fit, never below the floor, never cut ----
    check("words that fit keep their size", MicFit.size(57f, 300f, 400f) == 57f)
    check("words a little too long shrink just enough", MicFit.size(57f, 400f, 300f) == 57f * 300 / 400)
    check("never smaller than the floor", MicFit.size(57f, 1000f, 300f) == null)
    check("the floor itself is allowed", MicFit.size(50f, 100f, 100f * MicFit.FLOOR) == 50f * MicFit.FLOOR)
    check("no room yet is no size", MicFit.size(57f, 300f, 0f) == null)
}
