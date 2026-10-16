"""Example extension: drive Raspberry Pi GPIO pins from routed signals.

This is a complete, working sink that lives entirely outside the core tree — it
was "installed" just by being copied into ``extensions/``. It shows the two
things a real output extension needs: mapping the abstract bus ports onto real
hardware, and degrading gracefully when the hardware library isn't present.

Ports
-----
  pwm.0 .. pwm.3   scalar, -1..1  -> servo/ESC pulse width on four PWM pins
                   (mapped 1.0..2.0 ms; centre 0 -> 1.5 ms — the neutral a hobby
                   servo or a drone ESC expects)
  gpio.0 .. gpio.3 event 0/1      -> digital high/low on four output pins

So "tilt the sensor to swing a servo" is ``bmi160/tilt.roll -> gpio/pwm.0`` with a
``scale``/``clamp`` chain, and "shake to fire a relay" is
``bmi160/accel.mag -> gpio/gpio.0`` through a ``threshold``. Re-pin the BCM
numbers with the ``pwm_pins`` / ``gpio_pins`` args.

Run it
------
    python run.py --sink gpio                       # auto: real GPIO on a Pi, else log
    python run.py --sink gpio:pwm_pins=18,13        # two PWM channels on BCM 18,13

On anything that isn't a Pi (no ``RPi.GPIO``) it stays selectable and simply logs
what it *would* drive, so you can build and preview the patch on your laptop.
"""

from __future__ import annotations

import time

from engine.registry import register_sink
from engine.signals import PortSpec, SCALAR, EVENT
from sinks.base import Sink

PWM_HZ = 50                    # 50 Hz standard servo/ESC frame
_MIN_MS, _MAX_MS = 1.0, 2.0    # pulse width at input -1 .. +1


def _pins(spec, default):
    """Parse a "18,13,12" pin list arg into a list of BCM ints."""
    if not spec:
        return list(default)
    return [int(x) for x in str(spec).split(",") if x.strip() != ""]


@register_sink
class GPIOSink(Sink):
    type = "gpio"
    id = "gpio"
    label = "Raspberry Pi GPIO"
    ARGS = {
        "pwm_pins":  {"default": "18,13,12,19", "type": str,
                      "help": "BCM pins for pwm.0.. (comma list)"},
        "gpio_pins": {"default": "17,27,22,23", "type": str,
                      "help": "BCM pins for gpio.0.. (comma list)"},
    }

    @classmethod
    def available(cls):
        # Selectable everywhere; only the *real* driver needs the Pi library, and
        # we fall back to logging without it. So: always available.
        return True

    def __init__(self, pwm_pins="18,13,12,19", gpio_pins="17,27,22,23"):
        self._pwm_pins = _pins(pwm_pins, [18, 13, 12, 19])
        self._gpio_pins = _pins(gpio_pins, [17, 27, 22, 23])
        self._GPIO = None
        self._pwm = {}          # port id -> RPi.GPIO PWM handle
        self._real = False
        self._last_log = 0.0

    @property
    def PORTS(self):
        out = []
        for i in range(len(self._pwm_pins)):
            out.append(PortSpec(f"pwm.{i}", SCALAR, f"pwm.{i}", "pwm", "-1..1",
                                f"BCM {self._pwm_pins[i]} · servo/ESC pulse"))
        for i in range(len(self._gpio_pins)):
            out.append(PortSpec(f"gpio.{i}", EVENT, f"gpio.{i}", "digital",
                                hint=f"BCM {self._gpio_pins[i]} · high when >=0.5"))
        return out

    def start(self):
        try:
            import RPi.GPIO as GPIO  # only present on a Pi
        except Exception:
            print("[gpio] RPi.GPIO not available — logging outputs instead of driving pins")
            return
        self._GPIO = GPIO
        GPIO.setmode(GPIO.BCM)
        GPIO.setwarnings(False)
        for i, pin in enumerate(self._pwm_pins):
            GPIO.setup(pin, GPIO.OUT)
            handle = GPIO.PWM(pin, PWM_HZ)
            handle.start(self._duty(0.0))
            self._pwm[f"pwm.{i}"] = handle
        for pin in self._gpio_pins:
            GPIO.setup(pin, GPIO.OUT, initial=GPIO.LOW)
        self._real = True
        print(f"[gpio] driving PWM {self._pwm_pins} + digital {self._gpio_pins}")

    def _duty(self, x):
        """Map -1..1 to a PWM duty-cycle percent for a 1..2 ms pulse at 50 Hz."""
        x = max(-1.0, min(1.0, x))
        ms = _MIN_MS + (x + 1.0) * 0.5 * (_MAX_MS - _MIN_MS)
        return ms / (1000.0 / PWM_HZ) * 100.0

    def apply(self, values, dt):
        if self._real:
            for port, handle in self._pwm.items():
                handle.ChangeDutyCycle(self._duty(values.get(port, 0.0)))
            for i, pin in enumerate(self._gpio_pins):
                self._GPIO.output(pin, self._GPIO.HIGH
                                  if values.get(f"gpio.{i}", 0.0) >= 0.5 else self._GPIO.LOW)
            return
        # Fallback: throttled log so the patch is still previewable off-Pi.
        active = {k: round(v, 3) for k, v in values.items() if abs(v) > 1e-3}
        now = time.perf_counter()
        if active and now - self._last_log > 0.5:
            self._last_log = now
            print("  [gpio:log]", " ".join(f"{k}={v}" for k, v in sorted(active.items())))

    def release_all(self):
        # Centre every PWM (servos to neutral / ESCs to idle) and drop every pin.
        if not self._real:
            return
        for handle in self._pwm.values():
            try:
                handle.ChangeDutyCycle(self._duty(0.0))
            except Exception:
                pass
        for pin in self._gpio_pins:
            try:
                self._GPIO.output(pin, self._GPIO.LOW)
            except Exception:
                pass

    def stop(self):
        self.release_all()
        if self._real:
            try:
                for handle in self._pwm.values():
                    handle.stop()
                self._GPIO.cleanup()
            except Exception:
                pass
