"""Every attack key in every melee fight, in the Python port, from the state the full run reaches.

    re/.venv/bin/python -I -W ignore re/tools/fight_sweep.py run [--seeds 12] [--only guard1,grdcon] [--fast] [--delay 2,4,2]
    re/.venv/bin/python -I re/tools/fight_sweep.py report [--markdown] [--fast]

One pass of playthrough_full stops at each fight and forks one child per attack and seed; the run itself goes on untouched. A child plays
fight_sample's loop (the same keys and LATENCY, so a human's or the debugger's reaction time, not the harness's fast one) with one attack and
writes one row to re/out/fight_sweep/<fight>.jsonl. `--fast` plays with no reaction time at all, the best a person could anticipate, and writes under fast/. Staging beyond what the run has done is listed in STAGES and comes before the first key.
Port only: `fight_sample.py live --attack` plays a chosen attack in the original."""
import argparse
import collections
import json
import os
import random
import sys
import time
import types

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(ROOT, 're', 'out', 'fight_sweep')
sys.path[:0] = [os.path.join(ROOT, 're', 'tools'), os.path.join(ROOT, 're', 'interp'), os.path.join(ROOT, 're', 'formats')]

PAD = {0x47: 7, 0x48: 8, 0x49: 9, 0x4b: 4, 0x4d: 6, 0x4f: 1, 0x50: 2, 0x51: 3}      # keys.COMBAT_PAD: the scan of each keypad digit
NOT_ATTACKS = {('H', 0x4f), ('H', 0x50), ('H', 0x51), ('F', 0x50)}                  # ATK_H1, H2, H3 and F2 have strength 0 in MAN.MTN: they cannot hurt
ATTACKS = [(kind, scan) for kind in ('H', 'F') for scan in PAD if (kind, scan) not in NOT_ATTACKS]      # Alt: ATK_H<n>; Ctrl: ATK_F<n>
FAST_LATENCY = {'wait': 1, 'key': 0, 'punch': 0}
WORKERS = 8
STAGES = {
    'caynan': 'None: the run\'s own fight, after the nurse.',
    'guard1': 'None: the run\'s own fight, on arrival in cell 2.',
    'grdcon': 'After the operating room: Lex placed in the control room, `_LexConLoc` 5. No suit.',
    'grdcon-suit': 'None: after the suit machine, in the hard suit.',
    'grdhall': 'After the suit machine: GRDCON_DEATH run, Lex placed in the hall, still in the suit, at the HP the run has.',
    'grdhang': 'None: the run\'s own fight at the foot of the lift, healed to 100 first.',
    'drogg1': 'None: the run\'s own fight. A win is six super recoils.',
    'drogg2': 'Lex placed on TDROGG2B on arrival in DIGSITE, in place of the run\'s `_Drogg2_Alive = 0`. A win is his escape.',
    'drogg3': 'None: the run\'s own fight, on plain LEX.',
    'marine4': 'None: the run\'s own fight.',
    'marine5': 'None: the guard-ai-off shortcut is left out and Lex walks the hall to him. He has a BLASTER.',
    'tumolt': 'None: after his speech, in place of the staged death. He has the TONFA.',
}


def attack_name(attack):
    kind, scan = attack
    return f'ATK_{kind}{PAD[scan]}'


def key_name(attack):
    kind, scan = attack
    return f"{'Alt' if kind == 'H' else 'Ctrl'}+KP{PAD[scan]}"


def sweep(name, play, enemy_key, alive, seeds, setup=None):
    """Forks the fight once per attack and seed, then waits for them all. The caller goes on as if nothing happened."""
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, f'{name}.jsonl')
    open(path, 'w').close()
    started = time.time()
    jobs = [(attack, seed) for attack in ATTACKS for seed in range(seeds)]
    running = 0
    sys.stdout.flush()
    for attack, seed in jobs:
        if running == WORKERS:
            os.wait()
            running -= 1
        if os.fork() == 0:
            code = 1
            try:
                row = one_fight(play, enemy_key, alive, attack, seed, setup)
                with open(path, 'a') as out:
                    out.write(json.dumps(dict(row, fight=name)) + '\n')
                code = 0
            except BaseException as error:              # a child must never return into the run
                with open(path, 'a') as out:
                    out.write(json.dumps({'fight': name, 'attack': attack_name(attack), 'key': key_name(attack), 'seed': seed, 'outcome': 'error', 'error': repr(error)[:300]}) + '\n')
            finally:
                os._exit(code)
        running += 1
    while running:
        os.wait()
        running -= 1
    print(f'{name}: {len(jobs)} fights in {time.time() - started:.0f} s', flush=True)


def one_fight(play, enemy_key, alive, attack, seed, setup):
    """One fight to its end. -> a row of the sweep's output."""
    import fight_sample
    import world as worldmod
    world, vm = play.world, play.vm
    world.rng = random.Random(seed)
    if setup:
        setup(play)
    lex = world.player()
    play.lex = lex
    enemy = world.figures[enemy_key]
    for _ in range(900):                                # a scene can hold the keys: the fight starts when they work
        if lex.ai_enabled:
            break
        play.tick(1)
    level, hits_before, start = world.level, len(world.hits), vm.tick
    lex_start, enemy_start = vm.objects['LEX'][0], vm.objects[enemy_key][0]
    modifier = worldmod.keys_mod.ALT if attack[0] == 'H' else worldmod.keys_mod.CTRL
    trace = []
    def going():
        return alive() and world.level == level
    presses = fight_sample.port_fight(play, enemy, enemy_key, attack[1], trace, mods=modifier, going=going, unstick=True)
    lex_end, enemy_end = vm.objects['LEX'][0], vm.objects[enemy_key][0]
    landed = [h for h in world.hits[hits_before:] if h[1] == 'LEX' and h[2] == enemy_key and h[-1] != 'BLOCKED']
    if lex_end <= 0:
        outcome = 'loss'
    elif world.level != level:
        outcome = 'left'
    elif not alive() or enemy_end <= 0:
        outcome = 'win'
    else:
        outcome = 'timeout'
    return {'attack': attack_name(attack), 'key': key_name(attack), 'seed': seed, 'outcome': outcome, 'ticks': vm.tick - start, 'presses': presses, 'landed': len(landed),
            'lex': [lex_start, lex_end], 'enemy': [enemy_start, enemy_end], 'end': {'lex': [lex.motion, [int(v) for v in lex.pos[:2]]], 'enemy': [enemy.motion, [int(v) for v in enemy.pos[:2]]], 'camera': world.current_camera()}}


def run_sweeps(seeds, only):
    """One pass of the full run with a sweep at each fight. Hooks only read: the run is the same as without them, save for the two shortcuts a child leaves out."""
    import playthrough_base as pb
    import playthrough_full as pf
    import playthrough_prison as pp
    import playthrough_surface as ps
    import scenarios
    wanted = lambda name: only is None or name in only
    fight_keys = {'CAYNAN': 'caynan', 'GUARD1': 'guard1', 'DROGG1': 'drogg1', 'DROGG3': 'drogg3', 'MARINE4': 'marine4', 'GRDHANG': 'grdhang'}
    original_fight = scenarios.Play.fight
    def fight(self, enemy, alive, *args, **kwargs):
        name = fight_keys.get(enemy.name.upper())
        if name and wanted(name):
            sweep(name, self, enemy.name.upper(), alive, seeds)
        return original_fight(self, enemy, alive, *args, **kwargs)
    scenarios.Play.fight = fight

    def hp_alive(play, key):
        return lambda: play.vm.objects[key][0] > 0

    original_shortcut = pp.Run.shortcut
    def shortcut(self, kind, **detail):
        guard = detail.get('guard')
        if kind == 'guard-ai-off' and guard == 'MARINE5' and wanted('marine5'):
            def hall(play):
                marine = play.world.figures[guard]
                for x, y in pf.FROM_CABIN + ((20000, -70800), (24000, -69000)):
                    if abs(marine.pos[0] - play.world.player().pos[0]) < 6000:
                        break
                    play.goto(x, y, radius=500)
            sweep('marine5', self, guard, hp_alive(self, guard), seeds, hall)
        return original_shortcut(self, kind, **detail)
    pp.Run.shortcut = shortcut

    original_stage = ps.Segment.stage
    def stage(self, kind, what, reason):
        if kind == 'fight' and what.startswith('TUMOLT') and wanted('tumolt'):
            sweep('tumolt', self.play, 'TUMOLT', hp_alive(self.play, 'TUMOLT'), seeds)
        return original_stage(self, kind, what, reason)
    ps.Segment.stage = stage

    original_set_global = ps.Segment.set_global
    def set_global(self, name, value, reason):
        if name == '_Drogg2_Alive' and wanted('drogg2'):
            seg = self
            def wake(play):
                seg.set_pos(seg.box_centre('TDROGG2B'), 0, 'onto the trigger that wakes him')
                play.tick(5)
                play.until(lambda: play.world.player().ai_enabled, 900, 'Drogg 2 has jumped out')
            play = self.play
            sweep('drogg2', play, 'DROGG2', lambda: play.vm.globals.get('_drogg2_alive', 1) and play.vm.objects['DROGG2'][0] > 0, seeds, wake)
        return original_set_global(self, name, value, reason)
    ps.Segment.set_global = set_global

    def to_control_room(play):
        world, vm = play.world, play.vm
        world.set_pos(world.player(), [51000.0, -78000.0, -3100.0], raw=True)
        world.player().heading = 0.0
        vm.globals['_lexconloc'] = 5
        play.until(lambda: vm.globals.get('_grdcon_active') == 1, 400, 'the guard is active')

    def grdhall_comes(play):
        world, vm = play.world, play.vm
        vm.objects['GRDCON'][0] = 0
        vm.spawn('GRDCON_DEATH', ctx=types.SimpleNamespace(cur_fig='GRDCON', cur_item=None, owner='level'))
        play.until(lambda: not any(p.block.name == 'GRDCON_DEATH' and not p.done for p in vm.procs.values()), 1500, 'the guard has died')
        z = world.point_floor(20000, -70800, 0, 0)
        world.set_pos(world.player(), [20000.0, -70800.0, z + world.foot(world.player())], raw=True)
        play.tick(30)

    run = pp.play(run_class=pf.Full)
    if not run.passed:
        raise RuntimeError('the prison leg failed')
    for name, leg in pf.LEGS:
        if name == 'bio-repair' and only is not None and not (only - {'caynan', 'guard1'}):
            return
        leg(run)
        if not run.passed:
            raise RuntimeError(f'the leg {name} failed')
        if name == 'operating-room':
            if wanted('grdcon'):
                sweep('grdcon', run, 'GRDCON', hp_alive(run, 'GRDCON'), seeds, to_control_room)
        elif name == 'hardsuit':
            if wanted('grdcon-suit'):
                sweep('grdcon-suit', run, 'GRDCON', hp_alive(run, 'GRDCON'), seeds)
            if wanted('grdhall'):
                sweep('grdhall', run, 'GRDHALL', hp_alive(run, 'GRDHALL'), seeds, grdhall_comes)


def load():
    """{fight: [row]}, in STAGES' order."""
    out = {}
    for name in STAGES:
        path = os.path.join(OUT, f'{name}.jsonl')
        if os.path.exists(path):
            out[name] = [json.loads(line) for line in open(path)]
    return out


def table(rows):
    """One line per attack, best first: wins first, then HP Lex keeps in them, then damage done."""
    by = collections.defaultdict(list)
    for row in rows:
        by[row['key']].append(row)
    lines = []
    for key, fights in by.items():
        played = [f for f in fights if f['outcome'] != 'error']
        wins = [f for f in played if f['outcome'] == 'win']
        mean = lambda values: sum(values) / len(values) if values else 0
        lines.append({'key': key, 'attack': fights[0]['attack'], 'fights': len(fights), 'wins': len(wins), 'left': sum(f['outcome'] == 'left' for f in played),
                      'timeouts': sum(f['outcome'] == 'timeout' for f in played), 'errors': len(fights) - len(played),
                      'lex_left_in_wins': round(mean([f['lex'][1] for f in wins])), 'enemy_lost': round(mean([f['enemy'][0] - f['enemy'][1] for f in played])),
                      'lex_lost': round(mean([f['lex'][0] - max(f['lex'][1], 0) for f in played])), 'hits_per_press': round(sum(f['landed'] for f in played) / max(sum(f['presses'] for f in played), 1), 2),
                      'ticks': round(mean([f['ticks'] for f in played]))})
    return sorted(lines, key=lambda l: (-l['wins'], -l['lex_left_in_wins'], -l['enemy_lost']))


def report(markdown=False):
    for name, rows in load().items():
        lines = table(rows)
        start = next((r for r in rows if 'lex' in r), None)
        print(f"\n{'### ' if markdown else ''}{name}: Lex {start and start['lex'][0]} HP, enemy {start and start['enemy'][0]} HP. {STAGES[name]}")
        if markdown:
            print('\n| Key | Attack | Wins | Lex left in wins | Enemy HP lost | Lex HP lost | Hits per press | Ticks |\n|---|---|---|---|---|---|---|---|')
        for l in lines:
            cells = (l['key'], l['attack'], f"{l['wins']}/{l['fights']}", l['lex_left_in_wins'], l['enemy_lost'], l['lex_lost'], l['hits_per_press'], l['ticks'])
            extra = ''.join(f" {k}={l[k]}" for k in ('left', 'timeouts', 'errors') if l[k])
            print(('| ' + ' | '.join(map(str, cells)) + ' |' if markdown else ' '.join(f'{c!s:>9}' for c in cells)) + extra)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('run', 'report'))
    parser.add_argument('--seeds', type=int, default=12)
    parser.add_argument('--only')
    parser.add_argument('--markdown', action='store_true')
    parser.add_argument('--fast', action='store_true')
    parser.add_argument('--delay', help='wait,key,punch in port ticks, in place of LATENCY: writes under delay_<wait>_<key>_<punch>/')
    args = parser.parse_args(argv)
    if args.fast or args.delay:
        global OUT
        import fight_sample
        wait, key, punch = map(int, args.delay.split(',')) if args.delay else FAST_LATENCY.values()
        OUT = os.path.join(OUT, f'delay_{wait}_{key}_{punch}' if args.delay else 'fast')
        fight_sample.LATENCY = {'wait': wait, 'key': key, 'punch': punch}
    if args.action == 'run':
        run_sweeps(args.seeds, set(args.only.split(',')) if args.only else None)
    report(args.markdown)


if __name__ == '__main__':
    main()
