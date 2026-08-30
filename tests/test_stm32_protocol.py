"""树莓派与 STM32 串口协议的无硬件测试。"""

import queue
import unittest

from robot_hardware.stm32.messages import (
    Command,
    MessageType,
    Response,
    ResponseStatus,
    encode_chassis_velocity,
    encode_command,
)
from robot_hardware.stm32.protocol import (
    Frame,
    FrameDecoder,
    ProtocolError,
    crc16_ccitt,
    decode_frame,
)
from robot_hardware.stm32.serial_link import SerialLink


class ProtocolTests(unittest.TestCase):
    def test_standard_crc_vector(self):
        self.assertEqual(crc16_ccitt(b"123456789"), 0x29B1)

    def test_frame_round_trip(self):
        original = Frame(
            MessageType.COMMAND,
            37,
            encode_command(Command.SET_CHASSIS_VELOCITY, encode_chassis_velocity(120, -30, 250)),
        )

        self.assertEqual(decode_frame(original.encode()), original)

    def test_stream_decoder_handles_noise_fragmentation_and_multiple_frames(self):
        first = Frame(MessageType.HEARTBEAT, 1, b"abcd")
        second = Frame(MessageType.EVENT, 2, b"event")
        wire = b"\x00\xFFnoise" + first.encode() + second.encode()
        decoder = FrameDecoder()

        frames = []
        for start in range(0, len(wire), 3):
            frames.extend(decoder.feed(wire[start : start + 3]))

        self.assertEqual(frames, [first, second])
        self.assertGreater(decoder.discarded_bytes, 0)

    def test_stream_decoder_recovers_after_bad_crc(self):
        damaged = bytearray(Frame(MessageType.EVENT, 3, b"bad").encode())
        damaged[-1] ^= 0x80
        good = Frame(MessageType.EVENT, 4, b"good")
        decoder = FrameDecoder()

        self.assertEqual(decoder.feed(bytes(damaged) + good.encode()), [good])
        self.assertEqual(decoder.crc_errors, 1)

    def test_decode_rejects_wrong_crc(self):
        raw = bytearray(Frame(MessageType.HEARTBEAT, 5).encode())
        raw[-1] ^= 1
        with self.assertRaisesRegex(ProtocolError, "CRC"):
            decode_frame(bytes(raw))


class _LoopbackStm32Serial:
    """收到 COMMAND 后立即构造一个 STM32 RESPONSE。"""

    def __init__(self, **kwargs):
        self.is_open = True
        self._rx = queue.Queue()

    def read(self, size=1):
        try:
            return self._rx.get(timeout=0.05)
        except queue.Empty:
            return b""

    def write(self, data):
        request = decode_frame(data)
        command = request.payload[0]
        response = Response(request.sequence, command, ResponseStatus.OK)
        self._rx.put(Frame(MessageType.RESPONSE, 90, response.encode()).encode())
        return len(data)

    def close(self):
        self.is_open = False


class SerialLinkTests(unittest.TestCase):
    def test_request_matches_response_without_pyserial_or_hardware(self):
        link = SerialLink("loopback", serial_factory=_LoopbackStm32Serial)
        with link:
            response = link.request(Command.PING, timeout=0.5)

        self.assertEqual(response.command, Command.PING)
        self.assertEqual(response.status, ResponseStatus.OK)
        self.assertEqual(link.statistics().sent_frames, 1)
        self.assertEqual(link.statistics().received_frames, 1)


if __name__ == "__main__":
    unittest.main()

