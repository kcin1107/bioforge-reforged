# Project structure

Reverse-engineering workspace for a native macOS port of BioForge (1995). Current status and
to-do: **`STATUS.md`**. Technical reference: **`re/NOTES.md`**.

```
README.md                project overview and prototype commands
AGENTS.md, CLAUDE.md     working guidelines for coding agents (identical apart from the title line)
STATUS.md                current progress and next steps
ROADMAP.md               milestones to a first playable beta
PLAYER_GUIDE.md          short guide for players: setup, controls, known differences, per platform
KNOWN_DIFFERENCES.md     fidelity policy, open gaps, kept quirks, port extras
PLAYTEST.md              playtest sessions per area and how bugs are triaged
CHANGELOG.md             what each build has, known issues, save compatibility
LICENSE                  MIT for the port's code; the game, its data and the BioForge trademark are not covered
.github/ISSUE_TEMPLATE/  the bug report template for the public repository
STRUCTURE.md             this repository map
GOG_Galaxy_Bioforge.exe   GOG downloader stub (not the game; ignore)
installer/                GOG offline installer (setup_bioforge_2.1.0.14.exe)
game/                     extracted original game files: read-only, never modify
  app/Bioforge/           BIOFORGE.EXE, ROOMS/ BODY/ ITEMS/ SCRIPT/ DATA/ SOUND/ MUSIC/ SHOW/ MONITORS/ INITGAME/
  app/GAMEDAT/            level object files (saved-game state)
native/                   Swift package (Xcode 27 / Swift 6.4, no third-party packages, one vendored C header (TinySoundFont, for the SDL shell's General MIDI); the app target is macOS only, BioForgeCore and BioForgeHost also build on Linux and Windows, the SDL3 shell (BioForgeSDL) only there (the Mac with BIOFORGE_SDL=1), Apple-only parts behind `#if canImport`: Core ML upscaling, the memory guard, the art packs' DEFLATE):
  Sources/BioForgeCore/   decoders + software 320×200 framebuffer (Bytes, GameFolder, Flex, Flic, IFF,
                          CAMImage, LevelObjects, Framebuffer, EORMesh, Bed, Skeleton, Scene,
                          Compositor, HiResFrame (View > High-Resolution Art: the picture repainted at 2x or 4x indices from the art pack of that scale, presentation only), PixelPack (builds that pack in the app: the indexed filter, room, texture and monitor passes (a monitor's background, a pointer's frames), Core ML upscaler on the Neural Engine, fixed to 70 bucketed input sizes; outlines smoothed with Scale2x; 'BFX3' frames ('BFX2' ones are rebuilt); a 3 GB memory guard; resumable, versioned `complete` marker), JointAngleTable (generated: Apple libm's cos/sin bits for Mat3.rotated's angles -256...511, so posed vertices match on Linux and Windows), FigureAssets, WorldCombat (melee hits: .COL cubes, zones, guard, damage, auto-turn), CaptionFont, MouseShapes (MOUSE.SHP cursor), SubtitleRenderer (with Readable Text: a darker box and a brighter colour), MonitorScreen (including live camera viewports; also renders into a HiResFrame, its elements plain-enlarged and only the background and pointer from the pack; View > Readable Text: letter spacing, drop shadow and a brighter palette colour for monitor and options text),
                          Options (OPTS.CAM options dialog), WorldItems (floor/inventory/hand items, ready, stow, pick up / put down), Settings (INSTALL.OPT settings, SettingsStore (the key-value calls it needs; UserDefaults conforms), gamma, master volume, the language E/G/F behind Game > Language), SaveGame/SaveScript/SaveObjRec (native
                          save formats and .IM1 archives), SaveWrite (save writer), SaveLoad and Resume
                          (save, load and resume a running game),
                          SHA256 (hand-written, for portability), PlayLog (the play log behind Help > Report a Bug: level, camera and health changes, Lex's position every ten seconds, a "quit" line on a clean exit), SessionRecorder and SessionReplay (every input call of a session written as JSON lines with its start save, RNG state and flags; the headless exact replay and World.stateDigest checkpoints; ReplayTests),
                          Level (cross-level camera index), ScriptTokens (generated), GameData (the MD5 and GameData.check: which game files are missing or differ from KnownData), KnownData (generated), ScriptDetokenizer,
                          ScriptParser, ScriptVM, PyRandom, Keys, SoundBank, SoundMixer, Music (GM and AdLib arrangements),
                          AdLib (AIL AdLib driver port, timbre bank, live OPL2Stream), OPL2 (FM chip model), World* (WorldAudio: voice
                          statements, OVERTIME ramps, room ambient loops, motion sound cues)), mirroring
                          re/formats and re/interp
  Sources/BioForgeHost/   portable host layer shared by the Mac app and the SDL shell (Foundation + BioForgeCore only): HostPaths (where saves, autosaves, art packs, logs, reports and the settings file live; `.macOS` is the app's folders, `.linux` the XDG folders, `.windows` %APPDATA%\BioForge) with GameFolder.find (the chosen folder or a game folder up to two levels inside it),
                          HostText (the exact alert and empty-state texts about the game folder and failed saves), MemoryStore (an in-memory SettingsStore), FileSettingsStore (a SettingsStore in one JSON file, for the shells without UserDefaults), PictureLayout (where the 320x200 picture sits in an output of any size, with the 4:3 correction, and the pointer maths; top-left origin), FrameRGBA (the indexed frame through its palette into RGBA bytes for a texture), SettingsScreen (the SDL shell's settings screen as state and drawing, no SDL: pages, rows, key and button capture, drawn over the RGBA picture in DATA/SMALL.FNT; SettingsScreenHost applies the changes), Autosave (the rolling per-level autosave: newest five kept), BugReport (the report's app line, folder name, Session recordings and report.txt, keeping a crashed recording), KeyBindings (the remappable keys, in USB HID usages; MonitorKeys), PadBindings (game controller buttons and the stick's eight directions), MacKeyCodes (kVK <-> HID usage table), BindingsMigration (the Mac's saved key-code bindings converted once to KeyBindingsHID), TickClock (the 30 Hz tick clock and the TITLE picture hold, no World in it), GameHost (the running game: one `advance` per display frame runs the ticks with play log, autosave and audio; HostPlatform is what the shell does), InputRouter (key, controller and pointer routing into the World: GameInput, KeyEvent, PointerPhase), HostLog (diagnostics sink protocol), HostAudio (what a shell's audio output offers the game loop; MIDISynth), AudioScheduler (feeds the sound and music logs to the SoundMixer, the GM synth or the AdLib/OPL2 stream once per tick)
  Sources/BioForgeApp/    AppKit app; Metal presents the indexed framebuffer the core renders, flics included (AppDelegate:
                          window, menus, the display link driving GameHost, game folder, errors, turning NSEvents into the Host's KeyEvents and pointer phases; ControlsWindow: Settings > Controls key and controller remapping; MacKeys (the modifier device bits by Mac key code), MacLog (os.Logger behind HostLog), GamepadInput: Game Controller framework polling; HelpWindow: Help > BioForge Help; BugReport: Help > Report a Bug… sheets, the zip in ~/Library/Logs/BioForge/Reports and the DiagnosticReports crash-report lookup (the report's contents come from BioForgeHost), also the build stamp and the crash offer after an unexpected end; Autosave: File > Open Autosave… (the rolling per-level autosave itself is in BioForgeHost); the art build's first-launch offer and progress sheet in AppDelegate;
                          FramebufferView (the picture fills the window, keeping its shape), Shader (palette lookup with crisp
                          edges at any scale), SoundOutput: AVAudioEngine output for the Host's AudioScheduler, the DLS General MIDI synth and the OPL2 source node, main)
  Package.swift           the package: targets BioForgeCore, BioForgeHost, BioForgeApp (macOS), CSDL3, CTinySoundFont, BioForgeSDLShell and BioForgeSDL (Linux, Windows, or the Mac with BIOFORGE_SDL=1) and their tests
  Resources/              AppIcon.png (the fallback app icon, original artwork) and make_icon.py, which draws it; gog_icon.py, which makes the icon from the GOG release's goggame-*.ico at build time
  VERSION                 the app's version (0.1.0), read by build-app.sh and notarize.sh
  notarize.sh             notarizes and staples a --sign build, writes dist/BioForge-<version>-mac.zip
  build-app.sh            builds build/BioForge.app (release, ad-hoc signed or with --sign a universal Developer ID build with no GOG icon and with the art model, Info.plist and AppIcon.icns written here, the icon from the game folder's GOG icon when present; with BIOFORGE_ML_PYTHON it also downloads, checks and converts the art model into the app; build/ and build/cache are ignored)
  Sources/CSDL3/          SDL3 as a Swift system library (module.modulemap; shim.h with the flag macros Swift can't import); pkg-config sdl3 on Linux and the Mac, native/ThirdParty/SDL3 (ignored) or SDL3_DIR on Windows
  Sources/CTinySoundFont/ TinySoundFont v0.9 (MIT): include/tsf.h unmodified at a pinned commit, tsf.c builds it (TSF_NO_STDIO); only with the SDL targets
  Sources/BioForgeSDLShell/ the SDL3 shell for Windows and Linux, built on the Mac only with BIOFORGE_SDL=1: SDLApp (SDL init, the XDG or %APPDATA% folders, the settings file), SDLShell (window, the picture through a streamed texture with PIXELART scaling and PictureLayout, the game folder from BIOFORGE_DATA, the settings or the folder dialog, the data check, GameHost's loop and HostPlatform, suspend on focus loss; BIOFORGE_SDL_SMOKE / BIOFORGE_SDL_SHOT headless runs), SDLInput (SDL keys as the router's KeyEvents, the mouse through PictureLayout, F11 / Alt+Enter full screen, the modifier state after the ticks, the pointer following the mouse, the warp and the cursor), SDLGamepad (the first SDL_Gamepad, polled at 60 Hz into PadTracker, its button labels), SDLSettings (the settings screen's host: saving and applying each change, F1 and Back / View, keys and the controller while it is open), SDLDialogs (message boxes, the folder dialog), SDLLog, SDLAudio (HostAudio over three SDL_AudioStreams on one device: SoundMixer's effects at 22050 Hz, the AdLib OPL2Stream at 49716 Hz and GMStream at 44100 Hz stereo, fed by the Host's AudioScheduler from SDL's audio thread; General MIDI plays as AdLib when no SoundFont is found; mute is the device gain), SDLMIDI (GMStream: the MIDISynth over TinySoundFont, each message's delay a sample offset on its own timeline; SoundFontSearch: the "SoundFont" setting, the data folder, the program's folders, Linux system files)
  Sources/BioForgeSDL/    the BioForgeSDL executable: main.swift only
  package-linux.sh        builds the Linux AppImages in Apple's container tool (x86_64, arm64) and smoke-tests each in a clean container; output in dist/ (ignored, with cache/ for the pinned SDL and AppImage-runtime downloads)
  package-windows.ps1     builds the Windows zip on a Windows PC (Visual Studio developer PowerShell): release exe for the Windows subsystem with BioForge.rc linked in, the DLLs found with dumpbin, the notices; then a smoke run of the unzipped copy with a bare PATH; output in dist/
  package/                what goes into the packages: README.txt (for players), NOTICES.txt, licenses/ (SDL3, its HIDAPI and yuv2rgb parts, Swift, ICU, TinySoundFont);
                          linux/build.sh (runs in swift:6.4-jammy: SDL3 from source, the static-stdlib release build, the AppDir and its checks, mksquashfs + type2 runtime), linux/bioforge.desktop; windows/BioForge.rc and AppIcon.ico (the exe's icon and version information)
  WINDOWS_CHECK.md        brief for a Claude Code session on a Windows PC: SDL3 setup, swift build and swift test with the game data, the SDL smoke run, a hand checklist; then the packaging (package-windows.ps1) and a hand check of the zip
  Tests/BioForgeSDLTests/ SDLShellTests (headless on the offscreen or dummy driver, needs the game data: a new game runs from TITLE to CHAOS through real SDL events, BIOFORGE_DATA is not remembered, the saves folder, a remembered folder is found), SDLInputTests (key translation; Escape and the options dialog, walking, clicks inside and outside the picture, focus loss, F11), SDLGamepadTests (a virtual SDL gamepad: connecting, Start, the stick moving the pointer, A and B, walking, unplugging lets go of Run), SDLAudioTests (SDL's disk audio driver: effects and AdLib render in real time and are audible, music off, pause, mute; General MIDI audible with a SoundFont, AdLib without one or with a bad file, switching at run time), GMStreamTests (offline, no data: a delayed message starts exactly that many samples later, order kept, all notes off, bank 128 drums, the SoundFont search order), TestSoundFont (a minimal sine SoundFont written at run time), SDLSettingsTests (F1 stops the ticks, Readable Text toggled and kept after a restart, a key rebound and saved)
  Tests/BioForgeHostTests/ HostTextTests (every message verbatim, GameFolder.find on a temp tree), HostPathsTests (also the XDG and %APPDATA% folders), SettingsStoreTests (Settings save/apply through MemoryStore), FileSettingsStoreTests (every stored type, Settings, key and controller bindings through the file, a corrupt file), PictureLayoutTests (sizes and bars, round trips, the same mapping as the Mac's FramebufferView), FrameRGBATests, SettingsScreenTests (navigation, every row, key and button capture, refused keys, reset, the drawing pinned with the game's font), AutosaveTests (needs the game data: pruning, once per level, a failed write), KeyBindingsTests (numpad-free defaults, same actions as the fixed mapping, Escape reaches a captured keyboard), PadBindingsTests, MacKeyCodesTests (the table is one-to-one; defaults and monitor keys equal the old Mac ones converted), BindingsMigrationTests, TickClockTests, GameHostTests (the loop, suspend and the picture hold against a fake platform and audio; needs the game data), InputRouterTests (every routing rule against a recording GameInput; no game data), AudioSchedulerTests (needs the game data: pinned digests of the GM bytes, GM messages keep their place inside the tick, the OPL2 stream and the effect mix, a stall, device switch, stop, request/level order), BugReportTests (texts, keepCrashedRecording, assembling a report with game data)
  Tests/BioForgeCoreTests/ OracleTests, SHA256Tests, JointAngleTableTests (the angle table), PlayLogTests, PlaythroughTests (the prison playthrough's input fixes), TestDescriptions (one-line descriptions for captured objects, so a failing expectation does not print a whole World), CharacterTests, ScriptTests, WorldTests, FlicTests, SoundTests, HiResFrameTests, PixelPackTests (the Swift filter against Python's on Fixtures/pixel_filters.json; the monitor pass; bucketed model input sizes; Scale2x outlines; the memory guard; opt-in Core ML parity and memory (BIOFORGE_HD_MODEL)), PackBenchTests (opt-in PACK_BENCH: a 555-frame sample per variant, timing and palette-index changes against the CPU build, re/out/pack_bench/), HiResScreensTests (monitors, options and captions at 2x/4x equal the 1x picture enlarged without a pack; options in play sit on the 2x room; menu and monitor elements ignore pack frames), LanguageTests (Game > Language: sound bank, monitor and options text, captions and spoken subtitles, GETOPTDATA and the intro in German and French), ReadableTextTests (Readable Text: shadow and brighter colours, the label and list fallbacks, subtitles' darker box, the same picture at every scale),
                          GameDataTests (MD5 vectors, the real folder is recognised, a copy with a missing and a changed file), MusicTests, AdLibTests, SubtitleTests, MouseShapesTests, MonitorTests, OptionsTests, SettingsTests, HotkeyTests, ItemTests, SaveGameTests, SaveLoadTests, SaveFuzzTests (corrupted saves fail with an error, never a trap; SAVE_FUZZ=n), GroundingTests, TriggerTests, VelocityTests (persistent velocity, bounce, SETVELOCITY / LEAP), NurseBounceTests, NursePushTests, HitTests, ChaosEncounterTests (cm units, waypoint functions, AMBIENT, APPLY decals, type-name SETCURRENTFIGURE, script query functions and COORDX units, unmodelled list), CollisionResponseTests (FUN_10a0_0ead), MissileTests (FIRE, CARRY, hits, the BEACH zip line, MAKEMISSILE, the blaster shoot path), EffectsTests (flat objects, EXPLODE and its shrapnel, THROWCURITEM and the TEMPLE grenade), FloorsTests (moving floors, area-scoped floor queries, the CONTROL garage elevator ride), PlaythroughBaseTests (LOADLEVEL callers and destinations, object-local selectors and renames, CALL argument lists, refused MOTIONs, FIGR AI names, use blocks that take Lex), AudioTests (SETVOLUME, SETPITCH re-timing, REPLACESOUND, OVERTIME ramps, ambient loops, a released loop's tail, motion sound cues), LoadLevelTests (LOADLEVEL kills all but the caller's CALL chain and keeps only the named voice; PROCESS from a timeline block), MechanicsTests (CHANGEMYFORM, GRABCRITTER / RELEASEFROMLIMB and the BEACH beast, FREEHAND, ANIMATE state, SETREFERENT, INCVIRTUALSECONDS, FORCERELOAD, numeric GO, FLOATATHEIGHT's one-argument form), PresentationTests (CHANGEPALETTE, FADE, RUMBLE, CAPTION, DEBUG, SET_PTR_*), ShowTests (flics, JUMPON, the keyboard hook, FREEZE/THAW, front end), PlaythroughSurfaceTests (dangling ELSE, GO to a trigger's centre, the shoot request name, key-move loops, a trigger's LOADLEVEL mid-frame), ItemsCombatTests (duplicate item names, SETCURRENTITEM / ISCARRYING lookup, item hulls and AMINTRIGGER, MY_HAND, the motion gates, AI ON when dead, TURN), FullRunTests (replays the Python full run, new game to EXIT, from Fixtures/full_run.json with checkpoints every 200 ticks and a save-then-load digest check at every leg end; its op replay is FullRunReplay), MonkeyTests (opt-in with MONKEY=1: random keys and clicks, routed through BioForgeHost's InputRouter with the default bindings, as the app routes them, at each of the full run's 30 save points cached in re/out/monkey_saves/, then checks Lex can move again and that the reload dialog after a death stays up; outcomes in re/out/monkey/), MovementTests (rising motions and the loop rule, FREEZE, GO arrival, the PHYS cache on LOADLEVEL, support without LAND_REVERT, the jetson tube), RoomEventsTests (room events, ISCURRENTCAMERA, the AI-off counter, the show / hide pass), CameraLinkTests (LINKMETOCAMERAS: pause and resume on a camera switch, WAIT and timelines while paused, the flags sampled live) against Fixtures/fixtures.json
                          and shared original nurse-contact snapshots in Fixtures/nurse_bounce.json, the recorded post-wound key route in Fixtures/nurse_push.json, and Python music event hashes (hashes from
                          re/tools/native_fixtures.py; needs BIOFORGE_DATA);
                          re/tools/native_script_tables.py generates ScriptTokens.swift
                          re/tools/data_checksums.py (with test_data_checksums.py) generates KnownData.swift from a game folder: size and MD5 of the first 5000 bytes of BIOFORGE.EXE and the data folders' files, not INSTALL.OPT (the installer rewrites it)
re/
  NOTES.md                formats, engine functions, semantics (the reference)
  formats/                Python decoders and renderers:
                          flex (archives), cam (room images), flc (SHOW movies), iff, eor (meshes), salsa (skeleton/motions incl. frame time, turning flag and attack fields, .COL hit volumes, engine fixed-point FK and F),
                            bed, level (level objects), script (detokenizer), sound (samples → WAV), fnt (fonts), mouse (MOUSE.SHP cursor shapes), savegame (native save state + .im1), savewrite (save writer; the original loads its saves),
                            xmi/music/musicseq (XMIDI → MIDI, song/transition tables,
                            the engine's music state machine), adlib (the game's AIL AdLib driver:
                            MIDI → OPL2 register writes), opl (OPL2 FM chip model), render/compose (renderer +
                            depth-sorted compositor), scene/camview/camfit (camera tools), animate
  interp/                 script VM and engine binding:
                            parse.py (parser), vm.py (scheduler/interpreter), world.py (engine binding:
                            figures, cameras, levels, player input, minimal item state,
                            per-figure hull / area-based PHYS collision, IMAG triggers and melee hits: COL volumes, zones, damage),
                            keys.py (original PC scan-code mapping),
                            monitor.py (monitor/PIMM UI engine and renderer, live camera viewports, translucent elements, the pointer's press animation and input switch),
                            settings.py (INSTALL.OPT sound/music/gamma/subtitles/language, gamma LUT, master volume table; test_language.py covers the language),
                            options.py (OPTS.CAM dialog preview, button text from SCRIPT/PIMM.SCP in the art's label elements: difficulty, audio, gamma, credits,
                            nine-slot save/load selectors wired to prototype native persistence),
                            items.py (the item list with duplicate names, floor, inventory and held items, ready/stow/put down, hand pose, item position, the motions' frame event walk),
                            missiles.py (FIRE, MAKEMISSILE, the missile task: flight, hits, CARRY),
                            effects.py (MAKEFLATOBJECT sprites, EXPLODE, THROWCURITEM and free-item physics),
                            floors.py (SETFLOOROFPHYS, TELEPORTALLONPHYS: moving floors),
                            presentation.py (CHANGEPALETTE, FADE, RUMBLE, CAPTION, DEBUG, SET_PTR_*: the presented palette and frame),
                            show.py (flics: STARTFLIC / RUNFLIC ..., FREEZE / THAW, the CAPTUREKEYBOARD hook, ADDKEY, GETOPTDATA; JUMPON is in vm.py),
                            audio.py (SETVOLUME, SETPITCH / ADDTOPITCH, REPLACESOUND / REVERTSOUND, the OVERTIME ramps,
                            camera / room ambient loops, motion sound cues, the engine's cutting sound-name lookup),
                            mechanics.py (CHANGEMYFORM, GRABCRITTER / RELEASEFROMLIMB, FREEHAND, ANIMATE, SETREFERENT,
                              INCVIRTUALSECONDS, FORCERELOAD; numeric GO and FLOATATHEIGHT's F live in world.py),
                            subtitles.py (on-screen captions),
                            movie.py (render scenes to GIF, optional WAV mix of effects + music), scenarios.py (deterministic
                            cross-level replays, the CHAOS nurse / Caynan / Guard 1 encounters and JSON/PNG checkpoints),
                            playthrough_base.py (the base / ending playthrough harness: CONTROL, TOWER, PLATFORM, ENDGAME from real
                              LOADLEVEL arrivals, real keys, logged staged shortcuts and problems),
                            playthrough_prison.py (prison playthrough harness: new game through CHAOS and TANKS with real keys,
                              per-segment problems and logged staged shortcuts),
                            playthrough_surface.py (the surface playthrough harness: LANDPAD -> BEACH -> DIGSITE -> TUNROOM from real
                              arrivals, real keys, recorded staged shortcuts and per-step problems),
                            playthrough_full.py (one continuous run from a new game to EXIT in a single World / VM, reusing the three
                              harnesses above on the running world; logged shortcuts, test_playthrough_full.py shares one ~2 minute run),
                            resume.py (a native save restored into the prototype: figures, carried items, script processes),
                            play.py (SDL2 live preview, optional -e style MOUSE.SHP cursor), run.py, test_*.py
  playthrough/            playthrough maps and findings per stretch of the game (base.md: base and ending; prison.md: CHAOS and TANKS;
                          surface.md: LANDPAD, BEACH, DIGSITE, TUNROOM; full.md: the whole game in one run, its shortcuts and ranked blockers; assumption-audit.md: every ASSUMPTION marker checked against the decompile)
  tools/                  newgame_save_digest.py (the new-game save digests pinned in SaveLoadTests.swift),
                          parity.py / parity_core.py (clock-scheduled original-vs-Python comparison;
                          parity_scenarios/ JSON definitions, parity_samples/ checked-in test traces),
                          midi2wav.swift (offline General MIDI rendering via Apple's synth AU),
                          opl2wav.swift (offline OPL2 rendering; compiled with native OPL2.swift),
                          dosbox_live.py (reads figure records, incl. motion, heading, frame, avoidance points and InTrig bytes, plus the camera and object boxes, script processes with their paused flag and camera links, forces a camera, dumps the VGA screen (`vga`), passes one raw debugger command (`debug`, e.g. a breakpoint), writes one 16-bit figure field (`figure_word`, e.g. the AI-off counter),
                          from the original running in DOSBox-X; dense samples, key holds (incl. key_down / key_up across frames), PHYS/height experiments,
                          native-save staging, detached controller / reconnect support, persistent paused JSON control,
                          controlled pose setup and figure-update breakpoint sampling;
                          optional scratch macOS app wrapper for computer control; needs Homebrew `dosbox-x`),
                          dosbox_control.py (command client and automated original-game fall/combat checks,
                          staged nurse front/rear attacks, input-driven wounded-nurse steering,
                          bar-contact defeat continuation and corridor escape checks),
                          nurse_bounce.py (compares original wall-contact records with the port's XY response
                          at the observed poses; not a free-running timeline comparison),
                          test_dosbox_live.py / test_dosbox_control.py (control/protocol regressions),
                          fight_sample.py / test_fight_sample.py (one fight, live and in the port, with the same keys and a chosen attack: damage and rates; output in re/out/fight_samples/),
                          fight_sweep.py / test_fight_sweep.py (every attack in every melee fight, in the port, forked from the full run; output in re/out/fight_sweep/),
                          run_tests.py (the unittest suites of re/interp, re/formats and re/tools in parallel, one process per test class, slowest first by the last run's times in re/out/test_times.json; the floor is test_playthrough_full.FullRun, about 2.5 min),
                          run_seeds.py / test_run_seeds.py (the full run on several RANDOM streams, and how far each got; `--difficulty medium|hard` for the other levels; output in re/out/run_seeds/),
                          pixel_pack.py / pixel_filters.py / test_pixel_filters.py (the reference for the 2x/4x indexed art pack of View > High-Resolution Art, guided by a 4x torch/spandrel model, and its hand-fix route; output is not committed), pixel_fixtures.py (writes the Swift filter's parity fixtures), convert_model.py (the model to Core ML for the app, with the builder's 70 fixed input sizes for the Neural Engine),
                          save_resume_check.py (saves, reloads and plays on to the end at every leg boundary of the full run; re/out/save_resume_check.jsonl; `--control` only restarts the animations and rounds positions and headings as the records do, re/out/save_resume_control.jsonl),
                          save_diff.py (at chosen boundaries, what a save and load changes in every figure, item, global and process; re/out/save_diff/),
                          save_trace.py (the loaded game and the unsaved `--control` game side by side from one save point, tick by tick; re/out/save_trace/),
                          resume_digest.py (the resume digests pinned in SaveLoadTests.swift),
                          full_run_transcript.py (records the Python full run for FullRunTests, with a save_check digest per leg end; `--trace a b` diffs ticks against `FULL_RUN_TRACE=a-b swift test`), native_fixtures.py (including item/inventory indexed frames), native_script_tables.py, ne_dump.py
  scripts/                Ghidra headless Java scripts (decompile, disassemble, xrefs, tables)
  ghidra/                 Ghidra project (BIOFORGE.EXE analysed, far-pointer refs recovered)
  decomp/                 decompiled C per code segment (<seg>.c); 1280.c covers options panels,
                          1090.c figure retirement, 10f8.c explosion dispatch,
                          1280_callbacks.c the recovered dialog event handler,
                          1288.c the save/load slot selector, 1128.c new-game reset,
                          1140.c and 11e0/11f8/1200.c archive/file paths, 1230/1238/1240.c kernel save/process paths
  out/                    generated output: music/ (.mid + songs.json), decoded scripts (out/scripts/*.scr + index.md), token and
                          handler tables, surveys (*_survey.md), renders (*.png, *.gif)
  dgroup.bin, strings.tsv data segment dump; strings with code references (both, and ghidra/, are derived from BIOFORGE.EXE and not committed)
  .venv/                  Python venv (numpy, Pillow)
tools/                    publish_public.sh (exports HEAD to the public source repo; see below)
```

Requirements: Homebrew `ghidra` (brings openjdk@21) and `innoextract`; Python 3 venv at `re/.venv`.
The optional live preview also uses Homebrew `sdl2` through Python `ctypes`. Music rendering
needs the Xcode command-line tools (`swiftc`); General MIDI uses the system `gs_instruments.dls`,
AdLib compiles `native/Sources/BioForgeCore/OPL2.swift` with `re/tools/opl2wav.swift`.

## Public source repo

This repository stays private because it holds `re/decomp`. The public source repo (MIT) is a
filtered export of it, one commit per sync, made by `tools/publish_public.sh <clone-dir | remote> [--push]`
run from `main`:

- It takes the tracked files of HEAD (`git archive`) and drops `re/decomp/`, `re/out/`,
  `AGENTS.md`, `CLAUDE.md` and `.claude/`. It keeps one file of `re/out`: `script_tokens.txt`, the
  engine's keyword and opcode table that `re/interp` and `re/formats` load on import (no script
  excerpts; the same table is in `ScriptTokens.swift`).
- Leak check, which aborts on any hit: home paths, e-mail addresses (outside the third-party
  license texts in `native/package/licenses/`), game files (`.IFF .CAM .SMK .FLC .EXE .WAV .IM1`),
  anything under `re/decomp`, and files over 5 MB.
- It builds the export (`swift build`) and runs `re/tools/run_tests.py` in a temp copy, with only
  the git-ignored pieces linked in from the main checkout: `game`, `re/.venv`, `re/dgroup.bin`,
  `re/strings.tsv` and the untracked `re/out/*` entries.
- It then replaces the clone's working tree (keeping its `.git`) and commits "Sync from <short sha>".
  A directory with a `.git` is used as the clone; a URL or bare repo path is cloned to a temp dir.
  It pushes only with `--push`.
