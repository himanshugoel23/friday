package app.robin.core

/** One thing the child setup screen shows for the floating mic. The app maps [GateStep] to strings and [GateAction] to an intent. */
enum class GateStep { PAIRED, OVERLAY, MICROPHONE, NOTIFICATIONS, VOICE_CONSENT, BATTERY }

/** What the button next to a missing step does. */
enum class GateAction { NONE, OPEN_PAIRING, OPEN_OVERLAY_SETTINGS, REQUEST_MICROPHONE, REQUEST_NOTIFICATIONS, OPEN_BATTERY_SETTINGS }

data class GateInput(
    val sdk: Int,
    val serverConfigured: Boolean,
    val paired: Boolean,
    val overlayGranted: Boolean,
    val micGranted: Boolean,
    val notificationsGranted: Boolean,
    /** From the pairing profile (the family's consent items). Null = not known. */
    val voiceConsent: Boolean?,
    /** Null = could not be read. */
    val batteryUnrestricted: Boolean?,
)

data class GateRow(val step: GateStep, val required: Boolean, val done: Boolean, val action: GateAction)

data class GateResult(
    val rows: List<GateRow>,
    /** All required steps are done: the child may turn the bubble on. */
    val canStart: Boolean,
    /** The first required step still open (the setup screen highlights it). Null when [canStart]. */
    val next: GateStep?,
) {
    fun row(s: GateStep) = rows.first { it.step == s }

    /** True when the one thing missing is "Display over other apps": the screen must then explain where to switch it on. */
    val overlayMissing: Boolean get() = !row(GateStep.OVERLAY).done
}

object OverlayGate {
    const val ANDROID_13 = 33

    fun evaluate(i: GateInput): GateResult {
        val needsNotifPermission = i.sdk >= ANDROID_13
        val rows = listOf(
            GateRow(GateStep.PAIRED, true, i.serverConfigured && i.paired, if (i.paired) GateAction.NONE else GateAction.OPEN_PAIRING),
            GateRow(GateStep.OVERLAY, true, i.overlayGranted, if (i.overlayGranted) GateAction.NONE else GateAction.OPEN_OVERLAY_SETTINGS),
            GateRow(GateStep.MICROPHONE, true, i.micGranted, if (i.micGranted) GateAction.NONE else GateAction.REQUEST_MICROPHONE),
            // Below Android 13 notifications need no permission: the step is done by definition.
            GateRow(GateStep.NOTIFICATIONS, true, !needsNotifPermission || i.notificationsGranted, if (!needsNotifPermission || i.notificationsGranted) GateAction.NONE else GateAction.REQUEST_NOTIFICATIONS),
            // Advice only: without voice consent the bubble still opens SOS and says the family has not turned voice on.
            GateRow(GateStep.VOICE_CONSENT, false, i.voiceConsent != false, GateAction.NONE),
            // Advice only: many phones stop background apps; "unrestricted" helps but is never required.
            GateRow(GateStep.BATTERY, false, i.batteryUnrestricted == true, if (i.batteryUnrestricted == true) GateAction.NONE else GateAction.OPEN_BATTERY_SETTINGS),
        )
        val firstOpen = rows.firstOrNull { it.required && !it.done }
        return GateResult(rows, firstOpen == null, firstOpen?.step)
    }
}

/**
 * What is remembered about the bubble. [childAllowed] is set only by the child on the setup screen. [enabled] is "should be
 * running now": the child's Turn on sets it, the parent's main-screen switch and "turn off for now" clear it, and the
 * parent's switch can set it again only while [childAllowed]. [autoStartAfterReboot] is the child's own choice.
 */
data class BubbleSettings(
    val childAllowed: Boolean = false,
    val enabled: Boolean = false,
    val autoStartAfterReboot: Boolean = false,
)

object BubblePolicy {
    /** The child turned it on in person (setup screen). Refused while a required step is open. */
    fun childTurnOn(s: BubbleSettings, gate: GateResult, autoStart: Boolean): BubbleSettings =
        if (gate.canStart) BubbleSettings(childAllowed = true, enabled = true, autoStartAfterReboot = autoStart) else s

    /** The child withdraws the permission for good: off, and no auto-start. */
    fun childTurnOff(@Suppress("UNUSED_PARAMETER") s: BubbleSettings): BubbleSettings = BubbleSettings()

    /** Parent's switch, or the menu's "turn off for now": off keeps the child's permission so the parent can switch it on again. */
    fun parentTurnOff(s: BubbleSettings): BubbleSettings = s.copy(enabled = false)

    fun parentTurnOn(s: BubbleSettings, gate: GateResult): BubbleSettings =
        if (s.childAllowed && gate.canStart) s.copy(enabled = true) else s

    /** After a reboot: only what the child allowed, left on, with every permission still in place. */
    fun startAtBoot(s: BubbleSettings, gate: GateResult): Boolean = s.childAllowed && s.enabled && s.autoStartAfterReboot && gate.canStart

    /** The service itself checks again when it starts (the permission may have been withdrawn in system settings). */
    fun mayRun(s: BubbleSettings, gate: GateResult): Boolean = s.childAllowed && s.enabled && gate.canStart
}

/** The switch on the parent's main screen. */
data class ParentSwitch(val checked: Boolean, val enabled: Boolean, val hint: Hint) {
    enum class Hint { NONE, ASK_FAMILY, FIX_PERMISSIONS }
}

object ParentSwitchModel {
    fun from(s: BubbleSettings, gate: GateResult, running: Boolean): ParentSwitch = when {
        !s.childAllowed -> ParentSwitch(false, false, ParentSwitch.Hint.ASK_FAMILY) // the child has not set it up: nothing to switch
        running -> ParentSwitch(true, true, ParentSwitch.Hint.NONE) // can always be switched off
        !gate.canStart -> ParentSwitch(false, false, ParentSwitch.Hint.FIX_PERMISSIONS)
        else -> ParentSwitch(false, true, ParentSwitch.Hint.NONE)
    }
}
