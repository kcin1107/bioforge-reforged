import Testing
@testable import BioForgeHost

struct TickClockTests {
    private func run(_ c: inout TickClock, dt: Double, now: Double = 0, holdDue: @escaping () -> Bool = { false }, tick: () -> Bool = { true }) -> TickClock.Outcome {
        c.advance(dt: dt, now: { now }, holdDue: holdDue, tick: tick)
    }

    @Test func oneTickPerThirtiethOfASecond() {
        var c = TickClock()
        for _ in 0..<5 { #expect(run(&c, dt: 1 / 30) == .ran(ticks: 1)) }
    }

    @Test func fractionsAccumulate() {
        var c = TickClock()
        let results = (0..<4).map { _ in run(&c, dt: 1 / 60) }
        #expect(results == [.ran(ticks: 0), .ran(ticks: 1), .ran(ticks: 0), .ran(ticks: 1)])
    }

    @Test func aHitchCatchesUpAndKeepsTheRemainder() {
        var c = TickClock()
        #expect(run(&c, dt: 0.25) == .ran(ticks: 7))                    // 7.5 ticks owed
        #expect(run(&c, dt: 1 / 60) == .ran(ticks: 1))                  // the half tick left over plus half a tick
    }

    @Test func neverMoreThanEightTicksAndTheClockResets() {
        var c = TickClock()
        var ticks = 0
        #expect(run(&c, dt: 0.5, tick: { ticks += 1; return true }) == .ran(ticks: 8))
        #expect(ticks == 8 && c.gameClock == 0)
    }

    @Test func aPictureHoldStopsTheBatchAndHoldsForTwoSeconds() {
        var c = TickClock()
        var asked = 0, ticks = 0
        let outcome = run(&c, dt: 0.25, now: 10, holdDue: { asked += 1; return asked == 3 }, tick: { ticks += 1; return true })
        #expect(outcome == .ran(ticks: 2) && ticks == 2)
        #expect(c.pictureHoldUntil == 12 && c.gameClock == 0 && c.holding)
        ticks = 0
        #expect(run(&c, dt: 1, now: 11.9, tick: { ticks += 1; return true }) == .holding)
        #expect(ticks == 0 && c.gameClock == 0)
        #expect(run(&c, dt: 1 / 30, now: 12, tick: { ticks += 1; return true }) == .ran(ticks: 1))      // the hold ends: the clock restarts from 0
        #expect(ticks == 1 && !c.holding)
    }

    @Test func aTickThatLeavesStopsTheFrame() {
        var c = TickClock()
        var ticks = 0
        #expect(run(&c, dt: 0.25, tick: { ticks += 1; return ticks < 3 }) == .stopped)
        #expect(ticks == 3)
    }

    @Test func resetClearsTheClockAndTheHold() {
        var c = TickClock()
        _ = run(&c, dt: 0.25, now: 1, holdDue: { true })
        #expect(c.holding)
        c.reset()
        #expect(!c.holding && c.gameClock == 0)
    }
}
