import Foundation
import UIKit

private let shareLog = AppLogger(category: "Share")

/// [T-share-buffer-merge] Minimal key-window toast for share-pipeline user
/// feedback. The app has no global toast infrastructure; this is deliberately
/// tiny and UIKit-level so it works regardless of which SwiftUI screen is
/// frontmost when a share is discarded.
@MainActor
enum ShareFeedbackToast {
    static func show(_ message: String, duration: TimeInterval = 3.0) {
        guard let window = UIApplication.shared.connectedScenes
            .compactMap({ ($0 as? UIWindowScene)?.keyWindow })
            .first else { return }

        let label = UILabel()
        label.text = message
        label.font = .systemFont(ofSize: 14, weight: .medium)
        label.textColor = .white
        label.numberOfLines = 0
        label.textAlignment = .center

        let container = UIView()
        container.backgroundColor = UIColor.black.withAlphaComponent(0.8)
        container.layer.cornerRadius = 12
        container.alpha = 0
        container.addSubview(label)
        window.addSubview(container)

        label.translatesAutoresizingMaskIntoConstraints = false
        container.translatesAutoresizingMaskIntoConstraints = false
        NSLayoutConstraint.activate([
            label.topAnchor.constraint(equalTo: container.topAnchor, constant: 10),
            label.bottomAnchor.constraint(equalTo: container.bottomAnchor, constant: -10),
            label.leadingAnchor.constraint(equalTo: container.leadingAnchor, constant: 16),
            label.trailingAnchor.constraint(equalTo: container.trailingAnchor, constant: -16),
            container.centerXAnchor.constraint(equalTo: window.centerXAnchor),
            container.bottomAnchor.constraint(equalTo: window.safeAreaLayoutGuide.bottomAnchor, constant: -80),
            container.widthAnchor.constraint(lessThanOrEqualTo: window.widthAnchor, constant: -48),
        ])

        UIView.animate(withDuration: 0.25) { container.alpha = 1 }
        DispatchQueue.main.asyncAfter(deadline: .now() + duration) {
            UIView.animate(withDuration: 0.25, animations: { container.alpha = 0 }) { _ in
                container.removeFromSuperview()
            }
        }
    }
}

/// Singleton that bridges the Share Extension's pending content into the main app.
final class ShareCoordinator: ObservableObject {
    static let shared = ShareCoordinator()

    /// How long a buffered share remains consumable (seconds).
    /// Must be long enough for the launch session (new or last) to finish loading.
    /// [T-share-buffer-merge] Raised 30 → 300: consumption happens on
    /// AIChatView.onAppear, so the old 30s window silently dropped the share
    /// whenever the user lingered on the session list (or a slow cold start)
    /// before entering a chat. 300s matches checkForPendingShare's staleness
    /// cutoff — within that window the user's intent to inject clearly stands.
    private static let bufferTTL: TimeInterval = 300

    /// Set to true when a `minis://share` URL is received.
    @Published var hasPendingShare = false {
        didSet {
            shareLog.info("[Share] hasPendingShare changed: \(oldValue) → \(self.hasPendingShare)")
        }
    }

    /// Single funnel for raising `hasPendingShare`. Before flipping the
    /// flag we ask every fullScreenCover host to dismiss, then wait one
    /// dismiss-animation duration so SwiftUI has actually torn the prior
    /// cover down. Otherwise the share UI tries to surface while a stale
    /// gallery / WebApp / camera cover is still on top and the user sees
    /// nothing happen.
    @MainActor
    func raisePendingShare() {
        guard !hasPendingShare else {
            shareLog.info("[Share] raisePendingShare: already pending — coalescing")
            return
        }
        shareLog.info("[Share] raisePendingShare: dismissing immersive covers, then setting flag")
        NotificationCenter.default.post(name: .dismissAllImmersivePresentations, object: nil)
        Task { @MainActor in
            try? await Task.sleep(nanoseconds: 350_000_000)
            self.hasPendingShare = true
        }
    }

    // MARK: - In-memory buffer (replaces pendingInjection)

    struct PendingShareBuffer {
        let share: PendingShare
        let bufferedAt: Date
    }

    /// Written by processPendingShare() in ContentView, consumed once by AIChatView.
    private(set) var pendingShareBuffer: PendingShareBuffer?

    /// Incremented each time a new buffer is stored. AIChatView observes this to
    /// trigger injection when the user is already inside a session (warm start).
    @Published private(set) var bufferVersion: Int = 0

    /// Write share content into the buffer.
    /// [T-share-buffer-merge] APPEND to an unconsumed buffer instead of
    /// replacing it. A second share arriving while the first still sits in
    /// the buffer (AIChatView hasn't injected yet — app mid-launch, covers
    /// dismissing, user on the session list) used to overwrite the first
    /// share's items entirely. Items are de-duplicated by (kind, value) —
    /// attachment file names are UUID-suffixed so distinct files never
    /// collide, while a doubled delivery of the same record stays single.
    /// bufferedAt renews so the merged buffer gets a fresh TTL window.
    func storeBuffer(_ share: PendingShare) {
        if let existing = pendingShareBuffer {
            var merged = existing.share.items
            for item in share.items where !merged.contains(where: { $0.kind == item.kind && $0.value == item.value }) {
                merged.append(item)
            }
            let mergedShare = PendingShare(items: merged, timestamp: share.timestamp)
            pendingShareBuffer = PendingShareBuffer(share: mergedShare, bufferedAt: Date())
            bufferVersion += 1
            shareLog.info("[Share] storeBuffer: MERGED \(existing.share.items.count) existing + \(share.items.count) new → \(merged.count) items (v\(bufferVersion))")
            return
        }
        pendingShareBuffer = PendingShareBuffer(share: share, bufferedAt: Date())
        bufferVersion += 1
        shareLog.info("[Share] storeBuffer: \(share.items.count) items buffered (v\(bufferVersion)) at \(Date())")
    }

    /// Consume the buffer. Returns nil (and cleans up) if expired or empty.
    func consumeBuffer() -> PendingShare? {
        guard let buf = pendingShareBuffer else {
            shareLog.info("[Share] consumeBuffer: buffer is nil — nothing to consume")
            return nil
        }
        pendingShareBuffer = nil
        let age = Date().timeIntervalSince(buf.bufferedAt)
        guard age < Self.bufferTTL else {
            shareLog.info("[Share] consumeBuffer: expired (age=\(String(format: "%.1f", age))s > \(Self.bufferTTL)s), discarding")
            SharedContainerStore.cleanSharedFiles()
            // [T-share-buffer-merge] Never drop a share silently: the user
            // explicitly shared content into Minis — tell them it didn't make
            // it instead of letting the screenshot vanish into thin air.
            Task { @MainActor in
                ShareFeedbackToast.show(String(localized: "Shared content expired. Please share again."))
            }
            return nil
        }
        shareLog.info("[Share] consumeBuffer: consumed \(buf.share.items.count) items (age=\(String(format: "%.1f", age))s)")
        return buf.share
    }

    /// Discard buffer if it has exceeded the TTL. Call on scene background.
    func clearBufferIfStale() {
        guard let buf = pendingShareBuffer else { return }
        let age = Date().timeIntervalSince(buf.bufferedAt)
        if age >= Self.bufferTTL {
            shareLog.info("[Share] clearBufferIfStale: expired (age=\(String(format: "%.1f", age))s > \(Self.bufferTTL)s), discarding")
            pendingShareBuffer = nil
            SharedContainerStore.cleanSharedFiles()
        }
    }

    // MARK: - Launch check

    /// Check for stale pending shares on app launch (e.g. if the extension wrote one but the URL didn't fire).
    func checkForPendingShare() {
        shareLog.info("[Share] checkForPendingShare called")
        if let pending = SharedContainerStore.loadPendingShare() {
            let age = Date().timeIntervalSince(pending.timestamp)
            shareLog.info("[Share] Found pending share: \(pending.items.count) items, age=\(String(format: "%.1f", age))s")
            if age < 300 {
                Task { @MainActor in raisePendingShare() }
            } else {
                shareLog.info("[Share] Pending share too old (\(String(format: "%.0f", age))s), discarding")
                SharedContainerStore.clearPendingShare()
                SharedContainerStore.cleanSharedFiles()
            }
        } else {
            shareLog.info("[Share] No pending share found")
        }
    }
}
