# SPDX-FileCopyrightText: 2026 Mikalai Kaliaha
#
# SPDX-License-Identifier: MIT

"""DualSense trigger effect -> Flydigi effect.

Vendored from openflydigi's flydigi/relay.py (translate_ds5), unchanged apart
from taking the effect's fields directly. Its own note, kept because it is the
reason the constants below must not be "cleaned up":

Transcribed from Flydigi's own PS5DataManager.ProcessDataWithResult rather
than guessed. Theirs is not a general conversion: it recognises the specific
byte patterns particular games emit and maps each to a hand-tuned effect, so
the odd-looking constants below are deliberate.

Two behaviours worth preserving:
  * An unrecognised effect type yields None -- the trigger is left as it is.
    Flydigi leaves their mode byte at 0xFF (invalid) and applies nothing.
    Falling back to "normal" instead would clear effects the game never asked
    to clear.
  * Left and right are genuinely asymmetric. Right type 37 pattern-matches in
    detail; left type 37 is a single mapping. This mirrors the original.

Parameter indices are into the 10-byte effect parameter block, as
ds5.parse_output() hands it over. The output modes are 0-3 only: Flydigi's
DualSense path never emits lock or vibration.
"""


def _pad5(values):
    out = [int(v) & 0xFF for v in values[:5]]
    return out + [0] * (5 - len(out))


def translate_ds5(side, type_, params, left_motor=0):
    """(mode, params[5]) for a DualSense effect, or None if unhandled.

    `left_motor` is the last motor_left value seen, which Flydigi stashes and
    reuses for one left-trigger case.
    """
    p = list(params) + [0] * 10          # tolerate short blocks
    t = type_

    if side == "right":
        if t == 1:
            return 1, _pad5([p[0], p[1]])
        if t == 2:
            return 3, _pad5([p[0], p[1], p[2]])
        if t == 5:
            return 0, _pad5([])
        if t == 6:
            return 2, _pad5([p[2], p[1], p[1], p[0]])
        if t == 33:
            if p[0] == 0xFF and p[1] == 3 and p[2] == 0xFF:
                return 1, _pad5([110, 50, 0])
            if p[0] == 0:
                return 1, _pad5([120, 1])
            if p[0] == 0xFF and p[1] == 3:
                return 1, _pad5([1, 64])
            return 1, _pad5([1, 1])
        if t == 37:
            if p[0] == 20:
                if p[2] == 2:
                    return 3, _pad5([70, 20, 20, 0])
                if p[2] == 6:
                    return 3, _pad5([70, 60, 20, 0])
                if p[2] == 1:
                    return 3, _pad5([20, 10, 20, 0])
                if p[2] == 3:
                    return 3, _pad5([50, 30, 1, 0, 1])
                return 2, _pad5([50, 1, 10, 10, 10])
            if p[0] == 12:
                return 3, _pad5([70, 0, 12, 0])
            if p[0] == 36 and p[2] <= 6:
                return 3, _pad5([10, 36, 10 + p[2] * 10, 0])
            if p[0] == 68:
                return 3, _pad5([70, 50, 68, 0])
            if p[0] == 4 and p[1] == 1 and p[2] in (5, 7):
                return 3, _pad5([80, 200, 90, 0])
            if p[0] == 64 and p[1] == 1 and p[2] == 3:
                return 3, _pad5([120, 150, 60, 0])
            # includes the p[0]==72,p[1]==0,p[2]==4 case, identical to default
            return 3, _pad5([64, p[0], 0, p[2], 1])
        if t == 38:
            return 2, _pad5([255 - p[0], 1, ((p[1] + 1) * 30) & 0xFF, p[8]])
        return None

    # left trigger, from Flydigi's switch on data[22]
    if t == 1:
        return 1, _pad5([p[0], p[1]])
    if t == 2:
        return 3, _pad5([p[0], p[1], p[2]])
    if t == 5:
        return 0, _pad5([])
    if t == 6:
        return 2, _pad5([p[2], p[1], p[1], p[0]])
    if t == 33:
        if p[0] == 0:
            out = [120, 1, 0, 0, 0]
        elif p[0] == 252 or (p[0] == 192 and p[1] == 3):
            out = [1, 96, 0, 0, 0]
        else:
            out = [0, 1, 0, 0, 0]
        # these two run after the branch above and may override it
        if p[1] == 3:
            out[0], out[1] = 140, (p[5] + 1) & 0xFF
        if p[0] == 128:
            out[0], out[1] = 128, p[4]
        return 1, _pad5(out)
    if t == 37:
        return 3, _pad5([64, p[0], 0, p[2], 1])
    if t == 38:
        if p[0] == 240 and p[1] == 3 and p[3] == 0:
            return 1, _pad5([30, left_motor])
        if p[0] == 0xFF and p[1] == 3 and p[3] == 0xFF:
            return None                      # Flydigi marks this invalid
        if p[2] == 0:
            strength = ((p[1] + 1) * 30) & 0xFF
        else:
            strength = max(p[2], p[3], p[4], p[5])
        return 2, _pad5([255 - p[0], 1, strength, p[8]])
    return None
