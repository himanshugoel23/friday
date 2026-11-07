package app.robin.core

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ApiClientTest {
    private fun client(t: FakeTransport, token: String? = TOKEN) = ApiClient("$BASE/", t, MemTokens(token))
    private fun errOf(r: ApiResult<*>): ApiError = (r as ApiResult.Err).error

    @Test fun baseUrlTrailingSlashIsTrimmed() {
        val t = FakeTransport().reply(200, """{"paused": false}""")
        client(t).resume()
        assertEquals("$BASE/robin/device/resume", t.last.url)
    }

    @Test fun noTokenMeansUnauthorizedWithoutAnyRequest() {
        val t = FakeTransport()
        assertEquals(ApiError.Unauthorized, errOf(client(t, token = null).sos()))
        assertTrue(t.sent.isEmpty())
    }

    @Test fun pairSendsNoAuthorizationHeader() {
        val t = FakeTransport().reply(404, """{"detail":"Not Found"}""")
        val r = client(t, token = TOKEN).pair("K7M2QX9A", "1.0.0", 34)
        assertFalse(t.last.headers.containsKey("Authorization"))
        assertEquals(ApiError.PairingRejected, errOf(r))
    }

    @Test fun clientRefusesWhatTheServerSchemaWouldRefuse() {
        val t = FakeTransport()
        val c = client(t)
        listOf(
            c.pair("k7m2qx9a", "1.0.0", 34), // lower case
            c.pair("K7M2QX0A", "1.0.0", 34), // 0 is not in the code alphabet
            c.pair("K7M2QX9A", "v1", 34),
            c.pair("K7M2QX9A", "1.0.0", 10),
            c.heartbeat("1.0.0", 34, 5, false, emptyMap()), // ts too small
            c.heartbeat("1.0.0", 34, 1_788_000_000_000, false, mapOf("camera" to true)), // not a Roles key
            c.share("sms", "x"),
            c.share("text", ""),
            c.share("text", "x".repeat(2001)),
            c.ack("bogus"),
            c.ack("this_was_fine"), // needs a prompt id
            c.ack("dismissed", "abc"), // prompt id too short
            c.sos(lat = 91.0, lon = 0.0),
            c.sos(lat = 1.0, lon = null),
            c.voice(ByteArray(0), "audio/ogg", 3),
            c.voice(ByteArray(1_048_577), "audio/ogg", 3),
            c.voice(ByteArray(10), "audio/flac", 3),
            c.voice(ByteArray(10), "audio/ogg", 0),
            c.voice(ByteArray(10), "audio/ogg", 61),
            c.pause(4), c.pause(1441),
            c.withdrawConsent(emptyList()),
            c.signals(emptyList()),
            c.signals(List(101) { JSONObject() }),
        ).forEachIndexed { i, r -> assertTrue("case $i", errOf(r) is ApiError.ClientValidation) }
        assertTrue("nothing was sent", t.sent.isEmpty())
    }

    @Test fun withdrawSendsOnlyFalse() {
        val t = FakeTransport().reply(200, """{"consent_basis":"admin_on_behalf","items":{"camera":false,"calls":true}}""")
        client(t).withdrawConsent(listOf("camera", "calls"))
        val items = t.lastBody().getJSONObject("items")
        assertEquals(setOf("camera", "calls"), items.keys().asSequence().toSet())
        assertTrue(items.keys().asSequence().all { !items.getBoolean(it) })
        assertEquals("PUT", t.last.method)
    }

    @Test fun voiceReplyWithAudioUrlIsParsedAndOldRepliesStillWork() {
        val t = FakeTransport().reply(200, """{"accepted":true,"reply_text":"ok","reply_audio_url":"https://robin-server.invalid/a/1.mp3","new_key":1}""")
        val r = client(t).voice(ByteArray(10), "audio/mp4", 2) as ApiResult.Ok
        assertEquals(VoiceReply(true, "ok", "https://robin-server.invalid/a/1.mp3"), r.value)
        assertEquals("audio/mp4", t.last.headers["Content-Type"])
        assertEquals("2", t.last.headers["X-Duration-S"])
        assertEquals(null, (client(FakeTransport().reply(200, """{"accepted":true,"reply_text":null}""")).voice(ByteArray(10), "audio/mp4", 2) as ApiResult.Ok).value.replyAudioUrl)
    }

    @Test fun voiceUploadIsRawAudioWithDurationHeader() {
        val t = FakeTransport().reply(200, """{"accepted": true, "reply_text": null}""")
        val audio = byteArrayOf(1, 2, 3)
        val r = client(t).voice(audio, "audio/mp4", 7) as ApiResult.Ok
        assertEquals(VoiceReply(true, null), r.value)
        assertEquals("audio/mp4", t.last.headers["Content-Type"])
        assertEquals("7", t.last.headers["X-Duration-S"])
        assertEquals(audio.toList(), t.last.body!!.toList())
    }

    @Test fun statusCodesMapToErrors() {
        fun err(status: Int, body: String): ApiError =
            errOf(client(FakeTransport().reply(status, body)).stop())
        assertEquals(ApiError.Unauthorized, err(404, """{"detail":"Not Found"}"""))
        assertEquals(ApiError.RateLimited, err(429, """{"detail":"slow down"}"""))
        assertEquals(ApiError.TooLarge, err(413, """{"detail":"too large"}"""))
        assertEquals(ApiError.Unavailable(503), err(503, """{"error":"voice_not_available"}"""))
        assertEquals(ApiError.Unavailable(502), err(502, "<html>bad gateway</html>"))
        assertEquals(ApiError.Forbidden("something_else"), err(403, """{"error":"something_else"}"""))
        assertEquals(ApiError.Invalid(emptyList(), "bad_reference"), err(422, """{"error":"bad_reference"}"""))
        // an ack for a prompt that is gone must NOT look like a revoked token (that would unpair the phone)
        val ack = errOf(client(FakeTransport().reply(404, """{"error":"unknown_prompt"}""")).ack("dismissed", "abcdef123"))
        assertEquals(ApiError.Invalid(emptyList(), "unknown_prompt"), ack)
    }

    @Test fun networkErrorsNeverCarryTheMessage() {
        val e = errOf(client(FakeTransport().fail()).stop()) as ApiError.Network
        assertEquals("IOException", e.reason)
        assertFalse(e.toString().contains("secret.example"))
    }

    @Test fun malformedRepliesAreRejectedNamingTheKeyOnly() {
        fun m(body: String): ApiError = errOf(client(FakeTransport().reply(200, body)).pause(30))
        assertEquals(ApiError.Malformed("until_ms", "missing"), m("""{"paused": true}"""))
        assertEquals(ApiError.Malformed("paused", "not_bool"), m("""{"paused": "yes", "until_ms": 1}"""))
        assertEquals(ApiError.Malformed("until_ms", "not_int"), m("""{"paused": true, "until_ms": "soon"}"""))
        assertEquals(ApiError.Malformed("body", "not_json"), m("not json"))
        assertEquals(ApiError.Malformed("paused", "missing"), m("""{"paused": null, "until_ms": 1}"""))
    }

    @Test fun extraKeysInRepliesAreIgnoredButRequiredOnesAreEnforced() {
        val ok = client(FakeTransport().reply(200, """{"paused": false, "future_field": 1}""")).resume()
        assertEquals(ResumeReply(false), (ok as ApiResult.Ok).value)
    }

    @Test fun tokensAndBodiesStayOutOfToString() {
        val t = FakeTransport().reply(200, """{"paused": false}""")
        client(t).resume()
        assertFalse(t.last.toString().contains(TOKEN))
    }
}
