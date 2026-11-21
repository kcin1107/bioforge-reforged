import BioForgeCore
import Foundation
import Testing
@testable import BioForgeHost

struct HostTextTests {
    @Test func missingListShortensAfterFive() {
        #expect(HostText.missingList(["A"]) == "A")
        #expect(HostText.missingList(["A", "B", "C", "D", "E"]) == "A, B, C, D, E")
        #expect(HostText.missingList(["A", "B", "C", "D", "E", "F", "G"]) == "A, B, C, D, E and 2 more")
    }

    @Test func incompleteTexts() {
        #expect(HostText.incompleteEmptyState(folder: "Bioforge", missing: ["A"]) == "The game data in “Bioforge” is incomplete: A is missing. Choose another folder.")
        #expect(HostText.incompleteEmptyState(folder: "Bioforge", missing: ["A", "B"]) == "The game data in “Bioforge” is incomplete: A, B are missing. Choose another folder.")
        #expect(HostText.incompleteEmptyState(folder: "X", missing: ["A", "B", "C", "D", "E", "F", "G"]) == "The game data in “X” is incomplete: A, B, C, D, E and 2 more are missing. Choose another folder.")
        let a = HostText.incompleteAlert(folder: "Bioforge", missing: ["A", "B", "C", "D", "E", "F", "G"])
        #expect(a.message == "The game data is incomplete.")
        #expect(a.info == "Missing from “Bioforge”: A, B, C, D, E and 2 more.\n\nReinstall the game or choose another folder.")
    }

    @Test func unknownDataTexts() {
        let n = HostText.unknownDataNotice(unknown: ["A", "B"])
        #expect(n.message == "The game files differ from the tested release.")
        #expect(n.info == "These files aren’t the ones in the GOG release 2.1.0.14 BioForge was tested with: A, B. The game may still work. Help > Report a Bug lists them.")
        #expect(HostText.unknownDataNotice(unknown: ["A", "B", "C", "D", "E", "F", "G"]).info.contains("A, B, C, D, E and 2 more. The game"))
        #expect(HostText.unknownDataFingerprint(folderPath: "/g", unknown: ["A", "B"]) == "/g\nA\nB")
        #expect(HostText.unknownDataFingerprint(folderPath: "/g", unknown: []) == "/g")
    }

    @Test func folderTexts() {
        #expect(HostText.folderGone(path: "/x/Bioforge") == "The game folder used last time can’t be found: /x/Bioforge. If you moved it, choose it again.")
        let n = HostText.notAGameFolder(name: "Docs")
        #expect(n.message == "“Docs” isn’t a BioForge game folder.")
        #expect(n.info == "Choose the folder that contains BIOFORGE.EXE and a ROOMS folder. In a GOG installation it’s the Bioforge folder inside the app folder.")
        #expect(HostText.unreadableData(folder: "Bioforge") == "The game data in “Bioforge” couldn’t be read. Make sure the installation is complete, or choose another folder.")
        let u = HostText.unreadableAlert(error: "Boom", folderPath: "/x/Bioforge")
        #expect(u.message == "BioForge couldn’t read the game data.")
        #expect(u.info == "Boom\n\nFolder: /x/Bioforge")
    }

    @Test func fileErrors() {
        let l = HostText.fileError(load: true, slot: 3, reason: "Bad file.")
        #expect(l.message == "The saved game couldn’t be loaded.")
        #expect(l.info == "Slot 3: Bad file.")
        let s = HostText.fileError(load: false, slot: 2, reason: "Disk full.")
        #expect(s.message == "The game couldn’t be saved.")
        #expect(s.info == "Slot 2: Disk full.\n\nAny earlier save in that slot is unchanged.")
    }
}

struct GameFolderFindTests {
    private func makeTree() throws -> URL {
        let tmp = URL(fileURLWithPath: NSTemporaryDirectory()).appendingPathComponent("BioForgeHostTests-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: tmp, withIntermediateDirectories: true)
        return tmp
    }

    private func addGame(at dir: URL) throws {
        try FileManager.default.createDirectory(at: dir.appendingPathComponent("ROOMS", isDirectory: true), withIntermediateDirectories: true)
        try Data().write(to: dir.appendingPathComponent("BIOFORGE.EXE"))
    }

    @Test func findsTheFolderItselfAndOneOrTwoLevelsDown() throws {
        let tmp = try makeTree()
        defer { try? FileManager.default.removeItem(at: tmp) }
        let game = tmp.appendingPathComponent("app/Bioforge", isDirectory: true)
        try addGame(at: game)
        #expect(GameFolder.find(in: game)?.url.standardizedFileURL == game.standardizedFileURL)
        #expect(GameFolder.find(in: tmp.appendingPathComponent("app"))?.url.lastPathComponent == "Bioforge")
        #expect(GameFolder.find(in: tmp)?.url.lastPathComponent == "Bioforge")
    }

    @Test func givesUpThreeLevelsDownOrWhenAbsent() throws {
        let tmp = try makeTree()
        defer { try? FileManager.default.removeItem(at: tmp) }
        #expect(GameFolder.find(in: tmp) == nil)
        try addGame(at: tmp.appendingPathComponent("a/b/c", isDirectory: true))
        #expect(GameFolder.find(in: tmp) == nil)
        #expect(GameFolder.find(in: tmp.appendingPathComponent("a"))?.url.lastPathComponent == "c")
    }
}
