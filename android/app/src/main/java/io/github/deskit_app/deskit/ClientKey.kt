package io.github.deskit_app.deskit

import android.content.Context
import android.os.Build
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyInfo
import android.security.keystore.KeyProperties
import android.util.Log
import java.math.BigInteger
import java.security.GeneralSecurityException
import java.security.KeyFactory
import java.security.KeyPair
import java.security.KeyPairGenerator
import java.security.KeyStore
import java.security.PrivateKey
import java.security.ProviderException
import java.security.SecureRandom
import java.security.Signature
import java.security.cert.X509Certificate
import java.security.spec.ECGenParameterSpec
import java.util.UUID
import javax.security.auth.x500.X500Principal

/**
 * This phone's identity at the PC's door: an EC key in Android Keystore that
 * can sign and can never leave, and the self-signed certificate Keystore makes
 * for it. The PCs learn the certificate from the sealed `link` row, so nothing
 * here depends on anyone having signed it.
 *
 * DIGEST_NONE is what TLS needs: Conscrypt hashes and hands Keystore the
 * digest. DIGEST_SHA256 beside it is what gives the certificate a real
 * self-signature, as the probe of 2026-11-06 ran it; with NONE alone an older
 * phone writes a placeholder there.
 *
 * The subject is random, because Android's default is `CN=fake` for everyone
 * and OpenSSL takes the first anchor of a name: three phones with one subject
 * gave [ok, SSLError, refused] in the plan's measurement.
 *
 * setUnlockedDeviceRequired where the phone has it (API 28+, and a screen lock:
 * see Sealed.lockable): a stolen, locked phone cannot use the key. A Keystore
 * that will not make such a key, or makes it and will not use it, gets one
 * without the condition. A device with no Keystore at all has no road here:
 * the plan's answer, a software key sealed by [Sealed], is for the day a real
 * phone needs it.
 */
object ClientKey {
    private const val STORE = "AndroidKeyStore"
    private const val SIGNS = "NONEwithECDSA"

    private fun keystore() = KeyStore.getInstance(STORE).apply { load(null) }

    private fun alias(deviceId: String) = "deskit.client.$deviceId"

    private fun make(alias: String, unlockedOnly: Boolean): KeyPair {
        val spec = KeyGenParameterSpec.Builder(alias, KeyProperties.PURPOSE_SIGN)
            .setAlgorithmParameterSpec(ECGenParameterSpec("secp256r1"))
            .setDigests(KeyProperties.DIGEST_NONE, KeyProperties.DIGEST_SHA256)
            .setCertificateSubject(X500Principal("CN=${UUID.randomUUID()}"))
            .setCertificateSerialNumber(BigInteger(63, SecureRandom()))
        if (unlockedOnly && Build.VERSION.SDK_INT >= 28) spec.setUnlockedDeviceRequired(true)
        return KeyPairGenerator.getInstance(KeyProperties.KEY_ALGORITHM_EC, STORE)
            .apply { initialize(spec.build()) }
            .generateKeyPair()
    }

    private fun signs(key: PrivateKey): Boolean = try {
        Signature.getInstance(SIGNS).apply {
            initSign(key)
            update(ByteArray(32))
            sign()
        }
        true
    } catch (e: GeneralSecurityException) {
        false
    } catch (e: ProviderException) {
        false
    }

    /** The key and whether a locked phone cannot use it. See Sealed.lockable. */
    private fun made(c: Context, alias: String): Pair<KeyPair, Boolean> {
        if (Sealed.lockable(c)) {
            try {
                val strict = make(alias, unlockedOnly = true)
                if (signs(strict.private)) return Pair(strict, true)
            } catch (e: GeneralSecurityException) {
                Log.w("DeskIT", "no unlocked-only client key here: ${e.javaClass.simpleName}")
            } catch (e: ProviderException) {
                Log.w("DeskIT", "no unlocked-only client key here: ${e.javaClass.simpleName}")
            }
            keystore().deleteEntry(alias)
        }
        return Pair(make(alias, unlockedOnly = false), false)
    }

    /** This device's certificate, as DER, making the key the first time. */
    @Synchronized
    fun ensure(c: Context, deviceId: String): ByteArray {
        val a = alias(deviceId)
        keystore().getCertificate(a)?.let { return it.encoded }
        made(c, a)
        return (keystore().getCertificate(a) as X509Certificate).encoded
    }

    /** The certificate if there is one; no key is made. */
    fun certificate(deviceId: String): ByteArray? =
        keystore().getCertificate(alias(deviceId))?.encoded

    /** The key, for the door's KeyManager (next lane). */
    fun privateKey(deviceId: String): PrivateKey? =
        keystore().getKey(alias(deviceId), null) as? PrivateKey

    /** Every client key on this phone: what leaving, or being forgotten, wipes. */
    @Synchronized
    fun wipe() {
        val ks = keystore()
        for (a in ks.aliases().toList()) if (a.startsWith("deskit.client.")) ks.deleteEntry(a)
    }

    /**
     * One throwaway key, made, used and deleted: where it lives and how long
     * it took. For M16: "The S26's own Keystore is still the first thing to try".
     */
    fun probe(c: Context): String {
        val a = "deskit.probe"
        keystore().deleteEntry(a)
        val t0 = System.nanoTime()
        val (pair, strict) = made(c, a)
        val makeMs = (System.nanoTime() - t0) / 1_000_000
        val t1 = System.nanoTime()
        val signed = signs(pair.private)
        val signMs = (System.nanoTime() - t1) / 1_000_000
        val info = KeyFactory.getInstance(pair.private.algorithm, STORE)
            .getKeySpec(pair.private, KeyInfo::class.java)
        val where = if (Build.VERSION.SDK_INT >= 31) when (info.securityLevel) {
            KeyProperties.SECURITY_LEVEL_STRONGBOX -> "StrongBox"
            KeyProperties.SECURITY_LEVEL_TRUSTED_ENVIRONMENT -> "secure hardware"
            KeyProperties.SECURITY_LEVEL_SOFTWARE -> "software"
            else -> "level ${info.securityLevel}"
        } else {
            @Suppress("DEPRECATION")
            if (info.isInsideSecureHardware) "secure hardware" else "software"
        }
        keystore().deleteEntry(a)
        return "made in $makeMs ms, signs in $signMs ms, in $where, " +
            (if (strict) "unlocked only" else "NOT unlocked only") +
            (if (signed) "" else ", DID NOT SIGN")
    }
}
