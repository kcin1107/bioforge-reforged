// Stage 4b: event-stream parity with re/formats/musicseq.py. The hashes cover a straight song
// and a positive transition at the music task's next update, including the note queue (XMIDI note durations),
// 0x74/0x75 loops, and the driver's stop (queued note offs, sustain off).
import Foundation
import Testing
@testable import BioForgeCore

@Suite(.serialized, .enabled(if: game != nil, "BIOFORGE_DATA is not set; point it at the BioForge game folder"))
struct MusicTests {
    private func digest(_ events: [MusicMIDIEvent]) -> String {
        let text = events.map { String(format: "%.6f:%@\n", $0.time, $0.bytes.map { String(format: "%02x", $0) }.joined()) }.joined()
        return Sha256.hex(Data(text.utf8))
    }

    @Test func songStartMatchesPython() throws {
        let sequence = MusicSequencer(library: try MusicLibrary(game: requireGame()))
        sequence.request(10, at: 0)
        sequence.request(-1, at: 8)
        let events = sequence.advance(to: 8)
        #expect(events.count == 63)
        #expect(digest(events) == "9fa3ba4676191d1ab68ab8e130ea43b43d5fe66bcab01610aecf68f2741665af")
    }

    @Test func barTransitionMatchesPython() throws {
        let sequence = MusicSequencer(library: try MusicLibrary(game: requireGame()))
        sequence.request(10, at: 0)
        sequence.request(21, at: 12)
        sequence.request(-1, at: 30)
        let events = sequence.advance(to: 30)
        #expect(events.count == 539)
        #expect(digest(events) == "78a79d2f74341d4fb9fd35f451127da5955575538f40a7d2e9f037cfe0c8e8d0")
    }

    @Test func directAndOverlayTransitionsMatchPython() throws {
        let direct = MusicSequencer(library: try MusicLibrary(game: requireGame()))
        direct.request(11, at: 0)
        direct.request(27, at: 0.5)
        direct.request(-1, at: 8)
        let directEvents = direct.advance(to: 8)
        #expect(directEvents.count == 219)
        #expect(digest(directEvents) == "ec9d3e940f42a793177077854562c9cd3bae18272e32ced08253558dd54dc619")

        let overlay = MusicSequencer(library: try MusicLibrary(game: requireGame()))
        overlay.request(10, at: 0)
        overlay.request(5, at: 1)
        overlay.request(-1, at: 20)
        let overlayEvents = overlay.advance(to: 20)
        #expect(overlayEvents.count == 376)
        #expect(digest(overlayEvents) == "4291a979b1b7798e04e672ea32a2a5f44e9b4d66d0611fc6f0e6a14317f56441")
    }

    @Test func pauseResumeMatchesPython() throws {
        let sequence = MusicSequencer(library: try MusicLibrary(game: requireGame()))
        sequence.request(10, at: 0)
        sequence.request(-2, at: 2)
        sequence.request(-3, at: 5)
        sequence.request(-1, at: 8)
        let events = sequence.advance(to: 8)
        #expect(events.count == 42)
        #expect(digest(events) == "4d9e2c53f6258ff7b24f15eea5a7816410e6b2aae6afd673291672b02a98aef2")
    }

    // Music level (options dialog): hashes from musicseq.sequence(..., volume=, volumes=) of the Python prototype.
    @Test func scaledVolumeMatchesPython() throws {
        let sequence = MusicSequencer(library: try MusicLibrary(game: requireGame()), volume: 100)
        sequence.request(10, at: 0)
        sequence.request(-1, at: 8)
        let events = sequence.advance(to: 8)
        #expect(events.count == 63)
        #expect(digest(events) == "9fa3ba4676191d1ab68ab8e130ea43b43d5fe66bcab01610aecf68f2741665af", "level 100 = AIL relative volume 100 %: unscaled")
        let cc7 = events.filter { $0.bytes[0] & 0xf0 == 0xb0 && $0.bytes[1] == 7 }
        #expect(!cc7.isEmpty)
    }

    @Test func levelChangesStopResumeAndRescaleLikePython() throws {
        let library = try MusicLibrary(game: requireGame())
        let sequence = MusicSequencer(library: library, volume: 100)
        sequence.request(11, at: 0)
        sequence.setVolume(50, at: 3)          // channel volumes are re-sent
        sequence.setVolume(0, at: 5)           // stops and disables
        sequence.request(27, at: 6)            // ignored while disabled
        sequence.setVolume(40, at: 7)          // enabled again: the last requested song resumes
        sequence.request(-1, at: 12)
        let events = sequence.advance(to: 12)
        #expect(events.count == 123)
        #expect(digest(events) == "d390d139ad1dc19f2710232b14ec126c3171a65eb0a8961b13870896da041a79")
        #expect(!events.contains { $0.time > 5 && $0.time < 7 && $0.bytes[0] & 0xf0 == 0x90 }, "silent while disabled")

        let options = MusicSequencer(library: library, volume: 0)     // disabled from the start: raising it starts the options music (song 4)
        options.request(10, at: 0)
        options.setVolume(70, at: 1)
        options.request(-1, at: 5)
        let optionEvents = options.advance(to: 5)
        #expect(optionEvents.count == 101)
        #expect(digest(optionEvents) == "dc66442f5cda3e9b9b24e9d4c1dbacc6b9794fac39ad63722fe4aab8998efbba")
    }

    @Test func everySongStarts() throws {
        let library = try MusicLibrary(game: requireGame())
        for id in 0..<49 {
            let sequence = MusicSequencer(library: library)
            sequence.request(id, at: 0)
            let events = sequence.advance(to: 5)
            if id == 31 { #expect(events.isEmpty, "song \(id) is the intentionally silent GM reset") }
            else { #expect(!events.isEmpty, "song \(id) did not decode or emit MIDI") }
        }
    }
}
