import serial
import sys
import time
from pynput.mouse import Controller

mouse = Controller()

PORT = "/dev/cu.usbmodem2101"
BAUD_RATE = 115200

# Tuning parameters
ACCEL_SENSITIVITY = 180.0   # Scales acceleration impulse to cursor speed
ACCEL_DEADZONE = 0.04       # Adjust based on your IMU units (g vs m/s^2)
FRICTION_DECAY = 0.82       # 0.0 to 0.95: lower = snappier stop, higher = smoother glide
ALPHA = 0.95                # High-pass filter constant for removing slow bias/tilt drift

def calibrate(ser, samples=100):
    print("Keep IMU flat and still for calibration...")
    sum_x, sum_y = 0.0, 0.0
    count = 0
    while count < samples:
        line = ser.readline().decode("utf-8", errors="ignore").strip()
        parts = line.split(",")
        if len(parts) == 6:
            try:
                ax, ay = float(parts[0]), float(parts[1])
                sum_x += ax
                sum_y += ay
                count += 1
            except ValueError:
                continue
    return sum_x / samples, sum_y / samples

def main():
    try:
        ser = serial.Serial(PORT, BAUD_RATE, timeout=1.0)
        time.sleep(2)
    except serial.SerialException as e:
        print(f"Error opening serial port: {e}")
        sys.exit(1)

    baseline_x, baseline_y = calibrate(ser)
    vx, vy = 0.0, 0.0
    still_frames = 0
    print("Ready! Slide flat on desk.")

    while True:
        try:
            raw_line = ser.readline().decode("utf-8", errors="ignore").strip()
            parts = raw_line.split(",")
            if len(parts) != 6:
                continue

            ax, ay, _, _, _, _ = map(float, parts)

            # 1. Slowly adapt baseline to cancel thermal/tilt drift
            baseline_x = ALPHA * baseline_x + (1 - ALPHA) * ax
            baseline_y = ALPHA * baseline_y + (1 - ALPHA) * ay

            lin_ax = ax - baseline_x
            lin_ay = ay - baseline_y

            # 2. Deadzone gate
            if abs(lin_ax) < ACCEL_DEADZONE:
                lin_ax = 0.0
            if abs(lin_ay) < ACCEL_DEADZONE:
                lin_ay = 0.0

            # 3. Directional Latching + Leaky Integration
            # Only apply acceleration if we are stopped OR pushing in the SAME direction
            if vx == 0.0 or (lin_ax * vx) > 0:
                vx = (vx * FRICTION_DECAY) + (lin_ax * ACCEL_SENSITIVITY)
            else:
                # We are decelerating/braking: ignore reverse spike and just let friction bleed speed
                vx = vx * (FRICTION_DECAY * 0.85)

            if vy == 0.0 or (lin_ay * vy) > 0:
                vy = (vy * FRICTION_DECAY) + (lin_ay * ACCEL_SENSITIVITY)
            else:
                vy = vy * (FRICTION_DECAY * 0.85)

            # Snap tiny residual velocity to zero so you can immediately swipe the opposite way next
            if abs(vx) < 0.5:
                vx = 0.0
            if abs(vy) < 0.5:
                vy = 0.0

            # 4. Snap to zero if stationary for a few frames
            if lin_ax == 0.0 and lin_ay == 0.0:
                still_frames += 1
                if still_frames > 4:
                    vx, vy = 0.0, 0.0
            else:
                still_frames = 0

            # Invert signs as needed to match your sensor's physical orientation
            move_x = int(vy)
            move_y = int(vx)

            if move_x != 0 or move_y != 0:
                mouse.move(move_x, move_y)

        except ValueError:
            continue
        except KeyboardInterrupt:
            print("\nStopped.")
            break

    ser.close()

if __name__ == "__main__":
    main()