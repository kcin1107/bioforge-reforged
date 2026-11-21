import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent))
import dosbox_control as control


def state(clock, falling=False, vz=0, motion='stand', z=-5133, base=None):
    return {'clock': clock, 'figures': [{'pos': [1, 2, z], 'falling': falling,
                                       'vz': vz, 'motion': motion, 'F': -100,
                                       'R': -33, 'base': z + 133 - (vz if falling else 0)
                                       if base is None else base}]}


def combat_state(clock, lex_flags=0x40, lex_motion='stand', lex_hp=100, target_hp=50,
                 target_motion='stand'):
    return {'clock': clock, 'figures': [
        {'name': 'LEX', 'flags': lex_flags, 'locals': [lex_hp] + [0] * 9, 'motion': lex_motion},
        {'name': 'FIRSTBOT', 'flags': 0, 'locals': [target_hp] + [0] * 9, 'motion': target_motion},
    ]}


def nurse_state(clock, lex_y=-1000, bot_motion='atk_stand', wound=0, status=0,
                lex_motion='stand', bot_flags=0):
    return {'clock': clock, 'figures': [
        {'name': 'LEX', 'flags': 0x40, 'locals': [100, 0, 0, 0, 0], 'motion': lex_motion,
         'pos': [0, lex_y, -5133], 'base_heading': 180, 'avoid': []},
        {'name': 'FIRSTBOT', 'flags': bot_flags, 'locals': [50, 0, 0, status, wound, 50],
         'motion': bot_motion, 'pos': [0, 0, -5133], 'base_heading': 0, 'avoid': []},
    ]}


class FallCheckTests(unittest.TestCase):
    def test_timed_out_request_removes_queued_input(self):
        with tempfile.TemporaryDirectory() as directory:
            control_dir = Path(directory)
            (control_dir / 'in').mkdir()
            (control_dir / 'out').mkdir()
            with mock.patch.object(control.time, 'monotonic', side_effect=[0, 31]):
                with self.assertRaisesRegex(TimeoutError, 'pending request was removed'):
                    control.request(control_dir, {'command': 'sample'})
            self.assertEqual(list((control_dir / 'in').iterdir()), [])

    def test_timed_out_running_request_is_not_cancelled(self):
        with tempfile.TemporaryDirectory() as directory:
            control_dir = Path(directory)
            (control_dir / 'in').mkdir()
            (control_dir / 'out').mkdir()
            (control_dir / 'running').mkdir()
            with mock.patch.object(control.uuid, 'uuid4') as new_id, \
                 mock.patch.object(control.time, 'monotonic', side_effect=[0, 1, 31]), \
                 mock.patch.object(control.time, 'sleep') as sleep:
                new_id.return_value.hex = 'request'
                sleep.side_effect = lambda _seconds: (control_dir / 'in' / 'request.json').replace(
                    control_dir / 'running' / 'request.json')
                with self.assertRaisesRegex(TimeoutError, 'already running and was not cancelled'):
                    control.request(control_dir, {'command': 'sample'})
            self.assertTrue((control_dir / 'running' / 'request.json').exists())

    def test_command_aware_timeouts_are_bounded(self):
        self.assertEqual(control.request_timeout({'command': 'frames', 'count': 12}), 60)
        self.assertEqual(control.request_timeout({'command': 'run_for', 'seconds': 60, 'every': .5}), 102)
        self.assertEqual(control.request_timeout({'command': 'key', 'duration': 45}), 75)
        self.assertEqual(control.request_timeout({'command': 'run_for', 'seconds': float('inf'), 'every': 1}), 30)
        self.assertEqual(control.request_timeout({'command': 'key', 'duration': float('nan')}), 30)

    def test_menu_with_frozen_clock_prevents_height_injection(self):
        with tempfile.TemporaryDirectory() as output, \
             mock.patch.object(control, 'request', side_effect=[state(10), {'samples': [state(10)]}]) as send:
            with self.assertRaisesRegex(RuntimeError, 'persistent game session is not running'):
                control.fall('control', 2000, output)
            self.assertEqual(send.call_count, 2)
            self.assertEqual(send.call_args.args[1], {'command': 'frames', 'count': 1, 'figure': 'LEX'})

    def test_observed_fall_and_landing_write_a_passing_report(self):
        replies = [state(10), {'samples': [state(12)]}, {}, state(12),
                   {'samples': [state(13, True, -102, z=-5235),
                                state(14, True, -204, z=-5439),
                                state(18, motion='land_medium', z=-5353)]}]
        with tempfile.TemporaryDirectory() as output, \
             mock.patch.object(control, 'request', side_effect=replies):
            report = control.fall('control', 2000, output)
            self.assertTrue(report['passed'])
            self.assertEqual(report['landing_motion'], 'land_medium')
            self.assertEqual(report['incoherent_samples'], 0)
            self.assertEqual(json.loads((Path(output) / 'report.json').read_text()), report)
            self.assertEqual(len((Path(output) / 'original.jsonl').read_text().splitlines()), 4)

    def test_single_fall_with_an_incoherent_pose_does_not_pass(self):
        replies = [state(10), {'samples': [state(12)]}, {}, state(12),
                   {'samples': [state(13, True, -102, z=-5235),
                                state(14, True, -204, z=-816928, base=-5306),
                                state(18, motion='land_soft', z=-5353)]}]
        with tempfile.TemporaryDirectory() as output, \
             mock.patch.object(control, 'request', side_effect=replies):
            with self.assertRaisesRegex(RuntimeError, 'transition was not captured'):
                control.fall('control', 2000, output)
            report = json.loads((Path(output) / 'report.json').read_text())
            self.assertFalse(report['passed'])
            self.assertEqual(report['falling_samples'], 1)
            self.assertEqual(report['incoherent_samples'], 1)

    def test_actual_fall_update_rows_are_coherent_before_model_catches_up(self):
        first = state(13, True, -102, z=-3235, base=-5405)
        first['figures'][0].update({'F': 2312, 'R': -40})
        second = state(14, True, -204, z=-3439, base=-5507)
        second['figures'][0].update({'F': 2312, 'R': -40})
        replies = [state(10), {'samples': [state(12)]}, {}, state(12),
                   {'samples': [first, second, state(18, motion='land_medium', z=-5353)]}]
        with tempfile.TemporaryDirectory() as output, \
             mock.patch.object(control, 'request', side_effect=replies):
            report = control.fall('control', 2000, output)
        self.assertTrue(report['passed'])
        self.assertEqual(report['falling_samples'], 2)
        self.assertEqual(report['incoherent_samples'], 0)


class CombatCheckTests(unittest.TestCase):
    def test_combat_uses_alt_keypad_attack_and_writes_passing_report(self):
        replies = [
            {'samples': [combat_state(10, lex_flags=0)]},
            combat_state(11, lex_flags=0),
            {}, combat_state(12, lex_flags=0x40), {},
            {'samples': [combat_state(13, lex_motion='atk_h8'), combat_state(14, lex_motion='atk_h8')]},
            combat_state(15, target_hp=0),
        ]
        with tempfile.TemporaryDirectory() as output, \
             mock.patch.object(control, 'request', side_effect=replies) as send:
            report = control.combat('control', 'FIRSTBOT', 6, output)
            self.assertTrue(report['passed'])
            self.assertTrue(report['combat_entered'])
            self.assertEqual(report['damage'], 50)
            self.assertEqual(report['attempts'], 1)
            requests = [call.args[1] for call in send.call_args_list]
            self.assertIn({'command': 'key', 'scan': '2e', 'duration': .2}, requests)
            self.assertIn({'command': 'key', 'scan': '48', 'modifiers': ['38'], 'duration': .25}, requests)
            saved = json.loads((Path(output) / 'report.json').read_text())
            self.assertEqual(saved, report)
            trace = [json.loads(line) for line in (Path(output) / 'original.jsonl').read_text().splitlines()]
            self.assertTrue(any(row['kind'] == 'input' and row['stage'] == 'attack_1' for row in trace))

    def test_combat_does_not_toggle_when_lex_is_already_in_combat(self):
        replies = [
            {'samples': [combat_state(10)]}, combat_state(11), {},
            {'samples': [combat_state(12, lex_motion='atk_f8')]}, combat_state(13, target_hp=45),
        ]
        with tempfile.TemporaryDirectory() as output, \
             mock.patch.object(control, 'request', side_effect=replies) as send:
            report = control.combat('control', 'FIRSTBOT', 1, output)
        self.assertTrue(report['passed'])
        requests = [call.args[1] for call in send.call_args_list]
        self.assertNotIn({'command': 'key', 'scan': '2e', 'duration': .2}, requests)

    def test_attack_motion_without_damage_does_not_pass(self):
        replies = [
            {'samples': [combat_state(10)]}, combat_state(11), {},
            {'samples': [combat_state(12, lex_motion='atk_h8')]}, combat_state(13, target_hp=50),
        ]
        with tempfile.TemporaryDirectory() as output, \
             mock.patch.object(control, 'request', side_effect=replies):
            with self.assertRaisesRegex(RuntimeError, 'did not damage FIRSTBOT'):
                control.combat('control', 'FIRSTBOT', 1, output)
            report = json.loads((Path(output) / 'report.json').read_text())
        self.assertFalse(report['passed'])
        self.assertEqual(report['damage'], 0)

    def test_nurse_recoil_is_a_hit_when_its_health_does_not_change(self):
        replies = [
            {'samples': [combat_state(10, target_motion='atk_stand')]},
            combat_state(11, target_motion='atk_stand'), {},
            {'samples': [combat_state(12, lex_motion='atk_h8', target_motion='atk_stand')]},
            combat_state(13, target_hp=50, target_motion='recoil_tl'),
        ]
        with tempfile.TemporaryDirectory() as output, \
             mock.patch.object(control, 'request', side_effect=replies):
            report = control.combat('control', 'FIRSTBOT', 1, output)
        self.assertTrue(report['passed'])
        self.assertEqual(report['damage'], 0)
        self.assertEqual(report['hit_reactions'], ['recoil_tl'])

    def test_existing_identical_nurse_recoil_does_not_count_as_a_new_hit(self):
        replies = [
            {'samples': [combat_state(10, target_motion='recoil_tl')]},
            combat_state(11, target_motion='recoil_tl'), {},
            {'samples': [combat_state(12, lex_motion='atk_h8', target_motion='recoil_tl')]},
            combat_state(13, target_hp=50, target_motion='recoil_tl'),
        ]
        with tempfile.TemporaryDirectory() as output, \
             mock.patch.object(control, 'request', side_effect=replies):
            with self.assertRaisesRegex(RuntimeError, 'did not damage FIRSTBOT'):
                control.combat('control', 'FIRSTBOT', 1, output)
            report = json.loads((Path(output) / 'report.json').read_text())
        self.assertFalse(report['passed'])
        self.assertEqual(report['hit_reactions'], [])

    def test_combat_rejects_an_unbounded_attempt_count(self):
        with self.assertRaisesRegex(ValueError, '1 through 12'):
            control.combat('control', 'FIRSTBOT', 13, 'unused')


class PushScenarioTests(unittest.TestCase):
    def test_push_uses_keys_and_observes_defeat_without_pose_edits(self):
        stage = 0
        def reply(_directory, command):
            nonlocal stage
            state = nurse_state(stage, bot_motion='ZAPPED' if stage else 'BOUNCE', wound=2, status=2)
            lex, bot = state['figures'][:2]
            lex.update(flags=0, base_heading=0, pos=[-10090, -11000, -5133])
            bot.update(flags=0x10, pos=[-10090, -13500, -4500])
            if command['command'] == 'key':
                self.assertEqual(command['scan'], '48')
                stage = 1
                return {}
            if command['command'] == 'run_for':
                state['figures'].remove(bot)
                return {'samples': [state]}
            return state
        with tempfile.TemporaryDirectory() as output, mock.patch.object(control, 'request', side_effect=reply) as send:
            report = control.push_nurse('control', output)
            self.assertTrue(report['passed'])
            self.assertFalse(report['started_zapped'])
            self.assertEqual(report['actions'], 1)
            self.assertEqual(report['setup_mutations'], [])
            self.assertTrue(set(call.args[1]['command'] for call in send.call_args_list)
                            <= {'sample', 'key', 'frames', 'run_for'})

    def test_push_rejects_an_unwounded_nurse(self):
        with tempfile.TemporaryDirectory() as output, mock.patch.object(control, 'request', return_value=nurse_state(1)):
            with self.assertRaisesRegex(RuntimeError, 'wounded, bouncy'):
                control.push_nurse('control', output)


class EscapeScenarioTests(unittest.TestCase):
    def test_approach_can_pass_the_waypoint_without_orbiting_it(self):
        stage = 0
        bars = iter([1, 0])
        def reply(_directory, command):
            nonlocal stage
            lex = nurse_state(1)['figures'][0]
            lex.update(flags=0, base_heading=0, pos=[-10090, [-12500, -13550, -17100][stage], -5133])
            state = {'clock': stage, 'camera': 'BLK1' if stage == 2 else 'CE33', 'figures': [lex]}
            if command['command'] == 'variables':
                return {'values': {'_BARS3_ON': next(bars)}}
            if command['command'] == 'key':
                self.assertEqual(command['scan'], '48')
                stage += 1
                return {}
            return {'samples': [state]} if command['command'] == 'run_for' else state
        with tempfile.TemporaryDirectory() as output, mock.patch.object(control, 'request', side_effect=reply):
            self.assertTrue(control.escape('control', output)['passed'])

    def test_escape_waits_for_a_new_off_window_and_uses_only_keys(self):
        for camera, damaged, start_y in (('BLK1', False, -14000), ('BLK1', False, -13100),
                                         ('CE33', False, -14000), ('BLK1', True, -14000)):
            with self.subTest(camera=camera, damaged=damaged), tempfile.TemporaryDirectory() as output:
                outside = False
                bars = iter([0, 1, 0])
                def reply(_directory, command):
                    nonlocal outside
                    lex = nurse_state(1)['figures'][0]
                    lex.update(flags=0, base_heading=0, pos=[-10090, -17100 if outside else start_y, -5133])
                    lex['locals'][0] = 81 if outside and damaged else 100
                    state = {'clock': 1, 'camera': camera if outside else 'CE33', 'figures': [lex]}
                    if command['command'] == 'variables':
                        return {'values': {'_BARS3_ON': next(bars)}}
                    if command['command'] == 'key':
                        self.assertEqual(command['scan'], '48')
                        self.assertEqual(command['modifiers'], ['2a'])
                        outside = True
                        return {}
                    return {'samples': [state]} if command['command'] == 'run_for' else state
                with mock.patch.object(control, 'request', side_effect=reply) as send:
                    if camera == 'BLK1' and not damaged:
                        report = control.escape('control', output)
                        self.assertTrue(report['passed'])
                        self.assertTrue(report['input_only'])
                    else:
                        with self.assertRaisesRegex(RuntimeError, 'did not reach the corridor'):
                            control.escape('control', output)
                    commands = [call.args[1]['command'] for call in send.call_args_list]
                    self.assertEqual(commands.count('variables'), 3)
                    self.assertEqual(commands.count('key'), 1)
                    self.assertTrue(set(commands) <= {'sample', 'variables', 'run_for', 'key'})


class NurseScenarioTests(unittest.TestCase):
    def test_failed_setup_keeps_the_partial_trace(self):
        responses = [{'samples': [nurse_state(1)]}, nurse_state(1),
                     {'samples': [nurse_state(2)]}, nurse_state(2), RuntimeError('readback failed')]
        with tempfile.TemporaryDirectory() as output, \
             mock.patch.object(control, 'request', side_effect=responses):
            with self.assertRaisesRegex(RuntimeError, 'readback failed'):
                control.nurse('control', output)
            trace = list(map(json.loads, Path(output, 'original.jsonl').read_text().splitlines()))
            self.assertEqual(trace[-1]['stage'], 'face_nurse_north')
            self.assertEqual(trace[-1]['kind'], 'setup')

    def test_wounded_encounter_stages_contact_then_observes_zap_and_defeat(self):
        baseline = nurse_state(1, bot_motion='BOUNCE', wound=2, status=2)
        zapped = nurse_state(2, bot_motion='ZAPPED', wound=2, status=2)
        defeated = nurse_state(3, bot_motion='ZAPPED', wound=2, status=2)
        defeated['figures'][1]['locals'][0] = 0
        with tempfile.TemporaryDirectory() as output, \
             mock.patch.object(control, 'request', side_effect=[{'samples': [baseline]}, baseline, {}, {'samples': [zapped]},
                                                               {'samples': [defeated]}]) as send:
            report = control.nurse('control', output)
            self.assertTrue(report['passed'])
            self.assertTrue(report['observed_zapped'])
            self.assertTrue(report['defeated'])
            self.assertEqual(send.call_args_list[2].args[1],
                             {'command': 'set_xy', 'name': 'FIRSTBOT', 'x': -10090, 'y': -15100})
            self.assertEqual([call.args[1]['command'] for call in send.call_args_list],
                             ['frames', 'sample', 'set_xy', 'run_for', 'run_for'])

    def test_bounce_without_zap_times_out_without_restarting(self):
        baseline = nurse_state(1, bot_motion='BOUNCE', wound=2, status=2)
        def reply(_directory, command):
            return baseline if command['command'] == 'sample' else {'samples': [baseline]}
        with tempfile.TemporaryDirectory() as output, \
             mock.patch.object(control, 'request', side_effect=reply) as send:
            with self.assertRaisesRegex(RuntimeError, 'zap/defeat'):
                control.nurse('control', output)
            report = json.loads((Path(output) / 'report.json').read_text())
            self.assertFalse(report['passed'])
            self.assertEqual(report['steps'], 60)
            self.assertEqual(send.call_count, 63)

    def test_front_then_rear_nurse_response_passes(self):
        frame = lambda motion: {'samples': [{'figures': [{'motion': motion}]}]}
        replies = [
            frame('stand'), nurse_state(1), frame('stand'), nurse_state(1),
            {}, {}, frame('stand'), nurse_state(2), {}, frame('stand'), nurse_state(2, bot_motion='atk_stand'), {},
            frame('atk_h8'), nurse_state(3, bot_motion='defend'), frame('stand'),
            nurse_state(3, bot_motion='defend'), {}, frame('stand'),
            nurse_state(3, bot_motion='defend'), {},
            frame('stand'), nurse_state(4, lex_y=1000, bot_motion='defend'), {},
            frame('atk_h8'), nurse_state(5, lex_y=1000, bot_motion='start_bounce', wound=2,
                                         status=2, bot_flags=0x10),
        ]
        with tempfile.TemporaryDirectory() as output, \
             mock.patch.object(control, 'request', side_effect=replies) as send:
            report = control.nurse('control', output)
            self.assertTrue(report['passed'])
            self.assertTrue(report['front_passed'])
            self.assertTrue(report['front_new_reaction'])
            self.assertTrue(report['rear_passed'])
            self.assertTrue(report['wound_after'])
            self.assertEqual(report['status'], 2)
            commands = [call.args[1] for call in send.call_args_list]
            self.assertIn({'command': 'set_heading', 'name': 'FIRSTBOT', 'value': 0}, commands)
            self.assertIn({'command': 'key', 'scan': '48', 'modifiers': ['38'], 'duration': .25}, commands)

    def test_unchanged_defend_does_not_pass_front_attack(self):
        def reply(_directory, command):
            if command['command'] == 'frames':
                motion = 'atk_h8' if command['count'] == 12 else 'stand'
                return {'samples': [{'figures': [{'motion': motion}]}]}
            if command['command'] == 'sample':
                return nurse_state(1, bot_motion='defend')
            if command['command'] == 'run_for':
                return {'samples': [nurse_state(1, bot_motion='defend')]}
            return {}

        with tempfile.TemporaryDirectory() as output, \
             mock.patch.object(control, 'request', side_effect=reply):
            with self.assertRaisesRegex(RuntimeError, 'rear-wound'):
                control.nurse('control', output)
            report = json.loads((Path(output) / 'report.json').read_text())
        self.assertFalse(report['front_passed'])
        self.assertEqual(report['front_outcome'], 'defending_unchanged')

    def test_missing_new_rear_wound_fails(self):
        frame = lambda motion: {'samples': [{'figures': [{'motion': motion}]}]}
        replies = [
            frame('stand'), nurse_state(1), frame('stand'), nurse_state(1),
            {}, {}, frame('stand'), nurse_state(2), {}, frame('stand'), nurse_state(2), {},
            frame('atk_h8'), nurse_state(3, bot_motion='defend'), frame('stand'),
            nurse_state(3, bot_motion='defend'), {}, frame('stand'),
            nurse_state(3, bot_motion='defend'), {},
            frame('stand'), nurse_state(4, lex_y=1000, bot_motion='defend'), {},
            frame('atk_h8'), nurse_state(5, lex_y=1000, bot_motion='defend'),
        ]
        with tempfile.TemporaryDirectory() as output, \
             mock.patch.object(control, 'request', side_effect=replies):
            with self.assertRaisesRegex(RuntimeError, 'rear-wound'):
                control.nurse('control', output)
            report = json.loads((Path(output) / 'report.json').read_text())
        self.assertFalse(report['passed'])
        self.assertFalse(report['wound_after'])

    def test_defend_timeout_is_bounded_and_fails(self):
        frames_seen = []
        samples = iter([nurse_state(1), nurse_state(2), nurse_state(3, bot_motion='recoil_tl')])

        def reply(_directory, command):
            if command['command'] == 'sample':
                try:
                    return next(samples)
                except StopIteration:
                    return nurse_state(4, bot_motion='recoil_tl')
            if command['command'] == 'run_for':
                frames_seen.append('wait')
                return {'samples': [nurse_state(4, bot_motion='recoil_tl')]}
            if command['command'] == 'frames':
                frames_seen.append(command['count'])
                motion = 'atk_h8' if command['count'] == 12 else 'stand'
                return {'samples': [{'figures': [{'motion': motion}]}]}
            return {}

        with tempfile.TemporaryDirectory() as output, \
             mock.patch.object(control, 'request', side_effect=reply):
            with self.assertRaisesRegex(RuntimeError, 'rear-wound'):
                control.nurse('control', output)
        self.assertEqual(frames_seen.count('wait'), 32)

if __name__ == '__main__':
    unittest.main()
