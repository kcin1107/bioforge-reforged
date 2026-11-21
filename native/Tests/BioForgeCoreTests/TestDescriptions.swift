// One-line descriptions for the objects the tests capture. A failing #expect / #require prints every value it captured with Swift's
// reflection, and for a World, a GameSession or the GameResources that is the whole object graph (one failing test wrote 347 MB).
import Testing
@testable import BioForgeCore

// The expansion lists the Mirror children of every captured value too, so each type also gets an empty customMirror.

extension GameResources: CustomTestStringConvertible, CustomReflectable {
    public var customMirror: Mirror { Mirror(self, children: []) }
    public var testDescription: String { "GameResources" }
}

extension World: CustomTestStringConvertible, CustomReflectable {
    public var customMirror: Mirror { Mirror(self, children: []) }
    public var testDescription: String {
        "World(level: \(level), tick: \(tick), camera: \(currentCamera ?? "-"), figures: \(figures.keys.count), items: \(items.keys.count))"
    }
}

extension GameSession: CustomTestStringConvertible, CustomReflectable {
    public var customMirror: Mirror { Mirror(self, children: []) }
    public var testDescription: String { "GameSession(\(world.testDescription))" }
}

extension ScriptVM: CustomTestStringConvertible, CustomReflectable {
    public var customMirror: Mirror { Mirror(self, children: []) }
    public var testDescription: String { "ScriptVM(tick: \(tick), processes: \(processes.count))" }
}

extension ScriptProcess: CustomTestStringConvertible, CustomReflectable {
    public var customMirror: Mirror { Mirror(self, children: []) }
    public var testDescription: String { "ScriptProcess(#\(handle) \(block.name), pc: \(pc), done: \(done))" }
}

extension Figure: CustomTestStringConvertible, CustomReflectable {
    public var customMirror: Mirror { Mirror(self, children: []) }
    public var testDescription: String { "Figure(\(name) \(type), motion: \(motion ?? "-"), pos: \(pos.map { "\($0.x), \($0.y), \($0.z)" } ?? "-"))" }
}

extension Item: CustomTestStringConvertible, CustomReflectable {
    public var customMirror: Mirror { Mirror(self, children: []) }
    public var testDescription: String { "Item(\(name) \(type), owner: \(owner ?? "-"), slot: \(slot ?? "-"))" }
}

extension MonitorScreen: CustomTestStringConvertible, CustomReflectable {
    public var customMirror: Mirror { Mirror(self, children: []) }
    public var testDescription: String { "MonitorScreen(\(name))" }
}

extension Options: CustomTestStringConvertible, CustomReflectable {
    public var customMirror: Mirror { Mirror(self, children: []) }
    public var testDescription: String { "Options(screen: \(screen), closed: \(closed))" }
}

extension Framebuffer: CustomTestStringConvertible, CustomReflectable {
    public var customMirror: Mirror { Mirror(self, children: []) }
    public var testDescription: String { "Framebuffer(\(Framebuffer.width)x\(Framebuffer.height), sha: \(sha(pixels).prefix(12)))" }
}

extension Run: CustomTestStringConvertible, CustomReflectable {
    var customMirror: Mirror { Mirror(self, children: []) }
    var testDescription: String { "Run(\(world.testDescription))" }
}

extension LevelIndex: CustomTestStringConvertible, CustomReflectable {
    public var customMirror: Mirror { Mirror(self, children: []) }
    public var testDescription: String { "LevelIndex(\(levels.count) levels)" }
}
