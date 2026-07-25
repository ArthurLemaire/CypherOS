import Foundation

/// Safe URL joining for provider endpoints.
///
/// Goal: when a user-provided base URL like `https://api.deepseek.com`,
/// `https://api.deepseek.com/`, or `https://api.deepseek.com/v1/` is combined
/// with a path like `/v1/chat/completions` or `chat/completions`, the result
/// must always have exactly one `/` between every segment — never `//` and
/// never a missing separator. The scheme's `://` must be preserved.
///
/// Implementation uses `URLComponents` to keep query/fragment intact and to
/// avoid the classic `replacingOccurrences("//", "/")` pitfall that eats the
/// scheme separator.
enum URLBuilding {

    /// Join a base URL with one or more path segments. Each segment may carry
    /// any number of leading/trailing slashes — they are normalized so the
    /// final URL has exactly one `/` between every part.
    ///
    /// - Query strings (`?foo=bar`) and fragments (`#frag`) on the *last*
    ///   segment are preserved on the result.
    /// - Colons inside a segment (e.g. `models/x:streamGenerateContent`)
    ///   survive untouched — they are not URL-encoded.
    /// - Empty segments are skipped.
    ///
    /// Returns the assembled string. Falls back to a best-effort string
    /// concatenation if `base` cannot be parsed as a URL — that path keeps
    /// existing behavior for malformed input rather than throwing.
    static func join(_ base: String, _ segments: String...) -> String {
        join(base, segments: segments)
    }

    static func join(_ base: String, segments: [String]) -> String {
        let trimmedBase = base.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmedBase.isEmpty else {
            return mergePathSegments(segments)
        }

        // Split the last segment into path / query / fragment so the query
        // and fragment ride along on the result rather than being mangled
        // into the path.
        var pathSegments: [String] = []
        var trailingQuery: String?
        var trailingFragment: String?

        for (idx, raw) in segments.enumerated() {
            let isLast = idx == segments.count - 1
            var seg = raw
            if isLast {
                if let hashIdx = seg.firstIndex(of: "#") {
                    trailingFragment = String(seg[seg.index(after: hashIdx)...])
                    seg = String(seg[..<hashIdx])
                }
                if let qIdx = seg.firstIndex(of: "?") {
                    trailingQuery = String(seg[seg.index(after: qIdx)...])
                    seg = String(seg[..<qIdx])
                }
            }
            pathSegments.append(seg)
        }

        // Try parsing the base via URLComponents so we can append to its path
        // without disturbing scheme/host/port/existing-query.
        if var components = URLComponents(string: trimmedBase) {
            let basePath = components.path
            let appended = mergePathSegments([basePath] + pathSegments)
            components.path = appended.isEmpty ? "" : appended

            // Merge queries: preserve any query on the base, then append the
            // last-segment query (if any) joined by `&`.
            if let q = trailingQuery, !q.isEmpty {
                if let existing = components.percentEncodedQuery, !existing.isEmpty {
                    components.percentEncodedQuery = existing + "&" + q
                } else {
                    components.percentEncodedQuery = q
                }
            }
            if let f = trailingFragment, !f.isEmpty {
                components.percentEncodedFragment = f
            }

            if let s = components.string {
                return s
            }
        }

        // Fallback: base wasn't a parseable URL. Strip its trailing slashes
        // and concatenate.
        var result = stripTrailingSlashes(trimmedBase)
        let mergedTail = mergePathSegments(pathSegments)
        if !mergedTail.isEmpty {
            result += mergedTail.hasPrefix("/") ? mergedTail : "/" + mergedTail
        }
        if let q = trailingQuery, !q.isEmpty {
            result += "?" + q
        }
        if let f = trailingFragment, !f.isEmpty {
            result += "#" + f
        }
        return result
    }

    /// `URL` variant. Returns nil if the assembled string isn't a valid URL.
    static func joinURL(_ base: String, _ segments: String...) -> URL? {
        URL(string: join(base, segments: segments))
    }

    // MARK: - Helpers

    /// Joins path segments with exactly one `/` between each non-empty piece.
    /// Preserves a leading `/` if the *first* non-empty segment had one.
    private static func mergePathSegments(_ segments: [String]) -> String {
        let pieces = segments
            .map { stripSurroundingSlashes($0) }
            .filter { !$0.isEmpty }

        guard !pieces.isEmpty else {
            // Caller may still want a leading "/" if any input segment was
            // explicitly "/" — but if everything was empty/whitespace, drop it.
            return ""
        }

        let firstHadLeadingSlash = segments.first(where: {
            !$0.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        })?.hasPrefix("/") ?? false

        let body = pieces.joined(separator: "/")
        return firstHadLeadingSlash ? "/" + body : body
    }

    private static func stripSurroundingSlashes(_ s: String) -> String {
        var start = s.startIndex
        var end = s.endIndex
        while start < end, s[start] == "/" {
            start = s.index(after: start)
        }
        while end > start, s[s.index(before: end)] == "/" {
            end = s.index(before: end)
        }
        return String(s[start..<end])
    }

    private static func stripTrailingSlashes(_ s: String) -> String {
        var end = s.endIndex
        while end > s.startIndex, s[s.index(before: end)] == "/" {
            end = s.index(before: end)
        }
        return String(s[s.startIndex..<end])
    }
}
