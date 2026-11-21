"""Original-asset options dialog preview.

The DOS options dialog is separate from the normal ``MON_*`` script UI.  Its
screens and assets come from ``OPTS.CAM`` (decompiled in ``1280.c``).  This
small model exposes its useful decisions to :mod:`world`, which performs the
save and load actions.  The audio and gamma panels change the persisted :class:`settings.Settings` and apply every change
at once through the callbacks the world passes in (FUN_1100_0dc2 / FUN_1100_0e6f).
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from monitor import HIGHLIGHT, INVISIBLE, NORMAL, NOT_SELECTABLE, ROOT, SELECTED, SEL_HIGH, Monitor, font, localize, text_entry  # noqa: E402
from settings import Settings  # noqa: E402


DEFAULT, MUST_RELOAD, LOAD, SAVE, CREDITS, AUDIO = 1, 2, 4, 8, 16, 32
LEVEL, TEST, NEW, DIFFICULTY, EXIT = 64, 128, 256, 512, 1024
NO_SAVE = 0x800                 # added by FUN_10a8_02cc when saving is refused: the main panel's Save button is disabled
SBT_OFF, SBT_ON = 1, 3          # SBTX button state: > 2 = subtitles on (callback AOKX: 2 < state)
TOGGLES = ('SFXX', 'MSCX', 'SBTX')    # FUN_1258_0512 mode 1 (+0x40; 1280.c:296, 299, 1280_callbacks.c MSCX): the highlight keeps their selection
# The confirm prompt of each mode (FUN_1280_214c: the string at a41c + mode * 0x1e), as PIMM.SCP keys.
PROMPTS = ('QEXITTODOSSTR', 'QRETURNTOGAMESTR', 'QLOADGAMESTR', 'QNEWGAMESTR', 'QSAVEGAMESTR', 'QSAVEOVERSTR')
_STRINGS = {}

# The credits roll (re/out/credits_live/SPEC.md: the page of FUN_1280_221e / 1278:1c08, measured on the original's VGA dumps).
CREDITS_STOPS = (60, 60, 180, 180, 180)       # _CrCol1..4, the 5th copies the 4th
CREDITS_CENTRE = 160                          # (left + right) >> 1 of the 0,0,320,200 widget
CREDITS_PITCH = 12                            # glyph height of 'A' (11) + line gap (1)
CREDITS_COLOURS = (249, 200)                  # CRDT header colours 1 (text) and 2 (a \x02 heading line)
CREDITS_SHADOW = 0                            # the DR shadow, palette 0, one pixel right and down, drawn first


def credits_lines(raw):
    """FUN_1248_0a5b's stream model -> [(text, heading)] display lines. `\n` ends a line; `\r` also swallows the next `\n`; `\x02` marks a
    heading and is not stored; tab and 0x20..0xe1 are stored; any other byte (the final NUL) ends the line. After a line ends, if the next byte is a
    newline one more is swallowed (1248:0e09 ignore(2, '\n')), so k newlines after text make ceil(k / 2) line steps."""
    out, i, n = [], 0, len(raw)
    while i < n:
        buf, head = '', False
        while i < n:
            c = raw[i]
            i += 1
            if c == '\n':
                break
            if c == '\r':
                if i < n:
                    i += 1
                break
            if c == '\x02':
                head = True
                continue
            if c == '\t' or ' ' <= c <= '\xe1':
                buf += c
                continue
            break
        if i < n and raw[i] in '\n\r':
            i += 1
            if raw[i - 1] == '\r' and i < n and raw[i] == '\n':
                i += 1
        out.append((buf, head))
    return out


def credits_done(count):
    """The scroll position the roll stops at: 12 * (lines - 2 - 18 + 1) = 2784 for the 251 lines of CREDITS."""
    return CREDITS_PITCH * (count - 2 - 18 + 1)


def pimm_string(key, lang='E'):
    """The `lang` text of `< KEY = "ENGLISH/FFRENCH/GGERMAN" >` in SCRIPT/PIMM.SCP (the options text, loaded by FUN_1280_0212)."""
    if lang not in _STRINGS:
        raw = open(os.path.join(ROOT, 'game', 'app', 'Bioforge', 'SCRIPT', 'PIMM.SCP'), 'rb').read().decode('latin1')
        _STRINGS[lang] = {m.group(1): localize(m.group(2), lang).strip() for m in re.finditer(r'<\s*(\w+)\s*=\s*"([^"]*)"', raw)}
    return _STRINGS[lang][key]


class Options:
    """A stateful rendering of the recovered options screens.

    ``activate(name)`` accepts either UI asset names (``EZYX``) or semantic
    names (``EASY``) and returns a compact action string.  The same value is
    available as ``last_action`` for callers which drive the dialog from mouse
    hit tests.  The recovered nine-slot screens are selectable; confirming a slot
    returns ``save:<slot>`` or ``load:<slot>`` (``unsupported:new`` for New Game).  The audio panel returns
    ``audio:<sfx>,<music>`` (levels 0..100) and the gamma panel ``gamma:<g>`` for every change and for OK.
    """
    def __init__(self, difficulty=1, settings=None, apply_audio=None, apply_gamma=None, slot_used=None):
        self.monitor = Monitor('OPTS', language=settings.language if settings is not None else 'E')
        self.monitor.translucent = ('X',)                                    # the buttons blend with the screen (FUN_1270_185b)
        self.difficulty = max(0, min(2, int(difficulty)))
        self.settings = settings if settings is not None else Settings()
        self.language = self.settings.language                                # the language the texts were read in
        self._apply_audio = apply_audio or (lambda sfx, music: None)
        self._apply_gamma = apply_gamma or (lambda g: None)
        self._slot_used = slot_used or (lambda slot: False)                   # whether a save exists in the slot (DAT_a86d == 5 when not)
        self.sfx, self.music = self.settings.sound, self.settings.music      # working levels (d712 / d714)
        self.saved = (self.sfx, self.music)                                   # the levels when the panel opened (d70e / d710)
        self.sbt = self.settings.subtitles                                    # SBTX button state > 2
        self.gamma = self.settings.gamma                                      # working gamma (a364)
        self.flags = 0
        self.screen = None
        self.closed = True
        self.last_action = None
        self.hovered = None
        self.pressed = None                                                   # the control a mouse down went to (the pointer's press action)
        self.queued = []                                                      # actions a delayed mouse release produced, for update()'s caller
        self.monitor.press_action, self.monitor.release_action = self._press_control, self._release_control
        self.monitor.buttons_fn, self.monitor.hover_fn = self._focusable_controls, self._hover_control    # the keys (monitor.key_event) move over its X controls
        self._controls = {}
        self.slot = 1
        self._confirm_action = 'exit'
        self._credits = text_entry('CREDITS', self.settings.language) or ''
        self.credits_lines = credits_lines(self._credits)
        self.credits_pos = 0                                                  # s = 12 * T - o: pixels scrolled
        self.credits_state = 0                                                # CREDITSSTATE [9ce5]: 0 none, 1 scrolling, 2 done
        self.credits_lockout = False                                          # [4e3b] = 0x29a: keys ignored until the first update
        self.credits_mode = False                                             # [a36c]: the dialog opened with _OPTS_CREDITS or has shown the page (FUN_1100_0ae6 acts on close)
        self.resumed = False                                                  # the world was resumed for the page (FUN_1100_0716): the dialog does not pause
        self.on_credits_page = None                                           # the World's 221e effects (0716 resume, 0740 song), called when the page is set up

    def _clear(self):
        self.monitor.hide_all()
        self.monitor.set_frame('FRMA', 1)

    def _frame(self, *names):
        for name in names:
            self.monitor.set_frame(name, 1)

    def _controls_for(self, *pairs):
        """Active original X controls as ``(asset name, semantic name)`` pairs. The screen is built: FUN_1258_0512 runs FUN_1250_19bc
        after each selectable button it defines (except a state-2 one), so the control under the pointer is highlighted at once."""
        self._controls = {asset: semantic for asset, semantic in pairs}
        self._highlight()

    def _main(self):
        self._clear()
        # Only the buttons with a label element (first 3 letters + 'L') show text: here CRDL and GMAL.  OPTS.CAM has no DETX.
        self._button('EXTX', 2, 'EXITSTR')        # FUN_1280_176b: EXTX state 2
        for name, key in (('CRDX', 'CREDITSSTR'), ('LODX', 'LOADSTR'), ('AUDX', 'AUDIOSTR'), ('GMAX', 'GAMMACORRECTIONSTR')):
            self._button(name, 1, key)
        # FUN_1280_176b: SAVX state 5 (disabled) for MUST_RELOAD or NO_SAVE (0x800), RETX for MUST_RELOAD (seen live after a death)
        self._button('SAVX', NOT_SELECTABLE if self.flags & (MUST_RELOAD | NO_SAVE) else 1, 'SAVESTR')
        self._button('RETX', NOT_SELECTABLE if self.flags & MUST_RELOAD else 1, 'GAMESTR')
        self._controls_for(('EXTX', 'EXIT'), ('CRDX', 'CREDITS'), ('LODX', 'LOAD'),
                           ('SAVX', 'SAVE'), ('AUDX', 'AUDIO'), ('GMAX', 'GAMMA'),
                           ('RETX', 'RETURN'))
        self.screen = 'main'

    def _difficulty(self):
        self._clear()
        for name, key in (('EZYX', 'LEVELEASYSTR'), ('MEDX', 'LEVELMEDSTR'), ('HRDX', 'LEVELHARDSTR')):
            self._button(name, 1, key)
        self._controls_for(('EZYX', 'EASY'), ('MEDX', 'MEDIUM'), ('HRDX', 'HARD'))
        self.screen = 'difficulty'

    def _button(self, name, state=1, text=None):
        """A panel button in `state` (1 normal, 2 default, 3 selected; the frame the monitor draws for a button is its state).
        `text` is a PIMM.SCP key: FUN_1258_0512 shows it only in the button's label element (first 3 letters + 'L'), if there is one.
        A default (state 2) starts normal once the mouse has moved ([9dca] & 2); before that it takes the focus and the pointer jumps
        to its centre (pointer +0x1c = FUN_1270_08ef), which puts the mouse there too (FUN_1250_1a78). The port redraws a whole panel
        for a step the original makes on one button, and a redraw leaves the default alone (normal, the pointer stays)."""
        if state == HIGHLIGHT and (self.monitor.mouse_moved or self._redraw):
            state = NORMAL
        self.monitor.set_frame(name, state)        # the drawn frame is the state: live, EXTX shows frame 2 and a disabled button frame 5
        self.monitor.define_button(name, pimm_string(text, self.settings.language) if text else None, state, int(name in TOGGLES))
        if state == HIGHLIGHT:
            e = self.monitor.el(name)
            self.monitor.focus = e
            if self.monitor.set_pointer_pos(e.x + e.w // 2, e.y + e.h // 2):
                self.monitor.mouse_warp = self.monitor.pointer['pos']

    def _audio(self):
        """FUN_1280_1cc5: both levels come from the persisted settings, which are also what Cancel restores."""
        s = self.settings
        self.sfx, self.music, self.saved, self.sbt = s.sound, s.music, (s.sound, s.music), s.subtitles
        self._audio_draw()

    def _audio_draw(self, redraw=False):
        self._redraw = redraw
        self._clear()
        # SFXX / MSCX show state 1 at level 0 and 3 otherwise (FUN_1280_0803 / 0884 keep them in step with the levels)
        self._button('SFXX', 1 if self.sfx == 0 else 3, 'SFXSTR')
        self._button('SFPX')
        self._button('SFMX')
        self._button('MSCX', 1 if self.music == 0 else 3, 'MUSICSTR')
        self._button('MSPX')
        self._button('MSMX')
        self._button('SBTX', SBT_ON if self.sbt else SBT_OFF)
        self._button('AOKX', 2, 'OKSTR')
        self._button('ACAX', 1, 'CANCELSTR')
        self.monitor.set_gauge('SFXQ', self._gauge(self.sfx))
        self.monitor.set_gauge('MSCQ', self._gauge(self.music))
        self._controls_for(('SFXX', 'SFX'), ('MSCX', 'MUSIC'), ('SBTX', 'SUBTITLES'), ('SFPX', 'SFX+'), ('SFMX', 'SFX-'),
                           ('MSPX', 'MUSIC+'), ('MSMX', 'MUSIC-'), ('AOKX', 'OK'), ('ACAX', 'CANCEL'))
        self.screen, self._redraw = 'audio', False

    @staticmethod
    def _gauge(value):
        """The last frame a gauge draws for a level 0..100: 1270:0b57 keeps n = (frames - 2) * value / 100 and 1270:0a64 draws frames 1..n + 1."""
        return max(1, min(11, int(value) // 10 + 1))

    def _gamma_panel(self):
        """FUN_1280_1ff1 (screen mode 0x47): the working value starts at the persisted gamma."""
        self.gamma = self.settings.gamma
        self._gamma_draw()

    def _gamma_draw(self, redraw=False):
        self._redraw = redraw
        self._clear()
        self._button('GMPX')
        self._button('GMMX')
        self.monitor.set_gauge('GMAQ', self._gauge(self.gamma))
        self._button('AOKX', 2, 'OKSTR')              # ASSUMPTION: FUN_1280_1ff1 is not decompiled; OK / Cancel are labelled as on the audio panel
        self._button('ACAX', 1, 'CANCELSTR')
        self._controls_for(('GMPX', 'GAMMA+'), ('GMMX', 'GAMMA-'), ('AOKX', 'OK'), ('ACAX', 'CANCEL'))
        self.screen, self._redraw = 'gamma', False

    def _leave(self, action):
        """Leaving a sub-screen (OK / Cancel on the audio or gamma panel, LCAX, NOOX; 1280_callbacks.c): a366 = 0, then the main
        panel if the dialog was opened with _OPTS_DEFAULT, else the callback turns the press into Escape (LAB_1280_0e57). With
        MUST_RELOAD that Escape brings up the exit prompt (FUN_1280_214c(0)) instead of closing, so a dead Lex never gets back to
        the game without a load."""
        if self.flags & DEFAULT:
            self._main()
        elif self.flags & MUST_RELOAD:
            self._confirm(0)
        else:
            return self._close(action)
        self.last_action = action
        return action

    def _credits_screen(self):
        """FUN_1280_221e: the roll starts at the top with the key lockout set. The page is only text over the live scene (the world draws it)."""
        self.monitor.hide_all()
        self.credits_mode = True
        self.credits_pos, self.credits_state, self.credits_lockout = 0, 0, True
        self._controls_for()
        self.screen = 'credits'
        if self.on_credits_page is not None:                                  # unless _forcing_reload: 0716 then 0740. Nothing pauses again when the page is left
            self.on_credits_page()

    def _credits_update(self):
        """1278:1c08, once per dialog frame (one port tick): at the end position state 2 and no scroll, else state 1, the lockout cleared and
        the picture one pixel further."""
        if self.credits_pos >= credits_done(len(self.credits_lines)):
            self.credits_state = 2
        else:
            self.credits_state, self.credits_lockout = 1, False
            self.credits_pos += 1

    def credits_pixels(self, pos=None):
        """The roll at scroll position `pos` (default: now) -> (200x320 uint8 palette indices, 200x320 bool drawn mask). Lines from T = pos // 12 at
        baselines 8 + o + 12k, o = -(pos % 12), until the baseline passes 208; each centred about x = 160 in font 1 (spacing 1), the shadow first."""
        import numpy as np
        pos = self.credits_pos if pos is None else pos
        fnt = font(1)
        img, mask = bytearray(64000), bytearray(64000)

        def adv(ch, x):
            if ch == '\t':
                return next((st - x for st in CREDITS_STOPS if x < st), 0)
            c = ord(ch)
            return fnt.glyphs[c][0] if 0x20 <= c < len(fnt.glyphs) else fnt.glyphs[0x41][0]

        top, off = divmod(pos, CREDITS_PITCH)
        y, i = 8 - off, top
        while i < len(self.credits_lines):
            text, heading = self.credits_lines[i]
            width = sum(adv(ch, 0) + 1 for ch in text + '\n') - 1                  # measured with x fixed at the column start
            start = max(0, CREDITS_CENTRE - width // 2)
            for shift, colour in ((1, CREDITS_SHADOW), (0, CREDITS_COLOURS[heading])):
                x = start + shift
                for ch in text:
                    if ch != '\t' and ord(ch) >= 0x20:
                        fnt.draw((img, 320, 200), x, y + shift, ch, colour, baseline=True)
                        fnt.draw((mask, 320, 200), x, y + shift, ch, 1, baseline=True)
                    x += adv(ch, x) + 1
            y += CREDITS_PITCH
            i += 1
            if y > 208:
                break
        return (np.frombuffer(bytes(img), np.uint8).reshape(200, 320), np.frombuffer(bytes(mask), np.uint8).reshape(200, 320).astype(bool))

    def _slots(self, mode):
        self._clear()
        self._frame('LLFX', 'LRTX')
        self._button('LOKX', 1, 'LOADSTR' if mode == 'load' else 'SAVESTR')
        self._button('LCAX', 1, 'CANCELSTR')
        if mode == 'load':
            self._button('LNWX', 1, 'NEWSTR')
        self.monitor.set_frame('SELG', self.slot)
        for number in range(1, 10):
            self.monitor.set_frame('SE%dX' % number, 1)
        pairs = [('SE%dX' % n, 'SLOT%d' % n) for n in range(1, 10)]
        pairs += [('LLFX', 'LEFT'), ('LRTX', 'RIGHT'), ('LOKX', 'OK'), ('LCAX', 'CANCEL')]
        if mode == 'load':
            pairs.append(('LNWX', 'NEW'))
        self._controls_for(*pairs)
        self.screen = mode

    def _confirm(self, mode=0, action='exit'):
        """FUN_1280_214c(mode): the yes / no box; QSTL shows the prompt PROMPTS[mode] (FUN_1258_07cf), modes 2 and 5 also frame SELG 0xf."""
        self._clear()
        self._confirm_action = action
        self._frame('QSTY')
        self.monitor.define_text('QSTL', pimm_string(PROMPTS[mode], self.settings.language))
        if mode in (2, 5):
            self.monitor.set_frame('SELG', 0xf)
        self._button('YESX', 2, 'YESSTR')
        self._button('NOOX', 1, 'NOSTR')
        self._controls_for(('YESX', 'YES'), ('NOOX', 'NO'))
        self.screen = 'confirm'

    def open(self, flags=DEFAULT):
        """Open the screen selected by the native ``MON_CODE`` flag priority."""
        self.flags = int(flags)
        self.closed, self.last_action, self.hovered = False, None, None
        self.credits_mode, self.resumed = bool(self.flags & CREDITS), False
        if self.flags & DEFAULT:
            self._main()
        elif self.flags & LOAD:
            self._slots('load')
        elif self.flags & SAVE:
            self._slots('save')
        elif self.flags & CREDITS:
            self._credits_screen()
        elif self.flags & AUDIO:
            self._audio()
        elif self.flags & (LEVEL | TEST | NEW | DIFFICULTY):
            self._difficulty()
        elif self.flags & EXIT:
            self._confirm(0)
        else:
            self._main()
        return self.last_action

    _escaping = False                                  # True while key() passes Escape on as Cancel
    _redraw = False                                    # True while the audio / gamma panel is redrawn for a step (_button)

    def _close(self, action):
        self.closed, self.last_action = True, action
        return action

    def activate(self, button):
        """Activate a named control and return its observable semantic action."""
        name = str(button).upper()
        if name.endswith('_BUTTON'):
            name = name[:-7]
        aliases = {'EZYX': 'EASY', 'MEDX': 'MEDIUM', 'HRDX': 'HARD',
                   'AOKX': 'OK', 'ACAX': 'CANCEL', 'LCAX': 'CANCEL',
                   'YESX': 'YES', 'NOOX': 'NO', 'SFPX': 'SFX+', 'SFMX': 'SFX-',
                   'MSPX': 'MUSIC+', 'MSMX': 'MUSIC-', 'CRDX': 'CREDITS',
                   'AUDX': 'AUDIO', 'LODX': 'LOAD', 'SAVX': 'SAVE', 'GMAX': 'GAMMA',
                   'RETX': 'RETURN', 'EXTX': 'EXIT', 'DETX': 'DETAIL', 'GMPX': 'GAMMA+', 'GMMX': 'GAMMA-',
                   'SFXX': 'SFX', 'MSCX': 'MUSIC', 'SBTX': 'SUBTITLES',
                   'LLFX': 'LEFT', 'LRTX': 'RIGHT', 'LOKX': 'OK', 'LNWX': 'NEW'}
        name = aliases.get(name, name)
        if len(name) == 4 and name.startswith('SE') and name[2].isdigit() and name[3] == 'X':
            name = 'SLOT' + name[2]
        self.last_action = None
        if self.closed:
            return None
        if self.screen == 'main':
            if name == 'CREDITS':
                self._credits_screen()
            elif name == 'AUDIO':
                self._audio()
            elif name == 'EXIT':
                self._confirm(0)
            elif name == 'RETURN' and not self.flags & MUST_RELOAD:    # RETX disabled: a dead player cannot go back to the game
                return self._close('return')
            elif name == 'LOAD' or name == 'SAVE' and not self.flags & (MUST_RELOAD | NO_SAVE):
                self._slots(name.lower())
            elif name == 'GAMMA':
                self._gamma_panel()
            # DETAIL: the original callback has no DETX branch, so the button does nothing
            return self.last_action
        if self.screen in ('load', 'save'):
            if name.startswith('SLOT') and name[4:].isdigit():
                number = int(name[4:])
                if 1 <= number <= 9:
                    self.slot = number
            elif name == 'LEFT':
                self.slot = max(1, self.slot - 1)
            elif name == 'RIGHT':
                self.slot = min(9, self.slot + 1)
            elif name == 'OK':
                mode = self.screen
                if mode == 'load':
                    self._confirm(2, mode)
                else:
                    self._confirm(5 if self._slot_used(self.slot) else 4, mode)
                return None
            elif name == 'NEW' and self.screen == 'load':
                self._confirm(3, 'new')
                return None
            elif name in ('CANCEL', 'ESCAPE'):
                return self._close('cancel') if self._escaping else self._leave('cancel')
            self.monitor.set_frame('SELG', self.slot)
            return None
        if self.screen == 'difficulty':
            choices = {'EASY': 0, 'MEDIUM': 1, 'HARD': 2}
            if name in choices:
                self.difficulty = choices[name]
                return self._close('difficulty:' + str(self.difficulty))
            return None
        if self.screen == 'audio':
            if name == 'SFX-':
                self.sfx = max(0, self.sfx - 10)
            elif name == 'SFX+':
                self.sfx = min(100, self.sfx + 10)
            elif name == 'SFX':                        # SFXX toggles 0 <-> 100
                self.sfx = 100 if self.sfx == 0 else 0
            elif name == 'MUSIC-':
                self.music = max(0, self.music - 10)
            elif name == 'MUSIC+':
                self.music = min(100, self.music + 10)
            elif name == 'MUSIC':                      # MSCX toggles 0 <-> 100
                self.music = 100 if self.music == 0 else 0
            elif name == 'SUBTITLES':
                self.sbt = not self.sbt
                self._audio_draw(redraw=True)
                return None
            elif name == 'OK':
                s = self.settings
                s.subtitles = self.sbt
                s.sound, s.music = self.saved = (self.sfx, self.music)
                self._apply_audio(self.sfx, self.music)
                return self._leave('audio:%d,%d' % (self.sfx, self.music))
            elif name == 'CANCEL':
                self.sfx, self.music = self.saved
                self._apply_audio(self.sfx, self.music)
                return self._leave('cancel')
            else:
                return None
            if self.sfx == 0 and name.startswith('SFX'):
                self.sbt = True                        # FUN_1280_0803(1) forces SBTX to state 3 when the effects go silent
            self._apply_audio(self.sfx, self.music)
            self._audio_draw(redraw=True)
            self.last_action = 'audio:%d,%d' % (self.sfx, self.music)
            return self.last_action
        if self.screen == 'gamma':
            if name == 'GAMMA-':
                if self.gamma > 9:
                    self.gamma -= 10
            elif name == 'GAMMA+':
                if self.gamma < 91:
                    self.gamma += 10
            elif name == 'OK':
                self.settings.gamma = self.gamma
                self._apply_gamma(self.gamma)
                return self._leave('gamma:%d' % self.gamma)
            elif name == 'CANCEL':
                self.gamma = self.settings.gamma
                self._apply_gamma(self.gamma)
                return self._leave('cancel')
            else:
                return None
            self._apply_gamma(self.gamma)
            self._gamma_draw(redraw=True)
            self.last_action = 'gamma:%d' % self.gamma
            return self.last_action
        if self.screen == 'credits':
            if self.credits_lockout:
                return None
            if name in ('RETURN', 'CANCEL', 'ESCAPE'):
                return self._close('return') if self._escaping else self._leave('return')
            return None
        if self.screen == 'confirm':
            if name == 'YES':
                if self._confirm_action == 'exit':
                    return self._close('exit')
                if self._confirm_action in ('load', 'save'):
                    return self._close(f'{self._confirm_action}:{self.slot}')
                return self._close('unsupported:' + self._confirm_action)
            if name in ('NO', 'CANCEL', 'ESCAPE'):
                if self._confirm_action in ('load', 'save'):
                    self._slots(self._confirm_action)
                    return None
                return self._close('cancel') if self._escaping else self._leave('cancel')
        return None

    def key(self, name):
        if not self.monitor.input_enabled:             # the dialog is the current monitor: FUN_1250_0cf9 drops keys while the pointer presses
            return None
        name = str(name).upper()
        if self.screen == 'credits' and self.credits_lockout:      # [4e3b] = 0x29a (FUN_1100_0769 acts only at 0)
            return None
        if name == 'ESCAPE' and self.flags & MUST_RELOAD:
            # Escape with MUST_RELOAD (1280_callbacks.c, the end of the key path): the exit prompt, or from that prompt (a366 0x51)
            # the main panel.
            if self.screen == 'confirm':
                self._main()
            else:
                self._confirm(0)
            return None
        if name == 'ESCAPE':
            # Escape otherwise goes to the monitor's own handler (FUN_1250_0cf9), which closes the dialog: not back to the main panel.
            self._escaping = True
            try:
                return self.activate('CANCEL' if self.screen != 'main' else 'RETURN')
            finally:
                self._escaping = False
        return None

    def right_click(self):
        """The right mouse button: the dialog's event handler hands it to the monitor's (FUN_1250_0cf9), which presses "ESCAPE" as for the key, so
        the dialog closes (or backs out) through its Escape path without the MUST_RELOAD special case, which tests the key byte 0x1b
        (1280_callbacks.c)."""
        if self.closed or not self.monitor.input_enabled:
            return None
        self._escaping = True
        try:
            return self.activate('CANCEL' if self.screen != 'main' else 'RETURN')
        finally:
            self._escaping = False

    def _focusable_controls(self):
        """The active X controls in definition order: the buttons FUN_1250_0cf9's key handling cycles through."""
        found = (self.monitor.elements.get(asset) for asset in self._controls)
        return [e for e in found if e is not None and e.active]

    def _hover_control(self):
        """FUN_1250_19bc for the dialog: the control under the pointer is highlighted and takes the focus."""
        self.hovered = None if self.closed else self._control_at(*self.monitor.pointer['pos'])
        self._highlight()
        return self.hovered is not None

    def _selectable(self, asset):
        """Button vtable +0x18 (FUN_1260_06e2): a control in state 1..4. Its state is the frame it draws."""
        e = self.monitor.elements.get(asset)
        return e is not None and e.active and e.frame not in (INVISIBLE, NOT_SELECTABLE)

    def _set_state(self, e, state):
        """Button vtable +0x20 (FUN_1278_0894): the state is the bar's frame and its label's text colour (px[state - 1])."""
        e.frame = e.state = state
        lab = self.monitor.label_for(e)
        if lab is not None and lab.active:
            lab.state = state

    def _unhighlight(self, e):
        """Button vtable +0x28 (FUN_1278_0844): back to normal (1); a toggle (mode 1) keeps its selection (4 -> 3, 3 stays)."""
        toggle = e.name in TOGGLES
        if e.frame == SEL_HIGH:
            self._set_state(e, SELECTED if toggle else NORMAL)
        elif e.frame == HIGHLIGHT or not toggle:
            self._set_state(e, NORMAL)

    def _highlight(self):
        """FUN_1250_19bc: FUN_1250_158e takes the highlight off the focus; with a selectable control under the pointer (FUN_1250_1889),
        FUN_1250_166b takes it off every selectable control and puts it on that one (vtable +0x24, FUN_1278_0803: 2, or 4 for a selected
        toggle), which becomes the focus. Off every control nothing is highlighted. A brighter bar (frame 2) and brighter label text."""
        if self.closed:
            return
        sel = [self.monitor.elements[a] for a in self._controls if self._selectable(a)]
        if not sel:                                # FUN_1250_0449: no selectable button, nothing to do
            return
        if self.monitor.focus not in sel:          # 0449 moves a stale focus to the first selectable button
            self.monitor.focus = sel[0]
        self._unhighlight(self.monitor.focus)
        x, y = self.monitor.pointer['pos']
        under = next((e for e in sel if e.hit(x, y)), None)
        if under is None:
            return
        for e in sel:
            self._unhighlight(e)
        self._set_state(under, SEL_HIGH if under.name in TOGGLES and under.frame in (SELECTED, SEL_HIGH) else HIGHLIGHT)
        self.monitor.focus = under

    def _control_at(self, x, y):
        for asset in reversed(tuple(self._controls)):
            element = self.monitor.el(asset)
            if element is not None and element.active and element.hit(x, y):
                return asset
        return None

    def pointer_move(self, x, y):
        """Return the active original X-control under authored screen coordinates (the pointer ignores the move while it animates)."""
        if not self.monitor.input_enabled:
            return self.hovered
        self.monitor.mouse_moved = True            # FUN_1250_1a21: [9dca] |= 2, then the move and FUN_1250_19bc
        if self.monitor.set_pointer_pos(x, y):
            self._hover_control()
        return self.hovered

    def click(self, x, y):
        """Hit-test then activate an original X-control at authored coordinates (immediate; the app uses mouse_down / mouse_up)."""
        asset = self.pointer_move(x, y)
        return self.activate(self._controls[asset]) if asset else None

    def mouse_down(self):
        """The mouse button went down: through the pointer's press animation (monitor.Monitor.mouse_down)."""
        return self.monitor.mouse_down()

    def mouse_up(self):
        """The mouse button went up: the control pressed is activated, if the pointer is still over it, when the pointer releases."""
        self.monitor.mouse_up()

    def update(self):
        """The pointer's per-tick update, also while the dialog pauses the game. -> the actions its release activated since the last call."""
        self.monitor.update()
        if self.screen == 'credits' and not self.closed:
            self._credits_update()
        done, self.queued = self.queued, []
        return done

    def _press_control(self):
        """The pointer's press action: remember the control under it."""
        self.pressed = None if self.closed else self._control_at(*self.monitor.pointer['pos'])
        return self.pressed is not None

    def _release_control(self):
        """The pointer's release action: today's click semantics, activate the pressed control only if the pointer is still over it."""
        pressed, self.pressed = self.pressed, None
        if pressed is None or self.closed or self._control_at(*self.monitor.pointer['pos']) != pressed:
            return False
        action = self.activate(self._controls[pressed])
        if action is not None:
            self.queued.append(action)
        return action is not None

    def render(self, underlay=None):
        """Return the 320×200 indexed frame and the original OPTS palette. OPTS.CAM's background is fully transparent: the dialog is
        drawn over what the screen shows (`underlay`, Monitor.render), e.g. the STITLE picture KILLLEX shows before FORCERELOAD."""
        return self.monitor.render(underlay)
