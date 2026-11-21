// Autodesk FLC decoder for the game's SHOW/*.SHO files. Frames are indexed colour plus RGB8 palette.
import Foundation

public struct FlicFrame: Sendable, Equatable {
    public let pixels: [UInt8]
    public let palette: [UInt8]

    public init(pixels: [UInt8], palette: [UInt8]) {
        self.pixels = pixels
        self.palette = palette
    }
}

public final class FlicDecoder {
    public let width: Int
    public let height: Int
    public let frameCount: Int
    /// Milliseconds between frames, as stored in the FLC header.
    public let speed: Int

    private let data: [UInt8]
    private let frames: [(offset: Int, size: Int)]
    private var index = 0
    private var pixels: [UInt8]
    private var palette = [UInt8](repeating: 0, count: 256 * 3)

    public init(data: [UInt8]) throws {
        guard data.count >= 128 else { throw FormatError("FLC header is truncated") }
        guard try data.u16(4) == 0xaf12 else { throw FormatError("not an FLC file") }
        let count = try data.u16(6), width = try data.u16(8), height = try data.u16(10)
        guard width > 0 && height > 0 else { throw FormatError("invalid FLC dimensions \(width)x\(height)") }
        guard try data.u16(12) == 8 else { throw FormatError("FLC is not 8-bit indexed") }

        self.data = data
        self.width = width
        self.height = height
        self.frameCount = count
        self.speed = try data.u32(16)
        self.pixels = [UInt8](repeating: 0, count: width * height)

        var offset = 128, found: [(offset: Int, size: Int)] = []
        while offset + 6 <= data.count && found.count < count {
            let size = try data.u32(offset), type = try data.u16(offset + 4)
            guard size >= 6, offset + size <= data.count else { throw FormatError("invalid FLC chunk at \(offset)") }
            if type == 0xf1fa {
                guard size >= 16 else { throw FormatError("truncated FLC frame at \(offset)") }
                found.append((offset, size))
            } else if type != 0xf100 && type != 18 {
                throw FormatError("unexpected FLC top-level chunk 0x\(String(type, radix: 16))")
            }
            offset += size
        }
        guard found.count == count else { throw FormatError("FLC declares \(count) frames but contains \(found.count)") }
        self.frames = found
    }

    /// Decodes the next display frame. The decoder starts before frame zero; returns nil after `frameCount` frames.
    public func nextFrame() throws -> FlicFrame? {
        guard index < frames.count else { return nil }
        let frame = frames[index]
        let chunks = try data.u16(frame.offset + 6)
        var offset = frame.offset + 16
        let end = frame.offset + frame.size
        for _ in 0..<chunks {
            guard offset + 6 <= end else { throw FormatError("truncated FLC frame chunk") }
            let size = try data.u32(offset), type = try data.u16(offset + 4)
            guard size >= 6, offset + size <= end else { throw FormatError("invalid FLC frame chunk") }
            try decodeChunk(type, from: offset + 6, to: offset + size)
            offset += size
        }
        index += 1
        return FlicFrame(pixels: pixels, palette: palette)
    }

    private func decodeChunk(_ type: Int, from start: Int, to end: Int) throws {
        switch type {
        case 4: try color(from: start, to: end, sixBit: false)       // COLOR_256
        case 7: try deltaFLC(from: start, to: end)                    // DELTA_FLC / SS2
        case 11: try color(from: start, to: end, sixBit: true)        // COLOR_64
        case 12: try lineCompressed(from: start, to: end)             // LC
        case 13: pixels = [UInt8](repeating: 0, count: pixels.count)  // BLACK
        case 15: try brun(from: start, to: end)                        // BRUN
        case 16:                                                       // COPY
            let count = Swift.min(end - start, pixels.count)
            pixels.replaceSubrange(0..<count, with: data[start..<(start + count)])
            if count < pixels.count { pixels.replaceSubrange(count..<pixels.count, with: repeatElement(0, count: pixels.count - count)) }
        case 18, 0xf100: break                                         // Animator thumbnail / metadata
        default: throw FormatError("unsupported FLC chunk 0x\(String(type, radix: 16))")
        }
    }

    private func color(from start: Int, to end: Int, sixBit: Bool) throws {
        var at = start
        let packets = try u16(&at, end)
        var color = 0
        for _ in 0..<packets {
            color += try u8(&at, end)
            var count = try u8(&at, end)
            if count == 0 { count = 256 }
            guard color + count <= 256 else { throw FormatError("FLC palette packet exceeds 256 colours") }
            for i in 0..<count {
                for component in 0..<3 {
                    let value = try u8(&at, end)
                    palette[(color + i) * 3 + component] = UInt8(sixBit ? (value << 2) | (value >> 4) : value)
                }
            }
            color += count
        }
    }

    private func brun(from start: Int, to end: Int) throws {
        var at = start
        for y in 0..<height {
            _ = try u8(&at, end) // Animator's per-line packet count is unreliable; runs terminate the line.
            var x = 0
            while x < width {
                let count = try s8(&at, end)
                if count > 0 {
                    let value = try u8(&at, end)
                    try writeRun(y: y, x: &x, count: count, value: UInt8(value))
                } else if count < 0 {
                    let count = -count
                    guard x + count <= width, at + count <= end else { throw FormatError("truncated FLC BRUN literal") }
                    pixels.replaceSubrange((y * width + x)..<(y * width + x + count), with: data[at..<(at + count)])
                    at += count; x += count
                } else { throw FormatError("zero-length FLC BRUN run") }
            }
        }
    }

    private func lineCompressed(from start: Int, to end: Int) throws {
        var at = start
        var y = try u16(&at, end)
        let lines = try u16(&at, end)
        guard y + lines <= height else { throw FormatError("FLC LC lines exceed frame") }
        for _ in 0..<lines {
            let packets = try u8(&at, end)
            var x = 0
            for _ in 0..<packets {
                x += try u8(&at, end)
                let count = try s8(&at, end)
                if count >= 0 {
                    guard x + count <= width, at + count <= end else { throw FormatError("truncated FLC LC literal") }
                    pixels.replaceSubrange((y * width + x)..<(y * width + x + count), with: data[at..<(at + count)])
                    at += count; x += count
                } else {
                    let value = try u8(&at, end)
                    try writeRun(y: y, x: &x, count: -count, value: UInt8(value))
                }
            }
            y += 1
        }
    }

    private func deltaFLC(from start: Int, to end: Int) throws {
        var at = start, y = 0, lines = try u16(&at, end)
        while lines > 0 {
            let opcode = try u16(&at, end)
            switch opcode & 0xc000 {
            case 0xc000:
                y += 0x1_0000 - opcode
                guard y <= height else { throw FormatError("FLC SS2 line skip exceeds frame") }
            case 0x8000:
                guard y < height else { throw FormatError("FLC SS2 last pixel exceeds frame") }
                pixels[y * width + width - 1] = UInt8(truncatingIfNeeded: opcode)
            default:
                guard y < height else { throw FormatError("FLC SS2 line exceeds frame") }
                var x = 0
                for _ in 0..<opcode {
                    x += try u8(&at, end)
                    let count = try s8(&at, end)
                    if count >= 0 {
                        let bytes = count * 2
                        guard x + bytes <= width, at + bytes <= end else { throw FormatError("truncated FLC SS2 literal") }
                        pixels.replaceSubrange((y * width + x)..<(y * width + x + bytes), with: data[at..<(at + bytes)])
                        at += bytes; x += bytes
                    } else {
                        let first = try u8(&at, end), second = try u8(&at, end)
                        let bytes = -count * 2
                        guard x + bytes <= width else { throw FormatError("FLC SS2 repeat exceeds line") }
                        for i in stride(from: 0, to: bytes, by: 2) {
                            pixels[y * width + x + i] = UInt8(first)
                            pixels[y * width + x + i + 1] = UInt8(second)
                        }
                        x += bytes
                    }
                }
                y += 1; lines -= 1
            }
        }
    }

    private func writeRun(y: Int, x: inout Int, count: Int, value: UInt8) throws {
        guard x + count <= width else { throw FormatError("FLC run exceeds line") }
        pixels.replaceSubrange((y * width + x)..<(y * width + x + count), with: repeatElement(value, count: count))
        x += count
    }

    private func u8(_ at: inout Int, _ end: Int) throws -> Int {
        guard at < end else { throw FormatError("truncated FLC chunk at \(at), ending at \(end)") }
        defer { at += 1 }; return Int(data[at])
    }

    private func s8(_ at: inout Int, _ end: Int) throws -> Int {
        Int(Int8(bitPattern: UInt8(try u8(&at, end))))
    }

    private func u16(_ at: inout Int, _ end: Int) throws -> Int {
        guard at + 2 <= end else { throw FormatError("truncated FLC chunk at \(at), ending at \(end)") }
        defer { at += 2 }; return Int(data[at]) | Int(data[at + 1]) << 8
    }
}
