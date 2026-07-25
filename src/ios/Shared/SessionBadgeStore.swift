import Foundation
import Combine

/// A transient, prioritized status that can be shown as a small corner badge on
/// a session's list-cell icon. Ordered, head-of-queue wins.
///
/// The design is a per-session *queue* rather than a single flag so multiple
/// concurrent statuses can coexist (e.g. a session is both background-paused and
/// iCloud-syncing): the highest-priority one is shown, and when it's cleared the
/// next one surfaces. Only `.paused` is produced today; the enum + queue exist so
/// future states (`.iCloudSyncing`, `.error`, `.uploading`, …) drop in without a
/// rearchitecture, and so iOS/Android stay structurally aligned.
///
/// Note: the existing iCloud badge in `SessionRow` is *derived* from
/// `ChatSession.isRemote` and is intentionally left as the render fallback — it
/// is not migrated into this queue. The queue owns the new, transient states.
enum SessionBadgeState: String, Codable {
    /// The session's agent task was suspended by the system while backgrounded
    /// (the "Interrupted — tap Resume" condition). Cleared once the user opens
    /// the session. Rendered as an orange circle with a white exclamation mark.
    case paused

    /// Reserved for future use — an explicit iCloud-syncing state, should we ever
    /// move the derived `isRemote` badge into the queue. Not produced yet.
    case iCloudSyncing

    /// [T-ios-session-unread-badge] A background task finished and posted its
    /// completion notification, so this session has an unread new message.
    /// Cleared the moment the user opens the session (loadSession). Rendered as
    /// a small red dot at the icon's TOP-trailing corner — a different corner
    /// from `.paused` (bottom-trailing), so the two can coexist. Intentionally
    /// NOT persisted (see `persist()`): it's a transient, lightweight hint that
    /// is fine to lose on relaunch.
    case unread
}

/// Owns the per-session badge-state queues and their persistence. Observed by
/// `SessionRow` (like `SessionLockStore`) so a change re-evaluates the affected
/// rows in place.
@MainActor
final class SessionBadgeStore: ObservableObject {
    static let shared = SessionBadgeStore()

    /// sessionId → ordered badge states (index 0 = highest priority, shown).
    /// `@Published` so observing rows refresh when a session's queue changes.
    @Published private(set) var badgeStates: [String: [SessionBadgeState]] = [:]

    private static let storageKey = "sessionBadgeStates.v1"

    private init() {
        restore()
    }

    // MARK: - Query

    /// The badge state to render for `sessionId`, or nil if the queue is empty.
    func topBadge(for sessionId: String) -> SessionBadgeState? {
        badgeStates[sessionId]?.first
    }

    /// Whether `sessionId` currently carries the `.unread` hint. Rendered as a
    /// separate top-trailing red dot, independent of `topBadge` (which owns the
    /// bottom-trailing corner), so an unread session can also show e.g. ⏸.
    func hasUnread(for sessionId: String) -> Bool {
        badgeStates[sessionId]?.contains(.unread) ?? false
    }

    /// The highest-priority *corner-badge* state for `sessionId`, skipping
    /// `.unread` (which renders separately as a top-trailing dot, not through the
    /// bottom-trailing corner badge). `.unread` is pushed to the queue front, so
    /// `topBadge` alone would shadow a coexisting `.paused`; this returns the
    /// first non-`.unread` entry instead.
    func topCornerBadge(for sessionId: String) -> SessionBadgeState? {
        badgeStates[sessionId]?.first { $0 != .unread }
    }

    // MARK: - Mutation

    /// Push `state` to the *front* of the session's queue (highest priority).
    /// No-op if the same state is already at the front, so repeated interruptions
    /// don't stack duplicates. Persists.
    func pushFront(_ state: SessionBadgeState, for sessionId: String) {
        var queue = badgeStates[sessionId] ?? []
        // Drop any existing copy so the state isn't duplicated, then prepend.
        queue.removeAll { $0 == state }
        queue.insert(state, at: 0)
        badgeStates[sessionId] = queue
        persist()
    }

    /// Remove `state` from the session's queue (if present). The next state in
    /// the queue, if any, becomes the visible badge. Persists.
    func remove(_ state: SessionBadgeState, for sessionId: String) {
        guard var queue = badgeStates[sessionId] else { return }
        let before = queue.count
        queue.removeAll { $0 == state }
        guard queue.count != before else { return }
        if queue.isEmpty {
            badgeStates.removeValue(forKey: sessionId)
        } else {
            badgeStates[sessionId] = queue
        }
        persist()
    }

    /// [T-ios-session-paused-badge-hardkill] Reconcile the `.paused` badges
    /// against the authoritative set of currently-interrupted sessions (derived
    /// from the persisted message tail by `ChatStore.interruptedSessionIds`).
    /// Called once at launch so a session hard-killed (jetsam/SIGKILL) while
    /// running — which never hit the background-expiry push path — still shows
    /// the badge after restart, and a session that is NO longer interrupted
    /// (resumed/completed before the kill) gets its stale badge cleared.
    ///
    /// Only touches `.paused`; other queued states are left intact.
    func reconcileInterruptedSessions(_ interruptedIds: Set<String>) {
        var changed = false
        // Add .paused for interrupted sessions that don't have it yet.
        for sid in interruptedIds where badgeStates[sid]?.contains(.paused) != true {
            var queue = badgeStates[sid] ?? []
            queue.insert(.paused, at: 0)
            badgeStates[sid] = queue
            changed = true
        }
        // Remove .paused from sessions that are no longer interrupted.
        for (sid, queue) in badgeStates where queue.contains(.paused) && !interruptedIds.contains(sid) {
            var q = queue
            q.removeAll { $0 == .paused }
            if q.isEmpty { badgeStates.removeValue(forKey: sid) } else { badgeStates[sid] = q }
            changed = true
        }
        if changed { persist() }
    }

    /// Remove a session's entire queue (e.g. when the session is deleted).
    func clearAll(for sessionId: String) {
        guard badgeStates[sessionId] != nil else { return }
        badgeStates.removeValue(forKey: sessionId)
        persist()
    }

    // MARK: - Persistence

    private func persist() {
        // Encode [String: [String]] (rawValues) so a future enum-case addition
        // can't fail to decode the whole store — unknown cases are skipped on
        // restore instead.
        // [T-ios-session-unread-badge] `.unread` is a transient hint that must
        // not survive relaunch (a completed-in-background task the user hasn't
        // read yet should not re-flag a red dot forever). Strip it before
        // encoding; queues that held only `.unread` drop out entirely.
        let raw = badgeStates
            .mapValues { $0.filter { $0 != .unread }.map(\.rawValue) }
            .filter { !$0.value.isEmpty }
        if let data = try? JSONEncoder().encode(raw) {
            UserDefaults.standard.set(data, forKey: Self.storageKey)
        }
    }

    private func restore() {
        guard let data = UserDefaults.standard.data(forKey: Self.storageKey),
              let raw = try? JSONDecoder().decode([String: [String]].self, from: data)
        else { return }
        var restored: [String: [SessionBadgeState]] = [:]
        for (sessionId, rawStates) in raw {
            // Skip unknown/legacy raw values rather than dropping the session.
            let states = rawStates.compactMap { SessionBadgeState(rawValue: $0) }
            if !states.isEmpty { restored[sessionId] = states }
        }
        badgeStates = restored
    }
}
