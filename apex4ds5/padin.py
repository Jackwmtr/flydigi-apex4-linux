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


class PadState:
    """Latest button and axis state, fed by evdev events."""

    def __init__(self):
        self.abs = {ABS_X: 128, ABS_Y: 128, ABS_Z: 128, ABS_RZ: 128,
                    ABS_GAS: 0, ABS_BRAKE: 0, ABS_HAT0X: 0, ABS_HAT0Y: 0}
        self.keys = {}

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
