package app.robin.parent

import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.drawable.GradientDrawable
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.view.Gravity
import android.view.MotionEvent
import android.widget.TextView

/**
 * A big press-and-hold button. It only reports touch timing (down / tick / up / abort); the rules (2 seconds, minimum and
 * maximum voice length) live in the tested :core gesture classes. Ticks run only while a finger is down.
 */
class HoldButton(context: Context, colour: Int) : TextView(context) {
    var onDown: (Long) -> Unit = {}
    var onTick: (Long) -> Unit = {}
    var onUp: (Long) -> Unit = {}
    var onAbort: () -> Unit = {}

    /** 0..1 fill shown along the bottom edge. */
    var progress: Float = 0f
        set(v) {
            field = v.coerceIn(0f, 1f)
            invalidate()
        }

    private var held = false
    private val handler = Handler(Looper.getMainLooper())
    private val bar = Paint().apply { color = Color.argb(150, 255, 255, 255) }
    private val ticker = object : Runnable {
        override fun run() {
            if (!held) return
            onTick(SystemClock.elapsedRealtime())
            if (held) handler.postDelayed(this, 50)
        }
    }

    init {
        gravity = Gravity.CENTER
        setTextColor(Color.WHITE)
        textSize = 26f
        setTypeface(typeface, android.graphics.Typeface.BOLD)
        background = GradientDrawable().apply {
            setColor(colour)
            cornerRadius = 48f
        }
        isClickable = true
    }

    override fun onTouchEvent(e: MotionEvent): Boolean {
        when (e.actionMasked) {
            MotionEvent.ACTION_DOWN -> {
                parent?.requestDisallowInterceptTouchEvent(true)
                held = true
                onDown(SystemClock.elapsedRealtime())
                handler.post(ticker)
            }
            MotionEvent.ACTION_UP -> if (held) {
                held = false
                handler.removeCallbacks(ticker)
                onUp(SystemClock.elapsedRealtime())
                performClick()
            }
            MotionEvent.ACTION_CANCEL -> abort()
            MotionEvent.ACTION_MOVE -> {
                // sliding the finger off the button abandons the press
                if (held && (e.x < 0 || e.y < 0 || e.x > width || e.y > height)) abort()
            }
        }
        return true
    }

    override fun performClick(): Boolean = super.performClick()

    /** Also called by the screen when it pauses, so nothing keeps running (or recording) in the background. */
    fun abort() {
        if (!held) return
        held = false
        handler.removeCallbacks(ticker)
        onAbort()
    }

    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)
        if (progress > 0f) canvas.drawRect(0f, height - 16f, width * progress, height.toFloat(), bar)
    }

    override fun onDetachedFromWindow() {
        handler.removeCallbacks(ticker)
        if (held) abort()
        super.onDetachedFromWindow()
    }
}
