package io.github.deskit_app.deskit

import java.io.ByteArrayOutputStream
import java.time.Instant
import java.time.ZoneOffset
import java.time.format.DateTimeFormatter

/**
 * The cloud backup's decisions (PHONE_LINK_PLAN.md stage 2b), apart from Android so
 * the JVM checks hold every one of them: which road a recording takes, which answer
 * lands, the body the provider is sent, the row the PCs are told, and what a log
 * line may say. [Backup] runs them on a phone.
 */
object Road {
    /** A PC answered the knock (the recording is on its way to it), or nobody did. */
    enum class Door { NOT_YET, ANSWERED, NOBODY }

    /** The PC road's own answer: still out, the text, or why not. */
    enum class Pc {
        PENDING,
        OK,
        /** It answered that it never will, about this recording: it does not go anywhere else either. */
        REFUSED,
        /** It answered that it cannot now (its model is off, it is signed out), or the phone could not look. */
        BUSY,
        /** Nobody answered, or the one that did went quiet and dropped it. */
        UNREACHED,
    }

    enum class Cloud { IDLE, PENDING, OK, FAILED }

    enum class Step {
        /** Nothing to do yet: ask again in a moment. */
        WAIT,
        /** Send the same recording to the key, beside whatever the PC road is still doing. */
        CLOUD,
        /** The PC's text lands. */
        LAND_PC,
        /** The cloud's text lands; a PC that answers after it is dropped. */
        LAND_CLOUD,
        /** Nothing landed: the PC road's answer stands, and the recording waits as it always has. */
        PC_SAYS,
        /** Nothing landed, and the cloud has the last word about why. */
        CLOUD_SAYS,
    }

    /**
     * About a second of asking: a door at home answers in milliseconds, so a second
     * with nobody means nobody. Counted from the press, because the keyboard knocks
     * while the person speaks, so only a dictation shorter than this waits past the
     * release, and at home that is milliseconds.
     */
    const val ASK_MS = 1000L

    /**
     * The PC road's own moment once it sets out at the release, whatever the second
     * says: a door that answered while the person spoke is used in milliseconds, but
     * only once its thread has looked (measured on the emulator, 2026-11-11: the cloud
     * won by 31 ms against a PC that had answered the knock, before this).
     */
    const val ROAD_MS = 300L

    /**
     * A PC that answered the knock and then said nothing for this long: the same
     * recording goes to the key too, and the first answer lands. A cold model takes
     * ~12 s on his PC, which is why it is not shorter; the PC keeps its chance to the
     * end, and its text lands if it comes first.
     */
    const val SILENT_MS = 10_000L

    /** Everything the decision reads, at one moment. */
    data class Moment(
        /** The switch is on and the person said yes to it. */
        val active: Boolean,
        /** A key is in the account (Groq or Gemini). */
        val keyed: Boolean,
        /** Since the asking began: the press, or Send again. */
        val askedMs: Long,
        /** Since the PC road set out, at the release. */
        val roadMs: Long,
        val door: Door,
        /** Since the door answered, with nothing back from it yet. */
        val silentMs: Long,
        val pc: Pc,
        val cloud: Cloud,
    )

    /** What to do now. The first rule that holds wins; the table is the plan's. */
    fun next(m: Moment): Step = when {
        m.pc == Pc.OK -> Step.LAND_PC
        m.cloud == Cloud.OK -> Step.LAND_CLOUD
        // a PC answered "never": the cloud would be asked the same and the answer
        // is a property of the recording, not of the road
        m.pc == Pc.REFUSED -> if (m.cloud == Cloud.PENDING) Step.WAIT else Step.PC_SAYS
        // the switch off, no yes, or no key: today's road and nothing else
        !m.active || !m.keyed -> if (m.pc == Pc.PENDING) Step.WAIT else Step.PC_SAYS
        // a PC answered that it cannot now: its own words, the recording waits
        m.pc == Pc.BUSY -> if (m.cloud == Cloud.PENDING) Step.WAIT else Step.PC_SAYS
        m.cloud == Cloud.PENDING -> Step.WAIT
        m.cloud == Cloud.FAILED -> if (m.pc == Pc.PENDING) Step.WAIT else Step.CLOUD_SAYS
        // the cloud is IDLE from here on. Nobody answered: the PC road comes back
        // unreached, and the door is NOBODY in the same moment, so this rule is that one
        m.pc == Pc.UNREACHED -> Step.CLOUD
        m.door == Door.NOT_YET && m.askedMs >= ASK_MS && m.roadMs >= ROAD_MS -> Step.CLOUD
        m.door == Door.ANSWERED && m.silentMs >= SILENT_MS -> Step.CLOUD
        else -> Step.WAIT
    }
}

/**
 * The first answer wins, once: text never lands twice. Whoever offers a text after
 * the first is told no, and its text goes nowhere.
 */
class FirstAnswer {
    private var winner: String? = null

    /** True for exactly one [from] in this object's life, the first to offer. */
    @Synchronized
    fun offer(from: String): Boolean {
        if (winner != null) return false
        winner = from
        return true
    }

    @Synchronized
    fun winner(): String? = winner
}

/**
 * The keyboard's line after a text landed, and its number. The number is the
 * RECORDING'S LENGTH on both roads: the PC sends it (server.py's `seconds`, to_wav's
 * `len(samples) / 16000`), and the cloud's is counted here the same way off the WAV.
 * The provider's wait is a log line and never the line: on his S26, 2026-11-11, "0.5 s ·
 * from the cloud (Groq)" beside "3.7 s · local" read as a PC seven times slower, when
 * 3.7 s was how long he spoke.
 */
object CloudLine {
    /** A 16 kHz mono 16-bit WAV's length, as to_wav counts it: whole samples over the rate. */
    fun seconds(wav: ByteArray): Double = ((wav.size - 44).coerceAtLeast(0) / 2) / 16000.0

    /**
     * The cloud's text as the keyboard reads one: [backend] the line's words for the
     * road ("from the cloud (Groq)"), [wait] the provider's answer time, which is kept
     * for the log and nowhere else.
     */
    @Suppress("UNUSED_PARAMETER")
    fun ok(text: String, backend: String, provider: String, wav: ByteArray, wait: Double): Transcriber.Result.Ok {
        val length = Math.round(seconds(wav) * 100) / 100.0           // server.py rounds to 2
        return Transcriber.Result.Ok(text, null, backend, length, cloud = provider, audio = seconds(wav))
    }

    /** The line itself, the same words on both roads: "3.7 s · local", "3.7 s · from the cloud (Groq)". */
    fun note(ok: Transcriber.Result.Ok): String =
        if (ok.backend.isEmpty()) "" else String.format(java.util.Locale.US, "%.1f s · %s", ok.seconds, ok.backend)
}

/** A multipart/form-data body, by hand: the provider's one request, no library. */
object Multipart {
    fun body(boundary: String, fields: List<Pair<String, String>>, fileField: String,
             fileName: String, fileType: String, file: ByteArray): ByteArray {
        val out = ByteArrayOutputStream(file.size + 1024)
        fun line(s: String) = out.write((s + "\r\n").toByteArray(Charsets.UTF_8))
        for ((name, value) in fields) {
            line("--$boundary")
            line("Content-Disposition: form-data; name=\"$name\"")
            line("")
            line(value)
        }
        line("--$boundary")
        line("Content-Disposition: form-data; name=\"$fileField\"; filename=\"$fileName\"")
        line("Content-Type: $fileType")
        line("")
        out.write(file)
        out.write("\r\n".toByteArray(Charsets.UTF_8))
        line("--$boundary--")
        return out.toByteArray()
    }

    fun contentType(boundary: String) = "multipart/form-data; boundary=$boundary"
}

/**
 * The text of a dictation the cloud carried, as a row of the account's history store:
 * what a PC writes for its own (sb._seal_history), with the mark sync.CLOUD_SOURCE
 * sealed in beside the words. The stamp is the PC's canonical one, because the PC
 * opens the row under the stamp as it reads it back. No org.json here, so the JVM
 * checks hold it: [inside] is JSON written by hand, and [Json.str] escapes it.
 */
object HistoryRow {
    const val SOURCE = "phone-cloud"
    const val KIND = "dictation"

    /** One row, its words already sealed. [Backup] turns it into the request's JSON. */
    class Row(val uid: String, val device: String, val ts: String, val kind: String,
              val engine: String, val seconds: Double, val cipher: String)

    private val STAMP = DateTimeFormatter.ofPattern("yyyy-MM-dd'T'HH:mm:ss.SSS'+00:00'")
        .withZone(ZoneOffset.UTC)

    /** sync.history_rows' stamp: UTC, milliseconds, the PC's own spelling of it. */
    fun stamp(epochMs: Long): String = STAMP.format(Instant.ofEpochMilli(epochMs))

    fun aad(uid: String, device: String, ts: String, kind: String = KIND) =
        "history/$uid/$device/$ts/$kind"

    /** What is sealed: the PC's {"text", "raw"} and the mark. */
    fun inside(text: String): String =
        "{\"text\":${Json.str(text)},\"raw\":null,\"source\":\"$SOURCE\"}"

    /** sb._fit_history: the whole text when it fits one sealed value, else its head. */
    fun fit(text: String): String {
        if (inside(text).toByteArray(Charsets.UTF_8).size <= Crypt.PLAIN_MAX) return text
        var keep = 0
        var most = text.length
        while (keep < most) {
            val mid = (keep + most + 1) / 2
            if (inside(text.substring(0, mid)).toByteArray(Charsets.UTF_8).size <= Crypt.PLAIN_MAX) keep = mid
            else most = mid - 1
        }
        // never half of a surrogate pair
        if (keep > 0 && Character.isHighSurrogate(text[keep - 1])) keep--
        return text.substring(0, keep)
    }

    /** The row as it leaves: the words sealed, the rest as a PC's own row has them. */
    fun build(key: ByteArray, uid: String, device: String, epochMs: Long, text: String,
              engine: String, seconds: Double): Row {
        val ts = stamp(epochMs)
        return Row(uid, device, ts, KIND, engine.take(32),
                   Math.round(seconds.coerceIn(0.0, 36000.0) * 10) / 10.0,
                   Crypt.sealText(key, inside(fit(text)), aad(uid, device, ts)))
    }

    /** What the row holds inside, for a check: the sealed JSON as written. */
    fun open(key: ByteArray, row: Row): String =
        Crypt.openText(key, row.cipher, aad(row.uid, row.device, row.ts, row.kind))
}

/** JSON's string, by hand: what org.json would write, for a module the JVM checks load. */
object Json {
    fun str(s: String): String {
        val b = StringBuilder(s.length + 2).append('"')
        for (ch in s) when {
            ch == '"' -> b.append("\\\"")
            ch == '\\' -> b.append("\\\\")
            ch == '\n' -> b.append("\\n")
            ch == '\r' -> b.append("\\r")
            ch == '\t' -> b.append("\\t")
            ch.code < 0x20 || ch.code == 0x2028 || ch.code == 0x2029 ->
                b.append(String.format("\\u%04x", ch.code))
            else -> b.append(ch)
        }
        return b.append('"').toString()
    }
}

/**
 * What a log line, a status line or a word on the screen may carry of a provider's
 * answer: never the key, and never anything shaped like one (redact.PATTERNS' two
 * provider shapes), whatever the provider chose to echo back.
 */
object Scrub {
    private val SHAPES = listOf(Regex("gsk_[A-Za-z0-9]{8,}"), Regex("AIza[0-9A-Za-z_\\-]{20,}"))

    fun words(text: String, key: String?): String {
        var out = text
        if (!key.isNullOrEmpty()) out = out.replace(key, "[key]")
        for (s in SHAPES) out = s.replace(out, "[key]")
        return out
    }

    /** What an API key can be: printable ASCII with no spaces (keyrow.looks_like_key). */
    fun looksLikeKey(value: String): Boolean =
        value.isNotEmpty() && value.length <= 512 && value.all { it.code in 0x21..0x7e }
}
