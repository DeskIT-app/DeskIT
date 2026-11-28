package io.github.deskit_app.deskit

import java.net.Socket
import java.nio.ByteBuffer
import java.security.KeyPair
import java.security.MessageDigest
import java.security.Principal
import java.security.PrivateKey
import java.security.SecureRandom
import java.security.Signature
import java.security.cert.CertificateException
import java.security.cert.X509Certificate
import java.util.UUID
import javax.net.ssl.HostnameVerifier
import javax.net.ssl.SSLContext
import javax.net.ssl.SSLEngine
import javax.net.ssl.SSLEngineResult
import javax.net.ssl.SSLException
import javax.net.ssl.SSLPeerUnverifiedException
import javax.net.ssl.SSLSession
import javax.net.ssl.X509ExtendedKeyManager
import javax.net.ssl.X509KeyManager
import javax.net.ssl.X509TrustManager

/**
 * Who a phone will talk to at home, and how it proves who it is. Nothing here
 * touches Android, so the JVM holds all of it (`gradle jvmChecks`).
 *
 * Both ends are pinned, from sealed rows of the account (PHONE_LINK_PLAN.md
 * stage 1). A PC's row names the SHA-256 of its certificate's DER, and [Trust]
 * accepts that one leaf and throws on anything else: there is no CA here, and
 * no name, because a PC's certificate is random hex and a LAN address is
 * whatever the router gave it this week. Dates mean nothing either: a pin
 * compares a hash.
 *
 * [Names] checks the same pin again instead of returning true. A verifier that
 * returns true is what Google's scanner flags, and rightly: it is the one thing
 * standing between this connection and a session some other trust manager let
 * through.
 *
 * The failure happens before anything of ours leaves. The client's certificate
 * and every byte of a recording come after the server's certificate has been
 * checked, in TLS 1.2 and in 1.3, so a stranger at the address learns nothing.
 *
 * [handshake] runs TLS between two engines in this process, with no socket. It
 * is how a phone finds out whether its Keystore key can sign for TLS at all,
 * which no document promises, before it has anyone to fail in front of.
 */
object Pin {
    private const val ALIAS = "deskit"

    /** One hop of a handshake is a flight, and TLS 1.2 has few: this only stops a stuck pair. */
    private const val MOST_STEPS = 256

    /** How a `link` row and the forgotten list spell a certificate. */
    fun of(der: ByteArray): String = Crypt.hex(Crypt.sha256(der))

    /** Constant time: this is a comparison a stranger can feed. */
    fun matches(pin: String, der: ByteArray): Boolean =
        MessageDigest.isEqual(of(der).toByteArray(), pin.lowercase().toByteArray())

    /** Exactly one leaf, whichever side asks. */
    class Trust(private val pin: String) : X509TrustManager {
        private fun check(chain: Array<out X509Certificate>?) {
            val only = chain?.singleOrNull() ?: throw CertificateException("not one certificate")
            if (!matches(pin, only.encoded)) throw CertificateException("not the pinned certificate")
        }

        override fun checkServerTrusted(chain: Array<out X509Certificate>?, authType: String?) =
            check(chain)

        override fun checkClientTrusted(chain: Array<out X509Certificate>?, authType: String?) =
            check(chain)

        override fun getAcceptedIssuers(): Array<X509Certificate> = emptyArray()
    }

    /** The same pin, on what the session really holds. */
    class Names(private val pin: String) : HostnameVerifier {
        override fun verify(hostname: String?, session: SSLSession?): Boolean = try {
            val peers = session?.peerCertificates
            peers != null && peers.size == 1 && matches(pin, peers[0].encoded)
        } catch (e: SSLPeerUnverifiedException) {
            false
        }
    }

    /**
     * The one certificate this phone shows, and its key, which may well be a
     * Keystore key that can sign and can never leave. No page documents that with
     * HttpsURLConnection, and it was run: stage 1's probe.
     */
    class OneKey(private val chain: Array<X509Certificate>, private val key: PrivateKey) :
        X509ExtendedKeyManager() {
        override fun chooseClientAlias(types: Array<out String>?, issuers: Array<out Principal>?,
                                       socket: Socket?): String = ALIAS

        override fun chooseServerAlias(type: String?, issuers: Array<out Principal>?,
                                       socket: Socket?): String = ALIAS

        // An engine asks these, and the plain interface has no answer to them:
        // the JDK's wrapper for it says null, and a handshake with no certificate.
        override fun chooseEngineClientAlias(types: Array<out String>?,
                                             issuers: Array<out Principal>?,
                                             engine: SSLEngine?): String = ALIAS

        override fun chooseEngineServerAlias(type: String?, issuers: Array<out Principal>?,
                                             engine: SSLEngine?): String = ALIAS

        override fun getClientAliases(type: String?, issuers: Array<out Principal>?) = arrayOf(ALIAS)

        override fun getServerAliases(type: String?, issuers: Array<out Principal>?) = arrayOf(ALIAS)

        override fun getCertificateChain(alias: String?) = if (alias == ALIAS) chain else null

        override fun getPrivateKey(alias: String?) = if (alias == ALIAS) key else null
    }

    fun context(trust: X509TrustManager, key: X509KeyManager?): SSLContext =
        SSLContext.getInstance("TLS").apply {
            init(if (key == null) null else arrayOf(key), arrayOf(trust), null)
        }

    /**
     * TLS between [client] and [server] right here, a client certificate asked
     * for: the client's session when it held, null when anything refused. Every
     * signature a real door would ask of the client's key is asked of it here.
     */
    fun handshake(client: SSLContext, server: SSLContext): SSLSession? {
        val c = client.createSSLEngine().apply { useClientMode = true }
        val s = server.createSSLEngine().apply {
            useClientMode = false
            needClientAuth = true
        }
        val size = maxOf(c.session.packetBufferSize, s.session.packetBufferSize) * 2
        val room = maxOf(c.session.applicationBufferSize, s.session.applicationBufferSize) * 2
        val toServer = ByteBuffer.allocate(size)
        val toClient = ByteBuffer.allocate(size)
        val sink = ByteBuffer.allocate(room)
        return try {
            c.beginHandshake()
            s.beginHandshake()
            var steps = 0
            while (shaking(c) || shaking(s)) {
                if (steps++ > MOST_STEPS) return null
                step(c, toServer, toClient, sink)
                step(s, toClient, toServer, sink)
            }
            c.session.takeIf { it.isValid }
        } catch (e: SSLException) {
            null
        }
    }

    private fun shaking(e: SSLEngine): Boolean = e.handshakeStatus.let {
        it != SSLEngineResult.HandshakeStatus.NOT_HANDSHAKING &&
            it != SSLEngineResult.HandshakeStatus.FINISHED
    }

    private fun step(e: SSLEngine, out: ByteBuffer, into: ByteBuffer, sink: ByteBuffer) {
        when (e.handshakeStatus) {
            SSLEngineResult.HandshakeStatus.NEED_TASK ->
                generateSequence { e.delegatedTask }.forEach { it.run() }
            SSLEngineResult.HandshakeStatus.NEED_WRAP -> e.wrap(ByteBuffer.allocate(0), out)
            SSLEngineResult.HandshakeStatus.NOT_HANDSHAKING,
            SSLEngineResult.HandshakeStatus.FINISHED -> return
            else -> {
                into.flip()
                sink.clear()
                e.unwrap(into, sink)
                into.compact()
            }
        }
    }
}

/**
 * A self-signed certificate written by hand, for the day a phone's Keystore
 * will not sign for TLS and a software key has to take over: [ClientKey] has
 * the rule. Keystore makes a certificate for its own keys and nothing on
 * Android makes one for any other, short of a library, so this is the DER that
 * phone.py's make_pair writes for a PC: X.509 v3, P-256, ECDSA with SHA-256, and
 * a random subject, because OpenSSL takes the first anchor of a name.
 */
object Cert {
    private val CN = byteArrayOf(0x06, 0x03, 0x55, 0x04, 0x03)
    private val ECDSA_SHA256 = byteArrayOf(0x06, 0x08, 0x2a, 0x86.toByte(), 0x48, 0xce.toByte(),
                                           0x3d, 0x04, 0x03, 0x02)
    private const val NOT_BEFORE = "200101000000Z"
    private const val NOT_AFTER = "491231235959Z"
    private const val SERIAL_BYTES = 16

    private fun length(n: Int): ByteArray = when {
        n < 0x80 -> byteArrayOf(n.toByte())
        n < 0x100 -> byteArrayOf(0x81.toByte(), n.toByte())
        else -> byteArrayOf(0x82.toByte(), (n shr 8).toByte(), n.toByte())
    }

    private fun tlv(tag: Int, value: ByteArray) = byteArrayOf(tag.toByte()) + length(value.size) + value

    private fun seq(vararg parts: ByteArray) = tlv(0x30, parts.reduce { a, b -> a + b })

    private fun name(cn: String) = seq(tlv(0x31, seq(CN, tlv(0x0C, cn.toByteArray(Charsets.UTF_8)))))

    private fun serial(): ByteArray {
        val raw = ByteArray(SERIAL_BYTES).also { SecureRandom().nextBytes(it) }
        raw[0] = (raw[0].toInt() and 0x7f or 0x40).toByte()      // positive, and no leading zero
        return tlv(0x02, raw)
    }

    /** The DER of a certificate for [pair], signed by [pair]. */
    fun selfSigned(pair: KeyPair, cn: String = UUID.randomUUID().toString()): ByteArray {
        val tbs = seq(tlv(0xA0, tlv(0x02, byteArrayOf(2))),      // v3
                      serial(),
                      seq(ECDSA_SHA256),
                      name(cn),
                      seq(tlv(0x17, NOT_BEFORE.toByteArray()), tlv(0x17, NOT_AFTER.toByteArray())),
                      name(cn),
                      pair.public.encoded)
        val signature = Signature.getInstance("SHA256withECDSA").run {
            initSign(pair.private)
            update(tbs)
            sign()
        }
        return seq(tbs, seq(ECDSA_SHA256), tlv(0x03, byteArrayOf(0) + signature))
    }
}
