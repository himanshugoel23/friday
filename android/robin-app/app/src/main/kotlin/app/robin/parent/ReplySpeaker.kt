package app.robin.parent

import android.content.Context
import android.media.AudioAttributes
import android.media.MediaPlayer
import android.speech.tts.TextToSpeech
import android.speech.tts.UtteranceProgressListener
import android.os.Handler
import android.os.Looper
import app.robin.core.SpeechPlan
import java.util.Locale

/**
 * Speaks Robin's answer: the server's audio URL when the plan says so (falls back to the phone voice if it cannot play),
 * else Android TextToSpeech in the parent's language. [onDone] is always called once, on the main thread, when speech
 * ends, fails or there is nothing to say. Nothing runs in the background: [stop] is called when the screen leaves.
 */
class ReplySpeaker(private val ctx: Context) {
    private val main = Handler(Looper.getMainLooper())
    private var player: MediaPlayer? = null
    private var tts: TextToSpeech? = null
    private var token = 0

    fun speak(plan: SpeechPlan, fallbackText: String?, localeTag: String, onDone: () -> Unit) {
        stop()
        val my = ++token
        var finished = false
        fun done() = main.post { if (!finished && my == token) { finished = true; onDone() } }
        when (plan) {
            is SpeechPlan.PlayUrl -> play(plan.url, onDone = { done() }, onFail = { speakText(fallbackText, localeTag, ::done) })
            is SpeechPlan.Speak -> speakText(plan.text, plan.localeTag, ::done)
            SpeechPlan.Silent -> speakText(fallbackText, localeTag, ::done)
        }
    }

    private fun play(url: String, onDone: () -> Unit, onFail: () -> Unit) {
        try {
            val p = MediaPlayer()
            player = p
            p.setAudioAttributes(AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_ASSISTANCE_ACCESSIBILITY).setContentType(AudioAttributes.CONTENT_TYPE_SPEECH).build())
            p.setDataSource(url) // no token is sent: the URL is whatever the server chose to give
            p.setOnPreparedListener { it.start() }
            p.setOnCompletionListener { onDone() }
            p.setOnErrorListener { _, _, _ -> onFail(); true }
            p.prepareAsync()
        } catch (e: Exception) {
            onFail()
        }
    }

    private fun speakText(text: String?, localeTag: String, done: () -> Unit) {
        if (text.isNullOrBlank()) { done(); return }
        var engine: TextToSpeech? = null
        engine = TextToSpeech(ctx) { status ->
            val e = engine
            if (status != TextToSpeech.SUCCESS || e == null) { done(); return@TextToSpeech }
            val r = e.setLanguage(Locale.forLanguageTag(localeTag))
            if (r == TextToSpeech.LANG_MISSING_DATA || r == TextToSpeech.LANG_NOT_SUPPORTED) { done(); return@TextToSpeech } // text stays on screen
            e.setOnUtteranceProgressListener(object : UtteranceProgressListener() {
                override fun onStart(utteranceId: String?) {}
                override fun onDone(utteranceId: String?) = done()
                @Deprecated("Deprecated in Java") override fun onError(utteranceId: String?) = done()
            })
            e.speak(text, TextToSpeech.QUEUE_FLUSH, null, "robin_reply")
        }
        tts = engine
    }

    fun stop() {
        token++
        player?.let { try { it.stop() } catch (_: Exception) {}; it.release() }
        player = null
        tts?.let { try { it.stop() } catch (_: Exception) {}; it.shutdown() }
        tts = null
    }
}
