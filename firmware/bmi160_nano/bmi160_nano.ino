// Arduino Nano + BMI160 (I2C) -> plugins/arduino_bmi160.py
//
// Same library and the same BMI160.readGyro()/readAccelerometer() calls as
// the tutorial this is adapted from:
//   https://how2electronics.com/interfacing-bmi160-accelerometer-gyroscope-with-arduino/
// The tutorial prints one human-readable reading a second; this streams raw
// samples continuously as one CSV line each, which is what the Python side
// (plugins/arduino_bmi160.py) expects:
//
//   ax,ay,az,gx,gy,gz\n
//
// six raw signed 16-bit ints, straight off the sensor, no scaling done here
// (the host does that, from the full-scale ranges set below).
//
// Library: https://github.com/hanyazou/BMI160-Arduino  (BMI160Gen)

#include <BMI160Gen.h>
#include <Wire.h>

const int i2c_addr = 0x68;      // BMI160 default I2C address
const unsigned long SAMPLE_PERIOD_MS = 5;   // ~200 Hz

void setup() {
  Serial.begin(115200);         // must match ArduinoBMI160(baud=...) on the host

  Wire.begin();

  if (!BMI160.begin(BMI160GenClass::I2C_MODE, i2c_addr)) {
    Serial.println("# BMI160 initialization failed!");
    while (1);                  // halt; the host will see nothing but timeouts
  }

  // Fixed, explicit full-scale ranges -- plugins/arduino_bmi160.py's
  // ACCEL_LSB_PER_G / GYRO_LSB_PER_DPS constants assume exactly these.
  // Change both sides together if you need more range/resolution.
  BMI160.setAccelerometerRange(2);    // +/- 2 g
  BMI160.setGyroRange(250);           // +/- 250 deg/s

  Serial.println("# BMI160 ready");  // a '#'-prefixed line; the host skips
                                      // anything that isn't 6 comma-separated
                                      // ints, so this is harmless noise, not
                                      // part of the protocol.
}

void loop() {
  static unsigned long next = 0;
  unsigned long now = millis();
  if (now < next) return;
  next = now + SAMPLE_PERIOD_MS;

  int gx, gy, gz;
  int ax, ay, az;
  BMI160.readGyro(gx, gy, gz);
  BMI160.readAccelerometer(ax, ay, az);

  Serial.print(ax); Serial.print(',');
  Serial.print(ay); Serial.print(',');
  Serial.print(az); Serial.print(',');
  Serial.print(gx); Serial.print(',');
  Serial.print(gy); Serial.print(',');
  Serial.println(gz);
}
