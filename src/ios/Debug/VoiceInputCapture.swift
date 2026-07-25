#if DEBUG
import Foundation

/// One captured voice-transcription input: a snapshot of the EXACT audio payload
/// that was about to be sent to the ASR model, taken at the chokepoint just
/// before `transcribe(request)` fires. [T-debug-voice-input-capture]
///
/// This is the *final request payload* audio (16-bit PCM WAV), not a VAD
/// intermediate — so it answers "what did the model actually receive", which is
/// what you need to tell whether VAD trimmed/dropped speech before the request.
final class CapturedVoiceInput {
    let id: String
    let capturedAt: Date
    /// Model id the request carried (nil = provider default).
    let model: String?
    /// Requested language (nil = auto-detect).
    let language: String?
    /// System ASR on-device flag: true=forced offline, false=cloud, nil=auto.
    let onDeviceRecognition: Bool?
    /// Total payload byte count (WAV header + PCM).
    let byteCount: Int
    /// Parsed WAV header. Zero if the payload isn't a parseable RIFF/WAVE.
    let sampleRate: Int
    let channels: Int
    let bitsPerSample: Int
    /// Duration (seconds) derived from the WAV byte rate + data size.
    let durationSeconds: Double

    // VAD context available at the capture point — for diagnosing whether the
    // segmentation cut audio short.
    /// How many VAD segments were merged into this payload.
    let vadSegmentCount: Int
    /// Reason the LAST contributing VAD segment ended (silence / max-length /
    /// manual-flush / raw-fallback), if known.
    let vadEndReason: String?
    /// The VAD's running speech duration at capture time (seconds), if known —
    /// compared against `durationSeconds`, a gap hints at trimming.
    let vadRunningDuration: Double?

    /// The raw audio bytes. Kept in memory only (bounded ring, ≤5 entries), never
    /// persisted. Exposed base64 by the RPC for export/inspection.
    let audioData: Data

    init(audioData: Data,
         model: String?,
         language: String?,
         onDeviceRecognition: Bool?,
         vadSegmentCount: Int,
         vadEndReason: String?,
         vadRunningDuration: Double?) {
        self.id = UUID().uuidString
        self.capturedAt = Date()
        self.model = model
        self.language = language
        self.onDeviceRecognition = onDeviceRecognition
        self.byteCount = audioData.count
        self.audioData = audioData
        self.vadSegmentCount = vadSegmentCount
        self.vadEndReason = vadEndReason
        self.vadRunningDuration = vadRunningDuration

        let hdr = Self.parseWavHeader(audioData)
        self.sampleRate = hdr.sampleRate
        self.channels = hdr.channels
        self.bitsPerSample = hdr.bitsPerSample
        self.durationSeconds = hdr.durationSeconds
    }

    /// Minimal RIFF/WAVE header parse. Standard PCM layout:
    /// channels @22 (u16), sampleRate @24 (u32), byteRate @28 (u32),
    /// bitsPerSample @34 (u16), then a 44-byte header before PCM data.
    static func parseWavHeader(_ wav: Data)
        -> (sampleRate: Int, channels: Int, bitsPerSample: Int, durationSeconds: Double) {
        let headerSize = 44
        guard wav.count >= headerSize,
              wav.starts(with: [0x52, 0x49, 0x46, 0x46]) /* "RIFF" */ else {
            return (0, 0, 0, 0)
        }
        func u16(_ off: Int) -> UInt16 {
            wav.withUnsafeBytes { UInt16(littleEndian: $0.loadUnaligned(fromByteOffset: off, as: UInt16.self)) }
        }
        func u32(_ off: Int) -> UInt32 {
            wav.withUnsafeBytes { UInt32(littleEndian: $0.loadUnaligned(fromByteOffset: off, as: UInt32.self)) }
        }
        let channels = Int(u16(22))
        let sampleRate = Int(u32(24))
        let byteRate = u32(28)
        let bits = Int(u16(34))
        let dataBytes = Double(wav.count - headerSize)
        let duration = byteRate > 0 ? dataBytes / Double(byteRate) : 0
        return (sampleRate, channels, bits, duration)
    }

    func toDict(includeAudio: Bool) -> [String: Any] {
        let tf = ISO8601DateFormatter()
        tf.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        var d: [String: Any] = [
            "id": id,
            "capturedAt": tf.string(from: capturedAt),
            "byteCount": byteCount,
            "durationSeconds": durationSeconds,
            "audioFormat": [
                "container": sampleRate > 0 ? "wav" : "unknown",
                "sampleRate": sampleRate,
                "channels": channels,
                "bitsPerSample": bitsPerSample,
            ] as [String: Any],
            "vad": [
                "segmentCount": vadSegmentCount,
                "endReason": vadEndReason as Any,
                "runningDurationSeconds": vadRunningDuration as Any,
            ] as [String: Any],
        ]
        if let model { d["model"] = model }
        if let language { d["language"] = language }
        if let onDeviceRecognition { d["onDeviceRecognition"] = onDeviceRecognition }
        if includeAudio {
            // base64 WAV — directly saveable to a .wav for playback/inspection.
            d["audioBase64"] = audioData.base64EncodedString()
        }
        return d
    }
}

/// Thread-safe, bounded (last 5) ring of voice-transcription inputs, mirroring
/// `AgentRequestTrace` / `LastAPIRequestBody`. `#if DEBUG` only; no disk, no
/// effect on the realtime transcription path beyond one lock-guarded append.
final class VoiceInputCapture: @unchecked Sendable {
    static let shared = VoiceInputCapture()

    private let lock = NSLock()
    private let maxEntries = 5
    private var _entries: [CapturedVoiceInput] = []

    private init() {}

    /// Snapshot the audio about to be transcribed. Called on the capture-side
    /// path immediately before `transcribe(request)`.
    func record(audioData: Data,
                model: String?,
                language: String?,
                onDeviceRecognition: Bool?,
                vadSegmentCount: Int,
                vadEndReason: String?,
                vadRunningDuration: Double?) {
        let entry = CapturedVoiceInput(
            audioData: audioData,
            model: model,
            language: language,
            onDeviceRecognition: onDeviceRecognition,
            vadSegmentCount: vadSegmentCount,
            vadEndReason: vadEndReason,
            vadRunningDuration: vadRunningDuration
        )
        lock.lock()
        _entries.append(entry)
        if _entries.count > maxEntries {
            _entries.removeFirst(_entries.count - maxEntries)
        }
        lock.unlock()
    }

    /// All captured inputs, newest last.
    func getAll(includeAudio: Bool) -> [[String: Any]] {
        lock.lock()
        defer { lock.unlock() }
        return _entries.map { $0.toDict(includeAudio: includeAudio) }
    }

    func clear() {
        lock.lock()
        _entries.removeAll()
        lock.unlock()
    }
}
#endif
