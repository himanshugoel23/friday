package app.robin.core

/**
 * The prompts the server wants the parent to see (from heartbeat, signals and /prompts replies). Rules: never show one
 * before ``not_before_ms`` (night prompts wait for the morning) or after ``expires_ms``; show the most serious first;
 * a prompt the parent already answered on this phone is not shown again while the server still lists it.
 * In memory only: the server is the source of truth and re-sends open prompts.
 */
class PromptQueue {
    private val open = LinkedHashMap<String, Prompt>()
    private val answered = LinkedHashSet<String>()

    /** The server's list is authoritative for what is still open: anything missing from it is dropped. */
    fun replaceFromServer(prompts: List<Prompt>) {
        val ids = prompts.map { it.promptId }.toSet()
        open.keys.retainAll(ids)
        answered.retainAll(ids) // forget answers for prompts the server no longer lists
        for (p in prompts) if (p.promptId !in answered) open[p.promptId] = p
    }

    /** Add prompts without dropping others (for a reply that carries only new ones). */
    fun addAll(prompts: List<Prompt>) {
        for (p in prompts) if (p.promptId !in answered) open.putIfAbsent(p.promptId, p)
    }

    /** Prompts that may be shown right now, most serious first, then oldest first. */
    fun due(nowMs: Long): List<Prompt> =
        open.values.filter { it.notBeforeMs <= nowMs && nowMs < it.expiresMs }
            .sortedWith(compareBy<Prompt> { rank(it.tier) }.thenBy { it.notBeforeMs })

    fun next(nowMs: Long): Prompt? = due(nowMs).firstOrNull()

    /** The parent tapped a button (or the app acked it): hide it from now on. */
    fun markAnswered(promptId: String) {
        open.remove(promptId)
        answered.add(promptId)
    }

    /** When the next held-back prompt becomes due, so the app can wake then (null if none waits). */
    fun nextDueAt(nowMs: Long): Long? =
        open.values.filter { it.notBeforeMs > nowMs && it.notBeforeMs < it.expiresMs }.minOfOrNull { it.notBeforeMs }

    fun size(): Int = open.size

    fun clear() {
        open.clear()
        answered.clear()
    }

    companion object {
        private val ORDER = listOf("EMERGENCY", "HIGH", "MEDIUM", "LOW", "INFO")

        /** Unknown tiers rank as HIGH, like the server (never hide something we do not understand). */
        fun rank(tier: String): Int {
            val i = ORDER.indexOf(tier.uppercase())
            return if (i >= 0) i else ORDER.indexOf("HIGH")
        }
    }
}
