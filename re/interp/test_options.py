import os
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import numpy as np  # noqa: E402
import keys as keysmod  # noqa: E402
from options import AUDIO, CREDITS, DEFAULT, DIFFICULTY, EXIT, LOAD, MUST_RELOAD, Options, SAVE, credits_done, credits_lines, pimm_string  # noqa: E402
import settings as settingsmod  # noqa: E402
from settings import Settings  # noqa: E402
import movie  # noqa: E402
import vm as vmmod  # noqa: E402
import world as worldmod  # noqa: E402


class OptionsTests(unittest.TestCase):
    def test_main_screen_renders_the_original_frame(self):
        options = Options()
        options.open(DEFAULT)
        pixels, palette = options.render()
        self.assertEqual(options.screen, 'main')
        self.assertEqual(len(pixels), 320 * 200)
        self.assertEqual(len(palette), 768)
        self.assertGreater(len(set(pixels)), 5)
        self.assertIsNone(options.activate('DETX'))          # no DETX branch in the original callback: nothing happens
        self.assertEqual((options.screen, options.last_action, options.closed), ('main', None, False))

    def diff_rows(self, options):
        """Rows and colours of every pixel the label texts draw: a render against the same screen with all label text cleared."""
        with_text, _ = options.render()
        saved = {n: e.text for n, e in options.monitor.elements.items() if e.kind == 'L'}
        for n in saved:
            options.monitor.elements[n].text = ''
        without, _ = options.render()
        for n, t in saved.items():
            options.monitor.elements[n].text = t
        changed = np.flatnonzero(np.frombuffer(bytes(with_text), np.uint8) != np.frombuffer(bytes(without), np.uint8))
        return {(int(i) // 320, int(i) % 320): with_text[i] for i in changed}

    def test_pimm_strings_are_the_english_text_of_the_script_defines(self):
        self.assertEqual([pimm_string(k) for k in ('OKSTR', 'EXITSTR', 'LEVELEASYSTR', 'GAMMACORRECTIONSTR', 'QSAVEOVERSTR')],
                         ['SAVE SETTINGS', 'EXIT', 'EASY COMBAT', 'GAMMA', 'Save over this game?'])

    def test_main_screen_text_only_shows_in_label_elements(self):
        options = Options()
        options.open(DEFAULT)
        self.assertEqual(options.monitor.el('GMAL').text, 'GAMMA')
        self.assertEqual(options.monitor.el('CRDL').text, 'CREDITS')
        self.assertNotIn('DETX', options.monitor.elements)
        self.assertNotIn('DETX', options._controls)
        changed = self.diff_rows(options)
        for name, label in (('GMAL', 'GAMMA'), ('CRDL', 'CREDITS')):
            e = options.monitor.el(name)
            inside = [k for k in changed if e.y <= k[0] < e.y + e.h]
            self.assertTrue(inside, name)
            self.assertEqual({changed[k] for k in inside}, {e.colour(e.state)})
        rows = {k[0] for k in changed}
        self.assertTrue(all(166 <= r < 175 for r in rows), 'text only in the label band of the bottom bars')
        for name in ('EXTX', 'LODX', 'SAVX', 'AUDX', 'RETX'):            # these buttons have no label element: no text
            e = options.monitor.el(name)
            self.assertFalse([k for k in changed if e.y <= k[0] < e.y + e.h and e.x <= k[1] < e.x + e.w], name)

    def test_labels_of_the_other_screens_show_the_pimm_text(self):
        options = Options(settings=Settings(sound=40, music=60))
        label = lambda n: options.monitor.el(n).text
        options.open(DIFFICULTY)
        self.assertEqual([label(n) for n in ('EZYL', 'MEDL', 'HRDL')], ['EASY COMBAT', 'MEDIUM COMBAT', 'HARD COMBAT'])
        self.assertTrue(self.diff_rows(options))
        options.open(AUDIO)
        self.assertEqual((label('AOKL'), label('ACAL')), ('SAVE SETTINGS', 'CANCEL'))
        self.assertEqual(options.monitor.el('AOKX').text, 'SAVE SETTINGS')
        self.assertEqual(options.monitor.el('SFXX').text, 'SFX')
        self.assertEqual(options.monitor.el('MSCX').text, 'MUSIC')
        self.assertEqual(options.monitor.el('SFPX').text, '')
        self.assertTrue(self.diff_rows(options))
        options.open(DEFAULT)
        options.activate('GMAX')
        self.assertEqual((options.screen, label('AOKL'), label('ACAL')), ('gamma', 'SAVE SETTINGS', 'CANCEL'))      # ASSUMPTION panel
        options.open(LOAD)
        self.assertEqual((label('LOKL'), label('LCAL'), label('LNWL')), ('LOAD', 'CANCEL', 'NEW'))
        self.assertTrue(self.diff_rows(options))
        options.open(SAVE)
        self.assertEqual((label('LOKL'), label('LCAL'), label('LNWL')), ('SAVE', 'CANCEL', ''))
        self.assertFalse(options.monitor.el('LNWX').active)

    def test_confirm_prompts_follow_the_mode(self):
        options = Options(slot_used=lambda slot: slot == 2)
        label = lambda n: options.monitor.el(n).text
        options.open(EXIT)
        self.assertEqual((label('QSTL'), label('YESL'), label('NOOL')), ('Do you really want to quit?', 'YES', 'NO'))
        self.assertTrue(self.diff_rows(options))
        options.open(LOAD)
        options.activate('LOKX')
        self.assertEqual(label('QSTL'), 'Load this game?')
        self.assertEqual(options.monitor.el('SELG').frame, 0xf)
        options.activate('NOOX')
        options.activate('LNWX')
        self.assertEqual((label('QSTL'), options.monitor.el('SELG').frame), ('Begin New Game?', 0))
        options.open(SAVE)
        options.activate('LOKX')
        self.assertEqual((label('QSTL'), options.monitor.el('SELG').frame), ('Save this game?', 0))
        options.activate('NOOX')
        options.activate('SE2X')
        options.activate('LOKX')
        self.assertEqual((label('QSTL'), options.monitor.el('SELG').frame), ('Save over this game?', 0xf))
        self.assertEqual(options.activate('YESX'), 'save:2')

    def test_difficulty_selection_is_observable(self):
        options = Options()
        options.open(DIFFICULTY)
        self.assertEqual(options.screen, 'difficulty')
        hard = options.monitor.el('HRDX')
        self.assertEqual(options.pointer_move(hard.x + hard.w // 2, hard.y + hard.h // 2), 'HRDX')
        self.assertEqual(options.monitor.pointer['pos'], (hard.x + hard.w // 2, hard.y + hard.h // 2))
        self.assertEqual(options.click(hard.x + hard.w // 2, hard.y + hard.h // 2), 'difficulty:2')
        self.assertEqual(options.difficulty, 2)
        self.assertTrue(options.closed)

    def test_the_bar_under_the_pointer_is_drawn_highlighted(self):
        """FUN_1250_19bc: the control under the pointer goes to state 2 (FUN_1278_0803), a brighter bar (frame 2) and brighter label text;
        moving to another moves the highlight, moving off every control takes it away (FUN_1278_0844)."""
        options = Options()
        options.open(DIFFICULTY)
        options.monitor.pointer['frame'] = 0         # the hand is not drawn: only the bars differ
        options.pointer_move(0, 14)
        plain, _ = options.render()
        bars = ('EZYX', 'MEDX', 'HRDX')
        self.assertEqual([options.monitor.el(n).frame for n in bars], [1, 1, 1])
        med = options.monitor.el('MEDX')
        options.pointer_move(med.x + med.w // 2, med.y + med.h // 2)
        self.assertEqual([options.monitor.el(n).frame for n in bars], [1, 2, 1])
        label = options.monitor.el('MEDL')
        self.assertEqual((label.state, label.colour(label.state)), (2, label.header[0][1]))
        lit, _ = options.render()
        changed = {i for i in range(64000) if lit[i] != plain[i]}
        self.assertTrue(changed)
        self.assertTrue(all(med.y <= i // 320 < med.y + med.h for i in changed))     # only the hovered bar changes
        options.pointer_move(*self.hard_spot(options))
        self.assertEqual([options.monitor.el(n).frame for n in bars], [1, 1, 2])
        options.pointer_move(0, 14)
        self.assertEqual([options.monitor.el(n).frame for n in bars], [1, 1, 1])
        self.assertEqual(options.render()[0], plain)

    def test_a_panel_opens_with_the_control_under_the_pointer_highlighted(self):
        """FUN_1258_0512 runs FUN_1250_19bc for each button it defines. A default (state 2) takes the focus and the pointer until the mouse
        has moved ([9dca] & 2), then starts normal; a key's glide (FUN_1250_15ef) clears the flag again."""
        options = Options()
        options.open(DEFAULT)
        extx = options.monitor.el('EXTX')
        self.assertEqual((extx.frame, options.monitor.pointer['pos'], options.monitor.mouse_warp),
                         (2, (extx.x + extx.w // 2, extx.y + extx.h // 2), (extx.x + extx.w // 2, extx.y + extx.h // 2)))
        options.pointer_move(0, 14)
        self.assertEqual(extx.frame, 1)
        options.open(DIFFICULTY)
        options.pointer_move(*self.hard_spot(options))
        options.open(DEFAULT)                       # the mouse has moved: EXTX starts normal and the pointer stays
        self.assertEqual((extx.frame, options.monitor.pointer['pos']), (1, self.hard_spot(options)))
        options.open(DIFFICULTY)                    # the bar under the pointer is lit at once
        self.assertEqual([options.monitor.el(n).frame for n in ('EZYX', 'MEDX', 'HRDX')], [1, 1, 2])

    def test_a_selected_toggle_keeps_its_selection_under_the_highlight(self):
        """Mode 1 buttons (SFXX, MSCX, SBTX): the highlight turns 3 into 4 and taking it away gives 3 back; a plain button goes back to 1."""
        options = Options(settings=Settings(sound=60, music=30, subtitles=True))
        options.open(AUDIO)
        sfx = options.monitor.el('SFXX')
        self.assertEqual(sfx.frame, 3)
        options.pointer_move(sfx.x + sfx.w // 2, sfx.y + sfx.h // 2)
        self.assertEqual((sfx.frame, options.monitor.el('AOKX').frame), (4, 1))
        options.pointer_move(0, 14)
        self.assertEqual(sfx.frame, 3)

    def hard_spot(self, options):
        hard = options.monitor.el('HRDX')
        return hard.x + hard.w // 2, hard.y + hard.h // 2

    def test_pointer_click_activates_the_control_on_tick_6(self):
        """mouse down + up at once: pressed on tick 5 of the pointer's animation, activated by the release on tick 6 (update returns it)."""
        options = Options()
        options.open(DIFFICULTY)
        options.pointer_move(*self.hard_spot(options))
        options.mouse_down()
        options.mouse_up()
        got = [(tick, action) for tick in range(1, 13) for action in options.update()]
        self.assertEqual(got, [(6, 'difficulty:2')])
        self.assertEqual(options.difficulty, 2)
        self.assertTrue(options.closed)

    def test_held_mouse_keeps_the_pointer_until_the_release(self):
        options = Options()
        options.open(DIFFICULTY)
        spot = self.hard_spot(options)
        options.pointer_move(*spot)
        options.mouse_down()
        got = [a for _ in range(6) for a in options.update()]      # pressed on tick 5, the hold ends on tick 6, input stays off (FUN_1250_0415)
        options.pointer_move(0, 0)
        self.assertIsNone(options.key('ESCAPE'))
        self.assertEqual(options.monitor.pointer['pos'], spot)
        options.mouse_up()                                          # input back on, the mouse is put on the pointer
        self.assertEqual(options.monitor.mouse_warp, spot)
        got += [a for _ in range(12) for a in options.update()]
        self.assertEqual(got, ['difficulty:2'])

    def test_pointer_released_off_the_control_does_not_activate_it(self):
        options = Options()
        options.open(DIFFICULTY)
        options.pointer_move(*self.hard_spot(options))
        options.mouse_down()
        got = [a for _ in range(6) for a in options.update()]
        options.monitor.pointer['pos'] = (0, 14)                    # a pointer glide (MON_SIMULATE) can move it; a held mouse cannot
        options.mouse_up()
        got += [a for _ in range(12) for a in options.update()]
        self.assertEqual((got, options.closed, options.screen), ([], False, 'difficulty'))

    def test_tab_in_the_dialog_glides_over_its_controls_and_return_presses(self):
        options = Options()
        options.open(DIFFICULTY)
        mon = options.monitor
        mon.key_event(0x09, 0x0f)                          # the dialog's events end in the monitor's key handler (1280_callbacks.c)
        self.assertIsNotNone(mon.glide)
        self.assertIn(mon.focus.name, options._controls)
        for _ in range(80):
            options.update()
        self.assertEqual(options.hovered, mon.focus.name)
        mon.key_event(0x0d, 0x1c)
        got = [a for _ in range(4) for a in options.update()]     # the hand is past its first frame: the key's release ends the press
        mon.key_release(0x1c)
        got += [a for _ in range(30) for a in options.update()]
        self.assertEqual(len(got), 1)

    def test_right_click_closes_the_dialog_like_escape(self):
        options = Options()
        options.open(DEFAULT)
        options.right_click()                              # as the Escape key on the main panel
        self.assertTrue(options.closed)
        self.assertIsNone(options.right_click())

    def test_main_navigation_and_audio_controls(self):
        options = Options(settings=Settings(sound=40, music=60))
        options.open(DEFAULT)
        self.assertIsNone(options.activate('AUDX'))
        self.assertEqual(options.screen, 'audio')
        self.assertEqual(options.activate('SFPX'), 'audio:50,60')
        self.assertEqual(options.activate('MSMX'), 'audio:50,50')
        self.assertEqual(options.activate('AOKX'), 'audio:50,50')
        self.assertEqual((options.screen, options.closed), ('main', False))      # opened with _OPTS_DEFAULT: back to the main panel


    def test_credits_and_native_slot_selection_are_explicit(self):
        options = Options()
        options.open(CREDITS)
        pixels, _ = options.render()
        self.assertEqual(options.screen, 'credits')
        self.assertGreater(len(set(pixels)), 5)
        self.assertIsNone(options.key('ESCAPE'))                 # [4e3b] = 0x29a: keys wait for the first update
        options.update()
        self.assertEqual(options.key('ESCAPE'), 'return')
        self.assertIsNone(options.open(LOAD))
        self.assertEqual(options.screen, 'load')
        self.assertEqual(options.activate('SE9X'), None)
        self.assertEqual(options.slot, 9)
        self.assertEqual(options.monitor.el('SELG').frame, 9)
        options.activate('LRTX')
        self.assertEqual(options.slot, 9)
        options.activate('LLFX')
        self.assertEqual(options.slot, 8)
        self.assertIsNone(options.activate('LOKX'))
        self.assertEqual(options.screen, 'confirm')
        self.assertIsNone(options.activate('NOOX'))
        self.assertEqual(options.screen, 'load')
        options.activate('LOKX')
        self.assertEqual(options.activate('YESX'), 'load:8')
        self.assertIsNone(options.open(SAVE))
        self.assertEqual(options.screen, 'save')
        self.assertEqual(options.activate('LCAX'), 'cancel')


    def test_the_reload_dialog_stays_open_until_a_load(self):
        """After a death (MUST_RELOAD only) no way out of a sub-screen closes the dialog: OK, Cancel and No become Escape, which shows
        the exit prompt; Escape on that prompt goes to the main panel (1280_callbacks.c)."""
        options = Options()
        options.open(MUST_RELOAD)
        self.assertIsNone(options.key('ESCAPE'))
        self.assertEqual(options.screen, 'confirm')
        self.assertIsNone(options.key('ESCAPE'))
        self.assertEqual(options.screen, 'main')
        steps = [('RETURN',), ('LOAD', 'CANCEL'), ('NO',), ('LOAD', 'ESCAPE'), ('AUDIO', 'OK'), ('GAMMA', 'CANCEL'),
                 ('CREDITS', 'ESCAPE'), ('CREDITS', 'RETURN')]
        for step in steps:
            options.key('ESCAPE') if options.screen == 'confirm' else None
            for name in step:
                if options.screen == 'credits':
                    options.update()                                    # the key lockout ends with the first update
                options.key(name) if name == 'ESCAPE' else options.activate(name)
            self.assertFalse(options.closed, step)
        options.key('ESCAPE') if options.screen == 'confirm' else None
        options.activate('LOAD')
        options.activate('OK')
        self.assertEqual(options.activate('YES'), 'load:1')
        self.assertTrue(options.closed)

    def test_cancel_on_the_slots_goes_back_to_the_main_panel(self):
        options = Options()
        options.open(DEFAULT)
        options.activate('LOAD')
        self.assertEqual(options.activate('CANCEL'), 'cancel')
        self.assertEqual(options.screen, 'main')
        self.assertFalse(options.closed)
        options.activate('LOAD')
        self.assertEqual(options.key('ESCAPE'), 'cancel')
        self.assertTrue(options.closed)


class CreditsRollTests(unittest.TestCase):
    """The credits page against the original's VGA dumps (re/out/credits_live/SPEC.md): pixel facts of the renderer at several scroll positions."""

    def setUp(self):
        self.options = Options()
        self.options.open(CREDITS)

    def rows(self, pos, lo=0, hi=200):
        idx, drawn = self.options.credits_pixels(pos)
        return idx, drawn, [r for r in range(lo, hi) if drawn[r].any()]

    def test_line_model_and_end_position(self):
        """251 display lines (the extra newline after a line is swallowed); the roll stops at 12 * (251 - 2 - 18 + 1) = 2784."""
        lines = self.options.credits_lines
        self.assertEqual((len(lines), lines[18], lines[19]), (251, ('BIOFORGE', True), ('A Ken Demarest Game', False)))
        self.assertEqual(credits_done(251), 2784)
        self.assertEqual(credits_lines('X\n\nY\nZ\n\n\n\nW\x00'), [('X', False), ('Y', False), ('Z', False), ('', False), ('W', False)])

    def test_first_text_scrolls_in_from_the_bottom(self):
        """s = 22 (live dump 0003): line 18 (BIOFORGE) has its baseline at 8 + 12 * 18 - 22 = 202, so only its top rows 196..199 show."""
        idx, drawn, rows = self.rows(22)
        self.assertEqual((rows[0], rows[-1]), (196, 199))
        self.assertEqual({int(v) for v in idx[drawn]}, {0, 200})     # the heading colour and its shadow
        idx, drawn, rows = self.rows(52)                     # BIOFORGE at baseline 172, then 'A Ken Demarest Game' at 184 (normal colour)
        self.assertEqual((rows[0], rows[-1]), (166, 185))
        self.assertEqual({int(v) for v in idx[166:173][drawn[166:173]]}, {0, 200})

    def test_end_picture(self):
        """s = 2784 (live dump f20021): BIOFORGE in colour 200 with cap rows 86-92, then the lines at baselines 104, 116 and 128 in 249; every
        glyph pixel has its shadow in palette 0 one pixel right and down."""
        idx, drawn, rows = self.rows(2784)
        self.assertEqual((rows[0], rows[-1]), (86, 130))
        self.assertEqual({int(v) for v in idx[86][drawn[86]]}, {200})
        self.assertEqual({int(v) for v in idx[92][drawn[92]]}, {0, 200})
        self.assertEqual({int(v) for v in idx[93][drawn[93]]}, {0})
        for baseline in (104, 116, 128):
            self.assertIn(249, {int(v) for v in idx[baseline][drawn[baseline]]})
        self.assertEqual(int(drawn[86].nonzero()[0][0]), 132)    # BIOFORGE is centred about x = 160
        self.assertEqual(int(drawn[116].nonzero()[0][0]), 63)
        self.assertEqual(int(drawn[116].nonzero()[0][-1]), 250)

    def test_tab_fields_start_at_the_stops(self):
        """Lines 148.. are tabbed: left aligned at 60 + 1 and 180 + 1 (the measuring pass counts every tab as 60 + 1, the drawing pass uses the x)."""
        pos = 8 + 12 * 148 - 100                              # line 148 '\tFrench\tDominique Poumeyrol' on baseline 100
        idx, drawn, _ = self.rows(pos)
        band = drawn[94:101]
        self.assertEqual(int(band.any(axis=0).nonzero()[0][0]), 61)
        self.assertFalse(band[:, 110:181].any())
        self.assertTrue(band[:, 181].any())
        self.assertEqual({int(v) for v in idx[94:101][band]}, {0, 249})

    def test_states_and_key_lockout(self):
        o = self.options
        done = credits_done(len(o.credits_lines))
        self.assertEqual((o.credits_state, o.credits_pos, o.credits_lockout), (0, 0, True))
        self.assertIsNone(o.key('ESCAPE'))
        o.update()
        self.assertEqual((o.credits_state, o.credits_pos, o.credits_lockout), (1, 1, False))
        for _ in range(done - 1):
            o.update()
        self.assertEqual((o.credits_state, o.credits_pos), (1, done))      # the update that reaches the end still reports 1
        o.update()
        self.assertEqual((o.credits_state, o.credits_pos), (2, done))      # state 2 from the next update, the picture stays
        o.update()
        self.assertEqual((o.credits_state, o.credits_pos), (2, done))
        self.assertEqual(o.key('ESCAPE'), 'return')


class OptionsTimingTests(unittest.TestCase):
    def setUp(self):
        self.world = worldmod.World('CHAOS', state_dir=worldmod.INITGAME)
        self.vm = vmmod.VM(self.world)
        vmmod.load_level(self.vm, 'CHAOS')

    def script(self, text):
        with tempfile.NamedTemporaryFile('w', suffix='.scr', delete=False) as source:
            source.write(text)
        try:
            self.vm.load(source.name)
        finally:
            os.unlink(source.name)

    def test_mon_code_returns_to_its_caller_immediately(self):
        self.script('''
{ CALLER
    MON_CODE _OPTS_DEFAULT
    _after_options = 1
}
{ OTHER
    _other_ran = 1
}
''')
        caller = self.vm.spawn('CALLER')
        self.vm.spawn('OTHER')
        self.assertEqual(self.world.options.screen, 'main')
        self.assertIsNone(caller.wait_pred)
        self.assertEqual(self.vm.globals['_after_options'], 1)
        self.assertEqual(self.vm.globals['_other_ran'], 1)

    def open_options(self, flags=DEFAULT):
        self.world.options = Options()
        self.world.options.open(flags)

    def frame(self):
        self.vm.tick_once()
        self.world.step()

    def test_open_dialog_freezes_scripts_and_clock(self):
        self.script("""
{ TICKER
    _ticks = 1
    SUSPEND
    _ticks = 2
}
""")
        self.vm.spawn('TICKER')
        self.open_options()
        self.assertTrue(self.world.paused)
        tick = self.vm.tick
        for _ in range(5):
            self.frame()
        self.assertEqual((self.vm.globals['_ticks'], self.vm.tick), (1, tick))
        self.world.options.closed = True
        self.assertFalse(self.world.paused)
        self.frame()
        self.frame()
        self.assertEqual((self.vm.globals['_ticks'], self.vm.tick), (2, tick + 2))

    def test_open_dialog_freezes_timers(self):
        self.script("""
{ TIMER
    WAIT 3
    _timer_done = 1
}
""")
        self.vm.spawn('TIMER')
        self.frame()
        self.open_options()
        for _ in range(10):
            self.frame()
        self.assertNotIn('_timer_done', self.vm.globals)
        self.world.options.closed = True
        for _ in range(4):
            self.frame()
        self.assertEqual(self.vm.globals['_timer_done'], 1)

    def test_open_dialog_freezes_figures_and_camera_selection(self):
        self.open_options()
        with patch.object(self.world, 'apply_player_input') as movement, \
                patch.object(self.world, 'update_camera') as camera:
            self.frame()
            movement.assert_not_called()
            camera.assert_not_called()
            self.world.options.closed = True
            self.frame()
            movement.assert_called_once()
            camera.assert_called_once()

    def test_open_dialog_hides_subtitles(self):
        self.world.subtitle_log.append((0, 1, 5, 'HELLO', 100))
        self.assertEqual(self.world.active_subtitle(10), (5, 'HELLO'))
        self.open_options()
        self.assertIsNone(self.world.active_subtitle(10))
        self.world.options.closed = True
        self.assertEqual(self.world.active_subtitle(10), (5, 'HELLO'))

    def test_dialog_ui_stays_responsive_while_paused(self):
        self.open_options()
        self.frame()
        self.assertEqual(len(self.world.options.render()[0]), 320 * 200)
        self.assertIsNone(self.world.option_activate('AUDX'))
        self.assertEqual(self.world.options.screen, 'audio')
        self.assertEqual(self.world.option_activate('SFMX'), 'audio:90,100')
        self.assertTrue(self.world.paused)

    def test_credits_page_does_not_pause_and_reports_its_state(self):
        """FUN_1280_221e resumes the game at once: the world, clock and scripts run under the roll. CREDITSSTATE [9ce5] 0, 1 while scrolling, 2 at the
        end, 0 again once the page closes (FUN_1100_0ae6)."""
        self.assertEqual(self.world.credits_state(), 0)
        self.world.open_options(CREDITS)
        self.assertFalse(self.world.paused)
        self.assertEqual(self.world.credits_state(), 0)
        tick = self.vm.tick
        self.frame()
        self.assertEqual((self.vm.tick, self.world.credits_state(), self.world.options.credits_pos), (tick + 1, 1, 1))
        done = credits_done(len(self.world.options.credits_lines))
        for _ in range(done + 5):
            self.frame()
        self.assertEqual((self.world.credits_state(), self.world.options.credits_pos), (2, done))
        self.assertEqual(self.vm.tick, tick + 1 + done + 5)
        self.assertEqual(self.world.option_key('ESCAPE'), 'return')
        self.assertTrue(self.world.options.closed)
        self.assertEqual(self.world.credits_state(), 0)

    def test_mon_code_credits_opens_during_a_flic_and_while_frozen(self):
        """10a8:02cc has no flic test. ENDGAME's FREEZE stops the world update, camera selection and the game clock ([50be]); the credits page clears
        it (1100:0716) and closing does not set it again. The processes FREEZE suspended stay so until THAW."""
        self.world.flic = types.SimpleNamespace(running=False, armed=False, frame=None)
        self.world.cmd_freeze(None)
        self.assertTrue(self.world.frozen)
        self.frame()
        self.frame()
        stopped = self.world.game_tick
        self.world.open_options(CREDITS)
        self.assertEqual(self.world.options.screen, 'credits')
        self.assertFalse(self.world.frozen)
        stepped = []
        self.world.step_presentation = lambda: stepped.append(1)
        self.frame()
        self.frame()
        self.assertEqual(stepped, [1, 1])
        self.assertEqual(self.world.game_tick, stopped + 2)               # the game clock runs again
        self.world.options.update()
        self.world.option_key('ESCAPE')
        self.assertTrue(self.world.options.closed)
        self.frame()
        self.assertEqual((stepped, self.world.frozen), ([1, 1, 1], False))
        self.world.cmd_thaw()

    def test_credits_open_restarts_the_dialog_song_and_close_runs_creditsrolling(self):
        """FUN_1100_0740: a different song than [4e30] stops, then [4e30] restarts (when 0 or more). FUN_1100_0ae6 starts CREDITSROLLING."""
        started = []
        self.world.run_as_player = started.append
        self.world.current_music = 4
        self.world.open_options(DEFAULT)                                  # [4e30] = 4
        self.world.options.closed = True
        self.assertEqual(self.world.dialog_song, 4)
        self.world.current_music = 7
        self.world.open_options(CREDITS)
        self.assertEqual([m for _, m in self.world.music_log], [-1, 4])
        self.assertEqual(self.world.current_song(), 4)
        self.world.options.closed = True
        self.world.open_options(CREDITS)                                  # the same song: nothing
        self.assertEqual([m for _, m in self.world.music_log], [-1, 4])
        self.world.dialog_song = -1                                       # after a load: the music stops and stays off
        self.world.options.closed = True
        self.world.open_options(CREDITS)
        self.assertEqual(([m for _, m in self.world.music_log][2:], self.world.current_song()), ([-1], -1))
        self.world.options.update()
        self.world.option_key('ESCAPE')
        self.assertTrue(self.world.options.closed)
        self.assertEqual(started, ['CREDITSROLLING'])

    def test_main_panel_credits_button_resumes_once_and_nothing_pauses_again(self):
        """The Credits button runs FUN_1280_221e too (0716 + 0740 unless _forcing_reload); only 10a8:02cc sets [50be], so the main panel the page
        returns to stays over a running game, and closing the dialog (a36c set) starts CREDITSROLLING."""
        started = []
        self.world.run_as_player = started.append
        self.world.current_music = 4
        self.world.open_options(DEFAULT)
        self.assertTrue(self.world.paused)
        self.world.current_music = 7
        self.world.option_activate('CRDX')
        self.assertEqual((self.world.options.screen, self.world.paused), ('credits', False))
        self.assertEqual([m for _, m in self.world.music_log], [-1, 4])
        self.world.options.update()
        self.world.option_activate('RETURN')
        self.assertEqual((self.world.options.screen, self.world.paused), ('main', False))
        self.world.option_activate('RETX')
        self.assertTrue(self.world.options.closed)
        self.assertEqual(started, ['CREDITSROLLING'])
        self.world.forcing_reload = True                                  # a forced reload: stays paused
        self.world.open_options(DEFAULT)
        self.world.option_activate('CRDX')
        self.assertTrue(self.world.paused)

    def test_credits_during_forced_reload_pauses(self):
        """10a8:02cc pauses a credits dialog while _forcing_reload is set (FUN_1100_06d4 false), and 221e does not resume it."""
        self.world.forcing_reload = True
        self.world.open_options(CREDITS)
        self.assertTrue(self.world.paused)
        self.world.options.closed = True
        self.world.forcing_reload = False
        self.world.open_options(CREDITS)
        self.assertFalse(self.world.paused)

    def test_load_and_save_return_to_their_callers_immediately(self):
        self.script('''
{ LOADTEST
    MON_CODE _OPTS_LOAD
    _load_returned = 1
}
{ SAVETEST
    MON_CODE _OPTS_SAVE
    _save_returned = 1
}
''')
        load = self.vm.spawn('LOADTEST')
        self.assertIsNone(load.wait_pred)
        self.assertEqual(self.vm.globals['_load_returned'], 1)
        save = self.vm.spawn('SAVETEST')
        self.assertIsNone(save.wait_pred)
        self.assertEqual(self.vm.globals['_save_returned'], 1)

    def test_pimm_options_handler_sets_return_flag_without_waiting_for_close(self):
        caller = self.vm.spawn('PIMM_MONITOR', [0])
        self.assertEqual(self.world.monitor.name, 'PIMM')
        self.assertTrue(self.world.monitor_tap('OPTB'))
        self.assertEqual(self.world.options.screen, 'main')
        self.assertIsNone(caller.wait_pred)
        self.assertEqual(self.vm.globals['_return_to_pim'], 1)

    def test_opening_waits_for_difficulty_before_creating_lex(self):
        world = worldmod.World('TITLE', state_dir=worldmod.INITGAME)
        vm = vmmod.VM(world)
        vmmod.load_level(vm, 'TITLE')
        world.fire_event('TITLE_LOAD')
        vm.fire('GAME', 'global')
        for _ in range(20000):                                     # the intro movie plays before the difficulty dialog
            vm.tick_once()
            world.step()
            if world.options is not None:
                break
        self.assertEqual((world.options.screen, world.options.closed), ('difficulty', False))
        self.assertEqual(world.call('func', 'ISMONITORRUNNING', [], next(iter(vm.procs.values()))), 1)
        self.assertEqual(world.level, 'TITLE')
        self.assertIsNone(world.player())
        self.assertEqual(world.option_activate('MEDX'), 'difficulty:1')
        for _ in range(4):
            vm.tick_once()
            world.step()
        self.assertEqual(world.level, 'CHAOS')
        self.assertIsNotNone(world.player())


class SettingsTests(unittest.TestCase):
    def test_install_opt_parsing_is_case_insensitive_with_defaults(self):
        s = Settings.from_text('Dir=C:\\BIOFORGE\r\nSOUNDVOL=40\r\nmusicvol = 70\r\nGamma=50\r\nSubtitles=0\r\n')
        self.assertEqual((s.sound, s.music, s.gamma, s.subtitles), (40, 70, 50, False))
        s = Settings.from_text('Dir=C:\\BIOFORGE\r\n')
        self.assertEqual((s.sound, s.music, s.gamma, s.subtitles), (100, 100, 30, True))
        s = Settings.from_text('soundvol=loud\r\n')                       # unreadable values fall back to the default
        self.assertEqual(s.sound, 100)
        self.assertEqual(settingsmod.parse_install_opt('A=1\nnonsense\n b = 2 \n'), {'a': '1', 'b': '2'})

    def test_the_gog_file_has_gamma_50(self):
        s = Settings.load()
        self.assertEqual((s.sound, s.music, s.gamma, s.subtitles), (100, 100, 50, True))
        self.assertEqual(Settings.load('/nonexistent/INSTALL.OPT').gamma, 30)

    def test_gamma_offset_is_c_division(self):
        self.assertEqual([settingsmod.gamma_offset(g) for g in (0, 10, 30, 50, 100)], [-9, -6, 0, 6, 22])

    def test_gamma_lut_works_on_6_bit_values_and_clamps(self):
        expand = lambda c6: c6 * 255 // 63
        up, down = settingsmod.gamma_lut(50), settingsmod.gamma_lut(0)             # +6 / -9 on the 6-bit scale
        self.assertEqual([up[expand(c)] for c in (0, 10, 57, 63)], [expand(6), expand(16), expand(63), expand(63)])
        self.assertEqual([down[expand(c)] for c in (0, 9, 10, 63)], [0, 0, expand(1), expand(54)])
        self.assertEqual([settingsmod.gamma_lut(30)[expand(c)] for c in range(64)], [expand(c) for c in range(64)])   # 30 is the identity

    def test_master_volume_table(self):
        full = settingsmod.master_table(100)
        self.assertEqual((full[0], full[128], full[255]), (0, 127, 254))          # (i * 255) >> 8
        half = settingsmod.master_table(50)                                       # v = 50 * 255 // 100 = 127
        self.assertEqual((half[255], half[200]), (126, 99))
        self.assertEqual(settingsmod.master_table(1)[255], 1)                     # v = 2: (255 * 2) >> 8
        self.assertEqual(settingsmod.master_table(0), [0] * 256)                  # sfx < 1: effects disabled


class PanelTests(unittest.TestCase):
    def setUp(self):
        self.settings = Settings(sound=60, music=30, gamma=40, subtitles=True)
        self.audio, self.gamma = [], []
        self.options = Options(settings=self.settings, apply_audio=lambda *a: self.audio.append(a),
                               apply_gamma=lambda g: self.gamma.append(g))

    def state(self, name):
        return self.options.monitor.el(name).state

    def frame(self, name):
        return self.options.monitor.el(name).frame

    def test_a_gauge_draws_its_backdrop_and_every_bar(self):
        """Class Q: 1270:0a64 blits frames 1..n + 1, not one frame."""
        self.options.open(AUDIO)
        monitor = self.options.monitor
        gauge = monitor.render()
        monitor.el('SFXQ').gauge = False
        self.assertNotEqual(gauge, monitor.render())

    def test_audio_panel_opens_from_the_settings(self):
        self.options.open(AUDIO)
        self.assertEqual((self.options.screen, self.frame('SFXQ'), self.frame('MSCQ')), ('audio', 7, 4))
        self.assertEqual([self.state(n) for n in ('SFXX', 'MSCX', 'SBTX', 'AOKX', 'ACAX')], [3, 3, 3, 2, 1])
        self.settings.sound, self.settings.music, self.settings.subtitles = 0, 0, False
        self.options.open(AUDIO)
        self.assertEqual([self.state(n) for n in ('SFXX', 'MSCX', 'SBTX')], [1, 1, 1])
        self.assertEqual((self.frame('SFXQ'), self.frame('MSCQ')), (1, 1))

    def test_steps_clamp_and_apply_at_once(self):
        self.options.open(AUDIO)
        self.assertEqual(self.options.activate('SFMX'), 'audio:50,30')
        self.assertEqual(self.options.activate('MSPX'), 'audio:50,40')
        self.assertEqual(self.audio, [(50, 30), (50, 40)])
        self.assertEqual((self.frame('SFXQ'), self.frame('MSCQ')), (6, 5))
        for _ in range(6):
            self.options.activate('SFPX')
        self.assertEqual(self.options.sfx, 100)
        self.assertEqual(self.frame('SFXQ'), 11)
        for _ in range(6):
            self.options.activate('MSMX')
        self.assertEqual((self.options.music, self.state('MSCX'), self.frame('MSCQ')), (0, 1, 1))
        self.options.activate('MSPX')
        self.assertEqual((self.options.music, self.state('MSCX')), (10, 3))
        self.assertEqual(self.settings.sound, 60)                             # nothing persisted before OK

    def test_toggles_flip_between_zero_and_full(self):
        self.options.open(AUDIO)
        self.assertEqual(self.options.activate('SFXX'), 'audio:0,30')
        self.assertEqual((self.state('SFXX'), self.frame('SFXQ')), (1, 1))
        self.assertEqual(self.options.activate('SFXX'), 'audio:100,30')
        self.assertEqual((self.state('SFXX'), self.frame('SFXQ')), (3, 11))
        self.assertEqual(self.options.activate('MSCX'), 'audio:100,0')
        self.assertEqual(self.state('MSCX'), 1)
        self.assertEqual(self.options.activate('MSCX'), 'audio:100,100')
        self.assertEqual(self.state('MSCX'), 3)
        self.assertEqual(self.audio[-1], (100, 100))

    def test_silent_effects_force_subtitles_on(self):
        self.settings.subtitles = False
        self.options.open(AUDIO)
        self.assertEqual(self.state('SBTX'), 1)
        self.options.activate('SFXX')                                          # FUN_1280_0803(1) sets SBTX to state 3
        self.assertEqual(self.state('SBTX'), 3)
        self.assertIsNone(self.options.activate('SBTX'))                       # SBTX toggles
        self.assertEqual(self.state('SBTX'), 1)

    def test_ok_persists_and_returns_to_main_when_opened_with_default(self):
        self.options.open(DEFAULT)
        self.options.activate('AUDX')
        self.options.activate('SFMX')
        self.options.activate('MSCX')
        self.options.activate('SBTX')
        self.assertEqual(self.options.activate('AOKX'), 'audio:50,0')
        self.assertEqual((self.settings.sound, self.settings.music, self.settings.subtitles), (50, 0, False))
        self.assertEqual((self.options.screen, self.options.closed), ('main', False))
        self.assertEqual(self.audio[-1], (50, 0))
        self.options.activate('AUDX')                                          # reopening starts from the persisted values
        self.assertEqual((self.options.sfx, self.options.music, self.state('MSCX')), (50, 0, 1))

    def test_ok_closes_a_dialog_opened_with_the_audio_flag(self):
        self.options.open(AUDIO)
        self.options.activate('SFPX')
        self.assertEqual(self.options.activate('AOKX'), 'audio:70,30')
        self.assertTrue(self.options.closed)
        self.assertEqual(self.settings.sound, 70)

    def test_cancel_restores_and_reapplies_the_opening_values(self):
        self.options.open(DEFAULT)
        self.options.activate('AUDX')
        self.options.activate('SFXX')
        self.options.activate('MSPX')
        self.options.activate('SBTX')
        self.assertEqual(self.options.activate('ACAX'), 'cancel')
        self.assertEqual(self.audio[-1], (60, 30))
        self.assertEqual((self.settings.sound, self.settings.music, self.settings.subtitles), (60, 30, True))
        self.assertEqual((self.options.screen, self.options.closed), ('main', False))
        self.options.open(AUDIO)
        self.options.activate('SFPX')
        self.assertEqual(self.options.key('ESCAPE'), 'cancel')                 # Escape = Cancel
        self.assertTrue(self.options.closed)
        self.assertEqual(self.audio[-1], (60, 30))

    def test_gamma_panel_steps_and_limits(self):
        self.options.open(DEFAULT)
        self.assertIsNone(self.options.activate('GMAX'))
        self.assertEqual((self.options.screen, self.frame('GMAQ')), ('gamma', 5))
        self.assertEqual([self.state(n) for n in ('GMPX', 'GMMX', 'AOKX', 'ACAX')], [1, 1, 2, 1])
        self.assertEqual(self.options.activate('GMPX'), 'gamma:50')
        self.assertEqual((self.frame('GMAQ'), self.gamma), (6, [50]))
        for _ in range(8):
            self.options.activate('GMPX')
        self.assertEqual((self.options.gamma, self.frame('GMAQ')), (100, 11))
        for _ in range(11):
            self.options.activate('GMMX')
        self.assertEqual((self.options.gamma, self.frame('GMAQ')), (0, 1))
        self.assertEqual(self.gamma[-1], 0)
        self.assertEqual(self.settings.gamma, 40)                              # not persisted before OK

    def test_gamma_ok_persists_cancel_restores(self):
        self.options.open(DEFAULT)
        self.options.activate('GMAX')
        self.options.activate('GMMX')
        self.assertEqual(self.options.activate('AOKX'), 'gamma:30')
        self.assertEqual((self.settings.gamma, self.options.screen, self.gamma[-1]), (30, 'main', 30))
        self.options.activate('GMAX')
        self.options.activate('GMPX')
        self.options.activate('GMPX')
        self.assertEqual(self.gamma[-1], 50)
        self.assertEqual(self.options.activate('ACAX'), 'cancel')
        self.assertEqual((self.settings.gamma, self.gamma[-1], self.options.screen), (30, 30, 'main'))
        self.options.activate('GMAX')
        self.assertEqual(self.options.key('ESCAPE'), 'cancel')
        self.assertEqual(self.options.screen, 'main')

    def test_panels_render_and_gauges_follow_the_value(self):
        self.options.open(DEFAULT)
        self.options.activate('GMAX')
        low, _ = self.options.render()
        self.options.activate('GMPX')
        high, palette = self.options.render()
        self.assertNotEqual(bytes(low), bytes(high))
        self.assertEqual(len(palette), 768)
        for control in ('GMPX', 'GMMX'):
            e = self.options.monitor.el(control)
            self.assertEqual(self.options.pointer_move(e.x + e.w // 2, e.y + e.h // 2), control)


class WorldSettingsTests(unittest.TestCase):
    def setUp(self):
        self.world = worldmod.World('CHAOS', state_dir=worldmod.INITGAME)
        self.vm = vmmod.VM(self.world)
        vmmod.load_level(self.vm, 'CHAOS')

    def test_defaults_are_the_engine_defaults_not_the_users_file(self):
        w = self.world
        self.assertEqual((w.settings.sound, w.settings.music, w.settings.gamma, w.settings.subtitles), (100, 100, 30, True))
        self.assertEqual((w.gamma, w.sfx_log, w.music_initial, w.music_vol_log), (30, [(0, 100)], 100, []))

    def test_configure_settings_applies_the_installed_values(self):
        self.world.configure_settings(Settings(sound=20, music=0, gamma=50))
        self.assertEqual((self.world.gamma, self.world.sfx_log, self.world.music_initial), (50, [(0, 20)], 0))

    def test_the_options_dialog_uses_the_world_settings(self):
        w = self.world
        self.vm.tick = 7
        w.options = Options(settings=w.settings, apply_audio=w.apply_audio, apply_gamma=w.apply_gamma)
        w.options.open(DEFAULT)
        w.option_activate('AUDX')
        w.option_activate('SFMX')
        w.option_activate('MSMX')
        w.option_activate('AOKX')
        self.assertEqual((w.settings.sound, w.settings.music), (90, 90))
        self.assertEqual((w.sfx_log, w.music_vol_log), ([(0, 100), (8, 90)], [(7, 90)]))
        w.option_activate('GMAX')
        w.option_activate('GMMX')
        self.assertEqual(w.gamma, 20)
        w.option_activate('ACAX')
        self.assertEqual(w.gamma, 30)
        self.assertEqual([a for _, a in w.option_actions][-3:], ['audio:90,90', 'gamma:20', 'cancel'])
        self.assertEqual(w.warnings, [])

    def test_mon_code_creates_a_dialog_on_the_world_settings(self):
        self.world.call('stmt', 'MON_CODE', [1], types.SimpleNamespace(block=types.SimpleNamespace(name='T'), cur_fig=None,
                                                                          cur_item=None, handle=0, waiters=[]))
        self.assertIs(self.world.options.settings, self.world.settings)

    def test_detail_does_nothing(self):
        self.world.options = Options(settings=self.world.settings)
        self.world.options.open(DEFAULT)
        self.assertIsNone(self.world.option_activate('DETX'))
        self.assertEqual((self.world.options.screen, self.world.warnings, self.world.option_actions), ('main', [], []))

    def test_silent_effects_stop_every_voice(self):
        w = self.world
        h = w.play_sound(0, 255, loop=True)
        self.assertIn(h, self.vm.procs)
        w.apply_audio(0, 100)
        self.assertNotIn(h, self.vm.procs)
        self.assertEqual(w.sound_stops, [(0, h)])
        self.assertEqual(w.sfx_log, [(0, 100), (1, 0)])
        w.apply_audio(0, 100)                                                      # no change: nothing is logged
        self.assertEqual(w.sfx_log, [(0, 100), (1, 0)])

    def test_gamma_keys_step_persist_and_stop_at_the_limits(self):
        w = self.world
        w.key_down(0x34, keysmod.SHIFT)                                            # Shift + .
        self.assertEqual((w.settings.gamma, w.gamma), (40, 40))
        w.key_up(0x34)
        w.key_down(0x33, keysmod.ALT)                                              # Alt + ,
        w.key_up(0x33)
        w.key_down(0x4a, keysmod.SHIFT)                                            # Shift + numpad -
        w.key_up(0x4a)
        self.assertEqual((w.settings.gamma, w.gamma), (20, 20))
        w.key_down(0x4e, keysmod.ALT)                                              # Alt + numpad +
        w.key_up(0x4e)
        self.assertEqual(w.settings.gamma, 30)
        w.key_down(0x34, 0)                                                        # no modifier: not a gamma key
        w.key_up(0x34)
        self.assertEqual(w.settings.gamma, 30)
        for _ in range(12):
            w.key_down(0x34, keysmod.SHIFT)
            w.key_up(0x34)
        self.assertEqual((w.settings.gamma, w.gamma), (100, 100))
        for _ in range(12):
            w.key_down(0x33, keysmod.SHIFT)
            w.key_up(0x33)
        self.assertEqual((w.settings.gamma, w.gamma), (0, 0))
        self.assertEqual([k[1:] for k in w.key_log][:2], [('gamma', 10), ('gamma', -10)])

    def test_play_presents_with_the_gamma_step(self):
        import play
        w = self.world
        w.options = Options(settings=w.settings)
        w.options.open(DEFAULT)
        px, pal = w.options.render(w.options_underlay())                     # to_rgb draws the dialog over the screen it covers
        raw = np.frombuffer(bytes(pal), np.uint8).reshape(256, 3)[np.frombuffer(bytes(px), np.uint8)].reshape(200, 320, 3)
        self.assertTrue(np.array_equal(play.to_rgb(w), raw))                    # the default gamma 30 is the identity
        w.gamma = 50
        bright = play.to_rgb(w)
        self.assertTrue((bright >= raw).all() and (bright > raw).any())
        self.assertEqual(int(bright.max()), 255)
        self.assertTrue(np.array_equal(w.options.render(w.options_underlay())[0], px))     # the indexed frame is untouched

    def test_play_editor_cursor_draws_the_mouse_arrow_in_the_screen_palette(self):
        import play
        w = self.world
        w.options = Options(settings=w.settings)
        w.options.open(DEFAULT)
        px, pal = w.options.render()
        pal = np.frombuffer(bytes(pal), np.uint8).reshape(256, 3)
        plain, drawn = play.to_rgb(w), play.to_rgb(w, (160, 100))
        self.assertEqual(drawn[100, 160].tolist(), pal[248].tolist())          # MOUSE.SHP arrow hotspot (1,1) at the mouse
        self.assertEqual(drawn[101, 161].tolist(), pal[241].tolist())
        changed = np.argwhere((drawn != plain).any(axis=2))
        self.assertTrue(len(changed) and (changed.min(0) >= (100, 160)).all() and (changed.max(0) <= (110, 169)).all())

    def test_subtitles_switch(self):
        self.world.subtitle_log.append((0, 1, 5, 'HELLO', 100))
        self.assertEqual(self.world.active_subtitle(10), (5, 'HELLO'))
        self.world.settings.subtitles = False
        self.assertIsNone(self.world.active_subtitle(10))

    def test_the_mix_applies_the_master_table_at_each_voice_start(self):
        w = self.world
        w.play_sound(0, 255, loop=False)
        mixes = {}
        for name, log in (('full', [(0, 100)]), ('half', [(0, 50)]), ('late', [(0, 100), (1, 0)]), ('off', [(0, 0)])):
            w.sfx_log = log
            mixes[name] = movie.mix_audio(w, 30).astype(int)
        self.assertGreater(np.abs(mixes['full']).max(), 0)
        self.assertLessEqual(np.abs(mixes['half'] - mixes['full'] * 126 / 254).max(), 1.0)      # table[255]: 254 vs 126
        self.assertTrue((mixes['late'] == mixes['full']).all())                                 # the sound started at tick 0
        self.assertEqual(np.abs(mixes['off']).max(), 0)
        w.sound_log.append((2, 0, 'x', 255, 0, 0))                                              # a second one at tick 2
        w.sfx_log = [(0, 100), (1, 0)]
        late = movie.mix_audio(w, 30).astype(int)
        self.assertTrue((late == mixes['full']).all())                                          # silent: nothing new is added
        w.sfx_log = [(0, 100)]
        both = movie.mix_audio(w, 30).astype(int)
        self.assertGreater(np.abs(both).max(), np.abs(mixes['full']).max())

    def test_the_mix_scales_positional_volume_changes(self):
        w = self.world
        w.play_sound(0, 255, loop=False)
        h = w.sound_log[0][5]
        w.sound_volumes += [(0, h, 200), (10, h, 100)]
        w.sfx_log = [(0, 100)]
        full = movie.mix_audio(w, 30).astype(int)
        w.sfx_log = [(0, 100), (10, 50)]                                      # the level change applies to the volume change at tick 10
        changed = movie.mix_audio(w, 30).astype(int)
        end = int(10 / vmmod.TPS * movie.AUDIO_RATE)
        self.assertTrue((changed[:end - movie.AUDIO_RATE // vmmod.TPS] == full[:end - movie.AUDIO_RATE // vmmod.TPS]).all())
        self.assertLess(np.abs(changed[end + 1000:]).max(), np.abs(full[end + 1000:]).max())


class NativeStateTests(unittest.TestCase):
    def test_boot_from_native_gamedat_and_export(self):
        world, vm = worldmod.World.from_native_state()
        self.assertEqual(world.level, 'CHAOS')
        self.assertEqual(world.current_camera(), 'CE33')
        self.assertEqual(vm.globals['_DIFFICULTY_LEVEL'] if '_DIFFICULTY_LEVEL' in vm.globals else vm.globals.get('_difficulty_level'), 0)
        self.assertEqual(world.log_entries['LEX'], ['MYBOOK', 'INJECT', 'SCREAM'])
        out = world.export_state()
        self.assertEqual(out['misc']['level'], 'CHAOS.IFF')
        self.assertEqual(out['lists']['GMAINT'][0], ('A', 1783137))


if __name__ == '__main__':
    unittest.main()
