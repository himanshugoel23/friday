package app.robin.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class BubbleMenuTest {
    private val sos = BubbleMenu.items().first { it.id == MenuItemId.SOS }
    private fun item(id: MenuItemId) = BubbleMenu.items().first { it.id == id }

    @Test fun menuHasTheRequiredEntriesInAFixedOrderWithSosFirst() {
        assertEquals(
            listOf(MenuItemId.SOS, MenuItemId.CALL_112, MenuItemId.HIDE_FOR_NOW, MenuItemId.TURN_OFF_FOR_NOW, MenuItemId.CLOSE),
            BubbleMenu.items().map { it.id },
        )
    }

    @Test fun sosNeedsTheSameTwoSecondHoldAsEverywhereElse() {
        assertEquals(SosGesture.DEFAULT_HOLD_MS, sos.holdMs)
        assertFalse(BubbleMenu.tapFires(sos))
        assertTrue(BubbleMenu.tapFires(item(MenuItemId.CLOSE)))
    }

    @Test fun tapOnBubbleTalksAndLongPressOpensMenu() {
        val s = BubbleSession()
        assertEquals(BubbleEffect.ToggleTalk, s.onBubbleTap())
        assertEquals(BubbleEffect.ShowMenu, s.onBubbleLongPress())
        assertEquals(BubbleSession.Mode.MENU, s.mode)
        assertEquals(BubbleEffect.CloseMenu, s.onBubbleTap()) // tap closes the menu, does not start talking
        assertEquals(BubbleSession.Mode.COLLAPSED, s.mode)
    }

    @Test fun shortPressOnSosDoesNothingLongHoldRaisesIt() {
        val s = BubbleSession()
        s.onBubbleLongPress()
        assertEquals(BubbleEffect.None, s.onMenuItem(sos, 400))
        assertEquals(BubbleSession.Mode.MENU, s.mode)
        assertEquals(BubbleEffect.None, s.onMenuItem(sos, 1_999))
        assertEquals(BubbleEffect.RaiseSos, s.onMenuItem(sos, 2_000))
        assertEquals(BubbleSession.Mode.COLLAPSED, s.mode)
    }

    @Test fun hideForNowHidesAndShowBringsItBack() {
        val s = BubbleSession()
        s.onBubbleLongPress()
        assertEquals(BubbleEffect.HideBubble, s.onMenuItem(item(MenuItemId.HIDE_FOR_NOW), 0))
        assertFalse(s.visible)
        assertEquals(BubbleEffect.None, s.onBubbleTap())
        assertEquals(BubbleEffect.None, s.onBubbleLongPress())
        s.show()
        assertTrue(s.visible)
        assertEquals(BubbleEffect.ToggleTalk, s.onBubbleTap())
    }

    @Test fun turnOffForNowAsksTheServiceToStop() {
        val s = BubbleSession()
        s.onBubbleLongPress()
        assertEquals(BubbleEffect.TurnOff, s.onMenuItem(item(MenuItemId.TURN_OFF_FOR_NOW), 0))
    }

    @Test fun call112DialsAndClosesTheMenu() {
        val s = BubbleSession()
        s.onBubbleLongPress()
        assertEquals(BubbleEffect.DialEmergency, s.onMenuItem(item(MenuItemId.CALL_112), 0))
        assertEquals(BubbleSession.Mode.COLLAPSED, s.mode)
    }

    @Test fun menuItemsDoNothingWhenMenuIsClosed() {
        val s = BubbleSession()
        assertEquals(BubbleEffect.None, s.onMenuItem(item(MenuItemId.TURN_OFF_FOR_NOW), 0))
        assertEquals(BubbleEffect.None, s.dismissMenu())
        s.onBubbleLongPress()
        assertEquals(BubbleEffect.CloseMenu, s.dismissMenu())
    }
}

class OverlayGateTest {
    private fun input(
        sdk: Int = 34, configured: Boolean = true, paired: Boolean = true, overlay: Boolean = true, mic: Boolean = true,
        notif: Boolean = true, voice: Boolean? = true, battery: Boolean? = true,
    ) = GateInput(sdk, configured, paired, overlay, mic, notif, voice, battery)

    @Test fun everythingInPlaceCanStart() {
        val g = OverlayGate.evaluate(input())
        assertTrue(g.canStart)
        assertNull(g.next)
        assertFalse(g.overlayMissing)
    }

    @Test fun missingOverlayBlocksAndTellsTheSetupScreenToOpenSettings() {
        val g = OverlayGate.evaluate(input(overlay = false))
        assertFalse(g.canStart)
        assertTrue(g.overlayMissing)
        assertEquals(GateStep.OVERLAY, g.next)
        assertEquals(GateAction.OPEN_OVERLAY_SETTINGS, g.row(GateStep.OVERLAY).action)
    }

    @Test fun stepsAreReportedInOrderAndTheFirstOpenOneIsNext() {
        val g = OverlayGate.evaluate(input(paired = false, overlay = false, mic = false, notif = false))
        assertEquals(GateStep.PAIRED, g.next)
        assertEquals(GateAction.OPEN_PAIRING, g.row(GateStep.PAIRED).action)
        assertEquals(listOf(GateStep.PAIRED, GateStep.OVERLAY, GateStep.MICROPHONE, GateStep.NOTIFICATIONS, GateStep.VOICE_CONSENT, GateStep.BATTERY), g.rows.map { it.step })
    }

    @Test fun unconfiguredServerCountsAsNotPaired() {
        assertFalse(OverlayGate.evaluate(input(configured = false)).canStart)
    }

    @Test fun notificationPermissionOnlyMattersFromAndroid13() {
        assertTrue(OverlayGate.evaluate(input(sdk = 30, notif = false)).canStart)
        val g = OverlayGate.evaluate(input(sdk = 33, notif = false))
        assertFalse(g.canStart)
        assertEquals(GateAction.REQUEST_NOTIFICATIONS, g.row(GateStep.NOTIFICATIONS).action)
    }

    @Test fun batteryAndVoiceConsentNeverBlock() {
        val g = OverlayGate.evaluate(input(battery = false, voice = false))
        assertTrue(g.canStart)
        assertFalse(g.row(GateStep.BATTERY).done)
        assertEquals(GateAction.OPEN_BATTERY_SETTINGS, g.row(GateStep.BATTERY).action)
        assertFalse(g.row(GateStep.VOICE_CONSENT).done)
        assertTrue(OverlayGate.evaluate(input(battery = null, voice = null)).canStart)
    }
}

class BubblePolicyTest {
    private val ok = OverlayGate.evaluate(GateInput(34, true, true, true, true, true, true, true))
    private val noOverlay = OverlayGate.evaluate(GateInput(34, true, true, false, true, true, true, true))

    @Test fun onlyTheChildCanSetItUpAndOnlyWithEveryRequiredStep() {
        val s = BubbleSettings()
        assertEquals(s, BubblePolicy.childTurnOn(s, noOverlay, autoStart = true))
        assertEquals(BubbleSettings(true, true, true), BubblePolicy.childTurnOn(s, ok, autoStart = true))
        assertEquals(BubbleSettings(true, true, false), BubblePolicy.childTurnOn(s, ok, autoStart = false))
    }

    @Test fun parentCannotTurnOnWhatTheChildNeverSetUp() {
        val s = BubbleSettings(childAllowed = false, enabled = false)
        assertEquals(s, BubblePolicy.parentTurnOn(s, ok))
    }

    @Test fun parentCanSwitchOffAndBackOnButNotWithoutPermissions() {
        val on = BubbleSettings(true, true, true)
        val off = BubblePolicy.parentTurnOff(on)
        assertEquals(BubbleSettings(true, false, true), off)
        assertEquals(on, BubblePolicy.parentTurnOn(off, ok))
        assertEquals(off, BubblePolicy.parentTurnOn(off, noOverlay))
    }

    @Test fun childWithdrawingClearsEverythingIncludingAutoStart() {
        assertEquals(BubbleSettings(), BubblePolicy.childTurnOff(BubbleSettings(true, true, true)))
    }

    @Test fun bootStartsOnlyWhatTheChildEnabledAndLeftOn() {
        assertTrue(BubblePolicy.startAtBoot(BubbleSettings(true, true, true), ok))
        assertFalse(BubblePolicy.startAtBoot(BubbleSettings(true, true, false), ok)) // child did not choose auto-start
        assertFalse(BubblePolicy.startAtBoot(BubbleSettings(true, false, true), ok)) // parent had switched it off
        assertFalse(BubblePolicy.startAtBoot(BubbleSettings(false, true, true), ok)) // never set up by the child
        assertFalse(BubblePolicy.startAtBoot(BubbleSettings(true, true, true), noOverlay)) // permission since withdrawn
        assertFalse(BubblePolicy.startAtBoot(BubbleSettings(), ok))
    }

    @Test fun serviceRefusesToRunWithoutPermissionOrChoice() {
        assertTrue(BubblePolicy.mayRun(BubbleSettings(true, true, false), ok))
        assertFalse(BubblePolicy.mayRun(BubbleSettings(true, true, false), noOverlay))
        assertFalse(BubblePolicy.mayRun(BubbleSettings(true, false, false), ok))
    }

    @Test fun parentSwitchStatesAreClear() {
        assertEquals(ParentSwitch(false, false, ParentSwitch.Hint.ASK_FAMILY), ParentSwitchModel.from(BubbleSettings(), ok, false))
        assertEquals(ParentSwitch(true, true, ParentSwitch.Hint.NONE), ParentSwitchModel.from(BubbleSettings(true, true, false), ok, true))
        assertEquals(ParentSwitch(false, true, ParentSwitch.Hint.NONE), ParentSwitchModel.from(BubbleSettings(true, false, false), ok, false))
        assertEquals(ParentSwitch(false, false, ParentSwitch.Hint.FIX_PERMISSIONS), ParentSwitchModel.from(BubbleSettings(true, false, false), noOverlay, false))
        // running with a withdrawn permission can still be switched off
        assertEquals(ParentSwitch(true, true, ParentSwitch.Hint.NONE), ParentSwitchModel.from(BubbleSettings(true, true, false), noOverlay, true))
    }
}
