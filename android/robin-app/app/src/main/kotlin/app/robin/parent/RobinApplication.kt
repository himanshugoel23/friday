package app.robin.parent

import android.app.Application
import android.content.Context
import android.content.SharedPreferences
import android.os.Build
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import app.robin.core.ApiClient
import app.robin.core.HttpRequest
import app.robin.core.HttpResponse
import app.robin.core.HttpTransport
import app.robin.core.PairProfile
import app.robin.core.PairingFlow
import app.robin.core.ProfileStore
import app.robin.core.PromptQueue
import app.robin.core.TokenStore
import java.io.ByteArrayOutputStream
import java.io.File
import java.io.IOException
import java.net.HttpURLConnection
import java.net.URL
import java.security.KeyStore
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec
import org.json.JSONArray
import org.json.JSONObject

/** Wires the pure modules (:core) to Android. No analytics, no crash reporter, no background work. */
class RobinApplication : Application() {
    lateinit var tokens: KeystoreTokenStore
    lateinit var profiles: PrefsProfileStore
    lateinit var client: ApiClient
    lateinit var pairing: PairingFlow
    val prompts = PromptQueue()

    /** One worker thread for all network calls, so calls never overlap and the main thread never blocks. */
    val io: ExecutorService = Executors.newSingleThreadExecutor()

    /** False when the build still has the placeholder server address (".invalid"): nothing can be sent. */
    val serverConfigured: Boolean get() = !BuildConfig.BASE_URL.contains(".invalid")

    override fun onCreate() {
        super.onCreate()
        tokens = KeystoreTokenStore(this)
        profiles = PrefsProfileStore(this)
        client = ApiClient(BuildConfig.BASE_URL, UrlConnectionTransport(), tokens)
        pairing = PairingFlow(client, tokens, profiles, BuildConfig.VERSION_NAME, Build.VERSION.SDK_INT)
        voiceFile(this).delete() // a recording is never left on the phone from an earlier run
    }

    companion object {
        fun voiceFile(ctx: Context) = File(ctx.cacheDir, "voice_note.m4a")
    }
}

val Context.robin: RobinApplication get() = applicationContext as RobinApplication

/** The device token, encrypted with an AES-GCM key that never leaves the Android Keystore. */
class KeystoreTokenStore(ctx: Context) : TokenStore {
    private val prefs: SharedPreferences = ctx.getSharedPreferences("robin_secure", Context.MODE_PRIVATE)

    private fun key(): SecretKey {
        val ks = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        (ks.getKey(ALIAS, null) as? SecretKey)?.let { return it }
        val gen = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore")
        gen.init(
            KeyGenParameterSpec.Builder(ALIAS, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .setKeySize(256)
                .build(),
        )
        return gen.generateKey()
    }

    override fun token(): String? {
        val stored = prefs.getString(PREF, null) ?: return null
        return try {
            val (iv, ct) = stored.split(":").map { Base64.decode(it, Base64.NO_WRAP) }
            val c = Cipher.getInstance("AES/GCM/NoPadding")
            c.init(Cipher.DECRYPT_MODE, key(), GCMParameterSpec(128, iv))
            String(c.doFinal(ct), Charsets.UTF_8)
        } catch (e: Exception) {
            clearToken() // key lost (restore, lock-screen reset): the phone simply has to pair again
            null
        }
    }

    override fun saveToken(token: String) {
        val c = Cipher.getInstance("AES/GCM/NoPadding")
        c.init(Cipher.ENCRYPT_MODE, key())
        val ct = c.doFinal(token.toByteArray(Charsets.UTF_8))
        prefs.edit().putString(PREF, Base64.encodeToString(c.iv, Base64.NO_WRAP) + ":" + Base64.encodeToString(ct, Base64.NO_WRAP)).apply()
    }

    override fun clearToken() {
        prefs.edit().remove(PREF).apply()
    }

    private companion object {
        const val ALIAS = "robin_device_token_key"
        const val PREF = "token"
    }
}

/** Who this phone is paired as. Not secret (the token is), but kept private to the app. */
class PrefsProfileStore(ctx: Context) : ProfileStore {
    private val prefs = ctx.getSharedPreferences("robin_profile", Context.MODE_PRIVATE)

    override fun profile(): PairProfile? {
        val s = prefs.getString("profile", null) ?: return null
        return try {
            val o = JSONObject(s)
            val items = o.getJSONArray("items")
            PairProfile(o.getString("parent_id"), o.getString("language"), o.getString("brand"), List(items.length()) { items.getString(it) })
        } catch (e: Exception) {
            null
        }
    }

    override fun saveProfile(profile: PairProfile) {
        val o = JSONObject().put("parent_id", profile.parentId).put("language", profile.language).put("brand", profile.brand)
            .put("items", JSONArray(profile.consentItems))
        prefs.edit().putString("profile", o.toString()).apply()
    }

    override fun clearProfile() {
        prefs.edit().remove("profile").apply()
    }
}

/** Plain HttpsURLConnection: no networking library. HTTPS only; no redirects; response capped at 1 MB. */
class UrlConnectionTransport : HttpTransport {
    override fun execute(request: HttpRequest): HttpResponse {
        if (!request.url.startsWith("https://")) throw IOException("https only")
        val conn = URL(request.url).openConnection() as HttpURLConnection
        try {
            conn.requestMethod = request.method
            conn.connectTimeout = 10_000
            conn.readTimeout = 30_000
            conn.instanceFollowRedirects = false
            conn.useCaches = false
            request.headers.forEach { (k, v) -> conn.setRequestProperty(k, v) }
            val body = request.body
            if (body != null) {
                conn.doOutput = true
                conn.setFixedLengthStreamingMode(body.size)
                conn.outputStream.use { it.write(body) }
            }
            val status = conn.responseCode
            val stream = if (status >= 400) conn.errorStream else conn.inputStream
            val out = ByteArrayOutputStream()
            stream?.use { s ->
                val buf = ByteArray(8192)
                while (true) {
                    val n = s.read(buf)
                    if (n < 0) break
                    out.write(buf, 0, n)
                    if (out.size() > 1_048_576) throw IOException("reply too large")
                }
            }
            return HttpResponse(status, out.toByteArray())
        } finally {
            conn.disconnect()
        }
    }
}
