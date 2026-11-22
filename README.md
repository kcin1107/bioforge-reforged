# BioForge for macOS, Windows and Linux

A faithful native port of BioForge, Origin Systems' 1995 action adventure, for today's Macs, with a preview for Windows, Linux
and the Steam Deck. It plays the whole game from your own copy, with the original's rules, saves, sound and music.

It also adds optional Readable Text, High-Resolution Art on the Mac (2x or 4x pixel art built from your own game files with
Venomalia's HDcube model, used with permission), remappable keys and game controllers.

**You need your own copy of BioForge** (the GOG release). This repository and its downloads include no game data.

- Download the [latest release](../../releases/latest). The Mac app is signed and notarized and runs on macOS 14 or later
  (Apple silicon and Intel). The Linux AppImages are previews, and a Windows zip follows once it has been tested on a real PC.
- [PLAYER_GUIDE.md](PLAYER_GUIDE.md) gets you started: installing, pointing the app at your game folder, the controls and
  the known differences.
- [KNOWN_DIFFERENCES.md](KNOWN_DIFFERENCES.md) lists what differs from the DOS game.
- [CHANGELOG.md](CHANGELOG.md) lists what is new in each build, with known issues and save compatibility.
- Found a bug? Open an issue and attach the zip from Help > Report a Bug… It holds a save and a replay of your last minutes.
  The app sends nothing anywhere. Questions and ideas go to Discussions, and [CONTRIBUTING.md](CONTRIBUTING.md) explains how
  pull requests get in.

Version 0.1 is a preview. The scripted playthrough reaches the ending in every build, but nobody has played it to the end by
hand yet. Medium and Hard are in, but only Easy has been played through.

The port's code is MIT licensed ([LICENSE](LICENSE)). BioForge is a trademark of Electronic Arts Inc. This project is not
affiliated with or endorsed by Electronic Arts or Origin Systems. Game art in screenshots is © Origin Systems / Electronic
Arts. See [Legal](#legal) for the full notice.

## For developers

This repository ports the 1995 DOS game BioForge (Origin) by reverse-engineering the original executable and data. The port
reads your own copy of BioForge; the GOG release 2.1.0.14 is the known one. The repository includes and distributes no game
data.

Other documents:

- [PLAYER_GUIDE.md](PLAYER_GUIDE.md): setup and controls.
- [STATUS.md](STATUS.md): the current state and history, progress and next steps.
- [STRUCTURE.md](STRUCTURE.md): the map of the repository and its dependencies.
- [ROADMAP.md](ROADMAP.md): the milestones.
- [re/NOTES.md](re/NOTES.md): format and engine findings.

### Repository layout

The repository has two parts:

- `re/`: a Python reference interpreter. It holds format decoders, the script VM, the engine binding, playthrough harnesses
  and tools that compare it with the original running in DOSBox-X.
- `native/`: a native Swift port that reads the same data.

The native port is split into these modules:

| Module | Contents |
| --- | --- |
| `BioForgeCore` | The engine. |
| `BioForgeHost` | Portable shell logic: input routing, the 30 Hz loop, audio scheduling, paths, settings, saves folders, autosave, bug reports. |
| `BioForgeApp` | The macOS app (AppKit and Metal). |
| `BioForgeSDL` | An SDL3 app for Windows and Linux, built from `BioForgeSDLShell` and `CSDL3`. |

The original game files under `game/` are read-only. They are not part of the port's distributable source.

### Project status

The Mac app plays the whole game from the intro to the ending. Medium and Hard are audited against the original, but nobody
has played them through.

On Windows and Linux the engine and host layer build, and the SDL3 app runs the game. Linux AppImages (x86_64, arm64) build
and pass headless smoke runs in containers. Nobody has run anything by hand on Windows or on a Steam Deck yet; see the
"Windows and Linux" section of `ROADMAP.md`.

Version 0.1.0 is out as a preview (2026-11-21): the notarized Mac app and the Linux AppImages, on the public repository's
Releases. The Windows zip waits on a run on a real PC, and the beta proper on a full playthrough by the author.

## The Python reference port

Run the existing prototype from the repository root with its Python environment:

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

Notes on some of these tools:

- `movie.py --audio` renders the music device from `INSTALL.OPT` too; `--music-device adlib|gm` overrides it.
- `re/formats/flc.py` decodes all six SHOW files, including DEMO1, which has no recovered script trigger.
- `play.py` is the live preview, described below.
- `parity.py` compares the prototype with the original; see
  [Comparing with the original in DOSBox-X](#comparing-with-the-original-in-dosbox-x).
- The playthrough scripts are described under [Playthrough checks](#playthrough-checks).

### The live preview

The live preview (`play.py`) requires Homebrew `sdl2`. By default it skips the opening sequence, selects Medium difficulty
and chooses a camera facing Lex.

- `play.py --skip 0` shows the opening difficulty dialog. Choose a difficulty to let the startup script continue.
- `play.py --editor-cursor` also draws the `MOUSE.SHP` arrow at the mouse, as `BIOFORGE.EXE -e` does.

| Key | Action |
| --- | --- |
| Up, Home, Page Up | Walk (Shift to run). |
| Left, right | Turn. The turning motions rotate Lex as in the original; while walking or running they steer him. |
| Down | Backstep. |
| End, Page Down | Sidestep. |
| Space | Use a nearby object. |
| C | Toggle combat. |
| Keypad 5 | Shoot. With the CHAOS blaster in the right hand it fires laser bolts that fly, hit and explode by script, as in the original. |
| Keypad directions | Move in combat. Alt/Option adds hand attacks, Ctrl adds foot attacks. |
| I, P, D, J | Open the PIMM inventory, main, diagnostics and journal screens. I and P first stow a left-hand item. |
| Escape | Close options or a monitor, or quit the preview. |

In the zero-g room, keypad 5 fires a right-hand gun, whose recoil moves Lex, and keypad 4/6 turn him.

To use a monitor button, move the mouse over it and left-click. The hand pointer follows the mouse and plays the original's
press animation: the button acts when the hand reaches its last frame, and the release follows when the mouse is up. As in
the original, the hand stays put while the button is held, and on the release the mouse moves back onto the hand.

Tab, the arrow keys and L glide the hand to a button, and Return or Space press it. Right-click acts as Escape, as in the
original. Letters press nothing, because the game gives no button a shortcut letter. Monitor text can show live script
variables.

Journal entries appear when scripts award them, with their award time shown as `day-HHMM`. Monitor camera windows stretch the
full camera image into the authored viewport and use the monitor's grey ramp, which matches a native screenshot closely.
Nobody has recovered the original's exact sampling and colour formula from the executable yet.

The original options artwork appears for script options calls, including the opening difficulty choice; the opening script
waits for the dialog through `ISMONITORRUNNING`. Audio, credits and nine-slot save/load selector screens are available. The
audio and gamma panels and the gamma keys work as in the original, reading `INSTALL.OPT`.

The preview can load native saves and write archives the DOS game accepts. Its own saves also write its running scripts, in
a form only the port resumes.

Lex starts with a battery in inventory but no weapon in hand. Walk through the open cell door to evade the nurse. If it
catches Lex twice, the script plays the knockout and revival.

This is a research preview: input timing remains approximate.

### Engine behaviour

Melee hits follow the original. The engine tests the striking limb against the target's `BODY/*.COL` cubes on frames 4 to
n−5, with hit zones, blocking from the frame guard bytes, armour, difficulty and the scripts' hit labels. The `DAMAGE`
statement, energy damage, hit and block sounds, `_WOUNDS`/`_DEATH` blocks and the player's combat auto-turn follow the
original too.

Manual, scripted `GO` and AI root movement test each figure's recovered hull against `PHYS` boxes in its current area when its
collision flag is on. They use the original's fixed-point signed overlap score: closed or neutral doorways block, open ones
pass. A blocked figure slides along the wall or stays put, as in the original.

Living figures push each other apart (each keeps its `PERSONAL_RADIUS`); the nurse's push nudges Lex toward the cell door.
Scripted avoidance points (`ADDAVOIDANCEPOINT`) keep a living figure out of a circle around a waypoint, even with its
collision flag off.

IMAG trigger volumes fire as in the original. Their scripts run when a figure enters them, camera triggers switch the view,
and the cell's live bars shock Lex if he walks out of the cell.

Motions play at the original's per-figure speed: `MY_SPEED` times each motion's frame time. Figures other than Lex animate
faster on harder difficulty levels, and Lex's repeated attacks slow down. So the opening runs on the original's timeline, and
turning motions such as the nurse's ATK_M7 rotate the figure as they loop. Rendered poses interpolate between interior motion
frames; a loop's final frame holds until the next cycle starts.

Figures with gravity stand on the floor under the original's hull (Lex at exactly the original's height). They fall off
ledges at the original's rate, select the original's soft landing on normal floor contact, and teeter (the whoah motions) at
drops. Level figures keep the gravity setting saved in the level data.

### Lighting

Untextured (flat and Gouraud) faces now follow the original lighting. The game's single light has zero strength and zero
ambient, so each such face takes the darkest colour of its palette ramp; the original's own framebuffer confirms this.

Textured faces use their source palette indices directly, as the original rasterizer does; each room's palette supplies their
colors. Textured index 255 is transparent. The original applies no depth haze (`PALFADE.IFF` is loaded but unused), so
neither does the port.

## Playthrough checks

### Scenarios

The scenario command (`scenarios.py`) replays these scenes in the Python prototype:

- the opening escape and nurse revival;
- the LANDPAD airlock;
- the nurse's front/rear punches, scripted defeat and corridor escape;
- Lex's key-driven fights with Caynan (after the nurse, through the flickering cell-1 bars) and Guard 1 (staged return from
  the tanks);
- a BEACH ↔ TUNROOM round trip.

The Swift port mirrors the engine pieces these scenarios need; the scenarios themselves exist only in Python.

The nurse test uses logged pose/contact fixtures and normal combat input. It covers bouncy wall rebound and figure retirement.
Persistent velocity, the generic 3D rebound, SETVELOCITY and LEAP are in the Python prototype and the Swift port; explosion
debris remains unimplemented.

A post-wound route now uses movement keys to reach the live bars and then the corridor at full health in both Python and
Swift. Only the front/rear attack poses are staged. Exact free-running trajectory parity with the original remains open.

The scenario run writes JSON checkpoints and selected PNG frames. The test suite also checks that all 10 level datasets load
and render. These checks cover representative paths; they do not cover every gameplay action.

### Prison

The prison playthrough harness drives a new game through CHAOS with real keys and monitor clicks:

1. the fork;
2. the circuit board;
3. the cell-block door;
4. Dane's code;
5. Caynan's arm;
6. driving the USE_BOT robot from its monitor to hold the arm at the reader;
7. the security terminal;
8. the guard-room door;
9. the cryo iris;
10. the ladder down into TANKS;
11. the catwalk and the mantle up to cell 2.

Where the ports cannot play a step yet, it takes a logged staged shortcut. Its report lists each segment, the problems found
and the shortcuts. [re/playthrough/prison.md](re/playthrough/prison.md) has the path, blockers and shortcuts.

### Surface

`playthrough_surface.py` drives the surface levels, from LANDPAD's elevator arrival to the exit toward PLATFORM, with the
shipped scripts and real keys. It records each staged shortcut and problem and writes `report.json`. The route, how far it
gets and the remaining blockers are in `re/playthrough/surface.md`.

### Base and ending

The base and ending playthrough harness (`playthrough_base.py`, notes in `re/playthrough/base.md`) drives CONTROL, TOWER,
PLATFORM and the ending through the real scripts, from elevator arrivals to ENDGAME's `EXIT`. Its JSON report lists its staged
shortcuts and the problems found.

### Full game

`playthrough_full.py` plays the whole game in one run (about 2 minutes): a new game, CHAOS and TANKS, the tower, CONTROL with
the reactor shutdown, LANDPAD, BEACH, DIGSITE, TUNROOM, the alien city, the gravity ring and back to CONTROL's bike and the
ending. It runs in a single World / VM, so inventory, globals, HP and level state carry from level to level.

Script processes linked to cameras (`LINKMETOCAMERAS`) pause and resume on camera switches in both ports, as the original
does.

The run reaches `EXIT`. [re/playthrough/full.md](re/playthrough/full.md) lists the shortcuts it still takes (fights its
one-key punch loop does not win, a few walks and engine gaps) and the blockers, ranked.

`--difficulty medium` or `hard` plays the route at that level after the prison. Medium finishes on 1 of 27 RANDOM streams,
Hard on none. `run_seeds.py` takes the same flag.

## Comparing with the original in DOSBox-X

### Parity runs

The parity command (`re/tools/parity.py`) boots the original in a DOSBox-X scratch copy and runs the same clock-scheduled
scenario in the Python prototype. It requires Homebrew `dosbox-x` and the original `game/app/` data.

It writes `original.jsonl`, `port.jsonl`, `report.md`, `report.json` and `positions.png` under
`re/out/parity/<scenario>/`. It exits nonzero when a sampled field exceeds its tolerance.

- `report <scenario>` rebuilds a report from existing traces without launching DOSBox-X.
- `port <scenario>` reruns only the Python side.
- The available scenarios are `opening_wake`, `nurse_activation`, `closed_door_walk` and `open_door_zap`.

DOSBox-X runs without effects sound. Set `BIOFORGE_DOSBOX_MUTE=1` to silence its music as well.

The scenario JSON files are in `re/tools/parity_scenarios/`. They use `boot: "new_game"`. To start from a native DOS save
instead, use `boot: {"save": "/path/to/GAME1.IM1", "slot": 1, "keys": "..."}`. The `keys` sequence must navigate the
original's load dialog and choose that slot.

### The live controller

For repeated original-game checks, `dosbox_live.py WORKDIR --control DIR --app-bundle` keeps one DOSBox-X session open and
pauses it at `--start`. An agent can then inspect figures, hold keys, advance short intervals and capture controlled falls
through JSON requests, without asking a person to drive Lex.

- `--background` detaches the controller from its launching terminal. Its PID and log path go into
  `WORKDIR/controller.json`. Wait for the paused-ready message in `controller.log` before sending commands.
- `--attach --control DIR` reconnects a replacement controller to a running DOSBox-X without booting it.
- `--load-save GAME1.IM1` copies a native save to the scratch game directory for explicit load-dialog experiments.

Probe the existing control session before launching another process. Reuse its paused state between trials; emulator restore
and repeated native reloads proved unreliable on this setup. See the persistent testing workflow in
[re/NOTES.md](re/NOTES.md).

Clients write requests atomically as `DIR/in/NAME.json`; replies appear at `DIR/out/NAME.json`. The commands are `sample`,
`frames`, `key`, `set_z`, `set_xy`, `set_heading`, `phys_top`, `variables`, `processes`, `force_camera`, `set_variable`,
`mouse`, `run_for`, `pause`, `run` and `quit`.

| Command | Notes |
| --- | --- |
| `frames` | Stops at the requested figure's update entry, so samples follow completed updates. |
| `key` | Accepts modifier scan codes for punches and kicks. |
| `variables` | Reads named script globals for checks such as the live bars' off window. |
| `processes` | Lists the script processes with their paused flag and camera links. |
| `force_camera` | Stages a camera switch. |
| `set_variable`, `mouse` | For staging: they write a script global and the pointer state. `fight_sample.py` uses them to run one fight in the original and in the port with the same keys. |
| `quit` | For a controller that launched its emulator, requires `"stop_emulator": true`. An attach controller's `quit` disconnects and leaves the game paused. |

Position and clearance changes are explicit test setup. The client sends commands and runs a fall check that writes a trace
and a pass/fail report; it never restarts the game.

The controller claims a request before executing it. A client timeout cancels a queued request; an already running request
can finish and leave its reply for inspection. Timeouts allow for the requested run duration and sampling overhead.

Limits:

- Individual key holds and timed runs: at most 120 seconds.
- Frame batches: at most 100 updates.
- Timed sampling intervals: at least 0.01 seconds.

### Combat and nurse checks

`dosbox_control.py` runs these checks against the live controller:

- `dosbox_control.py combat DIR --target FIRSTBOT --out OUT` enters combat and attacks the nurse, recording motions, new hit
  reactions and health changes. An attack animation alone does not pass the test.
- `dosbox_control.py nurse DIR --out OUT` stages front and rear attack positions and records the nurse's scripted
  wound/bounce response using real combat keys. Running `nurse` again on a wounded nurse stages direct bar contact instead,
  as a separate fixture.
- `dosbox_control.py push DIR --out OUT`, on a wounded nurse, steers toward the bars using keys and state feedback, then
  observes defeat. It makes no pose edits and needs an existing wounded encounter.
- `dosbox_control.py escape DIR --out OUT` uses key input and live bar-state feedback to attempt the corridor crossing after
  nurse removal. It stops on the first health loss and records a failure; it never retries a lethal route.

A recorded input run from staged starting positions reached the original zap and defeat at full Lex health. The packaged push
CLI has protocol tests, but nobody has rerun that wrapper on a fresh nurse. The original crossing passed at full health in
`re/out/nurse_validation/corridor/`.

The client logs each setup change, preserves the one-way encounter and never reboots it.

## The native Swift port

The native port needs Xcode 27. It reads your own game folder; no game data is bundled.

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

`native_fixtures.py` regenerates the oracle fixtures from the Python prototype. Among them it records every declared movie
frame's indexed-pixel and palette hashes for the Swift decoder tests.

### Test switches

| Switch | Effect |
| --- | --- |
| `FULL_RUN_PERF=1 ... --filter frameTimes` | Times every tick of the whole recorded game, with the frame the app draws, against the 33.3 ms of a 30 Hz tick. |
| `MONKEY=1 ... --filter MonkeyTests` | The soft-lock check, described below. |
| `MONKEY_TRIALS` | Trials per save point; default 40. |
| `MONKEY_LEG`, `MONKEY_TRIAL` | Pick one trial. |
| `MONKEY_LOG=1` | Prints that trial's keys. |
| `MONKEY_TRACE=a-b` | Prints the player every tick of that range. |
| `MONKEY_PROCS=1` | Prints the script processes in the outcome. |
| `SAVE_FUZZ=n ... --filter SaveFuzzTests` | Loads n corrupted copies of a save (flipped bytes, cut files) and checks that each fails with an error or loads and runs, and never crashes. A normal run uses 40 cases. |
| `REPLAY=<unzipped report folder>` with `--filter ReplayTests` | Replays a bug report's recording; see [Bug reports](#bug-reports-and-crash-reports). |

The monkey test runs at each of the full run's 30 save points. It mashes random keys and clicks (routed as the app routes
them), then checks that Lex can move again, and after a death that the reload dialog stays up until a load. It takes about
1.5 min in release and writes its results to `re/out/monkey/`.

## The Mac app

The Mac app has:

- the original's keys (remappable) and game controller support;
- sound effects, and General MIDI or the original AdLib music;
- subtitles, the PIMM screens and monitors;
- the original options dialog with nine save slots in the DOS game's own `GAMEn.IM1` format, plus per-level autosaves;
- Game > Language (English, German, French);
- optional Readable Text, and High-Resolution Art at 2x or 4x (built on the Mac from your own game files);
- Help > Report a Bug.

### Building

`native/build-app.sh` builds `native/build/BioForge.app`, a double-clickable release build. It is ad-hoc signed, so on another
Mac it opens with right-click > Open. The script also keeps `native/build/BioForge.app.dSYM` for symbolicating crash reports.

The app icon is the GOG release's robotic hand. `native/Resources/gog_icon.py` makes it from `goggame-*.ico` in your game
folder when `build-app.sh` runs, so GOG's artwork stays out of the repository. Without that file the icon is
`native/Resources/AppIcon.png`, original artwork drawn by `make_icon.py`.

### Game folder

On first launch the app asks for your BioForge folder and remembers it. If you choose a folder above it, such as a GOG
installation's top folder, the app finds the game folder inside. If the folder later goes missing, or its data can't be read,
the window says so and offers the folder picker again. File > Open Game Folder… (⌘O) changes the folder.

Each time a folder opens, the app checks the size and MD5 of the first 5000 bytes of every game file it needs (BIOFORGE.EXE
and the data folders). The table is `KnownData.swift`, made from the GOG release 2.1.0.14, English, the only release known.

- If files are missing, the game won't start, and the app names them.
- If files differ, the game starts anyway, and the app says so once, naming the first few.
- The log and Report a Bug list them.

The game pauses while the app is in the background or minimized.

### Controls

BioForge > Settings… (⌘,) remaps the controls; the game pauses while it is open. Each control has a key and an alternate,
saved by the app. Bindings are stored as USB HID key usages (what SDL uses). The app converts bindings that earlier builds
saved as Mac key codes, once.

Help > BioForge Help (⌘?) explains setup, saving and the controls with your current keys. Help > Keyboard Controls… opens the
key settings.

Controls follow the original's keys. The defaults need no numpad:

| Key | Action |
| --- | --- |
| Arrows | Walk and turn (Fn+arrows = Home/End/PgUp/PgDn). |
| Shift | Run. |
| C | Toggle combat. |
| Space | Use. Space uses a held item, including scripted combinations with nearby objects, such as using the fork on the cell panel. |
| Enter | Pick up the item in front of Lex or put down what he holds, as in the original. |
| The eight direction keys, in combat | Attack. |
| Holding A, in combat | Kicks. A stands in for the original's Ctrl, since Control+arrows are Mission Control shortcuts. |
| Holding Option (Alt), in combat | Punches. |
| `/` (keypad 5) | Shoot. |
| P | Open the personal monitor, after Lex wakes. |
| I, D, J | Open the monitor's inventory, diagnostics and journal pages. |
| O, S, L, R | The original's option keys: options, save, load, the credits. |
| Option+X | Ask to exit. |
| Escape | Open the options dialog (a port addition, see below). |
| Option+V | Show the game's build caption, as in the original, once the one currently showing ends. |
| Shift or Option with `,`/`.` (or keypad −/+) | Step gamma. |

The numpad and Control keys stay bound as alternates. Items on the floor and in Lex's hands are drawn.

### Display

The picture fills the window at any size, keeping its shape, with crisp pixel edges.

- View > Correct Aspect Ratio toggles 4:3.
- View > High-Resolution Art: see [High-resolution art](#high-resolution-art).
- View > Readable Text: see [Readable Text](#readable-text).

### Language

Game > Language switches speech and text between English, Deutsch and Français, as the original's installer did with
`language=` in `INSTALL.OPT`. That setting picks the first choice; GOG's is English.

The voices (`SOUND/<E|G|F>SAMPLES.FLX`), subtitles and captions, monitors and the options dialog change at once. An open
options dialog changes on its next opening, and the intro movie on the next new game.

### Intro, movies and the ending

New Game plays the original INTRO show (INTROF/INTROG for the corresponding language), with its script-timed effects and
music, before the difficulty dialog. Escape skips the show.

Script fades, palette flashes (`CHANGEPALETTE`), the opening quake's screen shake (`RUMBLE`) and captions follow the original's
timing. Escape also skips the opening quake, as in the original.

The ENDGAME and PLT0 shows play when their game scripts reach them. Escape skips PLT0. At the end the credits roll over the
end movie's last picture, as in the original, and the game quits five seconds after they stop. Escape or Alt+X ends it
sooner.

### The PIMM and monitors

After Lex wakes, P opens the personal monitor, and I, D and J open its inventory, diagnostics and journal pages. Move the
pointer with the mouse or trackpad. Click Exit or press Escape to leave the page.

In Inventory, use the up/down buttons to select an item, then click READY (or the item artwork) to put it in its declared free
hand and close the page. If the hand is occupied, the item stays in inventory. I or P first stows an item in Lex's left hand;
press again to open the page.

Enter puts down a held item. The original inventory screen has no separate Use, Combine or Drop button.

Diagnostics shows the script's health, energy and PFD controls. Journal entries appear as the game awards them, with their
recorded times. In-world monitor camera windows show the selected room view, including feeds from another level.

### The options dialog

A new game starts with the original difficulty dialog. Click Easy, Medium or Hard; as in all the dialog's screens, the bar
under the pointer lights up. The dialog sits on the greyed title picture, and after the choice that picture stays up for two
seconds while the first level loads.

During play, Escape opens the options dialog over the dimmed scene, which pauses the game. The original does nothing with
Escape there; the port adds it. O works as in the original. Like O, Escape does nothing while a script has Lex's AI off, such
as the wake-up.

In the options dialog, Escape cancels or returns. Cancel on the load or save slots goes back to the main panel. The credits
(R, or Credits in the dialog) scroll by themselves over the running game, as in the original, which does not pause for them.
Exit, then Yes, quits the app.

When Lex dies, the options dialog opens over the greyed title picture with see-through buttons, as in the original, and asks
you to load a game. Return is disabled there. Until a game is loaded, every other way out of its screens leads back to the
exit prompt or the main panel, as in the original (Load, then New, then Yes starts a new game).

A load that fails brings the dialog back. A save or load that fails shows an alert with the reason.

### Saves and autosaves

Saves go to `~/Library/Application Support/BioForge/Saves/GAME1.IM1`…`GAME9.IM1`, the original file names, so you can copy
saves between the DOS game and the app. Saves use the original's format both ways: the port loads the original's `GAMEn.IM1`
saves, and the original loads the port's.

- Loading a DOS save resumes its figures, carried items and running scripts.
- Saves written by the app keep level, camera, variables, journal logs, figures, items and the app's running scripts, so a
  game saved in the app goes on where it was. The DOS game would not resume those scripts.
- As in the DOS game, a load starts every running animation again from its first frame, and the inventory keeps its order.
- Each level keeps the items left there when Lex leaves it, as in the DOS game, and saves write them into that level's file.
- An open monitor is not kept.

While saving is unsafe, S shows "PIMM: Save temporarily disabled" instead, and the options screen greys out Save. Saving is
unsafe while a script holds the keyboard, as in the opening, or while an invulnerable figure or a grenade is around.

The app also autosaves whenever the level changes and saving would be allowed, retrying later in the level if not. Autosaves
go into `~/Library/Application Support/BioForge/Autosaves` as `<date time> <LEVEL>.IM1`, and the app keeps the newest five.
File > Open Autosave… continues from one.

### Bug reports and crash reports

Help > Report a Bug… pauses the game, writes a zip to `~/Library/Logs/BioForge/Reports` and shows it in the Finder. Nothing is
sent anywhere. The zip holds:

- where you are;
- the log;
- a save of that moment;
- a recording of your inputs for this game and the one before it (`Session` and `Session.previous`, kept in
  `~/Library/Logs/BioForge`);
- the newest BioForge crash report of the last week, from `~/Library/Logs/DiagnosticReports`.

The report and About name the build: version, build number and git commit, with `-dirty` when built from uncommitted changes.

If the log of the last session lacks its final "quit" line, the next launch offers to make a report, and keeps the crashed
game as `Session.crashed`. To try it, `BIOFORGE_CRASH_AFTER=<seconds>` crashes the app that long into a game.

The recording replays the minutes before the report exactly, headless. `REPLAY=<unzipped report folder> swift test --filter
ReplayTests` (with `BIOFORGE_DATA` set) replays it and checks the state recorded at report time.

### Debug menu

- Debug > Camera Viewer browses room cameras.
- Debug > Show Editor Mouse Cursor draws the game's own arrow (`MOUSE.SHP`) at the pointer. The original shows it only when
  started as `BIOFORGE.EXE -e`; normal play never draws it.
- Debug > Save Frame as PNG… saves the picture as shown (art scale and aspect, no window) at 1280 pixels wide.
- Debug > God Mode (Lex takes no damage), Refill Health and Open Save File… are tester aids for getting past a blocker. Open
  Save File… takes any `.IM1`, such as the ones `re/tools/save_resume_check.py --export DIR` writes.

Each use of a tester aid is logged in the play log and recorded in the session recording (`World.setGodMode`,
`refillHealth`), so a replay does the same. God Mode is also shown in report.txt. God Mode is off in every new game or load.

### Environment variables

| Variable | Effect |
| --- | --- |
| `BIOFORGE_DATA` | Overrides the remembered game folder (development and tests). |
| `BIOFORGE_LOAD=/path/to/GAMEn.IM1` | Boots a save directly. Also takes a GAMEDAT folder. |
| `BIOFORGE_CAMERA=CE33` | Opens Debug > Camera Viewer directly. |
| `BIOFORGE_TICK_TITLE=1` | Shows the tick in the title. |
| `BIOFORGE_CRASH_AFTER=<seconds>` | Crashes the app that long into a game. |
| `BIOFORGE_SHOT=<file.png>` | With `BIOFORGE_LOAD=<save>` (and `BIOFORGE_SHOT_AFTER`, `BIOFORGE_SHOT_KEYS`), saves a frame as Debug > Save Frame as PNG… does, unattended. The screenshots for the website are made this way. |
| `BIOFORGE_HD_PACK` | Points the app at another art pack folder. |
| `BIOFORGE_HD_MODEL=/path/HDCube.mlmodelc` | Gives `swift run` an art model. |

### Building a release: signing and notarizing

To make a build to hand out:

1. Store the notarytool credentials once with `xcrun notarytool store-credentials <profile>`.
2. Run `native/build-app.sh --sign "Developer ID Application: <name> (<team>)"`. It builds a universal app (Apple silicon and
   Intel, macOS 14 or later), signed with the hardened runtime and a secure timestamp. The app gets the original-artwork icon
   (never the GOG icon) and the art model, from `BIOFORGE_ML_PYTHON` or the converted copy in `native/build/cache`.
3. Run `native/notarize.sh` with `NOTARY_PROFILE=<profile>`. It notarizes the app, staples the ticket and writes
   `native/dist/BioForge-<version>-mac.zip`. The version comes from `native/VERSION`.

## Windows and Linux

`native/build-app.sh` packages the Mac app. The SDL3 app ships as a Linux AppImage from `native/package-linux.sh` and as a
Windows zip from `native/package-windows.ps1`.

The engine (`BioForgeCore`), the shared host layer the app runs on (`BioForgeHost`) and their tests also build on Linux and
Windows. That was phases 1 and 2 of "Windows and Linux" in `ROADMAP.md`.

### The SDL3 app

Phase 3 adds `BioForgeSDL`, an SDL3 app for Windows and Linux. It is checked on Linux, not yet on Windows. `PLAYER_GUIDE.md`
has a section on it.

It opens a window, finds or asks for the game folder and runs the game with:

- the keyboard, with the player's bindings, and F11 or Alt+Enter for full screen;
- the mouse;
- a game controller (`SDL_Gamepad`: Xbox, PlayStation, Steam Deck), with the same buttons as on the Mac;
- sound effects and the AdLib music, through SDL's audio streams;
- General MIDI through TinySoundFont (MIT, vendored in `native/Sources/CTinySoundFont`) when the player has a SoundFont.

The app looks for a SoundFont in these places. None is bundled.

- the first `.sf2` in the data folder (`~/.local/share/BioForge`, `%APPDATA%\BioForge`);
- a `"SoundFont"` path in the settings file;
- one next to the program or the AppImage;
- on Linux, a system one such as `/usr/share/sounds/sf2/FluidR3_GM.sf2`.

Without a SoundFont, a General MIDI setting plays as AdLib, and the log and the settings screen say so.

F1, or a controller's Back / View button in the game's options dialog, opens the app's settings screen. It covers full
screen, aspect ratio, music (General MIDI, AdLib or off), mute, language, Readable Text, and the keyboard and controller
bindings, all kept in the settings file.

The SDL shell keeps its files in the XDG folders (`~/.local/share/BioForge`, `~/.local/state/BioForge`,
`~/.config/BioForge/settings.json`), and on Windows in `%APPDATA%\BioForge`.

The app needs SDL 3.4 or later (`libsdl3-dev` on Debian and Ubuntu; on Windows see `native/WINDOWS_CHECK.md`). On the Mac it
is built only with `BIOFORGE_SDL=1` (Homebrew `sdl3`), for development.

### Linux in a container on the Mac

On a Mac, Linux runs in Apple's `container` tool (`brew install container`, then `container system start`):

```bash
container run --rm --cpus 10 --memory 16g -v "$PWD/native:/src:ro" -v /path/to/install:/app:ro -w /src docker.io/library/swift:6.4 \
  bash -c 'apt-get update -qq && apt-get install -y -qq libsdl3-dev && BIOFORGE_DATA=/app/Bioforge swift test --scratch-path /build'
```

- Mount the folder that holds `Bioforge`, one level up from `Bioforge` itself. The GOG install keeps `GAMEDAT` (the save
  tests' starting state) next to it.
- Add `--arch amd64 --rosetta` for x86_64 (the Steam Deck's).
- For Windows, see `native/WINDOWS_CHECK.md`.

`BIOFORGE_SDL_SMOKE=900 /build/debug/BioForgeSDL` (with `SDL_VIDEO_DRIVER=offscreen SDL_AUDIO_DRIVER=dummy` and
`BIOFORGE_DATA`) runs 900 ticks headless and prints where the game is. `BIOFORGE_SDL_SHOT=file.bmp` also saves the picture.

### Linux package (AppImage)

Phase 4 is the Linux package. `native/package-linux.sh` builds `native/dist/BioForge-<commit>-x86_64.AppImage` (the Steam
Deck's) and `-aarch64.AppImage` in `container`. It then starts each in a clean container (Arch Linux, Debian) for the smoke
run above, which must print the same line.

```bash
native/package-linux.sh                       # both architectures, smoke run with game/app
native/package-linux.sh --arch amd64 --data /path/to/install
```

The build runs `native/package/linux/build.sh` in `swift:6.4-jammy` (glibc 2.35, so the AppImage runs on systems older than
the build host, SteamOS included). It uses:

- SDL 3.4 from its release tarball, with X11, Wayland, PipeWire, PulseAudio and ALSA loaded at run time;
- the Swift runtime, linked in statically;
- the pinned AppImage type2 runtime.

The build checks the SDL and runtime downloads against SHA-256 and keeps them in `native/dist/cache`.

The result needs glibc 2.35 and a libstdc++ from GCC 12 or later (Ubuntu 22.04, Debian 12, current SteamOS). The build fails
if the program or SDL links any library other than those and the bundled `libSDL3.so.0`. Each AppImage is about 23 MB.

The container has no FUSE, so the smoke run uses `APPIMAGE_EXTRACT_AND_RUN=1`. For x86_64 it runs a copy with the AppImage's
`AI\2` mark in the ELF header cleared, because Rosetta refuses to run it otherwise; real x86_64 machines ignore the mark. The
normal FUSE start is checked on a real Linux system.

The package holds:

- the program and `libSDL3.so.0`;
- the desktop file and the original-artwork icon;
- `native/package/README.txt`, `NOTICES.txt` and `licenses/` (SDL's zlib, HIDAPI and yuv2rgb notices, Swift's Apache 2.0 with
  the runtime exception, ICU's Unicode licence).

It holds no game data and no art model. `native/dist` is ignored by git, and nothing is uploaded.

### Windows package

`native/package-windows.ps1` has not run yet: it waits for the Windows PC. Run it on a Windows PC in the Visual Studio
developer PowerShell (`native/WINDOWS_CHECK.md`, "Packaging"). The script:

1. builds a release `BioForgeSDL.exe` for the Windows subsystem (no console window), with an icon and version resource
   (`native/package/windows/BioForge.rc`, and `AppIcon.ico` made from `AppIcon.png`);
2. collects the DLLs it needs by walking `dumpbin /dependents`: `SDL3.dll`, the Swift runtime and Foundation DLLs, and the
   Visual C++ runtime, app-local from the Build Tools' redist folder (Windows' own DLLs stay out);
3. adds the same `README.txt`, `NOTICES.txt` and `licenses/`;
4. writes `native\dist\BioForge-<commit>-windows-x64.zip`;
5. unzips it into a fresh folder and runs the smoke test there, with `PATH` cut down to Windows' own folders and a throwaway
   `%APPDATA%`.

The exe is not signed, so SmartScreen warns on first start ("More info", "Run anyway"). Signing needs a code-signing
certificate and is not done.

## Sound and music

On the Mac, Game > Music Device switches between General MIDI (Apple's synth) and AdLib. AdLib is the game's own AdLib
arrangement, played through a port of its AdLib driver and an OPL2 FM model. Game > Mute (⌥⌘M) silences effects and music.

The first choice follows `MusicCardId` in `INSTALL.OPT`: 1 to 3 = AdLib/Sound Blaster, GOG's 7 = General MIDI. `MUSIC=OFF`
there means no music.

Sound, music, gamma and subtitle settings start from your game folder's `INSTALL.OPT`. GOG ships Gamma=50, which brightens
every colour slightly. The app keeps your changes and never writes them to the game folder.

The SDL3 app's music, SoundFonts included, is covered under [The SDL3 app](#the-sdl3-app).

## High-resolution art

View > High-Resolution Art (Off by default, or 2x or 4x) draws the picture at 640x400 or 1280x800, still in the game's own 256
colours. It uses room art and textures the app builds on your Mac from your own game files. The art pack is never shipped or
committed.

### How the art is made

A program makes the art; nobody draws it by hand. An AI upscale serves only as a guide. Every new pixel takes a colour already
next to it in the original, and at least half of each pixel's new pixels (2 of 4 at 2x, 8 of 16 at 4x) keep the original's
colour. So the art stays pixel art in the game's palette.

The buttons, arrows, digits and gauges on menus and monitors don't come from the pack. Like the text, they are drawn with plain
pixel doubling (2x) or quadrupling (4x), since the upscale smeared their hard edges. The pictures behind them and the hand
pointer use the built art.

Outlines, where art meets what's behind it, are smoothed with Scale2x: once at 2x and twice at 4x. Edge pixels that become
solid take the nearest colour of the same piece.

### Building a pack

The first game you start offers to build a 2x or 4x pack once. Picking 2x or 4x the first time also offers to build that
pack.

While the pack builds, a progress sheet holds the game. Play Now closes the sheet, and the build carries on in the background
while you play. Rooms switch over as they finish: textures first, then the current level.

- View > High-Resolution Art > Show Build Progress brings the sheet back.
- Stop Building pauses the build. Picking the scale again resumes it.
- The session log notes when a build starts, stops, finishes or fails.

On an Apple M4 Pro:

- the 2x pack (7740 frames) takes about 11 minutes and 115 MB on disk;
- the 4x pack takes about 12 minutes and 300 MB;
- the first build adds about 2 minutes while macOS prepares the model for the Neural Engine (the sheet says so under its
  bar);
- the build stays under about 300 MB of memory.

Each call frees its memory at once. If BioForge still passes 3 GB of memory, the build stops with a message; picking the
scale again resumes it. Two early builds grew to 19 and 35 GB and froze the Mac.

Packs live in `~/Library/Application Support/BioForge/HD/2x` and `/4x`. `BIOFORGE_HD_PACK` points the app elsewhere. A pack
from before there were two scales is moved into `2x`.

A pack made by an older version (frames in the 'BFX2' format, without smoothed outlines) is rebuilt frame by frame, and the
app offers a finished one as "Update the 4x art?". Packs built before monitors were added offer Build again, which adds only
the monitor art.

### What the pack covers

- Rooms without art yet are shown plain enlarged, with the 3D figures drawn at the full resolution.
- Monitors, the PIMM and the options dialog get their art from the pack too (`monitors/`).
- The dimmed scene behind the options dialog is the 2x/4x one.
- Text, captions and subtitles are drawn at the full resolution in the game's own fonts, each font pixel enlarged.
- Live camera feeds in monitors are enlarged, as the original shows them at low resolution.
- Movies are shown enlarged, with their subtitles at the full resolution.
- Fades, palette changes and screen shake work as in the original.
- A window with fewer than 4 screen pixels per original pixel shows the 2x art instead of the 4x.

### The model

The guide is the model [4x_HDCube_200k](https://github.com/Venomalia/HDcube/tree/main/v1) by Venomalia. The app runs it with
Core ML on the Neural Engine, which leaves the CPU and GPU to the game.

The model is converted with 70 fixed input sizes, which is what lets it run there. Each crop is grown with real screen pixels,
or its edge repeated, to a multiple of 32, at most 320x200. A range-shaped model fell back to slower paths.

On a 555-frame sample the Neural Engine was 2.9x faster than the CPU. It changed 2.7% of palette indices against a CPU build,
as much as the GPU does (2.6%). The GPU starved the game and the window server; a build during play once made macOS restart
the GPU.

The model's licence (changed on 2026-10-19; it was CC0 before) allows redistributing the original file only, unmodified, and
claims nothing on the images it makes. **The author, Venomalia, gave permission on 2026-11-21 to ship the converted model in
BioForge**, so signed builds include it, with its licence file.

`native/build-app.sh` downloads the model at a pinned commit and checks its SHA-256. It converts it with
`re/tools/convert_model.py` (cached in `native/build/cache/model2`) and puts the converted model and the licence in the app.

This needs `BIOFORGE_ML_PYTHON`, a Python 3.12 with `torch`, `spandrel` and `coremltools`. Without it, the app is built
without the model and can't build art. `BIOFORGE_HD_MODEL=/path/HDCube.mlmodelc` gives `swift run` a model.

```bash
BIOFORGE_ML_PYTHON=<venv>/bin/python native/build-app.sh
<venv>/bin/python -I re/tools/pixel_pack.py --model 4x_HDCube_200k.pth --scale 4 --level CHAOS
```

### Reference implementation and hand fixes

`re/tools/pixel_pack.py` is the reference implementation (torch). The app's Swift port, `PixelPack.swift`, matches its filter
exactly. Its output differs in about 0.5% of pixels, because Core ML and torch round differently.

`pixel_pack.py` is also the route for hand fixes. `--export DIR` also writes each frame as an indexed PNG. Edit one and pass
its folder as `--overrides DIR` to replace that frame.

### Benchmarking

`PACK_BENCH=1 BIOFORGE_HD_MODEL=… BIOFORGE_DATA=… swift test -c release --filter PackBenchTests` builds a 555-frame sample per
variant. It writes time, memory, input sizes and palette-index changes against the CPU build to
`re/out/pack_bench/<scale>x/summary.md`, with side-by-side PNGs.

| Variable | Effect |
| --- | --- |
| `PACK_BENCH_VARIANTS` | Picks the variants, e.g. `cpu,gpu,ane,pad16`. |
| `PACK_BENCH_MODEL2` and `alt-…` | For a second model. |
| `PACK_BENCH_CLEAN=1` | Starts over. |

## Readable Text

View > Readable Text (off by default) makes the game's text easier to read.

- On monitors, the PIMM and the options dialog it adds one pixel between letters, a dark drop shadow and a brighter colour from
  the game's own palette, in the same hue.
- A label that would no longer fit keeps the original spacing. A list whose text fitted keeps the original line breaks if the
  spaced text would not.
- Subtitles and captions already have spacing and a shadow. They get a darker box and the same brighter colour, except colours
  already at full brightness, so speakers stay apart.

The original's text is equally small. Readable Text is an addition to the original.

## Public repository export

The public source repository is a filtered export of the private working repository, one commit per sync, made by
`tools/publish_public.sh`. `STRUCTURE.md` lists what it leaves out and checks. The docs still mention paths it leaves out,
such as `re/decomp`.

## Legal

BioForge is a trademark of Electronic Arts Inc. This is an unofficial fan port; it is not affiliated with, endorsed or
sponsored by Electronic Arts, Origin Systems or GOG. It includes no game data: you need your own copy of BioForge.
