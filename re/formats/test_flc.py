"""FLC chunk coverage and ffmpeg parity: python -I -m unittest test_flc.py"""
import hashlib
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import flc


ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..')
SHOW = os.path.join(ROOT, 'game', 'app', 'Bioforge', 'SHOW')


def chunk(typ, payload):
    return struct.pack('<IH', len(payload) + 6, typ) + payload


def movie(width, height, chunks):
    frame = chunk(flc.FRAME, struct.pack('<H8x', len(chunks)) + b''.join(chunks))
    header = bytearray(128)
    struct.pack_into('<I6HI', header, 0, 128 + len(frame), flc.MAGIC, 1, width, height, 8, 0, 71)
    return bytes(header) + frame


def copy_frames(path):
    """Return frame numbers containing Animator's 63998-byte COPY chunk."""
    data = open(path, 'rb').read()
    off, number, found = 128, 0, []
    while off < len(data):
        size, typ = struct.unpack_from('<IH', data, off)
        if typ == flc.FRAME:
            pos = off + 16
            for _ in range(struct.unpack_from('<H', data, off + 6)[0]):
                chunk_size, chunk_type = struct.unpack_from('<IH', data, pos)
                if chunk_type == flc.COPY and chunk_size == 64004:
                    found.append(number)
                pos += chunk_size
            number += 1
        off += size
    return found


def repaired_copy_stream(path):
    """Make the game's short COPY payloads valid FLC for an ffmpeg oracle."""
    data = bytearray(open(path, 'rb').read())
    off = 128
    while off < len(data):
        size, typ = struct.unpack_from('<IH', data, off)
        if typ == flc.FRAME:
            pos = off + 16
            for _ in range(struct.unpack_from('<H', data, off + 6)[0]):
                chunk_size, chunk_type = struct.unpack_from('<IH', data, pos)
                if chunk_type == flc.COPY and chunk_size == 64004:
                    struct.pack_into('<I', data, pos, 64006)
                    data[pos + 64004:pos + 64006] = b'\0\0'
                pos += chunk_size
        off += size
    return bytes(data)


class Chunks(unittest.TestCase):
    def test_palette_brun_black_and_copy(self):
        color256 = struct.pack('<HBB', 1, 1, 2) + bytes([1, 2, 3, 4, 5, 6])
        brun = bytes([2, 2, 7, 2, 8, 2, 2, 9, 2, 10])
        frames = list(flc.Flic(movie(4, 2, [chunk(flc.COLOR_256, color256), chunk(flc.BRUN, brun)])).frames())
        self.assertEqual(frames[0].pixels, bytes([7, 7, 8, 8, 9, 9, 10, 10]))
        self.assertEqual(frames[0].palette[3:9], bytes([1, 2, 3, 4, 5, 6]))

        # Packet skips are relative to the palette cursor after the previous
        # packet, rather than absolute indices.
        packets = struct.pack('<HBB', 2, 1, 2) + bytes([1, 2, 3, 4, 5, 6]) + struct.pack('<BB', 2, 1) + bytes([7, 8, 9])
        frame = next(flc.Flic(movie(1, 1, [chunk(flc.COLOR_256, packets), chunk(flc.COPY, b'\0')])).frames())
        self.assertEqual(frame.palette[3:9], bytes([1, 2, 3, 4, 5, 6]))
        self.assertEqual(frame.palette[15:18], bytes([7, 8, 9]))

        raw = movie(4, 2, [chunk(flc.COPY, bytes(range(6))), chunk(flc.BLACK, b'')])
        self.assertEqual(list(flc.Flic(raw).frames())[0].pixels, b'\0' * 8)

    def test_color64_lc_and_delta(self):
        color64 = struct.pack('<HBB', 1, 0, 1) + bytes([63, 32, 1])
        # First row: skip 1, literal 2; second row: skip 2, run 2.
        lc = struct.pack('<HH', 0, 2) + bytes([1, 1, 2, 4, 5, 1, 2, -2 & 255, 9])
        # Skip the first line.  On line 2 set its last pixel through SS2's
        # 0x8000 control word, then write a repeated two-byte word.
        delta = struct.pack('<H', 1) + struct.pack('<H', 0xffff) + struct.pack('<H', 0x800c) + struct.pack('<H', 1) + bytes([0, -1 & 255, 6, 7])
        data = movie(4, 2, [chunk(flc.COLOR_64, color64), chunk(flc.LC, lc)])
        data += chunk(flc.FRAME, struct.pack('<H8x', 1) + chunk(flc.DELTA_FLC, delta))
        # Correct the container length after appending the second frame.
        data = bytearray(data); struct.pack_into('<I', data, 0, len(data)); data = bytes(data)
        frames = list(flc.Flic(data).frames())
        self.assertEqual(frames[0].palette[:3], bytes([255, 130, 4]))
        self.assertEqual(frames[0].pixels, bytes([0, 4, 5, 0, 0, 0, 9, 9]))
        self.assertEqual(frames[1].pixels, bytes([0, 4, 5, 0, 6, 7, 9, 12]))


@unittest.skipUnless(os.path.isdir(SHOW), 'game data is unavailable')
class GameMovies(unittest.TestCase):
    def test_all_show_files_decode(self):
        for name in ('INTRO', 'INTROF', 'INTROG', 'ENDGAME', 'DEMO1', 'PLT0'):
            anim = flc.load(os.path.join(SHOW, name + '.SHO'))
            frames = list(anim.frames())
            self.assertEqual((anim.width, anim.height), (320, 200))
            self.assertGreater(anim.speed, 0)
            self.assertGreaterEqual(len(frames), anim.frame_count)
            self.assertEqual(len(frames[-1].pixels), 64000)
        # FLC headers omit the physical ring frame.  Python exposes every
        # frame chunk for format inspection; the player may stop at header N.
        plt0 = flc.load(os.path.join(SHOW, 'PLT0.SHO'))
        self.assertEqual((plt0.frame_count, len(list(plt0.frames()))), (48, 49))

    def test_short_copy_frames_are_zero_padded(self):
        self.assertEqual(copy_frames(os.path.join(SHOW, 'INTRO.SHO')), [1229])
        self.assertEqual(copy_frames(os.path.join(SHOW, 'INTROF.SHO')), [1229])
        self.assertEqual(copy_frames(os.path.join(SHOW, 'INTROG.SHO')), [1229])
        self.assertEqual(copy_frames(os.path.join(SHOW, 'ENDGAME.SHO')), [38, 273, 526])
        self.assertEqual(copy_frames(os.path.join(SHOW, 'PLT0.SHO')), [43, 44, 45, 46, 47])
        self.assertEqual(copy_frames(os.path.join(SHOW, 'DEMO1.SHO')), [])

    @unittest.skipUnless(shutil.which('ffmpeg'), 'ffmpeg is unavailable')
    def test_first_frame_hashes_match_original_ffmpeg(self):
        """The leading BRUN frames are valid on disk, before any short COPY."""
        for name in ('INTRO', 'INTROF', 'INTROG', 'ENDGAME', 'DEMO1', 'PLT0'):
            path = os.path.join(SHOW, name + '.SHO')
            frame = next(flc.load(path).frames())
            got = subprocess.run(['ffmpeg', '-v', 'error', '-f', 'flic', '-i', path,
                                  '-frames:v', '1', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'],
                                 check=True, stdout=subprocess.PIPE).stdout
            self.assertEqual(hashlib.sha256(frame.rgb()).hexdigest(), hashlib.sha256(got).hexdigest(), name)

    @unittest.skipUnless(shutil.which('ffmpeg'), 'ffmpeg is unavailable')
    def test_rgb_hashes_match_ffmpeg(self):
        # The first and final frame of every movie compare with ffmpeg while
        # keeping its output small.  Animator's short
        # COPY chunks are normalized to zero-padded FLC first: stock ffmpeg
        # rejects the original 63998-byte chunks rather than padding them.
        for name in ('INTRO', 'INTROF', 'INTROG', 'ENDGAME', 'DEMO1', 'PLT0'):
            path = os.path.join(SHOW, name + '.SHO')
            frames = list(flc.load(path).frames())
            wanted = sorted({0, len(frames) - 1})
            expr = '+'.join(f'eq(n\\,{n})' for n in wanted)
            with tempfile.NamedTemporaryFile(suffix='.flc') as fixed:
                fixed.write(repaired_copy_stream(path)); fixed.flush()
                got = subprocess.run(['ffmpeg', '-v', 'error', '-f', 'flic', '-i', fixed.name,
                                  '-vf', 'select=' + expr, '-fps_mode', 'passthrough', '-f', 'rawvideo',
                                  '-pix_fmt', 'rgb24', '-'], check=True, stdout=subprocess.PIPE).stdout
            reference = [got[i * 192000:(i + 1) * 192000] for i in range(len(wanted))]
            self.assertEqual(len(reference), len(wanted))
            self.assertEqual([hashlib.sha256(frames[i].rgb()).hexdigest() for i in wanted],
                             [hashlib.sha256(image).hexdigest() for image in reference], name)


if __name__ == '__main__':
    unittest.main()
