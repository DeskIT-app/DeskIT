package io.github.deskit_app.deskit

import java.io.ByteArrayOutputStream
import java.io.InputStream
import java.net.InetAddress
import java.net.ServerSocket
import java.security.MessageDigest
import java.util.Base64
import kotlin.concurrent.thread

/**
 * The sealed relay (stage 3), with nothing of Android's in it: the ladder as a table,
 * the pieces against what the real relay.py sealed, every rule broken once, the size
 * against the broadcast cap, the JSON reader, Phoenix's messages, and the websocket
 * against a server of its own on loopback. Run from CryptChecks' main.
 */
private object RelayVectors {
    const val UID = "11111111-2222-3333-4444-555555555555"
    const val PC = "aaaaaaaa-0000-4000-8000-000000000001"
    const val PHONE = "bbbbbbbb-0000-4000-8000-000000000002"
    const val RID = "0123456789abcdef0123456789abcdef"

    // dev/android/make_relay_vectors.py's output, pasted: relay.seal with chosen nonces
    const val TEXT_S = "v1.CgsMDQ4PEBESExQVFJ9M6lHs+1fdJuIvqsmdPN8y/VzLC4rBmHvxpGFt8MFLDjTIgb65dew0jogIIj8In207UsyE2lfB49So3OlVfrY/ToKfhiOG/CiKsbOMaQ4vEWz5MenrRVgtYrvJGZ7qvtNi+DrZjxjiLfyV4A+ZpwOGGz0RhRv6xuI="
    const val PING_S = "v1.Hh8gISIjJCUmJygpNG0QhEWsEhCtsrjW6s7X8pogFjKlAXddvViFfZrq5A2tdOw="
    const val AUDIO_S = "v1.MjM0NTY3ODk6Ozw9vXmZ4v8NrcEGJdCkOpibkQmRZouJTKXo1R8Nn786kXkvDcREB/IVvYUZbMi8f/n24+n58vLtcha+fpd1Zw2kCuaZ9NEWWs4Q7Wd5Aqwt96egalmqcNk+alM1VT/KZzUHTVvw1SzhxQidrAIrKMjP/pLUscYkAxfyTU5ixzVy1GqDDW8WA17SV7+Q1T2oyRzM+Xj6rXzzIFG82dMLv2FXBo0oY+u1tgUyaweSmAp2Jy35Uo1ZIdDCYWAyyMFp3toGEAz7ArdbtKAd+aOQMZTrrP3M9D+/bytRnkhIKJs5N3IlMogIo6dqYJEXIOr7q5yUrqc1fHhSLYmKqtErQ1+LPw6Wj4LbhDcsvti7iFyPKQ+kQf5e1FuG4ezlqpQjH0pKlqu2lxYNA0h9Mt/52r4apCbPknFxbephTtMqtRbLwWzOYg+pnIhQMNO7hHHp+meFLQpyB/GSqm4XWNDZFyLyhmv1F2p51dXgx2Ox/0Yazb0whQdHHT4+kS4vlTSDUK/esPGWZGqO7dqBLEZs1bclkmPI4I3eXweEGsA36/1iByK0GpmVY1Ln9RR+U8cirfO14yWv0t1RuTh4eB6gkF/Dkbw15h4VT+lJpuD82VM8G3nIZahqYPBoL/C8H9nCsIt8kDvJMdiFKsgwxV9r4C2T8VMIsK2PlAPSrR+EphGkXj9e4Rm4hel6s94xu/uUuExheuXcvh7V5nR4mIsta9NMzZKBk3G/snFrZuRuB8k7OPKrgJ1GSUG/pGq8s5Qq4QBnGLr7QmODo3eiNrj6c9JRcgfheWED3vmw8g3FeGKXI+cmyvM1Bcvdq0eAmt1cRjJUKoN2UcQcRYcU5FuElH/YTanw4/XwBEr44WA6vpqNPU9th20OgtaFKBTXfMGDtw4BeIcVBlS91wKlaZb+e3uEhSVQc5f831xVmFrnbg2hduf4Eh251euomi5rH8RYsH97WXVi4vWSFSuddpMh+hhCWJXqGbjDFkBEydnGuM9wdOIgyUZLRKgkdTz+ESdg1wj6HtAqFwRMzMEhSmfz4Nbg6NySGtTW3KWKsh9Nh6vuyyJuJ7Vs4tNEO8Qkr7SjLGFglc2mLjq4RdYdNdC3B0xTn9L1GWmLtFd6fhDkmGlbcCf7h5fC1q8bUDXQHhx+ZsaQB+oo9ryM2JzXFsrDso//J7q2YdZMj5lFbmPNws2YwZg5h3Y6h03Jz4D039+f9lV6cy4hK7qMCXIIjE2oiEekGeHQFJFIzH1HwhdZOsipZ1fh/dKdFY2tuTGrNSpg5iwJTB4WBbJsDdw5BhKQyH86+pV+7+ZQ6xB5XuK5meE8t6rqvVRTf8ldzygid5GOQ+S85wEcXmGQJOEwpkBbShxiAAWVijBajbmFpdKxkxqEcVjtOlbpFTaoZWeydwvHO58P26ct4Q=="
}

private typealias S = Road.Step
private typealias R = Road.Relay

private fun refused(block: () -> Unit): Boolean = try {
    block(); false
} catch (e: RelayWire.Refused) {
    true
}

@Suppress("UNCHECKED_CAST")
private fun parsed(json: String): Map<String, Any?> = JsonIn.parse(json) as Map<String, Any?>

internal fun relayChecks(check: (String, Boolean) -> Unit) {
    // ---- the ladder: home, the relay, the cloud, the waiting row ----
    fun m(active: Boolean = true, keyed: Boolean = true, asked: Long = 0, door: Road.Door = Road.Door.NOT_YET,
          silent: Long = 0, pc: Road.Pc = Road.Pc.PENDING, cloud: Road.Cloud = Road.Cloud.IDLE,
          road: Long = asked, relay: Road.Relay = Road.Relay.OFF, run: Road.Run = Road.Run.IDLE,
          quiet: Long = 0, relayPc: Road.Pc = Road.Pc.PENDING) =
        Road.next(Road.Moment(active, keyed, asked, road, door, silent, pc, cloud, relay, run, quiet, relayPc))
    val second = Road.ASK_MS

    check("home: the door answered, the relay ready too: the door, and nothing through the account",
          m(asked = 5000, door = Road.Door.ANSWERED, silent = 3000, relay = R.READY) == S.WAIT &&
              m(door = Road.Door.ANSWERED, pc = Road.Pc.OK, relay = R.READY) == S.LAND_PC)
    check("away: the door had its second and no answer, a PC answered through the account: the relay",
          m(asked = second, relay = R.READY) == S.RELAY)
    check("not before the door's second is up", m(asked = second - 1, relay = R.READY) == S.WAIT)
    check("nor before the door's moment after the release",
          m(asked = 9000, road = Road.ROAD_MS - 1, relay = R.READY) == S.WAIT)
    check("the door gave up at once (off the Wi-Fi): the relay at once",
          m(asked = 100, door = Road.Door.NOBODY, pc = Road.Pc.UNREACHED, relay = R.READY) == S.RELAY)
    check("the relay ready and the cloud keyed: never the cloud first",
          (0..60_000L step 250).none { m(asked = it, relay = R.READY) == S.CLOUD })
    check("the relay on its way: wait, and no cloud beside it",
          m(asked = 5000, relay = R.READY, run = Road.Run.SENDING, quiet = 2000) == S.WAIT &&
              m(asked = 5000, relay = R.READY, run = Road.Run.TOOK, quiet = 9000) == S.WAIT)
    check("the relay's text lands",
          m(asked = 5000, relay = R.READY, run = Road.Run.TOOK, relayPc = Road.Pc.OK) == S.LAND_RELAY)
    check("the relay's pieces stopped going up: the cloud beside it",
          m(asked = 20_000, relay = R.READY, run = Road.Run.SENDING, quiet = Road.RELAY_QUIET_MS) == S.CLOUD)
    check("the PC took it and went silent: the cloud beside it",
          m(asked = 30_000, relay = R.READY, run = Road.Run.TOOK, quiet = Road.SILENT_MS) == S.CLOUD)
    check("and the relay's text still lands if it comes first",
          m(asked = 30_000, relay = R.READY, run = Road.Run.TOOK, quiet = Road.SILENT_MS,
            cloud = Road.Cloud.PENDING, relayPc = Road.Pc.OK) == S.LAND_RELAY)
    check("the relay failed: on to the cloud",
          m(asked = 5000, pc = Road.Pc.UNREACHED, door = Road.Door.NOBODY, relay = R.READY,
            run = Road.Run.SENDING, relayPc = Road.Pc.UNREACHED) == S.CLOUD)
    check("the relay failed and no key: the waiting row",
          m(keyed = false, asked = 5000, pc = Road.Pc.UNREACHED, door = Road.Door.NOBODY, relay = R.READY,
            run = Road.Run.SENDING, relayPc = Road.Pc.UNREACHED) == S.PC_SAYS)
    check("asking through the account: the cloud waits for its answer",
          m(asked = 5000, pc = Road.Pc.UNREACHED, door = Road.Door.NOBODY, relay = R.ASKING) == S.WAIT)
    check("nobody through the account either: the cloud, as in 2b",
          m(asked = second, relay = R.NOBODY) == S.CLOUD &&
              m(asked = 100, door = Road.Door.NOBODY, pc = Road.Pc.UNREACHED, relay = R.NOBODY) == S.CLOUD)
    check("nobody anywhere and no key: the waiting row",
          m(keyed = false, door = Road.Door.NOBODY, pc = Road.Pc.UNREACHED, relay = R.NOBODY) == S.PC_SAYS)
    check("the switch for the cloud off: the relay still carries it",
          m(active = false, asked = second, relay = R.READY) == S.RELAY)
    check("the PC said through the account it cannot now: its words, and the cloud is not asked",
          m(asked = second, relay = R.BUSY) == S.RELAY_SAYS &&
              (0..60_000L step 500).none { m(asked = it, relay = R.BUSY) == S.CLOUD })
    check("and not before the door's second, which may still find a PC that can",
          m(asked = second - 1, relay = R.BUSY) == S.WAIT)
    check("the relay's PC answered it cannot now: its words",
          m(asked = 5000, door = Road.Door.NOBODY, pc = Road.Pc.UNREACHED, relay = R.READY,
            run = Road.Run.TOOK, relayPc = Road.Pc.BUSY) == S.RELAY_SAYS)
    check("the relay's PC refused the recording: nowhere else",
          m(asked = 5000, door = Road.Door.NOBODY, pc = Road.Pc.UNREACHED, relay = R.READY,
            run = Road.Run.TOOK, relayPc = Road.Pc.REFUSED) == S.RELAY_SAYS)
    check("a PC that answers through the account after the cloud set out: the cloud's turn stands",
          m(asked = 5000, pc = Road.Pc.UNREACHED, door = Road.Door.NOBODY, relay = R.READY,
            cloud = Road.Cloud.PENDING) == S.WAIT)
    check("the cloud failed and a PC answered through the account: back up the ladder",
          m(asked = 5000, pc = Road.Pc.UNREACHED, door = Road.Door.NOBODY, relay = R.READY,
            cloud = Road.Cloud.FAILED) == S.RELAY)
    check("the relay is asked once: never twice while it works",
          m(asked = 5000, relay = R.READY, run = Road.Run.SENDING) != S.RELAY)
    // stage 2b's table as it was merged (125912d), word for word: with the relay off the
    // ladder must be it, so nothing a person checked on his phone moved
    fun was2b(m: Road.Moment): Road.Step = when {
        m.pc == Road.Pc.OK -> S.LAND_PC
        m.cloud == Road.Cloud.OK -> S.LAND_CLOUD
        m.pc == Road.Pc.REFUSED -> if (m.cloud == Road.Cloud.PENDING) S.WAIT else S.PC_SAYS
        !m.active || !m.keyed -> if (m.pc == Road.Pc.PENDING) S.WAIT else S.PC_SAYS
        m.pc == Road.Pc.BUSY -> if (m.cloud == Road.Cloud.PENDING) S.WAIT else S.PC_SAYS
        m.cloud == Road.Cloud.PENDING -> S.WAIT
        m.cloud == Road.Cloud.FAILED -> if (m.pc == Road.Pc.PENDING) S.WAIT else S.CLOUD_SAYS
        m.pc == Road.Pc.UNREACHED -> S.CLOUD
        m.door == Road.Door.NOT_YET && m.askedMs >= Road.ASK_MS && m.roadMs >= Road.ROAD_MS -> S.CLOUD
        m.door == Road.Door.ANSWERED && m.silentMs >= Road.SILENT_MS -> S.CLOUD
        else -> S.WAIT
    }
    check("with the relay off, the 2b table is the table: every moment, the same step", run {
        var same = true
        val ts = listOf(0L, 299L, 300L, 999L, 1000L, 9_999L, 10_000L, 99_999L)
        for (a in listOf(true, false)) for (k in listOf(true, false)) for (d in Road.Door.values())
            for (p in Road.Pc.values()) for (cl in Road.Cloud.values())
                for (asked in ts) for (road in ts) for (silent in ts) {
                    val mo = Road.Moment(a, k, asked, road, d, silent, p, cl)
                    if (Road.next(mo) != was2b(mo)) same = false
                }
        same
    })
    check("every step is reachable from the table", S.values().all { step ->
        val all = HashSet<Road.Step>()
        for (a in listOf(true, false)) for (k in listOf(true, false)) for (d in Road.Door.values())
            for (p in Road.Pc.values()) for (cl in Road.Cloud.values()) for (rl in Road.Relay.values())
                for (rn in Road.Run.values()) for (rp in Road.Pc.values()) for (t in listOf(0L, 99_999L))
                    all.add(m(a, k, t, d, t, p, cl, t, rl, rn, t, rp))
        step in all
    })
    check("the line, through the account: the recording's length, the PC's engine, and how",
          CloudLine.note(Transcriber.Result.Ok("שלום", null, "local", 3.7, via = "via your account")) ==
              "3.7 s · local via your account")

    // ---- the pieces, against the real relay.py ----
    val key = ByteArray(32) { it.toByte() }
    val V = RelayVectors
    val text = try {
        RelayWire.open(key, V.UID, mapOf("device" to V.PC, "to" to V.PHONE, "rid" to V.RID,
                                         "n" to 2L, "s" to V.TEXT_S))
    } catch (e: RelayWire.Refused) {
        null
    }
    @Suppress("UNCHECKED_CAST")
    val body = text?.head?.get("body") as? Map<String, Any?> ?: emptyMap()
    check("the PC's text, sealed by the real relay.py, opens here, Hebrew and quotes whole",
          text != null && text.kind == "text" && text.head["status"] == 200L &&
              body["text"] == "שלום \"מהדרך\"" && body["seconds"] == 4.5 && body["backend"] == "local")
    check("and reads as /transcribe's answer", text != null && RelayWire.answer(text).first == 200)
    check("a piece over the broadcast cap is refused, never sent to be refused there",
          refused { RelayWire.seal(key, V.UID, V.PHONE, V.PC, V.RID, 0, RelayWire.audioHead(), ByteArray(200_000)) })
    val ping = RelayWire.seal(key, V.UID, V.PHONE, RelayWire.EVERY_PC, V.RID, 0, RelayWire.pingHead(),
                              nonce = ByteArray(12) { (30 + it).toByte() })
    check("the phone's ping is relay.py's, byte for byte", parsed(ping)["s"] == V.PING_S)
    val audioBody = ByteArray(1024) { (it % 256).toByte() }
    val audio = RelayWire.seal(key, V.UID, V.PHONE, V.PC, V.RID, 3, RelayWire.audioHead(), audioBody,
                               nonce = ByteArray(12) { (50 + it).toByte() })
    check("an audio piece is relay.py's, byte for byte, its body raw after the head",
          parsed(audio)["s"] == V.AUDIO_S &&
              RelayWire.open(key, V.UID, parsed(audio)).body.contentEquals(audioBody))

    // ---- every rule, broken once ----
    val good = parsed(audio)
    check("moved to another place in the request: does not open",
          refused { RelayWire.open(key, V.UID, good + ("n" to 4L)) })
    check("moved to another request: does not open",
          refused { RelayWire.open(key, V.UID, good + ("rid" to "f".repeat(32))) })
    check("said to be from another device: does not open",
          refused { RelayWire.open(key, V.UID, good + ("device" to V.PC)) })
    check("said to be for another device: does not open",
          refused { RelayWire.open(key, V.UID, good + ("to" to "cccccccc-0000-4000-8000-000000000003")) })
    check("under another account: does not open", refused {
        RelayWire.open(key, "99999999-2222-3333-4444-555555555555", good)
    })
    check("under another key: does not open", refused { RelayWire.open(ByteArray(32), V.UID, good) })
    check("a piece that is not one is refused before anything is opened",
          refused { RelayWire.open(key, V.UID, good - "rid") } &&
              refused { RelayWire.open(key, V.UID, good + ("rid" to "not-hex")) } &&
              refused { RelayWire.open(key, V.UID, good + ("n" to 999L)) })
    val sealedWithOtherHead = RelayWire.seal(key, V.UID, V.PHONE, V.PC, V.RID, 5, "{\"v\":2,\"k\":\"audio\"}")
    check("a head of another version is not read", refused { RelayWire.open(key, V.UID, parsed(sealedWithOtherHead)) })

    // ---- a recording, cut into pieces that fit the broadcast cap ----
    val longest = ByteArray(44 + Recorder.MAX_SECONDS * 32_000) { (it * 7).toByte() }
    val pieces = RelayWire.recording(key, V.UID, V.PHONE, V.PC, V.RID, longest, 1_762_877_412_345L)
    val frames = (longest.size + RelayWire.FRAME_BYTES - 1) / RelayWire.FRAME_BYTES
    check("the longest recording a phone makes is ${frames + 1} pieces, the last its end",
          pieces.size == frames + 1 && frames < RelayWire.MAX_FRAMES)
    check("every piece is under the broadcast cap, with room", pieces.all { it.length < RelayWire.PAYLOAD_MAX * 0.6 })
    val back = ByteArrayOutputStream()
    for (p in pieces.dropLast(1)) back.write(RelayWire.open(key, V.UID, parsed(p)).body)
    val end = RelayWire.open(key, V.UID, parsed(pieces.last()))
    val sha = MessageDigest.getInstance("SHA-256").digest(longest)
    check("the pieces put back together are the recording", back.toByteArray().contentEquals(longest))
    check("the end names how many, how much and the hash, as relay.py checks them",
          end.kind == "end" && end.n == frames && end.head["frames"] == frames.toLong() &&
              end.head["bytes"] == longest.size.toLong() && end.head["sha256"] == Crypt.hex(sha) &&
              end.head["at"] == 1_762_877_412_345L)
    check("a recording too long for the relay is refused, not cut",
          refused { RelayWire.recording(key, V.UID, V.PHONE, V.PC, V.RID, ByteArray(RelayWire.FRAME_BYTES * 120), 0) })
    check("request ids are 32 hex and new each time",
          RelayWire.newRid().let { it.length == 32 && it.all { ch -> ch in "0123456789abcdef" } } &&
              RelayWire.newRid() != RelayWire.newRid())

    // ---- the JSON reader ----
    check("objects, arrays, numbers, words",
          JsonIn.parse("{\"a\":[1,-2.5,true,false,null],\"b\":{}}") ==
              mapOf("a" to listOf(1L, -2.5, true, false, null), "b" to emptyMap<String, Any?>()))
    check("escapes, as JSON has them", JsonIn.parse("\"a\\\"b\\\\c\\n\\u05e9\\/\"") == "a\"b\\c\nש/")
    check("what JSON is not is Bad", listOf("{", "[1,]", "{\"a\" 1}", "\"\\x\"", "01x", "tru", "{} x").all {
        try { JsonIn.parse(it); false } catch (e: JsonIn.Bad) { true }
    })
    check("a JSON string is what Json.str writes, read back", JsonIn.parse(Json.str("a\"\u0001\nש")) == "a\"\u0001\nש")

    // ---- Phoenix ----
    val join = parsed(RelayWire.join(V.UID, "token-x", "1"))
    @Suppress("UNCHECKED_CAST")
    val config = (join["payload"] as Map<String, Any?>)["config"] as Map<String, Any?>
    check("the join: the account's private topic, its own pieces not echoed, each acknowledged",
          join["topic"] == "realtime:user:${V.UID}" && join["event"] == "phx_join" && config["private"] == true &&
              config["broadcast"] == mapOf("self" to false, "ack" to true))
    val b = parsed(RelayWire.broadcast(V.UID, audio, "7", "1"))
    @Suppress("UNCHECKED_CAST")
    val inner = b["payload"] as Map<String, Any?>
    check("a piece goes as a `link` broadcast, whole", b["event"] == "broadcast" && inner["event"] == "link" &&
        inner["payload"] == good && b["ref"] == "7")
    check("a reply is read by its ref", RelayWire.heard("{\"event\":\"phx_reply\",\"ref\":\"7\",\"payload\":{\"status\":\"ok\",\"response\":{}}}")
        .let { it is RelayWire.Heard.Reply && it.ok && it.ref == "7" })
    check("a refusal carries the server's words", RelayWire.heard(
        "{\"event\":\"phx_reply\",\"ref\":\"8\",\"payload\":{\"status\":\"error\",\"response\":{\"reason\":\"Payload too large\"}}}")
        .let { it is RelayWire.Heard.Reply && !it.ok && it.why == "Payload too large" })
    check("a link broadcast is the piece", RelayWire.heard(
        "{\"event\":\"broadcast\",\"payload\":{\"type\":\"broadcast\",\"event\":\"link\",\"payload\":$audio}}")
        .let { it is RelayWire.Heard.Link && it.payload == good })
    check("another event of the account's is nothing here", RelayWire.heard(
        "{\"event\":\"broadcast\",\"payload\":{\"type\":\"broadcast\",\"event\":\"changed\",\"payload\":{}}}") ==
        RelayWire.Heard.Other)
    check("the channel going is said", RelayWire.heard("{\"event\":\"phx_close\",\"payload\":{}}") is RelayWire.Heard.Gone &&
        RelayWire.heard("{\"event\":\"system\",\"payload\":{\"status\":\"error\",\"message\":\"token expired\"}}")
            .let { it is RelayWire.Heard.Gone && it.why == "token expired" })
    check("what is not JSON is nothing", RelayWire.heard("not json") == RelayWire.Heard.Other)

    // ---- the websocket, against a server of its own ----
    check("a client frame is masked, and its length said the RFC's three ways", run {
        val mask = byteArrayOf(1, 2, 3, 4)
        listOf(5, 300, 70_000).all { n ->
            val f = Ws.frame(0x1, ByteArray(n) { 9 }, mask)
            val second2 = f[1].toInt() and 0xff
            val head = when { n < 126 -> 2; n < 65536 -> 4; else -> 10 }
            (second2 and 0x80) != 0 && f.size == head + 4 + n && (f[head + 4].toInt() xor 1) == 9
        }
    })
    val server = ServerSocket(0, 1, InetAddress.getLoopbackAddress())
    val serverGot = ArrayList<String>()
    var handshake = ""
    val serving = thread {
        server.accept().use { s ->
            val input = s.getInputStream()
            val out = s.getOutputStream()
            val head = StringBuilder()
            while (!head.endsWith("\r\n\r\n")) head.append(input.read().toChar())
            handshake = head.toString()
            val key = Regex("Sec-WebSocket-Key: (\\S+)").find(handshake)!!.groupValues[1]
            val accept = Base64.getEncoder().encodeToString(MessageDigest.getInstance("SHA-1")
                .digest((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").toByteArray()))
            out.write("HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: $accept\r\n\r\n".toByteArray())
            fun frameOut(op: Int, data: ByteArray) {
                out.write(0x80 or op)
                if (data.size < 126) out.write(data.size) else { out.write(126); out.write(data.size shr 8); out.write(data.size and 0xff) }
                out.write(data); out.flush()
            }
            fun readFrame(): Pair<Int, ByteArray> {
                fun rd(n: Int, i: InputStream) = ByteArray(n).also { var at = 0; while (at < n) at += i.read(it, at, n - at) }
                val h = rd(2, input)
                var n = h[1].toInt() and 0x7f
                if (n == 126) { val e = rd(2, input); n = ((e[0].toInt() and 0xff) shl 8) or (e[1].toInt() and 0xff) }
                val mask = rd(4, input)
                val d = rd(n, input)
                for (i in d.indices) d[i] = (d[i].toInt() xor mask[i and 3].toInt()).toByte()
                return Pair(h[0].toInt() and 0x0f, d)
            }
            frameOut(0x9, "hi".toByteArray())                    // a ping: the client answers it
            // the client's message and its answer to the ping, in whichever order they came
            val two = listOf(readFrame(), readFrame())
            serverGot.add("pong:" + String(two.first { it.first == 0xA }.second))
            serverGot.add(String(two.first { it.first == 0x1 }.second))
            frameOut(0x1, "{\"event\":\"phx_reply\"}".toByteArray())
            // one message in two fragments
            out.write(0x01); out.write(3); out.write("abc".toByteArray())
            out.write(0x80); out.write(3); out.write("def".toByteArray()); out.flush()
            frameOut(0x8, byteArrayOf(0x03, 0xe8.toByte()))
        }
    }
    val ws = Ws.open("ws://127.0.0.1:${server.localPort}/realtime/v1/websocket?vsn=1.0.0",
                     mapOf("apikey" to "sb_publishable_x"), 5000)
    ws.send("{\"hello\":1}")
    val first = ws.next(5000)
    val joined = ws.next(5000)
    val gone = ws.next(5000)
    serving.join(5000)
    server.close()
    check("the handshake: the path, the query, the version and the key header",
          handshake.startsWith("GET /realtime/v1/websocket?vsn=1.0.0 HTTP/1.1\r\n") &&
              "Sec-WebSocket-Version: 13\r\n" in handshake && "apikey: sb_publishable_x\r\n" in handshake)
    check("the server's ping is answered with its own bytes", serverGot.getOrNull(0) == "pong:hi")
    check("a message goes out whole", serverGot.getOrNull(1) == "{\"hello\":1}")
    check("a message comes in whole, and one in two fragments too",
          first == "{\"event\":\"phx_reply\"}" && joined == "abcdef")
    check("a close is the end, said once", gone == GONE && ws.closed)
    check("a ws:// address is the fake's alone: anything but ws and wss is refused", try {
        Ws.open("http://127.0.0.1:1/", emptyMap(), 500); false
    } catch (e: java.io.IOException) {
        true
    })
}
