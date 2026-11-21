// AdLib music parity with re/formats/adlib.py and opl.py: the AdLib arrangement's MIDI stream through the AIL AdLib driver
// port (register writes stamped with chip samples) and the OPL2 model's output. Hashes from the Python prototype
// (re/formats/test_adlib.py computes the same values).
import Foundation
import Testing
@testable import BioForgeCore

@Suite(.serialized, .enabled(if: game != nil, "BIOFORGE_DATA is not set; point it at the BioForge game folder"))
struct AdLibTests {
    private func sha(_ data: Data) -> String { Sha256.hex(data) }

    private func writes(_ requests: [(Double, Int)], end: Double) throws -> [AdLibSequencer.Write] {
        let game = try requireGame()
        let sequencer = MusicSequencer(library: try MusicLibrary(game: game, arrangement: .adlib))
        for (t, id) in requests { sequencer.request(id, at: t) }
        let events = sequencer.advance(to: end)
        return AdLibSequencer(bank: try AdLibBank(game: game)).advance(events, serving: sequencer.takeServingChanges(), through: end)
    }

    private func digest(_ writes: [AdLibSequencer.Write]) -> String {
        sha(Data(writes.map { String(format: "%d:%02x:%02x\n", $0.sample, $0.register, $0.value) }.joined().utf8))
    }

    @Test func bankInstallsTheTimbresTheSongsList() throws {
        #expect(try AdLibBank(game: requireGame()).count == 80)
    }

    @Test func songRegisterWritesMatchPython() throws {
        let w = try writes([(0, 10), (8, -1)], end: 8)
        #expect(w.count == 607)
        #expect(digest(w) == "89659a959506de4ba655a8513b82c0a0c870b890b6c63b91c3b64d496f0aded0")
        let serves = Set((0...480).map { $0 * OPL2.rate / 60 })
        #expect(w.allSatisfy { serves.contains($0.sample) }, "writes land on the 60 Hz serves")
    }

    @Test func transitionsMatchPython() throws {
        let bar = try writes([(0, 10), (12, 21), (30, -1)], end: 30)
        #expect(bar.count == 3220)
        #expect(digest(bar) == "b3879836e7e9912435feddf83aeab3b1f8238bde6500b894fb60a6644c343975")
        let overlay = try writes([(0, 10), (1, 5), (20, -1)], end: 20)
        #expect(overlay.count == 2426)
        #expect(digest(overlay) == "50083c92cbc04641acad416de1095f0bcc795251b76e60219b62708a4c8b7d8c")
    }

    // test_adlib.test_reused_slot_keeps_its_old_key_on_register_copy: the 0xB0 copy survives a slot's reuse.
    @Test func reusedSlotKeepsItsOldKeyOnRegisterCopy() throws {
        let bank = try AdLibBank(game: requireGame())
        let program = UInt8(bank.timbres.keys.filter { $0 >> 8 == 0 }.min()! & 0xff)
        let driver = AdLibDriver(bank: bank)
        for ch: UInt8 in [1, 2, 3] { driver.send([0xc0 | ch, program]) }
        for k: UInt8 in 0..<9 { driver.send([0x91, 40 + k, 100]) }
        driver.send([0x92, 70, 100])
        let old = driver.writes.last { $0.register == 0xb8 }!.value
        driver.send([0x82, 70, 0])
        driver.send([0xb1, 112, 127])
        driver.send([0x91, 48, 100])
        driver.send([0x93, 60, 100])
        driver.send([0x81, 40, 0])
        driver.writes.removeAll()
        driver.send([0x83, 60, 0])
        #expect(driver.writes.last!.register == 0xb0 && driver.writes.last!.value == old & 0xdf)
        #expect(old & 0xdf != 0)
    }

    // test_adlib.test_serves_only_while_a_song_is_loaded_and_not_paused
    @Test func servesOnlyWhileASongIsLoadedAndNotPaused() throws {
        let game = try requireGame()
        let sequencer = MusicSequencer(library: try MusicLibrary(game: game, arrangement: .adlib))
        for (t, id) in [(1.0, 10), (2.0, -2), (3.0, -3), (4.0, -1)] { sequencer.request(id, at: t) }
        _ = sequencer.advance(to: 5)
        #expect(sequencer.takeServingChanges().map { "\($0.time):\($0.on)" } == ["1.0:true", "2.0:false", "3.0:true", "4.0:false"])
        let bank = try AdLibBank(game: game)
        let program = UInt8(bank.timbres.keys.filter { $0 >> 8 == 0 }.min()! & 0xff)
        var events = [[0xc1, program], [0xc3, program], [0xb1, 112, 127]].map { MusicMIDIEvent(time: 0, bytes: $0) }
        events += (0..<9).map { MusicMIDIEvent(time: 0, bytes: [0x91, 40 + UInt8($0), 100]) }
        events += [MusicMIDIEvent(time: 0, bytes: [0x93, 60, 100]), MusicMIDIEvent(time: 0.05, bytes: [0xb1, 112, 0])]
        func steal(_ serving: [(time: Double, on: Bool)]) -> [Int] {
            let w = AdLibSequencer(bank: bank).advance(events, serving: serving, through: 2).dropFirst(0xf5)
            return Array(w.filter { (0xb0...0xb8).contains($0.register) && $0.value & 0x20 != 0 }.map { $0.sample }.dropFirst(9))
        }
        #expect(steal([(0, true)]) == [23 * OPL2.rate / 60])              // serves 0...23
        #expect(steal([(0, true), (0.1, false), (0.5, true)]) == [47 * OPL2.rate / 60])   // serves 0...5, then 30...47
        #expect(steal([]) == [])
    }

    @Test func chipOutputMatchesPython() throws {
        let w = try writes([(0, 10), (8, -1)], end: 8)
        let chip = OPL2()
        var pcm: [Int16] = [], i = 0
        while pcm.count < OPL2.rate / 2 {
            while i < w.count && w[i].sample <= pcm.count { chip.write(Int(w[i].register), Int(w[i].value)); i += 1 }
            chip.generate(1, into: &pcm)
        }
        #expect(pcm.reduce(0) { $0 + abs(Int($1)) } == 46420190)
        #expect(sha(pcm.withUnsafeBufferPointer { Data(buffer: $0) }) == "4837f5d034909acb3eb3073b6fcc404a47cc07ab63891832e4897e100db81f29")
    }

    @Test func streamRendersWritesAtTheirSamples() throws {
        let w = try writes([(0, 10), (8, -1)], end: 8)
        let stream = OPL2Stream()
        stream.reset(pad: 0)
        stream.push(w)
        let total = OPL2.rate / 2
        var out = [Float](repeating: 0, count: total)
        out.withUnsafeMutableBufferPointer { buffer in
            for start in stride(from: 0, to: total, by: 512) {         // block by block, like the audio thread
                stream.render(into: buffer.baseAddress! + start, count: min(512, total - start))
            }
        }
        #expect(out.reduce(0) { $0 + abs(Int(($1 * 32768).rounded())) } == 46420190)
    }

    // After a stall (a menu held open) every write arrived late and landed at the next block start: the rhythm fell to the 30 Hz tick.
    @Test func streamKeepsTheRhythmAfterAStall() throws {
        let w = try writes([(0, 10), (8, -1)], end: 8)
        let lead = 4617, stall = OPL2.rate, total = stall + lead + OPL2.rate / 2
        // `stall` chip samples render before the first write arrives; the reference is a timeline started that much later
        func render(pad: Int, stall: Int, keepUp: Bool) -> [Float] {
            let stream = OPL2Stream()
            stream.reset(pad: pad)
            var out = [Float](repeating: 0, count: total)
            out.withUnsafeMutableBufferPointer { buffer in
                var start = 0
                func run(to end: Int) { while start < end { let n = min(512, end - start); stream.render(into: buffer.baseAddress! + start, count: n); start += n } }
                run(to: stall)
                if keepUp { stream.keepUp(sample: w[0].sample) }
                stream.push(w)
                run(to: total)
            }
            return out
        }
        let reference = render(pad: stall + lead, stall: stall, keepUp: false)
        #expect(reference.contains { $0 != 0 })
        #expect(render(pad: lead, stall: stall, keepUp: false) != reference, "without keepUp the late writes bunch up at block starts")
        #expect(render(pad: lead, stall: stall, keepUp: true) == reference, "after a stall the song plays as on a timeline started later")
        #expect(render(pad: lead, stall: 0, keepUp: true) == render(pad: lead, stall: 0, keepUp: false), "no stall: keepUp changes nothing")
    }

    @Test func installOptPicksTheMusicDevice() {
        func device(_ text: String) -> MusicArrangement? { Settings(installOpt: text).musicDevice }
        #expect(device("MUSIC=ON\r\nMusicCardId=7\r\n") == .generalMIDI)    // GOG: MPU-401
        #expect(device("MusicCardId=1") == .adlib)
        #expect(device("MusicCardId=3") == .adlib)
        #expect(device("MusicCardId=4") == .generalMIDI)                   // AWE32 driver carries the "MPU" tag
        #expect(device("MUSIC=OFF\r\nMusicCardId=0") == nil)
        #expect(device("") == .generalMIDI)
    }
}
