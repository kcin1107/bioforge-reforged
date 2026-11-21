# Changelog

## 0.1.0 (preview)

### Added

- A native macOS app that plays BioForge from your own copy of the game. It asks for your game folder, checks the files and remembers the folder. No game data is included. Signed and notarized, for Apple silicon and Intel Macs (macOS 14 or later).
- The whole game, from the intro to the ending, with the original's keys, sound effects, subtitles, and music (General MIDI or the original AdLib arrangement). The recorded full run replays in the app's code from start to ending; nobody has yet played it to the end by hand.
- Keys that work on a MacBook with no numpad, remappable in Settings > Controls. Game controllers.
- The PIMM screens (inventory, diagnostics, journal), monitors with live camera feeds, and the original options dialog with nine save slots.
- Autosaves on each level change (the newest five; File > Open Autosave…).
- Game > Language: English, German or French voices and text, from the translations in your game files.
- Readable Text and High-Resolution Art (2x or 4x), both optional and off by default. The art is built on your Mac from your game files, with Venomalia's HDcube model (included with the author's permission).
- Help > BioForge Help and Help > Report a Bug…, which writes a zip you attach yourself. Nothing is sent anywhere.
- [PLAYER_GUIDE.md](PLAYER_GUIDE.md) and [KNOWN_DIFFERENCES.md](KNOWN_DIFFERENCES.md).
- A preview for Windows, Linux and the Steam Deck: a smaller app on SDL3 with the same game, keys, controllers and saves, packaged as a Windows zip and a Linux AppImage. General MIDI there needs your own SoundFont (.sf2); without one it plays the AdLib music. See the player guide.

### Save compatibility

- Saves use the original's `GAMEn.IM1` format both ways. The app loads the DOS game's saves, and the DOS game loads the app's saves.
- A save made by the app also holds the app's running scripts. The DOS game does not resume those scripts; the app does.
- After a load, every animation starts again from its first frame, as in the DOS game. The game clock restarts, and random events can turn out differently.
- A save doesn't keep an open monitor.
- No promise is made yet that later versions will load saves from this one.

### Known issues

- Only Easy was played through. Medium and Hard have every difficulty effect of the original, but nobody has played them to the end, and they are not part of the beta.
- This is a preview: the scripted playthrough reaches the ending in every build, but nobody has played to the end by hand yet.
- Game controllers have not been tried with real hardware. The Linux AppImage has run only in containers, and the Windows zip and the Steam Deck have not been tried by hand.
- Some fights may feel a little harder than the original: Guard 1 starts more attacks in the port than in the original's samples.
- After a load, the music stays silent until the next music cue.
- Only the GOG release 2.1.0.14 (English) is recognised. Other files are reported as different, and the game still starts.
- The other differences are in [KNOWN_DIFFERENCES.md](KNOWN_DIFFERENCES.md).
