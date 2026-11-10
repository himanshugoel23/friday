package app.robin.parent

import android.animation.ValueAnimator
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.pm.ServiceInfo
import android.content.res.Configuration
import android.graphics.Color
import android.graphics.PixelFormat
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.net.Uri
import android.os.Build
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.os.SystemClock
import android.view.Gravity
import android.view.HapticFeedbackConstants
import android.view.MotionEvent
import android.view.View
import android.view.ViewGroup
import android.view.WindowInsets
import android.view.WindowManager
import android.widget.Button
import android.widget.LinearLayout
import android.widget.TextView
import app.robin.core.ApiError
import app.robin.core.BubbleCard
import app.robin.core.BubbleCards
import app.robin.core.BubbleEffect
import app.robin.core.BubbleGlyph
import app.robin.core.BubbleMenu
import app.robin.core.BubblePolicy
import app.robin.core.BubblePosition
import app.robin.core.BubbleSession
import app.robin.core.BubbleState
import app.robin.core.BubbleStates
import app.robin.core.BubbleWord
import app.robin.core.CardKey
import app.robin.core.ColourRole
import app.robin.core.Haptic
import app.robin.core.MenuItem
import app.robin.core.MenuItemId
import app.robin.core.Pt
import app.robin.core.ScreenBox
import app.robin.core.SosGesture
import app.robin.core.SosSender
import app.robin.core.SpeechPlan
import app.robin.core.VoiceRecorderPort
import app.robin.core.VoiceTurn

/**
 * The floating mic. A foreground service that owns two small overlay windows (the bubble, and one panel next to it for the
 * menu or the reply card). It does nothing on its own: the microphone opens only after a tap on the bubble, closes the
 * moment the question ends, the screen turns off or the service stops. No hotword, no accessibility service, no text is
 * ever put into another app. The rules live in :core (BubbleSession, BubblePosition, TouchClassifier, VoiceTurn, SosGesture).
 */
class BubbleService : Service(), BubbleView.Listener {
    private val main = Handler(Looper.getMainLooper())
    private lateinit var wm: WindowManager
    private lateinit var prefs: BubblePrefs
    private val session = BubbleSession()

    private lateinit var bubble: BubbleView
    private lateinit var bubbleLp: WindowManager.LayoutParams
    private var bubbleAttached = false
    private var dragStart = Pt(0, 0)
    private var dragging = false
    private var snapAnim: ValueAnimator? = null

    private var panel: View? = null
    private var panelLp: WindowManager.LayoutParams? = null
    private val panelHide = Runnable { removePanel() }

    private var imeTop: Int? = null

    // voice
    private lateinit var recorder: VoiceRecorder
    private lateinit var turn: VoiceTurn
    private lateinit var speaker: ReplySpeaker
    @Volatile private var lastLevel = 0
    private var lastState: BubbleState = BubbleState.IDLE
    private var running = false
    private var micForeground = false
    private val sosGesture = SosGesture()
    private var sosBusy = false

    private val ticker = object : Runnable {
        override fun run() {
            val s = turn.tick(SystemClock.elapsedRealtime())
            bubble.level = lastLevel / 12_000f
            if (s is VoiceTurn.State.Recording) main.postDelayed(this, 100) else afterStep(s)
        }
    }

    private val screenOff = object : BroadcastReceiver() {
        override fun onReceive(c: Context, i: Intent) {
            // Screen off: the microphone and the voice both stop. Nothing is recorded or spoken with the screen dark.
            stopVoice()
            removePanel()
        }
    }

    override fun onBind(intent: Intent?): IBinder? = null

    // ------------------------------------------------------------------ lifecycle
    override fun onCreate() {
        super.onCreate()
        alive = true
        wm = getSystemService(WindowManager::class.java)
        prefs = BubblePrefs(this)
        recorder = VoiceRecorder(this)
        val port = object : VoiceRecorderPort by recorder {
            override fun level(): Int = recorder.level().also { lastLevel = it }
        }
        turn = VoiceTurn(port, { audio, mime, secs -> robin.client.voice(audio, mime, secs) })
        speaker = ReplySpeaker(this)
        bubble = BubbleView(this).apply { listener = this@BubbleService }
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        // startForegroundService() requires startForeground() within seconds, even when we are about to stop again.
        goForeground(withMic = false)
        when (intent?.action) {
            ACTION_STOP -> { stopSelfCleanly(); return START_NOT_STICKY }
            ACTION_SHOW -> { session.show(); if (running) attachBubble(); updateNotification(); return START_STICKY }
        }
        // The service checks again itself: a permission may have been withdrawn in system settings since the switch was set.
        if (!BubblePolicy.mayRun(prefs.settings(), BubbleEnv.gate(this))) {
            stopSelfCleanly()
            return START_NOT_STICKY
        }
        if (!running) {
            running = true
            registerReceiver(screenOff, IntentFilter(Intent.ACTION_SCREEN_OFF))
            if (!attachBubble()) { turnOffFlag(); stopSelfCleanly(); return START_NOT_STICKY }
        }
        updateNotification()
        return START_STICKY
    }

    override fun onConfigurationChanged(newConfig: Configuration) {
        super.onConfigurationChanged(newConfig)
        if (bubbleAttached) { placeFromPrefs(); removePanel() }
    }

    override fun onDestroy() {
        stopVoice()
        main.removeCallbacksAndMessages(null)
        snapAnim?.cancel()
        removePanel()
        if (bubbleAttached) { try { wm.removeView(bubble) } catch (_: Exception) {}; bubbleAttached = false }
        if (running) { try { unregisterReceiver(screenOff) } catch (_: Exception) {}; running = false }
        speaker.stop()
        alive = false
        super.onDestroy()
    }

    private fun stopSelfCleanly() {
        stopForeground(STOP_FOREGROUND_REMOVE)
        stopSelf()
    }

    /** The overlay could not be shown (permission gone): remember "off" so nothing restarts it. */
    private fun turnOffFlag() {
        prefs.save(BubblePolicy.parentTurnOff(prefs.settings()))
    }

    // ------------------------------------------------------------------ foreground + notification
    private fun goForeground(withMic: Boolean) {
        val n = buildNotification()
        try {
            when {
                Build.VERSION.SDK_INT >= 34 -> {
                    // specialUse for the long-lived overlay; microphone is added ONLY while a tapped question is being recorded.
                    val type = ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE or (if (withMic) ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE else 0)
                    startForeground(NOTIF_ID, n, type)
                }
                else -> startForeground(NOTIF_ID, n)
            }
            micForeground = withMic
        } catch (e: Exception) {
            // Not allowed right now (for example the microphone type from the background): keep the plain overlay service.
            if (withMic) goForeground(false) else stopSelfCleanly()
        }
    }

    private fun channel() {
        val nm = getSystemService(NotificationManager::class.java)
        if (nm.getNotificationChannel(CHANNEL) == null) {
            nm.createNotificationChannel(
                NotificationChannel(CHANNEL, getString(R.string.bubble_channel_name), NotificationManager.IMPORTANCE_LOW).apply {
                    setShowBadge(false)
                    setSound(null, null)
                },
            )
        }
    }

    private fun buildNotification(): Notification {
        channel()
        val hidden = !session.visible
        // Tapping opens Robin's first screen, where the clear on/off switch is. When hidden, tapping brings the bubble back instead.
        val tap = if (hidden) {
            PendingIntent.getService(this, 1, Intent(this, BubbleService::class.java).setAction(ACTION_SHOW), PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        } else {
            PendingIntent.getActivity(this, 2, Intent(this, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK), PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        }
        return Notification.Builder(this, CHANNEL)
            .setSmallIcon(R.drawable.ic_mic)
            .setContentTitle(getString(if (hidden) R.string.bubble_notif_hidden_title else R.string.bubble_notif_title))
            .setContentText(getString(if (hidden) R.string.bubble_notif_hidden_text else R.string.bubble_notif_text))
            .setContentIntent(tap)
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .setCategory(Notification.CATEGORY_SERVICE)
            .setVisibility(Notification.VISIBILITY_PUBLIC)
            .build()
    }

    private fun updateNotification() {
        try { getSystemService(NotificationManager::class.java).notify(NOTIF_ID, buildNotification()) } catch (_: Exception) {}
    }

    // ------------------------------------------------------------------ windows
    private fun dp(v: Int) = (v * resources.displayMetrics.density).toInt()
    private val margin get() = dp(6)

    private fun overlayParams(w: Int, h: Int) = WindowManager.LayoutParams(
        w, h, WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY,
        WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL or
            WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN or WindowManager.LayoutParams.FLAG_LAYOUT_NO_LIMITS,
        PixelFormat.TRANSLUCENT,
    ).apply { gravity = Gravity.TOP or Gravity.START; title = "robin-mic" }

    private fun screenBox(): ScreenBox {
        if (Build.VERSION.SDK_INT >= 30) {
            val m = wm.currentWindowMetrics
            val ins = m.windowInsets.getInsetsIgnoringVisibility(WindowInsets.Type.systemBars() or WindowInsets.Type.displayCutout())
            return ScreenBox(m.bounds.width(), m.bounds.height(), ins.top, ins.bottom)
        }
        val dm = resources.displayMetrics
        @Suppress("DEPRECATION") val real = android.util.DisplayMetrics().also { wm.defaultDisplay.getRealMetrics(it) }
        fun res(name: String): Int {
            val id = resources.getIdentifier(name, "dimen", "android")
            return if (id > 0) resources.getDimensionPixelSize(id) else 0
        }
        return ScreenBox(real.widthPixels.coerceAtLeast(dm.widthPixels), real.heightPixels, res("status_bar_height"), res("navigation_bar_height"))
    }

    private fun attachBubble(): Boolean {
        if (!session.visible) return true
        if (bubbleAttached) return true
        bubbleLp = overlayParams(bubble.sizePx, bubble.sizePx)
        placeFromPrefs()
        return try {
            wm.addView(bubble, bubbleLp)
            bubbleAttached = true
            bubble.setOnApplyWindowInsetsListener { v, insets ->
                if (Build.VERSION.SDK_INT >= 30) {
                    val box = screenBox()
                    imeTop = if (insets.isVisible(WindowInsets.Type.ime())) box.height - insets.getInsets(WindowInsets.Type.ime()).bottom else null
                    keepOffKeyboard()
                }
                v.onApplyWindowInsets(insets)
            }
            bubble.requestApplyInsets()
            renderBubble(turn.state, force = true)
            true
        } catch (e: Exception) { // BadTokenException / SecurityException: "Display over other apps" was withdrawn
            false
        }
    }

    private fun detachBubble() {
        removePanel()
        if (bubbleAttached) { try { wm.removeView(bubble) } catch (_: Exception) {}; bubbleAttached = false }
    }

    private fun placeFromPrefs() {
        val box = screenBox()
        val pl = prefs.placement()
        val p = if (pl == null) BubblePosition.default(box, bubble.sizePx, margin) else BubblePosition.fromPlacement(box, bubble.sizePx, pl, margin)
        moveBubble(BubblePosition.avoidKeyboard(box, bubble.sizePx, p, imeTop, margin))
    }

    private fun moveBubble(p: Pt) {
        bubbleLp.x = p.x
        bubbleLp.y = p.y
        if (bubbleAttached) try { wm.updateViewLayout(bubble, bubbleLp) } catch (_: Exception) {}
    }

    private fun keepOffKeyboard() {
        if (!bubbleAttached || dragging) return
        val box = screenBox()
        val moved = BubblePosition.avoidKeyboard(box, bubble.sizePx, Pt(bubbleLp.x, bubbleLp.y), imeTop, margin)
        if (imeTop == null) placeFromPrefs() else moveBubble(moved)
        removePanel()
    }

    // ------------------------------------------------------------------ BubbleView.Listener
    override fun onTap() = apply(session.onBubbleTap())

    override fun onLongPress() {
        bubble.performHapticFeedback(HapticFeedbackConstants.LONG_PRESS)
        apply(session.onBubbleLongPress())
    }

    override fun onDragStart() {
        dragging = true
        snapAnim?.cancel()
        removePanel()
        dragStart = Pt(bubbleLp.x, bubbleLp.y)
    }

    override fun onDrag(dx: Float, dy: Float) {
        val p = BubblePosition.clampWhileDragging(screenBox(), bubble.sizePx, dragStart.x + dx.toInt(), dragStart.y + dy.toInt())
        moveBubble(p)
    }

    override fun onDragEnd() {
        if (!dragging) return
        dragging = false
        val box = screenBox()
        val target = BubblePosition.snap(box, bubble.sizePx, bubbleLp.x, bubbleLp.y, margin)
        prefs.savePlacement(BubblePosition.toPlacement(box, bubble.sizePx, target, margin))
        val fromX = bubbleLp.x
        snapAnim = ValueAnimator.ofInt(fromX, target.x).apply {
            duration = 160
            addUpdateListener { moveBubble(Pt(it.animatedValue as Int, target.y)) }
            start()
        }
    }

    override fun onA11yAction(id: Int): Boolean {
        val box = screenBox()
        return when (id) {
            BubbleView.A11Y_LEFT, BubbleView.A11Y_RIGHT -> {
                val x = if (id == BubbleView.A11Y_LEFT) 0 else box.width
                val t = BubblePosition.snap(box, bubble.sizePx, x, bubbleLp.y, margin)
                prefs.savePlacement(BubblePosition.toPlacement(box, bubble.sizePx, t, margin))
                moveBubble(t)
                removePanel()
                true
            }
            BubbleView.A11Y_HIDE -> { hideForNow(); true }
            else -> false
        }
    }

    // ------------------------------------------------------------------ effects
    private fun apply(e: BubbleEffect) {
        when (e) {
            BubbleEffect.None -> Unit
            BubbleEffect.ToggleTalk -> onTalk()
            BubbleEffect.ShowMenu -> showMenu()
            BubbleEffect.CloseMenu -> removePanel()
            BubbleEffect.HideBubble -> hideForNow()
            BubbleEffect.TurnOff -> { turnOffFlag(); stopSelfCleanly() }
            BubbleEffect.DialEmergency -> dial112()
            BubbleEffect.RaiseSos -> fireSos()
        }
    }

    private fun hideForNow() {
        stopVoice()
        // Go through the :core session so the rule (menu -> hidden) is not duplicated; harmless if it is already hidden.
        if (session.mode == BubbleSession.Mode.COLLAPSED) session.onBubbleLongPress()
        session.onMenuItem(BubbleMenu.items().first { it.id == MenuItemId.HIDE_FOR_NOW }, 0)
        detachBubble()
        updateNotification()
    }

    private fun dial112() {
        removePanel()
        try {
            startActivity(Intent(Intent.ACTION_DIAL, Uri.parse("tel:112")).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
        } catch (_: Exception) {
            showTextCard(getString(R.string.bubble_dial_failed), show112 = false)
        }
    }

    // ------------------------------------------------------------------ voice turn (same VoiceTurn and ApiClient as the widget)
    private fun isPaired() = robin.serverConfigured && robin.tokens.token() != null

    private fun onTalk() {
        removePanel()
        if (!isPaired()) { showTextCard(getString(R.string.voice_not_set_up), false); buzz(Haptic.REJECT); return }
        if (!BubbleEnv.micGranted(this)) { showTextCard(getString(R.string.voice_mic_needed), false); buzz(Haptic.REJECT); return }
        speaker.stop()
        if (turn.state !is VoiceTurn.State.Recording) goForeground(withMic = true) // microphone service type only for this question
        afterStep(turn.tap(SystemClock.elapsedRealtime()))
    }

    private fun afterStep(s: VoiceTurn.State) {
        renderBubble(s)
        when (s) {
            is VoiceTurn.State.Recording -> { main.removeCallbacks(ticker); main.postDelayed(ticker, 100) }
            is VoiceTurn.State.Uploading -> startUpload()
            else -> { bubble.level = 0f; if (micForeground) goForeground(false) } // microphone released: drop the microphone type too
        }
    }

    private fun startUpload() {
        robin.io.execute {
            val s = turn.upload { Thread.sleep(it) } // the file is already deleted; retries use the bytes in memory
            main.post { onUploadDone(s) }
        }
    }

    private fun onUploadDone(s: VoiceTurn.State) {
        if (!running) return
        if (s is VoiceTurn.State.Error && s.reason == VoiceTurn.Failure.UNPAIRED) robin.pairing.onUnauthorized()
        afterStep(s)
        if (s is VoiceTurn.State.Answering) {
            val lang = robin.profiles.profile()?.language ?: "en"
            val plan = SpeechPlan.choose(s.answer, BuildConfig.BASE_URL, lang)
            val fallback = s.answer.text ?: getString(R.string.voice_answer_fallback)
            speaker.speak(plan, fallback, SpeechPlan.localeTag(lang)) { afterStep(turn.answerDone()); scheduleCardHide(CARD_ANSWER_MS) }
        }
    }

    /** Microphone, voice and any upload callback stop now (screen off, hide, destroy). */
    private fun stopVoice() {
        main.removeCallbacks(ticker)
        speaker.stop()
        turn.cancel()
        bubble.level = 0f
        if (micForeground && running) goForeground(false)
        if (bubbleAttached) renderBubble(turn.state)
    }

    private fun renderBubble(s: VoiceTurn.State, force: Boolean = false) {
        val look = BubbleStates.look(s)
        val changed = look.state != lastState
        lastState = look.state
        val word = getString(wordRes(look.word))
        val desc = getString(R.string.bubble_desc_prefix) + " " + word + ". " + getString(descRes(look.state))
        bubble.render(look.shape, glyphRes(look.glyph), word, getColor(colourRes(look.colour)), desc)
        if (changed || force) {
            if (changed) buzz(look.haptic)
            val card = BubbleCards.from(s)
            when {
                card != null -> showCard(card)
                s is VoiceTurn.State.Uploading -> removePanel()
                else -> Unit // idle after an answer: the card stays until its timer ends
            }
        }
    }

    private fun buzz(h: Haptic) {
        val c = when (h) {
            Haptic.NONE -> return
            Haptic.CONFIRM -> if (Build.VERSION.SDK_INT >= 30) HapticFeedbackConstants.CONFIRM else HapticFeedbackConstants.VIRTUAL_KEY
            Haptic.REJECT -> if (Build.VERSION.SDK_INT >= 30) HapticFeedbackConstants.REJECT else HapticFeedbackConstants.LONG_PRESS
        }
        bubble.performHapticFeedback(c)
    }

    private fun wordRes(w: BubbleWord) = when (w) {
        BubbleWord.TALK -> R.string.bubble_word_talk
        BubbleWord.LISTENING -> R.string.bubble_word_listening
        BubbleWord.SENDING -> R.string.bubble_word_sending
        BubbleWord.SPEAKING -> R.string.bubble_word_speaking
        BubbleWord.NO_INTERNET -> R.string.bubble_word_no_internet
        BubbleWord.PROBLEM -> R.string.bubble_word_problem
    }

    private fun descRes(s: BubbleState) = when (s) {
        BubbleState.IDLE -> R.string.bubble_desc_idle
        BubbleState.LISTENING -> R.string.bubble_desc_listening
        BubbleState.SENDING -> R.string.bubble_desc_sending
        BubbleState.ANSWERING -> R.string.bubble_desc_answering
        BubbleState.OFFLINE -> R.string.bubble_desc_offline
        BubbleState.PROBLEM -> R.string.bubble_desc_problem
    }

    private fun glyphRes(g: BubbleGlyph) = when (g) {
        BubbleGlyph.MIC -> R.drawable.ic_mic
        BubbleGlyph.STOP -> R.drawable.ic_stop
        BubbleGlyph.SEND -> R.drawable.ic_send
        BubbleGlyph.SPEAKER -> R.drawable.ic_speaker
        BubbleGlyph.OFFLINE -> R.drawable.ic_offline
        BubbleGlyph.WARNING -> R.drawable.ic_warning
    }

    private fun colourRes(c: ColourRole) = when (c) {
        ColourRole.VOICE -> R.color.robin_voice
        ColourRole.LISTENING -> R.color.robin_listening
        ColourRole.BUSY -> R.color.robin_busy
        ColourRole.ANSWER -> R.color.robin_answer
        ColourRole.PROBLEM -> R.color.robin_problem
    }

    // ------------------------------------------------------------------ SOS (from the menu: 2 second hold, then the same sender)
    private fun fireSos() {
        removePanel()
        if (sosBusy) return
        sosBusy = true
        sosGesture.reset()
        bubble.performHapticFeedback(HapticFeedbackConstants.LONG_PRESS)
        showTextCard(getString(R.string.sos_sending), show112 = true)
        robin.io.execute {
            // No location in this build (no location permission): the family is told SOS, not where.
            val out = SosSender(robin.client, { Thread.sleep(it) }).send(null, null) { n ->
                if (n > 1) main.post { showTextCard(getString(R.string.sos_sending) + " ($n)", show112 = true) }
            }
            main.post {
                sosBusy = false
                when (out) {
                    is SosSender.Outcome.Sent -> showTextCard(out.message ?: getString(R.string.sos_sent), show112 = true)
                    is SosSender.Outcome.NotSent -> {
                        if (out.lastError == ApiError.Unauthorized) robin.pairing.onUnauthorized()
                        showTextCard(getString(R.string.sos_not_sent), show112 = true)
                    }
                }
                scheduleCardHide(CARD_SOS_MS)
            }
        }
    }

    // ------------------------------------------------------------------ panel (menu or reply card; one at a time)
    private fun panelBackground() = GradientDrawable().apply {
        setColor(Color.WHITE)
        cornerRadius = dp(20).toFloat()
        setStroke(dp(3), 0xFF202124.toInt())
    }

    private fun bigButton(text: String, bg: Int, onClick: () -> Unit) = Button(this).apply {
        this.text = text
        textSize = 22f
        isAllCaps = false
        setTextColor(Color.WHITE)
        setTypeface(typeface, Typeface.BOLD)
        minHeight = dp(60)
        minimumHeight = dp(60)
        background = GradientDrawable().apply { setColor(bg); cornerRadius = dp(14).toFloat() }
        setOnClickListener { onClick() }
    }

    private fun showCard(card: BubbleCard) {
        val text = when (card.key) {
            CardKey.ANSWER -> card.text ?: getString(R.string.voice_answer_fallback)
            CardKey.ANSWER_FALLBACK -> getString(R.string.voice_answer_fallback)
            CardKey.LISTENING_HINT -> getString(R.string.voice_listening_hint)
            CardKey.OFFLINE -> getString(R.string.voice_offline_detail)
            CardKey.NO_MIC -> getString(R.string.voice_no_mic)
            CardKey.TOO_SHORT -> getString(R.string.voice_too_short)
            CardKey.NO_SPEECH -> getString(R.string.voice_no_speech)
            CardKey.NOT_UNDERSTOOD -> getString(R.string.voice_not_understood)
            CardKey.NO_CONSENT -> getString(R.string.voice_no_consent)
            CardKey.BUSY -> getString(R.string.voice_busy)
            CardKey.NOT_SET_UP -> getString(R.string.voice_not_set_up)
            CardKey.FAILED -> getString(R.string.voice_failed)
        }
        showTextCard(text, show112 = false)
        // A listening hint stays while recording; answers stay until their own timer; problems fade after a while.
        when (card.key) {
            CardKey.LISTENING_HINT, CardKey.ANSWER, CardKey.ANSWER_FALLBACK -> main.removeCallbacks(panelHide)
            else -> scheduleCardHide(CARD_ERROR_MS)
        }
    }

    private fun showTextCard(text: String, show112: Boolean) {
        if (!bubbleAttached) return
        val col = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(18), dp(16), dp(18), dp(16))
            background = panelBackground()
        }
        col.addView(TextView(this).apply {
            this.text = text
            textSize = 26f // large type
            setTextColor(getColor(R.color.robin_ink))
            accessibilityLiveRegion = View.ACCESSIBILITY_LIVE_REGION_POLITE
        })
        if (show112) col.addView(bigButton(getString(R.string.home_call_112), getColor(R.color.robin_sos)) { dial112() }, rowLp())
        col.addView(bigButton(getString(R.string.bubble_card_close), getColor(R.color.robin_busy)) { removePanel() }, rowLp())
        showPanel(col)
    }

    private fun rowLp() = LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT).apply { topMargin = dp(10) }

    private fun showMenu() {
        if (!bubbleAttached) return
        val col = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(14), dp(14), dp(14), dp(14))
            background = panelBackground()
        }
        for (item in BubbleMenu.items()) {
            when (item.id) {
                MenuItemId.SOS -> col.addView(sosHoldButton(item), LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(84)))
                MenuItemId.CALL_112 -> col.addView(bigButton(getString(R.string.home_call_112), getColor(R.color.robin_sos)) { apply(session.onMenuItem(item, 0)) }, rowLp())
                MenuItemId.HIDE_FOR_NOW -> col.addView(bigButton(getString(R.string.bubble_menu_hide), getColor(R.color.robin_voice)) { apply(session.onMenuItem(item, 0)) }, rowLp())
                MenuItemId.TURN_OFF_FOR_NOW -> col.addView(bigButton(getString(R.string.bubble_menu_turn_off), getColor(R.color.robin_busy)) { apply(session.onMenuItem(item, 0)) }, rowLp())
                MenuItemId.CLOSE -> col.addView(bigButton(getString(R.string.bubble_menu_close), 0xFF5F6368.toInt()) { apply(session.onMenuItem(item, 0)) }, rowLp())
            }
        }
        main.removeCallbacks(panelHide)
        showPanel(col, watchOutside = true)
        scheduleCardHide(MENU_MS) // a menu left open closes itself
    }

    /** SOS is the same press-and-hold as on the home screen: nothing happens until the finger has stayed down for 2 seconds. */
    private fun sosHoldButton(item: MenuItem): HoldButton {
        val b = HoldButton(this, getColor(R.color.robin_sos))
        b.text = getString(R.string.home_sos) + "\n" + getString(R.string.home_sos_hold)
        b.contentDescription = getString(R.string.home_sos_desc)
        b.textSize = 22f
        var downAt = 0L
        b.onDown = { now -> downAt = now; sosGesture.down(now) }
        b.onTick = { now ->
            when (val s = sosGesture.tick(now)) {
                is SosGesture.State.Holding -> b.progress = s.progress
                SosGesture.State.Fired -> { b.progress = 1f; apply(session.onMenuItem(item, now - downAt)) }
                SosGesture.State.Idle -> b.progress = 0f
            }
        }
        b.onUp = { now ->
            if (sosGesture.up(now) == SosGesture.State.Fired) apply(session.onMenuItem(item, now - downAt)) else { b.progress = 0f; sosGesture.reset() }
        }
        b.onAbort = { sosGesture.cancel(); b.progress = 0f }
        return b
    }

    private fun showPanel(content: View, watchOutside: Boolean = false) {
        removePanelView()
        val box = screenBox()
        val maxW = (box.width - 2 * margin).coerceAtMost(dp(340))
        content.measure(View.MeasureSpec.makeMeasureSpec(maxW, View.MeasureSpec.EXACTLY), View.MeasureSpec.makeMeasureSpec(0, View.MeasureSpec.UNSPECIFIED))
        val w = content.measuredWidth
        val h = content.measuredHeight
        val o = BubblePosition.cardOrigin(box, Pt(bubbleLp.x, bubbleLp.y), bubble.sizePx, w, h, dp(8), imeTop)
        val lp = overlayParams(w, h).apply {
            x = o.x
            y = o.y
            if (watchOutside) flags = flags or WindowManager.LayoutParams.FLAG_WATCH_OUTSIDE_TOUCH
        }
        if (watchOutside) {
            content.setOnTouchListener { _, e ->
                if (e.action == MotionEvent.ACTION_OUTSIDE) { apply(session.dismissMenu()); true } else false
            }
        }
        try {
            wm.addView(content, lp)
            panel = content
            panelLp = lp
        } catch (_: Exception) {
            panel = null
        }
    }

    private fun removePanelView() {
        panel?.let { try { wm.removeView(it) } catch (_: Exception) {} }
        panel = null
        panelLp = null
    }

    private fun removePanel() {
        main.removeCallbacks(panelHide)
        removePanelView()
        session.dismissMenu()
    }

    private fun scheduleCardHide(ms: Long) {
        main.removeCallbacks(panelHide)
        main.postDelayed(panelHide, ms)
    }

    companion object {
        const val ACTION_STOP = "app.robin.parent.BUBBLE_STOP"
        const val ACTION_SHOW = "app.robin.parent.BUBBLE_SHOW"
        private const val CHANNEL = "robin_bubble"
        private const val NOTIF_ID = 2201
        private const val CARD_ANSWER_MS = 45_000L
        private const val CARD_ERROR_MS = 20_000L
        private const val CARD_SOS_MS = 60_000L
        private const val MENU_MS = 30_000L

        /** True while the service object exists in this process (used by the switch to show the truth). */
        @Volatile var alive = false
            private set

        /** Start (or restart) the floating mic. Call only from a foreground screen or the boot receiver. */
        fun start(ctx: Context) {
            ctx.startForegroundService(Intent(ctx, BubbleService::class.java))
        }

        fun stop(ctx: Context) {
            ctx.stopService(Intent(ctx, BubbleService::class.java))
        }
    }
}
