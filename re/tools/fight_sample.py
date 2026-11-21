"""Samples one fight in the original and in the Python port with the same key loop, for comparing damage and rates.

    re/.venv/bin/python -I -W ignore re/tools/fight_sample.py live guard1 --run 1 --port 7101
    re/.venv/bin/python -I -W ignore re/tools/fight_sample.py port guard1 --seeds 24
    re/.venv/bin/python -I -W ignore re/tools/fight_sample.py live guard1 --attack alt-4b --run 1 --port 7101     # a chosen attack: alt- or ctrl- and the keypad scan; give every run its own port
    re/.venv/bin/python -I -W ignore re/tools/fight_sample.py port guard1 --attack alt-4b --seeds 24
    re/.venv/bin/python -I re/tools/fight_sample.py report guard1

`live` boots a scratch DOSBox-X at Easy, stages the fight (every staged step is listed in STAGES) and logs both figures. Output goes to
re/out/fight_samples/<fight>/. A live decision costs a debugger round trip, about 8 clock ticks for a wait and 20-30 for a key, while the game is
paused for the sampling itself; `port` adds LATENCY to the same loop, so the two compare. Times are 60 Hz clock ticks: a port tick is two of them."""
import argparse
import collections
import json
import math
import os
import random
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(ROOT, 're', 'out', 'fight_samples')
sys.path[:0] = [os.path.join(ROOT, 're', 'tools'), os.path.join(ROOT, 're', 'interp'), os.path.join(ROOT, 're', 'formats')]

REACH = 1650                # scenarios.Play.REACH
BUSY = ('ATK_H', 'ATK_F', 'ATK_M', 'RECOIL', 'SUPER', 'SHOCK', 'GET_UP', 'DIE', 'ENTER')
LATENCY = {'wait': 4, 'key': 8, 'punch': 6}     # port ticks that stand in for the debugger round trip
ALT_SCAN = '38'
CTRL_SCAN = '1d'
FIGHTS = {'guard1': ('GUARD1', 0x48), 'grdcon': ('GRDCON', 0x48), 'drogg1': ('DROGG1', 0x4b)}     # enemy, the keypad scan of the attack
STAGES = {
    'guard1': 'The iris and `_Fido_and_Scorp_are_DEAD` set, Lex placed at the ladder and on TOCELL2. ENTERCELL2 and the guard are the game\'s.',
    'grdcon': 'Lex placed in the CHAOS cabin, the CONB click by `mouse`, Lex placed on the platform, camera CTR1 and `_LexConLoc` 5 forced. No suit.',
    'drogg1': 'As grdcon to the cabin; `_Use_Hardsuit_Machine` set and Lex placed on SUITTEST; CR_BOT placed on RAM_BOT under camera CTR1; `_Reactor_Safe` set; '
              'Lex placed on the far platform, then on CONLOC7.',
}


def bearing(lex, enemy):
    """The port's rel_angle from a live sample: positive = to Lex's left. `base_heading` is the figure's facing; `heading` also holds the stance's body yaw."""
    dx, dy = enemy['pos'][0] - lex['pos'][0], enemy['pos'][1] - lex['pos'][1]
    return -((math.degrees(math.atan2(-dx, -dy)) - lex['base_heading'] + 180) % 360 - 180)


def decide(motion, finished, distance, angle):
    """The loop of scenarios.Play.fight: -> 'wait', 'turn-left', 'turn-right', 'approach' or 'punch'."""
    if motion.upper().startswith(BUSY) and not finished:
        return 'wait'
    if abs(angle) >= 50:
        return 'turn-left' if angle > 0 else 'turn-right'
    if distance > REACH:
        return 'approach'
    return 'wait' if abs(angle) > 20 else 'punch'


def parse_attack(text):
    """'alt-4b' -> (the modifier's scan, the keypad scan)."""
    modifier, scan = text.split('-')
    return {'alt': ALT_SCAN, 'ctrl': CTRL_SCAN}[modifier], scan


class Live:
    def __init__(self, fight, run, port, attack=None):
        import dosbox_control
        self.control = dosbox_control
        self.fight, self.enemy = fight, FIGHTS[fight][0]
        self.attack = parse_attack(attack) if attack else (ALT_SCAN, f'{FIGHTS[fight][1]:x}')
        folder = os.path.join(OUT, fight, attack) if attack else os.path.join(OUT, fight)
        self.work = os.path.join(folder, f'live_{run}')
        self.log_path = os.path.join(folder, f'live_{run}.jsonl')
        self.dir = os.path.join(self.work, 'control')
        subprocess.run(['rm', '-rf', self.work], check=True)
        os.makedirs(self.work)
        subprocess.run([sys.executable, '-I', '-W', 'ignore', os.path.join(ROOT, 're', 'tools', 'dosbox_live.py'), self.work, '--control', self.dir, '--background',
                        '--keys', 'esc rshift rshift enter', '--start', '70', '--port', str(port)], capture_output=True, check=True)
        for _ in range(400):
            if os.path.isdir(os.path.join(self.dir, 'in')):
                return
            time.sleep(1)
        raise RuntimeError('the live session never became ready')

    def rq(self, **command):
        """A request; a game between levels or a falling Lex is waited out."""
        for _ in range(40):
            try:
                return self.control.request(self.dir, command)
            except RuntimeError as error:
                if not any(s in str(error) for s in ('not ready', 'no loaded', 'not grounded')):
                    raise
                time.sleep(1)
                self.control.request(self.dir, {'command': 'run_for', 'seconds': .5, 'every': .5})
        raise RuntimeError(f'gave up on {command}')

    def run_for(self, seconds):
        self.rq(command='run_for', seconds=seconds, every=seconds)

    def sample(self):
        state = self.rq(command='sample')
        return state, {f['name'].upper(): f for f in state['figures']}

    def show(self, tag):
        state, figures = self.sample()
        lex = figures.get('LEX')
        print(tag, state.get('clock'), state['camera'], lex and (lex['pos'], lex['motion'], lex['locals'][0]), flush=True)
        return state, figures

    def place(self, x, y, z=None, heading=None):
        self.rq(command='set_xy', x=x, y=y)
        if z is not None:
            self.rq(command='set_z', value=z)
        if heading is not None:
            self.rq(command='set_heading', value=heading)

    def click(self, x, y):
        for buttons, seconds in ((0, .5), (1, .5), (0, 1)):
            self.rq(command='mouse', x=x, y=y, buttons=buttons)
            self.run_for(seconds)

    def until(self, what, test, tries, seconds=2):
        for _ in range(tries):
            if test():
                return
            self.run_for(seconds)
        raise RuntimeError(f'never happened: {what}')

    def blocks(self):
        return [p['block'] for p in self.rq(command='processes')['processes']]

    def value(self, name):
        return self.rq(command='variables', names=[name])['values'][name.upper()]

    def awake(self):
        """The opening has ended and Lex stands in his cell."""
        self.run_for(25)
        def ready():
            state, figures = self.show('wake')
            return figures.get('LEX') is not None and figures['LEX']['motion'].upper() == 'STAND' and state['clock'] > 3500
        self.until('Lex wakes', ready, 40, 3)

    def stage_guard1(self):
        self.awake()
        self.rq(command='set_variable', name='_iris_opn', value=1)
        self.rq(command='set_variable', name='_fido_and_scorp_are_dead', value=1)
        self.place(-12900, -74300, -6000, 180)
        self.run_for(1.5)
        self.rq(command='key', scan='39', duration=.2)
        self.until('the ladder reaches TANKS', lambda: self.sample()[0]['camera'].startswith('TNK'), 40, 3)
        self.until('the foot of the ladder', lambda: (self.sample()[1].get('LEX') or {}).get('motion', '').upper() == 'STAND', 90)
        self.place(20000, -185700, -19000)
        def greeted():
            figures = self.sample()[1]
            guard, lex = figures.get('GUARD1'), figures.get('LEX')
            return guard and lex and guard['motion'].upper() == 'ATK_STAND' and lex['motion'].upper() in ('ATK_STAND', 'STAND')
        self.until('the guard wakes', greeted, 150, 1)

    def ride_to_control(self):
        self.awake()
        self.place(29370, -53911, heading=90)
        def console():                              # ELEV2_H1 wants COMPASS 50..130; a placed Lex can lose the heading in his first update
            self.rq(command='set_heading', value=90)
            self.run_for(1)
            self.rq(command='key', scan='39', duration=.2)
            self.run_for(2)
            return 'ELEVATOR_MONITOR' in self.blocks()
        def ride():
            self.until('the elevator monitor opens', console, 10, .5)
            self.click(165, 103)                    # CONB on ELMN
            self.run_for(10)
            return self.sample()[1].get('MECHO2') is not None
        self.until('CONTROL loads', ride, 6, 1)
        self.run_for(20)                            # the ride's tail and the door

    def stage_grdcon(self):
        self.ride_to_control()
        self.place(51000, -78000, -3100, 0)
        self.run_for(1)
        self.rq(command='force_camera', name='CTR1', auto=1)
        self.rq(command='set_variable', name='_lexconloc', value=5)
        self.until('the guard moves', lambda: self.sample()[1]['GRDCON']['motion'].upper() in ('ATK_STAND', 'ATK_M4', 'ATK_M8'), 40, 1)

    def stage_drogg1(self):
        self.ride_to_control()
        self.rq(command='set_variable', name='_use_hardsuit_machine', value=1)
        self.place(61321, -86600, -3100, 0)
        self.rq(command='force_camera', name='CTR1', auto=1)
        self.until('the suit machine starts', lambda: 'HARDSUITMACHINE' in self.blocks(), 60)
        self.until('the suit machine ends', lambda: 'HARDSUITMACHINE' not in self.blocks(), 120)
        self.rq(command='set_xy', name='CR_BOT', x=-8897, y=-102026)
        self.rq(command='force_camera', name='CTR1', auto=1)
        self.until('the forklift rams REACTBOT', lambda: self.value('_forklift_dead') == 1, 40)
        self.run_for(6)
        self.rq(command='set_variable', name='_reactor_safe', value=1)
        self.place(-8950, -141000, -5000, 180)      # the bridge is retracted: y above -133966 has no floor
        self.rq(command='force_camera', name='RTR3', auto=1)
        self.run_for(2)
        self.place(-8950, -136500, heading=0)       # into CONLOC7: ACTIVATE_DROGG1
        self.run_for(2)

    def fight_loop(self):
        modifier, attack = self.attack
        with open(self.log_path, 'w', buffering=1) as log:
            lex = self.sample()[1]['LEX']
            if not lex['flags'] & 0x40:
                self.rq(command='key', scan='2e', duration=.1)
                self.run_for(.3)
            for _ in range(6000):
                state, figures = self.sample()
                lex, enemy = figures.get('LEX'), figures.get(self.enemy)
                if lex is None or enemy is None:            # between updates the figure list can miss one
                    self.run_for(.1)
                    continue
                log.write(json.dumps({'clock': state.get('clock'), 'lex': lex['motion'].upper(), 'enemy': enemy['motion'].upper(), 'lex_hp': lex['locals'][0], 'enemy_hp': enemy['locals'][0],
                                      'lex_pos': lex['pos'], 'enemy_pos': enemy['pos'], 'bearing': round(bearing(lex, enemy))}) + '\n')
                if lex['locals'][0] <= 0 or enemy['locals'][0] <= 0:
                    break
                act = decide(lex['motion'], False, math.hypot(enemy['pos'][0] - lex['pos'][0], enemy['pos'][1] - lex['pos'][1]), bearing(lex, enemy))
                if act == 'wait':
                    self.run_for(.12 if lex['motion'].upper().startswith(BUSY) else .06)
                elif act == 'approach':
                    self.rq(command='key', scan='48', duration=.13)
                elif act == 'punch':
                    self.rq(command='key', scan=attack, modifiers=[modifier], duration=.05)
                    log.write(json.dumps({'press': state.get('clock')}) + '\n')
                else:
                    self.rq(command='key', scan='4b' if act == 'turn-left' else '4d', duration=.2)

    def quit(self):
        try:
            self.control.request(self.dir, {'command': 'quit', 'stop_emulator': True})
        except (RuntimeError, TimeoutError) as error:
            print('quit:', error)


def live(fight, run, port, attack=None):
    session = Live(fight, run, port, attack)
    try:
        getattr(session, f'stage_{fight}')()
        print('staged', fight, run, flush=True)
        session.fight_loop()
    finally:
        session.quit()


def port_fight(play, enemy, enemy_key, attack, trace, mods=None, going=None, unstick=False):
    """Play.fight's loop with LATENCY added; trace rows are (clock, lex motion, enemy motion, lex HP, enemy HP). `mods` is the attack's modifier (Alt); `going()` can end the fight early.
    `unstick`: KP4 / KP6 circle in combat without turning, so a bearing past the auto-turn's 55 degrees can stay there for good; after three such moves in a row Lex leaves combat, turns and goes back in."""
    import world as worldmod
    world, vm, lex = play.world, play.vm, play.lex
    def wait(ticks):
        for _ in range(ticks):
            play.tick(1)
            trace.append((vm.tick * 2, lex.motion.upper(), enemy.motion.upper(), vm.objects['LEX'][0], vm.objects[enemy_key][0]))
    if not lex.combat:
        play.key(0x2e)
        wait(5)
    start = vm.tick
    presses = circled = 0
    while vm.objects['LEX'][0] > 0 and vm.objects[enemy_key][0] > 0 and vm.tick - start < 4000 and (going is None or going()):
        act = decide(lex.motion, lex.finished, math.hypot(*(enemy.pos[:2] - lex.pos[:2])), world.rel_angle(lex, enemy.pos))
        circled = circled + 1 if act.startswith('turn') else 0
        if unstick and circled > 3:
            circled = 0
            play.key(0x2e)
            wait(5)
            for _ in range(5):
                angle = world.rel_angle(lex, enemy.pos)
                if abs(angle) < 25 or vm.objects['LEX'][0] <= 0:
                    break
                play.key(0x4b if angle > 0 else 0x4d, 0, 8)     # a turn motion needs some frames to rotate
            play.key(0x2e)
            wait(5)
        elif act == 'wait':
            wait(LATENCY['wait'])
        elif act == 'approach':
            play.key(0x48, 0, 3)
            wait(LATENCY['key'])
        elif act == 'punch':
            wait(LATENCY['punch'])
            play.key(attack, worldmod.keys_mod.ALT if mods is None else mods, 2)
            wait(LATENCY['punch'])
            presses += 1
        else:
            play.key(0x4b if act == 'turn-left' else 0x4d, 0, 5)
            wait(LATENCY['key'])
    return presses


def port_samples(fight, seeds, chosen=None):
    import playthrough_full as pf
    import world as worldmod
    enemy_key, attack = FIGHTS[fight]
    mods = None
    if chosen:
        modifier, scan = parse_attack(chosen)
        attack, mods = int(scan, 16), worldmod.keys_mod.ALT if modifier == ALT_SCAN else worldmod.keys_mod.CTRL
    path = os.path.join(OUT, fight, chosen, 'port.jsonl') if chosen else os.path.join(OUT, fight, 'port.jsonl')
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, 'w').close()
    def save(seed, trace, presses):
        rows = [row for row in trace if row[3] > 0 and row[4] > 0]
        with open(path, 'a') as out:
            out.write(json.dumps({'seed': seed, 'trace': rows, 'presses': presses, 'last': trace[-1][3:]}) + '\n')
    if fight == 'guard1':
        import scenarios
        key = attack
        def body(self, enemy, alive, max_steps=3000, attack=None):
            self.sampled = []
            self.presses = port_fight(self, enemy, enemy_key, key, self.sampled, mods=mods)
            scenarios.sampled = (self.sampled, self.presses)
            return {'steps': 0, 'punches': self.presses, 'turns': 0, 'approaches': 0, 'waits': 0}
        scenarios.Play.fight = body
        for seed in range(seeds):
            if os.fork() == 0:
                scenarios.chaos_guard1_fight(seed=seed)
                save(seed, *scenarios.sampled)
                os._exit(0)
            if seed % 4 == 3:
                reap(4)
        reap()
        return
    run = pf.play(stop_after='operating-room' if fight == 'grdcon' else 'reactor-room')
    world, vm, lex = run.world, run.vm, run.lex
    enemy = world.figures[enemy_key]
    if fight == 'grdcon':
        world.set_pos(lex, [51000.0, -78000.0, -3100.0], raw=True)
        lex.heading = 0.0
        vm.globals['_lexconloc'] = 5
        run.until(lambda: vm.globals.get('_grdcon_active') == 1, 400, 'the guard is active')
    else:
        vm.globals['_reactor_safe'] = 1
        vm.objects['LEX'][0] = 100                  # the live sample starts there
        for y in (-110000, -120000, -130000, -134500, -138500):
            run.goto(-8950, y, radius=500, run=True)
    for seed in range(seeds):
        if os.fork() == 0:
            world.rng = random.Random(seed)
            trace = []
            presses = port_fight(run, enemy, enemy_key, attack, trace, mods=mods)
            save(seed, trace, presses)
            os._exit(0)
        if seed % 4 == 3:
            reap(4)
    reap()


def reap(count=None):
    try:
        while count is None or count > 0:
            os.wait()
            count = None if count is None else count - 1
    except ChildProcessError:
        pass


def attacks(trace):
    """The enemy's attacks in a trace: [{'motion', 'hit'}], `hit` = HP Lex lost during it."""
    out, current, previous = [], None, None
    for _, _, motion, lex_hp, _ in trace:
        if motion.startswith(('ATK_H', 'ATK_F', 'TONFA')):
            if current is None or current['motion'] != motion:
                if current:
                    out.append(current)
                current = {'motion': motion, 'hit': 0}
        elif current:
            out.append(current)
            current = None
        if current and previous is not None and lex_hp < previous:
            current['hit'] += previous - lex_hp
        previous = lex_hp
    return out + ([current] if current else [])


def summary(traces, presses, outcomes):
    """Rates per 1000 clock ticks over `traces`, and the damage values: the numbers the write-up compares."""
    clocks = sum(t[-1][0] - t[0][0] for t in traces if t)
    lex_lost = sum(t[0][3] - t[-1][3] for t in traces if t)
    enemy_lost = sum(t[0][4] - t[-1][4] for t in traces if t)
    enemy_hits = collections.Counter(a[4] - b[4] for t in traces for a, b in zip(t, t[1:]) if b[4] < a[4])
    lex_hits = collections.Counter(a[3] - b[3] for t in traces for a, b in zip(t, t[1:]) if b[3] < a[3])
    found = [a for t in traces for a in attacks(t)]
    by = collections.Counter(a['motion'] for a in found)
    landed = collections.Counter(a['motion'] for a in found if a['hit'])
    return {'fights': len(traces), 'clocks': clocks, 'wins': sum(1 for lex_hp, enemy_hp in outcomes if enemy_hp <= 0 and lex_hp > 0),
            'lex_hp_per_1000': round(1000 * lex_lost / max(clocks, 1), 1), 'enemy_hp_per_1000': round(1000 * enemy_lost / max(clocks, 1), 1),
            'hits_per_press': round(sum(enemy_hits.values()) / max(presses, 1), 2), 'damage_by_lex': sorted(enemy_hits.items()), 'damage_to_lex': sorted(lex_hits.items()),
            'attacks_per_1000': round(1000 * len(found) / max(clocks, 1), 1), 'attacks_landed': {k: f'{landed[k]}/{v}' for k, v in by.most_common()}}


def report(fight, attack=None):
    folder = os.path.join(OUT, fight, attack) if attack else os.path.join(OUT, fight)
    traces, presses, outcomes = [], 0, []
    for name in sorted(os.listdir(folder)):
        if name.startswith('live_') and name.endswith('.jsonl'):
            rows = [json.loads(line) for line in open(os.path.join(folder, name))]
            presses += sum('press' in r for r in rows)
            rows = [(r['clock'], r['lex'], r['enemy'], r['lex_hp'], r['enemy_hp']) for r in rows if 'press' not in r]
            outcomes.append(rows[-1][3:])
            traces.append([r for r in rows if r[3] > 0 and r[4] > 0])
    print('LIVE', json.dumps(summary(traces, presses, outcomes)))
    path = os.path.join(folder, 'port.jsonl')
    if os.path.exists(path):
        rows = [json.loads(line) for line in open(path)]
        print('PORT', json.dumps(summary([r['trace'] for r in rows], sum(r['presses'] for r in rows), [tuple(r['last']) for r in rows])))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('live', 'port', 'report'))
    parser.add_argument('fight', choices=sorted(FIGHTS))
    parser.add_argument('--run', type=int, default=1)
    parser.add_argument('--port', type=int, default=7101)
    parser.add_argument('--seeds', type=int, default=20)
    parser.add_argument('--attack', help='alt-4b, ctrl-49: the attack to play, from the fight\'s default')
    args = parser.parse_args(argv)
    if args.action == 'live':
        live(args.fight, args.run, args.port, args.attack)
    elif args.action == 'port':
        port_samples(args.fight, args.seeds, args.attack)
    else:
        report(args.fight, args.attack)


if __name__ == '__main__':
    main()
