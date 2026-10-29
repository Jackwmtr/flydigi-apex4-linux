#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Fire DualSense adaptive-trigger effects at the virtual controller.

Writes the same USB output report (0x02) a game would, to the virtual
DualSense's own hidraw node -- so it exercises the whole chain: hidraw, uhid,
the relay's parser and translation, and the command to the pad. Nothing here
talks to the pad directly.

    trigger-test.py right race 40 180     DS5 type 0x01: start, strength
    trigger-test.py right recoil 40 60 200  type 0x02: start, end, strength
    trigger-test.py left buzz 30 200 10   type 0x06: frequency, amplitude, start
    trigger-test.py both off              type 0x05
    trigger-test.py right raw 0x25 20 0 2 one raw type + up to 10 param bytes

Watch the relay's log while doing it: `journalctl --user -fu flydigi-apex4`
(with "verbose": true it prints what each effect was translated to).
"""
import glob, os, sys

SONY = 0x054C
PRODUCTS = (0x0CE6, 0x0DF2)
FLAG0_RIGHT, FLAG0_LEFT = 0x04, 0x08

NAMED = {            # DualSense "simple" effect types and their params
    "race": 0x01,
    "recoil": 0x02,
    "off": 0x05,
    "buzz": 0x06,
}


def find_virtual():
    for path in sorted(glob.glob("/sys/class/hidraw/hidraw*/device/uevent")):
        text = open(path).read()
        ids = name = None
        for line in text.splitlines():
            if line.startswith("HID_ID="):
                parts = line.split("=", 1)[1].split(":")
                ids = (int(parts[1], 16), int(parts[2], 16))
            elif line.startswith("HID_NAME="):
                name = line.split("=", 1)[1]
        if ids and ids[0] == SONY and ids[1] in PRODUCTS and name and "Apex" in name:
            return "/dev/" + path.split("/")[4], name
    return None, None


def number(text):
    return int(text, 0)


def main(argv):
    if len(argv) < 2 or argv[0] not in ("left", "right", "both"):
        raise SystemExit(__doc__)
    side, what, rest = argv[0], argv[1], argv[2:]
    if what == "raw":
        type_, params = number(rest[0]), [number(v) for v in rest[1:]]
    elif what in NAMED:
        type_, params = NAMED[what], [number(v) for v in rest]
    else:
        raise SystemExit("unknown effect %r; one of %s, raw"
                         % (what, ", ".join(NAMED)))
    block = bytes([type_] + params[:10] + [0] * (10 - len(params[:10])))

    report = bytearray(48)
    report[0] = 0x02
    if side in ("right", "both"):
        report[1] |= FLAG0_RIGHT
        report[11:22] = block
    if side in ("left", "both"):
        report[1] |= FLAG0_LEFT
        report[22:33] = block

    node, name = find_virtual()
    if not node:
        raise SystemExit("no virtual Apex 4 DualSense found -- is the relay running?")
    fd = os.open(node, os.O_WRONLY)
    try:
        os.write(fd, bytes(report))
    finally:
        os.close(fd)
    print("%s (%s): %s type 0x%02x params %s"
          % (node, name, side, type_, block[1:].hex(" ")))


if __name__ == "__main__":
    main(sys.argv[1:])
