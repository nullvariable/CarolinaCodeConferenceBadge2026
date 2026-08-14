# Build step 3: the OODA loop

**Deliverable:** the badge plays itself. Reflexes handle danger, the directive
biases everything else. Still no networking: the directive is a variable set by
hand or by a local stub.

**Depends on:** step 2. **Blocks:** step 4.

Read `plans/build_overview.md` and `plans/gameplay.md` first. `gameplay.md` is
Doug's and takes precedence over anything inferred here.

## The loop

From `plans/gameplay.md`, verbatim in structure:

```
Observe   what is the game showing us right now?
Orient    what has changed since the last loop?
Decide    urgent threat?
              -> act locally (reflex), shoot, heal etc
          no urgency
              -> apply current LLM directive
              -> if not requesting a new directive, request a refreshed one
Act       execute
```

Four functions, called in order, every frame. Keep them named `observe()`,
`orient()`, `decide()`, `act()` so the code and the design document read the
same. That naming is worth more than any micro-optimisation here, because this
loop is the thing the talk is about.

## Observe

Build a small snapshot dict from world state. Nothing clever, just gather:

* hp, ammo, position, facing
* enemies with line of sight, as (direction, distance)
* items within a radius, as (kind, direction, distance)
* walls immediately N/S/E/W of the player
* explored fraction

This is the same shape as the beacon (see the overview), deliberately. Step 4
serialises this snapshot rather than building a second one.

Line-of-sight uses the same DDA traversal as the renderer. Walk the grid from
player to entity and stop at the first wall. Do not add a second algorithm.

## Orient

Diff against the previous snapshot and record what changed:

* new enemy appeared in view / last enemy left view
* hp dropped since last frame, and by how much
* ammo hit zero
* a new tile became explored
* the directive changed since last frame

Orient exists to answer "what is new", and its output is what makes urgency
decidable without re-scanning the world. Keep the previous snapshot in a single
variable and swap it at the end of the frame.

## Decide

Urgency first, always. These are the reflexes and they are never overridden by a
directive:

```
if enemy in view and ammo > 0 and aligned within N degrees:
    -> FIRE
elif hp < CRITICAL_HP and enemy in view:
    -> RETREAT along the last safe direction, toward the last seen medkit
elif ammo == 0 and enemy in view:
    -> BREAK CONTACT
elif blocked ahead:
    -> TURN toward the most open adjacent direction
```

No urgency means the directive applies. The directive **biases, it does not
command**. Concretely: score the four candidate moves (N/S/E/W) each frame and
pick the highest. The directive adds weight, it does not select:

| directive | weighting |
|---|---|
| `EXPLORE_<dir>` | +large toward that compass direction, +small toward any unexplored neighbour |
| `HUNT` | +large toward the nearest known enemy |
| `RETREAT` | +large away from enemies, + toward last known medkit |
| `SEEK_ITEM` | +large toward the nearest known item |
| `HOLD` | +large to staying put, reflexes still fire freely |

Walls are a hard veto, not a weight. Everything else is additive. This is what
makes the directive visibly *influence* rather than *puppet* the player, which is
the whole point of showing the directive on screen.

### Requesting a refresh

Per `gameplay.md`, the request is triggered from inside Decide, in the no-urgency
branch, when no request is already in flight. Not on a fixed timer.

That is better than a fixed cadence because the badge asks for judgment when it
has the space to use it, and never mid-firefight. It needs one addition
`gameplay.md` does not specify:

**A staleness ceiling.** A badge pinned in a long fight would otherwise never
refresh and would act on a two-minute-old directive. So force a request when the
current directive is older than `DIRECTIVE_MAX_AGE` (start at 20 s) regardless of
urgency. Also keep a floor, `DIRECTIVE_MIN_INTERVAL` (start at 5 s), so a calm
badge does not spam the relay every frame.

Request logic, in the order it should be written:

```
want = (no request in flight)
       and (now - last_request >= DIRECTIVE_MIN_INTERVAL)
       and (not urgent or now - directive_at >= DIRECTIVE_MAX_AGE)
```

In this step, "request" just sets a flag and a stub fills the directive in after
a fake delay. Step 4 replaces the stub with the socket. Simulating the 2-4 s
real latency here matters: build against the delay so the loop is correct before
the network can hide the bug.

## Act

Execute exactly one action per frame: fire, step, turn, or hold. Keep it a single
switch so there is one place where the game state actually mutates.

Append the executed directive to `recent` (cap at 6) only when the directive
changes, not every frame. `recent` is what tells the model it has been repeating
itself.

## Difficulty and pacing

The demo is watched, not played. Tune so a spectator can follow: movement in the
range of 2-4 tiles/sec, enemies that take a couple of seconds to kill, and a
badge that survives minutes rather than seconds. A badge that dies in 20 seconds
on a lanyard is a worse demo than one that never dies.

Decide what death means now, not later. Recommended: respawn at the start tile
with a reset map, keeping the explored overlay, and print a line to serial. A
frozen "GAME OVER" screen on a lanyard is dead air.

## Verification

1. In the simulator with the directive pinned to `HOLD`, the player stays put but
   still fires at anything that comes into view. That single test proves
   reflexes are not gated behind the directive.
2. Pinned to `EXPLORE_E`, the player works east, but still turns at walls and
   still breaks off to fight.
3. Pinned to `SEEK_ITEM` with no items known, nothing breaks. It should degrade
   to ordinary exploration, not deadlock.
4. `RETREAT` at low HP visibly moves away from enemies.
5. With the stub delay set to 4 s, the loop never stalls and never double-
   requests. Log every request and reply to serial and read the trace.
6. Leave it running 10 minutes unattended. It should still be alive, still
   exploring, and `recent` should show variety rather than one directive
   repeated 40 times.
