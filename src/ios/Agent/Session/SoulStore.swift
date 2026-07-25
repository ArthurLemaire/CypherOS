import Foundation
import SwiftUI

/// Persistent personality/identity file living alongside GLOBAL.md and the
/// daily memory logs. Two-part format: YAML frontmatter (delimited by `---`)
/// followed by a Markdown body. The body is injected as Layer 1 of the
/// system prompt; the `name` / `emoji` fields drive the chat bubble header.
struct SoulMetadata: Equatable {
    var name: String
    /// Raw `emoji` value parsed from SOUL.md. Preserved on disk for
    /// backward compatibility but NOT shown anywhere in the UI: the chat
    /// bubble header and Soul Settings preview always render
    /// `displayEmoji` (a fixed sparkles glyph). User-customized emoji
    /// was removed; this field is round-tripped untouched if the file
    /// already has one.
    var emoji: String
    var style: String
    /// `"auto"`, `"zh"`, `"en"`, or any free-form tag.
    var lang: String

    /// The emoji shown in every UI surface (chat bubble header, Soul
    /// Settings preview card). Hard-coded — see comment on `emoji`.
    var displayEmoji: String { "✨" }

    static let `default` = SoulMetadata(
        name: "Minis",
        // Default emoji is intentionally empty — the UI uses the fixed
        // `displayEmoji` sparkle and serialize() no longer writes the
        // `emoji:` line. Kept on the struct only so the parser can
        // round-trip an `emoji: "..."` line that survives in an old
        // user-authored SOUL.md (next save will drop it on disk too).
        emoji: "",
        // Default style is also empty so the user fills it in themselves
        // (UI shows a placeholder hint). Avoids shipping an opinionated
        // baseline that users have to first delete before authoring their
        // own.
        style: "",
        lang: "auto"
    )
}

/// Result of parsing a SOUL.md file. `body` is the Markdown body with
/// frontmatter stripped (trimmed of leading newlines).
struct SoulFile: Equatable {
    var metadata: SoulMetadata
    var body: String
}

enum SoulMDParser {

    /// Parse a SOUL.md file content into metadata + body. When the file has
    /// no frontmatter, the entire text is treated as body and metadata
    /// falls back to default. Designed to be lossless enough that
    /// `serialize(parse(s)) == s` for files this app writes itself.
    static func parse(_ source: String) -> SoulFile {
        let trimmedLeading = source.drop(while: { $0 == "\n" || $0 == "\r" })
        // Frontmatter must start with "---" on its own line and end with
        // another "---" on its own line. Otherwise return as plain body.
        guard trimmedLeading.hasPrefix("---") else {
            return SoulFile(metadata: .default, body: source)
        }
        let lines = String(trimmedLeading).components(separatedBy: "\n")
        // First line is the opening "---". Find the matching closing "---".
        guard lines.first?.trimmingCharacters(in: .whitespaces) == "---",
              let closeIdx = lines.dropFirst().firstIndex(where: { $0.trimmingCharacters(in: .whitespaces) == "---" })
        else {
            return SoulFile(metadata: .default, body: source)
        }
        let frontmatterLines = Array(lines[1..<closeIdx])
        let bodyLines = Array(lines[(closeIdx + 1)...])
        let body = bodyLines.joined(separator: "\n").drop(while: { $0 == "\n" || $0 == "\r" })
        var meta = SoulMetadata.default
        for raw in frontmatterLines {
            let line = raw.trimmingCharacters(in: .whitespaces)
            guard let colon = line.firstIndex(of: ":") else { continue }
            let key = line[..<colon].trimmingCharacters(in: .whitespaces).lowercased()
            var value = String(line[line.index(after: colon)...]).trimmingCharacters(in: .whitespaces)
            // Strip optional surrounding double quotes; otherwise take raw.
            if value.hasPrefix("\""), value.hasSuffix("\""), value.count >= 2 {
                value = String(value.dropFirst().dropLast())
            }
            switch key {
            case "name":  if !value.isEmpty { meta.name = value }
            case "emoji": if !value.isEmpty { meta.emoji = value }
            case "style": meta.style = value
            case "lang":  if !value.isEmpty { meta.lang = value }
            default: break
            }
        }
        return SoulFile(metadata: meta, body: String(body))
    }

    /// Serialize back to SOUL.md text. Emits a 3-key frontmatter
    /// block (name / style / lang) followed by an empty line and the body.
    /// The `emoji` field is deliberately NOT written — the UI is locked to
    /// a fixed sparkle (`displayEmoji`), so persisting a `emoji:` line would
    /// imply user-controlled customization that doesn't exist. Old files
    /// containing `emoji: "..."` still parse cleanly (the value is kept in
    /// memory for round-trip safety) but the line is dropped on the next
    /// save, naturally migrating disk state to the new schema.
    static func serialize(_ file: SoulFile) -> String {
        var out = "---\n"
        out += "name: \"\(escape(file.metadata.name))\"\n"
        out += "style: \"\(escape(file.metadata.style))\"\n"
        out += "lang: \"\(escape(file.metadata.lang))\"\n"
        out += "---\n\n"
        out += file.body
        if !out.hasSuffix("\n") { out += "\n" }
        return out
    }

    private static func escape(_ s: String) -> String {
        s.replacingOccurrences(of: "\\", with: "\\\\")
         .replacingOccurrences(of: "\"", with: "\\\"")
    }
}

/// Result of a SOUL.md body length check. The hard limit depends on what
/// language the body is written in — Chinese / Japanese / Korean text is
/// information-dense per character so the cap is in grapheme clusters,
/// while English / other Latin-alphabet text is capped by word count.
///
/// Mirrors `SoulStore.isOverLimit(_:)`. The associated value carries the
/// observed token count and the matching cap so callers can surface a
/// precise "your body is N / max M" message.
enum SoulBodyLimitCheck: Equatable {
    case ok
    case overLimit(count: Int, cap: Int)

    var isOverLimit: Bool {
        if case .ok = self { return false }
        return true
    }
}

/// Filesystem helpers for SOUL.md. The file lives in the same memory
/// directory as GLOBAL.md and daily logs.
enum SoulStore {

    static var fileURL: URL {
        AIChatViewModel.minisMemoryPersistentDir.appendingPathComponent("SOUL.md")
    }

    // MARK: - Body length rules (unified token count)
    //
    // The personality body has a single hard cap of 2000 tokens, applied
    // at every write surface (Settings UI Save button, minis-config writer,
    // and the prompt-build-time fallback in `SystemPromptBuilder`).
    //
    // Counting rules — see `tokenCount(_:)`:
    //   - Each CJK glyph or CJK punctuation mark = 1 token
    //   - Each whitespace-delimited Latin / Cyrillic / etc. run = 1 token
    //   - Mixed text adds both kinds together
    //
    // So "hello AB CD" with two CJK glyphs counts as 1 (hello) + 4 (A B C D) = 5.

    static let bodyTokenLimit = 2000

    /// Count tokens in [body] under the unified rule. Empty / whitespace
    /// returns 0. CJK glyphs/punctuation count one-per-character; non-CJK
    /// text counts one-per-whitespace-delimited-word.
    static func tokenCount(_ body: String) -> Int {
        var count = 0
        var inWord = false
        for scalar in body.unicodeScalars {
            if isCJKScalar(scalar) || isCJKPunctuationScalar(scalar) {
                // Close any open Latin word, then count the CJK glyph itself.
                if inWord { count += 1; inWord = false }
                count += 1
            } else if CharacterSet.whitespacesAndNewlines.contains(scalar) {
                if inWord { count += 1; inWord = false }
            } else {
                inWord = true
            }
        }
        if inWord { count += 1 }
        return count
    }

    /// Classify [body] under the unified 2000-token rule. Empty /
    /// whitespace-only bodies always return `.ok`.
    static func isOverLimit(_ body: String) -> SoulBodyLimitCheck {
        let trimmed = body.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return .ok }
        let count = tokenCount(trimmed)
        return count > Self.bodyTokenLimit
            ? .overLimit(count: count, cap: Self.bodyTokenLimit)
            : .ok
    }

    /// CJK punctuation that the user perceives as a character — full-width
    /// comma, period, brackets, etc. Counted alongside CJK glyphs so a
    /// 100-glyph Chinese paragraph with 10 commas reports as 110, matching
    /// what a user counts visually.
    private static func isCJKPunctuationScalar(_ s: Unicode.Scalar) -> Bool {
        let v = s.value
        // CJK Symbols and Punctuation: 、。「」『』〈〉《》…
        if (0x3000...0x303F).contains(v) { return true }
        // Halfwidth and Fullwidth Forms: ,.!?:;()… (full-width)
        if (0xFF00...0xFFEF).contains(v) { return true }
        return false
    }

    /// True if [scalar] belongs to any of the CJK Unified Ideograph or
    /// Kana / Hangul ranges. Covers Chinese (Simplified + Traditional),
    /// Japanese (Hiragana + Katakana + Kanji shared with CJK Unified),
    /// and Korean (Hangul Syllables + Jamo). Wider than just U+4E00–U+9FFF
    /// so CJK-Ext-A/B/C/… and Hangul also count toward the ratio.
    private static func isCJKScalar(_ s: Unicode.Scalar) -> Bool {
        let v = s.value
        // CJK Unified Ideographs + Ext A
        if (0x4E00...0x9FFF).contains(v) { return true }
        if (0x3400...0x4DBF).contains(v) { return true }
        // CJK Unified Ideographs Ext B, C/D/E/F, G/H
        if (0x20000...0x2A6DF).contains(v) { return true }
        if (0x2A700...0x2EBEF).contains(v) { return true }
        if (0x30000...0x323AF).contains(v) { return true }
        // Hiragana, Katakana, Katakana Phonetic Extensions
        if (0x3040...0x309F).contains(v) { return true }
        if (0x30A0...0x30FF).contains(v) { return true }
        if (0x31F0...0x31FF).contains(v) { return true }
        // Hangul Syllables, Jamo, Compatibility Jamo
        if (0xAC00...0xD7AF).contains(v) { return true }
        if (0x1100...0x11FF).contains(v) { return true }
        if (0x3130...0x318F).contains(v) { return true }
        return false
    }

    /// The verbatim default file content used both for auto-create on first
    /// run and for the "Restore Default" button in Settings.
    ///
    /// IMPORTANT: the body contains ONLY personality / character / voice
    /// guidance. It must NOT contain the "You are <name>, …" identity
    /// sentence — that boilerplate is owned by `SystemPromptBuilder` and
    /// stitched in around the body at prompt-build time. Mixing identity
    /// boilerplate into the body would:
    ///   (a) expose internal prompt structure to users in the Settings
    ///       Personality editor, and
    ///   (b) double-up "You are X" lines whenever the template-rendered
    ///       prompt also produces one.
    ///
    /// Defaults intentionally ship with NO personality body so the
    /// agent runs with vanilla behaviour out of the box and users decide
    /// what voice / tone to add themselves. Only the frontmatter (name /
    /// style / lang) is seeded.
    static let defaultContent: String = """
    ---
    name: "Minis"
    style: ""
    lang: "auto"
    ---

    """

    /// Create SOUL.md with default content if it does not already exist.
    /// Safe to call on every launch — never overwrites existing content.
    static func ensureExists() {
        let url = fileURL
        let fm = FileManager.default
        guard !fm.fileExists(atPath: url.path) else { return }
        // Parent dir is created earlier by registerFileProviderDomain;
        // defensive createDirectory here in case ensureExists is invoked
        // from a code path that runs before that.
        try? fm.createDirectory(at: url.deletingLastPathComponent(),
                                withIntermediateDirectories: true)
        try? defaultContent.data(using: .utf8)?.write(to: url, options: .atomic)
    }

    /// Read + parse the current SOUL.md. Returns nil when the file does
    /// not exist or is unreadable. An empty file parses to default-meta +
    /// empty body, which callers may want to treat as missing.
    static func load() -> SoulFile? {
        let url = fileURL
        guard FileManager.default.fileExists(atPath: url.path),
              let data = try? Data(contentsOf: url),
              let str = String(data: data, encoding: .utf8) else { return nil }
        return SoulMDParser.parse(str)
    }

    /// Best-effort cached metadata for synchronous call sites that cannot
    /// re-read the file (e.g. cell builders running off the main thread).
    /// Refreshed after every Settings save via `notifyChanged()`.
    @MainActor
    static var cachedMetadata: SoulMetadata = .default

    /// Re-read SOUL.md into `cachedMetadata` and post a notification so
    /// observers (chat bubble header, prompt builder, etc.) can refresh.
    @MainActor
    static func refreshCache() {
        if let file = load() {
            cachedMetadata = file.metadata
        } else {
            cachedMetadata = .default
        }
        NotificationCenter.default.post(name: .soulMdChanged, object: nil)
    }

    /// Persist a SoulFile back to disk and refresh the cache.
    @MainActor
    static func save(_ file: SoulFile) throws {
        let url = fileURL
        try? FileManager.default.createDirectory(at: url.deletingLastPathComponent(),
                                                 withIntermediateDirectories: true)
        let text = SoulMDParser.serialize(file)
        try text.data(using: .utf8)?.write(to: url, options: .atomic)
        cachedMetadata = file.metadata
        NotificationCenter.default.post(name: .soulMdChanged, object: nil)
        // Notify the V2 sync layer so SOUL.md changes propagate to the
        // user's other devices. SoulStore is a singleton record on
        // iCloud (recordId "soul"); the hydrator reads SOUL.md from
        // disk when building the outbound portable, so the only thing
        // we need to do here is enqueue it as dirty.
        Task { await ChatStore.shared.markDirty(recordType: "SoulV2", recordId: "soul") }
    }

    /// Apply an inbound SOUL.md from iCloud without re-marking it dirty.
    /// Used by the V2 sync hydrator's merger path. LWW-by-mtime is
    /// applied here so a stale remote write doesn't clobber a newer
    /// local file (the cloud record's updatedAt is the authority, not
    /// our local file mtime).
    @MainActor
    static func applyRemoteContent(_ markdown: String, remoteUpdatedAt: Date) {
        let url = fileURL
        let fm = FileManager.default
        // Compare local file mtime against the remote updatedAt; skip
        // the write if local is strictly newer (peer's record reflects
        // an older snapshot).
        if let attrs = try? fm.attributesOfItem(atPath: url.path),
           let localMtime = attrs[.modificationDate] as? Date,
           localMtime > remoteUpdatedAt {
            return
        }
        // [T-icloud-local-edit-clobber] Content-equality short circuit: an
        // echo of what we already have must not rewrite the file (rewriting
        // refreshes the LWW clock and fires soulMdChanged for nothing).
        if let data = try? Data(contentsOf: url),
           let localText = String(data: data, encoding: .utf8),
           localText == markdown {
            return
        }
        // Reject a remote default-seed payload when the local file is
        // already customized. The matching buildSoul guard prevents
        // healthy peers from pushing default seeds, but a record that
        // landed in iCloud before the buildSoul guard existed (or that
        // came from a downgraded device) would otherwise wipe out a
        // customized local SOUL.md via LWW.
        if markdown == defaultContent,
           let data = try? Data(contentsOf: url),
           let localText = String(data: data, encoding: .utf8),
           localText != defaultContent {
            return
        }
        try? fm.createDirectory(at: url.deletingLastPathComponent(),
                                withIntermediateDirectories: true)
        try? markdown.data(using: .utf8)?.write(to: url, options: .atomic)
        // Stamp the file's mtime to match the remote updatedAt so the
        // local mtime comparison stays meaningful across round-trips.
        try? fm.setAttributes([.modificationDate: remoteUpdatedAt],
                              ofItemAtPath: url.path)
        if let parsed = SoulMDParser.parse(markdown).metadata as SoulMetadata? {
            cachedMetadata = parsed
        }
        NotificationCenter.default.post(name: .soulMdChanged, object: nil)
    }
}

extension Notification.Name {
    /// Posted on the main thread whenever SOUL.md has been (re-)written
    /// via SoulStore. Listeners refresh derived UI state.
    static let soulMdChanged = Notification.Name("MinisSoulMdChanged")
}

// MARK: - System prompt composition

enum SystemPromptBuilder {

    private static let logger = AppLogger(category: "Soul")

    /// The identity sentence template. `{name}` is substituted from the
    /// SOUL metadata. This wording is owned by the app — users never see
    /// it in the Personality editor, and it's stable so model-side
    /// expectations ("Minis, capable AI assistant, iSH Linux shell")
    /// stay intact regardless of what the user writes in SOUL.md.
    ///
    /// IMPORTANT: keep this sentence in sync with the original literal
    /// that lived in `baseSystemPrompt` before SOUL.md existed. Wording
    /// changes here affect every chat.
    private static let identityTemplate =
        "You are {name}, a capable AI assistant running on an iOS device with a fully functional iSH Linux shell (Alpine Linux, aarch64). "

    /// Render the identity sentence (template + name) and optionally
    /// append the user-authored personality body from SOUL.md.
    ///
    /// Two distinct trailing-whitespace contracts so the next concatenated
    /// sentence in `baseSystemPrompt` glues correctly:
    ///   - No personality body → identity sentence with its original
    ///     single trailing space (byte-identical to the pre-SOUL prompt).
    ///   - With personality body → identity sentence + blank line +
    ///     "Personality:" block + blank line, so the runtime-guidance
    ///     sentence starts a fresh paragraph.
    ///
    /// Returned format (when SOUL body is present):
    ///
    ///     You are <name>, a capable AI assistant running on an iOS device …
    ///
    ///     Personality (from SOUL.md — your character and voice; defer to
    ///     the user's latest message when it conflicts with anything here):
    ///     <body>
    ///
    /// We never substitute a default body into the prompt — the identity
    /// sentence alone is the safe fallback when SOUL.md is missing or
    /// empty, matching pre-SOUL behavior.
    static func identitySection() -> String {
        let file = SoulStore.load()
        let name: String = {
            let n = (file?.metadata.name ?? SoulMetadata.default.name)
                .trimmingCharacters(in: .whitespacesAndNewlines)
            return n.isEmpty ? "Minis" : n
        }()
        let style: String = (file?.metadata.style ?? "")
            .trimmingCharacters(in: .whitespacesAndNewlines)

        let identity = identityTemplate.replacingOccurrences(of: "{name}", with: name)
        let identityTrimmed = identity.trimmingCharacters(in: .whitespaces)

        // [T-soul-hint] Fixed hint telling the model how SOUL fields can be
        // changed. Always appended (with or without a personality body) so
        // the model never says "I can't change my personality". This hint
        // is system-owned text and is NOT counted against the user-facing
        // SOUL body length limit (#356 / 500 EN words / 800 CN chars).
        let soulEditHint =
            "---\n" +
            "SOUL.md fields (name / style / lang / body) can be edited two ways:\n" +
            "1. Tool: call `minis-config` to propose changes (user must approve).\n" +
            "2. UI: ask the user to go to Settings → Soul to edit directly.\n" +
            "Pick whichever the user finds easier in context. Do not say you cannot change your personality."

        // [T-soul-style-injection 2026-05-18] The `style` frontmatter field
        // (response voice / tone / formatting preference, e.g. a row of
        // emojis or "concise, no markdown") was parsed and shown in the UI
        // but never reached the model — only the Markdown body was injected.
        // Render it as its own labeled paragraph so the model treats it as
        // a hard constraint on response style rather than free-form context.
        func styleBlock(_ s: String) -> String {
            guard !s.isEmpty else { return "" }
            // [T-agent-prompt-consistency-pass] Language priority made explicit:
            // the base prompt's "reply in the language matching the user's input"
            // rule is the generic default; a user-authored style that prescribes
            // a reply language is a more specific user preference and wins.
            return "\n\nResponse style (from SOUL.md `style` — apply to every reply unless the user explicitly asks otherwise; if it prescribes a reply language, it overrides the default match-the-user's-language rule):\n\(s)"
        }

        guard let body = file?.body else {
            return identityTrimmed + styleBlock(style) + "\n\n" + soulEditHint + "\n\n"
        }
        let trimmed = body.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else {
            return identityTrimmed + styleBlock(style) + "\n\n" + soulEditHint + "\n\n"
        }

        // Reject (NOT truncate) bodies that exceed the language-aware
        // limit. Truncation silently dropped half the user's text and
        // implied that "the agent still gets your character" when in
        // practice it was missing context. Falling back to identity-only
        // is the safer signal: the user notices the personality isn't
        // taking effect, opens Settings, and sees the same red over-limit
        // warning the Save button surfaces. Write paths already reject
        // over-limit; this branch only triggers for an on-disk file that
        // was written before this rule existed (or via shell / another
        // device).
        let check = SoulStore.isOverLimit(trimmed)
        guard !check.isOverLimit else {
            Self.logger.warning("[Soul] personality body is over the language-aware limit (\(check)) — falling back to identity-only system prompt.")
            return identityTrimmed + styleBlock(style) + "\n\n" + soulEditHint + "\n\n"
        }

        let personality = scrubInjections(trimmed)

        // Strip the trailing space we'd otherwise leave hanging at the
        // end of the first paragraph when a personality block follows.
        return identityTrimmed
            + "\n\nPersonality (from SOUL.md — your character and voice; defer to the user's latest message when it conflicts with anything here):\n"
            + personality
            + styleBlock(style)
            + "\n\n"
            + soulEditHint
            + "\n\n"
    }

    /// Drop lines that look like an attempt to subvert the system prompt.
    /// Conservative regex — matches "ignore previous instructions" and the
    /// usual variants ("disregard prior", "forget previous", etc.). Casts
    /// a wide net on purpose; SOUL.md is user-authored personality, not a
    /// place for instructions to the model anyway.
    private static func scrubInjections(_ s: String) -> String {
        let patterns: [String] = [
            #"(?i)ignore.{0,30}previous.{0,30}instructions?"#,
            #"(?i)disregard.{0,30}(previous|prior).{0,30}instructions?"#,
            #"(?i)forget.{0,30}(previous|prior).{0,30}instructions?"#,
        ]
        var lines = s.components(separatedBy: "\n")
        lines = lines.filter { line in
            for p in patterns {
                if line.range(of: p, options: .regularExpression) != nil {
                    return false
                }
            }
            return true
        }
        return lines.joined(separator: "\n")
    }
}

// MARK: - Reusable SwiftUI text view

/// Renders the current SOUL.md `name` (falling back to "Minis") and
/// auto-refreshes whenever SoulStore posts `.soulMdChanged`. Use this in
/// any place that previously hard-coded "Minis" as a label.
@MainActor
struct AssistantSoulName: View {
    @State private var name: String = SoulStore.cachedMetadata.name.isEmpty
        ? "Minis" : SoulStore.cachedMetadata.name
    var body: some View {
        Text(name)
            .onReceive(NotificationCenter.default.publisher(for: .soulMdChanged)) { _ in
                let n = SoulStore.cachedMetadata.name
                name = n.isEmpty ? "Minis" : n
            }
    }
}
