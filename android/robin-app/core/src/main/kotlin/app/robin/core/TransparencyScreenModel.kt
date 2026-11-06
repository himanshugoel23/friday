package app.robin.core

/**
 * Model for the "what is on" screen (also the Play transparency requirement): what Robin collects, what it never
 * collects, what the family was told, and whether Robin is paused or still in its learning week. Lines that come from
 * the server (collected / never / meaning / why) are shown as received; the headings are app strings (PENDING).
 */
class TransparencyScreenModel(
    val banner: Banner,
    val collected: List<String>,
    val neverCollected: List<String>,
    val toldFamily: List<ToldChild>,
    val learningDaysLeft: Int,
    val learningMeaning: String?,
    val counters: List<Pair<String, Int>>,
    val allowedItems: List<String>,
    val withdrawnItems: List<String>,
) {
    enum class Banner { NORMAL, PAUSED, LEARNING }

    /** Nothing is being collected at all (every consent item is off or the phone is paused). */
    val nothingOn: Boolean get() = banner == Banner.PAUSED || allowedItems.isEmpty()

    companion object {
        fun from(r: TransparencyReply, order: List<String> = emptyList()): TransparencyScreenModel {
            val banner = when {
                r.paused -> Banner.PAUSED
                r.learningMode.active -> Banner.LEARNING
                else -> Banner.NORMAL
            }
            fun ordered(allowed: Boolean): List<String> {
                val names = r.consent.filterValues { it == allowed }.keys
                return order.filter { it in names } + names.filter { it !in order }.sorted()
            }
            return TransparencyScreenModel(
                banner = banner,
                collected = r.collected,
                neverCollected = r.neverCollected,
                // newest first, as the family sees them; the server already limits this to the last 20
                toldFamily = r.toldChild.sortedByDescending { it.tsMs },
                learningDaysLeft = if (r.learningMode.active) r.learningMode.daysLeft else 0,
                learningMeaning = if (r.learningMode.active) r.learningMode.meaning else null,
                counters = r.counters.entries.sortedBy { it.key }.map { it.key to it.value },
                allowedItems = ordered(true),
                withdrawnItems = ordered(false),
            )
        }
    }
}
