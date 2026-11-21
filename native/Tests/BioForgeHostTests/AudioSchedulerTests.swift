@testable import BioForgeCore
import Foundation
import Testing
@testable import BioForgeHost

/// Records every MIDI message the scheduler sends.
final class RecordingSynth: MIDISynth {
    var messages: [[UInt8]] = [], delays: [Double] = []
    func send(_ bytes: [UInt8], after seconds: Double) { messages.append(bytes); delays.append(seconds) }
    var digest: String { Sha256.hex(messages.flatMap { [UInt8($0.count)] + $0 }) }
    static func isNoteOn(_ m: [UInt8]) -> Bool { m[0] & 0xf0 == 0x90 && m.count > 2 && m[2] > 0 }
}

struct SilentLog: HostLog {
    func info(_ category: String, _ message: String) {}
    func error(_ category: String, _ message: String) {}
}

private func quantized(_ samples: [Float]) -> String {
    var bytes: [UInt8] = []
    bytes.reserveCapacity(samples.count * 2)
    for f in samples { let v = Int16(max(-32768, min(32767, (f * 32768).rounded()))); bytes += [UInt8(truncatingIfNeeded: v), UInt8(truncatingIfNeeded: v >> 8)] }
    return Sha256.hex(bytes)
}

private func hexOf(_ pcm: [Int16]) -> String { Sha256.hex(pcm.flatMap { [UInt8(truncatingIfNeeded: $0), UInt8(truncatingIfNeeded: $0 >> 8)] }) }

/// A new game with its scheduler, as the app starts one.
@MainActor private func start(_ device: MusicArrangement?) throws -> (session: GameSession, scheduler: AudioScheduler, synth: RecordingSynth) {
    let session = try GameSession.newGame(resources: try #require(hostResources))
    let synth = RecordingSynth()
    let scheduler = AudioScheduler(synth: synth, log: SilentLog())
    scheduler.newGame(game: try #require(hostGame), musicLevel: session.world.musicInitial, device: device)
    return (session, scheduler, synth)
}

@MainActor
@Suite(.enabled(if: hostGame != nil, "BIOFORGE_DATA is not set; point it at the BioForge game folder"), .serialized)
struct AudioSchedulerTests {
    // Each pinned digest below was produced once by the scheduler as moved out of SoundOutput (the Mac's code before this change).

    @Test func generalMIDISendsNotes() throws {
        let (s, sched, synth) = try start(.generalMIDI)
        for _ in 0..<900 { s.tick(); sched.sync(s.world) }
        #expect(synth.messages.contains(where: RecordingSynth.isNoteOn))
        #expect(synth.digest == "583d80e8d5c607328f5f2576277e9f7b8aa588bfb6ef3aaf760a0d220b99d538")
    }

    // GM messages used to go to the synth when the 30 Hz tick produced them; now each sounds at lead + (its 120 Hz time - the tick's time).
    @Test func generalMIDIKeepsItsPlaceInsideTheTick() throws {
        let (s, sched, synth) = try start(.generalMIDI)
        for _ in 0..<900 { s.tick(); sched.sync(s.world) }
        let notes = synth.messages.indices.filter { RecordingSynth.isNoteOn(synth.messages[$0]) }.map { synth.delays[$0] }
        #expect(!notes.isEmpty)
        #expect(notes.allSatisfy { $0 >= AudioScheduler.lead - 1.0 / 30 - 1e-9 && $0 <= AudioScheduler.lead + 1e-9 })
        #expect(Set(notes).count > 4, "notes are spread over the tick, not all at its end")
    }

    @Test func adLibRendersTheOPL2Stream() throws {
        let (s, sched, synth) = try start(.adlib)
        for _ in 0..<900 { s.tick(); sched.sync(s.world) }
        #expect(synth.messages.allSatisfy { $0 == [0xB0 | $0[0] & 0x0f, 123, 0] }, "the GM synth gets only the silence messages")
        var out: [Float] = []
        var left = 900 * OPL2.rate / 30 + AudioScheduler.pad * OPL2.rate / SoundMixer.rate
        while left > 0 {
            let n = min(4096, left)
            var chunk = [Float](repeating: 0, count: n)
            chunk.withUnsafeMutableBufferPointer { sched.opl.render(into: $0.baseAddress!, count: n) }
            out += chunk; left -= n
        }
        #expect(out.contains { $0 != 0 })
        #expect(quantized(out) == "cef09a086bb955e925727654a8ee8e0d527f60305a072e94f5adfb4d5a165575")
    }

    private func effects(stall: ClosedRange<Int>?) throws -> String {
        let (s, sched, _) = try start(.generalMIDI)
        var pcm: [Int16] = []
        for t in 0..<900 {
            s.tick(); sched.sync(s.world)
            if let stall, stall.contains(t) { continue }               // the render thread stops pulling: keepUp has to catch the mixer up
            var chunk = [Int16](repeating: 0, count: SoundMixer.rate / 30)
            chunk.withUnsafeMutableBufferPointer { sched.mixer.render(into: $0) }
            pcm += chunk
        }
        #expect(pcm.contains { $0 != 0 })
        return hexOf(pcm)
    }

    @Test func effectsInPaceWithTheTicks() throws { #expect(try effects(stall: nil) == "43a5a0c66369c54693f3cb5041a0451ffc73beac10b8398c26d58dfeeb99af89") }

    @Test func effectsAfterAStall() throws {
        let stalled = try effects(stall: 300...400)
        #expect(stalled == "7f1bcd0c1e9e4e97ac22eab2c0cb96abacb7be7e41c042a7cc1400c7a7cdc801")
        #expect(stalled != (try effects(stall: nil)))
    }

    @Test func switchingDeviceReplaysWithoutNotesThenPlays() throws {
        let (s, sched, synth) = try start(.adlib)
        for _ in 0..<600 { s.tick(); sched.sync(s.world) }
        let before = synth.messages.count
        sched.setMusicDevice(.generalMIDI, world: s.world)
        let during = Array(synth.messages[before...])
        #expect(!during.contains(where: RecordingSynth.isNoteOn))
        #expect(during.count >= 16)                                    // at least the all-notes-off messages
        for _ in 0..<300 { s.tick(); sched.sync(s.world) }
        #expect(synth.messages[(before + during.count)...].contains(where: RecordingSynth.isNoteOn))
    }

    @Test func stopSilencesAllSixteenChannels() throws {
        let (_, sched, synth) = try start(.generalMIDI)
        synth.messages = []
        sched.stop()
        #expect(synth.messages == (0..<16).map { [UInt8(0xB0 | $0), 123, 0] })
    }

    /// At equal ticks the script's request comes before the options dialog's level change (musicseq.sequence): the scheduler's bytes match a
    /// sequencer fed in that order, and differ from one fed the other way round.
    @Test func requestsComeBeforeLevelChangesAtEqualTicks() throws {
        let (probe, probeSched, _) = try start(.generalMIDI)
        for _ in 0..<900 { probe.tick(); probeSched.sync(probe.world) }
        let ids = probe.world.musicLog.compactMap { entry -> Int? in if case .int(let n) = entry.value { n } else { nil } }
        let (s, sched, synth) = try start(.generalMIDI)
        for _ in 0..<30 { s.tick() }
        let now = Double(s.world.vm?.tick ?? 0) / 30
        // a song from tick 0, then a stop and a level change at tick 15: stop first starts the options music, the other order does not
        func reference(_ id: Int, requestFirst: Bool) throws -> [[UInt8]] {
            let m = MusicSequencer(library: try MusicLibrary(game: try #require(hostGame), arrangement: .generalMIDI), volume: 100)
            m.request(id, at: 0)
            if requestFirst { m.request(-1, at: 0.5); m.setVolume(40, at: 0.5) } else { m.setVolume(40, at: 0.5); m.request(-1, at: 0.5) }
            return m.advance(to: now).map(\.bytes).filter { $0.count >= 2 }
        }
        let id = try #require(try ids.first { try reference($0, requestFirst: true) != reference($0, requestFirst: false) })
        synth.messages = []
        s.world.musicLog = [(tick: 0, value: .int(id)), (tick: 15, value: .int(-1))]
        s.world.musicVolLog = [(tick: 15, music: 40)]
        sched.sync(s.world)
        #expect(synth.messages.filter { $0.count >= 2 } == (try reference(id, requestFirst: true)))
    }
}
