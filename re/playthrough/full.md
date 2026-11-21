# Full playthrough: a new game to `EXIT`

`re/interp/playthrough_full.py` drives the Python port from `scenarios.boot_opening` to ENDGAME's `EXIT` in **one World / VM**: 136095 ticks,
about 2 minutes of wall time (4 under load) (`re/.venv/bin/python -I -W ignore re/interp/playthrough_full.py [--out DIR] [--stop-after LEG] [--seed N] [--difficulty easy|medium|hard]`, report
`re/out/playthrough/playthrough_full.json`). Tests: `re/interp/test_playthrough_full.py` (one shared run, about 2 minutes, plus fast unit tests).
Citations are `FILE.scr:LINE` in `re/out/scripts/`, engine addresses in `NOTES.md` style.

**How far it gets: all of it.** Every leg passes, `World.exit_requested` is set by `LEAVEGAME` in the TITLE level, Lex has 72 HP. Lex, the
inventory, the globals, HP, moved floors and figure state really carry from level to level: no leg creates Lex, seeds a global or an item, or places him
at an arrival to stand in for earlier play. What it still stands in for is the shortcut list below (16 kinds, 34 uses): fights the keys cannot win
and a few walks and engine gaps (the ranked blockers).

## The route (as played, with the scripts behind it)

The segment functions of `playthrough_prison`, `playthrough_surface` and `playthrough_base` are reused: they take the run that is already going
(`Segment(outer=run)`, `playthrough_base.Run.attached`, `playthrough_prison.start(run_class=)`) and skip everything that created or seeded a world.

| Leg | What happens | Script |
|---|---|---|
| prison (`playthrough_prison.play`) | nurse, Caynan, fork, circuit board, DR5, cell-4 bars, Dane's code, the arm, the bot at the reader, security terminal, DR6, hall (sentry passed by sidesteps), cryo iris, ladder, TANKS catwalk, mantle onto TOCELL2 | prison.md |
| `guard1` | TOCELL2's `TANKTOCELL2` starts `ENTERCELL2` itself; Guard 1 fought at Easy with the routine's ATK_H4, no seed (`scenarios.chaos_guard1_fight(play=run)`): Lex ends with **60 HP**, and has the same at the BLASTER | CHAOS.scr:144-182, AI_GRD1.scr |
| `blaster` | Enter on the BLASTER at (495, -29827) | AI_LEX.scr:395 |
| `bio-repair` | **D, BRSB**: BIOREPAIR (+2 HP per 8 ticks for 1 battery energy while MY_BATTERY holds 10) takes Lex from 60 to 100 HP; MEDICAID and ZEDICAID heal 20 HP a charge, 5 charges each (ITEMS.scr:652-656, `re/NOTES.md` "Item charges") | PIMM.scr:441-505 |
| `tanks-back` | the hole under TNKS_ARV (`FM_TNKS`), the catwalk north, Space at TO_CRYO (`TO_CRYO_USE`), ladder up, `LOADLEVEL CHAOS BTM_LDR` | CHAOS.scr:184-196, CRYTOTNK.scr:206-309 |
| `hall-to-elevator` | down the hall (a run past the sentry to the vestibule), DR7_BTN, the cabin, **the real ELMN elevator monitor** (pointer click on TOWB) | CHAOSHAL.scr:59-94, CHAOSMON.scr:6-30, ELEVATOR.scr:750-895 |
| `battle-room` | after `tunroom`: Drogg 3, beaten with ATK_F9, keeping off the glass panes THOLE1 and THOLE2 (PLATFORM.scr:200-321); REFLECT picked up; mirror suit on through PLTDOOR, off in the square | AI_DROG3.scr, ITEMS.scr:1477-1545 |
| `tower` / `tower-exit` | across the deck, both landers with the gun keys, the way back, TDR_BUT, CONB | TOWER.scr, TOWERGUN.scr; base.md |
| `operating-room` | CNT_BTN1, DR13, OPENTER: OPRSCENE to `_Operate_Done = 1` (Lex's BLASTER is destroyed there, MASTABA.scr:277-283) | CONOPER.scr:111-135, MASTABA.scr:3-32, 262-330 |
| `hardsuit` | CNT_BTN3, DR14, the stairs of the control room, SUITTEST: HARDSUITMACHINE (GRDCON's hits until the machine runs depend on the RANDOM stream: Lex ends the leg on 52 on this run; 6-37 HP with other Guard 1 seeds) | CONCNTRL.scr:2-22, 71-139, AI_GRDCN.scr |
| `grdcon` / `grdhall` | GRDCON beaten in the suit straight after the machine. After `garage-up`, GRDHALL in the hall for BLASTER2 (he stays peaceful with the suit on until hit); CNT_BTN3 again, as DR14 has closed | AI_GRDCN.scr, AI_GRDHL.scr:65-127 |
| `garage-block` / `garage-up` | the hangar monitor (**real clicks**, AIAB), the lift down, the bike's battery into Lex's leg and his old one into the bike (BIKE_USE, ABAT_500_USE), a repair to 100, BLOCK (Enter), TAKEMEUP raises the lift | CONCNTRL.scr:208-385, CONMACH.scr:288-519 |
| `forklift` | FORKMON1, **real clicks**: MANUAL, then CR_BOT driven by the MLBT buttons out of the control room, along the hall and through the airlock, whose doors and decontamination run for it, into RAM_BOT: robot and REACTBOT die | CONTROL.scr:70, ROBOCNTL.scr, CONREACT.scr:32-125 |
| `reactor-room` | CNT_BTN2 (Lex has to reach the door before it has opened, or CONDR2AUTOCLOSE shuts it), the airlock, BRDG_BUT | CONREACT.scr:149-253, 344-358, BRIDGE.scr:2-60 |
| `drogg1` | across the bridge (CONLOC10 starts the 90-second timer); six super recoils with ATK_H4, 27 HP; back at a run with Drogg 1 following; BRDG_BUT retracts the bridge under him | AI_DROG1.scr |
| `reactor-shutdown` | bridge back on, both levers, RTR_MON: the three ID buttons (read from `_reactor_id_number`, which the REACTO text shows; the harness does not go and look), POWER DOWN; back out through the airlock | AI_DROG1.scr:508-575, SHUTDOWN.scr:100-130 |
| `temple-monitor`, `temple` | the tube monitor's temple code, TMPL_MON: open, crush Marine 1 as he peers in, open again; Marine 2's grenade thrown back along the tube kills him; then TO_TMPL in the mirror suit and north to TO_BCH | TUNMON.scr, TEMPLE.scr, TUBES.scr |
| `beach-climb` | BIOREPAIR, then the block mantles, ZIP8 and ZIP7 the other way, the ledge CT1 and CT2 to TO_PAD; MARINE2 and MARINE3A do not stop a mirrored Lex | BEACHZIP.scr, BEACH.scr:208-218 |
| `landpad-to-elevator` | the ledge north, running and stopping for the dropship's bolts; SHIP_GO; JET_BUT2 and PAD_DOWN; Marine 4 fought with Alt+KP4; AIRLCK and the keypad's after-the-city rule; DRB_STRT, decontamination, AIR_DOOR, ELV_LND1 | LEDGE.scr, LANDPAD.scr, LANDMON.scr |
| `to-landpad` | the cabin door (CTRELVDR), ELV_C21, **real click on AIRB** | CONTROL.scr:178-190, ELEVATOR.scr:326-430 |
| `landpad` ... `tunroom` | `playthrough_surface` on the run: mech, airlock grid, decontamination, jetson tube, ledge, BEACH (zips, warhead, blast door, suit machine), the Captain's TONFA, DIGSITE (key from `GETKEY`, the gun picked up again at the tomb), `DIGTUBE_KEY_USE`, TUNROOM, zero-g tube, `TO_FINAL` (flown) | surface.md |
| `platform` | the city monitor (solved), the city scene, the Elite's talk and gift: `ABAT_500` in the right hand, 500 / 500 / type 3 / alien 1; then wait for PLAYER_MIND_MELD's `AI ON`; Space puts the battery in Lex's leg, the old one stays on the floor, and he takes the gun again | base.md "PLATFORM", AI_ELITE.scr:124-322 |
| `platform-exit` | TO_ZEROG: `LOADLEVEL TUNROOM GFROMFIN` | TUN2PLAT.scr:22-40 |
| `zero-g-back` | the marines' speech (MARINESENTERTEMPLE), the suit off (Space), the flight to TO_TUNRM, the suit on again; TO_TUNRM: `ENTERTUBEROOM 1`, `GO FRMZEROG`, `AI ON` | TEMPLE.scr:48-90, TUNZEROG.scr:90-105, TUBES.scr:236-290 |
| `grav-ring` | `TO_GRAV_USE` (needs `_TubesOpen` bit 3), GRV_LOAD, pads RING3 / 6 / 1 / 3, `_Grav_Solved`, ACID_VIEW | TUNROOM.scr:151-166, TUNGRAV.scr:3-185, 228-350 |
| `to-beach` / `beach-to-landpad` / `landpad-to-elevator` | TO_TUN, TO_BCH (`LOADLEVEL BEACH FROM_TPL`), TO_PAD (`LOADLEVEL LANDPAD FROM_BCH`), ELV_LND1, **real click on CONB** | TUNROOM.scr:215-226, BEACH.scr:208-218, ELEVATOR.scr |
| `control-second`, `ending` | hall, CNT_BTN3, the hangar monitor and lift, the bike with both batteries (`_Grav_Solved` lets the alien one in), `OUTAHERE_USE`, ENDGAME, ROLLCREDITS, Esc: LEAVEGAME, `EXIT` | CONMACH.scr:8-220, ENDGAME.scr |

**Order differs from the brief in one place, on purpose: TOWER before CONTROL.** OPRSCENE ends with `READY_MARINE1` (MASTABA.scr:322), which stands Marine 1
in the hall holding M1TONFA while the first lander lives (AI_MRN1.scr:1-30); the trigger TMRN1 (x 7497..14409, y -68791..-67127) lies directly across the exit of the operating room
(DR13 spans x 8122..13767) and does 500 damage (AI_MRN1.scr:36-62): walking out of the operating room is death. The first lander dies at the tower gun
(`_FirstLanderAlive = 0`), so the tower comes first. The brief's other sequence points hold (CHAOS - TOWER - CONTROL - LANDPAD - BEACH - DIGSITE - TUNROOM - PLATFORM - TUNROOM -
BEACH - LANDPAD - CONTROL - ENDGAME).

## Shortcuts (`SHORTCUTS` in playthrough_full.py; the prison, base and surface ones keep their names, the surface harness's staged items are `surface-<kind>`)

Real engine gaps (the run would not go on without them; each one has a ranked blocker below):

| Shortcut | Uses | What it stands in for |
|---|---|---|

Harness limits (fights the keys do not win, `set_pos` next to a trigger):

`nurse-poses`, `difficulty-easy`, `difficulty` (Medium or Hard only: the level is set after the prison), `fido-puzzle` (the tower bots are shot, `playthrough_full.tower_bots`; GRDHANG is fought at the foot of the lift, MARINE5 in the mirror suit),
`ring-pads` (4 `set_pos`
onto the pads), `set-pos` (5: the hangar monitor twice, the ring platform, TO_TUN, ...; one more, down the BEACH blocks, on a stream whose battery is too weak for the bike and makes the trip back to the platform), `surface-set_pos` (8: LEXSTUK, the zip walks and climbs, the bomb carry, the escape, there and back
between the tunnel and the lander for the gun, TO_0G), `surface-global` (`_Drogg2_Alive`). Every zero-g crossing is flown: entered by TO_0G_USE Lex floats at
z -5539, as in the original (re/NOTES.md "Lex's height in the zero-g room"). The tomb, city and tube monitors are clicked (`TOMB_PRESSES`, `CITY_PRESSES`, `tube_monitor`), and Lex walks from the suit machine to the tomb and on to the dig tube.
**Gone compared with the segment harnesses:** `player`, `item`, `form` (HARD comes from the machine), the BLASTER / BLOCK / alien battery seeds, `elevator-button`
(every ride is a click on the ELMN monitor), the staged hangar monitor tail (the click is real), and the globals `_alien_city_seen`, `_Grav_Solved`, `_gave_alien_battery`, `_escher_dead`
(the city scene, the Elite and the ring puzzle set them).

## Blockers, ranked by how much they block real play

1. **The weapon for the zero-g room rests on a staged fight.** The run now also wins BLASTER2 (`grdhall`), but the TONFA still flies the zero-g room. OPRSCENE destroys every BLASTER (MASTABA.scr:277-283). Two guns remain before the first crossing: BLASTER2, which GRDHALL carries once GRDCON is dead
   (AI_GRDHL.scr:18-37, 332-350), and the TONFA of the Captain on the BEACH lander (TUMOLT, AI_TUMLT.scr:380-410). The run fights him by keys (`playthrough_surface.captain_fight`, `re/NOTES.md` "The Captain by keys, won") and takes the TONFA he drops.
   while his bolts take 50 of Lex's 84 a hit. He does not move until Lex has crossed RTMLT1 and comes back over RTMLT2, on the lander's floor. The gun overheats after six shots (TONFA_FIRE, ITEMS.scr:1132-1205); that window has not been tried.
   A later weapon also exists: the PFD arm gun (`LEX_ATK_SHOOT`, AI_LEX.scr:220-233; journal ALWEP / ALWEP2), which needs a battery of capacity 375 or more (PIMM.scr:267), so only after the Elite's alien battery.
   M1TONFA is not a route: with the first lander dead Marine 1 is never readied and the item lies at (18628, -83447, -7186) with no floor under it; with the lander alive TMRN1 kills Lex at the operating room's exit.
2. **Engine, fixed here: LINKMETOCAMERAS did nothing.** A camera switch now pauses every linked process unless the new camera is in its list (`re/NOTES.md`, "Camera-linked processes", checked live). ZEROG_TURNING, ZEROG_GRAVITY and ZEROG_ROOM stand still outside ZEG1-4, so the shortcut `camera-linked-processes` is gone. The fights were retuned, because the paused processes no longer draw RANDOM: `CAYNAN_SEED` 29, `GUARD1_SEED` 20, `GUARD1_SEED_FULL` 28.
3. **Engine, fixed here: Lex could not leave the garage-lift recess.** The Q pass's fit test counted only solids; it is `FUN_1058_1a1b`'s collision score (`re/NOTES.md`, "Garage recess and the ladder top"). He now climbs QST3, QST2 and QST1 himself.
4. **Engine, fixed here: the ladder up out of TANKS ended in a fall.** A motion's first update moves by frame 0's root, which the ports did not do (`re/NOTES.md`, same section). Since `COORDZ` includes the root height (`re/NOTES.md`, "The 40 units"), CLIMB_UP stops mid-cycle and `MANTLE_6` leaves him at (-12269, -74431). Played in the original since (`re/NOTES.md`, "The ladder through the iris"): the arrivals, the stop's cycle and the lift onto the floor now match; he lands about 135 units west and south of that in the original, and the port's one whoah frame does not happen there. The route walks west off the edge, then round the south side of the hatch.
5. **Engine, fixed here: the garage lift's trigger list was empty** (below).
6. **The Guard 1 fight no longer has a seed** (`re/NOTES.md` "The fighting routine"; the numbers in this entry and the HP in the tables above may predate it). Before root moves rounded down, of seeds 0-39 the ATK_H8 loop that also reaches the BLASTER left the most HP at seed 28 (Lex 60, not re-swept since); seeds 13, 14, 25, 32 and 33 win, but the BLASTER pick-up then fails (not traced). The numbers for GRDCON and GRDHALL below predate the frame 0 root fix and were not rerun. Without BIOREPAIR (D, BRSB) the first bolt in CONTROL (46) kills him
   in the elevator. Healing exists and works; nothing tells the player to use it. GRDCON (180 HP) was tried with 10 attack loops on 6 seeds each: unarmored at Easy 3 wins of 60 (Lex left with 30, 12, 12 HP), at Medium and Hard none of 120; in the hard suit (armour 5, Lex arrives with 40 HP) none of 90. GRDHALL (220 HP) then appears, friendly to the suit: from the best GRDCON win (Lex 30 HP, HARD, Easy) 12 fights lost with him at 160-200 HP, so BLASTER2 was not reached. GRDHANG and MARINE5 are untried; the loops only punch, with no blocks or retreats, and the original has not been compared.
7. **The sentry HALMECHO is passed by play now** (`re/NOTES.md` "The hall sentry and the tower bots": the first pass sidesteps past it, the second outruns it to the vestibule). Earlier: (it spots Lex at about 5800 units (live: 6059-6292), freezes, warns twice for a step and shoots at the third or at a run; the blaster needs 6 hits at 1 HP each and every hit makes it fire) and
   MECHO2 no longer hurts Lex in CONTROL's elevator: he runs to the cabin's north corner (CMECHZA) before the door opens and shoots it from there.
   Since the item events moved a frame earlier (2026-11-18, `re/NOTES.md` "Motion sound cues and formatted sound names") its bolts leave sooner: he runs
   east along y -67800 (the cabin's inner wall at x -39900 stops him further north), then into the corner (below).
   The LANDPAD ledge's bots (LDGBOT1-3 at x 30848) now land their bolts on a Lex who runs at x 25700, and each hit restarts his recoil so the next
   lands too: `ledge_run` runs from his arrival straight down the ledge's west side, x 23800, and takes no hit on the default stream.
   `battery_trip` still ran the ledge at x 25700, stopping at each point; the bots shot Lex to death on it (the stop after the `reactor-room` save
   and the `forklift` restart, traced 2026-11-21). It runs `ledge_run` now too. After CONTROL's ride
   Lex `dash`es (Shift+Up held, steering on the run) into CMECHZA's middle at once: turning east in place first (some 65 ticks) had him meet the first
   bolt at x -41500 in every stream (46 HP), and a stop to turn, `goto`'s walked last stretch or a bolt at the strip's south edge (it knocks him back into
   CMECH1A) let the next bolt land. GRDHANG shoots too (ATK_SHOOT / SHOOT carry 0xf0): `GRDHANG_PUNCH` is 3 ticks between
   blows there (2 lost 5 of 27 streams up to that fight, 1 and 3 lose 3). Since a woken waiter runs in the next scheduler walk (2026-11-20) Guard 1 is fought
   with BIOREPAIR from 50 HP (`GUARD1_HEAL_BELOW`; at 35 two of 12 reseeded draws from seed 17's start died with a full battery) and the Captain is only
   walked up to from beyond REACH + 3000 (`CAPTAIN_STEP_IN`; 24 of 24 reseeded draws from the full run's fight, 2000 lost the full run's own). Drogg 3 is
   fought 1800 units clear of the glass (`BATTLE_ROOM_AVOID_MARGIN`: at 1200 an ATK_M8 lunge carried Lex onto it in a control restart), and at the reactor
   console Lex waits out a LEVEL1TREMORS quake that takes his turn and dash, then goes again. Since an idle requested in a walk starts in the next one
   (2026-11-21) the streams shift again, and three steps were made sturdier, unchanged on streams they already passed: `pick_up` waits
   out a quake that takes its Enter press and approaches again; after the Guard 1 fight Lex goes back to cell 2 whenever he is in TANKS,
   also when the walk round the hole drops him through it; and when the Captain's TONFA cannot be picked up from the ramp (it can
   land 2200 units lower), the last press's KEYDVICE is stowed and `take` walks round to the gun. The default stream's leg battery covers BIKE_NEEDS at the
   bike, so there is no battery trip.
8. Known warnings only: `BREAK n` (CAYNAN_PACE, XLOG, LUTHOR_ATTACK, ELEVATOR_MONITOR, SWITCHTOCONTROLLEVEL / SWITCHTOLANDINGLEVEL, TMP_MAR_2_AI, RESTOREALIASOFBATTERY, FLUFFY_SFX3). No unmodelled call.

## What did not carry over between levels

Nothing that the scripts carry failed to carry: Lex's HP, FORK / DANELOG / MY_BATTERY, BLOCK (LTHAND, then INVENTORY after the zips), KEY, the Elite's `ABAT_500` (500 / 500 / type 3 / alien 1), `_alien_city_seen`, `_Grav_Solved`
and the garage lift all arrive where the next stretch needs them. Findings from the lack of a state the next stretch needs:
- `_Reactor_Safe` is only set by the reactor puzzle (SHUTDOWN.scr:113), which nothing before the ledge makes you play: the ledge QUAKER is lethal without it (LEDGE.scr:44-67). The run plays the puzzle first (`re/NOTES.md`, "The reactor puzzle"); a player who goes to LANDPAD first has to come back.
- `PLAYER_MIND_MELD` (AI_ELITE.scr:310-322) is still in its last MIND_MELD2 loop when the Elite has gone; a LOADLEVEL before its `AI ON` ends the process (class 0x10c) and **Lex's AI stays off for good**
  (`hold` 1: no keys work). A player who leaves within two seconds of the gift would be stuck; the harness waits.
- The dig-tube KEY stays in the left hand to the end; BIKE_USE puts it on the floor beside the batteries, where the nearest-item pick-up chooses it over the battery. The harness stows it with I.
- `ENTERTUBEROOM` and `TO_TUNRM` need the keys' directions to be right: with AI off or `ZEROG_*` running (on a ZEG camera), forward keys walk the wrong way.

## Medium and Hard (`--difficulty`, 2026-11-20)

The prison is played at Easy (`difficulty-easy`) and the level is set after `guard1` (shortcut `difficulty`). Above Easy the fighting routine
keeps a quicker rhythm and repairs earlier, the tower bots are reached by a curved dash, and Lex steps forward before a big turn on the BEACH
zip blocks; `re/NOTES.md` "Medium and Hard played through" has the details and the benches.

**How far it gets** (`run_seeds.py --difficulty ... --seeds 26`): **Medium 1 of 27** streams finish (the default stream, Lex 100 at the end);
the others die to GRDCON (11), GRDHANG (12) or GRDHALL (2), and seed 4 stops in the prison as at Easy. **Hard 0 of 27**: Lex dies on the tower
deck. The blockers, in order: the battery runs out across GRDCON, GRDHANG and GRDHALL (GRDHALL alone takes 114 of the bike's 129); Lex
reaches the BEACH with 13, so the Captain wins most streams there (1 of 6 in a bench); Hard's tower bots. Other attacks, blocking, repair
thresholds and mid-fight medkits did not help: these fights need a routine that reacts to the guard.

## Engine fix made here (both ports)

**Area trigger lists are built with the level** (`World.area_triggers`, `World.areaTriggers`; RoomType->triggers, `FUN_1138_131c`). The lists were built on the first query. The garage
lift's first query came while LOWER_GARAGE_ELEVATOR had raised ELV to -633 (box z -162048..-146988, no longer touching TAKEMEUP, z -165153..-164129): the list stayed empty,
TAKEMEUP never fired and the lift never came back. The decompile backs this: `FUN_1138_1853`, which builds the area records, has three call sites (`1148.c:888`, `1068.c:629`, `1068.c:691`), none in the SETFLOOROFPHYS handler; not checked live. Twin tests: `test_floors.AreaTriggers` /
`FloorsTests.aMovedAnchorKeepsTheTriggersItTouchedAtLoad` (ELV after `SETFLOOROFPHYS ELV -633` keeps CAM_SHO5 x3, CAM_SHO1, TAKEMEUP, MSENTER).
Harness changes that other tests see: `playthrough_prison.Run.goto` stops when a trigger on the way loaded another level (the prison run no longer walks into cell 2 and dies after TOCELL2);
`scenarios.chaos_guard1_fight(play=, seed=)` can continue a run; `playthrough_base.tower` / `platform` / `ending` are split (`tower_deck`, `platform_city`, `ending_bike`) and `Run.attached` joins a run; the BEACH walk to ZIP1_A goes through three waypoints
(the ledge is narrow) and falls back to a logged `set_pos` when the walk to a zip start drifts; the DIGSITE segment runs `GETKEY` instead of creating the KEY.
