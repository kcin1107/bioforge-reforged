"""Tests for the engine binding (world.py): re/.venv/bin/python -I -m unittest discover -s re/interp -p 'test_*.py' -v"""
import glob
import math
import os
import sys
import tempfile
import types
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np  # noqa: E402
import vm as vmmod  # noqa: E402
import world as worldmod  # noqa: E402

WORLD = None


def make_world():
    global WORLD
    if WORLD is None:
        WORLD = worldmod.World('LANDPAD')           # object/asset loading is shared; figures are reset per test
    WORLD.figures.clear()
    WORLD.items.clear()
    WORLD.player_name = None
    WORLD.camera = WORLD.default_camera = None
    WORLD.follow = worldmod.FOLLOW_DEFAULT
    WORLD.log.clear()
    WORLD.auto_camera, WORLD.script_auto, WORLD.candidate, WORLD.selected = True, True, None, False
    WORLD.disabled.clear()
    WORLD.loaded_cam = None
    WORLD.events.clear()
    WORLD.follow = worldmod.FOLLOW_DEFAULT
    WORLD.camera_changes.clear()
    WORLD.warnings.clear()
    WORLD.set_player_input()
    return WORLD


def ticks_for(fig, frames, world=None):
    """VM ticks that play `frames` frames of the figure's current motion (FUN_1098_0088's duration, FUN_1088_1854)."""
    duration = world.motion_duration(fig) if world is not None else fig.frame_duration()
    return math.ceil(frames * duration / worldmod.CLOCK_PER_TICK)


def proc(fig='PLAYER'):
    return types.SimpleNamespace(block=types.SimpleNamespace(name='TEST'), cur_fig=fig, cur_item=None, handle=0, waiters=[], cameras=[])


def cmd(w, name, *args, fig='PLAYER'):
    return w.call('stmt', name, list(args), proc(fig))


def run(w, ticks):
    for _ in range(ticks):
        w.step()


class ViewingCams(unittest.TestCase):
    def test_figr_camera_lists(self):
        got = {}
        for lvl in ('CHAOS', 'LANDPAD'):
            for o in worldmod.load_level_objs(os.path.join(worldmod.GAMEDAT, lvl + '.IFF')):
                if o['tag'] == 'FIGR':
                    inst = o['raw'][33:42].split(b'\0')[0].decode()
                    got[(lvl, inst)] = worldmod.figr_view_cams(o['raw'])
        self.assertEqual(got[('CHAOS', 'USE_BOT')], ['CE41', 'CE42', 'CE43', 'CE32', 'CE33'])
        self.assertEqual(got[('CHAOS', 'HALMECHO')], ['HAL1', 'HAL2', 'HAL3', 'HAL4', 'HAL5', 'HAL6', 'ELH1', 'ELH2'])
        self.assertEqual(got[('CHAOS', 'FIDO')], [])
        self.assertEqual(got[('LANDPAD', 'AIRMECHO')], [])

    def test_rule_resolves_every_figr(self):
        for p in sorted(glob.glob(os.path.join(worldmod.GAMEDAT, '*.IFF'))):
            for o in worldmod.load_level_objs(p):
                if o['tag'] == 'FIGR':
                    self.assertIsNotNone(worldmod.figr_view_cams(o['raw']), (p, o['name']))

    def test_airmecho_hidden_until_defined(self):
        w = make_world()
        vmmod.VM(w)
        cmd(w, 'GO', 'LEX_POS2')
        cmd(w, 'CAMERA', 'HFR3')
        m = w.figure('AIRMECHO')
        self.assertEqual(m.view_cams, [])
        hidden = w.render()
        cmd(w, 'GO', 'AIR_POSX', fig='AIRMECHO')
        self.assertTrue(np.array_equal(hidden, w.render()))      # still not drawn after moving
        cmd(w, 'DEFINEVIEWINGCAMS', 'HFR3', 'HFR6', fig='AIRMECHO')
        self.assertEqual(m.view_cams, ['HFR3', 'HFR6'])
        self.assertFalse(np.array_equal(hidden, w.render()))     # now drawn
        cmd(w, 'ADDVIEWINGCAMS', 'HFR6', 'HFR1', fig='AIRMECHO')
        self.assertEqual(m.view_cams, ['HFR3', 'HFR6', 'HFR1'])
        self.assertIsNone(w.figure('PLAYER').view_cams)           # player is never gated


class Commands(unittest.TestCase):
    def test_kill_retires_figure_without_lazy_resurrection(self):
        w = worldmod.World('CHAOS', state_dir=worldmod.INITGAME)
        vm = vmmod.VM(w)
        bot = w.figure('FIRSTBOT')
        bot.avoid = [('AVDBAR3', 100)]
        cmd(w, 'KILL', 'CURFIG', fig='FIRSTBOT')
        self.assertEqual(vm.objects['FIRSTBOT'][0], -666)
        self.assertNotIn('FIRSTBOT', w.figures)
        self.assertIsNone(w.figure('FIRSTBOT'))
        self.assertEqual(w.call('func', 'SETCURRENTFIGURE', ['FIRSTBOT'], proc()), 0)
        self.assertEqual(bot.avoid, [])
        cmd(w, 'CREATEFIGURE', 'NURSEBOT', 'FIRSTBOT')
        self.assertIsNotNone(w.figure('FIRSTBOT'))
        self.assertIsNot(w.figure('FIRSTBOT'), bot)

    def test_bounciness_sets_created_and_loaded_figure_flags(self):
        w = make_world()
        vmmod.VM(w)
        cmd(w, 'CREATEFIGURE', 'NURSEBOT', 'FIRSTBOT')
        bot = w.figures['FIRSTBOT']
        self.assertFalse(bot.bouncy)                         # FIGURES.SCP: FIRSTBOT IS_BOUNCY = 0
        cmd(w, 'BOUNCINESS', 'FIRSTBOT', 'ON')
        self.assertTrue(bot.bouncy)
        cmd(w, 'BOUNCINESS', 'CURFIG', 'OFF', fig='FIRSTBOT')
        self.assertFalse(bot.bouncy)
        bot.vz = -102
        cmd(w, 'STOPVELOCITY', 'CURFIG', fig='FIRSTBOT')
        self.assertEqual(bot.vz, 0)
        w.fig_defs['_BOUNCY_TEST'] = ('LEX', np.zeros(3), [], 0x10, None, 0)
        try:
            self.assertTrue(w.figure('_BOUNCY_TEST').bouncy)
        finally:
            w.fig_defs.pop('_BOUNCY_TEST', None)

    def test_go_snaps_to_waypoint(self):
        w = make_world()
        cmd(w, 'GO', 'LEX_POS')
        f = w.figures['PLAYER']
        wp = w.points['LEX_POS']
        self.assertEqual(f.type, 'LEX')
        np.testing.assert_allclose(f.pos[:2], wp[:2])
        # gravity is on for CREATEFIGURE figures: SetPos (FUN_10a0_1ff0) puts the figure on the floor under the target
        # point (FUN_1060_0871) + F; the waypoint z is up to ~45 units above the true floor
        self.assertEqual(f.pos[2], w.point_floor(int(wp[0]), int(wp[1]), int(wp[2]), int(wp[2])) + f.assets.foot_offset)
        self.assertLess(abs(f.pos[2] - wp[2] - f.assets.foot_offset), 100)
        self.assertFalse(w.is_moving('PLAYER'))

    def test_foot_offset_matches_figr_z(self):
        # AIRMECHO's FIGR z sits one foot_offset above the airlock floor waypoint (within 100 units)
        w = make_world()
        m = w.figure('AIRMECHO')
        self.assertLess(abs(m.pos[2] - m.assets.foot_offset - w.points['AIR_POS'][2]), 100)

    def test_go_walk_arrives_and_stands(self):
        w = make_world()
        cmd(w, 'GO', 'LEX_POS')
        # scaffolding: this world has no script VM, so DR9 keeps its closed (solid) file state, which now blocks the walk; the
        # test is about GO, and the scripted walk (DR9 opened by MARCHOUTAIRMECHO) is covered by the landpad_meetmech scenario
        w.figures['PLAYER'].no_collide = True
        cmd(w, 'GO', 'LEX_POS2', 'WALK')
        f = w.figures['PLAYER']
        self.assertTrue(w.is_moving('PLAYER'))
        self.assertEqual(f.motion, 'WALK')
        self.assertAlmostEqual(f.heading, -90, delta=1)
        xs, ticks = [f.pos[0]], 0
        while w.is_moving('PLAYER') and ticks < 600:
            w.step()
            ticks += 1
            xs.append(f.pos[0])
        self.assertLess(ticks, 300)
        self.assertEqual(f.motion, 'STAND')
        # 10e0:1a4c: the GO ends once length2d(target - pos) < 614 (1098:11c0); there is no snap, so Lex stands where the stride left him
        target = w.points['LEX_POS2'][:2]
        self.assertLess(float(np.hypot(*(f.pos[:2] - target))), worldmod.GO_RADIUS)
        np.testing.assert_allclose(f.pos[:2], [-28216, -71058], atol=0.01)       # 548 units short of LEX_POS2 (-27668, -71040)
        steps = np.diff(xs)
        self.assertTrue((steps >= 0).all())                   # walks toward +x only

    def test_motion_during_go_plays_after_arrival(self):
        w = make_world()
        cmd(w, 'GO', 'AIR_POS', fig='AIRMECHO')
        w.figures['AIRMECHO'].view_cams = None    # a script-created figure is always visible, unlike the placed record
                                                   # w.figure() lazily fetched (view_cams=[])
        cmd(w, 'GO', 'AIR_POSX', 'WALK', fig='AIRMECHO')
        cmd(w, 'MOTION', 'ATK_STAND', 'CONTINUE', fig='AIRMECHO')
        m = w.figures['AIRMECHO']
        self.assertEqual(m.motion, 'WALK')
        run(w, 400)
        self.assertEqual(m.motion, 'ATK_STAND')
        self.assertTrue(m.loop)

    def test_face_number_and_turn(self):
        w = make_world()
        cmd(w, 'GO', 'LEX_POS')
        cmd(w, 'FACE', -90)
        self.assertEqual(w.figures['PLAYER'].heading, -90)
        cmd(w, 'TURN', -5)
        self.assertEqual(w.figures['PLAYER'].heading, -85)       # TURN n = n degrees toward positive bearing (10a0:19e6), heading -= n

    def test_face_name(self):
        w = make_world()
        cmd(w, 'GO', 'LEX_POS')
        cmd(w, 'FACE', 'LEX_POS2')                            # +x
        self.assertAlmostEqual(w.figures['PLAYER'].heading, -90, delta=2)
        cmd(w, 'FACE', 'AIRMECHO')                            # far +x too
        self.assertAlmostEqual(w.figures['PLAYER'].heading, -90, delta=3)
        cmd(w, 'FACE', 'LEX_POS', fig='AIRMECHO')             # AIRMECHO is at +x of LEX_POS: faces -x
        self.assertAlmostEqual(w.figures['AIRMECHO'].heading, 90, delta=3)

    def test_motion_once_vs_continue(self):
        w = make_world()
        cmd(w, 'GO', 'LEX_POS')
        f = w.figures['PLAYER']
        n = len(f.assets.motions['WALK'])
        cmd(w, 'MOTION', 'WALK')
        self.assertEqual((f.motion, f.idx), ('WALK', 0))
        run(w, ticks_for(f, 4))
        self.assertEqual(f.idx, 4)                            # LEX WALK: MY_SPEED 384 x frame time 3 = 2.25 ticks a frame
        run(w, ticks_for(f, n) + 10)
        self.assertEqual(f.idx, n - 1)                        # played once, holds the last frame
        cmd(w, 'MOTION', 'WALK', 'CONTINUE')
        run(w, ticks_for(f, n))
        self.assertEqual(f.idx, 0)                            # looped a full cycle
        run(w, 2)
        self.assertEqual(f.idx, 1)

    def test_go_without_gravity_takes_the_engines_z_root_z_included(self):
        w = make_world()
        cmd(w, 'CREATEFIGURE', 'LEX', 'PLAYER')
        lex = w.player()
        lex.gravity = False
        lex.root_start = False                                             # STAND's first update has run
        self.assertEqual(w.root_z(lex), -40)
        cmd(w, 'GO', 0, 0, -22)
        self.assertEqual(lex.pos[2], -5632 + 40)                           # z is origin + R (10a0:1ff0; live: PLAYLOC's -5754 reads -5714 at R 0)
        self.assertEqual(w.call('func', 'COORDZ', ['PLAYER'], proc()), -22)  # the same z comes back (10d8:104e; live: OUT_OF_BED frame 36, -5714 + 665)
        lex.set_motion('WAKE_UP', False)                                   # R stays -40 until the motion's first update (STARTUPLEX: SNAPTOPOSE, then GO)
        cmd(w, 'GO', 0, 0, -22)
        self.assertEqual(lex.pos[2], -5632 + 40)
        self.assertEqual(w.root_z(lex), 0)

    def test_camera_and_functions(self):
        w = make_world()
        cmd(w, 'GO', 'LEX_POS')
        self.assertEqual(w.current_camera(), next(iter(w.cameras)))        # nothing set: first camera of the level
        self.assertEqual(w.call('func', 'ISCURRENTCAMERA', [next(iter(w.cameras))], proc()), 0)     # the fallback is for drawing: [63e1] is empty until the first switch
        cmd(w, 'LINKMETOCAMERAS', 'HFR6', 'HFR3')
        self.assertEqual(w.current_camera(), next(iter(w.cameras)))        # a link is not a camera
        cmd(w, 'CAMERA', 'HFR3')
        self.assertEqual(w.current_camera(), 'HFR3')
        self.assertEqual(w.call('func', 'ISCURRENTCAMERA', ['HFR3'], proc()), 1)
        self.assertEqual(w.call('func', 'ISCURRENTCAMERA', ['HFR6'], proc()), 0)
        pos = w.figures['PLAYER'].pos
        self.assertEqual(w.call('func', 'COORDX', ['CURFIG'], proc()), int(pos[0]) >> 8)
        self.assertEqual(w.call('func', 'COORDZ', ['PLAYER'], proc()), (int(pos[2]) + w.model_root_z(w.figures['PLAYER'])) >> 8)
        self.assertEqual(w.call('func', 'COORDX', ['LEX_POS'], proc()), 0)        # a waypoint is not an object (FUN_10c0_16a8)
        self.assertEqual(w.warnings, [])


class PlayerControl(unittest.TestCase):
    def setUp(self):
        self.w = make_world()
        vmmod.VM(self.w)
        cmd(self.w, 'CREATEFIGURE', 'LEX', 'PLAYER')
        cmd(self.w, 'GO', 'LEX_POS')
        self.lex = self.w.player()

    def test_forward_and_backward_use_root_motion(self):
        start = self.lex.pos.copy()
        self.w.set_player_input(forward=1)
        run(self.w, 8)
        forward = self.lex.pos - start
        self.assertEqual(self.lex.motion, 'WALK')
        self.assertGreater(float(np.dot(forward[:2], self.lex.forward())), 100)
        self.w.set_player_input(forward=-1)
        start = self.lex.pos.copy()
        run(self.w, 8)
        backward = self.lex.pos - start
        self.assertEqual(self.lex.motion, 'WALK_BACK')
        self.assertLess(float(np.dot(backward[:2], self.lex.forward())), -100)

    def test_turn_and_release_to_stand(self):
        self.w.set_player_input(forward=1, turn=1)
        self.w.step()
        self.w.step()
        self.assertEqual(self.lex.heading, worldmod.PLAYER_TURN_PER_TICK)
        self.w.set_player_input()
        self.w.step()
        self.assertEqual(self.lex.motion, 'STAND')

    def test_input_does_not_interrupt_scripted_go(self):
        cmd(self.w, 'GO', 'LEX_POS2', 'WALK')
        heading = self.lex.heading
        self.w.set_player_input(forward=-1, turn=1, run=True, attack=True)
        run(self.w, 8)
        self.assertIsNotNone(self.lex.go)
        self.assertEqual(self.lex.motion, 'WALK')
        self.assertAlmostEqual(self.lex.heading, heading, delta=1)      # the GO's steering only corrects the walk's drift (steer_go); input turns nothing

    def test_unplaced_player_is_not_driven(self):
        w = make_world()
        vmmod.VM(w)
        cmd(w, 'CREATEFIGURE', 'LEX', 'PLAYER')
        f = w.player()
        w.set_player_input(forward=1, turn=1, attack=True)
        run(w, 8)
        self.assertEqual((f.pos, f.motion, f.heading), (None, 'STAND', 0.0))

    def test_attack_edge_without_loaded_script_does_not_invent_attack_motion(self):
        self.w.set_player_input(attack=True)
        self.w.step()
        self.assertEqual(self.lex.motion, 'STAND')

    def test_a_finished_scripted_player_motion_returns_to_idle(self):
        self.lex.go = None
        cmd(self.w, 'MOTION', 'DROPSHIP_WINS')
        run(self.w, ticks_for(self.lex, len(self.lex.frames)) + 2)
        self.assertEqual(self.lex.motion, 'STAND')               # 1088:4155 has no exemption for the player

        self.w.set_player_input(forward=1)
        self.w.step()
        self.assertEqual(self.lex.motion, 'WALK')

        self.w.set_player_input()
        cmd(self.w, 'MOTION', 'DROPSHIP_WINS')
        run(self.w, ticks_for(self.lex, len(self.lex.frames)) + 2)
        self.w.key_down(0x2e)                                   # C: fresh combat input also takes control
        self.w.step()
        self.assertTrue(self.lex.combat)

    def test_sprite_frames_from_globals(self):
        w = make_world()
        vm = vmmod.VM(w)
        self.assertEqual(w.sprite_frames('HFR3'), {'HFR3': 0, 'DOOR': vm.globals['_door_frame'], 'DRH': 0})
        vm.globals['_door_frame'] = 7
        self.assertEqual(w.sprite_frames('HFR3')['DOOR'], 7)

    def test_render_shape(self):
        w = make_world()
        vmmod.VM(w)
        cmd(w, 'GO', 'LEX_POS2')
        cmd(w, 'CAMERA', 'HFR3')
        self.assertEqual(w.render().shape, (200, 320, 3))


class Grounding(unittest.TestCase):
    def test_support_is_bed_top_or_cell_floor(self):
        w = worldmod.World('CHAOS')
        cmd(w, 'CREATEFIGURE', 'LEX', 'PLAYER')
        lex = w.player()
        lex.pos = np.array([-10944.0, -7281.0, -5754.0])          # PLAYLOC, above bed CT3
        self.assertEqual(w.support(lex, *w.hull(lex)), -6052)
        lex.pos = np.array([-10795.0, -9610.0, -5000.0])          # in front of the bed
        self.assertEqual(w.support(lex, *w.hull(lex)), -7405)

    def test_foot_depth_matches_every_initgame_record(self):
        # FIGR/PLAY records save the model's F (+0x88); the fixed-point FK reproduces each one
        import struct
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'formats'))
        import level
        w, n = worldmod.World('CHAOS'), 0
        for path in sorted(glob.glob(os.path.join(worldmod.INITGAME, '*.IFF'))):
            for o in level.load_level(path):
                if o['tag'] in ('FIGR', 'PLAY'):
                    rec = level.ObjRec(o['tag'], o['raw'])
                    saved = struct.unpack_from('<i', rec.buf, rec.t['s88'])[0]
                    self.assertEqual(w.asset(rec.name.upper()).foot_offset, saved, rec.name)
                    n += 1
        self.assertGreater(n, 40)

    def test_hull_follows_extent_and_foot_depth(self):
        w = worldmod.World('CHAOS')
        cmd(w, 'CREATEFIGURE', 'LEX', 'PLAYER')
        lex = w.player()
        self.assertEqual(lex.assets.foot_offset, 2312)               # MAN.SKL, the engine's F
        lex.pos = np.array([0.0, 0.0, 0.0])
        lo, hi = w.hull(lex)
        r = w.root_z(lex)
        ex, ey, ez = (int(v) for v in worldmod.figure_extents()['LEX'])
        self.assertEqual(lo, (-worldmod.hull_units(ex), -worldmod.hull_units(ey), r - 2293))   # s = 112 cm
        self.assertEqual(hi[2], r + worldmod.hull_units(ez))

    def test_gravity_flag_gates_a_2000_unit_normal_floor_fall(self):
        w = worldmod.World('CHAOS')
        cmd(w, 'CREATEFIGURE', 'LEX', 'PLAYER')
        lex = w.player()
        # BLK (ceiling -799) is tall enough for the whole 2000-unit fall: in CE3 (ceiling -2583) the hull would poke out of the
        # space, which FUN_10a0_0ead treats as a collision, and land at once
        lex.pos = np.array([-5000.0, -20000.0, -7405.0 + lex.assets.foot_offset + 2000.0])
        cmd(w, 'GRAVITY', 'CURFIG', 'OFF')
        w.step()
        self.assertEqual(lex.pos[2], -7405.0 + lex.assets.foot_offset + 2000.0)
        cmd(w, 'GRAVITY', 'CURFIG', 'ON')                         # only sets the bit; the next frames fall
        self.assertEqual(lex.pos[2], -7405.0 + lex.assets.foot_offset + 2000.0)
        w.step()
        self.assertTrue(lex.falling)
        self.assertEqual(lex.vz, -worldmod.FALL_DV)
        velocities = [lex.vz]
        for _ in range(60):
            w.step()
            if lex.falling:
                velocities.append(lex.vz)
            if not lex.falling:
                break
        self.assertFalse(lex.falling)
        self.assertEqual(lex.vz, 0)
        self.assertEqual(velocities[:5], [-102, -204, -306, -408, -510])
        self.assertEqual(lex.motion, 'LAND_SOFT')                    # FUN_10a0_0ead clears vz before 0e24 classifies it
        w.step()
        self.assertEqual(lex.pos[2], -7405 + lex.assets.foot_offset)

    def test_scripted_motion_applies_root_travel(self):
        w = worldmod.World('CHAOS')
        cmd(w, 'CREATEFIGURE', 'LEX', 'PLAYER')
        lex = w.player()
        lex.pos = np.array([0.0, 0.0, -5000.0])
        lex.heading = 0.0
        lex.no_collide = True                     # scaffolding: (0, 0) is outside every CHAOS space; this tests root travel
        cmd(w, 'GRAVITY', 'CURFIG', 'OFF')
        lex.set_motion('OUT_OF_BED', False)
        run(w, 200)
        last = lex.frames[-1][0]
        np.testing.assert_allclose(lex.pos[:2], [last[0], last[1]], atol=1e-6)
        cmd(w, 'MOTION', 'STAND', 'CONTINUE')
        self.assertAlmostEqual(lex.pos[2], -5000.0 + last[2])      # a finished large root z stays as height

    def test_combat_key_twice_lowers_the_fists(self):
        import scenarios
        w, vm = scenarios.boot_opening()
        scenarios.tick(w, vm, scenarios.opening_ticks(1170))
        w.script_auto = True
        lex = w.player()
        w.key_down(0x2e); w.key_up(0x2e)                             # C: combat on (LEX_ENTER_COMBAT: ENTER_COMBAT, then atk_stand)
        scenarios.tick(w, vm, 60)
        self.assertEqual((lex.combat, lex.motion), (True, 'ATK_STAND'))
        w.key_down(0x2e); w.key_up(0x2e)                             # C: combat off; LEX_LEAVE_COMBAT plays no motion, FUN_1098_0745 asks for stand
        scenarios.tick(w, vm, 5)
        self.assertEqual((lex.combat, lex.motion), (False, 'STAND'))

    def test_new_game_wake_up_ends_on_the_cell_floor(self):
        import scenarios
        w, vm = scenarios.boot_opening()
        back, held, woke = [], [], False
        for _ in range(scenarios.opening_ticks(1200)):               # Lex stands from old tick 1155 (opening_ticks: FREEZE blocks)
            scenarios.tick(w, vm, 1)
            lex = w.player()
            woke = woke or lex.motion == 'WAKE_UP_HEAD'
            if woke and lex.motion == 'STAND' and lex.pos[1] == -7281:         # the idle at WAKE_UP's end, in bed: live, its pose is never drawn
                frames, i, _ = lex.held_pose
                held.append((len(frames), i))
            if w.player().motion == 'OUT_OF_BED' and w.player().idx >= 21:          # the step off the bed (y falls ~2300): the drawn body never slides back
                back.append(float(np.mean(w.posed(w.player())[:, 1])))
        self.assertLess(max(b - a for a, b in zip(back, back[1:])), 20)
        wake = len(w.player().assets.motions['WAKE_UP'])
        self.assertEqual(held, [(wake, wake - 1)])                   # drawn: WAKE_UP's last frame (DOSBox-X 2026-11-12)
        lex = w.player()
        floor = -7405
        self.assertTrue(lex.gravity)
        self.assertAlmostEqual(lex.pos[2], floor + lex.assets.foot_offset)
        # engine z = support + F + root z: -7405 + 2312 - 40 = -5133, as in the real saves
        self.assertEqual(lex.pos[2] + lex.frames[0][0][2], -5133)
        self.assertGreater(lex.pos[1], -9000)
        self.assertLess(lex.pos[1], -8800)                           # carried ~1640 units from y -7281 by OUT_OF_BED (frame 0's root included;
                                                                     # live DOSBox-X: -8918, the port -8920)
        caynan = w.figures['CAYNAN']
        self.assertTrue(caynan.ai_enabled)
        self.assertIsNone(caynan.ai_proc)                            # hidden CAYNAN_AI stays pending after READY_CAYNAN


class PhysCollision(unittest.TestCase):
    def setUp(self):
        self.w = worldmod.World('CHAOS')
        self.vm = vmmod.VM(self.w)
        cmd(self.w, 'CREATEFIGURE', 'LEX', 'PLAYER')
        cmd(self.w, 'GO', 'PLAYLOC')
        self.lex = self.w.player()

    def reset_before_door(self):
        door = next(p for p in self.w.phys if p['name'] == 'DR3')
        floor = next(p for p in self.w.phys if p['name'] == 'CE3')['lo'][2]
        self.lex.pos[:] = (-10000, door['hi'][1] + 500, floor + self.lex.assets.foot_offset)   # standing on CE3
        self.lex.heading, self.lex.manual_control = 0, False
        self.lex.set_motion('STAND', True)
        return door

    @staticmethod
    def phys(name, state, lo, hi):
        return {'name': name, 'lo': np.array(lo, float), 'hi': np.array(hi, float), 'raw': bytes([state])}

    def test_playloc_hull_reaches_the_bed_support_but_no_area_stays_clear(self):
        # The F-derived lower hull face reaches CT3 at PLAYLOC. With no selected
        # area, the signed solid-minus-space fallback leaves this position clear.
        lo, hi = self.w.hull(self.lex)
        bed = next(p for p in self.w.phys if p['name'] == 'CT3')
        self.assertTrue(np.all(lo < bed['hi']) and np.all(hi > bed['lo']))
        self.assertFalse(self.w.player_blocked(self.lex, self.lex.pos))

    def test_positive_door_blocks_and_open_or_neutral_passes(self):
        door = self.reset_before_door()
        cmd(self.w, 'COLLISIONS', 'CURFIG', 'ON')
        self.w.set_player_input(forward=1)
        self.vm.globals['_dr3_space'] = 1
        run(self.w, 60)
        self.assertGreater(self.lex.pos[1], door['hi'][1])

        self.reset_before_door()
        self.vm.globals['_dr3_space'] = 0
        run(self.w, 60)
        self.assertLess(self.lex.pos[1], door['lo'][1])

        # NEUTRAL is ignored by the score, so a neutral doorway is not walkable space.
        self.reset_before_door()
        self.vm.globals['_dr3_space'] = 2
        run(self.w, 60)
        self.assertGreater(self.lex.pos[1], door['hi'][1])

    def test_collision_off_bypasses_positive_door(self):
        door = self.reset_before_door()
        cmd(self.w, 'COLLISIONS', 'CURFIG', 'ON')
        self.w.set_player_input(forward=1)
        self.vm.globals['_dr3_space'] = 1
        run(self.w, 60)
        blocked_y = self.lex.pos[1]
        cmd(self.w, 'COLLISIONS', 'CURFIG', 'OFF')
        run(self.w, 60)
        self.assertLess(self.lex.pos[1], door['lo'][1])
        self.assertLess(self.lex.pos[1], blocked_y)

    def test_large_delta_stops_at_positive_door_boundary(self):
        door = self.reset_before_door()
        cmd(self.w, 'COLLISIONS', 'CURFIG', 'ON')
        self.vm.globals['_dr3_space'] = 1
        start = self.lex.pos.copy()
        # Six 833-unit steps (5000 / the 736 hull span); the first already enters DR3. The response
        # then keeps the blocked x with the start y, which is the start itself for a straight push.
        self.assertFalse(self.w.player_move(self.lex, np.array([0.0, -5000.0])))
        np.testing.assert_array_equal(self.lex.pos, start)

    def test_figure_push_arithmetic(self):
        self.assertEqual(worldmod.length2d(3000, -4000), 5000)
        self.assertEqual(worldmod.length2d(3, 4), 5)
        self.assertEqual(worldmod.length2d(0, 0), 0)
        # The original's nurse beside Lex after OUT_OF_BED (DOSBox-X): Lex lands at (-10270, -8879), as observed live.
        np.testing.assert_array_equal(worldmod.push_out(np.array([-10795., -9610., -5093.]),
                                                        np.array([-11394., -10445., -4515.]), 1945),
                                      (-10270, -8879, -5093))
        # q = (r << 4) / |d| is an integer: an overlap below r / 16 leaves the target where it was.
        np.testing.assert_array_equal(worldmod.push_out(np.array([-10795., -9610., 0.]),
                                                        np.array([-10478., -11490., 0.]), 1945),
                                      (-10795, -9610, 0))

    def test_figure_radius_and_hit_points_come_from_figures_scp(self):
        cmd(self.w, 'CREATEFIGURE', 'NURSEBOT', 'FIRSTBOT')
        nurse = self.w.figures['FIRSTBOT']
        self.assertEqual(worldmod.personal_radius(self.lex), 819)          # LEX PERSONAL_RADIUS 40
        self.assertEqual(worldmod.personal_radius(nurse), 1126)            # FIRSTBOT 55
        self.assertEqual(self.vm.objects['FIRSTBOT'], [50, 0, 0, 0, 0, 50, 0, 0, 0, 0])   # fresh: ~0 = ~5 = MAX HPS
        # Level figures take their FIGR record's locals (DOSBox-X: GUARD1 ~0 100, ~5 170).
        self.assertEqual(self.vm.objects['GUARD1'], [100, 0, 0, 0, 0, 170, 0, 0, 0, 0])
        self.assertEqual(self.vm.objects['CAYNAN'][:6], [200, 0, 0, 0, 0, 200])

    def test_standing_figure_is_pushed_out_of_another_figures_radius(self):
        cmd(self.w, 'CREATEFIGURE', 'NURSEBOT', 'FIRSTBOT')
        nurse = self.w.figures['FIRSTBOT']
        self.w.phys = [self.phys('ROOM', 0, (-9000, -9000, -6000), (9000, 9000, 6000))]
        self.w._boxes = None
        self.lex.pos = np.array([0.0, 0.0, 0.0])
        self.lex.set_motion('STAND', True)
        nurse.pos = np.array([600.0, 0.0, 0.0])
        cmd(self.w, 'COLLISIONS', 'CURFIG', 'ON')
        cmd(self.w, 'COLLISIONS', 'CURFIG', 'ON', fig='FIRSTBOT')
        start = self.lex.pos.copy()
        self.w.step()
        self.assertLess(self.lex.pos[0], start[0] - 1000)                  # out to ~1945 from the nurse
        # A dead (~0 = 0) or hidden figure does not push.
        self.lex.pos = start.copy()
        self.vm.objects['FIRSTBOT'][0] = 0
        self.w.step()
        np.testing.assert_array_equal(self.lex.pos[:2], start[:2])

    def test_avoidance_point_list_rules(self):
        names = [n for n in self.w.points if n.startswith('AVDBAR') or n == 'WAY_PT2' or n == 'GETMEAT']
        names += [n for n in self.w.points if n not in names][:9 - len(names)]
        cmd(self.w, 'ADDAVOIDANCEPOINT', names[0], 110)
        cmd(self.w, 'ADDAVOIDANCEPOINT', names[0], 50)                     # already listed: radius kept
        cmd(self.w, 'ADDAVOIDANCEPOINT', names[1], 0)                      # radius must be > 0
        cmd(self.w, 'ADDAVOIDANCEPOINT', 'NO_SUCH_OBJECT', 100)
        self.assertEqual(self.lex.avoid, [(names[0], 110)])
        for i, n in enumerate(names[1:], 1):
            cmd(self.w, 'ADDAVOIDANCEPOINT', n, 100 + i)
        self.assertEqual([n for n, _ in self.lex.avoid], names[:8])         # at most 8
        cmd(self.w, 'REMOVEAVOIDANCEPOINT', names[7])                       # slot 7 is not scanned
        self.assertEqual(len(self.lex.avoid), 8)
        cmd(self.w, 'REMOVEAVOIDANCEPOINT', names[2])                       # later entries shift down
        self.assertEqual(self.lex.avoid, [(names[0], 110), (names[1], 101)] + [(n, 100 + i) for i, n in enumerate(names[3:8], 3)])
        cmd(self.w, 'REMOVEAVOIDANCEPOINT', names[7])                       # now in slot 6
        self.assertEqual(len(self.lex.avoid), 6)

    def test_collisions_follow_flag_0x02_and_the_collisions_statement(self):
        self.assertFalse(self.lex.no_collide)                        # every figure collides until flag 0x02 is set
        self.assertTrue(self.lex.collisions)
        cmd(self.w, 'CREATEFIGURE', 'NURSEBOT', 'NURSE')
        self.assertTrue(self.w.figures['NURSE'].collisions)
        cmd(self.w, 'COLLISIONS', 'CURFIG', 'OFF')
        self.assertTrue(self.lex.no_collide)
        self.assertFalse(self.lex.collisions)
        cmd(self.w, 'COLLISIONS', 'CURFIG', 'ON')
        self.assertTrue(self.lex.collisions)
        with self.assertRaises(AttributeError):                      # no separate opt-in state any more
            self.lex.collisions = False
        self.assertTrue(all(not f.no_collide for f in (self.w.figure(n) for n in self.w.fig_defs) if f is not None
                            and not self.w.fig_defs[f.name][3] & 2))   # level figures take the FIGR flag byte

    def test_avoidance_point_pushes_a_living_figure_with_collisions_off(self):
        point = np.array(self.w.points['AVDBAR3'], float)
        self.lex.pos = point + (300, 400, 0)
        self.lex.set_motion('STAND', True)
        self.lex.no_collide = True
        self.assertFalse(self.lex.collisions)
        cmd(self.w, 'ADDAVOIDANCEPOINT', 'AVDBAR3', 110)                  # (110 << 11) / 100 = 2252
        self.w.step()
        np.testing.assert_array_equal(self.lex.pos[:2], worldmod.push_out(point + (300, 400, 0), point, 2252)[:2])
        self.assertAlmostEqual(np.hypot(*(self.lex.pos[:2] - point[:2])), 2252, delta=2)
        # A dead figure (~0 = 0) is not pushed; a removed point no longer pushes.
        self.lex.pos = point + (300, 400, 0)
        self.vm.objects[self.w.object_key(self.lex.name)][0] = 0
        self.w.step()
        np.testing.assert_array_equal(self.lex.pos[:2], (point + (300, 400, 0))[:2])
        self.vm.objects[self.w.object_key(self.lex.name)][0] = 100
        cmd(self.w, 'REMOVEAVOIDANCEPOINT', 'AVDBAR3')
        self.w.step()
        np.testing.assert_array_equal(self.lex.pos[:2], (point + (300, 400, 0))[:2])

    def test_mover_step_arithmetic(self):
        self.assertEqual(worldmod.approx_length((3000, -4000, 0)), 4000 + 750 + 375 - 93)
        self.assertEqual(worldmod.approx_length((0, 0, 0)), 0)
        self.assertEqual(worldmod.fix_div(-5000, 6 << 8), -833)
        self.assertEqual(worldmod.fix_div(5000, 6 << 8), 833)
        self.assertEqual(worldmod.move_steps((0, -5000), 736), 6)
        self.assertEqual(worldmod.move_steps((736, 0), 736), 1)

    def test_blocked_oblique_move_slides_along_the_wall(self):
        # z = 1, not 0: FUN_10a0_0ead skips the slide when the last good position is exactly the zero vector
        self.lex.pos[:] = (0, 0, 1)
        self.lex.vz = 0
        self.w.phys = [self.phys('ROOM', 0, (-5000, -5000, -3000), (5000, 5000, 2000)),
                       self.phys('WALL', 1, (-5000, 1000, -3000), (5000, 1200, 2000))]
        self.vm.globals['_wall_space'] = 1             # a bound PHYS joins the area's members
        self.w._boxes = None
        # Two 750-unit y steps; the first touches WALL, so x from the step is kept with the start y.
        self.assertFalse(self.w.figure_move(self.lex, np.array([300.0, 1500.0])))
        np.testing.assert_array_equal(self.lex.pos, (150, 0, 1))
        # A short move takes the single target check and slides the same way.
        self.lex.pos[:] = (0, 500, 1)
        self.assertFalse(self.w.figure_move(self.lex, np.array([100.0, 200.0])))
        np.testing.assert_array_equal(self.lex.pos, (100, 500, 1))
        # With z velocity the response skips the slide and returns to the last good step.
        self.lex.pos[:] = (0, 0, 0)
        self.lex.vz = -10
        self.assertFalse(self.w.figure_move(self.lex, np.array([300.0, 1500.0])))
        np.testing.assert_array_equal(self.lex.pos, (0, 0, 0))

    def test_bouncy_collision_rolls_back_axes_without_turning(self):
        self.lex.pos[:] = (0, 0, 0)
        self.lex.bouncy, self.lex.vz, self.lex.heading = True, -10, 47
        room = self.phys('ROOM', 0, (-5000, -5000, -3000), (5000, 5000, 2000))
        wall_x = self.phys('WALL_X', 1, (1000, -5000, -3000), (1200, 5000, 2000))
        wall_y = self.phys('WALL_Y', 1, (-5000, 1000, -3000), (5000, 1200, 2000))
        self.vm.globals['_wall_x_space'] = self.vm.globals['_wall_y_space'] = 1
        # X wall: first rollback candidate keeps blocked y and restores x.
        self.w.phys, self.w._boxes = [room, wall_x], None
        self.assertFalse(self.w.figure_move(self.lex, np.array([1500.0, 300.0])))
        np.testing.assert_array_equal(self.lex.pos, (0, 150, 0))
        self.assertEqual(self.lex.heading, 47)
        # Y wall: the X rollback remains blocked, so the second candidate restores y.
        self.lex.pos[:] = (0, 0, 0)
        self.w.phys, self.w._boxes = [room, wall_y], None
        self.assertFalse(self.w.figure_move(self.lex, np.array([300.0, 1500.0])))
        np.testing.assert_array_equal(self.lex.pos, (150, 0, 0))
        # A corner rejects both axis candidates and restores both axes.
        self.lex.pos[:] = (0, 0, 0)
        self.w.phys, self.w._boxes = [room, wall_x, wall_y], None
        self.assertFalse(self.w.figure_move(self.lex, np.array([1500.0, 1500.0])))
        np.testing.assert_array_equal(self.lex.pos, (0, 0, 0))
        # The same falling, non-bouncy figure retains the existing last-good response.
        self.lex.bouncy = False
        self.w.phys, self.w._boxes = [room, wall_y], None
        self.assertFalse(self.w.figure_move(self.lex, np.array([300.0, 1500.0])))
        np.testing.assert_array_equal(self.lex.pos, (0, 0, 0))

    def test_collision_bounds_are_the_grounding_hull(self):
        cmd(self.w, 'CREATEFIGURE', 'NURSEBOT', 'NURSE')
        cmd(self.w, 'CREATEFIGURE', 'MECHO', 'MECHO')
        candidate = np.array([50000.0, 50000.0, 0.0])
        for name in ('NURSE', 'MECHO'):
            fig = self.w.figures[name]
            fig.pos = candidate.copy()
            expected = self.w.hull(fig)
            actual = self.w.figure_bounds(fig, candidate)
            np.testing.assert_array_equal(actual[0], expected[0])
            np.testing.assert_array_equal(actual[1], expected[1])

        # AIRMECHO has no mesh of its own and therefore keeps the default
        # EXTENT despite sharing MECHO's material. Supply the pose fields the
        # hull needs instead of relying on the old centered-box shortcut.
        air = types.SimpleNamespace(type='AIRMECHO', pos=candidate.copy(),
                                    assets=self.lex.assets, frames=self.lex.frames, idx=self.lex.idx)
        lo, hi = self.w.figure_bounds(air, candidate)
        self.assertEqual(hi[0] - lo[0], 2 * worldmod.hull_units(10))
        self.assertEqual(hi[1] - lo[1], 2 * worldmod.hull_units(10))

        # Lex's F-derived lower face reaches below the former centered 20-unit/cm
        # box, while the current STAND root offset is still part of the hull.
        self.lex.pos = candidate.copy()
        lo, hi = self.w.figure_bounds(self.lex)
        self.assertEqual(lo[2], self.lex.pos[2] + self.w.root_z(self.lex) - 2293)
        self.assertEqual(hi[2], self.lex.pos[2] + self.w.root_z(self.lex) + worldmod.hull_units(58))
        self.w.phys.append({'name': 'HULL_ONLY',
                            'lo': np.array([49900.0, 49900.0, -2200.0]),
                            'hi': np.array([50100.0, 50100.0, -1800.0]), 'raw': b'\x01'})
        self.assertTrue(self.w.figure_blocked(self.lex, candidate))

    def test_no_area_subtracts_overlapping_space_from_solid(self):
        self.lex.pos[:] = (0, 0, 0)
        self.lex.area = None
        self.w.phys = [self.phys('SOLID', 1, (-1000, -1000, -3000), (1000, 1000, 2000)),
                       self.phys('SPACE', 0, (-1000, -1000, -3000), (1000, 1000, 2000))]
        self.w._boxes = None
        # The hull volume starts the score; a solid adds its overlap even inside a space.
        self.assertTrue(self.w.null_area_blocked(*self.w.hull(self.lex)))
        # An enclosing space alone cancels the hull volume exactly.
        self.w.phys.pop(0)
        self.w._boxes = None
        self.assertFalse(self.w.null_area_blocked(*self.w.hull(self.lex)))
        # Outside every space the hull volume alone is positive.
        self.w.phys.pop(0)
        self.w._boxes = None
        self.assertTrue(self.w.null_area_blocked(*self.w.hull(self.lex)))

    def test_fixed_collision_score_rounding_overflow_and_partial_boxes(self):
        box = lambda state, lo, hi: (None, state, np.array(lo), np.array(hi))
        lo, hi = np.array([0, 0, 0]), np.array([256, 256, 256])
        self.assertEqual(worldmod.collision_volume((255, 255, 255)), 253)
        self.assertEqual(worldmod.collision_volume((65536, 65536, 256)), 0)
        self.assertEqual(worldmod.collision_volume((65535, 65535, 256)), 512)
        self.assertEqual(self.w.collision_score(lo, hi, []), 256)
        self.assertEqual(self.w.collision_score(lo, hi, [box(0, lo, hi)]), 0)
        self.assertEqual(self.w.collision_score(lo, hi, [box(1, (0, 0, 0), (128, 256, 256)),
                                                          box(0, (0, 0, 0), (64, 256, 256))]), 320)

    def test_area_members_are_every_phys_touching_the_grown_anchor(self):
        # FUN_1138_131c: physical_objs holds every PHYS (solids included) touching the
        # anchor box grown by 0x1000; only spaces and bound PHYS anchor areas.
        self.lex.pos[:] = (0, 0, 0)
        self.w.phys = [self.phys('AREA', 0, (-1000, -1000, -3000), (1000, 1000, 2000)),
                       self.phys('NEAR', 1, (1000 + 0x1000, -1000, -3000), (6000, 1000, 2000)),
                       self.phys('FAR', 1, (1001 + 0x1000, -1000, -3000), (6000, 1000, 2000)),
                       self.phys('UNBOUND', 1, (-1000, -1000, -3000), (1000, 1000, 2000))]
        self.w._boxes = None
        self.assertEqual([area[0] for area in self.w.area_candidates()], [0])
        self.w.select_area(self.lex)
        self.assertEqual(self.lex.area, 0)
        self.assertEqual([p['name'] for p, _, _, _ in self.w.area_members(self.lex.area)], ['AREA', 'NEAR', 'UNBOUND'])
        self.assertTrue(self.w.figure_blocked(self.lex, self.lex.pos))
        self.w.phys.pop()
        self.w._boxes = None
        self.assertFalse(self.w.figure_blocked(self.lex, self.lex.pos))

    def test_area_members_and_movement_transition_are_ordered(self):
        self.lex.pos[:] = (0, 0, 0)
        self.w.phys = [self.phys('AREA_A', 0, (-1000, -1000, -3000), (1000, 1000, 2000)),
                       self.phys('BLOCK_A', 1, (600, -1000, -3000), (700, 1000, 2000)),
                       self.phys('AREA_B', 0, (900, -1000, -3000), (3000, 1000, 2000))]
        self.vm.globals['_block_a_space'] = 1
        self.w._boxes = None
        self.w.select_area(self.lex)
        self.assertEqual(self.lex.area, 0)
        self.assertEqual([p['name'] for p, _, _, _ in self.w.area_members(self.lex.area)], ['AREA_A', 'BLOCK_A', 'AREA_B'])
        self.assertFalse(self.w.figure_blocked(self.lex, self.lex.pos))
        self.lex.pos[:] = (400, 0, 0)
        self.assertTrue(self.w.figure_blocked(self.lex, self.lex.pos))

        # With the area-A-only blocker removed, candidate substeps select B once
        # the mover leaves A. A later miss retains B, matching the sticky index.
        self.w.phys.pop(1)
        self.w._boxes = None
        # Spaces that only touch leave a truncation remainder: the two shifted
        # partial volumes sum below the hull's, so the straddling hull is blocked.
        b = self.w.phys[1]
        b['lo'][0] = 1000
        self.w._boxes = None
        self.assertTrue(self.w.figure_blocked(self.lex, np.array([750.0, 0.0, 0.0])))
        b['lo'][0] = 900
        self.w._boxes = None
        self.assertTrue(self.w.figure_move(self.lex, np.array([2000.0, 0.0])))
        self.assertEqual(self.lex.area, 1)
        self.lex.pos[:] = (5000, 0, 0)
        self.w.select_area(self.lex)
        self.assertEqual(self.lex.area, 1)
        self.lex.pos[:] = (0, 0, 0)
        self.lex.area, self.lex.no_collide = None, True
        self.assertTrue(self.w.figure_move(self.lex, np.array([2000.0, 0.0])))
        self.assertEqual(self.lex.area, 1)
        self.w.load_objects('LANDPAD')
        self.assertIsNone(self.lex.area)
        self.assertFalse(self.lex.in_area)

    def test_go_waits_at_closed_door_then_collision_off_reaches_target(self):
        door = next(p for p in self.w.phys if p['name'] == 'DR3')
        cmd(self.w, 'CREATEFIGURE', 'NURSEBOT', 'NURSE')
        nurse = self.w.figures['NURSE']
        nurse.pos = np.array([-10000, door['hi'][1] + 500, -5754 + nurse.assets.foot_offset], float)
        self.w.points['BEYOND_DOOR'] = np.array([-10000, door['lo'][1] - 1000, -5754], float)
        cmd(self.w, 'COLLISIONS', 'CURFIG', 'ON', fig='NURSE')
        self.vm.globals['_dr3_space'] = 1
        cmd(self.w, 'GO', 'BEYOND_DOOR', 'WALK', fig='NURSE')
        run(self.w, 300)
        self.assertTrue(nurse.is_moving())
        self.assertGreater(nurse.pos[1], door['hi'][1])
        cmd(self.w, 'COLLISIONS', 'CURFIG', 'OFF', fig='NURSE')
        run(self.w, 300)
        self.assertFalse(nurse.is_moving())
        gap = self.w.points['BEYOND_DOOR'][:2] - nurse.pos[:2]
        self.assertLess(float(np.hypot(*gap)), worldmod.GO_RADIUS)       # ends within 614 units of the target, no snap (10e0:1a4c)
        np.testing.assert_allclose(nurse.pos[:2], [-10000, -15969])      # 579 units short of BEYOND_DOOR (-10000, -16548)

    def test_blocked_go_keeps_its_script_waiting_until_door_opens(self):
        door = next(p for p in self.w.phys if p['name'] == 'DR3')
        cmd(self.w, 'CREATEFIGURE', 'NURSEBOT', 'NURSE')
        nurse = self.w.figures['NURSE']
        nurse.pos = np.array([-10000, door['hi'][1] + 500, -5754 + nurse.assets.foot_offset], float)
        self.w.points['BEYOND_DOOR'] = np.array([-10000, door['lo'][1] - 1000, -5754], float)
        with tempfile.NamedTemporaryFile('w', suffix='.scr', delete=False) as f:
            f.write('{ GOWAIT\n\tSETCURRENTFIGURE NURSE\n\tCOLLISIONS CURFIG ON\n\tGO BEYOND_DOOR WALK\n\t_door_frame = 5\n}\n')
        try:
            self.vm.load(f.name)
        finally:
            os.unlink(f.name)
        self.vm.globals['_dr3_space'] = 1
        self.vm.globals['_door_frame'] = 0
        self.vm.fire('GOWAIT')
        for _ in range(300):
            self.vm.tick_once()
            self.w.step()
        self.assertTrue(nurse.is_moving())
        self.assertEqual(self.vm.globals['_door_frame'], 0)
        self.vm.globals['_dr3_space'] = 0
        for _ in range(300):
            self.vm.tick_once()
            self.w.step()
        self.assertFalse(nurse.is_moving())
        self.assertEqual(self.vm.globals['_door_frame'], 5)

    def test_ai_root_motion_respects_closed_door(self):
        door = next(p for p in self.w.phys if p['name'] == 'DR3')
        cmd(self.w, 'CREATEFIGURE', 'NURSEBOT', 'NURSE')
        nurse = self.w.figures['NURSE']
        nurse.pos = np.array([-10000, door['hi'][1] + 500, -5754 + nurse.assets.foot_offset], float)
        nurse.heading, nurse.no_collide = 0, False
        nurse.ai_proc = types.SimpleNamespace(done=False)
        nurse.set_motion('WALK', True)
        self.vm.globals['_dr3_space'] = 1
        for _ in range(300):
            self.w.advance(nurse)
            self.w.frame_move(nurse)         # advance only accumulates the root motion; the frame's one mover call applies it
        self.assertGreater(nurse.pos[1], door['hi'][1])
        nurse.no_collide = True
        for _ in range(300):
            self.w.advance(nurse)
            self.w.frame_move(nurse)
        self.assertLess(nurse.pos[1], door['lo'][1])


class PersistentVelocity(unittest.TestCase):
    """FUN_1088_384e / 39ef / 10a0_22e1 / 1070_0fa7: the persistent velocity, its step, the 3D mover, the rebound and the statements,
    on synthetic PHYS boxes (a ROOM space with floor z -3000 and solid walls); Lex's hull is 736 x 736 x 3480 at the origin."""

    @staticmethod
    def phys(name, state, lo, hi):
        return {'name': name, 'lo': np.array(lo, float), 'hi': np.array(hi, float), 'raw': bytes([state])}

    def setUp(self):
        self.w = worldmod.World('CHAOS')
        self.vm = vmmod.VM(self.w)
        cmd(self.w, 'CREATEFIGURE', 'LEX', 'PLAYER')
        cmd(self.w, 'GO', 'PLAYLOC')
        self.lex = self.w.player()
        self.lex.pos[:] = (0, 0, 0)
        self.lex.gravity = False
        self.lex.prev_pos = self.lex.pos.copy()
        self.room = self.phys('ROOM', 0, (-5000, -5000, -3000), (5000, 5000, 12000))
        self.wall_x = self.phys('WALL_X', 1, (1000, -5000, -3000), (1200, 5000, 12000))
        self.wall_y = self.phys('WALL_Y', 1, (-5000, 1000, -3000), (5000, 1200, 12000))
        self.vm.globals['_wall_x_space'] = self.vm.globals['_wall_y_space'] = 1

    def world(self, *boxes):
        self.w.phys, self.w._boxes = [self.room, *boxes], None

    def frame(self):
        """One frame of the move: the frame start is recorded the way the tick does."""
        self.lex.prev_pos = self.lex.pos.copy()
        self.w.frame_move(self.lex)

    def test_step_scaling_by_frame_time(self):
        v = (100, -100, 5)
        self.assertEqual(worldmod.velocity_step(v), [100, -100, 5])              # 30 fps ([83a0] = 512): step == v
        self.assertEqual(worldmod.velocity_step(v, 256), [50, -50, 2])           # 60 fps: scale 128; 5 * 128 >> 8 = 2
        self.assertEqual(worldmod.velocity_step(v, 768), [150, -150, 7])         # 20 fps: scale 384
        self.assertEqual(worldmod.velocity_step(v, 600), [119, -120, 5])         # 0x3c00 // 600 = 25 whole fps, scale 307; 0c42 floors
        self.assertEqual(worldmod.velocity_step(v, 0), [0, 0, 0])                # 0 -> 1: 0x3c00 fps, scale 0
        self.assertEqual(worldmod.velocity_step((1,), 0x4000), [0x1e0000 >> 8])  # slower than 1 fps: fps clamps to 1, scale 0x1e0000

    def test_blocked_step_scaling_truncates_toward_zero(self):
        self.assertEqual(worldmod.scale_step([7, -7, 0, 10], 1, 3), [2, -2, 0, 3])
        self.assertEqual(worldmod.scale_step([3000, -3001, 0], 2, 4), [1500, -1500, 0])
        self.world(self.wall_x)
        self.lex.step = [3000, 0, 0]
        self.assertFalse(self.w.mover(self.lex, np.array([3000.0, 0, 0])))     # n = 4 steps of 750: the first touches the wall
        self.assertEqual(self.lex.pos[0], 750)
        self.assertEqual(self.lex.step, [750, 0, 0])

    def test_mover_length_and_steps_include_z(self):
        self.assertEqual(worldmod.move_steps((0, 0, 8000), 736), 10)
        self.world(self.phys('CEIL', 1, (-5000, -5000, 2000), (5000, 5000, 2100)))
        self.vm.globals['_ceil_space'] = 1
        # the final hull (z 5667..9147) clears the thin ceiling box, only the 3D steps (800 each) see it: step 2 (z 1600) is blocked
        self.lex.step = [0, 0, 8000]
        self.assertFalse(self.w.mover(self.lex, np.array([0.0, 0, 8000])))
        self.assertEqual(self.lex.pos[2], 1600)
        self.assertEqual(self.lex.step, [0, 0, 1600])

    def test_horizontal_velocity_carries_without_friction(self):
        self.world()
        self.lex.vx, self.lex.vy = 300, -200
        for i in range(1, 6):
            self.frame()
            np.testing.assert_array_equal(self.lex.pos, (300 * i, -200 * i, 0))
            self.assertEqual((self.lex.vx, self.lex.vy, self.lex.vz), (300, -200, 0))
        self.assertEqual(self.lex.step, [300, -200, 0])
        self.assertFalse(self.lex.gravity)                       # a figure without the gravity flag moves too

    def test_non_bouncy_collision_zeroes_the_velocity(self):
        self.world(self.wall_x)
        self.lex.vx = 300
        for _ in range(4):
            self.frame()
        self.assertEqual((self.lex.vx, self.lex.vy, self.lex.vz), (0, 0, 0))
        self.assertLess(self.lex.pos[0], 1000 - 368)             # stopped short of the wall
        before = self.lex.pos.copy()
        self.frame()
        np.testing.assert_array_equal(self.lex.pos, before)

    def rebound(self, elasticity, v, wall):
        self.world(wall)
        self.lex.bouncy, self.lex.elasticity = True, elasticity
        self.lex.vx, self.lex.vy = v
        for _ in range(3):
            self.frame()
            if self.lex.vx != v[0] or self.lex.vy != v[1]:
                break
        return self.lex

    def test_bouncy_rebound_negates_the_candidate_axes_and_loses_energy(self):
        # E: ((vx, vy), step) after the rebound, v -= floor(v * E / 256) on both (E 0 = lossless)
        expected = {0: ((-300, 200), [300, 200, 0]), 50: ((-241, 161), [242, 161, 0]), 200: ((-65, 44), [66, 44, 0])}
        for e, (v, step) in expected.items():
            self.setUp()
            lex = self.rebound(e, (300, 200), self.wall_x)
            # frames: x 300, 600, then 900 hits the wall (hull edge 1268 > 1000); step = (300, 200, 0); candidate X (600, y) is free
            np.testing.assert_array_equal(lex.pos, (600, 600, 0))
            self.assertEqual((lex.vx, lex.vy, lex.vz), v + (0,), e)             # only x negated
            self.assertEqual(lex.step, step, e)

    def test_bounce_tries_y_after_x(self):
        lex = self.rebound(0, (200, 300), self.wall_y)             # the wall is in y: X (prev x, blocked y) is blocked, Y is free
        np.testing.assert_array_equal(lex.pos, (600, 600, 0))
        self.assertEqual((lex.vx, lex.vy, lex.vz), (200, -300, 0))

    def test_bounce_falls_back_to_where_the_yz_attempt_left_the_figure(self):
        # every candidate fails inside a solid box: the fallback mover call does not return to the last good position
        self.world(self.phys('BLOCK', 1, (-3000, -3000, -3000), (3000, 3000, 12000)))
        self.vm.globals['_block_space'] = 1
        lex = self.lex
        lex.bouncy, lex.elasticity = True, 0
        lex.pos[:], lex.prev_pos = (500.0, 500.0, 0.0), np.array([200.0, 300.0, 0.0])
        lex.vx, lex.vy, lex.vz = 300, 200, 0
        self.w.bounce_collision(lex, lex.prev_pos)
        np.testing.assert_array_equal(lex.pos, (500, 300, 0))     # YZ = (P.x, prev.y, prev.z)
        self.assertEqual((lex.vx, lex.vy, lex.vz), (-300, -200, 0))

    def test_bounce_off_the_floor_negates_z_and_keeps_rising(self):
        self.world(self.phys('FLOOR', 1, (-5000, -5000, -3000), (5000, 5000, -2400)))
        self.vm.globals['_floor_space'] = 1
        lex = self.lex
        lex.bouncy, lex.elasticity, lex.falling, lex.vz = True, 50, True, -300
        self.frame()                                  # z -300: the hull bottom (-2633) is under the floor top (-2400)
        # step z = -300; X and Y candidates are P itself (blocked); Z goes back up to z 0, strictly above the support
        np.testing.assert_array_equal(lex.pos, (0, 0, 0))
        self.assertEqual(lex.vz, 300 - 58)            # -(-300), then v -= floor(300 * 50 / 256)
        self.assertEqual(lex.step, [0, 0, -300 + 59])  # the step -300 loses floor(-300 * 50 / 256) = -59
        self.assertFalse(lex.falling)
        self.frame()                                  # not falling any more: gravity is off and vz keeps its value
        self.frame()
        self.assertEqual((lex.pos[2], lex.vz), (2 * 242, 242))

    def test_set_stop_and_read_velocity_round_trip(self):
        w, lex = self.w, self.lex
        cmd(w, 'SETVELOCITY', 'CURFIG', 100, -200, 300)
        self.assertEqual((lex.vx, lex.vy, lex.vz), (100, -200, 300))
        rd = lambda n: w.call('func', n, ['CURFIG'], proc())
        self.assertEqual((rd('VELOCITYX'), rd('VELOCITYY'), rd('VELOCITYZ')), (100, -200, 300))
        cmd(w, 'SETVELOCITY', 'CURFIG', rd('VELOCITYX'), rd('VELOCITYY'), 0)   # the TUNZEROG idiom
        self.assertEqual((lex.vx, lex.vy, lex.vz), (100, -200, 0))
        cmd(w, 'SETVELOCITY', 'PLAYER', 70000, -70000, 2 ** 31 - 1)             # raw s32; the function returns the low 16 bits
        self.assertEqual((lex.vx, lex.vy, lex.vz), (70000, -70000, 2 ** 31 - 1))
        self.assertEqual((rd('VELOCITYX'), rd('VELOCITYY'), rd('VELOCITYZ')), (4464, -4464, -1))
        lex.step = [1, 2, 3]
        cmd(w, 'STOPVELOCITY', 'CURFIG')
        self.assertEqual((lex.vx, lex.vy, lex.vz, lex.step), (0, 0, 0, [0, 0, 0]))
        self.assertEqual(w.call('func', 'VELOCITYX', ['NO_SUCH_FIGURE'], proc()), 0)

    def test_leap_adds_along_row_one_scaled_by_speed(self):
        w, lex = self.w, self.lex
        for heading, expect in ((0, (0, 61, 0)), (90, (61, 0, 0))):   # row 1 = backward = (sin h, cos h); k = (3 << 11) / 100 = 61
            lex.heading, lex.vx, lex.vy, lex.vz = heading, 0, 0, 0
            cmd(w, 'LEAP', 'CURFIG', 0, 3)
            self.assertEqual((lex.vx, lex.vy, lex.vz), expect)
        lex.heading, lex.vx, lex.vy, lex.vz = 0, 0, 0, 0
        cmd(w, 'LEAP', 'CURFIG', 0, -4)                              # negative speed leaps forward (-y at heading 0): k = -81
        self.assertEqual((lex.vx, lex.vy, lex.vz), (0, -81, 0))
        cmd(w, 'STOPVELOCITY', 'CURFIG')
        cmd(w, 'LEAP', 'CURFIG', 45, -3)                             # the pitch tilts row 1 up: a forward leap with negative speed goes down
        self.assertLess(lex.vz, 0)
        self.assertAlmostEqual(lex.vz, lex.vy, delta=1)
        cmd(w, 'STOPVELOCITY', 'CURFIG')
        w.points['GRAVPT'] = (1000.0, 0.0, 0.0)
        cmd(w, 'LEAP', 'CURFIG', 'GRAVPT', 0, 2)                     # toward the target: k = 40
        self.assertEqual((lex.vx, lex.vy, lex.vz), (40, 0, 0))
        w.points['GRAVPT'] = (0.0, 0.0, 1000.0)
        cmd(w, 'LEAP', 'CURFIG', 'GRAVPT', 0, 2)
        self.assertEqual((lex.vx, lex.vy, lex.vz), (40, 0, 40))

    def test_knockback_row_is_backward(self):
        for heading, row1 in ((0, [0, 256, 0]), (90, [256, 0, 0]), (180, [0, -256, 0])):
            self.lex.heading = heading
            self.assertEqual(self.w.orientation(self.lex)[1], row1)

    def test_terminal_fall_speed(self):
        self.lex.gravity = True
        self.world()
        self.room['hi'][2] = 40000
        self.room['lo'][2] = -30000
        self.lex.pos[2] = 20000
        self.w._boxes = None
        seen = []
        for _ in range(18):
            self.lex.prev_pos = self.lex.pos.copy()
            self.w.settle(self.lex)
            seen.append(self.lex.vz)
        self.assertEqual(seen[:3], [-102, -204, -306])
        self.assertEqual(seen[11:13], [-1224, -1326])                # applied while vz > -1280, so it stops at -1326
        self.assertEqual(set(seen[12:]), {-1326})
        self.assertEqual(worldmod.FALL_VMIN, -0x500)


class CollisionResponse(unittest.TestCase):
    """FUN_10a0_0ead: step-up, the vz branches, landing, FUN_1130_1a2d's unstick, the mantle and the BONK sound, on a synthetic
    ROOM space (floor z -3000) with solid boxes."""

    FLOOR = -3000

    @staticmethod
    def box(name, state, lo, hi, flags=0, material=b'STONE'):
        raw = bytearray(64)
        raw[21], raw[45:45 + len(material)], raw[-1] = flags, material, state
        return {'name': name, 'lo': np.array(lo, float), 'hi': np.array(hi, float), 'raw': bytes(raw)}

    def setUp(self):
        self.w = worldmod.World('CHAOS')
        self.vm = vmmod.VM(self.w)
        cmd(self.w, 'CREATEFIGURE', 'LEX', 'PLAYER')
        self.lex = self.w.player()
        self.stand = self.FLOOR + self.lex.assets.foot_offset
        self.room = self.box('ROOM', 0, (-9000, -9000, self.FLOOR), (9000, 9000, 6000))

    def world_with(self, *boxes):
        self.w.phys = [self.room, *boxes]
        self.w._boxes = None
        for b in boxes:
            self.vm.globals['_' + b['name'].lower() + '_space'] = b['raw'][-1]    # bound PHYS join the area's members
        self.lex.pos = np.array([2000.0, 0.0, self.stand])
        self.lex.set_motion('STAND', True)
        self.lex.area = None
        self.w.select_area(self.lex)
        self.lex.vz = 0

    def hull_bottom(self):
        return self.w.query_hull(self.lex)[0][2]

    def test_step_up_lifts_a_low_support_before_the_slide(self):
        self.world_with(self.box('STEP', 1, (1000, -3000, self.FLOOR), (3000, -1000, self.FLOOR + 300)))
        z0 = self.lex.pos[2]
        blocked = np.array([2000.0, -700.0, z0])             # overlaps STEP by 68 units
        self.lex.pos = blocked.copy()
        lo, hi, sup = self.w.query_hull(self.lex)
        self.assertEqual(sup, self.FLOOR + 300)
        k, R = (hi[2] - lo[2]) // 4, self.w.root_z(self.lex)
        self.assertTrue(lo[2] < sup < lo[2] + k - R)         # k = hull dz / 4, R = the frame's root z
        self.w.collision_response(self.lex, np.array([2000.0, 0.0, z0]), blocked, np.array([2000.0, 0.0, z0]))
        np.testing.assert_array_equal(self.lex.pos[:2], blocked[:2])        # no slide: the blocked x, y stay
        self.assertEqual(self.lex.pos[2], z0 + sup - lo[2])
        self.assertEqual(self.hull_bottom(), sup)

    def test_step_taller_than_k_minus_r_slides_instead(self):
        self.world_with(self.box('STEP', 1, (1000, -3000, self.FLOOR), (3000, -1000, self.FLOOR + 1500)))
        z0 = self.lex.pos[2]
        blocked = np.array([2000.0, -700.0, z0])
        self.lex.pos = blocked.copy()
        lo, hi, sup = self.w.query_hull(self.lex)
        self.assertGreaterEqual(sup, lo[2] + (hi[2] - lo[2]) // 4 - self.w.root_z(self.lex))
        self.w.collision_response(self.lex, np.array([2000.0, 0.0, z0]), blocked, np.array([2000.0, 0.0, z0]))
        np.testing.assert_array_equal(self.lex.pos, (2000, 0, z0))          # kept the blocked x, start y

    def test_zero_vector_last_good_skips_the_slide(self):
        self.world_with(self.box('WALL', 1, (-9000, 1000, self.FLOOR), (9000, 1200, 2000)))
        z0 = self.lex.pos[2]
        start, blocked = np.array([0.0, 0.0, z0]), np.array([150.0, 1100.0, z0])
        for good, expect in ((np.array([0.0, 0.0, 1.0]), (150, 0, z0)), (np.zeros(3), (150, 1100, z0))):
            self.lex.pos = start.copy()
            self.w.collision_response(self.lex, start, blocked, good)
            np.testing.assert_array_equal(self.lex.pos, expect)

    def test_z_velocity_without_a_fall_returns_to_the_last_good_position(self):
        self.world_with()
        good = np.array([500.0, 0.0, self.stand])
        self.lex.vz, self.lex.vx, self.lex.falling = -300, 5, False
        self.w.collision_response(self.lex, good, np.array([900.0, 0.0, self.stand - 40]), good)
        np.testing.assert_array_equal(self.lex.pos, good)
        self.assertEqual((self.lex.vx, self.lex.vy, self.lex.vz, self.lex.motion), (0, 0, 0, 'STAND'))

    def test_landing_motion_thresholds(self):
        names = [self.w.landing_motion(v) for v in (-0x300, -0x280, -0x27f, -0x140, -0x13f, 0)]
        self.assertEqual(names, ['LAND_HARD', 'LAND_HARD', 'LAND_MEDIUM', 'LAND_MEDIUM', 'LAND_SOFT', 'LAND_SOFT'])

    def fall(self, fig, drop=100):
        """A falling figure whose hull bottom is `drop` units below the floor; -> (start, good, bottom0)."""
        start = np.array([2000.0, 0.0, self.stand + 2000])
        fig.pos = np.array([2000.0, 0.0, self.stand - drop])
        fig.vz, fig.falling, fig.hold = -500, True, 1
        return start, start.copy(), self.hull_bottom_of(fig)

    def hull_bottom_of(self, fig):
        return self.w.query_hull(fig)[0][2]

    def test_landing_puts_the_hull_on_the_support_and_plays_land_soft(self):
        self.world_with()
        start, good, bottom0 = self.fall(self.lex)
        self.w.vertical_response(self.lex, start, good, bottom0)
        self.assertEqual((self.lex.falling, self.lex.vz, self.lex.hold, self.lex.motion), (False, 0, 0, 'LAND_SOFT'))
        np.testing.assert_array_equal(self.lex.pos[:2], (2000, 0))
        self.assertEqual(self.lex.pos[2], self.stand)                      # unstick's SetPos stands it on the floor

    def test_support_over_0x1000_above_the_entry_bottom_restores_the_previous_position(self):
        self.world_with()
        start, good, bottom0 = self.fall(self.lex, drop=worldmod.LAND_REVERT + 600)
        start[:2] = (2500, 300)
        self.w.vertical_response(self.lex, start, good, bottom0)
        np.testing.assert_array_equal(self.lex.pos[:2], (2500, 300))      # x, y from the previous position, then snapped to the floor
        self.assertEqual(self.lex.pos[2], self.stand)
        self.assertEqual(self.lex.motion, 'LAND_SOFT')

    def test_player_keeps_falling_straight_down_when_the_previous_xy_is_free(self):
        self.world_with()
        start, good, bottom0 = self.fall(self.lex, drop=-500)              # still above the floor, hull free
        start[:2] = (1500, 100)
        self.lex.vx = 7
        self.w.vertical_response(self.lex, start, good, bottom0)
        self.assertTrue(self.lex.falling)
        self.assertEqual((self.lex.vx, self.lex.vy, self.lex.vz), (0, 0, -500))
        np.testing.assert_array_equal(self.lex.pos[:2], (1500, 100))
        self.assertEqual(self.lex.pos[2], self.stand + 500)

    def test_other_figures_land_without_the_player_rule(self):
        self.world_with()
        cmd(self.w, 'CREATEFIGURE', 'NURSEBOT', 'NURSE')
        nurse = self.w.figures['NURSE']
        nurse.set_motion('STAND', True)
        start, good, bottom0 = self.fall(nurse, drop=-500)
        start[:2] = (1500, 100)
        self.w.vertical_response(nurse, start, good, bottom0)
        self.assertFalse(nurse.falling)                                    # (NURSEBOT has no LAND_SOFT motion to play)
        self.assertEqual(nurse.vz, 0)
        self.assertNotIn('LAND_SOFT', nurse.assets.motions)

    def test_unstick_nudges_are_bounded_and_follow_the_byte_pattern(self):
        self.world_with()
        calls = []
        real = self.w.set_pos
        self.w.set_pos = lambda fig, pos, raw=False: calls.append(np.array(pos, float)) or real(fig, pos, raw)
        self.w.null_area_blocked = lambda lo, hi: True                     # never clear: the loop runs to its bound
        p0 = np.array([2000.0, 0.0, self.stand])
        self.lex.pos = p0.copy()
        self.w.unstick(self.lex)
        self.assertEqual(len(calls), 1 + 40 + 1)                           # the first SetPos, 40 nudges, the final SetPos(p0)
        for i, q in enumerate(calls[1:41]):
            expect = p0 + ((i << 8, 0, 0) if i & 3 in (0, 2) else (0, -(i << 8), 0))
            np.testing.assert_array_equal(q, expect)
        np.testing.assert_array_equal(calls[-1], p0)
        np.testing.assert_array_equal(self.lex.pos, p0)
        calls.clear()
        self.w.null_area_blocked = lambda lo, hi: False                   # clear and already on the floor: no nudge at all
        self.w.unstick(self.lex)
        self.assertEqual(len(calls), 1)

    def mantle_world(self, top=1500, flags=2, material=b'METAL'):
        self.world_with(self.box('LEDGE', 1, (1000, -3000, self.FLOOR), (3000, -1000, self.FLOOR + top), flags, material))
        self.lex.set_motion('WALK', True, engine=True)
        self.lex.heading = 7.0
        z0 = self.lex.pos[2]
        self.requested = []
        self.w.request_motion = lambda fig, name, loop: self.requested.append(name)
        return np.array([2000.0, 0.0, z0]), np.array([2000.0, -700.0, z0])

    def bump(self, start, blocked):
        self.lex.pos = blocked.copy()
        self.w.collision_response(self.lex, start, blocked, start)

    def test_a_pit_is_the_support_only_when_the_whole_hull_fits_in_it(self):
        self.world_with(self.box('QPIT', 0, (1000, -2000, self.FLOOR - 2000), (3000, 2000, self.FLOOR + 5000), 0, b'STONE'))
        self.w.select_area(self.lex)
        self.assertEqual(self.w.query_hull(self.lex)[2], self.FLOOR - 2000)    # (2000, 0): inside
        self.lex.pos = np.array([900.0, 0.0, self.stand])                      # straddles the edge: FUN_1058_1a1b's score is positive there
        self.w.select_area(self.lex)
        self.assertEqual(self.w.query_hull(self.lex)[2], self.FLOOR)

    def test_mantle_snaps_the_heading_and_picks_by_height(self):
        for top, name in ((1500, 'MANTLE_3'), (3000, 'MANTLE_6')):
            start, blocked = self.mantle_world(top)
            self.bump(start, blocked)
            self.assertEqual((self.requested, self.lex.heading), ([name], 0.0), top)

    def test_mantle_height_boundaries(self):
        self.mantle_world()
        got = []
        self.w.request_motion = lambda fig, name, loop: got.append(name)
        for h in (0x7ff, 0x800, 0xfff, 0x1000):
            self.w.mantle(self.lex, h)
        self.assertEqual(got, ['MANTLE_3', 'MANTLE_6', 'MANTLE_6', 'MANTLE_9'])

    def test_mantle_needs_flag_walk_request_axis_and_reach(self):
        start, blocked = self.mantle_world(flags=0)
        self.bump(start, blocked)
        self.assertEqual(self.requested, [])                              # collider flag 0x02 clear
        start, blocked = self.mantle_world()
        self.lex.set_motion('WALK', True)                                 # a script's WALK is not the engine's "walk"
        self.bump(start, blocked)
        self.assertEqual(self.requested, [])
        start, blocked = self.mantle_world()
        self.lex.heading = 45.0
        self.bump(start, blocked)
        self.assertEqual(self.requested, [])                              # not within 15 degrees of an axis
        start, blocked = self.mantle_world(top=4500)                      # support more than 0x1000 below the top
        self.bump(start, blocked)
        self.assertEqual(self.requested, [])
        start, blocked = self.mantle_world()
        start[0] = blocked[0] = 1100.0                                    # hull not inside the box shrunk by 0x266
        self.bump(start, blocked)
        self.assertEqual(self.requested, [])

    def test_mantle_axis_snaps_for_each_quadrant(self):
        self.mantle_world()
        plo, phi = [1000, -3000, self.FLOOR], [3000, 3000, self.FLOOR + 1500]
        self.lex.pos = np.array([2000.0, 0.0, self.stand])
        for heading, expect in ((10, 0), (-10, 0), (80, 90), (100, 90), (-80, -90), (170, 180), (-170, 180)):
            self.lex.heading = float(heading)
            self.assertTrue(self.w.mantle_fits(self.lex, plo, phi), heading)
            self.assertEqual(self.lex.heading % 360, float(expect) % 360, heading)
        self.lex.heading = 45.0
        self.assertFalse(self.w.mantle_fits(self.lex, plo, phi))

    def test_bonk_sound_name_is_looked_up_and_silent_when_missing(self):
        names = []
        self.w.sound_index = lambda name: names.append(name) or None
        start, blocked = self.mantle_world()
        self.w.sound_index = lambda name: names.append(name) or None
        self.bump(start, blocked)
        self.assertEqual(names, ['_LEX_BONK_WALK_METAL', '_LEX_BONK_WALK', '_LEX_BONK', '_LEX'])     # 1118:0044 cuts at each `_`
        played = []
        self.w.sound_index = lambda name: 3
        self.w.play_sound = lambda idx, **kw: played.append((idx, kw.get('fig')))
        self.bump(start, blocked)
        self.assertEqual(played, [(3, self.lex)])


class Triggers(unittest.TestCase):
    """IMAG triggers (FUN_1088_51c3 per frame, FUN_1088_50c1 in the mover) on CHAOS's cell door DR_ZAP3."""

    @classmethod
    def setUpClass(cls):
        cls.w = worldmod.World('CHAOS')
        cls.vm = vmmod.VM(cls.w)
        vmmod.load_level(cls.vm, 'CHAOS')

    def setUp(self):
        w, vm = self.w, self.vm
        w.figures.clear()
        w.player_name, w.camera, w.forced_camera, w.candidate = None, None, None, None
        w.script_auto, w.selected = True, False
        w.events.clear()
        w.camera_changes.clear()
        w.set_player_input()
        vm.procs.clear()
        vm.globals.clear()
        cmd(w, 'CREATEFIGURE', 'LEX', 'PLAYER')
        cmd(w, 'GO', 'PLAYLOC')
        self.lex = w.player()
        vm.objects[w.object_key('LEX')] = [100] + [0] * 9                # alive: a dead player fires nothing
        self.zap = next(i for i, t in enumerate(w.triggers) if t['name'] == 'DR_ZAP3')
        self.floor = next(p for p in w.phys if p['name'] == 'CE3')['lo'][2] + self.lex.assets.foot_offset

    def place(self, y):
        self.lex.pos[:] = (-10000, y, self.floor)
        self.lex.heading, self.lex.manual_control = 0, False
        self.lex.set_motion('STAND', True)
        self.w.select_area(self.lex)

    def fired(self):
        calls = []
        self.w.fire_trigger = lambda t, f: calls.append((t['name'], f.name))
        return calls

    def tearDown(self):
        self.w.__dict__.pop('fire_trigger', None)

    def test_area_lists_the_triggers_touching_its_anchor(self):
        names = lambda n: [self.w.triggers[i]['name'] for i in self.w.area_triggers(self.area(n))]
        self.assertEqual(names('DR3'), ['CAM_BLK1', 'DR_ZAP3'])
        self.assertEqual(names('CE3'), [])                         # the cell itself: DR_ZAP3 fires once Lex is in DR3

    def area(self, name):
        return next(i for i, p in enumerate(self.w.phys) if p['name'] == name)

    def test_every_frame_trigger_fires_while_inside_and_clears_outside(self):
        calls = self.fired()
        self.place(-14800)                                        # in the DR3 area, hull inside DR_ZAP3
        for _ in range(3):
            self.w.update_triggers(self.lex)
        self.assertEqual(calls, [('DR_ZAP3', 'LEX')] * 3)          # flag bit 0x01 clear: every frame
        self.assertEqual(self.lex.in_trig[self.zap], 1)
        self.place(-12000)                                        # back in CE3, whose list lacks DR_ZAP3 (FUN_1138_1b8a)
        self.assertEqual(self.lex.in_trig[self.zap], 0)
        self.w.update_triggers(self.lex)
        self.assertEqual(len(calls), 3)

    def test_entry_only_trigger_fires_once_per_entry(self):
        calls = self.fired()
        self.w.triggers[self.zap]['once'] = True
        try:
            self.place(-14800)
            for _ in range(3):
                self.w.update_triggers(self.lex)
            self.place(-12000)
            self.w.update_triggers(self.lex)
            self.place(-14800)
            self.w.update_triggers(self.lex)
        finally:
            self.w.triggers[self.zap]['once'] = False
        self.assertEqual(calls, [('DR_ZAP3', 'LEX')] * 2)

    def test_dead_player_or_collisions_off_fires_nothing(self):
        calls = self.fired()
        self.place(-14800)
        self.vm.objects[self.w.object_key('LEX')][0] = 0
        self.w.update_triggers(self.lex)
        self.vm.objects[self.w.object_key('LEX')][0] = 100
        cmd(self.w, 'COLLISIONS', 'CURFIG', 'OFF', fig='LEX')
        self.w.update_triggers(self.lex)
        self.assertEqual(calls, [])

    def test_block_runs_for_the_player_and_figure_named_blocks_for_others(self):
        self.vm.globals['_zap_interrupt'] = 1                      # DR_ZAP3 returns at once
        self.place(-14800)
        self.w.update_triggers(self.lex)
        self.assertEqual(self.w.events[-1][1], 'DR_ZAP3')
        nurse = types.SimpleNamespace(name='FIRSTBOT')
        self.assertEqual(self.w.trigger_block(self.w.triggers[self.zap], nurse), 'DR_ZAP3_FIRSTBOT')
        self.assertTrue(self.w.trigger_has_block(self.w.triggers[self.zap]))

    def test_live_bars_shock_lex_in_the_doorway(self):
        self.vm.globals['_bars3_on'] = 1
        self.place(-14800)
        run(self.w, 2)
        self.assertIn('DR_ZAP3', [b for _, b in self.w.events])
        self.assertTrue(self.lex.motion.startswith('SHOCK_'))

    def test_camera_trigger_forces_its_camera_unless_locked(self):
        blk6 = next(t for t in self.w.triggers if t['name'] == 'CAM_BLK6')
        self.place(-12000)
        self.w.camera = 'CE33'
        self.w.fire_trigger(blk6, self.lex)
        self.w.update_camera()
        self.assertEqual(self.w.current_camera(), 'BLK6')
        self.assertEqual(self.w.camera_changes[-1][3], 'trigger forces BLK6')
        self.assertIsNone(self.w.forced_camera)
        cmd(self.w, 'CAMERA', 'CE33')                              # locked: the request is dropped
        self.w.fire_trigger(blk6, self.lex)
        self.w.update_camera()
        self.assertEqual(self.w.current_camera(), 'CE33')
        self.assertIsNone(self.w.forced_camera)

    def test_mover_stops_on_entering_a_trigger_with_a_block(self):
        self.place(-12000)
        self.vm.globals['_dr3_space'] = 0
        self.lex.in_trig = bytearray(len(self.w.triggers))
        t = self.w.triggers[self.zap]
        # 6 steps of -833: the third (-14499) is still in CE3, the fourth enters DR3, whose DR_ZAP3 has a block
        self.assertFalse(self.w.figure_move(self.lex, np.array([0.0, -5000.0])))
        self.assertEqual((self.lex.pos[1], self.lex.area), (-12000 - 4 * 833, self.area('DR3')))
        lo, hi, _ = self.w.query_hull(self.lex)
        self.assertTrue(self.w.boxes_touch(lo, hi, t['lo'], t['hi']))
        stop = self.lex.pos[1]
        self.place(-12000)
        self.lex.in_trig[self.zap] = 1                             # already inside: no stop
        self.w.figure_move(self.lex, np.array([0.0, -5000.0]))
        self.assertLess(self.lex.pos[1], stop)

    def test_amintrigger_tests_the_figure_hull(self):
        self.place(-14800)
        p = proc('LEX')
        self.assertEqual(self.w.call('func', 'AMINTRIGGER', ['CURFIG', 'DR_ZAP3'], p), 1)
        self.place(-12000)
        self.assertEqual(self.w.call('func', 'AMINTRIGGER', ['CURFIG', 'DR_ZAP3'], p), 0)
        self.assertEqual(self.w.call('func', 'AMINTRIGGER', ['LEX', 'NO_SUCH'], p), 0)


def put_player(w, x, y, z=-5000):
    """Place PLAYER with its origin at (x, y, z)."""
    w.points['TESTPT'] = np.array([x, y, z], float)
    cmd(w, 'GO', 'TESTPT')
    w.figures['PLAYER'].pos[:] = (x, y, z)


def accepting(w, wp, up=2300):
    P = w.points[wp] + np.array([0, 0, up])
    out = {n: round(d) for n, c in w.cameras.items() for ok, d in [worldmod.accepts(c, P)] if ok}
    return out


class AutoCamera(unittest.TestCase):
    def test_acceptance_on_landpad_waypoints(self):
        w = make_world()
        self.assertEqual(list(accepting(w, 'LEX_POS')), ['ELV2'])
        a = accepting(w, 'LEX_POS2')
        self.assertEqual(sorted(a), ['HFR1', 'HFR3', 'HFR6'])
        a = accepting(w, 'AIR_POS')
        self.assertEqual(sorted(a), ['HFR2', 'HFR4'])
        self.assertEqual(list(accepting(w, 'AIR_POSX')), ['HFR5'])

    def test_distance_is_the_engines_approximate_length(self):
        """1110:1a95 and the ranking of 1130:0fa3 take FUN_1210_0f9b of P - eye, not the Euclidean length."""
        w = make_world()
        P = w.points['LEX_POS2'] + np.array([0, 0, 2300])
        cam = w.cameras['HFR3']
        ok, d = worldmod.accepts(cam, P)
        self.assertTrue(ok)
        self.assertEqual(d, worldmod.approx_length(P - cam['pos']))
        self.assertNotAlmostEqual(d, float(np.linalg.norm(P - cam['pos'])), delta=20)     # the two metrics differ here
        near = dict(cam, extra=(cam['extra'][0], 0, d - 1, 0, cam['extra'][4], cam['extra'][5]))    # FARMARK just under d
        self.assertFalse(worldmod.accepts(near, P)[0])
        far = dict(cam, extra=(cam['extra'][0], 0, d, 0, cam['extra'][4], cam['extra'][5]))
        self.assertTrue(worldmod.accepts(far, P)[0])

    def test_acceptance_range_and_angle(self):
        cam = {'pos': np.zeros(3), 'R': np.array([[1, 0, 0], [0, 1, 0], [0, 0, 1.0]]),
               'extra': (38, 0, 1000, 100, 0, 0)}               # looks along +y
        acc = lambda x, y: worldmod.accepts(cam, np.array([x, y, 0.0]))[0]
        self.assertTrue(acc(0, 500))
        self.assertFalse(acc(0, 50))                             # nearer than NEARMARK
        self.assertFalse(acc(0, 1500))                           # beyond FARMARK
        self.assertTrue(acc(300, 500))                           # ~31 deg off axis, inside +-38
        self.assertFalse(acc(500, 500))                          # 45 deg
        self.assertTrue(acc(-300, 500))

    def test_camera_name_locks_and_unlock_resumes(self):
        w = make_world()
        vmmod.VM(w)
        put_player(w, *(w.points['LEX_POS'][:2]), -5051)         # only ELV2 accepts here
        cmd(w, 'CAMERA', 'HFR3')
        self.assertEqual(w.current_camera(), 'HFR3')
        self.assertFalse(w.script_auto)
        for _ in range(5):
            w.step()
        self.assertEqual(w.current_camera(), 'HFR3')             # HFR3 rejects the player but stays locked
        cmd(w, 'CAMERA', 'UNLOCK')
        self.assertTrue(w.script_auto)
        w.step()
        self.assertEqual(w.current_camera(), 'ELV2')             # first selection switches at once
        self.assertEqual(w.camera_changes[-1][1:3], ('HFR3', 'ELV2'))

    def test_unlock_keeps_current_while_accepting(self):
        w = make_world()
        vmmod.VM(w)
        put_player(w, *(w.points['LEX_POS2'][:2]), -5051)        # HFR3, HFR6, HFR1 accept
        cmd(w, 'CAMERA', 'HFR1')
        cmd(w, 'CAMERA', 'UNLOCK')
        w.step()
        w.step()
        self.assertEqual(w.current_camera(), 'HFR1')

    def test_camera_show_at_load_log_only(self):
        w = make_world()
        vmmod.VM(w)
        cmd(w, 'CAMERA', 'HFR3')
        for args in (('SHOW', 'TITLE'), ('AT', 1, 2, 3), ('HFR6', 'LOAD'), ('HFR6', 'UNLOAD')):
            cmd(w, 'CAMERA', *args)
        self.assertEqual(w.current_camera(), 'HFR3')
        self.assertFalse(w.script_auto)                          # still locked
        self.assertEqual(len(w.warnings), 3)                     # CAMERA HFR6 LOAD is silent (FUN_1110_024a, the resource cache)
        self.assertEqual(sum(1 for e in w.log if e[3] == 'CAMERA'), 5)

    def test_debounce_and_keep_current(self):
        w = make_world()
        vmmod.VM(w)
        w.selected = True                                        # not the first selection
        put_player(w, *(w.points['LEX_POS'][:2]), -5051)
        w.camera = 'HFR5'                                        # does not accept LEX_POS
        w.step()
        self.assertEqual(w.current_camera(), 'HFR5')             # candidate seen once: not yet
        w.step()
        self.assertEqual(w.current_camera(), 'ELV2')
        put_player(w, 0, 0, 0)                                   # accepted by no camera: keep
        w.step()
        self.assertEqual(w.current_camera(), 'ELV2')

    def test_disable_and_follow(self):
        w = make_world()
        cmd(w, 'CAMERAAUTOACTIVATE', 'ELV2', 'OFF')
        self.assertIn('ELV2', w.disabled)
        vmmod.VM(w)
        put_player(w, *(w.points['LEX_POS'][:2]), -5051)
        w.camera = 'HFR5'
        w.step()
        self.assertEqual(w.current_camera(), 'HFR5')             # only ELV2 would accept, but it is disabled
        cmd(w, 'CAMERAAUTOACTIVATE', 'ELV2', 'ON')
        self.assertNotIn('ELV2', w.disabled)
        cmd(w, 'CAMERAFOLLOW', 'AIRMECHO')
        self.assertEqual(w.follow, 'AIRMECHO')

    def test_disabled_auto_camera_and_unplaced(self):
        w = make_world()
        w.step()
        self.assertEqual(w.camera_changes, [])
        w.auto_camera = False
        put_player(w, *(w.points['LEX_POS'][:2]), -5051)
        w.step()
        self.assertIsNone(w.camera)


SPIN = """{ SPIN
	:A
	WAIT 5
	JUMP A
}
{ HFR6_LOAD
\t_door_frame = 9
}
{ HFR3_UNLOAD
\t_door_frame = 4
}
"""


def beach_world():
    w = worldmod.World('BEACH')
    vm = vmmod.VM(w)
    vmmod.load_level(vm, 'BEACH')
    cmd(w, 'CREATEFIGURE', 'LEX', 'PLAYER')
    return w, vm


class LevelChange(unittest.TestCase):
    def test_createfigure_unplaced_and_idempotent(self):
        w = worldmod.World('BEACH')
        vmmod.VM(w)
        cmd(w, 'CREATEFIGURE', 'LEX', 'PLAYER')
        f = w.player()
        self.assertEqual((f.type, f.pos, f.name), ('LEX', None, 'LEX'))
        self.assertIs(w.resolve('PLAYER') and w.player(), f)         # PLAYER is a keyword for the flagged figure
        cmd(w, 'CREATEFIGURE', 'LEX', 'PLAYER')
        self.assertIs(w.player(), f)
        self.assertEqual(w.call('func', 'SETCURRENTFIGURE', ['PLAYER'], proc()), 1)
        self.assertEqual(w.call('func', 'SETCURRENTFIGURE', ['LEX'], proc()), 1)
        self.assertEqual(w.call('func', 'SETCURRENTFIGURE', ['NOBODY'], proc()), 0)

    def test_initgame_state_dir(self):
        w = worldmod.World('CHAOS', state_dir=worldmod.INITGAME)
        self.assertTrue(w.level_path.startswith(worldmod.INITGAME))
        self.assertIn('PLAYLOC', w.points)

    def test_loadlevel_kills_places_player_and_fires_load(self):
        w, vm = beach_world()
        with tempfile.NamedTemporaryFile('w', suffix='.scr', delete=False) as t:
            t.write(SPIN.replace('\\t', '\t'))
        try:
            vm.load(t.name)
        finally:
            os.unlink(t.name)
        spin = vm.spawn('SPIN')
        self.assertIn(spin.handle, vm.procs)
        vm.fire('TO_TPL')                                       # LOADLEVEL TUNROOM FROM_BCH
        self.assertEqual(w.level, 'TUNROOM')
        self.assertNotIn(spin.handle, vm.procs)                 # other processes killed
        self.assertNotIn('SPIN', vm.blocks)                     # old scripts replaced
        self.assertIn('TUNROOM_LOAD', vm.blocks)
        self.assertNotIn('TO_TPL', vm.blocks)
        p = w.player()
        wp = w.points['FROM_BCH']
        np.testing.assert_allclose(p.pos[:2], wp[:2])
        self.assertAlmostEqual(p.pos[2], wp[2] + p.assets.foot_offset)
        self.assertEqual([e[1] for e in w.events if e[1].endswith('_LOAD')][0], 'TUNROOM_LOAD')
        self.assertEqual(w.level_loads[-1][1:3], ('TUNROOM', 'FROM_BCH'))
        self.assertIn(w.current_camera(), w.cameras)            # cameras reloaded for the new level
        self.assertNotIn('HFR3', w.cameras)

    def test_loadlevel_back_to_beach(self):
        w, vm = beach_world()
        vm.fire('TO_TPL')
        vm.fire('TO_BCH')
        self.assertEqual(w.level, 'BEACH')
        np.testing.assert_allclose(w.player().pos[:2], w.points['FROM_TPL'][:2])

    def test_loadlevel_missing_arrival_keeps_player(self):
        w, vm = beach_world()
        w.player().pos = np.array([1.0, 2.0, 3.0])
        w.call('stmt', 'LOADLEVEL', ['TUNROOM'], proc())        # one argument: engine error
        np.testing.assert_allclose(w.player().pos, [1, 2, 3])
        self.assertTrue(any('no arrival' in m for m in w.warnings))
        w.call('stmt', 'LOADLEVEL', ['TUNROOM', 'NOWHERE_X'], proc())
        np.testing.assert_allclose(w.player().pos, [1, 2, 3])
        self.assertTrue(any('NOWHERE_X' in m for m in w.warnings))

    def _load_snippet(self, vm, text):
        with tempfile.NamedTemporaryFile('w', suffix='.scr', delete=False) as t:
            t.write(text)
        try:
            vm.load(t.name)
        finally:
            os.unlink(t.name)

    def test_level_owned_caller_ends_after_loadlevel(self):
        w, vm = beach_world()
        self._load_snippet(vm, '{ LLOWN\n\tLOADLEVEL TUNROOM FROM_BCH\n\t_door_frame = 77\n}\n')
        vm.globals['_door_frame'] = 0
        vm.fire('LLOWN')
        self.assertEqual(w.level, 'TUNROOM')
        self.assertEqual(vm.globals['_door_frame'], 0)          # statements after LOADLEVEL never run
        self.assertNotIn(1, [p.handle for p in vm.procs.values() if p.block.name == 'LLOWN'])

    def test_call_chain_survives_loadlevel_and_other_global_processes_do_not(self):
        w, vm = beach_world()
        self._load_snippet(vm, '{ LLBOOT\n\tCALL LLSUB\n\t_door_frame = 78\n}\n{ LLSUB\n\tLOADLEVEL TUNROOM FROM_BCH\n\t_door_frame = 77\n}\n'
                               '{ LLBYST\n\tWAIT 100\n\t_door_frame = 99\n}\n')
        vm.globals['_door_frame'] = 0
        bystander = vm.fire('LLBYST', 'global')
        vm.fire('LLBOOT', 'global')
        self.assertEqual(w.level, 'TUNROOM')
        self.assertEqual(vm.globals['_door_frame'], 78)         # the caller's CALL chain (+0x71 links) survives, even when LOADLEVEL runs in the child's first slice
        self.assertNotIn(bystander, vm.procs)                   # 10b0:13fb has no exemption for the boot chain
        for _ in range(200):
            vm.tick_once()
        self.assertEqual(vm.globals['_door_frame'], 78)         # the killed process never ran its tail

    def test_loadlevel_keeps_only_the_named_sound_handle(self):
        w, vm = beach_world()
        keep = w.play_sound(0, 255, loop=True)
        other = w.play_sound(1, 255, loop=True)
        short = w.play_sound(2, 255, loop=False)
        sub = w.subtitle(['', 0x75, 'hello'])
        self._load_snippet(vm, '{ LLSND\n\tLOADLEVEL TUNROOM FROM_BCH %d\n}\n' % keep)
        w.sound_stops.clear()
        tick = vm.tick
        vm.fire('LLSND')
        self.assertEqual(w.level, 'TUNROOM')
        self.assertIn(keep, vm.procs)                           # ISHANDLEPLAYING 1
        self.assertNotIn(keep, [h for _, h in w.sound_stops])
        stopped = {h: t for t, h in w.sound_stops}
        self.assertEqual(stopped, {other: tick, short: tick})   # every other voice ends in the mix at the load tick (FUN_1028_12d2)
        self.assertNotIn(sub, vm.procs)                         # a subtitle is no voice: the kill walk ends it
        self._load_snippet(vm, '{ LLNOSND\n\tLOADLEVEL BEACH FROM_TUN\n}\n')
        vm.fire('LLNOSND')                                      # without a numeric argument nothing is kept
        self.assertIn(keep, [h for _, h in w.sound_stops])

    def test_process_from_a_timeline_waits_for_the_scheduler(self):
        w, vm = beach_world()
        self._load_snippet(vm, '{ PRCCHILD\n\t_door_frame = 5\n}\n{ PRCROUTINE\n\tPROCESS PRCCHILD\n\t_door_frame = _door_frame + 100\n}\n'
                               '[ PRCTIMELINE\n00:00 PROCESS PRCCHILD\n00:00 _door_frame = _door_frame + 100\n]\n')
        vm.globals['_door_frame'] = 0
        vm.fire('PRCROUTINE')
        self.assertEqual(vm.globals['_door_frame'], 105)        # a `{` caller runs the child's first slice at once (10c0:37e9)
        vm.globals['_door_frame'] = 0
        vm.fire('PRCTIMELINE')
        self.assertEqual(vm.globals['_door_frame'], 100)        # a `[` caller does not
        vm.tick_once()
        self.assertEqual(vm.globals['_door_frame'], 5)          # INFERRED: the child first runs in the next tick's walk

    def test_new_game_boot_reaches_chaos_and_runs_goodmorninglex(self):
        import play
        import scenarios
        w = worldmod.World('TITLE', state_dir=worldmod.INITGAME)
        vm = vmmod.VM(w)
        vmmod.load_level(vm, 'TITLE')
        vm.fire('GAME', 'global')
        after_dialog = None
        while not w.level_loads:                                 # the intro plays first; the old port loaded CHAOS in tick 26
            vm.tick_once()
            w.step()
            if w.choose_default_difficulty() is not None:
                after_dialog = play.to_rgb(w)
        # CAMERA SHOW TITLE (10d0:115c) put the screen on the TITLE picture: it shows, undimmed, from the dialog's close until LOADLEVEL CHAOS,
        # and GOODMORNINGLEX's FADE HIDE turns it black in the same tick. Twin of OptionsTests.openingDifficultyDialogSets...
        title = worldmod.World.shown_picture_rgb(types.SimpleNamespace(shown_picture='TITLE'))
        self.assertTrue(np.array_equal(after_dialog, title))                  # the default gamma 30 is the identity
        self.assertIsNone(w.shown_picture)
        for _ in range(scenarios.old_ticks(40)):
            vm.tick_once()
            w.step()
            w.choose_default_difficulty()
        self.assertEqual([l[1:3] for l in w.level_loads], [('CHAOS', 'PLAYLOC')])
        self.assertEqual(w.current_camera(), 'CE31')            # set by GOODMORNINGLEX, which START's CALL reached
        self.assertIn('CHAOS_LOAD', [e[1] for e in w.events])
        np.testing.assert_allclose(w.player().pos[:2], w.points['PLAYLOC'][:2])

    def test_a_show_picture_replaces_the_room_on_screen(self):
        """CAMERA SHOW <cam> switches the screen to the picture camera. WARHEAD's RTRW is one colour (121) over the whole screen: the white
        flash BLAST_LEX shows until KILLLEX's STITLE. Twin of OptionsTests.aShowPictureReplacesTheRoomOnScreen."""
        import play
        import test_items
        w, vm, lex = test_items.make()
        room = play.to_rgb(w)
        w.call('stmt', 'CAMERA', ['SHOW', 'RTRW'], test_items.stub())
        self.assertEqual(play.to_rgb(w).max(), 0)                            # the cut to a very different palette: one black frame (10e8:1dcc)
        flash = play.to_rgb(w)
        self.assertTrue(np.array_equal(flash, w.shown_picture_rgb()))
        self.assertEqual(len(np.unique(flash.reshape(-1, 3), axis=0)), 1)
        self.assertFalse(np.array_equal(flash, room))
        w.shown_picture = None
        play.to_rgb(w)
        self.assertTrue(np.array_equal(play.to_rgb(w), room))

    def test_camera_load_unload_events(self):
        w = worldmod.World('LANDPAD')
        vm = vmmod.VM(w)
        with tempfile.NamedTemporaryFile('w', suffix='.scr', delete=False) as t:
            t.write(SPIN.replace('\\t', '\t'))
        try:
            vm.load(t.name)
        finally:
            os.unlink(t.name)
        cmd(w, 'CAMERA', 'HFR3')
        vm.globals['_door_frame'] = 1
        cmd(w, 'CAMERA', 'HFR6')                                # HFR6_LOAD then HFR3_UNLOAD (1130:03b0-044f)
        self.assertEqual([e[1] for e in w.events], ['HFR6_LOAD', 'HFR3_UNLOAD'])
        self.assertEqual(vm.globals['_door_frame'], 4)          # UNLOAD ran after LOAD
        cmd(w, 'CAMERA', 'HFR6')                                # no change, no events
        self.assertEqual(len(w.events), 2)


class Motions(unittest.TestCase):
    def setUp(self):
        self.w = worldmod.World('LANDPAD')
        self.vm = vmmod.VM(self.w)
        cmd(self.w, 'CREATEFIGURE', 'LEX', 'PLAYER')
        cmd(self.w, 'GO', 'LEX_POS')                           # PLAYER keyword -> the LEX figure
        self.lex = self.w.figures['LEX']
        # test scaffolding: these tests are about GO / MOTION semantics; without MARCHOUTAIRMECHO's script DR9 keeps its closed
        # (solid) file state, which blocks the walk LEX_POS -> LEX_POS2 now that collisions are on
        self.lex.no_collide = True

    def load(self, text):
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

    def test_stopmotion_holds_the_pose_without_root_travel(self):
        cmd(self.w, 'MOTION', 'WALK', 'CONTINUE')
        self.run_ticks(20)
        idx, pose, pos = self.lex.idx, self.lex.frames[self.lex.idx], self.lex.pos.copy()
        cmd(self.w, 'STOPMOTION')
        self.assertEqual(self.lex.frames, [pose])               # FUN_1040_0c07: the current pose is kept
        self.run_ticks(30)
        np.testing.assert_array_equal(self.lex.pos[:2], pos[:2])
        self.assertEqual(self.w.call('func', 'ISMYMOTION', ['WALK'], proc()), 0)
        cmd(self.w, 'MOTION', 'STAND', 'CONTINUE')                   # a new motion ends the hold
        self.assertEqual(self.lex.motion, 'STAND')
        self.assertFalse(self.lex.frozen)

    def test_stopmotion_bakes_a_turning_motions_yaw_once(self):
        cmd(self.w, 'MOTION', 'TURN_LEFT', 'CONTINUE')
        self.lex.idx = len(self.lex.frames) // 2
        yaw = self.lex.frames[self.lex.idx][2][0][2] - self.lex.frames[0][2][0][2]
        self.assertNotEqual(yaw, 0)
        heading = self.lex.heading
        cmd(self.w, 'STOPMOTION')
        self.assertAlmostEqual(self.lex.heading, heading - yaw * 45 / 32)
        cmd(self.w, 'MOTION', 'STAND', 'CONTINUE')                   # the held pose carries no yaw left to bake
        self.assertAlmostEqual(self.lex.heading, heading - yaw * 45 / 32)

    def test_player_is_keyword_for_flagged_figure(self):
        w = self.w
        self.assertEqual(w.player_name, 'LEX')
        self.assertNotIn('PLAYER', w.figures)
        self.assertIsNotNone(self.lex.pos)                      # GO PLAYER-keyword proc placed LEX
        self.assertIs(w.figure('PLAYER'), self.lex)
        self.assertEqual(w.call('func', 'SETCURRENTFIGURE', ['LEX'], proc()), 1)
        self.assertIsNone(self.lex.view_cams)
        w.follow = 'PLAYER'
        self.assertIs(w.followed_pos(), self.lex.pos)

    def test_plain_motion_blocks_until_it_finishes(self):
        self.load('{ MBLK\n\tSETCURRENTFIGURE PLAYER\n\tMOTION WAKE_UP\n\t_door_frame = 5\n}\n')
        self.vm.globals['_door_frame'] = 0
        self.vm.fire('MBLK')
        self.assertEqual(self.lex.motion, 'WAKE_UP')
        n = len(self.lex.frames)
        self.run_ticks(ticks_for(self.lex, n - 1) - 4)
        self.assertEqual(self.vm.globals['_door_frame'], 0)     # still playing: caller blocked
        self.run_ticks(12)
        self.assertEqual(self.vm.globals['_door_frame'], 5)

    def test_continue_does_not_block_but_freeze_does(self):
        """10d0:6083: only CONTINUE skips the wait. FREEZE clears just the idle-fallback bit (10d0:5e8b): the motion plays out, the
        caller waits for it, and the last pose is held with no STAND fallback until the next MOTION."""
        self.load('{ MNB\n\tSETCURRENTFIGURE PLAYER\n\tMOTION WALK CONTINUE\n\t_door_frame = 5\n'
                  '\tMOTION WAKE_UP FREEZE\n\t_door_frame = 6\n}\n')
        self.vm.globals['_door_frame'] = 0
        self.vm.fire('MNB')
        self.assertEqual(self.vm.globals['_door_frame'], 5)     # WALK CONTINUE returned at once, WAKE_UP FREEZE blocks
        self.assertEqual((self.lex.motion, self.lex.frozen, self.lex.no_idle), ('WAKE_UP', False, True))
        self.run_ticks(ticks_for(self.lex, len(self.lex.frames) - 1) - 4)
        self.assertEqual(self.vm.globals['_door_frame'], 5)     # still playing
        self.run_ticks(12)
        self.assertEqual(self.vm.globals['_door_frame'], 6)
        self.assertEqual((self.lex.motion, self.lex.finished, self.lex.idx), ('WAKE_UP', True, len(self.lex.frames) - 1))
        self.run_ticks(60)
        self.assertEqual((self.lex.motion, self.lex.idx), ('WAKE_UP', len(self.lex.frames) - 1))   # the last pose is held, no idle fallback
        cmd(self.w, 'MOTION', 'STAND', 'CONTINUE')              # next MOTION ends the hold
        self.assertFalse(self.lex.no_idle)
        self.assertTrue(self.lex.loop)

    def test_freeze_with_continue_plays_without_waiting(self):
        self.load('{ MFC\n\tSETCURRENTFIGURE PLAYER\n\tMOTION WAKE_UP FREEZE CONTINUE\n\t_door_frame = 6\n}\n')
        self.vm.globals['_door_frame'] = 0
        self.vm.fire('MFC')
        self.assertEqual(self.vm.globals['_door_frame'], 6)
        self.assertEqual((self.lex.motion, self.lex.no_idle), ('WAKE_UP', True))
        self.run_ticks(10)
        self.assertGreater(self.lex.idx, 0)                     # it animates (the old FREEZE held the start frame)

    def test_continue_noncycle_does_not_block(self):
        p = proc()
        self.w.cmd_motion(self.lex, 'DROPSHIP_WINS', ['CONTINUE'], p)
        self.assertFalse(self.lex.loop)
        self.assertFalse(hasattr(p, 'wait_pred'))

    def test_new_motion_ends_the_wait(self):
        self.load('{ MRPL\n\tSETCURRENTFIGURE PLAYER\n\tMOTION WAKE_UP\n\t_door_frame = 5\n}\n')
        self.vm.globals['_door_frame'] = 0
        self.vm.fire('MRPL')
        self.run_ticks(4)
        cmd(self.w, 'MOTION', 'STAND', 'CONTINUE')
        self.run_ticks(2)
        self.assertEqual(self.vm.globals['_door_frame'], 5)

    def test_blocking_motion_during_go_starts_after_arrival(self):
        cmd(self.w, 'GO', 'LEX_POS2', 'WALK')
        self.load('{ MGO\n\tSETCURRENTFIGURE PLAYER\n\tMOTION WAKE_UP_HEAD\n\t_door_frame = 5\n}\n')
        self.vm.globals['_door_frame'] = 0
        self.vm.fire('MGO')
        self.assertEqual(self.lex.motion, 'WALK')
        self.run_ticks(400)                                     # arrival, then the motion plays, then the caller resumes
        self.assertEqual(self.lex.motion, 'STAND')
        self.assertEqual(self.vm.globals['_door_frame'], 5)

    def test_walk_go_blocks_script_until_arrival(self):
        self.load('{ GOBLK\n\tSETCURRENTFIGURE PLAYER\n\tGO LEX_POS2 WALK\n\t_door_frame = 5\n}\n')
        self.vm.globals['_door_frame'] = 0
        self.vm.fire('GOBLK')
        self.assertTrue(self.lex.is_moving())
        self.assertEqual(self.vm.globals['_door_frame'], 0)
        self.run_ticks(20)
        self.assertEqual(self.vm.globals['_door_frame'], 0)
        while self.lex.is_moving():
            self.run_ticks(1)
        self.assertEqual(self.vm.globals['_door_frame'], 0)
        self.run_ticks(1)
        self.assertEqual(self.vm.globals['_door_frame'], 5)

    def test_snap_go_does_not_block_script(self):
        self.load('{ GOSNAP\n\tSETCURRENTFIGURE PLAYER\n\tGO LEX_POS\n\t_door_frame = 5\n}\n')
        self.vm.globals['_door_frame'] = 0
        self.vm.fire('GOSNAP')
        self.assertEqual(self.vm.globals['_door_frame'], 5)

    def test_collisions_after_walk_go_are_not_enabled_early(self):
        self.load('{ GOCOLL\n\tSETCURRENTFIGURE PLAYER\n\tCOLLISIONS CURFIG OFF\n\tGO LEX_POS2 WALK\n\tCOLLISIONS CURFIG ON\n}\n')
        cmd(self.w, 'COLLISIONS', 'CURFIG', 'ON', fig='LEX')
        self.vm.fire('GOCOLL')
        self.assertFalse(self.lex.collisions)
        self.run_ticks(20)
        self.assertTrue(self.lex.is_moving())
        self.assertFalse(self.lex.collisions)
        while self.lex.is_moving():
            self.run_ticks(1)
        self.assertFalse(self.lex.collisions)
        self.run_ticks(1)
        self.assertTrue(self.lex.collisions)

    def test_replacing_walk_go_releases_its_wait(self):
        self.load('{ GOREPL\n\tSETCURRENTFIGURE PLAYER\n\tGO LEX_POS2 WALK\n\t_door_frame = 5\n}\n')
        self.vm.globals['_door_frame'] = 0
        self.vm.fire('GOREPL')
        self.assertTrue(self.lex.is_moving())
        cmd(self.w, 'GO', 'LEX_POS')                         # snap GO aborts the scripted walk
        self.assertFalse(self.lex.is_moving())
        self.run_ticks(2)
        self.assertEqual(self.vm.globals['_door_frame'], 5)

    def test_snaptopose(self):
        cmd(self.w, 'SNAPTOPOSE', 'WAKE_UP', 3, 'FREEZE')
        self.assertEqual((self.lex.motion, self.lex.idx, self.lex.frozen), ('WAKE_UP', 3, True))
        cmd(self.w, 'SNAPTOPOSE', 'WAKE_UP', 5)
        self.assertEqual((self.lex.idx, self.lex.frozen), (5, False))
        self.run_ticks(ticks_for(self.lex, 1))
        self.assertEqual(self.lex.idx, 6)

    def test_render_pose_interpolates_interior_frames_and_holds_loop_end(self):
        cmd(self.w, 'MOTION', 'WALK', 'CONTINUE')
        duration = self.w.motion_duration(self.lex)
        self.lex.idx, self.lex.phase = 1, duration / 2
        middle = self.w.posed(self.lex)
        p0, r0, limbs0 = self.lex.frames[1]
        p1, _, limbs1 = self.lex.frames[2]
        halfway = ((0, 0, math.trunc((p0[2] + p1[2]) / 2)), r0,
                   [tuple(math.trunc((a + b) / 2) for a, b in zip(a0, a1)) for a0, a1 in zip(limbs0, limbs1)])
        expected = worldmod.place(np.array(worldmod.salsa.pose_vertices(
            self.lex.assets.mesh.verts, self.lex.assets.links, self.lex.assets.skel, halfway)),
            self.lex.pos + self.w.subframe_root(self.lex, 1, 0.5), -self.lex.heading)   # root x/y blended too (FUN_1088_0d63)
        np.testing.assert_allclose(middle, expected)
        self.assertGreater(np.hypot(*self.w.subframe_root(self.lex, 1, 0.5)[:2]), 0)
        self.assertFalse(np.array_equal(middle, self.lex.assets.pose(self.lex.frames, 1)))

        self.lex.idx, self.lex.phase = len(self.lex.frames) - 1, duration / 2
        np.testing.assert_array_equal(self.w.posed(self.lex), worldmod.place(
            self.lex.assets.pose(self.lex.frames, self.lex.idx), self.lex.pos, -self.lex.heading))

    def test_motion_predicates(self):
        w = self.w
        cmd(w, 'MOTION', 'WAKE_UP', 'FREEZE')
        f = lambda n, a: w.call('func', n, [a], proc())
        self.assertEqual(f('ISMYMOTION', 'wake_up'), 1)
        self.assertEqual(f('ISMYMOTION', 'STAND'), 0)
        self.assertEqual(f('ISPLAYERSMOTION', 'WAKE_UP'), 1)
        self.assertEqual(f('MOTIONEXISTS', 'OUT_OF_BED'), 1)
        self.assertEqual(f('MOTIONEXISTS', 'NO_SUCH'), 0)

    def test_continue_loops_only_cycles(self):
        w = self.w
        cmd(w, 'MOTION', 'STAND', 'CONTINUE')
        self.assertTrue(self.lex.loop)                          # STAND returns to its first pose
        cmd(w, 'MOTION', 'OUT_OF_BED', 'CONTINUE')
        self.assertFalse(self.lex.loop)                         # not a cycle: plays once
        self.run_ticks(ticks_for(self.lex, len(self.lex.frames)) + 4)
        self.assertEqual(w.call('func', 'ISMYMOTION', ['OUT_OF_BED'], proc()), 0)   # finished one-shot is not "my motion"


class MotionTiming(unittest.TestCase):
    """FUN_1098_0088 / FUN_1088_1854: a frame lasts MY_SPEED x the motion's frame time (header byte 76) in 1/256 ticks of the
    60 Hz clock; FUN_10a0_1c83 adds a turning motion's root yaw to the heading."""

    def setUp(self):
        self.w = make_world()
        self.vm = vmmod.VM(self.w)                                             # the difficulty level is a VM global
        cmd(self.w, 'CREATEFIGURE', 'NURSEBOT', 'FIRSTBOT')
        self.bot = self.w.figures['FIRSTBOT']
        self.bot.pos = np.array([0.0, 0.0, 0.0])

    def tearDown(self):
        self.w.vm = None                                                       # the test world is shared

    def test_frame_duration_is_my_speed_times_frame_time_adjusted_by_difficulty(self):
        self.assertEqual(self.bot.speed, 384)                                  # FIRSTBOT / NURSEBOT MY_SPEED
        # FUN_1098_0088: other figures get + 0x80 at level 0 and - level << 6 above it (live, Medium: ATK_M7 704,
        # ACTIVATE 3776, ATK_STAND 1472 at model+0x102)
        for level, adjust in ((0, 0x80), (1, -64), (2, -128)):
            self.w.vm.globals['_difficulty_level'] = level
            for name, frame_time in (('ACTIVATE', 10), ('ATK_M7', 2), ('ATK_STAND', 4)):
                self.bot.set_motion(name, True)
                self.assertEqual(self.w.motion_duration(self.bot), 384 * frame_time + adjust)
        self.w.vm.globals['_difficulty_level'] = 1
        self.bot.set_motion('ATK_M7', True)
        run(self.w, 4)                                                         # 4 x 512 / 704: two frames
        self.assertEqual(self.bot.idx, 2)

    def test_player_repeating_an_attack_slows_it(self):
        cmd(self.w, 'CREATEFIGURE', 'LEX', 'PLAYER')
        lex = self.w.player()
        self.w.vm.globals['_difficulty_level'] = 2
        base = lex.speed * lex.assets.motion_info['ATK_H1'][0]
        lex.set_motion('ATK_H1', False)
        self.assertEqual(self.w.motion_duration(lex), base)                    # first use: no difficulty adjustment
        lex.set_motion('ATK_H1', False)
        self.assertEqual(self.w.motion_duration(lex), base + 1 * 64 * 2 * 16)  # repeat 1: + count * 64 * level * 16
        lex.set_motion('ATK_H1', False)
        self.assertEqual(self.w.motion_duration(lex), base + 2 * 64 * 2 * 16)
        lex.set_motion('STAND', True)                                          # any other motion clears the count
        self.w.motion_duration(lex)
        lex.set_motion('ATK_H1', False)
        self.assertEqual(self.w.motion_duration(lex), base)

    def test_turning_motion_adds_its_root_yaw_each_cycle(self):
        bot = self.bot
        bot.heading = 150.0
        bot.set_motion('ATK_M7', True)
        self.assertTrue(bot.turning())                                         # flag bit 0x01; ATK_STAND is not
        n = len(bot.frames)
        run(self.w, ticks_for(bot, n, self.w))
        self.assertEqual(bot.idx, 0)
        self.assertEqual(bot.heading, 150.0 + 7 * 45 / 32)                     # root yaw 0 -> -7: 9.84 degrees right
        run(self.w, ticks_for(bot, 3, self.w))
        yaw = bot.frames[bot.idx][2][0][2]
        bot.set_motion('ATK_STAND', True)                                      # a replaced turning motion keeps its yaw
        self.assertEqual(bot.heading, 150.0 + (7 - yaw) * 45 / 32)
        bot.set_motion('STAND', True)
        self.assertEqual(bot.heading, 150.0 + (7 - yaw) * 45 / 32)


class NurseActivation(unittest.TestCase):
    def test_nurse_curves_toward_the_bed_like_the_original(self):
        # DOSBox-X live (2026-10-16/17, dosbox_live.py and parity.py nurse_activation): ACTIVATE, then ATK_M7 for WAIT 60
        # turning 9.84 degrees a cycle, ending at (-11380, -10462) heading 213.8 (other runs: (-11360, -10489), (-11411,
        # -10427)). At Medium a non-player frame lasts MY_SPEED x frame time - 64 (live model+0x102: ATK_M7 704), so the
        # port plays the original's ~43 frames and ends at (-11331, -10449).
        import scenarios
        w, vm = scenarios.boot_opening()
        scenarios.tick(w, vm, scenarios.opening_ticks(1020))
        bot = w.figures['FIRSTBOT']
        self.assertEqual(bot.motion, 'ATK_STAND')
        self.assertLess(float(np.hypot(bot.pos[0] + 11380, bot.pos[1] + 10462)), 100)
        self.assertAlmostEqual(bot.heading, 213.8, delta=2)


class AnimatedTextures(unittest.TestCase):
    def test_frame_follows_animate_state(self):
        a = worldmod.Assets('NURSEBOT')
        self.assertTrue(a.mesh.anim)
        ti, frames = next(iter(a.mesh.anim.items()))
        self.assertGreater(len(frames), 1)
        name = a.mesh.textures[ti][0].upper()[:8]
        V = np.zeros((len(a.mesh.verts), 3))
        eye = np.array([0.0, -1000.0, 0.0])
        self.assertIs(worldmod.shade_mesh(a.mesh, V, eye).textures[ti][3], frames[0])        # no ANIMATE: frame 0
        self.assertIs(worldmod.shade_mesh(a.mesh, V, eye, {}).textures[ti][3], frames[0])
        m = worldmod.shade_mesh(a.mesh, V, eye, {name: {'frame': 1}})
        self.assertIs(m.textures[ti][3], frames[1])
        self.assertIs(a.mesh.textures[ti][3], frames[0])         # the original mesh is not modified


class TexturedFaces(unittest.TestCase):
    def mesh(self, pixels):
        return types.SimpleNamespace(
            textures=[('TEST', len(pixels), 1, bytes(pixels))],
            polys=[(6, 0, [0, 1, 2], 0, [(0, 0), (1, 0), (2, 0)])],
            anim={},
        )

    def test_textured_face_keeps_ramp_texels_direct(self):
        mesh = self.mesh([0x80, 0x81, 0x8c, 0xff])
        V = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], float)
        shaded = worldmod.shade_mesh(mesh, V, np.array([1 / 3, 1 / 3, 10.0]))
        self.assertEqual(shaded.textures[0][3], mesh.textures[0][3])
        self.assertEqual(shaded.polys, mesh.polys)

    def test_non_ramp_texture_indices_are_preserved(self):
        mesh = self.mesh([0x02, 0x3f, 0x60, 0x6f])
        V = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], float)
        lit = worldmod.shade_mesh(mesh, V, np.array([0, 0, 10.0]))
        self.assertEqual(lit.textures[lit.polys[0][3]][3], mesh.textures[0][3])
        self.assertEqual(lit.polys, mesh.polys)

    def test_textured_face_does_not_create_palette_variant(self):
        mesh = self.mesh([0x80, 0x84, 0x8c])
        source_textures, source_polys = list(mesh.textures), list(mesh.polys)
        V = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], float)
        lit = worldmod.shade_mesh(mesh, V, np.array([0, 0, 10.0]))
        self.assertEqual(mesh.textures, source_textures)
        self.assertEqual(mesh.polys, source_polys)
        self.assertEqual(len(lit.textures), len(mesh.textures))
        self.assertEqual(lit.polys[0][3], mesh.polys[0][3])


class UntexturedFaces(unittest.TestCase):
    def test_ramp_faces_draw_at_ramp_start(self):
        # Intensity is always 0 (light 1290:cb84 keeps its constructor state), so flat (1) and Gouraud (5) ramp
        # faces take the ramp start; membership is inclusive of start + last offset (0x9f is in the 0x80 ramp).
        colors = [0x80, 0x88, 0x9f, 0xa6, 0xb6, 0x79, 0x00, 0x60]
        mesh = types.SimpleNamespace(textures=[], anim={},
                                     polys=[(5 if c == 0xa6 else 1, c, [0, 1, 2], None, None) for c in colors])
        V = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], float)
        lit = worldmod.shade_mesh(mesh, V, np.array([0, 0, 10.0]))
        self.assertEqual([p[1] for p in lit.polys], [0x80, 0x80, 0x80, 0xa0, 0xa0, 0x70, 0x00, 0x60])


class Combat(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.shared = None

    def setUp(self):
        w = self.w = worldmod.World('CHAOS', state_dir=worldmod.INITGAME)
        self.vm = vmmod.VM(w)
        vmmod.load_level(self.vm, 'CHAOS')
        cmd(w, 'CREATEFIGURE', 'LEX', 'PLAYER')
        self.lex = w.player()
        self.bot = w.figure('FIRSTBOT')
        self.bot.view_cams = None    # the real STARTUPFIRSTBOT creates it via CREATEFIGURE (always visible), not a placed
                                      # FIGR record (view_cams=[]); w.figure()'s lazy fetch pulls the latter, which this
                                      # combat test does not exercise
        # test scaffolding: the figures stand at arbitrary coordinates outside every CHAOS space, where collisions (flag 0x02
        # clear, the default) would block every move and push them apart; these tests exercise combat, not walls
        self.bot.no_collide = self.lex.no_collide = True
        self.place(0, 0, 0, 100, 0)
        cmd(w, 'DEFINEENEMY', 'PLAYER', fig='FIRSTBOT')

    def place(self, bx, by, bh, lx, ly):
        self.bot.pos = np.array([bx, by, 0.0])
        self.bot.heading = float(bh)
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

    def give_player_item(self, item_type, slot):
        p = proc('PLAYER')
        self.w.call('stmt', 'CREATEITEM', [item_type], p)
        self.w.call('stmt', 'PLACEITEM', [slot], p)
        return p.cur_item

    def test_lex_attack_input_is_unarmed_noop(self):
        self.w.set_player_input(attack=True)
        self.w.step()
        self.assertEqual(self.lex.motion, 'STAND')
        self.assertFalse(self.w.is_carrying(self.lex, 'RTHAND'))

    def test_lex_attack_input_uses_original_weapon_branch(self):
        self.give_player_item('BLASTER', 'RTHAND')
        self.w.set_player_input(attack=True)
        self.w.step()
        self.assertEqual((self.lex.motion, self.lex.loop), ('ATK_SHOOT', False))
        self.assertTrue(any(p.block.name == 'LEX_ATK_SHOOT' for p in self.vm.procs.values()))

    def test_starting_battery_is_inventory_not_weapon(self):
        self.vm.fire('GIVELEXSTARTINGBATT')
        battery = self.w.items['MY_BATTERY']
        self.assertEqual((battery.type, battery.owner, battery.slot), ('MONBAT', 'LEX', 'INVENTORY'))
        self.assertFalse(self.w.is_carrying(self.lex, 'RTHAND'))

    def test_setai_ai_on_off_and_individualize(self):
        w, vm = self.w, self.vm
        cmd(w, 'SETAI', 'NURSEBOT', fig='FIRSTBOT')
        self.assertEqual(self.bot.ai_type, 'NURSEBOT')
        cmd(w, 'AI', 'ON', fig='FIRSTBOT')
        self.assertTrue(self.bot.ai_enabled)
        self.assertIsNone(self.bot.ai_proc)                    # FUN_1088_31fb only enables; 3371 starts during update
        self.bot.view_cams, w.camera = ['VISIBLE'], 'HIDDEN'
        w.step()
        self.assertIsNone(self.bot.ai_proc)                    # hidden figures do not start AI
        w.camera = 'VISIBLE'
        w.step()
        p = self.bot.ai_proc
        self.assertEqual((p.block.name, p.cur_fig, p.owner), ('NURSEBOT_AI', 'FIRSTBOT', 'level'))
        cmd(w, 'AI', 'ON', fig='FIRSTBOT')
        self.assertIs(self.bot.ai_proc, p)                      # already running: no second process
        cmd(w, 'AI', 'OFF', fig='FIRSTBOT')
        self.assertFalse(self.bot.ai_enabled)
        self.assertEqual((p.suspended, p.done, self.bot.ai_proc), (True, False, p))   # FUN_1088_3196 pauses the process, it does not end it
        self.assertIn(p.handle, vm.procs)
        cmd(w, 'AI', 'ON', fig='FIRSTBOT')
        self.assertEqual((p.suspended, self.bot.ai_proc), (False, p))
        vm.finish(p)
        cmd(w, 'AI', 'OFF', fig='FIRSTBOT')
        w.step()
        self.assertTrue(self.bot.ai_proc.done)                 # the counter holds back a new start (FUN_1088_3371)
        cmd(w, 'INDIVIDUALIZE', 'CURFIG', 'BOT2', fig='FIRSTBOT')
        self.assertIn('BOT2', w.figures)
        self.assertNotIn('FIRSTBOT', w.figures)
        self.assertEqual(self.bot.name, 'BOT2')

    def test_enemy_queries_units_and_sign(self):
        w = self.w
        f = lambda n: w.combat_query(self.bot, n)
        self.place(0, 0, 0, 0, 2000)                            # enemy straight BEHIND (facing -y)
        self.assertEqual(f('DISTFROMENEMY'), 97)                # 2,000 units = (2000 * 100 + 0x80) // 0x800 = 97 cm (FUN_10d8:1278: 20.48 units/cm)
        self.assertEqual(abs(f('ANGLEFROMENEMY')), 180)
        self.place(0, 0, 0, 0, -2000)                           # straight ahead
        self.assertEqual(f('ANGLEFROMENEMY'), 0)
        self.place(0, 0, 0, 2000, 0)                            # facing -y: +x is to the LEFT
        self.assertEqual(f('ANGLEFROMENEMY'), 90)
        self.assertEqual(f('ATTACKRADIUS'), 55)                 # FIRSTBOT PERSONAL_RADIUS 55 cm (1126 units): FUN_10d8:0e28
        self.assertEqual(w.enemy_of('FIRSTBOT'), 'PLAYER')

    def test_turn_and_confront(self):
        w = self.w
        self.place(0, 0, 0, 2000, 0)
        cmd(w, 'TURNTOENEMY', 'TEN_DEGREES', fig='FIRSTBOT')
        self.assertAlmostEqual(self.bot.heading, -10)
        self.assertEqual(w.combat_query(self.bot, 'ANGLEFROMENEMY'), 80)    # turned toward the enemy
        cmd(w, 'CONFRONTENEMY', fig='FIRSTBOT')
        task = self.bot.confront
        self.assertEqual((task['settled'], w.combat_query(self.bot, 'ANGLEFROMENEMY')), (False, 80))       # 10d0:1c9b only starts the task
        w.update_confront(self.bot)
        self.assertEqual(self.bot.motion, 'TURN_LEFT' if w.rel_angle(self.bot, w.player().pos) > 0 else 'TURN_RIGHT')
        self.bot.heading -= w.rel_angle(self.bot, w.player().pos) - 5                                     # within 8/256 of a turn: stop and snap
        self.bot.set_motion('STAND', True)
        w.update_confront(self.bot)
        self.assertEqual((task['settled'], w.combat_query(self.bot, 'ANGLEFROMENEMY')), (True, 0))
        w.update_confront(self.bot)
        self.assertIs(self.bot.confront, task)                                                             # ... and the caller waits two updates more
        w.update_confront(self.bot)
        self.assertIsNone(self.bot.confront)
        cmd(w, 'CONFRONTENEMY', fig='FIRSTBOT')
        cmd(w, 'STOPMOTION', fig='FIRSTBOT')                                                               # FUN_1098_0789(fig, 1, 1) ends class 0x109 tasks
        self.assertIsNone(self.bot.confront)
        cmd(w, 'COMBATMODE', 'ON', fig='FIRSTBOT')
        cmd(w, 'SPARWITHPLAYER', fig='FIRSTBOT')
        self.assertTrue(self.bot.combat and self.bot.spar)
        self.assertEqual((self.bot.enemy, self.lex.enemy), ('PLAYER', 'FIRSTBOT'))

    def test_monster_move_codes_use_enemy_keyword(self):
        self.script('{ TMM\n\tSETCURRENTFIGURE FIRSTBOT\n\t_door_frame = CALL MONSTER_MOVE 10\n}\n')
        res = {}
        for name, (lx, ly) in {'attack': (0, -2000), 'walk': (0, -4000), 'run': (0, -9000),
                               'left': (6000, 0), 'right': (-6000, 0)}.items():
            self.place(0, 0, 0, lx, ly)
            self.vm.fire('TMM')
            res[name] = self.vm.globals['_door_frame']
        self.assertEqual(res, {'attack': 0, 'walk': 8, 'run': 10, 'left': 4, 'right': 6})

    def test_damage_subtracts_object_hp(self):
        w = self.w
        w.vm.objects['LEX'][0] = 100
        w.vm.globals['_difficulty_level'] = 0                   # FUN_1090_09b9 adjusts a player target by -4 at difficulty 0
        cmd(w, 'DAMAGE', 5, 'IMPACT', fig='PLAYER')
        cmd(w, 'DAMAGE', 'ENERGY', 20, fig='PLAYER')
        self.assertEqual(w.vm.objects['LEX'][0], 100 - 1 - 16)  # PLAYER.~0 and LEX.~0 are the same record
        self.assertEqual(w.vm.objname(proc(), 'PLAYER'), 'LEX')

    def test_timed_handles(self):
        w, vm = self.w, self.vm
        short = w.call('func', 'SUBTITLE', ['_x', 1, 'hi'], proc())
        self.assertIn(short, vm.procs)
        self.run_ticks(5)
        self.assertNotIn(short, vm.procs)                       # unresolved sound: lifetime = len(text) = 2 ticks
        long = w.call('func', 'SUBTITLE', ['_x', 1, 'x' * 300], proc())
        snd = w.call('func', 'GETSOUNDHANDLE', ['_x'], proc())
        self.assertTrue(all(h in vm.procs for h in (long, snd)))
        self.assertEqual(w.call('func', 'ISHANDLEPLAYING', [snd], proc()), 1)
        self.run_ticks(worldmod.SOUND_TICKS + 5)
        self.assertIn(long, vm.procs)                           # 300 chars = 300 ticks
        self.assertNotIn(snd, vm.procs)                         # 90-tick sound
        self.assertEqual(w.call('func', 'ISHANDLEPLAYING', [snd], proc()), 0)
        cmd(w, 'STOPSOUND', long)
        self.assertNotIn(long, vm.procs)

    def test_syringe_hit_dispatches_label_in_attacker_stimulus(self):
        w, vm = self.w, self.vm
        self.place(0, 0, 0, 0, -2000)                           # 100 cm ahead (gap ~3 cm)
        vm.globals['_lex_drugged'] = 0
        self.bot.set_motion('ATK_SYRINGE', False)
        self.run_ticks(ticks_for(self.bot, len(self.bot.frames)))
        self.assertEqual(vm.globals['_lex_drugged'], 1)
        self.assertEqual(w.hits[-1][1:], ('FIRSTBOT', 'LEX', 'ATK_SYRINGE', 'HIT_PLAYER_ATK_SYRINGE'))

    def test_second_syringe_starts_authored_revival(self):
        ctx = types.SimpleNamespace(cur_fig='FIRSTBOT', cur_item=None, owner='level')
        self.vm.spawn_at('FIRSTBOT_STIMULUS', 'HIT_PLAYER_ATK_SYRINGE', ctx=ctx)
        self.vm.spawn_at('FIRSTBOT_STIMULUS', 'HIT_PLAYER_ATK_SYRINGE', ctx=ctx)
        self.run_ticks(760)                                     # REVIVELEX ends at tick 743: its FREEZE motions (WAKE_UP SNAP_TO FREEZE, 92 ticks, and
                                                                # WAKE_UP_HEAD FREEZE, 39) now play out and block (were 612 with the start frame held)
        self.assertEqual(self.vm.globals['_lex_drugged'], 2)
        self.assertEqual(self.vm.globals['_lexrevived'], 1)
        self.assertTrue(self.lex.collisions)

    def test_syringe_misses_out_of_reach_or_arc(self):
        w, vm = self.w, self.vm
        vm.globals['_lex_drugged'] = 0
        for lx, ly in ((0, -9000), (0, 2000)):                 # too far / behind
            self.place(0, 0, 0, lx, ly)
            self.bot.set_motion('ATK_SYRINGE', False)
            self.run_ticks(ticks_for(self.bot, len(self.bot.frames)))
        self.assertEqual((vm.globals['_lex_drugged'], w.hits), (0, []))

    def test_stimulus_from_behind_stuns_and_bounces(self):
        w, vm = self.w, self.vm
        self.place(0, 0, 0, 0, 2000)                            # player behind the robot
        ctx = types.SimpleNamespace(cur_fig='FIRSTBOT', cur_item=None, owner='level')
        vm.spawn('FIRSTBOT_STIMULUS', [1], ctx)
        self.assertEqual(vm.objects['FIRSTBOT'][3], 2)          # _ATK_STATUS_STUNNED
        self.assertTrue(vm.objects['FIRSTBOT'][4] & 2)          # wound decal bit (NURSEBOT_DAMAGE)
        self.assertTrue(self.bot.bouncy)                         # NURSEBOT_BOUNCING: BOUNCINESS CURFIG ON
        self.assertEqual(self.bot.motion, 'START_BOUNCE')       # NURSEBOT_BOUNCING started
        self.run_ticks(ticks_for(self.bot, len(self.bot.frames)) + 6)
        self.assertEqual(self.bot.motion, 'BOUNCE')

    def test_turning_bounce_continue_moves_across_multiple_cycles(self):
        cmd(self.w, 'MOTION', 'BOUNCE', 'CONTINUE', fig='FIRSTBOT')
        self.assertTrue(self.bot.turning())
        self.assertTrue(self.bot.loop)
        cycle = ticks_for(self.bot, len(self.bot.frames), self.w)
        start = self.bot.pos[:2].copy()
        self.run_ticks(cycle)
        first = self.bot.pos[:2].copy()
        self.run_ticks(cycle)
        second = self.bot.pos[:2].copy()
        self.assertGreater(np.linalg.norm(first - start), 1)
        self.assertGreater(np.linalg.norm(second - first), 1)

    def test_stimulus_from_front_only_sets_is_hit(self):
        vm = self.vm
        self.place(0, 0, 0, 0, -2000)
        vm.globals['_nursebot_is_hit'] = 0
        ctx = types.SimpleNamespace(cur_fig='FIRSTBOT', cur_item=None, owner='level')
        vm.spawn('FIRSTBOT_STIMULUS', [1], ctx)
        self.assertEqual(vm.globals['_nursebot_is_hit'], 1)
        self.assertEqual(vm.objects['FIRSTBOT'][3], 0)

    def test_ai_walks_up_and_uses_syringe(self):
        w, vm = self.w, self.vm
        self.place(0, 0, 0, 0, -7000)                           # 350 cm ahead
        cmd(w, 'SETAI', 'NURSEBOT', fig='FIRSTBOT')
        cmd(w, 'AI', 'ON', fig='FIRSTBOT')
        vm.globals['_lex_drugged'] = 0
        seen, dist = set(), None
        for _ in range(900):
            self.run_ticks(1)
            seen.add(self.bot.motion)
            if vm.globals['_lex_drugged'] >= 1:
                dist = w.combat_query(self.bot, 'DISTFROMENEMY')
                break
        self.assertIn('ATK_M8', seen)                           # walks (code 8/10)
        self.assertIn('ATK_SYRINGE', seen)
        self.assertIsNotNone(dist)                              # the syringe hit
        self.assertLess(dist, 150)                              # ... from about arm's length


class ChaosEncounterEngine(unittest.TestCase):
    """Engine pieces the Caynan and Guard 1 encounters need (NOTES "CHAOS encounters: Caynan and Guard 1")."""

    def setUp(self):
        w = self.w = worldmod.World('CHAOS', state_dir=worldmod.INITGAME)
        self.vm = vmmod.VM(w)
        vmmod.load_level(self.vm, 'CHAOS')
        cmd(w, 'CREATEFIGURE', 'LEX', 'PLAYER')
        self.lex = w.player()
        self.lex.no_collide = True
        self.lex.heading = 0.0
        self.lex.pos = np.array([0.0, 0.0, 0.0])

    def run_ticks(self, n):
        for _ in range(n):
            self.vm.tick_once()
            self.w.step()

    def ask(self, name, *args, fig='PLAYER'):
        return self.w.call('func', name, list(args), proc(fig))

    def test_cm_from_units_is_the_inverse_of_hull_units(self):
        self.assertEqual(worldmod.cm_from_units(2000), 97)          # (2000 * 100 + 0x80) // 0x800
        self.assertEqual([worldmod.cm_from_units(worldmod.hull_units(cm)) for cm in (10, 40, 43, 55, 150)], [10, 40, 43, 55, 150])
        self.assertEqual(worldmod.cm_from_units(0), 0)
        self.assertEqual(worldmod.cm_from_units(-2000), -97)        # the signed divide truncates toward zero

    def test_attackradius_is_personal_radius(self):
        cay = self.w.figure('CAYNAN')
        self.assertEqual(self.w.combat_query(self.lex, 'ATTACKRADIUS'), 40)
        self.assertEqual(self.w.combat_query(cay, 'ATTACKRADIUS'), 43)

    def test_waypoint_distances_use_the_enemy_units(self):
        w = self.w
        wp = w.waypoints['GETMEAT']
        self.lex.pos = np.array([wp[0] + 3000, wp[1] + 4000, wp[2]])
        self.assertEqual(self.ask('2DDISTFROMWAYPOINT', 'CURFIG', 'GETMEAT'), 244)     # exact 5,000 units
        self.assertEqual(self.ask('DISTFROMWAYPOINT', 'CURFIG', 'GETMEAT'), 245)       # approx_length: 5,032 units
        self.assertEqual(self.ask('DISTFROMWAYPOINT', 'LEX', 'GETMEAT'), 245)          # a figure name works as well as CURFIG
        self.lex.pos[2] += 20000                                                       # z only counts in the 3D form
        self.assertEqual(self.ask('2DDISTFROMWAYPOINT', 'CURFIG', 'GETMEAT'), 244)
        self.assertGreater(self.ask('DISTFROMWAYPOINT', 'CURFIG', 'GETMEAT'), 900)
        self.assertEqual(w.warnings, [])

    def test_waypoint_angle_matches_the_enemy_bearing(self):
        w = self.w
        wp = w.waypoints['GETMEAT']
        for dx, dy, expect in ((0, -2000, 0), (2000, 0, 90), (-2000, 0, 90), (0, 2000, 180)):   # |bearing|; facing -y: +x is to the left
            self.lex.pos = np.array([wp[0] - dx, wp[1] - dy, wp[2]])
            self.assertEqual(abs(self.ask('ANGLEFROMWAYPOINT', 'CURFIG', 'GETMEAT')), expect, (dx, dy))
        self.lex.pos = np.array([wp[0] - 2000, wp[1], wp[2]])
        self.assertEqual(self.ask('ANGLEFROMWAYPOINT', 'CURFIG', 'GETMEAT'), 90)
        enemy = w.figure('CAYNAN')
        enemy.pos = np.array([wp[0], wp[1], wp[2]])
        self.lex.enemy = 'CAYNAN'
        self.assertEqual(self.ask('ANGLEFROMWAYPOINT', 'CURFIG', 'GETMEAT'), w.combat_query(self.lex, 'ANGLEFROMENEMY'))

    def test_aminwaypoint_is_the_hull_touching_the_point(self):
        wp = self.w.waypoints['GETMEAT']
        self.lex.pos = np.array([wp[0], wp[1], wp[2] + self.lex.assets.foot_offset])
        self.assertEqual(self.ask('AMINWAYPOINT', 'CURFIG', 'GETMEAT'), 1)
        self.lex.pos[0] += 3000
        self.assertEqual(self.ask('AMINWAYPOINT', 'CURFIG', 'GETMEAT'), 0)

    def test_unknown_waypoint_or_object_warns_and_returns_zero(self):
        self.assertEqual(self.ask('DISTFROMWAYPOINT', 'CURFIG', 'NOWHERE'), 0)
        self.assertEqual(self.ask('ANGLEFROMWAYPOINT', 'NOBODY', 'GETMEAT'), 0)
        self.assertEqual(self.w.warnings, ['DISTFROMWAYPOINT CURFIG NOWHERE: no such waypoint',
                                           'ANGLEFROMWAYPOINT NOBODY GETMEAT: no such object'])

    def test_ambient_loops_until_released_and_stopambient_leaves_one_shots(self):
        w = self.w
        handle = self.ask('AMBIENT', '_grd_ambient', 30)
        shot = self.ask('SOUND', '_light1', 100)
        self.assertIn(handle, w.sound_loops)
        self.run_ticks(300)
        self.assertEqual(self.ask('ISHANDLEPLAYING', handle), 1)                # a looped sample stays valid
        cmd(w, 'STOPAMBIENT', shot)                                             # FUN_1028_10c9: only a voice with the loop flag
        self.assertNotIn(shot, w.sound_loops)
        cmd(w, 'STOPAMBIENT', handle)                                           # 1000:046f: plays on to the sample's end, no wrap
        self.assertEqual(w.sound_releases, [(w.vm.tick, handle)])
        self.assertEqual(w.sound_stops, [])
        # alarm4c: 43299 samples at 11025 Hz, loop 19..43136 (19 + 43117). 300 ticks in = sample 110250, wrapped to 24035; 19264 left = 52.4 ticks,
        # so the handle wakes 53 ticks on and ends on the update after, as a one-shot does
        self.assertEqual(w.vm.procs[handle].wake, w.vm.tick + 53)
        self.run_ticks(53)
        self.assertEqual(self.ask('ISHANDLEPLAYING', handle), 1)
        cmd(w, 'STOPAMBIENT', handle)                                           # a second release changes nothing
        self.assertEqual(len(w.sound_releases), 1)
        self.run_ticks(1)
        self.assertEqual(self.ask('ISHANDLEPLAYING', handle), 0)
        self.assertEqual(w.warnings, [])

    def test_apply_tracks_the_texture_decal_state(self):
        w = self.w
        cay = w.figure('CAYNAN')
        cmd(w, 'APPLY', 'CURFIG', 'CLEAR', 'CAHND', 'PICTURE', 1, fig='CAYNAN')
        self.assertEqual(cay.decals, {'CAHND': ('CLEAR', 1, 'CAY')})
        cmd(w, 'APPLY', 'CURFIG', 'DRAWONLY', 'CAHDF', 'PICTURE', 3, fig='CAYNAN')
        self.assertEqual(cay.decals['CAHDF'], ('DRAWONLY', 3, 'CAY'))
        cmd(w, 'APPLY', 'CURFIG', 'RESTORE', 'CAHDF', fig='CAYNAN')
        self.assertEqual(list(cay.decals), ['CAHND'])
        cmd(w, 'APPLY', 'CAYNAN', 'RESTORE', 'ALL', fig='PLAYER')                # the object may be named; ALL walks every texture
        self.assertEqual(cay.decals, {})
        guard = w.figure('GUARD1')
        cmd(w, 'APPLY', 'CURFIG', 'DRAWONLY', 'CHEST', 'PICTURE', 6, 'GRD', fig='GUARD1')
        cmd(w, 'APPLY', 'CURFIG', 'CLEAR', 'LHAND', 'PICTURE', 1, 'GRD', fig='GUARD1')
        self.assertEqual(guard.decals, {'CHEST': ('DRAWONLY', 6, 'GRD'), 'LHAND': ('CLEAR', 1, 'GRD')})
        self.assertEqual(w.warnings, [])
        cmd(w, 'APPLY', 'CURFIG', 'DRAWONLY', 'NOTEXTURE', 'PICTURE', 1, fig='CAYNAN')
        cmd(w, 'APPLY', 'CURFIG', 'SCRIBBLE', 'CAHND', fig='CAYNAN')
        self.assertEqual(w.warnings, ['APPLY CAYNAN NOTEXTURE: no such texture', 'APPLY SCRIBBLE: unknown mode'])

    def test_setcurrentfigure_falls_back_to_the_type_name(self):
        w = self.w
        w.figure('GUARD1')
        p = proc('PLAYER')
        self.assertEqual(w.call('func', 'SETCURRENTFIGURE', ['GRDCELL'], p), 1)
        self.assertEqual(p.cur_fig, 'GUARD1')                                   # GUARD1 is a GRDCELL (INDIVIDUALIZEd)
        self.assertEqual(w.call('func', 'SETCURRENTFIGURE', ['NOSUCHTYPE'], proc('PLAYER')), 0)
        p = proc('PLAYER')
        self.assertEqual(w.call('func', 'SETCURRENTFIGURE', ['GUARD1'], p), 1)  # the instance name still wins
        self.assertEqual(p.cur_fig, 'PLAYER')

    def test_compass_is_the_orientation_row_in_whole_degrees(self):
        for heading, expect in ((0, 0), (90, 90), (45, 45), (-135, -135), (180, 180), (-90, -90), (10.5, 10)):
            self.lex.heading = float(heading)
            self.assertEqual(self.ask('COMPASS'), expect, heading)
        self.assertEqual(self.w.call('func', 'COMPASS', [], proc(None)), 0)             # no current figure: 0, silently
        self.assertEqual(self.w.warnings, [])

    def test_ismyform_compares_the_type_name_without_case(self):
        w = self.w
        self.assertEqual(self.ask('ISMYFORM', 'LEX'), 1)
        self.assertEqual(self.ask('ISMYFORM', 'lex'), 1)
        self.assertEqual(self.ask('ISMYFORM', 'LEXMIR'), 0)
        w.figure('GUARD1')
        self.assertEqual(self.ask('ISMYFORM', 'GRDCELL', fig='GUARD1'), 1)              # the type, not the instance name
        self.assertEqual(self.ask('ISMYFORM', 'GUARD1', fig='GUARD1'), 0)
        self.assertEqual(self.ask('ISMYFORM', ''), 0)
        self.assertEqual(w.warnings, ['ISMYFORM: no form name'])

    def test_isincombatmode_returns_flag_0x40(self):
        self.assertEqual(self.ask('ISINCOMBATMODE'), 0)
        self.lex.combat = True
        self.assertEqual(self.ask('ISINCOMBATMODE'), 0x40)

    def test_iskeypressed_reads_the_held_scan_codes(self):
        self.assertEqual(self.ask('ISKEYPRESSED', 71), 0)
        self.w.keys_held.append(0x47)                                                   # _HK_KEYPAD7 = 71
        self.assertEqual(self.ask('ISKEYPRESSED', 71), 1)
        self.assertEqual(self.ask('ISKEYPRESSED', 72), 0)

    def test_heading_is_the_direction_of_the_last_frame_move(self):
        lex = self.lex
        lex.prev_pos = np.array([1000.0, 2000.0, 0.0])
        for move, expect in (((0, -100), 0), ((-100, 0), 90), ((100, 0), -90), ((0, 100), 180), ((-100, -100), 45), ((100, -100), -45),
                             ((-100, 100), 135), ((100, 100), -135), ((0, 0), 666)):
            lex.pos = lex.prev_pos + np.array([move[0], move[1], 5.0])
            self.assertEqual(self.ask('HEADING', 'CURFIG'), expect, move)
        self.lex.heading = 90.0                                                         # a forward step at heading h reads HEADING == COMPASS
        lex.pos = lex.prev_pos + np.append(lex.forward() * 200, 0)
        self.assertEqual(self.ask('HEADING', 'PLAYER'), self.ask('COMPASS'))
        self.assertEqual(self.ask('HEADING', 'NOBODY'), 0)
        self.assertEqual(self.w.warnings, ['HEADING NOBODY: no such object'])

    def test_aminextent_is_the_hull_touching_the_named_phys(self):
        w = self.w
        ce3 = next(p for p in w.phys if p['name'] == 'CE3')
        lo, hi = np.array(ce3['lo'], float), np.array(ce3['hi'], float)
        self.lex.pos = np.array([(lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2, lo[2] + self.lex.assets.foot_offset])
        self.assertEqual(self.ask('AMINEXTENT', 'CURFIG', 'CE3'), 1)
        self.assertEqual(self.ask('AMINEXTENT', 'PLAYER', 'ce3'), 1)
        self.lex.pos[1] = hi[1] + 5000
        self.assertEqual(self.ask('AMINEXTENT', 'CURFIG', 'CE3'), 0)
        self.assertEqual(w.warnings, [])
        self.assertEqual(self.ask('AMINEXTENT', 'CURFIG', 'NOWHERE'), 0)
        self.assertEqual(w.warnings, ['AMINEXTENT CURFIG NOWHERE: no such extent'])

    def test_floatatheight_maximum_caps_the_mover_target_z(self):
        w = self.w
        lex = self.lex
        lex.area = next(i for i, p in enumerate(w.phys) if p['name'] == 'CE3')
        base = w.phys[lex.area]['lo'][2]
        cmd(w, 'FLOATATHEIGHT', 'USEALTI', 'MAXIMUM')
        self.assertEqual(lex.z_cap, w.waypoints['USEALTI'][2] - base)                    # waypoint z - the anchor's base z
        w.mover(lex, np.array([-10000.0, -10000.0, base + 9000.0]))
        self.assertEqual(lex.pos[2], w.waypoints['USEALTI'][2])                          # limited to base + cap = the waypoint z
        w.mover(lex, np.array([-10000.0, -10000.0, base + 100.0]))
        self.assertEqual(lex.pos[2], base + 100.0)                                       # below the cap: untouched
        self.assertEqual(w.warnings, [])
        cmd(w, 'FLOATATHEIGHT', 'NOWHERE', 'MAXIMUM')
        cmd(w, 'FLOATATHEIGHT', 'USEALTI', 'MINIMUM')
        lex.area = None
        lex.pos = np.array([1e7, 1e7, 0.0])                                              # outside every area
        cmd(w, 'FLOATATHEIGHT', 'USEALTI', 'MAXIMUM')
        self.assertEqual(w.warnings, ['FLOATATHEIGHT NOWHERE: no such waypoint', 'FLOATATHEIGHT USEALTI MINIMUM: expected MAXIMUM',
                                      'FLOATATHEIGHT USEALTI MAXIMUM: LEX has no area'])
        self.assertEqual(w.unmodelled, [])
        lex.pos = np.array([-11485.0, -30181.0, -6470.0])                                # USE_BOT's spot: a placed figure without a selected area gets one
        cmd(w, 'FLOATATHEIGHT', 'USEALTI', 'MAXIMUM')
        self.assertEqual(w.phys[lex.area]['name'], 'CE4')
        self.assertEqual(lex.z_cap, w.waypoints['USEALTI'][2] - w.phys[lex.area]['lo'][2])
        cmd(w, 'FLOATATHEIGHT', 'USEALTI')                                               # the float-height form sets F (mechanics tests)
        self.assertEqual(w.unmodelled, [])
        self.assertEqual(lex.foot_override, w.waypoints['USEALTI'][2] - w.point_floor(*(int(c) for c in w.waypoints['USEALTI']), int(w.waypoints['USEALTI'][2])))

    def test_coord_functions_shift_the_position_right_by_eight(self):
        self.lex.pos = np.array([-1139201.0, 2560.0, 255.0])
        self.assertEqual([self.ask(n, 'LEX') for n in ('COORDX', 'COORDY', 'COORDZ')], [-4451, 10, 0])    # SAR 8 floors
        self.assertEqual([self.ask(n, 'CURFIG') for n in ('COORDX', 'COORDY', 'COORDZ')], [-4451, 10, 0])  # the process's current figure
        cay = self.w.figure('CAYNAN')
        cay.pos = np.array([512.0, 0.0, 0.0])
        self.assertEqual(self.ask('COORDX', 'CURFIG', fig='CAYNAN'), 2)
        self.assertEqual(self.ask('COORDX', 'NOBODY'), 0)
        self.assertEqual(self.w.warnings, [])                                    # an unknown object is silent

    def test_distfromextent_and_trigger_measure_to_the_box_centre(self):
        w = self.w
        for name, boxes, fn in (('DISTFROMEXTENT', w.phys, 'CE3'), ('DISTFROMTRIGGER', w.triggers, w.triggers[0]['name'])):
            box = next(b for b in boxes if b['name'] == fn)
            c = [(int(lo) + int(hi)) // 2 for lo, hi in zip(box['lo'], box['hi'])]
            self.lex.pos = np.array([c[0] + 3000.0, c[1] + 4000.0, c[2]])
            self.assertEqual(self.ask(name, 'CURFIG', fn.lower()), worldmod.cm_from_units(worldmod.approx_length([3000, 4000, 0])), name)
        self.assertEqual(self.ask('DISTFROMEXTENT', 'CURFIG', 'NOWHERE'), 0)
        self.assertEqual(self.ask('DISTFROMTRIGGER', 'NOBODY', w.triggers[0]['name']), 0)
        self.assertEqual(w.warnings, ['DISTFROMEXTENT CURFIG NOWHERE: no such extent',
                                      f"DISTFROMTRIGGER NOBODY {w.triggers[0]['name']}: no such object"])

    def test_item_distances_need_a_current_item_and_figure(self):
        w = self.w
        p = proc()
        self.assertEqual(w.call('func', 'DISTFROMITEM', [], p), 0)
        self.assertEqual(w.call('func', '2DDISTFROMITEM', [], p), 0)
        self.assertEqual(w.warnings, ['DISTFROMITEM: no current item', '2DDISTFROMITEM: no current item'])
        cmd(w, 'CREATEITEM', 'MEDKIT')
        item = next(iter(w.items.values()))
        p.cur_item = item.name
        item.pos = np.array([3000.0, 4000.0, 20000.0])
        self.assertEqual(w.call('func', '2DDISTFROMITEM', [], p), 244)
        self.assertEqual(w.call('func', 'DISTFROMITEM', [], p), worldmod.cm_from_units(worldmod.approx_length([3000, 4000, 20000])))
        p.cur_fig = 'NOBODY'
        self.assertEqual(w.call('func', 'DISTFROMITEM', [], p), 0)
        self.assertIn('DISTFROMITEM: no current figure', w.warnings)

    def test_2ddistfromcoords_takes_coordx_units(self):
        self.lex.pos = np.array([0.0, 0.0, 500.0])
        self.assertEqual(self.ask('2DDISTFROMCOORDS', 'CURFIG', 11, 15), worldmod.cm_from_units(worldmod.length2d(11 << 8, 15 << 8)))
        self.assertEqual(self.ask('2DDISTFROMCOORDS', 'NOBODY', 1, 1), 0)
        self.assertEqual(self.w.warnings, ['2DDISTFROMCOORDS NOBODY: no such object'])

    def test_isaion_isgravityon_and_keyboard_flags(self):
        w = self.w
        self.assertEqual(self.ask('ISAION'), 1)
        self.lex.hold = 2
        self.assertEqual(self.ask('ISAION'), 0)
        self.assertEqual(self.ask('ISGRAVITYON', 'CURFIG'), int(self.lex.gravity))
        self.lex.gravity = False
        self.assertEqual(self.ask('ISGRAVITYON', 'LEX'), 0)
        self.assertEqual(self.ask('ISGRAVITYON', 'NOBODY'), 0)
        self.assertEqual(w.warnings, ['ISGRAVITYON NOBODY: no such object'])
        self.assertEqual(self.ask('ISKEYBOARDCAPTURED'), 0)
        cmd(w, 'CAPTUREKEYBOARD')
        self.assertEqual(self.ask('ISKEYBOARDCAPTURED'), 1)

    def test_findfirst_and_findnext_walk_the_figure_list(self):
        w = self.w
        cmd(w, 'CREATEFIGURE', 'CAYNAN', 'CAYNAN')
        p = proc()
        names = list(w.figures)
        w.call('stmt', 'FINDFIRSTFIGURE', [], p)
        self.assertEqual((p.cur_fig, p.fig_index), (names[0], 0))
        seen = [p.cur_fig]
        while w.call('func', 'FINDNEXTFIGURE', [], p):
            seen.append(p.cur_fig)
        self.assertEqual(seen, names)
        self.assertEqual(p.cur_fig, names[-1])                                   # the end leaves the current figure
        self.assertEqual(w.call('func', 'FINDNEXTFIGURE', [], p), 0)

    def test_ambient_handles_are_none(self):
        self.assertEqual((self.ask('GETROOMAMBIENT'), self.ask('GETCAMERAAMBIENT')), (-1, -1))

    def test_new_script_functions_are_modelled(self):
        w = self.w
        for n in ('DISTFROMEXTENT', 'DISTFROMTRIGGER'):
            w.call('func', n, ['CURFIG', 'X'], proc())
        w.call('func', '2DDISTFROMCOORDS', ['CURFIG', 1, 1], proc())
        for n in ('DISTFROMITEM', '2DDISTFROMITEM', 'ISAION', 'ISKEYBOARDCAPTURED', 'FINDNEXTFIGURE', 'GETROOMAMBIENT', 'GETCAMERAAMBIENT'):
            w.call('func', n, [], proc())
        w.call('func', 'ISGRAVITYON', ['CURFIG'], proc())
        w.call('stmt', 'FINDFIRSTFIGURE', [], proc())
        self.assertEqual(w.unmodelled, [])

    def test_unmodelled_calls_are_listed_apart_from_warnings(self):
        w = self.w
        w.call('stmt', 'RUNEDITORTOOL', [3], proc())
        w.call('func', 'NOSUCHFUNC', [], proc())
        w.call('stmt', 'GRAVITY', ['CURFIG', 'ON'], proc())                      # modelled: not listed
        w.call('func', 'COMPASS', [], proc())                                    # ported with the encounters' last gaps: not listed
        self.assertEqual(w.unmodelled, ['RUNEDITORTOOL: unmodelled statement (ignored)', 'NOSUCHFUNC: unmodelled function (ignored)'])
        self.assertEqual(w.warnings, [])

    def test_continue_taunt_plays_once_but_idles_loop(self):
        w = self.w
        cmd(w, 'MOTION', 'TAUNT2', 'CONTINUE')
        self.assertFalse(self.lex.loop)
        cmd(w, 'MOTION', 'STAND', 'CONTINUE')
        self.assertTrue(self.lex.loop)

    def test_combat_figure_returns_to_atk_stand_after_a_one_shot(self):
        w = self.w
        bot = w.figure('FIRSTBOT')
        bot.view_cams = None
        bot.pos = np.array([-5000.0, 5000.0, 0.0])
        bot.no_collide = True
        bot.combat = True
        bot.set_motion('RECOIL_TL', False)
        self.run_ticks(ticks_for(bot, len(bot.frames), w) + 2)
        self.assertEqual((bot.motion, bot.loop, bot.engine_request), ('ATK_STAND', True, True))
        self.lex.combat = True                                                   # 1088:4155 has no exemption for the player
        self.lex.set_motion('ATK_H8', False)
        self.run_ticks(ticks_for(self.lex, len(self.lex.frames), w) + 2)
        self.assertEqual(self.lex.motion, 'ATK_STAND')
        bot.combat = False
        bot.set_motion('RECOIL_TL', False)
        self.run_ticks(ticks_for(bot, len(bot.frames), w) + 2)
        self.assertEqual((bot.motion, bot.loop), ('STAND', True))                # 1088:4155: out of combat mode its idle is stand

    def test_final_root_z_is_carried_only_by_a_hovering_motion(self):
        guard = worldmod.Figure('G', 'GRDCELL', self.w.asset('GRDCELL'), pos=[0.0, 0.0, 100.0])
        guard.gravity = True
        guard.set_motion('WAKE_UP', False)                                        # started under gravity: its root z lived in the pose
        guard.finished = True
        guard.gravity = False
        guard.set_motion('ATK_STAND', True)
        self.assertEqual(guard.pos[2], 100.0)
        guard.set_motion('WAKE_UP', False)                                        # without gravity too: only a lift is carried (live: GET_UP brings GUARD1 back up)
        guard.finished = True
        guard.set_motion('ATK_STAND', True)
        self.assertEqual(guard.pos[2], 100.0)


if __name__ == '__main__':
    unittest.main()
