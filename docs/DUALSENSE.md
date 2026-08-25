# Emulating a DualSense on Linux

What a host has to get right for `hid-playstation` to adopt a virtual device as a
real DualSense, and for a game to then read it correctly. All of it was found the
hard way while building the relay in this repository; each item below cost a
debugging session.

## Creating the device

`/dev/uhid`, `UHID_CREATE2`, with Sony's ids — vendor `0x054C`, product `0x0CE6`
— the real controller's 289-byte report descriptor, and `bus = BUS_USB`. The
descriptor and the feature blobs in `apex4ds5/_ds5/ds5_usb.py` were captured off
real hardware by the openflydigi project; inventing them does not work, because
the host compares bytes.

`/dev/uhid` is often already writable: on Fedora-derived systems (Bazzite, Aurora)
it comes up accessible, elsewhere it needs a udev rule.

## Feature reports, and the length trap

At probe, `hid-playstation` reads three feature reports and **detaches if any of
them fails**:

| Report | Size incl. id | Contents |
|---|---|---|
| `0x05` | 41 | gyro and accel calibration |
| `0x09` | 20 | pairing info, including the MAC |
| `0x20` | 65 | firmware info |

They must be answered **with the report id as the first byte**. The blobs are
stored without it, so whoever serves them prepends it exactly once. Getting this
wrong produces exactly one line in the kernel log and nothing else:

```
playstation 0003:054C:0CE6.0016: Invalid byte count transferred, expected 20 got 19
playstation 0003:054C:0CE6.0016: Failed to retrieve DualSense pairing info: -22
```

## Calibration: the kernel and SDL disagree, and both matter

The kernel parses report `0x05` in `ds_get_calibration_data()` and normalises
sensors to `1/1024` deg/s and `1/8192` g. Two details decide what a game sees:

* **The kernel hard-codes gyro bias to 0.** It reads the bias fields and then
  ignores them.
* **SDL does not.** `HIDAPI_DriverPS5_ApplyCalibrationData()` computes
  `(value - bias) * sensitivity` itself, from the same blob.

So a blob captured from somebody's real DualSense hands a game *that unit's*
offsets. The one in this repository carried a gyro yaw bias of 10, which became a
permanent ~0.6 deg/s drift on yaw and nothing else — invisible through the kernel's
own motion node, obvious in a game. The relay therefore rewrites the blob: zero
every offset, and make each plus/minus pair symmetric at its existing magnitude so
the *scales* survive untouched.

Derive the units from the blob rather than hard-coding them. With the blob here:

| | Per unit |
|---|---|
| gyro | ~16.37 raw per deg/s (`denominator / speed_2x`) |
| accel | ~8192 raw per g, offset 0 |

An older openflydigi comment says 10000 raw per g, citing inputtino; the blob
shipped in that same project implies 8192, so anything following the comment reads
about 22% low.

## Pretending to be an Edge instead, for real paddle buttons

A plain DualSense has nowhere to put a pad's back paddles, which is why they end
up folded into touchpad halves and stick clicks. A **DualSense Edge** has four
buttons of its own, and as far as everything downstream is concerned an Edge *is*
a DualSense with a different product id:

| | |
|---|---|
| Product id | `0x0DF2` instead of `0x0CE6` |
| Extra feature reports | **none** — the same three, unchanged |
| Extra buttons | bits 4–7 of the same `buttons[2]` byte (report offset 10): FN1 `0x10`, FN2 `0x20`, left paddle `0x40`, right paddle `0x80` |

So the switch costs one id and four bits, and the pad's four paddles become real
buttons that Steam and games can bind — strictly better than the touchpad-click
trick. `hid-playstation` sets its internal `is_edge` purely from the product id
and asks for nothing else, and the descriptor served can stay the plain DualSense
one.

**Check the right consumer.** On the machine this was built on, the kernel bound
the device as `054C:0DF2` but did *not* register `BTN_TRIGGER_HAPPY1..4` on its
evdev node — and Steam showed the Edge with all four buttons working anyway,
because SDL reads the controller over hidraw and parses those bits itself. A
capability check on the kernel's node therefore proves nothing either way about
what a game will see.

## Input report

Report id `0x01`, 64 bytes. What the relay fills in:

| Offset | Field |
|---|---|
| 1–4 | left X, left Y, right X, right Y (0..255, `0x80` centre) |
| 5, 6 | L2, R2 analogue |
| 7 | sequence counter |
| 8 | hat in the low nibble, face buttons in the high nibble |
| 9 | L1, R1, L2, R2, Create, Options, L3, R3 |
| 10 | PS, touchpad, mic mute |
| 16–21 | gyro ×3 then accel ×3, signed 16-bit LE |
| 28–31 | sensor timestamp, 32-bit LE |
| 33–36, 37–40 | two touch points |
| 53 | battery level in the low nibble, status in the high |

**The timestamp is in units of ⅓ µs** — the kernel divides deltas by 3 to get
microseconds. Feed `monotonic_us * 3`. Leaving it at zero makes the motion device
look dead even while values change; getting the factor wrong mis-scales anything
that integrates rate over time, which is all gyro aiming.

**Touch points** are `contact, x_lo, (y_lo << 4) | x_hi, y_hi` with the touchpad
1920 × 1080. Bit 7 of `contact` set means *no* contact. The DualSense touchpad is
one physical button, so "left click" and "right click" are the same button with the
contact on one side or the other — which is how this repository turns two back
paddles into two clicks.

## Output reports: rumble, and how to stop it

Report `0x02` over USB (`0x31` over Bluetooth). Motor levels sit at `base+2` and
`base+3`, valid when flag0 has `MOTOR` or `USE_RUMBLE_NOT_HAPTICS`, or flag2 has
`COMPATIBLE_VIBRATION`.

Three things, all learned by getting them wrong:

1. **Forward each report once.** The device holds the level until told otherwise,
   exactly like real hardware.
2. **Do not re-assert a held level.** Re-sending it periodically so a long effect
   "cannot fade" turns a missed stop into rumble that outlives the game, Steam,
   and the pad being switched off — the refresh loop becomes the only thing driving
   it, so nothing the user closes makes it stop.
3. **Do not use a watchdog instead.** Measured: the kernel sends a level once and
   its stop only when the effect ends, so a one-second timeout cut a two-second
   effect in half.

Recognise the stop properly instead. A stop normally arrives with the motor
validity flags set and both levels zero. **Steam sends something else**: a report
with *no* validity bits at all and zero motors, which a strict flag check reads as
"no information" — and that is how rumble gets stuck on. Reports that do carry
other validity bits (lightbar, mic LED) with zero motors are *not* stops: a game
sends those in the middle of a legitimate long rumble.

Also zero the motors when the relay exits, and note that systemd's SIGTERM skips
`finally` unless a handler turns it into an exception.

## udev, and a rule that silently does nothing

systemd tags the main gamepad node for seat access by itself, but leaves the
motion-sensor, touchpad and headset-jack nodes as `root:input`. So gyro is
unreadable by the user and touchpad-click is silently dead — that event is
reported on the touchpad node, not the gamepad one.

```
SUBSYSTEM=="input", ATTRS{id/vendor}=="054c", ATTRS{id/product}=="0ce6", TAG+="uaccess"
```

**The file must be numbered below 73.** `TAG+="uaccess"` only sets a tag; what
acts on it is systemd's own `73-seat-late.rules`. A `99-` file sets the tag after
the rule that would have read it, so nothing happens at all — and the failure looks
like a permissions bug rather than an ordering one.

## Living beside the real pad

A game sees both the physical pad and the virtual DualSense. Two ways out:

* per-game: `SDL_GAMECONTROLLER_IGNORE_DEVICES=0x04b4/0x2412` **and**
  `SDL_JOYSTICK_IGNORE_DEVICES=0x04b4/0x2412` — both spellings, because SDL3
  renamed the hint and an application ignores the one it does not know;
* system-wide: the same variables in `~/.config/environment.d/`, which is what
  `install.sh --hide-pad` writes. Steam then offers only the virtual controller
  and Steam Input can stay on. Steam must be restarted to pick it up.

Note that with the pad hidden and the relay stopped there is no controller at all,
so this belongs together with the autostart unit.

Steam will happily wrap the virtual DualSense in Steam Input and re-emulate it as
an Xbox 360 pad — which is fine, but it masks DS5 semantics, so adaptive triggers
and native PS5 handling need Steam Input off for that game.

## Surviving the pad going away

A pad that sleeps or is switched off takes its hidraw and evdev nodes with it and
comes back under different numbers. Keep the uhid device alive across that: freeze
the readings, re-open the nodes when they reappear, and report sticks as neutral
in the meantime rather than latching the last value. A relay that dies with the
pad takes the controller the game is holding with it.
