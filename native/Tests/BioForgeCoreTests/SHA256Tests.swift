import Foundation
import Testing
#if canImport(CryptoKit)
import CryptoKit
#endif
@testable import BioForgeCore

struct SHA256Tests {
    @Test func knownVectors() {
        #expect(Sha256.hex([UInt8]()) == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855")
        #expect(Sha256.hex(Array("abc".utf8)) == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad")
        #expect(Sha256.hex(Data("abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq".utf8)) == "248d6a61d20638b8e5c026930c3e6039a33ce45964ff2167f6ecedd419db06c1")
        #expect(Sha256.hex([UInt8](repeating: 0x61, count: 1_000_000)) == "cdc76e5c9914fb9281a1c7e284d73e67f1809a48a497200e046d39ccc7112cd0")
    }

    #if canImport(CryptoKit)
    @Test func matchesCryptoKit() {
        var rng = SystemRandomNumberGenerator()
        for n in Array(0...140) + [191, 192, 193, 255, 256, 1000, 4097] + (0..<20).map { _ in Int.random(in: 0..<5000, using: &rng) } {
            let bytes = (0..<n).map { _ in UInt8.random(in: 0...255, using: &rng) }
            #expect(Sha256.hex(bytes) == SHA256.hash(data: bytes).map { String(format: "%02x", $0) }.joined(), "length \(n)")
        }
    }
    #endif
}
