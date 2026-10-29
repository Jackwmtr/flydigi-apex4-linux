# SPDX-License-Identifier: MIT
"""Adaptive triggers: DualSense effects from a game -> the Apex 4's own.

The translation is Flydigi's, vendored in _ds5/trigger_map.py; what lives here
is everything around it that a long-running relay has to get right.

* **Every effect goes out with applyFlag 0** (Flydigi's "onlyPreview"). It
  engages the effect without rewriting the stored profile, which matters for
  something a game may send hundreds of times a session -- openflydigi always
  sends 1, and that is the one thing about it not to copy.

* **A live effect is not cleared by anything but an explicit normal.** Measured:
  reloading a profile left a Lock engaged. So the relay sends normal to both
  sides on exit, the same lesson rumble taught, or a game's last Lock outlives
  the relay with nothing left that knows about it.

* **The wanted effect is remembered per side and sent again whenever the
  vendor interface is reopened.** A pad that slept or was switched off may
  come back with or without the effect -- both were seen -- and re-sending is
  cheap where guessing wrong leaves a game's trigger loose.

* **Every effect is sent more than once.** The pad acknowledges nothing a relay
  can see: after a 160 there is no echo in byte 15 (which is accel Z's low byte
  anyway) and no report of any other id. Flydigi's own SDK waits for an ACK and
  retries three times; blind, the equivalent is to repeat. That is not
  theoretical -- the very first left-trigger effect sent on hardware did not
  take, and the same packet sent again did. The command sets a state rather
  than starting something, so a repeat costs nothing.

* **Writes are spaced.** Effects are queued and pumped from the relay's loop at
  most one per WRITE_GAP_S, rather than written back to back when one output
  report changes both triggers.
"""
import os, sys, time

from . import legacy
from ._ds5.trigger_map import translate_ds5

SIDES = {"left": legacy.SIDE_LEFT, "right": legacy.SIDE_RIGHT}

# When to (re)send a changed effect, relative to the change.
SEND_SCHEDULE_S = (0.0, 0.1, 0.5)
WRITE_GAP_S = 0.01

# DualSense effect type 0x00 is not in Flydigi's table, so their relay leaves
# the trigger as it was. But 0x00 is what a zeroed output report carries, and
# what some titles send to mean "no effect" -- leaving the last Lock standing
# there is worse than clearing one that was never set. Ours, not Flydigi's.
DS5_EFFECT_NONE = 0x00

# Three DualSense effects Flydigi's table has no entry for, so their relay
# leaves the trigger as it was. These mappings are ours: the DualSense layout
# is the well-known one (a 10-bit zone mask over the pull in bytes 0-1, forces
# packed three bits each as value-1), and each is aimed at the Apex 4 mode
# that feels closest -- not a translation Flydigi vouched for.
DS5_EFFECT_BOW = 0x22          # resist from start to end zone, then snap
DS5_EFFECT_GALLOPING = 0x23    # two-beat pulse at a frequency
DS5_EFFECT_MACHINE = 0x27      # alternating amplitudes at a frequency
TRAVEL_MAX = 192               # the pad's stroke scale, see legacy.py
ZONES = 10


def _zones(p):
    """(first, last) zone index of a DualSense zone mask, or None if empty."""
    mask = (p[0] | (p[1] << 8)) & 0x3FF
    if not mask:
        return None
    return (mask & -mask).bit_length() - 1, mask.bit_length() - 1


def _stroke(zone):
    return round(zone * TRAVEL_MAX / ZONES)


def _force(three_bits):
    """A packed DualSense force (stored as 0..7 for 1..8) on the pad's 1..255."""
    return (three_bits & 7) * 36 + 3


def translate_extra(type_, params):
    """(mode, params[5]) for the effects Flydigi's table skips, else None."""
    p = list(params) + [0] * 10
    zones = _zones(p)
    if zones is None:
        return None
    first, last = zones
    if type_ == DS5_EFFECT_BOW:
        travel = max(1, _stroke(last) - _stroke(first))
        return 3, [_stroke(first), travel, _force(p[2]), 0, 0]
    if type_ in (DS5_EFFECT_GALLOPING, DS5_EFFECT_MACHINE):
        # Two force fields either way: galloping's two feet, machine's two
        # alternating amplitudes. The pad has one strength, so the larger.
        strength = _force(max(p[2] & 7, (p[2] >> 3) & 7))
        return 2, [_stroke(first), 1, strength, max(1, p[3]), 0]
    return None


def normal_packet(side):
    return legacy.force_trigger_packet(SIDES[side], legacy.TRIGGER_MODE_NORMAL)


class TriggerRelay:
    def __init__(self, verbose=False):
        self.verbose = verbose
        self.seen = {}       # side -> last DualSense effect key, to skip repeats
        self.wanted = {}     # side -> packet the pad should be holding
        self.due = {}        # side -> pending send times for wanted[side]
        self.last_write = 0.0

    def _log(self, text):
        if self.verbose:
            print(text)

    def _write(self, link, side, packet):
        if link.vendor_fd is None:
            return False
        try:
            os.write(link.vendor_fd, packet)
        except OSError as exc:
            print("trigger write failed: %s" % exc, file=sys.stderr)
            link.drop("vendor_fd")
            return False
        return True

    def handle(self, link, effects, left_motor=0):
        """Forward the effects of one DualSense output report."""
        for effect in effects:
            key = effect.key()
            if self.seen.get(effect.side) == key:
                continue
            self.seen[effect.side] = key
            if effect.type == DS5_EFFECT_NONE:
                mapped = (legacy.TRIGGER_MODE_NORMAL, [0] * 5)
            else:
                mapped = translate_ds5(effect.side, effect.type, effect.params,
                                       left_motor)
                if mapped is None:
                    mapped = translate_extra(effect.type, effect.params)
            if mapped is None:
                # Logged regardless of verbosity: an unmapped pattern is a game
                # this relay does not cover yet, and the log is how to find out.
                print("%r -> unmapped, trigger unchanged" % (effect,))
                continue
            mode, params = mapped
            packet = legacy.force_trigger_packet(SIDES[effect.side], mode, params)
            self._log("%r -> mode %d params %s" % (effect, mode, params))
            # Different DualSense effects can land on the same Flydigi one;
            # the pad needs telling (three times) once.
            if self.wanted.get(effect.side) != packet:
                self.wanted[effect.side] = packet
                self._schedule(effect.side)

    def _schedule(self, side, now=None):
        now = time.monotonic() if now is None else now
        self.due[side] = [now + d for d in SEND_SCHEDULE_S]

    def pump(self, link, now=None):
        """Send whatever is due, at most one packet per WRITE_GAP_S.

        Called every loop iteration; cheap when there is nothing to do.
        """
        if not self.due or link.vendor_fd is None:
            return
        now = time.monotonic() if now is None else now
        if now - self.last_write < WRITE_GAP_S:
            return
        for side in sorted(self.due, key=lambda s: self.due[s][0]):
            times = self.due[side]
            if times[0] > now:
                continue
            if self._write(link, side, self.wanted[side]):
                self.last_write = now
                times.pop(0)
                if not times:
                    del self.due[side]
            return

    def reopened(self, link):
        """The vendor interface is new: whatever was sent before went nowhere."""
        for side in self.wanted:
            self._log("re-sending %s trigger effect after reconnect" % side)
            self._schedule(side)

    def reset(self, link=None):
        """Forget the game's effects, and clear them on the pad if it is there.

        Used on exit, and when a new virtual controller is created -- a fresh
        DualSense has no effects, so the pad must not keep the last session's.
        """
        self.seen.clear()
        self.wanted.clear()
        self.due.clear()
        # Synchronous, unlike everything else here: on exit there is no loop
        # left to pump a queue. Same repeat-and-space rule, so a lost packet
        # cannot leave a Lock behind.
        if link is not None:
            for _ in SEND_SCHEDULE_S:
                for side in SIDES:
                    self._write(link, side, normal_packet(side))
                    time.sleep(WRITE_GAP_S)
