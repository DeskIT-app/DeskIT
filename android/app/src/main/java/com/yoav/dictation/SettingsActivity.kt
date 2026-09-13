package com.yoav.dictation

import android.app.Activity
import android.content.Intent
import android.graphics.Color
import android.net.Uri
import android.os.Bundle
import android.provider.Settings
import android.text.InputType
import android.util.TypedValue
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.Switch
import android.widget.TextView
import kotlin.concurrent.thread

/**
 * Everything that is a setting, on one page behind the home's one button.
 *
 * Where the PC is and the token that proves we may talk to it (paste the
 * whole "https://host/#t=token" line and both fields fill); whether to hop
 * back to the everyday keyboard after the text lands; the keys' order,
 * back to the designed one; the keyboard's own system page; and the
 * update check, which only opens the browser when the PC really has a
 * newer build.
 *
 * The microphone permission is asked from the home screen, not here — an
 * InputMethodService cannot show a runtime permission dialog, so some
 * activity has to, and the home's step list is where the red dot is.
 */
class SettingsActivity : Activity() {

    private lateinit var urlField: EditText
    private lateinit var tokenField: EditText
    private lateinit var switchBack: Switch
    private lateinit var result: TextView

    override fun onCreate(saved: Bundle?) {
        super.onCreate(saved)
        val col = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            layoutDirection = View.LAYOUT_DIRECTION_LTR
            val p = Skin.dp(this@SettingsActivity, 20)
            setPadding(p, Skin.dp(this@SettingsActivity, 24), p, Skin.dp(this@SettingsActivity, 32))
        }
        setContentView(ScrollView(this).apply {
            setBackgroundColor(Skin.BG)
            isVerticalScrollBarEnabled = false
            addView(col, ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT)
        })

        col.addView(Skin.text(this, getString(R.string.settings), 26f, Skin.FG, heavy = true)
            .apply { setPadding(0, 0, 0, Skin.dp(this@SettingsActivity, 6)) })
        col.addView(Skin.text(this, getString(R.string.setup_intro), 14f, Skin.DIM).apply {
            setPadding(0, 0, 0, Skin.dp(this@SettingsActivity, 20))
            setLineSpacing(0f, 1.25f)
        })

        // ---- the PC ----
        val pc = Skin.card(this)
        pc.addView(Skin.eyebrow(this, getString(R.string.the_pc)))
        pc.addView(Skin.gap(this, 12))
        pc.addView(label(getString(R.string.paste_url_label)))
        urlField = field(Prefs.url(this), Prefs.DEFAULT_URL)
        pc.addView(urlField)
        pc.addView(Skin.gap(this, 12))
        pc.addView(label(getString(R.string.token_label)))
        tokenField = field(Prefs.token(this), "")
        pc.addView(tokenField)
        pc.addView(Skin.gap(this, 16))
        pc.addView(Skin.button(this, getString(R.string.save_and_test), primary = true) {
            saveAndTest()
        })
        result = Skin.text(this, "", 14f, Skin.DIM).apply {
            setPadding(0, Skin.dp(this@SettingsActivity, 12), 0, 0)
            visibility = View.GONE
        }
        pc.addView(result)
        col.addView(pc)

        // ---- the keyboard ----
        val kb = Skin.card(this)
        kb.addView(Skin.eyebrow(this, getString(R.string.the_keyboard)))
        kb.addView(Skin.gap(this, 8))
        val sw = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            setPadding(0, Skin.dp(this@SettingsActivity, 8), 0, Skin.dp(this@SettingsActivity, 8))
        }
        sw.addView(Skin.text(this, getString(R.string.switch_back_label), 15f, Skin.FG).apply {
            layoutParams = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f)
                .apply { marginEnd = Skin.dp(this@SettingsActivity, 12) }
        })
        switchBack = Switch(this).apply {
            isChecked = Prefs.switchBack(this@SettingsActivity)
            thumbTintList = Skin.tint(Skin.FG)
            trackTintList = Skin.tint(Skin.LINE_HI)
            setOnCheckedChangeListener { _, on ->
                Prefs.save(this@SettingsActivity, Prefs.url(this@SettingsActivity),
                           Prefs.token(this@SettingsActivity), on)
            }
        }
        sw.addView(switchBack)
        kb.addView(sw)
        kb.addView(Skin.rule(this))
        kb.addView(Skin.text(this, getString(R.string.arrange_help), 13f, Skin.DIM).apply {
            setLineSpacing(0f, 1.25f)
            setPadding(0, 0, 0, Skin.dp(this@SettingsActivity, 12))
        })
        val keysRow = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL }
        keysRow.addView(Skin.button(this, getString(R.string.reset_keys)) {
            Prefs.saveKeyOrder(this, Prefs.DEFAULT_ORDER)
            android.widget.Toast.makeText(this, getString(R.string.keys_reset),
                                          android.widget.Toast.LENGTH_SHORT).show()
        }.apply {
            layoutParams = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f)
                .apply { marginEnd = Skin.dp(this@SettingsActivity, 10) }
        })
        keysRow.addView(Skin.button(this, getString(R.string.system_keyboards)) {
            startActivity(Intent(Settings.ACTION_INPUT_METHOD_SETTINGS))
        }.apply {
            layoutParams = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f)
        })
        kb.addView(keysRow)
        col.addView(kb)

        // ---- the app ----
        val app = Skin.card(this)
        app.addView(Skin.eyebrow(this, getString(R.string.the_app)))
        app.addView(Skin.gap(this, 8))
        val version = try {
            packageManager.getPackageInfo(packageName, 0).versionName
        } catch (e: Exception) { "?" }
        app.addView(Skin.text(this, getString(R.string.version_line, version), 14f, Skin.DIM)
            .apply { setPadding(0, 0, 0, Skin.dp(this@SettingsActivity, 12)) })
        app.addView(Skin.button(this, getString(R.string.check_update)) { checkForUpdate() })
        col.addView(app)

        // Paste the whole "https://host/#t=token" line and both fields fill.
        urlField.setOnFocusChangeListener { _, focused -> if (!focused) splitPastedUrl() }
    }

    private fun label(s: String): TextView = Skin.text(this, s, 13f, Skin.DIM).apply {
        setPadding(0, 0, 0, Skin.dp(this@SettingsActivity, 6))
    }

    private fun field(value: String, hintText: String): EditText = EditText(this).apply {
        setText(value)
        hint = hintText
        typeface = Skin.font(this@SettingsActivity)
        setTextSize(TypedValue.COMPLEX_UNIT_SP, 15f)
        setTextColor(Skin.FG)
        setHintTextColor(Skin.FAINT)
        background = Skin.face(this@SettingsActivity, Skin.PANE, Skin.LINE, 14)
        val px = Skin.dp(this@SettingsActivity, 14); val py = Skin.dp(this@SettingsActivity, 12)
        setPadding(px, py, px, py)
        inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_URI
        isSingleLine = true
        layoutDirection = View.LAYOUT_DIRECTION_LTR
        textDirection = View.TEXT_DIRECTION_LTR
    }

    private fun splitPastedUrl() {
        Prefs.parsePasted(urlField.text.toString())?.let { (url, token) ->
            urlField.setText(url)
            if (token.isNotEmpty()) tokenField.setText(token)
        }
    }

    private fun say(s: String, colour: Int) {
        result.visibility = View.VISIBLE
        result.text = s
        result.setTextColor(colour)
    }

    private fun saveAndTest() {
        splitPastedUrl()
        val url = urlField.text.toString().trim().trimEnd('/')
        val token = tokenField.text.toString().trim()
        Prefs.save(this, url, token, switchBack.isChecked)
        say(getString(R.string.checking), Skin.DIM)
        thread {
            // A one-second silent clip: proves DNS, Tailscale, TLS, the
            // token and the model in one round trip, without needing the
            // user to say anything.
            val silent = ByteArray(Recorder.SAMPLE_RATE * 2)
            val r = Transcriber.send(url, token, wavOf(silent))
            runOnUiThread {
                when (r) {
                    is Transcriber.Result.Ok -> say(getString(R.string.reachable), Skin.GREEN)
                    is Transcriber.Result.Err -> say(r.message, Skin.RED)
                }
            }
        }
    }

    /**
     * Compare the version the PC serves against the one installed, and
     * only open the browser when they differ — straight at the APK, so
     * the download starts immediately. When they match there is nothing
     * to fetch and nothing opens.
     */
    private fun checkForUpdate() {
        val url = Prefs.url(this)
        say(getString(R.string.checking), Skin.DIM)
        thread {
            val remote = Transcriber.serverApkVersion(url)
            val mine = try {
                packageManager.getPackageInfo(packageName, 0).versionName
            } catch (e: Exception) { "?" }
            runOnUiThread {
                when (remote) {
                    null -> say(getString(R.string.update_check_failed), Skin.RED)
                    mine -> say(getString(R.string.up_to_date, mine), Skin.GREEN)
                    else -> {
                        say(getString(R.string.update_available, remote), Skin.GREEN)
                        startActivity(Intent(Intent.ACTION_VIEW, Uri.parse("$url/app.apk")))
                    }
                }
            }
        }
    }

    private fun wavOf(pcm: ByteArray): ByteArray {
        val header = java.io.ByteArrayOutputStream()
        fun i32(v: Int) = header.write(
            byteArrayOf(
                (v and 0xff).toByte(), ((v shr 8) and 0xff).toByte(),
                ((v shr 16) and 0xff).toByte(), ((v shr 24) and 0xff).toByte()
            )
        )
        fun i16(v: Int) = header.write(
            byteArrayOf((v and 0xff).toByte(), ((v shr 8) and 0xff).toByte())
        )
        header.write("RIFF".toByteArray()); i32(36 + pcm.size)
        header.write("WAVE".toByteArray())
        header.write("fmt ".toByteArray()); i32(16); i16(1); i16(1)
        i32(Recorder.SAMPLE_RATE); i32(Recorder.SAMPLE_RATE * 2); i16(2); i16(16)
        header.write("data".toByteArray()); i32(pcm.size)
        header.write(pcm)
        return header.toByteArray()
    }
}
