// Python's random.Random for int seeds: MT19937 seeded by init_by_array (CPython random_seed), getrandbits and
// randint/randrange (_randbelow_with_getrandbits), so the script RANDOM function reproduces the prototype's stream exactly
// (world.py uses random.Random(0).randint). Only what world.py needs is implemented; the seed is a non-negative Int.
import Foundation

public struct PyRandom: Sendable {
    private var mt = [UInt32](repeating: 0, count: 624)
    private var index = 624

    /// The whole generator state (session recordings restore it, see SessionRecorder).
    public struct State: Codable, Equatable, Sendable { public var mt: [UInt32], index: Int }
    public var state: State {
        get { State(mt: mt, index: index) }
        set { mt = newValue.mt; index = newValue.index }
    }

    public init(seed: Int = 0) {
        // CPython: key = |seed| as little-endian 32-bit words (one word for 0), init_by_array(key)
        var key: [UInt32] = [], s = UInt(seed.magnitude)
        repeat { key.append(UInt32(truncatingIfNeeded: s)); s >>= 32 } while s != 0
        mt[0] = 19650218
        for i in 1..<624 { mt[i] = 1812433253 &* (mt[i - 1] ^ (mt[i - 1] >> 30)) &+ UInt32(i) }
        var i = 1, j = 0
        for _ in 0..<max(624, key.count) {
            mt[i] = (mt[i] ^ ((mt[i - 1] ^ (mt[i - 1] >> 30)) &* 1664525)) &+ key[j] &+ UInt32(j)
            i += 1; j += 1
            if i >= 624 { mt[0] = mt[623]; i = 1 }
            if j >= key.count { j = 0 }
        }
        for _ in 0..<623 {
            mt[i] = (mt[i] ^ ((mt[i - 1] ^ (mt[i - 1] >> 30)) &* 1566083941)) &- UInt32(i)
            i += 1
            if i >= 624 { mt[0] = mt[623]; i = 1 }
        }
        mt[0] = 0x8000_0000
    }

    /// genrand_uint32
    public mutating func next32() -> UInt32 {
        if index >= 624 {
            for k in 0..<624 {
                let y = (mt[k] & 0x8000_0000) | (mt[(k + 1) % 624] & 0x7fff_ffff)
                mt[k] = mt[(k + 397) % 624] ^ (y >> 1) ^ (y & 1 == 0 ? 0 : 0x9908_b0df)
            }
            index = 0
        }
        var y = mt[index]
        index += 1
        y ^= y >> 11
        y ^= (y << 7) & 0x9d2c_5680
        y ^= (y << 15) & 0xefc6_0000
        y ^= y >> 18
        return y
    }

    /// getrandbits(k) for 0 < k <= 63.
    public mutating func getrandbits(_ k: Int) -> UInt64 {
        if k <= 32 { return UInt64(next32() >> UInt32(32 - k)) }
        var out: UInt64 = 0, left = k, shift: UInt64 = 0     // words are filled least significant first
        while left > 0 {
            var r = UInt64(next32())
            if left < 32 { r >>= UInt64(32 - left) }
            out |= r << shift
            shift += 32; left -= 32
        }
        return out
    }

    /// _randbelow(n) for n >= 1.
    public mutating func randbelow(_ n: Int) -> Int {
        let k = Int.bitWidth - n.leadingZeroBitCount
        var r = getrandbits(k)
        while r >= UInt64(n) { r = getrandbits(k) }
        return Int(r)
    }

    /// random.randint(a, b), a <= b.
    public mutating func randint(_ a: Int, _ b: Int) -> Int { a + randbelow(b - a + 1) }
}
