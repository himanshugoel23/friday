package app.robin.core

import java.io.IOException
import org.json.JSONArray
import org.json.JSONException
import org.json.JSONObject

class HttpRequest(val method: String, val url: String, val headers: Map<String, String>, val body: ByteArray?) {
    // Headers carry the bearer token: never print them.
    override fun toString() = "HttpRequest($method $url)"
}

class HttpResponse(val status: Int, val body: ByteArray)

/** The only place bytes leave the process. Implementations throw [IOException] for any network failure. */
fun interface HttpTransport {
    @Throws(IOException::class)
    fun execute(request: HttpRequest): HttpResponse
}

/** Where the bearer device token lives (Android: Keystore-backed). */
interface TokenStore {
    fun token(): String?
    fun saveToken(token: String)
    fun clearToken()
}

data class FieldError(val field: String, val rule: String)

/** Every way a call can fail. Messages name fields and rules, never values. */
sealed class ApiError {
    /** A bad, missing or revoked token (the server answers 404 so the route does not reveal itself). Re-pair. */
    object Unauthorized : ApiError()

    /** Pairing code wrong, used or expired (404 on /pair). */
    object PairingRejected : ApiError()

    /** 403 ``no_consent``: the family has not allowed this feature (for example voice messages). */
    object ConsentRequired : ApiError()

    /** 403 ``consent_given_by_family_admin``: the phone tried to grant consent. */
    object FamilyAdminOnly : ApiError()
    data class Forbidden(val code: String) : ApiError()
    data class Invalid(val fields: List<FieldError>, val code: String = "invalid") : ApiError()
    object RateLimited : ApiError()
    object TooLarge : ApiError()
    data class Unavailable(val status: Int) : ApiError()
    data class Network(val reason: String) : ApiError()
    data class Malformed(val key: String, val rule: String) : ApiError()

    /** Refused by the client before sending (same rules as the server schema), so no request was made. */
    data class ClientValidation(val field: String, val rule: String) : ApiError()
}

sealed class ApiResult<out T> {
    data class Ok<T>(val value: T) : ApiResult<T>()
    data class Err(val error: ApiError) : ApiResult<Nothing>()

    inline fun <R> map(f: (T) -> R): ApiResult<R> = when (this) {
        is Ok -> Ok(f(value))
        is Err -> this
    }
}

/**
 * Client for every device-API call (under /robin/device). Strict writer: bodies are built here from typed arguments and checked against
 * the server's schema rules first (extra fields cannot be expressed). Strict reader: required keys and types are enforced.
 * Blocking; call it from a worker thread.
 */
class ApiClient(
    baseUrl: String,
    private val transport: HttpTransport,
    private val tokens: TokenStore,
) {
    private val base = baseUrl.trimEnd('/') + "/robin/device"

    // ------------------------------------------------------------------ calls
    fun pair(code: String, appVersion: String, osSdk: Int): ApiResult<PairReply> {
        if (!CODE.matches(code)) return bad("code", "pattern")
        if (!APP_VERSION.matches(appVersion)) return bad("app_version", "pattern")
        if (osSdk !in 21..60) return bad("os_sdk", "range")
        val body = JSONObject().put("code", code).put("app_version", appVersion).put("os_sdk", osSdk)
        return call("POST", "/pair", body, auth = false, parse = PairReply::parse)
    }

    /** [roles] holds only the keys of the server's Roles schema; the thin build sends just ``post_notifications``. */
    fun heartbeat(appVersion: String, osSdk: Int, tsMs: Long, batteryLow: Boolean, roles: Map<String, Boolean>): ApiResult<HeartbeatReply> {
        if (!APP_VERSION.matches(appVersion)) return bad("app_version", "pattern")
        if (osSdk !in 21..60) return bad("os_sdk", "range")
        if (tsMs !in MIN_MS..MAX_MS) return bad("ts_ms", "range")
        val unknownRole = roles.keys.firstOrNull { it !in ROLE_KEYS }
        if (unknownRole != null) return bad("roles.$unknownRole", "extra_forbidden")
        val r = JSONObject()
        roles.toSortedMap().forEach { (k, v) -> r.put(k, v) }
        val body = JSONObject().put("app_version", appVersion).put("os_sdk", osSdk).put("ts_ms", tsMs)
            .put("battery_low", batteryLow).put("roles", r)
        return call("POST", "/heartbeat", body, parse = HeartbeatReply::parse)
    }

    /** Raw events; the server validates each one. Used by the later protection pack, not by the first ship. */
    fun signals(events: List<JSONObject>): ApiResult<SignalsReply> {
        if (events.isEmpty() || events.size > 100) return bad("events", "length")
        return call("POST", "/signals", JSONObject().put("events", JSONArray(events)), parse = SignalsReply::parse)
    }

    fun share(kind: String, value: String): ApiResult<ShareReply> {
        if (kind !in SHARE_KINDS) return bad("kind", "enum")
        if (value.isEmpty() || value.length > 2000) return bad("value", "length")
        return call("POST", "/share", JSONObject().put("kind", kind).put("value", value), parse = ShareReply::parse)
    }

    fun prompts(): ApiResult<PromptsReply> = call("GET", "/prompts", null, parse = PromptsReply::parse)

    /** [promptId] is required for ``this_was_fine``, ``dismissed`` and ``call_son_tapped``. */
    fun ack(kind: String, promptId: String? = null): ApiResult<MessageReply> {
        if (kind !in ACK_KINDS) return bad("kind", "enum")
        if (promptId != null && !PROMPT_ID.matches(promptId)) return bad("prompt_id", "pattern")
        if (promptId == null && kind in ACK_NEEDS_PROMPT) return bad("prompt_id", "required")
        val body = JSONObject().put("kind", kind)
        if (promptId != null) body.put("prompt_id", promptId)
        return call("POST", "/ack", body, parse = MessageReply::parse)
    }

    /** SOS. Works while stopped or paused. The reply line says "tap Call 112"; the app must show that button itself. */
    fun sos(lat: Double? = null, lon: Double? = null): ApiResult<MessageReply> {
        if ((lat == null) != (lon == null)) return bad("lat/lon", "both_or_neither")
        val body = JSONObject()
        if (lat != null && lon != null) {
            if (lat !in -90.0..90.0) return bad("lat", "range")
            if (lon !in -180.0..180.0) return bad("lon", "range")
            body.put("lat", lat).put("lon", lon)
        }
        return call("POST", "/sos", body, parse = MessageReply::parse)
    }

    /** Press-to-talk upload: raw audio, an audio Content-Type, ``X-Duration-S`` 1-60, at most 1 MB. */
    fun voice(audio: ByteArray, mime: String, durationS: Int): ApiResult<VoiceReply> {
        if (mime !in VOICE_MIMES) return bad("content-type", "enum")
        if (durationS !in 1..MAX_VOICE_SECONDS) return bad("x-duration-s", "range")
        if (audio.isEmpty()) return bad("body", "empty")
        if (audio.size > MAX_VOICE_BYTES) return bad("body", "too_large")
        val headers = mapOf("Content-Type" to mime, "X-Duration-S" to durationS.toString())
        return send("POST", "/voice", audio, headers, auth = true, parse = VoiceReply::parse)
    }

    fun consent(): ApiResult<ConsentReply> = call("GET", "/consent", null, parse = ConsentReply::parse)

    /** Withdraw only: every value is ``false`` by construction. There is no way to ask the server for a grant. */
    fun withdrawConsent(items: List<String>): ApiResult<ConsentReply> {
        if (items.isEmpty() || items.size > 32) return bad("items", "length")
        val m = JSONObject()
        items.forEach { m.put(it, false) }
        return call("PUT", "/consent", JSONObject().put("items", m), parse = ConsentReply::parse)
    }

    fun pause(minutes: Int): ApiResult<PauseReply> {
        if (minutes !in 5..1440) return bad("minutes", "range")
        return call("POST", "/pause", JSONObject().put("minutes", minutes), parse = PauseReply::parse)
    }

    fun stop(): ApiResult<StopReply> = call("POST", "/stop", null, parse = StopReply::parse)
    fun resume(): ApiResult<ResumeReply> = call("POST", "/resume", null, parse = ResumeReply::parse)
    fun transparency(): ApiResult<TransparencyReply> = call("GET", "/transparency", null, parse = TransparencyReply::parse)
    fun erase(): ApiResult<EraseReply> = call("DELETE", "/erase", null, parse = EraseReply::parse)

    // ------------------------------------------------------------------ plumbing
    private fun <T> bad(field: String, rule: String): ApiResult<T> = ApiResult.Err(ApiError.ClientValidation(field, rule))

    private fun <T> call(
        method: String, path: String, body: JSONObject?, auth: Boolean = true, parse: (JSONObject) -> T,
    ): ApiResult<T> {
        val headers = if (body != null) mapOf("Content-Type" to "application/json") else emptyMap()
        return send(method, path, body?.toString()?.toByteArray(Charsets.UTF_8), headers, auth, parse)
    }

    private fun <T> send(
        method: String, path: String, body: ByteArray?, extra: Map<String, String>, auth: Boolean, parse: (JSONObject) -> T,
    ): ApiResult<T> {
        val headers = LinkedHashMap<String, String>()
        headers["Accept"] = "application/json"
        headers.putAll(extra)
        if (auth) {
            val t = tokens.token() ?: return ApiResult.Err(ApiError.Unauthorized)
            headers["Authorization"] = "Bearer $t"
        }
        val resp = try {
            transport.execute(HttpRequest(method, base + path, headers, body))
        } catch (e: IOException) {
            return ApiResult.Err(ApiError.Network(e.javaClass.simpleName)) // class name only, never the message (may hold a URL)
        }
        val text = String(resp.body, Charsets.UTF_8)
        if (resp.status in 200..299) {
            return try {
                ApiResult.Ok(parse(JSONObject(text)))
            } catch (e: MalformedReply) {
                ApiResult.Err(ApiError.Malformed(e.key, e.rule))
            } catch (e: JSONException) {
                ApiResult.Err(ApiError.Malformed("body", "not_json"))
            }
        }
        return ApiResult.Err(errorFor(resp.status, path, text))
    }

    private fun errorFor(status: Int, path: String, text: String): ApiError {
        val j = try { JSONObject(text) } catch (e: JSONException) { null }
        val code = j?.optString("error", "").orEmpty()
        return when (status) {
            // 404 with {"error": "unknown_prompt"} is an ack for a prompt that is gone; any other 404 is a bad token.
            404 -> when {
                code == "unknown_prompt" -> ApiError.Invalid(emptyList(), code)
                path == "/pair" -> ApiError.PairingRejected
                else -> ApiError.Unauthorized
            }
            403 -> when (code) {
                "no_consent" -> ApiError.ConsentRequired
                "consent_given_by_family_admin" -> ApiError.FamilyAdminOnly
                else -> ApiError.Forbidden(code)
            }
            422 -> {
                val f = j?.optJSONArray("fields")
                val fields = if (f == null) emptyList() else List(f.length()) {
                    val e = f.optJSONObject(it)
                    FieldError(e?.optString("field", "").orEmpty(), e?.optString("rule", "").orEmpty())
                }
                ApiError.Invalid(fields, code.ifEmpty { "invalid" })
            }
            413 -> ApiError.TooLarge
            429 -> ApiError.RateLimited
            else -> ApiError.Unavailable(status)
        }
    }

    companion object {
        const val MAX_VOICE_BYTES = 1_048_576
        const val MAX_VOICE_SECONDS = 60
        const val MIN_MS = 1_600_000_000_000L
        const val MAX_MS = 4_102_444_800_000L
        val CODE = Regex("^[A-Z2-9]{8}$")
        val APP_VERSION = Regex("^[0-9][0-9A-Za-z._+-]{0,23}$")
        val PROMPT_ID = Regex("^[A-Za-z0-9_-]{6,64}$")
        val ROLE_KEYS = setOf(
            "call_screening", "phone_state", "notification_access", "location", "package_visibility", "usage_access",
            "post_notifications",
        )
        val SHARE_KINDS = setOf("text", "url", "phone", "app_name", "file_name", "screenshot_ref")
        val ACK_KINDS = setOf("this_was_fine", "i_am_ok", "sos", "dismissed", "call_son_tapped")
        val ACK_NEEDS_PROMPT = setOf("this_was_fine", "dismissed", "call_son_tapped")
        val VOICE_MIMES = setOf("audio/ogg", "audio/mp4", "audio/aac", "audio/amr", "audio/wav", "audio/webm", "audio/mpeg")
    }
}
