# Build step 5: the Pi dashboard

**Deliverable:** a small web server on the Pi showing what the badge sees and
what the LLM decided, per `plans/wishlist spec.md`.

**Depends on:** the relay (done). Independent of steps 2-4, can be built in
parallel or skipped. **Blocks:** nothing.

Read `plans/build_overview.md` and `plans/wishlist spec.md` first. The wishlist
is Doug's and takes precedence.

## The spec, restated

```
left panel
    some visual representation of the game state if possible
    debug or other visual representation of the game (what we give the llm)

right panel
    recent LLM turns, newest at the bottom
```

"What we give the LLM" is the important half. `relay.py:describe()` already
flattens a beacon into the exact prompt text the model receives. Showing that
verbatim next to the answer is the whole debugging story: you can see the model
being asked a bad question, which is usually what is actually wrong.

## Constraints

* **Standard library only.** The relay is stdlib-only on purpose and runs on
  whatever Python the host has. Do not add Flask. `http.server` is enough.
* **Must not slow the relay.** The directive path is the product; the dashboard
  is an observer. Serve from a separate thread, never block the UDP receive
  loop or the worker on an HTTP client.
* Single file, `relay/dashboard.py`, imported by `relay.py` and started only
  when `--dashboard` is passed or `DOOMISH_DASHBOARD=1` is set. Off by default so
  the demo path stays minimal.

## Design

### Data

A bounded ring buffer of the last N exchanges (start at 50), appended by the
relay worker right where it currently logs. One entry:

```python
{
  "t": <epoch seconds>,
  "addr": "192.168.1.60:5116",
  "seq": 42,
  "state": {...},              # the raw beacon dict
  "prompt": "<describe(state) output>",
  "directive": "HUNT",
  "why": "enemy known and healthy",
  "source": "gpt-oss:20b",     # or "heuristic", or "gpt-oss:20b+repaired"
  "elapsed": 2.41,
}
```

Use `collections.deque(maxlen=N)`. Guard with the existing lock or its own. The
relay must never wait on the dashboard, so if you have to choose, drop dashboard
data rather than delay a directive.

### Server

`http.server.ThreadingHTTPServer` on port 8080, bound to `0.0.0.0` so it is
reachable from the laptop and phone. Three routes:

* `GET /` -- the page, one self-contained HTML string, no CDN, no external
  assets. The Pi will not always have internet at a venue.
* `GET /api/state` -- JSON: latest entry plus the ring buffer.
* `GET /api/stream` -- optional Server-Sent Events. Poll every 1 s from the page
  first and only add SSE if polling feels laggy. Polling is 5 lines and cannot
  wedge.

### Page

Two columns, CSS grid, dark, readable from a few feet away since this will be on
a laptop next to the badge.

**Left, top:** the game state drawn from the beacon. A 32x32 grid on a
`<canvas>` or a CSS grid of divs: walls, explored tiles, player with facing,
enemies, items. This is the "visual representation of the game state" and it is
genuinely useful because it shows whether the badge's model of the world matches
what is on the badge screen.

**Left, bottom:** the prompt text, verbatim, in a monospace block. Plus hp, ammo,
explored percent, and the `recent` list.

**Right:** the exchange log, newest at the bottom, auto-scrolled. One row per
turn: timestamp, directive as a coloured chip, the `why`, latency, and the
source. Tag heuristic fallbacks and `+repaired` answers visibly, in a different
colour. Those two states are the ones worth noticing at a glance, because both
mean the LLM is not actually steering.

Colour the directive chips by family: explore blue, hunt red, retreat amber,
seek-item green, hold grey. From across a table the colour pattern alone shows
whether the model is thinking or stuck.

### Failure behaviour

If no beacon has arrived in 15 s, say so in large text. A dashboard that shows a
stale state indistinguishably from a live one is worse than no dashboard.

## Wiring into relay.py

One import guarded by the flag, one `deque` append next to the existing log call,
one thread start. If the dashboard import fails, log it and continue. The relay
must run with the dashboard file deleted.

## Verification

1. Relay running with `--dashboard`, `fake_badge.py` beaconing. The page shows a
   live map, the prompt, and turns appearing at the bottom.
2. Open from a phone on the same wifi. Layout still readable.
3. Stop `fake_badge.py`. The stale banner appears within 15 s.
4. Kill the API key so every cycle falls back. Heuristic rows are visually
   distinct from model rows.
5. Hammer it: hold refresh in two browser tabs while beacons flow. Directive
   latency in the relay log must not change. If it does, the dashboard is on the
   critical path and needs moving off it.
6. Delete `dashboard.py` and start the relay. It must still run.
