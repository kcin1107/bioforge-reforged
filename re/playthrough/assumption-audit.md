# Assumption audit

Every `ASSUMPTION` marker in `re/interp/*.py` (tests excluded), checked against the decompiled engine on 2026-11-02. This changes no game code: fixes are separate PRs, tracked in `ROADMAP.md`.

| Verdict | Markers |
|---|---|
| Wrong: the code contradicts it | 26 |
| Confirmed: the code agrees | 42 |
| Simplification: a known approximation | 34 |
| Unknown: the code doesn't settle it | 36 |
| Not engine: a port or harness rule | 6 |
| **Total** | **144** |

**How far to trust this.** Subagents gave the first verdict for all 144. I re-read the code behind the Wrong items, and the last column below says how far that went. One claim changed on re-reading (see Unknown). Confirmed, Simplification and Not engine verdicts were not re-read. Everything here comes from the code, not from new live checks, so anything marked "live" below still needs one.

## Wrong, ranked

Ranked by how much a player would notice and how often it runs. Some rows hold several markers.

| # | Port | Engine | What's wrong | Impact | Fix | Re-read |
|---|---|---|---|---|---|---|
| 1 | world.py:97 | 10a8:0541 (key cases), 10a0:19e6, TURN_* root yaw | **Fixed, narrower than first reported.** Live: standing 43-48°/s, walking 113-117°/s. The port's standing rate was already right. The bug was Up + Left dropping the walk for TURN_LEFT at 45°/s, with no steering while moving. | High | S-M | Yes |
| 2 | world.py:3789 | 1088:4155 -> 1098:0745 | **Fixed.** Every living figure with no motion task and no event process returns to idle, with no player exemption. In the port Lex waited for a key after a finished scripted motion. | Med | M | Yes |
| 3 | world.py:2173, 2179 | 10a8:0541, 1098:13e1 | **Fixed.** The key handler only refuses on +0x229, z velocity, +0x1e8 and the recoil flag. Walk and run keys pass only the 12bd gate; turn and sidestep also use 13e1. The port kept keys out during one-shot script motions. | Med | M | Yes |
| 4 | world.py:3085 | 1088:3419 (5-byte compare, DS:2595), DS:2b34 | **Fixed, confirmed live.** The auto-turn tests case-sensitive "atk_m", and the keys name moves "atk_M8". Live, atk_stand steps toward the enemy and atk_M8 holds its heading. The port lower-cased the name and auto-turned. | Med | S | Yes |
| 5 | missiles.py:321 (extra finding) | 10e0:0961 | **Fixed.** A hit figure with +0x34 bit 0x08 (INVULNERABLE) leaves the missile flying with no HIT. The port destroyed it. AI_GRDOP, DIGSITE and TUNROOM set that flag. | Med | S | Yes |
| 6 | presentation.py:277 | 10d0:16cb, 10b0:0f48; [50bc] read only in 10e8 | **Fixed.** Captions ignore the subtitles switch and still show with subtitles off. | Med | S | Yes |
| 7 | options.py:129 | 1270:0b57, 1270:0a64 | Audio and gamma gauges draw frames 1..n+1 together. **Fixed.** The port drew one frame, so a single bar segment and no backdrop. | Med | S | Yes |
| 8 | world.py:2357 | 10e8:0529 -> 08a4, 1028:0ddc | **Fixed.** A new subtitle stops the old voice. The port let it keep playing. | Low-med | S | Yes |
| 9 | world.py:3074 | 10d0:8c53, 10a0:1f0a, 10e8:0000 | TURNTOENEMY and CONFRONTENEMY take frames (10° a call, or a turn task). The port turns at once. | Low-med | M | Partly: 1f0a read |
| 10 | resume.py:32 | 10b8:00a0, 10b8:027a | The MODIFYVAREVERYNTH task stores the end value; the port reads its high word as the start. Resuming a mid-ramp save only works when the start is 0. Relevant to milestone 5. | Low-med | S | Partly: constructor read |
| 11 | world.py:77 | 1168:055e, 1168:0711 | Only textures set by ANIMATE step. The renderer cycles every animated texture. | Low | S-M | Yes |
| 12 | world.py:3868 | 1088:1854 | Each wrap re-bases the root for every motion. Only matters for looping travel motions with no driver. | Low | S | Yes |
| 13 | world.py:100 | 10c0:31e0, 1100:196c | An unresolved sound gets no voice and handle 0; the port runs a 3 s timed handle. Two shipped names. | Low | S | Partly |
| 14 | world.py:2396 | 10c0:31e0 | An explicit volume of 0 means full volume. One script line (CHAOSBLK.scr:368). | Low | S | Yes |
| 15 | world.py:2504 | 11d8:0f79 | The keyboard interrupt records keys while a monitor is open; the port drops them. | Low | S | Yes |
| 16 | presentation.py:275, 276 | 10b0:0f48, 1100:1376 | Caption lifetime is one tick longer for even lengths, and its colour is the last subtitle colour, not always 0x75. | Low | S | Partly |
| 17 | monitor.py:618 | 1278:0b7d | Button frame is min(state, nframes-1), with no special case. No shipped path reaches the difference. | Low | S | Yes |
| 18 | items.py:311 | 1138:0000 | Corpse looting has no max-HP test. | Low | S | Yes |
| 19 | world.py:3474 | 10a0:1ff0 | GO with no floor below puts the figure near the floor constant, not at its own z. Off the map either way. | Low | S | Yes |
| 20 | world.py:3209 | 1088:0708, 1098:0000 | The already-hit byte clears only at motion start. No shipped looping strike motion, so no effect. | Low | S | Yes |
| 21 | mechanics.py:157 | 10d0:3207, 1098:0e49 | FREEHAND does consult the PUT_DOWN_RTHAND override. No shipped path reaches it. | Low | S | No |
| 22 | show.py:43, 272 | 1140:0c6a, 10d0:1823 | STARTFLIC needs no RUNFLIC gate; a missing keyboard hook block leaves the keyboard uncaptured. Rarely or never reached. | Low | S | No |
| 23 | world.py:3366 | 1090:09b9 | Dead guard: only the comment is wrong. | None | S | No |
| 24 | world.py:79 | 1070:08df | UNITS_PER_CM is 20.48, not 20, but the constant is unused. | None | S | Yes |

## Unknown worth checking

| Port | Question | How to settle it | Impact |
|---|---|---|---|
| `world.py:277` | `1120:0763` has no type fallback, and `MY_SPEED` is looked up under the instance name (+0xf7). But `EXTENT` and the armour values use +0x1ea, a different name. So MECHO2, CR_BOT, MARINE1 and TMP_MAR_1/2 may differ in speed only, or in more. | Sample those figures live. | Med |
| `world.py:64, 3794` | MOTION during a GO: the engine doesn't defer it. Does the displaced GO keep steering? | Live: start a motion during a GO. | Med |
| `world.py:92, 619, 620` | Root z kept by a figure without gravity: the 100-unit threshold isn't in the code. | Live: a gravity-less figure's finished motion. | Med |
| `missiles.py:229` | Missiles may score only their area's solids; the port scores all. | Read +0x35 after FIRE, or disassemble `10e0:0440`. | Med |
| `missiles.py:366, 380` | The carried pose on the BEACH zip ride. | Read the item class's vtable +0x4c. | Med |
| `world.py:3387, 3418` | LOADLEVEL volume arrivals; part of tracing vtable +0x44. | Trace `1148:15c7`. | Med |
| `world.py:2397` | Which object a SOUND is positioned on. | Trace `10c0:31e0`'s lookup. | Low-med |
| `subtitles.py:32` | The subtitle box's darkening table. | Compare box pixels live. | Low |
| `show.py:161, 196, 211`, `options.py:145` | Segment 10c8 and `1280:1ff1` aren't in `re/decomp`. | Decompile them. | Low |

Where these go in `ROADMAP.md`: figure properties and missile scoring to milestone 4; MOTION during a GO, root z without gravity and the zip ride to milestone 3, when those scenes are played; LOADLEVEL volumes when a level arrival needs them.

The other Unknown markers are low impact. Re-run the audit's method on any of them when its area comes up.
