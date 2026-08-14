"""Fake `board` for the desktop simulator.

Blinka ships a real `board`, but on a PC it resolves to GENERIC_X86 where
`board.IO12` does not exist. This shadows it with plain named pin objects.
Nothing reads a pin's value here; the pin is just an identity that the other
fakes switch on.
"""


class Pin:
    def __init__(self, name):
        self.name = name

    def __repr__(self):
        return "<Pin %s>" % self.name

    def __hash__(self):
        return hash(self.name)

    def __eq__(self, other):
        return isinstance(other, Pin) and other.name == self.name


# The ESP32-S3-WROOM-1 exposes these; create them all so any sample resolves.
for _n in range(0, 49):
    globals()["IO%d" % _n] = Pin("IO%d" % _n)

# Aliases the CircuitPython board module also defines.
LED = globals()["IO4"]
SPI_CLOCK = globals()["IO12"]
SPI_MOSI = globals()["IO11"]


# No __getattr__ fallback on purpose. An earlier version fabricated any IOnn on
# demand so a typo would "just work" here and then die on the badge, which is
# the worst thing a simulator can do. The loop above already defines every real
# ESP32-S3 GPIO, so anything else is a mistake and should raise exactly as
# CircuitPython does.
