// swift-tools-version: 6.0
import PackageDescription

#if os(macOS)
let appProducts: [Product] = [.executable(name: "BioForgeApp", targets: ["BioForgeApp"])]
// AppKit + MetalKit shell; the Metal shader is compiled at runtime from source.
let appTargets: [Target] = [.executableTarget(name: "BioForgeApp", dependencies: ["BioForgeCore", "BioForgeHost"])]
#else
let appProducts: [Product] = []
let appTargets: [Target] = []
#endif

// The SDL3 shell (Windows and Linux): always on there, on the Mac only for development with BIOFORGE_SDL=1 (the Mac app is the Mac's shell).
#if os(macOS)
let sdlEnabled = Context.environment["BIOFORGE_SDL"] == "1"
#else
let sdlEnabled = true
#endif
#if os(Windows)
// The official SDL3-devel (VC) zip unpacked into ThirdParty/SDL3, or wherever SDL3_DIR points.
let sdlDir = Context.environment["SDL3_DIR"] ?? "\(Context.packageDirectory)/ThirdParty/SDL3"
let sdlSwift: [SwiftSetting] = [.unsafeFlags(["-Xcc", "-I\(sdlDir)/include"])]
let sdlLink: [LinkerSetting] = [.unsafeFlags(["-L\(sdlDir)/lib/x64"])]
#else
let sdlSwift: [SwiftSetting] = []
let sdlLink: [LinkerSetting] = []
#endif
// BioForgeSDLShell holds the whole shell, as a library so the tests can import it; BioForgeSDL is only its main.swift.
let sdlProducts: [Product] = sdlEnabled ? [.executable(name: "BioForgeSDL", targets: ["BioForgeSDL"])] : []
let sdlTargets: [Target] = sdlEnabled ? [
    .systemLibrary(name: "CSDL3", path: "Sources/CSDL3", pkgConfig: "sdl3", providers: [.apt(["libsdl3-dev"]), .brew(["sdl3"])]),
    // TinySoundFont (MIT, vendored unmodified): the shell's General MIDI synth. Optimized even in debug builds, as it renders on the audio thread.
    .target(name: "CTinySoundFont", cSettings: [.unsafeFlags(["-O2"], .when(configuration: .debug))]),
    .target(name: "BioForgeSDLShell", dependencies: ["BioForgeCore", "BioForgeHost", "CSDL3", "CTinySoundFont"], swiftSettings: sdlSwift, linkerSettings: sdlLink),
    .executableTarget(name: "BioForgeSDL", dependencies: ["BioForgeSDLShell"], swiftSettings: sdlSwift, linkerSettings: sdlLink),
    .testTarget(name: "BioForgeSDLTests", dependencies: ["BioForgeSDLShell", "BioForgeCore", "BioForgeHost", "CSDL3"], swiftSettings: sdlSwift, linkerSettings: sdlLink),
] : []

let package = Package(
    name: "BioForge",
    platforms: [.macOS(.v14)],
    products: [
        .library(name: "BioForgeCore", targets: ["BioForgeCore"]),
        .library(name: "BioForgeHost", targets: ["BioForgeHost"]),
    ] + appProducts + sdlProducts,
    targets: [
        // Pure Swift (Foundation everywhere; Core ML art upscaling only on Apple platforms): data access, decoders, software framebuffer, the High-Resolution Art pack builder.
        // The software renderer runs per game tick, so it is optimized even in debug builds.
        .target(name: "BioForgeCore", swiftSettings: [.unsafeFlags(["-O"], .when(configuration: .debug))]),
        .testTarget(
            name: "BioForgeCoreTests",
            dependencies: ["BioForgeCore", "BioForgeHost"],          // the Host only for MonkeyTests, which routes through InputRouter
            resources: [.copy("Fixtures/fixtures.json"), .copy("Fixtures/nurse_bounce.json"), .copy("Fixtures/full_run.json"), .copy("Fixtures/nurse_push.json"), .copy("Fixtures/pixel_filters.json")]
        ),
        // Pure Swift (Foundation + BioForgeCore only, so it builds everywhere): the platform-neutral logic shared by the Mac app and other shells (folders, message texts, settings store).
        .target(name: "BioForgeHost", dependencies: ["BioForgeCore"]),
        .testTarget(name: "BioForgeHostTests", dependencies: ["BioForgeHost"]),
    ] + appTargets + sdlTargets,
    swiftLanguageModes: [.v6]
)
