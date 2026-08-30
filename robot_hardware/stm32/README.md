# 树莓派—STM32 USB 转串口通信

本目录是树莓派端实现；STM32F407 HAL 文件位于
[`stm32_firmware/Comm`](../../stm32_firmware/Comm)。默认参数为 115200、8 数据位、
无校验、1 停止位、无硬件流控（115200 8N1）。

## 接线

```text
树莓派 USB ── USB插头 [CP2102/FT232] TTL_TXD ── STM32 UART_RX
                                      TTL_RXD ── STM32 UART_TX
                                      GND     ── STM32 GND
```

- TTL 电平必须设为 **3.3 V**。部分 FT232 板有 3.3 V/5 V 跳帽，必须确认位置。
- TX/RX 交叉连接并共地。
- 转串口板已经由树莓派 USB 供电，通常不要连接其 VCC/5V 到 STM32，避免两套
  电源互相反灌。
- 这里使用的是 STM32 硬件 UART，不是 STM32 的 USB D+/D- 接口。

## 帧格式

所有多字节字段均为小端序，最大 payload 为 128 字节，最大整帧为 137 字节。

| 偏移 | 长度 | 字段 | 说明 |
|---:|---:|---|---|
| 0 | 2 | SOF | 固定 `A5 5A` |
| 2 | 1 | version | 当前为 `01` |
| 3 | 1 | message_type | COMMAND/RESPONSE/TELEMETRY/HEARTBEAT/EVENT |
| 4 | 1 | sequence | 0~255 循环 |
| 5 | 2 | payload_length | 0~128 |
| 7 | N | payload | 消息数据 |
| 7+N | 2 | CRC16 | CRC-16/CCITT-FALSE，覆盖 version 到 payload |

COMMAND payload 是 `command(1) + data(N)`；RESPONSE payload 是
`request_sequence(1) + command(1) + status(1) + data(N)`。响应内携带请求序号，
树莓派可以在连续发命令时正确匹配结果。

默认命令：

| 命令 | 值 | data |
|---|---:|---|
| PING | `01` | 无 |
| STOP_ALL | `02` | 无 |
| SET_CHASSIS_VELOCITY | `10` | `vx:int16, vy:int16, wz:int16`；mm/s、mrad/s |
| SET_SERVO_ANGLE | `20` | `servo_id:uint8, angle:int16`；角度单位 0.1° |
| QUERY_STATUS | `30` | 无，返回数据由底盘定义 |
| SET_TASK_CODE | `40` | 1~31 字节 ASCII，例如 `452+321+254+312` |

项目扩展命令建议使用 `0x80~0xEF`，并同时更新 Python 与 C 两端枚举。

OPS9 不直接连接树莓派。STM32 读取 OPS9 后，以 20 Hz 左右发送
`message_type=TELEMETRY(0x20)`，payload 固定为：

| 偏移 | 类型 | 字段 | 单位/说明 |
|---:|---|---|---|
| 0 | uint8 | telemetry_kind | `0x01` 表示 OPS9_POSE |
| 1 | int32 | x | mm |
| 5 | int32 | y | mm |
| 9 | int32 | yaw | mrad |
| 13 | uint32 | timestamp | STM32 单调毫秒计数 |
| 17 | uint8 | quality | 0~100 |
| 18 | uint8 | status | bit0有效、bit1已标定、bit2通信正常 |

树莓派通过 `Stm32Ops9Receiver` 订阅这类帧。质量低、状态位不全或超过
`config/ops9.json` 的 250 ms 新鲜度限制时，导航器会停车而不是外推旧位姿。

## 树莓派使用

安装依赖并查找稳定设备名：

```bash
python3 -m pip install -r requirements-hardware.txt
ls -l /dev/serial/by-id/
sudo usermod -aG dialout "$USER"
```

加入 `dialout` 组后需要重新登录。优先把 `/dev/serial/by-id/...` 写入
[`config/stm32.json`](../../config/stm32.json)，不要长期依赖可能变化的
`/dev/ttyUSB0`。

只测试协议连通性（STM32 默认 weak 处理器已经支持 PING）：

```bash
python3 -m tools.stm32_link_test --port /dev/serial/by-id/你的设备名
```

代码示例：

```python
from robot_hardware.stm32 import Command, SerialLink
from robot_hardware.stm32.messages import encode_chassis_velocity

with SerialLink("/dev/serial/by-id/你的设备名") as link:
    print(f"RTT={link.ping() * 1000:.1f} ms")
    link.request(
        Command.SET_CHASSIS_VELOCITY,
        encode_chassis_velocity(200, 0, 0),
    )
```

`SerialLink` 启动唯一接收线程，处理粘包、拆包、CRC、响应匹配、100 ms 心跳和
USB 短暂掉线后的重连。动作命令不会自动重发，以免机械动作执行两次。

查看 STM32 实际上报的 OPS9 数据：

```bash
python3 -m tools.stm32_ops9_monitor
```

## 设计约束

- 整个程序只能创建一个 `SerialLink` 实例持有该设备。
- UART 断连或心跳超时后，STM32 应独立停止底盘和执行机构，不能等待树莓派恢复。
- TELEMETRY 只能用于状态观测，不应绕过实体 Start 按钮远程启动比赛流程。
- 往届 `0x66...0x77` 示例没有长度、序号和强校验；新代码使用本页协议，不混用。
