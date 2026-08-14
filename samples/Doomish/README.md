# Doomish

A tiny Doom-like that plays itself.

The badge runs the fast half of the loop: raycasting, movement, collision,
shooting. A language model on the network runs the slow half and sends back a
single word saying what the badge should be *trying* to do. That word is on
screen at all times, along the bottom strip.

Reflexes at twenty frames a second, judgment every few seconds. That split is
the whole demo, and the directive strip is what makes it visible to somebody
looking over your shoulder.

This is step 4 of the build. The badge is on the network: it broadcasts its
state, a relay on a Raspberry Pi asks a language model what to do about it, and
the answer comes back a couple of seconds later. Pull the plug and the game
carries on regardless.

## What you should see

- A textureless 3D corridor view, 40 columns wide, walls in two shades of brown
  so corners read without any texturing. Enemies are red blocks, medkits green,
  ammo yellow, all hidden correctly behind walls.
- A HUD: HP and ammo top-left, frame rate top-right, the directive strip in
  amber along the bottom.
- The badge exploring on its own, stopping to shoot anything that comes into
  view, backing off toward a medkit when it gets hurt, and picking things up by
  walking over them.
- The directive strip changing every five seconds or so, and the badge's
  behaviour visibly leaning that way without being commanded.
- The LED strip tracking HP across pixels 0 to 2, pixel 3 flashing white on
  every shot, and pixel 4 pulsing cyan each time a directive lands.
- Press SW1 and you get a top-down map instead, with fog over everywhere you
  have not been.

Serial tells you the rest. One line a second with frame time, position, HP,
ammo, what is in view, the chosen action, the directive and its age; plus a
line for every request, reply, kill, pickup and death. That trace is what you
will actually be reading when something is wrong on Saturday and the badge is
on a lanyard.

## Controls

| Switch | Action |
|---|---|
| SW1 (IO1) | toggle view: 3D raycast / top-down |
| SW2 (IO2) | toggle the LED status channel |
| SW3 (IO43) | pause the AI, freezing the player in place |
| SW1 + SW3 | back to the Launcher menu |

The SW1+SW3 exit is the thing no other sample in this repo has. It calls
`supervisor.reload()`, and because the Launcher writes its NVM selection before
it hands over, a reload lands back at the 3-second countdown where a button
press opens the menu.

## Configuration

Everything worth editing is in the banner at the top of `code.py`.

`WORLD` is 32 rows of 32 characters. `#` is wall, `.` is floor, and `E`, `M`,
`A` are enemy, medkit and ammo spawns that behave as floor. Both dimensions are
checked at boot, so a mistyped row tells you which row rather than quietly
drawing nonsense.

`RAY_COLS` is the performance dial. Forty columns on a 160 pixel screen means
each one is 4 pixels wide. Halve it and the raycaster does half the work and
looks twice as chunky.

`ROTATION` is 90 for landscape, which is what a Doom-like wants. Set it to 0 for
portrait and nothing else needs to change: both renderers read `display.width`
and `display.height` rather than hardcoding a size.

The gameplay block below that is the difficulty. It is tuned for something
watched rather than played: one enemy needs about a second of sustained fire to
kill and takes about twenty seconds to kill you, so the badge survives minutes
and a spectator can follow what is happening.

`PIN_DIRECTIVE` is the demo switch. Set it to any of the eight vocabulary words
and the badge holds that one and asks nobody, so you can hold it up and show
what a single directive does to its behaviour. Leave it `None` and the relay
decides.

`RELAY_HOST`, `RELAY_PORT` and `BADGE_PORT` are below that. See **The network**.

## The loop

Four functions, called in order, every frame, named to match
`plans/gameplay.md` exactly.

**Observe** builds a snapshot dict of what the badge can see: HP, ammo,
position, facing, enemies and items with a compass bearing and a distance,
which of the four neighbouring tiles are walls, and the explored fraction. It
is deliberately shaped like the network beacon, because this same dict goes on
the wire rather than a second one being assembled to carry it.

Line of sight uses the same grid DDA the renderer uses, not a second algorithm.
`cast_ray()` is the only traversal in the file; the raycaster calls it once per
column and `line_of_sight()` calls it once per entity.

**Orient** diffs against the previous snapshot: an enemy appeared or left,
how much HP was lost, ammo hit zero, tiles were gained, the directive changed.

**Decide** runs urgency first, and the reflexes are never overridden by a
directive:

| | condition | action |
|---|---|---|
| 1 | enemy in view, ammo left, already aimed | fire |
| 2 | enemy in view and HP below `CRITICAL_HP` | break away, toward a known medkit |
| 3 | enemy in view and out of ammo | break contact |
| 3b | enemy in view, armed, not yet aimed | turn onto it |
| 4 | nothing reachable to score | turn toward the open side |

Reflex 3b sits below the retreat checks on purpose. Above them, a badge on its
last few HP stands still turning to face the thing killing it, because aiming
wins every frame before retreating ever gets a look.

With no urgency, the four compass moves are scored and the best one wins. Walls
are the only hard veto; everything else is additive, and the directive is worth
+10 against single-digit terms for unexplored tiles, not doubling back, and not
spinning on the spot. That is what makes the word on screen visibly *influence*
the badge rather than puppet it, which is the entire reason it is on screen.

**Act** executes exactly one thing: fire, step, turn, or hold. It is the only
function in the file that mutates player state.

## The network

The badge broadcasts a beacon to `255.255.255.255:5115` and the relay answers
unicast to whatever address it arrived from. The badge listens on `5116`.
Neither end is configured with the other's address.

The beacon is the snapshot Observe already built, serialised once at send time
and never per frame. Enemies and items are trimmed to the four nearest, which
is all `relay.py`'s `describe()` reads and keeps the packet inside its ~400 byte
budget; measured beacons run 197 to 311 bytes against a 1472 byte ceiling.

`recent` carries every accepted directive, repeats included. Appending only on
change made consecutive duplicates impossible, which quietly defeated both
`relay.py`'s own repeat guard and the system prompt's instruction not to repeat
an `EXPLORE_*` more than twice: the relay was being told a history with its
repetitions edited out.

The receive buffer is 1024 bytes. `recvfrom_into` truncates silently and the
relay does not cap the length of `why` -- "8 words max" is a prompt hint, not a
rule -- so a chatty model would otherwise produce a truncated packet, a JSON
parse failure and a dropped directive.

A reply is only accepted if its directive is one of the eight vocabulary words.
The relay normalises and validates already, but the badge does not trust the
network. A reply whose `seq` is within 2 of the current one is accepted rather
than only an exact match: directives take two to four seconds and change
slowly, so one aimed at the previous beacon is still worth acting on.

Nothing blocks. The socket is non-blocking and polled once per frame, and the
ordinary case is an empty socket raising `OSError` with `errno == 11`.

### When the network is not there

This is the part that matters on the day. Every failure lands in the same
place: reflexes and the badge's own navigation carry the game.

| | what happens |
|---|---|
| no `WIFI_SSID` in `settings.toml` | boots straight to `LOCAL`, never retries |
| association fails | one message, then `LOCAL` |
| relay absent or unreachable | beacons go out, each unanswered request times out after 12 s, the strip falls back to `LOCAL` after 45 s of silence |
| relay comes back | directives resume, no restart |
| link drops | retries every 20 s until it associates, and **builds a new socket** each time |
| the badge dies with no relay | respawns to `LOCAL` and carries on |

The new socket is not optional. CircuitPython does not close user sockets on
disconnect and the old pcb keeps the stale IP, so a socket that survives a
reconnect silently stops working. Recreating it is cheap and removes a whole
class of worked-at-rehearsal-dead-on-the-day failure.

Associating blocks -- CircuitPython has no non-blocking connect -- so a
reconnect visibly stalls a frame, and `NET_RETRY` is what bounds how often the
badge is allowed to pay that. It keeps retrying: an earlier version gave up
after the first failure, and one transient blip then left the badge on `LOCAL`
for the rest of the run.

The last row matters more than it looks. Offline there is nothing that can ever
replace the directive, so a respawn that set `HOLD` left the badge standing on
the spawn tile until it was power cycled. Death is the one event that can hand
the badge a directive without the relay, so it hands it `LOCAL`.

`RELAY_HOST` is the field repair. It defaults to `""`, meaning broadcast. If a
venue AP isolates its clients, broadcast never arrives, and putting the Pi's IP
there takes broadcast out of the picture without touching another line. It is
also what you need when running the simulator under WSL2, which sits on its own
NAT'd subnet and cannot broadcast to the LAN at all.

### Three things about CircuitPython sockets

Each of these was expensive to establish and contradicts what the docs imply.

**Do not ask for `SO_BROADCAST`.** It is not exposed, it is unnecessary because
lwIP's broadcast filter is compiled out on the ESP32, and on some ports asking
raises `OSError`. `SO_REUSEADDR` is one of only two options the implementation
accepts.

**`recvfrom` does not exist.** Only `recvfrom_into`, and truncation is silent,
so the 512-byte buffer has to comfortably exceed any reply.

**`settimeout(0)`, not a small positive timeout.** They are not the same: a
positive timeout raises `ETIMEDOUT` instead of `EAGAIN` and the poll idiom
stops working.

**`RELAY_HOST` must be an IP literal, never a hostname.** CircuitPython
resolves the host on every `sendto()`, which would put a DNS lookup inside the
frame loop.

And one that is not about sockets: `wifi.radio.power_management` must be
`NONE`. The default wakes only on DTIM and `MAX` drops AP-buffered broadcast
frames outright, which is exactly the traffic this design runs on. The same
setting cost 65-110 ms per packet on the Pi before it was disabled there.

### Asking for a new directive

The request is fired from inside Decide, in the no-urgency branch, never on a
timer. The badge asks for judgment when it has the space to use it, and never
mid-firefight.

That needs one addition `gameplay.md` does not specify: a staleness ceiling. A
badge pinned in a long fight would otherwise act on a two-minute-old directive,
so `DIRECTIVE_MAX_AGE` forces a request through regardless of urgency.
`DIRECTIVE_MIN_INTERVAL` is the floor underneath it, so a calm badge does not
ask forty times a second.

## Code design

**The world is parsed once.** `WORLD` is readable strings, but strings are a
bad thing to index thousands of times a second, so boot flattens it into a
`bytearray` of 1s and 0s. Spawn positions come out into a list at the same time,
and `OPEN_TILE_COUNT` is counted then too, so the explored fraction the network
beacon reports is a division instead of a scan.

**Trigonometry is a lookup table.** `math.sin` is soft-float on the ESP32-S3.
The heading is quantised to 512 steps, which is 0.7 degrees, and the two tables
are `array("f")` rather than lists so they cost 2 KB each instead of about 8 KB.
Nothing calls `math` after boot.

**The raycaster is textureless DDA.** One `fill_region` per wall slice and one
for the floor below it, into a 16-colour bitmap that displayio packs at 4 bits
per pixel. Walls hit on an x-face get a brighter shade than walls hit on a
y-face, and there are three distance bands of each, which is enough for corners
and depth to read with no texture work at all.

Clearing is `bitmap.fill(0)`, never a full-screen `fill_region`. In the
simulator that is 0.07 ms against 38 ms, and on hardware it is the same call
either way. Column tops and bottoms are clamped explicitly, because
out-of-bounds writes silently no-op in the simulator and hardware has never
promised to agree.

**Two renderers, one call site.** `render()` dispatches on `view_mode` and
nothing else in the file knows which one ran. That boundary is deliberate: if
the raycaster turns out to be too slow on the real badge, SW1 or the `VIEW_MODE`
constant switches to top-down and not one other line changes.

**The directive strip is its own bitmap.** It sits below the viewport rather
than inside it, so it gets drawn once at boot instead of being cleared and
redrawn on every frame.

**Entities are drawn as flat blocks with a depth buffer.** The raycaster keeps
the wall distance for each of its 40 columns, and the sprite pass drops any
column where the wall is nearer than the entity. Column granularity, not pixel,
because the wall slices are drawn that way too, so the two line up exactly.
This is not in the step plan, which specifies walls only. It is here because
the raycast view is the screen people watch, and without it the badge stands in
an empty corridor firing at nothing.

**Exploration is marked from the player, not the rays.** The 5x5 block of tiles
around the player, each frame. Doing it in the raycaster would have been cheaper, but
then the top-down map would never fog correctly for anyone who leaves it in
top-down mode and never switches.

**The badge remembers what it has seen.** The directive table talks about the
nearest *known* enemy and the last *known* medkit, and known is not the same as
visible. Any enemy actually in view trips a reflex, so a HUNT weighted on sight
alone would never once get to apply. Memory is what lets HUNT walk the badge
toward something around a corner.

**It commits to a target tile, and walks to the centre of it.** Re-scoring
every frame chatters: standing on a tile boundary flips `int(player_y)` between
two rows, each scores a different winner, and the badge shivers in the doorway.
Arriving means reaching the centre, not merely crossing the line, because a
player stopped at the edge has its 0.44-wide collision box clipping the wall
corner beside every perpendicular opening, and the only move left is back the
way it came.

**The badge can navigate without the directive.** A breadth-first search finds
the nearest unexplored tile and pulls toward it, recomputed at most every two
seconds. It only gets a vote when the directive has no opinion, which is the
point: letting it compete with a live directive made the two alternate, and the
badge spent its whole life turning around. With this, a `HOLD` or an unhelpful
answer costs the demo nothing.

"No opinion" means the directive did not name *this* direction. `EXPLORE_N`
adds a small bonus to any unexplored neighbour whichever way it points, and
counting that as an opinion kept the frontier switched off on exactly the tiles
where north is a wall, which is where the badge most needs routing out.

**Revisiting a tile costs something, and being stuck costs more.** Three layers,
in increasing order of bluntness, because a badge that gets wedged on a lanyard
is the worst possible failure:

1. A decaying visit count per tile. A directive can name a direction that is
   locally sensible on every tile of a small pocket and still trap the badge in
   it; each move looks like the best one available from the tile it is made
   from, so nothing in the scoring notices. Charging a tile for being revisited
   breaks the cycle once the penalty outgrows the directive's weight. It decays,
   so a corridor the badge legitimately needs to cross twice does not become
   permanently unattractive.
2. A goal that could not be reached within six seconds is charged extra and
   dropped. Dropping alone was not enough: the same scoring ran again from the
   same tile and chose the same unreachable goal, and the badge turned on the
   spot in a six second cycle.
3. A watchdog. Ten seconds inside a tile and a half hands navigation to the
   frontier search for six seconds regardless of what the directive says, which
   is long enough to walk out of any pocket on a 32x32 map. It prints a `STUCK`
   line to serial when it fires. It deliberately does not override `HOLD`: a
   badge told to hold and standing still is doing as it was told, and the
   reflexes still fire underneath.

**Turning is not free.** Act does one thing per frame, so every frame spent
turning is a frame not spent walking. At the original 2.4 rad/s a ninety degree
corner cost thirteen frames against the five it takes to cross the tile after
it, and a badge in a one-tile-wide maze spent most of its life rotating.
`TURN_SPEED` is 4.5 for that reason, and it is the knob to reach for if the
badge looks sluggish on hardware.

## Running it on a laptop

The desktop simulator runs this file unmodified:

```sh
sim/.venv/bin/python sim/run.py Doomish --fps
```

Keys `1`, `2`, `3` are SW1, SW2, SW3. The frame rate it prints is the laptop's,
not the badge's, and the two have nothing to do with each other. See
`sim/README.md` for why.

## Known limits, for now

- **`ROTATION = 90` is unproven on the real panel.** Every other sample in this
  repo runs portrait at `rotation=0`, and `AGENTS.md` only documents landscape
  through the `busdisplay` route with an explicit MADCTL byte. The simulator
  cannot settle it either: its ST7735R fake accepts `colstart`, `rowstart`,
  `bgr` and `invert` and ignores all four, so it will render perfectly aligned
  whatever the hardware does. Real HS180S10B panels often need those offsets.
  Check it first thing on the badge. Both renderers and the HUD have been swept
  clean at rotation 0, 90, 180 and 270, so if landscape is wrong the fix is one
  character.
- The badge's local stub is gone, replaced by the socket. It lives on in the
  step-3 test harness, which is where it belonged: a stand-in for the relay
  is a testing concern, not something to ship on the drive.
- **A permanently pinned directive can still corner the badge.** Left pinned
  for twenty minutes, one of the eight words found a stretch where the badge
  worked a small area for about twenty seconds before the watchdog walked it
  out. Unpinned, which is how it ships and how the relay drives it in step 4,
  two twenty-minute runs from opposite corners of the map never dropped below
  1.4 tiles of movement in any twenty second window and covered 85 to 95% of
  the map. `PIN_DIRECTIVE` is a demo switch, and the real system changes its
  mind every five seconds.
- Enemies are stationary sentries. They shoot when they can see you and they do
  not chase. That is deliberate: a spectator can see why the badge is taking
  damage, which is worth more in a talk than pursuit behaviour nobody can
  follow.
- Death respawns at the start tile with the map reset and the explored overlay
  kept, and prints a line to serial. A frozen GAME OVER screen on a lanyard is
  dead air.
- Pixel 4 of the LED strip is the network: bright cyan for a beat when a
  directive lands, a faint glow while a request is out, dim while the link is
  idle, and dark when there is no relay at all.
