// The rolling autosave: when the level changes and the in-game S would be accepted (World.levelAutosaveDue), a native save goes to the
// autosaves folder as "<date time> <LEVEL>.IM1", the newest five kept. A failed write is only logged (the player did not ask for it, so no alert).
import BioForgeCore
import Foundation

public enum Autosave {
    public static let kept = 5

    /// Call once per tick, after it: saves when a level change is due, retrying on later ticks while saving is not allowed.
    public static func saveIfDue(_ w: World, directory dir: URL, log: (String) -> Void, now: Date = Date()) {
        guard w.levelAutosaveDue else { return }
        w.autosavedLevel = w.level                      // one try per level, whatever comes of it
        let fm = FileManager.default
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.dateFormat = "yyyy-MM-dd HH.mm.ss"
        let target = dir.appendingPathComponent("\(formatter.string(from: now)) \(w.level).IM1")
        let saves = w.savesDir
        defer { w.savesDir = saves }
        do {
            try fm.createDirectory(at: dir, withIntermediateDirectories: true)
            w.savesDir = dir
            guard let written = w.saveNative(slot: 1) else { throw CocoaError(.fileWriteUnknown, userInfo: [NSLocalizedDescriptionKey: w.takeFileError()?.reason ?? "unknown"]) }
            try? fm.removeItem(at: target)
            try fm.moveItem(at: written, to: target)
            log("autosave \(target.lastPathComponent)")
            let old = try fm.contentsOfDirectory(at: dir, includingPropertiesForKeys: nil).filter { $0.pathExtension == "IM1" }
                .sorted { $0.lastPathComponent > $1.lastPathComponent }.dropFirst(kept)
            for url in old { try? fm.removeItem(at: url) }
        } catch {
            _ = w.takeFileError()                       // no alert for a save the player didn't ask for
            log("autosave failed: \(error.localizedDescription)")
        }
    }
}
