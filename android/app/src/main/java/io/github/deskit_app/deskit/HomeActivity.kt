package io.github.deskit_app.deskit

import android.app.Activity
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import android.text.SpannableString
import android.text.Spanned
import android.text.style.ForegroundColorSpan
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.view.inputmethod.InputMethodManager
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import android.widget.Toast
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import kotlin.concurrent.thread

/**
 * What opens from the icon: a small home, not a form.
 *
 * Top to bottom — the state of the link to the PC as a lamp and a line;
 * a gold pill when the PC holds a newer build; the three set-up steps
 * only while one is still red; the second reading's proposals while any
 * wait; and the last things you said from this phone, a tap to copy.
 * Everything that is a setting is behind the one Settings button. It is
 * the desktop's Home, cut for a pocket: a summary, and doors.
 */
class HomeActivity : Activity() {

    private lateinit var col: LinearLayout
    private lateinit var lamp: LampView
    private lateinit var stateTitle: TextView
    private lateinit var stateLine: TextView
    private lateinit var updateCard: LinearLayout
    private lateinit var updateLine: TextView
    private lateinit var stepsCard: LinearLayout
    private lateinit var reviewCard: LinearLayout
    private lateinit var saidCard: LinearLayout
    /** Where the pill or the blocking card sends the person (12.9). */
    private var updateUrl: String = ""
    /** The newest keyboard versionCode the PC last named. */
    private var latestSeen = 0
    /** True while this build is below the PC's ime_min: the card blocks. */
    private var mustUpdate = false

    private val version: String
        get() = try {
            packageManager.getPackageInfo(packageName, 0).versionName ?: "?"
        } catch (e: Exception) { "?" }

    /** This build's versionCode — MAJOR*10000 + MINOR*100 + PATCH. */
    private val versionCode: Int
        get() = try {
            val info = packageManager.getPackageInfo(packageName, 0)
            if (Build.VERSION.SDK_INT >= 28) info.longVersionCode.toInt()
            else @Suppress("DEPRECATION") info.versionCode
        } catch (e: Exception) { 0 }

    /** Installed from Play, so Play is where an update comes from. */
    private val fromPlay: Boolean
        get() = try {
            val installer = if (Build.VERSION.SDK_INT >= 30)
                packageManager.getInstallSourceInfo(packageName).installingPackageName
            else @Suppress("DEPRECATION") packageManager.getInstallerPackageName(packageName)
            installer == "com.android.vending"
        } catch (e: Exception) { false }

    override fun onCreate(saved: Bundle?) {
        super.onCreate(saved)
        col = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            layoutDirection = View.LAYOUT_DIRECTION_LTR
            val p = Skin.dp(this@HomeActivity, 20)
            setPadding(p, Skin.dp(this@HomeActivity, 24), p, Skin.dp(this@HomeActivity, 32))
        }
        setContentView(ScrollView(this).apply {
            setBackgroundColor(Skin.BG)
            isVerticalScrollBarEnabled = false
            addView(col, ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT)
        })

        // The wordmark, the version, the one door to the settings.
        val head = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            layoutParams = LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT
            ).apply { bottomMargin = Skin.dp(this@HomeActivity, 22) }
        }
        head.addView(Skin.text(this, wordmark(), 30f, Skin.FG, heavy = true).apply {
            layoutParams = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f)
        })
        head.addView(Skin.text(this, "v$version", 13f, Skin.FAINT).apply {
            setPadding(0, 0, Skin.dp(this@HomeActivity, 14), 0)
        })
        head.addView(Skin.button(this, getString(R.string.settings)) {
            startActivity(Intent(this, SettingsActivity::class.java))
        }.apply {
            val px = Skin.dp(this@HomeActivity, 16); val py = Skin.dp(this@HomeActivity, 10)
            setPadding(px, py, px, py)
            setTextSize(android.util.TypedValue.COMPLEX_UNIT_SP, 14f)
        })
        col.addView(head)

        // A newer keyboard build, as the PC's /api/version names it (12.9):
        // one dismissible pill per version between ime_min and ime_latest,
        // a card that stays while this build is below ime_min. A tap opens
        // the store page or the release APK — the PC's URL, never a file
        // served by the PC itself.
        updateCard = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            background = Skin.pressable(this@HomeActivity, Skin.ACCENT_SOFT, Skin.CARD_HI,
                                        Skin.ACCENT_EDGE, 18)
            val p = Skin.dp(this@HomeActivity, 16)
            setPadding(p, p, p, p)
            visibility = View.GONE
            layoutParams = LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT
            ).apply { bottomMargin = Skin.dp(this@HomeActivity, 14) }
            isClickable = true
            setOnClickListener {
                if (updateUrl.isNotEmpty()) {
                    startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(updateUrl)))
                }
            }
            setOnLongClickListener {
                // A long press dismisses the pill for this version; the
                // blocking card cannot be dismissed, only acted on.
                if (!mustUpdate) {
                    Prefs.markUpdateSeen(this@HomeActivity, latestSeen)
                    visibility = View.GONE
                }
                true
            }
        }
        updateLine = Skin.text(this, "", 15f, Skin.ACCENT_TEXT, heavy = true).apply {
            layoutParams = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f)
        }
        updateCard.addView(updateLine)
        updateCard.addView(Skin.text(this, getString(R.string.install), 14f, Skin.ACCENT_TEXT))
        col.addView(updateCard)

        // The state of the link, as a lamp and a line. A tap asks again.
        val state = Skin.card(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            background = Skin.pressable(this@HomeActivity, Skin.CARD, Skin.CARD_HI)
            isClickable = true
            setOnClickListener { check() }
        }
        lamp = LampView(this).apply {
            layoutParams = LinearLayout.LayoutParams(Skin.dp(this@HomeActivity, 56),
                                                     Skin.dp(this@HomeActivity, 56))
            colour = Skin.PAUSED
            halo = false
        }
        state.addView(lamp)
        val lines = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            layoutParams = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f)
                .apply { marginStart = Skin.dp(this@HomeActivity, 14) }
        }
        stateTitle = Skin.text(this, getString(R.string.checking), 18f, Skin.FG, heavy = true)
        stateLine = Skin.text(this, "", 13f, Skin.DIM).apply {
            setPadding(0, Skin.dp(this@HomeActivity, 4), 0, 0)
        }
        lines.addView(stateTitle)
        lines.addView(stateLine)
        state.addView(lines)
        col.addView(state)

        // The three steps, while one is still red.
        stepsCard = Skin.card(this)
        col.addView(stepsCard)

        // The second reading, while anything waits.
        reviewCard = Skin.card(this).apply { visibility = View.GONE }
        col.addView(reviewCard)

        // What you said from this phone.
        saidCard = Skin.card(this)
        col.addView(saidCard)

        Notify.channel(this)
    }

    override fun onResume() {
        super.onResume()
        buildSteps()
        buildSaid()
        check()
    }

    private fun wordmark(): CharSequence {
        val s = SpannableString("DeskIT")
        s.setSpan(ForegroundColorSpan(Skin.ACCENT_TEXT), 4, 6, Spanned.SPAN_EXCLUSIVE_EXCLUSIVE)
        return s
    }

    // ---- the link ----

    private fun check() {
        val url = Prefs.url(this)
        val token = Prefs.token(this)
        if (token.isEmpty()) {
            state(Skin.PAUSED, false, getString(R.string.no_token_title),
                  getString(R.string.no_token_line))
            return
        }
        stateTitle.text = getString(R.string.checking)
        thread {
            val pcVersion = Transcriber.health(url)
            val versions = if (pcVersion != null) Transcriber.versions(url, token) else null
            val pending = if (pcVersion != null) Notify.poll(this) else null
            runOnUiThread {
                if (pcVersion == null) {
                    state(Skin.PAUSED, false, getString(R.string.unreachable_title),
                          getString(R.string.unreachable_line))
                } else {
                    state(Skin.LISTENING, true, getString(R.string.connected_title),
                          getString(R.string.connected_line, pcVersion))
                    showUpdate(versions)
                }
                buildReview(pending)
            }
        }
    }

    /**
     * 12.9's three rows, against this build's own versionCode: below
     * `ime_min` the card blocks — "update the keyboard to keep dictating"
     * — and cannot be dismissed; between `ime_min` and `ime_latest` one
     * pill, shown until a long press dismisses it for that version;
     * at `ime_latest` (or with no answer) nothing at all.
     */
    private fun showUpdate(v: Transcriber.Versions?) {
        val mine = versionCode
        if (v == null || v.imeLatest <= 0 || mine <= 0) {
            updateCard.visibility = View.GONE
            mustUpdate = false
            return
        }
        latestSeen = v.imeLatest
        updateUrl = if (fromPlay && v.playUrl.isNotEmpty()) v.playUrl else v.apkUrl
        mustUpdate = mine < v.imeMin
        val newer = mine < v.imeLatest
        val dismissed = !mustUpdate && Prefs.updateSeen(this) >= v.imeLatest
        when {
            mustUpdate -> {
                updateLine.text = getString(R.string.update_required)
                updateCard.visibility = View.VISIBLE
            }
            newer && !dismissed -> {
                updateLine.text = getString(R.string.update_on_pc, versionName(v.imeLatest))
                updateCard.visibility = View.VISIBLE
            }
            else -> updateCard.visibility = View.GONE
        }
    }

    /** 10102 -> "1.1.2": the versionCode formula, read backwards. */
    private fun versionName(code: Int): String =
        "${code / 10000}.${code / 100 % 100}.${code % 100}"

    private fun state(colour: Int, halo: Boolean, title: String, line: String) {
        lamp.colour = colour
        lamp.halo = halo
        stateTitle.text = title
        stateLine.text = line
    }

    // ---- the steps ----

    private fun hasMic() =
        checkSelfPermission(android.Manifest.permission.RECORD_AUDIO) ==
                PackageManager.PERMISSION_GRANTED

    private fun keyboardOn(): Boolean {
        val imm = getSystemService(Context.INPUT_METHOD_SERVICE) as InputMethodManager
        return imm.enabledInputMethodList.any { it.packageName == packageName }
    }

    private fun buildSteps() {
        stepsCard.removeAllViews()
        val steps = ArrayList<Triple<String, Boolean, () -> Unit>>()
        steps.add(Triple(getString(R.string.step_mic), hasMic()) {
            requestPermissions(arrayOf(android.Manifest.permission.RECORD_AUDIO), 1)
        })
        steps.add(Triple(getString(R.string.step_keyboard), keyboardOn()) {
            startActivity(Intent(Settings.ACTION_INPUT_METHOD_SETTINGS))
        })
        steps.add(Triple(getString(R.string.step_pc), Prefs.token(this).isNotEmpty()) {
            startActivity(Intent(this, SettingsActivity::class.java))
        })
        if (Build.VERSION.SDK_INT >= 33) {
            steps.add(Triple(getString(R.string.step_notify), Notify.allowed(this)) {
                requestPermissions(arrayOf("android.permission.POST_NOTIFICATIONS"), 2)
            })
        }
        if (steps.all { it.second }) { stepsCard.visibility = View.GONE; return }
        stepsCard.visibility = View.VISIBLE
        stepsCard.addView(Skin.eyebrow(this, getString(R.string.steps_title)))
        stepsCard.addView(Skin.gap(this, 6))
        for ((label, done, go) in steps) {
            val row = LinearLayout(this).apply {
                orientation = LinearLayout.HORIZONTAL
                gravity = Gravity.CENTER_VERTICAL
                setPadding(0, Skin.dp(this@HomeActivity, 10), 0, Skin.dp(this@HomeActivity, 10))
                isClickable = !done
                if (!done) setOnClickListener { go() }
            }
            row.addView(View(this).apply {
                background = Skin.face(this@HomeActivity,
                    if (done) Skin.GREEN else Skin.ACCENT, radius = 6, stroke = 0)
                layoutParams = LinearLayout.LayoutParams(Skin.dp(this@HomeActivity, 10),
                                                         Skin.dp(this@HomeActivity, 10))
                    .apply { marginEnd = Skin.dp(this@HomeActivity, 14) }
            })
            row.addView(Skin.text(this, label, 16f, if (done) Skin.DIM else Skin.FG).apply {
                layoutParams = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f)
            })
            row.addView(Skin.text(this, if (done) "✓" else "→", 16f,
                                  if (done) Skin.GREEN else Skin.ACCENT_TEXT))
            stepsCard.addView(row)
        }
    }

    override fun onRequestPermissionsResult(
        requestCode: Int, permissions: Array<out String>, grantResults: IntArray
    ) {
        if (requestCode == 1) {
            val ok = grantResults.firstOrNull() == PackageManager.PERMISSION_GRANTED
            Toast.makeText(this, getString(
                if (ok) R.string.mic_granted else R.string.mic_denied), Toast.LENGTH_LONG).show()
        }
        buildSteps()
    }

    // ---- the second reading ----

    private fun buildReview(items: List<Transcriber.Proposal>?) {
        reviewCard.removeAllViews()
        if (items.isNullOrEmpty()) { reviewCard.visibility = View.GONE; return }
        reviewCard.visibility = View.VISIBLE
        reviewCard.addView(Skin.eyebrow(this, getString(R.string.second_reading)))
        reviewCard.addView(Skin.gap(this, 4))
        for (p in items) {
            val row = LinearLayout(this).apply {
                orientation = LinearLayout.VERTICAL
                setPadding(0, Skin.dp(this@HomeActivity, 10), 0, Skin.dp(this@HomeActivity, 10))
                isClickable = true
                setOnClickListener {
                    startActivity(Intent(this@HomeActivity, ReviewActivity::class.java)
                        .putExtra(Notify.EXTRA_ID, p.id))
                }
            }
            row.addView(Skin.text(this, p.proposed, 16f, Skin.FG).apply {
                maxLines = 2
                ellipsize = android.text.TextUtils.TruncateAt.END
                textDirection = View.TEXT_DIRECTION_ANY_RTL
                layoutParams = LinearLayout.LayoutParams(
                    ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT)
            })
            row.addView(Skin.text(this, getString(R.string.did_you_mean_row,
                getString(if (p.fromPhone) R.string.the_phone else R.string.the_desk)),
                12f, Skin.ACCENT_TEXT).apply {
                setPadding(0, Skin.dp(this@HomeActivity, 4), 0, 0)
            })
            reviewCard.addView(row)
        }
    }

    // ---- what you said ----

    private fun buildSaid() {
        saidCard.removeAllViews()
        val head = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
        }
        head.addView(Skin.eyebrow(this, getString(R.string.said_title)).apply {
            layoutParams = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f)
        })
        val rows = Prefs.said(this)
        if (rows.isNotEmpty()) head.addView(
            Skin.text(this, getString(R.string.clear), 12f, Skin.FAINT).apply {
                isClickable = true
                setOnClickListener { Prefs.clearSaid(this@HomeActivity); buildSaid() }
            })
        saidCard.addView(head)
        saidCard.addView(Skin.gap(this, 6))
        if (rows.isEmpty()) {
            saidCard.addView(Skin.text(this, getString(R.string.said_empty), 15f, Skin.DIM).apply {
                setPadding(0, Skin.dp(this@HomeActivity, 8), 0, Skin.dp(this@HomeActivity, 4))
            })
            return
        }
        val today = SimpleDateFormat("yyyy-MM-dd", Locale.US)
        val clock = SimpleDateFormat("HH:mm", Locale.US)
        val day = SimpleDateFormat("d MMM · HH:mm", Locale.US)
        val now = today.format(Date())
        for ((t, s) in rows) {
            val stamp = Date(t)
            val row = LinearLayout(this).apply {
                orientation = LinearLayout.VERTICAL
                setPadding(0, Skin.dp(this@HomeActivity, 10), 0, Skin.dp(this@HomeActivity, 10))
                isClickable = true
                setOnClickListener {
                    (getSystemService(CLIPBOARD_SERVICE) as ClipboardManager)
                        .setPrimaryClip(ClipData.newPlainText("DeskIT", s))
                    Toast.makeText(this@HomeActivity, getString(R.string.copied),
                                   Toast.LENGTH_SHORT).show()
                }
            }
            row.addView(Skin.text(this,
                if (today.format(stamp) == now) clock.format(stamp) else day.format(stamp),
                12f, Skin.FAINT))
            row.addView(Skin.text(this, s, 16f, Skin.FG).apply {
                maxLines = 4
                ellipsize = android.text.TextUtils.TruncateAt.END
                textDirection = View.TEXT_DIRECTION_ANY_RTL
                layoutParams = LinearLayout.LayoutParams(
                    ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT)
                setPadding(0, Skin.dp(this@HomeActivity, 4), 0, 0)
                setLineSpacing(0f, 1.2f)
            })
            saidCard.addView(row)
        }
    }
}
