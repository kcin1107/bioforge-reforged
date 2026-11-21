"""Playthrough harness for the base and the ending: CONTROL, TOWER, PLATFORM and ENDGAME. The path, the findings and the blocker list
are in re/playthrough/base.md. Run from the repository root:
    re/.venv/bin/python -I -W ignore re/interp/playthrough_base.py [--out DIR]

Every segment starts in the level the game comes from and arrives through the engine's own LOADLEVEL path (the scripted elevator ride
or tube transit runs the statement). It then drives the real scripts with player keys (World.key_down / key_event and the recovered
PC key map) in deterministic steps with checkpoints. Where keys are impractical a staged shortcut is taken: each one is listed in
SHORTCUTS with its reason and logged in the run report when it is applied. Problems (warnings, unmodelled calls, stuck steps, a dead
Lex) are collected per step.
"""
import argparse
import json
import math
import os
import sys
import types

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import scenarios  # noqa: E402
from playthrough_prison import Stuck  # noqa: E402
import vm as vmmod  # noqa: E402
import world as worldmod  # noqa: E402

SPACE, ENTER, ESC, KP4, KP5, KP6 = 0x39, 0x1c, 0x01, 0x4b, 0x4c, 0x4d
SHIFT = worldmod.keys_mod.SHIFT

SHORTCUTS = {
    'player': 'Lex is created as START.scr does (CREATEFIGURE LEX PLAYER) and placed at the source level\'s arrival point; the '
              'earlier levels are not played.',
    'globals': 'Story globals the earlier levels would have set are assigned directly (listed per run).',
    'item': 'An item the earlier levels would have given is created by a staging block that repeats the giving script\'s statements.',
    'elevator-button': 'The elevator monitor\'s floor button (ELEVATOR_MONITOR, a MON_* click) is replaced by starting the block the '
                       'button runs (SWITCHTOCONTROLLEVEL / SWITCHTOTOWERLEVEL).',
    'trigger': 'A trigger or monitor whose geometry or UI is not driven by keys is replaced by starting the block it runs.',
    'set-pos': 'Lex is moved next to a trigger instead of walking there.',
    'hold-fire': 'Lex crosses a fight zone while its shooters\' AI is off (the tower bots: missile hits ignore INVULNERABLE, NOTES '
                 '"Missiles"), and their AI is switched back on afterwards.',
    'fight-outcome': 'A fight is skipped by setting its recorded outcome (the global its death or capitulation block sets).',
    'unstick': 'A scripted GO that makes no progress is completed by moving the figure to its target (the waiting script resumes).',
}


class Run:
    """One segment: a world, its VM, and everything observed. `tick` advances the normal frame loop (scenarios.tick)."""

    def __init__(self, segment, level):
        self.segment = segment
        self.world = worldmod.World(level, state_dir=worldmod.INITGAME)
        self.vm = vmmod.VM(self.world)
        vmmod.load_level(self.vm, level)
        self.world.fire_event(level + '_LOAD')
        self.checkpoints, self.problems, self.shortcuts, self.inputs, self.blocks = [], [], [], [], []
        self._seen, self._warn_seen = set(), (0, 0, 0)
        self.lex_hits = []

    @classmethod
    def attached(cls, segment, outer):
        """A Run on the world and VM of a run that is already going (playthrough_full): nothing is created or seeded; the keys it sends go to
        `outer.inputs`. Its checkpoints, problems and shortcuts stay on this object for the caller to merge."""
        r = cls.__new__(cls)
        r.segment, r.world, r.vm, r.outer = segment, outer.world, outer.vm, outer
        r.checkpoints, r.problems, r.shortcuts, r.inputs, r.blocks = [], [], [], outer.inputs, []
        r._seen, r._warn_seen = set(), (len(r.world.warnings), len(r.vm.warnings), len(r.world.unmodelled))
        r.lex_hits = []
        return r

    # ---- bookkeeping
    @property
    def lex(self):
        return self.world.player()

    def shortcut(self, kind, **detail):
        self.shortcuts.append(dict(kind=kind, tick=self.vm.tick, reason=SHORTCUTS[kind], **detail))

    def problem(self, kind, text, rank=None):
        self.problems.append({'segment': self.segment, 'tick': self.vm.tick, 'kind': kind, 'text': text, 'rank': rank})

    def collect(self, step):
        """New warnings / unmodelled calls since the last step become problems."""
        w, vm = self.world, self.vm
        a, b, c = self._warn_seen
        for text in w.warnings[a:]:
            self.problem('warning', f'{step}: {text}')
        for text in vm.warnings[b:]:
            self.problem('vm-warning', f'{step}: {text}')
        for text in w.unmodelled[c:]:
            self.problem('unmodelled', f'{step}: {text}')
        self._warn_seen = (len(w.warnings), len(vm.warnings), len(w.unmodelled))

    def checkpoint(self, name, **extra):
        point = scenarios.checkpoint(self.world, self.vm, name)
        point.pop('frame')
        point.pop('figures')
        point['hp'] = self.vm.objects[self.world.player_name][0] if self.lex is not None else None
        point.update(extra)
        self.checkpoints.append(scenarios.plain(point))
        self.collect(name)
        return point

    # ---- time
    def tick(self, count=1):
        for _ in range(count):
            lex = self.lex
            hp = self.vm.objects[self.world.player_name][0] if lex is not None else None
            scenarios.tick(self.world, self.vm, 1)
            if lex is not None and self.vm.objects[self.world.player_name][0] != hp:
                self.lex_hits.append((self.vm.tick, hp, self.vm.objects[self.world.player_name][0]))
            for proc in list(self.vm.procs.values()):
                name = proc.block.name.split('(')[0]
                if not proc.done and name != 'TIMED' and name not in self._seen:
                    self._seen.add(name)
                    self.blocks.append((self.vm.tick, name))

    def until(self, step, cond, limit):
        """Tick until `cond()` holds; a step that never gets there within `limit` ticks is logged as stuck. -> reached"""
        for _ in range(limit):
            if cond():
                return True
            self.tick()
        if cond():
            return True
        self.problem('stuck', f'{step}: no progress in {limit} ticks')
        return False

    def running(self, name):
        return any(p.block.name.split('(')[0] == name and not p.done for p in self.vm.procs.values())

    def ran(self, name):
        """A block that ran, even one that started and ended within a tick (its engine calls are in World.log)."""
        return name in self._seen or any(entry[1] == name for entry in self.world.log)

    # ---- input (scenarios.Play's real-key driver, logged here)
    def play(self):
        play = scenarios.Play(self.world, self.vm, self.inputs)
        play.tick = self.tick
        return play

    def key_event(self, scan, mods=0):
        self.inputs.append({'tick': self.vm.tick, 'scan': scan, 'mods': mods, 'event': True})
        self.world.key_event(scan, mods)

    # ---- staging
    def create_lex(self, arrival):
        self.world.call('stmt', 'CREATEFIGURE', ['LEX', 'PLAYER'], stub())
        t = self.world.arrival_point(arrival)
        self.world.set_pos(self.lex, [t[0][0], t[0][1], t[1] + self.world.foot(self.lex)], raw=True)
        self.shortcut('player', at=arrival)

    def set_globals(self, **values):
        for k, v in values.items():
            self.vm.globals[k.lower()] = v
        self.shortcut('globals', values=values)

    def stage_block(self, text, name):
        """Load a staging block into the current level's scripts and start it. -> process"""
        load_script(self.vm, text)
        return self.vm.spawn(name, ctx=types.SimpleNamespace(cur_fig=self.world.player_name, cur_item=None, owner='level'))

    def set_pos(self, xy, heading=None, **why):
        lex = self.lex
        z = self.world.point_floor(int(xy[0]), int(xy[1]), int(lex.pos[2]), int(lex.pos[2]))
        self.world.set_pos(lex, [xy[0], xy[1], z + self.world.foot(lex)], raw=True)
        if heading is not None:
            lex.heading = heading
        self.shortcut('set-pos', to=[int(xy[0]), int(xy[1])], **why)

    def unstick(self, name, step, limit=300):
        """Wait while figure `name` walks a scripted GO; if it stops making progress for `limit` ticks, log it and finish the GO."""
        fig = self.world.figure(name)
        last, still = None, 0
        while fig is not None and fig.go is not None:
            pos = fig.pos[:2].copy()
            self.tick()
            still = still + 1 if last is not None and np.hypot(*(pos - last)) < 40 else 0
            last = pos if still == 0 or last is None else last
            if still >= limit:
                self.problem('stuck', f'{step}: {name} makes no progress toward its GO target at {[int(v) for v in fig.pos]}')
                self.shortcut('unstick', figure=name, at=[int(v) for v in fig.pos], to=[int(v) for v in fig.go['target']])
                fig.pos = np.array([fig.go['target'][0], fig.go['target'][1], fig.go['z']])
                fig.go = None
                return False
        return True

    def release_motion(self, step, limit=120):
        """Wait for the one-shot motion a script left Lex in (a CONTINUE motion plays once unless its header event list has the 0xfe loop
        marker) to end, so the keys work again; a motion that does not end within `limit` ticks is logged as stuck."""
        lex = self.lex
        motion = lex.motion
        if motion == 'STAND' or lex.finished:
            return
        self.until(f'{step}: {motion} ends', lambda: lex.motion != motion or lex.finished, limit)

    def heading_to(self, xy):
        d = np.asarray(xy[:2], float) - self.lex.pos[:2]
        return math.degrees(math.atan2(-d[0], -d[1]))

    def report(self):
        self.collect('end')
        return scenarios.plain({
            'segment': self.segment, 'tick': self.vm.tick, 'level': self.world.level, 'checkpoints': self.checkpoints,
            'shortcuts': self.shortcuts, 'problems': self.problems, 'inputs': self.inputs, 'blocks': self.blocks,
            'level_loads': [(t, lv, arr) for t, lv, arr, _ in self.world.level_loads], 'lex_hits': self.lex_hits,
            'exit_requested': bool(self.world.exit_requested)})


def stub(fig='PLAYER'):
    return types.SimpleNamespace(block=types.SimpleNamespace(name='HARNESS'), cur_fig=fig, cur_item=None, handle=0, waiters=[])


def load_script(vm, text):
    import tempfile
    with tempfile.NamedTemporaryFile('w', suffix='.scr', delete=False) as t:
        t.write(text)
    try:
        vm.load(t.name)
    finally:
        os.unlink(t.name)


def ride_elevator(r, block, level, on_arrival=None):
    """Start an elevator ride (the monitor button's block) and wait until the caller has run its post-LOADLEVEL tail (door open);
    `on_arrival(r)` runs in the first tick spent in the new level."""
    r.shortcut('elevator-button', block=block)
    r.vm.fire(block)
    r.until(f'{block}: LOADLEVEL {level}', lambda: r.world.level == level, 900)
    if on_arrival is not None:
        on_arrival(r)
    return r.until(f'{block}: arrival tail in {level}', lambda: not r.running(block), 900)


# ---------------------------------------------------------------------------------------------------------------- CONTROL (1st)
def control_first():
    """CHAOS → elevator → CONTROL: the ride, the door, the arrival blocks (ELEVATOR.scr:231-325, CONTROL.scr:4-68)."""
    r = Run('control-first', 'CHAOS')
    r.create_lex('ELH')
    r.shortcut('item', block='the CHAOS level\'s BLASTER in the right hand (STAGE_BLASTER: SETCURRENTITEM BLASTER, PLACEITEM RTHAND)')
    r.stage_block(BLASTER, 'STAGE_BLASTER')
    r.tick(5)
    ride_elevator(r, 'SWITCHTOCONTROLLEVEL', 'CONTROL')
    ran = {e[1] for e in r.world.log}
    r.checkpoint('control-arrival', caller_tail=sorted(ran & {'EXITSTASIS', 'ELEVATOR_DOOR_OPEN', 'ACTIVATE_GRDCON'}),
                 door_open=r.vm.globals.get('_dr9_space'), lex_con_loc=r.vm.globals.get('_lexconloc'))
    # MECHO2 guards the elevator door (CMECH1A / 1B lie inside INELC, AI_MECH2.scr:9-19, 55-90). By keys Lex is knocked into
    # recoil / fall motions by every bolt and dies before he can aim (base.md, blocker list), so the fight's outcome is staged.
    r.shortcut('fight-outcome', fight='MECHO2', outcome='MECHO2_DEATH (AI_MECH2.scr:136), as the blaster\'s hits end it')
    r.vm.fire('MECHO2_DEATH')
    r.until('MECHO2_DEATH and the taunt', lambda: not r.running('LEXTAUNTSMECHO2') and not r.running('MECHO2_DEATH'), 900)
    r.checkpoint('mecho2', alive=r.vm.globals.get('_mecho2_alive'), hp_after_arrival=r.lex_hits[:3])
    # the operating room: OPENTER runs OPRSCENE once (MASTABA.scr:3-32, 262-330)
    t = next(t for t in r.world.triggers if t['name'] == 'OPENTER')
    centre = (np.asarray(t['lo'], float) + np.asarray(t['hi'], float)) / 2
    r.set_pos((centre[0], centre[1] - 1800), heading=180, why='in front of the operating room (OPENTER, MASTABA.scr:15)')
    play = r.play()
    play.walk_to(centre[0], centre[1], radius=300)
    r.until('OPRSCENE: the guard is called', lambda: r.world.figure('GRDOP').go is not None, 3000)
    r.unstick('GRDOP', 'OPRSCENE: GO OPRGD1 WALK (MASTABA.scr:134)')
    r.until('OPRSCENE: Mastaba, Dane, the fade', lambda: r.vm.globals.get('_operate_done') == 1, 6000)
    r.until('OPRSCENE ends', lambda: not r.running('OPRSCENE') and not r.running('OPENTER'), 3000)
    r.checkpoint('operating-room', operate_done=r.vm.globals.get('_operate_done'), lex_motion=r.lex.motion, lex_frozen=r.lex.frozen,
                 blasters=[k for k, i in r.world.items.items() if i.type == 'BLASTER'],
                 scene=[b for _, b in r.blocks if b.startswith(('OPR', 'MAS', 'DANE', 'KILL_MECHO2', 'READY_MARINE1'))])
    return r


# ---------------------------------------------------------------------------------------------------------------- TOWER
ROUTE_TO_GUN = ((29500, -56700), (25500, -56700), (25500, -64600), (46000, -64600), (52000, -59000), (54165, -55815))


def aim_gun(r, target):
    """Hold KP4 (SWIVELGUNLEFT: _GN1_FRAME + 1) or KP6 (SWIVELGUNRIGHT: - 1) until _GN1_FRAME reaches `target` (MANAGEGUN polls
    ISKEYPRESSED, TOWERGUN.scr:35-74, 135-150)."""
    w, vm = r.world, r.vm
    for _ in range(40):
        frame = vm.globals.get('_gn1_frame', 0)
        if frame == target:
            return
        scan = KP4 if frame < target else KP6
        w.key_down(scan)
        r.tick(2)
        w.key_up(scan)
        r.tick(1)


def first_hit_window(ship):
    """TESTFIRSTHIT's gun + ship sums (TOWERGUN.scr:586-620)."""
    return (61, 64) if ship < 51 else (63, 66) if ship < 56 else (60, 63)


def tower():
    """CONTROL → elevator → TOWER, across the deck to the gun, Roland's gun restart (staged), both landers with real gun keys."""
    r = Run('tower', 'CONTROL')
    r.create_lex('ELC')
    r.tick(5)
    ride_elevator(r, 'SWITCHTOTOWERLEVEL', 'TOWER', on_arrival=tower_hold_fire)
    return tower_deck(r)


TOWER_BOTS = ['TOWBOT%d' % i for i in range(1, 7)]


def tower_hold_fire(r):
    """The first tick in TOWER: the tower bots' AI off (shortcut 'hold-fire'), as the arrival's bolts kill a standing Lex."""
    for n in TOWER_BOTS:
        if r.world.figure(n) is not None:
            r.world.cmd_ai(r.world.figure(n), False)
    r.shortcut('hold-fire', figures=TOWER_BOTS)


def tower_deck(r, restart_gun=None):
    """From the arrival in ELT (bots held): across the deck to the gun, Roland's gun restart (staged, or `restart_gun(r)` before the bots wake), both landers with real gun keys."""
    bots = TOWER_BOTS
    r.checkpoint('tower-arrival', stage=r.vm.globals.get('_lander_stage'))
    play = r.play()
    reached = all(play.walk_to(x, y, radius=600, run=True) for x, y in ROUTE_TO_GUN)
    if restart_gun is not None:
        restart_gun(r)
    for n in bots:
        if r.world.figure(n) is not None:
            r.world.cmd_ai(r.world.figure(n), True)
    r.checkpoint('at-gun', reached=reached, stage=r.vm.globals.get('_lander_stage'), hits=len(r.lex_hits))
    if restart_gun is None:
        r.set_globals(_GunActive=1)
        r.shortcut('fight-outcome', fight='Roland', outcome='_GunActive = 1 (AI_ROLAN.scr:365, his restart after Lex beats him)')
    r.set_pos((54165, -55815), heading=-90, why='BIG_GUN use position (GUNHERE)')
    play.key(SPACE)
    r.until('BIG_GUN_USE: at the gun', lambda: r.vm.globals.get('_lexatgun') == 1, 300)
    # ship 1: TESTFIRSTHIT wants _GN1_FRAME + ship frame in its window (TOWERGUN.scr:586-620); ship 2: _GN1_FRAME 6-8, rise > 17
    r.until('ship 1 crosses', lambda: r.vm.globals.get('_lnd2_frame', 0) > 40 or r.vm.globals.get('_lander_stage', 0) >= 4, 4000)
    shots = 0
    while r.vm.globals.get('_firstlanderalive') == 1 and r.vm.globals.get('_lnd2_frame', 0) < 60 and shots < 12:
        ship = r.vm.globals.get('_lnd2_frame', 0)
        lo, hi = first_hit_window(ship)
        aim_gun(r, max(1, min(16, (lo + hi) // 2 - ship)))
        ship = r.vm.globals.get('_lnd2_frame', 0)
        lo, hi = first_hit_window(ship)
        if lo <= r.vm.globals.get('_gn1_frame', 0) + ship <= hi:            # FIREGUN tests the frames when the key arrives
            r.key_event(SPACE)
            shots += 1
            r.until('gun shot', lambda: r.vm.globals.get('_incutscene', 0) == 0, 300)
        else:
            r.tick(1)
    r.checkpoint('first-lander', alive=r.vm.globals.get('_firstlanderalive'), shots=shots)
    # CELEBRATE (TOWERGUN.scr:720) CALLs RELEASEGUN and starts TWR_VICTORY in the next walk after it returns (1238:077f): wait for both
    r.until('ship 2 comes in', lambda: r.vm.globals.get('_lander_stage', 0) >= 4 and not r.running('RELEASEGUN') and not r.running('CELEBRATE'), 3000)
    if r.vm.globals.get('_lexatgun') != 1:                  # CELEBRATE / RELEASEGUN took Lex off the gun: mount it again
        r.release_motion('CELEBRATE')
        play.key(SPACE)
        r.until('BIG_GUN_USE again', lambda: r.vm.globals.get('_lexatgun') == 1, 300)
    aim_gun(r, 7)                                             # GETSECONDSHIPHITSTATE: _GN1_FRAME 6-8 (TOWERGUN.scr:667-671)
    r.until('ship 2 rises', lambda: r.vm.globals.get('_rise_frame', 0) > 17 or r.vm.globals.get('_lander_stage', 0) >= 5, 4000)
    shots2 = 0
    while r.vm.globals.get('_secondlanderalive') == 1 and 17 < r.vm.globals.get('_rise_frame', 0) < 33 and shots2 < 8:
        r.key_event(SPACE)
        shots2 += 1
        r.until('gun shot', lambda: r.vm.globals.get('_incutscene', 0) == 0, 300)
    r.until('stage 5', lambda: r.vm.globals.get('_lander_stage', 0) >= 5, 1500)
    r.checkpoint('second-lander', alive=r.vm.globals.get('_secondlanderalive'), shots=shots2, stage=r.vm.globals.get('_lander_stage'))
    return r


# ---------------------------------------------------------------------------------------------------------------- PLATFORM
# Lex waits at the first point: the Elite walks to him and its attack makes the contact. With a second point 9000 units further south he stood in
# the Elite's way to FELITE (the push of FUN_1088_3629 deflected its GO RUN for good) after a motion's first update began to move by frame 0's root.
ROUTE_TO_ELITE = ((10000, -162500),)


def platform():
    """Zero-g room → TO_FINAL → PLATFORM (the caller walks Lex to WALKHERE after its LOADLEVEL), the city scene, the Elite's battery."""
    r = Run('platform', 'TUNROOM')
    r.create_lex('GFROMFIN')
    r.shortcut('trigger', trigger='TO_FINAL (zero-g room exit, TUN2PLAT.scr:2)')
    r.world.spawn_for(r.lex, 'TO_FINAL')
    r.until('TO_FINAL: arrive and walk to WALKHERE', lambda: r.world.level == 'PLATFORM' and not r.running('TO_FINAL'), 900)
    return platform_city(r)


# The city monitor: visit all 20 hexes (_City_Total = 20) without a trap edge or a repeat, from hex 1: 1 2 3 5 6 7 8 13 17 16 12 11 15 19 20 18 14 10 9 4 (the table in
# PROCESS_RESULT, CITYMON.scr:668-1283). A button's direction turns with the hex you came from (DETERMINE_DIRECTION), hence these colours.
CITY_PRESSES = ('GRNB', 'REDB', 'BLUB', 'REDB', 'GRNB', 'REDB', 'BLUB', 'YELB', 'REDB', 'PURB', 'REDB', 'YELB', 'PURB', 'YELB', 'ORGB', 'BLUB', 'YELB', 'GRNB', 'YELB')


def platform_city(r, outer=None):
    """From the arrival in PLATFORM (TO_FINAL has walked Lex to WALKHERE): the city monitor (solved by clicks when attached, else staged), the city scene, the Elite and
    its battery."""
    walkhere = r.world.arrival_point('WALKHERE')[0]
    # `GO WALKHERE WALK` ends within the GO radius (614) of its target and does not snap onto it (10e0:1a4c)
    gap = float(np.hypot(*(r.lex.pos[:2] - walkhere)))
    r.checkpoint('platform-arrival', at_walkhere=bool(gap < worldmod.GO_RADIUS), walkhere_gap=gap,
                 to_final_tail=[e[3] for e in r.world.log if e[1] == 'TO_FINAL'][-4:])
    if outer is None:
        c = r.world.arrival_point('CTYMON')[0]
        r.set_pos((c[0], c[1] - 800), heading=0, why='the city monitor CTYMON (from the battle room through PLTDOOR)')
    if outer is None:
        r.set_globals(_city_solved=1)
        r.shortcut('trigger', trigger='CITY_MONITOR solved: PROCESS BRINGONTHEALIEN (CITYMON.scr:1376-1395)')
        r.vm.fire('BRINGONTHEALIEN')
    else:
        if outer.use() != 'CTYMON_USE':
            raise Stuck('Space at the city monitor did not run CTYMON_USE')
        outer.until(lambda: r.world.monitor is not None, 300, 'the city monitor opens')
        outer.tick(30)                                              # STARTLOOP flashes the traps
        for name in CITY_PRESSES:
            outer.click(name)
        outer.until(lambda: r.vm.globals.get('_city_solved') == 1, 300, 'the city puzzle is solved')
    r.until('plt0 flic', lambda: r.world.flic is not None, 300)
    r.until('city scene', lambda: not r.running('BRINGONTHEALIEN'), 3000)
    elite = r.world.figure('ELITE')
    r.checkpoint('city-seen', city_seen=r.vm.globals.get('_alien_city_seen'), elite_ai=r.world.ai_active(elite),
                 elite=elite.pos.astype(int).tolist())
    # The Elite walks to Lex by itself (GO PELITE / GO FELITE RUN keep its gravity-off height, so it is not buried in PLAT03) and its attack
    # makes the contact: ELITE_STIMULUS runs from the hit, no staging
    start = elite.pos.copy()
    play = r.play()
    for x, y in ROUTE_TO_ELITE:
        reached = play.walk_to(x, y, radius=500)
        if r.ran('ELITE_STIMULUS'):
            break
    for _ in range(300):
        if r.ran('ELITE_STIMULUS'):
            break
        r.tick()
    else:                                                            # its attack fell short of where he stopped: step up to it, as a player would
        play.walk_to(*elite.pos[:2], radius=1500)
    r.until('the Elite reaches Lex: ELITE_STIMULUS', lambda: r.ran('ELITE_STIMULUS'), 600)
    r.checkpoint('near-elite', reached=reached, distance=float(np.hypot(*(elite.pos[:2] - r.lex.pos[:2]))),
                 elite_moved=float(np.hypot(*(elite.pos[:2] - start[:2]))), elite_z=int(elite.pos[2]), elite_motion=elite.motion)
    r.until('the Elite gives the battery', lambda: r.vm.globals.get('_gave_alien_battery') == 1, 4000)
    r.until('the Elite leaves', lambda: not r.running('ELITE_STIMULUS'), 3000)
    battery = {k: (i.type, i.owner, i.slot, list(r.vm.objects.get(k, []))) for k, i in r.world.items.items() if i.type == 'ALBAT'}
    r.checkpoint('battery', battery=battery, gave=r.vm.globals.get('_gave_alien_battery'), lex_motion=r.lex.motion)
    return r


# ---------------------------------------------------------------------------------------------------------------- ENDING
BLASTER = """{ STAGE_BLASTER
	SETCURRENTFIGURE ( PLAYER )
	SETCURRENTITEM ( BLASTER )
	PLACEITEM RTHAND
}"""

ALIEN_BATTERY = """{ STAGE_ALIEN_BATTERY
	SETCURRENTFIGURE ( PLAYER )
	CREATEITEM ALBAT
	INDIVIDUALIZE CURITEM ABAT_500
	CURITEM.~0 = 500
	CURITEM.~1 = 500
	CURITEM.~2 = _ABAT_500
	CURITEM.~3 = 1
	PLACEITEM RTHAND
}"""

LOWER_GARAGE = """{ STAGE_LOWER_GARAGE
	SETCURRENTFIGURE PLAYER
	AI OFF
	WAIT 20
	MOTION WALK_BACK CONTINUE
	WAIT 20
	CALL LOWER_GARAGE_ELEVATOR
}"""

LIFT_TOP = (44000.0, -60000.0)              # on QSF, over the garage lift ELV (test_floors.PLAYER_POS)
BIKE = (51650, -44700)


def ending():
    """LANDPAD → elevator → CONTROL with the alien battery, the garage lift, the bike (both uses), OUTAHERE_USE, ENDGAME in TITLE,
    the end flic and its sounds, ROLLCREDITS (the credits roll over the flic until CREDITSSTATE 2), then ENDGAME's WAIT 5 SECONDS, LEAVEGAME and EXIT."""
    r = Run('ending', 'LANDPAD')
    r.create_lex('ELV')
    r.set_globals(_alien_city_seen=1, _Grav_Solved=1, _gave_alien_battery=1, _escher_dead=1)
    r.shortcut('item', block='AI_ELITE.scr:177-183 (CREATEITEM ALBAT, INDIVIDUALIZE, charge / max / type / alien flag)')
    r.stage_block(ALIEN_BATTERY, 'STAGE_ALIEN_BATTERY')
    r.tick(2)
    ride_elevator(r, 'SWITCHTOCONTROLLEVEL', 'CONTROL')
    r.checkpoint('control-arrival', door_open=r.vm.globals.get('_dr9_space'))
    r.set_pos(LIFT_TOP, heading=0, why='the control room over the garage lift')
    r.shortcut('trigger', trigger='CR_HANGERMONITOR ICARUS ACCESS (AIAB): its tail (CONCNTRL.scr:372-381)')
    r.stage_block(LOWER_GARAGE, 'STAGE_LOWER_GARAGE')
    r.until('LOWER_GARAGE_ELEVATOR', lambda: r.vm.globals.get('_seen_mach_shop') == 1, 1500)
    r.checkpoint('garage', z=int(r.lex.pos[2]))
    return ending_bike(r)


def ending_bike(r):
    """From Lex in the garage (the lift is down, the Elite's battery in his right hand): the bike with both batteries, OUTAHERE_USE, ENDGAME,
    the end flic, ROLLCREDITS, its roll to CREDITSSTATE 2 and the 5 s wait: LEAVEGAME and EXIT."""
    play = r.play()
    reached = play.walk_to(*BIKE, radius=500)
    gift = next((i for i in r.world.items.values() if i.name == 'ABAT_500'), None)     # the Elite's gift, in Lex's right hand; the full run has it in his leg, as MY_BATTERY
    r.checkpoint('alien-battery-held', gift=gift and (gift.key, gift.owner, gift.slot, r.vm.objects[gift.key][0]))
    play.key(SPACE)
    r.until('BIKE_USE: take out the old battery', lambda: r.vm.globals.get('_battery_in_bike') == 0 and not r.running('BIKE_USE'), 600)
    # both batteries are named ABAT_500 (the Elite's gift, AI_ELITE.scr:175, and the bike's old one after RESTOREALIASOFBATTERY): the
    # charge tells them apart (the gift 500, the old one 150, CONMACH.scr:43)
    batteries = lambda: [i for i in r.world.items.values() if i.name == 'ABAT_500']
    charge = lambda i: r.vm.objects[i.key][0]
    old = next((i for i in batteries() if charge(i) == 150), None)
    r.checkpoint('old-battery', reached_bike=reached, old=old and (old.key, old.owner, old.slot, list(r.vm.objects.get(old.key, []))),
                 batteries=[(i.key, i.owner, i.slot, charge(i)) for i in batteries()], lex_motion=r.lex.motion)
    r.release_motion('BIKE_USE')
    play.tick(5)
    if gift is None:                                                    # away from the bike, Space with the old battery swaps it for the one in the leg (REPLACEBATTERYINLEG)
        play.walk_to(BIKE[0], BIKE[1] + 2500, radius=500)
        n = len(r.world.key_log)
        play.key(SPACE)                                                 # the old battery is the one Lex left in the bike (CONTROL keeps it): BAT_100_USE, or ABAT_500_USE
        uses = ('ABAT_500_USE', 'BAT_100_USE')
        r.until('the gift back out of the leg', lambda: any(e[1] == 'use' and e[2] in uses for e in r.world.key_log[n:]) and not any(r.running(u) for u in uses)
                and r.lex.ai_enabled, 500)
        alien = r.world.held_item(r.lex, 'RTHAND')                      # no longer 500: the suit and BIOREPAIR drew on it
    else:
        play.key(ENTER)                                                 # put the old battery down
        play.tick(60)
        alien = next(i for i in batteries() if charge(i) == 500)
        for _ in range(4):                                              # walk up to the alien battery until Enter would take it
            cand = r.world.pickup_candidate(r.lex)
            if cand is alien:
                break
            play.walk_to(alien.pos[0], alien.pos[1], radius=900)
            play.face(r.heading_to(alien.pos), tolerance=6)
            play.tick(5)
        play.key(ENTER)                                                 # pick up the alien battery
        play.tick(60)
    r.checkpoint('alien-battery-in-hand', held=(alien.owner, alien.slot))
    play.walk_to(*BIKE, radius=400)
    play.key(SPACE)
    r.until('BIKE_USE → OUTAHERE_USE → ENDGAME', lambda: r.world.level == 'TITLE', 3000)
    r.checkpoint('endgame', battery_in_bike=r.vm.globals.get('_battery_in_bike'), endgame_alive=r.running('ENDGAME'))
    r.until('the end flic and ROLLCREDITS', lambda: r.ran('ROLLCREDITS'), 2400)
    r.checkpoint('credits', flic=r.world.flic and r.world.flic.name, options=r.world.options and r.world.options.screen,
                 credits_state=r.world.credits_state(), keyboard_captured=r.world.keyboard_captured)
    if r.world.options is None or r.world.options.screen != 'credits':
        r.problem('missing', 'ROLLCREDITS: MON_CODE _OPTS_CREDITS did not open the credits page')
    rolling = r.world.credits_state()
    r.tick(2)
    r.checkpoint('credits-rolling', state=(rolling, r.world.credits_state()), paused=r.world.paused, frozen=bool(r.world.frozen))
    if r.world.credits_state() != 1:
        r.problem('wrong', f'ROLLCREDITS: CREDITSSTATE {r.world.credits_state()} two ticks into the roll, expected 1')
    r.until('the credits to finish (CREDITSSTATE 2)', lambda: r.world.credits_state() == 2, 3000)
    r.checkpoint('credits-done', credits_pos=r.world.options and r.world.options.credits_pos, state=r.world.credits_state())     # the page can close in the tick the state reaches 2
    r.until('ENDGAME: WAIT 5 SECONDS, LEAVEGAME and EXIT', lambda: r.world.exit_requested, 600)
    r.checkpoint('exit', flic=r.world.flic is not None, frozen=bool(getattr(r.world, 'frozen', False)),
                 keyboard_captured=r.world.keyboard_captured)
    return r


SEGMENTS = (('control-first', control_first), ('tower', tower), ('platform', platform), ('ending', ending))


def run_all(out_dir=None):
    reports = {}
    for name, fn in SEGMENTS:
        reports[name] = fn().report()
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
        with open(os.path.join(out_dir, 'playthrough_base.json'), 'w', encoding='utf-8') as handle:
            json.dump(reports, handle, indent=1, sort_keys=True)
    return reports


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--out', default=os.path.join(os.path.dirname(os.path.dirname(HERE)), 're', 'out', 'playthrough'))
    args = ap.parse_args()
    for name, rep in run_all(args.out).items():
        print(f'== {name}: tick {rep["tick"]}, level {rep["level"]}, {len(rep["shortcuts"])} shortcuts, {len(rep["problems"])} problems')
        for point in rep['checkpoints']:
            print('  ', point['name'], {k: v for k, v in point.items() if k not in ('name', 'items', 'player', 'tick', 'level', 'camera')})
        for p in rep['problems']:
            print('   !', p['kind'], p['text'])


if __name__ == '__main__':
    main()
