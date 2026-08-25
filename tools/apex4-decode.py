#!/usr/bin/env python3
"""Decode the Apex 4 vendor report under the hypothesis 'Vader 3 Pro layout, +1 for report id'.

  [0]      report id 0x04
  [4:6]    gyro yaw, 12-bit packed (low byte 4, high nibble 5) -- also duplicated at [18],[20]
  [7]      paddle/extra flags        [8] home / aeromouse
  [9],[10] button flags
  [11:12]  accel X   [13:14] accel Y   [15:16] accel Z
  [17],[19] right stick X,Y           [21],[22] left stick X,Y
  [23],[24] LT, RT analog             [25] trigger digital flags
  [26:27]  gyro pitch                 [29:30] gyro roll
"""
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


def s12(lo, hi_nibble):
    v = lo | ((hi_nibble & 0x0F) << 8)
    return v - 4096 if v & 0x800 else v


def fields(p):
    return {
        "gyroYaw12": s12(p[4], p[5]),
        "gyroSplit": (lambda v: v - 65536 if v & 0x8000 else v)(p[18] | (p[20] << 8)),
        "gyroPitch": s16(p, 26),
        "gyroRoll": s16(p, 29),
        "accelX": s16(p, 11),
        "accelY": s16(p, 13),
        "accelZ": s16(p, 15),
        "LT": p[23],
        "RT": p[24],
        "flags7": p[7],
        "btn9": p[9],
        "btn10": p[10],
        "rsX": p[17],
        "rsY": p[19],
        "lsX": p[21],
        "lsY": p[22],
    }


rows = [(t, p) for t, p in load(sys.argv[1]) if len(p) >= 32 and p[0] == 4]
step = float(sys.argv[2]) if len(sys.argv) > 2 else 5.0
start = float(sys.argv[3]) if len(sys.argv) > 3 else 0.0
stop = float(sys.argv[4]) if len(sys.argv) > 4 else rows[-1][0]
names = ["gyroYaw12", "gyroSplit", "gyroPitch", "gyroRoll", "accelZ"]
print("t(s)   " + "".join("%14s" % n for n in names) + "   LT   RT  f7 b9 b10  sticks")
t = start
while t < stop:
    sel = [p for tt, p in rows if t <= tt < t + step]
    if sel:
        f = [fields(p) for p in sel]
        line = "%5.0f  " % t
        for n in names:
            vals = [x[n] for x in f]
            line += "%6d..%-6d" % (min(vals), max(vals))
        line += " %3d %3d" % (max(x["LT"] for x in f), max(x["RT"] for x in f))
        line += " %3d %2d %3d" % (max(x["flags7"] for x in f), max(x["btn9"] for x in f),
                                  max(x["btn10"] for x in f))
        line += "  %d/%d %d/%d" % (min(x["rsX"] for x in f), max(x["rsX"] for x in f),
                                   min(x["lsX"] for x in f), max(x["lsX"] for x in f))
        print(line)
    t += step
