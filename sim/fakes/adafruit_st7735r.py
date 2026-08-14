"""Fake `adafruit_st7735r` for the desktop simulator.

Returns a PyGame window standing in for the badge's ST7735S panel.

Rotation is handled here rather than passed through. On hardware the driver is
constructed with the panel's native portrait size (128x160) and `rotation=90`
makes displayio present it as 160x128 landscape, with `display.width` and
`display.height` reporting the rotated values. This fake computes those same
rotated dimensions and builds the window at that size, so a renderer that reads
`display.width` / `display.height` behaves identically on both platforms.
"""

import sys

import pygame
from blinka_displayio_pygamedisplay import PyGameDisplay

# Keyboard and mouse events are not consumed by check_quit(), which filters for
# displayio and QUIT types only. Left alone they accumulate until pygame's
# 128-event queue overflows and starts dropping, which can swallow a QUIT.
# Drain the ones nobody reads from the queue; key *state* is unaffected.
_DRAINABLE = [
    pygame.KEYDOWN,
    pygame.KEYUP,
    pygame.MOUSEMOTION,
    pygame.MOUSEBUTTONDOWN,
    pygame.MOUSEBUTTONUP,
    pygame.TEXTINPUT,
]


class _BadgeDisplay(PyGameDisplay):
    """PyGameDisplay that exits cleanly and does not throttle the frame rate."""

    def refresh(self, *args, **kwargs):
        # check_quit() defaults to delay=0.05, which would silently cap the
        # simulator at 20 FPS. Pass 0 and let the game loop set the pace.
        if self.check_quit(delay=0):
            raise SystemExit(0)
        pygame.event.clear(eventtype=_DRAINABLE)
        return super().refresh(*args, **kwargs)


class ST7735R(_BadgeDisplay):
    """Stands in for the badge panel. A real class, so `isinstance` and
    subclassing behave the way they would against the actual driver."""

    def __init__(
        self,
        display_bus,
        width=128,
        height=160,
        rotation=0,
        bgr=False,
        auto_refresh=True,   # CircuitPython's real default. Do not "fix" this
                             # to False: a sample that omits the argument relies
                             # on it, and defaulting False makes such a sample
                             # silently render nothing here while working on the
                             # badge.
        colstart=0,
        rowstart=0,
        invert=False,
        **kwargs
    ):
        eff_w, eff_h = (height, width) if rotation in (90, 270) else (width, height)

        # colstart/rowstart/bgr/invert are accepted and ignored. Real ST7735S
        # panels often need those offsets, so the simulator can render perfectly
        # aligned while hardware is shifted a few pixels. Check on the badge.
        super().__init__(
            width=eff_w,
            height=eff_h,
            caption="CCC 2026 badge  (%dx%d, rotation %d)" % (eff_w, eff_h, rotation),
            native_frames_per_second=60,
        )
        self.auto_refresh = bool(auto_refresh)
        self._warn_if_auto()

    def _warn_if_auto(self):
        if self.auto_refresh:
            sys.stderr.write(
                "\n[sim] WARNING: this sample uses auto_refresh=True.\n"
                "[sim]   pygame can only be driven from the main thread, so the\n"
                "[sim]   background refresh thread posts one event and then stalls.\n"
                "[sim]   The window will not update. This is a simulator limit, not\n"
                "[sim]   a bug in the sample -- it works on the badge.\n"
                "[sim]   Samples that call display.refresh() explicitly are fine.\n\n"
            )
