# Source `joycon` — Nintendo Switch Joy-Con (R)

Reads a right Joy-Con over Bluetooth HID via `pyjoycon`. Its packages
(`joycon-python`, `hidapi`, `pyglm`) come from [`module.toml`](module.toml), so
the environment sync installs them; you only need to pair the controller.

## Pairing over Bluetooth

The Joy-Con pairs as a standard Bluetooth HID gamepad. Hold the small **round
sync button** on the rail (between SL and SR) until the lights run back and forth,
then pair from the OS:

- **Linux** — `bluetoothctl` → `scan on` → `pair <MAC>` → `connect <MAC>` → `trust <MAC>`.
  You then need read access to the hidraw node. Drop this in
  `/etc/udev/rules.d/70-joycon.rules` and `sudo udevadm control --reload && sudo udevadm trigger`:

  ```
  # Nintendo Switch Joy-Con / Pro Controller — user access to hidraw
  KERNEL=="hidraw*", KERNELS=="*057E:200[6-9]*", MODE="0660", TAG+="uaccess"
  SUBSYSTEM=="hidraw", ATTRS{idVendor}=="057e", MODE="0660", TAG+="uaccess"
  ```

  If a system service grabs the Joy-Con first (`joycond`), stop/mask it so
  `pyjoycon` can open the device: `sudo systemctl stop joycond`.

- **macOS** — pair from  System Settings ▸ Bluetooth. `hidapi` can open it with no
  extra permissions.

- **Windows** — pair from  Settings ▸ Bluetooth & devices. Works via the default
  HID driver.

Check it's visible:

```bash
python run.py --list-ports
python -c "from pyjoycon import get_R_id; print(get_R_id())"   # -> (1406, 8199, '...') when found
```

The right Joy-Con held horizontally (SL/SR up, rail to the left) is the reference
orientation for `tilt.pitch` / `tilt.roll`.

## Ports

`stick.x/y`, `accel.x/y/z`, `accel.mag`, `gyro.x/y/z`, `tilt.pitch`, `tilt.roll`,
`btn.{a,b,x,y,r,zr,sl,sr,plus,home,rstick}`.
`gyro.*` is deg/s, `accel.*` is g, `tilt.*` is gravity-referenced degrees
(drift-free), `accel.mag` ≈ 1.0 at rest and spikes on a shake.

No Joy-Con to hand? The [`mock`](../mock/) source has the same ports under the
same `joycon` id, so presets built against one run unchanged on the other.
