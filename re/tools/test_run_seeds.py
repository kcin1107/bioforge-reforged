import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import run_seeds  # noqa: E402


class Summary(unittest.TestCase):
    def test_a_finished_run(self):
        result = {'segments': [{'name': 'guard1', 'status': 'passed'}], 'problems': [{'severity': 'minor', 'message': 'a warning'}]}
        self.assertEqual(run_seeds.summary(result), (True, None, None))

    def test_a_stuck_run_names_the_segment_and_the_blocker(self):
        result = {'segments': [{'name': 'guard1', 'status': 'stuck'}, {'name': 'blaster', 'status': 'stuck'}],
                  'problems': [{'severity': 'minor', 'message': 'a warning'}, {'severity': 'blocker', 'message': 'Guard 1 fight lost\nmore'}]}
        self.assertEqual(run_seeds.summary(result), (False, 'guard1', 'Guard 1 fight lost'))


class Command(unittest.TestCase):
    def commands(self, seed, difficulty):
        seen = []
        real, out = run_seeds.subprocess.run, run_seeds.OUT
        run_seeds.subprocess.run = lambda command, **_: seen.append(command)
        try:
            with tempfile.TemporaryDirectory() as run_seeds.OUT:
                self.assertEqual(run_seeds.one(seed, difficulty), (seed, None))       # no report: a run that wrote nothing
                self.folder = run_seeds.OUT
        finally:
            run_seeds.subprocess.run, run_seeds.OUT = real, out
        return seen[0]

    def test_easy_keeps_its_folder_and_passes_no_level(self):
        command = self.commands(3, 'easy')
        self.assertEqual(command[command.index('--out') + 1], os.path.join(self.folder, '3'))
        self.assertNotIn('--difficulty', command)
        self.assertEqual(command[command.index('--seed') + 1], '3')

    def test_medium_and_hard_get_their_own_folder_and_the_flag(self):
        for level in ('medium', 'hard'):
            command = self.commands('default', level)
            self.assertEqual(command[command.index('--out') + 1], os.path.join(self.folder, level, 'default'))
            self.assertEqual(command[command.index('--difficulty') + 1], level)
            self.assertNotIn('--seed', command)


if __name__ == '__main__':
    unittest.main()
