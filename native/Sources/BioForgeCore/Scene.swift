// Game-camera projection and figure placement, mirrors re/formats/scene.py (FUN_1178_0000 + FUN_1150_19a3).
//
// A CAMR record gives the eye position and a 3x3 matrix (s32 8.8 fixed, rows = right, forward/depth, up).
// With d = P - eye: x = row0·d, y = row1·d (depth), z = row2·d;  u = 160 + 204.5·x/y;  v = 100 - 204.5·0.833·z/y.
// Result is (u, v, depth); depth <= 0 or non-finite values are culled by the rasterizer.
// place(): rotate model space about +Z by the yaw (degrees, counter-clockwise) and translate to the figure position.
import Foundation

public struct Camera: Sendable {
    public let name: String
    public let pos: SIMD3<Double>
    let rows: [SIMD3<Double>]
    /// CAMR extra fields (half field of view, ?, far, near, fovr1, fovr2), see LevelObjects.
    public let extra: [Int]

    public init?(_ o: LevelObject) {
        guard o.tag == "CAMR", let r = o.rotation, r.count == 9 else { return nil }
        name = o.name
        pos = SIMD3(Double(o.pos[0]), Double(o.pos[1]), Double(o.pos[2]))
        rows = (0..<3).map { SIMD3(Double(r[3 * $0]) / 256, Double(r[3 * $0 + 1]) / 256, Double(r[3 * $0 + 2]) / 256) }
        extra = o.extra ?? []
    }
}

public enum Scene {
    public static let focal = 204.5, aspect = 0.833, centerX = 160.0, centerY = 100.0

    @inline(__always) static func dot(_ a: SIMD3<Double>, _ b: SIMD3<Double>) -> Double { a.x * b.x + a.y * b.y + a.z * b.z }

    public static func project(_ p: SIMD3<Double>, _ cam: Camera) -> SIMD3<Double> {
        let d = p - cam.pos
        let x = dot(d, cam.rows[0]), y = dot(d, cam.rows[1]), z = dot(d, cam.rows[2])
        return SIMD3(centerX + focal * x / y, centerY - focal * aspect * z / y, y)
    }

    public static func place(_ verts: [SIMD3<Double>], at: SIMD3<Double>, yaw: Double) -> [SIMD3<Double>] {
        let a = yaw * (Double.pi / 180), c = cos(a), s = sin(a)
        return verts.map { SIMD3(c * $0.x - s * $0.y, s * $0.x + c * $0.y, $0.z) + at }
    }
}
