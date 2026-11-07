package io.github.deskit_app.deskit

import android.content.Context
import android.os.Build
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Log
import org.json.JSONException
import org.json.JSONObject
import java.io.ByteArrayInputStream
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
import java.security.cert.CertificateFactory
import java.security.cert.X509Certificate
import java.security.spec.ECGenParameterSpec
import java.util.Base64
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
 * without the condition, so it is never made on a phone that is locked: a locked
 * phone fails exactly that way, and it is told to come back ([Sealed.NotNow]).
 *
 * **What a phone did not have when the key was made, it gets by itself.** A
 * screen lock added later means a better key is possible, and one that signs at
 * every door until a person thinks of signing out is not the promise. [ensure]
 * runs at every look, so that is where it is made. Nothing else about this
 * phone changes, and it says nothing.
 *
 * **And a Keystore that cannot do TLS has a way out.** That Keystore signs is
 * proved on a real phone (M16). That Conscrypt will hand it a handshake is proved on
 * the emulator and nowhere else, and on a real phone, with its maker's own
 * Keystore and with no one to ask, a refusal would leave it joined and unable to
 * reach any PC. So the first thing asked of a key, here and with no network, is
 * a whole TLS handshake with it ([Pin.handshake]). One that fails, in a handshake
 * that a plain software key passes, gives way to that software key: made here,
 * sealed by [Sealed] (so a locked phone can no more use it than a Keystore key),
 * with a certificate written by hand ([Cert]). The private half is in memory
 * while a connection is made. It is the plan's fallback, and the only reason it
 * is here at all is that a person must never be left with nothing.
 *
 * **A new key has to reach the PCs first.** A door takes the certificate its row
 * names, so a new key stays [PENDING], and is not used, until the row carrying
 * it has landed: [published]. A phone offline at that moment goes on with the
 * key the PCs know. The last PC to hear of the new row drops this phone until it
 * does, and the spool holds what it says meanwhile.
 *
 * A device with no Keystore at all has no road here: the session itself is
 * sealed by one.
 */
object ClientKey {
    private const val STORE = "AndroidKeyStore"
    private const val SIGNS = "NONEwithECDSA"
    private const val FILE = "client_key"
    /** The slot of the software key, and the sealed file it is kept in. */
    private const val SOFT = "client_soft"
    private const val PREFIX = "deskit.client."
    private const val ACTIVE = "active."
    private const val PENDING = "pending."
    private const val STRICT = "strict."
    private const val PASSED = "passed."
    private const val NO_STRICT = "no_strict"

    private fun keystore() = KeyStore.getInstance(STORE).apply { load(null) }

    private fun sp(c: Context) = c.getSharedPreferences(FILE, Context.MODE_PRIVATE)

    private fun alias(deviceId: String) = PREFIX + deviceId

    private fun active(c: Context, id: String): String =
        sp(c).getString(ACTIVE + id, null) ?: alias(id)

    private fun pending(c: Context, id: String): String? = sp(c).getString(PENDING + id, null)

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

    /** The key, and whether a locked phone cannot use it, kept as a word. See Sealed.lockable. */
    private fun made(c: Context, alias: String) {
        if (Sealed.locked(c)) throw Sealed.NotNow("the phone is locked", locked = true)
        if (Sealed.lockable(c)) {
            try {
                val strict = make(alias, unlockedOnly = true)
                if (signs(strict.private)) {
                    sp(c).edit().putBoolean(STRICT + alias, true).commit()
                    return
                }
            } catch (e: GeneralSecurityException) {
                Log.w("DeskIT", "no unlocked-only client key here: ${e.javaClass.simpleName}")
            } catch (e: ProviderException) {
                Log.w("DeskIT", "no unlocked-only client key here: ${e.javaClass.simpleName}")
            }
            keystore().deleteEntry(alias)
            // It may have locked since the look above.
            if (Sealed.locked(c)) throw Sealed.NotNow("the phone is locked", locked = true)
            sp(c).edit().putBoolean(NO_STRICT, true).commit()
        }
        make(alias, unlockedOnly = false)
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

    private fun x509(der: ByteArray): X509Certificate =
        CertificateFactory.getInstance("X.509").generateCertificate(ByteArrayInputStream(der))
            as X509Certificate

    // ---- the software key ----

    private fun soft(c: Context): Pair<ByteArray, PrivateKey>? {
        val text = Sealed.getText(c, SOFT) ?: return null
        return try {
            val o = JSONObject(text)
            val decode = Base64.getDecoder()
            val pkcs8 = decode.decode(o.getString("key"))
            val key = Crypt.privateFrom(pkcs8)
            pkcs8.fill(0)
            Pair(decode.decode(o.getString("cert")), key)
        } catch (e: JSONException) {
            null
        } catch (e: IllegalArgumentException) {
            null
        }
    }

    private fun makeSoft(c: Context) {
        val pair = Crypt.newPair()
        val pkcs8 = pair.private.encoded
        Sealed.putText(c, SOFT, JSONObject().put("key", Crypt.b64(pkcs8))
            .put("cert", Crypt.b64(Cert.selfSigned(pair))).toString())
        pkcs8.fill(0)
    }

    private fun der(c: Context, slot: String): ByteArray? =
        if (slot == SOFT) soft(c)?.first else keystore().getCertificate(slot)?.encoded

    // ---- can it do TLS ----

    private fun handshakes(cert: X509Certificate, key: PrivateKey): Boolean {
        val side = Crypt.newPair()
        val pc = x509(Cert.selfSigned(side))
        return Pin.handshake(
            Pin.context(Pin.Trust(Pin.of(pc.encoded)), Pin.OneKey(arrayOf(cert), key)),
            Pin.context(Pin.Trust(Pin.of(cert.encoded)), Pin.OneKey(arrayOf(pc), side.private)),
        ) != null
    }

    /**
     * Did this slot sign a whole handshake, on this build of Android? A phone
     * locked just now fails for that reason alone, and a failure that a software
     * key fails too says nothing about Keystore, so neither counts.
     */
    private fun passes(c: Context, slot: String): Boolean {
        val mark = PASSED + slot
        if (sp(c).getString(mark, "") == Build.FINGERPRINT) return true
        val entry = keystore()
        val key = entry.getKey(slot, null) as? PrivateKey ?: return true
        val cert = entry.getCertificate(slot) as? X509Certificate ?: return true
        val t0 = System.nanoTime()
        val ok = try {
            handshakes(cert, key)
        } catch (e: RuntimeException) {
            Log.w("DeskIT", "client key: the handshake threw ${e.javaClass.simpleName}")
            false
        }
        val ms = (System.nanoTime() - t0) / 1_000_000
        if (ok) {
            Log.i("DeskIT", "client key: TLS holds, in memory, in $ms ms")
            sp(c).edit().putString(mark, Build.FINGERPRINT).commit()
            return true
        }
        if (Sealed.locked(c)) return true
        val pair = Crypt.newPair()
        val control = try {
            handshakes(x509(Cert.selfSigned(pair)), pair.private)
        } catch (e: RuntimeException) {
            false
        }
        Log.w("DeskIT", "client key: Keystore will not do TLS here (a software key would: $control)")
        return !control
    }

    /** True when the Keystore key is the weaker: the screen lock came after it. */
    private fun canDoBetter(c: Context, slot: String): Boolean =
        slot != SOFT && Sealed.lockable(c) && !Sealed.locked(c) &&
            !sp(c).getBoolean(STRICT + slot, false) && !sp(c).getBoolean(NO_STRICT, false)

    /** The slot a better key goes in. */
    private fun nextSlot(id: String) = "${alias(id)}.${System.currentTimeMillis()}"

    /** A key the row has yet to carry, when this one has to give way. Null when it need not. */
    private fun better(c: Context, id: String, slot: String): String? {
        if (slot != SOFT && !passes(c, slot)) {
            makeSoft(c)
            return SOFT
        }
        if (!canDoBetter(c, slot)) return null
        val next = nextSlot(id)
        return try {
            made(c, next)
            if (sp(c).getBoolean(STRICT + next, false)) next
            else {
                keystore().deleteEntry(next)    // no better than the one it has
                null
            }
        } catch (e: Sealed.NotNow) {
            null                                // the next look, on a phone in a hand
        }
    }

    /**
     * The certificate this device's row should carry, making the key the first
     * time, and a better one when there can be one. Runs at every look.
     */
    @Synchronized
    fun ensure(c: Context, deviceId: String): ByteArray = asked(c) {
        val slot = active(c, deviceId)
        val mine = der(c, slot) ?: first(c, deviceId, slot)
        val waiting = pending(c, deviceId)?.let { der(c, it) }
        if (waiting != null) return@asked waiting
        // [first] may have gone straight to the software key
        val next = better(c, deviceId, active(c, deviceId)) ?: return@asked mine
        sp(c).edit().putString(PENDING + deviceId, next).commit()
        der(c, next) ?: mine
    }

    /** The first key: Keystore's, or what stands in for it on a phone that has none to give. */
    private fun first(c: Context, id: String, slot: String): ByteArray {
        try {
            made(c, slot)
            if (passes(c, slot)) return keystore().getCertificate(slot).encoded
        } catch (e: GeneralSecurityException) {
            if (Sealed.locked(c)) throw e
            Log.w("DeskIT", "client key: no Keystore key here: ${e.javaClass.simpleName}")
        } catch (e: ProviderException) {
            if (Sealed.locked(c)) throw e
            Log.w("DeskIT", "client key: no Keystore key here: ${e.javaClass.simpleName}")
        }
        makeSoft(c)
        sp(c).edit().putString(ACTIVE + id, SOFT).commit()
        return soft(c)?.first ?: throw Sealed.NotNow("the client key would not keep")
    }

    /**
     * Keystore failed a real handshake, as [passes] would have told: the software
     * key takes over at the next look. What a test does, and what a door has no
     * way to do: a door that refuses says nothing about why.
     */
    @Synchronized
    fun fallBack(c: Context, deviceId: String) = asked(c) {
        if (active(c, deviceId) != SOFT) {
            makeSoft(c)
            sp(c).edit().putString(PENDING + deviceId, SOFT).commit()
        }
    }

    /** The row carrying [der] has landed: the key behind it is the one in use now. */
    @Synchronized
    fun published(c: Context, deviceId: String, der: ByteArray) = asked(c) {
        val next = pending(c, deviceId) ?: return@asked
        if (der(c, next)?.contentEquals(der) != true) return@asked
        val old = active(c, deviceId)
        sp(c).edit().putString(ACTIVE + deviceId, next).remove(PENDING + deviceId)
            .remove(STRICT + old).remove(PASSED + old).commit()
        if (old == SOFT) Sealed.delete(c, SOFT) else keystore().deleteEntry(old)
    }

    /** The certificate in use, if there is one; no key is made. */
    fun certificate(c: Context, deviceId: String): ByteArray? = asked(c) {
        der(c, active(c, deviceId))
    }

    /** What the door is shown. Null when this device has no key yet. */
    fun forDoor(c: Context, deviceId: String): Pin.OneKey? = asked(c) {
        val slot = active(c, deviceId)
        if (slot == SOFT) soft(c)?.let { Pin.OneKey(arrayOf(x509(it.first)), it.second) }
        else {
            val entry = keystore()
            val key = entry.getKey(slot, null) as? PrivateKey
            val cert = entry.getCertificate(slot) as? X509Certificate
            if (key == null || cert == null) null else Pin.OneKey(arrayOf(cert), key)
        }
    }

    /** Every client key on this phone: what leaving, or being forgotten, wipes. */
    @Synchronized
    fun wipe(c: Context) = asked(c) {
        val ks = keystore()
        for (a in ks.aliases().toList()) if (a.startsWith(PREFIX)) ks.deleteEntry(a)
        Sealed.delete(c, SOFT)
        sp(c).edit().clear().commit()
    }
}
