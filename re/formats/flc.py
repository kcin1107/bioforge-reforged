"""Autodesk FLI/FLC animation decoder used by BioForge's ``SHOW/*.SHO`` files.

``load(path)`` returns a :class:`Flic`.  Iterate ``Flic.frames()`` to receive
indexed :class:`Frame` objects; each frame retains the palette active when it
was displayed.  Palette entries and :meth:`Frame.rgb` use ordinary 8-bit RGB.
"""
import struct
from dataclasses import dataclass


MAGIC = 0xAF12
FRAME = 0xF1FA
PREFIX = 0xF100
COLOR_256 = 4
DELTA_FLC = 7
COLOR_64 = 11
LC = 12
BLACK = 13
BRUN = 15
COPY = 16
PSTAMP = 18


@dataclass(frozen=True)
class Frame:
    """One decoded indexed frame and its 256-entry RGB palette."""
    pixels: bytes
    palette: bytes

    def rgb(self):
        """Return this frame expanded to packed RGB24 bytes."""
        return b''.join(self.palette[i * 3:i * 3 + 3] for i in self.pixels)


class Flic:
    """A parsed FLI/FLC stream.  ``speed`` is the header delay in milliseconds."""
    def __init__(self, data):
        if len(data) < 128:
            raise ValueError('FLC header is truncated')
        size, magic, self.frame_count, self.width, self.height, depth, _flags, self.speed = struct.unpack_from('<I6HI', data)
        if magic != MAGIC or depth != 8:
            raise ValueError('not an 8-bit FLC stream')
        if size > len(data):
            raise ValueError('FLC stream is truncated')
        self.data = memoryview(data)[:size]

    def frames(self):
        """Yield every physical frame chunk, including empty and ring frames."""
        pixels = bytearray(self.width * self.height)
        palette = bytearray(768)
        off = 128
        while off < len(self.data):
            size, typ = _chunk_header(self.data, off, len(self.data))
            end = off + size
            if typ == PREFIX or typ == PSTAMP:
                pass                         # Animator metadata / thumbnail only
            elif typ == FRAME:
                if size < 16:
                    raise ValueError('truncated FLC frame header')
                count, = struct.unpack_from('<H', self.data, off + 6)
                pos = off + 16
                for _ in range(count):
                    chunk_size, chunk_type = _chunk_header(self.data, pos, end)
                    payload = self.data[pos + 6:pos + chunk_size]
                    _apply(chunk_type, payload, pixels, palette, self.width, self.height)
                    pos += chunk_size
                # Animator leaves two bytes after each short COPY chunk.  They
                # are not pixels: use the documented zero padding instead.
                if pos != end and (end - pos != 2 or not count):
                    raise ValueError('FLC frame chunk sizes do not add up')
                yield Frame(bytes(pixels), bytes(palette))
            off = end


def load(path):
    """Read an Autodesk FLI/FLC animation from *path*."""
    with open(path, 'rb') as f:
        return Flic(f.read())


def _chunk_header(data, off, end):
    if off + 6 > end:
        raise ValueError('truncated FLC chunk header')
    size, typ = struct.unpack_from('<IH', data, off)
    if size < 6 or off + size > end:
        raise ValueError('invalid FLC chunk size')
    return size, typ


def _apply(typ, data, pixels, palette, width, height):
    if typ == COLOR_256:
        _color(data, palette, False)
    elif typ == COLOR_64:
        _color(data, palette, True)
    elif typ == BRUN:
        _brun(data, pixels, width, height)
    elif typ == DELTA_FLC:
        _delta(data, pixels, width, height)
    elif typ == LC:
        _lc(data, pixels, width, height)
    elif typ == BLACK:
        pixels[:] = b'\0' * len(pixels)
    elif typ == COPY:
        # BioForge's Animator writes two bytes less than a full 320x200 frame.
        # The original player (and ffmpeg) leave those final pixels black.
        pixels[:] = bytes(data[:len(pixels)]) + b'\0' * max(0, len(pixels) - len(data))
    elif typ != PSTAMP:
        raise ValueError(f'unsupported FLC chunk {typ:#x}')


def _color(data, palette, six_bit):
    if len(data) < 2:
        raise ValueError('truncated FLC palette chunk')
    packets, = struct.unpack_from('<H', data)
    pos = 2
    index = 0
    for _ in range(packets):
        if pos + 2 > len(data):
            raise ValueError('truncated FLC palette packet')
        index += data[pos]
        count = data[pos + 1] or 256
        pos += 2
        if index + count > 256 or pos + 3 * count > len(data):
            raise ValueError('invalid FLC palette packet')
        colors = data[pos:pos + 3 * count]
        if six_bit:
            colors = bytes((value << 2) | (value >> 4) for value in colors)
        palette[index * 3:(index + count) * 3] = colors
        pos += 3 * count
        index += count


def _brun(data, pixels, width, height):
    pos = 0
    for y in range(height):
        if pos >= len(data):
            raise ValueError('truncated FLC BRUN row')
        pos += 1                              # packet count is unreliable; consume to row width
        x = 0
        while x < width:
            if pos >= len(data):
                raise ValueError('truncated FLC BRUN packet')
            count = struct.unpack_from('<b', data, pos)[0]
            pos += 1
            n = abs(count)
            if n == 0 or x + n > width:
                raise ValueError('invalid FLC BRUN packet')
            dst = y * width + x
            if count > 0:
                if pos >= len(data):
                    raise ValueError('truncated FLC BRUN run')
                pixels[dst:dst + n] = bytes([data[pos]]) * n
                pos += 1
            else:
                if pos + n > len(data):
                    raise ValueError('truncated FLC BRUN literal')
                pixels[dst:dst + n] = data[pos:pos + n]
                pos += n
            x += n


def _delta(data, pixels, width, height):
    if len(data) < 2:
        raise ValueError('truncated FLC delta chunk')
    lines, = struct.unpack_from('<H', data)
    pos = 2
    y = 0
    remaining = lines
    while remaining:
        if pos + 2 > len(data):
            raise ValueError('truncated FLC delta control word')
        packets, = struct.unpack_from('<H', data, pos)
        pos += 2
        if packets & 0xC000 == 0xC000:
            y += 0x10000 - packets
            continue
        if packets & 0x8000:
            if y >= height:
                raise ValueError('FLC delta writes beyond image')
            pixels[(y + 1) * width - 1] = packets & 0xff
            continue
        if y >= height:
            raise ValueError('FLC delta writes beyond image')
        x = 0
        for _ in range(packets):
            if pos + 2 > len(data):
                raise ValueError('truncated FLC delta packet')
            x += data[pos]
            count = struct.unpack_from('<b', data, pos + 1)[0]
            pos += 2
            n = abs(count) * 2
            if n == 0 or x + n > width:
                raise ValueError('invalid FLC delta packet')
            dst = y * width + x
            if count < 0:
                if pos + 2 > len(data):
                    raise ValueError('truncated FLC delta run')
                pixels[dst:dst + n] = bytes(data[pos:pos + 2]) * (-count)
                pos += 2
            else:
                if pos + n > len(data):
                    raise ValueError('truncated FLC delta literal')
                pixels[dst:dst + n] = data[pos:pos + n]
                pos += n
            x += n
        y += 1
        remaining -= 1


def _lc(data, pixels, width, height):
    if len(data) < 4:
        raise ValueError('truncated FLC LC chunk')
    y, lines = struct.unpack_from('<HH', data)
    pos = 4
    if y + lines > height:
        raise ValueError('FLC LC writes beyond image')
    for _ in range(lines):
        if pos >= len(data):
            raise ValueError('truncated FLC LC row')
        packets = data[pos]
        pos += 1
        x = 0
        for _ in range(packets):
            if pos + 2 > len(data):
                raise ValueError('truncated FLC LC packet')
            x += data[pos]
            count = struct.unpack_from('<b', data, pos + 1)[0]
            pos += 2
            n = abs(count)
            if n == 0 or x + n > width:
                raise ValueError('invalid FLC LC packet')
            dst = y * width + x
            if count < 0:
                if pos >= len(data):
                    raise ValueError('truncated FLC LC run')
                pixels[dst:dst + n] = bytes([data[pos]]) * n
                pos += 1
            else:
                if pos + n > len(data):
                    raise ValueError('truncated FLC LC literal')
                pixels[dst:dst + n] = data[pos:pos + n]
                pos += n
            x += n
        y += 1
