package app.robin.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class BubbleStateTest {
    @Test fun voiceTurnStatesMapOneToOne() {
        assertEquals(BubbleState.IDLE, BubbleStates.from(VoiceTurn.State.Idle))
        assertEquals(BubbleState.LISTENING, BubbleStates.from(VoiceTurn.State.Recording(0, false, 0)))
        assertEquals(BubbleState.SENDING, BubbleStates.from(VoiceTurn.State.Uploading(3)))
        assertEquals(BubbleState.ANSWERING, BubbleStates.from(VoiceTurn.State.Answering(VoiceTurn.Answer("x", null))))
        assertEquals(BubbleState.OFFLINE, BubbleStates.from(VoiceTurn.State.Offline))
        assertEquals(BubbleState.PROBLEM, BubbleStates.from(VoiceTurn.State.Error(VoiceTurn.Failure.SERVER)))
    }

    @Test fun colourIsNeverTheOnlyCue() {
        val looks = BubbleState.values().map { BubbleStates.look(it) }
        assertEquals("shape", looks.size, looks.map { it.shape }.toSet().size)
        assertEquals("glyph", looks.size, looks.map { it.glyph }.toSet().size)
        assertEquals("word", looks.size, looks.map { it.word }.toSet().size)
    }

    @Test fun problemStatesBuzzDifferentlyAndAreAnnounced() {
        for (s in listOf(BubbleState.OFFLINE, BubbleState.PROBLEM)) {
            val l = BubbleStates.look(s)
            assertEquals(Haptic.REJECT, l.haptic)
            assertTrue(l.announce)
        }
        assertEquals(Haptic.NONE, BubbleStates.look(BubbleState.IDLE).haptic)
        assertTrue(!BubbleStates.look(BubbleState.IDLE).announce)
    }

    @Test fun cardsForEveryFailureAreDistinctWhereTheyShouldBe() {
        val keys = VoiceTurn.Failure.values().map { BubbleCards.from(VoiceTurn.State.Error(it))!!.key }
        assertEquals(CardKey.NO_MIC, keys[VoiceTurn.Failure.NO_MIC.ordinal])
        assertEquals(CardKey.NOT_SET_UP, keys[VoiceTurn.Failure.UNPAIRED.ordinal])
        assertEquals(CardKey.FAILED, keys[VoiceTurn.Failure.SERVER.ordinal])
        assertEquals(CardKey.FAILED, keys[VoiceTurn.Failure.REJECTED.ordinal])
    }

    @Test fun answerCardCarriesTheServerTextOrAFallback() {
        assertEquals(BubbleCard(CardKey.ANSWER, "Hello"), BubbleCards.from(VoiceTurn.State.Answering(VoiceTurn.Answer("Hello", null))))
        assertEquals(BubbleCard(CardKey.ANSWER_FALLBACK), BubbleCards.from(VoiceTurn.State.Answering(VoiceTurn.Answer(null, "https://x/a"))))
        assertNull(BubbleCards.from(VoiceTurn.State.Idle))
        assertNull(BubbleCards.from(VoiceTurn.State.Uploading(2)))
        assertNotNull(BubbleCards.from(VoiceTurn.State.Recording(0, false, 0)))
        assertEquals(CardKey.OFFLINE, BubbleCards.from(VoiceTurn.State.Offline)!!.key)
    }

    @Test fun polygonHasTheRightCornersAroundTheCentre() {
        val p = Polygons.points(4, 100f, 100f, 50f)
        assertEquals(4, p.size)
        assertEquals(100f, p[0].x, 0.01f); assertEquals(50f, p[0].y, 0.01f) // first corner at the top
        assertEquals(150f, p[1].x, 0.01f); assertEquals(100f, p[1].y, 0.01f)
        for (n in listOf(3, 6, 8)) assertEquals(n, Polygons.points(n, 0f, 0f, 10f).size)
    }
}
