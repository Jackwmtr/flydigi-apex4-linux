#!/usr/bin/env python3
"""Trigger rumble through the kernel's force-feedback interface.

Goes the same way a game does: upload an FF_RUMBLE effect to the DualSense
gamepad node and play it. If the pad buzzes, the whole chain works -- game ->
kernel -> DS5 output report -> uhid -> relay -> the pad's haptic command.
"""
import fcntl, os, re, struct, sys, time

EVIOCSFF = 0x40304580          # _IOW('E', 0x80, struct ff_effect), 48 bytes
FF_RUMBLE, EV_FF = 0x50, 0x15


def gamepad_node():
    text = open("/proc/bus/input/devices").read()
    for block in text.split("\n\n"):
        if 'Name="Apex 4 (DualSense)"' in block:
            m = re.search(r"event(\d+)", block)
            if m:
                return "/dev/input/event%s" % m.group(1)
    return None


# Usage: ff-test.py [strong] [weak] [--node /dev/input/eventN]
# strong drives the LEFT motor and weak the RIGHT one -- that is the kernel's
# mapping (strong_magnitude -> motor_left), not a choice made here.
args = sys.argv[1:]
node = None
if "--node" in args:
    i = args.index("--node")
    node = args[i + 1]
    del args[i:i + 2]
node = node or gamepad_node()
strong = int(args[0]) if len(args) > 0 else 0xFFFF
weak = int(args[1]) if len(args) > 1 else 0xFFFF
if not node:
    sys.exit("no Apex 4 (DualSense) gamepad node found")
print("rumbling %s: strong %d weak %d" % (node, strong, weak))
fd = os.open(node, os.O_RDWR)
effect = bytearray(48)
struct.pack_into("<HhHHHHH", effect, 0, FF_RUMBLE, -1, 0, 0, 0, 2000, 0)
struct.pack_into("<HH", effect, 16, strong, weak)
fcntl.ioctl(fd, EVIOCSFF, effect, True)
effect_id = struct.unpack_from("<h", effect, 2)[0]
print("effect id %d uploaded; playing 2s" % effect_id)
os.write(fd, struct.pack("llHHi", 0, 0, EV_FF, effect_id, 1))
time.sleep(2.2)
os.close(fd)
print("done")
