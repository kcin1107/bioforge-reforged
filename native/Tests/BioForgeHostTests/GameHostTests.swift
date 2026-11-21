import BioForgeCore
import Foundation
import Testing
@testable import BioForgeHost

@MainActor
final class FakeAudio: HostAudio {
    var muted = false
    var calls: [String] = []
    func newGame(game: GameFolder, musicLevel: Int, device: MusicArrangement?) { calls.append("newGame") }
    func setMusicDevice(_ device: MusicArrangement?, world: World?) { calls.append("setMusicDevice") }
    func sync(_ world: World) { calls.append("sync") }
    func setPaused(_ paused: Bool) { calls.append("setPaused \(paused)") }
    func stop() { calls.append("stop") }
    func count(_ prefix: String) -> Int { calls.filter { $0.hasPrefix(prefix) }.count }
}

@MainActor
final class FakePlatform: HostPlatform {
    var time = 0.0
    var redraws = 0, afterTicks = 0, fileErrors = 0
    func terminate() {}
    func startNewGame() {}
    func startPendingLoad() {}
    func reportFileError(_ w: World) { fileErrors += 1 }
    func afterTicks(_ w: World) { afterTicks += 1 }
    func redrawGame() { redraws += 1 }
    func now() -> Double { time }
}

@MainActor
private struct Rig {
    let host: GameHost, audio = FakeAudio(), platform = FakePlatform(), session: GameSession
    init() throws {
        session = try GameSession.newGame(resources: try #require(hostResources))
        session.autoDifficulty = false
        let dir = URL(fileURLWithPath: NSTemporaryDirectory()).appendingPathComponent("gamehost-\(UUID().uuidString)", isDirectory: true)
        host = GameHost(input: InputRouter(), audio: audio, playLog: PlayLog(file: nil), autosaves: dir, log: nil)
        host.platform = platform
        host.session = session
        host.gameStarted()
    }
}

@MainActor
@Suite(.enabled(if: hostGame != nil, "BIOFORGE_DATA is not set; point it at the BioForge game folder"), .serialized)
struct GameHostTests {
    /// A hair over 1/30 s, so rounding never leaves the clock a hair short of a tick.
    let frame = 1 / 30.0 + 1e-9
    @Test func tenFramesRunTenTicks() throws {
        let r = try Rig()
        let start = r.session.vm.tick
        for _ in 0..<10 { r.host.advance(dt: frame) }
        #expect(r.session.vm.tick == start + 10)
        #expect(r.audio.count("sync") == 10 && r.audio.count("setPaused") == 10)
        #expect(r.platform.redraws == 10 && r.platform.afterTicks == 10 && r.platform.fileErrors == 10)
    }

    @Test func suspendingReleasesKeysAndPausesTheAudio() throws {
        let r = try Rig()
        r.host.setSuspended(true, inGame: true)
        #expect(r.audio.calls == ["setPaused true"])
        r.host.setSuspended(false, inGame: true)
        #expect(r.audio.calls == ["setPaused true", "setPaused \(r.session.world.paused)"])
        r.host.setSuspended(false, inGame: false)
        #expect(r.audio.calls.count == 2, "outside the game the audio is left alone")
    }

    @Test func gameStartedResetsTheClock() throws {
        let r = try Rig()
        r.host.advance(dt: 1 / 60)
        #expect(r.host.clock.gameClock > 0)
        r.host.gameStarted()
        #expect(r.host.clock.gameClock == 0)
    }

    @Test func theTitlePictureIsHeldForTwoSecondsBeforeTheOpeningCarriesOn() throws {
        let r = try Rig()
        var frames = 0
        while !(r.session.world.options.map { !$0.closed && $0.screen == "difficulty" } ?? false) && frames < 40_000 { r.host.advance(dt: frame); frames += 1 }
        #expect(r.session.world.isOptionsOpen)
        r.host.advance(dt: frame)                               // one frame with the dialog up: pictureHoldDue notes it
        var click: (Int, Int)?
        search: for y in 0..<200 { for x in 0..<320 where r.session.world.optionPointerMove(x: x, y: y) == "EZYX" { click = (x, y); break search } }
        let point = try #require(click)
        #expect(r.session.world.optionClick(x: point.0, y: point.1) == "difficulty:0")
        r.platform.time = 100
        let tick = r.session.vm.tick
        r.audio.calls = []; r.platform.redraws = 0
        r.host.advance(dt: frame)                              // the hold starts before any tick
        #expect(r.host.clock.holding && r.session.vm.tick == tick && r.audio.count("sync") == 0 && r.platform.redraws == 1)
        r.platform.time = 101.9
        r.host.advance(dt: frame)
        r.host.advance(dt: frame)
        #expect(r.session.vm.tick == tick && r.platform.redraws == 3, "no tick runs during the hold, but the picture is redrawn")
        r.platform.time = 102
        r.host.advance(dt: frame)
        #expect(!r.host.clock.holding && r.session.vm.tick == tick + 1, "ticks resume")
    }
}
