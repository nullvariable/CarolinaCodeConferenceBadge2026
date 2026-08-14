# Build step 0: phone hotspot validation

**Deliverable:** proof that the conference network topology works, using a
phone, the Pi, and a laptop. No badge required.

**Depends on:** nothing. **Blocks:** nothing, but it de-risks everything.
**Do this tonight.**

Read `plans/build_overview.md` first.

## Why this is step 0

Every other piece of the chain is proven. Badge state to relay to Ollama and
back has been measured end to end on the home network. The one link never
tested is the actual venue topology: **phone hotspot as the network, with the
Pi and the badge both joined as ordinary clients.**

Two things can only fail here, and both are fatal to the design:

1. **Hotspot client isolation.** Many phones, especially some Android builds,
   prevent clients from talking to each other. Broadcast is the first casualty.
   Discovery depends on it entirely.
2. **Ollama Cloud over cellular.** Every latency number so far came from home
   broadband. At the venue the Pi reaches `ollama.com` through the phone's
   cellular data. The `gpt-oss:20b` p90 of 2.87 s is a home-broadband figure and
   it is not obviously transferable.

Neither needs the badge. Both are cheap to check tonight and expensive to
discover Saturday.

## Setup

Phone hotspot on **2.4 GHz**. iPhone: Personal Hotspot with **Maximize
Compatibility ON**. Android: hotspot settings, **band = 2.4 GHz**. The badge,
the Pi 3 B, and the Pi Zero W are all 2.4 GHz only, and a 5 GHz-only hotspot
means nothing associates.

### Getting the Pi onto the hotspot

The Pi currently has one wifi profile, `netplan-wlan0-conezone`, for the home
network. Add the hotspot as a **second** profile rather than replacing it, so
the Pi comes back on its own when the hotspot is off. Do not delete the home
profile: it is the only way back in without a keyboard and monitor.

Run this on the Pi so the password is typed rather than pasted into a
transcript:

```sh
sudo nmcli device wifi connect "<HOTSPOT-SSID>" password "<PASSWORD>" ifname wlan0
sudo nmcli connection modify "<HOTSPOT-SSID>" connection.autoconnect-priority 10
sudo nmcli connection modify netplan-wlan0-conezone connection.autoconnect-priority 20
```

Higher priority wins, so the home network stays preferred and the Pi only falls
to the hotspot when home wifi is absent. Confirm both profiles survive with
`nmcli connection show`.

Wifi power save is already disabled globally via
`/etc/NetworkManager/conf.d/wifi-powersave.conf`, so it applies to the new
profile too. Verify anyway: `/usr/sbin/iwconfig wlan0 | grep -i power`.

### Finding the Pi on the hotspot

Its home-network IP (192.168.1.54) will not apply. Options, in order of speed:

* the phone's connected-devices list
* `ping doomish-relay.local` from the laptop (avahi is running and advertising)
* `nmap -sn <subnet>.0/24`, typically `172.20.10.0/24` on iPhone

**Write the hotspot IP down.** It is the value for `RELAY_HOST` if broadcast
turns out to be isolated.

## The tests

Laptop joins the same hotspot for all of these.

### 1. Basic reachability

```sh
ping -c 5 <pi-hotspot-ip>
ssh pi@<pi-hotspot-ip> 'systemctl is-active doomish-relay; iwgetid'
```

Expect the relay already running: it is enabled at boot. Confirm `iwgetid` shows
the hotspot SSID and not the home network.

### 2. Broadcast, the one that matters

Run from **Windows, not WSL**. WSL2 is NAT'd onto its own subnet and its
broadcast will not reach the LAN. Python is at `C:\Python312\python.exe`.

```sh
cp relay/fake_badge.py /mnt/c/temp/
powershell.exe -NoProfile -c "C:\Python312\python.exe C:\temp\fake_badge.py --count 4 --interval 6"
```

Directives coming back means broadcast crosses the hotspot and the architecture
holds as designed.

### 3. Unicast, to interpret a broadcast failure

```sh
powershell.exe -NoProfile -c "C:\Python312\python.exe C:\temp\fake_badge.py --host <pi-hotspot-ip> --count 3 --interval 5"
```

* broadcast works, unicast works ... ship it
* broadcast fails, unicast works ... **client isolation.** Set `RELAY_HOST` to
  the Pi's hotspot IP in the badge sample. One constant, no other change. This
  is why that escape hatch exists.
* both fail ... the Pi is not actually on the hotspot, or the relay is down.
  Recheck step 1 before concluding anything about the network.

### 4. Ollama over cellular

The real unknown. Re-run the benchmark from the Pi while it is on the hotspot:

```sh
ssh pi@<pi-hotspot-ip> 'cd ~/relay && set -a; . ./relay.env; set +a; \
    python3 bench_models.py gpt-oss:20b'
```

Compare against the home-broadband baseline in `relay/README.md`:
mean 2.41 s, p90 2.87 s, max 3.87 s.

If cellular pushes p90 past ~6 s, the honest options are, in order:

1. Raise `BEACON_SEC` so the badge asks less often and tolerates the wait. The
   directive is strategy, not reflex; 8 or 10 seconds between judgments is still
   a working demo.
2. Raise `OLLAMA_TIMEOUT` to match, since a slow answer still beats a heuristic
   fallback.
3. Accept more heuristic fallbacks and make sure the status bar shows honestly
   when that is happening.

Do not respond by switching to a smaller model. `gpt-oss:20b` is already the
smallest the plan exposes.

Note it is worth running this twice, once with the phone on wifi-assist/5G and
once on a deliberately weak signal, if that is easy. Conference cellular is
congested in ways home cellular is not.

### 5. Stability

Leave `fake_badge.py` beaconing for 10 minutes on the hotspot. Watch for
dropouts. Phones aggressively sleep their hotspot when they think nothing is
using it, and a 5-second beacon may not be enough to keep it awake. If the link
drops, that is worth knowing now, and the fix is keeping the phone screen on or
plugged in.

## Record the results

Add a short section to `relay/README.md` with what actually happened: broadcast
yes or no, the Pi's hotspot IP, and the cellular latency numbers. That file is
the thing anyone reads on Saturday when something is wrong.

## Verification

1. Pi joins the hotspot and keeps its home profile.
2. `doomish-relay` is active on the hotspot with no manual start.
3. Broadcast from a second device produces directives, **or** isolation is
   confirmed and `RELAY_HOST` is recorded as the workaround.
4. Ollama latency over cellular measured and written down.
5. Ten minutes of beaconing without a dropout.
6. Pi returns to the home network on its own when the hotspot is turned off.
   Test this explicitly. Losing remote access to the Pi is the worst outcome of
   this whole exercise, and it is entirely preventable.
