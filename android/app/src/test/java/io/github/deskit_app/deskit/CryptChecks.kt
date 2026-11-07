package io.github.deskit_app.deskit

import java.io.ByteArrayInputStream
import java.io.File
import java.math.BigInteger
import java.nio.file.Files
import java.security.KeyFactory
import java.security.KeyPair
import java.security.PrivateKey
import java.security.cert.CertificateException
import java.security.cert.CertificateFactory
import java.security.cert.X509Certificate
import java.security.interfaces.ECPublicKey
import java.security.spec.ECPoint
import java.security.spec.ECPrivateKeySpec
import java.security.spec.ECPublicKeySpec
import java.util.Base64
import java.util.Locale
import kotlin.system.exitProcess

/**
 * Crypt.kt against what the real vault.py wrote. A plain main, run with
 * `gradle jvmChecks --offline` from android/: there is no JUnit in this
 * build's offline cache and the app has no dependencies. Exit code 1 on any
 * failure, and every check says its name.
 *
 * The block below is dev/android/make_vectors.py's output, pasted: CNG's own
 * keys and CNG's own hand-over, written on this PC on 2026-11-06. All of it
 * is throwaway. The two codes are PHONE_LINK_PLAN §12's own worked examples.
 */
private object Vectors {
    const val UID = "11111111-2222-3333-4444-555555555555"
    const val PAIRING = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"

    const val PHONE_D = "8e97148d1da00c362ce2bbc1cf028e406e4006ff970169b5ce63b8b5b3f2eb42"
    const val PHONE_POINT = "kRmk1/7wJQZyMYEBmOqnD9DYOdeaeowECJtuGSyFnPrNIbinz4nQ0JlpFteoJ1ClLf7c1N70/Yd6pW0vNoGiLA=="
    const val HANDED_BY_PC = "w1.1b9w6Gy22kfr17pA8e/1KI5naCPCAh3vQo/kWLZ4Fz+C8bLEIF6AcKb06M5oq9UFCopOsWNWKxDlsEsFEMu80qn6BsCafv5HhZh7N7Oy6hNyrJtYLFx9qf1Xo0xmKmuEe+tXr4EJoTFQ9+S2neP8bR+HTFuuqIu+krrRoQ=="
    const val PC_POINT = "D/fZuBAjSOTHQYhFPD6S9XfI5r2nokMUEVdRrTYe08fdxJiIAsZU3xb1X40BEyxdId83r7OBWrOy87Rwgf1y4g=="
    const val EPH_D = "3d161b416fa8882b6d6fa981d51921d089517e393357d85f8bc8cdceb96e9b9f"
    const val EPH_POINT = "E5ReoMQQx+Vp/dB2Z3WCUqvO9PXPC7nWhcDJA467gdoRf2KTPJ0erpbcLAGq3No/CExc6nBW6THf6j/aRLOYRg=="
    const val HANDED_TO_PC = "w1.E5ReoMQQx+Vp/dB2Z3WCUqvO9PXPC7nWhcDJA467gdoRf2KTPJ0erpbcLAGq3No/CExc6nBW6THf6j/aRLOYRmRlZmdoaWprbG1ubw2erlcISHCx8e2WNp1d5ZN0iJ2uwZYpdpLNptjtMkgTdUZb7O7F9XLnRKTK8olxuw=="
    const val ROW = "v1.MjM0NTY3ODk6Ozw9vXmZ4v8e5pAGWITpL7KepxTWeu3WJsKS82dc5UhgzapXcbEU35hsX26f"
    const val LOCK_ID = "1c1fc90f8cfc1041"
}

private var passed = 0
private var failed = 0

private fun check(name: String, ok: Boolean) {
    if (ok) passed++ else failed++
    println((if (ok) "ok    " else "FAIL  ") + name)
}

private fun refuses(name: String, what: () -> Unit) {
    val refused = try {
        what()
        false
    } catch (e: Crypt.Refused) {
        true
    }
    check(name, refused)
}

private fun bytes(b64: String): ByteArray = Base64.getDecoder().decode(b64)

private fun privateKey(d: String): PrivateKey =
    KeyFactory.getInstance("EC").generatePrivate(ECPrivateKeySpec(BigInteger(d, 16), Crypt.p256))

private fun publicKey(point: ByteArray): ECPublicKey =
    KeyFactory.getInstance("EC").generatePublic(ECPublicKeySpec(
        ECPoint(BigInteger(1, point.copyOfRange(0, 32)), BigInteger(1, point.copyOfRange(32, 64))),
        Crypt.p256)) as ECPublicKey

private fun x509(der: ByteArray) =
    CertificateFactory.getInstance("X.509").generateCertificate(ByteArrayInputStream(der))
        as X509Certificate

private fun throws(name: String, what: () -> Unit) {
    val threw = try {
        what()
        false
    } catch (e: CertificateException) {
        true
    }
    check(name, threw)
}

/** The hand-written certificate, the pin, and whether TLS really turns on them. */
private fun pinChecks() {
    val phone = Crypt.newPair()
    val pc = Crypt.newPair()
    val der = Cert.selfSigned(phone)
    val phoneCert = x509(der)
    val pcCert = x509(Cert.selfSigned(pc))
    val stranger = x509(Cert.selfSigned(Crypt.newPair()))
    check("a hand-written certificate parses as X.509 v3", phoneCert.version == 3)
    phoneCert.verify(phone.public)
    check("and carries its own good signature", true)
    check("subject and issuer are one name, and random",
          phoneCert.subjectX500Principal == phoneCert.issuerX500Principal &&
              phoneCert.subjectX500Principal != pcCert.subjectX500Principal)
    check("it runs to 2049, like a PC's", phoneCert.notAfter.time > 2_500_000_000_000L)
    check("a pin is the SHA-256 of the DER, in hex, as a row writes it",
          Pin.of(der) == Crypt.hex(Crypt.sha256(der)) && Pin.of(der).length == 64)
    check("a pin in capitals is the same pin", Pin.matches(Pin.of(der).uppercase(), der))

    val trust = Pin.Trust(Pin.of(der))
    trust.checkServerTrusted(arrayOf(phoneCert), "ECDHE_ECDSA")
    check("the one leaf passes", true)
    throws("any other leaf throws") { trust.checkServerTrusted(arrayOf(stranger), "ECDHE_ECDSA") }
    throws("the leaf with another behind it throws") {
        trust.checkServerTrusted(arrayOf(phoneCert, stranger), "ECDHE_ECDSA")
    }
    throws("the other leaf with this one behind it throws") {
        trust.checkServerTrusted(arrayOf(stranger, phoneCert), "ECDHE_ECDSA")
    }
    throws("no chain throws") { trust.checkServerTrusted(emptyArray(), "ECDHE_ECDSA") }
    throws("null throws") { trust.checkServerTrusted(null, "ECDHE_ECDSA") }
    check("it vouches for no issuer", trust.acceptedIssuers.isEmpty())

    fun client(pin: String, cert: X509Certificate = phoneCert, key: PrivateKey = phone.private) =
        Pin.context(Pin.Trust(pin), Pin.OneKey(arrayOf(cert), key))
    fun door(wants: String, cert: X509Certificate = pcCert, key: PrivateKey = pc.private) =
        Pin.context(Pin.Trust(wants), Pin.OneKey(arrayOf(cert), key))
    val pcPin = Pin.of(pcCert.encoded)
    val phonePin = Pin.of(der)

    val session = Pin.handshake(client(pcPin), door(phonePin))
    check("both pins right: TLS holds, in memory, with a client certificate", session != null)
    check("the verifier finds the pin in the real session", Pin.Names(pcPin).verify("10.0.0.2", session))
    check("and refuses any other", !Pin.Names(phonePin).verify("10.0.0.2", session))
    check("no session is no", !Pin.Names(pcPin).verify("10.0.0.2", null))
    check("a door with another certificate is refused",
          Pin.handshake(client(pcPin), door(phonePin, stranger,
                                            Crypt.newPair().private)) == null)
    check("a door that shows the right certificate and cannot prove it is refused",
          Pin.handshake(client(pcPin), door(phonePin, pcCert, Crypt.newPair().private)) == null)
    check("a phone that is not on the door's list is refused",
          Pin.handshake(client(pcPin), door(Pin.of(stranger.encoded))) == null)
    check("a phone with another key under its certificate is refused",
          Pin.handshake(client(pcPin, phoneCert, Crypt.newPair().private), door(phonePin)) == null)
}

/** The spool's rules, on a real folder. */
private fun spoolChecks() {
    val dir: File = Files.createTempDirectory("spool").toFile()
    val day = 24 * 3600 * 1000L
    try {
        val small = SpoolFiles(dir, maxBytes = 3000, keepMs = 7 * day)
        val t = 1_700_000_000_000L
        val a = small.keep(ByteArray(1000), t)
        val b = small.keep(ByteArray(1000), t + 1)
        check("a kept recording is a whole file", a.file?.length() == 1000L && a.dropped == 0)
        check("and no temporary is left", dir.list()!!.none { it.endsWith(".tmp") })
        check("oldest first", small.items().map { it.name } == listOf(a.file!!.name, b.file!!.name))
        File(dir, "a.wav").writeBytes(ByteArray(0))
        check("a name that is not ours is never sent", small.items().size == 2)
        check("and is still a recording to Sign out", small.count() == 3)
        File(dir, "1-half.wav.tmp").writeBytes(ByteArray(10))
        check("half a write is not a recording", small.items().size == 2 && small.count() == 3)
        val c = small.keep(ByteArray(1000), t + 2)
        check("the first past the cap costs nothing yet", c.dropped == 0 && small.items().size == 3)
        check("and the half a write has gone", dir.list()!!.none { it.endsWith(".tmp") })
        val d = small.keep(ByteArray(1000), t + 3)
        check("past the cap the oldest goes first, and it says so",
              d.dropped == 1 && !a.file!!.exists() && b.file!!.exists() && small.items().size == 3)
        val e = small.keep(ByteArray(9000), t + 4)
        check("a recording bigger than the cap is never its own victim",
              e.file!!.exists() && small.items() == listOf(e.file))
        check("and took everything older", e.dropped == 3)
        val gone = SpoolFiles(dir, maxBytes = 1 shl 30, keepMs = 7 * day)
        check("a day short of the week it stays", gone.prune(t + 7 * day - 1) == 0)
        check("past the week it goes", gone.prune(t + 8 * day) == 1 && gone.items().isEmpty())
        check("a name that is not ours outlives it", File(dir, "a.wav").exists())
        val was = Locale.getDefault()
        try {
            Locale.setDefault(Locale.forLanguageTag("ar-EG-u-nu-arab"))
            val arabic = gone.keep(ByteArray(10), t + 9 * day)
            check("a phone set to Arabic digits writes a name the spool can read",
                  gone.items() == listOf(arabic.file))
        } finally {
            Locale.setDefault(was)
        }
    } finally {
        dir.deleteRecursively()
    }
}

fun main() {
    pinChecks()
    spoolChecks()
    val aad = Crypt.aadPairing(Vectors.UID, Vectors.PAIRING)
    val account = ByteArray(32) { it.toByte() }
    val rowAad = Crypt.aadVault(Vectors.UID, "groq")

    // the code: §12's two examples, the lock in the material
    val point41 = ByteArray(Crypt.POINT_BYTES) { 0x41 }
    val one = Crypt.pairingCode(Vectors.UID, Vectors.PAIRING, point41, "0123456789abcdef")
    val two = Crypt.pairingCode(Vectors.UID, Vectors.PAIRING, point41, "fedcba9876543210")
    check("§12's first example: WK0MS-7HN8C, got $one", one == "WK0MS-7HN8C")
    check("§12's second example: R85CJ-HRE9H, got $two", two == "R85CJ-HRE9H")
    check("the hint is the code's first eight, flat", Crypt.codeHint("WK0MS-7HN8C") == "WK0MS7HN")
    refuses("a point of the wrong length has no code") {
        Crypt.pairingCode(Vectors.UID, Vectors.PAIRING, ByteArray(63), "0123456789abcdef")
    }

    // the hand-over from a PC: THE TRAP, CNG's byte order
    val phone = privateKey(Vectors.PHONE_D)
    val phonePoint = bytes(Vectors.PHONE_POINT)
    val taken = Crypt.take(phone, phonePoint, Vectors.HANDED_BY_PC, aad)
    check("the key comes out of a hand-over the real vault.py wrote", taken.contentEquals(account))
    val raw = Crypt.unb64("w1", Vectors.HANDED_BY_PC)
    val eph = raw.copyOfRange(0, Crypt.POINT_BYTES)
    val sealed = "v1." + Crypt.b64(raw.copyOfRange(Crypt.POINT_BYTES, raw.size))
    val info = "deskit pairing v1".toByteArray() + eph + phonePoint
    val notReversed = Crypt.hkdf(Crypt.shared(phone, eph).reversedArray(), info)
    refuses("the secret as Android hands it does NOT open it: the reversal is the fix") {
        Crypt.open(notReversed, sealed, aad)
    }
    refuses("a hand-over for another request does not open") {
        Crypt.take(phone, phonePoint, Vectors.HANDED_BY_PC,
                   Crypt.aadPairing(Vectors.UID, "bbbbbbbb-bbbb-cccc-dddd-eeeeeeeeeeee"))
    }

    // the hand-over from this phone: byte for byte what vault.take opened
    val ephPair = KeyPair(publicKey(bytes(Vectors.EPH_POINT)), privateKey(Vectors.EPH_D))
    val nonce = ByteArray(Crypt.NONCE_BYTES) { (100 + it).toByte() }
    val mine = Crypt.handOver(account, bytes(Vectors.PC_POINT), aad, ephPair, nonce)
    check("a hand-over made here is byte for byte the one vault.take opened",
          mine == Vectors.HANDED_TO_PC)

    // a round trip through the sealed private half's own form
    val pair = Crypt.newPair()
    val point = Crypt.pointOf(pair.public as ECPublicKey)
    val back = Crypt.privateFrom(pair.private.encoded)
    val wrapped = Crypt.handOver(account, point, aad)
    check("the private half survives its sealed form",
          Crypt.take(back, point, wrapped, aad).contentEquals(account))
    check("every hand-over is a shape the server admits", Crypt.isSealed(wrapped))
    check("p1. is a shape the server admits", Crypt.isSealed(Crypt.publicText(point)))
    check("p1. reads back", Crypt.pointFrom(Crypt.publicText(point)).contentEquals(point))

    // a sealed row
    val plain = "{\"v\":\"gsk_not_a_real_key\"}"
    val rowNonce = ByteArray(Crypt.NONCE_BYTES) { (50 + it).toByte() }
    check("a row sealed here is byte for byte the real vault's",
          Crypt.seal(account, plain.toByteArray(), rowAad, rowNonce) == Vectors.ROW)
    check("the real vault's row opens here", Crypt.openText(account, Vectors.ROW, rowAad) == plain)
    refuses("a row under another name does not open") {
        Crypt.open(account, Vectors.ROW, Crypt.aadVault(Vectors.UID, "gemini"))
    }
    refuses("a row under another key does not open") {
        Crypt.open(ByteArray(32), Vectors.ROW, rowAad)
    }
    refuses("a value of another format does not open") {
        Crypt.open(account, "w1.AAAA", rowAad)
    }
    check("the fingerprint is the real vault's", Crypt.fingerprint(account) == Vectors.LOCK_ID)

    // what the migration admits
    check("a sealed value passes", Crypt.isSealed(Vectors.ROW))
    check("url-safe base64 does not", !Crypt.isSealed("v1.abc_defghijklmnopqrstuvwxyz"))
    check("a bare word does not", !Crypt.isSealed("hello"))
    check("past the cap does not", !Crypt.isSealed("v1." + "A".repeat(Crypt.SEALED_MAX)))

    // a point off the curve is an error and never a secret
    refuses("a point off the curve is refused") {
        Crypt.shared(phone, ByteArray(Crypt.POINT_BYTES) { 0x41 })
    }

    // RFC 7636, appendix B
    check("the PKCE challenge is RFC 7636's",
          Crypt.pkceChallenge("dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk") ==
              "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM")
    check("a verifier is the length the spec asks", Crypt.pkceVerifier().length == 64)

    println("$passed passed, $failed failed")
    if (failed > 0) exitProcess(1)
}
