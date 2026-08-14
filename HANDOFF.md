# HANDOFF — CCC 2026 badge projects

**For:** a fresh Claude session working in this repo
**From:** CoS session with Doug, 2026-08-13 evening
**Doug's context:** he speaks at Carolina Code Conference **this Saturday, Aug 15, 2pm** ("The Moat Was Made of YAML"). Talk prep happens in a DIFFERENT session and is off-limits here — do not touch anything under the vault `Presentations/` folder or suggest talk changes. He gets the physical badge **at the conference Saturday**; nothing can be tested on real hardware before then.

---

## What this repo is

Clone of `https://github.com/circuitboardmedics/CarolinaCodeConferenceBadge2026` — the badge's CIRCUITPY drive contents. The badge: **ESP32-S3-WROOM-1-N8** (8MB flash, **no PSRAM**, ~512KB RAM), 160×128 ST7735S LCD, 5 WS2812 NeoPixels (GPIO4), 3 buttons (GPIO1/2/43, active-low pull-up), WiFi **2.4GHz only**, CR123A or USB-Micro power, **CircuitPython 10.2.1 pre-flashed**. No sensors, no buzzer.

Read `AGENTS.md` in this repo before writing any badge code — it's a pin map + CircuitPython 10 patterns written specifically for AI agents (use `fourwire.FourWire`, NOT `displayio.FourWire`; drive font-chip CS GPIO9 HIGH or it fights the LCD on the shared SPI bus).

Deployment model: badge mounts as a USB drive; save = soft-reboot = running. The stock `code.py` Launcher auto-discovers any `/samples/<Name>/code.py` folder and adds it to its menu — that's how apps ship.

Known repo gotchas (verified 2026-08-13):
- `samples/CCCLogo/code.py:37` loads `/img/CarolinaCodeConference.bmp` but the file here is `img/CarolinaCodeConference Logo.bmp` — rename when copying to a badge.
- Serial console needs DTR asserted (native ESP32-S3 USB); GUI terminals do it, raw pyserial needs `ser.dtr = True`.
- Linux: user must be in `dialout` group.
- WiFi creds go in `settings.toml` as `WIFI_SSID`/`WIFI_PASSWORD` (deliberately NOT `CIRCUITPY_WIFI_*`, to avoid the web-workflow ~10s boot penalty).
- Data-capable USB-Micro cable required; badge storage partition is small (~2MB typical for N8 CIRCUITPY) — the 8.6MB `img/` PNGs in this clone are repo-only, don't copy them over.

---

## The project: "Doomish" — two-loop AI plays a Doom-like on the badge

Doug's idea, refined together. **Decisions already made — do not relitigate:**

1. **Real Doom is out.** No PSRAM kills every ESP32 Doom port, and we're staying on CircuitPython (keeps the drop-a-folder story). We build a Wolfenstein-style raycaster ("Build A"), not a streamed thin client.
2. **Two-brain architecture.** Reflex layer runs on-badge every frame (enemy in view → fire, low HP → retreat toward last medkit, dead end → turn). Strategy layer is an LLM that receives a compact game-state transcript every ~5s and returns ONE directive from a fixed vocabulary (EXPLORE_N/S/E/W, HUNT, RETREAT, SEEK_ITEM, HOLD) that biases pathfinding. Current directive gets drawn in the status bar so the "slow judgment / fast reflexes" split is visible.
3. **UDP, not HTTP, from the badge.** `adafruit_requests` is blocking and would freeze the game ~1s every cycle. Badge fire-and-forgets a state beacon to the **broadcast address** (solves discovery — no IPs configured anywhere); relay replies with the directive; badge polls its socket non-blocking each frame.
4. **LLM = Doug's Ollama CLOUD subscription** (not homelab ollama — the badge can't reach the tailnet). Relay constrains output with `format: json` against the directive vocabulary; a small model is fine and answers sub-second.
5. **Network topology: phone hotspot is the network.** Phone hotspot on 2.4GHz (iPhone "Maximize Compatibility" / Android 2.4GHz band). Badge and relay both join as ordinary clients. Conference WiFi and laptop AP-mode are NOT in the architecture — rejected after checking driver realities.
6. **Relay host = a Raspberry Pi Zero W on a power bank, as a hotspot CLIENT — never as an AP.** brcmfmac AP+STA concurrency is notoriously flaky; as a plain client the Zero W is bulletproof and the whole rig (badge + phone + Pi + battery) is pocket-sized and self-contained. If Doug finds a **Zero 2 W** in the drawer, prefer it (ARMv7 → current OS + modern Python; the ARMv6 Zero W works but fights on wheels/versions).
7. **Timeline: this is a NEXT-WEEK build.** Nothing here is for Saturday's stage. This week only the cheap prep below happens. Do not create pressure to finish before the conference.

### Work order

**Now / tonight (no badge needed):**
1. Write `relay/relay.py` — runs on the Pi: listens UDP broadcast port (pick one, e.g. 5115), parses badge state JSON, calls Ollama cloud with a system prompt + `format: json` schema returning `{"directive": "..."}`, sends reply UDP to the beacon's source addr. Log each exchange to stdout. Include `relay/README.md` with Pi setup (join hotspot, systemd unit or `nohup`, where the API key lives).
2. Write `relay/fake_badge.py` — laptop stand-in: sends a plausible fake game state every 5s, prints directives received. This proves the full chain (hotspot → Pi → Ollama cloud → back) before the badge exists.
3. Doug's own checklist (remind him, don't do it for him — it's physical):
   - Plug the actual Zero W into the actual power bank; confirm it's still up after 15 min (many banks auto-off below ~50-70mA; Zero W draws ~120mA — usually enough, but verify).
   - `curl` Ollama cloud with his API key from the Pi (his cloud auth broke once before, April 2026, in another tool — verify the subscription side independently).
   - Run `fake_badge.py` end-to-end over the phone hotspot.

**Next week (badge in hand):**
4. `samples/Doomish/code.py` — raycaster (~40 columns via `bitmaptools`, reduced internal res, expect 5-10 FPS = acceptable retro), tile map, 1-2 sprite enemy types, reflex rules, UDP beacon/poll, directive in status bar. Fallback pre-agreed: if raycaster FPS embarrasses, switch to top-down tile view — both loops unchanged.
5. On-badge REPL check: `help("modules")` — note whether `espnow` is in the build (future badge-to-badge idea, separate project, don't build it now).

### Related but separate (status: pitched, Doug has NOT green-lit)
- **"The Moat" sample app** — nameplate/marquee app for Saturday, written against AGENTS.md, README stating exactly how much was AI-written. ~1hr. **Ask Doug before building.**
- Blog/content: "vendor shipped AGENTS.md" post; later "I Put the Judgment Layer in Doom." Content only, not code.

---

## Guardrails

- **Never push to the `circuitboardmedics` remote.** If publishing is wanted later, fork under Doug's GitHub — with his explicit OK first.
- Don't touch talk materials, the vault `Presentations/` tree, or `~/CoS`.
- Ollama cloud API key: ask Doug where it lives; don't go hunting through credential files, and never echo it.
- Doug's writing voice if you draft READMEs/posts he'll publish: ellipses for pauses, never em dashes; no hedging filler.

## Open questions for Doug (ask at session start, one message)

1. Zero W or Zero 2 W — which is actually in the drawer and charged?
2. Where's the Ollama cloud API key, and which model does his plan include (pick smallest capable for sub-second directives)?
3. Green light on "The Moat" app for Saturday, or skip it?
