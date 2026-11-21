// Sound-effect mixer: the offline mix of re/interp/movie.py mix_audio and the live renderer are the same code.
//
// A voice is one SOUND/SUBTITLE event: it starts at frame(tick) = round(tick / 30 * 22050) and ends at its STOPSOUND (or the end of
// the sample). Output frame i reads the sample at position (i - start) * (rate - pitch) / 22050 (linear interpolation, pitch -1024
// plays faster); a looped sample (loop_end > loop_start) wraps from loop_end back to loop_start until its STOPAMBIENT, then plays on to the
// end of the sample. The gain is volume / 255, or, for a
// positional sound, the piecewise-linear curve through the World's volume log: hold the old value until one tick before a change
// (max(t - 1, 0) / 30 s), then ramp to the new one at t / 30 s. Voices add into a Float64 accumulator in event order, which is
// scaled by 256, rounded half-to-even and clipped to Int16, so every float operation matches numpy. The volume of every voice start
// and positional change goes through the master-volume table of the effect level in force at that tick (World.sfxLog,
// MasterVolume.table: FUN_1028_1da5, applied where the engine hands the volume to the driver), as movie.mix_audio does.
//
// `render` produces the next block of the timeline and may be called with any block size; live playback feeds the same events
// incrementally (`sync` once per game tick) and renders from the audio thread, so live output equals the offline mix sample for
// sample. `origin` maps game frames to the timeline (offline: 0; live: playhead + a small latency pad when the game starts).
import Foundation

public final class SoundMixer: @unchecked Sendable {
    public static let rate = 22050
    private static let ticksPerSecond = 30.0

    private struct Voice {
        let handle: Int, pcm: [Int8], loopStart: Int, loopEnd: Int, loops: Bool, start: Int, volume: Int, tick0: Int
        let step: Double
        var end = Int.max
        var release = Int.max, released: (base: Double, raw: Double)?     // STOPAMBIENT's frame; the wrapped and raw positions there
        var segs: [(frame: Int, base: Double, step: Double)] = [], seg = -1   // rate changes: position = base + (i - frame) * step per segment
        var xs: [Double] = [], ys: [Double] = [], cursor = 0, lastTick = -1     // gain curve (seconds, volume)

        /// The unwrapped sample position `rel` frames after the start.
        func rawPos(_ rel: Int) -> Double {
            var k = -1
            while k + 1 < segs.count && segs[k + 1].frame <= rel { k += 1 }
            return k < 0 ? Double(rel) * step : segs[k].base + Double(rel - segs[k].frame) * segs[k].step
        }

        /// Adds frames [max(start, f0), min(end, f1)) into `acc` (index 0 = frame f0); true once the voice has ended.
        /// A released loop plays on from its wrapped position at the release, without wrapping, to the end of the sample.
        mutating func mix(into acc: UnsafeMutablePointer<Double>, from f0: Int, to f1: Int, origin: Int) -> Bool {
            let n = pcm.count, last = Double(n - 1), looped = loops && loopEnd > loopStart
            var i = max(start, f0)
            while i < min(f1, end) {
                let rel = i - start
                while seg + 1 < segs.count && segs[seg + 1].frame <= rel { seg += 1 }
                var pos = seg < 0 ? Double(rel) * step : segs[seg].base + Double(rel - segs[seg].frame) * segs[seg].step
                if looped {
                    let raw = pos
                    if pos >= Double(loopEnd) { pos = wrap(pos) }
                    if rel >= release - start {
                        if released == nil { let r = rawPos(release - start); released = (r >= Double(loopEnd) ? wrap(r) : r, r) }
                        pos = released!.base + (raw - released!.raw)
                        if pos > last { return true }
                    }
                } else if pos > last { return true }
                var v = Double(pcm[n - 1])                                       // np.interp: the right edge holds the last sample
                if pos < last { let j = Int(pos), a = Double(pcm[j]); v = (Double(pcm[j + 1]) - a) * (pos - Double(j)) + a }
                var gain = Double(volume) / 255
                if !xs.isEmpty {
                    let x = Double(i - origin) / Double(SoundMixer.rate)
                    while cursor + 1 < xs.count && xs[cursor + 1] <= x { cursor += 1 }
                    var g = ys[cursor]
                    if x < xs[0] { g = ys[0] }
                    else if cursor + 1 < xs.count {
                        g = (ys[cursor + 1] - ys[cursor]) / (xs[cursor + 1] - xs[cursor]) * (x - xs[cursor]) + ys[cursor]
                    }
                    gain = g / 255
                }
                acc[i - f0] += v * 256 * gain
                i += 1
            }
            return end <= f1
        }

        func wrap(_ pos: Double) -> Double {
            Double(loopStart) + (pos - Double(loopStart)).truncatingRemainder(dividingBy: Double(loopEnd - loopStart))
        }
    }

    private let lock = NSLock()
    private var voices: [Voice] = []
    private var scratch: [Double] = []
    private var origin: Int
    private var fed = (log: 0, volumes: 0, rates: 0, stops: 0, sfx: 0, releases: 0)  // World log entries already handed to the mixer
    private var levels: [(tick: Int, sfx: Int)] = [(0, 100)]  // effect level steps (World.sfxLog)
    private var tables: [Int: [Int]] = [:]
    /// Next timeline frame to be rendered.
    public private(set) var playhead = 0

    public init(origin: Int = 0) { self.origin = origin }

    /// Game tick -> frame offset on the timeline (Python: int(round(tick / TPS * AUDIO_RATE))).
    static func frame(_ tick: Int) -> Int { Int((Double(tick) / ticksPerSecond * Double(rate)).rounded(.toNearestOrEven)) }

    /// New game: drop all voices and start the World's tick 0 `pad` frames after the current playhead.
    public func reset(pad: Int) {
        lock.lock(); defer { lock.unlock() }
        voices = []; fed = (0, 0, 0, 0, 0, 0); levels = [(0, 100)]
        origin = playhead + pad
    }

    /// Live playback only: game ticks stopped while the audio kept playing (a menu held open, a held picture, a dropped hitch), so `tick`
    /// would start behind the playhead and its sounds would lose their beginning. Moves tick 0 on the timeline so `tick` starts `pad`
    /// frames after the playhead again; voices already playing keep their place. No effect while the game keeps up.
    public func keepUp(tick: Int, pad: Int) {
        lock.lock(); defer { lock.unlock() }
        if origin + Self.frame(tick) < playhead { origin = playhead + pad - Self.frame(tick) }
    }

    /// The effect level steps (World.sfxLog entries, in order): the first replaces the initial level 100.
    public func setLevel(tick: Int, sfx: Int) {
        lock.lock(); defer { lock.unlock() }
        if levels.count == 1 && tick == 0 && levels[0].tick == 0 { levels[0] = (0, sfx) } else { levels.append((tick, sfx)) }
    }

    /// Master-volume table value for a script volume at `tick` (caller holds the lock).
    private func master(_ tick: Int, _ volume: Int) -> Int {
        var sfx = levels[0].sfx
        for step in levels where step.tick <= tick { sfx = step.sfx }
        if tables[sfx] == nil { tables[sfx] = MasterVolume.table(sfx) }
        return tables[sfx]![max(0, min(255, volume))]
    }

    public func play(_ s: SoundSample, pcm: [Int8], tick: Int, volume: Int, pitch: Int, handle: Int, looped: Bool = true) {
        guard pcm.count >= 2 else { return }
        lock.lock(); defer { lock.unlock() }
        voices.append(Voice(handle: handle, pcm: pcm, loopStart: s.loopStart, loopEnd: s.loopEnd, loops: looped, start: origin + Self.frame(tick), volume: master(tick, volume), tick0: tick,
                            step: Double(max(s.rate - pitch, 1)) / Double(Self.rate)))
    }

    /// A positional volume change at `tick` (World.soundVolumes entry).
    public func setVolume(handle: Int, tick: Int, volume: Int) {
        lock.lock(); defer { lock.unlock() }
        guard let k = voices.lastIndex(where: { $0.handle == handle }) else { return }
        if voices[k].lastTick == tick && !voices[k].ys.isEmpty {              // several entries in one tick: the last one counts
            voices[k].ys[voices[k].ys.count - 1] = Double(master(tick, volume))
            return
        }
        voices[k].lastTick = tick
        if voices[k].ys.isEmpty && tick > voices[k].tick0 {          // a non-positional voice plays at its start volume until the first change
            voices[k].xs.append(Double(voices[k].tick0) / Self.ticksPerSecond)
            voices[k].ys.append(Double(voices[k].volume))
        }
        if let held = voices[k].ys.last {
            voices[k].xs.append(Double(max(tick - 1, 0)) / Self.ticksPerSecond)
            voices[k].ys.append(held)
        }
        voices[k].xs.append(Double(tick) / Self.ticksPerSecond)
        voices[k].ys.append(Double(master(tick, volume)))
    }

    /// A playback rate change at `tick` (World.soundRates entry): the resampling step becomes rate / 22050 from then on, the position stays
    /// continuous (rate 0 holds it).
    public func setRate(handle: Int, tick: Int, rate: Int) {
        lock.lock(); defer { lock.unlock() }
        guard let k = voices.lastIndex(where: { $0.handle == handle }) else { return }
        let f = Self.frame(tick) - (voices[k].start - origin)
        let prev = voices[k].segs.last ?? (frame: 0, base: 0.0, step: voices[k].step)
        voices[k].segs.append((frame: f, base: prev.base + Double(f - prev.frame) * prev.step, step: Double(rate) / Double(Self.rate)))
    }

    public func stop(handle: Int, tick: Int) {
        lock.lock(); defer { lock.unlock() }
        if let k = voices.lastIndex(where: { $0.handle == handle }) { voices[k].end = origin + Self.frame(tick) }
    }

    /// STOPAMBIENT at `tick` (World.soundReleases entry): the loop plays on to the end of its sample.
    public func release(handle: Int, tick: Int) {
        lock.lock(); defer { lock.unlock() }
        if let k = voices.lastIndex(where: { $0.handle == handle }) { voices[k].release = origin + Self.frame(tick) }
    }

    /// Hands the World's new sound-log entries (plays, volume changes, rates, releases, stops - in that order) to the mixer.
    public func sync(_ world: World) {
        let bank = world.soundBank
        for l in world.sfxLog.dropFirst(fed.sfx) { setLevel(tick: l.tick, sfx: l.sfx) }
        for e in world.soundLog.dropFirst(fed.log) { play(bank.samples[e.index], pcm: bank.pcm(e.index), tick: e.tick, volume: e.volume, pitch: e.pitch, handle: e.handle, looped: world.soundLoops.contains(e.handle)) }
        for v in world.soundVolumes.dropFirst(fed.volumes) { setVolume(handle: v.handle, tick: v.tick, volume: v.volume) }
        for r in world.soundRates.dropFirst(fed.rates) { setRate(handle: r.handle, tick: r.tick, rate: r.rate) }
        for r in world.soundReleases.dropFirst(fed.releases) { release(handle: r.handle, tick: r.tick) }
        for s in world.soundStops.dropFirst(fed.stops) { stop(handle: s.handle, tick: s.tick) }
        fed = (world.soundLog.count, world.soundVolumes.count, world.soundRates.count, world.soundStops.count, world.sfxLog.count, world.soundReleases.count)
    }

    /// Renders the next `out.count` frames of the timeline.
    public func render(into out: UnsafeMutableBufferPointer<Int16>) {
        lock.lock(); defer { lock.unlock() }
        let n = out.count, f0 = playhead
        if scratch.count < n { scratch = [Double](repeating: 0, count: n) }
        scratch.withUnsafeMutableBufferPointer { acc in
            for i in 0..<n { acc[i] = 0 }
            var ended = Set<Int>()
            for k in voices.indices where voices[k].mix(into: acc.baseAddress!, from: f0, to: f0 + n, origin: origin) { ended.insert(k) }
            if !ended.isEmpty { voices = voices.enumerated().filter { !ended.contains($0.offset) }.map(\.element) }
            for i in 0..<n { out[i] = Int16(clamping: Int(acc[i].rounded(.toNearestOrEven))) }
        }
        playhead = f0 + n
    }

    /// movie.mix_audio: the whole World sound log of a run that ended at `endTick`, as 22050 Hz mono Int16.
    public static func mix(_ world: World, endTick: Int) -> [Int16] {
        let m = SoundMixer()
        m.sync(world)
        var out = [Int16](repeating: 0, count: Int((Double(endTick) / ticksPerSecond * Double(rate)).rounded(.up)))
        out.withUnsafeMutableBufferPointer { m.render(into: $0) }
        return out
    }
}
