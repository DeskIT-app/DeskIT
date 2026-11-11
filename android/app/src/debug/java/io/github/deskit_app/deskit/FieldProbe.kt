package io.github.deskit_app.deskit

import android.app.Activity
import android.os.Bundle
import android.view.ViewGroup
import android.view.WindowManager
import android.widget.EditText

/**
 * Debug builds only: one text field with the cursor in it, so the keyboard comes
 * up for a flow on a field of nobody's in particular. What lands in it is on
 * screen for the flow to read, and closing this is a field that has gone.
 *
 *   adb shell am start -n <package>/.FieldProbe [--ez private true]
 *
 * `private` makes it a password field, where the keyboard stays out.
 */
class FieldProbe : Activity() {

    override fun onCreate(saved: Bundle?) {
        super.onCreate(saved)
        val secret = intent.getBooleanExtra("private", false)
        val field = EditText(this).apply {
            hint = if (secret) "password" else "field"
            contentDescription = hint
            if (secret) inputType = android.text.InputType.TYPE_CLASS_TEXT or
                android.text.InputType.TYPE_TEXT_VARIATION_PASSWORD
        }
        setContentView(field, ViewGroup.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT,
                                                     ViewGroup.LayoutParams.WRAP_CONTENT))
        window.setSoftInputMode(WindowManager.LayoutParams.SOFT_INPUT_STATE_ALWAYS_VISIBLE)
        field.requestFocus()
    }
}
