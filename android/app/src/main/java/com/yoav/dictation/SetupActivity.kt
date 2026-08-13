package com.yoav.dictation

import android.app.Activity
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Color
import android.os.Bundle
import android.provider.Settings
import android.util.TypedValue
import android.view.ViewGroup
import android.widget.Button
import android.widget.CheckBox
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import android.widget.Toast
import kotlin.concurrent.thread

/**
 * The one screen: grant the microphone, point at the PC, turn the keyboard on.
 *
 * The microphone permission has to be requested here — an
 * InputMethodService cannot show a runtime permission dialog, so a
 * keyboard that asks for the mic itself would simply be denied forever.
 */
class SetupActivity : Activity() {

    private lateinit var urlField: EditText
    private lateinit var tokenField: EditText
    private lateinit var switchBack: CheckBox
    private lateinit var result: TextView

    override fun onCreate(saved: Bundle?) {
        super.onCreate(saved)
        val dp = { v: Int ->
            TypedValue.applyDimension(
                TypedValue.COMPLEX_UNIT_DIP, v.toFloat(), resources.displayMetrics
            ).toInt()
        }
        val col = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(22), dp(28), dp(22), dp(28))
        }

        fun label(text: String, size: Float = 14f, colour: String = "#444c5c") {
            col.addView(TextView(this).apply {
                this.text = text
                setTextSize(TypedValue.COMPLEX_UNIT_SP, size)
                setTextColor(Color.parseColor(colour))
                setPadding(0, dp(14), 0, dp(4))
            })
        }

        label(getString(R.string.app_name), 22f, "#101319")
        // Version on screen: the only way to answer "did my reinstall
        // actually take?" without guessing at the phone's behaviour.
        val version = try {
            packageManager.getPackageInfo(packageName, 0).versionName
        } catch (e: Exception) { "?" }
        label("v$version", 13f, "#8b8f99")
        label(getString(R.string.setup_intro))

        label(getString(R.string.paste_url_label))
        urlField = EditText(this).apply {
            hint = Prefs.DEFAULT_URL
            setText(Prefs.url(this@SetupActivity))
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 14f)
        }
        col.addView(urlField)

        label(getString(R.string.token_label))
        tokenField = EditText(this).apply {
            setText(Prefs.token(this@SetupActivity))
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 14f)
        }
        col.addView(tokenField)

        switchBack = CheckBox(this).apply {
            text = getString(R.string.switch_back_label)
            isChecked = Prefs.switchBack(this@SetupActivity)
        }
        col.addView(switchBack)

        col.addView(Button(this).apply {
            text = getString(R.string.save_and_test)
            setOnClickListener { saveAndTest() }
        })

        result = TextView(this).apply {
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 14f)
            setPadding(0, dp(12), 0, dp(4))
        }
        col.addView(result)

        label(getString(R.string.steps_title), 16f, "#101319")
        label(getString(R.string.steps_body))

        col.addView(Button(this).apply {
            text = getString(R.string.grant_mic)
            setOnClickListener {
                requestPermissions(arrayOf(android.Manifest.permission.RECORD_AUDIO), 1)
            }
        })
        col.addView(Button(this).apply {
            text = getString(R.string.enable_keyboard)
            setOnClickListener {
                startActivity(Intent(Settings.ACTION_INPUT_METHOD_SETTINGS))
            }
        })

        setContentView(ScrollView(this).apply {
            addView(col, ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT)
        })

        // Paste the whole "https://host/#t=token" line and both fields fill.
        urlField.setOnFocusChangeListener { _, focused ->
            if (!focused) splitPastedUrl()
        }
    }

    private fun splitPastedUrl() {
        Prefs.parsePasted(urlField.text.toString())?.let { (url, token) ->
            urlField.setText(url)
            if (token.isNotEmpty()) tokenField.setText(token)
        }
    }

    private fun saveAndTest() {
        splitPastedUrl()
        val url = urlField.text.toString().trim().trimEnd('/')
        val token = tokenField.text.toString().trim()
        Prefs.save(this, url, token, switchBack.isChecked)
        result.text = getString(R.string.checking)
        thread {
            // A one-second silent clip: proves DNS, Tailscale, TLS, the
            // token and the model in one round trip, without needing the
            // user to say anything.
            val silent = ByteArray(Recorder.SAMPLE_RATE * 2)
            val r = Transcriber.send(url, token, wavOf(silent))
            runOnUiThread {
                when (r) {
                    is Transcriber.Result.Ok -> {
                        result.setTextColor(Color.parseColor("#1a7f37"))
                        result.text = getString(R.string.reachable)
                    }
                    is Transcriber.Result.Err -> {
                        result.setTextColor(Color.parseColor("#c0392b"))
                        result.text = r.message
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

    override fun onRequestPermissionsResult(
        requestCode: Int, permissions: Array<out String>, grantResults: IntArray
    ) {
        val ok = grantResults.firstOrNull() == PackageManager.PERMISSION_GRANTED
        Toast.makeText(
            this,
            getString(if (ok) R.string.mic_granted else R.string.mic_denied),
            Toast.LENGTH_LONG
        ).show()
    }
}
