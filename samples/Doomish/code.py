"""
code_Doomish.py -- Carolina Code Conference sample
==================================================
A tiny Doom-like that plays itself. The badge runs the fast half of the
loop -- raycasting, movement, shooting -- while a language model on the
network runs the slow half and sends back one word telling the badge what
it should be trying to do. This file is the fast half.

The bottom strip of the display always shows the current directive. That
line is the whole point: reflexes at 20 fps, judgment every few seconds.

Controls
--------
  SW1 (IO1)   -- toggle view: 3D raycast / top-down
  SW2 (IO2)   -- toggle the LED status channel
  SW3 (IO43)  -- pause the AI (freeze in place)
  SW1 + SW3   -- exit to the Launcher menu

The loop is OODA, and the four functions are named observe / orient /
decide / act so the code and the design document read the same.

Reflexes live in Decide and are never overridden: the badge shoots what is
in front of it, retreats when it is nearly dead, and breaks contact when it
is out of ammo, whatever the directive says. Everything calmer is scored,
and the directive is a large thumb on the scale rather than a command.

The badge broadcasts its state and a relay on the network answers with one
word, a couple of seconds later. Pull the plug, or turn up somewhere with
hostile wifi, and the reflexes and the badge's own navigation carry the game
on their own.
"""

# ------------------------------------------------------------------
# Backlight off FIRST, before the slow adafruit imports.
# The panel powers up bright white and those imports take a couple of
# seconds on a cold boot. Same trick the Launcher uses.
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

BADGE_ID  = "badge-01"   # who this badge says it is on the network

VIEW_MODE = 0            # 0 = 3D raycast, 1 = top-down. SW1 toggles.
ROTATION  = 90           # 90 = landscape 160x128, 0 = portrait 128x160
RAY_COLS  = 40           # raycast columns. Fewer = faster and chunkier.
SHOW_FPS  = True         # frame rate in the top-right corner

MOVE_SPEED = 2.2         # tiles per second
TURN_SPEED = 4.5         # radians per second. Act does one thing per frame,
                         # so every turn is frames not spent walking. At 2.4
                         # a 90 degree corner cost 13 frames against the 5 it
                         # takes to cross the tile after it, and a badge in a
                         # one-tile-wide maze spent most of its life turning.

# The world. 32 rows of 32 characters, and both of those are checked at
# boot so a typo tells you the row number instead of drawing nonsense.
#
#   #  wall        .  floor
#   E  enemy       M  medkit       A  ammo
#
# E/M/A tiles are floor as far as walking and raycasting are concerned;
# the letter only says what spawns there.
WORLD = (
    "################################",
    "#...#.....#.................#.##",
    "###.#####.#.#####.#####.###...##",
    "#.#.............#.......#...#.##",
    "#.#.....A.####M...#.#####.#.#.##",
    "#.#.......#.....#.#...#.#..E#.##",
    "#.#...E...#.###.#.#.#.#.#.#.#.##",
    "#.#.......#.....#.#.#.#.......##",
    "#.#.M.....#######.#.#.#######.##",
    "#.#.#.#.#.......#...#.....#.#.##",
    "#.#.#.#######.#.#.#######.#.#.##",
    "#...#.........#.#.#.......#.#.##",
    "#.#####.##..#.#...###.#.###.#.##",
    "#.....#.....#.#.#A....#.#.....##",
    "####.##..####...#######.#.######",
    "#.....#...#.#..E........#.#...##",
    "#.###.###.#.#.##.#####.##.###.##",
    "#...#...#.#...#.........#.#...##",
    "###.###...#####.#..####.#.#..###",
    "#...#.....#.....#.....#.#.#...##",
    "#.###.###.#.#####.###.........##",
    "#.#.A.#.....#...#.........E...##",
    "#.#.###.#####.###.###.........##",
    "#.......#.......#.............##",
    "#.#############.#####...E..A..##",
    "#.......#.....#...............##",
    "#######.#.###.#.###.#.M.......##",
    "#....E..#.#...#.....#.........##",
    "#.###.###.#.#######.#.###.###.##",
    "#.........#.........#.....#...##",
    "################################",
    "################################",
)

START_X, START_Y = 4.5, 4.5   # tile centre, must be floor
START_ANGLE      = 0.0        # radians, 0 = +x = east

# --- Gameplay -------------------------------------------------
# This demo is watched, not played. It is tuned so a spectator can follow
# what is happening: a badge on a lanyard that dies in twenty seconds is a
# worse demo than one that never dies at all.

CRITICAL_HP   = 35      # below this, contact with an enemy means retreat
FIRE_CONE     = 0.20    # radians off-centre that still counts as aimed
FIRE_INTERVAL = 0.35    # seconds between the player's shots
FIRE_DAMAGE   = 34      # so an enemy takes three hits, about a second
SIGHT_RANGE   = 12.0    # tiles the player can notice an enemy across
ITEM_RANGE    = 10.0    # tiles an item registers from
PICKUP_RANGE  = 0.6     # tiles, how close counts as walking over it

ENEMY_HP       = 100
ENEMY_RANGE    = 9.0    # tiles an enemy will shoot from
ENEMY_INTERVAL = 1.2    # seconds between an enemy's shots
ENEMY_DAMAGE   = 6      # one enemy alone takes ~20 s to kill you
MEDKIT_HEAL    = 40
AMMO_PICKUP    = 12

# Directive pacing. The relay really does take 2 to 4 seconds to answer, and
# everything downstream is built to tolerate that.
DIRECTIVE_MIN_INTERVAL = 5.0    # floor, so a calm badge does not spam
DIRECTIVE_MAX_AGE      = 20.0   # ceiling, so a pinned badge still refreshes
# --- Networking -----------------------------------------------
# The badge broadcasts and the relay answers unicast to wherever the beacon
# came from, so neither end needs the other's address.
#
# RELAY_HOST is the field repair. If a venue AP isolates its clients,
# broadcast never arrives; putting the Pi's IP here takes broadcast out of
# the picture without touching another line. It is also what you want when
# running the simulator under WSL2, which is NAT'd onto its own subnet and
# cannot broadcast to the LAN at all.
# An IP literal, never a hostname: CircuitPython resolves the host on every
# sendto(), which would put a DNS lookup inside the frame loop.
RELAY_HOST = ""          # "" = broadcast to 255.255.255.255
RELAY_PORT = 5115        # where the relay listens
BADGE_PORT = 5116        # where the answer comes back

DIRECTIVE_TIMEOUT = 12.0 # give up on an unanswered beacon after this
NET_STALE         = 45.0 # silence for this long and the strip says LOCAL
NET_RETRY         = 20.0 # seconds between reconnect attempts once the link is
                         # down. Associating blocks, so this is how often the
                         # badge is allowed to stall a frame trying.
NET_CONNECT_TIMEOUT = 6.0

# Pin this to one of the eight vocabulary words to watch a single directive
# drive the badge, with no relay involved at all. None is normal.
PIN_DIRECTIVE = None

# ==============================================================


import os
import time
import json
import math
import random
import busio
import wifi
import socketpool
import displayio
import fourwire
import neopixel
import terminalio
import bitmaptools
import supervisor
import adafruit_st7735r
from adafruit_display_text import label


# ------------------------------------------------------------------
# Hardware setup
# ------------------------------------------------------------------
pixels = neopixel.NeoPixel(board.IO4, 5, brightness=0.35, auto_write=False)
pixels.fill((0, 0, 0)); pixels.show()

sw1 = digitalio.DigitalInOut(board.IO1);  sw1.switch_to_input(pull=digitalio.Pull.UP)
sw2 = digitalio.DigitalInOut(board.IO2);  sw2.switch_to_input(pull=digitalio.Pull.UP)
sw3 = digitalio.DigitalInOut(board.IO43); sw3.switch_to_input(pull=digitalio.Pull.UP)

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

# Read the size back rather than hardcoding it. displayio swaps width and
# height for rotation 90/270, so this is the only thing that has to change
# when ROTATION does -- which makes flipping that constant the entire
# fallback if landscape misbehaves on the real panel.
SCREEN_W = display.width
SCREEN_H = display.height


# ------------------------------------------------------------------
# Tables and helpers
# ------------------------------------------------------------------
MAP_W = len(WORLD[0])
MAP_H = len(WORLD)

# Palette indices, named so the renderers read like English. 16 entries
# means displayio packs the bitmap at 4 bits per pixel.
C_SKY     = 0
C_FLOOR   = 1
C_XWALL   = 2    # 2,3,4  -- near, mid, far
C_YWALL   = 5    # 5,6,7  -- the other face, darker, so corners read
C_ENEMY   = 8
C_MEDKIT  = 9
C_AMMO    = 10
C_PLAYER  = 11
C_UNSEEN  = 12
C_SEEN    = 13
C_WALL2D  = 14
C_WHITE   = 15

PALETTE_RGB = (
    0x000000, 0x1A1F26,
    0xB0743A, 0x7A5028, 0x442C15,
    0x8A5A2B, 0x5E3D1D, 0x33210F,
    0xFF3020, 0x20FF60, 0xFFD020,
    0x30E0FF, 0x0A0A0C, 0x2A2F36, 0x6A7078, 0xFFFFFF,
)

# Parse the world once, into a flat bytearray. Indexing a bytearray is a
# single operation; indexing a tuple of strings is two plus a character
# compare, and the raycaster does that thousands of times a second.
tiles = bytearray(MAP_W * MAP_H)
spawns = []          # (kind, tile_x, tile_y) -- step 3 turns these into actors
OPEN_TILE_COUNT = 0

for _y in range(MAP_H):
    _row = WORLD[_y]
    if len(_row) != MAP_W:
        raise ValueError("WORLD row %d is %d chars, expected %d"
                         % (_y, len(_row), MAP_W))
    for _x in range(MAP_W):
        _c = _row[_x]
        if _c == "#":
            tiles[_y * MAP_W + _x] = 1
            continue
        OPEN_TILE_COUNT += 1
        if _c == "E":
            spawns.append(("enemy", _x, _y))
        elif _c == "M":
            spawns.append(("medkit", _x, _y))
        elif _c == "A":
            spawns.append(("ammo", _x, _y))
        elif _c != ".":
            raise ValueError("WORLD row %d col %d: unknown tile %r" % (_y, _x, _c))

# Entities are plain lists rather than objects or dicts: they are touched
# several times a frame and a list index is the cheapest thing MicroPython
# does. These names are the field offsets.
EX, EY, KIND, ALIVE, EHP, ENEXT = 0, 1, 2, 3, 4, 5
E_ENEMY, E_MEDKIT, E_AMMO = 0, 1, 2

_KIND_OF = {"enemy": E_ENEMY, "medkit": E_MEDKIT, "ammo": E_AMMO}

entities = []


def reset_entities():
    """Rebuild every enemy and item from the map. Called at boot and on
    respawn, so death costs progress without costing the explored overlay."""
    del entities[:]
    for kind, tx, ty in spawns:
        entities.append([tx + 0.5, ty + 0.5, _KIND_OF[kind], True, ENEMY_HP, 0.0])


# Explored-tile mask, one byte per tile. Kept as a count as well so the
# network beacon can report progress with a division instead of a scan.
explored = bytearray(MAP_W * MAP_H)
explored_count = 0


def is_wall(tx, ty):
    """True for a wall or anything off the edge of the map."""
    if tx < 0 or ty < 0 or tx >= MAP_W or ty >= MAP_H:
        return True
    return tiles[ty * MAP_W + tx] == 1


# Trig lookup. math.sin on the ESP32-S3 is soft-float and this runs per
# frame, so quantise the heading to 512 steps (0.7 degrees) and never call
# it again after boot. array("f") keeps the two tables at 2 KB each rather
# than the ~8 KB a list of float objects would cost.
from array import array

TWO_PI    = 2.0 * math.pi
ANG_STEPS = 512
ANG_MASK  = ANG_STEPS - 1
ANG_SCALE = ANG_STEPS / TWO_PI

SIN_T = array("f", (math.sin(i * 2.0 * math.pi / ANG_STEPS) for i in range(ANG_STEPS)))
COS_T = array("f", (math.cos(i * 2.0 * math.pi / ANG_STEPS) for i in range(ANG_STEPS)))

FOV = 0.66          # half-width of the camera plane; ~66 degrees horizontal

# Per-column camera offset, -1 at the left edge to +1 at the right, and the
# pixel span each column covers. COL_X has RAY_COLS+1 entries so the columns
# tile the screen exactly even when RAY_COLS does not divide the width.
CAMERA_X = [0.0] * RAY_COLS
COL_X    = [0] * (RAY_COLS + 1)
for _i in range(RAY_COLS):
    CAMERA_X[_i] = 2.0 * (_i + 0.5) / RAY_COLS - 1.0
for _i in range(RAY_COLS + 1):
    COL_X[_i] = (_i * SCREEN_W) // RAY_COLS

# The bottom band belongs to the directive strip, so the viewport both
# renderers draw into is shorter than the screen. Keeping the strip out of
# the viewport bitmap means it is drawn once at boot instead of being
# cleared and redrawn every frame.
STRIP_H = 12
VIEW_H  = SCREEN_H - STRIP_H

# Top-down geometry, also fixed at boot.
MAP_SCALE = max(1, min(SCREEN_W // MAP_W, VIEW_H // MAP_H))
MAP_OX    = (SCREEN_W - MAP_W * MAP_SCALE) // 2
MAP_OY    = (VIEW_H - MAP_H * MAP_SCALE) // 2


def clamp(v, lo, hi):
    return lo if v < lo else (hi if v > hi else v)


# ------------------------------------------------------------------
# State
# ------------------------------------------------------------------
player_x = START_X
player_y = START_Y
player_a = START_ANGLE
turn_dir = 0         # 0 = walking, +1 = turning left, -1 = turning right

hp   = 100
ammo = 24

view_mode = VIEW_MODE
leds_on   = True
ai_paused = False

directive     = "LOCAL"
directive_why = "no relay yet"
directive_at  = 0.0      # when the current directive arrived
recent        = []       # last few directives, capped at 6, for the model

# The request is fired from inside Decide, never on a timer. Step 4 swaps
# the stub for a socket and these three variables keep their meaning.
seq            = 0
request_flight = False   # a request is out and no answer has come back
request_at     = 0.0
last_request   = -999.0

# What Decide chose. Act is the only function that touches player state, so
# these two are the entire channel between deciding and doing.
action         = "HOLD"
action_heading = 0.0
urgent         = False

# The tile Decide is currently walking to: [x, y, active]. A list rather
# than three globals so Decide can update it without a global statement.
goal = [0, 0, False]

# The tile we were on before this one, so the scoring can prefer not to
# double back. Not a veto: a dead end has to be reversible.
last_tile = [-1, -1]

# Per-frame scratch for the move scoring, allocated once rather than rebuilt
# forty times a second.
legal   = [False] * 4
weights = [0.0] * 4

# Frames spent trying to reach the current goal, so an unreachable one is
# abandoned rather than chased forever.
stall = [0]

# How often the badge has stood on each tile lately, and when that count was
# last decayed. This is the anti-livelock: a directive can name a direction
# that is legal here and a dead end one tile on, and then the badge walks
# A -> B, finds nothing to score at B, gets routed back to A by the frontier,
# and the directive sends it to B again. Nothing in the scoring notices,
# because each individual move is the best one available on the tile it is
# made from. Charging a tile for being revisited is what breaks the cycle:
# after a few laps the penalty outgrows the directive's +10 and the badge
# picks a different neighbour. It decays, so a corridor the badge legitimately
# needs to cross twice does not become permanently unattractive.
# Where the badge was when the stuck-check last looked, when it looked, and
# until when the directive is being ignored. This is the watchdog of last
# resort: everything above is meant to keep the badge moving, and this is
# what catches the case where it did not. A directive can name a direction
# that is locally sensible on every tile of a small pocket and still trap the
# badge in it, and pinning one by hand for a demo makes that easy to hit.
# Ten seconds of going nowhere hands navigation to the frontier search for
# six, which is long enough to walk out of any pocket on a 32x32 map.
_anchor = [0.0, 0.0, 0.0]
_ignore_directive_until = [0.0]
STUCK_WINDOW = 8.0
STUCK_RADIUS = 1.5
STUCK_RELEASE = 12.0     # longer than the window, so a badge that is still
                         # stuck when the release expires gets another one
                         # rather than alternating stuck-free-stuck-free

visits = bytearray(MAP_W * MAP_H)
VISIT_PENALTY  = 2.0
VISIT_CAP      = 7
VISIT_DECAY    = 12.0     # seconds between decays
_visit_decay_at = [0.0]

next_shot   = 0.0        # player's own weapon cooldown
deaths      = 0
snapshot      = None
prev_snapshot = None

# Debounce by timestamp, not by time.sleep(). Nameplate sleeps 0.12 s after
# each press, which is fine there and impossible here: nothing in this loop
# is allowed to block. Same idea as the tail of samples/LEDLab/code.py.
DEBOUNCE = 0.15
sw1_prev = True; sw1_last = 0.0
sw2_prev = True; sw2_last = 0.0
sw3_prev = True; sw3_last = 0.0

frame_ms   = 0.0     # rolling average, milliseconds
fps_text   = ""
last_led   = 0.0
last_trace = 0.0
muzzle_until = 0.0   # LED 3 stays white until this timestamp


# ------------------------------------------------------------------
# Scene
# ------------------------------------------------------------------
palette = displayio.Palette(len(PALETTE_RGB))
for _i in range(len(PALETTE_RGB)):
    palette[_i] = PALETTE_RGB[_i]

viewport = displayio.Bitmap(SCREEN_W, VIEW_H, len(PALETTE_RGB))

scene = displayio.Group()
scene.append(displayio.TileGrid(viewport, pixel_shader=palette))

# Directive strip: its own bitmap below the viewport, filled once and never
# touched again. The label on top of it is the only thing that changes.
strip_bmp = displayio.Bitmap(SCREEN_W, STRIP_H, 1)
strip_pal = displayio.Palette(1)
strip_pal[0] = 0x101828
scene.append(displayio.TileGrid(strip_bmp, pixel_shader=strip_pal, x=0, y=VIEW_H))

hp_lbl = label.Label(terminalio.FONT, text="", color=0xFFFFFF, x=2, y=6)
scene.append(hp_lbl)

fps_lbl = label.Label(terminalio.FONT, text="", color=0x808890)
fps_lbl.anchor_point = (1.0, 0.0)
fps_lbl.anchored_position = (SCREEN_W - 2, 1)
scene.append(fps_lbl)

# Amber, because nothing else on screen is, and this is the line people are
# meant to read over your shoulder.
dir_lbl = label.Label(terminalio.FONT, text="", color=0xFFC030,
                      x=2, y=VIEW_H + STRIP_H // 2)
scene.append(dir_lbl)

display.root_group = scene


# ------------------------------------------------------------------
# Render
# ------------------------------------------------------------------
# The map border is solid, so a ray always terminates. The cap is a
# seatbelt against an edited WORLD with a hole in the outer wall.
MAX_DDA_STEPS = MAP_W + MAP_H
MAX_VIEW      = float(MAX_DDA_STEPS)

# Set by cast_ray(): 0 = the ray hit a wall face perpendicular to x, 1 = to y.
ray_side = 0

# Perpendicular wall distance per ray column, filled by render_raycast() and
# read by the sprite pass so entities are hidden behind walls.
zbuf = [MAX_VIEW] * RAY_COLS


def cast_ray(ox, oy, rx, ry, limit):
    """Grid DDA. Distance from (ox, oy) along the unit ray (rx, ry) to the
    first wall, or `limit` if nothing is hit within it.

    The renderer and line_of_sight() both call this, so the file contains
    exactly one grid traversal. The face that was hit comes back through the
    module global `ray_side` rather than in a returned tuple: this runs forty
    times a frame, and a tuple per call is ~25 KB/s of garbage on a board
    with no PSRAM.
    """
    global ray_side

    map_x = int(ox)
    map_y = int(oy)

    # Distance the ray covers crossing one full tile on each axis. A
    # perfectly axis-aligned ray never crosses the other axis at all.
    delta_x = 1e30 if rx == 0.0 else abs(1.0 / rx)
    delta_y = 1e30 if ry == 0.0 else abs(1.0 / ry)

    if rx < 0.0:
        step_x = -1
        side_x = (ox - map_x) * delta_x
    else:
        step_x = 1
        side_x = (map_x + 1.0 - ox) * delta_x

    if ry < 0.0:
        step_y = -1
        side_y = (oy - map_y) * delta_y
    else:
        step_y = 1
        side_y = (map_y + 1.0 - oy) * delta_y

    for _ in range(MAX_DDA_STEPS):
        if side_x < side_y:
            side_x += delta_x
            map_x += step_x
            ray_side = 0
            if side_x - delta_x > limit:
                return limit
        else:
            side_y += delta_y
            map_y += step_y
            ray_side = 1
            if side_y - delta_y > limit:
                return limit
        if is_wall(map_x, map_y):
            return (side_x - delta_x) if ray_side == 0 else (side_y - delta_y)

    return limit


def line_of_sight(ox, oy, tx, ty):
    """True if nothing solid stands between the two points."""
    dx = tx - ox
    dy = ty - oy
    dist = math.sqrt(dx * dx + dy * dy)
    if dist < 0.001:
        return True
    # A shade short of the target, so an entity standing against a wall is
    # not occluded by the wall it is standing against.
    return cast_ray(ox, oy, dx / dist, dy / dist, dist) >= dist - 0.02


def render_raycast():
    """Textureless DDA raycaster. One fill_region per wall slice."""
    # Clear with fill(), never a full-screen fill_region: 0.07 ms against
    # 38 ms in the simulator, and it is the same call on hardware.
    viewport.fill(C_SKY)

    ai = int(player_a * ANG_SCALE) & ANG_MASK
    dir_x = COS_T[ai]
    dir_y = SIN_T[ai]
    plane_x = -dir_y * FOV
    plane_y = dir_x * FOV
    half = VIEW_H >> 1

    for c in range(RAY_COLS):
        cam = CAMERA_X[c]
        dist = cast_ray(player_x, player_y,
                        dir_x + plane_x * cam, dir_y + plane_y * cam, MAX_VIEW)
        side = ray_side

        if dist < 0.05:          # standing in a doorway, do not divide by ~0
            dist = 0.05
        zbuf[c] = dist

        line_h = int(VIEW_H / dist)
        top = half - (line_h >> 1)
        bot = top + line_h

        # Clamp explicitly. Out-of-bounds writes silently no-op in the
        # simulator, and hardware has never promised to do the same.
        d_top = clamp(top, 0, VIEW_H)
        d_bot = clamp(bot, 0, VIEW_H)

        x0 = COL_X[c]
        x1 = COL_X[c + 1]

        if d_bot > d_top:
            base = C_XWALL if side == 0 else C_YWALL
            shade = 0 if dist < 3.0 else (1 if dist < 7.0 else 2)
            bitmaptools.fill_region(viewport, x0, d_top, x1, d_bot, base + shade)

        if d_bot < VIEW_H:
            bitmaptools.fill_region(viewport, x0, d_bot, x1, VIEW_H, C_FLOOR)

    render_sprites(dir_x, dir_y, plane_x, plane_y, half)


def render_sprites(dir_x, dir_y, plane_x, plane_y, half):
    """Draw live entities as flat blocks, clipped against the wall depths.

    Not in the step plan, which specifies walls only. Added because the
    raycast view is the screen people watch, and without this the badge
    stands in an empty corridor firing at nothing.
    """
    inv_det = plane_x * dir_y - dir_x * plane_y
    if inv_det == 0.0:
        return
    inv_det = 1.0 / inv_det

    for ent in entities:
        if not ent[ALIVE]:
            continue

        sx = ent[EX] - player_x
        sy = ent[EY] - player_y

        # Into camera space. depth is distance along the view axis, which is
        # the same quantity zbuf holds, so the comparison below is valid.
        across = inv_det * (dir_y * sx - dir_x * sy)
        depth = inv_det * (-plane_y * sx + plane_x * sy)
        if depth < 0.2 or depth > SIGHT_RANGE:
            continue

        size = int(VIEW_H / depth * 0.55)
        if size < 2:
            continue

        centre = int((SCREEN_W >> 1) * (1.0 + across / depth))
        top = clamp(half - (size >> 1), 0, VIEW_H)
        bot = clamp(half + (size >> 1), 0, VIEW_H)
        if bot <= top:
            continue

        colour = C_ENEMY if ent[KIND] == E_ENEMY else (
            C_MEDKIT if ent[KIND] == E_MEDKIT else C_AMMO)

        # Walk the ray columns the sprite covers and drop the ones with a
        # nearer wall in front. Column granularity, not pixel: the wall
        # slices are drawn at that granularity too, so it lines up.
        c0 = clamp((centre - (size >> 1)) * RAY_COLS // SCREEN_W, 0, RAY_COLS)
        c1 = clamp((centre + (size >> 1)) * RAY_COLS // SCREEN_W + 1, 0, RAY_COLS)
        for c in range(c0, c1):
            if depth >= zbuf[c]:
                continue
            x0 = COL_X[c]
            x1 = COL_X[c + 1]
            if x1 > x0:
                bitmaptools.fill_region(viewport, x0, top, x1, bot, colour)


def render_topdown():
    """The fallback view, and the one that has to work.

    If the raycaster turns out to be too slow on the real badge, SW1 or the
    VIEW_MODE constant switches to this and nothing else in the file changes.
    """
    viewport.fill(C_UNSEEN)
    s = MAP_SCALE

    for ty in range(MAP_H):
        row = ty * MAP_W
        py = MAP_OY + ty * s
        for tx in range(MAP_W):
            i = row + tx
            if not explored[i]:
                continue          # fog: unseen tiles stay background
            colour = C_WALL2D if tiles[i] else C_SEEN
            px = MAP_OX + tx * s
            bitmaptools.fill_region(viewport, px, py, px + s, py + s, colour)

    for ent in entities:
        if not ent[ALIVE]:
            continue
        tx = int(ent[EX])
        ty = int(ent[EY])
        if not explored[ty * MAP_W + tx]:
            continue
        if ent[KIND] == E_ENEMY:
            colour = C_ENEMY
        elif ent[KIND] == E_MEDKIT:
            colour = C_MEDKIT
        else:
            colour = C_AMMO
        px = MAP_OX + tx * s
        py = MAP_OY + ty * s
        bitmaptools.fill_region(viewport, px, py, px + s, py + s, colour)

    # Player dot, then a tick showing which way they are looking.
    px = MAP_OX + int(player_x * s)
    py = MAP_OY + int(player_y * s)
    bx0 = clamp(px - 1, 0, SCREEN_W)
    by0 = clamp(py - 1, 0, VIEW_H)
    bx1 = clamp(px + 2, 0, SCREEN_W)
    by1 = clamp(py + 2, 0, VIEW_H)
    if bx1 > bx0 and by1 > by0:
        bitmaptools.fill_region(viewport, bx0, by0, bx1, by1, C_PLAYER)

    ai = int(player_a * ANG_SCALE) & ANG_MASK
    for k in range(2, s * 3):
        tx = px + int(COS_T[ai] * k)
        ty = py + int(SIN_T[ai] * k)
        if 0 <= tx < SCREEN_W and 0 <= ty < VIEW_H:
            viewport[tx, ty] = C_WHITE


def render():
    """One call site, two renderers. Keep this boundary clean -- it is the
    pre-agreed degradation plan."""
    if view_mode == 0:
        render_raycast()
    else:
        render_topdown()


# ------------------------------------------------------------------
# Movement, exploration, HUD, LEDs
# ------------------------------------------------------------------
PLAYER_R = 0.22          # collision radius in tiles


def blocked(x, y):
    """True if a player-sized box centred on (x, y) overlaps a wall."""
    return (is_wall(int(x - PLAYER_R), int(y - PLAYER_R)) or
            is_wall(int(x + PLAYER_R), int(y - PLAYER_R)) or
            is_wall(int(x - PLAYER_R), int(y + PLAYER_R)) or
            is_wall(int(x + PLAYER_R), int(y + PLAYER_R)))


def try_move(nx, ny):
    """Move one axis at a time so a glancing hit slides along the wall
    instead of stopping dead in the corridor."""
    global player_x, player_y
    if not blocked(nx, player_y):
        player_x = nx
    if not blocked(player_x, ny):
        player_y = ny


def mark_explored():
    """Light up the tiles around the player. Done here rather than inside
    the raycaster so the top-down view fogs correctly even if the 3D view
    is never switched on."""
    global explored_count
    cx = int(player_x)
    cy = int(player_y)
    for dy in range(-2, 3):
        ty = cy + dy
        if ty < 0 or ty >= MAP_H:
            continue
        row = ty * MAP_W
        for dx in range(-2, 3):
            tx = cx + dx
            if tx < 0 or tx >= MAP_W:
                continue
            if not explored[row + tx]:
                explored[row + tx] = 1
                # Walls get marked so the top-down view can draw them, but
                # only floor counts toward progress. OPEN_TILE_COUNT is the
                # denominator and it does not include walls.
                if not tiles[row + tx]:
                    explored_count += 1


def side_clearance(ai, reach):
    """How far the ray at table index `ai` gets before a wall, in probe steps."""
    dx = COS_T[ai]
    dy = SIN_T[ai]
    for k in range(1, reach + 1):
        if blocked(player_x + dx * k * 0.5, player_y + dy * k * 0.5):
            return k
    return reach + 1


HUD_CHARS = SCREEN_W // 6 - 1        # terminalio.FONT is 6 px wide

FACINGS = ("E", "S", "W", "N")       # +y is south on screen


def facing():
    ai = int(player_a * ANG_SCALE) & ANG_MASK
    return FACINGS[((ai + ANG_STEPS // 8) & ANG_MASK) * 4 // ANG_STEPS]


def clip(text, n):
    """Trim to n characters on a word boundary.

    Three dots, not an ellipsis character: terminalio.FONT has no glyph for
    one. The directive strip is the line people read over your shoulder, and
    a word cut in half reads worse than a word left off.
    """
    if len(text) <= n:
        return text
    if n <= 3:
        return "..."
    cut = text.rfind(" ", 0, n - 2)
    return (text[:cut] if cut > 0 else text[:n - 3]) + "..."


def update_hud():
    hp_lbl.text = "HP %d  AMMO %d" % (hp, ammo)
    fps_lbl.text = fps_text if SHOW_FPS else ""

    # The directive word always survives whole. Only the why gets trimmed,
    # and it is dropped entirely rather than shown as a stub.
    room = HUD_CHARS - len(directive) - 2
    if directive_why and room >= 6:
        dir_lbl.text = "%s  %s" % (directive, clip(directive_why, room))
    else:
        dir_lbl.text = clip(directive, HUD_CHARS)


def update_leds(now):
    """Five pixels as a second status channel, readable across a room."""
    if not leds_on:
        return

    frac = hp / 100.0
    if frac > 0.6:
        base = (0, 255, 40)
    elif frac > 0.3:
        base = (255, 150, 0)
    else:
        base = (255, 20, 0)

    # 0-2: HP bar. Each pixel is a third, and the last lit one dims as that
    # third drains, so the bar reads smoothly rather than in three jumps.
    for i in range(3):
        level = clamp(frac * 3.0 - i, 0.0, 1.0)
        pixels[i] = (int(base[0] * level), int(base[1] * level), int(base[2] * level))

    # 3: muzzle flash. Step 3 sets muzzle_until when a shot goes out.
    pixels[3] = (255, 255, 255) if now < muzzle_until else (0, 0, 0)

    # 4: the network. Bright cyan for a beat when a directive lands, a dim
    # blue idle while the link is up, dark when there is no relay at all.
    if now < net_pulse_until:
        pixels[4] = (0, 255, 255)
    elif not net_up:
        pixels[4] = (0, 0, 0)
    elif request_flight:
        pixels[4] = (0, 40, 60)
    else:
        pixels[4] = (0, 0, 20)

    pixels.show()


# ------------------------------------------------------------------
# OODA -- Observe
# ------------------------------------------------------------------
# Four functions, called in this order, every frame. The names come from
# plans/gameplay.md and are worth more than any micro-optimisation here:
# this loop is the thing the talk is about.

DIR_NAME = ("N", "S", "E", "W")
DIR_DX   = (0, 0, 1, -1)
DIR_DY   = (-1, 1, 0, 0)
DIR_ANG  = (3.0 * math.pi / 2.0, math.pi / 2.0, 0.0, math.pi)
OPPOSITE = {"N": "S", "S": "N", "E": "W", "W": "E"}

# Entity references for whatever is currently visible, nearest first, held
# alongside the snapshot rather than inside it. The snapshot has to stay
# JSON-shaped because step 4 puts it on the wire unchanged.
seen_enemies = []
seen_items   = []
seen_dist    = []      # distances alongside, to keep both lists sorted
item_dist    = []

# Everything ever seen and not yet dealt with. The directive table talks
# about the "nearest known enemy" and the "last known medkit", and known is
# not the same as visible: any enemy actually in view trips a reflex, so a
# HUNT weighted on sight alone would never once get to apply. Memory is
# what lets HUNT walk you toward something around a corner.
known = []


def remember(ent):
    for e in known:
        if e is ent:
            return
    known.append(ent)


def nearest_known(kind):
    """Closest remembered entity of a kind, forgetting anything now dead."""
    best = None
    best_d = 1e9
    i = 0
    while i < len(known):
        ent = known[i]
        if not ent[ALIVE]:
            del known[i]
            continue
        i += 1
        if kind is not None and ent[KIND] != kind:
            continue
        dx = ent[EX] - player_x
        dy = ent[EY] - player_y
        d = dx * dx + dy * dy
        if d < best_d:
            best_d = d
            best = ent
    return best


# Breadth-first search scratch, allocated once. Rebuilding these every
# search would be 2 KB of garbage each time on a board with no PSRAM.
_bfs_seen = bytearray(MAP_W * MAP_H)
_bfs_tag  = bytearray(MAP_W * MAP_H)
_bfs_q    = [0] * (MAP_W * MAP_H)

# Cached answer from frontier_dir(): [direction index, expiry time].
_frontier = [-1, 0.0]
FRONTIER_INTERVAL = 2.0


def frontier_dir(now):
    """Which of N/S/E/W starts the shortest walk to an unexplored tile.

    This is the badge's own competence, not the directive's. It matters
    because the directive is only a bias: when it points at a wall, or says
    HOLD, or the model says something unhelpful, this is what stops the
    badge pacing the same corridor for ten minutes. Deliberately weighted
    below the directive in the scoring, so the word on screen still visibly
    wins whenever it names a legal direction.

    Recomputed at most every couple of seconds. A full sweep of a 32x32 map
    is cheap next to a frame of raycasting, but not cheap enough to want it
    forty times a second.
    """
    if now < _frontier[1]:
        return _frontier[0]
    _frontier[1] = now + FRONTIER_INTERVAL

    for i in range(MAP_W * MAP_H):
        _bfs_seen[i] = 0

    head = 0
    tail = 0
    start = int(player_y) * MAP_W + int(player_x)
    _bfs_seen[start] = 1

    for i in range(4):
        nx = int(player_x) + DIR_DX[i]
        ny = int(player_y) + DIR_DY[i]
        if is_wall(nx, ny):
            continue
        idx = ny * MAP_W + nx
        if _bfs_seen[idx]:
            continue
        _bfs_seen[idx] = 1
        _bfs_tag[idx] = i
        _bfs_q[tail] = idx
        tail += 1

    while head < tail:
        idx = _bfs_q[head]
        head += 1
        if not explored[idx]:
            _frontier[0] = _bfs_tag[idx]
            return _frontier[0]
        cx = idx % MAP_W
        cy = idx // MAP_W
        tag = _bfs_tag[idx]
        for i in range(4):
            nx = cx + DIR_DX[i]
            ny = cy + DIR_DY[i]
            if is_wall(nx, ny):
                continue
            n_idx = ny * MAP_W + nx
            if _bfs_seen[n_idx]:
                continue
            _bfs_seen[n_idx] = 1
            _bfs_tag[n_idx] = tag
            _bfs_q[tail] = n_idx
            tail += 1

    _frontier[0] = -1        # whole map seen
    return -1


def bearing(dx, dy):
    """Compass letter for an offset. Whichever axis dominates wins."""
    if abs(dx) >= abs(dy):
        return "E" if dx >= 0 else "W"
    return "S" if dy >= 0 else "N"


def observe():
    """What is the game showing us right now?

    Builds the beacon-shaped snapshot from build_overview.md. Step 4 puts
    this dict on the wire as-is rather than assembling a second one, which
    is why it costs a dict and two lists a frame instead of a few globals.
    """
    global snapshot

    del seen_enemies[:]
    del seen_items[:]
    del seen_dist[:]
    del item_dist[:]
    enemies = []
    items = []

    for ent in entities:
        if not ent[ALIVE]:
            continue
        dx = ent[EX] - player_x
        dy = ent[EY] - player_y
        dist = math.sqrt(dx * dx + dy * dy)
        if dist > (SIGHT_RANGE if ent[KIND] == E_ENEMY else ITEM_RANGE):
            continue
        if not line_of_sight(player_x, player_y, ent[EX], ent[EY]):
            continue

        remember(ent)
        rec = {"dir": bearing(dx, dy), "dist": round(dist, 1)}
        if ent[KIND] == E_ENEMY:
            # Insertion sort, nearest first. decide() treats seen_enemies[0]
            # as *the* threat and act() shoots the first one in the cone, so
            # spawn order would have the badge turning away from something a
            # tile away to face something nine tiles away.
            i = len(seen_enemies)
            while i > 0 and seen_dist[i - 1] > dist:
                i -= 1
            seen_enemies.insert(i, ent)
            seen_dist.insert(i, dist)
            enemies.insert(i, rec)
        else:
            i = len(seen_items)
            while i > 0 and item_dist[i - 1] > dist:
                i -= 1
            seen_items.insert(i, ent)
            item_dist.insert(i, dist)
            rec["kind"] = "medkit" if ent[KIND] == E_MEDKIT else "ammo"
            items.insert(i, rec)

    # The relay's describe() reads at most four of each, and the beacon has a
    # ~400 byte budget against a 1472 byte ceiling. seen_enemies/seen_items
    # keep every entity; only what goes on the wire is trimmed.
    del enemies[4:]
    del items[4:]

    tx = int(player_x)
    ty = int(player_y)

    snapshot = {
        "id": BADGE_ID,
        "seq": seq,
        "hp": hp,
        "ammo": ammo,
        "pos": [tx, ty],
        "facing": facing(),
        "explored": round(explored_count / OPEN_TILE_COUNT, 2),
        "enemies": enemies,
        "items": items,
        "walls": {"n": is_wall(tx, ty - 1), "s": is_wall(tx, ty + 1),
                  "e": is_wall(tx + 1, ty), "w": is_wall(tx - 1, ty)},
        "recent": recent[-6:],
    }


# ------------------------------------------------------------------
# OODA -- Orient
# ------------------------------------------------------------------
# What is new since last frame. Kept in globals rather than a returned dict
# because it is read once, immediately, by Decide.
new_enemy         = False
enemy_lost        = False
hp_drop           = 0
ammo_empty        = False
tiles_gained      = 0
directive_changed = False

# One-element lists so orient() can remember things without a global
# statement for values nothing else writes. explored_count is tracked here
# rather than read back out of the snapshot, whose "explored" field is
# rounded to two decimals and so quantises to about five tiles.
prev_directive = [None]
prev_explored  = [0]


def orient():
    """What has changed since the last loop?"""
    global prev_snapshot, new_enemy, enemy_lost, hp_drop, ammo_empty
    global tiles_gained, directive_changed

    if prev_snapshot is None:
        new_enemy = bool(snapshot["enemies"])
        enemy_lost = False
        hp_drop = 0
        ammo_empty = snapshot["ammo"] <= 0
        tiles_gained = 0
        directive_changed = True
    else:
        was = len(prev_snapshot["enemies"])
        now_n = len(snapshot["enemies"])
        new_enemy = now_n > was
        enemy_lost = now_n < was
        hp_drop = prev_snapshot["hp"] - snapshot["hp"]
        ammo_empty = snapshot["ammo"] <= 0 and prev_snapshot["ammo"] > 0
        tiles_gained = explored_count - prev_explored[0]
        directive_changed = prev_directive[0] != directive

    prev_directive[0] = directive
    prev_explored[0] = explored_count
    prev_snapshot = snapshot


# ------------------------------------------------------------------
# OODA -- Decide
# ------------------------------------------------------------------
DIRECTIVES = ("EXPLORE_N", "EXPLORE_S", "EXPLORE_E", "EXPLORE_W",
              "HUNT", "RETREAT", "SEEK_ITEM", "HOLD")

# The weight a directive puts on the direction it actually names. Every other
# term in the scoring is single digit, so this is the thumb on the scale.
DIRECTIVE_STRONG = 10.0


def angle_to(tx, ty):
    """Heading from the player to a point, in radians."""
    return math.atan2(ty - player_y, tx - player_x) % TWO_PI


def angle_diff(a, b):
    """Shortest signed angle from a to b, in -pi..pi."""
    d = (b - a) % TWO_PI
    return d - TWO_PI if d > math.pi else d


def open_heading():
    """The most open direction to turn toward when the way ahead is blocked.

    Reused from the placeholder wander, and still the right answer: probe
    left and right, commit to the roomier side, and hold that commitment in
    `turn_dir` until forward clears. Re-deciding every frame deadlocks,
    because at a junction the better side flips as the heading rotates.
    """
    global turn_dir
    ai = int(player_a * ANG_SCALE) & ANG_MASK
    if turn_dir == 0:
        quarter = ANG_STEPS // 4
        left = side_clearance((ai + quarter) & ANG_MASK, 8)
        right = side_clearance((ai - quarter) & ANG_MASK, 8)
        turn_dir = 1 if left >= right else -1     # ties go left, so dead ends resolve
    return (player_a + turn_dir * 0.9) % TWO_PI


def head_for(want):
    """Turn if we are not pointing that way yet, otherwise walk. Keeps Act's
    contract of exactly one action per frame."""
    global action, action_heading
    action = "STEP" if abs(angle_diff(player_a, want)) <= 0.25 else "TURN"
    action_heading = want


def decide(now):
    """Urgency first, always. Reflexes are never overridden by a directive.

    Below the reflexes the four compass moves are scored and the best wins.
    The directive adds weight; it does not select. Walls are the one hard
    veto. That is what makes the word on screen visibly influence the badge
    rather than puppet it, which is the entire reason it is on screen.
    """
    global action, action_heading, urgent, turn_dir

    enemy = seen_enemies[0] if seen_enemies else None
    if enemy is not None:
        goal[2] = False        # after a fight, think again rather than
                               # resuming a walk decided before it started
    urgent = True

    # -- reflex 1: already lined up on something -> shoot it ---------------
    if enemy is not None and ammo > 0:
        want = angle_to(enemy[EX], enemy[EY])
        if abs(angle_diff(player_a, want)) <= FIRE_CONE:
            # Between shots, hold the aim rather than wandering off it.
            action = "FIRE" if now >= next_shot else "HOLD"
            action_heading = want
            request_refresh(now)
            return

    # -- reflex 2: nearly dead with contact -> break away, toward a medkit -
    if enemy is not None and hp < CRITICAL_HP:
        # Known, not merely visible: the step document says "toward the last
        # seen medkit", and one around a corner still counts.
        medkit = nearest_known(E_MEDKIT)
        if medkit is not None:
            head_for(angle_to(medkit[EX], medkit[EY]))
        else:
            head_for((angle_to(enemy[EX], enemy[EY]) + math.pi) % TWO_PI)
        request_refresh(now)
        return

    # -- reflex 3: out of ammo with contact -> break contact ---------------
    if enemy is not None and ammo <= 0:
        head_for((angle_to(enemy[EX], enemy[EY]) + math.pi) % TWO_PI)
        request_refresh(now)
        return

    # -- reflex 3b: in contact, armed, not yet aimed -> turn onto it -------
    # Below the retreat checks on purpose. Above them, a badge on its last
    # few HP would stand still turning to face the thing killing it instead
    # of leaving, because aiming would win every frame before retreating
    # ever got a look.
    if enemy is not None and ammo > 0:
        action = "TURN"
        action_heading = angle_to(enemy[EX], enemy[EY])
        request_refresh(now)
        return

    # -- no urgency: the directive applies ---------------------------------
    # `urgent` from here down means "in contact", which is what the refresh
    # rule cares about. Being stuck against a wall is not a firefight, and a
    # badge that is stuck is exactly one that could use fresh judgment.
    urgent = False

    tx = int(player_x)
    ty = int(player_y)

    # A goal already in progress is kept. Re-scoring every frame chatters:
    # standing on a tile boundary flips int(player_y) between two rows, each
    # scores a different winner, and the badge shivers in the doorway
    # forever. Commit to a tile, walk to it, then think again.
    if goal[2] and not directive_changed and not is_wall(goal[0], goal[1]):
        gdx = goal[0] + 0.5 - player_x
        gdy = goal[1] + 0.5 - player_y
        if gdx * gdx + gdy * gdy > 0.09:        # further than 0.3 tiles
            # Arrival means the centre of the tile, not merely crossing into
            # it. Stopping at the edge leaves the player straddling a tile
            # boundary, where its 0.44-wide box clips the wall corner beside
            # every perpendicular opening, so the only move left is back the
            # way it came -- and the badge paces two tiles forever. Walking
            # to centres is what makes a grid navigable at all.
            stall[0] += 1
            if stall[0] < 120:                  # ~6 s of no arrival, then quit
                head_for(angle_to(goal[0] + 0.5, goal[1] + 0.5))
                request_refresh(now)
                return
            # Giving up is not enough on its own. The scoring that picked this
            # tile is about to run again from the same place and pick it
            # again, and the badge turns on the spot in a six second cycle
            # forever. Charge the tile for having been unreachable so the
            # next score comes out differently.
            idx = goal[1] * MAP_W + goal[0]
            visits[idx] = 255 if visits[idx] > 250 else visits[idx] + 4
        goal[2] = False
    stall[0] = 0

    # Stuck check. Only ever measured here, in the no-urgency branch, so a
    # long firefight in one spot is not mistaken for being trapped.
    if now - _anchor[2] >= STUCK_WINDOW:
        dx = player_x - _anchor[0]
        dy = player_y - _anchor[1]
        if dx * dx + dy * dy < STUCK_RADIUS * STUCK_RADIUS:
            _ignore_directive_until[0] = now + STUCK_RELEASE
            print("STUCK inside %.1f tiles for %.0fs, frontier takes over for %.0fs"
                  % (STUCK_RADIUS, STUCK_WINDOW, STUCK_RELEASE))
        _anchor[0] = player_x
        _anchor[1] = player_y
        _anchor[2] = now

    # Pass one: which moves are legal at all, and what the directive makes
    # of each. Kept separate because whether the badge falls back on its own
    # navigation depends on whether the directive said anything.
    said_something = False
    for i in range(4):
        nx = tx + DIR_DX[i]
        ny = ty + DIR_DY[i]

        # An open tile is not the same as a reachable one. The player is a
        # 0.44-wide box, so standing off-centre in a corridor puts a corner
        # into the wall beside the opening. Vetoing on is_wall alone wedges
        # the badge: the directive keeps choosing a direction it physically
        # cannot enter while reflex 4 turns it away, and the two cancel.
        if is_wall(nx, ny) or blocked(player_x + DIR_DX[i] * 0.5,
                                      player_y + DIR_DY[i] * 0.5):
            legal[i] = False             # the one hard veto
            weights[i] = 0.0
            continue

        legal[i] = True
        weights[i] = directive_weight(i, nx, ny)
        # "Said something" means the directive named *this* direction, not
        # merely that it contributed a nudge. EXPLORE_N adds a small bonus to
        # any unexplored neighbour whichever way it points, and counting that
        # kept the frontier switched off on exactly the tiles where north is a
        # wall -- which is where the badge most needs routing out.
        if weights[i] >= DIRECTIVE_STRONG:
            said_something = True

    if now < _ignore_directive_until[0]:
        said_something = False       # let the frontier drive us out

    # The frontier pull is the badge's own navigation and it only gets a
    # vote when the directive has none: HOLD, or an EXPLORE pointing into a
    # wall, or a HUNT with nothing known. Letting it compete with a live
    # directive made the two alternate, and the badge spent its whole life
    # turning around -- 1648 turns against 135 steps in a 90 second run.
    frontier = -1 if said_something else frontier_dir(now)

    best = -1e9
    best_i = -1
    for i in range(4):
        if not legal[i]:
            continue
        nx = tx + DIR_DX[i]
        ny = ty + DIR_DY[i]

        score = weights[i]
        if not explored[ny * MAP_W + nx]:
            score += 3.0                 # unexplored is mildly interesting anywhere
        if abs(angle_diff(player_a, DIR_ANG[i])) < 0.4:
            score += 1.0                 # mild preference for not spinning
        if nx == last_tile[0] and ny == last_tile[1]:
            score -= 2.5                 # doubling back is dull, not forbidden
        seen_count = visits[ny * MAP_W + nx]
        if seen_count:
            score -= VISIT_PENALTY * (seen_count if seen_count < VISIT_CAP
                                      else VISIT_CAP)
        if i == frontier:
            score += 6.0                 # the badge's own sense of direction

        if score > best:
            best = score
            best_i = i

    # -- reflex 4: nothing reachable -> turn toward the open side ----------
    # Last, not first. Written above the scoring it hijacked every frame the
    # heading happened to point at a wall, chose its own turn direction, and
    # fought the directive to a standstill. Down here it is what it was
    # always meant to be: the way out when there is no move to score.
    if best_i < 0:
        goal[2] = False
        action = "TURN"
        action_heading = open_heading()
        request_refresh(now)
        return

    # Staying put is a fifth candidate with a weight, exactly like the four
    # moves, rather than a threshold gate bolted on beside them. Only HOLD
    # puts anything on it, and under every other directive it is not a
    # candidate at all -- scored as merely zero it wins by default on any
    # tile where the visit penalties have pushed every move negative, and
    # the badge sits down for good.
    # The watchdog deliberately does not touch this. A badge told to HOLD and
    # standing still is doing exactly as it was told, and the reflexes still
    # fire freely underneath, so it is not stuck -- it is holding. Gating this
    # on the watchdog made a pinned HOLD wander off across the map.
    stay = DIRECTIVE_STRONG if directive == "HOLD" else -1e9
    # Strictly greater. The best possible move also scores exactly
    # DIRECTIVE_STRONG (3 unexplored + 1 aligned + 6 frontier), and letting a
    # tie go to standing still turns one unlucky arithmetic coincidence into a
    # badge that never moves again.
    if stay > best:
        goal[2] = False
        action = "HOLD"
        action_heading = player_a
        request_refresh(now)
        return

    if now >= _visit_decay_at[0]:
        _visit_decay_at[0] = now + VISIT_DECAY
        for i in range(MAP_W * MAP_H):
            if visits[i]:
                visits[i] -= 1

    here = ty * MAP_W + tx
    if visits[here] < 255:
        visits[here] += 1

    last_tile[0] = tx
    last_tile[1] = ty
    goal[0] = tx + DIR_DX[best_i]
    goal[1] = ty + DIR_DY[best_i]
    goal[2] = True

    # Head for the centre of the chosen tile, not along the bare compass
    # angle. That is what pulls the badge back into the middle of a corridor
    # instead of grinding along one wall of it.
    head_for(angle_to(tx + DIR_DX[best_i] + 0.5, ty + DIR_DY[best_i] + 0.5))
    request_refresh(now)


def directive_weight(i, nx, ny):
    """How much the current directive likes the compass move `i`.

    Additive, never selective. A directive that pointed at a wall would
    otherwise pin the badge against it forever.
    """
    d = directive

    if d == "HOLD":
        return 0.0

    if d.startswith("EXPLORE_"):
        w = DIRECTIVE_STRONG if d[8:] == DIR_NAME[i] else 0.0
        if not explored[ny * MAP_W + nx]:
            w += 4.0
        return w

    if d == "HUNT":
        target = nearest_known(E_ENEMY)
        return DIRECTIVE_STRONG if target is not None and towards(i, target) else 0.0

    if d == "SEEK_ITEM":
        # Degrades to ordinary exploring when nothing is known, rather than
        # deadlocking, which is the point of scoring instead of commanding.
        target = nearest_known(None)
        if target is not None and target[KIND] == E_ENEMY:
            target = nearest_known(E_MEDKIT) or nearest_known(E_AMMO)
        return DIRECTIVE_STRONG if target is not None and towards(i, target) else 0.0

    if d == "RETREAT":
        w = 0.0
        medkit = nearest_known(E_MEDKIT)
        if medkit is not None and towards(i, medkit):
            w += 8.0
        threat = nearest_known(E_ENEMY)
        if threat is not None and not towards(i, threat):
            w += 6.0
        return w

    return 0.0


def towards(i, ent):
    """True if compass move `i` closes the distance to an entity."""
    return bearing(ent[EX] - player_x, ent[EY] - player_y) == DIR_NAME[i]


def request_refresh(now):
    """Ask for a fresh directive, from inside Decide, per gameplay.md.

    Not on a timer: the badge asks for judgment when it has the space to use
    it, and never mid-firefight. The staleness ceiling is the one thing
    gameplay.md does not specify and the loop needs, because a badge pinned
    in a long fight would otherwise act on a two-minute-old directive.
    """
    global request_flight, request_at, last_request, seq

    if request_flight or not net_up or PIN_DIRECTIVE:
        return
    if now - last_request < DIRECTIVE_MIN_INTERVAL:
        return
    if urgent and now - directive_at < DIRECTIVE_MAX_AGE:
        return

    seq += 1
    # The snapshot was built before this frame's request existed, and step 4
    # puts that same dict on the wire. Stamp it, or the relay echoes back a
    # seq one behind the one the badge is waiting on.
    snapshot["seq"] = seq
    request_at = now
    last_request = now
    if not send_beacon():
        return                      # no route; try again after the floor
    request_flight = True
    print("NET -> seq=%d hp=%d ammo=%d enemies=%d items=%d expl=%.2f%s"
          % (seq, hp, ammo, len(snapshot["enemies"]), len(snapshot["items"]),
             snapshot["explored"], "  (stale, mid-fight)" if urgent else ""))


# ------------------------------------------------------------------
# OODA -- Act
# ------------------------------------------------------------------
# One action per frame, one switch, and the only place player state changes.


def act(now, dt):
    """Execute exactly what Decide chose."""
    global player_a, player_x, player_y, ammo, hp, next_shot, muzzle_until
    global turn_dir

    if action == "FIRE":
        ammo -= 1
        next_shot = now + FIRE_INTERVAL
        muzzle_until = now + 0.08
        player_a = action_heading
        hit = None
        for ent in seen_enemies:
            if abs(angle_diff(player_a, angle_to(ent[EX], ent[EY]))) <= FIRE_CONE:
                hit = ent
                break
        if hit is not None:
            hit[EHP] -= FIRE_DAMAGE
            if hit[EHP] <= 0:
                hit[ALIVE] = False
                print("KILL at %.1f,%.1f  ammo=%d" % (hit[EX], hit[EY], ammo))

    elif action == "TURN":
        step = TURN_SPEED * dt
        d = angle_diff(player_a, action_heading)
        player_a = (player_a + (step if d > 0 else -step)) % TWO_PI \
            if abs(d) > step else action_heading % TWO_PI

    elif action == "STEP":
        ai = int(player_a * ANG_SCALE) & ANG_MASK
        before_x, before_y = player_x, player_y
        try_move(player_x + COS_T[ai] * MOVE_SPEED * dt,
                 player_y + SIN_T[ai] * MOVE_SPEED * dt)
        # A step that actually got somewhere clears the committed turn
        # direction. Clearing it anywhere else throws away the commitment
        # that stops open_heading() dithering at a junction.
        if player_x != before_x or player_y != before_y:
            turn_dir = 0
        collect()

    # "HOLD" is the fourth case and it does nothing on purpose.


def collect():
    """Walk over a medkit or an ammo box and it is yours."""
    global hp, ammo
    for ent in entities:
        if not ent[ALIVE] or ent[KIND] == E_ENEMY:
            continue
        dx = ent[EX] - player_x
        dy = ent[EY] - player_y
        if dx * dx + dy * dy > PICKUP_RANGE * PICKUP_RANGE:
            continue
        ent[ALIVE] = False
        if ent[KIND] == E_MEDKIT:
            hp = min(100, hp + MEDKIT_HEAL)
            print("PICKUP medkit  hp=%d" % hp)
        else:
            ammo += AMMO_PICKUP
            print("PICKUP ammo  ammo=%d" % ammo)


# ------------------------------------------------------------------
# The world acting back
# ------------------------------------------------------------------
def enemies_act(now):
    """Enemies are stationary sentries: they shoot when they can see you.

    Stationary because it is tunable and legible. A spectator can see why
    the badge is taking damage, which is more use in a talk than clever
    pursuit behaviour nobody can follow.
    """
    global hp
    for ent in entities:
        if not ent[ALIVE] or ent[KIND] != E_ENEMY:
            continue
        dx = player_x - ent[EX]
        dy = player_y - ent[EY]
        if dx * dx + dy * dy > ENEMY_RANGE * ENEMY_RANGE:
            continue
        if now < ent[ENEXT]:
            continue
        if not line_of_sight(ent[EX], ent[EY], player_x, player_y):
            continue
        ent[ENEXT] = now + ENEMY_INTERVAL
        hp -= ENEMY_DAMAGE


def respawn(now):
    """Death costs the map, not the exploration.

    A frozen GAME OVER screen on a lanyard is dead air, so the badge just
    gets back up at the start tile and carries on.
    """
    global hp, ammo, player_x, player_y, player_a, turn_dir, deaths
    global prev_snapshot, directive, directive_why, directive_at

    deaths += 1
    print("DEAD after %d kills, respawning (death %d)"
          % (sum(0 if e[ALIVE] else 1 for e in entities if e[KIND] == E_ENEMY),
             deaths))
    hp = 100
    ammo = 24
    player_x, player_y = START_X, START_Y
    player_a = START_ANGLE
    turn_dir = 0
    prev_snapshot = None
    del known[:]
    goal[2] = False
    _frontier[1] = 0.0
    for i in range(MAP_W * MAP_H):
        visits[i] = 0
    _anchor[2] = 0.0
    _ignore_directive_until[0] = 0.0
    reset_entities()
    # LOCAL, not HOLD. With no relay nothing would ever replace a HOLD: the
    # request path is gated on the link being up, and so is the staleness
    # fallback, so the badge would stand on the spawn tile until it was power
    # cycled. That is reachable from every offline path, which is exactly the
    # case this sample is supposed to survive.
    directive, directive_why, directive_at = "LOCAL", "just respawned", now


# ------------------------------------------------------------------
# Networking
# ------------------------------------------------------------------
# The badge broadcasts its state and the relay answers unicast to whatever
# address the beacon came from, so neither end has to know the other's IP.
# Nothing here blocks, ever: this runs inside the frame loop.
#
# relay/fake_badge.py is the reference implementation of this exact pattern
# and has been proven against the live relay.

# Not CIRCUITPY_WIFI_*. Those magic names trigger CircuitPython's web
# workflow, which brings up wifi before code.py runs and adds ~10 s to every
# cold boot of every sample on the drive. See settings.toml.example.
WIFI_SSID = os.getenv("WIFI_SSID", "")
WIFI_PASSWORD = os.getenv("WIFI_PASSWORD", "")

sock = None
net_up = False
last_reply_at = 0.0
net_pulse_until = 0.0
last_link_check = 0.0

# Preallocated once. Allocating a receive buffer inside the frame loop is
# exactly the kind of per-frame garbage a board with no PSRAM cannot afford.
# 1024, not 512. relay.py passes the model's `why` through with no length
# cap -- "8 words max" is a prompt hint, not a rule -- and recvfrom_into
# truncates silently, which shows up as a JSON parse failure and a dropped
# directive. Still far under the 1472-byte datagram ceiling.
_rx = bytearray(1024)


def net_socket():
    """Build the one UDP socket. Returns False rather than raising."""
    global sock
    if sock is not None:
        try:
            sock.close()
        except Exception:
            pass
        sock = None
    s = None
    try:
        pool = socketpool.SocketPool(wifi.radio)
        s = pool.socket(pool.AF_INET, pool.SOCK_DGRAM)
        # SO_REUSEADDR is one of only two options this implementation takes.
        # Do NOT add SO_BROADCAST: it is not exposed, lwIP's broadcast filter
        # is compiled out on the ESP32 so it is unnecessary, and on some ports
        # asking for it raises.
        s.setsockopt(pool.SOL_SOCKET, pool.SO_REUSEADDR, 1)
        s.bind(("", BADGE_PORT))
        # settimeout(0) is setblocking(False). A small positive timeout would
        # raise ETIMEDOUT instead of EAGAIN and the poll idiom below would
        # stop working.
        s.settimeout(0)
        sock = s
        return True
    except Exception as e:
        # Close it here or it is gone for good: `sock` is still None, so
        # nothing else can ever reach it, and the device only has eight.
        if s is not None:
            try:
                s.close()
            except Exception:
                pass
        print("NET socket failed: %s" % e)
        sock = None
        return False


def net_connect():
    """Join the network. Any failure means reflex-only, not a crash."""
    global net_up
    net_up = False

    if not WIFI_SSID:
        print("NET no WIFI_SSID in settings.toml -- reflex only, no relay")
        return

    try:
        # Not optional. The default wakes only on DTIM and MAX drops
        # AP-buffered broadcast frames outright, which is precisely the
        # traffic this design runs on.
        wifi.radio.power_management = wifi.PowerManagement.NONE
        # Bounded: this call blocks the frame loop, and an AP that is simply
        # gone should not cost more than a visible hiccup.
        wifi.radio.connect(WIFI_SSID, WIFI_PASSWORD, timeout=NET_CONNECT_TIMEOUT)
    except Exception as e:
        print("NET connect to %r failed: %s -- reflex only" % (WIFI_SSID, e))
        return

    if not net_socket():
        return

    net_up = True
    print("NET %s as %s, relay %s:%d, listening on %d"
          % (WIFI_SSID, wifi.radio.ipv4_address,
             RELAY_HOST or "255.255.255.255 (broadcast)", RELAY_PORT, BADGE_PORT))


def net_check(now):
    """Re-associate if the link dropped, and rebuild the socket when it does.

    The rebuild is the part that matters. CircuitPython does not close user
    sockets on disconnect, and the old pcb keeps the stale IP, so a socket
    that survives a reconnect silently stops working. Recreating is cheap.

    This also has to keep trying after a failure. Returning early whenever the
    link was down meant one transient blip latched the badge onto LOCAL for
    the rest of the run.

    Associating blocks -- there is no non-blocking connect in CircuitPython --
    so this is the one place a frame can stall, and the retry interval is what
    bounds how often. No credentials means no retrying at all, ever.
    """
    global net_up, last_link_check

    if not WIFI_SSID or PIN_DIRECTIVE:
        return
    if now - last_link_check < (NET_RETRY if not net_up else 5.0):
        return
    last_link_check = now

    if net_up:
        try:
            if wifi.radio.connected:
                return
        except Exception:
            pass
        print("NET link dropped")
        net_up = False

    print("NET reconnecting (this stalls a frame)")
    net_connect()


def send_beacon():
    """One datagram carrying the snapshot Observe already built."""
    if not net_up or sock is None:
        return False
    try:
        payload = json.dumps(snapshot).encode("utf-8")
    except Exception as e:
        print("NET encode failed: %s" % e)
        return False
    try:
        sock.sendto(payload, (RELAY_HOST or "255.255.255.255", RELAY_PORT))
        return True
    except BrokenPipeError:
        # Caught first: it is an OSError subclass. sendto discards the errno,
        # so a failure here means no route, not permissions.
        return False
    except OSError:
        return False


def poll_directive(now):
    """Drain the socket, take the first usable reply, and never block."""
    global request_flight, directive, directive_why, directive_at
    global last_reply_at, net_pulse_until

    # A pinned directive is a demo switch: the badge holds it and asks
    # nobody. Handled here so the rest of the loop is unchanged.
    if PIN_DIRECTIVE:
        if directive != PIN_DIRECTIVE:
            directive, directive_why, directive_at = (
                PIN_DIRECTIVE, "pinned in config", now)
        request_flight = False
        return

    # With no link there is nothing that can ever change the directive again,
    # so anything left over from a live relay has to be dropped rather than
    # acted on forever.
    if not net_up:
        if directive != "LOCAL":
            print("NET link down, falling back to LOCAL")
            directive, directive_why, directive_at = "LOCAL", "no relay", now
        request_flight = False
        return

    if sock is not None:
        # Bounded, so a flood cannot stall a frame. The receive queue is six
        # datagrams deep, and anything past the first usable reply is older.
        for _ in range(4):
            try:
                n, addr = sock.recvfrom_into(_rx)
            except OSError as e:
                if e.errno == 11:          # EAGAIN, the ordinary empty socket
                    break
                print("NET recv error: %s" % e)
                break
            except Exception as e:
                print("NET recv error: %s" % e)
                break
            if apply_reply(now, _rx, n, addr):
                break

    # An answer that never came must not wedge the request slot shut.
    if request_flight and now - request_at > DIRECTIVE_TIMEOUT:
        request_flight = False
        print("NET seq=%d timed out after %.0fs" % (seq, DIRECTIVE_TIMEOUT))

    # Nothing for a long time: say so on the strip rather than showing a word
    # the badge is no longer really being told.
    if (net_up and directive != "LOCAL" and last_reply_at
            and now - last_reply_at > NET_STALE):
        print("NET nothing for %.0fs, falling back to LOCAL" % (now - last_reply_at))
        directive, directive_why, directive_at = "LOCAL", "relay quiet", now


def apply_reply(now, buf, n, addr):
    """Validate one datagram and adopt it. True if it was used."""
    global request_flight, directive, directive_why, directive_at
    global last_reply_at, net_pulse_until

    if n <= 0:
        return False
    try:
        reply = json.loads(bytes(memoryview(buf)[:n]))
    except Exception:
        print("NET %d bytes of non-JSON from %s" % (n, addr[0]))
        return False
    if not isinstance(reply, dict):
        print("NET reply from %s was not an object" % addr[0])
        return False

    new = reply.get("directive")
    # The relay already normalises, but the badge does not trust the network.
    if new not in DIRECTIVES:
        print("NET rejected directive %r from %s" % (new, addr[0]))
        return False

    # Accept slightly late answers. Directives take 2-4 s and change slowly,
    # so one aimed at the previous beacon is still worth acting on.
    # A reply with no seq is not one of ours. The relay always echoes the
    # beacon's, and every beacon carries one, so anything without it is
    # somebody else's traffic on udp/5116.
    rseq = reply.get("seq")
    try:
        rseq = int(rseq)
    except (TypeError, ValueError):
        print("NET reply from %s had no usable seq" % addr[0])
        return False
    if seq - rseq > 2:
        print("NET stale seq=%s (now %d), ignoring" % (rseq, seq))
        return False

    why = reply.get("why") or ""
    if not isinstance(why, str):
        why = ""

    request_flight = False
    last_reply_at = now
    net_pulse_until = now + 0.4
    print("NET <- %s (%s) seq=%s in %.1fs from %s"
          % (new, why, rseq, now - request_at, addr[0]))

    # Every accepted reply, including a repeat. Appending only on change made
    # consecutive duplicates impossible, which quietly defeated both
    # relay.py's `recent[-2:] != [candidate, candidate]` guard and the system
    # prompt's instruction not to repeat an EXPLORE_* more than twice: the
    # relay was told a history that had had its repetitions edited out. Step 3
    # said "only when the directive changes, not every frame" -- the part that
    # matters is `not every frame`, and this runs once per reply.
    recent.append(new)
    del recent[:-6]
    directive, directive_why, directive_at = new, why, now
    return True


# ------------------------------------------------------------------
# Boot
# ------------------------------------------------------------------
if blocked(START_X, START_Y):
    raise ValueError("START_X/START_Y (%.1f, %.1f) is inside a wall"
                     % (START_X, START_Y))

reset_entities()
mark_explored()
observe()
orient()
net_connect()
if PIN_DIRECTIVE:
    directive, directive_why = PIN_DIRECTIVE, "pinned in config"
update_hud()
render()
display.refresh()
bl.value = True           # backlight on only once there is something to see

print("Doomish [%s]  %dx%d rotation=%d  view=%s" % (
    BADGE_ID, SCREEN_W, SCREEN_H, ROTATION,
    "raycast" if view_mode == 0 else "top-down"))
print("  world %dx%d, %d open tiles, %d ray columns"
      % (MAP_W, MAP_H, OPEN_TILE_COUNT, RAY_COLS))
print("  %d enemies, %d items" % (
    sum(1 for e in entities if e[KIND] == E_ENEMY),
    sum(1 for e in entities if e[KIND] != E_ENEMY)))
print("  directives: floor %.0f s, ceiling %.0f s, timeout %.0f s, stale %.0f s%s"
      % (DIRECTIVE_MIN_INTERVAL, DIRECTIVE_MAX_AGE, DIRECTIVE_TIMEOUT,
         NET_STALE,
         ("  PINNED to %s" % PIN_DIRECTIVE) if PIN_DIRECTIVE else ""))
if not net_up and not PIN_DIRECTIVE:
    print("  no relay: reflexes and the badge's own navigation carry the game")
print("  SW1 view   SW2 leds   SW3 pause ai   SW1+SW3 menu")


# ------------------------------------------------------------------
# Main loop
# ------------------------------------------------------------------
# No time.sleep() anywhere in here. Nothing blocks, nothing waits.
last_frame = time.monotonic()
last_trace = last_frame     # first trace line after a real second, not on frame 1

while True:
    now = time.monotonic()
    dt = now - last_frame
    last_frame = now
    if dt > 0.25:
        dt = 0.25          # a long stall must not teleport the player

    # --- frame time ---
    # Exponential average rather than a ring buffer: one multiply-add, no
    # allocation, and it settles fast enough to be worth reading. Computed
    # before the HUD is built so the label shows this second, not last one.
    frame_ms = frame_ms * 0.9 + dt * 100.0 if frame_ms else dt * 1000.0
    if now - last_trace >= 1.0:
        fps_text = "%d fps" % int(1000.0 / frame_ms) if frame_ms > 0 else ""
        # Orient's diff goes here rather than into a decision. Decide reads
        # the world directly, so these are diagnostics -- and they are the
        # ones worth having when the badge is on a lanyard and misbehaving.
        news = ""
        if new_enemy:
            news += " +enemy"
        if enemy_lost:
            news += " -enemy"
        if hp_drop > 0:
            news += " -%dhp" % hp_drop
        if ammo_empty:
            news += " dry"
        if tiles_gained:
            news += " +%dt" % tiles_gained

        print("%.1f ms  pos=%.2f,%.2f %s  hp=%d ammo=%d  expl=%d%%  "
              "see=%de/%di  %s%-5s  [%s %.0fs]%s%s"
              % (frame_ms, player_x, player_y, facing(), hp, ammo,
                 100 * explored_count // OPEN_TILE_COUNT,
                 len(seen_enemies), len(seen_items),
                 "!" if urgent else " ", action,
                 directive, now - directive_at, news,
                 "  req in flight" if request_flight else ""))
        last_trace = now

    # --- buttons ---
    v1, v2, v3 = sw1.value, sw2.value, sw3.value

    # Both outer switches held: back to the Launcher. Level-triggered on
    # both pins at once, so no single press can reach it. SW1 usually lands
    # a frame early and flips the view on its way past; supervisor.reload()
    # throws that away, so it does not matter.
    if (not v1) and (not v3):
        print("SW1+SW3 -- returning to the menu")
        pixels.fill((0, 0, 0)); pixels.show()
        supervisor.reload()

    pressed_sw1 = (not v1) and sw1_prev and (now - sw1_last) > DEBOUNCE
    pressed_sw2 = (not v2) and sw2_prev and (now - sw2_last) > DEBOUNCE
    pressed_sw3 = (not v3) and sw3_prev and (now - sw3_last) > DEBOUNCE
    sw1_prev, sw2_prev, sw3_prev = v1, v2, v3

    if pressed_sw1:
        sw1_last = now
        view_mode = 1 - view_mode
        print("view:", "raycast" if view_mode == 0 else "top-down")

    if pressed_sw2:
        sw2_last = now
        leds_on = not leds_on
        if not leds_on:
            pixels.fill((0, 0, 0)); pixels.show()
        print("leds:", "on" if leds_on else "off")

    if pressed_sw3:
        sw3_last = now
        ai_paused = not ai_paused
        print("ai:", "paused" if ai_paused else "running")

    # --- OODA ---
    # Observe, Orient, Decide, Act, in that order, every frame. SW3 freezes
    # the loop without freezing the display, so the badge can be held up and
    # pointed at while the directive strip still reads.
    net_check(now)
    poll_directive(now)
    if not ai_paused:
        enemies_act(now)
        observe()
        orient()
        decide(now)
        act(now, dt)
        if hp <= 0:
            respawn(now)
    mark_explored()

    # --- draw ---
    render()
    update_hud()
    display.refresh()

    # --- status channels ---
    if now - last_led >= 0.1:      # pixels.show() is not free
        update_leds(now)
        last_led = now
