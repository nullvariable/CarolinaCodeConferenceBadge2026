# Doomish relay

The badge runs the reflexes. This runs the judgment.

Every ~5 seconds the badge fire-and-forgets a UDP broadcast describing what it
can see. This relay catches it, asks a model for one directive out of a fixed
vocabulary, and unicasts the answer back to whatever address the beacon came
from. Nothing has a hardcoded IP. Nothing on the badge ever blocks.

Two files, standard library only, no pip install:

* `relay.py` ... runs on the Pi
* `fake_badge.py` ... runs on the laptop, pretends to be the badge

## Quick start

Terminal one:

```sh
export OLLAMA_API_KEY='...'
python3 relay.py
```

Terminal two:

```sh
python3 fake_badge.py
```

You should see directives come back in under a second. To test the plumbing
without touching the model at all:

```sh
python3 relay.py --mock
```

Mock mode answers from a small heuristic instead of the LLM. Useful for
proving the network path when you do not yet trust the API key.

## Network topology

The phone hotspot is the network. Badge and Pi both join it as ordinary
clients. No AP mode anywhere, no conference WiFi.

* iPhone: Personal Hotspot, **Maximize Compatibility ON** (forces 2.4GHz)
* Android: hotspot settings, **band = 2.4GHz**

The badge is 2.4GHz only. So is the Pi 3 B and the Zero W. A 5GHz hotspot
means nothing associates and you will spend the whole time debugging the wrong
layer.

Discovery is solved by broadcast: the badge sends to `255.255.255.255:5115`,
the relay is bound to `0.0.0.0:5115` and hears it, then replies straight to the
source address. Neither side is configured with the other's IP.

Hotspots on some Android builds isolate clients from each other. If broadcast
goes nowhere, that is the first thing to check.

## Pi setup

Use the **Pi 3 B**. Current OS, modern Python, and it draws enough current that
a power bank will not decide nothing is plugged in and shut off. The Zero W
works but it is ARMv6, so you fight Python versions and wheels for no benefit
here... this script imports nothing outside the standard library either way.

1. Flash Raspberry Pi OS Lite, enable SSH.
2. Join the hotspot. Easiest is to put the credentials in before first boot via
   Imager's advanced options, so the Pi comes up already on the phone. Otherwise
   `sudo raspi-config` > System Options > Wireless LAN.
3. Copy this folder over:

   ```sh
   scp -r relay/ pi@raspberrypi.local:~/
   ```

4. Verify the model side independently, before involving any of this code:

   ```sh
   curl https://ollama.com/api/chat \
     -H "Authorization: Bearer $OLLAMA_API_KEY" \
     -d '{"model":"gpt-oss:20b","stream":false,
          "messages":[{"role":"user","content":"reply with the word ok"}]}'
   ```

   If that fails, the problem is the subscription or the key, not the relay.

### Keeping it running

Quick and dirty:

```sh
OLLAMA_API_KEY='...' nohup python3 relay.py > relay.log 2>&1 &
```

Or as a service, `/etc/systemd/system/doomish-relay.service`:

```ini
[Unit]
Description=Doomish relay
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/relay
Environment=OLLAMA_API_KEY=...
Environment=OLLAMA_MODEL=gpt-oss:20b
ExecStart=/usr/bin/python3 /home/pi/relay/relay.py
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

```sh
sudo systemctl enable --now doomish-relay
journalctl -u doomish-relay -f
```

The key lives in the environment and nowhere else. It is never logged, never
written to disk by this code, and never echoed back to the badge.

## Configuration

| Variable | Default | Notes |
|---|---|---|
| `OLLAMA_API_KEY` | none | required unless `--mock`. Without it every cycle falls back to the heuristic and says so. |
| `OLLAMA_MODEL` | `gpt-oss:20b` | measured best of the plan's models, see below. |
| `OLLAMA_URL` | `https://ollama.com/api/chat` | point at a local ollama instead if you ever want to. |
| `OLLAMA_TIMEOUT` | `4.0` | seconds. Shorter than the beacon interval on purpose. |
| `DOOMISH_PORT` | `5115` | relay listen port. |
| `DOOMISH_BADGE_PORT` | `5116` | badge listen port, `fake_badge.py` only. |

Flags override env: `--port --model --url --timeout --mock -v`.

## Model choice, measured

Benchmarked from the Pi against Ollama Cloud on 2026-08-13, on the real
directive prompt. Nine interleaved calls per model so all three saw the same
load conditions. The tail is what matters, not the mean... a directive that
arrives after the next beacon is a directive nobody used.

| model | mean | median | p90 | max | in-vocabulary |
|---|---|---|---|---|---|
| **gpt-oss:20b** | 2.41 s | 2.44 s | **2.87 s** | 3.87 s | 9/9 |
| minimax-m3 | 3.28 s | 3.05 s | 4.75 s | 5.25 s | 9/9 |
| glm-5.2 | 7.60 s | 3.54 s | 15.06 s | 21.33 s | 9/9 |

Also tested and rejected:

* `deepseek-v4-flash:0731` ... 3.13 s mean but a 6.92 s outlier in three calls.
* `nemotron-3-nano:30b` ... 8.12 s mean.
* `gemma4:31b` ... 12.9 s **and** it ignores the schema entirely, returning an
  object with no `directive` key at all. 0/3 usable.

`minimax-m3` is the backup. It cost about a second more but got the low-health
judgment right every time, where `gpt-oss:20b` missed it once in four.

Two things the benchmark settled that the original design got wrong:

**Directives take 2 to 4 seconds, not sub-second.** Everything downstream has
to tolerate that. The relay's timeout is 8 s for this reason, and the badge
accepts an answer aimed at the previous beacon rather than only the current one.

**`format` does not enforce `enum`.** Ollama honours the JSON *type* but will
still answer `{"directive": "S"}` or `{"directive": "shoot N"}` against a schema
that lists eight legal values. With the full system prompt (which spells the
vocabulary out) every model tested answered in-vocabulary, but the schema alone
is not a guarantee. `normalize()` in `relay.py` repairs near-misses and the log
tags them `+repaired`, so you can watch how often it happens. Anything
unrepairable falls through to the heuristic.

## Protocol

Badge to relay, UDP broadcast to port 5115, roughly 250 to 350 bytes:

```json
{
  "id": "badge-01",
  "seq": 42,
  "hp": 63,
  "ammo": 12,
  "pos": [12, 7],
  "facing": "N",
  "explored": 0.35,
  "enemies": [{"dir": "N", "dist": 4}],
  "items":   [{"kind": "medkit", "dir": "E", "dist": 6}],
  "walls":   {"n": false, "s": true, "e": true, "w": false},
  "recent":  ["EXPLORE_N", "HUNT"]
}
```

Relay to badge, UDP unicast to the beacon's source port:

```json
{"directive": "HUNT", "seq": 42, "why": "enemy known and healthy"}
```

`seq` echoes back so the badge can throw away a late answer to an old question.
`why` is for the log and the status bar, the badge is free to ignore it.

Directive vocabulary, closed set:

```
EXPLORE_N  EXPLORE_S  EXPLORE_E  EXPLORE_W
HUNT  RETREAT  SEEK_ITEM  HOLD
```

The model is constrained to this set with a JSON schema in the `format` field,
and the answer is validated against the set again on arrival. Anything else,
or any transport failure, falls through to the heuristic. The badge always gets
an answer, so the game never stalls waiting on the cloud.

### Badge side

`fake_badge.py` is the reference implementation of the badge's networking. It
binds a socket, sets `settimeout(0)`, sends, then polls `recvfrom` once per pass
and moves on if nothing is there. That is the whole pattern, and it stays inside
what CircuitPython's `socketpool` supports. On the badge those polls happen once
per frame instead of in a sleep loop.

Nothing blocking. `adafruit_requests` would freeze the render loop for about a
second every cycle, which is why this is UDP and not HTTP.

## Troubleshooting

**`fake_badge.py` says "nothing came back"**
Is the relay actually running, on the same hotspot, and is anything firewalling
udp/5115. Try `--host <relay ip>` to take broadcast out of the picture. If
unicast works and broadcast does not, the hotspot is doing client isolation.

**Directives arrive but always say "heuristic" in the relay log**
`OLLAMA_API_KEY` is unset in the environment that actually launched the relay,
or the call is failing. The failure reason is logged on the line above.

**Answers take longer than the beacon interval**
Pick a smaller model. The relay already drops a queued beacon when a newer one
arrives, so the badge acts on current information rather than a backlog, but a
model that cannot answer inside 5 seconds makes the whole idea feel dead.

**Two badges**
Already handled. State is tracked per source address, replies go back to the
sender.
