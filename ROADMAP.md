# Roadmap to a first playable beta

Written 2026-11-02. `STATUS.md` says where things stand; this file says what comes next and in what order. An agent picking up work starts at the first unchecked item, without waiting to be asked.

## What "first playable beta" means

A person who owns the game can:

1. Open a double-clickable macOS app and point it at their own game folder.
2. Start a new game and play to the ending, in the native app, with real keys, at Easy.
3. Save and load anywhere the original allows.
4. Finish with no crash, no dead end and no shortcut.

Differences from the original are allowed if they are written down and don't stop play. Medium and Hard and upscaling are not part of the beta.

## Where we are

- **The whole game runs start to finish in the Python port**, reaching `EXIT` in about 160,000 ticks, but only through the harness. 22 of 26 random streams finish.
- **The harness still takes 7 kinds of shortcut** (`re/playthrough/full.md`), none of them a fight. Most are scripted placements that save the harness a walk.
- **The native app's code replays the whole run, matching Python at every checkpoint** (`FullRunTests`). The app itself has never been played that far.
- **Nobody has played through in the port.** Every run so far was scripted.

## Milestones

Each one is finished when its check passes. Sizes are rough: S is a few PRs, M is many, L is the biggest kind of work on this list.

### 1. Close the assumption audit (S)

- [x] Report every `ASSUMPTION` marker as wrong, confirmed, a simplification, unknown or not engine (`re/playthrough/assumption-audit.md`).
- [x] Fix the ones a player would notice, in both ports: items 1-8 of the report's ranked list.
- [x] Settle the report's medium-impact unknowns, or move them to the milestone that needs them.

**Done when:** the report is merged and its high-impact items are fixed or moved into a later milestone here.

### 2. Prove the native port runs the whole game (M)

This comes early because every later check should run on the code a player uses.

- [x] Replay the full run's recorded inputs and staged steps through `GameSession`, headless (`FullRunTests`, about 5 seconds).
- [x] Compare with Python at every checkpoint: level, every figure's position and motion, HP, script globals, process count.
- [x] Fix each divergence where it first appears.

**Done when:** a Swift test reaches `EXIT` with the same checkpoints as Python.

### 3. Remove the real content gaps (L)

These are the shortcuts standing in for play. Worked in this order, because each opens the next:

- [x] `reactor-shutdown`: drive the reactor puzzle (SHUTDOWN.scr).
- [x] Monitor puzzles: tomb, city and tube monitors, played by clicks.
- [x] `platform-door`: not a wall. Drogg 3 drops REFLECT, and its mirror suit opens PLTDOOR.
- [x] `temple`: marines, grenade. Comes before the walks: without the mirror suit, MARINE2 on the BEACH ledge and the LANDPAD airlock kill Lex.
- [x] `beach-climb`, `landpad-walk`: the walks back up to the pad ledge and across LANDPAD.
- [x] `zero-g-flight`: both crossings are flown with the Captain's TONFA. Getting the gun still rests on a staged fight (milestone 4).

When a shortcut exposes an engine bug, compare with the original live, fix both ports and add a test.

**Done when:** none of these shortcuts is left in `playthrough_full.py`.

### 4. Make the fights winnable by a person (M-L) - done

The harness wins fights by picking seeds and a one-key punch loop, and skips others. A player gets neither. It's also unknown whether the port's fights are as hard as the original's.

- [x] Sample the same fight live against the original and the port: damage, timing, hit rates. Guard 1, `GRDCON` and Drogg 1 (`re/tools/fight_sample.py`, `re/NOTES.md` "Fights sampled in the original").
- [x] Fix the differences that are found: `CONFRONTENEMY`, recoils and the kept root z. Still unexplained, and listed in `re/NOTES.md`: Guard 1 attacks more often in the port, and Drogg 1 after his sixth super recoil (`GRDCON`'s hit rate was resampled and matches, 2026-11-20).
- [x] Try every attack in every fight (`re/tools/fight_sweep.py`, `re/NOTES.md` "Every attack in every fight"). ATK_H4 is best overall and ATK_F9 second; live, ATK_H4 beat `GRDCON` five of five and Guard 1 three of four. How quickly Lex presses again matters more than which attack he uses.
- [x] Give the harness a real fighting routine, and stop picking seeds (`fight-seed` is gone). 17 of 24 RANDOM streams now finish the game (`re/tools/run_seeds.py`, `re/NOTES.md` "The fighting routine"); 21 of 24 after the fixes below.
- [x] Make the failing streams finish: all 24 RANDOM streams finish (`re/tools/run_seeds.py`). The last fixes: MECHO2 shot from the cabin's north corner, the trip back to the platform for a new battery when the bike's is under 375, the hard suit put back on when the GRDCON fight knocks Lex into the machine, and the fighting routine switching combat mode back on after a quake drops it (`re/NOTES.md` "The suit machine during the GRDCON fight" and the entries before it). Not checked live.
- [x] Fight what the run skipped: AIRMECHO and the Captain are both fought now. AIRMECHO is fought by keys now: Lex sidesteps each bolt and shoots three times between volleys (`re/NOTES.md` "AIRMECHO by keys"), on all 25 streams; not played live. Earlier, AIRMECHO was checked live: the original loses a straight duel from where the scene leaves Lex too, and the port matches its timing, shot rate, damage and cameras (`re/NOTES.md` "AIRMECHO, checked live"). Winning it needs three hits before its first bolt lands. `bot-fights` is gone: every LANDPAD and BEACH bot is alive, and Lex runs past them (the ledge, and FROM_PAD to ZIP1). That costs one stream of 24: the bots leave Lex about 60 HP down by the dig site, and although he is healed to 100 before the battle room, Drogg 3 then wins on one stream (14, or 6 with repairs from 45 HP). MECHO2 is shot down with real keys now, from the cabin's corner, and Roland is beaten down until he restarts the gun himself (`fight-outcome` is gone).
- [x] Get past the sentry `HALMECHO` and the tower bots without `sentry-*` or `hold-fire`. The sentry is passed by play, both times (`re/NOTES.md` "The hall sentry and the tower bots"). The tower bots are shot: five of the six fall from spots where they cannot answer, bot 5 is off the route, and no stream of 26 fails on the deck (`re/NOTES.md` "The tower bots shot"). All five firing spots were checked live. `GRDHANG` (`guard-ai-off` is gone) and `MARINE5` are fought.
- [x] Win the Captain (`TUMOLT`, 200 HP) for the TONFA, by keys in the port: Alt+KP4 tapped at a steady rhythm keeps him in recoil, and 2 of 26 streams lose to him (`re/NOTES.md` "The Captain by keys, won"). The one valid live attempt matched the first five hits and then lost, so this is not confirmed in the original.
- [x] Get a weapon through the route the game intends: Lex kills `GRDCON` in the suit, repairs on the bike's battery, then kills `GRDHALL` for `BLASTER2`, on 19 of the 20 streams that finish. Not checked live.

**Done when:** the full run passes at Easy on several seeds, with no fight shortcut.

### 5. Save and load anywhere (M)

`STATUS.md` records that the port's saves don't yet store every live script process. That entry predates much of the work since, so this starts by checking it.

- [x] Save, reload and continue at every checkpoint of the full run, comparing the state afterwards in both ports. Saves now write the player, every figure's state, the script processes and the items (`re/NOTES.md` "Prototype saves write figure state", "Prototype saves write the script processes"). `re/tools/save_resume_check.py` does this in Python: all 29 saves play on to `EXIT` (`temple-monitor` is skipped: a monitor stays open there). A load restarts every running animation from its first frame, in both ports, as the original's does ("The original does not save the motion phase either"). The check's `--control` does only that restart, with no save, and rounds positions and headings to what the records hold; it also finishes all 29. The last two failures, `tanks-back` and `beach`, were harness steps with no slack ("Two save points failed on the heading's last bits"). The Swift side checks parity instead: `full_run_transcript.py` records, at each of the 30 leg ends, the digest of Python's save-then-load state (`resume_digest.state_lines`), and `FullRunTests` saves, unpacks and loads the same point in Swift and compares it (all 30 match; `SAVE_CHECK_LINES=<leg>` prints the lines in both).
- [x] Keep a level's floor items when Lex leaves it, in both ports. Each level keeps its items, and the ones its figures hold, as the original does (`re/NOTES.md` "A level keeps its items when Lex leaves it"); saves write them into that level's file. The ending now takes Lex's old battery out of the bike (BAT_100_USE) instead of a fresh `ORIGBIKEBAT`. The level's figures are kept too (next item).
- [x] Keep a level's figures when Lex leaves it, in both ports: a killed figure stays gone and the others come back as he left them; saves write them into that level's file (`re/NOTES.md` "A level keeps its figures").
- [x] Roll the credits as the original does, in both ports: at the ending (then the game quits) and from R or the options; checked pixel for pixel against the original (`re/NOTES.md` "The credits roll").
- [x] Fix what doesn't survive, including the process list. Found by diffing and by running the loaded game beside the unsaved one (`re/tools/save_diff.py`, `save_trace.py`): the processes, motion tasks, AI links, avoidance lists, the keyboard hook and other record fields ("What the save lost, found by diffing"), each level's items, and the item list's order, which a load now rebuilds from the records as the original's reader does ("The inventory order after a load"). The last two failures failed without a save too, on the records' 8.8 heading; both were harness steps with no slack, now fixed ("Two save points failed on the heading's last bits"). Not saved yet, with no failure found from it: the game clock, open monitors, other levels' figures and the timeline clock origin.
- [x] Check that a save from the original loads in the port, and the other way round. Both ports resumed the original's saves already; the original now loads port saves too, after the writer started writing each script process the way the original's kernel does (brace depth, links, local count, timeline class; "Port saves load in the original"). Checked live at three save points (a round trip of the original's own save, `guard1`, `hall-to-elevator`): no fault, Lex where the port saved him, and after `guard1` the original runs the processes the port saved.

**Done when:** the run still reaches `EXIT` with a save and reload at every checkpoint, except where it also fails when the animations are only restarted from frame 0 without a save. The original's own load does that restart, so the port keeps it.

### 6. Make it a real app (M)

- [x] A double-clickable `.app`, with a folder picker for the game data instead of `BIOFORGE_DATA` (`native/build-app.sh`; the folder is asked for once and remembered).
- [x] Remappable keys that work on a MacBook with no numpad (Settings > Controls). The defaults use A for the Ctrl attacks and `/` for keypad 5; nobody has fought with them by hand yet.
- [x] Sensible window handling, plus a clear message for a wrong folder or a crash. The window keeps the picture's shape for either aspect setting and the game pauses in the background. A missing or wrong folder and unreadable data are explained in the window or an alert; a real crash gets macOS's own report, since a Swift trap can't be caught.
- [x] Game controllers (Game Controller framework): found automatically, remappable in Settings > Controls, the left stick and D-pad are the directions and move the pointer on the game's screens. Not tried with a real controller yet.
- [x] Follow Apple's Human Interface Guidelines for everything that isn't the game itself: standard menus, Settings (⌘,), sheets for the folder picker and alerts, an app icon (a full-bleed 1024 px square the system masks, original artwork, `native/Resources/make_icon.py`), and Help > BioForge Help (⌘?), one page on setup, saving, sound and the controls with the player's current keys, plus Keyboard Controls…. Not a Help Book, so the Help menu has no search field.
- [x] Performance check for the whole game on your Mac. On an M4 Pro, release build, every tick of the recorded game plus the frame the app draws takes 0.5 ms on average, 0.9 ms at the 99th percentile; every tick over 10 ms is a level load, the slowest 116 ms, which drops a few frames while a level loads (`FULL_RUN_PERF=1 swift test -c release --filter frameTimes`; `re/NOTES.md` "Performance over the whole game").

**Done when:** the app runs from a fresh copy with nothing set up in a terminal.

### 7. Human playtest (M, needs you)

- [ ] You play from the start; each session ends in a list of bugs.
- [ ] I triage and fix them, and compare with the original where something feels off.
- [x] Add a log and a way to attach it, so a bug report says where you were: Help > Report a Bug… makes a zip with where Lex is, the session's log and a save of that moment (`native/Sources/BioForgeCore/PlayLog.swift`, `native/Sources/BioForgeApp/BugReport.swift`).

- [x] Tester support (2026-11-15, after other ports' practice: OpenRCT2 replays, ScummVM release testing, OpenXcom's differences list): each session's inputs are recorded and a report replays them exactly (`SessionReplay`, `REPLAY=`); builds and reports carry the commit; a crash is offered as a report on the next launch with macOS's crash report; autosaves on level change; Debug > God Mode / Refill Health / Open Save File…, logged and recorded; `save_resume_check.py --export` writes the route's save points.
- [x] `KNOWN_DIFFERENCES.md` (fidelity policy, open gaps, kept quirks, port extras) and `PLAYTEST.md` (sessions per area, triage).

**Done when:** you have played to the ending in the native app.

### 8. Beta release (S)

Decided 2026-11-21: a first public release, **v0.1 preview**, goes out before milestone 7's playthrough is finished: the Mac app
signed and notarized (universal), the Linux AppImages and the Windows zip as previews, from a new public MIT repository (a filtered
export of this one, `tools/publish_public.sh`, without `re/decomp`), with a page on the author's website. This repository stays private.

- [x] Signed and notarized build. The game data is never included. (v0.1.0, 2026-11-21: universal, with the art model, on the public repository's Releases.)
- [x] Short player guide: setup, controls, known differences (`PLAYER_GUIDE.md`).
- [x] Detect the game data by checksum (size and MD5 of the GOG files, as ScummVM's detection tables do) and say which file is missing or unknown. GOG 2.1.0.14 English is the only known release; missing files stop the start, others are reported as unknown and still run.
- [x] A changelog and a Known Issues list with each build, with a note on save compatibility (`CHANGELOG.md`).
- [x] A non-affiliation and trademark notice in the app (About, Help, Info.plist), README and player guide.
- [x] `README.md`, `STRUCTURE.md` and `STATUS.md` brought up to date (2026-11-19).

**Done when:** someone else can install it and start playing from the guide alone.

## Bugs to fix later

Found along the way, not blocking the current milestone. Each one links to its notes.

The last audit findings (the CHAOS drip after a load, FORCERELOAD during a flic, corrupt saves, the one `swift test` crash and the `operating-room` save point) were closed on 2026-11-15: `re/NOTES.md` "The last audit findings".

- **The scripted run's remaining failures are its own key play, not game bugs** (2026-11-17: 29 of 29 from the save, 29 of 29 with the animations only restarted, 23 of 26 seeds).
  - Seed 16, `reactor-shutdown`: a LEVEL1TREMORS quake holds Lex about 260 ticks between the levers, and the run is then too slow for the reactor countdown (SHUT_DOWN_LOSE). Speeding the route up moves every stream (tried: net worse).
  - Seed 9, `tower-exit`: Lex reaches CONTROL with 45 HP, the battery at 9 and the medkits spent; two MECHO2 bolts are 92 HP. The fix belongs in how earlier legs spend health.
  - Seed 19, `battle-room`: Drogg 3 wins with 13 of 200 HP left; `scenarios.fight` never started BIOREPAIR (heal below 35) and left 3 medkit charges unused.

## Checked at every step

- All test suites and the full run pass.
- Both ports change together.
- Anything claimed about the original is read from the code or checked live, and marked if it's only inferred.

## How the work runs

Agents work through the milestones in order without being asked, and commit, push, open and merge their own PRs once all checks pass. Each merged item gets ticked here.

## What I'll stop and ask you about

- Anything that changes what "beta" means, or drops something from it.
- A behaviour the original leaves open, where the choice is yours (like the 30 Hz update rate).
- Things only you can do: playtesting, signing with your developer account.

## After the beta

Not started until the beta is out: the update-rate check in the mind meld, Medium and Hard, and the Windows and Linux phases after the first (below). These stay optional and separate from the original-behaviour path.

- [ ] **Medium and Hard played through.** Started 2026-11-20: `playthrough_full.py` / `run_seeds.py --difficulty` play the route above Easy and finish Medium on 1 of 27 streams, Hard on none (`re/NOTES.md` "Medium and Hard played through"). Open: a fighting routine that reacts to the guard, since the battery runs out across GRDCON, GRDHANG and GRDHALL, and the Captain wins most streams after that; Hard's tower bots.

Language selection is in (2026-11-18): Game > Language switches voices and text between the English, German and French versions in the game data, as the original's installer did with `language=`; English stays the default and the English path is unchanged.

### Windows and Linux (Steam Deck)

The Mac keeps its native AppKit + Metal app; Windows and Linux get a second, smaller shell on the same engine. Each phase leaves the Mac app unchanged and passes the gates.

- [ ] **1. Portable engine.** `BioForgeCore` builds and its tests pass on Linux (arm64, x86_64) and Windows, and the full run gives the same results as on the Mac. Apple-only pieces are guarded: the app target (macOS only in `Package.swift`), Core ML upscaling, the memory guard and the art packs' DEFLATE (packs stay macOS-only for now); SHA-256 is hand-written (`Sha256`) instead of CryptoKit. Linux runs in Apple's `container` tool (README); Windows on a Windows PC (`native/WINDOWS_CHECK.md`).
  - 2026-11-18, Linux arm64 and x86_64: everything passes, the full run included, except the posed-vertex bits of 18 figure types: glibc's `cos`/`sin` differ from Apple's in the last bit for 25 of the 256 joint angles (`Mat3.rotated`). Decided 2026-11-19: `Mat3.rotated` takes cos and sin from `JointAngleTable`, Apple libm's bits for angles -256 to 511 (the tests use -140 to 255), libm outside it; the Mac's results are unchanged.
  - 2026-11-18, Windows x86_64: everything passes, the full run included, except the same posed-vertex check, for 17 figure types: the Microsoft C runtime's `cos`/`sin` also differ from Apple's in the last bit. The table above covers both.
- [x] **2. Shared host layer.** The shell's platform-neutral logic moves to a portable module, the Mac app uses it with no visible change: input routing, the 30 Hz loop and suspend, audio scheduling behind a sink, paths, settings storage, autosave, bug-report and data-check text. Key bindings move from Mac key codes to USB HID usages (what SDL uses), with a one-time migration.
  - 2026-11-19: `BioForgeHost` (Foundation and `BioForgeCore` only) holds `InputRouter`, `TickClock`/`GameHost`, `AudioScheduler` behind `HostAudio`/`MIDISynth`, `HostPaths`, `SettingsStore`, `Autosave`, `BugReport` and `HostText`; the Mac app runs on it unchanged. Bindings are HID usages; Mac-key-code bindings migrate once (`BindingsMigration`). Its tests pass on macOS and Linux (`container`, the audio digests included); Windows not run yet. PRs #153 to #158.
- [ ] **3. SDL3 shell** for Windows and Linux: window and full screen, the indexed frame through a streamed texture (sharp scaling, 4:3), keyboard, mouse and pointer warp, `SDL_Gamepad` (Steam Deck), effects and AdLib music through `SDL_AudioStream`, folder picker, XDG and `%APPDATA%` folders. General MIDI needs a SoundFont synth and comes after (done 2026-11-20, below). How the Mac menu settings (art scale, aspect, music device, bindings) appear there is decided at the start of this phase.
  - 2026-11-19: `BioForgeSDL` (PRs #161 to #167): all of the above, plus a settings screen (F1) for the Mac's menu settings and both bindings (decided with you: a screen, not a config file). Linux arm64 and x86_64 pass everything headless in `container` (Core, Host, SDL suites; the same smoke digest as the Mac). Left before ticking: the Windows run (`native/WINDOWS_CHECK.md`, also the first Windows run of the Host suite).
  - 2026-11-20: General MIDI in the SDL app through TinySoundFont (MIT, one vendored C header) with the player's own SoundFont (`.sf2`; none bundled, decided with you); the settings screen's Music row is General MIDI, AdLib or Off. Not yet heard with a real General MIDI SoundFont: its loudness against the effects and AdLib is still to tune by ear.
- [x] **4. Packaging**: Linux AppImage or Flatpak (Steam Deck Game Mode, controller defaults), Windows zip with the Swift runtime and SDL3; the player guide per platform.
  - 2026-11-19: an AppImage (decided with you; Flatpak/Flathub later, once the licence and publishing are settled). `native/package-linux.sh` builds x86_64 and arm64 in `container` and both pass the smoke run in clean Arch and Debian containers (PR #169); `native/package-windows.ps1` builds and smoke-tests the Windows zip on the PC (PR #170); the notices go into every package; `PLAYER_GUIDE.md` has install and first start per platform and the Steam Deck's non-Steam-game path. Still open, written down in STATUS: the Windows run (`native/WINDOWS_CHECK.md` does phases 3 and 4 together), a real Steam Deck and Linux desktop, Windows signing (SmartScreen), and the licence below before any package is shared.
- [ ] **5. High-Resolution Art off the Mac** (optional): an upscaler other than Core ML behind `Upscaler` and a portable DEFLATE; waits for the model licence.

Licence (2026-11-21): MIT for the port's code (`LICENSE`); `re/decomp` stays out of the public repository. Before: the project had no licence file, and `re/decomp` (decompiled code) needs a legal look (decided 2026-11-19: chosen later; until then the packages are built locally and not shared).

Upscaling is in, off by default and separate from the original path (View > High-Resolution Art: Off, 2x or 4x): indexed packs, palette-locked, with fades, palette changes and screen shake, built by the app on the player's Mac from their own game files, in the background (`PixelPack.swift`; `re/tools/pixel_pack.py` is the reference). The model's author, Venomalia, gave permission on 2026-11-21 to ship the converted model in BioForge (its licence alone allows only the unmodified original), so signed builds include it. Still to do: hand-repainting the worst frames through `--overrides` (painted numbers and logos), and movies at the higher scales (monitors, the options dialog and subtitles are done).
