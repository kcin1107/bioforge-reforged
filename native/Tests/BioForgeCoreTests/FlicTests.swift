import Testing
@testable import BioForgeCore

private struct FlicBytes {
    var bytes = [UInt8](repeating: 0, count: 128)

    init(frames: Int, width: Int, height: Int, speed: Int) {
        put(0xaf12, at: 4, bytes: 2); put(frames, at: 6, bytes: 2)
        put(width, at: 8, bytes: 2); put(height, at: 10, bytes: 2)
        put(8, at: 12, bytes: 2); put(speed, at: 16, bytes: 4)
    }

    mutating func chunk(_ type: Int, _ payload: [UInt8]) {
        let offset = bytes.count
        put(payload.count + 6, at: offset, bytes: 4)
        put(type, at: offset + 4, bytes: 2)
        bytes += payload
    }

    mutating func frame(_ chunks: [(Int, [UInt8])]) {
        var payload = little(chunks.count, 2) + [UInt8](repeating: 0, count: 8)
        for (type, body) in chunks { payload += little(body.count + 6, 4) + little(type, 2) + body }
        chunk(0xf1fa, payload)
    }

    mutating func finish() { put(bytes.count, at: 0, bytes: 4) }

    private mutating func put(_ value: Int, at: Int, bytes count: Int) {
        while bytes.count < at + count { bytes.append(0) }
        for i in 0..<count { bytes[at + i] = UInt8(truncatingIfNeeded: value >> (8 * i)) }
    }
}

private func little(_ value: Int, _ count: Int) -> [UInt8] {
    (0..<count).map { UInt8(truncatingIfNeeded: value >> (8 * $0)) }
}

@Suite struct FlicTests {
    @Test func decodesEveryChunkKindIncrementally() throws {
        var file = FlicBytes(frames: 6, width: 4, height: 2, speed: 70)
        file.chunk(0xf100, [1, 2, 3]) // Animator metadata before the frame stream.
        // COLOR_256, then BRUN (a repeat and a literal on each scanline).
        file.frame([(4, [1, 0, 1, 2, 1, 2, 3, 4, 5, 6]), (15, [0, 2, 8, 254, 9, 10, 0, 252, 1, 2, 3, 4])])
        // LC updates only the second line, leaving the first line from BRUN.
        file.frame([(12, [1, 0, 1, 0, 1, 1, 253, 7])])
        // SS2 skips the first line, sets the second line's final byte, then repeats one word.
        file.frame([(7, [1, 0, 255, 255, 3, 128, 1, 0, 0, 255, 8, 9])])
        file.frame([(13, [])]) // BLACK
        file.frame([(16, [1, 2, 3, 4, 5, 6])]) // short COPY pads its two missing pixels with zero
        file.frame([(0xf100, [99]), (11, [1, 0, 2, 1, 1, 2, 63])]) // metadata in a frame, then COLOR_64
        file.finish()
        let decoder = try FlicDecoder(data: file.bytes)
        #expect(decoder.width == 4 && decoder.height == 2 && decoder.frameCount == 6 && decoder.speed == 70)

        let brun = try #require(try decoder.nextFrame())
        #expect(brun.pixels == [8, 8, 9, 10, 1, 2, 3, 4])
        #expect(Array(brun.palette[3..<9]) == [1, 2, 3, 4, 5, 6])

        let lc = try #require(try decoder.nextFrame())
        #expect(lc.pixels == [8, 8, 9, 10, 1, 7, 7, 7])
        let ss2 = try #require(try decoder.nextFrame())
        #expect(ss2.pixels == [8, 8, 9, 10, 8, 9, 7, 3])
        let black = try #require(try decoder.nextFrame())
        #expect(black.pixels == [UInt8](repeating: 0, count: 8))
        let copy = try #require(try decoder.nextFrame())
        #expect(copy.pixels == [1, 2, 3, 4, 5, 6, 0, 0])
        let color64 = try #require(try decoder.nextFrame())
        #expect(Array(color64.palette[6..<9]) == [4, 8, 255])
        #expect(try decoder.nextFrame() == nil)
    }

    @Test func showFramesMatchPythonFixtures() throws {
        let g = try requireGame()
        let shows = fixtures["shows"] as! JSON
        var decoded = 0
        for (name, any) in shows {
            let expected = any as! JSON
            let decoder = try FlicDecoder(data: g.read("SHOW/\(name)"))
            #expect(decoder.width == expected["width"] as! Int && decoder.height == expected["height"] as! Int, "\(name) dimensions")
            #expect(decoder.speed == expected["speed"] as! Int, "\(name) speed")
            let frames = expected["frames"] as! [[String]]
            #expect(decoder.frameCount == frames.count, "\(name) frame count")
            for (index, hashes) in frames.enumerated() {
                let frame = try #require(try decoder.nextFrame(), "\(name) frame \(index)")
                #expect(sha(frame.pixels) == hashes[0], "\(name) frame \(index) pixels")
                #expect(sha(frame.palette) == hashes[1], "\(name) frame \(index) palette")
                decoded += 1
            }
            #expect(try decoder.nextFrame() == nil, "\(name) ends at its declared frame count")
        }
        print("showFramesMatchPythonFixtures: \(shows.count) shows, \(decoded) frames matched")
    }
}
