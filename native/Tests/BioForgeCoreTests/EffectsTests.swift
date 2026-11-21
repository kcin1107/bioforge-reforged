// Effects (WorldEffects.swift) against re/interp/test_effects.py: MAKEFLATOBJECT lifetimes, DELETE, the fixed object-form point and the drawn
// sprite; EXPLODE's 150-tick wait, CONTINUE and the hidden figure; THROWCURITEM's velocity and the free-item physics up to the TEMPLE grenade
// bouncing off the wall, with the same cases and the same numbers.
import Foundation
import Testing
@testable import BioForgeCore

private let effectsScript = """
{ EXPLTEST
\t_ex = 1
\tEXPLODE CURFIG
\t_ex = 2
}
{ WAITTEST
\t_ex = 1
\tWAIT 150
\t_ex = 2
}
{ EXPLCONT
\t_ex = 1
\tKILL CURFIG
\tEXPLODE CURFIG CONTINUE
\t_ex = 2
}
{ EXPLOTHER
\t_ex = 1
\tEXPLODE SOMEONE
\t_ex = 2
}

"""

@Suite(.serialized, .enabled(if: game != nil, "BIOFORGE_DATA is not set; point it at the BioForge game folder"))
struct EffectsTests {
    /// A LANDPAD world with a VM that has only the test script blocks, and a stand-in process (current figure PLAYER) to issue calls.
    private func make() throws -> (World, ScriptVM, ScriptProcess) {
        let world = try World(resources: try #require(worldResources), level: "LANDPAD")
        let vm = ScriptVM(engine: world, defs: try ScriptDefs(game: requireGame()))
        vm.load(DecodedScript(name: "SYN_EFFECTS.scr", text: Array(effectsScript.utf8), lineStarts: [], columns: [], unresolved: []))
        return (world, vm, proc(vm, "PLAYER"))
    }

    private func proc(_ vm: ScriptVM, _ fig: String?, item: String? = nil) -> ScriptProcess {
        let block = ScriptBlock("TEST", "routine", 0, nil)
        return ScriptProcess(vm: vm, handle: 0, block: block, code: vm.code(block), ctx: ScriptContext(curFig: fig, curItem: item))
    }

    private func run(_ w: World, _ vm: ScriptVM, _ n: Int) { for _ in 0..<n { vm.tickOnce(); w.step() } }
    private func stepsUntil(_ w: World, _ vm: ScriptVM, _ limit: Int, _ pred: () -> Bool) -> Int? {
        for n in 1...limit { run(w, vm, 1); if pred() { return n } }
        return nil
    }
    private func ints(_ v: V3?) -> [Int] { [v!.x, v!.y, v!.z].map { Int($0) } }
    private func flat(_ w: World, _ p: ScriptProcess, _ args: ScriptValue...) { _ = w.call(.stmt, "MAKEFLATOBJECT", args, p) }
    private func s(_ x: String) -> ScriptValue { .str(x) }

    /// Ticks after which a flat object made from `args` is still in the list (capped at 100).
    private func lifetime(_ w: World, _ vm: ScriptVM, _ p: ScriptProcess, _ args: [ScriptValue]) -> Int? {
        w.flatObjects = []
        _ = w.call(.stmt, "MAKEFLATOBJECT", args, p)
        for n in 0..<100 {
            if w.flatObjects.isEmpty { return n - 1 }
            run(w, vm, 1)
        }
        return nil
    }

    // MARK: MAKEFLATOBJECT

    @Test func lifetimesAreTheFrameCountMinusTwo() throws {
        let (w, vm, p) = try make()
        let at: [ScriptValue] = [.int(10), .int(10), .int(50)]
        let got = [("BOOM", "PING"), ("BOOM", "WHITE"), ("TNKD", "Q4B"), ("BOOM", "BLUEC")].map { lifetime(w, vm, p, [s($0.0), s($0.1)] + at) }
        #expect(got == [1, 21, 10, 17])
    }

    @Test func aShortSequenceStaysUntilDelete() throws {
        let (w, vm, p) = try make()
        flat(w, p, s("BOOM"), s("BLANK"), .int(0), .int(0), .int(50))
        flat(w, p, s("TNKD"), s("Q4B"), .int(0), .int(0), .int(50))
        run(w, vm, 40)
        #expect(w.flatObjects.map(\.cam) == ["BOOM"])
        flat(w, p, s("tnkd"), s("q4b"), .int(0), .int(0), .int(50))
        flat(w, p, s("BOOM"), s("delete"))
        #expect(w.flatObjects.map(\.cam) == ["TNKD"])
    }

    @Test func theObjectFormKeepsThePointItHadWhenMade() throws {
        let (w, vm, p) = try make()
        _ = w.call(.stmt, "CREATEFIGURE", [s("LEX"), s("PLAYER")], p)
        let lex = try #require(w.player)
        lex.pos = V3(1000, 2000, 3000)
        flat(w, p, s("BOOM"), s("WHITE"), s("CURFIG"))
        lex.pos = V3(9, 9, 9)
        run(w, vm, 3)
        #expect(w.flatObjects.map(\.point) == [[1000, 2000, 3000]])
        flat(w, p, s("BOOM"), s("WHITE"), s("NO_SUCH_OBJECT"))
        #expect(w.flatObjects.count == 1)
        flat(w, p, s("BOOM"), s("NOPE"), .int(1), .int(2), .int(3))
        #expect(w.flatObjects.count == 1 && w.warnings.count == 1)
    }

    @Test func aFlatSpriteIsDrawnUnscaledAtItsTopLeft() throws {
        let (w, vm, p) = try make()
        var plain = Framebuffer(), img = Framebuffer()
        w.render(camera: "CE24", into: &plain)
        flat(w, p, s("BOOM"), s("WHITE"), .int(160), .int(100), .int(50))
        run(w, vm, 1)                                           // frame 2: 15 x 21, hot spot (-52, -31); W, H = the largest frame
        let f = try #require(w.flatObjects.first)
        let fr = f.frames[f.frame]
        let x0 = 160 - f.w / 2 - fr.hotX, y0 = 100 - f.h / 2 - fr.hotY
        w.render(camera: "CE24", into: &img)
        let got: [Int] = [f.frame, fr.width, fr.height, f.w, f.h, x0, y0]
        let want: [Int] = [2, 15, 21, 112, 91, 156, 86]
        #expect(got == want)
        var drawn = 0, changed = 0, inside = 0
        for y in 0..<fr.height { for x in 0..<fr.width where fr.mask[y * fr.width + x] != 0 {
            drawn += 1
            #expect(img.pixels[(y0 + y) * 320 + x0 + x] == fr.pixels[y * fr.width + x])
        } }
        for i in 0..<img.pixels.count where img.pixels[i] != plain.pixels[i] {
            changed += 1
            let (x, y) = (i % 320, i / 320)
            if x >= x0 && x < x0 + fr.width && y >= y0 && y < y0 + fr.height { inside += 1 }
        }
        #expect(drawn > 0 && changed > 0 && inside == changed)
    }

    // MARK: EXPLODE

    private func spawn(_ vm: ScriptVM, _ block: String, _ fig: String) { vm.spawn(block, ctx: ScriptContext(curFig: fig, curItem: nil, owner: "level")) }

    @Test func explodeWaits150TicksAndHidesTheFigureAndItsItems() throws {
        let (w, vm, p) = try make()
        _ = w.call(.stmt, "CREATEFIGURE", [s("LEX"), s("TARGET1")], p)
        let fig = try #require(w.figures["TARGET1"])
        fig.pos = V3(0, 0, 0)
        let item = Item(name: "HELD", type: "FORK", owner: "TARGET1")
        item.slot = "RTHAND"
        w.items["HELD"] = item
        spawn(vm, "EXPLTEST", "TARGET1")
        #expect(vm.globals["_ex"] == .int(1) && fig.exploded && item.hidden)
        let n = stepsUntil(w, vm, 300) { vm.globals["_ex"] == .int(2) }
        spawn(vm, "WAITTEST", "TARGET1")
        #expect(stepsUntil(w, vm, 300) { vm.globals["_ex"] == .int(2) } == n)            // the same wait as WAIT 150
        #expect(n == 151 && fig.hidden && w.warnings.isEmpty)
    }

    @Test func continueDoesNotWaitAndSurvivesAKill() throws {
        let (w, vm, p) = try make()
        _ = w.call(.stmt, "CREATEFIGURE", [s("LEX"), s("TARGET1")], p)
        spawn(vm, "EXPLCONT", "TARGET1")
        #expect(vm.globals["_ex"] == .int(2) && w.warnings.isEmpty)
    }

    @Test func aFigureThatIsNotCurrentIsAnErrorWithoutAWait() throws {
        let (w, vm, p) = try make()
        _ = w.call(.stmt, "CREATEFIGURE", [s("LEX"), s("TARGET1")], p)
        spawn(vm, "EXPLOTHER", "TARGET1")
        #expect(vm.globals["_ex"] == .int(2) && w.warnings.count == 1 && w.figures["TARGET1"]?.exploded == false)
    }

    // MARK: shrapnel (test_effects.py Shrapnel)

    private func bot(_ w: World, _ p: ScriptProcess) throws -> Figure {
        w.rng = PyRandom(seed: 7)
        _ = w.call(.stmt, "CREATEFIGURE", [s("TOWERBOT"), s("BOT")], p)
        let fig = try #require(w.figures["BOT"])
        fig.gravity = false
        fig.pos = V3(83578, -82740, -1549)
        _ = fig.setMotion("EXPLODE", loop: false)                    // the dying pose
        fig.area = 21                                               // PAD01 (LANDPAD)
        return fig
    }

    @Test func aKillThenExplodeThrowsOneFragmentPerTenFacesWithOneToFiveFaces() throws {
        let (w, vm, p) = try make()
        let fig = try bot(w, p)
        spawn(vm, "EXPLCONT", "BOT")                                // KILL CURFIG, EXPLODE CURFIG CONTINUE: the killed object still has its pose
        #expect(w.figures["BOT"] == nil && fig.assets.assets.mesh.polys.count == 62)
        #expect(w.fragments.map { $0.mesh.polys.count } == [1, 2, 3, 4, 5, 1])        // 6 = ceil((62 - 10) / 10)
    }

    @Test func velocitiesAndLivesAreFourDrawsEachFromTheSharedStream() throws {
        let (w, vm, p) = try make()
        _ = try bot(w, p)
        var ref = PyRandom(seed: 7)
        let clock = w.gameTick * 2
        spawn(vm, "EXPLTEST", "BOT")
        #expect(w.fragments.count == 6)
        for (k, f) in w.fragments.enumerated() {
            let n = k % 5 + 1
            var v = [ref.randint(0, 512) - 256, ref.randint(0, 514) - 257, ref.randint(0, 516) - 258]
            let length = Double(v.reduce(0) { $0 + $1 * $1 }).squareRoot()
            v = v.map { (Int(Double($0 << 8) / length) * 4505) >> 8 }
            let end = clock + 60 * (5 - n) + ref.randint(0, 59)
            #expect(f.vel == v && f.end == end)
            let mag = Double(v.reduce(0) { $0 + $1 * $1 }).squareRoot()
            #expect(mag > 4400 && mag < 4600)
        }
        #expect(w.rng.next32() == ref.next32())                      // exactly 4 * 6 draws
    }

    @Test func aFragmentDiesAfterItsLife() throws {
        let (w, vm, p) = try make()
        _ = try bot(w, p)
        spawn(vm, "EXPLTEST", "BOT")
        let life = w.fragments.map { $0.end - w.gameTick * 2 }.max()!
        run(w, vm, life / 2 - 2)
        #expect(!w.fragments.isEmpty)
        run(w, vm, 6)
        #expect(w.fragments.isEmpty)
    }

    @Test func theFragmentsAreDrawnAsPolygons() throws {
        let (w, vm, p) = try make()
        let fig = try bot(w, p)
        let cam = try #require(w.data.cameras["PAD7"])
        fig.viewCams = nil; fig.area = nil
        fig.pos = cam.pos + cam.rows[1] * 8000                       // straight ahead of the camera (row 1 is its axis)
        spawn(vm, "EXPLTEST", "BOT")
        var with = Framebuffer(), without = Framebuffer()
        w.render(camera: "PAD7", into: &with)
        w.fragments = []
        w.render(camera: "PAD7", into: &without)
        #expect(with.pixels != without.pixels)
    }

    @Test func aFragmentBouncesOffItsAreaBoxAndFalls() throws {
        let (w, _, _) = try make()
        let box = w.data.phys[21]
        let lo = [Int(box.lo.x), Int(box.lo.y), Int(box.lo.z)], hi = [Int(box.hi.x), Int(box.hi.y), Int(box.hi.z)]
        let mid = [lo[0] + 100, (lo[1] + hi[1]) / 2, (lo[2] + hi[2]) / 2]
        let mesh = try #require(w.asset("TOWERBOT")).assets.mesh
        let f = Fragment(mesh: mesh,
                         rel: [], pos: mid, vel: [-2560, 0, -2000], end: 1_000_000_000, area: 21)
        w.fragments = [f]
        w.tickFragments()
        #expect(f.pos[0] == lo[0] + 100 && f.vel[0] == 2560)         // 100 - 250 is outside: the old x stays, vx flips
        #expect(f.pos[2] == mid[2] + ((-2000 * 25) >> 8) && f.vel[2] == -2000 - 240)       // gravity 240 a frame, no cap
        f.pos[2] = lo[2] + 10
        f.vel[2] = -2000
        w.tickFragments()
        #expect(f.vel[2] == -((-2000 * 230) >> 8) - 240)             // below -0x400: lost 230/256, then flipped
    }

    // MARK: THROWCURITEM

    /// TUNROOM with Lex at PIL_BASE (the temple floor) holding a grenade, facing `heading`.
    private func tunroom(_ heading: Double) throws -> (GameSession, Figure, Item) {
        let sess = try GameSession(resources: try #require(worldResources), level: "TUNROOM")
        let w = sess.world
        _ = w.call(.stmt, "CREATEFIGURE", [.str("LEX"), .str("PLAYER")], proc(sess.vm, "PLAYER"))
        let lex = try #require(w.player)
        let base = try #require(w.data.waypoints["PIL_BASE"])
        lex.pos = base + V3(0, 0, Double(lex.assets.footOffset))
        lex.heading = heading
        w.settle(lex)
        let grenade = Item(name: "GRENADE", type: "GRENADE", owner: nil)
        w.items["GRENADE"] = grenade
        #expect(w.attachItem(lex, grenade))
        return (sess, lex, grenade)
    }

    @Test func throwAddsTheVelocityOfALeapAlongMinusRow1() throws {
        let (sess, lex, g) = try tunroom(-90)
        let w = sess.world
        let p = proc(sess.vm, "PLAYER", item: "GRENADE")
        _ = w.call(.stmt, "THROWCURITEM", [.int(0), .int(-12)], p)
        #expect(g.owner == nil && g.slot == nil && ints(g.pos) == [8276, -28035, -10107] && g.vel == [245, 0, 0])
        #expect(g.extent == [102, 102, 102] && g.bouncy && g.gravity && g.elasticity == 110)
        _ = w.call(.stmt, "THROWCURITEM", [.int(0), .int(-12)], p)               // added, not assigned
        #expect(g.vel == [490, 0, 0])
        _ = lex
    }

    @Test func throwErrors() throws {
        let (sess, lex, g) = try tunroom(0)
        let w = sess.world
        _ = w.call(.stmt, "THROWCURITEM", [.int(0), .int(-12)], proc(sess.vm, "PLAYER"))                  // no current item
        _ = w.call(.stmt, "THROWCURITEM", [.int(0), .int(-12)], proc(sess.vm, nil, item: "GRENADE"))      // no current figure
        #expect(w.warnings.count == 2 && g.owner == lex.name)
    }

    @Test func grenadeFliesStraightWithoutGravityAndBouncesOffTheWall() throws {
        let (sess, _, g) = try tunroom(-90)
        let w = sess.world, vm = sess.vm
        vm.spawn("GRENADE_FIRE", ctx: ScriptContext(curFig: "PLAYER", curItem: "GRENADE", owner: "level"))
        #expect(!g.gravity && g.vel == [245, 0, 0] && ints(g.pos) == [8276, -28035, -10107])
        let p = proc(vm, "PLAYER", item: "GRENADE")
        var seen: [Int] = [], tick = 0
        for t in 1..<60 {
            run(w, vm, 1)
            guard case .int(let vx) = w.call(.function, "VELOCITYX", [.str("CURITEM")], p) else { break }
            seen.append(vx)
            tick = t
            if vx != 245 { break }
        }
        #expect(tick == 34 && seen.last == -139 && seen[seen.count - 2] == 245)
        #expect(ints(g.pos) == [16361, -28035, -10107] && g.vel == [-139, 0, 0] && g.bouncy)
        run(w, vm, 5)
        #expect(!w.items.contains("GRENADE"))                  // GRENADEENTERTUBE saw the change, was away from the tube and removed the item
    }

    @Test func aGravityItemFallsAndAPlainOneStopsOnTheFloor() throws {
        let (sess, _, _) = try tunroom(0)
        let w = sess.world, vm = sess.vm
        let item = Item(name: "ALBAT", type: "ALBAT", owner: nil)
        item.pos = V3(8142, -27403, -8000); item.matrix = .identity
        w.items["ALBAT"] = item
        _ = w.call(.stmt, "SETVELOCITY", [.str("CURITEM"), .int(50), .int(0), .int(-1)], proc(vm, "PLAYER", item: "ALBAT"))
        run(w, vm, 1)
        #expect(ints(item.pos) == [8192, -27403, -8103] && item.vel == [50, 0, -103])
        let n = stepsUntil(w, vm, 30) { !item.vel.contains { $0 != 0 } }
        #expect(n == 7 && ints(item.pos) == [8517, -27403, -11271] && item.vel == [0, 0, 0])
    }

    @Test func leapAndStopvelocityWorkOnItems() throws {
        let (sess, _, _) = try tunroom(0)
        let w = sess.world
        let item = Item(name: "G2", type: "GRENADE", owner: nil)
        item.pos = V3(8142, -27403, -11672); item.matrix = .identity
        w.items["G2"] = item
        let p = proc(sess.vm, "PLAYER", item: "G2")
        _ = w.call(.stmt, "GRAVITY", [.str("CURITEM"), .str("OFF")], p)
        _ = w.call(.stmt, "LEAP", [.str("CURITEM"), .str("TMP_PT"), .int(0), .int(12)], p)
        #expect(item.vel == [237, -4, -61] && w.call(.function, "VELOCITYX", [.str("CURITEM")], p) == .int(237) && !item.gravity)
        _ = w.call(.stmt, "STOPVELOCITY", [.str("CURITEM")], p)
        #expect(item.vel == [0, 0, 0] && w.call(.function, "VELOCITYX", [.str("CURITEM")], p) == .int(0))
    }
}
