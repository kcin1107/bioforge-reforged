// The start of the SDL shell: SDL, the per-user folders, the settings file, then the loop. BioForgeSDL's main.swift only calls `run`.
import BioForgeHost
import CSDL3
import Foundation

public enum SDLApp {
    @MainActor
    public static func run() -> Int32 {
        SDL_SetAppMetadata("BioForge", "dev", "BioForge")
        guard SDL_Init(BF_INIT_SHELL) else {
            FileHandle.standardError.write(Data("SDL_Init failed: \(String(cString: SDL_GetError()))\n".utf8))
            return 1
        }
        defer { SDL_Quit() }
        #if os(Windows)
        let paths = HostPaths.windows() ?? HostPaths.linux()
        #elseif os(macOS)
        // Development only: the Mac app has its own shell and its own files, which this must never touch.
        let paths = HostPaths.linux(env: [:], home: FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Library/Application Support/BioForge-SDL", isDirectory: true))
        #else
        let paths = HostPaths.linux()
        #endif
        let log = SDLLog()
        let shell = SDLShell(paths: paths, store: FileSettingsStore(file: paths.settingsFile, log: log), environment: ProcessInfo.processInfo.environment, log: log)
        shell.start()
        return shell.run()
    }
}
