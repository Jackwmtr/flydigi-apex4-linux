# SPDX-License-Identifier: MIT
"""Settings file, so that nobody has to edit code to move a paddle.

JSON rather than TOML on purpose: `tomllib` only arrived in Python 3.11, and this
has to run on whatever a Steam Deck or an LTS distribution ships. The whole
project has no dependencies and that is worth keeping -- on an immutable system a
`pip install` line in the instructions costs somebody an evening.

Precedence is defaults < config file < command-line flags, so a flag can always
be used to try something out without touching the file.
"""
import json
import os

APP = "flydigi-apex4"
DEFAULTS = {
    # Which controller to present: "dualsense" or "dualsense-edge". The Edge has
    # four extra buttons of its own, so paddles can map to real buttons there
    # instead of being folded into touchpad halves and stick clicks.
    "emulate": "dualsense-edge",
    # What the four back paddles do, in physical order left to right.
    # Any pad: tp-left, tp-right, l3, r3, none
    # Edge only: paddle-left, paddle-right, fn1, fn2
    "paddles": ["paddle-left", "fn1", "fn2", "paddle-right"],
    # Pad axes -> DualSense axes. A leading minus inverts that axis.
    "gyro_map": "pitch,yaw,roll",
    "accel_map": "-x,z,y",
    # DualSense input report rate, Hz.
    "rate_hz": 250,
    # Log every output report from the game, and every rumble level sent on.
    "verbose": False,
}


def path(explicit=None):
    if explicit:
        return os.path.expanduser(explicit)
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, APP, "config.json")


def load(explicit=None):
    """Defaults merged with the config file. Returns (settings, source)."""
    settings = dict(DEFAULTS)
    target = path(explicit)
    try:
        with open(target) as handle:
            stored = json.load(handle)
    except FileNotFoundError:
        return settings, None
    except ValueError as exc:
        # A broken file is worth complaining about rather than silently
        # falling back: someone edited it and expects the edit to matter.
        raise SystemExit("%s: %s" % (target, exc))
    if not isinstance(stored, dict):
        raise SystemExit("%s: expected an object at the top level" % target)
    unknown = sorted(set(stored) - set(DEFAULTS))
    if unknown:
        print("%s: ignoring unknown key(s): %s" % (target, ", ".join(unknown)))
    settings.update({k: v for k, v in stored.items() if k in DEFAULTS})
    return settings, target


def write_default(explicit=None, force=False):
    """Write a commented-by-example config, without clobbering an existing one."""
    target = path(explicit)
    if os.path.exists(target) and not force:
        return target, False
    os.makedirs(os.path.dirname(target), exist_ok=True)
    with open(target, "w") as handle:
        json.dump(DEFAULTS, handle, indent=2)
        handle.write("\n")
    return target, True
