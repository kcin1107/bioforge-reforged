BioForge (Windows and Linux)
============================

An unofficial port of Origin's 1995 game BioForge. It plays the original game from
your own copy of it: no game files are included. Only the GOG release 2.1.0.14
(English) is known to work.

First start
-----------
- Windows: unzip the whole folder anywhere and start BioForgeSDL.exe. The program is
  not signed, so Windows SmartScreen may say it protected your PC: choose
  "More info", then "Run anyway".
- Linux and Steam Deck: make the .AppImage file executable (Properties >
  Permissions, or chmod +x) and start it. On a Steam Deck, do the first start in
  Desktop Mode, then add the AppImage to Steam with "Add a Non-Steam Game".

The first start asks for your BioForge folder: pick the folder with BIOFORGE.EXE
in it, or a folder above it, such as the top folder of a GOG installation. The
choice is remembered. If the folder dialog does not appear, start the game with
BIOFORGE_DATA set to that folder (on Steam: the launch option
BIOFORGE_DATA=/path/to/Bioforge %command%).

Playing
-------
F1 opens the settings: full screen, aspect ratio, music, language, readable text,
and the keys and controller buttons. F11 or Alt+Enter switches full screen.
Controllers (Xbox, PlayStation, Steam Deck) work without setup. The player guide
(PLAYER_GUIDE.md in the source) lists the controls.

General MIDI music
------------------
The original AdLib music needs nothing. General MIDI needs a SoundFont (.sf2), not
included: put one in %APPDATA%\BioForge (Windows) or ~/.local/share/BioForge
(Linux, Steam Deck), or next to the program, then choose Music: General MIDI in F1.
Without one, General MIDI plays as AdLib.

Your files
----------
- Windows: %APPDATA%\BioForge (saves, autosaves, logs, settings.json)
- Linux: saves and autosaves in ~/.local/share/BioForge, logs in
  ~/.local/state/BioForge, settings in ~/.config/BioForge/settings.json

Saves use the DOS game's own GAMEn.IM1 format and work in the Mac app too.

Legal
-----
BioForge is a trademark of Electronic Arts Inc. This is an unofficial fan port; it
is not affiliated with, endorsed or sponsored by Electronic Arts, Origin Systems
or GOG. See NOTICES.txt for the third-party software it includes.
