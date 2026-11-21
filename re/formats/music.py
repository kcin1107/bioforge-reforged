"""BioForge MUSIC.FLX: song/transition tables + XMIDI -> .mid export.

MUSIC.FLX (Origin flex v1, 262 entries) - same design as the Ultima 8 / Crusader music flex:
  [0..48]     49 XMIDI songs, one sequence each. Entry k = song line k of entry 261
              (and = song id k, since ids are 0-9a-zA-M in line order).
  [128..176]  the same 49 songs, second arrangement: entry 128+k pairs with entry k (same
              length in notes/channels, differs in controllers/tempo; 159 = empty gmreset).
              # ASSUMPTION: [0..48] = Roland (MT-32/GS: gmreset carries a GS-reset sysex there,
              # none in 159) and [128..176] = AdLib FM (entry 259 is the AdLib timbre bank).
  [257]       text: 55 transition file names (im1_t7a.mid ...), one per line.
  [258]       ONE XDIR/XMID file holding the 55 transition sequences, in the order of entry 257
              (XDIR INFO count = 0x37 = 55). [260] = same, second arrangement.
  [259]       Miles AdLib timbre bank (GTL), see parse_timbres().
  [261]       text song table, see parse_songs() / parse_transitions().
  everything else is empty.

Entry 261 text:
  <file.xmi> <id char> <measures> <loop_measure>      49 lines (the last, 'M', repeats im1_18a)
  #                                                    section separators / the name 'trans.xmi'
  <from.xmi> <to.xmi> <v0> <v1> ...                    transition rows (one value per measure)
 id char: '0'-'9' -> 0-9, 'a'-'z' -> 10-35, 'A'-'M' -> 36-48 (scripts: MUSIC n); id == entry index.
 measures    = number of measures (counts the 0x77 bar-marker controllers in the XMIDI).
 loop_measure= 1-based measure of the XMIDI for-loop controller (0x74) where the song restarts
               when it loops; 0 = no loop point / loop from start. # ASSUMPTION (matches the
               for-loop position in about half the songs; the rest differ or have no 0x74).
 transition values: 1-based index into entry 257 / sequence index into entry 258 of the transition
 sequence to play when switching from -> to at that measure of the 'from' song; 0 = no transition
 (switch directly). A leading '!' flags the value. # ASSUMPTION: as in ScummVM's Ultima 8 reader
 this is a "negative" value (different playback mode of the transition); exact meaning unproven.

Entry 259: u8 patch, u8 bank, u32 offset (LE) records, 127 melodic (bank 0, patch 0-127) plus
 drum-note patches (bank 0x7f, notes 0x1f-0x57), ends with ff ff; each offset points to a 14-byte
 timbre: u16 length(14), s8 transpose, modulator(5: AVEKM, KSL/TL, AD, SR, WS), u8 feedback/conn,
 carrier(5 bytes). # ASSUMPTION: field names from the Miles AdLib .OPL/GTL layout.

CLI: music.py <MUSIC.FLX> <outdir>  writes <outdir>/<name>.mid (+ alt/<name>.mid for the second
 arrangement), songs.json, transitions.json, adlib_timbres.json.
 music.py [--flx MUSIC.FLX] [--seconds N] [--adlib] (--play ID | --switch "T:ID,T:ID,...") OUT.wav  audition through
 the engine's music sequencer (musicseq.py) + Apple's GM synth (--adlib: the AdLib arrangement through adlib.py's driver port
 and the OPL2 model, mono): --play 10 = song 10 from t=0, --switch =
 MUSIC requests (seconds:song id, -1 = stop). Prints the sequencer trace (starts, transitions, loop restarts).
"""
import struct, sys, os, json
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from flex import read_flex
import xmi

SONG0, ALT0, N_SONGS = 0, 128, 49
E_TRANS_LIST, E_TRANS, E_TIMBRES, E_TRANS_ALT, E_TABLE = 257, 258, 259, 260, 261
CHARS = '0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ'


def _entry(d, ents, i):
    _, off, size, _ = ents[i]
    return d[off:off + size]


def parse_songs(text):
    songs = []
    for ln in text.split('\n')[:N_SONGS]:
        f, c, m, lp = ln.split()
        songs.append(dict(file=f, char=c, id=CHARS.index(c), measures=int(m), loop_measure=int(lp)))
    return songs


def parse_transitions(text):
    rows, in_rows = [], False
    for ln in text.split('\n')[N_SONGS:]:
        w = ln.split()
        if len(w) < 3 or not w[0].endswith('.xmi') or not w[1].endswith('.xmi'): continue
        vals = [(int(v.lstrip('!')), v.startswith('!')) for v in w[3 - 1:]]
        rows.append(dict(src=w[0], dst=w[1], values=[v for v, _ in vals], flags=[int(b) for _, b in vals]))
    return rows


def parse_timbres(b):
    out, p = [], 0
    while b[p:p + 2] != b'\xff\xff':
        patch, bank, off = struct.unpack_from('<BBI', b, p); p += 6
        ln, tr = struct.unpack_from('<Hb', b, off)
        out.append(dict(patch=patch, bank=bank, length=ln, transpose=tr,
                        modulator=list(b[off + 3:off + 8]), feedback=b[off + 8],
                        carrier=list(b[off + 9:off + 14])))
    return out


def export(src, dst):
    d, ents = read_flex(src)
    ent = lambda i: _entry(d, ents, i)
    songs = parse_songs(ent(E_TABLE).decode('latin1'))
    trows = parse_transitions(ent(E_TABLE).decode('latin1'))
    tnames = ent(E_TRANS_LIST).decode('latin1').split()
    os.makedirs(os.path.join(dst, 'alt'), exist_ok=True)
    def write(sub, name, smf, e, extra=None):
        open(os.path.join(dst, sub, name), 'wb').write(smf)
        return dict(file=name.replace('.xmi', '.mid'), flx_entry=e, ticks=xmi.end_tick(smf),
                    seconds=round(xmi.end_tick(smf) / 120, 2), **(extra or {}))
    out = []
    for k, s in enumerate(songs):
        name = s['file'].replace('.xmi', '.mid')
        rec = dict(s)
        rec['file'] = name
        for key, base, sub in (('primary', SONG0, ''), ('alt', ALT0, 'alt')):
            e = base + k
            seqs = xmi.convert(ent(e))
            assert len(seqs) == 1
            r = write(sub, name, seqs[0], e)
            rec[key] = dict(flx_entry=e, seconds=r['seconds'])
        rec['flx_entry'] = SONG0 + k
        rec['alt_flx_entry'] = ALT0 + k
        rec['seconds'] = rec['primary']['seconds']
        out.append(rec)
    json.dump(out, open(os.path.join(dst, 'songs.json'), 'w'), indent=1)
    trans = []
    for sub, e in (('', E_TRANS), ('alt', E_TRANS_ALT)):
        seqs = xmi.convert(ent(e))
        assert len(seqs) == len(tnames), (len(seqs), len(tnames))
        for i, (n, smf) in enumerate(zip(tnames, seqs)):
            r = write(sub, n, smf, e)
            if not sub: trans.append(dict(index=i, ref=i + 1, file=n, flx_entry=E_TRANS, sequence=i, seconds=r['seconds']))
    json.dump(dict(files=trans, rows=trows), open(os.path.join(dst, 'transitions.json'), 'w'), indent=1)
    json.dump(parse_timbres(ent(E_TIMBRES)), open(os.path.join(dst, 'adlib_timbres.json'), 'w'), indent=1)
    return out, trans, trows


def audition(argv):
    import argparse, wave
    ap = argparse.ArgumentParser()
    ap.add_argument('out')
    ap.add_argument('--flx', default=os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..',
                                                   'game', 'app', 'Bioforge', 'MUSIC', 'MUSIC.FLX'))
    ap.add_argument('--play', type=int)
    ap.add_argument('--switch', help='"0:10,20:35" = request song 10 at 0 s, song 35 at 20 s')
    ap.add_argument('--seconds', type=float, default=60)
    ap.add_argument('--adlib', action='store_true')
    a = ap.parse_args(argv)
    reqs = [(float(t), int(n)) for t, n in (x.split(':') for x in a.switch.split(','))] if a.switch else [(0.0, a.play)]
    import musicseq
    events, trace = musicseq.sequence(musicseq.Library(a.flx, adlib=a.adlib), reqs, a.seconds)
    for tr in trace: print(f'{tr[0]:8.3f} s', *tr[1:])
    if a.adlib:
        import adlib, wave
        pcm = adlib.render(adlib.register_writes(events, trace, a.seconds, adlib.Bank.load(a.flx)), a.seconds, 22050)
        with wave.open(a.out, 'wb') as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(22050); w.writeframes(pcm.tobytes())
    else:
        pcm = musicseq.render(events, a.seconds, out=a.out)
    x = pcm.astype(float)
    print(f'{a.out}: {len(pcm) / 22050:.1f} s, rms {np.sqrt((x ** 2).mean()):.0f} peak {np.abs(x).max():.0f}')


if __name__ == '__main__':
    if sys.argv[1].startswith('--'):
        audition(sys.argv[1:]); sys.exit()
    songs, trans, rows = export(sys.argv[1], sys.argv[2])
    secs = sorted([s['seconds'] for s in songs] + [t['seconds'] for t in trans])
    print(f"{len(songs)} songs, {len(trans)} transitions, {len(rows)} transition rows -> {sys.argv[2]}")
    print(f"duration s: min {secs[0]} median {secs[len(secs)//2]} max {secs[-1]}")
