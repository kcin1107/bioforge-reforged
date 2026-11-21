# Known differences from the original

What a player can notice where this port differs from the 1995 DOS game, and what it adds. Use it while playtesting: something listed here is already known, so a report only needs to say if it got in the way. Everything else that looks different is worth a report.

Each line says how we know:
- **live**: compared with the original running in DOSBox-X.
- **code**: read from the original's code.
- **inferred**: an assumption.

Details are in `re/NOTES.md` under the heading given.

## Fidelity policy

- The port matches the original's behaviour, including its quirks, unless that would cause a crash, a dead end, or something the Mac forces on it (keys, windows, files).
- Anything the port adds is listed under "Added by the port". Extras that change the picture are off by default.
- A difference that is not on this list is a bug until it is shown to be the original's behaviour.

## Gaps still open

None known. Report anything that differs.

## Kept from the original on purpose

| What you notice | How we know | Notes |
|---|---|---|
| A missile still in the air when the level changes is destroyed. Everything on an elevator travels with it and keeps its place on the floor. | code | "LOADLEVEL: missiles, the volume carry and offsets" |
| Explosions throw fragments of the figure's own mesh. How each piece is turned at the start is not traced, so their spin may look different. | code | "Shrapnel" |
| Lasers rebound off some surfaces (the tower's kiosks, some elevator shafts) and fly on; most walls stop them. | code | "Missiles and FIRE" |
| A camera cut or monitor that changes the colours a lot shows one black frame first, as do level changes. | code | "Monitor keys, pointer glide and black frames" |
| On monitors and in the options, Tab, the arrows and L glide the hand to a button and Return or Space press it; a click while it glides is lost. Right-click acts as Escape. Letters do nothing: the game never gives a button a shortcut letter. | code | same section |
| The credits (R, or Credits in the options) roll over the running game: it is not paused, so enemies keep acting. | live | "The credits roll" |
| The credits scroll one pixel per frame, so their speed follows the frame rate (30 frames a second in the port; about 25 in DOSBox-X with the GOG settings). | code + live | "The credits roll" |
| If you carry ZEDICAID, using MEDICAID spends ZEDICAID's charges. Once ZEDICAID is empty, MEDICAID fails until you put the empty kit down (hold it, Enter). | live | "The last audit findings" |
| A missile loaded from a save flies on silently. | code | "Missiles in saves" |
| After a load, every animation starts again from its first frame. | code | "The original does not save the motion phase either" |
| After a load the music stays silent until the next music cue. | code | "Bug audit 2026-11-14" |
| A sound plays once even if its file has loop points. | code | "Audio: voice statements" |
| Return does nothing on the reload dialog after Lex dies. | code | "Bug audit 2026-11-14" |

## Saves

| What you notice | How we know | Notes |
|---|---|---|
| Saves are interchangeable with the DOS game: its saves load in the app, and the app's saves load in the DOS game. The DOS game does not resume the scripts that were running in an app save, but the app does. | live | "Port saves load in the original" |
| Monitors that are open are closed by a save. | code | README "Saving" |
| Random events after a load (fight rolls, for example) can turn out differently from the same moment without a load. The original saves no random state either. | inferred | "Saves" |
| The game clock (journal times, `%time%` on monitors) restarts after a load. | code | "Game clock" |
| A failed save or load shows an alert with the reason. | port addition | "Bug audit 2026-11-14" |

## Fights

| What you notice | How we know | Notes |
|---|---|---|
| Hits, blocks, armour and the Easy difficulty follow the original's numbers. Fights were sampled in the original at Easy. | live (sampled) | "Fights sampled in the original" |
| Medium and Hard are not played through yet: every way the original uses the difficulty is in the port (checked 2026-11-19), but only Easy is part of the beta. | decompile | ROADMAP "After the beta" |
| Some fights may feel a little harder than the original: Guard 1 started more attacks in the port than in the original's samples. | live (sampled) | same section |

## Sound and music

| What you notice | How we know | Notes |
|---|---|---|
| AdLib music comes from a model of the OPL2 chip, not a real card, and its fine timing is inferred: the driver's 60 Hz serve is placed right after the game frame, without the original's ±7 ms timer jitter. The driver's instrument handling is ported from its code. | inferred | "AdLib music" |
| A song change waits for the song's next bar and is checked once per game frame; how often the original checks is inferred. Transitions between songs are cut off at that next check, as in the original's code, so only their first notes sound. | inferred | "Music state machine" |

## Picture and text

| What you notice | How we know | Notes |
|---|---|---|
| Camera windows on monitors are scaled with plain pixel doubling. The original's exact sampling and colours there are not recovered. | inferred | README "Picture" |
| There is no distance haze. The original loads the haze table but doesn't use it either. | code | README "Picture" |

## Added by the port

- **High-Resolution Art** (View menu, off by default): an AI-assisted upscale of the rooms, figures and monitor pictures (menu and monitor buttons, icons and text are plain-doubled), built on your Mac from your own game files. Movies and the credits roll stay at their original resolution.
- **Readable Text** (View menu): one pixel between letters, a drop shadow, brighter monitor colours.
- **Keys, controllers and windows:** remappable keys with MacBook-friendly defaults, game controllers, and a window that keeps the picture's shape at any size.
- **Game > Language** switches between English, German and French while you play. The original set the language once, in its installer (`language=` in `INSTALL.OPT`).
- **Escape** opens the options dialog during play. The original ignores Escape there.
- **The BioForge picture after choosing the difficulty** stays up for 2 seconds before the first room loads. The original shows it for as long as its level load takes (seconds on the PCs of the time, no timer, no key skips it); the port loads in a fraction of a second, so the app holds it. The game waits meanwhile, so nothing in play changes ("CAMERA SHOW pictures and the TITLE hold" in `re/NOTES.md`).
- **Pausing:** the game pauses while the app is in the background or a sheet or Settings is open.
- **Help > Report a Bug:**
  - The zip holds where you are, the log, a save and a recording of your inputs that replays the bug exactly.
  - After a crash, the next launch offers a report that includes macOS's crash report.
- **Autosaves:** on each level change, the app keeps the last five (File > Open Autosave…). They don't use your save slots.
- **Debug menu:**
  - Camera Viewer.
  - Show Editor Mouse Cursor (the original's `-e` arrow).
  - The tick in the title bar.
  - Tester aids, logged in every report.
  - Save Frame as PNG…: the picture as shown, without the window, for screenshots.
