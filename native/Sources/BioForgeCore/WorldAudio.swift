// Audio: the voice statements SETVOLUME (10d0:750d), SETPITCH (10d0:7264), ADDTOPITCH (10d0:03bf), REPLACESOUND (10d0:6a73), REVERTSOUND
// (10d0:6c22), BANKINSFX (10d0:095d), SETSOUNDCACHE (10d0:739f), REVERTSOUNDCACHE (10d0:6c73), the ramps MODIFYVOLUMEOVERTIME (10d8:3788 ->
// 10c0:36b9) / MODIFYPITCHOVERTIME (10d8:374c -> 10c0:3589) and the camera / room ambient loops (1130:0114 camera switch, 1130:0e6b per frame,
// 1100:1b59, 1100:1a15). Port of re/interp/audio.py (the oracle, which also holds the decoded rules and the ASSUMPTIONs).
//
// Every statement returns at once (AL = 0); script errors continue (warnings here).
//
// Voice state. 1028:09d3 keeps per voice a level (+0x08, the raw 0..255 volume after the positional rule, before the master table) and a
// rate (+0x0a, `sample.rate - pitch`, the playback rate in Hz, a u16). The port keeps both per issued sound handle (`voiceState`).
// SETVOLUME / the ramps set the level (1028:1464 / 168e: clamp to 255, an underflow wraps to 255) and log it to `soundVolumes` (the mixer
// ramps per handle); SETPITCH / ADDTOPITCH / the pitch ramp set the rate (1028:152b / 15db, no clamp) and log it to `soundRates` (the mixer
// resamples with it from that tick on). A dead, unknown, 0 or -1 handle is silently ignored. A positional handle (figure sound) gets its
// positional value back at the next frame (1030:07cf overwrites voice+0x08 every frame).
// ASSUMPTION (re-timing): a rate change moves the end of a non-looped handle (AI_MAIN SLUR_ENEMY_SPEECH waits on ISHANDLEPLAYING). The port
// counts samples played * TPS (`pos30`) and ends the handle when `length * TPS` is reached at the current rate; integer arithmetic only.
//
// REPLACESOUND writes a sound symbol's value (the symbol table's record, +0x19); the port keeps `soundOverrides[name] -> sample id` and
// `soundIndex` consults it first. NOT PORTED: the overrides are not written into saves (open item: the original's saved SOUNDS.DEF holds the
// current values). They persist across LOADLEVEL (script state).
//
// Ambient loops. `_<CAM>_AMBIENT` / `_<ROOM>_AMBIENT` (ROOM = the camera's first 3 characters) play looped at priority 1, non-positional, at
// the volume of the camera's volume binding (1110:19cc / 1e3c / 1e74 / 1eab): the script variable `_<CAM>_VOLUME` (else `_<CAM[:3]>_VOLUME`,
// else unbound = 255). The shipped data names only 3-letter room ambients, so the camera loop is silent and GETCAMERAAMBIENT stays -1.
import Foundation

/// Per sound handle: level (voice+0x08), rate (voice+0x0a), the sample id, and the playback position model of a non-looped handle
/// (`length` samples; `pos30` = samples played * TPS at tick `t0`, at the rate in force since then).
struct VoiceState {
    let index: Int
    var level: Int, rate: Int
    var length: Int?
    var t0: Int, pos30 = 0
}

/// The camera's volume tracker (camera+0x7e): the bound script variable (or nil), the cached value and the changed flag.
final class AmbientBinding {
    let variable: String?
    var cache: Int, dirty = false
    init(variable: String?, cache: Int) { self.variable = variable; self.cache = cache }
}

/// C integer division (truncates toward zero; Swift's `/` does the same).
private func tdiv(_ a: Int, _ b: Int) -> Int { a / b }

extension World {
    static let audioStmts: Set<String> = ["SETVOLUME", "SETPITCH", "ADDTOPITCH", "REPLACESOUND", "REVERTSOUND", "BANKINSFX", "SETSOUNDCACHE", "REVERTSOUNDCACHE"]

    /// The sample of a sound name before any REPLACESOUND (the test seam `soundNameProbe` or the bank).
    func baseSoundIndex(_ name: String) -> Int? { soundNameProbe.map { $0(name) } ?? soundBank.ids[name.lowercased()] }

    // MARK: voice state

    /// A sound handle was issued (playSound): level = the volume after the positional rule, rate = sample.rate - pitch (1028:09d3).
    func voiceStart(_ h: Int, _ idx: Int, volume: Int, pitch: Int, looped: Bool, length: Int) {
        voiceState[h] = VoiceState(index: idx, level: volume, rate: (soundBank.samples[idx].rate - pitch) & 0xffff,
                                   length: looped ? nil : length, t0: tick)
    }

    /// The VoiceState of a live sound handle, or nil (dead, unknown, 0, -1 or not a sound).
    func liveVoice(_ h: Int) -> VoiceState? {
        guard let v = voiceState[h], let vm, vm.process(h) != nil else { return nil }
        return v
    }

    /// Append (tick, handle, level) to soundVolumes. Several entries of one handle may share a tick (a ramp's step and remainder, SETVOLUME
    /// plus the positional refresh): the mixer keeps the last.
    func logVolume(_ h: Int, _ v: Int) { soundVolumes.append((tick, h, v)) }

    /// 1028:1464: v is unsigned 16 bit, clamped to 255. Live only. A positional handle is re-evaluated by the next frame's refresh.
    func setLevel(_ h: Int, _ v: Int) {
        let v = min(v & 0xffff, 255)
        guard liveVoice(h) != nil else { return }
        voiceState[h]!.level = v
        logVolume(h, v)
        if let p = soundPos[h] { soundPos[h] = (p.key, v) }
    }

    /// 1028:168e: (level + x) as an unsigned 16 bit, clamped to 255 (an underflow wraps to 255).
    func addLevel(_ h: Int, _ x: Int) {
        if let voice = liveVoice(h) { setLevel(h, voice.level + x) }
    }

    /// 1028:152b: the rate word := r (u16, no clamp).
    func setRate(_ h: Int, _ r: Int) {
        if liveVoice(h) != nil { changeRate(h, r & 0xffff) }
    }

    /// 1028:15db: the rate word += d (u16 wrap).
    func addRate(_ h: Int, _ d: Int) {
        if let voice = liveVoice(h) { changeRate(h, (voice.rate + d) & 0xffff) }
    }

    private func changeRate(_ h: Int, _ rate: Int) {
        let t = tick
        soundRates.append((t, h, rate))
        voiceState[h]!.pos30 += (t - voiceState[h]!.t0) * voiceState[h]!.rate
        voiceState[h]!.t0 = t
        voiceState[h]!.rate = rate
        guard let length = voiceState[h]!.length else { return }       // a looped handle is not re-timed
        let remaining = length * ScriptVM.ticksPerSecond - voiceState[h]!.pos30
        let wake: Int
        if remaining <= 0 { wake = t + 1 }
        else if rate == 0 { wake = ScriptVM.forever }
        else { wake = t + max(1, (remaining + rate - 1) / rate) }
        vm!.process(h)!.wake = wake
    }

    /// STOPAMBIENT on a looped voice (1028:10c9 -> 1000:046f): the voice's end (+0x10) becomes the sample's end (+0x0c) and its state 2, so
    /// the mixer (1000:115a) plays on from where it is without wrapping and frees the voice at the end. The handle and its voice slot stay
    /// live until then (ISHANDLEPLAYING; AWAKEN's quake waits on it). From here on it is timed like a one-shot: `length` and the position in
    /// the sample (`pos30`, the loop wrapped). A second release changes nothing. -> logged to `soundReleases`.
    func releaseLoop(_ h: Int) {
        guard let voice = liveVoice(h), voice.length == nil else { return }
        let s = soundBank.samples[voice.index], t = tick, tps = ScriptVM.ticksPerSecond
        var p30 = voice.pos30 + (t - voice.t0) * voice.rate
        let lo = s.loopStart * tps, hi = s.loopEnd * tps
        if hi > lo && p30 >= hi { p30 = lo + (p30 - lo) % (hi - lo) }
        voiceState[h]!.pos30 = p30
        voiceState[h]!.t0 = t
        voiceState[h]!.length = s.length
        soundReleases.append((t, h))
        let remaining = s.length * tps - p30
        let wake: Int
        if remaining <= 0 { wake = t + 1 }
        else if voice.rate == 0 { wake = ScriptVM.forever }
        else { wake = t + max(1, (remaining + voice.rate - 1) / voice.rate) }
        vm!.process(h)!.wake = wake
    }

    // MARK: statements

    /// SETVOLUME / SETPITCH / ADDTOPITCH `handle value` (a handle of 0 or -1, or not a number, is skipped); REPLACESOUND `name value`,
    /// REVERTSOUND `name`; BANKINSFX / SETSOUNDCACHE / REVERTSOUNDCACHE are sample-cache only (modelled no-ops).
    func cmdAudio(_ name: String, _ args: [ScriptValue]) {
        switch name {
        case "SETVOLUME", "SETPITCH", "ADDTOPITCH":
            guard case .int(let h)? = args.first, h != 0, h != -1 else { return }
            let value = args.count > 1 ? num(args[1]) : 0
            if name == "SETPITCH" { setRate(h, value) }
            else if name == "ADDTOPITCH" { addRate(h, value & 0xffff) }
            else {
                setLevel(h, value)
                if let cam = currentCamera, h == roomAmbient || h == cameraAmbient {
                    bindingSet(binding(cam), value)                    // 10d0:750d: even when the voice is already dead
                }
            }
        case "REPLACESOUND":
            guard case .str(let target)? = args.first, baseSoundIndex(target) != nil else {
                warn("REPLACESOUND: not a sound name (error 0x34)")
                return
            }
            let value = args.count > 1 ? args[1] : .int(0)
            var id: Int?
            switch value {
            case .str(let s): id = soundOverrides[s.lowercased()] ?? baseSoundIndex(s)    // another sound name: its CURRENT value (chains copy)
            case .int(let i): id = i
            case .list: id = nil
            }
            guard let id else { warn("REPLACESOUND \(pyStr(args[0])): unknown value \(pyRepr(value))"); return }
            soundOverrides[target.lowercased()] = id
        case "REVERTSOUND":
            guard case .str(let target)? = args.first, baseSoundIndex(target) != nil else {
                warn("REVERTSOUND: not a sound name (error 0x34)")
                return
            }
            soundOverrides[target.lowercased()] = nil                  // 6c22: the DEF value comes back
        case "SETSOUNDCACHE":
            // 10d0:739f: limit [19bb] := FUN_1008_06ab(a << 10, b, c << 10) = a KB, plus b * (free - 5,000,000) / 1024 when more than 5 MB are
            // free, capped at c KB (c != 0); evicts LRU samples above it. Memory management only: no effect here.
            let a = (args + [.int(0), .int(0), .int(0)]).prefix(3)
            if !a.allSatisfy({ num($0) != 0 }) { warn("SETSOUNDCACHE: needs three non-zero values (error 0x17c)") }
        default: break
        }
    }

    // MARK: MODIFYVOLUMEOVERTIME / MODIFYPITCHOVERTIME

    /// `FN(handle, START, END, DURATION)` is an absolute ramp (DURATION != 0), `FN(handle, DELTA, DURATION)` a relative one (10c0:36b9
    /// volume / 10c0:3589 pitch). Error 0x3a (START == END, DELTA == 0) returns 0 without a task; ASSUMPTION: DURATION <= 0 does too (the
    /// engine would divide by zero; no shipped use). -> a new VM native handle that lives exactly DURATION ticks (the original task serial
    /// from [2ed0]; SUSPENDWHILE on it releases after DURATION ticks).
    func cmdOvertime(_ name: String, _ args: [ScriptValue]) -> Int {
        let volume = name == "MODIFYVOLUMEOVERTIME"
        let a = Array((args.map { num($0) } + [0, 0, 0, 0]).prefix(4))
        let h = a[0]
        let absolute = a[3] != 0
        let start = a[1]
        let delta = wrap32(absolute ? a[2] - a[1] : a[1]), dur = wrap32(absolute ? a[3] : a[2])
        if delta == 0 || dur <= 0 {
            warn("\(name): nothing to ramp (error 0x3a)")
            return 0
        }
        guard let vm else { return 0 }
        var bound: AmbientBinding?
        if volume, let cam = currentCamera, h != 0, h != -1, h == roomAmbient || h == cameraAmbient {
            bound = binding(cam)                                       // 10b8:04d3 / 0653: the current camera's tracker
        }
        if absolute {                                                  // 10b8:04d3: the start value is set at once
            if volume {
                setLevel(h, start)
                if let bound { bindingSet(bound, start) }
            } else { setRate(h, start) }
        }
        // 10b8:0762: |delta| < D (case A): step = +1 ALWAYS, period = D / delta (negative for delta < 0: it then fires every tick, so
        // INTRO.scr:416 `(_sfx_2, 65, 0, 120)` RISES by 120: INFERRED from the disassembly, replicated); else step = delta / D, the
        // remainder on the last tick, period 1.
        let step: Int, rem: Int, period: Int
        if abs(delta) < dur { step = 1; rem = 0; period = tdiv(dur, delta) }
        else { step = tdiv(delta, dur); rem = delta - step * dur; period = 1 }
        func apply(_ x: Int) {                                         // 10b8:090c
            if volume {
                addLevel(h, x)
                if let bound { bindingSet(bound, bindingGet(bound) + x) }
            } else { addRate(h, x) }
        }
        var started = false, countdown = period, elapsed = 0
        return vm.nativeGenerator(volume ? "MODIFYVOLUMEOVERTIME" : "MODIFYPITCHOVERTIME") { [unowned self] in
            _ = self
            if !started { started = true; return 1 }                   // the first advance is on the next update
            elapsed += 1                                               // 10b8:0853
            countdown -= 1
            if countdown <= 0 { countdown = period; apply(step) }
            if elapsed == dur { apply(rem); return nil }
            return 1
        }
    }

    // MARK: camera / room ambient loops

    /// The volume tracker of camera `cam` (1110:19cc): bound to the script variable `_<CAM>_VOLUME`, else `_<CAM[:3]>_VOLUME`, else unbound
    /// (255). ASSUMPTION: a bound tracker starts with the variable's value as its cache.
    func binding(_ cam: String) -> AmbientBinding {
        if let b = ambientBindings[cam] { return b }
        let vars = vm?.globals ?? [:]
        let v = ["_\(cam.lowercased())_volume", "_\(String(cam.prefix(3)).lowercased())_volume"].first { vars[$0] != nil }
        let b = AmbientBinding(variable: v, cache: v.map { num(vars[$0]!) } ?? 255)
        ambientBindings[cam] = b
        return b
    }

    /// 1110:1e74: reads the variable into the cache, clears the changed flag.
    func bindingGet(_ b: AmbientBinding) -> Int {
        if let v = b.variable { b.cache = num(vm!.globals[v] ?? .int(0)) }
        b.dirty = false
        return b.cache
    }

    /// 1110:1e3c: the variable differs from the cache (bound), or the flag is set (unbound).
    func bindingChanged(_ b: AmbientBinding) -> Bool {
        if let v = b.variable { return b.cache != num(vm!.globals[v] ?? .int(0)) }
        return b.dirty
    }

    /// 1110:1eab: cache := v (flag set when it changes); a bound tracker writes the script variable.
    func bindingSet(_ b: AmbientBinding, _ v: Int) {
        if v != b.cache { b.dirty = true }
        b.cache = v
        if let name = b.variable { vm!.setGlobal(name, .int(v)) }
    }

    /// 1118:0044, the lookup of every name the engine formats (room and camera loops, hits, blocks, BONKs, `_METAL_HITS_`, the last
    /// motion-cue try): the sound named `name` (case-insensitive, through soundIndex so REPLACESOUND applies; a name longer than 25
    /// characters is cut to 24); not found: strip the last `_xxx` segment and retry; nothing left -> -1.
    func ambientId(_ name: String) -> Int {
        var name = name
        if name.count > 25 { name = String(name.prefix(24)) }
        while !name.isEmpty {
            if let idx = soundIndex(.str(name)) { return idx }
            if let k = name.lastIndex(of: "_"), k != name.startIndex { name = String(name[..<k]) } else { name = "" }
        }
        return -1
    }

    /// FUN_1088_13ea, a sound cue: the first of `_<motion>_<n>_<form>_<camera>`, `_<motion>_<n>_<form>_<room>`, `_<motion>_<n>_<camera>`,
    /// `_<motion>_<n>_<room>` the bank has exactly (FUN_1100_1d82), else `_<motion>_<n>_<form>` through 1118:0044 (FUN_1100_1c92: cut at
    /// the last `_` until found, so Lex's `_WALK_1_LEX` exists and `_ATK_M1_1_CAYNAN` is an alias of `_WALK_1_CAYNAN`). form = +0x1ea
    /// (fig.type), camera = [63e1], room = [63e5] (its first 3 characters). Priority 0, volume 255, pitch 0, positional at the figure.
    func motionCue(_ fig: Figure, _ n: Int) {
        if let probe = motionCueProbe { probe(fig, n); return }
        let cam = switchingTo ?? camera ?? defaultCamera ?? "", room = String(cam.prefix(3))
        let m = fig.motion ?? "", form = fig.type
        var idx: Int?
        for name in ["_\(m)_\(n)_\(form)_\(cam)", "_\(m)_\(n)_\(form)_\(room)", "_\(m)_\(n)_\(cam)", "_\(m)_\(n)_\(room)"] {
            idx = soundIndex(.str(name))
            if idx != nil { break }
        }
        if idx == nil {
            let a = ambientId("_\(m)_\(n)_\(form)")
            if a < 0 { return }
            idx = a
        }
        playSound(idx!, priority: 0, fig: fig.pos != nil ? fig : nil)
    }

    /// 1100:1b59 (stop mode 0): keep the loop when its sample is unchanged (only the volume is re-set), else stop the old one at once and
    /// start the new one (1100:1a15 -> 1028:0f0a: looped, priority 1, volume low byte, pitch 0, not positional). -> the handle.
    func startOrKeep(_ handle: Int, _ name: String, _ vol: Int) -> Int {
        let idx = ambientId(name)
        if (liveVoice(handle)?.index ?? -1) == idx {
            if handle != 0 { setLevel(handle, vol) }
            return handle
        }
        if handle != 0 {
            stopSound(handle)
            if soundHandles.contains(where: { $0.handle == handle }) && soundStops.allSatisfy({ $0.handle != handle }) {
                soundStops.append((tick, handle))                      // a loop whose process ended without a stop: end its voice in the mix
            }
        }
        return idx >= 0 ? playSound(idx, volume: vol & 0xff, pitch: 0, loop: true, priority: 1) : 0
    }

    /// 1130:0e6b, every unpaused frame: after a camera switch start / keep the camera and room loops at the binding's volume; then a changed
    /// binding (a script assigned `_<CAM>_VOLUME`, SETVOLUME / a ramp on an ambient handle) re-sets both handles.
    func updateAmbients() {
        guard let cam = currentCamera, vm != nil else { return }
        let b = binding(cam)
        if ambientPending {
            let vol = bindingGet(b)
            cameraAmbient = startOrKeep(cameraAmbient, "_\(cam)_AMBIENT", vol)
            roomAmbient = startOrKeep(roomAmbient, "_\(cam.prefix(3))_AMBIENT", vol)
            ambientPending = false
        }
        if bindingChanged(b) {
            let v = bindingGet(b)
            if roomAmbient != 0 { setLevel(roomAmbient, v) }
            if cameraAmbient != 0 { setLevel(cameraAmbient, v) }
        }
    }

    /// 1130:0114 step e: [63f1] := 1 unless a monitor is running ([4e2c], ISMONITORRUNNING).
    func cameraSwitched() {
        if !(monitor != nil || (options.map { !$0.closed } ?? false)) { ambientPending = true }
    }
}
