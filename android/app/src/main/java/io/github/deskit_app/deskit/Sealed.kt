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
 *
 * A phone with no screen lock cannot have such a key, and one that gets a lock
 * later should not stay without it. Two aliases: [ALIAS] is a key with no
 * condition, or one from before anyone kept count, and [STRICT] is the
 * unlocked-only one. [strengthen] moves every file across by itself, one atomic
 * file at a time, so a process killed in the middle leaves files under both, and
 * [get] opens either until it runs again. Android tells nobody when a lock
 * appears, so a look asks.
 */
object Sealed {
    private const val STORE = "AndroidKeyStore"
    private const val ALIAS = "deskit.sealed.v1"
    private const val STRICT = "deskit.sealed.v2"
    private const val MODE = "AES/GCM/NoPadding"
    private const val TAG_BITS = 128
    private const val IV_BYTES = 12
    private const val SUFFIX = ".bin"
    /** A phone whose Keystore will not make the strict key: it is not asked at every look. */
    private const val NO_STRICT = "no_strict"

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

    private fun file(c: Context, name: String) = File(dir(c), name + SUFFIX)

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
            strictKey()?.let { return it }
            // A phone that locked in this very moment fails the same way, and
            // the weaker key would be its key for good.
            if (locked(c)) throw NotNow("the phone is locked", locked = true)
        }
        return makeOne(ALIAS, unlockedOnly = false)
    }

    /**
     * Null on a phone whose Keystore will not make the key, or makes it and then
     * will not use it. Sealed without the condition beats not sealed at all.
     */
    private fun strictKey(): SecretKey? = try {
        makeOne(STRICT, unlockedOnly = true).also { roundTrip(it) }
    } catch (e: GeneralSecurityException) {
        Log.w("DeskIT", "no unlocked-only key here: ${e.javaClass.simpleName}")
        null
    } catch (e: ProviderException) {
        Log.w("DeskIT", "no unlocked-only key here: ${e.javaClass.simpleName}")
        null
    }

    private fun makeOne(alias: String, unlockedOnly: Boolean): SecretKey {
        val spec = KeyGenParameterSpec.Builder(
            alias, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
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

    private fun keystore() = KeyStore.getInstance(STORE).apply { load(null) }

    private fun held(alias: String): SecretKey? = keystore().getKey(alias, null) as? SecretKey

    /** The key to seal with. */
    private fun stored(): SecretKey? = held(STRICT) ?: held(ALIAS)

    private fun drop() {
        keystore().apply {
            deleteEntry(STRICT)
            deleteEntry(ALIAS)
        }
    }

    private fun sealWith(key: SecretKey, name: String, plain: ByteArray): ByteArray {
        val cipher = Cipher.getInstance(MODE)
        cipher.init(Cipher.ENCRYPT_MODE, key)
        cipher.updateAAD(name.toByteArray(Charsets.UTF_8))
        return cipher.iv + cipher.doFinal(plain)
    }

    private fun openWith(key: SecretKey, name: String, raw: ByteArray): ByteArray {
        val cipher = Cipher.getInstance(MODE)
        cipher.init(Cipher.DECRYPT_MODE, key, GCMParameterSpec(TAG_BITS, raw, 0, IV_BYTES))
        cipher.updateAAD(name.toByteArray(Charsets.UTF_8))
        return cipher.doFinal(raw, IV_BYTES, raw.size - IV_BYTES)
    }

    private fun write(f: File, out: ByteArray) {
        val tmp = File(f.path + ".tmp")
        try {
            tmp.writeBytes(out)
        } catch (e: IOException) {
            // A full phone, above all. What was sealed before is still there.
            tmp.delete()
            throw NotNow("the sealed file could not be written", false, e)
        }
        if (!tmp.renameTo(f)) {
            tmp.delete()
            throw NotNow("the sealed file could not be written")
        }
    }

    /**
     * Is what is here kept under a key a locked phone can use, on a phone that
     * could do better now? The question is a Keystore call, so a look asks and a
     * keyboard does not.
     */
    @Synchronized
    fun weak(c: Context): Boolean = try {
        lockable(c) && keystore().containsAlias(ALIAS) && !File(dir(c), NO_STRICT).exists()
    } catch (e: GeneralSecurityException) {
        false
    } catch (e: IOException) {
        false
    }

    /**
     * A screen lock has appeared since the key was made: every file moves to one
     * a locked phone cannot use, and the old key goes. Quiet: a phone that says
     * nothing about having no lock says nothing about getting one, and whatever
     * stops this leaves everything readable for the next look.
     */
    @Synchronized
    fun strengthen(c: Context) {
        if (!weak(c)) return
        try {
            val strict = held(STRICT) ?: strictKey()
            if (strict == null) {
                if (!locked(c)) File(dir(c), NO_STRICT).writeBytes(ByteArray(0))
                return
            }
            val old = held(ALIAS) ?: return
            for (f in dir(c).listFiles().orEmpty()) {
                if (!f.name.endsWith(SUFFIX)) continue
                val name = f.name.removeSuffix(SUFFIX)
                val raw = f.readBytes()
                if (raw.size < IV_BYTES) continue
                val plain = try {
                    openWith(old, name, raw)
                } catch (e: AEADBadTagException) {
                    continue                    // moved already
                }
                write(f, sealWith(strict, name, plain))
                plain.fill(0)
            }
            keystore().deleteEntry(ALIAS)
            Log.i("DeskIT", "sealed: what is here now needs the phone unlocked")
        } catch (e: GeneralSecurityException) {
            Log.w("DeskIT", "sealed: not moved: ${e.javaClass.simpleName}")
        } catch (e: ProviderException) {
            Log.w("DeskIT", "sealed: not moved: ${e.javaClass.simpleName}")
        } catch (e: IOException) {
            Log.w("DeskIT", "sealed: not moved: ${e.javaClass.simpleName}")
        } catch (e: NotNow) {
            // a phone that filled up, and the next look tries again
        }
    }

    /**
     * Can [put] seal at this moment? The question goes to Keystore, because
     * that is who says no: KeyguardManager still reads "locked" for a moment
     * after it has opened (measured on Android 14, 2026-11-07, in an activity
     * the unlocking had resumed), and a key made before the screen lock seals
     * on a locked phone all the same.
     */
    @Synchronized
    fun sealsNow(c: Context): Boolean = try {
        val key = stored()
        if (key == null) !locked(c)
        else {
            Cipher.getInstance(MODE).apply { init(Cipher.ENCRYPT_MODE, key) }.doFinal(ByteArray(1))
            true
        }
    } catch (e: KeyPermanentlyInvalidatedException) {
        true                            // put makes a new key
    } catch (e: GeneralSecurityException) {
        false
    } catch (e: ProviderException) {
        false
    } catch (e: IOException) {
        false
    }

    /** Keep [plain] under [name], replacing what was there. */
    @Synchronized
    fun put(c: Context, name: String, plain: ByteArray) {
        val out = try {
            try {
                sealWith(stored() ?: make(c), name, plain)
            } catch (e: KeyPermanentlyInvalidatedException) {
                drop()
                sealWith(make(c), name, plain)
            }
        } catch (e: GeneralSecurityException) {
            throw NotNow("nothing could be sealed: ${e.javaClass.simpleName}", locked(c), e)
        } catch (e: ProviderException) {
            throw NotNow("nothing could be sealed: ${e.javaClass.simpleName}", locked(c), e)
        } catch (e: IOException) {
            throw NotNow("nothing could be sealed: ${e.javaClass.simpleName}", locked(c), e)
        }
        write(file(c, name), out)
    }

    /**
     * What [name] holds; null when there is nothing there, or what is there
     * can never open again. [NotNow] when it cannot be opened at this moment.
     */
    @Synchronized
    fun get(c: Context, name: String): ByteArray? {
        val f = file(c, name)
        if (!f.exists()) return null
        val raw = try {
            f.readBytes()
        } catch (e: IOException) {
            throw NotNow("the sealed file could not be read", false, e)
        }
        if (raw.size < IV_BYTES) return null
        return try {
            val strict = held(STRICT)
            val old = held(ALIAS)
            if (strict == null && old == null) return null
            try {
                openWith(strict ?: old!!, name, raw)
            } catch (e: AEADBadTagException) {
                // a file [strengthen] had not reached when it was stopped
                if (strict == null || old == null) throw e
                openWith(old, name, raw)
            }
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
    fun dropKey(c: Context) {
        File(dir(c), NO_STRICT).delete()
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
