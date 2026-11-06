package io.github.deskit_app.deskit

import android.app.Activity
import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.view.Gravity
import android.widget.LinearLayout
import kotlin.concurrent.thread

/**
 * Where the browser lands: deskit://auth. A line on the ground while the code
 * is exchanged, then the way back. Exported, because a browser has to reach
 * it, so it carries no authority of its own: Account.finishSignIn needs the
 * verifier this phone sealed when it opened the browser.
 */
class AuthActivity : Activity() {

    override fun onCreate(saved: Bundle?) {
        super.onCreate(saved)
        setContentView(LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            gravity = Gravity.CENTER
            setBackgroundColor(Skin.BG)
            addView(Skin.text(this@AuthActivity, getString(R.string.signing_in), 16f, Skin.DIM))
        })
        back(intent?.data)
    }

    override fun onNewIntent(intent: Intent?) {
        super.onNewIntent(intent)
        back(intent?.data)
    }

    private fun back(uri: Uri?) {
        if (uri == null) { finish(); return }
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
