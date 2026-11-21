// A SettingsStore kept in one JSON file (HostPaths.settingsFile), for the shells without UserDefaults. Read once at start-up, rewritten whole on every change.
// Values go through a small Codable enum so Bool, Int, String, arrays and dictionaries come back as the same Swift types on every platform.
import BioForgeCore
import Foundation

public final class FileSettingsStore: SettingsStore, @unchecked Sendable {
    private let file: URL
    private let log: HostLog?
    private let memory = MemoryStore()
    private var stored: [String: JSONValue] = [:]
    private let lock = NSLock()

    /// A missing file is an empty store; an unreadable one too (logged, and left alone until the next `set` overwrites it).
    public init(file: URL, log: HostLog? = nil) {
        self.file = file; self.log = log
        guard let data = try? Data(contentsOf: file) else { return }
        do {
            stored = try JSONDecoder().decode([String: JSONValue].self, from: data)
            for (key, value) in stored { memory.set(value.native, forKey: key) }
        } catch {
            log?.error("settings", "Ignoring unreadable \(file.path): \(error)")
        }
    }

    public func object(forKey defaultName: String) -> Any? { memory.object(forKey: defaultName) }
    public func string(forKey defaultName: String) -> String? { memory.string(forKey: defaultName) }
    public func dictionary(forKey defaultName: String) -> [String: Any]? { memory.dictionary(forKey: defaultName) }
    public func integer(forKey defaultName: String) -> Int { memory.integer(forKey: defaultName) }
    public func bool(forKey defaultName: String) -> Bool { memory.bool(forKey: defaultName) }

    public func set(_ value: Any?, forKey defaultName: String) {
        lock.lock(); defer { lock.unlock() }
        var json: JSONValue?
        if let value {
            json = JSONValue(value)
            if json == nil { log?.error("settings", "Not storing \(defaultName): unsupported value type"); return }
        }
        memory.set(value, forKey: defaultName)
        stored[defaultName] = json
        write()
    }

    private func write() {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys, .prettyPrinted]
        do {
            try FileManager.default.createDirectory(at: file.deletingLastPathComponent(), withIntermediateDirectories: true)
            try encoder.encode(stored).write(to: file, options: .atomic)
        } catch {
            log?.error("settings", "Could not write \(file.path): \(error)")
        }
    }
}

private enum JSONValue: Codable, Equatable {
    case bool(Bool), int(Int), string(String), array([JSONValue]), object([String: JSONValue])

    /// nil for a type the store does not keep.
    init?(_ value: Any) {
        switch value {
        case let v as Bool: self = .bool(v)
        case let v as Int: self = .int(v)
        case let v as String: self = .string(v)
        case let v as [Any]:
            let items = v.compactMap(JSONValue.init)
            guard items.count == v.count else { return nil }
            self = .array(items)
        case let v as [String: Any]:
            let items = v.compactMapValues(JSONValue.init)
            guard items.count == v.count else { return nil }
            self = .object(items)
        default: return nil
        }
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.singleValueContainer()
        if let v = try? c.decode(Bool.self) { self = .bool(v) }
        else if let v = try? c.decode(Int.self) { self = .int(v) }
        else if let v = try? c.decode(String.self) { self = .string(v) }
        else if let v = try? c.decode([JSONValue].self) { self = .array(v) }
        else { self = .object(try c.decode([String: JSONValue].self)) }
    }

    func encode(to encoder: Encoder) throws {
        var c = encoder.singleValueContainer()
        switch self {
        case .bool(let v): try c.encode(v)
        case .int(let v): try c.encode(v)
        case .string(let v): try c.encode(v)
        case .array(let v): try c.encode(v)
        case .object(let v): try c.encode(v)
        }
    }

    var native: Any {
        switch self {
        case .bool(let v): return v
        case .int(let v): return v
        case .string(let v): return v
        case .array(let v): return v.map(\.native)
        case .object(let v): return v.mapValues(\.native)
        }
    }
}
