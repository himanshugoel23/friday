package app.robin.core

import kotlin.math.max
import kotlin.math.min

enum class Edge { LEFT, RIGHT }

/** Pixels. [topInset] is the status bar / cutout, [bottomInset] the navigation bar. */
data class ScreenBox(val width: Int, val height: Int, val topInset: Int = 0, val bottomInset: Int = 0)

data class Pt(val x: Int, val y: Int)

/** What is remembered between runs: the edge and how far down (0..1 of the free height), so a rotation or a different screen still works. */
data class Placement(val edge: Edge, val yFraction: Float)

/**
 * Where the bubble sits. All pure integer/float maths; the Android layer passes real screen sizes. The bubble always rests
 * against the left or right edge (never in the middle of the screen), stays out of the status and navigation bars, and
 * steps above the keyboard when the keyboard is up.
 */
object BubblePosition {
    const val DEFAULT_Y_FRACTION = 0.55f

    private fun minY(s: ScreenBox, margin: Int) = s.topInset + margin
    private fun maxY(s: ScreenBox, size: Int, margin: Int) = max(minY(s, margin), s.height - s.bottomInset - size - margin)
    private fun xFor(s: ScreenBox, size: Int, edge: Edge, margin: Int) = if (edge == Edge.LEFT) margin else max(margin, s.width - size - margin)

    fun default(s: ScreenBox, size: Int, margin: Int): Pt = fromPlacement(s, size, Placement(Edge.RIGHT, DEFAULT_Y_FRACTION), margin)

    /** The edge nearest the bubble's centre when it is let go. */
    fun edgeFor(s: ScreenBox, size: Int, dropX: Int): Edge = if (dropX + size / 2 < s.width / 2) Edge.LEFT else Edge.RIGHT

    /** Where the bubble comes to rest after being dropped at ([dropX], [dropY]) (top-left corner of the bubble). */
    fun snap(s: ScreenBox, size: Int, dropX: Int, dropY: Int, margin: Int): Pt {
        val edge = edgeFor(s, size, dropX)
        return Pt(xFor(s, size, edge, margin), dropY.coerceIn(minY(s, margin), maxY(s, size, margin)))
    }

    /** Keeps a bubble that is being dragged inside the screen (no snap yet). */
    fun clampWhileDragging(s: ScreenBox, size: Int, x: Int, y: Int): Pt =
        Pt(x.coerceIn(0, max(0, s.width - size)), y.coerceIn(s.topInset, max(s.topInset, s.height - s.bottomInset - size)))

    fun toPlacement(s: ScreenBox, size: Int, p: Pt, margin: Int): Placement {
        val lo = minY(s, margin)
        val hi = maxY(s, size, margin)
        val f = if (hi <= lo) DEFAULT_Y_FRACTION else (p.y - lo).toFloat() / (hi - lo)
        return Placement(edgeFor(s, size, p.x), f.coerceIn(0f, 1f))
    }

    fun fromPlacement(s: ScreenBox, size: Int, pl: Placement, margin: Int): Pt {
        val lo = minY(s, margin)
        val hi = maxY(s, size, margin)
        val f = if (pl.yFraction.isNaN()) DEFAULT_Y_FRACTION else pl.yFraction.coerceIn(0f, 1f)
        return Pt(xFor(s, size, pl.edge, margin), lo + ((hi - lo) * f).toInt())
    }

    /**
     * Keyboard up: the bubble must not sit on the keyboard. [imeTop] is the y of the keyboard's top edge, or null when no
     * keyboard is showing. A bubble that overlaps is lifted so its bottom is [margin] above the keyboard. [Unverified] on
     * real phones: an overlay window may not be told the keyboard size on every Android version/OEM, which is why the
     * person can also hide the bubble.
     */
    fun avoidKeyboard(s: ScreenBox, size: Int, p: Pt, imeTop: Int?, margin: Int): Pt {
        if (imeTop == null) return p
        val limit = imeTop - size - margin
        return if (p.y > limit) Pt(p.x, max(minY(s, margin), limit)) else p
    }

    /**
     * Top-left corner for a card or menu of [cardW] x [cardH] next to the bubble: on the side with room (a bubble on the
     * left edge gets its card on the right), aligned with the bubble's top, never off the screen or into the system bars.
     * If the card is wider than the room beside the bubble it goes above or below it, full width.
     */
    fun cardOrigin(s: ScreenBox, bubble: Pt, size: Int, cardW: Int, cardH: Int, gap: Int, imeTop: Int? = null): Pt {
        val bottomLimit = (imeTop ?: (s.height - s.bottomInset))
        val roomRight = s.width - (bubble.x + size + gap)
        val roomLeft = bubble.x - gap
        val y0 = bubble.y.coerceIn(s.topInset, max(s.topInset, bottomLimit - cardH))
        return when {
            roomRight >= cardW -> Pt(bubble.x + size + gap, y0)
            roomLeft >= cardW -> Pt(bubble.x - gap - cardW, y0)
            else -> {
                val w = min(cardW, s.width)
                val x = ((s.width - w) / 2).coerceAtLeast(0)
                val below = bubble.y + size + gap
                val above = bubble.y - gap - cardH
                val y = if (below + cardH <= bottomLimit) below else max(s.topInset, above)
                Pt(x, y)
            }
        }
    }
}

/**
 * Turns raw touches on the bubble into one decision: a tap (talk), a drag (move), or a long press (menu). Time and
 * positions are passed in. A finger that moves further than [slopPx] is a drag, never a tap or a long press.
 */
class TouchClassifier(private val slopPx: Int, private val longPressMs: Long = DEFAULT_LONG_PRESS_MS) {
    enum class Gesture { NONE, DRAG_START, DRAG_MOVE, LONG_PRESS, TAP, DRAG_END, CANCELLED }

    private enum class Phase { IDLE, PRESSED, DRAGGING, LONG }

    private var phase = Phase.IDLE
    private var downX = 0f
    private var downY = 0f
    private var downT = 0L

    /** How far the finger is from where it went down (valid while dragging). */
    var dx = 0f; private set
    var dy = 0f; private set

    fun down(x: Float, y: Float, t: Long): Gesture {
        phase = Phase.PRESSED; downX = x; downY = y; downT = t; dx = 0f; dy = 0f
        return Gesture.NONE
    }

    fun move(x: Float, y: Float): Gesture {
        if (phase == Phase.IDLE || phase == Phase.LONG) return Gesture.NONE
        dx = x - downX; dy = y - downY
        if (phase == Phase.PRESSED) {
            if (dx * dx + dy * dy <= slopPx.toLong() * slopPx) return Gesture.NONE
            phase = Phase.DRAGGING
            return Gesture.DRAG_START
        }
        return Gesture.DRAG_MOVE
    }

    /** Call from a delayed callback (or any time). Fires the long press once when the finger has stayed put long enough. */
    fun tick(t: Long): Gesture {
        if (phase == Phase.PRESSED && t - downT >= longPressMs) { phase = Phase.LONG; return Gesture.LONG_PRESS }
        return Gesture.NONE
    }

    fun up(t: Long): Gesture {
        val p = phase
        phase = Phase.IDLE
        return when (p) {
            Phase.PRESSED -> if (t - downT >= longPressMs) Gesture.LONG_PRESS else Gesture.TAP
            Phase.DRAGGING -> Gesture.DRAG_END
            // The long press already fired on tick: lifting the finger must not also count as a tap.
            Phase.LONG, Phase.IDLE -> Gesture.NONE
        }
    }

    fun cancel(): Gesture {
        val was = phase
        phase = Phase.IDLE
        return if (was == Phase.IDLE) Gesture.NONE else Gesture.CANCELLED
    }

    companion object {
        const val DEFAULT_LONG_PRESS_MS = 600L
    }
}
