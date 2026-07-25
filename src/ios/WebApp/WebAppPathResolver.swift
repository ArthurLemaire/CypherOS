import Foundation

private let resolverLogger = AppLogger(category: "WebAppResolver")

/// Translates a `(scope, scopeContext, relativeHtmlPath)` triple into the
/// host file URL of the HTML and a base directory the WebView should be
/// granted read-access to. The base is the directory we hand to
/// `WKWebView.loadFileURL(_:allowingReadAccessTo:)` so relative
/// `<script src="…">` / `<link href="…">` / `<img src="…">` references
/// inside the HTML can load.
///
/// All inputs are sandbox-relative so the row survives container UUID
/// rotation across reinstalls — the host base is recomputed at launch.
enum WebAppPathResolver {
    struct Resolved {
        let htmlURL: URL
        /// The directory passed to `loadFileURL(_:allowingReadAccessTo:)`.
        /// Always a parent of `htmlURL` (often the same dir). For mounts
        /// it's the mount root; for sessions it's the session root so
        /// nested asset folders work.
        let readAccessRoot: URL
    }

    enum ResolveError: Error, CustomStringConvertible {
        case missingContext
        case unknownMount
        case sourceMissing
        case escapesScope

        var description: String {
            switch self {
            case .missingContext: return "WebApp shortcut is missing scope context (sessionId or mountId)."
            case .unknownMount:   return "Mount no longer exists or hasn't been authorized in this run."
            case .sourceMissing:  return "Source HTML file is missing — the file may have been moved or deleted."
            case .escapesScope:   return "WebApp shortcut path escapes its scope and was rejected."
            }
        }
    }

    /// Resolve a shortcut to a host URL pair. Caller is responsible for
    /// presenting `ResolveError` to the user (e.g. an offer to remove the
    /// stale tile). Reads `MountedFoldersManager.shared` on `MainActor`
    /// when the scope is `.mount`, so call from main.
    @MainActor
    static func resolve(_ shortcut: WebAppShortcut) throws -> Resolved {
        let base: URL
        switch shortcut.pathScope {
        case .sessionAttachment:
            guard let sid = shortcut.scopeContext else { throw ResolveError.missingContext }
            base = AIChatViewModel.minisAttachmentsPersistentDir(for: sid)
        case .sessionWorkspace:
            guard let sid = shortcut.scopeContext else { throw ResolveError.missingContext }
            base = AIChatViewModel.minisWorkspacePersistentDir(for: sid)
        case .shared:
            base = AIChatViewModel.minisSharedPersistentDir
        case .mount:
            guard let raw = shortcut.scopeContext, let mountId = UUID(uuidString: raw) else {
                throw ResolveError.missingContext
            }
            guard let mountRoot = MountedFoldersManager.shared.resolvedURL(for: mountId) else {
                throw ResolveError.unknownMount
            }
            base = mountRoot
        }

        // Strip any leading slash so appendingPathComponent doesn't anchor
        // the stored path absolutely (which would defeat the scope).
        let trimmed = shortcut.htmlPath.trimmingCharacters(in: CharacterSet(charactersIn: "/"))
        let candidate = base.appendingPathComponent(trimmed).standardizedFileURL
        let scopeRoot = base.standardizedFileURL

        // Reject paths that escape the scope (e.g. "../../other-session/..").
        // standardizedFileURL collapses "..", so a hostile path becomes
        // visible after standardization. Compare path prefixes.
        if !candidate.path.hasPrefix(scopeRoot.path + "/") && candidate.path != scopeRoot.path {
            resolverLogger.warning("resolve: path escapes scope; candidate=\(candidate.path) scopeRoot=\(scopeRoot.path)")
            throw ResolveError.escapesScope
        }

        if !FileManager.default.fileExists(atPath: candidate.path) {
            throw ResolveError.sourceMissing
        }

        // For sessions, grant read access at the session root so the HTML
        // can pull from sibling folders (workspace/, attachments/, etc. —
        // common when the agent generates a multi-file site under the
        // session). For mounts we already have the mount root. For shared
        // the shared dir itself is the natural sandbox.
        let readAccessRoot: URL
        switch shortcut.pathScope {
        case .sessionAttachment, .sessionWorkspace:
            // <minisPersistentBase>/<sid>/   ← parent of attachments/ and workspace/
            readAccessRoot = base.deletingLastPathComponent()
        case .shared, .mount:
            readAccessRoot = base
        }

        return Resolved(htmlURL: candidate, readAccessRoot: readAccessRoot)
    }
}
