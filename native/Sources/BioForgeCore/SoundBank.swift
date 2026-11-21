// Sound sample metadata (SOUND/<lang>SAMPLES.FLX) and the script sound-name table, mirrors re/formats/sound.py as far as the
// engine binding needs it (handle lifetimes and logs) plus the PCM access for the mixer (SoundMixer).
//
// Flex archive: entries 0..n-1 are samples (u32 data_len, u16 rate, u16 flags, u32 loop_start, u32 loop_end, 12 unused,
// signed 8-bit PCM at +0x20), the last entry is the name table (9-byte NUL-padded names, one per sample).
// Script sound ids: SCRIPT/SOUNDS.DEF lists the 717 sample names in sample order (a name's id is its position in the file);
// SOUNDS2.DEF adds `_alias = _name` lines. The prototype reads the saved-game copy GAMEDAT/SOUNDS.DEF, which is the same table
// with names cut to 24 characters, so ids are keyed by the first 24 characters of the lower-case name.
import Foundation

public struct SoundSample: Sendable {
    /// `loopEnd` = loop start + the header's loop length (+0x0c), 0 when that is 0: the engine loops [loopStart, loopEnd) (1028:0f0a ->
    /// 1000:03de sets the voice's loop end to start + loop start + length).
    public let index: Int, name: String, rate: Int, loopStart: Int, loopEnd: Int, length: Int
    /// Offset of the signed 8-bit PCM inside the bank's flex data.
    let pcmOffset: Int
}

public struct SoundBank: Sendable {
    public let samples: [SoundSample]
    private let data: [UInt8]
    /// Lower-case `_name` -> sample index.
    public let ids: [String: Int]

    public init(game: GameFolder, language: String = "E") throws {
        let flex = try Flex(data: game.read("SOUND/\(language)SAMPLES.FLX"))
        let table = flex.entries.last.map { flex.bytes($0) } ?? []
        let names = stride(from: 0, to: max(table.count - 8, 0), by: 9).map { table.cString($0, $0 + 9) }
        samples = try flex.entries.dropLast().enumerated().map { i, e in
            let d = flex.data
            let n = try d.u32(e.offset)
            return SoundSample(index: i, name: i < names.count ? names[i] : "", rate: try d.u16(e.offset + 4),
                               loopStart: try d.u32(e.offset + 8), loopEnd: try { let ll = try d.u32(e.offset + 12); return ll == 0 ? 0 : try d.u32(e.offset + 8) + ll }(), length: min(n, e.size - 32), pcmOffset: e.offset + 32)
        }
        data = flex.data
        func lines(_ f: String) throws -> [String] {
            try game.read("SCRIPT/" + f).split(separator: 0x0a, omittingEmptySubsequences: false).map { latin1String($0) }
        }
        func key(_ s: String) -> String { String(s.lowercased().prefix(24)) }
        func word(_ s: Substring) -> (name: String, rest: Substring)? {      // \s*(_\w+)
            let t = s.drop { $0 == " " || $0 == "\t" || $0 == "\r" }
            guard t.first == "_" else { return nil }
            let w = t.prefix { $0 == "_" || $0.isLetter && $0.isASCII || $0.isNumber && $0.isASCII }
            return (String(w), t.dropFirst(w.count))
        }
        var ids: [String: Int] = [:], next = 0
        for l in try lines("SOUNDS.DEF") {
            guard let (n, _) = word(Substring(l)) else { continue }
            ids[key(n)] = next; next += 1
        }
        for l in try lines("SOUNDS2.DEF") {
            guard let (n, rest) = word(Substring(l)) else { continue }
            let r = rest.drop { $0 == " " || $0 == "\t" }
            guard r.first == "=" else { continue }
            let target = r.dropFirst().drop { $0 == " " || $0 == "\t" }.prefix { $0 != " " && $0 != "\t" && $0 != "\r" }
            if let id = ids[key(String(target))] ?? Int(target) { ids[key(n)] = id }
        }
        self.ids = ids.filter { $0.value < flex.entries.count - 1 }
    }

    /// Signed 8-bit mono PCM of sample `i` (clamped to the file like a Python slice).
    public func pcm(_ i: Int) -> [Int8] {
        let s = samples[i]
        return data.slice(s.pcmOffset, s.pcmOffset + s.length).map { Int8(bitPattern: $0) }
    }

    /// Seconds of one pass through sample `i` at rate - pitch.
    public func duration(_ i: Int, pitch: Int = 0) -> Double { Double(samples[i].length) / Double(max(samples[i].rate - pitch, 1)) }
}
