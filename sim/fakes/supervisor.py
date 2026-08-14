"""Fake `supervisor`.

On the badge, reload() restarts code.py, which lands back in the Launcher. In
the simulator there is no Launcher, so raise a distinct exception that run.py
catches and reports rather than pretending a restart happened.
"""

import time

_START = time.monotonic()

# The badge does not boot with ticks at zero. Start partway through the range
# so wraparound arithmetic gets exercised rather than never being reached.
_TICKS_OFFSET = 0x1FFF0000


class ReloadRequest(SystemExit):
    """Raised by reload(). run.py catches this and says so."""


class _RunReason:
    STARTUP = "STARTUP"
    AUTO_RELOAD = "AUTO_RELOAD"
    SUPERVISOR_RELOAD = "SUPERVISOR_RELOAD"
    REPL_RELOAD = "REPL_RELOAD"


class _Runtime:
    serial_connected = True
    serial_bytes_available = 0
    run_reason = _RunReason.STARTUP
    autoreload = False


runtime = _Runtime()
RunReason = _RunReason


def reload():
    raise ReloadRequest("supervisor.reload() -- badge would return to the Launcher")


def ticks_ms():
    # CircuitPython's ticks_ms is a 29-bit value and adafruit_ticks assumes
    # that period. Masking at 2**30 here would hide wraparound bugs.
    # Offset the start so wraparound can actually occur in a long sim run.
    return (int((time.monotonic() - _START) * 1000) + _TICKS_OFFSET) & 0x1FFFFFFF


def set_next_code_file(*a, **kw):
    pass
