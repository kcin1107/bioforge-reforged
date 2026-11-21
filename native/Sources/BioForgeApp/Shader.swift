// Metal shader source, compiled at runtime (MTLDevice.makeLibrary(source:)) to avoid a build phase.
// The fragment shader looks the r8Uint index texture up in a 256-entry RGBA palette buffer, with crisp edges at any scale.
let shaderSource = """
#include <metal_stdlib>
using namespace metal;

struct VOut { float4 position [[position]]; float2 uv; };

// Fullscreen quad from 4 vertices (triangle strip); `rect` = x0,y0,x1,y1 in clip space.
vertex VOut vs(uint vid [[vertex_id]], constant float4 &rect [[buffer(0)]]) {
    float2 c = float2(vid & 1, vid >> 1);
    VOut o;
    o.position = float4(mix(rect.xy, rect.zw, c), 0, 1);
    o.uv = float2(c.x, 1 - c.y);
    return o;
}

// Sharp bilinear on palette indices: inside a texel the screen pixel takes its colour; only a screen pixel that straddles two texels
// blends their palette colours, by coverage, so pixels stay crisp at any (fractional) scale. `ratio` = screen pixels per texel (x, y).
fragment float4 fs(VOut in [[stage_in]], texture2d<uint> indices [[texture(0)]],
                   constant float4 *palette [[buffer(0)]], constant float2 &ratio [[buffer(1)]]) {
    float2 size = float2(indices.get_width(), indices.get_height());
    float2 t = in.uv * size - 0.5, i = floor(t);
    float2 f = clamp((t - i - 0.5) * max(ratio, 1.0) + 0.5, 0.0, 1.0);
    int2 a = int2(i), hi = int2(size) - 1;
    uint2 p0 = uint2(clamp(a, 0, hi)), p1 = uint2(clamp(a + 1, 0, hi));
    float4 c00 = palette[indices.read(p0).r], c10 = palette[indices.read(uint2(p1.x, p0.y)).r];
    float4 c01 = palette[indices.read(uint2(p0.x, p1.y)).r], c11 = palette[indices.read(p1).r];
    return mix(mix(c00, c10, f.x), mix(c01, c11, f.x), f.y);
}
"""

