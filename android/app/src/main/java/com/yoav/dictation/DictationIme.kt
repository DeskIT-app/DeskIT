package com.yoav.dictation

import android.content.ClipData
import android.content.Intent
import android.content.pm.PackageManager
import android.content.res.Configuration
import android.graphics.Color
import android.graphics.drawable.GradientDrawable
import android.inputmethodservice.InputMethodService
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.text.InputType
import android.text.TextUtils
import android.util.TypedValue
import android.view.Gravity
import android.view.DragEvent
import android.view.HapticFeedbackConstants
import android.view.KeyEvent
import android.view.MotionEvent
import android.view.View
import android.view.ViewGroup
import android.view.inputmethod.EditorInfo
import android.view.inputmethod.InputConnection
import android.widget.LinearLayout
import android.widget.TextView
import java.util.Locale
import kotlin.concurrent.thread

/**
 * A keyboard that is one microphone button and the few keys you need to
 * finish a sentence.
 *
 * This is the only kind of app Android lets put text into someone else's
 * text field, which is the whole point: a floating button or a Quick
 * Settings tile can record just fine, but neither can do anything with the
 * result except leave it on the clipboard. Here the transcript is
 * committed straight into whatever field has the cursor, in any app.
 *
 * Recording happens on the phone; transcription happens on the PC, over
 * Tailscale, on the Hebrew fine-tune that lives there. A phone cannot run
 * that model at a useful speed, and its accuracy is the point of the whole
 * project.
 *
 * IT IS STILL NOT THE KEYBOARD YOU LIVE IN. There is no letter grid and
 * there will not be one. What the second row buys is the two things
 * dictating into someone else's app actually needs and could not do at
 * all: FINISH what you dictated — the action key, which is Send in a chat,
 * Search in a search box, a newline in a note — and FIX it, with a space,
 * a full stop, undo and punctuation. Both of those cost two keyboard
 * switches before this, on every single message.
 *
 * The face is in English deliberately. It sits directly under a Hebrew
 * text field, and two scripts in one glance is harder to read, not easier.
 *
 * THE LOOK IS THE DESKTOP'S (Skin.kt): LAMPLIGHT's colours and Rubik, on
 * shapes cut for a thumb. The microphone is a pill holding the desktop's
 * status dot as a lamp — listening blue, recording red, locked red and
 * breathing, transcribing gold, grey with no halo when the PC cannot be
 * reached — so the corner of the desk and the bottom of the phone say the
 * same thing in the same colour.
 */
class DictationIme : InputMethodService() {

    private val recorder = Recorder()
    private val ui = Handler(Looper.getMainLooper())

    /** The whole microphone: the lamp, the label and the level line. */
    private lateinit var pill: LinearLayout
    private lateinit var lamp: LampView
    private lateinit var button: TextView
    private lateinit var levelTrack: LinearLayout
    private lateinit var levelFill: View
    private lateinit var status: TextView
    private lateinit var backspace: TextView
    private lateinit var actionKey: TextView
    private lateinit var row1: LinearLayout
    private lateinit var row2: LinearLayout

    /** Every small key by its stable id, in [Prefs.DEFAULT_ORDER]'s ids. */
    private val keyViews = LinkedHashMap<String, TextView>()

    /**
     * Arrange mode: the keys stop doing their jobs and become movable.
     *
     * Entered by holding any key that has no long-press job of its own —
     * backspace holds to repeat, the period holds for a comma and the
     * action key holds for a real Enter, so those three cannot also hold
     * to arrange. They still MOVE like every other key: dragging any key
     * onto them swaps the pair, which reaches every possible layout.
     */
    private var arranging = false

    private var busy = false
    private var holding = false
    private var locked = false
    private var downY = 0f
    private var gestured = false

    /**
     * What the field being typed into said about itself.
     *
     * Read rather than ignored, which it was until now, and three separate
     * things depend on it: the action key's face, whether Enter means "go"
     * or "new line", and whether this is a field where dictating is a bad
     * idea in the first place.
     */
    private var editor: EditorInfo? = null

    /**
     * Bumped every time the cursor lands in a DIFFERENT field.
     *
     * Captured before a request goes out and compared when it comes back: a
     * transcript that took four seconds has to land in the field it was
     * spoken into, or nowhere. Committing it into whatever happens to hold
     * the cursor writes into text the user never meant to touch — and a
     * translation, which replaces the whole field, is worse again.
     */
    private var session = 0

    /** A password or an explicitly private field. See [isPrivate]. */
    private var privateField = false

    /** The EditorInfo action to fire, or 0 for "Enter means a newline". */
    private var actionId = 0

    /** Exactly what this keyboard last put in the field, for undo. */
    private var lastInsert: String? = null

    /** The last recording, kept so a failure can be retried, not respoken. */
    private var lastWav: ByteArray? = null

    /** Text that arrived after its field went away; offered, never forced. */
    private var pending: String? = null

    /** An error stays up until something succeeds, instead of being wiped. */
    private var sticky = false
    private var statusAction: (() -> Unit)? = null

    private var backendName = ""
    private var lastHealth = 0L

    /** Every repeating key's Runnable, so nothing is left ticking. */
    private val repeats = ArrayList<Runnable>()

    /**
     * Whether the PC answered the last /health. Decides what idle looks
     * like: the listening blue when it did, the paused grey — no halo —
     * when it did not, which is the desktop dot's own rule for "off".
     */
    private var reachable = true

    private val idleColor: Int
        get() = if (reachable) Skin.LISTENING else Skin.PAUSED
    private val recColor = Skin.RECORDING
    private val lockColor = Skin.LOCKED
    private val busyColor = Skin.TRANSCRIBING
    private val keyText = Skin.FG
    private val statusText = Skin.DIM
    private val errorText = Skin.RED

    /** The review polls after a dictation, so a rebuild can drop them. */
    private val polls = ArrayList<Runnable>()

    /** Drag distance that means "lock it on", or "throw it away". */
    private val lockDistance by lazy { dp(48).toFloat() }

    private fun dp(v: Int): Int = TypedValue.applyDimension(
        TypedValue.COMPLEX_UNIT_DIP, v.toFloat(), resources.displayMetrics
    ).toInt()

    private val landscape: Boolean
        get() = resources.configuration.orientation ==
                Configuration.ORIENTATION_LANDSCAPE

    // ---- the view ----

    /**
     * The vertical budget, because it is what decides everything else.
     *
     * Portrait: 12 padding + 100 mic + 11 level + 30 status + 48 row + 6
     * gap + 48 row + 14 padding = 269 of 272dp. The mic came down from
     * 124dp to make room for the second row, and at 100dp it is still
     * several times the size of any key on any keyboard — it was never a
     * button that had to be found by looking.
     *
     * Landscape is a different problem: the keyboard competes with a screen
     * that is mostly gone already, so the mic shrinks again and the level
     * bar goes. That has to move together with [onEvaluateFullscreenMode]
     * and not separately.
     */
    override fun onCreateInputView(): View {
        // The framework rebuilds this view on every configuration change,
        // so anything held across builds has to be dropped here or it
        // accumulates one stale copy per rotation.
        for (r in repeats) ui.removeCallbacks(r)
        repeats.clear()
        // A rotation mid-arrange lands here too: the fresh build below is
        // a normal keyboard, so the flag must not claim otherwise.
        arranging = false

        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            gravity = Gravity.CENTER
            setBackgroundColor(Skin.BG)
            setPadding(dp(14), dp(12), dp(14), dp(14))
            // The row order is this keyboard's own, not the phone's. With
            // supportsRtl on, a Hebrew-locale phone mirrors these rows and
            // puts backspace where the user learned the switch key was —
            // the same ambiguity the English face exists to avoid.
            layoutDirection = View.LAYOUT_DIRECTION_LTR
            layoutParams = ViewGroup.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                dp(if (landscape) 210 else 272)
            )
        }

        // The microphone is a pill: the lamp on the left, the label beside
        // it, the level line along the bottom. The whole face is the
        // button — at 100dp it is still several times the size of any key
        // on any keyboard, and it was never a button found by looking.
        pill = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            gravity = Gravity.CENTER
            contentDescription = getString(R.string.cd_mic)
            background = Skin.face(this@DictationIme, Skin.CARD, Skin.LINE, 28)
            setPadding(dp(22), dp(10), dp(22), dp(10))
            isClickable = true
            isFocusable = true
            layoutParams = LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                dp(if (landscape) 56 else 100)
            )
        }
        val face = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            layoutParams = LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f)
        }
        lamp = LampView(this).apply {
            val side = dp(if (landscape) 32 else 48)
            layoutParams = LinearLayout.LayoutParams(side, side).apply {
                marginEnd = dp(14)
            }
        }
        face.addView(lamp)
        button = TextView(this).apply {
            text = getString(R.string.hold_and_talk)
            typeface = Skin.fontBold(this@DictationIme)
            includeFontPadding = false
            gravity = Gravity.START or Gravity.CENTER_VERTICAL
            setTextColor(Skin.FG)
            setTextSize(TypedValue.COMPLEX_UNIT_SP, if (landscape) 16f else 19f)
            maxLines = 1
            ellipsize = TextUtils.TruncateAt.END
            layoutParams = LinearLayout.LayoutParams(
                0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f)
        }
        face.addView(button)
        pill.addView(face)

        // The level line. Not decoration: without it the only evidence the
        // microphone is live is that a lamp turned red, and a microphone
        // another app is holding looks exactly like a working one.
        levelTrack = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            background = Skin.face(this@DictationIme, Skin.PANE, radius = 2, stroke = 0)
            visibility = View.INVISIBLE
            layoutParams = LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, dp(3)
            ).apply { topMargin = dp(6) }
        }
        levelFill = View(this).apply {
            background = Skin.face(this@DictationIme, Skin.ACCENT, radius = 2, stroke = 0)
            layoutParams = LinearLayout.LayoutParams(
                0, ViewGroup.LayoutParams.MATCH_PARENT
            )
        }
        levelTrack.addView(levelFill)
        if (!landscape) pill.addView(levelTrack)
        root.addView(pill)

        status = TextView(this).apply {
            gravity = Gravity.CENTER
            typeface = Skin.font(this@DictationIme)
            includeFontPadding = false
            setTextColor(statusText)
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 13f)
            setPadding(0, dp(8), 0, dp(6))
            // Server errors are whole sentences. Unbounded, they wrap to
            // three lines and push the key rows out of a fixed-height view.
            maxLines = 2
            ellipsize = TextUtils.TruncateAt.END
            // This is the only feedback channel the keyboard has. Without
            // this line TalkBack never speaks a word of it.
            accessibilityLiveRegion = View.ACCESSIBILITY_LIVE_REGION_POLITE
            isClickable = true
            setOnClickListener { statusAction?.invoke() }
        }
        root.addView(status)

        backspace = repeatKey()

        // Built by id, laid out by the saved order: the user can hold a
        // key and drag the eight of them into any arrangement they like,
        // and it has to survive rotation and reinstalls of the view.
        keyViews.clear()
        keyViews["backspace"] = backspace
        keyViews["space"] = key(R.string.space_btn, R.string.cd_space, 19f) {
            // A key event rather than commitText(" "), for the same reason
            // backspace is one: the host editor gets to treat it as a word
            // boundary, and its own autocorrect behaves.
            sendDownUpKeyEvents(KeyEvent.KEYCODE_SPACE)
        }
        keyViews["period"] = key(R.string.period_btn, R.string.cd_period, 17f,
            onLong = { commit(",") }) { commit(".") }
        keyViews["undo"] = key(R.string.undo_btn, R.string.cd_undo, 19f) { undo() }
        keyViews["translate"] = key(R.string.translate_btn, R.string.cd_translate, 14f) {
            translateField()
        }
        keyViews["punctuate"] = key(R.string.punctuate_btn, R.string.cd_punctuate, 14f) {
            punctuateField()
        }
        actionKey = key(R.string.act_enter, R.string.act_enter, 15f,
            primary = true,
            // Some apps never listen for performEditorAction and take only
            // a real Enter, and there is no way to ask in advance. A long
            // press is the way out of that, rather than a key that looks
            // like it did nothing.
            onLong = { sendDownUpKeyEvents(KeyEvent.KEYCODE_ENTER) }) {
            fireAction()
        }
        keyViews["action"] = actionKey
        keyViews["switch"] = key(R.string.back_to_keyboard, R.string.cd_switch, 19f) {
            goBack()
        }

        row1 = row()
        row2 = row()
        (row2.layoutParams as LinearLayout.LayoutParams).topMargin = dp(6)
        layoutKeys()
        root.addView(row1)
        root.addView(row2)

        pill.setOnTouchListener { v, e ->
            when (e.action) {
                MotionEvent.ACTION_DOWN -> {
                    downY = e.rawY; gestured = false
                    press(v); true
                }
                MotionEvent.ACTION_MOVE -> { gesture(v, e.rawY); true }
                MotionEvent.ACTION_UP, MotionEvent.ACTION_CANCEL -> {
                    // Locked recordings survive the finger leaving; the next
                    // tap is what ends them. A discard gesture has already
                    // dealt with the recording, so this must not send it.
                    if (!locked && !gestured) {
                        release(e.action == MotionEvent.ACTION_CANCEL)
                    }
                    true
                }
                else -> false
            }
        }
        // The touch listener above consumes every real touch, so this only
        // ever fires from an accessibility service — which cannot hold a
        // button down. Tap to start, tap again to finish: the same shape as
        // a locked recording, which is the one mode a click can drive.
        pill.setOnClickListener {
            if (busy) return@setOnClickListener
            if (locked) finishLocked() else if (!holding) startLocked()
        }

        // A rebuilt view — rotation, a theme change — must not claim the
        // app is idle while a recording or a request is still in flight.
        restoreState()
        return root
    }

    /**
     * Never take the screen over with an extracted editor.
     *
     * Left at its default, the framework goes fullscreen in landscape: the
     * host app's field is replaced by the IME's own proxy, and every read
     * and write below — the translate and punctuate keys especially — then
     * talks to that proxy instead of to the app. Paired deliberately with
     * the short landscape height above: turning this off is right for a
     * keyboard that leaves room and wrong for one that does not.
     */
    override fun onEvaluateFullscreenMode(): Boolean = false

    private fun row(): LinearLayout = LinearLayout(this).apply {
        orientation = LinearLayout.HORIZONTAL
        gravity = Gravity.CENTER
        layoutDirection = View.LAYOUT_DIRECTION_LTR
        layoutParams = LinearLayout.LayoutParams(
            ViewGroup.LayoutParams.MATCH_PARENT, dp(48)
        )
    }

    /**
     * One key. Four to a row and no more: at 320dp wide that is 50dp of
     * touch target each, and a fifth would put every one of them under the
     * 48dp minimum.
     */
    private fun key(
        face: Int, desc: Int, size: Float,
        primary: Boolean = false,
        onLong: (() -> Unit)? = null,
        onTap: () -> Unit,
    ): TextView = TextView(this).apply {
        text = getString(face)
        contentDescription = getString(desc)
        gravity = Gravity.CENTER
        typeface = if (primary) Skin.fontBold(this@DictationIme) else Skin.font(this@DictationIme)
        includeFontPadding = false
        setTextColor(if (primary) Skin.ACCENT_ON else keyText)
        setTextSize(TypedValue.COMPLEX_UNIT_SP, size)
        isFocusable = true
        // The action key is the ONE gold thing on this surface — the
        // primary action, the same rule every desktop surface keeps.
        background = if (primary) Skin.primaryFace(this@DictationIme, 14)
                     else Skin.secondaryFace(this@DictationIme, 14)
        layoutParams = LinearLayout.LayoutParams(0, dp(48), 1f).apply {
            marginStart = dp(4); marginEnd = dp(4)
        }
        setOnClickListener {
            it.performHapticFeedback(HapticFeedbackConstants.KEYBOARD_TAP)
            onTap()
        }
        if (onLong != null) setOnLongClickListener {
            it.performHapticFeedback(HapticFeedbackConstants.LONG_PRESS)
            onLong()
            true
        } else setOnLongClickListener {
            // Every key without a long-press job of its own is a handle
            // into arrange mode. See [arranging] for why not all eight.
            it.performHapticFeedback(HapticFeedbackConstants.LONG_PRESS)
            enterArrange()
            true
        }
    }

    // ---- moving the keys around ----

    /** Empties both rows and refills them from the saved order. */
    private fun layoutKeys() {
        row1.removeAllViews()
        row2.removeAllViews()
        for ((i, id) in Prefs.keyOrder(this).withIndex()) {
            val v = keyViews.getValue(id)
            (v.parent as? ViewGroup)?.removeView(v)
            (if (i < 4) row1 else row2).addView(v)
        }
    }

    /**
     * The keys keep their faces and places but trade their jobs for one:
     * being dragged. Press one and it lifts immediately — the long press
     * was spent getting here, demanding another inside the mode would
     * teach that the mode is broken. Dropping it on a sibling swaps the
     * pair, which is the reorder that never surprises: exactly two keys
     * move, both of them chosen.
     *
     * The way out is the microphone, relabeled Done — and leaving simply
     * throws this view away and builds a fresh one, the same path a
     * rotation takes, so every listener this mode replaced comes back
     * without a list of what they were.
     */
    private fun enterArrange() {
        if (arranging || holding || locked || busy) return
        arranging = true
        for ((id, v) in keyViews) {
            v.setOnLongClickListener(null)
            v.setOnClickListener { }
            v.setOnTouchListener { view, e ->
                if (e.action == MotionEvent.ACTION_DOWN) {
                    view.performHapticFeedback(HapticFeedbackConstants.LONG_PRESS)
                    view.startDragAndDrop(
                        ClipData.newPlainText("key", id),
                        View.DragShadowBuilder(view), id, 0)
                    view.alpha = 0.35f
                }
                true
            }
            v.setOnDragListener { view, e ->
                when (e.action) {
                    DragEvent.ACTION_DRAG_STARTED -> true
                    DragEvent.ACTION_DRAG_ENTERED -> {
                        if (e.localState != id) view.alpha = 0.6f; true
                    }
                    DragEvent.ACTION_DRAG_EXITED -> {
                        if (e.localState != id) view.alpha = 1f; true
                    }
                    DragEvent.ACTION_DROP -> {
                        val from = e.localState as? String
                        if (from != null && from != id) {
                            val order = Prefs.keyOrder(this).toMutableList()
                            val a = order.indexOf(from)
                            val b = order.indexOf(id)
                            order[a] = id
                            order[b] = from
                            Prefs.saveKeyOrder(this, order)
                            say(getString(R.string.arrange_saved))
                        }
                        true
                    }
                    DragEvent.ACTION_DRAG_ENDED -> {
                        // Also the landing spot for a drag let go over the
                        // mic or nowhere: everything opaque, nothing moved.
                        for (k in keyViews.values) k.alpha = 1f
                        // Off the drag dispatch: relaying out re-parents
                        // the very views the ended event is walking.
                        ui.post { if (arranging) layoutKeys() }
                        true
                    }
                    else -> false
                }
            }
        }
        button.text = getString(R.string.arrange_done)
        pill.contentDescription = getString(R.string.arrange_done)
        pill.setOnTouchListener(null)
        pill.setOnClickListener { exitArrange() }
        status.text = getString(R.string.arrange_hint)
        status.contentDescription = getString(R.string.cd_arrange)
    }

    private fun exitArrange() {
        arranging = false
        setInputView(onCreateInputView())
    }

    /**
     * Backspace, with hold-to-repeat: fixing one wrong letter must not mean
     * switching keyboards.
     *
     * Sent as a DEL key event rather than deleteSurroundingText(1, 0),
     * because the latter counts UTF-16 units and would cut an emoji in
     * half; the key event lets the editor do its own grapheme-aware delete,
     * and it clears a selection too.
     *
     * While a recording is LOCKED this same key becomes the way out of it.
     * There is no finger on the microphone to gesture with then, and until
     * now the only end to a locked recording was one that also sent it.
     */
    private fun repeatKey(): TextView = TextView(this).apply {
        text = getString(R.string.backspace_btn)
        contentDescription = getString(R.string.cd_backspace)
        gravity = Gravity.CENTER
        typeface = Skin.font(this@DictationIme)
        includeFontPadding = false
        setTextColor(keyText)
        setTextSize(TypedValue.COMPLEX_UNIT_SP, 19f)
        isFocusable = true
        background = Skin.secondaryFace(this@DictationIme, 14)
        layoutParams = LinearLayout.LayoutParams(0, dp(48), 1f).apply {
            marginStart = dp(4); marginEnd = dp(4)
        }
        val repeat = object : Runnable {
            override fun run() {
                sendDownUpKeyEvents(KeyEvent.KEYCODE_DEL)
                ui.postDelayed(this, 50)
            }
        }
        repeats.add(repeat)
        setOnTouchListener { v, e ->
            when (e.action) {
                MotionEvent.ACTION_DOWN -> {
                    v.performHapticFeedback(HapticFeedbackConstants.KEYBOARD_TAP)
                    if (locked) discard()
                    else {
                        sendDownUpKeyEvents(KeyEvent.KEYCODE_DEL)
                        ui.postDelayed(repeat, 350)
                    }
                    true
                }
                MotionEvent.ACTION_UP, MotionEvent.ACTION_CANCEL -> {
                    ui.removeCallbacks(repeat); true
                }
                else -> false
            }
        }
        setOnClickListener { }   // so an accessibility service can operate it
    }

    // ---- what field is this? ----

    override fun onStartInputView(info: EditorInfo?, restarting: Boolean) {
        super.onStartInputView(info, restarting)
        // Landing in a new field mid-arrange: the mode's disabled keys
        // must not be what greets the field. The layout is already saved
        // after every swap, so leaving loses nothing.
        if (arranging) exitArrange()
        val moved = info?.fieldId != editor?.fieldId ||
                info?.packageName != editor?.packageName
        editor = info
        if (moved) {
            session++
            lastInsert = null
        }
        privateField = isPrivate(info)
        refreshActionKey()
        restoreState()
        if (!sticky) sayReady()
        if (!privateField) checkHealth()
    }

    /**
     * Fields this keyboard must stay out of.
     *
     * A password box, a bank's one-time code, or any field the app flagged
     * with NO_PERSONALIZED_LEARNING — Android's explicit "do not take this
     * text off the device". Dictating into one sends the audio to the PC
     * and writes the plaintext into transcripts.log, where it stays.
     * "Everything is logged" is a good property for prose and a completely
     * different thing for a password, so the answer is not to log it more
     * carefully but to refuse.
     */
    private fun isPrivate(info: EditorInfo?): Boolean {
        if (info == null) return false
        if ((info.imeOptions and EditorInfo.IME_FLAG_NO_PERSONALIZED_LEARNING) != 0) {
            return true
        }
        val cls = info.inputType and InputType.TYPE_MASK_CLASS
        val variation = info.inputType and InputType.TYPE_MASK_VARIATION
        if (cls == InputType.TYPE_CLASS_TEXT) {
            return variation == InputType.TYPE_TEXT_VARIATION_PASSWORD ||
                    variation == InputType.TYPE_TEXT_VARIATION_VISIBLE_PASSWORD ||
                    variation == InputType.TYPE_TEXT_VARIATION_WEB_PASSWORD
        }
        if (cls == InputType.TYPE_CLASS_NUMBER) {
            return variation == InputType.TYPE_NUMBER_VARIATION_PASSWORD
        }
        return false
    }

    /**
     * The action key's face, taken from what the field declared.
     *
     * Never a hard-coded IME_ACTION_SEARCH: performEditorAction fires
     * whatever that field's action really is, so guessing here would send a
     * message when the user asked to search. Three cases mean "Enter is a
     * newline, not a command": a multi-line field, IME_FLAG_NO_ENTER_ACTION
     * (the app saying it does not want an action offered), and no declared
     * action at all.
     *
     * The slot is permanent and only its label changes. A key that appeared
     * and vanished with the field would re-width all three of its siblings
     * every time the cursor moved, and move every target out from under a
     * thumb already on its way to one.
     */
    private fun refreshActionKey() {
        if (!::actionKey.isInitialized) return
        val opts = editor?.imeOptions ?: 0
        val declared = opts and EditorInfo.IME_MASK_ACTION
        val suppressed = (opts and EditorInfo.IME_FLAG_NO_ENTER_ACTION) != 0
        val multiline =
            ((editor?.inputType ?: 0) and InputType.TYPE_TEXT_FLAG_MULTI_LINE) != 0
        actionId = if (suppressed || multiline ||
            declared == EditorInfo.IME_ACTION_NONE ||
            declared == EditorInfo.IME_ACTION_UNSPECIFIED
        ) 0 else declared
        val face = when (actionId) {
            EditorInfo.IME_ACTION_SEARCH -> R.string.act_search
            EditorInfo.IME_ACTION_GO -> R.string.act_go
            EditorInfo.IME_ACTION_SEND -> R.string.act_send
            EditorInfo.IME_ACTION_DONE -> R.string.act_done
            EditorInfo.IME_ACTION_NEXT -> R.string.act_next
            EditorInfo.IME_ACTION_PREVIOUS -> R.string.act_prev
            else -> R.string.act_enter
        }
        actionKey.text = getString(face)
        actionKey.contentDescription = getString(face)
    }

    /** Do what the field's own blue key does. */
    private fun fireAction() {
        val ic = currentInputConnection ?: return
        if (actionId != 0) ic.performEditorAction(actionId)
        else sendDownUpKeyEvents(KeyEvent.KEYCODE_ENTER)
    }

    private fun sayReady() {
        if (privateField) { say(getString(R.string.private_field)); return }
        if (!hasMic()) {
            sayError(getString(R.string.needs_permission)) { openSetup() }; return
        }
        if (Prefs.token(this).isEmpty()) {
            sayError(getString(R.string.needs_setup)) { openSetup() }; return
        }
        say(
            if (backendName.isNotEmpty()) getString(R.string.ready_on, backendName)
            else getString(R.string.slide_to_lock)
        )
    }

    /**
     * Ask the PC whether it is awake, at most once a minute.
     *
     * onStartInputView fires on every field focus, so an unthrottled check
     * would be one network round trip per tap while filling in a form. It
     * never blocks anything: a failed preflight is a message, not a veto —
     * a recording made while the PC is asleep is still worth making, and
     * the retry below is what gets it there.
     */
    private fun checkHealth() {
        if (Prefs.token(this).isEmpty()) {
            // Nothing to ask yet: the lamp is grey until the PC is named.
            reachable = false
            if (!busy && !holding && !locked) tint(idleColor)
            return
        }
        val now = SystemClock.elapsedRealtime()
        if (now - lastHealth < HEALTH_TTL_MS) return
        lastHealth = now
        val url = Prefs.url(this)
        thread {
            val backend = Transcriber.health(url)
            ui.post {
                backendName = backend.orEmpty()
                reachable = backend != null
                if (busy || holding || locked) return@post
                tint(idleColor)
                if (backend == null) {
                    sayError(getString(R.string.unreachable)) { openSetup() }
                } else if (!sticky) {
                    sayReady()
                }
            }
        }
    }

    private fun hasMic() =
        checkSelfPermission(android.Manifest.permission.RECORD_AUDIO) ==
                PackageManager.PERMISSION_GRANTED

    // ---- recording ----

    private fun press(v: View) {
        if (busy) return
        if (locked) { finishLocked(); return }   // tap while locked = stop
        if (!ready()) return
        try {
            recorder.start()
        } catch (e: Exception) {
            sayError(e.message ?: "microphone error"); return
        }
        v.performHapticFeedback(HapticFeedbackConstants.KEYBOARD_TAP)
        holding = true
        tint(recColor)
        say(getString(R.string.slide_to_lock))
        startTicking()
    }

    /** The accessibility path: no finger to hold, so it locks immediately. */
    private fun startLocked() {
        if (!ready()) return
        try {
            recorder.start()
        } catch (e: Exception) {
            sayError(e.message ?: "microphone error"); return
        }
        holding = true
        locked = true
        tint(lockColor)
        say("")
        startTicking()
    }

    private fun ready(): Boolean {
        if (privateField) { say(getString(R.string.private_field)); return false }
        if (!hasMic()) {
            sayError(getString(R.string.needs_permission)) { openSetup() }
            return false
        }
        if (Prefs.token(this).isEmpty()) {
            sayError(getString(R.string.needs_setup)) { openSetup() }
            return false
        }
        return true
    }

    /**
     * Up locks the recording on; down throws it away.
     *
     * Up is the same escape hatch the desktop has on the left-arrow key:
     * holding a button is fine for a sentence and miserable for a
     * paragraph. Down is the desktop's Esc, which had no twin here at all —
     * releasing sent, and a locked recording could only be ended by a tap
     * that also sent it.
     *
     * They share one threshold and the first axis to cross it wins, so a
     * diagonal drag can never do both.
     */
    private fun gesture(v: View, y: Float) {
        if (!holding || gestured) return
        if (!locked && downY - y >= lockDistance) {
            gestured = true
            locked = true
            v.performHapticFeedback(HapticFeedbackConstants.LONG_PRESS)
            tint(lockColor)
            say("")
            return
        }
        if (y - downY >= lockDistance) {
            gestured = true
            discard()
        }
    }

    private fun discard() {
        if (!holding && !locked) return
        holding = false
        locked = false
        stopTicking()
        recorder.cancel()
        reset()
        button.performHapticFeedback(HapticFeedbackConstants.LONG_PRESS)
        say(getString(R.string.discarded))
    }

    private fun finishLocked() {
        locked = false
        holding = false
        deliverRecording()
    }

    private fun release(cancelled: Boolean) {
        if (!holding) return
        holding = false
        if (cancelled) {
            stopTicking()
            recorder.cancel()
            reset()
            return
        }
        deliverRecording()
    }

    private fun deliverRecording() {
        stopTicking()
        val capped = recorder.capped
        val silent = recorder.loudest < SILENCE
        val wav = recorder.stop()
        reset()
        if (wav == null) { say(getString(R.string.too_short)); return }
        if (silent) {
            // A whole recording under the noise floor is a microphone
            // another app is holding, not a quiet room. Uploading it buys a
            // round trip and the reply "No speech", which explains nothing.
            sayError(getString(R.string.no_sound))
            return
        }
        lastWav = wav
        send(wav)
        if (capped) {
            say(getString(R.string.capped, "${Recorder.MAX_SECONDS / 60} min"))
        }
    }

    private fun send(wav: ByteArray) {
        busy = true
        tint(busyColor)
        say(getString(R.string.transcribing))
        val url = Prefs.url(this)
        val token = Prefs.token(this)
        val mine = session
        thread {
            val result = Transcriber.send(url, token, wav)
            ui.post { deliver(result, mine) }
        }
    }

    private fun deliver(result: Transcriber.Result, mine: Int) {
        busy = false
        tint(idleColor)
        when (result) {
            is Transcriber.Result.Ok -> {
                val text = result.text.trim()
                if (text.isEmpty()) { say(getString(R.string.no_speech)); return }
                lastWav = null
                // The PC answered, so the link is up whatever /health last
                // said — and the sentence goes on the phone's own Said.
                reachable = true
                Prefs.addSaid(this, text)
                scheduleReviewPolls()
                if (!place(text, mine)) return
                // A decoder loop means words were LOST, not garbled — say
                // so now, not after the gap is discovered in reading.
                say(result.warning ?: engineNote(result))
                if (Prefs.switchBack(this)) goBack()
            }
            is Transcriber.Result.Err -> retryable(result.message)
        }
    }

    /**
     * The second reading takes three more decodes and a language model,
     * so its proposal is seconds to a minute behind the text. Three
     * polls after each dictation catch it; the home screen catches what
     * these miss. Never a service: nothing runs when nothing was said.
     */
    private fun scheduleReviewPolls() {
        for (r in polls) ui.removeCallbacks(r)
        polls.clear()
        val app = applicationContext
        for (delay in longArrayOf(20_000L, 60_000L, 150_000L)) {
            val r = Runnable { thread { Notify.poll(app) } }
            polls.add(r)
            ui.postDelayed(r, delay)
        }
    }

    private fun engineNote(ok: Transcriber.Result.Ok): String =
        if (ok.backend.isEmpty()) ""
        else String.format(Locale.US, "%.1f s · %s", ok.seconds, ok.backend)

    /**
     * Put the transcript where it was spoken, or keep it and say so.
     *
     * The whole reason this is a keyboard and not a floating button: the
     * text goes straight into the field, no clipboard involved. But only
     * into the RIGHT field — if the cursor moved to another app while the
     * PC was working, this holds the text and offers it on a tap rather
     * than writing into a stranger's.
     */
    private fun place(text: String, mine: Int): Boolean {
        val ic = currentInputConnection
        if (mine != session || ic == null) {
            pending = text
            sayError(getString(R.string.field_gone)) { insertPending() }
            return false
        }
        // The glue space matters now that the keyboard stays put: two
        // dictations in a row would otherwise weld into "משפטראשוןמשפטשני".
        val whole = glued(ic, text)
        ic.commitText(whole, 1)
        lastInsert = whole
        button.performHapticFeedback(HapticFeedbackConstants.KEYBOARD_TAP)
        return true
    }

    private fun glued(ic: InputConnection, text: String): String {
        val before = ic.getTextBeforeCursor(1, 0)
        return if (before.isNullOrEmpty() || before.last().isWhitespace()) text
        else " $text"
    }

    private fun insertPending() {
        val text = pending ?: return
        val ic = currentInputConnection ?: return
        val whole = glued(ic, text)
        ic.commitText(whole, 1)
        lastInsert = whole
        pending = null
        say("")
    }

    /** A failed send keeps its audio: "say it again" is the wrong answer. */
    private fun retryable(message: String) {
        val wav = lastWav
        if (wav == null) { sayError(message); return }
        sayError(getString(R.string.tap_to_retry, message)) { send(wav) }
    }

    // ---- keys that change what is already there ----

    /**
     * What the next operation works on, and how to put the answer back.
     *
     * A selection means just the selection; no selection means the whole
     * field — the same rule the desktop's Ctrl+F9 and F2 follow.
     *
     * The whole-field case is read as before-plus-after rather than through
     * getExtractedText, which returns null in Chrome's omnibox and in most
     * WebView-backed fields and made the translate key report an empty
     * field that was full. Reading it this way also yields the two lengths
     * needed to REPLACE it: performContextMenuAction(selectAll) is simply
     * not implemented in some fields, and there the translation was
     * appended after the Hebrew instead of replacing it.
     */
    private class Target(
        val text: String, val whole: Boolean,
        val beforeLen: Int, val afterLen: Int,
    )

    private fun readTarget(ic: InputConnection): Target? {
        val selected = ic.getSelectedText(0)?.toString()
        if (!selected.isNullOrBlank()) return Target(selected, false, 0, 0)
        val before = ic.getTextBeforeCursor(MAX_FIELD, 0)?.toString().orEmpty()
        val after = ic.getTextAfterCursor(MAX_FIELD, 0)?.toString().orEmpty()
        if ((before + after).isBlank()) return null
        return Target(before + after, true, before.length, after.length)
    }

    private fun translateField() = fieldOp(R.string.translating) { url, token, text ->
        Transcriber.translate(url, token, text)
    }

    private fun punctuateField() =
        fieldOp(R.string.punctuating) { url, token, text ->
            Transcriber.punctuate(url, token, text)
        }

    /**
     * Send what is in the field to the PC and put the answer back.
     *
     * Fails closed at every step, the way the passes on the far end do: a
     * field that moved on while the model was thinking is left alone rather
     * than half-replaced, and a reply the PC threw away — the model rewrote
     * the words instead of punctuating them — arrives as a sentence on the
     * status line with the text untouched.
     */
    private fun fieldOp(
        note: Int,
        call: (String, String, String) -> Transcriber.Result,
    ) {
        if (busy) return
        if (privateField) { say(getString(R.string.private_field)); return }
        if (Prefs.token(this).isEmpty()) {
            sayError(getString(R.string.needs_setup)) { openSetup() }; return
        }
        val ic = currentInputConnection ?: return
        val target = readTarget(ic)
        if (target == null) { say(getString(R.string.nothing_to_translate)); return }
        busy = true
        tint(busyColor)
        say(getString(note))
        val url = Prefs.url(this)
        val token = Prefs.token(this)
        val mine = session
        thread {
            val result = call(url, token, target.text)
            ui.post { putBack(result, target, mine) }
        }
    }

    private fun putBack(result: Transcriber.Result, target: Target, mine: Int) {
        busy = false
        tint(idleColor)
        if (result is Transcriber.Result.Err) { sayError(result.message); return }
        val out = (result as Transcriber.Result.Ok).text.trim()
        if (out.isEmpty()) { say(getString(R.string.no_speech)); return }
        val ic = currentInputConnection
        if (mine != session || ic == null) {
            sayError(getString(R.string.field_changed)); return
        }
        // Re-read before writing. The user may have typed while the model
        // was working, and deleting by lengths measured before that would
        // cut the wrong span out of their text.
        val now = readTarget(ic)
        if (now == null || now.text != target.text) {
            sayError(getString(R.string.field_changed)); return
        }
        ic.beginBatchEdit()
        // With a live selection commitText replaces it, so only the
        // whole-field case has anything to delete first.
        if (now.whole) ic.deleteSurroundingText(now.beforeLen, now.afterLen)
        ic.commitText(out, 1)
        ic.endBatchEdit()
        lastInsert = null
        say("")
    }

    /**
     * Take back exactly what this keyboard put in, and nothing else.
     *
     * Verified before it deletes: the text has to still be sitting there,
     * character for character. If the user has typed since, or the host app
     * rewrote what was committed, this refuses and says so rather than
     * eating a word it did not write. deleteSurroundingText counts UTF-16
     * units — safe here only because the exact string was matched first, so
     * an emoji in the transcript goes whole or not at all.
     */
    private fun undo() {
        val ic = currentInputConnection ?: return
        val mine = lastInsert
        if (mine.isNullOrEmpty()) { say(getString(R.string.cannot_undo)); return }
        if (ic.getTextBeforeCursor(mine.length, 0)?.toString() != mine) {
            say(getString(R.string.cannot_undo)); return
        }
        ic.deleteSurroundingText(mine.length, 0)
        lastInsert = null
        say(getString(R.string.undone))
    }

    private fun commit(text: String) {
        currentInputConnection?.commitText(text, 1)
        lastInsert = null
    }

    // ---- plumbing ----

    /**
     * Back to the everyday keyboard. This one exists to dictate a
     * sentence, not to be the keyboard you live in.
     */
    private fun goBack() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
            if (switchToPreviousInputMethod()) return
        }
        @Suppress("DEPRECATION")
        (getSystemService(INPUT_METHOD_SERVICE)
                as android.view.inputmethod.InputMethodManager)
            .showInputMethodPicker()
    }

    /**
     * The one place a keyboard is allowed to send you: its own setup screen.
     *
     * An InputMethodService cannot show a runtime permission dialog, so "no
     * mic permission" is not something this can ever fix in place — which
     * is why the status line has to be able to OPEN the app rather than
     * only mention it. NEW_TASK is mandatory from a Service.
     */
    private fun openSetup() {
        startActivity(
            Intent(this, HomeActivity::class.java)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        )
    }

    private val ticker = object : Runnable {
        override fun run() {
            if (!holding && !locked) return
            if (recorder.capped) { finishLocked(); return }
            val s = recorder.seconds.toInt()
            val clock = String.format(Locale.US, "%d:%02d", s / 60, s % 60)
            button.text = getString(
                if (locked) R.string.locked_time else R.string.recording_time, clock
            )
            val track = levelTrack.width
            if (track > 0) {
                val p = levelFill.layoutParams
                p.width = (track * recorder.peak.coerceIn(0f, 1f)).toInt()
                levelFill.layoutParams = p
            }
            ui.postDelayed(this, 100)
        }
    }

    private fun startTicking() {
        levelTrack.visibility = View.VISIBLE
        ui.removeCallbacks(ticker)
        ui.post(ticker)
    }

    private fun stopTicking() {
        ui.removeCallbacks(ticker)
        if (::levelTrack.isInitialized) levelTrack.visibility = View.INVISIBLE
    }

    /** After the view is rebuilt, show what is actually going on. */
    private fun restoreState() {
        if (!::button.isInitialized) return
        when {
            locked -> { tint(lockColor); startTicking() }
            holding -> { tint(recColor); startTicking() }
            busy -> {
                tint(busyColor)
                button.text = getString(R.string.hold_and_talk)
            }
            else -> {
                tint(idleColor)
                button.text = getString(R.string.hold_and_talk)
            }
        }
    }

    private fun reset() {
        locked = false
        stopTicking()
        tint(idleColor)
        button.text = getString(R.string.hold_and_talk)
    }

    /**
     * One state, three places: the lamp's colour, its halo (paused has
     * none — that is the desktop's rule for "off"), its breath (locked
     * only), and the pill's edge, which takes the state colour while
     * something is happening so the state is not read off 48dp alone.
     */
    private fun tint(color: Int) {
        if (::lamp.isInitialized) {
            lamp.colour = color
            lamp.halo = color != Skin.PAUSED
            lamp.breathe(color == lockColor)
            (pill.background as? GradientDrawable)?.setStroke(
                dp(1), if (color == idleColor || color == Skin.PAUSED) Skin.LINE else color)
        }
        // The backspace slot doubles as the way out of a locked recording,
        // so its face follows the same state the colour does.
        if (::backspace.isInitialized) {
            backspace.text = getString(
                if (locked) R.string.discard_btn else R.string.backspace_btn
            )
            backspace.contentDescription = getString(
                if (locked) R.string.cd_discard else R.string.cd_backspace
            )
        }
    }

    private fun say(msg: String) {
        if (!::status.isInitialized) return
        status.text = msg
        status.setTextColor(statusText)
        sticky = false
        statusAction = null
    }

    /**
     * An error that survives being looked away from.
     *
     * onStartInputView used to overwrite the status unconditionally, so the
     * only explanation the user was ever given — "can't reach the PC" — was
     * wiped the moment they tapped into the next field looking for it.
     */
    private fun sayError(msg: String, action: (() -> Unit)? = null) {
        sticky = true
        statusAction = action
        if (!::status.isInitialized) return
        status.text = msg
        status.setTextColor(errorText)
    }

    /**
     * The keyboard was swiped away, or the host app hid it.
     *
     * This is the hook that fires then. onFinishInput is the EDITOR going
     * away, which is a different event, and having only that one meant a
     * locked recording kept the microphone open — and the system's green
     * mic dot lit — with nothing on screen to explain it.
     */
    override fun onFinishInputView(finishingInput: Boolean) {
        super.onFinishInputView(finishingInput)
        stopTicking()
        for (r in repeats) ui.removeCallbacks(r)
        if (holding || locked) {
            holding = false; locked = false
            recorder.cancel()
            sayError(getString(R.string.recording_cancelled))
        }
    }

    override fun onFinishInput() {
        super.onFinishInput()
        stopTicking()
        for (r in repeats) ui.removeCallbacks(r)
        // Cleared here too: a request still in flight when the field goes
        // away would otherwise have presses swallowed in the NEXT field
        // until it lands.
        busy = false
        lastInsert = null
        if (holding || locked) {
            holding = false; locked = false
            recorder.cancel()
        }
    }

    private companion object {
        /**
         * How much of the field to read on each side of the cursor. The
         * server refuses anything over translate.max_chars (5000) anyway,
         * so this is that same ceiling arriving one step earlier — and it
         * keeps a whole document out of an IPC call.
         */
        const val MAX_FIELD = 4000

        /** Below this for a whole recording, nothing was captured. */
        const val SILENCE = 0.01f

        const val HEALTH_TTL_MS = 60_000L
    }
}
