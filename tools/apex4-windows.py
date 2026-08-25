#!/usr/bin/env python3
"""Per-window byte and 16-bit-pair spans, for reading a report layout off a capture."""
import struct, sys


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


def report(rows, label):
    if not rows:
        print("  %s: no data" % label)
        return
    width = min(len(p) for _, p in rows)
    print("  %s -- %d reports" % (label, len(rows)))
    spans = []
    for i in range(width):
        vals = [p[i] for _, p in rows]
        spans.append((max(vals) - min(vals), i, min(vals), max(vals)))
    for span, i, lo, hi in sorted(spans, reverse=True)[:12]:
        if span:
            print("     byte %2d: %3d..%3d span %3d" % (i, lo, hi, span))
    pairs = []
    for i in range(width - 1):
        vals = [s16(p, i) for _, p in rows]
        pairs.append((max(vals) - min(vals), i, min(vals), max(vals)))
    print("     top 16-bit LE pairs:")
    for span, i, lo, hi in sorted(pairs, reverse=True)[:6]:
        if span > 50:
            print("       [%2d:%2d] %7d..%7d span %6d" % (i, i + 1, lo, hi, span))


if __name__ == "__main__":
    rows = [(t, p) for t, p in load(sys.argv[1]) if len(p) >= 32 and p[0] == 4]
    for spec in sys.argv[2:]:
        label, a, b = spec.split(":")
        print("\n=== %s (%s..%s s)" % (label, a, b))
        report([(t, p) for t, p in rows if float(a) <= t < float(b)], label)
