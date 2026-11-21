// Audio (WorldAudio.swift) against re/interp/test_audio.py: the voice statements, REPLACESOUND, the OVERTIME ramps and the camera / room
// ambient loops, with the same cases and the same numbers.
import Foundation
import Testing
@testable import BioForgeCore

private let scream = "_ESCHER_VOX_SCREAM"      // sample 0: 16054 samples at 11111 Hz, one pass 44 ticks

@Suite(.serialized, .enabled(if: game != nil, "BIOFORGE_DATA is not set; point it at the BioForge game folder"))
struct AudioTests {
    private func session(_ level: String = "LANDPAD", camera: String? = nil) throws -> GameSession {
        try GameSession(resources: try #require(worldResources), level: level, camera: camera)
    }

    private func proc(_ vm: ScriptVM) -> ScriptProcess {
        let block = ScriptBlock("TEST", "routine", 0, nil)
        return ScriptProcess(vm: vm, handle: 0, block: block, code: vm.code(block), ctx: ScriptContext(curFig: "PLAYER"))
    }

    private func stmt(_ s: GameSession, _ name: String, _ args: ScriptValue...) { _ = s.world.call(.stmt, name, args, proc(s.vm)) }
    @discardableResult private func fn(_ s: GameSession, _ name: String, _ args: ScriptValue...) -> Int {
        if case .int(let i) = s.world.call(.function, name, args, proc(s.vm)) { return i }
        return Int.min
    }
    private func run(_ s: GameSession, _ n: Int) { for _ in 0..<n { s.vm.tickOnce() } }
    private func alive(_ s: GameSession, _ h: Int) -> Bool { s.vm.process(h) != nil }
    private func vols(_ s: GameSession, _ h: Int) -> [[Int]] { s.world.soundVolumes.filter { $0.handle == h }.map { [$0.tick, $0.volume] } }
    private func rates(_ s: GameSession, _ h: Int) -> [[Int]] { s.world.soundRates.filter { $0.handle == h }.map { [$0.tick, $0.rate] } }
    private func switchTo(_ s: GameSession, _ cam: String) { s.world.setCamera(cam, "test"); s.world.step() }

    // MARK: voice statements

    @Test func setVolumeClampsUnsigned() throws {
        let s = try session()
        let h = fn(s, "SOUND", .str(scream), .int(100))
        stmt(s, "SETVOLUME", .int(h), .int(300)); run(s, 1)
        stmt(s, "SETVOLUME", .int(h), .int(-1)); run(s, 1)
        stmt(s, "SETVOLUME", .int(h), .int(20))
        #expect(vols(s, h) == [[0, 255], [1, 255], [2, 20]])
        #expect(s.world.voiceState[h]?.level == 20)
    }

    @Test func setVolumeSameTickLogsBoth() throws {
        let s = try session()
        let h = fn(s, "SOUND", .str(scream), .int(100))
        stmt(s, "SETVOLUME", .int(h), .int(10))
        stmt(s, "SETVOLUME", .int(h), .int(30))
        #expect(vols(s, h) == [[0, 10], [0, 30]])           // both are logged, the mixer keeps the last
    }

    @Test func deadUnknownAndSkippedHandlesDoNothing() throws {
        let s = try session()
        let h = fn(s, "SOUND", .str(scream), .int(100))
        run(s, 60)
        #expect(!alive(s, h))
        for bad in [ScriptValue.int(h), .int(0), .int(-1), .int(9999), .str("x")] {
            stmt(s, "SETVOLUME", bad, .int(50)); stmt(s, "SETPITCH", bad, .int(5000)); stmt(s, "ADDTOPITCH", bad, .int(5))
        }
        #expect(s.world.soundVolumes.isEmpty && s.world.soundRates.isEmpty && s.world.warnings.isEmpty)
    }

    @Test func positionalHandleGetsThePositionalValueBack() throws {
        let s = try session(), w = s.world
        stmt(s, "CREATEFIGURE", .str("LEX"), .str("PLAYER"))
        let lex = try #require(w.player)
        w.setPos(lex, V3(0, 0, 0), raw: true)
        let h = w.playSound(0, fig: lex)
        let start = w.soundPos[h]!.volume
        stmt(s, "SETVOLUME", .int(h), .int(10))
        #expect(w.voiceState[h]?.level == 10 && w.soundPos[h]?.key == lex.name && w.soundPos[h]?.volume == 10)
        run(s, 1)
        w.refreshSoundVolumes()
        #expect(start == 0)
        #expect(vols(s, h) == [[0, 0], [0, 10], [1, 0]])
    }

    @Test func setPitchRetimesTheHandle() throws {
        let s = try session()
        let h = fn(s, "SOUND", .str(scream), .int(100))
        #expect(s.world.voiceState[h]?.rate == 11111)
        stmt(s, "SETPITCH", .int(h), .int(5555))                  // ceil(16054 * 30 / 5555) = 87
        #expect(rates(s, h) == [[0, 5555]])
        run(s, 87)
        #expect(alive(s, h))
        run(s, 1)
        #expect(!alive(s, h))
    }

    @Test func setPitchMidway() throws {
        let s = try session()
        let h = fn(s, "SOUND", .str(scream), .int(100))
        run(s, 10)
        stmt(s, "SETPITCH", .int(h), .int(5555))                  // 10 * 11111 played; ceil((481620 - 111110) / 5555) = 67 more
        run(s, 66)
        #expect(alive(s, h))
        run(s, 2)
        #expect(!alive(s, h))
    }

    @Test func setPitchZeroNeverEndsAndALaterRateResumes() throws {
        let s = try session()
        let h = fn(s, "SOUND", .str(scream), .int(100))
        stmt(s, "SETPITCH", .int(h), .int(0))
        run(s, 500)
        #expect(alive(s, h))
        stmt(s, "SETPITCH", .int(h), .int(11111))
        run(s, 46)
        #expect(!alive(s, h))
    }

    @Test func addToPitchWrapsU16() throws {
        let s = try session()
        let h = fn(s, "SOUND", .str(scream), .int(100))
        stmt(s, "ADDTOPITCH", .int(h), .int(-20000))
        stmt(s, "ADDTOPITCH", .int(h), .int(20000))
        #expect(rates(s, h) == [[0, 56647], [0, 11111]])
        #expect(s.world.voiceState[h]?.rate == 11111)
    }

    @Test func mixerFollowsTheRateAndTheVolumeLog() throws {
        let s = try session()
        let h = fn(s, "SOUND", .str(scream), .int(200))
        run(s, 10)
        stmt(s, "SETPITCH", .int(h), .int(0))                     // rate 0 holds the source position from tick 10 on
        stmt(s, "SETVOLUME", .int(h), .int(100))
        #expect(s.world.soundVolumes.map { [$0.tick, $0.handle, $0.volume] } == [[10, h, 100]])
        let mixed = SoundMixer.mix(s.world, endTick: 60)
        let f10 = 7350
        #expect(mixed[..<f10].contains { $0 != 0 })
        #expect(Set(mixed[(f10 + 22050 / 30 + 2)...]).count == 1)
        #expect(mixed[(f10 + 3)..<(f10 + 20)].contains { $0 != 0 })
    }

    // rumble1a: 40505 samples at 11025 Hz, loop 7819 + 15313 = 7819..23132. STOPAMBIENT (1000:046f) lets it play on from where it is, without wrapping, to
    // the end of the sample; the handle lives until then. test_audio.test_released_loop_plays_its_tail.
    @Test func releasedLoopPlaysItsTail() throws {
        let s = try session()
        let h = fn(s, "AMBIENT", .str("_quake_1"), .int(200))
        run(s, 30)
        stmt(s, "SETPITCH", .int(h), .int(9000))
        run(s, 60)
        stmt(s, "STOPAMBIENT", .int(h))
        #expect(s.world.soundReleases.map { [$0.tick, $0.handle] } == [[90, h]])
        #expect(s.vm.process(h)?.wake == 90 + 90, "position 13712 after the wrap; 26793 samples left at 9000 Hz")
        run(s, 90)
        #expect(s.vm.process(h) != nil)
        run(s, 1)
        #expect(s.vm.process(h) == nil)
        let mixed = SoundMixer.mix(s.world, endTick: 300)
        let f90 = 66150, tail = Int((40504 - 13712.0) / (9000 / 22050.0)) + 1
        #expect(mixed[(f90 + tail - 400)..<(f90 + tail)].contains { $0 != 0 })
        #expect(mixed[(f90 + tail + 2)...].allSatisfy { $0 == 0 })
        #expect(sha(mixed.flatMap { [UInt8(truncatingIfNeeded: $0), UInt8(truncatingIfNeeded: $0 >> 8)] }) == "08b0ecc9160c04201772302e12e6e9b10e9ab1717f90b515a2a138341329a177")
    }

    @Test func mixerPiecewiseRateDigest() throws {
        let s = try session()
        let h = fn(s, "SOUND", .str(scream), .int(200))
        run(s, 10)
        stmt(s, "SETPITCH", .int(h), .int(5555)); run(s, 5)
        stmt(s, "SETPITCH", .int(h), .int(0)); stmt(s, "SETVOLUME", .int(h), .int(100)); run(s, 3)
        stmt(s, "SETPITCH", .int(h), .int(20000))
        let mixed = SoundMixer.mix(s.world, endTick: 60)
        #expect(mixed.count == 44100)
        #expect(sha(mixed.flatMap { [UInt8(truncatingIfNeeded: $0), UInt8(truncatingIfNeeded: $0 >> 8)] }) == "15407c246ae7de44be20b0ef9ff29589557ecd1d7443264ff92d82582f851766")
    }

    // MARK: REPLACESOUND

    @Test func replaceChainAndRevert() throws {
        let s = try session(), w = s.world
        #expect(w.soundIndex(.str("_wind2")) == 59)
        stmt(s, "REPLACESOUND", .str("_wind2"), .str("_wind4"))
        #expect(w.soundIndex(.str("_wind2")) == 61 && w.soundIndex(.str("_WIND2")) == 61 && w.soundIndex(.str("_wind4")) == 61)
        fn(s, "SOUND", .str("_wind2"))
        #expect(w.soundLog.last?.index == 61)
        stmt(s, "REPLACESOUND", .str("_wind4"), .int(5))          // copy semantics: _wind2 does not follow
        #expect(w.soundIndex(.str("_wind2")) == 61 && w.soundIndex(.str("_wind4")) == 5)
        stmt(s, "REVERTSOUND", .str("_wind2"))
        #expect(w.soundIndex(.str("_wind2")) == 59)
        stmt(s, "REVERTSOUND", .str("_wind4"))
        #expect(w.soundIndex(.str("_wind4")) == 61)
        #expect(w.warnings.isEmpty)
    }

    @Test func outOfRangeOverrideResolvesToNothing() throws {
        let s = try session()
        stmt(s, "REPLACESOUND", .str("_wind2"), .int(99999))
        #expect(s.world.soundIndex(.str("_wind2")) == nil)
    }

    @Test func nonSoundNamesWarn() throws {
        let s = try session()
        stmt(s, "REPLACESOUND", .str("_not_a_sound"), .int(1))
        stmt(s, "REVERTSOUND", .str("_not_a_sound"))
        #expect(s.world.warnings == ["REPLACESOUND: not a sound name (error 0x34)", "REVERTSOUND: not a sound name (error 0x34)"])
    }

    @Test func cacheStatementsAreNoOps() throws {
        let s = try session()
        stmt(s, "BANKINSFX", .str("_wind2"), .str("_wind3"))
        stmt(s, "SETSOUNDCACHE", .int(1000), .int(100), .int(1000))
        stmt(s, "REVERTSOUNDCACHE")
        #expect(s.world.warnings.isEmpty)
        stmt(s, "SETSOUNDCACHE", .int(1000), .int(0), .int(1000))
        #expect(s.world.warnings == ["SETSOUNDCACHE: needs three non-zero values (error 0x17c)"])
    }

    // MARK: ramps

    private func loop(_ s: GameSession, _ volume: Int = 0) -> Int { fn(s, "AMBIENT", .str("_wind2"), .int(volume)) }

    @Test func absoluteTotalAndRemainderOnTheLastTick() throws {
        let s = try session()
        let h = loop(s, 255)
        let r = fn(s, "MODIFYVOLUMEOVERTIME", .int(h), .int(100), .int(0), .int(30))      // delta -100 over 30: step -3, remainder -10 on tick 30
        #expect(vols(s, h) == [[0, 100]])
        run(s, 30)
        #expect(alive(s, r))
        #expect(Array(vols(s, h)[1..<4]) == [[1, 97], [2, 94], [3, 91]])
        run(s, 1)
        #expect(!alive(s, r))
        #expect(vols(s, h).last == [30, 0] && s.world.voiceState[h]?.level == 0)
    }

    @Test func caseAPositive() throws {
        let s = try session()
        let h = loop(s, 50)
        let r = fn(s, "MODIFYVOLUMEOVERTIME", .int(h), .int(10), .int(30))               // relative: +1 every 3 ticks
        #expect(vols(s, h).isEmpty)
        run(s, 31)
        #expect(!alive(s, r))
        #expect(Array(vols(s, h)[..<2]) == [[3, 51], [6, 52]])
        #expect(s.world.voiceState[h]?.level == 60)
    }

    @Test func negativeCaseARises() throws {
        let s = try session()
        let h = loop(s, 0)
        fn(s, "MODIFYVOLUMEOVERTIME", .int(h), .int(65), .int(0), .int(120))           // INTRO.scr:416: 65 -> 0 over 120 RISES (period < 0)
        run(s, 121)
        #expect(s.world.voiceState[h]?.level == 185)
    }

    @Test func relativeForm() throws {
        let s = try session()
        let h = loop(s, 100)
        fn(s, "MODIFYVOLUMEOVERTIME", .int(h), .int(-40), .int(20))
        run(s, 21)
        #expect(s.world.voiceState[h]?.level == 60)
    }

    @Test func error0x3aReturnsZero() throws {
        let s = try session()
        let h = loop(s, 100)
        #expect(fn(s, "MODIFYVOLUMEOVERTIME", .int(h), .int(50), .int(50), .int(10)) == 0)
        #expect(fn(s, "MODIFYVOLUMEOVERTIME", .int(h), .int(0), .int(10)) == 0)
        #expect(fn(s, "MODIFYPITCHOVERTIME", .int(h), .int(7), .int(7), .int(10)) == 0)
        #expect(s.world.warnings.count == 2)
    }

    @Test func underflowWrapsTo255() throws {
        let s = try session()
        let h = loop(s, 10)
        fn(s, "MODIFYVOLUMEOVERTIME", .int(h), .int(-20), .int(10))
        run(s, 11)                                                // 8 6 4 2 0, then -2 wraps to 255, 253 ... 247
        #expect(Array(vols(s, h).map { $0[1] }[4..<8]) == [0, 255, 253, 251])
        #expect(s.world.voiceState[h]?.level == 247)
    }

    @Test func pitchRampLogsRates() throws {
        let s = try session()
        let h = loop(s, 10)
        let r = fn(s, "MODIFYPITCHOVERTIME", .int(h), .int(9000), .int(11000), .int(20))
        #expect(rates(s, h) == [[0, 9000]])
        run(s, 21)
        #expect(!alive(s, r))
        let got = rates(s, h)
        #expect(got.count == 22 && got[1] == [1, 9100] && got[20] == [20, 11000] && got.last == [20, 11000])
    }

    // MARK: ambient loops

    @Test func firstCameraStartsTheRoomLoopAfterTheFrame() throws {
        let s = try session("CHAOS", camera: "CE33"), w = s.world
        #expect(s.vm.globals["_ce33_volume"] == .int(80))
        w.setCamera("CE33", "test")
        #expect(w.roomAmbient == 0 && fn(s, "GETROOMAMBIENT") == -1)
        w.step()
        let h = w.roomAmbient
        #expect(w.soundLog.count == 1 && w.soundLog[0].tick == 0 && w.soundLog[0].index == 8 && w.soundLog[0].name == "hum1e"
                && w.soundLog[0].volume == 80 && w.soundLog[0].pitch == 0 && w.soundLog[0].handle == h)
        #expect(fn(s, "GETROOMAMBIENT") == h && fn(s, "GETCAMERAAMBIENT") == -1)
        #expect(w.soundLoops.contains(h))
    }

    @Test func sameRoomKeepsTheHandleAndSetsTheCamerasVolume() throws {
        let s = try session("CHAOS", camera: "CE33"), w = s.world
        switchTo(s, "CE33")
        let h = w.roomAmbient
        switchTo(s, "CE31")
        #expect(w.roomAmbient == h && w.soundLog.count == 1)
        #expect(vols(s, h) == [[0, 0]])                           // _CE31_VOLUME: CE3_LOAD (the room event) restarts its 0 -> 100 ramp
    }

    @Test func aDifferentSampleReplacesTheLoop() throws {
        let s = try session("CHAOS", camera: "CE33"), w = s.world
        switchTo(s, "CE33")
        let old = w.roomAmbient
        switchTo(s, "HAL1")
        #expect(w.soundStops.map { [$0.tick, $0.handle] } == [[0, old]])
        #expect(w.roomAmbient != old)
        let e = w.soundLog.last!
        #expect(e.index == 17 && e.name == "hum3a" && e.volume == 150)
    }

    @Test func setVolumeOnTheRoomHandleWritesTheVariable() throws {
        let s = try session("CHAOS", camera: "CE33"), w = s.world
        switchTo(s, "CE33")
        let h = w.roomAmbient
        stmt(s, "SETVOLUME", .int(h), .int(33))
        #expect(s.vm.globals["_ce33_volume"] == .int(33))
        w.step()
        #expect(vols(s, h) == [[0, 33]])
        stmt(s, "SETVOLUME", .int(h), .int(300))                  // the variable gets the unclamped level
        #expect(s.vm.globals["_ce33_volume"] == .int(300))
    }

    @Test func aScriptAssignmentIsAppliedNextFrame() throws {
        let s = try session("CHAOS", camera: "CE33"), w = s.world
        switchTo(s, "CE33")
        let h = w.roomAmbient
        s.vm.setGlobal("_ce33_volume", .int(20))
        #expect(vols(s, h).isEmpty)
        w.step()
        #expect(vols(s, h) == [[0, 20]])
    }

    @Test func monitorRunningDoesNotSetPending() throws {
        let s = try session("CHAOS", camera: "CE33"), w = s.world
        w.options = try Options(game: try #require(game))
        w.options!.open(Options.save)
        w.setCamera("CE33", "test")
        w.step()
        #expect(!w.ambientPending && w.roomAmbient == 0 && w.soundLog.isEmpty)
    }

    @Test func volumeRampOnTheRoomHandleEditsTheVariable() throws {
        let s = try session("CHAOS", camera: "CE33"), w = s.world
        switchTo(s, "CE33")
        let h = w.roomAmbient
        fn(s, "MODIFYVOLUMEOVERTIME", .int(h), .int(80), .int(40), .int(20))     // 80 -> 40 over 20: -2 per tick
        #expect(s.vm.globals["_ce33_volume"] == .int(80))
        for _ in 0..<21 { s.vm.tickOnce(); w.step() }
        #expect(s.vm.globals["_ce33_volume"] == .int(40) && w.voiceState[h]?.level == 40)
    }

    @Test func loopVoiceTakesASlotAndStopsWithStopAllSounds() throws {
        let s = try session("CHAOS", camera: "CE33"), w = s.world
        switchTo(s, "CE33")
        let h = w.roomAmbient
        #expect(w.voices.contains { $0?.handle == h })
        stmt(s, "STOPALLSOUNDS")
        #expect(!alive(s, h))
    }

    // MARK: motion cues (test_audio.py MotionCues)

    private func cueFig(_ w: World, _ type: String, _ motion: String = "WALK") throws -> Figure {
        let f = Figure(name: type, type: type, assets: try #require(w.asset(type)), speed: World.defaultSpeed, pos: V3(0, 0, 0))
        f.motion = motion; f.motId = 1; f.idx = 0
        return f
    }

    private func walk(_ w: World, _ fig: Figure, _ frames: [Int]) -> [[Int]] {
        var cues: [[Int]] = []
        w.motionCueProbe = { f, n in cues.append([f.idx, n]) }
        for i in frames { fig.idx = i; w.eventWalk(fig) }
        return cues
    }

    @Test func caynanWalkCuesAtTheFrameBeforeTheirFrameByte() throws {
        let w = try session("CHAOS", camera: "CE31").world
        let fig = try cueFig(w, "CAYNAN")       // CAYNAN WALK: 0 1 2 3 4 fc 5 ... 10 fc 11 12 13 fe
        #expect(walk(w, fig, Array(0..<14) + Array(0..<14)) == [[4, 1], [10, 1], [4, 1], [10, 1]])
    }

    @Test func lexWalkCueBeforeFrameZeroAndAfterAWrap() throws {
        let w = try session("CHAOS", camera: "CE31").world
        let fig = try cueFig(w, "LEX")           // MAN WALK: fb 0 1 2 3 4 fc 5 6 fb 7 8 9 10 fc 11 12 13 fe; after the wrap the walk waits for the first frame change
        #expect(walk(w, fig, Array(0..<14) + [0, 1, 2]) == [[0, 2], [4, 1], [6, 2], [10, 1], [1, 2]])
    }

    @Test func skippedFramesAndANewMotion() throws {
        let w = try session("CHAOS", camera: "CE31").world
        let fig = try cueFig(w, "CAYNAN")
        #expect(walk(w, fig, [0, 7, 12]) == [[7, 1], [12, 1]])
        fig.motId = 2; fig.motion = "RECOIL_TL"                 // 0 fc 1 ...: the new motion starts its list again
        #expect(walk(w, fig, [0, 1]) == [[0, 1]])
    }

    @Test func cueNamesInOrderThenTheCutFormName() throws {
        let w = try session("CHAOS", camera: "CE31").world
        var tried: [String] = []
        w.soundNameProbe = { tried.append($0); return nil }
        w.motionCue(try cueFig(w, "CAYNAN", "ATK_M1"), 2)
        #expect(Array(tried.prefix(5)) == ["_ATK_M1_2_CAYNAN_CE31", "_ATK_M1_2_CAYNAN_CE3", "_ATK_M1_2_CE31", "_ATK_M1_2_CE3", "_ATK_M1_2_CAYNAN"])
        #expect(Array(tried.dropFirst(5)) == ["_ATK_M1_2", "_ATK_M1", "_ATK"])
    }

    @Test func cuesPlayTheBankSamplesAtPriority0OnTheFigure() throws {
        let w = try session("CHAOS", camera: "CE31").world
        let caynan = try cueFig(w, "CAYNAN"), lex = try cueFig(w, "LEX")
        w.motionCue(caynan, 1); w.motionCue(lex, 1); w.motionCue(lex, 2)
        caynan.motion = "RECOIL_TL"
        w.motionCue(caynan, 1)
        let ids = ["_WALK_1_CAYNAN", "_WALK_1_LEX", "_WALK_2_LEX", "_RECOIL_TL_1_CAYNAN"].map { w.soundIndex(.str($0)) }
        #expect(!ids.contains(nil))
        #expect(w.soundLog.map(\.index) == ids.map { $0! })
        #expect(w.voices.compactMap { $0?.priority }.allSatisfy { $0 == 0 })
        #expect(w.soundLog.allSatisfy { $0.volume <= 255 })
    }

    @Test func theLookupCutsLongNamesTo24Characters() throws {
        let w = try session("CHAOS", camera: "CE31").world
        var tried: [String] = []
        w.soundNameProbe = { tried.append($0); return nil }
        #expect(w.ambientId("_ABCDEFGHIJKLMNOPQRSTUVWXYZ") == -1)
        #expect(tried == ["_ABCDEFGHIJKLMNOPQRSTUVW"])
        tried.removeAll()
        _ = w.ambientId("_ABCDEFGHIJKLMNOPQRSTUVWX")             // 25 characters stay whole
        #expect(tried == ["_ABCDEFGHIJKLMNOPQRSTUVWX"])
    }
}
