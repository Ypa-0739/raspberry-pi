#ifndef RPI_APP_COMMANDS_H
#define RPI_APP_COMMANDS_H

#ifdef __cplusplus
extern "C" {
#endif

#include "rpi_uart_link.h"

/*
 * 以下钩子由底盘项目实现。默认 weak 实现返回 INTERNAL_ERROR，避免在尚未
 * 接入电机/舵机时向树莓派误报执行成功。
 */
RpiResponseStatus RpiApp_StopAll(void);
RpiResponseStatus RpiApp_SetChassisVelocity(int16_t vx_mm_s,
                                            int16_t vy_mm_s,
                                            int16_t wz_mrad_s);
RpiResponseStatus RpiApp_SetServoAngle(uint8_t servo_id,
                                      int16_t angle_tenths_degree);
RpiResponseStatus RpiApp_QueryStatus(uint8_t *output,
                                    uint16_t output_capacity,
                                    uint16_t *output_length);
RpiResponseStatus RpiApp_SetTaskCode(const uint8_t *ascii_code,
                                    uint16_t code_length);

#ifdef __cplusplus
}
#endif

#endif /* RPI_APP_COMMANDS_H */

