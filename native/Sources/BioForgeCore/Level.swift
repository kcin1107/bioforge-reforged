// Level object files in INITGAME/ (initial game state) and the figures they place, mirrors the loading part of world.py.
//
// Every ROOMS camera belongs to the level whose CAMR record carries its name (index built once; the first level in file-name
// order wins). A level's FIGR records place figures: record name = BODY type, bytes 33..41 = instance name (first record per
// instance wins), pos = figure origin. Figures start with heading 0 in their initial motion (STAND, else the first), which
// advances one motion frame per 2 ticks (30 Hz ticks) and loops; the prototype's viewing-camera lists are filled in by scripts,
// so here every figure is drawn when it lies entirely in front of the camera (all depths > 200, world.py NEAR_DEPTH).
import Foundation

public struct LevelFigure: Sendable {
    public let instance: String, type: String
    public let position: SIMD3<Double>
}

public struct Level: Sendable {
    public let name: String
    public let cameras: [String: Camera]
    public let figures: [LevelFigure]

    public init(name: String, data: [UInt8]) throws {
        self.name = name
        let objs = try LevelObjects.load(data)
        cameras = Dictionary(objs.compactMap { o in Camera(o).map { (o.name.uppercased(), $0) } }, uniquingKeysWith: { $1 })
        var seen = Set<String>(), figs: [LevelFigure] = []
        for o in objs where o.tag == "FIGR" {
            let inst = o.raw.cString(33, 42).uppercased()
            if seen.insert(inst).inserted {
                figs.append(LevelFigure(instance: inst, type: o.name.uppercased(), position: SIMD3(o.pos.map(Double.init))))
            }
        }
        figures = figs
    }
}

public struct LevelIndex: Sendable {
    public let levels: [String: Level]
    /// Upper-case camera name -> level name.
    public let cameraLevel: [String: String]

    public init(game: GameFolder) throws {
        var levels: [String: Level] = [:], owner: [String: String] = [:]
        for file in game.list("INITGAME", ext: "IFF") {
            let name = (file as NSString).deletingPathExtension.uppercased()
            let level = try Level(name: name, data: game.read("INITGAME/\(file)"))
            levels[name] = level
            for cam in level.cameras.keys.sorted() where owner[cam] == nil { owner[cam] = name }
        }
        self.levels = levels
        cameraLevel = owner
    }
}

/// A level's figures with their assets loaded, ready to be posed for any tick.
public struct Stage: Sendable {
    struct Placed: Sendable { let instance: String; let assets: FigureAssets; let position: SIMD3<Double>; let motion: Motion }
    let placed: [Placed]

    public init(level: Level, game: GameFolder, cache: inout [String: FigureAssets]) throws {
        var out: [Placed] = []
        for f in level.figures {
            if cache[f.type] == nil { cache[f.type] = try FigureAssets(type: f.type, game: game) }
            let assets = cache[f.type]!
            if let m = assets.initialMotion, !m.frames.isEmpty { out.append(Placed(instance: f.instance, assets: assets, position: f.position, motion: m)) }
        }
        placed = out
    }

    /// Instance names in draw order.
    public var instances: [String] { placed.map(\.instance) }

    /// Figures to draw through `camera` at `tick`, in placement order.
    public func figures(for camera: Camera, tick: Int) -> [DrawFigure] {
        placed.compactMap { p in
            let frame = p.motion.frames[(tick / 2) % p.motion.frames.count]
            let world = Scene.place(p.assets.pose(frame), at: p.position, yaw: 0)
            guard world.allSatisfy({ Scene.project($0, camera).z > 200 }) else { return nil }
            return DrawFigure(name: p.instance, mesh: p.assets.mesh, world: world)
        }
    }
}
