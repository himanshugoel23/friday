package app.robin.parent

import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.Path
import android.graphics.RectF
import android.graphics.Typeface
import android.graphics.drawable.Drawable
import android.os.Bundle
import android.view.MotionEvent
import android.view.View
import android.view.accessibility.AccessibilityNodeInfo
import app.robin.core.BubbleShape
import app.robin.core.Polygons
import app.robin.core.TouchClassifier

/**
 * The floating bubble itself: a coloured outline (a different SHAPE per state), a big white glyph, and the state WORD in a
 * dark strip under it, so colour is never the only cue. The view only draws and reports raw touches; every decision
 * (tap / drag / long press, snapping, modes) is in :core and in [BubbleService].
 */
class BubbleView(context: Context) : View(context) {
    interface Listener {
        fun onTap()
        fun onLongPress()
        fun onDragStart()
        fun onDrag(dx: Float, dy: Float)
        fun onDragEnd()
        /** TalkBack custom actions. */
        fun onA11yAction(id: Int): Boolean
    }

    var listener: Listener? = null
    private val density = resources.displayMetrics.density
    private fun dp(v: Float) = v * density

    /** Whole touch target: 88 dp square. */
    val sizePx: Int = dp(88f).toInt()

    private var shape = BubbleShape.CIRCLE
    private var fill = Color.BLUE
    private var glyph: Drawable? = null
    private var word = ""

    /** 0..1 loudness while listening: thickens a ring around the shape so the person can see Robin hears them. */
    var level = 0f
        set(v) { field = v.coerceIn(0f, 1f); invalidate() }

    private val fillPaint = Paint(Paint.ANTI_ALIAS_FLAG)
    private val edgePaint = Paint(Paint.ANTI_ALIAS_FLAG).apply { style = Paint.Style.STROKE; color = Color.WHITE; strokeWidth = dp(3f) }
    private val darkEdge = Paint(Paint.ANTI_ALIAS_FLAG).apply { style = Paint.Style.STROKE; color = 0xFF202124.toInt(); strokeWidth = dp(5f) }
    private val ringPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply { style = Paint.Style.STROKE; color = 0xAAFFFFFF.toInt() }
    private val stripPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = 0xE6202124.toInt() }
    private val textPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = Color.WHITE; typeface = Typeface.DEFAULT_BOLD; textAlign = Paint.Align.CENTER }
    private val path = Path()
    private val rect = RectF()

    private val touch = TouchClassifier(slopPx = (dp(10f)).toInt())
    private val longPress = Runnable { if (touch.tick(android.os.SystemClock.elapsedRealtime()) == TouchClassifier.Gesture.LONG_PRESS) fireLong() }

    init {
        isClickable = true
        isFocusable = true
        importantForAccessibility = IMPORTANT_FOR_ACCESSIBILITY_YES
        accessibilityLiveRegion = ACCESSIBILITY_LIVE_REGION_POLITE
    }

    fun render(shape: BubbleShape, glyphRes: Int, word: String, colour: Int, description: String) {
        this.shape = shape
        this.fill = colour
        this.glyph = context.getDrawable(glyphRes)?.mutate()
        this.word = word
        contentDescription = description
        invalidate()
    }

    override fun onMeasure(widthMeasureSpec: Int, heightMeasureSpec: Int) = setMeasuredDimension(sizePx, sizePx)

    override fun onDraw(canvas: Canvas) {
        val shapeD = dp(64f)
        val cx = width / 2f
        val cy = dp(2f) + shapeD / 2f
        val r = shapeD / 2f
        fillPaint.color = fill
        buildPath(cx, cy, r)
        if (level > 0.05f) {
            ringPaint.strokeWidth = dp(2f + 5f * level)
            canvas.drawCircle(cx, cy, r + dp(3f) + dp(3f) * level, ringPaint)
        }
        canvas.drawPath(path, fillPaint)
        canvas.drawPath(path, darkEdge)
        canvas.drawPath(path, edgePaint)
        glyph?.let {
            val g = dp(34f).toInt()
            it.setBounds((cx - g / 2).toInt(), (cy - g / 2).toInt(), (cx + g / 2).toInt(), (cy + g / 2).toInt())
            it.draw(canvas)
        }
        // word strip, with the text shrunk until it fits (Hindi words are longer)
        val stripH = dp(22f)
        val top = height - stripH
        rect.set(dp(1f), top, width - dp(1f), height - dp(1f))
        canvas.drawRoundRect(rect, dp(11f), dp(11f), stripPaint)
        var size = dp(14f)
        textPaint.textSize = size
        while (textPaint.measureText(word) > rect.width() - dp(6f) && size > dp(8f)) { size -= dp(0.5f); textPaint.textSize = size }
        val base = rect.centerY() - (textPaint.descent() + textPaint.ascent()) / 2f
        canvas.drawText(word, rect.centerX(), base, textPaint)
    }

    private fun buildPath(cx: Float, cy: Float, r: Float) {
        path.reset()
        when (shape) {
            BubbleShape.CIRCLE -> path.addCircle(cx, cy, r, Path.Direction.CW)
            BubbleShape.ROUNDED_SQUARE -> { rect.set(cx - r, cy - r, cx + r, cy + r); path.addRoundRect(rect, dp(12f), dp(12f), Path.Direction.CW) }
            else -> {
                // Regular polygons, pulled in a little so every outline has about the same visual weight as the circle.
                val rr = when (shape) { BubbleShape.DIAMOND -> r * 1.15f; BubbleShape.TRIANGLE -> r * 1.15f; else -> r }
                val pts = Polygons.points(shape.sides, cx, cy + (if (shape == BubbleShape.TRIANGLE) dp(3f) else 0f), rr)
                pts.forEachIndexed { i, p -> if (i == 0) path.moveTo(p.x, p.y) else path.lineTo(p.x, p.y) }
                path.close()
            }
        }
    }

    // ------------------------------------------------------------------ touch
    private fun fireLong() {
        removeCallbacks(longPress)
        listener?.onLongPress()
    }

    override fun onTouchEvent(e: MotionEvent): Boolean {
        val now = android.os.SystemClock.elapsedRealtime()
        when (e.actionMasked) {
            MotionEvent.ACTION_DOWN -> {
                // rawX/rawY: the window itself moves while dragging, so view-relative coordinates would drift.
                touch.down(e.rawX, e.rawY, now)
                postDelayed(longPress, TouchClassifier.DEFAULT_LONG_PRESS_MS)
                parent?.requestDisallowInterceptTouchEvent(true)
            }
            MotionEvent.ACTION_MOVE -> when (touch.move(e.rawX, e.rawY)) {
                TouchClassifier.Gesture.DRAG_START -> { removeCallbacks(longPress); listener?.onDragStart(); listener?.onDrag(touch.dx, touch.dy) }
                TouchClassifier.Gesture.DRAG_MOVE -> listener?.onDrag(touch.dx, touch.dy)
                else -> Unit
            }
            MotionEvent.ACTION_UP -> {
                removeCallbacks(longPress)
                when (touch.up(now)) {
                    TouchClassifier.Gesture.TAP -> performClick()
                    TouchClassifier.Gesture.DRAG_END -> listener?.onDragEnd()
                    TouchClassifier.Gesture.LONG_PRESS -> fireLong()
                    else -> Unit
                }
            }
            MotionEvent.ACTION_CANCEL -> {
                removeCallbacks(longPress)
                if (touch.cancel() == TouchClassifier.Gesture.CANCELLED) listener?.onDragEnd()
            }
        }
        return true
    }

    /** Both a finger tap and TalkBack's double tap arrive here. */
    override fun performClick(): Boolean {
        super.performClick()
        listener?.onTap()
        return true
    }

    // ------------------------------------------------------------------ TalkBack
    override fun onInitializeAccessibilityNodeInfo(info: AccessibilityNodeInfo) {
        super.onInitializeAccessibilityNodeInfo(info)
        info.className = android.widget.Button::class.java.name
        info.addAction(AccessibilityNodeInfo.AccessibilityAction.ACTION_LONG_CLICK)
        info.addAction(AccessibilityNodeInfo.AccessibilityAction(A11Y_MENU, context.getString(R.string.bubble_a11y_menu)))
        info.addAction(AccessibilityNodeInfo.AccessibilityAction(A11Y_LEFT, context.getString(R.string.bubble_a11y_left)))
        info.addAction(AccessibilityNodeInfo.AccessibilityAction(A11Y_RIGHT, context.getString(R.string.bubble_a11y_right)))
        info.addAction(AccessibilityNodeInfo.AccessibilityAction(A11Y_HIDE, context.getString(R.string.bubble_a11y_hide)))
    }

    override fun performAccessibilityAction(action: Int, arguments: Bundle?): Boolean {
        return when (action) {
            AccessibilityNodeInfo.ACTION_LONG_CLICK, A11Y_MENU -> { listener?.onLongPress(); true }
            A11Y_LEFT, A11Y_RIGHT, A11Y_HIDE -> listener?.onA11yAction(action) ?: false
            else -> super.performAccessibilityAction(action, arguments)
        }
    }

    override fun onDetachedFromWindow() {
        removeCallbacks(longPress)
        super.onDetachedFromWindow()
    }

    companion object {
        const val A11Y_MENU = 0x7f0f0001
        const val A11Y_LEFT = 0x7f0f0002
        const val A11Y_RIGHT = 0x7f0f0003
        const val A11Y_HIDE = 0x7f0f0004
    }
}
