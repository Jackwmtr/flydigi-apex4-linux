# The DSX channel, and Flydigi's trigger effects

This is the road to adaptive triggers, which this repository does **not** implement
yet. It is written down because it is the part where the next person needs a map
rather than encouragement.

## Two feedback modes exist in Flydigi's own software

Space Station offers two: **DS mode**, where a game writes adaptive-trigger effects
to a virtual DualSense and Space Station translates them into pad commands, and a
**per-game mode** driven by their own config for each supported title.

That matters as evidence: both change trigger behaviour *during play*, which a
setting stored in the pad's flash cannot do. So live force-effect commands exist
for this generation. The risk that the Apex 4 only supports stored presets — which
would have made per-shot effects impossible — is ruled out by the existence of a
per-game mode on the same pad.

## Flydigi speak DSX

They adopted the DualSenseX protocol rather than inventing one, which is why their
per-game "mods" are DSX mods. ASCII JSON datagrams over UDP:

```json
{"instructions":[{"type":1,"parameters":[0, side, 19, mode, p1, p2]}]}
```

| Field | Meaning |
|---|---|
| `type` | 1 = TriggerUpdate (2 = RGB, 3 = player LED, 4 = trigger threshold, 5 = mic LED) |
| `parameters[0]` | controller index, ignored |
| `parameters[1]` | side: 1 = left, 2 = right |
| `parameters[2]` | constant 19, ignored |
| `parameters[3]` | **mode** |
| `parameters[4..]` | effect parameters |

Ports: **7878** is DSX's own, **8787** is what Flydigi's software listens on. The
mode field is passed straight through to their effect builder — no translation — so
sending a datagram applies a specific force mode with specific parameters.

## The modes

`AdapterTriggerType` from their SDK:

| Mode | Behaviour | Parameters |
|---|---|---|
| 0 | normal, no added resistance | — |
| 1 | constant resistance past a point (a throttle) | start 0..192, strength 1..255 |
| 2 | rattle ("machine gun") | — |
| 3 | resist, then break through ("sniper") | — |
| 4 | lock | — |
| 5 | vibration | — |

Two notes worth carrying over. In Flydigi's own UI the labels for modes 2 and 3 are
**crossed** relative to their enum names, and the behaviour follows the label.
And the localisation keys for these modes are named `trigger_mode_K2_*` — `K2` is
the Apex 4's device code, which suggests this effect family started with this pad.

## How to test physical triggers without a game

Space Station must be running, with the pad connected. Then, from PowerShell on
Windows, no tooling required:

```powershell
$c = New-Object System.Net.Sockets.UdpClient
function Trig($json) { $b=[Text.Encoding]::ASCII.GetBytes($json); $c.Send($b,$b.Length,"127.0.0.1",8787) }

Trig '{"instructions":[{"type":1,"parameters":[0,2,19,1,60,220]}]}'   # right: resistance
Trig '{"instructions":[{"type":1,"parameters":[0,2,19,5]}]}'          # right: vibration
Trig '{"instructions":[{"type":1,"parameters":[0,2,19,0]}]}'          # clear
```

Comparing mode 1 with mode 5 answers the only question that matters before any of
this is worth doing: is "ForceAdapt" a force actuator or a motor? If mode 1 gives a
felt stop and 5 gives a buzz, there are two mechanisms and effects are worth
translating. If only 5 does anything, there is nothing for a DualSense effect to
map onto — the DS5 protocol has no trigger *vibration*, only resistance.

`Get-NetUDPEndpoint | ? LocalPort -in 7878,8787` shows which port their build
actually listens on.

## Getting the pad's own command family

Not publicly documented for `k2`, and openflydigi covers only the newer generation
(where the family is `SetForceTrigger`, effect-based, live). Three ways in, in the
order they are worth trying:

1. **Flydigi's public config API** — their game list ships effect parameters per
   title. If it has `k2` entries, that is ready-made semantics and a test corpus.
   Half an hour to check; openflydigi's `tools/fetch-configs` already fetches it.
2. **USB capture on Windows** with the DSX channel above as the input. Sweeping one
   parameter at a time against USBPcap turns this into a table of input → output
   rather than a guessing game. The framing is already known — 12 bytes,
   `[0x05, cmd, args...]` — so only the command number and parameter order are
   missing.
3. **Capture DS mode itself**, which additionally yields the *translation* from a
   DualSense effect to a pad command — the part that would otherwise have to be
   invented, since the two effect vocabularies do not line up one to one.

Back up the pad's profile blobs before writing anything unknown to it (flydigictl
can do this). An unknown command number could be a config write rather than an
effect, and that copy will be the only one.

## Where it would plug in

The relay already parses adaptive-trigger effects out of the DualSense output
reports it receives — they appear in `--verbose` output as `trigger effects` with a
type and ten parameter bytes. What is missing is only the last hop: translating
those into the pad's command. Once that exists, adding a DSX listener (openflydigi
has one under MIT) would also let the whole existing ecosystem of DSX mods drive
this pad on Linux.
