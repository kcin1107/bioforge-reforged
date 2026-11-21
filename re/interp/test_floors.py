"""Tests for floors.py: SETFLOOROFPHYS and TELEPORTALLONPHYS, on CONTROL's real PHYS data and its real garage elevator scripts. The Swift
twin is FloorsTests.swift (same cases, same numbers).  re/.venv/bin/python -I -W ignore -m unittest discover -s re/interp -p 'test_floors.py'"""
import os
import sys
import types
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_items  # noqa: E402
import vm as vmmod  # noqa: E402
import world as worldmod  # noqa: E402

NO_FLOOR = worldmod.NO_FLOOR

PLAYER_POS = (44000.0, -60000.0)        # inside ELV, QSF and CTR in x and y
DZ = 2333                               # Lex's z above his hull bottom: foot offset 2312 + 21 (hull_units(s))


def control(player_z=None):
    """CONTROL with Lex (gravity off, as the elevator scripts leave him) standing at (44000, -60000); his hull bottom 21 below the ELV
    floor when ``player_z`` is None (the garage)."""
    w = worldmod.World('CONTROL', state_dir=worldmod.INITGAME)
    vm = vmmod.VM(w)
    vmmod.load_level(vm, 'CONTROL')
    w.call('stmt', 'CREATEFIGURE', ['LEX', 'PLAYER'], test_items.stub())
    lex = w.player()
    lex.gravity = False
    w.set_pos(lex, [PLAYER_POS[0], PLAYER_POS[1], -165174 + DZ if player_z is None else player_z], raw=True)
    return w, vm, lex


def phys(w, name):
    p = w.find_phys(name)
    return int(p['lo'][2]), int(p['hi'][2])


def setfloor(w, *args):
    w.call('stmt', 'SETFLOOROFPHYS', list(args), test_items.stub())


def teleport(w, *args):
    w.call('stmt', 'TELEPORTALLONPHYS', list(args), test_items.stub())


class AreaFloor(unittest.TestCase):
    """support / point_floor rank only the figure's area members, seeded with the anchor's floor (FUN_1060_03f2 / 0871, 1060:040d-045c)."""

    def stand(self, z):
        w, vm, lex = control(z)
        lex.gravity = True
        w.select_area(lex)
        lo, hi = w.hull(lex)
        return w, lex, lo, hi

    def test_the_garage_floor_is_elv_not_the_control_room_above_it(self):
        w, lex, lo, hi = self.stand(-165153 + 2312)
        self.assertEqual(w.phys[lex.area]['name'], 'ELV')
        self.assertEqual([m[0]['name'] for m in w.area_members(lex.area)], ['ELV', 'DOR', 'SH1'])
        self.assertEqual((w.support(lex, lo, hi, w.area_of(lex)), w.support(lex, lo, hi)), (-165153, -9302))      # scoped, global (QSF pit)
        self.assertEqual(w.query_hull(lex)[2], -165153)
        self.assertEqual(w.point_floor(44000, -60000, lo[2], hi[2], w.area_of(lex)), -165153)
        test_items.run(w, w.vm, 5)
        self.assertEqual((lex.pos[2], lex.falling, w.phys[lex.area]['name']), (-165153 + 2312, False, 'ELV'))     # stays on ELV

    def test_the_control_room_still_gets_its_floor(self):
        w, lex, lo, hi = self.stand(-7160)
        self.assertEqual(w.phys[lex.area]['name'], 'QSF')
        self.assertEqual((w.support(lex, lo, hi, w.area_of(lex)), w.support(lex, lo, hi)), (-9302, -9302))
        self.assertEqual(w.point_floor(44000, -60000, lo[2], hi[2], w.area_of(lex)), -9302)

    def test_the_anchor_seeds_the_result_without_an_xy_test(self):
        w, lex, lo, hi = self.stand(-165153 + 2312)
        far = ([-1000000, -1000000, -165174], [-999000, -999000, -161000])
        self.assertEqual(w.support(lex, *far, w.area_of(lex)), -165153)          # a space seeds lo.z
        self.assertEqual(w.support(lex, *far), NO_FLOOR)
        self.assertEqual((w.point_floor(0, 0, -165000, -165000, w.area_of(lex)), w.point_floor(0, 0, -165000, -165000)), (-165153, NO_FLOOR))
        # the anchor's state selects the slot: a solid seeds hi.z, a state 2 anchor seeds nothing
        for state, seed in ((1, -150093), (2, NO_FLOOR)):
            area = w.area_of(lex)
            area = area[:5] + (state,)
            self.assertEqual(w.support(lex, *far, area), seed)

    def test_a_null_area_falls_back_to_the_global_scan(self):
        w, lex, lo, hi = self.stand(-165153 + 2312)
        lex.area = None
        self.assertIsNone(w.area_of(lex))
        self.assertEqual(w.query_hull(lex)[2], -9302)
        self.assertEqual(w.point_floor(44000, -60000, lo[2], hi[2], None), -9302)


class AreaTriggers(unittest.TestCase):
    def test_a_moved_anchor_keeps_the_triggers_it_touched_at_load(self):
        """RoomType->triggers (FUN_1138_131c) are the IMAGs that touch the anchor's box; the port built each list on the first query, and the
        garage lift's first query came while LOWER_GARAGE_ELEVATOR had raised ELV to -633 (box no longer touching TAKEMEUP, z -165153..-164129):
        the list stayed empty and the trigger that raises the lift never fired. ASSUMPTION: the lists are built with the level."""
        w, vm, lex = control()
        elv = next(k for k, p in enumerate(w.phys) if p['name'] == 'ELV')
        setfloor(w, 'ELV', -633)
        self.assertEqual(phys(w, 'ELV'), (-162048, -146988))
        self.assertEqual([w.triggers[j]['name'] for j in w.area_triggers(elv)],
                         ['CAM_SHO5', 'CAM_SHO5', 'CAM_SHO5', 'CAM_SHO1', 'TAKEMEUP', 'MSENTER'])


class SetFloor(unittest.TestCase):
    def test_a_space_sets_its_bottom_and_keeps_its_height(self):
        w, vm, lex = control()
        self.assertEqual(phys(w, 'ELV'), (-165153, -150093))
        setfloor(w, 'ELV', -642)                                 # -642 << 8
        self.assertEqual((phys(w, 'ELV'), w.warnings), ((-164352, -149292), []))
        self.assertEqual(w.find_phys('ELV')['lo'][:2].tolist(), [34553, -63386])     # x and y untouched

    def test_a_solid_sets_its_top(self):
        w, vm, lex = control()
        self.assertEqual((w.phys_state(w.find_phys('TWIN3')), phys(w, 'TWIN3')), (1, (-7431, -5019)))
        setfloor(w, 'TWIN3', -10)
        self.assertEqual(phys(w, 'TWIN3'), (-4972, -2560))

    def test_zero_unknown_name_and_a_bad_state_only_warn(self):
        w, vm, lex = control()
        before = [phys(w, p['name']) for p in w.phys]
        setfloor(w, 'ELV', 0)
        setfloor(w, 'ELV', 65536)                                # low 16 bits are 0
        setfloor(w, 'NOSUCH', -5)
        setfloor(w, 'WK1', -5)                                   # state 2
        setfloor(w, '', -5)
        self.assertEqual([phys(w, p['name']) for p in w.phys], before)
        self.assertEqual(len(w.warnings), 4)           # the two zero forms share a message

    def test_only_the_low_16_bits_count(self):
        w, vm, lex = control()
        setfloor(w, 'ELV', 65536 - 642)
        self.assertEqual(phys(w, 'ELV'), (-164352, -149292))
        setfloor(w, 'QSF', 0x10000 + 0x8000)                     # 0x8000 = -32768 << 8
        self.assertEqual(phys(w, 'QSF')[0], -32768 * 256)

    def test_the_box_cache_is_invalidated(self):
        w, vm, lex = control()
        w._boxes = w._phys_boxes()                               # as step() holds it while a script runs
        self.assertEqual(w.point_floor(44000, -60000, -10000, 0), -9302)         # QSF pit
        setfloor(w, 'QSF', -57)
        self.assertEqual(phys(w, 'QSF'), (-14592, -8676))
        self.assertEqual(w.point_floor(44000, -60000, -10000, 0), -14592)
        self.assertEqual(next(b for b in w._boxes if b[0]['name'] == 'QSF')[2][2], -14592)
        lo, hi = w.hull(lex, pos=[44000, -60000, -9000])
        self.assertEqual(w.support(lex, list(lo), list(hi)), -14592)
        w._boxes = None
        setfloor(w, 'QSF', -37)
        self.assertEqual(w.point_floor(44000, -60000, -10000, 0), -9472)         # no cache: read fresh


class Teleport(unittest.TestCase):
    def test_a_self_teleport_keeps_x_y_and_reseats_z_on_the_floor(self):
        w, vm, lex = control(-100000)                            # z is not tested
        lex.vx = 7
        teleport(w, 'ELV', 'ELV')
        self.assertEqual((lex.pos.tolist(), lex.vx), ([44000, -60000, -165153 + DZ], 0))
        setfloor(w, 'ELV', -642)
        teleport(w, 'ELV', 'ELV')
        self.assertEqual(lex.pos.tolist(), [44000, -60000, -164352 + DZ])

    def test_the_teleport_uses_the_hull_from_before_the_floor_moved(self):
        w, vm, lex = control()                                   # hull bottom 21 below ELV: 21b2 raised it onto the floor
        setfloor(w, 'ELV', -642)                                 # 708e rebuilds no hulls; the live hull would not reach the new floor
        teleport(w, 'ELV', 'ELV')
        self.assertEqual(lex.pos.tolist(), [44000, -60000, -164352 + 2312])
        self.assertIsNone(lex.stored_hull)                       # set_pos rebuilds it

    def test_elv_to_qsf_scales_x_and_y(self):
        w, vm, lex = control()
        teleport(w, 'ELV', 'QSF')                                # sx 255, sy 282
        # z' = floor + (z - hull bottom): the hull bottom is raised onto the floor under it (ELV's, 21 above it) now that support is
        # scoped to the figure's area, so the offset is the foot offset 2312 (the global support took QSF and left the bottom 21 lower)
        self.assertEqual(lex.pos.tolist(), [34489 + (9447 * 255 >> 8), -64698 + (3386 * 282 >> 8), -9302 + 2312])
        self.assertEqual(lex.pos.tolist(), [43899, -60969, -6990])
        teleport(w, 'QSF', 'ELV')                                # sx 256, sy 232
        self.assertEqual(lex.pos.tolist(), [34553 + (9410 * 256 >> 8), -63386 + (3729 * 232 >> 8), -165153 + DZ - 21])

    def test_a_hull_outside_a_in_x_or_y_is_not_moved(self):
        for x, y in ((53761 - 300, -60000), (44000, -53341 - 300), (34553 + 300, -60000), (44000, -63386 + 300)):
            w, vm, lex = control()
            w.set_pos(lex, [x, y, -165174 + DZ], raw=True)
            teleport(w, 'ELV', 'QSF')
            self.assertEqual(lex.pos.tolist(), [x, y, -165174 + DZ])

    def test_unknown_names_only_warn(self):
        w, vm, lex = control()
        teleport(w, 'ELV', 'NOSUCH')
        teleport(w, 'NOSUCH', 'ELV')
        teleport(w, 'ELV')
        self.assertEqual((lex.pos.tolist(), len(w.warnings)), ([44000, -60000, -165174 + DZ], 2))     # the two NOSUCH forms share one

    def test_items_move_too(self):
        w, vm, lex = control()
        def put(name, item_type, x, y, z):
            it = worldmod.Item(name, item_type)
            it.pos, it.matrix, it.vel = np.array([x, y, z], float), np.eye(3), [5, 0, 0]
            w.items[name] = it
            return it
        plain = put('PLAIN', 'GRENADE', 44000, -60000, -100000)
        loaded = put('LOADED', 'GRENADE', 44000, -60000, -100000)
        w.load_item_physics(loaded)
        held = worldmod.Item('HELD', 'GRENADE', 'PLAYER')
        w.items['HELD'] = held
        outside = put('OUTSIDE', 'GRENADE', 34553, -60000, -100000)          # the point is on A's edge: not strictly inside
        missile = worldmod.Missile('MISSILE', 'GRENADE')
        missile.pos, missile.extent = np.array([44000.0, -60000.0, 0.0]), [50, 50, 50]
        w.items['MISSILE'] = missile
        teleport(w, 'ELV', 'QSF')
        self.assertEqual(plain.pos.tolist(), [43899, -60969, -9302])         # ASSUMPTION: no EXTENT loaded -> dz 0
        self.assertEqual((loaded.pos.tolist(), loaded.extent[2]), ([43899, -60969, -9302 + 102], 102))
        self.assertEqual(missile.pos.tolist(), [43899, -60969, -9302 + 50])
        self.assertEqual((plain.vel, plain.step), ([0, 0, 0], [0, 0, 0]))
        self.assertEqual((held.pos, outside.pos.tolist()), (None, [34553, -60000, -100000]))


def ride(w, vm, lex, ticks, block=None):
    """Run ``ticks`` frames (spawning the real script ``block`` first, if any) -> per frame (player z, ELV lo.z, QSF lo.z)."""
    if block:
        vm.spawn(block, ctx=types.SimpleNamespace(cur_fig='PLAYER', cur_item=None, owner='level'))
    out = []
    for _ in range(ticks):
        test_items.run(w, vm, 1)
        out.append((int(lex.pos[2]), phys(w, 'ELV')[0], phys(w, 'QSF')[0]))
    return out


class Ride(unittest.TestCase):
    def test_the_real_garage_elevator_up_and_down(self):
        """Lex stands on ELV (hull bottom 21 below the floor, gravity off) and enters the TAKEMEUP trigger, which runs
        the real CONMACH RAISE_GARAGE_ELEVATOR: z follows ELV (00:04 .. 00:16, ticks 5 .. 20), the teleport at 00:20 takes Lex to QSF
        (tick 21), which then rises to the control room floor, and GRAVITY ON at 02:20 (tick 81) leaves him standing on it.
        LOWER_GARAGE_ELEVATOR (the end of CR_HANGERMONITOR) then takes him back to the garage."""
        w, vm, lex = control()
        up = ride(w, vm, lex, 100)
        self.assertEqual(vm.globals['_elev_frame'], 8)
        self.assertEqual([r[0] for r in up[:5]], [-165174 + DZ] * 5)                   # the trigger ran; the first step is at 00:04
        self.assertEqual([up[n][1] for n in (5, 9, 13, 17)], [-164352, -163584, -163072, -162048])      # ELV -642, -639, -637, -633
        for n in range(5, 21):
            self.assertEqual(up[n][0], up[n][1] + 2312, n)                            # player z = ELV lo.z + F at every ELV step
        for n in range(21, 81):
            self.assertEqual(up[n][0], up[n][2] + 2312, n)                              # then QSF lo.z + constant (rising -57 .. -37)
        self.assertEqual((up[41][0], up[41][2], up[80][2]), (-14592 + 2312, -14592, -9984))
        self.assertEqual((up[81][0], up[81][2], lex.gravity, lex.pos[:2].tolist()), (-9472 + 2312, -9472, True, [43899, -60969]))
        self.assertEqual({r[0] for r in up[81:]}, {-7160})                            # grounded in the control room, not falling through
        self.assertEqual((w.query_hull(lex)[0][2], w.warnings), (-9472, []))
        down = ride(w, vm, lex, 76, 'LOWER_GARAGE_ELEVATOR')
        self.assertEqual(down[3][0], -7160)
        for n in range(4, 60):
            self.assertEqual(down[n][0], down[n][2] + 2312, n)                          # QSF -39 .. -57, then reset to -37 at 01:10
        self.assertEqual((down[39][2], down[40][2]), (-14592, -9472))
        for n in range(60, 76):
            self.assertEqual(down[n][0], down[n][1] + 2312, n)                          # QSF -> ELV at 02:00: ELV -633 .. -642
        self.assertEqual((down[60], lex.pos[:2].tolist(), down[75][1]), ((-159736, -162048, -9472), [43963.0, -60007.0], -164352))
        # the last step (ELV -646, GRAVITY ON at 02:16): support is scoped to the garage area, so he stays on ELV's floor (F above it)
        end = ride(w, vm, lex, 24)
        self.assertEqual({r[1:] for r in end}, {(-165376, -9472)})
        self.assertEqual(({r[0] for r in end}, lex.gravity, lex.falling, w.phys[lex.area]['name']), ({-165376 + 2312}, True, False, 'ELV'))

    def test_the_ride_starts_by_standing_on_elv_with_gravity_on(self):
        """Lex placed on ELV with gravity on (z = ELV floor + F) stays grounded and enters TAKEMEUP by himself: the same ride, z following
        ELV (the script's GRAVITY OFF at the start leaves him riding), up to the control room and back down to the garage."""
        w, vm, lex = control(-165153 + 2312)
        lex.gravity = True
        up = ride(w, vm, lex, 100)
        self.assertEqual(vm.globals['_elev_frame'], 8)
        self.assertEqual([r[0] for r in up[:5]], [-165153 + 2312] * 5)
        for n in range(5, 21):
            self.assertEqual(up[n][0], up[n][1] + 2312, n)                            # F above ELV at every step
        self.assertEqual(({r[0] for r in up[81:]}, lex.gravity), ({-7160}, True))
        down = ride(w, vm, lex, 100, 'LOWER_GARAGE_ELEVATOR')
        self.assertEqual(({r[0] for r in down[80:]}, down[99][1], lex.falling), ({-165376 + 2312}, -165376, False))


if __name__ == '__main__':
    unittest.main()
