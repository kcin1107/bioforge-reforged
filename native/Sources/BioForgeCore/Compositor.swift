// Software rasterizer and depth-sorted ("painter") compositor, mirrors re/formats/render.py draw_poly,
// re/formats/compose.py and re/interp/world.py shade_mesh. Writes palette INDICES into a Framebuffer.
//
// Cels (FUN_1110_051f / 0d9c): every non-palette entry of the room .CAM is a sprite cel (frame 0, top-left at -hotspot)
// with the Flex entry depth (0 -> 99999); every polygon of every figure is its own cel at its average vertex depth
// (inference). Cels are drawn farthest first, ties: sprites before polygons, then entry/polygon order. No z-buffer.
// Triangles are split (0,1,2) (0,2,3) for quads; a triangle is skipped if any vertex is non-finite or at depth <= 0.
// Pixel (x, y) is covered when its centre (x+.5, y+.5) has barycentric weights w0, w1, w2 >= 0 (edges inclusive),
// scanned inside the bounding box [trunc(max(0, min)), trunc(min(W-1, max))] (truncation toward zero, like int()).
// Textured faces copy the source texel index at (trunc(u), trunc(v)) clamped to the texture, skipping index 255;
// animated textures show the frame of the drawing object's ANIMATE state (frame 0 without one). Untextured (flat and Gouraud) faces whose colour lies in a palette ramp
// draw at the ramp start: the original's global light keeps zero strength and ambient, so every intensity is 0 (see
// shade_mesh and NOTES "Face lighting"); other colours are kept. LINE faces are not drawn (as in the prototype).
import Foundation

/// A posed figure to draw: its mesh, world-space vertices and the current frame of each animated texture its ANIMATE state names (upper
/// case, 8 characters: cmdAnimate's key); a texture without state shows frame 0 (a record starts there with mode 0, 1168:055e).
public struct DrawFigure: Sendable {
    public let name: String
    public let mesh: EORMesh
    public let world: [SIMD3<Double>]
    public let anim: [String: Int]
    public init(name: String, mesh: EORMesh, world: [SIMD3<Double>], anim: [String: Int] = [:]) { self.name = name; self.mesh = mesh; self.world = world; self.anim = anim }
}

/// A MAKEFLATOBJECT sprite to draw this frame: its depth (camera depth) and the frame blitted with its hot spot at (x, y), i.e. the
/// top-left is (x - hotX, y - hotY) with x, y already moved by half the sequence's largest frame (WorldEffects.swift).
public struct FlatCel: Sendable {
    public let depth: Double, frame: CAMFrame, x: Int, y: Int
}

public enum Shading {
    /// Palette ramps (start, last offset) of DATA/PALETTE.IFF RANG; membership is inclusive (FUN_1150_1ef4).
    static let ramps = [(0x70, 9), (0x7a, 5), (0x80, 31), (0xa0, 31), (0xc0, 15), (0xd0, 15), (0xe0, 15), (0xf0, 14)]

    /// The pixels of each texture: a static one as is, an animated one at its ANIMATE state's frame (0 without state; same key as cmdAnimate).
    static func texturePixels(_ mesh: EORMesh, anim: [String: Int]) -> [[UInt8]] {
        mesh.textures.enumerated().map { i, t in
            mesh.frames[i].map { $0[min(max(anim[String(t.name.uppercased().prefix(8))] ?? 0, 0), $0.count - 1)] } ?? t.pixels
        }
    }

    static func isTextured(_ p: EORPoly, _ mesh: EORMesh) -> Bool { p.uv != nil && p.tex.map { $0 >= 0 && $0 < mesh.textures.count } == true }

    /// Palette index used to fill each polygon (textured faces keep their colour field, unused). Ramp colours become the
    /// ramp start: ramp_start + ((offset · I + 128) >> 8) with intensity I = 0 (FUN_1150_1eb2, FUN_1158_0ade).
    public static func colors(_ mesh: EORMesh) -> [Int] {
        mesh.polys.map { poly in
            if isTextured(poly, mesh) { return poly.color }
            return ramps.first(where: { $0.0 <= poly.color && poly.color <= $0.0 + $0.1 })?.0 ?? poly.color
        }
    }
}

public struct Compositor: Sendable {
    struct Sprite: Sendable { let depth: Int; let name: String; let frames: [CAMFrame] }
    private let sprites: [Sprite]
    public let palette: [UInt8]

    /// Decodes every frame of every image entry of the room.
    public init(room: CAMFile) throws {
        var depths: [String: Int] = [:]
        for e in room.flex.entries { if let d = e.depth { depths[e.name.uppercased()] = d } }
        sprites = try room.images.compactMap { e in
            let frames = try CAMImage.frames(room.flex.bytes(e))
            if frames.isEmpty { return nil }
            return Sprite(depth: depths[e.name.uppercased()] ?? 99999, name: e.name.uppercased(), frames: frames)
        }
        palette = room.palette
    }

    /// The frames of the room's image entry named `name` (upper case), or nil.
    func frames(named name: String) -> [CAMFrame]? { sprites.first { $0.name == name }?.frames }

    /// Upper-case names of the room's sprites (those whose frame the scripts select through `_<name>_frame`).
    public var spriteNames: [String] { sprites.map(\.name) }

    private struct Cel { let depth: Double; let kind: Int; let order: Int; let fig: Int; let poly: Int; var flat = false }

    /// Every cel of the picture, farthest first, with each figure's projected vertices, face colours and current texture pixels.
    private func layout(camera: Camera?, figures: [DrawFigure], flats: [FlatCel]) -> (cels: [Cel], screen: [[SIMD3<Double>]], colors: [[Int]], textures: [[[UInt8]]]) {
        var cels = sprites.enumerated().map { Cel(depth: Double($1.depth), kind: 0, order: $0, fig: 0, poly: $0) }
        for (k, f) in flats.enumerated() { cels.append(Cel(depth: f.depth, kind: 0, order: 1_000_000 + k, fig: 0, poly: k, flat: true)) }
        var screen: [[SIMD3<Double>]] = [], colors: [[Int]] = [], textures: [[[UInt8]]] = []
        for (fi, f) in figures.enumerated() {
            guard let camera else { break }
            let s = f.world.map { Scene.project($0, camera) }
            screen.append(s)
            colors.append(Shading.colors(f.mesh))
            textures.append(Shading.texturePixels(f.mesh, anim: f.anim))
            for (pi, p) in f.mesh.polys.enumerated() where p.vi.allSatisfy({ $0 < s.count }) {
                let z = p.vi.map { s[$0].z }
                if z.contains(where: { !$0.isFinite }) { continue }
                var sum = z[0]
                for v in z.dropFirst() { sum += v }
                cels.append(Cel(depth: sum / Double(z.count), kind: 1, order: fi * 100_000 + pi, fig: fi, poly: pi))
            }
        }
        cels.sort { ($1.depth, $0.kind, $0.order) < ($0.depth, $1.kind, $1.order) }
        return (cels, screen, colors, textures)
    }

    /// Without a camera only the room's sprites are drawn. `spriteFrames`: frame index per upper-case sprite name (default 0;
    /// like Python's list index, a too-large index clamps to the last frame and a negative one counts from the end).
    public func render(camera: Camera?, figures: [DrawFigure], spriteFrames: [String: Int] = [:], flats: [FlatCel] = [], into fb: inout Framebuffer) {
        let (cels, screen, colors, textures) = layout(camera: camera, figures: figures, flats: flats)
        fb.palette = palette
        fb.clear()
        for c in cels {
            if c.flat {
                let f = flats[c.poly]
                fb.blit(f.frame, x: f.x, y: f.y)
            } else if c.kind == 0 {
                let s = sprites[c.poly]
                fb.blit(s.frames[frameIndex(s, spriteFrames)])
            } else {
                let f = figures[c.fig]
                Self.draw(f.mesh.polys[c.poly], mesh: f.mesh, color: colors[c.fig][c.poly], textures: textures[c.fig], screen: screen[c.fig], into: &fb)
            }
        }
    }

    private func frameIndex(_ s: Sprite, _ spriteFrames: [String: Int]) -> Int {
        let k = Swift.min(spriteFrames[s.name] ?? 0, s.frames.count - 1)
        return k < 0 ? Swift.max(0, k + s.frames.count) : k               // a script frame below -count must not index out of range
    }

    /// The same picture as `render`, as cels for the 2x picture (HiResFrame.swift): same cels, same order, same triangle split and skipping.
    func hdCels(room: String, camera: Camera?, figures: [DrawFigure], spriteFrames: [String: Int], flats: [FlatCel]) -> [HDCel] {
        let (cels, screen, colors, textures) = layout(camera: camera, figures: figures, flats: flats)
        var out: [HDCel] = []
        out.reserveCapacity(cels.count)
        for c in cels {
            if c.flat {
                let f = flats[c.poly]
                out.append(.sprite(frame: f.frame, x: f.x - f.frame.hotX, y: f.y - f.frame.hotY, pack: nil))
            } else if c.kind == 0 {
                let s = sprites[c.poly], k = frameIndex(s, spriteFrames), f = s.frames[k]
                out.append(.sprite(frame: f, x: -f.hotX, y: -f.hotY, pack: "rooms/\(room)/\(s.name).\(k)"))
            } else {
                let f = figures[c.fig], poly = f.mesh.polys[c.poly], S = screen[c.fig]
                let textured = Shading.isTextured(poly, f.mesh)
                let tex = textured ? HDTexture(width: f.mesh.textures[poly.tex!].width, height: f.mesh.textures[poly.tex!].height, pixels: textures[c.fig][poly.tex!]) : nil
                for tri in poly.vi.count == 3 ? [[0, 1, 2]] : [[0, 1, 2], [0, 2, 3]] {
                    let P = tri.map { S[poly.vi[$0]] }
                    if P.contains(where: { !$0.x.isFinite || !$0.y.isFinite || !$0.z.isFinite || $0.z <= 0 }) { continue }
                    let uv = textured ? tri.map { SIMD2<Float>(Float(poly.uv![2 * $0]), Float(poly.uv![2 * $0 + 1])) } : []
                    out.append(.triangle(points: P.map { SIMD2<Float>(Float($0.x), Float($0.y)) }, uv: uv, texture: tex, color: UInt8(truncatingIfNeeded: colors[c.fig][c.poly])))
                }
            }
        }
        return out
    }

    @inline(__always) private static func clampInt(_ v: Double) -> Int { Int(Swift.max(-1e9, Swift.min(1e9, v))) }

    static func draw(_ poly: EORPoly, mesh: EORMesh, color: Int, textures: [[UInt8]], screen S: [SIMD3<Double>], into fb: inout Framebuffer) {
        let (W, H) = (Framebuffer.width, Framebuffer.height)
        let textured = Shading.isTextured(poly, mesh)
        for tri in poly.vi.count == 3 ? [[0, 1, 2]] : [[0, 1, 2], [0, 2, 3]] {
            let P = tri.map { S[poly.vi[$0]] }
            if P.contains(where: { !$0.x.isFinite || !$0.y.isFinite || !$0.z.isFinite || $0.z <= 0 }) { continue }
            let (xs, ys) = (P.map(\.x), P.map(\.y))
            let x0 = clampInt(Swift.max(0, xs.min()!)), x1 = clampInt(Swift.min(Double(W - 1), xs.max()!))
            let y0 = clampInt(Swift.max(0, ys.min()!)), y1 = clampInt(Swift.min(Double(H - 1), ys.max()!))
            if x1 < x0 || y1 < y0 { continue }
            let den = (ys[1] - ys[2]) * (xs[0] - xs[2]) + (xs[2] - xs[1]) * (ys[0] - ys[2])
            if abs(den) < 1e-9 { continue }
            let tex = textured ? mesh.textures[poly.tex!] : nil
            let uv = textured ? tri.map { (Double(poly.uv![2 * $0]), Double(poly.uv![2 * $0 + 1])) } : []
            for y in y0...y1 {
                let gy = Double(y) + 0.5
                for x in x0...x1 {
                    let gx = Double(x) + 0.5
                    let w0 = ((ys[1] - ys[2]) * (gx - xs[2]) + (xs[2] - xs[1]) * (gy - ys[2])) / den
                    let w1 = ((ys[2] - ys[0]) * (gx - xs[2]) + (xs[0] - xs[2]) * (gy - ys[2])) / den
                    let w2 = 1 - w0 - w1
                    if !(w0 >= 0 && w1 >= 0 && w2 >= 0) { continue }
                    var idx = UInt8(truncatingIfNeeded: color)
                    if let t = tex {
                        let u = Swift.min(Swift.max(Int(w0 * uv[0].0 + w1 * uv[1].0 + w2 * uv[2].0), 0), t.width - 1)
                        let v = Swift.min(Swift.max(Int(w0 * uv[0].1 + w1 * uv[1].1 + w2 * uv[2].1), 0), t.height - 1)
                        idx = textures[poly.tex!][v * t.width + u]
                        if idx == 0xff { continue }
                    }
                    fb.pixels[y * W + x] = idx
                }
            }
        }
    }
}
