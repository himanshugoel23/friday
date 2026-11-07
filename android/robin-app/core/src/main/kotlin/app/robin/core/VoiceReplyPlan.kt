package app.robin.core

import java.net.URI

/** How to voice an answer: play the server's audio, else speak the text with the phone, else say nothing (text is still shown). */
sealed class SpeechPlan {
    data class PlayUrl(val url: String) : SpeechPlan()
    data class Speak(val text: String, val localeTag: String) : SpeechPlan()
    object Silent : SpeechPlan()

    companion object {
        /** The audio URL must be https on the same host as the server the phone is paired with (no third-party fetches). */
        fun audioUrlAllowed(url: String, baseUrl: String): Boolean = try {
            val u = URI(url)
            val b = URI(baseUrl)
            u.scheme == "https" && u.host != null && u.host.equals(b.host, ignoreCase = true) && u.userInfo == null
        } catch (e: Exception) {
            false
        }

        fun choose(answer: VoiceTurn.Answer, baseUrl: String, language: String): SpeechPlan {
            val url = answer.audioUrl
            if (url != null && audioUrlAllowed(url, baseUrl)) return PlayUrl(url)
            val text = answer.text
            if (text != null) return Speak(text, localeTag(language))
            return Silent
        }

        /** "hi" -> hi-IN; "hinglish" and "en" -> en-IN (Roman script reads better with the English voice); other codes -> xx-IN. */
        fun localeTag(language: String): String {
            val l = language.trim().lowercase()
            return when {
                l == "hi" -> "hi-IN"
                l == "hinglish" || l == "en" || l.isEmpty() -> "en-IN"
                Regex("^[a-z]{2,3}$").matches(l) -> "$l-IN"
                else -> "en-IN"
            }
        }
    }
}

/** The child's setup link: ``robin://pair?code=K7M2QX9A`` (also the QR payload). A bare 8-character code is accepted too. */
object PairLink {
    fun parse(raw: String?): String? {
        if (raw == null) return null
        val t = raw.trim()
        val code = if (t.startsWith("robin://", ignoreCase = true)) {
            val q = t.substringAfter('?', "")
            if (!t.substringBefore('?').substringAfter("://").trim('/').equals("pair", ignoreCase = true)) return null
            q.split('&').map { it.split('=', limit = 2) }.firstOrNull { it[0] == "code" && it.size == 2 }?.get(1) ?: return null
        } else t
        val norm = code.filter { it.isLetterOrDigit() }.uppercase()
        return norm.takeIf { ApiClient.CODE.matches(it) }
    }
}
