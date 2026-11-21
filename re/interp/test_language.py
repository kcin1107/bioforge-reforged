"""Tests for the language setting (E / G / F, INSTALL.OPT `language=`): the caption and monitor text filter, GETOPTDATA("LANGUAGE"), the sound bank,
the monitor text file, the options dialog text and the intro movie. The Swift twin is LanguageTests.swift.
re/.venv/bin/python -I -W ignore -m unittest discover -s re/interp -p 'test_language.py'"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import monitor  # noqa: E402
import options  # noqa: E402
import play  # noqa: E402
import presentation  # noqa: E402
import settings  # noqa: E402
import test_show  # noqa: E402
import vm as vmmod  # noqa: E402
import world as worldmod  # noqa: E402


class LanguageTests(unittest.TestCase):
    def test_caption_filter_follows_the_language(self):
        s = '/FBonjour/EHello/GHallo'
        self.assertEqual([presentation.caption_text(s, lang) for lang in 'EGF'], ['Hello', 'Hallo', 'Bonjour'])
        self.assertEqual(presentation.caption_text('/EHello/GHallo', 'F'), 'Hello')       # no /F: the English segment
        self.assertEqual(presentation.caption_text('Yep', 'G'), 'Yep')                    # no segments: the whole string
        self.assertEqual(presentation.caption_text('/!', 'G'), '')

    def test_monitor_filter_follows_the_language(self):
        s = 'EXIT/FSORTIE/GZUR\x9aCK'
        self.assertEqual([monitor.localize(s, lang) for lang in 'EGF'], ['EXIT', 'ZUR\x9aCK', 'SORTIE'])

    def test_settings_read_the_language(self):
        self.assertEqual(settings.Settings.from_text('Language=G\r\n').language, 'G')
        self.assertEqual(settings.Settings.from_text('language=f\r\n').language, 'F')
        self.assertEqual(settings.Settings.from_text('Dir=C:\\BIOFORGE\r\n').language, 'E')
        self.assertEqual(settings.Settings.from_text('language=X\r\n').language, 'E')

    def test_getoptdata_language_is_the_setting(self):
        w, vm = test_show.fresh()
        w.settings.language = 'G'
        self.assertEqual([test_show.func(w, 'GETOPTDATA', k) for k in ('LANGUAGE', 'language', 'Soundvol')], [71, 71, 100])
        w.settings.language = 'F'
        self.assertEqual(test_show.func(w, 'GETOPTDATA', 'LANGUAGE'), 70)

    def test_sound_bank_per_language(self):
        english, german = worldmod.sound_bank('E')[0], worldmod.sound_bank('G')[0]
        self.assertEqual((len(english), len(german)), (717, 717))
        self.assertEqual(len(german.get(0).pcm), 11022)                 # GSAMPLES.FLX, not ESAMPLES.FLX
        self.assertEqual(len(english.get(0).pcm), 16054)

    def test_monitor_text_file_per_language(self):
        self.assertIn('Selbstmord', monitor.text_entry('ORRESULT', 'G'))
        self.assertNotIn('Selbstmord', monitor.text_entry('ORRESULT'))
        self.assertIn('PROJECT AFA', monitor.text_entry('ORRESULT', 'E'))

    def test_options_text_per_language(self):
        self.assertEqual([options.pimm_string('EXITSTR', lang) for lang in 'EG'], ['EXIT', 'ZUR\x9aCK'])
        o = options.Options(settings=settings.Settings(language='G'))
        o.open(options.DIFFICULTY)
        self.assertEqual(o.monitor.elements['EZYX'].text, 'EINFACHER KAMPF')

    def test_spoken_subtitles_show_and_time_the_language_text(self):
        for lang, shown in (('E', 'Hello'), ('G', 'H\x84llo w\x94rld'), ('F', 'Bonjour')):
            w = worldmod.World('LANDPAD')
            w.settings.language = lang
            vmmod.VM(w)
            w.subtitle(('_pim_beep_5', 0x75, 0xff, 'Hello/FBonjour/GH\x84llo w\x94rld'))
            (tick, _, colour, text, end), = w.subtitle_log
            n = len(worldmod.sound_bank(lang)[0].get(worldmod.sound_bank(lang)[1]['_pim_beep_5']).pcm)
            self.assertEqual((text, end - tick), (shown, n * 30 // 11025 + len(shown)))

    def test_new_game_starts_the_language_intro(self):
        for lang, flic in (('E', 'INTRO'), ('G', 'INTROG'), ('F', 'INTROF')):
            w, vm = play.boot(0, settings=settings.Settings(language=lang))
            for _ in range(600):
                if w.flic:
                    break
                vm.tick_once()
                w.step()
            self.assertEqual(w.flic and w.flic.name, flic)


if __name__ == '__main__':
    unittest.main()
