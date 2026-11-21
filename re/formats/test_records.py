"""FIGR / ITEM / PLAY record decoding (level.ObjRec) against INITGAME, the shipped GAMEDAT and the native save in
re/out/native_save/gamedat (never modified): re/.venv/bin/python -I -W ignore -m unittest discover -s re/formats -p 'test_records.py'"""
import math, os, struct, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import level
import savegame as sg

NATIVE = os.path.join(sg.ROOT, 're', 'out', 'native_save', 'gamedat')


def chaos(path):
    return sg.LevelIff.parse(open(os.path.join(path, 'CHAOS.IFF'), 'rb').read()).records()


def by_inst(path, inst, tag=None):
    return next(r for t, n, raw, r in chaos(path) if r is not None and r.inst == inst and (tag is None or t == tag))


class Layout(unittest.TestCase):
    def test_every_record_of_every_sample_decodes_and_reencodes(self):
        n = 0
        for path in (sg.INITGAME, sg.GAMEDAT, NATIVE):
            for f in sorted(os.listdir(path)):
                if f.upper().endswith('.IFF'):
                    for t, nm, raw, rec in sg.LevelIff.parse(open(os.path.join(path, f), 'rb').read()).records():
                        if t in level.RECORD_TAGS:
                            self.assertEqual(rec.encode(), raw, (path, f, nm))
                            n += 1
                        else:
                            self.assertIsNone(rec)
        self.assertEqual(n, 222)

    def test_sizes_follow_the_variable_parts(self):
        # base 191 (ITEM) | FIGR = 191 + 2+9+8+2 +1+4+25 +2+L +2+25+4 +2+9n +2+2+32 +20 +2+21 | PLAY + 8
        for path in (sg.INITGAME, sg.GAMEDAT, NATIVE):
            for t, nm, raw, r in chaos(path):
                if t == 'ITEM':
                    self.assertEqual(len(raw), 191)
                elif t in ('FIGR', 'PLAY'):
                    L, n = len(r.in_trig), len(r.view_cams)
                    self.assertEqual(L, 78)                                  # CHAOS has 78 IMAG objects
                    self.assertEqual(len(raw), 356 + L + 9 * n + 8 * (t == 'PLAY'))
        self.assertEqual(len(by_inst(sg.GAMEDAT, 'LEX').buf), 442)

    def test_init_state(self):
        for t, nm, raw, r in chaos(sg.INITGAME):
            if r is not None:
                self.assertEqual(r.matrix, [(256, 0, 0), (0, 256, 0), (0, 0, 256)])
                self.assertAlmostEqual(r.heading, 0)
                self.assertEqual(r.holder, 0)
        self.assertEqual(by_inst(sg.INITGAME, 'FIRSTBOT').hp, 50)
        self.assertEqual(by_inst(sg.INITGAME, 'FIRSTBOT').view_cams, [])


class Fields(unittest.TestCase):
    def test_heading_matches_geometry(self):
        # native save: Lex and the nurse face each other (COMPASS convention: forward = (-sin h, -cos h))
        lex, nurse = by_inst(NATIVE, 'LEX'), by_inst(NATIVE, 'FIRSTBOT')
        self.assertEqual(lex.matrix[:2], [(197, -163, 0), (163, 197, 0)])
        self.assertAlmostEqual(lex.heading, 39.6, 1)
        self.assertAlmostEqual(nurse.heading, -143.8, 1)
        d = [b - a for a, b in zip(lex.pos, nurse.pos)][:2]
        fwd = (-math.sin(math.radians(lex.heading)), -math.cos(math.radians(lex.heading)))
        cosang = (fwd[0] * d[0] + fwd[1] * d[1]) / math.hypot(*d)
        self.assertGreater(cosang, 0.99)
        self.assertAlmostEqual(by_inst(sg.GAMEDAT, 'LEX').heading, -149.6, 1)

    def test_heading_setter(self):
        r = by_inst(NATIVE, 'LEX')
        raw = r.encode()
        r.heading = -90
        self.assertEqual(r.matrix, [(0, 256, 0), (-256, 0, 0), (0, 0, 256)])
        self.assertAlmostEqual(r.heading, -90)
        r.heading = 39.6
        self.assertEqual(r.encode()[147:183], raw[147:183])
        r.pos = (1, 2, 3)
        self.assertEqual(r.pos, (1, 2, 3))

    def test_hit_points_and_locals(self):
        lex = by_inst(NATIVE, 'LEX')
        self.assertEqual((lex.hp, lex.locals[5]), (96, 100))
        self.assertEqual(by_inst(sg.GAMEDAT, 'LEX').hp, 98)
        self.assertEqual(by_inst(NATIVE, 'CAYNAN').hp, 200)
        self.assertEqual(by_inst(NATIVE, 'MY_BATTERY').locals[:3], [100, 100, 2])         # item locals: charge / maximum / ?

    def test_motion_flags_and_cameras(self):
        n = by_inst(NATIVE, 'FIRSTBOT')
        self.assertEqual((n.motion, n.flags), ('atk_stand', 0xc0))
        self.assertTrue(n.flags & level.F_COMBAT and not n.flags & level.F_HIDDEN)
        u = by_inst(NATIVE, 'USE_BOT')
        self.assertEqual(u.view_cams, ['CE41', 'CE42', 'CE43'])
        self.assertTrue(u.flags & level.F_HIDDEN)                   # current camera CE31 is not in its list
        s = by_inst(sg.GAMEDAT, 'USE_BOT')                          # shipped state is in CE33: visible, in combat
        self.assertEqual((s.flags, s.view_cams[-1]), (0x40, 'CE33'))
        self.assertEqual(by_inst(sg.GAMEDAT, 'LEX').motion, 'STAND')

    def test_avoidance_points(self):
        st = sg.SaveState.load(NATIVE)
        objs = st.levels['CHAOS'].records()
        nm = lambda i: objs[i - 1][1]
        self.assertEqual([(nm(w), r) for w, r in by_inst(NATIVE, 'FIRSTBOT').avoid], [('AVDBAR3', 100), ('AVDBNK3', 200)])
        self.assertEqual([(nm(w), r) for w, r in by_inst(NATIVE, 'CAYNAN').avoid],
                         [('CAYSTOP1', 60), ('CAYSTOP2', 60), ('CAYSTOP3', 60)])

    def test_enemy_and_task_slots_point_at_the_kernel_table(self):
        st = sg.SaveState.load(NATIVE)
        objs = st.levels['CHAOS'].records()
        lex, nurse = by_inst(NATIVE, 'LEX'), by_inst(NATIVE, 'FIRSTBOT')
        self.assertEqual(objs[lex.enemy - 1][3].inst, 'FIRSTBOT')
        self.assertEqual(objs[nurse.enemy - 1][3].inst, 'LEX')
        # motion task: type 0x108 owned by the figure's object id; AI task: the NURSEBOT_AI process
        ids = {r.inst: i for i, (t, n, raw, r) in enumerate(objs, 1) if r is not None}
        for fig in (lex, nurse):
            t = st.script.slot(fig.motion_task)
            self.assertEqual(t.type, 0x108)
            self.assertEqual(t.task()[2], ids[fig.inst])
        self.assertEqual(st.script.slot(nurse.ai_task).proc().block_name(), 'NURSEBOT_AI')
        self.assertEqual(lex.ai_task, 0)

    def test_items_holder_and_flags(self):
        st = sg.SaveState.load(sg.GAMEDAT)
        objs = st.levels['CHAOS'].records()
        carried = {r.inst: (r.flags, objs[r.holder - 1][3].inst) for t, n, raw, r in objs if t == 'ITEM' and r.holder}
        self.assertEqual(carried, {'MEAT': (0x15, 'LEX'), 'LEXLOG': (0x15, 'LEX'), 'MY_BATTERY': (0x05, 'LEX')})
        self.assertEqual(by_inst(sg.GAMEDAT, 'FLUTE').flags, 0x11)           # lying about: bouncy + gravity, not hidden
        self.assertEqual(by_inst(NATIVE, 'MY_BATTERY').hand, '')
        n = sg.SaveState.load(NATIVE).levels['CHAOS'].records()
        self.assertEqual(n[by_inst(NATIVE, 'MY_BATTERY').holder - 1][3].inst, 'LEX')

    def test_player_tail(self):
        g, n = by_inst(sg.GAMEDAT, 'LEX'), by_inst(NATIVE, 'LEX')
        self.assertEqual((g.player_clock, n.player_clock), (0x2427, 0x211a))
        objs = chaos(sg.GAMEDAT)
        self.assertEqual(objs[g.player_target - 1][3].inst, 'MEAT')          # the item about to be used
        self.assertEqual(n.player_target, 0)

    def test_bad_layout_is_refused(self):
        t, nm, raw, r = next(x for x in chaos(NATIVE) if x[0] == 'FIGR')
        with self.assertRaises(ValueError):
            level.ObjRec('FIGR', raw[:-1])
        with self.assertRaises(ValueError):
            level.ObjRec('ITEM', raw)


if __name__ == '__main__':
    unittest.main()
