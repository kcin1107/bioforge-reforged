"""Indexed 2x filter for the High-Resolution Art pack: an AI upscale used only as a guide, so the art stays palette indices.

The rule every output pixel obeys: it is one of the colours in the 3x3 neighbourhood of its source pixel.
Bake-off against Scale2x and MMPX: NOTES "High-resolution art".
"""
import numpy as np


def canon(palette):
    """index -> first index with the same RGB, so duplicate palette entries compare equal (palette: 256x3)."""
    seen, out = {}, np.zeros(256, np.int32)
    for i, c in enumerate(map(tuple, palette.tolist())):
        out[i] = seen.setdefault(c, i)
    return out


def nearest2x(a, factor=2):
    return a.repeat(factor, 0).repeat(factor, 1)


def constrain(src, guide, palette, solid=None, factor=2):
    """src: HxW palette indices; guide: (factor*H)x(factor*W) RGB (the model's picture); solid: HxW, False where src is empty (its value is
    never used). Each of a pixel's factor^2 new pixels takes the neighbourhood colour closest to the guide; at least half keep the source
    colour, the rest going back to it in order of least gain. Ties go to the lowest index."""
    f, F = factor, factor * factor
    h, w = src.shape
    src = src.astype(np.int64)
    if solid is None: solid = np.ones((h, w), bool)
    c = canon(palette)
    P = palette.astype(np.int64)
    g = np.pad(np.where(solid, src, -1), 1, 'edge')
    n = np.stack([g[dy:dy + h, dx:dx + w] for dy in range(3) for dx in range(3)], -1)
    n = np.where(n < 0, src[..., None], n)
    n.sort(-1)                                                   # ties: lowest index, as np.unique would order them
    v = guide.astype(np.int64).reshape(h, f, w, f, 3).transpose(0, 2, 1, 3, 4).reshape(h, w, F, 3)
    d = ((P[n][:, :, None] - v[:, :, :, None]) ** 2).sum(-1)     # h, w, F sub-pixels, 9 candidates
    k = d.argmin(-1)
    pick = np.take_along_axis(n, k, -1)
    keep = c[pick] == c[src][..., None]
    gain = ((P[src][:, :, None] - v) ** 2).sum(-1) - np.take_along_axis(d, k[..., None], -1)[..., 0]
    gain = np.where(keep, -1, gain)
    rank = gain.argsort(-1, kind='stable').argsort(-1, kind='stable')
    pick = np.where(rank < F // 2, src[..., None], pick)
    return pick.reshape(h, w, f, f).transpose(0, 2, 1, 3).reshape(f * h, f * w)


def rule3_violations(src, up, factor=2):
    """Output pixels whose value is not in the 3x3 neighbourhood of their source pixel."""
    f = factor
    g = np.pad(src, 1, 'edge')
    bad = 0
    for y in range(src.shape[0]):
        for x in range(src.shape[1]):
            n = set(g[y:y + 3, x:x + 3].ravel().tolist())
            bad += sum(v not in n for v in up[f * y:f * y + f, f * x:f * x + f].ravel().tolist())
    return bad
