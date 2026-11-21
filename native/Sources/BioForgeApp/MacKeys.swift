// Mac-only key facts the portable bindings (BioForgeHost.KeyBindings, in HID usages) leave out.
enum MacKeys {
    /// Mac modifier keys: key code (kVK) -> device-dependent bit of NSEvent.modifierFlags (NX_DEVICE*KEYMASK), to tell left from
    /// right on flagsChanged. Caps Lock, Fn and Command are not here (see KeyBindings.reserved).
    static let deviceBits: [UInt16: UInt] = [56: 0x02, 60: 0x04, 59: 0x01, 62: 0x2000, 58: 0x20, 61: 0x40]
}
