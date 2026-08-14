# Doomish relay

The badge runs the reflexes. This runs the judgment.

Every ~5 seconds the badge fire-and-forgets a UDP broadcast describing what it
can see. This relay catches it, asks a model for one directive out of a fixed
vocabulary, and unicasts the answer back to whatever address the beacon came
from. Nothing has a hardcoded IP. Nothing on the badge ever blocks.

Three files, standard library only, no pip install:

* `relay.py` ... runs on the Pi
* `fake_badge.py` ... runs on the laptop, pretends to be the badge
* `dashboard.py` ... optional web view of both halves, off unless asked for

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

Add `--dashboard` to the `ExecStart` line if you want the web view up whenever
the relay is.

## The dashboard

```sh
python3 relay.py --dashboard          # then http://<pi-ip>:8080/
```

Off by default. The directive path is the product and the demo path stays
minimal without it.

Two panels. On the left, the badge's world: the maze, where the badge thinks it
is, which way it is facing, and every contact it reported. Under that, the exact
prompt text the model was handed, verbatim from `describe()`, with the system
prompt folded away below it. On the right, the turns, newest at the bottom.

The prompt half is the one that earns its keep. When a directive looks stupid it
is usually a fair answer to a bad question, and this is where you see the
question.

Reading it:

* Directive chips are coloured by family. Explore blue, hunt red, retreat amber,
  seek-item green, hold grey. From across a table the colour pattern alone tells
  you whether the model is thinking or stuck in a rut.
* An amber-outlined row means the model was not really steering. A solid
  `heuristic` tag is the fallback answering because the API failed or the key is
  missing. A dashed `repaired` tag means the model answered off-vocabulary and
  `normalize()` rescued it. Both are worth noticing... a screen full of them is
  a demo that only looks like it is working.
* The header counts clean, repaired, failed and heuristic for the run.
* Green and red ticks around the badge are the four `walls` flags, drawn exactly
  as the model is told them. If they disagree with the maze underneath, the
  badge and the dashboard have different ideas about where it is.
* Contacts sit on their compass axis at the reported distance, because bearing
  and distance is the only fix the beacon carries. An enemy at `E 4.2` may be a
  tile off to one side. It is not a position, it is what the model was told.

The map is not in the beacon... 32 rows of walls every five seconds would blow
the packet budget for something that never changes. `dashboard.py` keeps its own
copy, and reads `WORLD` straight out of `samples/Doomish/code.py` when the repo
is next to it, so the header says which. On the Pi only `relay/` gets copied
across, so the built-in copy is what runs there. If the maze is ever edited,
paste it into `WORLD_FALLBACK` too.

Two things that look like bugs and are not. `fake_badge.py` walks wherever it
likes and makes its wall flags up, so the fake badge strolls through walls and
the ticks contradict the maze; the real badge does neither. And `explored` is a
percentage on the wire, not a set of tiles, so the map cannot fog... the bar
under the vitals is the whole story there.

To see the page without a relay or a badge:

```sh
python3 dashboard.py --demo
```

It cannot slow the relay down. Measured on this laptop, six clients hammering
the page served 9,892 requests in five seconds while the beacon-to-directive
round trip went from 0.61 ms to 0.93 ms, against a directive that takes two to
four seconds. Serving happens on its own threads, the ring buffer is fifty
entries behind a lock held for microseconds, and the page asks only for turns it
has not seen yet. Delete `dashboard.py` and the relay still starts, logs one
line about it, and runs.

## Configuration

| Variable | Default | Notes |
|---|---|---|
| `OLLAMA_API_KEY` | none | required unless `--mock`. Without it every cycle falls back to the heuristic and says so. |
| `OLLAMA_MODEL` | `gpt-oss:20b` | measured best of the plan's models, see below. |
| `OLLAMA_URL` | `https://ollama.com/api/chat` | point at a local ollama instead if you ever want to. |
| `OLLAMA_TIMEOUT` | `8.0` | seconds. Sits above the measured p90, see below. |
| `DOOMISH_PORT` | `5115` | relay listen port. |
| `DOOMISH_BADGE_PORT` | `5116` | badge listen port, `fake_badge.py` only. |
| `DOOMISH_DASHBOARD` | unset | `1` turns the web view on, same as `--dashboard`. |
| `DOOMISH_DASHBOARD_PORT` | `8080` | bound to `0.0.0.0`, so the laptop and the phone can both reach it. |

Flags override env: `--port --model --url --timeout --mock --dashboard
--dashboard-port -v`.

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

## The conference hotspot

The Pi has three wifi profiles. Home is the lowest, so the Pi comes back to
it on its own whenever the other two are absent and remote access is never
lost:

| profile | priority | notes |
|---|---|---|
| `Pixel_6469` | 30 | the phone hotspot. Preferred, and normally off |
| `Flywheel` | 25 | the venue network. WPA2-PSK, untested |
| `netplan-wlan0-conezone` | 20 | home network, 192.168.1.54 |

**The badge follows one network and it will not tell you it disagreed.**
`settings.toml` holds a single `WIFI_SSID`/`WIFI_PASSWORD` pair, currently the
hotspot. At the venue with the hotspot off, the Pi joins `Flywheel` on its own
and the badge does not -- it keeps playing perfectly, on reflexes and its own
navigation, with the directive strip reading `LOCAL` and no LLM in the loop.
That is the whole point of the talk quietly missing, and nothing on screen
says "wrong network".

So pick the network deliberately and change both ends together:

* **hotspot** -- turn it on, `sudo nmcli connection up Pixel_6469`, badge
  already configured. Costs cellular data, known to work end to end.
* **Flywheel** -- `sudo nmcli connection up Flywheel`, then edit
  `settings.toml` on the CIRCUITPY drive and let the badge reboot. Saves data,
  unproven.

If that swap sounds too fiddly for the day, the alternative is giving the
badge a short list of networks to try in `net_connect()`. It is a contained
change and it wants its own test pass, so decide before Saturday rather than
during it.

Power save is pinned off on all three profiles rather than left to inherit the
global default in `/etc/NetworkManager/conf.d/wifi-powersave.conf`, because
the default wakes only on DTIM and that cost 65-110 ms per packet before it
was turned off.

**Priority does not make the Pi hop networks while it is connected.**
NetworkManager uses `autoconnect-priority` to choose *which profile to
activate* -- at boot, or after the current connection drops. There is no
roam-to-a-better-network behaviour between profiles. So turning the hotspot
on while the Pi is happily on home wifi changes nothing on its own. To move
it across mid-session:

```sh
sudo nmcli connection up Pixel_6469
```

It comes back to home by itself when the hotspot disappears, because home is
then the only candidate. The priority ordering is what matters at the venue,
where home is absent anyway, and on any reboot with both in range.

The hotspot profile was created with `nmcli connection add`, not
`nmcli device wifi connect`. The latter associates immediately, which drops
the SSH session you are typing into if you are on the home network at the
time. Adding the profile changes nothing until the hotspot is the only network
in range.

To find the Pi once it is on the hotspot, in order of speed: the phone's
connected-devices list, `ping doomish-relay.local` (avahi is running and
advertising that name), or `nmap -sn` across the hotspot subnet. Android
hotspots are usually `192.168.x.0/24`, iPhone `172.20.10.0/24`.

**Write the hotspot IP down when you have it.** It is the value for
`RELAY_HOST` in `samples/Doomish/code.py` if the hotspot turns out to isolate
its clients.

### Adding another network

`Flywheel` is already added, from the credentials saved on the phone. These
are the commands if the venue turns out to have a different or second SSID.

Ordinary WPA2 with a shared password:

```sh
sudo nmcli connection add type wifi con-name "<SSID>" ifname wlan0 ssid "<SSID>" \
  wifi-sec.key-mgmt wpa-psk wifi-sec.psk "<PASSWORD>" \
  connection.autoconnect yes connection.autoconnect-priority 25 \
  802-11-wireless.powersave 2
```

WPA2-Enterprise, if it asks for a username as well as a password. This Pi
supports it -- `wpa_supplicant` has PEAP, TTLS and LEAP compiled in:

```sh
sudo nmcli connection add type wifi con-name "<SSID>" ifname wlan0 ssid "<SSID>" \
  wifi-sec.key-mgmt wpa-eap 802-1x.eap peap 802-1x.phase2-auth mschapv2 \
  802-1x.identity "<USER>" 802-1x.password "<PASSWORD>" \
  connection.autoconnect yes connection.autoconnect-priority 25 \
  802-11-wireless.powersave 2
```

Use `nmcli connection add`, not `nmcli device wifi connect`: the latter
associates immediately, which drops the SSH session you are typing into.
Then `sudo nmcli connection up "<SSID>"` when you actually want to move.

Three things to check before trusting `Flywheel`, none of which can be
checked from here:

**Captive portal.** The killer. `nmcli networking connectivity` reports
`portal` instead of `full` when one is in the way. The relay cannot click
through a splash page, so Ollama calls fail and every directive falls back to
the heuristic. Worse, the badge has no browser at all -- there is no version
of this where a captive portal works. If you see `portal`, stop and use the
hotspot.

**2.4 GHz.** This Pi's radio is 2412-2484 MHz and nothing else. A 5 GHz-only
SSID will not even appear in `nmcli device wifi list`.

**Client isolation.** Conference networks isolate clients far more often than
phones do. Run the broadcast test from the checklist above. If broadcast fails
and unicast works, set `RELAY_HOST` in `samples/Doomish/code.py` to the Pi's
address on that network.

To back it out: `sudo nmcli connection delete "<SSID>"`. The hotspot and home
profiles are untouched by any of this.

### Still to test on the hotspot

None of this has been run yet -- the profile is configured, nothing more. The
phone hotspot must be on 2.4 GHz or nothing associates: the badge, the Pi 3 B
and the Pi Zero W are all 2.4 GHz only.

1. Pi associates, `doomish-relay` comes up on its own, `nmcli -t -f NAME
   connection show --active` names the hotspot.
2. **Broadcast.** `fake_badge.py --count 4 --interval 6` from a second device
   on the same hotspot. Run it from Windows, not WSL: WSL2 is NAT'd onto its
   own subnet and its broadcast never reaches the LAN.
3. **Unicast**, to interpret a broadcast failure. Broadcast fails and unicast
   works means client isolation, and the fix is one constant: `RELAY_HOST`.
4. **Ollama over cellular.** Every latency number in this file came from home
   broadband. Re-run `bench_models.py gpt-oss:20b` from the Pi on the hotspot
   and compare against mean 2.41 s, p90 2.87 s, max 3.87 s. If cellular pushes
   p90 past ~6 s, raise the beacon interval and the Ollama timeout rather than
   switching to a smaller model -- `gpt-oss:20b` is already the smallest.
5. **Ten minutes of beaconing without a dropout.** Phones sleep their hotspot
   aggressively when they think nothing is using it, and a 5 second beacon may
   not be enough to keep it awake. Plugged in with the screen on is the fix.
6. **Turn the hotspot off and confirm the Pi returns to the home network on
   its own.** Do this explicitly. Losing remote access to the Pi is the worst
   outcome of the whole exercise and it is entirely preventable.


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
