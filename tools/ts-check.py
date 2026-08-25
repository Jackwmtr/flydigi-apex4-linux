#!/usr/bin/env python3
"""Does MSC_TIMESTAMP on the motion node advance at real time?

hid-playstation divides the DualSense timestamp delta by 3 to get microseconds,
so the relay must send microseconds*3. If that factor is wrong, anything that
integrates rate over time -- gyro-to-mouse, in-game aim -- is mis-scaled.
"""
import os, select, struct, sys, time
node = sys.argv[1]
secs = float(sys.argv[2]) if len(sys.argv) > 2 else 10.0
SZ = struct.calcsize("llHHi")
fd = os.open(node, os.O_RDONLY | os.O_NONBLOCK)
first = last = None
t_start = time.time()
end = t_start + secs
while time.time() < end:
    if not select.select([fd], [], [], 0.2)[0]:
        continue
    data = os.read(fd, SZ * 64)
    for off in range(0, len(data) - SZ + 1, SZ):
        _, _, etype, code, value = struct.unpack_from("llHHi", data, off)
        if etype == 0x04 and code == 0x05:      # EV_MSC / MSC_TIMESTAMP
            if first is None:
                first = value
            last = value
os.close(fd)
wall = time.time() - t_start
if first is None:
    print("no MSC_TIMESTAMP seen -- the motion node reported nothing")
else:
    span = (last - first) & 0xFFFFFFFF
    print("wall clock %.3f s, MSC_TIMESTAMP advanced %d us (%.3f s)" % (wall, span, span / 1e6))
    print("ratio device/real = %.4f  (1.0 is correct)" % (span / 1e6 / wall))
