"""Tests for the monitor engine (monitor.py) and its world/VM binding: re/.venv/bin/python -I -m unittest discover -s re/interp -p 'test_*.py'"""
import os
import sys
import tempfile
import types
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import monitor as mon  # noqa: E402
import play  # noqa: E402
import vm as vmmod  # noqa: E402
import world as worldmod  # noqa: E402

DEBUGS = lambda w: [e[4][0] for e in w.log if e[3] == 'DEBUG']


def tick(m, n=1):
    """n ticks of the monitor's pointer (the world's step_pointers)."""
    for _ in range(n):
        m.update()


def stub(fig='PLAYER'):
    return types.SimpleNamespace(block=types.SimpleNamespace(name='TEST'), cur_fig=fig, cur_item=None, handle=0,
                                 waiters=[], goto=None, ended=False, wait_pred=None)


class MonitorModel(unittest.TestCase):
    def test_simulated_tab_moves_to_an_active_button(self):
        m = mon.Monitor('MLBT')
        m.define_button('PWRB', 'POWER')
        self.assertTrue(m.tab())
        self.assertIsNone(m.hovered)                      # FUN_1270_0536: the pointer glides there, it does not jump
        tick(m, 40)
        self.assertEqual(m.hovered.name, 'PWRB')
        self.assertEqual(m.pointer['pos'], (247, 186))

    def glide_positions(self, dx, ticks):
        m = mon.Monitor('MLBT')
        m.pointer['pos'] = (100, 100)
        m.glide_to(100 + dx, 100)
        got = []
        for _ in range(ticks):
            m.update()
            got.append(m.pointer['pos'][0])
        return m, got

    def test_glide_follows_the_integer_model(self):
        # dx = 100 at dt 4: 14 accelerating steps (t = 56), one coasting step, then decelerating; arrives on step 22 (1270:064f)
        m, got = self.glide_positions(100, 24)
        self.assertEqual(got[:15], [101, 102, 104, 106, 109, 112, 116, 120, 125, 130, 136, 142, 149, 156, 163])
        self.assertEqual(got[15:22], [170, 176, 182, 187, 192, 196, 200])
        self.assertEqual((m.glide['t'], m.glide['s'], m.glide['p']), (100, 56, -2))
        self.assertEqual(got[22:], [200, 200])
        self.assertFalse(m.gliding)                       # DAT_9fea clears one update after the arrival

    def test_glide_distance_with_16_bit_overflow_jumps_at_once(self):
        m = mon.Monitor('MLBT')
        m.pointer['pos'] = (0, 14)
        m.glide_to(100, 100)                              # 100 * 86 = 8600: ceil(sqrt) = 93
        self.assertEqual(m.glide['dist'], 93)
        m.glide_to(247, 186)                              # 247 * 172 = 42484 wraps negative: dist 0
        self.assertEqual(m.glide['dist'], 0)
        m.update()
        self.assertEqual(m.pointer['pos'], (247, 186))

    def test_glide_target_is_clamped_to_the_margins(self):
        m = mon.Monitor('MLBT')
        m.pointer['pos'] = (100, 100)
        m.glide_to(500, 0)
        self.assertEqual(m.glide['target'], (319, 14))

    def test_mouse_move_cancels_a_glide(self):
        m, got = self.glide_positions(100, 5)
        m.pointer_move(m.pointer['pos'][0], 100)
        tick(m, 5)
        self.assertEqual(m.pointer['pos'], (got[-1], 100))
        m, _ = self.glide_positions(100, 5)
        m.place_pointer(50, 60)                           # MON_SETPTRPOS jumps and ends it
        tick(m, 5)
        self.assertEqual(m.pointer['pos'], (50, 60))

    def test_glide_highlights_the_buttons_it_crosses(self):
        m = mon.Monitor('MLBT')
        m.define_button('PWRB', 'POWER')
        m.pointer['pos'] = (100, 190)
        m.glide_to(247, 186)
        tick(m, 3)
        self.assertEqual(m.poll()[0], None)
        tick(m, 40)
        self.assertEqual(m.poll()[0], 'PWRB_HIGHLIGHT')

    def test_click_during_a_glide_is_lost(self):
        m = mon.Monitor('MLBT')
        taken = []
        m.press_action = lambda: taken.append(1) or True
        m.pointer['pos'] = (0, 100)
        m.glide_to(300, 100)
        tick(m, 2)
        m.mouse_down()
        tick(m, 12)                                        # the press animation reaches its last frame mid-glide
        self.assertTrue(m.gliding)
        self.assertEqual(taken, [])
        tick(m, 60)
        self.assertFalse(m.gliding)
        m.mouse_up()
        m.settle_pointer()
        m.mouse_down()
        self.assertEqual(taken, [1])

    def test_letter_shortcut_glides_then_clicks_on_arrival(self):
        m = mon.Monitor('MLBT')
        m.define_button('PWRB', 'POWER')
        self.assertEqual(m.elements['PWRB'].shortcut, '')   # no script statement sets +0x42 (see Element.shortcut)
        m.elements['PWRB'].shortcut = 'p'                 # as FUN_1278_0894 would
        m.pointer['pos'] = (100, 190)
        self.assertFalse(m.letter_key('x'))
        self.assertTrue(m.letter_key('P'))
        tick(m, 60)
        self.assertEqual((m.pressed, m.released), ('PWRB', 'PWRB'))
        self.assertIsNone(m.shortcut)

    def test_letter_shortcut_on_the_focused_button_clicks_at_once(self):
        m = mon.Monitor('MLBT')
        m.define_button('PWRB', 'POWER')
        m.elements['PWRB'].shortcut = 'p'
        m.pointer_move(247, 186)
        self.assertTrue(m.letter_key('p'))
        tick(m, 30)
        self.assertEqual((m.pressed, m.released), ('PWRB', 'PWRB'))

    def keyed(self):
        m = mon.Monitor('MLBT')
        for n in ('PWRB', 'MANB', 'AUTB'):                # one row, in this order; centres x 247, 160, 74 at y 186
            m.define_button(n)
        return m

    def test_tab_starts_on_the_first_selectable_button_and_steps_to_the_next(self):
        m = self.keyed()
        self.assertTrue(m.key_event(mon.KEY_TAB))
        self.assertEqual(m.focus.name, 'MANB')            # the focus starts on DNDB, is not selectable, moves to PWRB; Tab steps on
        self.assertEqual(m.glide['target'], (160, 186))
        m.key_event(mon.KEY_BACKTAB)
        self.assertEqual(m.focus.name, 'PWRB')

    def test_direction_keys_pick_the_nearest_button_that_way_or_step(self):
        m = self.keyed()
        m.focus = m.elements['MANB']
        m.key_event(0xcd)                                 # Right
        self.assertEqual(m.focus.name, 'PWRB')
        m.key_event(0xcb)                                 # Left, twice
        m.key_event(0xcb)
        self.assertEqual(m.focus.name, 'AUTB')
        m.key_event(0xcb)                                 # nothing further left: Left steps to the previous button (the wrap)
        self.assertEqual(m.focus.name, 'MANB')
        m.key_event(0xd0)                                 # Down: nothing below, the "next" fallback
        self.assertEqual(m.focus.name, 'AUTB')
        m.key_event(ord('L'))                             # L: the nearest button not sharing a row or column: none, so the previous
        self.assertEqual(m.focus.name, 'MANB')

    def test_return_presses_and_its_release_ends_the_press(self):
        m = mon.Monitor('MLBT')
        m.define_button('PWRB')
        taken = []
        m.press_action = lambda: taken.append(1) or True
        m.release_action = lambda: taken.append(2) or True
        m.pointer_move(247, 186)
        m.key_event(mon.KEY_RETURN, 0x1c)
        self.assertEqual((m.held, m.pointer['state']), (0x1c, mon.PTR_PRESSING))
        tick(m, 3)
        m.key_release(0x1c)
        tick(m, 30)
        self.assertEqual((taken, m.held), ([1, 2], 0))

    def test_space_ends_at_the_next_event_because_it_follows_the_return_key(self):
        m = mon.Monitor('MLBT')
        m.define_button('PWRB')
        m.pointer_move(247, 186)
        m.key_event(mon.KEY_SPACE, 0x39)
        tick(m, 3)
        self.assertEqual(m.held, 0x1c)
        m.pointer_move(247, 186)                          # any event: the scan 0x1c is not down, the press ends
        self.assertEqual(m.held, 0)

    def test_escape_presses_and_its_release_is_a_label(self):
        m = mon.Monitor('MLBT')
        self.assertFalse(m.key_event(mon.KEY_ESCAPE, 0x01))
        self.assertEqual(m.poll(), ('ESCAPE_BUTTON', True))
        m.key_release(0x01)
        self.assertEqual(m.poll()[0], 'ESCAPE_RELEASED')

    def test_right_click_presses_escape_while_input_is_on(self):
        m = mon.Monitor('MLBT')
        m.right_click()                                   # FUN_1250_0cf9: type 1 with flag 2 -> "ESCAPE" pressed, like the key; no release label
        self.assertEqual(m.poll(), ('ESCAPE_BUTTON', True))
        self.assertEqual(m.held, 0)
        m = mon.Monitor('MLBT')
        m.set_input(False)
        m.right_click()
        self.assertEqual(m.poll(), (None, False))

    def test_keys_are_dropped_while_input_is_off_except_for_mon_simulate(self):
        m = self.keyed()
        m.set_input(False)
        self.assertFalse(m.key_event(mon.KEY_TAB))
        self.assertIsNone(m.glide)
        self.assertTrue(m.key_event(mon.KEY_TAB, force=True))
        self.assertIsNotNone(m.glide)

    def test_scan_codes_map_to_key_bytes(self):
        self.assertEqual([mon.key_code(s) for s in (0x0f, 0x1c, 0x01, 0x39, 0x26, 0x48, 0x4c, 0x02)], [9, 0x0d, 0x1b, 0x20, ord('l'), 0xc8, 0xcc, ord('1')])
        self.assertEqual(mon.key_code(0x0f, True), 0x8f)
        self.assertIsNone(mon.key_code(0x3b))

    def test_start_loads_elements(self):
        m = mon.Monitor('mlbt')
        self.assertEqual(m.name, 'MLBT')
        self.assertIsNotNone(m.background)
        for n in ('PWRB', 'CAMV', 'WRNL', 'PWRL', 'DNDB'):
            self.assertIn(n, m.elements)
        pwrb = m.elements['PWRB']
        self.assertEqual((pwrb.kind, pwrb.x, pwrb.y, pwrb.w, pwrb.h), ('B', 203, 177, 89, 19))    # (-hotx, -hoty)

    def test_localize(self):
        self.assertEqual(mon.localize('POWER /FCONTACT /GSTROM'), 'POWER ')
        self.assertEqual(mon.localize('/E1/F   1/G1'), '1')
        self.assertEqual(mon.localize('/!  73 K'), '  73 K')
        self.assertEqual(mon.localize('/!'), '')

    def test_variable_substitution_preserves_unresolved_time_and_standalone_fields(self):
        self.assertEqual(mon.substitute('%% %VALUE% %time%', lambda n: {'value': 7}.get(n.lower())), '% 7 %time%')
        self.assertEqual(mon.substitute('%% %VALUE% %time%', lambda n: {'value': 7}.get(n.lower()), '3-0412'), '% 7 3-0412')
        self.assertEqual(mon.substitute('ID %missing%'), 'ID %missing%')

    def test_game_time_uses_two_60hz_ticks_per_vm_tick_at_boundaries(self):
        self.assertEqual(mon.format_game_time(0), '0-0000')
        self.assertEqual(mon.format_game_time(1799), '0-0000')
        self.assertEqual(mon.format_game_time(1800), '0-0001')
        self.assertEqual(mon.format_game_time(108000), '0-0100')
        self.assertEqual(mon.format_game_time(2592000), '1-0000')
        self.assertEqual(mon.format_game_time(0, 60 * 60 * 60, 7), '7-0100')

    def test_button_states_draw_frames_at_hotspot_positions(self):
        m = mon.Monitor('MLBT')
        m.pointer['frame'] = 0
        base, _ = m.render()
        self.assertEqual(bytes(base), bytes(m.background[4]))              # nothing active: just the background
        b = m.elements['PWRB']
        m.define_button('pwrb', '', mon.NORMAL, 1)
        for state, frame in ((mon.NORMAL, 1), (mon.HIGHLIGHT, 2), (mon.SELECTED, 2)):
            m.elements['PWRB'].state = state
            px, _ = m.render()
            w, h, hx, hy, fpx, mask = b.frames[frame]
            for (x, y) in ((0, 9), (44, 9), (88, 9)):
                if mask[y * w + x]:
                    self.assertEqual(px[(177 + y) * 320 + 203 + x], fpx[y * w + x])
        m.elements['PWRB'].state = mon.INVISIBLE
        self.assertEqual(bytes(m.render()[0]), bytes(base))
        m.hide_all()
        self.assertFalse(m.elements['PWRB'].active)

    def test_default_pointer_uses_pointer_cam_frame_one(self):
        m = mon.Monitor('MLBT')
        self.assertEqual((m.pointer['name'], m.pointer['frame']), (None, 1))
        frames = mon.pointer_frames()
        self.assertEqual(len(frames), 4)             # POINTER.CAM's first image entry is HAND
        m.pointer['frame'] = 0
        hidden, _ = m.render()
        m.pointer['frame'] = 1
        shown, _ = m.render()
        self.assertNotEqual(bytes(shown), bytes(hidden))

    def test_selected_pointer_uses_named_cam_first_image_entry(self):
        m = mon.Monitor('MLBT')
        m.pointer.update(name='pcayhand', frame=1, pos=(0, 0))
        frames = mon.pointer_frames('PCAYHAND.CAM')
        self.assertEqual(len(frames), 2)             # PCAYHAND.CAM has its palette and PCAY entry
        m.pointer['frame'] = 0
        hidden, _ = m.render()
        m.pointer['frame'] = 1
        shown, _ = m.render()
        self.assertNotEqual(bytes(shown), bytes(hidden))

    def test_pointer_hotspot_mask_and_screen_clipping(self):
        m = mon.Monitor('MLBT')
        m.pointer.update(name='PCAYHAND', frame=1, pos=(-125 + mon.PTR_HOT[0], -2 + mon.PTR_HOT[1]))
        frame = mon.pointer_frames('PCAYHAND')[1]
        w, h, hx, hy, fpx, mask = frame
        m.pointer['frame'] = 0
        hidden, _ = m.render()
        m.pointer['frame'] = 1
        shown, _ = m.render()
        x0, y0 = -125 - hx, -2 - hy
        opaque = next((c, r) for r in range(h) for c in range(w)
                      if mask[r * w + c] and 0 <= x0 + c < 320 and 0 <= y0 + r < 200)
        clear = next((c, r) for r in range(h) for c in range(w)
                     if not mask[r * w + c] and 0 <= x0 + c < 320 and 0 <= y0 + r < 200)
        c, r = opaque
        self.assertEqual(shown[(y0 + r) * 320 + x0 + c], fpx[r * w + c])
        c, r = clear
        self.assertEqual(shown[(y0 + r) * 320 + x0 + c], hidden[(y0 + r) * 320 + x0 + c])

    def test_pointer_renders_above_monitor_text_and_art(self):
        m = mon.Monitor('MLBT')
        pwr = m.elements['PWRB']
        m.define_button('pwrb', 'POWER', mon.NORMAL, 0)
        mon._POINTERS['TESTPOINTER'] = (
            (1, 1, 0, 0, bytearray(), bytearray()),
            (1, 1, 0, 0, bytearray([17]), bytearray([1])),
        )
        try:
            m.pointer.update(name='TESTPOINTER', frame=0, pos=(pwr.x + mon.PTR_HOT[0], pwr.y + mon.PTR_HOT[1]))
            without, _ = m.render()
            m.pointer['frame'] = 1
            with_pointer, _ = m.render()
        finally:
            mon._POINTERS.pop('TESTPOINTER', None)
        i = pwr.y * 320 + pwr.x
        self.assertNotEqual(without[i], 17)
        self.assertEqual(with_pointer[i], 17)

    def test_viewport_stretches_the_whole_view_into_the_grey_ramp_and_stays_below_pointer(self):
        source = np.zeros((200, 320, 3), np.uint8)
        source[:100, :160] = 255                       # bright upper-left quarter of the camera view
        m = mon.Monitor('MLBT', viewport_frame=lambda camera: source)
        e = m.elements['CAMV']
        m.pointer['frame'] = 0
        empty, _ = m.render()
        m.define_viewport('CAMV', 'TEST')
        shown, _ = m.render()
        ramp = m.grey_ramp
        self.assertEqual((ramp[0], ramp[-1], len(ramp)), (128, 159, 32))
        inside = {i for y in range(e.y, e.y + e.h) for i in range(y * 320 + e.x, y * 320 + e.x + e.w)}
        self.assertTrue(all(shown[i] in ramp for i in inside))                 # rectangle filled, ramp indices only
        self.assertTrue(all(a == b for i, (a, b) in enumerate(zip(empty, shown)) if i not in inside))
        at = lambda x, y: shown[(e.y + y) * 320 + e.x + x]
        # the bright quarter of the 320x200 view covers the upper-left quarter of the rectangle (scaled, not cropped)
        self.assertEqual((at(0, 0), at(e.w // 2 - 1, e.h // 2 - 1)), (ramp[-1], ramp[-1]))
        self.assertEqual((at(e.w // 2 + 1, 0), at(0, e.h // 2 + 1), at(e.w - 1, e.h - 1)), (ramp[0],) * 3)
        mon._POINTERS['VIEWPORT_TEST'] = (
            (1, 1, 0, 0, bytearray(), bytearray()),
            (1, 1, 0, 0, bytearray([17]), bytearray([1])),
        )
        try:
            m.pointer.update(name='VIEWPORT_TEST', frame=1, pos=(e.x + 1 + mon.PTR_HOT[0], e.y + mon.PTR_HOT[1]))
            pointed, _ = m.render()
            rgb = m.render_rgb()
        finally:
            mon._POINTERS.pop('VIEWPORT_TEST', None)
        self.assertEqual(pointed[e.y * 320 + e.x + 1], 17)
        self.assertEqual(rgb[e.y, e.x + 1].tolist(), list(m.pal[17 * 3:17 * 3 + 3]))

    def test_viewport_brightness_maps_linearly_onto_the_ramp_in_both_paths(self):
        source = np.zeros((200, 320, 3), np.uint8)
        source[:, 160:] = [0, 255, 0]                  # luma 0.587 * 255
        source[:, :160] = [255, 255, 255]
        m = mon.Monitor('MLBT', viewport_frame=lambda camera: source)
        m.pointer['frame'] = 0
        m.define_viewport('CAMV', 'TEST')
        e = m.elements['CAMV']
        px, pal = m.render()
        left, right = px[e.y * 320 + e.x], px[e.y * 320 + e.x + e.w - 1]
        self.assertEqual((left, right), (159, 128 + round(0.587 * 31)))
        rgb = m.render_rgb()
        self.assertEqual(rgb[e.y, e.x].tolist(), [255, 255, 255])
        self.assertEqual(rgb[e.y, e.x + e.w - 1].tolist(), list(pal[right * 3:right * 3 + 3]))

    def test_buttons_draw_over_the_viewport_and_high_style_bytes_use_font_zero(self):
        m = mon.Monitor('CELL', viewport_frame=lambda camera: np.zeros((200, 320, 3), np.uint8))
        m.pointer['frame'] = 0
        m.define_button('BT4b', '/!2', mon.NORMAL)
        m.define_viewport('VEWV', 'TEST')
        px, _ = m.render()
        w, h, hx, hy, fpx, mask = m.elements['BT4B'].frames[1]
        i = next(k for k in range(w * h) if mask[k])
        self.assertEqual(px[(-hy + i // w) * 320 - hx + i % w], fpx[i])        # frame pixel, not the camera ramp
        self.assertIs(mon.font(0x82), mon.font(0))

    def test_press_release_hover_states(self):
        m = mon.Monitor('MLBT')
        m.define_button('pwrb', '', mon.NORMAL, 1)            # toggle
        m.define_button('manb', '', mon.NORMAL, 0)
        m.define_button('autb', '', mon.NOT_SELECTABLE, 0)
        self.assertTrue(m.hover('manb'))
        self.assertEqual(m.elements['MANB'].state, mon.HIGHLIGHT)
        m.press('manb')
        self.assertEqual(m.elements['MANB'].state, mon.SELECTED)
        m.release('manb')
        self.assertEqual(m.elements['MANB'].state, mon.NORMAL)   # a plain button pops back
        m.press('pwrb'); m.release('pwrb')
        self.assertEqual(m.elements['PWRB'].state, mon.SELECTED)  # a toggle stays down
        m.press('pwrb')
        self.assertEqual(m.elements['PWRB'].state, mon.NORMAL)
        self.assertFalse(m.press('autb'))                         # not selectable
        self.assertFalse(m.press('nonesuch'))

    def test_mouse_hit_testing_hover_and_capture(self):
        m = mon.Monitor('MLBT')
        m.define_button('pwrb', '', mon.NORMAL, 0)
        m.define_button('manb', '', mon.NORMAL, 0)
        pwr, man = m.elements['PWRB'], m.elements['MANB']
        self.assertTrue(m.pointer_move(pwr.x, pwr.y))
        self.assertEqual((m.pointer['pos'], m.hovered.name, pwr.state), ((pwr.x, pwr.y), 'PWRB', mon.HIGHLIGHT))
        self.assertTrue(m.mouse_down())
        tick(m, 6)                                                 # the press animation: pressed on the 5th tick, the hold ends on the 6th
        self.assertEqual((m.captured, pwr.state), ('PWRB', mon.SELECTED))
        self.assertEqual(m.poll(), ('PWRB_HIGHLIGHT', False))
        self.assertEqual(m.poll(), ('PWRB_BUTTON', True))
        self.assertEqual(m.poll(), (None, mon.REPEAT_DELAY))
        self.assertFalse(m.pointer_move(man.x, man.y))             # input is off from the press to the release (FUN_1250_0415)
        self.assertEqual(m.pointer['pos'], (pwr.x, pwr.y))
        m.mouse_up()
        self.assertEqual((m.captured, m.mouse_warp), (None, (pwr.x, pwr.y)))
        self.assertEqual(m.poll(), ('PWRB_RELEASED', False))
        tick(m, 12)
        self.assertTrue(m.pointer_move(man.x, man.y))
        self.assertEqual((m.hovered.name, man.state), ('MANB', mon.HIGHLIGHT))
        self.assertEqual(m.poll(), ('MANB_HIGHLIGHT', False))
        m.mouse_up()
        tick(m, 20)
        self.assertEqual(m.poll(), (None, False))                  # no unmatched release event

    def pointer_over_power_button(self):
        m = mon.Monitor('MLBT')
        m.define_button('pwrb', '', mon.NORMAL, 0)
        pwr = m.elements['PWRB']
        m.pointer_move(pwr.x, pwr.y)
        return m, pwr

    def test_pointer_press_animation_frames_and_press_release_ticks(self):
        """FUN_1270_01ec / 0263 / 02ef: a click's frames per tick; the press fires on the tick the last frame is shown, the release one
        tick later (the mouse went up during the press); the intervals are 4, 1 and 4 units of 2 per tick (14 / 5 / 14 over 4 frames)."""
        m, pwr = self.pointer_over_power_button()
        self.assertEqual((m.pointer['frame'], m.pointer['state']), (1, 0))
        self.assertTrue(m.mouse_down())
        m.mouse_up()
        got = []
        for _ in range(11):
            tick(m)
            got.append((m.pointer['frame'], m.pointer['state'], m.captured, m.released))
        self.assertEqual([g[0] for g in got], [1, 2, 2, 3, 3, 2, 2, 1, 1, 1, 1])
        self.assertEqual([g[1] for g in got], [1, 1, 1, 1, 2, -1, -1, -1, 0, 0, 0])
        self.assertEqual([g[2] for g in got].index('PWRB') + 1, 5)           # pressed on tick 5
        self.assertEqual([g[3] for g in got].index('PWRB') + 1, 6)           # released on tick 6

    def test_pointer_ignores_moves_and_a_second_press_while_animating(self):
        m, pwr = self.pointer_over_power_button()
        presses = []
        m.press_action = lambda: presses.append(m.pointer['frame']) or m._press_button()
        self.assertTrue(m.mouse_down())
        tick(m, 2)
        self.assertFalse(m.mouse_down())                           # dropped
        m.pointer_move(10, 100)
        self.assertEqual(m.pointer['pos'], (pwr.x, pwr.y))         # not moved, nothing stored
        m.mouse_up()
        tick(m, 5)                                                 # tick 7: the release animation is still running
        m.pointer_move(10, 100)
        self.assertEqual(m.pointer['pos'], (pwr.x, pwr.y))
        tick(m, 2)
        self.assertEqual((m.pointer['frame'], m.pointer['state']), (1, 0))
        m.pointer_move(10, 100)
        self.assertEqual(m.pointer['pos'], (10, 100))
        self.assertEqual(presses, [3])                             # pressed once, on the last frame

    def test_pointer_holds_the_last_frame_until_the_mouse_goes_up(self):
        m, pwr = self.pointer_over_power_button()
        m.mouse_down()
        tick(m, 30)
        self.assertEqual((m.pointer['frame'], m.pointer['state'], m.captured, m.released), (3, 0, 'PWRB', ''))
        m.mouse_up()                                               # idle: the release runs at once
        self.assertEqual((m.captured, m.released, m.pointer['state']), (None, 'PWRB', -1))
        tick(m, 8)
        self.assertEqual((m.pointer['frame'], m.pointer['state']), (1, 0))

    def test_mouse_outside_or_disabled_buttons_has_no_event(self):
        m = mon.Monitor('MLBT')
        m.define_button('pwrb', '', mon.NORMAL, 0)
        self.assertFalse(m.pointer_move(-20, 240))
        self.assertEqual(m.pointer['pos'], (0, 199))
        self.assertFalse(m.mouse_down())
        self.assertEqual(m.poll(), (None, False))
        m.input_enabled = False
        self.assertFalse(m.pointer_move(203, 177))
        self.assertFalse(m.mouse_down())
        self.assertEqual(m.poll(), (None, False))

    def test_active_invisible_button_is_clickable_but_hidden_button_is_not(self):
        m = mon.Monitor('MLBT')
        pwr = m.elements['PWRB']
        m.define_button('pwrb', '', mon.INVISIBLE, 0)
        self.assertTrue(m.pointer_move(pwr.x, pwr.y))
        self.assertTrue(m.mouse_down())
        tick(m, 5)
        self.assertEqual(m.poll(), ('PWRB_HIGHLIGHT', False))
        self.assertEqual(m.poll(), ('PWRB_BUTTON', True))
        tick(m, 20)
        m.hide_all()
        self.assertFalse(m.pointer_move(pwr.x, pwr.y))
        self.assertFalse(m.mouse_down())

    def test_same_frame_mouse_click_dispatches_button_before_released(self):
        m = mon.Monitor('MLBT')
        m.define_button('pwrb', '', mon.NORMAL, 0)
        pwr = m.elements['PWRB']
        m.pointer_move(pwr.x, pwr.y)
        self.assertTrue(m.mouse_down())
        m.mouse_up()                                               # before the press: the release waits for it
        tick(m, 6)
        self.assertEqual(m.poll(), ('PWRB_HIGHLIGHT', False))
        self.assertEqual(m.poll(), ('PWRB_BUTTON', True))
        self.assertEqual(m.poll(), ('PWRB_RELEASED', False))

    def test_preview_mouse_coordinates_clamp_at_monitor_edges(self):
        self.assertEqual(play.monitor_coords(0, 0), (0, 0))
        self.assertEqual(play.monitor_coords(639, 399), (319, 199))
        self.assertEqual(play.monitor_coords(640, 400), (319, 199))
        self.assertEqual(play.monitor_coords(-1, -1), (0, 0))

    def test_button_text_uses_label_style(self):
        m = mon.Monitor('MLBT')
        m.pointer['frame'] = 0
        m.define_button('pwrb', 'POWER', mon.NORMAL, 0)
        lab = m.elements['PWRL']
        self.assertEqual((lab.active, lab.text), (True, 'POWER'))
        self.assertEqual(lab.header, ([248, 250, 248, 250, 248], 4))
        base = bytes(m.background[4])
        px, _ = m.render()
        self.assertNotEqual(bytes(px), base)                      # text pixels drawn in the label rectangle
        diff = [i for i in range(64000) if px[i] != base[i]]
        self.assertTrue(all(203 <= i % 320 < 292 and 177 <= i // 320 < 196 for i in diff))

    def test_poll_priority_and_repeat(self):
        m = mon.Monitor('MLBT')
        m.define_button('pwrb', '', mon.NORMAL, 0)
        m.hover('pwrb'); m.press('pwrb'); m.release('pwrb')
        self.assertEqual(m.poll(), ('PWRB_HIGHLIGHT', False))
        self.assertEqual(m.poll(), ('PWRB_RELEASED', False))       # released clears the pending button
        self.assertEqual(m.poll(), (None, False))
        m.press('pwrb')
        self.assertEqual(m.poll(), ('PWRB_BUTTON', True))
        self.assertEqual(m.poll(), (None, mon.REPEAT_DELAY))       # first poll after the press: wait the repeat delay
        self.assertEqual(m.poll(), ('PWRB_REPEAT', True))
        self.assertEqual(m.poll(), ('PWRB_REPEAT', True))
        m.release('pwrb')
        self.assertEqual(m.poll(), ('PWRB_RELEASED', False))
        self.assertEqual(m.poll(), (None, False))

    def test_lists_text_and_scales(self):
        m = mon.Monitor('PIMM')
        m.define_list('inmt', 'INVENTOR')
        m.define_list('dest', 'DITEMS')
        self.assertIn('MONBAT', [k for k, _ in m.elements['INMT'].source])
        m.make_inventory('inmt', [('MY_BATTERY', 'MONBAT'), ('FLUTE', 'FLUTE'), ('SWORD', 'SWORD')])
        self.assertEqual([k for k, _ in m.elements['INMT'].entries], ['MONBAT', 'FLUTE'])
        self.assertEqual(m.elements['INMT'].items, ['MY_BATTERY', 'FLUTE'])
        self.assertEqual(m.poll(), ('MONBAT_HIGHLIGHT', False))
        m.scroll_list('inmt', mon.ENTRY_DOWN)
        self.assertEqual((m.list_index('inmt'), m.poll()), (1, ('FLUTE_HIGHLIGHT', False)))
        m.scroll_list('inmt', mon.ENTRY_DOWN)                      # clamped at the end
        self.assertEqual(m.list_index('inmt'), 1)
        m.remove_entry('dest', '*+FLUTE')
        self.assertEqual([k for k, _ in m.elements['DEST'].entries], ['FLUTE'])
        self.assertEqual(m.poll(), (None, False))                  # "*+" is silent
        m.set_scale('hlts', 50, 1)
        self.assertTrue(m.elements['HLTS'].active)


class MonitorScripts(unittest.TestCase):
    def setUp(self):
        self.w = worldmod.World('CHAOS', state_dir=worldmod.INITGAME)
        self.vm = vmmod.VM(self.w)
        vmmod.load_level(self.vm, 'CHAOS')

    def script(self, text):
        with tempfile.NamedTemporaryFile('w', suffix='.scr', delete=False) as t:
            t.write(text)
        try:
            self.vm.load(t.name)
        finally:
            os.unlink(t.name)

    def open_pimm(self, screen):
        """w.open_pimm(screen) and run the VM and the world until the monitor is up: the PIMM block's `MOTION LOOK_AT_PIM FREEZE` now blocks
        until the motion has played (about 36 ticks, 10d0:6083), and a figure only animates once it is placed and the world steps."""
        lex = self.w.player()
        if lex.pos is None:
            lex.pos = np.array([0.0, 0.0, -5000.0])
        self.w.open_pimm(screen)
        for _ in range(80):
            if self.w.monitor is not None:
                break
            self.vm.tick_once()
            self.w.step()

    def test_options_commands_render_and_apply_a_difficulty_choice(self):
        w, p = self.w, stub()
        w.call('stmt', 'MON_CODE', [512], p)
        self.assertEqual(w.options.screen, 'difficulty')
        self.assertEqual(play.to_rgb(w).shape, (200, 320, 3))
        self.assertEqual(w.option_activate('HRDX'), 'difficulty:2')
        self.assertEqual(self.vm.globals['_difficulty_level'], 2)
        self.assertTrue(w.options.closed)
        w.call('stmt', 'MON_CODE', [1], p)
        self.assertEqual(w.options.screen, 'main')
        self.assertIsNone(w.option_activate('LODX'))
        self.assertEqual(w.options.screen, 'load')
        self.assertIsNone(w.option_activate('LOKX'))
        self.assertEqual(w.options.screen, 'confirm')
        w.saves_dir = os.path.join(tempfile.gettempdir(), 'bioforge_no_saves')      # nothing saved there
        self.assertEqual(w.option_activate('YESX'), 'load:1')
        self.assertTrue(w.options.closed)
        self.assertIn('load: no save in slot 1', w.warnings)
        w.call('stmt', 'MON_CODE', [1], p)
        w.call('stmt', 'MON_DESTROYOPTIONS', [], p)
        self.assertTrue(w.options.closed)

    def test_simulated_tab_reaches_script_monitor_button(self):
        w, p = self.w, stub()
        w.call('stmt', 'MON_START', ['MLBT'], p)
        w.call('stmt', 'MON_DEFINEBUTTON', ['PWRB', 2], p)
        w.call('stmt', 'MON_SIMULATE', [9], p)
        for _ in range(60):
            w.monitor.update()
        self.assertEqual(w.monitor.hovered.name, 'PWRB')

    def test_real_tab_glides_and_shift_tab_goes_back(self):
        w, p = self.w, stub()
        w.call('stmt', 'MON_START', ['MLBT'], p)
        w.call('stmt', 'MON_DEFINEBUTTON', ['PWRB', 2], p)
        w.call('stmt', 'MON_DEFINEBUTTON', ['MANB', 2], p)
        w.key_down(0x0f)                                   # FUN_10e8_11e3 hands the key to the monitor: the focus moves, the pointer glides
        self.assertEqual((w.monitor.focus.name, w.monitor.glide['target']), ('MANB', (160, 186)))
        w.key_up(0x0f)
        w.key_down(0x0f, mods=0x0c)                        # Shift+Tab
        self.assertEqual(w.monitor.focus.name, 'PWRB')

    def test_right_click_in_the_world_only_acts_on_a_monitor(self):
        w, p = self.w, stub()
        w.monitor_right_click()                            # plain play: nothing
        w.call('stmt', 'MON_START', ['MLBT'], p)
        w.monitor_right_click()
        self.assertEqual(w.monitor.poll(), ('ESCAPE_BUTTON', True))

    def test_keys_are_recorded_as_before_without_a_monitor(self):
        w = self.w
        w.key_down(0x0f)                                   # Tab is nothing in play
        self.assertIsNone(w.monitor)
        self.assertEqual(w.keys_held, [0x0f])              # recorded as before; the monitor code is never reached

    def test_start_stop_and_is_running(self):
        w, p = self.w, stub()
        self.assertEqual(w.call('func', 'ISMONITORRUNNING', [], p), 0)
        w.call('stmt', 'MON_START', ['mlbt'], p)
        self.assertEqual((w.monitor.name, w.call('func', 'ISMONITORRUNNING', [], p)), ('MLBT', 1))
        w.call('stmt', 'MON_DEFINEBUTTON', ['pwrb', 'POWER /FCONTACT', 2, 1], p)
        self.assertEqual((w.monitor.elements['PWRB'].state, w.monitor.elements['PWRB'].mode), (mon.NORMAL, 1))
        w.call('stmt', 'MON_DEFINEBUTTON', ['pwrb', 6], p)       # state only: not selectable, text kept
        self.assertEqual((w.monitor.elements['PWRB'].state, w.monitor.elements['PWRB'].text), (mon.NOT_SELECTABLE, 'POWER '))
        w.call('stmt', 'MON_STOP', [], p)
        self.assertEqual((w.monitor, w.call('func', 'ISMONITORRUNNING', [], p)), (None, 0))

    def test_render_uses_current_vm_globals_for_labels_and_text_lists(self):
        w, vm, p = self.w, self.vm, stub()
        vm.globals['_reactor_id_number'] = 17
        w.call('stmt', 'MON_START', ['pimm'], p)
        w.call('stmt', 'MON_DEFINETEXT', ['istl', 'ID %_REACTOR_ID_NUMBER%'], p)
        w.call('stmt', 'MON_DEFINETEXTAREA', ['dest', 'REACTO'], p)
        m = w.monitor
        self.assertEqual(m.elements['ISTL'].text, 'ID %_REACTOR_ID_NUMBER%')
        self.assertIn('%_reactor_id_number%', m.elements['DEST'].entries[0][1])
        m.elements['DEST'].active = False
        label_first, _ = m.render()
        vm.globals['_reactor_id_number'] = 42
        label_second, _ = m.render()
        self.assertNotEqual(bytes(label_first), bytes(label_second))
        m.elements['ISTL'].active = False
        m.elements['DEST'].active = True
        list_first, _ = m.render()
        vm.globals['_reactor_id_number'] = 99
        list_second, _ = m.render()
        self.assertNotEqual(bytes(list_first), bytes(list_second))

    def test_label_time_uses_the_current_vm_tick(self):
        w, vm, p = self.w, self.vm, stub()
        w.call('stmt', 'MON_START', ['pimm'], p)
        w.call('stmt', 'MON_DEFINETEXT', ['istl', '%time%'], p)
        self.assertEqual(w.monitor.expand(w.monitor.elements['ISTL'].text), '0-0000')
        vm.run_ticks(1800)
        self.assertEqual(w.monitor.expand(w.monitor.elements['ISTL'].text), '0-0001')

    def test_mon_jump_dispatches_labels(self):
        self.script("""{ MJ1
	MON_START "mlbt"
	MON_HIDEALL
	MON_DEFINEBUTTON "pwrb" "POWER" _MON_NORMAL
	:LOOP
	MON_JUMP
	SUSPEND
	JUMP LOOP
	:PWRB_HIGHLIGHT
	DEBUG "highlight"
	JUMP LOOP
	:PWRB_RELEASED
	DEBUG "released"
	JUMP LOOP
	:PWRB_BUTTON
	DEBUG "button"
	JUMP LOOP
	:PWRB_REPEAT
	DEBUG "repeat"
	JUMP LOOP
	:ESCAPE_BUTTON
	DEBUG "escape"
	MON_STOP
}
""")
        w, vm = self.w, self.vm
        p = vm.spawn('MJ1')
        vm.run_ticks(3)
        self.assertEqual(DEBUGS(w), [])
        pwr = w.monitor.elements['PWRB']
        w.monitor.pointer_move(pwr.x, pwr.y)
        vm.run_ticks(2)
        w.monitor.mouse_down()
        for _ in range(5 + 1 + mon.REPEAT_DELAY + 4):          # pressed on the 5th tick of the animation
            vm.tick_once()
            w.step()
        w.monitor.mouse_up()
        for _ in range(8):                                         # the release waits for the press animation's end and then runs
            vm.tick_once()
            w.step()
        got = DEBUGS(w)
        self.assertEqual(got[:2], ['highlight', 'button'])
        self.assertIn('repeat', got)
        self.assertEqual(got[-1], 'released')
        self.assertEqual(got.count('button'), 1)
        w.monitor_key('ESCAPE')
        vm.run_ticks(3)
        self.assertEqual(DEBUGS(w)[-1], 'escape')
        self.assertIsNone(w.monitor)
        self.assertTrue(p.done)

    def test_no_monitor_ends_process(self):
        self.script("""{ MJ2
	MON_JUMP
	DEBUG "after"
}
""")
        p = self.vm.spawn('MJ2')
        self.assertTrue(p.done)
        self.assertEqual(DEBUGS(self.w), [])

    def test_robocntl_panel(self):
        vm, w = self.vm, self.w
        vm.load(os.path.join(worldmod.parse.ROOT, 're', 'out', 'scripts', 'ROBOCNTL.scr'))
        w.call('stmt', 'CREATEFIGURE', ['LEX', 'PLAYER'], stub())
        w.start_script(None, 'GR_ROBOTCONTROLPANEL', [1])
        vm.run_ticks(3)
        m = w.monitor
        self.assertEqual(m.name, 'MLBT')
        self.assertEqual((m.elements['PWRB'].active, m.elements['PWRL'].text), (True, 'POWER '))
        self.assertEqual(m.viewport, ('CAMV', 'CTR4'))
        # CTR4 belongs to CONTROL rather than the active CHAOS level.  It is
        # still a live remote feed and rendering it must not select that camera
        # or emit its load events.
        m.pointer['frame'] = 0
        camera, events, changes = w.camera, list(w.events), list(w.camera_changes)
        live, _ = m.render()
        viewport = m.viewport
        m.viewport = None
        without_viewport, _ = m.render()
        m.viewport = viewport
        self.assertNotEqual(bytes(live), bytes(without_viewport))
        self.assertEqual((w.camera, w.events, w.camera_changes), (camera, events, changes))
        self.assertEqual(m.elements['LUPB'].state, mon.INVISIBLE)   # control buttons only appear in manual mode
        w.monitor_tap('manb')
        vm.run_ticks(4)
        self.assertEqual(m.elements['MANB'].state, mon.SELECTED)
        self.assertEqual(m.elements['LUPB'].state, mon.NORMAL)
        w.monitor_tap('pwrb')                                      # PWRB_BUTTON leaves the monitor
        vm.run_ticks(4)
        self.assertIsNone(w.monitor)
        self.assertFalse([x for x in w.warnings + vm.warnings if 'unknown' in x.lower()])

    def test_viewport_updates_when_a_visible_room_sprite_frame_changes(self):
        vm, w = self.vm, self.w
        m = mon.Monitor('MLBT', viewport_frame=w.monitor_viewport_frame)
        m.pointer['frame'] = 0
        m.define_viewport('CAMV', 'CE42')
        first, _ = m.render()
        vm.globals['_br3_frame'] = 2             # CE42's BR3 sprite is inside MLBT's CAMV crop
        second, _ = m.render()
        self.assertNotEqual(bytes(first), bytes(second))

    def test_unknown_viewport_camera_is_blank_and_warned_once(self):
        m = mon.Monitor('MLBT', viewport_frame=self.w.monitor_viewport_frame)
        m.pointer['frame'] = 0
        m.define_viewport('CAMV', 'NO_SUCH_CAMERA')
        first, _ = m.render()
        second, _ = m.render()
        self.assertEqual(bytes(first), bytes(second))
        self.assertEqual(sum('NO_SUCH_CAMERA' in warning for warning in self.w.warnings), 1)

    def test_pimm_inventory(self):
        vm, w = self.vm, self.w
        w.call('stmt', 'CREATEFIGURE', ['LEX', 'PLAYER'], stub())
        vm.fire('GIVELEXSTARTINGBATT')
        self.assertEqual(w.items['MY_BATTERY'].slot, 'INVENTORY')
        self.open_pimm('INVENTORY')
        m = w.monitor
        self.assertEqual(m.name, 'PIMM')
        inmt = m.elements['INMT']
        self.assertEqual((inmt.items, [k for k, _ in inmt.entries]), (['MY_BATTERY'], ['MONBAT']))
        self.assertEqual(m.elements['IITA'].frame, 1)             # MONBAT's `MONITOR ART FRAME = 1`
        self.assertEqual([k for k, _ in m.elements['DEST'].entries], ['MONBAT'])   # MONBAT_HIGHLIGHT filled the description
        self.assertEqual(m.elements['ISTL'].text, 'INVENTORY')
        px, _ = m.render()
        self.assertEqual(len(px), 64000)
        self.assertFalse([x for x in w.warnings + vm.warnings if 'unknown' in x.lower()])
        w.monitor_tap('rdyb')                                      # READY: MON_SETITEM + PLACEITEM CARRY, then exit
        vm.run_ticks(6)
        self.assertEqual(w.items['MY_BATTERY'].slot, 'RTHAND')
        self.assertIsNone(w.monitor)

    def test_pimm_ready_leaves_an_item_in_inventory_when_its_hand_is_occupied(self):
        vm, w = self.vm, self.w
        w.call('stmt', 'CREATEFIGURE', ['LEX', 'PLAYER'], stub())
        vm.fire('GIVELEXSTARTINGBATT')
        w.items['OTHER_BATTERY'] = worldmod.Item('OTHER_BATTERY', 'MONBAT', 'LEX', 'RTHAND')
        self.open_pimm('INVENTORY')
        self.assertIsNotNone(w.monitor)
        w.monitor_tap('rdyb')
        vm.run_ticks(6)
        self.assertEqual((w.items['MY_BATTERY'].owner, w.items['MY_BATTERY'].slot), ('LEX', 'INVENTORY'))
        self.assertIsNone(w.monitor)

    def test_pimm_screens_run_without_warnings(self):
        vm, w = self.vm, self.w
        w.call('stmt', 'CREATEFIGURE', ['LEX', 'PLAYER'], stub())
        vm.fire('GIVELEXSTARTINGBATT')
        for screen in ('DIAGNOSTICS', 'JOURNAL', ''):
            self.open_pimm(screen)
            self.assertIsNotNone(w.monitor, screen)
            self.assertEqual(w.monitor.name, 'PIMM')
            w.monitor_key('ESCAPE')
            vm.run_ticks(4)
            self.assertIsNone(w.monitor, screen)
        self.assertFalse([x for x in w.warnings + vm.warnings if 'unknown' in x.lower() or 'unresolved' in x.lower()])

    def test_journal_persists_earned_entries_and_suppresses_duplicates(self):
        vm, w, p = self.vm, self.w, stub()
        w.call('stmt', 'CREATEFIGURE', ['LEX', 'PLAYER'], p)
        w.call('stmt', 'ADDLOGENTRY', ['LEX', 'SEEGUN'], p)
        w.call('stmt', 'ADDLOGENTRY', ['LEX', 'INJECT'], p)
        w.call('stmt', 'ADDLOGENTRY', ['LEX', 'SEEGUN'], p)
        self.assertEqual(w.log_entries['LEX'], ['SEEGUN', 'INJECT'])
        self.open_pimm('JOURNAL')
        journal = w.monitor.elements['JORT']
        self.assertEqual([key for key, _ in journal.entries], ['SEEGUN', 'INJECT'])
        self.assertIn('gun inside of cell number two', journal.entries[0][1])
        self.assertIn('robot put me to sleep', journal.entries[1][1])
        w.load_objects('LANDPAD')
        self.assertEqual(w.log_entries['LEX'], ['SEEGUN', 'INJECT'])

    def test_remove_log_entry_targets_its_log_and_open_list(self):
        w, p = self.w, stub()
        for key in ('C1REP', 'C2REP'):
            w.call('stmt', 'ADDLOGENTRY', ['GMAINT', key], p)
        w.call('stmt', 'ADDLOGENTRY', ['LEX', 'SEEGUN'], p)
        w.call('stmt', 'MON_START', ['MANT'], p)
        w.call('stmt', 'MON_DEFINELIST', ['RLGT', 'GMAINT'], p)
        self.assertEqual([key for key, _ in w.monitor.elements['RLGT'].entries], ['C1REP', 'C2REP'])
        w.call('stmt', 'REMOVELOGENTRY', ['GMAINT', 'RLGT', 'C1REP'], p)
        self.assertEqual(w.log_entries['GMAINT'], ['C2REP'])
        self.assertEqual([key for key, _ in w.monitor.elements['RLGT'].entries], ['C2REP'])
        self.assertEqual(w.log_entries['LEX'], ['SEEGUN'])

    def test_found_logs_show_their_unkeyed_entries(self):
        """XLOG cases 2-6 (ITEMS.scr:819-836) only MON_DEFINELIST their record: the list adds its '[]' entries itself (FUN_1268_10c5)."""
        for lang in ('E', 'G'):
            self.w.settings.language = lang
            w, p = self.w, stub()
            for source, count in (('caynan', 43), ('dane', 19), ('eshmes', 34), ('lock', 1), ('lock2', 1)):
                w.call('stmt', 'MON_START', ['LGBK'], p)
                w.call('stmt', 'MON_DEFINELIST', ['TEXT', source], p)
                shown = w.monitor.elements['TEXT']
                self.assertEqual(shown.entries, shown.source, (lang, source))
                self.assertEqual((len(shown.entries), {key for key, _ in shown.entries}), (count, {''}), (lang, source))
            w.call('stmt', 'MON_START', ['LGBK'], p)
            w.call('stmt', 'MON_DEFINELIST', ['TEXT', 'caynan'], p)
            first = w.monitor.elements['TEXT'].entries[0][1]
            self.assertTrue(first.startswith({'E': 'd1892-1120 I can still hear Dane', 'G': 'T1892-1120 Ich kann Dane'}[lang]), first)

    def test_dane_log_shows_the_access_code(self):
        """Dane's 12th entry prints the access code ASSIGNRANDOMIDS rolled, which the player needs at the security terminal."""
        w, p = self.w, stub()
        for i, digit in enumerate((3, 1, 4, 1, 5), 1):
            self.vm.globals[f'_access_id{i}_to_match'] = digit
        w.call('stmt', 'MON_START', ['LGBK'], p)
        w.call('stmt', 'MON_DEFINELIST', ['TEXT', 'dane'], p)
        text = mon.substitute(w.monitor.elements['TEXT'].entries[11][1], w.monitor.resolve_var)
        self.assertIn('access code number is 31415', text)

    def test_mixed_record_lists_unkeyed_entries_before_log_keys(self):
        """CMAINT (MAINTMON.scr:123): its 64 '[]' entries in authored order, then the ADDLOGENTRY store's keys (FUN_1268_1213);
        the keyed C1REP..C4REP records stay out until earned. GMAINT and the journal have no '[]' entries and are unchanged."""
        w, p = self.w, stub()
        w.call('stmt', 'MON_START', ['MANT'], p)
        w.call('stmt', 'MON_DEFINELIST', ['RLGT', 'CMAINT'], p)
        source = w.monitor.elements['RLGT'].source
        self.assertEqual(w.monitor.elements['RLGT'].entries, source[:64])
        self.assertEqual({key for key, _ in source[:64]}, {''})
        w.call('stmt', 'ADDLOGENTRY', ['CMAINT', 'C3REP'], p)
        w.call('stmt', 'ADDLOGENTRY', ['CMAINT', 'C1REP'], p)
        w.call('stmt', 'MON_DEFINELIST', ['RLGT', 'CMAINT'], p)
        rlgt = w.monitor.elements['RLGT']
        self.assertEqual([key for key, _ in rlgt.entries], [''] * 64 + ['C3REP', 'C1REP'])
        self.assertEqual(rlgt.entry_times[:64], [None] * 64)
        w.call('stmt', 'REMOVELOGENTRY', ['CMAINT', 'RLGT', 'C3REP'], p)
        self.assertEqual([key for key, _ in rlgt.entries], [''] * 64 + ['C1REP'])
        w.call('stmt', 'ADDLOGENTRY', ['GMAINT', 'C2REP'], p)
        w.call('stmt', 'MON_DEFINELIST', ['RLGT', 'GMAINT'], p)
        self.assertEqual([key for key, _ in w.monitor.elements['RLGT'].entries], ['C2REP'])

    def test_journal_entries_keep_their_award_ticks_through_removal(self):
        vm, w, p = self.vm, self.w, stub()
        w.call('stmt', 'ADDLOGENTRY', ['LEX', 'SEEGUN'], p)
        first = w.log_entry_times['LEX'][0]
        vm.run_ticks(7)
        w.call('stmt', 'ADDLOGENTRY', ['LEX', 'INJECT'], p)
        self.assertEqual(w.log_entries['LEX'], ['SEEGUN', 'INJECT'])
        self.assertEqual(w.log_entry_times['LEX'], [first, first + 7])
        w.call('stmt', 'MON_START', ['PIMM'], p)
        w.call('stmt', 'MON_DEFINELIST', ['JORT', 'LEX'], p)
        self.assertEqual(w.monitor.elements['JORT'].entry_times, [first, first + 7])
        w.call('stmt', 'REMOVELOGENTRY', ['LEX', 'JORT', 'SEEGUN'], p)
        self.assertEqual(w.log_entries['LEX'], ['INJECT'])
        self.assertEqual(w.log_entry_times['LEX'], [first + 7])
        self.assertEqual(w.monitor.elements['JORT'].entry_times, [first + 7])

    def test_journal_times_are_saved_at_award_and_not_reformatted_later(self):
        vm, w, p = self.vm, self.w, stub()
        w.call('stmt', 'ADDLOGENTRY', ['LEX', 'SEEGUN'], p)
        vm.run_ticks(1800)                        # one displayed minute at the inferred 30 -> 60 Hz conversion
        w.call('stmt', 'ADDLOGENTRY', ['LEX', 'INJECT'], p)
        w.call('stmt', 'MON_START', ['PIMM'], p)
        w.call('stmt', 'MON_DEFINELIST', ['JORT', 'LEX'], p)
        journal = w.monitor.elements['JORT']
        self.assertEqual([w.monitor.expand(text, stamp).split(':', 1)[0]
                          for (_, text), stamp in zip(journal.entries, journal.entry_times)], ['0-0000', '0-0001'])
        before, _ = w.monitor.render()
        vm.run_ticks(1800)
        after, _ = w.monitor.render()
        self.assertEqual(bytes(before), bytes(after))


if __name__ == '__main__':
    unittest.main()
