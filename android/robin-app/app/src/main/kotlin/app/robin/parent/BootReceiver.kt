package app.robin.parent

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import app.robin.core.BubblePolicy

/**
 * After a reboot the floating mic starts again ONLY if the child allowed it, chose "start after restart", it was left on
 * (the parent had not switched it off) and every permission is still in place. The service checks the same rule again.
 */
class BootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action != Intent.ACTION_BOOT_COMPLETED) return
        if (BubblePolicy.startAtBoot(BubblePrefs(context).settings(), BubbleEnv.gate(context))) {
            try { BubbleService.start(context) } catch (_: Exception) { /* not allowed right now: stays off until the screen is opened */ }
        }
    }
}
