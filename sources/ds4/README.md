# Source `ds4` — Sony DualShock 4

Reads a DualShock 4 (v1, v2, or the Sony USB wireless adapter) as raw HID input
reports via `hidapi`, from [`module.toml`](module.toml). No controller-specific
library: the report layout is parsed in [`__init__.py`](__init__.py).

## Connecting

- **USB** — plug it in. Nothing else to do.
- **Bluetooth** — hold **SHARE + PS** until the light bar double-flashes, then pair
  from the OS (System Settings ▸ Bluetooth on macOS, `bluetoothctl` on Linux,
  Settings ▸ Bluetooth on Windows). The source switches the pad into its extended
  report mode itself, which is what turns on motion and touchpad data over BT.
- **Linux** — give your user hidraw access. Drop this in
  `/etc/udev/rules.d/70-ds4.rules` and `sudo udevadm control --reload && sudo udevadm trigger`:

  ```
  # Sony DualShock 4 — user access to hidraw (USB and Bluetooth)
  KERNEL=="hidraw*", ATTRS{idVendor}=="054c", ATTRS{idProduct}=="05c4|09cc|0ba0", MODE="0660", TAG+="uaccess"
  KERNEL=="hidraw*", KERNELS=="*054C:05C4*|*054C:09CC*", MODE="0660", TAG+="uaccess"
  ```

Check it's visible:

```bash
python -c "import hid; print([hex(d['product_id']) for d in hid.enumerate(0x054c)])"
```

More than one pad? Pass a path from that listing: `--source ds4:path=<path>`.

**Hold the pad still for the first second** after the source starts: that window
sets the gyro bias.

## Ports

| port | unit | notes |
|---|---|---|
| `lstick.x/y`, `rstick.x/y` | −1..1 | `+y` is stick pulled **down** |
| `l2`, `r2` | 0..1 | analog trigger travel |
| `accel.x/y/z`, `accel.mag` | g | `accel.mag` ≈ 1.0 at rest, spikes on a shake |
| `gyro.x/y/z` | deg/s | pitch / yaw / roll rate, bias-corrected |
| `tilt.pitch`, `tilt.roll` | deg | gravity-referenced (drift-free); 0/0 lying flat, face up |
| `touch.x/y` | 0..1 | first finger position, 0 when not touching |
| `touch.dx/dy` | touchpad px/s | first finger drag velocity (pad is 1920×942) |
| `battery` | 0..1 | |
| `btn.*` | event | `cross circle square triangle l1 r1 l2 r2 l3 r3 share options ps touchpad`, `dpad.{up,down,left,right}`, `touch` / `touch2` (finger 1 / 2 down) |

Gyro and accel use nominal scales (16 LSB per deg/s, 8192 LSB per g), not the
pad's factory calibration, so units are close but not exact. Tune with a `scale`
node in the preset.

## Preset

[`presets/ds4-mouse.json`](../../presets/ds4-mouse.json) turns the pad into a mouse:
right stick and touchpad drag move the cursor, R2 / touchpad click = left,
L2 = right, R3 = middle, L1 / R1 = back / forward, left stick scrolls, PS cycles
presets.
