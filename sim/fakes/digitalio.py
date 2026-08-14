"""Fake `digitalio` for the desktop simulator.

Input pins on the three switch GPIOs read the keyboard. Outputs (backlight,
font-chip CS) just remember what they were set to.

Switches are active-low on the badge: the internal pull-up holds the pin high
and pressing shorts it to ground, so `value == False` means pressed. The fake
reproduces that, because getting it backwards here would hide a real bug in the
sample.

Key state comes from `pygame.key.get_pressed()` rather than `pygame.event.get()`
on purpose. `get_pressed` polls state without consuming the event queue, so it
cannot steal the QUIT event that PyGameDisplay.check_quit() is watching for.
"""

try:
    import pygame
except ImportError:
    pygame = None


class Direction:
    INPUT = "INPUT"
    OUTPUT = "OUTPUT"


class Pull:
    UP = "UP"
    DOWN = "DOWN"


class DriveMode:
    PUSH_PULL = "PUSH_PULL"
    OPEN_DRAIN = "OPEN_DRAIN"


# Badge switch -> keys that press it. Two bindings each: the number matching the
# silkscreen, and an arrow for people who would rather not look down.
_KEYMAP = {}
if pygame is not None:
    _KEYMAP = {
        "IO1": (pygame.K_1, pygame.K_LEFT),
        "IO2": (pygame.K_2, pygame.K_DOWN),
        "IO43": (pygame.K_3, pygame.K_RIGHT),
    }

KEY_HELP = "SW1 = 1 or LEFT    SW2 = 2 or DOWN    SW3 = 3 or RIGHT"


class DigitalInOut:
    def __init__(self, pin):
        self.pin = pin
        self.direction = Direction.INPUT
        self.pull = None
        self.drive_mode = DriveMode.PUSH_PULL
        self._value = False
        self._deinited = False

    # --- configuration ---------------------------------------------------

    def switch_to_input(self, pull=None):
        self._check_alive()
        self.direction = Direction.INPUT
        self.pull = pull

    def switch_to_output(self, value=False, drive_mode=DriveMode.PUSH_PULL):
        self._check_alive()
        self.direction = Direction.OUTPUT
        self.drive_mode = drive_mode
        self._value = value

    def deinit(self):
        self._deinited = True

    def _check_alive(self):
        if self._deinited:
            raise ValueError("Object has been deinitialized and can no longer be used.")

    # --- value -----------------------------------------------------------

    @property
    def idle_level(self):
        """What an untouched input reads, given its pull resistor."""
        return self.pull != Pull.DOWN

    @property
    def value(self):
        self._check_alive()
        if self.direction == Direction.OUTPUT:
            return self._value

        keys = _KEYMAP.get(getattr(self.pin, "name", ""))
        if keys is None or pygame is None:
            # Unmapped input sits at whatever its pull resistor says. Returning
            # True unconditionally was wrong: a Pull.DOWN pin idles LOW on
            # hardware and would have read inverted here.
            return self.idle_level

        if not pygame.display.get_init():
            return self.idle_level  # window not up yet

        # pump() refreshes key state without removing anything from the queue.
        pygame.event.pump()
        pressed = pygame.key.get_pressed()
        for k in keys:
            if pressed[k]:
                return not self.idle_level  # held key drives the pin off idle
        return self.idle_level

    @value.setter
    def value(self, v):
        self._check_alive()
        if self.direction != Direction.OUTPUT:
            # CircuitPython refuses this. Accepting it silently would let a
            # write-where-you-meant-read bug reach the badge.
            raise AttributeError("Cannot set value when direction is input.")
        self._value = bool(v)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.deinit()
