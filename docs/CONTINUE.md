# Where this stands, and how to pick it up

Written so that this can be continued cold — by a person, or by a model in a new
session with no memory of how any of it was found. Read
[PROTOCOL.md](PROTOCOL.md) for the pad, [DUALSENSE.md](DUALSENSE.md) for the
emulation side, [DSX.md](DSX.md) for the unfinished part.

## What works today

Apex 4 on its 2.4 GHz dongle, presented to games as a DualSense:

* gyro on all three axes, analogue triggers, sticks, hat, face buttons, shoulders,
  stick clicks, Home as the PS button
* the four back paddles as real buttons, by presenting a DualSense **Edge** --
  same feature reports, one different product id, four bits in a byte already
  being written. Confirmed in Steam, which shows an Edge and binds all four
* rumble in both directions, two motors independently
* survives the pad sleeping, being switched off and coming back
* settings in `~/.config/flydigi-apex4/config.json`; flags override it

Verified on hardware: `./install.sh --check` reports gravity reading 1.00 g, which
exercises the whole chain rather than a file list.

## What does not

| | |
|---|---|
| Adaptive triggers | the command family for `k2` is unknown — [DSX.md](DSX.md) is the map |
| Bluetooth | no gyro, no rumble, and it cannot be fixed: no vendor interface, and the pad only transmits on input change |
| Other old-dialect pads | Vader 3/4, Direwolf 3/4, Apex 3 share the framing; the constants are per-model and must be measured |

## Method, because the numbers are the product

Anyone extending this to another pad should copy the method, not the constants.

**Anchor to physics, not to your own hands.** Gyro scales were obtained by turning
the pad a full circle and integrating — but a hand-made turn is not exactly 360°,
so the number is only as good as the turn. Two of the three axes were re-anchored
against the accelerometer: rotating about any horizontal axis sweeps gravity through
the same angle, and that sweep is independent of how well the turn was made. It
came out at 365° and 359° for two axes, confirming both scales at once. Yaw cannot
be done this way — rotating about gravity does not move gravity — so it stays the
least certain number here.

**Fit, don't eyeball.** The accelerometer was calibrated by an axis-aligned
ellipsoid fit over 614k resting samples, using only the constraint that gravity has
one length. It found a per-axis scale (792.2 / 803.5 / 792.2 LSB per g) and, more
usefully, a −98 LSB offset on Y that hand-reading of static poses had estimated as
−57 from two poses whose magnitude was visibly wrong. Residual |a| = 1.0000 ± 0.0024.

**Signs are not derivable.** Handedness analysis tells you whether a pad's own axes
agree with each other; it does not tell you how they should land in a consumer's
frame. Two of the three derived signs turned out inverted in practice (roll's
happened to be right). Fix them in a game, or with Steam driving gyro-to-mouse —
a controller test page's icons are too small to see a sign error, which is how one
of them survived a whole session.

**Check the consumer you actually care about.** The kernel and SDL are different
readers of the same virtual controller and they disagree in both directions: SDL
applies calibration offsets the kernel throws away (which produced a phantom yaw
drift), and it parses the Edge's extra buttons that this machine's kernel never
registered on its evdev node. Testing through the kernel's nodes alone would have
called one of those a success and the other a failure, wrongly.

**Watch out for interpretation errors that look like hardware faults.** A battery
byte read as a percentage said "4%" for a session while the pad's own display showed
nearly full: it is a 0..5 level. And the pad's Y accelerometer offset means it reads
+0.12 g on Y while "flat", because it rests tilted back on its own curved underside.

## The measurement kit

`tools/`, all standard-library Python:

| Tool | Use |
|---|---|
| `selftest.py` | the whole chain, one command; also `./install.sh --check` |
| `apex4-probe.py` | list hidraw nodes, dump descriptors, flag the vendor collection |
| `apex4-raw.py` | capture a stream to a file (timestamp + payload) |
| `apex4-windows.py`, `apex4-classes.py`, `apex4-decode.py` | slice a capture by time, by frame class, or decode it under the known layout |
| `accel-fit.py` | the ellipsoid fit — feed it several captures |
| `apex4-gyroscale.py` | integrate rotations; `--` compares against the accel sweep |
| `tilt-analyse.py`, `pose-sign.py` | static poses, for scales and signs |
| `drift-check.py`, `ts-check.py` | is the gyro really zero at rest; does the DS5 timestamp advance at real time |
| `button-watch.py` | log evdev codes and vendor bits side by side — how the Home key and the paddle bit order were found |
| `motion-read.py` | read the kernel's DualSense motion node in physical units |
| `ff-test.py`, `rumble-off.py` | rumble through the kernel; silence the motors |

A capture is worth more than a live experiment: the same recording can be re-sliced
when a hypothesis changes, and several of the findings here came from re-reading old
captures rather than taking new ones.

## Next steps, in the order they are worth doing

1. **An SDL patch.** `SDL_hidapi_flydigi.c` already recognises the Apex 4 and
   already opens the interface the IMU is in; it just does not set
   `sensors_supported` or parse the sensors, on the belief that they only stream
   with gyro-mouse on ([issue #10161](https://github.com/libsdl-org/SDL/issues/10161)).
   Measured here, they stream unconditionally. That patch gives gyro to every SDL
   game and to Steam Input with no emulation, no udev rules and no daemon — it makes
   most of this repository unnecessary for the common case, which is the point.
   Use the empirical signs, and say in the PR that roll is unconfirmed.
2. **Adaptive triggers.** [DSX.md](DSX.md). A day or two, needs Windows for the
   capture. Check the config API first — it may hand over the semantics for free.
3. Later, if wanted: a GUI whose value is *live sensor and button inspection* for
   measuring other pads (a settings panel would only duplicate the config file), a
   Decky plugin for handheld installs, and per-model constants for the other
   old-dialect pads.

## Environment this was developed on

* Bazzite (Fedora atomic), kernel 7.1.8, user `deck`, on a desktop machine.
* Pad on its 2.4 GHz dongle and, later, over a cable -- `04b4:2412` either way,
  firmware `04 15`, CPU `wch ch573`. The product string differs between the two
  ("Flydigi VADER3" vs "Flydigi APEX 4"), so match on ids, never on the name.
* Relay under `systemd-run --user`; logs in the user journal.
* An Apex 5 was **not** available. Where this document says something about the
  newer generation, it comes from openflydigi, not from measurement here.
