// YM3812 (OPL2) FM synthesis, bit for bit the model of re/formats/opl.py (see its docstring for the chip model and what is
// left out). Self-contained (Foundation only): re/tools/opl2wav.swift compiles this file on its own for the Python prototype's
// offline renders.
import Foundation

public final class OPL2 {
    public static let rate = 49716

    private static let mt2 = [1, 2, 4, 6, 8, 10, 12, 14, 16, 18, 20, 20, 24, 24, 30, 30]
    private static let kslROM = [0, 32, 40, 45, 48, 51, 53, 55, 56, 58, 59, 60, 61, 62, 63, 64]
    private static let kslShift = [-1, 1, 2, 0]
    private static let egStep = [[0, 1, 0, 1, 0, 1, 0, 1], [0, 1, 0, 1, 1, 1, 0, 1], [0, 1, 1, 1, 0, 1, 1, 1], [0, 1, 1, 1, 1, 1, 1, 1]]
    private static let egFast = [[1, 1, 1, 1, 1, 1, 1, 1], [1, 1, 1, 2, 1, 1, 1, 2], [1, 2, 1, 2, 1, 2, 1, 2], [1, 2, 2, 2, 1, 2, 2, 2]]
    private static let logsin: [Int] = (0..<256).map { Int((-log2(sin((Double($0) + 0.5) * Double.pi / 512)) * 256).rounded()) }
    private static let exp: [Int] = (0..<256).map { Int(((pow(2, Double($0) / 256) - 1) * 1024).rounded()) }
    private static let maxEnv = 0x1ff

    private enum State { case attack, decay, sustain, release }

    private struct Op {
        var am = false, vib = false, egt = false, ksr = false
        var mult = 0, ksl = 0, tl = 0, ar = 0, dr = 0, sl = 0, rr = 0, ws = 0
        var phase = 0, env = OPL2.maxEnv, state = State.release
        var idle: Bool { state == .release && env == OPL2.maxEnv }
    }

    private var ops = [Op](repeating: Op(), count: 18)       // channel c: modulator ops[2c], carrier ops[2c + 1]
    private var fnum = [Int](repeating: 0, count: 9), block = [Int](repeating: 0, count: 9)
    private var kon = [Bool](repeating: false, count: 9)
    private var fb = [Int](repeating: 0, count: 9), con = [Int](repeating: 0, count: 9)
    private var fbuf = [Int](repeating: 0, count: 18)
    private var wse = false, amDeep = false, vibDeep = false
    private var n = 0, egCounter = 0

    public init() {}

    private static func opIndex(_ off: Int) -> Int? {
        if off > 21 || off % 8 > 5 { return nil }
        return ((off / 8) * 3 + (off % 8) % 3) * 2 + (off % 8) / 3
    }

    public func write(_ register: Int, _ value: Int) {
        let reg = register & 0xff, val = value & 0xff, hi = reg & 0xe0
        if reg == 0x01 { wse = val & 0x20 != 0 }
        else if reg == 0xbd { amDeep = val & 0x80 != 0; vibDeep = val & 0x40 != 0 }
        else if hi == 0x20 || hi == 0x40 || hi == 0x60 || hi == 0x80 || hi == 0xe0 {
            guard let i = Self.opIndex(reg & 0x1f) else { return }
            switch hi {
            case 0x20: ops[i].am = val & 0x80 != 0; ops[i].vib = val & 0x40 != 0; ops[i].egt = val & 0x20 != 0
                ops[i].ksr = val & 0x10 != 0; ops[i].mult = val & 15
            case 0x40: ops[i].ksl = val >> 6; ops[i].tl = val & 0x3f
            case 0x60: ops[i].ar = val >> 4; ops[i].dr = val & 15
            case 0x80: ops[i].sl = val >> 4; ops[i].rr = val & 15
            default: ops[i].ws = val & 3
            }
        } else if (0xa0...0xa8).contains(reg) {
            let c = reg - 0xa0
            fnum[c] = (fnum[c] & 0x300) | val
        } else if (0xb0...0xb8).contains(reg) {
            let c = reg - 0xb0
            fnum[c] = (fnum[c] & 0xff) | (val & 3) << 8
            block[c] = (val >> 2) & 7
            let on = val & 0x20 != 0
            if on && !kon[c] {
                for i in 2 * c...2 * c + 1 {
                    ops[i].phase = 0; ops[i].state = .attack
                    if rate(c, ops[i], ops[i].ar) >= 60 { ops[i].env = 0; ops[i].state = .decay }
                }
            } else if !on && kon[c] {
                for i in 2 * c...2 * c + 1 { ops[i].state = .release }
            }
            kon[c] = on
        } else if (0xc0...0xc8).contains(reg) {
            let c = reg - 0xc0
            fb[c] = (val >> 1) & 7; con[c] = val & 1
        }
    }

    private func rate(_ c: Int, _ op: Op, _ r: Int) -> Int {
        if r == 0 { return 0 }
        var ksv = (block[c] << 1) | (fnum[c] >> 9 & 1)
        if !op.ksr { ksv >>= 2 }
        return min(63, r * 4 + ksv)
    }

    private func envelope(_ c: Int, _ i: Int) {
        let op = ops[i]
        let r: Int
        switch op.state {
        case .attack: r = op.ar
        case .decay: r = op.dr
        case .sustain: if op.egt { return }; r = op.rr
        case .release: if op.env == Self.maxEnv { return }; r = op.rr
        }
        let effective = rate(c, op, r)
        if effective == 0 { return }
        let k = egCounter, hi = effective >> 2
        let inc: Int
        if hi < 12 {
            let shift = 11 - hi
            if k & ((1 << shift) - 1) != 0 { return }
            inc = Self.egStep[effective & 3][(k >> shift) & 7]
        } else if hi < 15 {
            inc = Self.egFast[effective & 3][k & 7] << (hi - 12)
        } else { inc = 8 }
        if inc == 0 { return }
        var env = op.env
        if op.state == .attack {
            env = hi == 15 ? 0 : env + ((~env * inc) >> 3)
            if env <= 0 { ops[i].env = 0; ops[i].state = .decay; return }
        } else {
            env = min(Self.maxEnv, env + inc)
            if op.state == .decay && env >= op.sl << 4 { ops[i].state = .sustain }
        }
        ops[i].env = env
    }

    private static func wave(_ index: Int, _ ws: Int, _ env: Int) -> Int {
        var s = index & 0x3ff
        var negative = false
        switch ws {
        case 0: negative = s & 0x200 != 0
        case 1: if s & 0x200 != 0 { return 0 }
        case 3: if s & 0x100 != 0 { return 0 }; s &= 0xff
        default: break
        }
        let q = s & 0x100 != 0 ? ~s & 0xff : s & 0xff
        let a = min(0x1fff, logsin[q] + (env << 3))
        let v = ((exp[(a & 0xff) ^ 0xff] | 0x400) << 1) >> (a >> 8)
        return negative ? ~v : v
    }

    /// Appends `count` mono outputs (the sum of the 9 channels, clipped to 16 bit) at `rate`.
    public func generate(_ count: Int, into out: inout [Int16]) {
        for _ in 0..<count {
            let t = (n >> 6) % 210
            let trem = (t < 105 ? t : 210 - t) >> (amDeep ? 2 : 4)
            let vibpos = (n >> 10) & 7
            let egClock = n & 1 == 1
            var acc = 0
            for c in 0..<9 {
                let mi = 2 * c, ki = 2 * c + 1
                if ops[mi].idle && ops[ki].idle { continue }
                let f0 = fnum[c], b = block[c]
                let kslBase = max(0, (Self.kslROM[f0 >> 6] << 2) - ((8 - b) << 5))
                func attenuation(_ op: Op) -> Int {
                    var env = op.env + (op.tl << 2) + (op.am ? trem : 0)
                    let sh = Self.kslShift[op.ksl]
                    if sh >= 0 { env += kslBase >> sh }
                    return min(Self.maxEnv, env)
                }
                var o0 = 0, o1 = 0
                if !ops[mi].idle {
                    let mod = fb[c] != 0 ? (fbuf[mi] + fbuf[ki]) >> (9 - fb[c]) : 0
                    o0 = Self.wave((ops[mi].phase >> 9) + mod, wse ? ops[mi].ws : 0, attenuation(ops[mi]))
                    fbuf[mi] = fbuf[ki]; fbuf[ki] = o0
                }
                if !ops[ki].idle {
                    o1 = Self.wave((ops[ki].phase >> 9) + (con[c] != 0 ? 0 : o0), wse ? ops[ki].ws : 0, attenuation(ops[ki]))
                }
                acc += o1 + (con[c] != 0 ? o0 : 0)
                for i in [mi, ki] where !ops[i].idle {
                    var f = f0
                    if ops[i].vib {
                        var range = (f0 >> 7) & 7
                        if vibpos & 3 == 0 { range = 0 } else if vibpos & 1 != 0 { range >>= 1 }
                        if !vibDeep { range >>= 1 }
                        f = vibpos & 4 != 0 ? f0 - range : f0 + range
                    }
                    ops[i].phase = (ops[i].phase + ((((f << b) >> 1) * Self.mt2[ops[i].mult]) >> 1)) & 0x7ffff
                    if egClock { envelope(c, i) }
                }
            }
            if egClock { egCounter += 1 }
            out.append(Int16(clamping: acc))
            n += 1
        }
    }
}
