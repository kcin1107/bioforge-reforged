import BioForgeCore
import Testing
@testable import BioForgeHost

struct SettingsStoreTests {
    @Test func saveThenApplyRoundTrips() {
        let store = MemoryStore()
        Settings(sound: 10, music: 0, gamma: 90, subtitles: false, musicDevice: .adlib, language: "G").save(to: store)
        let s = Settings()
        s.apply(defaults: store)
        #expect(s.sound == 10 && s.music == 0 && s.gamma == 90 && !s.subtitles)
        #expect(s.musicDevice == .adlib && s.language == "G")
    }

    @Test func musicOffRoundTripsAsNil() {
        let store = MemoryStore()
        Settings(musicDevice: nil).save(to: store)
        let s = Settings(musicDevice: .generalMIDI)
        s.apply(defaults: store)
        #expect(s.musicDevice == nil)
    }

    @Test func emptyStoreChangesNothing() {
        let s = Settings(sound: 80, music: 70, gamma: 50, subtitles: false, musicDevice: .adlib, language: "F")
        s.apply(defaults: MemoryStore())
        #expect(s.sound == 80 && s.music == 70 && s.gamma == 50 && !s.subtitles && s.musicDevice == .adlib && s.language == "F")
    }

    @Test func memoryStoreReadsLikeUserDefaults() {
        let store = MemoryStore()
        #expect(store.integer(forKey: "n") == 0 && !store.bool(forKey: "n") && store.string(forKey: "n") == nil && store.object(forKey: "n") == nil)
        store.set(7, forKey: "n"); store.set(true, forKey: "b"); store.set("x", forKey: "s"); store.set(["a": 1], forKey: "d")
        #expect(store.integer(forKey: "n") == 7 && store.bool(forKey: "n") && store.bool(forKey: "b") && store.integer(forKey: "b") == 1)
        #expect(store.string(forKey: "s") == "x" && store.dictionary(forKey: "d")?["a"] as? Int == 1)
        store.set(nil, forKey: "n")
        #expect(store.object(forKey: "n") == nil)
    }
}
