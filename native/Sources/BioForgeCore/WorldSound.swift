// Sound, subtitle and music bookkeeping of the engine binding (world.py "Sound"): SoundMixer renders these logs (stage 4a), and
// handle lifetimes, voice allocation and the logs must match the prototype because scripts wait on sound handles.
//
// SOUND returns a handle (a timed VM process) valid for the sample's duration, or until STOPSOUND for looped samples. Voices follow
// FUN_1028_18f4: 8 slots; the first free one is used; with all busy the lowest-priority voice (strict <, lowest index) is stopped and
// reused unless the new priority is lower (sound dropped, handle 0). Positional volume (FUN_1030_04db): min(255, 65536 / q^2),
// q = max(1, d / 128), d = distance camera -> figure. SUBTITLE plays its voice at priority 2; the subtitle object is its own handle
// and lives sample_len * 30 / 11025 + len(text) ticks.
import Foundation

public struct SoundEvent: Sendable { public let tick: Int, index: Int, name: String, volume: Int, pitch: Int, handle: Int }
public struct SubtitleEvent: Sendable { public let tick: Int, handle: Int, colour: Int, text: String; public var end: Int }

extension World {
    /// Script sound name (or number) -> sample index, or nil.
    func soundIndex(_ ref: ScriptValue) -> Int? {
        let bank = soundBank
        switch ref {
        case .str(let s):
            if let o = soundOverrides[s.lowercased()] { return o >= 0 && o < bank.samples.count ? o : nil }    // REPLACESOUND / REVERTSOUND
            return baseSoundIndex(s)
        case .int(let i): return i >= 0 && i < bank.samples.count ? i : nil
        case .list: return nil
        }
    }

    /// Eye position of the 3D view's camera, or nil.
    func listenerPos() -> V3? { currentCamera.flatMap { data.cameras[$0]?.pos } }

    func positionalVolume(_ fig: Figure, scriptVolume: Int = 255) -> Int { positionalVolume(at: fig.pos, scriptVolume: scriptVolume) }

    func positionalVolume(at pos: V3?, scriptVolume: Int = 255) -> Int {
        guard let cam = listenerPos(), let p = pos else { return scriptVolume >> 1 }
        let d = p - cam
        let q = max(1, Int((d.x * d.x + d.y * d.y + d.z * d.z).squareRoot()) / 128)
        return min(255, 65536 / (q * q))
    }

    /// Per-frame refresh (FUN_1030_07cf): re-evaluate every live positional sound; log changes.
    func refreshSoundVolumes() {
        for h in soundPos.keys.sorted() {
            let (key, last) = soundPos[h]!
            let pos = figures[key] != nil ? figures[key]!.pos : items[key]?.pos        // a figure, or a missile's looped travel sound
            guard let vm, vm.process(h) != nil, pos != nil else { soundPos[h] = nil; continue }
            let v = positionalVolume(at: pos)
            if v != last {
                soundPos[h] = (key, v)
                logVolume(h, v)
            }
        }
    }

    /// Log a sound event and start its handle (see the header). -> handle (0 without a VM, or dropped)
    @discardableResult func playSound(_ idx: Int, volume: Int = 255, pitch: Int = 0, loop: Bool = false, priority: Int = 1, fig: Figure? = nil, item: Item? = nil) -> Int {
        let bank = soundBank, s = bank.samples[idx]
        var volume = min(volume, 255)
        let located = fig?.name ?? item?.name                    // positional: a figure, or an item (a missile's looped travel sound, a bounce)
        if located != nil { volume = positionalVolume(at: fig?.pos ?? item?.pos, scriptVolume: volume) }
        let ticks = loop && s.loopEnd > 0 ? Self.loopTicks : Int((bank.duration(idx, pitch: pitch) * Double(ScriptVM.ticksPerSecond)).rounded(.up))
        var slot: Int?
        if let vm {
            slot = voices.firstIndex { v in v.map { vm.process($0.handle) == nil } ?? true }
            if slot == nil {
                var lowest = 0
                for i in voices.indices where voices[i]!.priority < voices[lowest]!.priority { lowest = i }
                if priority < voices[lowest]!.priority {
                    soundDrops.append((vm.tick, idx, s.name))
                    return 0
                }
                stopSound(voices[lowest]!.handle)
                slot = lowest
            }
        }
        let h = vm?.timedHandle(ticks: ticks) ?? 0
        if h != 0 && ticks == Self.loopTicks { soundLoops.insert(h) }
        if let slot { voices[slot] = (h, priority) }
        soundLog.append(SoundEvent(tick: tick, index: idx, name: s.name, volume: volume, pitch: pitch, handle: h))
        if h != 0 {
            soundHandles.append((h, idx))
            voiceStart(h, idx, volume: volume, pitch: pitch, looped: ticks == Self.loopTicks, length: s.length)
            if let located {
                soundPos[h] = (located, volume)
                soundVolumes.append((tick, h, volume))
            }
        }
        return h
    }

    /// SUBTITLE / MINORSUBTITLE (10d8:3b26 / 10d8:36ed -> FUN_10e8_0529): (sound, colour = 0x75, [volume = 0xff,] text). -> subtitle handle
    func subtitle(_ args: [ScriptValue], minor: Bool, ticks fixedTicks: Int? = nil) -> Int {
        guard let vm else { return 0 }
        let live = curSubtitle.map { vm.process($0.handle) != nil } ?? false
        if minor && live { return 0 }
        var text = ""
        for case .str(let s) in args where s != args[0].stringValue && s.unicodeScalars.count > text.unicodeScalars.count { text = s }
        text = Presentation.captionText(text, language: settings.language)     // FUN_1120_03d2 (10e8:0529); the length counts the copy in the language in force
        func num(_ k: Int) -> Int? { if args.count > k, case .int(let i) = args[k], i != 0 { return i }; return nil }
        let colour = num(1) ?? 0x75
        let volume = args.count > 3 ? (num(2) ?? 0xff) : 0xff
        let idx = args.first.flatMap(soundIndex)
        let n = idx.map { soundBank.samples[$0].length } ?? 0     // ASSUMPTION: unresolved sound = sample length 0
        if live, let voice = subtitleVoice { stopSound(voice) }     // the new subtitle replaces the old one and stops its voice (10e8:08a4)
        subtitleVoice = idx.map { playSound($0, volume: volume, pitch: 0, loop: false, priority: 2) }
        if live {
            vm.finish(vm.process(curSubtitle!.handle)!)
            let i = curSubtitle!.index
            subtitleLog[i].end = vm.tick
        }
        let ticks = fixedTicks ?? (n * 30 / 11025 + text.unicodeScalars.count)     // engine: len*60/11025 + 2*strlen in 1/60 s (11025 even for 11111 Hz)
        let h = vm.timedHandle(ticks: ticks)
        curSubtitle = (h, subtitleLog.count)
        subtitleLog.append(SubtitleEvent(tick: vm.tick, handle: h, colour: colour, text: text, end: vm.tick + max(ticks, 1)))
        return h
    }

    func stopSound(_ handle: Int) {
        guard let vm, let p = vm.process(handle), !p.done else { return }
        vm.finish(p)
        if soundHandles.contains(where: { $0.handle == handle }) { soundStops.append((vm.tick, handle)) }
    }
}

extension ScriptValue {
    var stringValue: String? { if case .str(let s) = self { return s }; return nil }
}
