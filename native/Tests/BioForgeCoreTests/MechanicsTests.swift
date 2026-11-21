// Level mechanics (WorldMechanics.swift) against re/interp/test_mechanics.py: CHANGEMYFORM, GRABCRITTER / RELEASEFROMLIMB and FREEHAND,
// driven by the shipped BEACH / ITEMS scripts, with the same cases and the same numbers.
import Foundation
import Testing
@testable import BioForgeCore

private let mechanicsScript = """
{ MECHFORM
\tSETCURRENTFIGURE PLAYER
\tIF (ISMYFORM LEX) OR (ISMYFORM LEXMIR) THEN
\t\t{
\t\tCHANGEMYFORM HARD
\t\t}
\tELSE
\t\t{
\t\tCHANGEMYFORM LEX
\t\t}
\tCALL LEX_WOUNDS
\t_form_done = 1
}
{ REFSHOT
\t< HAS_GRAVITY = 0 >
\t< IS_BOUNCY = 0 >
\t< ELASTICITY = 0 >
\t< IS_REFLECTIVE = 0 >
\t< EXTENT = ( 20, 20, 20 ) >
}
{ REFSHOT_HIT_WALL
\t_ref_state = 1
\tWAIT 30
\t_ref_state = 2
}
{ REFSHOT2
\t< HAS_GRAVITY = 0 >
\t< IS_BOUNCY = 0 >
\t< ELASTICITY = 0 >
\t< IS_REFLECTIVE = 0 >
\t< EXTENT = ( 20, 20, 20 ) >
}
{ REFSHOT2_HIT_WALL
\t_ref_state = 1
\tSETCURRENTFIGURE PLAYER
\tSETREFERENT CURFIG
\tWAIT 30
\t_ref_state = 2
}
{ FREEHANDS
\tSETCURRENTFIGURE PLAYER
\tIF ISCARRYINGANYTHING LTHAND THEN
\t\tFREEHAND LTHAND
\tIF ISCARRYINGANYTHING RTHAND THEN
\t\tFREEHAND RTHAND
\t_fh_done = 1
}

"""

@Suite(.serialized, .enabled(if: game != nil, "BIOFORGE_DATA is not set; point it at the BioForge game folder"))
struct MechanicsTests {
    private func load(_ vm: ScriptVM) {
        vm.load(DecodedScript(name: "SYN_MECHANICS.scr", text: Array(mechanicsScript.utf8), lineStarts: [], columns: [], unresolved: []))
    }

    private func proc(_ vm: ScriptVM, _ fig: String = "PLAYER", item: String? = nil) -> ScriptProcess {
        let block = ScriptBlock("TEST", "routine", 0, nil)
        return ScriptProcess(vm: vm, handle: 0, block: block, code: vm.code(block), ctx: ScriptContext(curFig: fig, curItem: item))
    }

    /// BEACH with Lex (player) at ZIP1_A and the test blocks loaded.
    private func beach() throws -> (GameSession, Figure) {
        let s = try GameSession(resources: try #require(worldResources), level: "BEACH")
        load(s.vm)
        let w = s.world, p = proc(s.vm)
        _ = w.call(.stmt, "CREATEFIGURE", [.str("LEX"), .str("PLAYER")], p)
        let lex = try #require(w.player)
        let a = try #require(w.scriptPoint(p, .str("ZIP1_A")))
        lex.pos = V3(Double(a[0]), Double(a[1]), Double(a[2]))
        w.settle(lex)
        return (s, lex)
    }

    private func ismyform(_ s: GameSession, _ name: String) -> ScriptValue {
        s.world.call(.function, "ISMYFORM", [.str(name)], proc(s.vm))
    }

    private func ints(_ v: V3) -> [Int] { [v.x, v.y, v.z].map { Int($0.rounded(.toNearestOrEven)) } }
    private func ints(_ v: SIMD3<Int>) -> [Int] { [v.x, v.y, v.z] }

    // MARK: CHANGEMYFORM

    /// (type, x y, heading, mesh vertices, hull lo, hull hi, MY_SPEED) as one comparable line
    private func formState(_ w: World, _ lex: Figure) -> String {
        let h = w.hull(lex)
        return "\(lex.type) \([Int(lex.pos!.x), Int(lex.pos!.y)]) \(lex.heading) \(lex.assets.assets.mesh.verts.count) \(ints(h.lo)) \(ints(h.hi)) \(lex.speed)"
    }
    private func form(_ type: String, _ xy: [Int], _ heading: Double, _ verts: Int, _ lo: [Int], _ hi: [Int], _ speed: Int) -> String {
        "\(type) \(xy) \(heading) \(verts) \(lo) \(hi) \(speed)"
    }

    @Test func theFormBlockSwapsLexAndHardAndBack() throws {
        let (s, lex) = try beach(), w = s.world
        lex.heading = 40
        let before = formState(w, lex)
        #expect(before == form("LEX", [-1177873, -1002528], 40, 159, [-1178241, -1002896, -17356], [-1177505, -1002160, -13876], 384))
        #expect(w.spawnFor(lex, "MECHFORM"))
        for _ in 0..<3 { s.tick() }
        #expect(s.vm.globals["_form_done"] == .int(1))
        #expect(formState(w, lex) == form("HARD", [-1177873, -1002528], 40, 132, [-1178241, -1002896, -17372], [-1177505, -1002160, -13830], 384))
        #expect(ismyform(s, "HARD") == .int(1) && ismyform(s, "LEX") == .int(0) && lex.motion == "STAND" && lex.assets.footOffset == 2317)
        #expect(lex.pos!.z == -15018)                                  // regrounded: support + the new foot offset (2317, was 2312)
        s.vm.globals["_form_done"] = .int(0)
        #expect(w.spawnFor(lex, "MECHFORM"))
        for _ in 0..<3 { s.tick() }
        #expect(formState(w, lex) == before)
        #expect(ismyform(s, "HARD") == .int(0) && ismyform(s, "LEX") == .int(1) && lex.pos!.z == -15023)
    }

    @Test func aChangedFormReadsItsArmourByTheFormName() throws {       // FUN_1088_2a87: Lex's instance block (IMPACT_ARMOR 0) must not shadow HARD's (5)
        let (s, lex) = try beach(), w = s.world
        func hp() -> Int { if case .int(let v)? = s.vm.objects["LEX"]?[0] { return Int(v) }; return 0 }
        var before = hp()
        w.damage(lex, nil, 24, 0, 6, false)
        let taken = before - hp()
        #expect(w.spawnFor(lex, "MECHFORM"))
        for _ in 0..<3 { s.tick() }
        before = hp()
        w.damage(lex, nil, 24, 0, 6, false)
        #expect(taken - (before - hp()) == 5)
    }

    @Test func theHardsuitMachineScriptChangesTheForm() throws {
        let (s, lex) = try beach(), w = s.world
        #expect(w.spawnFor(lex, "HARDSUITMACHINE"))
        var ticks = 0
        while lex.type == "LEX" && ticks < 400 { s.tick(); ticks += 1 }
        #expect(ticks == 106 && lex.type == "HARD" && w.level == "DIGSITE" && ismyform(s, "HARD") == .int(1) && s.vm.globals["_digsite"] == .int(3))
    }

    @Test func theMotionIsRemappedByNameElseLexStands() throws {
        let (s, lex) = try beach(), w = s.world
        let p = proc(s.vm)
        lex.setMotion("WALK", loop: true)
        lex.idx = 5
        _ = w.call(.stmt, "CHANGEMYFORM", [.str("HARD")], p)
        #expect(lex.motion == "WALK" && lex.idx == 5 && lex.frames?.count == w.asset("HARD")!.motion("WALK")!.frames.count)
        let hard = try #require(w.asset("HARD")), lexAssets = try #require(w.asset("LEX"))
        let onlyLex = try #require(lexAssets.assets.motions.first { hard.motion($0.name) == nil }).name
        _ = w.call(.stmt, "CHANGEMYFORM", [.str("LEX")], p)
        lex.setMotion(onlyLex, loop: true)
        _ = w.call(.stmt, "CHANGEMYFORM", [.str("HARD")], p)
        #expect(lex.motion == "STAND" && lex.idx == 0)
    }

    @Test func decalsGoWithTheOldModel() throws {
        let (s, lex) = try beach()
        lex.decals["X"] = ("ON", 1, "LEX")
        _ = s.world.call(.stmt, "CHANGEMYFORM", [.str("HARD")], proc(s.vm))
        #expect(lex.decals.isEmpty)
    }

    @Test func formErrorsChangeNothing() throws {
        let (s, lex) = try beach(), w = s.world
        for (fig, args) in [("NOBODY", [ScriptValue.str("HARD")]), ("PLAYER", []), ("PLAYER", [.str("NOSUCHFORM")])] {
            _ = w.call(.stmt, "CHANGEMYFORM", args, proc(s.vm, fig))
            #expect(lex.type == "LEX" && lex.assets.assets.mesh.verts.count == 159)
        }
        #expect(w.warnings.filter { $0.contains("CHANGEMYFORM") } == ["CHANGEMYFORM: no current figure (error 0x4d)", "CHANGEMYFORM: needs a form name (error 0x64)",
                                                                       "CHANGEMYFORM NOSUCHFORM: no such form (error 0x20)"])
    }

    // MARK: GRABCRITTER / RELEASEFROMLIMB

    /// The world position of a limb end of `beast` in its current pose.
    private func limbPoint(_ beast: Figure, _ limb: String) -> V3 {
        let sk = beast.assets.assets.skeleton, li = sk.limbs.firstIndex { $0.name.uppercased() == limb }!
        let (start, rot) = sk.solve(beast.frames![min(beast.idx, beast.frames!.count - 1)])
        let end = start[li] + rot[li].r[1] * Double(sk.limbs[li].length)
        return Scene.place([end], at: beast.pos!, yaw: -beast.heading)[0]
    }

    private func setupBeast() throws -> (GameSession, Figure, Figure) {
        let (s, lex) = try beach()
        let beast = try #require(s.world.figure("ACIDD"))
        s.vm.globals["_FluffyRisen"] = .int(1)
        #expect(s.world.spawnFor(beast, "READY_ACID"))
        for _ in 0..<199 { s.tick() }
        s.world.scriptAuto = false
        s.world.setCamera("BCHK", "test")                    // a viewing camera: on BCH9 the hide pass has stopped him (1130:050d), and HIT_LEX wants him in STAND
        s.tick()
        return (s, lex, beast)
    }

    /// AI_BEAST HIT_LEX (the shipped script): GRAB, GRABCRITTER PLAYER RFINGER1, SWALLOW, WAIT 3 SECONDS, RELEASEFROMLIMB, then
    /// GO 6666 6666 6666. Lex hovers (gravity off) at the spot the CLAW reaches in the GRAB motion, so the 2DDISTFROMITEM poll passes.
    @Test func hitLexCarriesLexOnTheSwallowFingerAndLetsGo() throws {
        let (s, lex, beast) = try setupBeast(), w = s.world
        lex.gravity = false
        lex.pos = V3(-1104211, -1069482, -17274)
        #expect(w.spawnFor(beast, "HIT_LEX"))
        var seen: [Int: (String?, Int, [Int])] = [:], held: [Int] = []
        for t in 1..<112 {
            s.tick()
            if let h = lex.limbHolder {
                held.append(t)
                #expect(h.holder == "ACIDD" && h.limb == "RFINGER1")
                #expect(ints(lex.pos!) == ints(limbPoint(beast, "RFINGER1")))
                #expect(lex.noCollide)
            }
            seen[t] = (beast.motion, beast.idx, ints(lex.pos!))
        }
        // the x/y values below follow the beast's heading: `TURN ANGLEFROMENEMY ()` (AI_BEAST.scr:151) now turns it to face Lex (-90), 10a0:19e6
        #expect(held.first == 17 && held.last == 106)
        #expect(seen[16]! == ("GRAB", 2, [-1104211, -1069482, -17274]))
        #expect(seen[17]! == ("SWALLOW", 0, [-1110263, -1066104, -17086]))
        #expect(seen[28]! == ("SWALLOW", 1, [-1112287, -1065642, -16810]))
        #expect(seen[48]! == ("SWALLOW", 4, [-1108527, -1066904, -15089]))
        #expect(seen[68]! == ("SWALLOW", 7, [-1107832, -1065645, -2668]))      // he rises with the finger
        #expect(seen[106]! == ("SWALLOW", 12, [-1108633, -1065428, -1264]))
        #expect(lex.limbHolder == nil)
        #expect(seen[107]!.2 == [1706496, 1706496, 1706496 + 40])                  // released, then GO 6666 6666 6666 parks him (x, y, z << 8)
        #expect(w.warnings.isEmpty)
    }

    @Test func grabAndReleaseByStatements() throws {
        let (s, lex, _) = try setupBeast(), w = s.world
        let p = proc(s.vm, "ACIDD")
        _ = w.call(.stmt, "GRABCRITTER", [.str("PLAYER"), .str("RFINGER1")], p)
        #expect(lex.limbHolder?.holder == "ACIDD" && lex.limbHolder?.limb == "RFINGER1")
        #expect(p.curFig == "ACIDD")
        _ = w.call(.stmt, "RELEASEFROMLIMB", [.str("RFINGER2")], p)           // another limb: nothing attached there, silent
        #expect(lex.limbHolder?.limb == "RFINGER1")
        _ = w.call(.stmt, "RELEASEFROMLIMB", [.str("RFINGER1")], p)
        #expect(lex.limbHolder == nil)
        #expect(w.warnings.isEmpty)
    }

    @Test func grabErrors() throws {
        let (s, lex, _) = try setupBeast(), w = s.world
        w.warnings.removeAll()
        _ = w.call(.stmt, "GRABCRITTER", [.str("PLAYER")], proc(s.vm, "ACIDD"))
        _ = w.call(.stmt, "GRABCRITTER", [.str("PLAYER"), .str("RFINGER1")], proc(s.vm, "NOBODY"))
        _ = w.call(.stmt, "GRABCRITTER", [.str("NOBODY"), .str("RFINGER1")], proc(s.vm, "ACIDD"))          // unknown object: silent
        _ = w.call(.stmt, "RELEASEFROMLIMB", [], proc(s.vm, "ACIDD"))
        _ = w.call(.stmt, "RELEASEFROMLIMB", [.str("RFINGER1")], proc(s.vm, "NOBODY"))
        _ = w.call(.stmt, "RELEASEFROMLIMB", [.str("NOSUCHLIMB")], proc(s.vm, "ACIDD"))
        #expect(lex.limbHolder == nil)
        #expect(w.warnings == ["GRABCRITTER: needs an object and a limb (error 0x123)", "GRABCRITTER: no current figure (error 0x4d)",
                               "RELEASEFROMLIMB: needs a limb (error 0x4f)", "RELEASEFROMLIMB: no current figure (error 0x4d)",
                               "RELEASEFROMLIMB NOSUCHLIMB: ACIDD has no such limb (error 0x126)"])
    }

    // MARK: FREEHAND

    private func hands() throws -> (GameSession, Figure) {
        let (s, lex) = try itemWorld()
        load(s.vm)
        let w = s.world
        w.placeItem(lex, w.items["FORK"]!, "LTHAND")
        w.placeItem(lex, w.items["BLASTER"]!, "RTHAND")
        return (s, lex)
    }

    @Test func lthandIsStowedAtOnceRthandIsPutDownWithTheAnimation() throws {
        let (s, lex) = try hands(), w = s.world
        let fork = w.items["FORK"]!, blaster = w.items["BLASTER"]!
        #expect(w.spawnFor(lex, "FREEHANDS"))
        s.run(1)
        #expect(fork.owner == "LEX" && fork.slot == "INVENTORY" && fork.pos == nil)
        #expect(lex.motion == "PUT_DOWN_RTHAND" && blaster.slot == "RTHAND" && s.vm.globals["_fh_done"] == nil)
        let dropped = s.until { blaster.owner == nil }
        #expect(dropped == 22 && lex.motion == "PUT_DOWN_RTHAND" && lex.idx == 15 && s.vm.globals["_fh_done"] == nil)
        let done = s.until { s.vm.globals["_fh_done"] == .int(1) }
        #expect(done == 22 && blaster.owner == nil)            // the drop came a frame earlier, the motion's end did not
    }

    @Test func fluteUseDropsTheFluteBeforePlaying() throws {
        let (s, lex) = try itemWorld()
        let w = s.world, flute = w.items["FLUTE"]!
        w.placeItem(lex, flute, "RTHAND")
        #expect(w.spawnFor(lex, "FLUTE_USE", item: flute))
        let n = s.until { lex.motion == "START_FLUTE" }
        #expect(n == 45 && flute.owner == nil)
    }

    @Test func handErrorsAndEmptyHands() throws {
        let (s, lex) = try hands(), w = s.world
        _ = w.call(.stmt, "FREEHAND", [], proc(s.vm))
        _ = w.call(.stmt, "FREEHAND", [.str("RTHAND")], proc(s.vm, "NOBODY"))
        #expect(w.warnings == ["FREEHAND: needs a hand (error 0x4f)", "FREEHAND: no current figure (error 0x4d)"])
        w.items["BLASTER"]!.slot = "LTHAND"
        _ = w.call(.stmt, "FREEHAND", [.str("RTHAND")], proc(s.vm))          // nothing in the right hand
        #expect(lex.motion == "STAND")
    }

    // MARK: ANIMATE

    private func advance(_ mode: Int, _ n: Int, _ steps: Int, frame: Int = 0, period: Int = 1) -> ([Int], Int) {
        var st = TextureAnim(frame: frame, mode: mode, period: period, next: 0, n: n)
        var out: [Int] = []
        for clock in 0..<steps {
            World.advanceTexture(&st, clock: clock) { _, b in b }
            out.append(st.frame)
        }
        return (out, st.mode)
    }

    @Test func theTextureStateMachine() {
        #expect(advance(5, 6, 14) == ([1, 2, 3, 4, 5, 4, 3, 2, 1, 0, 1, 2, 3, 4], 5))     // INCREMENT YOYO: the end frames show once
        #expect(advance(2, 4, 6) == ([3, 2, 1, 0, 3, 2], 2))                               // DECREMENT wraps
        #expect(advance(2 | 8, 4, 6, frame: 1) == ([0, 0, 0, 0, 0, 0], 10))                // TO_LIMIT clamps
        #expect(advance(1 | 0x20, 4, 4) == ([1, 1, 1, 1], 0))                              // ONCE: one step, then the mode is cleared
        #expect(advance(3, 5, 2) == ([4, 4], 3))                                           // RANDOM draws rand(0, n - 1)
        #expect(advance(0x10, 4, 3) == ([0, 0, 0], 16))                                    // RESET alone: no step
        #expect(advance(0, 4, 3) == ([0, 0, 0], 0))                                        // FREEZE
        #expect(advance(1, 4, 3, period: 2).0 == [1, 1, 2])                                // next = clock + period, no catch-up
    }

    @Test func theBeastAcidTextureFromReadyAcid() throws {
        let (s, _, beast) = try setupBeast()
        #expect(beast.anim["ACID0"] == TextureAnim(frame: 3, mode: 5, period: 5, next: 403, n: 6))
        var frames: [Int] = []
        for _ in 0..<30 { s.tick(); frames.append(beast.anim["ACID0"]!.frame) }
        #expect(frames == [3, 4, 4, 4, 5, 5, 5, 4, 4, 4, 3, 3, 3, 2, 2, 2, 1, 1, 1, 0, 0, 0, 1, 1, 1, 2, 2, 2, 3, 3])
    }

    @Test func theDrawnFrameIsTheAnimateState() throws {
        let (s, _) = try beach(), w = s.world
        let item = Item(name: "PFDBLST", type: "PFDBLST", owner: nil)
        w.items["PFDBLST"] = item
        let mesh = try #require(w.itemMesh("PFDBLST"))
        let (ti, frames) = try #require(mesh.frames.first { mesh.textures[$0.key].name.uppercased() == "PDFFR0" })
        func drawn() -> [UInt8] { Shading.texturePixels(mesh, anim: item.anim.mapValues(\.frame))[ti] }
        for _ in 0..<4 {
            for _ in 0..<3 { s.tick() }
            #expect(drawn() == frames[0])                                   // no ANIMATE: frame 0 at any tick
        }
        _ = w.call(.stmt, "ANIMATE", [.str("CURITEM"), .str("PDFFR0"), .str("ON"), .str("INCREMENT"), .int(4)], proc(s.vm, item: "PFDBLST"))
        var seen = Set<Int>()
        for _ in 0..<12 {
            s.tick()
            let f = item.anim["PDFFR0"]!.frame
            #expect(drawn() == frames[f])
            seen.insert(f)
        }
        #expect(seen.count > 3)
    }

    @Test func theItemAndLexTexturesFromAiLex() throws {
        let (s, lex) = try beach(), w = s.world
        let item = Item(name: "PFDBLST", type: "PFDBLST", owner: nil)
        w.items["PFDBLST"] = item
        let p = proc(s.vm, item: "PFDBLST")
        _ = w.call(.stmt, "ANIMATE", [.str("CURITEM"), .str("PDFFR0"), .str("ON"), .str("RESET"), .int(0)], p)
        #expect(item.anim["PDFFR0"] == TextureAnim(frame: 0, mode: 16, period: 15, next: 15, n: 8))
        _ = w.call(.stmt, "ANIMATE", [.str("CURITEM"), .str("PDFFR0"), .str("ON"), .str("INCREMENT"), .int(4)], p)
        #expect(item.anim["PDFFR0"] == TextureAnim(frame: 0, mode: 1, period: 4, next: 4, n: 8))
        var frames: [Int] = []
        for _ in 0..<24 { s.tick(); frames.append(item.anim["PDFFR0"]!.frame) }
        #expect(frames == [0, 1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 6, 7, 7, 0, 0, 1, 1, 2, 2, 3, 3, 4])
        _ = w.call(.stmt, "ANIMATE", [.str("CURFIG"), .str("LEXPIM"), .str("ON"), .str("INCREMENT"), .int(60)], p)
        frames = []
        for _ in 0..<70 { s.tick(); frames.append(lex.anim["LEXPIM"]!.frame) }
        #expect(stride(from: 0, to: 70, by: 5).map { frames[$0] } == [0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 1, 1, 0, 0])
        _ = w.call(.stmt, "ANIMATE", [.str("CURFIG"), .str("LEXPIM"), .str("OFF")], p)
        #expect(lex.anim["LEXPIM"] == TextureAnim(frame: 0, mode: 0, period: 15, next: 203, n: 2))
        for _ in 0..<70 { s.tick() }
        #expect(lex.anim["LEXPIM"]!.frame == 0)                                  // OFF froze it
    }

    @Test func unknownStaticAndMissingObjectsAreSilent() throws {
        let (s, lex) = try beach(), w = s.world
        let p = proc(s.vm)
        let calls: [[ScriptValue]] = [[.str("CURFIG"), .str("MDTB3"), .str("ON"), .str("INCREMENT")], [.str("CURFIG"), .str("NOSUCH"), .str("ON"), .str("INCREMENT")],
                                      [.str("NOBODY"), .str("LEXPIM"), .str("ON"), .str("INCREMENT")], [.str("CURFIG")],
                                      [.str("CURITEM"), .str("LEXPIM"), .str("ON"), .str("INCREMENT")]]
        for args in calls { _ = w.call(.stmt, "ANIMATE", args, p) }
        #expect(lex.anim.isEmpty && w.warnings.isEmpty)
        _ = w.call(.stmt, "ANIMATE", [.str("CURFIG"), .str("lexpimxx"), .str("INCREMENT")], p)                       // 8 characters at most: LEXPIMXX is no texture
        _ = w.call(.stmt, "ANIMATE", [.str("CURFIG"), .str("lexpim"), .str("RANDOM"), .str("ONCE"), .int(-5)], p)     // a number <= 0 means 15
        #expect(lex.anim["LEXPIM"] == TextureAnim(frame: 0, mode: 0x23, period: 15, next: 15, n: 2))
    }

    @Test func nurseBotLoadSetsTheNurseTexturesAndChangeMyFormClearsThem() throws {
        let (s, _) = try itemWorld(), w = s.world
        _ = w.call(.stmt, "CREATEFIGURE", [.str("NURSEBOT"), .str("NURSE_X")], proc(s.vm))
        let nurse = try #require(w.figures["NURSE_X"])
        #expect(w.spawnFor(nurse, "NURSEBOT_LOAD"))
        #expect(nurse.anim.mapValues { [$0.n, $0.mode, $0.period] } == ["SLEAKSD": [3, 1, 15], "SLEAKBA": [3, 1, 15], "SLEAKEY": [4, 1, 15], "SLEAKNE": [4, 1, 15]])
        _ = w.call(.stmt, "CHANGEMYFORM", [.str("LEX")], proc(s.vm, "NURSE_X"))
        #expect(nurse.anim.isEmpty)
    }

    // MARK: SETREFERENT

    private func shoot(_ type: String) throws -> (GameSession, Figure) {
        let (s, lex) = try beach()
        let b = try #require(s.world.scriptPoint(proc(s.vm), .str("ZIP1_B")))          // away from Lex, whose hull a shot would hit
        _ = s.world.call(.function, "FIRE", [.str(type), .str("ZIP1_B"), .str("AT"), .int((b[0] >> 8) + 2), .int(b[1] >> 8), .int(b[2] >> 8),
                                             .int(5), .int(0), .int(0), .int(0)], proc(s.vm))
        return (s, lex)
    }

    @Test func aHitProcessDiesWithItsMissile() throws {
        let (s, _) = try shoot("REFSHOT")
        for _ in 0..<6 { s.tick() }
        #expect(s.vm.globals["_ref_state"] == .int(1))
        #expect(!s.world.items.values.contains { $0 is Missile })
        for _ in 0..<40 { s.tick() }
        #expect(s.vm.globals["_ref_state"] == .int(1))                    // killed in its WAIT: it never reaches state 2
    }

    @Test func setReferentPlayerKeepsItAlive() throws {
        let (s, lex) = try shoot("REFSHOT2")
        for _ in 0..<6 { s.tick() }
        #expect(s.vm.globals["_ref_state"] == .int(1))
        let p = try #require(s.vm.procs.values.first { $0.block.name == "REFSHOT2_HIT_WALL" })
        #expect(p.referent === lex)
        for _ in 0..<40 { s.tick() }
        #expect(s.vm.globals["_ref_state"] == .int(2))
    }

    @Test func killCurItemAndUnresolvedObjects() throws {
        let (s, lex) = try beach(), w = s.world
        let item = Item(name: "PFDBLST", type: "PFDBLST", owner: nil)
        w.items["PFDBLST"] = item
        let p = try #require(s.vm.spawn("REFSHOT_HIT_WALL", ctx: ScriptContext(curFig: nil, curItem: "PFDBLST", owner: "level")))
        #expect(p.referent === item)
        let stub = proc(s.vm)
        _ = w.call(.stmt, "SETREFERENT", [.str("NOBODY")], stub)
        #expect(stub.referent == nil)
        _ = w.call(.stmt, "SETREFERENT", [.str("PLAYER")], p)
        #expect(p.referent === lex)
        p.referent = item
        p.curItem = "PFDBLST"
        _ = w.call(.stmt, "KILLCURITEM", [], p)
        #expect(p.ended && w.items["PFDBLST"] == nil)
    }

    // MARK: INCVIRTUALSECONDS / FORCERELOAD

    @Test func determineMachineSpeedFinishesAndLeavesTimeTestZero() throws {
        let (s, _) = try itemWorld(), w = s.world
        s.vm.globals["_timetest"] = .int(7)
        s.vm.spawn("DETERMINEMACHINESPEED")
        var ticks = 0
        while s.vm.procs.values.contains(where: { $0.block.name == "DETERMINEMACHINESPEED" }) && ticks < 200 { s.tick(); ticks += 1 }
        #expect(ticks == 41 && s.vm.globals["_timetest"] == .int(0) && w.speedFactor == 0)
        for want in 1...3 {
            _ = w.call(.stmt, "INCVIRTUALSECONDS", [.int(0)], proc(s.vm))
            #expect(w.speedFactor == want)
        }
        w.speedFactor = 20
        _ = w.call(.stmt, "INCVIRTUALSECONDS", [.int(0)], proc(s.vm))
        #expect(w.speedFactor == 20)
    }

    @Test func forceReloadKillsThePlayerAndOpensTheReloadDialog() throws {
        let (s, lex) = try itemWorld(), w = s.world
        let p = proc(s.vm)
        _ = w.call(.stmt, "FORCERELOAD", [], p)
        #expect(w.hitPoints(lex) == -1 && w.paused && (w.options?.flags ?? 0) & Options.mustReload == Options.mustReload && p.waitPred?() == true)
    }

    /// Twin of test_mechanics test_falling_into_the_tanks_drowns_lex: CRYTOTNK FALL (collisions off, LOADLEVEL TANKS LEX_FALL) no longer
    /// stands Lex on the TANKS walkway; he falls on and TANKDETH drowns him (live, re/out/tank_fall_live).
    @Test func fallingIntoTheTanksDrownsLex() throws {
        let (s, _) = try itemWorld(lex: (-12355, -74517), heading: 87)
        s.vm.spawn("FALL", ctx: ScriptContext(curFig: s.world.playerName))
        s.run(60)
        let lex = try #require(s.world.player), p = try #require(lex.pos)
        #expect(s.world.level == "TANKS")
        #expect([Int(p.x), Int(p.y), Int(p.z)] == [-17408, -57344, -38741] && lex.motion?.uppercased() == "DROWN" && lex.vz == 0)
    }

    /// Loading an empty slot from the reload dialog fails; the dialog comes back, or a dead Lex is left with none and no key that works.
    @Test func aFailedLoadAfterADeathReopensTheReloadDialog() throws {
        let (s, _) = try itemWorld(), w = s.world
        let dir = tempDir()
        defer { try? FileManager.default.removeItem(at: dir) }
        w.savesDir = dir
        w.forcingReload = true                                   // KILLLEX's _forcing_reload
        _ = w.call(.stmt, "FORCERELOAD", [], proc(s.vm))
        let o = try #require(w.options)
        o.activate("LOAD"); o.activate("OK")
        #expect(w.recordOptionAction(o.activate("YES")) == "load:1" && w.pendingLoad == nil)
        #expect(w.isOptionsOpen && (w.options?.flags ?? 0) & Options.mustReload != 0 && w.options?.screen == "main")
    }

    /// Twin of test_mechanics test_reload_dialog_sits_on_the_shown_picture_in_greys: KILLLEX's CAMERA SHOW STITLE, then FORCERELOAD; as in a
    /// VGA dump of the original, STITLE dimmed onto 128...145 with the buttons blended over it, RETX disabled and RETURN ignored.
    @Test func reloadDialogSitsOnTheShownPictureInGreys() throws {
        let (s, _) = try itemWorld(), w = s.world
        let p = proc(s.vm)
        _ = w.call(.stmt, "CAMERA", [.str("SHOW"), .str("STITLE")], p)
        _ = w.call(.stmt, "FORCERELOAD", [], p)
        var fb = Framebuffer()
        w.renderPresentation(into: &fb)
        #expect(fb.pixels[60 * 320 + 160] == 131 && fb.pixels[100 * 320 + 60] == 141 && fb.pixels[170 * 320 + 290] == 44)
        #expect(fb.pixels.reduce(0) { $0 + Int($1) } == 7259828)
        #expect(fb.pixels[(60 * 320 + 40)..<(60 * 320 + 280)].allSatisfy { (128...145).contains($0) })
        #expect(w.options?.activate("RETURN") == nil && w.options?.closed == false)
        w.setCamera("BLK6", "test")                                          // a real switch drops the picture
        #expect(w.shownPictureFrame() == nil)
    }

    /// Twin of test_mechanics test_o_reopens_after_escape_and_the_dialog_sits_on_the_dimmed_room.
    @Test func oReopensAfterEscapeAndTheDialogSitsOnTheDimmedRoom() throws {
        let (s, _) = try itemWorld(), w = s.world
        w.keyDown(0x18)
        w.optionKey("ESCAPE")
        #expect(!w.isOptionsOpen)
        w.keyDown(0x18)
        #expect(w.isOptionsOpen)
        var fb = Framebuffer()
        w.renderPresentation(into: &fb)
        #expect(fb.pixels[60 * 320 + 160] == 137 && fb.pixels[100 * 320 + 60] == 135 && fb.pixels.reduce(0) { $0 + Int($1) } == 7529057)
        #expect(fb.pixels[(60 * 320 + 40)..<(60 * 320 + 280)].allSatisfy { (128...145).contains($0) })
    }

    /// Twin of test_mechanics test_translucent_table: FUN_1270_174b's table (fill 41 over grey 145 -> 53).
    @Test func translucentTable() {
        let t = Framebuffer.translucent
        #expect(t[9][17] == 21 && t[0][0] == 0 && t[4][31] == 31 && t[31][5] == 31 && Framebuffer.translucent(41, over: 145) == 53)
    }

    // MARK: numeric GO

    @Test func numericCoordinatesSnapWalkAndPark() throws {
        let (s, lex) = try itemWorld(), w = s.world
        let p = proc(s.vm)
        func go(_ a: ScriptValue...) { _ = w.call(.stmt, "GO", a, p) }
        go(.int(-57), .int(-292), .int(-21))                               // CHAOSCRY: gravity on, snapped onto the floor
        #expect(ints(lex.pos!) == [-14592, -74752, -5093])
        go(.int(113), .int(-114), .int(-87), .str("WALK"))                 // CRYTOTNK
        let g = try #require(lex.go)
        #expect(g.target == V2(28928, -29184) && g.z == -5093 && g.motion == "WALK" && lex.motion == "WALK" && p.waitPred != nil)
        lex.go = nil; lex.gravity = false
        go(.int(-4935), .int(-4215), .int(-100))                           // AI_BEAST: gravity off, z used as is
        #expect(ints(lex.pos!) == [-1263360, -1079040, -25600])
        lex.gravity = true
        go(.int(6666), .int(6666), .int(6666))                             // the park: no floor there, z kept
        #expect(ints(lex.pos!) == [1706496, 1706496, 1706496])
        for _ in 0..<10 { s.tick() }
        #expect(Array(ints(lex.pos!).prefix(2)) == [1706496, 1706496])
        lex.gravity = false
        lex.pos = V3(3000, -9000, -5093)
        go(.int(110), .int(Int(lex.pos!.y) >> 8), .int(Int(lex.pos!.z) >> 8))       // LEDGE: GO 110 COORDY (CURFIG) COORDZ (CURFIG)
        #expect(Array(ints(lex.pos!).prefix(2)) == [28160, -9216])
        #expect(lex.pos!.z + Double(w.rootZ(lex)) == -5120)              // z is origin + R (10a0:1ff0)
        #expect(w.warnings.isEmpty)
    }

    @Test func anUnknownGoModifierIsAnError() throws {
        let (s, lex) = try itemWorld(), w = s.world
        let before = ints(lex.pos!)
        _ = w.call(.stmt, "GO", [.int(1), .int(2), .int(3), .str("FLY")], proc(s.vm))
        #expect(ints(lex.pos!) == before && w.warnings == ["GO FLY: unknown modifier (error 0x120)"])
    }

    @Test func aiBeastReadyAcidPlacesTheBeastWithNumbers() throws {
        let (s, _) = try beach(), w = s.world
        let beast = try #require(w.figure("ACIDD"))
        #expect(w.spawnFor(beast, "READY_ACID"))
        s.tick()
        #expect(ints(beast.pos!) == [-1263360, -1079040, -25600] && !beast.gravity && w.warnings.isEmpty)
    }

    // MARK: FLOATATHEIGHT <waypoint>

    @Test func beachBotFloatsAtItsWaypointHeight() throws {
        let (s, _) = try beach(), w = s.world
        let bot = try #require(w.figure("BCHBOT1"))
        let wp = try #require(w.data.waypoints["B_BOT1"]), x = Int(wp.x), y = Int(wp.y), z = Int(wp.z)
        #expect(bot.assets.footOffset == 544 && w.foot(bot) == 544 && w.pointFloor(x, y, z, z) == -8787)
        #expect(w.spawnFor(bot, "READY_BBOT1"))
        for _ in 0..<5 { s.tick() }
        #expect(bot.footOverride == 2074 && w.foot(bot) == 2074 && ints(bot.pos!) == [-1205185, -1069266, -6713])
        bot.gravity = true                                                 // grounding uses the new F: the origin stays at the waypoint z
        for _ in 0..<29 { s.tick(); #expect(bot.pos!.z == -6713) }
        bot.footOverride = nil
        for _ in 0..<3 { s.tick() }
        #expect(bot.pos!.z == -7325)                                       // with the type's F (544) it would sink
        #expect(w.warnings.isEmpty && w.unmodelled.isEmpty)
    }

    @Test func theOverrideFollowsChangeMyFormAndNeedsAPlacedFigure() throws {
        let (s, lex) = try beach(), w = s.world
        lex.footOverride = 99
        _ = w.call(.stmt, "CHANGEMYFORM", [.str("HARD")], proc(s.vm))
        #expect(lex.footOverride == nil && w.foot(lex) == 2317)
        _ = w.call(.stmt, "FLOATATHEIGHT", [.str("B_BOT1")], proc(s.vm, "NOBODY"))
        #expect(lex.footOverride == nil)
    }
}
