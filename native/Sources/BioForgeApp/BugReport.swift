// Help > Report a Bug…: a zip in ~/Library/Logs/BioForge/Reports with report.txt (where Lex is, what the log saw), a save of this moment and the recording of the inputs (SessionRecorder) that replays it exactly. Nothing leaves
// the Mac: the player attaches the zip themselves. Sheets per HIG "Alerts": the game stays paused while it is up. The report also carries the newest
// BioForge crash report of the last week (DiagnosticReports) and, after an unexpected end, the crashed game's recording (Session.crashed, kept apart at
// launch so the next game can't push it out). The build stamp (commit, "-dirty" when built from uncommitted changes) is in report.txt, the log and About.
import AppKit
import BioForgeCore
import BioForgeHost

extension AppDelegate {
    /// "0.1 (build 345, 1a2b3c4)" from Info.plist (build-app.sh); "development build" under `swift run` and in tests.
    static var buildStamp: String {
        let d = Bundle.main.infoDictionary
        guard let version = d?["CFBundleShortVersionString"] as? String else { return "development build" }
        return "\(version) (\(buildDetail))"
    }

    /// "345 · 1a2b3c4" for the About panel's version line.
    static var buildDetail: String {
        let d = Bundle.main.infoDictionary
        return "\(d?["CFBundleVersion"] as? String ?? "?") · \(d?["BioForgeCommit"] as? String ?? "development build")"
    }

    /// The non-affiliation and trademark notice (same wording as README, the player guide and Help).
    static let legalNotice = "BioForge is a trademark of Electronic Arts Inc. This is an unofficial fan port; it is not affiliated with, endorsed or sponsored by Electronic Arts, Origin Systems or GOG. It includes no game data: you need your own copy of BioForge. High-Resolution Art uses the HDcube model by Venomalia, included with permission."

    @objc func showAbout() {
        let centred = NSMutableParagraphStyle()
        centred.alignment = .center
        let credits = NSAttributedString(string: Self.legalNotice, attributes: [.font: NSFont.systemFont(ofSize: NSFont.smallSystemFontSize),
                                                                                .foregroundColor: NSColor.secondaryLabelColor, .paragraphStyle: centred])
        NSApp.orderFrontStandardAboutPanel(options: [.applicationVersion: Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "development build",
                                                     .version: Self.buildDetail, .credits: credits])
    }

    /// After an unexpected end: keep the crashed game's recording out of the next game's way (BugReport.keepCrashedRecording). Call before any game starts.
    func keepCrashedRecording() { BugReport.keepCrashedRecording(logs: Self.hostPaths.logs) }

    /// Asked after launch when the last session ended unexpectedly (HIG "Alerts": a sheet, the useful answer first and the default).
    func offerCrashReport() {
        reportOpen = true
        updateSuspended()
        let ask = NSAlert()
        ask.messageText = "BioForge quit unexpectedly last time."
        ask.informativeText = "A bug report can include the crash report, the log and a recording of that game, so it can be replayed."
        ask.addButton(withTitle: "Make a Bug Report…")
        ask.addButton(withTitle: "Not Now")
        ask.beginSheetModal(for: window) { [self] answer in
            reportOpen = false
            updateSuspended()
            if answer == .alertFirstButtonReturn { DispatchQueue.main.async { [self] in reportBug() } }
        }
    }

    @objc func reportBug() {
        reportOpen = true                               // switching apps and back must not unpause it (updateSuspended)
        updateSuspended()
        let ask = NSAlert()
        ask.messageText = "Report a Bug"
        ask.informativeText = "BioForge will make a zip file with where you are in the game, a recent log, a save of this moment and a recording of your inputs so the problem can be replayed. Nothing is sent anywhere: you attach the file yourself. Say what went wrong (optional):"
        let field = NSTextField(frame: NSRect(x: 0, y: 0, width: 320, height: 72))
        field.placeholderString = "What happened?"
        ask.accessoryView = field
        ask.addButton(withTitle: "Create Report")
        ask.addButton(withTitle: "Cancel")
        ask.beginSheetModal(for: window) { [self] answer in
            defer { reportOpen = false; updateSuspended() }
            guard answer == .alertFirstButtonReturn else { return }
            do { revealReport(try writeReport(comment: field.stringValue)) } catch {
                showAlert("The report couldn’t be created.", error.localizedDescription)
            }
        }
    }

    private func writeReport(comment: String) throws -> URL {
        let fm = FileManager.default
        guard let library = fm.urls(for: .libraryDirectory, in: .userDomainMask).first else { throw CocoaError(.fileNoSuchFile) }
        let now = Date()
        let name = BugReport.folderName(now: now)
        let folder = fm.temporaryDirectory.appendingPathComponent(name, isDirectory: true)
        try fm.createDirectory(at: folder, withIntermediateDirectories: true)
        defer { try? fm.removeItem(at: folder) }
        let app = BugReport.appLine(buildStamp: Self.buildStamp, system: "macOS \(ProcessInfo.processInfo.operatingSystemVersionString)", gameFolder: game?.url.lastPathComponent,
                                    language: settings.language, dataReport: dataReport)
        let diagnostics = library.appendingPathComponent("Logs/DiagnosticReports", isDirectory: true)      // the system's crash reports, as they are
        let crashReports = ["ips", "crash"].compactMap { ext in
            ((try? fm.contentsOfDirectory(at: diagnostics, includingPropertiesForKeys: [.contentModificationDateKey])) ?? [])
                .filter { $0.pathExtension == ext && $0.lastPathComponent.hasPrefix("BioForge") }
                .compactMap { url in (try? url.resourceValues(forKeys: [.contentModificationDateKey]).contentModificationDate).map { (url, $0) } }
                .filter { $0.1 > now.addingTimeInterval(-7 * 86400) }
                .max { $0.1 < $1.1 }?.0
        }
        try BugReport.assemble(in: folder, world: session?.world, playLog: playLog, app: app, comment: comment, logs: Self.hostPaths.logs, crashReports: crashReports, now: now)
        let reports = Self.hostPaths.reports
        try fm.createDirectory(at: reports, withIntermediateDirectories: true)
        let zip = reports.appendingPathComponent(name + ".zip")
        let ditto = Process()
        ditto.executableURL = URL(fileURLWithPath: "/usr/bin/ditto")
        ditto.arguments = ["-c", "-k", "--norsrc", "--noextattr", "--keepParent", folder.path, zip.path]
        try ditto.run()
        ditto.waitUntilExit()
        guard ditto.terminationStatus == 0 else { throw CocoaError(.fileWriteUnknown) }
        return zip
    }

    private func revealReport(_ zip: URL) {
        NSWorkspace.shared.activateFileViewerSelecting([zip])
    }
}
