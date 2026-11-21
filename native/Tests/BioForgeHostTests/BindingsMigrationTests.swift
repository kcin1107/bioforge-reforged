import BioForgeCore
import Testing
@testable import BioForgeHost

struct BindingsMigrationTests {
    /// The Mac key codes the app saved before the host layer, for the default bindings.
    static let oldDefaults: [String: [Int]] = {
        let codes: [[Int]] = [[126, 91], [125, 84], [123, 86], [124, 88], [115, 89], [116, 92], [119, 83], [121, 85], [56, 60], [8], [0, 59], [58, 61], [44, 87],
                              [49], [36, 76], [35], [34], [2], [38], [31], [1], [37], [15], [7], [9], [43, 78], [47, 69]]
        return Dictionary(uniqueKeysWithValues: zip(KeyBindings.controls.map(\.id), codes))
    }()

    @Test func theOldDefaultsLoadAsTheDefaults() {
        let store = MemoryStore()
        store.set(Self.oldDefaults, forKey: BindingsMigration.macKey)
        #expect(BindingsMigration.load(store) == KeyBindings())
        #expect(store.dictionary(forKey: BindingsMigration.key) as? [String: [Int]] == KeyBindings().propertyList)
        #expect(store.dictionary(forKey: BindingsMigration.macKey) as? [String: [Int]] == Self.oldDefaults, "the old entry stays for older builds")
    }

    @Test func customBindingsConvert() {
        var old = Self.oldDefaults
        old["use"] = [12, -1]                          // Q, nothing
        old["run"] = [57, 56]                          // Caps Lock (reserved), left Shift
        let store = MemoryStore()
        store.set(old, forKey: BindingsMigration.macKey)
        let b = BindingsMigration.load(store)
        #expect(b.key("use", slot: 0) == 0x14 && b.key("use", slot: 1) == nil)
        #expect(b.control(for: 0x14)?.id == "use")
        #expect(b.key("run", slot: 0) == nil && b.key("run", slot: 1) == 0xE1)
        #expect(KeyBindings(propertyList: store.dictionary(forKey: BindingsMigration.key) as! [String: [Int]]) == b)
    }

    @Test func keysWithoutAUsageBecomeUnbound() {
        var old = Self.oldDefaults
        old["use"] = [63, 200]                         // Fn, nothing
        let store = MemoryStore()
        store.set(old, forKey: BindingsMigration.macKey)
        let b = BindingsMigration.load(store)
        #expect(b.key("use", slot: 0) == nil && b.key("use", slot: 1) == nil)
    }

    @Test func migratesOnlyOnce() {
        let store = MemoryStore()
        var hid = KeyBindings()
        hid.bind(0x14, to: "use", slot: 0)
        store.set(hid.propertyList, forKey: BindingsMigration.key)
        var old = Self.oldDefaults
        old["use"] = [0]
        store.set(old, forKey: BindingsMigration.macKey)
        #expect(BindingsMigration.load(store) == hid)
        #expect(store.dictionary(forKey: BindingsMigration.key) as? [String: [Int]] == hid.propertyList)
    }

    @Test func anEmptyStoreGivesTheDefaultsAndWritesNothing() {
        let store = MemoryStore()
        #expect(BindingsMigration.load(store) == KeyBindings())
        #expect(store.object(forKey: BindingsMigration.key) == nil && store.object(forKey: BindingsMigration.macKey) == nil)
    }

    @Test func usagesKeepUnbound() {
        #expect(BindingsMigration.usages(fromMac: ["a": [-1, 126], "b": [63, 300]]) == ["a": [-1, 0x52], "b": [-1, -1]])
    }
}
