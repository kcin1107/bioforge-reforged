// Presentation: what the player sees on top of the simulation. DEBUG / DEBUGINFO (10d0:2445 / 10d0:25cf), CHANGEPALETTE (10d0:1a43), the FADE
// function (10d8:17e6), RUMBLE (10d0:6dc6), CAPTION (10d0:16cb) and the monitor pointer set-ups SET_PTR_MOVEMENT (10d0:72b2) and
// SET_PTR_PRESS_TIME (10d0:72ef). Port of re/interp/presentation.py (the oracle, which also holds the decoded rules and the ASSUMPTIONs).
//
// DEBUG / DEBUGINFO are release-build no-ops (the only consumer of their trace mode, 10c0:24dc, is an empty `return`): they are only listed as
// modelled. Palette: the engine keeps ONE additive offset per channel (DS:c672/4/6) = the gamma offset (1100:0e6f) + the CHANGEPALETTE argument
// (10e8:18c1), applied to every one of the 256 entries on the 6-bit VGA values and clamped 0...63 (10e8:16bb). A Fade process scales the source
// palette in 8.8 fixed point before the offset is added (1148:1de8). `Presentation.palette` is that whole step, on the 8-bit channels the
// pipeline stores (c * 255 / 63); the app calls `World.applyPresentation(to:)` for the player-facing frame.
import Foundation

/// What the DAC shows besides the normal palette: all zero (FADE HIDE, no offset) or the Fade process's 8.8 scale (0...256).
public enum PaletteFade: Equatable, Sendable { case black, scale(Int) }

struct PresentationState {
    var palState = 0                 // DS:49bd: 0 normal, 1 fading down, 2 black, 3 fading up
    var fade: PaletteFade?           // nil = normal
    var installed: [Int]?            // the raw 6-bit palette last installed (c368+2), for World.paletteCut
    var fadeHandle: Int?             // the newest Fade process (DS:662a); only it writes the palette
    var cp = [0, 0, 0]               // CHANGEPALETTE offsets (DS:c672/4/6 minus the gamma offset)
    var cpTicks = 0                  // its duration d in 30 Hz ticks: 0 / negative persistent
    var cpAge: Int?                  // renders since it was latched, nil until the first one
    var rumbleAmp = 0, rumbleX = 0, rumbleY = 0, rumbleVX = 0, rumbleVY = 0, rumbleXP = 0, rumbleYP = 0     // DS:6576..657c
    var rumbleSeed = 0
}

public enum Presentation {
    static let paletteCutLimit = 12               // 10e8:1dcc: |dR|+|dG|+|dB| above this on one of entries 0...254 blacks the DAC for the cut
    static let fadeDefault = 20                   // FADE UP / DOWN without a number (3c74: duration 0 -> 0x14)
    static let ticksPerCharacter = 7              // RED.OPT TicksPerCharacter=7 ([2d52]); 60 Hz ticks per caption character
    static let captionMax = 0x15f                 // 10b0:0e5a drops a caption of this many characters or more
    static let rumbleMax = 127                    // 1 ... 127 is the random shake; 0xff (-1) is the fixed MOVE offset (1140:1313)
    static let rumbleLCG = 65539                  // ASSUMPTION: a dedicated LCG seed*65539+1 (FUN_11c8:197e), seeded 0; the engine's shared stream is not recovered

    static func s16(_ v: Int) -> Int { Int(Int16(truncatingIfNeeded: v)) }
    static func s8(_ v: Int) -> Int { Int(Int8(truncatingIfNeeded: v)) }

    /// 256 8-bit values after: back to 6 bits (as Gamma.lut), scale by the fade (8.8, nil = 256), add `offset`, clamp 0...63, expand.
    static func channelLUT(offset: Int, fade: PaletteFade?) -> [UInt8] {
        (0..<256).map { c in
            if fade == .black { return 0 }
            let src = (c * 63 + 254) / 255
            var base = src
            if case .scale(let s)? = fade { base = (src * s) >> 8 }
            return UInt8(min(63, max(0, base + offset)) * 255 / 63)
        }
    }

    /// The presented 768-byte palette for a source one (8-bit channels). gamma = the setting (0...100); cp = the CHANGEPALETTE offsets (r, g, b)
    /// in 6-bit units; fade = nil (normal), `.black` (FADE HIDE: all zero, no offset) or `.scale` (the Fade process's 8.8 scale; scale 0 keeps
    /// the offset, so with gamma 50 the "black" is 6,6,6). With cp zero and no fade it is `Gamma.apply`.
    public static func palette(_ pal: [UInt8], gamma: Int, cp: [Int] = [0, 0, 0], fade: PaletteFade? = nil) -> [UInt8] {
        let g = Gamma.offset(gamma)
        let luts = (0..<3).map { channelLUT(offset: g + cp[$0], fade: fade) }
        return pal.enumerated().map { luts[$0.offset % 3][Int($0.element)] }
    }

    /// 1140:0ff0: the page moved by (+x, +y) pixels. Rows revealed at the top (y > 0) / bottom (y < 0) take `fill`; columns revealed at the left /
    /// right keep their old pixels. Rows alternate between x and xp in pairs: for y >= 0 the source rows h-1-y, h-3-y ... use x and the ones
    /// between use xp; for y < 0 the rows -y, -y+2 ... use x. (The original leaves 1-2 edge rows stale; not ported.)
    public static func shiftFrame(_ a: [UInt8], width w: Int, height h: Int, x: Int, y: Int, xp: Int, fill: UInt8) -> [UInt8] {
        var out = a
        if y > 0 { for r in 0..<min(y, h) { for c in 0..<w { out[r * w + c] = fill } } }
        else if y < 0 { for r in max(h + y, 0)..<h { for c in 0..<w { out[r * w + c] = fill } } }
        let first = y >= 0 ? (h - 1 - y) % 2 : (-y) % 2
        for d in 0..<h {
            let s = d - y
            if s < 0 || s >= h { continue }
            let dx = s % 2 == first ? x : xp
            if dx >= 0 && dx < w { for c in dx..<w { out[d * w + c] = a[s * w + c - dx] } }
            else if dx < 0 && -dx < w { for c in 0..<(w + dx) { out[d * w + c] = a[s * w + c - dx] } }
        }
        return out
    }

    /// The CAPTION printf (FUN_1000_586c with the 10 s32 arguments flattened to 20 little-endian 16-bit words, missing ones 0): %d %i %u %x %X %c
    /// take one word, %l? two, %% none. A second %d reads the HIGH word of the first argument, not the second argument.
    public static func sprintf16(_ fmt: String, _ nums: [Int]) -> String {
        var words: [Int] = []
        for k in 0..<10 {
            let v = k < nums.count ? nums[k] : 0
            words += [v & 0xffff, (v >> 16) & 0xffff]
        }
        var pos = 0
        func take(_ n: Int) -> Int {
            var v = 0
            for i in 0..<n { v |= (pos < words.count ? words[pos] : 0) << (16 * i); pos += 1 }
            return v
        }
        let chars = Array(fmt)
        var out = "", i = 0
        while i < chars.count {
            guard chars[i] == "%" else { out.append(chars[i]); i += 1; continue }
            var j = i + 1, flags = "", width = "", long = false
            while j < chars.count, chars[j] == "-" || chars[j] == "0" { flags.append(chars[j]); j += 1 }
            while j < chars.count, chars[j].isASCII, chars[j].isNumber { width.append(chars[j]); j += 1 }
            if j < chars.count, chars[j] == "l" { long = true; j += 1 }
            guard j < chars.count, "diuxXc%".contains(chars[j]) else { out.append("%"); i += 1; continue }
            let conv = chars[j]
            i = j + 1
            if conv == "%" { out.append("%"); continue }
            let bits = long ? 32 : 16
            var v = take(long ? 2 : 1)
            if (conv == "d" || conv == "i") && v >= 1 << (bits - 1) { v -= 1 << bits }
            var text: String
            switch conv {
            case "c": text = String(Character(UnicodeScalar(UInt8(v & 0xff))))
            case "x": text = String(v, radix: 16)
            case "X": text = String(v, radix: 16, uppercase: true)
            default: text = String(v)
            }
            let n = Int(width) ?? 0, pad = max(0, n - text.unicodeScalars.count)
            if flags.contains("-") { text += String(repeating: " ", count: pad) }
            else { text = String(repeating: flags.contains("0") && conv != "c" ? "0" : " ", count: pad) + text }
            out += text
        }
        return out
    }

    /// FUN_1120_03d2: the segment after "/<language>", else after "/E", else the whole string (a leading "/" + one character, as "/!", is skipped),
    /// cut at the next "/".
    public static func captionText(_ text: String, language: String = "E") -> String {
        var t = text
        if let r = ["/" + language, "/E"].lazy.compactMap({ text.range(of: $0) }).first { t = String(text[r.upperBound...]) }
        else if text.hasPrefix("/") { t = String(text.dropFirst(2)) }
        return t.components(separatedBy: "/")[0]
    }
}

extension World {
    static let presentationStmts: Set<String> = ["CHANGEPALETTE", "RUMBLE", "CAPTION", "SET_PTR_MOVEMENT", "SET_PTR_PRESS_TIME"]

    func wordsAndNumbers(_ args: [ScriptValue]) -> (words: [String], nums: [Int]) {
        let flat = args.flatMap { v -> [ScriptValue] in if case .list(let l) = v { return l }; return [v] }
        return (flat.compactMap { v -> String? in if case .str(let s) = v { return s }; return nil },
                flat.compactMap { v -> Int? in if case .int(let i) = v { return i }; return nil })
    }

    func cmdPresentation(_ name: String, _ args: [ScriptValue], _ proc: ScriptProcess) {
        let (words, nums) = wordsAndNumbers(args)
        func num(_ k: Int) -> Int { k < nums.count ? nums[k] : 0 }
        switch name {
        case "CHANGEPALETTE": cmdChangePalette((0..<4).map { Presentation.s16(num($0)) })
        case "RUMBLE": cmdRumble(words, nums)
        case "CAPTION": cmdCaption(proc, words, nums)
        default:                                    // SET_PTR_*: nothing before MON_START (no monitor running)
            guard let monitor else { return }
            if name == "SET_PTR_MOVEMENT" { monitor.pointerMovement = (num(0) & 0xffff, num(1) & 0xffff) }
            else { monitor.pointerPressTime = (num(0) & 0xffff, num(1) & 0xffff, num(2) & 0xffff) }
        }
    }

    // MARK: CHANGEPALETTE

    /// `CHANGEPALETTE r g b d` (10d0:1a43 -> 10e8:1427 -> 18c1): signed additive offsets in 6-bit units that REPLACE any earlier one. d is in 30 Hz
    /// ticks: <= 0 persistent; d >= 1 reverts after d presented frames, counted from the first render after the statement (d == 1, the "flash":
    /// the engine busy-waits 50 ms at the next render; ASSUMPTION: the ports show exactly one tinted frame). The render is `stepPresentation`,
    /// the once-per-tick step. Never blocks, not saved.
    func cmdChangePalette(_ a: [Int]) {
        presentation.cp = Array(a[0..<3]); presentation.cpTicks = a[3]; presentation.cpAge = nil
    }

    /// Setting the gamma (FUN_1100_0e6f) calls 18c1(0, 0, 0).
    func cancelChangePalette() { presentation.cp = [0, 0, 0]; presentation.cpTicks = 0; presentation.cpAge = nil }

    /// 10e8:145c at the top of the per-frame render (game not paused): the CHANGEPALETTE timer. ASSUMPTION: the ports' per-tick hook is World.step
    /// (after the tick's scripts, before the frame is drawn).
    func stepPresentation() {
        guard presentation.cpTicks > 0 else { return }
        presentation.cpAge = (presentation.cpAge ?? -1) + 1
        if presentation.cpAge! >= presentation.cpTicks { cancelChangePalette() }
    }

    // MARK: FADE

    /// `FADE HIDE|SHOW|UP [n]|DOWN [n]` (10d8:17e6 -> 10c0:3c74), n in 30 Hz steps (default 20). HIDE: all-zero palette, state 2; SHOW: normal, state 0;
    /// both return 0. UP is a no-op (0) in states 0 and 3, DOWN in 1 and 2; otherwise the state becomes 3 / 1 and a Fade process (class "Fade",
    /// 1148:1ca5; handle returned, valid for n ticks) steps once per tick, the first on the tick after the statement (ASSUMPTION): k += 1,
    /// scale = (k << 8) / n (UP) or ((n - k) << 8) / n (DOWN), presented = clamp((src * scale >> 8) + offsets). Only the newest process writes (and
    /// an UP not in state 2 / a DOWN always, 1148:1de8); at k == n UP restores the normal palette (state 0) and DOWN leaves the scale-0 palette in
    /// state 2. A missing or unknown word warns (error 0x69) and returns 0.
    func cmdFade(_ proc: ScriptProcess, _ args: [ScriptValue]) -> Int {
        let (words, nums) = wordsAndNumbers(args)
        let word = words.first?.uppercased() ?? ""
        switch word {
        case "HIDE": presentation.fade = .black; presentation.palState = 2
        case "SHOW": presentation.fade = nil; presentation.palState = 0
        case "UP", "DOWN":
            let n = ((nums.first ?? 0) & 0xffff) != 0 ? (nums.first! & 0xffff) : Presentation.fadeDefault
            let down = word == "DOWN"
            guard let vm, !(down ? [1, 2] : [0, 3]).contains(presentation.palState) else { return 0 }
            presentation.palState = down ? 1 : 3
            let h = vm.nativeHandle("Fade")                          // a kernel task: LOADLEVEL's kill walk (10b0:13fb) ends it like any other
            presentation.fadeHandle = h
            var k = 0
            let p = vm.process(h)!
            p.gen = { [unowned self] in                                // the handle made by nativeHandle runs this instead of sleeping forever
                k += 1
                let scale = down ? ((n - k) << 8) / n : (k << 8) / n
                if presentation.fadeHandle == h && (down || presentation.palState != 2) { presentation.fade = .scale(scale) }     // 1148:1de8: the DAC write condition
                if k == n {
                    if down { presentation.palState = 2 } else { presentation.fade = nil; presentation.palState = 0 }
                    return nil
                }
                return 1
            }
            p.wake = vm.tick + 1
            return h
        default: warn("FADE \(word.isEmpty ? "(no word)" : word): needs HIDE, SHOW, UP or DOWN (error 0x69)")
        }
        return 0
    }

    // MARK: RUMBLE

    /// `RUMBLE` / `RUMBLE 0` stop (zero amplitude, x, y, vx, vy); `RUMBLE n` sets the amplitude (s8) and leaves the offsets; `RUMBLE MOVE a b c d`
    /// sets amplitude 0xff with x = a, y = b, xp = c, yp = d (s8; all four zero only clears the amplitude) (10d0:6dc6, 1140:12d5 / 133b / 134a).
    /// Presentation only.
    func cmdRumble(_ words: [String], _ nums: [Int]) {
        func num(_ k: Int) -> Int { k < nums.count ? nums[k] : 0 }
        if words.first?.uppercased() == "MOVE" {
            let a = (0..<4).map { num($0) & 0xffff }
            if a.allSatisfy({ $0 == 0 }) { presentation.rumbleAmp = 0 }
            else {
                presentation.rumbleAmp = -1
                (presentation.rumbleX, presentation.rumbleY, presentation.rumbleXP, presentation.rumbleYP) = (Presentation.s8(a[0]), Presentation.s8(a[1]), Presentation.s8(a[2]), Presentation.s8(a[3]))
            }
        } else if num(0) & 0xffffffff == 0 {
            presentation.rumbleAmp = 0; presentation.rumbleX = 0; presentation.rumbleY = 0; presentation.rumbleVX = 0; presentation.rumbleVY = 0
        } else {
            presentation.rumbleAmp = Presentation.s8(num(0))
        }
    }

    private func rumbleRand2() -> Int {
        presentation.rumbleSeed = (presentation.rumbleSeed * Presentation.rumbleLCG + 1) & 0xffffffff
        return (presentation.rumbleSeed >> 16) & 1
    }

    /// 1140:11cf, once per presented frame while 1 <= amplitude <= 127: the previous x is kept, a spring pulls the velocities toward 0, +-1 random
    /// per axis (vx's first), velocities are clamped to +-amplitude, then x += vx, y += vy.
    func rumbleStep() {
        let a = presentation.rumbleAmp
        guard a >= 1 && a <= Presentation.rumbleMax else { return }
        presentation.rumbleXP = presentation.rumbleX; presentation.rumbleYP = presentation.rumbleY
        var vx = presentation.rumbleVX, vy = presentation.rumbleVY
        let x = presentation.rumbleX, y = presentation.rumbleY
        vx += x < 0 ? (-x) >> 1 : -(x >> 1)
        vy += y < 0 ? (-y) >> 1 : -(y >> 1)
        vx += rumbleRand2() == 0 ? -1 : 1
        vy += rumbleRand2() == 0 ? -1 : 1
        presentation.rumbleVX = max(-a, min(a, vx)); presentation.rumbleVY = max(-a, min(a, vy))
        presentation.rumbleX += presentation.rumbleVX; presentation.rumbleY += presentation.rumbleVY
    }

    /// The player-facing frame (the app's redrawGame): 1140:1313 shifts the page by the current RUMBLE offsets, then advances the shake (skipped
    /// while paused); then the palette step (gamma, CHANGEPALETTE, fade) replaces `fb.palette`. ASSUMPTION: the page's black index ([7a7e]) is the
    /// palette entry nearest black; the HUD and captions shift with the scene.
    public func applyPresentation(to fb: inout Framebuffer) {
        var none: HiResFrame? = nil
        applyPresentation(to: &fb, hiRes: &none)
    }

    /// The same, also shifting View > High-Resolution Art's 2x picture by the same RUMBLE offsets; the shake still advances once.
    public func applyPresentation(to fb: inout Framebuffer, hiRes: inout HiResFrame?) {
        if !paused && !show.frozen && presentation.rumbleAmp != 0 {
            var black = 0, best = Int.max
            for i in 0..<256 {
                let d = (0..<3).reduce(0) { $0 + Int(fb.palette[i * 3 + $1]) * Int(fb.palette[i * 3 + $1]) }
                if d < best { best = d; black = i }
            }
            fb.pixels = Presentation.shiftFrame(fb.pixels, width: Framebuffer.width, height: Framebuffer.height, x: presentation.rumbleX,
                                                y: presentation.rumbleY, xp: presentation.rumbleXP, fill: UInt8(black))
            hiRes?.shift(x: presentation.rumbleX, y: presentation.rumbleY, xp: presentation.rumbleXP, fill: UInt8(black))
            rumbleStep()
        }
        // 10e8:1dcc: a cut to a very different palette is shown black once; the DAC is black only while the frame is blitted (see paletteCut)
        fb.palette = paletteCut(fb.palette) ? [UInt8](repeating: 0, count: fb.palette.count)
                                            : Presentation.palette(fb.palette, gamma: gamma, cp: presentation.cp, fade: presentation.fade)
    }

    /// 10e8:1dcc, once per presented frame: `source` is the screen's palette (8-bit channels, c * 255 / 63 of the raw 6-bit values), before
    /// gamma, CHANGEPALETTE and fade. With no fade running, down or black (DS:49bd == 0) and a source that differs from the one last installed
    /// (c368+2: the pending palette 17d8 installed; one that equals it is no write) by more than 12 in |dR|+|dG|+|dB| on any entry 0...254, the
    /// original sets the DAC black (183d), draws the frame and installs the new palette (17d8) within that one call. -> true when this presented
    /// frame is that black one. The installed palette follows the source on every frame with no fade; during a fade it stays, so the compare
    /// runs against it when the fade ends (the original leaves the pending palette until 49bd is 0). ASSUMPTION: the blit is the whole black
    /// time, so the nearest whole-frame equivalent is one black presented frame, display only.
    func paletteCut(_ source: [UInt8]) -> Bool {
        guard presentation.palState == 0, source.count >= 768 else { return false }
        let raw = source.prefix(768).map { (Int($0) * 63 + 127) / 255 }
        defer { presentation.installed = raw }
        guard let old = presentation.installed else { return false }
        for i in 0..<255 {
            let d = abs(raw[3 * i] - old[3 * i]) + abs(raw[3 * i + 1] - old[3 * i + 1]) + abs(raw[3 * i + 2] - old[3 * i + 2])
            if d > Presentation.paletteCutLimit { return true }
        }
        return false
    }

    // MARK: CAPTION

    /// `CAPTION "fmt" [numbers] [PAUSE]` (10d0:16cb -> 10b0:0e5a). No string: warning (error 0x2e), nothing shown. The text is sprintf16, then
    /// language-filtered (captionText); >= 351 characters are dropped. It lives 7 * len 60 Hz ticks = ceil(7 * len / 2) VM ticks (ASSUMPTION on
    /// the rounding) and REPLACES any caption or subtitle on screen. Drawn through the subtitle path, centred, colour 0x75 (ASSUMPTION: the
    /// caption object sets none, as for Alt+V); it shows with subtitles off too (10b0:0f48 never reads [50bc]). A second word must be PAUSE,
    /// which blocks the caller until the caption ends; any other warns (error 0x127) and the caption still shows.
    func cmdCaption(_ proc: ScriptProcess, _ words: [String], _ nums: [Int]) {
        guard let fmt = words.first, !fmt.isEmpty else { warn("CAPTION: needs a string (error 0x2e)"); return }
        let raw = Presentation.sprintf16(fmt, nums)
        var h = 0
        if raw.unicodeScalars.count < Presentation.captionMax, vm != nil {
            let text = Presentation.captionText(raw, language: settings.language)
            h = subtitle([.int(-1), .int(0x75), .int(0xff), .str(text)], minor: false,
                         ticks: (Presentation.ticksPerCharacter * text.unicodeScalars.count + 1) / 2)
            captionHandles.insert(h)
        }
        if words.count > 1 && !words[1].isEmpty {
            if words[1].uppercased() == "PAUSE" {
                if h != 0 { proc.waitPred = { [weak self] in self?.vm?.process(h) == nil } }
            } else {
                warn("CAPTION: unexpected word \(words[1]) (error 0x127)")
            }
        }
    }
}
