"""树莓派端单实例串口链路。

需要树莓派安装 ``pyserial``。模块采用后台接收线程，负责拆包、响应匹配，
并在 USB 转串口短暂掉线后尝试重连。
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
import queue
import struct
import threading
import time
from typing import Callable, Dict, List, Optional, Protocol

from .messages import (
    Command,
    MessageType,
    Response,
    ResponseStatus,
    encode_command,
)
from .protocol import Frame, FrameDecoder


LOGGER = logging.getLogger(__name__)


class SerialPort(Protocol):
    is_open: bool

    def read(self, size: int = 1) -> bytes: ...

    def write(self, data: bytes) -> int: ...

    def close(self) -> None: ...


class SerialLinkError(RuntimeError):
    pass


class CommandTimeout(SerialLinkError):
    pass


class CommandRejected(SerialLinkError):
    def __init__(self, response: Response) -> None:
        self.response = response
        super().__init__(
            f"STM32 拒绝命令 0x{response.command:02X}：{response.status.name}"
        )


@dataclass(frozen=True)
class LinkStatistics:
    received_frames: int
    sent_frames: int
    reconnects: int
    crc_errors: int
    discarded_bytes: int


class SerialLink:
    """独占一个 USB 串口的双向通信组件。"""

    def __init__(
        self,
        port: str,
        baudrate: int = 115200,
        *,
        read_timeout: float = 0.05,
        reconnect_interval: float = 1.0,
        heartbeat_interval: Optional[float] = 0.1,
        serial_factory: Optional[Callable[..., SerialPort]] = None,
    ) -> None:
        if not port:
            raise ValueError("port 不能为空")
        if baudrate <= 0:
            raise ValueError("baudrate 必须大于 0")
        self.port = port
        self.baudrate = baudrate
        self.read_timeout = read_timeout
        self.reconnect_interval = reconnect_interval
        if heartbeat_interval is not None and heartbeat_interval <= 0:
            raise ValueError("heartbeat_interval 必须大于 0 或为 None")
        self.heartbeat_interval = heartbeat_interval
        self._serial_factory = serial_factory
        self._serial: Optional[SerialPort] = None
        self._decoder = FrameDecoder()
        self._stop_event = threading.Event()
        self._connected_event = threading.Event()
        self._reader_thread: Optional[threading.Thread] = None
        self._tx_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._pending_lock = threading.Lock()
        self._pending: Dict[int, queue.Queue[Response]] = {}
        self._incoming: queue.Queue[Frame] = queue.Queue()
        self._handler_lock = threading.Lock()
        self._frame_handlers: Dict[int, List[Callable[[Frame], bool]]] = {}
        self._next_sequence = 0
        self._received_frames = 0
        self._sent_frames = 0
        self._reconnects = 0
        self._started_at = 0.0
        self._next_heartbeat = 0.0

    @property
    def connected(self) -> bool:
        return self._connected_event.is_set()

    def open(self) -> None:
        """首次同步打开串口，然后启动后台接收线程。"""

        if self._reader_thread and self._reader_thread.is_alive():
            return
        self._stop_event.clear()
        self._connect()
        self._started_at = time.monotonic()
        self._schedule_next_heartbeat()
        self._reader_thread = threading.Thread(
            target=self._reader_loop,
            name="stm32-serial-reader",
            daemon=True,
        )
        self._reader_thread.start()

    def close(self) -> None:
        self._stop_event.set()
        self._disconnect()
        thread = self._reader_thread
        if thread and thread is not threading.current_thread():
            thread.join(timeout=max(1.0, self.read_timeout * 3))
        self._reader_thread = None
        with self._pending_lock:
            self._pending.clear()

    def __enter__(self) -> "SerialLink":
        self.open()
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()

    def send(self, message_type: int, payload: bytes = b"") -> int:
        sequence = self._allocate_sequence()
        self.send_frame(Frame(message_type, sequence, payload))
        return sequence

    def send_frame(self, frame: Frame) -> None:
        raw = frame.encode()
        with self._tx_lock:
            serial_port = self._serial
            if serial_port is None or not serial_port.is_open:
                raise SerialLinkError(f"串口未连接：{self.port}")
            try:
                written = serial_port.write(raw)
            except Exception as error:
                self._disconnect()
                raise SerialLinkError(f"写入串口失败：{error}") from error
            if written != len(raw):
                raise SerialLinkError(f"串口只写入 {written}/{len(raw)} 字节")
            self._sent_frames += 1

    def send_command(self, command: int, data: bytes = b"") -> int:
        return self.send(MessageType.COMMAND, encode_command(command, data))

    def request(
        self,
        command: int,
        data: bytes = b"",
        *,
        timeout: float = 0.5,
    ) -> Response:
        """发送命令并等待匹配响应。

        不自动重发，以免底盘运动或机械臂动作被重复执行。调用方只应对确认
        幂等的命令自行重试。
        """

        sequence = self._allocate_sequence()
        response_queue: queue.Queue[Response] = queue.Queue(maxsize=1)
        with self._pending_lock:
            self._pending[sequence] = response_queue
        try:
            self.send_frame(
                Frame(MessageType.COMMAND, sequence, encode_command(command, data))
            )
            try:
                response = response_queue.get(timeout=timeout)
            except queue.Empty as error:
                raise CommandTimeout(
                    f"等待 STM32 响应超时：command=0x{int(command):02X}, seq={sequence}"
                ) from error
        finally:
            with self._pending_lock:
                self._pending.pop(sequence, None)
        if response.command != int(command):
            raise SerialLinkError(
                f"响应命令不匹配：期望 0x{int(command):02X}，收到 0x{response.command:02X}"
            )
        if response.status != ResponseStatus.OK:
            raise CommandRejected(response)
        return response

    def ping(self, timeout: float = 0.5) -> float:
        """测量一次请求/响应往返时间，返回秒数。"""

        started = time.monotonic()
        self.request(Command.PING, timeout=timeout)
        return time.monotonic() - started

    def receive(self, timeout: Optional[float] = None) -> Frame:
        """读取未被 request 消费的遥测、事件或心跳帧。"""

        try:
            return self._incoming.get(timeout=timeout)
        except queue.Empty as error:
            raise TimeoutError("等待 STM32 消息超时") from error

    def add_frame_handler(
        self,
        message_type: int,
        handler: Callable[[Frame], bool],
    ) -> None:
        """订阅非应答帧；回调返回 True 表示已消费，不再放入公共队列。"""

        with self._handler_lock:
            handlers = self._frame_handlers.setdefault(int(message_type), [])
            if handler not in handlers:
                handlers.append(handler)

    def remove_frame_handler(
        self,
        message_type: int,
        handler: Callable[[Frame], bool],
    ) -> None:
        with self._handler_lock:
            handlers = self._frame_handlers.get(int(message_type))
            if not handlers:
                return
            if handler in handlers:
                handlers.remove(handler)
            if not handlers:
                self._frame_handlers.pop(int(message_type), None)

    def send_heartbeat(self, uptime_ms: int) -> int:
        return self.send(MessageType.HEARTBEAT, struct.pack("<I", uptime_ms & 0xFFFFFFFF))

    def statistics(self) -> LinkStatistics:
        return LinkStatistics(
            received_frames=self._received_frames,
            sent_frames=self._sent_frames,
            reconnects=self._reconnects,
            crc_errors=self._decoder.crc_errors,
            discarded_bytes=self._decoder.discarded_bytes,
        )

    def _allocate_sequence(self) -> int:
        with self._state_lock:
            sequence = self._next_sequence
            self._next_sequence = (self._next_sequence + 1) & 0xFF
            return sequence

    def _default_serial_factory(self, **kwargs: object) -> SerialPort:
        try:
            import serial  # type: ignore[import-not-found]
        except ImportError as error:
            raise SerialLinkError(
                "缺少 pyserial，请执行：python3 -m pip install pyserial"
            ) from error
        return serial.Serial(**kwargs)

    def _connect(self) -> None:
        factory = self._serial_factory or self._default_serial_factory
        try:
            serial_port = factory(
                port=self.port,
                baudrate=self.baudrate,
                bytesize=8,
                parity="N",
                stopbits=1,
                timeout=self.read_timeout,
                write_timeout=0.5,
            )
        except SerialLinkError:
            raise
        except Exception as error:
            raise SerialLinkError(f"无法打开串口 {self.port}：{error}") from error
        with self._state_lock:
            self._serial = serial_port
            self._decoder.reset()
            self._connected_event.set()

    def _disconnect(self) -> None:
        with self._state_lock:
            serial_port, self._serial = self._serial, None
            self._connected_event.clear()
        if serial_port is not None:
            try:
                serial_port.close()
            except Exception:
                LOGGER.debug("关闭串口失败", exc_info=True)

    def _reader_loop(self) -> None:
        while not self._stop_event.is_set():
            serial_port = self._serial
            if serial_port is None:
                if self._stop_event.wait(self.reconnect_interval):
                    break
                try:
                    self._connect()
                    self._reconnects += 1
                    self._schedule_next_heartbeat()
                    LOGGER.info("STM32 串口已重连：%s", self.port)
                except SerialLinkError:
                    LOGGER.warning("STM32 串口重连失败：%s", self.port)
                continue
            try:
                data = serial_port.read(256)
            except Exception:
                LOGGER.exception("读取 STM32 串口失败，将尝试重连")
                self._disconnect()
                continue
            for frame in self._decoder.feed(data):
                self._received_frames += 1
                self._dispatch(frame)
            self._send_heartbeat_if_due()

    def _schedule_next_heartbeat(self) -> None:
        if self.heartbeat_interval is not None:
            self._next_heartbeat = time.monotonic() + self.heartbeat_interval

    def _send_heartbeat_if_due(self) -> None:
        if self.heartbeat_interval is None or time.monotonic() < self._next_heartbeat:
            return
        uptime_ms = int((time.monotonic() - self._started_at) * 1000.0)
        try:
            self.send_heartbeat(uptime_ms)
        except SerialLinkError:
            LOGGER.warning("发送 STM32 心跳失败，将尝试重连")
        finally:
            self._schedule_next_heartbeat()

    def _dispatch(self, frame: Frame) -> None:
        if frame.message_type == MessageType.RESPONSE:
            try:
                response = Response.decode(frame.payload)
            except ValueError:
                LOGGER.warning("收到格式错误的 RESPONSE", exc_info=True)
            else:
                with self._pending_lock:
                    response_queue = self._pending.get(response.request_sequence)
                if response_queue is not None:
                    try:
                        response_queue.put_nowait(response)
                    except queue.Full:
                        LOGGER.warning("重复的 RESPONSE：seq=%d", response.request_sequence)
                    return
                LOGGER.debug("丢弃未等待的 RESPONSE：seq=%d", response.request_sequence)
                return
        with self._handler_lock:
            handlers = tuple(self._frame_handlers.get(int(frame.message_type), ()))
        handled = False
        for handler in handlers:
            try:
                handled = handler(frame) or handled
            except Exception:
                LOGGER.exception("STM32 帧订阅回调执行失败")
        if not handled:
            self._incoming.put(frame)
