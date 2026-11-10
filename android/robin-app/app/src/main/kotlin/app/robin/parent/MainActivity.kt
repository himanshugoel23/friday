package app.robin.parent

import android.app.Activity
import android.appwidget.AppWidgetManager
import android.content.ComponentName
import android.content.Intent
import android.os.Build
import android.os.Bundle
import android.speech.tts.TextToSpeech
import android.text.InputFilter
import android.text.InputType
import android.view.View
import android.view.ViewGroup
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import app.robin.core.ApiError
import app.robin.core.ApiResult
import app.robin.core.ConsentView
import app.robin.core.PairProfile
import app.robin.core.PairLink
import app.robin.core.PairingFlow
import app.robin.core.Prompt
import app.robin.core.TransparencyScreenModel
import java.text.DateFormat
import java.util.Date
import java.util.Locale

/** Pairing, home (SOS, voice, prompts, stop/start), "what is on" and the read-only consent list. Views are built in code. */
class MainActivity : Activity(), QuickPanel.Host {
    private val app get() = robin
    private var panel: QuickPanel? = null
    private var paused = false
    private var tts: TextToSpeech? = null
    private val spoken = HashSet<String>()
    private var screen = Screen.WAITING
    private var bubbleSetup: BubbleSetupUi? = null
    private var bubbleSwitch: BubbleSwitchUi? = null

    private enum class Screen { WAITING, SETUP, HOME, WHATSON, CONSENT }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        if (!handleLink(intent)) route()
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        handleLink(intent)
    }

    /** `robin://pair?code=...` (link or QR) only opens the family setup screen with the code filled in; a person still taps Connect. */
    private fun handleLink(i: Intent?): Boolean {
        val code = PairLink.parse(i?.dataString) ?: return false
        i?.data = null
        showSetup(code, null)
        return true
    }

    override fun onResume() {
        super.onResume()
        panel?.onResume()
        bubbleSetup?.takeIf { screen == Screen.SETUP }?.render() // back from a system settings screen
        bubbleSwitch?.takeIf { screen == Screen.HOME }?.render()
        if (screen == Screen.HOME) refresh()
    }

    override fun onPause() {
        panel?.onPause()
        super.onPause()
    }

    override fun onStop() {
        tts?.stop()
        tts?.shutdown()
        tts = null
        super.onStop()
    }

    @Deprecated("Deprecated in Java")
    override fun onBackPressed() {
        if (screen == Screen.WHATSON || screen == Screen.CONSENT) showHome() else if (screen == Screen.SETUP) route() else super.onBackPressed()
    }

    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        panel?.onPermissionResult(requestCode)
        if (requestCode == BubbleSetupUi.REQ_MIC || requestCode == BubbleSetupUi.REQ_NOTIF) bubbleSetup?.render()
    }

    override fun onUnpaired() {
        app.pairing.onUnauthorized()
        showWaiting(getString(R.string.pairing_unpaired))
    }

    private fun route() {
        when (app.pairing.restore()) {
            is PairingFlow.State.Paired -> showHome()
            else -> showWaiting(null)
        }
    }

    // ------------------------------------------------------------------ small view helpers
    private fun dp(v: Int) = (v * resources.displayMetrics.density).toInt()

    private fun text(s: String, size: Float = 18f, bold: Boolean = false) = TextView(this).apply {
        text = s
        textSize = size
        setTextColor(getColor(R.color.robin_ink))
        if (bold) setTypeface(typeface, android.graphics.Typeface.BOLD)
        setPadding(0, dp(6), 0, dp(6))
    }

    private fun button(s: String, onClick: () -> Unit) = Button(this).apply {
        text = s
        textSize = 18f
        setOnClickListener { onClick() }
    }

    private fun column(): LinearLayout = LinearLayout(this).apply {
        orientation = LinearLayout.VERTICAL
        setPadding(dp(20), dp(24), dp(20), dp(24))
    }

    private fun show(col: LinearLayout) {
        setContentView(ScrollView(this).apply {
            setBackgroundColor(getColor(R.color.robin_bg))
            addView(col, ViewGroup.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT))
        })
    }

    private fun profile(): PairProfile? = app.profiles.profile()
    private fun lang() = profile()?.language ?: "en"

    /** Handles the errors every screen shares. Returns true when the error was handled (phone unpaired). */
    private fun unpairedBy(e: ApiError): Boolean {
        if (e == ApiError.Unauthorized) {
            onUnpaired()
            return true
        }
        return false
    }

    // ------------------------------------------------------------------ not set up yet (parent sees no text field)
    /** The brand name; a long press opens the family setup screen (the only place with a text field). */
    private fun title(): TextView = text(BuildConfig.BRAND_NAME, 32f, true).apply {
        contentDescription = BuildConfig.BRAND_NAME
        setOnLongClickListener { showSetup(null, null); true }
    }

    private fun showWaiting(notice: String?) {
        screen = Screen.WAITING
        panel = null
        val col = column()
        col.addView(title())
        col.addView(text(notice ?: getString(R.string.waiting_message), 28f))
        if (!app.serverConfigured) col.addView(text(getString(R.string.pairing_not_configured)))
        col.addView(text(getString(R.string.waiting_family_hint), 16f))
        col.addView(button(getString(R.string.home_call_112)) {
            startActivity(Intent(Intent.ACTION_DIAL, android.net.Uri.parse("tel:112")))
        }.apply { minHeight = dp(64) })
        show(col)
    }

    // ------------------------------------------------------------------ family setup (for the child)
    private fun showSetup(prefill: String?, notice: String?) {
        screen = Screen.SETUP
        panel = null
        bubbleSwitch = null
        val col = column()
        col.addView(text(getString(R.string.setup_title), 26f, true))
        col.addView(text(getString(R.string.setup_note)))
        val msg = text(notice ?: if (app.serverConfigured) "" else getString(R.string.pairing_not_configured))
        val input = EditText(this).apply {
            hint = getString(R.string.pairing_hint)
            textSize = 28f
            inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_FLAG_CAP_CHARACTERS or InputType.TYPE_TEXT_FLAG_NO_SUGGESTIONS
            filters = arrayOf(InputFilter.LengthFilter(14))
            if (prefill != null) setText(prefill)
        }
        col.addView(input)
        col.addView(msg)
        val go = button(getString(R.string.pairing_button)) {}
        go.setOnClickListener {
            go.isEnabled = false
            val raw = input.text.toString()
            app.io.execute {
                val s = app.pairing.submit(raw)
                runOnUiThread {
                    go.isEnabled = true
                    when (s) {
                        is PairingFlow.State.Paired -> showHome()
                        is PairingFlow.State.Failed -> msg.text = getString(
                            when (s.reason) {
                                PairingFlow.Failure.BAD_FORMAT -> R.string.pairing_err_format
                                PairingFlow.Failure.WRONG_OR_EXPIRED -> R.string.pairing_err_wrong
                                PairingFlow.Failure.RATE_LIMITED -> R.string.pairing_err_rate
                                PairingFlow.Failure.NETWORK -> R.string.pairing_err_network
                                else -> R.string.pairing_err_server
                            },
                        )
                        else -> Unit
                    }
                }
            }
        }
        col.addView(go)
        col.addView(button(getString(R.string.setup_add_widget)) { pinWidget(msg) })
        val bs = BubbleSetupUi(this)
        bubbleSetup = bs
        bs.render()
        col.addView(bs.view)
        col.addView(button(getString(R.string.back)) { route() })
        show(col)
    }

    /** Asks the launcher to add the widget (the launcher shows its own confirmation; not every launcher supports it). */
    private fun pinWidget(msg: TextView) {
        val m = getSystemService(AppWidgetManager::class.java)
        if (m != null && m.isRequestPinAppWidgetSupported) {
            m.requestPinAppWidget(ComponentName(this, RobinWidget::class.java), null, null)
        } else {
            msg.text = getString(R.string.setup_widget_manual)
        }
    }

    // ------------------------------------------------------------------ home
    private fun showHome() {
        screen = Screen.HOME
        val col = column()
        col.addView(title())
        val banner = text(getString(R.string.home_paused_banner), 18f, true).apply {
            setBackgroundColor(0xFFFFE08A.toInt())
            setPadding(dp(12), dp(10), dp(12), dp(10))
            visibility = if (paused) View.VISIBLE else View.GONE
        }
        col.addView(banner)
        val promptBox = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        col.addView(promptBox)
        val p = QuickPanel(this, this)
        panel = p
        col.addView(p.view)
        val sw = BubbleSwitchUi(this)
        bubbleSwitch = sw
        bubbleSetup = null
        sw.render()
        col.addView(sw.view)

        val stopStart = button(getString(if (paused) R.string.home_start_again else R.string.home_stop)) {}
        stopStart.setOnClickListener {
            stopStart.isEnabled = false
            app.io.execute {
                val r = if (paused) app.client.resume().map { false } else app.client.stop().map { true }
                runOnUiThread {
                    when (r) {
                        is ApiResult.Ok -> { paused = r.value; showHome() }
                        is ApiResult.Err -> if (!unpairedBy(r.error)) stopStart.isEnabled = true
                    }
                }
            }
        }
        col.addView(stopStart)
        col.addView(button(getString(R.string.home_what_is_on)) { showWhatsOn() })
        col.addView(button(getString(R.string.home_consent)) { showConsent() })
        show(col)
        renderPrompts(promptBox)
        refresh()
    }

    /** Heartbeat on open: learns paused/stopped and picks up prompts. No polling loop, no background work. */
    private fun refresh() {
        app.io.execute {
            val r = app.client.heartbeat(BuildConfig.VERSION_NAME, Build.VERSION.SDK_INT, System.currentTimeMillis(), false, emptyMap())
            runOnUiThread {
                when (r) {
                    is ApiResult.Ok -> {
                        val changed = paused != r.value.paused
                        paused = r.value.paused
                        app.prompts.replaceFromServer(r.value.prompts)
                        if (screen == Screen.HOME) { if (changed) showHome() else findPromptBox()?.let { renderPrompts(it) } }
                    }
                    is ApiResult.Err -> unpairedBy(r.error)
                }
            }
        }
    }

    private fun findPromptBox(): LinearLayout? {
        val root = (findViewById<ViewGroup>(android.R.id.content).getChildAt(0) as? ScrollView)?.getChildAt(0) as? LinearLayout
        return root?.getChildAt(2) as? LinearLayout
    }

    private fun renderPrompts(box: LinearLayout) {
        box.removeAllViews()
        val prompt = app.prompts.next(System.currentTimeMillis()) ?: return
        val l = lang()
        box.addView(text(prompt.textFor(l), 22f, true).apply { setBackgroundColor(0xFFFDE7E5.toInt()); setPadding(dp(12), dp(12), dp(12), dp(12)) })
        for (a in prompt.actions) {
            box.addView(button(a.label[l] ?: a.label["en"] ?: a.ack) { answer(prompt, a.ack) })
        }
        if (prompt.readAloud && spoken.add(prompt.promptId)) speak(prompt, l)
    }

    private fun answer(prompt: Prompt, ack: String) {
        app.prompts.markAnswered(prompt.promptId)
        findPromptBox()?.let { renderPrompts(it) }
        app.io.execute {
            val r = app.client.ack(ack, prompt.promptId)
            runOnUiThread { if (r is ApiResult.Err) unpairedBy(r.error) }
        }
    }

    private fun speak(prompt: Prompt, l: String) {
        val locale = if (l == "hi") Locale("hi", "IN") else Locale("en", "IN")
        val line = prompt.textFor(l)
        tts?.shutdown()
        tts = TextToSpeech(this) { status ->
            if (status == TextToSpeech.SUCCESS) {
                tts?.language = locale
                tts?.speak(line, TextToSpeech.QUEUE_FLUSH, null, prompt.promptId)
            }
        }
    }

    // ------------------------------------------------------------------ what is on
    private fun showWhatsOn() {
        screen = Screen.WHATSON
        panel = null
        val col = column()
        col.addView(text(getString(R.string.whatson_title), 26f, true))
        val body = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        col.addView(body)
        col.addView(button(getString(R.string.back)) { showHome() })
        show(col)
        app.io.execute {
            val r = app.client.transparency()
            runOnUiThread {
                when (r) {
                    is ApiResult.Ok -> renderWhatsOn(body, TransparencyScreenModel.from(r.value, profile()?.consentItems ?: emptyList()))
                    is ApiResult.Err -> if (!unpairedBy(r.error)) body.addView(text(getString(R.string.whatson_load_failed)))
                }
            }
        }
    }

    private fun renderWhatsOn(body: LinearLayout, m: TransparencyScreenModel) {
        when (m.banner) {
            TransparencyScreenModel.Banner.PAUSED -> body.addView(text(getString(R.string.whatson_paused), 20f, true))
            TransparencyScreenModel.Banner.LEARNING -> {
                body.addView(text(getString(R.string.whatson_learning, m.learningDaysLeft), 20f, true))
                m.learningMeaning?.let { body.addView(text(it)) }
            }
            else -> Unit
        }
        if (m.nothingOn) body.addView(text(getString(R.string.whatson_nothing_on), 20f, true))
        fun section(title: Int, lines: List<String>) {
            body.addView(text(getString(title), 20f, true))
            lines.forEach { body.addView(text("• $it")) }
        }
        section(R.string.whatson_allowed, m.allowedItems.map { itemLabel(it) })
        if (m.withdrawnItems.isNotEmpty()) section(R.string.whatson_withdrawn, m.withdrawnItems.map { itemLabel(it) })
        section(R.string.whatson_collected, m.collected)
        section(R.string.whatson_never, m.neverCollected)
        val fmt = DateFormat.getDateTimeInstance(DateFormat.SHORT, DateFormat.SHORT)
        section(
            R.string.whatson_told,
            if (m.toldFamily.isEmpty()) listOf(getString(R.string.whatson_told_none))
            else m.toldFamily.map { "${fmt.format(Date(it.tsMs))}: ${it.why}" },
        )
    }

    private fun itemLabel(item: String): String {
        val id = resources.getIdentifier("item_$item", "string", packageName)
        return getString(if (id != 0) id else R.string.item_other)
    }

    // ------------------------------------------------------------------ consent (read only, withdraw only)
    private fun showConsent() {
        screen = Screen.CONSENT
        panel = null
        val col = column()
        col.addView(text(getString(R.string.consent_title), 26f, true))
        col.addView(text(getString(R.string.consent_note)))
        val body = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        col.addView(body)
        col.addView(button(getString(R.string.back)) { showHome() })
        show(col)
        val view = ConsentView(app.client, profile()?.consentItems ?: emptyList())
        fun render(s: ConsentView.Screen) {
            body.removeAllViews()
            for (row in s.rows) {
                val line = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL }
                line.addView(text(itemLabel(row.item) + " (" + getString(if (row.allowed) R.string.consent_on else R.string.consent_off) + ")")
                    .apply { layoutParams = LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f) })
                if (row.canWithdraw) {
                    line.addView(button(getString(R.string.consent_withdraw)) {
                        app.io.execute {
                            val r = view.withdraw(row.item)
                            runOnUiThread {
                                when (r) {
                                    is ApiResult.Ok -> render(r.value)
                                    is ApiResult.Err -> unpairedBy(r.error)
                                }
                            }
                        }
                    })
                }
                body.addView(line)
            }
        }
        app.io.execute {
            val r = view.load()
            runOnUiThread {
                when (r) {
                    is ApiResult.Ok -> render(r.value)
                    is ApiResult.Err -> if (!unpairedBy(r.error)) body.addView(text(getString(R.string.whatson_load_failed)))
                }
            }
        }
    }
}
