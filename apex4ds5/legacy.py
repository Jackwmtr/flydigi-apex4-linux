# SPDX-License-Identifier: MIT
"""Flydigi Apex 4 ("old dialect", DeviceType 84 / DeviceCode k2) vendor report.

Everything here was measured on hardware: an Apex 4 on its 2.4 GHz dongle,
firmware dongle 04:15, CPU wch ch573, reading /dev/hidraw* on the interface that
carries usage page 0xFFA0 (report descriptor prefix 06 a0 ff).

The layout is Vader-3-Pro-shaped, shifted by one for the report id byte, but the
SCALES ARE NOT: the Apex 4 reports ~790 LSB per g, not 4096, and its three gyro
axes do not share a scale. Both were measured, see GYRO_DEG_PER_LSB.

    [0]        report id 0x04
    [4:5]      gyro yaw, 12-bit copy (low byte 4, high nibble of 5)
    [7]        paddle flags -- bits 3,5,4,2 are M1..M4 left to right (mask 0x3C),
               confirmed twice by pressing them in order. On evdev the same four
               arrive as TRIGGER_HAPPY1, TRIGGER_HAPPY3, TRIGGER_HAPPY2 and
               BTN_DEAD, which is a second reason to read them here instead.
    [8]        bit 3 = the Home key. It is not a gamepad button at all: the pad
               reports it through the descriptor's Consumer page, so it reaches
               evdev as KEY_RED (0x18E) and BTN_MODE stays empty forever.
    [9],[10]   button flags; b10 bit4 = L2 pressed, bit5 = R2 pressed
    [11:12]    accel X   [13:14] accel Y   [15:16] accel Z   (int16 LE)
    [17],[19]  right stick X,Y      [21],[22] left stick X,Y   (8-bit, 0x7f centre)
    [18],[20]  gyro yaw, full int16 -- DISCONTINUOUS: 18 is low, 20 is high
    [23],[24]  L2, R2 analogue 0..255
    [26:27]    gyro pitch (rotation about the accel X axis)
    [29:30]    gyro roll  (rotation about the accel Y axis)
"""
import os, struct

VENDOR_ID = 0x04B4
PRODUCT_ID = 0x2412
VENDOR_DESC_PREFIX = bytes((0x06, 0xA0, 0xFF))
INPUT_REPORT_ID = 0x04
REPORT_LEN = 32

# Command channel: 12 bytes out, [5, cmd, args...]. Replies come back inside the
# 0x04 input stream, discriminated by the command echo in byte 15 -- not by a
# report id of their own, which is what makes them look like input noise.
CMD_REPORT_ID = 0x05
CMD_GET_DEVICE_INFO = 236
CMD_HAPTIC = 0x0F           # [5, 0x0F, left, right], each 0..255
CMD_GET_DONGLE_VERSION = 17
CMD_ECHO_OFFSET = 15
DEVICE_TYPE_APEX4 = 84

# Measured. Slow and fast 360 deg turns agreed within 2% on yaw, so the firmware
# does not clip the top of the range. Pitch and roll are anchored by the
# accelerometer's own sweep through gravity (365 and 359 degrees), which is
# independent of how accurately a hand turn was made.
GYRO_DEG_PER_LSB = {"pitch": 0.377, "yaw": 0.400, "roll": 0.114}

# Accelerometer, from an axis-aligned ellipsoid fit over 614k resting samples in
# three separate captures: the only physical constraint used is that gravity has
# the same length in every orientation. Residual |a| came out 1.0000 with a
# standard deviation of 0.0024, so the axes are pinned, not guessed.
#
# Two earlier hand estimates were wrong and are worth recording as such: a
# common 790 LSB/g for all three axes (the axes differ), and a Y offset of -57
# read off two poses whose gravity magnitude was visibly off (704 and 894 against
# 800). That magnitude error was not a leaning pad -- it was this Y offset.
#
# The Y offset of -98 also means the pad reads about +0.12 g on Y while lying
# "flat", i.e. it rests tilted back some 7 degrees on its curved underside. That
# is real and is left in: it is the pad's attitude, not an error to subtract.
ACCEL_LSB_PER_G = (792.2, 803.5, 792.2)
ACCEL_BIAS = (-6.1, -98.0, 13.0)

# Gyro signs, per axis, settled in a game -- not derived.
#
# What CAN be derived is internal consistency: the pad's accel frame is
# right-handed (X left, Y toward the player, Z up, all fixed by gravity in
# measured poses), and its gyro does not follow the right-hand rule of that
# frame. Over a full turn about X the gyro integrated to -365.4 deg while gravity
# swept -365.1; about Y, -360.2 against -359.1 -- same sign where opposite was
# required.
#
# That says the pad's own axes disagree with each other. It does NOT say how they
# should land in the DualSense's frame, which is the sign a game actually sees --
# and taking the derivation for that answer was wrong twice over: yaw came out
# inverted with Steam driving gyro-to-mouse, and pitch came out inverted in an
# actual game (aiming up looked down), where the test page's icons were too small
# to notice it.
#
# So all three are empirical now, roll included -- confirmed in a game after the
# other two, and it turned out the derived sign was right for this one.
GYRO_SIGN = {"pitch": 1, "yaw": 1, "roll": -1}


def _s16(lo, hi):
    v = lo | (hi << 8)
    return v - 65536 if v & 0x8000 else v


def find_vendor_node():
    """The hidraw node carrying the vendor collection, or None.

    Matched on the report descriptor prefix as well as the ids: all four of the
    pad's interfaces share `04b4:2412`, and a command written to the mouse one is
    accepted silently and does nothing.
    """
    import fcntl, glob
    for path in sorted(glob.glob("/dev/hidraw*")):
        uevent = "/sys/class/hidraw/%s/device/uevent" % os.path.basename(path)
        try:
            text = open(uevent).read()
        except OSError:
            continue
        matched = False
        for line in text.splitlines():
            if line.startswith("HID_ID="):
                # bus:vendor:product, each id zero-padded to eight hex digits,
                # so a "%04x:%04x" substring never matches.
                parts = line.split("=", 1)[1].split(":")
                matched = (len(parts) == 3
                           and int(parts[1], 16) == VENDOR_ID
                           and int(parts[2], 16) == PRODUCT_ID)
        if not matched:
            continue
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
        except OSError:
            continue
        try:
            size = struct.unpack("i", fcntl.ioctl(fd, 0x80044801, struct.pack("i", 0)))[0]
            buf = bytearray(struct.pack("I4096s", size, b""))
            fcntl.ioctl(fd, 0x90044802, buf, True)
        except OSError:
            continue
        finally:
            os.close(fd)
        if bytes(buf[4:4 + len(VENDOR_DESC_PREFIX)]) == VENDOR_DESC_PREFIX:
            return path
    return None


def read_device_info(node, timeout=2.0):
    """Ask the pad who it is. Returns the parsed dict, or None on silence."""
    import select, time
    fd = os.open(node, os.O_RDWR | os.O_NONBLOCK)
    try:
        os.write(fd, bytes([CMD_REPORT_ID, CMD_GET_DEVICE_INFO] + [0] * 10))
        end = time.time() + timeout
        while time.time() < end:
            if not select.select([fd], [], [], 0.1)[0]:
                continue
            data = os.read(fd, 64)
            if is_input(data) and data[CMD_ECHO_OFFSET] == CMD_GET_DEVICE_INFO:
                return parse_device_info(data)
    finally:
        os.close(fd)
    return None


def haptic_packet(left, right):
    """Rumble command for the old dialect: one write to the vendor interface."""
    return bytes([CMD_REPORT_ID, CMD_HAPTIC, left & 0xFF, right & 0xFF])


def is_input(data):
    return len(data) >= REPORT_LEN and data[0] == INPUT_REPORT_ID


def command_echo(data):
    """The command this frame is answering, or None for a plain input frame."""
    if not is_input(data):
        return None
    echo = data[CMD_ECHO_OFFSET]
    return echo if echo in (236, 235, 234, 231, 229, 51, 17) else None


# Battery is a LEVEL, not a percentage: Flydigi report 0..5 steps, with 6 as
# the "charging" sentinel. Reading it as a percentage is why this pad looked
# like it was at 4% for a whole session while its own display showed nearly
# full -- and it is the same mistake behind flydigictl's issue #5.
BATTERY_MAX_LEVEL = 5
BATTERY_CHARGING = 6

# Connection type is at byte 13 after all -- where a Vader-era map puts it. On the
# dongle it reads 0, which that map does not name, and reading the neighbouring
# byte instead (a constant 2) looked like the fix until a cable disproved it: wired
# reads 1 there while byte 14 stays 2. So 0 means the 2.4 GHz dongle on this pad,
# and byte 14 is the motion-sensor type, also as the old map says.
CONNECTION = {0: "dongle", 1: "wired", 2: "wireless", 3: "bluetooth"}


def parse_device_info(data):
    """Decode a command-236 reply."""
    level = data[11]
    charging = level == BATTERY_CHARGING
    return {
        "device_type": data[3],
        "mac": data[5:9].hex(":"),
        "firmware": (data[10], data[9]),
        "battery_level": level,
        "battery_charging": charging,
        "battery_percent": None if charging
        else min(100, round(100 * level / BATTERY_MAX_LEVEL)),
        "cpu": data[12],
        "connection": CONNECTION.get(data[13], "unknown(%d)" % data[13]),
        "motion_sensor_type": data[14],
    }


class Reading:
    """One decoded input frame, in physical units."""

    __slots__ = ("gyro_deg_s", "accel_g", "l2", "r2", "paddles", "home", "raw")

    def __init__(self, data):
        self.raw = data
        pitch = _s16(data[26], data[27])
        roll = _s16(data[29], data[30])
        yaw = _s16(data[18], data[20])          # discontinuous, low then high
        self.gyro_deg_s = tuple(
            GYRO_SIGN[axis] * raw * GYRO_DEG_PER_LSB[axis]
            for axis, raw in (("pitch", pitch), ("yaw", yaw), ("roll", roll))
        )
        raw = struct.unpack_from("<3h", data, 11)
        self.accel_g = tuple(
            (raw[i] - ACCEL_BIAS[i]) / ACCEL_LSB_PER_G[i] for i in range(3)
        )
        self.l2 = data[23]
        self.r2 = data[24]
        flags = data[7]
        # Physical order left to right; the bit order is not the button order.
        self.paddles = tuple(bool(flags & (1 << b)) for b in (3, 5, 4, 2))
        self.home = bool(data[8] & 0x08)
