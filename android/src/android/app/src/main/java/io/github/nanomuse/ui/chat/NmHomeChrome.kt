package io.github.nanomuse.ui.chat

/**
 * Passed to `ChatScreen` when it is hosted inside the home shell (`io.github.nanomuse.ui.home`).
 * It swaps the back arrow for Muse's hamburger, the kebab for a round button, and — for the
 * main chat — grows the header into Muse's big-face layout; side chats get their title instead.
 */
data class NmHomeChrome(
    val isMainChat: Boolean,
    val onOpenDrawer: () -> Unit,
)
