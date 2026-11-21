// The texts the shell shows about the game folder and failed saves, so every host says the same thing. (message, info) pairs are an
// alert's bold line and its detail; the `problem` strings fill the empty window.
import Foundation

public enum HostText {
    /// "a, b, c, d, e and 2 more": the first five names of a long list.
    public static func missingList(_ names: [String]) -> String {
        names.prefix(5).joined(separator: ", ") + (names.count > 5 ? " and \(names.count - 5) more" : "")
    }

    public static func incompleteEmptyState(folder: String, missing: [String]) -> String {
        "The game data in “\(folder)” is incomplete: \(missingList(missing)) \(missing.count == 1 ? "is" : "are") missing. Choose another folder."
    }

    public static func incompleteAlert(folder: String, missing: [String]) -> (message: String, info: String) {
        ("The game data is incomplete.", "Missing from “\(folder)”: \(missingList(missing)).\n\nReinstall the game or choose another folder.")
    }

    public static func unknownDataNotice(unknown: [String]) -> (message: String, info: String) {
        ("The game files differ from the tested release.",
         "These files aren’t the ones in the GOG release 2.1.0.14 BioForge was tested with: \(missingList(unknown)). The game may still work. Help > Report a Bug lists them.")
    }

    /// What the player was last told about: the folder and the unknown files, so the notice comes once per folder and file list.
    public static func unknownDataFingerprint(folderPath: String, unknown: [String]) -> String { ([folderPath] + unknown).joined(separator: "\n") }

    public static func folderGone(path: String) -> String { "The game folder used last time can’t be found: \(path). If you moved it, choose it again." }

    public static func notAGameFolder(name: String) -> (message: String, info: String) {
        ("“\(name)” isn’t a BioForge game folder.",
         "Choose the folder that contains BIOFORGE.EXE and a ROOMS folder. In a GOG installation it’s the Bioforge folder inside the app folder.")
    }

    public static func unreadableData(folder: String) -> String {
        "The game data in “\(folder)” couldn’t be read. Make sure the installation is complete, or choose another folder."
    }

    public static func unreadableAlert(error: String, folderPath: String) -> (message: String, info: String) {
        ("BioForge couldn’t read the game data.", "\(error)\n\nFolder: \(folderPath)")
    }

    public static func fileError(load: Bool, slot: Int, reason: String) -> (message: String, info: String) {
        load ? ("The saved game couldn’t be loaded.", "Slot \(slot): \(reason)")
             : ("The game couldn’t be saved.", "Slot \(slot): \(reason)\n\nAny earlier save in that slot is unchanged.")
    }
}
