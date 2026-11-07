package app.robin.core

/** What the microphone side needs (Android: MediaRecorder). The file lives only between [start] and [deleteFile]. */
interface VoiceRecorderPort {
    fun start(): Boolean
    /** Stops and returns the bytes, or null when nothing usable was recorded. */
    fun stop(): ByteArray?
    fun cancel()
    fun deleteFile()
    /** Current loudness, 0..32767 (Android: getMaxAmplitude). */
    fun level(): Int
}

fun interface VoiceSender {
    fun send(audio: ByteArray, mime: String, durationS: Int): ApiResult<VoiceReply>
}

/**
 * One question to Robin and its answer: idle -> recording -> uploading -> answering -> idle, with error and offline states.
 * Tap to start, tap again (or silence, or the maximum length) to stop. Pure: time and loudness are passed in, the
 * recorder and the network are ports. No audio is kept: the file is deleted as soon as its bytes are read, before the
 * upload, and the bytes live only in memory for the (few) retries of that one attempt. A failed turn is retried by
 * the parent tapping again, which records afresh.
 */
class VoiceTurn(
    private val recorder: VoiceRecorderPort,
    private val sender: VoiceSender,
    private val cfg: Config = Config(),
    private val mime: String = "audio/mp4",
) {
    /** All numbers are invented working values, tunable and unverified on real phones. */
    data class Config(
        val minMs: Long = 1_000,
        val maxMs: Long = 30_000,
        val speechLevel: Int = 2_000,
        val silenceMs: Long = 2_500,
        val noSpeechMs: Long = 10_000,
        val uploadAttempts: Int = 3,
        val retryDelayMs: Long = 1_500,
    )

    enum class Failure { NO_MIC, TOO_SHORT, NO_SPEECH, NOT_UNDERSTOOD, NO_CONSENT, UNPAIRED, BUSY, REJECTED, SERVER }

    data class Answer(val text: String?, val audioUrl: String?)

    sealed class State {
        object Idle : State()
        data class Recording(val startMs: Long, val heardSpeech: Boolean, val lastLoudMs: Long) : State()
        data class Uploading(val seconds: Int) : State()
        data class Answering(val answer: Answer) : State()
        data class Error(val reason: Failure) : State()
        /** The network is down; tap to try again. */
        object Offline : State()
    }

    private var s: State = State.Idle
    val state: State @Synchronized get() = s

    /** The big button. Idle, error and offline start a recording; recording stops it; answering interrupts and starts a new one. */
    @Synchronized
    fun tap(nowMs: Long): State {
        when (val cur = s) {
            is State.Recording -> stop(nowMs, cur)
            is State.Uploading -> Unit
            else -> {
                recorder.deleteFile()
                s = if (recorder.start()) State.Recording(nowMs, false, nowMs) else State.Error(Failure.NO_MIC)
            }
        }
        return s
    }

    /** About every 100 ms while recording. Stops at the maximum length, or after speech followed by silence; gives up if nothing is said. */
    @Synchronized
    fun tick(nowMs: Long): State {
        val cur = s as? State.Recording ?: return s
        val elapsed = nowMs - cur.startMs
        val loud = recorder.level() >= cfg.speechLevel
        val upd = if (loud) cur.copy(heardSpeech = true, lastLoudMs = nowMs) else cur
        s = upd
        when {
            elapsed >= cfg.maxMs -> stop(nowMs, upd)
            upd.heardSpeech && nowMs - upd.lastLoudMs >= cfg.silenceMs -> stop(nowMs, upd)
            !upd.heardSpeech && elapsed >= cfg.noSpeechMs -> {
                recorder.cancel()
                s = State.Error(Failure.NO_SPEECH)
            }
        }
        return s
    }

    private fun stop(nowMs: Long, cur: State.Recording) {
        val ms = (nowMs - cur.startMs).coerceAtLeast(0)
        if (ms < cfg.minMs) {
            recorder.cancel()
            s = State.Error(Failure.TOO_SHORT)
            return
        }
        s = State.Uploading(minOf((ms + 999) / 1000, ApiClient.MAX_VOICE_SECONDS.toLong()).toInt().coerceAtLeast(1))
    }

    /**
     * Blocking; call on a worker thread when the state is [State.Uploading]. Reads the recording, deletes the file at once,
     * then sends (retrying network failures in memory). Returns the new state.
     */
    fun upload(sleeper: (Long) -> Unit): State {
        val seconds: Int
        synchronized(this) {
            val cur = s as? State.Uploading ?: return s
            seconds = cur.seconds
        }
        val audio = try { recorder.stop() } finally { recorder.deleteFile() }
        if (audio == null) return finish(State.Error(Failure.TOO_SHORT))
        var result: ApiResult<VoiceReply> = ApiResult.Err(ApiError.Network("none"))
        for (attempt in 1..cfg.uploadAttempts) {
            result = sender.send(audio, mime, seconds)
            val e = (result as? ApiResult.Err)?.error
            if (e == null || !(e is ApiError.Network || e is ApiError.Unavailable)) break
            if (attempt < cfg.uploadAttempts) {
                try { sleeper(cfg.retryDelayMs) } catch (ie: InterruptedException) { break }
            }
        }
        return finish(
            when (val r = result) {
                is ApiResult.Ok ->
                    if (r.value.accepted) State.Answering(Answer(r.value.replyText?.takeIf { it.isNotBlank() }, r.value.replyAudioUrl?.takeIf { it.isNotBlank() }))
                    else State.Error(Failure.NOT_UNDERSTOOD)
                is ApiResult.Err -> when (r.error) {
                    is ApiError.Network -> State.Offline
                    ApiError.Unauthorized -> State.Error(Failure.UNPAIRED)
                    ApiError.ConsentRequired -> State.Error(Failure.NO_CONSENT)
                    ApiError.RateLimited -> State.Error(Failure.BUSY)
                    ApiError.TooLarge, is ApiError.ClientValidation, is ApiError.Invalid -> State.Error(Failure.REJECTED)
                    else -> State.Error(Failure.SERVER)
                }
            },
        )
    }

    @Synchronized
    private fun finish(next: State): State {
        // The parent may have tapped or left the screen meanwhile; only an upload in progress is replaced.
        if (s is State.Uploading) s = next
        return s
    }

    /** Playback or speech of the answer ended. */
    @Synchronized
    fun answerDone(): State {
        if (s is State.Answering) s = State.Idle
        return s
    }

    /** Parent dismissed an error or offline message. */
    @Synchronized
    fun dismiss(): State {
        if (s is State.Error || s is State.Offline) s = State.Idle
        return s
    }

    /** Screen left the foreground: the microphone is never open in the background. An upload in flight finishes quietly. */
    @Synchronized
    fun cancel(): State {
        when (s) {
            is State.Recording -> { recorder.cancel(); s = State.Idle }
            is State.Answering, is State.Error, State.Offline -> s = State.Idle
            else -> Unit
        }
        return s
    }
}
