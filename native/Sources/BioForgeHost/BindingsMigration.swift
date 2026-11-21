// The one-time move of the Mac app's saved key bindings from Mac key codes (kVK, written by builds before the host layer) to USB HID usages.
import BioForgeCore
import Foundation

public enum BindingsMigration {
    public static let macKey = "KeyBindings"        // [id: [kVK or -1]] written by builds before the host layer
    public static let key = "KeyBindingsHID"         // [id: [HID usage or -1]]

    /// The saved HID bindings; else the old Mac set converted once (written under `key`, the old entry kept for older builds); else the defaults (nothing written).
    public static func load(_ store: SettingsStore) -> KeyBindings {
        if let saved = store.dictionary(forKey: key) as? [String: [Int]] { return KeyBindings(propertyList: saved) }
        guard let old = store.dictionary(forKey: macKey) as? [String: [Int]] else { return KeyBindings() }
        let migrated = KeyBindings(propertyList: usages(fromMac: old))      // converted first: the initializer's `bind` refuses reserved keys
        store.set(migrated.propertyList, forKey: key)
        return migrated
    }

    /// kVK property list -> HID property list: -1 stays -1, a key with no usage becomes -1.
    public static func usages(fromMac p: [String: [Int]]) -> [String: [Int]] {
        p.mapValues { codes in
            codes.map { code in
                guard code >= 0, let k = UInt16(exactly: code), let usage = MacKeyCodes.usage(forKeyCode: k) else { return -1 }
                return Int(usage)
            }
        }
    }
}
