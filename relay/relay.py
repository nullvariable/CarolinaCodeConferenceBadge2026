#!/usr/bin/env python3
"""Doomish relay: badge state in over UDP, LLM directive back out.

Runs on the Pi (or any laptop) as an ordinary client of the phone hotspot.
Listens for broadcast state beacons from the badge, asks Ollama Cloud for one
directive from a fixed vocabulary, and unicasts the answer back to whatever
address the beacon came from. No IPs are configured anywhere.

Standard library only, so it runs on whatever Python the host happens to have.

    OLLAMA_API_KEY=... python3 relay.py
    python3 relay.py --mock          # no LLM, heuristic directives only
"""

import argparse
import json
import os
import socket
import sys
import threading
import time
import urllib.error
import urllib.request

DIRECTIVES = (
    "EXPLORE_N",
    "EXPLORE_S",
    "EXPLORE_E",
    "EXPLORE_W",
    "HUNT",
    "RETREAT",
    "SEEK_ITEM",
    "HOLD",
)

DEFAULT_PORT = int(os.environ.get("DOOMISH_PORT", "5115"))
DEFAULT_MODEL = os.environ.get("OLLAMA_MODEL", "gpt-oss:20b")
DEFAULT_URL = os.environ.get("OLLAMA_URL", "https://ollama.com/api/chat")
# Measured 2026-08-13 against Ollama Cloud from the Pi, interleaved 9-call runs:
# gpt-oss:20b mean 2.41s / p90 2.87s / max 3.87s. A 4s timeout sat right on that
# max and would have thrown away good answers. 8s costs nothing: a slow answer
# still beats no answer, and a newer beacon supersedes a queued one anyway.
DEFAULT_TIMEOUT = float(os.environ.get("OLLAMA_TIMEOUT", "8.0"))

SYSTEM_PROMPT = """You are the strategy layer for a badge-sized Doom-like game.

A reflex layer already handles moment-to-moment combat: it fires at anything in
view, backs off at low health, and turns at dead ends. You do not control any of
that. Your only job is to bias where the player goes next, at roughly one
decision every five seconds.

Reply with exactly one directive from this vocabulary:

  EXPLORE_N / EXPLORE_S / EXPLORE_E / EXPLORE_W
      push into unexplored map in that compass direction
  HUNT       close on the nearest known enemy
  RETREAT    disengage, fall back toward the last known medkit
  SEEK_ITEM  detour to the nearest item (health, ammo, key)
  HOLD       stay put and let the reflex layer work the current fight

Judgment, not reflex. Prefer HOLD or HUNT when a fight is already live. Prefer
SEEK_ITEM when health or ammo is low and the fight can wait. Prefer an EXPLORE_*
direction that is actually open, per the walls field. Avoid repeating the same
EXPLORE_* direction more than twice in a row when the map stops opening up.

Answer as JSON: {"directive": "...", "why": "<8 words max>"}"""

FORMAT_SCHEMA = {
    "type": "object",
    "properties": {
        "directive": {"type": "string", "enum": list(DIRECTIVES)},
        "why": {"type": "string"},
    },
    "required": ["directive"],
}

# Ollama's structured output honours the "type" but NOT the "enum": gpt-oss:20b
# will happily answer {"directive": "S"} or {"directive": "shoot N"} against the
# schema above. Verified 2026-08-13. So the schema is a hint, not a guarantee,
# and every answer gets repaired and re-validated here before it goes anywhere.
_COMPASS = {
    "N": "N", "NORTH": "N", "S": "S", "SOUTH": "S",
    "E": "E", "EAST": "E", "W": "W", "WEST": "W",
}
_SYNONYMS = (
    ("SEEK_ITEM", ("MEDKIT", "HEAL", "HEALTH", "AMMO", "ITEM", "PICKUP", "KEYCARD")),
    ("RETREAT", ("RETREAT", "FLEE", "ESCAPE", "WITHDRAW", "FALLBACK", "FALL_BACK")),
    ("HUNT", ("HUNT", "SHOOT", "ATTACK", "FIRE", "KILL", "ENGAGE", "CHASE")),
    ("HOLD", ("HOLD", "WAIT", "STAY", "IDLE", "STAND")),
)


def normalize(raw):
    """Repair a near-miss model answer onto the vocabulary. None if hopeless."""
    if not raw:
        return None
    s = str(raw).strip().upper().replace("-", "_").replace(" ", "_")
    if s in DIRECTIVES:
        return s

    # A bare compass token means "go that way".
    if s in _COMPASS:
        return "EXPLORE_" + _COMPASS[s]

    words = [w for w in s.split("_") if w]

    # Verb-ish answers: "SHOOT_N", "GO_NORTH", "MOVE_EAST", "FLEE".
    for canonical, needles in _SYNONYMS:
        for needle in needles:
            if needle in words:
                return canonical

    if "EXPLORE" in words or "MOVE" in words or "GO" in words or "HEAD" in words:
        for w in words:
            if w in _COMPASS:
                return "EXPLORE_" + _COMPASS[w]
    return None


def log(msg):
    sys.stdout.write("%s  %s\n" % (time.strftime("%H:%M:%S"), msg))
    sys.stdout.flush()


def describe(state):
    """Flatten a badge state dict into a few lines of prompt text."""
    lines = []
    lines.append("hp=%s ammo=%s pos=%s facing=%s explored=%s%%" % (
        state.get("hp", "?"),
        state.get("ammo", "?"),
        state.get("pos", "?"),
        state.get("facing", "?"),
        int(float(state.get("explored", 0)) * 100),
    ))

    walls = state.get("walls") or {}
    if walls:
        openings = [d.upper() for d in ("n", "s", "e", "w") if not walls.get(d)]
        lines.append("open directions: %s" % (", ".join(openings) or "none"))

    enemies = state.get("enemies") or []
    if enemies:
        lines.append("enemies: " + "; ".join(
            "%s at %s tiles" % (e.get("dir", "?"), e.get("dist", "?"))
            for e in enemies[:4]
        ))
    else:
        lines.append("enemies: none in view")

    items = state.get("items") or []
    if items:
        lines.append("items: " + "; ".join(
            "%s %s at %s tiles" % (i.get("kind", "?"), i.get("dir", "?"), i.get("dist", "?"))
            for i in items[:4]
        ))

    recent = state.get("recent") or []
    if recent:
        lines.append("your last directives: " + ", ".join(recent[-4:]))

    return "\n".join(lines)


def heuristic(state):
    """Cheap fallback so the badge always gets an answer, even offline."""
    hp = float(state.get("hp", 100))
    ammo = float(state.get("ammo", 0))
    enemies = state.get("enemies") or []
    items = state.get("items") or []
    walls = state.get("walls") or {}

    nearest = min((float(e.get("dist", 99)) for e in enemies), default=99)

    if enemies and hp < 35:
        return "RETREAT", "low hp with contact"
    if ammo <= 0 and items:
        return "SEEK_ITEM", "out of ammo"
    if hp < 50 and any(i.get("kind") == "medkit" for i in items):
        return "SEEK_ITEM", "medkit in reach"
    if nearest <= 3:
        return "HOLD", "fight already live"
    if enemies:
        return "HUNT", "enemy known and healthy"

    recent = state.get("recent") or []
    for d in ("n", "e", "s", "w"):
        if not walls.get(d):
            candidate = "EXPLORE_" + d.upper()
            if recent[-2:] != [candidate, candidate]:
                return candidate, "open corridor"
    return "HOLD", "boxed in"


def ask_ollama(state, url, model, api_key, timeout):
    """Return (directive, why). Raises on transport or parse failure."""
    # No num_predict cap. gpt-oss emits "thinking" tokens before "content", so a
    # small budget gets spent reasoning and returns an EMPTY content string that
    # fails to parse. Verified 2026-08-13: cap of 80 produced empty content every
    # single call. Let it run; the socket timeout is the real guard.
    payload = {
        "model": model,
        "stream": False,
        "format": FORMAT_SCHEMA,
        "options": {"temperature": 0.3},
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": describe(state)},
        ],
    }

    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + api_key,
        },
        method="POST",
    )

    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = json.loads(resp.read().decode("utf-8"))

    content = (body.get("message") or {}).get("content", "")
    if not content.strip():
        raise ValueError("model returned empty content (all budget spent thinking?)")

    parsed = json.loads(content)
    raw = parsed.get("directive", "")
    directive = normalize(raw)
    if directive is None:
        raise ValueError("unrepairable directive %r" % (raw,))

    repaired = directive != str(raw).strip().upper()
    return directive, parsed.get("why", ""), repaired


class Relay(object):
    def __init__(self, args):
        self.args = args
        self.api_key = os.environ.get("OLLAMA_API_KEY", "")
        self.sock = None
        self.dashboard = None
        self.pending = {}
        self.cv = threading.Condition()
        self.running = True
        # clean = model answered in-vocabulary; repaired = answered off-vocabulary
        # and normalize() rescued it; failed = fell through to the heuristic.
        self.stats = {"clean": 0, "repaired": 0, "failed": 0, "heuristic": 0}

    def start(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        self.sock.bind(("0.0.0.0", self.args.port))

        # The dashboard is an observer and an optional one. A missing file, a
        # syntax error in it, or a port already in use must all cost the relay
        # nothing: the directive path is the product.
        if self.args.dashboard:
            try:
                import dashboard as dashboard_mod

                dash = dashboard_mod.Dashboard(
                    port=self.args.dashboard_port,
                    system_prompt=SYSTEM_PROMPT,
                    log=log,
                )
                if dash.start():
                    self.dashboard = dash
            except Exception as exc:
                log("dashboard unavailable (%s: %s), continuing without it"
                    % (type(exc).__name__, exc))

        mode = "mock" if self.args.mock else "%s via %s" % (self.args.model, self.args.url)
        log("listening on udp/%d, strategy = %s" % (self.args.port, mode))
        if not self.args.mock and not self.api_key:
            log("WARNING: OLLAMA_API_KEY unset, every cycle will fall back to heuristic")

        worker = threading.Thread(target=self.worker_loop)
        worker.daemon = True
        worker.start()
        self.recv_loop()

    def recv_loop(self):
        while self.running:
            try:
                data, addr = self.sock.recvfrom(4096)
            except OSError as exc:
                log("socket error: %s" % exc)
                continue

            try:
                state = json.loads(data.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                log("dropped %d bytes of non-JSON from %s:%d" % (len(data), addr[0], addr[1]))
                continue

            if self.args.verbose:
                log("<- %s:%d seq=%s %s" % (addr[0], addr[1], state.get("seq"), describe(state).replace("\n", " | ")))

            with self.cv:
                # Keep only the newest state per badge. A beacon that arrives
                # while inference is running supersedes the one queued behind it.
                superseded = addr in self.pending
                self.pending[addr] = state
                self.cv.notify()
            if superseded:
                log("   (superseded a queued beacon from %s:%d)" % (addr[0], addr[1]))

    def worker_loop(self):
        while self.running:
            with self.cv:
                while not self.pending:
                    self.cv.wait()
                addr, state = self.pending.popitem()

            started = time.time()
            source = "heuristic"
            if self.args.mock or not self.api_key:
                directive, why = heuristic(state)
                self.stats["heuristic"] += 1
            else:
                try:
                    directive, why, repaired = ask_ollama(
                        state, self.args.url, self.args.model, self.api_key, self.args.timeout
                    )
                    source = self.args.model
                    if repaired:
                        source += "+repaired"
                        self.stats["repaired"] += 1
                    else:
                        self.stats["clean"] += 1
                except urllib.error.HTTPError as exc:
                    detail = exc.read()[:200].decode("utf-8", "replace")
                    log("ollama HTTP %s: %s" % (exc.code, detail))
                    directive, why = heuristic(state)
                    self.stats["failed"] += 1
                except Exception as exc:
                    log("ollama failed (%s: %s)" % (type(exc).__name__, exc))
                    directive, why = heuristic(state)
                    self.stats["failed"] += 1

            elapsed = time.time() - started
            reply = json.dumps({
                "directive": directive,
                "seq": state.get("seq"),
                "why": why,
            }).encode("utf-8")

            try:
                self.sock.sendto(reply, addr)
            except OSError as exc:
                log("reply to %s:%d failed: %s" % (addr[0], addr[1], exc))
                continue

            log("-> %s:%d seq=%s %s (%.2fs, %s) %s" % (
                addr[0], addr[1], state.get("seq"), directive, elapsed, source, why
            ))

            if self.dashboard is not None:
                # describe() is pure, so recomputing it here yields the exact
                # text ask_ollama sent -- which is the point of showing it.
                self.dashboard.record(
                    addr, state, describe(state), directive, why, source,
                    elapsed, self.stats,
                )

            total = sum(self.stats.values())
            if total and total % 20 == 0:
                log("   stats after %d: %s" % (total, self.stats))


def main():
    p = argparse.ArgumentParser(description="Doomish UDP relay")
    p.add_argument("--port", type=int, default=DEFAULT_PORT)
    p.add_argument("--model", default=DEFAULT_MODEL)
    p.add_argument("--url", default=DEFAULT_URL)
    p.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    p.add_argument("--mock", action="store_true", help="skip the LLM, use heuristics only")
    p.add_argument("--dashboard", action="store_true",
                   default=os.environ.get("DOOMISH_DASHBOARD") == "1",
                   help="serve the web dashboard (or set DOOMISH_DASHBOARD=1)")
    p.add_argument("--dashboard-port", type=int,
                   default=int(os.environ.get("DOOMISH_DASHBOARD_PORT", "8080")))
    p.add_argument("-v", "--verbose", action="store_true", help="log every inbound state")
    args = p.parse_args()

    relay = Relay(args)
    try:
        relay.start()
    except KeyboardInterrupt:
        log("stopping")


if __name__ == "__main__":
    main()
