"""Resuming a native save (resume.py): processes, handles, figures, items.
Samples (never modified): game/app/GAMEDAT (shipped, camera CE33) and re/out/native_save/gamedat (made in the original, CE31).
re/.venv/bin/python -I -W ignore -m unittest discover -s re/interp -p 'test_resume.py' -v"""
import math
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import parse  # noqa: E402
import resume  # noqa: E402
import world as worldmod  # noqa: E402

SHIPPED = worldmod.GAMEDAT
NATIVE = os.path.join(parse.ROOT, 're', 'out', 'native_save', 'gamedat')
_CACHE = {}


def boot(path):
    """A fresh (world, vm) per call; asset loading is cached by the module so this stays cheap."""
    return worldmod.World.from_native_state(path)


def names(vm):
    return {h: p.block.name for h, p in vm.procs.items() if p.block.kind != 'native'}


class Processes(unittest.TestCase):
    def test_shipped_processes_restored_by_name_and_handle(self):
        w, vm = boot(SHIPPED)
        self.assertEqual(names(vm), {838: 'DR_ZAP3_FIRSTBOT', 2218: 'CHOPOFFCAYNANSARM', 18: 'CELLONEBARS', 19: 'CELLTWOBARS',
                                     21: 'CELLTHREEBARS', 23: 'CELLFOURBARS', 24: 'CELL3_MON', 26: 'FLICKER_LIGHT',
                                     27: 'BLOCK_DRIP', 29: 'ANIMGUARD', 30: 'ANIMCRYO', 31: 'LEVEL1TREMORS'})
        self.assertEqual(vm.procs[2211].block.name, 'MODIFYVAREVERYNTH')
        self.assertEqual(len(w.resumed), 12)        # script processes; the ramp task is a native process
        self.assertEqual(w.warnings + vm.warnings, [])

    def test_native_processes_restored(self):
        w, vm = boot(NATIVE)
        self.assertEqual(names(vm), {233: 'NURSEBOT_AI', 881: 'WAITFORNURSEBOTSPEECH', 18: 'CELLONEBARS', 19: 'CELLTWOBARS',
                                     21: 'CELLTHREEBARS', 23: 'CELLFOURBARS', 24: 'CELL3_MON', 26: 'FLICKER_LIGHT',
                                     27: 'BLOCK_DRIP', 29: 'ANIMGUARD', 30: 'ANIMCRYO', 31: 'LEVEL1TREMORS'})
        self.assertEqual(w.warnings + vm.warnings, [])

    def test_a_paused_process_stays_paused(self):
        import tempfile
        import savegame
        w, vm = boot(NATIVE)
        with tempfile.TemporaryDirectory() as d:
            w.saves_dir = d
            running = [h for h, p in vm.procs.items() if p.block.kind != 'native' and not p.suspended and not p.cameras]     # a camera link overrides the bit on load
            vm.procs[running[0]].suspended = True
            out = os.path.join(d, 'GAME1.d')
            savegame.Im1.unpack(open(w.save_native(1), 'rb').read(), out)
            w2, vm2 = boot(out)
            self.assertTrue(vm2.procs[running[0]].suspended)
            self.assertFalse(vm2.procs[running[1]].suspended)

    def test_vars_handles_refer_to_restored_processes(self):
        for path in (SHIPPED, NATIVE):
            w, vm = boot(path)
            for var, block in (('_cellone' + 'process', 'CELLONEBARS'), ('_cellthreeprocess', 'CELLTHREEBARS'),
                               ('_cellfourprocess', 'CELLFOURBARS')):
                self.assertIn(vm.globals[var], vm.procs, var)
                self.assertEqual(vm.procs[vm.globals[var]].block.name, block)
        w, vm = boot(SHIPPED)
        self.assertIn(vm.globals['_ce3_modifyvar_handle'], vm.procs)         # 2211: the ramp task
        w, vm = boot(NATIVE)
        self.assertNotIn(vm.globals['_ce3_modifyvar_handle'], vm.procs)      # 43: the ramp had finished

    def test_new_handles_continue_above_the_saved_serial(self):
        for path, nxt in ((SHIPPED, 2305), (NATIVE, 891)):
            w, vm = boot(path)
            self.assertEqual(vm.next_handle, nxt)
            self.assertGreaterEqual(vm.timed_handle(5), nxt)

    def test_resume_position_is_pc_and_pc0_is_a_statement_start(self):
        import savegame
        for path in (SHIPPED, NATIVE):
            w, vm = boot(path)
            st = savegame.SaveState.load(path)
            for s in st.script.slots:
                if s.kind != 'proc':
                    continue
                rec, p = s.proc(), vm.procs[s.serial]
                f = p.block.file
                offs = {o: st_ for o, st_, _ in f.positions()}
                self.assertIn(rec.pc0, offs, f'{rec.script} {p.block.name} pc0 {rec.pc0:#x}')      # pc0 = start of a statement
                # the instruction the process resumes at belongs to the first statement at/after pc
                nxt = f.statements_from(rec.pc)[0][0]
                ins = p.code.ins[p.pc]
                self.assertTrue(ins.op == 'END' or ins.line >= nxt.line, (p.block.name, ins.line, nxt.line))
                if rec.pc != rec.pc0:                                  # executed pc0 statement is behind the resume point
                    self.assertGreater(rec.pc, rec.pc0)
                    self.assertEqual(offs[rec.pc0].op in ('WAIT', 'SUSPEND') or offs[rec.pc0].ts is not None, True, p.block.name)

    def test_timers_and_links(self):
        w, vm = boot(SHIPPED)
        self.assertEqual(vm.procs[2218].wake, 1696)               # WAIT 70 SECONDS (2100 ticks) with 1696 left
        self.assertEqual(vm.procs[24].wake, 5)                    # WAIT _Medical_Speed (10), 5 left
        self.assertEqual(vm.procs[31].wake, 5430)                 # WAIT RANDOM (300,600) SECONDS
        self.assertIs(vm.procs[838].wait_on, vm.procs[2218])      # CALL CHOPOFFCAYNANSARM in progress
        self.assertIn(vm.procs[838], vm.procs[2218].waiters)
        self.assertEqual(len(vm.procs[838].pending), 1)
        w, vm = boot(NATIVE)
        self.assertIs(vm.procs[233].wait_on, vm.procs[881])       # NURSEBOT_AI CALLs WAITFORNURSEBOTSPEECH
        self.assertEqual(vm.procs[233].cur_fig, 'FIRSTBOT')
        self.assertEqual(vm.procs[881].wait_on, None)

    def test_blocked_call_continues_when_the_child_ends(self):
        w, vm = boot(SHIPPED)
        parent, child = vm.procs[838], vm.procs[2218]
        at = parent.pc
        vm.finish(child)                                           # only wakes the caller (1238:077f) ...
        self.assertIsNone(parent.wait_on)
        self.assertEqual(parent.pc, at)
        vm.tick_once()                                             # ... the next walk re-enters the CALL statement, which completes
        self.assertNotEqual(parent.pc, at)
        self.assertEqual(w.warnings + vm.warnings, [])

    def test_locals_and_context(self):
        w, vm = boot(NATIVE)
        self.assertEqual(vm.procs[233].locals[:2], [0, 1])
        self.assertEqual(vm.procs[31].cur_fig, 'LEX')
        self.assertEqual(vm.procs[18].cur_fig, 'LEX')

    def test_ramp_task_resumes_with_saved_value(self):
        w, vm = boot(SHIPPED)
        self.assertEqual(vm.globals['_ce31_volume'], 20)
        vm.run_ticks(284)
        self.assertEqual(vm.globals['_ce31_volume'], 20)
        vm.run_ticks(2)
        self.assertEqual(vm.globals['_ce31_volume'], 30)           # next step after the 285 ticks left, then every 300

    def test_background_loops_run_cleanly(self):
        for path in (SHIPPED, NATIVE):
            w, vm = boot(path)
            for _ in range(300):
                vm.tick_once()
                w.step()
            self.assertEqual(w.warnings + vm.warnings, [], path)
            for h in (18, 19, 21, 23, 24, 26, 27, 29, 30, 31):
                self.assertIn(h, vm.procs)                         # none of the loops ended
            frames = {n for _, n, _, _ in vm.changes}
            self.assertIn('_br3_frame', frames)                # CELLTHREEBARS animates: CE33 and CE31 are in its list ...
            self.assertFalse({'_br2_frame', '_lht_frame'} & frames, frames)      # ... CELLTWOBARS / FLICKER_LIGHT are paused, as the original shows live on CE33


class Figures(unittest.TestCase):
    def test_resume_preserves_bouncy_flag(self):
        import savegame
        w, vm = boot(NATIVE)
        records = savegame.SaveState.load(NATIVE).levels['CHAOS'].records()
        nurse = next(r for tag, _, _, r in records if tag == 'FIGR' and r.inst.upper() == 'FIRSTBOT')
        nurse.flags |= resume.levelmod.F_BOUNCY
        resume._figures(w, vm, resume.Names(records))
        self.assertTrue(w.figures['FIRSTBOT'].bouncy)
        self.assertFalse(w.figures['LEX'].bouncy)

    def test_native_save_lex_and_nurse(self):
        w, vm = boot(NATIVE)
        lex, nurse = w.figures['LEX'], w.figures['FIRSTBOT']
        self.assertEqual(w.player_name, 'LEX')
        # the saved z (-5133) includes the STAND root z (-40); the prototype keeps root z in the pose
        self.assertEqual([round(x) for x in lex.pos], [-9715, -9164, -5093])
        self.assertEqual(round(lex.pos[2] + lex.frames[0][0][2]), -5133)
        self.assertAlmostEqual(lex.heading, 39.6, 1)
        self.assertAlmostEqual(nurse.heading, -143.8, 1)
        # Lex looks straight at the nurse and the nurse at Lex
        d = nurse.pos[:2] - lex.pos[:2]
        self.assertLess(abs(w.rel_angle(lex, nurse.pos)), 4)
        self.assertLess(abs(w.rel_angle(nurse, lex.pos)), 4)
        self.assertEqual((lex.motion, nurse.motion), ('STAND', 'ATK_STAND'))
        self.assertEqual((lex.enemy, nurse.enemy), ('FIRSTBOT', 'PLAYER'))
        self.assertTrue(nurse.combat and not lex.combat)
        self.assertIs(nurse.ai_proc, vm.procs[233])
        self.assertEqual(nurse.ai_type, 'NURSEBOT')
        self.assertEqual(nurse.view_cams, ['CE31', 'CE32', 'CE33'])
        self.assertIsNone(lex.view_cams)
        self.assertEqual(w.current_camera(), 'CE31')
        self.assertEqual(w.camera, 'CE31')                  # the restore's switch makes it current (1130:0114)

    def test_shipped_lex_heading_and_compass(self):
        w, vm = boot(SHIPPED)
        lex = w.figures['LEX']
        self.assertEqual([round(x) for x in lex.pos], [-11732, -11331, -5093])      # saved -5133 minus STAND root z (-40)
        self.assertAlmostEqual(lex.heading, -149.6, 1)
        self.assertEqual(w.current_camera(), 'CE33')
        self.assertEqual(w.figures['USE_BOT'].enemy, 'PLAYER')
        self.assertNotIn('FIRSTBOT', w.figures)                      # that nurse was removed from the shipped state

    def test_object_locals_hold_hit_points(self):
        w, vm = boot(NATIVE)
        self.assertEqual(vm.objects['LEX'][0], 96)                   # PLAYER.~0
        self.assertEqual(vm.objects['LEX'][5], 100)
        self.assertEqual(vm.objects['FIRSTBOT'][0], 50)
        self.assertEqual(vm.objects['CAYNAN'][0], 200)

    def test_carried_items(self):
        w, vm = boot(SHIPPED)
        self.assertEqual({k: (i.type, i.owner, i.slot) for k, i in w.items.items() if i.owner},
                         {'MEAT': ('MEAT1', 'LEX', 'INVENTORY'), 'LEXLOG': ('LOGBOOK', 'LEX', 'INVENTORY'),
                          'MY_BATTERY': ('MONBAT', 'LEX', 'INVENTORY')})
        self.assertEqual(sorted(k for k, i in w.items.items() if not i.owner),                # the other ITEM records lie on the floor
                         ['BLASTER', 'CAYARM', 'CAYLOG', 'DANELOG', 'FLUTE', 'FORK', 'PHOTO'])
        self.assertEqual(vm.objects['MY_BATTERY'][:3], [100, 100, 2])
        w, vm = boot(NATIVE)
        self.assertEqual([k for k, i in w.items.items() if i.owner], ['MY_BATTERY'])
        self.assertTrue(w.is_carrying(w.figures['LEX'], 'ANYWHERE', 'MONBAT'))

    def test_render_has_the_figures(self):
        w, vm = boot(NATIVE)
        img = w.render()
        self.assertEqual(img.shape, (200, 320, 3))
        self.assertGreater(len(set(map(tuple, img.reshape(-1, 3)[::37]))), 50)


class ScriptPositions(unittest.TestCase):
    """parse.File.positions: every statement gets its byte offset in the tokenized .SCP."""
    def test_known_offsets(self):
        f = parse.parse_file(os.path.join(parse.ROOT, 're', 'out', 'scripts', 'CHAOSBLK.scr'))
        stmts = f.statements_from(0x3285)
        self.assertEqual((stmts[0][0].op, stmts[0][0].line, stmts[0][1].name), ('SUSPEND', 626, 'CELLONEBARS'))
        stmts = f.statements_from(0x45da)                            # `\t\tWAIT _Medical_Speed` (after two tabs)
        self.assertEqual((stmts[0][0].op, stmts[0][0].line, stmts[0][0].col), ('WAIT', 898, 2))
        stmts = f.statements_from(0x328f)                            # a comment line: the next statement follows
        self.assertEqual(stmts[0][0].line, 629)

    def test_offsets_are_unique_statement_starts_in_every_file(self):
        d = os.path.join(parse.ROOT, 're', 'out', 'scripts')
        for fn in ('CHAOSBLK.scr', 'ZAP.scr', 'CHAOSGRD.scr', 'AI_NURSE.scr', 'COMMON.scr'):
            f = parse.parse_file(os.path.join(d, fn))
            raw = open(f.scp, 'rb').read()
            pos = f.positions()
            self.assertEqual(len({o for o, _, _ in pos}), len(pos))
            for o, st, b in pos:
                self.assertEqual(raw.count(b'\n', 0, o) + 1, st.line)
                self.assertNotIn(raw[o:o + 1], (b' ', b'\t', b'\r', b'\n'))

    def test_inline_statement_after_then(self):
        f = parse.parse_file(os.path.join(parse.ROOT, 're', 'out', 'scripts', 'CHAOSBLK.scr'))
        raw = open(f.scp, 'rb').read()
        inline = [(o, s) for o, s, b in f.positions() if s.op == 'RETURN' and raw[raw.rfind(b'\n', 0, o) + 1:o].count(b' ') > 4]
        self.assertTrue(inline)
        for o, s in inline:
            line = raw[raw.rfind(b'\n', 0, o) + 1:raw.find(b'\n', o)]
            self.assertIn(b'THEN', line)


if __name__ == '__main__':
    unittest.main()
