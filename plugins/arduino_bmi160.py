"""Arduino Nano + BMI160 (I2C) over USB serial.

Pairs with ``firmware/bmi160_nano/bmi160_nano.ino`` — same library and the same
``BMI160.readGyro`` / ``BMI160.readAccelerometer`` calls as the how2electronics
tutorial this was built from, just reformatted to stream continuously instead
of once a second: one CSV line per sample, ``ax,ay,az,gx,gy,gz\\n``, raw int16
straight off the sensor. The 115200-baud debug prints ("BMI160 initialized...")
the tutorial sketch also does are harmless — any line that doesn't parse to
exactly six ints is silently skipped, so a banner or a dropped byte never
corrupts a real frame; it just costs one frame.

Raw units depend on the full-scale range the sketch configures. The shipped
firmware sets ±2 g / ±250 deg/s explicitly (see the constants below) — change
both sides together if you ever reconfigure the sensor's range.
"""

from __future__ import annotations

import math
import threading
import time

from engine.registry import register_source
from engine.signals import PortSpec, SCALAR
from plugins.base import Source

# Must match BMI160.setAccelerometerRange(...) / BMI160.setGyroRange(...) in the
# sketch. Datasheet sensitivity for a 16-bit signed reading at that range.
ACCEL_LSB_PER_G = 16384.0     # ±2 g
GYRO_LSB_PER_DPS = 131.0      # ±250 deg/s

# USB-UART chips found on typical Nano clones, for port auto-detection.
_KNOWN_VID_PID = {
    (0x1A86, 0x7523),  # CH340
    (0x0403, 0x6001),  # FTDI FT232
    (0x10C4, 0xEA60),  # CP2102/CP2104
    (0x2341, 0x0043),  # genuine Arduino Uno/Nano (some clones)
}

PORTS = [
    PortSpec("accel.x", SCALAR, "accel.x", "motion", "g"),
    PortSpec("accel.y", SCALAR, "accel.y", "motion", "g"),
    PortSpec("accel.z", SCALAR, "accel.z", "motion", "g"),
    PortSpec("accel.mag", SCALAR, "accel.mag", "motion", "g", "~1.0 at rest; spikes on shake"),
    PortSpec("gyro.x", SCALAR, "gyro.x", "motion", "deg/s"),
    PortSpec("gyro.y", SCALAR, "gyro.y", "motion", "deg/s"),
    PortSpec("gyro.z", SCALAR, "gyro.z", "motion", "deg/s"),
    PortSpec("tilt.pitch", SCALAR, "tilt.pitch", "derived", "deg", "gravity-referenced, drift-free"),
    PortSpec("tilt.roll", SCALAR, "tilt.roll", "derived", "deg", "gravity-referenced, drift-free"),
]


def _autodetect_port():
    import serial.tools.list_ports as list_ports
    candidates = list(list_ports.comports())
    for p in candidates:
        if (p.vid, p.pid) in _KNOWN_VID_PID:
            return p.device
    for p in candidates:
        if "arduino" in (p.description or "").lower():
            return p.device
    raise RuntimeError(
        "no Arduino-like serial port found; pass one explicitly, e.g. "
        "--source bmi160:port=/dev/ttyUSB0 (Linux), COM3 (Windows), "
        "/dev/cu.usbserial-XXXX (macOS)")


@register_source
class ArduinoBMI160(Source):
    id = "bmi160"
    label = "BMI160 (Arduino Nano)"
    PORTS = PORTS
    ARGS = {
        "port": {"default": None, "type": str,
                 "help": "serial device; auto-detected if omitted"},
        "baud": {"default": 115200, "type": int,
                 "help": "must match Serial.begin() in the sketch"},
    }

    def __init__(self, port=None, baud=115200):
        self._port_arg = port
        self._baud = baud
        self._ser = None
        self._ok = False
        self._lock = threading.Lock()
        self._latest = {p.id: 0.0 for p in self.PORTS}
        self._cal_n = 0
        self._gyro_bias = [0.0, 0.0, 0.0]
        self._stop = threading.Event()
        self._thread = None
        self._frames = 0        # valid 6-int frames parsed since start
        self._unparsed = 0      # consecutive non-empty lines that didn't parse
        self._warned_format = False

        import serial  # raises ImportError if pyserial isn't installed
        self._serial_mod = serial
        # Open eagerly so a bad --source arg fails fast instead of degrading
        # to a "disconnected" module the UI silently shows no data for.
        self._open()

    # ------------------------------------------------------------------
    def _open(self):
        port = self._port_arg or _autodetect_port()
        try:
            self._ser = self._serial_mod.Serial(port, self._baud, timeout=0.5)
        except self._serial_mod.SerialException as e:
            # errno 16 (EBUSY) almost always means another program already has
            # the port open — on macOS the Arduino IDE's Serial Monitor is the
            # usual culprit, and cu.* / tty.* are the same device so either one
            # locks out the other. Say so instead of surfacing "Resource busy".
            if getattr(e, "errno", None) == 16 or "Resource busy" in str(e):
                raise RuntimeError(
                    f"{port} is busy — another program has it open. Close the "
                    "Arduino Serial Monitor (or any other serial console), then "
                    "retry.") from e
            raise
        self._port_arg = port  # remember what we resolved to, for reconnects

    def start(self):
        self._thread = threading.Thread(target=self._poll, name="bmi160", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1.0)
        if self._ser:
            try:
                self._ser.close()
            except Exception:
                pass

    def status(self):
        if not self._ok:
            return "disconnected"
        # Bytes are arriving but nothing parses as a 6-int frame — almost always
        # the wrong sketch or a baud mismatch. Say so rather than reporting "ok"
        # while every port silently reads its initial 0.
        if self._frames == 0 and self._unparsed > 0:
            return "error: receiving data but no valid frames (wrong sketch or baud?)"
        return "ok"

    def read(self):
        with self._lock:
            return dict(self._latest)

    # ------------------------------------------------------------------
    def _poll(self):
        while not self._stop.is_set():
            try:
                line = self._ser.readline()
                self._ok = True  # the port is open and readable
                if not line:
                    continue  # read timeout with nothing waiting; keep last value
                self._ingest(line)
            except Exception:
                self._ok = False
                self._reconnect()

    def _reconnect(self):
        try:
            if self._ser:
                self._ser.close()
        except Exception:
            pass
        time.sleep(1.0)
        try:
            self._open()
        except Exception:
            pass  # keep retrying on the next loop iteration

    def _ingest(self, line: bytes):
        text = line.decode("ascii", "ignore").strip()
        parts = text.split(",")
        ints = None
        if len(parts) == 6:
            try:
                ints = tuple(int(x) for x in parts)
            except ValueError:
                ints = None
        if ints is None:
            # Not a data frame. A '#'-prefixed banner from the sketch is
            # expected; anything else that keeps coming means the wrong sketch
            # or baud. Warn once (only before we've ever seen a real frame) so
            # the operator gets a pointer instead of a silent stream of zeros.
            if text and not text.startswith("#"):
                self._unparsed += 1
                if (self._frames == 0 and self._unparsed >= 20
                        and not self._warned_format):
                    self._warned_format = True
                    print(f"[bmi160] receiving data on {self._port_arg} but no "
                          f"line parses as 'ax,ay,az,gx,gy,gz' (got e.g. {text!r}). "
                          f"Wrong sketch, or baud != {self._baud}? Upload "
                          "firmware/bmi160_nano/bmi160_nano.ino.")
            return  # a banner line or a torn frame; wait for the next one
        ax, ay, az, gx, gy, gz = ints
        self._frames += 1
        self._unparsed = 0

        # calibration: first ~90 frames establish gyro bias (Nano is assumed
        # stationary at startup, same convention as plugins/joycon_r.py)
        if self._cal_n < 90:
            self._cal_n += 1
            k = 1.0 / self._cal_n
            for i, v in enumerate((gx, gy, gz)):
                self._gyro_bias[i] += k * (v - self._gyro_bias[i])

        ax_g, ay_g, az_g = (ax / ACCEL_LSB_PER_G, ay / ACCEL_LSB_PER_G, az / ACCEL_LSB_PER_G)
        gx_d = (gx - self._gyro_bias[0]) / GYRO_LSB_PER_DPS
        gy_d = (gy - self._gyro_bias[1]) / GYRO_LSB_PER_DPS
        gz_d = (gz - self._gyro_bias[2]) / GYRO_LSB_PER_DPS

        # Gravity-referenced tilt, same formula as the Joy-Con plugin. Reorient
        # the board (or swap axes here) if pitch/roll come out flipped for your
        # mounting.
        pitch = math.degrees(math.atan2(-ax_g, math.hypot(ay_g, az_g)))
        roll = math.degrees(math.atan2(ay_g, az_g))

        out = {
            "accel.x": ax_g, "accel.y": ay_g, "accel.z": az_g,
            "accel.mag": math.sqrt(ax_g * ax_g + ay_g * ay_g + az_g * az_g),
            "gyro.x": gx_d, "gyro.y": gy_d, "gyro.z": gz_d,
            "tilt.pitch": pitch, "tilt.roll": roll,
        }
        with self._lock:
            self._latest = out
