"""Original wall-contact fixture replay and comparison failure checks."""
import copy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).parent))
import nurse_bounce

FIXTURE = Path(__file__).resolve().parents[2] / 'native/Tests/BioForgeCoreTests/Fixtures/nurse_bounce.json'


class NurseBounceOracleTests(unittest.TestCase):
    def setUp(self):
        self.samples = json.loads(FIXTURE.read_text())['samples']

    def test_original_wall_contacts_match_exactly(self):
        report = nurse_bounce.compare(self.samples)
        self.assertTrue(report['passed'])
        self.assertEqual(report['contacts'], 3)

    def test_a_coherent_but_different_observed_position_fails(self):
        sample = copy.deepcopy(self.samples[0])
        bot = sample['figures'][0]
        bot['pos'][0] -= 1
        bot['hull'][0] -= 1
        bot['hull'][3] -= 1
        self.assertFalse(nurse_bounce.compare([sample])['passed'])

    def test_no_collision_evidence_cannot_pass(self):
        for row in self.samples:
            row['figures'][0]['move_delta'] = [0, 0, 0]
        self.assertFalse(nurse_bounce.compare(self.samples)['passed'])


if __name__ == '__main__':
    unittest.main()
