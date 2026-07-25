#if DEBUG
import Foundation

/// A single step in the agent request pipeline, from user input to HTTP send.
struct AgentTraceStep {
    let timestamp: Date
    let label: String
    let detail: String
}

/// Captures the full lifecycle of a single agent API request for debugging.
final class AgentRequestTraceEntry {
    let id: String
    let startedAt: Date
    var steps: [AgentTraceStep] = []
    var httpRequestBody: String?
    var httpResponseStatus: Int?
    var httpResponseBody: String?
    var error: String?

    init() {
        self.id = UUID().uuidString
        self.startedAt = Date()
    }

    func add(_ label: String, detail: String = "") {
        steps.append(AgentTraceStep(timestamp: Date(), label: label, detail: detail))
    }

    func toDict() -> [String: Any] {
        let tf = ISO8601DateFormatter()
        tf.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return [
            "id": id,
            "startedAt": tf.string(from: startedAt),
            "steps": steps.map { step in
                [
                    "t": tf.string(from: step.timestamp),
                    "ms": Int(step.timestamp.timeIntervalSince(startedAt) * 1000),
                    "label": step.label,
                    "detail": String(step.detail.prefix(4000)),
                ] as [String: Any]
            },
            "httpRequestBody": httpRequestBody.map { String($0.prefix(8000)) } as Any,
            "httpResponseStatus": httpResponseStatus as Any,
            "httpResponseBody": httpResponseBody.map { String($0.prefix(2000)) } as Any,
            "error": error as Any,
        ]
    }
}

/// Thread-safe ring buffer of recent agent request traces.
final class AgentRequestTrace: @unchecked Sendable {
    static let shared = AgentRequestTrace()

    private let lock = NSLock()
    private let maxEntries = 5
    private var _entries: [AgentRequestTraceEntry] = []
    private var _current: AgentRequestTraceEntry?

    /// Start a new trace (called when the agent loop begins an API call).
    @discardableResult
    func begin() -> AgentRequestTraceEntry {
        let entry = AgentRequestTraceEntry()
        lock.lock()
        _current = entry
        lock.unlock()
        return entry
    }

    /// Add a step to the current trace.
    func step(_ label: String, detail: String = "") {
        lock.lock()
        _current?.add(label, detail: detail)
        lock.unlock()
    }

    /// Finish the current trace and archive it.
    func finish(error: String? = nil) {
        lock.lock()
        if let entry = _current {
            entry.error = error
            _entries.append(entry)
            if _entries.count > maxEntries {
                _entries.removeFirst(_entries.count - maxEntries)
            }
            _current = nil
        }
        lock.unlock()
    }

    /// Record HTTP request body on the current trace.
    func setHTTPRequest(_ body: String) {
        lock.lock()
        _current?.httpRequestBody = body
        lock.unlock()
    }

    /// Record HTTP response on the current trace.
    func setHTTPResponse(status: Int, body: String?) {
        lock.lock()
        _current?.httpResponseStatus = status
        _current?.httpResponseBody = body
        lock.unlock()
    }

    /// Get all archived traces (newest last).
    func getAll() -> [[String: Any]] {
        lock.lock()
        defer { lock.unlock() }
        var result = _entries.map { $0.toDict() }
        if let current = _current {
            var d = current.toDict()
            d["inProgress"] = true
            result.append(d)
        }
        return result
    }

    /// Get only the most recent trace.
    func getLast() -> [String: Any]? {
        lock.lock()
        defer { lock.unlock() }
        if let current = _current {
            var d = current.toDict()
            d["inProgress"] = true
            return d
        }
        return _entries.last?.toDict()
    }
}
#endif
