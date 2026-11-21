// Engine pieces the Caynan and Guard 1 encounters need, against re/interp/test_world.py `ChaosEncounterEngine` (NOTES "CHAOS
// encounters: Caynan and Guard 1"): the cm conversion, ATTACKRADIUS, the waypoint functions, AMBIENT / STOPAMBIENT, APPLY decals,
// SETCURRENTFIGURE by type name, the unmodelled list and the port behaviours added for the two fights.
import Foundation
import Testing
@testable import BioForgeCore

@Suite(.serialized, .enabled(if: game != nil, "BIOFORGE_DATA is not set; point it at the BioForge game folder"))
struct ChaosEncounterTests {
    /// test_world.py `ChaosEncounterEngine.setUp`: CHAOS at its INITGAME state with a VM, Lex as the player at the origin facing -y.
    private func make() throws -> (GameSession, Figure) {
        let s = try GameSession(resources: try #require(worldResources), level: "CHAOS")
        s.autoDifficulty = false
        _ = s.world.call(.stmt, "CREATEFIGURE", [.str("LEX"), .str("PLAYER")], proc(s, "PLAYER"))
        let lex = try #require(s.world.player)
        lex.noCollide = true
        lex.heading = 0
        lex.pos = V3(0, 0, 0)
        return (s, lex)
    }

    private func proc(_ s: GameSession, _ fig: String? = nil) -> ScriptProcess {
        let block = ScriptBlock("TEST", "routine", 0, nil)
        return ScriptProcess(vm: s.vm, handle: 0, block: block, code: s.vm.code(block), ctx: ScriptContext(curFig: fig))
    }

    private func cmd(_ s: GameSession, _ name: String, _ args: ScriptValue..., fig: String = "PLAYER") { _ = s.world.call(.stmt, name, args, proc(s, fig)) }

    private func ask(_ s: GameSession, _ name: String, _ args: ScriptValue..., fig: String = "PLAYER") -> Int {
        guard case .int(let v) = s.world.call(.function, name, args, proc(s, fig)) else { return Int.min }
        return v
    }

    private func run(_ s: GameSession, _ n: Int) { for _ in 0..<n { s.tick() } }

    private func ticksFor(_ w: World, _ fig: Figure) -> Int { (fig.frames!.count * w.motionDuration(fig) + World.clockPerTick - 1) / World.clockPerTick }

    @Test func cmFromUnitsIsTheInverseOfHullUnits() {
        #expect(cmFromUnits(2000) == 97)                                  // (2000 * 100 + 0x80) / 0x800
        #expect([10, 40, 43, 55, 150].map { cmFromUnits(hullUnits($0)) } == [10, 40, 43, 55, 150])
        #expect(cmFromUnits(0) == 0)
        #expect(cmFromUnits(-2000) == -97)                                // the signed divide truncates toward zero
    }

    @Test func attackRadiusIsPersonalRadius() throws {
        let (s, lex) = try make()
        let cay = try #require(s.world.figure("CAYNAN"))
        #expect(s.world.combatQuery(lex, "ATTACKRADIUS") == 40)
        #expect(s.world.combatQuery(cay, "ATTACKRADIUS") == 43)
    }

    @Test func waypointDistancesUseTheEnemyUnits() throws {
        let (s, lex) = try make()
        let wp = try #require(s.world.data.waypoints["GETMEAT"])
        lex.pos = V3(wp.x + 3000, wp.y + 4000, wp.z)
        #expect(ask(s, "2DDISTFROMWAYPOINT", .str("CURFIG"), .str("GETMEAT")) == 244)     // exact 5,000 units
        #expect(ask(s, "DISTFROMWAYPOINT", .str("CURFIG"), .str("GETMEAT")) == 245)       // approxLength: 5,032 units
        #expect(ask(s, "DISTFROMWAYPOINT", .str("LEX"), .str("GETMEAT")) == 245)          // a figure name works as well as CURFIG
        lex.pos = V3(lex.pos!.x, lex.pos!.y, lex.pos!.z + 20000)                         // z only counts in the 3D form
        #expect(ask(s, "2DDISTFROMWAYPOINT", .str("CURFIG"), .str("GETMEAT")) == 244)
        #expect(ask(s, "DISTFROMWAYPOINT", .str("CURFIG"), .str("GETMEAT")) > 900)
        #expect(s.world.warnings.isEmpty)
    }

    @Test func waypointAngleMatchesTheEnemyBearing() throws {
        let (s, lex) = try make()
        let w = s.world
        let wp = try #require(w.data.waypoints["GETMEAT"])
        for (dx, dy, expect) in [(0.0, -2000.0, 0), (2000, 0, 90), (-2000, 0, 90), (0, 2000, 180)] {   // |bearing|; facing -y: +x is to the left
            lex.pos = V3(wp.x - dx, wp.y - dy, wp.z)
            #expect(abs(ask(s, "ANGLEFROMWAYPOINT", .str("CURFIG"), .str("GETMEAT"))) == expect, "\(dx) \(dy)")
        }
        lex.pos = V3(wp.x - 2000, wp.y, wp.z)
        #expect(ask(s, "ANGLEFROMWAYPOINT", .str("CURFIG"), .str("GETMEAT")) == 90)
        let enemy = try #require(w.figure("CAYNAN"))
        enemy.pos = wp
        lex.enemy = "CAYNAN"
        #expect(ask(s, "ANGLEFROMWAYPOINT", .str("CURFIG"), .str("GETMEAT")) == w.combatQuery(lex, "ANGLEFROMENEMY"))
    }

    @Test func amInWaypointIsTheHullTouchingThePoint() throws {
        let (s, lex) = try make()
        let wp = try #require(s.world.data.waypoints["GETMEAT"])
        lex.pos = V3(wp.x, wp.y, wp.z + Double(lex.assets.footOffset))
        #expect(ask(s, "AMINWAYPOINT", .str("CURFIG"), .str("GETMEAT")) == 1)
        lex.pos = V3(lex.pos!.x + 3000, lex.pos!.y, lex.pos!.z)
        #expect(ask(s, "AMINWAYPOINT", .str("CURFIG"), .str("GETMEAT")) == 0)
    }

    @Test func unknownWaypointOrObjectWarnsAndReturnsZero() throws {
        let (s, _) = try make()
        #expect(ask(s, "DISTFROMWAYPOINT", .str("CURFIG"), .str("NOWHERE")) == 0)
        #expect(ask(s, "ANGLEFROMWAYPOINT", .str("NOBODY"), .str("GETMEAT")) == 0)
        #expect(s.world.warnings == ["DISTFROMWAYPOINT CURFIG NOWHERE: no such waypoint", "ANGLEFROMWAYPOINT NOBODY GETMEAT: no such object"])
    }

    @Test func ambientLoopsUntilReleasedAndStopAmbientLeavesOneShots() throws {
        let (s, _) = try make()
        let w = s.world
        let handle = ask(s, "AMBIENT", .str("_grd_ambient"), .int(30))
        let shot = ask(s, "SOUND", .str("_light1"), .int(100))
        #expect(w.soundLoops.contains(handle))
        run(s, 300)
        #expect(ask(s, "ISHANDLEPLAYING", .int(handle)) == 1)             // a looped sample stays valid
        cmd(s, "STOPAMBIENT", .int(shot))                                 // FUN_1028_10c9: only a voice with the loop flag
        #expect(!w.soundLoops.contains(shot))
        cmd(s, "STOPAMBIENT", .int(handle))                               // 1000:046f: plays on to the sample's end, no wrap
        #expect(w.soundReleases.map { [$0.tick, $0.handle] } == [[s.vm.tick, handle]])
        #expect(w.soundStops.isEmpty)
        // alarm4c: 43299 samples at 11025 Hz, loop 19..43136 (19 + 43117). 300 ticks in = sample 110250, wrapped to 24035; 19264 left = 52.4 ticks,
        // so the handle wakes 53 ticks on and ends on the update after, as a one-shot does
        #expect(s.vm.process(handle)?.wake == s.vm.tick + 53)
        run(s, 53)
        #expect(ask(s, "ISHANDLEPLAYING", .int(handle)) == 1)
        cmd(s, "STOPAMBIENT", .int(handle))                               // a second release changes nothing
        #expect(w.soundReleases.count == 1)
        run(s, 1)
        #expect(ask(s, "ISHANDLEPLAYING", .int(handle)) == 0)
        #expect(w.warnings.isEmpty)
    }

    @Test func applyTracksTheTextureDecalState() throws {
        let (s, _) = try make()
        let w = s.world
        let cay = try #require(w.figure("CAYNAN")), guardFig = try #require(w.figure("GUARD1"))
        func same(_ d: (mode: String, frame: Int?, prefix: String?)?, _ e: (String, Int?, String?)) -> Bool { d != nil && d!.mode == e.0 && d!.frame == e.1 && d!.prefix == e.2 }
        cmd(s, "APPLY", .str("CURFIG"), .str("CLEAR"), .str("CAHND"), .str("PICTURE"), .int(1), fig: "CAYNAN")
        #expect(cay.decals.count == 1 && same(cay.decals["CAHND"], ("CLEAR", 1, "CAY")))
        cmd(s, "APPLY", .str("CURFIG"), .str("DRAWONLY"), .str("CAHDF"), .str("PICTURE"), .int(3), fig: "CAYNAN")
        #expect(same(cay.decals["CAHDF"], ("DRAWONLY", 3, "CAY")))
        cmd(s, "APPLY", .str("CURFIG"), .str("RESTORE"), .str("CAHDF"), fig: "CAYNAN")
        #expect(Array(cay.decals.keys) == ["CAHND"])
        cmd(s, "APPLY", .str("CAYNAN"), .str("RESTORE"), .str("ALL"), fig: "PLAYER")      // the object may be named; ALL walks every texture
        #expect(cay.decals.isEmpty)
        cmd(s, "APPLY", .str("CURFIG"), .str("DRAWONLY"), .str("CHEST"), .str("PICTURE"), .int(6), .str("GRD"), fig: "GUARD1")
        cmd(s, "APPLY", .str("CURFIG"), .str("CLEAR"), .str("LHAND"), .str("PICTURE"), .int(1), .str("GRD"), fig: "GUARD1")
        #expect(guardFig.decals.count == 2 && same(guardFig.decals["CHEST"], ("DRAWONLY", 6, "GRD")) && same(guardFig.decals["LHAND"], ("CLEAR", 1, "GRD")))
        #expect(w.warnings.isEmpty)
        cmd(s, "APPLY", .str("CURFIG"), .str("DRAWONLY"), .str("NOTEXTURE"), .str("PICTURE"), .int(1), fig: "CAYNAN")
        cmd(s, "APPLY", .str("CURFIG"), .str("SCRIBBLE"), .str("CAHND"), fig: "CAYNAN")
        #expect(w.warnings == ["APPLY CAYNAN NOTEXTURE: no such texture", "APPLY SCRIBBLE: unknown mode"])
    }

    @Test func setCurrentFigureFallsBackToTheTypeName() throws {
        let (s, _) = try make()
        let w = s.world
        _ = w.figure("GUARD1")
        var p = proc(s, "PLAYER")
        #expect(w.call(.function, "SETCURRENTFIGURE", [.str("GRDCELL")], p) == .int(1))
        #expect(p.curFig == "GUARD1")                                    // GUARD1 is a GRDCELL (INDIVIDUALIZEd)
        #expect(w.call(.function, "SETCURRENTFIGURE", [.str("NOSUCHTYPE")], proc(s, "PLAYER")) == .int(0))
        p = proc(s, "PLAYER")
        #expect(w.call(.function, "SETCURRENTFIGURE", [.str("GUARD1")], p) == .int(1))   // the instance name still wins
        #expect(p.curFig == "PLAYER")
    }

    @Test func compassIsTheOrientationRowInWholeDegrees() throws {
        let (s, lex) = try make()
        for (heading, expect) in [(0.0, 0), (90, 90), (45, 45), (-135, -135), (180, 180), (-90, -90), (10.5, 10)] {
            lex.heading = heading
            #expect(ask(s, "COMPASS") == expect)
        }
        guard case .int(let none) = s.world.call(.function, "COMPASS", [], proc(s, nil)) else { Issue.record("no int"); return }
        #expect(none == 0)                                                // no current figure: 0, silently
        #expect(s.world.warnings.isEmpty)
    }

    @Test func isMyFormComparesTheTypeNameWithoutCase() throws {
        let (s, _) = try make()
        #expect(ask(s, "ISMYFORM", .str("LEX")) == 1)
        #expect(ask(s, "ISMYFORM", .str("lex")) == 1)
        #expect(ask(s, "ISMYFORM", .str("LEXMIR")) == 0)
        _ = s.world.figure("GUARD1")
        #expect(ask(s, "ISMYFORM", .str("GRDCELL"), fig: "GUARD1") == 1)    // the type, not the instance name
        #expect(ask(s, "ISMYFORM", .str("GUARD1"), fig: "GUARD1") == 0)
        #expect(ask(s, "ISMYFORM", .str("")) == 0)
        #expect(s.world.warnings == ["ISMYFORM: no form name"])
    }

    @Test func isInCombatModeReturnsFlag0x40() throws {
        let (s, lex) = try make()
        #expect(ask(s, "ISINCOMBATMODE") == 0)
        lex.combat = true
        #expect(ask(s, "ISINCOMBATMODE") == 0x40)
    }

    @Test func isKeyPressedReadsTheHeldScanCodes() throws {
        let (s, _) = try make()
        #expect(ask(s, "ISKEYPRESSED", .int(71)) == 0)
        s.world.keysHeld.append(0x47)                                     // _HK_KEYPAD7 = 71
        #expect(ask(s, "ISKEYPRESSED", .int(71)) == 1)
        #expect(ask(s, "ISKEYPRESSED", .int(72)) == 0)
    }

    @Test func headingIsTheDirectionOfTheLastFrameMove() throws {
        let (s, lex) = try make()
        let prev = V3(1000, 2000, 0)
        lex.prevPos = prev
        let cases: [((Double, Double), Int)] = [((0, -100), 0), ((-100, 0), 90), ((100, 0), -90), ((0, 100), 180), ((-100, -100), 45),
                                                ((100, -100), -45), ((-100, 100), 135), ((100, 100), -135), ((0, 0), 666)]
        for (move, expect) in cases {
            lex.pos = V3(prev.x + move.0, prev.y + move.1, 5)
            #expect(ask(s, "HEADING", .str("CURFIG")) == expect)
        }
        lex.heading = 90                                                  // a forward step at heading h reads HEADING == COMPASS
        let f = lex.forward()
        lex.pos = V3(prev.x + f.x * 200, prev.y + f.y * 200, 0)
        #expect(ask(s, "HEADING", .str("PLAYER")) == ask(s, "COMPASS"))
        #expect(ask(s, "HEADING", .str("NOBODY")) == 0)
        #expect(s.world.warnings == ["HEADING NOBODY: no such object"])
    }

    @Test func amInExtentIsTheHullTouchingTheNamedPhys() throws {
        let (s, lex) = try make()
        let w = s.world
        let ce3 = try #require(w.data.phys.first { $0.name == "CE3" })
        lex.pos = V3((ce3.lo.x + ce3.hi.x) / 2, (ce3.lo.y + ce3.hi.y) / 2, ce3.lo.z + Double(lex.assets.footOffset))
        #expect(ask(s, "AMINEXTENT", .str("CURFIG"), .str("CE3")) == 1)
        #expect(ask(s, "AMINEXTENT", .str("PLAYER"), .str("ce3")) == 1)
        lex.pos = V3(lex.pos!.x, ce3.hi.y + 5000, lex.pos!.z)
        #expect(ask(s, "AMINEXTENT", .str("CURFIG"), .str("CE3")) == 0)
        #expect(w.warnings.isEmpty)
        #expect(ask(s, "AMINEXTENT", .str("CURFIG"), .str("NOWHERE")) == 0)
        #expect(w.warnings == ["AMINEXTENT CURFIG NOWHERE: no such extent"])
    }

    @Test func floatAtHeightMaximumCapsTheMoverTargetZ() throws {
        let (s, lex) = try make()
        let w = s.world
        let index = try #require(w.data.phys.firstIndex { $0.name == "CE3" })
        lex.area = index
        let base = w.data.phys[index].lo.z
        let wp = try #require(w.data.waypoints["USEALTI"])
        cmd(s, "FLOATATHEIGHT", .str("USEALTI"), .str("MAXIMUM"))
        #expect(Double(lex.zCap) == wp.z - base)                          // waypoint z - the anchor's base z
        _ = w.mover(lex, V3(-10000, -10000, base + 9000))
        #expect(lex.pos!.z == wp.z)                                       // limited to base + cap = the waypoint z
        _ = w.mover(lex, V3(-10000, -10000, base + 100))
        #expect(lex.pos!.z == base + 100)                                 // below the cap: untouched
        #expect(w.warnings.isEmpty)
        cmd(s, "FLOATATHEIGHT", .str("NOWHERE"), .str("MAXIMUM"))
        cmd(s, "FLOATATHEIGHT", .str("USEALTI"), .str("MINIMUM"))
        lex.area = nil
        lex.pos = V3(1e7, 1e7, 0)                                         // outside every area
        cmd(s, "FLOATATHEIGHT", .str("USEALTI"), .str("MAXIMUM"))
        #expect(w.warnings == ["FLOATATHEIGHT NOWHERE: no such waypoint", "FLOATATHEIGHT USEALTI MINIMUM: expected MAXIMUM",
                               "FLOATATHEIGHT USEALTI MAXIMUM: LEX has no area"])
        #expect(w.unmodelled.isEmpty)
        lex.pos = V3(-11485, -30181, -6470)                               // USE_BOT's spot: a placed figure without a selected area gets one
        cmd(s, "FLOATATHEIGHT", .str("USEALTI"), .str("MAXIMUM"))
        let selected = try #require(lex.area)
        #expect(w.data.phys[selected].name == "CE4")
        #expect(Double(lex.zCap) == wp.z - w.data.phys[selected].lo.z)
        cmd(s, "FLOATATHEIGHT", .str("USEALTI"))                          // the float-height form sets F (mechanics tests)
        #expect(w.unmodelled.isEmpty)
        let uz = Int(w.data.waypoints["USEALTI"]!.z)
        #expect(lex.footOverride == uz - w.pointFloor(Int(w.data.waypoints["USEALTI"]!.x), Int(w.data.waypoints["USEALTI"]!.y), uz, uz))
    }

    @Test func coordFunctionsShiftThePositionRightByEight() throws {
        let (s, lex) = try make()
        lex.pos = V3(-1139201, 2560, 255)
        #expect(["COORDX", "COORDY", "COORDZ"].map { ask(s, $0, .str("LEX")) } == [-4451, 10, 0])     // SAR 8 floors
        #expect(["COORDX", "COORDY", "COORDZ"].map { ask(s, $0, .str("CURFIG")) } == [-4451, 10, 0])   // the process's current figure
        let cay = try #require(s.world.figure("CAYNAN"))
        cay.pos = V3(512, 0, 0)
        #expect(ask(s, "COORDX", .str("CURFIG"), fig: "CAYNAN") == 2)
        #expect(ask(s, "COORDX", .str("NOBODY")) == 0)
        #expect(s.world.warnings.isEmpty)                                 // an unknown object is silent
    }

    @Test func distFromExtentAndTriggerMeasureToTheBoxCentre() throws {
        let (s, lex) = try make()
        let w = s.world
        let phys = try #require(w.data.phys.first { $0.name.uppercased() == "CE3" })
        let trig = try #require(w.data.triggers.first)
        let centres: [(String, String, SIMD3<Int>)] = [
            ("DISTFROMEXTENT", "CE3", (SIMD3(Int(phys.lo.x), Int(phys.lo.y), Int(phys.lo.z)) &+ SIMD3(Int(phys.hi.x), Int(phys.hi.y), Int(phys.hi.z))) / 2),
            ("DISTFROMTRIGGER", trig.name, (trig.lo &+ trig.hi) / 2)]
        for (name, box, c) in centres {
            lex.pos = V3(Double(c.x + 3000), Double(c.y + 4000), Double(c.z))
            #expect(ask(s, name, .str("CURFIG"), .str(box.lowercased())) == cmFromUnits(approxLength(3000, 4000, 0)), "\(name)")
        }
        #expect(ask(s, "DISTFROMEXTENT", .str("CURFIG"), .str("NOWHERE")) == 0)
        #expect(ask(s, "DISTFROMTRIGGER", .str("NOBODY"), .str(trig.name)) == 0)
        #expect(w.warnings == ["DISTFROMEXTENT CURFIG NOWHERE: no such extent", "DISTFROMTRIGGER NOBODY \(trig.name): no such object"])
    }

    @Test func itemDistancesNeedACurrentItemAndFigure() throws {
        let (s, _) = try make()
        let w = s.world
        let p = proc(s, "PLAYER")
        #expect(w.call(.function, "DISTFROMITEM", [], p) == .int(0))
        #expect(w.call(.function, "2DDISTFROMITEM", [], p) == .int(0))
        #expect(w.warnings == ["DISTFROMITEM: no current item", "2DDISTFROMITEM: no current item"])
        _ = w.call(.stmt, "CREATEITEM", [.str("MEDKIT")], p)
        let itemName = try #require(p.curItem)
        let item = try #require(w.items[itemName])
        item.owner = nil                    // test_world's PLAYER does not exist, so its CREATEITEM has no holder: a floor item (a held one measures from its holder)
        item.pos = V3(3000, 4000, 20000)
        #expect(w.call(.function, "2DDISTFROMITEM", [], p) == .int(244))
        #expect(w.call(.function, "DISTFROMITEM", [], p) == .int(cmFromUnits(approxLength(3000, 4000, 20000))))
        p.curFig = "NOBODY"
        #expect(w.call(.function, "DISTFROMITEM", [], p) == .int(0))
        #expect(w.warnings.contains("DISTFROMITEM: no current figure"))
    }

    @Test func distFromCoordsTakesCoordXUnits() throws {
        let (s, lex) = try make()
        lex.pos = V3(0, 0, 500)
        #expect(ask(s, "2DDISTFROMCOORDS", .str("CURFIG"), .int(11), .int(15)) == cmFromUnits(length2d(11 << 8, 15 << 8)))
        #expect(ask(s, "2DDISTFROMCOORDS", .str("NOBODY"), .int(1), .int(1)) == 0)
        #expect(s.world.warnings == ["2DDISTFROMCOORDS NOBODY: no such object"])
    }

    @Test func isAiOnIsGravityOnAndKeyboardFlags() throws {
        let (s, lex) = try make()
        #expect(ask(s, "ISAION") == 1)
        lex.hold = 2
        #expect(ask(s, "ISAION") == 0)
        #expect(ask(s, "ISGRAVITYON", .str("CURFIG")) == (lex.gravity ? 1 : 0))
        lex.gravity = false
        #expect(ask(s, "ISGRAVITYON", .str("LEX")) == 0)
        #expect(ask(s, "ISGRAVITYON", .str("NOBODY")) == 0)
        #expect(s.world.warnings == ["ISGRAVITYON NOBODY: no such object"])
        #expect(ask(s, "ISKEYBOARDCAPTURED") == 0)
        cmd(s, "CAPTUREKEYBOARD")
        #expect(ask(s, "ISKEYBOARDCAPTURED") == 1)
    }

    @Test func findFirstAndFindNextWalkTheFigureList() throws {
        let (s, _) = try make()
        let w = s.world
        cmd(s, "CREATEFIGURE", .str("CAYNAN"), .str("CAYNAN"))
        let p = proc(s, "PLAYER")
        let names = w.figures.keys
        _ = w.call(.stmt, "FINDFIRSTFIGURE", [], p)
        #expect(p.curFig == names[0])
        var seen = [p.curFig!]
        while w.call(.function, "FINDNEXTFIGURE", [], p) == .int(1) { seen.append(p.curFig!) }
        #expect(seen == names)
        #expect(p.curFig == names.last)                                   // the end leaves the current figure
        #expect(w.call(.function, "FINDNEXTFIGURE", [], p) == .int(0))
    }

    @Test func ambientHandlesAreNone() throws {
        let (s, _) = try make()
        #expect(ask(s, "GETROOMAMBIENT") == -1 && ask(s, "GETCAMERAAMBIENT") == -1)
    }

    @Test func newScriptFunctionsAreModelled() throws {
        let (s, _) = try make()
        let w = s.world
        for n in ["DISTFROMEXTENT", "DISTFROMTRIGGER"] { _ = w.call(.function, n, [.str("CURFIG"), .str("X")], proc(s, "PLAYER")) }
        _ = w.call(.function, "2DDISTFROMCOORDS", [.str("CURFIG"), .int(1), .int(1)], proc(s, "PLAYER"))
        for n in ["DISTFROMITEM", "2DDISTFROMITEM", "ISAION", "ISKEYBOARDCAPTURED", "FINDNEXTFIGURE", "GETROOMAMBIENT", "GETCAMERAAMBIENT"] {
            _ = w.call(.function, n, [], proc(s, "PLAYER"))
        }
        _ = w.call(.function, "ISGRAVITYON", [.str("CURFIG")], proc(s, "PLAYER"))
        _ = w.call(.stmt, "FINDFIRSTFIGURE", [], proc(s, "PLAYER"))
        #expect(w.unmodelled.isEmpty)
    }

    @Test func unmodelledCallsAreListedApartFromWarnings() throws {
        let (s, _) = try make()
        let w = s.world
        _ = w.call(.stmt, "RUNEDITORTOOL", [.int(3)], proc(s))
        _ = w.call(.function, "NOSUCHFUNC", [], proc(s))
        _ = w.call(.stmt, "GRAVITY", [.str("CURFIG"), .str("ON")], proc(s))      // modelled: not listed
        _ = w.call(.function, "COMPASS", [], proc(s, "PLAYER"))                  // ported with the encounters' last gaps: not listed
        #expect(w.unmodelled == ["RUNEDITORTOOL: unmodelled statement (ignored)", "NOSUCHFUNC: unmodelled function (ignored)"])
        #expect(w.warnings.isEmpty)
    }

    @Test func continueTauntPlaysOnceButIdlesLoop() throws {
        let (s, lex) = try make()
        cmd(s, "MOTION", .str("TAUNT2"), .str("CONTINUE"))
        #expect(!lex.loop)
        cmd(s, "MOTION", .str("STAND"), .str("CONTINUE"))
        #expect(lex.loop)
    }

    @Test func combatFigureReturnsToAtkStandAfterAOneShot() throws {
        let (s, lex) = try make()
        let w = s.world
        let bot = try #require(w.figure("FIRSTBOT"))
        bot.viewCams = nil
        bot.pos = V3(-5000, 5000, 0)
        bot.noCollide = true
        bot.combat = true
        bot.setMotion("RECOIL_TL", loop: false)
        run(s, ticksFor(w, bot) + 2)
        #expect(bot.motion == "ATK_STAND" && bot.loop && bot.engineRequest)
        lex.combat = true                                                // 1088:4155 has no exemption for the player
        lex.setMotion("ATK_H8", loop: false)
        run(s, ticksFor(w, lex) + 2)
        #expect(lex.motion == "ATK_STAND")
        bot.combat = false
        bot.setMotion("RECOIL_TL", loop: false)
        run(s, ticksFor(w, bot) + 2)
        #expect(bot.motion == "STAND" && bot.loop)                       // 1088:4155: out of combat mode its idle is stand
    }

    /// 10d0:1c9b only starts the turn_to_enemy task; FUN_10e8_0079 turns by motion, snaps within 8/256 of a turn, and ends two updates later.
    @Test func confrontEnemyIsATaskTheCallerWaitsFor() throws {
        let (s, lex) = try make()
        let w = s.world
        let bot = try #require(w.figure("FIRSTBOT"))
        lex.pos = V3(0, 0, 0)
        bot.pos = V3(2000, 0, 0)
        bot.heading = 0
        bot.enemy = "PLAYER"
        bot.combat = false
        cmd(s, "CONFRONTENEMY", fig: "FIRSTBOT")
        let task = try #require(bot.confront)
        #expect(!task.settled)
        let before = w.relAngle(bot, lex.pos!)
        #expect(abs(before) > 11.25)
        w.updateConfront(bot)
        #expect(bot.motion == (before > 0 ? "TURN_LEFT" : "TURN_RIGHT"))
        bot.heading -= w.relAngle(bot, lex.pos!) - 5
        bot.setMotion("STAND", loop: true)
        w.updateConfront(bot)
        #expect(task.settled && abs(w.relAngle(bot, lex.pos!)) < 0.001)
        w.updateConfront(bot)
        #expect(bot.confront === task)
        w.updateConfront(bot)
        #expect(bot.confront == nil)
    }

    @Test func confrontEnemyInCombatTurnsWithAtkM4() throws {
        let (s, lex) = try make()
        let w = s.world
        let guardFig = try #require(w.figure("CAYNAN"))
        lex.pos = V3(0, 0, 0)
        guardFig.pos = V3(2000, 0, 0)
        guardFig.heading = 0
        guardFig.enemy = "PLAYER"
        guardFig.combat = true
        guardFig.setMotion("ATK_STAND", loop: true)
        cmd(s, "CONFRONTENEMY", fig: "CAYNAN")
        let before = w.relAngle(guardFig, lex.pos!)
        w.updateConfront(guardFig)
        #expect(guardFig.motion == (before > 0 ? "ATK_M4" : "ATK_M6"))
    }

    @Test func finalRootZIsCarriedOnlyByAHoveringMotion() throws {
        let (s, _) = try make()
        let w = s.world
        let guardFig = Figure(name: "G", type: "GRDCELL", assets: try #require(w.asset("GRDCELL")), speed: World.defaultSpeed, pos: V3(0, 0, 100))
        guardFig.gravity = true
        guardFig.setMotion("WAKE_UP", loop: false)                       // started under gravity: its root z lived in the pose
        guardFig.finished = true
        guardFig.gravity = false
        guardFig.setMotion("ATK_STAND", loop: true)
        #expect(guardFig.pos?.z == 100)
        guardFig.setMotion("WAKE_UP", loop: false)                       // without gravity too: only a lift is carried (live: GET_UP brings GUARD1 back up)
        guardFig.finished = true
        guardFig.setMotion("ATK_STAND", loop: true)
        #expect(guardFig.pos?.z == 100)
    }

    @Test func stoppedFigureStillTakesPlayerKeysButFrozenDoesNot() throws {
        let (s, lex) = try make()
        lex.stopMotion()
        #expect(lex.frozen && lex.stopped)
        lex.setMotion("STAND", loop: true, freeze: true)
        #expect(lex.frozen && !lex.stopped)
    }
}
