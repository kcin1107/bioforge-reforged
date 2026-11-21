"""Options settings of the original game (INSTALL.OPT) and what they drive (NOTES "Options settings").

INSTALL.OPT is a `Key=Value` text file (CRLF, keys case-insensitive).  The engine reads `Soundvol` and `Musicvol` (default
100, 1150.c ~810), `Gamma` (default 30, 10f0.c ~205) and `subtitles` (default 1) at startup and the options dialog writes
them back (FUN_10f0_06b7).  The prototype reads the file once into a `Settings` object and keeps changes in memory; it never
writes the game folder.

    gamma_offset(g)     FUN_1100_0e6f: (g * 32 - 960) / 100 with C truncation, added to every 6-bit palette channel
    gamma_lut(g)        the same step on 8-bit channels as the pipeline stores them (cam.palette: c * 255 // 63)
    master_table(sfx)   FUN_1028_1da5 / FUN_1100_0dc2: the effect master-volume table at mgr + 0x12f
    music_device(v)     the music driver INSTALL.EXE installed: 'adlib' for MusicCardId 1..3 (Adlib, Sound Blaster,
                        SB Pro/16 get MUSIC/AILADLIB.DLL), 'gm' for 4..7 (AWE32, Wave Blaster, SCC-1, MPU-401 get the AWE32 /
                        MT-32 drivers, which the engine treats alike), None for MUSIC=OFF or id 0 (the game plays no music).
                        A missing or unknown id counts as 'gm' (GOG ships 7).  NOTES "AdLib music".
"""
import functools
import os

HERE = os.path.dirname(os.path.abspath(__file__))
INSTALL_OPT = os.path.join(HERE, '..', '..', 'game', 'app', 'Bioforge', 'INSTALL.OPT')


def parse_install_opt(text):
    """INSTALL.OPT text -> {lower-case key: value string}; lines without '=' are ignored."""
    out = {}
    for line in text.splitlines():
        key, eq, value = line.partition('=')
        if eq:
            out[key.strip().lower()] = value.strip()
    return out


def _number(values, key, default):
    try:
        return int(values[key])
    except (KeyError, ValueError):
        return default


def music_device(values):
    """Parsed INSTALL.OPT -> 'adlib', 'gm' or None (module docstring)."""
    if values.get('music', 'ON').upper() == 'OFF':
        return None
    card = _number(values, 'musiccardid', 7)
    if card == 0:
        return None
    return 'adlib' if 1 <= card <= 3 else 'gm'


LANGUAGES = ('E', 'G', 'F')


def language(values):
    """Parsed INSTALL.OPT -> 'E', 'G' or 'F': the first character of `language=` (an unknown or missing one counts as English)."""
    c = values.get('language', 'E')[:1].upper()
    return c if c in LANGUAGES else 'E'


class Settings:
    """The persisted options: effect and music level (0..100), gamma (0..100), the subtitles switch, and the music device
    ('gm', 'adlib' or None; INSTALL.EXE's choice, which the game itself never changes) and the language ('E', 'G' or 'F': speech, text
    and the intro; INSTALL.OPT `language=`, read once at start-up, 1150.c ~369)."""
    def __init__(self, sound=100, music=100, gamma=30, subtitles=True, device='gm', language='E'):
        self.sound, self.music, self.gamma, self.subtitles = sound, music, gamma, bool(subtitles)
        self.music_device = device
        self.language = language

    @classmethod
    def from_text(cls, text):
        v = parse_install_opt(text)
        return cls(_number(v, 'soundvol', 100), _number(v, 'musicvol', 100), _number(v, 'gamma', 30),
                   _number(v, 'subtitles', 1) != 0, music_device(v), language(v))

    @classmethod
    def load(cls, path=INSTALL_OPT):
        """The user's INSTALL.OPT, or the engine defaults when it is missing."""
        try:
            return cls.from_text(open(path, 'rb').read().decode('latin1'))
        except OSError:
            return cls()


def gamma_offset(g):
    """FUN_1100_0e6f: DAT_49be = (g * 0x20 - 0x3c0) / 100 (C division truncates toward zero): 0 -> -9, 30 -> 0, 50 -> 6, 100 -> 22."""
    n = g * 32 - 960
    return n // 100 if n >= 0 else -(-n // 100)


@functools.lru_cache(maxsize=None)
def gamma_lut(g):
    """256 8-bit channel values after the gamma step (FUN_10e8_16bb): back to the 6-bit VGA value the CAM palette started from,
    add the offset, clamp 0..63, expand with c * 255 // 63 as cam.palette does.  The same offset applies to R, G and B."""
    off = gamma_offset(g)
    return tuple(min(255, max(0, min(63, (c * 63 + 254) // 255 + off)) * 255 // 63) for c in range(256))


def master_table(sfx):
    """FUN_1100_0dc2 -> FUN_1028_1da5: table[i] = (i * v) >> 8, v = min(255, sfx * 255 // 100); the final voice volume is
    table[script volume] (FUN_1028_09d3 and the volume updates pass it to FUN_1000_0345).  sfx < 1 disables effects
    (FUN_1028_08f6 stops every voice): a table of zeros."""
    if sfx < 1:
        return [0] * 256
    v = min(255, sfx * 255 // 100)
    return [(i * v) >> 8 for i in range(256)]
