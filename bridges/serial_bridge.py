#!/usr/bin/env python3
"""Example bridge: listen to the `robot` sink's UDP/JSON feed and forward it to a
serial device (e.g. an Arduino / Pico running a firmware that accepts one line of
comma-separated axis targets).

This is deliberately outside the engine. The engine stays real-time and
protocol-ignorant; a bridge like this is where "what does my hardware actually
speak" lives. Copy it for ROS 2 (publish a JointState / Twist), Dynamixel SDK,
CAN, OSC, LeRobot, etc.

    python run.py --robot                       # engine, sending UDP to :9870
    python bridges/serial_bridge.py /dev/ttyACM0 --map axis.0,axis.1,gripper

Requires: pyserial  (pip install pyserial)
"""
from __future__ import annotations

import argparse
import json
import socket


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("port", help="serial device, e.g. /dev/ttyACM0 or COM3")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--listen", default="127.0.0.1:9870")
    ap.add_argument("--map", default="axis.0,axis.1,axis.2,axis.3,axis.4,axis.5,gripper",
                    help="comma list of sink port ids -> serial columns, in order")
    args = ap.parse_args()

    import serial  # pyserial
    keys = [k.strip() for k in args.map.split(",")]
    host, _, port = args.listen.partition(":")
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((host, int(port)))
    ser = serial.Serial(args.port, args.baud, timeout=0)
    print(f"bridge: {args.listen} -> {args.port}@{args.baud}  columns={keys}")

    state = {k: 0.0 for k in keys}
    while True:
        data, _ = sock.recvfrom(65535)
        try:
            msg = json.loads(data)
        except ValueError:
            continue
        for k in keys:
            if k in msg:
                state[k] = msg[k]
        if msg.get("estop"):
            state = {k: 0.0 for k in keys}
        line = ",".join(f"{state[k]:.4f}" for k in keys) + "\n"
        ser.write(line.encode())


if __name__ == "__main__":
    main()
