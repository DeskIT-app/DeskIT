package io.github.deskit_app.deskit

/**
 * The door's `/stream`, the phone's half (PHONE_LINK_PLAN.md stage 2; server.py's
 * `read_frame` is the PC's and the truth). The recording is written while it is
 * spoken, as frames in one chunked POST:
 *
 *     kind (1 byte) · length (4 bytes, big-endian) · that many bytes
 *
 * `H` the head first, `{"v":1,"rate":16000,"bits":16,"channels":1}`; then `A`, the
 * PCM as it comes, any size up to [AUDIO_MAX]; then exactly one `E`, the end,
 * `{"bytes":N,"sha256":"…"}` of all the PCM, or `C`, cancel. An end and a cancel are
 * said and never inferred from the body stopping: a cancel and a break look alike
 * otherwise. Nothing of Android's here, so the JVM checks hold every byte of it.
 */
object StreamWire {
    const val PROTO = 1
    /** server.FRAME_MAX is a megabyte; an audio frame stays well under it. */
    const val AUDIO_MAX = 64 * 1024

    fun frame(kind: Char, payload: ByteArray = ByteArray(0)): ByteArray {
        val n = payload.size
        return byteArrayOf(kind.code.toByte(), (n ushr 24).toByte(), (n ushr 16).toByte(),
                           (n ushr 8).toByte(), n.toByte()) + payload
    }

    fun head(): ByteArray =
        frame('H', "{\"v\":$PROTO,\"rate\":${Recorder.SAMPLE_RATE},\"bits\":16,\"channels\":1}"
            .toByteArray(Charsets.UTF_8))

    /** [pcm] as audio frames, none over [AUDIO_MAX]: a kept recording crosses at once. */
    fun audio(pcm: ByteArray): List<ByteArray> =
        (pcm.indices step AUDIO_MAX).map { frame('A', pcm.copyOfRange(it, minOf(pcm.size, it + AUDIO_MAX))) }

    fun end(bytes: Int, sha256: String): ByteArray =
        frame('E', "{\"bytes\":$bytes,\"sha256\":${Json.str(sha256)}}".toByteArray(Charsets.UTF_8))

    fun cancel(): ByteArray = frame('C')
}
