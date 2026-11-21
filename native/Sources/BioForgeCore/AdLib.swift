// The original AdLib music path: a port of the game's AIL AdLib driver (MUSIC/AILADLIB.DLL) that turns the music sequencer's
// MIDI stream into OPL2 register writes. Mirrors re/formats/adlib.py, whose docstring has the recovered driver behaviour (voice
// allocation, priorities, register formulas) and the device choice. OPL2.swift synthesises the writes.
import Foundation

/// The installed timbres: every timbre of FLX entry 259 that a TIMB chunk of the AdLib songs (128...) or transitions (260) lists.
public struct AdLibBank: Sendable {
    let timbres: [Int: [UInt8]]                   // bank << 8 | patch -> 14 timbre bytes (u16 length, s8 transpose, 11 registers)

    public init(game: GameFolder) throws { try self.init(data: game.read("MUSIC/MUSIC.FLX")) }

    public init(data: [UInt8]) throws {
        let flex = try Flex(data: data)
        guard flex.entries.count > 261 else { throw FormatError("MUSIC.FLX is missing its AdLib timbres") }
        let raw = flex.bytes(flex.entries[259])
        var table: [Int: [UInt8]] = [:], p = 0
        while p + 6 <= raw.count, !(raw[p] == 0xff && raw[p + 1] == 0xff) {
            let key = Int(raw[p + 1]) << 8 | Int(raw[p])
            let off = Int(raw[p + 2]) | Int(raw[p + 3]) << 8 | Int(raw[p + 4]) << 16 | Int(raw[p + 5]) << 24
            p += 6
            guard off + 2 <= raw.count else { throw FormatError("bad AdLib timbre offset \(off)") }
            let length = Int(raw[off]) | Int(raw[off + 1]) << 8
            guard length >= 14, off + length <= raw.count else { throw FormatError("bad AdLib timbre length \(length)") }
            if table[key] == nil { table[key] = raw.slice(off, off + length) }
        }
        var wanted = Set<Int>()
        func timb(_ data: [UInt8], _ nodes: [IFFNode]) {
            for node in nodes {
                if node.id == "TIMB" {
                    let count = Int(data[node.offset]) | Int(data[node.offset + 1]) << 8
                    for i in 0..<count { wanted.insert(Int(data[node.offset + 3 + 2 * i]) << 8 | Int(data[node.offset + 2 + 2 * i])) }
                } else if let children = node.children { timb(data, children) }
            }
        }
        for index in Array(128..<177) + [260] where flex.entries[index].size > 0 {
            let data = flex.bytes(flex.entries[index])
            timb(data, try IFF.parse(data))
        }
        timbres = table.filter { wanted.contains($0.key) }
    }

    public var count: Int { timbres.count }
    func timbre(bank: Int, patch: Int) -> [UInt8]? { timbres[bank << 8 | patch] }
}

/// AILADLIB.DLL's YAMAHA part: `send` takes MIDI channel messages, `serve` is the 60 Hz service; register writes collect in
/// `writes` as (register, value).
public final class AdLibDriver {
    static let velocity = [82, 85, 88, 91, 94, 97, 100, 103, 106, 109, 112, 115, 118, 121, 124, 127]
    static let modOp = [0, 1, 2, 6, 7, 8, 12, 13, 14], carOp = [3, 4, 5, 9, 10, 11, 15, 16, 17]
    static let opReg = [0, 1, 2, 3, 4, 5, 8, 9, 10, 11, 12, 13, 16, 17, 18, 19, 20, 21]
    static let freq: [Int] = [
        690, 692, 695, 697, 700, 702, 705, 707, 710, 713, 715, 718, 720, 723, 726, 728, 731, 733, 736, 739, 741, 744, 747, 749,
        752, 755, 758, 760, 763, 766, 769, 771, 774, 777, 780, 783, 785, 788, 791, 794, 797, 800, 803, 806, 809, 811, 814, 817,
        820, 823, 826, 829, 832, 835, 838, 841, 844, 847, 850, 854, 857, 860, 863, 866, 869, 872, 875, 879, 882, 885, 888, 891,
        895, 898, 901, 904, 908, 911, 914, 917, 921, 924, 927, 931, 934, 937, 941, 944, 948, 951, 955, 958, 961, 965, 968, 972,
        975, 979, 983, 986, 990, 993, 997, 1000, 1004, 1008, 1011, 1015, 1019, 1022, -511, -509, -507, -505, -504, -502, -500,
        -498, -496, -494, -492, -490, -488, -486, -484, -482, -480, -479, -477, -475, -473, -471, -469, -467, -465, -463, -460,
        -458, -456, -454, -452, -450, -448, -446, -444, -442, -440, -438, -436, -433, -431, -429, -427, -425, -423, -420, -418,
        -416, -414, -412, -409, -407, -405, -403, -401, -398, -396, -394, -391, -389, -387, -385, -382, -380, -378, -375, -373,
        -371, -368, -366, -363, -361, -359, -356, -354, -351, -349, -347, -344, -342, -339, -337]
    static let initControllers = [(7, 127), (1, 0), (10, 64), (11, 127), (64, 0), (114, 0), (110, 0), (111, 0), (112, 0)]
    static let initPrograms: [Int?] = [nil, 68, 48, 95, 78, 41, 3, 110, 122, nil]
    static let fAVEKM = 0x80, fLevel = 0x40, fEnv = 0x20, fWave = 0x10, fFB = 0x08, fFreq = 0x01, fAll = 0xf9
    static let noVoice = 0xff

    struct Slot {
        var status = 0, chan = 0, key = 0, note = 0, transpose = 0, vel = 0, sustained = false, voice = AdLibDriver.noVoice
        var flags = 0, b0 = 0, kon = 0, conn = 0, mask = 0, fb = 0, prio = 0, eff = 0
        var ksl = [0, 0], avekm = [0, 0], ad = [0, 0], sr = [0, 0], tl = [0, 0], mult = [0, 0], ws = [0, 0]
    }

    private let bank: AdLibBank
    public var writes: [(register: Int, value: Int)] = []
    private var slots = [Slot](repeating: Slot(), count: 16)
    private var owner = [Int](repeating: AdLibDriver.noVoice, count: 9)
    private var voices = [Int](repeating: 0, count: 16)
    private var rr = -1, serves = 0
    private var vol = [Int](repeating: 0, count: 16), expr = [Int](repeating: 0, count: 16), pan = [Int](repeating: 0, count: 16)
    private var mod = [Int](repeating: 0, count: 16), sus = [Int](repeating: 0, count: 16)
    private var bendLSB = [Int](repeating: 0, count: 16), bendMSB = [Int](repeating: 0, count: 16)
    private var vprot = [Int](repeating: 0, count: 16), tbank = [Int](repeating: 0, count: 16)
    private var timbre = [[UInt8]?](repeating: nil, count: 16)

    public init(bank: AdLibBank) {
        self.bank = bank
        var regs = [Int](repeating: 0, count: 0xf6)
        regs[0x01] = 0x20; regs[0x04] = 0x60; regs[0xbd] = 0xc0
        for (base, value) in [(0x20, 0x01), (0x40, 0x3f), (0x60, 0xff), (0x80, 0x0f)] { for r in base..<base + 0x16 { regs[r] = value } }
        for r in 1..<0xf6 { writes.append((r, regs[r])) }
        for ch in 1...9 { for (c, v) in Self.initControllers { send([UInt8(0xb0 | ch), UInt8(c), UInt8(v)]) } }
        for ch in 1...9 {
            send([UInt8(0xe0 | ch), 0, 0x40])
            if let program = Self.initPrograms[ch] { send([UInt8(0xc0 | ch), UInt8(program)]) }
        }
    }

    public func send(_ m: [UInt8]) {
        guard let status = m.first else { return }
        let st = Int(status & 0xf0), ch = Int(status & 15)
        let a = m.count > 1 ? Int(m[1]) : 0, b = m.count > 2 ? Int(m[2]) : 0
        var mask = 0
        switch st {
        case 0xb0:
            switch a {
            case 114: tbank[ch] = b; return
            case 112: vprot[ch] = b; return
            case 1: mod[ch] = b; mask = Self.fAVEKM
            case 7: vol[ch] = b; mask = Self.fLevel
            case 11: expr[ch] = b; mask = Self.fLevel
            case 10: pan[ch] = b; mask = Self.fLevel
            case 64:
                sus[ch] = b
                if b < 64 { releaseSustain(ch) }
                return
            case 121:
                sus[ch] = 0
                releaseSustain(ch)
                mod[ch] = 0; expr[ch] = 127; bendLSB[ch] = 0; bendMSB[ch] = 64
                mask = Self.fAVEKM | Self.fLevel | Self.fFreq
            case 123:
                for i in 0..<16 where slots[i].status == 1 && slots[i].chan == ch { noteOff(ch, slots[i].note) }
                return
            default: return
            }
        case 0xc0: timbre[ch] = bank.timbre(bank: tbank[ch], patch: a); return
        case 0xe0: bendLSB[ch] = a; bendMSB[ch] = b; mask = Self.fFreq
        case 0x90:
            if (1...9).contains(ch) { if b != 0 { noteOn(ch, a, b) } else { noteOff(ch, a) } }
            return
        case 0x80: noteOff(ch, a); return
        default: return
        }
        for i in 0..<16 where slots[i].status != 0 && slots[i].chan == ch { slots[i].flags |= mask; update(i) }
    }

    public func serve() {
        serves += 1
        if serves == 24 { serves = 0; priority() }
    }

    private func noteOn(_ ch: Int, _ key: Int, _ velocity: Int) {
        guard let t = ch == 9 ? bank.timbre(bank: 127, patch: key) : timbre[ch],
              let i = slots.firstIndex(where: { $0.status == 0 }) else { return }
        var s = Slot()
        s.b0 = slots[i].b0                         // the 0xB0 copy (09f8) is only written by the register writer (13ea)
        s.chan = ch; s.key = key
        if ch == 9 { s.note = Int(t[2]); s.transpose = 0 } else { s.note = key; s.transpose = Int(Int8(bitPattern: t[2])) }
        s.vel = Self.velocity[(velocity >> 1 & 0x7f) >> 2]
        s.status = 1; s.kon = 0x20; s.prio = 0x7fff
        s.conn = Int(t[8]) & 1; s.fb = Int(t[8]) & 0x0f
        s.ksl = [Int(t[4]) & 0xc0, Int(t[10]) & 0xc0]
        s.tl = [~Int(t[4]) & 0x3f, ~Int(t[10]) & 0x3f]
        s.avekm = [Int(t[3]) & 0xf0, Int(t[9]) & 0xf0]
        s.mult = [Int(t[3]) & 0x0f, Int(t[9]) & 0x0f]
        s.ad = [Int(t[5]), Int(t[11])]; s.sr = [Int(t[6]), Int(t[12])]; s.ws = [Int(t[7]), Int(t[13])]
        s.mask = s.conn | 2
        s.flags = Self.fAll
        slots[i] = s
        assign(i)
    }

    private func assign(_ i: Int) {
        for _ in 0..<9 {
            rr = (rr + 1) % 9
            if owner[rr] == Self.noVoice { take(i, rr); update(i); return }
        }
        priority()
    }

    private func take(_ i: Int, _ v: Int) {
        slots[i].voice = v
        voices[slots[i].chan] += 1
        owner[v] = slots[i].chan
        slots[i].flags = Self.fAll
    }

    private func release(_ i: Int) {
        guard slots[i].voice != Self.noVoice else { return }
        slots[i].kon = 0
        slots[i].flags |= Self.fFreq
        update(i)
        voices[slots[i].chan] -= 1
        owner[slots[i].voice] = Self.noVoice
        slots[i].voice = Self.noVoice
        slots[i].status = 0
    }

    private func noteOff(_ ch: Int, _ key: Int) {
        for i in 0..<16 where slots[i].status == 1 && slots[i].key == key && slots[i].chan == ch {
            if sus[ch] < 64 { release(i); slots[i].status = 0; reassign() } else { slots[i].sustained = true }
        }
    }

    private func releaseSustain(_ ch: Int) {
        for i in 0..<16 where slots[i].status != 0 && slots[i].chan == ch && slots[i].sustained { noteOff(ch, slots[i].note) }
    }

    private func reassign() {
        guard let i = slots.firstIndex(where: { $0.status != 0 && $0.voice == Self.noVoice }),
              let v = owner.firstIndex(of: Self.noVoice) else { return }
        take(i, v)
        priority()
    }

    private func priority() {
        var count = 0
        for i in 0..<16 where slots[i].status != 0 {
            count += 1
            let base = vprot[slots[i].chan & 15] >= 64 ? 0xffff : slots[i].prio
            let n = voices[slots[i].chan & 15]
            slots[i].eff = base < n ? 0 : base - n
        }
        while count > 0 {
            var best = 0, worst = 0xffff, a: Int?, b: Int?
            for i in 0..<16 where slots[i].status != 0 {
                if slots[i].voice == Self.noVoice { if best <= slots[i].eff { best = slots[i].eff; a = i } }
                else if slots[i].eff <= worst { worst = slots[i].eff; b = i }
            }
            guard best >= worst, best != 0, let a, let b else { return }
            let v = slots[b].voice
            release(b)
            take(a, v)
            update(a)
            count -= 1
        }
    }

    private func op(_ op: Int, _ reg: Int, _ value: Int) { writes.append((reg + Self.opReg[op], value & 0xff)) }

    private func update(_ i: Int) {
        let s = slots[i]
        guard s.voice != Self.noVoice else { return }
        let v = s.voice, ch = s.chan & 15, mo = Self.modOp[v], co = Self.carOp[v], f = s.flags
        var level = 0
        if f & Self.fLevel != 0 {
            var x = ((vol[ch] * expr[ch] * 2) >> 8) & 0xff
            x = x != 0 ? x + 1 : 0
            x = (((x & 0xff) * s.vel * 2) >> 8) & 0xff
            level = x != 0 ? x + 1 : 0
        }
        if f & Self.fAVEKM != 0 {
            let vib = mod[ch] >= 64 ? 0x40 : 0
            op(mo, 0x20, s.mult[0] | vib | s.avekm[0]); op(co, 0x20, s.mult[1] | vib | s.avekm[1])
        }
        if f & Self.fLevel != 0 {
            for (j, o) in [(0, mo), (1, co)] {
                var lv = s.tl[j]
                if s.mask & (1 << j) != 0 { lv = lv * (level & 0xff) / 0x7f }
                op(o, 0x40, (~lv & 0x3f) | s.ksl[j])
            }
        }
        if f & Self.fEnv != 0 { op(mo, 0x60, s.ad[0]); op(co, 0x60, s.ad[1]); op(mo, 0x80, s.sr[0]); op(co, 0x80, s.sr[1]) }
        if f & Self.fWave != 0 { op(co, 0xe0, s.ws[1]); op(mo, 0xe0, s.ws[0]) }
        if f & Self.fFB != 0 { writes.append((0xc0 + v, s.fb)) }
        if f & Self.fFreq != 0 {
            if s.kon & 0x20 == 0 { writes.append((0xb0 + v, s.b0 & 0xdf)) }
            else {
                let (fnum, hi) = frequency(s)
                writes.append((0xa0 + v, fnum & 0xff))
                slots[i].b0 = hi | s.kon
                writes.append((0xb0 + v, hi | s.kon))
            }
        }
        slots[i].flags = 0
    }

    private func frequency(_ s: Slot) -> (Int, Int) {
        let ch = s.chan & 15
        let bend = bendMSB[ch] << 7 | bendLSB[ch]
        let b = ((bend - 0x2000) >> 5) * 12
        var n = s.note + s.transpose - 24
        while n + 12 < 0 { n += 12 }
        n += 12
        while n > 0x5f { n -= 12 }
        var u = ((n * 256 + b + 8) >> 4) - 0xc0
        while u + 0xc0 < 0 { u += 0xc0 }
        u += 0xc0
        while u > 0x5ff { u -= 0xc0 }
        var f = Self.freq[(u >> 4) % 12 * 16 + (u & 15)]
        var block = f < 0 ? (u >> 4) / 12 : (u >> 4) / 12 - 1
        if block < 0 { block = 0; f >>= 1 }
        return (f & 0x3ff, ((f & 0x3ff) >> 8) | block << 2)
    }
}

/// Driver + timeline: music events (seconds) in, OPL2 register writes stamped with chip samples out (adlib.py
/// register_writes / chip_writes). Serve k sits at k / 60 s: it sends the events whose 120 Hz tick floor(t * 120 + 0.5) is at
/// most 2k + 1 (two XMIDI steps per serve), then serves the driver if a song is loaded and not paused; its writes land at chip
/// sample k * OPL2.rate / 60.
public final class AdLibSequencer {
    public struct Write: Sendable, Equatable {
        public let sample: Int, register: UInt8, value: UInt8
        public init(sample: Int, register: UInt8, value: UInt8) { self.sample = sample; self.register = register; self.value = value }
    }
    private let driver: AdLibDriver
    private var nextServe = 0
    private var serving = false
    private var pending: [MusicMIDIEvent] = []
    private var pendingServing: [(time: Double, on: Bool)] = []
    private var output: [Write] = []

    public init(bank: AdLibBank) {
        driver = AdLibDriver(bank: bank)
        flush(serve: 0)
    }

    public static func tick(_ seconds: Double) -> Int { Int((seconds * 120 + 0.5).rounded(.down)) }

    /// Run every serve whose two steps are at or before `seconds`, with these (time-sorted) events and serving changes
    /// (MusicSequencer.takeServingChanges), and return the new writes.
    public func advance(_ events: [MusicMIDIEvent], serving changes: [(time: Double, on: Bool)], through seconds: Double) -> [Write] {
        pending += events
        pendingServing += changes
        let last = Self.tick(seconds)
        var i = 0, j = 0
        while 2 * nextServe + 1 <= last {
            while i < pending.count && Self.tick(pending[i].time) <= 2 * nextServe + 1 { driver.send(pending[i].bytes); i += 1 }
            while j < pendingServing.count && Self.tick(pendingServing[j].time) <= 2 * nextServe + 1 { serving = pendingServing[j].on; j += 1 }
            if serving { driver.serve() }
            flush(serve: nextServe)
            nextServe += 1
        }
        pending.removeFirst(i)
        pendingServing.removeFirst(j)
        let result = output
        output.removeAll(keepingCapacity: true)
        return result
    }

    private func flush(serve: Int) {
        let sample = serve * OPL2.rate / 60
        for w in driver.writes { output.append(Write(sample: sample, register: UInt8(w.register), value: UInt8(w.value))) }
        driver.writes.removeAll(keepingCapacity: true)
    }
}

/// Live AdLib output: the main thread queues register writes (stamped with chip samples of the music timeline), the audio
/// thread renders the chip at OPL2.rate. A write lands at its sample + the pad (the same lead the effect mixer uses); a write
/// that arrives late applies before the next sample rendered.
public final class OPL2Stream: @unchecked Sendable {
    private let lock = NSLock()
    private var chip = OPL2()
    private var queue: [AdLibSequencer.Write] = []
    private var head = 0
    private var clock = 0, pad = 0, lead = 0
    private var scratch: [Int16] = []

    public init() {}

    /// A new timeline: a silent chip, music time 0 at `pad` chip samples from now.
    public func reset(pad: Int) {
        lock.lock(); defer { lock.unlock() }
        chip = OPL2(); queue.removeAll(); head = 0; clock = 0; self.pad = pad; lead = pad
    }

    /// As SoundMixer.keepUp: after a stall (no tick ran while the chip kept rendering) the write at `sample` would land behind the
    /// clock, and every later write would bunch up at block starts. Moves music time so `sample` lands the reset's lead ahead again.
    public func keepUp(sample: Int) {
        lock.lock(); defer { lock.unlock() }
        if sample + pad < clock { pad = clock + lead - sample }
    }

    public func push(_ writes: [AdLibSequencer.Write]) {
        guard !writes.isEmpty else { return }
        lock.lock(); defer { lock.unlock() }
        queue += writes
    }

    /// The next `count` samples as Float in -1...1.
    public func render(into out: UnsafeMutablePointer<Float>, count: Int) {
        lock.lock(); defer { lock.unlock() }
        scratch.removeAll(keepingCapacity: true)
        let end = clock + count
        while clock < end {
            while head < queue.count && queue[head].sample + pad <= clock {
                chip.write(Int(queue[head].register), Int(queue[head].value)); head += 1
            }
            let next = head < queue.count ? min(end, max(clock + 1, queue[head].sample + pad)) : end
            chip.generate(next - clock, into: &scratch)
            clock = next
        }
        if head > 4096 { queue.removeFirst(head); head = 0 }
        for i in 0..<count { out[i] = Float(scratch[i]) / 32768 }
    }
}
