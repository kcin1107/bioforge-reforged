# BioForge port research notes

Source: GOG offline installer `setup_bioforge_2.1.0.14.exe`, extracted with
`innoextract --gog -d game installer/setup_bioforge_2.1.0.14.exe`.
Game files live in `game/app/Bioforge/` and `game/app/GAMEDAT/`.

## Executable

`BIOFORGE.EXE` (1,123,344 bytes) is a **16-bit protected-mode NE** binary
(module name `RED`), compiled with MetaWare High C, bound to the Phar Lap
286|DOS-Extender. Not DOS/4GW, not 32-bit. 82 code segments + DGROUP
(selector `1290` in Ghidra) + stack.

Imports (the whole platform surface — what a port must replace):

- `AILXMI` (`AILXMI.DLL`): Miles XMIDI music, 20 functions
- `DOSCALLS`: 9 OS/2-style ordinals (7, 38–43, 89, 135), emulated by Phar Lap
- `PHAPI`: Phar Lap API — real-mode interrupts/far calls (VGA, mouse, DOS file
  I/O), real/linear memory mapping, exception handlers

## Ghidra

Ghidra 12.1.4 (`brew install ghidra`, brings openjdk@21). Project:
`re/ghidra/BioForge.gpr`. Headless runs need
`JAVA_HOME=/opt/homebrew/opt/openjdk@21/libexec/openjdk.jdk/Contents/Home`.

```bash
analyzeHeadless re/ghidra BioForge -process BIOFORGE.EXE -noanalysis -scriptPath re/scripts -postScript <Script>.java [args]
```

(`analyzeHeadless` is in `/opt/homebrew/opt/ghidra/libexec/support/`.)

Built-in NE loader + auto-analysis: 3,845 functions, `x86:LE:16:Protected Mode`.

Scripts in `re/scripts/`:

- `Summary.java`: language, blocks, function count, imports
- `RecoverFarDataRefs.java`: adds refs for `PUSH DS / PUSH imm16` far pointers
  (1,970 refs, 300 new strings). Already applied to the saved project.
- `StringXrefs.java <out.tsv>`: every string + referencing functions → `re/strings.tsv`
- `DecompileSegments.java <outdir> <seg>...`: decompiled C per segment → `re/decomp/<seg>.c`
- `Disasm.java <seg:off>...`: disassembly of functions (for register-passed constants)
- `DecompileAt.java <seg:off>...`: creates a function where Ghidra has none and prints its
  decompilation (run with `-readOnly`; e.g. the gamma panel `1280:1ff1`, hidden inside `1cc5`)

### Module map (segment → source file, from `__FILE__` strings)

```
1008 MEMORY.C        1088 LIVING.C       1110 RESCACHE.C     11a8 CCONFIG.C
1020 CCACHE.C        10a0 LIVING_P.C     1128 CACHETXM/HASH/OBJTOINT
1028 SNDMGR.C        10a8 APLAYER.C      1140 FLIC.C         11b0 DMANAGER.C
1030 IMSNDMGR/WRITEFIG 10b0 KERN.C       1148 GAMEDATA.C     11b8 TAREA.C
1038 COMPRESS.C      10c0 SCRIPTPR.C     1150 GARBAGE/MEMORY1 11c0 CELIST/CMDEVICE
1050 LISTS.C         10f0 LATEFILE/RESOURCE 1158 CCOLORI.C   11c8 FDEVICE/FSTATSTR
1068 PHYSICAL.C      10f8 SCANNER.C      1168 CTEXTURI.C     11d0 FLOADER/FLOADPAL
1080 LMOTION.C       1100 MONFACE.C      1178 CAPRTYPE.C     11d8 CKEYDEV.C
                     1108 SCENE.C        1180 CPOLYGI4.C     11e8 CVPORT.C
1188 CPOLYGI5/7/IE/CPOLYGON  1190 FASTFLEX/FILEPARS  1198 CMUSIC.C
11a0 CFLIC/MUSICFLS  11f8 CIFFWRIT.C  1200 CQFLOAT.C  1210 CDESC.C  1218 CPROTMEM.C
1220 DESCRIPT/SPANKER  1230 KERNEL.C  1238 NOTLIST/PRIORITY/PROCESS
1240 MLIST.C  1258 DLGBOOK.C  1268 DLGLIST.C
```

Segment `1000` (largest, 43 KB) is unnamed: likely main + C runtime.

## REA

`rea-agents` (REA) **cannot open this binary**: its Ghidra DOS profile only
admits MZ real-mode / COM and lists NE/LE/LX as explicitly unsupported, and it
rejects language drift (we need `16:Protected Mode`). Options: use Ghidra
directly (what we do now), or contribute an NE profile to REA.

## Data formats

| Files | Format | Status |
|---|---|---|
| `ROOMS/*.CAM`, `MONITORS/*.CAM` | Flex archive of palette + RLE images | **decoded** (`re/formats/cam.py`), 8,446/8,446 frames |
| `SOUND/*.FLX` | Flex, 717 samples + name table (E/F/G language sets) | **decoded** (see "Sound" below) |
| `MUSIC/MUSIC.FLX` | Flex v1: 100 Miles XMIDI (`FORM XDIR`) + song/transition tables | **decoded** (`xmi.py`, `music.py`; see "Sound") |
| `MONITORS/FTEXT.FLX` etc. | Flex of plain text (in-game monitor text) | readable |
| `SHOW/*.SHO` | plain Autodesk FLC 320×200 (prefix chunk 0xF100 = Animator metadata); **no audio** | ffmpeg decodes (`-f flic`); FLI_COPY chunks are 63998 bytes (pad to 64000) |
| `BODY/*.EOR`, `ITEMS/*.IFF` | IFF `FORM REAL`: textured mesh | **decoded** (`eor.py`): 40/40 bodies, 35/37 items |
| `BODY/*.SKL` | IFF `FORM SKEL`: limb hierarchy | **decoded** (`salsa.py`) |
| `BODY/*.SKN` | IFF `FORM SKIN`: vertex → limb | **decoded** |
| `BODY/*.MTN` | IFF `FORM MOTN`: motions (`PRLE` packed / `POSE` raw) | **decoded**: 600/600 motions |
| `BODY/*.BED` | text: which REAL/SKIN/SKEL/MOTN files make a figure | **decoded** (`bed.py`) |
| `GAMEDAT/*.IFF`, `INITGAME/*.IFF` | IFF `FORM OBJS`: per-level objects (cameras, collision boxes, waypoints, triggers, figures) | **cameras + collision decoded** (`level.py`) |
| `BODY/*.COL` | 60-byte binary (collision?) | not yet |
| `SCRIPT/*.SCP` | text scripts with binary tokens (`^` + 2 bytes = variable/sound ref?) | not yet |
| `GAMEDAT/VARS.DEF`, `SOUNDS.DEF` | text: script variable / sound name tables | readable |

| `DATA/*.FNT`, `MOUSE.SHP` | fonts and cursor shapes, same format (see "Fonts") | **decoded** (`fnt.py`, `mouse.py`): 12/12 fonts, 8/8 cursor frames |

### SHOW playback (segment `1140`, FLIC.C)

`STARTFLIC` opens the named SHOW resource through `FUN_1140_0c6a`; `STOPFLIC` frees its state through
`FUN_1140_0ecc`. The constructor `FUN_1140_02bc` initializes the frame interval at offset `+0x164` to
2; `SETFLICRATE` (`FUN_1140_0dfc`) replaces it. `FUN_1140_077b` compares the next frame time against
the engine's 60 Hz clock at `1290:8334/8336`, advances at that interval, and uses the FLC header frame
count to stop. The script rates are 6 for INTRO/ENDGAME (10 fps), 7 for INTRO's Mastaba section, and
1 for PLT0 (a 60 Hz polling interval; its live `_plt0_frame` script variable selects the frame).
The SHOW headers' millisecond speed fields differ (INTRO 71, ENDGAME 114,
PLT0 128) and the scripts override the playback interval. Each file has one extra physical frame
chunk after its declared frame count, conventionally a ring frame; the native player presents the
declared frames.

`START.scr`'s `GAME` calls `INTRO` before `STARTPLAYING` opens the difficulty dialog and loads CHAOS.
`INTRO.scr` chooses INTRO/INTROF/INTROG by language. `RUNFLIC` starts the named timed scene block,
whose SOUND and MUSIC commands supply the movie audio separately; the file itself has no audio.
INTRO captures Escape and jumps to `BYEBYE`; ENDGAME captures Escape or Alt+X after its
`RUNFLIC ENDPROCESS 525` returns, then jumps to `LEAVEGAME`. `CONMACH.scr` calls ENDGAME
after the shuttle takeoff; `EL_SCENE.scr` starts PLT0
during `BRINGONTHEALIEN`. The demo menu can call INTRO or ENDGAME. No script starts DEMO1.SHO,
so it is a decodable asset without a recovered in-game trigger. Palette chunks are passed through
the FLIC display path (`FUN_1140_0603` checks types 4 and 11); script `FADE HIDE/UP/DOWN` controls
the show transitions. The fade curve is recovered (see "Presentation, flics and front end"), and both ports now play the
shows in the core.

### Flex container (`re/formats/flex.py`)

```
0x00 char[0x50] copyright        0x58 u32 version (6; MUSIC.FLX = 1)
0x50 u32 0xA1A11A00              0x60 u32 entry size (8 or 21; v1: always 8)
0x54 u32 entry count             0x80 entries: u32 off, u32 size[, char name[9], s32 depth]   (21-byte form)
```

### CAM image

Entry 0 = 768-byte 6-bit VGA palette. Other entries:
`u16 w, u16 h, u16 nframes, nframes × (u32 off, u16 size)`.
Frame: `u16 rle, u16 w, u16 h, s16 hotx, s16 hoty, u16 rowoff[h]` (rowoff
relative to its own position). Row: repeat `u8 skip; u8 n;` then if `rle`
`n&1 ? run(n>>1) : literal(n>>1)` else `literal(n)`, until x ≥ w. Same family
as Ultima 8 shapes.

```bash
python3 -I re/formats/cam.py game/app/Bioforge/ROOMS/AIR1.CAM re/out/AIR1
python3 -I re/formats/check_cams.py game/app/Bioforge/ROOMS/*.CAM
```

## Characters ("SALSA" figures)

A `.BED` text file names the parts: `REAL=` mesh (.EOR), `SKIN=` links, `SKEL=`
skeleton, `MOTN=`/`LIST=` motion files (`+`-separated; skeletons and motions are
shared, e.g. Lex = `lex.EOR` + `LEX.SKN` + `man.SKL` + `man.mtn+lex.mtn+roland.MTN`).
All payload integers little-endian; IFF chunk sizes big-endian.

**Mesh (`eor.py`)**, `FORM REAL`:
- `VERT` n × s32 x,y,z, bind pose, **+Z up**
- `TXMS/TXMP` char[8] name, u16 w, u16 h, 8-bit pixels (room palette); `TXMD` = source path
- `TRIS/FACE` (u8 kind, u8 color, u16 v[3]); `QUAD/FACE` same with 4 verts; `LINE/FACE` 2 verts.
  kind 6 = textured, 0/1/5 = flat (color = palette index)
- `TRIS/MAPS`, `QUAD/MAPS`: u16 face, u16 tex, (u16 u, u16 v) per vertex, textured faces only
- `DETA/LVL0` face order list, `ATTR` 9 bytes/face, `OBJT/EXTE`: unknown.
  `ITEMS/BLASTER.IFF`, `PIPE.IFF` use an older `VTRI`/`UVXY` layout: not handled.

**Skin**: `LINK` = u16 limb index per vertex (rigid, one limb per vertex).

**Skeleton** `LIMB` (39 bytes, parent before child), read by `FUN_1040_1470`:
`char name[9], s16 parent, s16 rest[3], s16 angle[3], s32 length, s32 offset[3]`.
`LOCK`, `SENS` unknown.

**Motions**: pairs of `MOTN` header (83 bytes) + `PRLE` or `POSE`.
Header: name (NUL-terminated, garbage after), frame event list (frame numbers with
event bytes between them: 0xfd..0xf9 sound cues, 0xef/0xee/0xf3/0xf4/0xf0 item events, 0xfe loop end, 0xff pad; see
"Motion sound cues and formatted sound names"), `+77 u8 nlimbs`,
`+79 u16 rowbytes = 18 + 8*nlimbs`, `+81 u16 nframes`. Rest unknown.
Frame = s32 root pos[3], s16 root angle[3], per limb s16 angle[3] + u16 (0x100).
`POSE` = raw frames. `PRLE` = raw 18-byte root records for all frames, then an RLE byte
stream of s8 angles, **axis-major**: a0 for limbs 0..n−1 (each nframes long), then a1,
then a2. RLE: c ≥ 0x80 → c−0x80 copies of next byte, else c literal bytes; runs cross
channel boundaries. Motions can have more channels than the skeleton (MAN: 20 vs 19;
the extra is always 0).

**Kinematics** (`FUN_1038_035b`, `FUN_1030_1054`, `FUN_1208_2548/2858/2b64`): angles are
256 per turn. Matrix rows = local axes (16.16 fixed). Per limb: start at parent's end
position/matrix; `pos += offset · R`; apply rest angles then animated angles, each as
rotZ(a[2]) → rotX(a[0]) → rotY(a[1]) about local axes, with X/Z as
`r_i' = c·r_i + s·r_j` and Y flipped (`r0' = c·r0 − s·r2`); end = pos + R.row1 · length.
Posed vertex = R_anim · R_bindᵀ · (v − start_bind) + start_anim (bind = rest, zero angles).

```bash
re/.venv/bin/python -I re/formats/eor.py game/app/Bioforge/BODY/LEX.EOR
re/.venv/bin/python -I re/formats/render.py BODY/LEX.EOR ROOMS/AIR1.CAM out.png 0 90 180
re/.venv/bin/python -I re/formats/animate.py BODY/LEX.EOR BODY/MAN.SKL BODY/LEX.SKN BODY/MAN.MTN WALK ROOMS/AIR1.CAM walk.gif
re/.venv/bin/python -I re/formats/bed.py BODY/MECHO.BED ROOMS/AIR1.CAM mecho.png [MOTION]
```

(`re/.venv` has numpy + Pillow. Paths above are relative to `game/app/Bioforge/`.)

Texture index 0xff is a transparent texel in the prototype renderer. Every checked room
palette maps 0xff to magenta RGB (255,0,255); Lex and NURSEBOT textures contain thousands
of 0xff pixels. The old rasterizer painted these pixels, creating bright pink hands and
robot parts. Skipping only textured 0xff pixels removes them in the same boot frame while
leaving opaque texture colours intact. The executable's textured pixel loop at
`1018:13a6..13ad` confirms that `0xff` is skipped while other indices are copied.

Open questions: root-motion semantics (root pos looks like absolute travel per frame);
interpolation fields (`FUN_1030_1175`); `ATTR`, `LOCK`, `SENS`, `.COL`.

## Levels, collision and cameras

10 levels (`BEACH CHAOS CONTROL DIGSITE LANDPAD PLATFORM TANKS TITLE TOWER TUNROOM`).
`INITGAME/` = initial state, `GAMEDAT/` = same format (current/saved state; CHAOS
differs, e.g. has a `PLAY` record). `SCRIPT/<LEVEL>.LVL` lists the `.scr` scripts used.

`FORM OBJS { VERS u16 (21); records }`, loaded by `FUN_1148_0d46`, which dispatches on
the tag via class descriptors (`1290:1fa6` WAYP → `FUN_1060_1849`, `2067` IMAG →
`1068_0b18`, `20f1` PHYS → `1068_117b`, `2228` ITEM → `1078_0483`, `5f30` CAMR →
`1110_11ae`/read `1110_1450`, FIGR → `1088_27e8`, PLAY → `10a8_00ed`).

Common 45-byte base: `char name[9]; s32 pos[3]; u32; u8; u8[7] (pointer junk); s32 pos2[3]`.
World units: Lex is ~9,500 tall, +Z up.

| Tag | Size | Meaning |
|---|---|---|
| `PHYS` | 55 | axis-aligned volume `pos`..`pos2`; last byte is state 0/1/2, preceding 9 bytes partly unknown |
| `WAYP` | 45 | named point (`pos == pos2`): AI/script targets, spawn points |
| `IMAG` | 54 | trigger volume (see "IMAG triggers"): base flags byte (+21) bit 0x01 = fire on entry only; camera name at +45 forced while the followed figure is inside |
| `CAMR` | 102 | camera, `name` = room image (`ROOMS/<name>.CAM`) |
| `FIGR` | 370–509 | placed character (not decoded) |
| `ITEM` | 191 | placed item (not decoded) |
| `PLAY` | 442 | player (not decoded) |

**CAMR** (189 total): `pos` = eye; `u8` at 33; at 34 a 3×3 rotation as s32 rows, 8.8
fixed (row0 = right, row1 = forward, row2 = up); at 70 `s32 target[3]` (look-at point,
along row1); at 82 `u32` (38) and `u32` (0); at 90/94 s32 16.16 `FARMARK`/`NEARMARK`;
at 98/100 s16 `FOVReduce` (defaults from option keys in `FUN_10f0_0164`; validated
in `FUN_1110_1450`). These are camera tracking/switching parameters.

**Projection** (`FUN_1178_0000`, viewport `FUN_1150_19a3`/`1739`):
`d = P − eye; x = row0·d, y = row1·d, z = row2·d;`
`u = cx + ((x · fx / y) >> 8), v = cy − ((z · fy / y) >> 8)` with `fx = 0xcc80`
(hard-coded, overrides the FOV/PROJPLANE math) ⇒ **204.5 px**, `fy = fx · aspect`
(runtime global `1290:6c70`; best fit 0.833 = VGA pixel aspect), `cx, cy = 160, 100`.
Verified by projecting PHYS boxes on all 177 camera backgrounds: edge-alignment score
peaks exactly at f = 204.5, aspect 0.833, unmirrored (`camfit.py`), and boxes sit on
the visible geometry (e.g. TUNROOM/ZEG3 wall cubes).

```bash
re/.venv/bin/python -I re/formats/level.py game/app/GAMEDAT/TUNROOM.IFF        # list cameras
re/.venv/bin/python -I re/formats/camview.py game/app/GAMEDAT/TUNROOM.IFF game/app/Bioforge/ROOMS ZEG3 out.png 204.5
re/.venv/bin/python -I re/formats/scene.py game/app/GAMEDAT/CONTROL.IFF SHO5 game/app/Bioforge/BODY/LEX.BED STAND 0 NOCROSS4 0 out.png
```

Open questions: no depth for the pre-rendered backgrounds, so how figures get occluded
by foreground scenery (probably the small named sprites in each `.CAM`, drawn after
figures, or PHYS-based masks); FIGR/ITEM/PLAY records; PHYS material and other tail
bytes; the `u8` at CAMR+33 and u32 at +82.

## Occlusion (depth-sorted cels)

The pre-rendered rooms have no depth buffer. The engine builds one list of 2D "cels"
per frame and paints it far-to-near (`FUN_1110_051f`):
- every non-palette entry of the camera's `.CAM` (background, full-screen light/door
  overlays, small foreground pieces) is a scene element (45-byte struct, list at camera
  object +0x7f, count +0x7d) → one cel per frame (`FUN_1110_0d9c`) with the element's
  32-bit depth;
- that depth comes from the room file's entry table: the 13-byte name field is
  `char name[9]` + `s32 depth` (`FUN_10f0_1dc8` → `FUN_1108_14fa`, default 99999 when 0).
  E.g. AIR1: background 18150, railings RG1/RG2/RG3 6270/4772/2304; many backgrounds 99999;
- 3D figures are not one cel: each polygon/line is a cel (`FUN_1170_0197`, `1160_*`,
  `1158_*`) whose depth is the global `1290:6d85`, set per primitive to the average of
  its vertices' camera depths (`FUN_1158_0d03` for lines; assumed the same for polygons);
- the frame shown for each element comes from a script variable `"<name> FRAME"`.
Implemented in `re/formats/compose.py` (see its docstring). Sanity check: AIR1's
doorway is transparent in the background (depth 18150) and filled by `BK5` (depth
393541, the room beyond), which the sort draws first; the RG3 railing (2304) covers
figures behind it.

```bash
re/.venv/bin/python -I re/formats/compose.py game/app/GAMEDAT/CONTROL.IFF AIR1 game/app/Bioforge/BODY/LEX.BED WALK 4 cam 200 out.png --depth 6000 --side 2200 [--frame NAME=K] [--verbose]
```

## Scripts

`SCRIPT/*.SCP` (107) are the game's script **source**, tokenized: layout, comments and
blocks are preserved, identifiers replaced by binary tokens padded with spaces to the
original width. The engine compiles them to bytecode at startup (seg 1118: `.SCR` plain
or `.SCP` tokenized sources, `.DEP` dependencies, `compile.tim`, `errors.im1`) and runs
them on a cooperative process kernel (seg 1230 `KERNEL.C`, "Kernel Ver. 1.00 - T.
Zurovec"; `PROCESS.C`, `PRIORITY.C`). `SCRIPT/<LEVEL>.LVL` lists the scripts per level.

Token encoding (verified on all 19,174 prefixed tokens):
- prefix + 2 bytes ≥ 0x80, `id = ((b0 & 0x7f) << 6) | (b1 & 0x3f)`:
  `^` variable = `SCRIPT/VARS.DEF` entry (0-based, 1000), `$` constant = `DEFINES.DEF`
  (255; 66 = _FALSE, 67 = _TRUE), backtick sound = `SOUNDS.DEF` + `SOUNDS2.DEF` (1564),
  `@` function = expression-function token (81: CALL 29, SOUND 6, PROCESS 13,
  SETCURRENTFIGURE 27, …), `~0`–`~9` local registers (guess).
- `#` + 2 bytes = jump target: index into the file's definitions in order of
  appearance (`{ NAME` and `[ NAME` headers at column 0, `:LABEL` lines); all 1,102 resolve.
- `.` + 4 bytes = another object's local: selector + local index 0–9. **Object-local selectors**
  (`FUN_10c0_24e1`): 1 = `CURITEM` (ctx+0xe7f), 2 = `CURFIG` (ctx+0xe7b), 3 = the player (DS:2a66), 4 = `ENEMY` (CURFIG's
  +0x195); an unset object is error 0x6f. Until 2026-10-31 the detokenizers named 1 `CURFIG` and 2 `CURITEM` (swapped):
  battery charge `CURITEM.~0` (CONMACH, AI_ELITE) read as a figure local and attack status `CURFIG.~3` as an item local.
- `BREAK` + 2 bytes (no prefix) inside SWITCH: the number of the innermost SWITCH, counted through the whole file (see "BREAK n" below).
- `[ NAME … ]` blocks are timelines (e.g. `ANI_FIRE_FRAME`): lines `MM:SS statement`,
  typically stepping a `_…_FRAME` variable to animate a room sprite.
- statement keyword = one token byte at statement start (146: `I` IF, `M` MOTION,
  `W` WAIT, `G` GO, `A` AI, `C` CAMERA, `P` LOCALVAR, 0x9c FACE, 0x83 SUSPEND, …).
- engine tables (DGROUP, 5-byte records `u8 token, far char* name`): statements
  `1290:3180`, functions `1290:3fee`, operators/words `1290:2f25` (AND OR && || THEN
  = == != <= >= < > IN NOTIN), argument keywords `1290:3108` (30, by index: ALWAYS AT
  CONTINUE … WALK). Dumped in `re/out/script_tokens.txt`. Statement handlers: far-pointer
  table into seg 10d0 around `1290:3582`.

Runtime conventions (from engine strings): blocks `{ NAME … }` are routines; the engine
fires event blocks by name: `<obj>_LOAD/_UNLOAD/_AI/_HIT/_HIT_<x>/_HIT_WALL/_DEATH/
_WOUNDS/_FIRE/_STIMULUS/_HIDE/_UNHIDE/_ENTER_COMBAT/_LEAVE_COMBAT/_LOG_ADDED`,
`<a>_<b>_USE/_DROP/_TAKE`, monitor buttons `<btn>_HIGHLIGHT/_RELEASED/_REPEAT/_BUTTON`.
Engine-read variables: `_<sprite>_FRAME` selects a room sprite's frame (e.g. `_DR7_FRAME`);
`_<phys>_SPACE` updates PHYS state. `_SOLID` appears in engine strings but its relation to
PHYS has not been established.
Runtime semantics (from the handlers; statement handler for token t = far ptr at
`1290:345a + 4t`, seg 10d0, full map `re/out/statement_handlers.txt`; function handler
for token t at `1290:4183 + 4t`, seg 10d8, `re/out/function_handlers.txt`):
- every block runs as a process on the kernel; handler result 0 = next statement,
  1 = yield until next tick, 2 = process ends.
- time: **30 ticks/s**. `WAIT n` = n ticks (n ≥ 2), `WAIT n SECONDS` = 30n ticks
  (`FUN_10d0_8def`). Timeline stamps are `seconds:ticks` (second field 0–29 in all 2,376
  stamps; first field up to 9000).
- `SUSPEND` yields one tick. `SUSPENDWHILE expr` waits until the process whose handle
  `expr` returns has finished (e.g. `SUSPENDWHILE MODIFYVAREVERYNTH(var,+1,1,10,4)`).
- `CALL block args…` (`FUN_10c0_3968`): child process linked to the caller; args are
  copied into the callee's LOCALVARs in order; caller blocks; value = callee's
  `RETURN v`. `PROCESS block args…` (`FUN_10c0_37e9`): same but detached; runs its first
  slice at once and returns a process handle (for KILLPROCESS, SUSPENDPROCESS,
  ISPROCESSVALID, SUSPENDWHILE). Both inherit CURFIG/CURITEM context.
- `RETURN v` stores v in the caller and ends the process. `JUMP label` = goto.
  `LOOP n label` loops back n−1 times (one counter per process). `BREAK n` jumps to the
  end of the n-th SWITCH of the file (per-file switch table; "BREAK n" below).
- label numbering (`#` refs) follows the compiler's definition counter `FUN_1118_07dc`: each
  `[`, each `{` followed by a name, each `:` that is neither followed nor preceded by a digit
  (`:` + digit = a timestamp), outside strings and `//` comments. Correction (2026-10-14): the
  `:` of `CASE n:` does NOT count, although the decompiled loop seems to count it (probably the
  CASE statement consumes it first). Counting it left 13 jumps on unnamed targets and broke the
  PIMM loops (`JUMP LOOP` after `:LOOP` rendered as `#13`); without it all jumps resolve.
Detokenizer: `re/formats/script.py` → readable sources + `index.md` in `re/out/scripts/`
(`script.py game/app/Bioforge/SCRIPT re/out/scripts`). All tokens resolve (label
numbering as above; 0 jumps to unnamed targets; a naive line-based rule mis-resolved 93 jumps). 1479 blocks, 165
timelines, 813 CALL edges (10 targets not defined in any file, e.g. demo entry points),
event handlers: _USE 132, _LOAD 106, _TAKE 88, _AI 45, _DEATH 45, _FIRE 35, …

## Interpreter (`re/interp/`)

The opt-in `World.set_player_input(forward, turn, run, attack)` API and `play.py` SDL2
preview now drive the player from keyboard state. Manual movement advances the existing
WALK/RUN/WALK_BACK root motion while scripts retain ownership during GO, AI, frozen poses,
and non-locomotion motions. The API's `turn` is an assumed 3° per 30 Hz tick (held turn keys play the
turning motions instead); Space plays the
available ATK_SHOOT motion as a provisional attack. The original keyboard mapping, attack
rules, and input-enable gate have not been recovered. CHAOS's negative CE3 room box contains
the PLAYLOC spawn, while `_dr*_SPACE` variables toggle doors; simply treating every PHYS
overlap as solid would block the player at spawn.
The PHYS constructor `FUN_1068_117b` allocates 0x53 runtime bytes. Its reader
`FUN_1068_12c9` loads nine tail bytes at object offset 0x41 and one at 0x4a;
`FUN_1068_127d` then looks up `_<name>_SPACE` and copies the variable byte at +0x19 into
the PHYS state byte at 0x4a. `FUN_1068_15ad` selects two words from an object table using
that state as an index (state 2 emits a PHYSICAL.C diagnostic). This confirms that `_SPACE`
affects PHYS runtime state, but the selected words' meaning and its role in player movement
remain unresolved.

`FUN_1130_07f6` computes a signed point-overlap score for PHYS boxes: start at 1;
subtract 1 for every containing state-0 (NEGATIVE) box; add 1 for every containing
state-1 (POSITIVE) box unless flag bit 3 at runtime +0x34 is set; ignore state 2
(NEUTRAL). It returns `score > 0`. `FUN_1068_087c` performs the inclusive 3D AABB
test. That signed point query is used for camera-side selection, not preview movement.
The preview instead checks the recovered figure hull against the selected area's positive-state
PHYS members. `World.phys_state` reads each PHYS final byte or its current `_<name>_SPACE` VM
override; `COLLISIONS CURFIG ON/OFF` gates manual, GO, and AI root movement for that figure.
Strides step like the original mover (`FUN_10a0_22e1`). See the movement section below.

`parse.py` (all 107 scripts parse, 0 failures; 1,644 blocks, 24,664 statements, 1,153
data-table lines `< NAME = a b >` kept raw), `vm.py` (30 Hz cooperative scheduler,
processes, expressions, the runtime semantics above; engine commands go through
`Engine.call(kind, name, args, proc)`; `RecordingEngine` logs them), `run.py`, and
`test_interp.py` (18 tests).

```bash
re/.venv/bin/python -I re/interp/parse.py re/out/scripts
re/.venv/bin/python -I -m unittest discover -s re/interp -p test_interp.py
re/.venv/bin/python -I re/interp/run.py LANDPAD MEETMECH --ticks 400     # airlock cutscene trace
re/.venv/bin/python -I re/interp/run.py TUNROOM TUNROOM_LOAD --ticks 300 --limit 30
```

VM-handled: control flow, WAIT/SUSPEND/SUSPENDWHILE, CALL/PROCESS/RETURN, process
control, flags, MODIFYVAREVERYNTH, SETCURRENTFIGURE/ITEM context. Everything else
(MOTION, GO, CAMERA, SOUND, SUBTITLE, RANDOM, ISCURRENTCAMERA, …) is engine-delegated
(`vm.ENGINE_STMTS` / `ENGINE_FUNCS`). Guesses are commented in the code. CALL and PROCESS follow the executable (2026-11-20,
"Engine assumptions settled"): CALL runs the child's first slice at once (`10c0:3968`), PROCESS only from a `{` routine
(`10c0:37e9`); a caller or waiter woken by a child's end runs in the next scheduler walk (`1238:077f`, `1230:177a`).
Other open points (the timeline clock is recovered: "Camera-linked processes"):
`IN lo, hi` treated as an inclusive range, data-table semantics, busy-polls on engine
predicates (ISAION, ISKEYPRESSED) need a real engine.

## Camera selection (seg 1130, camera manager)

`1290:63ce` holds the current camera and `63d2` a pending one. `FUN_1130_0000(cam, mode)`
requests a camera (mode 2 = switch now); `FUN_1130_0114` performs the switch (loads the
room, fires `<cam>_UNLOAD`). Each frame `FUN_1130_0fa3` picks the camera for the followed
object (default the player; `63fa`, set by `FUN_1130_00c1`, presumably CAMERAFOLLOW):
1. A forced camera (`63d6`, set via `FUN_1130_0f85`, presumably the CAMERA statement) is
   applied once.
2. Otherwise the current camera is kept while it still accepts the position.
3. Otherwise the engine takes, among cameras without flag 0x08 (disabled, presumably
   CAMERAAUTOACTIVATE OFF), the accepting camera with the smallest `FUN_1208_13e3`
   (probably distance).
4. Debounce: the same winner must come up two frames in a row.

Automatic switching only applies while the auto flag `1290:63da` is set (`FUN_1130_0f4e`).
The CAMERA statement (`FUN_10d0_12f9`) controls it:
- `CAMERA <cam>` locks: auto off, switch now.
- `CAMERA UNLOCK` (argument keyword 28) resumes automatic selection.
- `CAMERA SHOW …` (`FUN_10d0_115c`) and `CAMERA AT …` (keyword 1, `FUN_10d0_0c5e`) are
  special forms.
- `CAMERA <cam> LOAD` (`FUN_1110_024a`) loads `<cam>.CAM` into the resource cache and reloads the current room: no event, no switch
  (BEACH's `BCH_LOAD` is the only user). A word other than LOAD is an error message (0x1c / 0x1d).

The airlock scene never unlocks, so it stays on HFR3 while Lex walks in from behind the
camera.

Acceptance `FUN_1110_1a95(cam, P)`:
- Distance: `NEARMARK ≤ |P − eye| ≤ FARMARK` (CAMR @94 / @90, world units).
- Angle: the bearing to P relative to the camera heading lies within ±(half-FOV −
  FOVReduce), with half-FOV the u32 @82 (38° in every camera) and FOVReduce the s16s
  @98/@100.

Check on LANDPAD: LEX_POS is accepted only by ELV2, LEX_POS2 by HFR3/HFR6, AIR_POS by
HFR4, which matches the airlock script's own CAMERA HFR3. The `IMAG CAM_xxxx` boxes are
not part of acceptance: a trigger whose camera field is set forces that camera through `[63d6]`
(`FUN_1130_0f85`), which the next `FUN_1130_0fa3` requests ahead of the normal selection
(no acceptance test, no debounce; candidate cleared); the switch itself still needs the auto
flag, and `CAMERA UNLOCK` resets the pending camera to the current one, so a request made
while locked is lost (see "IMAG triggers").

## Game start and level changes

New game (START.scr): `GAME` → `CALL INTRO` (`LOADLEVEL TITLE ABC`, intro movies) →
`STARTPLAYING`: `CREATEFIGURE LEX PLAYER` (if no player yet), `LOADLEVEL CHAOS PLAYLOC`
(Lex's cell, (-10944,-7281,-5754)), then `CALL GOODMORNINGLEX` (AWAKEN.scr).
- `CREATEFIGURE <type> [name]` (`FUN_10d0_1f61`) creates a figure from `BODY/<type>.BED`.
  There's no position argument.
- `LOADLEVEL` (`FUN_10d0_4d46`) kills all script processes, then:
  - `LOADLEVEL <level> <arrival>` positions the player at the arrival point and loads the
    level (`FUN_1118_111b`). The z follows GO's rule (live: "The ladder through the iris").
  - `LOADLEVEL <level> <volume> <destination>` (elevators, e.g. `LOADLEVEL CONTROL ELV ELC`) carries every figure and
    floor item that overlaps the old level's volume to the new level, and the player whether or not he is inside. The third
    word, not the volume, is the destination looked up in the new level (`10d0:4d46` passes word 3, +700, to `1148:15c7` →
    `1050:0c65`). Each keeps its offset from the volume (x, y from its centre, z from its floor) and arrives at the destination
    plus that offset ("LOADLEVEL: missiles, the volume carry and offsets").
  - About 45 transitions exist, e.g. `LOADLEVEL LANDPAD FROM_BCH`, `LOADLEVEL BEACH FROM_TPL`.
- Level load fires `<LEVEL>_LOAD` (`FUN_1148_0490` formats `%s_LOAD`).
- A camera switch fires the room's and the camera's `_LOAD` / `_UNLOAD` blocks: see "Room events and the default AI".
- Level-number constants: `_TOWER_LEVEL` 1, `_CHAOS_LEVEL` 2, `_CONTROL_LEVEL` 3,
  `_LANDPAD_LEVEL` 4, `_TUNROOM_LEVEL` 5, `_PLATFORM_LEVEL` 6, `_Beach_Level` 7.
- LOADLEVEL kills processes twice: one class through `FUN_1230_1182(0, 0x10c)`, then every process except the caller and
  its CALL chain (the context's +0x71 links) in `FUN_10b0_13fb` (called from `1148:14a3` with the caller). After the load the
  handler's tail ends the caller (vtable +8, return 2) only if its script-file record (context +0xe87, looked up by name in the
  script registry by `1118:434d`) has no loaded code (+0xd/+0xf), i.e. its .scr is not in the new level's .LVL. So the caller
  goes on after LOADLEVEL in ELEVATOR.scr (EXITSTASIS, door), CRYTOTNK.scr (`CALL ENTERCELL2`), TUN2PLAT.scr ("IT WORKS"),
  ENDGAME.scr (TITLE.LVL) and START.scr; it dies in TUNROOM.scr:160 (not in DIGSITE.LVL), BEACH, DIGSITE, LANDPAD, PLATFORM.
  Ports: `VM.kill_level_owned` / `end_unloaded` (ASSUMPTION: a CALL ancestor whose file is gone is dropped the same way). The
  boot chain (`GAME`, owner 'global') survives as before.
- Flat faces carry a shading-ramp colour (128–140 = dark end of the 0x80 ramp); the engine
  shades them along the ramp by lighting. Drawing the raw byte makes them black.
- The nurse robot's textures cluster at `0x80`–`0x8c`, the dark end of the 0x80 ramp;
  Lex's textures cluster higher. The original textured rasterizer copies these indices
  directly, letting the active room palette determine their RGB values (see Face lighting).
- Mesh `TXMS/INFO` is `u16 n_static, u16 n_anim`. The animated textures are `TXMA` chunks
  after the `TXMD`s: `char name[8], u16 w, u16 h, u16 nframes, pixels[nframes][w*h]`
  (e.g. the nurse robot's eye `SLEAKEY`, 4 frames). They take texture indices
  n_static… in order. `eor.py` reads them (`Mesh.anim`): 43 across bodies and items, and all
  8,633 texture references resolve. The animation rate is unknown.
- `INITGAME/<LEVEL>.IFF` is the new-game state; `GAMEDAT/` is the saved game (the CHAOS
  `PLAY` record holds the saved player position).

## Face lighting (segs 1150/1158/1160)

- Colour of a ramp-shaded face (`FUN_1150_1eb2`): `ramp_base[ramp] + ((a · intensity + 128) >> 8)`.
  Ramp records are 17 bytes at renderer table +0x31c (base u16 @+8), built from
  `PALETTE.IFF` `RANG`. `a` is presumably the ramp length.
- Intensity 0–255 is Lambert lighting from one light object `1290:cb84`, plus ambient
  `1290:6ce0`, clamped to 255:
  - directional (`FUN_1158_09d7`): `max(0, n·L) · strength`;
  - point (`FUN_1158_0ade`): the same with L from the light position;
  - flag `cb94` selects which.
- `FUN_1158_078c` normalizes ambient and strength so that ambient + full light = `DAT_6cde`
  (presumably 255).
- Flat faces get one intensity (`FUN_1160_0d32`). Gouraud faces get one per vertex, cached
  per vertex (`FUN_1160_12e0`/`22a5`).
- Light and ambient values were long unresolved (resolved below: they stay zero). Two leads are ruled
  out:
  - `_%s_AMBIENT` / GETCAMERAAMBIENT are ambient *sound*: `FUN_1130_0e6b` calls into the
    sound manager (seg 1028), and the camera switch places the ambient sound source
    6,144 units in front of the camera.
  - `<cam>_LITE` is built in the camera switch (`FUN_1130_0114`), but only used for name
    handling there.
- Light object (20 bytes, class in seg 1158):
  - fields: s32 vec[3] (direction or position), +0xc intensity, +0xe normalized strength,
    +0x10 flag, +0x12 falloff;
  - constructor `FUN_1158_067f` sets the cap `DAT_6cde` = 256 (100%);
  - `FUN_1158_06cd` sets the vector and intensity; `FUN_1158_0773` sets the ambient `DAT_6cdc`;
  - `FUN_1158_0800` makes intensity distance-dependent (point light with falloff).
  - Startup initializer record `1290:bb78` (priority 0x20, callback `1150:1434`) calls
    `FUN_1158_067f` with `DS:cb84`, constructing the exact global object used by face shading.
    This callback is in a previously unanalysed code gap, which explains its missing C xref.
    `re/dgroup.bin` contains zeros at `cb84..cb97` and `6cdc..6ce0` before initialization.
  - A raw scan of executable far-call instructions finds the constructor call at `1150:1438`
    but no direct call to the vector, ambient, or falloff setters. Their runtime callers, if
    any, must be indirect or in unanalysed code. In particular, initializer `1158:14af`
    (`1290:bb90`) writes vtable pointers, not light values. The light direction, intensity,
    ambient, and whether they change per camera remain unresolved.
- `PALFADE.IFF` (`FORM FTBL`) looks like depth-haze data, but the shipped engine never uses
  it (resolved below, "Depth haze"):
  - `FADE` = 44 rows × 256 colour remaps. Rows 0–15 brighten along a ramp, rows 16–28 darken,
    rows 36–43 shift toward other ramps (fog colour).
  - `D_HZ` = 640 increasing distances, 4,988 → 86,878 world units.
- `FUN_1160_27b7` dispatches textured figure polygons to `FUN_1018_0ec4` when its texture
  fields are present. The previously missing seg 1018 is now decompiled in `re/decomp/1018.c`.
  Its hand-written pixel loop at `1018:13a6..13c9` reads one source byte (`MOV BL,[SI]`),
  skips palette index `0xff`, and writes every other index unchanged (`MOV ES:[DI],BL`).
  The four vertices carry ramp-shaded colors, but this textured loop does not apply those
  colors to sampled texels. The earlier preview's 40%-ramp texture brightening was an
  unsupported visual guess and has been removed. Animated textures still select a source
  frame before drawing; the room's camera palette supplies the displayed RGB colors.
- Ghidra references to `FUN_1158_06cd`, `FUN_1158_0773`, and `FUN_1158_0800` are empty;
  direct references to `1290:cb84` found by `FindScalar.java` are renderer reads in segs
  1160/1170. A scan of all relocated executable blocks found no direct far calls to those
  three setters, and a scan of initialized blocks found no static far pointers to them.
  Disassembling `1150:1434..1440` confirms the startup callback only calls
  `FUN_1158_067f` and returns.
- **Resolved (2026-10-16): the light never changes from its constructor state, so every
  intensity is 0.**
  - `FUN_1158_067f` sets falloff `+0x12` = 0, flag `+0x10` = 1 (`FUN_1158_0734`) and the cap
    `DAT_6cde` = (100 << 8) / 100 = 256 (`FUN_1158_0743`). It does not call `FUN_1158_078c`,
    so strength `+0xe` and normalized ambient `DAT_6ce0` keep their zero initial values.
  - Flag 1 selects the point-light path `FUN_1158_0ade` in every caller (segs 1160/1170).
    From its disassembly: if n·L ≤ 0 it returns `DAT_6ce0`; otherwise it returns
    `min(255, (fixmul(n·L, strength << 8) + (DAT_6ce0 << 8)) >> 8)`. Both are 0 when strength
    and ambient are 0.
  - Runtime check in DOSBox-X (debugger control port, see "Running the original"): DGROUP is
    LDT selector `040F` (limit `0xd873`, the size of `re/dgroup.bin`). During the opening,
    `6cdc..6ce1` = `0000 0001 0000` (ambient 0, cap 256, normalized ambient 0) and
    `cb84..cb97` = zero vector, intensity, and strength, flag 1, falloff 0. Sampling every 2 s
    for 4 minutes of the opening, across its camera changes, saw no change.
  - Colour: `FUN_1160_0cb8` finds the ramp holding the face colour with `FUN_1150_1ef4`. The
    test is inclusive: `start <= c <= start + last`, where `last` is the record's +0xf value
    (`RANG`: 0x70/9, 0x7a/5, 0x80/31, 0xa0/31, 0xc0/15, 0xd0/15, 0xe0/15, 0xf0/14). It stores
    the ramp index and the offset `c - start`. `FUN_1160_0ef0` then draws
    `start + ((offset · I + 128) >> 8)` (`FUN_1150_1eb2`), which is `start` for I = 0. Gouraud
    faces compute one I per vertex through the same light, so each vertex colour, and
    therefore the whole face, is also `start`. Colours outside every ramp (e.g. 0) are kept.
  - Visual check: in the VGA framebuffer (`MEMDUMPBIN 05E7:0 FA00`, mode 13h) of the opening
    cell, every untextured nursebot face is exactly index 0x80. Its mesh authors colours
    128, 130, 131, and 136 (`re/out/lighting_dosbox_ramp_base_mask.png` marks 0x80 magenta).
  - `shade_mesh` and the native `Shading.colors` implement this. Untextured faces in the shipped
    bodies are rare: 130 flat triangles, 15 flat quads, and 31 Gouraud (kind 5) triangles,
    against 7,194 textured faces. Their colours are 0 or in ramps 0x80/0xa0.
- **Depth haze: resolved (2026-10-16), the shipped engine applies none.** `PALFADE.IFF` is
  opened but its data is thrown away:
  - Palette load (`FUN_1158_0000`, called from seg 1150 for the renderer palette `1290:cc02`)
    opens `palette=` (`IMGAME.IFF`) and passes it to `FUN_1158_0080`. That reads
    `PALT`/`BLWH`/`RANG` (`FUN_1158_0283`) and then looks for a `TABL` chunk. `IMGAME.IFF`'s
    first `TABL` is the 7 bytes `palfade`; the name plus `.IFF` (`1290:6caa`) goes to
    `FUN_1158_0463`.
  - `FUN_1158_0463` (disassembled `1158:0463..0505`) opens that file, requires `FORM FTBL`
    (error `CCOLORI.C` line 0xdb otherwise), searches for chunk `D_HZ` (immediates
    `0x5f44`/`0x5a48` at `1158:04af`), and if found calls `FUN_1158_0655`, then closes the
    file. `FUN_1158_0655` is `push bp; mov bp,sp; pop bp; retf`, an empty stub. Nothing reads
    the chunk or keeps a pointer to it.
  - Nothing ever looks for `FADE`. A raw scan of every code segment for the chunk-ID immediates
    (`C7 46 xx` / `68` / `B8`–`BB` followed by `FA`/`DE`) finds only `FACE` (segs
    1178/1180/1188) and `DETA` (`1188:0704`). `D_HZ` appears only at `1158:04af`. The executable
    has no `palfade` string; the name comes only from the palette's `TABL` chunk.
  - So no draw path (room cels, flat/Gouraud figure faces, textured texels) remaps colours by
    distance. That matches the texel loop above (`1018:13a6`) and the flat colour path
    (`FUN_1160_0ef0`), which index no extra table. Distant figures keep the same indices as
    close ones, and the prototype and native renderer need no change.
  - The `Fade` class in seg 1148 (name `1290:662e`, constructor `FUN_1148_1ca5`) is the script
    `FADE` process, a kernel process. It does not touch `PALFADE`.
  - Runtime check in DOSBox-X (see "Running the original"): during the opening, every present
    LDT selector was dumped (35.5 MB over 7,651 distinct regions). It found no 32-byte window
    of the `FADE` or `D_HZ` data (offsets 0/256/1024/end, `D_HZ` also byte-swapped), while
    the control windows from `PALETTE.IFF` `PALT` and `BLWH` were found.

## Figure colours and room lighting

Figure textures index a global base palette, `DATA/PALETTE.IFF` (`FORM PALT`). Its `RANG`
chunk defines 8 dark-to-light shading ramps: 0x70 (9), 0x7a (5), 0x80 (31), 0xa0 (31),
0xc0 (15), 0xd0 (15), 0xe0 (15), 0xf0 (14). Almost all of the 149 texture indices used by
bodies fall in 0x60–0xff.

Each room's palette carries those ramps re-lit for that room, so figures take on the room's
lighting simply by being drawn with the room palette, which is what `compose.py` already does:
- ~150 rooms copy the base ramps unchanged (e.g. AIR1).
- HFR3 keeps them monotonic at ~30% brightness, so the airlock is meant to be dim and dark
  figures there are faithful.
- HFR6 tints them green.
- A few rooms (e.g. ACID) break the ramps up for their own art; probably rooms without
  figures (unverified).

`PALFADE.IFF` (`FADE` 44 × 256 index table, `D_HZ`) is never used by the shipped engine
(see "Face lighting", depth haze). `DATA/IMGAME.IFF` is a copy of `PALETTE.IFF`.

## Engine binding (`re/interp/world.py`, `movie.py`)

Placed objects (details in `re/out/figr_survey.md`):
- `FIGR`: type char[9] @0 (= `BODY/<type>.BED`), s32 pos[3] @9 (copies @82, @94),
  instance name char[9] @33.
- Viewing-camera list: u16 count c + c × char[9] camera names, ending 79 bytes before the
  record end. Find c as the value for which the u16 at `len − 79 − 9c − 2` equals c, with
  printable names and preferring c > 0 (c = 0 can also match by accident because of the last
  name's NUL padding; this happens for 5 of 49 records). E.g.
  CHAOS HALMECHO: HAL1–6, ELH1, ELH2; LANDPAD AIRMECHO: empty.
- `ITEM` (191 B): type @0 (`ITEMS/<type>.IFF`), pos @9, model name @33.
- `PLAY`: Lex in CHAOS.
- PLAYER is created by `CREATEFIGURE LEX PLAYER` (START.scr).
- The figure origin is the pelvis: FIGR z − floor z ≈ the STAND pose's foot depth (MECHO 2176
  vs 2139).

Visibility: a figure is drawn only when the current camera is in its viewing-camera list
(`FUN_1088_53e5` clears the list and hides the figure, `FUN_1088_542b` adds a camera and shows
the figure if it's the active one; `DEFINEVIEWINGCAMS` replaces the list, `ADDVIEWINGCAMS`
appends). That's why the airlock script runs `DEFINEVIEWINGCAMS HFR3, HFR6` "TO ALLOW MECHO
TO BE SEEN".

Binding semantics (assumptions marked in code):
- `GO wp` snaps to the waypoint. `GO wp WALK|RUN` turns toward the target, loops the motion
  and moves by the motion's root travel, so feet don't slide; it ends once within 614 units of the target, with no snap (see "Movement fixes"). `FUN_10d0_33c8` waits on a
  returned movement handle through `FUN_1238_0f48`, so the script resumes on arrival or
  when that movement is replaced; direct preview calls can still start it asynchronously.
- `FACE deg|name`, `TURN n` (n degrees, positive = left; NOTES "Items and combat").
- `MOTION name [n] [CONTINUE|FREEZE|SNAP_TO|NO_SCRIPT]` (`FUN_10d0_5e8b`): starts the motion now
  (optional start frame n). Without CONTINUE the script blocks until the motion finishes
  (`FUN_1238_0f48`); CONTINUE returns at once; SNAP_TO snaps the pose. FREEZE does not pause the
  animation: it only clears the idle-fallback bit (see "Movement fixes"; the first port held the start frame).
- `SNAPTOPOSE name frame [FREEZE]` sets a pose directly.
- `CREATEFIGURE LEX PLAYER` makes a figure named LEX and flags it as the player; `PLAYER` is
  an argument keyword that resolves to the player figure.
- Motion playback: a frame lasts `MY_SPEED` × the motion's frame time, adjusted by difficulty (see "Motion timing and turning motions").
- `CAMERA cam` sets the active camera.
- Room sprite frames come from the globals `_<SPRITE>_FRAME`. In HFR3, `_door_frame` drives
  sprite `DOOR` (21 frames).

```bash
re/.venv/bin/python -I re/interp/movie.py LANDPAD MEETMECH re/out/airlock.gif --ticks 260
re/.venv/bin/python -I -W ignore -m unittest discover -s re/interp -p 'test_*.py'
```

## Opening nurse encounter and movement collision (2026-10-13)

- `START.scr` loads CHAOS at `PLAYLOC`. `AWAKEN.scr` starts FIRSTBOT in recoil, then
  `GOODMORNINGLEX` releases its AI after the opening speech. Lex receives `MONBAT` as
  `MY_BATTERY` in `INVENTORY` (`ITEMS.scr:1386-1394`); no right-hand weapon is provided.
  `AI_LEX.scr:215-250` accepts `LEX_ATK_SHOOT` only for a right-hand grenade, a charged
  PFD, or a right-hand blaster/tonfa. The preview now executes that block on Space and
  models item type, owner and slot for its `ISCARRYING` predicates; unarmed Space does
  nothing. Full item interaction and inventory UI are not implemented.
- `AI_NURSE.scr:6-84,170-200` drives the approach and syringe. A second syringe hit starts
  Lex's knockout and `REVIVELEX` (`AWAKEN.scr:334-381`). The initial DR3 doorway has
  PHYS state 0 and requires no nurse kill or opening block: Lex can leave CE3 and cameras
  change through their acceptance volumes. The nurse later repeats its attack loop.
- The movement path is `FUN_10a0_22e1` (candidate-position and interpolated steps) →
  `FUN_10a0_21b2` (rebuild hull) → `FUN_1058_1a1b` (PHYS query) → `FUN_1058_142d`
  (3D AABB overlap). `COLLISIONS` handler `FUN_10d0_1aa4` toggles figure flag bit 0x02:
  ON clears the bit, permitting the collision check. With a figure PHYS list,
  state 1 overlap returns a blocker; state 0 is empty and state 2 is neutral. The
  previous signed point rule from `FUN_1130_07f6` belongs to a camera-side query and
  is not used for preview movement. The no-list fallback `FUN_1058_192f` scans the global
  PHYS list with the same score as `FUN_1058_1a1b` (below).
- `FUN_1138_1853` builds ordered area anchors from state-0 PHYS entries and entries with an
  existing `_<name>_SPACE` binding (the `_SPACE` value is copied to +0x4a first). Each anchor gets a
  RoomType node (`FUN_1138_131c`, 0x1e bytes: +0 trigger count, +2 triggers, +6 trigger indices,
  +0xa/+0xc `physical_objs`, +0x10/+0x12 `rooms`, +0x16 anchor PHYS, +0x1a next). `physical_objs`,
  which `FUN_1058_1a1b` scores, is every PHYS of the level (DGROUP 0x1cf5 count / 0x1cfd list),
  solids included, whose box touches (`FUN_1068_0934`, inclusive) the anchor's box grown by 0x1000
  on each side; `131c` grows the anchor PHYS in place and shrinks it back afterwards. Its trigger
  list uses the IMAG objects (0x1ce9/0x1cf1) touching the ungrown box. Correction (2026-10-16): the
  eligible anchors touching each anchor's ungrown box form the separate `rooms` list (built in
  `1853`), not the scored member list; the ports had used that list and now use `physical_objs`.
  In CHAOS, CE3's list grows from DR3, CE3 to DR3, CT3, CE3, CL3, CL1, BLK, J01, J02; the
  closed-DR3 walk is unchanged. `FUN_1138_1a93`
  keeps the current area while its box contains the figure origin, otherwise takes the first
  containing area, then the first area overlapping the figure hull, otherwise keeps the old
  area. The ports recompute candidate lists from current VM bindings; the original builds
  them at level setup/reset; late-created bindings still need an original-game check.
- Collision score (`FUN_1058_192f` disassembly; `FUN_1058_1a1b` uses the same rule over the
  area's members): start from the query volume at query+0x24, ADD/ADC each state-1 overlap
  (the largest becomes the collider far pointer at +0x28), SUB/SBB each state-0 overlap,
  ignore state 2; return signed 32-bit `score > 0`. Volumes (`FUN_1058_12c7` for the query,
  `FUN_1058_142d` for overlaps) multiply x*y, keep the low 32 bits and shift right 8, then
  multiply by z and shift 8 again; truncation makes axis order matter, and a hull straddling
  two spaces that only touch keeps a small positive remainder (blocked), so level spaces
  overlap. Outside every space the hull volume alone blocks; a neutral doorway blocks.
- `FUN_10a0_21b2`, after rebuilding the hull and selecting the area, stores the support
  (`FUN_1060_03f2`) at +0xee and, when `sup + R <= lo.z < sup` and `sup < hi.z`, sets the hull
  bottom to `sup` and recomputes the volume. Figures stand at `sup + F`, so a negative root z
  (the walk's bob) would otherwise push the hull into the floor. After `FUN_1058_1a1b` passes,
  `FUN_10a0_22e1` still blocks while `sup > lo.z` (a step higher than the lift). Both ports do this.
- Live check (DOSBox-X, opening, Lex in bed, 2026-10-16): record z −5754 (record z already
  includes R), F 2312, R −40; query hull (−11312, −7649, −8047)–(−10576, −6913, −4567), spans
  (736, 736, 3480), volume 28764: all equal the ports' hull and fixed-point volume.
- `FIGURES.scr:582` defines `LEX EXTENT=(18,18,58)`. `FUN_1088_2a87` reads that property
  and calls `FUN_10a0_0000`/`FUN_1070_08df`, which set local hull bounds at figure
  offsets +0x39..+0x4d; `FUN_1058_0f95` translates them into two AABBs at +0x65.
  The preview now uses the same recovered hull as grounding: 20.48 world units/cm,
  the current motion frame's root z, and an F-derived bottom. `.COL` files load
  separately as ten 6-byte records at figure +0x139 (`FUN_1088_5fe6`); no evidence
  links their fields to this movement hull, so they remain uninterpreted.
- Mover stepping (`FUN_10a0_22e1`, collisions on): d = target − position. If every axis of d
  is below the local hull span (+0x51/55/59), one check at the target. Otherwise n = the
  integer part of the 24.8 ratio `FUN_1210_0f9b(d)` / smallest query span (`FUN_1058_1bdc`),
  where `0f9b` approximates a length (|v| sorted a ≥ b ≥ c: a + c>>2 + b>>2 + b>>3 − b>>5) and
  `FUN_1210_0c24` is the 24.8 divide trunc((a<<8)/b); each of the n steps adds trunc(d/n),
  rebuilds the hull (`FUN_10a0_21b2`) and blocks on `FUN_1058_1a1b` or a support above the hull
  bottom. A passing step is stored at +0xe2 (last good). After the loop the target itself is
  checked. A blocked step scales the step +0xd2/d6/da by i/n (`0c42` multiply, `0c24`
  divide: trunc(c·i/n)) and returns with the figure at the blocked position. The 3D length
  (z included in the span test, the length and the steps) matters once velocity moves z. `FUN_1088_50c1` (after each
  passing step of the loop, not for the final target check) stops the move, the figure at that
  step, when the hull enters a trigger of its area that has a block (IMAG +0x4a) and whose
  InTrig byte is clear (see "IMAG triggers"); both ports do this. The step scaling is modelled in the Python
  ports (`scale_step` / `scaleStep`).
- Collision response (`FUN_1088_3629`'s caller re-tests the hull after the move and calls
  vtable +0x5c, `FUN_10a0_0ead`; full spec 2026-10-22, both ports: `collision_response` / `vertical_response` in world.py, `collisionResponse` / `verticalResponse` in WorldPlay.swift). Entry: the hull collides (`1a1b`) or the
  support is above the hull bottom. Frame start position +0xba, last good +0xe2. `SetPos raw` (`FUN_10a0_2158`) sets +0x1e8
  around vtable +0x58: position, last good and previous := p, hull / area / support rebuilt, all velocities zeroed, no floor
  snap (a plain SetPos stands a gravity figure on its floor). With z velocity: not falling -> raw SetPos at the last good
  position; the player first tries the previous x, y at the new z and, if that hull is free, only drops vx, vy and keeps
  falling; otherwise the landing: falling cleared, fall-end method (+0x229--), previous x, y, z when the support is over
  0x1000 above the entry hull bottom else the hull bottom on the support, `FUN_1130_1a2d` (SetPos, then up to 40 nudges of
  i << 8 units, x + for i & 3 = 0, 2 and y - for 1, 3, until the global PHYS score is clear with z unchanged -- which the
  F/s mismatch (2312 vs 2294) means never happens, so it ends with the original x, y snapped to the floor), raw SetPos,
  `0e24` landing motion (vz is already zero, so land_soft; hard <= -0x280, medium <= -0x140 are dead here). Zero z velocity:
  **step-up** first: support above the hull bottom and below bottom + k - R (k = fig+0x14a = hull dz / 4, R = model+0xa6 =
  the frame's root z) lifts z onto the support and returns (no slide). That is what lets Lex walk LANDPAD's DR9 -> HFR (a
  51-unit floor step; k - R ~ 910-990): the walk stalled before it was ported. Then, unless the +0x1e8 guard is set or the last
  good position is exactly (0, 0, 0), the slide: the blocked y with the start x, then the blocked x with the start y, else
  the last good position (raw SetPos); a straight push into a wall therefore never advances part way, an oblique one slides.
  Tail: vx, vy, vz zeroed; the **mantle** when the collider (`FUN_1070_0f68`: +0x8d, the largest state-1 overlap, else the
  area's PHYS) has flag byte 21 & 2, is not the area's PHYS, the motion is exactly lower-case `walk`, its top is above the hull
  bottom, |top - support| <= 0x1000, the facing is within 15 degrees of an axis and the hull lies inside the collider's box
  shrunk by 0x266 (`0ae5`; the facing snaps onto the axis): `0d93` requests mantle_3 (< 0x800), mantle_6 (< 0x1000) or
  mantle_9; then the `_<type>_BONK_<motion>_<collider material>` sound (silent in the shipped data). The port stores motion
  names upper case; the engine's own requests are lower case, so `Figure.engine_request` (set for the player's key motions)
  stands for "lower case": a script's `WALK` does not mantle (ASSUMPTION, not checked live). ASSUMPTIONS: the collider is the
  blocked hull's, not the slide's last candidate; the engine yaw is the port heading (only the snap onto an axis matters);
  the port has no mantle script blocks (`<TYPE>_MANTLE_n`) in the shipped scripts, so the motion plays. The bouncy path is
  `bounce` / `bounce_collision` (`FUN_1070_0fa7`, flag 0x10). `FUN_1070_0f68` returns the collider PHYS or the area's PHYS, never a figure.
- Figure push (`FUN_1088_3629`, before every move of a living figure (~0 > 0) with collisions
  on): every other figure that is not hidden (flag 0x04 with +0xf6 clear), has ~0 > 0 and
  collisions on moves the target out of the circle of the two figures' summed radius
  (+0x1e3, `PERSONAL_RADIUS` from the figure's FIGURES.SCP block, default 45 cm, at the hull
  scale: Lex and GUARD1 819, FIRSTBOT and USE_BOT 1126, CAYNAN 880, FIDO 1433, HALMECHO 3686,
  all confirmed live). `FUN_1098_096e`: d = other − target; dist = `FUN_1210_000d` (normalise
  until the larger of |x|, |y| reaches 0x1000 by `FUN_1208_0b86`, or falls to 0x40000 by
  `0c65`; isqrt(((x² >> 8) + (y² >> 8)) << 8), `FUN_1210_1047`; undo the shift). If dist < R:
  q = (R << 4) / dist as an integer, target = other − (d·q) >> 4 (through the 24.8 multiply), z
  kept. The integer q means an overlap below about R/16 does not push. The engine moves every
  figure every frame, so a standing figure is pushed too. The same function then applies the
  `ADDAVOIDANCEPOINT` points (see "Avoidance points").
- Object locals: figure +0x92 holds the ten script object locals `~0..~9` (DOSBox-X: FIRSTBOT
  [50, 0, 0, 1, 0, 50, …], GUARD1 [100, …, 170, …]). `FUN_1088_22ba` sets ~5 from `MAX HPS`
  (default 100) and, for a new figure, ~0 = ~5. Level figures keep their FIGR record's locals,
  which match live exactly. Both ports now seed them; `FUN_1120_0763` reads properties from the
  block named after the figure's instance (+0xf7), falling back (ASSUMPTION) to its type.
- Live check (2026-10-16, `dosbox_live.py --hold 48@84+10 --phys DR3=1`): with DR3 closed the
  original stops Lex at y −14100 for the whole hold, sliding in x (−9529 … −9665); the Python
  port, given the same input from its own wake position, also stops at y −14100 and slides
  by a similar amount. Re-run after the `physical_objs` correction: the original again stops at
  y −14100 (x −9462 … −9594). The Python port walked from x −9529, heading −y, ends at y −14128
  sliding to x −8494, identical before and after the correction; from its own wake path it
  reaches the wall west of DR3 (x ≈ −11900) at y −14130. The last ~30 units are a slow creep of
  the wall slide (3 units per slide), which the original stops sooner.
- Live check of the push (2026-10-16): OUT_OF_BED ends at (−10795, −9610) in both the original
  and the port; on the next frame, with collisions on, the original pushes Lex away from the
  nurse (FIRSTBOT, hovering beside the bed), to (−10270, −8879) in one run, which is exactly the
  push from her sampled position. The nurse's curved path to (−11360, −10489) during ATK_M7 is
  now reproduced (see "Motion timing and turning motions"); the port ends at (−11201, −10586).
  `scenarios.opening_escape` walks straight: the push carries Lex across to x ≈ −9750 and
  through DR3. `AUTO_TURN_SPEED` (+0x1df) is not involved there: its only reader, `FUN_1088_3419`, turns the
  player in combat mode only while the motion is atk_m* (not atk_m4 / atk_m6), `atk_stand` or `shoot`, which the unarmed opening walk does not use (see "Combat auto-turn and collision default" below).

### Combat auto-turn and collision default (recovered 2026-10-22; both ports)

- **Collision follows flag 0x02.** The mover `FUN_10a0_22e1` runs the PHYS test when figure flag 0x02 (+0x34) is CLEAR;
  `COLLISIONS CURFIG ON|OFF` (`FUN_10d0_1aa4`) clears / sets it. All 49 FIGR figures in the shipped levels have it clear, and
  CREATEFIGURE's base constructor clears +0x34, so every figure collides unless its record or a COLLISIONS OFF says otherwise.
  Python: `Figure.collisions` is now a read-only property (`not no_collide`); the old opt-in `collisions = False` default is
  gone, and the figure push (`FUN_1088_3629`) uses the same condition. Effects on the scenarios: the opening runs (escape,
  nurse defeat) are unchanged except the `collisions` fields (the revival run gains one hit: ZAP.scr's `DAMAGE 20 ENERGY` on
  FIRSTBOT now raises `GOT_HIT`, a repeated nurse subtitle at tick 2152); the input-driven nurse run (`opening_keys`) moves Lex
  to (-9825, -13275) instead of (-9971, -13241) at the SHOCK_BACK checkpoint (the wounded nurse now also runs
  `NURSEBOT_WOUNDS`). LANDPAD's scripted walk `LEX_POS -> LEX_POS2`
  (AIRHALL `MARCHOUTAIRMECHO`, no COLLISIONS OFF for Lex) first stalled at x = -32151 on the 51-unit floor step DR9 (-7417) ->
  HFR (-7366): the mover blocked on `support > hull bottom`. The step-up of `FUN_10a0_0ead` (k - R ~ 910-990 > 51, see
  "Collision response") fixes it; the `landpad_meetmech` scenario now runs with collisions on and matches the old output. The
  tests that only exercise GO / MOTION without that script (`test_world.Motions`, `test_go_walk_arrives_and_stands`) keep
  Lex's collisions off because DR9 then stays at its closed file state.
- **Auto-turn** `FUN_1088_3419` (called from `FUN_1088_39ef` for the player only, in combat mode, with a game running): needs an
  enemy (+0x195) and `AUTO_TURN_SPEED` >= 1 (FIGURES.SCP; Lex 1); counter +0x1e1 increments per call and acts when it reaches
  the speed, then resets. Only while the motion name (lower case) starts `atk_m` but is not `atk_m4` / `atk_m6`, or is
  `atk_stand` or `shoot`. With a = the enemy's bearing from the facing in degrees (`FUN_1088_5ee1`, positive = left), if
  3 <= |a| < 55 (`> 2` and `< 0x37`) it rotates `min(|a| >> 1, 6)` degrees toward the enemy (`FUN_10a0_19e6`).
  Python `World.auto_turn`, run each figure update after the push; ASSUMPTIONS: a is rounded to whole degrees, the counter
  resets whenever it reaches the speed regardless of the motion.
- **DAMAGE statement** (`FUN_10d0_230e`): `FUN_1090_09b9(current figure, no attacker, n, 1 if ENERGY else 0, zone 6, not heavy)`.
  Python's `DAMAGE` handler now calls `World.damage` (it used to subtract from ~0 only), so scripted DAMAGE (ZAP, MISSILES)
  applies the difficulty adjustment, armour, labels, WOUNDS / DEATH. Not ported: `FUN_1258_0f8b()` for a player target.
  Python `World.damage(target, attacker, dmg, type, zone, heavy)` now also has: armour by type (IMPACT_ARMOR / ENERGY_ARMOR),
  `ENERGY_DAMAGE` and `KILLED_PLAYER` / `PLAYER_ENERGY_DAMAGE` (type 1), an optional attacker (no ELITE check, knockback,
  attacker labels; motion name "Unknown"), zone 6 (no `GOT_HIT_<zone>`, no recoil), the `_<A>_HITS_<T>_<camera>` and
  `_BLOCK_<T>[_<A>]` sounds (MATERIAL from the TYPE block; both through the cutting lookup 1118:0044, so they play
  `_<A>_HITS_<T>` and `_BLOCK`; see "Motion sound cues and formatted sound names"), `<TYPE>_WOUNDS`, and on death the die method (`World.die_method`: +0x229 raised, AI process
  suspended, player input ignored; task +0x15b not ported), invulnerability and `<INSTANCE>_DEATH`. Knockback subtracts the
  attacker's orientation row 1 (x256; = −forward) from the bouncy target's velocity, i.e. pushes it away from the attacker; both
  ports apply it through the persistent velocity (see "Persistent velocity").
  Swift: `WorldCombat.swift` (`damage`, `autoTurn`, `dieMethod`, `material`, `hitSound`), `WorldPlay.swift` (`setPos`, `collisionResponse`,
  `verticalResponse`, `unstick`, `mantleFits`, `fallStart` / `fallEnd`), tests `HitTests.swift`, `CollisionResponseTests.swift`; the
  tests use small internal seams (`labelProbe`, `soundNameProbe`, `blockProbe`, `propOverrides`, `setPosTrace`). The native-resume digest
  in `SaveLoadTests` changed because the two nurse hits on Lex now run `LEX_WOUNDS` (engine calls in the log).

## Motion timing and turning motions (recovered 2026-10-16; both ports)

- Frame time: `FUN_1098_0088` stores model+0x102 = speed × motion+0x52, where speed (+0xea) is
  the figure's `MY_SPEED` (FIGURES.SCP, default 512 at `[249c]`, read by `FUN_1088_22ba`) and
  motion+0x52 is MOTN header byte 76 (the in-memory header sits 6 bytes after the file's: +0x57
  is the frame count at byte 81, +0x26 the event list at 32, +0x24 the flags at 30).
  `FUN_1088_1854` computes the frame as ((`[8330]` << 8) − start) / (+0x102) on the 60 Hz clock, so
  one frame lasts speed × frame time / 256 clock ticks (FIRSTBOT: ACTIVATE 15 = 4 fps, ATK_STAND 6,
  ATK_M7 3 = 20 fps; Lex WAKE_UP 6, OUT_OF_BED and WALK 4.5). Both ports advance figure phase by
  512 per 30 Hz VM tick and step a frame per speed × frame time, replacing the old 2-ticks-a-frame
  assumption. Live (`dosbox_live.py --only FIRSTBOT`): ACTIVATE frames 0–25 take 6.3 s, ATK_M7 runs
  at ~21 fps. The opening now follows the original's clock: Lex starts WAKE_UP ~74 s, OUT_OF_BED
  ~77 s and stands ~80 s live; the port mapped to 74.8, 77.9 and 80.7 s (stands at tick 1129); since the QUAKE
  decay ramps (2026-10-31, "Audio: voice statements ...") 30 ticks later: 75.8, 78.9, 81.7 s, tick 1155 (not re-checked live).
  `FUN_1088_5e4d` can rescale +0xea to fit a motion into a given time (caller not identified).
- Difficulty adjustment (correction, 2026-10-17; `FUN_1098_0088` disassembly): after the product,
  a figure other than the player gets +0x102 −= [a36e] << 6, or += 0x80 when [a36e] is 0. [a36e] is
  the difficulty level (`FUN_1280_2335` stores it with `_difficulty_level`; saves restore it,
  `1148.c`), so enemies animate faster on harder levels. Live at Medium (DOSBox-X, model+0x102):
  FIRSTBOT ACTIVATE 3776, ATK_M7 704, ATK_STAND 1472 = 384 × 10/2/4 − 64. The player instead
  gets no level adjustment, but repeating the same attack whose name starts ATK_H or ATK_F (not
  ATK_F2, ATK_SHO or ATK_F9) adds count × 64 × level × 16 (16-bit IMUL, count at +0x13e, last name
  at +0x12a); an ATK_F9 attack starts a timer ([2958]) after which, 0x2d clock ticks on, the count
  clears; any other motion clears it. +0xfe is then +0x102 × +0xf6. Both ports apply this once
  per motion start (`World.motion_duration` / `motionDuration`). The earlier "the port plays 40
  frames, the live runs ~43" was this −64: ATK_M7 runs 2.75 clock ticks a frame live, not 3.
  The frame times themselves (header byte 76: ACTIVATE 10, ATK_STAND 4, ATK_M7 2) were right;
  the figures quoted above (15, 6, 3) are not. `WAIT` runs at 30 − [66c6] per second and the
  engine at 60 − 2·[66c6]: [66c6] is the `Speed_Factor` slowdown that `DETERMINEMACHINESPEED` /
  `INCVIRTUALSECONDS` raise on a slow machine (INSTALL.OPT `Speed_Factor`, `_TimeTest`); it stayed
  0 in DOSBox-X at 35000 cycles, and the ports assume 0.
- Turning motions: header flag bit 0x01 (75 motions, e.g. NURSEBOT ATK_M4/M6/M7/M9, BOUNCE,
  RECOIL_TL/TR, MAN TURN_LEFT/RIGHT(_FAST), LEX_GETS_UP). At a loop wrap `FUN_1088_1854` applies
  the last frame's root step, clears the root base (+0xd1..+0xdb) so the first frame moves from 0,
  and calls `FUN_10a0_1c83`: d = model+0x25 (the current root-limb yaw, limb 0 angle[2]) − frame 0's
  yaw; the orientation is rotated about z by d × 45 / 32 degrees (`FUN_1208_2f60`) and the yaw offset
  +0x2d/+0x25 is reduced by d. A negative yaw turns right (COMPASS heading grows). `FUN_1098_0789`
  (motion stop/change) and `PLANTFEET` (`FUN_10d0_65fa`) call it too, so a replaced turning motion
  keeps the yaw reached. ATK_M7's root yaw ends at −7: +9.84° per cycle. Live, ATK_M7 runs 6 wraps
  in WAIT 60 (153.2° → 212.2°), moving −x first and then curving toward the bed; the port plays 40
  frames (5 wraps + the change bake) and ends 186 units from the live end. The port does not model
  the +0x2d offset (only `PLANTFEET` would need it; no script uses it), or the motion-start
  blend described below.
- Rendered pose interpolation (2026-10-18, both ports): `FUN_1088_1854` calculates an integer
  frame index plus a fractional cursor from elapsed clock / frame duration; `FUN_1088_0d63`
  interpolates the root coordinates and limb angles toward the next interior frame. Python and
  Swift now sample limb angles and root z at `phase / motion_duration` for rendering, truncating
  each angle toward zero; root x/y travel remains in the discrete world mover. Since 2026-11-12 the drawn position adds the blended
  part of the next frame's root x/y (`subframe_root`), through the figure's matrix: with the limbs blended and the position only
  stepped per frame, a travelling body slid back within each frame and jumped forward at the next (OUT_OF_BED frame 36: back 266,
  then forward 384, seen as a flicker while Lex gets out of bed). From the code (`FUN_1088_0d63` blends the root coordinates); not
  compared live. The root-angle
  words are copied from the current frame. The final frame holds until the next cycle wraps,
  when the existing root reset / turning bake runs. The sampled scene and scenario frames match
  between the two ports after regenerating the oracle fixtures.
- Motion-start blend: `FUN_1098_0394` calls `FUN_1088_0cab` for ordinary motion changes and stores
  `max(abs(target first-frame angle − current angle)) / 10` (integer quotient; `DAT_1290_24a0`
  is 10) at model+0x128. RECOIL, ATK_F2 and SUPER_REC, or a false blend parameter, skip it.
  `FUN_1038_0c00` sign-extends PRLE angle bytes without scaling; POSE angles are s16. The
  +0x128 value is compared to the Q1.15 fractional-frame cursor by `FUN_1088_1854`, so even
  a 255-unit difference lasts at most 25/32768 of a motion frame, shorter than the ports'
  30 Hz render sample. Both ports therefore start directly at the new motion's first pose.
  Exact sub-frame interpolation is still unmodelled.
- Held turn keys play TURN_LEFT/RIGHT(_FAST), whose root yaw reaches ±64 (90°) per cycle; the
  ports no longer add a per-tick turn for them. The 3°/tick `turn` input of the scenario API stays.
- Avoidance points do not affect the nurse's path (see "Avoidance points").

## Melee hits: reach, timing, zones and damage (recovered 2026-10-22; implemented in both ports)

Python (`world.update_hit` / `col_hit` / `hit_zone` / `damage`, `salsa.load_col`, tests in `test_hits.py`) implements
everything below (the knockback, sounds, energy damage, WOUNDS / DEATH and the DAMAGE statement were added 2026-10-22 in both ports, see
"Combat auto-turn and collision default"). Swift mirrors it in `WorldCombat.swift` (`updateHit`, `colHit`,
`hitZone`, `damage`, `ColVolume.load`, `MotionFrame.guardByte`; tests in `HitTests.swift`, the oracle fixtures regenerated). Port findings:
- **Guard table = the frame "root angle" words.** Frame row bytes 12..17 (the `r` tuple read as three s16) are
  never rotations: across all MTN files they hold codes 0-3, sometimes with 0x40/0x80 set (MAN ATK_H1 frame 6
  `03 03 02 02 00 00`, NURSEBOT DEFEND `02 02 02 02 03 03`; nurse STAND `03 03` in every frame). They are the
  `FUN_1088_0708` guard bytes: current frame record + 0x0c + zone (TL TR ML MR BL BR), the in-memory record starting
  with the root pos s32[3]. `(byte & 3) == 2` and |bearing| < 110 blocks the hit (sound `_metal_clank_1`, no damage,
  per-play flag set, hits row label `BLOCKED`); `(byte & 3) == 1` or strength > 19 is heavy. Applying them as root
  rotation had flipped bodies on strike frames (ATK_H8 frames 7/8 `82 82`, ATK_SYRINGE frames 4/5 `40 40`), so
  `salsa.solve` now keeps the root matrix at identity (renderer, hand poses, hit geometry; native fixtures `stage2`
  poses/scenes, NURSEBOT/CAYNAN pose_bits, boot/escape/revival/keys runs change).
- **Motion-task cancel.** After the damage is applied and before the GOT_HIT labels `FUN_1090_09b9` calls
  `FUN_1098_0789(target, 1, 0)`, ending the target's script-started motion (`World.damage` uses `Figure.stop_motion`,
  the STOPMOTION equivalent) unless it is playing an unfinished DIE. Motion names for `GOT_HIT_<zone>_<motion>` /
  `HIT_PLAYER_<motion>` are read before it. Afterwards the recoil plays when ~3 == 0 (so a nurse in ATK_STAND recoils,
  as live). Not blocked by the cancel: a target with an unfinished DIE neither cancels nor recoils.
- ~3 = 1 (`_ATK_STATUS_RECOIL`) makes `NURSEBOT_AI` idle; the port clears it when the recoil motion ends or is
  replaced (ASSUMPTION, the original's clearing site is not recovered). The recoil plays once (a looping
  `MOTION ... CONTINUE` would repeat the turning RECOIL_*).
- Hit ticks in the opening nurse scenario moved from 1180/1223 (middle frame 6) to 1183/1229 (first frame whose
  limb end is inside a cube), which changes the later closed-loop push/corridor route (see test_scenarios).

- **Motion header attack fields** (in memory = file byte + 6): +0x1e strength (file 24),
  +0x1f striking limb index (file 25), +0x25 kind (file 31): 1 strike, 2 guard/defend
  (DUCK, ATK_H1–H3, nurse DEFEND/BOUNCE/ZAPPED), 3 movement (ATK_M*, RUN, TURN_*), 0 other.
  Examples: MAN ATK_H8 strength 25 limb 17 (13 frames); ATK_F9 25/13; NURSEBOT ATK_SYRINGE 5/13
  (10 frames); FIDO CLAW_LEFT/RIGHT 16 with limbs 10/7.
- **Hit test** `FUN_1088_0708(model)`, called from the per-frame model update
  `FUN_1088_2035` after the frame advance (`FUN_1088_1854`), except on the motion's last frame. Conditions:
  current frame (+0x119) > 3, frame count (+0xf6) − (frame + 1) (+0x11d) > 3, no start
  blend (+0x128 == 0), motion kind == 1, figure has an enemy (+0x195), and the per-play
  flag +0xe5 clear (cleared when a motion is set, `FUN_1098_0000`; set on a hit). So a strike
  can land on any frame 4 … nframes−5, once per play. ATK_H8: frames 4–8; ATK_SYRINGE: 4–5.
  If the attacker is not the player (`DAT_1290_2a66`), the player's +0x195 is set to the
  attacker.
- **Reach**: the striking limb's END (limb record +0x21, s32 world) is tested against the
  enemy's ten collision volumes (figure +0x139, from `<BODY>.COL`); on a miss, the point
  end + row1·(`0c42(length +0x5e, scale +0x17 << 8)` >> 8) (one more scaled limb length
  along the limb) is tested. Either hit counts.
- **`.COL` volumes** (`FUN_1088_5fe6` loads 60 bytes = 10 × 6, test `FUN_10b0_0031`):
  u8 limb, u8 mode, s32 half-size (world units; all zero = unused). Centre = that limb's end
  if mode == 0, else end − row1·(scaled length >> 9) (the limb midpoint). Hit when
  |dx|, |dy| and |dz| are all < half-size (axis-aligned cube). NURSEBOT.COL: (8,1,280),
  (10,0,220), (14,1,560), (3,1,480), (7,1,200).
- **Zone**: h = F (model+0x88) × 0.16 (`0c24(0c42(F,0x1000),0x6400)`). Point z > enemy root z
  + h → top (0), z < root z − h → bottom (4), else middle (2); +1 when the enemy's vtable
  +0x60 (called with the attacker's position +0x31..+0x3b) returns a negative value. Zone names
  (DS:0x2756): TL TR ML MR BL BR. ASSUMPTION: +0x60 is the signed angle of the attacker from
  the enemy's facing, in degrees (not yet decompiled).
- **Guard**: byte = element 0 of the enemy model's +0x10e list (the current frame record; `FUN_1088_5ee1` reads
  element 1's root yaw at +0x16) at +0x0c + zone: the frame row's bytes 12..17 (see the port findings above). If
  (byte & 3) == 2 and the +0x60 value's magnitude is < 0x6e, the hit is blocked: sound `_metal_clank_1`, no dispatch.
  Otherwise `FUN_1090_09b9(enemy, attacker, strength, type 0, zone, heavy)` with heavy =
  (byte & 3) == 1 or strength > 19.
- **Damage** `FUN_1090_09b9(target, attacker, dmg, type, zone, heavy)`:
  - An attacker named `elite` (string compare at +0xf7) does no damage: unless the target is
    invulnerable it only raises `HIT_PLAYER_FOR_ZERO` on the attacker. Targets with HP (+0x92) ≤ 0 are ignored.
  - Bouncy (0x10) and not invulnerable: subtract the attacker's vtable +0x20 vector from
    target +0xc6/+0xca/+0xce (knockback: v −= row 1 = −forward, away from the attacker; see "Persistent velocity").
  - Difficulty `DAT_1290_a36e`: player target dmg −4 (difficulty 0) or +4·difficulty;
    others dmg −4·difficulty.
  - Invulnerable (0x08) or dmg < 1: `HIT_PLAYER_FOR_ZERO` on target's enemy, `HIT_FOR_ZERO` on
    target, sound `_BLOCK_<attacker MATERIAL>_<target MATERIAL>`; stop.
  - Armour: type 0 subtracts +0x142, type 1 +0x144; clamp ≥ 0. HP −= dmg; +0xae −= dmg
    (clamped ≥ 0). `ENERGY_DAMAGE` (type 1 only), `KILLED_PLAYER` / `PLAYER_ENERGY_DAMAGE`.
    Sound `_<attacker MATERIAL>_HITS_<target MATERIAL>_<camera>` (FUN_1100_1ce4: positional at the target, priority 1), through
    1118:0044. The block sound above goes through FUN_1100_1d34: not positional, priority 1.
  - Still alive: `GOT_HIT_<zone>_<own motion>` (zone 6 = none skips), else `GOT_HIT_<zone>`;
    then always `GOT_HIT`; `MY_HPS_75/50/25` when crossing those thresholds (and
    `PLAYERS_HPS_*` on the attacker for a player target); heavy: `SUPER_RECOIL` (or
    `PLAYER_SUPER_RECOILED` on the attacker); player target: `HIT_PLAYER` then
    `HIT_PLAYER_<attacker's motion name>` on the attacker ("Unknown" without one). If the target has no current motion
    (+0x13d), it plays `recoil_<zone>` (or `super_rec_<zone>` when heavy), falling back to
    `recoil_tl`/`recoil_tr` by side, through vtable +0x7c, unless ~3 (+0x9e) is set; then ~3 = 1.
  - Dead: `KILLED_PLAYER` on the attacker for a player target, `<name>_DEATH`, vtable +0x9c, set
    invulnerable.
  - Each label goes through `FUN_1090_12a6(fig, dmg, fmt, …)`: if the figure has a stimulus
    block (+0x157) of kind 1, run it at that label with local ~0 (`_DAMAGE`) = dmg; returns
    whether the label existed. `FIRSTBOT_STIMULUS` has `:GOT_HIT` and
    `:HIT_PLAYER_ATK_SYRINGE`.
- vtable +0x60 is `FUN_1088_5ee1`: `FUN_1070_2271` (bearing of the point from the figure's
  facing, degrees) corrected by the frame-0 vs current root yaw, wrapped to −180…179; the
  same bearing as ANGLEFROMENEMY. Negative = right (zone +1).
- Armour: `FUN_1088_2a87` reads `IMPACT_ARMOR` (+0x142) and `ENERGY_ARMOR` (+0x144) from
  FIGURES.SCP. FIRSTBOT has IMPACT_ARMOR 100, so Lex's punches do 0 damage while `GOT_HIT`
  and `recoil_tl` still run: this matches the six-punch live run (nurse health 50 unchanged).
- Locals are s32: +0x92 = ~0 (HP), +0x9e = ~3 (recoil sets it to 1), +0xae = ~7.
- Live check (`re/out/fall_live/combat`, original clock 14029–14051): from the captured poses
  (Lex (−10145, −10605) facing −4.0°, FIRSTBOT (−10035, −12475) facing 174.8° in atk_stand) the
  original put the nurse into recoil_tl at Lex's ATK_H8 frame 7, health 50, ~3 = 1. The Python
  port reproduces all four from the same poses (`test_hits.test_live_capture_first_punch_lands_on_frame_7`).
- Open: the original's ~3 clearing site. (Knockback now moves the target in the Python port, see "Persistent velocity".)

## Avoidance points (recovered 2026-10-16; both ports)

- `ADDAVOIDANCEPOINT <object> <radius cm>` (handler `10d0:0178`): needs a current figure, a radius
  (s32 +0xe2b) > 0 and an object found by name (`FUN_1050_0129`), else it prints an error.
  `FUN_1098_0b88` clamps a negative count (+0x1f3) to 0, refuses a full list (8), and ignores an
  object already listed (its radius is not updated); otherwise it appends the far object pointer
  (+0x1f5 + 4i) and the radius's low word (+0x215 + 2i). `REMOVEAVOIDANCEPOINT` (`FUN_1098_0c52`)
  scans slots 0..6 only (an entry in slot 7 cannot be removed), shifts later entries down, and
  clears slot 7's pointer.
- `FUN_1088_3629`, after the figure-figure loop and still only for a living figure (~0 > 0): every
  entry with a non-null pointer pushes the target out of the object's position with `FUN_1098_096e`
  at R = (r << 11) / 100 (sign-extended long division). The figure loop needs the target's flag 0x02
  clear; this loop does not, and the caller (`FUN_1088_39ef`) does not check the flag, so a figure
  with collisions off is pushed too. Both ports keep the object's name and resolve its position at
  push time; resumed saves carry the list (resume maps the saved object ids to names).
- Live (2026-10-16, `dosbox_live.py`, which now samples the lists): at 85–98 s USE_BOT has AVDBAR3,
  AVDBAR4, AVDBAR1, AVDBAR2 (110), WAY_PT2 (180), GETMEAT (80); FIRSTBOT AVDBAR3 (100), AVDBNK3
  (200); CAYNAN CAYSTOP1–3 (60); GUARD1 AVDBAR2 (40), AVDHOLE (200); the ports' lists are identical in
  order and radius. Writing FIRSTBOT's position to AVDBAR3 + (300, 400) made the original push her to
  (−8932, −13467) on the next frame, exactly `push_out` at 2048. The same write to USE_BOT was not
  pushed because USE_BOT is hidden, not because its motion was stopped (see "STOPMOTION and hidden
  figures"). No opening figure enters a circle; the closest is USE_BOT at 319 units outside AVDBAR4's.

## STOPMOTION and hidden figures (recovered 2026-10-16)

- `STOPMOTION` (handler `10d0:77d6`) calls `FUN_1098_0789(fig, 1, 1)` and clears flag 0x80. With
  those arguments the stop routine ends the figure's motion and GO tasks (kernel types 0x108/0x109,
  `FUN_1088_3229`), clears the motion (+0x13d) and its name (+0x15f), bakes a turning motion's yaw
  (`FUN_10a0_1c83`) and resets the model's motion state (`FUN_1098_0000(model, 1)`), whose
  `FUN_1040_0c07` copies every limb's target angles into its current angles: the figure holds the
  pose it had. The per-frame update (`FUN_1088_39ef`, figure vtable +0x08) has no motion check, so
  a stopped figure is still pushed, grounded and tested against triggers. Both ports: `stop_motion`
  holds the current frame (with frame 0's root yaw once a turning yaw is baked), ends any GO, marks
  the motion finished (so `ISMYMOTION` fails and motion waits resume) and keeps the figure updated.
  The flag 0x80 and the motion's script process are not modelled.
- Hidden figures: `FUN_1088_39ef` returns at once for a figure with flag 0x04 and +0xf6 clear (only
  `FUN_1058_0c81` on +0x135 runs), so a hidden figure is neither animated nor moved nor pushed.
  DOSBox-X (2026-10-16): writing x += 2000 into hidden USE_BOT (flags 0x44, stopped) and hidden
  CAYNAN (0xC5, playing ATK_STAND) left both hulls (+0x65) unchanged; the visible nurse (0xC0) is
  updated. `FUN_1070_224c` hides (unless +0xf6) and `FUN_1070_2264` shows; they are vtable methods
  and their callers are not recovered (NOTES lists `_HIDE`/`_UNHIDE` engine events).
  **Ported (2026-10-17):** since level.py's FIGR comment already gives the show/hide rule (hidden
  while the current camera is not one of the figure's viewing cameras), `World.step()` in both
  ports computes `fig.hidden` from `fig.view_cams` and the current camera every frame, before the
  `FUN_1088_39ef` gate: a hidden figure is skipped entirely (no phase/motion advance, push or
  settle), matching the live check above. `push_target`/`pushTarget` already excluded `other.hidden` figures from the
  PERSONAL_RADIUS push (ported earlier, unused until now). A level-placed figure's raw FIGR
  `view_cams` (from `fig_defs`, possibly `[]`) only applies to figures loaded directly from a
  level's object file; `CREATEFIGURE`/`w.figure()`'s `PLAYER` fallback still default to `view_cams
  = None` (always visible), matching the original (a script-created figure is never hidden until
  `DEFINEVIEWINGCAMS`/`ADDVIEWINGCAMS` restricts it). NOT PORTED: the `_HIDE`/`_UNHIDE` block event
  (`FUN_1128_0569`; no script in this game defines either block, confirmed by search) and stopping
  a hidden figure's ambient sound (`FUN_1058_0c81` on +0x135).

## IMAG triggers (2026-10-16; implemented in both ports)

- Objects: IMAG class descriptor `1290:2067`, vtable `1290:2077`, object 0x4b bytes. +0xb lo and
  +0x35 hi (the reader `FUN_1068_0e39` → `0507` normalises them), +0x34 flags (record byte 21;
  bit 0x01 = fire on entry only), +0x41 char[9] camera name (record +45), +0x4a "has a block",
  set by vtable +0x38 `FUN_1068_0e7a`: a block named `<trigger>` exists, or `<trigger>_<figure
  instance name>` (+0xf7) for some non-player figure ("%s_%s" at DGROUP 0x2071). The global list
  is DGROUP 0x1ce9 (count) / 0x1cf1 (far pointers); a trigger's index there is its InTrig index.
- Area lists: each RoomType node (`FUN_1138_131c`) keeps the IMAGs whose boxes touch its anchor
  box (`FUN_1068_0934`, inclusive), in global order, with their indices. CHAOS: CE3 (the cell)
  has none, DR3 (the doorway) has CAM_BLK1 and DR_ZAP3.
- InTrig: figure +0x191, one byte per IMAG, allocated zeroed by `FUN_1088_536a` when first
  needed; saved in FIGR/PLAY records. `FUN_1138_1b8a` (called by `FUN_10a0_21b2` on every hull
  rebuild and once per frame before the trigger pass) clears, when the area changes, the bytes of
  triggers missing from the new area's list.
- Per frame, at the end of the figure update, `FUN_1088_51c3` (skipped while [50b8] is clear,
  for a player with hit points ~0 ≤ 0, for collisions off (+0x34 bit 0x02) and without an
  area): for each trigger of the area, a hull (+0x65) not touching it (`FUN_1058_173c`,
  inclusive) clears the byte; touching it sets the byte and calls vtable +0x5c every frame, or
  only when the byte was clear if flag bit 0x01 is set. The loop stops if the call changed the
  figure's area.
- Vtable +0x5c `FUN_1068_0d45(trigger, figure)`: if the figure is the camera-followed object
  ([63fa]) and the camera name is set, `FUN_1130_0f85` looks it up and forces it. Then
  `FUN_1120_0000` starts block `<trigger>` (player) or `<trigger>_<figure>` with the figure as
  current figure and runs its first slice at once (its argument 1 → the process's vtable[0]).
  No block, no script. +0x58 `FUN_1068_0df1` is the same without the player case.
- `AMINTRIGGER <obj> <trigger>` (`FUN_10d8_07fa`): resolves the object (`FUN_10c0_16a8`), takes
  the first IMAG of that name and returns `FUN_1070_0aba` (the hull test above). The ports test
  figures only here; `AMINTRIGGER` on items: NOTES "Items and combat".
- Effect in the opening: CHAOS's cell bars are live (`_BARS3_ON = 1`). Walking Lex out through
  the open DR3 enters DR_ZAP3 (every frame), whose block (`ZAP.scr`) plays SHOCK_* and drains
  energy until `AMINTRIGGER` says he is out; he is thrown back about 1700 units. This explains
  the earlier live "thrown back past the doorway" observation (it was not the nurse). With the
  bars off, the corridor's CAM_BLK1 trigger forces BLK1.
- Live check (2026-10-16, `dosbox_live.py --hold 48@84+8`, DR3 open): the original sets the
  player's InTrig byte 43 (DR_ZAP3) at the doorway, plays SHOCK_BACK, clears the byte once Lex is
  thrown back into the cell and leaves him standing at y −13201. The Python port, with the same
  input from its own wake position, fires DR_ZAP3 on entering DR3 (y −14603), plays SHOCK_BACK
  and leaves Lex at y −13263. `--boxes CE3,DR3,DR_ZAP3` shows the in-memory boxes equal the file
  and DR_ZAP3's +0x4a = 1. One sample showed the byte set at y −14449, still inside CE3 by the
  area rule; the tool reads InTrig in a separate dump after the record, a few frames later, so
  this is most likely sampling skew. Not yet checked whether the walk also hits the mover's stop.
- Not modelled: IMAGs created at runtime (`FUN_1068_0c84`, flag 0x01 set), the editor-mode
  ([50b8] clear) rebuild in `FUN_1068_0b9f`, and writing the ports' InTrig bytes into their own
  saves (resume reads them from DOS saves).

## Cross-level regression scenarios (2026-10-14)

- `re/interp/scenarios.py` replays World+VM ticks in the engine's normal order
  (`vm.tick_once(); world.step()`). It saves JSON checkpoints, input events,
  script/engine call counts, camera and level changes, hits, warnings, and selected
  PNG frames. `test_scenarios.py` asserts causal milestones across four runs:
  CHAOS escape after unarmed input, the live nurse's two-hit revival, LANDPAD
  `MEETMECH`, and BEACH → TUNROOM → BEACH via the actual `TO_TPL`/`TO_BCH` blocks.
- A separate smoke check loads scripts, objects, and one rendered frame for every
  GAMEDAT level (10 total). All pass without VM or World warnings. It does not run
  arbitrary events or prove each level is playable.
- The scenario harness caught an integration gap: scripted `GO` and AI root motion bypassed
  Lex's manual PHYS check. `World.advance()` now sends all root movement through the same
  per-figure collision check, gated by `COLLISIONS`. `FUN_1088_2a87` reads a figure type's
  `EXTENT`, defaulting to `(10,10,10)` when absent. `AIRMECHO` uses that default despite
  `MATERIAL=MECHO`; `MECHO` has its own larger extent. A blocked GO remains active rather
  than snapping through a wall. The LANDPAD, nurse, and cross-level replays still pass.
- The full TITLE boot currently emits a logged `CAMERA SHOW TITLE` warning and three
  `CAYNAN_PACE` warnings for `BREAK 2` inside a `SWITCH` (`AI_CAYNA.scr:333-343`).
  (Settled 2026-11-19: the numbers count switches through the file, so these were never wrong; "BREAK n" below.)
  Scenario tests allow those known warnings and fail on additional ones.

Run from the repository root:

```bash
re/.venv/bin/python -I -W ignore -m unittest discover -s re/interp -p 'test_*.py'
re/.venv/bin/python -I -W ignore re/interp/scenarios.py --out re/out/scenarios
```

## Sound and music (segs 1028 SNDMGR, 10f0, 1198 CMUSIC)

Samples (`SOUND/{E,F,G}SAMPLES.FLX`, 718 entries): entries 0..716 are samples, entry 717 is
a name table of 9-byte NUL-padded names (`scream2a`, `bubble2a`, ...). Sample entry:

```
0x00 u32 data_len (= entry size - 32)   0x08 u32 loop_start   0x0c u32 loop length (0 = no loop; the loop is
                                                                     [loop_start, loop_start + length), "Released loops")
0x04 u16 rate (11111, some 11025)       0x10 12 bytes unused (sometimes garbage)
0x06 u16 flags (always 1)               0x20 data: signed 8-bit mono PCM
```

`FUN_1028_09d3` plays from header+0x20, streams samples over 0xfe00 bytes in 0x7f00 chunks,
and sets the channel rate to `header.rate - pitch`. Script `SOUND(id [, volume [, pitch]])`
(function 10d8:3ae9 → `FUN_10c0_31e0` → `FUN_1100_1c72`): defaults volume 255 (clamped to
255), pitch 0. `SUBTITLE(sound, speaker [, n], "text")` (10d8:3b26 → `FUN_10e8_0529`):
arg 1 defaults to 0x75, arg 2 to 0xff. GAMEDAT/SOUNDS.DEF ids index the FLX
(`_ESCHER_VOX_SCREAM = 0` ↔ `scream2a`, `_ACID_BUBBLES = 1` ↔ `bubble2a`).

Music: `MUSIC n` (statement 10d0:60ce) → `FUN_10f0_0953(n)`: n < 0 are control codes
(-1 = `_STOP_MUSIC`, -2..-4 other player calls), n ≥ 0 → `FUN_1198_0013(n)` → `FUN_1198_0702`
(request song; same song = no-op; if a song is playing it records the request and the
transition happens in `FUN_1198_1668`, decompiled in `re/decomp/1198.c`, not yet read). `MUSIC.FLX` (= `KEN.FLX`) resembles the Ultima 8 music flex: entry 261 = song
table text (`im1_18a.xmi 0 2 0`: file, song id char 0-9a-zA-Z, two numbers), entry 257 =
transition file list (`im1_t7a.mid` ...), entry 259 = binary transition table.

Decoded (`re/formats/xmi.py`, `music.py`, outputs in `re/out/music/`):
- Entries 0..48 = the 49 songs, song id (line index in entry 261, chars 0-9a-zA-M) = FLX
  index (`_GMRESET` 31 = `v` = `gmreset.xmi`). Entries 128..176 = the same songs in a second
  arrangement (0.. General MIDI / MT-32, 128.. AdLib: proven, see "AdLib music").
- Entry 258 = one XDIR with 55 transition sequences in entry-257 order; 260 = its alternate.
- Entry 261 after the song lines: `#`, `trans.xmi`, then 39 rows `from.xmi to.xmi v...`: one
  value per measure of the source song = 1-based index into the transition list (0 = switch
  directly). Proven: every non-zero value names `im1_t<source song>`. A leading `!` is a flag
  (meaning unknown).
- Song table columns: `measures` (read only by the bar-counter step, which no request reaches, see
  "Music state machine"; equals the 0x77 count in only about half the songs, e.g. song 1: 24 vs 39 bars),
  then the loop measure (the counter's wrap target in that same step; > 0 also makes an ended song
  restart at marker 126).
- Entry 259 is not a transition matrix: it is a Miles AdLib timbre bank (6-byte
  `patch, bank, u32 offset` records ending `ff ff`, 14-byte OPL timbres).
- XMIDI → SMF: fixed 120 Hz timing (PPQN 60, 500000 µs/qn). FF 51 tempo metas are dropped,
  because some files carry nonsense values. XMIDI controllers 110..120 are dropped.

Interpreter (`world.py`): `SOUND` returns a handle that lives for the sample's duration
(looped samples live until `STOPSOUND`/`STOPALLSOUNDS`); `SUBTITLE` with a voice sample lives
for that sample (assumption). Sound/music events are logged in scenario manifests, and
`movie.py --audio OUT.wav` mixes them. 589 of 591 script sound names resolve; the remaining
two (`_fido4_grunt`, `_marine2_vox_miscb`) are in no .DEF file.
Voice allocation (`FUN_1028_18f4`, called from `FUN_1028_09d3(mgr, id, priority, volume,
pitch)`): 8 voice slots. With fewer than 8 playing, the first free slot is used. With 8 playing,
the slot with the lowest priority is chosen (strict `<`, so the lowest index wins ties); if the
new sound's priority is lower than that, the new sound is dropped (handle 0), otherwise that
voice is stopped and reused. Script SOUND/SUBTITLE pass priority 1 (`FUN_10c0_31e0` →
`FUN_1100_1c72(..., 1, vol, pitch)` → `FUN_1100_196c`). When the process has a current
figure, the sound is positional: `FUN_1030_04db` ignores the script volume and returns
`min(255, 65536 / q²)`, `q = max(1, d / 128)` (32-bit integer helpers `FUN_1000_252d` mul,
`2658` div, `2706` shl; `FUN_1210_0c24` 8.8 fixed divide), where d = `|listener − figure+0xb|`
(`FUN_1208_13e3`) and 128 = `[19fa]` (16) × 80 / 10. The listener is `[63ca]+0x14`, the camera
of the 320×200 view object (`FUN_10e8_106a`). Without a listener: volume >> 1. The engine
recomputes the volume every frame (`FUN_1030_07cf` over the (handle, figure) list filled by
`FUN_1030_0668`). If the current-figure name does not resolve, SOUND reports an error and
returns -1. After that, the volume is scaled by the master-volume table at mgr+0x12f
(`FUN_1028_1da5`: `t[v] = v·m >> 8`, m = setting% × 255 / 100, default 255).

Subtitles (`FUN_10e8_0529`, object 0x1a6 bytes): SUBTITLE(sound, colour = 0x75, volume = 0xff,
"text"). The voice plays non-positionally with priority 2; colour is the speaker's palette
index (`_stcLex` 127, `_stcGold` 117, ... in DEFINES.DEF), set via `FUN_1100_1376`. End time
(60 Hz clock `[8330]`) = now + `FUN_1030_019f(sound)` × 60 / 11025 + 2 × strlen(text), i.e.
sample length + 1/30 s per character, independent of the voice. Text is shown only if
subtitles are enabled (`[50bc]`); a new subtitle destroys the current one (`[50d6]`).
MINORSUBTITLE (10d8:36ed) is skipped while a subtitle is up, otherwise identical.

Music control codes: -1 → `FUN_1198_0f2e`, one step of a volume fade (counter `719d`
from 2 × volume; stops below 5). Scripts always follow it with `MUSIC _GMRESET`, whose request
stops the fading song immediately (`FUN_1198_0702`). -2 → pause (`FUN_1198_082a`,
`_XMI_stop_sequence` without release), -3 → resume (`FUN_1198_07c7`), -4 → stop
(`FUN_1198_0899`).

Music state machine (seg 1198, reached from `MUSIC n`; tables parsed by `FUN_11a0_02cc`):
- Song record (0x11 bytes): u16 measures, u16 loop_measure, name. Every listed song gets
  flag bytes 1/1 (so the alternative "stinger" path, states 4/5/8/9, is unused in practice).
- Transition tables: `muTabl[from]` = (to song → row) pairs; `muTrans[row]` = (measure 1..99 →
  signed value) pairs, values 0 omitted. A leading `!` in the text = negative value.
- Measure count (settled 2026-11-20 from the code; "AdLib music" > "Measure count"): `_XMI_measure_count` is the
  value of the sequence's last 0x77 controller, 0 before the first. Every song numbers its 0x77s 1..N.
- Bar counter `72c4`: a switch sets it to 1 (`0899`, states 1/3/7). Its only step (`FUN_1198_1668`, 16c1..16fe:
  `if c % measures == 0: c = loop_measure else c += 1`, when the measure count moved since the last request) also
  needs the requested song to be the current one (`[718d] == [718b]`), and `0702` returns before that for a
  request of the current song. So every lookup reads measure 1 of the row.
- Request n (`FUN_1198_0702`): n == current → nothing. During a pending switch or transition (`[7195]` != 0) the
  request is remembered (`72ba`) and replayed at the end of the update that finishes it. Nothing playing, or the
  song has ended → start n now. Otherwise (`FUN_1198_0a91`), with row = muTabl[current][n] and
  v = muTrans[row][1] (`0595`), the current song's measure count is stored in `7197`:
  - no row: stop now, start n now;
  - v == 0 (state 3): at the next measure change, stop the song and start n;
  - v > 0 (states 1→2): at the next measure change, stop the song and start transition v
    (1-based in entry 257/258); at the next update, stop it and start n;
  - v < 0 (states 6→7): at the next measure change, start transition |v| on top of the
    still-playing song; at the next update, stop both and start n.
  `FUN_1198_09fc` (the check each state makes) says "moved on" when max(1, measure count) != `7197` or the
  sequence is no longer playing. A transition stores its own count right after its start (`11a0`, `13da`,
  `146f`), which is 0 because the start resets it to -1, so the check fires at once: a transition sounds only
  until the next update, its notes at ticks 0..3 at most.
- The update (`FUN_1198_1054`, the music task's vtable[0] at DS:7381 → `0ef1`, guarded against re-entry by
  `72f3`) runs after every request (`1668` → `183b`) and as the task's slice. INFERRED: once per game tick, like
  the other kernel tasks (the timer ISR that dispatches it is not decompiled; the serve is vtable slot 10,
  `0f02`).
- Starting a song: per-song entry counter `71ab[n]` (initially -1). If ≥ 0, jump to XMIDI
  branch marker (controller 0x78) with that value, or to marker 0 if it is missing, or reset to
  -1 if that is missing too. Then increment it. Songs therefore alternate entry points
  (`im1_10a` has markers 0, 1, 126).
- Songs loop through Miles for/next controllers (0x74 count 0 = forever, 0x75). If an idle
  song still ends and loop_measure > 0, the next update restarts it at branch marker 126 (`FUN_1198_1054`).
- n < 0: -1 stop (`FUN_1198_0045`), -2/-3/-4 other player calls (not traced).

Implemented (2026-10-14):
- 8 voices in `world.py` (`play_sound`): stolen voices are logged in `sound_stops` and
  dropped sounds in `sound_drops`. The new-game opening peaks at 8 live voices with 0 drops.
- `re/formats/musicseq.py` implements the state machine above and produces a timed MIDI event
  list. Measure changes and the update follow the code above (corrected 2026-11-20: the port had
  counted 0x77 events, stepped the bar counter on each, counted a NEXT jump as a change and ended a
  transition at its own next bar). Entering at a marker sends no earlier state (corrected
  2026-11-20, "AdLib music" > "XMIDI layer").
- `re/tools/midi2wav.swift` renders events offline through Apple's MIDI synth AU (`msyn`) with
  the system `gs_instruments.dls`. The native app now uses the same synth live:
  `native/Sources/BioForgeCore/Music.swift` ports the 120 Hz sequencer and
  `native/Sources/BioForgeApp/SoundOutput.swift` sends its MIDI to the synth beside the effects
  source. Four native tests compare event-stream hashes to Python for starts, direct and bar
  transitions, overlaid transitions and pause/resume; a fifth starts every song ID. A five-second `BIOFORGE_MUSIC_TAP`
  capture from the running app contained nonzero synth audio (44.1 kHz stereo, RMS 0.0146).
  MIDI is delivered on each 30 Hz app tick, so live note timing remains quantized by that frame.
- `movie.py --audio` mixes music (gain 0.5, a preview choice) under the effects; `--no-music`
  skips it. Audition: `music.py --play 10 --seconds 60 out.wav`, `music.py --switch
  "0:10,19:21" --seconds 60 out.wav`.
Open: the `!` flag beyond "negative".

Native mixer (`native/.../SoundMixer.swift`, 2026-10-15): bit-exact with `movie.mix_audio`. Linear
interpolation follows np.interp edge rules; voices accumulate in Float64 in event order, then
×256, round half to even, clip to Int16. Live playback renders the same code from an
AVAudioSourceNode, with the audio clock as master and a fixed 2048-frame pad (at least one tick,
because a positional volume ramp starts one tick before its logged tick).

## AdLib music (2026-10-17; both ports)

Device choice. INSTALL.EXE's music menu (none, Adlib, Sound Blaster, SB Pro/16/16ASP, AWE32, Wave
Blaster, Roland SCC-1, General MIDI MPU-401) writes `MusicCardId` 0..7 to INSTALL.OPT and copies a
driver to `AILXMI.DLL`: its only driver paths are `MUSIC\AILADLIB.DLL`, `AILAWE32.DLL` and
`AILMT32.DLL`, so ids 1..3 get the AdLib driver (`AILSBFM.DLL` ships but is never installed). GOG
ships id 7 and the MT-32 driver (`AILXMI.DLL` = `AILMT32.DLL`). `FUN_1198_0071` (CMUSIC.C) reads
three bytes of the driver and compares them with `"MPU"` (DGROUP 0x7333) to set `[719f]`; the MT-32
and AWE32 drivers carry `MPU` at file offset 12637 (the AWE32 one as a bare `MPU\0` that looks
planted), the AdLib driver does not. `[719f]` = 0 (AdLib) selects FLX entry n + 0x80 for song n
(`FUN_1198_1be0`, falling back to n when that entry is empty), the transitions in entry 260 instead
of 258 (`FUN_11a0_03e5`), and the timbre cache: `_XMI_default_timbre_cache_size` (0xe00 bytes) and,
for every song and transition, `_XMI_timbre_request` → `FUN_11a0_0990` (search entry 259 for
bank/patch) → `_XMI_install_timbre`. The 49 AdLib songs + transitions list 80 timbres (all in the
bank; 1120 bytes, so the cache never evicts). All 185 bank timbres are 14-byte BNK timbres.

Driver (`AILADLIB.DLL`, AIL 2 XMIDI.ASM + YAMAHA.INC, NE DLL; import it into a scratch Ghidra
project with `analyzeHeadless <dir> AIL -import game/app/Bioforge/MUSIC/AILADLIB.DLL -scriptPath re/scripts
-postScript Disasm.java 1000:0767 ...` (JAVA_HOME as above); functions named `1000:xxxx`). Two segments: code
(file offset 0x600) holding the tables, read through `CS:` (frequency table 1000:0156, block/note
02d6/0336, init registers 0395, velocity 0580, operator maps 0590/05a2/05b4, init controllers
009e/00a7, programs 00b0), and a data segment that is zero on disk apart from the driver descriptor
(port 0x388, service rate 0x78) and whose selector is the DLL's one relocation, at 1000:009c; state
offsets like 08f0 or 0b38 are in it. Recovered behaviour, ported in `re/formats/adlib.py` (docstring
has the formulas) and `native/.../AdLib.swift`:
- Init (`_XMI_INIT_DRIVER` 29c1, once at boot: `FUN_1198_0071` → `FUN_1198_0d4e`, 1198.c:855): registers 1..0xf5 from
  cs:0395 (0x01 = 0x20, 0xBD = 0xc0, operators silent), the reset 1274, then channels 1..9 get CC 7=127,
  1=0, 10=64, 11=127, 64=0, 114=0, 110=0, 111=0, 112=0 (110/111 do nothing in this driver), bend 0x2000
  and programs 68 48 95 78 41 3 110 122.
- Only MIDI channels 1..9 play notes (channel 0 and 10..15 are ignored); channel 9 is percussion
  (timbre bank 127, patch = key, played at the timbre's transpose byte as a fixed note).
- 16 voice slots on 9 OPL voices. Note on: the first free slot (none: dropped), the next free voice
  round robin, otherwise the priority pass `17d3` (priority 0x7fff − voices of the slot's channel;
  the best voiceless slot takes the voice of the worst voiced one, whose note ends, while it is not
  worse). Note off frees the slot and gives the voice to the first waiting slot (`0644`), whose
  registers are not written until its channel's next update (an original quirk, kept). The serve
  (120 Hz) runs the priority pass every 24th call.
- CC 123 and the sustain release call note-off with the slot's played note, not its key, so
  percussion slots survive an all-notes-off (kept).
- Settled from the bytes (2026-11-20), all as ported: velocity = `cs:0580[vel >> 3]` (1ae1); CC 10 is
  stored at 0ac8, which nothing reads (only a level rewrite: OPL2 is mono); CC 113 only marks the timbre
  cache; a program change looks its timbre up at once and `_XMI_INSTALL_TIMBRE` (1189) re-resolves the
  channels whose program matches, so the init programs sent before the bank is installed end up as the
  port's full-bank lookup; the round robin (131b) starts from 0xffff (reset, 12f9); 0644 never calls the
  register writer; the slot's 0xB0 copy (09f8) is written only by the register writer 13ea, so a reused
  slot keeps its previous note's value (Python had it, Swift reset it: fixed); 13ea never writes 0xBD after
  init nor 0x08, so rhythm mode is never used.
- Level: v = vol·expr·2 >> 8 (+1 if non-zero), v = v·VEL[vel >> 3]·2 >> 8 (+1); carrier (and an
  additive timbre's modulator) TL = 63 − (63 − TL)·v/127. Pitch bend ±12 semitones; A4 → F-number
  580, block 4 (440.0 Hz).
- The XMIDI layer (shared by every AIL driver) scales CC 7 by the relative volume as a percent
  (`220f`, `21a7`, `_XMI_SET_RELATIVE_VOLUME`); `musicseq.py` and `Music.swift` now do the same
  (they used rel/127, an assumption).
- Not ported: the TVFX (time-variant) timbre path (`099c`, `0767` envelopes; no BioForge timbre
  uses it), timbre-cache eviction (never needed), channel locking.

Chip: `re/formats/opl.py` / `OPL2.swift` are an own YM3812 model (documented chip behaviour: log-sin
and exp tables, 4 waveforms, feedback, KSL/KSR, half-rate envelope generator, tremolo/vibrato
LFOs; no rhythm mode, which the driver never uses, and no DAC quantisation) at 49716 Hz; the two are
bit-identical (tests). `opl2wav.swift` compiles `OPL2.swift` for Python's offline renders.

Timing (settled 2026-11-20; it was a 120 Hz serve from music time 0, an assumption):
- The game's music timer runs at 60 Hz: `FUN_1198_0f13` → `FUN_1198_0e0d(.., 0x3c)` → `FUN_1238_16e9`
  (period 1e6 / 60 µs). Every song start sets the relative tempo to 200 (`FUN_1198_1e3c`; DGROUP 717b = 1,
  never written). `XMI_SERVE_DRIVER` (26d6) adds the tempo to each sequence's accumulator and runs one
  120 Hz XMIDI step per 100 (275a..27a0): two steps per serve, then one synth serve (0767). So the tempo
  stays 120 steps a second, but register writes come in pairs of steps on a 60 Hz grid, and the priority
  pass (0767: +5 to 08f0 per serve, pass at 120) runs every 24 serves = 0.4 s.
- The timer calls the serve (`FUN_1198_102e`) only while music is on (`[7199]`: 0 at MUSIC -2 `082a`,
  1 at -3 `07c7`) and a sequence is loaded (`[72ca]` / `[72d7]`, released by the stops `0899`). The
  counter is zeroed only by the reset 1274, which only the boot-time init calls, so it carries over
  between songs and stands still between them.
- Ports: serve k at music time k/60 sends the musicseq events at 120 Hz ticks floor(t·120 + 0.5) ≤ 2k + 1,
  then serves the driver if a song is loaded and not paused (`adlib.serving` from the musicseq trace;
  `MusicSequencer.takeServingChanges`); its writes land at chip sample k·49716/60. A serve runs once both
  its steps are known, so the app's writes arrive one serve later than before, inside the stream's pad.
  No shipped song has a voice waiting at a serve in its first 30 s, so the pass's phase changes no song
  start; it matters only in dense passages.

Still open (what would settle each):
- The chip model itself (DAC, table and envelope details against a real YM3812): a recording of real
  hardware, or a DOSBox-X DRO capture (`caprawopl`, "Record FM (OPL) output") of the same music played
  through a reference core such as `oplemu=nuked`. The game has to run the AdLib driver: in a scratch copy,
  `MUSIC/AILADLIB.DLL` over `MUSIC/AILXMI.DLL` and INSTALL.OPT `MusicCardId=1`, `MusicPort=0x388`.
- INFERRED: serve k comes right after the game frame at the same music time. The 60 Hz timer is
  dispatched from the kernel's 140 Hz PIT tick (divisor 8522, `SCRIPT.DAT` above) in the interrupt
  handler, which is not decompiled, so the serves probably come 2 or 3 PIT ticks apart (±7 ms) with a
  boot-dependent phase against the frames. The same DRO capture shows the burst spacing.
- INFERRED: the priority counter is 0 when a new game's music starts. In the original it carries the
  serves of the music before (the menu's), so its phase depends on how long that music played.
- Seg 1198, not ported: a stop while paused leaves `[7199]` = 0 (only the boot init and MUSIC -3 set it), so a
  song started after it is not served until a resume. Unreachable in the shipped game: only `MUSIC -2` / `-3`
  pause and resume (`FUN_10f0_0953`), and no script sends them.
- Measure count (settled 2026-11-20; the earlier lead had it backwards): controller 0x77 stores its value as
  the sequence's measure count (`220f` → 2313, sequence +0x40). Nothing calls a callback: `_XMI_INSTALL_CALLBACK`
  stores a pointer (DS:38) that the serve never reads. Start sets the count to -1 (1e71), 0x76 to 0 (22f1; no
  shipped sequence has a 0x76, so the ports ignore it); a
  NEXT jump (2384..23be) and `_XMI_BRANCH_INDEX` leave it. `_XMI_MEASURE_COUNT` (2f5f → 26a7) returns it, at
  least 0, and `_XMI_BEAT_COUNT` (2f29) the beat. The FF 58 time signature (257c) only sets the beats per
  measure (+0x42) and the beat length (+0x44); the serve counts beats (275a..2794, 26fd..270b) and wraps the
  beat at the numerator without touching the measure count. Every shipped song and transition numbers its 0x77s
  1, 2, 3 ... in file order, so the count is the number of the bar last passed. What seg 1198 does with it is in
  "Music state machine".
- NEXT (0x75) jumps only for a value >= 64 (2384); every shipped NEXT is 127, so the ports do not check it.

XMIDI layer (settled 2026-11-20 from the driver bytes; every AIL driver shares it, so General MIDI too; ported in
`musicseq.py` and `Music.swift`, docstring there):
- Events run in file order within a step (2842..2914). The ports sorted controllers and programs before the note
  ons of the same tick: 1621 ticks in the shipped music have a note on first, 748 of them before an event on its
  own channel.
- Note queue: a note on takes the first free of 32 entries (2426; a full queue overwrites entry 0) with duration
  - 1; at each later step, before that step's events, every entry is decremented and those below 0 end in entry
  order (27d6..2835). So a note of duration d ends at step on + max(d, 1): the 280 zero-length notes end one step
  later than the ports had them, and notes due at the same step end in queue order, not file order.
- `_XMI_STOP_SEQUENCE` (2e40, only for a playing sequence): note offs for the queued notes (1fc3), then per
  channel CC 64 = 0 where the sequence's cached CC 64 is >= 64 and CC 112 = 0 likewise (2021; no song sets
  112). No CC 123: the ports sent CC 64 and 123 on every channel. Pause is the same stop. On AdLib this matters
  for percussion: CC 123 misses percussion slots (played note), the queue's note offs by key do not.
- FF 2F (2551) runs only 2021 and marks the sequence done; a stop after that does nothing. No shipped sequence
  has a note queued at its FF 2F.
- `_XMI_START_SEQUENCE` (2dd8 → 1e71) clears the queue, the controller / program / bend caches, the relative
  volume and tempo (100) and sends nothing; `_XMI_BRANCH_INDEX` (3018) seeks to the marker, ends the queued
  notes (1fc3) and clears the FOR stack. So a song entered at a marker keeps the channel state the earlier music
  left; the ports replayed the state before the marker.
- `_XMI_RESUME_SEQUENCE` (2e99 → 20c8) resends the cached CC 7, 1, 10, 11, 64, 114 (controller by controller,
  channels 0..15, CC 7 through the relative volume, 220f), then per channel the pitch bend (when both bytes are
  cached) and the program. Cached values are the raw ones the sequence sent (220f 2261, 28c0, 28dc).
- Ports: the player timeline is in integer 120 Hz steps (times = step / 120), so queue expiries, items and
  requests at the same step order exactly.
The native app renders the chip in a second AVAudioSourceNode (`OPL2Stream`, the effect mixer's
2048-frame pad as lead). Opening check: `movie.py --boot … --audio … --music-device adlib|gm`
renders both (36.7 s each); a live tap of the app with each device differs only by the music.

## Fonts (`DATA/*.FNT`)

12 files: `0.FNT`..`9.FNT`, `SMALL.FNT`, `TINYBLK.FNT`. Fonts are loaded by number:
`FUN_1278_0163(n)` builds `<fonts dir>\('0'+n).FNT`. The subtitle font comes from the option
`CAPTIONFONT` (`FUN_1100_12a2`): `RED.OPT` (the engine's real option file, every byte | 0x80)
sets `captionfont=%DataDir%\1.FNT`, which confirms 1.FNT. It is absent from the E/F/G.OPT files; the default is not
recoverable statically (`FUN_11a8_083b` returns nothing for a missing key). The prototype
assumes 1.FNT, which matches the caption geometry. Glyph blit (`FUN_11d8_03ca`): at
(x − x origin, y − baseline) as a solid fill; characters < 0x20 are skipped.

```
file:  u16 height, u16 max width, u16 n_glyphs, n × (u32 offset, u16 size), glyph data
glyph: u16 0, u16 width, u16 height, u16 x origin (0 except two glyphs in 7/8.FNT),
       u16 baseline, u16 rowoff[height] (self-relative),
       rows: (u8 skip, u8 count, count × u8 colour) pairs until x >= width (a skip that
       reaches the width ends the row, as in CAM images)
```

`DATA/MOUSE.SHP` uses the same format (header u16 11, u16 14, u16 8 frames; the glyph x origin and
baseline are the hotspot; real palette colours, draw with `colour=None`): 0 arrow pointer
11×12 hot (1,1); 1 small 3×7 marker hot (1,3); 2 hourglass 10×14 hot (4,6); 3..7 a 5-frame busy
animation 9-10×8 hot (8-9,0). Decoder and engine behaviour: see "Mouse cursor (`MOUSE.SHP`)".

Decoder and text drawing: `re/formats/fnt.py`. Glyph index = character code (`A` = 65; 9.FNT has 256 glyphs, the others 123..226).
All glyphs of all 12 files decode to exactly their size. Each font uses one colour index
(0/2/4.FNT 253, 1 230, 3 247, 5/6 244, 7/8 116, 9 160, TINYBLK 128) except SMALL.FNT,
which has a 5-step vertical ramp (0x9f..0x96). Presumably the drawing code remaps it to the
text colour (subtitle colour = speaker palette index).

Subtitle drawing (`FUN_1100_1538`, per frame; implemented in `re/interp/subtitles.py`):
- Drawn when `([50be] == 0 || [50bf] == 0) && [63c2] == 0 && [50d0] != 0`.
- Text is split at `~` into at most 3 lines (the rest stays on line 3), separator at
  dgroup 0x5121 (`FUN_1100_14a9`).
- Each line is centred: x = ((300 − width) >> 1) + 10, with width = Σ(glyph width + 1).
- Baselines: 194 for 1 line; 184, 194 for 2; 174, 184, 194 for 3.
- Box: x 5..315, y top..198, top = 185/175/165 for 1/2/3 lines. It is a palette-remap shade
  (`FUN_1138_1d0a`, runtime table; the prototype darkens by 50%).
- Shadow: the text is drawn in colour 0 at (+1, +1) first (`[obj+0x36] = 2`, `FUN_1248_192e`).
- Colour: the speaker index is used as given; the CAPTIONCOLORS remap applies only while
  `[4e2c]` is set (a monitor-face flag).

Native stage 5 (`native/Sources/BioForgeCore/CaptionFont.swift`, `SubtitleRenderer.swift`):
the app now draws active captions in the player-facing framebuffer from `DATA/1.FNT`.
The bare room renderer remains available for camera feeds and indexed-frame parity.
The box shade maps each source palette colour to the closest entry at half RGB brightness;
this is an approximation until the engine's runtime remap table is recovered.

Save state (2026-10-15; decoder and encoder `re/formats/savegame.py`; `dump`, `roundtrip`, `diff`,
`pack`, `unpack`). The play directory `GAMEDAT/` (`PlayDir`) holds the live runtime state; a
save packs it into `gameN.im1`. The shipped GAMEDAT is a real mid-game native state (CHAOS,
camera CE33, 117 of 1000 variables changed). All 15 files round-trip byte for byte.
- Flex container (SCRIPT.DAT, LISTS.FLX, .im1): 0x80-byte header (comment, `00 1A A1 A1` at
  0x50, u32 count 0x54, u16 version 6 0x58, u32 entry size 0x60, u16 checksum 0x64 = sum of
  the u16 at 0, 4, …, 0x7C excluding itself; 0x66 is stale). The checksum is verified on every
  shipped FLX/CAM. Entries are (u32 off, u32 size, tail); data is contiguous; (0,0) = empty.
- `MISC.DAT` (449 bytes, `FUN_1148_0076` / `0490`): char[13] save name, char[13] level file,
  char[9] camera `[63e1]`, u8 `[50bd]`, u8 auto camera `[63da]`, u16 0, u16 0, u32 next task
  serial `[2ed0]`, u32[100] serial per kernel slot `[2ed4]`, u16, u16 (object ids?). Strings
  keep stale bytes after the NUL. Task serials are also the VM handles (`_CELLONEPROCESS = 18`).
- `SCRIPT.DAT` (`FUN_1230_2208` / `1d7c`): 10 kernel entries + 2 per slot × 100 slots.
  0 = `Defines=77e Id=Kernel Ver. 1.00 - T. Zurovec`; 1 = raw kernel globals DS:9888..9921
  (slots 100, live tasks 25, PIT divisor 8522, tick accumulator); 2 = MLIST ids; 3 = u16[100]
  object sizes; 4 = group-owner bitmap; 5 = per-id flag bytes; 6 = live tasks per scheduling
  class; 7 = class-name pointers (StdIntHandler, BiosTimer, Default, Music, Wait); then per slot
  A = raw object memory (header: vtable, slot id, group, type 0x10a = script process, class at
  +8, flags +0xe/+0x10, serial +0x38, two MLISTs at +0x16/+0x20) and B = the object's virtual
  writer output (vtable +0x1c): waiter lists (`0x2000|id` waits for me, `0x4000|id` I wait for
  it, 0x408 ends), owner; script processes (`10c0:4ef4`) add three object ids (1-based indexes
  into the level IFF object list; 260 = PLAY LEX), wait slot, block index (1-based over the
  compiler's definition counter), char[13] script file, label, file index, u32 pc and pc0
  (byte offsets into the tokenized `.SCP` at statement starts), locals, and extra object ids.
  All 12 saved processes decode completely (e.g. CHAOSBLK #29 CELLONEBARS, COMMON
  LEVEL1TREMORS). pc0 = start of the statement being executed (WAIT, SUSPEND, CALL, a timeline
  line); pc = the text right after it, which is the resume point (a pending CALL is re-entered).
  Correction: list1 holds the task a process waits for (CALL child, Wait task); list2
  `0x2000|id` = I wait for id, `0x4000|id` = id waits for me; the "wait slot" (`obj+0x71`) is the
  caller of a CALL child. Wait tasks keep the remaining ticks at +0x40 (total at +0x42).
  Open: entries 2/4/5, most of entry 1, the clock origin of timeline processes.
- `LISTS.FLX`: 21-byte named entries (GMAINT, LEX); text `KEY,VALUE ` items, values are clock
  stamps (`1258:0f26` → `1278:13ec`).
- `VARS.DEF` / `SOUNDS.DEF` (`FUN_1118_4c7f`): header text, `{ Vars`, `\t%s = %d\r\n` per
  entry, `}`.
- FIGR/ITEM/PLAY records (`level.ObjRec`; writers via vtable +0x34 from `FUN_1148_1232`: FIGR
  `1088:489f`, PLAY `10a8:1ffa`, base `1070:0d5b` → `1060:16dd` → `1178:0e5f`; readers +0x30):
  base (all three, and ITEM entirely): char[9] type, s32[3] pos, u8 flags (+0x34: 0x01 gravity,
  0x02 collisions, 0x04 hidden, 0x08 invulnerable, 0x10 bouncy, 0x40 combat, 0x80 cleared by
  STOPMOTION), u16 holder object id (carried items: the player), char[9] hand name (empty =
  carried, no hand), char[25] instance name, s32[3] velocity, s32[3] 0, s32[3] previous pos,
  s32[3] pos copy, s32[10] object locals `~0..~9` (~0 = hit points, ~5 = maximum), u8, 3×3 s32
  orientation (256 = 1.0) at 147, s32 at 183/187. Heading = atan2(m[1][0], m[1][1]) (`COMPASS` →
  `FUN_1208_39a8`/`0574`), the prototype's convention. FIGR then adds enemy id, task slots of its
  motion task (0x108) and AI process, the current motion name (char[25]), one InTrig byte per IMAG
  object, the viewing-camera list, the ADDAVOIDANCEPOINT list and unknown blocks (size =
  356 + L + 9n). PLAY adds the player process slot, the game clock `[8330]` and the
  object about to be used. All 222 records in INITGAME/GAMEDAT/native save re-encode exactly.
- Level IFFs: saved CHAOS gains a `PLAY LEX` record (object 260) and an `ITEM MONBAT`, loses one
  NURSEBOT, and moves 12 records (carried items move to Lex). FIGR records grow (434 → 461–506
  bytes, tail not decoded); the flag word at +21 changes (carried items 0x10415). Other levels
  differ from INITGAME only in uninitialised junk bytes.
- `.im1` (`FUN_1140_134f`, DirPack `FUN_11f8_0859`, pack `09ee`, extract `0f03`): a Flex archive
  with entry size = longest name + 14, tail (u32 original size, u8 compressed flag, name).
  Entry 0 is a thumbnail written last (`1200:02a9`), files start at entry 1. Saves pass
  compress = 0. Comment "BioForge ver f1.01 savegame (C) 1994, 1995 Origin Systems Inc."
  Verified against a native save (2026-10-15, `re/out/native_save/GAME1.IM1`, made in the
  real game in DOSBox-X): saves go to `C:\Bioforge\GAMEn.IM1` (GameDir, not PlayDir); files
  are in alphabetical order; tail = u32 original size, u8 flag 0, name in one reused buffer
  (bytes after the NUL keep earlier, longer names); entry 0 = thumbnail stored after the files.
  The thumbnail is one CAM frame (rle 1, 320×200, hotspot 0,0) of the screen at save time.
  `Im1.pack(dir, thumbnail)` reproduces the native file byte for byte except the unchecked
  stale header word at 0x66. The native state inside (camera CE31, next serial 891) also
  round-trips exactly. **Load verified:** a `.im1` built by `Im1.pack` from the shipped GAMEDAT
  (with a native thumbnail) loads in the real game as slot 2; Lex appears at the saved place, and
  the extracted MISC/SCRIPT/VARS/LISTS/CHAOS files are byte-identical to the packed ones.
- Prototype resume (`re/interp/resume.py` from `World.from_native_state`): script processes restart
  at pc (statement byte offsets from `parse.File.positions()`, which maps every statement to its
  .SCP offset), with handle = task serial, locals, current figure/item, Wait sleeps, CALL links
  and MODIFYVAREVERYNTH ramps. Figures get position, heading, current motion, combat flag, enemy,
  viewing cameras and AI link; carried items get their owner. Resuming the native save renders
  the same scene as its thumbnail (`re/out/native_resume_vs_thumbnail.png`). Not restored: motion
  phase/frame, floor items, flag bits (decoded only), timeline clock origin. Avoidance lists are applied. Saving
  through the options dialog writes `re/out/saves/GAMEn.IM1` (`re/formats/savewrite.py`) with a
  thumbnail encoded by `cam.encode_frame` (byte-identical to the native thumbnail; native run rule:
  runs of ≥ 4 equal pixels). VM processes are not serialised, so the real game would not
  resume scripts from prototype saves; loading them back into the prototype works.
- Prototype saves write figure state (2026-11-07, both ports: `savewrite.patch_figure` /
  `SaveWrite.patchFigure`, `World.figure_states` / `exportState`). Before, only positions were written, and
  a game that began new (Lex made by `CREATEFIGURE`) had no PLAY record anywhere, so a save made after the
  opening loaded back with no player. Now every FIGR / PLAY record gets position (z plus the motion's
  first-frame root z, which resume takes off), heading, the managed flag bits (gravity, collisions,
  hidden, invulnerable, bouncy, combat), the ten object locals, the motion name, the enemy's object id,
  the AI hold and the InTrig bytes. A level with no PLAY record gets one appended, built from the shipped
  GAMEDAT CHAOS.IFF's (InTrig resized to the level's IMAG count; appended so no object id moves;
  ASSUMPTION: its other tail fields fit any level). The motion phase is still not saved and resume loops
  the saved motion from frame 0, so a one-off motion caught midway is saved as the idle it ends in
  (STAND, or ATK_STAND in combat; ASSUMPTION): a save during a pick-up otherwise replayed PICK_UP_RTHAND
  for ever. Saved after Guard 1 and loaded, Lex stands where he was; the run cannot go on from there
  yet, because no script process comes back (eleven kinds there, from GUARD1_AI to LEVEL1TREMORS).

- Prototype saves write the script processes (2026-11-08, both ports: `savewrite.task_script_dat` /
  `level_layout`, `World.process_states`, `resume.py`). SCRIPT.DAT keeps the system slots (< 6) and gets a
  process slot per live script process (block number, `.SCP` offsets pc / pc0, locals, current object,
  camera links, the CALL child or SUSPENDWHILE target in list 1), a Wait task for one that sleeps, a Wait
  task owned by no process (serial = the handle) for each subtitle / sound timer (ASSUMPTION: the original
  saves these tasks too; without them a SUSPENDWHILE SUBTITLE ran on at once after a load) and a task per
  MODIFYVAREVERYNTH ramp. Only the fields resume reads are right; the rest of each object is a template's.
  The level's records are laid out once, and the object ids come from that layout: a killed figure's FIGR
  record goes (its object is destroyed, `FUN_1090_135a`); a figure or item a script made gets a record
  (same-type template from any level; ASSUMPTION: the other tail fields fit); and the world's items follow
  the other records in creation order, because the inventory lists the player's items in item-list order
  (`FUN_10d0_0076` walking `DAT_1290_1d15`; CORRECTED 2026-11-08, it said object order), which a load rebuilds in
  record order ("The inventory order after a load"). A dropped, appended or moved record pads every chunk but the last, whose odd byte stays
  short as the writer's (`LevelIff.short_pad`); CONTROL.IFF's missing pad had made the saves unreadable.
  Figure records now also carry the AI name (+0x178: without it no AI restarted), the viewing-camera
  list, the velocity (+58; a zero-g float stopped) and the item records their locals. Resume selects
  each figure's area when it places it (INFERRED, as `set_pos` does), so Space works on the first frame.
  Any non-looping motion, even one held on its last frame, is saved as the idle stance.
  `re/tools/save_resume_check.py` plays the full run once and at each leg boundary forks a child that
  saves, loads into a fresh world and plays the remaining legs. It keeps the RANDOM stream (not in the
  save; INFERRED that the original keeps none either) and the harness's level-load history, and it saves
  once the player's last monitor has closed and his one-off motion has ended. One boundary
  (`temple-monitor`) ends with a monitor that the next leg goes on using; INFERRED that the options screen
  cannot open over it, so it is skipped. 20 of the other 29 reach EXIT. As a control, rounding every
  figure position to whole units without saving finishes all 29, so the 9 are lost state, not rounding:
  - the motion phase: figures restart their motion at frame 0, so they stand a few units off from the
    first frames on (GRDCON, DROGG1, SHRIMP1 and Lex), and the route's fights and dashes are tuned to the tick
    (CORRECTED 2026-11-08: the restart-only control below finishes all 29, so this is not what fails them);
  - the port keeps every level's items in one list, so the zero-g room's marine speech finds `WTALKY` (held by
    `GRDHANG` in CONTROL) and plays; a loaded game has only its level's objects, as the original does
    (INFERRED), skips it and leaves the room early (the "floor items kept per level" item);
  - after `tanks-back` Lex sways at a ledge (`WHOAH_BACKWARD`) on the first frame, not yet explained.
  Not saved: the game clock `[8330]` (the PLAY record has it; resume starts the VM tick at 0, so log stamps
  and `%time%` restart), open monitors, the motion phase.
- **The original does not save the motion phase either (2026-11-08, from the code).** The figure writer
  (`FUN_1088_489f`, `FUN_1088_04b4`) writes the motion name (+0x15f) but none of the model's timing: not the
  start clock (+0x106), the frame (+0x119) or the frame cursor (+0x10a). The motion task (class 0x46f5, type 0x108,
  77 bytes) is the figure (+0x2e; B = its object id), the motion name (+0x32), a started flag (+0x4b) and one
  option byte (+0x4c); its run (`FUN_10e0_0055`) only polls `FUN_1098_151c`, which asks whether the model has a
  motion. On load the reader rebuilds the model from the type (`FUN_1088_2a87`: the old one is destroyed,
  `FUN_1088_0000` / `0142` make a new one), and the fixup (`FUN_1088_4d67`) resolves the task slots, then starts
  `I_AM_DEAD` for a figure with no hit points, or else, when the figure still has a motion task, restarts that
  task's motion from its first frame (`FUN_1098_06e0(model, task+0x32, 0, 0)`). A figure with no motion task gets
  no motion there and falls back to its idle on its next update (`1088:4155`). So after a load every running
  motion starts again at frame 0, as in the port. The port differs in one case: a script's `MOTION ... CONTINUE`
  still running at the save is saved as the idle stance, where the original restarts it (its task survives).
  The save-resume failures put down to the phase above would therefore happen in the original too (CORRECTED below: they are
  not phase failures). Not checked live.
  Fixed in both ports: such a motion (non-looping, `MOTION ... CONTINUE`, not finished) is written as a 0x46f5 task (the shipped
  template's object with the name at +0x32, +0x4b = 1, +0x4c = 0, B = the figure's object id) linked from the record's +0x13d, and
  every other record now writes 0 there instead of its template's stale slot. Resume restarts it once from frame 0, still owned
  by the script (`task_name`, `unwaited`). A blocking MOTION comes back through its process, which re-runs the statement.
  The save-resume check then finishes 19 of 29: `garage-up`, which `main` finished, now fails at `CNT_BTN3` ("Space ... did not run
  CNT_BTN3_USE"). Its save holds the one such task, GRDHALL's `TAUNT4`, which used to come back as the idle stance and now plays
  again from frame 0. On `main` the other nine failures were the same.
- **None of the save-resume failures is the animation restart (2026-11-08).** `save_resume_check.py --control` does no save: at
  each save point it only does what a load does to the animations (`restart_animations`: every placed figure's motion back to
  frame 0 with no carried root, a one-off that is not a running CONTINUE or a waited MOTION becomes the idle stance, positions
  rounded to whole units) and plays on. All 29 boundaries reach EXIT (one skipped for its open monitor), `garage-up` included. So
  all ten failures of the real save (`tanks-back`, `operating-room`, `tower-exit`, `grdcon`, `hardsuit`, `garage-up`,
  `reactor-room`, `landpad`, `beach`, `platform-exit`) come from state the save or the load loses or changes, not from the
  phase. The control keeps everything else as it was, so the culprit is among what a fresh figure, item or VM lacks: unsaved figure
  fields (fall / teeter / step / turn state, combos, confront tasks), native processes the writer drops, the game clock, the global
  item list, or a resume difference. Not yet found.
- **What the save lost, found by diffing (2026-11-08, both ports).** A scratch tool saved and loaded at each failing point and
  compared every figure, item, global and process with the world that was saved. Fixed:
  - **Never written:** the AI process link (+0x152; the template's stale slot could even link a wrong process), the avoidance list
    (+0x1f3 count and 8 pairs), F (model+0x88, a FLOATATHEIGHT override), the FLOATATHEIGHT cap (+0x14e), the whoah teeter (first
    byte of +0x146) and the CAPTUREKEYBOARD hook. The hook is the PLAY record's task slot (`DAT_1290_6530`), a process every key
    event restarts (`FUN_1138_1da6`); the port writes the hook block as an idle process and resume only takes its name from it
    (ASSUMPTION). Without it the zero-g room's ZEROG_KEYBOARD was gone and the mirror suit never came off.
  - **Written but not read back:** the invulnerable flag.
  - **An item held in a limb:** only LTHAND/RTHAND were written as the hand string, so CAYARM in UP_ARM came back in the
    inventory. Any slot but the inventory is written now.
  - **Motions:** a looping MOTION ... CONTINUE is a motion task too. A dead figure keeps DIE and holds its last pose. The
    original's fixup starts `I_AM_DEAD`, which no body has, so the figure gets no motion; the held pose is the port's ASSUMPTION.
    A type with no idle motion (ESCHEAD) keeps its finished one-off held instead of getting a STAND it lacks.
  The check now finishes 23 of 29. Left: `tower-exit`, `operating-room`, `grdcon` and `hardsuit` stop on BEACH at "the Captain's
  speech ends"; every one of those saves loses the item CAYARM, which belongs to another level (the global item list; the
  floor-items work). `beach` fails at DIGSITE (`dig-tube-to-tunroom`); it also loses CAYARM and WTALKY. `tanks-back` stops in
  TOWER at "the landers are not down": its diff shows nothing left but the idle stance of a stopped USE_BOT, so it is not explained.
- **A level keeps its items when Lex leaves it (2026-11-08, from the code; both ports).** LOADLEVEL's level change
  (`FUN_10d0_4d46` -> `FUN_1148_14a3`) first detaches the player through his vtable +0x40 (`FUN_1088_2da1`, vtable 1290:2c4b):
  `FUN_1070_06ba` -> `FUN_1060_0df8` detaches, last to first, every object in the object list (1290:1cc5) whose holder (+0x2c/+0x2e)
  is the player (each through its own vtable +0x40, so recursively), takes each off the list and puts it on the carry list (1290:1d25). Then
  `FUN_1148_1404` -> `1232` writes every object left in the list to the old level's IFF in the play directory (`OBJS`, vtable +0x34),
  and `FUN_1148_15c7` reads the new level's IFF (`FUN_1148_1386` -> `0d46`) and attaches the carry list there (vtable +0x44,
  `FUN_1088_2dfc` -> `FUN_1070_0755` -> `FUN_1060_0e95`, which re-attaches the held objects the same way). So floor items, and items a
  level figure holds, stay in the level's file, and a return reads them back; what Lex holds travels. The save (`FUN_1148_1523`)
  writes the current level the same way with no detach, so a save's file has the PLAY record and Lex's items (as the saved CHAOS
  shows), and the other levels' files are whatever the last level change left. The ports keep the items that stay in
  `World.level_items` (Python) / `levelItems` (Swift) per level, with their object locals, instead of writing the IFF at once;
  `stash_level_items` / `stashLevelItems` and `load_floor_items` / `loadFloorItems`. In the ports an elevator's carried figures take
  their items along (INFERRED: the original's volume carry detaches them the same way; not traced); items lying inside the volume
  travel too (done 2026-11-16, "LOADLEVEL: missiles, the volume carry and offsets"). A save writes each kept level's items into that level's file (`savewrite.build_files`
  `other_levels`, `SaveWrite.buildFiles` `otherLevels`) and every written level now drops the ITEM records of items no longer
  there (carried off or destroyed); a level read from a file brings its floor items and the items its FIGR figures hold
  (`resume` adds only the player's). The old rule that a carried item of the same name hides a floor record is gone: the original
  makes no such check. Figures: done 2026-11-15 ("A level keeps its figures", below). Missiles: done 2026-11-16 ("LOADLEVEL: missiles, the volume carry and offsets").
  Effects: ORIGBIKEBAT no longer comes back in the bike when CONTROL reloads; the battery Lex left there is what the ending takes
  out (BAT_100_USE, its type's use; every battery use calls REPLACEBATTERYINLEG, ITEMS.scr:1313-1329). In TUNROOM the marine
  speech no longer finds `WTALKY` held by `GRDHANG` in CONTROL, as in a loaded game, so the save-resume check's `platform-exit` passes.
  The run loses the 150 energy the fresh battery gave, so more streams reach the bike under BIKE_NEEDS and take the battery trip;
  the harness's trip had only worked with an ABAT_500-named battery in the bike (`short_battery` wanted ABAT_500_USE, and its
  segment swallowed the Stuck) and took the first ALBAT on PLATFORM's floor, which now keeps older ones. With both fixed,
  `run_seeds.py` finishes 24 of 25 streams (14 still loses Drogg 3) and the save-resume check 23 of 29, the same six as before
  this change: `tanks-back`, `tower-exit`, `operating-room`, `grdcon`, `hardsuit` and `beach`. CAYARM (USE_BOT's, in CHAOS) is now
  missing from the live run as well as the loaded one, so it is not what those five lose.
- **A level keeps its figures (2026-11-15, from the code, the scripts and a live file; both ports).** The level change writes every object
  left in the object list to the old level's IFF (`FUN_1148_1404` -> `1232`, "A level keeps its items when Lex leaves it"), figures
  included, and a return reads them back; the per-frame AI start (`FUN_1088_3371`) restarts each AI from the record's name. KILLFIGURE /
  KILL (`FUN_1090_135a`) destroys the figure's object, so a killed figure has no record and stays gone; one carried off in an elevator's
  volume has left the list too. The scripts rely on it: CHAOS_LOAD kills HALMECHO only `IF SETCURRENTFIGURE HALMECHO` and resets its
  pacing state (CHAOS.scr:12-25), READY_TOWERBOTS and KILL_BEACHBOTS likewise (AI_TOWER.scr:94-99, BEACHBOT.scr:322-329).
  Live (`re/out/tank_fall_live`, the run that fell into the tanks): the original rewrote GAMEDAT/CHAOS.IFF at that level change, 22 s
  after the load, and no other file; the PLAY record is gone (Lex detached) and every FIGR record has its runtime flags (0x80 set:
  5 -> 133). That save was the port's own `tanks-back`, which still had FIRSTBOT (killed before the trip) back in CHAOS with ~0 = -666:
  the ports rebuilt every figure from the level file on a return. Now `World.level_figures` / `levelFigures` keep the left level's
  figures (all but the player and the travelling ones) as objects, `stash_level_figures` / `stashLevelFigures` reset what a record does
  not keep (processes, GO, confront, area; a one-off motion held on its last pose and a dead body frozen on DIE, as resume.py does), and
  `load_objects` / `loadObjects` puts them back on a return and marks every other FIGR name of the level killed, so `figure()` does not
  rebuild it (CREATEFIGURE still can). Saves write a kept level's figures (`figure_states` of the kept ones) and drop its other FIGR
  records (`build_files` / `buildFiles` `other_levels`). Not done: a level entered for the first time after a load is built by the
  level loader, which takes position, flags, AI, AI-off counter and locals from the records but not heading, motion, velocity, enemy or
  avoid list (a load restores those only for the current level). Gates: saves 28 of 29, control 28 of 29, seeds 19 of 26; seed 3,
  which passed, now loses the Captain on a random stream that moves at the first return to a level (tick ~38133), and the default full
  run ends with Lex at 67 HP instead of 61 (`full_run.json` regenerated).
- **The inventory order after a load (2026-11-08, from the code; both ports).** `re/tools/save_trace.py` runs the saved-and-loaded game
  and the `--control` game side by side from the save point and prints the first tick each kind of state differs. For `tower-exit` the
  first difference that mattered was the inventory: the loaded game listed `MEDICAID, FORK, DANELOG, MY_BATTERY`, the live one
  `FORK, DANELOG, MY_BATTERY, MEDICAID`, so the harness's `ready_item` clicked IPDB fewer times, the heal and the walks after it ran a
  few ticks apart, Lex reached BEACH with other HP, a bot's bolt knocked him back (RECOIL_ML) during the warhead escape, the fuse ran
  out with him inside BOMBHALL and BLOWLEXAWAY sent him to 6666 6666 6666. All four CONTROL saves (`tower-exit`, `operating-room`,
  `grdcon`, `hardsuit`) stopped there, at "the Captain's speech ends".
  The inventory walks the item list (`FUN_10d0_0076`: `DAT_1290_1d0d` entries of `DAT_1290_1d15`, each tested by `FUN_10d0_0000`), not
  the object list. An item appends itself to the item list when it is made (1050:10bf) and leaves it when destroyed (1050:0ff4). At a
  level change the carried items stay alive on the carry list, while the old level's are written out and the new level's made, so the
  live list is in creation order: what Lex brought first, the level's items after. The level reader (`FUN_1148_0d46`) makes the objects
  in chunk order, so after a load the item list is in the file's record order. The port's writer already writes the items in the
  world's creation order (`level_layout`), but its loader added the level's floor and figure-held items first (`load_floor_items`) and
  the player's after (`resume._items`). Now `resume._items` / `Resume.items` put `World.items` in record order, so a port save comes
  back with the inventory as it was. With that, all four reach EXIT. INFERRED, not checked live: the original's own save writes the
  object list order (level objects, then the player and what he carries, appended by `FUN_1060_0e95` -> `FUN_1050_0df0`), so loading
  one of its saves does reorder its inventory (floor items picked up later come first); a port save loaded in the original would not.
- **Port saves load in the original (2026-11-08, live check).** The first port save tried in the original (`guard1`, DOSBox-X,
  `dosbox_live.py --load-save`, keys `esc l 1 l enter y enter` after a new game starts) was unpacked byte for byte and then stopped
  the game with a protection fault (DOSBox-X log: a word write at ES:FFEA beyond limit 5DBF). Swapping files between the original's
  own `re/out/native_save` and its round trip through the port (load, save again) placed it: the port's level file alone loads,
  its SCRIPT.DAT (with MISC.DAT's serial table) faults. The writer copied each script process's 3746-byte object from one template
  process and set only the fields the port's reader uses. What the original's loader (`FUN_1230_1d7c`; per class
  `FUN_10c0_4a91`, lists `FUN_1240_08db`) takes from that object, now written per process (`savewrite.task_script_dat`):
  - +0x41, the brace depth. The interpreter raises it at `{`, lowers it at `}` and ends the process at 0. The template held 4,
    so every process ran past its block's closing brace into the next block's text. It is the count of `{` minus `}` from the
    definition to pc (strings and `//` comments left out), plus one for a `[` timeline; all 23 processes of both original saves
    hold exactly that (`savewrite.block_nesting`).
  - `[` blocks are a subclass, vtable 0x307f (3754 bytes: +0xea2 the timeline origin, +0xea6 the next due time, `10d0:6b03`);
    the writer made every process 0x3031. The two clock values are copied from the shipped GAMEDAT (ASSUMPTION: the same values
    in both original saves).
  - The two lists at +0x16 / +0x20 (vtable, count, ?, far pointer): the loader reads a list's entries only when the stored pointer
    is nonzero, and the original writes an empty list as count 0, no terminator. A link "P waits for T" is written as
    `FUN_1238_0f48` makes it: T in P's list1, 0x2000|T in P's list2, 0x4000|P in T's list2. A CALL child's +0x71 (the B
    record's wait_slot) is its caller, which gets the RETURN value at +0x47; the caller waits at the CALL statement with +0x46
    set (`10c0:3968`). A process in a plain WAIT has wait_slot 0 and its Wait task in list1.
  - +0x70, the local count, is the block's LOCALVAR count (the B record holds that many values, not 10); obj_b is 0, not 0xFFFF
    (0xFFFF reads back as the first persistent object).
  - +0xe bit 0 is the suspended bit (camera links, SUSPENDPROCESS, "Camera-linked processes"); bit 15 is left over from the
    wake-up of an earlier child (`1238:0000`) and is written 0.
  - +0x75..+0xe7a is scratch per depth: ELSE flags (+0x75+depth), 350-byte statement buffers (+0x7f + depth·0x15e), CALL
    argument values (+0xe2b), variable pointers (+0xe53); written zero.
  - Kernel entry 4 (a bit per task group in use) is rebuilt from the written tasks; a TIMED subtitle / sound handle's Wait task
    has no owner and so no links (the old writer linked it to slot 0, the interrupt handler). The original's subtitle task
    (class 0x4901, 422 bytes with the text) is still not written (ASSUMPTION: a plain timer stands in).
  The level writer now also keeps item records where the level file has them whenever the world's item order is the file's,
  so the object ids of the original's save survive a round trip; it moves them to the end only when the order changed (PR 79,
  "The inventory order after a load"). Round trip of `re/out/native_save` through the port now: every process matches the
  original's in class, depth, links, wait slot, flags and locals, except NURSEBOT_AI's bit 15 and pcs that the port sets on the
  next statement past comments; the level file differs only in figure-record details (motion-string tail bytes, a motion task's
  slot number, z rounding). Live, the original loaded three saves without a fault and with Lex where the port saved him: that
  round trip, `guard1` (CHAOS, BLK3) and `hall-to-elevator` (TOWER, ELT1); after `guard1` it runs the same ten script processes
  the port saved, with the camera-linked ones paused as on that camera, plus LEX_STAND, which it starts itself. Not checked
  live: a save with a pending CALL child, a ramp or a timeline that has started. The other direction already worked: both ports
  resume the original's own saves (GAMEDAT, `re/out/native_save`).

- **Two save points failed on the heading's last bits (2026-11-08).** `tanks-back` and `beach` failed after a load, and the same way with
  no save at all once `restart_animations` also rounds each heading to the record's 8.8 matrix (`level.ObjRec.heading`: 256·cos, 256·sin),
  as it already rounded positions to whole units. So nothing else the save drops was involved. The record is the original's own
  precision: the figure's persistent orientation is an 8.8 matrix (figure+0x111, "dosbox_live" `base_heading`), and every root move goes
  through it (`FUN_1088_0581`, "Root moves round down"); the original's save loses nothing it holds. The port keeps a float heading, finer
  than that, and the load drops the difference (at most about 0.2 degrees). Both failures were harness steps with no slack, now fixed:
  - `tanks-back`: the time went into the harness, not WARNROLAND (whose `FACE ROLAND GRADUAL` snaps in the port and lasts ~50 ticks).
    `roland()` walks Lex out of Roland's ZONE with a full `goto`, and that walk went on turning in 1.4 degree taps for ~350 ticks after
    `_GunActive` was set; Lex mounted the gun at `_LND2_FRAME` 58 unsaved (the first-hit loop stops at 60) and 61 after the load. The
    walk now takes 3 steps at a time and the loop checks `_GunActive` between them.
  - `beach`: at the dig tube the walk ended at heading 94.6 instead of 111.2 and Lex's hull missed the DIGTUBE box (`usable_objects`
    empty), so Space ran KEY_USE, not DIGTUBE_KEY_USE. The step now faces the box and steps in until Space would use it, as
    `tube_monitor` does at the pillar base.
  With both fixed, every save and every `--control` run reaches `EXIT`.

## Figure grounding: gravity and root motion (2026-10-15)

- SetPos (`FUN_10a0_1ff0`): with figure flag +0x34 bit 0x01 (gravity) set, z = floor(x, y, z) +
  F + R; without it, z is used as given (USE_BOT sits exactly at UBOTLOC z).
  - F = model+0x88: depth of the lowest limb joint below the root in the rest pose (`FUN_1040_0cf8`;
    2312 for the MAN skeleton from the fixed-point FK, see below).
  - R = model+0xa6: the current motion's root z (STAND = −40).
  - Check: −7405 + 2312 − 40 = −5133 = Lex's saved z (and the live value).
- Floor query `FUN_1060_0871`: over every PHYS box whose xy range holds the point, a state-1 box
  offers its top if the query z is above its bottom, a state-0 (space) box offers its bottom, and
  state 2 offers nothing; the highest offer wins (none = −819200). Names starting with 'Q' (pits)
  get a second pass (see "Grounding, recovered 2026-10-16").
- Per frame (`FUN_1088_39ef`, also `FUN_1078` ~line 980): unsupported gravity figures fall
  (`FUN_10a0_0072` starts the fall; `009b` are the whoah edge probes; full logic below). Recovered 2026-10-16:
  - `[83a0]` is the frame time, not a gravity constant: `FUN_11e0_0086` keeps the last three
    deltas of the 60 Hz clock `[8330]` and sets `[83a0]` = (sum << 8) / 3, i.e. 8.8 fixed-point
    ticks (512 at 30 fps). A single delta over 30 ticks is skipped; 0 becomes 1; the cap is 0x12c00.
  - `FUN_1000_265f` is unsigned long division (`2658` signed; `2706`/`2727` long shifts by CL).
    So gravity is vz −= `[83a0]` / 5 per frame (102 at 30 fps), applied only while
    vz > −0x500 (−1280): the disassembly is `CMP [vz_hi],−1 / JL / JG / CMP [vz_lo],0xfb00 / JBE`, so vz runs 0, −102, …, −1224, −1326
    and stays (13 frames at 30 fps). The earlier −0x10500 was a misread of that compare (fixed in both ports 2026-10-22).
  - Integration: fps = 0x3c00 / `[83a0]` (60·256 / dt, integer), scale = `FUN_1210_0c24`(0x1e00,
    fps << 8) = 30/fps in 8.8 (`0c24` = (a << 8) / b, `0c42` = (a·b) >> 8); the step
    `0c42`(v, scale) is added to the 32-bit position (+0xb/+0xf/+0x13). Positions are whole world
    units (SetPos adds the floor height, F and R without a shift), so at 30 fps gravity is
    102 units/frame² and velocity is in units per 30 fps frame.
- F (model+0x88) in detail (`FUN_1040_0cf8`, from the disassembly): walking the limb list from the
  root (`+0x70` next), take the lowest of each limb's world z (`+0x29`, 32-bit) and that z plus
  the z of the ROOT's vector `+0x3a` scaled by ((root+0x5e · (root+0x17 << 8)) >> 8) >> 8 (the
  same root vector for every limb, as written); F = root z − that minimum, stored at +0x78 of the
  root limb (= model+0x88); +0x96 is cleared. Limb positions come from the fixed-point FK
  (`FUN_1038_035b` via `FUN_1040_0c7e`), so F is a whole number: the engine's MAN F is 2312, not
  the floating-point 2313.6 (guards sit at floor + 2312; −7405 + 2312 − 40 = −5133 = Lex's saved
  z). The FK port is in `salsa.foot_depth` and the Swift port.
- Missiles read `HAS_GRAVITY`/`IS_BOUNCY` script properties (MISSILES.scr; `FUN_1088_22ba`
  sets +0x34 bit 0x10 for bouncy, and gravity from `HAS_GRAVITY`, default on). `FUN_1068_0c84` sets the gravity
  bit on a level object (class 0x2077), not on figures.
- `GRAVITY CURFIG ON/OFF` toggles the bit. The wake-up (`STARTUPLEX`, AWAKEN.scr) turns gravity
  off, places Lex at PLAYLOC z (the lying pelvis, 298 above the bed top), and turns gravity back on
  after STAND. Level figures keep the gravity bit saved in their FIGR record; created figures get it from
  `HAS_GRAVITY` (on).
- Root motion (`FUN_1088_0581` per frame via `FUN_1088_2035`): the change of each frame's root
  (first 18 bytes of a MOTN frame: s32 x, y, z + angles) is rotated by the orientation and applied,
  for every motion, not only walking. x/y accumulate; z is an absolute offset reset to 0 at motion
  start. NURSEBOT: BOTLOC z −6256 + ACTIVATE +1700 + STAND +20 = −4536 against the saved −4534.
  CONTINUE/FREEZE/SNAP_TO interaction with the reset is not recovered.

### Grounding, recovered 2026-10-16 (second pass; implemented in both ports)

- **Fixed-point FK** (`FUN_1038_035b` per limb, via `FUN_1040_0c7e`). Limb record: +0 name, +9 rest angles (3×s16),
  +0x11 current angles + s16 scale +0x17 (0x100 = 1, set by `FUN_1030_1138`), +0x19 target angles, +0x21 s32 pos[3],
  +0x2d matrix (u8 flag + rows +0x2e/+0x3a/+0x46, 3×s32 each, **8.8: 256 = 1**, identity from DGROUP 0x8f50 set to 0x100),
  +0x52 offset[3], +0x5e length, +0x62 interpolation steps, +0x6e done, +0x6f no-interp, +0x70 next, +0x74 parent.
  Per limb: copy parent's end pos and matrix (`02d3`, `1208:226f`); pos += Σ offset_i·row_i (each product
  `0c42` = (a·b)>>8, 64-bit product, floor); `1030:1175` steps +0x11 toward +0x19; rotate by rest then current angles
  (`1030:1054`): each angle a → deg = ((a·45) >> 5) << 8 (whole degrees, arithmetic shift), order Z (`1208:2b64`),
  X (`2548`), Y (`2858`), skipped when |deg| < 0x38. Rotation (X shown, rows i=1, j=2): old = r_i; r_i = r_i·c; r_i += r_j·s;
  r_j = r_j·c; r_j −= old·s (each product >>8 separately). Z uses rows 0/1 the same way; Y uses rows 0/2 with signs
  swapped (r0 −= r2·s; r2 += old·s). Then pos += row1·((0c42(length, scale<<8)) >> 8). The stored +0x21 is the limb's END.
  cos/sin (`1200:05fd`/`063c` → `1210:0cca`/`0c71`): angle normalised into (−180°, 180°] (`1200:0be3`), q = angle >> 6
  (quarter degrees, +1440 if negative), table of 361 bytes at DGROUP 0x8f74 (file offset 0x106774 in BIOFORGE.EXE; DGROUP
  = NE segment 83 at 0xfd800), value 256 at index 0; cos: q<360 T[q], q<720 −T[720−q], q<1080 −T[q−720], else T[1440−q];
  sin: q<360 T[360−q], q<720 T[q−360], q<1080 −T[1080−q], else −T[q−1080]. T = floor(256·cos(i/4°)) except T[240] = 127.
- **F** (`FUN_1040_0cf8`, root pos 0, identity root matrix, skeleton file angles): computed per skeleton with the above,
  F = MAN 2312 (exact), CAYNAN/DROGG/ESCHER/GRDOP/TEST 2312, HARD 2317, ACID/ACIDIE 6887, ACIDD/ACIDD2 3607, ACDIE 878,
  ELITE 1548, FIDO 1321, MECHO 2163, NURSEBOT 879, REACTBOT 1240, SHRIMP 1042, TOWERBOT 544, CONBOT/DANE/DANE2 0.
  **Verified against data:** every INITGAME FIGR record stores the model's F (record field `s88`, = model+0x88), and all
  48 records match this table (MARINE/TUMOLT 2317, ACIDD 3607, MECHO 2163, FIDO 1321, NURSEBOT 879, TOWERBOT 544, ...).
- **Hull** (`FUN_10a0_0000` → `FUN_1070_08df`): s = (F·100 + 128)/2048 cm; cm → units v·2048/100 (truncating, so
  UNITS_PER_CM is 20.48, not 20); box min = (−ex, −ey, −s), max = (ex, ey, ez) from script EXTENT (default 10,10,10);
  `FUN_1058_12c7` stores sizes at box+0x18 (dx, dy, dz). Hull at fig+0x65 = position + box (bottom z fig+0x6d, top +0x79).
  INITGAME check: saved +0xee equals z − s_units for every record (MAN s_units 2293, HARD 2314, FIDO 1310), i.e. the
  editor left figures with the hull bottom on the floor; the running game then grounds them at support + F + R.
- **Support** (`FUN_1060_03f2`, box query, fig+0xee via `FUN_10a0_21b2`): best = −819200 (or the area's PHYS slot);
  over the area's PHYS list: solid (state 1) with inclusive xy overlap offers its top if top > best and hull top > its
  bottom, and sets inside = z-overlap (last solid wins); space (state 0) with xy overlap offers its bottom; any such space
  named 'Q…' sets the pit flag. If pit flag and not inside: each 'Q' space whose top ≥ hull bottom and whose bottom < best,
  with xy overlap, lowers best to its bottom if the hull moved down to it collides with nothing (`FUN_1058_1a1b`).
  `FUN_1060_0871` (point query; SetPos via `0d9a`, whoah probes) is the same with point-in-xy tests, query z = the point
  z or box+8 when a box is passed; its 'Q' pass needs no collision test. PHYS memory: min +0xb/+0xf/+0x13, max
  +0x35/+0x39/+0x3d, slots +0x4b (bottom) / +0x4f (top), state +0x4a, name +2.
- **Per frame** (`FUN_1088_39ef`, gravity bit set, not attached (+0x2c), +0x1e8 clear, area +0x35 set): k = dz/4
  (fig+0x14a = `0c24`(dz, 0x400)); threshold = hull bottom − 2k. If support < threshold and vz == 0 and not falling:
  `FUN_10a0_0072` sets falling (+0x1e9) and calls vtable+0x9c (`1088:3196`: +0x229++, suspends the figure's script
  process and player input; **no motion is forced**). Else if vz == 0 and +0x229 == 0 and !(flags & 8): whoah probes
  (`FUN_10a0_009b`). While falling and vz > −0x500: vz −= [83a0]/5. If vz == 0 (and !(flags & 2)): model base = support
  (z = support + F + R, the step down/up snap); otherwise base = z − F − R. Velocity step (`FUN_1088_384e`) then move;
  vtable+0x5c (`FUN_10a0_0ead`) runs when the hull collides or support > hull bottom: falling ends (vtable+0xa0,
  +0x229−−), if support > bottom + 0x1000 the previous position is restored, else z = support + (z − bottom);
  the position helper `FUN_10a0_2158` calls vtable+0x58 (`10a0:1ff0`) → `FUN_1070_1e9d`, which clears
  velocity before calling the landing classifier. `FUN_10a0_0e24` has hard (vz ≤ −0x280), medium (≤ −0x140)
  and soft branches, but this normal floor-contact path reaches it with vz = 0 and requests `land_soft`
  (vtable+0x7c = `1098:0e49`). The prototype and Swift port now match this order; other impact paths remain separate.
- **Whoah probes** (`FUN_10a0_009b`, query struct from `FUN_1060_0000`/`006e`): C = hull centre xy at hull bottom,
  h = half x width, D = facing row1·h, S = row1 after rotZ(−90°)·h (= row0; `1208:2f60` renormalises, ignored). Probes
  C−D `whoah_forward`, C+D `whoah_backward`, C+S `whoah_left`, C−S `whoah_right`, each a point query with the hull top as
  query z; a floor that exists (> −819200) and lies below the threshold plays that motion and sets +0x146. While +0x146 is
  set the probes repeat and clear it when all are fine. `FUN_10a0_0d93` picks mantle_3/6/9 by height < 0x800/0x1000.
- **Areas** (`FUN_1138_1a93`, per frame via `1138_1b8a`): keep the current area while the position is inside its PHYS,
  else the first area containing the position, else the first whose PHYS overlaps the hull, else keep the old one
  (sticky). No area → no gravity processing.
- **Gravity default:** the +0x34 flags are saved in each FIGR/PLAY record (byte 21). INITGAME: TOWERBOT, NURSEBOT,
  DANE2, SHRIMP have gravity off (0x04); all others on (0x05). `FUN_1068_0c84` sets bit 0x01 on the level object it
  builds (class 0x2077, IMAG-type) after resetting areas, not on figures. `GRAVITY ON/OFF` = `FUN_1070_2232`/`223f`.
  CREATEFIGURE: the base object constructor clears +0x34; the figure set-up `FUN_1088_22ba` reads the type block's
  `HAS_GRAVITY` property (default 1, `1088:242c`) and calls vtable+0x70 (gravity on, `10a0:004c`) or +0x74 (off). Only
  missile/vehicle blocks (MISSILES, TANKCHEW TOSS, TUNGRAV ASTEROID) set it to 0, so created figures have gravity.
- **Collisions bit:** `COLLISIONS ON` clears +0x34 bit 0x02, `OFF` sets it (`FUN_10d0_1aa4`). `FUN_1088_39ef` stands a
  figure on its support and runs the landing test only while the bit is clear.
- **Port (both ports, 2026-10-16):** `salsa.foot_depth` (fixed-point FK, cos table read from BIOFORGE.EXE) gives F;
  `World.hull/support/point_floor/settle/whoah` follow the routines above (one prototype tick = one 30 fps frame).
  Movement now selects ordered areas from state-0 PHYS and those with a `_SPACE` binding, then scores every PHYS
  whose box touches the selected area's box grown by 0x1000 (`FUN_1138_1853`, `131c`, `1a93`). Correction (2026-10-31):
  grounding's support and point-floor queries ARE area-scoped (a far area argument Ghidra dropped; see "Area-scoped floor
  queries"); only SetPos, GO, FLOATATHEIGHT and item drops pass a null area (global).
  ASSUMPTIONS: a solid whose top is more than 0x1000 above the hull bottom offers only its bottom
  (a figure with collisions off, flag 0x02,
  can be inside one, so a walk can pass through a
  closed door); landing and whoah motions return to STAND (or to a running GO's walk) when they end; whoah facing
  vectors are float. GO snaps use SetPos (`point_floor` + F). Level figures take gravity and the collisions bit from
  their FIGR flags.
- **Live check (2026-10-16, `re/tools/dosbox_live.py`, new game, Medium):** standing Lex reads z −5133, flags 0x81,
  F 2312, R −40, model base −7405, support −7405, hull bottom −7405; in bed z −5754, flags 0x02, base −8026 (= z − F − R).
  GUARD1 and CAYNAN read z −5093; HALMECHO F 2163; FIDO (no area) support −819189 = its hull bottom. USE_BOT/FIRSTBOT
  flags 0x04/0x44 (no gravity). FIRSTBOT's F changes at run time (0 → 879 → 2579), so F is recomputed when a figure's
  pose source changes; irrelevant without gravity, not ported. No fall happens in the opening, so falling and landing
  are verified against the code only.
- **The 40 units between the ports and the original (2026-11-02).** A figure's record z is origin + R; the ports keep R in the pose, so port z = record z - R. Standing is no gap: port -5093 + R -40 = live -5133. In bed there was one: without gravity SetPos stores the given z as the record z (`10a0:1ff0`), so `GO PLAYLOC` means -5754 with R -40, and live reads -5714 once WAKE_UP's R 0 applies (sampled through WAKE_UP and OUT_OF_BED). The ports took -5754 as their origin. Now GO without gravity subtracts R, in both ports. A motion's frame 0 only reaches model+0xa6 at its first update, so a GO right after a MOTION still uses the previous motion's R (`applied_root_z` / `appliedRootZ`). STARTUPLEX does exactly that (GO PLAYLOC, SNAPTOPOSE WAKE_UP 0 FREEZE, GO PLAYLOC, AWAKEN.scr). Lex in bed now reads -5714 and his landing is unchanged. Still 40 off: before WAKE_UP starts playing the original reads -5754 (hull bottom -8047, R -40), while the port's snapped pose already has R 0, so its hull bottom there is -8007, not the live value noted under the opening's hull check. Collisions are off in bed, so nothing depends on it; port z + R matches once WAKE_UP plays. Only Lex in bed was seen live; other figures without gravity follow from `10a0:1ff0` (INFERRED). That includes ACIDD, which now stands 3299 units lower at BEAST_1, and it carries Lex lower on its finger.
- **COORDZ now includes R, both ports.** `10d8:104e` reads the record z, and the record z follows R through a motion. Live, OUT_OF_BED: frame 34 root z 255 reads -5459, frame 36 root z 665 reads -5049, both -5714 + R (the samples of the opening). So the ladder polls fire mid-cycle: at the ladder out of TANKS `COORDZ < -34` stops CLIMB_UP at -34, where the port used to read -31 at the next loop wrap. Played live since: see the next entry. `WARHEAD.scr:75-83` now gets its own z back from GO. The harness no longer turns Lex at the hatch: he faces west, and turning in place drifted him east into it (`hall_to_elevator`).
- **The ladder through the iris, played live (2026-11-02).** New game, Lex staged in the cryo room with `set_xy` / `set_heading`, then only real keys and scripts: CRYO_BTN, TRIG_LDR, the climb down, TO_CRYO, the climb up. Sampled every update. What it settled:
  - **A level arrival follows the GO rule.** Gravity off (TO_TANKS): z is the target's as is, ENTR_TNK's low z -3584. Gravity on (TO_CRYO_USE): the floor under the target + F, -13996 + 2312 = -11684, 564 under BTM_LDR's box. The ports used the box's low z + F for both, -1272 and -8808, so Lex entered both ladders too high and the -34 stop fell in the wrong cycle. Fixed in both ports (`cmd_loadlevel` / `cmdLoadLevel`). The player goes through vtable +0x44 from `1148:15c7`; that path was not traced, the rule comes from these two arrivals and the GO code. Other arrivals follow by the same rule (INFERRED); the full run moved by 60 ticks.
  - **Stop.** Live CLIMB_UP's origin runs -11684, -10563, -9442, and now the port's does too. The stop is on frame 14 at record z -8699, the first sample with `COORDZ` -34. Port: -8631, because it steps whole frames at 30 fps and the original blends between frames at 60. Live reads R 0 at once after STOPMOTION with the z kept, which confirms the commit in "Rising motions".
  - **MANTLE_6's end.** Live z goes -5862 to the floor in one update as the motion ends, with no fall and no landing motion: -8699 + 3083 = -5616 would be 523 under his standing origin, and he stands at -5093, reading -5133. The port lifts him the same way (from -8631, 455 under).
  - **The pit rule.** Staged at x -12100, where the whole hull fits over the pit, he falls at once. At -12269 and -12405 he stands. Matches "Make a pit the support only when the whole hull fits".
  - **Still different.** (1) Landing xy: see "Root moves round down", the next entry. (2) The WHOAH_BACKWARD frame on landing: fixed, see "Ending a rising motion marks the teeter". (3) Space reach: settled, see "Space is a hull test".
  - The DOWNLADDER stop was sampled too: record z -13893 on frame 23, `COORDZ` -55 (the `> -55` loop polls on a timeline, not every update), and the port stops at about the same height (-13913 with its coarser frames).
- **Root moves round down (2026-11-02, both ports).** `FUN_1088_0581` multiplies each update's root change by the figure's 8.8 matrix and shifts each axis down (`FUN_1210_15b4`, `FUN_1040_0f95`), so every update loses a fraction toward -x, -y. The drift is not root yaw. The ports rotated with floats. Sampled per update live (GOG settings, `re/out/ladder_live/up.jsonl`, heading 87): the shift reproduces all 88 MANTLE_6 moves and 175 of 177 CLIMB_UP moves; the other two are the loop wrap, which does not move. Normal rounding gets 39 and 49.
  - **The update count is not a constant of the game.** Clock ticks per update: about 1 in the ladder shaft at 35000 cycles (84 updates in a 90-tick climb cycle), about 1.9 walking in a busier room at 35000, about 3.7 at 8000 cycles. So the drift, and where a long root motion ends, depends on CPU speed and scene in the original.
  - **ASSUMPTION: one update per 30 Hz tick.** `root_step` / `rootStep` split a frame's root change over the 30 Hz ticks the frame lasts and shift each part. Against the ladder: a CLIMB_UP wrap moves (-34, -23), live (-46, -33); the landing is (-12355, -74517), live (-12405, -74564), about 50 off per axis (it was about 135). One update per 60 Hz tick landed about 35 off the other way, but Lex then drifted about 2200 units through PLATFORM's long mind meld and fell off the platform, which a real player would not see. That fall was not checked in the original.
  - **Other headings, live (walking, GOG settings).** WALK at 37, 127 and -53 degrees: the shift gets 61 of 62, 62 of 63 and 62 of 63 moves exactly; the single miss is the loop wrap. Normal rounding gets about 14 of each. A run at 127 walked into a wall and matched 43 of 62: the misses seen have x blocked at 0, so they don't count against the rule. Unproven only for the update rate above.
  - **What moved.** The seeded fights: `CAYNAN_SEED` 29 -> 46 (Lex 60; of seeds 0-47, 28 leaves 89 but never runs CAYNAN_STIMULUS), `GUARD1_SEED` 20 -> 19 (78). `GUARD1_SEED_FULL` stays 28 (Lex 33, not re-swept). GRDCON now lands one hit in `hardsuit`, so the full run ends on 89 HP. Harness: Lex turns on the spot before each BEACH block walk (the walk's steering took him over the edge), and steps toward the Elite if its attack falls short.
- **Ending a rising motion marks the teeter (2026-11-02, both ports).** `FUN_1098_0789` (motion stop or change, STOPMOTION too), when +0x1e8 is set, clears it and R and sets the teeter +0x146 = 1. `FUN_10a0_009b` then only repeats the probes until all four are fine, and plays no whoah. The port never set the mark, so MANTLE_6 played one frame of WHOAH_BACKWARD at the hatch and then kept teetering: Lex drifted about 1400 units with no key pressed ("Ladder top, fixed by that"). It also held +0x1e8 after STOPMOTION; the engine clears it. The earlier staged test at the port's landing showed no whoah because the mark was still on. Live traces (`re/out/ladder_live`): teeter 0 until ON_LADDER and ENTER_IRIS1 end, 1 through CLIMB_UP, DOWN_LADDER and MANTLE_6's stand. Port now: no whoah, STAND at the landing. No new live run: these are the traces of the ladder session. Edges reached by walking are unchanged; that path was not sampled live.
- **A held turn key steers a walk (2026-11-02, both ports).** `FUN_10a8_0541`, while the current motion is walk, walk_back, run, atk_m8 or atk_m2, adds `[83a0] << 1` per update for Left or Home and takes it off for Right or PgUp (`10a0:19e6`, 2 degrees per 60 Hz clock tick). Turn keys only ask for TURN_LEFT / RIGHT from stand or atk_stand (`1098:13e1`), and Up and Down are tested first. The port dropped the walk for TURN_LEFT at 45 degrees/s when both were held. Live: Up + Left stays in walk at 113-117 degrees/s, Left alone is 43-48. Port: 120 and 45. The whole-run harness never holds both, so its ticks don't change.
- **An end-of-update idle is drawn one update later (2026-11-12, both ports, live).** DOSBox-X, new game, breakpoint on
  `FUN_1098_0745`: it runs for Lex (stack figure pointer 0:4703) at the end of WAKE_UP, returning to `1088:41a4` (the `1088:4155`
  block), so the original requests the idle there as the ports do. The screen dumped after that update still shows Lex lying in
  WAKE_UP's last pose, and Lex's next update entry already reads OUT_OF_BED (frame -1, then 0): the script replaced the idle before it
  reached the model (a motion's pose is applied at the figure's next update). The ports drew STAND frame 0 at once, one standing pose
  in bed. Now the pose of the update is held for drawing (`held_pose` / `heldPose`) until the figure's next update; the simulation is
  unchanged. Per-update samples (live, clock 3709-4022): WAKE_UP frames to its last, then OUT_OF_BED directly, never `stand`. The
  live root motion also moves within a frame (OUT_OF_BED frame 21: y -7450, -7468, -7504), where the ports step once per frame.
- **The player returns to idle too (2026-11-02, both ports).** `1088:4155` -> `FUN_1098_0745` runs for every living figure with no motion task (+0x13d) and no event process (+0x15b), and the bit 0x80 test in `1088:508d` is the only opt-out (`MOTION ... FREEZE`). The port kept the player in his last pose until a key. From the code; not sampled live. The full run moved to 90758 ticks.
- **Four small audit fixes (2026-11-02, both ports), all from the code.** A missile that hits an INVULNERABLE figure flies on with no HIT (`10e0:0961`, +0x34 bit 0x08). CAPTION shows with subtitles off (`10b0:0f48` never reads [50bc]). A new subtitle stops the old voice (`10e8:0529` -> `08a4`). A class Q gauge draws frames 1..n + 1 together (`1270:0a64`), a backdrop and then the bars. The rendered audio panel was checked by eye; none were compared live.
- **No aim assist in a moving attack (2026-11-03, both ports).** `1088:3419` tests the motion name for "atk_m" (DS:2595) with a case-sensitive compare, but the keys name them "atk_M8" (DS:2b34), so only atk_stand and shoot auto-turn. Live, in combat near FIRSTBOT and 25 degrees off: atk_stand goes 25, 19.2, 13.3, 7.4; atk_M8 holds its heading throughout, and the name reads `atk_M8`. Seeds: `CAYNAN_SEED` 46 -> 40 (Lex 76), `GUARD1_SEED` 19 -> 14 (84). The 11 HP loss between Guard 1 and the BLASTER doesn't occur on this run.
- **A walk key breaks a scripted motion (2026-11-03, both ports).** `FUN_10a8_0541` refuses only on +0x229, z velocity, +0x1e8 and the +0x9e hold; then walk and run keys pass only the `1098:12bd` gate (RECOIL, DIE, SUPER_REC, the same name). The port's own rule kept keys out until a one-shot script motion ended. Turn and sidestep keys still ask only from stand or atk_stand (`1098:13e1`). From the code; not sampled live.
- **Keys while Lex is held (2026-11-12, both ports).** `FUN_10e8_11e3` hands every key to `FUN_10a8_0541` (no monitor up), and that goes to `LAB_10a8_058a` while +0x229, the z velocity or +0x1e8 is set: only S with no Alt answers, with the CANNOT_SAVE block at `[2a6a]`; the same branch serves a captured keyboard (`[6530]`). The ports checked this only for the motion keys, so a second I during PIMM_INVENTORY's `MOTION LOOK_AT_PIM FREEZE` (after its `AI OFF`, before `MON_START`) started a second block; the first page's exit left one AI OFF behind and Lex could not move. Now every key but S is dropped there, so the PIMM keys, O and R also do nothing during the wake-up (his +0x229 is 1 from the wake-up until he stands after OUT_OF_BED); the tests that opened screens then now wait for Lex, and so does the harness repair routine (`scenarios.start_repair`), whose D had landed mid-recoil; `run_seeds` 21 -> 22 of 26. From the code; not sampled live.
- **Missiles in saves (2026-11-14, from the code and a live check, both ports).** The missile class (vtable DS:47a9) has its own save hooks: vtable +0x18 `10e0:12b7` reads and +0x1c `10e0:135a` writes, after the common task part (`10b8:0d0b` / `0d67`: the two task lists and the owning process's slot, turned back into a pointer by +0x20 `10b8:0dd1`), the owner figure's and the missile item's object ids (`FUN_1128_0e84` / `0dec`). The item is an ordinary ITEM record of the level (position, velocity at record +58, orientation, flags). The task object is 0x56 bytes (ctor `10e0:0440`: base `10b8:0aa7`, vtable 0x47a9, owner at +0x44, type 0x10c through `1238:04ac`, the travel sound object at +0x40, the item at +0x52; +0x48 range, +0x4c/4e/50 spin). The ports dropped every missile at a save. Now `process_states` / `processStates` list each live missile, the writer gives its item an ITEM record with its velocity and flags and a missile task (A: the motion task's header, which shares the base, with the fields above; +0x3c 0, ASSUMPTION: the port does not keep the firing process; +0x40 0, see below), and `resume._missile` / `Resume.missile` turn the loaded item back into a Missile under the saved handle, so a `SUSPENDWHILE FIRE` waiter waits for it again. The travel sound is not restarted, as in the original (from the code): the reader `12b7` sets only the owner and item pointers, the update `0cbc` only changes the volume of the voice at +0x40 (`FUN_1058_0cb7` → `FUN_1028_1464`, which looks the handle up in the voice table and never starts one), and the save loader `FUN_1148_0490` calls `FUN_1028_13ac`, which stops all 8 voices and the queued ones (`FUN_1028_12d2`) and clears the voice table. The sound starts only in the constructor, so a loaded missile flies silently. Not checked live (DOSBox audio is not captured). NOT PORTED: what a missile carries (FIRE ... CARRY) is not re-attached; the player cannot save on a zip line. Live (DOSBox-X, a scratch run; the saves were made from `re/out/monkey_saves/bio-repair` after 30 ticks): a CHAOS save with one LASER 5000 units in front of Lex, written by the port, loads in the original with Lex hit, at 55 HP and knocked back about 100 units, as the port has him 10 ticks after the load (76 -> 55); the same save without the laser loads with Lex untouched at 76. A port save with a tower bot's NRLASER in the air also loads and plays on in the original.
- **The last audit findings (2026-11-15).**
  - *A process waiting on a ramp waits again after a load (both ports).* The writer listed the ramp task in the waiter's list 1, but `resume._ramp` / `Resume.ramp` did not register the rebuilt ramp as a task, so `SUSPENDWHILE MODIFYVAREVERYNTH` lost its target ("blocked on unknown task slot") and the waiter ran on with the next statement at once. CHAOSBLK's BLOCK_DRIP was the one seen: after a load mid-drip its two ramps overlapped. Now the ramp is linked like a missile or a timed handle; saved mid-drip and loaded, BLOCK_DRIP and `_dp1_frame` / `_dp2_frame` match the unsaved game for 120 ticks (`test_a_process_waiting_on_a_ramp_waits_again`, `aProcessWaitingOnARampWaitsAgain`).
  - *FORCERELOAD during a flic cannot happen in the shipped scripts (from the scripts and the code).* `10a8:02cc` returns while a flic is open, so the reload dialog would not open, and the ports do the same. But only EL_SCENE (BRINGONTHEALIEN) and ENDGAME open flics, both FREEZE first (every other task suspended, the world update stopped), and neither calls KILLLEX. No change.
  - *Corrupt saves (Swift).* Every read of the save reader goes through the throwing `Bytes` helpers. `SaveFuzzTests` flips bytes, cuts files and writes 0xFF runs into a real save, then unpacks it, boots it and runs 5 ticks and a frame of any that loads: 2000 cases, about half load and run, the rest end with a format error; none traps. The suite runs 40 cases (`SAVE_FUZZ=<n>` for more). The Python reader is not fuzzed.
  - *The one `swift test` crash (signal 11, 2026-11-08) was a data race in the tests.* `GameResources` is shared by every World, and its caches (`assets`, `compositors`, the lazy cos table, level index, extents and figure properties) were filled without a lock; Swift Testing runs suites in parallel. Thread Sanitizer showed the race between `makeMissileLimbShotStartsOutsideTheOwnerAndFliesAlong` and other tests in `GameResources.asset`. Now one lock guards them; the full suite is clean under `swift test --sanitize=thread`. The app runs one World, so it was never affected.
  - *`operating-room` failed on a medkit rule, not lost state (from the code, then checked live).* MEDICAID_USE runs `SETCURRENTITEM MEDICAID`, which takes the item of that name or type nearest the player (`10c0:3fd9`, `find_item`). ZEDICAID is of type MEDICAID, and in the inventory it lies at Lex's own position, nearer than the kit in his hand, so a MEDICAID use spends ZEDICAID's charges, and once those are gone it plays USE_MEDIC_FAIL with MEDICAID still full. From the save, the earlier fights went worse, ZEDICAID ran dry, the battery was flat, and Lex met Drogg 3 at 62 HP with no usable kit. The harness `heal` now puts an empty kit down when MEDICAID still has charges, as a player would (not in the middle of the Captain fight, where the put-down costs blows); the save point continues to EXIT. Counting both kits' charges when it checks a use was tried too: it spent kits where the battery had been used and lost two other save points to the Captain, so it was left out. Gates after these fixes: saves 28 of 29 (`grdcon` loses the Captain), control 28 of 29 (`operating-room` loses the Captain), seeds 20 of 26. Live (2026-11-15, DOSBox-X, `re/out/medkit_live`): the port's `landpad-to-elevator` save (Lex at 62 HP carrying an empty ZEDICAID and MEDICAID with 5 charges), readied with MEDICAID in hand by the port before it saved, loaded in the original, then Space. As saved, USE_MEDIC_FAIL and 62 HP. With ZEDICAID given 1 charge, USE_MEDIC to 82, then USE_MEDIC_FAIL on the next two presses with MEDICAID's 5 charges untouched. With the empty ZEDICAID put down first (Enter), USE_MEDIC to 82, then to 100. The port gave the same motions and HP in all three. A player who carries both kits meets the same rule.
- **GO steering (2026-11-14, from the code, both ports).** The GO task's walking state (`FUN_10e0_1a4c` case 4) calls `FUN_10a0_1f0a(fig, target)` on every update while the figure's motion is WALK, RUN or ATK_M8: it asks the angle to the target (vtable +0x60) and turns the figure by it when it is within 10 degrees, else by 10 degrees (`FUN_10a0_19e6` with 0xa00 / 0xf600, 8.8). The ports aimed once, in `cmd_go` / `cmdGo`, and never again, so a figure pushed off its line (PERSONAL_RADIUS, avoidance points) could pass outside the 614-unit arrival circle and run on into a wall for ever. That is what stopped stream 16 and the `hall-to-elevator` save point: after the sixth super recoil Drogg 1's `GO DCENTER RUN` passed DCENTER and ran away from it (heading 97.9 with the target the other way). Now `steer_go` / `steerGo` runs before each figure's update. ASSUMPTIONS: one task update per tick, before the figure's own update; the integer angle test is read as `|diff| < 11`. NOT PORTED: case 4 also ends the GO when the motion is none of WALK, RUN, ATK_M8 (the ports only skip the steering then). Every walking GO now follows a slightly different path (arrival points move by tens of units, e.g. LEX_POS2 548 short instead of 464), which moved the random streams and broke three harness spots tuned to the old paths, now made sturdier: the LANDPAD airlock button is approached again from the west until Lex faces it (TURN_LEFT travels); the warhead escape is staged at a fuse of 8 rather than 3 (a walk step is 9-15 ticks); after the TONFA Lex is placed inside the blast tunnel, as BCHBOT3 survives on some streams and holds him in recoil at its mouth; and the AIRMECHO duel dodges only while FIRE_GUN plays (a laser hit stops it and the frozen pose lasted through 100 ticks of AI waits). Two harness pickups were made sturdier too: the FORK falls back to `take` when `pick_up` stops out of reach, and `heal` presses I again when a LEVEL1TREMORS quake swallowed the press. On seed 8 REFLECT seemed out of reach; it is not (corrected the same day): DROGG3_DEATH drops it with PLACEITEM GROUND and moves it to LOADBTL4 only when it lies outside that box, and it lay inside, on the floor (z -1358 on floor -1492; Lex's origin 820 is floor + foot 2312), but behind the pillar BATPLR5, which stopped `take`'s straight walk; `take` now goes round when a straight walk stops short. Seen on the way, not changed: a figure whose own CONFRONTENEMY is still running when it dies is turned (atk_m4 / atk_m6) once DIE has finished, since `FUN_10e8_0079` has no death check (Caynan on the scenario stream); not checked live.
- **Falling into the tanks (2026-11-14, live check, both ports).** CRYTOTNK `FALL` (fired by the IMAG `FALL`, a slab just above the cryo shaft floor -13996): COLLISIONS CURFIG OFF, FADE, LOADLEVEL TANKS LEX_FALL, MOTION FLOAT, GRAVITY ON, then every 2 seconds `IF COORDZ (CURFIG) > -110` again, else PROCESS TANKDETH. The ports stood Lex on the walkway WK2 under LEX_FALL's box (z -21998, COORDZ about -86) and the loop never ended. Live (`re/out/tank_fall_live`: the port's tanks-back save loaded in the original, Down held for a second, Lex sampled every 0.1 s): flags 129 -> 131 (collisions off) while still falling, his hull passes the shaft floor (bottom -16516 against support -13996), +0x1e9 (falling) stays 1 through the load, the first TANKS sample is (0, 0, -816928) then (31888, -30101, -821411) (-816928 is the "no floor" -819200 + F + R; the second adds LEX_FALL's z -4483), vz builds again, and at the next sample TANKDETH has him at DROWN (-17408, -57344, -38781) with flags 2 and vz 0, sinking with the DROWN motion. So the original's arrival found no floor at all there; how (a query at (0, 0) before the point's offset is added is what the samples suggest) is not traced. The ports now place a player whose collisions are off at the arrival point's z with no floor snap (`cmd_loadlevel` / `cmdLoadLevel`): he falls through the walkway and FALL's test passes. The only other level change made with collisions off is DIGTUBE's (TUBE_WP4); the full-run replay is unchanged by the rule. Also from the samples: TANKDETH's `GO DROWN` (no WALK / RUN: placed at once) left vz 0, as SetPos does (`FUN_10a0_1ff0` -> `FUN_1070_1e9d` zeroes every velocity); the ports kept the -204 left from the fall and Lex sank out of view. Both ports now zero the velocity there (`_go_snap` / `goSnap`). Not matched: the original's arrival z itself, and the drown's sinking (the port keeps the root z in the pose).
- **Bug audit 2026-11-14.** Four code reviews and `MonkeyTests` (random keys and clicks at the 30 save points, routed as `AppDelegate.handleKey`, then: can Lex move; after a death does the reload dialog stay). Findings, from the code unless marked:
  - *The reload dialog (MUST_RELOAD, flags 2).* In `1280_callbacks.c` NOOX, LCAX, AOKX and ACAX set a366 = 0 and then go to the main panel (`176b`) when `[a36a] & 1` (_OPTS_DEFAULT), else turn the event into Escape (`LAB_1280_0e57`); at the end an Escape with `[a36a] & 2` and `[a36c] == 0` shows the exit prompt `214c(0)`, or the main panel when a366 is 0x51 (the prompt's id, set by `214c`). So a dead Lex's dialog never closes except by a load (or the exit / new game). The ports closed it on Cancel, OK, No and the credits' Return; now `Options.leave` follows the callback, and Escape with MUST_RELOAD toggles prompt / main. Escape without MUST_RELOAD still closes the dialog from a sub-screen (it goes to the monitor's own handler, `FUN_1250_0cf9`, INFERRED to close), except on the audio and gamma panels as before. Load > New > Yes starts a new game in the app (`newGameRequested`); a load that fails while `_forcing_reload` is set reopens the dialog (the port's own path: the original's empty-slot handling is not read).
  - *Keys go to an open monitor before a captured keyboard.* `FUN_10e8_11e3` sends keys to `FUN_1100_0769` (the monitor) while `[4e2c]` is set and only otherwise to `FUN_10a8_0541`, where the hook `[6530]` is answered. ZEROG_KEYBOARD (TUNROOM, TUNZEROG, TUN2PLAT) opens PIMM screens and the dialog itself (`MON_CODE`), and the app sent Escape to the hook, so they could not be closed by keyboard or controller.
  - *Held keys.* A key-up during a flic was dropped by the app, leaving the key in `keysHeld` (Lex walked on after the flic); every key-up now reaches `World.keyUp`, which only forgets the key. Controller modifiers released inside a screen, and a mouse button held while the window resigns key (the monitor's input stays off from the press to the release, `FUN_1250_0415`), are released too.
  - *Crash risks (Swift).* Script waits on GO, MOTION, FREEHAND and CONFRONTENEMY captured the figure `unowned`; KILLFIGURE or LOADLEVEL can free it while another process waits. Now `weak`, and a freed figure ends the wait. Script arithmetic was checked: `&+ &- &*`, guarded division. Small clamps: music volume, a sprite frame below `-count`, a zero hull span in the mover.
  - *Saves.* Written with `.atomic`. A failed save or load shows an alert in the app (`World.fileError`, the port's addition; what the original shows is not read). A ramp slot (`MODIFYVAREVERYNTH`) is now linked to its waiter on a load (see "The last audit findings").
  - *Music after a load matches the original (from the code, not checked live).* Opening the dialog stores the playing song in `[4e30]` (`1100:0631`, `FUN_1198_0029`); closing it (`FUN_1100_0740`, from `1100:0546`) stops the dialog's music and restarts `[4e30]` only if it is 0 or more. The save loader `FUN_1148_0490` sets `[4e30]` to -1 at its end, so after a load the music stays off until a script's next `MUSIC`, as in the ports.
  - *Keys under Command (app).* macOS sends no key-up for a key released while Command is down, nor for one pressed with it. The app now ignores a key pressed with Command and lets go of every held non-modifier key when Command goes down; before, such a key (a letter bound to a move, or Kick on A) stayed held.
  - *Falling into the tanks:* fixed the same day, see "Falling into the tanks".
  - *Monkey false positives, for reading its output:* the zero-G room captures the keyboard by design (`ok_captured`); the tower gun captures it until Escape or KP2 (TOWERGUN.scr CBG); LEVEL1TREMORS quakes, the CONTROL robot console (`GR_ROBOTCONTROLPANEL`) and the medic kit hold Lex for a while.
- **The native port runs the whole game (2026-11-03).** `re/tools/full_run_transcript.py` records every call the harnesses make into the engine, and any state they edit directly (found by comparing snapshots around each call). `FullRunTests` replays that through `GameSession` and compares each 200-tick checkpoint: level, camera, every figure's position and motion, Lex's HP and heading, the script globals and the next process handle. It's about 5 seconds, so regenerate the transcript whenever the full run changes. Replaying found three real gaps in Swift, all in monitors: buttons with no text were never defined (`MON_DEFINEBUTTON "bt1b" _MON_NORMAL`, so CC_CIRCUITBOARD could not be solved in the app), a pointer moving onto a button raised no `_HIGHLIGHT`, and `MON_SIMULATE _KB_TAB` did nothing. Known limit: this shows Swift matches Python, not that either matches the original, and it replays the harness's shortcuts too. It also led to "SOUND plays once" below.
- **SOUND plays once (2026-11-03, both ports).** `1028:09d3` clears the voice's loop flag (+0x1d) and only AMBIENT's `0f0a` sets it. The ports looped any sample with loop points, 46 samples, so `_pim_beep_6` in the opening kept six of the eight voice slots until the end of the game, repeating in the mix. Now only AMBIENT and a missile's travel sound (from the existing notes, not re-read) loop, and the mixers honour it. From the code; not compared live.
- **Space is a hull test, not a distance (2026-11-02, both ports).** The Space case of `FUN_10a8_0541` walks the figure's area list (+0x35, RoomType->triggers, in level order) and calls `1070:0aba` -> `1058:173c` on each IMAG: the hull touches the box, inclusive, height included. `FUN_1138_040c` is the held-item lookup (`FUN_1088_5669`), not a proximity search, and other figures are not in the list. The port's 2000-unit reach, nearest first, was wrong on all of that. Live at CRYO_BTN (box edge x -13939, hull 368 out), 0.5 s presses: gaps 1000, 420, 380 and 372 do nothing; 364, 340, 200 and -100 run CRYO_BTN_USE. Only that one box was pressed live; the rule for the rest comes from the code. Of the full run's 36 presses that ran a block, 7 stood too far, at 6 objects: CELPAN (twice), MONCL4, SEC_MON, CRYO_BTN, TWR_LV1 and DRA_BTN. The harness now walks closer. At TWR_LV1 and DRA_BTN it avoids a big turn, which carries Lex's hull off the box (about 2000 units for 150 degrees at DRA_BTN).
- Figure vtable (DGROUP 0x266d): +0x20 matrix `1070:0edc`, +0x2c move `10a0:22e1`, +0x58 SetPos `10a0:1ff0`,
  +0x5c collision/landing `10a0:0ead`, +0x78 `1088:3371`, +0x7c motion request `1098:0e49`, +0x9c fall start
  `1088:3196`, +0xa0 fall end `1088:31fb`.

## Monitors, PIMM and player keys (segs 10d0, 10a8 APLAYER)

Native stage 5b (`native/Sources/BioForgeCore/MonitorScreen.swift`, 2026-10-15): the
authored PIMM main screen is driven by the Swift VM's `MON_START`, `MON_HIDEALL`,
`MON_SETFRAME`, `MON_DEFINETEXT`, `MON_DEFINEBUTTON`, `MON_JUMP`, and `MON_STOP` calls.
P opens the script; mouse/trackpad movement and clicks use the 320×200 image rectangle;
Exit and Escape follow the script's stop labels. The initial PIMM main indexed frame and
palette match the Python monitor renderer's SHA-256 exactly. Scale bars, viewports, and
other PIMM pages are not yet complete in Swift.

Native stage 5c: `MON_DEFINELIST` reads keyed records from `MONITORS/TEXT.FLX`, and
`MON_MAKEINVENTORY` fills `INMT` from player-owned INVENTORY items. Initial highlight sends
`MONBAT_HIGHLIGHT`, which selects its description through `REMOVEENTRY "*+MONBAT"` and its
`MONITOR ART FRAME` table value. The booted inventory frame matches the Python renderer's
indexed SHA-256 (`67e19654…`); direct I/Exit and main/Inventory/Escape script routes pass.
Selectable list hit-testing assumes one line per entry, as in the authored inventory;
multi-line selectable lists still need row-to-entry mapping.

Inventory actions (`PIMM.scr:506–697`, recovered 2026-10-17): `IPUB`/`IPDB` scroll `INMT`;
each item `_HIGHLIGHT` label replaces `DEST` with its `DITEMS` description and refreshes
`IITA` from `MON_INVITEMFRAME`. `RDYB` and the art's `RDDB` button both execute
`MON_SETITEM(INMT); PLACEITEM CARRY` and then exit. The `PLACEITEM` handler is
`FUN_10d0_6171` (`re/out/statement_handlers.txt`); its `CARRY` branch in
`re/decomp/10d0.c:5547–5585` calls `FUN_1138_088d`. That routine chooses the item's
`HANDEDNESS` (default `LTHAND`), checks the hand is empty, and attaches it through
`FUN_1138_05a1`/`05ff` (`re/decomp/1138.c:528–596`). An occupied hand leaves the item
in inventory. The page has no Use, Combine, Unequip, or Drop button. `PLACEITEM INVENTORY`
keeps the player as holder and clears the hand; `PLACEITEM GROUND` clears the holder and
places the item in the world. Saved ITEM records encode holder at +22 and hand name at +24.

Player keys supply the other actions: I/P with a left-hand item calls `FUN_1138_1274` to stow
it before opening a PIMM page (`re/decomp/10a8.c:935–995`), Enter runs the pick-up / put-down
motion, and Space checks held items in both hands before nearby object `_USE` blocks, then
tries a held item's own `_USE` block (`10a8.c:1114–1192`). Item combinations are authored
as object-and-held-item scripts, such as `CELPAN_FORK_USE` in `CHAOSBLK.scr:305`; this
pries open the cell panel, while `CELPAN_USE` without the fork fails. Standalone item uses
include `MEDICAID_USE`, logbooks and batteries in `ITEMS.scr`. No general two-inventory-item
combination operation was found in the PIMM block or decoded item scripts.
Live check (2026-10-17, `re/tools/dosbox_live.py` with a scratch DOSBox-X copy): after
Lex stood up, the `MY_BATTERY` ITEM had holder pointer equal to Lex's figure pointer and
zero limb pointer; BLASTER and FORK had zero holder and limb pointers. Pressing I through
`OUTP 64 D2` / `OUTP 60 17` changed Lex's motion to `LOOK_AT_PIM`, confirming the page
opened. Enter, with and without a preceding Tab, returned Lex to STAND without changing
the battery's ITEM pointers. These keyboard attempts did not activate READY, so live
equip/unequip and item-combination outcomes remain unverified; their behavior above is
from the script and decompiled handlers.
The `inventory` fixture renders `MonitorScreen.render()` itself, with the pointer at
(160, 100): its battery, selected fork, and reopened-after-stow frames are compared
byte for byte with Swift. `world.render()` draws the room behind PIMM and must not be
used for these screen frames.

Native stage 5d: `MON_SETSCALE` activates S elements and clips each selected CAM frame
to its scripted percentage, matching the Python monitor renderer. `MON_DEFINELIST`
hydrates journal lists from ordered `ADDLOGENTRY` keys and their award ticks; text
expansion resolves `%time%` at each entry's award time. `MON_SCROLLLIST` handles entry,
line, and page directions. The booted PIMM diagnostics frame and a journal frame with a
PIM1 entry match the Python renderer's indexed SHA-256 (`f172bbd0…` and `a2d0a273…`).
The BRSB button dispatches its authored repair toggle; starting Lex is at full health,
so BIOREPAIR immediately resets `_bio_state` after a click. PDSB starts disabled and
correctly ignores pointer clicks. Charging behavior at later battery/PFD states still
needs gameplay verification.

Options settings (recovered 2026-10-16). INSTALL.OPT holds `Soundvol`, `Musicvol`, `Gamma` and
`subtitles`; the engine reads them at startup (1150.c ~810–845: volumes default 100; 10f0.c ~205:
`Gamma` default 30) and the dialog writes them back (`FUN_10f0_06b7`). The GOG file has
Gamma=50, Soundvol=100, Musicvol=100, subtitles=1.
- Audio panel (`FUN_1280_1cc5`, callback in `1280_callbacks.c`): sfx `[d712]` and music `[d714]`
  are 0–100 in steps of 10 (SFMX/SFPX, MSMX/MSPX); SFXX and MSCX toggle 0↔100; SBTX toggles
  subtitles (state > 2 = on). Every change applies at once through `FUN_1100_0dc2(sfx, music)`.
  AOKX persists them and sets subtitles (`FUN_1100_0e9e`); ACAX restores the values from when
  the panel opened (`[d70e]`/`[d710]`). OK and Cancel return to the main panel when the dialog was
  opened with `_OPTS_DEFAULT`, otherwise they close it.
- `FUN_1100_0dc2`: sfx < 1 disables effects (`FUN_1028_08f6`); otherwise `FUN_1028_1da5` rebuilds
  the master-volume table at mgr+0x12f as `table[i] = (i·v) >> 8`, v = sfx·255/100. This runs at
  startup too, so even sfx 100 scales every effect volume by 255/256. Music > 0 enables music and
  calls `FUN_1198_1b62(music)` → `XMI_set_relative_volume` (clamped to 127); music 0 stops it
  (`FUN_10f0_0953(0xfffc)`). AIL's relative volume is a percentage: CC 7 is sent as
  min(127, v·rel/100) (recovered from the AIL XMIDI layer, "AdLib music"), so level 100 leaves the songs unscaled.
- Gamma: `FUN_1100_0e6f(g)` sets offset = (g·32 − 960)/100 (C division; g 0 → −9, 30 → 0, 50 → 6,
  100 → 22) for R, G and B; `FUN_10e8_18c1`/`FUN_10e8_16bb` add it to every 6-bit palette channel
  on upload, clamped to 0–63. So the GOG default brightens every channel by 6 (24 in 8-bit
  terms), and screenshots of the original include that shift. The gamma panel (`FUN_1280_1ff1`):
  FRMA, GMPX/GMMX (±10 within 0–100), gauge GMAQ, AOKX persists, ACAX restores the saved value;
  each step applies at once. Shift/Alt with `,`/`.` or numpad −/+ step gamma by 10 and persist it
  (`10a8.c` ~1080–1215).
- Detail: the callback has no DETX branch (the string at 1290:a7f7 is referenced only by the
  main-panel builder `FUN_1280_176b`), so the DETAIL button does nothing. The `Detail` string in
  `FUN_1188_06d3` names the allocation for the mesh face-order lists of the `DETA` chunk (`LVL0`…`LVL7`, see Meshes); nothing in the dialog selects a level.

Item pick up and put down (recovered 2026-10-16; `re/interp/items.py` cites every function):
- Enter (0x1c, any modifiers, also in combat) → `FUN_1088_5729`. Hands via `FUN_1138_040c` →
  `FUN_1088_5669` (items on `[1cc5]` held by the figure with hand string `lthand`/`rthand`);
  `FUN_1138_0453` = the type's `HANDEDNESS` equals the hand (default `lthand`). Floor candidate
  `FUN_1138_0000(fig, 0x900, 60)`: unheld items on `[1d0d]`, 2D distance < 0x900 and bearing
  within 60° of the facing, nearest by 256-unit buckets (the first wins inside a bucket); hidden
  items are not skipped; a dead visible figure within 0x800 widens it to 0x1000/1000 (looting).
  The motion chosen (pick_up_/put_down_ lthand/rthand) follows the hand table in items.py; the
  target is stored at +0x199 for the two left-hand-empty pick-ups. `FUN_1098_0e49` runs a script
  block `<TYPE>_<MOTION>` instead when one exists (CHAOS/BEACH/PLATFORM gate `LEX_PUT_DOWN_*`
  with `LEGALTODROPHERE`).
- Motion event bytes (header u16 count at +28, list at +32), dispatched by `FUN_1088_13ea` (from the walk in `FUN_1088_1854`;
  `FUN_1088_35c2` handles the +0x141 copy): the sound cues are in "Motion sound cues and formatted sound names"; 0xef
  grab (vtable +0x90), 0xee/0xf3/0xf4 drop both/rthand/lthand (+0x94), 0xf0 (+0x98). MAN.MTN:
  PICK_UP_LTHAND 0xef after 16 frames, PICK_UP_RTHAND after 15, PUT_DOWN_LTHAND 0xf4 after 12,
  PUT_DOWN_RTHAND 0xf3 after 16.
- Grab `FUN_1088_5923`: the stored target if still free (else a new search), within 0x1000;
  `FUN_1138_088d` picks the hand, `FUN_1138_05ff` sets holder/hand and reads `ON_<HAND>`, then
  `<holder>_<item>_TAKE` runs (e.g. LEX_BLASTER_TAKE). Drop `FUN_1088_5b43` → `FUN_1138_099b`:
  clears the holder and collision flag 0x02, rotates by `ON_GROUND` (24.8 degrees, X·I then Z·K
  then Y·J), the item then falls; `<holder>_<item>_DROP` runs.
- Held item = child limb of the hand limb (`FUN_1088_5c19` → `FUN_1038_035b`): hand end + X/Y/Z
  along the parent axes + LENGTH along the rotated Y; offsets in cm × 20.48; I/J/K × 32/45
  (256 per turn), applied Z, X, Y (`FUN_1030_1054`). BLASTER.IFF and PIPE.IFF use an older mesh
  layout (`TRIS/VTRI` 8-byte faces + `UVXY`), now decoded by eor.py and EORMesh.swift.
- Timing: an event "after N frames" fires while frame N - 1 shows (the walk of FUN_1088_1854; see "Motion sound cues and formatted
  sound names", 2026-11-18). Port assumptions: the motion yaw offset in
  `FUN_1088_5ee1` is ignored; the player returns to STAND after these motions; a dropped item is
  placed on the floor without falling or bouncing; held LENGTH scale 1.0 (limb scale +0x17 not
  recovered). Saves write a picked-up item's holder and hand and a dropped item's position, except
  in a new game's level file, which has no PLAY record.

Options button text (recovered 2026-11-10). Each screen defines its buttons with `FUN_1258_0512(name, state, text, …)`
(main `FUN_1280_176b`, load `18cc`, save `1ad3`, audio `1cc5`, difficulty `20d5`, confirm `214c`). The text comes from the
`< KEY = "ENGLISH/FFRENCH/GGERMAN" >` defines in SCRIPT/PIMM.SCP, loaded by `FUN_1280_0212` (EXITSTR, OKSTR "SAVE SETTINGS",
GAMMACORRECTIONSTR "GAMMA", LEVELEASYSTR "EASY COMBAT", …). As with MON_* buttons, the text shows only in the label named with
the button's first three letters + 'L' (FUN_1250_1f81). OPTS.CAM has such labels for CRDX, GMAX, EZYX/MEDX/HRDX, AOKX/ACAX,
LOKX/LCAX/LNWX and YESX/NOOX only, so the main screen's top row is icons alone. GMAX is the bottom-left bar and CRDX the
bottom-right one. OPTS.CAM has no DETX element, so the Detail button `176b` defines is never shown. The confirm prompt
goes into QSTL (`FUN_1258_07cf`) and is the string at a41c + mode * 0x1e: 0 quit (EXTX, `_OPTS_EXIT`), 1 return, 2 load,
3 new (LNWX), 4 save to an empty slot, 5 save over. ASSUMPTION: the gamma panel (`FUN_1280_1ff1`, not decompiled) labels OK
and Cancel as the audio panel does. The port used to draw its own captions over the art; they are gone.

Options hover highlight (recovered 2026-11-18, decompile and disassembly; not checked live). OPTS.CAM's `xxxX` elements are buttons:
`FUN_1250_1ddc` makes class 'X' (0x58) with `FUN_1278_06f2(…, 1)`, the same button class as 'B' with the translucent flag (vtable
`1290:a23c`). The pointer's move handler `FUN_1250_1a21` sets `[9dca] |= 2` and runs `FUN_1250_19bc`: `FUN_1250_1889` finds the first
selectable button under the pointer (vtable +0x18 = `FUN_1260_06e2`: state not 0 or 5), `FUN_1250_158e` unhighlights the focus (+0x112),
and with a button found `FUN_1250_166b` unhighlights every selectable button, highlights the found one and makes it the focus. Highlight
is vtable +0x24 = `1278:0803` (disassembly: state 4 for a mode-1 button in state 3 or 4, else 2), unhighlight +0x28 = `1278:0844` (4 -> 3
for mode 1, 4 -> 1 otherwise, 2 -> 1, any other state -> 1 unless mode 1). Both set the state through +0x20 = `FUN_1278_0894`, which also
gives the label element the state. The state is the frame the button draws, so a hovered bar draws frame 2, a brighter blue (EZYX frame 1
is mostly palette 41, frame 2 is 47), and its label text takes colour px[1] (EZYL: 149, against 148 for state 1). Off every button
nothing is lit. Mode (+0x40) is `FUN_1258_0512`'s 7th argument: 1 for SFXX, MSCX and SBTX, 0 for every other options button.
`FUN_1258_0512` also runs `19bc` after defining any selectable button whose state is not 2, so a panel opens with the control under the
pointer lit. A state-2 default is defined as 1 once `[9dca] & 2` is set (the mouse has moved); otherwise it takes the focus and the
pointer jumps to its centre (pointer vtable `1290:a0b5` +0x1c = `FUN_1270_08ef`, which also puts the DOS mouse there, `FUN_1250_1a78`).
A key's glide (`FUN_1250_15ef`, pointer +0x18 = `FUN_1270_0536`) clears the bit. Monitors' `MON_DEFINEBUTTON` (`1258:08b4`) has no
`19bc` call. This is the dialog's whole hover; the difficulty screen, main panel, slots, audio, gamma and confirm screens all use it.
Both ports: `Options._highlight` / `highlight()`. Port simplifications: `[9dca]` is kept per dialog (the original's is global, so a
mouse move on an in-game monitor also counts), and the port redraws the audio and gamma panels for a step, so a redraw leaves the
default normal instead of keeping its state.

Options keys and the save guard (recovered 2026-10-16):
- Player key handler `FUN_10a8_0541`: R (0x13) → `_OPTS_CREDITS`, O (0x18) → `_OPTS_DEFAULT`,
  S (0x1f, not with Alt) → `_OPTS_SAVE`, each through `FUN_10a8_051d` → `FUN_10a8_02cc`, the
  function MON_CODE uses. Global hook `FUN_1128_0f7f`: L (0x26) → `_OPTS_LOAD` when a game runs,
  no save/load is busy (`FUN_1140_0fc0`), the player is absent or alive and no monitor is up
  (Alt overrides); Alt+X (0x2d) → `_OPTS_EXIT`. Enter (0x1c) is pick up / put down
  (`FUN_1088_5729`: motions `pick_up_rthand`/`lthand`, `put_down_rthand`/`lthand`).
- `FUN_10a8_02cc` refuses when `FUN_1128_0858` says saving is unsafe or `_forcing_reload` is set:
  S fires the block named at `[2a6a]` = `CANNOT_SAVE` (COMMON.scr, "PIMM: Save temporarily
  disabled") with the player as object and opens nothing; O fires it too and opens the main panel
  with flag 0x800 (SAVX state 5, disabled). Unsafe = a `CAPTUREKEYBOARD` grab is held (`[6530]`,
  set by the CAPTUREKEYBOARD handler 10d0:1823), or a figure that is not hidden (+0x34 bit 0x04
  with +0xf6 clear, `ISHIDDEN`) is invulnerable (bit 0x08, `INVULNERABLE`) with hit points > 0,
  or a GRENADE exists. The opening refusal seen in DOSBox-X is the `GOODMORNINGLEX` grab
  (EL_SCENE.scr, `CAPTUREKEYBOARD GETESCKEY`, ticks 98–685 of a new game). With the keyboard
  captured, the player handler answers only S, with CANNOT_SAVE.
- Ported to both ports; not modelled: running the capture block or routing keys to it, the
  engine's hide method (no script statement sets "hidden"), the `[4e3d]`/`[a36a]` dialog states
  and `FUN_1100_0f02`.
- Alt+V (0x2f, recovered 2026-10-17): case 0x2f calls `FUN_10b0_0e12` with the format string
  `"%s  %s~%s"` (1290:2c35) and three static near strings at 1290:4faa/4fb3/4fbd — "BioForge",
  "ver f1.01", "(C) 1994, 1995 Origin Systems" — guarded on `[50d6]`/`[50d8]` both zero (no
  caption process already showing; `FUN_10b0_0f48` is the same guard pattern the generic caption
  task uses, and `FUN_10b0_0feb`/`103f` clear both on close). `FUN_10b0_0e5a` builds a bare
  caption task (class 0x2d7b/0x2da7), not a SUBTITLE/MINORSUBTITLE sound object, and plays no
  sound. The same word triple is logged at startup with `"%s, %s, %s\r\n"` (1290:690e,
  `FUN_1150_02bd`) — a version line in a startup log the port doesn't write.
  Ported as a MINORSUBTITLE with no sound (`World.show_version`/`showVersion()`): the existing
  `subtitle()` `minor and live -> return 0` guard already matches `[50d6]`/`[50d8]`.
  ASSUMPTION: default colour 0x75, since `FUN_10b0_0e5a` sets none explicitly.

Native stage 5g: save formats, writer and resume are ported to Swift (see STATUS). The class-name
strings `savegame.class_names` reads from `re/dgroup.bin` lie in the user's BIOFORGE.EXE at file
offset `0xFD800 + pointer` (shipped 1,123,344-byte exe; `StdIntHandler` at pointer `0x9a98`), so
the port reads them from the game folder; they only label slots and are optional.

Native stage 5f: `Options.swift` ports the `options.py` dialog; ten screen states match the
Python frames. Its credits parity exposed a list-text offset in Swift `MonitorScreen.drawList`:
`monitor.py` places each row's baseline at `y + Font.baseline` (largest glyph baseline, 8 for
font 1), not `y + font height` (7). Swift now uses the baseline; existing PIMM hashes are unchanged.

Native stage 5e: `MON_DEFINEVIEWPORT` activates a V element and requests the named
camera through a scene-only render, leaving the selected game camera and events alone.
The full 320×200 source view is stretched to the authored rectangle by nearest-neighbour
sampling, converted from its own palette to Rec.601 brightness, then mapped to the
monitor's final grey run (last 32 indices). V pixels draw under art, buttons, text, and
pointer. A cached INITGAME camera index supplies CAMR geometry for remote views such as
CTR4 in CONTROL while CHAOS is active; the active level's camera record takes precedence.
CELL/CE11 and MLBT/CTR4 indexed frames match the Python prototype (`ca3d8703…` since floor items are drawn, earlier `217534e8…`; and
`3a2b8768…`). The original viewport resampling and conversion formula remain unrecovered;
this is parity with the prototype and its screenshot-supported approximation.

Monitor files `MONITORS/<NAME>.CAM`: entry 0 = palette (768 bytes); named entries =
background (e.g. `MLBT`), buttons (`xxxB`, several frames per state), lights (`xxxL`),
viewports (`CAMV`). `MON_START "mlbt"` opens one. Element states (DEFINES.DEF):
`_MON_INVISIBLE 1, _MON_NORMAL 2, _MON_HIGHLIGHT 3, _MON_SELECTED 4`. Button text uses
`/F` and `/G` language segments; `"/!"` is used for buttons without text.

Engine (`re/interp/monitor.py`, wired in `world.py`; recovered from 10d0, 1250, 1258, 1260):
- An element's screen position is (−hotx, −hoty) of its frames; frame 0 is a 1×1 dummy. The
  background is the entry named like the file.
- Element class = 4th character of the entry name (`FUN_1250_1ddc`): B button, L text label
  (frame = geometry only), T text list/area, S scale bar, V viewport, else art (frame via
  MON_SETFRAME).
- Internal state = script value − 1 (default normal): 0 invisible, 1 normal, 2 highlight,
  3 selected, 4 selected+highlight, 5 not selectable. A button draws frame
  `min(state, nframes−1)`. Invisible buttons stay clickable; MON_HIDEALL deactivates all.
- Button text goes into the label `xxxL` with the same first 3 letters (`FUN_1250_1f81`).
  The label image's first pixels hold its style (`FUN_1260_0891`): px[0..4] = text colours for
  states 1..5, px[5] = font number. Text is centred in the label (`FUN_1260_0a0a`).
- Text args `ENGLISH/FFRENCH/GGERMAN` (`FUN_1120_03d2`): use `/<lang>`, else `/E`, else the
  whole string; a leading `/x` marker is dropped, and text stops at the next `/`.
  (2026-11-18) `<lang>` is the `language=` character of INSTALL.OPT, read once at start-up (1150.c ~369, `[50c6]`); the strings
  are `/!` (1290:61c2), `/E` (61c5) and the cut `/` (61c8). The same filter runs on SUBTITLE / MINORSUBTITLE text (10e8.c:307,
  :404, before the line split), CAPTION (10b0:0e5a) and MON_DEFINETEXT/BUTTON (10d0:55eb). So the English intro line "...supply
  requisition B-9/3Q..." shows as "...B-9" in the original too. Text bytes are CP437 (ü 0x81, ä 0x84, ö 0x94, ß 0xE1), which
  index the fonts directly (1.FNT has 226 glyphs). `text=` picks MONITORS/TEXT.FLX, GTEXT.FLX or FTEXT.FLX; voices are
  SOUND/<lang>SAMPLES.FLX (717 samples each); INTRO.SCP picks INTRO / INTROF / INTROG by GETOPTDATA "LANGUAGE". Both ports
  follow Game > Language (`Settings.language`).
- MON_DEFINELIST / MON_DEFINETEXTAREA name TEXT.FLX entries (INVENTOR, DITEMS, ...). Lists hold
  `[KEY] text` lines; ADDENTRY / REMOVEENTRY (1258:0b50 / 0bc5) edit them by key, and
  `REMOVEENTRY x "*+KEY"` replaces the whole list.
- **Unkeyed list entries (recovered 2026-11-18).** MON_DEFINELIST (`10d0:54e6`) passes `"[" + record` to `FUN_1258_08b4`, whose element
  method `FUN_1270_0ffa` replaces the element's text object; a leading `[` builds the list class (`FUN_1268_005f`, vtable DGROUP `9f62`;
  `+0x44` update `1268:04a8`, `+0x58` AddEntry `1268:0c9c`, `+0x5c` RemoveEntry `1268:0e30`; Ghidra has no function at `0c9c`, see
  `DecompileAt.java`). Nothing is listed when it is defined. Its first update (`+0xc65 == 0`) rewinds the record and runs `FUN_1268_10c5`:
  at each `[` it peeks the next byte, and on `]` (an empty key) it adds the entry (`FUN_1268_0f73`, the text up to the next `[`); keyed
  records are skipped (`FUN_1268_0bc3`). Then `FUN_1268_1213` adds the ADDLOGENTRY store's keys in award order with their stamps, and
  later updates add keys awarded since. So a list shows its `[]` entries, then its earned keys. caynan (43), dane (19), eshmes (34),
  lock and lock2 (1 each), cell1-4 (prisoner information, CHAOSMON), freezer1-4 (cryo chambers) and reacto are all `[]`; CMAINT is 64 `[]` then
  the keyed C1REP-C4REP, which no script awards to CMAINT; lex, GMAINT, INVENTOR, DITEMS, ornotes, orresult and ORSEC have none. Both
  ports listed only earned and ADDENTRY keys, so Caynan's, Dane's and Escher's logs, the airlock notes and those CHAOS monitors were empty
  (playtest report; the route read Dane's code from the record, not the list). Both ports now put the `[]` entries first when the list is
  defined (`Monitor.set_list_entries`, `MonitorScreen.defineList`). ASSUMPTION: an ADDENTRY in the same script run as MON_DEFINELIST
  (before the first update) comes first in the original but after them in the ports; only XLOG case 1 does that, on `lex`, which has no
  `[]` entries. NOT MODELLED: AddEntry (`1268:0c9c`) adds every record with the key (case-insensitive), not only the first; no script's
  key repeats in its record. With no match it appends a placeholder entry (text from `FUN_1000_586c`, arguments not recovered); the
  ports add nothing. Only `ADDENTRY "TEXT" "LOGBOOK"` (XLOG 1, LEXLOG_USE) hits this, as `lex` has no LOGBOOK record; no script creates
  LEXLOG and no INITGAME file holds it, so a player does not reach it.
- Inventory = items owned by the player and not in a hand (`FUN_10d0_0000`). Icons are
  PIMM.CAM entry `IITA` frames 1–16. MON_INVITEMFRAME returns the item's
  `< MONITOR ART FRAME = n >` from ITEMS.scr.
- Monitor pointer: per-form hand CAMs (`MON_SETPTR "pcayhand"`; LEXHAND/HARDHAND/REFHAND.CAM have frames
  1–3 = press animation, PCAYHAND/PLEXHAND.CAM only frame 1, so they press at once; default POINTER.CAM `HAND`; `ptr_*` options in seg 1270).
- **Pointer hotspot and margins (recovered 2026-11-11).** The pointer object (`FUN_1270_0000`) reads the globals `_ptr_x_hot`,
  `_ptr_y_hot`, `_ptr_left/right/top/bottom_margin` and `_ptr_press/hold/release_time` (`FUN_1100_0d4c`); VARS.DEF sets them to
  122, 13, 0, 319, 14, 199 and 14, 5, 14, and no script changes them. `FUN_1270_0151` clamps the position to the margins ("hand ptrs
  do not reach to top of screen"). A hand frame sits at its CAM hotspot in a 320x200 canvas (HAND frame 1 at 109,11, its fingertip
  at canvas 119,11), so the canvas point (122, 13) is the pointer position. Both ports drew the frame's hotspot at the pointer until
  then, which put the hand about 110 px right of the mouse. INFERRED: the pointer's drawing subtracts (x_hot, y_hot); the draw call
  itself is not traced.
- **Pointer press animation (recovered 2026-11-11, `re/decomp/1270.c`).** Pointer object fields: frame +10 (starts 1), count +0x2e (frames
  of the pointer CAM entry minus 1; HAND, LEXHAND ... have frames 0..3, so 3), state +0x30 (0 idle, 1 pressing, 2 holding, 0xff
  releasing), start time +0x43/+0x45, interval +0x3f, releasePending +0x49, pressPending +0x47 (set by a press during an animation,
  never read: the press is dropped). `FUN_1270_01ae` starts a phase: start = the 60 Hz clock `[8334]`, interval = `(time + (count + 1) / 2) /
  (count + 1)` for the `_ptr_press/hold/release_time` 14 / 5 / 14 (VARS.DEF; `SET_PTR_PRESS_TIME`), i.e. 4, 1 and 4 clock units for the hand.
  `FUN_1270_01ec` (mouse down): frame > 0 and state 0: at the last frame it presses at once (`FUN_1250_185d` -> `12f6`), else frame = 1, state 1,
  press phase; state != 0 sets pressPending only. `FUN_1270_0263` (mouse up): frame > 0: idle -> release action (`FUN_1250_13f1`), state -1,
  release phase; else releasePending. `FUN_1270_0463` (move): the position changes only in state 0 (`FUN_1270_0151` clamps). `FUN_1270_02ef` (once
  per tick; `02c9` starts the hold phase): state 1: at the last frame press (`12f6`, skipped while the pointer glides, DAT_9fea) and hold, else
  every interval step +1; state 2: after its interval go idle and, with releasePending, release and step -1; state -1: at frame 1 go idle, else
  every interval step -1; the blocks fall through within one call. The pointer draws frame `frame` at the position minus (x_hot, y_hot).
  A click at 2 clock units per tick therefore shows frames 1,2,2,3,3,2,2,1,1 on ticks 1..9, presses on tick 5 and (mouse up before then)
  releases on tick 6; a held mouse stays on frame 3 (state 0) until the release. Both ports: `Monitor.update()` / `MonitorScreen.update()` once
  per tick from the world step (also while the options dialog pauses the game), `mouse_down` / `mouse_up` / `set_pointer_pos`; the options
  dialog runs its own machine with its own press and release actions (the control under the pointer is remembered and activated only if the
  pointer is still over it). ASSUMPTION: neither port has a never-paused 60 Hz clock (the show clock only runs while a flic plays and
  stops with the world), so each pointer keeps its own count, +2 per `update()`; INFERRED equal to `[8334]` for its use. NOT MODELLED: pointer
  glides (`MON_SIMULATE`, `DAT_9fea`; the keyboard drives the pointer by name instead). ASSUMPTION: a pointer with
  fewer than two frames presses and releases at once. The named test driver (`press` / `release` by name, `Options.activate`) stays immediate.
- **Monitor input switch (recovered 2026-11-11).** `FUN_1250_0415(monitor, on)` is MON_ENABLEINPUT's switch (handler `10d0:584e`,
  `re/out/statement_handlers.txt`, passes its number): it stores `on` at monitor +0x120 and, when `on` and `[9dca] & 1` (a mouse is in use;
  `[9dca]` starts as `[7bbc]`, mouse present), calls `FUN_11d8_0e91(pointer x, y)` = `MOV AX,4 / CX = 2x / DX = y / INT 33h` (bytes at
  11d8:0e91), i.e. the DOS mouse is put on the pointer. The monitor's event handler `FUN_1250_0cf9` first runs `FUN_1250_0c4c`, which
  hands a mouse up (event 2) to the pointer (`FUN_1270_0263`); everything else (mouse down 1, move 4 -> `FUN_1250_1a21`, keys) is handled
  only while +0x120 != 0. The pointer clears it when a press animation starts (`01ec`) and sets it on the release (`0263`, before
  `FUN_1250_13f1`). So from the press to the release the pointer cannot move (also on frame 3 with the mouse held) and keys are dropped;
  CHAOSMON.scr's palm reader uses `MON_ENABLEINPUT 0` to "PROHIBIT PTR MOVEMENT", and there a mouse up still releases the idle pointer and
  turns input back on. The options dialog (`FUN_1280_0168`, built on the monitor class `FUN_1250_0000`) is stored in the same `[9d76]`, so
  the switch applies to it. Both ports: `Monitor.set_input` / `MonitorScreen.setInput`, `mouse_warp` / `mouseWarp` (the app moves the Mac
  mouse; `play.py` does not). INFERRED: event 4 is the mouse move (it carries x, y at +9 / +0xb and goes to the pointer's move method).
  MOUSE.SHP is a separate editor-mode cursor (see "Mouse cursor"). The generic image initializer starts multi-frame
  pointers on frame 1; frame 0 is transparent. The prototype draws the default or selected
  CAM frame above monitor content at its hotspot, with masking and clipping. Pointer indices
  use the active monitor palette; original palette remapping has not been established.
- SDL preview mouse motion and left-clicks are scaled from 640×400 to monitor 320×200 coordinates;
  active buttons use authored CAM frame bounds for hover, press and release. An active invisible
  button remains clickable; MON_HIDEALL deactivates it. The release targets the button pressed
  even after the pointer moves away. If down and up arrive before a MON_JUMP poll, the preview
  preserves BUTTON before RELEASED so a quick click still activates the control.
- Monitor text rendering substitutes `%%` with `%` and `%variable%` with the current VM global
  value; missing globals follow the VM's zero default. This includes labels and TEXT.FLX lists/
  textareas (e.g. `REACTO`'s `%_reactor_id_number%`). `FUN_1260_0274` formats `%time%` as
  `day-HHMM` (`%d-%02lu%02lu` in `strings.tsv`). The prototype converts its 30 Hz VM tick to
  two 60 Hz engine ticks and defaults `StartTick`/`StartDate` to zero; the clock conversion is
  inferred, and config parsing is still absent. Journal rows retain the tick at which their
  `ADDLOGENTRY` was awarded rather than using the current display time.
- `ADDLOGENTRY`/`REMOVELOGENTRY` maintain ordered per-log keys. Duplicate awards do not append;
  PIMM_JOURNAL fills JORT from the awarded LEX TEXT.FLX records, and the maintenance logs use
  the `*KEY` expansion. The recovered `FUN_10d0_02a1` path emits `<log>_LOG_ADDED` on a changed
  list; `FUN_1258_0f38` passes the clock to `FUN_1278_134b` for stored entries.
- `MON_DEFINEVIEWPORT` draws a camera feed in a V element. ROBOCNTL's CTR4 resolves to
  CONTROL.IFF while CHAOS is active; drawing the feed does not fire camera events. The native
  screenshot comparison below replaced the earlier upper-left crop and nearest-colour preview
  with a full-frame stretch into the V rectangle and a monitor grey-ramp conversion.
- The V element vtable at `1290:a18c` maps its camera setter (+0x18) to no-op
  `FUN_1270_1379`. `FUN_1258_0dab` passes the camera argument through that slot and activates
  the element with +0x10 (`FUN_1270_1330`). Its +0x14 geometry callback (`FUN_1278_0a9a`)
  takes the rectangle from the authored CAM frame. This confirms element bounds, but does not
  reveal the native feed crop or palette path. `FUN_1270_1330` marks the element rectangle
  dirty through `FUN_1100_0bf2` and switches its display state through `FUN_1278_0b7d`;
  the dirty routine only records bounds. The generic image drawer `FUN_1278_0bb7` blits an
  authored frame. The main room draw path `FUN_1100_0580` → `FUN_1110_051f` has not exposed
  a V-specific camera compositor. The script camera name is therefore unused on this recovered
  V path. The native screenshot comparison below establishes the visible feed behavior even
  though the compositor's code path remains unlocated.
  **Observed in the original (2026-10-15, DOSBox-X, crafted save at C1MONLOC, CHAOS cell
  monitor 1, `re/out/native_shots/cellmon_cell1_cam1.png`):** the viewport shows a live render
  of the selected camera (CE11, with the prisoner figure), not a window onto the main view.
  Geometry: the whole 320×200 camera view is stretched non-uniformly to the V rectangle
  (CELL VEWV 240×172 at (38,13); best fit 240–244×172, ±2 px). A same-position crop fits much
  worse (correlation 0.55–0.59 vs 0.80–0.83 when scaled). Palette: the view is greyscale. 92%
  of its pixels are exact greys, with about 33 distinct colours, matching the monitor palette's
  grey ramp (CELL.CAM palette entries 128–159). So room pixels are mapped by brightness onto
  the monitor's 32-step grey ramp. The scripts also issue `CAMERA <cam>` (the main camera
  follows), and the V camera setter is a no-op, so the feed takes its camera from the
  current/main camera. The rendering path is still unlocated in the code.
  Implemented (`monitor.py`): full camera view, nearest-neighbour stretch to the V rectangle,
  Rec.601 luma mapped linearly onto the palette's grey ramp (`grey_ramp`: the last run of at
  least 16 grey entries, at most 32). The sampling and luma-to-ramp mapping are fitted choices,
  not recovered: the original's exact sampling and colour formula remain open; V elements are drawn first and buttons/labels on top.
  Correlation with the native shot is 0.85 over the rectangle and 0.91 without text and button
  rows; the missing prisoner is because the prototype's CHAOS state is fresh.
  Also found: a CAM file can contain two entries named like the file (CELL.CAM: background +
  a later CELL label), and the background is the first one. A label style font byte ≥ 0x80
  (0x81..0x83 seen) renders as font 0 natively; the low bits may be an alignment flag.
- `MON_CODE` opens the separate options dialog recovered in `decomp/1280.c` using OPTS.CAM art:
  main panel `FUN_1280_176b`, difficulty `20d5`, audio `1cc5`, credits `221e`, confirmation
  `214c`. Difficulty selection sets `_difficulty_level`; audio controls and credits display in
  the preview. `FUN_10a8_02cc` calls the dialog constructor and returns; `START.scr` then
  explicitly polls `ISMONITORRUNNING` before creating Lex. `PIMM.scr` continues immediately
  after `MON_CODE`; the pause behavior is resolved below. The load/save screens use
  nine slot controls (`SE1X`–`SE9X`) from
  `FUN_1280_18cc` and `FUN_1280_1ad3`. `FUN_1288_025e`/`029e` vary the digit in `game1.im1`
  from 1 to 9; `FUN_1288_095f` supplies the selected file to the load path.
  The dialog completion branch with `a368 == 4` calls `FUN_1128_0901`; its decompiled body
  resets game state, reloads the starting level, and starts Lex, so it is a new-game path.
  The previously missing dialog vtable callback at `1280:09ac` is recovered in
  `decomp/1280_callbacks.c`: save `LOKX` opens confirmation (mode 4 or 5 for empty/occupied
  slot), `YESX` drives a save selector event, and the `a368 == 2` branch calls
  `FUN_1148_0076` with the selected slot path. This confirms the archive writer is on the
  save action path.
  `FUN_1148_1a76` writes level resources. The save container and process state were subsequently
  decoded and validated against a native save sample (see "Save state" above). The preview
  wires slot confirmation to native-format persistence, with its own script-process limitation
  noted above; the audio, gamma and detail behavior is recovered (see "Options settings" below). `MON_DESTROYOPTIONS` closes the dialog;
  `MON_SIMULATE _KB_TAB` moves focus to an active button. Native button callbacks and focus
  order remain partially inferred. The preview freezes VM/world time during options.
  **Resolved (2026-10-15): the options dialog pauses the simulation.** `FUN_10a8_02cc(flags)`
  (MON_CODE passes its argument, `10d0:4574`; flags = DEFINES `_OPTS_*`) opens the dialog after
  `FUN_10b0_136b(0)` and sets `[50be] = [50bf] = 1`, unless the game is already paused (`[50be]`) or `flags & _OPTS_CREDITS`
  with no forced reload (`FUN_1100_06d4` is true when `_forcing_reload` is 0; CORRECTED 2026-11-16, this said the reverse; see "The credits roll").
  `FUN_10b0_136b(0)` increments the pause count `[2e17]`; on the first pause it suspends every
  kernel task of type 0x102/0x10e/0x10f (`FUN_1238_181f` → `FUN_1230_2ab5`) and sets the
  running flag `[2e16] = ([2e17] == 0)`. `FUN_10b0_1281(0)` reverses it (`FUN_1238_1807`).
  The frame loop (`FUN_1150`, around 1150.c:950) then skips camera selection
  (`FUN_1130_0fa3`), the world update (`FUN_1110_08bf`) and the game clock while `[50be]`, and
  the script scheduler (`FUN_1230_0259`) while `!([2e16] && ![50bf])`. Subtitles are hidden
  (`FUN_1100_1538` condition). The dialog UI (`FUN_11b0_077d`) keeps running. Closing
  (`FUN_1100_0716`) clears both flags and resumes. START.scr's `WAITHERE` loop is therefore
  frozen while the difficulty dialog is open and continues when it closes. `[a36a]` = flags of
  the open dialog (set by its constructor, 1280.c:30).
  Further static save research: `FUN_1148_0076` reaches `FUN_1140_134f`, whose strings
  include `*.*` and `%s %s savegame %s`. The latter configures a `FUN_11f8_*` archive object;
  `FUN_11f8_09ee` enumerates and packages directory entries, while `FUN_11f8_0f03` iterates
  and extracts archive members. `FUN_11f8_14cd` writes a 0x80-byte header with an `0xA1A1`
  marker, as confirmed by the native save analysis above. Before packaging,
  `FUN_1148_0076` writes `misc.dat` and calls `FUN_1148_1523`, which writes the current
  level via `FUN_1148_1404` (`OBJS` and `DROW` object writers through vtable +0x34), then
  writes `script.dat`. The records are described in the "Save state" section above.
  Assumed: repeat delay 10 ticks, toggle/plain button behaviour, scale-bar clipping.

`MON_JUMP` (10d0:5896) turns pending UI events into a jump to a label in the running script
(`FUN_10c0_31ad`): `<name>_HIGHLIGHT` (two highlight sources, `9db6` and `9da2`), then
`<name>_RELEASED`, then for a held button the first `<name>_BUTTON` and later
`<name>_REPEAT` after `_REPEAT_DELAY`. With no monitor running it ends the process
(result 2); with no event it continues, and scripts follow it with `SUSPEND` / `JUMP LOOP`.
Example: ROBOCNTL.scr `:RTDB_BUTTON`.

Player keyboard handler `FUN_10a8_0541` (event: +3 PC scan code, +5 modifier flags: 0x0c =
Shift (also synthesised from 0x2a/0x36 presses), 0x30 and 0xc0 = probably Ctrl and Alt (Alt+V
shows the version, the classic Origin key)). Motions are started through the figure vtable
+0x80 as (name, 1, scan code, required modifier mask, flags 0xf0/0xfc/0x0c); they last while
the key is held. Normal mode (figure flag 0x40 clear):

| Key (scan) | Plain | Shift |
|---|---|---|
| ↑ 0x48, Home 0x47, PgUp 0x49 | `walk` | `run` |
| ← 0x4b / → 0x4d | `turn_left` / `turn_right` | `turn_left_fast` / `turn_right_fast` |
| ↓ 0x50 | `walk_back` | |
| End 0x4f / PgDn 0x51 | `sidestep_left` / `sidestep_right` | |
| numpad 5 0x4c | `shoot` (vtable +0x7c, one-shot) | |

Combat mode (flag 0x40 set): the numpad keys 7 8 9 4 6 1 2 3 start `atk_M7 M8 M9 M4 M6 M1 M2 M3`
(plain; Shift+↑ still runs; M4/M6 only if no other attack/run is playing), `atk_F*` with
modifier 0x30, `atk_H*` with 0xc0; numpad 5 = `atk_shoot`.
Other keys: `C` 0x2e toggles combat (`%s_ENTER_COMBAT` / `%s_LEAVE_COMBAT`, `FUN_1090_077b` /
`0800`), then always calls `FUN_1098_0745` (10a8:1065), the idle of the new mode: `stand` or `atk_stand`. LEX_LEAVE_COMBAT only
restores the hand textures, so that call is what lowers Lex's fists (2026-11-18: the ports skipped it and Lex stayed in `atk_stand`);
LEX_ENTER_COMBAT's `MOTION ENTER_COMBAT` follows it; Space 0x39 = use: tests the figure's hull against its area's IMAGs ("Space is a hull test") and calls the script block
`%s_%s_USE` (held item + object) or `%s_USE` (e.g. `CTYMON_USE`); `S` 0x1f = save (or the
`CANNOT_SAVE` block while the player is not in control); `R` 0x13 = command 0x10 (probably
restore); Enter 0x1c → `FUN_1088_5729`; `,`/`.` 0x33/0x34 and numpad −/+ 0x4a/0x4e with Shift
or 0xc0 = gamma −/+10; Alt+V 0x2f = version message. PIMM screens are script blocks that the
engine calls by name (`FUN_1120_0000`): scan 0x17 `I` → `PIMM_Inventory`, 0x19 `P` → `PIMM`,
0x20 `D` → `PIMM_Diagnostics`, 0x24 `J` → `PIMM_Journal` (ignored with modifiers). So the
inventory UI is script-driven through the MON_* statements.

## Parity harness (2026-10-16)

`re/tools/parity.py run <scenario>` boots DOSBox-X from a copy under
`re/out/parity/<scenario>/workdir`, starts the Python `scenarios.boot_opening()` path,
and records both at the original's 60 Hz game clock. The clock is the little-endian
u32 at DGROUP `0x8330` (`decomp/11d8.c` increments its low word, with carry into
`0x8332`); one Python VM tick advances two clock ticks. Key presses and PHYS
state changes are scheduled in clock ticks relative to the scenario's event anchor.
An opening motion or Lex's first collision-enabled frame after OUT_OF_BED can be
the anchor, allowing the two boot timelines to differ without wall-clock key timing.
The trace keeps raw clock values. The report aligns by anchor-relative clock,
compares requested fields using each scenario's tolerances, and plots positions.
Original figure fields that occupy one record, including position, flags, hull and
locals, are captured in one 0x240-byte dump. Model orientation and InTrig still
require separate dumps and may be a frame later; reported first divergences in
those fields should be checked against neighbouring samples.

Scenario definitions are `re/tools/parity_scenarios/*.json`, generated traces
and reports are in `re/out/parity/`, and `parity.py report <scenario>` can rerun
the comparison without DOSBox-X. The harness does not alter the Python engine.
Besides `new_game`, a scenario may name a native `.IM1` save, its slot and the
original's load-dialog key sequence; the runner copies that save only into the
scratch workdir and unpacks it for `World.from_native_state` on the port side.
The `opening_wake`, `closed_door_walk`, and `open_door_zap` scenarios target the
live observations in "Figure grounding", "Motion timing and turning motions", and
"IMAG triggers" above. On 2026-10-17 all three were captured end to end. The
reports deliberately exit nonzero because other sampled fields exceed tolerance:

| Scenario | Original endpoint | Port endpoint | Observed difference |
|---|---|---|---|
| opening_wake | Lex y −8895; FIRSTBOT (−11361, −10489) | Lex y −9610; FIRSTBOT (−11615, −11135) | Nurse path/motion and Lex push timing differ; original nurse is at the recorded (−11360, −10489) point. Fixed 2026-10-17, see below. |
| closed_door_walk | Lex y −14100 | Lex y −14099 | Door stop is within 1 unit; earlier camera, locals, x and motion samples still differ. |
| open_door_zap | Lex y −13167 | Lex y −13297 | Both set InTrig 43 (DR_ZAP3) and play SHOCK_BACK; final y differs by 130 units. The current run ends 34 units from each previously recorded endpoint (−13201 original, −13263 port). |

The first wake run attached Lex's early CHAOS `WAKE_UP` to the later live wake; the
scenario now requires `WAKE_UP_HEAD` before anchoring on `WAKE_UP`. During the
new-game transition one debugger read returned a transient out-of-range clock, so
the runner discards it. Per-frame samples refresh the requested figure pointers
at the anchor, avoiding old TITLE/CHAOS pointers. The open-door run also showed
why key scheduling must occur between samples: sampling every record in a tight
loop delayed key release and changed the outcome. The final traces use clock
polling between bounded samples, and the report records the actual sampled
clocks so residual scheduling gaps remain visible.

`nurse_activation` (2026-10-17) anchors on FIRSTBOT's ACTIVATE (`"after_motion": null` lifts the
default requirement of an earlier motion; live the nurse's motion name is empty before ACTIVATE,
the port's DEACTIVATED) and samples every 6 clock ticks for 900. It found the nurse's ATK_M7
frames 9% slower in the port, which led to the difficulty adjustment in "Motion timing". After
the fix the nurse ends the window 35 units from the original ((−11785, −10816) against
(−11791, −10781)), and the port's Lex stands at (−10292, −9610) against the original's (−10283,
−9610) in the same run. The original itself varies here: in other runs the bed did not block the
y half of the push and Lex stood near (−10270, −8879), so `opening_wake`'s Lex y stays a
run-dependent reference. The live sampler reaches about one sample per 16 clock ticks, whatever
`sample_period` asks for.

## Mouse cursor (`MOUSE.SHP`)

Decoder `re/formats/mouse.py` (native `MouseShapes.swift`): the FNT layout (see "Fonts"). Header u16 0 = 11 and
u16 2 = 14 are the width and height of the background box the engine saves under the cursor (live: 11×14).
Loaded at start-up by `FUN_1150_099e` from the `MousePtr` option of the `Mouse` section (RED.OPT
`mouseptr=mouse.shp`) through `FUN_1058_053a` → `FUN_1058_01d6`; the mouse is then centred (`FUN_1058_066d(0xa0, 100)`).

Seg 1058 (no source-file string) keeps a priority stack of u16 `priority << 8 | shape` at DGROUP 0x1e91 (depth
0x1eb9, at most 19): base 0x7f00 = arrow. `FUN_1058_05d7(v)` pushes when the priority is not lower than the top
and returns the depth; `FUN_1058_05f8(depth | -1)` pops. Pushes: 0x702 hourglass around busy work in LIVING.C (1088),
RESCACHE.C (1110), 1128 and 1130, saves and loads (GAMEDATA.C, seg 1148, every caller), FLIC streaming (1140) and
the start-up game load (1150); 0x701 marker around garbage collection (`FUN_1150_0000`). Shapes 3..7 are never selected. Current
shape 0x1ebb, its far pointer 0x1e89, drawn top-left 0x1e74/0x1e76, saved size 0x1e78/0x1e7a, hide flag byte 0x7630,
mouse position 0x7baf/0x7bb1 (set by the mouse callback `FUN_11d8_116b`, x halved).

Per presented frame (`FUN_10e8_1dcc`): `FUN_1058_04ef` saves the box under the cursor and draws the shape at
(mouse − hotspot), clamped to 320×200, `FUN_10f0_0f93/101d` flips, `FUN_1058_04f4` restores the box. Colours are
copied unchanged into whatever palette is active. `FUN_1058_0616` hides (byte 0x7630 = 1, set at start-up and
around FLIC playback), `FUN_1058_063b` shows, but only when byte 0x50b9 is 0; `FUN_1058_05d7` also refuses
pushes while it is set. 0x50b9 defaults to 1 and only the `-e` command-line switch clears it (`FUN_1150_03cd`;
`-e` also sets 0x68ea like `-d`, and 0x50b9 = 0 enables editor-only prompts such as `FUN_1148_0cf7`). So
normal play never shows the cursor; it belongs to the developer / editor mode.

Live check (2026-10-16, DOSBox-X): plain `BIOFORGE.EXE` keeps 0x7630 = 1 and 0x50b9 = 1 throughout (intro, title,
opening, PIMM). `BIOFORGE.EXE -e` shows it (0x7630 = 0) from the opening on: the arrow sits at the screen
centre with hotspot (1,1) on (160,100), colours 240..248 exactly as stored, also on top of the PIMM screen; the
hourglass push stays hidden during the load. The prototype (`play.py --editor-cursor`) and the native app
(Debug > Show Editor Mouse Cursor) draw the arrow at the pointer over every screen only when asked to.

## Running the original (DOSBox-X)

Homebrew `dosbox-x` runs the game from a scratch copy (never from `game/`): copy `game/app/Bioforge`
and `game/app/GAMEDAT` into one folder, `mount C` there, then run `C:\Bioforge\BIOFORGE.EXE` with
the GOG settings (`svga_s3`, 16 MB, cycles 35000, SB16 220/5/1/5). Capture only the DOSBox
window (`screencapture -l <window id>`; the id comes from a CoreGraphics window-list helper),
never the whole screen. `RED.OPT` (decode with `b & 0x7f`) is the engine's option file:
`PlayDir=%GameDir%\gamedat`, `initial game=%GameDir%\GAME0.IM1`,
`save game dir=%PlayDir%\*.*`, `light`/`camera` = editor gizmo meshes (DATA/LIGHT.IFF and
CAMERA.IFF are FORM REAL), `palette=%DataDir%\imgame.iff`, `captionfont=1.FNT`,
`font=small.fnt`, `tinyfont=tinyblk.fnt`, `mouseptr=mouse.shp`.

Live memory (2026-10-16): DOSBox-X 2026.10 has a debugger control client. With
`mcp_server=<port>` in `[dosbox]`, it connects to a TCP server on 127.0.0.1. The server sends
`REQ <id> PING|BREAK|EXEC <debugger command>` lines and reads `BEGIN <id> OK` … `END <id>`.
`EXEC MEMDUMPBIN 040F:<off> <len> <file>` dumps DGROUP (keep the file name free of path
separators; it is written to the working directory). `05E7:0 FA00` dumps the mode 13h
framebuffer, and `EXEC LDT` lists the selectors. `BREAK` is refused unless DOSBox-X runs from a
terminal; `EXEC` works without it. `re/tools/dosbox_live.py WORKDIR` does all of this: it copies
the game into WORKDIR (never `game/`), writes the GOG config with `mcp_server`, starts DOSBox-X,
and prints the figure records (via the list at DGROUP 0x1d19 and the player pointer at 0x2a66)
as JSON lines whenever they change, including the motion name (+0x15f), the heading from the model's
orientation, the root-limb yaw (model+0x25) and the frame (model+0x119); `--only NAME --every 0`
samples one figure about ten times a second. Heap objects dump through their own selectors (`MEMDUMPBIN
<sel>:<off>`). Port writes are `OUTP <port> <byte>` (plain `OUT` is not a command): `OUTP 64 D2`
then `OUTP 60 <scan>` makes the 8042 deliver a keystroke, so `--hold 48@84+10` holds ↑ (walk) and
releases it with the break code; `SM` writes memory, used by `--phys DR3=1`.

Automation that works (DOSBox-X `AUTOTYPE` in the autoexec, before `BIOFORGE.EXE`):
`AUTOTYPE -w 30 -p 6 esc esc enter enter ...` skips intro and title and picks a difficulty;
gameplay starts after about 45 s. `rshift` is a harmless filler key for longer waits. In-game
keys: `L` = load dialog, `S` = save dialog, `Tab` moves the hand pointer between dialog
buttons. The real play directory is `C:\Bioforge\GAMEDAT` (from E/INSTALL.OPT); a new game
fills it with the level IFFs only (MISC/SCRIPT/LISTS/VARS appear only on save).
Observed (2026-10-15):
- Subtitles match the prototype (two centred lines in the bottom box, same text).
- A `.im1` packed by `savegame.py` from the shipped GAMEDAT, placed as
  `C:\Bioforge\GAMEDAT\GAME1.IM1`, is NOT recognised: slot 1 shows no thumbnail and LOAD
  stays disabled. Later resolved: this was the wrong directory; archives belong in GameDir
  (`C:\Bioforge\GAME1.IM1`), as verified with native saves.
- Saving is refused during the opening ("PIMM: Save temporarily disabled. Please try again
  later.", the `CANNOT_SAVE` block); the nurse encounter then knocks Lex out. A genuine native
  `GAME1.IM1` (saved later in the game) is needed to finish the container work.

### Persistent testing (2026-10-20)

First send a `sample` request to an existing session. Start a session only when it is no longer
running; one startup is required, then keep the original paused between experiments:

```sh
BIOFORGE_DOSBOX_MUTE=1 re/.venv/bin/python -I re/tools/dosbox_live.py re/out/fall_live \
  --control re/out/fall_live/control --app-bundle --start 87 --background
re/.venv/bin/python -I re/tools/dosbox_control.py send re/out/fall_live/control \
  '{"command":"sample","figure":"LEX"}'
re/.venv/bin/python -I re/tools/dosbox_control.py fall re/out/fall_live/control \
  --out re/out/fall_live/check
```

With `--background`, the first command returns a detached controller PID and log path;
`WORKDIR/controller.json` retains both. Wait for the paused-ready message in `controller.log`
before sending commands. Without that flag it stays open until `quit`; `--seconds` does not
end control mode. The detached worker owns its own process session and the game's PTY,
so closing its launch terminal does not send it a hangup. It never automatically reboots a
failed emulator. The previous session disappeared without a new DOSBox crash report between
messages; background launch was added to remove dependence on a live tool-terminal session. It supplies the real PTY required by DOSBox-X's debugger, pauses at `--start`, and
accepts atomic JSON request files in `control/in/`, replying under `control/out/`.
`sample` pauses and reads state; `key` holds a PC scan code with optional modifier
scan codes for a duration and releases all keys, including on failure; `run_for` advances short intervals with paused samples between them; `set_z` checks
that Lex is grounded in a valid world and verifies position, model base and both cached
hull Z bounds after translation (the gravity path reads that hull before rebuilding it).
`debug` passes one raw debugger command line (BP, BPDEL, EV, MEMDUMPBIN) and returns its text.
`frames` resolves the named figure's live vtable update entry (+0x08), sets an owned
execution breakpoint, and verifies the function-entry stack's figure pointer at every hit.
For Lex this is the `10a8:1edd` wrapper of `FUN_1088_39ef`; runtime selectors are resolved
from memory. Samples at the next entry follow the previous completed figure update.
The command refuses pre-existing breakpoints, removes its own breakpoint on exit and
leaves execution paused. `base_heading` samples the persistent matrix at figure+0x111
(header at +0x110); `heading` still reports the rendered pose orientation. `set_heading`
writes only the persistent matrix for staged encounters and preserves the header and other state. `set_xy` translates figure/model/cached-hull XY and the model's animation-base XY
(+0x8c/+0x90), preventing the next pose update from undoing encounter setup.
Debugger byte writes and keyboard OUTP values use leading-zero numeric literals (for
example `0AF` and `0CF`): bare `AF`/`CF` are parsed as CPU flag names by DOSBox-X.
Readback caught this collision in a pose write; the same fix prevents lost key releases.
`phys_top` changes only the max Z of an existing non-solid PHYS space,
with readback; this is for controlled clearance experiments.
These operations leave execution paused. `run`, `pause`, and `quit` control the session.
`--attach --control DIR` serves the existing DOSBox-X connection without launching or
terminating the emulator. This also permits a controller replacement after code changes;
`quit` in attach mode disconnects the controller and leaves the paused emulator alive.
The reported game clock is the timing reference: debugger requests add overhead to the
nominal run intervals. The client exits nonzero on a failed command or test and never
boots another game as a recovery action. The fall check records `original.jsonl` and
`report.json`; a frozen game clock detects a load/options dialog before height injection.
The controller atomically moves an inbox request into `running/` before dispatch.
Client timeouts remove only queued requests; a running command is allowed to finish
and write its reply. Command-aware client waits are capped, so a timeout is not a
signal to send replacement inputs or restart the game. Pose translation validates
all derived signed coordinates before the first memory write.

Live validation (2026-10-20): the asynchronous trials in `check/` and `check_repeat/`
caught collision-search positions and could not establish a fall trajectory. The synchronized
capture in `synchronized_fall/` records five descending updates (vz -102, -204, -306, -408,
-510) followed by `land_soft`, with no incoherent samples. During a completed falling
update the model base remains the pre-move base: final position Z equals base + F + R + vz;
at rest it equals base + F + R. The validator checks these two cases separately.

The cell is too low for a 2000-unit lift: CE3 max Z is -2583, while Lex's standing hull top
is -3946 (only 1363 units of headroom). That caused the earlier immediate soft landing.
For the controlled fall, only CE3's non-solid space max Z was temporarily raised to 0;
the original -2583 value was restored afterward (`fall_setup.json` and
`fall_setup_restored.json`). Lex was relocated within the same cell away from the shock
trigger before the trial. The descent agrees with the prototype's -102-per-frame velocity
step. Landing-class mismatch resolved by an impact-entry probe (`impact_probe.json`): velocity is
already zero at runtime `021f:0e24`, and the motion-dispatch stack contains string pointer
`040f:2a22` (`land_soft`). The position-update chain above explains the reset before classification.
Python and Swift normal floor landing now clear velocity before selecting soft; both grounding
regressions reproduce the five-step descent. The temporary ceiling clearance was restored again
in `impact_setup_restored.json`.

Combat checks use the same paused process:

```sh
re/.venv/bin/python -I re/tools/dosbox_control.py combat re/out/fall_live/control \
  --target FIRSTBOT --attacks 6 --out re/out/fall_live/combat
```

The client checks figure flag 0x40 before pressing C, then sends Alt+KP8 (overhead hand
attack, `ATK_H8`; Ctrl+keypad uses the feet attacks). Plain keypad directions are combat
movement. Each trial records input, Lex update samples and full encounter snapshots.
Success requires an observed hand/foot attack motion plus either target health loss
(local 0) or a new target recoil reaction after the strike. An unchanged pre-existing recoil
does not count. Health damage and hit reactions are reported separately; movement or a
missed attack cannot pass. The client bounds attempts,
stops for a dead combatant, and does not change health or repair a bad encounter setup.
The original nurse encounter handles frontal hits through `FIRSTBOT_STIMULUS(_DAMAGE)`:
it reacts and sets `_nursebot_is_hit`; only back hits call `NURSEBOT_DAMAGE`, marking wound
bit 1 and starting the bounce behavior (`AI_NURSE.scr`). The six-punch original run observed `ATK_H8` and new `recoil_tl` reactions with nurse
health 50 and Lex health 63 unchanged. Its first five hits kept wound bit 1 clear; the sixth
hit set locals[3]=2 and locals[4]=2, enabled bouncy flag 0x10 (flags 0xd0), and started
`START_BOUNCE`. Thus the trace already contains the authored rear-hit transition, which
the initial health/recoil-only report omitted. `BOUNCE` was observed later at clock 14530. The encounter was staged by relocating Lex beside FIRSTBOT within the cell;
all attacks, reactions and health values came from the running original.

The dedicated `dosbox_control.py nurse DIR --out OUT` stages measured front/rear
positions. Remaining in `DEFEND` after an attack does not prove contact and cannot
pass the frontal check; a new reaction is required. Fresh-session captures under
`re/out/nurse_live/` show frontal recoil without wound, then the rear probe at 174.8°
sets locals[3]=2, locals[4]=2 and `START_BOUNCE` at clock 5184 (`rear_probe.json`).
The complete fresh front/rear CLI sequence subsequently passed end to end in
`re/out/nurse_validation/front_rear/report.json` (2026-10-20), with measured angles
2.8° front and 170.8° rear, a fresh front recoil and rear wound/status 2.

On an already wounded nurse the command stages explicit bar contact at XY
(-10090,-15100), preserving health, AI, velocity and wound state, then advances the
original. `bar_contact_defeat/report.json` passed: `ZAPPED` with `DR_ZAP3` in the trigger
list at clock 8697, health still 50, followed by FIRSTBOT removal at clock 9205;
Lex remained at health 100. The setup and all samples are journaled in `original.jsonl`.
Passive bouncing and X-only alignment did not reliably reach the doorway. This proves
the original contact/scripted defeat path, not a natural player push to the bars.
The bounded XY bounce response is now ported; full encounter parity is still open.

Native saves belong in `C:\Bioforge\GAME1.IM1`, **not** its `GAMEDAT` subdirectory.
The earlier live/parity boot code copied to the wrong directory; both paths are corrected.
`--load-save` stages the archive only; it does not automate the load dialog. Keyboard
accelerators were recovered (Escape, L, 1, L, Enter, Y, Enter), but repeated native reloads
produced BioForge fatal error 286.3330 (general protection fault). Automatic reload was
removed from the client. Reuse the paused world for successive trials instead.
`--app-bundle` creates a scratch copy of the installed DOSBox-X binary
with bundle ID `org.bioforge.dosboxx.test`, making its game window and menus available
to computer control. The original `game/` data remain untouched.

Do not use DOSBox-X emulator save states for this workflow. In Homebrew DOSBox-X
2026.10.01 on this ARM Mac, two restored emulator states returned the saved game clock
and positions, then crashed on resume with `EXC_BAD_ACCESS`, PC 0, called from
`TIMER_AddTick()`. The supplied crash report confirms the same stack. This identifies a
null call in the emulator timer path; the exact faulty timer registration has not been
isolated. Native `.IM1` loading also proved unreliable under repeated automated trials.

## Script query functions (2026-10-30, both ports)

Recovered from `re/decomp/10d8.c` / `10d0.c` and headless Ghidra (handler map `re/out/function_handlers.txt`). These functions
returned 0 while unmodelled, so the scripts took a wrong branch instead of failing. "Object" = `FUN_10c0_16a8` (CURFIG,
CURITEM or a figure / item name). Missing arguments or objects report an error and return 0. Distances use the usual
`cm = (units*100 + 0x80) / 0x800`.
- **Box centres.** Vtable +0x50 returns a reference point. WAYP (vtable `1290:1fb0`, slot `1060:192b`): the position +0xb.
  PHYS (`1290:210f`, `1068:02cb`) and IMAG (`1290:2077`, `1068:0f4c`): the centre, per axis `FUN_1210_0c24(lo + hi, 0x200)` =
  trunc((+0xb + +0x35) / 2). (In each table, index 1 is `1178:0ae5`. `PtrTable.java` must start on the table's own
  alignment: 1fb4 or 2101 give shifted pairs.)
- `DISTFROMEXTENT obj name` (`136a`): approx_length of the object's +0xb minus the centre of the first PHYS of that name (list
  `1290:1cf5`, `FUN_1050_0996`). `DISTFROMTRIGGER` (`1566`): the same with the IMAG list `1290:1ce9` (`FUN_1050_03f8`).
  The engine also has 2D versions (`0152`, `03b6`), which no script uses.
- `DISTFROMITEM` (`14aa`) and `2DDISTFROMITEM` (`02d0`) take no arguments. They measure the current figure (+0xe7b) to the
  current item (+0xe7f): approx_length (3D) and length2d. Without a current item, error 0x62; without a current figure, error 0x4d.
- `COORDX/Y/Z obj` (`0fc6` / `100a` / `104e`) return the position component **>> 8** (`FUN_1000_2727`, a long SAR, CL = 8). The
  ports used to return raw units. BEACH coordinates are around −1,140,000 and `AI_BEAST` tests `COORDX CURFIG < -4450`.
  `2DDISTFROMCOORDS obj x y` (`0000`) takes such values: length2d of (x << 8, y << 8) (`FUN_1000_2706`, a long SHL) minus
  the object's x, y. `GO x y z` with numbers (LEDGE.scr) uses the same units (ported, see "Level mechanics").
- `ISAION` (`27e8`): the current figure's +0x229 == 0 (`Figure.hold`: raised while the figure falls or dies). `ISGRAVITYON obj` (`2b57`):
  +0x34 bit 0x01. `ISKEYBOARDCAPTURED` (`2cf3`): [6530] (the CAPTUREKEYBOARD process pointer) is non-null.
- `FINDFIRSTFIGURE` (statement, `10d0:2f1a`): the current figure := entry 0 of the figure list (DGROUP 0x1d19 count, 0x1d21
  far pointers), process +0x42 := 0. `FINDNEXTFIGURE` (`181c`): if +0x42 < count − 1, +0x42 is incremented, the current
  figure := that entry, and it returns 1. Otherwise it returns 0. Live CHAOS order: USE_BOT, FIRSTBOT, FIDO, HALMECHO, CAYNAN,
  GUARD1, LEX (level records, then the player). The ports walk their own figure order (ASSUMPTION; the only users are the
  COMMON.scr quake loops, which act on every figure).
- `GETROOMAMBIENT` (`26a8`) / `GETCAMERAAMBIENT` (`21b4`) return the handle [63f6] / [63f2], or −1 when there is none. Those
  handles belong to the per-room and per-camera ambient loops `_%s_AMBIENT` that `FUN_1130_0e6b` starts on a camera switch,
  and `SETVOLUME` (`10d0:750d`) also applies its level to them. Ported 2026-10-31: see "Audio: voice statements, ramps and ambient loops".

## Missiles and FIRE (2026-10-30)

Segment 10e0 (`re/decomp/10e0.c`) holds the missile class. FIRE (`10d8:18a0`) and MAKEMISSILE (`10d8:3030`) both build missiles
through it. Headless disassembly was needed for the constructor, because Ghidra's decompilation of it is garbled.
- **Two objects per missile.**
  - A kernel task: vtable DS:47a9, size 0x56, base `10b8:0aa7`. Its slots are vt+0 per tick `10e0:0cbc`, vt+8 destroy `1239`, and
    vt+0xc hit-then-destroy `11aa`.
  - An Item, the "missile figure", at task +0x52. It lives in the item list DAT_1d0d and its mesh is `ITEMS/<TYPE>.IFF`. ZIPPY
    and TOSS have no file, so those carriers are invisible.
  - **Task fields:** +0x38 u32 handle (`DAT_2ed0` serial; `10b8:0e0d` returns 0 once the task is gone, which ends
    `SUSPENDWHILE FIRE …`), +0x3c VM context, +0x40 travel sound, +0x44 owner (CURFIG for MAKEMISSILE, 0 for FIRE), +0x48 range
    (s32), +0x4c/4e/50 spin a, b, c (degrees per tick).
  - **Type properties** come from the `<TYPE>` block in MISSILES.scr (`1078:0214`):

    | Property | Default | Flag or field |
    |---|---|---|
    | IS_BOUNCY | 0 | 0x10 |
    | HAS_GRAVITY | 1 when absent | 0x01 |
    | IS_REFLECTIVE | 0 | 0x20 |
    | ELASTICITY | 200 | +0xde |
    | EXTENT | — | half-extents, ASSUMPTION cm |

    Every shipped missile sets gravity, bounce and elasticity to 0. LASER, BOLTPFD and TNFABOLT are reflective.
- **FIRE.**
  - **Syntax:** `FIRE <type> <from> <to> <speed> <a> <b> <c> [CARRY <obj>]`, or `… <from> AT x y z <speed> a b c`, where
    x y z are `<< 8`.
  - **Start and destination:** the objects' vt+0x50 points (see "Script query functions").
  - **Range:** `approx_length(dest − start)`.
  - **Orientation:**
    - D = normalise(delta), R = normalise(cross(**start position**, D)), U = cross(D, R). Using the start position is an original quirk.
    - If R.z < 0, R and U are negated.
    - The rows are {U, D, R}, and the constructor rotates them 180° about Z.
  - **Speed:** speed32 = s·2048 (metres per second). The constructor sets velocity = row1·k >> 8 with k = `0c24`(speed32, 0x1e00).
  - **Return value:** the handle.
  - **CARRY:** sets missile flag 0x02, so the missile moves with no collision tests. It then attaches the object with
    `1138:05ff` (holder +0x2c). The attachment comes from the **carried** object's own `ON_<CARRIER TYPE>` property.
    FIGURES.scr gives ESCHEAD, HARD, LEX, LEXMIR and MASTABA `< ON_ZIPPY = (0,0,0) 0 (0,0,100) >` (positional I, J, K,
    LENGTH, X, Y, Z). Attaching sets no collision flag: it ends with vt+0x68 = `1070:2264`, which clears flag 0x04. So the
    trigger test (`1088:51c3`, which skips only flag 0x02) keeps running for a rider.
  - **Spawn:** `_<TYPE>_FIRE` plays once and `_<TYPE>_TRAVEL` loops. A missile born inside PHYS solids gets range
    −9,999,999 and velocity 0, so it expires on its first tick.
- **Frame order:** the world update (`1110:08bf`) moves items, missiles included, before figures (Item::Update `1078:1490` →
  `1078:08f6`). The scheduler (`1230:0259`) then runs the missile ticks.
- **Item mover.**
  - Attached or flag 0x02: it teleports.
  - Otherwise it sub-steps like `10a0:22e1`, with two tests per step. The PHYS score (`1058:1a1b`), and figures (`1110:0b29`): the
    first non-hidden figure in the figure list whose +0x65 box overlaps the missile, stored at +0x135.
  - A PHYS block calls `1070:1d8f`. A bouncy missile, or a reflective one whose support has flag 4, gets the generic rebound and
    `<TYPE>_BOUNCE`. Any other missile gets velocity 0 and `_<TYPE>_BONK_<material>`. The flag-4 surface is the collider PHYS (`FUN_1070_0f68`, as for the mantle) with flag byte 21 & 4 (resolved 2026-11-16, both ports: TOWER's kiosks, several elevator shafts).
- **Tick (`0cbc`):**
  1. Move the travel sound.
  2. Unless the missile has flag 0x02, run the hit check `0961`.
  3. Aim the model along −velocity, or spin it by a, b, c about X, Y and Z.
  4. Range −= approx_length(step).
  5. If range < 0 or the velocity is 0: run `<TYPE>_HIT_WALL` with CURFIG = none and CURITEM = the missile (first slice now),
     then destroy it.
- **Hit check (`0961`):**
  - A target with flag 8 is ignored.
  - If both the missile and the target are reflective: a random yaw of 5..355° and pitch of −20..20° (`11c8:199f`). The missile
    survives.
  - Otherwise run `<TYPE>_HIT_<target instance>` or else `<TYPE>_HIT`, with CURFIG = target and CURITEM = missile, then destroy.
  - The engine applies no damage itself. MISSILES.scr does (`DAMAGE … ENERGY`, recoil motions, `MAKEFLATOBJECT BOOM`).
- **Destroy:** stops the sound, clears the handle (which wakes waiters), and detaches children (`1070:05a1` → vt+0x44, then SetPos).
  A rider is left where the missile ended, with zero velocity. Scripts restore gravity and collisions afterwards.
- **Ports (both):** `re/interp/missiles.py` and `WorldMissiles.swift`, with tests in `test_missiles.py` and `MissileTests.swift`.
  They cover FIRE with CARRY, the move, hits, HIT_WALL, the handle and sounds.
  - **Rider placement:** the held-item formula (`items.hand_pose`, `1038:035b`), with the missile's origin and matrix as the limb
    (ASSUMPTION for a limbless carrier). Lex hangs 100 cm along the missile's row 2, which points mostly up.
  - **BEACH ZIP1_A → ZIP1_B:** an 88-tick ride. Lex ends 2052 units from ZIP1_B's centre and BCHDETH never fires. With the
    origin-to-origin guess, Lex's hull dipped into the acid volume and he drowned.
  - **Other ASSUMPTIONS:**
    - An attached figure skips its own move, gravity, grounding and pushes, but still animates and runs triggers.
    - Normalise, spin and the reflective redirect use floats rounded to 24.8, the same in both ports.
    - PHYS tests use every PHYS of the level (the null-area path).
    - HAS_GRAVITY is stored but not applied. (Wall rebounds: see the flag-4 rule above, ported 2026-11-16.)
    - Missile ticks run after the figure updates in `World.step`.
    - The handle is finished last on destroy, because the port's `finish` runs waiters at once.
  - **Hit check:** the flag-8 test is skipped. Bit 0x08 is INVULNERABLE in the ports, and dead figures leave the list.
  - **Saves:** a missile in flight is saved and restored ("Missiles in saves").
- **MAKEMISSILE (`10d8:3030`, both ports).**
  - **Syntax:** `MAKEMISSILE <TYPE> [<LIMB>] <speed> <range> (a,b,c)`, with speed and range × 2048 (metres). It returns the handle.
  - **No current item:** the named limb of CURFIG (`1040:17d6`). No limb returns 0 silently. The matrix is the limb's world matrix,
    and the start is the limb end − row1 · `0c42`(length +0x5e, scale +0x17 << 8) >> 8. Travel is +row1.
  - **Current item (the held weapon):** the start is the item's position, and the matrix is its world matrix with all nine
    components negated.
  - **Owner push-out:** the owner is CURFIG. The constructor (`10e0:0631..06f5`) repeats `pos += row1 of the passed matrix` while
    the missile's box overlaps the owner's +0x65 box (`1058:1684`).
  - **Port ASSUMPTIONS:** no per-limb scale (as in the melee reach); a figure without motions uses its rest pose; a cap of 1000
    push-out steps.
- **Shoot key.** ATK_SHOOT's frame 4 carries event 0xf0, which goes to figure vtable +0x98 = `FUN_1090_15d0` (INFERRED: it has no
  direct callers, and it uses the strings `rthand` and `%s_FIRE`).
  - With an item in `rthand` (`1138:040c`) whose type has `is_weapon` (`1138:04e4`, string pointer DS:6442), it runs
    `<item instance +0xf7>_FIRE` with CURITEM = the item. Otherwise it runs `<figure instance>_FIRE` with no current item.
  - CURFIG is the figure, and the block's first slice runs at once.
  - CHAOS: BLASTER_FIRE → `MAKEMISSILE LASER 6 60 (0,0,0)`.
- **Object locals in hit blocks.** The hit runner (`1120:0035` → `10c0:09c3` → `0bb3`) sets CURFIG = target and CURITEM =
  missile, and `1070:0417` zeroes the missile's locals. Generic `LASER_HIT` reads `IF CURFIG.~0 > 0 THEN DAMAGE ENERGY 25`: the
  target's health (selector 2 → ctx+0xe7b, `10c0:24e1`), so a laser bolt damages any live target (the nurse 50 → 29). An earlier
  reading said it never damages; that came from the swapped selector names (see "Object-local selectors").

## Flat objects, EXPLODE and THROWCURITEM (2026-10-31, both ports)

`re/interp/effects.py` and `WorldEffects.swift`, with tests in `test_effects.py` and `EffectsTests.swift` (same numbers).

- **`MAKEFLATOBJECT` (`10d0:52ff`, returns 0).** `( cam, seq [, obj] )` or `( cam, seq, x, y, depth )`. Words and numbers are
  separate argument lists.
  - cam names `ROOMS/<cam>.CAM`, and seq names an entry of it. The object form captures the object's reference point at creation
    (`script_point`: position, or a box centre) and never follows it. The screen form is 320×200 pixels plus an s32 camera depth
    (TANKS bubbles: `TNKD Q4B RANDOM (0,320) RANDOM (0,200) 50`). seq `DELETE` removes every flat object of that cam (unused).
  - Object: vtable DS:237b, ctor `1080:0afa`, list [1d3d]. Frame 0 is a 320×200 blank. W, H = the largest frame over 1..n−1.
  - Per drawn frame (`1080:0e38`): with n > 2 the frame is pre-incremented from 1, so frame 1 is never shown; at frame ≥ n the
    object ends and the next update deletes it. With n ≤ 2 it never advances and lives until DELETE.
    Lifetimes: BOOM WHITE / YELLOWA 21, BLUEC 17, REDB 13, PING 1; SPARKS LARG 16, SMAL 18, MEDI 15; TNKD Q4B/Q5A/Q9C 10.
  - Drawing (`11d8:0000`): unscaled RLE blit, top-left = (x − W/2 − hotx, y − H/2 − hoty), as a depth-sorted cel among the room's
    cels and polygons. The world form projects the point through the current camera and is skipped behind it.
  - ASSUMPTIONS: one advance per 30 Hz world tick (the engine advances per drawn frame); the room palette applies and the CAM's
    own palette is ignored (BOOM/SPARKS use indices 120–254, which match across rooms); x, y truncate toward zero.
- **`EXPLODE <obj> [CONTINUE]` (`10d0:2841`).** obj must be the current figure (else error 0x4c). `FUN_10f8_1f8a` returns 300
  (DAT 4d1e), and the handler waits t / 2 = 150 ticks with the WAIT object unless the second word is CONTINUE (any other word:
  error 0x66, the wait stays).
  - `1f8a` → `10f8:1ea2` hides the figure and its held items (vt+0x64 = `1088:553a`) and spawns "Shrapnel" mesh fragments
    (ctor `10f8:124c`, list [1d31]): ⌈(N−10)/10⌉ pieces of 1..5 faces, a random direction at about 4505 velocity units, −240/tick
    gravity, a 15°/tick spin, clamped inside the figure's area PHYS (bounce; `_METAL_HITS_<material>` on hard z hits), and a
    lifetime of 0–5 s. Ported 2026-11-16 ("Shrapnel").
  - KILL removes the figure from play at once in the ports but keeps its object in `dead_figures` / `deadFigures` until the
    level changes, so EXPLODE finds it (every shipped script does KILL, then EXPLODE) and hides its held items. The ports
    keep a figure `exploded` flag, because `hidden` is recomputed from the viewing cameras every step.
- **`THROWCURITEM <pitch> <speed>` (`10d0:84d0`, returns 0).** Needs CURFIG (0x4d) and CURITEM (0x62). The item leaves its
  holder (+0x2c cleared) and keeps its world pose. Then the LEAP self-mode tail on CURFIG's matrix: rotate about X by pitch,
  k = trunc((speed << 11) / 100), item velocity (+0xc6..) += row 1 · k. It is added, not assigned. TEMPLE's `0 -12` gives k = −245.
- **Free items (Item::Update `1078:1490`, before the figures).** Items now carry velocity, so VELOCITYX/Y/Z, SETVELOCITY,
  STOPVELOCITY, LEAP and `GRAVITY CURITEM` work on them. A free, non-missile item with a velocity takes gravity (vz −= 102 while
  vz > −0x500), steps by `velocity_step`, and moves through the missile PHYS sub-step mover. On a block: IS_BOUNCY gives the generic
  rebound (six axis candidates, then v −= v·ELASTICITY >> 8); anything else stops with zero velocity. Then
  `_<TYPE>_BONK_<material>` plays if it exists.
  - TEMPLE (TUNROOM): `GRENADE_FIRE` turns gravity off and throws at [245, 0, 0]. The grenade flies straight to the wall at
    x = 16361, and VELOCITYX goes 245 → −139 at tick 34 (E = 110), which `GRENADEENTERTUBE` waits for.
  - ASSUMPTIONS: items without EXTENT never block; landing (INFERRED)
    zeroes a gravity item's velocity when it rebounds upward from a fall with at most one gravity step of speed; thrown items do
    not hit figures. Items hidden by EXPLODE are never shown again.

## Moving floors: SETFLOOROFPHYS and TELEPORTALLONPHYS (2026-10-31, both ports)

`re/interp/floors.py` and `WorldFloors.swift`, with tests in `test_floors.py` and `FloorsTests.swift` (same numbers). Only user:
CONMACH.scr in CONTROL, the garage elevator. RAISE_GARAGE_ELEVATOR is run by the TAKEMEUP trigger, and LOWER_GARAGE_ELEVATOR by the
end of CR_HANGERMONITOR. Both turn the player's gravity off for the ride. PHYS lookup for both is `FUN_1050_0996`, the first PHYS of
that name, as AMINEXTENT.

- **`SETFLOOROFPHYS name n` (`10d0:708e`).** n is only the low 16 bits, signed (`10d0:70a7`), in script coordinate units:
  v = n << 8. The box keeps its height h. A space (state 0) gets lo.z = v and hi.z = v + h. A solid (state 1) gets hi.z = v and
  lo.z = v − h. x and y stay, and no object moves.
  - Errors: no name 0xfc, n = 0 0xfd, unknown name 0x8b, other state 0x100.
  - The engine also refreshes its saved floor slots +0x4b/+0x4f and sets DAT_222c = 2, so loose items re-check their support for
    about 2 frames. The ports don't model DAT_222c.
- **`TELEPORTALLONPHYS A B` (`10d0:7d5b`).**
  - Which objects: every item, then every figure (the player too), whose hull lies strictly inside A in x and y (`1058:18b4`).
    z is not tested. The set is fixed before anything moves.
  - New position: x' = B.lo.x + fix_mul(x − A.lo.x, fix_div(B width, A width)), and y' the same way. z' = B's floor (lo.z for a
    space, hi.z for a solid) + (z − hull bottom).
  - Then SetPos: the ports' `set_pos` for figures, a plain position for items. Either way velocity and step are zeroed.
  - A self-teleport `A A` keeps x and y. The scales are ELV→QSF 255/282 and QSF→ELV 256/232.
  - Errors: a missing name 0xff, an unknown PHYS 0x15.
- **The ride in the ports:** Lex stays 2333 units above the moving floor at every step (foot offset 2312 + 21). The ELV→QSF
  teleport moves him from area 18 to area 14. At the end, GRAVITY ON leaves him on QSF at z −7160.
- **ASSUMPTIONS:**
  - An item's xy test uses its point position, and its hull bottom is z − EXTENT z (0 before its physics are loaded).
  - A zero-width A uses scale 256 (the engine would divide by zero).
  - The engine keeps the moved box in level state and saves (INFERRED). The ports do not.
- **Stale hull:** SETFLOOROFPHYS rebuilds no hulls, so TELEPORTALLONPHYS reads the hull 21b2 stored at fig+0x65 BEFORE the floor
  moved. The ports snapshot each figure's hull (`stored_hull`, per tick) before moving a box; `set_pos` clears it. Lex then stays
  F = 2312 above the moving floor at every step (live recomputation gave 2333: the hull no longer snapped onto the raised floor).
- The garage problem this section first recorded (figures snapping to the control-room floor) is fixed by area-scoped floor
  queries (next section).

## Area-scoped floor queries (2026-10-31, both ports)

- `FUN_1060_03f2` (support) takes `(far result, far area, far hull query)`; `FUN_1060_0871` (point floor) `(result, area, x, y, z,
  optional hull)`. Ghidra drops the area. Disasm `1060:0405-045c`: a null area scans the global PHYS list (DGROUP 0x1cf5/0x1cfd) with
  best = NO_FLOOR; otherwise the loop ranks only the area node's `physical_objs` (+0xa count, +0xc list) and best is seeded with the
  anchor's floor slot (anchor = +0x16; `+0x4b + 4·state`: lo.z for a space, hi.z for a solid, no seed for state 2; not xy-gated).
  The Q pass's fit test calls `1058:1a1b(query, area)` with the same area. The per-PHYS rules are unchanged.
- Area callers: the hull rebuild `10a0:21b2` (`1138:1b8a` first, then fig+0x35 pushed at `10a0:2231/2235`; the result at +0xee feeds
  gravity/landing in `1088:39ef`), the whoah probes (`10a0:009b`, area from `1088:3c43`), the item mover / Item::Update
  (`1078:08f6`, `1490`). Global callers (wrappers `1060:0806` / `0d9a` push a null area): SetPos (`10a0:1ff0`, `1070:1e9d`), FLOATATHEIGHT
  (`10d0:2f91`), item drop (`1138:099b`), `1068:047e`, `1068:15ad`, `1070:2097`.
- Ports: `support` / `point_floor` take the figure's area (`area_of`, from `area_candidates`, now with the anchor state);
  `query_hull`, `settle` and `whoah` pass it; `set_pos`, the GO snap and `drop_item` stay global. The area lists are recomputed live
  and cached with the step's PHYS boxes (the engine builds them once at load; in CONTROL they are identical at every elevator step).
- CONTROL: ELV's members are {ELV, DOR, SH1}, so a figure in the garage stands on ELV (−165153), not on QSF/CTR above it. Standing on
  ELV with gravity on fires TAKEMEUP and the whole ride runs; LOWER ends with the player grounded in the garage at z −163064.
- No existing fixture or scenario changed. The port-only LAND_REVERT rule in `support` (a solid top > hull bottom + 0x1000 offers its
  bottom) was no longer needed by any test and was kept as a marked ASSUMPTION; it is **removed** (see "Movement fixes": it blocked the
  LANDPAD jetson tube and the TANKS catwalk, and 03f2 has no such clause; `0ead`'s own 0x1000 revert stays). The item mover's own
  support query is not ported (the ports' free items do not query support).

## Audio: voice statements, ramps and ambient loops (2026-10-31, both ports)

`re/interp/audio.py` (`AudioMixin`) and `WorldAudio.swift`; tests `test_audio.py` / `AudioTests.swift`. Sources: `10d0.c`, `10d8.c`,
`10b8.c`, `1028.c`, `1100.c`, `1110.c`, `1118.c`, `1130.c`, checked in the Ghidra disassembly. None of these statements blocks (all
return AL = 0); errors (`1120:02a6` codes 0x34, 0x3a, 0x17c) are script warnings and the script continues.

- **Voice fields** (SNDMGR `[19bf]`, 8 voices at +0x2e, stride 0x20): +0 the 32-bit handle, +4 the sample id, +6 the priority, +8 the
  level (0..255, before the master table), +0xa the **rate in Hz** (`1028:09d3` stores `header.rate − pitch`). `1000:0311` sets the
  channel step to `rate / 11025`. The ports keep `level` and `rate` for each sound handle (`World.voice_state`).
- `SETVOLUME h level` (`750d`): if h is 0 or −1, nothing happens. `1028:1464` treats the level as unsigned and clamps it to 255, so −1
  becomes 255. A dead handle is silently ignored.
  - If h is the room or camera ambient handle (`[63f6]` / `[63f2]`), the level also goes to the current camera's volume binding
    (below). This happens even when the voice is dead.
  - A positional voice gets its distance value back on the next frame (`1030:07cf` calls `1464` for every entry, every frame).
- `SETPITCH h r` (`7264` → `1028:152b`) sets the rate to r. `ADDTOPITCH h d` (`03bf` → `15db`) adds d to the rate.
  - Both use 16-bit words with no clamp. A positive ADDTOPITCH raises the pitch, the opposite sign to SOUND's pitch argument (ZAP.scr's
    "pitch increase").
  - The playback length changes, and AI_MAIN SLUR_ENEMY_SPEECH waits on ISHANDLEPLAYING.
  - **ASSUMPTION (re-timing):** a non-looped handle ends once `length · 30` sample-ticks have been played. The ports count
    `Σ ticks · rate` in integers, and a rate of 0 never ends.
- `REPLACESOUND name value` (`6a73`) writes the sound symbol's value (record +0x19 in the SOUNDS table `[cafe]`, stride 0x1d).
  - arg0 must be a symbol in that table, else error 0x34. A sound-name value copies that name's current value, so chains copy and
    do not follow.
  - `REVERTSOUND name` (`6c22` → `1118:4ad4`) restores the DEF value from the snapshot taken at load.
  - Every name lookup reads the symbol at use time: SOUND, AMBIENT, SUBTITLE, GETSOUNDHANDLE, ISSOUNDPLAYING, motion sound cues
    (`1088:13ea`) and the ambient loops. The ports use an override map in `sound_index` / `soundIndex`.
  - **Open:** the original's saved SOUNDS.DEF holds the replaced values. The ports do not save the overrides.
- `BANKINSFX` (`095d` → `1028:03fd`: preload and pin a sample), `SETSOUNDCACHE a b c` (`739f`) and `REVERTSOUNDCACHE` (`6c73`) only
  manage the sample cache, so they are modelled no-ops.
  - The cache limit is `min(c KB, a KB + b·(free − 5 MB)/1024)`. The scripts' `(1000,100,1000)` gives exactly 1,024,000 bytes.
  - REVERTSOUNDCACHE reads a, b, c from the "SoundMem" configuration item (ASSUMPTION: its defaults are unknown and not needed).
- `MODIFYVOLUMEOVERTIME` / `MODIFYPITCHOVERTIME` (`10d8:3788` / `374c` → `10c0:36b9` / `3589` → `10b8:04d3` / `0653`) take two forms:
  - `(h, START, END, D)` is absolute and sets START at once. `(h, DELTA, D)` (D in arg 2, arg 3 zero) is relative.
  - START == END or DELTA == 0 is error 0x3a and returns 0.
  - **Return value:** the serial of a new kernel task (class 0x10f, vtable `2e70`, counter `[2ed0]`, shared with processes). It
    lives exactly D ticks at 30 Hz, so `SUSPENDWHILE` on it waits D ticks.
  - **Ramp maths (`10b8:0762`):** if |delta| ≥ D, the step is delta/D (C truncation), the remainder is applied on the last tick, and
    the period is 1. Otherwise the step is **always +1** and the period is D/delta.
  - **Per tick (`0853`):** elapsed++, countdown−−. When countdown ≤ 0 the step is applied and the countdown reloaded. At elapsed == D
    the remainder is applied and the task is done.
  - **Apply (`090c`):** a volume step adds `(level + x) & 0xffff`, clamped to 255, so an underflow wraps to 255. A pitch step adds to
    the rate.
  - A volume ramp on an ambient handle also moves the current camera's binding by x.
  - **Engine quirk (INFERRED from the disassembly, replicated):** a negative delta with |delta| < D gives a negative period, so the
    step fires every tick and the volume rises. `INTRO.scr:416 (_sfx_2, 65, 0, 120)` ends at 185.
  - Several ramps on one handle are independent. A ramp to 0 does not stop the sound.
  - Ports: `vm.native_generator` / `nativeGenerator`.
- **Ambient loops.** The camera switch (`1130:0114`) sets `[63f1]` unless a monitor is running (`[4e2c]`).
  - Each unpaused frame, `1130:0e6b` runs at the end of `10e8:1dcc`. If `[63f1]` is set, it calls `1100:1b59` for `_<CAM>_AMBIENT`
    (`[63e1]`, camera loop `[63f2]`) and then `_<ROOM>_AMBIENT` (`[63e5]`, room loop `[63f6]`). ROOM is the first 3 characters of the
    camera name. Both use one volume, the camera's binding.
  - **Name lookup (`1118:0044`):** a missing name has its last `_xxx` stripped and is retried; nothing left gives −1.
  - **`1b59` (start or keep):** if the voice on the handle still plays that sample, only the level is set. Otherwise the old voice is
    stopped at once (`1028:0ddc`) and the new one started through `1100:1a15` (AMBIENT: looped, priority 1, volume low byte, pitch 0,
    not positional). A missing sample leaves handle 0.
  - **Volume binding (`1110:19cc / 1e3c / 1e74 / 1eab`, camera +0x7e):** bound to the script variable `_<CAM>_VOLUME`, else
    `_<CAM[:3]>_VOLUME`, else unbound with 255. VARS.DEF has them for almost every camera, e.g. `_CE33_VOLUME = 80`.
  - When the bound variable differs from the cache (a script assignment, SETVOLUME, a ramp), `0e6b` re-applies it to both handles
    the next frame. GETROOMAMBIENT / GETCAMERAAMBIENT return the handle, or −1 when it is 0. A dead voice's handle is still returned.
  - SOUNDS.DEF names only 3-letter room ambients (36, e.g. `_CE3_AMBIENT = 8`, `_BLK_AMBIENT = 8`, `_TWR_AMBIENT = 20`). The camera
    loop is therefore always silent and GETCAMERAAMBIENT stays −1. `SETVOLUME (_RoomAmb 0)` after it is a no-op (CHAOSHAL, CONTROL,
    LANDPAD, TOWER).
  - Ports: `World.update_ambients` runs after `refresh_sound_volumes` (ASSUMPTION about the relative order). It is armed from
    `camera_events` and, INFERRED, after a resume. The loops are ordinary AMBIENT handles: they hold a voice and can be stolen by a
    priority-1 sound.
- **Effect on the opening (both ports):** AWAKEN.scr calls QUAKE twice (`:129`, `:139`). Each call's decay ramp
  (`~3 = MODIFYVOLUMEOVERTIME(_sfx_4, ~1, 0, 30)`, `WAIT 15`, `SUSPENDWHILE ~3`, COMMON.scr:333-346) now waits 15 more ticks.
  - From tick 685 on, the opening is the old one delayed by exactly 30 ticks (checked tick by tick to 1069): WAKE_UP_HEAD 686 → 716,
    Lex stands at 1155 (was 1125).
  - The DOSBox parity scenarios anchor on WAKE_UP / ACTIVATE, so they are unaffected. Port-absolute anchors moved by +30: scenario
    starts 1140 → 1170 and the nurse-curves check 990 → 1020.
  - Processes that loop on their own phase (CHAOSBLK BLOCK_DRIP, CELL3_MON, the shared RANDOM stream) are not delayed. So the later
    staged scenarios are not pure shifts. opening_escape's `outside-cell` checkpoint now has Lex in `DRIPPED_ON`, because the walk meets
    another drip phase. opening_revival draws RANDOM in another order (different wound flags).
  - The Guard 1 fight lost its Easy win (it was seeded from the boot). `chaos_guard1_fight` now reseeds `World.rng` with
    `GUARD1_SEED = 1` at its staging point, logged as stage `rng`.
    - Easy is won with Lex at 25–29 HP and Medium is lost, for every start offset tried from 0 to 400 ticks.
    - The test's decal check is now "drawn, and within CHEST / BACK / FLEGS": which zones are hit depends on the fight path.
- Not modelled: the pending-voice pool (mgr +0xe). (Since 2026-11-20 the ports play a released loop's tail and LOADLEVEL stops every
  voice but the one its numeric argument names: "Released loops play their tail", "Engine assumptions settled".) Before then also: the
  sample tail of a released loop, LOADLEVEL stopping the loops (ASSUMPTION: the
  next camera switch replaces them), and the overrides in saves. (The `_LOAD` / `_UNLOAD` order is ported: "Room events and the default AI".)

## Motion sound cues and formatted sound names (2026-11-18, both ports; from the decompile, not checked live)

Found from a playtest: a fight with Caynan had no footsteps, hits, grunts or recoil sounds. The ports never played the motion
cues, and the hit and block names were looked up exactly, so they almost never existed.

- **The lookup `1118:0044`** (from `FUN_1100_1c3e`, `1c92`, `1ce4`, `1d34`, the ambient loops `1058:0bf1`, the shrapnel `10f8:1b0c`):
  the formatted name is looked up in the SOUNDS table (case-insensitive). A name longer than 25 characters is first cut to 24.
  - If the name is not there, it is cut at its last `_` and looked up again. When nothing is left, the result is -1 and nothing plays.
  - So `_CAYNAN_HITS_LEX_CE31` plays `_CAYNAN_HITS_LEX`, `_BLOCK_NURSEBOT_LEX` plays `_BLOCK` (280), and `_WALK_1_LEX_CE31` plays
    `_WALK_1_LEX`.
  - Ports: `audio.ambient_id` / `ambientId`, now used for every name the engine formats.
- **Who plays at what** (`1100:196c(id, figure, priority, volume, pitch)`):

  | Sound | Caller | Positional | Priority |
  |---|---|---|---|
  | hit `_%s_HITS_%s_%s` (attacker MATERIAL, target MATERIAL, camera) | `FUN_1100_1ce4` | at the target | 1 |
  | block `_BLOCK_%s_%s` / `_BLOCK_%s`, guard `_metal_clank_1` | `FUN_1100_1d34` | no | 1 |
  | BONK `_%s_BONK_%s_%s` (10a0:0ead), `_%s_BONK_%s` (1070:1d8f) | `FUN_1100_1ce4` | at the figure / item | 1 |
  | motion cue | `FUN_1100_1d82` / `1c92` | at the figure | 0 |

  Volume 255 and pitch 0 for all of them; a positional voice gets the distance rule.
- **The event walk** (`FUN_1088_1854`): the list holds frame-number bytes with event bytes between them. It runs only when the
  frame changed since the last update (+0x121 < +0x119).
  - From the position where it stopped (+0x10a), it dispatches every byte >= 0x80 (`FUN_1088_13ea`). It stops at the byte equal to
    frame + 1 (+0x11d), at 0xfe, at the count (+0xfa) or after 999 bytes.
  - So the events after frame byte k fire while frame k shows. Events before frame byte 0 fire on the motion's first frame.
  - At 0xfe the walk waits until the loop wraps. The wrap sets the position back to 0 and the frame to 0 with "previous frame" 0,
    so the first events of the next cycle fire at its first frame change.
  - Skipped frames are fine: the equality test only stops at frame + 1.
- **Sound cues** (`FUN_1088_13ea`): bytes 0xfd (case -3, n = 1) and 0xfc..0xf9 (n = -3 - byte = 1..4).
  - It tries `_%s_%d_%s_%s` and `_%s_%d_%s` (1290:24d0 / 24dd) with motion name (header +6), n, form (+0x1ea), camera `[63e1]` and
    room `[63e5]`, in this order, each looked up exactly (`FUN_1100_1d82`, no cutting):
    `_<motion>_<n>_<form>_<camera>`, `_<motion>_<n>_<form>_<room>`, `_<motion>_<n>_<camera>`, `_<motion>_<n>_<room>`.
  - If none exists, `_<motion>_<n>_<form>` goes through 1118:0044 (`FUN_1100_1c92`).
  - The data fits: NURSEBOT ACTIVATE has 0xfc, 0xfb, 0xfa, 0xf9 and SOUNDS.DEF has `_ACTIVATE_1..4_NURSEBOT`. Lex's WALK has 0xfb and
    0xfc and the bank has `_WALK_2_LEX` and `_WALK_1_LEX`. The hard suit's `_WALK_1_HARD_PAD2` is form HARD at camera PAD2. Many
    names are aliases: `_ATK_M1_1_CAYNAN` is `_WALK_1_CAYNAN`'s sample, `_DIE_1_CAYNAN` is `_CAYNAN_GRUNT`'s.
  - Over all motion files: 0xfc 298 times, 0xfb 69, 0xfa 17, 0xf9 5, 0xfd never.
- **Other bytes, not ported:** 0xf8 (NURSEBOT STAND only) starts the figure's ambient loop `_<motion>_AMBIENT_<form>_<room>` through
  `1058:0bf1` on +0x135. It cuts down to nothing in the shipped data, so it is silent. 0xec (-0x14; NURSEBOT ACTIVATE / DEACTIVATE,
  three SHRIMP motions) jumps to the motion's last frame and commits its root. 0xea (MAN ATK_M7) falls through and does nothing.
- **Ports:** one walk for every event byte, sound cues and item events alike: `items.py` `event_walk` (state `World.cue_seen`, raw
  lists from `items.event_list`) and `audio.py` `motion_cue`; Swift `WorldItems.swift` `eventWalk` and `WorldAudio.swift` `motionCue`.
  `motion_events` / `motionEvents` runs it in the per-figure update.
- **The item events moved one frame earlier (2026-11-18).** They used the rule "after N frames fires when frame N shows". By the walk
  they fire while frame N - 1 shows: PICK_UP_LTHAND's grab while frame 15 shows, PUT_DOWN_LTHAND's drop at frame 11, Lex's ATK_SHOOT
  bolt at frame 3. Shots leave sooner after their aim:
  - The TOWERBOT FIRE motion is `0, 0xf0, 1, ...`: a ledge bot's bolt now leaves on FIRE's first frame, the update its script's
    TURNTOENEMY ran (LANDBOTS.scr LDGBOT1_AI), and lags a running Lex much less.
  - AIRMECHO's FIRE_GUN (`0 1 2 3 0xfc 0xf0 4`) and MECHO2's bolts leave a frame sooner too.
  - The scripted route was retuned for it (re/playthrough/full.md, surface.md): AIRMECHO's dodge starts just before the gun comes up,
    Lex runs straight to MECHO2's safe corner, and he runs the LANDPAD ledge on its west side, 7000 units from the bots.
- Measured on the prison route (Python, ticks 11398-13818, the Caynan fight): 133 sounds before, 274 after. Caynan's footsteps
  (sample 6), `_CAYNAN_HITS_LEX` (76), Lex's hits (11), Caynan's super recoils (649), his death grunt (10), Lex's footsteps
  (360 / 257) and recoils (239 / 241), and `_block` (280) now play.

## Surface playthrough findings (2026-10-31, both ports)

From `re/interp/playthrough_surface.py` (route and blockers: `re/playthrough/surface.md`; tests `test_playthrough_surface.py`,
`PlaythroughSurfaceTests.swift`).

- **IF / ELSE at run time.** IF (`10d0:3a6c`) stores its result in a flag per brace depth (ctx +0x75 + depth, depth = +0x41); true runs on,
  false skips one statement (`10c0:0f78`: a `{ }` block by brace count, an IF or ELSE token as its line plus one statement, recursively,
  so a nested IF is skipped without a following ELSE). ELSE (`10d0:27f9`) runs its statement iff the depth's flag is 0. So
  `IF a THEN IF b THEN x ELSE y` runs y when a is false as well as when a is true and b false (WARHEAD_TIMER, WARHEAD.scr:430-442: the
  fuse stopped after the drop). The ports keep the parse tree (ELSE on the inner IF) and jump a false outer IF of a braceless chain to
  that ELSE (`vm.Code._else_at`, ScriptCode `elseAt`; parser flag `braced`).
- **`GO <name>` (`10d0:33c8`)** resolves a figure, then a waypoint (list 1cdd), then an IMAG (1ce9), and moves to the object's reference
  point (vtable +0x50: a WAYP's position, an IMAG's box centre, see "Box centres"); other lists use +0xb. The ports used a box's first
  corner (`World.go_target` / `goTarget`). FACE's lookup is not recovered and still uses `target`.
- **Motion requests (`1098:0e49`)** format `%s_%s` (1290:299e) with the instance name +0xf7: the shoot key runs `LEX_ATK_SHOOT` in every
  form (there is no `HARD_ATK_SHOOT`). `World.request_motion` (the mantles) still formats the type name; no such blocks ship.
- **LOADLEVEL callers, three-word destinations, FIGR AI names, Use blocks that take Lex**: found here too, ported by the base
  playthrough (see its section); this branch uses those versions.
- **Player input ownership (port ASSUMPTION):** a script-set loop of one of the player's key moves (MANUAL_MOVES) yields to keys
  (AIRMECHO's death leaves `MOTION ATK_M2 CONTINUE`, AI_AMECH.scr:95).
- **A trigger's LOADLEVEL inside the frame**: `World.step` skips figures the load dropped (they indexed the new level's PHYS list).
- Since the CURFIG/CURITEM selector fix the bots' `NRLASER_HIT_LEX` damages Lex: the BEACH bots kill a suited Lex in ~150 ticks at the
  arrival, the LANDPAD ledge bots on the ledge (rate and damage since checked: faithful). AIRMECHO's `BOLTGRN` never hit because of `TURN`; both in NOTES "Items and combat".
- Open (all four resolved by "Movement fixes"): mantles do not lift (a finished motion's root z is carried only with gravity off); a FREEZE
  pose under AI ON keeps the keys out (THE_DIGTUBE's `ENTER_GRAV FREEZE`); the open jetson tube is not walkable; Lex falls through
  PLATFORM after the harness's TO_FINAL.

## Level mechanics: forms, limbs, texture animation and small statements (2026-10-31, both ports)

`re/interp/mechanics.py` and `WorldMechanics.swift`, with tests in `test_mechanics.py` and `MechanicsTests.swift` (26 each, same numbers).
Script context: ctx+0x7f first word, +0x1dd second word, +0xe2b the numbers, +0xe7b CURFIG, +0xe7f CURITEM, +0xe83 referent.

- **`CHANGEMYFORM <name>` (`10d0:192c`).** Acts on CURFIG. Errors (no change): no CURFIG 0x4d, empty word 0x64, no `<Figures dir>/<name>.BED`
  (`11a8:083b` "Figures" + `.BED`, checked by `11e0:0d0d`) 0x20. The name is not checked against FIGURES.scr. It then calls `FUN_1088_2a87`,
  the CREATEFIGURE loader:
  - It deletes the old model (+0x17: mesh, skeleton, skin, motions and the texture state) and writes the form name to +0x1ea (what ISMYFORM
    compares; the instance name +0xf7 stays). It builds the new model (`1088:0000`), loads the BED (`1088:0142`) and copies the new F
    (model +0x88) to +0x225.
  - By form name it re-reads EXTENT (default 10,10,10), IMPACT_ARMOR, ENERGY_ARMOR, IS_REFLECTIVE, AUTO_TURN_SPEED and PERSONAL_RADIUS.
    MY_SPEED is read by the instance name, so it does not change. Gravity, bouncy and elasticity come only from the creation path `1088:22ba`
    and are kept, as are position, heading, health, items, AI, velocity and the other flags. No event, sound or block runs.
  - For non-player figures it also calls vtable +0x64 and `1128:0569` (not decoded, not ported).
  - The ports swap `assets` and `type`; the per-type values are read from the type on use, so they follow. Decals, ANIMATE state and the
    FLOATATHEIGHT override are cleared (INFERRED: they lived in the deleted model). 2a87 starts no motion; ASSUMPTION: the ports re-map the
    current motion by name (frame kept if valid, the motion id bumped) or STAND.
  - LEX → HARD (BEACH, Lex at ZIP1_A): mesh vertices 159 → 132, F 2312 → 2317, hull z (−17356, −13876) → (−17372, −13830), MY_SPEED stays
    384; switching back restores the old state exactly. DIGSITE's real HARDSUITMACHINE reaches `type == HARD` at tick 105.
- **`GRABCRITTER <obj> <limb>` (`10d0:38a4`) and `RELEASEFROMLIMB <limb>` (`10d0:663e`).** The holder is CURFIG; obj resolves through
  `10c0:3e14` (PLAYER or an instance name; it borrows CURFIG and restores it). `1138:05a1` → `05ff` is the FIRE … CARRY attach: holder
  +0x2c and a +0x30 record with the limb name. The offset is the **grabbed** object's own `ON_<limb>` property (`sprintf` DS:6481). No script
  defines `ON_*FINGER*`, so it is zero (ASSUMPTION for the property defaults). The engine sets no flags; AI_BEAST's HIT_LEX does
  `COLLISIONS CURFIG OFF` on Lex itself. Errors: an empty argument 0x123 / 0x4f, no CURFIG 0x4d, a limb not in the holder's skeleton 0x126
  (release only). RELEASEFROMLIMB finds the attached object (`1088:5669`), clears +0x2c and frees the record: no SetPos, no velocity or
  flag change, unlike the missile detach `1070:05a1`.
  - Ports: `Figure.limb_holder` = (holder, limb). An attached figure (carrier or limb holder) skips settle like a missile rider. After the
    figure loop, `place_limb_held` puts it at the hand_pose formula point of the holder's current animated limb (INFERRED: `1088:5c19`, a
    vtable method with no static caller; ASSUMPTION for the order).
  - The real AI_BEAST READY_ACID → HIT_LEX (Lex staged in the claw's reach, gravity off): grabbed at tick 19 at (−1110284, −1067789,
    −13787), carried up by SWALLOW to (−1108550, −1067466, 2035) at tick 108, released at tick 109, then `GO 6666 6666 6666`.
- **`PLACEITEM` on any limb.** An item placed on a non-hand limb (READY_ACID: `PLACEITEM RFINGER2`, the CLAW) loses its level position like a
  held item, and `item_world_pose` / DISTFROMITEM / 2DDISTFROMITEM use the holder's limb pose for any limb (the vt+0x50 point of an
  attached object; before, the claw kept its stale level position and HIT_LEX's grab poll never passed).
- **`FREEHAND <hand>` (`10d0:3207`).** CURFIG (0x4d), empty word 0x4f, nothing in that hand (`1138:040c`): nothing. `RTHAND` (DS:3826) starts
  the `put_down_rthand` motion through vtable +0x7c and waits for it (`1238:0f48`); its event 0xf3 drops the item (`1088:5b43` → `1138:099b`,
  `<holder>_<item>_DROP`). Any other word stows the item (`1138:1274`) at once. ASSUMPTION: the ports start the motion directly and do not
  consult the `<TYPE>_PUT_DOWN_RTHAND` script override that the Enter key honours. FLUTE_USE reaches START_FLUTE after 45 ticks.
- **`ANIMATE <obj> <texture> [words] [n]` (`10d0:077b` → `10f8:0631`).** obj via `10c0:16a8`. The texture name (upper-case, 8 characters) is
  looked up in the model's texture lists (`1168:0752`); a static or missing texture is a silent no-op. Each word is looked up in the table at
  1290:4c76 and OR-ed into a mode byte: FREEZE 0, INCREMENT 1, DECREMENT 2, RANDOM 3, LOOP 0, YOYO 4, TO_LIMIT 8, RESET 0x10, ONCE 0x20. **ON
  and OFF are not in the table**, so `OFF` gives mode 0 (frozen on the current frame). n is the period in 60 Hz clock units; ≤ 0 or missing → 15.
  The mode is overwritten (`1168:04f4`), the period set with next = clock + period (`1168:04ac`), and RESET alone sets frame 0.
  - Texture record (0x28 bytes): +0x17 frame count, +0x1d frame, +0x1f next (u32), +0x23 period, +0x27 mode. Textures load with mode 0 on
    frame 0, and ANIMATE is the only writer, so a texture no script animates never changes in the engine.
  - Step `1168:055e` (via `0711` from the draw method `1188:1d54`, INFERRED: at most one step per draw): when clock ≥ next, step up, down or to
    a random frame; wrap, yoyo (the end frames show once) or clamp; ONCE clears the mode; next = clock + period (no catch-up).
  - Ports: per-object `anim` state stepped once per world tick for every figure and item, clock = 2 × tick (ASSUMPTION: the engine steps on
    draws; RANDOM uses the shared world RNG). **Drawn since 2026-11-20:** the renderers use this state (frame 0 without it). Before, they cycled every animated
    texture at tick/4, which does not match the engine (frame 0 unless animated).
  - BEACH beast `ACID0 ON INCREMENT YOYO 5` (6 frames) steps every 3 ticks: … 3 4 4 4 5 5 5 4 4 4 3 … 0 0 0 1 …. The CHAOS nurse's
    NURSEBOT_LOAD animates SLEAKSD/BA (3 frames) and SLEAKEY/NE (4) with period 15.
- **`SETREFERENT <obj>` (`10d0:7330`).** Sets the running process's referent (+0xe83) to the object; an unresolved object changes nothing.
  At spawn (`10c0` spawn, lines 535–556) the referent is CURFIG, else CURITEM. The Item destructor (`1078:0690`) and the base destructor
  (`1070:05a1`) kill every script process (task type 0x10a) whose referent is the dying object, so a missile's HIT_WALL block (CURFIG none)
  dies with the missile unless it moves its referent (AIRHALL BOLTGRN_HIT_LEX, TOWERGUN MISSILE_HIT_WALL). Error 0x70 when +0xea1 is set
  or the process is its referent's own owned process (`10c0:25f7`): not modelled. Ports: the kill runs on missile destroy and KILLCURITEM;
  figure referents are NOT PORTED.
- **`INCVIRTUALSECONDS n` (`10d0:6cef`, AWAKEN DETERMINEMACHINESPEED).** n ≠ 0 loads the persisted `_TimeTest` option into that script
  global (`10f0:0651`, `1100:0d82`; absent from INSTALL.OPT → 0). n = 0 raises the Speed_Factor [66c6] (cap 20), sets the timer rate to
  60 − 2n (`1238:16e9`) and persists the factor and `_TimeTest = 1`. The ports keep `speed_factor` without a reader; the timer rate and
  persistence are NOT PORTED. The real block finishes in 41 ticks with `_TimeTest` 0.
- **`FORCERELOAD` (`10d0:31db`, the end of AI_LEX's death block).** Not a weapon reload: the player's +0x92 (s32) := −1 (ASSUMPTION: object
  local ~0, as `hit_points`), then `FUN_10a8_02cc(2)` opens the options dialog with _OPTS_MUST_RELOAD, and the process yields. The lost Medium
  Guard 1 fight now ends with Lex at −1 HP (was 0).
- **`GO x y z [WALK|RUN] [speed]` (`10d0:33c8`).** Numeric when the first word is empty, WALK or RUN. Target = (n0 << 8, n1 << 8, n2 << 8),
  i.e. COORDX units; the 4th number is the speed (`(n << 11) / 100`, 0 → 614 in `1098:11c0`; ignored in the ports, ASSUMPTION). WALK / RUN
  start the mover task and wait as for names; any other word is error 0x120. Without a modifier: SetPos (`10a0:1ff0`), so with gravity z =
  floor + F + R (not gated on an area). Examples: CHAOS `GO -57 -292 -21` → (−14592, −74752, −5093) on the floor; AI_BEAST
  `GO -4935 -4215 -100` with gravity off → z −25600 exactly. `GO 6666 6666 6666` parks the figure off the map at 1706496 on each axis.
  ASSUMPTION: with gravity on and no floor the ports keep z (the engine would land near −819200 + F); the figure's retained area later pulls
  its z back to the old support while x and y stay parked (never visible).
- **FLOATATHEIGHT `<waypoint>`, one word (`10d0:2f91`).** F := waypoint z − the floor under the waypoint (`1060:0d9a`, null area), stored in
  model +0x88 and +0x225; model +0xa6 (R) := 0; z := the support cached by the last hull rebuild (+0xee) + F, then vtable +0x2c (the mover).
  F then drives SetPos, grounding (hull bottom = z − F − R) and the hit-zone height. Ports: `Figure.foot_override` and `World.foot(fig)`
  replace every per-figure read of the type's F; the support is the current area-scoped one (ASSUMPTION: equal after the `GO <waypoint>` that
  precedes every use). BEACHBOT READY_BBOT1: the floor under B_BOT1 is −8787 and the waypoint z −6713, so F = 2074 (type F 544); the bot
  hovers at z −6713 with gravity on.
- **`CAMERA SHOW <cam>` / `CAMERA AT` (`10d0:12f9`).** SHOW (`10d0:115c`) loads and switches to a full-screen picture camera (TITLE, STITLE,
  RTRW: a 320x200 picture of colour 121 alone, BLAST_LEX's white flash) and turns automatic camera selection off (`[63da] = 0`).
  `CAMERA AT` (`10d0:0c5e`) is used by no script. See "CAMERA SHOW pictures and the TITLE hold" below for what the ports draw.
- **CAMERA SHOW pictures and the TITLE hold (2026-11-18, both ports; from the code, not checked live).** Playtest: after the difficulty
  choice the original shows the red BioForge picture before the first room, the port showed black. START.scr's STARTPLAYING does `CAMERA SHOW
  TITLE` (ROOMS/TITLE.CAM, its own palette, no text) before the dialog. When the dialog closes, the next tick runs `LOADLEVEL CHAOS PLAYLOC`
  (`FUN_1148_1a76`), which renders nothing while it reads the level and its objects (`FUN_1148_1386` and the object loop) and installs the
  all-black palette (`1130:147c`) only after them, so TITLE stays on screen for the load's duration: disk time, not a script timer, and no
  key skips it. Then GOODMORNINGLEX (AWAKEN.scr) does `FADE HIDE` (black at once), `CAMERA CE31`, DETERMINEMACHINESPEED (40 frames), `WAIT 1
  SECOND` and `FADE SHOW`: about 2.4 s of black before CE31. The ports used to keep a SHOW picture only for the options dialog's underlay;
  now it is the screen (`play.to_rgb` / `World.renderPresentation` and `hiResFrame`) under a flic, until a real camera switch or LOADLEVEL
  (`shown_picture_rgb` / `shownPictureFrame`). The bare `World.render` stays the room for camera feeds and the indexed fixtures. The port's
  load takes a frame, so the app holds the picture for `GameSession.pictureHold` (2 s) when the dialog closes over a SHOW picture, before
  the next tick (`pictureHoldDue`; ticks wait, so the tick timeline and random stream are unchanged): KNOWN_DIFFERENCES.md. The hold is
  app-only; `play.py` does not hold. Not ported: SHOW's auto-selection off (`[63da] = 0`); a real switch in the port ends the picture.
- **Held keys and the dialog.** The dialog takes the keyboard, so the key that opened it (O, or the app's Escape, sent as O) never gets its
  key up in the world; the ports kept it in `keys_held` and the next O was ignored as a repeat (Escape could not reopen the dialog). Opening
  the dialog now clears `keys_held` / `keysHeld`, and the app releases its synthetic O at once.
- **The screen after a death (checked live 2026-11-11, VGA dump).** KILLLEX (AI_LEX.scr) waits `_delay_before_reload` seconds, then `CAMERA
  SHOW STITLE` and FORCERELOAD. OPTS.CAM's background frame is 320x200 and fully transparent (the border is the FRMA element), and the open
  path (`10a8:02cc`) clears nothing, so the dialog is drawn over what the screen shows. Ground truth: `dosbox_live.py`'s `vga` control command
  dumps the mode 13h screen (64000 indices at 05E7:0) of the reload dialog over STITLE (`re/out/tower_live/GAME1.IM1`, the bots kill Lex in
  seconds); through the OPTS palette it is the live screen exactly. Recovered from it and the code:
  - **The picture behind:** each STITLE pixel becomes `128 + max6 * 18 / 64`, max6 its largest 6-bit channel: FUN_1108_0d83 (max of r, g, b)
    and FUN_1108_0cfc (range table `start + brightness * len / 64`), applied to a rectangle by FUN_1138_1d0a (FUN_1100_1276 does it with the
    "dark_gray_color" range, `[5e3e]`). The range 128..145 (length 18) is measured: it matches every pixel the dialog leaves transparent,
    lengths 17 and 19 do not. Ports: `monitor.dark_grey` / `MonitorScreen.darkGrey`.
  - **Translucent buttons (FUN_1270_185b):** an element with its +0x2e bit 0 set (FUN_1270_16a2, message 1 on, 2 off) is drawn into a buffer
    cleared to 0xff and then blended: pixel p over screen pixel d becomes `(p & 0xe0) + T[p & 31][d - 128]` when d is in 128..159, p != 0 and
    p's ramp is not 0xe0, else p. FUN_1270_174b builds T: `T[o][u] = o + ((31 - o) * (u * 100 / 31) + 50) / 100`, capped at 31. So a button
    lightens along its own 32-entry ramp by the grey under it (fill 41 over 145: 53). Ports: the options dialog's X elements (`Monitor.translucent`
    / `translucentKinds`); INFERRED that every X element has the flag (all main-panel buttons do in the dump; the other options element kinds
    Q, Y, J, G are not seen in it and stay solid). The 2x/4x path blends the same way per enlarged pixel.
  - **Button frames:** the drawn frame is the button's state (FUN_1280_176b): EXTX opens in state 2 (its lit frame), SAVX in 5 (dimmed) for
    MUST_RELOAD or NO_SAVE, and RETX in 5 for MUST_RELOAD, so a dead Lex cannot go back to the game (the ports closed the dialog on RETURN).
    States 2 and 5 are confirmed by the dump; 3 (the audio panel's on toggles) follows the same rule, unchecked.
  - Match: 99.3% of the pixels outside the pointer equal the dump. The rest are the CREDITS label text against the blended fill (about a
    pixel off) and a few picture pixels.
  - Ports: `World.shown_picture` / `shownPicture`, cleared by a real camera switch and by LOADLEVEL; `Monitor.render(underlay)` /
    `MonitorScreen.render(underlay:)`; without a SHOW picture the underlay is the screen the dialog covers (`options_underlay` /
    `optionsUnderlay`: a running monitor, or the room with its caption). Checked live with O in CE31 (`re/out/native_save/GAME1.IM1`): the
    room shows dimmed behind the dialog with the same translucent buttons (88% of the picture pixels match the formula against the room screen
    dumped 6 ticks earlier, the nursebot moving in between), and the game clock stops. The new-game difficulty dialog follows START.scr's `CAMERA SHOW TITLE` the same way and
    sits on the dimmed TITLE picture: INFERRED from the same mechanism, not captured live.
  - Viewport feeds (`draw_viewport`) keep their fitted grey conversion. FUN_1100_0c14 is likely their real path: a stretch blit through the
    "video_color" range table (`[5e4a]`); not ported yet.

## Presentation, flics and front end (2026-10-31, both ports)

`re/interp/presentation.py` / `WorldPresentation.swift` (palette, FADE, RUMBLE, CAPTION, DEBUG, pointer) and `re/interp/show.py` /
`WorldShow.swift` (flics, FREEZE/THAW, keyboard hook, front end); JUMPON is in `vm.py` / `ScriptVM.swift`. Twin tests `test_presentation.py`
/ `PresentationTests.swift` and `test_show.py` / `ShowTests.swift` (same numbers). The app's ShowPlayer is gone: the core renders the flic.
The per-tick "render" hook is `World.step` in both ports (ASSUMPTION; the engine ticks these once per rendered frame).

- **DEBUG `10d0:2445` / DEBUGINFO `10d0:25cf`:** release no-ops. Only `DEBUG ON/OFF/NEVER/STACK` write a per-process trace mode
  (ctx+0xe9f) whose one reader calls `10c0:24dc`, an empty `return`. No print, wait or termination.
- **Palette (`10e8:16bb`):** one additive offset per channel (DS:c672/4/6) = gamma offset (`1100:0e6f`) + the CHANGEPALETTE argument,
  on all 256 6-bit entries, clamped 0..63.
  - `CHANGEPALETTE r g b d` (`10d0:1a43 -> 10e8:1427 -> 18c1`): signed offsets that replace the previous ones; d in 30 Hz ticks
    (stored as 2d against the 60 Hz clock). d ≤ 0 persists; d = 1 is a flash (the engine busy-waits 50 ms at the next render,
    `10e8:1488`; the ports show one tinted frame, ASSUMPTION); d ≥ 2 latches at the first render and reverts after d ticks (`145c`).
    Setting the gamma cancels it. Never blocks, not saved.
  - `FADE HIDE|SHOW|UP n|DOWN n` (function `10d8:17e6 -> 10c0:3c74`; state DS:49bd 0 normal / 1 down / 2 black / 3 up). HIDE: all
    zero (no offset), SHOW: normal; both return 0. UP is a no-op (0) in states 0/3, DOWN in 1/2; otherwise a 30 Hz Fade process
    (`1148:1ca5`, step `1148:1de8`) whose handle lives n steps (default 20; unknown word: error 0x69). Step k: scale = (k<<8)/n (UP)
    or ((n−k)<<8)/n (DOWN), out = clamp((src·scale >> 8) + offset); only the newest process writes, and only if DOWN or state ≠ 2.
    UP ends restored (state 0); DOWN ends on the offset-only palette (gamma 50: 6,6,6), state 2. The first step is on the next tick
    (ASSUMPTION). ShowPlayer's old linear guess had the shape right but counted n in 60 Hz ticks (twice as fast).
  - NOT PORTED: `10e8:1dcc` blacks one frame when a camera cut changes the palette by more than 12 on an entry.
- **RUMBLE (`10d0:6dc6`; shift `1140:0ff0` from `1140:1313`, step `11cf`):** presentation only. `RUMBLE`/`0` stops, `RUMBLE n` sets the
  amplitude, `RUMBLE MOVE a b c d` a fixed offset (x, y, previous x, previous y). Shake: spring toward 0 plus ±1 per axis, velocity clamped
  to ±A. Revealed rows are black, revealed columns keep their pixels, alternate row pairs use the previous x. Skipped while paused/frozen.
  ASSUMPTION: the engine's shared LCG (seed·65539+1) is replaced by a dedicated one seeded 0 in both ports.
- **CAPTION (`10d0:16cb -> 10b0:0e5a`):** a real caption, not debug-gated. sprintf over 16-bit words (a second `%d` reads the first arg's
  high word), language filter `1120:03d2`, lifetime 7·len 60 Hz ticks (RED.OPT TicksPerCharacter), replaces the current caption,
  `PAUSE` blocks the caller; other words error 0x127, no string 0x2e, ≥ 351 characters dropped. Colour 0x75 is an ASSUMPTION. The
  only gameplay use is the nurse's syringe (AI_NURSE:186).
- **SET_PTR_MOVEMENT / SET_PTR_PRESS_TIME (`10d0:72b2` / `72ef`):** no-ops before MON_START; they write the pointer object (`1270`).
  MOVEMENT's values are dead or reset at each glide. PRESS_TIME sets press/hold/release in 60 Hz ticks (defaults 14/5/14 from VARS.DEF,
  reset at every MON_START). The ports only store them: the click animation (`1270:01ae..02ef`: `_BUTTON` on the last press frame,
  `_RELEASED` after the hold) and the keyboard glide are not ported.
- **Flics (one global object DS:6538; `1100:0580` draws it instead of the world, full screen):**
  - STARTFLIC (`10d0:7761 -> 1140:0c6a`) opens SHOW/<name>.SHO, interval 2, index 0, draws nothing (black until the first RUNFLIC
    frame, ASSUMPTION). STOPFLIC (`782f`) closes. SETFLICRATE (`7042`) sets the interval in 60 Hz units only while open (no re-base).
    FLICLOOP (`2f64`) is MARK / jump back, not on/off. PLAYFLIC (`10d8:3950`) is a stub.
  - RUNFLIC block [limit] [var] (`10d8:3a40 -> 10c8:0636`) spawns the scene block (stamps SS:TT from the RUNFLIC tick, on the never
    paused clock [8334]) and returns its handle. The scene dies when no flic is open or the flic has finished (`10c8:081b`; the
    engine's ≤ 1 tick delay is 0 in the ports). Timed mode (`1140:077b`): first frame at once, one frame per render every interval,
    limit exclusive: `SETFLICRATE 6; RUNFLIC INTROSPACE 521` lasts 1563 ticks and last shows frame 520. Var mode: frames up to the
    live variable, never backwards, never finishes by itself. The catch-up clock set-back is not ported (interval 1 timed only).
- **JUMPON VAR LABEL (`10d0:4024`, polled in `10c0:2626`):** not a key hook. A per-process one-shot watch on global `_VAR`, checked
  before every statement and every tick while waiting. Non-zero: clear, cancel the wait, jump. Errors 0x29/6/0x17/0x11. All 15
  shipped uses are USERINTERRUPT.
- **CAPTUREKEYBOARD hook (`10d0:1823`, `1138:1da6` from `10e8:11e3`):** the 3-parameter block runs at once for every key event with
  ~0 scan, ~1 modifiers (Alt 0xC0, Ctrl 0x30, Shift 0x0C), ~2 mouse. COMMON's GETESCKEY sets `_UserInterrupt` on Esc, which JUMPON
  turns into the INTRO / PLT0 skip and the AWAKEN quake skip. The ENDGAME movie is not skippable (its capture starts after it).
  The Mac app sends Escape to the hook as scan 0x01 (`KeyBindings.capturedScan`): Escape is reserved and can't be bound, so until
  2026-11-11 the bindings lookup dropped it and the skip never fired in the app (the engine tests fed scan 1 directly). Escape
  outside a capture, a dialog or a monitor is not a case of `FUN_10a8_0541`; the app makes it open the options dialog (as O).
  One entry point `key_event` / `keyEvent(scan:mods:)`. ASSUMPTION: error 0xcf (not a 3-parameter block) is not checked.
- **FREEZE / THAW (`10d0:3314 -> 10c8:04de`, `84c4 -> 05b2`):** suspend every other task (marked in DS:30b8) and set [50be], which
  stops the world update, camera selection and the game clock. THAW resumes the marked ones. ASSUMPTIONS: native handles (sound,
  subtitle, Fade, missile) keep running; resumed wake times and timeline origins move later by the frozen time (INFERRED: WAIT runs
  on the game clock [8330]).
- **Front end:** MENU / UNMENU (`10d0:5396` / `539d`) are 7-byte stubs (all uses in the dead DEMO.scr). EXIT (`2835`) sets [6bda]:
  quit. ADDKEY (`025f -> 11d8:1136/116b`) queues a synthetic key event, delivered at the next step (PIMM's `ADDKEY _HK_ESC` closes
  monitors). WASALTPRESSED (`10d8:3cc1`): `(x & 0xC0) != 0`. GETOPTDATA (`267f -> 10f0:0651`): the INSTALL.OPT value, its integer if
  it starts with a digit, else its first character's code; missing 0. CREDITSSTATE (`1110`): byte [9ce5] (1 scrolling, 2 done,
  set by `1278:1c08`); the roll is ported ("The credits roll").
- **LOADLEVEL: missiles, the volume carry and offsets (2026-11-16, from the code; both ports; spec in `re/out/gaps/LEVEL_CHANGE_SPEC.md`).**
  - *Missiles first.* Before it checks its arguments, LOADLEVEL destroys every missile (`10e0:11aa`, a loop of `FUN_1230_1182(0,0x10c)`).
    A missile whose target is gone runs its HIT block; the rest end with no HIT_WALL: the sound stops, a rider is let go where he is,
    the item is removed and its handle finishes. Ports: `end_missiles_for_level_change` / `endMissilesForLevelChange`. The branch that
    kept a missile in the level's stash is gone.
  - *The volume.* The elevator form looks word 2 up as an IMAG, then a PHYS. Neither: error 0x8b, the caller ends, nothing loads.
  - *What travels.* Every non-player figure whose hull overlaps the volume and every floor item whose EXTENT box does (`1058:173c`,
    inclusive), plus the player always. Held items follow their holder.
  - *Where it arrives.* Each keeps its offset from the volume's point (x, y its centre, z its floor) and is placed at the destination
    plus that offset. Figures go through GO's floor rule and, with collisions on, up to 21 steps of ±204 in x and y toward the
    destination while the area's PHYS says the spot is blocked. Items get a plain SetPos with the velocity zeroed. No destination: a
    dummy at the origin (`1148:1061`).
  - *Scripted run.* The original puts Lex at his offset in ELT, not at its centre; the tower route now walks to TTBATZA first
    (`playthrough_full.py` `tower_bots`).
  - *Not traced:* whether the nudge's PHYS test is exactly the area-scoped hull score the ports use (positive = blocked).
- **Shrapnel (2026-11-16, from the code; both ports; spec in `re/out/gaps/VISUAL_SPEC.md`).** EXPLODE's fragments (`10f8:1ea2`, ctor
  `10f8:124c`):
  - *Pieces.* For first = 0, 10, 20 … while first < N − 10, a piece takes faces first … first + n − 1, n = 1, 2, 3, 4, 5, 1 …, of the
    posed mesh, and starts at the mean of their centres.
  - *Random draws.* Four per piece from the stream script RANDOM uses: vx = R(0,512)−256, vy = R(0,514)−257, vz = R(0,516)−258, then
    R(0,59). The vector is normalised to 256 (truncating) and scaled by 4505. Life: 60·(5−n) + r sixtieths.
  - *Motion.* pos += (v·25)>>8 per axis, clamped in the figure's area PHYS box with a bounce; a z bounce below −0x400 keeps 230/256 of
    vz and plays `_METAL_HITS_<PHYS name>`. Each frame it spins 15° about X and falls 240, with no cap.
  - *Harness.* The draws shift the random stream after every explosion, so later seeded fights play out differently. Gates after this
    change: saves 24/29, control 23/29, seeds 16/26 (before: 28, 28, 19). Every failure looked at is a lost fight, or for seed 4 a bot
    path that only differs on the new stream: with shrapnel off, seed 4 finishes the game.
  - *ASSUMPTION:* all polygons are taken (face types 0 and 4 are not told apart; every TOWERBOT face is kind 6); the look-at frame at
    `10f8:0efe` is not applied (a piece starts in the figure's orientation); `_METAL_HITS_` plays on a bounce on any axis; the
    fewer-than-8-voices check is skipped.
- **Monitor keys, pointer glide and black frames (2026-11-16, from the code; both ports; specs in `re/out/gaps/VISUAL_SPEC.md`).**
  - Glide (`1270:0536`, `064f`, `0891`): MON_SETPTRPOS jumps; MON_SIMULATE and real keys glide: accelerate by 2 to half way, coast one
    step, slow by 2, time step 4 at 30 fps, position by percentage; the distance is ceil(sqrt(|dx|*|dy|)) with a 16-bit product, and an
    overflow jumps at once. Moving the mouse cancels it; a press during a glide animates but is not taken (`[9fea]`).
  - Keys (`1250:0cf9`, jump table `1250:112e`, direction search `1250:0638`), for script monitors and the options dialog alike: Tab /
    Shift+Tab next / previous button; Home, Up, PgUp, Left, Right, End, Down, PgDn try three directions each (e.g. Up 0, 7, 4), keypad 5
    and L the nearest, else the previous or next button; Return and Space press the focused button; Escape presses ESCAPE (and now
    releases it). A right mouse down while input is on presses ESCAPE too. Letters match a button's shortcut char (+0x42, `1250:1166`),
    but only `1278:0894` (button vtable 0xa23c slot 0x20, reached only from `1258:0512`, which no statement calls) sets it, so no
    shipped button has one. Initial focus: the monitor's first button.
  - Black frame (`10e8:1dcc`): with no FADE running, if any entry 0..254 of the pending palette differs from the installed one by more
    than 12 in |dR|+|dG|+|dB| (6-bit), all colours go black, the frame is drawn, then the new palette is set. The ports show one black
    frame (ASSUMPTION: the original's black lasts for the drawing time). LOADLEVEL installs an all-black palette first (`1130:147c` from
    `1148:1a76`), so a level change shows black once too; the boot's (`1150:099e`) is not modelled.
- **Figures on a first visit after a load (2026-11-16, both ports).** The level loader now applies every FIGR record field the resume
  applies (`resume.apply_figure_record` / `applyFigureRecord`: motion, heading, flags, velocity, enemy, avoid list, teeter, z cap,
  foot). On a new game this only changes CONTROL's MARINE1, whose INITGAME record has ATK_STAND, heading 140 and the combat flag.
- **The credits roll (2026-11-16, from the code and live; both ports).** Live (DOSBox-X, `re/out/credits_live`, GOG settings): R from
  a CHAOS save opened the page; CREDITSSTATE [9ce5] went 0 -> 1 at the first scroll and 2 about 7800 ticks of the 60 Hz clock later; the
  text is drawn straight over the live, undimmed scene, which is redrawn every frame; [50be] stayed 0 and the scheduler ran (the game
  is not paused); the roll stops with the last block (BIOFORGE / An Origin Interactive Movie / Copyright ... / All Rights Reserved)
  on screen. Layout and scroll, from the code and fitted to 74 VGA dumps (`re/out/credits_live/SPEC.md`, reference `model.py`):
  - Panel `FUN_1280_221e`: tab stops `_CrCol1..4` (60, 60, 180, 180; a fifth = 180), the CRDT element (0, 0, 320, 200), `[4e3b] = 0x29a`
    (keys locked until the first update), `[a36c] = 1`. Widget `1278:1b47` (vtable 0xa2e8), init `1ba9`: text centre x 160, line gap 1,
    shadow `_Credits_Shadowing` = 2 (down-right).
  - Lines: the stream breaks at `\n`, and a `\n` or `\r` right after a line break is swallowed too (1248:0e09, jump table 1248:0faf), so
    k newlines give ceil(k/2) lines: 251 lines, pitch 12 (height of 'A' 11 + gap 1). `\x02` is not drawn and gives the line the second
    colour: headings 200, other lines 249, font 1, spacing 1. Each line is centred: W = sum(advance + 1) over the line and a trailing
    `\n` (advance of 'A') minus 1, a tab measured as 60 + 1 (x not advanced while measuring), X = max(0, 160 - W/2); drawn, a tab goes to
    the next stop past x, so tabbed fields start at 61 and 181. The shadow is the same string at (+1, +1) in colour 0, drawn first.
  - Scroll (`1278:1c08`, once per dialog frame): position s = 12 T - o; o steps 0 .. -11, then T + 1; the first baseline is at 8 + o, lines
    are drawn until the baseline passes 208. CREDITSSTATE 2 when (+0x453 - +0x455) < T, i.e. at s = 2784 (T = 232), and the picture stays.
    `_credits_frame_ticks` is 128 at run time (GAMEDAT/VARS.DEF; the script source says -1), so the pacing only waits above 120 fps:
    the speed is one pixel per frame (live about 0.4 px per 60 Hz tick; the ports, one per 30 Hz tick).
  - Pause: `10a8:02cc` does not pause for `_OPTS_CREDITS` unless a reload is forced (`FUN_1100_06d4` true when `_forcing_reload` is 0),
    and `221e`, run by the flag and by the main panel's Credits button alike, then calls `FUN_1100_0716` (clears [50be] / [50bf], resumes
    the paused tasks: FREEZE's world stop ends too, its marked processes stay suspended until THAW) and `FUN_1100_0740` (restarts the song
    [4e30] saved at the last non-credits open if another plays). Nothing pauses again: after a visit from the main panel the dialog stays
    over a running game. Close `FUN_1100_0ae6` with [a36c]: CREDITSSTATE 0, then the block CREDITSROLLING on the player (TITLE is loaded
    instead when paused under a forced reload: NOT PORTED, reached only by a dead Lex visiting Credits and then leaving with Escape).
  - The ending: ENDLOOP's `CALL ROLLCREDITS` (`MON_CODE _OPTS_CREDITS`) opens the page during the end flic (02cc has no flic test; the
    ports had one), the roll unfreezes the world, and ENDGAME's WAITHERE loop sees CREDITSSTATE 2, waits 5 seconds and EXITs.
  - Ports: `options.py` `credits_lines` / `credits_pixels`, Swift `Options.creditsLines` / `drawCredits`; the port's frames equal the live
    dumps on every pixel it draws at s = 22, 218, 2046, 2591 and 2784. Not ported: the button's sound release `FUN_1100_0ecc`; with
    High-Resolution Art on, the roll is shown at 320 x 200.
- **Game clock:** FREEZE's [50be] also stops the game clock [8330]. The ports keep `game_tick` / `gameTick` = VM tick minus the frozen
  ticks, read by the log/journal award stamp (and so the saved log lists), the monitor's `%time%`, the attack-combo timer [2958] and the
  ANIMATE texture clock. The scheduler tick and the [8334] flic clock are unchanged.
- **Opening timeline:** with the real FADE waits and the intro movie (FREEZE at tick 0, THAW at 6459), a new game reaches CHAOS at
  about tick 6460 instead of 26, and the intro allocates ~257 VM handles first. The anchor for every opening scenario and test boot is
  now the first CHAOS LOADLEVEL: an old absolute tick T is anchor + (T − 27) (`scenarios.old_ticks`, Swift `oldTicks`). Checked state by
  state against the pre-presentation build at anchor + N: figures, items, process lists, RNG, camera and the logs agree apart from handle
  numbers, the intro's own sounds, the newly modelled FADE / RUMBLE / CHANGEPALETTE / CAPTION effects and the game clock (25 ticks the old
  boot counted before CHAOS are now frozen). The native fixtures' cell boot is 1100 ticks from the anchor; a small intro fixture
  (`stage3b.intro`) holds frames at ticks 20/800/1700/2500 and the intro's sound log. Animated-texture frames still take their phase
  from the absolute VM tick (a port ASSUMPTION), so three checkpoint frames changed with the shift.

## Base and ending playthrough fixes (2026-10-31, both ports)

Found by the base / ending playthrough harness (`re/interp/playthrough_base.py`, findings and blocker list in
`re/playthrough/base.md`); tests in `test_playthrough_base.py` and `PlaythroughBaseTests.swift` (same numbers).

- **LOADLEVEL callers** and **three-word LOADLEVEL**: see "Game start and level changes".
- **Object-local selectors** were swapped in the decode: see the token list (`.` + 4 bytes).
- **INDIVIDUALIZE keeps an object's locals.** The locals live in the object (`10c0:24e1` addresses them at +0x92 + 4n), so renaming an
  item or a figure moves its record (`VM.rename_object`). Before, `RESTOREALIASOFBATTERY` (ITEMS.scr:1274) reset the bike's old
  battery to charge 0 / type 0, and an INDIVIDUALIZEd figure lost its hit points.
- **A level figure's AI name is record data.** `SETAI` (`10d0:6e8c`) copies its word to figure +0x178, CREATEFIGURE seeds it with the
  upper-cased name (`1088:2608`), and the AI start (`1088:33d4-3402`) runs `sprintf(DS:258f, +0x178)`, i.e. `<name>_AI`. The FIGR
  record saves +0x178 (the char[25] 4 bytes before the viewing-camera count; `world.figr_ai_name`): ELITE, AIRMECHO, ROLAND, MECHO2
  ... So `AI ON` starts ELITE_AI after the city scene (EL_SCENE.scr:286) and AIRMECHO_AI after MARCHOUTAIRMECHO (AIRHALL.scr:65)
  with no script SETAI. Saved names that have no block (GRDOP, LANDPAD's MARINE4 `INE4`) start nothing and warn.
- **`CALL ( NAME( a, b ) )`** passes `a, b`: a single parenthesised list after the block name is the argument list (29 call sites:
  CITYMON's `GET_COLOR(n)`, TOWERGUN's `TESTFIRSTHIT( _GN1_FRAME , ~1 )`, ...). The VM used to pass the list as one argument (0), so
  the tower gun could never hit the first lander.
- **A refused MOTION does not block.** `1098:0394` returns 0 while DIE is the current, unfinished motion; `10d0:5e8b` waits only on a
  non-zero handle, so the blocking `MOTION GET_UP_FORWARD` after Mastaba's scene (MASTABA.scr:310) no longer hangs OPRSCENE (and once
  DIE has finished the guard lets GET_UP_FORWARD through: "Movement fixes").
- **A use block that takes Lex keeps him.** Space runs the `_USE` block's first slice at once; when it starts a GO or AI the
  player-input pass now stops (its own entry guard) instead of resetting the motion to STAND (BIKE_USE's `GO HOOD WALK` never walked).
- Not ported, found here (base.md has the diagnoses): room events (`1130:0307-044f`), items with
  duplicate names. (The loop rule for `MOTION ... CONTINUE` is ported: "Movement fixes".)

## Movement fixes (2026-10-31, both ports)

Fixes A-E from the movement research (verified against the disassembly by the main session), in `world.py` / `salsa.py` and
`WorldTypes.swift` / `WorldPlay.swift` / `World.swift` / `Skeleton.swift`, twin tests `test_movement.py` and `MovementTests.swift` (same
numbers), plus the changed expectations listed below. Marks: ENGINE = read from the decompilation, INFERRED, ASSUMPTION.

**D. Stale PHYS cache on a LOADLEVEL inside `step()`.** `load_objects` swaps `self.phys`, but `step()`'s `_boxes` cache (and the area cache
built from it) kept the old level's boxes for the rest of the frame, so `GO FRMZEROG` right after TO_FINAL's trigger LOADLEVEL found no
floor (z -816888 on PLATFORM). `load_objects` / `loadObjects` now clear `_boxes` / `_areas` / `boxes`.

**E. The port-only LAND_REVERT clause of `support` is gone.** `st == 1 and xy and phi.z > lo.z + 0x1000 -> best = max(best, plo.z)` is not in
03f2 (ENGINE). It put the lintel ELVTP4 under Lex's feet in the LANDPAD jetson tube (he slid along JETSON1 and never entered) and made the
TANKS catwalk's FS1-FS3 (POSITIVE) a wall. `0ead`'s own revert (`sup > bottom + 0x1000` restores the previous position) stays. Consequence:
a hull overlapping the xy range of a tall solid by any amount is offered its top, so a *newly solid* PHYS that overlaps a standing figure
(LANDPAD's LEXSTUK, made solid by MARCHOUTAIRMECHO's last line) lifts him onto it (see "Open" below).

**C. GO arrival (`10d0:33c8`, `1098:11c0`, `10e0:1a4c`).** A GO ends when `length2d(target - pos) < radius` (ENGINE): radius 0x266 = 614 units
by default, and the numeric form's fourth number N (cm) when it is non-zero: `N * 2048 // 100` (INFERRED that the named forms never read
that slot). There is **no snap** to the target, in xy or z: the figure holds where its last stride left it, the motion stays, `after_go` /
STAND and the waiting token run as before. The port checks at each motion frame, before the next stride (`advance`), so the final distance
is quantised by the stride (LEX_POS2: 464 units short; an engine that checks every tick would stop nearer the radius edge). A gravity-off GO
keeps its z (GO PELITE puts the Elite's origin at z 1279, GO FELITE RUN moves xy only), so the Elite is no longer buried in PLAT03 and walks to
Lex by itself. Removed with it: `Run.finish_blocked_go` / the `go-arrival` shortcut (GO PRY_HERE ended 100 units short of a wall) and the
base harness's `contact` staging.

**A. Rising ("flag 2") motions: ladders, mantles, iris entries.** `motion_info[name][1] & 2` (header byte 30) is the engine's +0x1e8 for the
motion's duration (1098.c:274): MANTLE_3/6/9, CLIMB_UP, DOWN_LADDER, ON_/OFF_LADDER, CLIMB_SHUTTLE, ENTER_/EXIT_IRIS1/2, ENTER_SHUT2.
- While `Figure.rises`: `settle` skips the fall start, the whoah probes and the stand on the support (no `pos.z = sup + F`), and `set_pos` skips
  its floor snap (10a0:1ff0 needs +0x1e8 == 0). `collision_response` takes the same guard as `raw_setpos` (the same field, INFERRED): the blocked
  position stands, no slide, no restore, and no new mantle. Without that the mover blocks every frame of a mantle (the hull is still below the
  ledge top until the last frames), which is what stopped Lex at the BEACH blocks and the TANKS ledge.
- Commit (1088:1286, ENGINE): at each loop wrap a flag-2 motion adds the last frame's root z R to the figure (`pos.z += R_last`): CLIMB_UP +1121
  per wrap, DOWN_LADDER -1142 (the ladders are scripted loops: `MOTION CLIMB_UP CONTINUE` and a `COORDZ` poll). A once-motion commits its last
  root z when it ends (INFERRED: MANTLE_3 (42, -1078, 1275), MANTLE_6 (419, -1010, 3083), MANTLE_9 (-548, -97, 2792)); the port does it when the
  next motion starts (`set_motion`), so the held last pose and the hull keep the height until then, and MANTLE_* joined `ENGINE_ONESHOTS` (the
  engine's idle fallback returns Lex to STAND at once). After MANTLE_3 Lex stands on the ledge top: pos.z == T + F, no re-mantle.
  STOPMOTION mid-cycle commits the current root z and clears the held pose's own (live: the ladder through the iris, above; UPLADDER's STOPMOTION keeps the climb, and
  `rises` stays set so he is not snapped down). The old hover rule (a gravity-less figure keeps a finished motion's root z >= 100) stays for
  the non-flag-2 motions (NURSEBOT, FIRSTBOT, GUARD1).
- Loop rule (1088:1854, ENGINE; checked on all 227 LEX motions): a motion loops iff its header event list (count at byte 28, entries from byte
  32) holds the 0xfe marker (WALK, RUN, STAND, ATK_STAND, TURN_*, SIDESTEP_*, FALLING, CLIMB_UP, DOWN_LADDER, ...). `MOTION ... CONTINUE` uses it
  (`motion_loops`; `is_cycle` only when a motion has no list), the TAUNT exclusion stays. `salsa.load_motion_headers` / `Motion.loops` carry it.
- Checked on a synthetic ledge (Lex walking north into it): every top from 900 to 1500 above the floor is mantled once with MANTLE_3 and
  he stays on it; with the guard the hull passes through the ledge's box during the climb and `support` (03f2) then offers its top.

**B. FREEZE (`10d0:5e8b`, `10d0:6083`, the MOTION handler).** FREEZE does `+0x34 &= 0x7f` only: it clears the idle-fallback bit. So `MOTION x
FREEZE` blocks like a plain MOTION (only CONTINUE skips the wait), the motion plays to its end, and the last pose is held with no STAND /
ATK_STAND fallback (1088:508d, 1088:4167) until the next MOTION. `Figure.no_idle` is that bit (set by FREEZE, cleared by every accepted
`set_motion`); keys are not gated by it (a fresh press still takes the figure over, as for a held `frozen` pose); `Figure.frozen` stays for
the static hold of STOPMOTION and SNAPTOPOSE. DIE refuses a request only while it is current and unfinished (1098:0394), so after DIE ends
`GET_UP_FORWARD` works (OPRSCENE's soft lock is gone). Effects: the opening has two FREEZEs (STARTUPFIRSTBOT's `DEACTIVATED SNAP_TO FREEZE`,
15 ticks; GOODMORNINGLEX's `WAKE_UP_HEAD FREEZE`, 39), so every opening event from the nurse's ACTIVATE on is 54 ticks later
(`scenarios.FREEZE_SHIFT`; the walk, the zap and the shock-back trajectory of `opening_keys` are unchanged). The PIMM keys open the monitor
only after `LOOK_AT_PIM FREEZE` has played (about 36 ticks). REVIVELEX ends at tick 743 (was 612).

**Changed expectations (all follow from the rules above).** `scenarios.opening_ticks` (+54) for the CHAOS cell anchors (`opening_escape`,
`opening_revival`, the nurse and fight scenarios, `monitor.py`, `play.py AFTER_CHAOS_LOAD` 1143 -> 1197, `test_world` Grounding and
NurseActivation); the Caynan fight is now seeded at its staging point (`CAYNAN_SEED = 10`, a win with Lex at 35 HP; the boot-seeded
stream died at 50 Caynan HP; seeds 1 and 7 also win but Caynan gets up in ATK_STAND, see Open) and `GUARD1_SEED` 3 -> 0 (Easy wins with Lex
at 45 HP, Medium is lost; seed 3 now loses Easy). `LEX_POS2` arrivals end at (-28132.003, -71040.410), AIRMECHO's tick-500 pose moved to
(-6417.207, -71733.868), the closed-door GO ends at y -15969 (579 short of BEYOND_DOOR), TO_FINAL ends at (8566, -123457, 820) (the floor).
The surface harness aims its blaster before combat mode (a 2 degree error misses AIRMECHO at 20000 units). The native fixtures changed only
in the opening-derived runs (tick +54 and the RANDOM stream phase), `landpad_meetmech` (GO), the intro's last tick, and three PIMM frames.

**Open.** (1) A dead figure whose still-running script process issues a `MOTION` after DIE has finished now gets up (Caynan, seeds 1 and 7:
`PLAYER_SUPER_RECOILED`'s tail `MOTION ATK_STAND CONTINUE`, AI_CAYNA.scr:234); traced since: the engine has no lock against it (NOTES "Items and combat").
(2) LANDPAD: `GO LEX_POS2 WALK` stops 464 short with the hull 29 units inside LEXSTUK, which MARCHOUTAIRMECHO then makes solid; `support` lifts
Lex onto it (6500 units). Whether the original's per-tick arrival check ends clear of it is not known (the surface harness re-places him).
(3) The BEACH staircase to ZIP4 needs five more mantles (BLOCK33-35, the drop to 37, over to 27); only the first is driven. (4) The mantle
guard in `collision_response` reads +0x1e8 as shared with the SetPos guard; the engine could clear it between the two uses.

## Room events and the default AI (2026-11-01, both ports)

In `world.py`, `vm.py`, `resume.py`, `level.py` and their Swift twins; twin tests `test_room_events.py` / `RoomEventsTests.swift`.

**Room events (`1130:0114`, disassembly `1130:0250-0503`).**
- At its top the switch writes the camera name to `[63e1]` and its first 3 characters, the room, to `[63e5]`.
- While `[50b8]` is set: if the room differs from `[63ed]` it runs `<new room>_LOAD` (format `[62fc]` -> `1290:6377` `%s_LOAD`), then `<old room>_UNLOAD` (`%s_UNLOAD`, `1290:6424`); then the same for the camera against `[63e9]`. Only then are the names copied to `[63e9]` / `[63ed]` (`1130:0459`).
- Each block goes through `1120:0000` with CURFIG = the player `[2a66]`, no item, run flag 1: its first slice runs at once.
- The gate `[50b8]` is clear only during boot and restore: `1128:0901` until LEX exists (new game) and `1148:0b8a`. Every LOADLEVEL runs with it set. The ports have no such state: a port switch only happens with a level up.
- `1130:0048` (every level load) clears `[63e1]` / `[63e5]` but not the old names, so they survive a level change. LANDPAD and BEACH share room BCH, CONTROL and TANKS share RTR: no room event on such a crossing. A restore fills the old names from the saved camera (`1148:0490`), so restoring it runs nothing.
- `[63ce]`, the current camera, is assigned after the events (`1130:065d`); GETCAMERAAMBIENT inside a `_LOAD` block still returns the old handle (ELH_LOAD).
- ISCURRENTCAMERA (`10d8:2aea`) compares its argument, case-insensitively, with `[63e1]` or `[63e5]`. So a `_LOAD` block already sees the new camera, and `ISCURRENTCAMERA BCH` (the room name, AI_LEX.scr:538) works; the ports used to answer 0 to every room name.
- No shipped script defines an `_UNLOAD` block, so that half has no effect in this game.
- Why the first port attempt broke 10 tests, by cause:
  - `CAMERA BCHZ LOAD` was a logged warning.
  - CE1_LOAD's SPARWITHPLAYER retargeted Lex's enemy in `test_hits`, whose staged spot CE11 accepts (real behaviour; those tests now turn the auto camera off).
  - CE3_LOAD restarts the `_CE31_VOLUME` ramp (`test_audio`).
  - The save test rendered CAYNAN before his first motion.

**Default AI: why HALMECHO never acted.** Not its record and not a room event. Its record is fine: AI name HALMECHO, counter `+0x229` = 0 (read at `1088:3325`, the s16 right after the viewing cameras; 0 in every INITGAME record). PR #16 gave the ports the name but they kept their own `ai_enabled = False` until a script's `AI ON`, and no script gives HALMECHO one. `FUN_1088_3371` tests only the counter, visibility, hit points and "no process yet". The rules now ported:
- `+0x229` is one counter, `Figure.hold`. `AI OFF` is vtable +0x9c (`FUN_1088_3196`): +1, and it **pauses** the AI process (kernel flag bit 0). `AI ON` is vtable +0xa0 (`FUN_1088_31fb`): -1 and unpause, whatever the value; it is refused with hit points <= 0 (`10d0:04b3`, message 0xea). The ports used to end the process at AI OFF and restart it at AI ON.
- `10d0:04b3`: the second word names a figure (`AI ON PLAYER`, `AI OFF MASTABA`) or is NO_STOP_MOTION. The first OFF (counter 1) without NO_STOP_MOTION also stops the figure (`FUN_1098_0789(fig, 1, 1)`, a no-op while DIE is unfinished). A process that turned off its own figure's AI ends its slice (returns 1).
- `FUN_1098_0789` does not clear the idle-fallback bit, unlike STOPMOTION. So a stopped living figure goes to its idle at the end of its next update (`1088:4167` -> `FUN_1098_0745`: `atk_stand` in combat mode, else `stand`). READY_MONSTER_TAUNT waits for that, after CAYNAN's AI OFF. The player's +0xa0 (`10a8:1f2e`) requests the same idle when the counter reaches 0. INFERRED: that this is the player's vtable slot (it calls `31fb` and sits in the player's segment; the table was not dumped).
- The camera switch's show / hide pass (`1130:050d-0546`, all figures but the followed one and the player): not viewed (`FUN_1088_54e0`, an empty list never views) stops the motion (`FUN_1098_0789(fig, 1, 0)`), hides, pauses the AI; viewed again shows and, at counter 0, unpauses. A figure's hidden flag starts from its record (byte 21, 0x04) with no hide event. CAMERAFOLLOW shows the figure it follows (`1130:00c1`, vtable +0x68). ASSUMPTION kept: the ports evaluate this per frame, not only at a switch.
- The level loader builds every FIGR figure (`1148:18d3`); the ports used to create one when a script first named it. They now exist from the load, in record order.
- CREATEFIGURE seeds the AI name with the upper-cased figure name (`1088:2608`) and the counter 0. A name with no block starts nothing, silently, and is retried each frame (`FUN_1120_0000`); the `AI ON: no block` warning is gone.
- ASSUMPTION: a figure with no motion yet is not drawn (the engine draws its model's rest pose; the ports keep no such pose).
- ASSUMPTION (the port's ownership rule): the combat idle ATK_STAND yields to keys like STAND.
- Not ported: `+0x15b` (the task AI OFF can end when its stop flag is set, `FUN_1088_3196`).

Only figures with viewing cameras can start, so this reaches few figures on its own: HALMECHO, CAYNAN, GUARD1 and whatever a script's DEFINEVIEWINGCAMS shows.

**The sentry in play.** HALMECHO_AI starts on the first hallway camera and walks north at about 65 units a tick (Lex runs about 100). A run from DR6 for the elevator vestibule is spotted about 500 units short of it; running on past it under fire killed Lex (46 HP a bolt, 69 HP at the time). The alcove way past it is not solved; the prison harness stages it (`sentry-dodge`).

**Changed expectations, each from a rule above.**
- `test_world`: UNLOAD after LOAD; CAMERA LOAD silent; AI OFF pauses.
- `test_audio`: CE3_LOAD's ramp.
- `test_hits`: auto camera off.
- `test_items`: the shipped save's Lex has counter 1, and a record's hidden figure is no corpse.
- `test_mechanics`: the beast must be on a viewing camera before HIT_LEX; the hide pass stops him on BCH9 (2 ticks earlier).
- `test_movement`: PAD_UP's AI OFF stops Lex at the trigger.
- `test_floors`: AI ON's idle restart moves Lex 4 units on the garage ride.
- `test_missiles`: the hide pass needs a camera switched to.
- `test_playthrough_base`: AI ON's idle after GET_UP_FORWARD.
- `test_playthrough_surface`: BEACH's full figure list.
- `scenarios`: `CAYNAN_SEED` 13, `GUARD1_SEED` 4 (seeds that win; the fights now run with paused rather than restarted AI).

**What moved in the fixtures.**
- Every process handle after CE3_LOAD's MODIFYVAREVERYNTH is 2 higher, so the sound, subtitle and process logs differ only in handles. `VARS.DEF` differs in the three variables that hold handles (`_ce3_modifyvar_handle`, `_subtitle_hand`, `_sfx_4`).
- New events and calls come from the room blocks: CE3_LOAD (CAMERAAUTOACTIVATE), BLK_LOAD (SPARWITHPLAYER on USE_BOT, which sets Lex's enemy), TMP_LOAD and BCH_LOAD (MUSIC, `CAMERA BCHZ LOAD`).
- Figure lists grow by the record figures that used to be created lazily.
- Lex's positions in the opening are unchanged at every tick. His STAND runs one frame behind after AI ON's idle restart, and he stands instead of finishing SHOCK_BACK's hold. DR_ZAP3_FIRSTBOT's AI ON also ends DROPSHIP_WINS, so `nurse_push`'s recorded keys take effect earlier (ticks 5912-6173, 6187 at the end).
- The nurse keeps animating ATK_STAND while her AI is off (the idle request) and resumes rather than restarts, so her heading at the last tick of `opening_revival` differs.

## Items and combat (2026-11-01, both ports)

Twin tests: `re/interp/test_items_combat.py`, `native/Tests/BioForgeCoreTests/ItemsCombatTests.swift`.

**The item list.** DS:1d0d (count) / 1d15 (pointers); new items are appended (`1050:10bf`). Item fields: +2 type (exact, 9 bytes), +0xb position, +0x2c holder, +0x30 limb record, +0xf7 instance name. Nothing keeps names unique.
- `CREATEITEM` (`10d0:21c8` -> `1078:0130` -> vtable +0x6c = `1070:088e`, passing +2): the instance name is the type. The ports' `FORK_2` renaming was invented and is gone.
- `INDIVIDUALIZE` (`10d0:3e87`, +0x6c) overwrites +0xf7 only. List position, locals and other processes' CURITEM pointers stay.
- `SETCURRENTITEM` (`10d8:3ac8` -> `10c0:3fd9`; only the first word counts, `(CAYARM, CLOSEST)`'s second is ignored):
  - `RTHAND` / `LTHAND` (DS:3023 / 302a) needs CURFIG and takes `1088:5669`'s first held item.
  - Any other word walks the whole list, with no holder test and missiles included. A candidate matches on type or instance. The smallest exact 2D distance from the player's +0xb wins, the first on ties.
  - Not found: returns 0 and **CURITEM stays**.
- `ISCARRYING` (`10d8:2845`): `INVENTORY` (DS:46cf) and `ANYWHERE` (DS:46d9) run that same search with the second word, then restore CURITEM. So they ask about the *nearest* item of that name: holder == CURFIG, and for INVENTORY also no limb. Any other first word is a hand: `1088:5669` with **type** == the second word.
- Object argument by name (`10c0:16a8`): figures, then `1050:0f34`, the first item whose **type** matches. The scripts only ever pass CURITEM there.
- Port store: `World.items` keeps list order under a unique key, `Item.key` = the name when free, else `NAME#2`, ... `proc.cur_item`, `vm.objects`, pick targets and monitor list entries hold the key; block names and text use `item.name` / `item.type`. `add_item` and `rename_item` are the only writers; a rename keeps the dict position and updates every process.
- Consequence: the bike's old battery and the Elite's are two `ABAT_500` with their own locals (150 and 500), so the ending works in real play order.
- Limit: `export_state` patches level ITEM records by key, so a duplicate created at run time is not written to the port's own saves (as `FORK_2` was not).

**Item position and hull.** Each tick `10f0:12c3` -> `10f0:1209` runs for every object with a holder, holder first. Holder vtable +0x4c (`1088:5c19`) gives the limb origin (`1038:035b`) if the holder has the +0x30 limb, else the holder's +0xb (inventory: `1138:1274` freed +0x30). Item vtable +0x2c (`1078:08f6`) writes +0xb and the hull +0x65 = `1058:0f95`(pos, box +0x39). The box is EXTENT (`1070:08df`): +- cm * 2048 / 100, not rotated; no EXTENT is a point.
- `AMINTRIGGER` / `AMINEXTENT` / `AMINWAYPOINT` (`1070:0aba` -> `1058:173c`, inclusive) and COORD*, DISTFROM* use this for items, through `item_engine_pos` and `object_hull`. ASSUMPTION: computing it on demand equals the value `1209` wrote this tick.
- `1138:088d`: an attach uses the item's HANDEDNESS limb, or the holder type's `MY_HAND` if the holder has no such limb (NURSEBOT: UP_ARM). `1138:036e` counts lthand, rthand and MY_HAND as "holding".

**`MOTION ... CONTINUE`: closed.** Under the 0xfe rule (`1088:1854`) PUT_BATTERY and TWR_VICTORY play once; all 227 LEX motions carry an event list, so the `is_cycle` fallback is never used for Lex.

**Death and the motion request.** No hit-point, dead-flag or +0x229 test exists in `10d0:5e8b`, `1098:0e49`, `1098:12bd`, `1098:0394` or `06e0`.
- At hp <= 0 (`1090:09b9`) `<TYPE>_WOUNDS`, the die method and `<INSTANCE>_DEATH` run. Only the AI process is suspended and the per-motion event process +0x15b killed. Other processes on the figure keep running.
- `1098:0394` refuses any motion change while DIE is current, by name, with no SNAP_TO exception. A motion that reached its last frame is no longer current (`1088:2035` -> `0789`; decompile only). INFERRED: SNAPTOPOSE takes the same route (`10d0:76xx`); its pose-at-frame follow-up after a refusal is not ported.
- `1098:12bd` (scripted MOTION, not NO_SCRIPT): while a task and name +0x15f exist, refused if the name equals the request or starts RECOIL / DIE / SUPER_REC. Refused = a zero handle, no wait. A same-name re-request therefore does not restart the pose, which moved the Guard 1 fight (`GUARD1_SEED` 0 -> 4).
- `10d0:04b3`: AI ON at hp <= 0 is a warning only. ASSUMPTION: a figure with no object record counts as alive (a lazily made PLAYER in `landpad_meetmech`). `1088:508d`: no idle at hp <= 0. `1090:0e36`: the player's killer gets the die method too.
- **Open: there is no corpse lock in the engine.** After DIE has ended a stray process's MOTION is accepted. `PLAYER_SUPER_RECOILED` (AI_CAYNA.scr:203-235) runs as its own process on Caynan with no alive check, so if he dies during the taunt or PAUSE_FOR_SUBTITLE and DIE ends first, `MOTION ATK_STAND CONTINUE` stands the corpse up (the trailing `AI ON` is refused). The ports now do what the code does. Whether the original ever shows it depends on subtitle length against DIE length: not observed live.

**Bots: fire rate, damage and armour are faithful; `TURN` was not.**
- Fire rate: `_easy_wait` / `_medium_wait` / `_hard_wait` = 45 / 30 / 15 (VARS.DEF:969-971), WAIT twice per shot (BEACHBOT.scr:191-219): one bolt per 90 / 60 / 30 ticks per bot. Measured in the port: 61 on Medium. Three bots give 7.4 bolts in 150 ticks, the observed 8 hits.
- Damage: `NRLASER_HIT_LEX` = `DAMAGE_LEX_ENERGY 10`; `1090:0ac6-0add` adds 4 * level for the player (level 0: -4), so 6 / 14 / 18. The armour step (`1090:0bd6-0bf7`) matches, and HARD has `ENERGY_ARMOR 0` (FIGURES.scr:439-456), so the suit stops nothing. No script local absorbs a hit. A standing Lex dies in seconds in the engine too; bolts take 40-250 ticks to arrive, so moving dodges them (INFERRED: no live capture of a bot shot).
- Hit test: `1110:0b29` / `1058:1684`, inclusive box overlap with the first non-hidden figure in list order; matches the port.
- `TURN n` (`10d0:8841`, `8c27` -> `10a0:19e6`(fig, n << 8)) is n degrees in 24.8 (0xb400 = 180, `10a0:1bff`), the auto-turn's routine and sign: positive turns left, ANGLEFROMENEMY's sign. The port's `heading += 2 * n` was a guess from a script comment and ran away under `TURN ANGLEFROMENEMY ()`. That is why AIRMECHO's BOLTGRN never reached Lex: the first bolt missed by about 3400 units and the heading then diverged. Fixed: `heading -= n`; `BOLTGRN_HIT_LEX` now runs about 70 ticks after the first shot.
- Consequence: the AIRMECHO duel is lethal. By keys: two lasers connect (125 -> 94 -> 63 HP), RECOIL_ML costs about 27 ticks a hit, the camera leaves HFR3 / HFR6 (ELV3, tick 1112), AIRMECHO is hidden from then on so lasers pass through, and Lex dies at about tick 1300. Open: unchecked against the original (the view_cams hiding rule); the surface harness stages the fight's hits.

## Area trigger lists are built with the level (2026-11-01, both ports)

Found by the full playthrough (re/playthrough/full.md). `World.area_triggers` / `World.areaTriggers` (RoomType->triggers of the area anchored at a PHYS, `FUN_1138_131c`) built each list on its first
query from the anchor's *current* box. PHYS boxes move (`SETFLOOROFPHYS`): the garage lift's first query came while LOWER_GARAGE_ELEVATOR had raised ELV to `-633` (z -162048..-146988, no longer touching
TAKEMEUP at z -165153..-164129), so the list stayed empty, TAKEMEUP never fired and the lift never came back up. INFERRED (the lists are a field of the area record; `FUN_1138_1853` has three call sites, `1148.c:888`, `1068.c:629`, `1068.c:691`, none in the SETFLOOROFPHYS handler; not checked live): the original builds
them when it builds the areas, i.e. with the level; both ports now fill every anchor's list in `load_objects` / the level load. Twin tests: `test_floors.AreaTriggers.test_a_moved_anchor_keeps_the_triggers_it_touched_at_load`,
`FloorsTests.aMovedAnchorKeepsTheTriggersItTouchedAtLoad` (ELV keeps CAM_SHO5 x3, CAM_SHO1, TAKEMEUP, MSENTER after the move). No fixture changed.

**Found, not fixed (re/playthrough/full.md, ranked):** `LINKMETOCAMERAS` paused nothing (since fixed: "Camera-linked processes"); the step-up of `collision_response`
(`10a0:0ead`) does not see QST2 from QST3 (the garage lift recess); the ladder up out of TANKS ends inside the open iris hatch (since fixed: "Garage recess and the ladder top"); M1TONFA lies where there is no floor when the first lander is dead. A weapon does exist on the way: GRDHALL drops BLASTER2 (AI_GRDHL.scr:332-350); the harness does not kill GRDCON, so GRDHALL never appears.

## Next steps

1. Face lighting is resolved (intensity 0, ramp start; see "Face lighting"). Depth haze is
   resolved too: the engine opens `PALFADE.IFF` but never applies it.
2. Grounding and movement collision share the recovered hull (20.48 units/cm,
   bottom at −s from F). Movement selects a PHYS area and its ordered members and uses the
   original's fixed-point score, support lift, stepping and wall response; a closed-door walk
   matches the original live; living figures push each other apart (`FUN_1088_3629`), and IMAG
   triggers fire with the mover's InTrig stop ("IMAG triggers"); `STOPMOTION` holds the pose.
   Hidden figures (FIGR flag 0x04 skips the whole per-frame update) are ported (see "STOPMOTION and
   hidden figures"); the `FUN_1070_224c`/`2264` show/hide callers and the `_HIDE`/`_UNHIDE` block
   event remain unrecovered, with no current content depending on them. Rendered frame interpolation
   is ported; the motion-start blend is sub-frame at 30 Hz and remains unmodelled. Remaining: the
   player's `AUTO_TURN_SPEED` auto-aim (`FUN_1088_3419`), and the fall/landing branches of
   `FUN_10a0_0ead`. Complete the inventory controls needed beyond the opening scene; the
   original player key map is wired.
3. Remaining engine commands as scenes need them (CAMERA SHOW, a presentation form), ITEMs and monitors.
4. Audio: done apart from finer live MIDI timing (GM notes go out on the 30 Hz app tick).

## Persistent velocity (both ports, 2026-10-22)

Spec and disassembly: `FUN_1088_384e` (velocity -> step), `1088_39ef` (frame update), `10a0_22e1` (mover), `10a0_0ead`,
`1070_0fa7` (rebound), `10d0_7493` / `787c` / `42c4` / `84d0`, `10d8_3c04..3c82`. Python: `world.py` (`velocity_step`, `scale_step`,
`World.frame_move`, `mover`, `move_and_respond`, `bounce_collision`, `bounce`, `leap`, `orientation`); Swift: the same names in camelCase (`velocityStep`, `scaleStep`, `frameMove`, `moveAndRespond`, `bounceCollision`, `velocityFigure`) in `World.swift` / `WorldPlay.swift` / `WorldCombat.swift`, tests `VelocityTests.swift`.
- **Velocity** vx, vy, vz (+0xc6/+0xca/+0xce, s32, units per 30 fps frame) is persistent: no friction or damping anywhere. Writers: gravity,
  knockback, `SETVELOCITY`, `LEAP`, the rebound; zeroed by SetPos (also the step), `STOPVELOCITY`, every non-bouncy collision response.
- **Frame update** (`39ef`): gravity (falling && gravity flag && vz > −0x500), then ONE mover call per frame with target = root after root
  motion + step, where step = `0c42`(v, `0c24`(0x1e00, max(1, (0x3c00 // [83a0]) << 8))) per axis (`0c24` truncates, `0c42` floors; the step
  equals v at 30 fps, `[83a0]` = 512). It applies to figures without the gravity flag too. The port accumulates the frame's root motion in
  `advance()` and `settle()` makes the single move (a GO stride that reaches its target is applied when that move completes, and the
  tick now runs `settle` right after the motion frames instead of after the hit test and auto-turn).
- **Mover** (`22e1`): last good := position at entry; 3D delta; blocked step i of n rescales the step by trunc(c·i/n); a failed final check
  leaves the figure at the target. The +0x14e z cap (FLOATATHEIGHT ... MAXIMUM) is applied first (see "CHAOS encounters"). NOT PORTED: the
  attached branch (+0x2c).
- **Rebound** (`0fa7`, bouncy figures; entered from `0ead` with step := position − frame start, falling cleared): P = blocked position;
  candidates X, Y, Z, XY, XZ, YZ = P − step on those axes (step re-read per candidate), each through the mover from wherever the previous
  attempt left the figure; accepted when the hull bottom is strictly above the support and the PHYS score is clear; the accepted axes
  of the velocity are negated. The fallback calls the mover with a pointer to +0xe2, which the mover overwrites with the current position
  before reading its target: the figure stays where the YZ attempt left it, all three components negated. Always after: v and step
  −= floor(v·E/256), E = ELASTICITY (+0xde; FIGURES.SCP by instance name, default 200; FIRSTBOT 0, LEX 50, FIDO/HALMECHO/CAYNAN/GUARD1 150),
  and `_<TYPE>_BOUNCE` plays when it exists. A falling figure that bounces off the floor stops falling, so it rises at constant vz.
  The 3 captured nurse wall contacts (`nurse_bounce.json`, original data, untouched) still match exactly.
- **Knockback** (`09b9`): v −= attacker row 1; row 1 is the BACKWARD vector, so the target is pushed away from the attacker (the old ports
  subtracted forward(), pulling it in). `World.orientation` gives the row from the heading through the FK table (ASSUMPTION for a pure yaw).
- **Statements**: `SETVELOCITY obj vx vy vz` raw s32; `STOPVELOCITY` zeroes velocity and step; `VELOCITYX/Y/Z(obj)` return the low 16 bits
  (UNCERTAIN: sign-extended here, as the VM's 16-bit values are elsewhere; round-trips while |v| < 32768); `LEAP obj [target] pitch speed`:
  v += row 1 · k with k = (speed << 11) / 100 (signed, truncating, 20.48 units per cm) after an X rotation by pitch degrees (row 1 tilts
  toward row 2). Self mode adds along the backward row (positive speed pushes backward); target mode builds row 1 = normalised
  (target − object). UNCERTAIN: the cross-product order of `1208:0154` for rows 0/2 (only matters for a pitch with a target; shipped scripts
  use pitch 0) and the ±0x38 renormalise after the rotation (not modelled). Items carry velocity too since 2026-10-31
  (`THROWCURITEM` and the item forms: NOTES "Flat objects, EXPLODE and THROWCURITEM").

## Nurse bounce and defeat port (2026-10-20)

`BOUNCINESS` (token 0x72, `FUN_10d0_0ab2`) toggles figure flag 0x10. Created
figures start from `IS_BOUNCY`; level and resumed figures use the saved flag. Python
and Swift now preserve that state. (Persistent x/y/z velocity, `STOPVELOCITY` clearing all of it,
`SETVELOCITY`, `LEAP` and the generic rebound are in both ports since 2026-10-22, see "Persistent velocity".)

The nurse's wall response does not reflect its heading. `FUN_10a0_0ead` copies
blocked position minus frame-start position into +0xd2/+0xd6/+0xda, then calls
`FUN_1070_0fa7`. That routine tries axis rollbacks X, Y, Z, XY, XZ, YZ, then a fallback that
(through the aliasing of `&last_good`, see "Persistent velocity") leaves the figure where the YZ attempt left it. Each candidate must have its hull bottom strictly above support
and a clear PHYS score. It negates the corresponding persistent velocity components
(+0xc6/+0xca/+0xce) and applies loss from +0xde. The Python port now runs the generic 3D
rebound (six candidates through the mover, velocity negation and ELASTICITY loss; the old bounded XY rollback is gone) and leaves
heading untouched. The authored turning `BOUNCE`
motion changes heading over its cycle. Fresh original sampling confirms FIRSTBOT velocity zero and
loss coefficient zero before the bounce; the new sampler also records frame start,
last good position and movement delta for collision-response comparisons.

`SPARWITHPLAYER` is token 0xc2 / `FUN_10d0_76c9`, distinct from `DEFINEENEMY`
(token 0x8b / `FUN_10d0_265a`). Spar writes both target pointers: the nurse targets
Lex and Lex targets the nurse. Both ports previously only set a spar boolean, which
left Lex's enemy unset in the opening and caused real punches to miss without a
fixture target assignment. The reciprocal link is now implemented. The separate
incremental nearest-target scan (`FUN_10a8_1dce`, limit 0xc80, one candidate per call)
and player auto-facing still need full recovery/porting.

Fresh read-only Ghidra decompilation (`re/decomp/1090.c` and `re/decomp/10f8.c`) shows
`KILL` → `FUN_1090_135a`: local 0 becomes -666; the figure leaves the active figure
and object lists and enters a deferred-destruction list. The ports now remove the
active figure, stop its AI/positional sounds, clear motion destinations/avoidance/
triggers, and prevent lazy recreation from level definitions. The issuing script
continues. An explicit `CREATEFIGURE` can create a new instance with the same name;
`SETCURRENTFIGURE` reports a retired instance absent. `EXPLODE` → `FUN_10f8_1f8a`
uses the model to create debris; that visual effect remains unimplemented (the wait and the hiding are ported, see
"Flat objects, EXPLODE and THROWCURITEM").

`opening_nurse_defeat` now runs the opening, C and Alt+KP8 inputs, front and rear
pose fixtures, the authored wound/bounce block, then a logged bar-contact fixture
and `DR_ZAP3_FIRSTBOT` through `_BOT_BLOWN` and figure removal. It does not force
health, wound flags or the defeat global. This regression proves those script and
input paths; natural player pushing to the bars is not yet established.

Persistent automation additions: `variables` reads the script manager's +0x10
count and +0x12 far pointer (manager at DGROUP 0xcae6), 29-byte records consisting
of 25 name bytes and a signed value. Live values for `_BARS3_ON`, `_BOT_BLOWN`,
`_CELL3REPAIRNEEDED` and `_BR3_FRAME` were verified. `frames` now skips hits for
other instances sharing the selected update wrapper, within the same timeout.
An owned controller rejects bare `quit`; explicit `stop_emulator=true` is needed
to close its emulator. Attach-mode quit retains its disconnect-only behavior.

Original wall capture `re/out/nurse_validation/wall_frames.jsonl` contains 42 collision
responses across 60 nurse updates. All 42 match Python exactly at the observed poses,
including captured hulls and unchanged base heading. Three representative samples are
checked into `native/Tests/BioForgeCoreTests/Fixtures/nurse_bounce.json` and replayed by
both Python and Swift tests. This is a collision-response oracle, not a free-running
trajectory comparison.

Turning motion cycle detection now ignores root-limb yaw when comparing endpoint poses,
so the authored BOUNCE clip keeps looping. Other limb differences still distinguish
START_BOUNCE from a cycle. CONTINUE never blocks its caller, even for a noncyclic clip
(`FUN_10d0_5e8b`); a completed, unfrozen player pose yields to fresh control input.

AI startup correction: `AI ON` (`FUN_1088_31fb`) enables AI, while creation of
its process belongs to `FUN_1088_3371` during a visible, living figure update.
The port previously spawned immediately. During opening tick 26, READY_CAYNAN
briefly sees BLK4 before the caller selects CE31; deferred startup leaves hidden
Caynan pending. This prevents its shared `_enemy_process` writes from restarting
the nurse zap. The regression now checks exactly one zap process and guard value 1
throughout defeat. Restored active AI tasks retain their link and enabled state.
AI OFF still kills the port process; the original's suspend-counter/resume behavior
remains separate work. No speculative suspension of already-running hidden scripts
was added.

The original input-driven push experiment now reaches `ZAPPED` at clock 7325,
FIRSTBOT removal at 7843, and Lex health 100. `push_feedback.jsonl` logs the starting
pose fixtures and 60 steering actions; `push_direct.jsonl` logs 15 further actions
with no pose edits. `push_defeat.jsonl` observes completion. All are under
`re/out/nurse_validation/`. This is a route from staged positions, not an unassisted
opening-spawn encounter. `dosbox_control.py push` packages the direct steering
algorithm with a bounded attempt count and health-loss stop; its CLI wrapper has
protocol tests but was not rerun on a fresh nurse after the recorded run consumed
the encounter.

`dosbox_control.py escape` passed in the same original session: clock 8852,
BLK1, XY(-10129,-16932), Lex health 100, no setup edits. It aligns before the doorway,
waits for a fresh `_BARS3_ON` on-to-off edge, and runs through the four-second off
window. It stops after the first damage/shock. The Python nurse scenario now also
crosses to BLK1 at health 100 after its staged bar contact. Short prototype turn taps
must advance at least one yaw-changing pose; the scenario uses a 0.2-second minimum
rather than repeatedly cancelling the same initial pose. Natural player pushing
parity in the port remains open.


## Input-driven nurse regression (2026-10-22)

`opening_nurse_defeat` no longer places FIRSTBOT at the bars. Its only pose edits
are the logged front combat setup at tick 1162 and rear setup of Lex at tick 1205.
From the rear wound onward, the authored scripts, ordinary turning/walking/running
keys and normal world updates take the nurse into DR_ZAP3, play ZAPPED, retire
FIRSTBOT, and let Lex cross to BLK1 at health 100. The route preserves the recovered
`FUN_1088_3629` separation and `FUN_10a0_0ead`/`FUN_1070_0fa7` wall response;
no new physics change was needed for this regression.

The bounded steering loop keeps Lex on the far side of the nurse toward the bars.
Six-tick turn holds allow the turning pose to change yaw, and an 18-degree heading
window avoids alternating turns without forward progress. The deterministic route
uses 600 steering actions and 626 total key events, reaches nurse retirement at tick
7345, and finishes in BLK1 at tick 7775. The zap trigger is entered, only one
DR_ZAP3_FIRSTBOT process runs, and its guard remains 1. Scene images and the full
input/geometry log are in `re/out/natural_push/`.

`native_fixtures.py` writes `Fixtures/nurse_push.json`: the two explicit setup
records, the key schedule, and three expected checkpoints, with no embedded game
assets. `NursePushTests` replays that schedule in Swift and compares figure lists,
positions, motions and cameras at the checkpoints, plus zap, retirement and health.
All 167 native tests and all six Python scenario tests pass.

This establishes an input-driven post-wound route in both ports, not an unassisted
opening-spawn encounter or exact trajectory parity with DOS. The earlier successful
original push used additional starting poses near the bars. A fresh original-game
front/rear attack check also passed at full health in
`re/out/natural_push_live/front_rear/`; its first direct steering attempt stopped
at the safety boundary without a zap (`push/report.json`, 50 actions, health 100).
That exposed the test driver's tendency to get on the door side of the nurse and
push it away from the bars. Further original-game steering experiments remain
separate from the passing port replay.

## CHAOS encounters: Caynan and Guard 1 (2026-10-23, Python and Swift)

Scenarios `chaos_caynan_fight` and `chaos_guard1_fight` (`scenarios.py`, tests in `test_scenarios.py`, engine tests
`test_world.ChaosEncounterEngine`) take the next two CHAOS fights end to end with real keys.

**What runs.**
- CAYNAN: `READY_CAYNAN` -> `CAYNAN_AI`. The IMAG triggers `RESET3` / `OUTSIDE3` / `INSIDE3` set `_Caynan_State` 0 / 1 / 2
  (pace and eat meat / `CAYNAN_GREET` / fight: `SPARWITHPLAYER`, `MONSTER_MOVE 15`, `ATK_M*` or a random `ATK_H3/6/7/8/9`).
  The way in is not a puzzle: `_Cell1RepairNeeded = 1` (VARS.DEF) makes `CELLONEBARS` drop the cell-1 bars alternately for 61
  and 21 ticks (edges at 62, 123, 161, 182, ...); a run through DR_ZAP1 inside a window is unharmed, outside one `DR_ZAP1` shocks
  (`ZAPSOMEBODY`, 15-20 energy). The BLK hall (y < -18000) joins the pockets in front of every cell; no door is involved.
- GUARD1: cell 2 is entered by `TANKTOCELL2` (`LOADLEVEL CHAOS TNKS_ARV`, `CALL ENTERCELL2`). Nothing in the scripts calls
  `TANKTOCELL2`, so the scenario starts it (logged as staged); CRYTOTNK.scr is in CHAOS.LVL, so `TANKTOCELL2` survives its
  `LOADLEVEL` and calls `ENTERCELL2` itself. `ACTIVATE_GUARD1`'s first call `PROCESS GREET_GUARD1` already sets `_GRD1_Awake`, so the
  `WAKE_UP` / `GET_UP` branch of ACTIVATE is dead (the original runs the first slice at once too).

**Outcomes** (deterministic; the keys are C, Shift+Up / Up holds, KP4 / KP6 turn holds, KP8 and Alt+KP8 = ATK_H8):
- Caynan, Easy (`_difficulty_level` 0, logged staged): Lex wins with 9 recorded hits on Caynan (one `BLOCKED`), Caynan lands 5, Lex ends with
  17 HP; `CAYNAN_DEATH` runs (music `_CELPANEL`, DIE, taunt, growl). At Medium (1, the opening's choice) Lex dies after 8 recorded
  hits (two `BLOCKED`, Caynan 74/200). The difficulty term of `FUN_1090_09b9` (+4 per level on a player target, -4 per level
  on others) and Caynan's 200 HP with no armour are the reasons, not a missing rule: Lex needs 10 hits (21 each) against 5 of Caynan's.
- Guard 1, Easy: Lex wins with 68 HP, 5 landed punches; `GUARD1_DEATH` -> `DOTHELEXTHING` run to the end (uses
  `DISTFROMWAYPOINT` / `ANGLEFROMWAYPOINT`). Medium: Lex dies (guard 68/100). The guard hits twice before Lex can act (Lex's
  `TAUNT2` from GREET_GUARD1 lasts longer than the two subtitles that precede `AI ON`).

**Recovered and ported** (decompilation `re/decomp/10d8.c`, `10d0.c`, Ghidra disassembly for the rest):
- Distance functions convert world units like this (`10d8:1278`, `16a6`, `0534`, `0e28`): `cm = (units * 100 + 0x80) / 0x800`
  (signed long divide), i.e. units / 20.48, the inverse of `hull_units`. This replaces the earlier `units / 20` assumption of
  DISTFROMENEMY (2,000 units = 97 cm, not 100) and the STAND-pose-extent guess of ATTACKRADIUS, which is the current figure's
  PERSONAL_RADIUS (+0x1e3, Lex 40, Caynan 43, FIRSTBOT 55). `cm_from_units` in world.py, `cmFromUnits` in Swift. **Both ports
  use the new numbers.**
- `DISTFROMWAYPOINT` (`16a6`): 3D, `FUN_1208_13e3` = `approx_length` of the object's +0xb position minus the waypoint's (WAYP list
  `1290:1cdd`, position by vtable +0x50). `2DDISTFROMWAYPOINT` (`0534`): `FUN_1210_000d` = `length2d`. `ANGLEFROMWAYPOINT` (`0d10`):
  vtable +0x60 of the object on the point, the ANGLEFROMENEMY bearing. `AMINWAYPOINT` (`0905`): `FUN_1070_0aba`, the hull box against the
  point (waypoints have pos == pos2), inclusive like AMINTRIGGER. The object is CURFIG, CURITEM or a name (`FUN_10c0_16a8`); items
  support the two distances only. `World.waypoint_query`.
- `AMBIENT` (`06b2` -> `10c0:32e1` -> `1100:1ae1` / `1a15` -> `1028:0f0a`) is `SOUND` (`31e0` -> `196c` -> `1028:09d3`) with the voice's
  loop flag (+0x1d) set and the sample's loop points used. `STOPAMBIENT` (`10d0:777a` -> `1028:10c9`) releases a looping voice (the
  sample plays out) and leaves other voices alone; `STOPSOUND` (`0ddc`) stops at once. SOUND is one-shot even for a sample with loop points (`09d3` clears the flag); AMBIENT loops, and STOPAMBIENT lets the loop play on to the end of its sample ("Released loops play their tail"). Used by `DR_ZAP1_CAYNAN`, `ZAPSOMEBODY`, `BLK4_LOAD`.
- `APPLY obj mode texture [PICTURE n [prefix]]` (`10d0:0843` -> SCANNER.C `10f8:08a9`): the texture decal system. A scanner walks the
  model's textures (the name, or ALL); `10f8:0712` switches on the mode (names at `1290:4ce8`: DRAW, DRAWONLY, RESTORE, CLEAR). DRAW and
  DRAWONLY restore the texture from its backup (`1168:027c`, backup made on first use by `0019`) and draw frame n of the picture FLIC over
  it; RESTORE only restores; CLEAR backs up, fills with 0xff (`10f8:04ab`) and draws. The FLICs (`CAY0PIC.FLC`, `GRD0PIC.FLC` ...) are
  not in the shipped data, so the port keeps the state only (`Figure.decals`, `World.apply_decal`, texture names from the EOR TXMP chunks)
  and does not render it: a CLEAR without its picture would make the hands vanish. Open: the picture FLIC resource.
- `SETCURRENTFIGURE` (`10c0:3e14`) matches the instance name (+0xf7), then +0x178 (upper-cased copy of the creation name at +2, written
  by `1088:2608`) and +2: so `SETCURRENTFIGURE (GRDCELL)` finds GUARD1 after `INDIVIDUALIZE CURFIG GUARD1` (`GRDCELL_WOUNDS`,
  `GUARD1_ENTER_COMBAT`). `World.figure_by_type`, ASSUMPTION that +2 is the FIGR record's type name.
- `ATK_M5` (GUARD1_AI case 5) never fires (`MONSTER_MOVE` returns 0, 4, 6, 8 or 10 only). A `MOTION` with a missing name
  (`10d0:5e8b`): vtable +0x7c starts the motion by name and returns a task handle, 0 when the name does not exist; the caller waits
  (`FUN_1238_0f48`) only when the handle is non-zero and CONTINUE is absent, so a missing motion starts nothing, does not block and
  returns 0. The port already does exactly that (warning `<type> has no motion X`, no motion change, no wait).

**Port behaviour added to make the fights run** (all ASSUMPTIONs, commented in world.py):
- A combat-mode non-player figure whose one-shot motion ended returns to a lower-case `atk_stand` (`READY_MONSTER_TAUNT` waits for
  `ISMYMOTION("atk_stand")` after the attack; without it the guard's taunt never ended).
- `MOTION TAUNT1..4 CONTINUE` plays once (TAUNT2's first and last pose are identical, so `is_cycle` made Lex taunt forever after
  `GREET_GUARD1`). Since "Movement fixes" the loop rule is the header's 0xfe marker, which the taunts lack; the GESTURES exclusion stays.
- A MOTION deferred behind a GO (`after_go`) is released when the GO is cancelled (a hit, STOPMOTION, a new GO or pose); `CAYNAN_AI`
  hung in `MOTION ATK_H8` otherwise.
- STOPMOTION / a hit's motion cancel no longer blocks the player's keys (`Figure.stopped`; only FREEZE does): `DAMAGE 15 ENERGY` from
  the bars froze Lex for good.
- The final root z of a finished motion is carried only if the motion started with gravity off (`hover_motion`): GUARD1 sank 1780 units
  into the floor after `WAKE_UP`.

**Unmodelled calls the encounters hit** (`World.unmodelled`, listed in every scenario manifest as `unmodelled`; a separate list because
the opening alone drops about twenty names and existing tests assert exact warnings): FREEZE, GETOPTDATA, STARTFLIC, SETFLICRATE, JUMPON,
SETSOUNDCACHE, BANKINSFX, FADE, RUNFLIC, STOPFLIC, REVERTSOUNDCACHE, THAW, INCVIRTUALSECONDS, RUMBLE, MODIFYVOLUMEOVERTIME, CHANGEPALETTE,
MAKEFLATOBJECT, EXPLODE, ADDTOPITCH, ANIMATE, FORCERELOAD (presentation and startup); and the ones that change behaviour:
`FLOATATHEIGHT`'s single-argument form (below). Plus the known VM warnings: `CAYNAN_PACE` `BREAK 2` and
`LUTHOR_ATTACK` `BREAK 1` (a one-switch block; `BREAK n` numbers a block's switches from 0, the port breaks the innermost).

**Last gaps, recovered and ported** (`10d8.c`, `10d0.c`, Ghidra disassembly; ports `World.compass` / `motion_heading` / `am_in_extent` /
`cmd_floatatheight`, Swift `compass` / `motionHeading` / `amInExtent` / `cmdFloatAtHeight`):
- `COMPASS` (`10d8:0f68` -> `1208:39a8` -> `1208:0574`): the current figure's orientation row 1 (vtable +0x20) with z zeroed, normalised, as the
  8.8 angle atan2(m[1][0], m[1][1]) (`1200:0896` / `07e3` asin / acos through the table `1210:0e6b`); the script gets the integer part
  (`>> 8`, floor). 0 along +y, positive toward +x = the port heading wrapped to -180..180. ASSUMPTION: exact atan2 instead of the table (may differ by a degree at
  the cut points).
- `HEADING obj` (`10d8:26f2`): the last frame's move, d = frame start position (+0xba) minus position (+0xb), x and y as longs. If the 16-bit sum
  of the absolute LOW words of dx, dy is 0 or negative (only the low words are tested) it returns 666 (0x29a). Otherwise a = atan(dy/dx) in whole
  degrees (`1200:097a`: `1210:0c24` divide, atan table `1210:0f2f`; dx = 0 gives -90 / 90 by the sign of dy) and the result is -(a+90) for dx < 0, else
  90 - a: 0 = moving toward -y, 90 = -x, -90 = +x, 180 = +y, i.e. COMPASS of a figure walking forward. ZAPSOMEBODY compares it with the compass
  to choose SHOCK_FRONT / BACK / LEFT / RIGHT.
- `ISMYFORM name` (`10d8:2d98`): `FUN_1000_5a06` is a case-insensitive strcmp (stricmp) of the argument with the figure's string at +0x1ea; ASSUMPTION
  that it is the FIGR type name (`Figure.type`: Lex = LEX, GUARD1 = GRDCELL). An empty argument is an error (0).
- `ISINCOMBATMODE` (`10d8:2c4f`): returns `flags(+0x34) & 0x40`, i.e. 0x40, not 1 (`10d8:2c9e` is the 0x08 twin).
- `ISKEYPRESSED code` (`10d8:2d17`): the byte `1290:7bbe[low byte of the argument]` of the key state table; the ports test the held PC scan codes
  (`_HK_KEYPAD7` = 71 = 0x47, the numpad scan codes of `keys.py`). A key pressed while a monitor is open is not in the port's held list; one pressed while the keyboard is captured is kept apart, in `keys_captured`.
- `AMINEXTENT obj name` (`10d8:06ef`): `AMINWAYPOINT`'s twin; the name is looked up with `FUN_1050_0996` in the PHYS list (`1290:1cf5`), the first
  PHYS of that name, and `FUN_1070_0aba` tests the object's hull against the PHYS box (inclusive). Unknown object or PHYS: error, 0.
- `FLOATATHEIGHT wp [MAXIMUM]` (`10d0:2f91`; the shipped scripts use `FLOATATHEIGHT USEALTI MAXIMUM` in CHAOS and the one-argument form in the
  bot levels). With `MAXIMUM` the figure's area (+0x35) anchor PHYS gives the base z (+0x13) and +0x14e := waypoint z - base z; the mover
  (`10a0:22e1`, before the delta is read) then limits the target z to `anchor.z + cap` whenever +0x35 and +0x14e are non-zero (ported:
  `Figure.z_cap`, `World.mover`). Any other second word, a missing area or an unknown waypoint is an error. The port selects the area lazily, so
  the command selects it when a placed figure has none yet. Without the second word: F (model +0x88, copy at +0x225) := waypoint z - the
  support under the waypoint (`1060:0d9a`, the floor query that starts from -0xc8000), model +0xa6 := 0, z := support + F and vtable +0x2c (the
  mover). Ported 2026-10-31: see "Level mechanics", FLOATATHEIGHT.
- No current figure: the original reports an error and returns 0 for COMPASS, ISINCOMBATMODE and ISMYFORM; the ports return 0 silently (a process
  can still name a figure the port retired, e.g. `DR_ZAP3_FIRSTBOT` after FIRSTBOT's KILL).
- DIE is final **while it plays** (`FUN_1098_0394` returns before any motion change while the current motion is DIE and not finished;
  corrected in "Movement fixes", it first refused for good): both ports refuse `set_motion` on a figure in an unfinished DIE. ASSUMPTION: a `MOTION … SNAP_TO` or `SNAPTOPOSE` still replaces it, because AWAKEN.scr
  `REVIVELEX` revives the knocked-out Lex (FIRSTBOT_STIMULUS `MOTION DIE`) with `MOTION WAKE_UP SNAP_TO FREEZE`; the exact path
  is not traced. Without the lock a dead GUARD1 was put back into ATK_STAND by its still-running taunt process.

**Open.** Original-vs-port parity of the fights (Caynan checked live, see below; Guard 1 not); Caynan and the guard never hit Lex while he is in the long SUPER_REC
chain, the clearing site of ~3 is still assumed; decal pictures; SOUND one-shot; the float-height form of FLOATATHEIGHT; the presentation names of the list above. The Swift port mirrors the engine
changes (World*.swift, `ChaosEncounterTests.swift`); the two fight scenarios themselves are Python-only and not native fixtures.

### Live check: Caynan fight in the original (2026-10-23)

DOSBox-X captures in `re/out/live_fights/{easy,medium,medium2}/fight/` (ignored output). Lex was staged
inside Caynan's cell after a staged nurse defeat, then fought with real Alt+KP8 (ATK_H8) punches.

- Lex → Caynan: every hit took exactly 25 HP at Easy and 21 at Medium, i.e. strength 25 − 4·d, as
  `damage` computes (Caynan has no IMPACT_ARMOR). Caynan reacted with `super_rec_TL/TR/MR` (strength > 19).
- Caynan → Lex: Easy hits of 13, 14, 16 and 18 are ATK_H9/H3/H8/H7 strength − 4; Medium hits of 21 and 24 are
  ATK_H9/H8 strength + 4. Both match the player-target difficulty rule. Lex reacted with `super_rec_*`, or
  `recoil_*` for weaker hits.
- Outcomes: at Easy Lex won with 23 HP (the port's scenario: 17). At Medium the second run ended with Lex
  dead and Caynan at 95 (port: Lex dead, Caynan 74); the first Medium run was stopped at 34 against 116. So
  losing at Medium with straight punching is the original's behaviour, not a port defect.
- Unexplained: in Medium run 2 Lex lost 19 and then 17 HP while Caynan was in `atk_m6` (a movement, not a
  strike). This is probably the nearby electrified bars rather than a Caynan hit; not confirmed.
- Guard 1 was not captured: staging cell 2 in the original was still in progress when the run was stopped.

### Live check: melee and the sentry at Medium (2026-11-01)

DOSBox-X, new game at Medium, Lex revived (82 HP) and staged with `set_xy`, per-update samples (each duration good to about 1.5 ticks). Traces were in the session's scratch directory, not kept.

- **Timing matches.** Caynan's ATK_H9 runs 4.76 clock ticks a frame live; the ports' (MY_SPEED 320 x frame time 4 - 64) / 256 = 4.75. His `super_rec_TR` is 86 ticks live, 87 and 83 in the port. Lex's `recoil_TL` is 46 live, 48 by frames. An apparent gap in a first comparison (Caynan's ATK_H8 33 ticks in the port, 54 live) was the port's motion being cut short by a hit: compare frame rates, not segment lengths.
- **Damage matches.** Caynan on Lex 21, 22, 22, 26 (H9, H3, H3, H7 strength + 4); Lex on Caynan 21 (25 - 4). A sentry bolt took 54 (the port's 46 at Easy + 8).
- **Heavy hits agree with the code.** Live, strengths 17 and 18 gave `recoil_*`, and strength 22 was lethal, so these runs show no SUPER_REC on Lex; that is what strength > 19 predicts. The ATK_H8 that gives `super_rec_*` in the port was also lethal live here; the earlier live check saw `super_rec_*` on Lex.
- Alt+KP8 pressed during `recoil_BL` did nothing; the recoil ran on.
- **Two port bugs found this way, both fixed:**
  - `C` never showed: the input handler replaced LEX_ENTER_COMBAT's `MOTION ENTER_COMBAT` with STAND in the same tick, and Lex idled in STAND in combat mode. Live: ENTER_COMBAT, then `atk_stand` (`FUN_1098_0745`). The toggle now runs before the motion gates and the idle is `idle_motion`.
  - An ended motion fell back to idle only for combat-mode figures. `1088:4155` applies to any living figure with no motion task, and HALMECHO's TURN_WHILE_FIRING (AI_MAIN.scr:225) loops until its FIRE_GUN ends, so the port's sentry fired once and locked. It now cycles every 26 ticks (live: about 25). ASSUMPTION kept: the player's other finished scripted motions wait for a key (the port's ownership rule).
- **The sentry's warnings are the same in both.** CHECKLEXMOTION gives two warnings and the third move is the shot. Live, that was combat key + KP8 after earlier walk presses. Unexplained: it stops about 6059 units from Lex live (spotted between 6292 and 6059), 5822 in the port, and its x wanders differently. The staged spot (16550, -33000) is not comparable for bolts: `set_xy` keeps z live, and the port's floor there is z 208 (the hall floor is -5093).
- Not measured: Lex's SUPER_REC and DIE durations, a second hit during a recoil, Lex's reach, kicks. **The guards of CONTROL were not fought in the original**, so "GRDCON is this hard" is a port result only.

**Form armour.** CHANGEMYFORM (`FUN_1088_2a87`) re-reads IMPACT_ARMOR, ENERGY_ARMOR, IS_REFLECTIVE, AUTO_TURN_SPEED and PERSONAL_RADIUS by form name; the ports looked them up by instance name, so a HARD Lex had no armour. `Figure.reformed` / `form_prop` fix that. Not restored by a resume.

### Camera-linked processes (2026-11-02)

**`LINKMETOCAMERAS`, both ports (`link_to_cameras` / `apply_camera_links`, `linkToCameras` / `applyCameraLinks`).**
- `10d0:4c72` looks each word up in the camera list (DS:1d01; unknown = error 0x1e) and registers it with `10c0:547d` (list DS:2f1d, one node per process, at most 10 cameras, `10c0:533a`; more = error 0xe1). It does not touch the flags: a process linked while another camera is showing runs on until the next switch.
- `1130:0114` calls `10c0:5688` after the room / camera events and the show / hide pass, before [63ce] is written. Flag bit 0 of +0xe is set unless the new camera is in the list (`10c0:53fe`), cleared if it is. The kernel skips a flagged task (`1230:0259`). A process that an event block starts and links is therefore flagged by the same switch.
- `CAMERA <cam>` does not call the switch for the current camera (`10d0:1063`). The restore (`1148:0490`) calls it too. LOADLEVEL's call (`1148:15c7`, before `<level>_LOAD`) tests [63ce], which `1130:0048` has just cleared in the same function, so it does not switch and a linked survivor keeps its flag. A process's destructor drops its node (`10c0:4124`, `4177`).
- The bit is the same one as SUSPENDPROCESS / RESUMEPROCESS (`10d0:7985`, `6b76`), AI OFF / ON and the show / hide pass, so it is `Process.suspended`, and a switch overrides those for a linked process. The bot AIs (LANBOT*_AI, LDGBOT*_AI, BCHBOT*_AI, REACTBOT_AI) link themselves: `update_hidden` lets the list decide.
- **Timelines run on the game clock.** The timeline class is in the segment missing from `re/decomp`, `10c8` (Ghidra disassembly). `10c8:0172` parses the next stamp: due +0xea6 = origin +0xea2 + seconds * 60 + ticks * 2, in [8330] units (2 per script tick). `10c8:03e1` runs lines while due <= [8330]. So a resumed timeline runs every line that came due in one slice; RESETREALTIME (`10d0:6b03`) moves the origin to now. `vm.py` already behaved so.
- A WAIT is another kernel task, not flagged, so it runs out during a pause. A CALL child runs on.

**Checked live (DOSBox-X, new game, `dosbox_live.py`'s new `processes` and `force_camera`, frame by frame, cameras forced for the test):**
- CE33: only CELLTHREEBARS and CELL3_MON run; CELLONEBARS, CELLTWOBARS, CELLFOURBARS, FLICKER_LIGHT, BLOCK_DRIP, ANIMGUARD and ANIMCRYO are flagged. Their lists are those of the scripts. `test_camera_links` pins this table.
- `_BR3_FRAME` steps 1-5 each frame on CE33 while `_BR1_FRAME`, `_BR2_FRAME` and `_BR4_FRAME` stand still. Forcing CE11 swaps them: `_BR1_FRAME` runs on from 1, `_BR3_FRAME` freezes.
- ANIMCRYO, flagged with origin 1613 and due 1617, was resumed on CRY1 at clock 4559: at once origin 4559, due 4563. It ran its missed lines and its RESETREALTIME in one slice.
- BLOCK_DRIP and FLICKER_LIGHT show an empty wait list while flagged, which fits a WAIT running out during a pause. INFERRED: the moment it ran out was not sampled.

**Not checked live:** the zero-g room itself, the bot AIs and their interplay with the show / hide pass, SUSPENDPROCESS on a linked process, a linked survivor of a LOADLEVEL, and the pass at a restore.

**ASSUMPTIONS and what is not ported.**
- **A level starts with no camera.** Corrects an earlier note here that it starts from a saved camera read from misc.dat: that file is read only by the restore (`1148:0490`), and `1148:0341` is in the save writer. `1130:0048` empties [63ce] and [63e1] at every level load; until a script's CAMERA, `1130:0fa3` takes the nearest accepting camera on the first frame ([63e0] 1, no debounce). Checked live on a new game, sampling every 0.02 s: [63ce] went from TITLE to empty for the 2.2 s of the CHAOS load, then CE31. A coarser run also showed `UUUUUUUUU` around the load, twice; the finer run did not repeat it, and it is not explained.
- Both ports: a link no longer sets `default_camera` (now only the `World(camera=)` argument), selection and ISCURRENTCAMERA see no camera until the first switch, and LOADLEVEL no longer applies the links. The full run did not change.
- `current_camera()` keeps its fallback to the level's first camera for drawing, the ambient bindings, the sound listener and a save's camera. So a positional sound before the first switch takes its volume from that camera (the sound at tick 6460: 2 -> 5, previously from the first linked camera). What the engine uses there was not traced.
- The ports' show / hide pass still runs per frame, not only at a switch.

**What moved, each from the rule above.** Paused processes no longer draw from the shared RANDOM stream, so the seeded fights changed: `CAYNAN_SEED` 11 -> 29 (Lex 76 HP), `GUARD1_SEED` 6 -> 20 (89), `GUARD1_SEED_FULL` 16 -> 28 (60 after the fight). The search results are next to the constants. GRDCON's hits at the hard suit machine depend on that stream too: none with seed 28, 6-37 HP with seeds 22, 37, 20 and 4, so Lex ends the full run with 100 HP. In `SaveLoadTests` all four resume digests moved (the paused flags and what no longer changes) and so did the new-game save's VARS.DEF and IM1; the generator reproduced the old digests at the previous commit first. `test_resume`: on CE33 and CE31 `_br3_frame` animates, `_br2_frame` and `_lht_frame` do not. `fixtures.json` regenerated.

The full run went from 91793 ticks at the previous commit to 96289. Almost all of it is two legs, `cell-panel` (989 -> 3373) and `cryo-ladder` (4483 -> 6736). Sampled every 250 ticks: Lex is in the harness's `approach` key loop, turning and walking around its target by the panel and the iris button. No linked process acts on him there. INFERRED, not traced: a different Caynan fight leaves him in a different pose, and that loop is sensitive to where it starts. It is a harness limit, not a finding about the game.

### Garage recess and the ladder top (2026-11-02)

**Q-pass fit test, fixed in both ports.** `FUN_1060_03f2`'s Q pass lowers the support to a Q space only when `FUN_1058_1a1b` returns 0 for the hull moved to that floor. That is the collision score (`score > 0`), so a hull that would stick out of every space does not fit. The ports tested strict overlap with solids only, so a hull straddling two stepped Q spaces kept the lower support. Consequences:
- Lex now climbs QST3, QST2 and QST1 out of the garage lift's recess on his own (the `stairs-out-of-recess` shortcut is gone).
- A figure only drops into a pit once its whole hull fits. The harness used to reach the cell 2 hole at its edge; it now walks to the middle.

**A motion's first update moves by frame 0's root, fixed in both ports.** `FUN_1098_0000` clears the root base +0xd1..+0xd9 when a motion ends, `FUN_1088_0581` moves by root minus base, and `FUN_1098_0394` copies frame 0's root into the blend's start pose (+0x10e), so the blend (`FUN_1088_0d63`, length +0x128 from `FUN_1088_0cab`) holds the root at frame 0. The ports measured root motion from frame 0 and never applied it; `World.apply_first_root` now does, rotated by the heading. A frozen figure and a GO arrival skip it.

Live, DOSBox-X, sampled per frame with `key_down` / `key_up` and the new `root_base` / `blend` fields:
- WALK_BACK, frame 0 (7, 241): the base went (0, 0) -> (7, 241) and Lex moved exactly (7, 241) at the first update.
- WALK, frame 0 (-20, -180): the base went to (-20, -180), Lex to (50, -93), a constant (70, 87) off the base. INFERRED: a wall or collision push.
- OUT_OF_BED, sampled per frame: live and the port pass the same frame endpoints, (-10740, -9226) at frame 36 and (-10795, -9610) at frame 37. The live position is the start plus the unrotated root at every sample, including yaw 79 (root (0, -35) moved him (0, -35)), so the root delta is rotated by the figure's heading, not by the pose's root yaw. An earlier version of this note blamed a 388-unit x gap on root yaw. That was wrong: the gap comes from the nurse's push on the first frame with collisions on ("Live check of the push"), and it depends on where she is. Live landings: (-10270, -8879), (-10335, -8895), (-10696, -8918). The port lands at (-10308, -8920).

An earlier version of this section said live shows no such jump. That was wrong: it compared positions before and after walks with wall contact, and the per-frame samples above disprove it.

**Ladder top, fixed by that.** MANTLE_6 leaves Lex on the floor at the edge of the open hatch, (-12379, -74537). WHOAH_BACKWARD (frame 0 (-69, -259), frame 1 (0, 0)) now moves him about 262 units west at frame 0, away from the hatch, and frame 1 brings him back, so there is no net move over QPIT5 and he does not fall. The `ladder-top` shortcut is gone and the whole run climbs out on its own.

Port-only behaviour since fixed ("Ending a rising motion marks the teeter"): the whoah probe kept firing at that edge, and he drifted in a slow cycle of WHOAH_BACKWARD, WHOAH_LEFT and turns, about 1400 units in the first 250 ticks with no key pressed. A straight walk east from there still crosses the hatch and drowns him, so the harness goes round its south side.

**Fallout.** 35 of Lex's 227 motions have a non-zero frame 0 root, so routes and fights moved:
- New seeds: `CAYNAN_SEED` 11 (Lex 82 HP), `GUARD1_SEED` 6 (79), `GUARD1_SEED_FULL` 16 with ATK_H8 (71). The search results are in the comments next to them.
- Routes: shorter nurse pushes (`scenarios.nurse_defeat_run`), the robot's last stop before the arm within 800 (a wall there is an ASSUMPTION), a wait for the robot's STAND before PWRB, the south way round the hatch, and one stop on `ROUTE_TO_ELITE`.
- Pinned numbers that moved were checked against frame 0. The landpad `AIRMECHO` position is explained only partly: its WALK starts account for the shift's size, but why its AI timeline moved was not traced.
- Open: in the full run Lex loses 11 HP between the end of the Guard 1 fight and the BLASTER pick-up (71 -> 60); not traced.

## The reactor puzzle (2026-11-03, read from the scripts, played in both ports, not checked live)

`re/interp/playthrough_full.py` plays it with real keys and monitor clicks (legs `forklift`, `reactor-room`, `drogg1`, `reactor-shutdown`). No engine change was needed in either port to play it, apart from the Swift fix below.

- **Order the scripts force.** REACTBOT holds the near end of the bridge and the bridge button refuses while it lives (`BRDG_BUT_USE`, BRIDGE.scr:13), so the forklift comes first: RAM_BOT_CR_BOT kills both and calls READY_DROGG1 (CONREACT.scr:67-122). Lex needs the suit: the airlock's inner door kills a plain LEX (`DR2_OPEN`, CONREACT.scr:211-219).
- **The timer.** The first step into CONLOC10 starts REACTORDETONATIONTIMER (AI_DROG1.scr:44-54), since `_RDTHandle` is still 0; WAIT4TIMER in CONLOC6 never gets the chance on a walk over the bridge. In the port `_Reactor_Detonate` follows about 2,950 ticks later. A later entry into CONLOC10 cuts the tens digit to 5.
- **The trap.** Space on the second lever starts DROGG1_RUNFORIT: Drogg 1 runs to the bridge button and THREE_BILLY_GOAT_GRUFF retracts the bridge when Lex reaches CONLOC9. Nothing on the far side turns it back on. So a player who only does the levers and the console can save the reactor and still have no way back.
- **The way out.** Drogg 1 does not follow Lex onto the bridge until `_Drogg1_Counter` reaches `_Drogg1_Max_KO` = 6 (DROGG1_AI, AI_DROG1.scr:226), which counts SUPER_RECOIL, so strength above 19 (a blaster hit adds 1 to 3 by difficulty, LASER_HIT_DROGG1). Then he follows, and BRDG_BUT retracts the bridge under him: RFALLEN_DROGG1 kills him. INFERRED as the intended solution: the scripts have no other way to kill him (`DROGG1_DEATH` reports an error) and he must be gone for the way back. Other solutions may exist.
- **BRDG_BUT's COMPASS test** (-90..-10) has Lex looking back at the bridge, so arriving from it takes a turn of about 130 degrees. A walk with a turn key held does it in about 35 ticks, about 1700 units across.
- **The fight, port only.** Over six start times at Easy with 84 HP in the suit, Alt+KP4 (ATK_H4) won all six (57 HP left in five of them, about 570 ticks) and Ctrl+KP9 won all six more slowly (3 to 57 HP); Ctrl+KP7 won five and Ctrl+KP8 four; Alt+KP9 won one; Alt+KP8 (ATK_H8) and the other ten keys tried won none. Not compared with the original: milestone 4 of `ROADMAP.md`.
- **Swift fix found by the replay.** `applyPlayerInput` tested a one-shot against the motion from before its own STAND, so a move key pressed right after a finished attack started a tick late. Python tested the new motion.

## The mirror suit (2026-11-03, read from the code and scripts, played in both ports, not checked live)

- **Armour is read by type.** `FUN_1088_2a87` looks up EXTENT, IMPACT_ARMOR, ENERGY_ARMOR, IS_REFLECTIVE, AUTO_TURN_SPEED and PERSONAL_RADIUS under +0x1ea (`piVar7 + 0xf5`, 1088.c:1936-1966), MY_SPEED under +0xf7. The ports read the instance name until CHANGEMYFORM. DROGG3 is a DROGGMIR: IMPACT_ARMOR 8, where the DROGG3 block says 100, so he could not be hurt. `form_prop` and `prop` now read the type. HP still comes from the level record, 200 on DROGG3.
- **`PLACEITEM COORDS` and `WAYPT`** were not implemented: the item stayed on its holder, in a slot of that name. `10d0:5510-5640` takes it off its holder (`FUN_1138_099b`), then sets x, y, z << 8, or the named object's centre (`FUN_1050_0129` / `03f8`, vtable +0x50). The port's centre is `arrival_point`, on the box's lowest z; ASSUMPTION for a volume such as LOADBTL4. So REFLECT reached the floor, and BEACH.scr:192-205 and CONMACH.scr:129 now place what they mean to.
- **What it opens.** REFLECT_USE (ITEMS.scr:1477-1545), Space with REFLECT held, swaps LEX and LEXMIR, not in the suit (HARD) or inside PLTDOOR. LEXMIR sets `_pltdoor_SPACE` negative and drains MY_BATTERY by one a minute (REFLECTBATTDRAIN). Taking it off on a BCH, PAD, TMP, LND or BTN camera chokes Lex. So `PLTDOOR` is no wall, as `full.md` used to say, and the order is: zero-g room, battle room and Drogg 3, door, city monitor.
- **Drogg 3.** At Easy, in plain LEX with 57 HP: Alt+KP4 (ATK_H4) won at no cost in 885 ticks. Alt+KP7, KP8, KP9 and Ctrl+KP4, KP7, KP8, KP9 lost. Start times do not vary this fight's result, so this is one sample per key. Port only.
- **The way back over BEACH**, walked in the port up to MARINE2, who kills a plain Lex: FROM_TPL, mantles from BLOCK63 to 64, 60, 54 and 52 (one facing +y three times, then -90), down over 51 and 48 to 47, ZIP8_B to ZIP8_A, mantles to 43 and 42, ZIP7_A to ZIP7_B, mantles to 7 and 6, CT6, CT1 north, CT2 east, TN1, TO_PAD. The zips run both ways (BEACHZIP.scr). The inventory's IPDB and RDYB ready the BLOCK in LTHAND.

## The temple and the way back (2026-11-03, read from the scripts, played in both ports, not checked live)

- **Use blocks keep their motion.** After Space the input code went on to its idle request in the same tick, which replaced a MOTION the block's first slice had started, unless AI was off. `FUN_10a8_0541` has no such step. Blocks such as TO_TMPL_GRENADE_USE, TWR_LV1_USE and FORKMON1_USE now play theirs, so a button press takes the time the scripts expect. Both ports.
- **The temple.** Tube code TN3B TN4B TN8B (CASE 140). TMPL_MON: OPNB, then CLSB while Marine 1 peers in (`_marine_peering_in`) crushes him (CLOSETEMPLE). OPNB again and Marine 2 throws a grenade down the tube, 45 seconds on it (GRENADECOUNTDOWN). It needs the right hand. Thrown from TO_TMPL, it must stop within 125 cm of TMP_FACE (GRENADEENTERTUBE), so about on the axis y -27400. Port's cm: units / 20.48. Off axis it bounces back, and it kills Lex within 400 cm when it goes off.
- **Stowing REFLECT leaves the suit on.** Enter drops the left-hand item first; dropping REFLECT does turn it off, and that killed Lex on the way to this answer. I stows it.
- **The drain** is one energy per minute: REFLECTBATTDRAIN runs its timeline to 59:00, measured 73 to 70 over about 2,800 ticks in the port.
- **The dropship** (DROPSHIPFIREONLEX, LEDGE.scr:118-160) fires on the PAD3 camera, ahead of a walking or running Lex by 20 or 45 cm. Stopping while the bolts fly beats it. SHIP_GO ends it. In the port the scene between SHIP_GO and ANI_SHIP_TAKES_OFF lasts about 776 ticks; unexplained, and not compared with the original.
- **The keypad after the city** (LANDMON.scr) has another rule: a button toggles its own light plus others chosen by the previous button, target 455. `solve_city_keypad` searches it. `_airlock_solved` is 0 by then.
- **Marine 4** at the top of the jetson tube. Of 16 attacks three win from 100 HP (Alt+KP4 with 72 left, Ctrl+KP4 89, Ctrl+KP9 35); start times do not change the result, so each is one sample. Before recoils refused script motions and CONFRONTENEMY waited, only Alt+KP8 won.
- **Not settled.** All of it depends on fight results that have not been compared with the original, and Lex comes back on BEACH with what the temple left because `heal` runs there. Nothing says a player must heal.


## The zero-g room (2026-11-03, read from the scripts and the decompile, played in both ports, not checked live)

- **The key state table doesn't depend on the capture.** `1290:7bbe` is written from the keyboard interrupt (`11d8:1561`), and `ISKEYPRESSED` reads it (`10d8:2d17`). The front ends sent a captured key only to the hook block (`10e8:11e3`), so `ZEROG_TURNING` never saw KP4 or KP6 and a player could not turn. The ports now also record captured keys (`keys_captured`, cleared on key up), apart from the held list, because the normal handler must not see them.
- **Thrust.** ZEROG_KEYBOARD's KP5 plays `ZERO_G_FIRE`, whose frame 8 fires the gun (TUNZEROG.scr:119-131). `TONFA_FIRE` does `LEAP CURFIG 0 6` on a ZEG camera (ITEMS.scr:1153), about 126 raw units a tick directly away from where Lex faces. KP4 lowers the heading 10 degrees a tick, KP6 raises it.
- **Gravity.** ZEROG_GRAVITY leaps Lex at GRAVPT every 15 ticks, with 1 before the city and 2 after it (TUNZEROG.scr:62-80). After the city that is about 3.2 units a tick each tick, more than a shot gives in the 50 ticks a shot takes. Shots from near rest get nowhere. Fired while Lex already swings toward the exit, they carry him there: two shots, 282 ticks.
- **Which hand.** The gun needs the right hand, and three scripts empty it: DISARM_USE (WARHEAD.scr:128-132), OPENTOMB_USE (DIGSITE.scr:298) and the Elite's gift (AI_ELITE.scr:169). The gift can't be stowed, but Space with it puts it in the leg as MY_BATTERY and hands over the old one (REPLACEBATTERYINLEG, ITEMS.scr:1330-1380). At the bike, the same swap gets it back with the bike's old battery. The bike only starts with 375 or more in it (CONMACH.scr:154), so healing and the suit drawing on the battery in the leg can spend the way home.
- **The suit.** ZERO_G_FIRE fails in the mirror suit (TUNZEROG.scr:125-128). Space with REFLECT takes it off there, without the motion (REFLECT_USE _TRUE).

## Fights sampled in the original (2026-11-04, live in DOSBox-X at Easy, `re/tools/fight_sample.py`)

The same key loop in both, with the debugger's delay added to the port (`LATENCY`). Times are 60 Hz clock ticks; a port tick is two. Staging is listed in `STAGES`. Output is under `re/out/fight_samples/`, not kept in git.

| Fight, attack | Fights, original / port | Wins | Lex HP lost per 1000 | Enemy HP lost per 1000 | Hits per punch |
|---|---|---|---|---|---|
| Guard 1, Alt+KP8 | 5 / 24 | 3 / 10 | 30 / 46 | 36 / 39 | 0.38 / 0.38 |
| GRDCON, Alt+KP8, no suit | 5 / 20 | 0 / 3 | 42 / 43 | 27 / 45 | 0.34 / 0.54 |
| Drogg 1, Alt+KP4, suit, to the sixth super recoil | 2 / 20 | n/a | 11 / 12 | n/a | n/a |

One Guard 1 fight and one GRDCON fight stopped early on a sampling bug and count towards the rates, not as wins or losses.

- **What matches.** Damage per hit in all three (Lex 21 on Guard 1, 20 on GRDCON; Guard 1 on Lex 6, 11, 16, 21). Which attacks can land: ATK_H4, H6, H8, H9 and F7 of Guard 1 never hit a Lex in the loop's stance, in either. GET_UP's end position (live -1445, -30108; port -1455, -30115). Drogg's sixth super recoil comes at 1650-1850 ticks live, median about 1450 in the port.
- **CONFRONTENEMY, fixed in both ports.** It is not a snap. `10d0:1c9b` makes a `turn_to_enemy` task (`FUN_10e8_0000`) and the caller waits for it (`FUN_1238_0f48`). `FUN_10e8_0079` plays atk_m4 / atk_m6 (turn_left / turn_right out of combat) until the bearing is under 8/256 of a turn, then stops the motion with `FUN_1098_0789(fig, 0, 0)`, turns the rest at once, and ends two updates later. The port's enemies never showed atk_m4 before. It also changes the order of scenes: GREET_GUARD1 now waits for Lex's turn, so Guard 1 really plays WAKE_UP and GET_UP, as live.
- **A hit ends the turn, fixed with it.** `FUN_1098_0789`'s first argument reaches `FUN_1088_3229`: at 1 it also ends the figure's class 0x109 tasks, and turn_to_enemy is one. A hit passes 1, as do STOPMOTION, the first AI OFF and the hide pass. Without this the task cut recoils short when it settled.
- **Recoils refuse script motions, fixed in both ports.** `FUN_1098_12bd` refuses a MOTION while +0x15f starts with RECOIL or SUPER_REC, so a recoil must be stored there (INFERRED from the gate; the store itself was not read). The port did not, so a hit during a taunt was overwritten by the taunt's next MOTION after 1 to 30 updates. Live, SUPER_REC_TL always runs about 180 ticks; in the port, 56 of 65 super recoils now run 160 ticks or more, and none under 80.
- **Root z kept, narrowed in both ports.** A gravity-less figure's final root z was carried in either direction, so GUARD1 sank 1780 + 360 units through the floor. Live, its z goes back up through GET_UP. INFERRED: only a lift is carried (the known cases are +742 and +1700).
- **The cell's hole is not a port difference.** In the full run about half the Guard 1 seeds back Lex over the edge into TANKS. With the live loop's timing the port's Lex never fell in 16 fights and his range matches the five live fights; without the delay it was 1 in 16. It is the full run's fast loop, and a real hazard of the room.
- **Still open.** (GRDCON's hit rate was resampled and matches: "GRDCON resampled".) Lex loses HP to Guard 1 faster in the port (46 against 30), and Guard 1 starts more attacks there (6.3 against 4.6 per 1000); the guard also walks less, which may come from the harness approaching faster in the port. After Drogg's sixth super recoil he stays stunned far more live (76% of the time, against 40%), in two live fights; the run leaves at that point.
- **Timing matters.** Without the added delay the port wins Guard 1 far more often, so a player who reacts faster than the debugger does better than these figures.
- **Live tool.** `mouse` writes the state the mouse callback leaves (`FUN_11d8_0b8e`: [7bad] buttons, [7baf] x, [7bb1] y, [7b9f] changed), which the reader takes when no event is queued; `set_variable` writes a script global. A port-written save does not load usefully in the original: no figures and no processes come up, which is for milestone 5. A forklift placed on RAM_BOT needs a camera that shows it before its trigger fires.

## Every attack in every fight (2026-11-04, `re/tools/fight_sweep.py`, the port at Easy; two fights checked live)

Twelve attacks, twelve seeds, twelve fights, forked from the state the full run reaches, with no fight errors. Alt+KP1 to KP3 and Ctrl+KP2 are left out: their MAN.MTN headers have strength 0. Reports are in `re/out/fight_sweep/`, not kept in git. Wins of 12 for the best attacks, with `fight_sample`'s `LATENCY` and with `--fast` (almost no reaction time):

| Fight | Lex, enemy HP | With LATENCY | With `--fast` |
|---|---|---|---|
| Caynan | 100, 200 | H4 6, H8 1 | H8 11, H9 11, H4 10 |
| Guard 1 | 100, 100 | H4 9, F9 9, F6 7, H8 3 | F7 9, H4 8 (most others fall in the hole) |
| `GRDCON`, no suit | 100, 180 | H8 3, F6 2, H4 1 | H4 12, H9 12 |
| `GRDCON`, suit | 84, 180 | H4 3, F6 1 | H4 12, F6 11 |
| `GRDHALL`, suit | 84, 220 | H7 3, H4 1, H8 1 | H4 12, F9 5 |
| `GRDHANG` | 84, 180 | F9 5, H4 5 | H4 12, F9 11 |
| Drogg 1, a win is six super recoils | 84, 200 | F9 12, H4 12, F8 7, H8 7 | H4 12, F9 12 |
| Drogg 2 | 84, 200; the script's DAMAGE leaves Lex at 50 | none | H4 2, F6 2, F4 1 |
| Drogg 3 | 84, 200 | F9 9, H4 6, H7 5 | F9 12, H9 12, H4 11 |
| Marine 4 | 100, 100 | H8 11, H7 10, F9 9, H4 5 | H4, H9, F9, F6 12 |
| Marine 5 | 72, 180 | H7 12, H4 5 | H9 12, H4 10 |
| `TUMOLT`, the Captain | 84, 200 | F9 1 | F9 11, H4 10, H8 6 |

Wins over all twelve fights, of 144: with LATENCY H4 53, F9 50, H7 36, H8 33, H9 17, F7 16, F6 13, F8 12, F4 3, H6 0, F1 0, F3 0; with `--fast` H4 123, F9 102, H8 83, H9 78, F6 76, F4 51, F7 47, H7 27, F1 21, F8 20, F3 3, H6 0.

- **ATK_H4 is the best attack overall, ATK_F9 second.** ATK_H6 never landed in any fight. Marine 4 and 5 are the exceptions with the delay, where H8 and H7 lead.
- **The Captain can be beaten unarmed in the port.** With no delay F9 won 11 of 12 and H4 10 of 12. The earlier "at most 50 of his 200 HP" came from the punch loop, not from the fight. Not checked live.
- **Reaction time matters more than the choice of attack.** A hit stuns the enemy for about 110 clocks, in both. A loop that presses again inside that stun keeps him there.
- **Not swept.** The nurse (scripted, staged poses), the ranged bots (next items), Roland (no activation found; `AI_ROLAN.scr` has ROLAND_AI) and Luthor (not reached). Drogg 2 is an escape, so few wins there is expected.
- **Repeating an attack costs nothing at Easy** (`FUN_1098_0088` multiplies the slowdown by the difficulty level, 0 at Easy), so the sweep says nothing about one-attack play at higher levels.

ATK_H4 live, the two fights the earlier sweeps may have missed it in (`fight_sample.py live --attack alt-4b`, `port --attack alt-4b`):

| Fight | Wins, live | Wins, port | Lex HP lost per 1000 | Enemy HP lost per 1000 | Hits per press | Enemy attacks per 1000 |
|---|---|---|---|---|---|---|
| Guard 1 | 3 of 4 | 17 of 24 | 32.0 / 32.5 | 45.7 / 50.5 | 0.56 / 0.64 | 3.8 / 4.9 |
| `GRDCON`, no suit | 5 of 5 | 2 of 24 | 11.3 / 31.7 | 60.7 / 31.0 | 0.75 / 0.57 | 3.5 / 5.0 |

Live, Alt+KP8 went 3 of 5 on Guard 1 and 0 of 5 on `GRDCON`, so ATK_H4 is the answer to `GRDCON` in the original as well. Damage per hit matches: 16 on Guard 1, 15 on `GRDCON`.

- **The `GRDCON` gap is the delay model (INFERRED from the fit, not read from code).** Live, Lex presses 5.4 times per 1000 clocks and the guard is in a super recoil 46% of the time; with `LATENCY` the port presses 3.6 and he is stunned 25%. The stun per hit matches. The port's ATK_H4 at other delays (`wait`, `key`, `punch`, 24 seeds):

  | Delay | Wins | Presses per 1000 | Lex lost | Enemy lost | Hits per press | Stunned |
  |---|---|---|---|---|---|---|
  | 4, 8, 6 (`LATENCY`) | 2 | 3.6 | 31.7 | 31.0 | 0.57 | 25% |
  | 4, 8, 3 | 6 | 4.7 | 31.2 | 45.7 | 0.65 | 33% |
  | 2, 4, 3 | 19 | 6.9 | 21.3 | 64.2 | 0.62 | 42% |
  | 2, 4, 1 | 23 | 6.3 | 8.3 | 74.9 | 0.80 | 52% |
  | 1, 2, 0 | 23 | 6.8 | 14.9 | 77.4 | 0.76 | 45% |
  | 1, 0, 0 (`--fast`) | 22 | 7.6 | 18.4 | 79.6 | 0.70 | 31% |

  The live figures sit between 2, 4, 3 and 2, 4, 1, so `LATENCY` is too slow for ATK_H4 here although it fits Guard 1. Win rate moves steeply with delay, so the sweep's LATENCY column is a lower bound for a player and not a measure of the fight. `LATENCY` was left alone: changing it would also move the earlier comparison, and whether Alt+KP8's `GRDCON` numbers (0 of 5 live, 3 of 20 in the port) fit a shorter delay was not tested.
- **Live tool.** A finished session can stay behind on DOSBox-X's quit dialog and hold its port, so the next run on that port fails with "Address already in use" and "the live session never became ready". Give every run its own `--port`. Two Guard 1 runs stopped while staging, on "the guard wakes"; neither counts above.

## The fighting routine (2026-11-04, the port at Easy, `scenarios.Play.fight`, `re/tools/run_seeds.py`; not played live)

No fight in the run is seeded now, and `fight-seed` is gone. `playthrough_full.py --seed N` starts RANDOM after the nurse. Of 24 streams, 21 finish the game (`run_seeds.py`). The default stream is one of them, and the Swift fixture holds it. A change to the engine or the harness can move any stream, so the fixture's stream may need another look when one does.

- **The routine.** ATK_H4 by default and ATK_F9 on Drogg 3 (23 of 24 against ATK_H4's 15). The delay is 2, 4, 1 ticks, from "Every attack in every fight". After three circling moves in a row Lex leaves combat, turns and goes back in. The routine stops if the level changes.
- **Repair during a fight.** Under 35 HP the routine presses D, clicks BRSB and closes the page. BIOREPAIR is a process and goes on after the page closes (`PIMM.scr:441-505`). The port's fight does not visibly suffer for it; whether the original lets a person do this at the same speed was not checked live.
- **The battery is the real budget.** It holds 100 and stops healing under 10, which is 180 HP until the Elite's gift. `heal` now stops at 75 HP, 100 only before Drogg 3 where the new battery follows. It also no longer switches off a repair that is already running: BRSB is a toggle.
- **Harness fixes the streams exposed.** Where the fights leave Lex moves every arrival, so these no longer assume a position: `into_box` walks into a trigger box until Space would reach it (`PRY_DR`, the levers); `SEC_MON` is reached along the wall, since a turn inside the box moved him out; `take` checks `pickup_candidate` first, since Enter out of reach puts down what the right hand holds (this dropped the gun in the battle room). Keys wait out QUAKE. Falling down the cell's hole after the guard is dead now climbs back.
- **Fixed after the first count of 17 of 24.** Lex climbs back and finishes Guard 1 after falling down the hole with the guard alive. With the Elite's battery the routine repairs from 60 HP rather than 35, which is what Marine 4 needed. The harness waits for `BRDG_BUT_USE` to end, not only for `_Bridge_Moving`, which that block sets after its WAIT 15: when Drogg 1 had already fallen by knockback, the next press came too early and was ignored. That makes 21 of 24.
- **What still fails, 3 of 24.**
  - Stream 6: `DROGG3_DEATH` (AI_DROG3.scr:360) plays `MOTION ATK_M2 CONTINUE` on Lex with his AI off and has no `MOTION STAND` before its subtitle, so in the port he backs about 4600 units, off the platform's north edge. Guard 1's scene has the `MOTION STAND`, and live and port agree there (about 20 ticks of ATK_M2, then the turn). Whether the original keeps Lex backing in the Drogg 3 scene was not checked: it needs that scene staged live. The port treats `COMBATMODE OFF` as a flag only (`World`, not read from the handler).
  - Stream 9: the reactor timer runs out while Lex enters the ID at the console, after a long Drogg 1 fight. That is the game's own timer.
  - Stream 21: Drogg 1 stays in RUN at (-10849, -140159) and never reaches the bridge. Not known whether he would stick there in the original. A lure back up the bridge walked Lex off its side and was removed.
- **Medium.** The routine now wins some Medium Guard 1 streams, 2 of 6 tried; the test keeps a stream it loses. Medium and Hard were not run through the game.
- **Still skipped.** `fight-outcome` (MECHO2, Roland), `surface-fight` (AIRMECHO, the Captain), `bot-fights`, and the sentry and guard shortcuts are unchanged.

## Item charges (2026-11-04, read from the level data and scripts, played in both ports, not checked live)

**A port bug, fixed in both.** An ITEM record holds script locals at the same offset as a FIGR record (106, ten 32-bit values), and the save reader already used them, but a new level's floor items started at 0. Every item is affected. MEDICAID and ZEDICAID hold 5, DANEBAT 100, ORIGBIKEBAT 150, BLASTER 20 and 20. So DOMEDUSE (ITEMS.scr:652-656) always failed in the port, and "BIOREPAIR is the only healing" in the earlier notes was wrong: it also heals Lex, 20 HP a charge, not only Dr. Escher.

- **In the run.** Lex takes MEDICAID in the operating room and ZEDICAID by the Captain's ramp after his death. `heal` spends charges first, then the battery. Not used yet: DANEBAT (BATTERY_USE also runs DANE_DEATH, CONOPER.scr:27-48) and the bike's ORIGBIKEBAT (150 energy, BIKE_USE, CONMACH.scr).
- **MECHO2 by keys.** `Play.shoot` kills it from the cabin with 4 hits (LASER_HIT_MECHO2, DAMAGE ENERGY 30), and the `fight-outcome` shortcut for it is gone. Its two bolts, 92 HP, land before Lex's first shot. MECHO2 holds fire while the door is closed and fires as the ride's tail opens it; once a laser lands, LASER_RECOIL stops it answering. Sidesteps make it worse, aim is not the limit, and combat mode does not survive the ride.
- **The count.** 17 of 24 streams finish: 21 with the MECHO2 shortcut and no charges, 10 without the shortcut and no charges. It still kills Lex on streams 14 and 22, whatever he has left. Drogg 3 twice, GRDCON before the suit machine, the Drogg 1 bridge and the reactor timer make up the rest.
- **The weapon route, tried and not merged.** In the hard suit Lex did not lose to GRDCON on the first 24 streams without charges (one loss with them), but GRDHALL killed him on 11 of 24 with MEDICAID, and 6 finished. ZEDICAID and the spare batteries were not in that count.
- **The bike's battery (played in both ports, not checked live).** Lex reaches the garage on about 9 energy on most streams. In `garage-block` he takes ORIGBIKEBAT out (150 of 500, CONMACH.scr:39-44), swaps it into his leg away from the bike, puts the old one back in (`_Battery_In_Bike` 2, CONMACH.scr:141-147, and BATTLOW in the journal), and repairs to 100 there, before the reactor's timer starts. DANEBAT stays unused: DANE_DEATH sets `_Dane_Alive` 0, which the personality web reads (CONOPER.scr:971, 1024).
- **Most Drogg 3 "kills" were falls.** The battle room has two glass panes, THOLE1 (x 6216..7240, y -131528..-130504) and THOLE2 (x 12413..13437, y -131374..-130350). The first step creaks and shakes Lex, the next drops him through (FALLHOLE, BTL_FALL, PLATFORM.scr:200-321). With the new battery 5 of 24 streams still "lost" this fight, the traced ones with over 100 energy unused. `Play.fight` now takes `avoid` boxes: within AVOID_MARGIN (1200) he steps away first, at most six times in a row so a wall cannot hold him there. No stream loses the fight itself now. The open question about the death scene still stands, and it can end the run: DROGG3_DEATH plays `MOTION ATK_M2 CONTINUE` with no MOTION STAND before its subtitle, which on one traced build carried Lex about 2000 units onto THOLE2 with AI off, and he stood there until it gave way. The harness cannot prevent that. Not checked live.
- **The weapon route (played in both ports, not checked live).** `grdcon` follows the suit machine; `grdhall` follows the garage, so Lex meets him on 100 HP with the bike's battery. No stream loses to GRDHALL now (11 of 24 before), though the fight costs up to about 120 energy. In the suit GRDHALL is peaceful until Lex hits him (`_GrdHallHatesLex`, AI_GRDHL.scr:89-127), so a routine that never lands a punch stalemates: after 30 waits at 20..50 degrees it now punches anyway, and if he is still peaceful Lex walks on without the gun (stream 4). DR14 closes during the fight, so Lex presses CNT_BTN3 again.
- **The reactor's timer is tight.** Going back through CONLOC10 to lure Drogg 1 cuts the tens digit to 5 (AI_DROG1.scr:44-54), which leaves about 1200 ticks from the bridge to the console, and a quake at a lever costs about 200. The default stream missed by a few ticks until the lever walk stopped short and let `into_box` finish it.
- **The count now.** 20 of 24 finish, 19 of them with BLASTER2. Left: MECHO2 on 14 and 22, GRDCON on 5 (before the suit machine) and 13 (in the suit), all before the garage.
- **MARINE5 without `guard-ai-off` (port only, not checked live).** The gun does not do it. From the cabin side of the hall, about 18000 units away, 3000 shots from Lex and MARINE5's bolts all miss. Walking in, his bolts (46 HP each) kill a 100-HP Lex before he fires once. In the mirror suit the bolts do nothing (on the traced streams Lex kept all 100 HP), and guns fail in it (LEX_ATK_SHOOT, AI_LEX.scr:240-247), so Lex keeps the suit on and kills him with ATK_H4, about 20 hits. No stream dies to him. The repairs come from the Elite's battery, which needs 375 for the bike's ending (CONMACH.scr:95). Stream 11 reaches him with 400 and ends at 369. Without repairs MARINE5 kills Lex on 10 of 24. 19 of 24 finish. Repairs in that stretch capped to leave 385 (375 and the suit's drain to the bike) still give 19: stream 11 then dies to MARINE5. Not merged.
- **Where the Elite's battery goes (port, 20 streams that reach the bike).** The suit's drain is about 1 a thousand ticks, under 25 from the platform to the bike. The repairs are the rest: the BEACH climb up to 14, LANDPAD (Marine 4) up to 82 (mean 32), the MARINE5 stretch up to 106 (mean 42). ATK_H7 on MARINE5 (the sweep's best there) makes that fight cost up to 161, and ATK_H8 on Marine 4 up to 132: 4 and 5 of 24 finish. The repair to 100 after MARINE5 is dropped, since nothing fights Lex after him. That leaves the count at 19 and stream 11 at 368, because its cost is in the fights.
- **MECHO2 from the corner (port, not checked live).** MECHO2_AI fires only while `_LexConLoc` is set (AI_MECH2.scr:66-90). CMECH1A and 1B set it, and the console stands in CMECH1A. CMECHZA and ZB, the cabin's corners by the door, clear it (AI_MECH2.scr:1-19). Its first two bolts (92 HP) used to land as the ride's tail opened the door, whatever Lex did: they come at a fixed tick, and facing it or entering combat first did not help. Lex has his keys back during the tail, so he now runs into CMECHZA (-34800, -67100) while the door is still shut and shoots from there. MECHO2 never fires back; most early shots miss through the door, so the kill takes about 3000 ticks, and Lex keeps his HP. Leaving the operating room afterwards, a straight walk from MEDICAID to the hall stuck on streams with the new timing, so the route follows the path main took. 19 of 24 still finish, but with different failures: no MECHO2, GRDCON on 1, the Drogg 1 bridge button on 10, and the bike's 375 on 14, 19 and 21.
- **The bike's 375, and what the game does when it is short.** Switching a running repair off after the Marine 4 and MARINE5 fights, with a heal to 80 rather than 100 before MARINE5, still finishes 19 of 24 (14, 20 and 22 short now instead of 14, 19 and 21): the Marine 4 cost did not change, so the repairs are spent inside the fights. Not merged. The game has its own way out. With the Elite's battery (`~3 = 1`) under 375, BIKE_USE writes the BIKEWEAK log entry and sets `_need_new_battery = 1` (CONMACH.scr:173-187). The next PLATFORM load then creates a full 500 ALBAT at COORDS 34 -614 -6 (PLT_LOAD, PLATFORM.scr:72-81). So a short battery means the trip back to the platform, not a lost game. The harness does not make that trip.
- **The trip back for a new battery (port, not checked live).** `bike` checks the leg's charge before the ending. Under 375, `short_battery` swaps the batteries as `bike_battery` does but puts the weak one in, so the game sets `_need_new_battery`, and `battery_trip` goes back to PLATFORM. The route there: CONTROL's cabin to LANDPAD; the airlock keypad again (the city rule) in the mirror suit, because DRA_STRT chokes a plain Lex outside (LANDPAD.scr:230-239); the jetson tube and the ledge to TO_BCH; the BEACH ledge back to the blocks; one `set-pos` down the blocks to the temple tunnel (on the narrow blocks Lex teeters and turns off them into the sea); TO_TPL; the temple's hole TMPL2TUN back to the tube room (TEMPLE.scr:16-22); TO_0G with REFLECT in the left hand, since only then does Space take the suit off in the zero-g room (TUNZEROG.scr:167-170); the flight to TO_FINAL. On PLATFORM, PLT_LOAD has put a full ALBAT at (8704, -157184). Lex takes it (Enter puts the TONFA and REFLECT down), swaps it into the leg, drops the spent one and picks the rest up again. The way back is the first return's, with two changes. He waits for TONFA_TIMER to reset `_tonfa_used`. He takes the suit off before TO_ZEROG, because taken off inside the room he drifts back into TO_FINAL. On stream 14 he reaches the bike with 479 and the ending runs. With the trip, 22 of 24 finish: 14, 19 and 21 now finish, and GRDCON on 1 and the Drogg 1 bridge button on 10 are left. The default stream does not make the trip.
- **The suit machine during the GRDCON fight (port, not checked live).** On stream 10, which looked like a bridge-button failure, the fight is beside SUITTEST. A blow knocked Lex into it, HARDSUITMACHINE ran again and took the suit off, and much later DR2_OPEN choked the plain Lex in the reactor airlock (CONREACT.scr:211-219). `grdcon` now walks him back into SUITTEST when he leaves the fight without the suit. With that, 23 of 24 finish. GRDCON killing Lex on stream 1 is the one left.
- **Combat mode after a quake (port, not checked live).** On stream 1 a quake during the GRDCON fight dropped Lex out of combat mode. `Play.fight` went on pressing the combat keys, which out of combat walk and turn him, and he never hit GRDCON once while it beat him from 84 HP to dead. The routine now presses C again whenever it finds combat mode off and Lex has his AI. Stream 1 then wins with all 84 HP, and all 24 of 24 streams finish.
- **Roland by keys (port, not checked live).** ROLAND_AI only cowers, backs away and pleads; he never hits Lex (AI_ROLAN.scr:142-286). A hit while `_SRE_Count` is 1 or 3 moves it on (ROLAND_STIMULUS, :88-96). In his CORNER with Lex within 450 and the count at 2, he promises the gun. Under 50 HP, with Lex off the gun, he restarts it himself (RESTARTGUN, :279-365, `_GunActive = 1`), first telling Lex to move back while he stands in ZONE. `roland` fights him with the routine until he is under 50, leaves combat, steps out of ZONE when told, and waits for `_GunActive`. On the default stream he goes down to 45 and the gun comes on about 1100 ticks later. The `fight-outcome` and `globals` (`_GunActive`) shortcuts are gone from the full run, and all 24 of 24 streams still finish.
- **The LANDPAD bots alive (port, not checked live).** With `_LandbotsAlive` left set, READY_LANDBOTS readies LANBOT1-4 and LDGBOT1-3 (LANDBOTS.scr:6-31), each with 28 HP and a laser hit taking 15 (LASER_HIT_TOWERBOT, MISSILES.scr:256-265). The four pad bots never fire on the run's path. The three on the ledge do. Lex's laser needs about 10000 units, and they hit him from 24000. Shooting from the ledge arrival, 190 shots all missed: the combat auto-turn leaves him about 8 degrees off. Aimed out of combat and closer in, he killed LDGBOT1 but the other two killed him first. Run along the ledge, their bolts land behind him: 5 hits on the default stream, 84 to 54 HP. `ledge_run` does that. 24 of 24 still finish. The three BEACH bots stay set dead (`bot-fights`): alive, they hit Lex from the arrival on, one of them was killed by another's bolt, and he died on the way to ZIP1 even from 100 HP.
- **The BEACH bots alive (port, not checked live).** BCHBOT3 is already down when Lex arrives: another bot's bolt killed it at the level's load. BCHBOT1 and 2 hit Lex from 40000 to 84000 units, far past his laser. Healing at the arrival only gives them more shots, and the first-visit walk to ZIP1 stalled under the recoils. Run straight to ZIP1 with the BLOCK ready (`beach_zip1`), Lex rides the lines away, and the warhead's blast takes BCHBOT2 (WARHEAD.scr:24). On the default stream he reaches the dig site with 5 hits. With every bot alive, `bot-fights` is gone. 23 of 24 finish: one stream loses Drogg 3 (14, from 100 HP after the heal; with mid-fight repairs from 45 rather than 35 it is 6 instead, so that change was not kept).
- **MEDICAID in the mirror suit.** Space with MEDICAID in the suit plays USE_MEDIC_FAIL and uses no charge. `heal`'s loop only checked charges and HP, so after the battery trip (which ends in the suit) it tried again for ever: three streams hung for hours. It now stops when a use leaves the charge count unchanged.
- **AIRMECHO, checked live (2026-11-07, DOSBox-X at Easy).** Two runs: Lex woken, Guard 1's BLASTER taken from its cell (placed beside it, Enter), the CHAOS cabin's ELMN AIRB clicked (screen 171, 131; CONB is 165, 103), out of the LANDPAD cabin to MEETMECH. Standing still, AIRMECHO's opening bolt froze Lex about 210 clock ticks after the scene ended (RECOIL_ML, the camera then ELV3), and he died about 280 later, as in the port. Shooting (combat, KP5 when standing): a shot about every 65 clock ticks, as the port's 30-odd ticks; the laser about 200 units a clock tick (MAKEMISSILE LASER 6: the port's 407 a tick); 45 a hit (125 to 80 to 35); the camera flicks to HFR6 during each shot and back to HFR3. Lex was frozen with AIRMECHO at 35, one hit short, and died. So the original loses a straight duel from LEX_POS2 too, and the port's timing, shot rate, damage and the HFR3 / HFR6 cameras match it. The script's two-hit rule is the reason: the first bolt that reaches Lex bends him over (RECOIL_ML FREEZE) and fans five more, and the next kills him; in DEATHDOR it plays the ELV3 gunfire scene instead, which is a death too (BOLTGRN_HIT_LEX, AIRHALL.scr:90-171). A win needs three hits before the first bolt lands, so shots from the moment the scene gives Lex back. The port's routine fired from then and hit once of three (AIRMECHO walks while it fires); the live run started 190 clock ticks late and hit twice. Not tried: a sidestep before the first bolt (in the port a sidestep moved Lex about 600 units, too little, and keys are ignored while ATK_SHOOT plays). The fight stayed staged then; it is fought by keys now ("AIRMECHO by keys").
- **The Captain by keys, tried and not merged (port).** The gun is no use: LASER_HIT_TUMOLT does DAMAGE ENERGY 10 (MISSILES.scr:136-145), his armour takes all of it (23 laser hits left him at 200), and DISARM_USE has put the BLASTER down at the warhead anyway. By hand with the fighting routine (its reaction-time delay), healed to 100 first: on the default stream ATK_H4 left him on 40 and Lex dead, and ATK_F9 killed him with Lex on 48. Over the 24 streams ATK_F9 wins 12; breaking off under 40 HP for MEDICAID and going back in wins 5, because he does not let Lex heal. This matches the attack sweep (ATK_F9 1 of 12 with the delay, 11 of 12 without). His death stays staged.
- **GRDCON with MEDICAID's charges, tried and not merged.** Streams 5 and 13 reach GRDCON with 2 and 3 charges unused, because `heal(run)` stops at 75. On 5 GRDCON stands by the stairs to the suit machine and beats Lex from 88 to dead after a quake stops him there. On 13 Lex fights at 66; with all charges used first (to 100) he wins with 60. Healing that way before the suit walk too saves both, but the shifted RANDOM stream loses the default stream to GRDCON on the walk and finishes 17 of 24. Healing only before the fight finishes 15. In both counts the new losses are mostly elsewhere: four streams end with the Elite's battery under the bike's 375, one at the bridge button. So the bike's margin is the weak point that changes in the GRDCON stretch keep exposing.
- **GRDHANG without `guard-ai-off`, tried and not merged.** Fought by hand right after the lift, with what MEDICAID has left and about 9 energy, he killed Lex on 4 of 24 streams (6, 11, 18, 19). Taking the bike's battery first, with him chasing, finished none. The gun only comes after the garage. Fought now, healed first ("GRDHANG fought, the Captain tried again").
- **The glass and the death scene, again.** With GRDHANG fought, two streams (default, 16) DROGG3_DEATH's ATK_M2 carried Lex about 2000 units back onto THOLE1, roughly opposite Drogg 3 but not straight. A 3000 margin stops Lex reaching Drogg 3 at all (0 of 24). A check of the line straight behind him did not catch it.
- **A gap this shows (fixed 2026-11-08).** `load_floor_items` forgot a level's floor items when Lex left it, so ORIGBIKEBAT was back in the bike when CONTROL reloaded, and the old battery put there was gone; the ending took that fresh one out (ABAT_500_USE). CONTROL now keeps its items ("A level keeps its items when Lex leaves it"), and the ending takes out Lex's old battery with BAT_100_USE, as the scripts say the original does. Both reach ENDGAME.
- **Harness traps worth keeping.** Space takes an object in reach before a held item: `heal` once switched the bridge off under Lex, so it now checks for one. Any repair's first key stows the left hand, and the zip lines need the BLOCK there. SUITTEST must really be entered: a guard's blow used to knock him in.
- **`resume_digest.py`** regenerates the pinned resume digests. It reproduced all four old ones on the old code before giving the new ones, and the two ports' state lines match line by line.
- **AIRMECHO by keys (2026-11-08, both ports; not played live).** Lex wins the duel out of combat, so there is no auto-turn. The things that make it work, read from the scripts and measured in the port:
  - Lex has his keys back as soon as MARCHOUTAIRMECHO turns AIRMECHO's AI on (`AI ON` for it, then for the player, AIRHALL.scr:66-74). AIRMECHO fires once at AIR_POS, fires again as it walks to AIR_POSX, and then every 138 ticks at Easy (FIRE_GUN, `WAIT 50`, `WAIT 70 - 20 * difficulty`, AI_AMECH.scr:16-52).
  - Each BOLTGRN flies about 200 units a tick toward where Lex stood when it was fired, so it takes some 55 ticks to cross the corridor. A sidestep (End / PgDn) held from when AIRMECHO raises its gun until the bolt has passed clears it; started only when the bolt appears it can be too late. Passes 558 and 718 units off still hit, 1460 off missed. Out of combat a held sidestep moves Lex about 1900 units in 60 ticks. The bolt leaves about 15 ticks into AIRMECHO's FIRE_GUN.
  - KP5 out of combat fires ATK_SHOOT along Lex's heading (about 30 ticks). Short turn holds turn by fixed steps: left 1.41 degrees (4-7 ticks) or 11.25 (8-11), right 4.22 (3-5) or 11.25 (6-8); shorter taps do nothing. Aimed at a bearing of about 3.2 degrees left of AIRMECHO while it stands at AIR_POSX, every shot hits (45 of 125, LASER_HIT_AIRMECHO at Easy).
  - `airmecho_duel` (playthrough_surface.py) sidesteps from each FIRE_GUN and while any bolt would pass within 1300 units, and shoots only while AIRMECHO stands at its post, with no bolt on its way, and when the shot (30 ticks) ends before its next FIRE_GUN, unless the shot kills. Lex aims only when he may shoot. All 25 streams get past it with Lex unhurt. The standalone LANDPAD segment plays at Medium (35 a hit, a volley every 118 ticks) and wins too, with 5 shots and 5 dodges.
  - Not checked live. The live attempts stood still, and the earlier port attempt shot at AIRMECHO while it walked. The corrective `set_pos` off LEXSTUK stays (surface.md blocker S-lexstuk).
- **GRDHANG fought, the Captain tried again (2026-11-08, both ports for GRDHANG; the Captain in the port only).**
  - GRDHANG: `garage_block` heals with MEDICAID's charges before the hangar monitor (Lex had 55 HP and 5 unused charges), then fights him with the routine once the lift is down. `guard-ai-off` is gone. With AIRMECHO also fought, 22 of 25 streams finish (`run_seeds.py`): GRDHANG kills Lex on streams 2 and 14, and Drogg 3 kills him on 20. The default stream finishes.
  - The Captain's speech ends in a scripted shot (ACTIVATE_TUMOLT: `WAIT 10`, `MOTION SHOOT`, AI_TUMLT.scr:94-99) that took 46 of Lex's HP. In combat mode a held KP1 or KP3 (ATK_M1 / ATK_M3), or a run forward, dodges it; KP4, KP6, KP2 and a plain sidestep after C do not. He shoots only while `_TONFA_OK` (cleared for about 30 seconds after six shots, WAIT_30 in ITEMS.scr:1228-1243), and only beyond his attack range (MONSTER_MOVE cases 8 and 10, AI_MAIN.scr:1-51); the losses come from his melee, 11 to 21 a blow.
  - Lex reaches him with about 30 HP. ZEDICAID lies by the ramp before RTMLT2 wakes him, so the attempt took it and healed to 100 first. With that, the dodge and ATK_F9, the routine won 8 of 12 streams at the old battery budget (48 energy for BIOREPAIR during the fight). With GRDHANG fought, Lex arrives with 9 energy, the floor where BIOREPAIR stops, and the same routine wins 2 of 13, the default stream lost. Giving him back 48 energy (a diagnostic, not a route) only brought it to 6 of 13. ATK_H8 won 7 of 12, ATK_H4 and ATK_F7 none. Two variants did worse: using MEDICAID during his taunts (a use takes about 270 ticks and is cut short), and stepping back from his swings to strike on the recovery (0 of 26).
  - So his death stays staged (`surface-fight`, one use).
- **The hall sentry and the tower bots (2026-11-08, port; not played live).**
  - **HALMECHO's rules, read from AI_MECHO.scr.** Pacing (state 0), it reacts only to Lex within 300 cm (6144 units) and in front of it (ANGLEFROMENEMY -90..90), and not while he plays ALCOVE_L / ALCOVE_R (:160-190). It then stops, turns to him and warns (state 1). In state 1 it stays where it is, and CHECKLEXMOTION (:17-61) fires it (state 2) only for WALK, WALK_BACK, ATK_M2 or ATK_M8 (two warnings first) or RUN (at once). Sidesteps, turns and the other combat steps are not on the list. Its processes are linked to the hall cameras HAL1-6 / ELH1-2, and it does not move while another camera is current.
  - **First pass, unarmed (DR6 to the cryo door).** The sentry starts at the south end and walks north toward DR6, so it spots Lex wherever he goes. Once it has, Lex sidesteps the whole hall into the cryo room (`Run.sneak`: PgDn held, facing 90 degrees left of each leg). It warns and never fires. About 2300 ticks. `sentry-dodge` is gone.
  - **Second pass, armed (the cryo door to the cabin).** CHAOS has been reloaded, so the sentry is back at WAY_PT2 in state 0. It starts south once a hall camera is current, about 64 units a tick. Lex runs with Shift+Up held (`dash`) from the cryo door to DR7_BTN and is in the vestibule, more than 7000 units off its line, before it comes within reach. It never spots him. `sentry-ai-off` is gone. Shooting it does not work: every laser hit sets state 2 (LASER_HIT_HALMECHO, :97-114), it fires again within about 30 ticks, and two of its bolts (46 at Easy) kill Lex before the sixth laser.
  - All 25 streams pass both passes; the count stays at 22 of 25.
  - **The tower bots, tried and not solved; `hold-fire` stays.** Each bot fires every 60 ticks while `_LexTowLoc` (set by entering the TTBAT boxes, AI_TOWER.scr:5-77) is in its range: bot 1 in 1 and 3-7, bot 2 in 2-7, bots 3 and 4 in 5-7, bot 5 in 6 and 9, bot 6 in 7 and 8. Zones 0 (TTBATZA / ZB) and 10 are safe from all. A hit takes 6 and plays RECOIL_ML, and the next bot's laser lands during it.
    - The way to the gun from the elevator goes round through zones 4 and 5, or 6A, or 7A. ZB is closed to the south by a wall, and the east platform (zones 1-3) is walled off from zone 10.
    - Walking with goto, Lex dies in zone 5. Running with Shift+Up held throughout (`dash`) dies there too: the lasers still land. Every hit was on a camera in the bots' viewing list.
    - From ZA no laser leaves Lex's gun at all, so the safe zones appear to be behind cover. A bot has 28 HP and a laser takes 15, so two hits kill one, but that has to be done in the open.
    - Whether the original's deck can be crossed this way, and how, has not been checked live. The next step is a live run from a port save at the tower arrival.
  - **Roland's promise.** With the new hall timing, the save after `tanks-back` (and the same point with only the animations restarted) left Roland at 45 HP, and he never restarted the gun. He restarts it only after promising to (ROLAND_AI CASE 3, AI_ROLAN.scr:226-236). He promises only when he is in CORNER, Lex is within 450 cm and `_SRE_Count` is 2. Near Lex but out of the corner, he backs away into it (CASE 2). `roland` now walks back toward him while the count is 2 and Lex is more than 6000 units away. That boundary finishes again, with and without the save.
- **The tower deck, checked live (2026-11-08, DOSBox-X at Easy).** A port save at the tower arrival with the bots held (`hold-fire`) loads in the original. The live session then set each bot's AI-off counter (`+0x229`, NOTES "Default AI") from 1 to 0 with the new `figure_word` control command, and the original started their AI by itself.
  - **The gauntlet is real.** Standing just outside the elevator, bots 1 and 2 fired at once and took 6 a hit, about 12 HP a second, the same as the port: 76 to 4 in ten seconds. Running the port's route to the gun, steered live with short turn taps, Lex died in zone 5 (76, 58, 34, dead), as in the port. So a player who simply runs dies there in the original too, and `hold-fire` is not hiding a port bug.
  - **Not a save-writer gap after all (rechecked the same day).** A port save taken with the bots' AI running looked as if it never loaded: the check sampled after the load macro and found no figures, no processes and the game back at DOS. Watched from the start, the original loads it: Enter on the title screen already loads slot 1, and by 22 s the tower is up (camera ELT1). The bots resume firing straight away, and Lex, standing still with no one at the keys, takes a 6-damage hit every second or so (34 HP to 0 in about four seconds) and dies. The game then goes back to the title (camera STITLE) and quits to DOS ("Thanks for playing!") before the macro's `l 1 l`, which arrived at the DOS prompt (INFERRED: the macro's Esc on the title quits). The same happens with the port's save with the hit handler ended, and with the held save after setting TOWBOT1 / TOWBOT2's counter to 0 in TOWER.IFF. Setting it for bots 3-6 only (hidden, not firing in zone 3) leaves Lex alive. So the saves are fine; a live check of a save whose enemies are active must start sampling right after the title, not after the load macro.
  - **Clearing the deck, tried in the port.** `_LexTowLoc` changes only when Lex enters a TTBAT box, so after ZB he counts as zone 0, safe from every bot, wherever he stands outside the boxes. A bot has 28 HP and a laser takes 15. Results:
    - Bot 1 dies from ZB (two shots) with no fire at all.
    - With bot 1 dead, bot 2 is the only shooter in zones 3 and 4; walked into from the elevator door, it dies in three shots for 18-30 HP.
    - Bot 3 can only be hit from the strip between 4B and zone 5, and the aiming turns carry Lex into zone 5, where bots 3 and 4 fire. Healed in zone 4 (BIOREPAIR reached 64 on the battery he has), Lex died with bot 3 at 13 HP and bot 4 at 18.
    - Bots 4 and 6 cannot be hit from any safe spot tried (grids of spots, the bots held). Bot 6 does not fire in zone 5, and bot 5 fires only in zones 6 and 9, off the south route.
  - So the deck is clearable in principle, but not reliably with Lex's health and battery at this point. `hold-fire` stays.
- **The tower deck by keys, tried again and not merged (2026-11-08, port).** `hold-fire` stays. What was learned:
  - **The order that worked on the default stream.**
    1. Run (`dash`) from the cabin into ZB and kill bot 1 from there.
    2. With bot 1 dead, only bot 2 fires in zones 3 and 4: run to the cabin door and west into zone 4, and shoot it.
    3. Heal, then kill bots 3 and 4 from the strip between 4B and zone 5.
    4. Kill bot 6 from zone 5's south part, safe by then.
    - Lex reached the gun with 34 HP and finished the game. Over 25 streams, 17 finished (22 with the bots held). After a save, or after only an animation restart, the same route lost at bots 3 or 4.
  - **Where the lasers reach bots 3 and 4,** from a grid with the bots held and the aim set outright (three shots per spot):
    - Bot 3 is hit only from x 27200, y -56000 to -56500.
    - Bot 4 is hit from x 26700-26950, y -57500 to -59500. That is the edge of zone 5, where by then only bot 4 fires.
    - Nowhere else in 4B or the strip (x 26700-28200, y -59500 to -56000) hit either bot.
  - **Why it stayed fragile.** Each spot is a few hundred units wide, and the aiming turns (1.41 to 11.25 degrees a tap) move Lex off it or into zone 5. Bot 2 costs 18-48 HP depending on the recoils, and the heal before bots 3 and 4 only reaches about 64 on the battery Lex has here. Walking in along the line to the bot (`approach`) did not reach its stand-off points among the deck's walls.
  - **Kept: Roland and ZONE.** RESTARTGUN's "Move back!" loop waits while AMINTRIGGER(PLAYER, ZONE) holds, and that tests Lex's hull. `roland` tested his centre point, so Lex could stand 33 units outside the box, still touching it, until the lander won (DROPSHIP_WINS). It now tests the hull. This only showed with the new deck timing; the run with the bots held is unchanged.

## The Captain by keys, won (2026-11-09, port; one live attempt, not confirmed)

`surface-fight` is gone. `playthrough_surface.captain_fight`: heal to 100 first (ZEDICAID lies by the ramp), hold KP1 through the shot that ends his speech, then tap Alt+KP4 (ATK_H4) every 6 ticks whatever he is doing. Lex stops only for his own recoils, turns or steps in when the Captain is off to the side or out of reach, and switches BIOREPAIR on under 60 HP if the battery allows.

- **Why it wins.** Each ATK_H4 does 10 and puts him in SUPER_REC, and the next tap lands before he recovers: on the default stream 18 hits in a row with Lex untouched. A rhythm needs no reaction time. From the default stream's state the rhythm hardly matters (10 of 11 at 4, 6, 9 and 12 ticks; 12 of 15 in a second batch at 6).
- **What did not work.** ATK_F9 tapped the same way won 1 to 4 of 11. Holding the attack key won 2 of 27. Fetching BLASTER2 (it lies by the lander): a laser hit breaks his swing (RECOIL_ML) but does no damage, and shooting costs Lex his attacks, 0 of 27.
- **The dropped items.** He also drops KEYDVICE, and Enter takes the nearer item, so the run stows it (I) and presses again. Something stops a straight walk across y -1059616 west of the ramp, so Lex goes round by x -1085500.
- **Result.** In the first version none of 26 streams lost to him. After the tower changed the timing, the default stream lost, on 81 HP with 7 charges unused: `heal` will not spend a charge that would overshoot 100. From that state the win rate was 6 of 12 at every rhythm from 3 to 12 ticks (2 of 12 at 16), so the rhythm hardly matters and the starting health does. The run now tops up once more before the fight. 2 of 26 streams still lose to him.
- **Live (DOSBox-X, Easy, a port save at the end of his speech).** One attempt with stepping and turning: the dodge worked, H4 did 10 a hit, and five hits landed with Lex untouched, as in the port. Then the chain broke and Lex lost with the Captain at 150. Two more attempts did not load in time to count. The driver presses keys through the debugger, pausing between them, and does not re-enter combat mode after a knockdown as the port's routine does, so this neither confirms nor refutes the tactic in the original.

## The tower bots shot (2026-11-09, port; the firing spots checked live)

`hold-fire` is gone. `playthrough_full.tower_bots` runs first in the `tower` leg.

- **The rule that makes it possible.** `_LexTowLoc` changes only when Lex enters a TTBAT box (the test uses his hull), and each bot fires only in its own zones (AI_TOWER.scr). Bot 1: 1 and 3-7. Bot 2: 2-7. Bots 3 and 4: 5-7. Bot 5: 6 and 9. Bot 6: 7 and 8. Zones 0 and 10 are safe from all. So zone 4 is safe once bots 1 and 2 are dead, and zone 5 once bots 3 and 4 are too. The deck has no way round: from ZA, ZB and zones 1 and 2 Lex is walled in.
- **The order and the spots** (grids with the bots held and the aim set outright, three shots a spot):
  1. Bot 1 from ZB (zone 0).
  2. Bot 2 from y -58800 to -58300, x 26700 to 30000. Lex aims in ZB for where he will stand, then sidesteps north (a sidestep keeps the heading), so his first shot leaves before it answers. Two shots, no damage on the default stream.
  3. Bot 3 from around 4B: x 27300 to 28700 at y -58900 to -58100, and the whole strip x 26600 to 27400 down to y -54600.
  4. Bot 4 from the strip, x 26600 to 27300 at y -58900 to -58600. Lex must stay east of about x 27000, or his hull enters box 5.
  5. Bot 6 from y -63000 to -62600, x 21800 to 26200 (zone 5).
  Bot 5 fires only in 6 and 9, off the route, and is left alive. Bots 3-6 must be visible to be hit: they are hidden on ELT1 and ELT2, so a test must walk to the spot rather than move Lex there on those cameras.
- **Why the earlier attempts were fragile.** They hunted for narrow spots, and a walk of a short distance overshoots: a `goto` from x 27650 ended at 26778, in box 5.
- **Result.** No stream of 26 fails on the deck, and 21 of 26 finish. The others: the Captain on 2 and 9, an airlock on 5, Drogg 1's bridge on 16, GRDHANG on 25. `save_resume_check` reaches `EXIT` from 27 of 29 saves before the hangar monitor's retry was added. After a save mid-recoil Space does nothing until the motion lets go, so that step now retries, and the `grdcon` save gets past it (Drogg 3 then kills Lex on that continuation). After a save at the tower arrival the harness failed bot 3, walked into zone 5 and died; with only the animations restarted the deck is cleared. Explained in "A save point on the tower deck".
- **Live (DOSBox-X, Easy, the held save, Lex moved with `set_xy`, the aim set with `set_heading`).** With the bots held, every spot worked: bots 1, 2, 3, 4 and 6 all died from the positions the run uses (a shot at bot 3 from its spot also took 15 off bot 4 on the way). With the bots on, Lex took no damage in 5 seconds in zone 0 and killed bot 1 from ZB. Bot 2 then knocked him about through four shots and the rest failed, but that run moved Lex in and set the aim late rather than pre-aiming, so the ready-aimed entry is checked only in the port. A hit from one bot's laser on another took 10 (NRLASER_HIT_TOWBOT1), Lex's takes 15 (LASER_HIT_TOWERBOT, as the port).

## A save point on the tower deck (2026-11-09, port)

Milestone 5's two remaining failures, `hall-to-elevator` and `grdcon`, replayed under several random streams (`save_resume_check`'s three cases: unchanged, animations restarted, saved and loaded).

- **A load makes the saved camera current.** The restore ends by switching to the saved camera (`1148:0490` -> `1130:0114`) and runs no room events. Both ports kept the name only as a fallback and left the current camera empty until the first automatic switch. Both now set it, silently. This fix alone changed none of the results below.
- **A pillar stood in bot 3's line.** At `hall-to-elevator` the bots have two lasers in the air. The port does not save missiles, so after a load they are gone, Lex takes no knockback and ends up about 110 units further east. From there all Lex's lasers stop at about (26990, -54870), and in 8 of 8 streams he never hit bot 3. `tower_bots` now sidesteps west to x 27300 after two misses. The default run hits first time and does not use it.
- **Missiles in saves: done 2026-11-14** ("Missiles in saves"). Both ports now keep the two lasers in the air at `hall-to-elevator`.
- **`grdcon`, before the paused-bit fix below.** Of 25 streams from that point, 20 finish unsaved, 20 with the animations only restarted, 14 from the save. Drogg 3 and GRDHANG kill Lex about as often either way. The other failures after a save are single steps: Space or Enter not taking (HANGRMON, the bridge button, TONFA, REFLECT), the inventory not closing, Drogg 1's bridge, the beach route. Two of them come within 350 ticks of the load, the others far later. - **A load kept no process paused.** The two failures soon after the load (HANGRMON, the inventory) came from this. Bit 0 of a process's flags (+0xe, in the task memory the save keeps) is its paused state. The writers stored it and the loaders never read it, so a load woke every paused process, among them GRDCON_AI, which hit Lex in the first seconds. Both loaders read it now. From `grdcon`, 18 of 25 streams finish after a save (14 before), against 20 of 25 unsaved. No save-only Drogg 3 or interaction failure is left there; the remaining ones are the Captain (3 of 25; unsaved 1 of 25), a hall button, BIKE_USE and two walks.
- **`save_resume_check` after the camera and pillar fixes:** 27 of 29 from the save (26 after the paused-bit fix, with the same Captain wait the unsaved game sometimes fails). `hall-to-elevator` clears the deck and fails later at Drogg 1's bridge; with the animations only restarted it fails too (TONFA), so milestone 5's exception covers it. `grdcon` fails only from the save (Drogg 3, Lex arrives with 27 HP against 51). The control passes 26 of 29.

## The last three save points (2026-11-09, port)

After the paused-bit fix, three saves do not reach `EXIT`. State at each stall:

- **`grdcon` and `forklift`: the Captain won.** Lex is dead and TUMOLT alive, so the wait for his death scene never ends. Lex enters at 100 HP from the save as he does without one. Close fights: the Captain had 10 and 80 HP left. `captain_fight` now uses up to four medkit charges under 35 HP, as a player would, and fights on if a blow closes the monitor under a click. With that the Captain no longer stops stream 2, and the restart control goes from 26 to 27 of 29; the saves stay at 26, these two still lose.
- **`hall-to-elevator`: Drogg 1 never reaches the bridge.** After the sixth super recoil his AI runs `GO DCENTER RUN` (AI_DROG1.scr), INVULNERABLE and AI held by the GO. He was left at (-10836, -140148), 2130 units from DCENTER, and runs on the spot against something between them. Stream 16 stops the same way with no save. Fixed 2026-11-14: the ports never re-aimed a GO, and he had run past DCENTER into a wall ("GO steering"). The save's only part is that it moved where the fight ended.
- **Since GO steering (2026-11-14).** `hall-to-elevator`, `grdcon` and `forklift` now continue to EXIT; the one failure left is `operating-room` (Drogg 3 wins from the save, the Captain with the animations only restarted), a fight lost on a moved random stream. Saves 27 of 29, control 28 of 29; seeds 20 of 26, against 22 before; with `take`'s detour all six that stop are lost fights (Guard 1 twice, GRDHALL, GRDCON, the Captain twice), none a stall.
- **Conclusion.** No lost state is known behind these three. Milestone 5's done-when line still fails by its letter on all three, since each passes with the animations only restarted.

## Performance over the whole game (2026-11-08, native, release build, Apple M4 Pro)

`FullRunTests.frameTimes` (opt-in: `FULL_RUN_PERF=1 swift test -c release --filter frameTimes`) replays the whole recorded run, 158039 ticks, and after every tick draws the frame the app draws (`World.renderPresentation`, then `applyPresentation`, as `AppDelegate.redrawGame`). It times each tick against the 33.3 ms of the 30 Hz clock. Metal's upload of the 320x200 image is not timed.

- **Results.** Mean 0.50 ms, median 0.52, 99th percentile 0.94, 99.9th 1.63. Inside a level no tick reaches the budget; the slowest is under 25 ms.
- **Level loads.** Every tick over 10 ms is a level load, 24-116 ms. The slowest are TOWER to CONTROL (116) and TITLE to CHAOS (85); the other six over budget are 35-39 ms. So a level change can drop one to three frames. The original also stops to load a level from disk. Not measured: how long the original's loads take.
- **The test's rule.** It fails if any tick inside a level exceeds the budget, and prints the 14 slowest ticks with what happened on them.

## High-resolution art (2026-11-09/10, native app only)

Presentation only: `World.hiResFrame` reads the world and repaints the same cels as the indexed renderer (`Compositor.hdCels`) into a 640x400 picture of palette indices; the indexed renderer and its oracles are unchanged.
The app shows it through the same palette as the 320x200 picture, so gamma, CHANGEPALETTE and FADE need nothing extra; RUMBLE shifts it by doubled offsets in the same `applyPresentation` call, so the shake still advances once per frame.
Findings (not live checks against the original; this path has no original to match):
- The art: 789 full-screen frames in `ROOMS/*.CAM`, 324 of them with 32 or more colours, plus 5,098 smaller frames; 1,036 mesh textures, about 5 million texels.
- Texture names are not unique (41 of 623 name-and-size pairs have different art), so the pack names textures by FNV-1a of their indices.
- `DATA/PALETTE.IFF`'s palette starts 12 bytes into its PALT chunk (after the chunk header and a 4-byte field); indices 0x70-0xfe equal the room palettes checked (CE11, CTR1, BCH1, TWR1), so textures made with it fit those rooms.
- The first prototype (PR 95) drew a true-colour 4x AI upscale with Metal and linear filtering. It looked washed out and over-sharpened, so it was replaced.
- Bake-off at 2x on CE11, BCH1, CTR1, TWR1, TUN1 and Lex's torso texture (sheets in `re/out/upscale_test/bakeoff`). The share of pixels changed against plain doubling: Scale2x 4-7%, MMPX 2-3%, and the AI-guided filter 18-30%. On these pre-rendered, dithered rooms Scale2x and MMPX are hard to tell from plain doubling, as MMPX's authors warn for dithering. MMPX twice (4x) adds contour bands. The AI-guided filter was chosen.
- The filter (`pixel_filters.constrain`) halves the model's 4x picture. Each of a pixel's four new pixels takes the colour in its 3x3 source neighbourhood closest to that guide; at least two keep the source colour. So no colour is invented and the art stays indexed. Its weak spots are slightly noisy edges and painted markings (the "05" on the ship in BCH1), which is what `--overrides` is for.
- For MMPX, filtering each piece alone against filtering the composed room and recutting differed in 0.12% of pixels (CTR1). For the AI guide the context matters, so `pixel_pack.py` filters each frame in place on the finished room.
- The game's own frame encoding cannot hold a 640x400 frame (16-bit row offsets), so pack files are 'BFX2', width, height and raw DEFLATE of indices and mask.

### Built in the app, 2x or 4x (2026-11-10)

- 4x is one pass: the model's own 4x picture is the guide, each of a pixel's 16 new pixels takes a colour of its 3x3 source neighbourhood, at least 8 keep the source colour. Running the 2x filter twice (on the 2x picture, with the model run again on it) looked smoother but more painted, and costs about five times the model time; one pass costs the same model time as 2x.
- Size: the original art (`ROOMS`, `BODY`, `ITEMS`) is about 33 MB; the 2x pack holds about 90 MB of files (about 100 MB on disk); a 4x pack was estimated at about 250 MB (four full frames compressed 2.8 times larger at 4x than at 2x).
- Core ML (`re/tools/convert_model.py`, fp16, input up to 320x200) against torch on MPS: on the CPU and GPU the guide differs by up to 2.5 of 255 and 0.5-0.6% of output pixels change after the filter (CE11 0.57%, BLK5 0.49%), about 14% faster (BLK5, 36 frames: 5.0 s against 5.8 s); on the Neural Engine 2.4-2.8% change and it is slower (9.4 s). The app uses CPU and GPU.
- The model's licence: CC0 when chosen, replaced on 2026-10-19 by the "HDcube Model License": redistribution only of the original file, unmodified, with its notice; permanent changes to the weights for redistribution need the author's written permission; no rights claimed on outputs. A converted model counts as changed weights, so shipping it waits for permission. In an fp32 conversion 563 of 702 weight tensors are stored byte-for-byte; the rest are transformed (assembling the model on the player's Mac from the original file would need that mapping).
- `PixelPack.swift` ports `pixel_pack.py` (factor 2 or 4); `constrain` matches Python exactly on `Fixtures/pixel_filters.json`. The build order is textures, the current level's rooms, then the rest; files are written atomically and existing ones skipped, so a stopped build resumes.

### Monitors, options and captions (2026-11-10)

- Monitor art goes through the same pack: `monitors/<CAM>/<ENTRY>.<frame>.frm` for the 39 `MONITORS/*.CAM` files (the background entry like a room background, other element frames standalone like textures). L and T elements are skipped (their frames hold style bytes: 5 state colours and a font number), as are V elements (only the live camera is drawn there) and 1x1 dummy frames. Build order: textures, the current level's rooms, monitors, the rest.
- The `complete` marker holds a version (`2`); an older pack without it counts as unfinished, so the app offers Build again and only the monitor files are made.
- Text (labels, lists, credits, the journal, captions, subtitles) is drawn at the target scale in the game's own fonts with the same layout, each font pixel an s x s block (`HDText.scaledGlyph`, one function). A comparison against MMPX-smoothed glyphs was made; the blocky look was chosen as the faithful one.
- Live camera viewports in monitors are computed at 320x200 exactly as before, then enlarged. A flic with a caption is the flic enlarged under a full-resolution caption; a flic without one stays 320x200.
- Without a pack, every monitor, options and caption frame at 2x and 4x equals the 320x200 frame enlarged (HiResScreensTests).

## Difficulty: every use, and Medium and Hard checked (2026-11-19, both ports; from the decompile and scripts)

`_difficulty_level` (0 Easy, 1 Medium, 2 Hard) is an ordinary VARS integer (initial 0); the engine mirrors it at `[a36e]`.
- Engine: set by `FUN_1280_2335` (the dialog's EZYX / MEDX / HRDX through `FUN_1280_07d8`), copied back after a load by
  `FUN_1148_0490`, read by `FUN_1098_0088` (motion time: others +0x80 at Easy, -(level << 6) above; the player's repeated
  ATK_H / ATK_F adds count x 0x40 x level x 16) and `FUN_1090_09b9` (damage: player target -4 at Easy, +4 x level above; others
  -4 x level; not in `re/decomp`, from the disassembly notes above). No other `[a36e]` read was found; no item amount, hit chance
  or pickup depends on it.
- Scripts: AIRMECHO's volley wait (70 - 20 x level), laser damage (45 / 35 / 25) and bolt speed (3 / 4 / 5 west of x -82);
  Fluffy's look-up wait (14 / 10 / 8 s); Drogg 1's KO counter per laser hit (+3 / +2 / +1); the nursebot's COMBATCLUE log entry
  (Medium and Hard only); the beach and landing-pad bots' waits around FIRE (`_easy_wait` 45, `_medium_wait` 30, `_hard_wait` 15).
- All of these are in both ports (engine items in `world.py` / `WorldPlay.swift` / `WorldCombat.swift`; the script items run
  through the VM). Saves keep the level (`test_save` / `SaveLoadTests` "hard stays hard").
- Escape on the new-game difficulty dialog does nothing, in the original as in the ports: `FUN_1280_090e` would keep the level and
  close it, but the key handler only calls it when the dialog's flags have bit 2, and START.scr opens it with `_OPTS_DIFFICULTY` = 512.
- Smoke run (scratch, not kept): the full route with Easy through the prison and Lex's HP topped up every tick. Medium got through
  19 of 31 legs (to the beach), Hard 15 (to Drogg 1). Both stops are the scripted route's: at Medium the beach bots fire every 30
  ticks and keep Lex recoiling past the pickup's time limit; at Hard each laser hit adds 1 to Drogg 1's counter, and the route fires
  a fixed number of shots. The only warnings were the `BREAK n` ones every Easy run has too (above). Nobody has played Medium or
  Hard to the end; the route would need its own tuning per level. (Superseded by "Medium and Hard played through", below.)

## Medium and Hard played through (2026-11-20, the Python port's scripted route; not checked live)

`playthrough_full.py --difficulty medium|hard` (and `run_seeds.py --difficulty`, output under `re/out/run_seeds/<level>/`) plays the prison at Easy, as
before (`difficulty-easy`), and sets `_difficulty_level` after the `guard1` leg (shortcut `difficulty`; a player picks the level once, at the start).
Easy is untouched: its default stream and the Swift fixture regenerate byte-identical.

**Result:** Medium 1 of 27 streams finish (the default one: tick 165038, Lex 100). Hard 0 of 27. Of the 26 Medium losses: GRDCON 11 (2 of
them before the suit machine), GRDHANG 12, GRDHALL 2, and seed 4 in the prison (`caynans-arm`, played at Easy). Hard: every stream but seed 4
loses Lex on the tower deck (TOWBOT3 still up after the route's 4 shots).

What changed in the route above Easy (`playthrough_full.py`, `playthrough_surface.py`):
- The fighting routine keeps a quicker rhythm (`LEVEL_FIGHT_DELAY` wait 1, key 2, punch 1) and repairs under 65 HP (`LEVEL_HEAL_BELOW`); the
  sweep behind it is in the comment there (12 RANDOM streams of GRDCON).
- `tower_bots`: a dash that curves north, then east to the firing spot; the walk's half turn started 150 units from TTBAT4 and drifted Lex
  into its zone.
- `grdcon` heals to 100 first; a fight that ends with GRDCON up is now an error (a zero wait spun the routine to its step limit and the leg passed).
- `garage_block` gives the run its own rhythm back after the GRDHANG fight; it used to delete the attribute, which put Medium back on Easy's rhythm
  for GRDHALL.
- `grdhall` fails above Easy when the routine never hits him: he stays peaceful with the suit on, but BLASTER2 is the gun AIRMECHO's duel needs
  (OPRSCENE destroyed the BLASTER), so he cannot be walked past.
- `beach`: before a turn of more than 100 degrees on the zip blocks Lex takes a short step forward. On Medium the bots' hits change his walk to
  ZIP2_A, he comes off ZIP2_B facing back along the line (heading 39.8 against 1.8 at Easy), and the 118-degree turn on the spot (each
  TURN_LEFT step carries him about 200 units) took him over the block's +y edge into the sea. Easy's turn there is about 80 degrees.

Blockers (forked benches of 6-9 RANDOM streams per variant from the default Medium run):
- **The battery.** Lex's ATK_H4 does 11 to these guards instead of 15 (armour 5), their hits on him are 8 stronger than at Easy, and they
  animate faster. On the default stream Lex leaves the suit machine with 71 HP, battery 61 and MEDICAID at 4 charges. GRDCON costs 32 of the
  battery (and a charge in the heal before it); GRDHANG starts at battery 24, and a won fight ends at 41 HP and 18. The streams that lose
  have run the battery down to 9, the floor BIOREPAIR stops at. GRDCON to GRDHALL together win 3 of 8.
- **GRDHALL's cost.** The bike's battery brings Lex to 129; the GRDHALL fight (220 HP) takes 114 of it. Lex lands about 19 hits, GRDHALL
  13 of about 17 HP each, and he shoots BLASTER2 whenever they are apart (`MONSTER_MOVE` case 10, and near `STAY_OUT`, AI_GRDHL.scr).
  Lex reaches the beach with 13.
- **The Captain.** With no battery left for repairs, the Captain's hits (14 to 24 on Medium) win: 1 of 6 beach streams after the zip fix.
  `CAPTAIN_RHYTHM` 6 or 12 and `CAPTAIN_MEDKIT_BELOW` 50 change nothing; `CAPTAIN_STEP_IN` 3000 loses all 6.
- Hard stops at the tower deck before any of these.

Tried without gain: ATK_H8, ATK_H9, ATK_F9 and ATK_F7 instead of ATK_H4 (H9 never connects with GRDHALL; the others lose more); blocking with
ATK_H2 when the guard's strike starts (the guards' hits land on Lex's lower zones, which ATK_H2 does not guard: 0-1 of 8); a lower repair threshold
for GRDCON so the medkits refill afterwards (1 of 8); medkit charges mid-fight (in the garage Space takes the lift, elsewhere a blow closes the
inventory); GRDHANG at a repair threshold of 80 or 90 (5-7 of 9, within the noise of the 65 it keeps). Winning these fights at Medium needs a
fighting routine that reacts to the guard, not more tuning of this one.

## BREAK n: switches are numbered per file (2026-11-19, both ports; from the decompile, checked on every script)

- The runtime BREAK (`FUN_10d0_0b77`) decodes n as `((b0 & 0x3f) << 6) | (b1 & 0x3f)` (`FUN_1118_4b48`) and jumps past the n-th
  entry of the *script file's* switch table (count at +0x21, 0x18-byte entries at +0x23), restoring that switch's nesting depth;
  n beyond the table is error 0xc9 and ends the process; an empty operand is `ERR_BREAK_NOT_PREPROCESSED` and the statement does
  nothing (the next one runs).
- The table is built per file at load (`FUN_1118_147f`), numbered by `FUN_10c0_01cc`: one counter over every SWITCH line of the file
  in line order, through all routines and timelines, never reset at a block. The compiler (`FUN_1118_1e45`, for `.SCR` source)
  writes the innermost enclosing SWITCH's number into each BREAK; loading the shipped `.SCP` files keeps the stored numbers.
- Checked on all 107 scripts: 837 numbered BREAKs, every one equals its innermost switch's per-file number (154 sit in a nested
  switch and target the inner one). So "leave the innermost switch" was always the right target; only the ports' per-block
  numbering was off, which made every warning such as `CAYNAN_PACE ... BREAK 2 != innermost switch index 0` (the warning now
  stays as a consistency check and never fires on the shipped data; `test_interp.ParseAll`).
- `FUN_10c0_01cc` reads only a line's first statement, so the six inline `IF ISHANDLEPLAYING _HalMecho_speech THEN BREAK` lines of
  HALMECHOSPEECHES (`AI_MECHO.scr` 321-366) were never numbered: in the original they do nothing, and each speech follows on its
  fixed WAIT whether or not the last clip has finished. The ports used to leave the switch there (holding the next speech until the
  clip ended); both now let a bare BREAK do nothing. ASSUMPTION: that the argument slot after `THEN` is empty was inferred from the
  blank operand bytes and the error's name, not traced through the argument collector.

## Released loops play their tail (2026-11-20, from the decompile, checked live)

- **Release.** STOPAMBIENT (`10d0:777a` → `1028:10c9`) finds the voice by its handle. A voice with the loop flag (+0x3a) is released:
  `1000:046f` sets the voice's end (+0x10) to the sample's end (+0x0c) and its state to 2. The mixer (`1000:115a`) plays on from where the
  voice is; at the end it wraps to the loop start only in state 1 with a loop length, so a released voice runs to the sample's end and
  `1028:1bef` then frees its slot and clears the handle. ISHANDLEPLAYING (`10d8:2baf` → `1028:0e3b`) asks only whether a voice slot holds
  the handle, so the handle plays until the tail ends. A second release changes nothing. Each wrap sets the position to the loop start
  exactly (the overshoot is dropped); the ports keep it (sub-sample, not heard).
- **The loop field is a length.** AMBIENT (`1028:0f0a`) hands the header's +0x08 and +0x0c to `1000:03de`, which sets the loop start to
  start + loop_start and the loop end to that + the +0x0c value, so +0x0c is the loop's length (0 = no loop). The ports read it as the end
  until now. As a length every one of the 45 looped samples fits its data (`drip1b` and `hum3a` loop the whole sample). Both readers
  (`sound.py`, `SoundBank.swift`) now give `loop_end` = loop_start + length.
- **Ports.** `release_loop` / `releaseLoop` (audio.py, WorldAudio.swift) wrap the integer position at the release and time the rest like a
  one-shot (`length`, `pos30`, re-timed by a pitch change). `sound_releases` / `soundReleases` reach both mixers (movie.mix_audio,
  SoundMixer), which play on from the wrapped position without wrapping; their output matches sample for sample (`test_audio`,
  `AudioTests.releasedLoopPlaysItsTail`).
- **Where it shows.** AWAKEN's SMALL_QUAKE (`AWAKEN.scr:239-251`) releases `_quake_1` after 2 s and waits while ISHANDLEPLAYING, so the
  opening waits out the rumble. Live (DOSBox-X, the process list sampled every 6-7 clock ticks): SMALL_QUAKE lives 187-225 clock ticks.
  The port: 224 (with the old end reading of +0x0c it would be 266, without the tail 122). Every later opening event comes 52 ticks later
  (`scenarios.QUAKE_TAIL_SHIFT`). The elevator hum and TOWERGUN's fly-by are released too.
- **Gates for the batch.** Seeds 24 of 27, control 29 of 29, saves 28 of 29. The one save that fails is `reactor-room`, and it fails
  on the harness's battery margin, not on lost state. From the save, Lex's leg battery is 444 at the start of the bike leg, against 473 with
  only the animations restarted (the beach and the way back to CONTROL went differently and spent more). By `bike`'s check it is under
  BIKE_NEEDS (375), so the run takes `battery_trip`, and Lex dies on the LANDPAD ledge on that trip (traced 2026-11-21: `battery_trip` ran
  the ledge at x 25700 with stops, in the bots' reach; it now uses `ledge_run`, re/playthrough/full.md). Main saves at another tick
  (87308 against 90271) and continues to EXIT. The default stream without a save reaches the bike with enough battery.

## Engine assumptions settled (2026-11-20, from the decompile)

- **Animated textures.** See `ANIMATE`: a texture is drawn at its ANIMATE frame, frame 0 until a script animates it. The fixed 4-tick
  cycle is gone. Shrapnel carries no state and shows frame 0 (INFERRED).
- **Automatic cameras after a level load.** `1290:63da` is written only at boot and new game (`1128:0901` / `0b98`, 1), by CAMERA UNLOCK
  (`10d0.c:1099`, 1) and by CAMERA <cam> / SHOW / AT (0). LOADLEVEL leaves it as it was; the ports no longer switch it on at each load.
- **Camera distance.** The acceptance test `1110:1a95` and the nearest-camera ranking (`1130:0fa3` → `1208:13e3`) both measure
  `FUN_1210_0f9b` (approx_length) from the camera's eye (+0xb) to the followed object's position; the first camera wins a tie. The ports
  used the Euclidean length.
- **LOADLEVEL kills.** `1148:14a3` → `10b0:13fb` walks every kernel task and kills each one but a leading class-0x110 task (the sound
  manager's, not modelled) and the caller with every context on its +0x71 links. There is no boot-chain exemption: a process the ports
  fired as 'global' dies like any other, and so does the FADE task. `end_unloaded` still lets a 'global' caller go on (its file, START.scr,
  stays loaded). CALL now links the caller before the child's first slice, so a LOADLEVEL in that slice spares it.
- **LOADLEVEL voices.** After the load, `1028:12d2` (`10d0.c:4401`) stops all 8 voices and the pending ones except the voice whose handle is
  LOADLEVEL's first numeric argument (ctx+0xe2b, the argument slots ISHANDLEPLAYING reads): ELEVATOR.scr's `LOADLEVEL TOWER ELV ELT _sfx_5`
  keeps the hum, which EXITSTASIS later releases. The ports stop every other sound handle (logged, so the mixers end the voice) before the
  kill walk; no script runs between the two steps.
- **CALL and PROCESS.** CALL (`10d8:0e95` → `10c0:3968`) creates the child without running it, links it, runs its first slice itself and
  returns the child's value at once if it has ended, else the caller waits (+0x46 / +0x47). PROCESS (`10c0:37e9`) runs the first slice
  only if the caller's block is a `{` routine (+0x22 of the block record, as `1120.c:28`); from a `[` timeline (AI_DROG2's ROCK_BUSTER)
  the child waits for the scheduler and first runs in the next walk (see the next point).
- **A woken waiter runs in the next walk.** RETURN (`10d0.c:6062-6090`) and the end of a block destroy the child (vtable+8 of the script
  context vtable DS:3031 = `10c0:47b4` → `10b8:0c39` → `1238:1165` → `06ea` → `05bf`), which notifies its +0x20 links through
  `1238:0000`. The link a CALL made (`10c0.c:3116` → `1238:0f48`: child +0x20 gets 0x4000|parent slot, the parent's wait list +0x16
  the child's slot; SUSPENDWHILE and the other waits use 0f48 too) takes the 0x4000 branch to `1238:077f` (`1238.c:379-459`). It marks
  the entry done and, the list satisfied, calls `1230:177a` and frees the wait list (`1240:01b7`). It never runs the task. vtable+0xc
  (`10c0:48a2`) is reached only with the waiter's 0x10 flag, which 0f48 does not set; vtable+0x28 is `10b0:1091`, empty.
  `1230:177a`/`1799` (`1230.c:1131-1158`) set the task's flag 0x40 when a walk is under way (`[989f]`, set and cleared by the walk,
  `1230.c:166, 237`) and the task's slot (+2) is above the walk index `[989a]`; the walk (`1230:0259`, `1230.c:172-180`) skips a 0x40
  task once and clears the flag, before the wait and pause tests and the task's update. A waiter below the index was already passed.
  Either way the parent of a CALL, a SUSPENDWHILE waiter and a JUMPON watcher waiting on a process go on in the next walk, one tick
  after the child ended; outside a walk (`[989f]` = 0, engine code) nothing is flagged and the next walk runs it. The task constructor
  `1238:024c` registers the task (`1230:0a3d`) and calls `177a` (`1238.c:154`): a task created during a walk is never run by that
  walk, which is why PROCESS from a `[` block and every spawned child's second slice wait for the next walk. Slots are the lowest free
  index of the table (`1230:09da`, `1230.c:510-536`; it grows by 30), kept for the task's life (`049b`/`053f` only trim free tail
  slots). The ports had run the waiter inside the child's finish; they now clear its wait and, during a walk, hold it for the rest of
  that walk (`hold`, the 0x40 flag). Still different: among ready tasks the ports walk in creation order, the original in slot order
  (lowest free slot); the two differ only after a slot is reused, and matching it needs every kernel task (Wait tasks, sounds, motion
  tasks) in one table. Figures are not tasks: they are updated before the walk ("Lex's height in the zero-g room" below). Shifted by
  one tick: every CALL return, SUSPENDWHILE and process-handle wake-up.
- **Lex's height in the zero-g room (2026-11-20 live, 2026-11-21 from the code; both ports).** TO_0G_USE (TUNROOM.scr:169-207) does
  `AI OFF`, `CALL LEAVETUBEROOM` (TUBES.scr:1-44, ending `SUSPENDWHILE FIRE ZIPPY ...`, then `AI ON`), then `AI ON`, GRAVITY OFF,
  COLLISIONS OFF, STOPMOTION and `GO GFROMTUN`. Without gravity GO puts the figure's z at the waypoint with the current R (model +0xa6)
  still in it, and the next motion's first update re-bases z by the change of R; a motion's frame 0 reaches R only at its first update.
  Live (DOSBox-X, a port save at TO_0G loaded in the original, Space, Lex sampled at every entry of his update function, `frame_samples`):
  the zip ride ends with R 974 (ENTER_GRAV's last frame) and motion ''; the next entry shows `stand` with R 974; the one after it z -4565
  (GFROMTUN) with R 974 still; then FLOAT (ZEG_LOAD), and at FLOAT's first update z -5539, R 0, hull -7832 .. -4352. So the figure
  update between LEAVETUBEROOM's `AI ON` and TO_0G_USE's GO did not start STAND. Why, from the code:
  - The frame (`1150.c:950-970`, the game loop) runs the camera manager, then the world update `1110:08bf` (items, then every figure's
    vtable +0x08, `FUN_1088_39ef`), the render, and only then the scheduler walk `1230:0259`. Figures are not kernel tasks (Lex's
    object is not in the task table at DGROUP 0x9888) and are not interleaved with the scripts: the ports' order (`vm.tick_once`, then
    `World.step`) is the same cycle. (CORRECTED: the 2026-11-20 note put it down to the walk order among slots.)
  - LEAVETUBEROOM's `AI ON` brings the counter +0x229 to 0, so `10a8:1f2e` requests the idle: `FUN_1098_0745` pushes `0, 0, 1`, the
    name (`atk_stand` at DS:2994 in combat mode, else its tail `stand` at DS:2998) and the figure, and calls vtable +0x7c = `1098:0e49`
    with param 4 = 1, param 5 = 0. That branch makes the motion task (`FUN_10e0_0000`, class 0x46f5, type 0x108) and runs it at once
    only when param 5 is 1. Its run (`10e0:0055`, vtable[0]) is what starts the motion on the model (`FUN_1098_06e0`, flag +0x4b); later
    runs only poll. Made during the walk (`1238:024c` -> `1230:177a`), the task first runs in the next walk, so the figure update in
    between keeps the old motion and its R, and STOPMOTION (`FUN_1088_3229` ends the 0x108 task) or a GO before that run never see
    STAND. A MOTION command's request (`10d0:5e8b`) and the idle at a figure update's end (`1088:4155`, outside the walk) start the
    motion when they are made.
  Both ports now defer the in-walk idle request (`World.request_idle` / `World.requestIdle`, started by `start_pending_idles` /
  `endOfWalk` at the end of the next walk; a STOPMOTION or a new motion before it drops it, INFERRED for the new motion). Entered by
  TO_0G_USE Lex floats at -5539, and the full run flies into TO_FINAL with nothing staged. Before, the ports started STAND inside
  `AI ON`: the GO kept R -40 and Lex floated at -4525, where his FLOAT hull top (-3338) is 53 units above the exit corridor's (PHYS
  HLL01, space, top -3391) and every flight bounced. Not ported: the `stand` name the live sample shows before the task ran (+0x15f
  is written when the request is made, the port's `Figure.motion` changes with the motion), and the COMBATMODE command's own idle
  request (`10d0:1b69` -> `FUN_1090_077b` / `0800`, then `FUN_1098_0745` when `1088:508d` allows it): the ports only set the flag.

## General MIDI timing (2026-11-20, the Mac app)

- The Miles driver runs the XMIDI timeline at 120 steps a second, so a note does not wait for the game's 30 Hz frame (correction
  2026-11-20: the timer is 60 Hz with two steps per serve, "AdLib music" > Timing, so the original sends General MIDI messages in
  pairs of steps; the GM path still schedules each at its own step). The AdLib path already
  kept that timeline (OPL2Stream); the General MIDI path sent each tick's messages when the tick produced them. `AudioScheduler` now gives
  each message a delay of the effects' latency pad (2048 frames, 93 ms) plus its time minus the tick's time, and the Mac synth schedules it
  in the audio unit's event list (`scheduleMIDIEventBlock`, AUEventSampleTimeImmediate + offset). Checked offline: notes scheduled 0, 50,
  100 and 237 ms ahead start at 0, 50, 100 and 237 ms. Music and effects of one tick now also sound together, as both do in the original.

## Art builder: backgrounds and pointers only (2026-11-20)

- Menu and monitor elements are drawn plain-doubled (STATUS "High-Res Art: menu and monitor elements plain-doubled"), so the monitor pass of `PixelPack` /
  `pixel_pack.py` builds only frame 0 of each CAM's background entry. A CAM without one is a pointer (POINTER.CAM, or one MON_SETPTR names:
  PCAYHAND in the shipped scripts), and every frame of its first entry is built. Packs built before keep their element frames, unused.

## GRDCON resampled (2026-11-20, live)

- **Why.** The first sample ("Fights sampled in the original") had Lex's punches landing less often live (0.34 a press over 41 presses,
  against 0.54 in the port), the one fight figure the port did not match.
- **Resample.** `fight_sample.py live grdcon --attack alt-48` (Alt+KP8, no suit, Easy), 6 fights run one after another, then
  `fight_sample.py port grdcon --attack alt-48 --seeds 24` with the same loop and LATENCY. Original / port:

  | Fights | Wins | Lex HP lost per 1000 | Enemy HP lost per 1000 | Hits per punch | GRDCON attacks per 1000 |
  |---|---|---|---|---|---|
  | 6 / 24 | 0 / 2 | 26 / 35 | 27 / 36 | 0.47 / 0.48 | 3.5 / 5.0 |

- **Result.** Lex's punches land as often in both (0.47 against 0.48), so the old 0.34 was sampling noise. Which attacks land matches too:
  ATK_H4, H6, H8 and H9 never hit Lex in the loop's stance, in either; H7, F6 and F1 land most. Damage per hit matches (Lex 20; GRDCON
  6, 11, 16, 21).
- **Pace.** Both sides lose HP about a quarter slower per clock tick in the original, at the same ratio, and GRDCON starts fewer attacks
  (3.5 against 5.0 per 1000). The first sample did not show this for Lex (42 against 43), and fights 5 and 6 ran while other jobs loaded
  the machine, where a debugger round trip probably costs more clock ticks than LATENCY allows for (not measured). So it is taken as the
  sampling's delay, not a port difference; a quiet-machine resample would settle it. Logs: `re/out/fight_samples/grdcon/alt-48/` (not in git).
