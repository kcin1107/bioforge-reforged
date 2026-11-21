"""Send commands or run checks in an existing paused DOSBox-X session.

    python -I re/tools/dosbox_control.py send CONTROL '{"command":"sample","figure":"LEX"}'
    python -I re/tools/dosbox_control.py fall CONTROL --out re/out/fall_check
    python -I re/tools/dosbox_control.py combat CONTROL --target FIRSTBOT --out re/out/combat_check

Start dosbox_live.py --control CONTROL first. This client never boots or restarts the game.
"""
import argparse
import json
import math
from pathlib import Path
import sys
import time
import uuid


def request_timeout(command):
    """Return a bounded wait that covers this command's intentional runtime."""
    timeout = 30.0
    if command.get('command') == 'frames':
        count = command.get('count', 0)
        if isinstance(count, int) and not isinstance(count, bool):
            timeout += min(max(count, 0), 100) * 2.5
    elif command.get('command') == 'run_for':
        seconds, every = command.get('seconds', 0), command.get('every', .05)
        if (isinstance(seconds, (int, float)) and isinstance(every, (int, float))
                and math.isfinite(seconds) and math.isfinite(every) and every > 0):
            seconds = max(float(seconds), 0)
            timeout += min(seconds, 120) + math.ceil(min(seconds / every, 240)) * .1
    elif command.get('command') == 'key':
        duration = command.get('duration', 0)
        if isinstance(duration, (int, float)) and math.isfinite(duration):
            timeout += min(max(float(duration), 0), 120)
    return min(timeout, 300.0)


def request(directory, command):
    directory = Path(directory)
    incoming, outgoing = directory / 'in', directory / 'out'
    if not incoming.is_dir() or not outgoing.is_dir():
        raise RuntimeError('control session is not ready; start dosbox_live.py --control first')
    timeout = request_timeout(command)
    name = uuid.uuid4().hex + '.json'
    temporary = incoming / (name + '.tmp')
    temporary.write_text(json.dumps(command))
    temporary.replace(incoming / name)
    reply = outgoing / name
    deadline = time.monotonic() + timeout
    while not reply.exists():
        if time.monotonic() >= deadline:
            try:
                (incoming / name).unlink()
            except FileNotFoundError:
                if reply.exists():
                    continue
                raise TimeoutError('DOSBox-X control request timed out; command is already running and was not cancelled')
            raise TimeoutError('DOSBox-X control request timed out; its pending request was removed')
        time.sleep(.02)
    response = json.loads(reply.read_text())
    if not response['ok']:
        raise RuntimeError(response['error'])
    return response['result']


def fall(directory, height, output):
    if height <= 0:
        raise ValueError('fall height must be positive')
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    initial = request(directory, {'command': 'sample', 'figure': 'LEX'})
    probe = request(directory, {'command': 'frames', 'count': 1, 'figure': 'LEX'})['samples'][-1]
    if probe['clock'] == initial['clock']:
        raise RuntimeError('game clock did not advance: the persistent game session is not running')
    before = probe['figures'][0]
    target = before['pos'][2] + height
    request(directory, {'command': 'set_z', 'name': 'LEX', 'value': target})
    trace = [request(directory, {'command': 'sample', 'figure': 'LEX'})]
    trace += request(directory, {'command': 'frames', 'count': 12, 'figure': 'LEX'})['samples']

    def coherent(row):
        figure = row['figures'][0]
        fields = ('base', 'F', 'R')
        if not all(field in figure for field in fields):
            return True
        expected = figure['base'] + figure['F'] + figure['R']
        if figure['falling']:
            expected += figure['vz']
        return figure['pos'][2] == expected

    coherent_trace = [(index, row) for index, row in enumerate(trace) if coherent(row)]
    incoherent = len(trace) - len(coherent_trace)
    falling = [(index, row) for index, row in coherent_trace
               if row['figures'][0]['falling'] and row['figures'][0]['vz'] < 0]
    landed = [(index, row) for index, row in coherent_trace
              if row['figures'][0]['motion'].upper().startswith('LAND_')
              and not row['figures'][0]['falling'] and row['figures'][0]['vz'] == 0]
    before_landing = [sample for sample in falling if not landed or sample[0] < landed[0][0]]
    descent = len(before_landing) >= 2 and any(
        later[1]['clock'] != earlier[1]['clock']
        and later[1]['figures'][0]['vz'] < earlier[1]['figures'][0]['vz']
        for earlier, later in zip(before_landing, before_landing[1:]))
    report = {'passed': bool(landed and descent), 'height': height, 'start_z': target,
              'before': before, 'falling_samples': len(falling),
              'incoherent_samples': incoherent,
              'min_vz': min((row['figures'][0]['vz'] for _, row in coherent_trace), default=None),
              'landing_motion': landed[0][1]['figures'][0]['motion'] if landed else None,
              'clock_start': trace[0]['clock'], 'clock_end': trace[-1]['clock']}
    (output / 'original.jsonl').write_text(''.join(json.dumps(row) + '\n' for row in trace))
    (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    if not report['passed']:
        raise RuntimeError(f'fall/landing transition was not captured; inspect {output / "report.json"}')
    return report


def named_figure(state, name):
    return next((figure for figure in state['figures']
                 if figure['name'].upper() == name.upper()), None)


def health(figure):
    return figure['locals'][0]


def heading_delta(first, second):
    return abs((first - second + 180) % 360 - 180)


def nurse_pose(lex, nurse):
    """Describe Lex's angle from the nurse's persistent forward vector."""
    dx, dy = lex['pos'][0] - nurse['pos'][0], lex['pos'][1] - nurse['pos'][1]
    distance = math.hypot(dx, dy)
    heading = nurse['base_heading']
    forward = (-math.sin(math.radians(heading)), -math.cos(math.radians(heading)))
    cosine = (dx * forward[0] + dy * forward[1]) / distance if distance else 1
    return {'lex_pos': lex['pos'][:2], 'nurse_pos': nurse['pos'][:2],
            'nurse_heading': heading, 'distance': round(distance, 1),
            'angle': round(math.degrees(math.acos(max(-1, min(1, cosine)))), 1)}


def nurse(directory, output):
    """Exercise the nurse's authored front-hit then rear-wound response once.

    The scenario uses only the persistent test pose controls and normal key
    input.  It does not reset, reload, change health, or edit the nurse AI.
    """
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    trace = []
    trace_path = output / 'original.jsonl'
    trace_path.write_text('')

    def record(event):
        trace.append(event)
        with trace_path.open('a') as stream:
            stream.write(json.dumps(event) + '\n')

    def snapshot(stage):
        state = request(directory, {'command': 'sample'})
        record({'kind': 'snapshot', 'stage': stage, 'state': state})
        return state

    def frames(stage, count):
        rows = request(directory, {'command': 'frames', 'count': count, 'figure': 'LEX'})['samples']
        for row in rows:
            record({'kind': 'snapshot', 'stage': stage, 'state': row})
        return rows

    def setup(stage, command):
        record({'kind': 'setup', 'stage': stage, 'command': command})
        return request(directory, command)

    def input_(stage, command):
        record({'kind': 'input', 'stage': stage, 'command': command})
        return request(directory, command)

    def observe_attacks(rows):
        return [row['figures'][0]['motion'] for row in rows
                if row['figures'][0]['motion'].upper().startswith(('ATK_H', 'ATK_F'))]

    frames('initial_entry', 1)
    initial = snapshot('initial')
    lex = named_figure(initial, 'LEX')
    bot = named_figure(initial, 'FIRSTBOT')
    if lex is None or bot is None:
        raise RuntimeError('LEX and FIRSTBOT must exist in the persistent game session')
    if health(lex) <= 0 or health(bot) <= 0:
        raise RuntimeError('LEX and FIRSTBOT must both be alive')
    wound_before = bool(bot['locals'][4] & 2)
    if wound_before:
        # Continue the authored encounter instead of resetting its one-way wound state.
        zapped = bot['motion'].upper() == 'ZAPPED'
        if not zapped:
            # Explicit contact fixture inside the original DR_ZAP3 volume.
            # Damage, velocity, AI and trigger state remain original.
            setup('stage_bar_contact', {'command': 'set_xy', 'name': 'FIRSTBOT',
                                       'x': -10090, 'y': -15100})
        defeated = False
        last_bot = bot
        steps = 0
        while steps < 60 and not defeated:
            steps += 1
            rows = request(directory, {'command': 'run_for', 'seconds': .5, 'every': .5})['samples']
            for row in rows:
                record({'kind': 'snapshot', 'stage': 'continue_bounce', 'state': row})
                last_bot = named_figure(row, 'FIRSTBOT')
                if last_bot:
                    zapped = zapped or last_bot['motion'].upper() == 'ZAPPED'
                defeated = bool(zapped and (last_bot is None or health(last_bot) <= 0))
            if last_bot is None or health(named_figure(rows[-1], 'LEX')) <= 0:
                break
        report = {'phase': 'continue_bounce', 'passed': bool(zapped and defeated),
                  'rear_state_present': bot['locals'][3] == 2,
                  'observed_zapped': zapped, 'defeated': defeated, 'steps': steps,
                  'motion': last_bot['motion'] if last_bot else None,
                  'health': health(last_bot) if last_bot else None}
        (output / 'original.jsonl').write_text(''.join(json.dumps(row) + '\n' for row in trace))
        (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
        if not report['passed']:
            raise RuntimeError(f'nurse has not completed the zap/defeat sequence; inspect {output / "report.json"}')
        return report

    if not lex['flags'] & 0x40:
        input_('enter_combat', {'command': 'key', 'scan': '2e', 'duration': .2})
        initial = snapshot('after_enter_combat')
        lex = named_figure(initial, 'LEX')
        bot = named_figure(initial, 'FIRSTBOT')
        if lex is None or bot is None or not lex['flags'] & 0x40:
            raise RuntimeError('LEX did not enter combat mode')

    frames('front_setup_entry', 1)
    initial = snapshot('front_setup')
    bot = named_figure(initial, 'FIRSTBOT')
    setup('face_nurse_north', {'command': 'set_heading', 'name': 'FIRSTBOT', 'value': 0})
    setup('face_lex_toward_nurse', {'command': 'set_heading', 'name': 'LEX', 'value': 180})
    frames('front_heading_entry', 1)
    bot = named_figure(snapshot('front_heading'), 'FIRSTBOT')
    h = math.radians(bot['base_heading'])
    setup('place_lex_front', {'command': 'set_xy', 'name': 'LEX',
                              'x': round(bot['pos'][0] - 1000 * math.sin(h)),
                              'y': round(bot['pos'][1] - 1000 * math.cos(h))})
    frames('front_entry', 1)
    front = snapshot('front_pose')
    front_lex, front_bot = named_figure(front, 'LEX'), named_figure(front, 'FIRSTBOT')
    front_pose = nurse_pose(front_lex, front_bot)
    if front_pose['angle'] > 30:
        raise RuntimeError(f'front pose is not in FIRSTBOT forward arc ({front_pose["angle"]} degrees)')

    front_prior_motion = front_bot['motion']
    input_('front_attack', {'command': 'key', 'scan': '48', 'modifiers': ['38'], 'duration': .25})
    front_attacks = observe_attacks(frames('front_attack_frames', 12))
    after_front = snapshot('after_front_attack')
    front_bot_after = named_figure(after_front, 'FIRSTBOT')
    front_response = front_bot_after['motion'] if front_bot_after else ''
    fresh_front_response = front_response.upper() != front_prior_motion.upper() or (
        front_response.upper().startswith('RECOIL') and
        front_bot_after.get('frame', -1) < front_bot.get('frame', -1))
    defending_unchanged = front_response.upper() == front_prior_motion.upper() == 'DEFEND'
    front_passed = bool(front_attacks and not (front_bot_after['locals'][4] & 2)
                        and front_response.upper().startswith(('RECOIL', 'DEFEND'))
                        and fresh_front_response)

    defend = front_bot_after and front_bot_after['motion'].upper() == 'DEFEND'
    wait_chunks = 0
    while not defend and wait_chunks < 32:
        wait_chunks += 1
        rows = request(directory, {'command': 'run_for', 'seconds': .25, 'every': .25})['samples']
        for row in rows:
            record({'kind': 'snapshot', 'stage': 'wait_for_defend', 'state': row})
        after_front = rows[-1]
        front_bot_after = named_figure(after_front, 'FIRSTBOT')
        defend = front_bot_after and front_bot_after['motion'].upper() == 'DEFEND'
    current_heading = front_bot_after['base_heading'] if front_bot_after else None
    nurse_turned = current_heading is None or heading_delta(current_heading, 0) > 15
    rear_pose = None
    rear_attacks = []
    wound_after = None
    rear_status = None
    rear_flags = None
    bounce = {'observed': False, 'motion': None, 'flag16': False, 'avoid': []}
    rear_passed = False
    if front_passed and defend:
        frames('rear_setup_entry', 1)
        after_front = snapshot('rear_setup')
        front_bot_after = named_figure(after_front, 'FIRSTBOT')
        current_heading = front_bot_after['base_heading']
        setup('face_lex_rear_toward_nurse', {'command': 'set_heading', 'name': 'LEX',
                                             'value': current_heading})
        frames('rear_heading_entry', 1)
        rear_bot_ready = named_figure(snapshot('rear_heading'), 'FIRSTBOT')
        h = math.radians(rear_bot_ready['base_heading'])
        rear_x = round(rear_bot_ready['pos'][0] + 1000 * math.sin(h))
        rear_y = round(rear_bot_ready['pos'][1] + 1000 * math.cos(h))
        setup('place_lex_rear', {'command': 'set_xy', 'name': 'LEX', 'x': rear_x, 'y': rear_y})
        frames('rear_entry', 1)
        rear = snapshot('rear_pose')
        rear_lex, rear_bot = named_figure(rear, 'LEX'), named_figure(rear, 'FIRSTBOT')
        rear_pose = nurse_pose(rear_lex, rear_bot)
        if rear_pose['angle'] < 150:
            raise RuntimeError(f'rear pose is not behind FIRSTBOT ({rear_pose["angle"]} degrees)')
        input_('rear_attack', {'command': 'key', 'scan': '48', 'modifiers': ['38'], 'duration': .25})
        rear_attacks = observe_attacks(frames('rear_attack_frames', 12))
        after_rear = snapshot('after_rear_attack')
        rear_bot = named_figure(after_rear, 'FIRSTBOT')
        wound_after = bool(rear_bot and rear_bot['locals'][4] & 2)
        rear_status = rear_bot['locals'][3] if rear_bot else None
        rear_flags = rear_bot['flags'] if rear_bot else None
        bounce = {'observed': bool(rear_bot and rear_bot['motion'].upper() in ('START_BOUNCE', 'BOUNCE', 'ZAPPED')),
                  'motion': rear_bot['motion'] if rear_bot else None,
                  'flag16': bool(rear_bot and rear_bot['flags'] & 0x10),
                  'avoid': rear_bot['avoid'] if rear_bot else []}
        rear_passed = bool(rear_attacks and wound_after and rear_status == 2)
        for _ in range(5):
            if bounce['observed'] or not rear_passed:
                break
            frames('wait_for_bounce_frames', 12)
            after_rear = snapshot('wait_for_bounce')
            rear_bot = named_figure(after_rear, 'FIRSTBOT')
            if rear_bot:
                bounce = {'observed': rear_bot['motion'].upper() in ('START_BOUNCE', 'BOUNCE', 'ZAPPED'),
                          'motion': rear_bot['motion'], 'flag16': bool(rear_bot['flags'] & 0x10),
                          'avoid': rear_bot['avoid']}

    report = {
        'phase': 'front_rear',
        'passed': bool(front_passed and rear_passed),
        'front_passed': front_passed,
        'front_outcome': 'defending_unchanged' if defending_unchanged else front_response,
        'front_new_reaction': fresh_front_response,
        'rear_passed': rear_passed,
        'wound_before': wound_before,
        'wound_after': wound_after,
        'status': rear_status,
        'flags': {'front': front_bot_after['flags'] if front_bot_after else None, 'rear': rear_flags},
        'motions': {'front_attack': front_attacks, 'front_response': front_response,
                    'rear_attack': rear_attacks, 'bounce': bounce['motion']},
        'pose': {'front': front_pose, 'rear': rear_pose, 'nurse_turned': nurse_turned,
                 'defend_ready': bool(defend), 'defend_wait_chunks': wait_chunks},
        'bounce': bounce,
    }
    (output / 'original.jsonl').write_text(''.join(json.dumps(row) + '\n' for row in trace))
    (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    if not report['passed']:
        raise RuntimeError(f'nurse scenario did not reach the authored rear-wound response; inspect {output / "report.json"}')
    return report


def combat(directory, target_name, attacks, output):
    """Run bounded overhead attacks and require an observed, damaging combat result.

    The control server keeps the game paused around each request, so this does
    not reload, move, or otherwise repair the encounter if the target is out
    of range.  The JSONL trace contains every input and game snapshot used to
    decide the result.
    """
    if not 1 <= attacks <= 12:
        raise ValueError('attacks must be an integer from 1 through 12')
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    trace = []

    def snapshot(stage, state):
        trace.append({'kind': 'snapshot', 'stage': stage, 'state': state})
        return state

    def sample(stage):
        return snapshot(stage, request(directory, {'command': 'sample'}))

    # Start at Lex's update entry before taking the full, all-figure baseline.
    for row in request(directory, {'command': 'frames', 'count': 1, 'figure': 'LEX'})['samples']:
        snapshot('entry', row)
    initial = sample('initial')
    lex = named_figure(initial, 'LEX')
    target = named_figure(initial, target_name)
    if lex is None:
        raise RuntimeError('LEX is missing from the persistent game session')
    if target is None:
        raise RuntimeError(f'target {target_name!r} is missing from the persistent game session')

    target_before = health(target)
    combat_entered = bool(lex['flags'] & 0x40)
    attack_motions = []
    hit_reactions = []
    attempts_used = 0
    latest = initial
    if health(lex) > 0 and target_before > 0:
        if not combat_entered:
            command = {'command': 'key', 'scan': '2e', 'duration': .2}
            trace.append({'kind': 'input', 'stage': 'enter_combat', 'command': command})
            request(directory, command)
            latest = sample('after_enter_combat')
            live_lex = named_figure(latest, 'LEX')
            combat_entered = bool(live_lex and live_lex['flags'] & 0x40)

        if combat_entered:
            for attempt in range(1, attacks + 1):
                live_lex = named_figure(latest, 'LEX')
                live_target = named_figure(latest, target_name)
                if live_lex is None or live_target is None or health(live_lex) <= 0 or health(live_target) <= 0:
                    break
                prior_target_motion = live_target['motion']
                command = {'command': 'key', 'scan': '48', 'modifiers': ['38'], 'duration': .25}
                trace.append({'kind': 'input', 'stage': f'attack_{attempt}', 'command': command})
                request(directory, command)
                attempts_used = attempt
                rows = request(directory, {'command': 'frames', 'count': 12, 'figure': 'LEX'})['samples']
                for row in rows:
                    snapshot(f'attack_{attempt}_lex_frame', row)
                    frame_lex = named_figure(row, 'LEX')
                    if frame_lex and frame_lex['motion'].upper().startswith(('ATK_H', 'ATK_F')):
                        attack_motions.append(frame_lex['motion'])
                latest = sample(f'after_attack_{attempt}')
                current_lex = named_figure(latest, 'LEX')
                if current_lex and current_lex['motion'].upper().startswith(('ATK_H', 'ATK_F')):
                    attack_motions.append(current_lex['motion'])
                current_target = named_figure(latest, target_name)
                if current_target:
                    reaction = current_target['motion']
                    prior = prior_target_motion.upper()
                    if (reaction.upper().startswith('RECOIL')
                            and (not prior.startswith('RECOIL') or prior != reaction.upper())
                            and reaction not in hit_reactions):
                        hit_reactions.append(reaction)
                if current_target is None or health(current_target) <= 0:
                    break

    final_lex = named_figure(latest, 'LEX')
    final_target = named_figure(latest, target_name)
    target_after = health(final_target) if final_target else None
    report = {
        'passed': bool(combat_entered and attack_motions and target_after is not None
                       and (target_before > target_after or hit_reactions)),
        'target': target_name,
        'combat_entered': combat_entered,
        'observed_attack_motions': attack_motions,
        'hit_reactions': hit_reactions,
        'target_health_before': target_before,
        'target_health_after': target_after,
        'target_status_before': target['locals'][3],
        'target_status_after': final_target['locals'][3] if final_target else None,
        'target_wounds_before': target['locals'][4],
        'target_wounds_after': final_target['locals'][4] if final_target else None,
        'target_flags_after': final_target['flags'] if final_target else None,
        'target_motion_after': final_target['motion'] if final_target else None,
        'damage': target_before - target_after if target_after is not None else None,
        'attempts': attempts_used,
        'lex_health_after': health(final_lex) if final_lex else None,
    }
    (output / 'original.jsonl').write_text(''.join(json.dumps(row) + '\n' for row in trace))
    (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    if not report['passed']:
        raise RuntimeError(f'combat did not damage {target_name}; inspect {output / "report.json"}')
    return report


def push_nurse(directory, output):
    """Steer a wounded nurse toward DR3 using keys, then observe its defeat. No pose setup."""
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    trace = output / 'original.jsonl'
    trace.write_text('')

    def command(value):
        with trace.open('a') as stream:
            stream.write(json.dumps({'kind': 'command', 'command': value}) + '\n')
        result = request(directory, value)
        with trace.open('a') as stream:
            stream.write(json.dumps({'kind': 'result', 'result': result}) + '\n')
        return result

    state = command({'command': 'sample'})
    bot, lex = named_figure(state, 'FIRSTBOT'), named_figure(state, 'LEX')
    if not bot or not lex or health(lex) <= 0 or not bot['flags'] & 0x10:
        raise RuntimeError('push needs a living LEX and a wounded, bouncy FIRSTBOT')
    initial_health = health(lex)
    started_zapped = bot['motion'].upper() == 'ZAPPED'
    if lex['flags'] & 0x40:
        command({'command': 'key', 'scan': '2e', 'duration': .15})
        state = command({'command': 'sample'})
    observed_zap = started_zapped
    actions = 0
    for _ in range(60):
        bot, lex = named_figure(state, 'FIRSTBOT'), named_figure(state, 'LEX')
        if not bot or health(lex) < initial_health or lex['pos'][1] < -13900:
            break
        if bot['motion'].upper() == 'ZAPPED':
            observed_zap = True
            break
        dx, dy = -10090 - bot['pos'][0], -15100 - bot['pos'][1]
        distance = math.hypot(dx, dy)
        if not distance:
            break
        x, y = bot['pos'][0] + 500 * dx / distance, bot['pos'][1] + 500 * dy / distance
        desired = math.degrees(math.atan2(lex['pos'][0] - x, lex['pos'][1] - y))
        delta = (desired - lex['base_heading'] + 180) % 360 - 180
        scan, duration = ('4d' if delta > 0 else '4b'), min(.2, max(.06, abs(delta) / 90))
        if abs(delta) <= 7:
            scan, duration = '48', .35
        command({'command': 'key', 'scan': scan, 'duration': duration})
        command({'command': 'frames', 'figure': 'LEX', 'count': 1})
        state = command({'command': 'sample'})
        actions += 1
    bot = named_figure(state, 'FIRSTBOT')
    observed_zap = observed_zap or bool(bot and bot['motion'].upper() == 'ZAPPED')
    if observed_zap:
        for _ in range(40):
            state = command({'command': 'run_for', 'seconds': .5, 'every': .5})['samples'][-1]
            if named_figure(state, 'FIRSTBOT') is None or health(named_figure(state, 'LEX')) < initial_health:
                break
    lex = named_figure(state, 'LEX')
    passed = bool(observed_zap and named_figure(state, 'FIRSTBOT') is None and health(lex) == initial_health)
    report = {'passed': passed, 'actions': actions, 'observed_zapped': observed_zap,
              'started_zapped': started_zapped, 'lex_health': health(lex),
              'clock': state['clock'], 'input_only': True, 'setup_mutations': []}
    (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    if not passed:
        raise RuntimeError(f'push did not finish the nurse encounter; inspect {output / "report.json"}')
    return report


def escape(directory, output):
    """Walk from the cleared starting cell to BLK using keys and state feedback."""
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    trace = output / 'original.jsonl'
    trace.write_text('')

    def record(event):
        with trace.open('a') as stream:
            stream.write(json.dumps(event) + '\n')

    def command(value):
        record({'kind': 'command', 'command': value})
        result = request(directory, value)
        record({'kind': 'result', 'result': result})
        return result

    initial = command({'command': 'sample'})
    lex = named_figure(initial, 'LEX')
    if lex is None or health(lex) <= 0:
        raise RuntimeError('escape needs a living LEX')
    if named_figure(initial, 'FIRSTBOT') is not None:
        raise RuntimeError('escape needs the completed nurse defeat')
    if not (-13000 < lex['pos'][0] < -7500 and -16000 < lex['pos'][1] < -6000):
        raise RuntimeError('LEX must start in the cleared CE3 cell')
    initial_health = health(lex)
    for _ in range(12):
        if lex['motion'].upper() in ('STAND', 'ATK_STAND'):
            break
        rows = command({'command': 'run_for', 'seconds': .25, 'every': .25, 'figure': 'LEX'})['samples']
        lex = named_figure(rows[-1], 'LEX')
    else:
        raise RuntimeError('LEX has not returned to a controllable stance')
    if lex['flags'] & 0x40:
        command({'command': 'key', 'scan': '2e', 'duration': .15})
    actions, waypoint = 0, int(lex['pos'][1] <= -13000)
    bars_seen_on, bars_ready = False, False
    # Approach DR3 from inside CE3, then cross into the corridor. No world edits.
    targets = [(-10090, -13200), (-10090, -17100)]
    while actions < 80 and waypoint < len(targets) and health(lex) > 0:
        if health(lex) < initial_health or lex['motion'].upper().startswith('SHOCK'):
            break                                            # preserve the encounter after the first failed crossing
        x, y = targets[waypoint]
        dx, dy = x - lex['pos'][0], y - lex['pos'][1]
        distance = math.hypot(dx, dy)
        if distance < 350 or (waypoint == 0 and lex['pos'][1] <= -13000 and abs(dx) < 1000):
            waypoint += 1
            continue
        desired = math.degrees(math.atan2(-dx, -dy))
        delta = (desired - lex['base_heading'] + 180) % 360 - 180
        if abs(delta) > 8:
            scan, duration = ('4d' if delta > 0 else '4b'), min(.3, max(.08, abs(delta) / 90))
        else:
            scan, duration = '48', min(.5, max(.12, distance / 5000))
            if waypoint == 1 and lex['pos'][1] > -16000:
                bars = command({'command': 'variables', 'names': ['_BARS3_ON']})['values']['_BARS3_ON']
                bars_seen_on = bars_seen_on or bool(bars)
                bars_ready = bool(not bars and (bars_ready or bars_seen_on))
                if not bars_ready:
                    rows = command({'command': 'run_for', 'seconds': .25, 'every': .25, 'figure': 'LEX'})['samples']
                    lex = named_figure(rows[-1], 'LEX')
                    actions += 1
                    continue
        key_command = {'command': 'key', 'scan': scan, 'duration': duration}
        if waypoint == 1 and scan == '48':
            key_command['modifiers'] = ['2a']                 # run through the four-second off window
        command(key_command)
        rows = command({'command': 'run_for', 'seconds': .15, 'every': .15, 'figure': 'LEX'})['samples']
        lex = named_figure(rows[-1], 'LEX')
        if lex is None:
            raise RuntimeError('LEX disappeared during escape')
        actions += 1
    final = command({'command': 'sample'})
    lex = named_figure(final, 'LEX')
    passed = bool(lex and health(lex) == initial_health and lex['pos'][1] < -16500
                  and str(final.get('camera', '')).startswith('BLK'))
    report = {'passed': passed, 'actions': actions, 'waypoints': waypoint,
              'camera': final.get('camera'), 'clock': final.get('clock'),
              'lex_health': health(lex) if lex else None, 'pos': lex['pos'] if lex else None,
              'setup_mutations': [], 'input_only': True}
    (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    if not passed:
        raise RuntimeError(f'escape did not reach the corridor; inspect {output / "report.json"}')
    return report


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='action', required=True)
    send = commands.add_parser('send')
    send.add_argument('control')
    send.add_argument('json')
    check = commands.add_parser('fall')
    check.add_argument('control')
    check.add_argument('--height', type=int, default=2000)
    check.add_argument('--out', required=True)
    fight = commands.add_parser('combat')
    fight.add_argument('control')
    fight.add_argument('--target', default='FIRSTBOT')
    fight.add_argument('--attacks', type=int, default=6)
    fight.add_argument('--out', required=True)
    nurse_check = commands.add_parser('nurse')
    nurse_check.add_argument('control')
    nurse_check.add_argument('--out', required=True)
    push_check = commands.add_parser('push')
    push_check.add_argument('control')
    push_check.add_argument('--out', required=True)
    escape_check = commands.add_parser('escape')
    escape_check.add_argument('control')
    escape_check.add_argument('--out', required=True)
    args = parser.parse_args(argv)
    try:
        if args.action == 'send':
            result = request(args.control, json.loads(args.json))
        elif args.action == 'fall':
            result = fall(args.control, args.height, args.out)
        elif args.action == 'combat':
            result = combat(args.control, args.target, args.attacks, args.out)
        elif args.action == 'nurse':
            result = nurse(args.control, args.out)
        elif args.action == 'push':
            result = push_nurse(args.control, args.out)
        else:
            result = escape(args.control, args.out)
    except (RuntimeError, TimeoutError, ValueError) as error:
        parser.exit(1, f'{error}\n')
    print(json.dumps(result))


if __name__ == '__main__':
    main(sys.argv[1:])
