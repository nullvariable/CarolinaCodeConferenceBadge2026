#!/usr/bin/env python3
"""Run a badge sample on the desktop.

    sim/.venv/bin/python sim/run.py Doomish
    sim/.venv/bin/python sim/run.py Nameplate --fps

The sample is not modified and knows nothing about this. `sim/fakes` goes to the
front of sys.path so `board`, `digitalio`, `busio`, `fourwire`, `neopixel`,
`pwmio` and `adafruit_st7735r` resolve to the simulator's versions, while
`displayio`, `bitmaptools` and `terminalio` still come from Blinka, which
implements them for real. Then the file is exec'd exactly the way the badge's
Launcher does it:

    exec(source, {"__name__": "__main__", "__file__": path})

Anything that runs here is real badge code.
"""

import argparse
import os
import re
import signal
import sys
import time
import traceback

SIM_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_DIR = os.path.dirname(SIM_DIR)
FAKES_DIR = os.path.join(SIM_DIR, "fakes")


def load_settings_toml():
    """Copy settings.toml keys into the environment.

    On the badge, os.getenv() reads settings.toml. On CPython it reads the
    process environment. This is the only place the two platforms genuinely
    differ, and handling it here keeps the difference out of the sample.
    """
    path = os.path.join(REPO_DIR, "settings.toml")
    if not os.path.exists(path):
        return 0

    pattern = re.compile(r'^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.+?)\s*$')
    count = 0
    with open(path) as f:
        for line in f:
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            m = pattern.match(line)
            if not m:
                continue
            key, raw = m.group(1), m.group(2)
            if raw[:1] in ('"', "'") and raw[-1:] == raw[:1]:
                raw = raw[1:-1]
            os.environ.setdefault(key, raw)
            count += 1
    return count


def install_drive_root():
    """Make CircuitPython's absolute paths resolve to the repo root.

    On the badge the CIRCUITPY drive IS the filesystem root, so samples open
    "/img/logo.bmp" and the Launcher walks "/samples". On a laptop those point
    at the actual root and fail. Rewrite a leading "/" to the repo directory,
    but only when the original path does not exist, so real system paths are
    untouched.
    """
    import builtins

    real_open, real_listdir, real_stat = builtins.open, os.listdir, os.stat

    def exists(path):
        # Must use the pre-patch stat. os.path.exists() would call the patched
        # os.stat, which calls back into mapped(), which recurses forever.
        try:
            real_stat(path)
            return True
        except (OSError, ValueError):
            return False

    def mapped(path):
        if not isinstance(path, str) or not path.startswith("/"):
            return path
        candidate = os.path.join(REPO_DIR, path.lstrip("/"))

        # The repo wins whenever it has the file. That is what "the CIRCUITPY
        # drive is the filesystem root" means. Checking the host first was wrong:
        # /lib exists on Linux, so "/lib" silently resolved to the host's shared
        # objects instead of the badge's library folder.
        if exists(candidate):
            return candidate

        # Not present anywhere yet. If the parent directory exists in the repo,
        # this is a create, so point it at the repo rather than the real root
        # where it would fail with PermissionError.
        if not exists(path) and exists(os.path.dirname(candidate)):
            return candidate

        return path

    real_scandir = os.scandir

    builtins.open = lambda file, *a, **kw: real_open(mapped(file), *a, **kw)
    os.listdir = lambda path=None: real_listdir(mapped(path) if path else path)
    os.stat = lambda path, *a, **kw: real_stat(mapped(path), *a, **kw)
    os.scandir = lambda path=None: real_scandir(mapped(path) if path else path)


class FrameTimer:
    """Rolling frame-time average, printed on one rewritten line."""

    def __init__(self, enabled, window=30):
        self.enabled = enabled
        self.window = window
        self.samples = []
        self.last = None
        self.last_print = 0.0

    def tick(self):
        if not self.enabled:
            return
        now = time.monotonic()
        if self.last is not None:
            self.samples.append(now - self.last)
            if len(self.samples) > self.window:
                self.samples.pop(0)
        self.last = now

        if now - self.last_print >= 1.0 and self.samples:
            avg = sum(self.samples) / len(self.samples)
            sys.stderr.write(
                "\r[sim] %5.1f fps  (%5.1f ms/frame)   " % (1.0 / avg, avg * 1000)
            )
            sys.stderr.flush()
            self.last_print = now


def install_fps_hook(timer):
    """Count frames by wrapping the display's refresh().

    Done by patching the fake driver's factory rather than asking the sample to
    cooperate, so the sample stays simulator-unaware.
    """
    import adafruit_st7735r

    original = adafruit_st7735r.ST7735R

    def wrapped(*args, **kwargs):
        display = original(*args, **kwargs)
        inner = display.refresh

        def counted(*a, **kw):
            timer.tick()
            return inner(*a, **kw)

        display.refresh = counted
        return display

    adafruit_st7735r.ST7735R = wrapped


def hard_exit(code=0):
    """Leave immediately, without waiting to join threads.

    Blinka's displayio starts a non-daemon background refresh thread that never
    returns. A normal interpreter shutdown blocks joining it, so the process
    ignores SIGTERM and spins forever at 100% CPU -- `timeout 12` does not kill
    it and neither does ctrl-c. os._exit skips all of that.
    """
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(code)


def _on_signal(signum, frame):
    sys.stderr.write("\n[sim] signal %d, exiting\n" % signum)
    hard_exit(128 + signum)


def main():
    signal.signal(signal.SIGTERM, _on_signal)
    signal.signal(signal.SIGINT, _on_signal)

    p = argparse.ArgumentParser(description="Run a badge sample on the desktop")
    p.add_argument("sample", nargs="?", help="folder name under samples/, e.g. Doomish")
    p.add_argument("--fps", action="store_true", help="print a rolling frame rate")
    p.add_argument("--list", action="store_true", help="list available samples")
    args = p.parse_args()

    samples_dir = os.path.join(REPO_DIR, "samples")
    if args.list:
        for name in sorted(os.listdir(samples_dir)):
            if os.path.exists(os.path.join(samples_dir, name, "code.py")):
                print(name)
        return 0

    if not args.sample:
        p.error("a sample name is required (or use --list)")

    path = os.path.join(samples_dir, args.sample, "code.py")
    if not os.path.exists(path):
        print("no such sample: %s" % path, file=sys.stderr)
        print("try --list", file=sys.stderr)
        return 2

    # Fakes must win over Blinka's board/digitalio/busio/fourwire.
    sys.path.insert(0, FAKES_DIR)

    install_drive_root()

    n = load_settings_toml()
    print("[sim] running %s" % path)
    if n:
        print("[sim] loaded %d keys from settings.toml" % n)
    else:
        print("[sim] no settings.toml -- os.getenv() falls back to defaults")

    import digitalio  # the fake, for its key map

    print("[sim] buttons: %s" % digitalio.KEY_HELP)
    print("[sim] close the window or ctrl-c to stop")

    timer = FrameTimer(args.fps)
    if args.fps:
        install_fps_hook(timer)

    import supervisor

    with open(path) as f:
        source = f.read()

    try:
        exec(compile(source, path, "exec"), {"__name__": "__main__", "__file__": path})
    except supervisor.ReloadRequest as e:
        print("\n[sim] %s" % e)
        return 0
    except SystemExit as e:
        print("\n[sim] window closed")
        return int(e.code or 0)
    except KeyboardInterrupt:
        print("\n[sim] interrupted")
        return 0
    except Exception:
        print("\n[sim] sample raised:", file=sys.stderr)
        traceback.print_exc()
        return 1

    print("\n[sim] sample returned")
    return 0


if __name__ == "__main__":
    hard_exit(main() or 0)
