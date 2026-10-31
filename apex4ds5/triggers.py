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

* **Changes are rationed; repeats are not.** Every *change* of effect freezes
  the pad's sticks for ~50 ms -- measured with R2 held and the right stick
  spinning: 349 stick events/s with no effect, 246 with an effect changing
  5 times a second and gaps of 56 ms, while the *same* packet sent 5 times a
  second cost nothing (12 ms worst gap). Any mode, race as much as sniper.
  Ghostwire: Tokyo ramps a vibration's frequency every ~20 ms, up to 39
  changes a second, which froze the right stick most of the time it fired.
  So a change of mode -- the shot, the release -- goes out at once, but no
  two changes closer than MODE_GAP_S; a change of parameters within the same
  mode waits, and then sends whatever is newest: PARAM_FAST_S after that
  side's last change if some parameter moved by more than a quarter, else
  PARAM_INTERVAL_S. A ramp becomes a few steps; the sticks stay live.

  The two speeds are not decoration. A flat 500 ms made effects feel weaker:
  Ghostwire's ramps start near zero frequency, so the first value of a ramp --
  the one a mode change sends -- was held for half a second, and short bursts
  never left it. Replayed against a recorded session, the pad's frequency sat
  18% below the game's on average with a flat 500 ms, 12% with the two speeds,
  for about the same number of changes (61 against 55; 157 unrationed).
"""
import os, sys, time

from . import legacy
from ._ds5.trigger_map import translate_ds5

SIDES = {"left": legacy.SIDE_LEFT, "right": legacy.SIDE_RIGHT}

# When to repeat an effect after sending it -- repeats of an identical packet
# do not disturb the pad, see above.
SEND_SCHEDULE_S = (0.0, 0.1, 0.5)
WRITE_GAP_S = 0.01
# Rationing of changes, see above. Each change costs ~50 ms of frozen sticks.
MODE_GAP_S = 0.1
PARAM_INTERVAL_S = 0.5
PARAM_FAST_S = 0.15
SIGNIFICANT = 0.25             # relative change that earns PARAM_FAST_S

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
    def __init__(self, verbose=False, writer=None, param_interval=PARAM_INTERVAL_S):
        self.verbose = verbose
        self.writer = writer
        self.param_interval = param_interval
        self.seen = {}       # side -> last DualSense effect key, to skip repeats
        self.wanted = {}     # side -> (mode, packet) the game last asked for
        self.applied = {}    # side -> (mode, packet) last sent to the pad
        self.changed_at = {} # side -> when applied[side] was first sent
        self.repeats = {}    # side -> pending repeat times for applied[side]
        self.last_write = 0.0
        self.last_change = 0.0

    def _log(self, text):
        if self.verbose:
            print(text)

    def _write(self, link, side, packet):
        if link.vendor_fd is None:
            return False
        # Through the writer thread while the relay runs, so a trigger write
        # never stalls the loop that feeds the game; directly once it is gone.
        if self.writer is not None:
            self.writer.submit("trigger-" + side, packet)
            return True
        try:
            os.write(link.vendor_fd, packet)
        except OSError as exc:
            print("trigger write failed: %s" % exc, file=sys.stderr)
            link.drop("vendor_fd")
            return False
        return True

    def handle(self, link, effects, left_motor=0):
        """Take in the effects of one DualSense output report; pump() sends."""
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
            self.wanted[effect.side] = (mode, packet)

    def _change_allowed(self, side, now):
        """May wanted[side] replace what the pad holds, now?"""
        if now - self.last_change < MODE_GAP_S:
            return False
        applied = self.applied.get(side)
        wanted = self.wanted[side]
        if applied is None or applied[0] != wanted[0]:
            return True                          # a new mode: at once
        since = now - self.changed_at.get(side, 0.0)
        if since >= self.param_interval:
            return True
        # Bytes 6..10 are the five mode parameters. A small absolute floor, so
        # that 1 -> 2 at the very bottom of a ramp is not "a doubling".
        big = any(abs(a - b) > max(SIGNIFICANT * max(a, b), 4)
                  for a, b in zip(applied[1][6:11], wanted[1][6:11]))
        return big and since >= min(PARAM_FAST_S, self.param_interval)

    def pump(self, link, now=None):
        """Send what is due, at most one packet per WRITE_GAP_S.

        Called every loop iteration; cheap when there is nothing to do.
        """
        if link.vendor_fd is None:
            return
        now = time.monotonic() if now is None else now
        if now - self.last_write < WRITE_GAP_S:
            return
        for side, wanted in self.wanted.items():
            if self.applied.get(side) != wanted and self._change_allowed(side, now):
                if self._write(link, side, wanted[1]):
                    self.applied[side] = wanted
                    self.changed_at[side] = self.last_change = now
                    self.last_write = now
                    self.repeats[side] = [now + d for d in SEND_SCHEDULE_S[1:]]
                return
        for side, times in list(self.repeats.items()):
            if times and times[0] <= now:
                if self._write(link, side, self.applied[side][1]):
                    self.last_write = now
                    times.pop(0)
                return

    def reopened(self, link):
        """The vendor interface is new: whatever was sent before went nowhere."""
        for side in self.wanted:
            self._log("re-sending %s trigger effect after reconnect" % side)
        self.applied.clear()
        self.repeats.clear()

    def reset(self, link=None):
        """Forget the game's effects, and clear them on the pad if it is there.

        Used on exit, and when a new virtual controller is created -- a fresh
        DualSense has no effects, so the pad must not keep the last session's.
        """
        self.seen.clear()
        self.wanted.clear()
        self.applied.clear()
        self.repeats.clear()
        # Synchronous, unlike everything else here: on exit there is no loop
        # left to pump a queue. Same repeat-and-space rule, so a lost packet
        # cannot leave a Lock behind.
        if link is not None:
            for _ in SEND_SCHEDULE_S:
                for side in SIDES:
                    self._write(link, side, normal_packet(side))
                    time.sleep(WRITE_GAP_S)
