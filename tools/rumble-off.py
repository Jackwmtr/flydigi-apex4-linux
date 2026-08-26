#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Silence the pad's motors, whatever left them running.

The pad holds the last level it was given, so a relay that dies mid-rumble (or a
consumer that never sends a stop) leaves it buzzing with nothing to stop it. This
writes the zero haptic command straight to the vendor interface, so it works with
the relay stopped -- which is usually the situation it is needed in.

The node has to be picked by its report descriptor, not by vendor and product id:
the pad exposes four interfaces under the same ids, and a haptic command written
to the mouse one is silently accepted and does nothing at all.
"""
import fcntl, glob, os, struct, sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from apex4ds5 import legacy

HIDIOCGRDESCSIZE, HIDIOCGRDESC = 0x80044801, 0x90044802


def vendor_node():
    for path in sorted(glob.glob("/dev/hidraw*")):
        uevent = "/sys/class/hidraw/%s/device/uevent" % os.path.basename(path)
        try:
            text = open(uevent).read()
        except OSError:
            continue
        ids_match = False
        for line in text.splitlines():
            if line.startswith("HID_ID="):
                parts = line.split("=", 1)[1].split(":")
                ids_match = (len(parts) == 3
                             and int(parts[1], 16) == legacy.VENDOR_ID
                             and int(parts[2], 16) == legacy.PRODUCT_ID)
        if not ids_match:
            continue
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
        except OSError:
            continue
        try:
            size = struct.unpack("i", fcntl.ioctl(fd, HIDIOCGRDESCSIZE,
                                                  struct.pack("i", 0)))[0]
            buf = bytearray(struct.pack("I4096s", size, b""))
            fcntl.ioctl(fd, HIDIOCGRDESC, buf, True)
        except OSError:
            continue
        finally:
            os.close(fd)
        if bytes(buf[4:4 + len(legacy.VENDOR_DESC_PREFIX)]) == legacy.VENDOR_DESC_PREFIX:
            return path
    return None


node = vendor_node()
if not node:
    sys.exit("no Apex 4 vendor interface on the bus")
fd = os.open(node, os.O_RDWR)
for _ in range(3):
    os.write(fd, legacy.haptic_packet(0, 0))
os.close(fd)
print("motors silenced via %s" % node)
