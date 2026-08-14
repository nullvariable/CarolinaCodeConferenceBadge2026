"""Fake `socketpool` for the desktop simulator.

Real CPython sockets underneath, CircuitPython's API on top. The point is
not to make networking work on the laptop -- it already does -- but to make
it fail the same way, because that is where badge code goes wrong.

Four differences are enforced deliberately:

* **`recvfrom` does not exist.** CircuitPython only has `recvfrom_into`.
  A sample written against `recvfrom` runs fine on CPython and dies on the
  badge, so it has to die here too.
* **An empty non-blocking socket raises `OSError` with `errno == 11`**, not
  CPython's `BlockingIOError`. The badge's `except OSError` / `e.errno == 11`
  path is the hot path in the frame loop, and it has to be exercised for
  real rather than by a lucky subclass match.
* **`setsockopt` accepts only `SO_REUSEADDR` and `TCP_NODELAY`.** Those are
  the two the CircuitPython implementation takes. Anything else raises,
  which is what stops somebody adding `SO_BROADCAST` here and discovering on
  Saturday that it raises on the badge.
* **`settimeout(0)` and `settimeout(0.5)` are not the same call.** Zero means
  non-blocking and an empty socket gives `EAGAIN`; anything positive gives
  `ETIMEDOUT` instead, which breaks an `errno == 11` poll loop. CPython
  raises the same `socket.timeout` either way, so the distinction is
  reproduced here by hand.

The one thing papered over: CPython refuses to send to 255.255.255.255
without `SO_BROADCAST`, while lwIP on the ESP32 has its broadcast filter
compiled out and needs nothing. The wrapper sets that option on the
underlying socket itself, so badge code stays free of a call that would
raise on hardware.
"""

import errno as _errno
import socket as _socket

# WSL2 sits on its own NAT'd subnet, so a broadcast from here does not reach
# the LAN. Point RELAY_HOST at the Pi when testing networking from WSL.
# Broadcast is proven working between real devices on a real AP.


def _oserror(err, message):
    """A plain OSError carrying an errno, and not an OSError subclass.

    `OSError(errno.EAGAIN, msg)` does not do this: CPython inspects the errno
    and hands back a BlockingIOError instead. That silently defeated the
    strictness this module exists for, because badge code written
    `except BlockingIOError` then passed here and would have died on the
    badge, where MicroPython has no such class. Setting the attribute after
    construction keeps the type plain.
    """
    e = OSError(message)
    e.errno = err
    return e


class Socket:
    """One UDP socket, with CircuitPython's method set and nothing else."""

    def __init__(self, family, type_, proto=0):
        self._sock = _socket.socket(family, type_, proto)
        self._closed = False
        self._timeout = 0.0
        # Not exposed to the sample: on the badge this is free, here it is
        # required, and asking the sample to know the difference would defeat
        # the whole point of the simulator.
        try:
            self._sock.setsockopt(_socket.SOL_SOCKET, _socket.SO_BROADCAST, 1)
        except OSError:
            pass

    # --- configuration ---------------------------------------------------

    def setsockopt(self, level, opt, value):
        self._check_open()
        if level == SocketPool.SOL_SOCKET and opt == SocketPool.SO_REUSEADDR:
            self._sock.setsockopt(_socket.SOL_SOCKET, _socket.SO_REUSEADDR, value)
            return
        if level == SocketPool.IPPROTO_TCP and opt == SocketPool.TCP_NODELAY:
            self._sock.setsockopt(_socket.IPPROTO_TCP, _socket.TCP_NODELAY, value)
            return
        # CircuitPython takes these two and nothing else. SO_BROADCAST in
        # particular is not exposed and raises on some ports.
        raise OSError(_errno.EINVAL,
                      "setsockopt option %r not supported on CircuitPython" % (opt,))

    def settimeout(self, value):
        self._check_open()
        # settimeout(0) and setblocking(False) are the same call. A positive
        # timeout is NOT the same: CircuitPython raises ETIMEDOUT rather than
        # EAGAIN, which breaks the `errno == 11` poll idiom the frame loop is
        # built on. Remembered here so recvfrom_into can reproduce that.
        self._timeout = value or 0.0
        self._sock.settimeout(self._timeout)
        if not value:
            self._sock.setblocking(False)

    def bind(self, address):
        self._check_open()
        host, port = address
        self._sock.bind((host or "0.0.0.0", port))

    # --- traffic ---------------------------------------------------------

    def sendto(self, data, address):
        self._check_open()
        return self._sock.sendto(data, address)

    def recvfrom_into(self, buffer, nbytes=0):
        """(nbytes, (host, port)). Silently truncates, exactly like the badge."""
        self._check_open()
        try:
            if nbytes:
                view = memoryview(buffer)[:nbytes]
            else:
                view = buffer
            return self._sock.recvfrom_into(view)
        except BlockingIOError:
            raise _oserror(_errno.EAGAIN, "no data available")
        except _socket.timeout:
            # A positive timeout gives ETIMEDOUT on the badge, not EAGAIN.
            # Reproducing that is the whole point: code written against a
            # small positive timeout works on CPython and stops receiving on
            # hardware.
            if self._timeout:
                raise _oserror(_errno.ETIMEDOUT, "timed out")
            raise _oserror(_errno.EAGAIN, "no data available")

    def close(self):
        if not self._closed:
            self._closed = True
            self._sock.close()

    def _check_open(self):
        if self._closed:
            raise OSError(_errno.EBADF, "socket is closed")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


class SocketPool:
    """CircuitPython hangs the address-family constants off the pool."""

    AF_INET = _socket.AF_INET
    AF_INET6 = _socket.AF_INET6
    SOCK_STREAM = _socket.SOCK_STREAM
    SOCK_DGRAM = _socket.SOCK_DGRAM
    SOL_SOCKET = _socket.SOL_SOCKET
    SO_REUSEADDR = _socket.SO_REUSEADDR
    IPPROTO_TCP = _socket.IPPROTO_TCP
    TCP_NODELAY = _socket.TCP_NODELAY
    EAI_NONAME = -2

    def __init__(self, radio):
        self.radio = radio

    def socket(self, family=AF_INET, type=SOCK_DGRAM, proto=0):
        return Socket(family, type, proto)

    def getaddrinfo(self, host, port, family=0, type=0, proto=0, flags=0):
        return _socket.getaddrinfo(host, port, family, type, proto, flags)
