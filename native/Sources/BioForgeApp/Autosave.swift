// The rolling autosave: when the level changes and the in-game S would be accepted (World.levelAutosaveDue), a native save goes to
// ~/Library/Application Support/BioForge/Autosaves as "<date time> <LEVEL>.IM1", the newest five kept (the saving is Autosave in BioForgeHost; a failed
// write is only logged). Here: File > Open Autosave… loads one the way BIOFORGE_LOAD does.
import AppKit
import BioForgeCore
import BioForgeHost

extension AppDelegate {
    private var autosavesDirectory: URL? {
        Self.hostPaths.autosaves
    }

    @objc func openAutosave() { chooseSave(message: "Choose an autosave to continue from.", directory: autosavesDirectory) }

    /// Debug > Open Save File…: any .IM1, such as the ones re/tools/save_resume_check.py --export writes.
    @objc func openSaveFile() {
        chooseSave(message: "Choose a save file (.IM1) to open.", directory: nil, log: "debug: open save file")
    }

    private func chooseSave(message: String, directory: URL?, log: String? = nil) {
        let panel = NSOpenPanel()
        panel.message = message
        panel.prompt = "Open"
        panel.allowedContentTypes = [.init(filenameExtension: "IM1")].compactMap { $0 }
        panel.canChooseDirectories = false
        panel.directoryURL = directory
        panel.beginSheetModal(for: window) { [self] answer in
            guard answer == .OK, let url = panel.url else { return }
            if let log { playLog.note("\(log) \(url.lastPathComponent)") }
            loadSave(at: url, fallBackToNewGame: false)
        }
    }
}
