// SALSA figure mesh (.EOR, IFF FORM REAL), mirrors re/formats/eor.py.
//
// FORM REAL / FORM APPR / FORM POLY (chunks are found by their IFF path, e.g. /REAL/APPR/POLY/TRIS/FACE):
//   VERT  n * (s32 x, y, z)             bind-pose model space, +Z up
//   DETA/LVL0 u16[]                     face order / LOD list;  ATTR n * 9 bytes (unknown, kept raw)
//   TRIS|QUAD FACE n * (u8 kind, u8 color, u16 v[3|4])      kind 6 textured, 5/1 flat (color = palette index)
//             MAPS m * (u16 face, u16 tex, (u16 u, u16 v) * 3|4)   textured faces only (face index within its group)
//   LINE  FACE n * (u8 kind, u8 color, u16 v0, u16 v1)
//   TXMS  TXMP name[8], u16 w, u16 h, u8 pixels[w*h]         static textures, in file order
//         TXMA name[8], u16 w, u16 h, u16 nframes, pixels[nframes][w*h]   animated textures: they take the texture
//               indices after all static ones (in file order); `textures` holds their frame 0, `frames[tex]` all frames
// Polygons are TRIS first, then QUAD. All payload integers are little-endian, chunk sizes big-endian.
// Old layout (ITEMS/BLASTER.IFF, PIPE.IFF; one-byte indices): TRIS/VTRI n * (u8 kind, u8 v0, u8 v1, u8 v2, u8 colour, 0, 0xff, flag),
//   TRIS/UVXY m * (u8 face, u8 tex, 3 * (u8 u, u8 v)), and the TXMS chunk nested inside TRIS.
import Foundation

public struct EORPoly: Sendable {
    public let kind: Int, color: Int
    public let vi: [Int]
    /// Texture index and flat (u, v) pairs; nil for untextured faces.
    public let tex: Int?
    public let uv: [Int]?
}

public struct EORTexture: Sendable {
    public let name: String
    public let width: Int, height: Int
    public let pixels: [UInt8]
}

public struct EORMesh: Sendable {
    public let verts: [SIMD3<Double>]
    public let polys: [EORPoly]
    /// (kind, color, v0, v1)
    public let lines: [[Int]]
    public let textures: [EORTexture]
    /// Animated textures: texture index -> frames' pixels.
    public let frames: [Int: [[UInt8]]]
    public let lvl0: [Int]
    public let attr: [UInt8]

    /// `m` with its faces replaced by `polys` (vertex indices into `verts`): a piece of shrapnel keeps the figure's textures and colours.
    public init(piecesOf m: EORMesh, polys: [EORPoly], verts: [SIMD3<Double>]) {
        self.verts = verts; self.polys = polys
        lines = m.lines; textures = m.textures; frames = m.frames; lvl0 = m.lvl0; attr = m.attr
    }

    public init(data d: [UInt8]) throws {
        // Chunk payloads keyed by IFF path, in order of first appearance (a Python dict of lists).
        var order: [String] = [], chunks: [String: [(Int, Int)]] = [:]
        func walk(_ nodes: [IFFNode], _ prefix: String) {
            for n in nodes {
                let key = prefix + "/" + (n.type ?? n.id).trimmingCharacters(in: .whitespaces)
                if let kids = n.children { walk(kids, key) } else {
                    if chunks[key] == nil { order.append(key) }
                    chunks[key, default: []].append((n.offset, n.size))
                }
            }
        }
        walk(try IFF.parse(d), "")
        func first(_ suffix: String) -> (Int, Int)? { order.first { $0.hasSuffix(suffix) }.flatMap { chunks[$0]?.first } }
        guard let (vp, vs) = first("/VERT") else { throw FormatError("EOR without VERT") }
        verts = try (0..<vs / 12).map { SIMD3(Double(try d.s32(vp + 12 * $0)), Double(try d.s32(vp + 12 * $0 + 4)), Double(try d.s32(vp + 12 * $0 + 8))) }

        var polys: [EORPoly] = []
        let old = chunks["/REAL/APPR/POLY/TRIS/VTRI"] != nil
        if old {
            var maps: [Int: (Int, [Int])] = [:]
            for (p, s) in chunks["/REAL/APPR/POLY/TRIS/UVXY"] ?? [] {
                for i in 0..<s / 8 {
                    let o = p + 8 * i
                    maps[try d.u8(o)] = (try d.u8(o + 1), try (0..<6).map { try d.u8(o + 2 + $0) })
                }
            }
            var n = 0
            for (p, s) in chunks["/REAL/APPR/POLY/TRIS/VTRI"] ?? [] {
                for i in 0..<s / 8 {
                    let o = p + 8 * i, m = maps[n]
                    polys.append(EORPoly(kind: try d.u8(o), color: try d.u8(o + 4), vi: try (1...3).map { try d.u8(o + $0) },
                                         tex: m?.0, uv: m?.1))
                    n += 1
                }
            }
        }
        for (group, nv) in [("TRIS", 3), ("QUAD", 4)] {
            let fsz = 2 + 2 * nv, msz = 4 + 4 * nv, base = "/REAL/APPR/POLY/\(group)"
            var maps: [Int: (Int, [Int])] = [:]
            for (p, s) in chunks[base + "/MAPS"] ?? [] {
                for i in 0..<s / msz {
                    let o = p + msz * i
                    maps[try d.u16(o)] = (try d.u16(o + 2), try (0..<2 * nv).map { try d.u16(o + 4 + 2 * $0) })
                }
            }
            var n = 0
            for (p, s) in chunks[base + "/FACE"] ?? [] {
                for i in 0..<s / fsz {
                    let o = p + fsz * i, m = maps[n]
                    polys.append(EORPoly(kind: try d.u8(o), color: try d.u8(o + 1), vi: try (0..<nv).map { try d.u16(o + 2 + 2 * $0) },
                                         tex: m?.0, uv: m?.1))
                    n += 1
                }
            }
        }
        self.polys = polys
        var lines: [[Int]] = []
        for (p, s) in chunks["/REAL/APPR/POLY/LINE/FACE"] ?? [] {
            for i in 0..<s / 6 {
                let o = p + 6 * i
                lines.append([try d.u8(o), try d.u8(o + 1), try d.u16(o + 2), try d.u16(o + 4)])
            }
        }
        self.lines = lines
        func name(_ p: Int) -> String { d.cString(p, p + 8) }
        let txms = old ? "/REAL/APPR/POLY/TRIS/TXMS" : "/REAL/APPR/POLY/TXMS"
        var textures: [EORTexture] = []
        for (p, _) in chunks[txms + "/TXMP"] ?? [] {
            let w = try d.u16(p + 8), h = try d.u16(p + 10)
            textures.append(EORTexture(name: name(p), width: w, height: h, pixels: d.slice(p + 12, p + 12 + w * h)))
        }
        var anim: [Int: [[UInt8]]] = [:]
        for (p, _) in chunks[txms + "/TXMA"] ?? [] {
            let w = try d.u16(p + 8), h = try d.u16(p + 10), n = try d.u16(p + 12)
            let fr = (0..<n).map { d.slice(p + 14 + $0 * w * h, p + 14 + ($0 + 1) * w * h) }
            guard let f0 = fr.first else { throw FormatError("TXMA without frames") }
            anim[textures.count] = fr
            textures.append(EORTexture(name: name(p), width: w, height: h, pixels: f0))
        }
        self.textures = textures
        frames = anim
        lvl0 = try first("/DETA/LVL0").map { (p, s) in try (0..<s / 2).map { try d.u16(p + 2 * $0) } } ?? []
        attr = first("/ATTR").map { d.slice($0.0, $0.0 + $0.1) } ?? []
    }
}
