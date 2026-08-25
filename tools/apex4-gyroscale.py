#!/usr/bin/env python3
"""Integrate gyro over each rotation burst; a known 360 deg turn gives the scale."""
import struct, sys


def load(path):
    out, blob, i = [], open(path, "rb").read(), 0
    while i + 9 <= len(blob):
        t, ln = struct.unpack_from("dB", blob, i); i += 9
        out.append((t, blob[i:i+ln])); i += ln
    return out


def s16v(v):
    return v - 65536 if v & 0x8000 else v


def s16(p, i):
    return s16v(p[i] | (p[i+1] << 8))


def s12(p):
    v = p[4] | ((p[5] & 0x0F) << 8)
    return v - 4096 if v & 0x800 else v


AXES = {
    "yaw_split[18|20]": lambda p: s16v(p[18] | (p[20] << 8)),
    "yaw_12b[4:5]": s12,
    "pitch[26:27]": lambda p: s16(p, 26),
    "roll[29:30]": lambda p: s16(p, 29),
}

rows = [(t, p) for t, p in load(sys.argv[1]) if len(p) >= 32 and p[0] == 4]
print("%d frames, %.1fs\n" % (len(rows), rows[-1][0]))

THR, GAP, MINLEN = 30, 1.0, 0.5
hot = [(t, p) for t, p in rows if max(abs(f(p)) for f in AXES.values()) > THR]
groups, cur = [], [hot[0]] if hot else []
for t, p in hot[1:]:
    if t - cur[-1][0] > GAP:
        groups.append(cur); cur = []
    cur.append((t, p))
if cur:
    groups.append(cur)
groups = [g for g in groups if g[-1][0] - g[0][0] >= MINLEN]

print("rotation bursts: %d" % len(groups))
for n, g in enumerate(groups, 1):
    dur = g[-1][0] - g[0][0]
    print("\nburst %d  t=%.1f  dur %.2fs  %d frames" % (n, g[0][0], dur, len(g)))
    for name, f in AXES.items():
        integral, peak, prev_t = 0.0, 0, g[0][0]
        for t, p in g:
            v = f(p)
            integral += v * (t - prev_t)
            prev_t = t
            peak = max(peak, abs(v))
        print("   %-18s integral %10.1f LSB*s   peak %6d   -> 360deg/int = %8.4f deg per LSB*s"
              % (name, integral, peak, (360.0 / integral) if abs(integral) > 1 else float("nan")))
