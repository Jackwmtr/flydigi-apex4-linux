# Adaptive triggers

A game writes DualSense trigger effects to the virtual controller; the relay
translates each one into the Apex 4's own force-trigger command. Verified on
hardware, by hand on the pad, for every mode the translation can produce.

## The command

```
[0x05, 160, 1, applyFlag, side, mode, p1, p2, p3, p4, p5, 0]
```

Read out of Flydigi's own SDK rather than captured: Space Station 4.x ships
`SpaceStationService.exe`, an 80 MB .NET single-file bundle, and the assembly
`Flydigi.ControllerSdk.dll` inside it holds `ForceTriggerControllerCommandDInput`
(the Apex 4 is on the DInput branch -- report id 5). How to get at it is below.

| Byte | Meaning |
|---|---|
| 0 | report id 5, the old dialect's command channel |
| 1 | 160, `CommandId` of the DInput force-trigger command |
| 2 | **the constant 1** (4 for SyncWithGrip). Not a length |
| 3 | applyFlag: 0 = engage only ("onlyPreview"), 1 = engage *and* write into the stored profile |
| 4 | side: 1 left, 2 right. Never 3 |
| 5 | mode, Flydigi's `AdapterTriggerType` |
| 6.. | parameters, per mode |

Byte 2 is why a dozen framings tried before the SDK was read all failed silently:
the XInput branch puts a 6 there, and that 6 had been copied.

**The relay sends applyFlag 0.** With 1, every effect a game sets is also written
into the pad's profile, which is flash, hundreds of times a session. openflydigi
sends 1 on the newer pads; that is the one thing about it not to copy.

### Modes and parameters

From each mode's `CreateParams` in the SDK, in wire order:

| Mode | SDK name | Feels like | Parameters |
|---|---|---|---|
| 0 | Normal | nothing | -- |
| 1 | Race | constant resistance from a point to the end of the pull | stroke, resistance (≥1), matchStroke |
| 2 | Sniper | a vibration in the trigger past a point | stroke, pressure (≥1), strength (≥1), frequency (≥1), matchStroke |
| 3 | Recoil | a band of resistance that gives way | stroke, recoilStroke, strength (≥1), 0, matchStroke |
| 4 | Lock | a hard stop, and the axis stops with it | stroke, strength (255), matchStroke |
| 5 | Vibration | -- | dead code in Flydigi's stack |

Flydigi's UI labels for modes 2 and 3 are crossed relative to the enum names
("Recoil" is mode 2 there). The behaviour follows the label; the table above
uses the enum names, as the code does.

`stroke` is on a 0..192 scale of the pull, not the 0..255 the axis reports.

### Measured by hand

Each of these was set on the pad through the whole chain (virtual DualSense →
relay → command) and felt:

* **Race** 40/200: soft for the first ~10-20% of the pull, then firm to the end.
* **Recoil** 20/60/255: resistance, then a felt break at 30-40% of the pull --
  where 20+60 of 192 says it should be.
* **Recoil has a ceiling.** 20/160 and 38/135 both broke at 50-60%, not near the
  end. The break point cannot be pushed past about the middle of the pull,
  whatever the band length. A property of the pad; nothing to do about it.
* **Sniper** vibrates, from both the simple (0x06) and the full (0x26) DualSense
  effect, and **frequency is real**: 10 felt like a machine gun, 30 like a buzz.
  **Pressure seems to do nothing** -- the vibration starts past the point however
  lightly the trigger is held.
* **Lock** (August, by axis): Lock 60 with matchStroke 0 caps the axis at ~47-55
  out of 255, and it is a hard stop by feel. Lock 180 did *not* cap at 180, so the
  stroke scale and the axis are not 1:1.

### No acknowledgement

The pad confirms nothing a relay can see. After a 160 there is no echo in byte 15
of the input stream (which is accel Z's low byte in any case -- its "echo" values
are readings) and no report of any other id. Flydigi's SDK waits for an ACK with
3 retries and a 500 ms timeout; blind, the equivalent is to repeat.

And a lost command is not theoretical: the very first effect sent to the left
trigger, over the 2.4 GHz dongle, did not take, and the identical packet sent
again did. So the relay sends every change three times -- at once, after 100 ms
and after 500 ms -- spaced at least 10 ms from any other trigger write. The
command sets a state rather than starting anything, so a repeat costs nothing.

### A live effect stays until cleared

Reloading a profile (command 235) left a live Lock engaged, so nothing on the
config path clears one. The relay sends Normal to both sides on exit, on startup
(in case the previous run died without its `finally`), and when it creates a new
virtual controller. Same lesson as rumble, see [DUALSENSE.md](DUALSENSE.md).

## The translation, DualSense → Flydigi

`apex4ds5/_ds5/trigger_map.py` is Flydigi's own: openflydigi transcribed it from
Space Station's `PS5DataManager.ProcessDataWithResult`, and it is vendored here
under MIT, unchanged. It is not a general conversion -- it recognises the byte
patterns particular games send and maps each onto a hand-tuned effect, so its
constants are deliberate. Left and right are asymmetric on purpose. It only ever
emits modes 0-3.

| DualSense effect | Flydigi mode |
|---|---|
| 0x01 simple feedback, 0x21 feedback | 1 race |
| 0x02 simple weapon, 0x25 weapon (mostly) | 3 recoil |
| 0x06 simple vibration, 0x26 vibration, some 0x25 | 2 sniper |
| 0x05 off | 0 normal |

On top of it, in `apex4ds5/triggers.py`, four mappings that are **ours, not
Flydigi's** -- their relay leaves the trigger as it was for each of these:

| DualSense effect | Mapped to | Why |
|---|---|---|
| 0x00 | normal | a zeroed report, or a title's "no effect"; leaving a Lock standing is worse than clearing one never set |
| 0x22 bow | recoil, start zone → band to end zone, strength | tension, then a snap. Subject to recoil's ceiling, so a long draw snaps around the middle. Felt: right |
| 0x23 galloping | sniper, start zone, the larger foot, frequency | rhythmic pulses |
| 0x27 machine | sniper, start zone, the larger amplitude, frequency | felt: a machine gun |

These read the well-known DualSense layout: a 10-bit zone mask over the pull in
bytes 0-1, forces packed three bits each as value−1, frequency in byte 3.

Anything else is logged as `... -> unmapped, trigger unchanged`, verbose or not,
so a game that uses something new shows up in the journal.

## Trying it without a game

```
tools/trigger-test.py right race 40 200          # 0x01: start, strength
tools/trigger-test.py both recoil 30 60 200      # 0x02: start, end, strength
tools/trigger-test.py left buzz 30 200 10        # 0x06: frequency, amplitude, start
tools/trigger-test.py right raw 0x27 0x02 0x02 0x2c 0x0a 0x03
tools/trigger-test.py both off
```

It writes the same output report a game would, to the virtual DualSense's own
hidraw node, so it exercises the whole chain. With `"verbose": true` the relay
logs what each effect became: `journalctl --user -fu flydigi-apex4`.

In a real game, Steam Input must be off for that title, or Steam re-emulates the
controller and the effects never reach it.

## Reading Flydigi's SDK

For the next command someone needs -- lighting is in the same assembly:
`EnableDS5ModeDataCommandDInput`, `ReadRgbConfigCommandDInput`,
`WriteRgbConfigCommandStartDInput`, `WriteRgbConfigPackCommandDInput`.

1. `SpaceStationService.exe` from a Space Station 4.x install. It is a .NET
   single-file bundle: find the signature
   `8b1202b96a612038727b930214d7a032`; the int64 just before it is the offset of
   the bundle header. Header: major, minor, file count, a length-prefixed bundle
   id, then (v2+) five 64-bit fields. Each entry: offset, size, compressed size
   (v6+), type byte, length-prefixed path. Compressed entries are raw deflate.
2. Disassemble with pure-Python `dnfile` + `dncil`. dncil's
   `CilMethodBodyReaderBase` needs its `read`/`tell`/`seek` supplied over the PE.
   The types to read are `ForceTrigger*` and each config class's `CreateParams`.

## Not done

* **A DSX listener.** Flydigi's per-game "mods" are DualSenseX datagrams -- ASCII
  JSON over UDP, `{"instructions":[{"type":1,"parameters":[0, side, 19, mode,
  p1, p2...]}]}`, port 8787 for Space Station (7878 is DSX's own). The mode goes
  straight to the effect builder, so a listener is a thin wrapper around
  `legacy.force_trigger_packet`. openflydigi has one under MIT.
* **SyncWithGrip** (byte 2 = 4): the game's rumble routed into the triggers.
  Present in the SDK, not tried on this pad.
* **What pressure does** on Sniper, and **where exactly** Recoil's ceiling is.
