package app.robin.parent

import android.content.Context
import android.media.MediaRecorder
import android.os.Build
import java.io.File

/**
 * Records one voice note while the button is held. AAC in an MP4 container (upload type audio/mp4), mono, 16 kHz,
 * 32 kbit/s, so 60 seconds is about 240 KB (the server limit is 1 MB). The microphone is open only between [start]
 * and [stop]/[cancel]. The file is deleted after a successful upload (and at every app start).
 */
class VoiceRecorder(private val ctx: Context) {
    private var rec: MediaRecorder? = null
    val file: File get() = RobinApplication.voiceFile(ctx)

    fun start(): Boolean {
        cancel()
        return try {
            val r = if (Build.VERSION.SDK_INT >= 31) MediaRecorder(ctx) else @Suppress("DEPRECATION") MediaRecorder()
            r.setAudioSource(MediaRecorder.AudioSource.MIC)
            r.setOutputFormat(MediaRecorder.OutputFormat.MPEG_4)
            r.setAudioEncoder(MediaRecorder.AudioEncoder.AAC)
            r.setAudioChannels(1)
            r.setAudioSamplingRate(16_000)
            r.setAudioEncodingBitRate(32_000)
            r.setMaxFileSize(1_000_000)
            r.setOutputFile(file.absolutePath)
            r.prepare()
            r.start()
            rec = r
            true
        } catch (e: Exception) {
            cancel()
            false
        }
    }

    /** Stops and returns the recorded bytes, or null if nothing usable was recorded. */
    fun stop(): ByteArray? {
        val r = rec ?: return null
        rec = null
        return try {
            r.stop()
            r.release()
            file.readBytes().takeIf { it.isNotEmpty() }
        } catch (e: Exception) { // stop() throws if the recording was too short
            try { r.release() } catch (_: Exception) {}
            file.delete()
            null
        }
    }

    /** Throws the recording away and releases the microphone. Safe to call at any time. */
    fun cancel() {
        rec?.let {
            try { it.stop() } catch (_: Exception) {}
            try { it.release() } catch (_: Exception) {}
        }
        rec = null
        file.delete()
    }

    fun deleteFile() {
        file.delete()
    }
}
