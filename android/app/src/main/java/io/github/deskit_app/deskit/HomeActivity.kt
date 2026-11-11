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
import android.widget.TextView
import android.widget.Toast
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import kotlin.concurrent.thread

/**
 * What opens from the icon: a small home, not a form.
 *
 * Top to bottom — a pill when the PC holds a newer build; the state of the
 * link to the PC as a lamp and a word, or, while this phone's join waits, the
 * code to compare and its press; only the set-up steps that are left;
 * the second reading's proposals while any wait; and the last things you
 * said from this phone, a tap to copy.
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
    /** The account's line among the steps, as the last look left it. */
    private var accountStep = R.string.step_sign_in
    private var accountDone = false
    /** The link's card, which stands aside while the code is shown. */
    private lateinit var stateCard: View
    /**
     * The code screen's own card while this phone's join waits, null otherwise: the
     * code where the person looks, not behind a step (M17).
     */
    private var codeCard: View? = null
    /** What [codeCard] shows: a poll that finds the same draws nothing, and takes no focus. */
    private var codeDrawn = ""
    /** The code a press is out on: a look that left before the press does not undo it. */
    private var pressing = ""
    private var resumed = false
    /** While the join waits, Home looks again as the code screen does, and only while it is up. */
    private val lookAgain = Runnable { lookAtAccount() }
    /** [Traces.wipes] as of what this page last drew. */
    private var traces = Traces.wipes
    /**
     * The first moments of a phone are this page saying a PC cannot be reached,
     * while that PC hears of the phone, and Windows asks him about its first door. So
     * while the page is up and nobody answers, it asks again by itself.
     */
    private val again = Runnable { check(quietly = true) }

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
        col = Skin.page(this)

        // The wordmark and the one door to the settings.
        val head = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            layoutParams = LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT
            ).apply { bottomMargin = Skin.dp(this@HomeActivity, 18) }
        }
        head.addView(Skin.title(this, wordmark(), 30f).apply {
            layoutParams = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f)
        })
        head.addView(Skin.smallButton(this, getString(R.string.settings)) {
            startActivity(Intent(this, SettingsActivity::class.java))
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
            background = Glass(this@HomeActivity, Skin.GLASS_LEAD)
            val p = Skin.dp(this@HomeActivity, 16)
            setPadding(p, p, p, p)
            visibility = View.GONE
            layoutParams = LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT
            ).apply { bottomMargin = Skin.dp(this@HomeActivity, 12) }
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
            isClickable = true
            setOnClickListener { check() }
        }
        lamp = LampView(this).apply {
            layoutParams = LinearLayout.LayoutParams(Skin.dp(this@HomeActivity, 44),
                                                     Skin.dp(this@HomeActivity, 44))
            colour = Skin.PAUSED
            halo = false
        }
        state.addView(lamp)
        val lines = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            layoutParams = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f)
                .apply { marginStart = Skin.dp(this@HomeActivity, 14) }
        }
        stateTitle = Skin.title(this, getString(R.string.checking), 19f)
        stateLine = Skin.text(this, "", 14f, Skin.DIM).apply {
            setPadding(0, Skin.dp(this@HomeActivity, 4), 0, 0)
            visibility = View.GONE
        }
        lines.addView(stateTitle)
        lines.addView(stateLine)
        state.addView(lines)
        col.addView(state)
        stateCard = state

        // The steps, while one is still left.
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
        resumed = true
        Account.settle(this)
        // A recording's hour is up at whatever opens first.
        val app = applicationContext
        thread { Spool.prune(app) }
        traces = Traces.wipes
        accountDone = Lock.holdsKey(this)
        buildSteps()
        buildSaid()
        check()
        lookAtAccount()
    }

    override fun onPause() {
        super.onPause()
        resumed = false
        col.removeCallbacks(again)
        col.removeCallbacks(lookAgain)
    }

    override fun onWindowFocusChanged(hasFocus: Boolean) {
        super.onWindowFocusChanged(hasFocus)
        if (hasFocus) Traces.focused(this)
    }

    /** The page as this phone stands now, after the words went: [Traces]. */
    private fun redrawIfWiped() {
        if (traces == Traces.wipes) return
        traces = Traces.wipes
        buildSaid()
        check()
    }

    /** Where the account stands, on a thread: the first step's words and dot, or the code. */
    private fun lookAtAccount() {
        col.removeCallbacks(lookAgain)
        thread {
            val st = Lock.look(this)
            runOnUiThread { account(st) }
        }
    }

    /** What a look or a press found. On the main thread. */
    private fun account(st: Lock.State) {
        redrawIfWiped()
        // No answer, or Keystore said no: that says nothing about the account, so
        // the step keeps its words and a code on screen stays. The page says what is wrong.
        if (st !is Lock.State.NotNow && st !is Lock.State.Trouble) {
            val had = codeCard != null
            accountDone = st is Lock.State.Ready
            accountStep = when (st) {
                is Lock.State.SignedOut, is Lock.State.Ready -> R.string.step_sign_in
                is Lock.State.NoLock -> R.string.no_lock_title
                is Lock.State.Changed -> R.string.step_changed
                is Lock.State.Declined -> R.string.declined_title
                else -> R.string.step_approve
            }
            showCode(st as? Lock.State.Waiting)
            buildSteps()
            if (had && codeCard == null) check(quietly = true)   // the join is done, or gone
        }
        if (codeCard != null && resumed) col.postDelayed(lookAgain, Lock.POLL_MS)
    }

    /**
     * While this phone's join waits, Home's first row is the code screen's own card
     * ([AccountScreens.waitingCard]), and the link's card stands aside: there is no
     * PC to reach before the join is done.
     */
    private fun showCode(waiting: Lock.State.Waiting?) {
        // A look that left before the press reads the press as not yet made.
        val st = if (waiting != null && waiting.code == pressing && !waiting.pressed)
            Lock.State.Waiting(waiting.code, waiting.email, waiting.word, true) else waiting
        val key = if (st == null) "" else "${st.code}:${st.word}:${st.pressed}"
        if (key == codeDrawn) return
        codeDrawn = key
        codeCard?.let { col.removeView(it) }
        codeCard = null
        if (st == null) {
            stateCard.visibility = View.VISIBLE
            return
        }
        val card = AccountScreens(this).waitingCard(st.code, st.word, st.pressed) { same(st) }
        stateCard.visibility = View.GONE
        col.addView(card, col.indexOfChild(stateCard))
        codeCard = card
    }

    /** The code screen's press, on the code shown: [Lock.sameCode], answered at once on screen. */
    private fun same(st: Lock.State.Waiting) {
        pressing = st.code
        showCode(Lock.State.Waiting(st.code, st.email, st.word, true))
        col.removeCallbacks(lookAgain)
        thread {
            val after = Lock.sameCode(this, st.code)
            runOnUiThread {
                pressing = ""
                account(after)
            }
        }
    }

    private fun wordmark(): CharSequence {
        val s = SpannableString("DeskIT")
        s.setSpan(ForegroundColorSpan(Skin.ACCENT_TEXT), 4, 6, Spanned.SPAN_EXCLUSIVE_EXCLUSIVE)
        return s
    }

    // ---- the link ----

    private fun check(quietly: Boolean = false) {
        col.removeCallbacks(again)
        if (!Link.ready(this)) {
            state(Skin.PAUSED, false, getString(R.string.no_token_title), "")
            buildReview(null)
            return
        }
        if (!quietly) stateTitle.text = getString(R.string.checking)
        val wipes = Traces.wipes
        thread {
            var word = getString(R.string.unreachable_line)
            var locked = false
            val reached = try {
                Link.reach(this)
            } catch (e: Sealed.NotNow) {
                word = Sealed.words(this, e)    // the phone, and nothing about the PC
                locked = true
                null
            }
            // In the account, and no PC of it has a door for this phone yet: there
            // was nothing to reach, which is not connected yet, not can't reach.
            val none = reached == null && !locked && Link.pasted(this) == null && try {
                Link.pcs(this).isEmpty()
            } catch (e: Sealed.NotNow) {
                false
            }
            val versions = if (reached != null) Link.versions(this) else null
            val pending = if (reached != null) Notify.poll(this) else null
            // A recording that did not reach the PC is the keyboard's to offer: Home sends nothing.
            runOnUiThread {
                if (wipes != Traces.wipes) return@runOnUiThread
                if (reached == null) {
                    if (none) state(Skin.PAUSED, false, getString(R.string.no_token_title), "")
                    else state(Skin.PAUSED, false, getString(R.string.unreachable_title), word)
                    if (!isFinishing) col.postDelayed(again, AGAIN_MS)
                } else {
                    state(Skin.LISTENING, true, getString(R.string.connected_title), "")
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
        stateLine.visibility = if (line.isEmpty()) View.GONE else View.VISIBLE
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
        // While the code is shown, the card is this step.
        steps.add(Triple(getString(accountStep), accountDone || codeCard != null) {
            startActivity(Intent(this, AccountActivity::class.java))
        })
        steps.add(Triple(getString(R.string.step_mic), hasMic()) {
            requestPermissions(arrayOf(android.Manifest.permission.RECORD_AUDIO), 1)
        })
        steps.add(Triple(getString(R.string.step_keyboard), keyboardOn()) {
            startActivity(Intent(Settings.ACTION_INPUT_METHOD_SETTINGS))
        })
        if (Build.VERSION.SDK_INT >= 33) {
            steps.add(Triple(getString(R.string.step_notify), Notify.allowed(this)) {
                requestPermissions(arrayOf("android.permission.POST_NOTIFICATIONS"), 2)
            })
        }
        // Only what is left to do. A step that is done leaves the page.
        val left = steps.filter { !it.second }
        stepsCard.visibility = if (left.isEmpty()) View.GONE else View.VISIBLE
        for ((label, _, go) in left) {
            val row = LinearLayout(this).apply {
                orientation = LinearLayout.HORIZONTAL
                gravity = Gravity.CENTER_VERTICAL
                setPadding(0, Skin.dp(this@HomeActivity, 10), 0, Skin.dp(this@HomeActivity, 10))
                isClickable = true
                setOnClickListener { go() }
            }
            row.addView(View(this).apply {
                background = Skin.face(this@HomeActivity, Skin.ACCENT, radius = 6, stroke = 0)
                layoutParams = LinearLayout.LayoutParams(Skin.dp(this@HomeActivity, 8),
                                                         Skin.dp(this@HomeActivity, 8))
                    .apply { marginEnd = Skin.dp(this@HomeActivity, 14) }
            })
            row.addView(Skin.text(this, label, 15f, Skin.FG).apply {
                typeface = Skin.fontLabel(this@HomeActivity)
                layoutParams = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f)
            })
            row.addView(Skin.text(this, "›", 19f, Skin.MUTED))
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
        reviewCard.addView(Skin.eyebrow(this, getString(R.string.did_you_mean)))
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
            reviewCard.addView(row)
        }
    }

    // ---- what you said ----

    private companion object {
        /** A knock while the page is up: the page is what is spending it. */
        const val AGAIN_MS = 8000L
    }

    private fun buildSaid() {
        saidCard.removeAllViews()
        // Nothing said yet is nothing to show.
        saidCard.visibility = if (Prefs.said(this).isEmpty()) View.GONE else View.VISIBLE
        val head = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
        }
        head.addView(Skin.eyebrow(this, getString(R.string.said_title)).apply {
            layoutParams = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f)
        })
        val rows = Prefs.said(this)
        if (rows.isNotEmpty()) head.addView(
            Skin.link(this, getString(R.string.clear)) {
                Prefs.clearSaid(this@HomeActivity)
                Skin.settle(col)
                buildSaid()
            })
        saidCard.addView(head)
        saidCard.addView(Skin.gap(this, 6))
        if (rows.isEmpty()) return
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
                        .setPrimaryClip(ClipData.newPlainText(Traces.CLIP, s))
                    Toast.makeText(this@HomeActivity, getString(R.string.copied),
                                   Toast.LENGTH_SHORT).show()
                }
            }
            row.addView(Skin.text(this,
                if (today.format(stamp) == now) clock.format(stamp) else day.format(stamp),
                12f, Skin.MUTED))
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
