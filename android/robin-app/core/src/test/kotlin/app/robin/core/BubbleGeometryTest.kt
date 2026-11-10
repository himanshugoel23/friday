package app.robin.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class BubbleGeometryTest {
    private val screen = ScreenBox(1080, 2200, topInset = 100, bottomInset = 120)
    private val size = 180
    private val margin = 8

    @Test fun dropOnLeftHalfSnapsToLeftEdge() {
        val p = BubblePosition.snap(screen, size, dropX = 200, dropY = 900, margin = margin)
        assertEquals(Pt(margin, 900), p)
    }

    @Test fun dropOnRightHalfSnapsToRightEdge() {
        val p = BubblePosition.snap(screen, size, dropX = 700, dropY = 900, margin = margin)
        assertEquals(Pt(1080 - size - margin, 900), p)
    }

    @Test fun centreOfBubbleDecidesTheEdge() {
        // left of bubble at 449 -> centre at 539 < 540 -> LEFT; at 451 -> centre 541 -> RIGHT
        assertEquals(Edge.LEFT, BubblePosition.edgeFor(screen, size, 449))
        assertEquals(Edge.RIGHT, BubblePosition.edgeFor(screen, size, 451))
    }

    @Test fun neverSnapsIntoStatusOrNavigationBar() {
        assertEquals(100 + margin, BubblePosition.snap(screen, size, 0, -500, margin).y)
        assertEquals(2200 - 120 - size - margin, BubblePosition.snap(screen, size, 0, 5000, margin).y)
    }

    @Test fun placementSurvivesRotationAndScreenChange() {
        val pl = BubblePosition.toPlacement(screen, size, Pt(1080 - size - margin, 1000), margin)
        assertEquals(Edge.RIGHT, pl.edge)
        val landscape = ScreenBox(2200, 1080, topInset = 60, bottomInset = 0)
        val p = BubblePosition.fromPlacement(landscape, size, pl, margin)
        assertEquals(2200 - size - margin, p.x)
        assertTrue(p.y in (60 + margin)..(1080 - size - margin))
    }

    @Test fun placementRoundTripOnSameScreen() {
        val p = Pt(margin, 700)
        val pl = BubblePosition.toPlacement(screen, size, p, margin)
        assertEquals(p, BubblePosition.fromPlacement(screen, size, pl, margin))
    }

    @Test fun badSavedFractionFallsBackToSafeValues() {
        val p = BubblePosition.fromPlacement(screen, size, Placement(Edge.LEFT, Float.NaN), margin)
        assertTrue(p.y in (100 + margin)..(2200 - 120 - size - margin))
        val q = BubblePosition.fromPlacement(screen, size, Placement(Edge.LEFT, 9f), margin)
        assertEquals(2200 - 120 - size - margin, q.y)
    }

    @Test fun defaultIsRightEdgeBelowMiddle() {
        val p = BubblePosition.default(screen, size, margin)
        assertEquals(1080 - size - margin, p.x)
        assertTrue(p.y > 1000 && p.y < 1200)
    }

    @Test fun keyboardLiftsABubbleThatWouldSitOnIt() {
        val onKeys = Pt(900, 1500)
        val lifted = BubblePosition.avoidKeyboard(screen, size, onKeys, imeTop = 1300, margin = margin)
        assertEquals(1300 - size - margin, lifted.y)
        assertEquals(900, lifted.x)
        // a bubble already above the keyboard stays; no keyboard changes nothing
        assertEquals(Pt(900, 400), BubblePosition.avoidKeyboard(screen, size, Pt(900, 400), 1300, margin))
        assertEquals(onKeys, BubblePosition.avoidKeyboard(screen, size, onKeys, null, margin))
    }

    @Test fun cardGoesToTheSideWithRoom() {
        val left = Pt(margin, 800)
        val c1 = BubblePosition.cardOrigin(screen, left, size, cardW = 700, cardH = 500, gap = 12)
        assertEquals(margin + size + 12, c1.x)
        val right = Pt(1080 - size - margin, 800)
        val c2 = BubblePosition.cardOrigin(screen, right, size, cardW = 700, cardH = 500, gap = 12)
        assertEquals(right.x - 12 - 700, c2.x)
    }

    @Test fun wideCardGoesBelowOrAboveAndStaysOnScreen() {
        val b = Pt(margin, 300)
        val c = BubblePosition.cardOrigin(screen, b, size, cardW = 1000, cardH = 500, gap = 12)
        assertEquals(b.y + size + 12, c.y) // fits below
        assertTrue(c.x >= 0 && c.x + 1000 <= 1080)
        val low = Pt(margin, 1800)
        val c3 = BubblePosition.cardOrigin(screen, low, size, 1000, 500, 12)
        assertEquals(1800 - 12 - 500, c3.y) // does not fit below, goes above
    }

    @Test fun cardNeverOverlapsTheKeyboard() {
        val b = Pt(margin, 1000)
        val c = BubblePosition.cardOrigin(screen, b, size, 700, 600, 12, imeTop = 1300)
        assertTrue(c.y + 600 <= 1300)
    }

    @Test fun draggingIsClampedInsideTheScreen() {
        assertEquals(Pt(0, 100), BubblePosition.clampWhileDragging(screen, size, -50, -50))
        assertEquals(Pt(1080 - size, 2200 - 120 - size), BubblePosition.clampWhileDragging(screen, size, 5000, 5000))
    }
}

class TouchClassifierTest {
    private fun c() = TouchClassifier(slopPx = 20, longPressMs = 600)

    @Test fun quickPressIsATap() {
        val t = c()
        t.down(100f, 100f, 0)
        assertEquals(TouchClassifier.Gesture.NONE, t.move(105f, 103f))
        assertEquals(TouchClassifier.Gesture.TAP, t.up(200))
    }

    @Test fun movingPastSlopIsADragNeverATap() {
        val t = c()
        t.down(100f, 100f, 0)
        assertEquals(TouchClassifier.Gesture.DRAG_START, t.move(160f, 100f))
        assertEquals(TouchClassifier.Gesture.DRAG_MOVE, t.move(200f, 120f))
        assertEquals(100f, t.dx, 0.01f) // distance from the touch-down point
        assertEquals(20f, t.dy, 0.01f)
        assertEquals(TouchClassifier.Gesture.DRAG_END, t.up(300))
    }

    @Test fun dragNeverTurnsIntoALongPress() {
        val t = c()
        t.down(0f, 0f, 0)
        t.move(100f, 0f)
        assertEquals(TouchClassifier.Gesture.NONE, t.tick(2_000))
    }

    @Test fun holdStillFiresLongPressOnceAndReleaseIsNotATap() {
        val t = c()
        t.down(0f, 0f, 0)
        assertEquals(TouchClassifier.Gesture.NONE, t.tick(500))
        assertEquals(TouchClassifier.Gesture.LONG_PRESS, t.tick(650))
        assertEquals(TouchClassifier.Gesture.NONE, t.tick(900))
        assertEquals(TouchClassifier.Gesture.NONE, t.up(1_000))
    }

    @Test fun releaseAfterLongTimeWithoutTickStillCountsAsLongPress() {
        val t = c()
        t.down(0f, 0f, 0)
        assertEquals(TouchClassifier.Gesture.LONG_PRESS, t.up(800))
    }

    @Test fun cancelAbandonsEverything() {
        val t = c()
        t.down(0f, 0f, 0)
        assertEquals(TouchClassifier.Gesture.CANCELLED, t.cancel())
        assertEquals(TouchClassifier.Gesture.NONE, t.up(100))
        assertEquals(TouchClassifier.Gesture.NONE, t.cancel())
    }
}
