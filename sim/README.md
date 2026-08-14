# sim -- run badge code on the desktop

The badge does not exist until Saturday. This runs `samples/<Name>/code.py`
unmodified, in a window, on the laptop.

**Repo-only.** Never copy `sim/` to the CIRCUITPY drive, same as `img/` and
`relay/`.

## Setup

Once:

```sh
python3 -m venv sim/.venv
sim/.venv/bin/pip install adafruit-blinka-displayio blinka-displayio-pygamedisplay \
                          pygame adafruit-circuitpython-display-text
```

Then:

```sh
sim/.venv/bin/python sim/run.py Doomish
sim/.venv/bin/python sim/run.py Nameplate --fps
sim/.venv/bin/python sim/run.py --list
```

On WSL you need WSLg for the window. If `echo $DISPLAY` is empty, run headless
with `SDL_VIDEODRIVER=dummy` and watch the terminal instead.

## Controls

| Badge | Keyboard |
|---|---|
| SW1 (IO1) | `1` or LEFT |
| SW2 (IO2) | `2` or DOWN |
| SW3 (IO43) | `3` or RIGHT |

Close the window or ctrl-c to quit.

The 5 NeoPixels are drawn as coloured blocks on a single rewritten terminal
line, so the LED channel stays visible without a second window. Any change
redraws immediately; an unchanged frame redraws at most once a second.

## How it works

The sample is never modified and never imports anything from here. `sim/fakes`
goes to the front of `sys.path`, so `board`, `busio`, `digitalio`, `fourwire`,
`neopixel`, `pwmio`, `supervisor`, `wifi`, `socketpool` and `adafruit_st7735r`
resolve to the simulator's versions, while `displayio`, `bitmaptools` and
`terminalio` come from Blinka, which implements them for real. Then `run.py` executes the file the
same way the badge's Launcher does:

```python
exec(source, {"__name__": "__main__", "__file__": path})
```

So anything that runs here is real badge code, with no `if SIMULATOR:` branch
anywhere in `samples/`.

`run.py` also maps CircuitPython's absolute paths. On the badge the CIRCUITPY
drive is the filesystem root, so samples open `/img/logo.bmp` and the Launcher
walks `/samples`. A leading `/` resolves to the repo whenever the repo has that
file, and otherwise falls through to the real path.

**The repo wins on a collision, deliberately.** `/lib` exists both here and on
Linux, and on the badge it is the CircuitPython library folder that sits on
`sys.path`. An earlier version checked the host first, so `/lib` silently
resolved to the host's shared objects. If you ever need a genuine system path
that shares a name with something in this repo, you cannot get at it from
inside a sample, which matches the badge exactly.

`run.py` also copies `settings.toml` into the process environment at startup.
On the badge `os.getenv()` reads `settings.toml`; on CPython it reads the
environment. That is the only place the two platforms genuinely differ, and
handling it in the runner keeps it out of the sample.

Rotation is resolved in the display fake. Constructing `ST7735R(width=128,
height=160, rotation=90)` produces a 160x128 window and reports
`display.width == 160`, exactly as displayio does on hardware, so a renderer
that reads `display.width` / `display.height` behaves identically on both.

## The FPS number is not the badge's FPS

`--fps` measures this laptop. It tells you nothing about the ESP32-S3.

Blinka's `displayio` is a pure-Python reimplementation. `display.refresh()`
costs a flat ~47 ms here regardless of what changed, because it loops over every
one of the 20,480 display pixels in Python. That is a hard ~21 FPS ceiling
before any drawing happens, and it is a property of the simulator, not the game.
The badge runs the same API in native C against real SPI.

Use `--fps` to catch a change that made things *relatively* worse. Never use it
to decide whether the raycaster is fast enough. Only the badge answers that.

## Known simulator-vs-hardware differences

These are real and worth knowing before chasing a ghost:

* **`bitmap.fill(0)` vs `fill_region` over the whole screen** is 0.07 ms vs
  38 ms here. On hardware both are native C. Always use `fill()` to clear.
* **`bitmaptools.arrayblit` sub-region blits are broken** in Blinka (bad index
  arithmetic). Full-bitmap blits work. Avoid sub-region entirely.
* **Out-of-bounds pixel writes silently no-op here.** Hardware may not agree.
  Clamp explicitly rather than relying on either.
* **`auto_refresh = True` does not work here.** pygame must be driven from the
  main thread, so the background refresh thread posts one event and then stalls.
  The fake still *defaults* to True because that is CircuitPython's real
  default, and defaulting to False would silently change the behaviour of a
  sample that omits the argument. You get a loud warning instead.
  `samples/MorseCode` is the only sample affected; the other seven pass
  `auto_refresh=False` and call `display.refresh()` explicitly, which behaves
  identically on both platforms. Doomish does the same.
* **Blinka's displayio starts a non-daemon refresh thread that never returns.**
  A normal interpreter shutdown blocks joining it, so the process ignores
  SIGTERM and spins at 100% CPU: `timeout` will not kill it and neither will
  ctrl-c. `run.py` installs signal handlers and exits via `os._exit()` to skip
  thread joining. If you write your own harness against these fakes, do the
  same or you will leave runaway processes behind.
* **`colstart`, `rowstart`, `bgr` and `invert` are accepted and ignored.** Real
  ST7735S panels frequently need column and row offsets, so the simulator can
  render perfectly aligned while the badge is shifted a few pixels. Not
  something the simulator can tell you about. Check it on hardware.
* **`samples/CCCLogo` fails**, on the badge and here, because it loads
  `/img/CarolinaCodeConference.bmp` while the file is
  `img/CarolinaCodeConference Logo.bmp`. Pre-existing repo bug, noted in
  `HANDOFF.md`. The simulator reproducing it faithfully is the intended
  behaviour.
* **The network fakes are strict on purpose.** `socketpool` gives you real
  CPython sockets behind CircuitPython's API, and it enforces the three places
  they differ: there is no `recvfrom`, only `recvfrom_into`; an empty
  non-blocking socket raises `OSError` with `errno == 11` rather than
  `BlockingIOError`; and `setsockopt` accepts only `SO_REUSEADDR` and
  `TCP_NODELAY`, so asking for `SO_BROADCAST` fails here exactly as it would on
  a badge. The one thing papered over is that CPython needs `SO_BROADCAST` to
  send to 255.255.255.255 and the ESP32 does not, so the wrapper sets it on the
  underlying socket itself.
* **`wifi` cannot warn you about power management.** The laptop has no radio to
  manage, so `power_management = NONE` is accepted and ignored. On the badge it
  is load-bearing: the default wakes only on DTIM and `MAX` drops AP-buffered
  broadcast frames outright.
* **Broadcast UDP will not leave WSL2.** It is NAT'd onto its own subnet. Point
  the sample's `RELAY_HOST` at the Pi's IP when testing networking from WSL.
  Broadcast is proven working between real devices on a real AP.
