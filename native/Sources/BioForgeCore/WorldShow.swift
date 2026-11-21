// Show: the FLIC statements and functions STARTFLIC (10d0:7761 -> 1140:0c6a), STOPFLIC (782f -> 0ecc), SETFLICRATE (7042 -> 0dfc), FLICLOOP (2f64),
// PLAYFLIC (10d8:3950) and RUNFLIC (10d8:3a40 -> 10c8:0636), FREEZE / THAW (10d0:3314 / 84c4 -> 10c8:04de / 05b2), the front-end statements MENU /
// UNMENU (10d0:5396 / 539d), ADDKEY (10d0:025f), EXIT (10d0:2835) and the functions WASALTPRESSED (10d8:3cc1), CREDITSSTATE (10d8:1110) and
// GETOPTDATA (10d8:267f -> 10f0:0651), plus the CAPTUREKEYBOARD hook (10d0:1823 / 1138:1da6). JUMPON (10d0:4024) lives in ScriptVM.swift. Port of
// re/interp/show.py (the oracle, which also holds the decoded rules and the ASSUMPTIONs).
//
// One global flic object (DS:6538) is open between STARTFLIC and STOPFLIC; while it is, the frame renderer 1100:0580 draws it INSTEAD of the world
// (World.render(into:)). `stepShow` is the once-per-render step (World.step, before the frozen check: the flic clock [8334] is the real, never
// paused one, 2 units of 60 Hz per VM tick).
//
// Timed mode (1140:077b): the first render after RUNFLIC sets last = clock - interval, so the first frame is due at once; at most one frame per
// render, drawn when last + interval <= clock (last += interval, index++); finished at the render where the next frame is due and index >= count or
// (limit != 0 and index >= limit): limit L is exclusive. Var mode (a live variable): the interval is ignored; frames are drawn until index > variable,
// never backwards. NOT PORTED: the engine's catch-up (the clock is set back when more than one frame is due per render), which with one render per
// tick can only happen at interval 1 in timed mode (not shipped). A RUNFLIC scene is a timeline process (stamps SS:TT = SS * 30 + TT ticks from the
// RUNFLIC tick) that ends when no flic is open or the flic has finished (10c8:081b step 2).
import Foundation

/// The open flic (fields +0x34 count, +0x102 index, +0x160 last, +0x164 interval, +0x170 running, +0x171 limit, +0x173 var, +0x17e mark).
final class FlicPlayer {
    let name: String
    let data: [UInt8]
    var decoder: FlicDecoder
    var interval = 2                       // 60 Hz units per frame after STARTFLIC (30 fps)
    var last: Int?
    var index = 0, limit = 0
    var variable: String?
    var running = true
    var armed = false                      // nothing is drawn until the first RUNFLIC (ASSUMPTION: the brief's reading of 1.1 / 12)
    var mark: Int?
    var frame: FlicFrame?                  // the frame on screen (the last one drawn), nil = nothing drawn yet
    var count: Int { decoder.frameCount }

    init(name: String, data: [UInt8]) throws { self.name = name; self.data = data; decoder = try FlicDecoder(data: data) }

    /// Decode and show the next frame (1140:0603); frames are decoded lazily, one at a time, in order.
    func draw() {
        if let f = try? decoder.nextFrame() { frame = f }
        index += 1
    }

    /// FLICLOOP: back to frame `i` (1140:0bc5 restores the frame index and file offset); the frames before it are decoded again.
    func rewind(_ i: Int) {
        guard let d = try? FlicDecoder(data: data) else { return }
        decoder = d; index = 0
        for _ in 0..<i { draw() }
    }
}

struct ShowState {
    var flic: FlicPlayer?
    var clock = 0                          // [8334]
    var frozen = false                     // [50be] as FREEZE sets it
    var freezeMarks: [ScriptProcess] = []  // the processes FREEZE suspended (the mark buffer DS:30b8)
    var freezeTick = 0
    var frozenSince: Int?                  // the VM tick the game clock stopped at (the outermost FREEZE), nil while it runs
    var frozenTicks = 0                    // VM ticks the game clock has been stopped for, in total
    var keyHook: String?                   // the CAPTUREKEYBOARD block name (the hook process DS:6530); nil = captured without a block
    var keyHookProc: ScriptProcess?
    var keyHookOwner = "level"
    var keyQueue: [(scan: Int, mods: Int)] = []     // ADDKEY events not delivered yet
    var installOpt: [String: String]?
}

extension World {
    static let showStmts: Set<String> = ["STARTFLIC", "STOPFLIC", "SETFLICRATE", "FLICLOOP", "FREEZE", "THAW", "MENU", "UNMENU", "ADDKEY"]
    static let showFuncs: Set<String> = ["RUNFLIC", "PLAYFLIC", "WASALTPRESSED", "CREDITSSTATE", "GETOPTDATA"]
    static let flicInterval = 2            // 60 Hz units per frame after STARTFLIC
    static let showClockPerTick = 2        // [8334] 60 Hz units per VM tick (the timeline parser's relation, 10c8:0172)
    static let altMods = 0xc0              // DEFINES.DEF _EITHER_ALT_PRESSED (10d8:3cc1 tests & 0xC0)
    static let saveScan = 0x1f             // the one key the normal handler still answers while the keyboard is captured (not with Alt)

    public var flicOpen: Bool { show.flic != nil }
    public var isFrozen: Bool { show.frozen }

    func cmdShow(_ name: String, _ args: [ScriptValue], _ proc: ScriptProcess) {
        let (words, nums) = wordsAndNumbers(args)
        switch name {
        case "STARTFLIC": startFlic(words.first ?? "")
        case "STOPFLIC": show.flic = nil                       // 1140:0ecc: the palette comes back (the world's), safe when nothing is open
        case "SETFLICRATE":
            if let f = show.flic { f.interval = (nums.first ?? 0) & 0xffff }       // u16, no re-base: the next frame is due at last + n
        case "FLICLOOP":
            if let f = show.flic {
                if words.first == "MARK" { f.mark = f.index } else if let m = f.mark { f.rewind(m) }
            }
        case "FREEZE": cmdFreeze(proc)
        case "THAW": cmdThaw()
        case "ADDKEY":
            var mods = 0
            for n in nums.dropFirst().prefix(5) { mods |= n & 0xff }                 // (byte)(arg1 | ... | arg6); the unspecified slots are 0
            show.keyQueue.append(((nums.first ?? 0) & 0xff, mods))
        default: break                                         // MENU / UNMENU (10d0:5396 / 539d) are stubs in the release exe
        }
    }

    /// `STARTFLIC <name>` (1140:0c6a): closes any open flic, opens SHOW/<NAME>.SHO (interval 2, index 0, no limit, no variable) and draws nothing:
    /// until the first RUNFLIC frame the screen shows black (ASSUMPTION: the display pages are cleared, 10e8:1d5e, to colour 0 of a black palette).
    /// A missing or unreadable file warns and leaves no flic (the open failure path of 11a8:083b is not traced: ASSUMPTION).
    func startFlic(_ name: String) {
        show.flic = nil
        do { show.flic = try FlicPlayer(name: name.uppercased(), data: try game.read("SHOW/\(name.uppercased()).SHO")) }
        catch { warn("STARTFLIC \(name): cannot open SHOW/\(name.uppercased()).SHO") }
    }

    // MARK: RUNFLIC and the per-render step

    /// `RUNFLIC <block> [limit] [livevar]` (10d8:3a40 -> 10c8:0636). limit: the exclusive end frame, 0 = none; livevar (args[3], the VM passes its
    /// name): var mode. It resets the flic's frame timer, starts the scene block as a process whose timeline origin is this tick and returns its
    /// handle (valid until the process ends: block end, or no flic / a finished flic). An unknown block: a handle that dies on its next update
    /// (INFERRED: the task has no code). Without an open flic the scene ends at its first update without running anything.
    func cmdRunFlic(_ proc: ScriptProcess, _ args: [ScriptValue]) -> Int {
        let (words, nums) = wordsAndNumbers(args)
        let block = (words.first ?? "").uppercased()
        if let f = show.flic {
            f.limit = (nums.first ?? 0) & 0xffff
            f.variable = words.count > 1 ? words[1].lowercased() : nil
            f.last = nil; f.running = true; f.armed = true     // 0f6f -> 0c1f: +0x160 = 0, the flic ticks again
        }
        guard let vm else { return 0 }
        guard vm.blocks[block] != nil else { return vm.timedHandle(ticks: 1) }
        guard let p = vm.spawn(.str(block), ctx: ScriptContext(curFig: proc.curFig, curItem: proc.curItem, owner: proc.owner), run: false, owner: proc.owner) else { return 0 }
        p.scene = true
        if show.flic != nil { vm.run(p) }
        return p.handle
    }

    /// Once per render: deliver ADDKEY events, advance the flic (1140:077b) and end the scenes of a flic that is gone.
    func stepShow() {
        drainKeys()
        if let f = show.flic {
            show.clock += Self.showClockPerTick
            if f.running && f.armed { advanceFlic(f) }
        }
        if let vm, !sceneAlive {
            for p in vm.processes where p.scene { vm.finish(p) }       // ASSUMPTION: the engine's "dies on its next update" (<= 1 tick) is modelled as 0 ticks
        }
    }

    private func advanceFlic(_ f: FlicPlayer) {
        if let name = f.variable {
            var value = 0
            if case .int(let v)? = vm?.globals[name] { value = v }
            while f.index <= value && f.index < f.count && !(f.limit != 0 && f.index >= f.limit) { f.draw() }
            if f.limit != 0 && f.index >= f.limit { f.running = false }
            return
        }
        if f.last == nil { f.last = show.clock - f.interval }
        if f.last! + f.interval > show.clock { return }
        if f.index >= f.count || (f.limit != 0 && f.index >= f.limit) { f.running = false; return }
        f.draw()
        f.last! += f.interval
    }

    /// The flic frame as the pipeline's 320x200 indexed frame: 6-bit DAC values expanded c * 255 / 63 as every palette; black before the first frame.
    func renderFlic(_ f: FlicPlayer, into fb: inout Framebuffer) {
        fb.pixels = [UInt8](repeating: 0, count: Framebuffer.width * Framebuffer.height)
        guard let frame = f.frame else { fb.palette = [UInt8](repeating: 0, count: 768); return }
        fb.palette = frame.palette.map { UInt8((Int($0) >> 2) * 255 / 63) }
        let w = f.decoder.width, h = f.decoder.height
        for y in 0..<min(Framebuffer.height, h) {
            for x in 0..<min(Framebuffer.width, w) { fb.pixels[y * Framebuffer.width + x] = frame.pixels[y * w + x] }
        }
    }

    // MARK: FREEZE / THAW

    /// 10c8:04de: suspend every existing script process except the caller and the ones already suspended; ASSUMPTION: the native handles (sound,
    /// subtitle, Fade, missile: no script block) are the engine's type < 0x100 / 0x110 kernel tasks and keep running. Sets [50be], which stops
    /// World.step (figures, physics, camera selection) but not the VM tick, so processes made afterwards (RUNFLIC scenes, the key hook, FADE) run.
    /// A nested FREEZE replaces the mark buffer.
    func cmdFreeze(_ proc: ScriptProcess) {
        var marks: [ScriptProcess] = []
        for p in vm?.processes ?? [] where p !== proc && !p.suspended && p.gen == nil && !p.done {
            p.suspended = true
            marks.append(p)
        }
        show.freezeMarks = marks; show.frozen = true; show.freezeTick = vm?.tick ?? 0
        if show.frozenSince == nil { show.frozenSince = show.freezeTick }
    }

    /// 10c8:05b2: resume exactly the marked processes and clear [50be]. ASSUMPTION (INFERRED: WAIT and the timeline clocks run on the pausable game
    /// clock [8330]): a resumed process's pending wake and timeline origin move later by the frozen duration.
    func cmdThaw() {
        let now = vm?.tick ?? 0, shift = now - show.freezeTick
        for p in show.freezeMarks where !p.done && p.suspended {
            p.suspended = false
            if p.wake > show.freezeTick { p.wake += shift }         // a pending timer; a process that was only waiting on another has none
            if let o = p.origin { p.origin = o + shift }
        }
        show.freezeMarks = []; show.frozen = false
        if let since = show.frozenSince { show.frozenTicks += now - since; show.frozenSince = nil }
    }

    /// The game clock [8330] in VM ticks (2 clock units each): the scheduler's tick minus the ticks FREEZE has stopped it for ([50be] set, FREEZE
    /// 10c8:04de .. THAW 10c8:05b2; the options dialog stops the VM tick itself). Read by the journal / log award stamps and `%time%`
    /// (addLogEntry, the monitor clock) and the attack-combo timer [2958]; the scheduler's tick and the flic / scene clock [8334] are not it.
    var gameTick: Int { (show.frozenSince ?? (vm?.tick ?? 0)) - show.frozenTicks }

    // MARK: keyboard: ADDKEY, the CAPTUREKEYBOARD hook and keyEvent

    func drainKeys() {
        let queue = show.keyQueue
        show.keyQueue = []
        recorder?.depth += 1; defer { recorder?.depth -= 1 }       // ADDKEY keys come from the script: a replay queues them itself
        for k in queue { keyEvent(scan: k.scan, mods: k.mods) }
    }

    /// One key press (a real one while the keyboard is captured, an ADDKEY one always). Captured (1138:1da6 from 10e8:11e3): the hook block runs at
    /// once with ~0 = scan code, ~1 = modifiers, ~2 = mouse (0), a scan code of 0 does nothing; the normal handler is bypassed except scan 0x1f
    /// without Alt (CANNOT_SAVE) and not with a flic open. Not captured: Esc answers an open dialog / monitor, any other key is a press and release
    /// through keyDown.
    public func keyEvent(scan: Int, mods: Int = 0) {
        guard scan != 0 else { return }
        recorder?.enter("keyEvent", frames, [scan, mods]); defer { recorder?.leave() }
        if keyboardCaptured {
            if !keysCaptured.contains(scan) { keysCaptured.append(scan) }
            runKeyHook(scan, mods)
            if scan == Self.saveScan && mods & Self.altMods == 0 && show.flic == nil { keyDown(scan, mods: mods); keyUp(scan) }
        } else if scan == 1 && isOptionsOpen {
            optionKey("ESCAPE")
        } else if scan == 1 && monitor != nil {
            monitorKey("ESCAPE")
        } else {
            keyDown(scan, mods: mods); keyUp(scan)
        }
    }

    private func runKeyHook(_ scan: Int, _ mods: Int) {
        guard let vm, let hook = show.keyHook else { return }
        if let old = show.keyHookProc, !old.done { vm.finish(old) }         // the hook process is rewound to the block start
        show.keyHookProc = vm.spawn(.str(hook), args: [.int(scan), .int(mods), .int(0)],
                                    ctx: ScriptContext(curFig: playerName, curItem: nil, owner: show.keyHookOwner))
    }

    /// `CAPTUREKEYBOARD <block>` (10d0:1823): already captured warns (error 0xd1) and changes nothing. The hook is the named 3-parameter block;
    /// ASSUMPTION: a block the VM does not have (or none) captures without a hook, and the parameter count is not checked (error 0xcf is not
    /// ported: the parser keeps no block signature).
    func cmdCaptureKeyboard(_ proc: ScriptProcess, _ args: [ScriptValue]) {
        if keyboardCaptured { warn("CAPTUREKEYBOARD: the keyboard is already captured (error 0xd1)"); return }
        let words = wordsAndNumbers(args).words
        keyboardCaptured = true
        show.keyHook = words.first.map { $0.uppercased() }.flatMap { vm?.blocks[$0] != nil ? $0 : nil }
        show.keyHookOwner = proc.owner
    }

    /// `RELEASEKEYBOARD` (10d0:677d -> 1138:1e5f) destroys the hook process.
    func cmdReleaseKeyboard() {
        keyboardCaptured = false; show.keyHook = nil
        if let p = show.keyHookProc { vm?.finish(p) }
        show.keyHookProc = nil
    }

    // MARK: functions

    func cmdShowFunc(_ name: String, _ args: [ScriptValue], _ proc: ScriptProcess) -> Int {
        let (words, nums) = wordsAndNumbers(args)
        switch name {
        case "RUNFLIC": return cmdRunFlic(proc, args)
        case "WASALTPRESSED": return (nums.first ?? 0) & Self.altMods != 0 ? 1 : 0
        case "GETOPTDATA": return installOption(words.first ?? "")
        case "CREDITSSTATE": return creditsState
        default: return 0       // PLAYFLIC is a stub (returns 0, no flic action)
        }
    }

    /// FUN_10f0_0651: the INSTALL.OPT value of `key` (case-insensitive: INFERRED): a value starting with a digit gives its decimal integer, anything
    /// else the code of its first character (not upper-cased); a missing key gives 0. `language` is the setting in force (INTRO.SCP picks INTRO / INTROF / INTROG).
    func installOption(_ key: String) -> Int {
        if key.lowercased() == "language" { return Int(settings.language.unicodeScalars.first!.value) }      // the setting in force; INSTALL.OPT seeds it
        if show.installOpt == nil {
            show.installOpt = game.resolve("INSTALL.OPT").flatMap { try? Data(contentsOf: $0) }
                .map { Settings.parseInstallOpt(String(decoding: $0, as: UTF8.self)) } ?? [:]
        }
        let value = (show.installOpt?[key.lowercased()] ?? "").trimmingCharacters(in: CharacterSet(charactersIn: "\""))
        guard let token = value.split(whereSeparator: { $0 == "," || $0.isWhitespace }).first, let first = token.unicodeScalars.first else { return 0 }
        if first.properties.numericType != nil && first.isASCII { return Int(token.prefix { $0.isASCII && $0.isNumber }) ?? 0 }
        return Int(first.value)
    }
}
