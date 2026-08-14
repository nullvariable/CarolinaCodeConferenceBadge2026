#!/usr/bin/env python3
"""Doomish dashboard: what the badge said, and what the model said back.

An observer, never a participant. The relay hands it a copy of each exchange
and carries on; nothing here can delay a directive, and the relay runs fine
with this file deleted.

    python3 relay.py --dashboard              # then http://<pi>:8080/
    DOOMISH_DASHBOARD=1 python3 relay.py

Standard library only, same as the relay. No Flask, no CDN, no external assets:
the Pi will not always have internet at a venue, and a dashboard that needs to
fetch a stylesheet is a dashboard that is blank on stage.

Run it alone to check the page renders without a relay:

    python3 dashboard.py --demo
"""

import argparse
import ast
import json
import os
import sys
import threading
import time
from collections import deque

try:
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
except ImportError:  # pragma: no cover -- ThreadingHTTPServer landed in 3.7
    from http.server import BaseHTTPRequestHandler, HTTPServer
    from socketserver import ThreadingMixIn

    class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
        daemon_threads = True

DEFAULT_DASHBOARD_PORT = int(os.environ.get("DOOMISH_DASHBOARD_PORT", "8080"))
DEFAULT_HISTORY = 50
STALE_AFTER = 15.0          # seconds of silence before the page says so


# ------------------------------------------------------------------
# The map
# ------------------------------------------------------------------
# The beacon does not carry the map -- it is 32 rows of walls and would blow
# the ~400 byte budget on every single packet for something that never changes.
# So the dashboard keeps its own copy. This is a verbatim paste of WORLD from
# samples/Doomish/code.py.
#
# A stale copy here draws the wrong maze under a correct player position, which
# looks like a badge bug and is not one. So when the dashboard can see the repo
# it reads WORLD out of the sample instead and this copy is only the fallback --
# which is what runs on the Pi, where only relay/ gets copied across.
WORLD_FALLBACK = (
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

_SAMPLE_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    os.pardir, "samples", "Doomish", "code.py",
)


def load_world(path=_SAMPLE_PATH):
    """Return (rows, source). Parses the sample rather than importing it.

    `ast` and not `exec` or an import, because samples/Doomish/code.py is badge
    code: importing it would reach for `board` on line one and take the whole
    relay down with it.
    """
    try:
        with open(path, "r") as fh:
            tree = ast.parse(fh.read())
    except Exception:
        return WORLD_FALLBACK, "built-in copy"

    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        names = [t.id for t in node.targets if isinstance(t, ast.Name)]
        if "WORLD" not in names:
            continue
        try:
            rows = ast.literal_eval(node.value)
        except ValueError:
            break
        if rows and all(isinstance(r, str) for r in rows):
            return tuple(rows), os.path.relpath(path)
        break

    return WORLD_FALLBACK, "built-in copy"


# ------------------------------------------------------------------
# The ring buffer
# ------------------------------------------------------------------
class Dashboard(object):
    """Holds the last N exchanges and serves them. Never raises at the relay.

    Every method the relay touches swallows its own exceptions. The rule from
    the step plan is that if there is a choice between dropping dashboard data
    and delaying a directive, the data goes -- so a bug in here must not be able
    to propagate into the worker thread.
    """

    def __init__(self, port=DEFAULT_DASHBOARD_PORT, history=DEFAULT_HISTORY,
                 system_prompt="", log=None):
        self.port = port
        self.system_prompt = system_prompt
        self.log = log or (lambda msg: sys.stdout.write(msg + "\n"))
        self._entries = deque(maxlen=history)
        self._lock = threading.Lock()
        self._n = 0                 # monotonic id, so the page can ask for "newer than"
        self._started_at = time.time()
        self._server = None
        self.world, self.world_source = load_world()

    # -- called by the relay worker ---------------------------------
    def record(self, addr, state, prompt, directive, why, source, elapsed,
               stats=None):
        """Append one exchange. Called from the worker, so it stays cheap."""
        try:
            entry = {
                "t": time.time(),
                "addr": "%s:%d" % (addr[0], addr[1]),
                "seq": state.get("seq"),
                "id": state.get("id"),
                "state": state,
                "prompt": prompt,
                "directive": directive,
                "why": why,
                "source": source,
                "elapsed": round(elapsed, 2),
                "stats": dict(stats) if stats else {},
            }
            with self._lock:
                self._n += 1
                entry["n"] = self._n
                self._entries.append(entry)
        except Exception as exc:            # pragma: no cover -- belt and braces
            self.log("dashboard: dropped an entry (%s: %s)" % (type(exc).__name__, exc))

    # -- called by the http handler ---------------------------------
    def since(self, after):
        """Entries newer than `after`, plus the newest one whatever its age."""
        with self._lock:
            entries = [e for e in self._entries if e["n"] > after]
            latest = self._entries[-1] if self._entries else None
            n = self._n
        return entries, latest, n

    def start(self):
        """Start the server thread. Returns True if it is actually listening."""
        try:
            handler = _make_handler(self)
            self._server = ThreadingHTTPServer(("0.0.0.0", self.port), handler)
            self._server.daemon_threads = True
        except OSError as exc:
            self.log("dashboard: cannot bind port %d (%s), continuing without it"
                     % (self.port, exc))
            return False

        thread = threading.Thread(target=self._server.serve_forever)
        thread.daemon = True
        thread.start()
        self.log("dashboard on http://0.0.0.0:%d/  (map from %s)"
                 % (self.port, self.world_source))
        return True

    def stop(self):
        if self._server is not None:
            self._server.shutdown()


def _make_handler(dash):
    class Handler(BaseHTTPRequestHandler):
        # BaseHTTPRequestHandler logs every request to stderr by default, which
        # would bury the relay's own log under one line per poll per second.
        def log_message(self, fmt, *a):
            pass

        def _send(self, code, body, ctype):
            if not isinstance(body, bytes):
                body = body.encode("utf-8")
            try:
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                # A closed tab mid-response is normal, not an incident.
                pass

        def do_GET(self):
            path, _, query = self.path.partition("?")

            if path == "/":
                return self._send(200, PAGE, "text/html; charset=utf-8")

            if path == "/api/world":
                return self._send(200, json.dumps({
                    "world": list(dash.world),
                    "source": dash.world_source,
                    "system_prompt": dash.system_prompt,
                    "stale_after": STALE_AFTER,
                }), "application/json")

            if path == "/api/state":
                after = 0
                for part in query.split("&"):
                    key, _, val = part.partition("=")
                    if key == "after":
                        try:
                            after = int(val)
                        except ValueError:
                            after = 0
                entries, latest, n = dash.since(after)
                return self._send(200, json.dumps({
                    "now": time.time(),
                    "n": n,
                    "uptime": time.time() - dash._started_at,
                    "entries": entries,
                    "latest": latest,
                }), "application/json")

            self._send(404, "not found\n", "text/plain; charset=utf-8")

    return Handler


# ------------------------------------------------------------------
# The page
# ------------------------------------------------------------------
# One string, no build step, no assets. Read from a few feet away: this sits on
# a laptop next to the badge and people lean over to look at it.
PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Doomish relay</title>
<style>
  :root {
    --bg: #14161a; --panel: #1c1f26; --line: #2c313b;
    --fg: #e8eaf0; --dim: #98a0b0; --faint: #656d7d;
    --explore: #4a9eff; --hunt: #ff5a5a; --retreat: #ffb020;
    --seek: #46d17f; --hold: #7d8798; --warn: #ff5a5a;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; background: var(--bg); color: var(--fg);
    font: 15px/1.5 ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif;
  }
  header {
    display: flex; align-items: baseline; gap: 16px; flex-wrap: wrap;
    padding: 12px 18px; border-bottom: 1px solid var(--line); background: var(--panel);
  }
  header h1 { margin: 0; font-size: 17px; letter-spacing: .04em; text-transform: uppercase; }
  header .meta { color: var(--dim); font-size: 13px; }
  header .meta b { color: var(--fg); font-weight: 600; }
  #stale {
    display: none; margin-left: auto; padding: 4px 12px; border-radius: 4px;
    background: var(--warn); color: #14161a; font-weight: 700; font-size: 15px;
  }
  #stale.on { display: block; }

  main {
    display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
    gap: 14px; padding: 14px; align-items: start;
  }
  @media (max-width: 900px) { main { grid-template-columns: minmax(0, 1fr); } }

  .col { display: flex; flex-direction: column; gap: 14px; min-width: 0; }
  .card { background: var(--panel); border: 1px solid var(--line); border-radius: 6px; }
  .card > h2 {
    margin: 0; padding: 8px 12px; border-bottom: 1px solid var(--line);
    font-size: 12px; letter-spacing: .1em; text-transform: uppercase; color: var(--dim);
    display: flex; align-items: baseline; gap: 10px;
  }
  .card > h2 .note { text-transform: none; letter-spacing: 0; color: var(--faint); font-size: 12px; }
  .card .body { padding: 12px; }

  /* Capped, and never upscaled past its intrinsic 32x16 px. The prompt block
     below is the half of this panel worth reading, and a map that fills the
     viewport pushes it under the fold on a laptop. */
  canvas {
    display: block; margin: 0 auto; image-rendering: pixelated;
    max-width: 100%; max-height: 52vh; width: auto; height: auto;
  }

  .vitals { display: flex; gap: 18px; flex-wrap: wrap; align-items: center; margin-bottom: 10px; }
  .vital { font-variant-numeric: tabular-nums; }
  .vital span { color: var(--dim); font-size: 12px; text-transform: uppercase; letter-spacing: .08em; }
  .vital b { font-size: 19px; font-weight: 650; }
  .bar { height: 6px; background: var(--line); border-radius: 3px; overflow: hidden; min-width: 90px; }
  .bar i { display: block; height: 100%; background: var(--seek); }

  pre {
    margin: 0; padding: 10px; background: #0f1115; border: 1px solid var(--line);
    border-radius: 4px; color: #cfd6e4; font: 13px/1.6 ui-monospace, SFMono-Regular, Menlo, monospace;
    white-space: pre-wrap; word-break: break-word;
  }
  details { margin-top: 10px; }
  details summary { cursor: pointer; color: var(--dim); font-size: 13px; }
  details pre { margin-top: 8px; color: var(--faint); font-size: 12px; }

  .legend { display: flex; gap: 14px; flex-wrap: wrap; margin-top: 10px; color: var(--dim); font-size: 12px; }
  /* The outline is what makes the spawn-point swatch visible at all: it is the
     same near-background colour on the map, deliberately, and a legend key you
     cannot see is not a legend key. */
  .legend i {
    display: inline-block; width: 10px; height: 10px; border-radius: 2px;
    margin-right: 5px; vertical-align: -1px; outline: 1px solid var(--line);
  }

  #log { display: flex; flex-direction: column; gap: 8px; max-height: 74vh; overflow-y: auto; padding: 12px; }
  .turn {
    display: grid; grid-template-columns: 64px 118px minmax(0, 1fr);
    gap: 10px; align-items: baseline;
    padding: 8px 10px; border: 1px solid var(--line); border-radius: 5px; background: #191c22;
  }
  .turn .time { color: var(--faint); font: 12px ui-monospace, Menlo, monospace; }
  .chip {
    display: inline-block; padding: 3px 8px; border-radius: 4px; text-align: center;
    font: 600 12px/1.3 ui-monospace, Menlo, monospace; letter-spacing: .04em;
    color: #14161a; white-space: nowrap;
  }
  .chip.explore { background: var(--explore); }
  .chip.hunt    { background: var(--hunt); }
  .chip.retreat { background: var(--retreat); }
  .chip.seek    { background: var(--seek); }
  .chip.hold    { background: var(--hold); }
  .turn .why { color: var(--fg); min-width: 0; overflow-wrap: break-word; }
  .turn .sub { grid-column: 2 / -1; color: var(--faint); font-size: 12px; }
  .turn .tag {
    display: inline-block; margin-left: 6px; padding: 1px 6px; border-radius: 3px;
    font-size: 11px; font-weight: 600; letter-spacing: .04em;
  }
  .tag.heuristic { background: #3a2a12; color: var(--retreat); border: 1px solid var(--retreat); }
  .tag.repaired  { background: #3a2a12; color: var(--retreat); border: 1px dashed var(--retreat); }
  .turn.off { border-color: var(--retreat); }
  .empty { color: var(--faint); padding: 6px; }
</style>
</head>
<body>
<header>
  <h1>Doomish</h1>
  <div class="meta" id="meta">waiting for the first beacon...</div>
  <div id="stale">NO BEACON</div>
</header>

<main>
  <div class="col">
    <div class="card">
      <h2>Game state <span class="note" id="worldsrc"></span></h2>
      <div class="body">
        <canvas id="map" width="512" height="512"></canvas>
        <div class="legend">
          <span><i style="background:#ff5a5a"></i>enemy</span>
          <span><i style="background:#46d17f"></i>medkit</span>
          <span><i style="background:#ffd23f"></i>ammo</span>
          <span><i style="background:#e8eaf0"></i>badge</span>
          <span><i style="background:#39414f"></i>wall</span>
          <span><i style="background:#232833"></i>spawn point</span>
        </div>
        <div class="legend">
          <span>Contacts are placed by bearing and distance, the only fix the beacon carries,
          so they sit on the axis and not necessarily on the tile.</span>
        </div>
      </div>
    </div>

    <div class="card">
      <h2>What the model is told <span class="note">verbatim, from describe()</span></h2>
      <div class="body">
        <div class="vitals" id="vitals"></div>
        <pre id="prompt">nothing yet</pre>
        <details>
          <summary>system prompt (unchanged every turn)</summary>
          <pre id="sysprompt"></pre>
        </details>
      </div>
    </div>
  </div>

  <div class="col">
    <div class="card">
      <h2>LLM turns <span class="note">newest at the bottom</span></h2>
      <div id="log"><div class="empty">no turns yet</div></div>
    </div>
  </div>
</main>

<script>
var CELL = 16, world = [], staleAfter = 15, after = 0, latest = null, turns = 0;

function esc(s) {
  return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) {
    return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
  });
}

function family(d) {
  if (!d) return "hold";
  if (d.indexOf("EXPLORE") === 0) return "explore";
  if (d === "HUNT") return "hunt";
  if (d === "RETREAT") return "retreat";
  if (d === "SEEK_ITEM") return "seek";
  return "hold";
}

var STEP = { N: [0, -1], S: [0, 1], E: [1, 0], W: [-1, 0] };
var KIND_COLOUR = { medkit: "#46d17f", ammo: "#ffd23f", keycard: "#4ad9d9" };

function drawMap(state) {
  var c = document.getElementById("map"), g = c.getContext("2d");
  var h = world.length, w = h ? world[0].length : 0;
  if (!w) return;
  c.width = w * CELL; c.height = h * CELL;

  g.fillStyle = "#0f1115";
  g.fillRect(0, 0, c.width, c.height);

  for (var y = 0; y < h; y++) {
    for (var x = 0; x < w; x++) {
      var ch = world[y][x];
      if (ch === "#") { g.fillStyle = "#39414f"; }
      else if (ch === "E" || ch === "M" || ch === "A") { g.fillStyle = "#232833"; }
      else { continue; }
      g.fillRect(x * CELL, y * CELL, CELL, CELL);
    }
  }

  if (!state) return;
  var pos = state.pos || [0, 0], px = pos[0], py = pos[1];
  var cx = (px + 0.5) * CELL, cy = (py + 0.5) * CELL;

  // The four wall flags, exactly as the model is given them: a green tick on an
  // open side, red on a blocked one. Disagreement with the maze underneath is
  // the badge and the dashboard having different ideas about where it is, which
  // is worth seeing immediately.
  var walls = state.walls || {};
  for (var d in STEP) {
    var k = d.toLowerCase();
    if (!(k in walls)) continue;
    var s = STEP[d];
    g.strokeStyle = walls[k] ? "#ff5a5a" : "#46d17f";
    g.lineWidth = 3;
    g.beginPath();
    g.moveTo(cx + s[0] * CELL * 0.55, cy + s[1] * CELL * 0.55);
    g.lineTo(cx + s[0] * CELL * 0.95, cy + s[1] * CELL * 0.95);
    g.stroke();
  }

  // Contacts along their bearing axis. Dashed, because the beacon reports the
  // dominant axis only: an enemy at "E 4.2" may be a tile off to one side.
  function contact(list, colourOf) {
    for (var i = 0; i < list.length; i++) {
      var e = list[i], s = STEP[e.dir];
      if (!s) continue;
      var ex = cx + s[0] * e.dist * CELL, ey = cy + s[1] * e.dist * CELL;
      var col = colourOf(e);
      g.strokeStyle = col; g.globalAlpha = 0.45; g.lineWidth = 2;
      g.setLineDash([3, 4]);
      g.beginPath(); g.moveTo(cx, cy); g.lineTo(ex, ey); g.stroke();
      g.setLineDash([]); g.globalAlpha = 1;
      g.fillStyle = col;
      g.fillRect(ex - CELL * 0.35, ey - CELL * 0.35, CELL * 0.7, CELL * 0.7);
      g.fillStyle = "#0f1115";
      g.font = "600 9px ui-monospace, Menlo, monospace";
      g.textAlign = "center"; g.textBaseline = "middle";
      g.fillText(String(e.dist), ex, ey);
    }
  }
  contact(state.enemies || [], function () { return "#ff5a5a"; });
  contact(state.items || [], function (i) { return KIND_COLOUR[i.kind] || "#c9a0ff"; });

  // The badge: a disc, and a wedge for facing.
  g.fillStyle = "#e8eaf0";
  g.beginPath(); g.arc(cx, cy, CELL * 0.42, 0, Math.PI * 2); g.fill();
  var f = STEP[state.facing];
  if (f) {
    g.beginPath();
    g.moveTo(cx + f[0] * CELL * 1.1, cy + f[1] * CELL * 1.1);
    g.lineTo(cx + f[0] * CELL * 0.4 - f[1] * CELL * 0.4, cy + f[1] * CELL * 0.4 + f[0] * CELL * 0.4);
    g.lineTo(cx + f[0] * CELL * 0.4 + f[1] * CELL * 0.4, cy + f[1] * CELL * 0.4 - f[0] * CELL * 0.4);
    g.closePath(); g.fill();
  }
}

function drawVitals(e) {
  var s = e.state || {}, hp = s.hp == null ? 0 : s.hp;
  var explored = Math.round((s.explored || 0) * 100);
  document.getElementById("vitals").innerHTML =
    '<div class="vital"><span>hp</span><br><b>' + esc(hp) + '</b></div>' +
    '<div class="vital"><span>ammo</span><br><b>' + esc(s.ammo) + '</b></div>' +
    '<div class="vital"><span>pos</span><br><b>' + esc((s.pos || []).join(",")) +
      ' <small>' + esc(s.facing) + '</small></b></div>' +
    '<div class="vital"><span>seq</span><br><b>' + esc(s.seq) + '</b></div>' +
    '<div class="vital" style="flex:1;min-width:120px"><span>explored ' + explored + '%</span><br>' +
      '<div class="bar"><i style="width:' + explored + '%"></i></div></div>';
  document.getElementById("prompt").textContent = e.prompt || "(no prompt recorded)";
}

function addTurn(e) {
  var log = document.getElementById("log");
  if (turns === 0) log.innerHTML = "";
  turns++;

  var source = e.source || "";
  var heuristic = source.indexOf("heuristic") === 0;
  var repaired = source.indexOf("+repaired") >= 0;
  var tag = heuristic ? '<span class="tag heuristic">heuristic</span>'
          : repaired  ? '<span class="tag repaired">repaired</span>' : "";

  var when = new Date(e.t * 1000).toTimeString().slice(0, 8);
  var div = document.createElement("div");
  div.className = "turn" + (heuristic || repaired ? " off" : "");
  div.innerHTML =
    '<div class="time">' + when + '</div>' +
    '<div><span class="chip ' + family(e.directive) + '">' + esc(e.directive) + '</span></div>' +
    '<div class="why">' + esc(e.why) + tag + '</div>' +
    '<div class="sub">seq ' + esc(e.seq) + ' &middot; ' + e.elapsed.toFixed(2) + 's &middot; ' +
      esc(source) + ' &middot; ' + esc(e.addr) + '</div>';

  // Only follow the tail if the reader is already at it. Yanking the scroll
  // out from under someone reading back through the run is worse than a
  // dashboard that needs one scroll.
  var atBottom = log.scrollHeight - log.scrollTop - log.clientHeight < 40;
  log.appendChild(div);
  if (atBottom) log.scrollTop = log.scrollHeight;
}

function tick() {
  fetch("/api/state?after=" + after).then(function (r) { return r.json(); }).then(function (d) {
    for (var i = 0; i < d.entries.length; i++) addTurn(d.entries[i]);
    after = d.n;
    if (d.latest) latest = d.latest;

    if (latest) {
      drawMap(latest.state);
      drawVitals(latest);
      var age = d.now - latest.t;
      var st = latest.stats || {};
      document.getElementById("meta").innerHTML =
        '<b>' + esc(latest.state.id || "badge") + '</b> &middot; last beacon ' +
        age.toFixed(0) + 's ago &middot; ' + turns + ' turns &middot; ' +
        'clean <b>' + (st.clean || 0) + '</b> repaired <b>' + (st.repaired || 0) +
        '</b> failed <b>' + (st.failed || 0) + '</b> heuristic <b>' + (st.heuristic || 0) + '</b>';
      document.getElementById("stale").className = age > staleAfter ? "on" : "";
      document.getElementById("stale").textContent =
        "NO BEACON FOR " + age.toFixed(0) + "s";
    }
  }).catch(function () {
    // Relay gone. Say so rather than freezing on the last good frame.
    document.getElementById("stale").className = "on";
    document.getElementById("stale").textContent = "DASHBOARD UNREACHABLE";
  });
}

fetch("/api/world").then(function (r) { return r.json(); }).then(function (d) {
  world = d.world;
  staleAfter = d.stale_after;
  document.getElementById("worldsrc").textContent = "map: " + d.source;
  document.getElementById("sysprompt").textContent = d.system_prompt || "(not supplied)";
  drawMap(null);
  tick();
  setInterval(tick, 1000);
});
</script>
</body>
</html>
"""


# ------------------------------------------------------------------
# Standalone demo, so the page can be checked without a relay or a badge
# ------------------------------------------------------------------
def _demo(port):
    import random

    dash = Dashboard(port=port, system_prompt="(demo mode: no relay attached)")
    if not dash.start():
        return 1

    directives = ["EXPLORE_N", "EXPLORE_E", "HUNT", "RETREAT", "SEEK_ITEM", "HOLD"]
    sources = ["gpt-oss:20b", "gpt-oss:20b", "gpt-oss:20b+repaired", "heuristic"]
    state = {"id": "demo-badge", "seq": 0, "hp": 100, "ammo": 30, "pos": [4, 4],
             "facing": "E", "explored": 0.05, "enemies": [], "items": [],
             "walls": {"n": True, "s": False, "e": False, "w": True}, "recent": []}
    stats = {"clean": 0, "repaired": 0, "failed": 0, "heuristic": 0}

    print("demo beacons every 3s, ctrl-C to stop")
    try:
        while True:
            state["seq"] += 1
            state["hp"] = max(10, min(100, state["hp"] + random.randint(-9, 6)))
            state["ammo"] = max(0, state["ammo"] + random.randint(-3, 2))
            state["explored"] = round(min(1.0, state["explored"] + 0.01), 2)
            state["pos"] = [random.randint(1, 30), random.randint(1, 29)]
            state["facing"] = random.choice("NSEW")
            state["enemies"] = [{"dir": random.choice("NSEW"), "dist": random.randint(1, 9)}
                                for _ in range(random.choice([0, 1, 1, 2]))]
            state["items"] = [{"kind": random.choice(["medkit", "ammo"]),
                               "dir": random.choice("NSEW"), "dist": random.randint(2, 12)}
                              for _ in range(random.choice([0, 1]))]
            d = random.choice(directives)
            state["recent"] = (state["recent"] + [d])[-6:]
            src = random.choice(sources)
            stats["clean" if src == "gpt-oss:20b" else
                  "repaired" if "repaired" in src else "heuristic"] += 1

            prompt = ("hp=%s ammo=%s pos=%s facing=%s explored=%s%%\n"
                      "open directions: N, E\nenemies: %s\nyour last directives: %s"
                      % (state["hp"], state["ammo"], state["pos"], state["facing"],
                         int(state["explored"] * 100),
                         "none in view" if not state["enemies"] else
                         "; ".join("%s at %s tiles" % (e["dir"], e["dist"]) for e in state["enemies"]),
                         ", ".join(state["recent"][-4:])))

            dash.record(("192.168.1.60", 5116), dict(state), prompt, d,
                        "demo answer", src, random.uniform(1.5, 3.2), stats)
            time.sleep(3)
    except KeyboardInterrupt:
        print("")
    return 0


def main():
    p = argparse.ArgumentParser(description="Doomish dashboard")
    p.add_argument("--port", type=int, default=DEFAULT_DASHBOARD_PORT)
    p.add_argument("--demo", action="store_true",
                   help="serve fabricated turns, no relay needed")
    args = p.parse_args()

    if args.demo:
        return _demo(args.port)

    dash = Dashboard(port=args.port)
    if not dash.start():
        return 1
    print("serving an empty dashboard; run relay.py --dashboard for a real one")
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
