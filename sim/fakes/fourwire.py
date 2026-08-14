"""Fake `fourwire`. CP9+ moved FourWire out of displayio; the sample imports it
from here, the display fake ignores the instance entirely."""


class FourWire:
    def __init__(self, spi_bus, command=None, chip_select=None, reset=None,
                 baudrate=24000000, polarity=0, phase=0):
        self.spi_bus = spi_bus
        self.command = command
        self.chip_select = chip_select
        self.reset = reset
        self.baudrate = baudrate

    def send(self, *a, **kw):
        pass

    def deinit(self):
        pass
