#!/usr/bin/env python3
"""Log every button event from both sources at once, with names where known.

evdev gives the kernel's code for a press; the vendor report gives the raw bit.
A button that appears in one and not the other is the interesting case -- that is
how the Home key gets found.
"""
import os, select, struct, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from apex4ds5 import legacy, padin

KEY_NAMES = {
    0x130: "BTN_SOUTH(A)", 0x131: "BTN_EAST(B)", 0x132: "BTN_C", 0x133: "BTN_NORTH(X?)",
    0x134: "BTN_WEST(Y?)", 0x135: "BTN_Z", 0x136: "BTN_TL(LB)", 0x137: "BTN_TR(RB)",
    0x138: "BTN_TL2", 0x139: "BTN_TR2", 0x13A: "BTN_SELECT", 0x13B: "BTN_START",
    0x13C: "BTN_MODE(guide)", 0x13D: "BTN_THUMBL", 0x13E: "BTN_THUMBR",
    0x2C0: "BTN_TRIGGER_HAPPY1", 0x2C1: "BTN_TRIGGER_HAPPY2",
    0x2C2: "BTN_TRIGGER_HAPPY3", 0x2C3: "BTN_TRIGGER_HAPPY4",
    0x0A2: "KEY_SCREENLOCK?", 0x161: "KEY_?",
}
vendor = sys.argv[1] if len(sys.argv) > 1 else "/dev/hidraw10"
secs = float(sys.argv[2]) if len(sys.argv) > 2 else 180.0
vfd = os.open(vendor, os.O_RDONLY | os.O_NONBLOCK)
node, name, pfd = padin.find_pad()
print("watching %s and %s (%s)" % (vendor, node, name), flush=True)
SZ = struct.calcsize("llHHi")
prev = {7: 0, 8: 0, 9: 0, 10: 0}
end = time.time() + secs
while time.time() < end:
    select.select([vfd, pfd], [], [], 0.1)
    try:
        while True:
            p = os.read(vfd, 64)
            if not legacy.is_input(p) or legacy.command_echo(p) is not None:
                continue
            for off in prev:
                if p[off] != prev[off]:
                    bits = [b for b in range(8) if p[off] & (1 << b)]
                    print("  vendor byte %-2d = 0x%02X  bits %s" % (off, p[off], bits), flush=True)
                    prev[off] = p[off]
    except BlockingIOError:
        pass
    try:
        while True:
            data = os.read(pfd, SZ * 32)
            if not data:
                break
            for o in range(0, len(data) - SZ + 1, SZ):
                _, _, etype, code, value = struct.unpack_from("llHHi", data, o)
                if etype == 0x01:
                    print("  evdev %s (0x%03X) %s" % (
                        KEY_NAMES.get(code, "code"), code, "down" if value else "up"), flush=True)
                elif etype == 0x03 and code in (0x10, 0x11):
                    print("  evdev hat %s = %+d" % ("XY"[code - 0x10], value), flush=True)
    except BlockingIOError:
        pass
os.close(vfd)
print("done", flush=True)
