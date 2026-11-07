package app.robin.parent

import android.Manifest
import android.app.Activity
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.net.Uri
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.view.Gravity
import android.view.HapticFeedbackConstants
import android.view.View
import android.view.ViewGroup
import android.view.accessibility.AccessibilityNodeInfo
import android.widget.Button
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.TextView
import app.robin.core.ApiError
import app.robin.core.SosGesture
import app.robin.core.SosSender
import app.robin.core.SpeechPlan
import app.robin.core.VoiceTurn

/** The one big microphone button: icon plus a short state word, colour per state. Tap only; no typing anywhere. */
class MicView(private val activity: Activity) : LinearLayout(activity) {
    private val icon = ImageView(activity).apply {
        importantForAccessibility = IMPORTANT_FOR_ACCESSIBILITY_NO
        layoutParams = LayoutParams(dp(96), dp(96))
    }
    private val label = TextView(activity).apply {
        textSize = 30f
        setTextColor(Color.WHITE)
        setTypeface(typeface, Typeface.BOLD)
        gravity = Gravity.CENTER
        importantForAccessibility = IMPORTANT_FOR_ACCESSIBILITY_NO
    }

    init {
        orientation = VERTICAL
        gravity = Gravity.CENTER
        minimumHeight = dp(240) // far above the 48 dp touch target minimum
        setPadding(dp(16), dp(16), dp(16), dp(16))
        isClickable = true
        isFocusable = true
        accessibilityLiveRegion = ACCESSIBILITY_LIVE_REGION_POLITE
        addView(icon)
        addView(label)
        accessibilityDelegate = object : AccessibilityDelegate() {
            override fun onInitializeAccessibilityNodeInfo(host: View, info: AccessibilityNodeInfo) {
                super.onInitializeAccessibilityNodeInfo(host, info)
                info.className = Button::class.java.name // TalkBack: "button, double tap to activate"
            }
        }
    }

    private fun dp(v: Int) = (v * resources.displayMetrics.density).toInt()

    fun render(iconRes: Int, text: String, colour: Int, description: String) {
        icon.setImageResource(iconRes)
        label.text = text
        background = GradientDrawable().apply { setColor(colour); cornerRadius = dp(40).toFloat() }
        contentDescription = description
    }
}

/**
 * Voice-first panel: the big mic (tap to talk, tap again, silence or the maximum length to send), the answer in large
 * type and spoken aloud, then SOS (press and hold) and Call 112. Used by the home screen and by [QuickActivity] (the
 * widget target, shown over the lock screen). The rules are in :core; this class only connects touches, the recorder,
 * the network and the speaker.
 */
class QuickPanel(private val activity: Activity, private val host: Host) {
    interface Host {
        /** The server no longer knows this phone (bad or revoked token). */
        fun onUnpaired()
    }

    private val app = activity.robin
    private val main = Handler(Looper.getMainLooper())
    private val sosGesture = SosGesture()
    private val recorder = VoiceRecorder(activity)
    private val turn = VoiceTurn(recorder, { audio, mime, secs -> app.client.voice(audio, mime, secs) })
    private val speaker = ReplySpeaker(activity)
    private var sosBusy = false
    private var inactive = false
    private var wantAutoStart = false

    private val mic = MicView(activity)
    private val caption = TextView(activity).apply {
        textSize = 30f
        setTextColor(activity.getColor(R.color.robin_ink))
        gravity = Gravity.CENTER
        minLines = 2
        accessibilityLiveRegion = View.ACCESSIBILITY_LIVE_REGION_POLITE
    }
    private val sosStatus = TextView(activity).apply {
        textSize = 20f
        setTextColor(Color.DKGRAY)
        gravity = Gravity.CENTER
        accessibilityLiveRegion = View.ACCESSIBILITY_LIVE_REGION_POLITE
    }
    private val sosButton = HoldButton(activity, activity.getColor(R.color.robin_sos))
    private val callButton = Button(activity).apply {
        setText(R.string.home_call_112)
        textSize = 22f
        minHeight = dp(64)
        // The server never dials. Dialer screen only (ACTION_DIAL needs no permission and cannot call by itself).
        setOnClickListener { activity.startActivity(Intent(Intent.ACTION_DIAL, Uri.parse("tel:112"))) }
    }

    private fun dp(v: Int) = (v * activity.resources.displayMetrics.density).toInt()

    val view: View = LinearLayout(activity).apply {
        orientation = LinearLayout.VERTICAL
        fun add(v: View, h: Int) = addView(v, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, h).apply { topMargin = dp(16) })
        sosButton.text = activity.getString(R.string.home_sos) + "\n" + activity.getString(R.string.home_sos_hold)
        sosButton.contentDescription = activity.getString(R.string.home_sos_desc)
        sosButton.textSize = 24f
        add(mic, ViewGroup.LayoutParams.WRAP_CONTENT)
        add(caption, ViewGroup.LayoutParams.WRAP_CONTENT)
        add(sosButton, dp(130))
        add(sosStatus, ViewGroup.LayoutParams.WRAP_CONTENT)
        add(callButton, ViewGroup.LayoutParams.WRAP_CONTENT)
    }

    private val ticker = object : Runnable {
        override fun run() {
            val s = turn.tick(SystemClock.elapsedRealtime())
            if (s is VoiceTurn.State.Recording) main.postDelayed(this, 100) else afterStep(s)
        }
    }

    init {
        mic.setOnClickListener { onMicTap() }
        sosButton.onDown = { now -> if (!sosBusy) { sosGesture.down(now); sosStatus.text = "" } }
        sosButton.onTick = { now -> afterSosStep(sosGesture.tick(now)) }
        sosButton.onUp = { now -> afterSosStep(sosGesture.up(now)); if (!sosBusy) sosButton.progress = 0f }
        sosButton.onAbort = { sosGesture.cancel(); sosButton.progress = 0f }
        render(turn.state)
    }

    /** Widget hint: "voice" starts listening at once (the widget tap was the tap to talk). */
    fun focus(which: String?) {
        if (which == "voice") {
            if (!isPaired()) { render(turn.state); return }
            if (!hasMic()) { wantAutoStart = true; activity.requestPermissions(arrayOf(Manifest.permission.RECORD_AUDIO), REQ_MIC); return }
            if (turn.state is VoiceTurn.State.Idle) onMicTap()
        }
    }

    // ------------------------------------------------------------------ voice turn
    private fun isPaired() = app.serverConfigured && app.tokens.token() != null
    private fun hasMic() = activity.checkSelfPermission(Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED

    private fun onMicTap() {
        if (!isPaired()) {
            caption.text = activity.getString(R.string.voice_not_set_up)
            buzz(false)
            return
        }
        if (!hasMic()) {
            wantAutoStart = true
            activity.requestPermissions(arrayOf(Manifest.permission.RECORD_AUDIO), REQ_MIC)
            return
        }
        speaker.stop()
        afterStep(turn.tap(SystemClock.elapsedRealtime()))
    }

    private fun afterStep(s: VoiceTurn.State) {
        render(s)
        when (s) {
            is VoiceTurn.State.Recording -> { buzz(true); main.removeCallbacks(ticker); main.postDelayed(ticker, 100) }
            is VoiceTurn.State.Uploading -> { buzz(true); startUpload() }
            is VoiceTurn.State.Error, VoiceTurn.State.Offline -> buzz(false)
            else -> Unit
        }
    }

    private fun startUpload() {
        app.io.execute {
            val s = turn.upload { Thread.sleep(it) } // the file is already deleted; retries use the bytes in memory
            main.post { onUploadDone(s) }
        }
    }

    private fun onUploadDone(s: VoiceTurn.State) {
        if (inactive) { turn.cancel(); return } // the screen left meanwhile: say nothing out loud in the background
        if (s is VoiceTurn.State.Error && s.reason == VoiceTurn.Failure.UNPAIRED) { host.onUnpaired(); return }
        render(s)
        if (s is VoiceTurn.State.Answering) {
            buzz(true)
            val lang = app.profiles.profile()?.language ?: "en"
            val plan = SpeechPlan.choose(s.answer, BuildConfig.BASE_URL, lang)
            val fallback = s.answer.text ?: activity.getString(R.string.voice_answer_fallback)
            speaker.speak(plan, fallback, SpeechPlan.localeTag(lang)) { afterStep(turn.answerDone()) }
        } else {
            buzz(false)
        }
    }

    private fun render(s: VoiceTurn.State) {
        fun r(icon: Int, text: Int, colour: Int, hint: Int?) {
            val t = activity.getString(text)
            mic.render(icon, t, activity.getColor(colour), t + (if (hint != null) ". " + activity.getString(hint) else ""))
        }
        mic.keepScreenOn = s !is VoiceTurn.State.Idle
        when (s) {
            VoiceTurn.State.Idle -> r(R.drawable.ic_mic, R.string.voice_tap_to_talk, R.color.robin_voice, null)
            is VoiceTurn.State.Recording -> { r(R.drawable.ic_stop, R.string.voice_listening, R.color.robin_listening, R.string.voice_listening_hint); caption.text = activity.getString(R.string.voice_listening_hint) }
            is VoiceTurn.State.Uploading -> { r(R.drawable.ic_send, R.string.voice_sending, R.color.robin_busy, null); caption.text = "" }
            is VoiceTurn.State.Answering -> {
                r(R.drawable.ic_speaker, R.string.voice_answering, R.color.robin_answer, R.string.voice_answering_hint)
                caption.text = s.answer.text ?: activity.getString(R.string.voice_answer_fallback)
            }
            VoiceTurn.State.Offline -> { r(R.drawable.ic_offline, R.string.voice_offline, R.color.robin_problem, R.string.voice_try_again); caption.text = activity.getString(R.string.voice_offline_detail) }
            is VoiceTurn.State.Error -> {
                r(R.drawable.ic_warning, R.string.voice_problem, R.color.robin_problem, R.string.voice_try_again)
                caption.text = activity.getString(
                    when (s.reason) {
                        VoiceTurn.Failure.NO_MIC -> R.string.voice_no_mic
                        VoiceTurn.Failure.TOO_SHORT -> R.string.voice_too_short
                        VoiceTurn.Failure.NO_SPEECH -> R.string.voice_no_speech
                        VoiceTurn.Failure.NOT_UNDERSTOOD -> R.string.voice_not_understood
                        VoiceTurn.Failure.NO_CONSENT -> R.string.voice_no_consent
                        VoiceTurn.Failure.BUSY -> R.string.voice_busy
                        VoiceTurn.Failure.UNPAIRED -> R.string.voice_not_set_up
                        else -> R.string.voice_failed
                    },
                )
            }
        }
    }

    private fun buzz(ok: Boolean) {
        val c = when {
            ok -> HapticFeedbackConstants.VIRTUAL_KEY
            Build.VERSION.SDK_INT >= 30 -> HapticFeedbackConstants.REJECT
            else -> HapticFeedbackConstants.LONG_PRESS
        }
        mic.performHapticFeedback(c)
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
        sosStatus.text = activity.getString(R.string.sos_sending)
        app.io.execute {
            // No location in the thin build (no location permission): the family is told SOS, not where.
            val out = SosSender(app.client, { Thread.sleep(it) }).send(null, null) { n ->
                if (n > 1) activity.runOnUiThread { sosStatus.text = activity.getString(R.string.sos_sending) + " ($n)" }
            }
            activity.runOnUiThread {
                sosBusy = false
                sosButton.progress = 0f
                when (out) {
                    is SosSender.Outcome.Sent -> sosStatus.text = out.message ?: activity.getString(R.string.sos_sent)
                    is SosSender.Outcome.NotSent -> {
                        sosStatus.text = activity.getString(R.string.sos_not_sent)
                        if (out.lastError == ApiError.Unauthorized) host.onUnpaired()
                    }
                }
            }
        }
    }

    // ------------------------------------------------------------------ lifecycle
    fun onPermissionResult(requestCode: Int) {
        if (requestCode != REQ_MIC) return
        if (hasMic()) {
            if (wantAutoStart && !inactive) { wantAutoStart = false; onMicTap() }
        } else {
            wantAutoStart = false
            caption.text = activity.getString(R.string.voice_mic_needed)
        }
    }

    fun onResume() {
        inactive = false
        render(turn.state)
    }

    /** Screen leaves the foreground: stop recording, stop speaking, drop any hold. The microphone is never used in the background. */
    fun onPause() {
        inactive = true
        wantAutoStart = false
        main.removeCallbacks(ticker)
        sosButton.abort()
        speaker.stop()
        turn.cancel()
        render(turn.state)
    }

    companion object {
        const val REQ_MIC = 41
    }
}
