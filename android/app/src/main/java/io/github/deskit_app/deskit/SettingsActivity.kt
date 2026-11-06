package io.github.deskit_app.deskit

import android.app.Activity
import android.content.Intent
import android.graphics.Color
import android.net.Uri
import android.os.Build
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
    private lateinit var updateResult: TextView
    private lateinit var accountBox: LinearLayout

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

        // A way back that is on the page, not only on the phone's own bar.
        val head = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            setPadding(0, 0, 0, Skin.dp(this@SettingsActivity, 6))
        }
        head.addView(Skin.backButton(this) { finish() })
        head.addView(Skin.text(this, getString(R.string.settings), 26f, Skin.FG, heavy = true))
        col.addView(head)
        col.addView(Skin.text(this, getString(R.string.setup_intro), 14f, Skin.DIM).apply {
            setPadding(0, 0, 0, Skin.dp(this@SettingsActivity, 20))
            setLineSpacing(0f, 1.25f)
        })

        accountBox = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        col.addView(accountBox)

        // ---- the PC ----
        val pc = Skin.card(this)
        pc.addView(Skin.eyebrow(this, getString(R.string.the_pc)))
        pc.addView(Skin.gap(this, 12))
        pc.addView(label(getString(R.string.paste_url_label)))
        urlField = field(Prefs.url(this), getString(R.string.url_hint))
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
        // The answer lands under the button that asked, not under Save.
        updateResult = Skin.text(this, "", 14f, Skin.DIM).apply {
            setPadding(0, Skin.dp(this@SettingsActivity, 12), 0, 0)
            visibility = View.GONE
        }
        app.addView(updateResult)
        col.addView(app)

        // Paste the whole "https://host/#t=token" line and both fields fill.
        urlField.setOnFocusChangeListener { _, focused -> if (!focused) splitPastedUrl() }
    }

    // ---- the account ----

    private var drawnDevices: List<Lock.Device> = emptyList()
    private var drawnAsking: List<Lock.Asking> = emptyList()
    private var drawnState: Lock.State? = null
    private var drawnWord = ""
    /** The device whose Forget is being asked, in its own row. */
    private var askingForget = ""
    private var askingSignOut = false

    override fun onResume() {
        super.onResume()
        readAccount()
    }

    /** Whoever opens Settings sees who is asking: the plan's one read, here. */
    private fun readAccount() {
        thread {
            val st = Lock.look(this)
            var devices = emptyList<Lock.Device>()
            var asking = emptyList<Lock.Asking>()
            var word = if (st is Lock.State.Ready) st.word else ""
            if (st is Lock.State.Ready) {
                try {
                    devices = Lock.devices(this)
                    asking = Lock.asking(this)
                } catch (e: Account.Failed) {
                    word = e.message.orEmpty()
                    devices = cached()
                } catch (e: Sealed.NotNow) {
                    word = Sealed.words(this, e)
                }
            }
            runOnUiThread {
                drawnState = st
                drawnDevices = devices
                drawnAsking = asking
                drawnWord = word
                if (!isFinishing) drawAccount()
            }
        }
    }

    private fun cached(): List<Lock.Device> = try {
        Lock.cachedDevices(this)
    } catch (e: Account.Failed) {
        emptyList()
    } catch (e: Sealed.NotNow) {
        emptyList()
    }

    private fun openAccount() {
        startActivity(Intent(this, AccountActivity::class.java))
    }

    private fun seenWords(d: Lock.Device): String {
        val days = ((System.currentTimeMillis() / 1000 - d.seen) / 86400).toInt()
        return when {
            days <= 0 -> getString(R.string.seen_today)
            days == 1 -> getString(R.string.seen_yesterday)
            else -> resources.getQuantityString(R.plurals.seen_days, days, days)
        }
    }

    private fun rowOf(d: Lock.Device): AccountScreens.Row = AccountScreens.Row(
        d.id, d.name, getString(if (d.isPc) R.string.kind_pc else R.string.kind_phone),
        if (d.seen > 0) seenWords(d) else "", d.mine, d.linked)

    private fun drawAccount() {
        accountBox.removeAllViews()
        val st = drawnState ?: return
        val a = AccountScreens(this)
        if (st !is Lock.State.Ready) {
            val line = when (st) {
                is Lock.State.SignedOut -> R.string.sign_in_line
                is Lock.State.Changed -> R.string.step_changed
                is Lock.State.NoLock -> R.string.no_lock_title
                is Lock.State.Declined -> R.string.declined_title
                else -> R.string.approve_title
            }
            accountBox.addView(Skin.card(this).apply {
                addView(Skin.eyebrow(this@SettingsActivity, getString(R.string.your_account)))
                addView(Skin.gap(this@SettingsActivity, 10))
                addView(Skin.text(this@SettingsActivity, getString(line), 15f, Skin.FG).apply {
                    setLineSpacing(0f, 1.25f)
                    setPadding(0, 0, 0, Skin.dp(this@SettingsActivity, 14))
                })
                addView(Skin.button(this@SettingsActivity,
                    getString(if (st is Lock.State.SignedOut) R.string.sign_in_google
                              else R.string.continue_),
                    primary = st is Lock.State.SignedOut) { openAccount() })
            })
            return
        }
        for (ask in drawnAsking) {
            accountBox.addView(a.asking(AccountScreens.Ask(ask.id, ask.name, ask.code),
                                        { approve(ask) }, { decline(ask) }))
        }
        val rows = drawnDevices.map { d ->
            if (d.id == askingForget) a.forgetQuestion(d.name, { forget(d) },
                                                       { askingForget = ""; drawAccount() })
            else a.deviceRow(rowOf(d), if (d.mine) null else ({
                askingForget = d.id
                drawAccount()
            }))
        }
        val foot: View =
            if (askingSignOut) a.signOutQuestion(Lock.recordings(this), { signOut() },
                                                 { askingSignOut = false; drawAccount() })
            else Skin.button(this, getString(R.string.sign_out)) {
                askingSignOut = true
                drawAccount()
            }
        accountBox.addView(a.accountCard(st.email, drawnWord, rows, foot))
    }

    /** One action on a thread, then the card read again. */
    private fun act(work: () -> Unit) {
        thread {
            val word = try {
                work()
                ""
            } catch (e: Account.Failed) {
                e.message.orEmpty()
            } catch (e: Sealed.NotNow) {
                Sealed.words(this, e)
            }
            runOnUiThread {
                if (word.isNotEmpty()) {
                    android.widget.Toast.makeText(this, word, android.widget.Toast.LENGTH_LONG).show()
                }
                readAccount()
            }
        }
    }

    private fun approve(ask: Lock.Asking) = act { Lock.approve(this, ask.id) }

    private fun decline(ask: Lock.Asking) = act { Lock.decline(this, ask.id) }

    private fun forget(d: Lock.Device) {
        askingForget = ""
        act { Lock.forget(this, d) }
    }

    private fun signOut() {
        askingSignOut = false
        act { if (!Lock.signOut(this)) throw Account.Failed(getString(R.string.sign_out_unreached)) }
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

    private fun say(s: String, colour: Int, into: TextView = result) {
        into.visibility = View.VISIBLE
        into.text = s
        into.setTextColor(colour)
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
     * Ask the PC's /api/version (12.9) for the newest keyboard build it
     * knows of and compare it with this one's versionCode; only when the
     * PC names a newer one does the browser open — at the release
     * download, or the store page when this copy came from Play. At the
     * latest there is nothing to fetch and nothing opens.
     */
    private fun checkForUpdate() {
        val url = Prefs.url(this)
        val token = Prefs.token(this)
        say(getString(R.string.checking), Skin.DIM, updateResult)
        thread {
            val remote = Transcriber.versions(url, token)
            val info = try { packageManager.getPackageInfo(packageName, 0) } catch (e: Exception) { null }
            val mine = info?.versionName ?: "?"
            val myCode = when {
                info == null -> 0
                Build.VERSION.SDK_INT >= 28 -> info.longVersionCode.toInt()
                else -> @Suppress("DEPRECATION") info.versionCode
            }
            val fromPlay = try {
                val installer = if (Build.VERSION.SDK_INT >= 30)
                    packageManager.getInstallSourceInfo(packageName).installingPackageName
                else @Suppress("DEPRECATION") packageManager.getInstallerPackageName(packageName)
                installer == "com.android.vending"
            } catch (e: Exception) { false }
            runOnUiThread {
                when {
                    remote == null -> say(getString(R.string.update_check_failed), Skin.RED, updateResult)
                    myCode >= remote.imeLatest ->
                        say(getString(R.string.up_to_date, mine), Skin.GREEN, updateResult)
                    else -> {
                        val name = "${remote.imeLatest / 10000}.${remote.imeLatest / 100 % 100}.${remote.imeLatest % 100}"
                        say(getString(R.string.update_available, name), Skin.GREEN, updateResult)
                        val where = if (fromPlay && remote.playUrl.isNotEmpty()) remote.playUrl
                                    else remote.apkUrl
                        if (where.isNotEmpty()) {
                            startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(where)))
                        }
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
