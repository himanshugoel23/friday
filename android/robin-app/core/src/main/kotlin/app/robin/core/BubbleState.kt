package app.robin.core

import kotlin.math.PI
import kotlin.math.cos
import kotlin.math.sin

/** What the floating mic bubble shows. Derived from the [VoiceTurn] state; the bubble adds no rules of its own to the voice flow. */
enum class BubbleState { IDLE, LISTENING, SENDING, ANSWERING, OFFLINE, PROBLEM }

/** Outline of the bubble. Every state has its own outline AND its own word AND its own glyph, so colour is never the only cue. */
enum class BubbleShape(val sides: Int) { CIRCLE(0), ROUNDED_SQUARE(0), DIAMOND(4), HEXAGON(6), TRIANGLE(3), OCTAGON(8) }

enum class BubbleGlyph { MIC, STOP, SEND, SPEAKER, OFFLINE, WARNING }

/** Short word under the bubble (resolved to a string resource by the app). */
enum class BubbleWord { TALK, LISTENING, SENDING, SPEAKING, NO_INTERNET, PROBLEM }

enum class ColourRole { VOICE, LISTENING, BUSY, ANSWER, PROBLEM }

enum class Haptic { NONE, CONFIRM, REJECT }

data class BubbleLook(
    val state: BubbleState,
    val shape: BubbleShape,
    val glyph: BubbleGlyph,
    val word: BubbleWord,
    val colour: ColourRole,
    /** Vibration when the bubble enters this state. */
    val haptic: Haptic,
    /** True when a screen reader should announce the change (live region). */
    val announce: Boolean,
)

object BubbleStates {
    fun from(s: VoiceTurn.State): BubbleState = when (s) {
        VoiceTurn.State.Idle -> BubbleState.IDLE
        is VoiceTurn.State.Recording -> BubbleState.LISTENING
        is VoiceTurn.State.Uploading -> BubbleState.SENDING
        is VoiceTurn.State.Answering -> BubbleState.ANSWERING
        VoiceTurn.State.Offline -> BubbleState.OFFLINE
        is VoiceTurn.State.Error -> BubbleState.PROBLEM
    }

    fun look(s: BubbleState): BubbleLook = when (s) {
        BubbleState.IDLE -> BubbleLook(s, BubbleShape.CIRCLE, BubbleGlyph.MIC, BubbleWord.TALK, ColourRole.VOICE, Haptic.NONE, false)
        BubbleState.LISTENING -> BubbleLook(s, BubbleShape.ROUNDED_SQUARE, BubbleGlyph.STOP, BubbleWord.LISTENING, ColourRole.LISTENING, Haptic.CONFIRM, true)
        BubbleState.SENDING -> BubbleLook(s, BubbleShape.DIAMOND, BubbleGlyph.SEND, BubbleWord.SENDING, ColourRole.BUSY, Haptic.CONFIRM, true)
        BubbleState.ANSWERING -> BubbleLook(s, BubbleShape.HEXAGON, BubbleGlyph.SPEAKER, BubbleWord.SPEAKING, ColourRole.ANSWER, Haptic.CONFIRM, true)
        BubbleState.OFFLINE -> BubbleLook(s, BubbleShape.TRIANGLE, BubbleGlyph.OFFLINE, BubbleWord.NO_INTERNET, ColourRole.PROBLEM, Haptic.REJECT, true)
        BubbleState.PROBLEM -> BubbleLook(s, BubbleShape.OCTAGON, BubbleGlyph.WARNING, BubbleWord.PROBLEM, ColourRole.PROBLEM, Haptic.REJECT, true)
    }

    fun look(s: VoiceTurn.State): BubbleLook = look(from(s))
}

/** What the large-type card next to the bubble says (the app maps the key to a string resource; [text] is the server's reply). */
enum class CardKey { LISTENING_HINT, ANSWER, ANSWER_FALLBACK, OFFLINE, NO_MIC, TOO_SHORT, NO_SPEECH, NOT_UNDERSTOOD, NO_CONSENT, BUSY, NOT_SET_UP, FAILED }

data class BubbleCard(val key: CardKey, val text: String? = null)

object BubbleCards {
    /** Null = no card (idle, or sending, where the bubble word is enough). */
    fun from(s: VoiceTurn.State): BubbleCard? = when (s) {
        VoiceTurn.State.Idle -> null
        is VoiceTurn.State.Recording -> BubbleCard(CardKey.LISTENING_HINT)
        is VoiceTurn.State.Uploading -> null
        is VoiceTurn.State.Answering -> if (s.answer.text != null) BubbleCard(CardKey.ANSWER, s.answer.text) else BubbleCard(CardKey.ANSWER_FALLBACK)
        VoiceTurn.State.Offline -> BubbleCard(CardKey.OFFLINE)
        is VoiceTurn.State.Error -> BubbleCard(
            when (s.reason) {
                VoiceTurn.Failure.NO_MIC -> CardKey.NO_MIC
                VoiceTurn.Failure.TOO_SHORT -> CardKey.TOO_SHORT
                VoiceTurn.Failure.NO_SPEECH -> CardKey.NO_SPEECH
                VoiceTurn.Failure.NOT_UNDERSTOOD -> CardKey.NOT_UNDERSTOOD
                VoiceTurn.Failure.NO_CONSENT -> CardKey.NO_CONSENT
                VoiceTurn.Failure.BUSY -> CardKey.BUSY
                VoiceTurn.Failure.UNPAIRED -> CardKey.NOT_SET_UP
                VoiceTurn.Failure.REJECTED, VoiceTurn.Failure.SERVER -> CardKey.FAILED
            },
        )
    }
}

/** Corner points of a regular polygon, for drawing the non-round outlines. First corner at the top. */
object Polygons {
    data class P(val x: Float, val y: Float)

    fun points(sides: Int, cx: Float, cy: Float, radius: Float, rotationDeg: Float = 0f): List<P> {
        require(sides >= 3) { "a polygon needs 3 or more sides" }
        return List(sides) { i ->
            val a = (-90.0 + rotationDeg + 360.0 * i / sides) * PI / 180.0
            P((cx + radius * cos(a)).toFloat(), (cy + radius * sin(a)).toFloat())
        }
    }
}
