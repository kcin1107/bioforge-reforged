import Foundation
import Testing
@testable import BioForgeHost

struct PictureLayoutTests {
    private func near(_ a: Double, _ b: Double) -> Bool { abs(a - b) < 0.01 }

    // (width, height, correct aspect) -> scale, rect x, y, w, h
    private let table: [(Double, Double, Bool, Double, Double, Double, Double, Double)] = [
        (640, 400, false, 2, 0, 0, 640, 400),
        (640, 400, true, 400 / 240, (640 - 320 * 400 / 240) / 2, 0, 320 * 400 / 240, 400),       // pillarbox
        (640, 480, false, 2, 0, 40, 640, 400),                                                    // letterbox
        (640, 480, true, 2, 0, 0, 640, 480),
        (1280, 800, false, 4, 0, 0, 1280, 800),
        (1280, 800, true, 800 / 240, (1280 - 320 * 800 / 240) / 2, 0, 320 * 800 / 240, 800),      // w 1066.67, x 106.67
        (1920, 1080, false, 5.4, (1920 - 1728) / 2, 0, 1728, 1080),
        (1920, 1080, true, 4.5, 240, 0, 1440, 1080),
        (1000, 1000, false, 3.125, 0, 187.5, 1000, 625),
        (1000, 1000, true, 3.125, 0, 125, 1000, 750),
        (300, 100, false, 0.5, 70, 0, 160, 100),
        (300, 100, true, 100 / 240, (300 - 320 * 100 / 240) / 2, 0, 320 * 100 / 240, 100),
    ]

    @Test func fitsAndCentresThepicture() {
        for (w, h, aspect, scale, x, y, rw, rh) in table {
            let l = PictureLayout(width: w, height: h, correctAspect: aspect)
            let r = l.rect
            #expect(near(l.scale, scale) && near(r.x, x) && near(r.y, y) && near(r.w, rw) && near(r.h, rh), "\(w)x\(h) \(aspect)")
        }
        let deck = PictureLayout(width: 1280, height: 800, correctAspect: true).rect
        #expect(near(deck.w, 1066.67) && near(deck.x, 106.67))
    }

    @Test func roundTripsEveryEighthPixel() {
        for (w, h, aspect, _, _, _, _, _) in table {
            let l = PictureLayout(width: w, height: h, correctAspect: aspect)
            for y in stride(from: 0, to: 200, by: 8) {
                for x in stride(from: 0, to: 320, by: 8) {
                    guard let p = l.windowPoint(game: x, y), let g = l.gamePoint(x: p.x, y: p.y) else { Issue.record("\(w)x\(h) \(x),\(y)"); return }
                    #expect(g.x == x && g.y == y, "\(w)x\(h) \(x),\(y)")
                }
            }
        }
    }

    @Test func outsideThePictureIsNil() {
        let l = PictureLayout(width: 640, height: 480, correctAspect: false)     // bars above and below
        #expect(l.gamePoint(x: 10, y: 39.9) == nil && l.gamePoint(x: 10, y: 440.1) == nil)
        #expect(l.gamePoint(x: -0.1, y: 240) == nil && l.gamePoint(x: 640, y: 240) == nil)
        #expect(l.gamePoint(x: 0, y: 40)! == (0, 0) && l.gamePoint(x: 639.9, y: 439.9)! == (319, 199))
        let wide = PictureLayout(width: 1280, height: 800, correctAspect: true)    // bars left and right
        #expect(wide.gamePoint(x: 106, y: 400) == nil && wide.gamePoint(x: 1173.4, y: 400) == nil)
    }

    @Test func aZeroSizeGivesNil() {
        let l = PictureLayout(width: 0, height: 0, correctAspect: true)
        #expect(l.gamePoint(x: 0, y: 0) == nil && l.windowPoint(game: 0, 0) == nil)
    }

    /// FramebufferView.gamePoint with bounds = the drawable size (so no unit conversion), y pointing up.
    private func mac(_ x: Double, _ y: Double, _ dw: Double, _ dh: Double, _ aspect: Bool) -> (Int, Int)? {
        let aspectY = aspect ? 1.2 : 1.0
        let scale = min(dw / 320, dh / (200 * aspectY))
        guard scale > 0 else { return nil }
        let w = 320 * scale, h = 200 * aspectY * scale
        let px = x - (dw - w) / 2, py = y - (dh - h) / 2
        guard px >= 0, px < w, py >= 0, py < h else { return nil }
        return (Int(px / scale), max(0, min(199, Int(200 - py / (scale * aspectY)))))
    }

    @Test func matchesTheMacMapping() {
        for (w, h, aspect, _, _, _, _, _) in table {
            let l = PictureLayout(width: w, height: h, correctAspect: aspect)
            for gy in stride(from: 0.3, to: h, by: h / 37) {
                for gx in stride(from: 0.7, to: w, by: w / 41) {
                    let a = mac(gx, h - gy, w, h, aspect), b = l.gamePoint(x: gx, y: gy)
                    #expect(a?.0 == b?.x && a?.1 == b?.y, "\(w)x\(h) \(aspect) at \(gx),\(gy)")
                }
            }
        }
    }
}
