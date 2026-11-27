package io.github.deskit_app.deskit

import java.security.MessageDigest

/**
 * A recording sent while it is spoken (PHONE_LINK_PLAN.md stage 2), with nothing of
 * Android's in it: the buffer the stream reads, the door's frames byte by byte as
 * server.py's read_frame takes them, the relay's streamed pieces against what the real
 * relay.py sealed, the WAV they join back into, every rule broken once, and the ladder
 * with a relay that carried it while it was spoken. Run from CryptChecks' main.
 */
private object StreamVectors {
    const val UID = "11111111-2222-3333-4444-555555555555"
    const val PC = "aaaaaaaa-0000-4000-8000-000000000001"
    const val PHONE = "bbbbbbbb-0000-4000-8000-000000000002"
    const val RID = "0123456789abcdef0123456789abcdef"

    // dev/android/make_relay_vectors.py's output, pasted: relay.seal with chosen nonces
    const val STREAMED_S = "v1.RkdISUpLTE1OT1BRsNhsTXdOjQKu7qe1o9U1hdvlK6bNj8v6QJF1DmwIGzclR0ZGAwSLjnjyeaOKLqNhNfwdUfGQWXc7/MsXM4ZmUuml6zfFDq51Fe31YU3JljQ6slsaLGZUlMXg+lp83awSIugzZBHg/zEnQiCG139iLSCJgWyBbchPnqq+aNiCQkmRFdnrtufS3z/r4YSsqW7OTUo7MclfVOK31CX6Dfswr84uknU0JzVS8eKJAY+Q8yOmjM/nL40rtmy5xxds9LBGAg57ID6YmLDl6uvzs8SkSIc5fZehRutoLbXmv80elV0wkWXjpyx4Pu4ImQwk1OypQLyA/bIOEzU4+zrLDQb6ebkd+KSIJRj/PXHn5+7V+Sdr9VIRQA/g/62XFyGWKb5enh1hJijPi0/WGIXMuClrBqgMPyKlYmOCU+j2cCyug+mKxzzg+PJG8aJ5JJTvFFoQxfTL9iTUinLpoauQGZRcki5K9op9F93LUwdziq5LCZGXxk8k44qQ3iHhQ3fkwEbRNGbFXi5FWAHj+ERRWKRHYuo9LloAp2aBazN6SGsSMfJKKKTG8dS0uMj2BzahZZa6u42vAx7iRqpS55O8IHcoiUF1/l9ylyLe89wnKRPV6sX54DWuV8rtZ+sGx01lVO/WvJj9EjZdUZFhzXvGJ5jxW3wPukkxa53ZrGiQDDAJCNrtCE0TzHC4ggRtc5xbqxkU8OVOtzAOHPH94scSXgvVJgacfZipyJZ6drztoy8ToyaMRgfIL+fJ44BjyVPmtfJHmsEllXNW6B9AUt98Hj0/7xGhQfXzHmIat6knR/Cs/xjvze5tb1CFiamvwFxJ8EYKXScIVcqH5k+Y2GxQRD8YTdy4r8tcc91JJCCLhEqhVUmCB9rCKZjwq4LX/NdXDNjW4R7QsFfySf/zICXZeOrhYRU6GNA3grEf7INIUF6QOUzArrHoEeDgl79tImGw0bNep5Ur2c5qd4aLz6k94v7BLluFNwTOfmSroMvG2o3jeQKv45AiRX+dYnOSTaS8nXh/NIwZ9VBNDtinccusDa68zTWvF1q7YPY/902Ry1kLzvkjS21fYdXsk1r8qgRwCZzQOO/r4v6RedLjRo/aTEqPE/+dvSZe0YgPay+r0Bj71wHSKUiq9BJCdd4ZG2GjFx2FUhSxyGOoWrrcf1xWIZmLBfeD20dLNY8i+ccfNAXyrtJQWantYZBM2B496UgZymumKuFYFd8IU02dk43qQBfn7jvRtcgCyz+30MTFxkY0AhfylP+jJUxn/+I8mR7UH06D0ZX98R79uWu5tnf+Wpm0MTX9qaZBDAEzJvp5Bef9go+k9pBmOeAVN5Y/2DMAWHryN97ZjpdTwQUtP5QN2kq96/dY1fOopZNpltHGrgJvxUT+WYZHO7I+sE8hazDBSub5tXPnebrFdowEKuUKR34R4g=="
    const val CANCEL_S = "v1.WltcXV5fYGFiY2Rl+dauUJpRUMc61DRPGkpD4BPmVmjqoscuxYrafCOcttXkmGypug=="
}

private fun refusedHere(block: () -> Unit): Boolean = try {
    block(); false
} catch (e: RelayWire.Refused) {
    true
}

@Suppress("UNCHECKED_CAST")
private fun parsedHere(json: String): Map<String, Any?> = JsonIn.parse(json) as Map<String, Any?>

/** (kind, payload) of every frame in [body], as server.py's read_frame reads them, or null. */
private fun frames(body: ByteArray): List<Pair<Char, ByteArray>>? {
    val out = ArrayList<Pair<Char, ByteArray>>()
    var at = 0
    while (at < body.size) {
        if (at + 5 > body.size) return null
        val n = ((body[at + 1].toInt() and 0xff) shl 24) or ((body[at + 2].toInt() and 0xff) shl 16) or
            ((body[at + 3].toInt() and 0xff) shl 8) or (body[at + 4].toInt() and 0xff)
        if (n > (1 shl 20) || at + 5 + n > body.size) return null
        out.add(Pair(body[at].toInt().toChar(), body.copyOfRange(at + 5, at + 5 + n)))
        at += 5 + n
    }
    return out
}

internal fun streamChecks(check: (String, Boolean) -> Unit) {
    val V = StreamVectors
    val key = ByteArray(32) { it.toByte() }

    // ---- the buffer the stream reads while the mic writes ----
    val buf = PcmBuffer()
    val chunk = ByteArray(4096) { (it % 251).toByte() }
    repeat(40) { buf.write(chunk, 0, 4096) }                        // grows past its first 64 KB
    check("the buffer keeps every byte the mic wrote, in order",
          buf.size == 40 * 4096 && buf.all().contentEquals(ByteArray(40 * 4096) { ((it % 4096) % 251).toByte() }))
    check("since() is what came after the offset, and nothing past the end",
          buf.since(4096 * 39).contentEquals(chunk) && buf.since(buf.size).isEmpty() &&
              buf.since(buf.size + 9).isEmpty())
    buf.reset()
    check("a new recording starts empty", buf.size == 0 && buf.all().isEmpty())

    // ---- the WAV's header, apart from its body ----
    val pcm = ByteArray(300_001) { (it * 13).toByte() }
    check("the header is the 44 bytes in front of the PCM, the length in it",
          Recorder.header(pcm.size).size == Recorder.HEADER &&
              Recorder.wav(pcm).copyOfRange(Recorder.HEADER, Recorder.HEADER + pcm.size).contentEquals(pcm) &&
              Recorder.pcm(Recorder.wav(pcm)).contentEquals(pcm))

    // ---- the door's /stream, frame by frame ----
    val head = StreamWire.head()
    check("the head is server.py's: {\"v\":1,\"rate\":16000,\"bits\":16,\"channels\":1}, kind H",
          frames(head)?.single()?.let { (k, p) ->
              k == 'H' && String(p, Charsets.UTF_8) == "{\"v\":1,\"rate\":16000,\"bits\":16,\"channels\":1}"
          } == true)
    val audio = StreamWire.audio(pcm)
    val joined = audio.flatMap { frames(it) ?: emptyList() }
    check("a kept recording crosses as frames none over AUDIO_MAX, and they join back into it",
          joined.isNotEmpty() && joined.all { it.first == 'A' && it.second.size <= StreamWire.AUDIO_MAX } &&
              joined.fold(ByteArray(0)) { a, f -> a + f.second }.contentEquals(pcm))
    check("nothing to send is no frame at all", StreamWire.audio(ByteArray(0)).isEmpty())
    val sha = Crypt.hex(MessageDigest.getInstance("SHA-256").digest(pcm))
    check("the end says how many bytes came and their SHA-256",
          frames(StreamWire.end(pcm.size, sha))?.single()?.let { (k, p) ->
              k == 'E' && String(p, Charsets.UTF_8) == "{\"bytes\":${pcm.size},\"sha256\":\"$sha\"}"
          } == true)
    check("a cancel is said: kind C, nothing in it",
          StreamWire.cancel().contentEquals(byteArrayOf('C'.code.toByte(), 0, 0, 0, 0)))
    val body = head + audio.fold(ByteArray(0)) { a, f -> a + f } + StreamWire.end(pcm.size, sha)
    check("a whole stream reads back as head, audio, end", frames(body)?.let { f ->
        f.first().first == 'H' && f.last().first == 'E' && f.drop(1).dropLast(1).all { it.first == 'A' }
    } == true)

    // ---- the relay's streamed pieces, relay.py's byte for byte ----
    val body1024 = ByteArray(1024) { (it % 256).toByte() }
    val streamed = RelayWire.seal(key, V.UID, V.PHONE, V.PC, V.RID, 2, RelayWire.streamHead(RelayWire.FRAME_BYTES),
                                  body1024, nonce = ByteArray(12) { (70 + it).toByte() })
    check("a piece sent while it is spoken is relay.py's, byte for byte, its place in its head",
          parsedHere(streamed)["s"] == V.STREAMED_S)
    val cancel = RelayWire.seal(key, V.UID, V.PHONE, V.PC, V.RID, RelayWire.N_CANCEL, RelayWire.cancelHead(),
                                nonce = ByteArray(12) { (90 + it).toByte() })
    check("a cancel is relay.py's, byte for byte, at the place no recording reaches",
          parsedHere(cancel)["s"] == V.CANCEL_S && RelayWire.N_CANCEL == RelayWire.MAX_FRAMES)
    val one = RelayWire.open(key, V.UID, parsedHere(
        RelayWire.streamed(key, V.UID, V.PHONE, V.PC, V.RID, RelayWire.FRAME_BYTES, body1024)))
    check("streamed() puts piece 2 at PCM 96,000 and its bytes after the head",
          one.n == 2 && one.kind == "audio" && one.head["pcm"] == RelayWire.FRAME_BYTES.toLong() &&
              one.body.contentEquals(body1024))

    // a whole recording streamed: piece 0 the header, sent last, joined back into the WAV
    val longest = ByteArray(Recorder.MAX_SECONDS * 32_000) { (it * 7).toByte() }
    val wav = Recorder.wav(longest)
    val pieces = ArrayList<Pair<Int, String>>()
    var at = 0
    while (at < longest.size) {
        val end = minOf(longest.size, at + RelayWire.FRAME_BYTES)
        pieces.add(Pair(1 + at / RelayWire.FRAME_BYTES,
                        RelayWire.streamed(key, V.UID, V.PHONE, V.PC, V.RID, at, longest.copyOfRange(at, end))))
        at = end
    }
    pieces.add(Pair(0, RelayWire.header(key, V.UID, V.PHONE, V.PC, V.RID, longest.size)))
    val endPiece = RelayWire.streamedEnd(key, V.UID, V.PHONE, V.PC, V.RID, wav, 1_762_877_412_345L)
    val opened = pieces.map { RelayWire.open(key, V.UID, parsedHere(it.second)) }.sortedBy { it.n }
    val back = opened.fold(ByteArray(0)) { a, p -> a + p.body }
    val endOpen = RelayWire.open(key, V.UID, parsedHere(endPiece))
    check("joined by their places, header first, the pieces are the WAV the end names",
          back.contentEquals(wav) && endOpen.kind == "end" &&
              endOpen.head["frames"] == opened.size.toLong() && endOpen.n == opened.size &&
              endOpen.head["bytes"] == wav.size.toLong() &&
              endOpen.head["sha256"] == RelayWire.sha256Hex(wav))
    check("the longest recording streamed is ${opened.size + 1} pieces, inside MAX_FRAMES",
          opened.size + 1 <= RelayWire.MAX_FRAMES && RelayWire.streamedFrames(longest.size) == opened.size)
    check("every streamed piece is under the broadcast cap, with room",
          pieces.all { it.second.length < RelayWire.PAYLOAD_MAX * 0.6 })
    check("a streamed piece is where streamed() says: n is 1 + its place / FRAME_BYTES",
          opened.drop(1).all { it.head["pcm"] == ((it.n - 1) * RelayWire.FRAME_BYTES).toLong() })

    // every rule, broken once
    check("a place between pieces is refused",
          refusedHere { RelayWire.streamed(key, V.UID, V.PHONE, V.PC, V.RID, 1000, body1024) })
    check("an empty piece is refused", refusedHere { RelayWire.streamed(key, V.UID, V.PHONE, V.PC, V.RID, 0, ByteArray(0)) })
    check("a piece over FRAME_BYTES is refused",
          refusedHere { RelayWire.streamed(key, V.UID, V.PHONE, V.PC, V.RID, 0, ByteArray(RelayWire.FRAME_BYTES + 1)) })
    check("a place past the longest recording is refused", refusedHere {
        RelayWire.streamed(key, V.UID, V.PHONE, V.PC, V.RID, RelayWire.MAX_FRAMES * RelayWire.FRAME_BYTES, body1024)
    })
    check("a streamed piece moved to another place does not open",
          refusedHere { RelayWire.open(key, V.UID, parsedHere(streamed) + ("n" to 3L)) })
    check("a cancel moved to an audio piece's place does not open",
          refusedHere { RelayWire.open(key, V.UID, parsedHere(cancel) + ("n" to 0L)) })

    // ---- the ladder, with a relay that carried it while it was spoken ----
    fun m(asked: Long, road: Long, relay: Road.Relay = Road.Relay.READY, door: Road.Door = Road.Door.NOT_YET,
          streaming: Boolean, active: Boolean = true) =
        Road.next(Road.Moment(active, true, asked, road, door, 0, Road.Pc.PENDING, Road.Cloud.IDLE, relay,
                              Road.Run.IDLE, 0, Road.Pc.PENDING, relayStreaming = streaming))
    check("a relay that carried it while it was spoken goes at the release: no door's moment more",
          m(asked = 5000, road = 0, streaming = true) == Road.Step.RELAY &&
              m(asked = 5000, road = 0, streaming = false) == Road.Step.WAIT)
    check("never before the door's second, streamed or not",
          m(asked = Road.ASK_MS - 1, road = 0, streaming = true) == Road.Step.WAIT)
    check("a door that answered is never passed over for it",
          m(asked = 5000, road = 0, door = Road.Door.ANSWERED, streaming = true) == Road.Step.WAIT)
    check("with the backup off it is the same relay",
          m(asked = 5000, road = 0, streaming = true, active = false) == Road.Step.RELAY)
    check("nor does it make the cloud go sooner: a relay nobody answered is the old table",
          m(asked = 5000, road = 0, relay = Road.Relay.NOBODY, streaming = true) ==
              m(asked = 5000, road = 0, relay = Road.Relay.NOBODY, streaming = false))
}
