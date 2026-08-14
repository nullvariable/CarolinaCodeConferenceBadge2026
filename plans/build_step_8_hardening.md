# Build step 8: what the earlier plans did not consider

**Deliverable:** two things. Part 1 is a set of amendments that must be folded
into steps 2-4 *as they are built*, covering design holes the step documents do
not address. Part 2 is genuinely new work: crash containment, memory budget,
relay quota safety, a venue power plan, and the Saturday runbook.

**Depends on:** Part 1 depends on nothing -- read it before starting step 2.
Part 2 items name their own dependencies. **Blocks:** nothing, but N5 must be
done before Saturday morning.

Read `plans/build_overview.md` first.

## Part 1: amendments to steps 2-4

### A1. The combat model is undefined

Steps 2-3 render enemies and react to them, but nothing anywhere says what an
enemy *does*. Fill the hole with the cheapest model that reads well from a
lanyard. All constants go in the config banner; they are proposals, tune them
against step 3's pacing goals (badge survives minutes, spectator can follow).

* Enemies step one tile toward the player when they have line of sight, at most
  every `ENEMY_STEP_SEC = 0.8`. No LOS means stand still. No pathfinding.
* Damage is melee only: an enemy on an adjacent tile costs the player
  `ENEMY_DPS = 8` HP per second. No projectiles -- they are expensive to render
  at 40 columns and invisible to a spectator anyway.
* Player fire is hitscan along facing, using the same DDA walk as the renderer,
  first enemy hit takes 1 damage. Enemies die at `ENEMY_HP = 2`. One shot costs
  1 ammo.
* Pickups are on tile entry: medkit +25 HP capped at 100, ammo +8.
* Enemies respawn at their spawn tile after `ENEMY_RESPAWN_SEC = 30`, items
  after `ITEM_RESPAWN_SEC = 45`. Without respawns the badge clears the map in
  minutes and the rest of the day is an empty-corridor screensaver.

### A2. The raycast view has no way to draw enemies or items

Step 2's raycast section draws walls only, and its top-down section draws
entities as pixels, so the primary view would show a world the badge claims to
be fighting in with nothing visible in it. Billboard bars are enough:

* During the wall pass, store each column's wall distance in a preallocated
  `RAY_COLS`-length list. This is the depth buffer and it costs one store per
  column.
* For each entity with LOS: angle from player gives the screen column, distance
  gives bar height using the same height formula as walls. Draw it as a 2-3
  column `fill_region` in the entity's palette colour, skipping any column
  whose wall distance is nearer than the entity. Draw far-to-near.
* No textures, no scaling art. A red bar that gets taller as it approaches is
  legible at 160x128 and that is the bar to clear.

### A3. Movement speed is frame-rate dependent as specified

Step 3 tunes "2-4 tiles/sec" but the loop runs at ~21 FPS in the simulator and
maybe 5-10 FPS on the badge. Anything tuned per-frame in the sim arrives 2-4x
slower on hardware. Gate every rate by time, not by frames:

```python
if now - last_player_step >= PLAYER_STEP_SEC:   # 0.35 to start
    # act() may execute a move this frame
```

Same pattern for enemy steps (A1), LED updates (step 2 already says 100 ms),
and the serial status line. Tune the `_SEC` constants, never a per-frame
distance. This is what makes simulator tuning transfer to the badge at all.

### A4. Reconnect blocks, and step 4 does not say where it is allowed to

`wifi.radio.connect()` blocks for multiple seconds. Step 4 says "if
`wifi.radio.connected` goes false: reconnect" -- called naively that freezes
the game solid, in a loop, exactly when the venue wifi is flaky. Rules:

* Attempt reconnect only from the no-urgency branch of Decide, at most every
  `WIFI_RETRY_SEC = 15`.
* One attempt, wrapped in try/except; on failure show `LOCAL` and keep playing.
* Accept that the attempt itself freezes a few frames. Put `WIFI...` in the
  directive strip first so the freeze looks intentional.

### A5. Nothing verifies the beacon stays under 400 bytes

`recent` (6 entries), the enemies list, and the items list all grow. Cap at
serialisation time: nearest 3 enemies, nearest 2 items. In the simulator, print
`len(payload)` on every send; step 4's verification should include seeing the
worst-case number and confirming it is under 400.

### A6. `time.monotonic()` degrades over an all-day uptime

If step 7's `sys.implementation` check shows 4-byte floats, `time.monotonic()`
loses millisecond precision after a few hours of uptime -- and the badge is on
from Saturday morning. Frame dt, `DIRECTIVE_MAX_AGE`, and every `_SEC` gate go
coarse together. Use the tick counter instead, copied into the sample:

```python
_TICKS_PERIOD = 1 << 29
def ticks_diff(a, b):                     # a - b, rollover-safe
    return ((a - b + (_TICKS_PERIOD // 2)) % _TICKS_PERIOD) - (_TICKS_PERIOD // 2)
now = supervisor.ticks_ms()
```

`sim/fakes/supervisor.py` (step 1) gains
`ticks_ms = lambda: int(time.monotonic() * 1000) % (1 << 29)` so the same code
runs in the simulator.

### A7. Death crosses the beacon boundary

Step 3 defines respawn but step 4's beacon does not account for it. Two rules:
`seq` keeps counting monotonically across respawns, and `"DIED"` is pushed onto
`recent` at respawn so the model can see it keeps getting the badge killed.

## Part 2: new work

### N1. Crash containment on the badge

Depends on step 2. An unhandled exception on a lanyard is a frozen traceback
for the rest of the day. Wrap the main loop:

```python
_crashes = []
while True:
    try:
        main_loop()                        # never returns normally
    except (KeyboardInterrupt, SystemExit):
        raise                              # serial ctrl-C and the exit chord still work
    except Exception as e:
        traceback.print_exception(e)       # full trace to serial
        _crashes.append(supervisor.ticks_ms())
        if len(_crashes) >= 3 and ticks_diff(_crashes[-1], _crashes[-3]) < 60_000:
            raise                          # crash loop: stop hiding the bug
        reset_game_state()                 # respawn, keep explored map, keep socket
```

The 3-in-60s cap matters: a persistent bug should surface, not spin silently.

### N2. Memory is never measured

Depends on step 2. No PSRAM, ~512 KB, and no step ever looks at the heap. Doomish
will be the largest single file in `samples/`, and the Launcher `exec()`s raw
source, so the compile itself happens on the badge heap.

* Add `gc.mem_free()` to the once-per-second serial line from step 2.
* Allocate every bitmap, table, and buffer at boot. The only tolerated in-loop
  allocation is the EAGAIN exception step 4 already documents.
* On first hardware boot (step 7), record `gc.mem_free()` right after setup.
  Under ~60 KB free, cut `RAY_COLS` and the palette before anything else.
* Step 4's 15-minute soak already watches frame time; watch `mem_free` in the
  same run -- a downward trend is a leak even if frame time looks fine.

### N3. Relay quota and burst safety

Depends on nothing (relay is done). At `DIRECTIVE_MIN_INTERVAL = 5` s the badge
can generate ~720 Ollama Cloud calls per hour, all day. Nobody has checked the
subscription's rate limits, and `relay.py` currently has no 429 handling and no
dedup. Add to `relay/relay.py`:

* A one-entry cache keyed on the exact `describe(state)` text, TTL 3 s.
  Duplicate beacons (retries, unchanged state) return the cached directive with
  `source` suffixed `+cached`, no API call.
* On HTTP 429 or 3 consecutive transport failures: back off (double from 5 s,
  cap 60 s), serve `heuristic` with `source: "heuristic+backoff"`, log loudly.
  The dashboard (step 5) already colours heuristic rows, so backoff is visible.
* Log a per-hour call counter so Saturday's total is a known number, not a
  guess. Update the `relay/README.md` config table.

### N4. Venue power plan

Nothing plans power for a full conference day. Three devices, three answers:

* **Badge:** wifi with power management off, backlight on, 5 NeoPixels at 0.35.
  CR123A runtime under that load is unknown, and wifi TX bursts on a sagging
  battery mean brownout resets, which present as random reboots. Run the demo
  on a USB power bank. If Friday leaves time, measure actual CR123A runtime
  once and write it in `samples/Doomish/README.md`; otherwise just do not trust
  the cell on stage.
* **Pi 3 B:** wants 5 V / 2.5 A. The HANDOFF power-bank check was for the Zero
  W; the plan since moved to the 3 B and nobody re-verified. Confirm the bank
  holds it for 15 min without auto-off, or claim a wall outlet at the venue.
* **Phone:** hotspot plus cellular all day. Plugged in, screen kept awake per
  whatever step 0's test 5 found about hotspot sleep.

### N5. Saturday runbook and the stage fallback ladder

Depends on steps 4 and 7. Step 7 is bring-up; nothing owns the demo itself.
Write `plans/runbook_saturday.md` with two sections. (Demo rig only -- talk
materials stay off-limits per HANDOFF.)

Morning checklist: badge has `samples/Doomish/` and root `settings.toml` with
the hotspot creds; phone hotspot up, plugged in; Pi powered, `doomish-relay`
active, hotspot IP written down; dashboard reachable from the laptop; one full
beacon-to-directive round trip observed before leaving the prep table.

Fallback ladder, in order, each one rehearsed once on Friday:

1. Full demo: badge + relay + LLM directives.
2. Relay or hotspot dead: badge in `LOCAL` reflex-only mode. Still a live game
   on a badge; narrate what the strip would show.
3. Badge dead: `sim/run.py Doomish` plus `fake_badge.py` and the dashboard on
   the laptop. Same brain, no hardware.
4. Everything dead: a screen recording of option 3, captured Friday and stored
   at `plans/demo-recording.mp4` (gitignored -- check the size). Record it the
   moment step 4 passes verification, while everything is known to work.

Option 4 costs ten minutes on Friday and is the difference between "the wifi
gods said no, here is what it looks like" and dead air.

## Verification

1. Simulator: an adjacent enemy visibly drains HP, two shots kill it, and both
   it and a used medkit respawn on their timers.
2. Enemies render in the 3D view and are occluded when a wall is between them
   and the player. Walk behind a wall and confirm the bar disappears.
3. Halve the simulator frame rate (add a `time.sleep(0.05)` in the loop
   temporarily). Player tiles-per-second stays the same. Remove the sleep.
4. Worst-case beacon length printed and under 400 bytes.
5. Crash test: temporarily `raise ValueError` inside `act()`. The game logs the
   traceback and respawns; three crashes inside a minute re-raises; the exit
   chord still works throughout.
6. `mem_free` appears in the serial line and does not trend down over step 4's
   15-minute soak.
7. Two identical beacons 2 s apart produce one Ollama call and a `+cached` tag
   in the relay log; a simulated 429 (point `OLLAMA_URL` at a stub or revoke
   the key) produces `heuristic+backoff` rows and a rising backoff in the log.
8. Power bank runs the Pi 3 B for 15 min; the badge demo config assumes USB
   power.
9. `plans/runbook_saturday.md` exists, the recording exists, and ladder options
   2 and 3 have each been exercised once.
