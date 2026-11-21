// Mat3.rotated takes cos and sin from JointAngleTable, Apple libm's bits, so posed vertices are the same on Linux and Windows.
import Foundation
import Testing
@testable import BioForgeCore

struct JointAngleTableTests {
    @Test func coversMinus256To511() {
        #expect(JointAngleTable.first == -256)
        #expect(JointAngleTable.cosBits.count == 768 && JointAngleTable.sinBits.count == 768)
        #expect(Mat3.cosSin(0) == (1, 0))
        #expect(Mat3.cosSin(64).0.magnitude < 1e-15 && Mat3.cosSin(64).1 == 1, "a quarter turn")
    }

    /// The table was generated on macOS; on the Mac it must equal libm exactly, so the Mac's results (and the fixtures) are unchanged.
    #if os(macOS)
    @Test func matchesAppleLibmBitForBit() {
        for a in -256...511 {
            let t = Double(a * 2) * Double.pi / 256
            let (c, s) = Mat3.cosSin(a)
            #expect(c.bitPattern == cos(t).bitPattern && s.bitPattern == sin(t).bitPattern, "angle \(a)")
        }
    }
    #endif

    @Test func fallsBackToLibmOutsideTheTable() {
        for a in [-1000, -257, 512, 4000] {
            let t = Double(a * 2) * Double.pi / 256
            #expect(Mat3.cosSin(a) == (cos(t), sin(t)))
        }
    }
}
