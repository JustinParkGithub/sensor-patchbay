# Source `bmi160` — Arduino Nano + BMI160

Reads a Nano running [`firmware/bmi160_nano/bmi160_nano.ino`](firmware/bmi160_nano/bmi160_nano.ino)
over USB serial — no Bluetooth, no pairing, just a cable. `pyserial` comes from
[`module.toml`](module.toml).

**Wire it up** (I2C): BMI160 `VCC`→`5V` (or `3V3`, check your breakout),
`GND`→`GND`, `SCL`→`A5`, `SDA`→`A4`.

**Flash it**: open `firmware/bmi160_nano/bmi160_nano.ino` in the Arduino IDE,
install the **BMI160-Arduino** library (Library Manager, or
https://github.com/hanyazou/BMI160-Arduino), select *Arduino Nano* as the
board, upload.

**Run it**:

```bash
python run.py --source bmi160 --preset bmi160-mouse
#   port is auto-detected; if that fails, or you have more than one board
#   plugged in, be explicit:
python run.py --source bmi160:port=/dev/ttyACM0     # Linux
python run.py --source bmi160:port=COM5             # Windows
python run.py --source bmi160:port=/dev/cu.usbserial-1420   # macOS
```

This pre-loads the `bmi160` source; add a mouse/keyboard sink (`--sink hid`, or
from the UI) to drive anything, and patch either into it. You can run several
sources at once — a second board just gets a suffixed id (`bmi160-2`). `--preset
bmi160-mouse` is a starting air-mouse mapping (`gyro.x/y` → cursor, a shake
past 2.2 g → left-click) since this board has no buttons of its own; wire up
whatever else you like in the patch panel.

**Linux serial permissions**: your user needs to be in the `dialout` group
(`sudo usermod -aG dialout $USER`, then log out/in) or the port opens with
"Permission denied".

**If ports look wrong or jump around**: the firmware sends a fixed ±2 g /
±250 deg/s range explicitly (`BMI160.setAccelerometerRange`/`setGyroRange` in
the sketch) — `ACCEL_LSB_PER_G`/`GYRO_LSB_PER_DPS` at the top of
[`__init__.py`](__init__.py) assume exactly that. Change both sides together if
you reconfigure the sensor's range. If pitch/roll are inverted for how you've
mounted the board, that's an orientation convention, not a bug — flip the axis
with an `invert` node in the patch panel rather than editing the plugin.

## Ports

`accel.x/y/z`, `accel.mag`, `gyro.x/y/z`, `tilt.pitch`, `tilt.roll`. Same units
and the same derived-tilt convention as [`joycon`](../joycon/); no buttons or
stick — it's a bare IMU.
