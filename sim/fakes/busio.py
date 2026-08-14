"""Fake `busio`. The display fake never touches the bus, so this only records."""


class SPI:
    def __init__(self, clock=None, MOSI=None, MISO=None):
        self.clock, self.MOSI, self.MISO = clock, MOSI, MISO
        self._locked = False

    def try_lock(self):
        self._locked = True
        return True

    def unlock(self):
        self._locked = False

    def configure(self, baudrate=None, polarity=0, phase=0, bits=8):
        pass

    def deinit(self):
        pass


class I2C:
    def __init__(self, *a, **kw):
        pass

    def deinit(self):
        pass
