import BioForgeHost
import Foundation
import Testing
@testable import BioForgeSDLShell

/// General MIDI offline: no SDL device and no game data.
struct GMStreamTests {
    private func loaded() throws -> GMStream {
        let gm = GMStream()
        try #require(gm.load(sineSoundFont()) == 2)
        return gm
    }

    /// `frames` stereo frames as left samples only, rendered in blocks of `block`.
    private func render(_ gm: GMStream, frames: Int, block: Int) -> [Float] {
        var out: [Float] = [], buffer = [Float](repeating: 0, count: 2 * block)
        var done = 0
        while done < frames {
            let n = min(block, frames - done)
            buffer.withUnsafeMutableBufferPointer { gm.render(into: $0.baseAddress!, frames: n) }
            out += (0..<n).map { buffer[2 * $0] }
            done += n
        }
        return out
    }

    private func peak(_ x: ArraySlice<Float>) -> Float { x.map(abs).max() ?? 0 }

    @Test(arguments: [512, 22_050]) func aDelayedNoteStartsThatManySamplesLater(block: Int) throws {
        let gm = try loaded()
        gm.send([0xC0, 0], after: 0)
        gm.send([0x90, 69, 127], after: 0.25)
        let out = render(gm, frames: 22_050, block: block)
        #expect(out[..<11_025].allSatisfy { $0 == 0 })
        #expect(peak(out[11_025..<11_025 + 64]) > 1e-3)
    }

    @Test func theDelayCountsFromThePlayhead() throws {
        let gm = try loaded()
        _ = render(gm, frames: 1000, block: 256)
        gm.send([0x90, 69, 127], after: 0.1)
        let out = render(gm, frames: 8000, block: 300)
        #expect(out[..<4410].allSatisfy { $0 == 0 })
        #expect(peak(out[4410..<4410 + 64]) > 1e-3)
    }

    @Test func allNotesOffSilences() throws {
        let gm = try loaded()
        gm.send([0x90, 69, 127], after: 0)
        let on = render(gm, frames: 4410, block: 512)
        #expect(peak(on[...]) > 0.1)
        gm.send([0xB0, 123, 0], after: 0)
        let out = render(gm, frames: 22_050, block: 512)
        #expect(out.suffix(4410).allSatisfy { $0 == 0 })
    }

    @Test func drumChannelUsesBank128() throws {
        let gm = try loaded()
        gm.send([0x90, 69, 127], after: 0)
        let melodic = peak(render(gm, frames: 4410, block: 512)[...])
        let silent = try loaded()
        silent.send([0x99, 69, 127], after: 0)
        let drums = peak(render(silent, frames: 4410, block: 512)[...])
        #expect(melodic > 0.1 && drums > 0 && drums < melodic / 2)
    }

    @Test func withoutASoundFontItRendersSilence() {
        let gm = GMStream()
        #expect(!gm.isLoaded)
        gm.send([0x90, 69, 127], after: 0)
        #expect(render(gm, frames: 4410, block: 512).allSatisfy { $0 == 0 })
    }

    @Test func aFileThatIsNotASoundFontIsRefused() {
        let gm = GMStream()
        #expect(gm.load(Data("RIFF....WAVEfmt  nothing to hear".utf8)) == nil)
        #expect(gm.load(Data()) == nil)
        var truncated = sineSoundFont()
        truncated.removeLast(truncated.count / 2)
        #expect(gm.load(truncated) == nil)
        #expect(!gm.isLoaded)
    }

    @Test func theOrderIsKept() throws {
        let gm = try loaded()
        gm.send([0x90, 69, 127], after: 0.2)
        gm.send([0x80, 69, 0], after: 0.1)                    // asked to come sooner, but plays after the note it ends
        let out = render(gm, frames: 44_100, block: 512)
        #expect(peak(out[8820..<8820 + 200]) > 0)
        #expect(out.suffix(4410).allSatisfy { $0 == 0 })       // the note was ended: it did not sustain
    }

    @Test func resetCutsTheNotesAndDropsTheQueue() throws {
        let gm = try loaded()
        gm.send([0x90, 69, 127], after: 0)
        gm.send([0x90, 72, 127], after: 0.5)
        _ = render(gm, frames: 1000, block: 512)
        gm.reset()
        let out = render(gm, frames: 30_000, block: 512)
        #expect(out.suffix(10_000).allSatisfy { $0 == 0 })
        gm.send([0x90, 69, 127], after: 0)                    // the channels still work after a reset
        #expect(peak(render(gm, frames: 4410, block: 512)[...]) > 0.1)
    }

    @Test func theSearchOrder() throws {
        let fm = FileManager.default
        let root = fm.temporaryDirectory.appendingPathComponent("BioForgeSoundFonts-\(UUID().uuidString)", isDirectory: true)
        defer { try? fm.removeItem(at: root) }
        func file(_ path: String) throws -> URL {
            let url = root.appendingPathComponent(path)
            try fm.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
            fm.createFile(atPath: url.path, contents: Data("x".utf8))
            return url
        }
        let chosen = try file("elsewhere/chosen.sf2"), support = root.appendingPathComponent("support", isDirectory: true)
        let inSupport = try file("support/B.SF2"), program = try file("program/p.sf2"), system = try file("system/default.sf2")
        _ = try file("support/a.txt"); _ = try file("support/c.sf3")
        let search = SoundFontSearch(programFolders: [root.appendingPathComponent("program", isDirectory: true)], system: [root.appendingPathComponent("none.sf2").path, system.path])
        let store = MemoryStore()
        store.set(chosen.path, forKey: SoundFontSearch.settingKey)
        #expect(search.find(store: store, support: support) == chosen)
        store.set(root.appendingPathComponent("gone.sf2").path, forKey: SoundFontSearch.settingKey)       // a setting that points nowhere is skipped
        #expect(search.find(store: store, support: support)?.path == inSupport.path)
        try fm.removeItem(at: inSupport)
        #expect(search.find(store: store, support: support)?.path == program.path)
        try fm.removeItem(at: program)
        #expect(search.find(store: store, support: support)?.path == system.path)
        try fm.removeItem(at: system)
        #expect(search.find(store: store, support: support) == nil)
        #expect(SoundFontSearch.none.find(store: store, support: support) == nil)
    }
}
