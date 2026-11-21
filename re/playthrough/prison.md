# Prison playthrough: CHAOS and TANKS

This file maps the main path from a new game to the level change that leaves the prison, and lists what the playthrough
harness found while driving it.
- The harness is `re/interp/playthrough_prison.py`; its tests are `re/interp/test_playthrough_prison.py`.
- Citations are `FILE.scr:LINE` in `re/out/scripts/`.
- Positions are world units from the level files (`GAMEDAT/CHAOS.IFF`, `TANKS.IFF`).
- Script coordinates (GO x y z, COORDZ) are these units >> 8.

## Where the prison ends

CHAOS has no exit except the hall elevator.
- TANKS is a side trip: it is entered by the cryo ladder and left by the hole into cell 2.
- The elevator panel (`ELEVATOR_MONITOR`, ELEVATOR.scr:750-895) offers three destinations with no script gate:
  - TOWER: `LOADLEVEL TOWER ELH ELT _sfx_5` (ELEVATOR.scr:53).
  - CONTROL: `LOADLEVEL CONTROL ELH ELC` (:293).
  - LANDPAD: `LOADLEVEL LANDPAD ELH ELV` (:386). LANDPAD leads to BEACH via `TO_BCH`, LANDPAD.scr:712-733.
- TOWER looks like the intended first stop (TOWER.scr:130, 214-237; the guard-room radio's lander story), but nothing enforces it.

## Main path

| # | Step | Mechanism | Harness |
|---|---|---|---|
| 1 | New game, wake in cell 3, beat the nurse robot into the bars, leave cell 3 in an off window | START.scr:25, AWAKEN.scr:83-231, AI_NURSE.scr:141-153, ZAP.scr:70-124, CHAOSBLK.scr:743-828 | `scenarios.nurse_defeat_run` (keys; logged attack poses) |
| 2 | Fight Caynan in cell 1 through the flickering cell-1 bars | AI_CAYNA.scr:31-169, 476-510; CHAOSBLK.scr:618-707 | `scenarios.chaos_caynan_fight` (keys, Easy) |
| 3 | Pick up the FORK in cell 1 (Enter): `LEX_FORK_TAKE` sets `_Lex_Has_Fork` | AI_LEX.scr:465-470 | keys |
| 4 | Leave cell 1 in a long off window. With the fork held, press Space at CELPAN: the panel swings open, and Space again opens the circuit board (CLP2). Press BT4, BT3, BT2, BT2, BT1 to go from (4,4,1,2) to (1,2,2,3); this wins and sets `_celpan_state = 4` | CHAOSBLK.scr:305-328; CHAOSMON.scr:92-332 | keys + mouse |
| 5 | Space at PRY_DR: `PRY_DR_USE` walks Lex to PRY_HERE and pries DR5 open (`_cel_door_state = 1`) | CHAOSBLK.scr:425-475 | keys |
| 6 | Enter the guard room: GRD_LOAD plays the radio crosstalk (log RADIOREF). At MONCL4 (Space facing east), press OFF so the cell-4 bars go off | CHAOSGRD.scr:3-33, 278-317; CHAOSMON.scr:375-386, 546-577 | keys + mouse |
| 7 | In cell 4, stow the fork (I), pick up DANELOG (Enter) and read it (Space): `DANELOG_USE`. Its entry 12 prints the 5-digit code that ASSIGNRANDOMIDS rolled | ITEMS.scr:748-756, 794-797; AWAKEN.scr:105; ASSIGNID.scr:10-14 | keys; the code is read off the monitor page |
| 8 | Pick up CAYARM (a right-hand item) in the corridor in front of cell 1 | AI_LEX.scr:431-436; ITEMS.scr:177-190 | keys |
| 9 | Drop the arm (Enter), drive USE_BOT from BOT_MON (MANB, then held UPDB / RTDB etc.) to the arm, grab it (CCDB: PICK_UP_RTHAND, the arm goes on UP_ARM, its MY_HAND), and park it at the reader. Then SEC_MON (Space facing west): ACCESS and the five digits. `CHECK_ACCESS_ID` sees CAYARM inside ARMHERE1 (z -6400..-4352) and sets `_caynan_security_id_ok = 1` | CHAOSMON.scr:45-75, 832-1238; ROBOCNTL.scr:7-530 | keys + mouse, earned |
| 10 | Open DR6: walk onto the floor panel CHANDQ with the bot holding the arm. The alternative is the palm reader GR_PALM (Space facing south, arm in the right hand; not driven) | CHAOSHAL.scr:97-109; CHAOSMON.scr:700-827; CHAOSGRD.scr:152-171 | keys |
| 11 | Hallway: get past the sentry HALMECHO unarmed. It reacts within 300 cm in front of it. Running, or walking twice after a warning, gets Lex shot. The alcoves HIDE_L / HIDE_R hide Lex | AI_MECHO.scr:17-61, 131-297; CHAOSHAL.scr:132-147 | keys up to the sentry's start; **getting past it staged** (`sentry-dodge`) |
| 12 | Cryo room: CRYO_BTN (Space facing west) opens the iris. TRIG_LDR (Space) starts DOWNLADDER, then TO_TANKS: `LOADLEVEL TANKS ENTR_TNK` | CHAOSCRY.scr:321-416; CRYTOTNK.scr:4-40, 121-204 | keys; the looping DOWN_LADDER lowers Lex by itself (1142 units per wrap, about 100 ticks) |
| 13 | TANKS: climb down to TO_CRYO and walk the catwalk south. TELETNK1/3 hop the camera gaps. GONER runs unless Fido and the scorpion are dead (side puzzle: wake Fido at the freezer monitor, KO him, drop him through the iris, pour cryo at TRN_VLV). Then go west onto TOCELL2 (a MANTLE_6 onto the CBLT / LTB ledge): TANKTOCELL2 does `LOADLEVEL CHAOS TNKS_ARV` + `CALL ENTERCELL2` | TANKS.scr:4-47, 125-180; TANKCHEW.scr:2-65; CRYTOTNK.scr:292-299; CHAOSCRY.scr:435-524; AI_FIDO.scr | keys; **the Fido puzzle staged** (`_Fido_and_Scorp_are_DEAD = 1`) |
| 14 | Cell 2: Guard 1 forces a fight. Afterwards pick up the BLASTER (495, -29827) | CHAOS.scr:144-182; AI_GRD1.scr:43-330; AI_LEX.scr:395 | ENTERCELL2 starts when the harness ends (Lex is unarmed there and dies: `scenarios.chaos_guard1_fight` is the fight); `playthrough_full.py` fights it on this run (`play=run`, seed 0) |
| 15 | Back through FM_TNKS (`LOADLEVEL TANKS FROMCELL`), walk north to TO_CRYO, Space (`LOADLEVEL CHAOS BTM_LDR`) | CHAOS.scr:184-196; CRYTOTNK.scr:206-256, 301-309 | `playthrough_full.py` |
| 16 | Shoot HALMECHO (6 hits, not 2: 125 HP, 1 per hit above 120, then DAMAGE 666) or avoid it. DR7_BTN opens the elevator; ELEV2_H1 opens the panel; pick a destination | AI_MECHO.scr:97-114; CHAOSHAL.scr:59-94; CHAOSMON.scr:6-30; ELEVATOR.scr | `playthrough_full.py` (sentry paused, the ELMN monitor clicked for real) |

## How far the harness gets

**Passing, deterministic:** every segment, new game through the TANKS catwalk and back into cell 2: the nurse, Caynan, fork, circuit board, DR5, cell-4 bars, Dane's code, Caynan's arm, the bot carrying the arm to the reader, the security terminal (earned: it answers GSECPASS), DR6 by CHANDQ, the hallway (the sentry's AI runs; getting past it staged), the cryo iris, the ladder down to TANKS by DOWN_LADDER alone, the whole catwalk, the MANTLE_6 onto the ledge and TOCELL2's `LOADLEVEL CHAOS TNKS_ARV` (tick 33058, Lex at 76 HP).
- Every segment is a test in `test_playthrough_prison.Segments`; the run takes about 50 s.
- Before the movement fixes ("Movement fixes" in NOTES) the harness stopped at the catwalk's south end (27113, -185981) and staged the ladder (both ends) and a blocked GO. It now gets about 3700 ticks (the ladder, 21000 units tall) and the catwalk further.
- Since the room events and the default AI (NOTES) it needs no `room-events` or `halmecho-inert` shortcut: it plays the same stretch with real GRD_LOAD, HAL_LOAD, CRY_LOAD and a live sentry. The sentry is not passed by play, so this moves no stop further.
- It ends where the Guard 1 fight begins; Lex has no blaster and no keys then, so the run ends with him dead after `ENTERCELL2` (not a finding).

> The full run (`re/interp/playthrough_full.py`, `re/playthrough/full.md`) continues this stretch in the same World / VM; it takes the segment functions of this harness on the running world.

## Blockers, ranked by how much they block play

This list was found on `main` 8df4e21 and rechecked after rebasing onto 6db5813 (PR #16) and after merging 74bfd6e (PR #17).
- PR #16 resolved blocker 1: the caller now survives its LOADLEVEL, so TO_TANKS runs its tail itself.
- PR #16 also fixed the CURFIG / CURITEM selector swap (`10c0:24e1`), so GONER now reads `CURFIG.~0 = 1`: Lex goes to 1 HP, as described below.
- Lex's HP after the Caynan fight depends on the RANDOM stream: in a playthrough the fight is not seeded, and only the scenario on its own uses `scenarios.CAYNAN_SEED`. If the harness's dash out of cell 1 comes late in the bars' off window, a shock costs him HP. That is logged as a minor harness problem; the current run is not shocked.
- PR #17 resolved the old blocker "GO to an IMAG uses the box's low corner" (now item 7). It also exposed a new one, the GO arrival (item 8).
- The sentry's harmless shots (item 11) were not rechecked.

1. **Resolved by PR #16.** **LOADLEVEL ended its caller in the ports** (`World.cmd_loadlevel` / `vm.kill_level_owned`, an ASSUMPTION from TUNROOM.scr:160).
   - LOADLEVEL (`10d0:4d46`) kills the class-0x10c processes (`FUN_1230_1182(0, 0x10c)`) and otherwise returns 0. So the caller continues unless it is itself in that class. Unresolved.
   - TO_TANKS, TO_CRYO_USE, TANKTOCELL2 and CELL2TOTANK (CRYTOTNK.scr) all need the statements after their LOADLEVEL: GRAVITY ON, AI ON, `CALL ENTERCELL2`, `CALL ENTERFROMCELL`.
   - Without them, every trip into or out of TANKS strands Lex. The Guard 1 scenario and this harness both stage around it.
   - Next step: find the class of a script process started by PROCESS / CALL / a trigger, and which classes `FUN_1230_1182(0, 0x10c)` returns.
2. **Resolved (NOTES "Room events and the default AI").** **No default AI.** HALMECHO's record has AI name HALMECHO and counter 0; the ports kept their own "AI off until AI ON". It now starts on the first hallway camera, walks, spots Lex and fires.
   - Still open: **the unarmed way past it.** It walks about 65 units a tick (Lex runs about 100), so a run from DR6 for the elevator vestibule is spotted about 500 units short, and running on under fire killed Lex. Solved since (`re/NOTES.md` "The hall sentry and the tower bots"): once it has spotted Lex it fires only at a walk, run, ATK_M2 or ATK_M8, so Lex sidesteps the hall (`Run.sneak`); `sentry-dodge` is gone.
3. **Resolved (same section).** **Room-level events missing.** GRD_LOAD, HAL_LOAD and the rest run from the engine's camera switch; the `room-events` shim is gone.
4. **Resolved by "Items and combat" (NOTES).** **AMINTRIGGER on items was always 0.** Items now have a hull from EXTENT at their position, a held item's box following the holder's limb (`10f0:1209`, `1078:08f6`), and an attach falls back to the holder's MY_HAND (`1138:088d`).
   - The clearance is earned with the bot, as the scripts intend. Not checked against the original: the UP_ARM end height at the reader (the tip lands at z about -4985), and the drop from the bot (COPB).
5. **Resolved by the movement fixes.** **Ladders: a looping motion's root z never moved the figure.**
   - DOWNLADDER waits for `COORDZ(CURFIG) <= -55`, and TO_TANKS for `DISTFROMTRIGGER CURFIG TO_CRYO <= 105`, while DOWN_LADDER / CLIMB_UP loop.
   - At each loop wrap a flag-2 motion adds its last frame's root z to the figure (`1088:1286`): -1142 units per DOWN_LADDER wrap. The harness no longer places Lex.
6. **Resolved by the movement fixes.** **The catwalk's south end did not lead up to TOCELL2.**
   - TOCELL2 (19208..20744, -187655..-183815) lies at z -20992..-18432, about 3500 above the catwalk floor (Lex's feet at -24309), behind PHYS DTH1, CBLT and LTB.
   - The ledge CBLT / LTB (flag 0x02, 2838 above the floor) is a mantle: the key handler requests MANTLE_6 for a WALK (not a RUN) with the hull inside the ledge's width shrunk by 0x266; the climb's root z is committed and the mover lets the hull through (+0x1e8). The harness walks it along y -186300.
   - Needed removing the port-only LAND_REVERT clause (E): FS1-FS3 (POSITIVE, raised by TANKS_LOAD when Fido and the scorpion are dead) stood in the catwalk's way.
7. **Resolved by PR #17.** **GO to an IMAG used the box's low corner.**
   - `GO TELETNK4` (TANKS.scr:137-165) teleported Lex to (25777, -149103, z -25344), off the catwalk's west edge, and he dropped to the tank floor.
   - PR #17 sends `GO <trigger>` to the box centre (`10d0:33c8`, vtable +0x50).
8. **Resolved by the movement fixes.** **A script GO whose target put the hull into a wall never arrived.**
   - `GO PRY_HERE` (PRY_DR_USE, CHAOSBLK.scr:431) aims at the box centre (7330, -21427), 76 units into the closed DR5 for Lex's hull.
   - A GO ends once `length2d(target - pos) < radius` (`10e0:1a4c`; 614 by default, `1098:11c0`) and does not snap; PRY_DR_USE no longer waits forever. The `go-arrival` shortcut is gone.
9. **GONER's toss is a scripted death, not a port gap.**
   - With Fido and the scorpion alive (`_Fido_and_Scorp_are_DEAD == 0`) GONER sets Lex to 1 HP and FIRE TOSSes him to TOSSHERE (40448, -50931, -15471); TANKDETH kills him there. The earlier note that the ports find no floor under TOSSHERE does not change that.
   - The clean route (the Fido / cryo-pour puzzle) works since the LAND_REVERT clause is gone; the harness stages only its result (shortcut `fido-puzzle`).
10. **Turning moves Lex sideways.**
   - A 9-tick turn hold moves him about 180 units, a 15-tick hold about 250, so precise positioning by keys spirals.
   - It is not a blocker for a human player, but it is wrong-looking until checked against the original's turn_left / turn_right root data.
   - The harness works around it with short taps (`Run.fine_face`, `Run.approach`).
11. Minor:
   - `BREAK n` warnings (CAYNAN_PACE, XLOG, PALMREADER, GR_CELLMONITOR): the known BREAK-n assumption.
   - The sentry's bolts do hurt: 46 HP a hit in the run-past try (Lex 69 -> 23 -> dead). The rate and damage are not checked against the original.

## Fixed here (both ports, twin tests in `test_playthrough_prison.PlayerInput` / `PlaythroughTests.swift`)

- **Space returns once a USE block starts.**
  - The original's Space case returns as soon as a block starts (`10a8:1113..`).
  - Before: the port went on to request STAND in the same input pass, which replaced the block's `GO … WALK`. Lex kept the GO target but never moved, and `PRY_DR_USE` hung forever.
  - Fixed in parallel by PR #16, which returns when the block's first slice took Lex with a GO or AI. The rebase keeps #16's version.
  - Open: whether a block that only starts a MOTION should also suppress the STAND request. The original returns for any started block.
- **FREEZE'd and unwaited script motions yield to a fresh key press.**
  - Only a press counts, since the original requests motions on key-down events (FUN_10a8_0541). A key still held from before does not count; otherwise the opening's held Up would cut through BLOCK_DRIP's DRIPPED_ON.
  - This also unblocks the surface stretch: after THE_DIGTUBE's `MOTION ENTER_GRAV FREEZE` (TUNROOM), Up now walks Lex. `test_playthrough_surface` was updated to expect `walk-after-tube` to pass.
  - The key motion gate (vtable +0x8c = `1098:12bd`) refuses only during RECOIL, DIE and SUPER_REC. It stops any other motion for the key's motion and tests neither freeze nor the end of the motion.
  - Before: `MOTION LOOK_AT_MON FREEZE` (every monitor) and CRYO_BTN_USE's looping `PUSH_BUTTON CONTINUE` locked Lex's keys for good.
  - ASSUMPTION kept: a MOTION a script blocks on stays the script's until it ends.
- **Held-item USE blocks use the item instance name** (+0xf7), then the type: `"%s_%s_USE"` (DS:0x2bf9, 10a8:16d0-16f1) and `"%s_USE"` (DS:0x2bfc, 10a8:17f0-1803). DANELOG and CAYLOG (both LOGBOOKs) now run their own `_USE` blocks.
  - The port's extra `<type>_<object>_USE` form (not in the original) is unchanged.

## Staged shortcuts (each is a gap to close; `playthrough_prison.SHORTCUTS`)

| Name | What | Why |
|---|---|---|
| `nurse-poses` | the nurse fight's front/rear attack poses | inherited from `scenarios.nurse_defeat_run` |
| `difficulty-easy` | `_difficulty_level = 0` for the Caynan fight | the scripted punch loop wins only at Easy |
| `loadlevel-caller` | TO_TANKS' tail performed by the harness; no longer used after PR #16 (the code path remains for a pre-#16 port) | blocker 1 (resolved) |
| `fido-puzzle` | `_Fido_and_Scorp_are_DEAD = 1` before the TANKS load (the puzzle is not played) | blocker 9; replaces `goner-skipped` |

Removed by the movement fixes: `ladder-descent` (both placements) and `go-arrival`; `goner-skipped` became `fido-puzzle`. Removed by "Items and combat": `arm-at-reader`. Removed by the room events and default AI: `room-events`; `halmecho-inert` became `sentry-dodge`.

## Other observations

- The first guard-room entry: GRD_LOAD runs RADIO_CROSSTALK.
- Lex starts a new game without the MEAT / LEXLOG items that VARS-era notes put in his inventory: they lie on the cell-3 floor (MEAT at (-11508, -12965), LEXLOG at (-11424, -10678)). Not checked against the original.
- Camera monitors switch the real camera (`CAMERA CE41` in GR_CELLMONITOR), so room events fire while Lex sits at a monitor. The original does the same if 1130:0114 runs on every camera change.
