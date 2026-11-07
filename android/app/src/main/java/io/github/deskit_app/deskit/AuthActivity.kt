package io.github.deskit_app.deskit

import android.app.Activity
import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.view.Gravity
import kotlin.concurrent.thread

/**
 * Where the browser lands: deskit://auth. A line on the ground while the code
 * is exchanged, then the way back. Exported, because a browser has to reach
 * it, so it carries no authority of its own: Account.finishSignIn needs the
 * verifier this phone sealed when it opened the browser.
 *
 * Exported also means anything on the phone can start it with anything, past
 * the manifest's filter on Android 12 and down. Only that one address is read:
 * a URI that is not hierarchical throws on the thread below, and the keyboard
 * dies with the process.
 */
class AuthActivity : Activity() {

    override fun onCreate(saved: Bundle?) {
        super.onCreate(saved)
        Skin.page(this).apply {
            gravity = Gravity.CENTER_HORIZONTAL
            setPadding(0, Skin.dp(this@AuthActivity, 120), 0, 0)
            addView(Skin.text(this@AuthActivity, getString(R.string.signing_in), 16f, Skin.DIM))
        }
        back(intent?.data)
    }

    override fun onNewIntent(intent: Intent?) {
        super.onNewIntent(intent)
        back(intent?.data)
    }

    private fun back(uri: Uri?) {
        val home = Uri.parse(Account.REDIRECT)
        if (uri == null || uri.scheme != home.scheme || uri.host != home.host) {
            finish()
            return
        }
        thread {
            val word = try {
                Account.finishSignIn(this, uri)
                ""
            } catch (e: Account.Failed) {
                e.message.orEmpty()
            } catch (e: Sealed.NotNow) {
                Sealed.words(this, e)
            }
            runOnUiThread {
                startActivity(Intent(this, AccountActivity::class.java)
                    .putExtra(EXTRA_WORD, word)
                    .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP))
                finish()
            }
        }
    }

    companion object {
        const val EXTRA_WORD = "word"
    }
}
