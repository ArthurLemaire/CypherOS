import SwiftMath
import UIKit

private let logger = AppLogger(category: "SwiftMathRenderer")

/// Renders LaTeX math formulas to UIImage using SwiftMath (pure native, no WebView).
enum SwiftMathRenderer {

    /// LRU-style cache keyed by "D:<latex>" or "I:<latex>".
    private static let cache = NSCache<NSString, SwiftMathRenderResult>()
    private static let cacheSetup: Void = { cache.countLimit = 256 }()

    /// Render a LaTeX formula synchronously. Returns nil on parse error.
    static func render(latex: String, displayMode: Bool, fontSize: CGFloat = 17) -> SwiftMathRenderResult? {
        _ = cacheSetup

        let key = cacheKey(latex: latex, displayMode: displayMode, fontSize: fontSize) as NSString
        if let cached = cache.object(forKey: key) {
            return cached
        }

        let preprocessed = preprocessLatex(latex)

        // Use MTMathUILabel for rendering — more reliable on iOS 18 than MTMathImage.
        let label = MTMathUILabel()
        label.latex = preprocessed
        label.fontSize = fontSize
        label.textColor = UIColor.label
        label.labelMode = displayMode ? .display : .text
        label.textAlignment = displayMode ? .center : .left
        label.backgroundColor = .clear

        // Check for parse errors before rendering.
        if let error = label.error {
            logger.warning("parse error for '\(latex.prefix(60))': \(error.localizedDescription)")
            return nil
        }

        // Force layout to get intrinsic size.
        label.sizeToFit()
        let size = label.intrinsicContentSize
        guard size.width > 0, size.height > 0 else {
            logger.warning("zero size for '\(latex.prefix(60))'")
            return nil
        }

        // Add horizontal padding — MTMathUILabel.intrinsicContentSize sometimes
        // underreports width, causing inline formulas to overlap with following text.
        let hPad: CGFloat = 4
        let pixelSize = CGSize(width: ceil(size.width + hPad), height: ceil(size.height))
        label.frame = CGRect(origin: .zero, size: pixelSize)

        // Render the label to an image.
        // MTMathUILabel draws in a flipped CG coordinate system, so
        // we flip the context before rendering via the CALayer.
        let renderer = UIGraphicsImageRenderer(size: pixelSize)
        let image = renderer.image { ctx in
            let cgCtx = ctx.cgContext
            cgCtx.saveGState()
            cgCtx.translateBy(x: 0, y: pixelSize.height)
            cgCtx.scaleBy(x: 1, y: -1)
            label.layer.render(in: cgCtx)
            cgCtx.restoreGState()
        }

        let result = SwiftMathRenderResult(image: image, size: pixelSize)
        cache.setObject(result, forKey: key)
        return result
    }

    // MARK: - Internal

    private static func cacheKey(latex: String, displayMode: Bool, fontSize: CGFloat) -> String {
        (displayMode ? "D:" : "I:") + "\(Int(fontSize)):" + latex
    }

    /// Normalize LaTeX commands that SwiftMath doesn't support well.
    private static func preprocessLatex(_ latex: String) -> String {
        var s = latex
            .trimmingCharacters(in: .whitespacesAndNewlines)

        s = s.replacingOccurrences(of: "\\dots", with: "\\ldots")
        s = s.replacingOccurrences(of: "\\implies", with: "\\Rightarrow")
        s = s.replacingOccurrences(of: "\\iff", with: "\\Leftrightarrow")
        s = s.replacingOccurrences(of: "\\dfrac", with: "\\frac")
        s = s.replacingOccurrences(of: "\\tfrac", with: "\\frac")
        s = s.replacingOccurrences(of: "\\begin{align}", with: "\\begin{aligned}")
        s = s.replacingOccurrences(of: "\\end{align}", with: "\\end{aligned}")
        s = s.replacingOccurrences(of: "\\begin{align*}", with: "\\begin{aligned}")
        s = s.replacingOccurrences(of: "\\end{align*}", with: "\\end{aligned}")
        s = s.replacingOccurrences(of: "\\begin{gather}", with: "\\begin{gathered}")
        s = s.replacingOccurrences(of: "\\end{gather}", with: "\\end{gathered}")
        s = s.replacingOccurrences(of: "\\begin{gather*}", with: "\\begin{gathered}")
        s = s.replacingOccurrences(of: "\\end{gather*}", with: "\\end{gathered}")
        s = s.replacingOccurrences(of: "\\text{", with: "\\mathrm{")
        s = s.replacingOccurrences(of: "\\textbf{", with: "\\mathbf{")
        s = s.replacingOccurrences(of: "\\operatorname{", with: "\\mathrm{")
        s = s.replacingOccurrences(of: "\\bold{", with: "\\mathbf{")
        s = s.replacingOccurrences(of: "\\displaystyle", with: "")

        return s
    }

    // MARK: - Unicode Fallback

    /// Render a LaTeX formula to UIImage by converting to Unicode text
    /// and drawing with the system font. Handles CJK inside \text{} and
    /// common math operators that SwiftMath's Latin Modern font can't show.
    static func renderFallback(latex: String, displayMode: Bool, fontSize: CGFloat = 17) -> SwiftMathRenderResult? {
        let key = ("F:" + cacheKey(latex: latex, displayMode: displayMode, fontSize: fontSize)) as NSString
        if let cached = cache.object(forKey: key) { return cached }

        let unicode = latexToUnicode(latex)
        guard !unicode.isEmpty else { return nil }

        let textFont = UIFont.systemFont(ofSize: fontSize)
        let mathFont = UIFont(name: "STIXTwoMath-Regular", size: fontSize) ?? textFont
        let boldFont = UIFont.boldSystemFont(ofSize: fontSize)

        let attributed = buildAttributedString(unicode, textFont: textFont, mathFont: mathFont, boldFont: boldFont)
        guard attributed.length > 0 else { return nil }

        let constraintWidth: CGFloat = displayMode ? 600 : 2000
        let boundingRect = attributed.boundingRect(
            with: CGSize(width: constraintWidth, height: .greatestFiniteMagnitude),
            options: [.usesLineFragmentOrigin, .usesFontLeading],
            context: nil
        )
        let pixelSize = CGSize(width: ceil(boundingRect.width) + 4, height: ceil(boundingRect.height) + 2)
        guard pixelSize.width > 0, pixelSize.height > 0 else { return nil }

        let renderer = UIGraphicsImageRenderer(size: pixelSize)
        let image = renderer.image { _ in
            attributed.draw(in: CGRect(origin: CGPoint(x: 2, y: 1), size: boundingRect.size))
        }
        let result = SwiftMathRenderResult(image: image, size: pixelSize)
        cache.setObject(result, forKey: key)
        return result
    }

    private static func buildAttributedString(_ text: String, textFont: UIFont, mathFont: UIFont, boldFont: UIFont) -> NSAttributedString {
        let result = NSMutableAttributedString()
        let textColor = UIColor.label
        for ch in text.unicodeScalars {
            let s = String(ch)
            let font: UIFont
            if ch.properties.isAlphabetic && !ch.properties.isMath {
                font = textFont
            } else {
                font = mathFont
            }
            result.append(NSAttributedString(string: s, attributes: [.font: font, .foregroundColor: textColor]))
        }
        return result
    }

    /// Convert common LaTeX to Unicode text. Not exhaustive — covers the
    /// operators, Greek letters, and \text{} that appear in everyday formulas.
    private static func latexToUnicode(_ latex: String) -> String {
        var s = latex.trimmingCharacters(in: .whitespacesAndNewlines)

        // Strip \text{...} / \textbf{...} / \mathrm{...} / \operatorname{...} wrappers, keep content
        let textPattern = try! NSRegularExpression(pattern: #"\\(?:text|textbf|mathrm|operatorname|mathbf|bold)\{([^}]*)\}"#)
        s = textPattern.stringByReplacingMatches(in: s, range: NSRange(s.startIndex..., in: s), withTemplate: "$1")

        // \frac{a}{b} → a/b
        let fracPattern = try! NSRegularExpression(pattern: #"\\(?:frac|dfrac|tfrac)\{([^}]*)\}\{([^}]*)\}"#)
        s = fracPattern.stringByReplacingMatches(in: s, range: NSRange(s.startIndex..., in: s), withTemplate: "$1/$2")

        // \sqrt{x} → √x
        let sqrtPattern = try! NSRegularExpression(pattern: #"\\sqrt\{([^}]*)\}"#)
        s = sqrtPattern.stringByReplacingMatches(in: s, range: NSRange(s.startIndex..., in: s), withTemplate: "√($1)")

        let replacements: [(String, String)] = [
            ("\\div", "÷"), ("\\times", "×"), ("\\cdot", "·"),
            ("\\pm", "±"), ("\\mp", "∓"), ("\\leq", "≤"), ("\\geq", "≥"),
            ("\\neq", "≠"), ("\\approx", "≈"), ("\\equiv", "≡"),
            ("\\infty", "∞"), ("\\sum", "∑"), ("\\prod", "∏"),
            ("\\int", "∫"), ("\\partial", "∂"), ("\\nabla", "∇"),
            ("\\forall", "∀"), ("\\exists", "∃"),
            ("\\in", "∈"), ("\\notin", "∉"), ("\\subset", "⊂"), ("\\supset", "⊃"),
            ("\\cup", "∪"), ("\\cap", "∩"),
            ("\\to", "→"), ("\\rightarrow", "→"), ("\\leftarrow", "←"),
            ("\\Rightarrow", "⇒"), ("\\Leftarrow", "⇐"), ("\\Leftrightarrow", "⇔"),
            ("\\implies", "⇒"), ("\\iff", "⇔"),
            ("\\ldots", "…"), ("\\cdots", "⋯"), ("\\vdots", "⋮"),
            ("\\alpha", "α"), ("\\beta", "β"), ("\\gamma", "γ"), ("\\delta", "δ"),
            ("\\epsilon", "ε"), ("\\zeta", "ζ"), ("\\eta", "η"), ("\\theta", "θ"),
            ("\\iota", "ι"), ("\\kappa", "κ"), ("\\lambda", "λ"), ("\\mu", "μ"),
            ("\\nu", "ν"), ("\\xi", "ξ"), ("\\pi", "π"), ("\\rho", "ρ"),
            ("\\sigma", "σ"), ("\\tau", "τ"), ("\\upsilon", "υ"), ("\\phi", "φ"),
            ("\\chi", "χ"), ("\\psi", "ψ"), ("\\omega", "ω"),
            ("\\Gamma", "Γ"), ("\\Delta", "Δ"), ("\\Theta", "Θ"), ("\\Lambda", "Λ"),
            ("\\Xi", "Ξ"), ("\\Pi", "Π"), ("\\Sigma", "Σ"), ("\\Phi", "Φ"),
            ("\\Psi", "Ψ"), ("\\Omega", "Ω"),
            ("\\quad", "  "), ("\\qquad", "    "), ("\\,", " "),
            ("\\;", " "), ("\\!", ""),
            ("\\displaystyle", ""), ("\\left", ""), ("\\right", ""),
            ("\\big", ""), ("\\Big", ""), ("\\bigg", ""), ("\\Bigg", ""),
        ]
        for (cmd, repl) in replacements {
            s = s.replacingOccurrences(of: cmd, with: repl)
        }

        // Strip remaining \command sequences (e.g. \mathrm, \mathbf without braces)
        let cmdPattern = try! NSRegularExpression(pattern: #"\\[a-zA-Z]+"#)
        s = cmdPattern.stringByReplacingMatches(in: s, range: NSRange(s.startIndex..., in: s), withTemplate: "")

        // Clean up braces and extra whitespace
        s = s.replacingOccurrences(of: "{", with: "")
        s = s.replacingOccurrences(of: "}", with: "")
        s = s.replacingOccurrences(of: "^", with: "^")
        s = s.replacingOccurrences(of: "_", with: "_")

        let multiSpace = try! NSRegularExpression(pattern: #" {3,}"#)
        s = multiSpace.stringByReplacingMatches(in: s, range: NSRange(s.startIndex..., in: s), withTemplate: "  ")

        return s.trimmingCharacters(in: .whitespacesAndNewlines)
    }
}

// MARK: - Render Result

final class SwiftMathRenderResult: NSObject {
    let image: UIImage
    let size: CGSize

    init(image: UIImage, size: CGSize) {
        self.image = image
        self.size = size
    }
}
