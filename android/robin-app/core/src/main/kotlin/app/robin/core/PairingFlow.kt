package app.robin.core

/** What the phone remembers about the pairing (the token itself lives in [TokenStore]). */
data class PairProfile(
    val parentId: String,
    /** "en", "hinglish" or "hi". */
    val language: String,
    val brand: String,
    /** Consent item names in the server's order; used to order the read-only consent screen. */
    val consentItems: List<String>,
)

interface ProfileStore {
    fun profile(): PairProfile?
    fun saveProfile(profile: PairProfile)
    fun clearProfile()
}

/**
 * Pair with the 8-character code the child shows (15 minutes, single use). The phone never creates a code and never
 * grants consent: consent is the family admin's (admin_on_behalf).
 */
class PairingFlow(
    private val client: ApiClient,
    private val tokens: TokenStore,
    private val profiles: ProfileStore,
    private val appVersion: String,
    private val osSdk: Int,
) {
    enum class Failure { BAD_FORMAT, WRONG_OR_EXPIRED, RATE_LIMITED, NETWORK, SERVER, MALFORMED }

    sealed class State {
        object NeedsCode : State()
        data class Paired(val profile: PairProfile) : State()
        data class Failed(val reason: Failure) : State()
    }

    /** On app start: paired only when both the token and the profile exist. */
    fun restore(): State {
        val p = profiles.profile()
        return if (tokens.token() != null && p != null) State.Paired(p) else State.NeedsCode
    }

    /** People type codes with spaces or dashes and in lower case ("k7m2 qx9a"); accept all of that. */
    fun normalise(raw: String): String = raw.filter { it.isLetterOrDigit() }.uppercase()

    fun submit(raw: String): State {
        val code = normalise(raw)
        if (!ApiClient.CODE.matches(code)) return State.Failed(Failure.BAD_FORMAT) // no network call for a typo
        return when (val r = client.pair(code, appVersion, osSdk)) {
            is ApiResult.Ok -> {
                val v = r.value
                val profile = PairProfile(v.parentId, v.language, v.brand, v.consentItems)
                // Token first: if saving the profile failed we would rather be paired without a profile than lose the token.
                tokens.saveToken(v.deviceToken)
                profiles.saveProfile(profile)
                State.Paired(profile)
            }
            is ApiResult.Err -> State.Failed(
                when (r.error) {
                    ApiError.PairingRejected -> Failure.WRONG_OR_EXPIRED
                    ApiError.RateLimited -> Failure.RATE_LIMITED
                    is ApiError.Network -> Failure.NETWORK
                    is ApiError.Malformed -> Failure.MALFORMED
                    is ApiError.ClientValidation -> Failure.BAD_FORMAT
                    else -> Failure.SERVER
                },
            )
        }
    }

    /** The server said the token is not valid any more (revoked, or the family paired a new phone): back to the code screen. */
    fun onUnauthorized(): State {
        unpair()
        return State.NeedsCode
    }

    /** After a successful erase, or when the parent removes the pairing. Local only; the server side is /erase. */
    fun unpair() {
        tokens.clearToken()
        profiles.clearProfile()
    }
}
