package app.robin.core

import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

private class FakeRecorder(var startOk: Boolean = true, var bytes: ByteArray? = byteArrayOf(1, 2, 3)) : VoiceRecorderPort {
    var level = 0
    var recording = false
    var fileExists = false
    var deletes = 0
    var cancels = 0
    override fun start(): Boolean { if (startOk) { recording = true; fileExists = true }; return startOk }
    override fun stop(): ByteArray? { recording = false; return bytes }
    override fun cancel() { recording = false; fileExists = false; cancels++ }
    override fun deleteFile() { fileExists = false; deletes++ }
    override fun level() = level
}

class VoiceTurnTest {
    private val rec = FakeRecorder()
    private val sent = mutableListOf<Triple<ByteArray, String, Int>>()
    private var results = ArrayDeque<ApiResult<VoiceReply>>()
    private val sleeps = mutableListOf<Long>()

    private fun turn() = VoiceTurn(rec, { a, m, d -> sent += Triple(a, m, d); results.removeFirst() })

    private fun ok(text: String? = "hello", url: String? = null) = ApiResult.Ok(VoiceReply(true, text, url))
    private fun err(e: ApiError) = ApiResult.Err(e)

    @Test fun happyPathTapToTapThenAnswerThenIdle() {
        val t = turn()
        results += ok()
        assertTrue(t.tap(0) is VoiceTurn.State.Recording)
        assertTrue(rec.recording)
        assertEquals(VoiceTurn.State.Uploading(3), t.tap(2_400))
        val s = t.upload { sleeps += it }
        assertEquals(VoiceTurn.State.Answering(VoiceTurn.Answer("hello", null)), s)
        assertEquals(1, sent.size)
        assertEquals("audio/mp4", sent[0].second)
        assertEquals(3, sent[0].third)
        assertEquals(VoiceTurn.State.Idle, t.answerDone())
        assertTrue(sleeps.isEmpty())
    }

    @Test fun tapTooEarlyIsTooShortAndNothingIsSent() {
        val t = turn()
        t.tap(0)
        assertEquals(VoiceTurn.State.Error(VoiceTurn.Failure.TOO_SHORT), t.tap(400))
        assertTrue(sent.isEmpty())
        assertFalse(rec.fileExists)
    }

    @Test fun maximumLengthStopsByItself() {
        val t = turn()
        t.tap(0)
        rec.level = 5000
        assertTrue(t.tick(29_900) is VoiceTurn.State.Recording)
        assertEquals(VoiceTurn.State.Uploading(30), t.tick(30_000))
    }

    @Test fun silenceAfterSpeechStopsButSilenceBeforeSpeechDoesNot() {
        val t = turn()
        t.tap(0)
        rec.level = 100
        assertTrue(t.tick(5_000) is VoiceTurn.State.Recording) // nothing said yet: keep waiting
        rec.level = 6000
        t.tick(6_000)
        rec.level = 100
        assertTrue(t.tick(8_000) is VoiceTurn.State.Recording) // 2.0 s of quiet
        assertTrue(t.tick(8_500) is VoiceTurn.State.Uploading) // 2.5 s of quiet
    }

    @Test fun nothingSaidGivesUpAndReleasesTheMicrophone() {
        val t = turn()
        t.tap(0)
        rec.level = 0
        assertEquals(VoiceTurn.State.Error(VoiceTurn.Failure.NO_SPEECH), t.tick(10_000))
        assertFalse(rec.recording)
        assertFalse(rec.fileExists)
    }

    @Test fun microphoneThatCannotStartIsAnError() {
        rec.startOk = false
        assertEquals(VoiceTurn.State.Error(VoiceTurn.Failure.NO_MIC), turn().tap(0))
    }

    @Test fun fileIsDeletedBeforeTheUploadAndAfterEveryAttempt() {
        val t = turn()
        var fileDuringSend = true
        val t2 = VoiceTurn(rec, { _, _, _ -> fileDuringSend = rec.fileExists; err(ApiError.ConsentRequired) })
        t2.tap(0)
        t2.tap(2_000)
        t2.upload { }
        assertFalse("the file must already be gone while the bytes are on the wire", fileDuringSend)
        assertFalse(rec.fileExists)
        assertTrue(t.state is VoiceTurn.State.Idle)
    }

    @Test fun networkFailuresRetryInMemoryThenGoOffline() {
        val t = turn()
        results += err(ApiError.Network("X")); results += err(ApiError.Network("X")); results += err(ApiError.Network("X"))
        t.tap(0); t.tap(2_000)
        assertEquals(VoiceTurn.State.Offline, t.upload { sleeps += it })
        assertEquals(3, sent.size)
        assertEquals(listOf(1_500L, 1_500L), sleeps)
        assertArrayEquals(sent[0].first, sent[2].first) // same bytes, never re-read from disk
        assertFalse(rec.fileExists)
    }

    @Test fun retryRecoversAfterOneFailure() {
        val t = turn()
        results += err(ApiError.Unavailable(503)); results += ok("back")
        t.tap(0); t.tap(2_000)
        assertEquals(VoiceTurn.State.Answering(VoiceTurn.Answer("back", null)), t.upload { })
    }

    @Test fun offlineThenTapRecordsAgain() {
        val t = turn()
        results += err(ApiError.Network("X")); results += err(ApiError.Network("X")); results += err(ApiError.Network("X"))
        t.tap(0); t.tap(2_000); t.upload { }
        assertTrue(t.tap(10_000) is VoiceTurn.State.Recording)
    }

    @Test fun serverRefusalsMapToStatesAndAreNotRetried() {
        fun run(e: ApiError): VoiceTurn.State {
            sent.clear(); results.clear(); results += err(e)
            val t = turn(); t.tap(0); t.tap(2_000)
            val s = t.upload { }
            assertEquals(1, sent.size)
            return s
        }
        assertEquals(VoiceTurn.State.Error(VoiceTurn.Failure.NO_CONSENT), run(ApiError.ConsentRequired))
        assertEquals(VoiceTurn.State.Error(VoiceTurn.Failure.UNPAIRED), run(ApiError.Unauthorized))
        assertEquals(VoiceTurn.State.Error(VoiceTurn.Failure.BUSY), run(ApiError.RateLimited))
        assertEquals(VoiceTurn.State.Error(VoiceTurn.Failure.REJECTED), run(ApiError.TooLarge))
        assertEquals(VoiceTurn.State.Error(VoiceTurn.Failure.SERVER), run(ApiError.Malformed("x", "y")))
    }

    @Test fun acceptedFalseIsNotUnderstoodAndBlankTextBecomesNull() {
        results += ApiResult.Ok(VoiceReply(false, null))
        val t = turn(); t.tap(0); t.tap(2_000)
        assertEquals(VoiceTurn.State.Error(VoiceTurn.Failure.NOT_UNDERSTOOD), t.upload { })
        results += ok("  ", "https://x/y.mp3")
        val t2 = turn(); t2.tap(0); t2.tap(2_000)
        assertEquals(VoiceTurn.State.Answering(VoiceTurn.Answer(null, "https://x/y.mp3")), t2.upload { })
    }

    @Test fun tappingWhileAnsweringInterruptsAndRecordsAgain() {
        val t = turn(); results += ok()
        t.tap(0); t.tap(2_000); t.upload { }
        assertTrue(t.tap(5_000) is VoiceTurn.State.Recording)
    }

    @Test fun leavingTheScreenStopsTheMicAndDropsTheTurn() {
        val t = turn()
        t.tap(0)
        assertEquals(VoiceTurn.State.Idle, t.cancel())
        assertFalse(rec.recording)
        assertFalse(rec.fileExists)
        // ignored: uploading is not interrupted, and a late upload() with no upload pending does nothing
        assertEquals(VoiceTurn.State.Idle, t.upload { })
        assertTrue(sent.isEmpty())
    }

    @Test fun dismissClearsErrorsOnly() {
        val t = turn(); rec.startOk = false; t.tap(0)
        assertEquals(VoiceTurn.State.Idle, t.dismiss())
    }

    @Test fun nullRecordingIsTooShort() {
        rec.bytes = null
        val t = turn(); t.tap(0); t.tap(2_000)
        assertEquals(VoiceTurn.State.Error(VoiceTurn.Failure.TOO_SHORT), t.upload { })
        assertNull(rec.bytes)
    }

    private fun assertFalse(msg: String, b: Boolean) = org.junit.Assert.assertFalse(msg, b)
    private fun assertFalse(b: Boolean) = org.junit.Assert.assertFalse(b)
}

class SpeechPlanAndLinkTest {
    private val base = "https://robin.example"

    @Test fun serverAudioWinsWhenHttpsAndSameHost() {
        val a = VoiceTurn.Answer("hi", "https://robin.example/audio/1.mp3")
        assertEquals(SpeechPlan.PlayUrl("https://robin.example/audio/1.mp3"), SpeechPlan.choose(a, base, "hi"))
    }

    @Test fun otherHostsAndPlainHttpFallBackToTextToSpeech() {
        for (u in listOf("http://robin.example/a.mp3", "https://evil.example/a.mp3", "https://robin.example.evil.io/a", "https://u:p@robin.example/a", "not a url")) {
            assertEquals(u, SpeechPlan.Speak("hi", "hi-IN"), SpeechPlan.choose(VoiceTurn.Answer("hi", u), base, "hi"))
        }
    }

    @Test fun languagesMapToLocales() {
        assertEquals("hi-IN", SpeechPlan.localeTag("hi"))
        assertEquals("en-IN", SpeechPlan.localeTag("hinglish"))
        assertEquals("en-IN", SpeechPlan.localeTag("en"))
        assertEquals("ta-IN", SpeechPlan.localeTag("ta"))
        assertEquals("en-IN", SpeechPlan.localeTag("../x"))
    }

    @Test fun noTextAndNoAudioIsSilent() {
        assertEquals(SpeechPlan.Silent, SpeechPlan.choose(VoiceTurn.Answer(null, null), base, "en"))
    }

    @Test fun pairLinkAndQrPayload() {
        assertEquals("K7M2QX9A", PairLink.parse("robin://pair?code=K7M2QX9A"))
        assertEquals("K7M2QX9A", PairLink.parse("robin://pair?x=1&code=k7m2-qx9a"))
        assertEquals("K7M2QX9A", PairLink.parse("K7M2 QX9A"))
        assertNull(PairLink.parse("robin://other?code=K7M2QX9A"))
        assertNull(PairLink.parse("robin://pair?code=short"))
        assertNull(PairLink.parse("https://evil.example/pair?code=K7M2QX9A"))
        assertNull(PairLink.parse(null))
    }
}

class VoiceTurnWithSharedFixtureTest {
    @Test fun turnAgainstTheContractVoiceFixtureEndsInAnswering() {
        val fx = Fixtures.byName("voice")
        val client = ApiClient(BASE, FakeTransport().reply(fx.status, fx.responseText()), MemTokens(TOKEN))
        val rec = FakeRecorder()
        val t = VoiceTurn(rec, { a, m, d -> client.voice(a, m, d) })
        t.tap(0); t.tap(3_000)
        assertEquals(VoiceTurn.State.Answering(VoiceTurn.Answer(null, null)), t.upload { })
        val nc = Fixtures.byName("err_voice_no_consent")
        val c2 = ApiClient(BASE, FakeTransport().reply(nc.status, nc.responseText()), MemTokens(TOKEN))
        val t2 = VoiceTurn(rec, { a, m, d -> c2.voice(a, m, d) })
        t2.tap(0); t2.tap(3_000)
        assertEquals(VoiceTurn.State.Error(VoiceTurn.Failure.NO_CONSENT), t2.upload { })
    }
}
