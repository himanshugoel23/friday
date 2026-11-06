package app.robin.core

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Every shared fixture (the same files tests/robindevice/test_contract_fixtures.py replays against the real server):
 * the ApiClient must send exactly the fixture request and understand exactly the fixture reply.
 */
class ContractFixturesTest {
    private fun invoke(fx: Fixtures.Fx, client: ApiClient): ApiResult<Any> {
        val j = fx.requestJson
        @Suppress("UNCHECKED_CAST")
        return when (fx.name) {
            "pair", "err_pair_wrong_code" ->
                client.pair(j!!.getString("code"), j.getString("app_version"), j.getInt("os_sdk"))
            "heartbeat" -> {
                val roles = j!!.getJSONObject("roles")
                client.heartbeat(
                    j.getString("app_version"), j.getInt("os_sdk"), j.getLong("ts_ms"), j.getBoolean("battery_low"),
                    roles.keys().asSequence().associateWith { roles.getBoolean(it) },
                )
            }
            "signals" -> {
                val a = j!!.getJSONArray("events")
                client.signals(List(a.length()) { a.getJSONObject(it) })
            }
            "prompts" -> client.prompts()
            "ack_this_was_fine" -> client.ack(j!!.getString("kind"), j.getString("prompt_id"))
            "ack_i_am_ok" -> client.ack(j!!.getString("kind"))
            "sos" -> client.sos()
            "sos_with_location" -> client.sos(j!!.getDouble("lat"), j.getDouble("lon"))
            "voice", "err_voice_no_consent" ->
                client.voice(fx.requestRaw!!.toByteArray(), fx.headers.getValue("Content-Type"), fx.headers.getValue("X-Duration-S").toInt())
            "share" -> client.share(j!!.getString("kind"), j.getString("value"))
            "consent_get" -> client.consent()
            "consent_withdraw" -> client.withdrawConsent(j!!.getJSONObject("items").keys().asSequence().toList())
            // err_invalid sends minutes=1, which the client refuses locally; the 422 path is covered separately
            "pause", "err_invalid" -> client.pause(j!!.getInt("minutes"))
            "stop" -> client.stop()
            "resume" -> client.resume()
            "transparency", "err_bad_token" -> if (fx.name == "transparency") client.transparency() else client.consent()
            "erase" -> client.erase()
            "consent_grant_refused" -> client.withdrawConsent(emptyList()) // the client cannot even express a grant
            else -> error("no Kotlin mapping for fixture ${fx.name}: add one so the contract stays covered")
        } as ApiResult<Any>
    }

    @Test
    fun everyFixtureRoundTripsThroughTheClient() {
        val fixtures = Fixtures.all()
        assertTrue(fixtures.size >= 20)
        for (fx in fixtures) {
            val t = FakeTransport().reply(fx.status, fx.responseText())
            val client = ApiClient(BASE, t, MemTokens(if (fx.auth) TOKEN else null))
            val result = invoke(fx, client)
            when (fx.name) {
                // The client refuses these before sending, which is the point: the phone cannot grant consent and
                // cannot send an out-of-range value. The server side of both is proven by the Python test.
                "consent_grant_refused", "err_invalid" -> {
                    assertTrue(fx.name, result is ApiResult.Err && result.error is ApiError.ClientValidation)
                    assertTrue(fx.name, t.sent.isEmpty())
                    continue
                }
                "signals" -> { /* sent as given; checked below */ }
            }
            assertEquals(fx.name, 1, t.sent.size)
            val sent = t.last
            assertEquals(fx.name, fx.method, sent.method)
            assertEquals(fx.name, BASE + fx.path, sent.url)
            assertEquals(fx.name, fx.auth, sent.headers.containsKey("Authorization"))
            if (fx.auth) assertEquals("Bearer $TOKEN", sent.headers["Authorization"])
            fx.headers.forEach { (k, v) -> assertEquals("${fx.name} $k", v, sent.headers[k]) }
            if (fx.requestJson != null) {
                assertEquals(fx.name, "application/json", sent.headers["Content-Type"])
                val body = JSONObject(String(sent.body!!))
                assertTrue("${fx.name}: request body differs from the fixture\n$body\n${fx.requestJson}", body.similar(fx.requestJson))
            } else if (fx.requestRaw != null) {
                assertEquals(fx.name, fx.requestRaw, String(sent.body!!))
            } else {
                assertEquals(fx.name, null, sent.body)
            }
            if (fx.status in 200..299) {
                assertTrue("${fx.name} should parse: $result", result is ApiResult.Ok)
            } else {
                assertTrue("${fx.name} should be an error: $result", result is ApiResult.Err)
            }
        }
    }

    @Test
    fun errorFixturesMapToTheRightErrors() {
        fun err(name: String, client: (ApiClient) -> ApiResult<Any>): ApiError {
            val fx = Fixtures.byName(name)
            val c = ApiClient(BASE, FakeTransport().reply(fx.status, fx.responseText()), MemTokens(TOKEN))
            return (client(c) as ApiResult.Err).error
        }
        assertEquals(ApiError.Unauthorized, err("err_bad_token") { it.consent() })
        assertEquals(ApiError.ConsentRequired, err("err_voice_no_consent") { it.voice(byteArrayOf(1), "audio/ogg", 3) })
        assertEquals(ApiError.PairingRejected, err("err_pair_wrong_code") { it.pair("ZZZZZZZZ", "1.0.0", 34) })
        assertEquals(ApiError.FamilyAdminOnly, err("consent_grant_refused") { it.withdrawConsent(listOf("camera")) })
        val inv = err("err_invalid") { it.pause(30) } as ApiError.Invalid
        assertEquals(listOf(FieldError("minutes", "greater_than_equal")), inv.fields)
    }

    @Test
    fun parsedValuesMatchTheFixtures() {
        val pair = Fixtures.byName("pair")
        val r = (ApiClient(BASE, FakeTransport().reply(200, pair.responseText()), MemTokens())
            .pair("K7M2QX9A", "1.0.0", 34) as ApiResult.Ok).value
        assertEquals("hinglish", r.language)
        assertEquals("Robin", r.brand)
        assertEquals(100, r.maxBatch)
        assertEquals(12, r.consentItems.size)
        assertTrue("token must not appear in toString", TOKEN !in r.toString() && r.deviceToken == TOKEN)

        val tp = Fixtures.byName("prompts")
        val ps = (ApiClient(BASE, FakeTransport().reply(200, tp.responseText()), MemTokens(TOKEN)).prompts() as ApiResult.Ok).value.prompts
        assertEquals(1, ps.size)
        assertEquals("S2", ps[0].scenario)
        assertTrue(ps[0].fullScreen && ps[0].readAloud)
        assertEquals(setOf("en", "hinglish", "hi"), ps[0].text.keys)
        assertTrue(ps[0].actions.any { it.ack == "this_was_fine" })
        assertNotNull(ps[0].textFor("hi").takeIf { it.isNotEmpty() })

        val sg = Fixtures.byName("signals")
        val s = (ApiClient(BASE, FakeTransport().reply(200, sg.responseText()), MemTokens(TOKEN))
            .signals(listOf(JSONObject("{}"))) as ApiResult.Ok).value
        assertEquals(1, s.accepted)
        assertEquals(listOf(InvalidDetail(1, "unknown_type")), s.invalidDetail)

        val tr = Fixtures.byName("transparency")
        val t = (ApiClient(BASE, FakeTransport().reply(200, tr.responseText()), MemTokens(TOKEN)).transparency() as ApiResult.Ok).value
        assertTrue(t.collected.isNotEmpty() && t.neverCollected.isNotEmpty())
        assertEquals(1, t.toldChild.size)
        assertEquals("S2", t.toldChild[0].scenario)
    }
}
