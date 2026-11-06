package app.robin.core

/**
 * The read-only "what my family allowed" view. There is deliberately NO function that grants: the family admin
 * gives consent; the phone can only show it and WITHDRAW items (the server refuses any `true` with 403).
 */
class ConsentView(private val client: ApiClient, private val order: List<String>) {
    data class Row(
        /** Server item name; the app maps it to a string resource (PENDING wording). */
        val item: String,
        val allowed: Boolean,
        /** Only an allowed item can be withdrawn. */
        val canWithdraw: Boolean,
    )

    data class Screen(val basis: String, val rows: List<Row>) {
        val anyAllowed: Boolean get() = rows.any { it.allowed }
    }

    fun load(): ApiResult<Screen> = client.consent().map { screen(it) }

    /** Withdraw one item; the reply is the new state. Erases what that item allowed the server to keep. */
    fun withdraw(item: String): ApiResult<Screen> = client.withdrawConsent(listOf(item)).map { screen(it) }

    fun withdrawAll(current: Screen): ApiResult<Screen> {
        val items = current.rows.filter { it.allowed }.map { it.item }
        if (items.isEmpty()) return ApiResult.Ok(current)
        return client.withdrawConsent(items).map { screen(it) }
    }

    fun screen(reply: ConsentReply): Screen {
        val known = order.filter { it in reply.items }
        val extra = reply.items.keys.filter { it !in order }.sorted() // an item newer than this app still shows up
        return Screen(reply.basis, (known + extra).map { Row(it, reply.items.getValue(it), reply.items.getValue(it)) })
    }
}
