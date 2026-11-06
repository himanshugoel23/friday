package app.robin.core

/**
 * Press-and-hold SOS: the finger must stay down for [holdMs] (2 seconds). A tap or an early release does nothing, so a
 * pocket press cannot raise a false alarm. Pure state machine; time is passed in, nothing is read from a clock.
 */
class SosGesture(val holdMs: Long = DEFAULT_HOLD_MS) {
    sealed class State {
        object Idle : State()
        data class Holding(val startMs: Long, val progress: Float) : State()
        object Fired : State()
    }

    var state: State = State.Idle
        private set

    /** Finger down. Ignored while already holding or fired (a second finger must not restart the timer). */
    fun down(nowMs: Long): State {
        if (state is State.Idle) state = State.Holding(nowMs, 0f)
        return state
    }

    /** Call about every 50 ms while held (a UI frame callback). Fires exactly once. */
    fun tick(nowMs: Long): State {
        val s = state
        if (s is State.Holding) {
            val elapsed = (nowMs - s.startMs).coerceAtLeast(0)
            state = if (elapsed >= holdMs) State.Fired else State.Holding(s.startMs, elapsed.toFloat() / holdMs)
        }
        return state
    }

    /** Finger up. A release after the hold time has passed still fires, even if no tick ran in between. */
    fun up(nowMs: Long): State {
        val s = state
        if (s is State.Holding) {
            state = if (nowMs - s.startMs >= holdMs) State.Fired else State.Idle
        }
        return state
    }

    /** Finger moved away, screen turned off or the activity paused: abandon a hold in progress. Does not undo a fire. */
    fun cancel(): State {
        if (state is State.Holding) state = State.Idle
        return state
    }

    /** Called once the SOS has been handed over, so the button can be used again. */
    fun reset() {
        state = State.Idle
    }

    companion object {
        const val DEFAULT_HOLD_MS = 2_000L
    }
}

/**
 * Hold-to-record for the voice note (hold, speak, release to send). Under [MIN_S] seconds is "too short" (the server
 * needs at least 1 s); at [MAX_S] seconds it stops by itself. The microphone is open only between down and up.
 */
class VoiceNoteGesture(private val minMs: Long = MIN_S * 1000, private val maxMs: Long = MAX_S * 1000) {
    sealed class State {
        object Idle : State()
        data class Recording(val startMs: Long) : State()

        /** Finished with a duration the server accepts; [seconds] is what goes in X-Duration-S. */
        data class Done(val seconds: Int, val autoStopped: Boolean) : State()
        object TooShort : State()
    }

    var state: State = State.Idle
        private set

    fun down(nowMs: Long): State {
        if (state !is State.Recording) state = State.Recording(nowMs)
        return state
    }

    fun tick(nowMs: Long): State {
        val s = state
        if (s is State.Recording && nowMs - s.startMs >= maxMs) state = State.Done(MAX_S.toInt(), autoStopped = true)
        return state
    }

    fun up(nowMs: Long): State {
        val s = state
        if (s is State.Recording) {
            val ms = (nowMs - s.startMs).coerceAtLeast(0)
            state = when {
                ms < minMs -> State.TooShort
                else -> State.Done(minOf((ms + 999) / 1000, MAX_S).toInt(), autoStopped = false)
            }
        }
        return state
    }

    /** Activity paused or permission screen shown: drop the recording, never keep the microphone open. */
    fun cancel(): State {
        if (state is State.Recording) state = State.Idle
        return state
    }

    fun reset() {
        state = State.Idle
    }

    companion object {
        const val MIN_S = 1L
        const val MAX_S = 60L
    }
}

/**
 * Sends the SOS at once (never queued behind anything), retrying every [retryEveryMs] for [giveUpAfterMs] (10 s for
 * 2 minutes). The outcome tells the UI what to show; whatever it is, the 112 and "call family" buttons stay visible,
 * because the server never dials.
 */
class SosSender(
    private val client: ApiClient,
    private val sleeper: (Long) -> Unit,
    private val retryEveryMs: Long = 10_000,
    private val giveUpAfterMs: Long = 120_000,
) {
    sealed class Outcome {
        data class Sent(val message: String?, val attempts: Int) : Outcome()
        data class NotSent(val lastError: ApiError, val attempts: Int) : Outcome()
    }

    /** Blocking. [onAttempt] is called before each try (1, 2, ...) so the screen can show "sending". */
    fun send(lat: Double?, lon: Double?, onAttempt: (Int) -> Unit = {}): Outcome {
        var attempts = 0
        var waited = 0L
        var last: ApiError = ApiError.Network("none")
        while (true) {
            attempts++
            onAttempt(attempts)
            when (val r = client.sos(lat, lon)) {
                is ApiResult.Ok -> return Outcome.Sent(r.value.message, attempts)
                is ApiResult.Err -> {
                    last = r.error
                    // Retrying cannot fix a bad token or a refused request.
                    if (last == ApiError.Unauthorized || last is ApiError.ClientValidation) return Outcome.NotSent(last, attempts)
                }
            }
            if (waited + retryEveryMs > giveUpAfterMs) return Outcome.NotSent(last, attempts)
            try {
                sleeper(retryEveryMs)
            } catch (e: InterruptedException) {
                return Outcome.NotSent(last, attempts)
            }
            waited += retryEveryMs
        }
    }
}
