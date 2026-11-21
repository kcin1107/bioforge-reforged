// Python's recorded encounter inputs, with explicit front/rear attack setup only.
// The route from the rear wound through nurse defeat and corridor escape uses keys alone.
import Foundation
import Testing
@testable import BioForgeCore

@Suite(.enabled(if: game != nil, "BIOFORGE_DATA is not set; point it at the BioForge game folder"))
struct NursePushTests {
    @Test func inputDrivenNurseDefeatAndCorridorEscapeMatchPython() throws {
        let url = try #require(Bundle.module.url(forResource: "nurse_push", withExtension: "json"))
        let fixture = try #require(JSONSerialization.jsonObject(with: Data(contentsOf: url)) as? JSON)
        let inputs = try #require(fixture["input_events"] as? [JSON])
        let setups = try #require(fixture["fixtures"] as? [JSON])
        let checkpoints = try #require(fixture["checkpoints"] as? [JSON])
        let finalTick = try #require(checkpoints.last?["tick"] as? Int)
        #expect(setups.compactMap { $0["stage"] as? String } == ["front", "rear"])
        let session = try GameSession.newGame(resources: try #require(worldResources))
        session.runToChaosLoad()
        let world = session.world, vm = session.vm
        let base = vm.tick                                   // the fixture counts ticks from the end of the tick of the first CHAOS load
        var sawZap = false, maxZapProcesses = 0

        for tick in 0...finalTick {
            precondition(vm.tick - base == tick)
            for setup in setups where setup["tick"] as? Int == tick {
                for (name, value) in try #require(setup["figures"] as? JSON) {
                    let pose = try #require(value as? JSON)
                    let figure = try #require(world.figure(name))
                    let position = try #require(pose["position"] as? [Double])
                    figure.pos = V3(position[0], position[1], position[2])
                    figure.heading = try #require(pose["heading"] as? Double)
                }
            }
            for event in inputs where (event["tick"] as! Int) + (event["ticks"] as! Int) == tick {
                world.keyUp(event["scan"] as! Int, mods: 0)
            }
            for event in inputs where event["tick"] as? Int == tick {
                world.keyDown(event["scan"] as! Int, mods: event["mods"] as! Int)
            }
            sawZap = sawZap || world.figures["FIRSTBOT"]?.motion == "ZAPPED"
            maxZapProcesses = max(maxZapProcesses, vm.processes.filter {
                !$0.done && $0.block.name.uppercased() == "DR_ZAP3_FIRSTBOT"
            }.count)
            for checkpoint in checkpoints where checkpoint["tick"] as? Int == tick {
                #expect(world.currentCamera == checkpoint["camera"] as? String, "camera at tick \(tick)")
                let figures = try #require(checkpoint["figures"] as? JSON)
                #expect(Set(world.allFigureNames) == Set(figures.keys), "figures at tick \(tick)")
                for (name, value) in figures {
                    let expected = try #require(value as? JSON)
                    let figure = try #require(world.figures[name])
                    #expect(figure.motion == expected["motion"] as? String, "\(name) motion at tick \(tick)")
                    if let position = expected["position"] as? [Double] {
                        let actual = try #require(figure.pos)
                        #expect(zip([actual.x, actual.y, actual.z], position).allSatisfy { abs($0 - $1) < 0.001 },
                                "\(name) position at tick \(tick)")
                    }
                }
            }
            if tick < finalTick { session.tick() }
        }
        #expect(sawZap && maxZapProcesses == 1)
        #expect(world.figures["FIRSTBOT"] == nil)
        #expect(vm.objectRecord("FIRSTBOT")[0] == .int(-666))
        #expect(vm.objectRecord("LEX")[0] == .int(100))
        #expect(world.currentCamera == "BLK1")
    }
}
