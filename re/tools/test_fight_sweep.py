import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fight_sample as fs
import fight_sweep as fw


class FightSweepTests(unittest.TestCase):
    def test_the_sweep_leaves_out_only_the_moves_with_no_strength(self):
        names = {fw.attack_name(a) for a in fw.ATTACKS}
        self.assertEqual(len(names), 12)
        self.assertFalse(names & {'ATK_H1', 'ATK_H2', 'ATK_H3', 'ATK_F2'})
        self.assertTrue({'ATK_H4', 'ATK_H6', 'ATK_H8', 'ATK_F9'} <= names)

    def test_key_names_follow_the_modifier(self):
        self.assertEqual(fw.key_name(('H', 0x4b)), 'Alt+KP4')
        self.assertEqual(fw.key_name(('F', 0x49)), 'Ctrl+KP9')

    def test_the_table_ranks_wins_first_and_keeps_errors_out_of_the_means(self):
        row = lambda key, outcome, lex: {'key': key, 'attack': key, 'outcome': outcome, 'lex': [100, lex], 'enemy': [100, 0 if outcome == 'win' else 50], 'landed': 2, 'presses': 4, 'ticks': 100}
        rows = [row('a', 'loss', -5), row('b', 'win', 30), row('b', 'loss', 0), {'key': 'b', 'attack': 'b', 'outcome': 'error'}]
        table = fw.table(rows)
        self.assertEqual([line['key'] for line in table], ['b', 'a'])
        self.assertEqual((table[0]['wins'], table[0]['fights'], table[0]['errors'], table[0]['lex_left_in_wins']), (1, 3, 1, 30))
        self.assertEqual(table[1]['lex_lost'], 100)                # a death past zero counts as 100

    def test_a_live_attack_names_its_modifier(self):
        self.assertEqual(fs.parse_attack('alt-4b'), ('38', '4b'))
        self.assertEqual(fs.parse_attack('ctrl-49'), ('1d', '49'))


if __name__ == '__main__':
    unittest.main()
