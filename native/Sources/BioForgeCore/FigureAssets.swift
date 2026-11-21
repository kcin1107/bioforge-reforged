// Everything needed to pose one figure type (BODY/<TYPE>.BED): mesh, skeleton, skin and motions, mirrors world.py Assets.
//
// The BED names REAL (mesh), SKEL, SKIN and motion files (LIST if present, else MOTN; files that do not exist are skipped).
// Motion names are upper-cased; the first definition wins across files and within a file.
import Foundation

public struct FigureAssets: Sendable {
    public let type: String
    public let mesh: EORMesh
    public let skeleton: Skeleton, skin: Skin
    /// Motions in file order, unique by upper-cased name.
    public let motions: [Motion]
    /// BODY/<type>.COL hit cubes (same base name as the BED); empty when the file does not exist.
    public let col: [ColVolume]

    public init(type: String, game: GameFolder) throws {
        self.type = type
        let bed = Bed(data: try game.read("BODY/\(type).BED"))
        func file(_ key: String) throws -> String {
            guard let f = bed.entries[key]?.first else { throw FormatError("\(type).BED has no \(key)") }
            return "BODY/\(f)"
        }
        mesh = try EORMesh(data: game.read(file("REAL")))
        skeleton = try Skeleton(data: game.read(file("SKEL")))
        skin = try Skin(data: game.read(file("SKIN")))
        var seen = Set<String>(), all: [Motion] = []
        for f in bed.entries["LIST"] ?? bed.entries["MOTN"] ?? [] where game.resolve("BODY/\(f)") != nil {
            for m in try Motion.load(game.read("BODY/\(f)")) where seen.insert(m.name.uppercased()).inserted {
                all.append(Motion(name: m.name.uppercased(), frames: m.frames, frameTime: m.frameTime, flags: m.flags,
                                  strength: m.strength, strikeLimb: m.strikeLimb, kind: m.kind, loops: m.loops))
            }
        }
        motions = all
        col = game.resolve("BODY/\(type).COL") != nil ? try ColVolume.load(game.read("BODY/\(type).COL")) : []
    }

    public func motion(_ name: String) -> Motion? { motions.first { $0.name == name.uppercased() } }

    /// STAND, else the first motion (nil if the figure has none).
    public var initialMotion: Motion? { motion("STAND") ?? motions.first }

    /// Local posed vertices: root x/y zero, root z kept (world.py Assets.pose).
    public func pose(_ frame: MotionFrame) -> [SIMD3<Double>] { skeleton.pose(mesh.verts, links: skin.links, frame: frame) }
}
