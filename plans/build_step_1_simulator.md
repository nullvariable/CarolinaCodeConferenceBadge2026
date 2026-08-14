# Build step 1: the desktop simulator

**Deliverable:** `sim/` that runs an unmodified `samples/<Name>/code.py` on the
laptop in a window, so the badge app can be built and debugged before the
hardware exists.

**Depends on:** nothing. **Blocks:** steps 2, 3, 4.

Read `plans/build_overview.md` first for the shared context.

## The shape of it

The badge file must stay standalone and simulator-unaware. So the simulator does
**not** get imported by the sample. Instead it fakes the CircuitPython *module
namespace* on `sys.path` and then `exec()`s the sample exactly the way the
Launcher does:

```python
exec(source, {"__name__": "__main__", "__file__": path})
```

Anything that works in the simulator is therefore real badge code, and there is
no `if SIMULATOR:` branch anywhere in `samples/`.

## What already exists

`sim/.venv` is created and gitignored, with:

```
adafruit-blinka-displayio==2.3.2   blinka-displayio-pygamedisplay==4.0.1
pygame==2.6.1                      Adafruit-Blinka==9.2.0
```

Import check results from that venv:

| module | status |
|---|---|
| `displayio`, `bitmaptools`, `terminalio`, `microcontroller` | real, from Blinka. **Use as-is.** |
| `board`, `busio`, `digitalio`, `fourwire` | present but they are Blinka's, and they fail on a PC (`board.IO12` does not exist on `GENERIC_X86`). **Must be shadowed.** |
| `adafruit_display_text` | missing. `pip install adafruit-circuitpython-display-text` |
| `neopixel`, `supervisor`, `wifi`, `socketpool`, `pwmio` | missing. **Must be written.** |

The path ordering matters: `sim/fakes/` goes at the **front** of `sys.path` so
the fakes win over Blinka's `board`/`digitalio`/`busio`/`fourwire`, while
`displayio` and `bitmaptools` still resolve to Blinka's real implementations.

## Files to write

### `sim/fakes/board.py`
Pin objects for every GPIO the repo references. A pin can be a trivial class
with a `name`. Needs at least `IO0`-`IO12`, `IO43`, `IO44`.

### `sim/fakes/busio.py`, `sim/fakes/fourwire.py`
Inert stubs. `SPI(clock=, MOSI=, MISO=None)` and `FourWire(...)` just record
their arguments and expose `deinit()`. Nothing reads them.

### `sim/fakes/digitalio.py`
`Direction.INPUT/OUTPUT`, `Pull.UP/DOWN`, and `DigitalInOut(pin)` with
`.direction`, `.pull`, `.value`, `.switch_to_input(pull=)`,
`.switch_to_output()`, `.deinit()`.

Input pins on IO1 / IO2 / IO43 read the keyboard, **active-low**: return
`False` while the mapped key is held, `True` otherwise. Map SW1 -> `1` and
LEFT, SW2 -> `2` and DOWN, SW3 -> `3` and RIGHT.

Use `pygame.key.get_pressed()`, not `pygame.event.get()`. `get_pressed` polls
state without consuming the event queue, so it cannot steal the QUIT event from
`PyGameDisplay.check_quit()`. Call `pygame.event.pump()` first so the state is
current. If `pygame.display` is not yet initialised, return `True` (unpressed).

Output pins (IO5 backlight, IO9 font CS) are no-ops that just store the value.

### `sim/fakes/pwmio.py`
`PWMOut(pin, frequency=, duty_cycle=)` storing `.duty_cycle`. Some samples drive
the backlight this way. No-op.

### `sim/fakes/neopixel.py`
`NeoPixel(pin, n, brightness=, auto_write=)` supporting indexing, slicing,
`.fill()`, `.show()`, `.brightness`, `len()`.

Render the strip as a line of ANSI 24-bit colour blocks on stdout. Any change
redraws immediately; only an unchanged frame is rate-limited. Do not throttle
changes: a one-shot update like "turn every pixel off" is a single show() call
and throttling it drops it forever. Keeps the LED channel visible without a
second window:

```
LEDS  ██ ██ ██ ██ ██
```

### `sim/fakes/adafruit_st7735r.py`
`ST7735R(bus, width=, height=, rotation=0, bgr=, auto_refresh=, **kw)` returning
a `PyGameDisplay` subclass.

* Compute effective size from rotation: `rotation` in `(90, 270)` swaps width and
  height. Construct `PyGameDisplay(width=eff_w, height=eff_h, caption=...)`.
  This is what makes `display.width` / `display.height` correct on both sides,
  which is how the renderer stays orientation-agnostic.
* Override `refresh()` to call `check_quit()` first, and `sys.exit(0)` if the
  window was closed. Without this the window cannot be closed and the pygame
  event queue never drains.
* Do not pass `rotation` through to `PyGameDisplay`.

### `sim/fakes/wifi.py`, `sim/fakes/socketpool.py`
Deferred to **step 4**, which defines the exact API surface. Write them there,
not here. Step 1 only needs the sample to render.

### `sim/fakes/supervisor.py`
`reload()` raising a `SystemExit` subclass the runner catches and reports, since
a real reload would restart the Launcher.

### `sim/run.py`
The entry point. `python sim/run.py Doomish` should:

1. Put `sim/fakes` at the front of `sys.path`.
2. Load `settings.toml` from the repo root if present and copy its keys into
   `os.environ`, because on the badge `os.getenv` reads `settings.toml` and on
   CPython it reads the environment. This is the one place the two platforms
   genuinely differ, and doing it here keeps it out of the sample.
3. Read `samples/<Name>/code.py` and `exec()` it with
   `{"__name__": "__main__", "__file__": path}`.
4. Catch `KeyboardInterrupt` and the fake `supervisor.reload()` cleanly.
5. Accept `--fps` to print a rolling frame-time average, which is how step 2
   gets measured.

### `sim/README.md`
What it is, the one-line run command, the keyboard map, and a blunt statement
that **desktop FPS says nothing about badge FPS** (Blinka's displayio is pure
Python; the badge runs native C). Include the measured desktop ceiling: a flat
~47 ms per `display.refresh()` regardless of what changed, so ~21 FPS is the
ceiling and anything near it is normal, not a bug in the game.

## Verification

1. `sim/.venv/bin/python sim/run.py Nameplate` opens a 128x160 window showing the
   nameplate, with the LED strip echoed in the terminal. Nameplate is the right
   first target because it exercises display, labels, NeoPixels, and all three
   buttons, and it is known-good code nobody is editing.
2. Pressing `3` / RIGHT turns the LEDs off, proving active-low button mapping.
3. Closing the window exits the process cleanly with no traceback.
4. `sim/run.py DVDBounce` also runs, proving the fakes are not Nameplate-shaped.
5. `git status` shows no new tracked files under `sim/.venv/`.

Do not move on until a stock sample renders. Debugging the fakes and a new game
at the same time is how a day disappears.
