"""树莓派与 STM32 之间的语义消息定义。

多字节整数统一使用小端序。COMMAND 的 payload 为 ``opcode + 参数``，
RESPONSE 的 payload 为 ``请求序号 + opcode + 状态码 + 返回数据``。
"""

from dataclasses import dataclass
from enum import IntEnum, IntFlag
import struct
from typing import ClassVar


class MessageType(IntEnum):
    """协议帧的消息类型。"""

    COMMAND = 0x10
    RESPONSE = 0x11
    TELEMETRY = 0x20
    HEARTBEAT = 0x21
    EVENT = 0x22


class TelemetryKind(IntEnum):
    """TELEMETRY payload 的首字节，用于区分不同遥测数据。"""

    OPS9_POSE = 0x01


class Ops9Status(IntFlag):
    """STM32 上报的 OPS9 状态位。"""

    VALID = 0x01
    CALIBRATED = 0x02
    CONTACT_OK = 0x04


class Command(IntEnum):
    """默认命令集；可以在 0x80~0xEF 范围添加项目命令。"""

    PING = 0x01
    STOP_ALL = 0x02
    SET_CHASSIS_VELOCITY = 0x10
    SET_SERVO_ANGLE = 0x20
    QUERY_STATUS = 0x30
    SET_TASK_CODE = 0x40


class ResponseStatus(IntEnum):
    OK = 0x00
    UNKNOWN_COMMAND = 0x01
    INVALID_LENGTH = 0x02
    INVALID_ARGUMENT = 0x03
    BUSY = 0x04
    INTERNAL_ERROR = 0x05


class EventCode(IntEnum):
    START_BUTTON_PRESSED = 0x01
    ACTION_FINISHED = 0x02
    ACTION_FAILED = 0x03
    SAFETY_STOP = 0x04


@dataclass(frozen=True)
class Response:
    """STM32 对 COMMAND 的响应。"""

    request_sequence: int
    command: int
    status: ResponseStatus
    data: bytes = b""

    _PREFIX: ClassVar[struct.Struct] = struct.Struct("<BBB")

    def encode(self) -> bytes:
        return self._PREFIX.pack(
            self.request_sequence,
            self.command,
            int(self.status),
        ) + self.data

    @classmethod
    def decode(cls, payload: bytes) -> "Response":
        if len(payload) < cls._PREFIX.size:
            raise ValueError("RESPONSE payload 至少需要 3 字节")
        sequence, command, raw_status = cls._PREFIX.unpack_from(payload)
        try:
            status = ResponseStatus(raw_status)
        except ValueError as error:
            raise ValueError(f"未知响应状态码：0x{raw_status:02X}") from error
        return cls(sequence, command, status, payload[cls._PREFIX.size :])


@dataclass(frozen=True)
class Ops9Pose:
    """STM32 转发的 OPS9 平面位姿。

    坐标单位为毫米，航向单位为毫弧度。``timestamp_ms`` 使用 STM32 的
    单调毫秒计数，可自然回绕；``quality`` 约定为 0~100。
    """

    x_mm: int
    y_mm: int
    yaw_mrad: int
    timestamp_ms: int
    quality: int
    status: Ops9Status

    _STRUCT: ClassVar[struct.Struct] = struct.Struct("<iiiIBB")

    @property
    def valid(self) -> bool:
        required = Ops9Status.VALID | Ops9Status.CALIBRATED | Ops9Status.CONTACT_OK
        return (self.status & required) == required and self.quality > 0

    def encode_telemetry(self) -> bytes:
        if not 0 <= self.timestamp_ms <= 0xFFFFFFFF:
            raise ValueError("timestamp_ms 必须在 0~4294967295 范围内")
        if not 0 <= self.quality <= 100:
            raise ValueError("quality 必须在 0~100 范围内")
        try:
            body = self._STRUCT.pack(
                self.x_mm,
                self.y_mm,
                self.yaw_mrad,
                self.timestamp_ms,
                self.quality,
                int(self.status),
            )
        except struct.error as error:
            raise ValueError("OPS9 坐标、航向或状态超出协议整数范围") from error
        return bytes((TelemetryKind.OPS9_POSE,)) + body

    @classmethod
    def decode_telemetry(cls, payload: bytes) -> "Ops9Pose":
        expected = 1 + cls._STRUCT.size
        if len(payload) != expected:
            raise ValueError(f"OPS9 TELEMETRY payload 应为 {expected} 字节")
        if payload[0] != TelemetryKind.OPS9_POSE:
            raise ValueError(f"不是 OPS9 遥测：0x{payload[0]:02X}")
        x_mm, y_mm, yaw_mrad, timestamp_ms, quality, raw_status = (
            cls._STRUCT.unpack_from(payload, 1)
        )
        if quality > 100:
            raise ValueError(f"OPS9 quality 超出 0~100：{quality}")
        return cls(
            x_mm=x_mm,
            y_mm=y_mm,
            yaw_mrad=yaw_mrad,
            timestamp_ms=timestamp_ms,
            quality=quality,
            status=Ops9Status(raw_status),
        )


def encode_command(command: int, data: bytes = b"") -> bytes:
    if not 0 <= int(command) <= 0xFF:
        raise ValueError("command 必须在 0~255 范围内")
    return bytes((int(command),)) + bytes(data)


def decode_command(payload: bytes) -> tuple[int, bytes]:
    if not payload:
        raise ValueError("COMMAND payload 不能为空")
    return payload[0], payload[1:]


def encode_chassis_velocity(vx_mm_s: int, vy_mm_s: int, wz_mrad_s: int) -> bytes:
    """编码三轴速度，范围均为有符号 16 位整数。"""

    try:
        return struct.pack("<hhh", vx_mm_s, vy_mm_s, wz_mrad_s)
    except struct.error as error:
        raise ValueError("速度值必须在 -32768~32767 范围内") from error


def encode_servo_angle(servo_id: int, angle_tenths_degree: int) -> bytes:
    """编码舵机编号和 0.1 度单位的目标角度。"""

    if not 0 <= servo_id <= 0xFF:
        raise ValueError("servo_id 必须在 0~255 范围内")
    try:
        return struct.pack("<Bh", servo_id, angle_tenths_degree)
    except struct.error as error:
        raise ValueError("angle_tenths_degree 必须为有符号 16 位整数") from error
