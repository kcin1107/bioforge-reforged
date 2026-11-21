// Engine binding: lets the script VM drive real figures, cameras and room sprites. Port of re/interp/world.py (the oracle);
// everything the executable does not tell us is an ASSUMPTION, kept as a named constant or a commented branch, as in the prototype.
//
// World is a ScriptEngine (a RecordingEngine subclass, so every engine call is logged): the VM calls call(kind, name, args, proc);
// World keeps the figures (placed from the level's FIGR records, lazily), the camera state, items, sound/subtitle/music logs
// with their handle lifetimes, the deterministic RANDOM stream and the player's key state. Each tick the caller runs
//     vm.tickOnce(); world.step()      (GameSession.tick())
// and draws world.render(into:). Conventions: heading is in degrees; the figure's forward direction is (-sin h, -cos h);
// rendering yaw = -heading; a GO target puts the figure origin at waypoint z + foot offset of its type.
// Stage 5 begins with PIMM's authored monitor core (including TEXT.FLX lists and inventory).
// Camera viewports, the options dialog (Options.swift) and saving / loading (SaveLoad.swift, Resume.swift) are ported.
// Subtitle drawing is in WorldRender; the App renders the sound and music event logs.
// The other files of the binding: WorldPlay.swift (input, motion, combat, step, cameras), WorldSound.swift, WorldRender.swift.
import Foundation

/// Per-game data shared by every World: script library, sound table, figure assets and room compositors. The caches are filled on first
/// use under `lock`: the tests run several Worlds on one GameResources in parallel (an unlocked dictionary write crashed `swift test`).
public final class GameResources {
    public let game: GameFolder
    public let library: ScriptLibrary
    let captionFont: CaptionFont
    let sounds: SoundBank                                    // English
    private var languageSounds: [String: SoundBank] = [:]
    private let lock = NSRecursiveLock()
    private var assets: [String: WorldAssets] = [:]
    private var compositors: [String: Compositor?] = [:]
    var cosTable: [Int]? { lock.withLock { _cosTable } }
    var levelIndex: LevelIndex? { lock.withLock { _levelIndex } }
    var extents: [String: V3] { lock.withLock { _extents } }
    var figureProps: [String: [String: [ScriptValue]]] { lock.withLock { _figureProps } }
    private lazy var _cosTable: [Int]? = try? BioForgeCore.cosTable(exe: game.read("BIOFORGE.EXE"))
    private lazy var _levelIndex: LevelIndex? = try? LevelIndex(game: game)
    private lazy var _extents: [String: V3] = {
        var out: [String: V3] = [:]
        guard let script = library.script(named: "FIGURES.scr"), let defs = try? ScriptDefs(game: game) else { return out }
        for block in ScriptParser.parse(script, defs: defs).blocks {
            for t in block.tables where t.name == "EXTENT" && t.values.count >= 3 {
                if case .int(let x) = t.values[0], case .int(let y) = t.values[1], case .int(let z) = t.values[2] {
                    out[block.name.uppercased()] = V3(Double(x), Double(y), Double(z))
                }
            }
        }
        return out
    }()

    /// FIGURES.SCP data tables per block: {block: {property: values}} (world.py `figure_props`). `< MAX HPS = n >` parses as an
    /// unnamed row whose values are [MAX, HPS, =, n]; the words before "=" are the name.
    private lazy var _figureProps: [String: [String: [ScriptValue]]] = {
        var props: [String: [String: [ScriptValue]]] = [:]
        guard let script = library.script(named: "FIGURES.scr"), let defs = try? ScriptDefs(game: game) else { return props }
        for block in ScriptParser.parse(script, defs: defs).blocks {
            let key = block.name.uppercased()
            var rows = props[key] ?? [:]
            for t in block.tables {
                var name = t.name, values = t.values
                if name == nil, let k = values.firstIndex(of: .str("=")) {
                    name = values[..<k].map { v -> String in if case .int(let i) = v { return String(i) }; if case .str(let s) = v { return s }; return "" }.joined(separator: " ").uppercased()
                    values = Array(values[(k + 1)...])
                }
                if let name, rows[name.uppercased()] == nil { rows[name.uppercased()] = values }
            }
            props[key] = rows
        }
        return props
    }()

    /// FUN_1120_0763 looks a property up under the figure's instance name (+0xf7). ASSUMPTION: a figure without a block of its own
    /// falls back to its type's block. -> the first value as an integer, or `fallback`.
    func figureProp(name: String, type: String, prop: String, default fallback: Int) -> Int {
        for block in [name.uppercased(), type.uppercased()] {
            if let v = figureProps[block]?[prop]?.first {
                if case .int(let i) = v { return i }
                if case .str(let s) = v, let i = Int(s) { return i }
            }
        }
        return fallback
    }

    public init(game: GameFolder) throws {
        self.game = game
        library = try ScriptLibrary(game: game)
        captionFont = try CaptionFont(game.read("DATA/1.FNT"))
        sounds = try SoundBank(game: game)
    }

    /// SOUND/<language>SAMPLES.FLX, loaded on first use (a missing file falls back to English).
    func soundBank(_ language: String) -> SoundBank {
        if language == "E" { return sounds }
        return lock.withLock {
            if languageSounds[language] == nil { languageSounds[language] = (try? SoundBank(game: game, language: language)) ?? sounds }
            return languageSounds[language]!
        }
    }

    func asset(_ type: String) -> WorldAssets? {
        lock.withLock {
            if assets[type] == nil, let T = _cosTable, let a = try? FigureAssets(type: type, game: game) { assets[type] = WorldAssets(a, cosTable: T) }
            return assets[type]
        }
    }

    func compositor(_ camera: String) -> Compositor? {
        lock.withLock {
            if let c = compositors[camera] { return c }
            let c = game.resolve("ROOMS/\(camera).CAM").flatMap { _ in try? Compositor(room: CAMFile(data: game.read("ROOMS/\(camera).CAM"))) }
            compositors[camera] = .some(c)
            return c
        }
    }
}

struct Phys { let name: String; var lo: V3, hi: V3; let state: Int; var raw: [UInt8] = [] }

/// One IMAG trigger volume (world.py `triggers`): box, flag bit 0x01 (+0x34: fire on entry only, else every frame inside) and the
/// camera name at record +45 (+0x41) that CAM_xxxx triggers force.
struct Trigger { let name: String; let lo: SIMD3<Int>, hi: SIMD3<Int>; var once: Bool; let camera: String }

/// Objects of the current level file (INITGAME/<LEVEL>.IFF).
struct LevelData {
    var objs: [LevelObject] = []
    var phys: [Phys] = []
    var triggers: [Trigger] = []                         // IMAG records in level order (the InTrig index)
    var cameras: [String: Camera] = [:]
    var cameraOrder: [String] = []                       // first-seen order (a duplicate name replaces the object, not the position)
    var points: [String: V3] = [:]                       // WAYP first, then every other named object
    var waypoints: [String: V3] = [:]                    // WAYP objects by name, first of a name wins (the list at 1290:1cdd)
    var figDefs: [String: (type: String, pos: V3, cams: [String]?, flags: Int, aiName: String?, aiOff: Int)] = [:]
    var figDefOrder: [String] = []                       // figDefs keys in level order (SETCURRENTFIGURE's type-name fallback)
    var recordLocals: [String: [ScriptValue]] = [:]      // each FIGR record's script object locals ~0..~9, by instance name
    var figRecs: [String: ObjRec] = [:]                  // each FIGR record's decoded view, by instance name
    var objIds: [(tag: String, name: String)] = []       // the level's objects in file order = object ids 1.. (enemy / avoid references)
}

func v3(_ a: [Int]) -> V3 { V3(Double(a[0]), Double(a[1]), Double(a[2])) }

/// Initial viewing-camera list of a FIGR record: u16 count c + c 9-byte names + 79 trailing bytes. Several c can satisfy the
/// count check (c = 0 also matches when the last name's padding is zero); candidates need printable names, and a c > 0 wins over
/// c = 0. -> names, or nil if no c fits.
func figrViewCams(_ raw: [UInt8]) -> [String]? {
    var cands: [[String]] = []
    for c in 0...World.maxViewCams {
        let o = raw.count - 79 - 9 * c - 2
        guard o >= 0, (try? raw.u16(o)) == c else { continue }
        let names = (0..<c).map { i in Array(raw.slice(o + 2 + 9 * i, o + 11 + 9 * i).prefix { $0 != 0 }) }
        let ok = names.allSatisfy { n in !n.isEmpty && n.allSatisfy { ($0 >= 0x30 && $0 <= 0x39) || ($0 >= 0x41 && $0 <= 0x5a) || ($0 >= 0x61 && $0 <= 0x7a) || $0 == 0x5f } }
        if ok { cands.append(names.map { latin1String($0).uppercased() }) }
    }
    let nonempty = cands.filter { !$0.isEmpty }
    return nonempty.count == 1 ? nonempty[0] : cands.count == 1 ? cands[0] : nil
}

/// A FIGR record's AI name (figure +0x178, the char[25] that ends 4 bytes before the viewing-camera count): SETAI (10d0:6e8c) writes it
/// and the AI start (1088:33d4) runs the block `<it>_AI`, so a level figure has an AI without a script SETAI. nil if unknown.
func figrAIName(_ raw: [UInt8]) -> String? {
    guard let cams = figrViewCams(raw) else { return nil }
    let o = raw.count - 79 - 9 * cams.count - 2 - 4 - 25
    guard o >= 0 else { return nil }
    let name = Array(raw.slice(o, o + 25).prefix { $0 != 0 })
    let ok = !name.isEmpty && name.allSatisfy { ($0 >= 0x30 && $0 <= 0x39) || ($0 >= 0x41 && $0 <= 0x5a) || ($0 >= 0x61 && $0 <= 0x7a) || $0 == 0x5f }
    return ok ? latin1String(name).uppercased() : nil
}

/// A FIGR record's AI-off counter (figure +0x229, the s16 after the viewing-camera list; the loader 1088:3325 reads it for records of
/// version >= 0x10, all of the shipped ones). 0 = the AI runs by default: only CHAOS's USE_BOT has 1 (BEACH's MARINE3A has junk there, and
/// its saved AI name has no block anyway).
func figrAIOff(_ raw: [UInt8]) -> Int { Int(Int16(truncatingIfNeeded: (try? raw.u16(raw.count - 79)) ?? 0)) }

/// One PHYS volume as integers with its current space state (world.py `_phys_boxes`).
struct PhysBox { let name: String; let state: Int; let lo: SIMD3<Int>, hi: SIMD3<Int> }

/// FUN_1138_1853's ordered area node: the anchor PHYS and its physical_objs, every PHYS touching the anchor grown by 0x1000.
struct PhysArea { let anchor: Int; let members: [Int] }

/// Python `a // b` for b > 0.
func floorDiv(_ a: Int, _ b: Int) -> Int { a >= 0 ? a / b : -((-a + b - 1) / b) }

/// FUN_1070_08df: script centimetres to world units, (cm << 3 << 8) / 100 truncated toward zero.
func hullUnits(_ cm: Int) -> Int { cm * 2048 / 100 }

/// The script distance functions' unit conversion (DISTFROMENEMY 10d8:1278, DISTFROMWAYPOINT 16a6, 2DDISTFROMWAYPOINT 0534, ATTACKRADIUS
/// 0e28): (units * 100 + 0x80) / 0x800 as a signed long divide (truncates toward zero), i.e. world units / 20.48 (the inverse of
/// hullUnits). Replaces the earlier `units / 20` assumption.
func cmFromUnits(_ units: Int) -> Int { (units * 100 + 0x80) / 2048 }

/// FUN_1210_0c24: 24.8 fixed-point divide, trunc((a << 8) / b) in 32 bits.
func fixDiv(_ a: Int, _ b: Int) -> Int { Int(Int32(truncatingIfNeeded: (a << 8) / b)) }

/// FUN_1210_0f9b: |v| without a square root. With |v| sorted a >= b >= c: a + (c >> 2) - (b >> 5) + (b >> 3) + (b >> 2).
func approxLength(_ x: Int, _ y: Int, _ z: Int) -> Int {
    let v = [abs(x), abs(y), abs(z)].sorted(by: >)
    return v[0] + (v[2] >> 2) - (v[1] >> 5) + (v[1] >> 3) + (v[1] >> 2)
}

/// FUN_10a0_22e1: steps = the integer part of the 24.8 ratio |d| / smallest hull span (16 bits). The length takes all three axes
/// (the two-argument form is a move with dz = 0).
func moveSteps(_ dx: Int, _ dy: Int, _ dz: Int, _ minSpan: Int) -> Int {
    Int(Int16(truncatingIfNeeded: fixDiv(approxLength(dx, dy, dz), minSpan) >> 8))
}
func moveSteps(_ dx: Int, _ dy: Int, _ minSpan: Int) -> Int { moveSteps(dx, dy, 0, minSpan) }

func wrap32(_ v: Int) -> Int { Int(Int32(truncatingIfNeeded: v)) }

/// FUN_1210_0c42: (a * b) >> 8 on the 64-bit product (arithmetic shift = floor), low 32 bits.
func fixMul(_ a: Int, _ b: Int) -> Int { wrap32((a * b) >> 8) }

/// FUN_1088_384e: the per-frame step (+0xd2/+0xd6/+0xda) from the velocity (+0xc6/+0xca/+0xce, units per 30 fps frame).
/// fps = (0x3c00 // [83a0]) << 8 (unsigned divide, whole frames per second; at least 1), scale = 0c24(30 << 8, fps) = 30 / fps in
/// 8.8, step = 0c42(v, scale) per axis. At 30 fps ([83a0] = 512) scale = 256 and step == v.
func velocityStep(_ v: [Int], dt8: Int = World.frameTime8) -> [Int] {
    let dt8 = dt8 == 0 ? 1 : dt8                          // a zero frame time is replaced by 1
    let fps8 = max(1, wrap32((0x3c00 / dt8) << 8))
    let scale = fixDiv(0x1e00, fps8)
    return v.map { fixMul($0, scale) }
}

/// FUN_10a0_22e1, a blocked (or trigger-stopped) in-loop step i of n: each step component becomes 0c24(0c42(c, i << 8), n << 8) =
/// trunc(c * i / n) (the IDIV truncates toward zero).
func scaleStep(_ step: [Int], _ i: Int, _ n: Int) -> [Int] { step.map { fixDiv(fixMul($0, i << 8), n << 8) } }

/// FUN_1210_000d: fixed-point |(x, y)|. Normalise until the larger component reaches 0x1000 (FUN_1208_0b86) or falls to 0x40000
/// (FUN_1208_0c65), square through the 24.8 multiply, square-root isqrt(v << 8) (FUN_1210_1047), then undo the normalising shift.
func length2d(_ x: Int, _ y: Int) -> Int {
    var x = abs(x), y = abs(y)
    if x == 0 && y == 0 { return 0 }
    var up = 0, down = 0
    while x < 0x1000 && y < 0x1000 { x <<= 1; y <<= 1; up += 1 }
    if up == 0 { while x > 0x40000 || y > 0x40000 { x >>= 1; y >>= 1; down += 1 } }
    let v = Int(Int32(truncatingIfNeeded: ((x * x) >> 8) + ((y * y) >> 8))) << 8
    let r = isqrt(v)
    return up != 0 ? r >> up : r << down
}

/// Integer floor square root (math.isqrt).
func isqrt(_ n: Int) -> Int {
    if n < 2 { return n }
    var r = Int(Double(n).squareRoot())
    while r * r > n { r -= 1 }
    while (r + 1) * (r + 1) <= n { r += 1 }
    return r
}

/// FUN_1098_096e: move a target closer than r to `other` out to r along the line between them (q = (r << 4) / |d|, then
/// other - d * q >> 4 through the 24.8 multiply); z is kept.
func pushOut(target: V3, other: V3, r: Int) -> V3 {
    let dx = Int(other.x) - Int(target.x), dy = Int(other.y) - Int(target.y)
    let dist = length2d(dx, dy)
    if dist >= r { return target }
    let q = (r << 4) / (dist == 0 ? 1 : dist)
    var out = target
    out.x = Double(Int(other.x) - (wrap32(((dx << 8) * (q << 8)) >> 8) >> 12))
    out.y = Double(Int(other.y) - (wrap32(((dy << 8) * (q << 8)) >> 8) >> 12))
    return out
}

public final class World: RecordingEngine {
    // ASSUMPTIONS and constants (see world.py)
    static let unitsPerCM = 20.0, maxViewCams = 30
    static let maxAvoid = 8                  // FUN_1098_0b88: avoidance points per figure
    static let turnStep = 10.0, playerTurnPerTick = 4.0   // 10a8:0541: a held turn key adds [83a0] << 1 (2 degrees per 60 Hz clock tick) while moving. Live: 113-117 degrees/s walking
    static let turnWhileMoving: Set<String> = ["WALK", "WALK_BACK", "RUN", "ATK_M8", "ATK_M2"]   // the motions that take it; standing, TURN_LEFT / RIGHT turn by their root yaw (live: about 45 degrees/s)
    static let turnKeys = [0x4b: -1, 0x47: -1, 0x4d: 1, 0x49: 1]                                 // 10a8:0541: Left and Home turn left, Right and PgUp turn right
    static let soundTicks = 90, voiceCount = 8, loopTicks = 1_000_000_000, nearDepth = 200.0
    static let cycleTolerance = 20
    static let radPerDeg = Double.pi / 180, degPerRad = 180.0 / Double.pi
    static let defaultExtentCM = V3(10, 10, 10)
    static let noFloor = -819200        // floor queries FUN_1060_0871/03f2 start from -0xc8000 ("nothing below")
    static let fallDV = 512 / 5         // FUN_1088_39ef: vz -= frame time [83a0] / 5 per frame; [83a0] = 512 (8.8 ticks) at 30 fps
    static let fallVMin = -0x500        // ... applied only while vz > -0x500 (-1280; disassembly 1088:3d22), so vz stops at -1326 (30 fps)
    static let frameTime8 = 512         // [83a0]: frame time in 8.8 ticks of the 60 Hz clock; 512 = 30 fps (one tick per frame)
    static let goRadius = 0x266         // 1098:11c0: a GO ends once the figure is within this many units of its target (10e0:1a4c)
    static let landRevert = 0x1000      // FUN_10a0_0ead: support more than this above the hull bottom restores the previous position
    static let areaGrow = 0x1000        // FUN_1138_131c grows an area anchor box by this before collecting its physical_objs
    static let engineOneshots: Set<String> = ["LAND_HARD", "LAND_MEDIUM", "LAND_SOFT", "WHOAH_FORWARD", "WHOAH_BACKWARD", "WHOAH_LEFT", "WHOAH_RIGHT",
                                              "MANTLE_3", "MANTLE_6", "MANTLE_9"]
    static let confrontDone = 8.0 * 360 / 256     // FUN_10e8_0079: within 8/256 of a turn the task snaps to the enemy
    static let rootZKeepMin = 100.0     // ASSUMPTION: a finished motion's last root z at least this large is kept by a gravity-less figure
    /// ASSUMPTION: a CONTINUE taunt plays once although its last pose equals its first (TAUNT2 / TAUNT3 / TAUNT4 / C_TAUNT*: limb
    /// difference 0 passes isCycle). GREET_GUARD1 starts Lex's TAUNT2 with CONTINUE and never ends it: its 23 frames last about as long
    /// as the two subtitles that follow, after which the player is free
    static let gestures = ["TAUNT1", "TAUNT2", "TAUNT3", "TAUNT4"]
    static let waypointFuncs: Set<String> = ["DISTFROMWAYPOINT", "2DDISTFROMWAYPOINT", "ANGLEFROMWAYPOINT", "AMINWAYPOINT"]
    /// Statements and functions `call` acts on (MON_* by prefix). Anything else that reaches the engine is dropped and listed in
    /// `unmodelled` (a "NAME: unmodelled statement (ignored)" entry per name), so a gap shows up in the scenario manifests.
    static let modelledStmts: Set<String> = [
        "EXIT", "JUMPON", "STARTFLIC", "STOPFLIC", "SETFLICRATE", "FLICLOOP", "FREEZE", "THAW", "MENU", "UNMENU", "ADDKEY",
        "DEBUG", "DEBUGINFO", "CAPTION", "CHANGEPALETTE", "RUMBLE", "SET_PTR_MOVEMENT", "SET_PTR_PRESS_TIME",
        "ADDAVOIDANCEPOINT", "ADDENTRY", "ADDLOGENTRY", "ADDTOPITCH", "ADDVIEWINGCAMS", "AI", "ANIMATE", "APPLY", "BANKINSFX",
        "BOUNCINESS", "CAMERA", "CAMERAAUTOACTIVATE", "CAMERAFOLLOW", "CAPTUREKEYBOARD", "CHANGEMYFORM", "COLLISIONS", "COMBATMODE",
        "CONFRONTENEMY", "CREATEFIGURE", "CREATEITEM", "DAMAGE", "DEFINEENEMY", "DEFINEVIEWINGCAMS", "EXPLODE", "FACE", "FINDFIRSTFIGURE",
        "FLOATATHEIGHT", "FORCERELOAD", "FREEHAND", "GO", "GRABCRITTER", "GRAVITY", "INCVIRTUALSECONDS", "INDIVIDUALIZE", "INVULNERABLE",
        "KILL", "KILLCURITEM", "LEAP", "LINKMETOCAMERAS", "LOADLEVEL", "MAKEFLATOBJECT", "MOTION", "MUSIC", "PLACEITEM", "RELEASEFROMLIMB",
        "RELEASEKEYBOARD", "REMOVEAVOIDANCEPOINT", "REMOVEENTRY", "REMOVELOGENTRY", "REPLACESOUND", "REVERTSOUND", "REVERTSOUNDCACHE",
        "SETAI", "SETFLOOROFPHYS", "SETPITCH", "SETREFERENT", "SETSOUNDCACHE", "SETVELOCITY", "SETVOLUME", "SNAPTOPOSE", "SPARWITHPLAYER",
        "STOPALLSOUNDS", "STOPAMBIENT", "STOPMOTION", "STOPSOUND", "STOPVELOCITY", "TELEPORTALLONPHYS", "THROWCURITEM", "TURN", "TURNTOENEMY"]
    static let modelledFuncs: Set<String> = [
        "AMBIENT", "AMINEXTENT", "AMINTRIGGER", "ANGLEFROMENEMY", "ATTACKRADIUS", "COMPASS", "COORDX", "COORDY", "COORDZ", "COUNTBITS",
        "DISTFROMENEMY", "DISTFROMEXTENT", "DISTFROMITEM", "DISTFROMTRIGGER", "2DDISTFROMCOORDS", "2DDISTFROMITEM", "FADE", "RUNFLIC", "PLAYFLIC", "WASALTPRESSED", "CREDITSSTATE", "GETOPTDATA", "FINDNEXTFIGURE", "FIRE", "MAKEMISSILE",
        "GETCAMERAAMBIENT", "GETROOMAMBIENT", "GETSOUNDHANDLE", "HEADING", "ISAION", "ISGRAVITYON", "ISKEYBOARDCAPTURED", "ISCARRYING", "ISCARRYINGANYTHING", "ISCURRENTCAMERA", "ISHANDLEPLAYING", "ISHIDDEN",
        "ISINCOMBATMODE", "ISINVULNERABLE", "ISKEYPRESSED", "ISLEVEL", "ISMONITORRUNNING", "ISMYFORM", "ISMYMOTION", "ISPLAYERSMOTION", "ISSOUNDPLAYING", "MINORSUBTITLE", "MODIFYPITCHOVERTIME", "MODIFYVOLUMEOVERTIME", "MOTIONEXISTS", "RANDOM",
        "SETCURRENTFIGURE", "SETCURRENTITEM", "SOUND", "SUBTITLE", "VELOCITYX", "VELOCITYY", "VELOCITYZ",
        "DISTFROMWAYPOINT", "2DDISTFROMWAYPOINT", "ANGLEFROMWAYPOINT", "AMINWAYPOINT"]
    /// the 60 Hz clock [8330] << 8 advances 512 per 30 Hz VM tick (FUN_1088_1854's time base); MY_SPEED default [249c]
    static let clockPerTick = 2 << 8, defaultSpeed = 512
    /// turning motions: the root yaw turns the figure (FUN_10a0_1c83)
    static let turnMotions: Set<String> = ["TURN_RIGHT", "TURN_LEFT", "TURN_RIGHT_FAST", "TURN_LEFT_FAST"]
    static let manualMoves = Set(["WALK", "RUN", "WALK_BACK", "SIDESTEP_LEFT", "SIDESTEP_RIGHT"] + (1...9).filter { $0 != 5 }.map { "ATK_M\($0)" })

    public let resources: GameResources
    var game: GameFolder { resources.game }
    /// Directory holding the level object files (<LEVEL>.IFF): a native play directory (GAMEDAT, an unpacked save) or nil = the
    /// shipped INITGAME (a new game). Mirrors world.py `state_dir`.
    public let stateDirectory: URL?
    /// Where `saveNative` writes GAME<n>.IM1 and `loadNative` reads it (the app sets it; nil = saving and loading unavailable).
    public var savesDir: URL?
    /// Set by a confirmed load dialog: the session the caller's loop swaps to (a session cannot replace itself).
    public internal(set) var pendingLoad: GameSession?
    /// The last save or load that failed, for the app's alert (the port's addition: the original's handling is not read).
    public internal(set) var fileError: (load: Bool, slot: Int, reason: String)?
    /// -> the failed save or load since the last call, once.
    public func takeFileError() -> (load: Bool, slot: Int, reason: String)? { defer { fileError = nil }; return fileError }
    /// {kernel slot: process} of the script processes resumed from a save.
    public internal(set) var resumed: [Int: ScriptProcess] = [:]
    var data = LevelData()
    /// PHYS boxes cached while step() runs the figures (world.py `_boxes`).
    var boxes: [PhysBox]? { didSet { areaCache = nil } }
    /// `physAreas()` cached with `boxes` (world.py `_areas`); any change of `boxes` drops it.
    var areaCache: [PhysArea]?
    var figures = OrderedMap<Figure>()
    var killedFigures = Set<String>()           // retired FIGR names; prevents lazy recreation from current level definitions
    var items = OrderedMap<Item>()
    /// level -> the items kept with a level the player left, each with its script locals (WorldItems.swift stashLevelItems)
    var levelItems: [String: [(item: Item, locals: [ScriptValue])]] = [:]
    /// level -> the figures kept with a level the player left, in figure order (stashLevelFigures)
    var levelFigures: [String: OrderedMap<Figure>] = [:]
    var fragments: [Fragment] = []              // EXPLODE's shrapnel (WorldEffects.swift); a level change drops it
    var deadFigures: [String: Figure] = [:]     // KILLed figure objects by name, kept until the level changes: EXPLODE reads the dying pose from one
    var flatObjects: [FlatObject] = []          // MAKEFLATOBJECT sprites (WorldEffects.swift); a level change drops them
    let itemState = ItemState()
    public internal(set) var level = ""
    public internal(set) var playerName: String? { didSet { vm?.godKey = godMode ? playerName.map(objectKey) : nil } }
    /// Tester aid (Debug > God Mode): while on, the player's hit points can't fall. Off in every new game or load; part of `stateDigest` when on.
    public internal(set) var godMode = false { didSet { vm?.godKey = godMode ? playerName.map(objectKey) : nil } }
    /// [2958]: clock when an ATK_F9 attack started the repeat-count reset timer (see `motionDuration`).
    var comboTimer = 0
    public internal(set) var camera: String?
    /// CAMERA SHOW <cam> (10d0:115c): the full-screen picture camera, until the next switch or level load. Only the options dialog draws it.
    var shownPicture: String?
    public var defaultCamera: String?
    public var autoCamera = true
    public internal(set) var scriptAuto = true
    var disabled = Set<String>()
    var follow = "PLAYER"
    var candidate: String?
    var selected = false
    /// [63d6]: the camera a trigger forced (FUN_1130_0f85), applied by the next camera frame.
    var forcedCamera: String?
    /// `areaTriggers` per area anchor (world.py `_area_triggers`).
    var areaTriggerCache: [Int: [Int]] = [:]
    var loadedCam: String?                               // [63e9]: the camera whose events ran last; a level load keeps it (1130:0048 clears only [63e1] / [63e5])
    var loadedRoom: String?                              // [63ed]: its room, the camera name's first 3 characters
    var switchingTo: String?                             // [63e1] while 1130:0114 runs the events (`camera`, [63ce], changes after them)
    public internal(set) var cameraChanges: [(tick: Int, from: String?, to: String, reason: String)] = []
    public internal(set) var levelLoads: [(tick: Int, level: String, arrival: String?, position: SIMD3<Double>?)] = []
    public internal(set) var hits: [(tick: Int, attacker: String?, target: String, motion: String, label: String)] = []
    public internal(set) var events: [(tick: Int, block: String)] = []
    /// Test seams (no engine use): replace the stimulus-label lookup (fig name, label, dmg -> label exists), the sound-name lookup for
    /// string names (-> sample index or nil), and record every setPos position.
    var labelProbe: ((String, String, Int) -> Bool)?
    var soundNameProbe: ((String) -> Int?)?
    var motionCueProbe: ((Figure, Int) -> Void)?      // replaces motionCue (the cue walk's dispatch) in tests
    var setPosTrace: [V3]?
    var blockProbe: ((String, String) -> Void)?       // sees every block runFigureBlock is asked for (figure, block)
    var propOverrides: [String: Int] = [:]            // FIGURES.SCP property overrides for tests (autoTurn, damage armour)
    public internal(set) var warnings: [String] = []
    /// "NAME: unmodelled statement|function (ignored)" for every engine call `call` drops (kept apart from `warnings`)
    public internal(set) var unmodelled: [String] = []
    var logEntries = OrderedMap<[String]>()
    public internal(set) var logEntryTimes = [String: [Int]]()
    public internal(set) var monitorCodes: [(name: String, value: Int?)] = []
    public internal(set) var options: Options? { didSet { options?.readableText = readableText } }
    public internal(set) var monitor: MonitorScreen? { didSet { monitor?.readableText = readableText } }
    /// View > Readable Text: applied to the running monitor, the options dialog and subtitles / captions.
    public var readableText = false { didSet { monitor?.readableText = readableText; options?.readableText = readableText } }
    public internal(set) var optionActions: [(tick: Int, action: String)] = []
    public internal(set) var exitRequested = false
    /// The dialog's Load > New > Yes: the host starts a new game (the app does it as File > New Game; the only way on from the reload
    /// dialog besides a load).
    public internal(set) var newGameRequested = false
    public var forcingReload = false
    /// [66c6]: INCVIRTUALSECONDS 0 raises it (timer rate and persistence not ported)
    var speedFactor = 0
    /// [6530]: between CAPTUREKEYBOARD and RELEASEKEYBOARD (the block is not run, keys not routed to it).
    public internal(set) var keyboardCaptured = false
    var presentation = PresentationState()     // WorldPresentation.swift
    var show = ShowState()                     // WorldShow.swift
    /// FUN_1140_0fc0: a save or load is running (the port saves synchronously: never set).
    public var saveBusy = false
    /// The level the app's rolling autosave last covered (it sets the starting level, so a loaded save is not saved again at once).
    public var autosavedLevel: String?
    /// Record every engine call in `log` (tests, traces); a long-running game turns it off.
    public var recordLog = true
    var rng = PyRandom(seed: 0)
    /// While attached, every input call is appended to it (SessionRecorder.swift).
    public var recorder: SessionRecorder?
    /// Frames stepped: the recording's clock. The VM's tick stands still while the options dialog pauses the game, but the pointers run on.
    public internal(set) var frames = 0
    // sound, subtitle and music logs (WorldSound.swift)
    public internal(set) var soundLog: [SoundEvent] = []
    public internal(set) var soundStops: [(tick: Int, handle: Int)] = []
    /// (tick, handle) for STOPAMBIENT: the loop plays on to the end of its sample
    public internal(set) var soundReleases: [(tick: Int, handle: Int)] = []
    public internal(set) var soundDrops: [(tick: Int, index: Int, name: String)] = []
    public internal(set) var soundVolumes: [(tick: Int, handle: Int, volume: Int)] = []
    public internal(set) var subtitleLog: [SubtitleEvent] = []
    public internal(set) var musicLog: [(tick: Int, value: ScriptValue)] = []
    public internal(set) var currentMusic: ScriptValue?
    /// [4e30]: the song playing when a dialog (not the credits page) last opened; -1 after a load (FUN_1100_09cb, 1148:0473).
    var dialogSong = -1
    // options settings (Settings.swift): persisted values and what is in force now
    public internal(set) var settings = Settings()
    /// The sound bank of the language in force.
    var soundBank: SoundBank { resources.soundBank(settings.language) }
    public internal(set) var gamma = Settings().gamma                  // FUN_1100_0e6f; a presentation step (Gamma.apply)
    /// (tick, effect level 0...100): in force for sounds starting at or after the tick.
    public internal(set) var sfxLog: [(tick: Int, sfx: Int)] = [(0, Settings().sound)]
    public internal(set) var musicInitial = Settings().music           // music level at tick 0; musicVolLog holds the later changes
    public internal(set) var musicVolLog: [(tick: Int, music: Int)] = []
    var soundHandles: [(handle: Int, index: Int)] = []
    /// handles of looped samples (what STOPAMBIENT releases)
    var soundLoops = Set<Int>()
    var soundPos: [Int: (key: String, volume: Int)] = [:]
    /// (tick, handle, rate) for SETPITCH / ADDTOPITCH / the pitch ramp: the playback rate in Hz from then on (WorldAudio.swift)
    public internal(set) var soundRates: [(tick: Int, handle: Int, rate: Int)] = []
    var voiceState: [Int: VoiceState] = [:]                // level, rate and position model of every sound handle issued
    var soundOverrides: [String: Int] = [:]                // REPLACESOUND: lower-case sound name -> sample id
    var roomAmbient = 0, cameraAmbient = 0                 // [63f6] / [63f2]: the room / camera `_%s_AMBIENT` loop handles (0 = none)
    var ambientPending = false                             // [63f1]: a camera switch awaits its loops (updateAmbients)
    var ambientBindings: [String: AmbientBinding] = [:]    // camera name -> the `_<CAM>_VOLUME` tracker (camera+0x7e)
    var curSubtitle: (handle: Int, index: Int)?
    var subtitleVoice: Int?                 // the live subtitle's voice handle (+0x44, stopped by 10e8:08a4)
    var captionHandles = Set<Int>()         // CAPTION's entries in subtitleLog, which ignore the subtitles switch
    var voices: [(handle: Int, priority: Int)?] = Array(repeating: nil, count: World.voiceCount)
    // player input
    public struct PlayerInput: Sendable { public var forward = 0, turn = 0, run = false, attack = false }
    var playerInput = PlayerInput()
    public internal(set) var keysHeld: [Int] = []
    /// Keys pressed while captured: the key state table (1290:7bbe, set from the keyboard interrupt, 11d8:1561) has them, the normal handler does not.
    var keysCaptured: [Int] = []
    public internal(set) var keyMods = 0
    var keyPending: [KeyAction] = []
    var inputWasActive = false               // the player's input was active in the previous applyPlayerInput (rising edge)
    public internal(set) var keyLog: [(tick: Int, action: String, detail: LogValue)] = []

    public init(resources: GameResources, level: String, camera: String? = nil, stateDirectory: URL? = nil) throws {
        self.resources = resources
        self.stateDirectory = stateDirectory
        defaultCamera = camera?.uppercased()
        super.init()
        try loadObjects(level)
    }

    var tick: Int { vm?.tick ?? 0 }

    /// The level object file: <stateDirectory>/<LEVEL>.IFF, or INITGAME/<LEVEL>.IFF without a state directory.
    func levelFile(_ level: String) -> URL? {
        let name = level.uppercased() + ".IFF"
        if let stateDirectory { return GameFolder(stateDirectory).resolve(name) }
        return game.resolve("INITGAME/" + name)
    }

    /// (Re)load the object file of `level`: waypoints, cameras, placed figures. PLAYER (and carried figures, re-added by the
    /// caller) survive; other figures are dropped. The old level's items stay with it (stashLevelItems); the player's and the
    /// `travelling` figures' come along.
    func loadObjects(_ level: String, travelling: [String] = [], carryItems: Set<String> = []) throws {
        guard let file = levelFile(level) else { throw FormatError("\(level.uppercased()).IFF not found") }
        let objs = try LevelObjects.load([UInt8](try Data(contentsOf: file)))
        stashLevelItems(travelling, carryItems: carryItems)
        stashLevelFigures(travelling)
        self.level = level.uppercased()
        killedFigures.removeAll()
        fragments = []; deadFigures = [:]
        var d = LevelData()
        d.objs = objs
        for o in objs where o.tag == "PHYS" {
            let p2 = o.pos2 ?? o.pos
            d.phys.append(Phys(name: o.name.uppercased(), lo: pointwiseMin(v3(o.pos), v3(p2)), hi: pointwiseMax(v3(o.pos), v3(p2)), state: Int(o.raw.last ?? 0), raw: o.raw))
        }
        for o in objs where o.tag == "IMAG" {
            let p2 = o.pos2 ?? o.pos
            let lo = pointwiseMin(v3(o.pos), v3(p2)), hi = pointwiseMax(v3(o.pos), v3(p2))
            d.triggers.append(Trigger(name: o.name.uppercased(), lo: SIMD3(lo, rounding: .towardZero), hi: SIMD3(hi, rounding: .towardZero),
                                      once: o.raw[21] & 1 != 0, camera: o.raw.cString(45, 54).uppercased()))
        }
        for o in objs where o.tag == "CAMR" {
            guard let cam = Camera(o) else { continue }
            let n = o.name.uppercased()
            if d.cameras[n] == nil { d.cameraOrder.append(n) }
            d.cameras[n] = cam
        }
        for o in objs where o.tag == "WAYP" && d.waypoints[o.name.uppercased()] == nil { d.waypoints[o.name.uppercased()] = v3(o.pos) }
        for o in objs.filter({ $0.tag == "WAYP" }) + objs.filter({ $0.tag != "WAYP" }) where d.points[o.name.uppercased()] == nil {
            d.points[o.name.uppercased()] = v3(o.pos)
        }
        for o in objs where o.tag == "FIGR" {
            let inst = o.raw.cString(33, 42).uppercased()
            if d.figDefs[inst] == nil {
                d.figDefs[inst] = (o.name.uppercased(), v3(o.pos), figrViewCams(o.raw), Int(o.raw[21]), figrAIName(o.raw), figrAIOff(o.raw))
                d.figDefOrder.append(inst)
            }
            if d.figRecs[inst] == nil, let rec = try? ObjRec(tag: "FIGR", raw: o.raw) { d.figRecs[inst] = rec }
            if d.recordLocals[inst] == nil, o.raw.count >= 146 { d.recordLocals[inst] = (0..<10).map { .int((try? o.raw.s32(106 + 4 * $0)) ?? 0) } }
        }
        if !d.figRecs.isEmpty {
            d.objIds = objs.map { o in
                let inst = ObjRec.tags.contains(o.tag) ? (try? ObjRec(tag: o.tag, raw: o.raw))?.inst : nil
                return (o.tag, ((inst.flatMap { $0.isEmpty ? nil : $0 }) ?? o.name).uppercased())
            }
        }
        data = d
        boxes = nil                                          // a LOADLEVEL inside step() must not keep ranking the old level's PHYS for the rest of the frame
        areaTriggerCache = [:]
        for index in data.phys.indices { _ = areaTriggers(index) }     // built with the level (ASSUMPTION): a moved anchor (ELV in SETFLOOROFPHYS) keeps its own
        forcedCamera = nil
        figures = figures.filtering { $0 == self.playerName }
        for fig in figures.values { fig.area = nil; fig.inTrig = nil }
        camera = nil; disabled = []; candidate = nil; selected = false
        // scriptAuto (1290:63da) is not reset: only a new game / boot, CAMERA UNLOCK (1) and CAMERA <cam> / SHOW / AT (0) write it
        ambientBindings = [:]                                // the camera objects are rebuilt (1110:19cc)
        flatObjects = []
        loadFloorItems()
        seedObjectLocals()
        if let kept = levelFigures.removeValue(forKey: self.level) {   // a return: the figures come back from the level's IFF as the player left them;
            for k in kept.keys { figures[k] = kept[k] }                 // the killed and carried-off ones have no record, so figure() must not rebuild them
            for inst in data.figDefOrder where !kept.contains(inst) { killedFigures.insert(inst) }
            return
        }
        for inst in data.figDefOrder { figure(inst) }        // the level loader builds every FIGR figure (1148:18d3), AI and all (FUN_1088_3371)
    }

    /// A level change keeps the old level's figures with that level, as its items (stashLevelItems): every object left in the list is
    /// written to the level's IFF (FUN_1148_1232) and read back on a return (FUN_1148_1386), the AI restarted from the record's name
    /// (FUN_1088_3371). KILLFIGURE destroyed its figure, so a killed one has no record; the player and the `travelling` figures are not
    /// left behind. What a record does not keep is reset (as Resume.swift): the processes end with the level, a one-off motion with no
    /// task is held on its last pose, a dead body stays frozen on DIE's last pose.
    func stashLevelFigures(_ travelling: [String] = []) {
        if level.isEmpty { return }
        let keep = Set([playerName ?? "", "PLAYER"] + travelling.map { $0.uppercased() })
        var stay = OrderedMap<Figure>()
        for key in figures.keys {
            guard let fig = figures[key], !keep.contains(key), !keep.contains(fig.name) else { continue }
            fig.aiProc = nil; fig.go = nil; fig.afterGo = nil; fig.confront = nil; fig.area = nil
            fig.unwaited = false; fig.taskName = nil; fig.idleRequest = false; fig.heldPose = nil
            if let frames = fig.frames, let m = fig.motion, !Self.motionLoops(fig.assets, m) {
                fig.loop = false; fig.idx = frames.count - 1; fig.finished = true
            }
            if fig.motion == "DIE", let frames = fig.frames, ((vm?.objects[objectKey(key)]?.first).map { if case .int(let h) = $0 { return h }; return 0 } ?? 1) <= 0 {
                fig.loop = false; fig.idx = frames.count - 1; fig.finished = true
                fig.frozen = true; fig.stopped = true; fig.noIdle = true
            }
            stay[key] = fig
        }
        levelFigures[level] = stay
    }

    /// A level figure's script object locals `~0..~9` are its FIGR record's (figure +0x92; ~0 = hit points, ~5 = MAX HPS), unless
    /// the VM already holds that object.
    func seedObjectLocals() {
        guard let vm else { return }
        for (inst, rec) in data.recordLocals where vm.objects[inst] == nil { vm.setObject(inst, rec) }
    }

    public override func attach(_ vm: ScriptVM) {
        super.attach(vm)
        seedObjectLocals()
    }

    // MARK: figures

    func asset(_ type: String) -> WorldAssets? { resources.asset(type) }

    /// PLAYER is an argument keyword meaning the current player figure (the one flagged by CREATEFIGURE ... PLAYER).
    func resolve(_ name: String) -> String {
        let n = name.uppercased()
        return n == "PLAYER" && playerName != nil ? playerName! : n
    }

    public var player: Figure? { playerName.flatMap { figures[$0] } }
    public var allFigures: [Figure] { figures.values }

    /// MY_SPEED (FIGURES.SCP, read when the figure is made, FUN_1088_22ba stores it at model+0xea).
    func mySpeed(_ name: String, _ type: String) -> Int {
        resources.figureProp(name: name, type: type, prop: "MY_SPEED", default: Self.defaultSpeed)
    }

    /// ELASTICITY (FIGURES.SCP by instance name, default 200; FUN_1088_22ba stores it at +0xde): the 8.8 loss fraction per bounce.
    func elasticity(_ name: String, _ type: String) -> Int {
        resources.figureProp(name: name, type: type, prop: "ELASTICITY", default: 200)
    }

    func isBouncy(_ name: String, _ type: String) -> Bool {
        resources.figureProp(name: name, type: type, prop: "IS_BOUNCY", default: 0) != 0
    }

    /// Figure by instance name (lazy). PLAYER = LEX (not in level data); nil if unknown.
    @discardableResult func figure(_ name: String?) -> Figure? {
        guard let name, !name.isEmpty else { return nil }
        let key = resolve(name)
        if killedFigures.contains(key) { return nil }
        if figures[key] == nil {
            if let d = data.figDefs[key] {
                guard let a = asset(d.type) else { return nil }
                let rec = data.figRecs[key]
                let f = Figure(name: key, type: d.type, assets: a, speed: mySpeed(key, d.type), elasticity: elasticity(key, d.type), pos: d.pos,
                               heading: rec?.heading ?? 0)
                f.viewCams = d.cams ?? []
                f.gravity = d.flags & 1 != 0                                  // the record's +0x34 flags (byte 21)
                f.noCollide = d.flags & 2 != 0
                f.bouncy = d.flags & 0x10 != 0
                f.aiType = d.aiName
                f.hold = d.aiOff
                f.hidden = d.flags & 4 != 0                                   // no hide event: the flag comes with the record (1130:050d only hides a shown figure)
                if let rec {                                                  // the level reader restores the rest of the record too (FUN_1148_0d46), on a
                    let ids = data.objIds                                     // first visit as on a return: motion, velocity, enemy, avoid list ...
                    applyFigureRecord(f, rec, key: key, name: { $0 > 0 && $0 <= ids.count ? ids[$0 - 1].name : nil },
                                      tag: { $0 > 0 && $0 <= ids.count ? ids[$0 - 1].tag : nil })
                }
                figures[key] = f
            } else if key == "PLAYER" && playerName == nil, let a = asset("LEX") {      // backward compat: a LEX figure flagged as player
                playerName = key
                let f = Figure(name: key, type: "LEX", assets: a, speed: mySpeed(key, "LEX"), elasticity: elasticity(key, "LEX"))
                f.bouncy = isBouncy(key, "LEX")
                figures[key] = f
            } else { return nil }
        }
        return figures[key]
    }
    func figure(_ v: ScriptValue?) -> Figure? { v.flatMap { truth($0) ? figure(pyStr($0)) : nil } }

    func warn(_ msg: String) { if !warnings.contains(msg) { warnings.append(msg) } }

    /// -> (xy, z, isFigure) of a waypoint/object/figure name, or nil.
    func target(_ name: String) -> (xy: V2, z: Double, isFigure: Bool)? {
        let n = resolve(name)
        if let p = figures[n]?.pos { return (V2(p.x, p.y), p.z, true) }
        if let p = data.points[n] { return (V2(p.x, p.y), p.z, false) }
        if let p = figure(n)?.pos { return (V2(p.x, p.y), p.z, true) }
        return nil
    }

    /// GO's named target (FUN_10d0_33c8): a figure, else a waypoint, else an IMAG trigger at its box centre (vtable +0x50, trunc per
    /// axis), else `target`. See world.py `go_target`.
    func goTarget(_ name: String) -> (xy: V2, z: Double, isFigure: Bool)? {
        let n = resolve(name)
        if figures[n] == nil, data.waypoints[n] == nil,
           let box = data.objs.first(where: { $0.tag == "IMAG" && $0.name.uppercased() == n && $0.pos2 != nil }) {
            let a = v3(box.pos), b = v3(box.pos2!)
            let c = (0..<3).map { Double(Int((a[$0] + b[$0]) / 2)) }
            return (V2(c[0], c[1]), c[2], false)
        }
        return target(name)
    }

    func spawnContext(_ fig: Figure?, item: Item? = nil) -> ScriptContext { ScriptContext(curFig: fig?.name, curItem: item?.key, owner: "level") }

    @discardableResult func spawnFor(_ fig: Figure, _ block: String, item: Item? = nil) -> Bool {
        guard let vm, vm.blocks[block] != nil else { return false }
        vm.spawn(block, ctx: spawnContext(fig, item: item))
        return true
    }

    /// Engine-raised script event: start `block` if the loaded scripts define it (logged in `events`).
    func fireEvent(_ block: String) {
        guard let vm, vm.blocks[block] != nil else { return }
        events.append((vm.tick, block))
        vm.fire(block)
    }

    // MARK: ScriptEngine

    public override var paused: Bool {
        get { guard let o = options else { return false }; return !o.closed && !o.resumed }      // the credits page resumes the world (FUN_1280_221e -> FUN_1100_0716) unless a forced reload runs (10a8:02cc pauses it then)
        set {}
    }

    public override var sceneAlive: Bool { show.flic?.running ?? false }          // WorldShow.swift
    /// At the end of a walk: an idle requested in an earlier walk has had its task's first run in this one (its slot among the scripts
    /// is not modelled: a STOPMOTION or a new motion earlier in the walk has already dropped it).
    public override func endOfWalk() {
        guard let vm else { return }
        for fig in figures.values {
            if let p = fig.pendingIdle, p.tick < vm.tick {
                fig.pendingIdle = nil
                fig.setMotion(p.name, loop: true, engine: true)
            }
        }
    }
    public override func objectKey(_ name: String) -> String { name.isEmpty ? name : resolve(name) }
    public override func processReferent(_ p: ScriptProcess) -> AnyObject? { referent(of: p) }
    public override func enemy(of figure: String?) -> String? {
        guard let figure, !figure.isEmpty, let f = figures[resolve(figure)], let e = f.enemy, !e.isEmpty else { return nil }
        return e
    }

    /// Unattended play: pick Medium when the opening's difficulty dialog is waiting.
    public func chooseDefaultDifficulty() {
        guard let o = options, !o.closed, o.screen == "difficulty" else { return }
        recordOptionAction(o.activate("MEDX"))
    }

    /// Start with `settings` (the INSTALL.OPT / UserDefaults values, shared with the options dialog): the engine applies them at
    /// startup (FUN_1100_0dc2, FUN_1100_0e6f). Resets the level logs.
    public func configureSettings(_ settings: Settings) {
        self.settings = settings; gamma = settings.gamma
        sfxLog = [(0, settings.sound)]; musicInitial = settings.music; musicVolLog = []
    }

    /// Game > Language: speech (the sound bank), captions, the running monitor and the options dialog (built again when it next opens) follow
    /// at once; the intro movie is picked by INTRO.SCP (GETOPTDATA "LANGUAGE") when a new game starts.
    public func setLanguage(_ language: String) {
        guard Settings.languages.contains(language), language != settings.language else { return }
        settings.language = language
        monitor?.language = language
        settings.persist()
    }

    /// FUN_1100_0dc2(sfx, music), called by the audio panel for every change. Effects: sfx < 1 stops every voice and disables
    /// them (FUN_1028_08f6; the mixer plays nothing), otherwise the master-volume table is rebuilt from sfx (MasterVolume.table)
    /// and scales the volume of sounds that start from the next tick on. Music: the sequencer gets the level (setVolume).
    func applyAudio(sfx: Int, music: Int) {
        if sfx != sfxLog.last!.sfx {
            if sfx < 1, vm != nil { for (h, _) in soundHandles { stopSound(h) } }
            sfxLog.append((tick + 1, sfx))
        }
        if music != (musicVolLog.last?.music ?? musicInitial) { musicVolLog.append((tick, music)) }
    }

    /// FUN_1100_0e6f(g): the offset (Gamma.offset) is added to every presented 6-bit palette channel.
    func applyGamma(_ g: Int) { gamma = g; cancelChangePalette() }        // 1100:0e6f also calls 18c1(0, 0, 0)

    /// Shift/Alt + , . or numpad - + (FUN_10a8_0541 ~1080-1215): +-10, not above 100 / below 0 (the original refuses only at the
    /// limits), applied and persisted at once.
    func adjustGamma(_ step: Int) {
        let g = settings.gamma
        if (step > 0 && g >= 100) || (step < 0 && g <= 0) { return }
        settings.gamma = g + step
        settings.persist()
        applyGamma(settings.gamma)
    }

    /// Alt+V (0x2f): FUN_10a8_0541 case 0x2f calls FUN_10b0_0e12 with the format string "%s  %s~%s" (1290:2c35) and the
    /// three static strings at 1290:4faa/4fb3/4fbd ("BioForge", "ver f1.01", "(C) 1994, 1995 Origin Systems"), guarded on
    /// [50d6]/[50d8] both zero (no caption process already showing). FUN_10b0_0e12/0e5a build a bare caption task, not a
    /// SUBTITLE/MINORSUBTITLE sound object; the port models it as a MINORSUBTITLE with no sound, which the existing
    /// `subtitle()` guard (`minor && live -> return 0`) already refuses while one is showing. ASSUMPTION: default colour
    /// 0x75, since the original's caption task does not set one explicitly.
    func showVersion() {
        _ = subtitle([.int(-1), .int(0x75), .int(0xff), .str("BioForge  ver f1.01~(C) 1994, 1995 Origin Systems")], minor: true)
    }

    @discardableResult func recordOptionAction(_ action: String?) -> String? {
        guard let action else { return nil }
        optionActions.append((tick, action))
        if let o = options, o.closed, o.creditsMode {      // FUN_1100_0ae6 on a credits dialog: CREDITSSTATE is 0 (creditsState), then CreditsRolling
            o.creditsMode = false                          // on the player; a paused (forced reload) dialog loads TITLE instead: NOT PORTED
            if !forcingReloadOn { runAsPlayer("CREDITSROLLING") }
        }
        if action.hasPrefix("difficulty:"), let vm { vm.globals["_difficulty_level"] = .int(Int(action.dropFirst(11))!) }
        else if action == "exit" { exitRequested = true }
        else if action.hasPrefix("save:") || action.hasPrefix("load:") {
            let kind = action.prefix(4), slot = Int(action.dropFirst(5)) ?? 0
            if kind == "save" { saveNative(slot: slot) }
            // A load that fails (an empty or unreadable slot) after a death: the reload dialog comes back, or a dead Lex is left with none.
            else if loadNative(slot: slot) == nil && forcingReloadOn { openOptions(Options.mustReload) }
        }
        else if action == "unsupported:new" { newGameRequested = true }
        else if action.hasPrefix("unsupported:") { warn("options " + action.replacingOccurrences(of: ":", with: " ", options: [], range: action.range(of: ":")) + ": not implemented in preview") }
        return action
    }

    public override func call(_ kind: CallKind, _ name: String, _ args: [ScriptValue], _ proc: ScriptProcess) -> ScriptValue {
        if recordLog { log.append(Entry(tick: tick, block: proc.block.name, kind: kind, name: name, args: args)) }
        if !(kind == .function ? Self.modelledFuncs : Self.modelledStmts).contains(name) && !name.hasPrefix("MON_") {
            let msg = "\(name): unmodelled \(kind == .function ? "function" : "statement") (ignored)"
            if !unmodelled.contains(msg) { unmodelled.append(msg) }
        }
        let fig = name == "CREATEFIGURE" ? nil : figure(proc.curFig)       // CREATEFIGURE must not lazily make 'PLAYER'
        let zero = ScriptValue.int(0)
        let a0 = args.first
        if kind == .function { return callFunction(name, args, proc, fig) ?? zero }
        if name.hasPrefix("MON_") || name == "ADDENTRY" || name == "REMOVEENTRY" {
            cmdMonitor(name, args, proc)
        } else if name == "EXIT" {
            exitRequested = true
        } else if name == "ADDLOGENTRY" && args.count >= 2 {
            let f = figure(a0)
            if addLogEntry(pyStr(args[0]), pyStr(args[1])), let f { spawnFor(f, pyStr(args[0]).uppercased() + "_LOG_ADDED") }
        } else if name == "REMOVELOGENTRY" && args.count >= 2 {
            removeLogEntry(pyStr(args[0]), pyStr(args[args.count - 1]))
        } else if name == "CAMERA", case .str(let word)? = a0 {
            let kw = word.uppercased()
            if kw == "UNLOCK" {                                // FUN_10d0_12f9: auto flag (1290:63da) = 1
                scriptAuto = true; candidate = nil
            } else if args.count > 1 && pyStr(args[1]).uppercased() == "LOAD" {
                // FUN_1110_024a: loads <cam>.CAM into the resource cache and reloads the current one; no event, no switch
            } else if kw == "SHOW" || kw == "AT" || (args.count > 1 && pyStr(args[1]).uppercased() == "UNLOAD") {
                if kw == "SHOW" && args.count > 1 { shownPicture = pyStr(args[1]).uppercased() }   // the screen (renderPresentation) and the dialog's underlay
                warn("CAMERA \(args.map(pyStr).joined(separator: " ")): logged only, no switch")
            } else {                                           // CAMERA <cam>: auto OFF (locked) and switch now
                scriptAuto = false; candidate = nil
                setCamera(kw, "script CAMERA (locked)")
            }
        } else if name == "LOADLEVEL" && !args.isEmpty {
            cmdLoadLevel(args, proc)
        } else if name == "KILL" {
            let target = args.isEmpty || pyStr(args[0]).uppercased() == "CURFIG" ? fig : figure(pyStr(args[0]))
            if let target { killFigure(target, caller: proc) }
        } else if name == "CREATEFIGURE" && !args.isEmpty {
            // CREATEFIGURE <type> [name] [PLAYER]: PLAYER is an argument keyword that flags the figure as the player
            var words = args.compactMap { v -> String? in if case .str(let s) = v { return s.uppercased() }; return nil }
            let isPlayer = words.contains("PLAYER")
            words.removeAll { $0 == "PLAYER" }
            if let ftype = words.first {
                let fname = words.count > 1 ? words[1] : ftype
                if figures[fname] == nil {                     // unplaced until positioned (GO / LOADLEVEL arrival)
                    if let a = asset(ftype) {
                        let f = Figure(name: fname, type: ftype, assets: a, speed: mySpeed(fname, ftype), elasticity: elasticity(fname, ftype))
                        f.bouncy = isBouncy(fname, ftype)
                        f.aiType = fname                       // 1088:2608: +0x178 starts as the upper-cased name; the counter +0x229 as 0
                        figures[fname] = f
                        killedFigures.remove(fname)            // explicit creation replaces the retired instance
                        if let vm {                            // FUN_1088_22ba: a new figure's ~0 = ~5 = MAX HPS
                            let hps = resources.figureProp(name: fname, type: ftype, prop: "MAX HPS", default: 100)
                            vm.setObject(objectKey(fname), [.int(hps), .int(0), .int(0), .int(0), .int(0), .int(hps), .int(0), .int(0), .int(0), .int(0)])
                        }
                    } else { warn("CREATEFIGURE \(ftype): no such figure type") }
                }
                if figures[fname] != nil { proc.curFig = fname }          // the created figure becomes current
                if isPlayer, let f = figures[fname] { playerName = fname; f.viewCams = nil }
            }
        } else if name == "CREATEITEM" && !args.isEmpty {
            let type = pyStr(args[0]).uppercased()
            // 10d0:21c8 -> 1078:0130 -> vtable +0x6c: the instance name is the type; duplicates are normal (addItem keys them apart)
            let created = addItem(Item(name: type, type: type, owner: fig?.name))
            proc.curItem = created.key
            vm?.removeObject(created.key)                       // a new object starts with zeroed locals, not those of a destroyed item
        } else if name == "INDIVIDUALIZE" && args.count >= 2 && pyStr(args[0]).uppercased() == "CURITEM" {
            if let item = items[proc.curItem ?? ""] {
                renameItem(item, pyStr(args[1]).uppercased())
                proc.curItem = item.key
            }
        } else if name == "PLACEITEM" && !args.isEmpty {
            if let item = items[proc.curItem ?? ""] { placeItem(fig, item, pyStr(args[0]), where: Array(args.dropFirst())) }
        } else if name == "MAKEFLATOBJECT" {
            cmdMakeFlatObject(proc, args)
        } else if name == "EXPLODE" {
            cmdExplode(proc, args)
        } else if name == "THROWCURITEM" {
            cmdThrowCurItem(proc, args)
        } else if name == "SETFLOOROFPHYS" {
            cmdSetFloorOfPhys(proc, args)
        } else if name == "TELEPORTALLONPHYS" {
            cmdTeleportAllOnPhys(proc, args)
        } else if Self.audioStmts.contains(name) {
            cmdAudio(name, args)
        } else if name == "ANIMATE" {
            cmdAnimate(proc, args)
        } else if name == "SETREFERENT" {
            cmdSetReferent(proc, args)
        } else if name == "INCVIRTUALSECONDS" {
            cmdIncVirtualSeconds(args)
        } else if name == "FORCERELOAD" {
            cmdForceReload(proc)
        } else if name == "CHANGEMYFORM" {
            cmdChangeMyForm(proc, args)
        } else if name == "GRABCRITTER" {
            cmdGrabCritter(proc, args)
        } else if name == "RELEASEFROMLIMB" {
            cmdReleaseFromLimb(proc, args)
        } else if name == "FREEHAND" {
            cmdFreeHand(proc, args)
        } else if Self.presentationStmts.contains(name) {
            cmdPresentation(name, args, proc)
        } else if Self.showStmts.contains(name) {
            cmdShow(name, args, proc)
        } else if name == "KILLCURITEM" {
            let killed = items[proc.curItem ?? ""]
            items[proc.curItem ?? ""] = nil
            killItemReferents(killed, caller: proc)
            proc.curItem = nil
        } else if name == "CAMERAAUTOACTIVATE" && args.count >= 2, case .str(let cam) = args[0] {
            if pyStr(args[1]).uppercased() == "OFF" { disabled.insert(cam.uppercased()) } else { disabled.remove(cam.uppercased()) }
        } else if name == "CAMERAFOLLOW" && !args.isEmpty {
            if case .str(let s) = args[0] { follow = s.uppercased() }
        } else if name == "FINDFIRSTFIGURE" {
            _ = findFigure(proc, first: true)
        } else if name == "GRAVITY" && !args.isEmpty {
            if pyStr(args[0]).uppercased() == "CURFIG", let fig, args.count >= 2 {
                fig.gravity = pyStr(args[1]).uppercased() == "ON"      // FUN_1070_2232 / 223f only set the bit
            } else if pyStr(args[0]).uppercased() == "CURITEM", let item = items[proc.curItem ?? ""], args.count >= 2 {
                loadItemPhysics(item)                          // the same method on an item (TEMPLE: GRAVITY CURITEM OFF)
                item.gravity = pyStr(args[1]).uppercased() == "ON"
            }
        } else if name == "COLLISIONS" && !args.isEmpty {
            let enabled = args.count >= 2 && pyStr(args[1]).uppercased() == "ON"
            if pyStr(args[0]).uppercased() == "CURFIG", let fig {
                fig.noCollide = !enabled
            }
        } else if name == "BOUNCINESS" && args.count >= 2 {
            let target = pyStr(args[0]).uppercased()
            let targetFig = target == "CURFIG" ? fig : figure(target)
            targetFig?.bouncy = pyStr(args[1]).uppercased() == "ON"
        } else if name == "STOPVELOCITY" && !args.isEmpty {
            if let targetFig = velocityFigure(args[0], fig, proc) {      // FUN_10d0_787c zeroes the velocity and the step
                targetFig.vx = 0; targetFig.vy = 0; targetFig.vz = 0
                targetFig.step = [0, 0, 0]
            }
        } else if name == "SETVELOCITY" && args.count >= 4, case .int(let x) = args[1], case .int(let y) = args[2], case .int(let z) = args[3] {
            // FUN_10d0_7493: the three s32 arguments raw, units per 30 fps frame; the step is untouched
            if let targetFig = velocityFigure(args[0], fig, proc) { targetFig.vx = wrap32(x); targetFig.vy = wrap32(y); targetFig.vz = wrap32(z) }
        } else if name == "LEAP" && args.count >= 3, case .int(let pitch) = args[args.count - 2], case .int(let speed) = args[args.count - 1] {
            if let targetFig = velocityFigure(args[0], fig, proc) { leap(targetFig, pitch, speed, target: args.count >= 4 ? args[1] : nil) }
        } else if name == "LINKMETOCAMERAS" && !args.isEmpty {
            linkToCameras(proc, args)
        } else if (name == "DEFINEVIEWINGCAMS" || name == "ADDVIEWINGCAMS"), let fig, fig.viewCams != nil {
            if name == "DEFINEVIEWINGCAMS" { fig.viewCams = [] }
            for case .str(let s) in args {
                let c = s.uppercased()
                if !fig.viewCams!.contains(c) && fig.viewCams!.count < Self.maxViewCams { fig.viewCams!.append(c) }
            }
        } else if name == "STOPSOUND" && !args.isEmpty && vm != nil {
            if case .int(let h) = args[0], let p = vm!.process(h), p.block.name == "TIMED" { stopSound(p.handle) }
        } else if name == "STOPALLSOUNDS" && vm != nil {
            for (h, _) in soundHandles { stopSound(h) }
        } else if name == "STOPAMBIENT" && !args.isEmpty && vm != nil {
            // FUN_10d0_777a -> FUN_1028_10c9: a voice with the loop flag (+0x3a) is released and plays to the end of its sample
            // (releaseLoop) while any other voice is left alone, unlike STOPSOUND, which stops it at once.
            if case .int(let h) = args[0], let p = vm!.process(h), p.block.name == "TIMED", soundLoops.contains(p.handle) { releaseLoop(p.handle) }
        } else if name == "MUSIC" && !args.isEmpty {
            currentMusic = args[0]
            musicLog.append((tick, args[0]))
        } else if name == "CAPTUREKEYBOARD" {                                    // [6530]: WorldShow.swift
            cmdCaptureKeyboard(proc, args)
        } else if name == "RELEASEKEYBOARD" {
            cmdReleaseKeyboard()
        } else if name == "APPLY" && !args.isEmpty {
            applyDecal(pyStr(args[0]).uppercased() == "CURFIG" ? fig : figure(pyStr(args[0])), args)
        } else if name == "AI" && !args.isEmpty {
            let words = args.map { pyStr($0).uppercased() }
            var target = fig                                   // 10d0:04b3: the second word names the figure, or is NO_STOP_MOTION; so is a third
            if words.count > 1 && words[1] != "NO_STOP_MOTION" { target = figure(words[1]) }
            if let target {
                cmdAI(target, words[0] == "ON", stop: !words.dropFirst().contains("NO_STOP_MOTION"), proc: proc)
            } else if fig != nil || words.count > 1 {
                warn("AI \(words.joined(separator: " ")): no such figure")
            }
        } else if let fig { callFigure(name, args, proc, fig) }
        return zero
    }

    /// Statements that need a current figure.
    private func callFigure(_ name: String, _ args: [ScriptValue], _ proc: ScriptProcess, _ fig: Figure) {
        let a0 = args.first
        let upper0 = a0.map { pyStr($0).uppercased() }
        if name == "FLOATATHEIGHT" && !args.isEmpty { cmdFloatAtHeight(fig, args)
        } else if name == "SETAI" && !args.isEmpty { fig.aiType = upper0
        } else if name == "INDIVIDUALIZE" && args.count >= 2 && upper0 == "CURFIG" { renameFigure(fig, pyStr(args[1]).uppercased(), proc)
        } else if name == "ADDAVOIDANCEPOINT" && args.count >= 2 { addAvoidance(fig, pyStr(args[0]), args[1])
        } else if name == "REMOVEAVOIDANCEPOINT" && !args.isEmpty { removeAvoidance(fig, pyStr(args[0]))
        } else if name == "DEFINEENEMY" && !args.isEmpty { fig.enemy = upper0
        } else if name == "INVULNERABLE" && !args.isEmpty { fig.invulnerable = upper0 == "ON"
        } else if name == "COMBATMODE" && !args.isEmpty { fig.combat = upper0 == "ON"
        } else if name == "SPARWITHPLAYER" {
            fig.spar = true
            if let player, player !== fig { fig.enemy = "PLAYER"; player.enemy = fig.name } // FUN_10d0_76c9: reciprocal targets
        } else if name == "CONFRONTENEMY" {
            startConfront(fig, proc)
        } else if name == "TURNTOENEMY" {
            turnToEnemy(fig, !args.isEmpty ? Self.turnStep : nil)
        } else if name == "DAMAGE" && !args.isEmpty {
            // FUN_10d0_230e: FUN_1090_09b9(current figure, no attacker, n, 1 with ENERGY else 0, zone 6, not heavy)
            let n = args.lazy.compactMap { v -> Int? in if case .int(let i) = v { return i }; return nil }.first ?? 0
            let energy = args.contains { if case .str(let s) = $0 { return s.uppercased() == "ENERGY" }; return false }
            if vm != nil { damage(fig, nil, n, energy ? 1 : 0, 6, false) }
        } else if name == "GO" && !args.isEmpty { cmdGo(fig, args, proc)
        } else if name == "FACE" && !args.isEmpty { cmdFace(fig, args[0])
        } else if name == "TURN", case .int(let n)? = a0 { fig.heading -= Double(n)    // 10d0:8841 -> 10a0:19e6(fig, n << 8): n degrees, the auto-turn's routine and sign (positive = left)
        } else if name == "MOTION" && !args.isEmpty { cmdMotion(fig, pyStr(args[0]), args.dropFirst().map { pyStr($0).uppercased() }, proc)
        } else if name == "SNAPTOPOSE" && !args.isEmpty { cmdSnapToPose(fig, args) }
        else if name == "STOPMOTION" { fig.confront = nil; fig.stopMotion() }   // FUN_1098_0789(fig, 1, 1)
    }

    /// FUN_1090_135a: remove a figure from active world lists, but leave the issuing script alive for following statements.
    func killFigure(_ fig: Figure, caller: ScriptProcess? = nil) {
        let key = fig.name
        if let vm {
            var record = vm.objectRecord(objectKey(key))
            record[0] = .int(-666)
            vm.setObject(objectKey(key), record)
            if let ai = fig.aiProc, ai !== caller, !ai.done { vm.finish(ai) }
            for handle in soundPos.compactMap({ $0.value.key == key ? $0.key : nil }) {
                stopSound(handle)
                soundPos[handle] = nil
            }
        }
        fig.aiProc = nil; fig.go = nil; fig.afterGo = nil; fig.inTrig = nil
        fig.avoid.removeAll()
        figures = figures.filtering { $0 != key }
        deadFigures[key] = fig
        killedFigures.insert(key)
    }

    private func callFunction(_ name: String, _ args: [ScriptValue], _ proc: ScriptProcess, _ fig: Figure?) -> ScriptValue? {
        let a0 = args.first
        func bool(_ b: Bool) -> ScriptValue { .int(b ? 1 : 0) }
        func int(_ k: Int) -> Int? { args.count > k ? { if case .int(let i) = args[k] { return i }; return nil }() : nil }
        switch name {
        case "ANGLEFROMENEMY", "DISTFROMENEMY", "ATTACKRADIUS": return .int(combatQuery(fig, name))
        case "SUBTITLE", "MINORSUBTITLE": return vm == nil ? nil : .int(subtitle(args, minor: name == "MINORSUBTITLE"))
        case "SOUND" where !args.isEmpty, "AMBIENT" where !args.isEmpty:
            // AMBIENT (10d8:06b2 -> FUN_10c0_32e1 -> FUN_1028_0f0a) is SOUND's twin that loops: 1028:09d3 clears the voice's loop flag +0x1d, 0f0a sets it
            guard let idx = soundIndex(args[0]) else { return .int(vm?.timedHandle(ticks: Self.soundTicks) ?? 0) }
            if let cf = proc.curFig, !cf.isEmpty, fig == nil {   // FUN_1100_196c: a current figure that does not resolve = error, no sound
                warn("\(name) \(pyStr(args[0])): current figure \(cf) not found")
                return .int(-1)
            }
            // ASSUMPTION: a non-numeric volume/pitch (e.g. an object name) means the default; an unplaced figure is not positional
            return .int(playSound(idx, volume: int(1) ?? 255, pitch: int(2) ?? 0, loop: name == "AMBIENT", fig: fig?.pos != nil ? fig : nil))
        case "GETSOUNDHANDLE" where vm != nil:
            let idx = a0.flatMap(soundIndex)
            if let h = soundHandles.last(where: { $0.index == idx && vm!.process($0.handle) != nil }) { return .int(h.handle) }   // the newest live handle
            return .int(vm!.timedHandle(ticks: Self.soundTicks))
        case "ISSOUNDPLAYING" where !args.isEmpty && vm != nil:
            let idx = soundIndex(args[0])
            return bool(idx != nil && soundHandles.contains { $0.index == idx && vm!.process($0.handle) != nil })
        case "ISHANDLEPLAYING":
            if case .int(let h)? = a0, let vm { return bool(vm.process(h) != nil) }
            return .int(0)
        case "RANDOM" where args.count >= 2:
            guard let lo = int(0), let hi = int(1) else { return nil }
            return .int(rng.randint(min(lo, hi), max(lo, hi)))          // inclusive range (ASSUMPTION)
        case "COUNTBITS" where args.count >= 3:
            guard let v = int(0), let lo = int(1), let hi = int(2) else { return nil }
            return .int(lo > hi ? 0 : (lo...hi).reduce(0) { $0 + ((v >> $1) & 1) })   // set bits lo..hi (GETFLAG bit n = 1 << n)
        case "ISMONITORRUNNING": return bool(monitor != nil || (options.map { !$0.closed } ?? false))
        case "MON_LISTGETINDEX": return .int(monitor?.selectedIndex(a0.map(pyStr) ?? "") ?? 0)
        case "MON_INVITEMFRAME":
            guard let name = a0.map(pyStr), let itemName = monitor?.selectedItem(name), let item = items[itemName] else { return .int(0) }
            for key in [item.name, item.type] {
                guard let block = vm?.blocks[key] else { continue }
                for table in block.tables where table.values.count >= 4 {
                    let values = table.values.map(pyStr)
                    if Array(values.prefix(3)) == ["MONITOR", "ART", "FRAME"], case .int(let frame) = table.values.last { return .int(frame) }
                }
            }
            return .int(0)
        case "ISLEVEL": return bool(a0.map { pyStr($0).uppercased() == level } ?? false)
        case "SETCURRENTFIGURE":                                   // the VM already set the context; result = figure exists
            let n = a0.map { resolve(pyStr($0)) } ?? ""
            if !killedFigures.contains(n) && (figures.contains(n) || data.figDefs[n] != nil) { return .int(1) }
            if let alt = figureByType(n) {                        // FUN_10c0_3e14: the name may also be the figure's type name
                proc.curFig = alt.name
                return .int(1)
            }
            return .int(0)
        case _ where Self.waypointFuncs.contains(name) && args.count >= 2:
            return .int(waypointQuery(proc, name, args[0], args[1]))
        case "SETCURRENTITEM":
            return .int(a0 == nil ? 0 : setCurrentItem(proc, fig, pyStr(a0!)))        // 10c0:3fd9; the VM leaves CURITEM alone for this engine
        case "ISCARRYING" where !args.isEmpty:
            return bool(isCarryingItem(fig, pyStr(args[0]), args.count > 1 ? pyStr(args[1]) : nil))
        case "ISCARRYINGANYTHING" where !args.isEmpty: return bool(isCarrying(fig, pyStr(args[0]).uppercased(), nil))
        case "ISMYMOTION", "ISPLAYERSMOTION", "MOTIONEXISTS":
            guard !args.isEmpty else { return nil }
            guard let f = name == "ISPLAYERSMOTION" ? player : fig else { return .int(0) }
            let m = pyStr(args[0]).uppercased()
            if name == "MOTIONEXISTS" { return bool(f.assets.motion(m) != nil) }
            return bool(f.motion == m && !f.finished)              // ASSUMPTION: a finished one-shot motion no longer counts
        case "VELOCITYX", "VELOCITYY", "VELOCITYZ":
            guard !args.isEmpty else { return nil }
            guard let f = velocityFigure(args[0], fig, proc) else { return .int(0) }      // a missing object -> 0
            let v = name == "VELOCITYX" ? f.vx : name == "VELOCITYY" ? f.vy : f.vz
            // FUN_10d8_3c04/3c43/3c82 return the low 16 bits (AX only). ASSUMPTION: the script value is a signed 16-bit int
            // (sign-extended back into SETVELOCITY's s32 argument)
            return .int(Int(Int16(truncatingIfNeeded: v)))
        case "ISHIDDEN": return bool(fig?.hidden ?? false)
        case "ISINVULNERABLE": return bool(fig?.invulnerable ?? false)
        case "AMINTRIGGER" where args.count >= 2: return .int(amInTrigger(proc, args[0], args[1]))
        case "COMPASS": return .int(compass(fig))
        case "HEADING": return .int(motionHeading(proc, args.first ?? .str("CURFIG")))
        case "ISINCOMBATMODE":
            guard let fig else { return .int(0) }                  // the original reports an error; silent here, as for COMPASS
            return .int(fig.combat ? 0x40 : 0)                    // FUN_10d8_2c4f returns flags (+0x34) & 0x40, not 1
        case "ISKEYPRESSED":
            // FUN_10d8_2d17: the byte at DGROUP 1290:7bbe + the argument's low byte is the key state table; the ports keep the held PC
            // scan codes (keysHeld, keysCaptured). ASSUMPTION: a key held while a monitor is open is not recorded (keyDown drops it).
            if case .int(let k)? = a0 { return bool(keysHeld.contains(k & 0xff) || keysCaptured.contains(k & 0xff)) }
            return .int(0)
        case "ISMYFORM":
            // FUN_10d8_2d98: stricmp (FUN_1000_5a06) of the argument with the figure's form name at +0x1ea. An empty argument or no
            // current figure is an error (-> 0; silent for a missing figure, as for COMPASS). ASSUMPTION: +0x1ea holds the FIGR record's
            // type name, Figure.type.
            guard let fig else { return .int(0) }
            guard let a0, !pyStr(a0).isEmpty else { warn("ISMYFORM: no form name"); return .int(0) }
            return bool(fig.type.uppercased() == pyStr(a0).uppercased())
        case "AMINEXTENT" where args.count >= 2: return .int(amInExtent(proc, args[0], args[1]))
        case "ISCURRENTCAMERA":
            // 10d8:2aea: stricmp of the argument with the camera name [63e1] or the room name [63e5] (scripts ask ISCURRENTCAMERA BCH);
            // 1130:0114 writes both before it runs the events, so a _LOAD block already sees the new camera here
            guard let a0, let cam = switchingTo ?? camera ?? defaultCamera else { return bool(false) }
            let word = pyStr(a0).uppercased()
            return bool(word == cam || word == String(cam.prefix(3)))
        case "COORDX", "COORDY", "COORDZ":                         // 10d8:0fc6 / 100a / 104e: the object (FUN_10c0_16a8: CURFIG, CURITEM, a
            guard let a0 else { return nil }                       // figure / floor item name) +0xb position component; no object: 0, no error
            let obj = scriptObject(proc, a0)
            guard let pos = objectPos(obj) else { return .int(0) }
            if name == "COORDZ" {                                  // +0xf is origin + R; the port's origin leaves R out
                return .int((Int(pos.z) + (obj.fig.map(modelRootZ) ?? 0)) >> 8)
            }
            return .int(Int(name == "COORDX" ? pos.x : pos.y) >> 8)     // FUN_1000_2727: long SAR by 8 (floor)
        case "DISTFROMEXTENT", "DISTFROMTRIGGER":
            guard args.count >= 2 else { return nil }
            return .int(boxDistance(proc, name, args[0], args[1]))
        case "DISTFROMITEM", "2DDISTFROMITEM": return .int(itemDistance(proc, name))
        case "2DDISTFROMCOORDS":
            guard args.count >= 3, let x = int(1), let y = int(2) else { return nil }
            return .int(distanceFromCoords(proc, args[0], x, y))
        case "FINDNEXTFIGURE": return .int(findFigure(proc, first: false))
        case "FADE": return .int(cmdFade(proc, args))
        case "RUNFLIC", "PLAYFLIC", "WASALTPRESSED", "CREDITSSTATE", "GETOPTDATA": return .int(cmdShowFunc(name, args, proc))
        case "FIRE": return .int(cmdFire(proc, args))
        case "MAKEMISSILE": return .int(cmdMakeMissile(proc, args))
        case "ISAION":                                              // 10d8:27e8: the current figure's +0x229 == 0
            guard let fig else { warn("ISAION: no current figure"); return .int(0) }
            return bool(fig.hold == 0)
        case "ISGRAVITYON":                                         // 10d8:2b57: flags (+0x34) bit 0x01
            guard let a0 else { return nil }
            let sel = pyStr(a0).uppercased()
            if let f = figure(sel == "CURFIG" ? proc.curFig : sel) { return bool(f.gravity) }
            var isItem = sel == "CURITEM" && items.contains(proc.curItem ?? "")
            if figure(sel) == nil && itemByType(sel) != nil { isItem = true }
            if !isItem { warn("ISGRAVITYON \(pyStr(a0)): no such object") }
            return .int(0)                                          // the ports do not keep an item's flags byte
        case "ISKEYBOARDCAPTURED": return bool(keyboardCaptured)    // 10d8:2cf3
        case "GETROOMAMBIENT", "GETCAMERAAMBIENT":                  // 10d8:26a8 / 10d8:21b4: [63f6] / [63f2], -1 = none (a dead voice's handle stays)
            let h = name == "GETROOMAMBIENT" ? roomAmbient : cameraAmbient
            return .int(h == 0 ? -1 : h)
        case "MODIFYVOLUMEOVERTIME", "MODIFYPITCHOVERTIME": return .int(cmdOvertime(name, args))
        default: return nil
        }
    }

    // MARK: log entries (the persistent named-key store behind ADDLOGENTRY)

    func addLogEntry(_ log: String, _ key: String) -> Bool {
        let log = log.uppercased(), key = key.uppercased()
        var entries = logEntries[log] ?? []
        if entries.contains(key) { return false }
        entries.append(key)
        logEntries[log] = entries
        logEntryTimes[log, default: []].append(gameTick)         // the award stamp is the game clock [8330]
        return true
    }

    func removeLogEntry(_ log: String, _ key: String) {
        let log = log.uppercased(), key = key.uppercased()
        let entries = logEntries[log] ?? [], times = logEntryTimes[log] ?? []
        let kept = zip(entries, times).filter { $0.0 != key }
        logEntries[log] = kept.map(\.0)
        logEntryTimes[log] = kept.map(\.1)
    }

    /// MON_* statements (handlers in seg 10d0).  The authored PIMM core uses the common element subset;
    /// unsupported monitor operations stay no-ops until their element types are recovered.
    func cmdMonitor(_ name: String, _ args: [ScriptValue], _ proc: ScriptProcess) {
        let nums = args.compactMap { v -> Int? in if case .int(let i) = v { return i }; return nil }
        let strings = args.compactMap { v -> String? in if case .str(let s) = v { return s }; return nil }
        let state = nums.first ?? 0
        switch name {
        case "MON_START":
            guard let s = strings.first else { return }
            do {
                let screen = try MonitorScreen(name: s, game: game)
                screen.language = settings.language
                screen.setVariableResolver({ [weak self] name in
                    guard let vm = self?.vm else { return nil }
                    let key = vm.globals.keys.first { $0.caseInsensitiveCompare(name) == .orderedSame }
                    return key.flatMap { vm.globals[$0] }.map(pyStr) ?? "0"
                }, formatTime: { stamp in
                    let minutes = (2 * stamp) / 3600
                    let (hours, minute) = minutes.quotientAndRemainder(dividingBy: 60)
                    let (day, hour) = hours.quotientAndRemainder(dividingBy: 24)
                    return "\(day)-\(String(format: "%02d%02d", hour, minute))"
                }, currentTime: { [weak self] in
                    let stamp = self?.gameTick ?? 0                       // [8330]
                    let minutes = (2 * stamp) / 3600
                    let (hours, minute) = minutes.quotientAndRemainder(dividingBy: 60)
                    let (day, hour) = hours.quotientAndRemainder(dividingBy: 24)
                    return "\(day)-\(String(format: "%02d%02d", hour, minute))"
                })
                screen.setViewportRenderer { [weak self] camera in self?.viewportFrame(camera) }
                monitor = screen
            }
            catch { warn("MON_START \(s): \(error)") }
        case "MON_HIDEALL": monitor?.hideAll()
        case "MON_ENABLEINPUT": if let n = nums.first { monitor?.setInput(n != 0) }
        case "MON_SETPTR": if let n = strings.first { monitor?.setPointer(n) }
        case "MON_SETPTRFRAME": if let n = nums.first { monitor?.setPointerFrame(n) }
        case "MON_SETPTRPOS": if nums.count >= 2 { monitor?.placePointer(x: nums[0], y: nums[1]) }
        case "MON_SETFRAME":
            if let e = strings.first, let frame = nums.first { monitor?.setFrame(e, frame) }
        case "MON_DEFINETEXT":
            if strings.count >= 2 { monitor?.defineText(strings[0], strings[1], state: state) }
        case "MON_DEFINELIST":
            if strings.count >= 2 {
                let log = strings[1].uppercased()
                monitor?.defineList(strings[0], strings[1], keys: logEntries[log] ?? [], times: logEntryTimes[log] ?? [])
            }
        case "MON_DEFINEBUTTON":
            if let name = strings.first { monitor?.defineButton(name, strings.count >= 2 ? strings[1] : "", state: state, mode: nums.count > 1 ? nums[1] : 0) }   // the text is optional: CC_CIRCUITBOARD's buttons have none
        case "MON_MAKEINVENTORY":
            if let name = strings.first { monitor?.makeInventory(name, inventoryItems().map { ($0.name, $0.type, $0.key) }) }
        case "MON_SETITEM":
            if let name = strings.first { proc.curItem = monitor?.selectedItem(name) }
        case "MON_SCROLLLIST":
            if let name = strings.first, let code = nums.first { monitor?.scrollList(name, code) }
        case "MON_SETSCALE":
            if let name = strings.first, nums.count >= 2 { monitor?.setScale(name, nums[0], nums[1]) }
        case "MON_DEFINEVIEWPORT":
            if strings.count >= 2 { monitor?.defineViewport(strings[0], strings[1]) }
        case "ADDENTRY":
            if strings.count >= 2 { monitor?.addEntry(strings[0], strings[1]) }
        case "REMOVEENTRY":
            if strings.count >= 2 { monitor?.removeEntry(strings[0], strings[1]) }
        case "MON_JUMP":
            guard let monitor else { proc.ended = true; return }
            let action = monitor.poll()
            proc.goto = action.label
            if action.wait > 0 {
                let until = (vm?.tick ?? 0) + action.wait
                proc.waitPred = { [weak self] in (self?.vm?.tick ?? until) >= until }
            }
        case "MON_STOP": monitor = nil
        case "MON_CODE", "MON_SIMULATE", "MON_DESTROYOPTIONS":
            monitorCodes.append((name, nums.first))
            if name == "MON_CODE", let n = nums.first {
                openOptions(n)
            } else if name == "MON_DESTROYOPTIONS" { options?.closed = true }
            else if name == "MON_SIMULATE", let key = nums.first { monitor?.keyEvent(key & 0xff, force: true) }     // FUN_1258_017f: the key goes to the event handler with input forced on (_KB_TAB = 9)
        default: break
        }
    }

    /// Player-owned items stored in the INVENTORY slot, in creation order.
    func inventoryItems() -> [Item] {
        items.values.filter { $0.owner == playerName && $0.slot == "INVENTORY" }
    }

    func isCarrying(_ fig: Figure?, _ slot: String, _ type: String?) -> Bool {
        guard let fig else { return false }
        return items.values.contains { $0.owner == fig.name && (slot == "ANYWHERE" || $0.slot == slot) && (type == nil || $0.type == type) }
    }
}
