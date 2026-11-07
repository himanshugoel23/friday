package app.robin.parent

import android.app.Activity
import android.content.Intent
import android.os.Bundle
import android.view.WindowManager
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView

/** Opened by the widget buttons. Shows only SOS, voice note and Call 112 (also over the lock screen). */
class QuickActivity : Activity(), QuickPanel.Host {
    private lateinit var panel: QuickPanel

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        panel = QuickPanel(this, this)
        val col = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(32, 48, 32, 32)
        }
        if (!robin.serverConfigured || robin.tokens.token() == null) {
            // Not paired yet: SOS cannot reach the family. Say so and send the person to the app.
            col.addView(TextView(this).apply { text = getString(R.string.pairing_unpaired); textSize = 20f })
        }
        col.addView(panel.view)
        setContentView(ScrollView(this).apply { addView(col) })
        panel.focus(intent.getStringExtra(EXTRA_FOCUS))
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        panel.focus(intent.getStringExtra(EXTRA_FOCUS))
    }

    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        panel.onPermissionResult(requestCode)
    }

    override fun onResume() {
        super.onResume()
        panel.onResume()
    }

    override fun onPause() {
        panel.onPause()
        super.onPause()
    }

    override fun onUnpaired() {
        robin.pairing.onUnauthorized()
        startActivity(Intent(this, MainActivity::class.java))
        finish()
    }

    companion object {
        const val EXTRA_FOCUS = "focus"
    }
}
