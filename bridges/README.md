# bridges/

A bridge consumes the `robot` sink's UDP/JSON feed (`python run.py --robot`) and
translates it to real hardware. The engine never imports these — they run as
separate processes and can live on another machine.

- `serial_bridge.py` — UDP → pyserial (Arduino/Pico expecting a CSV line). Copy
  this for ROS 2 (`JointState`/`Twist` publisher), Dynamixel SDK, CAN, OSC, LeRobot.

Datagram shape (one per engine tick, ~100 Hz):

    {"t": 12.34, "axis.0": 0.12, "axis.1": -0.4, "gripper": 1.0}

`{"estop": 1, ...}` is sent once on PANIC / shutdown so a bridge can safe the arm.
