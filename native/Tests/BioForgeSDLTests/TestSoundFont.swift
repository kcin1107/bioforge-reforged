import Foundation

/// A minimal valid SoundFont 2, built at run time: preset 0 (bank 0) and the drum kit (bank 128) are each one looped 441 Hz sine, the drums 12 dB quieter.
func sineSoundFont() -> Data {
    func u16(_ v: Int) -> [UInt8] { [UInt8(v & 0xFF), UInt8((v >> 8) & 0xFF)] }
    func u32(_ v: Int) -> [UInt8] { u16(v & 0xFFFF) + u16(v >> 16) }
    func name(_ s: String) -> [UInt8] { Array(s.utf8) + [UInt8](repeating: 0, count: 20 - s.utf8.count) }
    func chunk(_ id: String, _ body: [UInt8]) -> [UInt8] { Array(id.utf8) + u32(body.count) + body + (body.count % 2 == 1 ? [0] : []) }
    func list(_ type: String, _ chunks: [UInt8]) -> [UInt8] { chunk("LIST", Array(type.utf8) + chunks) }

    let sine = (0..<4400).flatMap { u16(Int(Int16((sin(Double($0) * 2 * .pi / 100) * 26_000).rounded())) & 0xFFFF) } + [UInt8](repeating: 0, count: 2 * 46)
    func phdr(_ n: String, bank: Int, bag: Int) -> [UInt8] { name(n) + u16(0) + u16(bank) + u16(bag) + u32(0) + u32(0) + u32(0) }
    func pair(_ a: Int, _ b: Int) -> [UInt8] { u16(a) + u16(b) }
    let zeroModulator = [UInt8](repeating: 0, count: 10)
    let info = list("INFO", chunk("ifil", u16(2) + u16(1)) + chunk("INAM", Array("Test".utf8) + [0, 0]))
    let sdta = list("sdta", chunk("smpl", sine))
    let pdta = list("pdta",
        chunk("phdr", phdr("Sine", bank: 0, bag: 0) + phdr("Drums", bank: 128, bag: 1) + phdr("EOP", bank: 0, bag: 2))
        + chunk("pbag", pair(0, 0) + pair(1, 0) + pair(2, 0))
        + chunk("pmod", zeroModulator)
        + chunk("pgen", pair(41, 0) + pair(41, 1) + pair(0, 0))                           // instrument 0, instrument 1
        + chunk("inst", name("Sine") + u16(0) + name("Quiet") + u16(1) + name("EOI") + u16(2))
        + chunk("ibag", pair(0, 0) + pair(2, 0) + pair(5, 0))
        + chunk("imod", zeroModulator)
        + chunk("igen", pair(54, 1) + pair(53, 0)                                         // loop, sample 0
                      + pair(48, 1200) + pair(54, 1) + pair(53, 0)                        // 12 dB of attenuation (tsf counts 1/100 dB), loop, sample 0
                      + pair(0, 0))
        + chunk("shdr", name("Sine") + u32(0) + u32(4400) + u32(0) + u32(4400) + u32(44_100) + [69, 0] + u16(0) + u16(1)
                      + name("EOS") + [UInt8](repeating: 0, count: 26)))
    let body = Array("sfbk".utf8) + info + sdta + pdta
    return Data(Array("RIFF".utf8) + u32(body.count) + body)
}
