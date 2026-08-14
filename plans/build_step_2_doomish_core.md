# Build step 2: Doomish core (world, render, HUD)

**Deliverable:** `samples/Doomish/code.py` that boots, renders a world, and
draws a HUD. No AI, no networking yet. Player moves on a fixed script or under
button control purely so rendering can be judged.

**Depends on:** step 1. **Blocks:** steps 3, 4.

Read `plans/build_overview.md` first.

## Non-negotiables

Standalone single file. No project-local imports. Copy helpers in rather than
factoring them out. Canonical hardware init verbatim from the overview. Backlight
stays off until after the first `display.refresh()`.

## File structure

Follow the house style exactly: module docstring with a `Controls` section, then
a loud user-editable config banner, then `# ---` delimited sections.

```
"""Doomish -- Carolina Code Conference sample
============================================
<pitch>

Controls
    SW1 (IO1)   toggle view: 3D raycast / top-down
    SW2 (IO2)   toggle LED status channel
    SW3 (IO43)  pause the AI (freeze in place)
    SW1+SW3     exit to the Launcher menu (supervisor.reload)
"""

# --- backlight off FIRST, before the slow adafruit imports ---
# --- CONFIGURATION banner ---
# --- Hardware setup ---
# --- Tables and helpers ---
# --- State ---
# --- Scene ---
# --- Render ---
# --- Boot ---
# --- Main loop ---
```

The backlight-before-imports trick is copied from the Launcher: the panel powers
up bright white and the adafruit imports take seconds on a cold boot.

## Config constants

```python
BADGE_ID   = "badge-01"
VIEW_MODE  = 0        # 0 = 3D raycast, 1 = top-down. SW1 toggles at runtime.
ROTATION   = 90       # 90 = landscape 160x128. 0 = portrait 128x160.
RAY_COLS   = 40       # raycast columns; each is 160/RAY_COLS px wide
SHOW_FPS   = True
```

`ROTATION` is load-bearing and untestable until Saturday. Every sample in this
repo uses `rotation=0` portrait, and `AGENTS.md` only documents landscape via the
`busdisplay` route. Landscape is right for a Doom-like, so default to 90, but the
renderer must read `display.width` / `display.height` rather than hardcoding, so
flipping this constant is the entire fallback.

## World

Tile map as a tuple of equal-length strings, 32x32, in the config banner where
someone can edit it. `#` wall, `.` floor, `E` enemy spawn, `M` medkit, `A` ammo.

At boot, parse into a flat `bytearray(32*32)` for O(1) lookup and a second
`bytearray` for seen/explored. Strings are fine as the source, but index them
once at boot, not per ray.

Track `OPEN_TILE_COUNT` at parse time so `explored` in the beacon is a cheap
division rather than a scan.

## Rendering

Two renderers behind one call site. `render()` dispatches on `VIEW_MODE`. This is
the pre-agreed degradation plan: if the raycaster is too slow on real hardware,
SW1 or the constant switches to top-down and **nothing else in the file
changes**. Keep that boundary clean, it is the insurance policy.

### Raycast

* One `displayio.Bitmap(w, h, N)` where N is a small palette (8-16 entries).
  Vertical walls one colour, horizontal walls a darker shade of the same, so
  corners read without texturing. Floor and ceiling flat.
* Precompute sin/cos tables and the per-column camera-x offsets at boot. Do not
  call `math.sin` inside the render loop.
* DDA grid traversal per column. `RAY_COLS` columns, each drawn as a
  `bitmaptools.fill_region` spanning the wall slice.
* **Clear with `bitmap.fill(0)`**, never `fill_region` over the full frame.
* **Clamp column tops and bottoms explicitly** to `0..h`. Out-of-bounds writes
  silently no-op in the simulator and will not behave the same on hardware.

### Top-down

Draw the 32x32 grid scaled to fit, player as a dot with a facing tick, enemies
and items as coloured pixels, unexplored tiles dark. Cheap, and it is the
fallback that must actually work, so build it now rather than at 2am Saturday.

## HUD

A `displayio.Group` holding the viewport TileGrid plus `terminalio.FONT` labels:

* top-left: HP and ammo
* top-right: FPS when `SHOW_FPS`
* **bottom strip: the current directive**, plus its `why` text if it fits

The directive line is the entire point of the demo. It is what makes the "slow
judgment, fast reflexes" split visible to somebody looking over a shoulder.
Give it the full bottom row and a distinct colour. Step 3 fills it; step 2 just
draws a placeholder like `LOCAL`.

## LEDs

Five pixels as a second status channel, readable across a room:

* 0-2: HP bar, green to amber to red
* 3: flash white on each shot
* 4: network heartbeat. Step 2 leaves it dim.

Update at most every 100 ms. `pixels.show()` is not free.

## Main loop

No `time.sleep()`, no blocking call. Explicit `display.refresh()` per frame.
Track frame time with `time.monotonic()` and keep a rolling average for the FPS
label and for the serial line.

Print one line per second to serial with frame time, position, and state. That
trace is what you will actually be reading when something is wrong on Saturday
and the badge is on a lanyard.

## Buttons

Use the repo's edge-detection idiom rather than inventing one: keep `swN_prev`,
compute `pressed = (not v) and swN_prev`, reassign. See
`samples/Nameplate/code.py:266-289` or the debounce-timestamp variant at the tail
of `samples/LEDLab/code.py`.

SW1+SW3 together calls `supervisor.reload()`. No existing sample can return to
the menu, and `samples/LEDLab/README.md:80` names that as a known limitation.
The Launcher writes its NVM selection before `exec`, so a reload lands back at
the 3-second countdown where a button press opens the menu.

## Verification

1. `sim/run.py Doomish` renders a recognisable 3D corridor view that responds to
   movement.
2. SW1 (key `1`) switches to top-down and back with no crash and no leaked
   display resources.
3. HP/ammo labels update; the directive strip shows `LOCAL`.
4. LED strip in the terminal tracks HP.
5. Frame time printed and stable. Record the number, but do not tune against it:
   the simulator's flat ~47 ms refresh dominates and tells you nothing about the
   badge.
6. Walk into every wall on the map. No index errors, no visual tearing at the
   edges, both view modes.
