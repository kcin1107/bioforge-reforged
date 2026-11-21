"""Tests for floor items and the Enter key (items.py): selection, the motion chosen for each hand state, the transfer at the motion event,
put-down placement and drawing.  re/.venv/bin/python -I -W ignore -m unittest discover -s re/interp -p 'test_items.py'"""
import hashlib
import os
import sys
import types
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import items as items_mod  # noqa: E402
import keys  # noqa: E402
import vm as vmmod  # noqa: E402
import world as worldmod  # noqa: E402
from eor import Mesh  # noqa: E402

ENTER = 0x1c
BLASTER_POS = (495.0, -29827.0)           # the CHAOS BLASTER (INITGAME), 1,000 units in front of Lex at (495, -28827) facing -y
CAMERA = 'CE24'                           # a room camera that sees that spot
HELD_BLASTER_SHA = '2b13bbfdfad59c803a837b4e010184ca18f93e5a695a4e0ff8447510cd217d6e'     # indexed 320x200 frame of CE24: Lex at STAND frame 0 holding the blaster


def stub(fig='PLAYER'):
    return types.SimpleNamespace(block=types.SimpleNamespace(name='TEST'), cur_fig=fig, cur_item=None, handle=0, waiters=[])


def script(vm, text):
    import tempfile
    with tempfile.NamedTemporaryFile('w', suffix='.scr', delete=False) as t:
        t.write(text)
    try:
        vm.load(t.name)
    finally:
        os.unlink(t.name)


def make(level='CHAOS', lex=(495.0, -28827.0), heading=0.0):
    w = worldmod.World(level, state_dir=worldmod.INITGAME)
    vm = vmmod.VM(w)
    vmmod.load_level(vm, level)
    w.call('stmt', 'CREATEFIGURE', ['LEX', 'PLAYER'], stub())
    fig = w.player()
    fig.pos = np.array([lex[0], lex[1], -5000.0])
    fig.heading = heading
    w.settle(fig)
    return w, vm, fig


def run(w, vm, n):
    for _ in range(n):
        vm.tick_once()
        w.step()


def press_enter(w):
    w.key_down(ENTER)
    w.key_up(ENTER)


def steps_until(w, vm, pred, limit=200):
    """Number of (tick_once, step) frames until pred() holds."""
    for n in range(1, limit + 1):
        run(w, vm, 1)
        if pred():
            return n
    return None


def floor(w, name, item_type, x, y, hand_pos=None):
    item = worldmod.Item(name, item_type)
    item.pos = np.array([x, y, -7280.0])
    item.matrix = np.eye(3)
    w.items[name] = item
    return item


class FloorItemLocals(unittest.TestCase):
    """A level's floor items get the script locals of their ITEM record, as figures do: MEDICAID's charges, a battery's energy, a gun's ~0 and ~1."""
    def test_new_level_items_hold_their_records_locals(self):
        world = worldmod.World('CONTROL', state_dir=worldmod.INITGAME)
        vm = vmmod.VM(world)
        self.assertEqual(vm.objects['MEDICAID'][0], 5)
        self.assertEqual(vm.objects['DANEBAT'][0], 100)
        self.assertEqual(vm.objects['ORIGBIKEBAT'][0], 150)

    def test_a_held_value_is_not_overwritten(self):
        world = worldmod.World('CHAOS', state_dir=worldmod.INITGAME)
        vm = vmmod.VM(world)
        self.assertEqual(vm.objects['BLASTER'][:2], [20, 20])
        vm.objects['BLASTER'][0] = 3
        world.seed_object_locals()
        self.assertEqual(vm.objects['BLASTER'][0], 3)


class LevelItemsKept(unittest.TestCase):
    """A level change writes the old level's objects to its IFF and reads them back on a return (FUN_1148_14a3 -> 1404, 1148:1386); the
    player and what he holds travel (FUN_1088_2da1 -> FUN_1060_0df8)."""
    def setUp(self):
        self.w = worldmod.World('CONTROL', state_dir=worldmod.INITGAME)
        self.vm = vmmod.VM(self.w)
        self.w.player_name = 'LEX'

    def test_a_floor_item_is_back_where_it_was_with_its_locals(self):
        bat = self.w.items['ORIGBIKEBAT']
        bat.pos = bat.pos + (100, 0, 0)
        self.vm.objects['ORIGBIKEBAT'][0] = 20
        self.w.load_objects('TUNROOM')
        self.assertNotIn('ORIGBIKEBAT', self.w.items)
        self.w.load_objects('CONTROL')
        self.assertIs(self.w.items['ORIGBIKEBAT'], bat)
        self.assertEqual(self.vm.objects['ORIGBIKEBAT'][0], 20)
        self.assertEqual(sum(i.name == 'ORIGBIKEBAT' for i in self.w.items.values()), 1)

    def test_what_another_figure_holds_stays_and_the_players_items_travel(self):
        self.w.items['WTALKY'].owner, self.w.items['WTALKY'].slot = 'GRDHANG', 'RTHAND'
        self.w.items['DANEBAT'].owner, self.w.items['DANEBAT'].slot = 'LEX', 'INVENTORY'
        self.w.load_objects('TUNROOM')
        self.assertEqual(sorted(self.w.items), ['DANEBAT'])
        self.assertIsNone(self.w.find_item(None, 'WTALKY'))
        self.w.load_objects('CONTROL')
        self.assertEqual(self.w.items['WTALKY'].owner, 'GRDHANG')
        self.assertEqual(sum(i.name == 'DANEBAT' for i in self.w.items.values()), 1)

    def test_a_save_writes_the_kept_items_into_the_other_levels_file(self):
        import savegame
        import savewrite
        self.w.items['DANEBAT'].owner, self.w.items['DANEBAT'].slot = 'LEX', 'INVENTORY'
        bat = self.w.items['ORIGBIKEBAT']
        bat.pos = bat.pos + (100, 0, 0)
        self.w.load_objects('TUNROOM')
        files = savewrite.build_files('GAME1.IM1', 'TUNROOM', None, True, {}, {}, worldmod.INITGAME, {}, other_levels=self.w.level_item_states())
        recs = {sg_name(d): d for c, d, _ in savegame.LevelIff.parse(files['CONTROL.IFF']).chunks if c == b'ITEM'}
        self.assertNotIn('DANEBAT', recs)                    # carried off: no record left behind
        self.assertEqual(struct_pos(recs['ORIGBIKEBAT']), tuple(int(v) for v in bat.pos))


class LevelFiguresKept(unittest.TestCase):
    """A level keeps its figures when the player leaves it: the killed ones stay gone, the others come back as he left them, their AI
    restarted (FUN_1148_14a3 -> 1404 writes the object list, FUN_1090_135a destroys a killed figure's object)."""
    def setUp(self):
        self.w = worldmod.World('CONTROL', state_dir=worldmod.INITGAME)
        self.vm = vmmod.VM(self.w)
        vmmod.load_level(self.vm, 'CONTROL')
        self.w.player_name = 'LEX'

    def test_a_killed_figure_stays_gone(self):
        self.w.kill_figure(self.w.figures['DANE'])
        self.w.load_objects('TUNROOM')
        self.w.load_objects('CONTROL')
        self.assertNotIn('DANE', self.w.figures)
        self.assertIsNone(self.w.figure('DANE'))
        self.assertIsNotNone(self.w.figure('GRDHALL'))

    def test_a_survivor_comes_back_as_it_was_and_its_ai_restarts(self):
        fig = self.w.figures['GRDHALL']
        fig.pos = fig.pos + (100, 0, 0)
        fig.heading = 90.0
        fig.hold = 2
        self.vm.objects['GRDHALL'][0] = 7
        self.w.load_objects('TUNROOM')
        self.assertNotIn('GRDHALL', self.w.figures)
        self.w.load_objects('CONTROL')
        back = self.w.figures['GRDHALL']
        self.assertIs(back, fig)
        self.assertEqual((back.heading, back.hold, self.vm.objects['GRDHALL'][0]), (90.0, 2, 7))
        self.assertIsNone(back.ai_proc)
        back.hold, back.hidden = 0, False                   # (a camera shows it)
        self.w.start_enabled_ai(back)
        self.assertIsNotNone(back.ai_proc)

    def test_the_first_visit_builds_every_record(self):
        self.assertEqual(set(self.w.fig_defs), set(self.w.figures))
        self.w.load_objects('TUNROOM')
        self.assertIn('CONTROL', self.w.level_figures)
        self.assertEqual(set(self.w.figures), set(self.w.fig_defs))

    def test_a_save_writes_the_kept_figures_into_the_other_levels_file(self):
        import savegame
        import savewrite
        self.w.kill_figure(self.w.figures['DANE'])
        fig = self.w.figures['GRDHALL']
        fig.pos = fig.pos + (100, 0, 0)
        self.w.load_objects('TUNROOM')
        files = savewrite.build_files('GAME1.IM1', 'TUNROOM', None, True, {}, {}, worldmod.INITGAME, {}, other_levels=self.w.level_item_states())
        recs = {sg_name(d): d for c, d, _ in savegame.LevelIff.parse(files['CONTROL.IFF']).chunks if c == b'FIGR'}
        self.assertNotIn('DANE', recs)
        self.assertEqual(struct_pos(recs['GRDHALL'])[:2], (int(fig.pos[0]), int(fig.pos[1])))
        import tempfile
        with tempfile.TemporaryDirectory() as d:                   # a load reads that file: the killed figure stays gone on the return
            for n, data in files.items():
                open(os.path.join(d, n), 'wb').write(data)
            w2 = worldmod.World('TUNROOM', state_dir=d)
            vmmod.VM(w2)
            w2.player_name = 'LEX'
            w2.load_objects('CONTROL')
            self.assertNotIn('DANE', w2.figures)
            self.assertIsNone(w2.figure('DANE'))
            self.assertIn('GRDHALL', w2.figures)

    def test_a_loaded_games_first_visit_gives_the_figure_its_saved_heading_motion_velocity_enemy_and_avoid_list(self):
        """The level reader restores the whole record (FUN_1148_0d46), for a load as for a return: a save made in another level, after leaving
        this one with a turned, moving, fighting figure, hands it back as it was on the first visit after the load."""
        import tempfile
        import savewrite
        fig = self.w.figures['GRDHALL']
        wp = next(iter(self.w.waypoints))
        fig.heading, fig.combat, fig.enemy, fig.avoid = 90.0, True, 'DANE', [(wp, 300)]
        fig.set_motion('ATK_STAND', True, quiet=True)
        fig.vx, fig.vy, fig.vz = 12, -7, 0
        self.w.load_objects('TUNROOM')
        files = savewrite.build_files('GAME1.IM1', 'TUNROOM', None, True, {}, {}, worldmod.INITGAME, {}, other_levels=self.w.level_item_states())
        with tempfile.TemporaryDirectory() as d:
            for n, data in files.items():
                open(os.path.join(d, n), 'wb').write(data)
            w2 = worldmod.World('TUNROOM', state_dir=d)
            vmmod.VM(w2)
            w2.player_name = 'LEX'
            w2.load_objects('CONTROL')
            back = w2.figures['GRDHALL']
            self.assertEqual((back.heading, back.motion, back.combat, (back.vx, back.vy, back.vz), back.enemy, back.avoid),
                             (90.0, 'ATK_STAND', True, (12, -7, 0), 'DANE', [(wp, 300)]))
            self.assertIsNone(w2.figures['DANE'].enemy)


class ElevatorVolumeCarry(unittest.TestCase):
    """LOADLEVEL <level> <volume> <destination> (FUN_10d0_4d46): what the volume touches travels with its offset from the volume centre (x, y)
    and floor (z), the player too, wherever he is; a volume that does not exist ends the caller and nothing loads (error 0x8b)."""
    def setUp(self):
        self.w = worldmod.World('CHAOS', state_dir=worldmod.INITGAME)
        self.vm = vmmod.VM(self.w)
        vmmod.load_level(self.vm, 'CHAOS')
        self.proc = types.SimpleNamespace(block=types.SimpleNamespace(name='TEST'), cur_fig='PLAYER', cur_item=None, handle=0, waiters=[])
        self.w.call('stmt', 'CREATEFIGURE', ['LEX', 'LEX', 'PLAYER'], self.proc)
        self.vol = [o for o in self.w.objs if o['name'].upper() == 'ELH'][0]
        lo, hi = np.minimum(self.vol['pos'], self.vol['pos2']), np.maximum(self.vol['pos'], self.vol['pos2'])
        self.ref = np.array([int((lo[0] + hi[0]) / 2), int((lo[1] + hi[1]) / 2), int(lo[2])], float)

    def test_the_volumes_figures_and_items_and_the_player_arrive_at_their_offsets(self):
        w = self.w
        fido = w.figures['FIDO']
        fido.gravity = False
        fido.pos = self.ref + (100, -200, 700)
        flute = w.items['FLUTE']
        flute.pos, flute.owner = self.ref + (-300, 150, 40), None
        lex = w.player()
        lex.gravity = False
        lex.pos = self.ref + (500, 0, 600)                         # inside here, but the rule does not ask
        lex_rel = lex.pos - self.ref
        w.call('stmt', 'LOADLEVEL', ['CONTROL', 'ELH', 'ELC', '_sfx_5'], self.proc)
        c = w.arrival_point('ELC')
        dest = np.array([c[0][0], c[0][1], c[1]])
        self.assertEqual(w.level, 'CONTROL')
        self.assertEqual(w.items['FLUTE'].pos.tolist(), (dest + (-300, 150, 40)).tolist())
        self.assertEqual(w.items['FLUTE'].vel, [0, 0, 0])
        self.assertIsNot(w.figures.get('FIDO'), None)
        off = w.figures['FIDO'].pos - (dest + (100, -200, 700))       # the PHYS test may have nudged it, in steps of 204 toward the destination
        self.assertEqual((off[2], off[0] % 204, off[1] % 204), (0, 0, 0))
        self.assertLessEqual(abs(off[:2]).max(), 21 * 204)
        off = lex.pos - (dest + lex_rel)
        self.assertEqual((off[2], off[0] % 204, off[1] % 204), (0, 0, 0))
        self.assertLessEqual(abs(off[:2]).max(), 21 * 204)
        self.assertNotIn('GUARD1', w.figures)                           # outside the volume: it stays in CHAOS
        self.assertNotIn('CAYARM', w.items)

    def test_an_unknown_volume_ends_the_caller_and_loads_nothing(self):
        done = []
        self.vm.finish = lambda p: done.append(p)
        self.w.call('stmt', 'LOADLEVEL', ['CONTROL', 'NOVOLUME', 'ELC'], self.proc)
        self.assertEqual((self.w.level, done), ('CHAOS', [self.proc]))


def sg_name(d):
    return (d[33:58].split(b'\0')[0] or d[:9].split(b'\0')[0]).decode('latin1').upper()


def struct_pos(d):
    import struct
    return struct.unpack_from('<3i', d, 9)


class Keys(unittest.TestCase):
    def test_enter_maps_to_pickup_with_any_modifiers_and_in_combat(self):
        for mods in (0, keys.SHIFT, keys.CTRL, keys.ALT):
            for combat in (False, True):
                self.assertEqual(keys.action(0x1c, mods, combat), ('pickup',))
        self.assertEqual((keys.SDL_TO_PC[40], keys.SDL_TO_PC[88]), (0x1c, 0x1c))      # Return, keypad Enter


class OldMeshLayout(unittest.TestCase):
    def test_blaster_has_its_polygons_and_textures(self):
        m = Mesh(os.path.join(items_mod.ITEMS_DIR, 'BLASTER.IFF'))
        self.assertEqual((len(m.verts), len(m.polys), len(m.textures), len(m.anim)), (25, 29, 9, 2))
        self.assertEqual(sum(1 for p in m.polys if p[3] is not None), 22)
        self.assertEqual(m.textures[0][:3], ('BLASTSR', 112, 23))
        self.assertEqual(m.polys[0][:3], (8, 0x90, [15, 18, 17]))
        self.assertTrue(all(v < len(m.verts) for p in m.polys for v in p[2]))
        pipe = Mesh(os.path.join(items_mod.ITEMS_DIR, 'PIPE.IFF'))
        self.assertEqual((len(pipe.verts), len(pipe.polys)), (10, 16))


class FloorItems(unittest.TestCase):
    def test_item_records_without_a_holder_lie_on_the_floor(self):
        w, vm, lex = make()
        self.assertEqual(sorted(k for k, i in w.items.items() if i.owner is None),
                         ['BLASTER', 'CAYARM', 'CAYLOG', 'DANELOG', 'FLUTE', 'FORK', 'LEXLOG', 'MEAT', 'PHOTO'])
        b = w.items['BLASTER']
        self.assertEqual((b.type, b.pos.tolist(), b.matrix.tolist()), ('BLASTER', [495.0, -29827.0, -7280.0], np.eye(3).tolist()))
        self.assertTrue(w.items['PHOTO'].hidden is False and w.items['PHOTO'].type == 'PHOTO')

    def test_handedness_defaults_to_lthand(self):
        w, vm, lex = make()
        self.assertEqual({t: w.item_hand(worldmod.Item('X', t)) for t in ('BLASTER', 'FORK', 'MEAT1', 'CAYARM')},
                         {'BLASTER': 'RTHAND', 'FORK': 'LTHAND', 'MEAT1': 'LTHAND', 'CAYARM': 'RTHAND'})
        self.assertEqual(w.item_hand(worldmod.Item('X', 'NOSUCHITEM')), 'LTHAND')


class InventoryPlacement(unittest.TestCase):
    def setUp(self):
        self.w, self.vm, self.lex = make()
        self.w.items.clear()

    def inventory_item(self, name, item_type):
        item = worldmod.Item(name, item_type, 'LEX', 'INVENTORY')
        self.w.items[name] = item
        return item

    def test_carry_equips_the_declared_hand_or_leaves_the_item_in_inventory(self):
        fork = self.inventory_item('FORK', 'FORK')
        self.assertTrue(self.w.place_item(self.lex, fork, 'CARRY'))
        self.assertEqual((fork.owner, fork.slot, fork.pos), ('LEX', 'LTHAND', None))

        spare = self.inventory_item('SPARE', 'FORK')
        self.assertFalse(self.w.place_item(self.lex, spare, 'CARRY'))
        self.assertEqual((spare.owner, spare.slot, spare.pos), ('LEX', 'INVENTORY', None))

    def test_inventory_and_main_pimm_keys_stow_the_left_hand_before_opening_the_monitor(self):
        item = self.inventory_item('FORK', 'FORK')
        self.w.place_item(self.lex, item, 'CARRY')
        self.w.key_down(0x17)                                      # I
        self.assertEqual((item.owner, item.slot), ('LEX', 'INVENTORY'))
        self.assertIsNone(self.w.monitor)
        self.w.key_up(0x17)
        self.w.place_item(self.lex, item, 'CARRY')
        self.w.key_down(0x19)                                      # P
        self.assertEqual((item.owner, item.slot), ('LEX', 'INVENTORY'))
        self.assertIsNone(self.w.monitor)
        self.w.key_up(0x19)
        self.w.key_down(0x17)
        for _ in range(80):                                        # PIMM's `MOTION LOOK_AT_PIM FREEZE` blocks until the motion has played
            if self.w.monitor is not None:
                break
            self.vm.tick_once()
            self.w.step()
        self.assertIsNotNone(self.w.monitor)

    def test_space_tries_left_hand_combinations_and_standalone_item_use(self):
        fork = self.inventory_item('FORK', 'FORK')
        self.w.place_item(self.lex, fork, 'CARRY')
        self.lex.pos[:2] = (6400.0, -24300.0)                      # CELPAN
        self.w.select_area(self.lex)
        self.assertEqual(self.w.player_use(self.lex), 'CELPAN_FORK_USE')

        script(self.vm, '{ CRYO_BTN_FORK_USE\n}\n')
        self.lex.pos[:2] = (-14000.0, -79300.0)
        self.w.select_area(self.lex)
        self.assertEqual(self.w.player_use(self.lex), 'CRYO_BTN_FORK_USE')

        self.w.items.clear()
        medicaid = self.inventory_item('MEDICAID', 'MEDICAID')
        self.w.place_item(self.lex, medicaid, 'CARRY')
        self.lex.pos[:2] = (0.0, 0.0)
        self.assertEqual(self.w.player_use(self.lex), 'MEDICAID_USE')

    def test_a_motion_started_by_a_use_block_survives_its_tick(self):
        """The key handler has no idle request after Space: CELPAN_USE's MOTION, like TO_TMPL_GRENADE_USE's throw, stays. Swift: the toss in FullRunTests."""
        self.lex.pos[:2] = (6400.0, -24300.0)
        self.w.select_area(self.lex)
        self.w.key_down(0x39)
        self.w.apply_player_input()
        self.assertEqual(self.lex.motion, 'PRY_CELPAN_FAIL')

    def test_ground_drops_a_held_item_to_the_floor(self):
        fork = self.inventory_item('FORK', 'FORK')
        self.w.place_item(self.lex, fork, 'CARRY')
        self.assertTrue(self.w.place_item(self.lex, fork, 'GROUND'))
        self.assertEqual((fork.owner, fork.slot), (None, None))
        self.assertIsNotNone(fork.pos)

    def test_placeitem_coords_and_waypt_take_the_item_off_its_holder(self):
        """10d0:5510-5640: FUN_1138_099b, then x, y, z << 8 or the named object's centre."""
        fork = self.inventory_item('FORK', 'FORK')
        self.w.place_item(self.lex, fork, 'COORDS', 2, -3, 4)
        self.assertEqual((fork.owner, fork.slot), (None, None))
        self.assertEqual([int(v) for v in fork.pos], [512, -768, 1024])
        self.assertIn(fork, self.w.floor_items())
        name = next(o['name'] for o in self.w.objs if o['tag'] == 'WAYP')
        spot = self.w.arrival_point(name.upper())
        self.w.place_item(self.lex, fork, 'WAYPT', name)
        self.assertEqual([float(fork.pos[0]), float(fork.pos[1])], [float(spot[0][0]), float(spot[0][1])])

    def test_armour_is_read_by_the_type_name(self):
        """FUN_1088_2a87 reads it at +0x1ea: a DROGGMIR named DROGG3 has 8, though a DROGG3 block says 100."""
        fig = types.SimpleNamespace(name='DROGG3', type='DROGGMIR')
        self.assertEqual(worldmod.form_prop(fig, 'IMPACT_ARMOR', 0), 8)
        self.assertEqual(worldmod.figure_prop('DROGG3', 'DROGGMIR', 'IMPACT_ARMOR', 0), 100)

    def test_setcurrentitem_hand_selects_and_stows_the_held_item(self):
        fork = self.inventory_item('FORK', 'FORK')
        self.w.place_item(self.lex, fork, 'CARRY')
        proc = stub('LEX')
        self.assertEqual(self.w.call('func', 'SETCURRENTITEM', ['LTHAND'], proc), 1)
        self.assertEqual(proc.cur_item, 'FORK')
        self.w.call('stmt', 'PLACEITEM', ['INVENTORY'], proc)
        self.assertEqual((fork.owner, fork.slot), ('LEX', 'INVENTORY'))


class Selection(unittest.TestCase):
    def setUp(self):
        self.w, self.vm, self.lex = make()
        self.w.items.clear()
        self.lex.pos[:2] = (0.0, 0.0)
        self.lex.heading = 0.0                    # facing -y

    def pick(self):
        c = self.w.pickup_candidate(self.lex)
        return c and c.name

    def test_nearest_item_in_front_wins(self):
        floor(self.w, 'FAR', 'FORK', 0, -1500)
        floor(self.w, 'NEAR', 'FORK', 300, -1000)
        floor(self.w, 'BEHIND', 'FORK', 0, 300)
        self.assertEqual(self.pick(), 'NEAR')

    def test_distances_are_compared_in_256_unit_buckets(self):
        floor(self.w, 'FIRST', 'FORK', 0, -1678)                       # 1678 >> 8 = 6
        floor(self.w, 'SECOND', 'FORK', 0, -1554)                      # nearer, but not below 6 << 8 = 1536: the first stays
        self.assertEqual(self.pick(), 'FIRST')
        self.w.items['SECOND'].pos[1] = -1500                          # below 1536: it replaces the first
        self.assertEqual(self.pick(), 'SECOND')

    def test_earlier_item_wins_a_tie(self):
        floor(self.w, 'FIRST', 'FORK', 0, -1000)
        floor(self.w, 'SECOND', 'FORK', 0, -1000)
        self.assertEqual(self.pick(), 'FIRST')

    def test_reach_is_0x900(self):
        floor(self.w, 'A', 'FORK', 0, -2303)
        self.assertEqual(self.pick(), 'A')
        self.w.items['A'].pos[1] = -2304
        self.assertIsNone(self.pick())

    def test_cone_is_sixty_degrees(self):
        for deg, found in ((59, True), (61, False), (-59, True), (-61, False), (180, False)):
            self.w.items.clear()
            a = np.radians(deg)
            floor(self.w, 'A', 'FORK', -1000 * np.sin(a), -1000 * np.cos(a))
            self.assertEqual(self.pick() == 'A', found, deg)

    def test_nothing_in_range_finds_none(self):
        floor(self.w, 'A', 'FORK', 0, -5000)
        self.assertIsNone(self.pick())

    def test_held_and_inventory_items_are_not_candidates(self):
        floor(self.w, 'HELD', 'FORK', 0, -500).owner = 'LEX'
        self.w.items['HELD'].slot = 'LTHAND'
        floor(self.w, 'INV', 'FORK', 0, -600).owner = 'LEX'
        self.w.items['INV'].slot = 'INVENTORY'
        self.assertIsNone(self.pick())

    def test_a_corpse_widens_the_search(self):
        floor(self.w, 'FAR', 'FORK', 3500, 0)                          # 3,500 to the side: out of reach and out of the cone
        self.assertIsNone(self.pick())
        bot = self.w.figure('FIRSTBOT')
        bot.pos, bot.hidden = np.array([1000.0, 0.0, -5000.0]), False  # (the FIGR record has it hidden; a hidden figure is no corpse)
        self.vm.objects['FIRSTBOT'][:6] = [0, 0, 0, 0, 0, 50]          # hit points 0 of a maximum 50
        self.assertEqual(self.pick(), 'FAR')                           # reach 0x1000, any direction
        self.vm.objects['FIRSTBOT'][0] = 10
        self.assertIsNone(self.pick())


class WhichMotion(unittest.TestCase):
    """FUN_1088_5729 for every hand state; LANDPAD has no LEX_PUT_DOWN_* script gate, so the motion starts at once."""
    def setUp(self):
        self.w, self.vm, self.lex = make('LANDPAD', lex=(0.0, 0.0))
        self.w.items.clear()

    def motion(self, left=None, right=None, near=None):
        self.w.items.clear()
        self.lex.set_motion('STAND', True)
        for hand, item_type in (('LTHAND', left), ('RTHAND', right)):
            if item_type:
                it = floor(self.w, 'HELD_' + hand, item_type, 0, 0)
                it.owner, it.slot, it.pos = 'LEX', hand, None
        if near:
            floor(self.w, 'NEAR', near, 0, -1000)
        self.w.pick_targets.clear()
        self.w.player_pickup(self.lex)
        return self.lex.motion if self.lex.motion != 'STAND' else None

    def test_motion_for_each_hand_state(self):
        m = self.motion
        self.assertIsNone(m())                                         # empty hands, nothing near
        self.assertEqual(m(near='BLASTER'), 'PICK_UP_RTHAND')          # handedness rthand
        self.assertEqual(m(near='FORK'), 'PICK_UP_LTHAND')
        self.assertEqual(m(right='BLASTER'), 'PUT_DOWN_RTHAND')        # left empty, nothing near: put the right item down
        self.assertEqual(m(right='BLASTER', near='FORK'), 'PICK_UP_LTHAND')
        self.assertEqual(m(right='BLASTER', near='CAYARM'), 'PUT_DOWN_RTHAND')   # a second rthand item: no free hand
        self.assertEqual(m(left='FORK'), 'PUT_DOWN_LTHAND')
        self.assertEqual(m(left='FORK', near='BLASTER'), 'PICK_UP_RTHAND')
        self.assertEqual(m(left='FORK', near='MEAT1'), 'PUT_DOWN_LTHAND')        # lthand item but the left hand is full
        self.assertEqual(m(left='FORK', right='BLASTER'), 'PUT_DOWN_LTHAND')
        self.assertEqual(m(left='FORK', right='BLASTER', near='BLASTER'), 'PUT_DOWN_LTHAND')

    def test_pick_up_stores_its_target_only_when_the_left_hand_is_empty(self):
        self.motion(near='BLASTER')
        self.assertEqual(self.w.pick_targets, {'LEX': 'NEAR'})
        self.motion(left='FORK', near='BLASTER')
        self.assertEqual(self.w.pick_targets, {})

    def test_same_motion_is_not_restarted(self):
        floor(self.w, 'NEAR', 'BLASTER', 0, -1000)
        self.w.player_pickup(self.lex)
        run(self.w, self.vm, 3)
        idx = self.lex.idx
        self.assertFalse(self.w.player_pickup(self.lex))
        self.assertEqual(self.lex.idx, idx)


class Transfer(unittest.TestCase):
    def test_lex_has_the_motions_and_events(self):
        ev = items_mod.figure_events('LEX', items_mod.BODY_DIR)
        self.assertEqual([ev[n] for n in ('PICK_UP_LTHAND', 'PICK_UP_RTHAND', 'PUT_DOWN_LTHAND', 'PUT_DOWN_RTHAND')],
                         [[(16, 0xef)], [(15, 0xef)], [(12, 0xf4)], [(16, 0xf3)]])
        a = worldmod.Assets('LEX')
        self.assertEqual([len(a.motions[n]) for n in ('PICK_UP_LTHAND', 'PICK_UP_RTHAND', 'PUT_DOWN_LTHAND', 'PUT_DOWN_RTHAND')],
                         [32, 29, 21, 29])

    def test_pick_up_blaster_moves_it_into_the_right_hand_at_the_event(self):
        w, vm, lex = make()
        b = w.items['BLASTER']
        press_enter(w)
        n = steps_until(w, vm, lambda: b.owner is not None)
        self.assertEqual(n, 21)                                        # the event after frame byte 14 fires while frame 14 shows, 1.5 ticks a frame (MY_SPEED 384 x 2)
        self.assertEqual((lex.motion, lex.idx, b.owner, b.slot, b.pos), ('PICK_UP_RTHAND', 14, 'LEX', 'RTHAND', None))
        self.assertTrue(w.is_carrying(lex, 'RTHAND', 'BLASTER'))
        self.assertFalse(w.is_carrying(lex, 'LTHAND'))
        run(w, vm, 20)
        self.assertEqual(lex.motion, 'PICK_UP_RTHAND')                 # 29 frames = 44 ticks in all
        run(w, vm, 40)
        self.assertEqual((lex.motion, lex.loop), ('STAND', True))      # the one-shot ended and control returned

    def test_pick_up_fork_uses_the_left_hand_and_its_event_frame(self):
        w, vm, lex = make(lex=(-2466.0, -6717.0))                      # the FORK lies 1,000 units ahead
        f = w.items['FORK']
        press_enter(w)
        self.assertEqual(steps_until(w, vm, lambda: f.owner is not None), 23)     # 0xef after frame byte 15: while frame 15 shows
        self.assertEqual((lex.motion, lex.idx, f.slot), ('PICK_UP_LTHAND', 15, 'LTHAND'))

    def test_the_grab_fails_when_the_target_is_out_of_reach_by_then(self):
        w, vm, lex = make()
        press_enter(w)
        run(w, vm, 3)
        lex.pos[1] += 5000                                             # carried away during the motion
        run(w, vm, 40)
        self.assertIsNone(w.items['BLASTER'].owner)

    def test_the_shoot_key_now_runs_the_blaster_branch(self):
        w, vm, lex = make()
        press_enter(w)
        run(w, vm, 70)
        w.key_down(0x4c)
        w.key_up(0x4c)
        run(w, vm, 3)
        self.assertEqual((lex.motion, lex.loop), ('ATK_SHOOT', False))

    def test_the_game_s_own_take_block_runs_at_the_transfer(self):
        w, vm, lex = make()
        self.assertIn('LEX_BLASTER_TAKE', vm.blocks)                   # CHAOS names the blaster with a subtitle
        press_enter(w)
        n = steps_until(w, vm, lambda: w.items['BLASTER'].owner is not None)
        self.assertEqual([(t, a, d) for t, a, d in w.key_log if a == 'item'], [(vm.tick, 'item', 'LEX_BLASTER_TAKE')])
        self.assertEqual(n, 21)
        self.assertEqual([e[0] for e in w.subtitle_log], [vm.tick])

    def test_take_block_gets_the_item_as_current_item(self):
        w, vm, lex = make()
        script(vm, '{ LEX_ZZZ_TAKE\n\t_timetest = CURITEM.~2\n}\n')
        floor(w, 'ZZZ', 'FORK', 495.0, -29827.0)
        vm.objects['ZZZ'][2] = 42
        vm.globals['_timetest'] = 0
        w.items['BLASTER'].owner = 'ELSE'                              # only the new item lies in front
        press_enter(w)
        run(w, vm, 22)
        self.assertEqual(vm.globals['_timetest'], 0)                   # the left hand's event fires while frame 15 shows (tick 23)
        run(w, vm, 1)
        self.assertEqual(vm.globals['_timetest'], 42)


class PutDown(unittest.TestCase):
    def holding(self, level='CHAOS', item='BLASTER', slot='RTHAND'):
        w, vm, lex = make(level, lex=(5000.0, -20000.0))
        it = w.items[item]
        it.owner, it.slot, it.pos = 'LEX', slot, None
        return w, vm, lex, it

    def test_put_down_lands_in_front_of_lex_flat_on_the_floor(self):
        w, vm, lex, b = self.holding()
        start = lex.pos.copy()
        press_enter(w)
        n = steps_until(w, vm, lambda: b.owner is None)
        self.assertEqual(n, 23)                                        # LEX_PUT_DOWN_RTHAND (the CHAOS script gate) starts the motion at once; 0xf3 while frame 15 shows
        self.assertIsNone(b.slot)
        run(w, vm, 30)
        self.assertEqual((lex.motion, lex.loop), ('STAND', True))      # the script's motion ended and Lex stands up again
        self.assertFalse(w.is_carrying(lex, 'RTHAND', 'BLASTER'))
        self.assertTrue(np.allclose(b.matrix, [[0, 0, -1], [0, 1, 0], [1, 0, 0]]))        # ON_GROUND (0,90,0): Y by 90 degrees
        self.assertLess(b.pos[1], start[1] - 1000)                     # in front of where Lex stood (heading 0 = -y)
        self.assertAlmostEqual(b.pos[0], start[0], delta=400)
        low = min(float((np.array(v, float) @ b.matrix)[2]) for v in items_mod.item_mesh('BLASTER').verts)
        self.assertAlmostEqual(b.pos[2] + low, w.support(lex, *w.hull(lex)))        # its lowest point rests on the floor under Lex

    def test_put_down_without_a_gate_script_and_the_left_hand(self):
        w, vm, lex, f = self.holding('LANDPAD', 'BLASTERM3B', 'RTHAND')
        f.type = 'FORK'
        f.slot = 'LTHAND'
        press_enter(w)
        self.assertEqual(steps_until(w, vm, lambda: f.owner is None), 17)      # PUT_DOWN_LTHAND: 0xf4 after frame byte 11, while frame 11 shows
        self.assertTrue(np.allclose(f.matrix, [[1, 0, 0], [0, 0, 1], [0, -1, 0]]))        # ON_GROUND (90I,0,0): X by 90 degrees

    def test_both_hands_full_put_the_left_item_down(self):
        w, vm, lex, b = self.holding('LANDPAD', 'BLASTERM3B', 'RTHAND')
        f = floor(w, 'F', 'FORK', 0, 0)
        f.owner, f.slot, f.pos = 'LEX', 'LTHAND', None
        press_enter(w)
        steps_until(w, vm, lambda: f.owner is None)
        self.assertEqual((f.owner, b.owner, b.slot), (None, 'LEX', 'RTHAND'))

    def test_drop_script_block_runs_after_the_item_left_the_hand(self):
        w, vm, lex, b = self.holding()
        script(vm, '{ LEX_BLASTER_DROP\n\t_timetest = 7\n}\n')
        vm.globals['_timetest'] = 0
        press_enter(w)
        run(w, vm, 22)
        self.assertEqual(vm.globals['_timetest'], 0)
        run(w, vm, 1)
        self.assertEqual((vm.globals['_timetest'], b.owner), (7, None))


class Drawing(unittest.TestCase):
    def frame(self, held):
        w, vm, lex = make()
        if held:
            b = w.items['BLASTER']
            b.owner, b.slot, b.pos = 'LEX', 'RTHAND', None
        w.script_auto = False
        w.set_camera(CAMERA, 'test')
        return w.render(indexed=True)

    def test_floor_and_held_blaster_are_drawn_differently_from_nothing(self):
        w, vm, lex = make()
        w.script_auto = False
        w.set_camera(CAMERA, 'test')
        with_floor = w.render(indexed=True)
        del w.items['BLASTER']
        without = w.render(indexed=True)
        self.assertFalse(np.array_equal(with_floor, without))
        held = self.frame(True)
        self.assertFalse(np.array_equal(held, without) or np.array_equal(held, with_floor))

    def test_held_blaster_frame_hash(self):
        self.assertEqual(hashlib.sha256(self.frame(True).tobytes()).hexdigest(), HELD_BLASTER_SHA)

    def test_held_item_follows_the_hand(self):
        w, vm, lex = make()
        b = w.items['BLASTER']
        b.owner, b.slot, b.pos = 'LEX', 'RTHAND', None
        stand = w.hand_pose(lex, b)
        lex.set_motion('ATK_SHOOT', False)
        lex.idx = 5
        shoot = w.hand_pose(lex, b)
        self.assertGreater(np.linalg.norm(stand[0] - shoot[0]), 1000)
        self.assertAlmostEqual(abs(shoot[1][1][1]), 1.0, delta=0.05)    # in the shoot pose the barrel axis lies along the facing direction (y)
        self.assertIsNone(w.hand_pose(lex, worldmod.Item('X', 'FORK', 'LEX', 'NOSUCHHAND')))

    def test_hidden_and_inventory_items_are_not_drawn(self):
        w, vm, lex = make()
        w.script_auto = False
        w.set_camera(CAMERA, 'test')
        base = w.render(indexed=True)
        b = w.items['BLASTER']
        b.owner, b.slot, b.pos = 'LEX', 'INVENTORY', None
        no_item = w.render(indexed=True)
        del w.items['BLASTER']
        self.assertTrue(np.array_equal(no_item, w.render(indexed=True)))
        self.assertFalse(np.array_equal(base, no_item))


class SaveRoundTrip(unittest.TestCase):
    def saved(self, w):
        import savegame
        import tempfile
        w.saves_dir = tempfile.mkdtemp()
        out = tempfile.mkdtemp()
        savegame.Im1.unpack(open(w.save_native(1), 'rb').read(), out)
        return worldmod.World.from_native_state(out)

    def test_picked_up_and_put_down_items_survive_a_save(self):
        w, vm = worldmod.World.from_native_state()                  # the shipped GAMEDAT: its CHAOS file has Lex's PLAY record
        lex = w.player()
        lex.pos = np.array([495.0, -28827.0, lex.pos[2]])
        lex.heading = 0.0
        lex.hold = 0                                                # the shipped save's Lex has AI off (+0x229 = 1), which keeps the keys out
        press_enter(w)
        run(w, vm, 40)
        self.assertEqual((w.items['BLASTER'].owner, w.items['BLASTER'].slot), ('LEX', 'RTHAND'))
        w2, vm2 = self.saved(w)
        b = w2.items['BLASTER']
        self.assertEqual((b.owner, b.slot, b.pos), ('LEX', 'RTHAND', None))
        self.assertTrue(w2.is_carrying(w2.player(), 'RTHAND', 'BLASTER'))
        self.assertTrue(w2.items['FORK'].owner is None and w2.items['FORK'].pos is not None)       # untouched records are unchanged
        vm2.globals['_bars2_on'] = 0                                 # Lex stands at cell 2's live bars (trigger DR_ZAP2)
        press_enter(w2)                                              # put it down again
        run(w2, vm2, 40)
        dropped = w2.items['BLASTER']
        self.assertIsNone(dropped.owner)
        w3, _ = self.saved(w2)
        again = w3.items['BLASTER']
        self.assertEqual((again.owner, again.slot), (None, None))
        self.assertTrue(np.allclose(again.pos, dropped.pos, atol=0.5) and np.allclose(again.matrix, dropped.matrix, atol=1 / 256))

    def test_untouched_items_keep_their_record_bytes(self):
        import savewrite
        import savegame
        recs = [raw for cid, raw, _ in savegame.LevelIff.parse(open(os.path.join(worldmod.INITGAME, 'CHAOS.IFF'), 'rb').read()).chunks
                if cid == b'ITEM']
        for raw in recs:
            floor_state = (None, None, [float(v) for v in np.frombuffer(raw[9:21], '<i4')],
                           (np.frombuffer(raw[147:183], '<i4').reshape(3, 3) / 256).tolist())
            self.assertEqual(savewrite.patch_item(raw, floor_state, {}), raw)
        self.assertEqual(savewrite.patch_item(recs[0], ('LEX', 'RTHAND', None, None), {}), recs[0])        # unknown holder: left alone


class Numbers(unittest.TestCase):
    def test_property_numbers_and_units(self):
        self.assertEqual(items_mod.parse_numbers(['180I', '90J', '0K', '8LENGTH', '0X', '20Y', '-3Z']),
                         {'I': 180, 'J': 90, 'K': 0, 'LENGTH': 8, 'X': 0, 'Y': 20, 'Z': -3})
        self.assertEqual(items_mod.parse_numbers([0, 90, 0]), {'I': 0, 'J': 90, 'K': 0})
        self.assertEqual([items_mod.attach_units(v) for v in (0, 1, 7, 8, 20, -3)], [0, 20, 143, 163, 409, -61])


if __name__ == '__main__':
    unittest.main()
