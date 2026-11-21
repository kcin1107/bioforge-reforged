// Offline OPL2 rendering for the Python prototype (re/formats/adlib.py render_chip):
//   swiftc -O -parse-as-library native/Sources/BioForgeCore/OPL2.swift re/tools/opl2wav.swift -o opl2wav
//   opl2wav IN.bin OUT.raw
// IN.bin: u32 sample count, then (u32 chip sample, u8 register, u8 value) records sorted by sample; a write at sample s
// applies before output s. OUT.raw: int16 little-endian mono at 49716 Hz.
import Foundation

@main
struct OPL2WAV {
    static func main() throws {
        let args = CommandLine.arguments
        guard args.count == 3 else { FileHandle.standardError.write("usage: opl2wav IN.bin OUT.raw\n".data(using: .utf8)!); exit(2) }
        let data = [UInt8](try Data(contentsOf: URL(fileURLWithPath: args[1])))
        func u32(_ p: Int) -> Int { Int(data[p]) | Int(data[p + 1]) << 8 | Int(data[p + 2]) << 16 | Int(data[p + 3]) << 24 }
        let total = u32(0)
        let chip = OPL2()
        var pcm: [Int16] = []
        pcm.reserveCapacity(total)
        var p = 4
        while pcm.count < total {
            while p + 6 <= data.count && u32(p) <= pcm.count { chip.write(Int(data[p + 4]), Int(data[p + 5])); p += 6 }
            let next = p + 6 <= data.count ? min(total, max(pcm.count + 1, u32(p))) : total
            chip.generate(next - pcm.count, into: &pcm)
        }
        try pcm.withUnsafeBufferPointer { Data(buffer: $0) }.write(to: URL(fileURLWithPath: args[2]))
    }
}
