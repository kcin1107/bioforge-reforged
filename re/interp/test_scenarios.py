"""End-to-end, deterministic scenarios across independent BioForge levels."""
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import scenarios  # noqa: E402


class Scenarios(unittest.TestCase):
    def assert_known_opening_warnings_only(self, result):
        self.assertEqual([warning for warning in result['warnings']
                          if not (warning == 'CAMERA SHOW TITLE: logged only, no switch'
                                  or ('CAYNAN_PACE:' in warning and 'BREAK 2 != innermost' in warning))], [])

    def test_opening_escape_is_unarmed_and_changes_room_camera(self):
        result = scenarios.opening_escape()
        self.assert_known_opening_warnings_only(result)
        ready, unarmed, outside = result['checkpoints']
        self.assertEqual(ready['level'], 'CHAOS')
        self.assertEqual(ready['items']['MY_BATTERY']['slot'], 'INVENTORY')
        self.assertEqual(unarmed['player']['motion'], 'STAND')
        self.assertNotEqual(ready['player']['position'], outside['player']['position'])
        self.assertLess(outside['player']['position'][1], -15548)  # beyond DR3's far edge
        self.assertNotEqual(ready['camera'], outside['camera'])
        self.assertEqual(outside['camera'], 'BLK1')                # the corridor's CAM_BLK1 trigger forces it
        self.assertIn('trigger forces BLK1', [c[3] for c in result['camera_changes']])
        self.assertEqual(result['frames']['opening-ready'].shape, (200, 320, 3))
        self.assertFalse(np.array_equal(result['frames']['opening-ready'], result['frames']['outside-cell']))

    def test_opening_revival_comes_from_live_nurse_hits(self):
        result = scenarios.opening_revival()
        self.assert_known_opening_warnings_only(result)
        point = result['checkpoints'][0]
        self.assertEqual(result['final_globals']['_lex_drugged'], 2)
        self.assertEqual(result['final_globals']['_lexrevived'], 1)
        hits = [hit for hit in result['hits'] if hit[-1] == 'HIT_PLAYER_ATK_SYRINGE']
        self.assertGreaterEqual(len(hits), 2)
        self.assertEqual(point['player']['motion'], 'STAND')
        self.assertTrue(point['player']['collisions'])

    def test_nurse_punches_bounce_and_authored_defeat(self):
        result = scenarios.opening_nurse_defeat()
        encounter = result['encounter']
        self.assertEqual(len(encounter['front']['hits']), 1)
        self.assertEqual(encounter['front']['wound'] & 2, 0)
        self.assertEqual(len(encounter['rear']['hits']), 1)
        self.assertEqual(encounter['rear']['wound'] & 2, 2)
        self.assertEqual(encounter['rear']['status'], 2)
        self.assertTrue(encounter['rear']['bouncy'])
        self.assertEqual([fixture['stage'] for fixture in encounter['fixtures']], ['front', 'rear'])
        self.assertEqual(set(encounter['fixtures'][0]['figures']), {'FIRSTBOT', 'LEX'})
        self.assertEqual(set(encounter['fixtures'][1]['figures']), {'LEX'})
        self.assertTrue(all('tick' in fixture for fixture in encounter['fixtures']))
        self.assertGreater(len(encounter['push_steps']), 0)
        self.assertTrue(all(step['scan'] in (0x48, 0x4b, 0x4d)
                            for step in encounter['push_steps']))
        self.assertTrue(encounter['entered_zap_trigger'])
        self.assertTrue(encounter['saw_zap'] and encounter['nurse_removed'])
        self.assertEqual((encounter['bot_blown'], encounter['nurse_health']), (1, -666))
        self.assertEqual(encounter['zap_guard_values'], [1])
        self.assertEqual(encounter['max_zap_processes'], 1)
        self.assertTrue(encounter['escaped'])
        self.assertEqual(encounter['lex_health'], 100)
        self.assertGreater(encounter['total_ticks'], 0)
        self.assertEqual(result['checkpoints'][-1]['camera'], 'BLK1')
        self.assert_known_opening_warnings_only(result)
        self.assertNotIn('FIRSTBOT', result['checkpoints'][-1]['figures'])

    KNOWN_CHAOS_WARNINGS = ('CAMERA SHOW TITLE: logged only, no switch', 'CAMERA SHOW STITLE: logged only, no switch')

    def assert_known_chaos_warnings_only(self, result):
        """The opening's logged CAMERA SHOW lines, a refused AI ON for a dead Caynan, CAYNAN_PACE's BREAK 2 and LUTHOR_ATTACK's BREAK 1 (a block with one SWITCH:
        BREAK n numbers the block's switches from 0, so the port breaks the innermost one, which is what the script means)."""
        self.assertEqual([w for w in result['warnings'] if w not in self.KNOWN_CHAOS_WARNINGS
                          and not ('CAYNAN_PACE:' in w and 'BREAK 2 != innermost' in w)
                          and not ('LUTHOR_ATTACK:' in w and 'BREAK 1 != innermost' in w)
                          and w != "PIMM: no element 'emv1'"                     # the page the routine's mid-fight repair opens
                          and w != 'AI ON: CAYNAN is dead'], [])                  # PLAYER_SUPER_RECOILED's tail (AI_CAYNA.scr:233-235) when he dies in its
                                                                                  # subtitle pause: the original refuses it too (10d0:04b3, message 0xea)

    def test_chaos_caynan_fight_ends_with_caynan_death_script(self):
        result = scenarios.chaos_caynan_fight()
        e = result['encounter']
        self.assert_known_chaos_warnings_only(result)
        self.assertEqual([s['stage'] for s in e['staged']], ['difficulty', 'rng'])
        self.assertTrue(e['greeted'])                                    # OUTSIDE3 -> CAYNAN_GREET before the run-in
        self.assertEqual(e['inside']['caynan_state'], 2)                 # INSIDE3 reached through the open bars at full health
        self.assertEqual(e['inside']['lex_health'], 100)
        self.assertEqual(e['bars_off_ticks'][-1], 21)                    # the run-in took the long window that follows a short one
        self.assertTrue(all(k['scan'] in (0x48, 0x4b, 0x4d, 0x2e, 0x20) for k in result['input_events'] if 'scan' in k))     # D and the clicks: the routine's repair
        self.assertGreater(e['counts']['punches'], 0)
        # Caynan's own CONFRONTENEMY (CAYNAN_AI) can still be turning him when he dies: FUN_10e8_0079 has no death check, so once DIE has
        # finished its atk_m4 / atk_m6 goes through (re/NOTES.md "GO steering"). Which motion he ends in depends on the fight's end.
        self.assertEqual(e['caynan_alive'], 0)
        self.assertLessEqual(e['caynan_health'], 0)
        self.assertGreater(e['lex_health'], 0)
        self.assertTrue(e['lex_hits'])                                    # seed 9: Caynan lands nothing
        self.assertIn('SUPER_RECOIL', {hit[4] for hit in e['lex_hits']})
        for block in ('CAYNAN_AI', 'CAYNAN_GREET', 'CAYNAN_DEATH', 'GROWL'):
            self.assertIn(block, e['blocks'])
        self.assertEqual(e['music'][-1][1], 20)                          # _CELPANEL from CAYNAN_DEATH
        self.assertIn('CAHDF', e['caynan_decals'])                       # CAYNAN_WOUNDS drew the damage decal (state only)
        self.assertIn(result['checkpoints'][-1]['figures']['CAYNAN']['motion'], ('DIE', 'ATK_M4', 'ATK_M6'))   # DIE, or his confront's turn after it (above)
        self.assertFalse([u for u in result['unmodelled'] if u.startswith('FLOATATHEIGHT')])   # ported (z cap form)

    def test_chaos_guard1_fight_easy_ends_with_dothelexthing(self):
        result = scenarios.chaos_guard1_fight()
        e = result['encounter']
        self.assert_known_chaos_warnings_only(result)
        self.assertEqual([s['stage'] for s in e['staged']], ['tanks-return', 'difficulty', 'rng'])
        self.assertEqual((e['guard_alive'], e['guard_health'] <= 0, e['guard_motion']), (0, True, 'DIE'))
        self.assertGreater(e['lex_health'], 0)
        for block in ('ENTERCELL2', 'GREET_GUARD1', 'GUARD1_AI', 'LUTHOR_ATTACK', 'GUARD1_DEATH', 'DOTHELEXTHING'):
            self.assertIn(block, e['blocks'])
        self.assertEqual(e['music'][-1][1], 34)                          # _GOING_BACK from GUARD1_DEATH
        self.assertTrue(e['lex_hits'] and e['guard_hits'])
        # GRD_WOUNDS drew damage decals (state only); which zones depends on where the punches land, which shifts with the opening
        self.assertTrue(e['guard_decals'] and set(e['guard_decals']) <= {'CHEST', 'BACK', 'FLEGS'})
        self.assertIn(result['checkpoints'][-1]['camera'], ('CE22', 'CE23', 'CE24'))     # where the fight ended

    def test_chaos_guard1_fight_medium_can_be_lost(self):
        result = scenarios.chaos_guard1_fight(difficulty=1, seed=9)      # of seeds 0-11 the routine wins 9 and loses on 5, 8 and 9
        e = result['encounter']
        self.assert_known_chaos_warnings_only(result)
        self.assertEqual((e['lex_health'], e['guard_alive']), (-1, 1))   # AI_LEX's death block ends with FORCERELOAD (HP := -1)
        self.assertIn('KILLED_PLAYER', [hit[4] for hit in e['guard_hits']])
        self.assertNotIn('DOTHELEXTHING', e['blocks'])

    def test_landpad_meetmech_places_lex_and_reveals_airmecho(self):
        result = scenarios.landpad_meetmech()
        point = result['checkpoints'][0]
        self.assertEqual((point['level'], point['camera']), ('LANDPAD', 'HFR3'))
        self.assertEqual(result['final_globals']['_airmecho_scene'], 1)
        self.assertEqual(result['final_globals']['_dr9_space'], 1)
        # the scripted GO LEX_POS2 ends within 614 units of its target and does not snap (10e0:1a4c): 548 units short of (-27668, -71040)
        np.testing.assert_allclose(point['player']['position'][:2], [-28216, -71058])
        airmecho = point['figures']['AIRMECHO']
        # AIRHALL.scr:65 `AI ON` starts AIRMECHO_AI from the FIGR record's AI name (no script SETAIs it): it fires, then marches on
        # (his march is GO-driven: each leg now ends within 614 units of its waypoint without a snap, 10e0:1a4c, which moved the tick-500 pose; and each WALK
        # leg starts with frame 0's root, (-153, -509) here, which moved it again by about (-1037, 222) by tick 500)
        # (and each CALL return or process wait now goes on in the next walk, 1238:077f: it is still firing at tick 500, one leg short)
        np.testing.assert_allclose(airmecho['position'][:2], [-6934, -71537])
        self.assertEqual(airmecho['motion'], 'FIRE_GUN')
        self.assertEqual(airmecho['view_cams'], ['HFR3', 'HFR6'])
        self.assertTrue(airmecho['collisions'])
        self.assertEqual(result['warnings'], [])

    def test_beach_tunnel_beach_keeps_player_and_arrival_semantics(self):
        result = scenarios.beach_tunnel_beach()
        tunnel, beach = result['checkpoints']
        self.assertEqual((tunnel['level'], beach['level']), ('TUNROOM', 'BEACH'))
        self.assertIsNotNone(tunnel['player']['position'])
        self.assertIsNotNone(beach['player']['position'])
        self.assertIn(tunnel['camera'], ('TMP1', 'TMP2', 'TUN1', 'TUN2'))
        self.assertIn(beach['camera'], ('BCH8', 'BCH9', 'BCHA', 'BCHB', 'BCHC', 'BCHD'))
        self.assertEqual([(row[1], row[2]) for row in result['level_loads']],
                         [('TUNROOM', 'FROM_BCH'), ('BEACH', 'FROM_TPL')])
        self.assertIn('BOMB', beach['items'])
        self.assertEqual(result['warnings'], [])

    def test_every_shipped_level_loads_and_renders(self):
        results = scenarios.all_level_smoke()
        self.assertEqual([entry['level'] for entry in results],
                         ['BEACH', 'CHAOS', 'CONTROL', 'DIGSITE', 'LANDPAD', 'PLATFORM',
                          'TANKS', 'TITLE', 'TOWER', 'TUNROOM'])
        for entry in results:
            self.assertEqual(entry['shape'], [200, 320, 3], entry['level'])
            self.assertEqual(entry['warnings'], [], entry['level'])


if __name__ == '__main__':
    unittest.main()
