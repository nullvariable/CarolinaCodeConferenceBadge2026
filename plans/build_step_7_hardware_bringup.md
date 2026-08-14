# Build step 7: hardware bring-up

**Deliverable:** Doomish running on the real badge.

**Depends on:** steps 1-4 and 6. **Cannot start before Friday morning
2026-08-14**, when Doug gets the badge. The conference runs two days; his
session is Saturday 2026-08-15 in the afternoon.

That means there is roughly a full day with real hardware before the talk, not
the few hours the original handoff assumed. Use it on the REPL checks below
first. They are cheap and they are the ones that can invalidate work.

Read `plans/build_overview.md` first.

This step is a checklist, not a build. Everything before it was written blind
against a device that did not exist. Expect to find things. The order below is
deliberately "cheapest test that could invalidate the most work" first.

## Before touching Doomish

Run these at the REPL on a badge with stock firmware. Ten minutes here can save
rewriting the renderer.

1. **`help("modules")`** -- confirm `socketpool`, `wifi`, `bitmaptools`, and
   `fourwire` are all in the build. Note whether `espnow` is present. That is
   for a future badge-to-badge idea, not this project. Do not build it now.
2. **`import sys; sys.implementation`** -- float width. Doubles mean a heap
   allocation per float operation and a different performance story for the
   raycaster.
3. **Display orientation.** The single biggest untested assumption. Every sample
   in this repo runs `rotation=0` portrait; Doomish defaults to `ROTATION = 90`
   landscape, and `AGENTS.md` only documents landscape via the `busdisplay`
   route. Try `adafruit_st7735r.ST7735R(..., rotation=90)` with a matching
   160x128 bitmap and see if it renders correctly. If it does not, set
   `ROTATION = 0` and move on. Do not spend the day on it.
4. **A UDP broadcast round trip**, before the game is in the picture. Twenty
   lines: connect, socket, bind, `sendto` to `255.255.255.255:5115`,
   `recvfrom_into`. The relay's log confirms receipt from the other side. This
   is the architecture's single point of failure and it deserves an isolated
   test.
5. **Raw frame rate.** Fill a 160x128 bitmap with `bitmap.fill()` and
   `display.refresh()` in a tight loop, no game logic. That number is the
   ceiling everything else lives under. If refresh alone is under 10 FPS, go
   straight to `VIEW_MODE = 1`.

## Then Doomish

Copy `samples/Doomish/` to the drive and run it from the Launcher.

* Read the serial console (`screen /dev/ttyACM0 115200`). DTR must be asserted on
  the native ESP32-S3 USB; GUI terminals do it, raw pyserial needs `ser.dtr = True`.
  On Linux the user must be in `dialout`.
* Watch the frame-time line. Compare to the raw ceiling from check 5. The gap is
  what the game logic costs.
* **If the raycaster embarrasses, flip `VIEW_MODE` to 1.** That is the
  pre-agreed fallback and both loops are unchanged by it. Taking it is not a
  failure, it was designed in from the start.

## Known gotchas

* `samples/CCCLogo/code.py:37` loads `/img/CarolinaCodeConference.bmp` but the
  file in the repo is `img/CarolinaCodeConference Logo.bmp`. Rename on copy.
  Unrelated to Doomish but it will waste time if hit cold.
* The 8.6 MB of PNGs in `img/` are repo-only. The CIRCUITPY partition is ~2 MB.
  Do not copy them. Same for `sim/` and `relay/`.
* Data-capable USB-Micro cable. A charge-only cable presents no drive and looks
  exactly like a dead badge.
* `settings.toml` with `WIFI_SSID` / `WIFI_PASSWORD` must be at the drive root,
  not in the sample folder.

## The phone hotspot

The one piece of the architecture never tested end to end. Broadcast is proven
between two real devices on a home AP, but **hotspot client isolation is the
failure mode that would break the design**, and phones vary.

Test before relying on it:

1. Phone hotspot on 2.4 GHz. iPhone needs Maximize Compatibility ON; Android
   needs the band set to 2.4 GHz. The badge, the Pi 3 B, and the Pi Zero W are
   all 2.4 GHz only.
2. Pi joins the hotspot. Confirm with `iwgetid`.
3. `fake_badge.py` from a laptop on the same hotspot. Directives should come
   back.
4. If broadcast fails but unicast works, the hotspot is isolating clients. Set
   `RELAY_HOST` to the Pi's hotspot IP in `code.py`. That is the field repair and
   it costs one constant.

Worth doing tonight or Friday rather than Saturday morning, since the fix
requires knowing the Pi's IP on that network. The phone hotspot test needs no
badge at all: `fake_badge.py` from the laptop proves it, and it is the last
untested link in the chain.

## Do not

* Do not touch talk materials or the vault `Presentations/` tree.
* Do not push to the `circuitboardmedics` remote.
* Do not start the espnow badge-to-badge idea. Note what `help("modules")` says
  and stop.
