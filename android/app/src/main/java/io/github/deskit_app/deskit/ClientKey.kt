package io.github.deskit_app.deskit

import android.content.Context
import android.os.Build
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Log
import java.io.IOException
import java.math.BigInteger
import java.security.GeneralSecurityException
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

    /** Keystore's refusals, as the one thing a caller has to handle. */
    private inline fun <T> asked(c: Context, what: () -> T): T = try {
        what()
    } catch (e: GeneralSecurityException) {
        throw Sealed.NotNow("the client key: ${e.javaClass.simpleName}", Sealed.locked(c), e)
    } catch (e: ProviderException) {
        throw Sealed.NotNow("the client key: ${e.javaClass.simpleName}", Sealed.locked(c), e)
    } catch (e: IOException) {
        throw Sealed.NotNow("the client key: ${e.javaClass.simpleName}", Sealed.locked(c), e)
    }

    /** This device's certificate, as DER, making the key the first time. */
    @Synchronized
    fun ensure(c: Context, deviceId: String): ByteArray = asked(c) {
        val a = alias(deviceId)
        keystore().getCertificate(a)?.encoded ?: run {
            made(c, a)
            (keystore().getCertificate(a) as X509Certificate).encoded
        }
    }

    /** The certificate if there is one; no key is made. */
    fun certificate(c: Context, deviceId: String): ByteArray? = asked(c) {
        keystore().getCertificate(alias(deviceId))?.encoded
    }

    /** The key, for the door's KeyManager (next lane). */
    fun privateKey(c: Context, deviceId: String): PrivateKey? = asked(c) {
        keystore().getKey(alias(deviceId), null) as? PrivateKey
    }

    /** Every client key on this phone: what leaving, or being forgotten, wipes. */
    @Synchronized
    fun wipe(c: Context) = asked(c) {
        val ks = keystore()
        for (a in ks.aliases().toList()) if (a.startsWith("deskit.client.")) ks.deleteEntry(a)
    }
}
