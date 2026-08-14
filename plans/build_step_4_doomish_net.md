# Build step 4: badge networking

**Deliverable:** the badge talks to the relay. Beacon out, directive in, nothing
blocks, and the game keeps playing when the network is absent.

**Depends on:** steps 1-3. **Blocks:** step 6.

Read `plans/build_overview.md` first, especially the verified-facts list. Several
of those facts were expensive to establish and contradict what the CircuitPython
docs imply.

## Two halves

Badge side goes in `samples/Doomish/code.py`. Simulator side goes in
`sim/fakes/wifi.py` and `sim/fakes/socketpool.py`, deferred from step 1 so the
API surface is defined in one place: here.

`relay/fake_badge.py` is the working reference implementation of this exact
pattern, already proven against the live relay. Read it before writing anything.

## Badge side

### Credentials

```python
WIFI_SSID = os.getenv("WIFI_SSID", "")
WIFI_PASSWORD = os.getenv("WIFI_PASSWORD", "")
```

Not `CIRCUITPY_WIFI_*`. Those magic names trigger CircuitPython's web workflow
and add ~10 s to every cold boot for every sample on the drive. See
`settings.toml.example`.

No credentials means run reflex-only, show `LOCAL` in the directive strip, and
never retry. The game must be fully playable with no network at all. That is
also the fallback if conference wifi is hostile.

### Connect

```python
wifi.radio.power_management = wifi.PowerManagement.NONE
wifi.radio.connect(WIFI_SSID, WIFI_PASSWORD)
```

Power management is not optional. The default wakes only on DTIM and
`PowerManagement.MAX` drops AP-buffered broadcast frames outright, which is
exactly the traffic this design depends on. The same setting cost 65-110 ms per
packet on the Pi before it was disabled there.

Wrap in try/except. A failed connect drops to `LOCAL`, it does not crash.

### Socket

```python
pool = socketpool.SocketPool(wifi.radio)
sock = pool.socket(pool.AF_INET, pool.SOCK_DGRAM)
sock.setsockopt(pool.SOL_SOCKET, pool.SO_REUSEADDR, 1)
sock.bind(("", BADGE_PORT))
sock.settimeout(0)
_rx = bytearray(512)
```

**Do not call `setsockopt` with `SO_BROADCAST`.** It is not exposed, it is
unnecessary (lwIP's broadcast filter is compiled out on ESP32), and on some
CircuitPython ports it raises `OSError`. `SO_REUSEADDR` is one of only two
options this implementation accepts.

`settimeout(0)` and `setblocking(False)` are literally the same call. Use `0`,
not a small positive timeout: a positive timeout raises `ETIMEDOUT` instead of
`EAGAIN` and the poll idiom below stops working.

Preallocate `_rx` once. Never allocate in the frame loop.

### Send

```python
def send_beacon():
    try:
        sock.sendto(json.dumps(state).encode(), (RELAY_HOST or "255.255.255.255", RELAY_PORT))
    except BrokenPipeError:
        pass          # link down / no route
    except OSError:
        pass
```

`BrokenPipeError` must be caught first, it is an `OSError` subclass. `sendto`
discards the errno, so a failure here means no route, not permissions.

`RELAY_HOST` is a config constant defaulting to `""` (broadcast). If a venue AP
isolates clients, putting the Pi's IP there takes broadcast out of the picture
without touching any other code. That is the field-repair escape hatch.

Only serialise on send, never per frame. `json.dumps` is not cheap here.

### Poll

Once per frame, right after the render:

```python
def poll_directive():
    try:
        n, addr = sock.recvfrom_into(_rx)
    except OSError as e:
        if e.errno == 11:      # EAGAIN, the normal empty-socket case
            return None
        raise
    return json.loads(bytes(memoryview(_rx)[:n]))
```

**`recvfrom` does not exist in CircuitPython.** Only `recvfrom_into`. Truncation
is silent, so 512 bytes must comfortably exceed any reply.

The EAGAIN path allocates an exception object every frame. On a no-PSRAM part
that is real GC pressure. If frame timing shows GC pauses, poll every Nth frame
instead. Measure before optimising.

### Accepting a reply

Validate the directive against the eight-value vocabulary and ignore anything
else. The relay already normalises and validates, but the badge must not trust
the network.

Accept a reply whose `seq` is within 2 of the current one, not just an exact
match. Directives take 2-4 s and change slowly, so one aimed at the previous
beacon is still worth acting on. `relay/fake_badge.py` does this already.

On accept: set `directive`, `directive_why`, `directive_at = now`, clear the
in-flight flag, pulse LED 4 bright cyan for one beat, and print a serial line.

### Reconnect

If `wifi.radio.connected` goes false: reconnect, then **build a new socket**.
CircuitPython does not close user sockets on disconnect and the old pcb keeps
the stale IP, so the socket silently stops working. Recreating is cheap and
removes a whole class of worked-at-rehearsal-dead-on-the-day failure.

Cap total sockets at one. The device limit is 8 device-wide and the web workflow
takes from the same pool.

## Simulator side

### `sim/fakes/wifi.py`
`radio` singleton with `connect()` (no-op), `connected` (True), `ipv4_address`
(the real local IP so the dashboard shows something plausible),
`power_management`, and a `PowerManagement` enum with `NONE`/`MIN`/`MAX`.

### `sim/fakes/socketpool.py`
`SocketPool(radio)` returning sockets that wrap real CPython UDP sockets, with
the **CircuitPython** API surface, not the CPython one:

* `AF_INET`, `SOCK_DGRAM`, `SOL_SOCKET`, `SO_REUSEADDR` on the pool object
* `recvfrom_into(buf)` returning `(nbytes, addr)`
* `settimeout(0)` raising `OSError(11)` on an empty socket, **not**
  `BlockingIOError`, so the badge's except clause is exercised for real
* `setsockopt` accepting only `SO_REUSEADDR` and `TCP_NODELAY`, raising
  `OSError` otherwise, mirroring the real implementation

Getting these wrong makes the simulator lie in exactly the place it matters most.
The fake should be strict where CircuitPython is strict.

Note WSL2 is NAT'd onto its own subnet, so a broadcast from the simulator will
not reach the LAN. Point `RELAY_HOST` at the Pi when testing from WSL. Broadcast
is already proven between real devices on the real AP.

## Verification

1. Simulator with `RELAY_HOST` set to the Pi. Directives appear in the strip and
   change over time. `journalctl -u doomish-relay -f` shows matching exchanges.
2. Kill the relay mid-run. The game keeps playing, the strip goes stale then
   falls back, nothing crashes, no traceback.
3. Restart the relay. Directives resume with no badge restart.
4. Blank `WIFI_SSID`. Boots straight to `LOCAL` and plays reflex-only.
5. Point `RELAY_HOST` at an address with nothing on it. Same as case 2.
6. Check the relay log for `+repaired` tags. Frequent repairs mean the system
   prompt needs the vocabulary stated harder.
7. Run 15 minutes and confirm frame time has not drifted upward, which would
   indicate a leak in the poll path.
