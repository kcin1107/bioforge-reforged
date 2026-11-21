# Surface playthrough: LANDPAD, BEACH, DIGSITE, TUNROOM

Route map from the shipped scripts (`re/out/scripts/*.scr`, `game/app/Bioforge/SCRIPT/*.LVL`, `VARS.DEF`) and what the harness
`re/interp/playthrough_surface.py` finds when it drives that route. Regression tests: `re/interp/test_playthrough_surface.py`.

## 1. How the game reaches the surface

- No prison script loads BEACH. The surface starts at **LANDPAD**, by the elevator: the CHAOS elevator monitor's `AIRB` button runs
  `PROCESS SWITCHTOLANDINGLEVEL` (ELEVATOR.scr:829-881), which sets `_landpad = 1` (:342) and runs
  `LOADLEVEL LANDPAD ELH ELV _sfx_5` from CHAOS (:386; TOWER `ELT ELV` :373, CONTROL `ELC ELV` :409). After the load the same process
  opens the cabin (`EXITSTASIS`, `ELEVATOR_DOOR_OPEN`, `_dr9_SPACE = _NEGATIVE`, :419-430).
- The surface needs things only the base levels give, so the story visits CONTROL before the pad:
  - **HARD suit**: the LANDPAD airlock chokes Lex unless `ISMYFORM (HARD)` or `LEXMIR` (LANDPAD.scr:221-239). The suit comes from
    the CONTROL machine (CONCNTRL.scr:100-130: `CHANGEMYFORM HARD`, `ADDLOGENTRY LEX HARDSUIT`). REFLECT (LEXMIR) is a PLATFORM item.
  - **`_Reactor_Safe`**: `QUAKER` on the ledge knocks Lex into the acid unless it is set (LEDGE.scr:44-67); only CONTROL's reactor
    shutdown sets it (SHUTDOWN.scr:113).
  - **BLOCK** (the artifact, a CONTROL level item): every BEACH zip line is `<trigger>_BLOCK_USE` (BEACHZIP.scr:48-150), i.e. Space with
    BLOCK held (it is a LTHAND item, ITEMS.scr:149-160).
  - **A weapon**: AIRMECHO dies only through `LASER_HIT_AIRMECHO` (AI_AMECH.scr:126-137); the CHAOS BLASTER.
- VARS.DEF defaults the surface reads: `_alien_city_seen` 0 (:629; set only in PLATFORM, EL_SCENE.scr:256), `_landpad/_beach/_digsite/
  _tunroom` 0 (:538-542), `_Use_Hardsuit_Machine` 1 (:105), `_Hardsuit_Mach_Damaged` 0 (:297), `_Dropship_Missles` 14 (three missiles,
  :355), `_Warhead_Timer` 900 (:444), `_Drogg2_Alive` 1 (:1068).

## 2. The route, in order

### LANDPAD (first visit, `_alien_city_seen` 0)
1. Elevator arrival in `ELV` (above).
2. Walk into IMAG `MEETMECH`: `MARCHOUTAIRMECHO` (AIRHALL.scr:2-74) marches AIRMECHO to `AIR_POS` with AI ON; `AIRMECHO_AI` (its FIGR
   record's AI name) fires `BOLTGRN` (AI_AMECH.scr:1-50, 139-160).
3. Shoot it (KP5 with the blaster: `LEX_ATK_SHOOT` -> `BLASTER_FIRE`): `AIRMECHO_DEATH` sets `_airmecho_dead` (AI_AMECH.scr:52-120).
4. `DRA_BTN` (compass -130..-30, LANDPAD.scr:143-190) opens `AIRLOCK_MONITOR` (LANDMON.scr:11): a 3x3 lights-out grid from a random start;
   target 495 on the first visit (LANDMON.scr:603), toggle sets LANDMON.scr:59-537. Win: `_airlock_solved`, DRA opens.
5. `DRA_STRT` -> `DECONTAM` timeline (LANDPAD.scr:209-349) -> DRB opens; a HARD Lex survives the outer door.
6. Across the pad (LANBOT1-4 shoot, optional) to the jetson tube: `JET_BUT1` (compass -45..45, LANDPAD.scr:472-485) opens `JETSON1`;
   `PAD_UP` rides Lex down to `DEST_DWN` (LANDPAD.scr:421-439).
7. Along the ledge (LDGBOT1-3; `QUAKER`; `SHIP_GO` only after the city) to `TO_BCH`: `LOADLEVEL BEACH FROM_PAD` (LANDPAD.scr:712-733).
   The elevator (`ELV_LND1/2` -> `ELEVATOR_MONITOR`) also leads back to TOWER / CHAOS / CONTROL (ELEVATOR.scr:87, 205, 304).

### BEACH
1. Arrive at `FROM_PAD` on the upper ledge; `_beach` 0 takes BEACH_LOAD's fall-through (BEACH.scr:49-72).
2. Down the blocks to `ZIP1_A`, then ride ZIP1..ZIP3 with BLOCK; climb the block staircase BLOCK31 -> 32 -> 33 -> 34 -> 35 -> 37 -> 27 to
   `ZIP4_A`; ride ZIP4 to the lander shore.
3. The warhead: `DISARM_USE` (WARHEAD.scr:120-180, needs `_msl_frame` 1) puts the right-hand item down, gives BOMB in RTHAND and starts
   `WARHEAD_TIMER` (900 x 4 ticks).
4. Carry it to the blast door. The tuned route (TIMER_25 at the ledge's south end clamps the fuse, WARHEAD.scr:483-504) is ZIP5 ->
   the dead beast's body -> ZIP6..8 -> block stairs, so the beast must die first: gunnery station `WPN_MON_USE` (BEACHMON.scr:38), shot 1
   lures it, shot 2 in the look-up window kills it (BEACHMON.scr:363-400, AI_BEAST.scr:192-237); REMOVEBEAST makes PHYS FLUFFY walkable.
5. Put the bomb down inside `FIREBTN2`: `LEX_BOMB_DROP` (WARHEAD.scr:256-297) resets the fuse to 75 units, shows WARHEAD_MON until 50
   remain, then blows the door (`DOOR_BLASTED`, `_Blt_Space` neutral) and kills Lex if he is still in `BOMBHALL`; `BOMBRAD1/2` and
   `STAGGER` only knock him down.
6. Through the door to `SUITTES3`: `HARDSUITMACHINE` takes the suit off and runs `LOADLEVEL DIGSITE SUITTES2` (BEACH.scr:405-466).
   Other exits: `TO_PAD` / `FRM_PAD_USE` (LANDPAD), `TO_TPL` (TUNROOM FROM_BCH, the temple), `TO_CTY_USE` (`LOADLEVEL DIGSITE` with
   no arrival: DIGSITE has no `FRM_LDG`, so that one is vestigial).

### DIGSITE
1. `SUITTES2` arrival, `HARD_SUIT_OPEN_DIG` (DIGSITE.scr:67-72, 751-806). ZEDICAID (BEACH) heals Escher, who gives the scanner
   (ESCHER.scr; optional for the exit).
2. Drogg: `TDROGG2B` -> `ACTIVATE_DROGG2` (AI_DROG2.scr:22-174); it does not die: 22 hits plus a super-recoil run `DROGG2_ESCAPE`,
   which sets `_Drogg2_Alive = _FALSE` (:346-476).
3. The tomb: `OPENTOMB_USE` tears the door off, again with compass -105..-15 runs `TOMB_MONITOR` (DIGSITE.scr:282-349); buttons
   LTUB LTCB LTLB RTLB RTCB RTUB pressed 1 2 1 1 2 2 (TOMBMON.scr:150-392) give the KEY in LTHAND (DIGSITE.scr:236-258).
4. The key on the dig tube: `DIGTUBE_KEY_USE` sets `_TubesOpen` bit 4 and runs `THE_DIGTUBE`: `LOADLEVEL TUNROOM TUBE_WP4`, then
   `CALL ENTERTUBEROOM`, `GO DIG_PT`, `AI ON` (DIGSITE.scr:674-703, DIGTUBE.scr).

### TUNROOM (first visit) and the exit to the base
1. The tube monitor (`TUBEMON_USE` ..., TUNMON.scr:329-377): TN4B+TN5B+TN8B then SOLB set `_TubesOpen` bit 2 (zero-g).
2. `TO_0G_USE` (TUNROOM.scr:169-207): the tube ride into the zero-g room, gravity off, `CAPTUREKEYBOARD ZEROG_KEYBOARD`.
3. Fly by blaster recoil (TUNZEROG.scr:29-173: KP5 `ZERO_G_FIRE`, keypad turns, the pull toward `GRAVPT`) to `TO_FINAL`: The segment run has no gun and stands Lex in `TO_FINAL`; the full run flies it with the Captain's TONFA (`zero_g_flight`, `tumolt_tonfa`).
   `LOADLEVEL PLATFORM FRMZEROG`, then `GO FRMZEROG`, `GO WALKHERE WALK`, `AI ON` (TUN2PLAT.scr:1-20). **This is the exit to the base.**
4. The temple belongs to the return visit, after the city scene in PLATFORM: `TO_ZEROG` -> `LOADLEVEL TUNROOM GFROMFIN`
   (TUN2PLAT.scr:22-40), `MARINESENTERTEMPLE` (TEMPLE.scr:48-90), marines TMP_MAR_1/2 and the grenade (TEMPLE.scr:110-239),
   `TO_TMPL_USE` needs both marines dead and LEXMIR (TUNROOM.scr:237-311). Not driven by the harness.

## 3. How far the harness gets

| Segment | Start (real LOADLEVEL path) | Result |
|---|---|---|
| landpad | CHAOS, `PROCESS SWITCHTOLANDINGLEVEL` | plays to `BEACH FROM_PAD` by keys: mech fight, airlock grid, decontam, **a real walk into the open jetson tube** and its ride, ledge; one corrective `set_pos` after MEETMECH (blocker 9) |
| beach | LANDPAD, block `TO_BCH` | plays to `DIGSITE SUITTES2` (form LEX): zips 1-4, **the mantle onto BLOCK32**, warhead, drop, blast, suit machine; staged: the rest of the staircase (BLOCK33-35, 37, 27), the bomb carry, the last metres of the escape |
| digsite | BEACH, Lex in `SUITTES3` | probe: arrival; Drogg, tomb and key staged; `DIGTUBE_KEY_USE` by Space reaches TUNROOM and THE_DIGTUBE finishes |
| tunroom | DIGSITE, `THE_DIGTUBE` | probe: arrival; Lex walks after the tube; zero-g entry works; `TO_FINAL` reaches PLATFORM and Lex stands on its floor (z 820) |

Since the movement fixes (NOTES "Movement fixes") all four segments pass their steps (before: landpad stopped at the tube, beach at the first
mantle, tunroom at PLATFORM). The step that is a real finding now is `meet-mech`: see blocker 9.

AIRMECHO is fought by keys (`airmecho_duel`: a sidestep past each bolt, three shots between volleys). Its bolt leaves 8 ticks into FIRE_GUN
(frame 3, since the item events moved a frame earlier), and a sidestep drifts the wrong way for its first frames, so the dodge starts just
before the gun comes up: in AIRMECHO's last steps to AIR_POSX (it fires 3 ticks after arriving) and 5 ticks before each next volley (115
ticks apart), and the first bolt of a raise keeps the sidestep already held. Staged shortcuts (each is also recorded in the report with its reason): CONTROL's leftovers (HARD form, BLASTER, BLOCK readied in
LTHAND, `_Reactor_Safe`), the bot fights skipped with their outcome (`_LandbotsAlive` 0, `_BchBot1..3_Alive` 0: blocker 1 below),
`_airmecho_dead` for segments after LANDPAD, the elevator button (the process it runs), the BEACH arrival trigger, the mantle run-up onto
BLOCK32 (a turn on the spot carries Lex sideways off the block: turning drift), `ZIP4_A`, `FIREBTN2`, the escape out of BOMBHALL, `SUITTES3`,
the dig tube, `TO_0G`, `TO_FINAL`; the corrective `set_pos` after MEETMECH (LEXSTUK, blocker 9);
`_Drogg2_Alive` 0, `_tomb_solved` 1, the KEY, `_TubesOpen` bits 4 and 2.

> The full run (`re/interp/playthrough_full.py`, `re/playthrough/full.md`) continues this stretch in the same World / VM; it takes the segment functions of this harness on the running world.

## 4. Problems, ranked by how much they block play

Fixed in both ports. Items 1, 2 and 6 were found by the base playthrough too and merged with PR #16 (its versions and tests are
kept); the others have twin tests in `test_playthrough_surface.py` / `PlaythroughSurfaceTests.swift`:

1. **Elevator rides left Lex shut in the cabin at the wrong coordinates.** `LOADLEVEL <level> <volume> <arrival>`: `FUN_10d0_4d46` uses
   the first name (+0x15e) only for the carry query and hands the second (+700) to the level load; the port looked for an object named
   after the first. And the ride's own process was ended by its LOADLEVEL, so the door never opened. INFERRED rule: the caller survives
   when the new level uses its script file (ELEVATOR, DIGTUBE, TUN2PLAT, CRYTOTNK; TUNROOM.scr:158-160 says a TUNROOM caller dies).
   PR #16 recovered the rule (`10b0:13fb`, the script-file check in `10d0:4d46`); its versions are the ones in the tree.
2. **Level figures without SETAI never acted** (AIRMECHO, HALMECHO, DROGG2, FIDO, ACIDD, TMP_MAR_1/2): `FUN_1088_3371` starts
   `%s_AI` (1290:258f) of figure +0x178, which the loader (`FUN_1088_41b8`) reads from the FIGR record's 25-byte AI name field.
   (PR #16 gave them the name. They start by themselves only since the room events and default AI work, NOTES "Room events and the default AI": the counter +0x229 decides, and a script AI ON is no longer needed.)
3. **A suited Lex could not shoot.** The motion request `FUN_1098_0e49` runs `%s_%s` (1290:299e) of the instance name +0xf7: there is
   `LEX_ATK_SHOOT` but no `HARD_ATK_SHOOT`.
4. **After AIRMECHO's death Lex was locked** in `MOTION ATK_M2 CONTINUE` (AI_AMECH.scr:95): the port's ownership rule kept keys out
   until a script motion finished, and a loop never does. ASSUMPTION: a loop of the player's own key moves (MANUAL_MOVES) yields.
5. **Crash on the LANDPAD -> BEACH trigger**: `World.step` kept updating the old level's figures after a trigger's LOADLEVEL and indexed
   BEACH's PHYS list with a LANDPAD area (IndexError). Dropped figures are skipped now.
6. **Space on DISARM hung the warhead**: the use block's first slice starts `GO KNEEL WALK`, then the same input pass set STAND, so the
   GO never travelled. (PR #16.)
7. **`GO <trigger>` aimed at the box corner**: `FUN_10d0_33c8` takes the IMAG's reference point (vtable +0x50, `1068:0f4c`): the centre.
8. **The warhead fuse stopped after the drop.** IF (`10d0:3a6c`) stores its result per brace depth and a false IF skips one statement
   (`10c0:0f78`), skipping a nested IF without its ELSE; ELSE (`10d0:27f9`) runs iff that depth's flag is 0. So in
   `IF a THEN IF b THEN x ELSE y`, y also runs when a is false. The port bound the ELSE to the inner IF only (WARHEAD.scr:430-442).

Not fixed (bigger; diagnosis only):

1. **[S-bots] Checked: the bots' rate and damage are faithful** (NOTES "Items and combat"). One bolt per 60 ticks per bot on Medium, 14 HP a hit (10 + 4 * level, `1090:0ac6`), HARD has no energy armour, so three bots kill a Lex who stands still in seconds in the engine too; the bolts are slow enough to dodge (INFERRED). The harness still skips these fights. **`TURN` was wrong** (`10a0:19e6`: n degrees, positive = left; the port did `+= 2n`), which is why AIRMECHO's `BOLTGRN` never hit. It hits now, and the duel by keys is lost: two lasers connect, then RECOIL_ML, the camera leaves HFR3 / HFR6 at tick 1112, the hidden mech lets lasers through, and Lex dies about tick 1300. The landpad segment stages the fight's hits (shortcut kind `fight`); the death scene stays real. Open: a key policy that wins, and the view_cams rule against the original.
2. **[S-mantle] Resolved by the movement fixes.** Mantles did not lift Lex: the motion's root rise stayed in the pose. A flag-2 motion now commits
   its root z (`1088:1286`; once-motions at their end) and the hull passes the ledge under +0x1e8 (twin tests `test_movement.py` /
   `MovementTests.swift`: MANTLE_3 ends on the ledge, CLIMB_UP +1121 and DOWN_LADDER -1142 per wrap). Open: the BEACH staircase needs five more mantles.
3. **[S-tube] Resolved by the movement fixes.** Lex could not walk into the open jetson tube: the port-only LAND_REVERT clause of `support` offered
   the lintel ELVTP4's bottom under his feet and slid him along it. 03f2 has no such clause; it is gone. The harness walks in and PAD_UP rides him down.
4. **Resolved by the movement fixes.** Lex stayed frozen after the dig tube (`MOTION ENTER_GRAV FREEZE`): fixed first by letting a fresh key press
   break a FREEZE pose; FREEZE is now the idle-fallback bit only (the motion plays out and its last pose stays, `Figure.no_idle`).
5. **Resolved by the movement fixes.** Lex fell through PLATFORM after `TO_FINAL`: the trigger's LOADLEVEL runs inside `step()`, whose PHYS
   cache still held the old level's boxes, so `GO FRMZEROG` found no floor (z -816888). `load_objects` clears the cache; Lex ends at
   (8566, -123457, 820) on the floor.
6. **[S-escape] The warhead escape is a few hundred units short**: after WARHEAD_MON closes there are 50 x 4 = 200 ticks, the suited run covers
   ~129 units/tick, and Lex is still touching BOMBHALL at the blast (y -1035554 vs the hall's edge -1035738). Open: whether a monitor
   really stops the player's keys, and HARD's run speed.
7. **The beast fight, the gunnery monitor, the tomb monitor, Drogg and zero-g flight are not driven** (staged).
9. **[S-lexstuk] `GO LEX_POS2 WALK` now stops short and Lex ends on a wall.** MARCHOUTAIRMECHO's walk ends within 614 units of LEX_POS2
   (here 464 short, at (-28132, -71040)) with Lex's hull 29 units inside LEXSTUK, which the script makes solid at its end
   (`_lexstuk_SPACE = _POSITIVE`, AIRHALL.scr:69). 03f2 offers the new solid's top and the stand-on-support rule lifts him 6500 units onto it.
   Whether the original's arrival check (per tick, not per motion frame) ends clear of it is not known; the harness re-places him at the
   old LEX_POS2 with a logged `set_pos`.

Wrong-looking, low priority: `TO_LDG_USE` (`GO TO_LNDR`) puts Lex on top of PHYS CLIFF08 (z 44185; TO_LNDR lies inside the cliff);
`APPLY LEX PICTURE: no such texture`; turning motions shuffle Lex 350-450 units
(probably faithful); the known `BREAK n` warnings (`SWITCHTOLANDINGLEVEL:389`, `FLUFFY_SFX2/3`).
