"""The continuous playthrough: a new game to EXIT in one World / VM (playthrough_full.py, re/playthrough/full.md).

One run (about 2 minutes) is shared by every assertion; each leg that completed is a checkpoint. The unit tests at the top are fast."""
import os
import sys
import types
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import playthrough_full as pf  # noqa: E402


class RingMoves(unittest.TestCase):
    """The gravity ring plan (TUNGRAV.scr:228-330, solution in the comment at 340-350)."""

    def solve(self, start):
        vm = types.SimpleNamespace(globals={f'_pz{n}_frame': v for n, v in enumerate(start, 1)})
        last, presses = None, []
        for _ in range(12):
            frames = [vm.globals[f'_pz{n}_frame'] for n in range(1, 7)]
            if len(set(frames)) == 1:
                return presses
            pad = int(pf.ring_move(vm, last)[4:])
            presses.append(pad)
            last = f'RING{pad}'
            for ring in pf.RING_EFFECTS[pad]:
                key = f'_pz{ring}_frame'
                vm.globals[key] = (vm.globals[key] - 1 + 2) % 16 + 1
        return None

    def test_the_start_values_are_solved_in_four_presses(self):
        presses = self.solve((15, 1, 13, 15, 1, 11))
        self.assertEqual(sorted(presses), [1, 3, 3, 6])           # the comment's solution 3, 6, 1, 3 in another order

    def test_no_pad_is_pressed_twice_in_a_row(self):
        presses = self.solve((15, 1, 13, 15, 1, 11))
        self.assertTrue(all(a != b for a, b in zip(presses, presses[1:])))


class FullRun(unittest.TestCase):
    """One run from boot_opening to EXIT."""

    @classmethod
    def setUpClass(cls):
        cls.r = pf.play()
        cls.world, cls.vm = cls.r.world, cls.r.vm
        cls.seg = {s['name']: s for s in cls.r.segments}
        cls.point = {c['name']: c for c in cls.r.checkpoints if isinstance(c.get('name'), str)}

    def passed(self, *names):
        for name in names:
            self.assertEqual(self.seg[name]['status'], 'passed', (name, [p for p in self.r.problems if p['segment'] == name]))

    # ---- the whole run
    def test_the_game_is_finished(self):
        self.assertTrue(self.r.passed)
        self.assertTrue(self.world.exit_requested)                        # ENDGAME's LEAVEGAME ran EXIT
        self.assertEqual(self.world.level, 'TITLE')

    def test_every_leg_ran_in_order(self):
        names = [s['name'] for s in self.r.segments]
        legs = [name for name, _ in pf.LEGS if name != 'bike'] + ['control-second', 'ending']      # the 'bike' leg runs two segments
        it = iter(names)                                                  # in order; a short battery's trip (short_battery) runs some legs again
        self.assertTrue(all(leg in it for leg in legs), names)
        self.assertTrue(all(s['status'] == 'passed' for s in self.r.segments))

    def test_levels_in_the_order_of_the_route(self):
        """CHAOS - TANKS - CHAOS (cell 2) - TANKS - CHAOS (ladder up) - TOWER - CONTROL - LANDPAD - BEACH - DIGSITE - TUNROOM - PLATFORM - TUNROOM
        (TO_ZEROG) - BEACH (the temple exit) - LANDPAD - CONTROL - TITLE. TOWER comes before CONTROL: base.md and full.md explain why. On this RANDOM
        stream the leg battery covers BIKE_NEEDS at the bike, so there is no battery trip."""
        self.assertEqual([load[1] for load in self.world.level_loads],
                         ['CHAOS', 'TANKS', 'CHAOS', 'TANKS', 'CHAOS', 'TOWER', 'CONTROL', 'LANDPAD', 'BEACH', 'DIGSITE', 'TUNROOM', 'PLATFORM',
                          'TUNROOM', 'BEACH', 'LANDPAD', 'CONTROL', 'TITLE'])

    # ---- the legs
    def test_prison_and_cell_2(self):
        self.passed('caynan', 'cryo-ladder', 'tanks', 'guard1', 'blaster')
        self.assertEqual(self.vm.globals['_grd1_alive'], 0)
        self.assertEqual(self.point['blaster']['held']['RTHAND'], 'BLASTER')

    def test_bio_repair_heals_lex_before_the_next_levels(self):
        self.passed('bio-repair')
        self.assertGreaterEqual(self.point['bio-repair']['lex_health'], 75)

    def test_the_hall_and_the_elevator_ride_to_tower(self):
        self.passed('tanks-back', 'hall-to-elevator')
        self.assertEqual(self.point['hall-to-elevator']['level'], 'TOWER')

    def test_both_landers_are_shot_down(self):
        self.passed('tower', 'tower-exit')
        self.assertEqual((self.vm.globals['_firstlanderalive'], self.vm.globals['_secondlanderalive'], self.vm.globals['_lander_stage']), (0, 0, 5))

    def test_control_first_visit_operating_room_suit_and_block(self):
        self.passed('operating-room', 'hardsuit', 'garage-block', 'garage-up')
        self.assertEqual(self.vm.globals['_operate_done'], 1)
        self.assertEqual(self.vm.globals['_marine1_alive'], 0)            # the first lander was down: Marine 1 never stood in the hall
        self.assertEqual(self.point['hardsuit']['player']['position'][0] > 55000, True)      # the machine is in the control room's east corner
        self.assertEqual(self.point['garage-block']['held']['LTHAND'], 'BLOCK')
        self.assertNotIn('BLASTER', {i.type for i in self.world.items.values() if i.owner == self.world.player_name})     # OPRSCENE took it

    def test_surface_levels(self):
        self.passed('to-landpad', 'landpad', 'beach', 'digsite', 'tunroom')
        self.assertEqual(self.vm.globals['_airmecho_dead'], 1)
        self.assertEqual(self.point['tunroom']['level'], 'PLATFORM')

    def test_platform_gives_the_alien_battery(self):
        self.passed('platform')
        self.assertEqual(self.vm.globals['_alien_city_seen'], 1)
        self.assertEqual(self.vm.globals['_gave_alien_battery'], 1)
        battery = self.point['battery']['battery']
        self.assertEqual({v[0] for v in battery.values()}, {'ALBAT'})
        self.assertIn(500, [v[3][0] for v in battery.values()])

    def test_return_trip_and_the_gravity_ring(self):
        self.passed('platform-exit', 'zero-g-back', 'grav-ring', 'temple-monitor', 'temple', 'beach-climb', 'landpad-to-elevator', 'landpad-to-elevator')
        self.assertEqual(self.vm.globals['_grav_solved'], 1)
        self.assertEqual([self.vm.globals[f'_pz{n}_frame'] for n in range(1, 7)], [0] * 6)      # the rings are removed after the win

    def test_second_visit_and_the_ending(self):
        self.passed('control-second', 'ending')
        self.assertEqual(self.point['endgame']['battery_in_bike'], 3)             # the alien battery is in the bike
        self.assertTrue(self.point['endgame']['endgame_alive'])                  # ENDGAME survived LOADLEVEL TITLE
        self.assertEqual(self.point['exit']['keyboard_captured'], False)         # LEAVEGAME released the keyboard before EXIT

    # ---- what carried over, and what did not
    def test_inventory_carried_over_the_whole_run(self):
        mine = {i.name: i.slot for i in self.world.items.values() if i.owner == self.world.player_name}
        for name in ('FORK', 'DANELOG', 'MY_BATTERY', 'BLOCK', 'KEY'):
            self.assertIn(name, mine)

    def test_health_is_continuous_between_levels(self):
        """Lex's HP is what the previous stretch left, on this RANDOM stream: the Caynan fight leaves him 57, Guard 1's fight 75, so BIOREPAIR has nothing
        to do (heal's default `enough` is 75), and the hard suit machine's guard leaves him at 52."""
        health = {name: self.point[name]['lex_health'] for name in ('caynan', 'guard1', 'bio-repair', 'hardsuit', 'platform', 'ending')}
        self.assertEqual((health['caynan'], health['guard1'], health['bio-repair'], health['hardsuit']), (57, 75, 75, 52))
        self.assertEqual((health['platform'], health['ending']), (94, 67))  # what the platform stretch and the way back leave on this stream

    def test_marine5_is_fought_in_the_mirror_suit(self):
        """His bolts do nothing to LEXMIR, so Lex keeps the suit on and kills him by hand; no guard is held."""
        self.assertFalse([s for s in self.r.shortcuts if s['name'] == 'guard-ai-off'])
        self.assertEqual(self.r.vm.globals.get('_marine5_alive'), 0)

    def test_nothing_is_seeded(self):
        """No segment creates Lex, seeds a global or an item, or places Lex at an arrival to stand in for earlier play."""
        names = {s['name'] for s in self.r.shortcuts}
        self.assertFalse(names & {'player', 'item', 'form', 'surface-item', 'surface-form', 'elevator-button'}, names)
        self.assertTrue(all(s['name'] in pf.SHORTCUTS or s['name'].startswith('surface-') for s in self.r.shortcuts))
        self.assertEqual(self.world.unmodelled, [])

    def test_the_shortcut_list_is_the_documented_one(self):
        self.assertEqual(sorted({s['name'] for s in self.r.shortcuts}),
                         sorted(['nurse-poses', 'difficulty-easy', 'fido-puzzle',
                                 'set-pos',
                                 'surface-set_pos', 'surface-global',
                                 'ring-pads']))

    def test_the_bike_lends_its_battery_in_the_garage(self):
        """Out of the bike, into the leg, and the old one back in the bike: two BIKE_USE presses there and two at the end. Lex leaves the garage with more than the 9 he arrives on."""
        uses = [e[0] for e in self.world.key_log if e[1] == 'use' and e[2] == 'BIKE_USE']
        self.assertEqual(len(uses), 4)
        garage = self.seg['garage-block']
        self.assertEqual(sum(garage['start_tick'] <= tick <= garage['end_tick'] for tick in uses), 2)

    def test_the_guards_are_beaten_for_blaster2(self):
        """GRDCON in the suit, then GRDHALL on the bike's battery, and his gun in Lex's hand or carried on from there."""
        self.passed('grdcon', 'grdhall')
        self.assertEqual((self.vm.globals['_grdcon_alive'], self.vm.globals['_grdhall_alive']), (0, 0))
        self.assertEqual(self.point['grdhall']['held']['RTHAND'], 'BLASTER2')

    def test_the_glass_floor_never_gives_way(self):
        """THOLE1 and THOLE2 (PLATFORM.scr:200-321): the fight keeps Lex off both, so neither pane has started to crack."""
        self.assertEqual((self.vm.globals.get('_gls1_frame', 0) >= 2, self.vm.globals.get('_gls2_frame', 0) >= 2), (False, False))

    def test_the_zero_g_room_is_flown_with_the_captains_gun(self):
        """Every crossing by ZERO_G_FIRE, nothing staged: entered by TO_0G_USE Lex floats at z -5539, as in the original (live; re/NOTES.md
        "Lex's height in the zero-g room"), low enough for the exit corridor. The gift took the gun's hand, so the alien battery goes in his leg; at the bike
        the ending takes out the old battery Lex left there (BAT_100_USE), since CONTROL keeps its items."""
        g = self.r.vm.globals
        self.assertEqual(g.get('_tumolt_alive'), 0)
        self.assertFalse([s for s in self.r.shortcuts if 'flying the zero-g' in str(s)])
        self.assertEqual(g.get('_battery_in_bike'), 3)
        self.assertEqual([e[2] for e in self.world.key_log if e[1] == 'use' and e[2] in ('ABAT_500_USE', 'BAT_100_USE')],
                         ['ABAT_500_USE', 'ABAT_500_USE', 'BAT_100_USE'])     # the bike's in the garage, the gift, Lex's old one at the bike

    def test_the_monitor_puzzles_are_solved_by_clicks(self):
        """Tomb, city and tube monitors: no block or global staged, and each ends in what its own script sets."""
        g = self.r.vm.globals
        self.assertEqual((g.get('_tomb_solved'), g.get('_city_solved')), (1, 1))
        self.assertEqual(g.get('_tubesopen') >> 2 & 3, 3)           # the zero-g room and the gravity ring

    def test_the_reactor_is_shut_down_by_play(self):
        """No staged global: the forklift rams REACTBOT, Drogg 1 falls with the bridge, both levers and the ID at the console set _Reactor_Safe."""
        g = self.r.vm.globals
        self.assertEqual((g.get('_forklift_dead'), g.get('_reactbot_alive'), g.get('_drogg1_alive')), (1, 0, 0))
        self.assertEqual((g.get('_lt_lev'), g.get('_rt_lev'), g.get('_reactor_safe')), (1, 1, 1))
        self.assertEqual(g.get('_reactor_detonate'), 0)


if __name__ == '__main__':
    unittest.main()
