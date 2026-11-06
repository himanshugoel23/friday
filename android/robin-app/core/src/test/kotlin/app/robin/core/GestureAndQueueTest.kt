package app.robin.core

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class SosGestureTest {
    @Test fun firesOnlyAfterTwoSecondsHeld() {
        val g = SosGesture()
        assertEquals(SosGesture.State.Idle, g.state)
        g.down(1000)
        assertEquals(0.0f, (g.tick(1000) as SosGesture.State.Holding).progress, 0.001f)
        assertEquals(0.5f, (g.tick(2000) as SosGesture.State.Holding).progress, 0.001f)
        assertTrue(g.tick(2999) is SosGesture.State.Holding)
        assertEquals(SosGesture.State.Fired, g.tick(3000))
    }

    @Test fun tapOrEarlyReleaseNeverFires() {
        val g = SosGesture()
        g.down(0)
        assertEquals(SosGesture.State.Idle, g.up(150))
        g.down(1000)
        g.tick(2500)
        assertEquals(SosGesture.State.Idle, g.up(2999))
    }

    @Test fun releaseAfterTheHoldTimeStillFiresEvenWithoutATick() {
        val g = SosGesture()
        g.down(0)
        assertEquals(SosGesture.State.Fired, g.up(2000))
    }

    @Test fun cancelAbandonsAHoldButNotAFire() {
        val g = SosGesture()
        g.down(0)
        g.tick(1000)
        assertEquals(SosGesture.State.Idle, g.cancel())
        g.down(0)
        g.tick(2000)
        assertEquals(SosGesture.State.Fired, g.cancel())
        g.reset()
        assertEquals(SosGesture.State.Idle, g.state)
    }

    @Test fun secondFingerDoesNotRestartTheTimer() {
        val g = SosGesture()
        g.down(0)
        g.down(1500)
        assertEquals(SosGesture.State.Fired, g.tick(2000))
    }

    @Test fun clockGoingBackwardsIsHarmless() {
        val g = SosGesture()
        g.down(5000)
        assertEquals(0.0f, (g.tick(4000) as SosGesture.State.Holding).progress, 0.001f)
    }
}

class VoiceNoteGestureTest {
    @Test fun shortPressIsTooShort() {
        val g = VoiceNoteGesture()
        g.down(0)
        assertEquals(VoiceNoteGesture.State.TooShort, g.up(900))
    }

    @Test fun releaseGivesRoundedUpSeconds() {
        val g = VoiceNoteGesture()
        g.down(0)
        assertEquals(VoiceNoteGesture.State.Done(1, false), g.up(1000))
        g.reset(); g.down(0)
        assertEquals(VoiceNoteGesture.State.Done(4, false), g.up(3200))
    }

    @Test fun stopsByItselfAtSixtySeconds() {
        val g = VoiceNoteGesture()
        g.down(0)
        assertTrue(g.tick(59_999) is VoiceNoteGesture.State.Recording)
        assertEquals(VoiceNoteGesture.State.Done(60, true), g.tick(60_000))
        assertEquals(VoiceNoteGesture.State.Done(60, true), g.up(70_000)) // the late release changes nothing
    }

    @Test fun cancelNeverKeepsTheMicrophoneOpen() {
        val g = VoiceNoteGesture()
        g.down(0)
        assertEquals(VoiceNoteGesture.State.Idle, g.cancel())
        assertEquals(VoiceNoteGesture.State.Idle, g.up(5000))
    }
}

class SosSenderTest {
    private fun client(t: FakeTransport) = ApiClient(BASE, t, MemTokens(TOKEN))
    private val sosOk = """{"ok": true, "message": "line"}"""

    @Test fun sendsAtOnceWithoutWaiting() {
        val slept = mutableListOf<Long>()
        val o = SosSender(client(FakeTransport().reply(200, sosOk)), { slept += it }).send(null, null)
        assertEquals(SosSender.Outcome.Sent("line", 1), o)
        assertTrue(slept.isEmpty())
    }

    @Test fun retriesEveryTenSecondsAndSucceeds() {
        val t = FakeTransport().fail().reply(503, "{}").reply(200, sosOk)
        val slept = mutableListOf<Long>()
        val seen = mutableListOf<Int>()
        val o = SosSender(client(t), { slept += it }).send(28.6, 77.2) { seen += it }
        assertEquals(SosSender.Outcome.Sent("line", 3), o)
        assertEquals(listOf(10_000L, 10_000L), slept)
        assertEquals(listOf(1, 2, 3), seen)
        assertEquals(28.6, t.lastBody().getDouble("lat"), 0.0)
    }

    @Test fun givesUpAfterTwoMinutesButSaysSo() {
        val t = FakeTransport()
        repeat(40) { t.fail() }
        var total = 0L
        val o = SosSender(client(t), { total += it }).send(null, null) as SosSender.Outcome.NotSent
        assertEquals(120_000L, total)
        assertEquals(13, o.attempts) // at 0, 10, ... 120 s
        assertTrue(o.lastError is ApiError.Network)
    }

    @Test fun doesNotRetryAfterARevokedToken() {
        val o = SosSender(client(FakeTransport().reply(404, "{}")), { error("must not sleep") }).send(null, null)
        assertEquals(SosSender.Outcome.NotSent(ApiError.Unauthorized, 1), o)
    }

    @Test fun interruptedWhileWaitingStops() {
        val t = FakeTransport().fail()
        val o = SosSender(client(t), { throw InterruptedException() }).send(null, null)
        assertTrue(o is SosSender.Outcome.NotSent)
    }
}

class PromptQueueTest {
    private fun prompt(id: String, tier: String = "HIGH", from: Long = 0, until: Long = 1_000_000): Prompt {
        val base = Prompt.parse(JSONObject(Fixtures.byName("prompts").responseText()).getJSONArray("prompts").getJSONObject(0))
        return base.copy(promptId = id, tier = tier, notBeforeMs = from, expiresMs = until)
    }

    @Test fun holdsBackUntilNotBeforeAndDropsAfterExpiry() {
        val q = PromptQueue()
        q.replaceFromServer(listOf(prompt("night_prompt", from = 5000, until = 9000)))
        assertNull(q.next(4999))
        assertEquals(5000L, q.nextDueAt(0))
        assertEquals("night_prompt", q.next(5000)!!.promptId)
        assertNull(q.next(9000))
    }

    @Test fun mostSeriousFirstThenOldest() {
        val q = PromptQueue()
        q.replaceFromServer(listOf(
            prompt("info_prompt", "INFO", 1), prompt("high_old_x", "HIGH", 2), prompt("high_new_x", "HIGH", 3),
            prompt("sos_prompt", "EMERGENCY", 9), prompt("weird_tier", "WEIRD", 4),
        ))
        assertEquals(
            listOf("sos_prompt", "high_old_x", "high_new_x", "weird_tier", "info_prompt"),
            q.due(10).map { it.promptId },
        )
    }

    @Test fun answeredPromptStaysHiddenWhileServerStillListsIt() {
        val q = PromptQueue()
        val p = prompt("prompt_one")
        q.replaceFromServer(listOf(p))
        q.markAnswered("prompt_one")
        assertNull(q.next(10))
        q.replaceFromServer(listOf(p)) // the server has not processed the ack yet
        assertNull(q.next(10))
        q.addAll(listOf(p))
        assertNull(q.next(10))
        q.replaceFromServer(emptyList()) // gone on the server: forget it
        q.replaceFromServer(listOf(p)) // a genuinely new prompt with a reused id would show again
        assertEquals("prompt_one", q.next(10)!!.promptId)
    }

    @Test fun serverListIsAuthoritative() {
        val q = PromptQueue()
        q.replaceFromServer(listOf(prompt("prompt_aaa"), prompt("prompt_bbb")))
        q.replaceFromServer(listOf(prompt("prompt_bbb")))
        assertEquals(listOf("prompt_bbb"), q.due(1).map { it.promptId })
        q.addAll(listOf(prompt("prompt_ccc")))
        assertEquals(2, q.size())
        q.clear()
        assertEquals(0, q.size())
    }

    @Test fun textFallsBackToEnglish() {
        val p = prompt("prompt_one").copy(text = mapOf("en" to "hello"))
        assertEquals("hello", p.textFor("hi"))
    }
}
