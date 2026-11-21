"""Deterministic script-and-world scenarios for cross-level regression checks.

Run from the repository root:
    re/.venv/bin/python -I re/interp/scenarios.py --out re/out/scenarios
"""
import argparse
import collections
import json
import os
import sys
import math
import random

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import monitor as monitor_mod  # noqa: E402
import vm as vmmod  # noqa: E402
import world as worldmod  # noqa: E402


def tick(world, vm, count, controls=None):
    """Advance the normal VM/world frame loop, optionally changing held input per tick."""
    for index in range(count):
        if controls is not None:
            world.set_player_input(**controls(index))
        vm.tick_once()
        world.step()
        world.choose_default_difficulty()


def plain(value):
    """Make engine data suitable for a stable JSON manifest."""
    if isinstance(value, np.ndarray):
        return [plain(v) for v in value.tolist()]
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, tuple):
        return [plain(v) for v in value]
    if isinstance(value, list):
        return [plain(v) for v in value]
    if isinstance(value, dict):
        return {str(k): plain(v) for k, v in value.items()}
    return value


def command_counts(world):
    return dict(sorted(collections.Counter(record[3] for record in world.log).items()))


def checkpoint(world, vm, name, frame=False):
    player = world.player()
    return {
        'name': name,
        'tick': vm.tick,
        'level': world.level,
        'camera': world.current_camera(),
        'player': None if player is None else {
            'name': player.name,
            'position': plain(player.pos),
            'motion': player.motion,
            'collisions': player.collisions,
        },
        'figures': {name: {'type': figure.type, 'position': plain(figure.pos),
                           'motion': figure.motion, 'collisions': figure.collisions,
                           'view_cams': figure.view_cams}
                    for name, figure in sorted(world.figures.items())},
        'items': {name: {'type': item.type, 'owner': item.owner, 'slot': item.slot}
                  for name, item in sorted(world.items.items())},
        'frame': world.render() if frame else None,
    }


# The opening scenarios are timed from the first CHAOS LOADLEVEL (the anchor): the intro movie and its fades now run first, so a tick count from
# the boot no longer means anything. The pre-intro port reached CHAOS in the tick numbered 26 (27 ticks run), so an old absolute tick T is
# `anchor + (T - 26)`: `old_ticks(T)` = the ticks to run after `boot_opening()` to be where the old port was after T ticks.
OLD_ANCHOR_TICKS = 27


def old_ticks(count):
    return count - OLD_ANCHOR_TICKS


# `MOTION ... FREEZE` blocks its caller until the motion ends (10d0:5e8b/6083; NOTES "Movement fixes"). The opening has two: STARTUPFIRSTBOT's
# `MOTION DEACTIVATED SNAP_TO FREEZE` (15 ticks) and GOODMORNINGLEX's `MOTION WAKE_UP_HEAD FREEZE` (39 ticks), so every opening event from the
# nurse's ACTIVATE on comes 54 ticks later than the old port had it (checked tick by tick: WAKE_UP_HEAD 7149 -> 7164, ACTIVATE 7179 -> 7233,
# Lex stands 7588 -> 7642 ... all by 54 from ACTIVATE on).
FREEZE_SHIFT = 54
# SMALL_QUAKE's STOPAMBIENT lets the quake loop play out, and AWAKEN waits on its handle (1000:046f; NOTES "Released loops play their tail"): from
# the quake on every opening event comes 52 ticks later again (WAKE_UP_HEAD 7164 -> 7216, ACTIVATE 7233 -> 7285). Live, SMALL_QUAKE lasts 187-225
# clock ticks; the port, 224.
QUAKE_TAIL_SHIFT = 52


def opening_ticks(count):
    """Ticks to run after `boot_opening()` to be where the old port was at tick `count`, for an old tick after the nurse's ACTIVATE (the anchors of the
    CHAOS cell scenarios): `old_ticks` plus FREEZE_SHIFT and QUAKE_TAIL_SHIFT."""
    return old_ticks(count) + FREEZE_SHIFT + QUAKE_TAIL_SHIFT


def boot_opening(max_ticks=40000):
    """A new game: TITLE, GAME fired, the intro played (no key pressed) up to and including the tick of the first CHAOS LOADLEVEL."""
    world = worldmod.World('TITLE', state_dir=worldmod.INITGAME)
    vm = vmmod.VM(world)
    vmmod.load_level(vm, 'TITLE')
    world.fire_event('TITLE_LOAD')
    vm.fire('GAME', 'global')
    while not world.level_loads and vm.tick < max_ticks:
        tick(world, vm, 1)
    return world, vm


def opening_escape():
    """Boot the original opening, prove unarmed input is inert, then leave the cell."""
    world, vm = boot_opening()
    tick(world, vm, opening_ticks(1170))      # Lex stands from old tick 1155 (OUT_OF_BED ends; the quake ramps hold AWAKEN 30 ticks)
    ready = vm.tick
    # This is the preview's explicit handoff from the scripted opening shot to
    # automatic room cameras.  It makes the manual escape exercise camera boxes.
    world.script_auto = True
    world.set_camera('CE31', 'scenario handoff')
    # The cell bars are live: walking through DR3 enters the DR_ZAP3 trigger, which shocks Lex back (as in the
    # original). Switching them off lets the walk exercise the corridor camera boxes.
    vm.globals['_bars3_on'] = 0
    result = [checkpoint(world, vm, 'opening-ready', frame=True)]
    world.set_player_input(attack=True)
    tick(world, vm, 1)
    result.append(checkpoint(world, vm, 'unarmed-space'))
    # The nurse (alive, PERSONAL_RADIUS 55) pushes Lex away when he passes within their summed radius
    # (FUN_1088_3629), which carries his straight walk across to the DR3 doorway.
    tick(world, vm, 180, lambda _: {'forward': 1})
    world.set_player_input()
    tick(world, vm, 1)
    result.append(checkpoint(world, vm, 'outside-cell', frame=True))
    return scenario_result('opening_escape', world, vm, result, [
        {'tick': ready, 'attack': True},
        {'start_tick': ready + 1, 'end_tick': ready + 181, 'forward': 1},
        {'tick': ready + 181, 'forward': 0},
    ])


def opening_revival(max_ticks=10000):
    """Let the live nurse AI land two syringes and run the script revival path."""
    world, vm = boot_opening()
    result = []
    for _ in range(max_ticks):
        vm.tick_once()
        world.step()
        world.choose_default_difficulty()
        if vm.globals.get('_lexrevived') == 1:
            break
    result.append(checkpoint(world, vm, 'after-revival', frame=True))
    return scenario_result('opening_revival', world, vm, result)


def opening_nurse_defeat():
    """Real attack input and authored defeat scripts, with logged encounter poses."""
    return nurse_defeat_run()[2]


def nurse_defeat_run():
    """The nurse encounter itself -> (world, vm, report): the world and VM are left running at the end (Lex in the BLK1
    corridor at full health), which the CHAOS encounters after it continue from."""
    world, vm = boot_opening()
    tick(world, vm, opening_ticks(1170))
    lex, bot = world.player(), world.figures['FIRSTBOT']
    inputs = []

    def key(scan, mods=0, count=1):
        inputs.append({'tick': vm.tick, 'scan': scan, 'mods': mods, 'ticks': count})
        world.key_down(scan, mods)
        tick(world, vm, count)
        world.key_up(scan, 0)
        tick(world, vm, 1)

    key(0x2e)                                               # C: enter combat
    tick(world, vm, 20)
    bot.heading, lex.heading = 0, 180
    bot.pos[:2], lex.pos[:2] = (-10000, -11000), (-10000, -12000)
    fixtures = [{'stage': 'front', 'tick': vm.tick, 'figures': {
        'FIRSTBOT': {'position': plain(bot.pos), 'heading': bot.heading},
        'LEX': {'position': plain(lex.pos), 'heading': lex.heading},
    }}]
    key(0x48, worldmod.keys_mod.ALT)                          # Alt+KP8: overhead punch
    tick(world, vm, 40)
    front = {'hits': plain(world.hits), 'wound': vm.objects['FIRSTBOT'][4]}
    for _ in range(200):
        if bot.motion == 'DEFEND' and lex.motion == 'STAND':
            break
        tick(world, vm, 1)
    heading = math.radians(bot.heading)
    lex.heading = bot.heading
    lex.pos[:2] = bot.pos[:2] + (1000 * math.sin(heading), 1000 * math.cos(heading))
    fixtures.append({'stage': 'rear', 'tick': vm.tick, 'figures': {
        'LEX': {'position': plain(lex.pos), 'heading': lex.heading},
    }})
    key(0x48, worldmod.keys_mod.ALT)
    tick(world, vm, 40)
    rear = {'hits': plain(world.hits[len(front['hits']):]), 'status': vm.objects['FIRSTBOT'][3],
            'wound': vm.objects['FIRSTBOT'][4], 'bouncy': bot.bouncy, 'motion': bot.motion}
    tick(world, vm, 100)
    result = [checkpoint(world, vm, 'nurse-bouncing', frame=True)]

    # Steer Lex behind the wounded nurse and push it through DR_ZAP3 using
    # ordinary movement input.  The target is the original controller's live
    # bar-contact point; neither the nurse nor Lex is repositioned here.
    if lex.combat:
        key(0x2e)
    push_steps = []
    best_bar_distance, stalled_pushes = float('inf'), 0
    zap_trigger = next((index for index, trigger in enumerate(world.triggers)
                        if trigger['name'] == 'DR_ZAP3'), None)
    entered_zap_trigger = False
    for _ in range(600):
        if 'FIRSTBOT' not in world.figures or vm.objects['LEX'][0] < 100:
            break
        if bot.motion == 'ZAPPED':
            break
        dx, dy = -10090 - bot.pos[0], -15100 - bot.pos[1]
        distance = math.hypot(dx, dy)
        if not distance:
            break
        if distance < best_bar_distance:
            best_bar_distance, stalled_pushes = distance, 0
        else:
            stalled_pushes += 1
            if stalled_pushes >= 100:
                break
        toward_bars = np.array((dx, dy)) / distance
        relative = float(np.dot(lex.pos[:2] - bot.pos[:2], toward_bars))
        # Keep Lex on the far side of the nurse before aiming through it.  The
        # prototype's equal-radius resolver can otherwise let Lex cross the
        # nurse, after which its next push moves the nurse away from the bars.
        mode = 'push' if relative < -1000 else 'realign'
        x, y = bot.pos[:2] + toward_bars * (500 if mode == 'push' else -3000)
        desired = math.degrees(math.atan2(lex.pos[0] - x, lex.pos[1] - y))
        delta = (desired - lex.heading + 180) % 360 - 180
        if abs(delta) <= 18:
            scan, count = 0x48, 10        # a fresh press starts WALK, whose frame 0 jumps (-20, -180): shorter pushes
        else:
            scan, count = (0x4d if delta > 0 else 0x4b), 6
        mods = worldmod.keys_mod.SHIFT if mode == 'realign' and scan == 0x48 else 0
        push_steps.append({'nurse_xy': plain(bot.pos[:2]), 'desired': desired,
                           'delta': delta, 'scan': scan, 'ticks': count,
                           'mode': mode, 'mods': mods, 'lex_xy': plain(lex.pos[:2])})
        key(scan, mods, count)
        tick(world, vm, 1)
        entered_zap_trigger = entered_zap_trigger or bool(
            zap_trigger is not None and bot.in_trig is not None and bot.in_trig[zap_trigger])
    saw_zap, zap_guard_values, max_zap_processes = False, [], 0
    for _ in range(900):
        tick(world, vm, 1)
        entered_zap_trigger = entered_zap_trigger or bool(
            zap_trigger is not None and bot.in_trig is not None and bot.in_trig[zap_trigger])
        saw_zap = saw_zap or bot.motion == 'ZAPPED'
        max_zap_processes = max(max_zap_processes, sum(
            not proc.done and proc.block.name.upper() == 'DR_ZAP3_FIRSTBOT' for proc in vm.procs.values()))
        if saw_zap:
            zap_guard_values.append(vm.globals.get('_enemy_process'))
        if 'FIRSTBOT' not in world.figures:
            break
    result.append(checkpoint(world, vm, 'nurse-defeated', frame=True))
    initial_health = vm.objects['LEX'][0]
    for _ in range(90):
        if lex.motion in ('STAND', 'ATK_STAND'):
            break
        tick(world, vm, 1)
    if lex.combat:
        key(0x2e)
    waypoint = 0                                            # 0: stage in front of DR3, 1: dash through the bars
    bars_was_on = bars_ready = False
    for _ in range(100):
        if vm.objects['LEX'][0] < initial_health or waypoint == 2:
            break
        x, y = [(-10090, -13200), (-10090, -17100)][waypoint]
        dx, dy = x - lex.pos[0], y - lex.pos[1]
        distance = math.hypot(dx, dy)
        if distance < 350:
            waypoint += 1
            continue
        delta = (math.degrees(math.atan2(-dx, -dy)) - lex.heading + 180) % 360 - 180
        if abs(delta) > 20:                                 # a turn tap overshoots by up to ~20 degrees: walk on smaller errors
            scan = 0x4d if delta > 0 else 0x4b
            count = round(min(.3, max(.2, abs(delta) / 90)) * 30)
        else:
            scan, count = 0x48, round(min(.5, max(.3, distance / 5000)) * 30)
            if waypoint == 1 and lex.pos[1] > -16000:
                bars = bool(vm.globals['_bars3_on'])
                bars_ready = bars_was_on and not bars or (bars_ready and not bars)   # a fresh observed on -> off transition
                bars_was_on = bars
                if not bars_ready:
                    tick(world, vm, 8)
                    continue
        key(scan, worldmod.keys_mod.SHIFT if waypoint == 1 and scan == 0x48 else 0, count)
        tick(world, vm, 4)
    escaped = bool(lex.pos[1] < -16500 and world.current_camera().startswith('BLK')
                   and vm.objects['LEX'][0] == initial_health)
    result.append(checkpoint(world, vm, 'after-corridor-attempt', frame=True))
    report = scenario_result('opening_nurse_defeat', world, vm, result, inputs)
    report['encounter'] = {'front': front, 'rear': rear, 'saw_zap': saw_zap,
                           'bot_blown': vm.globals.get('_bot_blown'),
                           'nurse_removed': 'FIRSTBOT' not in world.figures,
                           'nurse_health': vm.objects['FIRSTBOT'][0], 'fixtures': fixtures,
                           'push_steps': push_steps,
                           'closest_bar_distance': best_bar_distance,
                           'stalled_pushes': stalled_pushes,
                           'entered_zap_trigger': entered_zap_trigger,
                           'zap_guard_values': sorted(set(zap_guard_values)),
                           'max_zap_processes': max_zap_processes,
                           'escaped': escaped, 'lex_health': vm.objects['LEX'][0],
                           'total_ticks': vm.tick,
                           'explosion_debris_rendered': False}
    return world, vm, report


class Stuck(Exception):
    """A segment could not make progress; the message says what it waited for."""


class Play:
    """Real-key driver shared by the CHAOS encounters: held keys go through World.key_down / key_up, steering and fighting read the
    figures' state like the nurse scenario's loop. Every key lands in `inputs`; the script blocks that run are noted in `blocks`."""
    BUSY = ('ATK_H', 'ATK_F', 'RECOIL', 'SUPER', 'SHOCK', 'ATK_M')      # Lex's one-shot motions that own him until they end
    REACH = 1650                                  # centre distance below which a punch can reach: just inside the summed push radii

    def __init__(self, world, vm, inputs=None):
        self.world, self.vm, self.lex = world, vm, world.player()
        self.inputs = [] if inputs is None else inputs
        self.blocks, self._seen = [], set()      # (tick, block name) of every script process that ran, first sighting only

    def tick(self, count=1):
        for _ in range(count):
            tick(self.world, self.vm, 1)
            for proc in self.vm.procs.values():
                name = proc.block.name.split('(')[0]          # stimulus blocks are named 'X_STIMULUS(' with their argument list
                if not proc.done and name != 'TIMED' and name not in self._seen:
                    self._seen.add(name)
                    self.blocks.append((self.vm.tick, name))

    def key(self, scan, mods=0, count=1):
        for _ in range(240):                      # the random tremors (LEVEL1TREMORS) shake Lex with AI off: a key does nothing until QUAKE ends
            if self.lex.motion != 'QUAKE':
                break
            self.tick(1)
        self.inputs.append({'tick': self.vm.tick, 'scan': scan, 'mods': mods, 'ticks': count})
        self.world.key_down(scan, mods)
        self.tick(count)
        self.world.key_up(scan, 0)
        self.tick(1)

    def delta(self, heading):
        return (heading - self.lex.heading + 180) % 360 - 180

    def face(self, heading, tolerance=12):
        for _ in range(40):
            delta = self.delta(heading)
            if abs(delta) <= tolerance:
                return
            self.key(0x4d if delta > 0 else 0x4b, 0, round(min(.3, max(.2, abs(delta) / 90)) * 30))

    def walk_to(self, x, y, radius=350, run=False, steps=200):
        """Turn taps and walk / run holds toward (x, y), like the nurse scenario's corridor loop. -> reached."""
        lex = self.lex
        for _ in range(steps):
            dx, dy = x - lex.pos[0], y - lex.pos[1]
            distance = math.hypot(dx, dy)
            if distance < radius:
                return True
            delta = self.delta(math.degrees(math.atan2(-dx, -dy)))
            if abs(delta) > 20:
                self.key(0x4d if delta > 0 else 0x4b, 0, round(min(.3, max(.2, abs(delta) / 90)) * 30))
            else:
                self.key(0x48, worldmod.keys_mod.SHIFT if run else 0, round(min(.5, max(.3, distance / 5000)) * 30))
        return False

    def click(self, name, hold=2):
        """Click a monitor button with the pointer: move to the centre of its first drawn frame, mouse down, mouse up."""
        mon = self.world.monitor
        if mon is None:
            raise Stuck(f'click {name}: no monitor open')
        e = mon.elements.get(name.upper())
        frame = next((f for f in (e.frames[1:] if e else []) if f[0] > 1), None)
        if frame is None:
            raise Stuck(f'click {name}: no such button on {mon.name}')
        self.pointer_down(mon, name, frame)
        self.inputs.append({'tick': self.vm.tick, 'click': name})
        self.tick(hold)
        mon.mouse_up()
        self.tick(monitor_mod.REPEAT_DELAY + 2)

    def pointer_down(self, mon, name, frame):
        """Move the pointer to the centre of `frame` and press. The pointer is settled first (Monitor.settle_pointer: idle on its last frame,
        as a held mouse leaves it), so the press and, later, the release act at once as the harness's clicks always did: its playthroughs
        test the game's logic, not the hand's 5-tick press latency (the real animation is covered by test_monitor / test_options)."""
        mon.settle_pointer()
        mon.pointer_move(-frame[2] + frame[0] // 2, -frame[3] + frame[1] // 2)
        if not mon.mouse_down():
            raise Stuck(f'click {name}: button not selectable on {mon.name}')

    def start_repair(self):
        """D, BRSB, EXTB: BIOREPAIR (PIMM.scr:441-505) goes on as a process after the page closes, 1 battery energy for 2 HP every 8 ticks."""
        world, vm, lex = self.world, self.vm, self.lex
        for _ in range(120):                      # FUN_10a8_0541 drops page keys while Lex is held (+0x229, a fall): a person presses again
            if not (lex.falling or lex.vz or lex.hold):
                break
            self.tick(1)
        if world.held_item(self.lex, 'LTHAND') is not None:     # a first press of a page key only stows the left hand
            self.key(0x20)
            self.tick(10)
        self.key(0x20)
        for _ in range(120):
            if world.monitor is not None and world.monitor.name == 'PIMM':
                break
            self.tick(1)
        else:
            raise Stuck('the diagnostics page never opens')
        self.click('BRSB')
        if world.monitor is None:                 # Lex died with the page open
            return
        self.click('EXTB')
        for _ in range(60):
            if world.monitor is None:
                return
            self.tick(1)
        raise Stuck('EXIT never closes the diagnostics page')

    HEAL_BELOW = 35                               # HP under which the routine switches BIOREPAIR on, mid-fight
    HEAL_BELOW_RICH = 75                          # the same with the Elite's battery in Lex's leg: energy is no longer the limit
    STALL_STEPS = 12                              # approach steps that move him less than 300 units before he goes round whatever is in the way
    DETOUR_DISTANCE = 2200                        # how far sideways he walks to get round it
    AVOID_MARGIN = 1200                           # how far from a box in fight's `avoid` Lex stays: a lunge and a recoil each carry him about that far
    FIGHT_DELAY = {'wait': 2, 'key': 4, 'punch': 1}     # port ticks: a person's rhythm, the delay at which the port's GRDCON fight matches the live one (NOTES "Every attack in every fight")

    def shoot(self, enemy, alive, max_steps=1500):
        """The routine with a gun in hand: C into combat mode, turn toward the enemy from 50 degrees, let the auto-turn finish, KP5 until `alive()` ends or Lex dies; then out of combat. -> shots."""
        world, vm, lex = self.world, self.vm, self.lex
        delay = self.FIGHT_DELAY
        if not lex.combat:
            self.key(0x2e)
            self.tick(5)
        shots = 0
        for _ in range(max_steps):
            if vm.objects['LEX'][0] <= 0 or not alive():
                break
            if lex.motion.startswith(self.BUSY) and not lex.finished:
                self.tick(delay['wait'])
                continue
            bearing = world.rel_angle(lex, enemy.pos)
            if abs(bearing) >= 50:
                self.key(0x4b if bearing > 0 else 0x4d, 0, 5)
                self.tick(delay['key'])
            elif abs(bearing) > 12:
                self.tick(delay['wait'])
            else:
                self.key(0x4c, 0, 2)
                self.tick(delay['punch'])
                shots += 1
        if lex.combat and vm.objects['LEX'][0] > 0:
            self.key(0x2e)
            self.tick(5)
        return shots

    def fight(self, enemy, alive, max_steps=3000, attack=0x4b, mods=None, avoid=()):
        """The fighting routine, real keys only: C into combat mode, then while `alive()` and Lex lives wait out his one-shot motions, turn toward the enemy
        with KP4 / KP6 from 50 degrees (those combat keys are the ATK_M4 / ATK_M6 circling moves, and the engine's auto-turn, FUN_1088_3419, aligns Lex only
        within 55 degrees while he walks or stands), close in with KP8 until within REACH, and press the attack (default Alt+KP4: ATK_H4) again inside the
        stun of the last hit. Three circling moves in a row can leave the bearing past the auto-turn for good, so then Lex leaves combat, turns and goes back in.
        Under HEAL_BELOW HP he switches BIOREPAIR on while the battery allows it. Within AVOID_MARGIN of a trigger box in `avoid` he steps away before anything else. -> {'steps', 'punches', 'turns', 'approaches', 'waits', 'repairs'}"""
        world, vm, lex = self.world, self.vm, self.lex
        delay = self.FIGHT_DELAY
        if not lex.combat:
            self.key(0x2e)
            self.tick(5)
        counts = {'steps': 0, 'punches': 0, 'turns': 0, 'approaches': 0, 'waits': 0, 'repairs': 0}
        circled = retreated = waited = stalled = 0
        stalled_at = None
        level = world.level
        for _ in range(max_steps):
            if vm.objects['LEX'][0] <= 0 or not alive() or world.level != level:      # a fall through a hole leaves the enemy behind
                break
            counts['steps'] += 1
            if lex.motion.startswith(self.BUSY) and not lex.finished and lex.motion != 'ATK_M8':
                self.tick(delay['wait'])
                continue
            if not lex.combat and lex.ai_enabled:                   # a quake (or a scene) drops combat mode, and the combat keys then walk him about
                self.key(0x2e)
                self.tick(5)
                continue
            energy = vm.objects['MY_BATTERY'][0]
            if vm.objects['LEX'][0] < (self.HEAL_BELOW_RICH if energy > 100 else self.HEAL_BELOW) and vm.globals.get('_bio_state') != 1 and energy >= 10:
                self.start_repair()
                counts['repairs'] += 1
                continue
            box = next((b for b in avoid if b['lo'][0] - self.AVOID_MARGIN < lex.pos[0] < b['hi'][0] + self.AVOID_MARGIN and b['lo'][1] - self.AVOID_MARGIN < lex.pos[1] < b['hi'][1] + self.AVOID_MARGIN), None)
            retreated = retreated + 1 if box is not None else 0
            if box is not None and retreated <= 6:                  # a wall can hold him inside the margin: then the fight goes on where he stands
                away = 2 * lex.pos[:2] - (np.asarray(box['lo'][:2], float) + np.asarray(box['hi'][:2], float)) / 2
                self.key(0x48 if abs(world.rel_angle(lex, away)) < 90 else 0x50, 0, 3)
                self.tick(delay['key'])
                counts['retreats'] = counts.get('retreats', 0) + 1
                continue
            bearing = world.rel_angle(lex, enemy.pos)
            distance = math.hypot(*(enemy.pos[:2] - lex.pos[:2]))
            if abs(bearing) >= 50:
                circled += 1
                counts['turns'] += 1
                if circled > 3:
                    circled = 0
                    self.key(0x2e)
                    self.tick(5)
                    for _ in range(5):
                        angle = world.rel_angle(lex, enemy.pos)
                        if abs(angle) < 25 or vm.objects['LEX'][0] <= 0:
                            break
                        self.key(0x4b if angle > 0 else 0x4d, 0, 8)     # a turn motion needs some frames to rotate
                    self.key(0x2e)
                    self.tick(5)
                else:
                    self.key(0x4b if bearing > 0 else 0x4d, 0, 5)
                    self.tick(delay['key'])
                continue
            circled = 0
            if distance > self.REACH:
                if stalled_at is not None and math.hypot(*(lex.pos[:2] - stalled_at)) > 300:
                    stalled, stalled_at = 0, None
                if stalled_at is None:
                    stalled_at = lex.pos[:2].copy()
                stalled += 1
                if stalled > self.STALL_STEPS:                      # a wall or pillar between them: out of combat, turn square to him, walk clear of it (a side each time), back in
                    counts['detours'] = counts.get('detours', 0) + 1
                    self.key(0x2e)
                    self.tick(5)
                    goal = 90 if counts['detours'] % 2 else -90
                    for _ in range(12):
                        angle = world.rel_angle(lex, enemy.pos)
                        if abs(angle - goal) < 20 or vm.objects['LEX'][0] <= 0:
                            break
                        self.key(0x4b if angle > goal else 0x4d, 0, 8)
                    start = lex.pos[:2].copy()
                    for _ in range(15):
                        if math.hypot(*(lex.pos[:2] - start)) > self.DETOUR_DISTANCE or vm.objects['LEX'][0] <= 0:
                            break
                        self.key(0x48, 0, 3)
                        self.tick(delay['key'])
                    self.key(0x2e)
                    self.tick(5)
                    stalled, stalled_at = 0, None
                    continue
                self.key(0x48, 0, 3)
                self.tick(delay['key'])
                counts['approaches'] += 1
            elif abs(bearing) > 20 and waited < 30:                 # an enemy standing still at this bearing never brings the auto-turn: then he gets the punch anyway
                self.tick(delay['wait'])
                counts['waits'] += 1
                waited += 1
            else:
                waited = 0
                self.tick(delay['punch'])
                self.key(attack, worldmod.keys_mod.ALT if mods is None else mods, 2)
                self.tick(delay['punch'])
                counts['punches'] += 1
        return counts


def hits_between(world, attacker, target, since=0):
    """world.hits rows (tick, attacker, target, motion, label) of one pairing."""
    return [plain(hit) for hit in world.hits[since:] if hit[1] == attacker and hit[2] == target]


# The Caynan fight is seeded at its staging point too: after the movement fixes (NOTES "Movement fixes": the opening is 54 ticks longer, GO
# arrivals stop short of their targets) the boot-seeded stream lost the Easy fight (Lex died at 50 Caynan HP). The seed only has to land
# the punch loop on a win. Of seeds 0-11 the wins are 1 (Lex 69 HP), 6 (5), 7 (11) and 10 (35); seeds 1 and 7 leave Caynan up in ATK_STAND,
# because the tail of his PLAYER_SUPER_RECOILED process (`MOTION ATK_STAND CONTINUE`, AI_CAYNA.scr:234) now runs after his DIE finished
# (DIE only refuses while unfinished, 1098:0394). Seed 10 ends in DIE.
# Since AI OFF pauses rather than ends the AI (NOTES "Room events and the default AI") the wins of seeds 0-17 are 5 (Lex 46 HP), 7 (47), 13 (69) and 16 (57),
# all ending in DIE; seed 13 leaves Lex the most.
# Since a living figure's ended motion falls back to its idle (1088:4155) and Lex plays ENTER_COMBAT, the wins of seeds 0-23 ending in DIE are 0 (Lex 68 HP), 4 (13), 10 (22), 14 (6), 18 (46) and 23 (70). Seed 23 leaves Lex the most, and the prison run's dash out of cell 1 misses the bars (0 does not).
# Since a motion's first update moves by frame 0's root (NOTES "Movement fixes"; the nurse push route and the Caynan fight's steps changed), the wins
# of seeds 0-47 ending in DIE with the most HP are 11 (Lex 82), 39 (82), 33 (79), 24 (74) and 8 (54). Seed 24 makes a script run `AI ON` on the dead
# CAYNAN (a warning) and seed 33 never runs CAYNAN_STIMULUS; seed 11 leaves Lex 82 HP with neither.
# Since LINKMETOCAMERAS pauses the camera-linked processes (FLICKER_LIGHT, BLOCK_DRIP and the like no longer draw RANDOM off camera), seed 11 no longer
# kills him. Of seeds 0-32 the wins ending in DIE with no warning and the most HP are 29 (Lex 76), 25 (73), 17 (58), 2 (56) and 18 (50).
# Since every update's root move rounds down (NOTES "Root moves round down"), seed 29 loses. Of seeds 0-47 the wins ending in DIE with no warning are led by
# 28 (Lex 89), which never runs CAYNAN_STIMULUS, then 46 (Lex 60).
# Since moving attacks have no auto-turn (NOTES "No aim assist in a moving attack"), of seeds 0-47 the wins ending in DIE with no warning are led by 40 (Lex 76), 18 (57) and 9 (50).
CAYNAN_SEED = 9                # since recoils gate script motions: of seeds 0-27, 11 win and finish the prison; 9 keeps all of Lex's HP


def chaos_caynan_fight(run=None, difficulty=0, seed=CAYNAN_SEED):
    """Lex fights CAYNAN with real keys after the nurse encounter (`run` = nurse_defeat_run()'s (world, vm, report), else it is run).
    Staged: only the nurse encounter's own logged poses (carried in the report). Lex leaves the BLK1 pocket across the open block hall,
    stands outside cell 1 (OUTSIDE3: CAYNAN_GREET) and, when the cell bars' flicker (_Cell1RepairNeeded = 1: CELLONEBARS drops them
    for 61 and 21 ticks alternately) opens the long window, runs through DR_ZAP1 into INSIDE3 (CAYNAN_AI's fight state), enters combat
    mode and punches until CAYNAN_DEATH runs or Lex dies."""
    world, vm, nurse = run or nurse_defeat_run()
    play = Play(world, vm)
    lex, cay = play.lex, world.figures['CAYNAN']
    start_tick = vm.tick
    staged = [{'stage': 'difficulty', 'tick': vm.tick, 'from': vm.globals['_difficulty_level'], 'to': difficulty}]
    vm.globals['_difficulty_level'] = difficulty
    if seed is not None:                          # the scenario alone: its draws no longer depend on how long the opening ran. A playthrough passes None.
        staged.append({'stage': 'rng', 'tick': vm.tick, 'seed': seed})
        world.rng = random.Random(seed)
    result = [checkpoint(world, vm, 'nurse-aftermath')]
    for waypoint in ((-9500, -19500), (0, -19500), (0, -16500)):       # the hall (y < -18000) joins the pockets in front of the cells
        play.walk_to(*waypoint, radius=400, run=True)
    play.face(180)                                                       # north, toward the cell door
    result.append(checkpoint(world, vm, 'outside-cell-1', frame=True))
    greeted = vm.globals.get('_caynan_state') == 1 or 'CAYNAN_GREET' in {name for _, name in play.blocks}
    durations, state, edge = [], vm.globals['_bars1_on'], None
    for _ in range(3000):             # an off window that follows a short (21 tick) one is the long one; skip it if CAYNAN waits in the doorway
        play.tick(1)
        bars = vm.globals['_bars1_on']
        if state == 1 and bars == 0:
            edge = vm.tick
            if durations and durations[-1] < 40 and math.hypot(cay.pos[0], cay.pos[1] + 14500) > 3500:
                break
        elif state == 0 and bars == 1 and edge is not None:
            durations.append(vm.tick - edge)
        state = bars
    window_tick = vm.tick
    for _ in range(6):
        play.key(0x48, worldmod.keys_mod.SHIFT, 8)
        if vm.globals.get('_caynan_state') == 2 and lex.pos[1] > -13000:
            break
    play.walk_to(0, -9500, radius=500, run=True)                         # away from the bars: a hit's knockback must not throw Lex into them
    inside = {'tick': vm.tick, 'lex_xy': plain(lex.pos[:2]), 'caynan_state': vm.globals.get('_caynan_state'),
              'lex_health': vm.objects['LEX'][0]}
    result.append(checkpoint(world, vm, 'inside-cell-1', frame=True))
    hits_before = len(world.hits)
    fight_tick = vm.tick
    counts = play.fight(cay, lambda: bool(vm.globals.get('_caynan_alive')))
    result.append(checkpoint(world, vm, 'fight-end', frame=True))
    play.tick(400)                                                       # CAYNAN_DEATH's script tail (taunt, subtitle, growl)
    result.append(checkpoint(world, vm, 'after-death', frame=True))
    report = scenario_result('chaos_caynan_fight', world, vm, result, play.inputs)
    cay_health = vm.objects['CAYNAN'][0]
    report['encounter'] = {
        'nurse_report_ticks': nurse['encounter']['total_ticks'], 'start_tick': start_tick, 'bars_window_tick': window_tick,
        'staged': staged, 'nurse_fixtures': nurse['encounter']['fixtures'], 'greeted': greeted, 'inside': inside, 'fight_tick': fight_tick,
        'counts': counts, 'end_tick': vm.tick,
        'lex_hits': hits_between(world, 'LEX', 'CAYNAN', hits_before), 'caynan_hits': hits_between(world, 'CAYNAN', 'LEX', hits_before),
        'caynan_health': cay_health, 'lex_health': vm.objects['LEX'][0], 'caynan_alive': vm.globals.get('_caynan_alive'),
        'caynan_motion': cay.motion, 'caynan_decals': plain(cay.decals), 'music': plain(world.music_log[-3:]),
        'blocks': [name for _, name in play.blocks if name.startswith(('CAYNAN', 'DR_ZAP1', 'INSIDE3', 'OUTSIDE3', 'RESET3', 'MONSTER', 'EAT_', 'GROWL'))],
        'bars_off_ticks': durations,
    }
    return report


# After the movement fixes the former pick, seed 3, loses Easy (the opening is 54 ticks longer); seeds 0, 1 and 2 win Easy (Lex 45, 40 and 34 HP)
# and Medium is lost for 0, 1, 2, 4 and 5. Seed 0.
# (Earlier note:) The Guard 1 fight is seeded at its staging point. Seeded from the boot, the Easy win came and went with the opening's length (the
# QUAKE decay ramps added 30 ticks and Lex lost). With seed 1, Easy wins (Lex 25-29 HP) and Medium is lost for every start between
# 0 and 400 ticks later; seed 0 and seed 3 win Easy too, but by narrower margins (down to 7 and 4 HP). Since TANKTOCELL2 calls
# ENTERCELL2 itself after its LOADLEVEL (inside the VM tick, not after it), the RANDOM draws come in another order: seeds 1-12 now win
# Easy 8 times (3-6, 8-10, 12) and lose Medium every time; seed 3 is the first winner.
# Re-seeded 0 -> 4 with the scripted-MOTION gate (1098:12bd: a MOTION of the name that is still running is not restarted, so the AI loops'
# re-requests no longer reset the pose): seed 0 now loses Easy (Lex dies at 40 Guard HP). Of seeds 0-11 the Easy wins are 4 (Lex 56 HP), 5
# (46), 6 (45), 9 (51), 10 (20) and 11 (14); seed 4 is the first winner and all end in DIE.
# Since AI OFF pauses the AI, with the motion gate and TURN of "Items and combat", the Easy wins of seeds 0-11 are 2 (Lex 3 HP), 3 (25), 4 (41), 7 (3),
# 9 (8) and 11 (24), all ending in DIE; seed 4 leaves Lex the most.
# Since a motion's first update moves by frame 0's root (NOTES "Movement fixes"), seed 4 loses Easy; of seeds 0-23 the wins without a warning are 0 (Lex 62 HP),
# 1 (51), 2 (36), 5 (13), 6 (79), 7 (20), 8 (34), 9 (45), 10 (50), 12-14, 18, 22 (73) and 23 (2); seed 3 (68) runs `AI ON` on the dead GUARD1 (a warning). Seed 6 leaves Lex the most.
# Since LINKMETOCAMERAS pauses the camera-linked processes (fewer RANDOM draws off camera), seed 6 loses Easy; of seeds 0-23 the wins ending in DIE with no warning and the
# most HP are 20 (Lex 89), 7 (83), 17 (83) and 19 (78).
# Since every update's root move rounds down (NOTES "Root moves round down"), seed 20 ends with a warning; of seeds 0-31 the wins ending in DIE with no warning and
# the most HP are 19 and 25 (Lex 78).
# Since moving attacks have no auto-turn, of seeds 0-31 the wins ending in DIE with no warning are led by 14 (Lex 84), 19 and 21 (78).
# Since CONFRONTENEMY waits for its turn, GUARD1 really wakes first and recoils gate script motions: of seeds 0-15, 12 wins at Easy (Lex 62) and loses at Medium by KILLED_PLAYER.
GUARD1_SEED = 12


def chaos_guard1_fight(difficulty=0, play=None, seed=GUARD1_SEED, attack=0x4b):
    """Lex fights GUARD1 in cell 2 after the original's return from the tanks level. Staged (and logged): starting TANKTOCELL2
    (`LOADLEVEL CHAOS TNKS_ARV`, then `CALL ENTERCELL2`, CRYTOTNK.scr:292-298, CHAOS.scr:144), which nothing in the scripts calls.
    CRYTOTNK.scr is in CHAOS.LVL, so the caller survives its LOADLEVEL and calls ENTERCELL2 itself (VM.end_unloaded). From there the
    authored ACTIVATE_GUARD1 / GREET_GUARD1 run; Lex enters combat mode and punches with real keys until GUARD1_DEATH
    (DOTHELEXTHING) runs or Lex dies. `play` = a Play that is already in cell 2 (the full playthrough arrives by TOCELL2 itself): nothing is
    staged then, and `seed` seeds the fight's RANDOM draws."""
    arrived = play is not None
    if play is None:
        world, vm = boot_opening()
        tick(world, vm, opening_ticks(1170))
        play = Play(world, vm)
    else:
        world, vm = play.world, play.vm
    lex = play.lex
    loads = len(world.level_loads)
    staged = [{'stage': 'difficulty', 'tick': vm.tick, 'from': vm.globals['_difficulty_level'], 'to': difficulty}]
    vm.globals['_difficulty_level'] = difficulty
    if seed is not None:                   # the scenario alone: its draws no longer depend on how long the opening ran. A playthrough passes None.
        staged.append({'stage': 'rng', 'tick': vm.tick, 'seed': seed})
        world.rng = random.Random(seed)
    if not arrived:
        staged.insert(0, {'stage': 'tanks-return', 'tick': vm.tick, 'blocks': ['TANKTOCELL2', 'ENTERCELL2']})
        vm.fire('TANKTOCELL2')
        for _ in range(6):
            vm.tick_once()
            if len(world.level_loads) > loads:              # TANKTOCELL2 itself goes on to CALL ENTERCELL2 (CRYTOTNK.scr is in CHAOS.LVL)
                world.step()
                break
            world.step()
    guard = world.figures['GUARD1']
    result = [checkpoint(world, vm, 'cell-2-arrival', frame=True)]
    for _ in range(400):                                                  # ENTERCELL2's walk and GREET_GUARD1's subtitles
        play.tick(1)
        if guard.ai_proc is not None and not guard.ai_proc.done and vm.globals.get('_grd1_awake') == 1 and not lex.go \
                and 'GREET_GUARD1' in {name for _, name in play.blocks} and not any(
                    p.block.name == 'GREET_GUARD1' and not p.done for p in vm.procs.values()):
            break
    result.append(checkpoint(world, vm, 'guard-awake', frame=True))
    hits_before, fight_tick = len(world.hits), vm.tick
    counts = play.fight(guard, lambda: bool(vm.globals.get('_grd1_alive')), attack=attack)
    result.append(checkpoint(world, vm, 'fight-end', frame=True))
    play.tick(700)                                                       # GUARD1_DEATH, DOTHELEXTHING (taunts, subtitles, CAMERA UNLOCK)
    result.append(checkpoint(world, vm, 'after-death', frame=True))
    report = scenario_result('chaos_guard1_fight', world, vm, result, play.inputs)
    report['encounter'] = {
        'staged': staged, 'fight_tick': fight_tick, 'counts': counts, 'end_tick': vm.tick,
        'lex_hits': hits_between(world, 'LEX', 'GUARD1', hits_before), 'guard_hits': hits_between(world, 'GUARD1', 'LEX', hits_before),
        'guard_health': vm.objects['GUARD1'][0], 'lex_health': vm.objects['LEX'][0], 'guard_alive': vm.globals.get('_grd1_alive'),
        'guard_motion': guard.motion, 'guard_decals': plain(guard.decals), 'lex_decals': plain(lex.decals),
        'camera': world.current_camera(), 'music': plain(world.music_log[-3:]),
        'blocks': [name for _, name in play.blocks if name.startswith(('GUARD1', 'GRD', 'DOTHE', 'ACTIVATE', 'GREET', 'LUTHOR', 'ENTERCELL', 'MONSTER', 'GROWL'))],
    }
    return report


def landpad_meetmech():
    world = worldmod.World('LANDPAD')
    vm = vmmod.VM(world)
    vmmod.load_level(vm, 'LANDPAD')
    vm.fire('MEETMECH')
    tick(world, vm, 500)                      # AIRMECHO arrives at tick 459
    return scenario_result('landpad_meetmech', world, vm,
                           [checkpoint(world, vm, 'meetmech-complete', frame=True)])


def beach_tunnel_beach():
    world = worldmod.World('BEACH')
    vm = vmmod.VM(world)
    vmmod.load_level(vm, 'BEACH')
    # GAME normally creates the persistent player before a transit block runs.
    world.figure('PLAYER')
    vm.fire('TO_TPL')
    tick(world, vm, 1)
    into_tunnel = checkpoint(world, vm, 'tunnel-arrival', frame=True)
    vm.fire('TO_BCH')
    tick(world, vm, 1)
    return scenario_result('beach_tunnel_beach', world, vm,
                           [into_tunnel, checkpoint(world, vm, 'beach-return', frame=True)])


def all_level_smoke():
    """Load and draw each shipped GAMEDAT level without running an arbitrary event."""
    levels = []
    for filename in sorted(os.listdir(worldmod.GAMEDAT)):
        if not filename.upper().endswith('.IFF'):
            continue
        level = os.path.splitext(filename)[0].upper()
        world = worldmod.World(level)
        vm = vmmod.VM(world)
        vmmod.load_level(vm, level)
        frame = world.render()
        levels.append({'level': level, 'shape': list(frame.shape),
                       'warnings': list(world.warnings) + list(vm.warnings)})
    return levels


def scenario_result(name, world, vm, checkpoints, input_events=()):
    frames = {point['name']: point.pop('frame') for point in checkpoints if point['frame'] is not None}
    return {
        'name': name,
        'input_events': list(input_events),
        'checkpoints': checkpoints,
        'frames': frames,
        'events': plain(world.events),
        'camera_changes': plain(world.camera_changes),
        'level_loads': plain(world.level_loads),
        'hits': plain(world.hits),
        'sound_log': plain(world.sound_log),
        'sound_stops': plain(world.sound_stops),
        'sound_releases': plain(world.sound_releases),
        'sound_drops': plain(world.sound_drops),
        'sound_volumes': plain(world.sound_volumes),
        'subtitle_log': plain(world.subtitle_log),
        'music_log': plain(world.music_log),
        'warnings': list(world.warnings) + list(vm.warnings),
        'unmodelled': list(world.unmodelled),
        'command_counts': command_counts(world),
        'final_globals': {key: value for key, value in vm.globals.items()
                          if key in ('_lexrevived', '_lex_drugged', '_airmecho_scene', '_dr9_space')},
    }


def write_scenario(result, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    for name, frame in result['frames'].items():
        Image.fromarray(frame).save(os.path.join(out_dir, result['name'] + '_' + name + '.png'))
    with open(os.path.join(out_dir, result['name'] + '.json'), 'w', encoding='utf-8') as handle:
        json.dump(plain({key: value for key, value in result.items() if key != 'frames'}),
                  handle, indent=2, sort_keys=True)


def run_all(out_dir=None):
    nurse_run = nurse_defeat_run()           # the Caynan fight continues from this run's world, so the nurse encounter runs once
    results = [opening_escape(), opening_revival(), nurse_run[2], chaos_caynan_fight(nurse_run), chaos_guard1_fight(),
               landpad_meetmech(), beach_tunnel_beach()]
    smoke = all_level_smoke()
    manifest = {'scenarios': [{key: value for key, value in result.items() if key != 'frames'} for result in results],
                'all_level_smoke': smoke}
    if out_dir:
        for result in results:
            write_scenario(result, out_dir)
        with open(os.path.join(out_dir, 'manifest.json'), 'w', encoding='utf-8') as handle:
            json.dump(plain(manifest), handle, indent=2, sort_keys=True)
    return results, smoke


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', default='re/out/scenarios', help='directory for JSON manifests and selected PNG frames')
    args = parser.parse_args()
    scenarios, smoke = run_all(args.out)
    print('wrote %d scenarios and %d level smoke checks to %s' % (len(scenarios), len(smoke), args.out))
