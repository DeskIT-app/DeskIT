package io.github.deskit_app.deskit

import java.util.concurrent.CountDownLatch
import java.util.concurrent.atomic.AtomicInteger
import kotlin.concurrent.thread

/**
 * The cloud backup's decisions (stage 2b), with nothing of Android's in them: the road
 * as a table, the first answer winning, the provider's body, the text row the PCs read,
 * and that no key reaches a word anybody sees. Run from CryptChecks' main, with its
 * counter, so `gradle jvmChecks` is one run and one exit code.
 */
internal fun backupChecks(check: (String, Boolean) -> Unit) {
    // ---- the road, as the plan's table ----
    fun m(active: Boolean = true, keyed: Boolean = true, asked: Long = 0, door: Road.Door = Road.Door.NOT_YET,
          silent: Long = 0, pc: Road.Pc = Road.Pc.PENDING, cloud: Road.Cloud = Road.Cloud.IDLE,
          road: Long = asked) =
        Road.next(Road.Moment(active, keyed, asked, road, door, silent, pc, cloud))
    val s = Road.Step.values().toList()

    check("LAN up: a PC that answers lands, the cloud never asked",
          m(door = Road.Door.ANSWERED, pc = Road.Pc.OK) == Road.Step.LAND_PC)
    check("LAN up: the door answered and the PC is working: wait for it",
          m(asked = 5000, door = Road.Door.ANSWERED, silent = 4000) == Road.Step.WAIT)
    check("LAN down: nobody answered: the key, at once",
          m(asked = 200, door = Road.Door.NOBODY, pc = Road.Pc.UNREACHED) == Road.Step.CLOUD)
    check("LAN down: still knocking after a second: the key",
          m(asked = Road.ASK_MS, door = Road.Door.NOT_YET) == Road.Step.CLOUD)
    check("still knocking before the second is up: wait",
          m(asked = Road.ASK_MS - 1, door = Road.Door.NOT_YET) == Road.Step.WAIT)
    check("a long press, the PC road only just set out: its moment first",
          m(asked = 5000, road = Road.ROAD_MS - 1, door = Road.Door.NOT_YET) == Road.Step.WAIT)
    check("and once its moment is up, the key",
          m(asked = 5000, road = Road.ROAD_MS, door = Road.Door.NOT_YET) == Road.Step.CLOUD)
    check("a PC that answered and went silent: the same recording to the key",
          m(asked = 20_000, door = Road.Door.ANSWERED, silent = Road.SILENT_MS) == Road.Step.CLOUD)
    check("and not a moment before",
          m(asked = 20_000, door = Road.Door.ANSWERED, silent = Road.SILENT_MS - 1) == Road.Step.WAIT)
    check("the PC dropped it after answering: the key",
          m(door = Road.Door.ANSWERED, pc = Road.Pc.UNREACHED) == Road.Step.CLOUD)
    check("no key: today's road, waited for",
          m(keyed = false, asked = 9000, door = Road.Door.NOBODY) == Road.Step.WAIT)
    check("no key: today's answer stands, the recording waits",
          m(keyed = false, door = Road.Door.NOBODY, pc = Road.Pc.UNREACHED) == Road.Step.PC_SAYS)
    check("switch off: today's answer stands",
          m(active = false, door = Road.Door.NOBODY, pc = Road.Pc.UNREACHED) == Road.Step.PC_SAYS)
    check("switch off: never the cloud, however long",
          (0..60_000L step 500).none { m(active = false, asked = it) == Road.Step.CLOUD })
    check("a PC that refuses the recording: nowhere else",
          m(door = Road.Door.ANSWERED, pc = Road.Pc.REFUSED) == Road.Step.PC_SAYS)
    check("a PC that answered it cannot now: its own words",
          m(door = Road.Door.ANSWERED, pc = Road.Pc.BUSY) == Road.Step.PC_SAYS)
    check("the cloud on its way: wait for it",
          m(door = Road.Door.NOBODY, pc = Road.Pc.UNREACHED, cloud = Road.Cloud.PENDING) == Road.Step.WAIT)
    check("the cloud's text lands",
          m(door = Road.Door.NOBODY, pc = Road.Pc.UNREACHED, cloud = Road.Cloud.OK) == Road.Step.LAND_CLOUD)
    check("the cloud failed and the PC road is done: the cloud says why",
          m(door = Road.Door.NOBODY, pc = Road.Pc.UNREACHED, cloud = Road.Cloud.FAILED) == Road.Step.CLOUD_SAYS)
    check("the cloud failed and the PC is still working: the PC keeps its chance",
          m(door = Road.Door.ANSWERED, silent = 20_000, cloud = Road.Cloud.FAILED) == Road.Step.WAIT)
    check("the PC's text after the cloud failed lands",
          m(door = Road.Door.ANSWERED, pc = Road.Pc.OK, cloud = Road.Cloud.FAILED) == Road.Step.LAND_PC)
    check("the cloud is asked once: never a second time while it works",
          m(door = Road.Door.NOBODY, pc = Road.Pc.UNREACHED, cloud = Road.Cloud.PENDING) != Road.Step.CLOUD)
    // the relay's steps are reachable only with the relay asked: RelayChecks holds those
    val relaySteps = setOf(Road.Step.RELAY, Road.Step.LAND_RELAY, Road.Step.RELAY_SAYS)
    check("every step of the backup's is reachable from its table", s.filter { it !in relaySteps }.all { step ->
        val all = ArrayList<Road.Step>()
        for (a in listOf(true, false)) for (k in listOf(true, false)) for (d in Road.Door.values())
            for (p in Road.Pc.values()) for (cl in Road.Cloud.values()) for (t in listOf(0L, 99_999L))
                all.add(m(a, k, t, d, t, p, cl, t))
        step in all
    })

    // ---- the first answer wins, once ----
    val first = FirstAnswer()
    check("the first to offer wins", first.offer("cloud"))
    check("a second never does", !first.offer("pc") && !first.offer("cloud"))
    check("and the winner is the first", first.winner() == "cloud")
    repeat(5) {
        val race = FirstAnswer()
        val wins = AtomicInteger()
        val go = CountDownLatch(1)
        val ts = (1..16).map { i -> thread { go.await(); if (race.offer("t$i")) wins.incrementAndGet() } }
        go.countDown()
        ts.forEach { it.join() }
        if (it == 4) check("sixteen threads at once: exactly one text lands", wins.get() == 1)
    }

    // ---- the line's number: the recording's length on both roads ----
    // 3.7 s of 16 kHz mono 16-bit, as Recorder writes it: 44 bytes of header, 2 a sample
    val spoke = ByteArray(44 + 3_700 * 16 * 2)
    val viaCloud = CloudLine.ok("שלום", "from the cloud (Groq)", "groq", spoke, wait = 0.5)
    check("the cloud's number is how long he spoke, as to_wav counts it", viaCloud.seconds == 3.7)
    check("never the provider's wait", viaCloud.seconds != 0.5)
    check("the cloud's line", CloudLine.note(viaCloud) == "3.7 s · from the cloud (Groq)")
    // the PC's own answer for the same recording: server.py's seconds, len(samples) / 16000
    val viaPc = Transcriber.Result.Ok("שלום", null, "local", 3.7)
    check("one recording, one number on both roads: \"3.7 s · local\" and \"3.7 s · from the cloud\"",
          CloudLine.note(viaPc) == "3.7 s · local" &&
              CloudLine.note(viaPc).substringBefore(" ·") == CloudLine.note(viaCloud).substringBefore(" ·"))
    check("the length is whole samples, as the PC's", CloudLine.seconds(ByteArray(44 + 3)) == 1 / 16000.0)

    // ---- the provider's body ----
    val wav = ByteArray(300) { (it % 7).toByte() }
    val body = Multipart.body("BND", listOf("model" to "whisper-large-v3-turbo", "language" to "he"),
                              "file", "dictation.wav", "audio/wav", wav)
    val text = String(body, Charsets.ISO_8859_1)
    check("each field is a part of its own",
          "--BND\r\nContent-Disposition: form-data; name=\"model\"\r\n\r\nwhisper-large-v3-turbo\r\n" in text &&
              "name=\"language\"\r\n\r\nhe\r\n" in text)
    check("the file part names the file and its type",
          "Content-Disposition: form-data; name=\"file\"; filename=\"dictation.wav\"\r\nContent-Type: audio/wav\r\n\r\n" in text)
    val at = text.indexOf("audio/wav\r\n\r\n") + "audio/wav\r\n\r\n".length
    check("the recording is in it byte for byte", body.copyOfRange(at, at + wav.size).contentEquals(wav))
    check("and the body closes", text.endsWith("\r\n--BND--\r\n"))
    check("the type names the boundary", Multipart.contentType("BND") == "multipart/form-data; boundary=BND")

    // ---- the text row the PCs read ----
    val key = ByteArray(32) { (it * 3 + 1).toByte() }
    val uid = "11111111-2222-3333-4444-555555555555"
    val device = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    check("the stamp is sync.history_rows' own spelling",
          HistoryRow.stamp(1_762_877_412_345L) == "2025-11-11T16:10:12.345+00:00")
    check("and keeps its milliseconds when they are zero",
          HistoryRow.stamp(1_762_877_412_000L) == "2025-11-11T16:10:12.000+00:00")
    val said = "אני בדרך \"הביתה\"\nעם \\ ו-API"
    val row = HistoryRow.build(key, uid, device, 1_762_877_412_345L, said, "groq", 3.04)
    check("the row's columns are the PC's own", row.kind == "dictation" && row.engine == "groq" &&
          row.ts == "2025-11-11T16:10:12.345+00:00" && row.seconds == 3.0)
    check("the words are sealed: no plaintext in the row", Crypt.isSealed(row.cipher) && "הביתה" !in row.cipher)
    check("inside: the text, no raw, and the mark",
          HistoryRow.open(key, row) == "{\"text\":\"אני בדרך \\\"הביתה\\\"\\nעם \\\\ ו-API\",\"raw\":null,\"source\":\"phone-cloud\"}")
    var other = false
    try {
        Crypt.open(key, row.cipher, HistoryRow.aad(uid, device, "2025-11-11T16:10:12.346+00:00"))
    } catch (e: Crypt.Refused) {
        other = true
    }
    check("sealed under its own stamp: a row moved to another opens for nobody", other)
    val long = "מילה ".repeat(3000)
    val fitted = HistoryRow.fit(long)
    check("a long dictation keeps its head, and fits one sealed value",
          long.startsWith(fitted) && fitted.length > 1000 &&
              HistoryRow.inside(fitted).toByteArray(Charsets.UTF_8).size <= Crypt.PLAIN_MAX)
    check("a short one is whole", HistoryRow.fit(said) == said)
    check("JSON escapes what JSON must", Json.str("a\u0001b ") == "\"a\\u0001b\\u2028\"")

    // ---- no key in a word anybody sees ----
    val fake = "gsk_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8S9t0U1v2W3x4"
    check("the key itself is taken out of what a provider said",
          fake !in Scrub.words("Invalid API Key: $fake", fake))
    val plain = "x9" + "Q7pL2mZr8".repeat(3)
    check("a key of no known shape is taken out too, by its value",
          plain !in Scrub.words("the provider echoed $plain back", plain))
    check("and anything shaped like a Groq key", "gsk_" !in Scrub.words("key gsk_ABCDEFGH12345678 refused", null))
    check("and like a Google key",
          "AIza" !in Scrub.words("bad AIzaSyA1234567890abcdefghijklmnopqrstu", null))
    check("plain words pass", Scrub.words("Rate limit reached", null) == "Rate limit reached")
    check("a pasted sentence is not a key", !Scrub.looksLikeKey("my key is here"))
    check("Hebrew is not a key", !Scrub.looksLikeKey("מפתח"))
    check("a key's shape is a key", Scrub.looksLikeKey(fake))
}
