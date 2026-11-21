"""Items and combat rules (re/NOTES.md "Items and combat"), twin of native/Tests/BioForgeCoreTests/ItemsCombatTests.swift with the same numbers:
R1 the item list (duplicate names, INDIVIDUALIZE, SETCURRENTITEM, ISCARRYING), R2 item position / hull / AMINTRIGGER and the MY_HAND attach,
R4 the motion gates, death and AI ON, R5 TURN.
    re/.venv/bin/python -I -W ignore -m unittest discover -s re/interp -p 'test_items_combat.py'"""
import os
import sys
import types
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import vm as vmmod  # noqa: E402
import world as worldmod  # noqa: E402
from test_world import cmd  # noqa: E402

LEX = 'LEX'
LEX_POS = (495.0, -28827.0, -5000.0)          # settles to z -5093 on the CHAOS floor
HAND = (-322, -29118, -6092)                  # CAYARM in Lex's RTHAND at STAND frame 0, heading 0 (rounded engine position)


def stub(fig, item=None):
    return types.SimpleNamespace(block=types.SimpleNamespace(name='TEST'), cur_fig=fig, cur_item=item, handle=0, waiters=[])


def call(w, kind, name, args, p):
    return w.call(kind, name, list(args), p)


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.w = worldmod.World('CHAOS', state_dir=worldmod.INITGAME)
        cls.vm = vmmod.VM(cls.w)
        vmmod.load_level(cls.vm, 'CHAOS')
        cmd(cls.w, 'CREATEFIGURE', 'LEX', 'PLAYER')
        cls.lex = cls.w.player()
        cls.n_triggers = len(cls.w.triggers)

    def setUp(self):
        w = self.w
        w.items.clear()
        w.vm.objects.clear()
        w.pick_targets.clear()
        del w.triggers[self.n_triggers:]
        self.lex.pos, self.lex.heading = np.array(LEX_POS), 0.0
        w.settle(self.lex)
        self.lex.set_motion('STAND', True)
        self.lex.hold, self.lex.finished = 0, False
        self.vm.objects[w.object_key(self.lex.name)][0] = 100
        self.p = stub(LEX)

    def item(self, name, itype, pos=None, owner=None, slot=None):
        it = worldmod.Item(name, itype, owner, slot)
        if pos is not None:
            it.pos, it.matrix = np.array(pos, float), np.eye(3)
        return self.w.add_item(it)

    def trigger(self, lo, hi):
        self.w.triggers.append({'name': 'TESTBOX', 'lo': list(lo), 'hi': list(hi), 'once': False, 'camera': None})


class ItemList(Base):
    def test_createitem_keeps_the_type_as_name_and_duplicates_coexist(self):
        p = self.p
        call(self.w, 'stmt', 'CREATEITEM', ['ABAT_500'], p)
        first = p.cur_item
        self.vm.objects[first][0] = 150
        call(self.w, 'stmt', 'CREATEITEM', ['ABAT_500'], p)
        self.vm.objects[p.cur_item][0] = 500
        self.assertEqual((first, p.cur_item), ('ABAT_500', 'ABAT_500#2'))
        self.assertEqual([(i.key, i.name, i.type) for i in self.w.items.values()],
                         [('ABAT_500', 'ABAT_500', 'ABAT_500'), ('ABAT_500#2', 'ABAT_500', 'ABAT_500')])
        self.assertEqual((self.vm.objects['ABAT_500'][0], self.vm.objects['ABAT_500#2'][0]), (150, 500))      # each keeps its own locals

    def test_individualize_renames_in_place_and_every_process_follows(self):
        w, p = self.w, self.p
        call(w, 'stmt', 'CREATEITEM', ['ABAT_500'], p)
        self.vm.objects['ABAT_500'][0] = 150
        call(w, 'stmt', 'CREATEITEM', ['ABAT_500'], p)                    # the second is current
        other = stub(LEX, 'ABAT_500')                                     # another process points at the first
        self.vm.procs[9999] = other
        try:
            p.cur_item = 'ABAT_500'
            call(w, 'stmt', 'INDIVIDUALIZE', ['CURITEM', 'ALIENBAT'], p)
        finally:
            del self.vm.procs[9999]
        self.assertEqual(list(w.items), ['ALIENBAT', 'ABAT_500#2'])      # list position kept
        self.assertEqual((p.cur_item, other.cur_item), ('ALIENBAT', 'ALIENBAT'))
        self.assertEqual((w.items['ALIENBAT'].name, self.vm.objects['ALIENBAT'][0], 'ABAT_500' in self.vm.objects), (
            'ALIENBAT', 150, False))
        call(w, 'stmt', 'CREATEITEM', ['ABAT_500'], p)                    # the freed name is a fresh item with zeroed locals
        self.assertEqual((p.cur_item, self.vm.objects['ABAT_500'][0]), ('ABAT_500', 0))

    def test_setcurrentitem_nearest_by_type_or_instance_first_on_ties_and_unchanged_on_a_miss(self):
        w, p = self.w, self.p
        far = self.item('FORK', 'FORK', (495.0, -27827.0, -5000.0))        # 1000 away
        near = self.item('FORK', 'FORK', (495.0, -29327.0, -5000.0))       # 500 away
        tie = self.item('FORK', 'FORK', (1495.0, -28827.0, -5000.0))       # 1000 away
        named = self.item('SPOON', 'FORK', (495.0, -28727.0, -5000.0))     # 100 away; instance SPOON
        self.assertEqual((far.key, near.key, tie.key), ('FORK', 'FORK#2', 'FORK#3'))
        self.assertEqual(call(w, 'func', 'SETCURRENTITEM', ['FORK'], p), 1)
        self.assertEqual(p.cur_item, named.key)                            # the type matches SPOON too; it is nearest
        self.assertEqual(call(w, 'func', 'SETCURRENTITEM', ['SPOON'], p), 1)
        named.type = 'SPORK'
        self.assertEqual(call(w, 'func', 'SETCURRENTITEM', ['FORK'], p), 1)
        self.assertEqual(p.cur_item, near.key)                             # 500 beats the 1000 pair
        near.pos = np.array([495.0, -27827.0, -5000.0])                    # now three at 1000
        call(w, 'func', 'SETCURRENTITEM', ['FORK'], p)
        self.assertEqual(p.cur_item, far.key)                              # the first wins the tie
        p.cur_item = tie.key
        self.assertEqual(call(w, 'func', 'SETCURRENTITEM', ['NOSUCH'], p), 0)
        self.assertEqual(p.cur_item, tie.key)                              # unchanged

    def test_setcurrentitem_with_a_hand_needs_the_item_in_that_hand(self):
        w, p = self.w, self.p
        held = self.item('FORK', 'FORK', owner=LEX, slot='LTHAND')
        self.assertEqual(call(w, 'func', 'SETCURRENTITEM', ['RTHAND'], p), 0)
        self.assertIsNone(p.cur_item)
        self.assertEqual(call(w, 'func', 'SETCURRENTITEM', ['LTHAND'], p), 1)
        self.assertEqual(p.cur_item, held.key)

    def test_iscarrying_inventory_anywhere_and_hands(self):
        w, p = self.w, self.p
        self.item('DANELOG', 'LOGBOOK', owner=LEX, slot='LTHAND')
        self.item('BLASTER', 'BLASTER', owner=LEX, slot='INVENTORY')
        p.cur_item = 'DANELOG'
        isc = lambda *a: call(w, 'func', 'ISCARRYING', a, p)
        self.assertEqual([isc('INVENTORY', 'BLASTER'), isc('INVENTORY', 'DANELOG'), isc('INVENTORY', 'LOGBOOK')], [1, 0, 0])
        self.assertEqual([isc('ANYWHERE', 'BLASTER'), isc('ANYWHERE', 'DANELOG'), isc('ANYWHERE', 'LOGBOOK'), isc('ANYWHERE', 'NOSUCH')], [1, 1, 1, 0])
        self.assertEqual([isc('LTHAND', 'LOGBOOK'), isc('LTHAND', 'DANELOG'), isc('RTHAND', 'LOGBOOK')], [1, 0, 0])      # a hand compares the TYPE
        self.assertEqual(p.cur_item, 'DANELOG')                            # CURITEM restored after the search

    def test_iscarrying_anywhere_looks_at_the_nearest_item_only(self):
        w, p = self.w, self.p
        self.item('FORK', 'FORK', owner=LEX, slot='INVENTORY')        # at the holder's origin: distance 0
        self.item('FORK', 'FORK', (495.0, -28727.0, -5000.0))              # on the floor, 100 away
        self.assertEqual(call(w, 'func', 'ISCARRYING', ['ANYWHERE', 'FORK'], p), 1)
        self.w.items['FORK'].slot = 'LTHAND'                               # now the hand pose (about 820 away) loses to the floor item
        self.assertEqual(call(w, 'func', 'ISCARRYING', ['ANYWHERE', 'FORK'], p), 0)

    def test_the_object_argument_by_name_is_the_first_item_of_that_type(self):
        w = self.w
        self.item('SPOON', 'FORK', (0.0, 0.0, 0.0))
        self.item('FORK', 'FORK', (100.0, 0.0, 0.0))
        self.assertEqual(w.item_by_type('FORK').name, 'SPOON')
        self.assertIsNone(w.item_by_type('SPOON'))                         # the instance name does not count here
        self.assertEqual(call(w, 'func', 'COORDX', ['FORK'], self.p), 0)


class ItemPosition(Base):
    def test_floor_item_hull_is_pos_plus_minus_extent_and_touching_is_inclusive(self):
        w, p = self.w, self.p
        self.trigger((0, 0, 0), (1000, 1000, 1000))
        arm = self.item('CAYARM', 'CAYARM', (1204.0, 500.0, 500.0))        # EXTENT 10 cm = 204 units: lo x = 1000, touching hi x
        p.cur_item = arm.key
        self.assertEqual(call(w, 'func', 'AMINTRIGGER', ['CURITEM', 'TESTBOX'], p), 1)
        arm.pos[0] = 1205.0
        self.assertEqual(call(w, 'func', 'AMINTRIGGER', ['CURITEM', 'TESTBOX'], p), 0)
        arm.pos[:] = (-204.0, 500.0, 500.0)                                # hi x = 0 = lo x of the trigger
        self.assertEqual(call(w, 'func', 'AMINTRIGGER', ['CURITEM', 'TESTBOX'], p), 1)
        self.assertEqual(call(w, 'func', 'AMINTRIGGER', ['CAYARM', 'TESTBOX'], p), 1)   # by type name

    def test_an_item_without_extent_is_a_point(self):
        w, p = self.w, self.p
        self.trigger((0, 0, 0), (1000, 1000, 1000))
        bat = self.item('ABAT_500', 'ABAT_500', (1000.0, 1000.0, 1000.0))
        p.cur_item = bat.key
        self.assertEqual(call(w, 'func', 'AMINTRIGGER', ['CURITEM', 'TESTBOX'], p), 1)
        bat.pos[2] = 1001.0
        self.assertEqual(call(w, 'func', 'AMINTRIGGER', ['CURITEM', 'TESTBOX'], p), 0)

    def test_a_held_item_is_where_the_hand_is(self):
        w, p = self.w, self.p
        arm = self.item('CAYARM', 'CAYARM', owner=LEX, slot='RTHAND')
        pos = w.item_engine_pos(arm)
        self.assertEqual(tuple(int(round(c)) for c in pos), HAND)
        p.cur_item = arm.key
        self.trigger((HAND[0] + 204, -40000, -9000), (HAND[0] + 2000, -20000, -3000))      # lo x = hand x + 204: touching the hull's hi x
        self.assertEqual(call(w, 'func', 'AMINTRIGGER', ['CURITEM', 'TESTBOX'], p), 1)
        w.triggers[-1]['lo'][0] = HAND[0] + 205
        self.assertEqual(call(w, 'func', 'AMINTRIGGER', ['CURITEM', 'TESTBOX'], p), 0)
        self.assertEqual(call(w, 'func', 'COORDX', ['CURITEM'], p), HAND[0] >> 8)

    def test_an_inventory_item_is_where_the_holder_is(self):
        w, p = self.w, self.p
        arm = self.item('CAYARM', 'CAYARM', owner=LEX, slot='INVENTORY')
        self.assertEqual(tuple(int(round(c)) for c in w.item_engine_pos(arm)), (495, -28827, -5093))
        p.cur_item = arm.key
        self.trigger((495 + 204, -30000, -6000), (3000, -27000, -4000))
        self.assertEqual(call(w, 'func', 'AMINTRIGGER', ['CURITEM', 'TESTBOX'], p), 1)
        w.triggers[-1]['lo'][0] = 495 + 205
        self.assertEqual(call(w, 'func', 'AMINTRIGGER', ['CURITEM', 'TESTBOX'], p), 0)

    def test_a_holder_without_the_limb_attaches_in_its_my_hand(self):
        w = self.w
        bot = w.figure('USE_BOT')                                          # NURSEBOT: MY_HAND = UP_ARM, no RTHAND limb
        arm, arm2 = self.item('CAYARM', 'CAYARM', (0.0, 0.0, 0.0)), self.item('CAYARM', 'CAYARM', (0.0, 0.0, 0.0))
        self.assertEqual(w.my_hand(bot), 'UP_ARM')
        self.assertTrue(w.attach_item(bot, arm))
        self.assertEqual((arm.owner, arm.slot), ('USE_BOT', 'UP_ARM'))
        self.assertFalse(w.attach_item(bot, arm2))                         # the hand is occupied
        self.assertIsNone(w.held_item(bot, 'RTHAND'))
        self.assertIs(w.held_item(bot, 'UP_ARM'), arm)
        self.assertIs(w.held_any(bot), arm)                                # FUN_1138_036e counts MY_HAND
        self.assertIsNotNone(w.item_world_pose(arm))                       # hand_pose finds the limb now
        self.assertTrue(w.attach_item(self.lex, arm2))                     # Lex has the limb: HANDEDNESS RTHAND
        self.assertEqual(arm2.slot, 'RTHAND')
        arm3 = self.item('CAYARM', 'CAYARM', (0.0, 0.0, 0.0))
        bot2 = w.figure('FIRSTBOT')
        w.place_item(bot2, arm3, 'CARRY')
        self.assertEqual(arm3.slot, 'UP_ARM')


class Combat(Base):
    def setUp(self):
        super().setUp()
        w = self.w
        self.bot = w.figure('FIRSTBOT')
        self.bot.view_cams = None
        self.vm.globals['_difficulty_level'] = 0
        self.bot.pos, self.bot.heading = np.array([495.0, -30827.0, -5000.0]), 0.0
        self.lex.invulnerable = False
        self.lex.hold = self.bot.hold = 0
        self.lex.finished = False

    def hp(self, fig, value):
        self.vm.objects[self.w.object_key(fig.name)][0] = value

    def finish(self, fig):
        motion = fig.motion
        for _ in range(2000):
            if fig.finished or fig.motion != motion:          # 1088:4155 takes a finished motion straight to the idle
                return
            self.w.step()
        self.fail('motion did not finish')

    def test_turn_n_is_n_degrees_toward_the_left(self):
        self.lex.heading = -90.0
        cmd(self.w, 'TURN', -5)
        self.assertEqual(self.lex.heading, -85.0)
        cmd(self.w, 'TURN', 10)
        self.assertEqual(self.lex.heading, -95.0)

    def test_a_scripted_motion_of_the_same_name_is_refused_and_not_restarted(self):
        w, lex = self.w, self.lex
        p = types.SimpleNamespace(wait_pred=None)
        w.cmd_motion(lex, 'TAUNT1', ['CONTINUE'], p)
        mot_id = lex.mot_id
        for _ in range(3):
            w.step()
        idx = lex.idx
        q = types.SimpleNamespace(wait_pred=None)
        w.cmd_motion(lex, 'TAUNT1', [], q)                                 # blocking form: refused = a zero handle, no wait
        self.assertEqual((lex.mot_id, lex.idx, q.wait_pred), (mot_id, idx, None))
        w.cmd_motion(lex, 'TAUNT1', ['NO_SCRIPT', 'CONTINUE'], q)          # NO_SCRIPT skips the gate
        self.assertNotEqual(lex.mot_id, mot_id)
        w.cmd_motion(lex, 'TAUNT1', ['CONTINUE'], p)
        self.finish(lex)
        mot_id = lex.mot_id
        w.cmd_motion(lex, 'TAUNT1', ['CONTINUE'], p)                       # the task has ended: accepted again
        self.assertNotEqual(lex.mot_id, mot_id)

    def test_a_recoil_die_or_super_rec_task_refuses_other_scripted_motions(self):
        w, lex = self.w, self.lex
        p = types.SimpleNamespace(wait_pred=None)
        w.cmd_motion(lex, 'RECOIL_TL', ['CONTINUE'], p)
        w.cmd_motion(lex, 'TAUNT1', ['CONTINUE'], p)
        self.assertEqual(lex.motion, 'RECOIL_TL')                          # refused while RECOIL* is the task
        self.finish(lex)
        w.cmd_motion(lex, 'TAUNT1', ['CONTINUE'], p)
        self.assertEqual(lex.motion, 'TAUNT1')
        lex.task_name = 'SUPER_REC_TL'                                     # 9 characters prefix
        lex.finished = False
        w.cmd_motion(lex, 'STAND', ['CONTINUE'], p)
        self.assertEqual(lex.motion, 'TAUNT1')

    def test_an_unfinished_die_refuses_snap_to_and_snaptopose_too(self):
        w, lex = self.w, self.lex
        p = types.SimpleNamespace(wait_pred=None)
        w.cmd_motion(lex, 'DIE', ['NO_SCRIPT', 'CONTINUE'], p)
        w.step()
        w.cmd_motion(lex, 'WAKE_UP', ['NO_SCRIPT', 'SNAP_TO', 'FREEZE'], p)
        self.assertEqual(lex.motion, 'DIE')
        w.cmd_snaptopose(lex, ['WAKE_UP', 3])
        self.assertEqual((lex.motion, lex.idx < 3), ('DIE', True))

    def test_a_finished_die_accepts_a_motion_with_hit_points_or_without(self):
        w, lex = self.w, self.lex
        p = types.SimpleNamespace(wait_pred=None)
        for hp in (100, 0):
            self.hp(lex, hp)
            w.cmd_motion(lex, 'DIE', ['CONTINUE'], p)
            self.assertEqual(lex.motion, 'DIE')
            self.finish(lex)
            w.cmd_motion(lex, 'WAKE_UP', ['CONTINUE'], p)
            self.assertEqual(lex.motion, 'WAKE_UP', hp)                    # the engine has no corpse lock (1098:0394 / 12bd)

    def test_ai_on_is_refused_with_a_warning_at_zero_hit_points(self):
        w, lex = self.w, self.lex
        lex.hold = 1
        self.hp(lex, 0)
        cmd(w, 'AI', 'ON')
        self.assertEqual((lex.ai_enabled, lex.hold), (False, 1))
        self.assertTrue(any('AI ON' in m for m in w.warnings))
        self.hp(lex, 5)
        cmd(w, 'AI', 'ON')
        self.assertTrue(lex.ai_enabled)

    def test_a_dead_figure_does_not_idle_after_an_engine_one_shot(self):
        w, lex = self.w, self.lex
        for hp, expect in ((0, 'LAND_SOFT'), (5, 'STAND')):
            self.hp(lex, hp)
            lex.set_motion('LAND_SOFT', False, engine=True)
            for _ in range(60):                                            # 8 frames: over after 17 ticks
                w.step()
            self.assertEqual(lex.motion, expect, hp)                       # 1088:508d: idle only with hit points

    def test_the_killer_of_the_player_gets_the_die_method_too(self):
        w, lex, bot = self.w, self.lex, self.bot
        self.hp(lex, 5)
        w.damage(lex, bot, 10, 0, 6, False)                                # hp <= 0 with an attacker
        self.assertEqual((lex.hold, bot.hold), (1, 1))
        lex.hold = bot.hold = 0
        self.hp(lex, 5)
        lex.invulnerable = False
        w.damage(lex, None, 10, 0, 6, False)                               # a DAMAGE statement: no attacker, no second hold
        self.assertEqual((lex.hold, bot.hold), (1, 0))


if __name__ == '__main__':
    unittest.main()
