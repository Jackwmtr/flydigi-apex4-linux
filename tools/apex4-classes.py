#!/usr/bin/env python3
"""Classify frames in the vendor stream, then show per-class spans per window."""
import struct, sys
from collections import Counter


def load(path):
    out, blob, i = [], open(path, "rb").read(), 0
    while i + 9 <= len(blob):
        t, ln = struct.unpack_from("dB", blob, i)
        i += 9
        out.append((t, blob[i:i + ln]))
        i += ln
    return out


def s16(p, i):
    v = p[i] | (p[i + 1] << 8)
    return v - 65536 if v & 0x8000 else v


rows = [(t, p) for t, p in load(sys.argv[1]) if len(p) >= 32]
print("total frames: %d" % len(rows))
for name, key in (("p[0]", 0), ("p[1]", 1), ("p[2]", 2), ("p[15]", 15), ("p[31]", 31)):
    c = Counter(p[key] for _, p in rows)
    print("  %-6s %s" % (name, ", ".join("0x%02x:%d" % kv for kv in c.most_common(8))))

sig = Counter((p[1], p[2]) for _, p in rows)
print("\ntop (p[1],p[2]) signatures:")
for (a, b), n in sig.most_common(8):
    print("  p1=0x%02x p2=0x%02x  %d frames" % (a, b, n))

main_sig = sig.most_common(1)[0][0]
print("\n=== windows, frames with p1=0x%02x p2=0x%02x only" % main_sig)
for spec in sys.argv[2:]:
    label, a, b = spec.split(":")
    sel = [p for t, p in rows
           if float(a) <= t < float(b) and (p[1], p[2]) == main_sig]
    print("\n--- %s (%s..%s s): %d frames" % (label, a, b, len(sel)))
    if not sel:
        continue
    width = min(len(p) for p in sel)
    for i in range(width):
        vals = [p[i] for p in sel]
        if max(vals) != min(vals):
            print("    byte %2d: %3d..%3d" % (i, min(vals), max(vals)))
    print("    16-bit LE pairs with travel:")
    for i in range(width - 1):
        vals = [s16(p, i) for p in sel]
        if max(vals) - min(vals) > 100:
            print("      [%2d:%2d] %7d..%7d" % (i, i + 1, min(vals), max(vals)))
