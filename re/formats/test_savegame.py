"""Checks for savegame.py against the native sample game/app/GAMEDAT (never modified)."""
import os, struct, sys, tempfile, unittest
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import savegame as sg

ST = sg.SaveState.load(sg.GAMEDAT)


class Native(unittest.TestCase):
    def test_roundtrip_every_file(self):
        enc = ST.files()
        for n in os.listdir(sg.GAMEDAT):
            self.assertEqual(enc[n.upper()], open(os.path.join(sg.GAMEDAT, n), 'rb').read(), n)

    def test_misc_known_values(self):
        m = ST.misc
        self.assertEqual((m.save_name, m.level, m.camera, m.auto_camera, m.next_serial), ('GAME1.IM1', 'CHAOS.IFF', 'CE33', 1, 2305))
        self.assertEqual((m.obj_a, m.obj_b), (4, 5))
        m2 = sg.Misc(m.encode())
        m2.camera = 'CE31'
        self.assertEqual(sg.Misc(m2.encode()).camera, 'CE31')
        self.assertEqual(m.camera, 'CE33')

    def test_misc_serials_match_script_slots(self):
        for s in ST.script.slots:
            if s.kind in ('task', 'proc') and ST.misc.serials[s.index]:
                self.assertEqual(ST.misc.serials[s.index], s.serial)

    def test_script_dat_structure(self):
        sd = ST.script
        self.assertEqual(sd.ident, 'Defines=77e Id=Kernel Ver. 1.00 - T. Zurovec')
        self.assertEqual(len(sd.flex.entries), 210)
        self.assertEqual(sum(1 for e in sd.flex.entries if e.data), 52)
        self.assertEqual([len(sd.flex.entries[i].data) for i in range(1, 8)], [153, 10, 200, 1152, 9216, 64, 400])
        self.assertEqual(len(sd.slots), 25)
        self.assertEqual(sd.kernel_fields()['live_tasks'], 25)
        self.assertEqual(sd.active_list, [1, 3, 4, 5, 0x408])
        self.assertEqual(sum(sd.class_counts), 25)
        self.assertEqual(sorted({s.class_name for s in sd.slots}), ['BiosTimer', 'Default', 'Music', 'StdIntHandler', 'Wait'])

    def test_process_records_decode_fully(self):
        procs = [s for s in ST.script.slots if s.kind == 'proc']
        self.assertEqual(len(procs), 12)
        for s in procs:
            p = s.proc()
            self.assertEqual(p.encode(), s.b)
            self.assertTrue(p.script.endswith('.SCP'))
            names = sg.script_blocks(p.script)
            self.assertTrue(0 < p.block <= len(names))
        by = {s.index: s.proc() for s in procs}
        self.assertEqual((by[15].script, by[15].block_name()), ('CHAOSBLK.SCP', 'CELLONEBARS'))
        self.assertEqual(by[23].block_name(), 'FLICKER_LIGHT')
        self.assertEqual(ST.describe_obj(by[15].obj_a), 'PLAY LEX')
        self.assertIn('CAMR CE11', [ST.describe_obj(o) for o in by[15].objs])

    def test_wait_links_are_symmetric(self):
        for s in ST.script.slots:
            if s.kind == 'task' and s.class_name == 'Wait':
                _, l2, owner = s.task()
                target = ST.script.slot(owner)
                self.assertIn(s.index, target.task()[0])
                self.assertEqual(l2[0], 0x4000 | owner)

    def test_lists(self):
        ls = ST.lists.lists()
        self.assertEqual(list(ls), ['GMAINT', 'LEX'])
        self.assertEqual(ls['LEX'][0], ('MYBOOK', 1786577))

    def test_vars_vs_defaults(self):
        dv = sg.default_vars()
        self.assertEqual([n for n, _ in ST.vars.items], [n for n, _ in dv])
        self.assertEqual(sum(1 for a, b in zip(ST.vars.items, dv) if a[1] != b[1]), 117)
        self.assertEqual(ST.vars.values()['_DIFFICULTY_LEVEL'], 0)
        self.assertEqual(len(ST.sounds.items), 1564)

    def test_chaos_level_diff(self):
        init = sg.LevelIff.parse(open(os.path.join(sg.INITGAME, 'CHAOS.IFF'), 'rb').read()).objects()
        d = sg.level_diff(init, ST.levels['CHAOS'].objects())
        self.assertEqual(sorted(d['added']), [('ITEM', 'MONBAT', 0), ('PLAY', 'LEX', 0)])
        self.assertEqual(d['removed'], [('FIGR', 'NURSEBOT', 1)])
        self.assertTrue(any(k[1] == 'CAYNAN' for k, *_ in d['moved']))
        self.assertEqual(ST.level_objects()[259][:2], ('PLAY', 'LEX'))
        for n in ST.levels:                     # other levels are untouched
            if n not in ('CHAOS', 'TITLE'):
                ini = sg.LevelIff.parse(open(os.path.join(sg.INITGAME, n + '.IFF'), 'rb').read()).objects()
                self.assertFalse(any(sg.level_diff(ini, ST.levels[n].objects()).values()), n)


class Container(unittest.TestCase):
    def test_flex_header_checksum_and_rebuild(self):
        raw = open(os.path.join(sg.GAMEDAT, 'LISTS.FLX'), 'rb').read()
        self.assertEqual(sg.Flex.parse(raw).encode(), raw)

    def test_im1_pack_unpack_self_consistent(self):
        with tempfile.TemporaryDirectory() as t:
            data = sg.Im1.pack(sg.GAMEDAT, thumbnail=b'\x01\x02\x03')
            f = sg.Flex.parse(data)
            self.assertEqual(f.esz, len('PLATFORM.IFF') + 14)
            self.assertEqual(len(f.entries), 16)
            self.assertTrue(f.hdr.startswith(b'BioForge ver f1.01 savegame (C) 1994, 1995 Origin Systems Inc.'))
            names, thumb = sg.Im1.unpack(data, t)
            self.assertEqual(thumb, b'\x01\x02\x03')
            self.assertEqual(sorted(names), sorted(os.listdir(sg.GAMEDAT)))
            for n in names:
                self.assertEqual(open(os.path.join(t, n), 'rb').read(), open(os.path.join(sg.GAMEDAT, n), 'rb').read())
            self.assertEqual(sg.Im1.pack(t, thumbnail=b'\x01\x02\x03'), data)

    def test_im1_without_thumbnail(self):
        data = sg.Im1.pack(sg.GAMEDAT)
        f = sg.Flex.parse(data)
        self.assertEqual(f.entries[0].data, b'')
        self.assertTrue(f.hdr.startswith(b'(C) 1994 Origin Systems Inc.'))

    def test_compressed_member_is_refused(self):
        data = sg.Im1.pack(sg.GAMEDAT)
        f = sg.Flex.parse(data)
        f.entries[1].tail = f.entries[1].tail[:4] + b'\x01' + f.entries[1].tail[5:]
        with tempfile.TemporaryDirectory() as t, self.assertRaises(NotImplementedError):
            sg.Im1.unpack(f.encode(), t)


if __name__ == '__main__':
    unittest.main()
