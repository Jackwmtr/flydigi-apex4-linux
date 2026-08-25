#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Check the whole chain on this machine and say which link is missing.

Exits non-zero on the first hard failure. Run before installing anything.
"""
import os, sys, time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from apex4ds5 import legacy

APEX4 = legacy.DEVICE_TYPE_APEX4
ok, warn, bad = "  ok  ", " warn ", " FAIL "
failures = 0


def report(status, what, detail=""):
    print("[%s] %-34s %s" % (status, what, detail))


def modules():
    global failures
    for name, why in (("uhid", "needed to create the virtual controller"),
                      ("hid_playstation", "needed to pick it up as a DualSense")):
        loaded = os.path.exists("/sys/module/" + name)
        if loaded:
            report(ok, name)
        else:
            # built into the kernel rather than a module is also fine, but we
            # cannot tell that apart here, so say what to try rather than fail.
            report(warn, name, "not loaded -- try: sudo modprobe %s (%s)" % (name, why))


def uhid_writable():
    global failures
    try:
        fd = os.open("/dev/uhid", os.O_RDWR)
        os.close(fd)
        report(ok, "/dev/uhid writable")
    except OSError as exc:
        failures += 1
        report(bad, "/dev/uhid writable",
               "%s -- install udev/72-apex4-ds5.rules" % exc.strerror)


def pad():
    global failures
    node = legacy.find_vendor_node()
    if not node:
        failures += 1
        report(bad, "vendor interface", "not found -- pad off, or in a mode with no HID")
        return None
    report(ok, "vendor interface", node)
    info = legacy.read_device_info(node)
    if not info:
        failures += 1
        report(bad, "pad answers commands", "no reply to command 236")
        return node
    kind = "Apex 4" if info["device_type"] == APEX4 else "UNKNOWN model"
    status = ok if info["device_type"] == APEX4 else warn
    report(status, "pad identity",
           "%s (DeviceType %d), battery level %s/5, %s"
           % (kind, info["device_type"], info["battery_level"], info["connection"]))
    if info["device_type"] != APEX4:
        print("\n       The constants in this repository were measured on an Apex 4 and are")
        print("       per-model: axis scales differ by 3x between axes on that pad alone.")
        print("       Running with them would give a gyro that quietly lies. See docs/")
        print("       PROTOCOL.md and tools/ to measure yours.\n")
    return node


def sensors(node):
    """Gravity is the reference: at rest the accel vector must be about 1 g."""
    global failures
    import select
    fd = os.open(node, os.O_RDONLY | os.O_NONBLOCK)
    best, end = None, time.time() + 2.0
    try:
        while time.time() < end:
            if not select.select([fd], [], [], 0.2)[0]:
                continue
            data = os.read(fd, 64)
            if legacy.is_input(data) and legacy.command_echo(data) is None:
                r = legacy.Reading(data)
                best = sum(v * v for v in r.accel_g) ** 0.5
    finally:
        os.close(fd)
    if best is None:
        failures += 1
        report(bad, "sensor stream", "no input reports at all")
    elif 0.8 <= best <= 1.2:
        report(ok, "sensor stream", "gravity reads %.2f g" % best)
    else:
        failures += 1
        report(bad, "sensor stream",
               "gravity reads %.2f g -- constants do not fit this pad" % best)


print("flydigi-legacy-ds5 self-test\n")
modules()
uhid_writable()
node = pad()
if node:
    sensors(node)
print()
if failures:
    print("%d check(s) failed -- see above." % failures)
    sys.exit(1)
print("All checks passed.")
