package io.github.deskit_app.deskit

import java.io.ByteArrayOutputStream
import java.io.IOException
import java.io.InputStream
import java.io.OutputStream
import java.net.InetSocketAddress
import java.net.Socket
import java.security.MessageDigest
import java.util.Base64
import java.util.concurrent.LinkedBlockingQueue
import java.util.concurrent.TimeUnit
import javax.net.ssl.HttpsURLConnection
import javax.net.ssl.SSLSocket
import javax.net.ssl.SSLSocketFactory

/**
 * One websocket, by hand, the way net.py's is (RFC 6455, client side): the account's
 * channel, for the sealed relay (PHONE_LINK_PLAN.md stage 3). No library, because the
 * app has none, and nothing of Android's, so the JVM checks hold it against a server
 * of their own. Why not a hidden WebView running link.js, as the plan first said: the
 * relay needs only a socket, a WebView costs the keyboard 40 MB and 446 ms before it
 * says anything, and Kotlin seals anyway; the WebView waits for the direct road.
 *
 * `wss://` checks the host's certificate against the phone's own trust store and the
 * host's name against the certificate, as HttpsURLConnection does: an SSLSocket by
 * itself checks no name. `ws://` is the emulator's fake account and nothing else
 * (`-PdeskitAccount=http://…`, debug builds only).
 *
 * A thread reads: every whole text message goes on [messages], a ping is answered, a
 * close or a broken socket ends it ([closed]). [send] may be called from any thread.
 */
class Ws private constructor(private val socket: Socket, private val input: InputStream,
                             private val output: OutputStream) {
    /** Every text message, whole, in the order it came. */
    val messages = LinkedBlockingQueue<String>()
    @Volatile var closed = false
        private set
    @Volatile var why: String = ""
        private set
    private val writeLock = Any()
    private val random = java.security.SecureRandom()

    companion object {
        const val MAX_FRAME = 4 * 1024 * 1024
        private const val GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

        /**
         * Open [url] (`wss://host/path?query` or `ws://`), with [headers], within
         * [timeoutMs]. IOException on anything but a checked 101.
         */
        fun open(url: String, headers: Map<String, String>, timeoutMs: Int): Ws {
            val u = java.net.URI(url)
            val tls = when (u.scheme) {
                "wss" -> true
                "ws" -> false
                else -> throw IOException("not a websocket address")
            }
            val host = u.host ?: throw IOException("no host")
            val port = if (u.port > 0) u.port else if (tls) 443 else 80
            val raw = Socket()
            raw.connect(InetSocketAddress(host, port), timeoutMs)
            raw.soTimeout = timeoutMs
            val socket: Socket = if (tls) {
                val s = (SSLSocketFactory.getDefault() as SSLSocketFactory)
                    .createSocket(raw, host, port, true) as SSLSocket
                s.sslParameters = s.sslParameters.apply { endpointIdentificationAlgorithm = "HTTPS" }
                s.startHandshake()
                if (!HttpsURLConnection.getDefaultHostnameVerifier().verify(host, s.session)) {
                    s.close()
                    throw IOException("the server's certificate does not name it")
                }
                s
            } else raw
            try {
                val input = socket.getInputStream()
                val output = socket.getOutputStream()
                val key = Base64.getEncoder().encodeToString(ByteArray(16).also { java.security.SecureRandom().nextBytes(it) })
                val path = (u.rawPath ?: "/").ifEmpty { "/" } + (u.rawQuery?.let { "?$it" } ?: "")
                val head = StringBuilder()
                    .append("GET ").append(path).append(" HTTP/1.1\r\n")
                    .append("Host: ").append(host).append(if (u.port > 0) ":${u.port}" else "").append("\r\n")
                    .append("Upgrade: websocket\r\nConnection: Upgrade\r\n")
                    .append("Sec-WebSocket-Key: ").append(key).append("\r\n")
                    .append("Sec-WebSocket-Version: 13\r\n")
                for ((k, v) in headers) head.append(k).append(": ").append(v).append("\r\n")
                output.write(head.append("\r\n").toString().toByteArray(Charsets.UTF_8))
                output.flush()
                val answer = readHead(input)
                val status = answer.lineSequence().first().split(" ").getOrNull(1)?.toIntOrNull() ?: 0
                if (status != 101) throw IOException("the websocket was refused: HTTP $status")
                val want = Base64.getEncoder().encodeToString(
                    MessageDigest.getInstance("SHA-1").digest((key + GUID).toByteArray(Charsets.US_ASCII)))
                val accept = answer.lineSequence().drop(1).map { it.split(":", limit = 2) }
                    .firstOrNull { it.size == 2 && it[0].trim().equals("Sec-WebSocket-Accept", true) }
                    ?.get(1)?.trim()
                if (accept != want) throw IOException("the websocket handshake did not check out")
                socket.soTimeout = 0
                return Ws(socket, input, output).also { it.startReading() }
            } catch (e: IOException) {
                socket.close()
                throw e
            }
        }

        private fun readHead(input: InputStream): String {
            val out = ByteArrayOutputStream()
            var tail = 0
            while (true) {
                val b = input.read()
                if (b < 0) throw IOException("the server hung up during the handshake")
                out.write(b)
                tail = (tail shl 8) or b
                if (tail == 0x0d0a0d0a) return String(out.toByteArray(), Charsets.ISO_8859_1)
                if (out.size() > 65536) throw IOException("a handshake answer over 64 KB")
            }
        }

        /** One client frame: FIN, [opcode], masked with [mask] (RFC 6455, 5.3). */
        fun frame(opcode: Int, data: ByteArray, mask: ByteArray): ByteArray {
            val out = ByteArrayOutputStream(data.size + 14)
            out.write(0x80 or opcode)
            when {
                data.size < 126 -> out.write(0x80 or data.size)
                data.size < 65536 -> {
                    out.write(0x80 or 126); out.write(data.size shr 8); out.write(data.size and 0xff)
                }
                else -> {
                    out.write(0x80 or 127)
                    for (shift in 56 downTo 0 step 8) out.write(((data.size.toLong() shr shift) and 0xff).toInt())
                }
            }
            out.write(mask)
            val masked = ByteArray(data.size)
            for (i in data.indices) masked[i] = (data[i].toInt() xor mask[i and 3].toInt()).toByte()
            out.write(masked)
            return out.toByteArray()
        }
    }

    private fun startReading() {
        Thread({ read() }, "relay-ws").apply { isDaemon = true }.start()
    }

    private fun readFully(n: Int): ByteArray {
        val buf = ByteArray(n)
        var at = 0
        while (at < n) {
            val got = input.read(buf, at, n - at)
            if (got < 0) throw IOException("the server closed the websocket")
            at += got
        }
        return buf
    }

    private fun read() {
        val parts = ByteArrayOutputStream()
        try {
            while (!closed) {
                val h = readFully(2)
                val fin = (h[0].toInt() and 0x80) != 0
                val opcode = h[0].toInt() and 0x0f
                val masked = (h[1].toInt() and 0x80) != 0
                var n = (h[1].toInt() and 0x7f).toLong()
                if (n == 126L) {
                    val e = readFully(2); n = ((e[0].toInt() and 0xff) shl 8 or (e[1].toInt() and 0xff)).toLong()
                } else if (n == 127L) {
                    val e = readFully(8); n = 0
                    for (b in e) n = (n shl 8) or (b.toLong() and 0xff)
                }
                if (n > MAX_FRAME) throw IOException("a websocket frame of $n bytes")
                val mask = if (masked) readFully(4) else null
                val data = readFully(n.toInt())
                if (mask != null) for (i in data.indices) data[i] = (data[i].toInt() xor mask[i and 3].toInt()).toByte()
                when (opcode) {
                    0x8 -> { why = "closed by the server"; break }
                    0x9 -> write(0xA, data)
                    0xA -> {}
                    0x0, 0x1, 0x2 -> {
                        parts.write(data)
                        if (fin) {
                            val whole = parts.toByteArray()
                            parts.reset()
                            if (opcode != 0x2) messages.put(String(whole, Charsets.UTF_8))
                        }
                    }
                }
            }
        } catch (e: IOException) {
            if (!closed) why = e.javaClass.simpleName
        } finally {
            closed = true
            try { socket.close() } catch (e: IOException) {}
            messages.put(GONE)
        }
    }

    private fun write(opcode: Int, data: ByteArray) {
        val mask = ByteArray(4).also { random.nextBytes(it) }
        val f = frame(opcode, data, mask)
        synchronized(writeLock) {
            if (closed) throw IOException("the websocket is closed")
            output.write(f)
            output.flush()
        }
    }

    /** One text message. IOException when the socket is gone. */
    fun send(text: String) = write(0x1, text.toByteArray(Charsets.UTF_8))

    /** The next message, or null after [timeoutMs]; [GONE] once the socket went. */
    fun next(timeoutMs: Long): String? = messages.poll(timeoutMs, TimeUnit.MILLISECONDS)

    fun close() {
        if (closed) return
        try {
            write(0x8, byteArrayOf(0x03, 0xe8.toByte()))
        } catch (e: IOException) {
            // gone already
        }
        closed = true
        try { socket.close() } catch (e: IOException) {}
    }
}

/** What [Ws.messages] says once the socket went: never a message a server sends. */
const val GONE = "\u0000gone"
