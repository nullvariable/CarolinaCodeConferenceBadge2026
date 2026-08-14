"""Fake `pwmio`. Some samples drive the backlight with PWM to fade it."""


class PWMOut:
    def __init__(self, pin, frequency=500, duty_cycle=0, variable_frequency=False):
        self.pin = pin
        self.frequency = frequency
        self.duty_cycle = duty_cycle

    def deinit(self):
        pass
