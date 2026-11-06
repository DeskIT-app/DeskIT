package io.github.deskit_app.deskit

import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.ColorFilter
import android.graphics.LinearGradient
import android.graphics.Matrix
import android.graphics.Outline
import android.graphics.Paint
import android.graphics.Path
import android.graphics.PixelFormat
import android.graphics.RadialGradient
import android.graphics.Rect
import android.graphics.RectF
import android.graphics.Shader
import android.graphics.drawable.Drawable
import kotlin.math.abs
import kotlin.math.cos
import kotlin.math.sin

/**
 * B+'s surfaces, drawn: the desk's `bplus.css` in Canvas, value for value. No
 * blur anywhere, because a real backdrop blur needs API 31 and minSdk is 26.
 * The sky behind is already all soft fields, so the frost is the translucent
 * fill and the rim, and nothing has to be sampled from behind. Each face builds
 * its shaders when its size changes and only paints after that, and nothing
 * here is used by the keyboard's own bar, which stays on flat GradientDrawables.
 */

/** `rgba(r,g,b,a)`, as the CSS writes it. */
internal fun rgba(r: Int, g: Int, b: Int, a: Float): Int =
    Color.argb((a * 255 + 0.5f).toInt(), r, g, b)

private fun white(a: Float) = rgba(255, 255, 255, a)

/** The end points of CSS's `linear-gradient(<deg>, …)` on a box. */
private fun cssLine(box: RectF, degrees: Float): FloatArray {
    val a = Math.toRadians(degrees.toDouble())
    val s = sin(a).toFloat()
    val c = cos(a).toFloat()
    val half = (abs(box.width() * s) + abs(box.height() * c)) / 2f
    val cx = box.centerX()
    val cy = box.centerY()
    return floatArrayOf(cx - s * half, cy + c * half, cx + s * half, cy - c * half)
}

private fun cssGradient(box: RectF, degrees: Float, colours: IntArray, stops: FloatArray): Shader {
    val p = cssLine(box, degrees)
    return LinearGradient(p[0], p[1], p[2], p[3], colours, stops, Shader.TileMode.CLAMP)
}

abstract class Face : Drawable() {
    override fun setAlpha(alpha: Int) {}
    override fun setColorFilter(filter: ColorFilter?) {}

    @Deprecated("Deprecated in Java")
    override fun getOpacity(): Int = PixelFormat.TRANSLUCENT
}

/**
 * The night behind everything: the desk's floor and four soft fields of light.
 * Dithered, or a gradient this dark bands on most screens.
 */
class Sky : Face() {
    private class Field(val x: Float, val y: Float, val r: Float, val colour: Int) {
        val paint = Paint(Paint.ANTI_ALIAS_FLAG).apply { isDither = true }
    }

    private val fields = listOf(
        Field(0.08f, 0.16f, 1.05f, rgba(118, 98, 246, .30f)),       // --f-indigo
        Field(1.02f, 0.48f, 0.95f, rgba(44, 146, 232, .20f)),       // --f-blue
        Field(0.05f, 0.92f, 0.95f, rgba(196, 92, 178, .13f)),       // --f-plum
        Field(0.95f, 1.02f, 0.70f, rgba(40, 178, 168, .10f)),       // --f-teal
    )

    override fun onBoundsChange(bounds: Rect) {
        val w = bounds.width().toFloat()
        val h = bounds.height().toFloat()
        if (w <= 0f || h <= 0f) return
        for (f in fields) {
            val a = Color.alpha(f.colour)
            val edge = f.colour and 0x00FFFFFF
            val mid = Color.argb((a * 0.42f).toInt(), Color.red(f.colour), Color.green(f.colour),
                                 Color.blue(f.colour))
            f.paint.shader = RadialGradient(w * f.x, h * f.y, w * f.r,
                intArrayOf(f.colour, mid, edge), floatArrayOf(0f, 0.5f, 1f), Shader.TileMode.CLAMP)
        }
    }

    override fun draw(canvas: Canvas) {
        canvas.drawColor(Skin.GROUND)
        val b = RectF(bounds)
        for (f in fields) canvas.drawRect(b, f.paint)
    }
}

/**
 * A pane of glass: its fill, the frost's own light from the top-left, and the
 * rim that catches it. `.glass` and `.glass::before`.
 */
class Glass(c: Context, private val fill: Int = Skin.GLASS_CARD, radiusDp: Int = 22,
            private val rimFoot: Int = rgba(160, 150, 255, .10f)) : Face() {
    private val radius = Skin.dpF(c, radiusDp.toFloat())
    private val hair = Skin.dpF(c, 1f).coerceAtLeast(1f)
    private val solid = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = fill }
    private val frost = Paint(Paint.ANTI_ALIAS_FLAG)
    private val rim = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE
        strokeWidth = hair
    }
    private val box = RectF()
    private val edge = RectF()

    override fun onBoundsChange(bounds: Rect) {
        box.set(bounds)
        edge.set(box)
        edge.inset(hair / 2f, hair / 2f)
        frost.shader = cssGradient(box, 150f, intArrayOf(white(.045f), 0), floatArrayOf(0f, .45f))
        rim.shader = cssGradient(box, 155f,
            intArrayOf(white(.26f), white(.08f), white(.025f), rimFoot),
            floatArrayOf(0f, .22f, .55f, 1f))
    }

    override fun draw(canvas: Canvas) {
        canvas.drawRoundRect(box, radius, radius, solid)
        canvas.drawRoundRect(box, radius, radius, frost)
        canvas.drawRoundRect(edge, radius, radius, rim)
    }

    override fun getOutline(outline: Outline) {
        outline.setRoundRect(bounds, radius)
    }
}

/**
 * A button: the quiet pill of frost, or the one lit iris pill with its light
 * pooled under it, never a ring. The view keeps [footDp] free below the pill
 * for that light, the quiet ones too, so two buttons in a row line up.
 */
class Pill(c: Context, private val lit: Boolean, private val pressed: Boolean,
           private val footDp: Int = Skin.BUTTON_FOOT) : Face() {
    private val foot = Skin.dpF(c, footDp.toFloat())
    private val hair = Skin.dpF(c, 1f).coerceAtLeast(1f)
    private val body = Paint(Paint.ANTI_ALIAS_FLAG).apply { isDither = true }
    private val rim = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE
        strokeWidth = hair
    }
    private val glow = Paint(Paint.ANTI_ALIAS_FLAG)
    private val pill = RectF()
    private val edge = RectF()

    override fun onBoundsChange(bounds: Rect) {
        pill.set(bounds.left.toFloat(), bounds.top.toFloat(), bounds.right.toFloat(),
                 bounds.bottom - foot)
        edge.set(pill)
        edge.inset(hair / 2f, hair / 2f)
        val top = pill.top
        val bottom = pill.bottom
        if (lit) {
            val colours = if (pressed)
                intArrayOf(Skin.ACCENT, Skin.ACCENT_LO, Skin.ACCENT_LO)
            else intArrayOf(Skin.ACCENT_HI, Skin.ACCENT, Skin.ACCENT_LO)
            body.shader = LinearGradient(0f, top, 0f, bottom, colours,
                                         floatArrayOf(0f, .55f, 1f), Shader.TileMode.CLAMP)
            rim.shader = LinearGradient(0f, top, 0f, bottom,
                intArrayOf(white(.24f), 0, rgba(40, 20, 120, .28f)),
                floatArrayOf(0f, .4f, 1f), Shader.TileMode.CLAMP)
            val cx = pill.centerX()
            val cy = bottom
            val spread = pill.width() * .46f
            val shape = Matrix().apply { setScale(1f, (foot * 1.6f) / spread, cx, cy) }
            glow.shader = RadialGradient(cx, cy, spread,
                intArrayOf(rgba(135, 115, 255, if (pressed) .30f else .50f), rgba(135, 115, 255, 0f)),
                null, Shader.TileMode.CLAMP).apply { setLocalMatrix(shape) }
        } else {
            val a = if (pressed) .15f else .10f
            val b = if (pressed) .09f else .055f
            body.shader = LinearGradient(0f, top, 0f, bottom, white(a), white(b),
                                         Shader.TileMode.CLAMP)
            rim.shader = LinearGradient(0f, top, 0f, bottom, white(.16f), white(.10f),
                                        Shader.TileMode.CLAMP)
        }
    }

    override fun draw(canvas: Canvas) {
        val r = pill.height() / 2f
        if (lit) canvas.drawRect(bounds.left.toFloat(), pill.centerY(), bounds.right.toFloat(),
                                 bounds.bottom.toFloat(), glow)
        canvas.drawRoundRect(pill, r, r, body)
        canvas.drawRoundRect(edge, r, r, rim)
    }
}

/** A round disc of frost with a drawn mark inside: the arrow back. */
class Disc(c: Context, private val pressed: Boolean) : Face() {
    private val hair = Skin.dpF(c, 1f).coerceAtLeast(1f)
    private val body = Paint(Paint.ANTI_ALIAS_FLAG)
    private val rim = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE
        strokeWidth = hair
    }
    private val ink = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE
        strokeWidth = Skin.dpF(c, 1.8f)
        strokeCap = Paint.Cap.ROUND
        strokeJoin = Paint.Join.ROUND
        color = Skin.FG
    }
    private val mark = Path()

    /**
     * Drawn, not typed. A "←" in a font sits where the font's metrics put it,
     * which is why it was off-centre: here its box is centred on the disc's.
     */
    override fun onBoundsChange(bounds: Rect) {
        val cx = bounds.exactCenterX()
        val cy = bounds.exactCenterY()
        val half = bounds.width() * .19f            // half the arrow's length
        val barb = half * .72f
        mark.reset()
        mark.moveTo(cx + half, cy)
        mark.lineTo(cx - half, cy)
        mark.moveTo(cx - half + barb, cy - barb)
        mark.lineTo(cx - half, cy)
        mark.lineTo(cx - half + barb, cy + barb)
        val top = bounds.top.toFloat()
        val bottom = bounds.bottom.toFloat()
        body.shader = LinearGradient(0f, top, 0f, bottom, white(if (pressed) .15f else .10f),
                                     white(if (pressed) .09f else .055f), Shader.TileMode.CLAMP)
        rim.shader = LinearGradient(0f, top, 0f, bottom, white(.16f), white(.08f),
                                    Shader.TileMode.CLAMP)
    }

    override fun draw(canvas: Canvas) {
        val cx = bounds.exactCenterX()
        val cy = bounds.exactCenterY()
        val r = bounds.width() / 2f
        canvas.drawCircle(cx, cy, r, body)
        canvas.drawCircle(cx, cy, r - hair / 2f, rim)
        canvas.drawPath(mark, ink)
    }
}

/** A device's mark: a disc of frost with a phone or a laptop drawn in it. */
class DeviceMark(c: Context, private val phone: Boolean) : Face() {
    private val fill = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = rgba(255, 255, 255, .07f) }
    private val ink = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE
        strokeWidth = Skin.dpF(c, 1.4f)
        strokeCap = Paint.Cap.ROUND
        color = Skin.MUTED
    }
    private val shape = RectF()
    private val base = FloatArray(4)

    override fun onBoundsChange(bounds: Rect) {
        val cx = bounds.exactCenterX()
        val cy = bounds.exactCenterY()
        val u = bounds.width() / 34f
        if (phone) {
            shape.set(cx - 5 * u, cy - 8 * u, cx + 5 * u, cy + 8 * u)
            base[0] = cx - 1.5f * u; base[1] = cy + 5.5f * u
            base[2] = cx + 1.5f * u; base[3] = cy + 5.5f * u
        } else {
            shape.set(cx - 7 * u, cy - 6 * u, cx + 7 * u, cy + 3.5f * u)
            base[0] = cx - 9 * u; base[1] = cy + 6.5f * u
            base[2] = cx + 9 * u; base[3] = cy + 6.5f * u
        }
    }

    override fun draw(canvas: Canvas) {
        canvas.drawCircle(bounds.exactCenterX(), bounds.exactCenterY(), bounds.width() / 2f, fill)
        val r = shape.width() * .16f
        canvas.drawRoundRect(shape, r, r, ink)
        canvas.drawLine(base[0], base[1], base[2], base[3], ink)
    }
}

/** `.fade-rule`: a divider that fades out at both ends. */
class FadeRule : Face() {
    private val paint = Paint()

    override fun onBoundsChange(bounds: Rect) {
        val line = rgba(170, 175, 220, .12f)
        paint.shader = LinearGradient(bounds.left.toFloat(), 0f, bounds.right.toFloat(), 0f,
            intArrayOf(0, line, line, 0), floatArrayOf(0f, .12f, .88f, 1f), Shader.TileMode.CLAMP)
    }

    override fun draw(canvas: Canvas) {
        canvas.drawRect(bounds, paint)
    }
}
