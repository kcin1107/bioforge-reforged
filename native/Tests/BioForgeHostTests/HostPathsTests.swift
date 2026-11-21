import Foundation
import Testing
@testable import BioForgeHost

struct HostPathsTests {
    @Test func subFoldersFollowTheTwoRoots() {
        let p = HostPaths(support: URL(fileURLWithPath: "/s/BioForge", isDirectory: true), logs: URL(fileURLWithPath: "/l/BioForge", isDirectory: true))
        #expect(p.saves.path == "/s/BioForge/Saves")
        #expect(p.autosaves.path == "/s/BioForge/Autosaves")
        #expect(p.hiRes.path == "/s/BioForge/HD")
        #expect(p.logFile.path == "/l/BioForge/BioForge.log")
        #expect(p.sessions.path == "/l/BioForge/Session")
        #expect(p.reports.path == "/l/BioForge/Reports")
    }

    #if os(macOS)
    @Test func macOSPathsAreTheOnesTheAppAlwaysUsed() {
        let fm = FileManager.default
        let support = fm.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0], library = fm.urls(for: .libraryDirectory, in: .userDomainMask)[0]
        let p = HostPaths.macOS
        #expect(p.saves.path == support.appendingPathComponent("BioForge/Saves", isDirectory: true).path)
        #expect(p.autosaves.path == support.appendingPathComponent("BioForge/Autosaves", isDirectory: true).path)
        #expect(p.hiRes.path == support.appendingPathComponent("BioForge/HD").path)
        #expect(p.logFile.path == library.appendingPathComponent("Logs/BioForge/BioForge.log").path)
        #expect(p.sessions.path == library.appendingPathComponent("Logs/BioForge/Session", isDirectory: true).path)
        #expect(p.logs.path == library.appendingPathComponent("Logs/BioForge", isDirectory: true).path)
        #expect(p.reports.path == library.appendingPathComponent("Logs/BioForge/Reports", isDirectory: true).path)
    }
    #endif
}

struct HostPathsPlatformTests {
    private func home() -> URL { URL(fileURLWithPath: "/home/me", isDirectory: true) }
    private func path(_ base: String, _ rest: String...) -> String {
        rest.reduce(URL(fileURLWithPath: base, isDirectory: true)) { $0.appendingPathComponent($1, isDirectory: true) }.path
    }

    @Test func configDefaultsToSupport() {
        let p = HostPaths(support: URL(fileURLWithPath: "/s/BioForge", isDirectory: true), logs: URL(fileURLWithPath: "/l/BioForge", isDirectory: true))
        #expect(p.config == p.support)
        #expect(p.settingsFile.path == "/s/BioForge/settings.json")
        let q = HostPaths(support: p.support, logs: p.logs, config: URL(fileURLWithPath: "/c/BioForge", isDirectory: true))
        #expect(q.settingsFile.path == "/c/BioForge/settings.json")
    }

    #if os(macOS)
    @Test func macOSSettingsFileSitsInSupport() {
        #expect(HostPaths.macOS.config == HostPaths.macOS.support)
        #expect(HostPaths.macOS.settingsFile.path == HostPaths.macOS.support.appendingPathComponent("settings.json").path)
    }
    #endif

    @Test func linuxDefaultsFollowTheHome() {
        let p = HostPaths.linux(env: [:], home: home())
        #expect(p.support.path == path("/home/me", ".local", "share", "BioForge"))
        #expect(p.logs.path == path("/home/me", ".local", "state", "BioForge"))
        #expect(p.config.path == path("/home/me", ".config", "BioForge"))
        #expect(p.saves.path == path("/home/me", ".local", "share", "BioForge", "Saves"))
    }

    @Test func linuxXDGVariablesOverride() {
        let p = HostPaths.linux(env: ["XDG_DATA_HOME": "/d", "XDG_STATE_HOME": "/s", "XDG_CONFIG_HOME": "/c"], home: home())
        #expect(p.support.path == path("/d", "BioForge") && p.logs.path == path("/s", "BioForge") && p.config.path == path("/c", "BioForge"))
        #expect(p.settingsFile.path == path("/c", "BioForge", "settings.json"))
    }

    @Test func linuxIgnoresEmptyAndRelativeVariables() {
        let p = HostPaths.linux(env: ["XDG_DATA_HOME": "", "XDG_STATE_HOME": "state", "XDG_CONFIG_HOME": "./cfg"], home: home())
        #expect(p.support.path == path("/home/me", ".local", "share", "BioForge"))
        #expect(p.logs.path == path("/home/me", ".local", "state", "BioForge"))
        #expect(p.config.path == path("/home/me", ".config", "BioForge"))
    }

    @Test func windowsLivesUnderAppData() throws {
        let p = try #require(HostPaths.windows(env: ["APPDATA": "/appdata"]))
        #expect(p.support.path == path("/appdata", "BioForge") && p.config == p.support)
        #expect(p.logs.path == path("/appdata", "BioForge", "Logs"))
        #expect(p.settingsFile.lastPathComponent == "settings.json")
    }

    @Test func windowsNeedsAppData() {
        #expect(HostPaths.windows(env: [:]) == nil)
        #expect(HostPaths.windows(env: ["APPDATA": ""]) == nil)
    }
}
