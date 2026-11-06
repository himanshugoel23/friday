package app.robin.core

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class TransparencyScreenModelTest {
    private fun reply(patch: (JSONObject) -> Unit = {}): TransparencyReply {
        val o = JSONObject(Fixtures.byName("transparency").responseText())
        patch(o)
        return TransparencyReply.parse(o)
    }

    private val order = listOf("calls", "camera", "voice_messages")

    @Test fun normalScreenListsWhatIsOnAndWhatIsNever() {
        val m = TransparencyScreenModel.from(reply { it.put("paused", false).getJSONObject("learning_mode").put("active", false) }, order)
        assertEquals(TransparencyScreenModel.Banner.NORMAL, m.banner)
        assertTrue(m.collected.isNotEmpty())
        assertTrue("call recordings or audio" in m.neverCollected)
        assertEquals(listOf("calls", "voice_messages"), m.allowedItems.take(2))
        assertEquals(listOf("camera"), m.withdrawnItems) // the fixture was taken after the phone withdrew the camera
        assertEquals(1, m.toldFamily.size)
        assertEquals(0, m.learningDaysLeft)
        assertNull(m.learningMeaning)
        assertFalse(m.nothingOn)
    }

    @Test fun pausedWinsOverLearning() {
        val m = TransparencyScreenModel.from(reply { it.put("paused", true).getJSONObject("learning_mode").put("active", true) })
        assertEquals(TransparencyScreenModel.Banner.PAUSED, m.banner)
        assertTrue(m.nothingOn)
    }

    @Test fun learningWeekShowsDaysLeftAndTheServersMeaning() {
        val m = TransparencyScreenModel.from(reply {
            it.put("paused", false).getJSONObject("learning_mode").put("active", true).put("days_left", 4)
        })
        assertEquals(TransparencyScreenModel.Banner.LEARNING, m.banner)
        assertEquals(4, m.learningDaysLeft)
        assertTrue(m.learningMeaning!!.isNotEmpty())
    }

    @Test fun withdrawnItemsAreSeparatedAndNothingOnWhenAllWithdrawn() {
        val m = TransparencyScreenModel.from(reply {
            val c = it.getJSONObject("consent")
            c.keys().asSequence().toList().forEach { k -> c.put(k, false) }
            it.put("paused", false)
        }, order)
        assertTrue(m.allowedItems.isEmpty())
        assertEquals(12, m.withdrawnItems.size)
        assertEquals("calls", m.withdrawnItems[0])
        assertTrue(m.nothingOn)
    }

    @Test fun newestToldEntryFirstAndCountersSorted() {
        val m = TransparencyScreenModel.from(reply {
            val a = it.getJSONArray("told_child")
            a.put(JSONObject().put("ts_ms", 5L).put("tier", "INFO").put("scenario", "ACK").put("why", "w"))
            a.put(JSONObject().put("ts_ms", 99_999_999_999_999L).put("tier", "HIGH").put("scenario", "S2").put("why", "w2"))
        })
        assertEquals(99_999_999_999_999L, m.toldFamily.first().tsMs)
        assertEquals(m.counters.map { it.first }.sorted(), m.counters.map { it.first })
    }
}
