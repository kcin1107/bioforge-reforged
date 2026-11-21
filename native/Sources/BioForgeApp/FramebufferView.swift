// MTKView that presents a 320x200 indexed framebuffer: indices as an r8Uint texture, palette as a 256-entry buffer,
// filling the window with its shape kept (letterboxed on one axis), crisp edges at any scale. Optional 4:3 correction (pixel aspect 1.2,
// as on the original CRT). View > High-Resolution Art swaps in a 2x or 4x picture of the same indices (HiResFrame), drawn the same way.
import AppKit
import BioForgeCore
import BioForgeHost
import MetalKit

@MainActor
final class FramebufferView: MTKView, MTKViewDelegate {
    private var queue: MTLCommandQueue!
    private var pipeline: MTLRenderPipelineState!
    private var texture: MTLTexture!, hiResTextures: [Int: MTLTexture] = [:]
    private var shownScale = 1
    private var shown: (pixels: [UInt8], width: Int, height: Int, palette: [UInt8])?     // the last presented picture, for Save Frame as PNG
    private var paletteBuffer: MTLBuffer!

    var correctAspect = true { didSet { needsDisplay = true } }
    /// View > High-Resolution Art: 0 (off), 2 or 4.
    var artScale = 0 { didSet { needsDisplay = true } }
    /// Receives keyDown / keyUp / flagsChanged while set (the running game); otherwise keys fall through to the menus.
    var onKey: ((NSEvent) -> Void)?
    var onPointer: ((Int?, Int?, PointerPhase) -> Void)?
    private var pointerTracking: NSTrackingArea?

    init() {
        let device = MTLCreateSystemDefaultDevice()!
        super.init(frame: NSRect(x: 0, y: 0, width: 960, height: 720), device: device)
        queue = device.makeCommandQueue()
        let lib = try! device.makeLibrary(source: shaderSource, options: nil)
        let d = MTLRenderPipelineDescriptor()
        d.vertexFunction = lib.makeFunction(name: "vs")
        d.fragmentFunction = lib.makeFunction(name: "fs")
        d.colorAttachments[0].pixelFormat = colorPixelFormat
        pipeline = try! device.makeRenderPipelineState(descriptor: d)
        let td = MTLTextureDescriptor.texture2DDescriptor(pixelFormat: .r8Uint, width: Framebuffer.width,
                                                          height: Framebuffer.height, mipmapped: false)
        texture = device.makeTexture(descriptor: td)
        for k in [2, 4] {
            td.width = Framebuffer.width * k; td.height = Framebuffer.height * k
            hiResTextures[k] = device.makeTexture(descriptor: td)
        }
        paletteBuffer = device.makeBuffer(length: 256 * 16, options: .storageModeShared)
        clearColor = MTLClearColor(red: 0, green: 0, blue: 0, alpha: 1)
        enableSetNeedsDisplay = true
        isPaused = true
        delegate = self
    }

    required init(coder: NSCoder) { fatalError() }

    override var acceptsFirstResponder: Bool { true }
    override func keyDown(with event: NSEvent) { if let onKey { onKey(event) } else { super.keyDown(with: event) } }
    override func keyUp(with event: NSEvent) { if let onKey { onKey(event) } else { super.keyUp(with: event) } }
    override func flagsChanged(with event: NSEvent) { if let onKey { onKey(event) } else { super.flagsChanged(with: event) } }

    override func updateTrackingAreas() {
        if let pointerTracking { removeTrackingArea(pointerTracking) }
        pointerTracking = NSTrackingArea(rect: .zero, options: [.mouseMoved, .activeInKeyWindow, .inVisibleRect], owner: self)
        addTrackingArea(pointerTracking!)
        super.updateTrackingAreas()
    }

    /// Map a window point through the exact scaled, letterboxed image rectangle used by draw(in:).
    private func gamePoint(_ event: NSEvent) -> (Int, Int)? { gamePoint(window: event.locationInWindow) }

    /// The same for a point in window coordinates (nil outside the picture).
    func gamePoint(window location: NSPoint) -> (Int, Int)? {
        let point = convert(location, from: nil)
        guard bounds.width > 0, bounds.height > 0 else { return nil }
        let dw = Double(drawableSize.width), dh = Double(drawableSize.height)
        let aspectY = correctAspect ? 1.2 : 1.0
        let scale = pictureScale(dw, dh, aspectY)
        guard scale > 0 else { return nil }
        let w = Double(Framebuffer.width) * scale, h = Double(Framebuffer.height) * aspectY * scale
        let x = Double(point.x) * dw / Double(bounds.width) - (dw - w) / 2
        let y = Double(point.y) * dh / Double(bounds.height) - (dh - h) / 2
        guard x >= 0, x < w, y >= 0, y < h else { return nil }
        return (Int(x / scale), max(0, min(199, Int(Double(Framebuffer.height) - y / (scale * aspectY)))))
    }

    /// The inverse of gamePoint: the window point at the middle of 320x200 pixel (x, y), or nil before the view has a size.
    func windowPoint(game x: Int, _ y: Int) -> NSPoint? {
        guard bounds.width > 0, bounds.height > 0 else { return nil }
        let dw = Double(drawableSize.width), dh = Double(drawableSize.height)
        let aspectY = correctAspect ? 1.2 : 1.0
        let scale = pictureScale(dw, dh, aspectY)
        guard scale > 0 else { return nil }
        let w = Double(Framebuffer.width) * scale, h = Double(Framebuffer.height) * aspectY * scale
        let px = (Double(x) + 0.5) * scale + (dw - w) / 2
        let py = (Double(Framebuffer.height) - Double(y) - 0.5) * scale * aspectY + (dh - h) / 2
        return convert(NSPoint(x: px * Double(bounds.width) / dw, y: py * Double(bounds.height) / dh), to: nil)
    }

    /// The art scale the window has room for: `artScale`, or 2 when the window is too small for 4x pixels, or 0.
    var fittingArtScale: Int {
        let scale = fitScale(Double(drawableSize.width), Double(drawableSize.height), correctAspect ? 1.2 : 1.0)
        return [4, 2].first { $0 <= artScale && scale >= Double($0) } ?? 0
    }

    private func fitScale(_ dw: Double, _ dh: Double, _ aspectY: Double) -> Double {
        min(dw / Double(Framebuffer.width), dh / (Double(Framebuffer.height) * aspectY))
    }

    /// The picture fills the window, keeping its shape; the shader keeps the pixels crisp at any scale.
    private func pictureScale(_ dw: Double, _ dh: Double, _ aspectY: Double) -> Double { fitScale(dw, dh, aspectY) }

    private func pointer(_ event: NSEvent, phase: PointerPhase) {
        let point = gamePoint(event)
        onPointer?(point?.0, point?.1, phase)
    }

    override func mouseMoved(with event: NSEvent) { pointer(event, phase: .move) }
    override func mouseDragged(with event: NSEvent) { pointer(event, phase: .move) }
    override func mouseDown(with event: NSEvent) { pointer(event, phase: .down) }
    override func mouseUp(with event: NSEvent) { pointer(event, phase: .up) }
    override func rightMouseDown(with event: NSEvent) { pointer(event, phase: .rightDown) }      // Escape on a monitor or the dialog (FUN_1250_0cf9)

    /// `hiRes`: show this 2x or 4x picture of the same indices instead (nil: the 320x200 one). `fb.palette` colours either.
    /// `gamma`: the game's gamma setting, added to the palette on upload as the engine does (Gamma.apply); nil = as is.
    func present(_ fb: Framebuffer, gamma: Int? = nil, hiRes: HiResFrame? = nil) {
        shownScale = hiRes?.scale ?? 1
        if let hiRes, let t = hiResTextures[hiRes.scale] {
            hiRes.pixels.withUnsafeBytes {
                t.replace(region: MTLRegionMake2D(0, 0, hiRes.width, hiRes.height), mipmapLevel: 0, withBytes: $0.baseAddress!, bytesPerRow: hiRes.width)
            }
        } else {
            fb.pixels.withUnsafeBytes {
                texture.replace(region: MTLRegionMake2D(0, 0, Framebuffer.width, Framebuffer.height), mipmapLevel: 0,
                                withBytes: $0.baseAddress!, bytesPerRow: Framebuffer.width)
            }
        }
        let p = paletteBuffer.contents().bindMemory(to: Float.self, capacity: 256 * 4)
        let palette = gamma.map { Gamma.apply(to: fb.palette, gamma: $0) } ?? fb.palette
        shown = hiRes.map { ($0.pixels, $0.width, $0.height, palette) } ?? (fb.pixels, Framebuffer.width, Framebuffer.height, palette)
        for i in 0..<256 {
            for c in 0..<3 { p[i * 4 + c] = Float(palette[i * 3 + c]) / 255 }
            p[i * 4 + 3] = 1
        }
        needsDisplay = true
    }

    /// Debug > Save Frame as PNG…: the last presented picture as it is shown, with no window around it: enlarged with whole pixels to
    /// 1280 wide (4x the original, 2x a 2x pack, a 4x pack as is), and with the 4:3 aspect the rows repeated as the screen stretches them.
    func framePNG() -> Data? {
        guard let shown else { return nil }
        let w = 1280, k = w / shown.width
        let h = correctAspect ? w * 3 / 4 : shown.height * k
        var rgba = [UInt8](repeating: 255, count: w * h * 4)
        for y in 0..<h {
            let sy = y * shown.height / h
            for x in 0..<w {
                let i = Int(shown.pixels[sy * shown.width + x / k]) * 3, o = (y * w + x) * 4
                rgba[o] = shown.palette[i]; rgba[o + 1] = shown.palette[i + 1]; rgba[o + 2] = shown.palette[i + 2]
            }
        }
        guard let provider = CGDataProvider(data: Data(rgba) as CFData),
              let image = CGImage(width: w, height: h, bitsPerComponent: 8, bitsPerPixel: 32, bytesPerRow: w * 4,
                                  space: CGColorSpace(name: CGColorSpace.sRGB)!, bitmapInfo: CGBitmapInfo(rawValue: CGImageAlphaInfo.noneSkipLast.rawValue),
                                  provider: provider, decode: nil, shouldInterpolate: false, intent: .defaultIntent) else { return nil }
        return NSBitmapImageRep(cgImage: image).representation(using: .png, properties: [:])
    }

    func mtkView(_ view: MTKView, drawableSizeWillChange size: CGSize) {}

    func draw(in view: MTKView) {
        guard let pass = currentRenderPassDescriptor, let drawable = currentDrawable,
              let cmd = queue.makeCommandBuffer() else { return }
        let dw = Double(drawableSize.width), dh = Double(drawableSize.height)
        let aspectY = correctAspect ? 1.2 : 1.0
        let fw = Double(Framebuffer.width), fh = Double(Framebuffer.height) * aspectY
        let scale = pictureScale(dw, dh, aspectY)
        let w = fw * scale / dw, h = fh * scale / dh   // half-extents in clip space
        var rect = SIMD4<Float>(Float(-w), Float(-h), Float(w), Float(h))
        let enc = cmd.makeRenderCommandEncoder(descriptor: pass)!
        enc.setRenderPipelineState(pipeline)
        enc.setVertexBytes(&rect, length: MemoryLayout<SIMD4<Float>>.size, index: 0)
        enc.setFragmentTexture(hiResTextures[shownScale] ?? texture, index: 0)
        enc.setFragmentBuffer(paletteBuffer, offset: 0, index: 0)
        let k = Double(hiResTextures[shownScale] == nil ? 1 : shownScale)
        var ratio = SIMD2<Float>(Float(scale / k), Float(scale * aspectY / k))        // screen pixels per texel
        enc.setFragmentBytes(&ratio, length: MemoryLayout<SIMD2<Float>>.size, index: 1)
        enc.drawPrimitives(type: .triangleStrip, vertexStart: 0, vertexCount: 4)
        enc.endEncoding()
        cmd.present(drawable)
        cmd.commit()
    }
}
