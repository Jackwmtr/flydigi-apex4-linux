#!/usr/bin/env python3
"""Is the yaw rate really zero when nothing moves, and do the two yaw fields agree?

Reads the pad's vendor stream directly: the 12-bit copy at [4:5] and the
discontinuous int16 at [18]+[20]. If those two disagree in anything but scale,
the one being relayed is the wrong field -- which would look exactly like drift.
"""
import os, select, statistics, struct, sys, time

node = sys.argv[1] if len(sys.argv) > 1 else "/dev/hidraw10"
secs = float(sys.argv[2]) if len(sys.argv) > 2 else 30.0
fd = os.open(node, os.O_RDONLY | os.O_NONBLOCK)
split, twelve, pitch, roll, nonzero = [], [], [], [], 0
end = time.time() + secs
while time.time() < end:
    if not select.select([fd], [], [], 0.2)[0]:
        continue
    p = os.read(fd, 64)
    if len(p) < 32 or p[0] != 4 or p[15] in (236, 235, 234, 231, 229, 51):
        continue
    v = p[18] | (p[20] << 8)
    v = v - 65536 if v & 0x8000 else v
    w = p[4] | ((p[5] & 0x0F) << 8)
    w = w - 4096 if w & 0x800 else w
    split.append(v)
    twelve.append(w)
    pitch.append(struct.unpack_from("<h", p, 26)[0])
    roll.append(struct.unpack_from("<h", p, 29)[0])
    if v or w:
        nonzero += 1
os.close(fd)
n = len(split)
print("%d frames over %.0fs" % (n, secs))
for name, series in (("yaw split[18|20]", split), ("yaw 12-bit[4:5]", twelve),
                     ("pitch[26:27]", pitch), ("roll[29:30]", roll)):
    print("  %-18s mean %+8.3f  stdev %6.3f  min %6d  max %6d"
          % (name, statistics.mean(series), statistics.pstdev(series),
             min(series), max(series)))
print("  frames with any yaw value: %d of %d (%.1f%%)" % (nonzero, n, 100.0 * nonzero / n))
pairs = [(a, b) for a, b in zip(split, twelve) if b]
if pairs:
    ratios = [a / b for a, b in pairs]
    print("  split/12bit ratio: mean %+.4f  stdev %.4f  over %d frames"
          % (statistics.mean(ratios), statistics.pstdev(ratios), len(ratios)))
    print("  integrated yaw over the window: split %+.1f deg, 12bit %+.1f deg"
          % (sum(split) * 0.400 * secs / n, sum(twelve) * 0.400 * secs / n))
else:
    print("  12-bit field never left zero, so no ratio to take")
