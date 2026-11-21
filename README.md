# BioForge for macOS, Windows and Linux

A faithful native port of BioForge, Origin Systems' 1995 action adventure, for today's Macs, with a preview for Windows, Linux
and the Steam Deck. It plays the whole game from your own copy, with the original's rules, saves, sound and music, plus optional
Readable Text, High-Resolution Art on the Mac (2x or 4x pixel art built from your own game files with Venomalia's HDcube model,
used with permission), remappable keys and game controllers.

**You need your own copy of BioForge** (the GOG release). No game data is included in this repository or in any download.

- **Download:** the [latest release](../../releases/latest). The Mac app is signed and notarized and runs on macOS 14 or later
  (Apple silicon and Intel). The Windows zip and the Linux AppImage are previews.
- **Getting started:** [PLAYER_GUIDE.md](PLAYER_GUIDE.md): installing, pointing the app at your game folder, the controls.
- **What differs from the DOS game:** [KNOWN_DIFFERENCES.md](KNOWN_DIFFERENCES.md). **What's new:** [CHANGELOG.md](CHANGELOG.md).
- **Bugs:** open an issue and attach the zip from Help > Report a Bug… (it holds a save and a replay of your last minutes;
  nothing is sent anywhere by the app).

Version 0.1 is a preview: the scripted playthrough reaches the ending in every build, but nobody has yet played it to the end
by hand. Medium and Hard are in, but only Easy has been played through.

The port's code is MIT licensed ([LICENSE](LICENSE)). BioForge is a trademark of Electronic Arts Inc.; this project is not
affiliated with or endorsed by Electronic Arts or Origin Systems. Game art in screenshots is © Origin Systems / Electronic Arts.

## For developers

This repository is a faithful port of the 1995 DOS game BioForge (Origin), built by reverse-engineering the original
executable and data. It has two parts: a Python reference interpreter in `re/` (format decoders, script VM, engine binding,
playthrough harnesses and tools that compare it with the original running in DOSBox-X), and a native Swift port in `native/`
that reads the same data. The native port is split into `BioForgeCore` (the engine), `BioForgeHost` (portable shell logic:
input routing, the 30 Hz loop, audio scheduling, settings, saves folders, bug reports), `BioForgeApp` (the macOS app, AppKit
and Metal) and `BioForgeSDL` (an SDL3 app for Windows and Linux, built from `BioForgeSDLShell` and `CSDL3`).

The Mac app plays the whole game from the intro to the ending. It has the original's keys (remappable), game controller
support, sound effects, General MIDI or the original AdLib music, subtitles, the PIMM screens and monitors, and the original
options dialog with nine save slots in the DOS game's own `GAMEn.IM1` format. It also has per-level autosaves, Game > Language
(English, German, French), optional Readable Text and High-Resolution Art at 2x or 4x (built on the Mac from your own game
files), and Help > Report a Bug. Medium and Hard are audited against the original but have not been played through.

Windows and Linux: the engine and host layer build there, and the SDL3 app runs the game. Linux AppImages (x86_64, arm64) build
and pass headless smoke runs in containers. Nothing has been run by hand on Windows or on a Steam Deck yet, and nothing is
published; see the "Windows and Linux" section of `ROADMAP.md`. The first beta still waits on a full playthrough by the
author and on notarization of the Mac build.

No game data is included or distributed. The port reads your own copy of BioForge (the GOG release 2.1.0.14 is the known one).
`PLAYER_GUIDE.md` covers setup and controls, `STRUCTURE.md` is the map of the repository, `STATUS.md` the current state and
history, and `ROADMAP.md` the milestones.

The original game files under `game/` are read-only and are not part of the port's distributable
source. Run the existing prototype from the repository root with its Python environment:

```bash
re/.venv/bin/python -I -W ignore -m unittest discover -s re/interp -p 'test_*.py'
re/.venv/bin/python -I re/tools/run_tests.py     # re/interp, re/formats and re/tools tests in parallel: about 3 min instead of 16
re/.venv/bin/python -I -W ignore re/interp/scenarios.py --out re/out/scenarios
re/.venv/bin/python -I -W ignore re/interp/playthrough_base.py
re/.venv/bin/python -I -W ignore re/interp/playthrough_prison.py --out re/out/playthrough_prison
re/.venv/bin/python -I -W ignore re/interp/playthrough_surface.py --out re/out/playthrough_surface
re/.venv/bin/python -I -W ignore re/interp/playthrough_full.py
re/.venv/bin/python -I re/interp/movie.py --boot re/out/newgame.gif --ticks 1100 --audio re/out/newgame.wav
re/.venv/bin/python -I re/formats/music.py game/app/Bioforge/MUSIC/MUSIC.FLX re/out/music
re/.venv/bin/python -I re/formats/music.py --play 10 --seconds 60 re/out/music/chaos_60s.wav
re/.venv/bin/python -I re/formats/music.py --adlib --play 10 --seconds 60 re/out/music/chaos_adlib.wav
re/.venv/bin/python -I re/interp/play.py
re/.venv/bin/python -I -W ignore re/interp/monitor.py --pimm INVENTORY --out re/out/monitor_pimm_inventory.png
re/.venv/bin/python -I re/tools/parity.py run closed_door_walk
```

The parity command boots the original in a DOSBox-X scratch copy and runs the same
clock-scheduled scenario in the Python prototype. It writes `original.jsonl`, `port.jsonl`,
`report.md`, `report.json`, and `positions.png` under `re/out/parity/<scenario>/` and exits
nonzero when a sampled field exceeds its tolerance. Homebrew `dosbox-x` and the original
`game/app/` data are required. Available scenarios are `opening_wake`, `nurse_activation`,
`closed_door_walk`, and `open_door_zap`; `report <scenario>` rebuilds a report from existing
traces without launching DOSBox-X, and `port <scenario>` reruns only the Python side. DOSBox-X
runs without effects sound; set `BIOFORGE_DOSBOX_MUTE=1` to silence its music as well. The scenario JSON files are in `re/tools/parity_scenarios/`.
They use `boot: "new_game"`; a native DOS save can instead be selected with
`boot: {"save": "/path/to/GAME1.IM1", "slot": 1, "keys": "..."}`. The `keys`
sequence must navigate the original's load dialog and choose that slot.

For repeated original-game checks, `dosbox_live.py WORKDIR --control DIR --app-bundle`
keeps one DOSBox-X session open and pauses it at `--start`. Add `--background` to detach
the controller from its launching terminal; its PID and log path are recorded in
`WORKDIR/controller.json`. Wait for the paused-ready message in `controller.log` before
sending commands. An agent can inspect figures,
hold keys, advance short intervals, and capture controlled falls through JSON requests,
without asking a person to drive Lex. Requests are written atomically as `DIR/in/NAME.json`;
replies appear at `DIR/out/NAME.json`. Commands include `sample`, `frames`, `key`, `set_z`,
`set_xy`, `set_heading`, `phys_top`, `variables`, `processes`, `force_camera`, `set_variable`, `mouse`, `run_for`, `pause`, `run`, and `quit`. `set_variable` and `mouse` are for staging: they write a script global and the pointer state. `fight_sample.py` uses them to run one fight in the original and in the port with the same keys. `variables`
reads named script globals for checks such as the live bars' off window; `processes` lists the script processes with their
paused flag and camera links; `force_camera` stages a camera switch. `key` accepts modifier scan codes
for punches and kicks. `dosbox_control.py combat DIR --target FIRSTBOT --out OUT` enters
combat and attacks the nurse, recording motions, new hit reactions and health changes;
an attack animation alone does not pass the test. Position and clearance changes are explicit test setup. `--load-save GAME1.IM1` copies a native save to the scratch
game directory for explicit load-dialog experiments. The client sends commands and runs a fall
check that writes a trace and pass/fail report; it never restarts the game. `frames` stops at
the requested figure’s update entry so samples follow completed updates. `--attach --control DIR`
reconnects a replacement controller to a running DOSBox-X without booting it. Probe the existing
control session before launching another process. Reuse its paused state between trials;
emulator restore and repeated native reloads proved unreliable on this setup. See the persistent
testing workflow in [re/NOTES.md](re/NOTES.md).

`dosbox_control.py nurse DIR --out OUT` stages front and rear attack positions and
records the nurse's scripted wound/bounce response using real combat keys. On a
wounded nurse, `dosbox_control.py push DIR --out OUT` steers toward the bars using
keys and state feedback, then observes defeat. It makes no pose edits; an existing
wounded encounter is required. A recorded input run from staged starting positions
reached the original zap and defeat at full Lex health. The packaged push CLI has
protocol tests; that wrapper has not been rerun on a fresh nurse. Running `nurse`
again on a wounded nurse instead stages direct bar contact as a separate fixture.
Each setup change is logged; the client preserves the one-way encounter and never reboots it.

The controller claims a request before executing it. A client timeout cancels a queued
request; an already running request can finish and leave its reply for inspection.
Timeouts allow for the requested run duration and sampling overhead.
Individual key holds and timed runs are limited to 120 seconds; frame batches to 100 updates.
Timed sampling intervals must be at least 0.01 seconds.
`dosbox_control.py escape DIR --out OUT` uses key input and live bar-state feedback
to attempt the corridor crossing after nurse removal; it stops on the first health loss
and records failure rather than retrying a lethal route. The original crossing passed at full health in `re/out/nurse_validation/corridor/`.
For a controller that launched its emulator, `quit` requires `"stop_emulator": true`;
an attach controller's `quit` disconnects and leaves the game paused.

Native app (needs Xcode 27; it reads your own game folder, no game data is bundled). `native/build-app.sh`
builds `native/build/BioForge.app`, a double-clickable release build (ad-hoc signed, so on another Mac
it opens with right-click > Open). On first launch it asks for your BioForge folder and remembers it; choosing a
folder above it, such as a GOG installation's top folder, finds the game folder inside. If the folder later
goes missing, or its data can't be read, the window says so and offers the folder picker again. Each time a folder opens, the app checks the size and MD5 of the first 5000 bytes of every game file it needs (BIOFORGE.EXE and the data folders; the table is `KnownData.swift`, made from the GOG release 2.1.0.14, English, which is the only release known): if files are missing it won't start and names them, if files differ it starts anyway and says so once, naming the first few; the log and Report a Bug list them. The game
pauses while the app is in the background or minimized. Help > BioForge Help (⌘?) explains setup, saving and
the controls with your current keys; Help > Keyboard Controls… opens the key settings. Help > Report a Bug… pauses the game and writes a zip to `~/Library/Logs/BioForge/Reports` with where you are, the log, a save of that moment and a recording of your inputs for this game and the one before it (`Session` and `Session.previous`, kept in `~/Library/Logs/BioForge`), and shows it in the Finder, plus the newest BioForge crash report of the last week from `~/Library/Logs/DiagnosticReports`; nothing is sent anywhere. The report and About name the build (version, build number and git commit, `-dirty` when built from uncommitted changes; `build-app.sh` also keeps `native/build/BioForge.app.dSYM` for symbolicating crash reports). If the log of the last session lacks its final "quit" line, the next launch offers to make a report (the crashed game is kept as `Session.crashed`); `BIOFORGE_CRASH_AFTER=<seconds>` crashes the app that long into a game to try it. The recording replays the minutes before the report exactly, headless: `REPLAY=<unzipped report folder> swift test --filter ReplayTests` (with `BIOFORGE_DATA` set) replays it and checks the state recorded at report time. The app icon is the GOG
release's robotic hand, made by `native/Resources/gog_icon.py` from `goggame-*.ico` in your game folder when `build-app.sh` runs (GOG's artwork stays out of
the repository); without that file it is `native/Resources/AppIcon.png`, original artwork drawn by `make_icon.py`.

A build to hand out: `native/build-app.sh --sign "Developer ID Application: <name> (<team>)"` builds a universal app (Apple silicon and
Intel, macOS 14 or later), signed with the hardened runtime and a secure timestamp, with the original-artwork icon and the art model
(never the GOG icon; the model from `BIOFORGE_ML_PYTHON` or the converted copy in `native/build/cache`). `native/notarize.sh` then notarizes it (notarytool credentials
stored once with `xcrun notarytool store-credentials <profile>`, `NOTARY_PROFILE=<profile>`), staples the ticket and writes
`native/dist/BioForge-<version>-mac.zip`; the version is `native/VERSION`. Debug > Save Frame as PNG… saves the picture as shown (art
scale and aspect, no window) at 1280 pixels wide; `BIOFORGE_SHOT=<file.png>` with `BIOFORGE_LOAD=<save>` (and `BIOFORGE_SHOT_AFTER`,
`BIOFORGE_SHOT_KEYS`) does it unattended, which is how the screenshots for the website are made.

```bash
native/build-app.sh && open native/build/BioForge.app
cd native && swift build
BIOFORGE_DATA=/path/to/Bioforge swift run BioForgeApp
BIOFORGE_DATA=/path/to/Bioforge swift test
FULL_RUN_PERF=1 BIOFORGE_DATA=/path/to/Bioforge swift test -c release --filter frameTimes
MONKEY=1 BIOFORGE_DATA=/path/to/Bioforge swift test -c release --filter MonkeyTests
SAVE_FUZZ=2000 BIOFORGE_DATA=/path/to/Bioforge swift test --filter SaveFuzzTests
re/.venv/bin/python -I re/tools/native_fixtures.py
re/.venv/bin/python -I -W ignore re/tools/full_run_transcript.py
```

The Mac app is packaged by `native/build-app.sh`; the SDL3 app below as a Linux AppImage by `native/package-linux.sh` and as a Windows zip by `native/package-windows.ps1` (not run yet: it waits for the Windows PC). The engine (`BioForgeCore`), the shared host layer the app runs on (`BioForgeHost`: input routing, the 30 Hz loop, audio scheduling, paths, settings, autosave, bug reports) and their tests also build on Linux and Windows (phases 1 and 2 of "Windows and Linux" in `ROADMAP.md`). Phase 3 adds an SDL3 app for Windows and Linux, `BioForgeSDL` (checked on Linux, not yet on Windows; `PLAYER_GUIDE.md` has a section on it). It opens a window, finds or asks for the game folder and runs the game with the keyboard (the player's bindings, F11 or Alt+Enter for full screen), the mouse and a game controller (`SDL_Gamepad`: Xbox, PlayStation, Steam Deck; the same buttons as on the Mac), with sound effects and the AdLib music through SDL's audio streams, and General MIDI through TinySoundFont (MIT, vendored in `native/Sources/CTinySoundFont`) when the player has a SoundFont: the first `.sf2` in the data folder (`~/.local/share/BioForge`, `%APPDATA%\BioForge`), a `"SoundFont"` path in the settings file, one next to the program or the AppImage, or on Linux a system one such as `/usr/share/sounds/sf2/FluidR3_GM.sf2`. None is bundled. Without one, a General MIDI setting plays as AdLib and the log and the settings screen say so. F1, or a controller's Back / View button in the game's options dialog, opens its settings screen: full screen, aspect ratio, music (General MIDI, AdLib or off), mute, language, Readable Text, and the keyboard and controller bindings, all kept in the settings file. It needs SDL 3.4 or later (`libsdl3-dev` on Debian and Ubuntu; on Windows see `native/WINDOWS_CHECK.md`); on the Mac it is built only with `BIOFORGE_SDL=1` (Homebrew `sdl3`), for development. On a Mac, Linux runs in Apple's `container` tool (`brew install container`, then `container system start`):

```bash
container run --rm --cpus 10 --memory 16g -v "$PWD/native:/src:ro" -v /path/to/install:/app:ro -w /src docker.io/library/swift:6.4 \
  bash -c 'apt-get update -qq && apt-get install -y -qq libsdl3-dev && BIOFORGE_DATA=/app/Bioforge swift test --scratch-path /build'
```

`BIOFORGE_SDL_SMOKE=900 /build/debug/BioForgeSDL` (with `SDL_VIDEO_DRIVER=offscreen SDL_AUDIO_DRIVER=dummy` and `BIOFORGE_DATA`) runs 900 ticks headless and prints where the game is; `BIOFORGE_SDL_SHOT=file.bmp` also saves the picture. The SDL shell keeps its files in the XDG folders (`~/.local/share/BioForge`, `~/.local/state/BioForge`, `~/.config/BioForge/settings.json`), on Windows in `%APPDATA%\BioForge`.

Mount the folder that holds `Bioforge`, not `Bioforge` itself: the GOG install keeps `GAMEDAT` (the save tests' starting state) next to it.

Add `--arch amd64 --rosetta` for x86_64 (the Steam Deck's). For Windows, see `native/WINDOWS_CHECK.md`.

Linux package (phase 4): `native/package-linux.sh` builds `native/dist/BioForge-<commit>-x86_64.AppImage` (the Steam Deck's) and `-aarch64.AppImage` in `container` and starts each in a clean container (Arch Linux, Debian) for the smoke run above, which must print the same line. The build runs `native/package/linux/build.sh` in `swift:6.4-jammy` (glibc 2.35, so the AppImage runs on systems older than the build host, SteamOS included): SDL 3.4 from its release tarball, with X11, Wayland, PipeWire, PulseAudio and ALSA loaded at run time; the Swift runtime linked in statically; the pinned AppImage type2 runtime (SDL and runtime downloads are checked against SHA-256 and kept in `native/dist/cache`). The result needs glibc 2.35 and a libstdc++ from GCC 12 or later (Ubuntu 22.04, Debian 12, current SteamOS); the build fails if the program or SDL links any other library than those and the bundled `libSDL3.so.0`. Each AppImage is about 23 MB. The container has no FUSE, so the smoke run uses `APPIMAGE_EXTRACT_AND_RUN=1` (and for x86_64 a copy with the AppImage's `AI\2` mark in the ELF header cleared, because Rosetta refuses to run it otherwise; real x86_64 machines ignore the mark); the normal FUSE start is checked on a real Linux system. The package holds the program, `libSDL3.so.0`, the desktop file, the original-artwork icon and `native/package/README.txt`, `NOTICES.txt` and `licenses/` (SDL's zlib, HIDAPI and yuv2rgb notices, Swift's Apache 2.0 with the runtime exception, ICU's Unicode licence); no game data and no art model. `native/dist` is ignored by git; nothing is uploaded.

```bash
native/package-linux.sh                       # both architectures, smoke run with game/app
native/package-linux.sh --arch amd64 --data /path/to/install
```

Windows package: `native/package-windows.ps1`, run on a Windows PC in the Visual Studio developer PowerShell (`native/WINDOWS_CHECK.md`, "Packaging"), builds a release `BioForgeSDL.exe` for the Windows subsystem (no console window) with an icon and version resource (`native/package/windows/BioForge.rc`, `AppIcon.ico` made from `AppIcon.png`), collects the DLLs it needs by walking `dumpbin /dependents` (`SDL3.dll`, the Swift runtime and Foundation DLLs, the Visual C++ runtime app-local from the Build Tools' redist folder; Windows' own DLLs stay out), adds the same `README.txt`, `NOTICES.txt` and `licenses/`, and writes `native\dist\BioForge-<commit>-windows-x64.zip`. It then unzips it into a fresh folder and runs the smoke test there with `PATH` cut down to Windows' own folders and a throwaway `%APPDATA%`. The exe is not signed, so SmartScreen warns on first start ("More info", "Run anyway"); signing needs a code-signing certificate and is not done.

`FULL_RUN_PERF=1 ... --filter frameTimes` times every tick of the whole recorded game, with the frame the app draws, against
the 33.3 ms of a 30 Hz tick. `MONKEY=1 ... --filter MonkeyTests` is the soft-lock check: at each of the full run's 30 save points it
mashes random keys and clicks (routed as the app routes them), then checks that Lex can move again, and after a death that the reload
dialog stays up until a load (`MONKEY_TRIALS`, default 40 per point; about 1.5 min in release; results in `re/out/monkey/`; `MONKEY_LEG` and `MONKEY_TRIAL` pick one trial, `MONKEY_LOG=1` prints its keys,
`MONKEY_TRACE=a-b` the player every tick of that range, `MONKEY_PROCS=1` the script processes in the outcome). `SAVE_FUZZ=n ... --filter SaveFuzzTests` loads n corrupted copies of a save (flipped bytes, cut files) and checks each fails with an error or loads and runs, never crashes (40 cases in a normal run). The last command regenerates the oracle fixtures from the Python prototype. `BIOFORGE_DATA` overrides
the remembered folder (development and tests); File > Open Game Folder… (⌘O) changes it. Controls follow the
original's keys, and BioForge > Settings… (⌘,) remaps them (the game pauses while it is open): each control has a key and an alternate, saved by
the app. Bindings are stored as USB HID key usages (what SDL uses); bindings saved by earlier builds as Mac key codes are converted once. The defaults need no numpad: arrows walk and turn (Fn+arrows = Home/End/PgUp/PgDn), Shift runs,
C toggles combat, Space uses. In combat the eight direction keys attack, holding A (the original's Ctrl, since
Control+arrows are Mission Control shortcuts) gives the kicks and Option (Alt) the punches, and `/` (keypad 5)
shoots. The numpad and Control keys stay bound as alternates. Game > Mute (⌥⌘M) silences effects and music. Game > Music Device switches between General MIDI
(Apple's synth) and AdLib (the game's own AdLib arrangement, played through a port of its AdLib driver
and an OPL2 FM model); the first choice follows `MusicCardId` in `INSTALL.OPT` (1–3 = AdLib/Sound
Blaster, GOG's 7 = General MIDI), and `MUSIC=OFF` there means no music. Game > Language switches speech and text between English, Deutsch and Français, as the original's installer did with `language=` in `INSTALL.OPT` (which sets the first choice; GOG's is English): the voices (`SOUND/<E|G|F>SAMPLES.FLX`), subtitles and captions, monitors and the options dialog change at once (an open options dialog on its next opening), the intro movie on the next new game. Debug > Camera Viewer browses room cameras
(`BIOFORGE_CAMERA=CE33` opens it directly);
View > High-Resolution Art (Off by default, or 2x or 4x) draws the picture at 640x400 or 1280x800, still in the game's own 256 colours, with room art and textures the app builds on your Mac: see below. The picture fills the window at any size, keeping its shape, with crisp pixel edges. View > Readable Text (off by default) makes the game's text easier to read. On monitors, the PIMM and the options dialog it adds one pixel between letters, a dark drop shadow and a brighter colour from the game's own palette, in the same hue; a label that would no longer fit keeps the original spacing, and a list whose text fitted keeps the original line breaks if the spaced text would not. Subtitles and captions, which already have spacing and a shadow, get a darker box and the same brighter colour, except colours already at full brightness, so speakers stay apart. The original's text is just as small; this is an addition, not a fix. View > Correct Aspect Ratio toggles 4:3; `BIOFORGE_TICK_TITLE=1` shows the tick in the title.
New Game plays the original INTRO show (INTROF/INTROG for the corresponding language), with
its script-timed effects and music, before the difficulty dialog. Escape skips the show.
Script fades, palette flashes (`CHANGEPALETTE`), the opening quake's screen shake (`RUMBLE`) and captions
follow the original's timing, and Escape also skips the opening quake as in the original.
The ENDGAME and PLT0 shows play when their game scripts reach them. Escape skips PLT0;
At the end the credits roll over the end movie's last picture as in the original, and the game quits five seconds after they stop; Escape or Alt+X ends it sooner. `re/formats/flc.py`
decodes all six SHOW files, including DEMO1,
which has no recovered script trigger. `native_fixtures.py` records every declared movie
frame's indexed-pixel and palette hashes for the Swift decoder tests.
Debug > Show Editor Mouse Cursor draws the game's own arrow (`MOUSE.SHP`) at the pointer, which the
original shows only when started as `BIOFORGE.EXE -e`; normal play never draws it.
Debug > God Mode (Lex takes no damage), Refill Health and Open Save File… (any `.IM1`, such as the ones
`re/tools/save_resume_check.py --export DIR` writes) are tester aids for getting past a blocker: each use
is logged in the play log, recorded in the session recording (`World.setGodMode`, `refillHealth`, so a replay
does the same) and, for God Mode, shown in report.txt. God Mode is off in every new game or load.
After Lex wakes, P opens the personal monitor; I, D, and J open its inventory, diagnostics,
and journal pages. Move the pointer with the mouse or trackpad; click Exit or press Escape
to leave the page. In Inventory, use the up/down buttons to select an item, then click READY
(or the item artwork) to put it in its declared free hand and close the page. If the hand is
occupied, the item stays in inventory. I or P first stows an item in Lex's left hand; press
again to open the page. Space uses a held item, including scripted combinations with nearby
objects such as using the fork on the cell panel. Enter puts down a held item. The original
inventory screen has no separate Use, Combine, or Drop button.
Diagnostics shows the script's health, energy, and PFD controls. Journal entries appear as
the game awards them, with their recorded times. In-world monitor camera windows show the
selected room view, including feeds from another level. A new game starts with the original
difficulty dialog; click Easy, Medium, or Hard (as in all the dialog's screens, the bar under the pointer lights up). During play, Escape opens the options dialog over the dimmed scene, which pauses the game (the original
does nothing with Escape there; the port adds it, O works as in the original; like O it does nothing while a script has Lex's AI off, such as the wake-up). In the options dialog, Escape cancels or
returns (Cancel on the load or save slots goes back to the main panel). The credits (R, or Credits in the dialog) scroll by themselves over the running game, as in the original, which does not pause for them. Exit, then Yes, quits the app. When Lex dies, the options
dialog opens over the greyed title picture with see-through buttons, as in the original, and asks you to load a
game; Return is disabled there, and every other way out of its screens leads back to the exit prompt or the main panel, as in the
original, until a game is loaded (Load, then New, then Yes starts a new game). A load that fails brings the dialog back. A save or load that fails shows an alert with the reason. The new-game difficulty
dialog sits on the same kind of picture, and after the choice that picture stays up for two seconds while the first level loads.
Saves go to `~/Library/Application Support/BioForge/Saves/GAME1.IM1`…`GAME9.IM1`, the original
file names, so you can copy saves between the DOS game and the app. Loading a DOS save
resumes its figures, carried items and running scripts. Saves written by the app keep level,
camera, variables, journal logs, figures, items and the app's running scripts, so a game saved
in the app goes on where it was; the DOS game would not resume those scripts. As in the DOS game,
a load starts every running animation again from its first frame, and the inventory keeps its order. Each level keeps the items left
there when Lex leaves it, as in the DOS game, and saves write them into that level's file. Not kept: an open monitor.
`BIOFORGE_LOAD=/path/to/GAMEn.IM1` (or a GAMEDAT folder) boots a save directly.
`movie.py --audio` renders the music device from `INSTALL.OPT` too; `--music-device adlib|gm` overrides it.
Sound, music, gamma, and subtitle settings start from your game folder's `INSTALL.OPT`
(GOG ships Gamma=50, which brightens every colour slightly); changes are kept by the app,
never written to the game folder. Shift or Option with `,`/`.` (or keypad −/+) steps gamma.
The original's option keys work in game: O opens options, S save, L load, R the credits,
and Option+X asks to exit. Enter picks up the item in front of Lex or puts down what he holds,
as in the original; items on the floor and in Lex's hands are drawn. While saving is unsafe (a script holds the keyboard, as in the
opening, or an invulnerable figure or a grenade is around), S shows "PIMM: Save
temporarily disabled" instead, and the options screen greys out Save.
Saves use the original's format both ways: the port loads the original's `GAMEn.IM1` saves, and the original loads the port's
(the app keeps them in `~/Library/Application Support/BioForge/Saves`).
The app also autosaves whenever the level changes and saving would be allowed (retrying later in the level if not), into `~/Library/Application Support/BioForge/Autosaves` as `<date time> <LEVEL>.IM1`, keeping the newest five; File > Open Autosave… continues from one.
Option+V shows the game's build caption, as in the original, once the one currently showing ends.

**High-resolution art.** The art pack is made on your Mac from your own game files and is never shipped or committed. It is automated, not hand-drawn: an AI upscale is used only as a guide, and every new pixel takes a colour already next to it in the original, with at least half of each pixel's new pixels (2 of 4 at 2x, 8 of 16 at 4x) keeping the original's colour, so the art stays pixel art in the game's palette. The buttons, arrows, digits and gauges on menus and monitors are not taken from the pack: like the text, they are drawn with plain pixel doubling (2x) or quadrupling (4x), since the upscale smeared their hard edges; the pictures behind them and the hand pointer use the built art. Outlines (where art meets what's behind it) are smoothed with Scale2x, once at 2x and twice at 4x; edge pixels that become solid take the nearest colour of the same piece. The first game you start offers to build a 2x or 4x pack once, and picking 2x or 4x the first time offers to build that pack. While it builds, a progress sheet holds the game; Play Now closes the sheet and the build carries on in the background while you play (rooms switch over as they finish, textures first, then the current level). View > High-Resolution Art > Show Build Progress brings the sheet back, Stop Building pauses the build, and picking the scale again resumes. On an Apple M4 Pro the 2x pack (7740 frames) takes about 11 minutes and 115 MB on disk, the 4x pack about 12 minutes and 300 MB, plus about 2 minutes the first time while macOS prepares the model for the Neural Engine (the sheet says so under its bar); the build stays under about 300 MB of memory. A pack made by an older version (frames in the 'BFX2' format, without smoothed outlines) is rebuilt frame by frame, and a finished one is offered as "Update the 4x art?". Packs live in `~/Library/Application Support/BioForge/HD/2x` and `/4x` (`BIOFORGE_HD_PACK` points the app elsewhere; a pack from before there were two scales is moved into `2x`).

The guide is the model [4x_HDCube_200k](https://github.com/Venomalia/HDcube/tree/main/v1) by Venomalia, run with Core ML on the Neural Engine, which leaves the CPU and GPU to the game. The model is converted with 70 fixed input sizes (each crop is grown with real screen pixels, or its edge repeated, to a multiple of 32, at most 320x200), which is what lets it run there: on a 555-frame sample it was 2.9x faster than the CPU and changed 2.7% of palette indices against a CPU build, as much as the GPU does (2.6%); a range-shaped model fell back to slower paths. The GPU starved the game and the window server (a build during play once made macOS restart the GPU). Each call frees its memory at once. If BioForge still passes 3 GB of memory the build stops with a message; picking the scale again resumes it. (Two early builds grew to 19 and 35 GB and froze the Mac.) The session log notes when a build starts, stops, finishes or fails. Its licence (changed on 2026-10-19; it was CC0 before) allows redistributing the original file only, unmodified, and claims nothing on the images it makes. `native/build-app.sh` downloads it at a pinned commit, checks its SHA-256, converts it with `re/tools/convert_model.py` (cached in `native/build/cache/model2`) and puts the converted model and the licence in the app; this needs `BIOFORGE_ML_PYTHON`, a Python 3.12 with `torch`, `spandrel` and `coremltools` (without it the app is built without the model and can't build art). **The author, Venomalia, gave permission on 2026-11-21 to ship the converted model in BioForge**, so signed builds include it (with its licence file). `BIOFORGE_HD_MODEL=/path/HDCube.mlmodelc` gives `swift run` a model. `PACK_BENCH=1 BIOFORGE_HD_MODEL=… BIOFORGE_DATA=… swift test -c release --filter PackBenchTests` builds a 555-frame sample per variant (`PACK_BENCH_VARIANTS`, e.g. `cpu,gpu,ane,pad16`; `PACK_BENCH_MODEL2` and `alt-…` for a second model; `PACK_BENCH_CLEAN=1` starts over) and writes time, memory, input sizes and palette-index changes against the CPU build to `re/out/pack_bench/<scale>x/summary.md`, with side-by-side PNGs.

```bash
BIOFORGE_ML_PYTHON=<venv>/bin/python native/build-app.sh
<venv>/bin/python -I re/tools/pixel_pack.py --model 4x_HDCube_200k.pth --scale 4 --level CHAOS
```

`re/tools/pixel_pack.py` is the reference implementation (torch; the app's Swift port, `PixelPack.swift`, matches its filter exactly, and its output differs in about 0.5% of pixels because Core ML and torch round differently) and the route for hand fixes: `--export DIR` also writes each frame as an indexed PNG; edit one and pass its folder as `--overrides DIR` to replace that frame. Rooms without art yet are shown plain enlarged, with the 3D figures drawn at the full resolution. Monitors, the PIMM and the options dialog get their art from the pack too (`monitors/`), and the dimmed scene behind the options dialog is the 2x/4x one, with text, captions and subtitles drawn at the full resolution in the game's own fonts, each font pixel enlarged; live camera feeds in monitors are enlarged, as the original shows them at low resolution. Packs built before monitors were added offer Build again, which adds only the monitor art. Fades, palette changes and screen shake work as in the original; movies are shown enlarged, with their subtitles at the full resolution. A window with fewer than 4 screen pixels per original pixel shows the 2x art instead of the 4x.

The live preview requires Homebrew `sdl2`. By default it skips the opening sequence, selects
Medium difficulty, and chooses a camera facing Lex. Run `play.py --skip 0` to see the opening
difficulty dialog; choose a difficulty to let the startup script continue. Use up/Home/Page Up
to walk (Shift to run), left/right to turn (the turning motions rotate Lex as in the original; while walking or running they steer him), down to backstep,
and End/Page Down to sidestep.
Space uses a nearby object, C toggles combat, and
keypad 5 shoots (with the CHAOS blaster in the right hand it fires laser bolts that fly, hit and explode by
script as in the original); keypad directions move in combat, Alt/Option adds hand attacks, and Ctrl adds foot attacks. In the zero-g room keypad 5 fires a right-hand gun, whose recoil moves Lex, and keypad 4/6 turn him. I/P/D/J open the PIMM
inventory/main/diagnostics/journal screens (I/P first stow a left-hand item). Move the mouse over a monitor button and left-click
to use it; the hand pointer follows the mouse and plays the original's press animation (the button acts when the hand reaches its last frame, the release follows when the mouse is up). As in the original, the hand stays put while the button is held, and on the release the mouse is moved back onto the hand. Tab, the arrow keys and L glide the hand to a button and Return or Space press it, and right-click acts as Escape, as in the original; letters press nothing, because the game gives no button a shortcut letter. Monitor text can show live script variables.
`play.py --editor-cursor` also draws the `MOUSE.SHP` arrow at the mouse, as `BIOFORGE.EXE -e` does.
Journal entries appear when scripts award them, with their award time shown as `day-HHMM`.
Monitor camera windows stretch the full camera image into the authored viewport and use the
monitor's grey ramp, which matches a native screenshot closely. The original's exact sampling
and colour formula are not yet recovered from the executable. The original options artwork
appears for script options calls, including the opening difficulty
choice; the opening script waits for the dialog through `ISMONITORRUNNING`. Audio, credits,
and nine-slot save/load selector screens are available. The preview can load native saves and
write archives the DOS game accepts. Its own saves write its running scripts too, in a form
only the port resumes. Audio and gamma panels and
the gamma keys work as in the original, reading `INSTALL.OPT`. Escape closes options or a monitor, or quits the preview.
Lex starts with a battery in inventory but no weapon in hand. Walk through the open cell door
to evade the nurse; if it catches Lex twice, the script plays the knockout and revival.
This is a research preview: input timing remains approximate. Melee hits follow the original:
the striking limb is tested against the target's `BODY/*.COL` cubes on frames 4 to n−5, with
hit zones, blocking from the frame guard bytes, armour, difficulty and the scripts' hit labels.
The `DAMAGE` statement, energy damage, hit and block sounds, `_WOUNDS`/`_DEATH` blocks and the
player's combat auto-turn follow the original too. Manual, scripted `GO`,
and AI root movement test each figure's recovered hull against `PHYS` boxes in its current
area when its collision flag is on, using the original's fixed-point signed overlap score
(closed or neutral doorways block, open ones pass); a blocked figure slides along the wall
or stays put, as in the original. Living figures push each other apart (each keeps its
`PERSONAL_RADIUS`); the nurse's push nudges Lex toward the cell door. Scripted avoidance
points (`ADDAVOIDANCEPOINT`) keep a living figure out of a circle around a waypoint, even with
its collision flag off. IMAG trigger volumes fire as in the original: their scripts run when a
figure enters them, camera triggers switch the view, and the cell's live bars shock Lex if he
walks out of the cell. Motions play at the
original's per-figure speed (`MY_SPEED` times each motion's frame time; other figures than Lex
animate faster on harder difficulty levels, and Lex's repeated attacks slow down), so the opening runs
on the original's timeline, and turning motions such as the nurse's ATK_M7 rotate the figure
as they loop. Rendered poses interpolate between interior motion frames; a loop's final frame
holds until the next cycle starts. Figures with gravity stand on the floor under the
original's hull (Lex at exactly the original's height), fall
off ledges at the original's rate, select the original’s soft landing on normal floor contact, and teeter
(the whoah motions) at drops; level figures keep the gravity setting saved in the level data.

The scenario command replays the opening escape and nurse revival, the LANDPAD airlock,
the nurse's front/rear punches, scripted defeat and corridor escape, Lex's key-driven fights with Caynan (after the nurse, through the
flickering cell-1 bars) and Guard 1 (staged return from the tanks) in the Python prototype (the Swift port mirrors the engine pieces they need, not the scenarios), and a BEACH ↔ TUNROOM round trip. `playthrough_surface.py` drives the surface levels (LANDPAD's elevator arrival to the exit
toward PLATFORM) with the shipped scripts and real keys, records each staged shortcut and problem, and writes `report.json`; the
route, how far it gets and the remaining blockers are in `re/playthrough/surface.md`.
The nurse test uses logged pose/contact fixtures and normal combat input; it covers bouncy
wall rebound and figure retirement; persistent velocity, the generic 3D rebound, SETVELOCITY and LEAP are in the Python
prototype and the Swift port, while explosion debris remains unimplemented. A post-wound route now uses movement keys to reach the live bars and then the corridor at full health in both Python and Swift; only the front/rear attack poses are staged. Exact free-running trajectory parity with the original remains open. It writes JSON checkpoints and selected PNG frames;
the test suite also checks that all 10 level datasets load and render. These checks
cover representative paths, not every gameplay action. The base and ending playthrough harness (`playthrough_base.py`, notes in `re/playthrough/base.md`) drives CONTROL, TOWER, PLATFORM and the ending through the real scripts, from elevator arrivals to ENDGAME's `EXIT`, with its staged shortcuts and the problems found listed in its JSON report.

The prison playthrough harness drives a new game through CHAOS with real keys and monitor clicks: fork, circuit board,
cell-block door, Dane's code, Caynan's arm, driving the USE_BOT robot from its monitor to hold the arm at the reader, the security terminal, the guard-room door, the cryo iris, the ladder down into TANKS, the catwalk and the mantle up to cell 2. Where the ports
cannot play a step yet it takes a logged staged shortcut. Its report lists each segment, the problems found and the shortcuts.
The path, blockers and shortcuts are in [re/playthrough/prison.md](re/playthrough/prison.md).

`playthrough_full.py` plays the whole game in one run (about 2 minutes): a new game, CHAOS and TANKS, the tower, CONTROL with the reactor shutdown, LANDPAD, BEACH, DIGSITE, TUNROOM, the alien city, the gravity ring and back to CONTROL's bike and the ending, in a single World / VM, so inventory, globals, HP and level state carry from level to level. Script processes linked to cameras (`LINKMETOCAMERAS`) pause and resume on camera switches in both ports, as the original does. It reaches `EXIT`; the shortcuts it still takes (fights its one-key punch loop does not win, a few walks and engine gaps) and the blockers, ranked, are in [re/playthrough/full.md](re/playthrough/full.md). `--difficulty medium` or `hard` plays the route at that level after the prison (Medium finishes on 1 of 27 RANDOM streams, Hard on none; `run_seeds.py` takes the same flag).

Untextured (flat and Gouraud) faces now follow the original lighting. The game's single light
has zero strength and zero ambient, so each such face takes the darkest colour of its palette
ramp; the original's own framebuffer confirms this. Textured faces use their source palette
indices directly, as the original rasterizer does; each room's palette supplies their colors.
Textured index 255 is transparent. The original applies no depth haze (`PALFADE.IFF` is
loaded but unused), so neither does the port.

For players: [PLAYER_GUIDE.md](PLAYER_GUIDE.md) (setup, controls, known differences) and [CHANGELOG.md](CHANGELOG.md) (what is in each build, known issues, save compatibility).

The public source repository is a filtered export of the private working repository, one commit per sync, made by `tools/publish_public.sh` (`STRUCTURE.md` lists what it leaves out and checks); the docs still mention paths it leaves out, such as `re/decomp`.

See [STATUS.md](STATUS.md) for progress and next steps, [STRUCTURE.md](STRUCTURE.md) for the
repository map and dependencies, and [re/NOTES.md](re/NOTES.md) for format and engine findings.

## Legal

BioForge is a trademark of Electronic Arts Inc. This is an unofficial fan port; it is not affiliated with, endorsed or sponsored by Electronic Arts, Origin Systems or GOG. It includes no game data: you need your own copy of BioForge.
