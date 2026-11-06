package io.github.deskit_app.deskit

import android.app.Activity
import android.os.Bundle
import android.view.View
import android.view.ViewGroup
import android.widget.LinearLayout
import android.widget.ScrollView

/**
 * The account's screens with made-up data and buttons that do nothing: what
 * the prototype pictures are taken from.
 *
 *   adb shell am start -n <package>/.ProtoActivity --es screen waiting
 *
 * Debug builds only (src/debug), and it reads nothing of the account.
 */
class ProtoActivity : Activity() {

    override fun onCreate(saved: Bundle?) {
        super.onCreate(saved)
        val c = this
        val a = AccountScreens(c)
        val email = "dana.levi@example.com"
        val code = "WK0MS-7HN8C"
        val none = {}
        val col = LinearLayout(c).apply {
            orientation = LinearLayout.VERTICAL
            layoutDirection = View.LAYOUT_DIRECTION_LTR
            val p = Skin.dp(c, 20)
            setPadding(p, Skin.dp(c, 24), p, Skin.dp(c, 32))
        }
        setContentView(ScrollView(c).apply {
            setBackgroundColor(Skin.BG)
            isVerticalScrollBarEnabled = false
            addView(col, ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT)
        })
        val screen = intent.getStringExtra("screen") ?: "signin"
        val onSettings = screen in setOf("devices", "asking", "twins", "forget", "signout")
        col.addView(LinearLayout(c).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = android.view.Gravity.CENTER_VERTICAL
            setPadding(0, 0, 0, Skin.dp(c, 18))
            addView(Skin.backButton(c) { })
            addView(Skin.text(c, getString(if (onSettings) R.string.settings else R.string.your_account),
                              26f, Skin.FG, heavy = true))
        })
        val phone = AccountScreens.Row("1", "Dana's phone", "Phone", "", mine = true, linked = true)
        val home = AccountScreens.Row("2", "HOME-PC", "PC", "today", mine = false, linked = true)
        val work = AccountScreens.Row("3", "Office PC", "PC", "3 days ago", mine = false, linked = true)
        val tablet = AccountScreens.Row("4", "דנה טאבלט", "Phone", "last week", mine = false, linked = true)
        fun account(rows: List<View>, foot: View) = col.addView(a.accountCard(email, "", rows, foot))
        val signOut = Skin.button(c, getString(R.string.sign_out)) { }
        val devices = listOf(a.deviceRow(phone, null), a.deviceRow(home, none),
                             a.deviceRow(work, none), a.deviceRow(tablet, none))
        when (screen) {
            "signin" -> col.addView(a.signIn("", none))
            "signin_gone" -> col.addView(a.signIn(Account.GONE_ELSEWHERE, none))
            "preparing" -> col.addView(a.preparing(email))
            "waiting" -> col.addView(a.waiting(code, email, "", none))
            "removed" -> col.addView(a.waiting(code, email, getString(R.string.removed_word), none))
            "nolock" -> col.addView(a.noLock(email, "", none))
            "declined" -> col.addView(a.declined(email, none, none))
            "ready" -> col.addView(a.ready(listOf("HOME-PC", "Office PC"), none))
            "changed" -> col.addView(a.changed(none, none))
            "refused" -> col.addView(a.refused())
            "devices" -> account(devices, signOut)
            "asking" -> {
                col.addView(a.asking(AccountScreens.Ask("5", "NEW-PC", code), none, none))
                account(devices.take(2), signOut)
            }
            "twins" -> {
                col.addView(a.asking(AccountScreens.Ask("5", "NEW-PC", ""), none, none))
                account(devices.take(2), signOut)
            }
            "forget" -> account(listOf(a.deviceRow(phone, null),
                                       a.forgetQuestion("Office PC", none, none),
                                       a.deviceRow(home, none)), signOut)
            "signout" -> account(devices.take(2), a.signOutQuestion(2, none, none))
        }
    }
}
