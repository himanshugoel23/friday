package app.robin.core

/** The long-press menu. SOS is first and needs a 2 second hold (the same [SosGesture] as everywhere); the rest are single taps. */
enum class MenuItemId { SOS, CALL_112, HIDE_FOR_NOW, TURN_OFF_FOR_NOW, CLOSE }

data class MenuItem(val id: MenuItemId, val holdMs: Long = 0)

object BubbleMenu {
    /** Fixed order. Never changes with state, so a person who learned it can rely on it. */
    fun items(): List<MenuItem> = listOf(
        MenuItem(MenuItemId.SOS, SosGesture.DEFAULT_HOLD_MS),
        MenuItem(MenuItemId.CALL_112),
        MenuItem(MenuItemId.HIDE_FOR_NOW),
        MenuItem(MenuItemId.TURN_OFF_FOR_NOW),
        MenuItem(MenuItemId.CLOSE),
    )

    /** A tap on an item that needs a hold does nothing: the SOS cannot be raised by a pocket touch. */
    fun tapFires(item: MenuItem): Boolean = item.holdMs == 0L
}

/** What the Android layer must do after an event. */
sealed class BubbleEffect {
    object None : BubbleEffect()
    /** Start or stop the question (the [VoiceTurn] tap). */
    object ToggleTalk : BubbleEffect()
    object ShowMenu : BubbleEffect()
    object CloseMenu : BubbleEffect()
    /** Remove the bubble from the screen until it is shown again (the notification stays; the service stays). */
    object HideBubble : BubbleEffect()
    /** Stop the service: also clears "enabled" so a restart or a reboot does not bring it back. */
    object TurnOff : BubbleEffect()
    object DialEmergency : BubbleEffect()
    /** The SOS item completed its hold. */
    object RaiseSos : BubbleEffect()
}

/**
 * The bubble's own modes, separate from the voice turn: collapsed, menu open, hidden for the session. Pure. "Hidden"
 * lasts until the person taps "show" in the notification or the service is started again; it is not remembered across
 * a restart (the bubble reappears, because a hidden thing that can never come back would confuse the parent).
 */
class BubbleSession {
    enum class Mode { COLLAPSED, MENU, HIDDEN }

    var mode: Mode = Mode.COLLAPSED
        private set

    /** Tap on the bubble. While the menu is open a tap on the bubble closes it. Nothing happens while hidden. */
    fun onBubbleTap(): BubbleEffect = when (mode) {
        Mode.COLLAPSED -> BubbleEffect.ToggleTalk
        Mode.MENU -> { mode = Mode.COLLAPSED; BubbleEffect.CloseMenu }
        Mode.HIDDEN -> BubbleEffect.None
    }

    fun onBubbleLongPress(): BubbleEffect {
        if (mode != Mode.COLLAPSED) return BubbleEffect.None
        mode = Mode.MENU
        return BubbleEffect.ShowMenu
    }

    /** A tap (or completed hold) on a menu item. [heldMs] is how long the finger stayed on it. */
    fun onMenuItem(item: MenuItem, heldMs: Long): BubbleEffect {
        if (mode != Mode.MENU) return BubbleEffect.None
        if (item.holdMs > 0 && heldMs < item.holdMs) return BubbleEffect.None // a short press on SOS does nothing
        return when (item.id) {
            MenuItemId.SOS -> { mode = Mode.COLLAPSED; BubbleEffect.RaiseSos }
            MenuItemId.CALL_112 -> { mode = Mode.COLLAPSED; BubbleEffect.DialEmergency }
            MenuItemId.HIDE_FOR_NOW -> { mode = Mode.HIDDEN; BubbleEffect.HideBubble }
            MenuItemId.TURN_OFF_FOR_NOW -> { mode = Mode.COLLAPSED; BubbleEffect.TurnOff }
            MenuItemId.CLOSE -> { mode = Mode.COLLAPSED; BubbleEffect.CloseMenu }
        }
    }

    /** Touch outside the menu, back, screen off: close the menu. */
    fun dismissMenu(): BubbleEffect {
        if (mode != Mode.MENU) return BubbleEffect.None
        mode = Mode.COLLAPSED
        return BubbleEffect.CloseMenu
    }

    /** The notification's "show" (or any explicit request) brings a hidden bubble back. */
    fun show() {
        if (mode == Mode.HIDDEN) mode = Mode.COLLAPSED
    }

    val visible: Boolean get() = mode != Mode.HIDDEN
}
