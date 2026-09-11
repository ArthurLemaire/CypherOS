package com.openminis.app.data.db

/** Raw usage record from joined messages + sessions query. */
data class UsageRecord(
    /**
     * [T-android-usage-orphan-rows] Nullable because `allUsageRecords` uses a
     * LEFT JOIN (GH#168): a message whose `sessions` row is missing still
     * carries real, already-billed token usage and must be counted, but it has
     * no session to read a model id from. Room would throw on the NULL if this
     * stayed non-null. Callers group these under "Unknown".
     */
    val modelId: String?,
    val tokenUsage: String,
    val createdAt: Long,
    val sessionId: String,
)
