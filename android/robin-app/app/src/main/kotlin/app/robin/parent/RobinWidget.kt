package app.robin.parent

import android.app.PendingIntent
import android.appwidget.AppWidgetManager
import android.appwidget.AppWidgetProvider
import android.content.Context
import android.content.Intent
import android.widget.RemoteViews

/** Home-screen widget: a big SOS button and a big voice-note button. Each opens [QuickActivity] (hold happens there). */
class RobinWidget : AppWidgetProvider() {
    override fun onUpdate(context: Context, manager: AppWidgetManager, ids: IntArray) {
        for (id in ids) {
            val v = RemoteViews(context.packageName, R.layout.widget)
            v.setOnClickPendingIntent(R.id.widget_sos, open(context, "sos", 1))
            v.setOnClickPendingIntent(R.id.widget_voice, open(context, "voice", 2))
            manager.updateAppWidget(id, v)
        }
    }

    private fun open(context: Context, focus: String, code: Int): PendingIntent {
        val i = Intent(context, QuickActivity::class.java)
            .putExtra(QuickActivity.EXTRA_FOCUS, focus)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP)
        return PendingIntent.getActivity(context, code, i, PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
    }
}
