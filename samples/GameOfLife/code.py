"""
code_GameOfLife.py -- Carolina Code Conference 2026 badge sample
================================================================
Conway's Game of Life on the badge panel. Four rules, no player, and a
board that never runs the same way twice.

    a live cell with 2 or 3 live neighbours survives
    a live cell with any other count dies
    a dead cell with exactly 3 live neighbours is born

That is the whole simulation. Everything else in this file is there to
fit a 42x45 board into a 128x160 panel and step it fast enough to watch.

The grid is a torus: the left edge neighbours the right, the top edge
neighbours the bottom. A glider that walks off one side comes back in on
the other instead of dying in a corner, which matters a lot on a board
this small.

Cells are coloured by what just happened to them rather than by whether
they are alive, so the shape of the wavefront is visible. A cell is born
in conference orange, cools to conference purple once it has survived a
generation, and leaves a dark ember for one step on the way out. The
front edge of anything growing is therefore orange and its body is
purple, which is what makes a glider read as moving rather than blinking.

Controls
--------
  SW1 (IO1)   -- next pattern (RANDOM SOUP is a fresh roll every time)
  SW2 (IO2)   -- cycle speed; while paused, advance a single generation
  SW3 (IO43)  -- pause / resume
  SW1 + SW3   -- exit to the Launcher menu

Most patterns settle. When the board repeats itself -- a still life, a
blinker, a pulsar -- the status line says SETTLED and the next pattern
loads a couple of seconds later, so the badge keeps showing something on
a lanyard all afternoon without being touched.
"""

# ------------------------------------------------------------------
# Backlight off FIRST, before the slow adafruit imports.
# The panel powers up bright white and those imports take a couple of
# seconds on a cold boot. Same trick the Launcher and Doomish use.
# ------------------------------------------------------------------
import board
import digitalio

bl = digitalio.DigitalInOut(board.IO5)
bl.direction = digitalio.Direction.OUTPUT
bl.value = False


# ==============================================================
#   >>>  CONFIGURATION  <<<
#   Edit anything in this block, save the file, and CircuitPython
#   auto-reloads. Everything below the block is machinery.
# ==============================================================

ROTATION = 0        # 0 = portrait 128x160, 90 = landscape 160x128
CELL     = 3        # pixels per cell. 2 = denser and slower, 4 = chunkier
STRIP_H  = 24       # status strip along the bottom. A terminalio label
                    # occupies a 12 px box, descenders included, so two
                    # lines need 24 and anything less clips the lower one.

DENSITY  = 0.30     # fraction of cells alive in RANDOM SOUP

SPEEDS   = (2, 6, 15, 0)   # generations per second. 0 = as fast as it runs.
SPEED    = 1               # which of those to start on

SEED_HOLD = 1.4            # seconds to show a freshly loaded pattern before
                           # the first step. Block letters and the glider gun
                           # are recognisable for about a second and then
                           # never again, so this is the only chance to read
                           # what the board started as.

START_PATTERN = 0          # index into PATTERNS below

AUTO_ADVANCE = True        # load the next pattern once the board settles
STILL_HOLD   = 2.5         # seconds to hold a board that has stopped moving
OSC_HOLD     = 9.0         # ...and one left beating on a period-3 loop, which
                           # in practice means the pulsar. It gets there on
                           # generation 3, so without a longer hold it would be
                           # gone before anyone saw it pulse. Period 2 is
                           # usually just leftover blinkers, so it does not
                           # count as worth watching.
PATTERN_TIMEOUT = 90       # seconds before moving on anyway. 0 = never.

LEDS_ON  = True            # the 5 NeoPixels as a population meter
BRIGHT   = 0.30

# Conference colours. The purple is the badge's own soldermask (#3E3457 in
# img/Badge Concept - Purple.png) pushed up to something a 16-bit panel can
# actually show, and the orange is the amber accent from the same render.
CCC_PURPLE = 0x8B5CF6
CCC_ORANGE = 0xFFB01A

# Cell colours, by what happened to the cell this generation.
COL_DEAD  = 0x120A1E       # background -- near-black, purple-biased
COL_NEW   = CCC_ORANGE     # born this generation
COL_LIVE  = CCC_PURPLE     # alive last generation and still alive
COL_EMBER = 0x3A1B12       # died this generation, shown for one step

# Status strip
COL_STRIP = 0x1C1233
COL_NAME  = CCC_ORANGE
COL_STAT  = 0xB9A6E0
COL_SPEED = 0x6B5A8A

# ==============================================================


import gc
import time
import random
import busio
import displayio
import neopixel
import terminalio
import supervisor
import fourwire
import adafruit_st7735r
from adafruit_display_text import label


# ------------------------------------------------------------------
# Hardware setup
# ------------------------------------------------------------------
pixels = neopixel.NeoPixel(board.IO4, 5, brightness=BRIGHT, auto_write=False)
pixels.fill((0, 0, 0))
pixels.show()

sw1 = digitalio.DigitalInOut(board.IO1);  sw1.switch_to_input(pull=digitalio.Pull.UP)
sw2 = digitalio.DigitalInOut(board.IO2);  sw2.switch_to_input(pull=digitalio.Pull.UP)
sw3 = digitalio.DigitalInOut(board.IO43); sw3.switch_to_input(pull=digitalio.Pull.UP)

# The font chip shares the SPI bus with the LCD. Its chip select has to be
# driven high or it answers for the display.
font_cs = digitalio.DigitalInOut(board.IO9)
font_cs.direction = digitalio.Direction.OUTPUT
font_cs.value = True

displayio.release_displays()
spi = busio.SPI(clock=board.IO12, MOSI=board.IO11)
display_bus = fourwire.FourWire(
    spi, command=board.IO6, chip_select=board.IO10, reset=board.IO7,
    baudrate=8_000_000,
)
display = adafruit_st7735r.ST7735R(
    display_bus, width=128, height=160, rotation=ROTATION, bgr=True,
    auto_refresh=False,
)

# Read the size back rather than assuming it: displayio swaps width and
# height for rotation 90/270, so ROTATION is the only thing that has to
# change to flip the whole sample on its side.
SCREEN_W = display.width
SCREEN_H = display.height

GRID_W = SCREEN_W // CELL
GRID_H = (SCREEN_H - STRIP_H) // CELL
CELLS  = GRID_W * GRID_H

VIEW_H = GRID_H * CELL
OX     = (SCREEN_W - GRID_W * CELL) // 2   # leftover pixels, split evenly

# The strip gets whatever the cells could not use, so it is never smaller
# than STRIP_H. Label y is the centre of that 12 px box, so these two put
# the lines flush against each other with nothing hanging off the bottom.
LINE1_Y = VIEW_H + 6
LINE2_Y = VIEW_H + 18

C_DEAD, C_NEW, C_LIVE, C_EMBER = 0, 1, 2, 3


# ------------------------------------------------------------------
# Patterns
#
# Each entry is (name, rows, placements). `rows` is a block of text where
# anything that is not a dot is a live cell; None means "random soup".
# `placements` is a tuple of top-left grid positions to stamp that block
# at, or None to centre a single copy.
#
# Stamping wraps, so a placement near an edge is not an error.
# ------------------------------------------------------------------
GLIDER = (
    ".O.",
    "..O",
    "OOO",
)

LWSS = (          # lightweight spaceship
    "O..O.",
    "....O",
    "O...O",
    ".OOOO",
)

# Two cells thick on purpose. A one-cell stroke is nearly all ends, and
# ends have one neighbour, so a thin letter starves in about five
# generations instead of exploding into anything worth watching.
LETTER_C = (
    "..OOOOOOO..",
    ".OOOOOOOOO.",
    "OOO.....OOO",
    "OO.......OO",
    "OO.........",
    "OO.........",
    "OO.........",
    "OO.........",
    "OO.......OO",
    "OOO.....OOO",
    ".OOOOOOOOO.",
    "..OOOOOOO..",
)

GOSPER_GUN = (    # 36 wide -- the reason the grid is not narrower than that
    "........................O...........",
    "......................O.O...........",
    "............OO......OO............OO",
    "...........O...O....OO............OO",
    "OO........O.....O...OO..............",
    "OO........O...O.OO....O.O...........",
    "..........O.....O.......O...........",
    "...........O...O....................",
    "............OO......................",
)

PULSAR = (
    "..OOO...OOO..",
    ".............",
    "O....O.O....O",
    "O....O.O....O",
    "O....O.O....O",
    "..OOO...OOO..",
    ".............",
    "..OOO...OOO..",
    "O....O.O....O",
    "O....O.O....O",
    "O....O.O....O",
    ".............",
    "..OOO...OOO..",
)

R_PENTOMINO = (
    ".OO",
    "OO.",
    ".O.",
)

ACORN = (
    ".O.....",
    "...O...",
    "OO..OOO",
)

DIEHARD = (       # 130 generations, then nothing. The name is the spoiler.
    "......O.",
    "OO......",
    ".O...OOO",
)

# Three block letters with a two-cell gap, centred by hand rather than by
# the usual auto-centre because the placements are what space them out.
_C_W   = len(LETTER_C[0]) + 1
_CCC_Y = (GRID_H - len(LETTER_C)) // 2
_CCC_X = (GRID_W - (_C_W * 3 - 2)) // 2

PATTERNS = (
    ("CCC",         LETTER_C,    ((_CCC_X, _CCC_Y), (_CCC_X + _C_W, _CCC_Y),
                                  (_CCC_X + _C_W * 2, _CCC_Y))),
    ("RANDOM SOUP", None,        None),
    ("GLIDER GUN",  GOSPER_GUN,  None),
    ("PULSAR",      PULSAR,      None),
    ("R-PENTOMINO", R_PENTOMINO, None),
    ("ACORN",       ACORN,       None),
    ("GLIDERS",     GLIDER,      ((4, 4), (24, 13), (9, 30), (33, 41))),
    ("SPACESHIPS",  LWSS,        ((3, 6), (17, 23), (30, 39))),
    ("DIEHARD",     DIEHARD,     None),
)


# ------------------------------------------------------------------
# State
#
# One flat bytearray of 0/1 per cell, indexed y * GRID_W + x. Flat rather
# than a list of rows because slicing a bytearray is a native memcpy and
# comparing two of them is a native compare -- both used heavily below.
# ------------------------------------------------------------------
grid  = bytearray(CELLS)
drawn = bytearray(CELLS)   # what is currently in the bitmap, to skip redraws

# Horizontal neighbour sums, one row at a time: tri[y][x] is the number of
# live cells in the three-wide window centred on (x, y). Computing these
# once per row turns the eight lookups per cell that the naive version does
# into three, which is most of the reason this runs at a watchable rate.
tri      = [bytearray(GRID_W) for _ in range(GRID_H)]
tri_zero = bytearray(GRID_H)          # 1 when that row of tri is all zeros
ext      = bytearray(GRID_W + 2)      # one row with its wrapped edges attached
ZERO_ROW = bytes(GRID_W)

EMPTY_GRID = bytes(CELLS)             # for clearing, in one native memcpy
EMPTY_ROWS = bytes(GRID_H)

# Rows holding an ember. An all-dead row is skipped outright next step, and
# without this its embers would never be cleared.
ember_row = bytearray(GRID_H)

# The last three generations, for cycle detection. bytes() copies, so these
# do not alias the live grid.
prev1 = bytes(grid)
prev2 = prev1
prev3 = prev1

pattern_idx = START_PATTERN % len(PATTERNS)
speed_idx   = SPEED % len(SPEEDS)

generation = 0
population = 0
births     = 0
deaths     = 0

paused        = False
single_step   = False
settled       = False
settle_period = 0        # 1 = stopped dead, 2 or 3 = still oscillating
settle_at     = 0.0
pattern_at    = 0.0
next_step     = 0.0      # earliest monotonic time the next generation may run

flash_until = 0.0     # LEDs go white for a moment when a pattern loads
last_led    = 0.0

DEBOUNCE = 0.15
sw1_prev = True; sw1_last = 0.0
sw2_prev = True; sw2_last = 0.0
sw3_prev = True; sw3_last = 0.0


# ------------------------------------------------------------------
# Scene
#
# The bitmap is one pixel per cell -- 42x48, not 126x144. A Group with
# scale=CELL does the magnification, which happens in displayio's native
# code, so a cell change costs exactly one bitmap write however big the
# cells are drawn.
# ------------------------------------------------------------------
palette = displayio.Palette(4)
palette[C_DEAD]  = COL_DEAD
palette[C_NEW]   = COL_NEW
palette[C_LIVE]  = COL_LIVE
palette[C_EMBER] = COL_EMBER

bmp = displayio.Bitmap(GRID_W, GRID_H, 4)

scene = displayio.Group()

board_group = displayio.Group(scale=CELL, x=OX, y=0)
board_group.append(displayio.TileGrid(bmp, pixel_shader=palette))
scene.append(board_group)

# Status strip: its own bitmap, filled once and never touched again. Only
# the labels on top of it change.
strip_bmp = displayio.Bitmap(SCREEN_W, SCREEN_H - VIEW_H, 1)
strip_pal = displayio.Palette(1)
strip_pal[0] = COL_STRIP
scene.append(displayio.TileGrid(strip_bmp, pixel_shader=strip_pal, x=0, y=VIEW_H))

name_lbl = label.Label(terminalio.FONT, text="", color=COL_NAME,
                       x=2, y=LINE1_Y)
scene.append(name_lbl)

speed_lbl = label.Label(terminalio.FONT, text="", color=COL_SPEED)
speed_lbl.anchor_point = (1.0, 0.5)
speed_lbl.anchored_position = (SCREEN_W - 2, LINE1_Y)
scene.append(speed_lbl)

stat_lbl = label.Label(terminalio.FONT, text="", color=COL_STAT,
                       x=2, y=LINE2_Y)
scene.append(stat_lbl)

state_lbl = label.Label(terminalio.FONT, text="", color=0xFFC030)
state_lbl.anchor_point = (1.0, 0.5)
state_lbl.anchored_position = (SCREEN_W - 2, LINE2_Y)
scene.append(state_lbl)

display.root_group = scene


# ------------------------------------------------------------------
# Seeding
# ------------------------------------------------------------------
def stamp(rows, ox, oy):
    """Draw a block of pattern text into the grid, wrapping at the edges."""
    for j, row in enumerate(rows):
        base = ((oy + j) % GRID_H) * GRID_W
        for k in range(len(row)):
            if row[k] != ".":
                grid[base + (ox + k) % GRID_W] = 1


def repaint():
    """Resync the whole bitmap to the grid after a reseed.

    Everything alive is painted as newborn. Still goes through `drawn`, so
    the cells the old and new patterns happen to share cost nothing.
    """
    for y in range(GRID_H):
        base = y * GRID_W
        for x in range(GRID_W):
            c = C_NEW if grid[base + x] else C_DEAD
            if drawn[base + x] != c:
                drawn[base + x] = c
                bmp[x, y] = c


def load_pattern(idx, now):
    """Clear the board and seed pattern `idx`."""
    global pattern_idx, generation, population, births, deaths
    global settled, settle_period, settle_at, pattern_at, next_step
    global prev1, prev2, prev3, flash_until

    pattern_idx = idx % len(PATTERNS)
    name, rows, places = PATTERNS[pattern_idx]

    grid[:] = EMPTY_GRID
    ember_row[:] = EMPTY_ROWS

    if rows is None:
        for i in range(CELLS):
            if random.random() < DENSITY:
                grid[i] = 1
    elif places is None:
        w = 0
        for row in rows:
            if len(row) > w:
                w = len(row)
        stamp(rows, (GRID_W - w) // 2, (GRID_H - len(rows)) // 2)
    else:
        for ox, oy in places:
            stamp(rows, ox, oy)

    repaint()

    generation = 0
    population = sum(grid)
    births = population
    deaths = 0

    # Three distinct histories, so the first few generations cannot look
    # like a cycle just because the buffers all started equal.
    prev1 = bytes(grid)
    prev2 = b"\xff" * CELLS
    prev3 = b"\xfe" * CELLS

    settled = False
    settle_period = 0
    settle_at = now
    pattern_at = now
    next_step = now + SEED_HOLD
    flash_until = now + 0.3

    print("GameOfLife: %s -- %d cells alive" % (name, population))
    gc.collect()


# ------------------------------------------------------------------
# The simulation
#
# Two passes over the board. The first fills `tri` with horizontal
# neighbour sums; the second applies the rules, using tri[y-1] + tri[y] +
# tri[y+1] minus the cell itself as the neighbour count.
#
# The second pass writes back into `grid` as it goes, which is safe
# precisely because `tri` was built from the old grid and nothing in the
# second pass reads a neighbour's new state.
# ------------------------------------------------------------------
def step():
    global generation, population, births, deaths

    # -- pass 1: horizontal triples --
    for y in range(GRID_H):
        base = y * GRID_W
        row = grid[base:base + GRID_W]
        t = tri[y]
        if row == ZERO_ROW:
            # An empty row has empty triples. Both the compare and the
            # clear are native, so skipping GRID_W interpreted iterations
            # here is nearly free -- and most rows are empty for most of
            # the patterns in the catalogue.
            t[:] = ZERO_ROW
            tri_zero[y] = 1
            continue
        tri_zero[y] = 0
        ext[0] = row[GRID_W - 1]
        ext[1:GRID_W + 1] = row
        ext[GRID_W + 1] = row[0]
        for x in range(GRID_W):
            t[x] = ext[x] + ext[x + 1] + ext[x + 2]

    # -- pass 2: the rules, and paint only what changed --
    born = 0
    died = 0
    pop = 0
    for y in range(GRID_H):
        yn = y + 1
        if yn == GRID_H:
            yn = 0
        # tri[y - 1] wraps by itself: at y == 0 that is tri[-1], the last
        # row, which is exactly the torus neighbour we want.
        if tri_zero[y - 1] and tri_zero[y] and tri_zero[yn] and not ember_row[y]:
            continue

        ta = tri[y - 1]
        tb = tri[y]
        tc = tri[yn]
        base = y * GRID_W
        embers = 0

        for x in range(GRID_W):
            i = base + x
            was = grid[i]
            n = ta[x] + tb[x] + tc[x] - was

            if n == 3:
                alive = 1
            elif n == 2 and was:
                alive = 1
            else:
                alive = 0

            if alive:
                pop += 1
                if was:
                    c = C_LIVE
                else:
                    c = C_NEW
                    born += 1
                    grid[i] = 1
            elif was:
                c = C_EMBER
                died += 1
                embers = 1
                grid[i] = 0
            else:
                c = C_DEAD

            if drawn[i] != c:
                drawn[i] = c
                bmp[x, y] = c

        ember_row[y] = embers

    generation += 1
    population = pop
    births = born
    deaths = died


def check_settled(now):
    """Spot a board that is repeating itself at period 1, 2 or 3.

    That covers still lifes, blinkers and the pulsar, which is where the
    overwhelming majority of small boards end up. Anything with a longer
    period -- a glider circling the torus -- is still moving and is worth
    watching, so it deliberately does not count as settled.

    Period 1 means the board has genuinely stopped. Periods 2 and 3 are
    still animating, so they get held on screen for longer before the
    auto-advance takes them away.
    """
    global prev1, prev2, prev3, settled, settle_at, settle_period

    if grid == prev1:
        period = 1
    elif grid == prev2:
        period = 2
    elif grid == prev3:
        period = 3
    else:
        period = 0

    prev3 = prev2
    prev2 = prev1
    prev1 = bytes(grid)

    if period:
        if not settled:
            settled = True
            settle_at = now
            settle_period = period
            print("GameOfLife: settled at generation %d, population %d, period %d"
                  % (generation, population, period))
    else:
        settled = False
        settle_period = 0


# ------------------------------------------------------------------
# Status strip
# ------------------------------------------------------------------
def speed_text():
    rate = SPEEDS[speed_idx]
    return "MAX" if rate == 0 else "%d/s" % rate


def update_hud():
    """Refresh the four labels, returning True if anything actually moved.

    Assigning to Label.text re-renders the glyphs, so every one of these
    is guarded. At MAX speed the generation counter changes every frame
    and the pattern name never does.
    """
    changed = False

    name = PATTERNS[pattern_idx][0]
    if name_lbl.text != name:
        name_lbl.text = name
        changed = True

    sp = speed_text()
    if speed_lbl.text != sp:
        speed_lbl.text = sp
        changed = True

    stats = "G%d P%d" % (generation, population)
    if stat_lbl.text != stats:
        stat_lbl.text = stats
        changed = True

    if paused:
        state, colour = "PAUSE", CCC_PURPLE
    elif generation == 0:
        # Only true during SEED_HOLD -- the first step makes it 1.
        state, colour = "SEED", CCC_ORANGE
    elif population == 0:
        state, colour = "EMPTY", 0x8A6A78
    elif settled:
        state, colour = "SETTLED", 0xC08AF0
    else:
        state, colour = "RUN", CCC_ORANGE

    if state_lbl.text != state:
        state_lbl.text = state
        state_lbl.color = colour
        changed = True

    return changed


# ------------------------------------------------------------------
# NeoPixels -- population meter, coloured by which way it is heading
#
# Same two colours as the board, for the same reason: orange is growth,
# purple is what is left behind. Someone glancing at the LED strip from
# across the room gets the trend without reading the screen.
#
# The full-scale reference is 12% of the board rather than all of it. A
# random soup starts around 30% and pins the meter, then falls to a few
# percent as it burns down, and that early collapse is the interesting
# part to watch.
# ------------------------------------------------------------------
LED_FULL = max(1, int(CELLS * 0.12))

LED_GROW  = (255, 130, 10)     # orange -- more born than died
LED_FALL  = (140, 60, 255)     # purple -- more died than born
LED_LEVEL = (200, 90, 170)     # the two in balance


def update_leds(now):
    if not LEDS_ON:
        return

    if now < flash_until:
        pixels.fill((255, 210, 150))
        pixels.show()
        return

    if settled:
        # Slow purple breath, so a settled board still looks alive enough
        # that nobody assumes the badge has crashed.
        phase = (now - settle_at) * 2.0
        f = 0.30 + 0.40 * (1.0 - abs((phase % 2.0) - 1.0))
        c = (int(139 * f), int(92 * f), int(246 * f))
        for i in range(5):
            pixels[i] = c
        pixels.show()
        return

    if births > deaths:
        base = LED_GROW
    elif births < deaths:
        base = LED_FALL
    else:
        base = LED_LEVEL

    level = 5.0 * population / LED_FULL
    for i in range(5):
        f = level - i
        if f <= 0.0:
            pixels[i] = (0, 0, 0)
        else:
            if f > 1.0:
                f = 1.0
            pixels[i] = (int(base[0] * f), int(base[1] * f), int(base[2] * f))
    pixels.show()


# ------------------------------------------------------------------
# Go
# ------------------------------------------------------------------
print("GameOfLife: %dx%d grid, %d cells, %d px per cell"
      % (GRID_W, GRID_H, CELLS, CELL))

start = time.monotonic()
load_pattern(pattern_idx, start)   # this is what arms next_step
update_hud()
display.refresh()
bl.value = True

while True:
    now = time.monotonic()

    # -- buttons --
    v1, v2, v3 = sw1.value, sw2.value, sw3.value

    # SW1 + SW3 together leaves. The single-button handlers below may fire
    # a frame early on the way here and change pattern or pause state;
    # supervisor.reload() throws all of that away, so it does not matter.
    if (not v1) and (not v3):
        print("SW1+SW3 -- returning to the menu")
        pixels.fill((0, 0, 0))
        pixels.show()
        supervisor.reload()

    pressed1 = (not v1) and sw1_prev and (now - sw1_last) > DEBOUNCE
    pressed2 = (not v2) and sw2_prev and (now - sw2_last) > DEBOUNCE
    pressed3 = (not v3) and sw3_prev and (now - sw3_last) > DEBOUNCE
    sw1_prev, sw2_prev, sw3_prev = v1, v2, v3

    if pressed1:
        sw1_last = now
        load_pattern(pattern_idx + 1, now)   # sets next_step past the seed hold

    if pressed2:
        sw2_last = now
        if paused:
            single_step = True
        else:
            speed_idx = (speed_idx + 1) % len(SPEEDS)
            next_step = now
            print("GameOfLife: speed", speed_text())

    if pressed3:
        sw3_last = now
        paused = not paused
        next_step = now

    # -- simulate --
    stepped = False
    if single_step:
        single_step = False
        step()
        check_settled(now)
        stepped = True
    elif not paused and now >= next_step:
        step()
        check_settled(now)
        stepped = True
        rate = SPEEDS[speed_idx]
        # Set from `now` rather than advancing by a period, so coming back
        # from a pause does not burn through a backlog of missed steps.
        next_step = (now + 1.0 / rate) if rate else now

    # -- move on when there is nothing left to watch --
    if stepped:
        hold = OSC_HOLD if settle_period == 3 else STILL_HOLD
        if settled and AUTO_ADVANCE and (now - settle_at) >= hold:
            load_pattern(pattern_idx + 1, now)
        elif PATTERN_TIMEOUT and (now - pattern_at) >= PATTERN_TIMEOUT:
            print("GameOfLife: %ds up, next pattern" % PATTERN_TIMEOUT)
            load_pattern(pattern_idx + 1, now)

    # -- present --
    if update_hud() or stepped:
        display.refresh()

    if now - last_led >= 0.05:
        last_led = now
        update_leds(now)

    # Nothing here is allowed to block for long, but a paused or slow board
    # has no reason to spin the CPU flat out either.
    if not stepped:
        time.sleep(0.005)
