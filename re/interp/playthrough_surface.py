"""Playthrough harness for the surface stretch: LANDPAD, BEACH, DIGSITE and TUNROOM (the temple included), with the shipped scripts.

Run from the repository root:
    re/.venv/bin/python -I -W ignore re/interp/playthrough_surface.py [--out re/out/playthrough_surface]

The route is mapped in re/playthrough/surface.md. Each segment starts at the level's real arrival through the engine's own LOADLEVEL
(a script block that calls it, or `World.cmd_loadlevel` with the scripts' arguments), then drives the path with the real scripts and
player keys in deterministic steps. A segment starts from a fresh world, so a blocker in one segment does not hide the next.

Where keys are impractical the harness takes a staged shortcut and records it (kind, what, reason) in the segment's report:
`set_pos` next to a trigger, a global the player would set, an item the player would carry in, or a fight skipped with its outcome.
Every step records the new warnings, VM warnings and unmodelled calls it raised, and the step fails when its goal is not reached
within its tick budget (a stuck state).
"""
import argparse
import collections
import json
import math
import os
import re
import sys
import traceback
import types

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
import vm as vmmod  # noqa: E402
import world as worldmod  # noqa: E402
import scenarios  # noqa: E402
from playthrough_prison import Stuck  # noqa: E402

SPACE, SHOOT, COMBAT = 0x39, 0x4c, 0x2e          # keys.py: Space use, KP5 shoot, C combat


def harness_proc(owner='boot'):
    """A stand-in caller for engine statements the harness issues itself (like test_missiles.stub)."""
    return types.SimpleNamespace(block=types.SimpleNamespace(name='HARNESS', file=None), cur_fig=None, cur_item=None,
                                 handle=0, waiters=[], owner=owner)


class Segment:
    """One stretch of the route on a fresh world. `steps` and `shortcuts` are the report; `ok` is False after the first failed step."""

    def __init__(self, name, level, outer=None):
        """`outer` = a run that is already going (playthrough_full): the segment drives its world, VM and keys and creates or seeds nothing."""
        self.name, self.ok = name, True
        self.attached = outer is not None
        if outer is None:
            self.world = worldmod.World(level)
            self.vm = vmmod.VM(self.world)
            vmmod.load_level(self.vm, level)
            self.play = scenarios.Play(self.world, self.vm)
        else:
            self.world, self.vm, self.play = outer.world, outer.vm, outer
        self.steps, self.shortcuts = [], []
        self._seen = (len(self.world.warnings), len(self.vm.warnings), len(self.world.unmodelled)) if self.attached else (0, 0, 0)

    # ---- set-up
    @property
    def lex(self):
        return self.world.player()

    def create_lex(self):
        """STARTPLAYING's `CREATEFIGURE LEX PLAYER` (START.scr:19-22): the persistent player the arrival places."""
        self.world.call('stmt', 'CREATEFIGURE', ['LEX', 'PLAYER'], harness_proc())
        self.play.lex = self.lex

    def stage(self, kind, what, reason):
        self.shortcuts.append({'step': len(self.steps), 'tick': self.vm.tick, 'kind': kind, 'what': what, 'reason': reason})

    def set_global(self, name, value, reason):
        self.vm.globals[name.lower()] = value
        self.stage('global', f'{name} = {value}', reason)

    def give(self, item_type, slot, reason, name=None):
        """An item carried in from an earlier level: CREATEITEM's record, owned by Lex in `slot` (a hand or INVENTORY)."""
        name = (name or item_type).upper()
        item = worldmod.Item(name, item_type.upper(), owner=self.world.player_name, slot=slot)
        self.world.add_item(item)
        self.stage('item', f'{name} ({item_type}) in {slot}', reason)
        return item

    def form(self, name, reason):
        """CHANGEMYFORM on Lex, the statement the earlier level's machine runs (e.g. CONCNTRL.scr:116)."""
        proc = harness_proc()
        proc.cur_fig = self.world.player_name
        self.world.call('stmt', 'CHANGEMYFORM', [name], proc)
        self.stage('form', f'CHANGEMYFORM {name}', reason)

    def set_pos(self, xy, heading=None, reason='', z=None):
        """Stand Lex on the floor under (x, y), searching down from `z` (default: his own height)."""
        lex = self.lex
        top = int(lex.pos[2] if z is None else z) + 4096
        z = self.world.point_floor(int(xy[0]), int(xy[1]), top, top) + self.world.foot(lex)
        lex.pos = np.array([float(xy[0]), float(xy[1]), float(z)])
        lex.vx = lex.vy = lex.vz = 0
        if lex.motion != worldmod.STAND and lex.assets.motions.get(worldmod.STAND) is not None:
            lex.set_motion(worldmod.STAND, True)            # a teleport ends whatever teeter or walk was playing
        if heading is not None:
            lex.heading = float(heading)
        self.stage('set_pos', f'Lex to ({int(xy[0])}, {int(xy[1])}, {int(z)}) heading {lex.heading:g}', reason)

    # ---- driving
    def tick(self, count=1):
        self.play.tick(count)

    def wait(self, cond, budget):
        """Tick until `cond()` or `budget` ticks. -> ticks spent, or None when stuck."""
        for n in range(budget + 1):
            if cond():
                return n
            if n < budget:
                self.tick(1)
        return None

    def key(self, scan, mods=0, count=1):
        self.play.key(scan, mods, count)

    def use(self):
        """Space (FUN_10a8_0541): the nearby object's <obj>[_<item>]_USE block, as the player's use key starts it. Waits for a
        one-shot motion (a teeter, a landing) to end first, as a player would."""
        self.wait(lambda: self.lex.motion == worldmod.STAND or self.lex.manual_control, 90)
        self.key(SPACE)

    def trigger_box(self, name):
        o = next(o for o in self.world.objs if o['name'].upper() == name and 'pos2' in o)
        return np.minimum(o['pos'], o['pos2']), np.maximum(o['pos'], o['pos2'])

    def box_centre(self, name):
        lo, hi = self.trigger_box(name)
        return (lo[:2] + hi[:2]) / 2

    def in_hull_box(self, name):
        """AMINTRIGGER's test: Lex's hull touches the trigger box."""
        lo, hi = self.trigger_box(name)
        hlo, hhi, _ = self.world.query_hull(self.lex)
        return all(hhi[i] >= lo[i] and hlo[i] <= hi[i] for i in range(3))

    def in_box(self, name):
        lo, hi = self.trigger_box(name)
        return bool(np.all(self.lex.pos[:2] >= lo[:2]) and np.all(self.lex.pos[:2] <= hi[:2]))

    def walk(self, x, y, radius=350, run=False, steps=200, stop=None):
        """Play.walk_to one key at a time, stopping when the level changes under the walk (a trigger's LOADLEVEL) or `stop()`."""
        level = self.world.level
        for _ in range(steps):
            if self.world.level != level or (stop is not None and stop()):
                return False
            if self.play.walk_to(x, y, radius=radius, run=run, steps=1):
                return True
        return False

    def ran(self, block):
        return any(name == block for _, name in self.play.blocks)

    def running(self, block):
        return any(p.block.name == block and not p.done for p in self.vm.procs.values())

    def alive(self):
        return self.vm.objects.get(self.world.player_name, [1])[0] > 0 and not self.vm.globals.get('_lexisdead')

    # ---- steps
    def step(self, name, goal, detail=None):
        """Close a step: record whether `goal` holds, the state, and the problems raised since the previous step."""
        world, vm = self.world, self.vm
        w0, v0, u0 = self._seen
        lex = self.lex
        record = {
            'step': name, 'ok': bool(goal), 'tick': vm.tick, 'level': world.level, 'camera': world.current_camera(),
            'lex': None if lex is None else {'pos': [round(float(c)) for c in lex.pos], 'motion': lex.motion, 'form': lex.type,
                                             'hp': vm.objects.get(world.player_name, [None])[0]},
            'warnings': world.warnings[w0:], 'vm_warnings': vm.warnings[v0:], 'unmodelled': world.unmodelled[u0:],
        }
        if detail:
            record['detail'] = detail
        self._seen = (len(world.warnings), len(vm.warnings), len(world.unmodelled))
        self.steps.append(record)
        self.ok = self.ok and record['ok']
        return record['ok']

    def report(self):
        return {'segment': self.name, 'ok': self.ok, 'steps': self.steps, 'shortcuts': self.shortcuts,
                'level_loads': scenarios.plain(self.world.level_loads), 'blocks': [b for _, b in self.play.blocks]}


def run_segment(name, body):
    """Run one segment function; an exception is recorded as a crash step instead of ending the playthrough."""
    seg = None
    try:
        seg = body()
    except Exception as exc:                                   # noqa: BLE001 - a crash is a finding
        seg = getattr(exc, 'segment', None)
        report = seg.report() if seg is not None else {'segment': name, 'steps': [], 'shortcuts': []}
        report['ok'] = False
        report['steps'].append({'step': 'crash', 'ok': False, 'error': f'{type(exc).__name__}: {exc}',
                                'traceback': traceback.format_exc(limit=6)})
        return report
    return seg.report()


# ---- LANDPAD: the arrival from the prison levels
def landpad(outer=None, ledge=None):
    """CHAOS elevator -> LANDPAD (ELEVATOR.scr:326-430) -> AIRMECHO -> airlock -> pad -> jetson tube -> ledge -> TO_BCH. With `outer` (a run
    that has just ridden the elevator) it starts at the arrival: nothing is created or seeded."""
    seg = Segment('landpad', 'CHAOS', outer)
    world, vm = seg.world, seg.vm
    try:
        if not seg.attached:
            landpad_seed(seg)
        else:
            arrived = seg.wait(lambda: vm.globals.get('_elevator_moving') == 0, 200) is not None
            seg.step('elevator-arrival', world.level == 'LANDPAD' and arrived and seg.in_box('ELV') and vm.globals.get('_dr9_space') == 0,
                     {'dr9_space': vm.globals.get('_dr9_space'), 'elevator_moving': vm.globals.get('_elevator_moving')})
        lex = seg.lex
        # 2. Out of the cabin into MEETMECH: MARCHOUTAIRMECHO (AIRHALL.scr:10-74)
        seg.walk(-31000, -71000, radius=600)
        seg.wait(lambda: vm.globals.get('_airmecho_scene') == 1, 60)
        mecho = world.figure('AIRMECHO')
        seg.wait(lambda: mecho is not None and world.ai_active(mecho), 900)
        seg.step('meet-mech', seg.ran('MEETMECH') and mecho is not None and world.ai_active(mecho))
        landpad_rest(seg, lex, mecho, ledge)
    except Exception as exc:
        exc.segment = seg
        raise
    return seg


def landpad_seed(seg):
    """The standalone segment's world: Lex, what CONTROL leaves behind, and the ride from CHAOS (shortcuts, all logged)."""
    world, vm = seg.world, seg.vm
    seg.create_lex()
    lex = seg.lex
    world.fire_event('CHAOS_LOAD')
    seg.tick(2)
    # What CONTROL leaves behind before the first ride to the pad (surface.md "Carried in")
    seg.form('HARD', 'the LANDPAD airlock chokes Lex unless HARD or LEXMIR (LANDPAD.scr:226-239); the suit comes from the '
                     'CONTROL machine (CONCNTRL.scr:116), a base level')
    seg.give('BLASTER', 'RTHAND', 'the CHAOS blaster (CHAOS level item): AIRMECHO dies only by LASER_HIT_AIRMECHO (AI_AMECH.scr)')
    seg.set_global('_Reactor_Safe', 1, "CONTROL's reactor shutdown (SHUTDOWN.scr:113); otherwise QUAKER knocks Lex off the "
                                       'ledge (LEDGE.scr:44-67)')
    seg.set_global('_LandbotsAlive', 0, 'fight skipped, outcome recorded: since the CURFIG/CURITEM fix (PR #16) the pad and ledge '
                                        'bots kill a suited Lex in seconds (blocker S-bots); LANDPAD_LOAD then runs KILL_LANDBOTS')
    seg.give('BLOCK', 'INVENTORY', "the artifact from CONTROL: BEACH's zip lines are <trigger>_BLOCK_USE (BEACHZIP.scr:57-150)")
    # 1. The ride: the elevator monitor's AIRB button runs `PROCESS SWITCHTOLANDINGLEVEL` (ELEVATOR.scr:881)
    seg.stage('process', 'SWITCHTOLANDINGLEVEL', 'stands for pressing AIRB on the elevator monitor (ELEVATOR.scr:829-881)')
    vm.spawn('SWITCHTOLANDINGLEVEL', ctx=types.SimpleNamespace(cur_fig=world.player_name, cur_item=None, owner='level'))
    seg.wait(lambda: world.level == 'LANDPAD', 400)
    arrived = seg.wait(lambda: vm.globals.get('_elevator_moving') == 0, 200) is not None
    seg.step('elevator-arrival', world.level == 'LANDPAD' and arrived and seg.in_box('ELV') and vm.globals.get('_dr9_space') == 0,
             {'dr9_space': vm.globals.get('_dr9_space'), 'elevator_moving': vm.globals.get('_elevator_moving')})


AIRMECHO_AIM = 3.2          # degrees: ATK_SHOOT's laser leaves this far left of Lex's heading
AIRMECHO_CYCLE = 138        # ticks between its volleys at Easy, standing at AIR_POSX: FIRE_GUN, WAIT 50, WAIT 70 - 20 * difficulty (measured)
SHOT_TICKS = 30             # ATK_SHOOT
LANE = 1300                 # a bolt passing nearer than this to Lex is dodged
VOLLEY_PERIOD = 115         # ticks from one FIRE_GUN to the next while AIRMECHO stands at AIR_POSX (measured, Easy)
VOLLEY_LEAD = 5             # the dodge starts this long before FIRE_GUN: the bolt leaves 8 ticks into FIRE_GUN, just before the sidestep's burst
ARRIVE = 300                # AIRMECHO raises its gun 3 ticks after it reaches AIR_POSX: its last ~2 ticks of walking there


def airmecho_duel(seg, lex, mecho, budget=1500):
    """AIRMECHO by keys, out of combat (no auto-turn). The first BOLTGRN that reaches Lex while the camera is HFR3 / HFR6 bends him over
    and the fan after it kills him (BOLTGRN_HIT_LEX, AIRHALL.scr:90-171), so no bolt may land. Each bolt flies at where Lex stood when
    it was fired, about 200 units a tick (some 55 ticks down the corridor). From when AIRMECHO raises its gun (the bolt leaves some 15
    ticks into FIRE_GUN) and while a bolt would pass within LANE units of him, he holds a sidestep (End / PgDn) away from its line: passes
    558 and 718 units off still hit, 1460 cleared. He shoots KP5 only while AIRMECHO stands at AIR_POSX (it fires as it walks out, and a
    walking target is missed), with no bolt on its way, and only when the shot ends before AIRMECHO's next FIRE_GUN, unless the shot kills
    it (LASER_HIT_AIRMECHO: 45 of 125 at Easy, three shots; 35 at Medium). He aims in the turn
    steps a short hold gives: left 1.41 degrees (4-7 ticks) or 11.25 (8-11), right 4.22 (3-5) or 11.25 (6-8). -> (shots, dodges)."""
    world, vm = seg.world, seg.vm
    shots, dodges = 0, 0
    fired = [None, mecho.motion, None]      # the tick of AIRMECHO's last FIRE_GUN, its motion last tick, the tick its last walk ended
    post = world.waypoints['AIR_POSX']

    def tick(n=1):
        for _ in range(n):
            seg.tick(1)
            if mecho.motion == 'FIRE_GUN' and fired[1] != 'FIRE_GUN':
                fired[0] = vm.tick
            if mecho.motion == 'STAND' and fired[1] == 'WALK':
                fired[2] = vm.tick
            fired[1] = mecho.motion

    def hold(scan, n):
        world.key_down(scan, 0)
        tick(n)
        world.key_up(scan, 0)
        tick(1)

    def over():
        return vm.objects['LEX'][0] <= 0 or vm.globals.get('_airmecho_dead') or lex.motion in ('RECOIL_ML', 'DIE')

    def incoming():
        """(ticks to Lex, the bolt's y there, the bolt) of every BOLTGRN not yet past him, soonest first."""
        found = []
        for b in world.items.values():
            if getattr(b, 'missile', False) and b.type == 'BOLTGRN' and b.vel[0] < 0 and b.pos[0] > lex.pos[0] - 300:
                t = (lex.pos[0] - b.pos[0]) / b.vel[0]
                found.append((t, b.pos[1] + b.vel[1] * max(t, 0), b))
        return sorted(found, key=lambda f: f[0])

    def threat():
        return next((f for f in incoming() if abs(f[1] - lex.pos[1]) < LANE), None)

    def due():
        """A volley is about to come: AIRMECHO walks its last stretch to AIR_POSX (it fires on arrival), or it stands there and its next
        FIRE_GUN is VOLLEY_LEAD ticks away. A sidestep (19 frames) drifts some 230 units the wrong way over frames 2-9, jumps some 700 over
        frames 10-14, then stalls; the bolt leaves while FIRE_GUN's frame 3 shows (8 ticks in) and needs some 36 ticks to reach Lex. Started
        5 ticks before FIRE_GUN, the bolt leaves just before the jump and Lex gets two jumps before it arrives."""
        if mecho.motion == 'WALK' and approx(mecho.pos, post) < ARRIVE:
            return True
        if mecho.motion == 'STAND' and fired[2] is not None and vm.tick - fired[2] <= 10 and approx(mecho.pos, post) <= 600:
            return True                                             # just arrived: it raises the gun 3 ticks later
        return (fired[0] is not None and mecho.motion == 'STAND' and approx(mecho.pos, post) <= 600
                and fired[0] + VOLLEY_PERIOD - VOLLEY_LEAD <= vm.tick <= fired[0] + VOLLEY_PERIOD + 10)

    def raising():
        """FIRE_GUN is playing. A laser hit stops it (stop_motion) and the pose stays frozen through AIRMECHO_AI's waits, about 100 ticks
        with no bolt: dodging all that time took Lex to the corridor's side, and the turn back crossed the next bolt's line."""
        return mecho.motion == 'FIRE_GUN' and not mecho.finished

    def dodge():
        """Hold a sidestep while AIRMECHO raises its gun or a bolt threatens: away from the soonest threatening bolt's line, else away
        from the corridor's side Lex is nearer (LEXSTUK: y -75727..-66821); chosen again when another bolt becomes the soonest. The
        first bolt of a raise keeps the sidestep already held: it was aimed where Lex stood as it left, so going on clears it, while
        turning back over a few units of a sidestep's first frames lost the time to clear it."""
        bolt, side = None, None
        while not over():
            f = threat()
            if f is None and not raising() and not due():
                break
            if side is None or (f is not None and f[2] is not bolt):
                keep = side is not None and bolt is None
                bolt = f[2] if f is not None else None
                want = (0x51 if f[1] > lex.pos[1] else 0x4f) if f is not None else (0x51 if lex.pos[1] > -72000 else 0x4f)    # PgDn: -y, End: +y
                if keep:
                    want = side
                if lex.pos[1] < -74500:
                    want = 0x4f
                elif lex.pos[1] > -67500:
                    want = 0x51
                if want != side:
                    if side is not None:
                        world.key_up(side, 0)
                    side = want
                    world.key_down(side, 0)
            tick()
        if side is not None:
            world.key_up(side, 0)
            tick()

    cycle = AIRMECHO_CYCLE - 20 * vm.globals.get('_difficulty_level', 0)
    laser = (45, 35, 25)[min(2, vm.globals.get('_difficulty_level', 0))] - 4         # LASER_HIT_AIRMECHO's DAMAGE, less its armour at worst

    def shot_is_safe():
        """A shot that kills is always worth it; any other must end before AIRMECHO raises its gun again, so the dodge starts with it."""
        if vm.objects['AIRMECHO'][0] <= laser:
            return True
        if incoming() or mecho.motion in ('WALK', 'FIRE_GUN') or approx(mecho.pos, post) > 600 or fired[0] is None:
            return False
        return vm.tick + SHOT_TICKS <= fired[0] + cycle

    def approx(a, b):
        return math.hypot(a[0] - b[0], a[1] - b[1])

    if lex.combat:                          # in combat End / PgDn are ATK_M1 / ATK_M3 and KP4 / KP6 circle: the duel is played out of it
        seg.key(COMBAT)
        seg.tick(5)
    start = vm.tick
    while vm.tick - start < budget and not over():
        if threat() is not None or raising() or due():               # its bolt leaves some 12 ticks into FIRE_GUN: a player who knows its rhythm moves first
            dodges += 1
            dodge()
            continue
        if lex.motion != worldmod.STAND or not shot_is_safe():
            tick()
            continue
        error = world.rel_angle(lex, mecho.pos) - AIRMECHO_AIM
        if abs(error) > 0.8:
            if error > 0:
                hold(0x4b, 8 if error > 8 else 4)                    # left: 11.25 or 1.41 degrees
            else:
                hold(0x4d, 6 if error < -8 else 3)                   # right: 11.25 or 4.22 degrees
        else:
            hold(SHOOT, 2)
            shots += 1
    return shots, dodges


def landpad_rest(seg, lex, mecho, ledge=None):
    world, vm = seg.world, seg.vm
    if lex.pos[2] > -2000:
        # `GO LEX_POS2 WALK` now ends within 614 units of its target and does not snap onto it (10e0:1a4c): 464 short, with Lex's hull 29
        # units inside LEXSTUK, which MARCHOUTAIRMECHO turns solid at its end (`_lexstuk_SPACE = _POSITIVE`, AIRHALL.scr:69). 03f2
        # has no step limit (the port-only LAND_REVERT clause is gone), so it offers the new solid's top and the stand-on-support
        # rule lifts Lex 6500 units onto the wall. Whether the original's per-tick arrival check ends clear of it is not known
        seg.set_pos((-27668, -71040), -90, 'GO LEX_POS2 WALK stopped 464 short, 29 units inside the LEXSTUK solid the scene makes '
                                            'solid afterwards; the port stands him on its top (NOTES "Movement fixes")', z=-5049)
    # 3. The fight (the blaster, out of combat: KP5 -> ATK_SHOOT -> BLASTER_FIRE)
    shots, dodges = airmecho_duel(seg, lex, mecho)
    seg.wait(lambda: vm.globals.get('_airmecho_dead'), 600)
    seg.step('airmecho-dead', bool(vm.globals.get('_airmecho_dead')) and seg.alive(), {'shots': shots, 'dodges': dodges})
    seg.wait(lambda: not any(p.block.name == 'AIRMECHO_DEATH' and not p.done for p in vm.procs.values()), 600)
    if lex_combat_off(seg):
        seg.tick(10)
    # 4. The airlock button and its monitor (LANDPAD.scr:143-190 -> LANDMON.scr:11): a lights-out grid solved with real presses
    for x, y in ((-20000, -68500), (-12000, -68500), (-6000, -72500), (-6000, -74300), (-3000, -74300)):     # north of the wreck (PHYS MECHO), then east: arriving on the
        seg.walk(x, y, radius=300)                                                                             # button's heading, as a big turn carries his hull off its box
    for _ in range(4):                               # a big turn still walks him off it (TURN_LEFT travels): come in again from the west, facing it
        seg.play.face(-80, tolerance=8)
        if math.hypot(lex.pos[0] + 3000, lex.pos[1] + 74300) < 300:
            break
        seg.walk(-4800, -74300, radius=300)
        seg.walk(-3000, -74300, radius=300)
    seg.use()
    opened = seg.wait(lambda: world.monitor is not None, 90) is not None
    seg.tick(60)                                     # AIRLOCK_MONITOR's WAIT 45, then CLRB_BUTTON draws the random start
    presses = solve_airlock(seg) if opened else None
    solved = seg.wait(lambda: vm.globals.get('_airlock_solved'), 300) is not None
    seg.wait(lambda: world.monitor is None, 300)
    seg.step('airlock-solved', solved and world.monitor is None, {'presses': presses})
    # 5. Through DRA, decontamination and DRB (LANDPAD.scr:209-349): HARD survives the outer door
    dra = seg.wait(lambda: vm.globals.get('_dr18_space') == 0, 300)       # AIRLOCK_DRA_OPEN after the win
    for x, y in ((-2500, -71200), (1700, -71200), (6900, -71200)):           # DR18, DRA_STRT, DECONTAM (ARL chamber)
        seg.walk(x, y, radius=300)
    opened = seg.wait(lambda: seg.ran('AIRLOCK_DRB_OPEN') and not seg.running('AIRLOCK_DRB_OPEN'), 9000)
    seg.tick(30)                                      # DRA_STRT's form check right after the outer door opens
    seg.step('decontamination', opened is not None and seg.alive(), {'dra_open_ticks': dra, 'decontam_ticks': opened})
    # 6. Across the pad (LANBOT1-4 hover and shoot) to the jetson tube: PAD_UP walks Lex down to DEST_DWN (LANDPAD.scr:421-439)
    for x, y in ((13500, -71200), (17000, -71200), (27000, -96000), (29000, -101400)):
        seg.walk(x, y, radius=300)
    seg.play.face(0, tolerance=8)                     # JET_BUT1_USE needs COMPASS IN -45, 45 (LANDPAD.scr:472-485)
    seg.use()
    seg.wait(lambda: seg.ran('JETSON_OPEN') and vm.globals.get('_jetson1_space') == 0, 300)     # LANDPAD.scr:596-637
    seg.walk(27200, -100600, radius=200)              # line up on the door (JETSON1 spans x 25918..28352)
    # into the open tube: the hull enters the lintel's box (JETSON1, ELVTP4) and PAD_UP's trigger fires on the way. The port-only LAND_REVERT
    # clause of `support` used to stand the lintel's bottom under Lex and slide him along it (blocker S-tube)
    seg.walk(27200, -104448, radius=250, stop=lambda: seg.ran('PAD_UP'))
    seg.step('walk-into-tube', seg.ran('PAD_UP'), {'at': [round(float(c)) for c in lex.pos]})
    down = seg.wait(lambda: seg.ran('PAD_UP') and not seg.running('PAD_UP'), 900)
    seg.step('jetson-tube', down is not None and seg.alive() and lex.pos[2] < -20000, {'ticks': down})
    # 7. Along the ledge (LDGBOT1-3, QUAKER, SHIP_GO) to TO_BCH: `LOADLEVEL BEACH FROM_PAD` (LANDPAD.scr:712-733)
    if ledge is not None:                             # the caller walks the ledge (and deals with its bots)
        ledge(seg)
    for x, y in ((25700, -114000), (25700, -140000), (25700, -170000), (25700, -200000), (26500, -212000)):   # PADLDG x 23038..28294
        if world.level != 'LANDPAD':
            break
        seg.walk(x, y, radius=400)
    seg.wait(lambda: world.level == 'BEACH', 120)
    seg.step('to-beach', world.level == 'BEACH' and seg.alive(), {'arrival': scenarios.plain(world.level_loads[-1])})


WALK_UNITS_PER_TICK = 55          # Lex's WALK root speed, measured on BEACH (552 units in 10 ticks)


def unteeter(seg):
    """At an edge the whoah motions repeat while Lex stands or turns; step away from the drop first (Down from a forward teeter,
    Up from a backward one), as a player would."""
    lex = seg.lex
    for _ in range(4):
        if not lex.motion.startswith('WHOAH'):
            return
        seg.wait(lambda: not lex.motion.startswith('WHOAH'), 60)
        seg.key(0x50 if 'FORWARD' in lex.motion or not lex.motion.startswith('WHOAH') else 0x48, 0, 10)


def approach(seg, x, y, radius=250, steps=20):
    """Short, exact walks for tight spots: face the bearing to (x, y), hold Walk for the ticks the distance needs. -> reached."""
    lex = seg.lex
    unteeter(seg)
    for _ in range(steps):
        dx, dy = x - lex.pos[0], y - lex.pos[1]
        dist = math.hypot(dx, dy)
        if dist < radius:
            return True
        seg.play.face(math.degrees(math.atan2(-dx, -dy)), tolerance=3)       # forward is (-sin h, -cos h)
        seg.key(0x48, 0, max(1, min(10, round(dist / WALK_UNITS_PER_TICK))))
        seg.wait(lambda: lex.motion == worldmod.STAND, 30)
    return False


def climb(seg, start, heading, top, budget=150):
    """Mantle onto the next block: stand at `start`, face `heading` (an axis: FUN_10a0_0ae5 wants the hull inside the block shrunk
    by 0x266 across the facing), hold Walk until Lex stands at the block's `top`: MANTLE_3 / 6 / 9 lift him by their root z. The run-up
    is placed (shortcut set_pos): turning on the spot from the zip's landing carries Lex sideways by up to 2000 units (turning drift),
    off the block's width, and the landing platform has no room to approach along the facing. -> ticks, or None."""
    lex = seg.lex
    seg.set_pos(start, heading, 'the mantle run-up: a turn on the spot carries Lex sideways off the block (turning drift)', z=lex.pos[2])
    seg.world.key_down(0x48)
    spent = seg.wait(lambda: lex.pos[2] - seg.world.foot(lex) >= top - 64 and not lex.motion.startswith('MANTLE'), budget)
    seg.world.key_up(0x48, 0)
    seg.tick(2)
    return spent


def lex_combat_off(seg):
    if seg.lex.combat:
        seg.key(COMBAT)
        return True
    return False


AIRLOCK_TOGGLES = {'ULTB': (0, 5, 7), 'UCTB': (1, 6, 8), 'URTB': (2, 3, 7), 'CLTB': (3, 2, 8), 'CCTB': (4, 0, 2, 6, 8),
                   'CRTB': (5, 0, 6), 'LLTB': (6, 1, 5), 'LCTB': (7, 0, 2), 'LRTB': (8, 1, 3)}     # LANDMON.scr:59-537, city not seen


def press_button(seg, name):
    """A mouse click on a monitor button: press, let MON_JUMP poll it, release."""
    seg.world.monitor.press(name)
    seg.tick(2)
    seg.world.monitor.release(name)
    seg.tick(2)


def solve_airlock(seg, target=495):
    """Press the buttons whose toggle sets (AIRLOCK_TOGGLES) turn the random start into `target` (LANDMON.scr:603). -> presses."""
    start = seg.vm.globals['_airlock_flag']
    names = list(AIRLOCK_TOGGLES)
    for mask in range(1 << len(names)):
        flag = start
        for i, name in enumerate(names):
            if mask >> i & 1:
                for bit in AIRLOCK_TOGGLES[name]:
                    flag ^= 1 << bit
        if flag == target:
            chosen = [n for i, n in enumerate(names) if mask >> i & 1]
            for name in chosen:
                press_button(seg, name)
            return chosen
    return None


def city_keypad_table():
    """The keypad's rule once the city has been seen (LANDMON.scr:59-570): a button toggles its own light and, by the button pressed before it, others. -> {name: (index, own bit, {previous: bits})}."""
    source = open(os.path.join(ROOT, 're', 'out', 'scripts', 'LANDMON.scr'), encoding='latin1').read()
    table = {}
    for index, name in enumerate(AIRLOCK_TOGGLES):
        body = source[source.index(f':{name}_BUTTON'):]
        body = body[:body.index('JUMP UPDATE_GRID')]
        own = int(re.search(r'TOGGLEFLAG \(_airlock_flag ,(\d)\)', body).group(1))
        cases = re.split(r'CASE (\d)', body[body.index('SWITCH'):])
        table[name] = (index, own, {int(cases[i]): [int(b) for b in re.findall(r'_airlock_flag ,(\d)', cases[i + 1])] for i in range(1, len(cases), 2)})
    return table


def solve_city_keypad(flag, previous, target=455):
    """Breadth first over (lights, previous button) to the target (LANDMON.scr:611). -> the button names."""
    table = city_keypad_table()
    seen, queue = {(flag, previous)}, collections.deque([(flag, previous, [])])
    while queue:
        lights, last, path = queue.popleft()
        if lights == target and path:
            return path
        for name, (index, own, by_previous) in table.items():
            after = lights ^ 1 << own
            for bit in by_previous.get(last, ()):
                after ^= 1 << bit
            if (after, index) not in seen:
                seen.add((after, index))
                queue.append((after, index, path + [name]))
    return None


def spawn_player_block(seg, block):
    """Start a level block for the player as its trigger or Use key would (World.spawn_for)."""
    return seg.world.spawn_for(seg.lex, block)


def carried_in(seg, hard=True):
    """What the levels before the surface leave behind (surface.md "Carried in"), staged on a fresh world."""
    if hard:
        seg.form('HARD', 'the CONTROL hard-suit machine (CONCNTRL.scr:116); the LANDPAD airlock and the surface air need it')
    seg.give('BLASTER', 'RTHAND', 'the CHAOS blaster')
    seg.give('BLOCK', 'LTHAND', 'the CONTROL artifact, readied from the inventory: the zips are <trigger>_BLOCK_USE (BEACHZIP.scr)')
    seg.set_global('_Reactor_Safe', 1, "CONTROL's reactor shutdown (SHUTDOWN.scr:113)")
    seg.set_global('_airmecho_dead', 1, 'the LANDPAD segment kills AIRMECHO (AI_AMECH.scr:59)')
    seg.set_global('_LandbotsAlive', 0, 'the LANDPAD bots are skipped there (blocker S-bots)')
    for n in (1, 2, 3):
        seg.set_global(f'_BchBot{n}_Alive', 0, 'fight skipped, outcome recorded: the beach bots kill a suited Lex in ~150 ticks at the '
                                               'arrival since PR #16 (blocker S-bots); BCHBOTn_AI returns when it is false')


# ---- BEACH
def beach(outer=None, to_zip1=None):
    """LANDPAD TO_BCH -> BEACH FROM_PAD -> zip lines to the lander -> warhead -> blast door -> SUITTES3 -> DIGSITE SUITTES2. With `outer` it
    starts where the LANDPAD walk ended (Lex has walked into TO_BCH): nothing is created or seeded."""
    seg = Segment('beach', 'LANDPAD', outer)
    world, vm = seg.world, seg.vm
    try:
        lex = seg.lex
        if not seg.attached:
            seg.create_lex()
            lex = seg.lex
            world.fire_event('LANDPAD_LOAD')
            carried_in(seg)
            # 1. The arrival through the engine's LOADLEVEL: the ledge trigger's block (LANDPAD.scr:712-733)
            seg.set_pos(seg.box_centre('TO_BCH'), 180, "the LANDPAD segment's end: Lex walks into TO_BCH on the ledge",
                        z=seg.trigger_box('TO_BCH')[1][2])
        seg.wait(lambda: world.level == 'BEACH', 60)
        seg.tick(30)
        seg.step('arrival', world.level == 'BEACH' and seg.alive() and world.level_loads[-1][2] == 'FROM_PAD',
                 {'arrival': scenarios.plain(world.level_loads[-1])})
        # 2. Down the blocks to the first zip line (BLOCK66 -> BLOCK65 -> ZIP1_A) and ride it with the artifact
        # (the ledge is narrow: when Lex arrives facing south from the LANDPAD walk, a single long walk drifts off it)
        if to_zip1 is not None:                           # the caller gets Lex to ZIP1 (past the bots)
            to_zip1(seg)
        else:
            for x, y in (((-1178500, -990000), (-1177873, -996000), (-1177873, -1002528)) if seg.attached else ((-1177873, -1002528),)):
                seg.walk(x, y, radius=600)
        seg.step('reach-zip1', seg.in_box('ZIP1_A') and seg.alive())
        rides = []
        for n, (a, b) in enumerate((('ZIP1_A', 'ZIP1_B'), ('ZIP2_A', 'ZIP2_B'), ('ZIP3_A', 'ZIP3_B'), ('ZIP4_A', 'ZIP4_B')), 1):
            if n == 4:                                           # climb BLOCK31 -> 32 -> 33 -> 34 -> 35, down to 37, over to 27
                up = climb(seg, (-1139600, -1024700), -90, -19841)
                seg.step('climb-block32', up is not None, {'z': round(float(lex.pos[2])), 'motion': lex.motion})
                seg.set_pos(seg.box_centre(a), -90, 'the rest of the block staircase (mantles onto BLOCK33-35, down to 37, over to 27) is not '
                                                   'driven; the first mantle, onto BLOCK32, is real', z=seg.trigger_box(a)[1][2])
            elif n > 1:
                x, y = seg.box_centre(a)                         # the blocks are narrow: turn on the spot first, a walk's steering takes him over the edge
                heading = math.degrees(math.atan2(lex.pos[0] - x, lex.pos[1] - y))
                if abs(seg.play.delta(heading)) > 100:           # each TURN_LEFT step carries him ~200 units sideways: 118 degrees from ZIP2_B (Medium, where the bots' hits leave him
                    seg.key(0x48, 0, 6)                          # facing back along the zip) took him over the block's +y edge; a step forward first, away from it
                    seg.tick(10)
                seg.play.face(heading)
                seg.walk(x, y, radius=500)
                if seg.attached and not seg.in_box(a):     # Lex arrives from the previous zip with a heading of its own and the walk drifts off the blocks
                    seg.set_pos(seg.box_centre(a), -90, f'the walk from the end of the previous zip to {a} drifted off the block path (turning drift)',
                                z=seg.trigger_box(a)[1][2])
            here = seg.in_box(a)
            seg.use()                                            # Space with BLOCK in LTHAND: <trigger>_BLOCK_USE
            ridden = seg.wait(lambda: seg.ran(f'{a}_BLOCK_USE') and vm.globals.get('_ziptripping') == 0, 600)
            rides.append({'zip': a, 'in_trigger': here, 'ticks': ridden, 'end': [round(float(c)) for c in lex.pos]})
            if not seg.step(f'zip{n}', ridden is not None and seg.in_box(b) and seg.alive(), rides[-1]):
                break
        # 3. The warhead on the lander shore (WARHEAD.scr:120-180): DISARM_USE puts the blaster down and the BOMB in RTHAND
        for x, y in ((-1117000, -1032600), (-1108000, -1032600)):
            seg.walk(x, y, radius=500)
        approach(seg, *seg.box_centre('DISARM'), radius=150)
        seg.use()
        bomb = world.items.get('BOMB')
        seg.wait(lambda: seg.ran('DISARM_USE') and not seg.running('DISARM_USE'), 900)
        blaster = world.items.get('BLASTER')
        seg.step('warhead', bomb is not None and bomb.owner == world.player_name and bomb.slot == 'RTHAND' and seg.alive(),
                 {'timer': vm.globals.get('_warhead_timer'), 'blaster_owner': blaster and blaster.owner,
                  'monitor': world.monitor is not None})
        # 4. Back to the blast tunnel with the bomb. The route the timer is tuned for (TIMER_25 at the ledge's south end) runs
        #    ZIP5 -> the dead beast's body -> ZIP6..8 -> block stairs, i.e. the gunnery-station beast kill plus mantles; staged.
        seg.set_pos((-1235000, -1031200), -90, 'carrying the bomb back needs the beast killed and block mantles (blocker '
                    'S-mantle); the lift pair TO_LDG/TO_LNDR is no way up (TO_LNDR lies inside PHYS CLIFF08)',
                    z=seg.trigger_box('FIREBTN2')[1][2])
        seg.key(0x17)                                         # I: the first press stows the left-hand BLOCK
        seg.tick(5)
        seg.key(0x1c)                                         # Enter: put the held bomb down -> LEX_BOMB_DROP (WARHEAD.scr:256)
        seg.wait(lambda: vm.globals.get('_warhead_status') == 2, 60)
        armed = vm.globals.get('_warhead_status') == 2
        seg.wait(lambda: world.monitor is None, 400)          # WARHEAD_MON shows the count until 50 (4-tick units) remain
        # One continuous run: Shift+Up east down the tunnel, then hold Right as well past its mouth (x -1214926) so Lex arcs south
        # onto CT1 and out of BOMBHALL (y -1035738..-1028314) before the fuse ends
        world.key_down(0x48, worldmod.keys_mod.SHIFT)
        seg.wait(lambda: lex.pos[0] > -1214500, 260)
        world.key_up(0x48, 0)
        for x, y in ((-1211500, -1038000), (-1212000, -1045000)):
            seg.walk(x, y, radius=600, run=True, stop=lambda: vm.globals.get('_warhead_timer', 0) <= 8)      # a walk step is 9-15 ticks, the fuse counts every 4
        escaped = [round(float(c)) for c in lex.pos]
        if vm.globals.get('_warhead_timer', 0) <= 8 and seg.in_hull_box('BOMBHALL'):
            seg.set_pos((-1212000, -1039000), 180, 'the warhead escape: after WARHEAD_MON closes there are 200 ticks, and the suited '
                        'run (~129 units/tick) ends a few hundred units inside BOMBHALL (problem S-escape)')
        blown = seg.wait(lambda: vm.globals.get('_blt_space') == 2, 600)            # DOOR_BLASTED (a CALL child): BLT neutral
        seg.step('door-blasted', armed and blown is not None and seg.alive() and vm.globals.get('_blt_space') == 2,
                 {'armed': armed, 'ticks': blown, 'blt_space': vm.globals.get('_blt_space'), 'escaped_to': escaped})
        if seg.attached:
            tumolt_tonfa(seg, outer)
        # 5. Through the blasted door to the suit machine: SUITTES3 -> HARDSUITMACHINE -> LOADLEVEL DIGSITE SUITTES2 (BEACH.scr:405-466)
        seg.wait(lambda: not seg.running('KNOCKLEXDOWN_1') and not seg.running('STAGGERLEX') and lex.motion == worldmod.STAND, 400)
        if lex.pos[0] > -1230000:                           # not already placed inside the tunnel (tumolt_tonfa)
            approach(seg, -1212000, -1036000)                 # the middle of CT1, then west into the tunnel
        for x, y in ((-1212000, -1031200), (-1240000, -1031200), (-1260000, -1031200), (-1274999, -1031031)):
            if world.level != 'BEACH':
                break
            if x > lex.pos[0] + 1000:                         # behind him already
                continue
            seg.walk(x, y, radius=500)
        seg.wait(lambda: world.level == 'DIGSITE', 900)
        seg.wait(lambda: not seg.running('HARD_SUIT_OPEN_DIG') and seg.ran('HARD_SUIT_OPEN_DIG'), 900)
        seg.step('to-digsite', world.level == 'DIGSITE' and seg.alive() and lex.type == 'LEX',
                 {'arrival': scenarios.plain(world.level_loads[-1]), 'form': lex.type})
    except Exception as exc:
        exc.segment = seg
        raise
    return seg


def tumolt_tonfa(seg, run):
    """The Captain's TONFA, the gun the zero-g room needs. He waits on the lander's back ramp until Lex has crossed RTMLT1 and comes back over RTMLT2 (AI_TUMLT.scr:1-8); his death
    drops the gun (TUMOLT_DEATH, AI_TUMLT.scr:380-410). A bomb in RTHAND leaves no hand for it (DISARM_USE puts down whatever the hand holds, WARHEAD.scr:128-132), so this comes after the blast."""
    world, vm, lex = seg.world, seg.vm, seg.lex
    seg.set_pos((-1096000, -1041700), -90, 'back to the lander: the way from the tunnel, by the ledge and the zip lines, is not driven', z=seg.trigger_box('DISARM')[1][2])
    import playthrough_full as pf
    pf.take(run, 'ZEDICAID')                    # the second medical device lies by the lander's ramp, before RTMLT2 wakes him
    run.key(0x17)
    run.tick(10)
    pf.heal(run, 100)
    if vm.objects['LEX'][0] < 100:
        pf.heal(run, vm.objects['LEX'][0] + 20)      # heal stops short of 100 rather than waste part of a charge; this fight is worth it (at 81 HP he wins about half, at 98 nearly all)
    for x, y in ((-1088000, -1041700), (-1085500, -1050000), (-1085500, -1060800)):
        run.goto(x, y, radius=500)
    run.dash((-1085500, -1056000), until=lambda: vm.globals.get('_tumolt_activated'), stop=100)
    run.until(lambda: vm.globals.get('_tumolt_activated') and lex.ai_enabled, 3000, "the Captain's speech ends")
    captain_fight(run, world.figure('TUMOLT'))
    run.until(lambda: seg.ran('TUMOLT_DEATH') and not seg.running('TUMOLT_DEATH'), 2000, "the Captain's death ends")
    if lex.combat:
        run.key(0x2e)
        run.tick(5)
    y = world.items['TONFA'].pos[1]             # something stops a straight walk across y -1059616 west of the ramp; the way he came, along x -1085500, is open
    if abs(lex.pos[1] - CAPTAIN_LEDGE_Y) < 1000 or (lex.pos[1] < CAPTAIN_LEDGE_Y) != (y < CAPTAIN_LEDGE_Y):
        run.goto(-1085500, lex.pos[1], radius=500)
        run.goto(-1085500, y, radius=500)
    for attempt in range(3):                    # he drops KEYDVICE too (READY_TUMOLT gives it to his LTHAND), and Enter takes the nearer: stow it and press again; a turn beside the gun can also carry Lex 1800 units off (turning drift): then approach again
        try:
            run.pick_up('TONFA')
            break
        except Stuck:
            if world.held_item(lex, 'LTHAND') is not None:
                run.key(0x17)
                run.tick(10)
            if attempt == 2:                    # the last press can take KEYDVICE too: stowed above, then take walks round
                import playthrough_full as pf
                pf.take(run, 'TONFA')           # the straight approach stays blocked where the fight left it: take walks round
    seg.step('tonfa', world.is_carrying_item(lex, 'RTHAND', 'TONFA'), {'lex': world.hit_points(lex)})
    # inside the tunnel, not at its mouth on CT1: a beach bot still alive there (BCHBOT3 survives on some streams) keeps him in recoil until he dies
    seg.set_pos((-1240000, -1031200), 90, 'back to the blast tunnel from the lander, the way above', z=seg.trigger_box('FIREBTN2')[1][2])


def captain_fight(run, captain):
    """The Captain by real keys. KP1 held dodges the shot that ends his speech (ACTIVATE_TUMOLT: WAIT 10, MOTION SHOOT, AI_TUMLT.scr:94-99). Then Alt+KP4 (ATK_H4) is tapped at a steady
    rhythm whatever he is doing, with no reaction to his moves: the win does not depend on the rhythm (10 of 11 streams at each of 4, 6, 9 and 12 ticks). Lex only stops for his own recoils, and turns toward him when he is off to the side and only walks up when he has wandered far off, and switches BIOREPAIR on under CAPTAIN_HEAL_BELOW while the battery allows it."""
    world, vm, lex = run.world, run.vm, run.lex
    import playthrough_full as pf
    medkits = 4
    world.key_down(0x4f, 0)
    run.tick(40)
    world.key_up(0x4f, 0)
    run.tick(1)
    for _ in range(CAPTAIN_STEPS):
        if vm.objects['LEX'][0] <= 0 or vm.objects['TUMOLT'][0] <= 0:
            return
        if not lex.ai_enabled or (lex.motion.startswith(('RECOIL', 'SUPER', 'SHOCK')) and not lex.finished):
            run.tick(1)
        elif not lex.combat:
            run.key(0x2e)
            run.tick(5)
        elif vm.objects['LEX'][0] < CAPTAIN_MEDKIT_BELOW and medkits > 0:
            medkits -= 1                                # a bad spell late in the fight: the kits are worth more now than after it
            try:
                pf.heal(run, vm.objects['LEX'][0] + 40, fighting=True)
            except (pf.Stuck, AttributeError):          # a blow closed the monitor under the click: fight on
                run.tick(1)
        elif vm.objects['LEX'][0] < CAPTAIN_HEAL_BELOW and vm.globals.get('_bio_state') != 1 and vm.objects['MY_BATTERY'][0] >= 10:
            try:
                run.start_repair()
            except (pf.Stuck, AttributeError):          # a blow closed the monitor under the click: fight on, the next pass tries again
                run.tick(1)
        else:
            distance, bearing = math.hypot(*(captain.pos[:2] - lex.pos[:2])), world.rel_angle(lex, captain.pos)
            if abs(bearing) >= 50 and not lex.motion.startswith(run.BUSY):
                run.key(0x4b if bearing > 0 else 0x4d, 0, 5)
                run.tick(4)
            elif distance > run.REACH + CAPTAIN_STEP_IN and not lex.motion.startswith(run.BUSY):
                run.key(0x48, 0, 3)
                run.tick(4)
            else:
                run.key(0x4b, worldmod.keys_mod.ALT, 1)
                run.tick(CAPTAIN_RHYTHM - 2)


def zero_g_flight(run, trigger):
    """Across the zero-g room by the gun's recoil to `trigger`. KP5 is ZEROG_KEYBOARD's ZERO_G_FIRE (TUNZEROG.scr:119-131), whose shot pushes Lex directly away from where he faces (LEAP CURFIG 0 6,
    ITEMS.scr:1153); KP4 and KP6 turn him 10 degrees a tick (ZEROG_TURNING). After the city ZEROG_GRAVITY's pull to GRAVPT (LEAP CURFIG GRAVPT 0 2 every 15 ticks) takes more than a shot gives between
    two shots, so standing shots get nowhere: Lex fires only while he is already moving toward the trigger, where the same push raises his swing the most."""
    world, vm, lex = run.world, run.vm, run.lex
    run.until(lambda: world.current_camera().startswith('ZEG') and lex.ai_enabled, 200, 'the zero-g camera')       # ZEG_LOAD's MOTION FLOAT would end a shot fired before it
    run.tick(1)
    box = next(t for t in world.triggers if t['name'] == trigger)
    x, y = (box['lo'][0] + box['hi'][0]) / 2, (box['lo'][1] + box['hi'][1]) / 2
    held = None
    for _ in range(ZERO_G_LIMIT):
        if world.level != 'TUNROOM' or run.running(trigger):
            break
        if lex.motion == 'ZERO_G_FIRE' and lex.idx < ZERO_G_SHOT_FRAME:      # the shot pushes along his heading when it leaves
            if held:
                world.key_up(held)
                held = None
            run.tick(1)
            continue
        dx, dy = x - lex.pos[0], y - lex.pos[1]
        scale = ZERO_G_SPEED / math.hypot(dx, dy)
        cx, cy = dx * scale - lex.vx, dy * scale - lex.vy
        error = (math.degrees(math.atan2(cx, cy)) - lex.heading + 180) % 360 - 180
        turn = None if abs(error) <= 6 else 0x4d if error > 0 else 0x4b
        if turn != held:
            if held:
                world.key_up(held)
            if turn:
                world.key_event(turn)
            held = turn
        if turn is None and (lex.vx * dx + lex.vy * dy) * scale > ZERO_G_CLOSING * ZERO_G_SPEED and lex.motion != 'ZERO_G_FIRE' and vm.globals.get('_tonfa_used', 0) < 6:
            world.key_event(0x4c)
            world.key_up(0x4c)
        run.tick(1)
    if held:
        world.key_up(held)
    if world.level == 'TUNROOM' and not run.running(trigger):
        raise Stuck(f'the zero-g flight did not reach {trigger}: {[int(v) for v in lex.pos[:2]]}')


# ---- DIGSITE (probe)
ZERO_G_SPEED = 400           # the velocity the shots try to reach, raw units a tick; a shot adds about 126
ZERO_G_CLOSING = 100         # fire when moving this fast toward the trigger: the same push is worth the most energy at speed
ZERO_G_SHOT_FRAME = 9        # ZERO_G_FIRE: the frame the gun fires on
ZERO_G_LIMIT = 4000
CAPTAIN_STEPS, CAPTAIN_RHYTHM, CAPTAIN_HEAL_BELOW, CAPTAIN_LEDGE_Y = 6000, 9, 100, -1059616     # BIOREPAIR whenever the battery allows (at 60, four streams lost since the fists came down on leaving combat) and a beat of 9 ticks
CAPTAIN_MEDKIT_BELOW = 35
CAPTAIN_STEP_IN = 3000       # Lex only walks up to him from further than this: stepping in after each hit (REACH + 300) lost 7 of 24 streams, standing his ground and letting him come won 48 of 48 at 3000; since the fists come down on leaving combat 2000 won more, and since a woken waiter runs in the next walk 3000 again (24 of 24 reseeded draws from the full run's fight, 2000 lost the full run's own; his knockback puts him out of reach, but he closes in himself, and every step Lex takes is a beat lost)
TOMB_PRESSES = (('LTUB', 1), ('LTCB', 2), ('LTLB', 1), ('RTLB', 1), ('RTCB', 2), ('RTUB', 2))      # from _tomb_flag1..6 = 2 2 0 1 1 1 to _tomb_sol1..6 = 0 1 1 2 0 0 (TOMBMON.scr: SET_UP_SOLUTION)


def tomb_monitor(seg, run):
    """The walk from the suit machine to the tomb, Space tears the door off (OPENTOMB_USE), Space again runs TOMB_MONITOR (SHOWTMB4, COMPASS -105..-15, DIGSITE.scr:282-349), the buttons
    by clicks; TOMBPUZZLESOLVED ends in GETKEY, which gives the KEY into LTHAND (DIGSITE.scr:236-258)."""
    world, vm, lex = seg.world, seg.vm, seg.lex
    for x, y in ((64000, -12000), (63800, 0), (63800, 15000), (63800, 29000), (66000, 40000), (68500, 45500), (69900, 46900)):
        run.goto(x, y, radius=450)
    run.face(-90, tolerance=12)
    for _ in range(8):
        if 'OPENTOMB' in world.usable_objects(lex):
            break
        run.key(0x48, 0, 4)
    if run.use() != 'OPENTOMB_USE':
        raise Stuck('Space at the tomb did not run OPENTOMB_USE')
    run.until(lambda: vm.globals.get('_open_frame') != 1 and not run.running('OPENTOMB_USE'), 1500, 'the tomb door comes off')
    run.face(-60, tolerance=25)
    if run.use() != 'OPENTOMB_USE':
        raise Stuck('the second Space at the tomb did not run OPENTOMB_USE')
    run.until(lambda: world.monitor is not None, 500, 'the tomb monitor opens')
    run.tick(120)                                                   # START_FLASH, then SET_UP_SOLUTION
    for name, presses in TOMB_PRESSES:
        for _ in range(presses):
            run.click(name)
    run.until(lambda: vm.globals.get('_tomb_solved') == 1, 400, 'the tomb puzzle is solved')
    run.until(lambda: 'KEY' in world.items and world.items['KEY'].owner == world.player_name and not run.running('GETKEY'), 900, 'GETKEY gives the KEY')
    if 'TONFA' in world.items:                                      # OPENTOMB_USE made Lex put it down (FREEHAND RTHAND, DIGSITE.scr:298)
        run.pick_up('TONFA')


def digsite(outer=None):
    """BEACH SUITTES3 -> DIGSITE SUITTES2 -> the tomb -> the key on the dig tube -> THE_DIGTUBE's `LOADLEVEL TUNROOM TUBE_WP4`.
    A probe: the Drogg fight and the tomb monitor are staged (surface.md lists what they need). With `outer` it starts where the BEACH walk
    ended (Lex has walked into SUITTES3): nothing is created or seeded."""
    seg = Segment('digsite', 'BEACH', outer)
    world, vm = seg.world, seg.vm
    try:
        lex = seg.lex
        if not seg.attached:
            seg.create_lex()
            lex = seg.lex
            world.fire_event('BEACH_LOAD')
            carried_in(seg)
            # 1. The arrival through the suit machine (BEACH.scr:405-466): Lex stands in SUITTES3 behind the blasted door
            seg.set_pos(seg.box_centre('SUITTES3'), 90, "the BEACH segment's end: Lex walks into SUITTES3", z=seg.trigger_box('SUITTES3')[1][2])
        seg.wait(lambda: world.level == 'DIGSITE', 600)
        seg.wait(lambda: seg.ran('HARD_SUIT_OPEN_DIG') and not seg.running('HARD_SUIT_OPEN_DIG'), 900)
        seg.step('arrival', world.level == 'DIGSITE' and lex.type == 'LEX' and seg.alive(),
                 {'arrival': scenarios.plain(world.level_loads[-1])})
        # 2. Drogg and the tomb: staged outcomes
        seg.set_global('_Drogg2_Alive', 0, 'the Drogg fight ends in DROGG2_ESCAPE after 22 hits and a super-recoil (AI_DROG2.scr:346-476); '
                                          'not driven')
        if seg.attached:
            tomb_monitor(seg, outer)
        else:
            seg.set_global('_tomb_solved', 1, 'the tomb monitor (TOMBMON.scr: LTUB LTCB LTLB RTLB RTCB RTUB pressed 1 2 1 1 2 2); not driven')
            world.items['BLOCK'].slot = 'INVENTORY'               # the tomb sequence frees both hands (OPENTOMB_USE: FREEHAND)
            seg.give('KEY', 'LTHAND', 'GETKEY gives the tomb KEY into LTHAND (DIGSITE.scr:236-258)')
        # 3. The key on the dig tube: DIGTUBE_KEY_USE -> THE_DIGTUBE (DIGSITE.scr:674-703, DIGTUBE.scr)
        if seg.attached:
            for x, y in ((66000, 40000), (63800, 29000), (63800, 0), (63000, -12000), (57500, -18600), (56400, -18600)):
                outer.goto(x, y, radius=350)
            # The walk's last heading decides whether Lex's hull reaches the DIGTUBE box (a 0.2 degree difference was enough): face
            # the box and step in until Space would use it, as tube_monitor does at the pillar base
            outer.face_point(*seg.box_centre('DIGTUBE'), tolerance=10)
            for _ in range(8):
                if 'DIGTUBE' in world.usable_objects(lex):
                    break
                outer.key(0x48, 0, 4)
        else:
            seg.set_pos(seg.box_centre('DIGTUBE'), 90, 'next to the dig tube (walking from SUITTES2 not driven)', z=-7857)
        seg.use()
        seg.wait(lambda: world.level == 'TUNROOM', 900)
        seg.wait(lambda: seg.ran('THE_DIGTUBE') and not seg.running('THE_DIGTUBE'), 900)
        survived = not seg.running('THE_DIGTUBE') and seg.ran('THE_DIGTUBE')
        seg.step('dig-tube-to-tunroom', world.level == 'TUNROOM' and survived and not lex.invulnerable and seg.alive(),
                 {'arrival': scenarios.plain(world.level_loads[-1]), 'invulnerable': lex.invulnerable,
                  'ai_on': bool(lex.ai_enabled), 'used': world.key_log[-1:]})
    except Exception as exc:
        exc.segment = seg
        raise
    return seg


# ---- TUNROOM (probe)
def tube_monitor(run, start, buttons, bit):
    """From `start`, facing PIL_BASE (FACINGPILLARBASE, TUNMON.scr:4), Space on the pillar base walks Lex to the console (GOTOTML0, TUNMON.scr:69-120); the TUNM buttons by clicks and SOLB
    toggle a tube in `_TubesOpen` (TS_TUBEACTIVATIONMONITOR, TUNMON.scr:163-418)."""
    world, vm = run.world, run.vm
    run.goto(*start, radius=300)
    run.face_point(8142, -27403, tolerance=15)
    for _ in range(8):
        if {'TMLFT', 'TMBOTL', 'TUBEMON'} & set(world.usable_objects(run.lex)):
            break
        run.key(0x48, 0, 4)
    if run.use() not in ('TMLFT_USE', 'TMBOTL_USE', 'TMRGT_USE', 'TMBOTR_USE', 'TUBEMON_USE'):
        raise Stuck(f'Space at the pillar base started no walk to the console (Lex at {[int(v) for v in run.lex.pos[:2]]})')
    run.until(lambda: world.monitor is not None, 900, 'the tube monitor opens')
    run.tick(5)
    for name in buttons:
        run.click(name)
    run.click('SOLB')
    if not vm.globals.get('_tubesopen', 0) >> bit & 1:
        raise Stuck(f'the tube monitor did not open tube {bit}')
    run.until(lambda: world.monitor is None and run.lex.ai_enabled and not run.running('GOTOTML0'), 900, 'Lex leaves the console')


def tunroom(outer=None):
    """TUNROOM tube monitor -> TO_0G_USE (the zero-g room) -> TO_FINAL's `LOADLEVEL PLATFORM FRMZEROG`, the exit to the base. With `outer` it
    starts where the DIGSITE walk ended (THE_DIGTUBE has loaded TUNROOM): nothing is created or seeded."""
    seg = Segment('tunroom', 'DIGSITE', outer)
    world, vm = seg.world, seg.vm
    try:
        lex = seg.lex
        if not seg.attached:
            seg.create_lex()
            lex = seg.lex
            world.fire_event('DIGSITE_LOAD')
            carried_in(seg, hard=False)
            # 1. The arrival: THE_DIGTUBE's LOADLEVEL (DIGTUBE.scr:32), run as the DIGSITE probe does
            seg.set_pos(seg.box_centre('DIGTUBE'), 90, 'the DIGSITE probe ends here', z=-7857)
            seg.set_global('_TubesOpen', 1 << 4, 'the dig-tube key set bit 4 (DIGSITE.scr:690)')
            spawn_player_block(seg, 'THE_DIGTUBE')
        seg.wait(lambda: world.level == 'TUNROOM', 900)
        seg.wait(lambda: seg.ran('THE_DIGTUBE') and not seg.running('THE_DIGTUBE'), 900)
        seg.step('arrival', world.level == 'TUNROOM' and seg.alive(), {'arrival': scenarios.plain(world.level_loads[-1])})
        start = lex.pos.copy()
        seg.key(0x48, 0, 20)                                   # THE_DIGTUBE leaves MOTION ENTER_GRAV FREEZE: do the keys move Lex?
        seg.step('walk-after-tube', float(np.hypot(*(lex.pos[:2] - start[:2]))) > 300,
                 {'moved': round(float(np.hypot(*(lex.pos[:2] - start[:2])))), 'motion': lex.motion})
        # 2. The tube monitor's zero-g combination (TUNMON.scr:329-377: TN4B TN5B TN8B then SOLB sets bit 2)
        if seg.attached:
            tube_monitor(outer, (5450, -27400), ('TN4B', 'TN5B', 'TN8B'), 2)
        else:
            vm.globals['_tubesopen'] = vm.globals.get('_tubesopen', 0) | 1 << 2
            seg.stage('global', '_TubesOpen |= bit 2', 'the tube monitor TN4B+TN5B+TN8B, SOLB (TUNMON.scr:329-377); not driven')
        seg.set_pos(seg.box_centre('TO_0G'), 0, 'at the zero-g tube (TO_0G, TUNROOM.scr:169)', z=-10240)
        seg.use()
        seg.wait(lambda: seg.ran('TO_0G_USE') and not seg.running('TO_0G_USE'), 1500)
        seg.step('zero-g-room', seg.ran('TO_0G_USE') and not lex.gravity and seg.alive(),
                 {'gravity': lex.gravity, 'keyboard': getattr(world, 'keyboard_block', None)})
        # 3. Into TO_FINAL: flown
        if seg.attached:
            zero_g_flight(outer, 'TO_FINAL')
        else:
            seg.set_pos(seg.box_centre('TO_FINAL'), 0, 'flying the zero-g room by blaster recoil is not driven', z=-6000)
        seg.wait(lambda: world.level == 'PLATFORM', 300)
        seg.wait(lambda: seg.ran('TO_FINAL') and not seg.running('TO_FINAL'), 900)
        seg.step('exit-to-platform', world.level == 'PLATFORM' and not seg.running('TO_FINAL') and lex.gravity and seg.alive(),
                 {'arrival': scenarios.plain(world.level_loads[-1]), 'pos': [round(float(c)) for c in lex.pos]})
    except Exception as exc:
        exc.segment = seg
        raise
    return seg


SEGMENTS = [('landpad', landpad), ('beach', beach), ('digsite', digsite), ('tunroom', tunroom)]


def run_all(out_dir=None):
    reports = [run_segment(name, body) for name, body in SEGMENTS]
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
        with open(os.path.join(out_dir, 'report.json'), 'w', encoding='utf-8') as handle:
            json.dump(scenarios.plain(reports), handle, indent=2, sort_keys=True)
    return reports


def summary(reports):
    lines = []
    for r in reports:
        lines.append(f"== {r['segment']}: {'ok' if r.get('ok') else 'BLOCKED'}")
        for s in r['steps']:
            extra = ''.join(f' {k}={s[k]}' for k in ('detail', 'error') if s.get(k))
            lines.append(f"  [{'ok' if s['ok'] else 'FAIL'}] {s['step']} t={s.get('tick')} {s.get('camera', '')} {s.get('lex', '')}{extra}")
            for k in ('warnings', 'vm_warnings', 'unmodelled'):
                for m in s.get(k, []):
                    lines.append(f'      {k}: {m}')
        for c in r['shortcuts']:
            lines.append(f"  staged {c['kind']}: {c['what']}")
    return '\n'.join(lines)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--out', help='directory for report.json')
    args = parser.parse_args()
    print(summary(run_all(args.out)))
