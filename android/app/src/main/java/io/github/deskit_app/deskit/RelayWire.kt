package io.github.deskit_app.deskit

import java.security.MessageDigest

/**
 * The sealed relay's formats, with nothing of Android's in them, so the JVM checks
 * hold every one (PHONE_LINK_PLAN.md stage 3; relay.py is the PC's other hand and the
 * truth). A piece on the account's topic is
 *
 *     {"device": <from>, "to": <to, or "*">, "rid": <request>, "n": <piece>, "s": "v1.…"}
 *
 * and `s` seals `<head JSON>\n<body>` under the AAD `link/{uid}/{from}/{to}/{rid}/{n}`,
 * so a piece moved to another request, place, sender or device does not open. The
 * heads, in the order relay.py's json.dumps writes them, because the bytes are what
 * the seal covers: `{"v":1,"k":"ping"}`, `{"v":1,"k":"audio"}`, `{"v":1,"k":"end",
 * "frames":N,"bytes":B,"sha256":"…","at":ms}`; from the PC `pong`, `took`, `text`.
 */
object RelayWire {
    const val PROTO = 1
    /** relay.FRAME_BYTES: 3.0 s of 16 kHz 16-bit mono, about 128 KB once sealed. */
    const val FRAME_BYTES = 96_000
    /** Supabase Free's broadcast cap, as relay.PAYLOAD_MAX. */
    const val PAYLOAD_MAX = 256_000
    /** relay.MAX_FRAMES: the longest recording a phone makes, in pieces, and room. */
    const val MAX_FRAMES = 110
    const val N_PONG = 0
    const val N_TOOK = 1
    const val N_TEXT = 2
    const val EVERY_PC = "*"

    class Refused(why: String) : Exception(why)

    /** One piece as it came: who sent it, for whom, and what it says. */
    class Piece(val from: String, val to: String, val rid: String, val n: Int,
                val head: Map<String, Any?>, val body: ByteArray) {
        val kind: String get() = head["k"] as? String ?: ""
    }

    fun aad(uid: String, from: String, to: String, rid: String, n: Int) = "link/$uid/$from/$to/$rid/$n"

    /** A request's id: 32 hex characters, as relay.py wants them. */
    fun newRid(): String = Crypt.hex(Crypt.randomBytes(16))

    fun sha256Hex(raw: ByteArray): String = Crypt.hex(MessageDigest.getInstance("SHA-256").digest(raw))

    // ---- heads, in json.dumps' order ----

    fun pingHead() = "{\"v\":$PROTO,\"k\":\"ping\"}"
    fun audioHead() = "{\"v\":$PROTO,\"k\":\"audio\"}"

    fun endHead(frames: Int, bytes: Int, sha256: String, atMs: Long) =
        "{\"v\":$PROTO,\"k\":\"end\",\"frames\":$frames,\"bytes\":$bytes,\"sha256\":${Json.str(sha256)},\"at\":$atMs}"

    // ---- sealing ----

    /** One piece, its payload as JSON text, ready to broadcast. */
    fun seal(key: ByteArray, uid: String, from: String, to: String, rid: String, n: Int,
             head: String, body: ByteArray = ByteArray(0),
             nonce: ByteArray = Crypt.randomBytes(Crypt.NONCE_BYTES)): String {
        val plain = head.toByteArray(Charsets.UTF_8) + byteArrayOf('\n'.code.toByte()) + body
        val s = Crypt.seal(key, plain, aad(uid, from, to, rid, n), nonce)
        val out = "{\"device\":${Json.str(from)},\"to\":${Json.str(to)},\"rid\":${Json.str(rid)}," +
            "\"n\":$n,\"s\":${Json.str(s)}}"
        if (out.length > PAYLOAD_MAX) throw Refused("a piece of ${out.length} bytes, over the broadcast cap")
        return out
    }

    private val UUID = Regex("[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
    private val RID = Regex("[0-9a-f]{32}")

    /** A broadcast's payload (a parsed object) opened under [key], or [Refused]. */
    fun open(key: ByteArray, uid: String, payload: Map<String, Any?>): Piece {
        val from = payload["device"] as? String ?: throw Refused("no sender")
        val to = payload["to"] as? String ?: throw Refused("no receiver")
        val rid = payload["rid"] as? String ?: throw Refused("no request")
        val n = (payload["n"] as? Long)?.toInt() ?: throw Refused("no piece number")
        val s = payload["s"] as? String ?: throw Refused("nothing sealed")
        if (!UUID.matches(from) || !(to == EVERY_PC || UUID.matches(to)) || !RID.matches(rid) ||
            n !in 0..MAX_FRAMES) throw Refused("not a piece")
        val plain = try {
            Crypt.open(key, s, aad(uid, from, to, rid, n))
        } catch (e: Crypt.Refused) {
            throw Refused("the seal does not open")
        }
        val cut = plain.indexOf('\n'.code.toByte())
        if (cut < 0) throw Refused("no head")
        @Suppress("UNCHECKED_CAST")
        val head = try {
            JsonIn.parse(String(plain, 0, cut, Charsets.UTF_8)) as? Map<String, Any?>
        } catch (e: JsonIn.Bad) {
            null
        } ?: throw Refused("a head that is not JSON")
        if (head["v"] != PROTO.toLong() || head["k"] !is String) throw Refused("not a head this phone reads")
        return Piece(from, to, rid, n, head, plain.copyOfRange(cut + 1, plain.size))
    }

    /**
     * Every piece of one recording, in order: the audio cut at [FRAME_BYTES], then the
     * end, which names how many came, how many bytes and their SHA-256, and this phone's
     * clock ([atMs]), which the PC holds to a wide window.
     */
    fun recording(key: ByteArray, uid: String, from: String, to: String, rid: String,
                  wav: ByteArray, atMs: Long): List<String> {
        val frames = (wav.size + FRAME_BYTES - 1) / FRAME_BYTES
        if (frames == 0 || frames >= MAX_FRAMES) throw Refused("a recording of $frames pieces")
        val out = ArrayList<String>(frames + 1)
        for (i in 0 until frames) {
            val chunk = wav.copyOfRange(i * FRAME_BYTES, minOf(wav.size, (i + 1) * FRAME_BYTES))
            out.add(seal(key, uid, from, to, rid, i, audioHead(), chunk))
        }
        out.add(seal(key, uid, from, to, rid, frames, endHead(frames, wav.size, sha256Hex(wav), atMs)))
        return out
    }

    // ---- Phoenix, Supabase Realtime's own protocol ----

    fun topic(uid: String) = "realtime:user:$uid"

    /** The join: the account's private topic, its own broadcasts not echoed, each acknowledged. */
    fun join(uid: String, token: String, ref: String) =
        "{\"topic\":${Json.str(topic(uid))},\"event\":\"phx_join\",\"payload\":{\"config\":" +
            "{\"broadcast\":{\"self\":false,\"ack\":true},\"presence\":{\"key\":\"\"}," +
            "\"postgres_changes\":[],\"private\":true},\"access_token\":${Json.str(token)}}," +
            "\"ref\":${Json.str(ref)},\"join_ref\":${Json.str(ref)}}"

    fun broadcast(uid: String, payloadJson: String, ref: String, joinRef: String) =
        "{\"topic\":${Json.str(topic(uid))},\"event\":\"broadcast\",\"payload\":{\"type\":\"broadcast\"," +
            "\"event\":\"link\",\"payload\":$payloadJson},\"ref\":${Json.str(ref)}," +
            "\"join_ref\":${Json.str(joinRef)}}"

    fun heartbeat(ref: String) =
        "{\"topic\":\"phoenix\",\"event\":\"heartbeat\",\"payload\":{},\"ref\":${Json.str(ref)}}"

    /** What one message off the socket is. */
    sealed class Heard {
        /** A reply to one of ours, by its ref: ok or not. */
        class Reply(val ref: String, val ok: Boolean, val why: String) : Heard()
        /** A `link` broadcast's payload. */
        class Link(val payload: Map<String, Any?>) : Heard()
        /** The channel itself went: an error, a close, the token's hour. */
        class Gone(val why: String) : Heard()
        object Other : Heard()
    }

    @Suppress("UNCHECKED_CAST")
    fun heard(text: String): Heard {
        val m = try {
            JsonIn.parse(text) as? Map<String, Any?>
        } catch (e: JsonIn.Bad) {
            null
        } ?: return Heard.Other
        val payload = m["payload"] as? Map<String, Any?> ?: emptyMap()
        return when (m["event"]) {
            "phx_reply" -> {
                val status = payload["status"] as? String ?: ""
                val response = payload["response"]
                Heard.Reply(m["ref"] as? String ?: "", status == "ok",
                            if (status == "ok") "" else (JsonIn.firstText(response) ?: status).take(160))
            }
            "broadcast" -> {
                if (payload["event"] == "link") {
                    val inner = payload["payload"] as? Map<String, Any?>
                    if (inner != null) Heard.Link(inner) else Heard.Other
                } else Heard.Other
            }
            "phx_error", "phx_close" -> Heard.Gone(m["event"] as String)
            "system" -> if (payload["status"] == "error")
                Heard.Gone((payload["message"] as? String ?: "system error").take(160)) else Heard.Other
            else -> Heard.Other
        }
    }

    /** /transcribe's answer, as the PC's `text` piece carries it: (status, body). */
    @Suppress("UNCHECKED_CAST")
    fun answer(p: Piece): Pair<Int, Map<String, Any?>> {
        val status = (p.head["status"] as? Long)?.toInt() ?: 0
        val body = p.head["body"] as? Map<String, Any?> ?: emptyMap()
        return Pair(status, body)
    }
}

/**
 * A JSON reader small enough to read here, for a module the JVM checks load (org.json
 * is Android's). Objects are maps, arrays lists, numbers Long or Double, and every
 * string is unescaped as JSON says. Anything else is [Bad].
 */
object JsonIn {
    class Bad(why: String) : Exception(why)

    fun parse(text: String): Any? {
        val r = Reader(text)
        val v = r.value()
        r.space()
        if (r.i != text.length) throw Bad("text after the value")
        return v
    }

    /** The first string anywhere in [v], for an error's words. */
    fun firstText(v: Any?): String? = when (v) {
        is String -> v
        is Map<*, *> -> v.values.firstNotNullOfOrNull { firstText(it) }
        is List<*> -> v.firstNotNullOfOrNull { firstText(it) }
        else -> null
    }

    private class Reader(val s: String) {
        var i = 0
        var depth = 0

        fun space() {
            while (i < s.length && s[i] in " \t\r\n") i++
        }

        fun value(): Any? {
            space()
            if (i >= s.length) throw Bad("the text ended")
            return when (s[i]) {
                '{' -> obj()
                '[' -> arr()
                '"' -> str()
                't' -> word("true", true)
                'f' -> word("false", false)
                'n' -> word("null", null)
                else -> num()
            }
        }

        private fun word(w: String, v: Any?): Any? {
            if (!s.startsWith(w, i)) throw Bad("not a value")
            i += w.length
            return v
        }

        private fun obj(): Map<String, Any?> {
            if (++depth > 32) throw Bad("too deep")
            i++
            val out = LinkedHashMap<String, Any?>()
            space()
            if (i < s.length && s[i] == '}') { i++; depth--; return out }
            while (true) {
                space()
                if (i >= s.length || s[i] != '"') throw Bad("a key that is not a string")
                val k = str()
                space()
                if (i >= s.length || s[i] != ':') throw Bad("no colon")
                i++
                out[k] = value()
                space()
                if (i >= s.length) throw Bad("the object did not end")
                if (s[i] == ',') { i++; continue }
                if (s[i] == '}') { i++; depth--; return out }
                throw Bad("not a comma")
            }
        }

        private fun arr(): List<Any?> {
            if (++depth > 32) throw Bad("too deep")
            i++
            val out = ArrayList<Any?>()
            space()
            if (i < s.length && s[i] == ']') { i++; depth--; return out }
            while (true) {
                out.add(value())
                space()
                if (i >= s.length) throw Bad("the array did not end")
                if (s[i] == ',') { i++; continue }
                if (s[i] == ']') { i++; depth--; return out }
                throw Bad("not a comma")
            }
        }

        private fun str(): String {
            i++
            val b = StringBuilder()
            while (true) {
                if (i >= s.length) throw Bad("the string did not end")
                val c = s[i++]
                when {
                    c == '"' -> return b.toString()
                    c == '\\' -> {
                        if (i >= s.length) throw Bad("an escape at the end")
                        when (val e = s[i++]) {
                            '"' -> b.append('"'); '\\' -> b.append('\\'); '/' -> b.append('/')
                            'b' -> b.append('\b'); 'f' -> b.append('\u000c'); 'n' -> b.append('\n')
                            'r' -> b.append('\r'); 't' -> b.append('\t')
                            'u' -> {
                                if (i + 4 > s.length) throw Bad("a short \\u")
                                b.append(s.substring(i, i + 4).toIntOrNull(16)?.toChar() ?: throw Bad("a bad \\u"))
                                i += 4
                            }
                            else -> throw Bad("an escape JSON has not got: \\$e")
                        }
                    }
                    c.code < 0x20 -> throw Bad("a control character in a string")
                    else -> b.append(c)
                }
            }
        }

        private fun num(): Any {
            val start = i
            if (i < s.length && s[i] == '-') i++
            while (i < s.length && (s[i].isDigit() || s[i] in ".eE+-")) i++
            val t = s.substring(start, i)
            if (t.isEmpty() || t == "-") throw Bad("not a value")
            return t.toLongOrNull() ?: t.toDoubleOrNull() ?: throw Bad("not a number")
        }
    }
}
