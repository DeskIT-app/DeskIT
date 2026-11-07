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
 *   adb shell am start -n <package>/.FieldProbe
 */
class FieldProbe : Activity() {

    override fun onCreate(saved: Bundle?) {
        super.onCreate(saved)
        val field = EditText(this).apply {
            hint = "field"
            contentDescription = "field"
        }
        setContentView(field, ViewGroup.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT,
                                                     ViewGroup.LayoutParams.WRAP_CONTENT))
        window.setSoftInputMode(WindowManager.LayoutParams.SOFT_INPUT_STATE_ALWAYS_VISIBLE)
        field.requestFocus()
    }
}
