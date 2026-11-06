package app.robin.parent

import android.Manifest
import android.app.Activity
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Color
import android.net.Uri
import android.view.HapticFeedbackConstants
import android.view.View
import android.view.ViewGroup
import android.widget.Button
import android.widget.LinearLayout
import android.widget.TextView
import app.robin.core.ApiError
import app.robin.core.ApiResult
import app.robin.core.SosGesture
import app.robin.core.SosSender
import app.robin.core.VoiceNoteGesture

/**
 * The two big buttons plus Call 112. Used by the home screen and by [QuickActivity] (the widget target, shown over the
 * lock screen). The rules are in :core; this class only connects touches, the recorder and the network.
 */
class QuickPanel(private val activity: Activity, private val host: Host) {
    interface Host {
        /** The server no longer knows this phone (bad or revoked token). */
        fun onUnpaired()
    }

    private val app = activity.robin
    private val sosGesture = SosGesture()
    private val voiceGesture = VoiceNoteGesture()
    private val recorder = VoiceRecorder(activity)
    private var sosBusy = false
    private var voiceBusy = false

    private val status = TextView(activity).apply { textSize = 18f; setTextColor(Color.DKGRAY); minLines = 2 }
    private val sosButton = HoldButton(activity, activity.getColor(R.color.robin_sos))
    private val voiceButton = HoldButton(activity, activity.getColor(R.color.robin_voice))
    private val callButton = Button(activity).apply {
        setText(R.string.home_call_112)
        textSize = 20f
        // The server never dials. Dialer screen only (ACTION_DIAL needs no permission and cannot call by itself).
        setOnClickListener { activity.startActivity(Intent(Intent.ACTION_DIAL, Uri.parse("tel:112"))) }
    }

    val view: View = LinearLayout(activity).apply {
        orientation = LinearLayout.VERTICAL
        fun add(v: View, h: Int) = addView(v, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, h).apply { topMargin = 24 })
        sosButton.text = activity.getString(R.string.home_sos) + "\n" + activity.getString(R.string.home_sos_hold)
        voiceButton.text = activity.getString(R.string.home_voice) + "\n" + activity.getString(R.string.home_voice_hold)
        add(sosButton, 320)
        add(voiceButton, 260)
        add(callButton, ViewGroup.LayoutParams.WRAP_CONTENT)
        add(status, ViewGroup.LayoutParams.WRAP_CONTENT)
    }

    init {
        sosButton.onDown = { now -> if (!sosBusy) { sosGesture.down(now); setStatus("") } }
        sosButton.onTick = { now -> afterSosStep(sosGesture.tick(now)) }
        sosButton.onUp = { now -> afterSosStep(sosGesture.up(now)); if (!sosBusy) sosButton.progress = 0f }
        sosButton.onAbort = { sosGesture.cancel(); sosButton.progress = 0f }

        voiceButton.onDown = { now -> startVoice(now) }
        voiceButton.onTick = { now -> afterVoiceStep(voiceGesture.tick(now)) }
        voiceButton.onUp = { now -> afterVoiceStep(voiceGesture.up(now)) }
        voiceButton.onAbort = { abortVoice() }
    }

    /** Focus hint from the widget: the screen shows both buttons either way; this only sets the first message. */
    fun focus(which: String?) {
        if (which == "voice" && !hasMic()) setStatus(activity.getString(R.string.voice_mic_needed))
    }

    // ------------------------------------------------------------------ SOS
    private fun afterSosStep(s: SosGesture.State) {
        when (s) {
            is SosGesture.State.Holding -> sosButton.progress = s.progress
            SosGesture.State.Fired -> fireSos()
            SosGesture.State.Idle -> sosButton.progress = 0f
        }
    }

    private fun fireSos() {
        if (sosBusy) return
        sosBusy = true
        sosGesture.reset()
        sosButton.progress = 1f
        sosButton.performHapticFeedback(HapticFeedbackConstants.LONG_PRESS)
        setStatus(activity.getString(R.string.sos_sending))
        app.io.execute {
            // No location in the thin build (no location permission): the family is told SOS, not where.
            val out = SosSender(app.client, { Thread.sleep(it) }).send(null, null) { n ->
                if (n > 1) activity.runOnUiThread { setStatus(activity.getString(R.string.sos_sending) + " ($n)") }
            }
            activity.runOnUiThread {
                sosBusy = false
                sosButton.progress = 0f
                when (out) {
                    is SosSender.Outcome.Sent -> setStatus(out.message ?: activity.getString(R.string.sos_sent))
                    is SosSender.Outcome.NotSent -> {
                        setStatus(activity.getString(R.string.sos_not_sent))
                        if (out.lastError == ApiError.Unauthorized) host.onUnpaired()
                    }
                }
            }
        }
    }

    // ------------------------------------------------------------------ voice note
    private fun hasMic() = activity.checkSelfPermission(Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED

    private fun startVoice(now: Long) {
        if (voiceBusy) return
        if (!hasMic()) { // first press only asks; recording starts on the next press
            activity.requestPermissions(arrayOf(Manifest.permission.RECORD_AUDIO), REQ_MIC)
            voiceButton.abort()
            return
        }
        if (!recorder.start()) {
            setStatus(activity.getString(R.string.voice_no_mic))
            voiceButton.abort()
            return
        }
        voiceGesture.down(now)
        setStatus(activity.getString(R.string.voice_recording))
    }

    private fun afterVoiceStep(s: VoiceNoteGesture.State) {
        when (s) {
            is VoiceNoteGesture.State.Done -> finishVoice(s.seconds)
            VoiceNoteGesture.State.TooShort -> {
                recorder.cancel()
                voiceGesture.reset()
                setStatus(activity.getString(R.string.voice_too_short))
            }
            else -> Unit
        }
    }

    private fun finishVoice(seconds: Int) {
        voiceGesture.reset()
        val audio = recorder.stop() // first: abort() below would cancel (and delete) a running recording
        voiceButton.abort()
        if (audio == null) {
            setStatus(activity.getString(R.string.voice_too_short))
            return
        }
        voiceBusy = true
        setStatus(activity.getString(R.string.voice_sending))
        app.io.execute {
            val r = app.client.voice(audio, "audio/mp4", seconds)
            recorder.deleteFile() // the local copy goes whatever the outcome; the parent can simply record again
            activity.runOnUiThread {
                voiceBusy = false
                when (r) {
                    is ApiResult.Ok -> setStatus(r.value.replyText ?: activity.getString(R.string.voice_sent))
                    is ApiResult.Err -> when (r.error) {
                        ApiError.ConsentRequired -> setStatus(activity.getString(R.string.voice_no_consent))
                        ApiError.Unauthorized -> host.onUnpaired()
                        else -> setStatus(activity.getString(R.string.voice_failed))
                    }
                }
            }
        }
    }

    private fun abortVoice() {
        voiceGesture.cancel()
        recorder.cancel()
    }

    fun onPermissionResult(requestCode: Int) {
        if (requestCode == REQ_MIC && !hasMic()) setStatus(activity.getString(R.string.voice_mic_needed))
    }

    /** Screen leaves the foreground: drop any hold and any recording. The microphone is never used in the background. */
    fun onPause() {
        sosButton.abort()
        voiceButton.abort()
        abortVoice()
    }

    private fun setStatus(text: String) {
        status.text = text
    }

    companion object {
        const val REQ_MIC = 41
    }
}
