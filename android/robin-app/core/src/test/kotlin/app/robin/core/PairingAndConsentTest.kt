package app.robin.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class PairingFlowTest {
    private val pairOk = Fixtures.byName("pair").responseText()
    private val tokens = MemTokens()
    private val profiles = MemProfiles()
    private fun flow(t: FakeTransport) = PairingFlow(ApiClient(BASE, t, tokens), tokens, profiles, "1.0.0", 34)

    @Test fun normalisesWhatPeopleType() {
        val f = flow(FakeTransport())
        assertEquals("K7M2QX9A", f.normalise(" k7m2-qx9a "))
        assertEquals("K7M2QX9A", f.normalise("K7M2 QX9A\n"))
    }

    @Test fun typoIsRejectedWithoutANetworkCall() {
        val t = FakeTransport()
        val s = flow(t).submit("K7M2")
        assertEquals(PairingFlow.State.Failed(PairingFlow.Failure.BAD_FORMAT), s)
        assertTrue(t.sent.isEmpty())
        assertEquals(PairingFlow.State.Failed(PairingFlow.Failure.BAD_FORMAT), flow(t).submit("K7M2QX0A")) // 0 not allowed
    }

    @Test fun successStoresTokenAndProfile() {
        val t = FakeTransport().reply(200, pairOk)
        val s = flow(t).submit("k7m2 qx9a") as PairingFlow.State.Paired
        assertEquals("K7M2QX9A", t.lastBody().getString("code"))
        assertEquals(TOKEN, tokens.value)
        assertEquals("hinglish", s.profile.language)
        assertEquals("Robin", profiles.value!!.brand)
        assertEquals(12, profiles.value!!.consentItems.size)
        assertEquals(s, flow(FakeTransport()).restore())
    }

    @Test fun failuresKeepNothing() {
        val cases = mapOf(
            PairingFlow.Failure.WRONG_OR_EXPIRED to FakeTransport().reply(404, """{"detail":"Not Found"}"""),
            PairingFlow.Failure.RATE_LIMITED to FakeTransport().reply(429, "{}"),
            PairingFlow.Failure.NETWORK to FakeTransport().fail(),
            PairingFlow.Failure.SERVER to FakeTransport().reply(500, "oops"),
            PairingFlow.Failure.MALFORMED to FakeTransport().reply(200, """{"device_token": "x"}"""),
        )
        for ((expected, t) in cases) {
            assertEquals(PairingFlow.State.Failed(expected), flow(t).submit("K7M2QX9A"))
            assertNull(tokens.value)
            assertNull(profiles.value)
        }
    }

    @Test fun restoreNeedsBothTokenAndProfile() {
        assertEquals(PairingFlow.State.NeedsCode, flow(FakeTransport()).restore())
        tokens.value = TOKEN
        assertEquals(PairingFlow.State.NeedsCode, flow(FakeTransport()).restore())
    }

    @Test fun revokedTokenSendsThePhoneBackToTheCodeScreen() {
        flow(FakeTransport().reply(200, pairOk)).submit("K7M2QX9A")
        assertEquals(PairingFlow.State.NeedsCode, flow(FakeTransport()).onUnauthorized())
        assertNull(tokens.value)
        assertNull(profiles.value)
    }
}

class ConsentViewTest {
    private val order = listOf("calls", "camera", "voice_messages", "location")
    private fun view(t: FakeTransport) = ConsentView(ApiClient(BASE, t, MemTokens(TOKEN)), order)

    @Test fun showsServerStateInTheServersOrderAndNewItemsLast() {
        val t = FakeTransport().reply(
            200, """{"consent_basis":"admin_on_behalf","items":{"zeta_new":true,"location":false,"calls":true,"voice_messages":true,"camera":true}}""",
        )
        val s = (view(t).load() as ApiResult.Ok).value
        assertEquals("admin_on_behalf", s.basis)
        assertEquals(listOf("calls", "camera", "voice_messages", "location", "zeta_new"), s.rows.map { it.item })
        assertEquals(listOf(true, true, true, false, true), s.rows.map { it.allowed })
        assertFalse(s.rows.first { it.item == "location" }.canWithdraw) // already off: nothing to withdraw
        assertTrue(s.rows.first { it.item == "camera" }.canWithdraw)
        assertEquals("GET", t.last.method)
    }

    @Test fun withdrawIsTheOnlyWriteAndSendsFalse() {
        val t = FakeTransport()
            .reply(200, """{"consent_basis":"admin_on_behalf","items":{"calls":true,"camera":false}}""")
        val s = (view(t).withdraw("camera") as ApiResult.Ok).value
        assertEquals("""{"items":{"camera":false}}""", String(t.last.body!!))
        assertFalse(s.rows.first { it.item == "camera" }.allowed)
    }

    @Test fun withdrawAllOnlyNamesAllowedItems() {
        val t = FakeTransport()
            .reply(200, """{"consent_basis":"admin_on_behalf","items":{"calls":true,"camera":false,"location":true}}""")
            .reply(200, """{"consent_basis":"admin_on_behalf","items":{"calls":false,"camera":false,"location":false}}""")
        val v = view(t)
        val first = (v.load() as ApiResult.Ok).value
        val after = (v.withdrawAll(first) as ApiResult.Ok).value
        assertEquals(setOf("calls", "location"), t.lastBody().getJSONObject("items").keys().asSequence().toSet())
        assertFalse(after.anyAllowed)
        // nothing left to withdraw: no request at all
        val n = t.sent.size
        assertEquals(ApiResult.Ok(after), v.withdrawAll(after))
        assertEquals(n, t.sent.size)
    }

    @Test fun viewHasNoGrantFunction() {
        val names = ConsentView::class.java.declaredMethods.map { it.name.lowercase() }
        assertTrue(names.none { "grant" in it || "allow" in it || "enable" in it })
        val apiNames = ApiClient::class.java.declaredMethods.map { it.name.lowercase() }
        assertTrue(apiNames.none { "grant" in it })
    }

    @Test fun familyAdminOnlyIsSurfacedIfServerStillRefuses() {
        val t = FakeTransport().reply(403, """{"error":"consent_given_by_family_admin"}""")
        assertEquals(ApiError.FamilyAdminOnly, (view(t).withdraw("camera") as ApiResult.Err).error)
    }
}
