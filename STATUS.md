# BioForge port — status and to-do

Handoff note for any agent picking up this project. Read this first, then
`STRUCTURE.md` (where things are) and `re/NOTES.md` (the detailed technical reference: file
formats, engine functions, semantics). Last updated 2026-11-20.

## Current state (2026-11-19)

- **Where the port is.** A faithful port of BioForge, in two versions: the Python reference interpreter (`re/interp`) and the native Swift
  port (`native/`: `BioForgeCore`, `BioForgeHost`, `BioForgeApp`, and the SDL3 `BioForgeSDL` / `BioForgeSDLShell` / `CSDL3`). The Mac app
  plays the whole game from the intro to the ending (keys and controllers, sound, GM or AdLib music, subtitles, PIMM screens and
  monitors, the options dialog with nine `GAMEn.IM1` slots, autosaves, Game > Language, Readable Text, High-Resolution Art, Report a Bug).
  The scripted full run reaches the end in both ports. Medium and Hard are audited (every difficulty use is ported) and not part
  of the beta; the scripted run plays them with `--difficulty` and finishes Medium on 1 of 27 streams, Hard on none.
- **Windows and Linux** (ROADMAP "Windows and Linux (Steam Deck)"): phases 1, 2 and 4 are ticked; phase 3 waits only on the Windows run
  on the user's PC. The Linux AppImages build and pass headless smoke runs in containers. Nothing has been run by hand on Windows or a
  Steam Deck, and nothing is published.
- **Gates** (latest): `run_tests.py` OK; `swift test` OK; seeds 25/27; saves 29/29; control 29/29. Playthrough gates run only for
  game-logic changes (the commands are in README and CLAUDE.md).
- **What waits on the user:** a playthrough to the end in the Mac app (ROADMAP milestone 7), then the bugs it finds; notarization of
  the Mac build (blocked on Apple's updated developer agreement); running `native/WINDOWS_CHECK.md` on a Windows PC.
- **Next:** ROADMAP milestones 7 and 8 for the beta (the playthrough and notarization), then "Bugs to fix later" there.
  Later wishes (a controller on more screens, other platforms' polish) stay behind a faithful port.

## Fix 2026-11-21: an idle requested in a walk starts in the next one (the zero-g height)

- From the code (re/NOTES.md "Lex's height in the zero-g room"): the frame updates every figure before the scheduler walk
  (`1150.c:950-970`), so figures and scripts are not interleaved by slot, as #182 had guessed. The cause is the idle request: AI ON
  (`10a8:1f2e`) -> `FUN_1098_0745` -> `1098:0e49(fig, name, 1, 0)` makes the motion task without running it, and only its first run
  (`10e0:0055`) starts the motion. Made during a walk it runs in the next one, after the figure update in between; a STOPMOTION before
  that drops it. Both ports now defer it (`request_idle` / `requestIdle`, started at the end of the next walk), with tests in both.
- Entered by TO_0G_USE Lex now floats at -5539 as in the original, and the full run flies into TO_FINAL with nothing staged: the
  `zero-g-height` shortcut is gone. Not ported: COMBATMODE's own idle request (`10d0:1b69`; the ports only set the flag).
- Gates: `run_tests.py` OK, `swift test` OK, seeds 27/27, saves 28/29 (the restart after `hardsuit` loses the Captain), control 27/29
  (after `reactor-room` the Captain; after `operating-room` a quake between the levers lets the reactor timer run out 3 ticks after
  the console opens). Harness timing, not the port change; not tuned further (decided with the user). Three harness steps were made
  sturdier (re/playthrough/full.md).

## Release prep 2026-11-21: v0.1 preview

- Decided with the user: release v0.1 as a preview before the hand playthrough (ROADMAP milestone 8), from a new public MIT repository
  (a filtered export without `re/decomp`, `re/out`, AGENTS.md and CLAUDE.md: `tools/publish_public.sh`), downloads on its GitHub
  Releases, a page on the author's website. This repository stays private.
- Done: `LICENSE` (MIT, with the game-data and trademark note); README opens with a player section; CHANGELOG, PLAYER_GUIDE for the
  preview; a bug report template (`.github/ISSUE_TEMPLATE`); `build-app.sh --sign` (universal, hardened runtime, timestamp, original
  icon, the art model) and `notarize.sh`; Debug > Save Frame as PNG and `BIOFORGE_SHOT` for the website screenshots (4x art, Readable Text).
- Open: the public repository's name; notarization (Apple's updated developer agreement); the Linux packages for the release; the
  Windows zip (the PC run); the website page; tag and upload. The HDcube model's author, Venomalia, allowed shipping the converted model (2026-11-21): signed builds include it.

## Fix 2026-11-21: the LANDPAD ledge stop traced (harness)

- The stop at the LANDPAD ledge (TO_BCH never loads BEACH) after the `reactor-room` save and the `forklift` restart was the harness's
  `battery_trip`: it ran the ledge at x 25700 and stopped at each point, in the ledge bots' reach. Traced tick by tick: SUPER_REC_MR and
  recoils from y -169500 took Lex from 79 HP to 9, and a last bolt killed him near TO_BCH. The first way down already uses `ledge_run`
  (the west side, x 23800, at a run); `battery_trip` uses it now too. Harness only, no port change.
- Gates: `run_tests.py` OK; seeds 25/27 (losses 3, 15, as before); saves 29/29; control 29/29 (was 28/29).

## Scheduler: a woken waiter runs in the next walk 2026-11-21

- From the decompile (re/NOTES.md "A woken waiter runs in the next walk"): when a CALL child, a SUSPENDWHILE process or a missile a
  process waits on ends, the original only clears the waiter's wait (`1238:077f` -> `1230:177a`, flag 0x40) and the scheduler runs it in
  the next walk; a task created during a walk (PROCESS from a `[` timeline) also first runs in the next walk. Both ports ran the waiter
  inside the child's finish; they now hold it for the rest of that walk (`hold`). Every such wake-up is one tick later.
- Live (DOSBox-X): in the zero-g room the original floats Lex at z -5539 because LEAVETUBEROOM's STAND never reaches R before
  TO_0G_USE's GO, the ports at -4525, too tall for the exit corridor. (CORRECTED 2026-11-21, below: the cause is the idle request's
  motion task, not the walk order; the `zero-g-height` shortcut is gone.)
- The harness was tuned for the new timing (re/playthrough/full.md): MECHO2's cover dash starts at once, the Captain is walked up to
  from beyond REACH + 3000, Guard 1 is fought with BIOREPAIR from 50 HP, Drogg 3 1800 units clear of the glass, and the reactor
  console waits out a quake. Gates: run_tests and swift test green, seeds 25/27 (losses 3, 15), saves 29/29, control 28/29: the
  restart after `forklift` stops at the LANDPAD ledge (TO_BCH never loads BEACH), the stop main already records after `reactor-room`.

## Fix 2026-11-20: music measures and song switches as the code has them (General MIDI and AdLib)

- Read from AILADLIB.DLL and seg 1198 (re/NOTES.md "AdLib music" > "Measure count", "Music state machine"). The measure count
  is the value of the last 0x77 controller (every song numbers them 1..N); the time signature drives only the beat count. The
  earlier lead (measures from the time signature) was wrong.
- What changes in the ports (`musicseq.py`, `Music.swift`): a request reads the transition table at measure 1, because the bar
  counter's only step needs a request for the current song, which the request handler turns away. The switch waits until the
  song's measure count moves on, checked by the music task's update after the request and, INFERRED, once per 30 Hz tick, not at
  the bar's own step. A transition ends at the next update (it stores its count right after its start, 0), so only its first
  notes sound. A NEXT jump no longer counts as a new measure, and an ended song restarts at the next update.
- Tests: the bar-counter tests are replaced by tests for the measure count, the measure-1 lookup and the one-update transition;
  the positive-transition parity case is now 10 -> 21 (11 -> 27 is a direct switch at measure 1). Music and AdLib digests
  regenerated in both twins.
- Open: the update's rate (once per game tick is inferred). A DOSBox-X MIDI capture of a song change with a transition would
  confirm the short transitions live; it was not run (DOSBox-X was busy with the fight sampler).

## Fix 2026-11-20: the full run on Medium and Hard (`--difficulty`)

- `playthrough_full.py --difficulty medium|hard` and `run_seeds.py --difficulty` play the prison at Easy and set the level after
  `guard1` (shortcut `difficulty`). Easy is unchanged: its default stream and `full_run.json` regenerate byte-identical.
- Seeds (`run_seeds.py --seeds 26`): **Medium 1/27** (the default stream finishes, Lex 100), **Hard 0/27** (the tower deck). Medium's
  losses: GRDCON 11, GRDHANG 12, GRDHALL 2, seed 4 in the prison.
- Route changes above Easy: a quicker fighting rhythm and earlier repairs, a curved dash to the tower bots' firing spot, GRDCON's heal
  to 100 and an error when the routine stops with him up, GRDHANG's rhythm handed back, GRDHALL required (BLASTER2 is AIRMECHO's gun),
  and a step forward before a big turn on the BEACH zip blocks (the turn drifted Lex into the sea).
- Blockers: the battery runs out across GRDCON, GRDHANG and GRDHALL (GRDHALL takes 114 of the bike's 129), Lex reaches the BEACH
  with 13 and the Captain wins most streams, and Hard's tower bots. Other attacks, blocking, repair thresholds and mid-fight medkits
  did not help; a fighting routine that reacts to the guard is the open work. Details: `re/NOTES.md` "Medium and Hard played through".
- Gates (Easy): `run_tests.py` OK (with new `test_run_seeds` cases for the flag), `swift test` OK, `full_run.json` unchanged, seeds 24/27
  (losses 4, 24, 26), control 29/29, saves 28/29: the save after `reactor-room` stops at the LANDPAD ledge (TO_BCH never loads BEACH),
  the same on main as of #175, so not from this change; not traced.

## SDL app: General MIDI 2026-11-20

- The SDL app (Windows, Linux, Steam Deck) plays the General MIDI arrangement through TinySoundFont (MIT, `tsf.h` v0.9 vendored
  unmodified as the C target `CTinySoundFont`, built only with the SDL targets; the user approved the file). `GMStream`
  (`BioForgeSDLShell/SDLMIDI.swift`) is the `AudioScheduler`'s `MIDISynth` and renders a third `SDL_AudioStream` (float stereo,
  44100 Hz). Each `send(_:after:)` lands at `clock + round(after * 44100)` on its own timeline (`clock` = frames rendered, as
  `OPL2Stream` counts chip samples), never before the message queued ahead of it; the render splits each block at the messages'
  samples. One lock covers the queue and every tsf call; voices and channels are allocated when the SoundFont loads.
- No SoundFont is bundled (decided with the user): `SoundFontSearch` takes the `"SoundFont"` setting, the first `.sf2` in the data
  folder, one next to the program (or in the AppImage's `share/BioForge`, or beside the AppImage), then common Linux system files.
  It loads the first time General MIDI is wanted. Without one (or with a file that isn't a SoundFont 2), General MIDI plays as AdLib,
  as before; the log and `BioForge.log` say where to put one, and the settings screen's Music row (now General MIDI, AdLib, Off)
  notes it. The Mac app is unchanged.
- Tests: `GMStreamTests` (offline, a sine SoundFont written at run time: a note sent with 0.25 s starts exactly at frame 11025, in
  512-frame blocks and in one block; the delay counts from the playhead; order kept; all notes off; bank 128 drums; refused files;
  the search order) and four `SDLAudioTests` on the disk driver (General MIDI audible with a SoundFont and the chip silent; AdLib
  without one or with a bad file; switching at run time). macOS: SDL 36, Host 120 pass; the Mac app builds. Linux arm64 and
  x86_64 (Rosetta) in `container` (`swift:6.4`, SDL 3.4.2): `CTinySoundFont` compiles without warnings, SDL 36 and Host 118 pass, and the smoke run gives
  the usual `frame 50e055142d28b295`, logging that no SoundFont was found. `native/package-linux.sh` builds both AppImages
  (x86_64 24.1 MB, aarch64 23.2 MB: no bigger than before, TinySoundFont is linked in, its licence in `licenses/`); they pass the
  library check and the smoke run in clean Arch Linux and Debian containers with the same digest.
- Not checked: listening with a real General MIDI SoundFont (none on this machine), so the gain (`GMStream.gainDB` = 0 dB) is not
  tuned against the effects and AdLib; the Windows build of the C target (`WINDOWS_CHECK.md` covers it).
## Fix 2026-11-20: the XMIDI layer as AIL runs it (General MIDI and AdLib)

- Checked in AILADLIB.DLL's shared XMIDI code (re/NOTES.md "AdLib music" > "XMIDI layer") and ported to `musicseq.py` and
  `Music.swift`. Events now run in file order within a step; the ports had sorted note ons last, which changed 1621 ticks.
  Notes go through the driver's 32-entry note queue: they end before a step's events, in queue order, and a zero-length note
  ends one step later.
- A stop or pause ends the queued notes and turns sustain off where it was on, with no all-notes-off. A sequence's end runs
  only the sustain release. Resume resends the sequence's cached controllers, bend and program. Entering a song at a branch
  marker no longer replays the state before it.
- The player timeline is in integer 120 Hz steps. Music and AdLib digests regenerated in both twins; new Python tests for each
  rule. `AudioSchedulerTests.requestsComeBeforeLevelChangesAtEqualTicks` now tells the orders apart with a stop and a level
  change at one tick: the silent stop made the old tick-0 case indistinguishable.
- Not ported: a stop while paused leaves the original unserved until a resume (unreachable: no script pauses). The 0x77 lead
  left open here is settled in the entry above.

## Fix 2026-11-20: AdLib driver assumptions settled

- Read from AILADLIB.DLL (a scratch Ghidra import, re/NOTES.md "AdLib music") and seg 1198: the game serves the driver at 60 Hz
  with relative tempo 200, so it runs two 120 Hz XMIDI steps per serve and writes registers on a 60 Hz grid, and the priority pass
  comes every 24 serves (0.4 s, not 0.2 s). The serves run only while a song is loaded and the music is not paused, and the pass's
  counter is reset only at boot. Both ports now do this (`adlib.register_writes` takes the musicseq trace;
  `MusicSequencer.takeServingChanges` feeds `AdLibSequencer.advance`). This replaces the assumption of a 120 Hz serve from music
  time 0.
- Swift reset a slot's 0xB0 copy on note on; the driver (and Python) keep it, which shows when a slot that got its voice without
  a register write is keyed off. Fixed.
- Confirmed as ported: velocity table index, init registers and controllers (110/111 added to the docs), pan stored but never
  read, rhythm mode never used, timbre lookup at install, round robin start, the 0644 quirk. Corrected in NOTES: the driver's DS
  is a separate data segment, not an alias of the code segment.
- Still open: the chip model against a real YM3812, the timer jitter and phase, and the counter's phase at a new game (a DOSBox-X
  DRO capture would settle the first two). Leads for the XMIDI layer shared with General MIDI (stop, zero-length notes, branch
  entry, resume) are listed in NOTES and not changed here. Gates: run_tests OK, swift test OK (music only, no playthrough gates).

## Fix 2026-11-19: BREAK n and Hal Mecho's speeches

- `BREAK n` was the last open script-engine question. The engine numbers SWITCH statements through the whole file (`FUN_10c0_01cc`)
  and the compiler writes the innermost switch's number into each BREAK; the ports numbered them per block, which caused every
  `BREAK n != innermost switch index` warning. All 837 numbered BREAKs match (`test_interp.ParseAll`), so the jump target never
  changed and the warning now stays silent on the shipped data.
- The six inline `IF ... THEN BREAK` lines of HALMECHOSPEECHES were never numbered, and the original does nothing for them
  (`FUN_10d0_0b77`, `ERR_BREAK_NOT_PREPROCESSED`): Hal Mecho's speeches now follow their fixed waits instead of each waiting for
  the last clip to end. Both ports; Swift fixtures and the full-run transcript regenerated. Gates: run_tests OK, swift test OK,
  seeds 24/27, saves 29/29, control 29/29. re/NOTES.md "BREAK n: switches are numbered per file".

## Fix 2026-11-19: save_resume_check reported timeouts many times

- A child past `--timeout` was killed and reported, but stayed in the child list until reaped, so it was reported again on every
  pass; a child that had finished but was not reaped yet could also be reported as a timeout beside its real row. The summary then
  counted rows, not boundaries ("24 of 52"). `kill_late` now reaps finished children first and kills, reaps and reports a late one
  once. Checked: `--timeout 20` on two boundaries gives one timeout row each (0 of 2); two that finish give 2 of 2.
## Windows and Linux, phase 4: packages 2026-11-19

- Linux: an AppImage (chosen over Flatpak, which only reaches the Steam Deck's Discover store through Flathub, so it waits on the
  licence and on publishing). `native/package-linux.sh` builds `native/dist/BioForge-<commit>-x86_64.AppImage` (the Steam Deck's)
  and `-aarch64` in `container` (PR #169): `native/package/linux/build.sh` in `swift:6.4-jammy` (glibc 2.35; the default `swift:6.4`
  is Ubuntu 26.04 with glibc 2.43, too new for SteamOS), SDL 3.4.20 from its tarball with every backend dlopened, the Swift runtime
  linked statically, the AppImage type2 runtime `20251108`; pinned SHA-256s. The binary needs only glibc 2.35, GCC 12's libstdc++
  and the bundled `libSDL3.so.0`; the build fails otherwise. About 23 MB each.
- Both pass the smoke run (`smoke: level TITLE tick 900 camera NONE frame 50e055142d28b295`) in a clean container with no Swift or
  SDL: Arch Linux for x86_64, Debian 12 for arm64, through `APPIMAGE_EXTRACT_AND_RUN=1` (no FUSE in a container). Under Rosetta the
  x86_64 one runs from a copy with the `AI\2` mark in its ELF header cleared, which Rosetta refuses; real x86_64 machines ignore it.
- Windows: `native/package-windows.ps1` (PR #170) builds the zip on the PC: a Windows-subsystem exe with icon and version resource,
  `SDL3.dll`, the Swift runtime DLLs and the VC++ runtime found through `dumpbin /dependents`, then a smoke run of the unzipped copy
  with a bare `PATH`. Not run yet; it is part of `native/WINDOWS_CHECK.md`, so the same Windows session does phases 3 and 4.
- Every package carries `native/package/README.txt`, `NOTICES.txt` and `licenses/` (SDL3 zlib with its HIDAPI and yuv2rgb notices,
  Swift's Apache 2.0 with the runtime exception, ICU's Unicode licence). No game data, no art model.
- Steam Deck (`PLAYER_GUIDE.md`): no code change was needed. The shell already starts full screen on `SteamDeck=1`; Steam's
  `SDL_GAMECONTROLLERCONFIG` and `SDL_GAMECONTROLLER_IGNORE_DEVICES` reach SDL3 unchanged (the AppImage's `AppRun` is a plain link to
  the program), so the first gamepad is Steam's virtual one, and no Steam Input template is needed. The guide's path: first start in
  Desktop Mode to pick the folder, then Add a Non-Steam Game; `BIOFORGE_DATA=... %command%` as the fallback.
- Open: the Windows run; a real Linux desktop and Steam Deck (the FUSE start, Game Mode, the default controller layout, the folder
  dialog and message boxes in Game Mode); the project's licence and a legal look at `re/decomp` before any package is shared
  publicly; Windows code signing (unsigned means SmartScreen warnings); Flatpak/Flathub once publishing is decided.

## Windows and Linux, phase 3: the SDL3 shell 2026-11-19

- `BioForgeSDL`, a second, smaller app on SDL 3.4 for Windows and Linux, runs the game on the same engine and `BioForgeHost` as the
  Mac app (PRs #161 to #167). Built on Linux and Windows; on the Mac only with `BIOFORGE_SDL=1` (Homebrew `sdl3`), for development.
  `CSDL3` links SDL by pkg-config (`libsdl3-dev`), on Windows from `native/ThirdParty/SDL3` or `SDL3_DIR` (the official VC zip).
- What it does: a window keeping 4:3 (or 16:10), F11 / Alt+Enter full screen (on by default on a Steam Deck); the 320x200 picture
  as RGBA in a streamed texture with SDL's PIXELART scaling (`PictureLayout`, `FrameRGBA`); the game folder from `BIOFORGE_DATA`,
  the settings file or a folder dialog, with the `HostText` messages; keys (SDL scancodes are the HID usages the bindings use), the
  mouse with the game's pointer warp and the cursor rules of the Mac; `SDL_Gamepad` controllers polled at 60 Hz into `PadTracker`;
  effects, AdLib and General MIDI (TinySoundFont, with the player's SoundFont; AdLib without one) on three `SDL_AudioStream`s fed by `AudioScheduler`; a settings
  screen (F1, or Back / View in the options dialog) for the Mac's menu settings and both bindings, drawn in `DATA/SMALL.FNT`.
- Files: XDG folders on Linux (`~/.local/share/BioForge`, `~/.local/state/BioForge`, `~/.config/BioForge/settings.json`),
  `%APPDATA%\BioForge` on Windows, through `HostPaths.linux` / `.windows` and `FileSettingsStore` (a JSON file).
- Tests: `BioForgeSDLTests` (23) run the shell headless (offscreen or dummy video, disk or dummy audio) with real SDL events: a new
  game from TITLE to CHAOS by keys and clicks, walking, the options dialog, a virtual gamepad, audible effects and AdLib, pause, the
  settings screen and its persistence. Host 116 on Linux (118 on macOS). Linux arm64 and x86_64 (Rosetta, the Steam Deck's) pass all
  of Core (677, the full run included), Host and SDL; `BIOFORGE_SDL_SMOKE=900` gives the same frame digest on both and on the Mac.
- Not checked yet: Windows (the next run on the Windows PC, `native/WINDOWS_CHECK.md`; the Host suite has not run there either), a
  real Linux desktop or Steam Deck (the container is headless), and anyone listening to the SDL sound. Not in this phase: General
  MIDI off the Mac, High-Resolution Art (phase 5), packaging (phase 4, done; see above), Report a Bug off the Mac (needs a zip), the mouse on the
  settings screen.

## Medium and Hard checked 2026-11-19

- Audit of every difficulty use (re/NOTES.md "Difficulty: every use, and Medium and Hard checked"): all engine and script uses are
  in both ports; Escape on the difficulty dialog does nothing in the original either (flags 512 lack bit 2). New tests: a save on
  Hard loads as Hard (`test_save.test_hard_stays_hard_after_a_load`, `SaveLoadTests.hardStaysHardAfterALoad`).
- Smoke run with Lex kept alive: Medium reached the beach (19 of 31 legs), Hard Drogg 1 (15); both stops are the scripted route's
  timing, not game bugs, and no new warnings appeared. Playing them to the end needs the route tuned per level; not part of the beta.

## Windows and Linux, phase 2: the shared host layer 2026-11-19

- New SwiftPM module `BioForgeHost` (Foundation and `BioForgeCore` only, builds on every platform): what the Mac shell did that is
  not AppKit. `InputRouter` (keys as `KeyEvent`s with HID usages, the controller, the pointer, against `GameInput`, which `World`
  satisfies), `TickClock` and `GameHost` (the 30 Hz loop, catch-up of at most 8 ticks, suspend, the 2 s TITLE hold, behind
  `HostPlatform`), `AudioScheduler` (the mixer, OPL2 and music feed with both `keepUp` calls, behind `HostAudio` and `MIDISynth`),
  `HostPaths`, `SettingsStore` (in Core; `UserDefaults` conforms), `Autosave`, `BugReport`, `HostText`, `HostLog`.
- The Mac app keeps AppKit, Metal, AVAudioEngine and the DLS synth, the menus, sheets and panels, and runs on the module with no
  visible change. Key bindings are USB HID usages now (what SDL uses): `MacKeyCodes` translates at the event edge, and bindings saved
  as Mac key codes migrate once to `KeyBindingsHID` (`BindingsMigration`; the old entry stays).
- Tests: `BioForgeHostTests` pin the texts, folders, autosave, report folder, the routing rules (a recording `GameInput`), the clock,
  the migration, and the GM, AdLib and effects output by SHA-256. They pass on macOS and on Linux in `container` with the same digests.
  Not run on Windows yet.
- `MonkeyTests` now presses its keys and clicks through `InputRouter` (default bindings; the Core tests depend on the Host for this),
  no longer a hand-kept copy of the routing, which had drifted: the options dialog got `optionKey` names for the arrows where the app
  sends the monitor keys. `InputRouter` is no longer `@MainActor`, so the 30 legs still run in parallel. 40 trials a leg, before and
  after: no stuck, drifting or unmovable trials; only the fights' death counts move (tanks-back, temple).
- Next: phase 3, the SDL3 shell on top of `GameHost` (done; see above).

## Windows and Linux: posed vertices match the Mac 2026-11-19

- glibc and the Microsoft C runtime round `cos`/`sin` of 25 joint angles differently from Apple's libm in the last bit, which changed
  the posed-vertex bits of 17 to 18 figure types (`WorldTests.soundTableAndAssets`) off the Mac. `Mat3.rotated` now takes them from
  `JointAngleTable`: Apple's bits for angles -256 to 511, generated on macOS (the whole test suite, the full run included, uses -140 to
  255), with libm outside that range. On the Mac the table equals libm bit for bit (`JointAngleTableTests`), so no result or fixture
  changes. Linux arm64 and x86_64 (`container`, Rosetta): all 687 tests pass, the full run included, with nothing left over. Windows not
  re-run yet (it needs the Windows PC; `native/WINDOWS_CHECK.md`).

## High-Res Art: menu and monitor elements plain-doubled 2026-11-19

- Playtest: in the options dialog at 2x the << >> arrows, slot digits and buttons looked smeared. `MonitorScreen.render(into:pack:)`
  now draws every element (buttons, arrows, digits, scale bars, gauges) by plain enlarging, as the text already was; the background
  picture and the hand pointer still come from the pack. Covers the options dialog, PIMM and all monitors. The pack builder still makes
  the element frames (unused now; dropping them needs `pixel_pack.py` in step and a format bump). Tests:
  `HiResScreensTests.optionsElementsArePlainDoubled`, `packFramesPaintMonitors`.

## Fix 2026-11-19: speech lost its first words

- Playtest: after switching the language, spoken lines (the medical robot, Caynan) played only their last words. The live mixer places a
  sound at `origin + frame(tick)` on a timeline that runs in real time. Whenever no tick ran while the audio kept playing, every later
  sound started behind the playhead and was cut from the front, and the gap never closed. That happened with a menu held open (Game >
  Language), the 2 s TITLE hold, or a hitch the tick loop drops. `SoundMixer.keepUp` (called by the app's `SoundOutput.sync`) now moves
  the timeline so the next sound starts whole. The offline mix and the Python port are unchanged. Test: `SoundTests.soundAfterAStallStartsWhole`.
  The AdLib stream had the same flaw: after a stall every register write arrived late and was applied at the next block start, so
  the 120 Hz rhythm fell to the 30 Hz tick for the rest of the session. `OPL2Stream.keepUp` does the same for it (test:
  `AdLibTests.streamKeepsTheRhythmAfterAStall`). General MIDI goes to the synth as each tick produces it, with no timeline, so a stall
  doesn't shift it.

## Item events on the event walk 2026-11-18

- Pick-up, put-down and fire events now fire on the original's frame-event walk (FUN_1088_1854), as the sound cues do: one frame earlier
  than the ports had them (while frame N - 1 shows). One walk dispatches every event byte in both ports (`items.py` `event_walk`,
  `WorldItems.swift` `eventWalk`). re/NOTES.md "Motion sound cues and formatted sound names".
- Enemy shots leave sooner after their aim and land more often. The route harness was retuned:
  - AIRMECHO's dodge starts just before the gun comes up.
  - Lex runs straight to MECHO2's safe corner after the CONTROL ride.
  - He runs the LANDPAD ledge 7000 units from its bots.
  - After the Guard 1 fight he walks round the cell's hole to the BLASTER.
  - When the walk to the Captain's TONFA is blocked, he goes round it.
  - At GRDHANG he waits 3 ticks between blows (1 and 3 lose 3 of 27 streams up to that fight, 2 loses 5).
- Gates (with combat-leave merged): run_tests 847 / 72 / 94 and swift test 683 green, saves 29/29, control 29/29, seeds 24 of 27
  streams (losses 5: Lex reaches CONTROL's ride with 39 HP and MECHO2's first bolt kills him; 16: GRDHANG; 17: Guard 1). On the
  default stream the leg battery is short at the bike, so the run takes its battery trip before the ending.

## Fix 2026-11-18: the BioForge picture before the first room

- Playtest: after the difficulty choice the original shows the red BioForge picture (ROOMS/TITLE.CAM) before the first room; the port showed
  black. START.scr's `CAMERA SHOW TITLE` switched the screen to it, and it stays up through LOADLEVEL CHAOS (the original renders nothing
  during the load) until GOODMORNINGLEX's FADE HIDE. Both ports now draw a SHOW picture as the screen (also WARHEAD's RTRW white flash before
  STITLE). The original shows it for its load time; the app holds it 2 s (KNOWN_DIFFERENCES.md, ticks wait). re/NOTES.md "CAMERA SHOW
  pictures and the TITLE hold". From the code, not checked live. No game logic or random stream change.

## Fix 2026-11-18: options buttons light up under the pointer

- Playtest: in the original the options dialog's bars (EASY / MEDIUM / HARD COMBAT, the main panel, slots, audio, gamma, confirm)
  light up when the pointer is over them; in the port none did. The original's move handler highlights the button under the pointer
  (FUN_1250_19bc → 1278:0803): state 2, so frame 2, a brighter bar, and the label's brighter text colour; moving off takes it away
  (1278:0844), and the toggles SFXX / MSCX / SBTX keep their selection (3 ↔ 4). A panel also opens with the control under the pointer
  lit, and a default button (EXIT, OK, YES) is lit, with the pointer put on it, only until the mouse first moves. Both ports;
  re/NOTES.md "Options hover highlight". In-game monitor buttons already highlighted. From the decompile, not checked live.
- Presentation only: no game logic or random stream changes. The pinned options render hashes were regenerated from Python, and the
  reload / O dialog pixel sums (test_mechanics, MechanicsTests) moved because the hand now sits on the default EXIT button.

## Fix 2026-11-18: C leaves combat with the fists still up

- Playtest: pressing C a second time took Lex out of combat mode but left him in the fighting stance, so it looked as if C never
  toggled off. The original's C handler (10a8:1058) toggles the mode and then calls FUN_1098_0745, which requests the new mode's idle
  (stand or atk_stand); LEX_LEAVE_COMBAT itself only restores the hand textures. Both ports now request that idle when Lex is idle.
  ASSUMPTION: only from an idle motion.
- The route harness was retuned for the moved fight timing (no game logic): `HEAL_BELOW_RICH` 75 (Marine 4 and Marine 5 keep 60 for
  the bike's battery), GRDHANG punch delay 2, Captain repair below 100 with rhythm 9 and step-in 2000, and a retry of the TONFA
  approach. Swift full-run transcript regenerated. Gates: saves 29/29, control 29/29, seeds 24/27 streams (losses 9, 16, 18).

## Fight and footstep sounds 2026-11-18

- Playtest report: fighting Caynan had no fight sounds. Both ports now play the motion sound cues (event bytes 0xfd..0xf9 in the motion
  headers: footsteps, swings, grunts, recoils, the nurse's activation), walked as FUN_1088_1854 walks them. Every name the engine
  formats now goes through its cutting lookup (1118:0044), so `_CAYNAN_HITS_LEX_CE31` plays `_CAYNAN_HITS_LEX` and blocks play `_block`.
  Blocks and the guard clank are no longer positional. re/NOTES.md "Motion sound cues and formatted sound names".
- Read from the decompile, not checked live (the harness runs DOSBox-X without effects sound). The item events (pick up, put down,
  fire) now use the same walk too: see "Item events on the event walk" above.
- The Caynan fight on the prison route has 274 sounds, was 133. The route needed no retuning. Swift fixtures, the full-run transcript
  and the pinned save digests were regenerated. Gates: saves 29/29, control 29/29, seeds 24/27 streams (losses 9, 16, 19).

## Fix 2026-11-18: empty log books

- Playtest: Caynan's log (CAYLOG, Ready, Space) opened an empty log book, in English and German. A monitor list shows its record's unkeyed
  `[]` entries before any earned keys (the list's first update, `FUN_1268_10c5`; re/NOTES.md "Unkeyed list entries"). Both ports now do,
  so Caynan's, Dane's and Escher's logs, the airlock notes, the CHAOS prisoner information and cryo chamber monitors and the reactor list
  show their text; CMAINT shows its 64 `[]` entries before earned keys. The journal, GMAINT and the PIMM lists are unchanged. The prison
  route reads Dane's code from the shown list now.

## Language selection 2026-11-18

- Game > Language (English, Deutsch, Français), in both ports: `Settings.language` from INSTALL.OPT `language=`, then UserDefaults.
  Voices (`SOUND/<L>SAMPLES.FLX`), captions and spoken subtitles (FUN_1120_03d2, now also on SUBTITLE text as in the original),
  monitors (`MONITORS/<G|F>TEXT.FLX`), the options dialog, GETOPTDATA "LANGUAGE" (so INTRO.SCP plays INTROG / INTROF).
  Switches live in the app; recordings carry the language. English unchanged except that subtitles now cut at the next `/` as the
  original does (the intro's "...requisition B-9/3Q..." shows "...B-9"). Gates: saves 29/29, control 29/29, seeds 24/27 streams.

## Portable engine 2026-11-18 (Windows and Linux, phase 1)

- `BioForgeCore` and its tests build on Linux; the app target is macOS only. Apple-only parts are behind `#if canImport`
  (Core ML upscaling, the memory guard, the art packs' DEFLATE; packs are macOS-only for now) and SHA-256 is hand-written (`Sha256`).
- Linux, Swift 6.4.2 in Apple's `container`, with the game data: arm64 and x86_64 (Rosetta) give the same result. 658 tests,
  17 skipped (art packs, opt-in suites), everything passes, including FullRunTests (new game to the end), the replay and fixture
  suites, except one check: `WorldTests.soundTableAndAssets` posed-vertex bits for 18 figure types. Cause: glibc's `cos`/`sin`
  differ from Apple's by one last bit for 25 of the 256 joint angles (`Mat3.rotated`, `Skeleton.swift`). Open decision in ROADMAP.
- Windows 10 x86_64, Swift 6.4.2 with the Visual Studio 2022 Build Tools, with the game data (`native/WINDOWS_CHECK.md`): 678 tests,
  17 skipped, everything passes, including FullRunTests, the replay and fixture suites, except the same check as on Linux:
  `WorldTests.soundTableAndAssets` posed-vertex bits, here for 17 figure types (ACID, ACIDD, ACIDD2, ACIDIE, CAYNAN, DANE, ESCHEAD,
  ESCHER, GRDOP, GUARD1, HARD, LEX, LEXMIR, MARINE, MASTABA, MECHO, SHRIMP): the Microsoft C runtime's `cos`/`sin` differ from
  Apple's in the last bit too. Two Windows fixes: `SessionRecorder.close()` (Windows cannot move a folder with an open file, so
  the previous recording was lost), and GameDataTests copies the files when symbolic links are not allowed (Developer Mode off).

## Ready for the first playthrough (2026-11-15)

- Tester support, from what other ports do before a beta (OpenRCT2 replays, ScummVM release testing, OpenXcom's differences list):
  each session's inputs are recorded (`SessionRecorder`) and Help > Report a Bug includes them, so `REPLAY=<report> swift test --filter
  ReplayTests` replays the bug exactly; builds, the log and reports carry the commit; after a crash the next launch offers a report with
  macOS's crash report and the crashed game's recording; autosaves on each level change (File > Open Autosave…); Debug > God Mode,
  Refill Health and Open Save File…, each logged and recorded; `save_resume_check.py --export DIR` writes the route's save points.
- `KNOWN_DIFFERENCES.md` lists what a player can notice, with how it is known; `PLAYTEST.md` is the session plan and triage scheme.
- The medkit rule (a carried ZEDICAID takes MEDICAID's uses) is confirmed live in the original.

## Fixes 2026-11-16: the remaining known gaps

- Every gap in `KNOWN_DIFFERENCES.md` is closed, from the original's code (re/NOTES.md entries of the same date):
  - LOADLEVEL destroys missiles in flight. An elevator carries every figure and floor item in its volume, and the player, each at its offset from the volume, with GO's nudge for figures.
  - EXPLODE throws shrapnel from the dying figure's mesh, drawing from the shared random stream.
  - Monitors take Tab, the arrows, L, Return and Space, and right-click acts as Escape; the pointer glides as in the original.
  - A large palette change shows one black frame, as does a level change.
  - Lasers rebound off surfaces whose PHYS has flag 4. A level's figures get their FIGR records on a first visit after a load.
- The shrapnel draws move the random stream, so the scripted run's later seeded fights differ: gates are now saves 24/29, control 23/29, seeds 16/26 (were 28, 28, 19). The failures are lost fights; none is known to come from lost state.

## Fix 2026-11-17: the robot and the arm in the scripted run

- Harness only. On some streams Lex drops Caynan's arm inside the bars' avoidance points (AVDBAR1, GETMEAT), so USE_BOT cannot drive closer than about 925 units;
  the claw reaches 0x900, so the run now grabs from there. Seeds 23/26 (saves and control still 29/29).

## Fixes 2026-11-17: the tower gauntlet and GRDHANG in the scripted run

- Harness only. The tower gauntlet failed after a load because a blow knocked Lex east and the tight walk back to bot 3's spot made him circle west into
  zone 5; he now stops anywhere in bot 3's box, and bot 4's fight is skipped when the shot at bot 3 already destroyed it. GRDHANG won on four seeds because
  Lex arrived standing in MAINTMON's box, so Space used the monitor instead of the medkit; he steps out of it first.
- Gates: saves 29/29, control 29/29, seeds 22/26 (were 28, 28, 18). Open: ROADMAP "Bugs to fix later".

## Fixes 2026-11-16: a sturdier scripted run

- The harness's key play, not the game: Lex puts an empty ZEDICAID down before fights so MEDICAID works (the original's medkit rule); he heals before the ride to the BEACH;
  he lets the Captain come to him instead of stepping in (48 of 48 streams from the default run); `scenarios.fight` walks round a pillar between Lex and the enemy;
  the ending's bike is approached from Lex's side and Space is retried after a quake; the bridge button is approached inside its box.
- Gates: saves 28/29, control 28/29, seeds 18/26 (were 24, 23, 16). What still fails is listed in ROADMAP "Bugs to fix later".

## Fix 2026-11-16: the credits roll

- The ending now rolls the credits over the end movie's last picture and quits five seconds after they stop, as the original does;
  R and the options' Credits button roll them over the running game. Layout, scroll speed, end position, CREDITSSTATE and the unpausing
  come from the code and were checked against 74 screen dumps of the original (re/NOTES.md "The credits roll"); the port's frames
  match them pixel for pixel.

## Fix 2026-11-15: a level keeps its figures

- A figure Lex killed stayed dead only until he left the level: both ports rebuilt every figure from the level file on a return
  (FIRSTBOT was back in CHAOS after the tanks, with -666 HP). The original writes the level's objects to its file at the level change
  and reads them back; a killed figure's object was destroyed, so it has no record. Both ports now keep each level's figures in memory
  as Lex left them (position, heading, motion, flags, HP, AI), and saves write them into that level's file. Checked live: the
  original rewrote CHAOS.IFF when Lex fell into the tanks, without his record and with the figures' current flags.
- Gates: saves 28 of 29, control 28 of 29, seeds 19 of 26 (seed 3 now loses the Captain on a moved random stream; re/NOTES.md
  "A level keeps its figures").

## Fixes 2026-11-15: the last audit findings

- A script waiting on a `MODIFYVAREVERYNTH` ramp (the CHAOS cell-block drip) waits again after a load, in both ports; before, it ran on at once.
- FORCERELOAD during a flic: cannot happen in the shipped scripts (both flic scenes FREEZE first and neither kills Lex); no change.
- Corrupt saves: a fuzz test (`SaveFuzzTests`, 2000 cases tried) found no crash in the Swift reader; 40 cases run in the suite.
- The one `swift test` crash was a data race on `GameResources`' caches between parallel tests; they are now locked, and the suite is
  clean under Thread Sanitizer. The app was not affected.
- `operating-room`: MEDICAID_USE picks the nearest item of name or type MEDICAID, so a carried ZEDICAID takes the charge and, when
  empty, blocks MEDICAID (confirmed live in the original, as is putting the empty kit down). The harness now puts an empty kit down. Saves 28 of 29 (`grdcon` loses the Captain), control 28 of 29, seeds
  20 of 26 (re/NOTES.md "The last audit findings").

## Fix 2026-11-14: saves keep shots in flight

A laser or bolt in the air vanished at a save in both ports. The original saves it: the missile class has its own save writer and reader
(`10e0:135a` / `10e0:12b7`), and its item is an ordinary ITEM record. Both ports now write the missile task and the item record and
rebuild the missile on load under its handle. Checked live: a port save with a laser aimed at Lex loads in the original and the laser hits
him (55 HP, as in the port); the same save without it leaves him untouched (re/NOTES.md "Missiles in saves").

## Fix 2026-11-14: a GO now steers (Drogg 1 running on the spot)

A walking or running GO turned toward its target only when it started. The original's GO task turns the figure toward it on every
update, by up to 10 degrees (`FUN_10e0_1a4c` -> `FUN_10a0_1f0a`). Without that a figure pushed off its line could miss the arrival
circle and run into a wall for ever, as Drogg 1 did after `GO DCENTER RUN` (stream 16, the `hall-to-elevator` save point). Both ports
steer now (`steer_go` / `steerGo`). Every scripted walk follows a slightly different path, so the full-run transcript, the oracle
fixtures and a few exact positions in tests were regenerated, and four harness spots tuned to the old paths were made sturdier
(re/NOTES.md "GO steering"). From the code; not checked live.

## Fix 2026-11-14: held keys, failed saves, music after a load

Three of the audit's open items (re/NOTES.md "Bug audit 2026-11-14", *Saves* and *Held keys*). The app ignores a key pressed with
Command (a shortcut, and macOS sends it no key-up) and lets go of every held non-modifier key when Command goes down, so a letter
released under Command (Kick on A, say) no longer stays held. The game also pauses while the Settings window or the Report a Bug sheet is open, as it does in the background, and coming back from another app no longer unpauses them. A failed save or load now shows an alert with the slot and the reason
(`World.fileError`, the port's own addition). Music silent after a load was left as it is: the original's loader clears the song the
dialog restores on closing, so it is silent there too until the next `MUSIC` (from the code, not checked live).

## Fix 2026-11-14: falling into the tanks

Falling off the catwalk above the cryo shaft left Lex standing on the TANKS walkway with CRYTOTNK's FALL waiting forever (found by
`MonkeyTests`; the whole game stopped there). Checked live in DOSBox-X with a port save loaded in the original (`re/out/tank_fall_live`):
the original does not stand him on any floor at that arrival, he falls on, and TANKDETH drowns him at (-17408, -57344) with no velocity.
Both ports now (re/NOTES.md "Falling into the tanks"): a level arrival made with Lex's collisions off places him at the arrival point
with no floor under him (the original's own placement there, z near the "no floor" value, is not fully traced), and a GO that places
at once zeroes the velocity as SetPos does. The full-run replay is unchanged.

## Bug audit 2026-11-14: soft-locks and crash risks

An audit for game-breaking bugs of the kind players hit (four code reviews: app input, script state pairing, Swift crash risks, save and
load; plus a new randomized soft-lock test, `MonkeyTests`, 1,200 trials over the 30 save points). Fixed, both ports where both have the
code (re/NOTES.md "Bug audit 2026-11-14"):
- **The reload dialog after a death could be closed without loading** (Load then Cancel, Audio or Gamma then OK, Credits then Return,
  Exit then No, Load then New then Yes), leaving a dead Lex with no dialog and no key that works. As in the original's callback
  (1280_callbacks.c), with MUST_RELOAD those now lead to the exit prompt and Escape on it to the main panel; Load > New > Yes starts a
  new game (`World.newGameRequested`); a failed load reopens the dialog. With O, Cancel on the slots now goes back to the main panel.
- **Escape could not close the PIMM or the options dialog in the zero-G room**: the app gave keys to a captured keyboard before an open
  monitor. The original's dispatcher (FUN_10e8_11e3) gives them to the monitor first; the app, the controller and `play.py` now do too.
- **Lex walked on by himself** when a key was released during a flic (the key-up was dropped); every key-up now reaches the world.
- **A controller's Run, Kick or Punch stayed on** when released inside a menu or monitor; a mouse button held on a dialog button while
  the window lost focus left the screen's keys ignored. Both released now.
- **Possible crash:** four script waits held the figure `unowned`; a figure removed while another process waited on it would trap.
  Now `weak` (the wait ends). Also clamped: a negative music volume from INSTALL.OPT, a sprite frame below its count, a zero hull span.
- Saves are written atomically, so a failed write keeps the slot's old save.
Open, in ROADMAP "Bugs to fix later": smaller items. Falling into the tanks, found by the new test, is fixed (above).
Not played by hand in the app.

## Fix 2026-11-12: stuck after a second I

While PIMM_INVENTORY raised the wrist (its AI OFF already run, no monitor yet), a second I started a second PIMM_INVENTORY. Its AI OFF
outlived the page, so after Escape Lex could not move until the inventory was opened again. `FUN_10a8_0541` answers only S (CANNOT_SAVE)
while +0x229 or the z velocity is set; both ports now do that for every key, not just the motion keys (re/NOTES.md, "Keys while Lex is
held"). So I/P/D/J, O, R, Enter and Space are also ignored during the wake-up and other AI OFF stretches. From the code; not checked live.
The harness's repair routine pressed D mid-recoil; it now waits until Lex is free, and `run_seeds` went from 21 to 22 of 26 (stream 5
now finishes; the airlock miss was a timing accident).

## Fix 2026-11-12: Lex flickering while he gets out of bed

Two drawing fixes, both ports; the simulation is unchanged and the oracle fixtures were regenerated (re/NOTES.md, "Rendered pose
interpolation" and "An end-of-update idle is drawn one update later"):
- The limbs were blended between motion frames but the root x/y was not, so a travelling body slid back within each frame and jumped
  forward at the next (OUT_OF_BED frame 36: back 266, forward 384). The blended root x/y is now drawn too. From the code.
- One standing pose in bed between WAKE_UP and OUT_OF_BED: the idle at the end of an update was drawn at once. Live (DOSBox-X), the
  original requests the same idle but never draws it before the script's OUT_OF_BED; the ports now draw the update's pose until the
  figure's next update.

## Fix 2026-11-11: the screen after Lex dies

After a death the port showed the reload dialog on black. The original (a VGA dump from DOSBox-X with `re/out/tower_live/GAME1.IM1`, where
the tower bots kill Lex) shows it over the title picture: KILLLEX runs `CAMERA SHOW STITLE` just before FORCERELOAD, and OPTS.CAM's
background is fully transparent. Both ports now keep the SHOW picture (until the next camera switch or level load) and draw the dialog over
it with the recovered rules: the picture dimmed onto 128..145, the buttons translucent (FUN_1270_185b), and the button frames following
their states (EXIT lit, SAVE and RETURN dimmed; RETURN no longer closes the reload dialog). 99.3% of the pixels outside the pointer match
the dump; NOTES "The screen after a death". The new-game difficulty dialog sits on the dimmed TITLE the same way (INFERRED, not captured).
The in-game dialog (O, or Escape in the app) sits on the dimmed room the same way, checked live with O in CE31. Fixed with it: Escape could
not reopen the dialog after it was closed (the key that opened it stayed "held").

## Fix 2026-11-11: Escape skips the intro in the app

Escape is reserved in the app's key bindings, so while a script held the keyboard (the intro's `CAPTUREKEYBOARD GETESCKEY`) the
press never reached the hook. It now goes through as scan 0x01 (`KeyBindings.capturedScan`); `WorldTests.escapeSkipsTheIntroMovie`
runs the real opening (first LOADLEVEL at tick 107 with Escape, 6,461 without).

Also in the app: Escape during play opens the options dialog (the game's pause; the port's addition, the original ignores Escape
there). The monitor and options pointer now follows the real mouse position every frame, so it no longer stays offset after the
mouse enters the window or the window is activated. Shift, Control and Option held for Run, kicks and punches are dropped once
macOS reports them up, so a release the window never saw (a Cmd+Shift+4 screenshot) no longer leaves Lex running. INFERRED cause
of the reported run after waking: the engine walks with no modifier (checked), and no custom key bindings were saved.

The hand pointer itself was drawn about 110 px right of the mouse: the ports put the CAM frame's hotspot at the pointer, but the
original uses VARS.DEF `_PTR_X_HOT` / `_PTR_Y_HOT` (122, 13) in the frame's 320x200 canvas, and clamps to the `_ptr_*_margin`s
(top 14). Both ports now do that; the app hides the Mac pointer over the picture while the hand is shown.

The pointer now animates its press as the original does (`re/NOTES.md` "Pointer press animation"): a click shows hand frames 1..3 and
back, the button is pressed when frame 3 is reached (tick 5 after the mouse goes down) and released one tick later when the mouse went up
meanwhile; the pointer ignores moves and a second press while it animates, and holds frame 3 while the mouse stays down. The options
dialog goes through the same machine (a click activates its control on the release), so the app's options path calls
`optionMouseDown` / `optionMouseUp`. The playthrough harnesses' `click` / `hold_button` first settle the pointer on its last frame
(`Monitor.settle_pointer`, a test driver; `full_run.json` now records it as an op), so their clicks act at once as before and every
playthrough, `run_seeds` (21 of 26) and `save_resume_check` (26 of 29, `--control` 27 of 29) are unchanged. Python and Swift keep their
own 60 Hz count for the pointer (no never-paused clock exists in either).

The function the pointer calls when a press starts and on the release (`FUN_1250_0415`) is MON_ENABLEINPUT's switch (the statement's
handler `10d0:584e` calls it; `re/out/statement_handlers.txt`). It stores the monitor's input flag (+0x120): while it is off the monitor's
event handler (`FUN_1250_0cf9`) drops mouse moves, mouse downs and keys, and only the mouse up gets through (`FUN_1250_0c4c`). Turning it on
with a mouse present moves the DOS mouse onto the pointer (INT 33h AX=4, read from the machine code at `11d8:0e91`). So from a press to the
release the hand can't move, even once its animation has ended with the mouse still held, and keys are ignored; after the release the
mouse is where the hand is. Both ports now do this (`set_input` / `setInput`); the app moves the Mac mouse onto the hand on the release.
The options dialog is the current monitor too (`FUN_1258` / `FUN_1280` store it in the same `[9d76]`), so it behaves the same way.
Swift now also handles `MON_SETPTR`, `MON_SETPTRFRAME`, `MON_SETPTRPOS` and `MON_ENABLEINPUT`: the per-form hands (`PCAYHAND.CAM` at the
palm reader, CHAOSMON.scr) are drawn from their own CAM, also at 2x/4x (`monitors/<CAM>/...` in the pack). PCAYHAND and PLEXHAND have one
frame, so they press without animating. Still not modelled: pointer glides (`MON_SIMULATE`, `DAT_9fea`), `MON_SET_TAB_STOPS` in Swift, and
moving the mouse in `play.py` (the Python monitor records `mouse_warp`).

## How work has been organized (optional, it worked well)

The main session does the reverse engineering and decisions (Ghidra, reading the
decompiled handlers). Read-only "scoper" agents catalog script usage and data. "Implementer"
agents build against a precise brief with acceptance commands, and report assumptions
honestly. Always rerun the tests and look at the rendered output yourself before calling
something done.

## Ground rules

- Never modify `game/` (the extracted original files) or redistribute them. Generated output
  goes in `re/out/`.
- Ghidra project: `re/ghidra/BioForge.gpr`. Headless runs need
  `JAVA_HOME=/opt/homebrew/opt/openjdk@21/libexec/openjdk.jdk/Contents/Home`. Helper scripts
  are in `re/scripts/`; usage is in NOTES "Ghidra".
- Python always via `re/.venv/bin/python -I` (numpy + Pillow).
- Keep `re/NOTES.md` current with every finding (cite the engine function), and update this
  file when the status changes.

## History (before 2026-11-11)

Kept for reference. Written between 2026-10-15 and 2026-11-02; the to-do lists and percentages in it are mostly done or out of date.
The dated entries above and ROADMAP.md are current.

## Current handoff: manual original-game escape confirmed (2026-10-22)

The user took over the original DOSBox-X game after automated nurse steering proved too
slow and expensive. They escaped the cell. The controller then paused and sampled the
original at clock **48890**:

- Camera **BLK1**; Lex position **(-10861, -20669, -5133)**; health **100**.
- Script globals **`_BOT_BLOWN=1`**, **`_BARS3_ON=0`**; **FIRSTBOT absent** from the figure list.
- Figure snapshot: `re/out/natural_push_live/manual_escape.json` (ignored local output).
  The globals were read separately at the same paused clock; their values are preserved here.

This confirms the original game's nurse defeat and corridor escape in this encounter.
The encounter began with explicitly staged front/rear attack poses, followed by automated
key-only steering attempts and finally manual play. It is **not** an unstaged full-game
replay or a recorded manual input timeline; exact original-versus-port trajectory parity
remains open. Do not spend more time automating this escape merely to repeat the result.

**Session handling:** the paused original session has since ended (no DOSBox-X process
was running on 2026-10-22). Its scratch workdir `re/out/natural_push_live` remains. Keep
`game/` read-only. The user is willing to play while agents inspect values; launch a new
session only when needed, then pause/sample at useful milestones.

```bash
# Inspect (pauses the original); paths are relative to the repository root.
re/.venv/bin/python -I re/tools/dosbox_control.py send re/out/natural_push_live/control '{"command":"sample"}'
re/.venv/bin/python -I re/tools/dosbox_control.py send re/out/natural_push_live/control '{"command":"variables","names":["_BARS3_ON","_BOT_BLOWN"]}'
# Resume for the user when requested.
re/.venv/bin/python -I re/tools/dosbox_control.py send re/out/natural_push_live/control '{"command":"run"}'
```

Controls already explained: C toggles combat; Option + direction gives hand attacks,
Control + direction gives kicks; Option+Up is the tested overhead punch. Shift+Up runs
and takes priority over attacking. Space uses/interacts. The user requested remappable
MacBook controls, but **no native remapping UI has been implemented**. A DOSBox mapper
file `re/out/natural_push_live/macbook.map` was prepared for number-row-to-numpad mapping
but **was not loaded**; do not tell the user those number bindings work.

There are uncommitted experimental steering changes in `re/tools/dosbox_control.py` and
`re/tools/test_dosbox_control.py` (69 tool tests passed, final driver not proven end to end
live). Preserve and assess them separately from this manual result. Existing port
regression commit `85f4f7` already verifies the post-wound key route in Python and Swift;
manual success adds original-game outcome evidence, not exact trajectory equivalence.

## Update 2026-10-23: Caynan and Guard 1 (Python scenarios; engine pieces in both ports)

- Scenarios `chaos_caynan_fight` (continues the nurse run: hall, bars-flicker window, INSIDE3, fight; Easy: Lex wins at 17 HP,
  `CAYNAN_DEATH` runs; Medium: Lex dies) and `chaos_guard1_fight` (staged `TANKTOCELL2` entry; Easy: Lex wins, `GUARD1_DEATH` ->
  `DOTHELEXTHING` finish; Medium: Lex dies). Difficulty is a logged staged setting. Details: NOTES "CHAOS encounters: Caynan and Guard 1".
- Recovered and ported: `DISTFROMWAYPOINT`, `2DDISTFROMWAYPOINT`, `ANGLEFROMWAYPOINT`, `AMINWAYPOINT`, `AMBIENT`, `STOPAMBIENT`, `APPLY`
  (state only: the decal FLICs are not in the data), SETCURRENTFIGURE's type-name fallback, and the real distance unit
  (`cm = (units*100+0x80)/0x800`, which also fixes DISTFROMENEMY / ATTACKRADIUS). The Swift port mirrors all of it (`World*.swift`,
  `ChaosEncounterTests.swift`); the native fixtures were regenerated (only `stage3b.runs` changed, `assets.radius` was dropped) and the
  new-game save digests in `SaveLoadTests.swift` were updated (AMBIENT handles shift `VARS.DEF` globals). The two fight scenarios are
  not native fixtures.
- New `World.unmodelled` lists every engine call that is dropped (kept apart from `warnings`). Open: SOUND should be one-shot; live parity of
  the fights; FLOATATHEIGHT's one-argument form (bot levels, recorded in `unmodelled`).
- The last behaviour-changing gaps are ported in both ports: `COMPASS`, `HEADING`, `ISMYFORM`, `ISINCOMBATMODE`, `ISKEYPRESSED`, `AMINEXTENT` and
  `FLOATATHEIGHT ... MAXIMUM` (z cap in the mover). `AMINEXTENT` now makes CELL3_MON animate Lex's cell indicators while he is in CE3, which
  shifts the opening's sound handles and subtitle timings: `stage3b.runs` in the native fixtures and the four `SaveLoadTests` digests were
  regenerated (the unchanged HEAD code reproduces the old digests with the same generator). The Caynan fight outcome is unchanged; Guard 1
  (Easy) still wins with 68 HP but with 6 recorded punches instead of 5 (ends at tick 2648, was 2680). Details: NOTES "CHAOS encounters".

## Engine gap survey (2026-10-30): the to-do list past CHAOS

Two passes over the shipped content, Python prototype (the Swift `modelledStmts` / `modelledFuncs` sets are identical; Swift
additionally handles the FLIC/FADE/JUMPON/GETOPTDATA presentation calls in the app):
- **Static:** every decoded script (`re/out/scripts`, 108 files) parsed; each engine statement/function not in `MODELLED_STMTS` /
  `MODELLED_FUNCS` (and not `MON_*`) counted per script and mapped to levels through `SCRIPT/<LEVEL>.LVL`. **58 names are unmodelled.**
  COMMON, DEMO, FIGURES, ITEMS, MISSILES and PIMM load in every level; the rest are level scripts.
- **Dynamic:** arriving in each of the 9 game levels through a real `LOADLEVEL` arrival (CONTROL and TOWER have no scripted arrival, so
  they loaded without one) and idling 1800 ticks: no crash, `_LOAD` scripts run, and the only unmodelled call reached is `ISAION`
  (LANDPAD, PLATFORM). New warnings: BEACH `FLUFFY_SFX3` `BREAK 2` (the known BREAK-n assumption) and a `PLATFORM_LOAD` runaway loop
  forced to yield at tick 0 (the loop spun on `IF ISAION = _FALSE` while ISAION returned 0; gone since item 1). Almost every gap is
  behind a trigger, a fight or an item, so idling cannot reach it. Static counts are the better guide.
- **After item 1 (2026-10-30): 46 names unmodelled; after item 2: 45; after MAKEMISSILE: 44; after item 3 (2026-10-31): 41; after the moving floors: 39; after the parallel mechanics, audio and presentation ports (2026-10-31, PRs #12–#14): **0**. Every engine name the shipped scripts use is now modelled (some only partly: see items 4–7)**; the dynamic pass reaches none and raises no warnings in 60 s per level.

An unmodelled **function returns 0**, so the script still takes a branch, just possibly the wrong one; that makes the cheap functions
more urgent than their counts suggest. Order of work (uses = call sites in the scripts):

1. **Done (2026-10-30, both ports): silent-zero query functions.** `DISTFROMEXTENT`, `DISTFROMTRIGGER` (box centres), `DISTFROMITEM`,
   `2DDISTFROMITEM`, `2DDISTFROMCOORDS`, `ISAION`, `ISGRAVITYON`, `ISKEYBOARDCAPTURED`, `FINDFIRSTFIGURE` / `FINDNEXTFIGURE`, and
   `GETROOMAMBIENT` / `GETCAMERAAMBIENT` (−1: the ambient loops are not ported, item 5). Also fixed: `COORDX/Y/Z` return the position
   `>> 8` and resolve CURFIG / CURITEM / figure / item like the original (they used to return raw units and treat CURFIG as a name, so
   every shipped use got 0). No fixture or scenario changed. Details: NOTES "Script query functions".
2. **Done (2026-10-30, both ports): `FIRE` and the missile core.** `FIRE` (59 uses) is scripted transport, not a weapon: it
   launches a missile (`ITEMS/<TYPE>.IFF`; ZIPPY is invisible) along a straight line, and `CARRY` hangs a figure or item on it by the
   carried object's `ON_<TYPE>` property. Scripts wait with `SUSPENDWHILE` on its handle. Hits run `<TYPE>_HIT[_<figure>]`, and the end
   of range or a wall runs `<TYPE>_HIT_WALL`. The BEACH zip line ZIP1_A → ZIP1_B rides end to end in both ports. `re/interp/missiles.py`,
   `WorldMissiles.swift`; details and assumptions: NOTES "Missiles and FIRE". Not yet: wall bounces/reflection, missiles in saves.
3. **Projectiles and effects.** Done (2026-10-30, both ports): `MAKEMISSILE` (30 uses: a named limb such as GUN, or the held
   weapon; pushed out of the shooter's box), and the shoot key: ATK_SHOOT's event 0xf0 runs `<rthand weapon>_FIRE` (IS_WEAPON) or
   `<figure>_FIRE`, so the CHAOS blaster fires LASER bolts. Generic `LASER_HIT` damages a live target (`CURFIG.~0 > 0`: corrected
   2026-10-31 after the CURFIG/CURITEM selector fix; it was first read as never damaging). Done (2026-10-31, both ports): `MAKEFLATOBJECT` (87 uses: BOOM explosions, sparks, TANKS
   bubbles, drawn as depth-sorted room sprites), `EXPLODE` (the 150-tick wait and hiding the figure), `THROWCURITEM` (free items
   now carry velocity, gravity and bounce; the TEMPLE grenade flies and bounces). `re/interp/effects.py`, `WorldEffects.swift`;
   NOTES "Flat objects, EXPLODE and THROWCURITEM". Still open: EXPLODE's shrapnel (visual only).
4. **Level-specific mechanics.** Done (2026-10-31, both ports): `SETFLOOROFPHYS` / `TELEPORTALLONPHYS` (30 each, CONMACH's garage
   elevator in CONTROL): the ride runs end to end with the player carried at a constant height above the moving floor.
   `re/interp/floors.py`, `WorldFloors.swift`; NOTES "Moving floors". Also fixed: grounding's floor queries now rank
   only the figure's area members (the engine's hidden area argument), so the garage is playable with gravity on and standing
   on ELV starts the ride; NOTES "Area-scoped floor queries". Open: moved boxes are not persisted. Done (2026-10-31, both ports):
   `CHANGEMYFORM` (the CREATEFIGURE loader swaps mesh, skeleton, motions, form name and per-form properties; the HARD suit in BEACH and
   DIGSITE), `GRABCRITTER` / `RELEASEFROMLIMB` (the BEACH acid beast carries Lex on its finger through the real HIT_LEX), `PLACEITEM` on
   any limb, `FREEHAND`, `ANIMATE` (texture animation state; the renderers do not read it yet), `SETREFERENT` (processes die with their
   referent item), `INCVIRTUALSECONDS`, `FORCERELOAD` (HP −1 and the must-reload dialog), numeric `GO x y z` and FLOATATHEIGHT's
   one-argument form (per-figure F). `re/interp/mechanics.py`, `WorldMechanics.swift`; NOTES "Level mechanics". `CAMERA SHOW` is
   presentation and `CAMERA AT` is unused. Still open: the renderers' texture frames from the ANIMATE state, figure referents, GO's speed
   number, the mover's attached branch and the player's auto-aim.
5. **Audio and presentation.** Audio done (2026-10-31, both ports): `SETVOLUME` 35, `SETPITCH` 2 / `ADDTOPITCH` 8 (the voice's
   absolute rate in Hz; a rate change re-times the handle), `REPLACESOUND` 30 / `REVERTSOUND` 28 (sound-symbol overrides honoured by
   every name lookup), `BANKINSFX` 45 and `SETSOUNDCACHE` / `REVERTSOUNDCACHE` 2 (cache only: no-ops), `MODIFYVOLUMEOVERTIME` 20 /
   `MODIFYPITCHOVERTIME` 15 (a ramp task whose handle lives D ticks), and the room ambient loops `_<ROOM>_AMBIENT` started after camera
   switches (`FUN_1130_0e6b`) with the `_<CAM>_VOLUME` binding; `GETROOMAMBIENT` returns the loop handle (`GETCAMERAAMBIENT` stays −1:
   no per-camera names exist). Not game-logic-free after all: the QUAKE decay ramps make the opening 30 ticks longer, so the
   port-absolute scenario starts moved 1140 → 1170, the Guard 1 fight is reseeded at its staging point (Easy still won), and
   fixtures/digests were regenerated. `re/interp/audio.py`, `WorldAudio.swift`;
   NOTES "Audio: voice statements, ramps and ambient loops". Open: REPLACESOUND overrides in saves, LOADLEVEL and the loops, the
   camera/room LOAD/UNLOAD order.
   Presentation done (2026-10-31, both ports): `CHANGEPALETTE` 43 (additive offsets on top of gamma, timed), `FADE` 29 (the 30 Hz Fade
   process: `SUSPENDWHILE FADE` now really waits), `RUMBLE` 11 (screen shake), `CAPTION` 6, `SET_PTR_PRESS_TIME` 5 / `SET_PTR_MOVEMENT` 4
   (stored only), and the flic statements `RUNFLIC` 17 / `STARTFLIC` 5 / `SETFLICRATE` 5 / `STOPFLIC` 3 / `FLICLOOP` / `PLAYFLIC` plus `JUMPON` 15
   (a one-shot watch on a global, not a key hook) and the CAPTUREKEYBOARD handler block. The flics moved from the app's ShowPlayer into the
   core of both ports; FREEZE now stops the game clock. `re/interp/presentation.py` / `show.py`, `WorldPresentation.swift` /
   `WorldShow.swift`; NOTES "Presentation, flics and front end". Open: the monitor pointer's glide, the palette-change
   black frame on camera cuts (`10e8:1dcc`). The new game now plays the intro movie with its real FADE waits, so the first CHAOS load moved
   from tick 26 to about 6460: the opening scenarios and test boots are re-timed relative to that load (the anchor), and the fixtures were
   regenerated (a cell boot of 1100 ticks from the anchor plus a small intro fixture).
6. **Front end.** Done (2026-10-31, both ports): `MENU` 14 / `UNMENU` 23 (stubs in the release exe), `EXIT` 3, `FREEZE` / `THAW` 4 (suspend
   the other script tasks and stop the world update), `ADDKEY` 4 (a synthetic key event), `WASALTPRESSED` 1, `GETOPTDATA` 2 (INSTALL.OPT).
   Open: `CREDITSSTATE` 1 stays 0 because the ports have no credits roll, so ENDGAME ends only on Esc / Alt+X.
7. **`DEBUG` 133.** Done (2026-10-31, both ports): confirmed a no-op in the release build (its trace reader `10c0:24dc` is empty);
   `DEBUG` and `DEBUGINFO` are modelled and silent.

## Playthrough harnesses (2026-10-31): how far the game plays

Three harnesses drive the main path in the Python port with the real scripts and, where practical, real keys. Each logs its
staged shortcuts and problems; every passing segment is a regression test.

| Stretch | Harness, notes | How far it plays |
|---|---|---|
| Prison: CHAOS, TANKS | `re/interp/playthrough_prison.py`, `re/playthrough/prison.md` | New game through the nurse and Caynan fights, fork, circuit board, cell-block door, cell-4 bars, Dane's code, Caynan's arm, USE_BOT carrying the arm to the reader, the security terminal (earned), the hallway with the sentry live (getting past it staged), the cryo iris and the ladder into TANKS, the whole TANKS catwalk and the mantle up into cell 2, where the unarmed run ends. Cell 2 (Guard 1, the blaster) and the hall elevator are mapped, not reached. |
| Surface: LANDPAD, BEACH, DIGSITE, TUNROOM | `re/interp/playthrough_surface.py`, `re/playthrough/surface.md` | LANDPAD from the CHAOS elevator to BEACH; BEACH through the zip lines, warhead, blast door and suit machine to DIGSITE; DIGSITE and TUNROOM as probes up to `TO_FINAL` into PLATFORM. The bot fights are skipped and AIRMECHO's hits are staged. |
| Base and ending: CONTROL, TOWER, PLATFORM | `re/interp/playthrough_base.py`, `re/playthrough/base.md` | Every segment reaches its goal and the game reaches `EXIT` through the real ENDGAME (operating-room scene, the tower gun and both landers, the city scene and the alien battery, the bike, the end flic). |

Engine fixes found along the way are in `main` (PRs #16–#18): the swapped CURFIG/CURITEM object-local selectors in the script
decoder (`10c0:24e1`; generic LASER_HIT does damage live targets), LOADLEVEL callers and three-word destinations, FIGR-record AI
names, `CALL ( NAME( a, b ) )` arguments, non-blocking refused MOTIONs, IF/ELSE binding, `GO <trigger>` to the box centre, the
suited shoot request, key gating of script and monitor motions, and held-item use blocks by instance name.

**Blockers across the harnesses, ranked** (each harness doc has the diagnosis and addresses):
1. **AI and room events.** Fixed in both ports (NOTES "Room events and the default AI"): room events in the engine's order, the AI-off counter from
   the FIGR records (AI OFF pauses, the show / hide pass), every level figure from the load. HALMECHO now acts, and Lex passes it by play
   (sidesteps on the first pass, a run on the second; NOTES "The hall sentry and the tower bots").
2. **Lex's movement.** Mantles and ladders do not move Lex (a motion's root rise is not committed at its end with gravity on);
   Lex falls through PLATFORM after `TO_FINAL`; the tank monster's throw lands him where the port has no floor; he cannot enter
   the jetson tube; a `MOTION … FREEZE` pose locks him (after the dig tube, after OPRSCENE's knockout); the `GO PRY_HERE` walk never
   arrives (no arrival tolerance); the Elite cannot step out of PLAT03 after a gravity-off GO; turning in place drifts him.
3. **Items and combat: fixed (2026-11-01, both ports; NOTES "Items and combat").** The item list allows duplicate names and SETCURRENTITEM takes the nearest match, so the
   ending works in real play order; items have a hull from EXTENT, so the security clearance is earned with USE_BOT; `MOTION … CONTINUE` is closed; the motion gates and AI ON follow the engine.
   The bots' rate and damage are faithful, but `TURN` was not (n degrees, positive = left): AIRMECHO's bolts now hit, and Lex wins the duel by keys: he sidesteps each bolt and shoots between volleys (NOTES "AIRMECHO by keys"). Open: the engine has no corpse lock, so a
   stray process can stand a dead figure up (not seen live).
4. Smaller: no credits roll (does not block the end), the warhead escape a few hundred units short, the arrival offset in a
   three-word LOADLEVEL volume.

## Goal

A native macOS port of BioForge (Origin, 1995, MS-DOS) that runs the original game data.
Approach: reverse-engineer the formats and engine behaviour, prove each piece with a Python
prototype (`re/`), then build a real-time native engine from that knowledge.

## Where we are (rough)

| Area | State | ≈ |
|---|---|---|
| File formats | Rooms, sprites and depth, meshes, animated textures, skeletons, motions, levels, cameras, placed objects, scripts, FLC video (Python and Swift), sound samples, XMIDI music (→ MIDI, song and transition tables, AdLib timbre bank), fonts, monitor CAM elements and the `MOUSE.SHP` cursor decoded. | 90% |
| Engine behaviour | Script VM, scheduler, rendering and occlusion, camera selection, motion playback, level loading, new-game boot, opening nurse encounter, subtitles, monitor/PIMM screens, face lighting, and the options dialog work. Melee hits follow the recovered engine (NOTES "Melee hits"); player collision and the monitor viewport's sampling and colour conversion are approximations. Missing: full physics and complete monitor interaction. | 50% |
| Player control | Opt-in preview with the recovered PC key mapping, held-item Space use, inventory READY/stow, combat motions, PIMM screens, and hull / area-based `PHYS` collision. | 40% |
| Audio | Samples, 8-voice allocation, the music state machine (bar-synced transitions), GM rendering through Apple's built-in synth, and the AdLib arrangement through a port of the game's AIL AdLib driver and an OPL2 model work; `movie.py --audio` writes effects + music (`--music-device adlib\|gm`). The native app plays effects and music live and switches GM/AdLib (Game > Music Device). The SDL app plays GM through TinySoundFont with the player's SoundFont, sample-accurate on its own timeline. Missing: sample-accurate live GM timing. | 95% |
| Native macOS app | Swift package `native/`: stages 1–4 done; stage 5 includes subtitles, PIMM pages, monitor camera viewports, and script-driven SHOW playback (the app runs the opening movie). | 50% |

Overall (2026-10-31): every engine name the scripts use is modelled, and the playthrough harnesses drive the main path from a
new game into TANKS, across the surface levels and through the base to the end, with staged shortcuts over the blockers above.
Played without shortcuts, the game stops at those blockers, so it is not yet playable end to end; the remaining work is the ranked
blocker list, then the native app's play loop. The per-area percentages above predate the harnesses.
Since 2026-11-02 `LINKMETOCAMERAS` pauses and resumes camera-linked processes in both ports, checked live against the original
(re/NOTES.md "Camera-linked processes"), and `playthrough_full.py` no longer takes a shortcut for it.

## What works today (commands from the repo root)

```bash
re/.venv/bin/python -I -W ignore -m unittest discover -s re/interp -p 'test_*.py'   # interpreter regression suite
re/.venv/bin/python -I -W ignore -m unittest discover -s re/formats -p 'test_*.py'  # 72 format tests
re/.venv/bin/python -I -W ignore re/interp/scenarios.py --out re/out/scenarios        # JSON checkpoints and PNGs
re/.venv/bin/python -I re/interp/movie.py --boot re/out/newgame.gif --ticks 1100 --audio re/out/newgame.wav   # new game + sound
re/.venv/bin/python -I re/formats/music.py game/app/Bioforge/MUSIC/MUSIC.FLX re/out/music   # songs → .mid
re/.venv/bin/python -I re/formats/music.py --play 10 --seconds 60 re/out/music/chaos_60s.wav   # one song (GM synth)
re/.venv/bin/python -I re/formats/music.py --switch "0:10,19:21" --seconds 60 re/out/music/trans.wav   # transition
re/.venv/bin/python -I re/formats/music.py --adlib --play 10 --seconds 60 re/out/music/chaos_adlib.wav   # AdLib arrangement (OPL2)
re/.venv/bin/python -I re/interp/movie.py --boot re/out/newgame_adlib.gif --ticks 1100 --audio re/out/newgame_adlib.wav --music-device adlib
re/.venv/bin/python -I re/formats/sound.py game/app/Bioforge/SOUND/ESAMPLES.FLX re/out/wav  # samples → .wav
re/.venv/bin/python -I re/interp/play.py                                               # SDL2 live control preview
re/.venv/bin/python -I re/interp/movie.py LANDPAD MEETMECH re/out/airlock.gif --ticks 260
re/.venv/bin/python -I re/formats/script.py game/app/Bioforge/SCRIPT re/out/scripts   # re-decode all scripts
re/.venv/bin/python -I re/interp/parse.py re/out/scripts                              # parse check (0 failures)
re/.venv/bin/python -I re/formats/check_cams.py game/app/Bioforge/ROOMS/*.CAM          # 8446 frames ok
```

- New game: GAME → INTRO → TITLE → CHAOS. Lex lies in bed (`SNAPTOPOSE`), the quake hits,
  the nurse robot activates, and Lex plays WAKE_UP → OUT_OF_BED → STAND (ticks ~716–1155 since the QUAKE
  decay ramps were ported; in the original WAKE_UP starts at ~74 s and Lex stands at ~80 s, the port maps to
  75.8 s and 81.7 s, 1 s later than before the ramps: unverified against a live clock).
- Airlock cutscene (LANDPAD): the door animates, Lex walks, the camera is locked on HFR3, and
  the mech appears when the door opens.
- Cross-level regression: deterministic World+VM runs cover CHAOS escape and nurse revival,
  LANDPAD MEETMECH, and BEACH → TUNROOM → BEACH. All 10 GAMEDAT levels load scripts and
  render a frame without warnings. Scenario manifests record input events, state checkpoints,
  camera and level changes, hit events, warnings, and engine call counts; selected frames
  are saved for visual inspection. These are representative paths, not full-game parity.
  `re/tools/parity.py run <scenario>` now compares DOSBox-X and Python traces for
  opening wake, closed-door walk and open-door zap at the game clock, with
  per-field first divergences, drift and position plots under `re/out/parity/`.
  The closed door stops at y −14100/−14099; other fields still diverge (NOTES,
  "Parity harness").

## In progress / next up (in order)

Native-fidelity work picked up on 2026-10-15 (details in NOTES):
- **Options dialog timing: resolved.** The original pauses scripts, world updates, camera
  selection and the game clock while the dialog is open (NOTES "Resolved (2026-10-15)").
  Implemented in the prototype (`World.paused`; scripts, world, camera, clock and subtitles
  stop; the dialog stays live).
- **Save/load: native format verified; resume works.** `savegame.py` decodes and re-encodes the
  whole runtime state byte for byte (incl. FIGR/ITEM/PLAY records), our packer's saves load in the
  real game, and the prototype resumes native saves (script processes at their saved statements,
  figures, carried items). The prototype also saves from the options dialog, now with its script processes,
  subtitle / sound timers and MODIFYVAREVERYNTH ramps in SCRIPT.DAT, written as the original's kernel writes them
  (brace depth, links, local count; NOTES "Port saves load in the original"): the original loads port saves and runs
  their processes (checked live at three save points), and both ports load the original's saves. `re/tools/save_resume_check.py` saves at every leg boundary
  of the full run and plays on: all 29 reach EXIT (`temple-monitor` skipped: a monitor stays open) (NOTES "Prototype saves write the script processes",
  "The original does not save the motion phase either", "The inventory order after a load"). A load restarts running animations
  from frame 0, as the original's does; `--control` (that restart alone, no save, with positions and headings rounded as the records
  hold them) finishes all 29 too; the last two failures were harness steps with no slack for the record's 8.8 heading
  (NOTES "Two save points failed on the heading's last bits"). A load lists the items in record order, as the original's reader does. The Swift port saves and loads at every leg end of the
  replayed full run and gets the same resumed state as Python at all 30 (FullRunTests, digests from full_run_transcript.py).
  Each level keeps its items when Lex leaves it (the player and what he holds travel), in both ports and in saves
  (NOTES "A level keeps its items when Lex leaves it"). Open: open monitors, the game clock, other levels' figures, timeline clock origin (avoidance lists are applied).
- **Monitor viewport: observed in the original.** It shows a live render of the selected camera,
  stretched to the V rectangle and drawn with the monitor palette's grey ramp (128–159) by
  brightness (NOTES; screenshot `re/out/native_shots/`). Implemented in `monitor.py`; the cell
  monitor matches the native shot (`re/out/monitor_cell1_vs_native.png`).
  **Still open:** the exact viewport sampling and colour formula. Nearest-neighbour stretch and
  linear Rec.601 luma onto the ramp are our choices (correlation 0.85–0.91 with the shot); the
  original's rendering path has not been located in the executable.
- DOSBox-X is installed and boots the game from a scratch copy (NOTES "Running the original").
- **Original-game test automation:** `dosbox_live.py --control DIR --app-bundle` keeps one
  original session paused between JSON commands; `dosbox_control.py` drives keys and
  captures falls at verified figure-update breakpoints and runs modifier-key combat checks.
  A controlled fall records five descending samples matching the prototype velocity step;
  normal landing now matches the original soft motion (the position helper clears velocity
  before classification). Python and Swift grounding regressions cover the captured descent. Six overhead punches
  triggered nurse recoil while its scripted resistance kept health unchanged; rear contact
  set the authored wound/stunned state and started bouncing. A logged doorway-contact
  fixture then triggered `ZAPPED` and the original script removed FIRSTBOT, with Lex at
  health 100. The persistent client now automates these checks without a restart.
  The ports apply the nurse's bouncy rollback path (the generic 3D rebound with persistent velocity since 2026-10-22, both ports), restore the bouncy flag from
  saves, and execute `KILL` retirement. `SPARWITHPLAYER` links both enemy pointers, so
  keyboard punches register without injecting a player target. The deterministic nurse
  scenario covers front/rear hits, looping bounce, staged bar contact, one zap process,
  removal and a key-driven corridor crossing at health 100. The original reached zap
  from staged push positions using only keys, then escaped to BLK1 at health 100
  (`re/out/nurse_validation/validation.json`). A post-wound route now reaches zap, removal and corridor escape at health 100
  in Python and Swift using only keys after the front/rear combat pose fixtures;
  no bar-contact placement remains. Exact original-vs-port trajectory parity
  remains open; persistent x/y/z velocity, the generic 3D rebound, SETVELOCITY / LEAP and the knockback sign are done in both ports (NOTES "Persistent velocity"); explosion debris remains unimplemented.
  Deferred AI startup now occurs in a visible, living figure update, matching
  `FUN_1088_3371`; hidden Caynan no longer starts early and overwrites the nurse
  zap guard. CONTINUE never blocks its caller; completed unfrozen player poses
  accept fresh input. The temporary ceiling-clearance change was restored.
  Save files now copy to GameDir in both live and parity runners. Reuse the paused process: emulator snapshot restore crashed
  DOSBox-X on resume, and repeated native loading produced a guest protection fault
  (NOTES "Persistent testing").
- **Native stage 4b music: done.** Swift decodes MUSIC.FLX, sequences XMIDI bars, loops,
  branch entries and direct/overlay/replacing transitions, and plays MIDI through Apple's
  built-in synth in the same audio engine as effects. Four native parity tests match Python
  event streams, and a fifth checks all 49 songs; the Swift tests pass. A five-second music-only tap from
  the running app contained nonzero synth audio.
  MIDI messages are delivered on the 30 Hz app tick, so live timing can vary by up to one frame.
- **AdLib music: done (2026-10-17, both ports).** The original plays MUSIC.FLX's second
  arrangement (entries 128.., transitions 260, timbres 259) only with its AdLib driver (INSTALL.OPT
  `MusicCardId` 1..3; the engine checks the driver for an "MPU" tag). `re/formats/adlib.py` ports
  that driver (AILADLIB.DLL, decompiled: voice slots, priorities, register formulas) and
  `opl.py` models the OPL2; `AdLib.swift`/`OPL2.swift` match them bit for bit (register-write
  and chip-output hashes; 6 native, 10 Python tests). The app renders the chip live in a second
  source node at 49716 Hz, timed to the music timeline, and Game > Music Device switches GM/AdLib
  mid-game (replaying the music log). The XMIDI relative volume is now the recovered percent
  (CC 7 · level / 100), not rel/127; three music hashes changed. The opening renders both ways;
  a live tap with each device differs only by the music. Open: the original's phase of the
  driver's 5 Hz priority pass (assumed to start at music time 0); the OPL2 model is not the
  real chip's DAC. Not live-tested: switching device in the middle of a song.

1. **Face lighting** (done 2026-10-16; see NOTES "Face lighting").
   - The global light `1290:cb84` keeps its constructor state for the whole game: point light,
     zero position and strength, ambient 0. Its setters have no callers, and DOSBox-X memory
     during the opening confirms it. Every flat and Gouraud intensity is therefore 0. A ramp
     face draws at its ramp start (`start + ((offset·0 + 128) >> 8)`); other colours are kept.
     The original framebuffer shows the nursebot's untextured faces at exactly 0x80.
   - `shade_mesh` and native `Shading.colors` implement this with byte parity. The camera
     headlight placeholder is gone. Ramp membership is now inclusive (`FUN_1150_1ef4`).
   - Textured faces copy source indices directly (`FUN_1018_0ec4`), unchanged.
   - Depth haze: none. The palette loader opens `PALFADE.IFF`, but its `D_HZ` handler
     (`FUN_1158_0655`) is an empty stub and `FADE` is never read (NOTES "Face lighting").
2. **Opening nurse encounter: playable preview.** `world.py` runs the nurse AI, enemy
   queries, turning, syringe hits, damage, and scripted knockout/revival after two hits.
   Lex starts with `MY_BATTERY` in `INVENTORY` and no weapon in hand. Space tries each held
   item's nearby-object combination (for example, FORK on CELPAN), a nearby object's bare
   `*_USE`, then held-item use; the combat shoot key invokes `LEX_ATK_SHOOT`, whose `ISCARRYING`
   checks leave unarmed Lex idle. A right-hand blaster
   follows the script's attack branch in a test. Lex can walk through open DR3 into the
   corridor while the nurse approaches; the camera follows. PIMM inventory opens, and weapon
   pickup works: Enter at the CHAOS blaster puts it in Lex's right hand, and the shoot key then
   takes the blaster branch of `LEX_ATK_SHOOT`. Melee hits use the recovered engine test (striking limb vs `.COL` cubes on frames 4…n−5, zones, frame guard bytes, armour, difficulty and the stimulus labels; NOTES "Melee hits"). The DAMAGE statement, energy damage, hit/block sounds, `_WOUNDS`/`_DEATH`, the die method and the combat auto-turn are ported; the first live punch (frame 7, recoil_tl) is reproduced. Knockback now moves the target in both ports. See
   `re/out/combat_survey.md` and NOTES for the script path.
3. **Player control** (prototype started). `keys.py` maps the recovered PC scan codes to held
   movement, combat motions, Space use, and PIMM screens; `world.py` and the SDL2 preview
   (`play.py`) use it. Native-format save/restore works in the Python prototype with the
   script-process limitation above; gamma keys and the original R/O/S/L/Alt+X option keys work,
   with the recovered save guard (NOTES "Options keys and the save guard"); Alt+V shows the
   recovered build caption ("BioForge  ver f1.01~(C) 1994, 1995 Origin Systems", refused while
   one is still showing, same NOTES section). Enter picks up and puts down items (NOTES "Item
   pick up and put down").
   Inventory READY equips its selected item in the declared free hand; I/P stow a left-hand
   item before opening PIMM. The original page has no general two-item combination control.
   - Manual, scripted `GO`, and AI root movement use the recovered figure hull built from
     `EXTENT`, root z and foot depth. With collisions enabled, movement selects the figure's
     current PHYS area and checks that area's `physical_objs` (every PHYS touching the area box grown
     by 0x1000, `FUN_1138_131c`); `_<phys>_SPACE` changes
     PHYS state. DR3 open permits passage; DR3 closed blocks it. This follows the movement
     path `FUN_10a0_22e1` → `FUN_1058_1a1b`, replacing the earlier camera-side point test.
     Scripted `GO ... WALK|RUN` waits for arrival before later script commands resume,
     preserving authored collision-off intervals. The signed score is the original's fixed-point
     arithmetic (hull volume + solid − space overlaps, > 0 blocks), with `FUN_10a0_21b2`'s
     lift of the hull bottom onto its support; Lex's live query hull and volume match. Strides
     step like the original mover and a block slides along the wall or returns to the last good
     step or lifts onto a low step (`FUN_10a0_0ead`); walking into a closed DR3 stops Lex at y −14100 live and within ~30 units in the port.
     Each area scores its physical_objs as the original builds them (`FUN_1138_131c`).
     Living figures push each other out of their summed `PERSONAL_RADIUS` before every move, and
     figures start with their FIGR record's (or `MAX HPS`) object locals, both matching DOSBox-X.
     Motion frames last `MY_SPEED` × the motion's frame time (header byte 76) in 1/256 ticks of the
     60 Hz clock, adjusted at the motion's start by the difficulty level (other figures: −64 per level,
     +128 at level 0; the player: repeated ATK_H/ATK_F attacks slow down; `FUN_1098_0088`,
     `FUN_1088_1854`), and turning motions (flag bit 0x01: ATK_M7, TURN_LEFT/RIGHT, …) add their
     root yaw to the heading at each loop and when replaced (`FUN_10a0_1c83`). The parity harness
     (`nurse_activation`) puts the nurse within 35 units of the original after activation, and Lex's
     wake-up push lands 9 units from the original's; the escape scenario walks straight and the push
     carries Lex through DR3 (NOTES "Motion timing and turning motions").
     `ADDAVOIDANCEPOINT`/`REMOVEAVOIDANCEPOINT` keep up to 8 (object, radius) pairs per figure; the same
     push moves a living figure out of each at (r << 11) / 100, even with collisions off. The opening's
     lists match DOSBox-X entry for entry, and a nurse moved into AVDBAR3's circle is pushed to the
     port's exact point; no figure enters a circle in the opening, so its digests are unchanged
     (NOTES "Avoidance points").
     IMAG triggers fire in both ports (NOTES "IMAG triggers"): per frame each figure's hull is
     tested against its area's triggers (`FUN_1088_51c3`), setting the InTrig bytes and running
     `<trigger>` (player) or `<trigger>_<figure>` blocks every frame or on entry only; camera
     triggers force their camera; the mover stops on entering a trigger that has a block
     (`FUN_1088_50c1`); `AMINTRIGGER` tests figure hulls. Live check: walking Lex out through
     the open DR3 trips the live cell bars (DR_ZAP3) and shocks him back, as in the original.
     `STOPMOTION` ends a motion with the pose held; the figure is still pushed and grounded.
     **Hidden figures are ported (2026-10-17):** `fig.hidden` is recomputed every step from the
     figure's viewing-camera list and the current camera (FIGR flag 0x04, NOTES "STOPMOTION and
     hidden figures"); a hidden figure is neither animated, moved, pushed nor pushed-against by
     others, matching a DOSBox-X live check (the earlier "a stopped USE_BOT is not pushed" was
     this). Background CHAOS figures (CAYNAN, GUARD1, HALMECHO, USE_BOT) now freeze off camera
     during the opening, changing the boot fixtures. Rendered poses now interpolate limb angles and
     root height between interior motion frames in both ports; the final frame holds until wrap.
     The motion-start blend is shorter than a 30 Hz sample for the decoded angles and remains
     unmodelled; `PLANTFEET`'s yaw offset is also not ported.
4. **Audio** (prototype and native app; see NOTES "Sound and music"). The native app plays
   effects through 8 voices and music through the `msyn` AU + `gs_instruments.dls` or, with
   the AdLib device, the AIL AdLib driver port + OPL2 model. Optional: finer live GM timing.
5. **Monitors, inventory, subtitles** (mostly done; see NOTES "Monitors, PIMM and player keys").
   - PIMM renders; SDL mouse hover and left-click reach active monitor buttons and their
     `MON_JUMP` labels. The default and script-selected hand pointers render from CAM frames.
     Escape reaches its script. Other physical keys are not mapped to
     monitor controls; only mappings recovered from the original should be added.
   - Monitor text resolves `%variable%` against live VM globals; `%%` prints `%`. `%time%`
     uses the recovered `day-HHMM` format and an inferred 60 Hz engine clock. Journal entries
     are awarded by scripts, stay in award order, suppress duplicates, and retain their award
     timestamps. `MON_DEFINEVIEWPORT` renders named cameras, including remote-level CTR4, in
     the viewport element. Native screenshot comparison confirms the full camera view is
     stretched into the V rectangle and mapped to the monitor's grey ramp; this is implemented
     in the preview.
   - `MON_CODE` opens options screens from the original OPTS.CAM art and returns immediately.
     The authored `START.scr` polling loop waits for difficulty selection before creating
     Lex; automated replays choose Medium explicitly. Difficulty selection updates
     `_difficulty_level`; audio values, credits, return/cancel and exit are represented in the
     preview. The nine-slot save/load selectors render, navigate, and ask for confirmation.
     The preview resumes native saves and writes archives accepted by the DOS game; its own
     saves do not yet serialize every live script process.
     Audio, gamma and detail follow the recovered callbacks (NOTES "Options settings"). `MON_SIMULATE _KB_TAB` advances to an active monitor button, and
     `MON_DESTROYOPTIONS` closes the options dialog. Native pause behavior is implemented;
     the dialog's UI beeps are not modelled.
   - The pointer CAM's indexed colours use the active monitor palette; original remapping,
     if any, is unconfirmed.
   - The subtitle font is 1.FNT (confirmed by `RED.OPT` `captionfont`).
6. **Native engine (started 2026-10-15).** Stack decided: Swift + AppKit + Metal, SwiftPM package
   in `native/`.
   - `BioForgeCore` (Foundation only): decoders and a software 320×200 indexed framebuffer that
     mirror the Python algorithms, so outputs can be compared byte for byte (oracle fixtures from
     `re/tools/native_fixtures.py`, derived hashes only, no game bytes).
   - `BioForgeApp`: AppKit window, Metal presents the framebuffer (palette lookup in the shader,
     integer scaling, 4:3 aspect toggle); audio later via the `msyn` AU.
   - Game data is never bundled: File > Open Game Folder… or `BIOFORGE_DATA`.
   - Stage order: 1 formats (Flex, IFF, CAM, levels) + camera viewer → 2 meshes, skeletons,
     motions and the figure renderer → 3 script VM and world → 4 audio → 5 monitors, subtitles,
     saves, input.
   - **Stage 1 done:** Flex, IFF, CAM and level decoders match the Python oracle byte for byte
     (35 CAM files / 1332 frames hashed, all 8446 ROOMS+MONITORS frames decode); the app shows
     room cameras (Left/Right arrows), with a 4:3 toggle and full screen.
   - **Stage 2 done:** meshes (40/40), skeletons/skins/motions (7 figures, 754 motions), FK and the
     depth-sorted indexed compositor match the prototype; 7 fixture scenes are pixel-identical. The
     app animates each level's figures over the camera (30 Hz ticks; Space pauses). Figures are not
     yet hidden by viewing-camera lists (those come from scripts in stage 3).
   - **Stage 3a done:** script detokenizer, parser, code generator and VM in Swift match Python on
     all 107 scripts (text, AST, 24,664 statement offsets, 29,971 instruction lines) and on 14 VM
     traces plus 26 synthetic scripts. Opcode names are generated into `ScriptTokens.swift` by
     `re/tools/native_script_tables.py`.
   - **Stage 3b done:** the Swift `World` (MT19937 RNG port, keys, sound bank, world logic) reproduces
     the prototype exactly on the 1100-tick boot and all scenarios (engine calls, logs, checkpoints,
     every compared frame). The app starts New Game (Game > New Game ⌘N; Debug > Camera Viewer).
     Stage 3b had no monitors, PIMM screens, options UI, subtitle drawing or audio output;
     audio, subtitles, monitors and the options dialog have since been added in stages 4 and 5.
   - **Fixed (2026-10-16): figure grounding.** Both ports follow the engine (NOTES "Figure grounding" and
     "Grounding, recovered 2026-10-16"): F comes from the engine's fixed-point FK (MAN 2312; every INITGAME
     record's saved F matches), the hull and its floor query (with the 'Q' pit pass) decide support,
     unsupported figures fall at −frame time/5 per frame and land with land_hard/medium/soft, and the whoah
     edge probes play at ledges. Level figures take gravity and the collisions bit from their FIGR flags;
     created figures have gravity (HAS_GRAVITY). Standing Lex is at exactly −5133, confirmed in DOSBox-X live
     memory (`re/tools/dosbox_live.py`). Prototype and Swift port match; parity exact.
   - **Open (grounding):** a fall was not observed live (none happens in the opening). Movement collision follows figure
     flag 0x02 (every figure collides unless its record or `COLLISIONS OFF` says otherwise) and `FUN_10a0_0ead` is ported in
     both ports (step-up, landing, unstick, mantle, BONK); Swift's `collisions` is `!noCollide`.
     See NOTES "Next steps" item 2.
   - **Stage 4a done: sound effects.** The 717 samples, the 8-voice mix and positional volume play live
     through one AVAudioSourceNode (`SoundMixer`/`SoundOutput`); the offline mix of the 1100-tick boot is
     byte-identical to the prototype, and the live renderer equals it sample for sample. Game > Mute
     (⌥⌘M). The master-volume table is modelled since stage 5h.
   - **Stage 4b done: music.** `Music.swift` matches Python's event streams for song starts,
     direct and bar-synced transitions, overlaid transitions and pause/resume. `SoundOutput`
     routes MIDI through Apple's `msyn` AU with the system GM bank. Live delivery occurs on
     the game tick.
   - **Stage 5a done: subtitles.** The app draws active captions from `DATA/1.FNT` over the room
     view, with the prototype's 50% palette shade approximation for the caption box. Bare scene
     rendering stays separate for camera feeds and frame parity.
   - **Stage 5b first slice done: PIMM main.** P runs the authored PIMM script, which builds
     the `PIMM.CAM` screen; the pointer follows the mouse/trackpad, and Exit or Escape runs
     the script's `MON_STOP`. The initial indexed frame and palette are byte-identical to the
     Python prototype.
   - **Stage 5c done: PIMM inventory.** I or the main screen's Inventory button opens the
     authored inventory page. The starting battery's list row, description and artwork come
     from `TEXT.FLX` and the item script. Scroll controls select an item; READY places it in
     its declared free hand and exits. I/P first stow a left-hand item; Space runs item use
     and scripted object/item combinations, and Enter drops a held item. Initial, scrolled,
     and reopened inventory frames are checked against Python's indexed pixels. Exit closes
     a directly opened page; Escape returns to main when entered from there.
   - **Stage 5d done: PIMM diagnostics and journal.** D/J and the corresponding main-screen
     buttons open the authored pages. Diagnostics renders clipped scale art for health,
     battery energy and PFD charge. Journal fills its list from awarded LEX log entries,
     retaining award times for `%time%`; its scroll controls follow the script. Representative
     diagnostics and populated-journal indexed frames match Python byte for byte.
   - **Stage 5e done: monitor camera viewports.** `MON_DEFINEVIEWPORT` now draws live room
     cameras in the authored V rectangle, stretching the full view and mapping its source
     colours into the monitor's grey ramp. Remote cameras such as CTR4 resolve through
     their owning level's CAMR record without changing the selected game camera or firing
     camera events. CELL/CE11 and MLBT/CTR4 indexed frames match the Python prototype
     byte for byte.
   - **Stage 5f done: options dialog.** `Options.swift` ports `options.py`: OPTS.CAM main,
     difficulty, audio, credits, nine-slot load/save and confirmation screens, with font-1
     captions, the same control hit order and action strings. `MON_CODE` opens it, the
     world pauses as before, and the app routes the pointer, Escape and credits scrolling
     to it; Exit → Yes quits. The app no longer auto-picks Medium (`GameSession.autoDifficulty`
     stays on for tests). Ten screen states match the Python frames byte for byte.
   - **Stage 5g done: save and load.** The save formats (`SaveGame`, `SaveScript`, `SaveObjRec`)
     round-trip every GAMEDAT, INITGAME and sample-save file byte for byte; `SaveWrite` writes
     the same files and `.IM1` as `savewrite.py`. `Resume.swift` ports `resume.py`: resuming the
     shipped GAMEDAT and the native sample matches Python right after resume and after 300
     ticks. The dialog's save/load slots work; the app keeps saves in
     `~/Library/Application Support/BioForge/Saves` and swaps to a loaded game.
     `BIOFORGE_LOAD` boots a save. Python's limits carry over: the port's own saves don't
     serialise its motion phase or record tails. Swift deviation:
     remote-level cameras still come from INITGAME, not from a save's level files.
   - **Stage 5h done: options settings.** Recovered from the dialog callback and ported to both
     ports: audio panel (effects/music 0–100 in tens, toggles, subtitles, live apply, Cancel
     restores), the default master-volume table (`(i·v) >> 8`, so even 100 scales by 255/256),
     music level as CC7 scaling (AIL relative volume, recovered 2026-10-17 as a percent: v·level/100), the gamma panel and
     keys (palette offset (g·32 − 960)/100 per 6-bit channel, presentation only), and an inert
     DETAIL button (no callback branch). Settings come from INSTALL.OPT; the app keeps changes
     in its user defaults. The boot audio fixture changed because of the master table.
     **Next:** stage 5 and face lighting are done; continue with the ordered list above (item 2
     onward) and the open grounding items above.

## Known assumptions to revisit (all marked in code comments)

- (Resolved) `CONTINUE` looping: the loop rule is the motion header's 0xfe marker (NOTES "Movement fixes"), no longer a first-equals-last-frame guess.
- (Resolved 2026-11-20, re/NOTES.md "Engine assumptions settled".) Animated textures are drawn from their ANIMATE state, frame 0
  until animated; camera `<cam>_LOAD` events were already traced, a level load leaves auto cameras as they were, and "nearest camera"
  is the engine's approximate length; LOADLEVEL kills all but the caller's CALL chain and stops all voices but the one it names; a CALL
  child runs its first slice at once (as the engine does), a PROCESS child only from a `{` routine; a CALL parent or SUSPENDWHILE
  waiter woken by its child's end runs in the next scheduler walk, not inside the child's finish (`1238:077f`, `1230:177a`). Left open:
  the original walks ready tasks in slot order (lowest free slot), the ports in creation order; they differ only after a slot is
  reused. Figures are not tasks (updated before the walk, `1150.c:950-970`). The zero-g height (2026-11-21) was the idle request's
  deferred motion task, not the walk order: re/NOTES.md "Lex's height in the zero-g room".
- (Resolved 2026-11-19: `BREAK n` numbers switches per file and always names the innermost one; re/NOTES.md "BREAK n".)
- The scenario API's `turn` input uses 3° per 30 Hz tick; it is a preview choice, not recovered from
  the executable (held turn keys play the turning motions, which rotate as in the original). The extent hull's world-unit scale and vertical anchor are provisional.
