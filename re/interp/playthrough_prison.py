"""Playthrough harness for the prison stretch: a new game through CHAOS and TANKS up to the elevator that leaves the prison.

The main path is mapped in re/playthrough/prison.md (script citations there). Each segment drives the Python port with real
scripts and real input (PC scan codes through World.key_down / key_up, monitor buttons through the pointer and mouse button).
Where key driving is impractical a staged shortcut is taken; every shortcut is listed in SHORTCUTS below with its reason and is
recorded in the run's report, because each one is a gap to close later. Problems seen on the way (crashes, stuck states,
warnings, unmodelled calls, wrong-looking behaviour) are collected per segment.

Run from the repository root:
    re/.venv/bin/python -I -W ignore re/interp/playthrough_prison.py --out re/out/playthrough_prison
"""
import argparse
import contextlib
import json
import math
import os
import random
import re
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import monitor as monitor_mod  # noqa: E402
import scenarios  # noqa: E402
import world as worldmod  # noqa: E402

KEY_ENTER, KEY_SPACE, KEY_I = 0x1c, 0x39, 0x17

# Staged shortcuts the harness may take, with the reason for each. A run records the ones it used (Run.shortcuts).
SHORTCUTS = {
    'difficulty-easy': 'The Caynan and Guard 1 fights are won by the scripted punch loop only at Easy (NOTES "CHAOS encounters"); '
                       'the opening dialog picks Medium. Set as the existing fight scenarios do.',
    'nurse-poses': "The nurse encounter's front/rear attack poses are the logged fixtures of scenarios.nurse_defeat_run.",
    'loadlevel-caller': "The statements after a level-owned caller's LOADLEVEL (FACE, GRAVITY ON, CALL ENTERCELL2, ...) are "
                        'performed by the harness, since the port ends the caller there.',
    'fido-puzzle': '_Fido_and_Scorp_are_DEAD = 1 before the TANKS load, as the Fido / cryo-pour puzzle (not played) leaves it. With it 0 '
                   'GONER (TANKCHEW.scr:2-65) sets Lex to 1 HP and FIRE TOSSes him to TOSSHERE, which is a scripted death (TANKDETH), not a '
                   'port gap; with it 1 GONER does nothing and TANKS_LOAD raises FS1-FS3 (POSITIVE), which the catwalk passes under.',
}


Stuck = scenarios.Stuck


class Run(scenarios.Play):
    """The shared driver: Play's keys and steering, plus segment bookkeeping, problems and shortcuts."""

    def __init__(self, world, vm, inputs=None):
        super().__init__(world, vm, inputs)
        self.segments, self.problems, self.shortcuts, self.checkpoints = [], [], [], []
        self._warn_seen = len(world.warnings) + len(vm.warnings)
        self._unmodelled_seen = len(world.unmodelled)

    # ---- bookkeeping
    def problem(self, severity, kind, message, segment=None):
        """severity: 'blocker' (the path cannot go on without a shortcut), 'major' (wrong behaviour on the path), 'minor'."""
        entry = {'segment': segment or (self.segments[-1]['name'] if self.segments else None), 'tick': self.vm.tick,
                 'severity': severity, 'kind': kind, 'message': message}
        if not any(p['message'] == message and p['segment'] == entry['segment'] for p in self.problems):
            self.problems.append(entry)

    catalog = SHORTCUTS                                   # a longer run (playthrough_full) swaps in its own catalogue

    def shortcut(self, name, **detail):
        self.shortcuts.append({'name': name, 'tick': self.vm.tick, 'reason': self.catalog[name], **detail})

    def collect_logs(self):
        warnings = list(self.world.warnings) + list(self.vm.warnings)
        for message in warnings[self._warn_seen:]:
            self.problem('minor', 'warning', message)
        self._warn_seen = len(warnings)
        for message in list(self.world.unmodelled)[self._unmodelled_seen:]:
            self.problem('major', 'unmodelled', str(message))
        self._unmodelled_seen = len(self.world.unmodelled)

    @contextlib.contextmanager
    def segment(self, name):
        """One step of the path: its outcome is 'passed', 'stuck' (Stuck raised) or 'crashed' (any other exception)."""
        seg = {'name': name, 'start_tick': self.vm.tick, 'status': 'passed'}
        self.segments.append(seg)
        try:
            yield seg
        except Stuck as exc:
            seg['status'] = 'stuck'
            self.problem('blocker', 'stuck', str(exc))
        except Exception as exc:                          # noqa: BLE001 - a crash is a finding, not a harness failure
            seg['status'] = 'crashed'
            self.problem('blocker', 'crash', f'{type(exc).__name__}: {exc}\n{traceback.format_exc(limit=6)}')
        finally:
            self.collect_logs()
            seg['end_tick'] = self.vm.tick
            seg['checkpoint'] = self.mark(name)

    def mark(self, name, frame=False):
        point = scenarios.checkpoint(self.world, self.vm, name, frame)
        point['lex_health'] = self.vm.objects.get('LEX', [None])[0]
        point['held'] = {hand: getattr(self.world.held_item(self.lex, hand), 'name', None) for hand in ('LTHAND', 'RTHAND')}
        self.checkpoints.append(point)
        return name

    @property
    def passed(self):
        return all(seg['status'] == 'passed' for seg in self.segments)

    # ---- waiting and input
    def until(self, predicate, ticks, what):
        """Tick until `predicate()` holds; Stuck after `ticks` ticks without it."""
        for _ in range(ticks):
            if predicate():
                return
            self.tick(1)
        if not predicate():
            raise Stuck(f'no progress in {ticks} ticks: {what}')

    def face_point(self, x, y, tolerance=8):
        self.face(math.degrees(math.atan2(-(x - self.lex.pos[0]), -(y - self.lex.pos[1]))), tolerance)

    def settle(self, ticks=200):
        """Let a script-started one-shot on Lex finish before the next key (LEVEL1TREMORS' QUAKE ignores the keys while it plays)."""
        for _ in range(ticks):
            if self.lex.motion not in ('QUAKE',) or self.lex.finished:
                return
            self.tick(1)

    def goto(self, x, y, radius=200, run=False, steps=150, tolerance=None):
        """Walk to within `radius` of (x, y) with turn taps and walk / run holds sized to the remaining distance (measured on Lex:
        a 4-tick walk hold moves ~70 units, 8 ticks ~260, 16 ticks ~1200; turn holds of 4 / 6 / 9 ticks turn ~4 / 11 / 21 degrees).
        Play.walk_to's fixed holds overshoot radii under ~400. `tolerance`: the heading error in degrees that is turned away (default:
        the radius's angle, 4 to 20). -> reached."""
        lex = self.lex
        best, stalled = float('inf'), 0
        level = self.world.level
        for _ in range(steps):
            if self.world.level != level:               # a trigger on the way loaded another level: the walk is over
                return True
            self.settle()
            dx, dy = x - lex.pos[0], y - lex.pos[1]
            distance = math.hypot(dx, dy)
            if distance < radius:
                return True
            delta = self.delta(math.degrees(math.atan2(-dx, -dy)))
            limit = tolerance if tolerance is not None else max(4.0, min(20.0, math.degrees(math.atan2(radius, distance))))
            if abs(delta) > limit:
                # a turn hold moves Lex too (~250 units for 15 ticks): near the target only small taps, or he orbits it
                if distance < 1500:
                    self.key(0x4d if delta > 0 else 0x4b, 0, 6)
                else:
                    self.key(0x4d if delta > 0 else 0x4b, 0, 4 if abs(delta) < 8 else 6 if abs(delta) < 15 else 9 if abs(delta) < 30 else 15)
            elif run and distance > 2000:
                self.key(0x48, worldmod.keys_mod.SHIFT, 8)
            else:
                self.key(0x48, 0, 4 if distance < 250 else 6 if distance < 500 else 8 if distance < 1000 else 12)
                # walks that bring Lex no closer: blocked (a wall, a closed door) or circling, give up
                best, stalled = (distance, 0) if distance < best - 20 else (best, stalled + 1)
                if stalled >= 8:
                    return False
        return False

    def fine_face(self, heading, tolerance=4):
        """Face `heading` with short turn taps (6 ticks ~ 2-11 degrees, ~16 units of travel; Play.face's longer holds move Lex
        ~180 units each)."""
        for _ in range(120):
            delta = self.delta(heading)
            if abs(delta) <= tolerance:
                return
            self.key(0x4d if delta > 0 else 0x4b, 0, 6)

    def approach(self, x, y, heading, stand_off=1500, radius=250, lead_in=True, tolerance=4):
        """Reach (x, y) facing `heading`: walk to a point `stand_off` behind it on that heading, face it, then walk straight in short
        holds until within `radius` (turning near a point moves Lex sideways too much to home in on it)."""
        h = math.radians(heading)
        fx, fy = -math.sin(h), -math.cos(h)                # forward() for a heading: atan2(-dx, -dy) = heading
        if lead_in:                                          # arrive moving along the line: a big turn in place drifts Lex sideways
            self.goto(x - fx * stand_off * 1.8, y - fy * stand_off * 1.8, radius=500)      # best effort: it may lie in a wall
        for _ in range(4):                                  # facing moves Lex too (turn holds travel): re-line-up until on the line
            self.route([(x - fx * stand_off, y - fy * stand_off)], radius=500)
            self.fine_face(heading, tolerance)
            along = (x - self.lex.pos[0]) * fx + (y - self.lex.pos[1]) * fy
            lateral = (x - self.lex.pos[0]) * fy - (y - self.lex.pos[1]) * fx
            if abs(lateral) < max(300, tolerance * 30) and along > stand_off / 2:
                break
        for _ in range(60):
            along = (x - self.lex.pos[0]) * fx + (y - self.lex.pos[1]) * fy
            if along < radius:
                return
            bearing = math.degrees(math.atan2(-(x - self.lex.pos[0]), -(y - self.lex.pos[1])))
            if along > 600 and abs(self.delta(bearing)) > 6:
                self.fine_face(bearing)                    # steer back onto the line to the point
            self.key(0x48, 0, 4 if along < 300 else 6 if along < 600 else 8)
        raise Stuck(f'approach ({x}, {y}) heading {heading}: Lex stopped at {[int(v) for v in self.lex.pos[:2]]}')

    def into_box(self, name):
        """Short holds toward the middle of the trigger box `name` until Space would reach it: where the fights left Lex moves his arrivals."""
        world, lex = self.world, self.lex
        box = next(t for t in world.triggers if t['name'] == name)
        x, y = (box['lo'][0] + box['hi'][0]) / 2, (box['lo'][1] + box['hi'][1]) / 2
        for _ in range(30):
            if name in world.usable_objects(lex):
                return
            self.face_point(x, y, tolerance=12)
            self.key(0x48, 0, 4)
        raise Stuck(f'{name}: Lex at {[int(v) for v in lex.pos[:2]]} never reached its box')

    def sneak(self, points, limit=2500):
        """Through `points` by sidesteps only: PgDn held, facing 90 degrees left of each leg, until Lex has passed the point along the leg;
        he faces again when he drifts 1200 units off it. HALMECHO's CHECKLEXMOTION counts WALK, WALK_BACK, RUN, ATK_M2 and ATK_M8 as
        moving (AI_MECHO.scr:26-37); sidesteps and turns are not on the list."""
        world, lex = self.world, self.lex
        for x, y in points:
            start, done = self.vm.tick, False
            while not done and self.vm.tick - start < limit and self.vm.objects['LEX'][0] > 0:
                ox, oy = lex.pos[0], lex.pos[1]
                length = math.hypot(x - ox, y - oy)
                if length < 300:
                    break
                ux, uy = (x - ox) / length, (y - oy) / length
                self.face(math.degrees(math.atan2(-ux, -uy)) - 90, tolerance=6)
                world.key_down(0x51, 0)
                while self.vm.tick - start < limit and self.vm.objects['LEX'][0] > 0:
                    self.tick(1)
                    px, py = lex.pos[0] - ox, lex.pos[1] - oy
                    along = px * ux + py * uy
                    if along >= length:
                        done = True
                        break
                    if abs(px * uy - py * ux) > 1200 + 0.1 * along:
                        break
                world.key_up(0x51, 0)
                self.tick(1)
            if not done and math.hypot(x - lex.pos[0], y - lex.pos[1]) > 1500:
                raise Stuck(f'sneak to ({x}, {y}) did not arrive; Lex at {[int(v) for v in lex.pos[:2]]}')

    def route(self, points, radius=200, run=False):
        """Walk through the (x, y) points with goto; Stuck at the first one not reached."""
        for x, y in points:
            if not self.goto(x, y, radius=radius, run=run) and math.hypot(x - self.lex.pos[0], y - self.lex.pos[1]) > 2 * radius:
                raise Stuck(f'walk to ({x}, {y}) did not arrive; Lex at {[int(v) for v in self.lex.pos[:2]]}')

    def pick_up(self, item, stand_off=700, retries=2):
        """Approach a floor item on the line from Lex, stop `stand_off` short of it facing it, press Enter; wait until Lex holds it. A
        LEVEL1TREMORS quake (AI off) that takes the press is waited out and the approach and press are made again (`retries` times)."""
        target = self.world.items[item]
        x, y = target.pos[:2]
        heading = math.degrees(math.atan2(-(x - self.lex.pos[0]), -(y - self.lex.pos[1])))
        h = math.radians(heading)
        if math.hypot(x - self.lex.pos[0], y - self.lex.pos[1]) > stand_off + 300:
            self.approach(x + math.sin(h) * stand_off, y + math.cos(h) * stand_off, heading,
                          stand_off=min(1500, math.hypot(x - self.lex.pos[0], y - self.lex.pos[1]) - stand_off), lead_in=False)
        self.face_point(x, y)
        hand = self.world.item_hand(target)
        held = self.world.held_item(self.lex, hand)
        if held is not None:
            if hand != 'LTHAND':
                raise Stuck(f'{item} needs the {hand}, which holds {held.name}')
            self.key(KEY_I)                               # I stows a left-hand item first (FUN_1120_0000's caller, README)
            self.until(lambda: self.world.held_item(self.lex, hand) is None, 30, f'I stows {held.name}')
        self.key(KEY_ENTER)
        for _ in range(120):
            if target.owner == self.lex.name:
                break
            self.tick(1)
        if target.owner != self.lex.name and retries and (not self.lex.ai_enabled or self.lex.motion.startswith('QUAKE')):
            self.until(lambda: self.lex.ai_enabled and not self.lex.motion.startswith('QUAKE'), 600, 'the quake lets Lex go')
            return self.pick_up(item, stand_off, retries - 1)
        self.until(lambda: target.owner == self.lex.name, 1, f'Enter picks up {item}')
        self.until(lambda: self.lex.finished or self.lex.motion == 'STAND', 120, f'the pick-up motion for {item} ends')

    def after_loadlevel(self, block, lines):
        """Shortcut 'loadlevel-caller': the port ends a level-owned caller at its LOADLEVEL (World.cmd_loadlevel), so the
        statements after it never run; the harness performs them (each caller says which)."""
        self.problem('blocker', 'engine', f'{block} ends at its LOADLEVEL in the port, so {lines} never run. LOADLEVEL (10d0:4d46) '
                     'kills every kernel task but the caller and its CALL chain (FUN_10b0_13fb) and ends the caller only '
                     'when its script file is not in the new level (1148:15c7); TUNROOM.scr:160 says its tail never ran, '
                     'but TO_TANKS, TO_CRYO_USE, TANKTOCELL2 and CELL2TOTANK (CRYTOTNK.scr) all need theirs')
        self.shortcut('loadlevel-caller', block=block, lines=lines)

    def running(self, block):
        return any(not proc.done and proc.block.name == block for proc in self.vm.procs.values())

    def use(self):
        """Space; -> the USE block the engine started (World.key_log), or None."""
        before = len(self.world.key_log)
        self.key(KEY_SPACE)
        uses = [entry for entry in self.world.key_log[before:] if entry[1] == 'use']
        return uses[-1][2] if uses else None

    def hold_button(self, name, ticks):
        """Hold a monitor button for `ticks` ticks (pointer on its first drawn frame, mouse down ... mouse up): the ROBOCNTL controls act
        while pressed and STAND CONTINUE on release (`click` holds only 2 ticks and then waits out the repeat delay)."""
        mon = self.world.monitor
        e = mon.elements.get(name.upper()) if mon is not None else None
        frame = next((f for f in (e.frames[1:] if e else []) if f[0] > 1), None)
        if frame is None:
            raise Stuck(f'hold {name}: no such button on {mon.name if mon else "a closed monitor"}')
        self.pointer_down(mon, name, frame)
        self.inputs.append({'tick': self.vm.tick, 'hold': name, 'ticks': ticks})
        self.tick(ticks)
        mon.mouse_up()
        self.tick(2)

    def wait_bars_off(self, var, ticks=3000):
        """Wait for the start of a long off window of flickering bars (`var` = _bars1_on): an off window that follows a short one
        (CELLONEBARS alternates 61 and 21 ticks off, CHAOSBLK.scr:618-707), as scenarios.chaos_caynan_fight does."""
        durations, state, edge = [], self.vm.globals.get(var), None
        for _ in range(ticks):
            self.tick(1)
            now = self.vm.globals.get(var)
            if state == 1 and now == 0:
                edge = self.vm.tick
                if durations and durations[-1] < 40:
                    return
            elif state == 0 and now == 1 and edge is not None:
                durations.append(self.vm.tick - edge)
            state = now
        raise Stuck(f'{var}: no long off window in {ticks} ticks')


# ---- segments --------------------------------------------------------------------------------------------------------------

def start(difficulty=0, run_class=Run, seed=None):
    """-> Run after the opening, the nurse and the Caynan fight (scenarios.nurse_defeat_run and chaos_caynan_fight)."""
    nurse_run = scenarios.nurse_defeat_run()
    world, vm, nurse = nurse_run
    if seed is not None:
        world.rng = random.Random(seed)
    run = run_class(world, vm)
    run.segments.append({'name': 'opening-nurse', 'start_tick': 0, 'end_tick': vm.tick,
                         'status': 'passed' if nurse['encounter']['escaped'] else 'stuck', 'checkpoint': run.mark('opening-nurse')})
    run.shortcut('nurse-poses', fixtures=nurse['encounter']['fixtures'])
    with run.segment('caynan'):
        run.shortcut('difficulty-easy', difficulty=difficulty)
        caynan = scenarios.chaos_caynan_fight(nurse_run, difficulty=difficulty, seed=None)
        run.lex = world.player()
        if caynan['encounter']['caynan_alive']:
            raise Stuck('Caynan survived the fight')
    run.collect_logs()
    return run


def fork(run):
    """Pick up the fork in cell 1 (Enter): LEX_FORK_TAKE sets _Lex_Has_Fork (AI_LEX.scr:465-470)."""
    with run.segment('fork'):
        try:
            run.pick_up('FORK')
        except Stuck:                                   # pick_up stops 700 short; where the Caynan fight leaves Lex that can be out of reach
            import playthrough_full as pf
            pf.take(run, 'FORK')
        if run.vm.globals.get('_lex_has_fork') != 1:
            raise Stuck('LEX_FORK_TAKE did not set _Lex_Has_Fork')


def cell_panel(run):
    """Leave cell 1 through a flicker window of its bars (CHAOSBLK.scr:618-707), pry the panel CELPAN open with the fork held
    (CELPAN_FORK_USE, CHAOSBLK.scr:305-328) and solve the circuit board (CC_CIRCUITBOARD, CHAOSMON.scr:92-332) from its start
    (4,4,1,2) with BT4, BT3, BT2, BT2, BT1 -> (1,2,2,3): columns 1 and 2 only go hot on the last press, so no ZAP is passed."""
    world, vm = run.world, run.vm
    with run.segment('cell-panel'):
        run.route([(0, -11500)], radius=300)
        run.face(0, tolerance=4)
        run.wait_bars_off('_bars1_on')
        health = vm.objects['LEX'][0]
        for _ in range(8):
            run.key(0x48, worldmod.keys_mod.SHIFT, 8)
            if run.lex.pos[1] < -16000:
                break
        if vm.objects['LEX'][0] < health:
            run.problem('minor', 'harness', f"the bars shocked Lex on the way out of cell 1 (HP {health} -> {vm.objects['LEX'][0]}): "
                        'the harness ran through too late in the off window')
        run.route([(0, -19500)], radius=300, run=True)
        run.approach(6300, -23900, 0)
        block = run.use()
        if block != 'CELPAN_FORK_USE':
            raise Stuck(f'Space at CELPAN with the fork ran {block}, not CELPAN_FORK_USE (Lex at {[int(v) for v in run.lex.pos[:2]]}, '
                        f'motion {run.lex.motion})')
        run.until(lambda: vm.globals.get('_celpan_open') == 1 and not run.running('CELPAN_FORK_USE'), 400, 'the panel swings open')
        run.use()
        run.until(lambda: world.monitor is not None and world.monitor.name == 'CLP2', 60, 'the circuit board monitor opens')
        for button in ('BT4B', 'BT3B', 'BT2B', 'BT2B', 'BT1B'):
            run.click(button)
        run.until(lambda: vm.globals.get('_celpan_state') == 4 and world.monitor is None, 400, 'the board is solved and closes')


def cell_block_door(run):
    """Space at PRY_DR: PRY_DR_USE walks Lex to PRY_HERE and, with the board solved, pries the cell-block door DR5 open
    (CHAOSBLK.scr:425-475; FULLY_OPEN_CELL_DOOR, `_dr5_SPACE = _NEGATIVE`, `_cel_door_state = 1`)."""
    vm = run.vm
    with run.segment('cell-block-door'):
        run.approach(7500, -21400, 180, stand_off=1200)    # into the PRY_DR box from the panel, out of CELPAN's reach
        run.into_box('PRY_DR')
        if run.use() != 'PRY_DR_USE':
            raise Stuck('Space at PRY_DR did not run PRY_DR_USE')
        run.until(lambda: vm.globals.get('_cel_door_state') == 1 and not run.running('PRY_DR_USE'), 600, 'Lex pries DR5 open')
        run.until(lambda: vm.globals.get('_dr5_frame') == 0 and not run.running('FULLY_OPEN_CELL_DOOR'), 300, 'the door finishes opening')


def cell_four_bars(run):
    """Into the guard room (GRD_LOAD's first-entry radio crosstalk, CHAOSGRD.scr:3-33, 278-317) and switch the cell-4 bars off at
    MONCL4 (MONCL4_USE needs COMPASS in -135..-45, CHAOSMON.scr:375-386; GR_CELLMONITOR's OFF button BT2B -> SETCELLFOURBARS(1),
    CHAOSMON.scr:546-577; EXIT is BT5B)."""
    world, vm = run.world, run.vm
    with run.segment('cell-four-bars'):
        run.route([(14000, -22500), (29200, -28300)], radius=200)
        if 'RADIO_CROSSTALK' not in {name for _, name in run.blocks}:
            run.problem('major', 'trigger', 'GRD_LOAD did not start RADIO_CROSSTALK on the first guard-room entry')
        run.face(-90, tolerance=6)
        if run.use() != 'MONCL4_USE':
            raise Stuck('Space at MONCL4 did not run MONCL4_USE')
        run.until(lambda: world.monitor is not None and world.monitor.name == 'CELL', 60, 'the cell monitor opens')
        run.click('BT2B')
        run.until(lambda: vm.globals.get('_bars4_on') == 0, 30, 'the OFF button switches the cell-4 bars off')
        run.click('BT5B')
        run.until(lambda: world.monitor is None, 30, 'EXIT closes the cell monitor')


def danes_log(run):
    """Back to the cell block, into cell 4 through the switched-off bars (DR_ZAP4, CE4), pick up DANELOG (Enter) and read it with
    Space: DANELOG_USE (ITEMS.scr:748-756) shows CF_DANESLOG, whose entry prints the random access code ASSIGNRANDOMIDS rolled
    (_access_id1..5_to_match, ASSIGNID.scr:10-14), and sets _read_danes_log."""
    world, vm = run.world, run.vm
    with run.segment('danes-log'):
        run.route([(14000, -22500), (11000, -21800), (7000, -21700), (-10100, -23500), (-10100, -26500), (-9300, -29500), (-9100, -32300)], radius=500)
        run.pick_up('DANELOG')
        block = run.use()
        if block != 'DANELOG_USE':
            raise Stuck(f'Space with DANELOG held ran {block}, not DANELOG_USE')
        run.until(lambda: world.monitor is not None and world.monitor.name == 'LGBK', 120, 'the log book monitor opens')
        # Read the page as the player does: entry 12 of the "dane" list prints the code with the monitor's variable substitution
        text = ' '.join(monitor_mod.substitute(t, world.monitor.resolve_var) for _, t in world.monitor.elements['TEXT'].entries)
        found = re.search(r'access code number is (\d{5})', text)
        if found is None:
            raise Stuck("Dane's log shows no access code")
        run.code = found.group(1)
        run.click('EXTB')
        run.until(lambda: world.monitor is None and vm.globals.get('_read_danes_log') == 1, 60, "EXIT closes Dane's log")


def caynans_arm(run):
    """Pick up CAYARM (a right-hand item) in the corridor in front of cell 1 with Enter: LEX_CAYARM_TAKE (AI_LEX.scr:431-436)."""
    with run.segment('caynans-arm'):
        run.route([(-10100, -29500), (-10100, -26500), (-9000, -23500), (369, -21500)], radius=400)
        run.pick_up('CAYARM')
        if not run.world.is_carrying(run.lex, 'RTHAND', 'CAYARM'):
            raise Stuck('CAYARM is not in the right hand')


def bot_heading(bot):
    """The robot's facing as the camera shows it: `Figure.heading` only takes a turning motion's yaw in when the motion ends (bake_turn,
    FUN_10a0_1c83), and a MOTION of the name already running is not restarted (1098:12bd), so the running TURN_* yaw is added here."""
    if bot.turning():
        return bot.heading - (bot.frames[bot.idx][2][0][2] - bot.frames[0][2][0][2]) * 45 / 32
    return bot.heading


def bot_delta(bot, heading):
    return (heading - bot_heading(bot) + 180) % 360 - 180


ARM_STALL_REACH = 1500                                      # how far from the arm a stalled robot can still be, claw out (PICKUP_REACH is 0x900)


def drive_bot(run, bot, sign, x, y, radius=300, loops=400):
    """Drive USE_BOT through the MLBT controls (ROBOCNTL.scr: RTDB / LTDB turn, UPDB walks while held) to within `radius` of (x, y):
    closed loop on the bearing (a RTDB hold of 8 ticks turned the bot 40.8 degrees, a tap 15.5 at least, UPDB walks ~22 units a tick; `sign` = +1 when RTDB
    raises the heading). -> reached; False when the distance stopped shrinking (a wall)."""
    best, stall = float('inf'), 0
    for _ in range(loops):
        dx, dy = x - bot.pos[0], y - bot.pos[1]
        dist = math.hypot(dx, dy)
        if dist < radius:
            return True
        d = bot_delta(bot, math.degrees(math.atan2(-dx, -dy)))
        tolerance = max(9, min(25, math.degrees(math.atan2(radius, dist))))      # a press turns 15 degrees at least: its WAIT 5 keeps TURN_* going
        if abs(d) > tolerance:
            run.hold_button('RTDB' if d * sign > 0 else 'LTDB', max(2, min(10, int(abs(d) / 4))))
        else:
            run.hold_button('UPDB', max(4, min(20, int(dist / 24))))
            best, stall = (dist, 0) if dist < best - 30 else (best, stall + 1)
            if stall >= 12:
                return False
    return False


def bot_holds_arm(run):
    """The designed way to earn the clearance (surface: re/playthrough/prison.md item 9): CHECK_ACCESS_ID wants CAYARM inside ARMHERE1
    (z -6400..-4352) while Lex is at the terminal, so the USE_BOT robot holds it there. Lex stows Dane's log (I) and puts the arm down
    (Enter, PUT_DOWN_RTHAND), walks to the BOT_MON monitor (Space facing south, BOT_MON_USE, ROBOCNTL.scr), switches the robot to manual
    (MANB: ACTIVATE, it rises 1700), drives it to the arm with the turn / walk buttons, closes the claw (CCDB = MOTION PICK_UP_RTHAND:
    the item goes into the NURSEBOT's MY_HAND, UP_ARM, 1138:088d), drives it to the palm reader with the arm inside ARMHERE1 (the
    arm tip lands ~1030 units in front of the robot's origin) and leaves the monitor (PWRB). The robot stays standing and keeps the arm."""
    world, vm = run.world, run.vm
    with run.segment('arm-to-reader'):
        arm = world.items['CAYARM']
        if world.held_item(run.lex, 'LTHAND') is not None:
            run.key(KEY_I)
            run.until(lambda: world.held_item(run.lex, 'LTHAND') is None, 60, 'I stows the left-hand item')
        for _ in range(4):                                  # a tremor starting on the press swallows it
            run.key(KEY_ENTER)
            run.tick(20)
            if arm.owner is None and arm.pos is not None:
                break
        run.until(lambda: arm.owner is None and arm.pos is not None, 120, 'Enter puts the arm down')
        run.until(lambda: run.lex.finished or run.lex.motion == 'STAND', 120, 'the put-down ends')
        run.route([(9000, -21600), (14000, -22500), (19800, -22800)], radius=400)
        run.approach(20946, -17400, 180, stand_off=2200, radius=100)
        if run.use() != 'BOT_MON_USE':
            raise Stuck(f'Space at BOT_MON ran another block (Lex at {[int(v) for v in run.lex.pos[:2]]}, heading {int(run.lex.heading)})')
        run.until(lambda: world.monitor is not None and world.monitor.name == 'MLBT', 200, 'the robot control monitor opens')
        bot = world.figures['USE_BOT']
        run.click('MANB')
        run.until(lambda: vm.globals.get('_use_bot_activated') == 1, 400, 'USE_BOT is activated')
        heading = bot_heading(bot)
        run.hold_button('RTDB', 8)
        run.tick(10)
        sign = 1 if bot_heading(bot) > heading else -1
        # Lex's way out of the cell block: the straight line hits a wall. The arm lies where Lex dropped it, 700 units off the lane the robot
        # walked along (its UPDB presses stalled there, ASSUMPTION: a wall), so the last stop is within 800 of it (the claw reaches ~1030)
        for x, y, radius in ((-10100, -29500, 500), (-10100, -26500, 500), (-9000, -23500, 500), (arm.pos[0], arm.pos[1], 800)):
            if not drive_bot(run, bot, sign, x, y, radius=radius):
                if (x, y) == tuple(arm.pos[:2]) and math.hypot(x - bot.pos[0], y - bot.pos[1]) < ARM_STALL_REACH:
                    break                                         # the bars' avoidance points (AVDBAR1, GETMEAT: ~2250 units) keep the robot from an arm dropped near them, but the claw still reaches
                raise Stuck(f'USE_BOT did not reach ({int(x)}, {int(y)}) on the way to the arm; at {[int(v) for v in bot.pos[:2]]}')
        for _ in range(20):                                           # face the arm until Enter would take it
            d = bot_delta(bot, math.degrees(math.atan2(-(arm.pos[0] - bot.pos[0]), -(arm.pos[1] - bot.pos[1]))))
            if abs(d) < 9:
                break
            run.hold_button('RTDB' if d * sign > 0 else 'LTDB', max(2, min(8, int(abs(d) / 4))))
            run.tick(6)
        run.hold_button('CCDB', 3)
        run.until(lambda: arm.owner == 'USE_BOT', 300, 'the claw takes the arm (PICK_UP_RTHAND)')
        run.until(lambda: bot.finished or bot.motion != 'PICK_UP_RTHAND', 600, 'the pick-up ends')
        for x, y in ((9000, -21600), (14000, -22500), (19800, -22800)):
            if not drive_bot(run, bot, sign, x, y, radius=500):
                raise Stuck(f'USE_BOT stopped at {[int(v) for v in bot.pos[:2]]} on the way to ({x}, {y})')
        box = next(t for t in world.triggers if t['name'] == 'ARMHERE1')

        def arm_in_box():
            hull = world.object_hull(arm)
            return hull is not None and world.boxes_touch(hull[0], hull[1], box['lo'], box['hi'])

        want, target = (19400, -29000), (19400, -29400)
        for _ in range(4):                                           # the arm tip hangs ~1000 units ahead of the robot: shift until it is inside
            reached = drive_bot(run, bot, sign, target[0], target[1], radius=200)
            if arm_in_box() or not reached:
                break
            pos = world.object_pos(arm)
            target = (want[0] - (pos[0] - bot.pos[0]), want[1] - (pos[1] - bot.pos[1]))
        if not arm_in_box():
            raise Stuck(f'the arm is not inside ARMHERE1 (arm at {[int(v) for v in world.object_pos(arm)]}, robot at {[int(v) for v in bot.pos[:3]]})')
        run.until(lambda: bot.motion == 'STAND', 60, 'the robot stands (a PWRB press during its WALK is dropped)')
        run.click('PWRB')
        run.until(lambda: world.monitor is None, 60, 'PWRB closes the robot control')
        run.tick(30)
        if (arm.owner, arm.slot) != ('USE_BOT', 'UP_ARM'):
            raise Stuck(f'the robot let go of the arm: {arm.owner} {arm.slot}')


def security_terminal(run):
    """SEC_MON (Space facing west, COMPASS 45..135: SEC_MON_USE, CHAOSMON.scr:65-75) -> ACCESS -> the five digits of Dane's code
    (GR_SECURITYMONITOR, CHAOSMON.scr:1005-1238). CHECK_ACCESS_ID (1058-1124) also needs CAYARM inside ARMHERE1, raised above the
    floor (z -6400..-4352), while Lex is at the terminal: USE_BOT holds it there (`bot_holds_arm`), so the terminal grants the clearance
    (GSECPASS, `_caynan_security_id_ok = 1`)."""
    world, vm = run.world, run.vm
    with run.segment('security-terminal'):
        run.approach(18650, -19300, 90, stand_off=1000, tolerance=10)        # from BOT_MON, where `bot_holds_arm` left Lex
        run.fine_face(90, tolerance=30)                     # SEC_MON_USE needs COMPASS 45..135
        for _ in range(30):                                 # the walk in can stop short of the box, and a turn inside it moves him out: along the wall, at a heading COMPASS accepts
            if 'SEC_MON' in world.usable_objects(run.lex):
                break
            run.fine_face(125 if run.lex.pos[1] < -19379 else 55, tolerance=10)
            run.key(0x48, 0, 4)
        block = run.use()
        if block != 'SEC_MON_USE':
            raise Stuck(f'Space at SEC_MON ran {block}, not SEC_MON_USE (Lex at {[int(v) for v in run.lex.pos[:2]]}, '
                        f'heading {int(run.lex.heading)})')
        run.until(lambda: world.monitor is not None, 300, 'the security terminal opens')
        run.click('ACCB')
        for digit in run.code:
            run.click(f'KN{digit}B')
        run.tick(90)
        answer = 'GSECPASS' if vm.globals.get('_caynan_security_id_ok') == 1 else \
            'GSECNOHN' if 'NEEDHAND' in run.world.log_entries.get('LEX', []) else 'GSECFAIL'
        run.terminal_answer = answer
        if answer != 'GSECPASS':
            raise Stuck(f'the terminal answered {answer}, not GSECPASS (the robot holds the arm at {[int(v) for v in run.world.object_pos(run.world.items["CAYARM"])]})')
        run.click('XITB')
        run.until(lambda: world.monitor is not None and 'AXTB' in world.monitor.elements
                  and world.monitor.elements['AXTB'].active, 60, 'back on the personnel screen')
        run.click('AXTB')
        run.until(lambda: world.monitor is None, 60, 'EXIT closes the terminal')


def guard_room_door(run):
    """With the clearance and the arm in USE_BOT's claw inside ARMHERE1, Lex steps onto the floor panel in front of the door (the IMAG
    CHANDQ, CHAOSHAL.scr): with `_caynan_security_id_ok` it sets the current figure to PLAYER, finds the arm (ISCARRYING(RTHAND, CAYARM)
    is false, SETCURRENTITEM(CAYARM), AMINTRIGGER(CURITEM, ARMHERE1)) and calls OPENDR6 (CHAOSMON.scr:705-806, CHAOSGRD.scr:152-171,
    HAND_DOOR_OPEN sets _dr6_SPACE = _NEGATIVE).  The palm reader GR_PALM would need the arm in Lex's right hand, but the robot has it."""
    world, vm = run.world, run.vm
    with run.segment('guard-room-door'):
        run.route([(20200, -24800), (20400, -26800), (20800, -29000)], radius=250)
        run.until(lambda: run.running('HAND_DOOR_OPEN') or vm.globals.get('_hand_door_in_op') == 1, 400, 'the floor panel opens DR6')
        run.until(lambda: not run.running('HAND_DOOR_OPEN') and world.monitor is None, 400, 'DR6 finishes opening')
        if vm.globals.get('_dr6_space') != vm.globals.get('_negative', 0):
            raise Stuck('DR6 is not open')


def hallway(run):
    """Down the hallway to the cryo room door (DR8 / HL3). HALMECHO_AI starts by itself once a hallway camera is current (AI-off counter 0
    in its FIGR record, AI name HALMECHO, viewing cameras from CHAOS_LOAD; FUN_1088_3371): the sentry paces WAY_PT1 (by the cryo door) ->
    WAY_PT2 (by the DR6 exit), reacts to Lex within 300 cm in front of it and never stands down once it has spotted him: running, or
    walking twice, makes it fire (HALMECHO_AI, CHECKLEXMOTION, AI_MECHO.scr:17-61, 131-297). It walks about 65 units a tick against Lex's
    100, so a run from DR6 for the elevator vestibule is spotted about 500 units short of it, and running on under fire kills him: the
    unarmed way past it: it starts at the south end and walks north toward DR6, so it spots Lex, stops and warns. Spotted, it only fires
    at a walk, run, ATK_M2 or ATK_M8 (CHECKLEXMOTION), so Lex sidesteps the whole hall into the cryo room (Run.sneak), where its processes
    pause (linked to the hall cameras)."""
    world, vm = run.world, run.vm
    mecho = world.figures['HALMECHO']
    with run.segment('hallway'):
        run.route([(17000, -31000), (17000, -35000)], radius=500, run=True)
        run.until(lambda: world.ai_active(mecho) and mecho.motion == 'WALK', 120, 'HALMECHO_AI starts with a hallway camera current')
        run.sneak([(17800, -50000), (18300, -62000), (17000, -72000), (14500, -76000), (6000, -76300)])
        if vm.objects['LEX'][0] <= 0:
            raise Stuck('Lex died in the hallway')
        if vm.globals.get('_halmecho_state') == 2:
            raise Stuck('the sentry fired at Lex in the hallway')


def cryo_ladder(run):
    """In the cryo room: CRYO_BTN (Space facing west, COMPASS 55..130) opens the iris (CRYO_BTN_USE, CHAOSCRY.scr:321-416,
    _IRIS_OPN = 1); TRIG_LDR (Space, CRYTOTNK.scr:4-40) puts Lex on the ladder; DOWNLADDER -> TO_TANKS: `LOADLEVEL TANKS ENTR_TNK`
    (CRYTOTNK.scr:121-204). Fido was never woken (_Fido_In_Tank = 0), so FIDOEATSLEX does not run."""
    world, vm = run.world, run.vm
    with run.segment('cryo-ladder'):
        run.shortcut('fido-puzzle')
        vm.globals['_fido_and_scorp_are_dead'] = 1
        run.route([(0, -80000)], radius=500)
        run.approach(-13900, -79300, 90, stand_off=2500)
        run.fine_face(90, tolerance=10)                     # CRYO_BTN_USE needs COMPASS 55..130
        if run.use() != 'CRYO_BTN_USE':
            raise Stuck('Space at CRYO_BTN did not run CRYO_BTN_USE')
        run.until(lambda: vm.globals.get('_iris_opn') == 1 and not vm.globals.get('_iris_moving'), 600, 'the iris opens')
        loads = len(world.level_loads)
        run.approach(-12900, -74300, 180, stand_off=4500)  # north along x -12900: the open iris (QPIT5) starts at x -12490, the valve at -14385
        block = run.use()
        if block != 'TRIG_LDR_USE':
            raise Stuck(f'Space at TRIG_LDR ran {block}, not TRIG_LDR_USE (Lex at {[int(v) for v in run.lex.pos[:2]]})')
        run.until(lambda: run.running('DOWNLADDER'), 600, 'Lex starts down the ladder (DOWNLADDER)')
        # DOWNLADDER loops MOTION DOWN_LADDER CONTINUE until COORDZ(CURFIG) <= -55 (CRYTOTNK.scr:121-136); each wrap of the looping
        # flag-2 motion commits its last root z (-1142 units) to Lex's height (1088:1286), so he climbs down by himself
        run.until(lambda: len(world.level_loads) > loads, 900, 'DOWN_LADDER lowers Lex to COORDZ -55 and TO_TANKS loads TANKS')
        if world.level != 'TANKS':
            raise Stuck(f'the ladder loaded {world.level}, not TANKS')
        run.tick(2)
        lex = run.lex
        if run.running('TO_TANKS'):
            # TO_TANKS goes on after its LOADLEVEL (FACE -165, DOWN_LADDER CONTINUE, GRAVITY ON) and waits for DISTFROMTRIGGER CURFIG
            # TO_CRYO <= 105: the looping DOWN_LADDER lowers Lex 1142 units per wrap (about 100 ticks) down the 21000-unit ladder, then
            # TO_TANKS ends (AI ON, MOTION STAND)
            run.until(lambda: not run.running('TO_TANKS'), 3000, 'DOWN_LADDER carries Lex to the ladder foot and TO_TANKS finishes')
        else:
            run.after_loadlevel('TO_TANKS', 'CRYTOTNK.scr:186-203')
            # TO_TANKS' tail: FACE -165, MOTION DOWN_LADDER CONTINUE, GRAVITY CURFIG ON, wait for DISTFROMTRIGGER CURFIG TO_CRYO <= 105,
            # _LEX_IS_CLIMBING = 0, AI ON, MOTION STAND
            lex.heading, lex.gravity = -165, True
            world.set_pos(lex, [28800, -29300, -22500])
            vm.globals['_lex_is_climbing'] = 0
            world.cmd_ai(lex, True)
            lex.set_motion('STAND', True)
        run.tick(30)
        if not -24500 < lex.pos[2] < -20000:
            raise Stuck(f'Lex is not on the TANKS catwalk at the ladder foot (z {int(lex.pos[2])})')


def heal(run, enough=75):
    """Up to `enough` HP: the battery has to last until the Elite's gift, and a repair the fight routine started may still be running (BRSB toggles it)."""
    world, vm = run.world, run.vm
    if vm.objects['LEX'][0] >= enough:
        return
    if world.held_item(run.lex, 'LTHAND') is not None:             # a first press of a page key only stows the left hand
        run.key(0x17)
        run.tick(10)
    run.key(0x20)
    run.until(lambda: world.monitor is not None and world.monitor.name == 'PIMM', 120, 'the diagnostics page opens')
    if vm.globals.get('_bio_state') != 1:
        run.click('BRSB')
    run.until(lambda: vm.objects['LEX'][0] >= enough or vm.globals.get('_bio_state') == 0, 3000, 'BIOREPAIR heals Lex')
    if vm.globals.get('_bio_state') == 1:
        run.click('BRSB')
    run.click('EXTB')
    run.until(lambda: world.monitor is None, 60, 'EXIT closes the diagnostics page')


def tanks_to_cell2(run):
    """From the west end of y -186300 onto TOCELL2: PROCESS TANKTOCELL2 -> `LOADLEVEL CHAOS TNKS_ARV` + CALL ENTERCELL2 (CRYTOTNK.scr:292-299)."""
    world = run.world
    loads = len(world.level_loads)
    run.route([(23000, -186300)], radius=600)
    run.goto(20000, -185700, radius=600)                # into the TOCELL2 trigger (x 19208..20744): the level changes on the way
    run.until(lambda: len(world.level_loads) > loads, 300, 'TOCELL2 loads CHAOS')
    if world.level != 'CHAOS':
        raise Stuck(f'TOCELL2 loaded {world.level}')


def tanks(run):
    """The TANKS catwalk south from the ladder foot: TELETNK1 / TELETNK3 hop the camera gaps (TANKS.scr:125-165), GONER does nothing
    (shortcut 'fido-puzzle'), then west at y -186300, up the CBLT / LTB ledge by MANTLE_6, onto TOCELL2 (TANKS.scr:169-180): PROCESS
    TANKTOCELL2 -> `LOADLEVEL CHAOS TNKS_ARV` + CALL ENTERCELL2 (CRYTOTNK.scr:292-299)."""
    world, vm = run.world, run.vm
    with run.segment('tanks'):
        loads = len(world.level_loads)
        run.route([(28500, -43000), (28500, -70000), (28500, -110000), (28500, -160000)], radius=600, run=True)
        run.route([(28500, -186300)], radius=250)
        # the catwalk's end is a ledge (CBLT / LTB, flag 0x02, 2838 above the floor) that Lex mantles onto: the engine requests MANTLE_6
        # only for a WALK ("walk" requested by the key handler), not a RUN, with the hull inside the ledge's width shrunk by 0x266 (so the
        # approach runs along y -186300, between -186684 and -185901), and the climb's root z is committed to his height
        heal(run)                                           # Guard 1 is next, and Lex comes out of the Caynan fight hurt
        tanks_to_cell2(run)


def play(stop_after=None, difficulty=0, run_class=Run, seed=None):
    """Drive the path segment by segment until one fails (or `stop_after` is done). -> Run."""
    run = start(difficulty, run_class, seed)
    for step in (fork, cell_panel, cell_block_door, cell_four_bars, danes_log, caynans_arm, bot_holds_arm, security_terminal, guard_room_door, hallway, cryo_ladder, tanks):
        if not run.passed:
            break
        step(run)
        if stop_after == step.__name__:
            break
    return run


def report(run):
    return {'segments': run.segments, 'problems': run.problems, 'shortcuts': run.shortcuts, 'inputs': run.inputs,
            'checkpoints': [{k: v for k, v in point.items() if k not in ('frame', 'figures')} for point in run.checkpoints],
            'level_loads': scenarios.plain(run.world.level_loads), 'room_events': [e for e in run.world.events if e[1][:-5] not in run.world.cameras and e[1].endswith('_LOAD')], 'passed': run.passed,
            'final_tick': run.vm.tick}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', default='re/out/playthrough_prison', help='directory for the JSON report')
    args = parser.parse_args()
    result = report(play())
    os.makedirs(args.out, exist_ok=True)
    with open(os.path.join(args.out, 'report.json'), 'w', encoding='utf-8') as handle:
        json.dump(scenarios.plain(result), handle, indent=2, sort_keys=True)
    for seg in result['segments']:
        print(f"{seg['name']:24} {seg['status']:8} ticks {seg['start_tick']}-{seg['end_tick']}")
    for p in result['problems']:
        print(f"[{p['severity']}] {p['segment']}: {p['kind']}: {p['message'].splitlines()[0]}")
