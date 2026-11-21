"""Prototype save/load through the options dialog: .im1 written by savewrite.py, read back by savegame.py + from_native_state."""
import os
import struct
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), 'formats'))
import cam  # noqa: E402
import savegame  # noqa: E402
import vm as vmmod  # noqa: E402
import world as worldmod  # noqa: E402
from options import SAVE, LOAD  # noqa: E402

NAMES = sorted(['MISC.DAT', 'SCRIPT.DAT', 'LISTS.FLX', 'VARS.DEF', 'SOUNDS.DEF'] +
               [l + '.IFF' for l in savegame.LEVELS])


def make(state_dir, level='CHAOS', camera=None):
    w = worldmod.World(level, camera=camera, state_dir=state_dir)
    vm = vmmod.VM(w)
    vmmod.load_level(vm, level)
    w.vm = vm
    return w, vm


class SaveTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def saved(self, state_dir, slot=3):
        w, vm = make(state_dir)
        w.saves_dir = self.tmp.name
        w.set_camera('CE11', 'test')
        key = next(k for k in vm.globals if isinstance(vm.globals[k], int) and k.upper() in dict(savegame.default_vars()))
        vm.globals[key] = 4321
        return w, vm, key, w.save_native(slot)

    def check_container(self, path):
        ents, thumb, _ = savegame.Im1.entries(open(path, 'rb').read())
        self.assertEqual([e[0] for e in ents], NAMES)
        w, h, hx, hy, px, mask = cam.decode_frame(thumb, 0)
        self.assertEqual((w, h, hx, hy, sum(mask)), (320, 200, 0, 0, 64000))
        self.assertTrue(all(128 <= v < 160 for v in px))

    def test_save_from_native_state_and_load_it_back(self):
        w, vm, key, path = self.saved(worldmod.GAMEDAT)
        self.assertEqual(os.path.basename(path), 'GAME3.IM1')
        self.check_container(path)
        w2, vm2 = w.load_native(3)
        self.assertEqual((w2.level, w2.current_camera(), vm2.globals[key]), ('CHAOS', 'CE11', 4321))
        self.assertIs(w.pending_load[0], w2)
        st = savegame.SaveState.load(os.path.join(self.tmp.name, 'GAME3.d'))
        self.assertEqual((st.misc.save_name, st.misc.level, st.misc.camera), ('GAME3.IM1', 'CHAOS.IFF', 'CE11'))
        shipped = savegame.SaveState.load(worldmod.GAMEDAT).script
        self.assertEqual(*([(s.index, s.vtable, bytes(s.b)) for s in sd.slots if s.index < 6] for sd in (st.script, shipped)))
        live = lambda m: sorted(p.block.name for p in m.procs.values() if not p.done and p.block.kind != 'native')   # noqa: E731
        self.assertEqual(live(vm2), live(vm))             # the world's processes are written and resumed

    def test_save_from_a_new_game_state_writes_system_tasks_only(self):
        w, vm, key, path = self.saved(worldmod.INITGAME)
        self.check_container(path)
        w2, vm2 = w.load_native(3)
        self.assertEqual((w2.level, w2.current_camera(), vm2.globals[key]), ('CHAOS', 'CE11', 4321))
        st = savegame.SaveState.load(os.path.join(self.tmp.name, 'GAME3.d'))
        self.assertEqual([s.index for s in st.script.slots], list(range(6)))
        self.assertEqual(st.misc.serials[6:], [0] * 94)
        self.assertEqual(st.vars.items[0][0], savegame.default_vars()[0][0])

    def test_figure_positions_are_written(self):
        w, vm = make(worldmod.INITGAME)
        w.saves_dir = self.tmp.name
        name = next(iter(w.fig_defs))
        fig = w.figure(name)
        fig.pos = fig.pos + [100, 0, 0]
        w.save_native(1)
        out = os.path.join(self.tmp.name, 'GAME1.d')
        savegame.Im1.unpack(open(os.path.join(self.tmp.name, 'GAME1.IM1'), 'rb').read(), out)
        recs = [r for t, n, r in savegame.SaveState.load(out).level_objects() if t == 'FIGR' and savegame.cstr(r[33:42]) == name]
        self.assertEqual(struct.unpack_from('<3i', recs[0], 9), tuple(int(round(v)) for v in fig.pos))

    def test_the_player_and_figure_state_come_back(self):
        """A new game creates Lex by script, so its level file has no PLAY record: the writer appends one (from the shipped GAMEDAT's), and every
        figure record carries the live state resume.py reads back: position, heading, motion, flags, object locals, enemy, AI hold."""
        w, vm = make(worldmod.INITGAME)
        w.saves_dir = self.tmp.name
        import types
        w.call('stmt', 'CREATEFIGURE', ['LEX', 'LEX', 'PLAYER'], types.SimpleNamespace(block=types.SimpleNamespace(name='TEST'), cur_fig=None, cur_item=None, owner='level'))
        lex = w.figures['LEX']
        w.player_name = 'LEX'
        w.set_pos(lex, [-10944.0, -7281.0, -5754.0], raw=True)
        lex.heading = 30.0
        vm.objects[w.object_key('LEX')] = [77, 0, 0, 0, 0, 0, 0, 0, 0, 0]
        name = next(iter(w.fig_defs))
        fig = w.figure(name)
        fig.heading, fig.combat, fig.hold, fig.enemy = -45.0, True, 1, 'PLAYER'
        fig.set_motion('ATK_STAND', True, quiet=True)
        vm.objects[w.object_key(name)] = [33, 1, 2, 3, 4, 5, 6, 7, 8, 9]
        w.save_native(1)
        out = os.path.join(self.tmp.name, 'GAME1.d')
        savegame.Im1.unpack(open(os.path.join(self.tmp.name, 'GAME1.IM1'), 'rb').read(), out)
        w2, vm2 = worldmod.World.from_native_state(out)
        lex2, fig2 = w2.player(), w2.figures[name]
        self.assertEqual((w2.player_name, [round(v) for v in lex2.pos[:2]], round(lex2.heading), vm2.objects[w2.object_key('LEX')][0]),
                         ('LEX', [-10944, -7281], 30, 77))
        self.assertEqual((round(fig2.heading), fig2.combat, fig2.hold, fig2.enemy, fig2.motion, vm2.objects[w2.object_key(name)]),
                         (-45, True, 1, 'PLAYER', 'ATK_STAND', [33, 1, 2, 3, 4, 5, 6, 7, 8, 9]))
        self.assertEqual([round(v) for v in fig2.pos], [round(v) for v in fig.pos])

    def test_hard_stays_hard_after_a_load(self):
        """The difficulty is the _difficulty_level variable, which a save keeps; a load copies it back to [a36e] (FUN_1148_0490)."""
        w, vm = make(worldmod.GAMEDAT)
        w.saves_dir = self.tmp.name
        vm.globals['_difficulty_level'] = 2
        w.save_native(2)
        w2, vm2 = w.load_native(2)
        self.assertEqual(vm2.globals['_difficulty_level'], 2)

    def test_the_item_list_order_comes_back(self):
        """The writer puts the items in the world's order and the reader makes them in record order (FUN_1148_0d46), so a floor item that
        came after Lex's items (a level entered with them) still comes after them, and the inventory lists it last once picked up."""
        w, vm = worldmod.World.from_native_state(worldmod.GAMEDAT)
        w.saves_dir = self.tmp.name
        carried = [k for k, i in w.items.items() if i.owner == 'LEX']
        w.items = {k: w.items[k] for k in carried + [k for k in w.items if k not in carried]}      # as after a level change
        w.save_native(1)
        out = os.path.join(self.tmp.name, 'GAME1.d')
        savegame.Im1.unpack(open(os.path.join(self.tmp.name, 'GAME1.IM1'), 'rb').read(), out)
        w2, vm2 = worldmod.World.from_native_state(out)
        self.assertEqual(list(w2.items), list(w.items))
        fork = w2.items['FORK']
        fork.owner, fork.slot, fork.pos = 'LEX', 'INVENTORY', None
        self.assertEqual([i.key for i in w2.inventory_items()], carried + ['FORK'])

    def test_a_running_continue_motion_restarts_from_frame_0(self):
        """MOTION ... CONTINUE keeps a motion task, which the original's load restarts from the first frame (FUN_1088_4d67); the save
        writes it as a 0x46f5 task linked from the figure record (+0x13d), and the phase is not kept."""
        w, vm = make(worldmod.INITGAME)
        w.saves_dir = self.tmp.name
        name = next(iter(w.fig_defs))
        fig = w.figure(name)
        motion = next(m for m in fig.assets.motions if not worldmod.motion_loops(fig.assets, m) and len(fig.assets.motions[m]) > 4)
        w.cmd_motion(fig, motion, ['CONTINUE'])
        fig.idx = 3
        w.save_native(1)
        out = os.path.join(self.tmp.name, 'GAME1.d')
        savegame.Im1.unpack(open(os.path.join(self.tmp.name, 'GAME1.IM1'), 'rb').read(), out)
        st = savegame.SaveState.load(out)
        rec = next(r for t, n, r in st.level_objects() if t == 'FIGR' and savegame.cstr(r[33:58]) == name)
        slot = next(s for s in st.script.slots if s.vtable == 0x46f5)
        import level
        self.assertEqual(level.ObjRec('FIGR', rec).motion_task, slot.index)        # the record links the task
        self.assertEqual(bytes(slot.a[0x32:0x4b]).split(b'\0')[0].decode().upper(), motion)
        w2, vm2 = worldmod.World.from_native_state(out)
        fig2 = w2.figures[name]
        self.assertEqual((fig2.motion, fig2.loop, fig2.idx, fig2.task_name, fig2.unwaited), (motion, False, 0, motion, True))

    def test_a_missile_in_flight_comes_back(self):
        """The original saves a missile task (vtable 0x47a9; FUN_10e0_135a writes the owner's and the item's ids after the task lists,
        FUN_10e0_12b7 reads them back) and its item as an ITEM record: the shot flies on after a load, under the same handle, from the
        same position, orientation, velocity, range and spin, and the two worlds move it the same way."""
        import scenarios
        w, vm = make(worldmod.INITGAME)
        w.saves_dir = self.tmp.name
        fig = w.figure('CAYNAN')                                    # above Caynan in his cell: a slow shot stays clear of the walls
        rows = [[0, 0, 256], [181, 181, 0], [181, -181, 0]]
        m = w.spawn_missile('LASER', [int(c) for c in fig.pos + (0, 0, 1500)], rows, 4 * 2048, 30000, (0, 0, 7), owner=fig)
        scenarios.tick(w, vm, 2)
        self.assertFalse(m.dead)
        w.save_native(1)
        out = os.path.join(self.tmp.name, 'GAME1.d')
        savegame.Im1.unpack(open(os.path.join(self.tmp.name, 'GAME1.IM1'), 'rb').read(), out)
        st = savegame.SaveState.load(out)
        slot = next(s for s in st.script.slots if s.vtable == 0x47a9)
        self.assertEqual((slot.serial, len(slot.a), slot.type), (m.handle, 0x56, 0x10c))
        w2, vm2 = worldmod.World.from_native_state(out)
        m2 = next(i for i in w2.items.values() if getattr(i, 'missile', False))
        self.assertEqual((m2.key, m2.type, m2.handle, m2.dist, tuple(m2.spin), m2.owner_fig.name), (m.key, 'LASER', m.handle, m.dist, (0, 0, 7), 'CAYNAN'))
        self.assertEqual(([int(c) for c in m2.pos], m2.rows, [int(v) for v in m2.vel]), ([int(c) for c in m.pos], m.rows, [int(v) for v in m.vel]))
        self.assertIn(m2.handle, vm2.procs)
        scenarios.tick(w, vm, 3)
        scenarios.tick(w2, vm2, 3)
        self.assertFalse(m.dead)
        self.assertEqual(([int(c) for c in m2.pos], m2.dist, m2.dead), ([int(c) for c in m.pos], m.dist, False))

    def test_a_process_waiting_on_a_ramp_waits_again(self):
        """SUSPENDWHILE MODIFYVAREVERYNTH: the waiter's list 1 names the ramp task, and a load links them again, so the CHAOS drip goes on
        in step with the unsaved game instead of running past its wait."""
        import scenarios
        w, vm = make(worldmod.INITGAME)
        w.saves_dir = self.tmp.name
        w.set_camera('BLK1', 'test')                            # the drip's LINKMETOCAMERAS: elsewhere it is suspended
        vm.spawn('BLOCK_DRIP')
        drip = lambda v: next(p for p in v.procs.values() if p.block.name.upper() == 'BLOCK_DRIP')
        scenarios.tick(w, vm, 31)                               # WAIT 30, then the first ramp of _dp1_frame
        self.assertEqual(drip(vm).wait_on.block.name, 'MODIFYVAREVERYNTH')
        w.save_native(1)
        out = os.path.join(self.tmp.name, 'GAME1.d')
        savegame.Im1.unpack(open(os.path.join(self.tmp.name, 'GAME1.IM1'), 'rb').read(), out)
        w2, vm2 = worldmod.World.from_native_state(out)
        self.assertIs(drip(vm2).wait_on, vm2.procs.get(drip(vm).wait_on.handle))
        for _ in range(120):
            scenarios.tick(w, vm, 1)
            scenarios.tick(w2, vm2, 1)
            self.assertEqual((drip(vm2).pc, vm2.globals.get('_dp1_frame'), vm2.globals.get('_dp2_frame')),
                             (drip(vm).pc, vm.globals.get('_dp1_frame'), vm.globals.get('_dp2_frame')))

    def test_dialog_confirmation_saves_and_loads(self):
        w, vm = make(worldmod.INITGAME)
        w.saves_dir = self.tmp.name
        w.options = worldmod.options_mod.Options()
        w.options.open(SAVE)
        w.option_activate('SE5X')
        w.option_activate('LOKX')
        self.assertEqual(w.option_activate('YESX'), 'save:5')
        self.assertTrue(os.path.exists(os.path.join(self.tmp.name, 'GAME5.IM1')))
        w.options.open(LOAD)
        w.option_activate('SE5X')
        w.option_activate('LOKX')
        self.assertEqual(w.option_activate('YESX'), 'load:5')
        self.assertEqual(w.pending_load[0].level, 'CHAOS')
        w.options.open(LOAD)
        w.option_activate('SE6X')
        w.option_activate('LOKX')
        w.pending_load = None
        w.option_activate('YESX')
        self.assertIsNone(w.pending_load)
        self.assertTrue(any('no save in slot 6' in x for x in w.warnings))


if __name__ == '__main__':
    unittest.main()
