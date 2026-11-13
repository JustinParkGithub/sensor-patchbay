import math
import sys
import time
from pynput.mouse import Controller
import serial

mouse = Controller()

# =============================================================================
# Configuration
# =============================================================================
PORT = "/dev/cu.usbmodem2101"  # Replace with your Arduino port
BAUD_RATE = 115200

# Sensitivity and Deadzone
SENSITIVITY = 0.35  # Multiplier for degrees/second -> pixels
DEADZONE = 1.5  # Minimum degrees/second to prevent drift

# Kalman Filter Tuning Parameters
# - Increase R_MEAS (e.g., 8.0 - 20.0) for heavier smoothing / less jitter
# - Increase Q_ACCEL (e.g., 50.0 - 150.0) for snappier response to fast flicks
Q_RATE = 0.05  # Process noise variance for angular velocity
Q_ACCEL = 40.0  # Process noise variance for angular acceleration
R_MEAS = 6.0  # Measurement noise variance (gyro sensor noise)

# Automatic Stationary Gyro Bias Calibration
STATIONARY_GYRO_THRESH = 2.5  # deg/s threshold to consider IMU stationary
GRAVITY_TOLERANCE = 0.15  # Allowed deviation from 1g for stationary check
BIAS_ALPHA = 0.01  # Adaptation rate for slow gyro bias drift


class KinematicKalman1D:
  """2-state constant-acceleration Kalman Filter for 1D angular velocity.

  State vector: x = [rate (deg/s), angular_accel (deg/s^2)]^T Tracks both angular
  rate and its derivative so steady motions are heavily smoothed while intentional
  flicks pass through with minimal phase lag.
  """

  def __init__(self, q_rate=Q_RATE, q_accel=Q_ACCEL, r_meas=R_MEAS):
    self.q_rate = q_rate
    self.q_accel = q_accel
    self.r_meas = r_meas

    # State estimate: [rate, accel]
    self.rate = 0.0
    self.accel = 0.0

    # 2x2 Error covariance matrix P
    self.p00 = 1.0
    self.p01 = 0.0
    self.p10 = 0.0
    self.p11 = 1.0

  def update(self, measured_rate: float, dt: float) -> float:
    # Clamp dt to guard against serial stalls or OS scheduling hiccups
    if dt <= 0.0 or dt > 0.1:
      dt = 0.01

    # -----------------------------------------------------------------
    # 1. Predict Step: x_k|k-1 = F * x_k-1,  P_k|k-1 = F * P * F^T + Q
    #    F = [[1, dt],
    #         [0,  1]]
    # -----------------------------------------------------------------
    self.rate += dt * self.accel

    p00_pred = (
        self.p00 + dt * (self.p10 + self.p01) + (dt * dt) * self.p11 + self.q_rate
    )
    p01_pred = self.p01 + dt * self.p11
    p10_pred = self.p10 + dt * self.p11
    p11_pred = self.p11 + self.q_accel

    # -----------------------------------------------------------------
    # 2. Update Step: H = [1, 0]
    #    y = z - H * x_pred
    #    S = H * P_pred * H^T + R = p00_pred + R
    #    K = P_pred * H^T / S
    # -----------------------------------------------------------------
    innovation = measured_rate - self.rate
    s = p00_pred + self.r_meas

    k0 = p00_pred / s
    k1 = p10_pred / s

    # Update state estimate
    self.rate += k0 * innovation
    self.accel += k1 * innovation

    # Update error covariance: P = (I - K * H) * P_pred
    self.p00 = (1.0 - k0) * p00_pred
    self.p01 = (1.0 - k0) * p01_pred
    self.p10 = p10_pred - k1 * p00_pred
    self.p11 = p11_pred - k1 * p01_pred

    return self.rate


def apply_soft_deadzone(value: float, deadzone: float) -> float:
  """Subtracts the deadzone continuously instead of jumping from 0 to deadzone,

  eliminating the 'step' jerk when starting or stopping slow movements.
  """
  if abs(value) <= deadzone:
    return 0.0
  return math.copysign(abs(value) - deadzone, value)


def main():
  try:
    ser = serial.Serial(PORT, BAUD_RATE, timeout=1.0)
    time.sleep(2)  # Wait for serial reset
    ser.reset_input_buffer()
    print(f"Connected to {PORT}. Press Ctrl+C in terminal to stop.")
  except serial.SerialException as e:
    print(f"Error opening serial port: {e}")
    sys.exit(1)

  # Separate Kalman filter per screen axis
  kf_x = KinematicKalman1D(q_rate=Q_RATE, q_accel=Q_ACCEL, r_meas=R_MEAS)
  kf_y = KinematicKalman1D(q_rate=Q_RATE, q_accel=Q_ACCEL, r_meas=R_MEAS)

  # Adaptive gyro bias estimates (deg/s)
  bias_gx = 0.0
  bias_gy = 0.0

  # Sub-pixel remainder accumulators to prevent int() truncation stutter
  rem_x = 0.0
  rem_y = 0.0

  last_time = time.perf_counter()

  while True:
    try:
      raw_line = ser.readline().decode("utf-8", errors="ignore").strip()
      if not raw_line or raw_line.startswith(
          ("aX", "[", "Failed", "Re-init", "Accelerometer")
      ):
        continue

      parts = raw_line.split(",")
      if len(parts) != 6:
        continue

      # aX, aY, aZ (g), gX, gY, gZ (deg/s)
      ax, ay, az, gx, gy, gz = map(float, parts)

      now = time.perf_counter()
      dt = now - last_time
      last_time = now

      # Update gyro bias slowly when IMU is stationary (~1g total acceleration
      # and minimal rotation across all 3 axes)
      accel_mag = math.sqrt(ax * ax + ay * ay + az * az)
      is_stationary = (
          abs(accel_mag - 1.0) < GRAVITY_TOLERANCE
          and abs(gx - bias_gx) < STATIONARY_GYRO_THRESH
          and abs(gy - bias_gy) < STATIONARY_GYRO_THRESH
          and abs(gz) < STATIONARY_GYRO_THRESH
      )
      if is_stationary:
        bias_gx = (1.0 - BIAS_ALPHA) * bias_gx + BIAS_ALPHA * gx
        bias_gy = (1.0 - BIAS_ALPHA) * bias_gy + BIAS_ALPHA * gy

      # Bias-corrected raw angular rates mapped to screen axes
      # (Matching starter code: screen X <- -gx, screen Y <- -gy)
      raw_rate_x = -(gx - bias_gx)
      raw_rate_y = -(gy - bias_gy)

      # 1. Kalman Filter smoothing on angular rates
      filt_rate_x = kf_x.update(raw_rate_x, dt)
      filt_rate_y = kf_y.update(raw_rate_y, dt)

      # 2. Soft deadzone (avoids sudden jump when crossing DEADZONE)
      clean_rate_x = apply_soft_deadzone(filt_rate_x, DEADZONE)
      clean_rate_y = apply_soft_deadzone(filt_rate_y, DEADZONE)

      # 3. Sub-pixel accumulation for ultra-smooth low-speed motion
      rem_x += clean_rate_x * SENSITIVITY
      rem_y += clean_rate_y * SENSITIVITY

      move_x = int(rem_x)
      move_y = int(rem_y)

      if move_x != 0 or move_y != 0:
        rem_x -= move_x
        rem_y -= move_y
        mouse.move(move_x, move_y)

    except ValueError:
      continue
    except KeyboardInterrupt:
      print("\nStopped by user.")
      break

  ser.close()


if __name__ == "__main__":
  main()