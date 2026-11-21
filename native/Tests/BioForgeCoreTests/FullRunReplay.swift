// The recorded full run (Fixtures/full_run.json, new game -> EXIT), shared by FullRunTests and MonkeyTests: one op applied to a session.
import Foundation
import Testing
@testable import BioForgeCore

enum FullRunReplay {
    /// Applies one op of the recorded run to the session; a `save_check` is handed to `saveCheck`.
    static func apply(_ op: [Any], _ s: GameSession, saveCheck: ([Any]) throws -> Void) throws {
        let w = s.world, vm = s.vm
        switch op[1] as! String {
        case "save_check": try saveCheck(op)
        case "key_down": w.keyDown(op[2] as! Int, mods: op[3] as! Int)
        case "key_up": w.keyUp(op[2] as! Int, mods: op[3] as! Int)
        case "key_event": w.keyEvent(scan: op[2] as! Int, mods: op[3] as! Int)
        case "pointer_move": w.monitor?.pointerMove(x: op[2] as! Int, y: op[3] as! Int)
        case "settle_pointer": w.monitor?.settlePointer()
        case "mouse_down": w.monitor?.mouseDown()
        case "mouse_up": w.monitor?.mouseUp()
        case "press": w.monitor?.press(op[2] as! String)
        case "release": w.monitor?.release(op[2] as! String)
        case "fire_event": w.fireEvent(op[2] as! String)
        case "fire": vm.fire(op[2] as! String, owner: op[3] as! String)
        case "spawn": vm.spawn(op[2] as! String, ctx: ScriptContext(curFig: op[4] as? String, curItem: op[5] as? String))
        case "seed": w.rng = PyRandom(seed: op[2] as! Int)
        case "ai": w.cmdAI(try #require(w.figure(op[2] as! String)), op[3] as! Bool)
        case "set_pos":
            let p = op[3] as! [Double]
            w.setPos(try #require(w.figure(op[2] as! String)), V3(p[0], p[1], p[2]), raw: op[4] as! Bool)
        case "set_motion": try #require(w.figure(op[2] as! String)).setMotion(op[3] as! String, loop: op[4] as! Bool)
        case "edit":
            let key = op[3] as! String
            switch op[2] as! String {
            case "global": vm.globals[key] = .int(op[4] as! Int)
            case "object":
                for (i, value) in (op[4] as! [Int]).enumerated() {
                    if case .int(let old) = vm.objectRecord(key)[i] { vm.addToObject(key, i, value - old) }
                }
            case "figure":
                let f = try #require(w.figures[key]), v = op[4] as! [String: Any]
                if let p = v["pos"] as? [Double] { f.pos = V3(p[0], p[1], p[2]) } else { f.pos = nil }
                f.heading = v["heading"] as! Double
                f.gravity = v["gravity"] as! Bool
                f.noCollide = v["no_collide"] as! Bool
                f.combat = v["combat"] as! Bool
                f.hold = v["hold"] as! Int
                f.enemy = v["enemy"] as? String
                f.vz = v["vz"] as! Int
            default: Issue.record("no replay for the edit \(op)")
            }
        default: Issue.record("no replay for \(op)")
        }
    }
}
