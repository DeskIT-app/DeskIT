package io.github.deskit_app.deskit

import android.app.KeyguardManager
import android.content.Context
import android.os.Build
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyPermanentlyInvalidatedException
import android.security.keystore.KeyProperties
import android.util.Log
import java.io.File
import java.io.IOException
import java.security.GeneralSecurityException
import java.security.KeyStore
import java.security.ProviderException
import javax.crypto.AEADBadTagException
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

/**
 * What the phone keeps under a key that cannot leave its hardware: the
 * session, the account key, the join's private half. One AES-GCM key in
 * Android Keystore, one small file per name under noBackupFilesDir, the name
 * as the associated data so a file cannot be moved under another name.
 * `EncryptedSharedPreferences` (D22) is not used: androidx.security-crypto is
 * deprecated, whole, and this is what it did.
 *
 * The key is made with setUnlockedDeviceRequired where the phone has it
 * (API 28+), so a stolen, locked phone cannot open any of this. That makes
 * "cannot open it now" an everyday answer, not a loss, and the two must never
 * be confused: [NotNow] leaves everything where it is, and only a file that
 * can never open again ([get] returning null) lets a caller start over. A
 * Keystore key can die under us (a device policy, a changed lock screen on
 * some phones): that reads as nothing there, and the phone asks to join again.
 */
object Sealed {
    private const val STORE = "AndroidKeyStore"
    private const val ALIAS = "deskit.sealed.v1"
    private const val MODE = "AES/GCM/NoPadding"
    private const val TAG_BITS = 128
    private const val IV_BYTES = 12

    /**
     * The phone is locked, or Keystore said no for now. Ask again later.
     * [locked] is which of the two, because they are different sentences: a
     * phone that is open in the person's hand must not be told to unlock.
     */
    class NotNow(why: String, val locked: Boolean = false, cause: Throwable? = null) :
        Exception(why, cause) {
        init {
            // Class names and Keystore's own words, never a value: this is
            // what a phone we have never held will say when it refuses.
            Log.w("DeskIT", "sealed: $why" + (cause?.let { " (${it.message})" } ?: ""))
        }
    }

    /** What a screen says for a [NotNow]. */
    fun words(c: Context, e: NotNow): String =
        c.getString(if (e.locked) R.string.phone_locked else R.string.keystore_busy)

    private fun dir(c: Context) = File(c.noBackupFilesDir, "sealed").apply { mkdirs() }

    private fun file(c: Context, name: String) = File(dir(c), "$name.bin")

    fun has(c: Context, name: String): Boolean = file(c, name).exists()

    fun locked(c: Context): Boolean =
        (c.getSystemService(Context.KEYGUARD_SERVICE) as KeyguardManager).isDeviceLocked

    /**
     * Can this phone be locked at all? With no screen lock, Android 14 refuses
     * even to MAKE an unlocked-only key: keystore2 fails it with "User ECDH
     * key missing" and hands us a ProviderException (measured on the emulator,
     * 2026-11-06). The condition would mean nothing there anyway.
     */
    fun lockable(c: Context): Boolean = Build.VERSION.SDK_INT >= 28 &&
        (c.getSystemService(Context.KEYGUARD_SERVICE) as KeyguardManager).isDeviceSecure

    private fun make(c: Context): SecretKey {
        if (locked(c)) throw NotNow("the phone is locked", locked = true)
        if (lockable(c)) {
            try {
                val strict = makeOne(unlockedOnly = true)
                roundTrip(strict)
                return strict
            } catch (e: GeneralSecurityException) {
                // A phone whose Keystore will not make the key, or makes it
                // and then will not use it. Sealed without the condition
                // beats not sealed at all.
                Log.w("DeskIT", "no unlocked-only key here: ${e.javaClass.simpleName}")
            } catch (e: ProviderException) {
                Log.w("DeskIT", "no unlocked-only key here: ${e.javaClass.simpleName}")
            }
        }
        return makeOne(unlockedOnly = false)
    }

    private fun makeOne(unlockedOnly: Boolean): SecretKey {
        val spec = KeyGenParameterSpec.Builder(
            ALIAS, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
            .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
            .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
            .setKeySize(256)
        if (unlockedOnly && Build.VERSION.SDK_INT >= 28) spec.setUnlockedDeviceRequired(true)
        return KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, STORE)
            .apply { init(spec.build()) }
            .generateKey()
    }

    private fun roundTrip(key: SecretKey) {
        val e = Cipher.getInstance(MODE).apply { init(Cipher.ENCRYPT_MODE, key) }
        val sealed = e.doFinal(ByteArray(8))
        val d = Cipher.getInstance(MODE)
        d.init(Cipher.DECRYPT_MODE, key, GCMParameterSpec(TAG_BITS, e.iv))
        d.doFinal(sealed)
    }

    private fun stored(): SecretKey? {
        val ks = KeyStore.getInstance(STORE).apply { load(null) }
        return ks.getKey(ALIAS, null) as? SecretKey
    }

    private fun drop() {
        KeyStore.getInstance(STORE).apply { load(null) }.deleteEntry(ALIAS)
    }

    /** Keep [plain] under [name], replacing what was there. */
    @Synchronized
    fun put(c: Context, name: String, plain: ByteArray) {
        val aad = name.toByteArray(Charsets.UTF_8)
        fun seal(key: SecretKey): ByteArray {
            val cipher = Cipher.getInstance(MODE)
            cipher.init(Cipher.ENCRYPT_MODE, key)
            cipher.updateAAD(aad)
            return cipher.iv + cipher.doFinal(plain)
        }
        val out = try {
            try {
                seal(stored() ?: make(c))
            } catch (e: KeyPermanentlyInvalidatedException) {
                drop()
                seal(make(c))
            }
        } catch (e: GeneralSecurityException) {
            throw NotNow("nothing could be sealed: ${e.javaClass.simpleName}", locked(c), e)
        } catch (e: ProviderException) {
            throw NotNow("nothing could be sealed: ${e.javaClass.simpleName}", locked(c), e)
        } catch (e: IOException) {
            throw NotNow("nothing could be sealed: ${e.javaClass.simpleName}", locked(c), e)
        }
        val f = file(c, name)
        val tmp = File(f.path + ".tmp")
        tmp.writeBytes(out)
        if (!tmp.renameTo(f)) {
            tmp.delete()
            throw NotNow("the sealed file could not be written")
        }
    }

    /**
     * What [name] holds; null when there is nothing there, or what is there
     * can never open again. [NotNow] when it cannot be opened at this moment.
     */
    @Synchronized
    fun get(c: Context, name: String): ByteArray? {
        val f = file(c, name)
        if (!f.exists()) return null
        val raw = f.readBytes()
        if (raw.size < IV_BYTES) return null
        return try {
            val key = stored() ?: return null
            val cipher = Cipher.getInstance(MODE)
            cipher.init(Cipher.DECRYPT_MODE, key, GCMParameterSpec(TAG_BITS, raw, 0, IV_BYTES))
            cipher.updateAAD(name.toByteArray(Charsets.UTF_8))
            cipher.doFinal(raw, IV_BYTES, raw.size - IV_BYTES)
        } catch (e: AEADBadTagException) {
            if (locked(c)) throw NotNow("the phone is locked", true, e)
            null
        } catch (e: KeyPermanentlyInvalidatedException) {
            null
        } catch (e: GeneralSecurityException) {
            val now = locked(c)
            throw NotNow(if (now) "the phone is locked" else e.javaClass.simpleName, now, e)
        } catch (e: ProviderException) {
            val now = locked(c)
            throw NotNow(if (now) "the phone is locked" else e.javaClass.simpleName, now, e)
        } catch (e: IOException) {
            throw NotNow(e.javaClass.simpleName, false, e)
        }
    }

    fun delete(c: Context, name: String) {
        file(c, name).delete()
    }

    /**
     * The sealing key itself goes, for a phone leaving its account: everything
     * it sealed has gone already. The next seal makes a new key under what the
     * phone is by then, so one that gained a screen lock after its key was made
     * comes back with an unlocked-only key and not the old one.
     */
    @Synchronized
    fun dropKey() {
        try {
            drop()
        } catch (e: GeneralSecurityException) {
            Log.w("DeskIT", "the sealing key stays: ${e.javaClass.simpleName}")
        } catch (e: IOException) {
            Log.w("DeskIT", "the sealing key stays: ${e.javaClass.simpleName}")
        }
    }

    /** Text forms, for the JSON blobs almost everything here is. */
    fun putText(c: Context, name: String, text: String) =
        put(c, name, text.toByteArray(Charsets.UTF_8))

    fun getText(c: Context, name: String): String? =
        get(c, name)?.let { String(it, Charsets.UTF_8) }
}
