"""Tests: re/.venv/bin/python -I -m unittest re/interp/test_interp.py -v   (from the project root)"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import parse  # noqa: E402
import vm as vmmod  # noqa: E402

SCRIPTS = os.path.join(parse.ROOT, 're', 'out', 'scripts')
DEFS = parse.Defs()


def make_vm(src, **globs):
    """VM with a single inline script; extra globals (lower-case names, with leading _) are declared first."""
    defs = parse.Defs()
    defs.vars.update({k: v for k, v in globs.items()})
    for n in 'abcdefghrnx':
        defs.vars.setdefault('_' + n, 0)
    with tempfile.NamedTemporaryFile('w', suffix='.scr', delete=False, encoding='latin-1') as f:
        f.write(src)
    vm = vmmod.VM(defs=defs)
    try:
        fl = vm.load(f.name)
    finally:
        os.unlink(f.name)
    assert not fl.failures, fl.failures
    return vm


def run(src, block='MAIN', ticks=20, **globs):
    vm = make_vm(src, **globs)
    vm.fire(block)
    vm.run_ticks(ticks)
    return vm


def airhall():
    vm = vmmod.VM()
    vm.load(os.path.join(SCRIPTS, 'AIRHALL.scr'))
    return vm


class RealScripts(unittest.TestCase):
    def test_timeline_fire_frame(self):
        vm = airhall()
        vm.globals['_airmecho_dead'] = vm.defs.consts['_true']
        vm.fire('ANI_FIRE_FRAME')
        vm.run_ticks(60)
        seq = [(t, new) for t, n, old, new in vm.changes if n == '_fire_frame']
        t0 = seq[0][0]
        self.assertEqual([(t - t0, v) for t, v in seq[:9]], [(3 * i, i + 1) for i in range(9)])
        # RESETREALTIME + JUMP TOP: 00:27 resets the clock, so the second cycle starts 27 ticks later
        self.assertEqual((seq[9][0] - t0, seq[9][1]), (27, 1))

    def test_timeline_waits_while_not_dead(self):
        vm = airhall()
        vm.fire('ANI_FIRE_FRAME')                          # _airmecho_dead == _FALSE -> JUMP WAIT_HERE
        vm.run_ticks(30)
        self.assertFalse([c for c in vm.changes if c[1] == '_fire_frame'])

    def test_meetmech(self):
        vm = airhall()
        eng = vm.engine
        self.assertEqual(vm.globals['_airmecho_scene'], 0)
        vm.fire('MEETMECH')
        vm.run_ticks(400)
        self.assertEqual(vm.globals['_airmecho_scene'], 1)
        want = [('SETCURRENTFIGURE', ['PLAYER']), ('AI', ['OFF']), ('GO', ['LEX_POS']), ('FACE', [-90]),
                ('MOTION', ['STAND', 'CONTINUE']), ('CAMERA', ['HFR3'])]
        got = [(r[3], r[4]) for r in eng.log]
        it = iter(got)
        for w in want:                                     # in order (subsequence)
            self.assertTrue(any(g == w for g in it), f'{w} missing/out of order in {got[:8]}')
        # WAIT 2 SECONDS: _dr9_SPACE = _POSITIVE (tick T) then WAIT 2 SECONDS then SETCURRENTFIGURE AIRMECHO
        t_pos = [t for t, n, o, new in vm.changes if n == '_dr9_space' and new == 1][0]
        t_next = [r[0] for r in eng.log if r[3] == 'SETCURRENTFIGURE' and r[4] == ['AIRMECHO']][0]
        self.assertEqual(t_next - t_pos, 60)
        # the call to MARCHOUTAIRMECHO happened as a child process of MEETMECH
        self.assertEqual({r[1] for r in eng.log}, {'MARCHOUTAIRMECHO'})

    def test_meetmech_not_repeated(self):
        vm = airhall()
        vm.globals['_airmecho_scene'] = 1
        vm.fire('MEETMECH')
        vm.run_ticks(10)
        self.assertEqual(vm.engine.log, [])


class Semantics(unittest.TestCase):
    def test_call_return_args(self):
        vm = run('''{ MAIN
	_r = CALL ADD 3 4
	_a = 1
}
{ ADD
	LOCALVAR ~0 ~1
	WAIT 5
	RETURN ~0 + ~1
}''')
        self.assertEqual(vm.globals['_r'], 7)
        # caller blocked until the child returned at tick 5; the RETURN only wakes it (1238:077f), it runs in the next walk
        self.assertIn((6, '_r', 0, 7), vm.changes)
        self.assertIn((6, '_a', 0, 1), vm.changes)

    def test_call_no_return_value_is_zero(self):
        vm = run('{ MAIN\n\t_r = 5\n\t_r = CALL CHILD\n}\n{ CHILD\n\t_a = 1\n}')
        self.assertEqual(vm.globals['_r'], 0)

    def test_process_valid_kill(self):
        vm = run('''{ MAIN
	_h = PROCESS FOREVER
	_a = ISPROCESSVALID ( _h )
	SUSPEND
	KILLPROCESS _h
	_b = ISPROCESSVALID ( _h )
}
{ FOREVER
	:TOP
	_c ++
	SUSPEND
	JUMP TOP
}''')
        g = vm.globals
        self.assertEqual((g['_a'], g['_b'], g['_c']), (1, 0, 1))
        self.assertFalse(vm.procs)

    def test_suspendwhile_process(self):
        vm = run('{ MAIN\n\tSUSPENDWHILE PROCESS SLOW\n\t_a = 1\n}\n{ SLOW\n\tWAIT 10\n}')
        self.assertEqual([(t, n) for t, n, o, v in vm.changes], [(11, '_a')])     # SLOW ends at 10, MAIN goes on next walk

    def test_suspendwhile_modifyvar(self):
        vm = run('{ MAIN\n\tSUSPENDWHILE MODIFYVAREVERYNTH ( _b , +1, 1, 5, 4 )\n\t_a = 1\n}')
        self.assertEqual(vm.globals['_b'], 5)
        self.assertIn((17, '_a', 0, 1), vm.changes)

    def test_waiter_later_in_walk_sits_it_out(self):
        # SLOW ends at tick 3 during the walk; WAITER comes after it in the walk but is skipped once (1230:177a sets 0x40 on a task
        # woken above the walk index, 1230.c:173 skips it) and runs at 4. MAIN, before SLOW, already had its turn: also 4.
        vm = run('{ MAIN\n\t_h = PROCESS SLOW\n\t_g = PROCESS WAITER\n\tSUSPENDWHILE _h\n\t_b = 1\n}\n{ SLOW\n\tWAIT 3\n}\n'
                 '{ WAITER\n\tSUSPENDWHILE _h\n\t_a = 1\n}')
        self.assertEqual([(t, n) for t, n, o, v in vm.changes if n in ('_a', '_b')], [(4, '_b'), (4, '_a')])

    def test_call_child_ending_outside_walk(self):
        # engine code (no walk under way) kills a CALL child: the caller is only woken, and runs in the next walk
        vm = make_vm('{ MAIN\n\t_r = CALL CHILD\n\t_a = 1\n}\n{ CHILD\n\tSUSPEND\n\tJUMP CHILD\n}')
        vm.fire('MAIN')
        vm.run_ticks(2)
        child = next(p for p in vm.procs.values() if p.block.name == 'CHILD')
        vm.finish(child)
        self.assertEqual(vm.globals['_a'], 0)
        vm.run_ticks(1)
        self.assertEqual([(t, n) for t, n, o, v in vm.changes if n == '_a'], [(2, '_a')])

    def test_timeline_process_first_runs_next_walk(self):
        # PROCESS from a `[` block (10c0:37e9) does not run the child; the task constructor (1238.c:154) holds it for the walk
        vm = run('[ MAIN\n\t00:01 _h = PROCESS CHILD\n\t00:02 _b = 1\n]\n{ CHILD\n\t_a = 1\n}')
        (th,), (ta,) = [[t for t, n, o, v in vm.changes if n == k] for k in ('_h', '_a')]
        self.assertEqual(ta, th + 1)

    def test_wait_forms(self):
        vm = run('{ MAIN\n\t_x = 7\n\tWAIT _x\n\t_a = 1\n\tWAIT 2 SECONDS\n\t_b = 1\n}', ticks=100, _x=0)
        self.assertEqual([(t, n) for t, n, o, v in vm.changes if n in ('_a', '_b')], [(7, '_a'), (67, '_b')])

    def test_loop(self):
        vm = run('{ MAIN\n\t:L\n\t_a ++\n\tLOOP L 5\n\t_b = 1\n}')
        self.assertEqual((vm.globals['_a'], vm.globals['_b']), (5, 1))

    def test_switch(self):
        src = '''{ MAIN
	SWITCH ( _x )
		{
		CASE 1
			_r = 10
			BREAK 0
		CASE 2
			_r = 20
		CASE _TRUE_PLUS
			_r = _r + 5
			BREAK 0
		CASE 4:
			_r = 40
			BREAK 0
		DEFAULT
			_r = 99
			BREAK 0
		}
	_a = 1
}'''
        def go(x):
            vm = make_vm(src.replace('_TRUE_PLUS', '3'))
            vm.globals['_x'] = x
            vm.fire('MAIN')
            vm.run_ticks(2)
            self.assertEqual(vm.globals['_a'], 1)
            return vm.globals['_r']
        self.assertEqual([go(x) for x in (1, 2, 3, 4, 9)], [10, 25, 5, 40, 99])

    def test_bare_break_does_nothing(self):
        """An operand-less BREAK (inline `THEN BREAK`, never numbered by the compiler) is ERR_BREAK_NOT_PREPROCESSED in
        FUN_10d0_0b77: the next statement runs, the SWITCH is not left."""
        vm = make_vm('''{ MAIN
	SWITCH ( _x )
		{
		CASE 1
			IF _x == 1 THEN BREAK
			_r = 10
			BREAK 0
		}
	_a = 1
}''')
        vm.globals['_x'] = 1
        vm.fire('MAIN')
        vm.run_ticks(2)
        self.assertEqual((vm.globals.get('_r'), vm.globals['_a']), (10, 1))

    def test_if_else_forms(self):
        src = '''{ MAIN
	IF _x = 1 THEN _a = 1
	ELSE _a = 2
	IF _x == 1 THEN
		_b = 1
	ELSE
		_b = 2
	IF _x = 1 THEN
		{
		_c = 1
		}
	ELSE
		{
		_c = 2
		}
	IF _x != 1 THEN
		_d = 1
	ELSE _d = 2
	_x = 5
	_e = _x
}'''
        for x, want in ((1, (1, 1, 1, 2)), (0, (2, 2, 2, 1))):
            vm = run(src, _x=x)
            g = vm.globals
            self.assertEqual((g['_a'], g['_b'], g['_c'], g['_d']), want)
            self.assertEqual((g['_x'], g['_e']), (5, 5))   # `=` as a statement assigns

    def test_in_notin(self):
        src = '''{ MAIN
	IF _x IN 1, 2 THEN _a = 1
	IF _x NOTIN ( 5 , 6 ) THEN _b = 1
	IF ( _x IN -3,-1 ) AND ( _x NOTIN 2,3 ) THEN _c = 1   // `IN lo, hi` is an inclusive range
}'''
        r = lambda x: tuple(run(src, _x=x).globals[k] for k in '_a _b _c'.split())
        self.assertEqual([r(1), r(5), r(-2), r(7)], [(1, 1, 0), (0, 0, 0), (0, 1, 1), (0, 1, 0)])

    def test_jump_defid_other_block(self):
        src = '''{ MAIN
	_a = 0
	SWITCH ( _x )
		{
		CASE 5:
			_a = 7
			BREAK 0
		CASE 6:
			_a = 8
			BREAK 0
		}
}
{ OTHER
	JUMP #2
}'''
        vm = run(src, 'OTHER')
        self.assertEqual(vm.globals['_a'], 8)

    def test_member_locals_and_context(self):
        src = '{ MAIN\n\tSETCURRENTFIGURE FOO\n\tCURFIG.~3 = 9\n\t_a = CALL CHILD\n}\n{ CHILD\n\tRETURN CURFIG.~3\n}'
        vm = run(src)
        self.assertEqual(vm.globals['_a'], 9)               # children inherit CURFIG
        self.assertEqual(vm.objects['FOO'][3], 9)

    def test_fire_missing_block_is_noop(self):
        vm = make_vm('{ MAIN\n\t_a = 1\n}')
        self.assertIsNone(vm.fire('NOPE'))


class ParseAll(unittest.TestCase):
    def test_every_script_parses(self):
        names = [n for n in os.listdir(SCRIPTS) if n.lower().endswith('.scr')]
        self.assertEqual(len(names), 107)
        for n in sorted(names):
            f = parse.parse_file(os.path.join(SCRIPTS, n), DEFS)
            bad = [x for x in f.failures if x[3] not in parse.IGNORABLE]
            self.assertEqual(bad, [], n)
            self.assertEqual(f.def_count, f.def_claimed, n)

    def test_every_break_names_its_innermost_switch(self):
        """The compiler writes the innermost SWITCH's number into each BREAK, counting switches through the whole file
        (FUN_10c0_01cc); an inline `IF ... THEN BREAK` never gets one (only a line's first statement is read) and does nothing."""
        def breaks(stmts, stack):
            for s in stmts:
                if s.op == 'BREAK':
                    yield s, stack[-1] if stack else None
                if s.op == 'SWITCH':
                    yield from breaks(s.then, stack + [s.idx])
                else:
                    for sub in (s.then, s.els):
                        if sub:
                            yield from breaks(sub, stack)
        numbered, bare = 0, []
        for n in sorted(x for x in os.listdir(SCRIPTS) if x.lower().endswith('.scr')):
            f = parse.parse_file(os.path.join(SCRIPTS, n), DEFS)
            for b in f.blocks:
                for s, idx in breaks(b.body, []):
                    if not s.args:
                        bare.append((n, b.name, s.line))
                        continue
                    numbered += 1
                    self.assertEqual(s.args[0], ('num', idx), f'{n} {b.name}:{s.line}')
        self.assertEqual(numbered, 837)
        self.assertEqual(bare, [('AI_MECHO.scr', 'HALMECHOSPEECHES', line) for line in (321, 330, 339, 348, 357, 366)])


if __name__ == '__main__':
    unittest.main()
