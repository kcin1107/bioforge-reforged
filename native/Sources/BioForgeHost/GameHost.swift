// The running game as every shell drives it: one call per display frame (`advance`) runs the ticks the clock owes, feeding the play log,
// the autosave and the audio after each, and tells the platform what to do about exits, new games, loads, file errors and redraws.
import BioForgeCore
import Foundation

/// What only the shell can do.
@MainActor
public protocol HostPlatform: AnyObject {
    func terminate()                          // the player chose Exit
    func startNewGame()                       // the game asked for a new one
    func startPendingLoad()                   // a confirmed Load dialog left a session to swap to
    func reportFileError(_ w: World)          // the alert sheet
    func afterTicks(_ w: World)               // the Mac: dropReleasedModifiers and syncPointer
    func redrawGame()                         // the game picture (the Mac's viewer has its own redraw)
    func now() -> Double                      // a monotonic clock in seconds
}

@MainActor
public final class GameHost {
    public var session: GameSession?
    public let input: InputRouter
    public let audio: HostAudio
    public let playLog: PlayLog
    public let autosaves: URL
    public var log: HostLog?
    public weak var platform: HostPlatform?
    public private(set) var clock = TickClock()
    private var loggedWarnings = 0

    public init(input: InputRouter, audio: HostAudio, playLog: PlayLog, autosaves: URL, log: HostLog?) {
        self.input = input; self.audio = audio; self.playLog = playLog; self.autosaves = autosaves; self.log = log
    }

    /// A game started: the clock and the warning count start over.
    public func gameStarted() { clock.reset(); loggedWarnings = 0 }

    /// One display frame of the running game: `dt` seconds since the last, already capped by the shell.
    public func advance(dt: Double) {
        guard let s = session, let platform else { return }
        for w in s.world.warnings.dropFirst(loggedWarnings) { log?.error("game", w) }       // save / load failures show up here
        loggedWarnings = s.world.warnings.count
        let outcome = clock.advance(dt: dt, now: { platform.now() }, holdDue: { s.pictureHoldDue() }, tick: { [self] in
            s.tick()
            playLog.observe(s.world)
            Autosave.saveIfDue(s.world, directory: autosaves, log: { [playLog] in playLog.note($0) })
            audio.sync(s.world)
            if s.world.exitRequested { platform.terminate(); return false }
            if s.world.newGameRequested { platform.startNewGame(); return false }
            if s.world.pendingLoad != nil { platform.startPendingLoad(); return false }      // a load the pointer's release activated
            return true
        })
        switch outcome {
        case .holding: platform.redrawGame(); return
        case .stopped: return
        case .ran(let ticks):
            audio.setPaused(s.world.paused)
            platform.reportFileError(s.world)
            platform.afterTicks(s.world)
            if ticks > 0 || clock.holding { platform.redrawGame() }
        }
    }

    /// In the background, minimized or behind a sheet: keys let go; the sound pauses (and resumes as the game was, in the game).
    public func setSuspended(_ s: Bool, inGame: Bool) {
        input.releaseAll(world: session?.world)
        if s { audio.setPaused(true) } else if inGame { audio.setPaused(session?.world.paused ?? false) }
    }
}
