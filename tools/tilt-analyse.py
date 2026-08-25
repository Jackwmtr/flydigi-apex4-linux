#!/usr/bin/env python3
"""Find the extremes of pad-frame accel Y in a capture, with their neighbours.

No stillness requirement: a held tilt is simply where |Y| peaks, and averaging a
window around the peak is enough to read its sign and size.
"""
import struct, sys


def load(path):
    out, blob, i = [], open(path, "rb").read(), 0
    while i + 9 <= len(blob):
        t, ln = struct.unpack_from("dB", blob, i); i += 9
        out.append((t, blob[i:i+ln])); i += ln
    return out


rows = [(t, p) for t, p in load(sys.argv[1]) if len(p) >= 32 and p[0] == 4]
vals = [(t,) + struct.unpack_from("<3h", p, 11) for t, p in rows]
print("%d frames, %.1fs" % (len(vals), vals[-1][0]))

# strongest positive and negative Y, each averaged over a +-0.4s window
for label, pick in (("max +Y", max), ("min -Y", min)):
    t0 = pick(vals, key=lambda v: v[2])[0]
    win = [v for v in vals if abs(v[0] - t0) < 0.4]
    n = len(win)
    mx, my, mz = (sum(v[i] for v in win) / n for i in (1, 2, 3))
    print("%s at t=%6.1f  X %+6.0f  Y %+6.0f  Z %+6.0f   |a| %5.0f  (%d frames)"
          % (label, t0, mx, my, mz, (mx*mx + my*my + mz*mz) ** 0.5, n))

# and a coarse timeline so a held pose is visible as a plateau
print("\ntimeline (1s means):")
t = 0.0
while t < vals[-1][0]:
    win = [v for v in vals if t <= v[0] < t + 1.0]
    if win:
        n = len(win)
        mx, my, mz = (sum(v[i] for v in win) / n for i in (1, 2, 3))
        mag = (mx*mx + my*my + mz*mz) ** 0.5
        if mag > 400:
            print("  t=%4.0f  X %+6.0f  Y %+6.0f  Z %+6.0f  |a| %5.0f" % (t, mx, my, mz, mag))
    t += 1.0
