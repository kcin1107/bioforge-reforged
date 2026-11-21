// SALSA skeleton (.SKL), skin (.SKN), motions (.MTN) and forward kinematics, mirrors re/formats/salsa.py.
//
// SKL: the first "LIMB" tag in the file (searched as raw bytes) is followed by u32be size and size/39 records:
//   char name[9], s16 parent, s16 rest[3], s16 angle[3], s32 length, s32 offset[3]
// SKN: first "LINK" tag, u32be size, size/2 u16 limb indices (one per mesh vertex).
// MTN: FORM MOTN of (header chunk, PRLE|POSE chunk) pairs. Header: name (16 bytes), +77 u8 nlimbs, +79 u16 rowbytes,
//   +81 u16 nframes, +76 u8 frame time, +30 u8 flags (in memory the header sits 6 bytes later: motion+0x52, +0x24). POSE: nframes rows of (s32 pos[3], s16 rootAngle[3], nlimbs * (s16 angle[3], u16 scale)).
//   PRLE: nframes * (s32 pos[3], s16 rootAngle[3]) then an RLE stream of nframes*nlimbs*3 s8 angles, axis-major
//   ((a0 of limb 0..n-1), (a1 ...), (a2 ...), each nframes long): c >= 0x80 -> (c-0x80) copies of the next byte,
//   else c literal bytes; runs span channels.
// Angles: 256 units per turn. Matrix rows are the local axes. A limb starts at its parent's end plus offset·R, applies
// rest then animated angles, each as rotZ(a[2]), rotX(a[0]), rotY(a[1]) about the local axes (X/Z: row_i' = c·r_i + s·r_j,
// row_j' = c·r_j - s·r_i; Y uses -sin, FUN_1208_2858); its end is start + rowY·length. A vertex is carried from the bind
// pose into the limb frame and out again in the animated frame.
import Foundation

public struct Limb: Sendable {
    public let name: String
    public let parent: Int
    public let rest: SIMD3<Int>, angle: SIMD3<Int>
    public let length: Int
    public let offset: SIMD3<Int>
}

public struct Skeleton: Sendable {
    public let limbs: [Limb]

    public init(data d: [UInt8]) throws {
        let p = try d.find("LIMB"), n = try d.u32be(p + 4)
        func v3(_ o: Int) throws -> SIMD3<Int> { SIMD3(try d.s16(o), try d.s16(o + 2), try d.s16(o + 4)) }
        limbs = try (0..<n / 39).map {
            let o = p + 8 + $0 * 39
            return Limb(name: d.cString(o, o + 9), parent: try d.s16(o + 9), rest: try v3(o + 11), angle: try v3(o + 17),
                        length: try d.s32(o + 23), offset: SIMD3(try d.s32(o + 27), try d.s32(o + 31), try d.s32(o + 35)))
        }
    }
}

/// Vertex -> limb index.
public struct Skin: Sendable {
    public let links: [Int]
    public init(data d: [UInt8]) throws {
        let p = try d.find("LINK"), n = try d.u32be(p + 4)
        links = try (0..<n / 2).map { try d.u16(p + 8 + 2 * $0) }
    }
}

public struct MotionFrame: Sendable {
    /// `rootAngle` holds frame row bytes 12..17 read as three s16: not rotations but the per-zone guard table (see `guardByte`).
    public let pos: SIMD3<Int>, rootAngle: SIMD3<Int>
    public let limbs: [SIMD3<Int>]

    /// Guard byte for hit zone 0..5 (TL TR ML MR BL BR): frame row byte 12 + zone (FUN_1088_0708 reads the current frame record + 0x0c
    /// + zone; the in-memory record starts with the root pos s32[3]). Only the low two bits are tested (& 3).
    public func guardByte(_ zone: Int) -> Int {
        let w = UInt16(bitPattern: Int16(truncatingIfNeeded: rootAngle[zone / 2]))
        return Int(zone % 2 == 0 ? w & 0xff : w >> 8)
    }
}

/// One used .COL record (FUN_1088_5fe6): a cube of half-size `half` (world units) centred on the end of `limb` (mode 0) or on its midpoint.
public struct ColVolume: Sendable, Equatable {
    public let limb: Int, mode: Int, half: Int

    /// <BODY>.COL: 10 records of u8 limb, u8 mode, s32 half-size; an all-zero half-size is unused. Mirrors salsa.load_col.
    public static func load(_ d: [UInt8]) throws -> [ColVolume] {
        try (0..<d.count / 6).compactMap { i in
            let half = try d.s32(6 * i + 2)
            return half == 0 ? nil : ColVolume(limb: try d.u8(6 * i), mode: try d.u8(6 * i + 1), half: half)
        }
    }
}

public struct Motion: Sendable {
    public let name: String
    public let frames: [MotionFrame]
    /// Header byte 76 (motion+0x52): times the figure's MY_SPEED, one frame's duration in 1/256 ticks of the 60 Hz clock
    /// (FUN_1098_0088, FUN_1088_1854).
    public let frameTime: Int
    /// Header byte 30 (motion+0x24): bit 0x01 marks a turning motion whose root yaw is added to the heading (FUN_10a0_1c83).
    public let flags: Int
    /// Header bytes 24, 25 and 31 (motion+0x1e, +0x1f, +0x25; FUN_1088_0708): strength, striking limb index and kind
    /// (1 strike, 2 guard, 3 movement, 0 other).
    public let strength: Int, strikeLimb: Int, kind: Int
    /// Header byte 30 bit 0x02 (+0x1e8 once the motion runs, 1098.c:274): a "rising" motion whose root z is committed to the figure at each
    /// wrap and at its end (MANTLE_*, ladders, iris entries).
    var rises: Bool { flags & 2 != 0 }
    /// The loop rule (FUN_1088_1854): the frame event list (count at byte 28, entries from byte 32) holds the 0xfe end marker; nil when
    /// the list is empty.
    public let loops: Bool?

    /// All motions of a .MTN file in file order (callers keep the first of duplicate names).
    public static func load(_ d: [UInt8]) throws -> [Motion] {
        guard let kids = try IFF.parse(d).first?.children else { throw FormatError("MTN is not an IFF FORM") }
        var out: [Motion] = []
        for k in stride(from: 0, to: kids.count - 1, by: 2) {
            let h = d.slice(kids[k].offset, kids[k].offset + kids[k].size), data = kids[k + 1]
            let nl = try h.u8(77), rb = try h.u16(79), nf = try h.u16(81)
            let ne = try h.u8(28), events = try (0..<ne).map { try h.u8(32 + $0) }
            let b = d.slice(data.offset, data.offset + data.size)
            func v3(_ o: Int, _ f: (Int) throws -> Int, _ step: Int) throws -> SIMD3<Int> { SIMD3(try f(o), try f(o + step), try f(o + 2 * step)) }
            var frames: [MotionFrame] = []
            if data.id == "POSE" {
                for f in 0..<nf {
                    let o = f * rb
                    frames.append(MotionFrame(pos: try v3(o, b.s32, 4), rootAngle: try v3(o + 12, b.s16, 2),
                                              limbs: try (0..<nl).map { try v3(o + 18 + 8 * $0, b.s16, 2) }))
                }
            } else {
                var vals: [Int] = [], q = 18 * nf
                while q < b.count {
                    let c = Int(b[q]); q += 1
                    if c >= 0x80 {
                        vals += [Int](repeating: try b.s8(q), count: c - 0x80); q += 1
                    } else {
                        vals += b.slice(q, q + c).map { Int(Int8(bitPattern: $0)) }; q += c
                    }
                }
                guard vals.count >= 3 * nl * nf else { throw FormatError("PRLE stream too short") }
                for f in 0..<nf {
                    frames.append(MotionFrame(pos: try v3(18 * f, b.s32, 4), rootAngle: try v3(18 * f + 12, b.s16, 2),
                                              limbs: (0..<nl).map { i in SIMD3((0..<3).map { vals[($0 * nl + i) * nf + f] }) }))
                }
            }
            out.append(Motion(name: h.cString(0, 16), frames: frames, frameTime: try h.u8(76), flags: try h.u8(30),
                              strength: try h.u8(24), strikeLimb: try h.u8(25), kind: try h.u8(31),
                              loops: ne == 0 ? nil : events.contains(0xfe)))
        }
        return out
    }
}

/// 3x3 rotation, rows are the local axes.
struct Mat3 {
    var r: [SIMD3<Double>]
    static let identity = Mat3(r: [SIMD3(1, 0, 0), SIMD3(0, 1, 0), SIMD3(0, 0, 1)])

    /// Rotate about local axis (0 = x, 1 = y, 2 = z) by `a` units.
    func rotated(_ a: Int, axis: Int) -> Mat3 {
        if a == 0 { return self }
        let (c, sine) = Self.cosSin(a), s = sine * (axis == 1 ? -1 : 1)
        let (i, j) = axis == 0 ? (1, 2) : axis == 1 ? (0, 2) : (0, 1)
        var m = self
        m.r[i] = c * r[i] + s * r[j]
        m.r[j] = c * r[j] - s * r[i]
        return m
    }

    func rotated(_ ang: SIMD3<Int>) -> Mat3 { rotated(ang[2], axis: 2).rotated(ang[0], axis: 0).rotated(ang[1], axis: 1) }

    /// cos and sin of `a` * 2π / 256: Apple libm's bits from JointAngleTable (the same on every platform), libm outside its range.
    static func cosSin(_ a: Int) -> (Double, Double) {
        let k = a - JointAngleTable.first
        if JointAngleTable.cosBits.indices.contains(k) {
            return (Double(bitPattern: JointAngleTable.cosBits[k]), Double(bitPattern: JointAngleTable.sinBits[k]))
        }
        let t = Double(a * 2) * Double.pi / 256
        return (cos(t), sin(t))
    }

    /// v · M (row vector times matrix). Accumulated with fused multiply-adds, like the prototype's numpy (BLAS) vector-matrix product,
    /// so posed vertices agree to the last bit.
    func apply(_ v: SIMD3<Double>) -> SIMD3<Double> {
        (r[0] * v.x).addingProduct(r[1], SIMD3(repeating: v.y)).addingProduct(r[2], SIMD3(repeating: v.z))
    }
    /// M · v (each row dotted with v).
    func inverseApply(_ v: SIMD3<Double>) -> SIMD3<Double> {
        SIMD3(r[0].x * v.x + r[0].y * v.y + r[0].z * v.z, r[1].x * v.x + r[1].y * v.y + r[1].z * v.z,
              r[2].x * v.x + r[2].y * v.y + r[2].z * v.z)
    }
}

extension Skeleton {
    /// Per-limb start position and rotation for a frame (nil = rest pose); root position is (0, 0, z) as the prototype poses.
    func solve(_ frame: MotionFrame?) -> (start: [SIMD3<Double>], rot: [Mat3]) {
        var start = [SIMD3<Double>](), rot = [Mat3](), end = [SIMD3<Double>](), rEnd = [Mat3]()
        let rootPos = frame.map { SIMD3<Double>(0, 0, Double($0.pos.z)) } ?? .zero
        let rootR = Mat3.identity        // the frame's rootAngle words are the guard table, not a rotation (NOTES: melee hits)
        for (i, l) in limbs.enumerated() {
            var (p, r) = l.parent < 0 ? (rootPos, rootR) : (end[l.parent], rEnd[l.parent])
            p += r.apply(SIMD3<Double>(l.offset))
            r = r.rotated(l.rest)
            if let f = frame, i < f.limbs.count { r = r.rotated(f.limbs[i]) }
            start.append(p); rot.append(r)
            end.append(p + r.r[1] * Double(l.length)); rEnd.append(r)
        }
        return (start, rot)
    }

    /// Bind-pose vertices carried by `links` into the pose of `frame` (model space, root x/y zeroed).
    func pose(_ verts: [SIMD3<Double>], links: [Int], frame: MotionFrame) -> [SIMD3<Double>] {
        let (s0, r0) = solve(nil), (s1, r1) = solve(frame)
        return zip(verts, links).map { v, l in s1[l] + r1[l].apply(r0[l].inverseApply(v - s0[l])) }
    }
}

// MARK: the engine's fixed-point FK (FUN_1038_035b via FUN_1040_0c7e) and its foot depth F (FUN_1040_0cf8), mirrors salsa.py

/// The engine's quarter-degree cosine bytes: BIOFORGE.EXE DGROUP (NE segment 83, file 0xfd800) + 0x8f74, 361 bytes (index 0 is never read).
func cosTable(exe: [UInt8]) throws -> [Int] {
    let o = 0xfd800 + 0x8f74
    guard exe.count >= o + 361 else { throw FormatError("BIOFORGE.EXE too short for the cosine table") }
    return exe[o..<o + 361].map { Int($0) }
}

private func s32(_ x: Int) -> Int { Int(Int32(truncatingIfNeeded: x)) }
/// FUN_1210_0c42: (a * b) >> 8 on the 64-bit product, kept to 32 bits.
private func mul8(_ a: Int, _ b: Int) -> Int { s32((a * b) >> 8) }

/// FUN_1200_0be3 then >> 6: an 8.8 degree angle as quarter degrees in 0..1439.
private func quarter(_ angle: Int) -> Int {
    var a = angle
    while a < -0xb400 { a += 0x16800 }
    while a > 0xb400 { a -= 0x16800 }
    let q = a >> 6
    return q < 0 ? q + 1440 : q
}

/// FUN_1210_0cca (via FUN_1200_05fd).
private func cos8(_ T: [Int], _ a: Int) -> Int {
    let q = quarter(a)
    func t(_ i: Int) -> Int { i == 0 ? 256 : T[i] }
    if q < 360 { return t(q) }
    let b = q - 720
    if b < 0 { return -t(-b) }
    if b < 360 { return -t(b) }
    return t(720 - b)
}

/// FUN_1210_0c71 (via FUN_1200_063c).
private func sin8(_ T: [Int], _ a: Int) -> Int {
    let q = quarter(a)
    func t(_ i: Int) -> Int { i == 0 ? 256 : T[i] }
    if q < 360 { return t(360 - q) }
    if q < 720 { return t(q - 360) }
    if q < 1080 { return -t(1080 - q) }
    return -t(q - 1080)
}

/// FUN_1208_2548 (X: rows 1, 2), 2b64 (Z: rows 0, 1), 2858 (Y: rows 0, 2, sign -1); each product >> 8 on its own.
func rot8(_ T: [Int], _ M: inout [[Int]], _ a: Int, _ i: Int, _ j: Int, _ sign: Int) {
    if abs(a) < 0x38 { return }
    let c = cos8(T, a), s = sin8(T, a), old = M[i]
    M[i] = (0..<3).map { mul8(M[i][$0], c) + sign * mul8(M[j][$0], s) }
    M[j] = (0..<3).map { mul8(M[j][$0], c) - sign * mul8(old[$0], s) }
}

/// FUN_1030_1054: each SALSA angle becomes whole degrees in 8.8 ((a * 45) >> 5 << 8), applied Z, X, Y.
private func rotate8(_ T: [Int], _ M: inout [[Int]], _ ang: SIMD3<Int>) {
    let deg = [ang[0], ang[1], ang[2]].map { (($0 * 45) >> 5) << 8 }
    rot8(T, &M, deg[2], 0, 1, 1)
    rot8(T, &M, deg[0], 1, 2, 1)
    rot8(T, &M, deg[1], 0, 2, -1)
}

extension Skeleton {
    /// Rest-pose limb END positions and 8.8 matrices (rows) as the engine builds them (salsa.solve_fixed).
    func solveFixed(_ T: [Int]) -> (pos: [[Int]], mat: [[[Int]]]) {
        var pos = [[Int]](), mat = [[[Int]]]()
        for l in limbs {
            var (P, M) = l.parent < 0 ? ([0, 0, 0], [[256, 0, 0], [0, 256, 0], [0, 0, 256]]) : (pos[l.parent], mat[l.parent])
            for k in 0..<3 { P = (0..<3).map { P[$0] + mul8(M[k][$0], l.offset[k]) } }
            rotate8(T, &M, l.rest)
            rotate8(T, &M, l.angle)
            let ln = mul8(l.length, 0x100 << 8) >> 8
            pos.append((0..<3).map { P[$0] + mul8(M[1][$0], ln) })
            mat.append(M)
        }
        return (pos, mat)
    }

    /// F (FUN_1040_0cf8, model+0x88): root z minus the lowest of every limb's z and that z plus the ROOT's row1 z scaled by the root length.
    func footDepth(_ T: [Int]) -> Int {
        let (pos, mat) = solveFixed(T)
        let rz = pos[0][2]
        let drop = mul8(mat[0][1][2], mul8(limbs[0].length, 0x100 << 8) >> 8)
        return rz - ([rz] + pos.map { min($0[2], $0[2] + drop) }).min()!
    }
}
