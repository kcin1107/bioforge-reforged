# BioForge: player guide

This is an unofficial port of the 1995 game BioForge to macOS, with a preview for Windows, Linux and the Steam Deck (see below). Version 0.1 is a preview: some things still differ from the original. See [KNOWN_DIFFERENCES.md](KNOWN_DIFFERENCES.md) and [CHANGELOG.md](CHANGELOG.md).

## What you need

- A Mac running macOS 14 or later, Apple silicon or Intel. It has been tested on an Apple silicon Mac (an M4 Pro); Intel Macs are supported but untested. Or, for the preview, a 64-bit Windows PC, a Linux computer or a Steam Deck.
- Your own copy of BioForge, for example the GOG release. The game's files are never included.

Only the GOG release 2.1.0.14 (English) is known to work.

## Installing on a Mac and first launch

1. Download `BioForge-mac.zip` from the [latest release](../../releases/latest), unzip it and move `BioForge.app` to Applications. The app is signed and notarized, so it opens with a double-click.
2. The app asks for your BioForge folder. Pick the folder with `BIOFORGE.EXE` in it, or a folder above it, such as the top folder of a GOG installation. The app remembers your choice. File > Open Game Folder… (⌘O) changes it.
3. The app checks your game files each time. If files are missing, it will not start and names them. If files are different from the GOG release, it starts anyway and says so once.

## Playing

- Choose Game > New Game (⌘N). The intro plays (Escape skips it). Then choose a difficulty. Easy is the one the beta was checked on.
- Press S to save and L to load. There are nine slots. Saves are kept in `~/Library/Application Support/BioForge/Saves`.
- The app also saves by itself when you enter a new level, and keeps the newest five. File > Open Autosave… continues from one.
- Escape opens the options dialog and pauses the game. Press Escape again to go back.
- The game pauses when the app is in the background.

## Controls

These are the default keys. No numpad is needed.

| Action | Key |
|---|---|
| Walk, back, turn | Arrow keys |
| Walk forward (the Home and Page Up moves) | Fn+Left, Fn+Up |
| Sidestep left, right | Fn+Right, Fn+Down |
| Run | Shift |
| Use | Space |
| Pick up / put down | Return |
| Combat mode on/off | C |
| Attack (in combat) | The movement keys |
| Kicks | Hold A with a direction |
| Punches | Hold Option with a direction |
| Shoot | / |
| Personal monitor (PIMM) | P |
| Inventory, Diagnostics, Journal | I, D, J |
| Options, Save, Load, Credits | O, S, L, R |
| Exit the game | Option+X |
| Darker / brighter picture | Shift or Option with , and . |

BioForge > Settings… (⌘,) remaps every key. Each control has a key and an alternate.

Game controllers are found by themselves. The left stick and D-pad move Lex, and on the game's screens they move the pointer. A clicks and B goes back.

## The PIMM

Press P for the main screen, or I, D or J for a page. Use the mouse or trackpad to move the pointer and click. Escape or Exit closes it.

- Inventory: pick an item with the up and down buttons, then click READY. Space uses the item in hand. Return puts it down.
- Diagnostics: health, energy and the PFD controls.
- Journal: entries appear as the game awards them.

## Options

- View > Readable Text: more space between letters, a shadow and brighter colours on monitors and in dialogs. Off by default.
- View > High-Resolution Art: Off, 2x or 4x. It is optional and off by default. The app builds the art on your Mac from your own game files; it is not downloaded. The first time takes about 11 to 12 minutes on an M4 Pro, and you can play while it builds. It needs an AI model that a shared build may not include, because the model's author has not yet given permission to ship it. Without the model, this option cannot build art.
- Game > Language: English, Deutsch or Français, for the voices and all text, as in the original's German and French versions. Your GOG copy already contains all three. It changes at once; the intro movie follows on the next new game.
- View > Correct Aspect Ratio, Game > Mute (⌥⌘M), Game > Music Device (General MIDI or the original AdLib music).

## Windows, Linux and Steam Deck (preview)

There is also a smaller app for Windows and Linux, `BioForgeSDL`. It plays the same game with the same keys, controller buttons and saves (a save file works in either app). It has been checked on Linux, in test containers only; Windows and a real Steam Deck have not been tried yet. No package has been shared publicly yet: these steps are for when one is.

### Windows

1. Unzip `BioForge-…-windows-x64.zip` anywhere, keeping all its files together, and start `BioForgeSDL.exe`.
2. The program is not signed. Windows SmartScreen may say "Windows protected your PC": choose More info, then Run anyway.
3. The first start asks for your BioForge folder, as on the Mac: pick the folder with `BIOFORGE.EXE` in it, or the top folder of the GOG installation. It is remembered.

### Linux

1. Make `BioForge-…-x86_64.AppImage` executable (in the file manager: Properties > Permissions; or `chmod +x`) and start it. Use the `aarch64` one on an ARM computer. It needs a Linux from about 2022 or later (Ubuntu 22.04, Debian 12, Fedora 36 or newer). If it says FUSE is missing, install your distribution's `fuse3` package.
2. The first start asks for your BioForge folder, as above. Your copy can come from the GOG installer (copied over from a Windows PC, or unpacked with `innoextract`) or from a launcher such as Heroic.

### Steam Deck

1. In Desktop Mode, copy your BioForge game folder to the Deck (for example to `~/Games/BioForge`, keeping `GAMEDAT` next to `Bioforge` as in the GOG installation), and put the AppImage next to it.
2. Make the AppImage executable (right-click > Properties > Permissions > Is executable) and start it once. Pick the game folder when asked. Do this first start in Desktop Mode: the folder dialog may not appear in Game Mode.
3. In Steam (still in Desktop Mode): Games > Add a Non-Steam Game to My Library, Browse, choose the AppImage. It now shows in your library in Game Mode.
4. In Game Mode it starts in full screen. The Deck's controls should work with the default layout Steam gives a non-Steam game: the left stick and D-pad move Lex, A uses, B goes back, Start opens the options dialog, and the right trackpad moves the pointer on the game's screens. No Steam Input template is needed. For the keyboard, press Steam + X.
5. If the folder was never picked, or you want another one: in the game's Properties in Steam, set the launch options to `BIOFORGE_DATA=/home/deck/Games/BioForge/Bioforge %command%` (the folder with `BIOFORGE.EXE`).

### Playing

- F1 opens the settings screen, which takes the place of the Mac's menus: Full Screen, Aspect Ratio, Music (General MIDI, AdLib or Off), Mute, Language, Readable Text, and the keyboard and controller bindings. Use the arrows (or the D-pad), Enter (or A) and Escape (or B). On a controller, the View (Back) button opens it from the game's options dialog.
- F11 or Alt+Enter switches full screen. On a Steam Deck it starts in full screen.
- General MIDI needs a SoundFont (`.sf2`), which is not included: put one in `~/.local/share/BioForge` (Linux, Steam Deck) or `%APPDATA%\BioForge` (Windows), or next to the program or the AppImage, or set its path as `"SoundFont"` in the settings file. On Linux an installed one is found too (Debian and Ubuntu: `fluid-soundfont-gm`; Arch: `soundfont-fluid`). Without one, General MIDI plays as AdLib and the settings screen says so. `.sf3` files are not read. The synth (TinySoundFont) has no reverb or chorus, so General MIDI may sound drier than on the Mac.
- There is no High-Resolution Art and no Report a Bug yet.
- Your files: on Linux and the Steam Deck saves and autosaves are in `~/.local/share/BioForge`, logs in `~/.local/state/BioForge` and the settings in `~/.config/BioForge/settings.json`; on Windows all of them are in `%APPDATA%\BioForge`.

## Reporting a bug

On the Mac, choose Help > Report a Bug… when it happens. The app writes a zip file to `~/Library/Logs/BioForge/Reports` and shows it in the Finder. It holds where you are, the log, a save and a recording of your keys. Nothing is sent anywhere: open an issue on the project's GitHub page ([Issues](../../issues)) and attach the file there. After a crash, the next launch offers to make a report.

Help > BioForge Help (⌘?) shows these steps and your current keys.

## Known differences

The full list is in [KNOWN_DIFFERENCES.md](KNOWN_DIFFERENCES.md). The ones you may notice:

- Only Easy was played through. Medium and Hard have every difficulty effect of the original, but nobody has played them to the end, and they are not part of the beta.
- Some fights may feel easier or harder than the original.
- After a load, every animation starts again from its first frame and the music is silent until the next cue.
- The credits roll over the running game, so enemies keep acting.
- Escape opens the options dialog; the original ignores Escape there.

## Legal

BioForge is a trademark of Electronic Arts Inc. This is an unofficial fan port; it is not affiliated with, endorsed or sponsored by Electronic Arts, Origin Systems or GOG. It includes no game data: you need your own copy of BioForge.
