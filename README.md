# flydigi-legacy-ds5

Gyroscope and analogue triggers from a **Flydigi Apex 4** on Linux, by presenting
it to games as a DualSense.

Flydigi's older pads (Apex 3/4, Vader 3/4, Direwolf 3/4) carry a 6-axis IMU that
nothing on Linux reads. SDL recognises the Apex 4, its paddles and its rumble, but
not its sensors; Flydigi's own Windows app is the only thing that ever exposed
them, and openflydigi — the good Linux tool for these pads — covers the *newer*
protocol generation only. So the sensors sit in a vendor HID interface that is
already open and nobody parses.

This reads them and relays the pad into a virtual DualSense on `/dev/uhid`, where
the kernel's `hid-playstation` picks it up as a genuine PS5 controller. A game then
gets gyro, analogue triggers and rumble with no Steam Input in the path.

**The measurements are the point of this repository**, more than the code. The
code can be rewritten by anyone holding the pad; the constants took a session of
turning a gamepad in the air.

| Document | What is in it |
|---|---|
| [docs/PROTOCOL.md](docs/PROTOCOL.md) | the pad: interfaces, report map, command channel, calibration, what Bluetooth can and cannot do |
| [docs/DUALSENSE.md](docs/DUALSENSE.md) | the emulation side: uhid, feature reports, report layouts, rumble, udev, and the traps in each |
| [docs/DSX.md](docs/DSX.md) | adaptive triggers — the part that is *not* done, and the route to it |
| [docs/CONTINUE.md](docs/CONTINUE.md) | state of play, method, the measurement kit, next steps |

## Status

Works, in daily use on one pad, on the 2.4 GHz dongle and over a cable.
Specifically:

- gyro, all three axes, no enable command, gyro-mouse off, 1000 Hz
- analogue triggers, sticks, hat, face buttons, shoulders, stick clicks
- the four back paddles as **real buttons**: the relay presents a DualSense
  **Edge** by default, which has four buttons of its own, so Steam and games can
  bind them like any other. Plain DualSense is still available, and there the
  paddles fold into touchpad halves and stick clicks instead
- the Home key as the PS button (it is a Consumer-page usage, not a gamepad button)
- rumble both ways, two motors independently
- survives the pad sleeping, being switched off, and coming back

Not done, honestly listed:

- **adaptive triggers** — the pad has them, the command family for this model is
  not publicly known, nothing here drives them

- **Bluetooth**: buttons, sticks, hat and analogue triggers work; **gyro and
  rumble cannot** — there is no vendor interface over Bluetooth, and the pad only
  transmits on input change, so rotation alone sends nothing at all. The relay
  says so once at startup instead of pretending
- **other old-dialect models** (Vader 3/4, Direwolf 3/4, Apex 3) share the framing
  but need their own scales — `tools/` is how you measure them
- wired (cable) mode not yet verified — everything here was measured on the dongle

## Requirements

Linux with `uhid` and `hid_playstation` (any kernel since 5.12), `python3`, and
**no dependencies at all** — the whole thing is standard library, which is
deliberate: on an immutable distribution, a `pip install` line in the instructions
costs somebody an evening.

## Install

```sh
git clone https://github.com/Jackwmtr/flydigi-apex4-linux
cd flydigi-legacy-ds5
./install.sh --check          # diagnose only, changes nothing
./install.sh                  # add --hide-pad to hide the physical pad from Steam
```

`--check` is the part that matters on a machine that is not mine: it reports which
of the four things failed rather than "it does not work" — is the pad there and is
it this model, is the vendor node readable, is `/dev/uhid` writable, are the kernel
modules present. Then it brings a virtual DualSense up briefly and watches whether
the sensors move, so the whole chain is tested rather than the file list.

`--hide-pad` writes an `environment.d` file that hides the physical pad from SDL,
so Steam offers only the virtual DualSense and Steam Input can stay on. **It is
only safe together with the autostart unit**: with the pad hidden and the relay
not running, there is no controller at all.

## Run

```sh
systemctl --user enable --now flydigi-legacy-ds5      # installed by install.sh
```

Or by hand, which is how you try things out:

```sh
./apex4-ds5 --write-config               # settings file, then edit it
./apex4-ds5 --dump                       # decode and print, create no device
./apex4-ds5 --calib                      # the constants, and what the served
                                         # DualSense calibration implies
./apex4-ds5 --paddles "paddle-left,fn1,fn2,paddle-right"
./apex4-ds5 --gyro-map "pitch,yaw,-roll" # a minus inverts that axis
```

Settings live in `~/.config/flydigi-apex4/config.json` — which controller to
present (`dualsense-edge` or `dualsense`), paddle assignments, axis maps, report
rate. Flags override the file, so anything can be tried without
editing it.

If the motors ever stick on: `tools/rumble-off.py` works with the relay stopped.

## Not an Apex 4?

The framing in [docs/PROTOCOL.md](docs/PROTOCOL.md) is shared across the old
generation, but **the sensor scales are per-model** and differ by more than 3×
between axes on this one pad alone. Running with the wrong constants gives a gyro
that quietly lies, which is worse than one that does not work. `tools/` contains
what was used here: probe the interfaces, capture the stream, fit the
accelerometer, integrate known rotations for the gyro.

Patches adding a model are welcome; patches adding one *without* measured constants
are not.

## Credit

`apex4ds5/_ds5/` is vendored from [openflydigi](https://github.com/mkaliaha/openflydigi)
(MIT, Mikalai Kaliaha) — the `/dev/uhid` binding, the DualSense report codec and the
descriptors captured off real hardware. That project carries an inputtino attribution
of its own; see `apex4ds5/_ds5/NOTICE`. Everything else here is MIT, see `LICENSE`.

Bug found in it while doing this, worth passing on: its `motion.py` hard-codes
`DS5_ACCEL_RAW_PER_G = 10000` citing inputtino, but the blob shipped in its own
`ds5_usb.py` — captured off real hardware — implies 8192, so its accelerometer
reads about 22% low.
