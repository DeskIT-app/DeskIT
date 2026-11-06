package io.github.deskit_app.deskit

import java.math.BigInteger
import java.security.KeyFactory
import java.security.KeyPair
import java.security.PrivateKey
import java.security.interfaces.ECPublicKey
import java.security.spec.ECPoint
import java.security.spec.ECPrivateKeySpec
import java.security.spec.ECPublicKeySpec
import java.util.Base64
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

fun main() {
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
