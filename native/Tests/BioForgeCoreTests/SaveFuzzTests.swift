// Corrupt saves must fail with an error, never trap: the app shows the error (World.fileError) and keeps running.
// SAVE_FUZZ=<n> runs n mutations of a real save (flipped bytes, cut files) through Im1.unpack and GameSession.fromNativeState, and runs
// a few ticks of any that loads; the default is a short run. Each case prints its number first, so a trap names the case that caused it.

import Foundation
import Testing
@testable import BioForgeCore

@Suite struct SaveFuzzTests {
    @Test func corruptSavesFailWithAnErrorNotACrash() throws {
        let res = try #require(worldResources)
        let n = ProcessInfo.processInfo.environment["SAVE_FUZZ"].flatMap { Int($0) } ?? 40
        let dir = tempDir()
        defer { try? FileManager.default.removeItem(at: dir) }
        let s = try GameSession(resources: res, level: "CHAOS")
        for _ in 0..<40 { s.tick() }
        s.world.savesDir = dir
        let im1URL = try #require(s.world.saveNative(slot: 1))
        let im1 = [UInt8](try Data(contentsOf: im1URL))
        let good = dir.appendingPathComponent("GAME1.d")
        try Im1.unpack(im1, to: good)
        let files = try FileManager.default.contentsOfDirectory(atPath: good.path).sorted()
        var rng = SplitMix(seed: 1)
        for i in 0..<n {
            FileHandle.standardError.write("save fuzz case \(i)\n".data(using: .utf8)!)
            let out = dir.appendingPathComponent("case.d")
            try? FileManager.default.removeItem(at: out)
            if i % 4 == 0 {                                         // the packed file itself
                try? Im1.unpack(mutate(im1, &rng), to: out)
                guard FileManager.default.fileExists(atPath: out.path) else { continue }
            } else {                                                // one unpacked file
                try FileManager.default.copyItem(at: good, to: out)
                let name = files[Int(rng.next() % UInt64(files.count))], url = out.appendingPathComponent(name)
                try Data(mutate([UInt8](try Data(contentsOf: url)), &rng)).write(to: url)
            }
            if let g = try? GameSession.fromNativeState(resources: res, directory: out) {
                for _ in 0..<5 { g.tick() }                         // a state that loads must also run
                var fb = Framebuffer()
                g.world.render(into: &fb)
            }
        }
    }

    /// A few flipped bytes, a cut, or a run of 0xFF over a length field.
    private func mutate(_ b: [UInt8], _ rng: inout SplitMix) -> [UInt8] {
        var b = b
        guard !b.isEmpty else { return b }
        switch rng.next() % 3 {
        case 0: for _ in 0..<(1 + Int(rng.next() % 8)) { b[Int(rng.next() % UInt64(b.count))] = UInt8(truncatingIfNeeded: rng.next()) }
        case 1: b = Array(b.prefix(Int(rng.next() % UInt64(b.count))))
        default:
            let at = Int(rng.next() % UInt64(b.count))
            for k in at..<min(b.count, at + 1 + Int(rng.next() % 4)) { b[k] = 0xff }
        }
        return b
    }
}

struct SplitMix {
    var state: UInt64
    init(seed: UInt64) { state = seed }
    mutating func next() -> UInt64 {
        state &+= 0x9e3779b97f4a7c15
        var z = state
        z = (z ^ (z >> 30)) &* 0xbf58476d1ce4e5b9
        z = (z ^ (z >> 27)) &* 0x94d049bb133111eb
        return z ^ (z >> 31)
    }
}
