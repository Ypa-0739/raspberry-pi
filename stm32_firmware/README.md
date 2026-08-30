# STM32F407 HAL 集成说明

`Comm/Inc` 和 `Comm/Src` 是可复制进 STM32CubeIDE 工程的通信层。协议核心
`rpi_protocol.c` 不依赖 HAL；`rpi_uart_link.c` 使用 HAL 中断接收并把完整帧送入
4 槽队列，命令在 `RpiUartLink_Process()` 中处理，不在中断中驱动硬件。

## 1. CubeMX 配置

选择实际接到 CP2102/FT232 的一个 USART/UART（示例使用 `USART1`）：

- Asynchronous，115200 8N1；
- TX/RX 均启用，无硬件流控；
- 打开对应 USART global interrupt；
- 生成 HAL 初始化代码，例如 `MX_USART1_UART_Init()`。

引脚复用以你们的板卡原理图和 CubeMX 为准，不要照抄往届 PCB 的引脚。

## 2. 加入文件

把以下文件加入工程，并将 `Comm/Inc` 加入编译器 include path：

```text
Comm/Inc/rpi_protocol.h
Comm/Inc/rpi_uart_link.h
Comm/Inc/rpi_app_commands.h
Comm/Inc/rpi_ops9.h
Comm/Src/rpi_protocol.c
Comm/Src/rpi_uart_link.c
Comm/Src/rpi_app_commands.c
Comm/Src/rpi_ops9.c
```

在 UART 初始化完成后启动接收：

```c
MX_USART1_UART_Init();
if (RpiUartLink_Start(&huart1) != HAL_OK)
{
    Error_Handler();
}
```

把下面两段并入现有 HAL 回调。若工程已经定义这些函数，只增加函数体里的调用，
不要再定义一份同名回调：

```c
void HAL_UART_RxCpltCallback(UART_HandleTypeDef *huart)
{
    RpiUartLink_OnRxComplete(huart);
}

void HAL_UART_ErrorCallback(UART_HandleTypeDef *huart)
{
    RpiUartLink_OnError(huart);
}
```

裸机主循环持续处理队列：

```c
while (1)
{
    RpiUartLink_Process();
    /* 其他非阻塞任务 */
}
```

使用 FreeRTOS 时，在唯一通信任务中每 1~5 ms 调一次 `RpiUartLink_Process()`。
同一个 UART 不要再被其他任务直接调用 `HAL_UART_Transmit`。

OPS9 驱动完成一帧解析后，在主循环或传感器任务中转发位姿：

```c
#include "rpi_ops9.h"

RpiOps9_SendPose(ops9_x_mm,
                 ops9_y_mm,
                 ops9_yaw_mrad,
                 HAL_GetTick(),
                 ops9_quality,
                 RPI_OPS9_STATUS_VALID |
                 RPI_OPS9_STATUS_CALIBRATED |
                 RPI_OPS9_STATUS_CONTACT_OK);
```

推荐 20 Hz 上报。OPS9 原始帧格式、串口号和清零方式仍由实际 OPS9 型号的驱动
负责；`rpi_ops9.c` 只统一 STM32 到树莓派的数据格式。

## 3. 绑定底盘函数

`rpi_app_commands.c` 已完成参数长度检查和小端解析。请在自己的应用 `.c` 文件中
提供以下非 weak 函数，覆盖默认安全实现：

```c
#include "rpi_app_commands.h"

RpiResponseStatus RpiApp_StopAll(void)
{
    Chassis_Stop();
    Manipulator_Stop();
    return RPI_STATUS_OK;
}

RpiResponseStatus RpiApp_SetChassisVelocity(int16_t vx,
                                            int16_t vy,
                                            int16_t wz)
{
    if ((vx < -1000) || (vx > 1000) ||
        (vy < -1000) || (vy > 1000) ||
        (wz < -3000) || (wz > 3000))
    {
        return RPI_STATUS_INVALID_ARGUMENT;
    }
    Chassis_SetVelocity(vx, vy, wz); /* 替换为你们的真实函数 */
    return RPI_STATUS_OK;
}
```

未覆盖钩子时会返回 `INTERNAL_ERROR`，不会假装动作已经成功。`PING` 不依赖底盘
钩子，可先用于接线测试。

## 4. 通信失联保护

树莓派端默认每 100 ms 发送 HEARTBEAT。底盘使能后，应在安全任务里检查最近有效
帧时间；建议连续 300 ms 未收到帧就立即停止，具体阈值再按现场测试调整：

```c
if (motors_enabled &&
    ((uint32_t)(HAL_GetTick() - RpiUartLink_GetLastReceiveTick()) > 300U))
{
    Chassis_Stop();
    Manipulator_Stop();
    motors_enabled = 0U;
}
```

该保护属于 STM32 本地安全逻辑，不能依赖树莓派发 STOP。协议说明和树莓派用法见
[`robot_hardware/stm32/README.md`](../robot_hardware/stm32/README.md)。
