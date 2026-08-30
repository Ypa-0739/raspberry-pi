#include "rpi_app_commands.h"

#include <stddef.h>

static int16_t read_i16_le(const uint8_t *data)
{
    return (int16_t)((uint16_t)data[0] | ((uint16_t)data[1] << 8));
}

RpiResponseStatus RpiUartLink_HandleCommand(uint8_t command,
                                           const uint8_t *data,
                                           uint16_t data_length,
                                           uint8_t *response_data,
                                           uint16_t response_capacity,
                                           uint16_t *response_length)
{
    if (response_length == NULL)
    {
        return RPI_STATUS_INTERNAL_ERROR;
    }
    *response_length = 0U;

    switch (command)
    {
        case RPI_CMD_PING:
            return (data_length == 0U) ?
                   RPI_STATUS_OK : RPI_STATUS_INVALID_LENGTH;

        case RPI_CMD_STOP_ALL:
            if (data_length != 0U)
            {
                return RPI_STATUS_INVALID_LENGTH;
            }
            return RpiApp_StopAll();

        case RPI_CMD_SET_CHASSIS_VELOCITY:
            if (data_length != 6U)
            {
                return RPI_STATUS_INVALID_LENGTH;
            }
            return RpiApp_SetChassisVelocity(read_i16_le(&data[0]),
                                             read_i16_le(&data[2]),
                                             read_i16_le(&data[4]));

        case RPI_CMD_SET_SERVO_ANGLE:
            if (data_length != 3U)
            {
                return RPI_STATUS_INVALID_LENGTH;
            }
            return RpiApp_SetServoAngle(data[0], read_i16_le(&data[1]));

        case RPI_CMD_QUERY_STATUS:
            if (data_length != 0U)
            {
                return RPI_STATUS_INVALID_LENGTH;
            }
            return RpiApp_QueryStatus(response_data,
                                      response_capacity,
                                      response_length);

        case RPI_CMD_SET_TASK_CODE:
            if ((data_length == 0U) || (data_length > 31U))
            {
                return RPI_STATUS_INVALID_LENGTH;
            }
            return RpiApp_SetTaskCode(data, data_length);

        default:
            return RPI_STATUS_UNKNOWN_COMMAND;
    }
}

__weak RpiResponseStatus RpiApp_StopAll(void)
{
    return RPI_STATUS_INTERNAL_ERROR;
}

__weak RpiResponseStatus RpiApp_SetChassisVelocity(int16_t vx_mm_s,
                                                   int16_t vy_mm_s,
                                                   int16_t wz_mrad_s)
{
    (void)vx_mm_s;
    (void)vy_mm_s;
    (void)wz_mrad_s;
    return RPI_STATUS_INTERNAL_ERROR;
}

__weak RpiResponseStatus RpiApp_SetServoAngle(uint8_t servo_id,
                                             int16_t angle_tenths_degree)
{
    (void)servo_id;
    (void)angle_tenths_degree;
    return RPI_STATUS_INTERNAL_ERROR;
}

__weak RpiResponseStatus RpiApp_QueryStatus(uint8_t *output,
                                           uint16_t output_capacity,
                                           uint16_t *output_length)
{
    (void)output;
    (void)output_capacity;
    *output_length = 0U;
    return RPI_STATUS_INTERNAL_ERROR;
}

__weak RpiResponseStatus RpiApp_SetTaskCode(const uint8_t *ascii_code,
                                           uint16_t code_length)
{
    (void)ascii_code;
    (void)code_length;
    return RPI_STATUS_INTERNAL_ERROR;
}

