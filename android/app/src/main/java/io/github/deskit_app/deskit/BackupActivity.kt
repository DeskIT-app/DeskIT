package io.github.deskit_app.deskit

import android.app.Activity
import android.content.Intent
import android.os.Bundle
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.widget.LinearLayout
import android.widget.Switch
import android.widget.TextView
import kotlin.concurrent.thread

/**
 * The cloud backup, seen once (PHONE_LINK_PLAN.md 2b, picture b of 2026-11-11): the
 * first open of Home on a joined phone after the update that brings it, and so the last
 * step of a new phone's setup. The switch is already on, one plain line says what it
 * does and where it is turned off, a smaller one names the price, and Done is the yes:
 * it records the words and their version on the phone ([Backup.answer]). With no key in
 * the account it says so, and Add a key opens Settings at the keys.
 *
 * Back leaves it unanswered, and it comes again at the next open of Home: nothing is
 * sent before Done.
 */
class BackupActivity : Activity() {

    private var on = true
    private lateinit var col: LinearLayout

    override fun onCreate(saved: Bundle?) {
        super.onCreate(saved)
        on = saved?.getBoolean("on", true) ?: true
        col = Skin.page(this)
        draw()
        // a key added on a PC since the last read: the screen says the truth about it
        thread(name = "backup-keys") {
            try {
                CloudKeys.refresh(this)
            } catch (e: Account.Failed) {
                // what was last read stands
            } catch (e: Sealed.NotNow) {
                // the same
            }
            runOnUiThread { if (!isFinishing) draw() }
        }
    }

    override fun onSaveInstanceState(out: Bundle) {
        super.onSaveInstanceState(out)
        out.putBoolean("on", on)
    }

    private fun match() = LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT,
                                                    ViewGroup.LayoutParams.WRAP_CONTENT)

    private fun below(v: View, dp: Int): View = v.apply {
        layoutParams = (layoutParams as? LinearLayout.LayoutParams ?: match()).also {
            it.topMargin = Skin.dp(this@BackupActivity, dp)
        }
    }

    private fun body(text: String, colour: Int = Skin.DIM, sp: Float = 15f): TextView =
        Skin.text(this, text, sp, colour).apply {
            setLineSpacing(0f, 1.25f)
            layoutParams = match()
        }

    private fun using(): String = (CloudKeys.provider(this) ?: Cloud.Provider.GROQ).label

    private fun draw() {
        col.removeAllViews()
        col.addView(Skin.gap(this, 24))
        col.addView(Skin.card(this, 22).apply {
            addView(Skin.title(this@BackupActivity, getString(R.string.backup_title), 22f).apply {
                setLineSpacing(0f, 1.15f)
                layoutParams = match()
            })
            addView(below(LinearLayout(this@BackupActivity).apply {
                orientation = LinearLayout.HORIZONTAL
                gravity = Gravity.CENTER_VERTICAL
                layoutParams = match()
                addView(Skin.text(this@BackupActivity, getString(R.string.backup_switch), 16f, Skin.FG).apply {
                    typeface = Skin.fontLabel(this@BackupActivity)
                    layoutParams = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f)
                        .apply { marginEnd = Skin.dp(this@BackupActivity, 12) }
                })
                addView(Switch(this@BackupActivity).apply {
                    isChecked = on
                    Skin.switchLook(this@BackupActivity, this)
                    contentDescription = getString(R.string.backup_switch)
                    setOnCheckedChangeListener { _, now -> on = now }
                })
            }, 18))
            addView(below(body(getString(R.string.backup_once_line, using())), 12))
            addView(below(body(getString(R.string.backup_price, using()), Skin.MUTED, 14f), 10))
            if (CloudKeys.provider(this@BackupActivity) == null) {
                addView(below(body(getString(R.string.backup_no_key_yet), Skin.AMBER, 14f), 10))
                addView(Skin.link(this@BackupActivity, getString(R.string.add_a_key)) {
                    startActivity(Intent(this@BackupActivity, SettingsActivity::class.java)
                        .putExtra(SettingsActivity.AT_KEYS, true))
                })
                addView(below(Skin.button(this@BackupActivity, getString(R.string.done), primary = true) {
                    done()
                }, 14))
            } else {
                addView(below(Skin.button(this@BackupActivity, getString(R.string.done), primary = true) {
                    done()
                }, 20))
            }
        })
    }

    /** The yes, to the words on this screen, or the switch left off: either way, answered. */
    private fun done() {
        val words = getString(R.string.backup_once_line, using()) + " " +
            getString(R.string.backup_price, using())
        Backup.answer(this, on, words)
        finish()
    }
}
