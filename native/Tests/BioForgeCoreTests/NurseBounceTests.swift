// Observed DOSBox-X nurse wall-contact snapshots. This replays only the bounded root-motion XY rollback, not a free-running fight.
import Foundation
import Testing
@testable import BioForgeCore

private struct NurseBounceFixture: Decodable {
    let samples: [Snapshot]

    struct Snapshot: Decodable { let clock: Int; let figures: [Figure] }

    struct Figure: Decodable {
        let r: Int
        let baseHeading: Double
        let flags: Int
        let frameStart, moveDelta, lastGood, pos, hull, velocity: [Int]
        let bounceLoss: Int

        enum CodingKeys: String, CodingKey {
            case r = "R", baseHeading = "base_heading", flags, frameStart = "frame_start", moveDelta = "move_delta"
            case lastGood = "last_good", pos, hull, velocity, bounceLoss = "bounce_loss"
        }
    }
}

@Suite(.serialized, .enabled(if: game != nil, "BIOFORGE_DATA is not set; point it at the BioForge game folder"))
struct NurseBounceTests {
    private func v3(_ values: [Int]) throws -> V3 {
        guard values.count == 3 else { throw FormatError("expected three-vector") }
        return V3(Double(values[0]), Double(values[1]), Double(values[2]))
    }

    @Test func originalNurseBounceContactsReplayExactly() throws {
        let url = try #require(Bundle.module.url(forResource: "nurse_bounce", withExtension: "json"))
        let fixture = try JSONDecoder().decode(NurseBounceFixture.self, from: Data(contentsOf: url))
        let world = try World(resources: try #require(worldResources), level: "CHAOS")
        let bot = try #require(world.figure("FIRSTBOT"))
        bot.noCollide = false; bot.bouncy = true
        var checked = 0

        for sample in fixture.samples {
            let capture = try #require(sample.figures.first)
            #expect(capture.flags & 0x10 != 0, "clock \(sample.clock): captured bounciness")
            #expect(capture.velocity == [0, 0, 0] && capture.bounceLoss == 0, "clock \(sample.clock): root-motion-only fixture")
            #expect(capture.moveDelta[0] != 0 || capture.moveDelta[1] != 0, "clock \(sample.clock): XY root delta")

            var start = try v3(capture.frameStart)
            var blocked = start + (try v3(capture.moveDelta))
            start.z = Double(capture.pos[2] - capture.r)
            blocked.z = start.z
            bot.frames = [MotionFrame(pos: SIMD3(0, 0, capture.r), rootAngle: .zero, limbs: [])]
            bot.idx = 0
            bot.heading = capture.baseHeading
            bot.pos = (try v3(capture.pos)) - V3(0, 0, Double(capture.r))

            let hull = world.queryHull(bot, at: bot.pos!)
            #expect([hull.lo.x, hull.lo.y, hull.lo.z, hull.hi.x, hull.hi.y, hull.hi.z] == capture.hull, "clock \(sample.clock): hull")
            #expect(world.figureBlocked(bot, blocked), "clock \(sample.clock): reconstructed wall contact")
            let heading = bot.heading
            bot.pos = blocked; bot.prevPos = start; bot.falling = false
            bot.vx = 0; bot.vy = 0; bot.vz = 0
            world.bounceCollision(bot, start: start)        // FUN_10a0_0ead's bouncy branch: step = blocked - start, then the rebound
            let actual = bot.pos!
            #expect(actual.x == Double(capture.pos[0]) && actual.y == Double(capture.pos[1]), "clock \(sample.clock): rollback XY")
            #expect(bot.heading == heading, "clock \(sample.clock): response keeps heading")
            checked += 1
        }
        #expect(checked == 3)
    }
}
