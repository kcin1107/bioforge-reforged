import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import parity_core as parity


SAMPLES = os.path.join(HERE, 'parity_samples')


def read_trace(name):
    with open(os.path.join(SAMPLES, name), encoding='utf-8') as handle:
        return [json.loads(line) for line in handle]


class ParityCoreTests(unittest.TestCase):
    def test_scenario_input_schedule_and_vm_clock(self):
        scenario = parity.load_scenario(os.path.join(SAMPLES, 'scenario.json'))
        self.assertEqual(parity.clock_to_vm_tick(211), 105)
        self.assertEqual(parity.scheduled_inputs(scenario, 210, 100), [0x48])
        self.assertEqual(parity.scheduled_inputs(scenario, 300, 100), [])
        self.assertEqual(parity.due_pokes(scenario, 100, 100)[0]['name'], 'DR3')

    def test_validation_rejects_bad_input_range(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, 'bad.json')
            with open(path, 'w', encoding='utf-8') as handle:
                json.dump({'name': 'bad', 'figures': [], 'fields': [], 'sample_period': 1,
                           'inputs': [{'scan': '48', 'start': 2, 'end': 1}]}, handle)
            with self.assertRaisesRegex(ValueError, 'precedes'):
                parity.load_scenario(path)

    def test_save_boot_parsing(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, 'save.json')
            base = {'name': 'saved', 'figures': ['LEX'], 'fields': ['pos'], 'sample_period': 20,
                    'boot': {'save': '/tmp/GAME1.IM1', 'slot': 1, 'keys': 'esc l enter'}}
            with open(path, 'w', encoding='utf-8') as handle:
                json.dump(base, handle)
            self.assertEqual(parity.load_scenario(path)['boot']['slot'], 1)
            base['boot']['slot'] = 10
            with open(path, 'w', encoding='utf-8') as handle:
                json.dump(base, handle)
            with self.assertRaisesRegex(ValueError, 'slot'):
                parity.load_scenario(path)

    def test_anchor_alignment_and_wrapped_heading(self):
        original, port = read_trace('original.jsonl'), read_trace('port.jsonl')
        aligned = parity.align_traces(original, port, {'type': 'control', 'figure': 'LEX'})
        self.assertEqual(aligned['anchor'], {'original': 100, 'port': 200})
        self.assertEqual([pair['clock'] for pair in aligned['pairs']], [0, 10, 20])
        result = parity.compare_traces(original, port, figures=['LEX'], fields=['heading'],
                                       tolerances={'heading': 2}, anchor={'type': 'control', 'figure': 'LEX'})
        self.assertFalse(result['diverged'])
        self.assertAlmostEqual(result['drift']['LEX.heading']['max'], 2)

    def test_alignment_uses_nearest_monotonic_sample_within_window(self):
        original, port = read_trace('original.jsonl'), read_trace('port.jsonl')
        port[2]['clock'] = 212
        aligned = parity.align_traces(original, port, {'type': 'control', 'figure': 'LEX'}, 5)
        self.assertEqual(aligned['pairs'][1]['port_clock'], 212)
        self.assertEqual(aligned['pairs'][1]['clock_delta'], 2)
        empty = parity.compare_traces(original, port, {'figures': ['LEX'], 'fields': ['pos'],
                                                       'sample_period': 1,
                                                       'anchor': {'type': 'control', 'figure': 'MISSING'}})
        self.assertTrue(empty['divergent'])
        self.assertEqual(empty['error'], 'no aligned samples')

    def test_first_divergence_and_report_files(self):
        original, port = read_trace('original.jsonl'), read_trace('port.jsonl')
        result = parity.compare_traces(original, port, figures=['LEX'], fields=['pos', 'motion'],
                                       tolerances={'pos': 5}, anchor={'type': 'control', 'figure': 'LEX'})
        self.assertTrue(result['diverged'])
        self.assertEqual(result['first_divergence']['LEX.pos.x']['clock'], 20)
        self.assertEqual(result['first_divergence']['LEX.motion']['clock'], 20)
        self.assertAlmostEqual(result['first_divergence']['LEX.pos.x']['delta'], 10)
        with tempfile.TemporaryDirectory() as directory:
            parity.write_report(result, directory, 'sample')
            self.assertTrue(os.path.exists(os.path.join(directory, 'report.md')))
            self.assertTrue(os.path.exists(os.path.join(directory, 'positions.png')))
            with open(os.path.join(directory, 'report.json'), encoding='utf-8') as handle:
                self.assertTrue(json.load(handle)['diverged'])

    def test_motion_anchor(self):
        original, port = read_trace('original.jsonl'), read_trace('port.jsonl')
        self.assertEqual(parity.find_anchor(original, {'type': 'motion', 'figure': 'LEX', 'motion': 'WAKE_UP'}), 90)
        self.assertEqual(parity.find_anchor(port, {'type': 'motion', 'figure': 'LEX', 'motion': 'WAKE_UP'}), 190)

    def test_vector_components_and_case_insensitive_motion(self):
        original = [{'clock': 10, 'figures': {'LEX': {'flags': 0, 'pos': [1, 2, 3],
                                                       'locals': [10, 20], 'motion': 'walk'}}}]
        port = [{'clock': 10, 'figures': {'LEX': {'flags': 0, 'pos': [1, 9, 3],
                                                   'locals': [10, 22], 'motion': 'WALK'}}}]
        result = parity.compare_traces(original, port, figures=['LEX'], fields=['pos', 'locals', 'motion'],
                                       tolerances={'pos.y': 5, 'locals.1': 1})
        self.assertEqual(set(result['first_divergence']), {'LEX.pos.y', 'LEX.locals.1'})
        self.assertNotIn('LEX.motion', result['first_divergence'])

    def test_control_anchor_waits_for_out_of_bed_when_present(self):
        trace = [{'clock': 1, 'figures': {'LEX': {'flags': 0, 'motion': 'STAND'}}},
                 {'clock': 2, 'figures': {'LEX': {'flags': 2, 'motion': 'OUT_OF_BED'}}},
                 {'clock': 3, 'figures': {'LEX': {'flags': 0, 'motion': 'STAND'}}}]
        self.assertEqual(parity.find_anchor(trace, {'type': 'control', 'figure': 'LEX'}), 3)


if __name__ == '__main__':
    unittest.main()
