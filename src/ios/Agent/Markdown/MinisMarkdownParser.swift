import Foundation
import cmark_gfm
import cmark_gfm_extensions

// MARK: - Block & Inline Node types (inlined from swift-markdown-ui)

enum BlockNode: Hashable {
    case blockquote(children: [BlockNode])
    case bulletedList(isTight: Bool, items: [RawListItem])
    case numberedList(isTight: Bool, start: Int, items: [RawListItem])
    case taskList(isTight: Bool, items: [RawTaskListItem])
    case codeBlock(fenceInfo: String?, content: String)
    case htmlBlock(content: String)
    case paragraph(content: [InlineNode])
    case heading(level: Int, content: [InlineNode])
    case table(columnAlignments: [RawTableColumnAlignment], rows: [RawTableRow])
    case thematicBreak
    case mathBlock(content: String)
}

extension BlockNode {
    var children: [BlockNode] {
        switch self {
        case .blockquote(let children):
            return children
        case .bulletedList(_, let items):
            return items.map(\.children).flatMap { $0 }
        case .numberedList(_, _, let items):
            return items.map(\.children).flatMap { $0 }
        case .taskList(_, let items):
            return items.map(\.children).flatMap { $0 }
        default:
            return []
        }
    }

    var isParagraph: Bool {
        guard case .paragraph = self else { return false }
        return true
    }
}

struct RawListItem: Hashable {
    let children: [BlockNode]
}

struct RawTaskListItem: Hashable {
    let isCompleted: Bool
    let children: [BlockNode]
}

enum RawTableColumnAlignment: Character {
    case none = "\0"
    case left = "l"
    case center = "c"
    case right = "r"
}

struct RawTableRow: Hashable {
    let cells: [RawTableCell]
}

struct RawTableCell: Hashable {
    let content: [InlineNode]
}

enum InlineNode: Hashable, Sendable {
    case text(String)
    case softBreak
    case lineBreak
    case code(String)
    case html(String)
    case emphasis(children: [InlineNode])
    case strong(children: [InlineNode])
    case strikethrough(children: [InlineNode])
    case link(destination: String, children: [InlineNode])
    case image(source: String, children: [InlineNode])
    case inlineMath(String)
}

extension InlineNode {
    var children: [InlineNode] {
        get {
            switch self {
            case .emphasis(let children): return children
            case .strong(let children): return children
            case .strikethrough(let children): return children
            case .link(_, let children): return children
            case .image(_, let children): return children
            case .inlineMath: return []
            default: return []
            }
        }
        set {
            switch self {
            case .emphasis: self = .emphasis(children: newValue)
            case .strong: self = .strong(children: newValue)
            case .strikethrough: self = .strikethrough(children: newValue)
            case .link(let destination, _): self = .link(destination: destination, children: newValue)
            case .image(let source, _): self = .image(source: source, children: newValue)
            default: break
            }
        }
    }
}

// MARK: - MarkdownContent (minimal replacement for MarkdownUI.MarkdownContent)

struct MarkdownContent: Hashable {
    let blocks: [BlockNode]

    init(_ markdown: String) {
        let (cleaned, mathSpans) = MarkdownMathExtractor.extract(from: markdown)
        let parsed = [BlockNode](markdown: cleaned)
        if mathSpans.isEmpty {
            self.blocks = parsed
        } else {
            self.blocks = MarkdownMathExtractor.restore(blocks: parsed, spans: mathSpans)
        }
    }

    init(blocks: [BlockNode]) {
        self.blocks = blocks
    }
}

// MARK: - Math Extraction

/// Extracts LaTeX math from markdown before cmark parsing, then restores math nodes in the AST.
enum MarkdownMathExtractor {
    struct MathSpan {
        let placeholder: String
        let latex: String
        let isBlock: Bool
    }

    /// Extract math expressions, replacing them with placeholders.
    /// Returns the cleaned markdown and the list of extracted spans.
    static func extract(from markdown: String) -> (String, [MathSpan]) {
        var spans: [MathSpan] = []
        var result = ""
        let chars = Array(markdown)
        let count = chars.count
        var i = 0

        // Track code fences and inline code to skip them
        var inFencedCode = false
        var fenceChar: Character = "`"
        var fenceLen = 0

        while i < count {
            // Check for fenced code blocks (``` or ~~~)
            if !inFencedCode && (i == 0 || chars[i - 1] == "\n" || (i > 0 && chars[i - 1] == "\r")) {
                let fc = chars[i]
                if fc == "`" || fc == "~" {
                    var fl = 0
                    var j = i
                    while j < count && chars[j] == fc { fl += 1; j += 1 }
                    if fl >= 3 {
                        inFencedCode = true
                        fenceChar = fc
                        fenceLen = fl
                        // Copy the fence line
                        while i < count && chars[i] != "\n" {
                            result.append(chars[i]); i += 1
                        }
                        if i < count { result.append(chars[i]); i += 1 } // newline
                        continue
                    }
                }
            }

            if inFencedCode {
                // Look for closing fence
                if (i == 0 || chars[i - 1] == "\n") && chars[i] == fenceChar {
                    var fl = 0
                    var j = i
                    while j < count && chars[j] == fenceChar { fl += 1; j += 1 }
                    if fl >= fenceLen {
                        inFencedCode = false
                        // Copy through the rest of the fence line
                        while i < count && chars[i] != "\n" {
                            result.append(chars[i]); i += 1
                        }
                        if i < count { result.append(chars[i]); i += 1 }
                        continue
                    }
                }
                result.append(chars[i]); i += 1
                continue
            }

            // Skip inline code spans
            if chars[i] == "`" {
                var backtickLen = 0
                var j = i
                while j < count && chars[j] == "`" { backtickLen += 1; j += 1 }
                // Find matching closing backticks
                var found = false
                var k = j
                while k <= count - backtickLen {
                    var matchLen = 0
                    while k + matchLen < count && chars[k + matchLen] == "`" { matchLen += 1 }
                    if matchLen == backtickLen {
                        // Copy everything from i through k + matchLen - 1
                        for idx in i..<(k + matchLen) {
                            result.append(chars[idx])
                        }
                        i = k + matchLen
                        found = true
                        break
                    }
                    if matchLen > 0 { k += matchLen } else { k += 1 }
                }
                if found { continue }
                // No matching close — just output the backticks
                for idx in i..<j { result.append(chars[idx]) }
                i = j
                continue
            }

            // Escaped dollar sign
            if chars[i] == "\\" && i + 1 < count && chars[i + 1] == "$" {
                result.append(chars[i]); result.append(chars[i + 1])
                i += 2
                continue
            }

            // Check for \[ ... \] (display math)
            if chars[i] == "\\" && i + 1 < count && chars[i + 1] == "[" {
                if let end = findClosingBracket(chars: chars, from: i + 2, close: "\\]") {
                    let latex = String(chars[(i + 2)..<end])
                    let placeholder = "\u{FFFC}MATH\(spans.count)\u{FFFC}"
                    spans.append(MathSpan(placeholder: placeholder, latex: latex, isBlock: true))
                    result.append(placeholder)
                    i = end + 2 // skip past \]
                    continue
                }
            }

            // Check for \( ... \) (inline math)
            if chars[i] == "\\" && i + 1 < count && chars[i + 1] == "(" {
                if let end = findClosingBracket(chars: chars, from: i + 2, close: "\\)") {
                    let latex = String(chars[(i + 2)..<end])
                    let placeholder = "\u{FFFC}MATH\(spans.count)\u{FFFC}"
                    spans.append(MathSpan(placeholder: placeholder, latex: latex, isBlock: false))
                    result.append(placeholder)
                    i = end + 2
                    continue
                }
            }

            // Check for $$ ... $$ (display math)
            if chars[i] == "$" && i + 1 < count && chars[i + 1] == "$" {
                if let end = findDoubleDollar(chars: chars, from: i + 2) {
                    let latex = String(chars[(i + 2)..<end])
                    let placeholder = "\u{FFFC}MATH\(spans.count)\u{FFFC}"
                    spans.append(MathSpan(placeholder: placeholder, latex: latex, isBlock: true))
                    result.append(placeholder)
                    i = end + 2
                    continue
                }
            }

            // Check for $ ... $ (inline math)
            if chars[i] == "$" && i + 1 < count && chars[i + 1] != "$" && chars[i + 1] != " " {
                if let end = findSingleDollar(chars: chars, from: i + 1) {
                    let latex = String(chars[(i + 1)..<end])
                    // Heuristic: skip plain currency like $5, $10.
                    // [T-ios-table-cell-katex-false-positive] Also skip a span
                    // that is really a table-cell artifact: a row like
                    // `| 月付 | $20|$ **3** |` lets the `$` at `$20` pair with a
                    // later `$` and capture `20|` (a number + the column pipe)
                    // as a fake formula — rendered serif-italic with the bold
                    // `**3**` lost. See isTablePipeArtifact for the rule
                    // (whitespace-adjacent or unbalanced bars), which preserves
                    // real absolute-value formulas like $|x|$ / $\|v\|$.
                    if looksLikeMath(latex) && !isTablePipeArtifact(latex) {
                        let placeholder = "\u{FFFC}MATH\(spans.count)\u{FFFC}"
                        spans.append(MathSpan(placeholder: placeholder, latex: latex, isBlock: false))
                        result.append(placeholder)
                        i = end + 1
                        continue
                    }
                }
            }

            result.append(chars[i])
            i += 1
        }

        return (result, spans)
    }

    /// Restore math nodes in the parsed AST by replacing placeholder text nodes.
    static func restore(blocks: [BlockNode], spans: [MathSpan]) -> [BlockNode] {
        let placeholderMap = Dictionary(uniqueKeysWithValues: spans.map { ($0.placeholder, $0) })
        return blocks.map { restoreBlock($0, placeholderMap: placeholderMap) }
    }

    // MARK: - Private Helpers

    private static func findClosingBracket(chars: [Character], from start: Int, close: String) -> Int? {
        let closeChars = Array(close)
        var i = start
        while i <= chars.count - closeChars.count {
            var match = true
            for j in 0..<closeChars.count {
                if chars[i + j] != closeChars[j] { match = false; break }
            }
            if match { return i }
            i += 1
        }
        return nil
    }

    private static func findDoubleDollar(chars: [Character], from start: Int) -> Int? {
        var i = start
        while i < chars.count - 1 {
            if chars[i] == "$" && chars[i + 1] == "$" { return i }
            i += 1
        }
        return nil
    }

    private static func findSingleDollar(chars: [Character], from start: Int) -> Int? {
        var i = start
        while i < chars.count {
            if chars[i] == "\\" && i + 1 < chars.count { i += 2; continue } // skip escaped
            if chars[i] == "$" && (i == 0 || chars[i - 1] != " ") { return i }
            if chars[i] == "\n" { return nil } // single-line only
            i += 1
        }
        return nil
    }

    /// Heuristic: content looks like LaTeX if it contains special chars or is long enough.
    private static func looksLikeMath(_ content: String) -> Bool {
        if content.isEmpty { return false }
        let mathChars: Set<Character> = ["\\", "^", "_", "{", "}", "∫", "∑", "∏", "√"]
        for ch in content {
            if mathChars.contains(ch) { return true }
        }
        // Length > 2 also qualifies (e.g., "x+y")
        return content.count > 2
    }

    /// [T-ios-table-cell-katex-false-positive] True when a candidate inline-math
    /// span is really a markdown table-cell artifact (a `$` that paired across
    /// `|` column separators) rather than a formula. Two signals, both of which
    /// a real formula avoids:
    ///   1. An unescaped pipe with whitespace on a side — the table column
    ///      separator is written ` | ` / `| ` / ` |`. Real LaTeX keeps pipes
    ///      flush against operands.
    ///   2. An ODD number of unescaped pipes — absolute-value / norm bars always
    ///      come in balanced pairs (`|x|`, `\frac{|a|}{|b|}`), so an odd count
    ///      (e.g. `20|`, `240|`) is a stray column separator, not math.
    /// Escaped `\|` (LaTeX norm) is never counted as a bare pipe.
    private static func isTablePipeArtifact(_ content: String) -> Bool {
        let chars = Array(content)
        var bareCount = 0
        for (idx, ch) in chars.enumerated() where ch == "|" {
            if idx > 0 && chars[idx - 1] == "\\" { continue }   // escaped norm bar
            bareCount += 1
            let prevIsSpace = idx > 0 && chars[idx - 1].isWhitespace
            let nextIsSpace = idx + 1 < chars.count && chars[idx + 1].isWhitespace
            if prevIsSpace || nextIsSpace { return true }
        }
        return bareCount % 2 == 1
    }

    private static func restoreBlock(_ block: BlockNode, placeholderMap: [String: MathSpan]) -> BlockNode {
        switch block {
        case .paragraph(let content):
            let restored = restoreInlines(content, placeholderMap: placeholderMap)
            // If paragraph contains only a single block-math placeholder, promote to mathBlock
            if restored.count == 1, case .inlineMath(let latex) = restored[0] {
                if let span = placeholderMap.values.first(where: { $0.latex == latex && $0.isBlock }) {
                    return .mathBlock(content: span.latex)
                }
            }
            // Check for mathBlock in a paragraph that has only whitespace + the math
            let nonWhitespace = restored.filter {
                switch $0 {
                case .text(let t): return !t.trimmingCharacters(in: .whitespaces).isEmpty
                case .softBreak, .lineBreak: return false
                default: return true
                }
            }
            if nonWhitespace.count == 1, case .inlineMath(let latex) = nonWhitespace[0] {
                if let span = placeholderMap.values.first(where: { $0.latex == latex && $0.isBlock }) {
                    return .mathBlock(content: span.latex)
                }
            }
            return .paragraph(content: restored)
        case .heading(let level, let content):
            return .heading(level: level, content: restoreInlines(content, placeholderMap: placeholderMap))
        case .blockquote(let children):
            return .blockquote(children: children.map { restoreBlock($0, placeholderMap: placeholderMap) })
        case .bulletedList(let isTight, let items):
            return .bulletedList(isTight: isTight, items: items.map {
                RawListItem(children: $0.children.map { restoreBlock($0, placeholderMap: placeholderMap) })
            })
        case .numberedList(let isTight, let start, let items):
            return .numberedList(isTight: isTight, start: start, items: items.map {
                RawListItem(children: $0.children.map { restoreBlock($0, placeholderMap: placeholderMap) })
            })
        case .taskList(let isTight, let items):
            return .taskList(isTight: isTight, items: items.map {
                RawTaskListItem(isCompleted: $0.isCompleted, children: $0.children.map { restoreBlock($0, placeholderMap: placeholderMap) })
            })
        case .table(let alignments, let rows):
            return .table(columnAlignments: alignments, rows: rows.map { row in
                RawTableRow(cells: row.cells.map { cell in
                    RawTableCell(content: restoreInlines(cell.content, placeholderMap: placeholderMap))
                })
            })
        default:
            return block
        }
    }

    private static func restoreInlines(_ inlines: [InlineNode], placeholderMap: [String: MathSpan]) -> [InlineNode] {
        inlines.flatMap { restoreInline($0, placeholderMap: placeholderMap) }
    }

    private static func restoreInline(_ node: InlineNode, placeholderMap: [String: MathSpan]) -> [InlineNode] {
        switch node {
        case .text(let text):
            return splitTextWithPlaceholders(text, placeholderMap: placeholderMap)
        case .emphasis(let children):
            return [.emphasis(children: children.flatMap { restoreInline($0, placeholderMap: placeholderMap) })]
        case .strong(let children):
            return [.strong(children: children.flatMap { restoreInline($0, placeholderMap: placeholderMap) })]
        case .strikethrough(let children):
            return [.strikethrough(children: children.flatMap { restoreInline($0, placeholderMap: placeholderMap) })]
        case .link(let dest, let children):
            return [.link(destination: dest, children: children.flatMap { restoreInline($0, placeholderMap: placeholderMap) })]
        case .image(let src, let children):
            return [.image(source: src, children: children.flatMap { restoreInline($0, placeholderMap: placeholderMap) })]
        default:
            return [node]
        }
    }

    private static func splitTextWithPlaceholders(_ text: String, placeholderMap: [String: MathSpan]) -> [InlineNode] {
        var result: [InlineNode] = []
        var remaining = text

        while !remaining.isEmpty {
            // Find the next placeholder
            var earliest: (range: Range<String.Index>, span: MathSpan)?
            for (placeholder, span) in placeholderMap {
                if let range = remaining.range(of: placeholder) {
                    if earliest == nil || range.lowerBound < earliest!.range.lowerBound {
                        earliest = (range, span)
                    }
                }
            }

            guard let match = earliest else {
                result.append(.text(remaining))
                break
            }

            // Text before the placeholder
            let before = String(remaining[remaining.startIndex..<match.range.lowerBound])
            if !before.isEmpty {
                result.append(.text(before))
            }

            // The math node
            result.append(.inlineMath(match.span.latex))

            remaining = String(remaining[match.range.upperBound...])
        }

        return result
    }
}

// MARK: - cmark parsing glue

extension Array where Element == BlockNode {
    init(markdown: String) {
        let blocks = UnsafeNode.parseMarkdown(markdown) { document in
            document.children.compactMap(BlockNode.init(unsafeNode:))
        }
        self.init(blocks ?? .init())
    }
}

extension BlockNode {
    fileprivate init?(unsafeNode: UnsafeNode) {
        switch unsafeNode.nodeType {
        case .blockquote:
            self = .blockquote(children: unsafeNode.children.compactMap(BlockNode.init(unsafeNode:)))
        case .list:
            if unsafeNode.children.contains(where: \.isTaskListItem) {
                self = .taskList(
                    isTight: unsafeNode.isTightList,
                    items: unsafeNode.children.map(RawTaskListItem.init(unsafeNode:))
                )
            } else {
                switch unsafeNode.listType {
                case CMARK_BULLET_LIST:
                    self = .bulletedList(
                        isTight: unsafeNode.isTightList,
                        items: unsafeNode.children.map(RawListItem.init(unsafeNode:))
                    )
                case CMARK_ORDERED_LIST:
                    self = .numberedList(
                        isTight: unsafeNode.isTightList,
                        start: unsafeNode.listStart,
                        items: unsafeNode.children.map(RawListItem.init(unsafeNode:))
                    )
                default:
                    fatalError("cmark reported a list node without a list type.")
                }
            }
        case .codeBlock:
            self = .codeBlock(fenceInfo: unsafeNode.fenceInfo, content: unsafeNode.literal ?? "")
        case .htmlBlock:
            self = .htmlBlock(content: unsafeNode.literal ?? "")
        case .paragraph:
            self = .paragraph(content: unsafeNode.children.compactMap(InlineNode.init(unsafeNode:)))
        case .heading:
            self = .heading(
                level: unsafeNode.headingLevel,
                content: unsafeNode.children.compactMap(InlineNode.init(unsafeNode:))
            )
        case .table:
            self = .table(
                columnAlignments: unsafeNode.tableAlignments,
                rows: unsafeNode.children.map(RawTableRow.init(unsafeNode:))
            )
        case .thematicBreak:
            self = .thematicBreak
        default:
            assertionFailure("Unhandled node type '\(unsafeNode.nodeType)' in BlockNode.")
            return nil
        }
    }
}

extension RawListItem {
    fileprivate init(unsafeNode: UnsafeNode) {
        guard unsafeNode.nodeType == .item else {
            fatalError("Expected a list item but got a '\(unsafeNode.nodeType)' instead.")
        }
        self.init(children: unsafeNode.children.compactMap(BlockNode.init(unsafeNode:)))
    }
}

extension RawTaskListItem {
    fileprivate init(unsafeNode: UnsafeNode) {
        guard unsafeNode.nodeType == .taskListItem || unsafeNode.nodeType == .item else {
            fatalError("Expected a list item but got a '\(unsafeNode.nodeType)' instead.")
        }
        self.init(
            isCompleted: unsafeNode.isTaskListItemChecked,
            children: unsafeNode.children.compactMap(BlockNode.init(unsafeNode:))
        )
    }
}

extension RawTableRow {
    fileprivate init(unsafeNode: UnsafeNode) {
        guard unsafeNode.nodeType == .tableRow || unsafeNode.nodeType == .tableHead else {
            fatalError("Expected a table row but got a '\(unsafeNode.nodeType)' instead.")
        }
        self.init(cells: unsafeNode.children.map(RawTableCell.init(unsafeNode:)))
    }
}

extension RawTableCell {
    fileprivate init(unsafeNode: UnsafeNode) {
        guard unsafeNode.nodeType == .tableCell else {
            fatalError("Expected a table cell but got a '\(unsafeNode.nodeType)' instead.")
        }
        self.init(content: unsafeNode.children.compactMap(InlineNode.init(unsafeNode:)))
    }
}

extension InlineNode {
    fileprivate init?(unsafeNode: UnsafeNode) {
        switch unsafeNode.nodeType {
        case .text: self = .text(unsafeNode.literal ?? "")
        case .softBreak: self = .softBreak
        case .lineBreak: self = .lineBreak
        case .code: self = .code(unsafeNode.literal ?? "")
        case .html: self = .html(unsafeNode.literal ?? "")
        case .emphasis:
            self = .emphasis(children: unsafeNode.children.compactMap(InlineNode.init(unsafeNode:)))
        case .strong:
            self = .strong(children: unsafeNode.children.compactMap(InlineNode.init(unsafeNode:)))
        case .strikethrough:
            self = .strikethrough(children: unsafeNode.children.compactMap(InlineNode.init(unsafeNode:)))
        case .link:
            self = .link(
                destination: unsafeNode.url ?? "",
                children: unsafeNode.children.compactMap(InlineNode.init(unsafeNode:))
            )
        case .image:
            self = .image(
                source: unsafeNode.url ?? "",
                children: unsafeNode.children.compactMap(InlineNode.init(unsafeNode:))
            )
        default:
            assertionFailure("Unhandled node type '\(unsafeNode.nodeType)' in InlineNode.")
            return nil
        }
    }
}

// MARK: - UnsafeNode helpers

private typealias UnsafeNode = UnsafeMutablePointer<cmark_node>

extension UnsafeNode {
    fileprivate var nodeType: NodeType {
        let typeString = String(cString: cmark_node_get_type_string(self))
        guard let nodeType = NodeType(rawValue: typeString) else {
            fatalError("Unknown node type '\(typeString)' found.")
        }
        return nodeType
    }

    fileprivate var children: UnsafeNodeSequence {
        .init(cmark_node_first_child(self))
    }

    fileprivate var literal: String? {
        cmark_node_get_literal(self).map(String.init(cString:))
    }

    fileprivate var url: String? {
        cmark_node_get_url(self).map(String.init(cString:))
    }

    fileprivate var isTaskListItem: Bool {
        self.nodeType == .taskListItem
    }

    fileprivate var listType: cmark_list_type {
        cmark_node_get_list_type(self)
    }

    fileprivate var listStart: Int {
        Int(cmark_node_get_list_start(self))
    }

    fileprivate var isTaskListItemChecked: Bool {
        cmark_gfm_extensions_get_tasklist_item_checked(self)
    }

    fileprivate var isTightList: Bool {
        cmark_node_get_list_tight(self) != 0
    }

    fileprivate var fenceInfo: String? {
        cmark_node_get_fence_info(self).map(String.init(cString:))
    }

    fileprivate var headingLevel: Int {
        Int(cmark_node_get_heading_level(self))
    }

    fileprivate var tableColumns: Int {
        Int(cmark_gfm_extensions_get_table_columns(self))
    }

    fileprivate var tableAlignments: [RawTableColumnAlignment] {
        (0..<self.tableColumns).map { column in
            let ascii = cmark_gfm_extensions_get_table_alignments(self)[column]
            let scalar = UnicodeScalar(ascii)
            let character = Character(scalar)
            return .init(rawValue: character) ?? .none
        }
    }

    fileprivate static func parseMarkdown<ResultType>(
        _ markdown: String,
        body: (UnsafeNode) throws -> ResultType
    ) rethrows -> ResultType? {
        cmark_gfm_core_extensions_ensure_registered()

        // [T-strikethrough-syntax] Require a DOUBLE tilde for strikethrough.
        // cmark-gfm's strikethrough extension accepts a SINGLE `~` as a
        // delimiter by default, so prose using `~` as a range separator
        // (e.g. "msg 41797~42810", "6月14日~6月16日") was incorrectly struck
        // through. CMARK_OPT_STRIKETHROUGH_DOUBLE_TILDE makes only `~~text~~`
        // trigger strikethrough; a lone `~` stays literal — matching GFM.
        let parser = cmark_parser_new(CMARK_OPT_DEFAULT | CMARK_OPT_STRIKETHROUGH_DOUBLE_TILDE)
        defer { cmark_parser_free(parser) }

        let extensionNames: Set<String>

        if #available(iOS 16.0, macOS 13.0, tvOS 16.0, watchOS 9.0, *) {
            extensionNames = ["autolink", "strikethrough", "tagfilter", "tasklist", "table"]
        } else {
            extensionNames = ["autolink", "strikethrough", "tagfilter", "tasklist"]
        }

        for extensionName in extensionNames {
            guard let syntaxExtension = cmark_find_syntax_extension(extensionName) else {
                continue
            }
            cmark_parser_attach_syntax_extension(parser, syntaxExtension)
        }

        cmark_parser_feed(parser, markdown, markdown.utf8.count)

        guard let document = cmark_parser_finish(parser) else {
            return nil
        }

        defer { cmark_node_free(document) }
        return try body(document)
    }
}

// MARK: - NodeType enum

private enum NodeType: String {
    case document
    case blockquote = "block_quote"
    case list
    case item
    case codeBlock = "code_block"
    case htmlBlock = "html_block"
    case customBlock = "custom_block"
    case paragraph
    case heading
    case thematicBreak = "thematic_break"
    case text
    case softBreak = "softbreak"
    case lineBreak = "linebreak"
    case code
    case html = "html_inline"
    case customInline = "custom_inline"
    case emphasis = "emph"
    case strong
    case link
    case image
    case inlineAttributes = "attribute"
    case none = "NONE"
    case unknown = "<unknown>"

    // Extensions
    case strikethrough
    case table
    case tableHead = "table_header"
    case tableRow = "table_row"
    case tableCell = "table_cell"
    case taskListItem = "tasklist"
}

// MARK: - UnsafeNodeSequence

private struct UnsafeNodeSequence: Sequence {
    struct Iterator: IteratorProtocol {
        private var node: UnsafeNode?

        init(_ node: UnsafeNode?) {
            self.node = node
        }

        mutating func next() -> UnsafeNode? {
            guard let node else { return nil }
            defer { self.node = cmark_node_next(node) }
            return node
        }
    }

    private let node: UnsafeNode?

    init(_ node: UnsafeNode?) {
        self.node = node
    }

    func makeIterator() -> Iterator {
        .init(self.node)
    }
}
