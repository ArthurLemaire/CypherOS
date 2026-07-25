package com.openminis.app.data.db

/** Raw usage record from joined messages + sessions query. */
data class UsageRecord(
    val modelId: String,
    val tokenUsage: String,
    val createdAt: Long,
    val sessionId: String,
)
