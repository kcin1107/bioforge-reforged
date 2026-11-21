import BioForgeCore
import Testing
@testable import BioForgeHost

struct MacKeyCodesTests {
    @Test func theTableIsOneToOne() {
        #expect(MacKeyCodes.toKeyCode.count == MacKeyCodes.toUsage.count)
        for (code, usage) in MacKeyCodes.toUsage { #expect(MacKeyCodes.keyCode(forUsage: usage) == code && MacKeyCodes.usage(forKeyCode: code) == usage) }
    }

    @Test func everyDefaultAndMonitorKeyRoundTrips() {
        for c in KeyBindings.controls {
            for usage in c.defaults { #expect(MacKeyCodes.keyCode(forUsage: usage).flatMap(MacKeyCodes.usage(forKeyCode:)) == usage, "\(c.id) \(usage)") }
        }
        for usage in UInt16(0)...0xFF where MonitorKeys.scan(forUsage: usage) != nil {
            #expect(MacKeyCodes.keyCode(forUsage: usage).flatMap(MacKeyCodes.usage(forKeyCode:)) == usage, "monitor key \(usage)")
        }
    }

    @Test func modifierUsagesAreTheMacFlagKeys() {
        #expect(KeyBindings.modifierUsages == Set([56, 60, 59, 62, 58, 61].map { MacKeyCodes.usage(forKeyCode: $0)! }))
    }

    /// The defaults before the host layer, as Mac key codes, in control order.
    private static let oldDefaults: [[UInt16]] = [[126, 91], [125, 84], [123, 86], [124, 88], [115, 89], [116, 92], [119, 83], [121, 85], [56, 60], [8], [0, 59], [58, 61], [44, 87],
                                                   [49], [36, 76], [35], [34], [2], [38], [31], [1], [37], [15], [7], [9], [43, 78], [47, 69]]

    @Test func hidDefaultsAreTheOldMacDefaultsConverted() {
        #expect(KeyBindings.controls.count == Self.oldDefaults.count)
        for (c, old) in zip(KeyBindings.controls, Self.oldDefaults) { #expect(c.defaults == old.map { MacKeyCodes.usage(forKeyCode: $0) }.map { $0! }, "\(c.id)") }
    }

    /// The old monitor key table (by Mac key code), copied from before the host layer.
    private static let oldMonitor: [UInt16: Int] = {
        var t: [UInt16: Int] = [48: 0x0f, 36: 0x1c, 76: 0x1c, 49: 0x39, 53: 0x01,
                                123: 0x4b, 124: 0x4d, 125: 0x50, 126: 0x48, 115: 0x47, 119: 0x4f, 116: 0x49, 121: 0x51,
                                87: 0x4c, 89: 0x47, 91: 0x48, 92: 0x49, 86: 0x4b, 88: 0x4d, 83: 0x4f, 84: 0x50, 85: 0x51]
        let letters: [(UInt16, Int)] = [(12, 0x10), (13, 0x11), (14, 0x12), (15, 0x13), (17, 0x14), (16, 0x15), (32, 0x16), (34, 0x17), (31, 0x18), (35, 0x19),
                                        (0, 0x1e), (1, 0x1f), (2, 0x20), (3, 0x21), (5, 0x22), (4, 0x23), (38, 0x24), (40, 0x25), (37, 0x26),
                                        (6, 0x2c), (7, 0x2d), (8, 0x2e), (9, 0x2f), (11, 0x30), (45, 0x31), (46, 0x32),
                                        (18, 0x02), (19, 0x03), (20, 0x04), (21, 0x05), (23, 0x06), (22, 0x07), (26, 0x08), (28, 0x09), (25, 0x0a), (29, 0x0b)]
        for (k, s) in letters { t[k] = s }
        return t
    }()

    @Test func monitorKeysAreTheOldTableConverted() {
        let converted = Dictionary(uniqueKeysWithValues: Self.oldMonitor.map { (MacKeyCodes.usage(forKeyCode: $0.key)!, $0.value) })
        for usage in UInt16(0)...0xFF { #expect(MonitorKeys.scan(forUsage: usage) == converted[usage], "usage \(usage)") }
        #expect(converted.count == Self.oldMonitor.count)
    }
}
