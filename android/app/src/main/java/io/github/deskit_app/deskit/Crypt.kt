package io.github.deskit_app.deskit

import java.math.BigInteger
import java.nio.ByteBuffer
import java.security.GeneralSecurityException
import java.security.KeyFactory
import java.security.KeyPair
import java.security.KeyPairGenerator
import java.security.MessageDigest
import java.security.PrivateKey
import java.security.SecureRandom
import java.security.interfaces.ECPublicKey
import java.security.spec.ECGenParameterSpec
import java.security.spec.ECParameterSpec
import java.security.spec.ECPoint
import java.security.spec.ECPublicKeySpec
import java.security.spec.PKCS8EncodedKeySpec
import java.util.Base64
import javax.crypto.Cipher
import javax.crypto.KeyAgreement
import javax.crypto.Mac
import javax.crypto.spec.GCMParameterSpec
import javax.crypto.spec.SecretKeySpec

/**
 * The account lock's formats, in Kotlin with no library: vault.py is the
 * truth and this is its other hand. Nothing here touches Android, so the
 * JVM can hold all of it against vectors the real vault.py wrote
 * (app/src/test, `gradle jvmChecks`), and java.util.Base64 is used and not
 * android.util.Base64 for that reason: it is there from API 26, which is
 * minSdk.
 *
 *   v1.<b64>  a sealed value: nonce ‖ ciphertext ‖ tag, AES-256-GCM
 *   p1.<b64>  a public key: the P-256 point, X ‖ Y
 *   w1.<b64>  a key wrapped to a public key: the ephemeral point ‖ a sealed value
 *
 * Standard base64 with padding, never url-safe: migration 0004's
 * is_sealed() is that shape, and it is why no sealed value can spell a
 * provider's key by accident.
 *
 * THE TRAP (M14, 2026-11-06). The PC's ECDH secret comes out of CNG's
 * TRUNCATE in the opposite byte order to Android's KeyAgreement, so every
 * hand-over failed with AEADBadTagException while the code on both screens
 * matched. The PC stays as it is, every PC depends on it, so [shared]
 * reverses the 32 bytes here. WebCrypto will need the same.
 */
object Crypt {
    const val KEY_BYTES = 32
    const val NONCE_BYTES = 12
    const val TAG_BYTES = 16
    const val POINT_BYTES = 64

    /** The longest sealed value the server takes (migration 0005). */
    const val SEALED_MAX = 7603

    /** vault.PLAIN_MAX: the most plain bytes that seal within [SEALED_MAX]. */
    const val PLAIN_MAX = (SEALED_MAX - 3) / 4 * 3 - NONCE_BYTES - TAG_BYTES

    /** 2^17: 50 ms on a good PC, seconds on a slow phone. Always on a thread. */
    const val CODE_ROUNDS = 1 shl 17

    /** The first eight characters of the code: `pairings.code`, a hint nobody compares. */
    const val HINT_CHARS = 8

    /** Crockford's alphabet without I, L, O and U: vault.ALPHABET. */
    private const val ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
    private const val CODE_TAG = "deskit pairing code v2"
    private const val WRAP_INFO = "deskit pairing v1"
    private const val LOCK_TAG = "deskit lock id\u0000"
    private const val CODE_BITS = 50

    /** vault.VaultError: something sealed that does not open or parse. */
    class Refused(why: String) : Exception(why)

    private val random = SecureRandom()

    fun randomBytes(n: Int): ByteArray = ByteArray(n).also { random.nextBytes(it) }

    private fun utf8(s: String): ByteArray = s.toByteArray(Charsets.UTF_8)

    /** No formatter in the way: this goes on the wire, whatever language the phone speaks. */
    fun hex(raw: ByteArray): String {
        val digits = "0123456789abcdef"
        val out = StringBuilder(raw.size * 2)
        for (b in raw) {
            out.append(digits[(b.toInt() shr 4) and 15]).append(digits[b.toInt() and 15])
        }
        return out.toString()
    }

    fun sha256(raw: ByteArray): ByteArray = MessageDigest.getInstance("SHA-256").digest(raw)

    fun b64(raw: ByteArray): String = Base64.getEncoder().encodeToString(raw)

    /** The bytes after `prefix.`, or [Refused]. */
    fun unb64(prefix: String, text: String): ByteArray {
        if (!text.startsWith("$prefix.")) throw Refused("not a $prefix value")
        return try {
            Base64.getDecoder().decode(text.substring(prefix.length + 1))
        } catch (e: IllegalArgumentException) {
            throw Refused("a malformed $prefix value")
        }
    }

    // ---- the row's identity: one line per table, as in vault.py ----

    fun aadVault(uid: String, name: String) = "vault/$uid/$name"
    fun aadPairing(uid: String, pairingId: String) = "pairing/$uid/$pairingId"
    fun aadDevice(uid: String, deviceId: String) = "device/$uid/$deviceId"

    // ---- sealing ----

    /** vault.is_sealed: the shape the migration admits. */
    fun isSealed(text: String): Boolean =
        text.length <= SEALED_MAX && Regex("[a-z]\\d\\.[A-Za-z0-9+/]{16,}={0,2}").matches(text)

    /** `v1.` + base64(nonce ‖ ciphertext ‖ tag). */
    fun seal(key: ByteArray, data: ByteArray, aad: String,
             nonce: ByteArray = randomBytes(NONCE_BYTES)): String {
        val c = Cipher.getInstance("AES/GCM/NoPadding")
        c.init(Cipher.ENCRYPT_MODE, SecretKeySpec(key, "AES"), GCMParameterSpec(TAG_BYTES * 8, nonce))
        c.updateAAD(utf8(aad))
        return "v1." + b64(nonce + c.doFinal(data))
    }

    fun open(key: ByteArray, sealed: String, aad: String): ByteArray {
        val raw = unb64("v1", sealed)
        if (raw.size < NONCE_BYTES + TAG_BYTES) throw Refused("a sealed value too short to be one")
        return try {
            val c = Cipher.getInstance("AES/GCM/NoPadding")
            c.init(Cipher.DECRYPT_MODE, SecretKeySpec(key, "AES"),
                   GCMParameterSpec(TAG_BYTES * 8, raw, 0, NONCE_BYTES))
            c.updateAAD(utf8(aad))
            c.doFinal(raw, NONCE_BYTES, raw.size - NONCE_BYTES)
        } catch (e: GeneralSecurityException) {
            throw Refused("the sealed value does not open with this key")
        }
    }

    /** seal_json: the caller's JSON text, as vault.seal_json seals its own. */
    fun sealText(key: ByteArray, json: String, aad: String): String = seal(key, utf8(json), aad)

    fun openText(key: ByteArray, sealed: String, aad: String): String =
        String(open(key, sealed, aad), Charsets.UTF_8)

    /** vault.fingerprint: what `profiles.lock_id` holds. Names a key, opens nothing. */
    fun fingerprint(key: ByteArray): String =
        hex(sha256(utf8(LOCK_TAG) + key)).substring(0, 16)

    // ---- the code on both screens ----

    /** PBKDF2-HMAC-SHA256, one block, by hand: PBEKeySpec takes characters and this is binary. */
    fun pbkdf2(material: ByteArray, salt: ByteArray, rounds: Int): ByteArray {
        val mac = Mac.getInstance("HmacSHA256")
        mac.init(SecretKeySpec(material, "HmacSHA256"))
        mac.update(salt)
        mac.update(byteArrayOf(0, 0, 0, 1))
        val u = mac.doFinal()
        val t = u.clone()
        for (round in 2..rounds) {
            mac.update(u)
            mac.doFinal(u, 0)
            for (i in t.indices) t[i] = (t[i].toInt() xor u[i].toInt()).toByte()
        }
        return t
    }

    /**
     * vault.pairing_code as PHONE_LINK_PLAN §12 gives it: the account, the
     * request, the asking device's point and the lock. The asking device
     * passes the `lock_id` it read, the approver the fingerprint of the key
     * it holds, never the server's column. So if the server lied to either
     * side the two screens differ and nobody presses Approve.
     */
    fun pairingCode(uid: String, pairingId: String, point: ByteArray, lockId: String): String {
        if (point.size != POINT_BYTES) throw Refused("the applicant's public key has the wrong length")
        val tag = utf8(CODE_TAG)
        val zero = byteArrayOf(0)
        val material = tag + zero + utf8(uid) + zero + utf8(pairingId) + zero + point + zero + utf8(lockId)
        val digest = pbkdf2(material, tag, CODE_ROUNDS)
        val bits = ByteBuffer.wrap(digest, 0, 8).long ushr (64 - CODE_BITS)
        val flat = StringBuilder(10)
        for (i in 0 until 10) flat.append(ALPHABET[((bits ushr (5 * (9 - i))) and 31).toInt()])
        return flat.substring(0, 5) + "-" + flat.substring(5)
    }

    /** vault.code_hint: the code flat, cut to the column's eight characters. */
    fun codeHint(code: String): String =
        code.uppercase().filter { it in '0'..'9' || it in 'A'..'Z' }.take(HINT_CHARS)

    // ---- the hand-off ----

    private fun fixed(v: BigInteger): ByteArray {
        val raw = v.toByteArray()
        val out = ByteArray(POINT_BYTES / 2)
        val n = minOf(raw.size, out.size)
        System.arraycopy(raw, raw.size - n, out, out.size - n, n)
        return out
    }

    fun newPair(): KeyPair = KeyPairGenerator.getInstance("EC")
        .apply { initialize(ECGenParameterSpec("secp256r1")) }
        .generateKeyPair()

    /** The curve, taken from a key: what the probe proved works with no library. */
    val p256: ECParameterSpec by lazy { (newPair().public as ECPublicKey).params }

    fun pointOf(key: ECPublicKey): ByteArray = fixed(key.w.affineX) + fixed(key.w.affineY)

    fun publicText(point: ByteArray): String = "p1." + b64(point)

    fun pointFrom(public: String): ByteArray {
        val point = unb64("p1", public)
        if (point.size != POINT_BYTES) throw Refused("the applicant's public key has the wrong length")
        return point
    }

    private fun publicKey(point: ByteArray): ECPublicKey = try {
        val x = BigInteger(1, point.copyOfRange(0, POINT_BYTES / 2))
        val y = BigInteger(1, point.copyOfRange(POINT_BYTES / 2, POINT_BYTES))
        KeyFactory.getInstance("EC")
            .generatePublic(ECPublicKeySpec(ECPoint(x, y), p256)) as ECPublicKey
    } catch (e: GeneralSecurityException) {
        throw Refused("a public key that is not on the curve")
    } catch (e: RuntimeException) {
        throw Refused("a public key that is not on the curve")     // Conscrypt's way of saying it
    }

    /** The shared secret in the PC's byte order. See THE TRAP above. */
    fun shared(mine: PrivateKey, peer: ByteArray): ByteArray = try {
        val ka = KeyAgreement.getInstance("ECDH")
        ka.init(mine)
        ka.doPhase(publicKey(peer), true)
        ka.generateSecret().reversedArray()
    } catch (e: GeneralSecurityException) {
        throw Refused("the agreement failed")
    } catch (e: IllegalStateException) {
        throw Refused("the agreement failed")
    }

    /** The private half back from its PKCS#8 bytes (the sealed request). */
    fun privateFrom(pkcs8: ByteArray): PrivateKey =
        KeyFactory.getInstance("EC").generatePrivate(PKCS8EncodedKeySpec(pkcs8))

    private fun hmac(key: ByteArray, data: ByteArray): ByteArray {
        val m = Mac.getInstance("HmacSHA256")
        m.init(SecretKeySpec(key, "HmacSHA256"))
        return m.doFinal(data)
    }

    /** vault._hkdf for its one length: HKDF-SHA256, empty salt, one block. */
    fun hkdf(secret: ByteArray, info: ByteArray): ByteArray =
        hmac(hmac(ByteArray(32), secret), info + byteArrayOf(1))

    /** vault.take: the account key out of what was handed over. */
    fun take(mine: PrivateKey, myPoint: ByteArray, handed: String, aad: String): ByteArray {
        val raw = unb64("w1", handed)
        if (raw.size < POINT_BYTES + NONCE_BYTES + TAG_BYTES) {
            throw Refused("a handed key too short to be one")
        }
        val eph = raw.copyOfRange(0, POINT_BYTES)
        val sealed = "v1." + b64(raw.copyOfRange(POINT_BYTES, raw.size))
        val wrap = hkdf(shared(mine, eph), utf8(WRAP_INFO) + eph + myPoint)
        val key = open(wrap, sealed, aad)
        wrap.fill(0)
        if (key.size != KEY_BYTES) throw Refused("what was handed over is not a key")
        return key
    }

    /** vault.hand_over: the account key wrapped to the applicant's point. */
    fun handOver(accountKey: ByteArray, applicant: ByteArray, aad: String,
                 eph: KeyPair = newPair(),
                 nonce: ByteArray = randomBytes(NONCE_BYTES)): String {
        val ephPoint = pointOf(eph.public as ECPublicKey)
        val wrap = hkdf(shared(eph.private, applicant), utf8(WRAP_INFO) + ephPoint + applicant)
        val sealed = seal(wrap, accountKey, aad, nonce)
        wrap.fill(0)
        return "w1." + b64(ephPoint + unb64("v1", sealed))
    }

    // ---- the sign-in ----

    private fun urlSafe(raw: ByteArray): String =
        Base64.getUrlEncoder().withoutPadding().encodeToString(raw)

    /** sb._pkce's verifier: 48 random bytes, 64 characters. */
    fun pkceVerifier(): String = urlSafe(randomBytes(48))

    fun pkceChallenge(verifier: String): String = urlSafe(sha256(verifier.toByteArray(Charsets.US_ASCII)))
}
