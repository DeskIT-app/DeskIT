package com.yoav.dictation

import android.animation.ValueAnimator
import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.RadialGradient
import android.graphics.Shader
import android.view.View
import android.view.animation.LinearInterpolator

/**
 * The lamp: the desktop's status dot, drawn large enough for a phone.
 *
 * A disc and a halo. The disc's colour is the state — the five the
 * desktop uses, in Skin — and the halo is what tells "on" from "off":
 * paused is the one state with no halo at all, the same rule skin\dot.py
 * keeps, because a grey dot and a blue dot at nearly the same lightness
 * are told apart by the light around them and not by hue.
 *
 * Recording and locked are one colour by design and are separated by the
 * breath: a locked recording breathes at the desktop's 0.16 Hz, a held
 * one holds still, so a lamp you walked away from reads as still alive.
 */
class LampView(context: Context) : View(context) {

    var colour: Int = Skin.PAUSED
        set(value) {
            if (field == value) return
            field = value
            haloShader = null
            invalidate()
        }

    var halo: Boolean = false
        set(value) { field = value; invalidate() }

    /** The disc's radius as a fraction of the view's half-width. */
    var core: Float = 0.42f

    private var breath = 1f
    private var breathing: ValueAnimator? = null
    private var haloShader: Shader? = null
    private var haloColour = 0

    private val discPaint = Paint(Paint.ANTI_ALIAS_FLAG)
    private val haloPaint = Paint(Paint.ANTI_ALIAS_FLAG)

    fun breathe(on: Boolean) {
        if (on && breathing == null) {
            breathing = ValueAnimator.ofFloat(0f, 1f).apply {
                duration = 6250          // 0.16 Hz, the desktop's breath
                repeatCount = ValueAnimator.INFINITE
                interpolator = LinearInterpolator()
                addUpdateListener {
                    val t = it.animatedValue as Float
                    // A sine, so the two ends of the breath are soft.
                    breath = 0.86f + 0.14f *
                            (0.5f + 0.5f * Math.sin(2 * Math.PI * t).toFloat())
                    invalidate()
                }
                start()
            }
        } else if (!on && breathing != null) {
            breathing?.cancel()
            breathing = null
            breath = 1f
            invalidate()
        }
    }

    override fun onDetachedFromWindow() {
        breathe(false)
        super.onDetachedFromWindow()
    }

    override fun onDraw(canvas: Canvas) {
        val w = width.toFloat()
        val h = height.toFloat()
        val cx = w / 2f
        val cy = h / 2f
        val half = Math.min(w, h) / 2f
        val r = half * core
        if (halo) {
            val reach = half * breath
            if (haloShader == null || haloColour != colour) {
                haloColour = colour
                haloShader = null
            }
            // Rebuilt per frame while breathing: the gradient's radius is
            // the breath. Cheap — one small view, six frames a second.
            val a = (Color.alpha(colour) * 0.55f).toInt()
            val inner = Color.argb(a, Color.red(colour), Color.green(colour),
                                   Color.blue(colour))
            val outer = Color.argb(0, Color.red(colour), Color.green(colour),
                                   Color.blue(colour))
            haloPaint.shader = RadialGradient(
                cx, cy, reach,
                intArrayOf(inner, inner, outer),
                floatArrayOf(0f, core * 0.9f, 1f),
                Shader.TileMode.CLAMP)
            canvas.drawCircle(cx, cy, reach, haloPaint)
        }
        discPaint.color = colour
        canvas.drawCircle(cx, cy, r, discPaint)
    }
}
