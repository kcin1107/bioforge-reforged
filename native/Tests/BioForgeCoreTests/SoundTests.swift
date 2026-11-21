// Stage 4a sound-effect tests: sample PCM decode (SHA-256 of all 717 E samples), the offline mix of the 1100-tick boot against
// movie.mix_audio (fixtures.json "stage3b": runs[boot].audio, sounds.pcm), and live == offline: the same boot mixed incrementally
// (World synced and one tick = 735 frames rendered per game tick, as the app does) and a synthetic event list rendered in odd
// block sizes must equal the one-shot offline render sample for sample.
import Foundation
import Testing
@testable import BioForgeCore

@Suite(.serialized, .enabled(if: game != nil, "BIOFORGE_DATA is not set; point it at the BioForge game folder"))
struct SoundTests {
    @Test func samplePCM() throws {
        let bank = try #require(worldResources).sounds
        expectDigest(bank.samples.map { row($0.index, sha(bank.pcm($0.index).map { UInt8(bitPattern: $0) })) }, (stage3b["sounds"] as! JSON)["pcm"], "sample PCM")
    }

    @Test func bootMixMatchesPrototype() throws {
        let r = try Run(level: "TITLE", boot: true, toAnchor: false)
        let live = SoundMixer(origin: 2048)                // live-style: events arrive per tick, the timeline starts a latency pad late
        var liveOut: [Int16] = []
        var after = -1                                     // ticks after the first CHAOS LOADLEVEL: the intro plays first
        while after < 1100 && r.vm.tick < 40_000 {
            r.tick(1)
            if !r.world.levelLoads.isEmpty { after += 1 }
            live.sync(r.world)
            var block = [Int16](repeating: 0, count: 735)
            block.withUnsafeMutableBufferPointer { live.render(into: $0) }
            liveOut += block
        }
        let full = SoundMixer.mix(r.world, endTick: r.vm.tick)
        let mix = Array(full[(r.world.levelLoads[0].tick * 735)...])        // the window from the CHAOS load (735 samples per tick)
        let fx = (stage3b["runs"] as! [JSON]).first { $0["name"] as! String == "boot" }!["audio"] as! JSON
        func bytes(_ a: ArraySlice<Int16>) -> [UInt8] { a.flatMap { [UInt8(truncatingIfNeeded: $0), UInt8(truncatingIfNeeded: $0 >> 8)] } }
        #expect(mix.count == fx["frames"] as! Int)
        #expect(mix.contains { $0 != 0 }, "the boot mix is silent")
        #expect(sha(bytes(mix[...])) == fx["sha"] as! String, "boot mix")
        let seconds = stride(from: 0, to: mix.count, by: 22050).map { sha(bytes(mix[$0..<min($0 + 22050, mix.count)])) }
        #expect(seconds == fx["seconds"] as! [String], "per-second hashes")
        // the live timeline is the offline one shifted by the pad
        #expect(Array(liveOut.dropFirst(2048)) == Array(full.dropLast(2048)), "live render differs from the offline mix")
    }

    // Master-volume table (effect level): hashes from movie.mix_audio with the same events and world.sfx_log.
    @Test func masterVolumeMatchesPrototype() throws {
        let bank = try #require(worldResources).sounds
        let loop = try #require(bank.samples.first { $0.loopEnd > $0.loopStart && $0.length > 2000 })
        let plain = try #require(bank.samples.first { $0.loopEnd == 0 && $0.length > 4000 })
        let plays = [(3, loop, 255, 0, 1), (5, plain, 200, 0, 2), (9, plain, 128, -1024, 3), (14, plain, 255, 500, 4), (14, loop, 90, 0, 5)]
        let volumes = [(3, 1, 255), (5, 2, 200), (9, 3, 255), (12, 2, 40), (13, 2, 255), (20, 3, 255), (26, 3, 10), (30, 1, 100)]
        let stops = [(25, 1), (33, 5)]
        func mix(_ levels: [(Int, Int)]) -> String {
            let m = SoundMixer()
            for l in levels { m.setLevel(tick: l.0, sfx: l.1) }
            for t in 0...40 {
                for p in plays where p.0 == t { m.play(p.1, pcm: bank.pcm(p.1.index), tick: p.0, volume: p.2, pitch: p.3, handle: p.4) }
                for v in volumes where v.0 == t { m.setVolume(handle: v.1, tick: v.0, volume: v.2) }
                for s in stops where s.0 == t { m.stop(handle: s.1, tick: s.0) }
            }
            var out = [Int16](repeating: 0, count: MixerFrames.of(tick: 40))
            out.withUnsafeMutableBufferPointer { m.render(into: $0) }
            return sha(out.flatMap { [UInt8(truncatingIfNeeded: $0), UInt8(truncatingIfNeeded: $0 >> 8)] })
        }
        #expect(mix([(0, 100)]) == "5e075b596386d92bcdce03b60b214bee919ca6f2cecb0ac09493e97f9b2f600d")
        #expect(mix([(0, 100), (10, 50), (21, 25), (31, 0)]) == "f1a746ea891cfa45df360f58190f2292fae9e1f8a1c4eec8aa921394be192e21")
    }

    @Test func worldLevelStepsReachTheMixer() throws {
        let r = try Run(level: "CHAOS")
        let h = r.world.playSound(0, volume: 255, loop: false)
        #expect(h != 0)
        let full = SoundMixer.mix(r.world, endTick: 30)
        r.world.configureSettings(Settings(sound: 50))
        let half = SoundMixer.mix(r.world, endTick: 30)
        #expect(full.contains { $0 != 0 })
        #expect(zip(full, half).allSatisfy { abs(Double($1) - Double($0) * 126 / 254) <= 1.0 }, "table[255] is 254 at 100 and 126 at 50")
        r.world.configureSettings(Settings(sound: 0))
        #expect(SoundMixer.mix(r.world, endTick: 30).allSatisfy { $0 == 0 })
    }

    // Playtest: speech lost its first words after a menu was held open (Game > Language). The audio kept rendering while no tick ran,
    // so the next line started behind the playhead. keepUp moves the timeline so it starts whole.
    @Test func soundAfterAStallStartsWhole() throws {
        let bank = try #require(worldResources).sounds
        let plain = try #require(bank.samples.first { $0.loopEnd == 0 && $0.length > 4000 })
        func render(stall: Bool, keepUp: Bool) -> [Int16] {
            let m = SoundMixer(origin: 2048)
            var skipped = [Int16](repeating: 0, count: MixerFrames.of(tick: 10) + (stall ? 22050 : 0))   // ticks 0-9, plus 1 s held
            skipped.withUnsafeMutableBufferPointer { m.render(into: $0) }
            if keepUp { m.keepUp(tick: 10, pad: 2048) }
            m.play(plain, pcm: bank.pcm(plain.index), tick: 10, volume: 255, pitch: 0, handle: 1, looped: false)
            var out = [Int16](repeating: 0, count: plain.length * 2 + 4096)
            out.withUnsafeMutableBufferPointer { m.render(into: $0) }
            let first = out.firstIndex { $0 != 0 } ?? 0, last = out.lastIndex { $0 != 0 } ?? -1
            return first <= last ? Array(out[first...last]) : []           // the line from its first to its last audible frame
        }
        let whole = render(stall: false, keepUp: true)
        #expect(!whole.isEmpty)
        let cut = render(stall: true, keepUp: false)
        #expect(cut.count < whole.count, "without keepUp the stalled line loses its start (\(cut.count) vs \(whole.count), rate \(plain.rate), length \(plain.length))")
        #expect(render(stall: true, keepUp: true) == whole, "after a stall the line plays from its first sample")
        #expect(render(stall: false, keepUp: false) == whole, "no stall: keepUp changes nothing")
    }

    @Test func liveRendererMatchesOfflineOnSyntheticEvents() throws {
        let bank = try #require(worldResources).sounds
        let loop = try #require(bank.samples.first { $0.loopEnd > $0.loopStart && $0.length > 2000 })
        let plain = try #require(bank.samples.first { $0.loopEnd == 0 && $0.length > 4000 })
        // (tick, sample, volume, pitch, handle), volume changes (tick, handle, volume), stops (tick, handle)
        let plays = [(3, loop, 255, 0, 1), (5, plain, 200, 0, 2), (9, plain, 128, -1024, 3), (14, plain, 255, 500, 4), (14, loop, 90, 0, 5)]
        let volumes = [(3, 1, 255), (5, 2, 200), (9, 3, 255), (12, 2, 40), (13, 2, 255), (20, 3, 255), (26, 3, 10), (30, 1, 100)]   // like the World: the first entry is the start
        let stops = [(25, 1), (33, 5)]
        let frames = MixerFrames.of(tick: 40)

        func feed(_ m: SoundMixer, upTo tick: Int) {
            for p in plays where p.0 == tick { m.play(p.1, pcm: bank.pcm(p.1.index), tick: p.0, volume: p.2, pitch: p.3, handle: p.4) }
            for v in volumes where v.0 == tick { m.setVolume(handle: v.1, tick: v.0, volume: v.2) }
            for s in stops where s.0 == tick { m.stop(handle: s.1, tick: s.0) }
        }
        let offline = SoundMixer()
        for t in 0...40 { feed(offline, upTo: t) }
        var want = [Int16](repeating: 0, count: frames)
        want.withUnsafeMutableBufferPointer { offline.render(into: $0) }
        #expect(want.contains { $0 != 0 })

        let live = SoundMixer(origin: 0)
        var got: [Int16] = [], tick = 0
        let sizes = [1, 97, 512, 733, 1024, 300]
        var k = 0
        while got.count < frames {
            // hand over every tick that starts within the next block plus 2000 frames (a volume ramp begins one tick, 735 frames, early)
            let n = min(sizes[k % sizes.count], frames - got.count); k += 1
            while MixerFrames.of(tick: tick) < got.count + n + 2000 && tick <= 40 { feed(live, upTo: tick); tick += 1 }
            var block = [Int16](repeating: 0, count: n)
            block.withUnsafeMutableBufferPointer { live.render(into: $0) }
            got += block
        }
        #expect(got.count == want.count)
        let bad = got.indices.first { got[$0] != want[$0] }
        #expect(bad == nil, "live \(got[bad ?? 0]) vs offline \(want[bad ?? 0]) differs from frame \(bad ?? 0) (tick \((bad ?? 0) / 735))")
    }
}

enum MixerFrames { static func of(tick: Int) -> Int { SoundMixer.frame(tick) } }
