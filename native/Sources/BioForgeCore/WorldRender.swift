// Drawing the world (world.py render_camera) and the game session that ties World and VM together.
//
// render(into:) composites the current camera: the room's sprites (their frame comes from the script variable `_<name>_frame`)
// and every placed figure whose viewing-camera list contains the camera (the player has none = always visible), when it lies
// entirely in front of the camera (all depths > NEAR_DEPTH). Cameras without room art (TITLE) render black. Figures are drawn in
// the World's figure order; the compositor sorts all cels by depth.
import Foundation

extension World {
    /// The figure's current pose: motion, frames, frame and blend (FUN_1088_1854 -> FUN_1088_0d63), or nil without one.
    func poseState(_ fig: Figure) -> HeldPose? {
        guard let frames = fig.frames, !frames.isEmpty else { return nil }
        let duration = fig.frameDuration()
        return HeldPose(motion: fig.motion, frames: frames, idx: min(fig.idx, frames.count - 1),
                        fraction: !fig.frozen && duration > 0 ? Double(fig.phase) / Double(duration) : 0)
    }

    /// World vertices of a figure in its current pose. An idle requested at the end of an update (1088:4155, 4167) reaches the model only
    /// at the figure's next update, so until then the pose of the update is drawn (`heldPose`, world.py posed). Live, DOSBox-X 2026-11-12:
    /// no standing pose in bed between WAKE_UP and OUT_OF_BED.
    func posed(_ fig: Figure) -> [V3]? {
        guard let state = fig.heldPose ?? poseState(fig), let pos = fig.pos, let m = fig.assets.motion(state.motion ?? "") else { return nil }
        let frames = state.frames, i = state.idx, fraction = state.fraction
        let vertices = frames.count == m.frames.count ? fig.assets.pose(m, i, fraction: fraction)
                                                   : fig.assets.assets.pose(frames[i])
        return Scene.place(vertices, at: pos + subframeRoot(fig, frames, i, fraction), yaw: -fig.heading)
    }

    /// FUN_1088_0d63 blends the root x, y toward the next interior frame too, while the world mover steps the position once per frame:
    /// the drawn position is ahead of fig.pos by the blended part of the next frame's root change, through the figure's matrix (world.py
    /// subframe_root). Without it a body that travels (OUT_OF_BED's step off the bed) slides back within each frame and jumps forward.
    func subframeRoot(_ fig: Figure, _ frames: [MotionFrame], _ i: Int, _ fraction: Double) -> V3 {
        guard fraction > 0, i + 1 < frames.count else { return V3(0, 0, 0) }
        let a = frames[i].pos, b = frames[i + 1].pos
        let dx = Double(Int(Double(a.x) + Double(b.x - a.x) * fraction) - a.x)
        let dy = Double(Int(Double(a.y) + Double(b.y - a.y) * fraction) - a.y)
        let m = orientation(fig)
        return V3((Double(m[0][0]) * dx + Double(m[1][0]) * dy) / 256, (Double(m[0][1]) * dx + Double(m[1][1]) * dy) / 256, 0)
    }

    /// What both renderers need for a room camera: its compositor, camera, the figures to draw and the scripts' sprite frames.
    func drawInput(camera cam: String) -> (Compositor, Camera, (figures: [DrawFigure], frames: [String: Int]))? {
        guard let compositor = resources.compositor(cam) else { return nil }
        let camera = data.cameras[cam] ?? resources.levelIndex?.cameraLevel[cam].flatMap { resources.levelIndex?.levels[$0]?.cameras[cam] }
        guard let camera else { return nil }
        var figs: [DrawFigure] = []
        for fig in figures.values {
            if fig.pos == nil || fig.frames == nil || fig.exploded || (fig.viewCams != nil && !fig.viewCams!.contains(cam)) { continue }
            guard let v = posed(fig), v.allSatisfy({ Scene.project($0, camera).z > Self.nearDepth }) else { continue }
            figs.append(DrawFigure(name: fig.name, mesh: fig.assets.assets.mesh, world: v, anim: fig.anim.mapValues(\.frame)))
        }
        figs += itemCels(cam, camera)
        figs += fragmentFigures(camera)
        var frames: [String: Int] = [:]
        for n in compositor.spriteNames {
            if case .int(let f)? = vm?.globals["_" + n.lowercased() + "_frame"] { frames[n] = f }       // missing variable = frame 0
        }
        return (compositor, camera, (figs, frames))
    }

    /// Render the named room camera into `fb` without selecting it or firing camera events.
    public func render(camera cam: String?, into fb: inout Framebuffer) {
        guard let cam = cam?.uppercased(), let (compositor, camera, input) = drawInput(camera: cam) else {
            fb.palette = [UInt8](repeating: 0, count: 768)
            fb.clear()
            return
        }
        compositor.render(camera: camera, figures: input.figures, spriteFrames: input.frames, flats: flatCels(camera), into: &fb)
    }

    func viewportFrame(_ camera: String) -> Framebuffer? {
        guard resources.compositor(camera.uppercased()) != nil else { return nil }
        var fb = Framebuffer()
        render(camera: camera, into: &fb)
        return fb
    }

    public func render(into fb: inout Framebuffer) {
        if let f = show.flic { renderFlic(f, into: &fb); return }          // 1100:0580: an open flic is drawn instead of the world
        render(camera: currentCamera, into: &fb)
    }

    /// The CAMERA SHOW picture (ROOMS/<cam>.CAM, first image, its own palette), or nil (world.py shown_picture_rgb). KILLLEX shows STITLE
    /// before FORCERELOAD, and live (DOSBox-X, 2026-11-11) the options dialog sits on it.
    /// What the options dialog is drawn over (world.py options_underlay): the CAMERA SHOW picture, else the screen as it was (a running
    /// monitor, or the room with its caption). Live (O in CE31) the dialog shows the room dimmed; the world is paused, so a fresh render is it.
    func optionsUnderlay() -> Framebuffer {
        if let shown = shownPictureFrame() { return shown }
        var fb = Framebuffer()
        if let monitor { monitor.render(into: &fb); return fb }
        render(into: &fb)
        if let event = captionEvent { SubtitleRenderer.render(event, font: resources.captionFont, readable: readableText, into: &fb) }
        return fb
    }

    func shownPictureFrame() -> Framebuffer? {
        guard let (palette, _, frame) = shownPictureArt() else { return nil }
        var fb = Framebuffer()
        fb.palette = palette
        fb.blit(frame)
        return fb
    }

    /// The CAMERA SHOW picture's palette, its pack path (rooms/<CAM>/<ENTRY>.0) and first frame; nil without a picture (RTRW: a palette only).
    func shownPictureArt() -> (palette: [UInt8], path: String, frame: CAMFrame)? {
        guard let name = shownPicture, let cam = try? CAMFile(data: game.read("ROOMS/\(name).CAM")), let entry = cam.images.first,
              let frame = try? cam.frames(of: entry).first else { return nil }
        return (cam.palette, "rooms/\(name.uppercased())/\(entry.name.uppercased()).0", frame)
    }

    /// The player-facing frame includes the active caption. `render(into:)` stays the bare scene for camera feeds and
    /// the indexed-frame oracle, which both compare the room picture without overlays.
    public func renderPresentation(into fb: inout Framebuffer) {
        if creditsRolling, let options { fb = optionsUnderlay(); options.drawCredits(into: &fb); return }          // the roll over the undimmed picture
        if let options, !options.closed { options.render(into: &fb, underlay: optionsUnderlay()); return }          // over the screen it covers (play.py to_rgb)
        if let monitor { monitor.render(into: &fb); return }
        // CAMERA SHOW (10d0:115c) switched the screen to the picture camera until a real switch or LOADLEVEL: START's TITLE stays up while
        // CHAOS loads, until GOODMORNINGLEX's FADE HIDE (world.py shown_picture_rgb). An open flic is drawn instead of the world.
        if show.flic == nil, let shown = shownPictureFrame() { fb = shown } else { render(into: &fb) }
        if let event = captionEvent { SubtitleRenderer.render(event, font: resources.captionFont, readable: readableText, into: &fb) }
    }

    /// The caption on screen now. 10d0:16cb -> 10b0:0f48 never reads [50bc]: captions show with subtitles off.
    var captionEvent: SubtitleEvent? {
        subtitleLog.last(where: { $0.tick <= tick && tick < $0.end && (settings.subtitles || captionHandles.contains($0.handle)) })
    }
}

/// A running game: the world, its script VM and the frame loop. `newGame` boots the original opening (TITLE from INITGAME, block
/// GAME of START.scr, which follows its LOADLEVEL chain to the CHAOS wake-up).
public final class GameSession {
    public let world: World
    public let vm: ScriptVM
    /// Pick Medium when the opening's difficulty dialog is waiting (unattended replay); the app turns it off so the player chooses.
    public var autoDifficulty = true
    /// The play directory a loaded session was unpacked from (a recording copies it); nil for a new game.
    public internal(set) var origin: URL?

    public init(resources: GameResources, level: String, camera: String? = nil, stateDirectory: URL? = nil) throws {
        world = try World(resources: resources, level: level, camera: camera, stateDirectory: stateDirectory)
        vm = ScriptVM(engine: world, defs: try ScriptDefs(game: resources.game))
        try vm.loadLevel(level, library: resources.library)
    }

    public static func newGame(resources: GameResources, configure: ((GameSession) -> Void)? = nil) throws -> GameSession {
        let s = try GameSession(resources: resources, level: "TITLE")
        configure?(s)
        s.world.fireEvent("TITLE_LOAD")
        s.vm.fire("GAME", owner: "global")
        return s
    }

    /// The app's hold on a CAMERA SHOW picture after the options dialog closes over it (KNOWN_DIFFERENCES.md), in seconds. The original
    /// keeps START's TITLE on screen for as long as LOADLEVEL CHAOS loads (no render until 1130:147c's black palette), which took seconds
    /// on the machines of the time and takes a frame here, so the app waits this long before the next tick. Presentation only: no tick runs
    /// during it, so the tick timeline and the random stream are unchanged. No key skips it, as no key skips the original's load.
    public static let pictureHold = 2.0
    /// Whether the dialog was open at the last pictureHoldDue call.
    private var dialogWasOpen = false

    /// Ask before every tick: true once, when the dialog has closed (in a tick or by a key) over a SHOW picture since the last call.
    public func pictureHoldDue() -> Bool {
        defer { dialogWasOpen = world.isOptionsOpen }
        return dialogWasOpen && !world.isOptionsOpen && world.show.flic == nil && world.shownPictureFrame() != nil
    }

    /// One 30 Hz frame: scripts, world, and, if `autoDifficulty`, the Medium choice the opening waits for.
    public func tick() {
        vm.tickOnce()
        world.step()
        if autoDifficulty { world.chooseDefaultDifficulty() }
    }
}
