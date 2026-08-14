#!/usr/bin/env python3
"""Laptop stand-in for the badge, so the chain can be tested before hardware.

Broadcasts a plausible game state every few seconds, then polls its socket
non-blocking for the directive, exactly the way samples/Doomish/code.py will.
Prints round-trip latency so a slow model is obvious immediately.

    python3 fake_badge.py                    # broadcast, the real topology
    python3 fake_badge.py --host 192.168.1.5 # unicast at a known relay, for debugging

Standard library only, and the socket calls stay inside the subset CircuitPython
supports, so this file doubles as the reference for the badge-side networking.
"""

import argparse
import json
import os
import random
import socket
import sys
import time

PORT = int(os.environ.get("DOOMISH_PORT", "5115"))
BADGE_PORT = int(os.environ.get("DOOMISH_BADGE_PORT", "5116"))

DIRS = ("N", "E", "S", "W")
STEPS = {"N": (0, -1), "S": (0, 1), "E": (1, 0), "W": (-1, 0)}
ITEM_KINDS = ("medkit", "ammo", "keycard")
MAP_MAX = 31


def log(msg):
    sys.stdout.write("%s  %s\n" % (time.strftime("%H:%M:%S"), msg))
    sys.stdout.flush()


class FakeGame(object):
    """A drifting game state. Not a simulation, just something that changes."""

    def __init__(self):
        self.seq = 0
        self.hp = 100
        self.ammo = 30
        self.pos = [8, 8]
        self.facing = "N"
        self.explored = 0.05
        self.recent = []

    def step(self, directive):
        self.seq += 1

        if directive and directive.startswith("EXPLORE_"):
            self.facing = directive.split("_")[1]
            self.explored = min(1.0, self.explored + random.uniform(0.01, 0.05))
        elif directive == "RETREAT":
            self.hp = min(100, self.hp + random.randint(0, 12))
        elif directive == "SEEK_ITEM":
            self.ammo = min(60, self.ammo + random.randint(0, 15))
            self.hp = min(100, self.hp + random.randint(0, 10))

        if directive:
            self.recent.append(directive)
            self.recent = self.recent[-6:]

        # Walk, and turn away from the edge rather than stopping against it.
        # Clamping pinned it: facing only changes on an EXPLORE_*, so the first
        # HUNT after reaching row 0 walked it into the edge and every directive
        # until the next EXPLORE_ held it there. Nine identical beacons in a row
        # look like a wedged badge on the dashboard, which is the one thing the
        # fallback demo cannot afford to look like.
        for _ in range(4):
            dx, dy = STEPS[self.facing]
            nx, ny = self.pos[0] + dx, self.pos[1] + dy
            if 0 <= nx <= MAP_MAX and 0 <= ny <= MAP_MAX:
                break
            self.facing = random.choice([d for d in DIRS if d != self.facing])
        else:
            nx, ny = self.pos          # boxed in all four ways, stay put
        self.pos = [nx, ny]

        enemies = []
        for _ in range(random.choice([0, 0, 1, 1, 2])):
            enemies.append({"dir": random.choice(DIRS), "dist": random.randint(1, 12)})

        if enemies:
            self.hp = max(1, self.hp - random.randint(0, 9))
            self.ammo = max(0, self.ammo - random.randint(0, 4))

        items = []
        for _ in range(random.choice([0, 1, 1, 2])):
            items.append({
                "kind": random.choice(ITEM_KINDS),
                "dir": random.choice(DIRS),
                "dist": random.randint(2, 15),
            })

        walls = {d: random.random() < 0.4 for d in ("n", "s", "e", "w")}
        if all(walls.values()):
            walls[random.choice(list(walls))] = False

        return {
            "id": "fake-badge",
            "seq": self.seq,
            "hp": self.hp,
            "ammo": self.ammo,
            "pos": self.pos,
            "facing": self.facing,
            "explored": round(self.explored, 3),
            "enemies": enemies,
            "items": items,
            "walls": walls,
            "recent": self.recent,
        }


def main():
    p = argparse.ArgumentParser(description="Fake badge beacon")
    p.add_argument("--host", default="255.255.255.255", help="relay address (default: broadcast)")
    p.add_argument("--port", type=int, default=PORT)
    p.add_argument("--bind-port", type=int, default=BADGE_PORT)
    p.add_argument("--interval", type=float, default=5.0, help="seconds between beacons")
    p.add_argument("--count", type=int, default=0, help="stop after N beacons (0 = forever)")
    args = p.parse_args()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.bind(("0.0.0.0", args.bind_port))
    sock.settimeout(0)  # non-blocking, same as the badge's frame loop

    game = FakeGame()
    directive = None
    sent = 0
    answered = 0

    log("beaconing to %s:%d from udp/%d every %.1fs" % (args.host, args.port, args.bind_port, args.interval))

    try:
        while True:
            state = game.step(directive)
            payload = json.dumps(state).encode("utf-8")
            sock.sendto(payload, (args.host, args.port))
            sent += 1
            sent_at = time.time()
            log("-> seq=%d hp=%d ammo=%d enemies=%d (%d bytes)" % (
                state["seq"], state["hp"], state["ammo"], len(state["enemies"]), len(payload)
            ))

            # Poll the way the game loop will: never block, just check each pass.
            directive = None
            deadline = sent_at + args.interval
            while time.time() < deadline:
                try:
                    data, addr = sock.recvfrom(1024)
                except (BlockingIOError, socket.timeout, OSError):
                    time.sleep(0.02)
                    continue

                try:
                    reply = json.loads(data.decode("utf-8"))
                except (ValueError, UnicodeDecodeError):
                    log("<- garbage from %s:%d" % (addr[0], addr[1]))
                    continue

                # Accept slightly late answers. Directives change slowly, so one
                # aimed at the previous beacon is still worth acting on. Only
                # drop genuinely ancient ones.
                rseq = reply.get("seq")
                if rseq is not None and state["seq"] - rseq > 2:
                    log("<- stale seq=%s (now %s), ignoring" % (rseq, state["seq"]))
                    continue

                directive = reply.get("directive")
                answered += 1
                log("<- %s in %.2fs from %s  (%s)" % (
                    directive, time.time() - sent_at, addr[0], reply.get("why", "")
                ))
                break

            if directive is None:
                log("   no directive within %.1fs, reflex layer carries on" % args.interval)

            # Hold the cadence. On the badge these seconds are frames of gameplay.
            remaining = deadline - time.time()
            if remaining > 0:
                time.sleep(remaining)

            if args.count and sent >= args.count:
                break
    except KeyboardInterrupt:
        pass

    log("sent %d, answered %d" % (sent, answered))
    if sent and not answered:
        log("nothing came back. check: same hotspot? relay running? port %d open?" % args.port)


if __name__ == "__main__":
    main()
