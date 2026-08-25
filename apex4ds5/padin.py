# SPDX-License-Identifier: MIT
"""Minimal evdev reader for the Apex 4's ordinary gamepad node.

Buttons and sticks come from here rather than from the vendor stream: the kernel
already decodes this node from a self-describing HID descriptor, so the physical
button order needs no guessing. Only the IMU has to come from the vendor
interface, because no kernel driver decodes that.

The pad's descriptor declares sticks as X/Y (left) and Z/Rz (right), 8-bit, plus
Simulation-page Brake and Accelerator for the analogue triggers -- so the axes
arrive as ABS_X/ABS_Y/ABS_Z/ABS_RZ and ABS_BRAKE/ABS_GAS.
"""
import ctypes, fcntl, glob, os, struct

EV_SYN, EV_KEY, EV_ABS = 0x00, 0x01, 0x03
ABS_X, ABS_Y, ABS_Z, ABS_RZ = 0x00, 0x01, 0x02, 0x05
ABS_GAS, ABS_BRAKE = 0x09, 0x0A
ABS_HAT0X, ABS_HAT0Y = 0x10, 0x11

BTN_SOUTH, BTN_EAST, BTN_C, BTN_NORTH = 0x130, 0x131, 0x132, 0x133
BTN_WEST, BTN_Z, BTN_TL, BTN_TR = 0x134, 0x135, 0x136, 0x137
BTN_TL2, BTN_TR2, BTN_SELECT, BTN_START = 0x138, 0x139, 0x13A, 0x13B
BTN_MODE, BTN_THUMBL, BTN_THUMBR = 0x13C, 0x13D, 0x13E

EVENT_SIZE = struct.calcsize("llHHi")
_EVIOCGNAME = 0x81004506  # _IOR('E', 0x06, 256)
_EVIOCGABS = 0x80184540   # _IOR('E', 0x40 + code, struct input_absinfo)
_ABSINFO = struct.Struct("6i")   # value, min, max, fuzz, flat, resolution

STICKS = (ABS_X, ABS_Y, ABS_Z, ABS_RZ)
TRIGGERS = (ABS_BRAKE, ABS_GAS)


def device_name(fd):
    buf = ctypes.create_string_buffer(256)
    fcntl.ioctl(fd, _EVIOCGNAME, buf, True)
    return buf.value.decode(errors="replace")


def find_pad(match="Flydigi"):
    """The first event node whose name matches and that has gamepad buttons."""
    for node in sorted(glob.glob("/dev/input/event*")):
        try:
            fd = os.open(node, os.O_RDONLY | os.O_NONBLOCK)
        except OSError:
            continue
        try:
            name = device_name(fd)
        except OSError:
            os.close(fd)
            continue
        if match.lower() in name.lower():
            return node, name, fd
        os.close(fd)
    return None, None, None


def axis_ranges(fd):
    """The kernel's own min/max for each axis we care about.

    Assuming a range is how the sticks ended up pinned to a corner over
    Bluetooth: the same pad reports 0..255 through its dongle and **-128..127**
    over Bluetooth, where a centred stick reads -1 and a hard-coded neutral of
    128 turns that into 255. The descriptor differs per connection, so the range
    has to be read rather than known.
    """
    ranges = {}
    for code in STICKS + TRIGGERS:
        data = bytearray(_ABSINFO.size)
        try:
            fcntl.ioctl(fd, _EVIOCGABS + code, data, True)
        except OSError:
            continue
        _, minimum, maximum, _, _, _ = _ABSINFO.unpack(data)
        if maximum > minimum:
            ranges[code] = (minimum, maximum)
    return ranges


class PadState:
    """Latest button and axis state, fed by evdev events.

    Axis values are kept raw and scaled on demand, so one pad connected two
    different ways needs no special cases anywhere else.
    """

    def __init__(self, ranges=None):
        self.ranges = dict(ranges or {})
        self.abs = {}
        for code in STICKS:
            self.abs[code] = self._neutral(code)
        for code in TRIGGERS:
            self.abs[code] = self.ranges.get(code, (0, 255))[0]
        self.abs[ABS_HAT0X] = self.abs[ABS_HAT0Y] = 0
        self.keys = {}

    def _neutral(self, code):
        lo, hi = self.ranges.get(code, (0, 255))
        return (lo + hi) // 2

    def stick(self, code):
        """A stick axis as 0..255 with the neutral landing exactly on 0x80.

        The two halves are scaled separately for that reason, around the range's
        floored midpoint rather than its arithmetic centre -- because that is
        where this pad actually rests, measured both ways: 127 out of 0..255 on
        the dongle and -1 out of -128..127 over Bluetooth, each one step below
        the arithmetic middle of a 256-value range. A single linear map puts the
        centre half a step off, which is invisible on a test page and a slow
        drift in a game with a dead zone around centre.
        """
        if code not in self.abs:
            return 128
        lo, hi = self.ranges.get(code, (0, 255))
        mid = (lo + hi) // 2
        value = self.abs[code]
        if hi - lo <= 0:
            return 128
        if value >= mid:
            out = 128 + (value - mid) * 127.0 / max(hi - mid, 1e-9)
        else:
            out = 128 - (mid - value) * 128.0 / max(mid - lo, 1e-9)
        return max(0, min(255, int(round(out))))

    def axis(self, code, default=0):
        """A one-ended axis (a trigger) as 0..255."""
        if code not in self.abs:
            return default
        lo, hi = self.ranges.get(code, (0, 255))
        if hi - lo <= 0:
            return default
        return max(0, min(255, (self.abs[code] - lo) * 255 // (hi - lo)))

    def feed(self, fd):
        """Drain pending events; returns True if anything changed."""
        changed = False
        while True:
            try:
                data = os.read(fd, EVENT_SIZE * 32)
            except BlockingIOError:
                return changed
            if not data:
                return changed
            for off in range(0, len(data) - EVENT_SIZE + 1, EVENT_SIZE):
                _, _, etype, code, value = struct.unpack_from("llHHi", data, off)
                if etype == EV_ABS:
                    self.abs[code] = value
                    changed = True
                elif etype == EV_KEY:
                    self.keys[code] = value
                    changed = True

    def down(self, code):
        return bool(self.keys.get(code))
