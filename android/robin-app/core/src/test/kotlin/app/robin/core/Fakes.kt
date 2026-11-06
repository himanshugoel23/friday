package app.robin.core

import java.io.File
import java.io.IOException
import org.json.JSONObject

class FakeTransport : HttpTransport {
    val sent = mutableListOf<HttpRequest>()
    private val queue = ArrayDeque<() -> HttpResponse>()

    fun reply(status: Int, body: String) = apply { queue.addLast { HttpResponse(status, body.toByteArray()) } }
    fun fail() = apply { queue.addLast { throw IOException("boom https://secret.example/x") } }

    override fun execute(request: HttpRequest): HttpResponse {
        sent += request
        return (queue.removeFirstOrNull() ?: error("no reply queued"))()
    }

    val last: HttpRequest get() = sent.last()
    fun lastBody(): JSONObject = JSONObject(String(last.body!!))
}

class MemTokens(var value: String? = null) : TokenStore {
    override fun token() = value
    override fun saveToken(token: String) { value = token }
    override fun clearToken() { value = null }
}

class MemProfiles(var value: PairProfile? = null) : ProfileStore {
    override fun profile() = value
    override fun saveProfile(profile: PairProfile) { value = profile }
    override fun clearProfile() { value = null }
}

object Fixtures {
    /** The shared contract fixtures (tests/robindevice/contract), also checked against the real server in Python. */
    val dir: File = File(System.getProperty("contract.dir") ?: error("contract.dir not set"))

    class Fx(val name: String, val method: String, val path: String, val auth: Boolean, val headers: Map<String, String>,
             val requestJson: JSONObject?, val requestRaw: String?, val status: Int, val response: JSONObject,
             val setup: List<String>) {
        fun responseText(): String = response.toString()
    }

    fun all(): List<Fx> {
        val files = dir.listFiles { f -> f.name.endsWith(".json") }?.sortedBy { it.name } ?: emptyList()
        check(files.size >= 20) { "expected the shared fixtures in $dir" }
        return files.map { f ->
            val d = JSONObject(f.readText())
            val req = d.getJSONObject("request")
            val h = req.optJSONObject("headers")
            val setup = d.getJSONArray("setup")
            Fx(
                d.getString("name"), req.getString("method"), req.getString("path"), req.getBoolean("auth"),
                if (h == null) emptyMap() else h.keys().asSequence().associateWith { h.getString(it) },
                req.optJSONObject("json"), req.optString("body_ascii", "").ifEmpty { null },
                d.getJSONObject("response").getInt("status"), d.getJSONObject("response").getJSONObject("json"),
                List(setup.length()) { setup.getString(it) },
            )
        }
    }

    fun byName(name: String): Fx = all().first { it.name == name }
}

const val TOKEN = "rbn_EXAMPLE_not_a_real_token_0123456789abcdefghijklmnop"
const val BASE = "https://robin-server.invalid"
