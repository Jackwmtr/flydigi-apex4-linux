#!/usr/bin/env python3
"""Read a DualSense Motion Sensors node and print values in physical units.

hid-playstation normalises accel to 1/8192 g and gyro to 1/1024 deg/s.
"""
import os, select, struct, sys, time
NAMES = {0x00: "accelX", 0x01: "accelY", 0x02: "accelZ",
         0x03: "gyroRX", 0x04: "gyroRY", 0x05: "gyroRZ"}
node, secs = sys.argv[1], float(sys.argv[2]) if len(sys.argv) > 2 else 4.0
fd = os.open(node, os.O_RDONLY | os.O_NONBLOCK)
SZ = struct.calcsize("llHHi")
cur, lo, hi, n = {}, {}, {}, 0
end = time.time() + secs
while time.time() < end:
    if not select.select([fd], [], [], 0.2)[0]:
        continue
    data = os.read(fd, SZ * 64)
    for off in range(0, len(data) - SZ + 1, SZ):
        _, _, etype, code, value = struct.unpack_from("llHHi", data, off)
        if etype == 0x03 and code in NAMES:
            cur[code] = value
            lo[code] = min(lo.get(code, value), value)
            hi[code] = max(hi.get(code, value), value)
            n += 1
os.close(fd)
print("%d sensor events" % n)
for code, name in NAMES.items():
    if code in cur:
        unit = 8192.0 if code < 3 else 1024.0
        what = "g" if code < 3 else "deg/s"
        print("  %-7s raw %7d  (%7.2f %s)   range %7d..%-7d" % (
            name, cur[code], cur[code] / unit, what, lo[code], hi[code]))
