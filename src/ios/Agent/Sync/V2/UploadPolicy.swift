import Foundation

/// Per-device user preference: which v2 record types this device is
/// allowed to push to iCloud, and the per-file size cap on SessionFile
/// asset content.
///
/// Settings live in UserDefaults so they survive launches and can be
/// flipped from the Settings sheet without restarting the engine.
/// Defaults are permissive — fresh installs sync everything until the
/// user opts out.
///
/// Filtering happens at `ChatStore.markDirty` so disabled types never
/// even enter the dirty queue. Records that are already on iCloud from
/// a prior policy are NOT pulled back; turning a category off only
/// stops new writes.
enum UploadPolicy {

    enum Category: String, CaseIterable {
        case chatSessions          // Session, Message, CompactMarker
        case sessionFiles          // SessionFile (binary attachments)
        case skills                // Skill (and SkillFile if any)
        case providers             // ProviderConfig
        case envVars               // EnvVar
        case memory                // MemoryGlobalV2 + MemoryDailyV2

        /// SQLite record_type values that fall under this category.
        var recordTypes: Set<String> {
            switch self {
            case .chatSessions:
                return ["Session", "SessionV2", "Message", "MessageV2", "CompactMarker", "CompactMarkerV2"]
            case .sessionFiles:
                return ["SessionFile", "SessionFileV2"]
            case .skills:
                return ["Skill", "SkillV2"]
            case .providers:
                return ["ProviderConfig", "ProviderConfigV2"]
            case .envVars:
                return ["EnvVar", "EnvVarV2"]
            case .memory:
                return ["MemoryGlobalV2", "MemoryDailyV2"]
            }
        }

        var defaultsKey: String { "cloudSync.v2.upload.\(rawValue)" }

        /// Display name for the Settings UI.
        var displayName: String {
            switch self {
            case .chatSessions: return "Chat Sessions"
            case .sessionFiles: return "Session Files"
            case .skills:       return "Skills"
            case .providers:    return "Providers"
            case .envVars:      return "Environments"
            case .memory:       return "Memory Files"
            }
        }
    }

    /// Read whether the user has opted IN to syncing a category.
    /// Defaults to true on first read (permissive).
    static func isEnabled(_ cat: Category) -> Bool {
        if UserDefaults.standard.object(forKey: cat.defaultsKey) == nil {
            UserDefaults.standard.set(true, forKey: cat.defaultsKey)
            return true
        }
        return UserDefaults.standard.bool(forKey: cat.defaultsKey)
    }

    static func setEnabled(_ cat: Category, _ enabled: Bool) {
        UserDefaults.standard.set(enabled, forKey: cat.defaultsKey)
    }

    /// Quick lookup: should `markDirty(recordType:)` be allowed through?
    /// SyncDeviceV2 is always allowed (device discovery itself can't be
    /// disabled — without it the device list would never populate).
    static func allowsRecordType(_ recordType: String) -> Bool {
        if recordType == "SyncDevice" || recordType == "SyncDeviceV2" {
            return true
        }
        for cat in Category.allCases where cat.recordTypes.contains(recordType) {
            return isEnabled(cat)
        }
        return true   // unknown types pass through (forward-compat)
    }

    // MARK: - Per-file cap

    /// Max per-file size in bytes that this device is willing to push
    /// for SessionFile asset content. Files above the cap are skipped
    /// at markDirty time. UserDefaults default = 1 MB.
    static let maxFileSizeKey = "cloudSync.v2.upload.maxFileSize"
    static var maxFileSizeBytes: Int {
        get {
            let v = UserDefaults.standard.integer(forKey: maxFileSizeKey)
            return v > 0 ? v : (1 * 1024 * 1024)
        }
        set { UserDefaults.standard.set(newValue, forKey: maxFileSizeKey) }
    }

    /// Comma-joined string of category record-types currently enabled,
    /// used in SyncedDevice.uploadTypes so peers can see what we sync.
    static func currentUploadTypesString() -> String {
        Category.allCases
            .filter { isEnabled($0) }
            .map { $0.rawValue }
            .joined(separator: ",")
    }

    // MARK: - Custom device name

    static let deviceNameKey = "cloudSync.v2.deviceName"
    static var customDeviceName: String? {
        get { UserDefaults.standard.string(forKey: deviceNameKey) }
        set {
            if let s = newValue, !s.isEmpty {
                UserDefaults.standard.set(s, forKey: deviceNameKey)
            } else {
                UserDefaults.standard.removeObject(forKey: deviceNameKey)
            }
        }
    }
}
