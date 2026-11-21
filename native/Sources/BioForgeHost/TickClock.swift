// The game's clock: how many 30 Hz ticks a display frame owes, and the app's hold on START's TITLE picture. No World in it, so it is
// tested on its own; GameHost feeds it the world's tick.
import BioForgeCore
import Foundation

public struct TickClock: Sendable {
    public static let rate = 30.0
    public static let maxCatchUp = 8                 // ticks per frame after a hitch; never spiral
    public private(set) var gameClock = 0.0
    public private(set) var pictureHoldUntil: Double?   // the end of GameSession.pictureHold while it runs
    public init() {}

    /// The picture is held or ticks are owed: the caller redraws.
    public var holding: Bool { pictureHoldUntil != nil }

    /// The start of a game: no time owed, no hold.
    public mutating func reset() { gameClock = 0; pictureHoldUntil = nil }

    public enum Outcome: Equatable, Sendable {
        case holding                     // the picture stays up, no tick ran: redraw only
        case stopped                     // a tick asked to leave (exit, new game, load)
        case ran(ticks: Int)
    }

    /// One display frame: `dt` seconds passed (already capped by the caller). `now` is read when a hold starts and ends.
    public mutating func advance(dt: Double, now: () -> Double, holdDue: () -> Bool, tick: () -> Bool) -> Outcome {
        if let until = pictureHoldUntil {                     // GameSession.pictureHold: the picture stays up, no tick runs
            guard now() >= until else { return .holding }
            pictureHoldUntil = nil; gameClock = 0
        }
        gameClock += dt
        var n = 0
        while gameClock >= 1 / Self.rate && n < Self.maxCatchUp {       // catch up after a hitch, but never spiral
            if holdDue() {                                    // the dialog closed over START's TITLE: show it before the level loads
                pictureHoldUntil = now() + GameSession.pictureHold
                gameClock = 0
                break
            }
            gameClock -= 1 / Self.rate
            if !tick() { return .stopped }
            n += 1
        }
        if n == Self.maxCatchUp { gameClock = 0 }
        return .ran(ticks: n)
    }
}
