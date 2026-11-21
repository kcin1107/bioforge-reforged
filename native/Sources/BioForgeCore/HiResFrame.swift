// View > High-Resolution Art: the picture painted again at 2x (640x400) or 4x (1280x800) from the same cels as the 320x200 one
// (Compositor.hdCels), with room pieces and figure textures from the art pack of that scale (PixelPack.swift) where it has them and plain
// enlarged where it does not. It stays
// palette indices, so the app shows it through the same palette as the 320x200 picture and gamma, CHANGEPALETTE and FADE apply unchanged.
// Presentation only: it reads the World and never changes it; the indexed renderer and its oracles are untouched.
import Foundation

/// A MESH texture for one frame of animation. `pixels` are palette indices; 255 is transparent, as in the indexed renderer.
public struct HDTexture: Sendable {
    public let width: Int, height: Int, pixels: [UInt8]
}

public enum HDCel: Sendable {
    /// `pack`: path inside the art pack without extension ("rooms/CE11/CE11.0"), nil if the frame has no 2x version (MAKEFLATOBJECT
    /// sprites). `x`, `y`: top-left in 320x200 coordinates.
    case sprite(frame: CAMFrame, x: Int, y: Int, pack: String?)
    /// One triangle in 320x200 coordinates; `uv` in texels (the original's affine mapping). `color` is the palette index of an untextured face.
    case triangle(points: [SIMD2<Float>], uv: [SIMD2<Float>], texture: HDTexture?, color: UInt8)
}

public enum HDArt {
    /// FNV-1a of a texture's indices, its name in the pack: 41 of the 623 texture names are reused with different art.
    public static func key(_ pixels: [UInt8]) -> UInt32 {
        var h: UInt32 = 0x811c9dc5
        for b in pixels { h = (h ^ UInt32(b)) &* 0x01000193 }
        return h
    }
}

/// An art pack at `scale` (2 or 4): rooms/<CAM>/<ENTRY>.<frame>.frm and tex/<key>.frm, each 'BFX3' ('BFX2', blocky outlines, is read too), u16 width, height (little-endian), then
/// raw DEFLATE of the indices followed by the mask (1 = opaque). Files are decoded once; a missing or unreadable one means "enlarge the
/// original".
public final class HiResPack: @unchecked Sendable {
    public let root: URL, scale: Int
    private var cache: [String: CAMFrame?] = [:]
    private let lock = NSLock()

    public init(root: URL, scale: Int) { self.root = root; self.scale = scale }

    public static func decode(_ data: Data) -> CAMFrame? {
        guard data.count > 8, (data.prefix(4) == Data("BFX3".utf8) || data.prefix(4) == Data("BFX2".utf8)) else { return nil }
        let b = [UInt8](data.prefix(8))
        let w = Int(b[4]) | Int(b[5]) << 8, h = Int(b[6]) | Int(b[7]) << 8
        #if canImport(Darwin)
        guard let raw = try? (data.dropFirst(8) as NSData).decompressed(using: .zlib) as Data, raw.count == 2 * w * h else { return nil }
        let a = [UInt8](raw)
        return CAMFrame(width: w, height: h, hotX: 0, hotY: 0, pixels: Array(a[..<(w * h)]), mask: Array(a[(w * h)...]))
        #else
        return nil
        #endif
    }

    func frame(_ path: String) -> CAMFrame? {
        lock.lock(); defer { lock.unlock() }
        if let f = cache[path] { return f }
        let f = (try? Data(contentsOf: root.appendingPathComponent(path + ".frm"))).flatMap(Self.decode)
        cache[path] = f
        return f
    }

    /// Drops what was cached for `room` and every missing texture, so art built since shows up without a restart.
    public func forget(room: String) {
        lock.lock(); defer { lock.unlock() }
        let prefix = "rooms/\(room.uppercased())/"
        cache = cache.filter { !$0.key.hasPrefix(prefix) && !($0.key.hasPrefix("tex/") && $0.value == nil) }
    }

    /// Drops what was cached for a monitor (MONITORS/<name>.CAM; POINTER included), so art built since shows up without a restart.
    public func forget(monitor: String) {
        lock.lock(); defer { lock.unlock() }
        let prefix = "monitors/\(monitor.uppercased())/"
        cache = cache.filter { !$0.key.hasPrefix(prefix) }
    }
}

public enum HDText {
    /// The ink of a glyph (`rows`: palette indices, 0 = none) at `scale`: "blocky", every ink pixel becomes a scale x scale block, so the
    /// layout is the original's times `scale`. The one place that decides a glyph's shape at a larger size; a smoothing scaler would replace it.
    /// `mask` is width x height, true where the ink goes.
    static func scaledGlyph(_ rows: [[UInt8]], _ scale: Int) -> (width: Int, height: Int, mask: [Bool]) {
        let w = (rows.map(\.count).max() ?? 0) * scale, h = rows.count * scale
        var mask = [Bool](repeating: false, count: w * h)
        for (r, row) in rows.enumerated() {
            for (c, v) in row.enumerated() where v != 0 {
                for dy in 0..<scale { for dx in 0..<scale { mask[(r * scale + dy) * w + c * scale + dx] = true } }
            }
        }
        return (w, h, mask)
    }
}

public struct HiResFrame: Sendable, Equatable {
    public let scale: Int
    public var pixels: [UInt8]
    public var width: Int { Framebuffer.width * scale }
    public var height: Int { Framebuffer.height * scale }

    init(pixels: [UInt8], scale: Int) { self.pixels = pixels; self.scale = scale }

    /// Black (index 0), for a picture painted from nothing (monitors).
    init(scale: Int) { self.init(pixels: [UInt8](repeating: 0, count: Framebuffer.width * scale * Framebuffer.height * scale), scale: scale) }

    /// The 320x200 picture with every pixel enlarged to `scale` x `scale`.
    init(enlarging fb: Framebuffer, scale k: Int) {
        var p = [UInt8](); p.reserveCapacity(Framebuffer.width * Framebuffer.height * k * k)
        for y in 0..<(Framebuffer.height * k) { for x in 0..<(Framebuffer.width * k) { p.append(fb.pixels[y / k * Framebuffer.width + x / k]) } }
        self.init(pixels: p, scale: k)
    }

    /// Paints `cels` in order at the pack's scale: room pieces and textures from `pack` when it has them, otherwise the original pixels
    /// enlarged.
    public init(cels: [HDCel], pack: HiResPack) {
        let s = pack.scale
        scale = s
        pixels = [UInt8](repeating: 0, count: Framebuffer.width * s * Framebuffer.height * s)
        var textures: [UnsafeRawPointer: HDTexture?] = [:]                // this frame's textures by storage (the cels keep it alive), looked up once
        for cel in cels {
            switch cel {
            case .sprite(let f, let x, let y, let path):
                place(f, x: x, y: y, path: path, pack: pack)
            case .triangle(let p, let uv, let tex, let color):
                var t = tex, k: Float = 1
                if let tex {
                    let id = tex.pixels.withUnsafeBytes { $0.baseAddress! }
                    let big: HDTexture?
                    if let known = textures[id] { big = known } else {
                        big = pack.frame(String(format: "tex/%08x", HDArt.key(tex.pixels))).flatMap {
                            $0.width == s * tex.width && $0.height == s * tex.height ? HDTexture(width: $0.width, height: $0.height, pixels: $0.pixels) : nil }
                        textures.updateValue(big, forKey: id)
                    }
                    if let big { t = big; k = Float(s) }
                }
                fill(p.map { $0 * Float(s) }, uv: uv.map { $0 * k }, texture: t, color: color)
            }
        }
    }

    /// The 320x200 frame `f` with its top-left at (x, y) in 320x200 coordinates: the pack's `path` where it has one of s x its size, else the
    /// frame enlarged. `columns`: draw only this many leftmost columns (at this scale), for the clipped scale bars.
    mutating func place(_ f: CAMFrame, x: Int, y: Int, path: String?, pack: HiResPack, columns: Int = .max, translucent: Bool = false) {
        let s = scale
        if let path, let big = pack.frame(path), big.width == s * f.width, big.height == s * f.height {
            blit(big, x: s * x, y: s * y, scale: 1, columns: columns, translucent: translucent)
        } else { blit(f, x: s * x, y: s * y, scale: s, columns: columns, translucent: translucent) }
    }

    /// Opaque pixels of `f` with its top-left at (x, y), each drawn `scale` x `scale`; clipped.
    private mutating func blit(_ f: CAMFrame, x: Int, y: Int, scale: Int, columns: Int = .max, translucent: Bool = false) {
        let W = width, H = height
        let X0 = Swift.max(0, x), X1 = Swift.min(W, x + Swift.min(f.width * scale, columns)), Y0 = Swift.max(0, y), Y1 = Swift.min(H, y + f.height * scale)
        if X1 <= X0 || Y1 <= Y0 { return }
        for Y in Y0..<Y1 {
            let row = (Y - y) / scale * f.width
            for X in X0..<X1 {
                let i = row + (X - x) / scale
                if f.mask[i] == 0 { continue }
                if translucent {                                 // FUN_1270_185b over the pixel already here (Framebuffer.translucent)
                    if f.pixels[i] != 0xff { pixels[Y * W + X] = Framebuffer.translucent(f.pixels[i], over: pixels[Y * W + X]) }
                } else { pixels[Y * W + X] = f.pixels[i] }
            }
        }
    }

    /// Compositor.draw's rules at this size: pixel centres with barycentric weights >= 0, the bounding box truncated, texel (trunc u, trunc v)
    /// clamped, index 255 skipped.
    private mutating func fill(_ P: [SIMD2<Float>], uv: [SIMD2<Float>], texture: HDTexture?, color: UInt8) {
        let W = width, H = height
        let xs = P.map { Double($0.x) }, ys = P.map { Double($0.y) }
        func trunc(_ v: Double) -> Int { Int(Swift.max(-1e9, Swift.min(1e9, v))) }
        let x0 = trunc(Swift.max(0, xs.min()!)), x1 = trunc(Swift.min(Double(W - 1), xs.max()!))
        let y0 = trunc(Swift.max(0, ys.min()!)), y1 = trunc(Swift.min(Double(H - 1), ys.max()!))
        if x1 < x0 || y1 < y0 { return }
        let den = (ys[1] - ys[2]) * (xs[0] - xs[2]) + (xs[2] - xs[1]) * (ys[0] - ys[2])
        if abs(den) < 1e-9 { return }
        let u = uv.map { Double($0.x) }, v = uv.map { Double($0.y) }
        for y in y0...y1 {
            let gy = Double(y) + 0.5
            for x in x0...x1 {
                let gx = Double(x) + 0.5
                let w0 = ((ys[1] - ys[2]) * (gx - xs[2]) + (xs[2] - xs[1]) * (gy - ys[2])) / den
                let w1 = ((ys[2] - ys[0]) * (gx - xs[2]) + (xs[0] - xs[2]) * (gy - ys[2])) / den
                let w2 = 1 - w0 - w1
                if !(w0 >= 0 && w1 >= 0 && w2 >= 0) { continue }
                var idx = color
                if let t = texture {
                    let tu = Swift.min(Swift.max(Int(w0 * u[0] + w1 * u[1] + w2 * u[2]), 0), t.width - 1)
                    let tv = Swift.min(Swift.max(Int(w0 * v[0] + w1 * v[1] + w2 * v[2]), 0), t.height - 1)
                    idx = t.pixels[tv * t.width + tu]
                    if idx == 0xff { continue }
                }
                pixels[y * W + x] = idx
            }
        }
    }

    /// A glyph's ink (rows of palette indices, 0 = none) painted at `colour`, its top-left at (left, top) in 320x200 coordinates, clipped. The
    /// glyph's shape at this scale comes from `HDText.scaledGlyph`.
    mutating func drawGlyph(_ rows: [[UInt8]], left: Int, top: Int, colour: UInt8) {
        let g = HDText.scaledGlyph(rows, scale)
        let W = width, H = height
        for y in 0..<g.height {
            let Y = scale * top + y
            guard Y >= 0 && Y < H else { continue }
            for x in 0..<g.width where g.mask[y * g.width + x] {
                let X = scale * left + x
                if X >= 0 && X < W { pixels[Y * W + X] = colour }
            }
        }
    }

    /// RUMBLE at this scale: Presentation.shiftFrame on the 320x200 rows, every row and offset enlarged, so an enlarged picture shifts exactly
    /// as the original does.
    mutating func shift(x: Int, y: Int, xp: Int, fill: UInt8) {
        let W = width, h = Framebuffer.height, k = scale
        let a = pixels
        if y > 0 { for i in 0..<(k * Swift.min(y, h) * W) { pixels[i] = fill } }
        else if y < 0 { for i in (k * Swift.max(h + y, 0) * W)..<(k * h * W) { pixels[i] = fill } }
        let first = y >= 0 ? (h - 1 - y) % 2 : (-y) % 2
        for d in 0..<h {
            let s = d - y
            if s < 0 || s >= h { continue }
            let dx = k * (s % 2 == first ? x : xp)
            for r in 0..<k {
                let D = (k * d + r) * W, S = (k * s + r) * W
                if dx >= 0 && dx < W { for c in dx..<W { pixels[D + c] = a[S + c - dx] } }
                else if dx < 0 && -dx < W { for c in 0..<(W + dx) { pixels[D + c] = a[S + c - dx] } }
            }
        }
    }
}

extension World {
    /// The current picture at the pack's scale, or nil when it has no room to paint (a flic without a caption): the app then shows the 320x200
    /// picture, which on the same pixel grid looks the same. `indexed`: this frame's renderPresentation output, before applyPresentation.
    /// The options dialog and monitors come from the pack's monitors/ folder; a flic with a caption is the flic enlarged under the caption at
    /// this scale.
    public func hiResFrame(indexed: Framebuffer, pack: HiResPack) -> HiResFrame? {
        if creditsRolling { return nil }                                    // the roll is drawn into the 320x200 picture, which the app then shows
        if let o = options, !o.closed {                                    // the dialog covers a running monitor, as in renderPresentation
            let under = optionsUnderlay()
            var hi = HiResFrame(scale: pack.scale)
            o.render(into: &hi, pack: pack, underlay: under, underlayHi: optionsUnderlayHiRes(pack: pack, palette: under.palette))
            return hi
        }
        if let monitor { var hi = HiResFrame(scale: pack.scale); monitor.render(into: &hi, pack: pack); return hi }
        if show.flic == nil, let (_, path, frame) = shownPictureArt() {   // the CAMERA SHOW picture, as in renderPresentation
            var hi = HiResFrame(scale: pack.scale); hi.place(frame, x: -frame.hotX, y: -frame.hotY, path: path, pack: pack)
            if let event = captionEvent { SubtitleRenderer.render(event, font: resources.captionFont, palette: indexed.palette, readable: readableText, into: &hi) }
            return hi
        }
        if let f = show.flic {
            guard let event = captionEvent else { return nil }
            var bare = Framebuffer()
            renderFlic(f, into: &bare)
            var hi = HiResFrame(enlarging: bare, scale: pack.scale)
            SubtitleRenderer.render(event, font: resources.captionFont, palette: indexed.palette, readable: readableText, into: &hi)
            return hi
        }
        return roomHiRes(pack: pack, palette: indexed.palette)
    }

    /// The room with its caption at the pack's scale, or nil without a room to paint.
    private func roomHiRes(pack: HiResPack, palette: [UInt8]) -> HiResFrame? {
        guard let cam = currentCamera?.uppercased(), let (compositor, camera, input) = drawInput(camera: cam) else { return nil }
        let cels = compositor.hdCels(room: cam, camera: camera, figures: input.figures, spriteFrames: input.frames, flats: flatCels(camera))
        var hi = HiResFrame(cels: cels, pack: pack)
        if let event = captionEvent { SubtitleRenderer.render(event, font: resources.captionFont, palette: palette, readable: readableText, into: &hi) }
        return hi
    }

    /// optionsUnderlay at the pack's scale (before dimming): the CAMERA SHOW picture, a running monitor or the room from the pack, so the
    /// scene behind the dialog keeps its 2x/4x art. `palette`: the 1x underlay's, which the caption shadow is matched against.
    func optionsUnderlayHiRes(pack: HiResPack, palette: [UInt8]) -> HiResFrame? {
        if let (_, path, frame) = shownPictureArt() {
            var hi = HiResFrame(scale: pack.scale); hi.place(frame, x: -frame.hotX, y: -frame.hotY, path: path, pack: pack); return hi
        }
        if let monitor { var hi = HiResFrame(scale: pack.scale); monitor.render(into: &hi, pack: pack); return hi }
        return roomHiRes(pack: pack, palette: palette)
    }
}
