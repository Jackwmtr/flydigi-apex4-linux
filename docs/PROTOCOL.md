# The Flydigi "old dialect", as measured on an Apex 4

Everything here was read off hardware: a Flydigi Apex 4 on its 2.4 GHz dongle,
dongle firmware `04 15`, CPU `wch ch573`, under Linux 7.1 (Bazzite). Where a
number is inherited from another model rather than measured, it says so.

The point of this document is that the numbers are the expensive part. The code
in this repository can be rewritten by anyone with the pad in front of them; the
constants took a session of turning a gamepad in the air and fitting ellipsoids
to the result.

## Which pads this is about

Flydigi speak two protocols. `IsOldProtocol()` in their own SDK is
`VendorId != 0x37D7`, so:

| Generation | USB ids | Reachable |
|---|---|---|
| Apex 5/6, Vader 5 | `37d7:2501`, `37d7:2401` | vendor HID collection, `5a a5` framing — see [openflydigi](https://github.com/mkaliaha/openflydigi) |
| **Apex 3/4, Vader 3/4, Direwolf 3/4** | `04b4:2412` (Cypress) or `045e:028e` | this document |

Model identity comes from a `DeviceType` byte and a short `DeviceCode`: the Apex 4
is **`DeviceType 84`, code `k2`** (`k2` is the Apex *4*, not the Apex 2).

## Interfaces

In HID mode the pad exposes four interfaces under `04b4:2412`:

| Interface | Usage | Contents |
|---|---|---|
| 0 | Gamepad | 9-byte report at 500 Hz: sticks 8-bit (X/Y/Z/Rz), 4-bit hat, 19 buttons, and two 8-bit Simulation-page axes (Brake/Accelerator) for the analogue triggers |
| 1 | Mouse | silent unless the pad's own gyro-mouse mode is on |
| 2 | **Vendor, usage page `0xFFA0`** | 32-byte `report id 0x04` at 1000 Hz — the IMU lives here |
| 3 | Vendor, usage page `0xFFEE` | `report id 0x05`, 63 bytes; not investigated (OTA?) |

Find interface 2 by its report descriptor prefix `06 a0 ff`, **not** by vendor and
product id: all four interfaces share those ids, and a command written to the
wrong one is accepted silently and does nothing.

## The IMU streams unconditionally

This is the finding that matters most, because the opposite was believed:
[SDL issue #10161](https://github.com/libsdl-org/SDL/issues/10161) was closed on
the understanding that an Apex 4 only reports sensors while its gyro-mouse mode
is enabled, and that there is no way to tell whether that mode is on.

Measured: with the mouse interface completely silent (gyro-mouse off), the vendor
stream carries all six axes at 1000 Hz, with no enable command of any kind, on the
dongle. Over 30 s at rest the gyro reads **exactly zero** in 27926 consecutive
frames — no bias, no dither.

One unexplained observation, recorded because it matters for any driver: early in
the session the same stream sat completely static for several minutes, then began
reporting and has done so reliably since. A driver should not assume the stream
cannot stop.

## Input report layout (`report id 0x04`, 32 bytes)

| Bytes | Field |
|---|---|
| 0 | report id `0x04` |
| 4–5 | gyro yaw, 12-bit copy (byte 4 low, low nibble of byte 5 high) |
| 7 | paddle flags: bits **3, 5, 4, 2** are M1..M4 **left to right** (mask `0x3C`) |
| 8 | bit 3 = Home key |
| 9, 10 | button flags; byte 10 bit 4 = L2 pressed, bit 5 = R2, bit 6 = L3, bit 7 = R3 |
| 11:12, 13:14, 15:16 | accelerometer X, Y, Z — int16 LE |
| 17, 19 | right stick X, Y (8-bit, `0x7f` centre) |
| **18, 20** | gyro yaw, full int16 — **discontinuous**: byte 18 is the low half, byte 20 the high half |
| 21, 22 | left stick X, Y |
| 23, 24 | L2, R2 analogue, 0..255 |
| 26:27 | gyro pitch (rotation about the accel X axis) |
| 29:30 | gyro roll (rotation about the accel Y axis) |

Two traps in there. The **paddle bit order is not the button order** — pressing
M1..M4 left to right lights bits 3, 5, 4, 2. And the **Home key is not a gamepad
button at all**: the pad reports it through the descriptor's Consumer page, so it
arrives on evdev as `KEY_RED` (0x18E) and `BTN_MODE` stays empty forever.

For reference, the same four paddles reach evdev as `BTN_TRIGGER_HAPPY1`,
`BTN_TRIGGER_HAPPY3`, `BTN_TRIGGER_HAPPY2` and `BTN_DEAD` — another reason to read
them from the vendor report instead.

## Bluetooth is a different pad, and a dead end for sensors

Paired over Bluetooth in DInput mode the same hardware arrives as a **single** HID
device on bus 5 (`0005:04b4:2412`, "Flydigi APEX 4") with a 163-byte descriptor
and **no vendor collection at all**. The IMU lives in the vendor interface, so
there is nothing to read it from, and rumble goes the same way: its command is a
write to an interface that is not there.

Two more things measured rather than assumed:

* **The axes change sign.** Sticks are `-128..127` over Bluetooth and `0..255`
  through the dongle, with the same pad resting one step below the arithmetic
  middle either way (`-1` and `127`). Anything hard-coding a neutral of 128 pins
  the sticks to a corner over Bluetooth — read `EVIOCGABS` instead.
* **The pad only transmits on input change.** In a 180-second capture, 40 seconds
  of continuous rotation produced *zero* packets; all 526 arrived in the eleven
  seconds when sticks and triggers were being moved. So even a sensor field that
  exists is only sampled when something else happens, which is useless for aiming.

Polling instead of waiting does not help: `HIDIOCGINPUT` on report id 1 succeeds
and returns an all-zero buffer — not a state snapshot — and takes ~315 ms per call.

**An undeclared tail, unexplained.** The Bluetooth report is 21 bytes where the
descriptor accounts for 15. Bytes 15–18 hold two 16-bit values that look like
sensors (one sits near 4096, which would be 1 g at a Vader-era scale), byte 19 is
a constant `0xa5` — the old dialect's own framing magic — and byte 20 a constant
1. The kernel ignores all of it; hidraw sees it. What it is remains open, and the
"only on input change" behaviour is what makes it hard to find out.

## Command channel

Out: 12 bytes, `[0x05, cmd, args...]`, written to interface 2.

Replies do **not** come back as a report of their own. They arrive inside the same
`0x04` input stream, identified by the **command echo in byte 15**. Anything that
treats byte 15 as input data will see phantom activity; anything waiting for a
separate reply report will wait forever.

| Command | Effect |
|---|---|
| 236 (`0xEC`) | device info — reply below |
| 17 (`0x11`) | dongle version — reply has `p[0]=4, p[1]=17`, then two version bytes |
| 15 (`0x0F`) | rumble: `[0x05, 0x0F, left, right]`, each 0..255 |
| 235, 234, 231, 229, 51 | config blob transfer (see flydigictl) |

Device info reply (`p[15] == 236`), as measured on this pad:

| Byte | Field |
|---|---|
| 3 | `DeviceType` (84 = Apex 4) |
| 5–8 | MAC |
| 9, 10 | firmware |
| 11 | **battery level 0..5**, with 6 meaning "charging" |
| 12 | CPU type (2 = `wch ch573`) |
| 14 | connection type (2 = wireless/dongle) |

Battery is a **level, not a percentage**. Reading it as a percentage is why this
pad appeared to sit at "4%" all session while its own display showed nearly full,
and it is the same mistake behind flydigictl's issue #5. Note also that connection
type is at byte 14 here, one along from where a Vader-era map puts it.

## Calibration

### Accelerometer

Axis-aligned ellipsoid fit over 614k resting samples from three captures, using
the only constraint available — gravity has the same length in every orientation.
Residual |a| came out **1.0000 with a standard deviation of 0.0024**.

| Axis | LSB per g | Zero offset |
|---|---|---|
| X | 792.2 | −6.1 |
| Y | 803.5 | **−98.0** |
| Z | 792.2 | +13.0 |

Not 4096 per g, as the Vader 3 Pro reports, and **not a single scale for all three
axes**. The large Y offset also means the pad reads about +0.12 g on Y while lying
"flat": it rests tilted back some 7 degrees on its curved underside. That is the
pad's attitude, not an error to remove.

Two hand estimates that were wrong and are recorded so nobody repeats them: a
common 790 for all axes, and a Y offset of −57 taken from two poses whose gravity
magnitude was visibly off (704 and 894 against 800). That magnitude error *was*
the Y offset.

### Gyroscope

| Axis | Field | deg/s per LSB | Anchored by |
|---|---|---|---|
| pitch (about X) | `[26:27]` | 0.377 | accel sweep through gravity of 365° |
| roll (about Y) | `[29:30]` | 0.114 | accel sweep of 359° |
| yaw (about Z) | `[18]`+`[20]` | 0.400 | two hand-made 360° turns, slow and fast, agreeing within 2% |

**The three axes do not share a scale** — roll is 3.3× finer than the other two.
Two of the three are anchored by the accelerometer's own rotation through gravity,
which is independent of how accurately a hand turn was made; yaw cannot be
anchored that way, because rotating about the gravity axis does not move gravity.

Slow and fast turns gave the same scale, so the firmware does not clip the top of
the range.

### Signs

The pad's accelerometer frame is right-handed: **X left, Y toward the player,
Z up**, each fixed by gravity in a measured pose.

Its gyro does **not** follow the right-hand rule of that frame. A world vector
seen from a rotating frame obeys `dg/dt = -w x g`, so gravity must sweep *against*
the rotation; over a full turn about X the gyro integrated to −365.4° while gravity
swept −365.1°, and about Y, −360.2° against −359.1°. Same sign where opposite was
required, on two independent axes.

That establishes the axes disagree with each other. It does **not** establish how
they should land in a consumer's frame, and treating it as though it did was wrong
twice: yaw came out inverted under Steam's gyro-to-mouse, and pitch came out
inverted in an actual game. The signs in use are therefore empirical:

| Axis | Sign | How |
|---|---|---|
| pitch | + | in-game (aiming up looked down with the derived sign) |
| yaw | + | Steam gyro-to-mouse cursor direction |
| roll | − | **unconfirmed** — games rarely roll a camera |

## Emulating a DualSense with this

Notes that cost time, for anyone taking the same route:

* `hid-playstation` reads feature reports at probe. They must be served **with the
  report id as the first byte** and at the exact expected length, or probe fails
  with `Invalid byte count transferred, expected 20 got 19`.
* udev rules for the virtual device's input sub-devices must be numbered **below
  73**: `TAG+="uaccess"` only sets a tag, and what acts on it is systemd's own
  `73-seat-late.rules`. A `99-` file sets the tag after the rule that reads it.
* The kernel hard-codes gyro bias to 0 when it parses the calibration blob, but
  **SDL does not** — it computes `(value - bias) * sensitivity` itself. Serving a
  blob captured from a real DualSense hands a game that unit's offsets: a yaw bias
  of 10 became a permanent 0.6 deg/s drift on yaw and nothing else.
* The DualSense timestamp is in units of ⅓ µs (the kernel divides deltas by 3).
* Rumble: forward each output report once. The device holds the level until told
  otherwise, exactly like real hardware. Re-asserting it periodically turns a
  missed stop into rumble that outlives the game, Steam, and the pad being
  switched off — and a watchdog instead of that truncates legitimate long effects.
  Recognise the stop properly: Steam sends a report with **no validity flags and
  zero motors**, which a strict flag check reads as "no information".

## What is not known

* **The adaptive-trigger command family for `k2`.** The pad has ForceAdapt
  triggers; nothing here drives them. Flydigi's SDK gates them on a device code,
  and the numbers for `k2` are not in any public source. This is the one large gap.
* **The roll sign** in a consumer's frame.
* **Bluetooth modes** — untested; the pad almost certainly speaks something else
  there.
* **Byte 13** of the device-info reply, and most bits of bytes 9 and 10.
* **Why the vendor stream was once static** for minutes.
* Everything about **other old-dialect models**. The framing is shared; the scales
  and offsets are per-model and must be measured. `tools/` is how.
