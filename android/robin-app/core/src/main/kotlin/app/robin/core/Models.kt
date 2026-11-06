package app.robin.core

import org.json.JSONArray
import org.json.JSONObject

/** Thrown by the strict reader when a server reply does not have the documented shape. Names the key, never a value. */
class MalformedReply(val key: String, val rule: String) : Exception("malformed reply: $key ($rule)")

/** Strict readers: a missing or wrong-typed required key is an error (never a silent default). */
internal object J {
    private fun raw(o: JSONObject, k: String): Any {
        if (!o.has(k) || o.isNull(k)) throw MalformedReply(k, "missing")
        return o.get(k)
    }

    fun str(o: JSONObject, k: String): String = raw(o, k) as? String ?: throw MalformedReply(k, "not_string")
    fun strOrNull(o: JSONObject, k: String): String? =
        if (!o.has(k) || o.isNull(k)) null else (o.get(k) as? String ?: throw MalformedReply(k, "not_string"))

    fun bool(o: JSONObject, k: String): Boolean = raw(o, k) as? Boolean ?: throw MalformedReply(k, "not_bool")
    fun int(o: JSONObject, k: String): Int {
        val v = raw(o, k)
        if (v is Int) return v
        if (v is Long && v in Int.MIN_VALUE..Int.MAX_VALUE) return v.toInt()
        throw MalformedReply(k, "not_int")
    }

    fun long(o: JSONObject, k: String): Long {
        val v = raw(o, k)
        return when (v) {
            is Int -> v.toLong()
            is Long -> v
            else -> throw MalformedReply(k, "not_int")
        }
    }

    fun obj(o: JSONObject, k: String): JSONObject = raw(o, k) as? JSONObject ?: throw MalformedReply(k, "not_object")
    fun arr(o: JSONObject, k: String): JSONArray = raw(o, k) as? JSONArray ?: throw MalformedReply(k, "not_array")

    fun strings(o: JSONObject, k: String): List<String> {
        val a = arr(o, k)
        return List(a.length()) { a.get(it) as? String ?: throw MalformedReply("$k[$it]", "not_string") }
    }

    fun boolMap(o: JSONObject, k: String): Map<String, Boolean> {
        val m = obj(o, k)
        val out = LinkedHashMap<String, Boolean>()
        for (name in m.keys().asSequence().toList().sorted()) {
            out[name] = m.get(name) as? Boolean ?: throw MalformedReply("$k.$name", "not_bool")
        }
        return out
    }

    fun intMap(o: JSONObject, k: String): Map<String, Int> {
        val m = obj(o, k)
        val out = LinkedHashMap<String, Int>()
        for (name in m.keys().asSequence().toList().sorted()) {
            val v = m.get(name)
            out[name] = (v as? Int) ?: (v as? Long)?.toInt() ?: throw MalformedReply("$k.$name", "not_int")
        }
        return out
    }

    fun langMap(o: JSONObject, k: String): Map<String, String> {
        val m = obj(o, k)
        val out = LinkedHashMap<String, String>()
        for (name in m.keys().asSequence().toList().sorted()) {
            out[name] = m.get(name) as? String ?: throw MalformedReply("$k.$name", "not_string")
        }
        return out
    }
}

data class PairReply(
    val deviceToken: String,
    val parentId: String,
    /** "en", "hinglish" or "hi" (the parent's language, chosen by the family). */
    val language: String,
    val brand: String,
    val consentItems: List<String>,
    val serverTimeMs: Long,
    val maxBatch: Int,
    val maxBodyBytes: Int,
) {
    // The token must never reach a log through toString().
    override fun toString() = "PairReply(parentId=$parentId, language=$language, brand=$brand, token=<redacted>)"

    companion object {
        fun parse(o: JSONObject): PairReply {
            val limits = J.obj(o, "limits")
            return PairReply(
                deviceToken = J.str(o, "device_token"),
                parentId = J.str(o, "parent_id"),
                language = J.str(o, "language"),
                brand = J.str(o, "brand"),
                consentItems = J.strings(o, "consent_items"),
                serverTimeMs = J.long(o, "server_time_ms"),
                maxBatch = J.int(limits, "max_batch"),
                maxBodyBytes = J.int(limits, "max_body_bytes"),
            )
        }
    }
}

data class PromptAction(val ack: String, val label: Map<String, String>)

data class Prompt(
    val promptId: String,
    val scenario: String,
    val tier: String,
    val fullScreen: Boolean,
    val readAloud: Boolean,
    val notBeforeMs: Long,
    val expiresMs: Long,
    val language: String,
    val text: Map<String, String>,
    val actions: List<PromptAction>,
    val status: String,
) {
    /** The line for the parent: the parent's language, else English. Wording is PENDING founder approval. */
    fun textFor(lang: String = language): String = text[lang] ?: text["en"] ?: text.values.firstOrNull() ?: ""

    companion object {
        fun parse(o: JSONObject): Prompt {
            val acts = J.arr(o, "actions")
            return Prompt(
                promptId = J.str(o, "prompt_id"),
                scenario = J.str(o, "scenario"),
                tier = J.str(o, "tier"),
                fullScreen = J.bool(o, "full_screen"),
                readAloud = J.bool(o, "read_aloud"),
                notBeforeMs = J.long(o, "not_before_ms"),
                expiresMs = J.long(o, "expires_ms"),
                language = J.str(o, "language"),
                text = J.langMap(o, "text"),
                actions = List(acts.length()) {
                    val a = acts.get(it) as? JSONObject ?: throw MalformedReply("actions[$it]", "not_object")
                    PromptAction(J.str(a, "ack"), J.langMap(a, "label"))
                },
                status = J.str(o, "status"),
            )
        }

        fun parseList(o: JSONObject, key: String): List<Prompt> {
            val a = J.arr(o, key)
            return List(a.length()) { parse(a.get(it) as? JSONObject ?: throw MalformedReply("$key[$it]", "not_object")) }
        }
    }
}

data class HeartbeatReply(
    val serverTimeMs: Long,
    val paused: Boolean,
    val consent: Map<String, Boolean>,
    val prompts: List<Prompt>,
) {
    companion object {
        fun parse(o: JSONObject) = HeartbeatReply(
            J.long(o, "server_time_ms"), J.bool(o, "paused"), J.boolMap(o, "consent"), Prompt.parseList(o, "prompts"),
        )
    }
}

data class InvalidDetail(val index: Int, val reason: String)

data class SignalsReply(
    val accepted: Int,
    val duplicates: Int,
    val droppedNoConsent: Int,
    val droppedPaused: Int,
    val stale: Int,
    val invalid: Int,
    val invalidDetail: List<InvalidDetail>,
    val prompts: List<Prompt>,
) {
    companion object {
        fun parse(o: JSONObject): SignalsReply {
            val d = J.arr(o, "invalid_detail")
            return SignalsReply(
                J.int(o, "accepted"), J.int(o, "duplicates"), J.int(o, "dropped_no_consent"),
                J.int(o, "dropped_paused"), J.int(o, "stale"), J.int(o, "invalid"),
                List(d.length()) {
                    val e = d.get(it) as? JSONObject ?: throw MalformedReply("invalid_detail[$it]", "not_object")
                    InvalidDetail(J.int(e, "index"), J.str(e, "reason"))
                },
                Prompt.parseList(o, "prompts"),
            )
        }
    }
}

data class PromptsReply(val prompts: List<Prompt>) {
    companion object {
        fun parse(o: JSONObject) = PromptsReply(Prompt.parseList(o, "prompts"))
    }
}

/** Reply to /ack and /sos: ``ok`` plus an optional line to show or read aloud (PENDING wording). */
data class MessageReply(val ok: Boolean, val message: String?) {
    companion object {
        fun parse(o: JSONObject) = MessageReply(J.bool(o, "ok"), J.strOrNull(o, "message"))
    }
}

data class VoiceReply(val accepted: Boolean, val replyText: String?) {
    companion object {
        fun parse(o: JSONObject) = VoiceReply(J.bool(o, "accepted"), J.strOrNull(o, "reply_text"))
    }
}

data class ShareReply(
    val kind: String,
    val verdict: String,
    val headline: String,
    val reason: String,
    val nextStep: String,
    val nextSteps: List<String>,
    val alertChild: Boolean,
    val childTold: Boolean,
    val language: String,
) {
    companion object {
        fun parse(o: JSONObject) = ShareReply(
            J.str(o, "kind"), J.str(o, "verdict"), J.str(o, "headline"), J.str(o, "reason"), J.str(o, "next_step"),
            J.strings(o, "next_steps"), J.bool(o, "alert_child"), J.bool(o, "child_told"), J.str(o, "language"),
        )
    }
}

data class ConsentReply(val basis: String, val items: Map<String, Boolean>) {
    companion object {
        fun parse(o: JSONObject) = ConsentReply(J.str(o, "consent_basis"), J.boolMap(o, "items"))
    }
}

data class PauseReply(val paused: Boolean, val untilMs: Long) {
    companion object {
        fun parse(o: JSONObject) = PauseReply(J.bool(o, "paused"), J.long(o, "until_ms"))
    }
}

data class StopReply(val stopped: Boolean, val paused: Boolean) {
    companion object {
        fun parse(o: JSONObject) = StopReply(J.bool(o, "stopped"), J.bool(o, "paused"))
    }
}

data class ResumeReply(val paused: Boolean) {
    companion object {
        fun parse(o: JSONObject) = ResumeReply(J.bool(o, "paused"))
    }
}

data class EraseReply(val erased: Boolean, val eventsDeleted: Int) {
    companion object {
        fun parse(o: JSONObject) = EraseReply(J.bool(o, "erased"), J.int(o, "events_deleted"))
    }
}

data class ToldChild(val tsMs: Long, val tier: String, val scenario: String, val why: String)

data class LearningMode(val active: Boolean, val daysLeft: Int, val meaning: String)

data class TransparencyReply(
    val collected: List<String>,
    val neverCollected: List<String>,
    val counters: Map<String, Int>,
    val toldChild: List<ToldChild>,
    val paused: Boolean,
    val consent: Map<String, Boolean>,
    val learningMode: LearningMode,
    val status: String,
) {
    companion object {
        fun parse(o: JSONObject): TransparencyReply {
            val told = J.arr(o, "told_child")
            val lm = J.obj(o, "learning_mode")
            return TransparencyReply(
                J.strings(o, "collected"), J.strings(o, "never_collected"), J.intMap(o, "counters"),
                List(told.length()) {
                    val e = told.get(it) as? JSONObject ?: throw MalformedReply("told_child[$it]", "not_object")
                    ToldChild(J.long(e, "ts_ms"), J.str(e, "tier"), J.str(e, "scenario"), J.str(e, "why"))
                },
                J.bool(o, "paused"), J.boolMap(o, "consent"),
                LearningMode(J.bool(lm, "active"), J.int(lm, "days_left"), J.str(lm, "meaning")),
                J.str(o, "status"),
            )
        }
    }
}
