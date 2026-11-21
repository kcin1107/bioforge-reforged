# Playtest guide

How to play the port for the first human playthrough and report what you find. The goal is the beta's test (ROADMAP §7): a person plays from a new game to the ending in the app, at Easy, with real keys.

## Before you start

- Use one build per session: the one from `native/build-app.sh`. Help > About shows its commit, and every report carries it.
- Read `KNOWN_DIFFERENCES.md` once. Anything listed there is known: report it only if it got in your way.
- Keep the DOS game at hand (DOSBox-X or GOG's DOSBox) if you want to compare a moment yourself. You don't have to: settling "is this the original's behaviour?" is my job.

## While you play

- **Something wrong or odd:** Help > Report a Bug… right away, while it's still on screen. One sentence on what you expected is enough. The zip holds:
  - where Lex is;
  - the log;
  - a save of that moment;
  - a recording of your inputs since the game started or was loaded, so I can replay the minutes before the report exactly.
- **A crash:** start the app again; it offers a report that includes macOS's crash report.
- **Stuck:** File > Open Autosave… goes back to the start of an earlier level (the last five level changes). Debug > God Mode (no damage), Debug > Refill Health and Debug > Open Save File… (any `.IM1`) get you past a blocker. God Mode also stops the game's own scripted deaths (drowning in the tanks, for example), so turn it off again if a death scene doesn't end. Each use is logged, so say in the report that you used one. Save points along the whole route, made by the scripted run, are in `~/Library/Application Support/BioForge/SavePoints` for Open Save File….
- **Save before anything risky,** and save and load at odd moments now and then, for example during a scripted scene or just after a fight starts. A save that loads differently from how it was saved is the hardest kind of bug to find any other way.

## Sessions

One session per area, in game order. Tick an area when you've finished it ("completable") and filed its reports. The save points named here are the scripted run's own stages, if you want to compare with it.

| # | Area | Main path | Also try | Done |
|---|---|---|---|---|
| 1 | **Prison** (CHAOS) | Wake-up, nurse, Caynan, the cell, Dane's code, the arm, the security terminal, Guard 1 (`guard1`), the blaster, bio-repair, the tanks and back (`tanks-back`), the hall and the elevator (`hall-to-elevator`) | Every item in the inventory with Space; fight Guard 1 with the keyboard only; save and load during the nurse scene; fall into the tanks | [ ] |
| 2 | **Tower and control** | The tower deck and both landers (`tower`, `tower-exit`), the operating room, the hard suit and GRDCON (`hardsuit`, `grdcon`), the garage (`garage-block`, `garage-up`), GRDHALL, the forklift | The gun keys on the tower; the medkits with ZEDICAID carried; quitting and loading in the middle of a fight | [ ] |
| 3 | **Reactor** | The reactor room, Drogg 1, the shutdown puzzle (`reactor-room`, `drogg1`, `reactor-shutdown`) | Wrong answers in the puzzle; leaving and coming back | [ ] |
| 4 | **Surface** | The landing pad and the Captain (`to-landpad`, `landpad`), the beach, the dig site, the tunnel room, Drogg 3 (`battle-room`), the platform | The Captain by keys alone; the mirror suit; the monitors (tomb, city, tube) clicked by hand | [ ] |
| 5 | **Zero-g and temple** | `zero-g-back`, the gravity ring, the temple monitor and temple, the climb back, the walk to the elevator (`landpad-to-elevator`) | Flying both crossings by hand; the grenade | [ ] |
| 6 | **Ending** | The bike and the ending (`bike`) | A save just before the ending, loaded again | [ ] |

Across all sessions, try once each:
- options and the audio and gamma panels;
- key remapping;
- a game controller, if you have one;
- resizing the window and full screen;
- High-Resolution Art on and off.

## How reports are sorted

Every report gets three labels. I set them; you don't need to.

- **Severity:**
  - *blocker*: a crash, a dead end, or a lost save;
  - *major*: wrong behaviour on the path;
  - *minor*: wrong, but you can play on;
  - *cosmetic*: looks or sounds only.
- **Repro:** *always*, *sometimes* or *once*. The recording usually turns "once" into "always".
- **Kind:**
  - *bug*: the port is wrong;
  - *differs from the original*: checked in the DOS game in DOSBox-X;
  - *known*: already in `KNOWN_DIFFERENCES.md`.

Blockers are fixed first, then majors. Every fix comes with a test, and when the original is involved, with a live check in it. A difference that turns out to be the original's own behaviour is added to `KNOWN_DIFFERENCES.md` so it isn't reported again.
