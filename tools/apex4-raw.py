#!/usr/bin/env python3
"""Continuous raw logger: timestamp + payload, until the time cap."""
import os, select, struct, sys, time
node, secs, out = sys.argv[1], float(sys.argv[2]), sys.argv[3]
fd = os.open(node, os.O_RDONLY | os.O_NONBLOCK)
t0 = time.time()
n = 0
with open(out, "wb") as f:
    while time.time() - t0 < secs:
        if not select.select([fd], [], [], 0.5)[0]:
            continue
        p = os.read(fd, 64)
        f.write(struct.pack("dB", time.time() - t0, len(p)) + p)
        n += 1
        if n % 2000 == 0:
            f.flush()
            os.fsync(f.fileno())
os.close(fd)
print("%d reports -> %s" % (n, out))
