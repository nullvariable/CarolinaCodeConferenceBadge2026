# Doomish build overview

Index of the remaining build steps, plus the shared context every step assumes.
Each `build_step_N.md` is self-contained enough to hand to a fresh session.
This file exists so the facts below are written once and stay consistent.

## Status

Done and verified 2026-08-13:

* `relay/relay.py`, `relay/fake_badge.py`, `relay/README.md`
* Pi 3 B provisioned at **192.168.1.54**, hostname `doomish-relay`, user `pi`,
  SSH key auth from WSL. `doomish-relay.service` enabled and running.
* Wifi power save disabled on the Pi (was adding 65-110 ms/packet). Now 6-22 ms.
* UDP broadcast proven across two real devices over a real AP.
* Ollama Cloud live. Real directives returning in 1.8-2.5 s.
* Model chosen: `gpt-oss:20b`. See `relay/README.md` for the benchmark table.

Steps 1-4 built later the same day: `sim/` runs badge code on the laptop, and
`samples/Doomish/code.py` is the whole game with the OODA loop and the network
in it. Each of those steps has its own README section describing what was
verified.

Step 5 done 2026-08-13 evening: `relay/dashboard.py`, wired into `relay.py`
behind `--dashboard`. All six verification items exercised, the browser ones
against headless chromium at both laptop and phone widths. No Ollama Cloud calls
were spent on it: mock mode and `dashboard.py --demo` cover every row type.

Not started: steps 6, 7 and 8.

## Build steps, in dependency order

| Step | File | Deliverable |
|---|---|---|
| 0 | `build_step_0_hotspot_test.md` | phone hotspot proven, no badge needed. **Tonight.** |
| 1 | `build_step_1_simulator.md` | `sim/` -- run badge code on the laptop |
| 2 | `build_step_2_doomish_core.md` | `samples/Doomish/code.py` -- world, render, HUD |
| 3 | `build_step_3_doomish_ooda.md` | the OODA loop and reflex rules |
| 4 | `build_step_4_doomish_net.md` | badge-side UDP, directive integration |
| 5 | `build_step_5_dashboard.md` | Pi web dashboard (`plans/wishlist spec.md`) |
| 6 | `build_step_6_docs_and_ship.md` | READMEs, root index, commit, push |
| 7 | `build_step_7_hardware_bringup.md` | Saturday checklist, run on real badge |
| 8 | `build_step_8_hardening.md` | gaps in steps 2-4 (read before step 2), crash/memory/quota/power hardening, Saturday runbook |

Steps 1-4 are the critical path. Step 5 is independent of 2-4 and can be built
in parallel or skipped. Step 7 cannot happen before Friday morning 2026-08-14,
when the badge arrives. The talk is Saturday afternoon, so there is about a full
day with real hardware, not a few hours.

## Review gate

**Every step ends with a reviewer subagent**, before any work starts on the next
one. The reviewer gets the step document and the actual diff, and judges against
that step's Verification section specifically. It is not a code-style pass.

The reviewer must return one of PASS / PASS WITH NOTES / FAIL, and must say which
verification items it could not confirm rather than assuming they hold. An item
that needs a human at a keyboard (pressing a button, looking at a window) gets
reported as unverified, not as passed.

Findings get fixed before moving on. The point is to stop a wrong assumption in
step 1 from being built on top of three more times before anyone notices.

## Shared context

### The badge

ESP32-S3-WROOM-1-N8. 8 MB flash, **no PSRAM**, ~512 KB RAM. CircuitPython
10.2.1 pre-flashed. Deployment is copy-a-folder: saving `code.py` reboots and
runs it. No build step, no pip.

| Thing | Pins |
|---|---|
| LCD ST7735S, panel native 128x160 portrait | SCK IO12, MOSI IO11, RST IO7, DC IO6, CS IO10, BL IO5 |
| Font chip (shares the SPI bus) | CS IO9 -- **must be driven HIGH** or it corrupts display traffic |
| 5x WS2812 NeoPixel | IO4 |
| Switches SW1/SW2/SW3 | IO1 / IO2 / IO43, `Pull.UP`, **active-low** (`value == False` means pressed) |

`AGENTS.md` in the repo root is the authority on pin map and CP10 patterns.

### Repo conventions that are not negotiable

* **Every sample is a standalone single file.** `samples/<Name>/code.py` with no
  project-local imports. Helper functions are copy-pasted between samples on
  purpose, so any folder can be dropped onto the drive alone. Do not factor out
  a shared module.
* The Launcher discovers samples by `os.stat("/samples/<Name>/code.py")` and
  `exec()`s the source with fresh globals. It releases all hardware first, so a
  sample must initialise everything itself.
* Only these libs exist in `lib/`: `adafruit_bitmap_font`, `adafruit_display_text`,
  `adafruit_imageload`, `adafruit_connection_manager`, `adafruit_pixelbuf`,
  `adafruit_requests`, `adafruit_st7735r`, `neopixel`.
* Every sample folder needs a `README.md` and a line in the root `README.md` tree.

### Canonical hardware init

Copy this verbatim. It is the one arrangement known to work on this board.

```python
pixels = neopixel.NeoPixel(board.IO4, 5, brightness=0.35, auto_write=False)
pixels.fill((0, 0, 0)); pixels.show()

sw1 = digitalio.DigitalInOut(board.IO1);  sw1.switch_to_input(pull=digitalio.Pull.UP)
sw2 = digitalio.DigitalInOut(board.IO2);  sw2.switch_to_input(pull=digitalio.Pull.UP)
sw3 = digitalio.DigitalInOut(board.IO43); sw3.switch_to_input(pull=digitalio.Pull.UP)

font_cs = digitalio.DigitalInOut(board.IO9)
font_cs.direction = digitalio.Direction.OUTPUT
font_cs.value = True

bl = digitalio.DigitalInOut(board.IO5)
bl.direction = digitalio.Direction.OUTPUT
bl.value = False          # stays off until after the first refresh

displayio.release_displays()
spi = busio.SPI(clock=board.IO12, MOSI=board.IO11)     # no MISO
display_bus = fourwire.FourWire(
    spi, command=board.IO6, chip_select=board.IO10, reset=board.IO7,
    baudrate=8_000_000,
)
display = adafruit_st7735r.ST7735R(
    display_bus, width=128, height=160, rotation=0, bgr=True, auto_refresh=False,
)
```

`fourwire.FourWire`, not `displayio.FourWire`. `display.root_group = group`,
not `display.show(group)`. `auto_refresh=False` plus an explicit
`display.refresh()` per frame.

### The relay protocol

Badge broadcasts to `255.255.255.255:5115`. Relay replies unicast to the source
address. Badge binds `5116`. Nothing knows anyone's IP.

Beacon, keep under ~400 bytes:

```json
{"id":"badge-01","seq":42,"hp":63,"ammo":12,"pos":[12,7],"facing":"N",
 "explored":0.35,"enemies":[{"dir":"N","dist":4}],
 "items":[{"kind":"medkit","dir":"E","dist":6}],
 "walls":{"n":false,"s":true,"e":true,"w":false},
 "recent":["EXPLORE_N","HUNT"]}
```

Reply:

```json
{"directive":"HUNT","seq":42,"why":"enemy known and healthy"}
```

Vocabulary, closed set of eight:
`EXPLORE_N` `EXPLORE_S` `EXPLORE_E` `EXPLORE_W` `HUNT` `RETREAT` `SEEK_ITEM` `HOLD`

`relay.py`'s `describe()` and `heuristic()` show exactly which fields are read.
Adding a field the relay does not read is wasted bytes.

### Verified facts, do not re-derive

* **UDP broadcast works on CircuitPython ESP32-S3 with no `setsockopt`.** lwIP's
  broadcast filter is compiled out (`IP_SOF_BROADCAST` = 0). `SO_BROADCAST` is
  not exposed and adding it would raise `OSError` on some ports. Send bare.
* **`recvfrom` does not exist.** Only `recvfrom_into`. Empty socket raises
  `OSError` with `errno == 11` (EAGAIN). Catch `BrokenPipeError` *before*
  `OSError`, it is a subclass.
* **Set `wifi.radio.power_management = wifi.PowerManagement.NONE`.** The default
  wakes on DTIM; `MAX` drops AP-buffered broadcast frames outright.
* **Recreate the socket after a wifi reconnect.** CircuitPython does not close
  user sockets on disconnect and the pcb keeps the stale IP.
* Max 8 sockets device-wide. UDP receive queue is 6 datagrams. Keep payloads
  under 1472 bytes.
* Directives take **2 to 4 seconds**, not sub-second. Everything downstream must
  tolerate that.
* **Ollama's `format` schema does not enforce `enum`.** The vocabulary must also
  be spelled out in the prompt, and answers must be validated on arrival.
  `relay.py:normalize()` already repairs near-misses.
* In the desktop simulator: clear bitmaps with `bitmap.fill(0)`, never
  `fill_region` over the whole screen (0.07 ms vs 38 ms). `bitmaptools`
  sub-region `arrayblit` is broken. Out-of-bounds pixel writes silently no-op,
  so clamp explicitly rather than relying on it.

### The two design documents

`plans/gameplay.md` defines the OODA loop, including that a directive refresh is
requested from inside Decide when there is no urgent threat. `plans/wishlist
spec.md` defines the dashboard. Both are Doug's and take precedence over any
inference in the build steps.
