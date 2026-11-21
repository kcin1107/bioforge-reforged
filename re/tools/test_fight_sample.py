import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fight_sample as fs


class FightSampleTests(unittest.TestCase):
    def test_bearing_uses_the_figure_facing_and_the_ports_sign(self):
        lex = {'pos': [0, 0], 'base_heading': 0, 'heading': 45}        # heading 0 faces -y; `heading` holds the stance's yaw and is ignored
        self.assertAlmostEqual(fs.bearing(lex, {'pos': [0, -100]}), 0)
        self.assertAlmostEqual(fs.bearing(lex, {'pos': [100, 0]}), 90)   # +x is to his left when he faces -y
        self.assertAlmostEqual(fs.bearing(lex, {'pos': [-100, 0]}), -90)

    def test_decide_follows_the_fight_loop(self):
        self.assertEqual(fs.decide('atk_h8', False, 1000, 0), 'wait')
        self.assertEqual(fs.decide('ATK_H8', True, 1000, 0), 'punch')
        self.assertEqual(fs.decide('ATK_STAND', False, 1000, 60), 'turn-left')
        self.assertEqual(fs.decide('ATK_STAND', False, 1000, -60), 'turn-right')
        self.assertEqual(fs.decide('ATK_STAND', False, 2000, 0), 'approach')
        self.assertEqual(fs.decide('ATK_STAND', False, 1000, 30), 'wait')

    def test_attacks_count_starts_and_the_hp_lost_during_them(self):
        trace = [(0, 'S', 'ATK_STAND', 100, 100), (2, 'S', 'ATK_H7', 100, 100), (4, 'S', 'ATK_H7', 84, 100), (6, 'S', 'ATK_STAND', 84, 100), (8, 'S', 'ATK_F4', 84, 100)]
        self.assertEqual(fs.attacks(trace), [{'motion': 'ATK_H7', 'hit': 16}, {'motion': 'ATK_F4', 'hit': 0}])

    def test_summary_rates_are_per_1000_clock_ticks(self):
        trace = [(0, 'S', 'ATK_STAND', 100, 100), (1000, 'S', 'ATK_STAND', 84, 100), (2000, 'S', 'ATK_STAND', 84, 79)]
        s = fs.summary([trace], 2, [(84, -5)])
        self.assertEqual((s['clocks'], s['wins'], s['lex_hp_per_1000'], s['enemy_hp_per_1000'], s['hits_per_press']), (2000, 1, 8.0, 10.5, .5))
        self.assertEqual((s['damage_by_lex'], s['damage_to_lex']), ([(21, 1)], [(16, 1)]))


if __name__ == '__main__':
    unittest.main()
