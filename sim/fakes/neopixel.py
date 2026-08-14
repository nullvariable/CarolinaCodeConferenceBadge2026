"""Fake `neopixel` for the desktop simulator.

The badge's 5 WS2812s are a real status channel in every sample in this repo,
so the simulator has to show them somewhere. Rather than open a second window,
draw the strip as ANSI 24-bit colour blocks on stdout. Any change redraws
immediately; an unchanged frame redraws at most once a second.
"""

import sys
import time



def _as_rgb(value):
    if isinstance(value, int):
        return ((value >> 16) & 0xFF, (value >> 8) & 0xFF, value & 0xFF)
    r, g, b = (tuple(value) + (0, 0, 0))[:3]
    return (int(r) & 0xFF, int(g) & 0xFF, int(b) & 0xFF)


class NeoPixel:
    def __init__(self, pin, n, brightness=1.0, auto_write=True, pixel_order=None):
        self.pin = pin
        self.n = n
        self.brightness = brightness
        self.auto_write = auto_write
        self._pixels = [(0, 0, 0)] * n
        self._last_drawn = None
        self._last_time = 0.0

    def __len__(self):
        return self.n

    def __setitem__(self, index, value):
        if isinstance(index, slice):
            for i, v in zip(range(*index.indices(self.n)), value):
                self._pixels[i] = _as_rgb(v)
        else:
            self._pixels[index] = _as_rgb(value)
        if self.auto_write:
            self.show()

    def __getitem__(self, index):
        return self._pixels[index]

    def fill(self, value):
        rgb = _as_rgb(value)
        self._pixels = [rgb] * self.n
        if self.auto_write:
            self.show()

    def deinit(self):
        self._pixels = [(0, 0, 0)] * self.n

    def show(self):
        now = time.monotonic()
        scaled = [
            tuple(min(255, int(c * self.brightness)) for c in px)
            for px in self._pixels
        ]

        # Always draw a change. Throttling changes was wrong: a one-shot update
        # like "turn every pixel off" is a single show() call, and if it landed
        # inside the throttle window it was dropped and never redrawn, so the
        # LEDs appeared stuck on forever. Only repeats of an identical frame get
        # rate-limited, and those are the ones nobody needs to see again.
        if scaled == self._last_drawn and now - self._last_time < 1.0:
            return

        self._last_drawn = scaled
        self._last_time = now

        blocks = "".join(
            "\x1b[38;2;%d;%d;%dm██\x1b[0m " % rgb for rgb in scaled
        )
        sys.stdout.write("\rLEDS  %s" % blocks)
        sys.stdout.flush()
