#ifndef TEST_STM32_MAIN_H
#define TEST_STM32_MAIN_H

#include <stdint.h>

typedef struct
{
    uint8_t unused;
} UART_HandleTypeDef;

typedef int HAL_StatusTypeDef;

#define HAL_OK 0
#define HAL_ERROR 1

#endif /* TEST_STM32_MAIN_H */
