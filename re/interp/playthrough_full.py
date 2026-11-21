"""One continuous deterministic run of the Python port: a new game to `EXIT`, in a single World / VM. The route and what it found are in
re/playthrough/full.md. Run from the repository root:
    re/.venv/bin/python -I -W ignore re/interp/playthrough_full.py [--out DIR] [--stop-after LEG] [--seed N] [--difficulty easy|medium|hard]

The legs reuse the segment functions of the three stretch harnesses (playthrough_prison, playthrough_surface, playthrough_base): they take
the run that is already going instead of creating a world, so inventory, globals, HP, moved floors and figure state carry from one level
to the next. No leg creates Lex, seeds a global or an item, or places Lex at an arrival. The allowed shortcuts (fights the keys cannot win
yet, monitor UI that is not driven, `set_pos` next to a trigger) are logged in SHORTCUTS with their reasons; a global or an item the next
stretch needs and the real play did not set is a finding (Run.problem), not something to paper over.
"""
import argparse
import json
import math
import os
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import playthrough_base as pb  # noqa: E402
import playthrough_prison as pp  # noqa: E402
import playthrough_surface as ps  # noqa: E402
import scenarios  # noqa: E402
import world as worldmod  # noqa: E402

Stuck = pp.Stuck
KEY_ENTER, KEY_SPACE, KEY_I = pp.KEY_ENTER, pp.KEY_SPACE, pp.KEY_I

# Logged shortcuts of this run (the prison harness's own are inherited). A run records the ones it used (Run.shortcuts).
SHORTCUTS = dict(pp.SHORTCUTS)
SHORTCUTS.update({
    'ring-pads': 'The gravity ring pads RING3, RING6, RING1, RING3 (TUNGRAV.scr:520-545, the solution in the comment at TUNGRAV.scr:590-600) lie in one row; '
                 'Lex is put on each pad in turn instead of walking between them (the pads in between would turn their rings too).',
})
SHORTCUTS['difficulty'] = ('Medium or Hard is set when the prison is done (after the guard1 leg): the opening replay picks Medium on the dialog, and the prison is '
                           'played at Easy (`difficulty-easy`); a player would choose the level once, at the start.')
SHORTCUTS.update({k: v for k, v in pb.SHORTCUTS.items() if k in ('hold-fire', 'fight-outcome', 'set-pos', 'trigger', 'unstick', 'globals')})


class Full(pp.Run):
    """The prison harness's driver with this run's shortcut catalogue. `difficulty`: the level from the leg after guard1 on (0 Easy, 1 Medium, 2 Hard)."""
    difficulty = 0

    @property
    def catalog(self):
        return SHORTCUTS

    def goto(self, x, y, **kwargs):
        """Walking is done out of combat mode (C toggles it): in combat mode Up is the ATK_M8 circling move, which does not take Lex anywhere."""
        if self.lex.combat:
            self.key(0x2e)
            self.tick(10)
        return super().goto(x, y, **kwargs)

    def dash(self, *points, stop=1200, until=None, limit=800):
        """Run through `points` the way a player does: Shift+Up held throughout, the turn keys steering at 4 degrees a tick (goto stops to turn and walks its last 2000 units; the
        reactor's countdown has no time for that). Takes a point `stop` short, ends at the last one or when `until()`, then coasts about 900 units."""
        lex, turning, points = self.lex, None, list(points)
        self.world.key_down(0x48, worldmod.keys_mod.SHIFT)
        for _ in range(limit):
            dx, dy = points[0][0] - lex.pos[0], points[0][1] - lex.pos[1]
            if math.hypot(dx, dy) < stop and len(points) > 1:
                points.pop(0)
                continue
            if (until() if until else math.hypot(dx, dy) < stop) or self.vm.objects['LEX'][0] <= 0:
                break
            delta = self.delta(math.degrees(math.atan2(-dx, -dy)))
            want = None if abs(delta) < 4 else 0x4d if delta > 0 else 0x4b
            if want != turning:
                if turning:
                    self.world.key_up(turning, worldmod.keys_mod.SHIFT)
                if want:
                    self.world.key_down(want, worldmod.keys_mod.SHIFT)
                turning = want
            self.tick(1)
        if turning:
            self.world.key_up(turning, 0)
        self.world.key_up(0x48, 0)
        self.tick(1)


def heal(run, enough=75, fighting=False):
    """MEDICAID's and ZEDICAID's charges first (DOMEDUSE, ITEMS.scr:652-656: 20 HP each, 5 in each level record), then BIOREPAIR with the battery.
    MEDICAID_USE's `SETCURRENTITEM MEDICAID` takes the item of that name or type nearest the player (10c0:3fd9, items.find_item), and
    ZEDICAID is of type MEDICAID: carried in the inventory it lies at Lex's own position, nearer than the kit in his hand, so a MEDICAID
    use spends ZEDICAID's charges, and once those are gone it fails (USE_MEDIC_FAIL). A player then puts the empty kit down, and so does this.
    `fighting`: no put-down, which costs blows mid-fight."""
    world, vm, lex = run.world, run.vm, run.lex
    was_held = world.held_item(lex, 'LTHAND')
    def put_down_empties():
        full = world.items.get('MEDICAID')
        if not fighting and full is not None and full.owner == lex.name and vm.objects[full.key][0] > 0:      # whatever his HP: the kit is put down before a fight, not during it
            for empty in [i for i in world.items.values() if i is not full and i.owner == lex.name and i.type == 'MEDICAID' and vm.objects[i.key][0] <= 0]:
                ready_item(run, empty.key)
                run.key(0x1c)                                       # Enter: PUT_DOWN_LTHAND
                run.until(lambda: empty.owner is None, 120, f'Enter puts the empty {empty.key} down')
    put_down_empties()
    for name in ('MEDICAID', 'ZEDICAID'):
        item = world.items.get(name)
        while item is not None and item.owner == lex.name and vm.objects[item.key][0] > 0 and vm.objects['LEX'][0] + 20 <= enough and not any(f'{obj}_USE' in vm.blocks for obj in world.usable_objects(lex)):   # Space takes an object in reach first
            if world.held_item(lex, 'LTHAND') is not item:
                ready_item(run, name)
            charges = vm.objects[item.key][0]
            for _ in range(4):                                      # Space does nothing until his last motion has let go
                used = run.use()
                if used is not None:
                    break
                run.tick(20)
            if used != f'{name}_USE':
                break
            for _ in range(500):                                    # the first use also waits for its journal entry; a blow can interrupt it, which need not stop the run
                if not run.running(f'{name}_USE') and not lex.motion.startswith('USE_MEDIC'):
                    break
                run.tick(1)
            else:
                break
            if vm.objects[item.key][0] >= charges:                  # USE_MEDIC_FAIL (the mirror suit, among others) uses no charge: trying again would loop for ever
                break
        if item is not None and world.held_item(lex, 'LTHAND') is item:
            for _ in range(3):                                      # a LEVEL1TREMORS quake that starts just after the press takes it (AI off)
                run.key(0x17)
                for _ in range(60):
                    if world.held_item(lex, 'LTHAND') is None:
                        break
                    run.tick(1)
                if world.held_item(lex, 'LTHAND') is None:
                    break
            run.until(lambda: world.held_item(lex, 'LTHAND') is None, 60, f'I stows {name}')
    pp.heal(run, enough)                                            # its first key stows the left hand too
    put_down_empties()
    if was_held is not None and world.held_item(lex, 'LTHAND') is not was_held:         # the zip lines want the BLOCK back in that hand
        ready_item(run, was_held.key)


# ---- legs --------------------------------------------------------------------------------------------------------------------

def guard1(run):
    """Cell 2: ENTERCELL2 (TOCELL2's tail) starts the authored ACTIVATE_GUARD1 / GREET_GUARD1; Lex punches Guard 1 down at Easy
    (scenarios.chaos_guard1_fight on this run, nothing staged), then picks up the BLASTER the guard's cell holds (495, -29827; Enter,
    LEX_BLASTER_TAKE, AI_LEX.scr:395)."""
    with run.segment('guard1'):
        run.HEAL_BELOW = GUARD1_HEAL_BELOW
        report = scenarios.chaos_guard1_fight(0, play=run, seed=None)
        del run.HEAL_BELOW                                          # back to the class's threshold
        run.lex = run.world.player()
        if run.world.level == 'TANKS' and not report['encounter']['guard_alive'] and run.vm.objects['LEX'][0] > 0:
            pp.tanks_to_cell2(run)                                  # the last blow backed Lex into the cell's hole: TOCELL2 again
            run.lex = run.world.player()
            run.until(lambda: run.lex.ai_enabled, 900, 'ENTERCELL2 gives Lex back')
        for _ in range(3):                                          # a hit backed him into it with the guard still up: back, and finish the fight
            if run.world.level != 'TANKS' or run.vm.objects['LEX'][0] <= 0:
                break
            pp.tanks_to_cell2(run)
            run.lex = run.world.player()
            run.until(lambda: run.lex.ai_enabled, 900, 'ENTERCELL2 gives Lex back')
            run.fight(run.world.figures['GUARD1'], lambda: bool(run.vm.globals.get('_grd1_alive')))
            run.lex = run.world.player()
            report['encounter']['guard_alive'] = run.vm.globals.get('_grd1_alive')
        if report['encounter']['guard_alive'] or run.vm.objects['LEX'][0] <= 0:
            raise Stuck(f"Guard 1 fight lost (Lex {run.vm.objects['LEX'][0]} HP, guard {report['encounter']['guard_health']})")
    with run.segment('blaster'):
        for _ in range(3):
            if run.world.level == 'TANKS' and run.vm.objects['LEX'][0] > 0:   # through the cell's hole after the fight, or on the way round it: back
                pp.tanks_to_cell2(run)
                run.lex = run.world.player()
                run.until(lambda: run.lex.ai_enabled, 900, 'ENTERCELL2 gives Lex back')
            if run.world.level == 'CHAOS' and run.lex.pos[1] < -32300:     # the fight ended south of the hole's north edge (QCLHOL1-5, x -3115..-410,
                run.goto(1500, run.lex.pos[1], radius=400)                # y -35192..-32541): east of it first, then north, or the walk to the BLASTER
                run.goto(1500, -31000, radius=400)                        # clips its edge and drops Lex into TANKS
            if run.world.level == 'CHAOS':
                break
        run.pick_up('BLASTER')
        if not run.world.is_carrying(run.lex, 'RTHAND', 'BLASTER'):
            raise Stuck('the BLASTER is not in the right hand')


def take(run, item, radius=300):
    """Walk up to the floor item and press Enter until Lex holds it (Play's pick_up stops 700 units short, which a HARD Lex's reach does not cover)."""
    target = run.world.items[item]
    for attempt in range(12):
        if target.owner == run.lex.name or target.pos is None:
            break
        run.goto(target.pos[0], target.pos[1], radius=radius)
        if target.pos is None:
            break
        if attempt < 4 and math.hypot(target.pos[0] - run.lex.pos[0], target.pos[1] - run.lex.pos[1]) > 3 * radius:
            # a straight walk stopped short: something stands between (REFLECT can lie behind the PLATFORM pillar BATPLR5): go round it
            side = 2500 if attempt % 2 == 0 else -2500
            run.goto(target.pos[0] + side, run.lex.pos[1], radius=500)
            run.goto(target.pos[0] + side, target.pos[1], radius=500)
            continue
        run.face_point(target.pos[0], target.pos[1])
        if run.world.pickup_candidate(run.lex) is not target:       # out of reach Enter would put down what the right hand holds
            run.key(0x48, 0, 3)
            continue
        run.key(KEY_ENTER)
        run.tick(20)
    run.until(lambda: target.owner == run.lex.name, 120, f'Enter picks up {item}')
    run.until(lambda: run.lex.finished or run.lex.motion == 'STAND', 120, f'the pick-up motion for {item} ends')


def bio_repair(run):
    """PIMM diagnostics (D), BRSB: BIOREPAIR (PIMM.scr:441-505) turns 1 battery energy into 2 HP every 8 ticks while MY_BATTERY holds 10 or more.
    Lex leaves the Guard 1 fight with a fraction of his health and the first bolt in CONTROL (46 HP) kills him; nothing else on the path heals him
    before MEDICAID, which lies in the operating room."""
    with run.segment('bio-repair'):
        heal(run)


def tanks_back(run):
    """Out of cell 2 the way the tank level came: walk into the hole under TNKS_ARV (FM_TNKS: `LOADLEVEL TANKS FROMCELL`, CHAOS.scr:184-196,
    CRYTOTNK.scr:301-309), back along the catwalk north to TO_CRYO, Space (TO_CRYO_USE, CRYTOTNK.scr:206-256: the ladder up, `LOADLEVEL
    CHAOS BTM_LDR`)."""
    world, vm = run.world, run.vm
    with run.segment('tanks-back'):
        loads = len(world.level_loads)
        run.goto(-1700, -33900, radius=300)
        run.until(lambda: len(world.level_loads) > loads and not run.running('CELL2TOTANK'), 600, 'the hole drops Lex into TANKS (FM_TNKS)')
        if world.level != 'TANKS':
            raise Stuck(f'FM_TNKS loaded {world.level}')
        run.tick(60)
        for x, y in ((23000, -186300), (28500, -186300), (28500, -160000), (28500, -110000), (28500, -70000), (28500, -43000), (28800, -30500)):
            run.goto(x, y, radius=600, run=y > -186000)
        run.goto(28800, -29500, radius=250)
        if run.use() != 'TO_CRYO_USE':
            raise Stuck('Space at TO_CRYO did not run TO_CRYO_USE')
        loads = len(world.level_loads)
        run.until(lambda: len(world.level_loads) > loads, 4000, 'the ladder up loads CHAOS (BTM_LDR)')
        lex = run.lex
        run.until(lambda: lex.motion == 'MANTLE_6', 4000, 'the ladder is climbed')
        run.until(lambda: lex.motion == 'STAND', 400, 'MANTLE_6 ends')
        run.until(lambda: not run.running('TO_CRYO_USE'), 4000, 'TO_CRYO_USE ends')
        run.tick(30)
        if world.level != 'CHAOS':
            raise Stuck('Lex fell back into TANKS')


def click_elevator_button(run, button):
    """Press `button` (TOWB / KAOB / CONB / AIRB) on the ELMN elevator monitor that the cabin console opened (ELEVATOR_MONITOR,
    ELEVATOR.scr:750-895) with the pointer; the button runs the SWITCHTO<level>LEVEL process, i.e. the real ride."""
    world = run.world
    run.until(lambda: world.monitor is not None and world.monitor.name == 'ELMN', 120, 'the elevator monitor opens')
    run.click(button)


RIDES = {'CONTROL': 'SWITCHTOCONTROLLEVEL', 'TOWER': 'SWITCHTOTOWERLEVEL', 'LANDPAD': 'SWITCHTOLANDINGLEVEL', 'CHAOS': 'SWITCHTOCHAOSLEVEL'}


def cabin_ride(run, console, headings, button, level, on_arrival=None, after_tail=None):
    """In the elevator cabin: walk to the console trigger `console`, face each of `headings` until Space runs its USE block (the console
    checks COMPASS), press `button` on the ELMN monitor with the pointer, and wait for the ride (SWITCHTO<level>LEVEL: LOADLEVEL, then the
    caller's own tail opens the door, ELEVATOR.scr:53-325). `on_arrival(run)` runs in the first tick spent in the new level, `after_tail(run)`
    once the tail has ended."""
    world, vm = run.world, run.vm
    box = next(t for t in world.triggers if t['name'] == console)
    cx, cy = (box['lo'][0] + box['hi'][0]) / 2, (box['lo'][1] + box['hi'][1]) / 2
    run.goto(cx, cy, radius=300)
    used = None
    for heading in headings:
        run.fine_face(heading, tolerance=15)
        for _ in range(4):                                          # a turn on the spot can carry his hull off the box
            if console in world.usable_objects(run.lex):
                break
            run.goto(cx, cy, radius=200)
            run.fine_face(heading, tolerance=15)
        used = run.use()
        if used == f'{console}_USE':
            break
    if used != f'{console}_USE':
        raise Stuck(f'Space at {console} never ran {console}_USE (last: {used}; Lex at {[int(v) for v in run.lex.pos[:2]]})')
    run.until(lambda: world.monitor is not None and world.monitor.name == 'ELMN', 120, 'the elevator monitor opens')
    loads = len(world.level_loads)
    run.click(button)
    run.until(lambda: len(world.level_loads) > loads, 900, f'the ride loads {level}')
    if world.level != level:
        raise Stuck(f'the ride loaded {world.level}, not {level}')
    if on_arrival is not None:
        on_arrival(run)
    run.until(lambda: not run.running(RIDES[level]), 900, "the ride's tail opens the door")
    if after_tail is not None:
        after_tail(run)


def hall_to_elevator(run):
    """Down the CHAOS hall: HALMECHO stands at WAY_PT2 by DR6 until a hall camera is current, then walks south along x 17000 at about 64 units a tick
    (it reacts to Lex within 300 cm in front of it, AI_MECHO.scr:160-190). Lex runs from the cryo door to DR7_BTN with Shift+Up held (`dash`) and is in the
    vestibule, over 7000 units off its line, before it comes within reach; then DR7_BTN (Space, COMPASS -130..-30, opens the
    cabin door, CHAOSHAL.scr:59-94), through DR7 into the cabin ELH and rides to TOWER (TOWB; ELEV2_H1, COMPASS 50..130, CHAOSMON.scr:6-30).
    TOWER first: CONTROL's operating-room scene readies Marine 1 while the first lander lives (READY_MARINE1, AI_MRN1.scr:1-64), and its
    trigger TMRN1 lies across the hall that leads from the operating room to the control room (500 damage); the lander dies at the tower
    gun. That order also leaves the lander's Marine 1 off the M1TONFA, the only gun that is left once OPRSCENE has taken the blaster."""
    world, vm = run.world, run.vm
    with run.segment('hall-to-elevator'):
        mecho = world.figure('HALMECHO')
        # MANTLE_6 leaves Lex facing west at the edge of the open iris hatch (QPIT1-5 span x -12490..-6815, y -77158..-71578). Turning there drifts
        # him east into it, so he walks straight off first; the next points take him round the south side (walking straight for (6000, -76300)
        # from the west crossed it and dropped him into TANKS, where he drowned)
        for x, y in ((-13200, -74700), (-13200, -78500), (-9000, -78500), (6000, -76300)):
            run.goto(x, y, radius=400)
        run.dash((12000, -76000), (17500, -70000), (18500, -63000), (20800, -61000), stop=800)
        run.goto(21000, -61000, radius=400)
        if vm.globals.get('_halmecho_state'):
            raise Stuck(f"the sentry spotted Lex in the hall (state {vm.globals.get('_halmecho_state')})")
        if run.use() != 'DR7_BTN_USE':
            raise Stuck('Space at DR7_BTN did not run DR7_BTN_USE')
        run.until(lambda: vm.globals.get('_dr7_space') == 0 and not run.running('ELEVATOR_DOOR_OPEN'), 400, 'the cabin door opens')
        for x, y in ((24000, -57000), (28000, -56500), (31000, -55500)):
            run.goto(x, y, radius=300)
        cabin_ride(run, 'ELEV2_H1', (90,), 'TOWB', 'TOWER')


def attach(run, name):
    """A playthrough_base.Run on this run's world, for the base harness's segment functions."""
    return pb.Run.attached(name, run)


def absorb(run, r):
    """Merge what a playthrough_base.Run saw into this run: its shortcuts under their names, its problems, its checkpoints."""
    for item in r.shortcuts:
        item = dict(item)
        name = item.pop('kind')
        item.pop('reason', None)
        run.shortcut(name, **item)
    for item in r.problems:
        run.problem('major' if item['kind'] in ('stuck', 'unmodelled') else 'minor', item['kind'], f"{item['kind']}: {item['text']}")
    for point in r.checkpoints:
        run.checkpoints.append({k: v for k, v in point.items() if k not in ('player', 'items')})


def absorb_surface(run, seg):
    """Merge a playthrough_surface.Segment into this run: its staged items under 'surface-<kind>' (reason as given), its steps as checkpoints,
    the failed ones as blockers."""
    for item in seg.shortcuts:
        run.shortcuts.append({'name': f"surface-{item['kind']}", 'tick': item['tick'], 'what': item['what'], 'reason': item['reason'],
                              'segment': seg.name})
    for step in seg.steps:
        run.checkpoints.append({'name': f"{seg.name}:{step['step']}", 'tick': step['tick'], 'level': step['level'], 'ok': step['ok'],
                                'lex': step.get('lex'), 'detail': step.get('detail')})
        if not step['ok']:
            run.problem('blocker', 'stuck', f"{seg.name}: step {step['step']} failed ({step.get('detail')})")
    if not seg.ok:
        raise Stuck(f"{seg.name}: a step failed: {[s['step'] for s in seg.steps if not s['ok']]}")


def surface_leg(name, function):
    def leg(run):
        with run.segment(name):
            absorb_surface(run, function(run))
    leg.__doc__ = f'playthrough_surface.{function.__name__} on this run (surface.md).'
    return leg


def ledge_run(run):
    """The LANDPAD ledge with its three bots alive (LDGBOT1-3, LANDBOTS.scr:42-105, 254-350; the pad's four never fire on this path): Lex runs it. Shot from where they float he would
    need about 10000 units for his laser and they reach him from 24000, so a fight is lost; at a run their bolts land behind him. He must not stop in their
    reach: a stop to turn lets a volley land, and each of its bolts restarts his recoil, so the next ones land too. From where he arrives (about
    (27300, -110300), heading 9) the first point is nearly straight ahead. He keeps to the ledge's west side, x 23800, some 7000 units from the bots
    (LDGBOT_1-3 float at x 30848): their bolt leaves on FIRE's first frame, right after TURNTOENEMY, and nearer them it lands."""
    world, vm = run.world, run.vm
    for x, y in ((23800, -140000), (23800, -170000), (23800, -200000), (26500, -212000)):     # PADLDG x 23038..28294, then TO_BCH
        if world.level != 'LANDPAD':
            break
        run.goto(x, y, radius=600, run=True)
        if vm.objects['LEX'][0] <= 0:
            raise Stuck('the ledge bots killed Lex')


def beach_zip1(run):
    """From FROM_PAD to ZIP1 with the BEACH bots alive (BEACHBOT.scr): at a run, the BLOCK ready for the line. BCHBOT3 is down to another bot's bolt before Lex arrives, and the
    others reach him from 40000 to 84000 units, past his laser's reach; standing to heal only gives them more shots. The warhead's blast takes BCHBOT2 (WARHEAD.scr:24)."""
    ready_item(run, 'BLOCK')
    run.goto(-1178500, -995000, radius=500, run=True)
    run.goto(-1177873, -1002528, radius=400, run=True)
    if run.vm.objects['LEX'][0] <= 0:
        raise Stuck('the BEACH bots killed Lex')


def beach_leg(run):
    return ps.beach(run, to_zip1=lambda seg: beach_zip1(run))


def landpad_leg(run):
    return ps.landpad(run, ledge=lambda seg: ledge_run(run))


landpad, beach, digsite, tunroom = (surface_leg(n, f) for n, f in (('landpad', landpad_leg), ('beach', beach_leg), ('digsite', ps.digsite), ('tunroom', ps.tunroom)))


def platform(run):
    """PLATFORM (base.md "PLATFORM"): the city monitor by clicks, the city scene and the Elite's battery (playthrough_base.platform_city)."""
    with run.segment('platform'):
        r = attach(run, 'platform')
        pb.platform_city(r, run)
        absorb(run, r)
        # PLAYER_MIND_MELD (AI_ELITE.scr:310-322) is still in its last MIND_MELD2 when the Elite has left; its `AI ON` ends Lex's stasis, and a
        # LOADLEVEL before it ends the process (class 0x10c) and keeps Lex's AI off for good
        run.until(lambda: not run.running('PLAYER_MIND_MELD') and run.lex.ai_enabled, 900, 'the mind meld ends and Lex has his AI back')
        gun_back(run)


def gun_back(run):
    """The gift took the gun's hand (FREEHAND RTHAND, AI_ELITE.scr:169), and the way back over the zero-g room needs the gun. Both want the right hand and neither can be stowed, but Space with the
    alien battery puts it in Lex's leg as MY_BATTERY and hands him the old one (REPLACEBATTERYINLEG, ITEMS.scr:1330-1380), which stays on the floor."""
    world, lex = run.world, run.lex
    run.key(KEY_I)                                                  # REFLECT in the left hand would take Space
    run.until(lambda: world.held_item(lex, 'LTHAND') is None, 60, 'I stows the left-hand item')
    if run.use() != 'ABAT_500_USE':
        raise Stuck('Space did not run ABAT_500_USE')
    run.until(lambda: not run.running('ABAT_500_USE') and lex.ai_enabled, 400, 'the batteries are swapped')
    old = world.held_item(lex, 'RTHAND')
    run.key(0x1c)
    run.until(lambda: old.owner is None and not lex.motion.startswith('PUT_DOWN'), 90, 'the old battery is down')
    run.tick(5)
    take(run, 'TONFA')
    run.tick(30)


def mirror(run):
    """Space with REFLECT in the left hand: REFLECT_USE (ITEMS.scr:1477-1545) swaps LEX and LEXMIR. LEXMIR turns PLTDOOR's solid off, and drains MY_BATTERY by one a minute."""
    if run.use() != 'REFLECT_USE':
        raise Stuck('Space did not run REFLECT_USE')
    run.until(lambda: not run.running('REFLECT_USE') and run.lex.ai_enabled, 300, 'the mirror suit changes')


def battle_room(run):
    """TDROGG3 wakes Drogg 3 (ACTIVATE_DROGG3, AI_DROG3.scr). Armour comes from the type block, so a DROGGMIR has IMPACT_ARMOR 8 (FUN_1088_2a87) and punches hurt him. He drops REFLECT
    (DROGG3_DEATH, AI_DROG3.scr:342-355). In the mirror suit Lex walks through PLTDOOR to the city's square, then takes the suit off to save the battery."""
    world, vm = run.world, run.vm
    lex = run.lex
    with run.segment('battle-room'):
        heal(run, 100)                                              # the Elite's battery comes straight after this fight
        run.goto(8500, -125900, radius=300)
        run.until(lambda: vm.globals.get('_drogg3_activated') == 1, 200, 'TDROGG3 fires')
        run.until(lambda: lex.ai_enabled, 900, 'the alien changes form')
        run.AVOID_MARGIN = BATTLE_ROOM_AVOID_MARGIN
        run.fight(world.figures['DROGG3'], lambda: vm.globals.get('_drogg3_alive') == 1, attack=0x49, mods=worldmod.keys_mod.CTRL,     # Ctrl+KP9: ATK_F9, 23 of 24 where ATK_H4 wins 15
                  avoid=[t for t in world.triggers if t['name'] in ('THOLE1', 'THOLE2')])     # glass: the first step creaks, the second drops Lex through it (PLATFORM.scr:200-321)
        del run.AVOID_MARGIN                                        # back to the class's margin
        if vm.objects['LEX'][0] > 0 and vm.globals.get('_drogg3_alive') == 1:
            raise Stuck('the fighting routine gave up on Drogg 3')
        if run.running('FALLHOLE'):
            raise Stuck('Lex fell through the glass floor')
        if vm.objects['LEX'][0] <= 0:
            raise Stuck('Drogg 3 killed Lex')
        run.until(lambda: not run.running('DROGG3_DEATH') and lex.ai_enabled, 900, 'the death scene ends')
        if world.held_item(lex, 'LTHAND') is not None:
            run.key(0x17)                                           # I: the dig tube's KEY goes away, REFLECT is a left-hand item
            run.tick(10)
        take(run, 'REFLECT')
        mirror(run)
        for x, y in ((8440, -152000), (8440, -158000)):
            run.goto(x, y, radius=400)
        mirror(run)
        run.goto(13000, -160500, radius=250)
        run.face(-90, tolerance=12)
        for _ in range(8):
            if 'CTYMON' in world.usable_objects(lex):
                break
            run.key(0x48, 0, 4)


def platform_exit(run):
    """PLATFORM -> the zero-g room: back through PLTDOOR in the mirror suit and the battle room to TO_ZEROG (walking into it runs `LOADLEVEL TUNROOM GFROMFIN`, TUN2PLAT.scr:22-40)."""
    world = run.world
    with run.segment('platform-exit'):
        run.goto(8440, -153000, radius=500)
        ready_item(run, 'REFLECT')
        mirror(run)
        for x, y in ((8440, -141000), (8440, -128000), (8500, -118000), (8500, -114500)):
            if world.level != 'PLATFORM':
                break
            run.goto(x, y, radius=500)
        run.until(lambda: world.level == 'TUNROOM', 100, 'TO_ZEROG loads TUNROOM')
        run.until(lambda: not run.running('TO_ZEROG'), 600, 'the tail of TO_ZEROG ends')


def zero_g_back(run):
    """The zero-g room (MARINESENTERTEMPLE's speech plays, TEMPLE.scr:48-90) and out by TO_TUNRM (TUNZEROG.scr:90-105)."""
    world, vm = run.world, run.vm
    with run.segment('zero-g-back'):
        lex = run.lex
        run.until(lambda: not run.running('MARINESENTERTEMPLE'), 3000, "the marines' speech ends")
        world.key_event(0x39)
        world.key_up(0x39)                                          # ZERO_G_FIRE_FAIL in the suit (TUNZEROG.scr:125-128); Space here takes it off (REFLECT_USE _TRUE)
        run.until(lambda: lex.type == 'LEX' and not run.running('REFLECT_USE'), 200, 'the mirror suit comes off')
        ps.zero_g_flight(run, 'TO_TUNRM')
        run.until(lambda: not run.running('TO_TUNRM') and lex.ai_enabled, 1500, 'TO_TUNRM walks Lex out and gives him his AI')
        mirror(run)                                                 # back on: the temple's air needs it (TO_TMPL_USE)


RING_EFFECTS = {1: (1, 4), 2: (2,), 3: (3, 6), 4: (4,), 5: (5, 2), 6: (6,)}      # RING<n> turns these rings by 2 (TUNGRAV.scr:228-330)


def ring_move(vm, last):
    """The next pad of the shortest press plan that makes the six `_pz<n>_frame` equal (values 1-16, a press adds 2 to each ring it moves,
    TUNGRAV.scr:228-330); the same pad cannot be pressed twice in a row (its triangle `_tg<n>_frame` is lit). From the start (15, 1, 13, 15, 1, 11)
    the plan is the comment's solution, pads 3, 6, 1, 3 (TUNGRAV.scr:340-350)."""
    import itertools
    start = [vm.globals.get(f'_pz{n}_frame', 1) for n in range(1, 7)]
    best = None
    for counts in itertools.product(range(8), repeat=6):
        values = {(start[n - 1] - 1 + 2 * sum(counts[k - 1] for k in RING_EFFECTS if n in RING_EFFECTS[k])) % 16 for n in range(1, 7)}
        if len(values) == 1 and (best is None or sum(counts) < sum(best)) and sum(counts) > 0:
            best = counts
    if best is None:
        return 3
    pads = [k for k in range(1, 7) for _ in range(best[k - 1])]
    order = [k for k in pads if f'RING{k}' != last] or pads
    return f'RING{order[0]}'


def grav_ring(run):
    """TO_GRAV_USE (needs `_TubesOpen` bit 3, TUNROOM.scr:151-166) takes Lex to the gravity ring; GRV_LOAD (TUNGRAV.scr:3-95) starts the rocks and the
    puzzle (only after the city: before it the arrival is a scripted death); RING3, RING6, RING1, RING3 solve it (`_pz*_frame` all equal,
    GRAV_PUZZLE, TUNGRAV.scr:118-185) and set `_Grav_Solved`. Then TO_TUN (TUNROOM.scr:215-221) leads back."""
    world, vm = run.world, run.vm
    with run.segment('grav-ring'):
        ps.tube_monitor(run, (5450, -27400), ('TN3B', 'TN4B'), 3)    # CASE 12, #3 GRAVITY RING
        for x, y in ((5000, -31000), (5000, -24500), (8000, -22500), (8000, -20700)):       # round the pedestal in the middle (x 6300-10500, y -28800..-26000)
            run.goto(x, y, radius=400)
        run.fine_face(180, tolerance=10)
        if run.use() != 'TO_GRAV_USE':
            raise Stuck('Space at TO_GRAV did not run TO_GRAV_USE')
        run.until(lambda: world.level == 'TUNROOM' and vm.globals.get('_pz1_frame') is not None and run.lex.pos[0] > 600000, 900, 'the gravity ring loads')
        run.until(lambda: not run.running('TO_GRAV_USE') and run.lex.ai_enabled, 900, 'TO_GRAV_USE ends')
        # the arrival camera is TUB2: the first move onto the platform switches to GRV1, and GRV_LOAD (TUNGRAV.scr:3-95) resets the puzzle to its start
        # values; a pad pressed at that moment loses half of its turn. Stand on the platform off the pads first and let the camera switch happen
        floor = world.point_floor(665000, -133500, int(run.lex.pos[2]) + 2000, int(run.lex.pos[2]) + 2000)
        run.shortcut('set-pos', to=[665000, -133500], why='onto the ring platform beside the pads (the walk along the platform is not the point)')
        world.set_pos(run.lex, [665000.0, -133500.0, floor + world.foot(run.lex)], raw=True)
        run.tick(90)
        last = None
        for _ in range(12):
            if vm.globals.get('_grav_solved') == 1:
                break
            name = ring_move(vm, last)
            box = next(t for t in world.triggers if t['name'] == name)
            x, y = (box['lo'][0] + box['hi'][0]) / 2, (box['lo'][1] + box['hi'][1]) / 2
            run.shortcut('ring-pads', pad=name)
            floor = world.point_floor(int(x), int(y), int(run.lex.pos[2]) + 2000, int(run.lex.pos[2]) + 2000)
            world.set_pos(run.lex, [x, y, floor + world.foot(run.lex)], raw=True)
            run.tick(40)
            run.until(lambda: not run.running(name), 300, f'{name} ends')
            run.tick(40)
            last = name
            if vm.objects['LEX'][0] <= 0:
                raise Stuck(f'a rock killed Lex on {name}')
        run.until(lambda: vm.globals.get('_grav_solved') == 1 and not run.running('ACID_VIEW'), 1200, 'the puzzle is solved and the acid lake opens')


def ready_item(run, name):
    """I (a first press stows the left hand), the inventory's IPDB until `name` is selected, RDYB (PIMM_INVENTORY, PIMM.scr:506-575)."""
    world, lex = run.world, run.lex
    run.key(0x17)
    run.tick(10)
    if not run.running('PIMM_INVENTORY'):
        run.key(0x17)
    run.until(lambda: world.monitor is not None, 200, 'the inventory opens')
    run.tick(5)
    entries = world.monitor.elements['INMT']
    while entries.items[entries.sel] != name:
        run.click('IPDB')
    run.click('RDYB')
    run.until(lambda: world.monitor is None and lex.ai_enabled and not run.running('PIMM_INVENTORY'), 200, 'the inventory closes')


def walk_into_reach(run, trigger, heading, tolerance=12):
    """Face `heading` and walk until Space would try `trigger`: its box has to touch his hull."""
    run.face(heading, tolerance=tolerance)
    for _ in range(10):
        if trigger in run.world.usable_objects(run.lex):
            return
        run.key(0x48, 0, 4)


def steer_u_turn_left(run, low, high, limit=70):
    """Walk + Left held until the heading is in low..high."""
    run.world.key_down(0x48, 0)
    run.world.key_down(0x4b, 0)
    for _ in range(limit):
        if low <= (run.lex.heading + 180) % 360 - 180 <= high:
            break
        run.tick(1)
    run.world.key_up(0x4b, 0)
    run.world.key_up(0x48, 0)
    run.tick(1)


def temple_monitor(run):
    """Back down the tube (TO_TUN), the tube monitor's temple combination (TN3B TN4B TN8B, CASE 140), then TMPL_MON (COMPASS -120..-50, TUNMON.scr:421-447). OPNB raises the temple's sphere;
    Marine 1 comes to peer into the hole (TEMPLEMARINESPEERIN) and CLSB crushes him (CLOSETEMPLE, TEMPLE.scr:660-670)."""
    world, vm = run.world, run.vm
    with run.segment('temple-monitor'):
        box = next(t for t in world.triggers if t['name'] == 'TO_TUN')
        x, y = (box['lo'][0] + box['hi'][0]) / 2, (box['lo'][1] + box['hi'][1]) / 2
        run.shortcut('set-pos', to=[int(x), int(y)], why='TO_TUN, under the ring platform (stepping off its edge)')
        world.set_pos(run.lex, [x, y, box['hi'][2] - 4000.0], raw=True)
        run.until(lambda: world.level == 'TUNROOM' and run.lex.pos[0] < 100000 and not run.running('TO_TUN'), 600, 'TO_TUN returns Lex to the tube room')
        ps.tube_monitor(run, (5450, -27400), ('TN3B', 'TN4B', 'TN8B'), 1)
        for x, y in ((5000, -31000), (11000, -32000), (13500, -32400)):
            run.goto(x, y, radius=350)
        walk_into_reach(run, 'TMPL_MON', -85)
        if run.use() != 'TMPL_MON_USE':
            raise Stuck('Space at the temple monitor did not run TMPL_MON_USE')
        run.until(lambda: world.monitor is not None, 100, 'the temple monitor opens')
        run.tick(30)
        run.click('OPNB')
        run.until(lambda: vm.globals.get('_marine_peering_in') == 1, 1200, 'Marine 1 peers into the hole')
        run.click('CLSB')
        run.until(lambda: vm.globals.get('_heard_templec_speech') == 1 and world.monitor is not None, 1500, "Marine 2's speech ends")
        run.until(lambda: vm.globals.get('_wak_frame') == 1, 400, 'the sphere is down')
        run.tick(30)


def grenade(run):
    """OPNB again: Marine 2 throws a grenade down the tube (TEMPLEMARINESPEERIN), which lands in the tube room with 45 seconds on it (GRENADECOUNTDOWN). It needs the right hand, so REFLECT goes
    away (the suit stays on) and the gun goes on the floor. Thrown from Space at TO_TMPL, along the tube's axis, it reaches the temple (TO_TMPL_GRENADE_USE, GRENADE_FIRE; TMP_FACE within
    125 cm when it stops, GRENADEENTERTUBE) and kills him. Then the gun again, REFLECT in hand, and Space at TO_TMPL: in the suit Lex can breathe in the temple (TO_TMPL_USE,
    TUNROOM.scr:237-311). The way out is at its north end, TO_BCH."""
    world, vm = run.world, run.vm
    lex = run.lex
    with run.segment('temple'):
        run.click('OPNB')
        grenade = lambda: world.items.get('GRENADE')
        run.until(lambda: grenade() is not None and grenade().owner is None and world.monitor is None and lex.ai_enabled and not run.running('GRENADEENTERTUBE'), 1500, 'the grenade lands')
        run.key(0x17)
        run.tick(15)
        run.key(0x1c)
        run.until(lambda: not lex.motion.startswith('PUT_DOWN'), 90, 'the gun is down')
        run.tick(5)
        gun = world.items['TONFA']
        run.goto(13900, -25000, radius=350)
        run.face_point(float(grenade().pos[0]), float(grenade().pos[1]), tolerance=10)
        run.key(0x1c)
        run.until(lambda: grenade().owner == lex.name, 60, 'Lex takes the grenade')
        run.tick(30)
        run.goto(11500, -25700, radius=300)
        steer_u_turn_left(run, -100, -80)                           # the tube's axis is y -27400, and a turn on the spot would carry him off it
        for _ in range(10):
            if 'TO_TMPL' in world.usable_objects(lex):
                break
            run.key(0x48, 0, 5)
        if run.use() != 'TO_TMPL_GRENADE_USE':
            raise Stuck('Space at TO_TMPL with the grenade did not run TO_TMPL_GRENADE_USE')
        run.until(lambda: vm.objects['TMP_MAR_2'][0] <= 0, 600, 'the grenade kills Marine 2')
        run.until(lambda: not run.running('GRENADELEAVETUBEROOM') and lex.ai_enabled, 900, 'the camera comes back')
        run.tick(60)
        run.goto(float(gun.pos[0]), float(gun.pos[1]) + 500, radius=300)
        run.face_point(float(gun.pos[0]), float(gun.pos[1]), tolerance=12)
        run.key(0x1c)
        run.until(lambda: gun.owner == lex.name, 60, 'Lex takes the gun')
        run.tick(30)
        ready_item(run, 'REFLECT')
        run.goto(13000, -27400, radius=400)
        walk_into_reach(run, 'TO_TMPL', -90, tolerance=20)
        if run.use() != 'TO_TMPL_USE':
            raise Stuck('Space at TO_TMPL did not run TO_TMPL_USE')
        run.until(lambda: not run.running('TO_TMPL_USE'), 1200, 'the tube takes Lex to the temple')
        for x, y in ((-49992, -130000), (-52000, -118000), (-52300, -108000), (-52300, -104500)):
            if world.level != 'TUNROOM':
                break
            run.goto(x, y, radius=500)
        run.until(lambda: world.level == 'BEACH', 600, 'TO_BCH loads BEACH')
        run.tick(60)


def mantle(run, x, y, heading, top, budget=200):
    """Stand at (x, y) on this block, face `heading` (an axis: FUN_10a0_0ae5 wants the hull inside the next block) and hold Up until his feet are at `top`: MANTLE_3 / 6 / 9."""
    lex = run.lex
    run.goto(x, y, radius=250)
    run.fine_face(heading, tolerance=5)
    run.world.key_down(0x48, 0)
    for _ in range(budget):
        if lex.pos[2] - run.world.foot(lex) >= top - 64 and not lex.motion.startswith('MANTLE'):
            break
        run.tick(1)
    else:
        run.world.key_up(0x48, 0)
        raise Stuck(f'the mantle to z {top} from ({x}, {y}) did not happen')
    run.world.key_up(0x48, 0)
    run.tick(2)


def zip_ride(run, a):
    """Space with BLOCK in the left hand: <a>_BLOCK_USE (BEACHZIP.scr), which runs either way along a line."""
    if run.use() != f'{a}_BLOCK_USE':
        raise Stuck(f'Space at {a} did not ride the zip line')
    run.until(lambda: run.vm.globals.get('_ziptripping') == 0 and run.lex.ai_enabled and not run.running(f'{a}_BLOCK_USE'), 900, f'{a} ends')


def beach_climb(run):
    """FROM_TPL to TO_PAD (`LOADLEVEL LANDPAD FROM_BCH`, BEACH.scr:208-218): the blocks up from the temple tunnel, ZIP8 and ZIP7 back the other way, the blocks to CT6, then the ledge CT1 north and
    CT2 east. The suit stays on: lasers bounce off it, so MARINE2 and MARINE3A on the ledge do not stop Lex (they kill a plain Lex)."""
    world = run.world
    with run.segment('beach-climb'):
        heal(run)
        ready_item(run, 'BLOCK')
        mantle(run, -1197232, -1138900, 180, -17982)                # BLOCK64
        mantle(run, -1197232, -1134000, 180, -16141)                # 60
        mantle(run, -1198000, -1129800, 180, -14298)                # 54
        mantle(run, -1197800, -1125800, -90, -12477)                # 52
        for x, y in ((-1194000, -1122000), (-1190500, -1122000), (-1189500, -1116000), (-1189500, -1112000), (-1189500, -1107000)):    # down over 51 and 48 to 47
            run.goto(x, y, radius=350)
        zip_ride(run, 'ZIP8_B')
        mantle(run, -1180800, -1098000, 180, -17982)                # 43
        mantle(run, -1180900, -1094900, 90, -16175)                 # 42
        run.goto(-1185500, -1094800, radius=300)
        zip_ride(run, 'ZIP7_A')
        mantle(run, -1194500, -1093000, 90, -14318)                 # 7
        mantle(run, -1198500, -1092500, 90, -10615)                 # 6
        for x, y in ((-1204500, -1092500), (-1207000, -1092500), (-1212000, -1090000), (-1212000, -1060000), (-1212000, -1030000), (-1212000, -1000000), (-1212000, -994000),
                     (-1195000, -994000), (-1182000, -994000), (-1182000, -988000), (-1181800, -985000)):
            if world.level != 'BEACH':
                break
            run.goto(x, y, radius=500, run=True)
            if run.vm.objects['LEX'][0] <= 0:
                raise Stuck('Lex died on the BEACH ledge')
        if world.level == 'BEACH':
            run.goto(-1181800, -984700, radius=200)
        run.until(lambda: world.level == 'LANDPAD', 600, 'TO_PAD loads LANDPAD')
        run.tick(60)


MARINE4_HEAL_BELOW = 60      # as MARINE5_HEAL_BELOW: on the default stream 75 here left the battery under 375 at the bike and a trip back for a new one


def to_landpad_again(run):
    """LANDPAD from FROM_BCH to the elevator cabin and CONB."""
    world, vm = run.world, run.vm
    with run.segment('landpad-to-elevator'):
        lex = run.lex
        bolts = lambda: [i for i in world.items.values() if i.missile and i.pos is not None and i.type == 'BOLTORNG']
        for _ in range(30):                                         # the dropship leads a moving Lex by 20 to 45 cm (DROPSHIPFIREONLEX, LEDGE.scr:118-160): keep running, and stop as its bolts fly
            run.dash((25700, -120000), stop=800, until=lambda: bool(bolts()) or lex.pos[1] > -121000 or not lex.ai_enabled, limit=400)
            if lex.pos[1] > -121000 or not lex.ai_enabled:
                break
            run.until(lambda: not bolts(), 200, 'the bolts land')
        if vm.objects['LEX'][0] <= 0:
            raise Stuck('the ledge killed Lex')
        run.until(lambda: vm.globals.get('_ship_has_left') == 1 and lex.ai_enabled and not run.running('SHIP_GO'), 3000, 'SHIP_GO: the dropship leaves')
        run.goto(25000, -110800, radius=350)
        walk_into_reach(run, 'JET_BUT2', 180)                       # COMPASS beyond +-130, LANDPAD.scr:487
        if run.use() != 'JET_BUT2_USE':
            raise Stuck(f'Space at JET_BUT2 did not run JET_BUT2_USE (Lex at {[int(v) for v in lex.pos[:2]]})')
        run.until(lambda: vm.globals.get('_jetson2_space', vm.globals.get('_jetson1_space')) == 0, 300, 'the jetson tube opens')
        run.goto(27200, -109500, radius=250)
        run.face_point(27250, -105700, tolerance=8)
        world.key_down(0x48, 0)                                     # into the tube: PAD_DOWN takes the keys away, and a longer walk would go on from the top
        for _ in range(300):
            if run.running('PAD_DOWN'):
                break
            run.tick(1)
        world.key_up(0x48, 0)
        run.until(lambda: lex.pos[2] > -20000 and lex.ai_enabled and not run.running('PAD_DOWN'), 900, 'the tube takes Lex up')
        run.goto(27000, -96000, radius=400)
        marine = world.figures['MARINE4']                           # TMRN4A wakes him as the tube arrives: 100 HP, melee
        run.HEAL_BELOW_RICH = MARINE4_HEAL_BELOW
        run.fight(marine, lambda: vm.objects['MARINE4'][0] > 0, attack=0x4b)     # KP4: ATK_H4. Of 16 attacks three win (Alt+KP4 72 of 100 HP left, Ctrl+KP4 89, Ctrl+KP9 35); start times do not change it
        del run.HEAL_BELOW_RICH
        if vm.objects['LEX'][0] <= 0:
            raise Stuck('Marine 4 killed Lex')
        run.tick(30)
        for x, y in ((21000, -70000), (19000, -67700)):
            run.goto(x, y, radius=400)
        walk_into_reach(run, 'AIRLCK', 90)
        if run.use() != 'AIRLCK_USE':
            raise Stuck(f'Space at AIRLCK did not run AIRLCK_USE (Lex at {[int(v) for v in lex.pos[:2]]})')
        run.until(lambda: world.monitor is not None or vm.globals.get('_paddr_space') == 0, 300, 'the airlock keypad opens')
        if world.monitor is not None:
            run.tick(60)                                            # AIRLOCK_MONITOR's WAIT 45, then CLRB_BUTTON draws the random start
            for name in ps.solve_city_keypad(vm.globals['_airlock_flag'], vm.globals['_airlock_prev']):
                run.click(name)
        run.until(lambda: vm.globals.get('_paddr_space') == 0, 900, 'the pad door opens')
        for x, y in ((17000, -71200), (14500, -71200), (10000, -71200), (6900, -71200)):                            # DRB_STRT shuts the pad door behind him; DECONTAM
            run.goto(x, y, radius=400)
        run.until(lambda: vm.globals.get('_dr18_space') == 0, 1800, 'the decontamination ends and DRA opens')
        for x, y in ((1700, -71200), (-2500, -71200), (-6000, -72500), (-12000, -68500), (-20000, -68500), (-30500, -68300)):
            run.goto(x, y, radius=500)
        if run.use() != 'AIR_DOOR_USE':
            walk_into_reach(run, 'AIR_DOOR', 90)
            if run.use() != 'AIR_DOOR_USE':
                raise Stuck(f'Space at the cabin door did not run AIR_DOOR_USE (Lex at {[int(v) for v in lex.pos[:2]]})')
        run.until(lambda: vm.globals.get('_dr9_space') == 0 and not run.running('AIR_DOOR_USE'), 400, 'the cabin door opens')
        run.goto(-36000, -70000, radius=600)
        cabin_ride(run, 'ELV_LND1', (90,), 'CONB', 'CONTROL')


MARINE5_HEAL_BELOW = 60      # the earlier fights repair from 75 (scenarios.HEAL_BELOW_RICH), but the battery has only a little over 375 to spare from here on (the bike's need)


def marine5(run):
    """MARINE5 waits in the hall with a BLASTER (READY_MARINE5, AI_MRN5.scr:1-30; HLC_LOAD activates him). A bolt takes about 46 of Lex's HP and a gun can't be fired in the mirror suit (LEX_ATK_SHOOT,
    AI_LEX.scr:240-247), but the suit stops the bolts: Lex keeps it on, walks up and hits him. The repairs come out of the Elite's battery in his leg, which needs
    375 left for the bike to run the ending (BIKE_USE, CONMACH.scr:95). Without repairs in the fight MARINE5 kills Lex on 10 of 24; after it nothing fights him, so no repair."""
    world, vm = run.world, run.vm
    for x, y in FROM_CABIN:
        run.goto(x, y, radius=500)
    run.HEAL_BELOW_RICH = MARINE5_HEAL_BELOW
    run.fight(world.figures['MARINE5'], lambda: vm.globals.get('_marine5_alive') == 1)
    del run.HEAL_BELOW_RICH
    if vm.objects['LEX'][0] <= 0:
        raise Stuck('MARINE5 killed Lex')
    if vm.globals.get('_marine5_alive') == 1:
        raise Stuck(f"the fighting routine gave up on MARINE5 ({vm.objects['MARINE5'][0]} HP)")
    run.until(lambda: not run.running('MARINE5_DEATH') and run.lex.ai_enabled, 1500, "MARINE5's death ends")
    if run.lex.combat:
        run.key(0x2e)
        run.tick(5)


TOWER_AIM, TOWER_SHOTS = 3.2, 24      # degrees a laser leaves left of the facing; the most shots tried at one bot
GUARD1_HEAL_BELOW = 50  # BIOREPAIR from this HP in the Guard 1 fight (guard1): the battery is full there and bio-repair spends it right after anyway; at 35 Lex died
                        # with the battery still at 99 in 2 of 12 reseeded draws from seed 17's start (seed 17's own among them), at 50 none of 12
BATTLE_ROOM_AVOID_MARGIN = 1800  # battle_room: how far Lex keeps from the glass (THOLE1 / THOLE2) while fighting Drogg 3; at the class's 1200 an ATK_M8 lunge carried him onto
                                 # it after GRDHALL's control restart (save_resume_check --control); from the full run's fight 22 of 24 reseeded draws win at 1200 and at 1800
GRDHANG_PUNCH = 3     # ticks between blows at GRDHANG (garage_block): 1 and 3 each lose 3 of 27 streams up to this fight since the item events moved a frame earlier, 2 loses 5
BIKE_NEEDS = 375     # BIKE_USE runs the ending only with a battery at 375 or more (CONMACH.scr:154)


def short_battery(run):
    """The Elite's battery in Lex's leg is under BIKE_NEEDS: the bike's swap as bike_battery does it, but the battery that goes in is the weak one, so BIKE_USE writes BIKEWEAK
    and sets `_need_new_battery` (CONMACH.scr:173-187), which makes the next PLATFORM load create a full one (PLT_LOAD, PLATFORM.scr:72-81). Then the TONFA again, which the
    right hand gave up for the batteries."""
    world, vm, lex = run.world, run.vm, run.lex
    bike = pb.BIKE
    with run.segment('short-battery'):
        run.goto(bike[0], bike[1] - 3500, radius=500)
        run.goto(*bike, radius=500)
        if run.use() != 'BIKE_USE':
            raise Stuck('Space at the bike did not run BIKE_USE')
        run.until(lambda: vm.globals.get('_battery_in_bike') == 0 and not run.running('BIKE_USE') and lex.ai_enabled, 600, 'BIKE_USE takes the battery out')
        run.goto(bike[0], bike[1] + 2500, radius=500)
        use = run.use()                 # the bike's battery is the one Lex left there (CONTROL keeps it): BAT_100_USE / BAT_150_USE / ABAT_500_USE all swap (ITEMS.scr:1313-1329)
        if use not in ('BAT_100_USE', 'BAT_150_USE', 'ABAT_500_USE'):
            raise Stuck(f'Space did not swap the batteries ({use})')
        run.until(lambda: not run.running(use) and lex.ai_enabled, 400, 'the batteries are swapped')
        run.goto(*bike, radius=500)
        if run.use() != 'BIKE_USE':
            raise Stuck('Space at the bike did not run BIKE_USE')
        run.until(lambda: vm.globals.get('_need_new_battery') == 1 and not run.running('BIKE_USE') and lex.ai_enabled, 600, 'BIKE_USE finds the battery too weak')
        take(run, 'TONFA')


def battery_trip(run):
    """From the garage back to PLATFORM for the battery PLT_LOAD creates, and back to CONTROL's cabin. CONTROL by the cabin to LANDPAD; the airlock's keypad again (the city rule,
    `ps.solve_city_keypad`), in the mirror suit, since DRA_STRT chokes a plain Lex (LANDPAD.scr:230-239); the jetson tube down and the ledge to TO_BCH; on BEACH the ledge back to
    the blocks, and a set_pos down them to the temple tunnel; TO_TPL; the temple's hole TMPL2TUN back to the tube room (TEMPLE.scr:16-22); TO_0G with REFLECT in the left hand
    (only then does Space take the suit off in the zero-g room, TUNZEROG.scr:167-170) and the flight to TO_FINAL; on PLATFORM through PLTDOOR to the battery at COORDS 34 -614 -6.
    It goes into the leg (ABAT_500_USE), the spent one back on the floor. Then back: PLTDOOR, the suit off before TO_ZEROG (taken off in there, Lex drifts back into TO_FINAL),
    the flight to TO_TUNRM, the tube to the temple, TO_BCH, and beach-climb and landpad-to-elevator as on the first way back."""
    world, vm, lex = run.world, run.vm, run.lex
    with run.segment('trip-to-landpad'):
        garage_up(run)
        for x, y in ((-25000, -71000), (-30500, -68300)):
            run.goto(x, y, radius=600, run=True)
        if run.use() != 'CTRELVDR_USE':
            raise Stuck('Space at the cabin door did not run CTRELVDR_USE')
        run.until(lambda: vm.globals.get('_dr9_space') == 0, 400, 'the cabin door opens')
        run.goto(-36000, -70000, radius=600)
        cabin_ride(run, 'ELV_C21', (90,), 'AIRB', 'LANDPAD')
    with run.segment('trip-landpad'):
        for x, y in ((-30500, -71000), (-20000, -68500), (-12000, -68500)):
            run.goto(x, y, radius=300)
        ready_item(run, 'REFLECT')
        mirror(run)
        run.key(KEY_I)
        run.until(lambda: world.held_item(lex, 'LTHAND') is None, 60, 'I stows REFLECT')
        for x, y in ((-6000, -72500), (-6000, -74300), (-3000, -74300)):
            run.goto(x, y, radius=300)
        run.face(-80, tolerance=8)
        if run.use() != 'DRA_BTN_USE':
            raise Stuck('Space at DRA_BTN did not run DRA_BTN_USE')
        run.until(lambda: world.monitor is not None, 120, 'the airlock keypad opens')
        run.tick(60)                                                # AIRLOCK_MONITOR's WAIT 45, then CLRB_BUTTON draws the random start
        for name in ps.solve_city_keypad(vm.globals['_airlock_flag'], vm.globals['_airlock_prev']):
            run.click(name)
        run.until(lambda: vm.globals.get('_dr18_space') == 0, 600, 'DRA opens')
        run.until(lambda: world.monitor is None, 300, 'the keypad closes')
        for x, y in ((-2500, -71200), (1700, -71200), (6900, -71200)):
            run.goto(x, y, radius=300)
        run.until(lambda: vm.globals.get('_paddr_space') == 0 and not run.running('AIRLOCK_DRB_OPEN'), 9000, 'the decontamination ends and DRB opens')
        run.tick(30)
        for x, y in ((13500, -71200), (17000, -71200), (27000, -96000), (29000, -101400)):
            run.goto(x, y, radius=300)
        run.face(0, tolerance=8)                                    # JET_BUT1_USE wants COMPASS -45..45 (LANDPAD.scr:472-485)
        if run.use() != 'JET_BUT1_USE':
            raise Stuck('Space at JET_BUT1 did not run JET_BUT1_USE')
        run.until(lambda: vm.globals.get('_jetson1_space') == 0 and not run.running('JETSON_OPEN'), 300, 'the jetson tube opens')
        run.goto(27200, -100600, radius=200)
        run.face_point(27200, -104448, tolerance=8)
        world.key_down(0x48, 0)                                     # into the tube: PAD_UP takes the keys away
        for _ in range(300):
            if run.running('PAD_UP'):
                break
            run.tick(1)
        world.key_up(0x48, 0)
        run.until(lambda: lex.pos[2] < -20000 and lex.ai_enabled and not run.running('PAD_UP'), 900, 'PAD_UP takes Lex down to the ledge')
        ledge_run(run)                                              # the ledge bots shoot here too: the west side at a run, as on the first way down
        run.until(lambda: world.level == 'BEACH', 300, 'TO_BCH loads BEACH')
        run.tick(60)
    with run.segment('trip-beach'):
        for x, y in ((-1182000, -990000), (-1182000, -994000), (-1195000, -994000), (-1212000, -994000), (-1212000, -1000000), (-1212000, -1030000),
                     (-1212000, -1060000), (-1212000, -1090000), (-1207000, -1092500), (-1204500, -1092500)):    # the ledge back; TO_PAD lies by the arrival
            run.goto(x, y, radius=500, run=True)
        x, y = -1200267, -1140500
        z = world.point_floor(x, y, 0, 0)
        run.shortcut('set-pos', to=[x, y], why='down the BEACH blocks to the temple tunnel (beach-climb the other way): on the narrow blocks Lex teeters and turns off them into the sea')
        world.set_pos(lex, [float(x), float(y), z + world.foot(lex)], raw=True)
        lex.heading = 0.0
        run.tick(10)
        run.goto(-1200267, -1143800, radius=300)
        run.until(lambda: world.level == 'TUNROOM', 300, 'TO_TPL loads TUNROOM')
        run.tick(60)
    with run.segment('trip-temple'):
        for x, y in ((-52300, -112000), (-52000, -118000), (-49992, -130000), (-52441, -135018)):     # into TMPL2TUN, the hole under the temple
            run.goto(x, y, radius=400)
            if run.running('TMPL2TUN'):
                break
        run.until(lambda: run.running('TMPL2TUN') or lex.pos[2] < -30000, 300, 'Lex falls into the hole')
        run.until(lambda: not run.running('TMPL2TUN') and lex.ai_enabled, 1500, 'TMPL2TUN takes Lex back to the tube room')
        ready_item(run, 'REFLECT')
        for x, y in ((11000, -27400), (8000, -31000), (7858, -33800)):
            run.goto(x, y, radius=300)
        walk_into_reach(run, 'TO_0G', 0)
        if run.use() != 'TO_0G_USE':
            raise Stuck('Space at TO_0G did not run TO_0G_USE')
        run.until(lambda: not run.running('TO_0G_USE') and not lex.gravity, 1500, 'TO_0G_USE: the zero-g room')
        world.key_event(0x39)
        world.key_up(0x39)
        run.until(lambda: lex.type == 'LEX' and not run.running('REFLECT_USE'), 200, 'the mirror suit comes off')
        ps.zero_g_flight(run, 'TO_FINAL')
        run.until(lambda: world.level == 'PLATFORM', 600, 'TO_FINAL loads PLATFORM')
        run.until(lambda: not run.running('TO_FINAL') and lex.ai_enabled, 900, 'TO_FINAL ends')
    with run.segment('trip-platform'):
        mirror(run)                                                 # PLTDOOR is solid to a plain Lex
        for x, y in ((8500, -126000), (8500, -140000), (8440, -152000), (8440, -156000)):
            run.goto(x, y, radius=400)
        new = next((i for i in reversed(list(world.items.values())) if i.type == 'ALBAT' and i.key != 'MY_BATTERY' and i.owner is None), None)    # the newest: PLATFORM keeps its older ones
        if new is None:
            raise Stuck('PLT_LOAD made no battery')
        take(run, new.key)                                          # Enter puts the TONFA and REFLECT down for it
        if world.held_item(lex, 'LTHAND') is not None:
            run.key(KEY_I)
            run.until(lambda: world.held_item(lex, 'LTHAND') is None, 60, 'I stows the left hand')
        if run.use() != 'ABAT_500_USE':
            raise Stuck('Space did not run ABAT_500_USE')
        run.until(lambda: not run.running('ABAT_500_USE') and lex.ai_enabled, 400, 'the new battery goes into the leg')
        run.key(KEY_ENTER)                                          # the spent one back on the floor
        run.tick(30)
        take(run, 'TONFA')
        take(run, 'REFLECT')
        run.until(lambda: vm.globals.get('_tonfa_used', 0) == 0, 3000, 'TONFA_TIMER cools the gun (ITEMS.scr:1215-1228)')
    with run.segment('trip-back'):
        run.goto(8440, -153000, radius=500)
        ready_item(run, 'REFLECT')
        mirror(run)
        for x, y in ((8440, -141000), (8440, -128000), (8500, -121000)):
            run.goto(x, y, radius=500)
        mirror(run)                                                 # off before the zero-g room
        for x, y in ((8500, -118000), (8500, -114500)):
            if world.level != 'PLATFORM':
                break
            run.goto(x, y, radius=500)
        run.until(lambda: world.level == 'TUNROOM', 100, 'TO_ZEROG loads TUNROOM')
        run.until(lambda: not run.running('TO_ZEROG'), 600, 'the tail of TO_ZEROG ends')
        ps.zero_g_flight(run, 'TO_TUNRM')
        run.until(lambda: not run.running('TO_TUNRM') and lex.ai_enabled, 1500, 'TO_TUNRM walks Lex out')
        mirror(run)                                                 # the temple's air
        run.goto(13000, -27400, radius=400)
        walk_into_reach(run, 'TO_TMPL', -90, tolerance=20)
        if run.use() != 'TO_TMPL_USE':
            raise Stuck('Space at TO_TMPL did not run TO_TMPL_USE')
        run.until(lambda: not run.running('TO_TMPL_USE') and lex.ai_enabled, 1200, 'the tube takes Lex to the temple')
        for x, y in ((-49992, -130000), (-52000, -118000), (-52300, -108000), (-52300, -104500)):
            if world.level != 'TUNROOM':
                break
            run.goto(x, y, radius=500)
        run.until(lambda: world.level == 'BEACH', 600, 'TO_BCH loads BEACH')
        run.tick(60)
    beach_climb(run)
    to_landpad_again(run)


def bike(run):
    """CONTROL, second visit (base.md "CONTROL, second visit, and the ending"): the hall to CNT_BTN3, the hangar monitor and the lift down, then the
    bike with both batteries, OUTAHERE_USE, ENDGAME, the end flic, ROLLCREDITS to CREDITSSTATE 2, the 5 s wait: LEAVEGAME and `EXIT` (playthrough_base.ending_bike)."""
    world, vm = run.world, run.vm
    with run.segment('control-second'):
        heal(run, 100)
        marine5(run)
        hall_east(run, ((run.lex.pos[0], -70800),))
        for x, y in ((34500, -71000),):
            run.goto(x, y, radius=500)
        hangar_monitor(run)
        run.until(lambda: vm.globals.get('_seen_mach_shop') == 1 and run.lex.pos[2] < -100000, 9000, 'the garage lift is down')
        for x, y in ((43000, -52500), (45000, -49500)):
            run.goto(x, y, radius=500)
    if world.held_item(run.lex, 'LTHAND') is not None:           # the dig-tube KEY is still in his left hand; BIKE_USE would put it on the floor beside the batteries
        run.key(KEY_I)
        run.until(lambda: world.held_item(run.lex, 'LTHAND') is None, 60, 'I stows the left-hand item')
    if vm.objects['MY_BATTERY'][0] < BIKE_NEEDS and not vm.globals.get('_need_new_battery'):
        short_battery(run)
        battery_trip(run)
        return bike(run)
    with run.segment('ending'):
        r = attach(run, 'ending')
        pb.ending_bike(r)
        absorb(run, r)


def roland(run):
    """Roland cowers and never hits back (ROLAND_AI, AI_ROLAN.scr:142-286). A first hit moves `_SRE_Count` to 2 (ROLAND_STIMULUS, :88-96); in his CORNER with Lex within 450
    he then says he will activate the gun; under 50 HP, with Lex off the gun, he restarts it (RESTARTGUN, :279-365), telling Lex to move back while he stands in ZONE."""
    world, vm = run.world, run.vm
    lex, man = run.lex, world.figures['ROLAND']
    run.fight(man, lambda: vm.objects['ROLAND'][0] >= 50 and not vm.globals.get('_gunactive'))
    if vm.objects['ROLAND'][0] <= 0:
        raise Stuck('Lex killed Roland, who has to restart the gun')
    if lex.combat:
        run.key(0x2e)
        run.tick(5)
    zone = next(t for t in world.triggers if t['name'] == 'ZONE')
    for _ in range(3000):
        if vm.globals.get('_gunactive') == 1:
            break
        hlo, hhi, _ = world.query_hull(lex)
        if lex.ai_enabled and all(hhi[i] >= zone['lo'][i] and hlo[i] <= zone['hi'][i] for i in range(2)):     # AMINTRIGGER: his hull touches ZONE
            away = 2 * lex.pos[:2] - man.pos[:2]
            # a few steps at a time: a full goto went on turning for ~350 ticks after the restart, and the first lander was nearly by
            run.goto(float(away[0]), float(away[1]), radius=300, steps=3)
        elif lex.ai_enabled and vm.globals.get('_sre_count') == 2 and math.hypot(*(man.pos[:2] - lex.pos[:2])) > 6000:
            # no promise yet: it needs Lex within 450 cm while Roland is in CORNER (CASE 3), and near him he backs away into it (CASE 2)
            run.goto(float(man.pos[0]), float(man.pos[1]), radius=5000, steps=3)
        run.tick(1)
    if vm.globals.get('_gunactive') != 1:
        raise Stuck(f"Roland did not restart the gun ({vm.objects['ROLAND'][0]} HP)")
    run.until(lambda: lex.ai_enabled, 900, 'RESTARTGUN gives Lex back')


def _hold(run, key, ticks):
    run.world.key_down(key, 0)
    run.tick(ticks)
    run.world.key_up(key, 0)
    run.tick(1)


def _settle(run, limit=80):
    for _ in range(limit):
        if run.lex.motion == 'STAND':
            return
        run.tick(1)


def _aim(run, point, tolerance=0.8):
    """Turn taps (Left: 1.41 degrees at 4 ticks, Right: 4.22 at 3, larger at 8 and 6; NOTES "AIRMECHO by keys") until a shot would go to `point`; a laser leaves TOWER_AIM to the left of Lex's facing."""
    for _ in range(40):
        _settle(run)
        err = run.world.rel_angle(run.lex, point) - TOWER_AIM
        if abs(err) <= tolerance:
            return
        if err > 0:
            _hold(run, 0x4b, 8 if err > 8 else 4)
        else:
            _hold(run, 0x4d, 6 if err < -8 else 3)


def _shoot_down(run, name, recover=None, spot=None, blocked=None):
    """KP5 until the bot's two hits (28 HP, a laser takes 15) are done, keeping the aim; `recover()` puts Lex back when he has drifted, and every few shots he walks back to `spot`, in case he stands just off the line. Two shots that took nothing off the bot run `blocked()` (a spot can have a pillar in the line; NOTES "A save point on the tower deck")."""
    vm, bot = run.vm, run.world.figure(name)
    shots = misses = 0
    while vm.objects[name][0] > 0 and vm.objects['LEX'][0] > 0 and shots < TOWER_SHOTS:
        _settle(run)
        if recover is not None and recover():
            continue
        if abs(run.world.rel_angle(run.lex, bot.pos) - TOWER_AIM) > 2.5:
            _aim(run, bot.pos)
            continue
        before = vm.objects[name][0]
        _hold(run, 0x4c, 2)
        shots += 1
        _settle(run)
        run.tick(6)
        misses = 0 if vm.objects[name][0] < before else misses + 1
        if blocked is not None and misses == 2:
            misses = 0
            blocked()
        if spot is not None and shots % 4 == 0 and vm.objects[name][0] > 0:
            run.goto(spot[0], spot[1], radius=150)
    if vm.objects[name][0] > 0:
        raise Stuck(f'{name} is still up after {shots} shots (Lex {vm.objects["LEX"][0]})')


def _aim_from(run, name, spot):
    """The aim Lex will need at `spot`, taken where he stands now, so that a sidestep (which keeps the heading) brings him there ready to fire."""
    bot, lex = run.world.figure(name), run.lex
    _aim(run, (bot.pos[0] - spot[0] + lex.pos[0], bot.pos[1] - spot[1] + lex.pos[1]))


def tower_bots(run):
    """The deck's bots shot from where they cannot answer. `_LexTowLoc` changes only when Lex enters a TTBAT box (AI_TOWER.scr:5-77) and each bot fires only in its own zones, so a spot outside the
    boxes, or in a zone whose shooters are dead, is safe however long the aiming takes. Bot 1 from ZB (zone 0); bot 2 from just north of ZB, ready aimed, so its first shot goes before it answers;
    bots 3 and 4 from around 4B (zone 4 fires only 1 and 2, dead by then); bot 6 from the south of zone 5. Bot 5 fires only in zones 6 and 9, off the route. Grids: re/NOTES.md "The tower bots shot"."""
    world, vm, lex = run.world, run.vm, run.lex
    if lex.combat:
        run.key(0x2e)
        run.tick(5)
    # LOADLEVEL TOWER ELH ELT (ELEVATOR.scr:260) puts Lex at his offset from ELH in ELT (FUN_1088_2dfc, (29233, -54002)), not at the cabin's centre:
    # he steps east inside TTBATZA (zone 0, safe) to above the dash's first point, so the dash runs straight south to it (from the arrival the
    # dash's turn circle misses the point)
    if run.difficulty:                          # the half turn there starts 150 units from TTBAT4 and drifts him into zone 4, where bots 1 and 2 fire (four hits on the default
        run.dash((29800, -52300), (31500, -52800), stop=700)     # stream, 6 HP each at Easy, 14 on Medium): a run curves to his right, north, then east
    else:
        run.goto(31500, -52800, radius=300)
    run.dash((31500, -57000), (30600, -60400), stop=500)
    _aim(run, world.figure('TOWBOT1').pos)
    _shoot_down(run, 'TOWBOT1')
    run.goto(28540, -60300, radius=120)
    _aim_from(run, 'TOWBOT2', (28540, -58650))
    world.key_down(0x51, 0)
    for _ in range(200):
        run.tick(1)
        if lex.pos[1] >= -58680:
            break
    world.key_up(0x51, 0)
    run.tick(1)
    _shoot_down(run, 'TOWBOT2')
    run.goto(28000, -58600, radius=350)         # anywhere in bot 3's box (x 27300-28700) will do; a tighter radius made a hit's recoil circle him west into zone 5

    def back_to_bot3_spot():
        if vm.globals.get('_lextowloc') == 4:
            return False
        run.goto(28000, -58600, radius=150)
        return True

    def clear_of_the_pillar():
        h = math.radians(lex.heading)
        key = 0x51 if -math.cos(h) * (27300 - lex.pos[0]) > 0 else 0x4f
        world.key_down(key, 0)
        for _ in range(200):
            run.tick(1)
            if lex.pos[0] <= 27300:
                break
        world.key_up(key, 0)
        run.tick(1)
    _shoot_down(run, 'TOWBOT3', back_to_bot3_spot, (28000, -58600), clear_of_the_pillar)
    if world.figure('TOWBOT4') is not None and vm.objects['TOWBOT4'][0] > 0:        # a shot at bot 3 from some spots goes through bot 4 too, and can finish it
        _aim_from(run, 'TOWBOT4', (27180, -58720))
        for _ in range(12):
            if lex.pos[1] >= -58800:
                break
            _hold(run, 0x50, 3)
            _settle(run)
        h = math.radians(lex.heading)
        right = (-math.cos(h), math.sin(h))
        key = 0x51 if (27180 - lex.pos[0]) * right[0] + (-58720 - lex.pos[1]) * right[1] > 0 else 0x4f
        world.key_down(key, 0)
        for _ in range(200):
            run.tick(1)
            if lex.pos[0] <= 27220:
                break
        world.key_up(key, 0)
        run.tick(1)

        def back_in_zone_4():
            if vm.globals.get('_lextowloc') == 4 and lex.pos[0] >= 27000:
                return False
            run.goto(27800, -58720, radius=150)
            run.goto(27180, -58720, radius=100)
            return True
        _shoot_down(run, 'TOWBOT4', back_in_zone_4)
    run.goto(25500, -60500, radius=300)
    run.goto(25000, -62800, radius=150)
    _shoot_down(run, 'TOWBOT6', spot=(25000, -62800))


def tower(run):
    """TOWER (base.md "TOWER"): across the deck, Roland's restart of the gun and both landers shot down with the gun keys
    (playthrough_base.tower_deck). Then the elevator back, to CONTROL."""
    with run.segment('tower'):
        tower_bots(run)
        r = attach(run, 'tower')
        pb.tower_deck(r, restart_gun=lambda r: roland(run))
        absorb(run, r)
        if run.vm.globals.get('_lander_stage', 0) < 5 or run.vm.globals.get('_firstlanderalive'):
            raise Stuck(f"the landers are not down (stage {run.vm.globals.get('_lander_stage')})")


def mecho2_cover(run):
    """While the ride's tail still holds the door shut: MECHO2 fires only while `_LexConLoc` is set (MECHO2_AI, AI_MECH2.scr:66-90), which CMECH1A / 1B set and
    CMECHZA / ZB, the cabin's corners by the door, clear (AI_MECH2.scr:1-19). At the console Lex stands in CMECH1A, and its first bolt (46 HP) leaves about
    50 ticks after the ride gives him back, through the door from the east, so Lex runs to the north corner at once: straight east along y -67750 (past the
    cabin's inner wall at x -39900, which stops him further north) and then into the middle of the corner's strip, as a `dash` (Shift+Up held, steering on
    the run). Turning east in place first (130 degrees, some 65 ticks) had him start the run as the bolt came and meet it at x -41500, in every stream."""
    run.until(lambda: run.lex.ai_enabled, 120, 'the ride gives Lex back')
    run.dash((-39000, -67800), (-34200, -67050), stop=700)            # into CMECHZA (x -36572..-32988, y -67584..-66560)


def mecho2_arrival(run):
    """From the cabin's north corner Lex shoots MECHO2 down with the BLASTER (4 hits, LASER_HIT_MECHO2). It does not fire back from there; most early shots
    miss through the door, so this takes a few thousand ticks. Its own death block then runs."""
    vm = run.vm
    run.shoot(run.world.figures['MECHO2'], lambda: vm.objects['MECHO2'][0] > 0, max_steps=6000)
    if vm.objects['LEX'][0] <= 0:
        raise Stuck('MECHO2 killed Lex')
    run.until(lambda: not run.running('MECHO2_DEATH') and run.lex.ai_enabled, 900, "MECHO2's death ends")
    heal(run)


def tower_exit(run):
    """Back across the deck, its bots shot on the way out (`tower_bots`), TDR_BUT (Space, COMPASS
    -130..-40, TOWER.scr:212-250) opens the cabin door, TWR_LV1 (COMPASS 50..130) opens the elevator monitor, CONB rides to CONTROL."""
    world, vm = run.world, run.vm
    with run.segment('tower-exit'):
        for x, y in ((52000, -59000), (46000, -64600), (25500, -64600), (25500, -61300)):
            run.goto(x, y, radius=600, run=True)
        run.fine_face(-90, tolerance=15)
        if run.use() != 'TDR_BUT_USE':
            raise Stuck('Space at TDR_BUT did not run TDR_BUT_USE')
        run.until(lambda: vm.globals.get('_dr7_space') == 2 and not run.running('ELEVATOR_DOOR_OPEN'), 400, 'the cabin door opens')
        for x, y in ((28000, -57000), (31000, -55500), (28800, -53800)):
            run.goto(x, y, radius=300)
        heal(run, 100)                                              # MECHO2 waits at the other end
        cabin_ride(run, 'TWR_LV1', (115,), 'CONB', 'CONTROL', on_arrival=mecho2_cover, after_tail=mecho2_arrival)      # the smallest turn into COMPASS 50..130: a bigger one carries his hull off the box


def operating_room(run):
    """CONTROL, once the first lander is down (Marine 1 is not readied): the hall west to CNT_BTN1 (Space; refused while MECHO2 lives,
    CONOPER.scr:111-135), DR13 opens, Lex walks to OPENTER and OPRSCENE plays (MASTABA.scr:3-32, 262-330) up to `_Operate_Done = 1`."""
    world, vm = run.world, run.vm
    with run.segment('operating-room'):
        run.until(lambda: not run.running('LEXTAUNTSMECHO2') and not run.running('MECHO2_DEATH'), 900, 'MECHO2_DEATH and the taunt')
        for x, y in ((-30000, -71000), (-22000, -71000), (-12000, -71000), (-3000, -71000), (6000, -70000), (7000, -68300)):
            run.goto(x, y, radius=400, run=y < -69000 or x < 0)
        if run.use() != 'CNT_BTN1_USE':
            raise Stuck('Space at CNT_BTN1 did not run CNT_BTN1_USE')
        run.until(lambda: vm.globals.get('_dr13_space') == 0 and not run.running('OPEN_OP_DOOR'), 600, 'DR13 opens')
        for x, y in ((11000, -66500), (11000, -62500), (11000, -59500), (11000, -58300)):
            run.goto(x, y, radius=400)
        run.until(lambda: vm.globals.get('_operate_done') == 1, 9000, 'OPRSCENE ends with _Operate_Done = 1')
        run.until(lambda: not run.running('OPRSCENE') and not run.running('OPR_MAS_1'), 3000, 'OPRSCENE ends')
        run.goto(12772, -48744, radius=500)                         # MEDICAID lies past the table, 8000 units on
        take(run, 'MEDICAID')
        heal(run, 100)                                              # GRDCON comes next


FROM_OPERATING_ROOM = ((6100, -48000), (8350, -54300), (11000, -59000), (11000, -62500), (11000, -66500), (11000, -70000))
FROM_CABIN = ((-25000, -71000), (-10000, -71000), (6000, -70500), (11000, -70000))


def hall_east(run, start=FROM_OPERATING_ROOM):
    """From the operating room out through DR13 (or from the cabin ELC) and the hall east to CNT_BTN3 (Space facing east, COMPASS -115..-45): it
    opens the control room's DR14 once `_Operate_Done` (CONCNTRL.scr:2-22)."""
    vm = run.vm
    for x, y in start + ((20000, -70800), (28000, -68000), (30800, -67800)):
        run.goto(x, y, radius=500, run=True)
    run.fine_face(-80, tolerance=10)
    if run.use() != 'CNT_BTN3_USE':
        raise Stuck('Space at CNT_BTN3 did not run CNT_BTN3_USE')
    run.until(lambda: vm.globals.get('_dr14_space') == 0, 400, 'DR14 opens')


def hardsuit(run):
    """Into the control room, up the machine-shop stairs to the hard-suit machine: SUITTEST starts HARDSUITMACHINE (CONCNTRL.scr:71-139),
    CHANGEMYFORM HARD. GRDCON (180 HP, melee) wakes on the way (ACTIVATE_GRDCON) and hits Lex until the machine takes him (AI_GRDCN.scr:98-120:
    it stands down while `_Suit_Machine_In_Use`); Lex keeps 40 of his 100 HP."""
    world, vm = run.world, run.vm
    with run.segment('hardsuit'):
        hall_east(run)
        for x, y in ((34500, -71000), (51000, -72000), (51000, -76000), (51000, -79000), (58000, -84000)):
            run.goto(x, y, radius=500)
        run.goto(61344, -86811, radius=300)                         # inside SUITTEST (x 60832..61856, y -87323..-86299); a guard's blow can knock him out of it again
        for _ in range(900):
            if run.lex.type == 'HARD' and not run.running('HARDSUITMACHINE'):
                break
            if vm.objects['LEX'][0] <= 0:
                raise Stuck('GRDCON killed Lex before the suit machine')
            if run.lex.ai_enabled and not run.running('HARDSUITMACHINE') and not vm.globals.get('_suit_machine_in_use') and run.lex.finished is not None and not run.lex.motion.startswith(run.BUSY):
                if not any(t['name'] == 'SUITTEST' and t['lo'][0] <= run.lex.pos[0] <= t['hi'][0] and t['lo'][1] <= run.lex.pos[1] <= t['hi'][1] for t in world.triggers):
                    run.goto(61344, -86811, radius=300)
            run.tick(1)
        else:
            raise Stuck('the machine never changes Lex to HARD')


def hangar_monitor(run):
    """At HANGRMON (the walk through the control room to it is not the point: set_pos): Space, ICARUS ACCESS (AIAB) with the pointer; the
    monitor's tail walks Lex back and runs LOWER_GARAGE_ELEVATOR."""
    world = run.world
    z = world.point_floor(44000, -54800, 0, 0)
    run.shortcut('set-pos', to=[44000, -54800], why='the hangar monitor HANGRMON (the walk through the control room to it is blocked by the lift recess: Lex sinks 1900 units at its south edge)')
    world.set_pos(run.lex, [44000.0, -54800.0, z + world.foot(run.lex)], raw=True)
    run.lex.heading = 180.0
    for _ in range(10):                                         # Space does nothing until his last motion has let go (a recoil restarted by a load)
        used = run.use()
        if used is not None:
            break
        run.tick(20)
    if used != 'HANGRMON_USE':
        raise Stuck('Space at HANGRMON did not run HANGRMON_USE')
    run.until(lambda: world.monitor is not None and world.monitor.name == 'HNGR', 120, 'the hangar monitor opens')
    run.click('AIAB')
    run.until(lambda: run.running('LOWER_GARAGE_ELEVATOR'), 400, 'LOWER_GARAGE_ELEVATOR starts')


def bike_battery(run):
    """The bike's battery holds 150 of 500 (BIKE_USE, CONMACH.scr:39-44), and by now Lex's holds about 9, the floor BIOREPAIR stops at. Space at the bike takes it out, Space away from the bike
    puts it in his leg (ABAT_500_USE, ITEMS.scr:1322-1329), and Space at the bike puts his old one back in (CONMACH.scr:67-192), which is what the ending takes out again."""
    world, vm, lex = run.world, run.vm, run.lex
    bike = pb.BIKE
    def use_bike():
        """Space at the bike; a LEVEL1TREMORS quake or a recoil that is still going (the fight's last blow) swallows it, and may have left him short of the bike: wait, walk up again, press again."""
        for _ in range(5):
            run.until(lambda: lex.ai_enabled, 400, 'the quake or the blow lets Lex go')
            run.goto(*bike, radius=500)
            if run.use() == 'BIKE_USE':
                return
            run.tick(40)
        raise Stuck('Space at the bike did not run BIKE_USE')
    run.goto(bike[0], bike[1] - 3500 if lex.pos[1] < bike[1] else bike[1] + 2500, radius=500)       # round the bike's side he is on, whose hull a straight line clips
    use_bike()
    run.until(lambda: vm.globals.get('_battery_in_bike') == 0 and not run.running('BIKE_USE') and lex.ai_enabled, 600, 'BIKE_USE takes the battery out')
    run.goto(bike[0], bike[1] + 2500, radius=500)                   # Space takes the bike first while it is in reach
    if world.held_item(lex, 'LTHAND') is not None:                  # and a left-hand item before the right hand's
        run.key(KEY_I)
        run.until(lambda: world.held_item(lex, 'LTHAND') is None, 60, 'I stows the left-hand item')
    if run.use() != 'ABAT_500_USE':
        raise Stuck('Space did not run ABAT_500_USE')
    run.until(lambda: not run.running('ABAT_500_USE') and lex.ai_enabled, 400, 'the batteries are swapped')
    use_bike()
    run.until(lambda: vm.globals.get('_battery_in_bike') == 2 and not run.running('BIKE_USE') and lex.ai_enabled, 600, 'BIKE_USE takes the old battery')
    if world.held_item(lex, 'RTHAND') is not None:
        raise Stuck('the old battery is still in his hand')


def garage_block(run):
    """The hangar monitor (HANGRMON, Space facing the wall; CR_HANGERMONITOR, CONCNTRL.scr:208-385): ICARUS ACCESS (AIAB) closes the monitor and
    lowers the garage lift under Lex (LOWER_GARAGE_ELEVATOR, CONMACH.scr:402-519); GRDHANG (180 HP) wakes at the bottom and Lex fights him there, healed first with
    MEDICAID's charges (he arrives with about 55); the BLOCK lies at (37272, -41797); TAKEMEUP raises the lift (CONMACH.scr:288-398)."""
    world, vm = run.world, run.vm
    with run.segment('garage-block'):
        if world.usable_objects(run.lex):                           # grdcon can end with Lex in MAINTMON's box (y -88415..-87455); Space would use the monitor, not the medkit
            run.goto(float(run.lex.pos[0]), -86300, radius=300)
        heal(run, 100)
        hangar_monitor(run)
        run.until(lambda: run.running('ACTIVATE_GRDHANG') or vm.globals.get('_grdhang_active') == 1, 900, 'GRDHANG wakes')
        run.until(lambda: vm.globals.get('_seen_mach_shop') == 1, 9000, 'the garage lift is down')
        guard = world.figure('GRDHANG')
        if guard is not None:
            rhythm = run.__dict__.get('FIGHT_DELAY')               # Medium and Hard keep their own (play)
            run.FIGHT_DELAY = dict(run.FIGHT_DELAY, punch=GRDHANG_PUNCH)   # a beat more between blows: with the usual 1 two streams lost to him since the fists came down on leaving combat, with 2 both win
            run.fight(guard, lambda: vm.objects['GRDHANG'][0] > 0)
            if rhythm is None:
                del run.FIGHT_DELAY                                 # back to the class's rhythm
            else:
                run.FIGHT_DELAY = rhythm
            if vm.objects['LEX'][0] <= 0:
                raise Stuck('GRDHANG killed Lex')
        for x, y in ((43000, -52500), (45000, -49500)):
            run.goto(x, y, radius=500)
        bike_battery(run)
        heal(run, 100)                                              # here rather than at the reactor, where the detonation timer is running
        run.goto(40000, -46000, radius=500)
        take(run, 'BLOCK')


def garage_up(run):
    """Back to the lift: walk into TAKEMEUP (it fires on entry; `_waiting_to_leave_elv` is clear once Lex has left the platform) and
    RAISE_GARAGE_ELEVATOR takes him up to the control room (CONMACH.scr:288-398); then the three QST steps out of the recess and the hall west."""
    world, vm = run.world, run.vm
    with run.segment('garage-up'):
        for x, y in ((43500, -49500), (43500, -52000), (44000, -56500), (44000, -60500)):
            run.goto(x, y, radius=400)
        run.until(lambda: run.lex.pos[2] > -20000 and not run.running('RAISE_GARAGE_ELEVATOR'), 3000, 'TAKEMEUP raises the lift')
        run.goto(44200, -65100, radius=300)         # the three stair steps QST3 / QST2 / QST1 lead out of the QSF recess
        run.goto(44200, -69000, radius=400)
        for x, y in ((36000, -71000), (30000, -71000)):
            run.goto(x, y, radius=500)


def grdcon(run):
    """In the hard suit Lex beats GRDCON (AI_GRDCN.scr), whose death readies GRDHALL (AI_GRDCN.scr:299, READY_GRDHALL) for the hall. The fight is beside the machine: a blow
    that knocks Lex into SUITTEST runs HARDSUITMACHINE again, which takes the suit off, and DR2_OPEN chokes a plain Lex in the reactor airlock (CONREACT.scr:211-219), so he
    walks back in afterwards."""
    world, vm = run.world, run.vm
    with run.segment('grdcon'):
        heal(run, 100 if run.difficulty else 75)
        run.fight(world.figures['GRDCON'], lambda: bool(vm.globals.get('_grdcon_alive')))
        if vm.objects['LEX'][0] <= 0:
            raise Stuck('GRDCON killed Lex')
        if vm.globals.get('_grdcon_alive'):
            raise Stuck(f"the fighting routine stopped with GRDCON up ({vm.objects['GRDCON'][0]} HP)")
        run.until(lambda: not run.running('GRDCON_DEATH') and run.lex.ai_enabled, 1500, "GRDCON's death ends")
        if run.lex.combat:
            run.key(0x2e)
            run.tick(5)
        if run.lex.type != 'HARD':                                  # a blow knocked him back into SUITTEST, and HARDSUITMACHINE took the suit off again: in again
            for _ in range(3):
                run.goto(61344, -86811, radius=300)
                run.until(lambda: run.running('HARDSUITMACHINE') or run.lex.type == 'HARD', 200, 'SUITTEST starts the machine')
                run.until(lambda: not run.running('HARDSUITMACHINE') and run.lex.ai_enabled, 900, 'the machine lets Lex go')
                if run.lex.type == 'HARD':
                    break
                run.goto(60000, -85000, radius=400)                # out of the box, so the next walk in is a new entry
            if run.lex.type != 'HARD':
                raise Stuck('the suit machine did not put the hard suit back on')


def grdhall(run):
    """GRDHALL waits in the hall (HLC_LOAD, CONTROL.scr:106-109), with BLASTER2. Lex comes to him from the garage, repaired on the bike's battery."""
    world, vm = run.world, run.vm
    with run.segment('grdhall'):
        heal(run, 100)
        run.fight(world.figures['GRDHALL'], lambda: bool(vm.globals.get('_grdhall_alive')))
        if vm.objects['LEX'][0] <= 0:
            raise Stuck('GRDHALL killed Lex')
        if vm.globals.get('_grdhall_alive'):
            if vm.globals.get('_grdhallhateslex'):
                raise Stuck(f"the fighting routine gave up on GRDHALL ({vm.objects['GRDHALL'][0]} HP)")
            if run.difficulty:                                      # BLASTER2 is the gun AIRMECHO's duel needs (OPRSCENE destroyed the BLASTER)
                raise Stuck(f"the fighting routine never hit GRDHALL ({vm.objects['GRDHALL'][0]} HP): no BLASTER2")
            if run.lex.combat:                                      # never hit, he stays peaceful with the suit on (AI_GRDHL.scr:89-127), and the run goes on without his gun
                run.key(0x2e)
                run.tick(5)
            hall_east(run, ((run.lex.pos[0], -70800),))
            return
        run.until(lambda: not run.running('GRDHALL_DEATH') and run.lex.ai_enabled, 1500, "GRDHALL's death ends")
        if run.lex.combat:
            run.key(0x2e)
            run.tick(5)
        heal(run, 100)
        take(run, 'BLASTER2')
        run.tick(30)
        hall_east(run, ((run.lex.pos[0], -70800),))                 # DR14 has closed behind him, and the fight can end anywhere in the hall


FORK_LANE = -8990          # the x of the airlock's doorways (DR11 and DR12 span -10338..-7643)


def steer_u_turn(run, low, high, limit=60):
    """Walk + Right held (a held turn key steers a walk at 4 degrees a tick) until the heading is in low..high: a U-turn about 1700 units wide."""
    lex = run.lex
    run.world.key_down(0x48, 0)
    run.world.key_down(0x4d, 0)
    for _ in range(limit):
        if low <= (lex.heading + 180) % 360 - 180 <= high:
            break
        run.tick(1)
    run.world.key_up(0x4d, 0)
    run.world.key_up(0x48, 0)


def forklift(run):
    """The console by the control room's east stairs (FORKMON1_USE, CONTROL.scr:70): MANUAL, then drive CR_BOT by the MLBT buttons (ROBOCNTL.scr) out of the control room, along the
    hall and through the airlock, whose doors and decontamination cycle run for the robot (AL1_AUTO_CR_BOT, DR2_OPEN_CR_BOT, DECON_CR_BOT, DR8_OPEN_CR_BOT, CONREACT.scr), into RAM_BOT:
    RAM_BOT_CR_BOT kills the robot and REACTBOT, whose bolts hold the reactor room, and readies Drogg 1."""
    world, vm = run.world, run.vm
    with run.segment('forklift'):
        for x, y in ((44000, -71000), (56800, -71500)):
            run.goto(x, y, radius=300)
        run.goto(56850, -73000, radius=150)
        run.fine_face(0)
        walk_into_reach(run, 'FORKMON1', 0)
        if run.use() != 'FORKMON1_USE':
            raise pp.Stuck('Space at the forklift console did not run FORKMON1_USE')
        run.until(lambda: world.monitor is not None, 300, 'the forklift monitor opens')
        run.tick(10)
        run.click('MANB')
        run.until(lambda: vm.globals.get('_forklift_activated') == 1, 400, 'the forklift activates')
        bot = world.figures['CR_BOT']
        for x, y in ((38400, -76000), (36000, -71000), (30000, -71000), (10000, -71000), (-4000, -71000)):
            pp.drive_bot(run, bot, 1, x, y, radius=900)
        pp.drive_bot(run, bot, 1, FORK_LANE, -72800, radius=500)
        best, stall = bot.pos[1], 0
        while not vm.globals.get('_conbot_is_ramming'):             # the airlock lane: steer on the sideways error, the doorways are narrow for its 1800-unit hull
            want = max(-45, min(45, math.degrees(math.atan2(bot.pos[0] - FORK_LANE, 1200))))
            delta = pp.bot_delta(bot, want)
            if abs(delta) > 6:
                run.hold_button('RTDB' if delta > 0 else 'LTDB', max(2, min(8, int(abs(delta) / 4))))
                run.tick(6)
                continue
            run.hold_button('UPDB', 16)
            best, stall = (bot.pos[1], 0) if bot.pos[1] < best - 30 else (best, stall + 1)
            if stall >= 25:
                raise pp.Stuck(f'the forklift stopped at {[int(v) for v in bot.pos[:2]]} on the way to RAM_BOT')
        run.until(lambda: vm.globals.get('_forklift_dead') == 1, 400, 'the forklift rams REACTBOT')
        run.click('PWRB')
        run.tick(10)


def reactor_room(run):
    """Lex's way in: the hall button CNT_BTN2 (he has to reach the door before it has opened, or CONDR2AUTOCLOSE shuts it again), the airlock cycle (the inner door opens only on the
    suit: DR2_OPEN chokes a plain LEX, CONREACT.scr:211-219) and BRDG_BUT, whose COMPASS test (-90..-10) has Lex looking back at the bridge."""
    world, vm = run.world, run.vm
    with run.segment('reactor-room'):
        for x, y in ((44000, -71000), (30000, -71000), (10000, -71000), (-13800, -71500)):
            run.goto(x, y, radius=500)
        run.goto(-13800, -73000, radius=120)
        run.fine_face(0)
        if run.use() != 'CNT_BTN2_USE':
            raise pp.Stuck('Space at the hall button did not run CNT_BTN2_USE')
        run.tick(25)
        run.goto(FORK_LANE, -74500, radius=300, run=True)
        run.goto(FORK_LANE, -77200, radius=150)
        run.until(lambda: vm.globals.get('_dr2_frame') == 0, 400, 'the airlock door opens')
        for y in (-82000, -84000, -87000, -91000):
            run.goto(FORK_LANE, y, radius=300)
        run.until(lambda: vm.globals.get('_dr8_frame') == 0, 700, 'the inner door opens')
        for y in (-94000, -97500, -99500):
            run.goto(FORK_LANE, y, radius=300)
        run.tick(40)
        run.goto(-8450, -102300, radius=100)      # BRDG_BUT's box starts at x -8268 and Lex's hull reaches about 370 ahead: at -8700 (radius 120 round -8600) it missed
        run.fine_face(-50)
        if run.use() != 'BRDG_BUT_USE':
            raise pp.Stuck('Space at the bridge button did not run BRDG_BUT_USE')
        run.until(lambda: vm.globals.get('_brdg_on') == 1 and not vm.globals.get('_bridge_moving'), 900, 'the light bridge comes on')


DROGG_ATTACK = 0x4b       # KP4: ATK_H4. Of the 16 Alt and Ctrl attacks tried over six start times it won all six, the fastest (five with 57 of 84 HP left, in about 570 ticks); ATK_H8 lost all six.


def drogg1(run):
    """The first step onto the bridge (CONLOC10) starts the 90-second reactor timer. Drogg 1 only guards the far platform until he has taken six super recoils (_Drogg1_Max_KO, DROGG1_AI,
    AI_DROG1.scr:226): from then on he follows Lex onto the bridge. Pulling both levers first is the trap: the second sends him to the bridge button (DROGG1_RUNFORIT), where he retracts
    the bridge under a Lex who comes back (THREE_BILLY_GOAT_GRUFF). So Lex runs back with him on the bridge and retracts it first: he falls into RFALLEN_DROGG1."""
    world, vm = run.world, run.vm
    with run.segment('drogg1'):
        run.goto(-8950, -105500, radius=200)
        heal(run, 100)
        for y in (-110000, -120000, -130000, -134500, -138500):
            run.goto(-8950, y, radius=500, run=True)
        run.fight(world.figures['DROGG1'], lambda: vm.globals.get('_drogg1_counter', 0) < 6, attack=DROGG_ATTACK)
        if vm.objects['LEX'][0] <= 0:
            raise pp.Stuck('Drogg 1 killed Lex before his sixth super recoil')
        run.key(0x2e)
        run.tick(3)
        run.dash((-8950, -137500), (-8950, -120000), (-9800, -103800), stop=900)
        for _ in range(8):                                          # the U-turn is 1450 units long: it has to start at about y -103800 to end at the button
            if run.lex.pos[1] > -104100:
                break
            run.key(0x48, 0, 4)
        steer_u_turn(run, -60, -25)
        if 'BRDG_BUT' not in world.usable_objects(run.lex):
            run.goto(-8300, -102350, radius=250)
            run.face(-50, tolerance=25)
        drogg = world.figures['DROGG1']
        run.until(lambda: drogg.pos[1] > -131000, 300, 'Drogg 1 is on the bridge')     # WK1 runs from -133966 to -107151; he leaves it at about 170 units a tick once he runs
        if run.use() != 'BRDG_BUT_USE':
            raise pp.Stuck(f'the bridge button is out of reach at {[int(v) for v in run.lex.pos[:2]]}')
        run.until(lambda: vm.globals.get('_drogg1_alive') == 0, 200, 'Drogg 1 falls with the bridge')
        run.until(lambda: not vm.globals.get('_bridge_moving') and not run.running('BRDG_BUT_USE'), 400, 'the bridge has gone')     # the press sets _Bridge_Moving only after its WAIT 15


def reactor_shutdown(run):
    """Bridge back on, both levers (LFT_LEV_USE / RGT_LEV_USE, AI_DROG1.scr: REACTOR_PULL holds Lex for about 4 seconds each) and the console (RTR_MON_USE, SHUTDOWN.scr): the three
    buttons of the reactor ID, POWER DOWN. The ID is read from its global: the REACTO text of the control monitors shows the same number (%_reactor_id_number%, CONCNTRL.scr:159), and
    the harness does not go and look. Then back over the bridge and out through the airlock from its reactor side (LOCK_BTN_USE, COMPASS -115..-45)."""
    world, vm = run.world, run.vm
    lex = run.lex
    with run.segment('reactor-shutdown'):
        if run.use() != 'BRDG_BUT_USE':
            raise pp.Stuck('Space at the bridge button did not run BRDG_BUT_USE')
        run.until(lambda: vm.globals.get('_brdg_on') == 1 and not vm.globals.get('_bridge_moving'), 600, 'the light bridge comes back')
        run.goto(-8950, -106000, radius=1500)
        run.dash((-8950, -122000), (-8950, -138500), stop=900)
        for var, block, x, y in (('_rt_lev', 'RGT_LEV_USE', -14900, -144750), ('_lt_lev', 'LFT_LEV_USE', -3100, -145150)):
            run.dash((x, y), stop=1300)
            run.goto(x, y, radius=500)                              # into_box does the rest: the timer leaves about 1200 ticks from the bridge to the console, and a quake can take 200
            run.into_box(block[:-4])
            if run.use() != block:
                raise pp.Stuck(f'Space at the lever did not run {block}')
            run.until(lambda: vm.globals.get(var) == 1, 160, f'{var} is pulled')
        for _ in range(3):                                          # a LEVEL1TREMORS quake (AI off) can take the turn and the dash: wait it out and go again
            run.until(lambda: lex.ai_enabled, 400, 'the quake lets Lex go')
            run.face_point(-7000, -148300, tolerance=5)
            run.dash((-7000, -148300), until=lambda: 'RTR_MON' in world.usable_objects(lex), limit=80)
            if 'RTR_MON' in world.usable_objects(lex):
                break
        if run.use() != 'RTR_MON_USE':
            raise pp.Stuck('Space at the console did not run RTR_MON_USE')
        run.until(lambda: world.monitor is not None, 200, 'the reactor monitor opens')
        run.tick(4)
        for digit in str(vm.globals['_reactor_id_number']):
            run.click(f'CD{digit}B')
        run.click('PRDB')
        if vm.globals.get('_reactor_safe') != 1:
            raise pp.Stuck('POWER DOWN did not set _Reactor_Safe')
        run.until(lambda: not run.running('SHUT_DOWN_WIN'), 500, 'the shutdown sequence ends')
        run.dash((-8950, -138000), (-8950, -122000), (-8950, -106000))
        run.goto(-7300, -96900, radius=350)
        run.face(-85, tolerance=12)
        for _ in range(8):
            if 'LOCK_BTN' in world.usable_objects(lex):
                break
            run.key(0x48, 0, 4)
        if run.use() != 'LOCK_BTN_USE':
            raise pp.Stuck('Space at the reactor-side button did not run LOCK_BTN_USE')
        run.until(lambda: vm.globals.get('_dr8_frame') == 0, 500, 'the inner door opens')
        for y in (-94500, -92000, -89000, -86500, -84000):
            run.goto(FORK_LANE, y, radius=350)
        run.until(lambda: vm.globals.get('_dr2_frame') == 0, 800, 'the outer door opens')
        for y in (-81000, -77000, -74000, -71500):
            run.goto(FORK_LANE, y, radius=400)


def to_landpad(run):
    """Hall west to the cabin ELC and its console ELV_C21 (COMPASS 50..130, CONTROL.scr:178-190), AIRB: SWITCHTOLANDINGLEVEL (ELEVATOR.scr:326-430).
    The bots are alive: the pad's never fire on the way, the ledge's are run past (ledge_run), and so are the BEACH ones (beach_zip1)."""
    world, vm = run.world, run.vm
    with run.segment('to-landpad'):
        heal(run, 100)                                              # the ledge's and the BEACH's bots come next, and nothing heals him on the way
        block = world.items.get('BLOCK')
        if block is not None and block.owner == run.lex.name and world.held_item(run.lex, 'LTHAND') is not block:     # a repair in a fight stowed it, and the zip lines want it
            ready_item(run, block.key)
        for x, y in ((-25000, -71000), (-30500, -68300)):
            run.goto(x, y, radius=600, run=True)
        if run.use() != 'CTRELVDR_USE':
            raise Stuck('Space at the cabin door did not run CTRELVDR_USE')
        run.until(lambda: vm.globals.get('_dr9_space') == 0, 400, 'the cabin door opens')
        run.goto(-36000, -70000, radius=600)
        cabin_ride(run, 'ELV_C21', (90,), 'AIRB', 'LANDPAD')


LEGS = [('guard1', guard1), ('bio-repair', bio_repair), ('tanks-back', tanks_back), ('hall-to-elevator', hall_to_elevator), ('tower', tower), ('tower-exit', tower_exit), ('operating-room', operating_room), ('hardsuit', hardsuit), ('grdcon', grdcon), ('garage-block', garage_block), ('garage-up', garage_up), ('grdhall', grdhall), ('forklift', forklift), ('reactor-room', reactor_room), ('drogg1', drogg1), ('reactor-shutdown', reactor_shutdown), ('to-landpad', to_landpad), ('landpad', landpad), ('beach', beach), ('digsite', digsite), ('tunroom', tunroom), ('battle-room', battle_room), ('platform', platform), ('platform-exit', platform_exit), ('zero-g-back', zero_g_back), ('grav-ring', grav_ring), ('temple-monitor', temple_monitor), ('temple', grenade), ('beach-climb', beach_climb), ('landpad-to-elevator', to_landpad_again), ('bike', bike)]


DIFFICULTIES = {'easy': 0, 'medium': 1, 'hard': 2}
# Above Easy every other figure animates faster (FUN_1098_0088: -64 per level against +128 at Easy) and hits Lex 4 per level harder (FUN_1090_09b9), so the
# fighting routine keeps a quicker rhythm and switches BIOREPAIR on earlier (opening the page costs blows: it is safer with HP to spare). Of 12 RANDOM
# streams from the default Medium run's GRDCON fight, with the heal before it: the Easy rhythm (wait 2, key 4, punch 1) wins 1, key 2 and punch 1 win 11
# (key 3: 10, key 4: 3, key 5: 4); with that rhythm a repair under 35 HP wins 7, under 50 10, under 65 12, under 75 11 (NOTES "Medium and Hard played through").
LEVEL_FIGHT_DELAY, LEVEL_HEAL_BELOW = {'wait': 1, 'key': 2, 'punch': 1}, 65


def play(stop_after=None, seed=None, difficulty=0):
    """The whole route, leg by leg, until one fails (or `stop_after` is done). `seed` starts RANDOM after the nurse, the first fight's draws on.
    `difficulty` (1 Medium, 2 Hard) is set once the prison is done, after guard1 (shortcut `difficulty`); Easy changes nothing. -> Full."""
    run = pp.play(run_class=Full, seed=seed)
    if not run.passed:
        return run
    for name, leg in LEGS:
        if not run.passed:
            break
        leg(run)
        if name == 'guard1' and difficulty and run.passed:
            run.shortcut('difficulty', level=difficulty)
            run.difficulty = run.vm.globals['_difficulty_level'] = difficulty
            run.FIGHT_DELAY, run.HEAL_BELOW = LEVEL_FIGHT_DELAY, LEVEL_HEAL_BELOW
        if stop_after == name:
            break
    return run


def report(run):
    result = pp.report(run)
    result['shortcut_names'] = sorted({s['name'] for s in run.shortcuts})
    result['exit_requested'] = bool(run.world.exit_requested)
    result['final_level'] = run.world.level
    result['lex_health'] = run.vm.objects['LEX'][0]
    result['globals'] = {k: run.vm.globals.get(k) for k in ('_grav_solved', '_alien_city_seen', '_gave_alien_battery', '_operate_done', '_reactor_safe')}
    if run.difficulty:                                              # an Easy report stays as it was
        result['difficulty'] = run.difficulty
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--out', default=os.path.join(os.path.dirname(os.path.dirname(HERE)), 're', 'out', 'playthrough'))
    parser.add_argument('--stop-after', default=None)
    parser.add_argument('--seed', type=int, default=None)
    parser.add_argument('--difficulty', choices=DIFFICULTIES, default='easy', help='the level after the prison (which is played at Easy)')
    args = parser.parse_args()
    started = time.time()
    result = report(play(args.stop_after, args.seed, DIFFICULTIES[args.difficulty]))
    os.makedirs(args.out, exist_ok=True)
    with open(os.path.join(args.out, 'playthrough_full.json'), 'w', encoding='utf-8') as handle:
        json.dump(scenarios.plain(result), handle, indent=1, sort_keys=True)
    for seg in result['segments']:
        print(f"{seg['name']:24} {seg['status']:8} ticks {seg['start_tick']}-{seg['end_tick']}")
    for p in result['problems']:
        print(f"[{p['severity']}] {p['segment']}: {p['kind']}: {p['message'].splitlines()[0]}")
    print(f"{result['final_tick']} ticks in {time.time() - started:.0f} s")
