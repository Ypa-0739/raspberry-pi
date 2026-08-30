#ifndef RPI_UART_LINK_H
#define RPI_UART_LINK_H

#ifdef __cplusplus
extern "C" {
#endif

#include "main.h"
#include "rpi_protocol.h"

typedef enum
{
    RPI_STATUS_OK = 0x00,
    RPI_STATUS_UNKNOWN_COMMAND = 0x01,
    RPI_STATUS_INVALID_LENGTH = 0x02,
    RPI_STATUS_INVALID_ARGUMENT = 0x03,
    RPI_STATUS_BUSY = 0x04,
    RPI_STATUS_INTERNAL_ERROR = 0x05
} RpiResponseStatus;

typedef enum
{
    RPI_CMD_PING = 0x01,
    RPI_CMD_STOP_ALL = 0x02,
    RPI_CMD_SET_CHASSIS_VELOCITY = 0x10,
    RPI_CMD_SET_SERVO_ANGLE = 0x20,
    RPI_CMD_QUERY_STATUS = 0x30,
    RPI_CMD_SET_TASK_CODE = 0x40
} RpiCommand;

typedef struct
{
    uint32_t queued_frames;
    uint32_t dropped_frames;
    uint32_t transmit_errors;
    uint32_t receive_errors;
} RpiUartLinkStatistics;

HAL_StatusTypeDef RpiUartLink_Start(UART_HandleTypeDef *huart);
void RpiUartLink_Process(void);
void RpiUartLink_OnRxComplete(UART_HandleTypeDef *huart);
void RpiUartLink_OnError(UART_HandleTypeDef *huart);

HAL_StatusTypeDef RpiUartLink_Send(uint8_t message_type,
                                  const uint8_t *payload,
                                  uint16_t payload_length);

HAL_StatusTypeDef RpiUartLink_SendResponse(uint8_t request_sequence,
                                          uint8_t command,
                                          RpiResponseStatus status,
                                          const uint8_t *data,
                                          uint16_t data_length);

const RpiUartLinkStatistics *RpiUartLink_GetStatistics(void);
const RpiProtocolParser *RpiUartLink_GetParser(void);
uint32_t RpiUartLink_GetLastReceiveTick(void);

/*
 * 在项目代码中提供同名的非 weak 函数来处理命令。函数在主循环或 RTOS
 * 通信任务中调用，不在 UART 中断中调用。response_capacity 最大为 125。
 */
RpiResponseStatus RpiUartLink_HandleCommand(uint8_t command,
                                           const uint8_t *data,
                                           uint16_t data_length,
                                           uint8_t *response_data,
                                           uint16_t response_capacity,
                                           uint16_t *response_length);

/* 非 COMMAND 帧（例如 HEARTBEAT）由此可选回调处理。 */
void RpiUartLink_HandleFrame(const RpiFrame *frame);

#ifdef __cplusplus
}
#endif

#endif /* RPI_UART_LINK_H */
