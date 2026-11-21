"""Render a script block to an animated GIF through the engine binding (world.py).

    re/.venv/bin/python -I re/interp/movie.py LEVEL BLOCK OUT.gif [--ticks N] [--every K] [--camera CAM]
                                                                  [--set VAR=VAL ...] [--no-auto-camera] [--no-subtitles] [--audio OUT.wav]
Writes OUT.gif (2x upscale) and OUT_sheet.png (8 evenly spaced frames labelled with tick and camera).
--audio mixes the logged SOUND/SUBTITLE events into a 22050 Hz mono 16-bit WAV aligned to the 30 Hz ticks, and the
MUSIC requests (music sequencer + Apple GM synth, re/tools/midi2wav.swift) underneath; --no-music skips the music.
--music-device adlib|gm picks the arrangement and synth (default: INSTALL.OPT's MusicCardId, settings.music_device; MUSIC=OFF
there means no music): adlib renders the AdLib arrangement through the port of the game's AdLib driver (re/formats/adlib.py) and
the OPL2 model (native OPL2.swift via re/tools/opl2wav.swift).
Active subtitles are drawn onto every frame (subtitles.py); --no-subtitles leaves them out.
"""
import argparse
import os
import sys
import wave

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'formats'))
import vm as vmmod  # noqa: E402
import world as worldmod  # noqa: E402
import subtitles  # noqa: E402
import settings as settingsmod  # noqa: E402
from cam import palette  # noqa: E402
from flex import read_flex  # noqa: E402


AUDIO_RATE = 22050
MUSIC_GAIN = 0.5      # preview choice (not recovered from the engine): music at 0.5, effects at 1.0, then clipped
MUSIC_FLX = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'game', 'app', 'Bioforge', 'MUSIC', 'MUSIC.FLX')


_pals = {}


def room_palette(cam):
    """256 x 3 RGB palette of ROOMS/<cam>.CAM (entry 0), or None without room art."""
    if cam not in _pals:
        path = os.path.join(worldmod.ROOMS, str(cam).upper() + '.CAM')
        if cam is None or not os.path.exists(path):
            _pals[cam] = None
        else:
            d, ents = read_flex(path)
            _pals[cam] = np.frombuffer(palette(d[ents[0][1]:ents[0][1] + 768]), np.uint8).reshape(256, 3)
    return _pals[cam]


def music_audio(world, end_tick, device='gm'):
    """world.music_log -> mono float array at AUDIO_RATE; None if there is no music or the renderer fails. device: 'gm'
    (first arrangement, Apple's GM synth) or 'adlib' (AdLib arrangement, driver port + OPL2)."""
    import musicseq
    if not world.music_log or device is None:
        return None
    end = end_tick / vmmod.TPS
    try:
        lib = musicseq.Library(MUSIC_FLX, adlib=device == 'adlib')
        events, trace = musicseq.sequence(lib, [(t / vmmod.TPS, n) for t, n in world.music_log], end,
                                      volume=world.music_initial, volumes=[(t / vmmod.TPS, m) for t, m in world.music_vol_log])
        if device == 'adlib':
            import adlib
            return adlib.render(adlib.register_writes(events, trace, end, adlib.Bank.load(MUSIC_FLX)), end, AUDIO_RATE).astype(np.float64)
        return musicseq.render(events, end, AUDIO_RATE).astype(np.float64).mean(axis=1)
    except Exception as e:                       # Swift toolchain missing / AU failure: keep the sound effects
        print(f'warning: music not rendered ({e})')
        return None


def mix_audio(world, end_tick):
    """Mix world.sound_log into int16 mono at AUDIO_RATE: resampled by rate - pitch (linear interpolation),
    scaled by volume / 255, clipped. A positional sound's volume follows world.sound_volumes, piecewise
    constant with a one-tick (1/30 s) linear ramp into each change; of several changes in one tick the last counts. A looped sample (SOUND only) repeats loop_start..loop_end until its
    STOPSOUND or the end; from its STOPAMBIENT on it plays on to the end of the sample without wrapping. ASSUMPTION: a looped sample played by SUBTITLE would loop too (not seen in practice).
    The volume of every voice start and positional change goes through the master-volume table of the effect level in force at
    that tick (world.sfx_log; settings.master_table: FUN_1028_1da5, applied where the engine hands the volume to the driver). A voice with a
    volume log that starts later than the voice (SETVOLUME / a ramp on a non-positional handle) plays at its start volume until then.
    world.sound_rates (SETPITCH / ADDTOPITCH / the pitch ramp) change the resampling step from the tick of each entry on: the source
    position stays continuous, the step is rate / AUDIO_RATE (rate 0 holds the position)."""
    sm, _ = worldmod.sound_bank(world.settings.language)
    n_out = int(np.ceil(end_tick / vmmod.TPS * AUDIO_RATE))
    mix = np.zeros(n_out, np.float64)
    stops = {h: t for t, h in world.sound_stops}
    releases = {h: t for t, h in world.sound_releases}
    tables = {}

    def master(tick, volume):
        sfx = world.sfx_log[0][1]
        for t, level in world.sfx_log:
            if t <= tick:
                sfx = level
        if sfx not in tables:
            tables[sfx] = settingsmod.master_table(sfx)
        return tables[sfx][max(0, min(255, volume))]

    vols, rates, last = {}, {}, {}
    starts = {handle: (tick, volume) for tick, _, _, volume, _, handle in world.sound_log}
    for t, h, r in world.sound_rates:
        rates.setdefault(h, []).append((t, r))
    for t, h, v in world.sound_volumes:
        pts = vols.setdefault(h, [])
        if pts and last[h] == t:                           # several entries in one tick: the last one counts
            pts[-1] = (t / vmmod.TPS, master(t, v))
            continue
        last[h] = t
        if not pts and h in starts and starts[h][0] < t:
            pts.append((starts[h][0] / vmmod.TPS, master(*starts[h])))
        if pts:                                            # hold the previous value until one tick before, then ramp
            pts.append((max(t - 1, 0) / vmmod.TPS, pts[-1][1]))
        pts.append((t / vmmod.TPS, master(t, v)))
    for tick, idx, _, volume, pitch, handle in world.sound_log:
        s = sm.get(idx)
        start = int(round(tick / vmmod.TPS * AUDIO_RATE))
        end = min(n_out, int(round(stops[handle] / vmmod.TPS * AUDIO_RATE)) if handle in stops else n_out)
        if start >= end or len(s.pcm) < 2:
            continue
        idx = np.arange(end - start)
        step = max(s.rate - pitch, 1) / AUDIO_RATE
        pos = idx * step
        base, at = 0.0, 0                                  # the piecewise position: base + (i - at) * step per segment
        for t, r in rates.get(handle, ()):
            f = int(round(t / vmmod.TPS * AUDIO_RATE)) - start
            if f >= len(idx):
                break
            base = base + (f - at) * step
            at, step = f, r / AUDIO_RATE
            pos[f:] = base + (idx[f:] - f) * step
        n = len(s.pcm)
        raw = pos.copy()
        if s.loop_end > s.loop_start and handle in world.sound_loops:
            pos = np.where(pos >= s.loop_end, s.loop_start + (pos - s.loop_start) % (s.loop_end - s.loop_start), pos)
            f = int(round(releases[handle] / vmmod.TPS * AUDIO_RATE)) - start if handle in releases else len(pos)
            if f < len(pos):                               # STOPAMBIENT: from the wrapped position on to the sample's end, no wrap
                pos[f:] = pos[f] + (raw[f:] - raw[f])
                pos = pos[pos <= n - 1]
        else:
            pos = pos[pos <= n - 1]
        gain = master(tick, volume) / 255
        if handle in vols:
            tv = np.array(vols[handle], float)
            gain = np.interp((start + np.arange(len(pos))) / AUDIO_RATE, tv[:, 0], tv[:, 1]) / 255
        mix[start:start + len(pos)] += np.interp(pos, np.arange(n), s.pcm.astype(np.float64)) * 256 * gain
    return np.clip(np.round(mix), -32768, 32767).astype(np.int16)


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument('args', nargs='+', metavar='LEVEL BLOCK OUT | OUT (with --boot)')
    ap.add_argument('--boot', action='store_true',
                    help='new game: load TITLE from INITGAME, run block GAME (START.scr), follow LOADLEVEL')
    ap.add_argument('--ticks', type=int, default=300)
    ap.add_argument('--every', type=int, default=2)
    ap.add_argument('--camera', default=None, help='camera used until the script issues CAMERA')
    ap.add_argument('--no-auto-camera', action='store_true', help='disable camera switching by CAM_ trigger boxes')
    ap.add_argument('--audio', default=None, metavar='OUT.wav', help='also write the mixed sound events as a WAV')
    ap.add_argument('--no-subtitles', action='store_true', help='do not draw the subtitles onto the frames')
    ap.add_argument('--no-music', action='store_true', help='with --audio: leave the music out')
    ap.add_argument('--music-device', choices=('gm', 'adlib'), default=None,
                    help="with --audio: music arrangement and synth (default: INSTALL.OPT's MusicCardId)")
    ap.add_argument('--set', nargs='*', default=[], metavar='VAR=VAL')
    a = ap.parse_args(argv[1:])
    if a.boot:
        if len(a.args) != 1:
            sys.exit('--boot takes only OUT')
        a.level, a.block, a.out = 'TITLE', 'GAME', a.args[0]
    elif len(a.args) != 3:
        sys.exit('usage: movie.py LEVEL BLOCK OUT (or --boot OUT)')
    else:
        a.level, a.block, a.out = a.args
    world = worldmod.World(a.level, a.camera, worldmod.INITGAME if a.boot else worldmod.GAMEDAT)
    world.auto_camera = not a.no_auto_camera
    vm = vmmod.VM(world)
    files = vmmod.load_level(vm, a.level)
    print(f'level {a.level.upper()}: {len(files)} scripts, {len(vm.blocks)} blocks')
    for kv in a.set:
        k, v = kv.split('=', 1)
        k = k.lower() if k.startswith('_') else '_' + k.lower()
        v = v.strip()
        vm.globals[k] = vm.defs.consts.get(v.lower(), None) if v.startswith('_') else int(v)
        if vm.globals[k] is None:
            sys.exit(f'unknown constant {v}')
    if a.block.upper() not in vm.blocks:
        sys.exit(f'block {a.block} not found in level {a.level}')
    if a.boot:
        world.fire_event('TITLE_LOAD')
    vm.fire(a.block, 'global' if a.boot else 'level')
    frames = []                                            # (tick, camera, image)
    cap_font = None if a.no_subtitles else subtitles.load_font()
    for _ in range(a.ticks):
        vm.tick_once()
        world.step()
        if a.boot:
            world.choose_default_difficulty()
        t = vm.tick - 1
        if t % a.every == 0:
            img, cam = world.render(), world.current_camera()
            sub = None if a.no_subtitles else world.active_subtitle(t)
            if sub and room_palette(cam) is not None:
                img = subtitles.draw_on_rgb(img.copy(), sub[1], sub[0], cap_font, room_palette(cam))
            frames.append((t, cam, Image.fromarray(img)))
        if t % 30 == 0:
            print(f'tick {t:4d} {world.level} cam {world.current_camera()}: ' + '; '.join(
                f'{f.name} ' + ('unplaced' if f.pos is None else
                                f'({f.pos[0]:.0f},{f.pos[1]:.0f},{f.pos[2]:.0f}) h={f.heading:.0f} '
                                f'{f.motion}[{f.idx}]{" go" if f.is_moving() else ""}')
                for f in world.figures.values()))
    dur = int(round(1000 * a.every / vmmod.TPS / 10)) * 10
    big = [im.resize((640, 400), Image.NEAREST) for _, _, im in frames]
    big[0].save(a.out, save_all=True, append_images=big[1:], duration=dur, loop=0)
    n = min(8, len(frames))
    pick = [frames[round(i * (len(frames) - 1) / max(n - 1, 1))] for i in range(n)]
    sheet = Image.new('RGB', (320 * 4, 200 * ((n + 3) // 4)))
    for i, (t, cam, im) in enumerate(pick):
        im = im.copy()
        d = ImageDraw.Draw(im)
        d.rectangle((0, 0, 110, 11), fill=(0, 0, 0))
        d.text((2, 0), f'tick {t} cam {cam}', fill=(255, 255, 255))
        sheet.paste(im, (320 * (i % 4), 200 * (i // 4)))
    base = os.path.splitext(a.out)[0]
    sheet.save(base + '_sheet.png')
    print(f'wrote {a.out} ({len(frames)} frames, {dur} ms each) and {base}_sheet.png')
    if a.audio:
        pcm = mix_audio(world, vm.tick)
        device = a.music_device or settingsmod.Settings.load().music_device
        music = None if a.no_music else music_audio(world, vm.tick, device)
        if music is not None:
            n = min(len(pcm), len(music))
            mixed = pcm.astype(np.float64)
            mixed[:n] += music[:n] * MUSIC_GAIN
            pcm = np.clip(np.round(mixed), -32768, 32767).astype(np.int16)
        with wave.open(a.audio, 'wb') as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(AUDIO_RATE)
            w.writeframes(pcm.tobytes())
        print(f'wrote {a.audio}: {len(world.sound_log)} sound events, {len(pcm) / AUDIO_RATE:.2f} s')
        for t, idx, name, vol, pitch, h in world.sound_log:
            print(f'  tick {t:4d} #{idx} {name} vol {vol} pitch {pitch} handle {h}')
        print('  music (tick, arg): ' + ', '.join(f'{t}:{m}' for t, m in world.music_log))
    print('--- engine log summary')
    counts = {}
    for _, _, kind, name, _ in world.log:
        counts[(kind, name)] = counts.get((kind, name), 0) + 1
    print(', '.join(f'{n}x{c}' for (k, n), c in sorted(counts.items())))
    print('--- level loads (tick, level, arrival, player position)')
    for t, lvl, arr, pos in world.level_loads:
        print(f'  {t:4d}  {lvl} {arr} {None if pos is None else pos.round().astype(int).tolist()}')
    print('--- engine-fired blocks (tick, block): ' + ', '.join(f'{t}:{b}' for t, b in world.events))
    print('--- camera changes (tick, from, to, reason)')
    for ch in world.camera_changes:
        print('  %4d  %s -> %s  (%s)' % ch)
    for w in world.warnings + vm.warnings:
        print('warning:', w)


if __name__ == '__main__':
    main(sys.argv)
