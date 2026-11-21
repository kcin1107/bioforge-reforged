// An in-memory SettingsStore: the tests' stand-in for UserDefaults, and a base for shells without UserDefaults.
import BioForgeCore
import Foundation

public final class MemoryStore: SettingsStore, @unchecked Sendable {
    private var values: [String: Any] = [:]
    public init() {}

    public func object(forKey defaultName: String) -> Any? { values[defaultName] }
    public func string(forKey defaultName: String) -> String? { values[defaultName] as? String }
    public func dictionary(forKey defaultName: String) -> [String: Any]? { values[defaultName] as? [String: Any] }

    /// Like UserDefaults: a number or Bool reads as an Int (a Bool as 0/1), anything else as 0.
    public func integer(forKey defaultName: String) -> Int {
        switch values[defaultName] {
        case let v as Bool: return v ? 1 : 0
        case let v as Int: return v
        case let v as NSNumber: return v.intValue
        default: return 0
        }
    }

    /// Like UserDefaults: a Bool or number reads as true when non-zero, anything else as false.
    public func bool(forKey defaultName: String) -> Bool {
        switch values[defaultName] {
        case let v as Bool: return v
        case let v as Int: return v != 0
        case let v as NSNumber: return v.boolValue
        default: return false
        }
    }

    public func set(_ value: Any?, forKey defaultName: String) { values[defaultName] = value }
}
