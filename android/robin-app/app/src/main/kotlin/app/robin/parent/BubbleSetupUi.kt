package app.robin.parent

import android.Manifest
import android.app.Activity
import android.content.Intent
import android.graphics.Typeface
import android.net.Uri
import android.provider.Settings
import android.view.ViewGroup
import android.widget.Button
import android.widget.CheckBox
import android.widget.LinearLayout
import android.widget.Switch
import android.widget.TextView
import app.robin.core.BubblePolicy
import app.robin.core.GateAction
import app.robin.core.GateRow
import app.robin.core.GateStep
import app.robin.core.ParentSwitch
import app.robin.core.ParentSwitchModel

private fun Activity.dp(v: Int) = (v * resources.displayMetrics.density).toInt()

private fun Activity.label(s: String, size: Float, bold: Boolean = false) = TextView(this).apply {
    text = s
    textSize = size
    setTextColor(getColor(R.color.robin_ink))
    if (bold) setTypeface(typeface, Typeface.BOLD)
    setPadding(0, dp(6), 0, dp(6))
}

/**
 * The CHILD's part: shown on the family setup screen only (reached by the long press on the name or the setup link).
 * Lists every step with its state in words, opens the right system screen for each missing one, and turns the floating
 * mic on or off. All rules (what blocks, what is only advice) are in :core ([app.robin.core.OverlayGate], [BubblePolicy]).
 */
class BubbleSetupUi(private val a: Activity) {
    val view = LinearLayout(a).apply { orientation = LinearLayout.VERTICAL }
    private val prefs = BubblePrefs(a)

    fun render() {
        view.removeAllViews()
        val gate = BubbleEnv.gate(a)
        val settings = prefs.settings()
        view.addView(a.label(a.getString(R.string.bubble_setup_title), 26f, true))
        view.addView(a.label(a.getString(R.string.bubble_setup_note), 18f))
        view.addView(a.label(a.getString(R.string.bubble_setup_privacy), 16f))
        for (row in gate.rows) view.addView(stepView(row, row.step == gate.next))
        if (gate.overlayMissing) view.addView(a.label(a.getString(R.string.bubble_overlay_help), 18f, true))

        val auto = CheckBox(a).apply {
            text = a.getString(R.string.bubble_setup_autostart)
            textSize = 18f
            isChecked = settings.autoStartAfterReboot
        }
        view.addView(auto)
        val running = BubbleService.alive
        if (settings.childAllowed && settings.enabled) {
            view.addView(a.label(a.getString(R.string.bubble_setup_is_on), 20f, true))
        }
        val on = Button(a).apply {
            text = a.getString(R.string.bubble_setup_turn_on)
            textSize = 20f
            minHeight = a.dp(64)
            isEnabled = gate.canStart
            setOnClickListener {
                // Only the child, only with every required step done (the same rule :core tests).
                val next = BubblePolicy.childTurnOn(prefs.settings(), BubbleEnv.gate(a), auto.isChecked)
                prefs.save(next)
                if (next.enabled) BubbleService.start(a)
                render()
            }
        }
        view.addView(on)
        if (!gate.canStart) view.addView(a.label(a.getString(R.string.bubble_setup_finish_first), 16f))
        if (settings.childAllowed || running) {
            view.addView(Button(a).apply {
                text = a.getString(R.string.bubble_setup_turn_off)
                textSize = 18f
                minHeight = a.dp(56)
                setOnClickListener {
                    prefs.save(BubblePolicy.childTurnOff(prefs.settings()))
                    BubbleService.stop(a)
                    render()
                }
            })
        }
    }

    private fun stepView(row: GateRow, highlight: Boolean): LinearLayout {
        val box = LinearLayout(a).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(0, a.dp(8), 0, a.dp(8))
        }
        val state = when {
            row.done -> R.string.bubble_step_done
            row.required -> R.string.bubble_step_needed
            else -> R.string.bubble_step_optional
        }
        box.addView(a.label(a.getString(stepTitle(row.step)) + " - " + a.getString(state), 20f, highlight || !row.done && row.required))
        if (!row.done) box.addView(a.label(a.getString(stepWhy(row.step)), 16f))
        val btn = actionLabel(row.action)
        if (!row.done && btn != null) {
            box.addView(Button(a).apply {
                text = a.getString(btn)
                textSize = 18f
                minHeight = a.dp(56)
                setOnClickListener { act(row.action) }
            })
        }
        return box
    }

    private fun act(action: GateAction) {
        when (action) {
            GateAction.OPEN_OVERLAY_SETTINGS ->
                a.startActivity(Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION, Uri.parse("package:" + a.packageName)))
            GateAction.REQUEST_MICROPHONE -> a.requestPermissions(arrayOf(Manifest.permission.RECORD_AUDIO), REQ_MIC)
            GateAction.REQUEST_NOTIFICATIONS ->
                if (android.os.Build.VERSION.SDK_INT >= 33) a.requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), REQ_NOTIF)
            GateAction.OPEN_BATTERY_SETTINGS -> a.startActivity(Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS))
            GateAction.OPEN_PAIRING, GateAction.NONE -> Unit // pairing is the code box on this same screen
        }
    }

    private fun stepTitle(s: GateStep) = when (s) {
        GateStep.PAIRED -> R.string.bubble_step_paired
        GateStep.OVERLAY -> R.string.bubble_step_overlay
        GateStep.MICROPHONE -> R.string.bubble_step_microphone
        GateStep.NOTIFICATIONS -> R.string.bubble_step_notifications
        GateStep.VOICE_CONSENT -> R.string.bubble_step_voice_consent
        GateStep.BATTERY -> R.string.bubble_step_battery
    }

    private fun stepWhy(s: GateStep) = when (s) {
        GateStep.PAIRED -> R.string.bubble_why_paired
        GateStep.OVERLAY -> R.string.bubble_why_overlay
        GateStep.MICROPHONE -> R.string.bubble_why_microphone
        GateStep.NOTIFICATIONS -> R.string.bubble_why_notifications
        GateStep.VOICE_CONSENT -> R.string.bubble_why_voice_consent
        GateStep.BATTERY -> R.string.bubble_why_battery
    }

    private fun actionLabel(action: GateAction): Int? = when (action) {
        GateAction.OPEN_OVERLAY_SETTINGS -> R.string.bubble_btn_open_setting
        GateAction.REQUEST_MICROPHONE, GateAction.REQUEST_NOTIFICATIONS -> R.string.bubble_btn_allow
        GateAction.OPEN_BATTERY_SETTINGS -> R.string.bubble_btn_open_setting
        GateAction.OPEN_PAIRING, GateAction.NONE -> null
    }

    companion object {
        const val REQ_MIC = 42
        const val REQ_NOTIF = 43
    }
}

/**
 * The PARENT's part: one clear switch on the main screen. It can always switch the bubble off; it can switch it on only
 * after the child set it up and while every permission is in place. It also brings the service back when the phone's
 * battery manager has killed it and the parent opens Robin.
 */
class BubbleSwitchUi(private val a: Activity) {
    val view = LinearLayout(a).apply { orientation = LinearLayout.VERTICAL }
    private val prefs = BubblePrefs(a)

    fun render() {
        view.removeAllViews()
        val gate = BubbleEnv.gate(a)
        val settings = prefs.settings()
        if (BubblePolicy.mayRun(settings, gate) && !BubbleService.alive) BubbleService.start(a)
        val model = ParentSwitchModel.from(settings, gate, running = BubbleService.alive || (settings.enabled && BubblePolicy.mayRun(settings, gate)))

        val row = LinearLayout(a).apply { orientation = LinearLayout.HORIZONTAL; gravity = android.view.Gravity.CENTER_VERTICAL }
        val title = a.label(a.getString(R.string.bubble_switch_title) + ": " + a.getString(if (model.checked) R.string.bubble_switch_on else R.string.bubble_switch_off), 22f, true)
        row.addView(title, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
        val sw = Switch(a).apply {
            isChecked = model.checked
            isEnabled = model.enabled
            minimumHeight = a.dp(56)
            minimumWidth = a.dp(72)
            contentDescription = a.getString(R.string.bubble_switch_desc)
            setOnCheckedChangeListener { _, on ->
                val s = prefs.settings()
                val g = BubbleEnv.gate(a)
                if (on) {
                    val next = BubblePolicy.parentTurnOn(s, g)
                    prefs.save(next)
                    if (next.enabled) BubbleService.start(a)
                } else {
                    prefs.save(BubblePolicy.parentTurnOff(s))
                    BubbleService.stop(a)
                }
                render()
            }
        }
        row.addView(sw)
        view.addView(row)
        when (model.hint) {
            ParentSwitch.Hint.ASK_FAMILY -> view.addView(a.label(a.getString(R.string.bubble_hint_ask_family), 16f))
            ParentSwitch.Hint.FIX_PERMISSIONS -> view.addView(a.label(a.getString(R.string.bubble_hint_fix), 16f))
            ParentSwitch.Hint.NONE -> if (model.checked) view.addView(a.label(a.getString(R.string.bubble_hint_how_to), 16f))
        }
    }
}
