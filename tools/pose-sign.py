#!/usr/bin/env python3
"""Watch a DualSense motion node and report each held-still pose, in order.

Still means the gyro is quiet; the pose is then the mean gravity vector, in g.
Two poses in a known order are enough to pin the two undetermined axis signs.
"""
import os, select, struct, sys, time

node = sys.argv[1]
secs = float(sys.argv[2]) if len(sys.argv) > 2 else 150.0
QUIET_GYRO = 3000        # raw, ~3 deg/s
MIN_STILL = 1.2
SZ = struct.calcsize("llHHi")

fd = os.open(node, os.O_RDONLY | os.O_NONBLOCK)
acc = {0: 0, 1: 0, 2: 0}
gyr = {3: 0, 4: 0, 5: 0}
still_since, samples, poses = None, [], 0
end = time.time() + secs
print("watching %s -- hold each pose still for ~3s" % node, flush=True)
while time.time() < end:
    if not select.select([fd], [], [], 0.2)[0]:
        pass
    else:
        data = os.read(fd, SZ * 64)
        for off in range(0, len(data) - SZ + 1, SZ):
            _, _, etype, code, value = struct.unpack_from("llHHi", data, off)
            if etype == 0x03:
                if code in acc:
                    acc[code] = value
                elif code in gyr:
                    gyr[code] = value
    quiet = all(abs(v) < QUIET_GYRO for v in gyr.values())
    now = time.time()
    if quiet:
        if still_since is None:
            still_since, samples = now, []
        samples.append((acc[0], acc[1], acc[2]))
    else:
        if still_since and now - still_since >= MIN_STILL and len(samples) > 5:
            poses += 1
            n = len(samples)
            mx, my, mz = (sum(s[i] for s in samples) / n for i in range(3))
            print("pose %d: accel X %+6.2f g   Y %+6.2f g   Z %+6.2f g   (|a| %.2f)"
                  % (poses, mx / 8192, my / 8192, mz / 8192,
                     (mx * mx + my * my + mz * mz) ** 0.5 / 8192), flush=True)
        still_since, samples = None, []
os.close(fd)
print("done", flush=True)
