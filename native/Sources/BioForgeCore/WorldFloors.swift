// Floors: the script statements SETFLOOROFPHYS (10d0:708e) and TELEPORTALLONPHYS (10d0:7d5b), the garage elevator of CONTROL (CONMACH.scr
// RAISE_GARAGE_ELEVATOR / LOWER_GARAGE_ELEVATOR). Port of re/interp/floors.py (the oracle, which also holds the decoded rules and the
// ASSUMPTIONs).
//
// Both look the PHYS up by name like AMINEXTENT does (FUN_1050_0996: the first PHYS of that name) and never block. SETFLOOROFPHYS moves one
// PHYS box in z (the box keeps its height); TELEPORTALLONPHYS carries every item and figure whose hull lies strictly inside box A in x and y
// over to box B, scaled between the two boxes, seated on B's floor. The scripts turn the player's gravity off for the ride, so SetPos does
// not snap the player to the support. The engine also persists the moved box in the level state / saves (INFERRED) and sets DAT_222c = 2 so
// loose items re-check their support for ~2 frames: NOT PORTED.
import Foundation

extension World {
    /// The first PHYS named `name` (FUN_1050_0996, as AMINEXTENT): its index in `data.phys`.
    func findPhys(_ name: String) -> Int? { data.phys.firstIndex { $0.name == name } }

    private func scriptWords(_ args: [ScriptValue]) -> (words: [String], nums: [Int]) {
        let flat = args.flatMap { v -> [ScriptValue] in if case .list(let l) = v { return l }; return [v] }
        return (flat.compactMap { v -> String? in if case .str(let s) = v { return s.uppercased() }; return nil },
                flat.compactMap { v -> Int? in if case .int(let i) = v { return i }; return nil })
    }

    // MARK: SETFLOOROFPHYS

    /// `SETFLOOROFPHYS <name> <n>` (10d0:708e): n is only its low 16 bits, signed (MOV SI,[ctx+0xe2b]; CWD at 10d0:70a7), in script coordinate
    /// units (v = n << 8, as COORDZ). Warnings (nothing moves): no name (0xfc); n & 0xffff == 0 (0xfd: `X 0` is an error, not a move); no such
    /// PHYS (0x8b); a state that is neither 0 nor 1 (0x100). With h = hi.z - lo.z: state 0 (space) lo.z = v, hi.z = v + h; state 1 (solid)
    /// hi.z = v, lo.z = v - h. x and y are untouched and no object moves.
    func cmdSetFloorOfPhys(_ proc: ScriptProcess, _ args: [ScriptValue]) {
        let (words, nums) = scriptWords(args)
        guard let name = words.first, !name.isEmpty else { warn("SETFLOOROFPHYS: needs a PHYS name (error 0xfc)"); return }
        let n = Int(Int16(truncatingIfNeeded: nums.first ?? 0))
        guard n != 0 else { warn("SETFLOOROFPHYS \(name): needs a non-zero floor (error 0xfd)"); return }
        guard let i = findPhys(name) else { warn("SETFLOOROFPHYS \(name): no such PHYS (error 0x8b)"); return }
        let state = physState(data.phys[i])
        guard state == 0 || state == 1 else { warn("SETFLOOROFPHYS \(name): PHYS state \(state) (error 0x100)"); return }
        let v = n << 8, h = Int(data.phys[i].hi.z) - Int(data.phys[i].lo.z)
        let (lo, hi) = state == 0 ? (v, v + h) : (v - h, v)
        for fig in figures.values where fig.pos != nil && fig.storedHull?.tick != tick {   // 708e rebuilds no hulls: fig+0x65 stays as 21b2 left it
            let h = queryHull(fig)
            fig.storedHull = (tick, h.lo, h.hi)
        }
        data.phys[i].lo.z = Double(lo)
        data.phys[i].hi.z = Double(hi)
        let cached = boxes != nil              // step() caches the boxes for the figures; the script runs inside it (`boxes` didSet drops areaCache)
        boxes = nil
        if cached { boxes = physBoxes() }
    }

    // MARK: TELEPORTALLONPHYS

    /// `TELEPORTALLONPHYS <A> <B>` (10d0:7d5b): every item (the item list, then the figure list: the player too, hidden or dead ones not
    /// excluded) whose hull lies STRICTLY inside A in x and y (FUN_1058_18b4; z is not tested) moves to B: x' = B.lo.x + fixMul(x - A.lo.x, sx),
    /// y' likewise, sx = fixDiv(B width x, A width x), z' = B's floor + (z - hull bottom), so the height above the object's own hull bottom
    /// (+0x6d) is kept. B's floor is lo.z for a state 0 box and hi.z for state 1. The set is evaluated before anything moves; each object then
    /// gets its SetPos (figures: setPos, which zeroes velocity / step; items: 1070:1e9d, no snap). Warnings (nothing moves): a missing name
    /// (0xff), no such PHYS (0x15), a B state that is neither 0 nor 1. A zero-width A is guarded (ASSUMPTION: scale 256, the engine would divide
    /// by zero). ASSUMPTION: an item has no hull in the port, its xy test uses the point position and its hull bottom is z - EXTENT z (0 when
    /// its physics are not loaded yet; a missile has its extent from the start); a carried item (pos nil) is skipped.
    func cmdTeleportAllOnPhys(_ proc: ScriptProcess, _ args: [ScriptValue]) {
        let words = scriptWords(args).words
        guard words.count >= 2, !words[0].isEmpty, !words[1].isEmpty else { warn("TELEPORTALLONPHYS: needs two PHYS names (error 0xff)"); return }
        var found: [Int] = []
        for name in words.prefix(2) {
            guard let i = findPhys(name) else { warn("TELEPORTALLONPHYS \(name): no such PHYS (error 0x15)"); return }
            found.append(i)
        }
        let a = data.phys[found[0]], b = data.phys[found[1]]
        let state = physState(b)
        guard state == 0 || state == 1 else { warn("TELEPORTALLONPHYS \(words[1]): PHYS state \(state)"); return }
        let alo = SIMD3<Int>(a.lo, rounding: .towardZero), ahi = SIMD3<Int>(a.hi, rounding: .towardZero)
        let blo = SIMD3<Int>(b.lo, rounding: .towardZero), bhi = SIMD3<Int>(b.hi, rounding: .towardZero)
        let sx = ahi.x != alo.x ? fixDiv(bhi.x - blo.x, ahi.x - alo.x) : 256
        let sy = ahi.y != alo.y ? fixDiv(bhi.y - blo.y, ahi.y - alo.y) : 256
        let floor = state == 0 ? blo.z : bhi.z
        func inside(_ lo: SIMD3<Int>, _ hi: SIMD3<Int>) -> Bool { alo.x < lo.x && hi.x < ahi.x && alo.y < lo.y && hi.y < ahi.y }
        func xy(_ x: Int, _ y: Int) -> (Double, Double) { (Double(blo.x + fixMul(x - alo.x, sx)), Double(blo.y + fixMul(y - alo.y, sy))) }
        func round(_ v: Double) -> Int { Int(v.rounded(.toNearestOrEven)) }

        var itemMoves: [(Item, V3)] = [], figMoves: [(Figure, V3)] = []
        for it in items.values {
            guard let p = it.pos else { continue }
            let x = round(p.x), y = round(p.y)
            let dz = it.physicsLoaded || it is Missile ? it.extent[2] : 0
            if inside(SIMD3(x, y, 0), SIMD3(x, y, 0)) {
                let (nx, ny) = xy(x, y)
                itemMoves.append((it, V3(nx, ny, Double(floor + dz))))
            }
        }
        for fig in figures.values {
            guard let p = fig.pos else { continue }
            // 10d0:7d5b reads the hull at fig+0x65/+0x6d, the one 21b2 built before this script's SETFLOOROFPHYS moved a floor
            let h = fig.storedHull.flatMap { $0.tick == tick ? (lo: $0.lo, hi: $0.hi) : nil } ?? { let q = queryHull(fig); return (lo: q.lo, hi: q.hi) }()
            if inside(h.lo, h.hi) {
                let (nx, ny) = xy(round(p.x), round(p.y))
                figMoves.append((fig, V3(nx, ny, p.z + Double(floor - h.lo.z))))
            }
        }
        for (it, pos) in itemMoves {
            it.pos = pos
            it.vel = [0, 0, 0]; it.step = [0, 0, 0]
        }
        for (fig, pos) in figMoves { setPos(fig, pos) }
    }
}
