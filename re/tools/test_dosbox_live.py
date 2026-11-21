import pathlib
import sys
import tempfile
import json
import threading
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import dosbox_live as live


class Socket:
    def __init__(self, reply): self.reply = reply.encode()
    def sendall(self, data): self.sent = data
    def recv(self, size): data, self.reply = self.reply, b''; return data


class DebuggerTests(unittest.TestCase):
    def test_script_variables_reads_named_signed_values_without_writes(self):
        table = b'_BARS3_ON'.ljust(25, b'\0') + live.struct.pack('<i', 0)
        table += b'_BOT_BLOWN'.ljust(25, b'\0') + live.struct.pack('<i', -1)
        dbg = mock.Mock()
        dbg.dump.side_effect = [live.struct.pack('<3H', 2, 0x100, 0x1234), table]
        self.assertEqual(live.script_variables(dbg, ['_bars3_on', '_BOT_BLOWN']),
                         {'_BARS3_ON': 0, '_BOT_BLOWN': -1})
        self.assertEqual(dbg.dump.call_args_list[0].args, (live.DGROUP, 0xcaf6, 6))
        self.assertEqual(dbg.dump.call_args_list[1].args, ('1234', 0x100, 58))
        dbg.exec.assert_not_called()

    def test_script_processes_reads_paused_flags_links_and_timeline_clocks(self):
        pack = live.struct.pack
        camera = b'\0\0CE33'.ljust(11, b'\0')
        memory = {
            (live.DGROUP, 0x9896): pack('<H', 2), (live.DGROUP, 0x9888): pack('<HH', 0x10, 0x2000), (live.DGROUP, 0x2f1d): pack('<HH', 0x40, 0x3000),
            ('2000', 0x10): pack('<HHHH', 0x100, 0x4000, 0x200, 0x4000),
            ('3000', 0x40): pack('<HHHHHHh', 0, 0, 0, 0, 0x100, 0x4000, 1) + pack('<HH', 0x50, 0x3000) + bytes(0x36 - 0x12),
            ('3000', 0x50): camera,
            ('4000', 0x100): (pack('<HHH', 0, 0, 0) + pack('<H', 0x10a) + bytes(6) + pack('<H', 1)).ljust(0x38, b'\0') + pack('<I', 18) + bytes(4),
            ('4000', 0x100 + 0xe93): pack('<HH', 0x600, 0x5000),
            ('5000', 0x600): b'ANIMCRYO'.ljust(25, b'\0'), ('5000', 0x622): b'[',
            ('4000', 0x100 + 0xea2): pack('<II', 1613, 1617),
            ('4000', 0x200): (pack('<HHH', 0, 0, 0) + pack('<H', 0x108)).ljust(0x40, b'\0'),
        }
        dbg = mock.Mock()
        dbg.dump.side_effect = lambda sel, off, length: memory[(sel, off)]
        self.assertEqual(live.script_processes(dbg), [{'block': 'ANIMCRYO', 'serial': 18, 'paused': True, 'waiting': False,
                                                       'cameras': ['CE33'], 'origin': 1613, 'due': 1617}])
        dbg.exec.assert_not_called()

    def test_force_camera_writes_the_forced_slot_and_the_auto_flag(self):
        pack = live.struct.pack
        memory = {(live.DGROUP, 0x1d01): pack('<H', 1), (live.DGROUP, 0x1d09): pack('<HH', 0x10, 0x2000), ('2000', 0x10): pack('<HH', 0x34, 0x3000),
                  ('3000', 0x34): b'\0\0CE11'.ljust(11, b'\0')}
        dbg = mock.Mock()
        dbg.dump.side_effect = lambda sel, off, length: memory[(sel, off)]
        live.force_camera(dbg, 'ce11', False)
        self.assertEqual([c.args[0] for c in dbg.exec.call_args_list], ['SM 040F:63D6 034 000 000 030', 'SM 040F:63DA 000'])
        with self.assertRaises(ValueError):
            live.force_camera(dbg, 'NOSUCH')

    def test_flag_named_byte_values_and_key_break_codes_are_numeric_literals(self):
        dbg = mock.Mock()
        live.set_bytes(dbg, 0x1234, 0x10, bytes([0xAC, 0xAF, 0xCF, 0xDF]))
        self.assertEqual(dbg.exec.call_args.args[0], 'SM 1234:0010 0AC 0AF 0CF 0DF')
        live.key(dbg, 0xCF)
        self.assertEqual(dbg.exec.call_args.args[0], 'OUTP 60 0CF')

    def test_background_worker_has_its_own_session_and_preserves_control_args(self):
        with tempfile.TemporaryDirectory() as directory, \
             mock.patch.object(live.subprocess, 'Popen') as spawn:
            spawn.return_value.pid = 123
            state = live.launch_background([directory, '--control', directory + '/control', '--background'],
                                           directory, directory + '/control')
            self.assertTrue(spawn.call_args.kwargs['start_new_session'])
            self.assertEqual(spawn.call_args.kwargs['stdin'], live.subprocess.DEVNULL)
            self.assertNotIn('--background', spawn.call_args.args[0])
            self.assertIn('--control', spawn.call_args.args[0])
            self.assertEqual(json.loads(pathlib.Path(directory, 'controller.json').read_text()), state)

    def test_request_rejects_mcp_error(self):
        dbg = live.Debugger(Socket('BEGIN 1 ERR unavailable\nEND 1'), '.')
        with self.assertRaisesRegex(RuntimeError, 'rejected'):
            dbg.pause()

    def test_request_reconnects_once_after_eof(self):
        first = Socket('')
        second = Socket('BEGIN 2 OK\nEND 2')
        dbg = live.Debugger(first, '.', reconnect=lambda: second)
        self.assertIn('BEGIN 2 OK', dbg.pause())
        self.assertEqual(first.sent, b'REQ 1 BREAK\n')
        self.assertEqual(second.sent, b'REQ 2 BREAK\n')

    def test_bplist_accepts_an_empty_wire_listing(self):
        class D:
            def exec(self, command):
                self.assertEqual(command, 'BPLIST')
                return '\nBEGIN 137 OK\nBreakpoint list:\n----\n'
            def assertEqual(self, left, right):
                if left != right: raise AssertionError((left, right))
        self.assertEqual(live.list_breakpoints(D()), set())

    def test_set_s32_uses_one_atomic_sm_command(self):
        class D:
            def __init__(self): self.commands = []
            def exec(self, command): self.commands.append(command)
        dbg = D()
        live.set_s32(dbg, 0x1234, 0x5678, -3133)
        self.assertEqual(dbg.commands, ['SM 1234:5678 0C3 0F3 0FF 0FF'])

    def test_set_figure_z_translates_cached_hull(self):
        figure = bytearray(0x1000)
        model = bytearray(0x1000)
        struct = live.struct
        struct.pack_into('<HH', figure, 0x117, 0x200, 0x2345)
        struct.pack_into('<i', figure, 0x16d, -7405)
        struct.pack_into('<i', figure, 0x179, -5133)

        class D:
            memory = {0x1234: figure, 0x2345: model}
            def dump(self, selector, offset, length):
                return bytes(self.memory[int(selector, 16)][offset:offset + length])
            def exec(self, command):
                _, address, *values = command.split()
                selector, offset = address.split(':')
                data = self.memory[int(selector, 16)]
                data[int(offset, 16):int(offset, 16) + len(values)] = bytes(int(v, 16) for v in values)

        before = {'name': 'LEX', 'ptr': (0x100, 0x1234), 'pos': [-1, -2, -5133],
                  'hull': [0, 0, -7405, 0, 0, -5133], 'hull_bottom': -7405, 'F': 2312, 'R': -40}
        with mock.patch.object(live, 'sample', return_value={'figures': [before]}):
            returned = live.set_figure_z(D(), 'LEX', -3133)
        self.assertIs(returned, before)
        self.assertEqual(struct.unpack_from('<i', figure, 0x113)[0], -3133)
        self.assertEqual(struct.unpack_from('<i', figure, 0x16d)[0], -5405)
        self.assertEqual(struct.unpack_from('<i', figure, 0x179)[0], -3133)
        self.assertEqual(struct.unpack_from('<i', model, 0x294)[0], -5405)

    def test_set_figure_xy_translates_model_and_cached_hull(self):
        figure, model = bytearray(0x1000), bytearray(0x1000)
        struct = live.struct
        struct.pack_into('<HH', figure, 0x117, 0x200, 0x2345)
        struct.pack_into('<2i', figure, 0x10b, -100, 200)
        struct.pack_into('<6i', figure, 0x165, -130, 170, -7405, -70, 230, -5133)
        struct.pack_into('<2i', model, 0x231, -96, 204)
        struct.pack_into('<3i', model, 0x28c, -1000, 3000, 9999)

        class D:
            memory = {0x1234: figure, 0x2345: model}
            def dump(self, selector, offset, length):
                return bytes(self.memory[int(selector, 16)][offset:offset + length])
            def exec(self, command):
                _, address, *values = command.split()
                selector, offset = address.split(':')
                data = self.memory[int(selector, 16)]
                data[int(offset, 16):int(offset, 16) + len(values)] = bytes(int(v, 16) for v in values)

        before = {'name': 'LEX', 'ptr': (0x100, 0x1234), 'pos': [-100, 200, -5133],
                  'hull': [-130, 170, -7405, -70, 230, -5133], 'support': -7405}
        dbg = D()
        with mock.patch.object(live, 'sample', return_value={'figures': [before]}):
            returned, model_xy = live.set_figure_xy(dbg, 'LEX', 500, -400)
        live.verify_set_xy(dbg, returned, model_xy, 500, -400)
        self.assertEqual(struct.unpack_from('<2i', figure, 0x10b), (500, -400))
        self.assertEqual(struct.unpack_from('<2i', model, 0x231), (504, -396))
        self.assertEqual(struct.unpack_from('<3i', model, 0x28c), (-400, 2400, 9999))
        self.assertEqual(struct.unpack_from('<2i', figure, 0x165), (470, -430))
        self.assertEqual(struct.unpack_from('<2i', figure, 0x171), (530, -370))

    def test_set_figure_xy_rejects_translated_overflow_before_writing(self):
        figure, model = bytearray(0x1000), bytearray(0x1000)
        struct = live.struct
        struct.pack_into('<HH', figure, 0x117, 0x200, 0x2345)
        struct.pack_into('<2i', model, 0x231, (1 << 31) - 1, 204)
        struct.pack_into('<2i', model, 0x28c, -1000, 3000)

        class D:
            memory = {0x1234: figure, 0x2345: model}
            def __init__(self): self.commands = []
            def dump(self, selector, offset, length):
                return bytes(self.memory[int(selector, 16)][offset:offset + length])
            def exec(self, command): self.commands.append(command)

        before = {'name': 'LEX', 'ptr': (0x100, 0x1234), 'pos': [-100, 200, -5133],
                  'hull': [-130, 170, -7405, -70, 230, -5133], 'support': -7405}
        dbg = D()
        with mock.patch.object(live, 'sample', return_value={'figures': [before]}):
            with self.assertRaisesRegex(ValueError, 'translated figure coordinates'):
                live.set_figure_xy(dbg, 'LEX', -99, 200)
        self.assertEqual(dbg.commands, [])

    def test_set_heading_writes_only_persistent_matrix(self):
        struct = live.struct
        for degrees, expected in ((0, (256, 0, 0, 0, 256, 0, 0, 0, 256)),
                                  (90, (0, -256, 0, 256, 0, 0, 0, 0, 256)),
                                  (180, (-256, 0, 0, 0, -256, 0, 0, 0, 256))):
            figure = bytearray(b'\xa5' * 0x400)
            figure[0x110] = 1
            original_header, original_tail = bytes(figure[:0x111]), bytes(figure[0x135:])

            class D:
                memory = {0x1234: figure}
                def dump(self, selector, offset, length):
                    return bytes(self.memory[int(selector, 16)][offset:offset + length])
                def exec(self, command):
                    _, address, *values = command.split()
                    selector, offset = address.split(':')
                    data = self.memory[int(selector, 16)]
                    data[int(offset, 16):int(offset, 16) + len(values)] = bytes(int(v, 16) for v in values)

            before = {'name': 'LEX', 'ptr': (0, 0x1234), 'pos': [1, 2, -5133],
                      'support': -7405, 'motion': 'DEFEND', 'base_heading': 13.0}
            with mock.patch.object(live, 'sample', return_value={'figures': [before]}):
                result = live.set_figure_heading(D(), 'LEX', degrees)
            self.assertEqual(struct.unpack_from('<9i', figure, 0x111), expected)
            self.assertEqual(bytes(figure[:0x111]), original_header)
            self.assertEqual(bytes(figure[0x135:]), original_tail)
            self.assertEqual(result['before'], before)
            self.assertEqual(result['base_heading'], float(degrees if degrees != 180 else 180))

    def test_set_heading_rejects_nonfinite_and_turning_motion(self):
        class D:
            def pause(self): raise AssertionError('must not pause')
        for value in (float('nan'), float('inf'), -float('inf')):
            with self.assertRaisesRegex(ValueError, 'finite'):
                live.control_dispatch(D(), {'command': 'set_heading', 'value': value})
        before = {'name': 'LEX', 'ptr': (0, 0x1234), 'pos': [1, 2, -5133],
                  'support': -7405, 'motion': 'TURN_LEFT'}
        with mock.patch.object(live, 'sample', return_value={'figures': [before]}):
            with self.assertRaisesRegex(RuntimeError, 'turning motion'):
                live.set_figure_heading(mock.Mock(), 'LEX', 0)

    def test_phys_top_disables_named_ceiling_and_verifies_writes(self):
        dgroup, pointers, phys = bytearray(0x2000), bytearray(4), bytearray(0x100)
        struct = live.struct
        struct.pack_into('<H', dgroup, 0x1cf5, 1)
        struct.pack_into('<HH', dgroup, 0x1cfd, 0x10, 0x2345)
        struct.pack_into('<HH', pointers, 0, 0x100, 0x2345)
        phys[2:6] = b'CE3\0'
        struct.pack_into('<i', phys, 0x3d, -2583)
        phys[0x4a] = 0

        class D:
            memory = {0x40f: dgroup, 0x2345: bytearray(0x1000)}
            memory[0x2345][0x10:0x14] = pointers
            memory[0x2345][0x100:0x14b] = phys
            def dump(self, selector, offset, length):
                return bytes(self.memory[int(selector, 16)][offset:offset + length])
            def exec(self, command):
                _, address, *values = command.split()
                selector, offset = address.split(':')
                data = self.memory[int(selector, 16)]
                data[int(offset, 16):int(offset, 16) + len(values)] = bytes(int(v, 16) for v in values)

        result = live.set_phys_top(D(), 'CE3', 0)
        self.assertEqual(result['before'], {'name': 'CE3', 'state': 0, 'top_z': -2583})
        self.assertEqual((result['top_z'], result['state']), (0, 0))

    def test_phys_top_refuses_a_solid_object_without_writing(self):
        record = bytearray(b'\0' * 0x4b)
        record[2:6], record[0x4a] = b'CE3\0', 1
        with mock.patch.object(live, 'phys_record', return_value=(0x100, 0x2345, bytes(record))), \
             mock.patch.object(live, 'set_s32') as set_s32:
            with self.assertRaisesRegex(RuntimeError, 'solid'):
                live.set_phys_top(mock.Mock(), 'CE3', 0)
        set_s32.assert_not_called()

    def test_config_uses_normal_new_game_timing_without_emulator_state(self):
        checked = live.config_text(7, '/tmp/c', 'esc esc enter enter', 30, 6)
        plain = live.config_text(7, '/tmp/c', 'esc')
        self.assertIn('mcp_server=7', plain)
        self.assertNotIn('savefile=', plain)
        self.assertIn('AUTOTYPE -w 30 -p 6 esc', plain)
        self.assertIn('AUTOTYPE -w 30 -p 6 esc esc enter enter', checked)

    def test_run_for_pauses_between_intervals(self):
        class D:
            def __init__(self): self.calls = []
            def pause(self): self.calls.append('pause')
            def run(self): self.calls.append('run')
        dbg = D()
        state = {'figures': [{'name': 'LEX', 'ptr': (1, 2)}]}
        focused = {'figures': [{'name': 'LEX', 'ptr': (1, 2), 'pos': [1, 2, 3]}]}
        with mock.patch.object(live, 'sample', side_effect=[state, focused, focused]), \
             mock.patch.object(live, 'game_clock', side_effect=[10, 11]), \
             mock.patch.object(live.time, 'sleep'):
            out = live.control_dispatch(dbg, {'command': 'run_for', 'seconds': .1, 'every': .05, 'figure': 'LEX'})
        self.assertEqual(len(out['samples']), 2)
        self.assertEqual(dbg.calls.count('run'), 2)
        self.assertGreaterEqual(dbg.calls.count('pause'), 4)

    def test_key_down_and_key_up_send_the_make_and_break_codes_while_the_cpu_runs(self):
        calls = []
        class D:
            def pause(self): calls.append('pause')
            def run(self): calls.append('run')
        with mock.patch.object(live, 'key', side_effect=lambda dbg, code: calls.append(code)), \
             mock.patch.object(live, 'game_clock', return_value=7):
            down = live.control_dispatch(D(), {'command': 'key_down', 'scan': '48'})
            up = live.control_dispatch(D(), {'command': 'key_up', 'scan': 0x48})
        self.assertEqual(calls, ['pause', 'run', 0x48, 'pause', 'pause', 'run', 0xC8, 'pause'])
        self.assertEqual((down, up), ({'clock': 7, 'paused': True},) * 2)

    def test_invalid_duration_never_runs(self):
        class D:
            def pause(self): raise AssertionError('must not pause')
        with self.assertRaises(ValueError):
            live.control_dispatch(D(), {'command': 'run_for', 'seconds': 1, 'every': 0})

    def test_nonfinite_or_unbounded_duration_never_runs(self):
        class D:
            def pause(self): raise AssertionError('must not pause')
        for request in ({'command': 'run_for', 'seconds': float('inf'), 'every': 1},
                        {'command': 'run_for', 'seconds': 1, 'every': float('nan')},
                        {'command': 'run_for', 'seconds': 1, 'every': 1e-320},
                        {'command': 'key', 'scan': '48', 'duration': float('nan')},
                        {'command': 'key', 'scan': '48', 'duration': 121}):
            with self.subTest(request=request), self.assertRaises(ValueError):
                live.control_dispatch(D(), request)

    def test_control_loop_keeps_running_request_until_dispatch_completes(self):
        with tempfile.TemporaryDirectory() as directory:
            incoming = pathlib.Path(directory, 'in')
            incoming.mkdir()
            started, release = threading.Event(), threading.Event()

            def dispatch(_dbg, request):
                if request['command'] == 'sample':
                    started.set()
                    self.assertTrue(release.wait(1))
                    return {'sampled': True}
                return {'quit': True}

            worker = threading.Thread(target=live.control_loop, args=(object(), directory))
            with mock.patch.object(live, 'control_dispatch', side_effect=dispatch):
                worker.start()
                (incoming / 'request.json').write_text(json.dumps({'command': 'sample'}))
                self.assertTrue(started.wait(1))
                self.assertFalse((incoming / 'request.json').exists())
                self.assertTrue(pathlib.Path(directory, 'running', 'request.json').exists())
                (incoming / 'request.json').unlink(missing_ok=True)
                release.set()
                deadline = live.time.monotonic() + 1
                while not pathlib.Path(directory, 'out', 'request.json').exists() and live.time.monotonic() < deadline:
                    live.time.sleep(.01)
                self.assertTrue(pathlib.Path(directory, 'out', 'request.json').exists())
                (incoming / 'quit.json').write_text(json.dumps({'command': 'quit'}))
                worker.join(1)
            self.assertFalse(worker.is_alive())

    def test_control_loop_skips_a_queue_cancellation_race(self):
        with tempfile.TemporaryDirectory() as directory:
            incoming = pathlib.Path(directory, 'in')
            incoming.mkdir()
            (incoming / 'cancelled.json').write_text(json.dumps({'command': 'sample'}))
            (incoming / 'quit.json').write_text(json.dumps({'command': 'quit'}))
            original_replace = live.os.replace

            def replace(source, target):
                if source.endswith('cancelled.json'):
                    raise FileNotFoundError(source)
                return original_replace(source, target)

            with mock.patch.object(live.os, 'replace', side_effect=replace), \
                 mock.patch.object(live, 'control_dispatch', return_value={'quit': True}) as dispatch:
                live.control_loop(object(), directory)
            self.assertEqual(dispatch.call_count, 1)

    def test_owned_emulator_requires_explicit_stop_on_quit(self):
        with tempfile.TemporaryDirectory() as directory:
            incoming = pathlib.Path(directory, 'in')
            incoming.mkdir()
            (incoming / '01.json').write_text(json.dumps({'command': 'quit'}))
            (incoming / '02.json').write_text(json.dumps({'command': 'quit', 'stop_emulator': True}))
            with mock.patch.object(live, 'control_dispatch', return_value={'quit': True}) as dispatch:
                live.control_loop(object(), directory, owns_emulator=True)
            rejected = json.loads(pathlib.Path(directory, 'out', '01.json').read_text())
            self.assertFalse(rejected['ok'])
            self.assertIn('owned emulator', rejected['error'])
            self.assertEqual(dispatch.call_count, 1)

    def test_key_releases_and_pauses_after_sleep_error(self):
        class D:
            def __init__(self): self.calls = []
            def pause(self): self.calls.append('pause')
            def run(self): self.calls.append('run')
        dbg, sent = D(), []
        with mock.patch.object(live, 'key', side_effect=lambda _dbg, code: sent.append(code)), \
             mock.patch.object(live.time, 'sleep', side_effect=RuntimeError('interrupted')):
            with self.assertRaisesRegex(RuntimeError, 'interrupted'):
                live.control_dispatch(dbg, {'command': 'key', 'scan': '48', 'duration': 1})
        self.assertEqual(sent, [0x48, 0xc8])
        self.assertEqual(dbg.calls[-1], 'pause')

    def test_key_releases_primary_then_modifiers_after_sleep_error(self):
        class D:
            def __init__(self): self.calls = []
            def pause(self): self.calls.append('pause')
            def run(self): self.calls.append('run')
        dbg, sent = D(), []
        with mock.patch.object(live, 'key', side_effect=lambda _dbg, code: sent.append(code)), \
             mock.patch.object(live.time, 'sleep', side_effect=RuntimeError('interrupted')):
            with self.assertRaisesRegex(RuntimeError, 'interrupted'):
                live.control_dispatch(dbg, {'command': 'key', 'scan': '48', 'modifiers': ['38', '1d'], 'duration': 1})
        self.assertEqual(sent, [0x38, 0x1d, 0x48, 0xc8, 0x9d, 0xb8])
        self.assertEqual(dbg.calls[-1], 'pause')

    def test_key_attempts_all_modifier_releases_when_primary_release_fails(self):
        class D:
            def __init__(self): self.calls = []
            def pause(self): self.calls.append('pause')
            def run(self): self.calls.append('run')
        dbg, sent = D(), []
        def send(_dbg, code):
            sent.append(code)
            if code == 0xc8:
                raise RuntimeError('release failed')
        with mock.patch.object(live, 'key', side_effect=send), \
             mock.patch.object(live.time, 'sleep'):
            with self.assertRaisesRegex(RuntimeError, 'release failed'):
                live.control_dispatch(dbg, {'command': 'key', 'scan': '48', 'modifiers': ['38', '1d'], 'duration': 1})
        self.assertEqual(sent, [0x38, 0x1d, 0x48, 0xc8, 0x9d, 0xb8])
        self.assertEqual(dbg.calls[-1], 'pause')

    def test_mouse_writes_the_callback_state_and_rejects_off_screen(self):
        class D:
            def __init__(self): self.commands = []
            def pause(self): pass
            def exec(self, command): self.commands.append(command)
        dbg = D()
        with mock.patch.object(live, 'game_clock', return_value=7):
            self.assertEqual(live.control_dispatch(dbg, {'command': 'mouse', 'x': 165, 'y': 103, 'buttons': 1}), {'clock': 7})
        self.assertEqual(dbg.commands, [f'SM {live.DGROUP}:7BAD 001 000 0A5 000 067 000', f'SM {live.DGROUP}:7B9F 001'])
        with self.assertRaisesRegex(ValueError, '320x200'):
            live.control_dispatch(dbg, {'command': 'mouse', 'x': 320, 'y': 0})

    def test_set_variable_writes_the_named_record_only(self):
        name = b'_IRIS_OPN'.ljust(25, b'\0')
        table = b'_OTHER'.ljust(25, b'\0') + live.struct.pack('<i', 9) + name + live.struct.pack('<i', -2)
        class D:
            def __init__(self): self.commands = []
            def pause(self): pass
            def exec(self, command): self.commands.append(command)
            def dump(self, selector, offset, length):
                return live.struct.pack('<3H', 2, 0x100, 0x1234) if length == 6 else table
        dbg = D()
        with mock.patch.object(live, 'game_clock', return_value=7):
            self.assertEqual(live.control_dispatch(dbg, {'command': 'set_variable', 'name': '_iris_opn', 'value': 1}), {'clock': 7, 'before': -2, 'value': 1})
        self.assertEqual(dbg.commands, ['SM 1234:0136 001 000 000 000'])
        with self.assertRaisesRegex(ValueError, 'unknown'):
            live.control_dispatch(dbg, {'command': 'set_variable', 'name': '_nope', 'value': 1})

    def test_unloaded_world_blocks_set_z_memory_writes(self):
        class D:
            def pause(self): pass
        with mock.patch.object(live, 'verify_ready', side_effect=RuntimeError('not ready')), \
             mock.patch.object(live, 'set_figure_z') as set_z:
            with self.assertRaisesRegex(RuntimeError, 'not ready'):
                live.control_dispatch(D(), {'command': 'set_z', 'value': -3133})
        set_z.assert_not_called()

    def test_frames_resolve_live_vtable_and_clean_up_owned_breakpoint(self):
        figure, stack = bytearray(4), bytearray(b'\xb6\x12\x6f\x02\x00\x00\x17\x47')
        live.struct.pack_into('<H', figure, 0, 0x2c4b)

        class D:
            def __init__(self): self.breakpoints, self.calls = set(), []
            def pause(self): self.calls.append('pause')
            def run(self): self.calls.append('run')
            def exec(self, command):
                self.calls.append(command)
                if command == 'BPLIST':
                    rows = '\n'.join(f'{ident:02d}. BP 0227:1EDD' for ident in self.breakpoints)
                    return f'Breakpoint list:\n----------\n{rows}\n'
                if command == 'BP 0227:1EDD': self.breakpoints.add(0); return ''
                if command == 'BPDEL 0': self.breakpoints.remove(0); return ''
                if command == 'EV CS EIP SS ESP':
                    return "EV of 'CS EIP SS ESP' is:\n227 1edd 417 5cce\n"
                raise AssertionError(command)
            def dump(self, selector, offset, length):
                if (selector, offset, length) == ('4717', 0, 2): return bytes(figure[:2])
                if (selector, offset, length) == ('040F', 0x2c53, 4): return b'\xdd\x1e\x27\x02'
                if (selector, offset, length) == ('0417', 0x5cce, 8): return bytes(stack)
                raise AssertionError((selector, offset, length))

        initial = {'figures': [{'name': 'LEX', 'ptr': (0, 0x4717)}]}
        focused = {'figures': [{'name': 'LEX', 'ptr': (0, 0x4717), 'frame': 42}]}
        dbg = D()
        with mock.patch.object(live, 'sample', side_effect=[initial, focused]), \
             mock.patch.object(live, 'game_clock', return_value=13211):
            result = live.frame_samples(dbg, 'LEX', 1)
        self.assertEqual(result['samples'][0]['clock'], 13211)
        self.assertEqual(result['samples'][0]['boundary']['entry'], {'cs': 0x227, 'ip': 0x1edd})
        self.assertEqual(result['samples'][0]['boundary']['figure_ptr'], [0, 0x4717])
        self.assertEqual(dbg.breakpoints, set())
        self.assertIn('BP 0227:1EDD', dbg.calls)
        self.assertIn('BPDEL 0', dbg.calls)

    def test_frames_timeout_removes_owned_breakpoint_and_pauses(self):
        class D:
            def __init__(self): self.breakpoints, self.calls = set(), []
            def pause(self): self.calls.append('pause')
            def run(self): self.calls.append('run')
            def exec(self, command):
                self.calls.append(command)
                if command == 'BPLIST':
                    rows = '\n'.join(f'{ident:02d}. BP 0227:1EDD' for ident in self.breakpoints)
                    return f'Breakpoint list:\n----------\n{rows}\n'
                if command == 'BP 0227:1EDD': self.breakpoints.add(0); return ''
                if command == 'BPDEL 0': self.breakpoints.remove(0); return ''
                if command == 'EV CS EIP SS ESP': return 'EV of \'CS EIP SS ESP\' is:\n1 2 3 4\n'
                raise AssertionError(command)
            def dump(self, selector, offset, length):
                if (selector, offset, length) == ('4717', 0, 2): return b'\x4b\x2c'
                if (selector, offset, length) == ('040F', 0x2c53, 4): return b'\xdd\x1e\x27\x02'
                raise AssertionError((selector, offset, length))

        initial = {'figures': [{'name': 'LEX', 'ptr': (0, 0x4717)}]}
        dbg = D()
        with mock.patch.object(live, 'sample', return_value=initial), \
             mock.patch.object(live.time, 'monotonic', side_effect=[0, 3]), \
             mock.patch.object(live.time, 'sleep'):
            with self.assertRaises(TimeoutError):
                live.frame_samples(dbg, 'LEX', 1)
        self.assertEqual(dbg.breakpoints, set())
        self.assertEqual(dbg.calls[-1], 'pause')

    def test_frames_refuse_an_unrelated_breakpoint(self):
        class D:
            def pause(self): pass
            def exec(self, command):
                self.command = command
                if command == 'BPLIST': return 'Breakpoint list:\n----------\n01. BP 0100:0200\n'
                raise AssertionError(command)
            def dump(self, selector, offset, length):
                if (selector, offset, length) == ('4717', 0, 2): return b'\x4b\x2c'
                if (selector, offset, length) == ('040F', 0x2c53, 4): return b'\xdd\x1e\x27\x02'
                raise AssertionError((selector, offset, length))

        initial = {'figures': [{'name': 'LEX', 'ptr': (0, 0x4717)}]}
        with mock.patch.object(live, 'sample', return_value=initial):
            with self.assertRaisesRegex(RuntimeError, 'already exist'):
                live.frame_samples(D(), 'LEX', 1)

    def test_frames_skip_other_instances_of_a_shared_update_wrapper(self):
        class D:
            def __init__(self): self.breakpoints, self.stack_hits = set(), 0
            def pause(self): pass
            def run(self): pass
            def exec(self, command):
                if command == 'BPLIST':
                    rows = '\n'.join(f'{ident:02d}. BP 0227:1EDD' for ident in self.breakpoints)
                    return f'Breakpoint list:\n----------\n{rows}\n'
                if command == 'BP 0227:1EDD': self.breakpoints.add(0); return ''
                if command == 'BPDEL 0': self.breakpoints.remove(0); return ''
                if command == 'EV CS EIP SS ESP': return 'EV of \'CS EIP SS ESP\' is:\n227 1edd 417 5cce\n'
                raise AssertionError(command)
            def dump(self, selector, offset, length):
                if (selector, offset, length) == ('4717', 0, 2): return b'\x4b\x2c'
                if (selector, offset, length) == ('040F', 0x2c53, 4): return b'\xdd\x1e\x27\x02'
                if (selector, offset, length) == ('0417', 0x5cce, 8):
                    self.stack_hits += 1
                    return (b'\x00\x00\x00\x00\x34\x12\x78\x56' if self.stack_hits == 1
                            else b'\x00\x00\x00\x00\x00\x00\x17\x47')
                raise AssertionError((selector, offset, length))

        initial = {'figures': [{'name': 'LEX', 'ptr': (0, 0x4717)}]}
        dbg = D()
        with mock.patch.object(live, 'sample', return_value=initial), \
             mock.patch.object(live, 'game_clock', return_value=1):
            result = live.frame_samples(dbg, 'LEX', 1)
        self.assertEqual(len(result['samples']), 1)
        self.assertEqual(dbg.stack_hits, 2)
        self.assertEqual(dbg.breakpoints, set())


if __name__ == '__main__':
    unittest.main()
