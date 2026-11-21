"""Tests for the recovered melee hit logic (world.update_hit / hit_zone / damage, salsa.load_col, motion attack fields):
re/.venv/bin/python -I -W ignore -m unittest discover -s re/interp -p 'test_hits.py' -v"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'formats'))
import numpy as np  # noqa: E402
import salsa  # noqa: E402
import vm as vmmod  # noqa: E402
import world as worldmod  # noqa: E402
from test_world import cmd, ticks_for  # noqa: E402


class Columns(unittest.TestCase):
    def test_nurse_col_decodes(self):
        got = salsa.load_col(os.path.join(worldmod.BODY, 'NURSEBOT.COL'))
        self.assertEqual(got, [(8, 1, 280), (10, 0, 220), (14, 1, 560), (3, 1, 480), (7, 1, 200)])
        self.assertEqual(worldmod.Assets('NURSEBOT').col, got)

    def test_motion_attack_fields(self):
        man = salsa.load_motion_headers(os.path.join(worldmod.BODY, 'MAN.MTN'))
        nurse = salsa.load_motion_headers(os.path.join(worldmod.BODY, 'NURSEBOT.MTN'))
        self.assertEqual(man['ATK_H8'][2:5], (25, 17, 1))
        self.assertEqual(nurse['ATK_SYRINGE'][2:5], (5, 13, 1))
        self.assertEqual(nurse['DEFEND'][4], 2)                # guard
        self.assertEqual(man['ATK_M8'][4], 3)                  # movement
        self.assertEqual(len(salsa.load_motions(os.path.join(worldmod.BODY, 'MAN.MTN'))['ATK_H8']), 13)
        self.assertEqual(len(salsa.load_motions(os.path.join(worldmod.BODY, 'NURSEBOT.MTN'))['ATK_SYRINGE']), 10)


class Hits(unittest.TestCase):
    def setUp(self):
        w = self.w = worldmod.World('CHAOS', state_dir=worldmod.INITGAME)
        self.vm = vmmod.VM(w)
        vmmod.load_level(self.vm, 'CHAOS')
        w.auto_camera = False                                   # at this staged spot CE11 would take over, and CE1_LOAD's SPARWITHPLAYER retarget Lex
        cmd(w, 'CREATEFIGURE', 'LEX', 'PLAYER')
        self.lex = w.player()
        self.bot = w.figure('FIRSTBOT')
        self.bot.view_cams = None
        self.vm.globals['_difficulty_level'] = 0
        self.place(0, -2000)                                    # Lex 100 cm in front of the robot (it faces -y)
        cmd(w, 'DEFINEENEMY', 'PLAYER', fig='FIRSTBOT')
        cmd(w, 'DEFINEENEMY', 'FIRSTBOT', fig='LEX')

    def place(self, lx, ly):
        self.bot.pos, self.bot.heading = np.array([0, 0, 0.0]), 0.0
        self.lex.pos = np.array([lx, ly, 0.0])

    def script(self, text):
        with tempfile.NamedTemporaryFile('w', suffix='.scr', delete=False) as t:
            t.write(text)
        try:
            self.vm.load(t.name)
        finally:
            os.unlink(t.name)

    def run_ticks(self, n):
        for _ in range(n):
            self.vm.tick_once()
            self.w.step()

    def play(self, fig, motion):
        fig.set_motion(motion, False)
        self.run_ticks(ticks_for(fig, len(fig.frames), self.w))

    def record_damage(self):
        calls = []
        self.w.damage = lambda *a: calls.append(a)
        return calls

    def test_live_capture_first_punch_lands_on_frame_7(self):
        # re/out/fall_live/combat (DOSBox-X, clock 14029-14051): from these poses the original's first ATK_H8 put the
        # nurse in recoil_tl at Lex's frame 7, with nurse health 50 and ~3 = 1
        bot, lex, vm = self.bot, self.lex, self.vm
        bot.pos, bot.heading = np.array([-10035., -12475., -4546.]), 174.8
        lex.pos, lex.heading = np.array([-10145., -10605., -5097.]), -4.0
        bot.set_motion('ATK_STAND', True)
        lex.set_motion('ATK_H8', False)
        n = len(self.w.hits)
        for _ in range(80):
            self.w.step()
            if len(self.w.hits) > n:
                break
        self.assertEqual((lex.idx, bot.motion, vm.objects['FIRSTBOT'][0], vm.objects['FIRSTBOT'][3]),
                         (7, 'RECOIL_TL', 50, 1))

    def test_checks_only_frames_4_to_n_minus_5(self):
        seen = []
        self.w.col_hit = lambda e, pt, geom: seen.append(self.attacker.idx) or False
        for self.attacker, motion, frames in ((self.lex, 'ATK_H8', [4, 5, 6, 7, 8]),      # 13 frames
                                              (self.bot, 'ATK_SYRINGE', [4, 5])):         # 10 frames
            seen.clear()
            self.play(self.attacker, motion)
            self.assertEqual(sorted(set(seen)), frames, motion)

    def test_motions_that_are_not_strikes_never_check(self):
        seen = []
        self.w.col_hit = lambda fig, pt, geom: seen.append(1) or True
        for motion in ('ATK_M8', 'DEFEND'):
            self.play(self.bot, motion)
        self.assertEqual(seen, [])

    def test_one_hit_per_play_and_cleared_by_a_new_motion(self):
        calls = self.record_damage()
        self.w.col_hit = lambda fig, pt, geom: True
        self.play(self.bot, 'ATK_SYRINGE')
        self.assertEqual(len(calls), 1)
        self.assertEqual((calls[0][0], calls[0][1], calls[0][2], calls[0][3], calls[0][5]), (self.lex, self.bot, 5, 0, False))
        self.play(self.bot, 'ATK_SYRINGE')
        self.assertEqual(len(calls), 2)

    def test_a_miss_does_not_consume_the_play(self):
        calls = self.record_damage()
        verdicts = iter([False, False, True, True, True, True, True, True])      # frame 4 misses both points, frame 5 hits
        self.w.col_hit = lambda fig, pt, geom: next(verdicts, True)
        self.play(self.bot, 'ATK_SYRINGE')
        self.assertEqual(len(calls), 1)

    def test_attacker_becomes_the_players_enemy(self):
        self.lex.enemy = None
        self.w.col_hit = lambda fig, pt, geom: False
        self.play(self.bot, 'ATK_SYRINGE')
        self.assertEqual(self.lex.enemy, 'FIRSTBOT')

    def test_cube_is_strict_and_centred_on_end_or_midpoint(self):
        w, bot = self.w, self.bot
        geom = w.limb_geometry(bot)
        ends, dirs = geom
        # (10, mode 0, 220): the limb's end
        for pt, expect in ((ends[10], True), (ends[10] + (219, 0, 0), True), (ends[10] + (220, 0, 0), False),
                           (ends[10] + (0, -219, 220), False), (ends[10] + (0, 0, -219), True)):
            self.assertEqual(w.col_hit(bot, np.array(pt, float), geom), expect, pt)
        mid = ends[8] - dirs[8] * (bot.assets.skel[8].length / 2)        # (8, mode 1, 280): the limb's midpoint
        self.assertTrue(w.col_hit(bot, mid, geom))
        self.assertTrue(w.col_hit(bot, mid + (0, 0, 279), geom))
        self.assertFalse(w.col_hit(bot, mid + (0, 0, 280), geom))

    def test_zone_height_side_and_integer_form(self):
        w, lex = self.w, self.lex
        self.assertEqual(int(((lex.assets.foot_offset * 0x1000 // 256) << 8) / 0x6400), 369)     # MAN F = 2312
        egeom = w.limb_geometry(lex)
        rootz, h = egeom[0][0][2], 369
        lex.pos, lex.heading = np.array([0, 0, 0.0]), 0.0              # faces -y: +x is its left
        left_attacker = type('A', (), {'pos': np.array([2000.0, -1000.0, 0.0])})
        right_attacker = type('A', (), {'pos': np.array([-2000.0, -1000.0, 0.0])})
        for z, base in ((rootz + h + 1, 0), (rootz + h, 2), (rootz, 2), (rootz - h, 2), (rootz - h - 1, 4)):
            self.assertEqual(w.hit_zone(lex, left_attacker, z, egeom), base, z)
            self.assertEqual(w.hit_zone(lex, right_attacker, z, egeom), base + 1, z)

    def test_armoured_nurse_takes_no_damage_but_still_runs_got_hit(self):
        w, vm, bot = self.w, self.vm, self.bot
        vm.globals['_nursebot_is_hit'] = 0
        bot.set_motion('STAND', True)
        self.lex.set_motion('ATK_H8', False)
        w.damage(bot, self.lex, 25, 0, 2, True)                    # ML, heavy
        self.assertEqual(vm.objects['FIRSTBOT'][0], 50)         # IMPACT_ARMOR 100
        self.assertEqual(vm.globals['_nursebot_is_hit'], 1)     # FIRSTBOT_STIMULUS :GOT_HIT
        self.assertEqual((bot.motion, vm.objects['FIRSTBOT'][3]), ('RECOIL_TL', 1))     # super_rec_ml missing: side fallback
        self.assertEqual(w.hits[-1][1:4], ('LEX', 'FIRSTBOT', 'ATK_H8'))
        self.run_ticks(ticks_for(bot, len(bot.frames), w) + 3)
        self.assertEqual(vm.objects['FIRSTBOT'][3], 0)          # ASSUMPTION: cleared when the recoil ends

    def test_hit_cancels_the_motion_task_so_a_busy_target_recoils(self):
        bot = self.bot
        bot.set_motion('ATK_STAND', True)                       # a script-started motion
        self.lex.set_motion('ATK_H8', False)
        log = self.labels({('FIRSTBOT', 'GOT_HIT_ML_ATK_STAND')})       # the name is taken before the cancel
        self.w.damage(bot, self.lex, 25, 0, 2, False)
        self.assertEqual((bot.motion, self.vm.objects['FIRSTBOT'][3]), ('RECOIL_TL', 1))
        self.assertEqual(log[0][:2], ('FIRSTBOT', 'GOT_HIT_ML_ATK_STAND'))

    def test_a_recoil_ends_the_turn_task_and_refuses_a_scripts_motion(self):
        """FUN_1098_0789(target, 1, 0) ends turn_to_enemy; +0x15f holds the recoil's name, so a taunt's next MOTION is refused (FUN_1098_12bd)."""
        bot = self.bot
        bot.set_motion('ATK_STAND', True)
        self.lex.set_motion('ATK_H8', False)
        bot.confront = {'settled': False, 'count': 0}
        self.w.damage(bot, self.lex, 25, 0, 2, False)
        self.assertEqual((bot.confront, bot.motion), (None, 'RECOIL_TL'))
        self.assertTrue(bot.motion_gate_refuses('STAND'))

    def test_unfinished_die_is_not_cancelled_and_does_not_recoil(self):
        self.lex.set_motion('DIE', False)
        self.bot.set_motion('ATK_SYRINGE', False)
        self.vm.objects['LEX'][0] = 100
        self.w.damage(self.lex, self.bot, 10, 0, 2, False)
        self.assertEqual((self.lex.motion, self.lex.frozen, self.vm.objects['LEX'][3]), ('DIE', False, 0))

    def test_no_motion_replaces_die(self):
        # FUN_1098_0394 refuses a motion change while the current motion is DIE
        self.assertTrue(self.lex.set_motion('DIE', False))
        self.assertFalse(self.lex.set_motion('ATK_STAND', True))
        self.assertEqual(self.lex.motion, 'DIE')
        self.assertFalse(self.lex.set_motion('WAKE_UP', False))      # 1098:0394 has no SNAP_TO exception (REVIVELEX runs after the blocking MOTION DIE)

    def test_guard_bytes_are_the_frame_record_root_words(self):
        mtn = salsa.load_motions(os.path.join(worldmod.BODY, 'MAN.MTN'))
        import struct
        self.assertEqual(struct.pack('<3h', *mtn['ATK_H1'][6][1]), bytes([3, 3, 2, 2, 0, 0]))
        nurse = salsa.load_motions(os.path.join(worldmod.BODY, 'NURSEBOT.MTN'))
        self.assertEqual(struct.pack('<3h', *nurse['DEFEND'][3][1]), bytes([2, 2, 2, 2, 3, 3]))
        sk = salsa.load_skel(os.path.join(worldmod.BODY, 'MAN.SKL'))
        p, r, l = mtn['ATK_H8'][7]
        np.testing.assert_allclose(salsa.solve(sk, (p, r, l))[2][17], salsa.solve(sk, (p, (0, 0, 0), l))[2][17])

    def test_guarded_zone_blocks_within_110_degrees(self):
        w, bot = self.w, self.bot
        calls = self.record_damage()
        w.col_hit = lambda e, pt, geom: True
        bot.set_motion('DEFEND', True)
        bot.idx = 3                                             # guard 02 02 02 02 03 03: top and middle zones block
        self.lex.set_motion('ATK_H8', False)
        self.lex.idx = 4
        self.lex.phase = 0
        self.run_ticks(1)
        self.assertEqual(calls, [])
        self.assertEqual(w.hits[-1][1:], ('LEX', 'FIRSTBOT', 'ATK_H8', 'BLOCKED'))
        self.assertTrue(self.lex.hit_done)

    def test_syringe_runs_hit_player_label_and_hurts_lex_by_the_difficulty_adjusted_amount(self):
        vm = self.vm
        vm.globals['_lex_drugged'] = 0
        self.play(self.bot, 'ATK_SYRINGE')
        self.assertEqual(vm.globals['_lex_drugged'], 1)
        self.assertEqual(vm.objects['LEX'][0], 99)              # 5 - 4 at difficulty 0
        self.assertEqual(self.w.hits[-1][1:], ('FIRSTBOT', 'LEX', 'ATK_SYRINGE', 'HIT_PLAYER_ATK_SYRINGE'))

    def test_difficulty_scales_damage_to_the_player_and_from_others(self):
        vm, w = self.vm, self.w
        vm.globals['_difficulty_level'] = 2
        self.bot.set_motion('ATK_SYRINGE', False)
        w.damage(self.lex, self.bot, 5, 0, 2, False)
        self.assertEqual(vm.objects['LEX'][0], 100 - 13)        # +4 x 2
        self.lex.set_motion('ATK_H8', False)
        vm.objects['FIRSTBOT'][0] = 50
        cmd(w, 'INVULNERABLE', 'OFF', fig='FIRSTBOT')
        w.damage(self.bot, self.lex, 25, 0, 2, False)              # armour 100 swallows it; no HP change, no exception
        self.assertEqual(vm.objects['FIRSTBOT'][0], 50)

    def labels(self, existing):
        """Replace raise_label by a recorder; `existing` are the (figure, label) pairs that count as present."""
        log = []
        self.w.raise_label = lambda fig, label, dmg: log.append((fig.name, label, dmg)) or (fig.name, label) in existing
        return log

    def test_invulnerable_or_zero_damage_raises_for_zero_labels(self):
        w, vm = self.w, self.vm
        log = self.labels(set())
        self.bot.set_motion('ATK_SYRINGE', False)
        w.damage(self.lex, self.bot, 4, 0, 2, False)               # 4 - 4 = 0 at difficulty 0
        self.assertEqual(log, [('FIRSTBOT', 'HIT_PLAYER_FOR_ZERO', 0), ('LEX', 'HIT_FOR_ZERO', 0)])
        self.assertEqual(vm.objects['LEX'][0], 100)
        log.clear()
        self.lex.invulnerable = True
        w.damage(self.lex, self.bot, 40, 0, 2, False)
        self.assertEqual([l[1] for l in log], ['HIT_PLAYER_FOR_ZERO', 'HIT_FOR_ZERO'])
        self.assertEqual(vm.objects['LEX'][0], 100)

    def test_label_order_for_a_player_hit(self):
        w, vm = self.w, self.vm
        log = self.labels({('LEX', 'GOT_HIT_ML')})
        self.bot.set_motion('ATK_SYRINGE', False)
        vm.objects['LEX'][0] = 80
        w.damage(self.lex, self.bot, 25, 0, 2, True)               # 25 - 4 = 21 (heavy): 80 -> 59
        self.assertEqual([l[:2] for l in log], [
            ('LEX', 'GOT_HIT_ML_STAND'), ('LEX', 'GOT_HIT_ML'), ('LEX', 'GOT_HIT'),
            ('LEX', 'MY_HPS_75'), ('FIRSTBOT', 'PLAYERS_HPS_75'), ('FIRSTBOT', 'PLAYER_SUPER_RECOILED'),
            ('FIRSTBOT', 'HIT_PLAYER'), ('FIRSTBOT', 'HIT_PLAYER_ATK_SYRINGE')])
        self.assertEqual(vm.objects['LEX'][0], 59)
        self.assertEqual({l[2] for l in log}, {21})

    def test_dead_player_raises_killed_player_and_stops_labels(self):
        w, vm = self.w, self.vm
        log = self.labels(set())
        self.bot.set_motion('ATK_SYRINGE', False)
        vm.objects['LEX'][0] = 3
        w.damage(self.lex, self.bot, 10, 0, 2, False)
        self.assertEqual((vm.objects['LEX'][0], log), (-3, [('FIRSTBOT', 'KILLED_PLAYER', 6)]))
        log.clear()
        w.damage(self.lex, self.bot, 10, 0, 2, False)              # HP <= 0: ignored
        self.assertEqual((vm.objects['LEX'][0], log), (-3, []))

    def test_elite_does_no_damage(self):
        w, vm = self.w, self.vm
        log = self.labels(set())
        self.bot.name = 'ELITE'
        w.damage(self.lex, self.bot, 40, 0, 2, False)
        self.assertEqual((vm.objects['LEX'][0], [l[:2] for l in log]), (100, [('ELITE', 'HIT_PLAYER_FOR_ZERO')]))
        self.lex.invulnerable = True
        log.clear()
        w.damage(self.lex, self.bot, 40, 0, 2, False)
        self.assertEqual(log, [])

    def test_real_punch_is_blocked_by_defend_but_not_by_stand(self):
        labels = {}
        for motion in ('STAND', 'DEFEND'):
            self.setUp()
            self.vm.globals['_nursebot_is_hit'] = 0
            self.place(0, -2000)
            self.lex.heading = 180
            self.bot.set_motion(motion, True)
            self.bot.idx = 3
            self.lex.set_motion('ATK_H8', False)
            self.run_ticks(ticks_for(self.lex, len(self.lex.frames), self.w))
            labels[motion] = [h[4] for h in self.w.hits]
        self.assertEqual(labels, {'STAND': ['GOT_HIT'], 'DEFEND': ['BLOCKED']})


class AutoTurn(unittest.TestCase):
    """FUN_1088_3419: the player's combat auto-turn toward its enemy."""
    setUp, place, script, run_ticks, labels = Hits.setUp, Hits.place, Hits.script, Hits.run_ticks, Hits.labels

    def aim(self, deg, motion='ATK_STAND'):
        """Lex at the origin facing -y with the robot `deg` degrees to its left (negative: right); combat mode, enemy set."""
        a = np.radians(deg)
        self.lex.pos, self.lex.heading = np.array([0, 0, 0.0]), 0.0
        self.bot.pos = np.array([-2000 * np.sin(a) * -1, -2000 * np.cos(a), 0.0])
        self.lex.combat, self.lex.enemy, self.lex.motion = True, 'FIRSTBOT', motion
        self.lex.auto_turn_count = 0
        self.assertAlmostEqual(self.w.rel_angle(self.lex, self.bot.pos), deg, delta=0.01)

    def turned(self):
        h, self.lex.heading = self.lex.heading, 0.0
        return h

    def test_window_and_step_cap(self):
        for deg, step in ((2, 0), (3, 1), (10, 5), (12, 6), (30, 6), (54, 6), (55, 0), (90, 0)):
            for sign in (1, -1):
                self.aim(sign * deg)
                self.w.auto_turn(self.lex)
                # +heading turns right, so a bearing to the left (positive) lowers the heading
                self.assertEqual(self.turned(), -sign * step, (deg, sign))

    def test_turn_reduces_the_bearing(self):
        self.aim(20)
        self.w.auto_turn(self.lex)
        self.assertAlmostEqual(self.w.rel_angle(self.lex, self.bot.pos), 14, delta=0.01)

    def test_only_in_attack_stand_and_shoot(self):
        """Live: atk_stand steps toward the enemy, atk_M8 holds its heading; 1088:3419's "atk_m" compare is case-sensitive."""
        for motion, acts in (('ATK_M8', False), ('atk_m1', False), ('ATK_M4', False), ('ATK_M6', False), ('ATK_STAND', True),
                             ('SHOOT', True), ('STAND', False), ('ATK_H8', False), ('WALK', False)):
            self.aim(20, motion)
            self.w.auto_turn(self.lex)
            self.assertEqual(self.turned() != 0, acts, motion)

    def test_only_the_player_in_combat_with_an_enemy(self):
        self.aim(20)
        self.lex.combat = False
        self.w.auto_turn(self.lex)
        self.assertEqual(self.turned(), 0)
        self.aim(20)
        self.lex.enemy = None
        self.w.auto_turn(self.lex)
        self.assertEqual(self.turned(), 0)
        self.aim(20)
        self.bot.combat, self.bot.enemy, self.bot.motion = True, 'PLAYER', 'ATK_M8'     # a non-player never auto-turns
        self.bot.pos, self.lex.pos = np.array([0.0, 0, 0]), np.array([-1000.0, -1000.0, 0])
        self.w.auto_turn(self.bot)
        self.assertEqual(self.bot.heading, 0.0)

    def test_counter_acts_every_auto_turn_speed_calls(self):
        orig = worldmod.figure_prop
        worldmod.figure_prop = lambda n, t, prop, default: 3 if prop == 'AUTO_TURN_SPEED' else orig(n, t, prop, default)
        try:
            self.aim(20)
            self.w.auto_turn(self.lex)
            self.w.auto_turn(self.lex)
            self.assertEqual((self.lex.heading, self.lex.auto_turn_count), (0.0, 2))
            self.w.auto_turn(self.lex)
            self.assertEqual((self.lex.heading, self.lex.auto_turn_count), (-6.0, 0))
            worldmod.figure_prop = lambda n, t, prop, default: 0 if prop == 'AUTO_TURN_SPEED' else orig(n, t, prop, default)
            self.lex.heading = 0.0
            self.w.auto_turn(self.lex)
            self.assertEqual(self.lex.heading, 0.0)
        finally:
            worldmod.figure_prop = orig

    def test_step_runs_it_each_frame(self):
        self.aim(20)
        self.lex.set_motion('ATK_STAND', True)
        self.lex.heading = 0.0
        self.w.step()
        self.assertEqual(self.lex.heading, -6.0)


class DamageExtras(unittest.TestCase):
    """FUN_1090_09b9 pieces beyond the melee hit: type, no attacker, knockback, sounds, WOUNDS / DEATH, and DAMAGE."""
    setUp, place, script, run_ticks, labels = Hits.setUp, Hits.place, Hits.script, Hits.run_ticks, Hits.labels

    def sounds(self, known=True):
        played = []
        self.w.sound_index = lambda name: played.append(name) or (len(played) if known else None)
        self.w.play_sound = lambda idx, volume=255, pitch=0, loop=True, priority=1, fig=None: played.append(('PLAY', idx, fig))
        return played

    def test_damage_statement_is_impact_or_energy_without_attacker(self):
        vm, w = self.vm, self.w
        vm.objects['FIRSTBOT'][0] = 100
        log = self.labels(set())
        cmd(w, 'DAMAGE', 'ENERGY', 30, fig='FIRSTBOT')
        self.assertEqual(vm.objects['FIRSTBOT'][0], 70)                # NURSEBOT ENERGY_ARMOR 0; difficulty 0 adjusts a non-player by 0
        self.assertEqual({l[2] for l in log}, {30})
        self.assertEqual(w.hits[-1][1:4], (None, 'FIRSTBOT', 'Unknown'))

    def test_energy_uses_energy_armour_and_impact_uses_impact_armour(self):
        vm, w = self.vm, self.w
        vm.objects['FIRSTBOT'][0] = 100
        cmd(w, 'DAMAGE', 20, fig='FIRSTBOT')                           # impact: NURSEBOT IMPACT_ARMOR 100 swallows it
        self.assertEqual(vm.objects['FIRSTBOT'][0], 100)
        cmd(w, 'DAMAGE', 20, 'ENERGY', fig='FIRSTBOT')                 # energy: ENERGY_ARMOR 0
        self.assertEqual(vm.objects['FIRSTBOT'][0], 80)

    def test_energy_labels_and_zone_6_skips_zone_labels_and_recoil(self):
        vm, w = self.vm, self.w
        vm.objects['FIRSTBOT'][0] = 100
        log = self.labels(set())
        cmd(w, 'DAMAGE', 'ENERGY', 10, fig='FIRSTBOT')
        names = [l[:2] for l in log]
        self.assertEqual(names, [('FIRSTBOT', 'ENERGY_DAMAGE'), ('FIRSTBOT', 'GOT_HIT')])
        self.assertEqual(vm.objects['FIRSTBOT'][3], 0)                 # no recoil
        log.clear()
        vm.objects['LEX'][0] = 100
        cmd(w, 'DAMAGE', 'ENERGY', 10, fig='LEX')                      # player with an enemy: PLAYER_ENERGY_DAMAGE on it
        self.assertEqual([l[:2] for l in log], [
            ('LEX', 'ENERGY_DAMAGE'), ('FIRSTBOT', 'PLAYER_ENERGY_DAMAGE'), ('LEX', 'GOT_HIT')])
        self.assertEqual(vm.objects['LEX'][0], 100 - 6)                # difficulty 0: 10 - 4
        log.clear()
        vm.objects['LEX'][0] = 5
        cmd(w, 'DAMAGE', 'ENERGY', 20, fig='LEX')
        self.assertIn(('FIRSTBOT', 'KILLED_PLAYER'), [l[:2] for l in log])
        self.assertNotIn(('FIRSTBOT', 'PLAYER_ENERGY_DAMAGE'), [l[:2] for l in log])

    def test_no_attacker_skips_attacker_labels(self):
        log = self.labels(set())
        self.vm.objects['LEX'][0] = 80
        self.w.damage(self.lex, None, 25, 0, 2, True)
        raised = [l[0] for l in log]
        self.assertNotIn('FIRSTBOT', raised)
        self.assertEqual(self.w.hits[-1][1:4], (None, 'LEX', 'Unknown'))

    def test_energy_armour_value(self):
        w, vm = self.w, self.vm
        orig = worldmod.figure_prop
        worldmod.figure_prop = lambda n, t, prop, default: {'ENERGY_ARMOR': 15, 'IMPACT_ARMOR': 10}.get(prop, orig(n, t, prop, default))
        try:
            vm.objects['FIRSTBOT'][0] = 100
            w.damage(self.bot, None, 40, 1, 6, False)
            self.assertEqual(vm.objects['FIRSTBOT'][0], 75)
            w.damage(self.bot, None, 40, 0, 6, False)
            self.assertEqual(vm.objects['FIRSTBOT'][0], 45)
            w.damage(self.bot, None, 15, 1, 6, False)                  # fully absorbed
            self.assertEqual(vm.objects['FIRSTBOT'][0], 45)
        finally:
            worldmod.figure_prop = orig

    def test_knockback_only_for_a_bouncy_vulnerable_target_with_an_attacker(self):
        w, bot, lex = self.w, self.bot, self.lex
        lex.heading = 90.0                                             # forward = (-1, 0); row 1 = (256, 0)
        bot.bouncy = True
        w.damage(bot, lex, 25, 0, 2, False)
        self.assertEqual((bot.vx, bot.vy, bot.vz), (-256, 0, 0))      # v -= row 1: pushed away from the attacker, along forward
        bot.vx = 0
        w.damage(bot, None, 25, 0, 6, False)
        self.assertEqual((bot.vx, bot.vy), (0, 0))
        bot.invulnerable = True
        w.damage(bot, lex, 25, 0, 2, False)
        self.assertEqual((bot.vx, bot.vy), (0, 0))
        bot.invulnerable, bot.bouncy = False, False
        w.damage(bot, lex, 25, 0, 2, False)
        self.assertEqual((bot.vx, bot.vy), (0, 0))
        bot.bouncy = True
        self.vm.objects['FIRSTBOT'][0] = 0                             # a dead target is not pushed either
        w.damage(bot, lex, 25, 0, 2, False)
        self.assertEqual((bot.vx, bot.vy), (0, 0))

    def test_hit_and_block_sound_names(self):
        w = self.w
        played = self.sounds(known=True)
        w.damage(self.bot, self.lex, 25, 0, 2, False)
        cam = w.current_camera()
        self.assertEqual(played[0], f'_LEX_HITS_NURSEBOT_{cam}')
        self.assertEqual(played[1][0], 'PLAY')
        self.assertIs(played[1][2], self.bot)
        played.clear()
        self.bot.invulnerable = True
        w.damage(self.bot, self.lex, 25, 0, 2, False)
        self.assertEqual(played[0], '_BLOCK_NURSEBOT_LEX')
        self.assertEqual(played[1], ('PLAY', 1, None))                 # FUN_1100_1d34: a block sound is not positional
        played.clear()
        w.damage(self.bot, None, 25, 0, 6, False)
        self.assertEqual(played[0], '_BLOCK_NURSEBOT')
        played.clear()
        self.sounds(known=False)
        w.damage(self.bot, self.lex, 25, 0, 2, False)                  # unknown names play nothing

    def test_hit_and_block_names_fall_back_to_shorter_names(self):
        """1118:0044 cuts a formatted name at its last `_` until the bank has it: the camera-suffixed hit names fall back to
        `_<A>_HITS_<T>`, the block names to `_BLOCK`."""
        w, played = self.w, []
        w.play_sound = lambda idx, volume=255, pitch=0, loop=False, priority=1, fig=None: played.append((idx, priority, fig))
        w.damage(self.bot, self.lex, 25, 0, 2, False)
        self.assertEqual(played[0], (w.sound_index('_LEX_HITS_NURSEBOT'), 1, self.bot))
        played.clear()
        self.bot.invulnerable = True
        w.damage(self.bot, self.lex, 25, 0, 2, False)
        self.assertEqual(played[0], (w.sound_index('_BLOCK'), 1, None))
        self.assertEqual((w.ambient_id('_CAYNAN_HITS_LEX_CE31'), w.ambient_id('_BLOCK_LEX_ELITE_X')),
                         (w.sound_index('_CAYNAN_HITS_LEX'), w.sound_index('_BLOCK_LEX_ELITE')))

    def test_unknown_sound_name_plays_nothing(self):
        played = self.sounds(known=False)
        self.w.damage(self.bot, self.lex, 25, 0, 2, False)
        self.assertTrue(all(p[0] != 'PLAY' for p in played if isinstance(p, tuple)))

    def spy_blocks(self):
        """Record every block run_figure_block is asked for (the real AI_NURSE defines NURSEBOT_WOUNDS, loaded on demand)."""
        ran, orig = [], self.w.run_figure_block
        self.w.run_figure_block = lambda fig, block: ran.append((fig.name, block)) or orig(fig, block)
        return ran

    def test_wounds_block_runs_on_a_hit_with_the_type_name(self):
        ran = self.spy_blocks()
        self.vm.objects['FIRSTBOT'][0] = 100
        self.bot.invulnerable = False
        self.w.damage(self.bot, self.lex, 25, 0, 2, False)
        self.assertEqual(ran, [('FIRSTBOT', 'NURSEBOT_WOUNDS')])
        ran.clear()
        self.w.damage(self.lex, self.bot, 25, 0, 2, False)             # the player: LEX_WOUNDS (DAMAGE.scr)
        self.assertEqual(ran, [('LEX', 'LEX_WOUNDS')])

    def test_death_runs_wounds_then_suspends_ai_sets_invulnerable_and_runs_death_block(self):
        self.script('{ FIRSTBOT_DEATH\n\t_door_frame = 42\n}\n')
        vm, bot = self.vm, self.bot
        vm.globals['_door_frame'] = 0
        bot.ai_proc = type('P', (), {'done': False, 'suspended': False})()
        vm.objects['FIRSTBOT'][0] = 5
        bot.invulnerable = False
        ran = self.spy_blocks()
        self.labels(set())
        self.w.damage(bot, self.lex, 25, 1, 2, False)                  # energy: the nurse's IMPACT_ARMOR 100 would absorb it
        self.assertEqual(ran, [('FIRSTBOT', 'NURSEBOT_WOUNDS'), ('FIRSTBOT', 'FIRSTBOT_DEATH')])
        self.assertEqual(vm.globals['_door_frame'], 42)
        self.assertEqual((bot.invulnerable, bot.hold, bot.ai_proc.suspended), (True, 1, True))
        self.assertLessEqual(vm.objects['FIRSTBOT'][0], 0)

    def test_a_living_target_gets_no_death_handling(self):
        ran = self.spy_blocks()
        self.vm.objects['FIRSTBOT'][0] = 100
        self.bot.invulnerable = False
        self.w.damage(self.bot, self.lex, 25, 0, 2, False)
        self.assertEqual((self.bot.invulnerable, self.bot.hold), (False, 0))
        self.assertNotIn('FIRSTBOT_DEATH', [b for _, b in ran])

    def test_dead_player_gets_killed_player_on_the_attacker_and_no_input(self):
        log = self.labels(set())
        self.vm.objects['LEX'][0] = 3
        self.w.damage(self.lex, self.bot, 10, 0, 2, False)
        self.assertEqual([l[:2] for l in log], [('FIRSTBOT', 'KILLED_PLAYER')])
        self.assertTrue(self.lex.invulnerable)
        self.assertEqual(self.lex.hold, 1)
        self.lex.pos, self.lex.heading = np.array([0, 0, 0.0]), 0.0
        self.w.set_player_input(forward=1)
        self.w.apply_player_input()
        self.assertFalse(self.lex.manual_control)


if __name__ == '__main__':
    unittest.main()
