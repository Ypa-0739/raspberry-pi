"""在树莓派上检查 USB 转串口与 STM32 的协议连通性。"""

import argparse

from robot_hardware.stm32 import Command, SerialLink
from robot_hardware.stm32.messages import encode_chassis_velocity


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", required=True, help="例如 /dev/ttyUSB0 或 /dev/serial/by-id/...")
    parser.add_argument("--baudrate", type=int, default=115200)
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument("--stop", action="store_true", help="发送全机构停止命令")
    actions.add_argument(
        "--velocity",
        nargs=3,
        type=int,
        metavar=("VX", "VY", "WZ"),
        help="发送 vx/vy(mm/s) 和 wz(mrad/s)",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    with SerialLink(args.port, args.baudrate) as link:
        if args.stop:
            response = link.request(Command.STOP_ALL)
            print(f"STOP_ALL 成功，seq={response.request_sequence}")
        elif args.velocity:
            payload = encode_chassis_velocity(*args.velocity)
            response = link.request(Command.SET_CHASSIS_VELOCITY, payload)
            print(f"SET_CHASSIS_VELOCITY 成功，seq={response.request_sequence}")
        else:
            round_trip_ms = link.ping(timeout=1.0) * 1000.0
            print(f"STM32 通信正常，往返延迟 {round_trip_ms:.2f} ms")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

