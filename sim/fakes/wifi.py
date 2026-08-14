"""Fake `wifi` for the desktop simulator.

The laptop is already on a network, so connecting is a no-op. What this has
to get right is the *shape* of CircuitPython's API, because the sample is
written against that and never learns it is not on a badge.

`ipv4_address` reports the real local address rather than a placeholder, so
a sample that prints it, or a dashboard that displays it, shows something
that is actually true and can be pinged.
"""

import socket as _socket


class PowerManagement:
    """CircuitPython's enum. The badge sets NONE and it is not optional.

    The default wakes only on DTIM and MAX drops AP-buffered broadcast frames
    outright, which is exactly the traffic the relay protocol depends on. The
    same setting cost 65-110 ms per packet on the Pi before it was turned off
    there. Nothing here enforces it -- the laptop has no radio to manage --
    so this is a place the simulator cannot warn you.
    """

    NONE = "NONE"
    MIN = "MIN"
    MAX = "MAX"


def _local_ip():
    """Address of the interface that would carry traffic off this machine.

    Connecting a UDP socket sends nothing; it just asks the routing table
    which source address would be used. Falls back to loopback rather than
    raising, because a sample must not die at boot over cosmetics.
    """
    s = _socket.socket(_socket.AF_INET, _socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 1))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


class _Radio:
    def __init__(self):
        self.power_management = PowerManagement.NONE
        self._connected = True
        self._ssid = None

    def connect(self, ssid, password=None, timeout=None, **kwargs):
        # No association to do. Recorded so a sample can print it back.
        self._ssid = ssid
        self._connected = True

    def disconnect(self):
        self._connected = False

    @property
    def connected(self):
        return self._connected

    @property
    def ap_info(self):
        return None

    @property
    def ipv4_address(self):
        return _local_ip()

    @property
    def ipv4_gateway(self):
        return None

    @property
    def mac_address(self):
        return b"\x00\x00\x00\x00\x00\x00"


radio = _Radio()
