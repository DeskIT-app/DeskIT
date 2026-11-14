package io.github.deskit_app.deskit

import android.app.Activity
import android.content.ClipboardManager
import android.util.Log

/**
 * Debug builds only: the label on whatever is on the clipboard, and then it
 * closes. A window, because Android 10 and up answer only the app with the focus.
 *
 *   adb shell am start -n <package>/.ClipProbe
 */
class ClipProbe : Activity() {

    override fun onWindowFocusChanged(hasFocus: Boolean) {
        super.onWindowFocusChanged(hasFocus)
        if (!hasFocus) return
        val board = getSystemService(CLIPBOARD_SERVICE) as ClipboardManager
        Log.i("DeskIT", "probe: clip=${board.primaryClipDescription?.label ?: "none"}")
        finish()
    }
}
