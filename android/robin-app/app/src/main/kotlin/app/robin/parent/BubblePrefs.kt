package app.robin.parent

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.os.Build
import android.os.PowerManager
import android.provider.Settings
import app.robin.core.BubbleSettings
import app.robin.core.Edge
import app.robin.core.GateInput
import app.robin.core.GateResult
import app.robin.core.OverlayGate
import app.robin.core.Placement

/** What the floating mic remembers: the child's choices and where the bubble rests. Private to the app; no text, no audio, no identifiers. */
class BubblePrefs(ctx: Context) {
    private val p = ctx.getSharedPreferences("robin_bubble", Context.MODE_PRIVATE)

    fun settings() = BubbleSettings(
        childAllowed = p.getBoolean("child_allowed", false),
        enabled = p.getBoolean("enabled", false),
        autoStartAfterReboot = p.getBoolean("auto_start", false),
    )

    fun save(s: BubbleSettings) {
        p.edit().putBoolean("child_allowed", s.childAllowed).putBoolean("enabled", s.enabled).putBoolean("auto_start", s.autoStartAfterReboot).apply()
    }

    fun placement(): Placement? {
        val edge = p.getString("edge", null) ?: return null
        return Placement(if (edge == "left") Edge.LEFT else Edge.RIGHT, p.getFloat("y_fraction", Float.NaN))
    }

    fun savePlacement(pl: Placement) {
        p.edit().putString("edge", if (pl.edge == Edge.LEFT) "left" else "right").putFloat("y_fraction", pl.yFraction).apply()
    }
}

/** Reads the real permission state and runs the pure gate (:core) over it. */
object BubbleEnv {
    fun canDrawOverlays(ctx: Context) = Settings.canDrawOverlays(ctx)

    fun micGranted(ctx: Context) = ctx.checkSelfPermission(Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED

    fun notificationsGranted(ctx: Context) =
        Build.VERSION.SDK_INT < 33 || ctx.checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED

    fun batteryUnrestricted(ctx: Context): Boolean? = try {
        ctx.getSystemService(PowerManager::class.java)?.isIgnoringBatteryOptimizations(ctx.packageName)
    } catch (e: Exception) {
        null
    }

    fun gate(ctx: Context): GateResult {
        val app = ctx.robin
        val paired = app.serverConfigured && app.tokens.token() != null
        val voice = app.profiles.profile()?.consentItems?.contains("voice_messages")
        return OverlayGate.evaluate(
            GateInput(
                sdk = Build.VERSION.SDK_INT,
                serverConfigured = app.serverConfigured,
                paired = paired,
                overlayGranted = canDrawOverlays(ctx),
                micGranted = micGranted(ctx),
                notificationsGranted = notificationsGranted(ctx),
                voiceConsent = voice,
                batteryUnrestricted = batteryUnrestricted(ctx),
            ),
        )
    }
}
