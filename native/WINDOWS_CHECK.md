# Windows check for the SDL3 shell

This is a brief for a Claude Code session on a Windows PC. Its job is to show that `BioForgeCore`, `BioForgeHost` and the SDL3 shell (`BioForgeSDL`) build on Windows, that their tests pass with the game data, and that the shell plays. This is phase 3 of "Windows and Linux" in `ROADMAP.md`. Phase 1 (the engine) has been checked on Windows; the Host suite and the shell have not. Then it builds the Windows package players would get and checks it (phase 4: "Packaging" at the end). Everything in the hand checklists should work: the shell has the keyboard, the mouse, controllers, sound, AdLib music, General MIDI with a SoundFont (TinySoundFont, the C target `CTinySoundFont`, which must compile in the developer shell), and a settings screen (F1).

## Setup (done by the person at the PC)

1. Install Swift 6.4 or later from swift.org, following its Windows guide, which also installs the Visual Studio Build Tools it needs. `winget install Swift.Toolchain` installs Swift only; then add the Build Tools from an administrator PowerShell:
   `winget install --id Microsoft.VisualStudio.2022.BuildTools -e --override "--passive --wait --add Microsoft.VisualStudio.Component.VC.Tools.x86.x64 --add Microsoft.VisualStudio.Component.Windows11SDK.22621 --add Microsoft.VisualStudio.Component.VC.Redist.14.Latest"` (the last component is for the packaging step: the Visual C++ runtime DLLs the zip carries)
   Restart the terminal (or the Claude app) afterwards, so `SDKROOT` and the new `Path` are seen.
2. Download SDL3: the latest 3.4 release's `SDL3-devel-3.4.x-VC.zip` from github.com/libsdl-org/SDL/releases. Unpack it so that `native\ThirdParty\SDL3\include\SDL3\SDL.h` and `native\ThirdParty\SDL3\lib\x64\SDL3.lib` exist (the zip has a versioned top folder: strip it). Or unpack it anywhere and set `SDL3_DIR` to that folder. `native\ThirdParty\` is ignored by git.
3. Install BioForge from your own GOG account. Note the folder that contains `BIOFORGE.EXE`, and check that `GAMEDAT` is next to it, as in the GOG layout.
4. Clone the repo, check out the branch named in the request, and open a Claude Code session in the repo.

## What the session does

Read `CLAUDE.md`, `README.md` and `STRUCTURE.md` first. Then run these in PowerShell. `swift build` needs the Visual Studio developer environment (otherwise: "could not find CLI tool `link`") and `SDKROOT` (otherwise: "unable to load standard library"):

```powershell
& "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\Common7\Tools\Launch-VsDevShell.ps1" -Arch amd64 -HostArch amd64 -SkipAutomaticLocation
cd native
swift build
$env:BIOFORGE_DATA = "C:\path\to\Bioforge"   # the folder with BIOFORGE.EXE
swift test
```

`swift test` runs the Core, Host and SDL suites. The macOS and Linux results to compare against are in `STATUS.md` (look for "Portable engine"). Expected:
- Everything passes. Only the Apple-only suites are compiled out (Core ML, the art-pack codec, `PackBenchTests`).
- `FullRunTests` (new game to the end) and the fixture parity suites must pass unchanged. The fixtures come from the Mac.
- The Host suite has never run on Windows: it needs the `settings.json` writes (`.atomic`), the temp folder and `%APPDATA%` paths to behave.
- The SDL suite runs the shell headless (SDL's own offscreen driver) and needs `SDL3.dll` to be found: if the tests fail to start with a missing DLL, copy `native\ThirdParty\SDL3\lib\x64\SDL3.dll` next to the test executable in `.build\debug`.

Then run the shell headless, as a smoke test. It copies the DLL next to the program and steps 900 ticks of the new game with no waiting:

```powershell
Copy-Item ThirdParty\SDL3\lib\x64\SDL3.dll .build\debug\
$env:SDL_VIDEO_DRIVER = "offscreen"; $env:SDL_AUDIO_DRIVER = "dummy"
$env:BIOFORGE_SDL_SMOKE = "900"; $env:BIOFORGE_SDL_SHOT = "$PWD\shot.bmp"
.build\debug\BioForgeSDL.exe
```

It must print one line, `smoke: level TITLE tick 900 camera NONE frame 50e055142d28b295`, and exit with code 0 (`$LASTEXITCODE`). The `frame` digest is the same on the Mac and on Linux; if it differs on Windows, report it. `shot.bmp` is the last picture: the opening's planet and spaceship. If the offscreen driver cannot start on Windows, say what SDL reports and try without `SDL_VIDEO_DRIVER` (a window opens briefly).

If something fails:
- **Foundation differences on Windows** (paths such as `URL.path` returning `/C:/...`, `.atomic` writes, the temp folder, case of file names): fix them in the engine or the host with the smallest change. macOS behaviour must stay identical.
- **A different simulation result** (a fixture, a digest or `FullRunTests` differs): don't patch around it. Find the first tick that differs with `FULL_RUN_TRACE`, name the maths call involved (`atan2`, `sin`, `cos`, `hypot` and others), and report back. The fix is decided on the Mac, because it affects the Python port and the Mac results too.
- **SDL does not build or link** (`SDL3/SDL.h` not found, `SDL3.lib` not found, unresolved `SDL_` symbols): check the two paths from Setup step 2 and `SDL3_DIR`; report the exact message. `Package.swift` adds `-I` and `-L` for them on Windows.

Commit fixes to the same branch, without AI attribution. Report the `swift build` result, the `swift test` totals, the smoke line and every change made.

## Then, for the person at the PC

Run `.build\debug\BioForgeSDL.exe` from `native` (with `SDL3.dll` beside it; no `BIOFORGE_DATA`, so it asks for the folder as a player's copy would) and check by hand. Note anything that fails or looks wrong.

- The first start asks for the game folder (a message box, then the folder dialog); a wrong folder says so and asks again; after a restart it does not ask.
- The picture is sharp (no blur between the big pixels) and 4:3; the window keeps that shape when resized, and the picture fills it. F11 (or Alt+Enter) goes full screen and back.
- New game: Escape skips the intro; the mouse picks a difficulty in the dialog. Then play with the default keys (arrows walk, Shift runs, C combat, A with an arrow kicks, Alt with an arrow punches, Space uses; `PLAYER_GUIDE.md` has the table).
- An Xbox-style controller, plugged in while the game runs: the left stick and D-pad walk, A uses, Start opens the options dialog, where the stick moves the pointer and A clicks.
- Sound effects and AdLib music, from the intro on. Alt+Tab away: the game and its sound pause; back: they resume.
- General MIDI: with no `.sf2` anywhere, F1 > Music > General MIDI shows "No SoundFont (.sf2) found" and AdLib keeps playing. Put any General MIDI `.sf2` in `%APPDATA%\BioForge`, restart, choose General MIDI: the music plays through it, in time, and `Logs\BioForge.log` names the file. Switching back to AdLib and again to General MIDI works without a restart.
- Save in the options dialog (S), quit, start again, load (L): Lex is where he was saved.
- F1 opens the settings screen (also the controller's View button in the options dialog): change Readable Text and Aspect Ratio and rebind a key; quit and start again: all three are kept.
- Files appear under `%APPDATA%\BioForge`: `settings.json`, `Logs\BioForge.log`, `Saves\GAME1.IM1` after a save, `Autosaves` after a level change.

## Packaging (phase 4), after the checks above pass

The same session then builds the Windows zip players would get, and checks it. In the same developer PowerShell, from the repository root:

```powershell
native\package-windows.ps1 -Data "C:\path\to\Bioforge"   # the folder with BIOFORGE.EXE
```

It builds a release `BioForgeSDL.exe` for the Windows subsystem (no console window) with the icon and version resource (`native\package\windows\BioForge.rc`, compiled with `rc.exe`), finds every DLL it needs by walking `dumpbin /dependents` (`SDL3.dll`, the Swift runtime and Foundation DLLs from the Swift install, the Visual C++ runtime from the Build Tools' redist folder; Windows' own DLLs are left out), and writes `native\dist\BioForge-<commit>-windows-x64.zip`: one folder with those files, `README.txt`, `NOTICES.txt` and `licenses\`. It then unzips it into a fresh temp folder and runs the smoke test there with `PATH` cut down to Windows' own folders and a throwaway `%APPDATA%`, so a DLL missing from the zip fails here. It must print `smoke: level TITLE tick 900 camera NONE frame 50e055142d28b295` with exit code 0.

If something fails:
- **rc.exe or dumpbin not found**: the shell is not the developer PowerShell (step above), or the Windows SDK component is missing from the Build Tools.
- **No Visual C++ redist folder**: the Build Tools lack `Microsoft.VisualStudio.Component.VC.Redist.14.Latest`; add it with the Visual Studio Installer (Modify) or the `winget` line from Setup step 1, restart the shell, run again.
- **`-Xlinker` flags rejected** (`/SUBSYSTEM:WINDOWS`, `/ENTRY:mainCRTStartup`, the `.res` file): report the exact message; the fallback is a console build without the three flags, noted in the report.
- **A DLL not found, or the smoke run fails with exit code `-1073741515` (0xC0000135, a DLL missing)**: report the DLL list the script printed; `dumpbin /dependents` on the unzipped files shows which one.

Report the DLL list, the zip's size, the smoke line and every change made. Don't upload the zip anywhere.

### Then, for the person at the PC

Copy the zip to a folder that has never had BioForge in it (or another PC without Swift or Visual Studio), unzip it and start `BioForgeSDL.exe` by double-click.

- No console window opens; Explorer and the taskbar show the BioForge icon; Properties > Details shows the description and version 0.1.
- The program is not signed, so SmartScreen may say "Windows protected your PC": "More info", then "Run anyway". Note whether it appears. (Signing is optional and not done; it would need a code-signing certificate.)
- The first start asks for the game folder, then plays as in the checklist above: sound, the music, a controller, F1, a save and a load.
- `README.txt`, `NOTICES.txt` and `licenses\` are in the folder.
