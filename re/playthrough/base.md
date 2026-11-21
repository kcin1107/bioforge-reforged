# Playthrough: the base and the ending (CONTROL, TOWER, PLATFORM, ENDGAME)

Scope: the part of the game after the CHAOS prison and around the surface levels: the CONTROL base (two visits), the TOWER gun,
the PLATFORM alien city, and the ending (`ENDGAME`, credits). Harness: `re/interp/playthrough_base.py`; regression tests:
`re/interp/test_playthrough_base.py`. Script citations are `re/out/scripts/<FILE>.scr:<line>` (decoded with
`re/formats/script.py game/app/Bioforge/SCRIPT re/out/scripts`; line numbers do not change with the selector fix below).

## 1. The main path, from the scripts

### Level graph and order

There is no single linear order: the elevator monitor reaches CHAOS, CONTROL, TOWER and LANDPAD at any time
(`ELEVATOR_MONITOR`, ELEVATOR.scr:750; `LV5B`/`LV6B` only say "level inaccessible", ELEVATOR.scr:897), and no elevator button
checks a story global. The scripts imply this order for the stretch:

1. CHAOS → elevator → **CONTROL** (first visit: hallway robot, operating-room scene, control room, garage lift).
2. CONTROL → elevator → **TOWER** (Roland, the gun, the two landers). TOWER is optional for the ending; killing the first lander
   only removes the Marine 1 trap in CONTROL (AI_MRN1.scr:3).
3. … LANDPAD → BEACH → DIGSITE / TUNROOM (the surface stretch, another session) → zero-g room → **PLATFORM** (city puzzle, the
   Elite gives the alien battery) → back to TUNROOM (grav ring puzzle, `_Grav_Solved`) → BEACH → LANDPAD → elevator →
4. **CONTROL** (second visit): the alien battery in the bike → `OUTAHERE_USE` → **ENDGAME** → credits → `EXIT`.

PLATFORM does not lead to CONTROL by itself: its exits go back to TUNROOM (`BTTL_RM_USE`, PLATFORM.scr:171-174;
`TO_ZEROG`, TUN2PLAT.scr:24-26). The reactor shutdown in CONTROL is not required by any script on the way to the ending.

### Arrivals (all through `LOADLEVEL`)

| Arrival | Statement | Caller continues after LOADLEVEL? |
|---|---|---|
| CONTROL from CHAOS / TOWER / LANDPAD | `LOADLEVEL CONTROL ELH\|ELT\|ELV ELC _sfx_5` in `SWITCHTOCONTROLLEVEL` (ELEVATOR.scr:231, 280-304) | yes: ELEVATOR.scr is in CONTROL.LVL; the tail runs `EXITSTASIS`, opens the door, `ACTIVATE_GRDCON` (ELEVATOR.scr:310-325) |
| TOWER from CHAOS / CONTROL / LANDPAD | `LOADLEVEL TOWER ELH\|ELC\|ELV ELT _sfx_5` in `SWITCHTOTOWERLEVEL` (ELEVATOR.scr:3, 53-87) | yes (ELEVATOR.scr is in TOWER.LVL) |
| PLATFORM from the zero-g room | `LOADLEVEL PLATFORM FRMZEROG` in `TO_FINAL` (TUN2PLAT.scr:2-19) | yes: `GO FRMZEROG`, walk to WALKHERE, `AI ON` (TUN2PLAT.scr:12-19, "DON'T KNOW WHY THIS IS NECESSARY, BUT IT WORKS") |
| TITLE for the ending | `LOADLEVEL TITLE ABC` in `ENDGAME` (ENDGAME.scr:3-4) | yes: ENDGAME.scr is in TITLE.LVL; the whole ending runs after it |

The three-word form `LOADLEVEL <level> <volume> <destination>` carries what is inside `<volume>` of the old level to
`<destination>` of the new one: the CONTROL elevator is ELC, the TOWER elevator ELT (see §3, fix 2).

Prerequisites: no elevator arrival checks a global or an item. `CONTROL_LOAD` (CONTROL.scr:4-68) and `TOWER_LOAD` (TOWER.scr:2-55)
do not branch on the arrival; both branch on `_alien_city_seen` (set by the PLATFORM city scene, EL_SCENE.scr:256): before it,
the guards GRDHALL / GRDCON / GRDHANG live and MARINE5 does not; after it, the reverse (AI_GRDHL.scr:1-13, AI_GRDCN.scr:28-34,
AI_GRDMS.scr:1-9, AI_MRN5.scr:1-5), and TOWER's bots are removed (AI_TOWER.scr:92-108). PLATFORM's arrival checks nothing; it
needs `_TubesOpen` bit 2 to reach the zero-g room (TUNROOM.scr:172, set by the TUNMON tube monitor, TUNMON.scr:377).

### CONTROL, first visit (in order)

1. Hallway robot MECHO2 fires at Lex (AI_MECH2.scr:62-85); `MECHO2_DEATH` clears `_Mecho2_Alive` (AI_MECH2.scr:122-145). The
   operating-room button refuses while it lives (CONOPER.scr:131-136). `ELV_C22_USE` logs NEEDGUN without a blaster (CONTROL.scr:198-203).
2. Operating room: triggers OPENT2 / OPENT3 / OPENTER run `OPRSCENE` once (`_Do_OPR_Scene`, MASTABA.scr:3-32): Mastaba's
   speech, Dane, a fade; every BLASTER is removed (MASTABA.scr:277-283); `_Operate_Done = 1` (MASTABA.scr:313),
   `READY_MARINE1`, `KILL_MECHO2` (MASTABA.scr:322-323). Optional: Dane's death (CONOPER.scr:18, 1129).
3. Marine 1 trap in the control hall if the first lander lives (AI_MRN1.scr:1-64: 500 energy damage).
4. Control-room door: `CNT_BTN3_USE` refuses until `_Operate_Done` (CONCNTRL.scr:2-22). GRDCON in the control room (AI_GRDCN.scr:60-81).
5. Consoles: hangar monitor `CR_HANGERMONITOR` (CONCNTRL.scr:208-385), whose ICARUS ACCESS button (`AIAB`) lowers the garage after
   the monitor closes (`CALL LOWER_GARAGE_ELEVATOR`, CONCNTRL.scr:372-381); its bike journal sets `_did_bike_journal`
   (CONCNTRL.scr:259). Reactor and maintenance monitors are informational.
6. Optional: forklift (ROBOCNTL.scr:7, CONREACT.scr:82-125) rams REACTBOT, light bridge (BRIDGE.scr:2-60), Drogg 1 and the
   reactor timer, levers and the random reactor ID (ASSIGNID.scr:24-47, SHUTDOWN.scr:100-190; played in `playthrough_full.py`, see `re/NOTES.md`, "The reactor puzzle"); losing runs `SHUT_DOWN_LOSE`
   (SHUTDOWN.scr:483). Leaving by elevator while the countdown runs is death (ELEVATOR.scr:65-73).
7. Garage lift: `LOWER_GARAGE_ELEVATOR` (CONMACH.scr:402-519; SETFLOOROFPHYS / TELEPORTALLONPHYS) activates GRDHANG at 01:02
   and sets `_Seen_Mach_Shop` (CONMACH.scr:506); `TAKEMEUP` raises it again (CONMACH.scr:288-398).

### TOWER (optional for the ending)

1. Arrival: `TOWER_LOAD` (TOWER.scr:2-55), `ELT_LOAD` (TOWER.scr:58-96): tower bots readied (AI_TOWER.scr:111-127), Mastaba's
   speech once both landers are dead.
2. `TWR_LOAD` forces `_Lander_Stage ≥ 1` (TOWER.scr:130); `TWR4_LOAD` 1 → 2 and "main gun is off line" (TOWER.scr:164-176);
   `TWR1_LOAD` 2 → 3, `SHIPORCHESTRA`, `MANAGEGUN` (TOWER.scr:136-150).
3. Roland (AI_ROLAN.scr:142-365): hurt him below 50 and he restarts the gun (`_GunActive = 1`, AI_ROLAN.scr:365).
4. Gun: `BIG_GUN_USE` (TOWERGUN.scr:89-103, `CAPTUREKEYBOARD CBG`), KP4/KP6 swivel (TOWERGUN.scr:35-74), KP5/Space fires
   (TOWERGUN.scr:159-187). Ship 1 hit test `TESTFIRSTHIT` (TOWERGUN.scr:586-620), ship 2 `GETSECONDSHIPHITSTATE`
   (TOWERGUN.scr:667-671); missing ship 2 is death (`BLOWYOUUP` → `KILLLEX`, TOWERGUN.scr:266-298).
5. Leaving: the door refuses while `_Lander_Stage` is 3-4 (TOWER.scr:214-218); elevator panels TOWER.scr:186-198.

### PLATFORM (in order)

1. `TO_FINAL` arrival (above); `PLATFORM_LOAD` (PLATFORM.scr:10-47), `PLT_LOAD` (PLATFORM.scr:60-83; a new ALBAT if
   `_need_new_battery = 1`, PLATFORM.scr:72-81).
2. City monitor `CTYMON_USE` → `CITY_MONITOR` colour-grid puzzle (CITYMON.scr:6, 574); solved → `PROCESS BRINGONTHEALIEN`
   (CITYMON.scr:1378-1395).
3. `BRINGONTHEALIEN` (EL_SCENE.scr:195-297): flic `plt0` (`RUNFLIC CITYON`, Esc skips, EL_SCENE.scr:227-234), `_alien_city_seen`
   and `_escher_dead` set (EL_SCENE.scr:256-258), the ship rises, the Elite walks to Lex and `ACTIVATE_ELITE` runs (EL_SCENE.scr:289).
4. The Elite (AI_ELITE.scr:124-246): on contact a subtitled speech, then `CREATEITEM ALBAT`, `INDIVIDUALIZE CURITEM ABAT_500`,
   charge 500 / max 500 / type `_ABAT_500` / alien flag 1 on the battery, into Lex's right hand, `_gave_alien_battery`
   (AI_ELITE.scr:170-183); it leaves in its ship (EL_SCENE.scr:339). Killing it drops the battery instead (AI_ELITE.scr:249-307).
5. Not optional: Drogg 3 in the battle room (AI_DROG3.scr:9-371) drops REFLECT, whose mirror suit is the only way through PLTDOOR (`re/NOTES.md`, "The mirror suit"). Glass-floor death: PLATFORM.scr:200-321.

### CONTROL, second visit, and the ending

1. Arrive by elevator (any source), lower the garage from the hangar monitor (`AIAB`), walk to the bike.
2. `BIKE_USE` (CONMACH.scr:8-193). With the original battery still in (`_Battery_In_Bike = 1`, VARS.DEF), the first use
   takes it out into Lex's right hand (charge 150, CONMACH.scr:28-67), putting down what he held. The second use with
   MONBAT or ALBAT in the right hand puts it in (CONMACH.scr:69-90). The alien battery (flag `~3 = 1`) is refused with a journal
   hint until `_Grav_Solved` (TUNGRAV.scr:165) (CONMACH.scr:93-125). Charge ≥ 375 (CONMACH.scr:154) closes the panel, opens
   the canopy (`ANICANOPY` → `_Can_frame = 29`), walks Lex to END1 / END2 and calls `OUTAHERE_USE`; a weaker one logs
   BIKEWEAK / BATTLOW (CONMACH.scr:175-189).
3. `OUTAHERE_USE` (CONMACH.scr:197-220): Lex climbs in, `MUSIC _VICTORY`, `ANI_BIKE_TAKES_OFF`, `CALL ENDGAME`.
4. `ENDGAME` (ENDGAME.scr:1-52): `LOADLEVEL TITLE ABC` (TITLE_LOAD kills LEX, TITLE.scr:1-4), `CAMERA UNLOCK`, `FREEZE`,
   `STARTFLIC "endgame"` at rate 6, sound banks, `SUSPENDWHILE RUNFLIC ENDPROCESS 525`: the `[ ENDPROCESS ]` timeline
   (ENDGAME.scr:65-119) plays the bike and flyby sounds and at 47:04 `MUSIC _OPTIONS` and `CALL ROLLCREDITS`
   (`MON_CODE _OPTS_CREDITS`, PIMM.scr:855-857). Then `CAPTUREKEYBOARD GETESCKEYORALTX`, `JUMPON USERINTERRUPT LEAVEGAME`,
   and the loop `:WAITHERE SUSPEND; IF CREDITSSTATE () == 2 THEN WAIT 5 SECONDS ELSE JUMP WAITHERE` (ENDGAME.scr:27-36).
   `LEAVEGAME`: stop sounds, `MUSIC _GMRESET`, `RELEASEKEYBOARD`, `STOPFLIC`, `THAW`, `EXIT` (ENDGAME.scr:38-51).

Bad endings on this stretch: `SHUT_DOWN_LOSE` (SHUTDOWN.scr:483), `BLOWYOUUP` (TOWERGUN.scr:266-298), the airlock
(CONREACT.scr:210-222), the PLATFORM glass floor (PLATFORM.scr:268-321). WARHEAD.scr is a BEACH countdown, not an ending.

## 2. The harness

`re/interp/playthrough_base.py` (`re/.venv/bin/python -I -W ignore re/interp/playthrough_base.py [--out DIR]`, about 25 s; the JSON
report goes to `re/out/playthrough/playthrough_base.json`). Four deterministic segments, each starting in the level the game comes from
and arriving through the engine's own LOADLEVEL (the scripted elevator ride or tube transit runs the statement). Input is real keys
(`World.key_down` / `key_event`, `scenarios.Play`'s walk / face helpers). Each segment collects checkpoints, problems (new warnings,
unmodelled calls, steps stuck past a tick limit, soft locks) and the shortcuts it took.

| Segment | Arrival | Driven by keys | Reaches |
|---|---|---|---|
| control-first | CHAOS → `SWITCHTOCONTROLLEVEL` → CONTROL ELC | Lex walks into OPENTER | MECHO2 dead (staged), OPRSCENE to `_Operate_Done = 1`, blasters removed; Lex gets up (`GET_UP_FORWARD`) |
| tower | CONTROL → `SWITCHTOTOWERLEVEL` → TOWER ELT | the run across the deck, Space at BIG_GUN, KP4 / KP6 aim, Space fires | both landers shot down with one shot each, `_Lander_Stage = 5`, Lex at 100 HP |
| platform | TUNROOM → `TO_FINAL` → PLATFORM FRMZEROG | the walk from CTYMON over PLAT01 / PLAT03 | `TO_FINAL`'s tail walks Lex to within 614 units of WALKHERE; city scene (flic PLT0); the Elite walks to Lex by itself and its attack makes the contact (no staging); the Elite's speech; ALBAT charge 500 / max 500 / type 3 / alien 1 in Lex's right hand |
| ending | LANDPAD → `SWITCHTOCONTROLLEVEL` → CONTROL ELC | the walk to the bike, Space (both uses), Enter (put down / pick up), Esc | old battery out (150 / 500 / 3), alien battery in, canopy, `OUTAHERE_USE`, ENDGAME survives `LOADLEVEL TITLE`, the end flic and ENDPROCESS sounds, `ROLLCREDITS`, Esc → `LEAVEGAME` → `EXIT` (`exit_requested`) |

In the full run the alien battery is in Lex's leg by then, because the zero-g room needed the gun's hand. `ending_bike` takes the old battery out of the bike, swaps it with Space away from the bike (ABAT_500_USE), and puts the alien one in.

**How far it gets:** every segment reaches its goal, and the game reaches its end (`EXIT`) through the real ENDGAME. Since the movement fixes
(NOTES "Movement fixes") three of the old stops are gone: OPRSCENE's soft lock (blocker 2), the stuck Elite (blocker 5, and the `contact`
shortcut with it) and the looping PUT_BATTERY (blocker 3, and the `motion-release` shortcut). Without the remaining staged shortcuts, play
stops at blocker 6 below. Since "Items and combat" (NOTES) the ending runs with both batteries named ABAT_500: Lex holds the gift when BIKE_USE starts, it goes to the floor, the old battery (ABAT_500#2 in the port's store, charge 150) comes out and RESTOREALIASOFBATTERY runs; it ends at tick 3582 with Lex at 100 HP.

### Staged shortcuts (also in `SHORTCUTS` and in each run's report)

| Shortcut | Where | Why |
|---|---|---|
| player | every segment | Lex is created as START.scr does and placed at the source level's arrival point; earlier levels are not played |
| globals | ending: `_alien_city_seen`, `_Grav_Solved`, `_gave_alien_battery`, `_escher_dead`; tower: `_GunActive = 1`; platform: `_city_solved` | what the earlier levels (surface, grav ring) or a skipped fight set |
| item | control-first: CHAOS's BLASTER into the right hand; ending: the Elite's battery, by a block repeating AI_ELITE.scr:177-183 | inventory from earlier levels |
| elevator-button | the three elevator rides | the ELEVATOR_MONITOR floor button is a MON_* click; the harness starts the block it runs |
| trigger | platform: `TO_FINAL`, the solved CITY_MONITOR (`PROCESS BRINGONTHEALIEN`); ending: the hangar monitor's ICARUS ACCESS tail (`CALL LOWER_GARAGE_ELEVATOR`) | trigger geometry / monitor UI not driven by keys |
| set-pos | control-first: in front of OPENTER; tower: GUNHERE; platform: CTYMON; ending: over the garage lift | walking there is not the point of the step |
| hold-fire | tower: TOWBOT1-6 AI off during the crossing | missile hits ignore INVULNERABLE; the bots fire into the open elevator at once (problem 8) |
| fight-outcome | control-first: `MECHO2_DEATH`; tower: Roland's gun restart (`_GunActive = 1`) | blocker 6 / a fight not driven |
| unstick | control-first: GRDOP's `GO OPRGD1` (a guard; not triggered in the current run) | completes a scripted GO that stops making progress |

> The full run (`re/interp/playthrough_full.py`, `re/playthrough/full.md`) continues this stretch in the same World / VM; it takes the segment functions of this harness on the running world.

## 3. Problems found, ranked by how much they block play

Fixed in both ports (section 4) are not repeated here.

1. **Resolved (NOTES "Room events and the default AI").** **Room events were not ported.** TWR_LOAD, ELT_LOAD, CTR_LOAD, OPR_LOAD, PLT_LOAD and the rest now run from the
   engine's camera switch; the harness's `room-events` wrapper is gone and every segment still reaches its goal.
2. **Resolved by the movement fixes.** **Soft lock after the operating-room scene.** OPRSCENE knocks Lex out with `MOTION DIE FREEZE CONTINUE`;
   `1098:0394` refuses a motion change only while DIE is current and *unfinished*, and FREEZE only clears the idle-fallback bit, so once DIE
   has played the blocking `MOTION GET_UP_FORWARD` (MASTABA.scr:310) works. The guard used to refuse for good.
3. **Resolved by the movement fixes.** **`MOTION <x> CONTINUE` looped forever when `is_cycle` judged the clip a cycle.** The loop rule is the
   header's frame event list: a motion loops iff it holds the 0xfe marker (`1088:1854`). PUT_BATTERY and CELEBRATE play once.
4. **Resolved by "Items and combat" (NOTES).** **Items were keyed by instance name**: `RESTOREALIASOFBATTERY` (ITEMS.scr:1274) renames every removed battery ABAT_500 / BAT_100 / BAT_150, so taking the bike's old
   battery out replaced the Elite's battery. The engine's list allows duplicates; SETCURRENTITEM takes the nearest match to the player (`10c0:3fd9`). The `item-name` shortcut is gone.
5. **Resolved by the movement fixes.** **The Elite could not move after the city scene.** `GO FELITE RUN` with gravity off snapped the origin to the
   waypoint z (−1473, the PLAT03 top) at its arrival, burying the hull 1496 units in PLAT03. A GO now ends without a snap and keeps its z
   (GO PELITE puts the origin at 1279), so the Elite walks to Lex by itself and its attack makes the contact.
6. **MECHO2 kills Lex in the CONTROL elevator.** The elevator lies inside MECHO2's trigger zones (CMECH1A / 1B inside INELC), so once
   the door opens it fires (AI_MECH2.scr:55-90). Every bolt knocks Lex into a recoil or fall, so facing it took 357 ticks and he died
   before the first shot. The port puts Lex at the centre of ELC (the three-word LOADLEVEL ASSUMPTION, not his offset in the volume),
   which may matter; otherwise this is a real fight that needs a better key policy (close the door first).
7. **No credits roll; CREDITSSTATE is always 0.** Does **not** block the end: ENDGAME's keyboard hook takes Esc / Alt+X and runs
   LEAVEGAME → `EXIT` (verified). Not ported, because it is not small: the port's `open_options` refuses while a flic is open, a rule
   that `10a8:02cc` does not have (its gates are IsExitMonRunning, `[4e3d]` / `[a36a]`, the pause flag, `1100:0f02` = the FADE state
   `[49bd]`, and the save checks), so `ROLLCREDITS` (`MON_CODE _OPTS_CREDITS`) opens nothing; the roll itself scrolls per
   `credits_frame_ticks` (read in `1278:1b47`) and sets `[9ce5]` 1 / 2 (`1278:1c08`); and closing the dialog runs `FUN_1100_0ae6` (`[9ce5] = 0`, then
   `LOADLEVEL TITLE` or the `CreditsRolling` block). Lifting the flic rule alone would open a static, pausing credits dialog and make
   the end worse.
8. **Tower bots fire into the open elevator on arrival** (ELT_LOAD → READY_TOWERBOTS; bot 1 has a line through DR7 to the centre of
   ELT): 14 HP every 26 ticks, death in about 5 s standing still. Probably a real gauntlet; the arrival-offset ASSUMPTION (problem 6)
   decides where Lex stands.
9. Warnings: `BREAK 2` / `BREAK 4 != innermost switch index` (SWITCHTOCONTROLLEVEL, RESTOREALIASOFBATTERY: the known BREAK-n
   ASSUMPTION), `APPLY MASTABA (PICTURE): no such texture`, `SOUND …: current figure MASTABA not found` (after Mastaba is killed),
   `CAMERA SHOW STITLE: logged only`, and the three-word LOADLEVEL ASSUMPTION.

## 4. Fixed (both ports, twin tests in `test_playthrough_base.py` / `PlaythroughBaseTests.swift`)

| Fix | RE | Effect on this stretch |
|---|---|---|
| A LOADLEVEL caller survives when its script file is in the new level's .LVL; its CALL chain is spared from the kill | `10b0:13fb` (via `1148:14a3`), `10d0:4d46` tail (context +0xe87 → `1118:434d` record, +0xd code) | elevator rides run EXITSTASIS and open the door; `TO_FINAL` walks Lex to WALKHERE; ENDGAME runs after `LOADLEVEL TITLE` (without it the game could not end) |
| Three-word LOADLEVEL arrives at the third word | `10d0:4d46` (+700 → `1148:15c7` → `1050:0c65`) | Lex arrives in the elevator ELC, not on CONTROL's garage PHYS ELV |
| Object-local selectors: 1 = CURITEM, 2 = CURFIG | `10c0:24e1` | battery charge / type / alien flag are the battery's; AI attack status is the figure's; generic LASER_HIT now damages live targets (NOTES "Missiles") |
| INDIVIDUALIZE moves the object's locals | `10c0:24e1` (+0x92) | the bike's old battery keeps 150 / 500 / type 3 |
| Level figures take their AI name from the record | `10d0:6e8c`, `1088:33d4-3402` | ELITE_AI and AIRMECHO_AI start on `AI ON` |
| `CALL ( NAME( a, b ) )` passes its arguments | script syntax (29 sites) | the tower gun can hit the first lander; CITYMON's GET_COLOR(n) |
| A refused MOTION does not block | `1098:0394`, `10d0:5e8b` | OPRSCENE reaches `_Operate_Done = 1` |
| A use block that takes Lex keeps him | `apply_player_input`'s own guard | BIKE_USE's `GO HOOD WALK` walks |

Test changes the fixes caused (shared files): `scenarios.chaos_guard1_fight` no longer starts ENTERCELL2 itself and is reseeded
(GUARD1_SEED 1 → 3; Easy wins with 8 of seeds 1-12, Medium is lost with all); `test_landpad_meetmech` expects AIRMECHO_AI's march;
`test_missiles` / `MissileTests` expect the laser's 25 energy (nurse 50 → 29); the VM trace `switch_level` returns ISAION 1 so
EXITSTASIS ends; the Swift fixtures were regenerated. **The decoded `re/out/scripts` must be regenerated after merging** (218 lines
change, only selector names).

Movement fixes (NOTES "Movement fixes", both ports): `test_playthrough_base.py` / `PlaythroughBaseTests.swift` now expect `TO_FINAL`'s walk to end at
(8566, -123457), within the GO radius of WALKHERE, BIKE_USE's `GO HOOD WALK` to end within 614 units of the hood, and add
`test_die_then_get_up_once_die_has_finished` (DIE plays out, holds its last pose, GET_UP_FORWARD plays). The platform segment no longer stages the
Elite's contact and the control-first segment no longer logs a soft lock. `GUARD1_SEED` is now 0 and the Caynan fight is seeded
(`CAYNAN_SEED` 10), because the opening is 54 ticks longer (two blocking FREEZEs).
