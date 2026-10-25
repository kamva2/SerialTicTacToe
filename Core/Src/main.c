/* USER CODE BEGIN Header */
/**
  ******************************************************************************
  * @file           : main.c
  * @brief          : Serial Tic-Tac-Toe server
  ******************************************************************************
  * @attention
  *
  * Copyright (c) 2026 STMicroelectronics.
  * All rights reserved.
  *
  * This software is licensed under terms that can be found in the LICENSE file
  * in the root directory of this software component.
  * If no LICENSE file comes with this software, it is provided AS-IS.
  *
  ******************************************************************************
  */
/* USER CODE END Header */

/* Includes ------------------------------------------------------------------*/
#include "main.h"

/* Private includes ----------------------------------------------------------*/
/* USER CODE BEGIN Includes */
#include "game.h"
#include "protocol.h"
#include "frame.h"
#include "hardware.h"
#include <string.h>
/* USER CODE END Includes */

/* Private typedef -----------------------------------------------------------*/
/* USER CODE BEGIN PTD */

/* USER CODE END PTD */

/* Private define ------------------------------------------------------------*/
/* USER CODE BEGIN PD */
#define UART_TX_TIMEOUT_MS 100u
/* USER CODE END PD */

/* Private macro -------------------------------------------------------------*/
/* USER CODE BEGIN PM */

/* USER CODE END PM */

/* Private variables ---------------------------------------------------------*/
UART_HandleTypeDef huart1;

/* USER CODE BEGIN PV */
static TttGame game;
static FrameReceiver receiver;
static char response[PROTOCOL_RESPONSE_SIZE];

/* Diagnostic counters, visible in the debugger. */
static volatile uint32_t uart_tx_failures = 0u;
static volatile uint32_t protocol_failures = 0u;
/* USER CODE END PV */

/* Private function prototypes -----------------------------------------------*/
void SystemClock_Config(void);
static void MX_GPIO_Init(void);
static void MX_USART1_UART_Init(void);

/* USER CODE BEGIN PFP */
static void Server_Service(void);
static void Server_HandleFrame(FrameEvent event);
static void Server_Send(const char *text);
static void Server_RecoverUart(void);
/* USER CODE END PFP */

/* Private user code ---------------------------------------------------------*/
/* USER CODE BEGIN 0 */

/* USER CODE END 0 */

int main(void)
{
    /* USER CODE BEGIN 1 */

    /* USER CODE END 1 */

    HAL_Init();

    /* USER CODE BEGIN Init */

    /* USER CODE END Init */

    SystemClock_Config();

    /* USER CODE BEGIN SysInit */

    /* USER CODE END SysInit */

    MX_GPIO_Init();
    MX_USART1_UART_Init();

    /* USER CODE BEGIN 2 */
    ttt_init(&game);
    frame_init(&receiver);
    hardware_init();

    /* Clear stale UART errors and any unread startup byte. */
    __HAL_UART_CLEAR_FLAG(&huart1,
                         UART_CLEAR_PEF | UART_CLEAR_FEF |
                         UART_CLEAR_NEF | UART_CLEAR_OREF);

    __HAL_UART_SEND_REQ(&huart1, UART_RXDATA_FLUSH_REQUEST);
    /* USER CODE END 2 */

    /* USER CODE BEGIN WHILE */
    while (1)
    {
        /* USER CODE END WHILE */

        /* USER CODE BEGIN 3 */
        Server_Service();

        hardware_service(&game, HAL_GetTick());
    }
    /* USER CODE END 3 */
}

/**
  * @brief System Clock Configuration
  */
void SystemClock_Config(void)
{
    RCC_OscInitTypeDef RCC_OscInitStruct = {0};
    RCC_ClkInitTypeDef RCC_ClkInitStruct = {0};
    RCC_PeriphCLKInitTypeDef PeriphClkInit = {0};

    RCC_OscInitStruct.OscillatorType = RCC_OSCILLATORTYPE_HSI;
    RCC_OscInitStruct.HSIState = RCC_HSI_ON;
    RCC_OscInitStruct.HSICalibrationValue =
        RCC_HSICALIBRATION_DEFAULT;
    RCC_OscInitStruct.PLL.PLLState = RCC_PLL_NONE;

    if (HAL_RCC_OscConfig(&RCC_OscInitStruct) != HAL_OK)
    {
        Error_Handler();
    }

    RCC_ClkInitStruct.ClockType =
        RCC_CLOCKTYPE_HCLK |
        RCC_CLOCKTYPE_SYSCLK |
        RCC_CLOCKTYPE_PCLK1;

    RCC_ClkInitStruct.SYSCLKSource = RCC_SYSCLKSOURCE_HSI;
    RCC_ClkInitStruct.AHBCLKDivider = RCC_SYSCLK_DIV1;
    RCC_ClkInitStruct.APB1CLKDivider = RCC_HCLK_DIV1;

    if (HAL_RCC_ClockConfig(&RCC_ClkInitStruct,
                           FLASH_LATENCY_0) != HAL_OK)
    {
        Error_Handler();
    }

    PeriphClkInit.PeriphClockSelection = RCC_PERIPHCLK_USART1;
    PeriphClkInit.Usart1ClockSelection = RCC_USART1CLKSOURCE_PCLK1;

    if (HAL_RCCEx_PeriphCLKConfig(&PeriphClkInit) != HAL_OK)
    {
        Error_Handler();
    }
}

/**
  * @brief USART1 Initialisation
  */
static void MX_USART1_UART_Init(void)
{
    /* USER CODE BEGIN USART1_Init 0 */

    /* USER CODE END USART1_Init 0 */

    /* USER CODE BEGIN USART1_Init 1 */

    /* USER CODE END USART1_Init 1 */

    huart1.Instance = USART1;
    huart1.Init.BaudRate = 115200;
    huart1.Init.WordLength = UART_WORDLENGTH_8B;
    huart1.Init.StopBits = UART_STOPBITS_1;
    huart1.Init.Parity = UART_PARITY_NONE;
    huart1.Init.Mode = UART_MODE_TX_RX;
    huart1.Init.HwFlowCtl = UART_HWCONTROL_NONE;
    huart1.Init.OverSampling = UART_OVERSAMPLING_16;
    huart1.Init.OneBitSampling = UART_ONE_BIT_SAMPLE_DISABLE;
    huart1.AdvancedInit.AdvFeatureInit = UART_ADVFEATURE_NO_INIT;

    if (HAL_UART_Init(&huart1) != HAL_OK)
    {
        Error_Handler();
    }

    /* USER CODE BEGIN USART1_Init 2 */

    /* USER CODE END USART1_Init 2 */
}

/**
  * @brief GPIO Initialisation
  */
static void MX_GPIO_Init(void)
{
    /* USER CODE BEGIN MX_GPIO_Init_1 */

    /* USER CODE END MX_GPIO_Init_1 */

    __HAL_RCC_GPIOA_CLK_ENABLE();

    /* USER CODE BEGIN MX_GPIO_Init_2 */

    /* USER CODE END MX_GPIO_Init_2 */
}

/* USER CODE BEGIN 4 */

static void Server_Send(const char *text)
{
    if (text == NULL)
    {
        return;
    }

    size_t length = strlen(text);

    if (length == 0u ||
        length > PROTOCOL_MAX_FRAME_LENGTH + 1u)
    {
        return;
    }

    if (HAL_UART_Transmit(&huart1,
                          (uint8_t *)text,
                          (uint16_t)length,
                          UART_TX_TIMEOUT_MS) != HAL_OK)
    {
        uart_tx_failures++;

        (void)HAL_UART_AbortTransmit(&huart1);
    }
}

static void Server_HandleFrame(FrameEvent event)
{
    if (event == FRAME_EVENT_COMMAND)
    {
        if (protocol_handle_command(&game,
                                    receiver.buffer,
                                    response,
                                    sizeof(response)))
        {
            Server_Send(response);
        }
        else
        {
            /*
             * Internal formatting/argument failure.
             * Avoid sending a false NACK after an accepted operation.
             * The client detects the missing response by its deadline.
             */
            protocol_failures++;
        }

        return;
    }

    const char *error = frame_error_response(event);

    if (error != NULL)
    {
        Server_Send(error);
    }
}

static void Server_RecoverUart(void)
{
    (void)HAL_UART_AbortReceive(&huart1);

    __HAL_UART_CLEAR_FLAG(&huart1,
                         UART_CLEAR_PEF | UART_CLEAR_FEF |
                         UART_CLEAR_NEF | UART_CLEAR_OREF);

    __HAL_UART_SEND_REQ(&huart1, UART_RXDATA_FLUSH_REQUEST);

    /*
     * Lost or corrupted bytes invalidate the current frame.
     * Preserve the game and discard through the next LF.
     */
    if (receiver.mode != FRAME_MODE_DISCARDING)
    {
        receiver.buffer[0] = '\0';
        receiver.length = 0u;
        receiver.started_ms = 0u;
        receiver.mode = FRAME_MODE_DISCARDING;

        Server_Send("NACK:BADCMD\n");
    }
}

static void Server_Service(void)
{
    const uint32_t error_flags =
        UART_FLAG_PE |
        UART_FLAG_FE |
        UART_FLAG_NE |
        UART_FLAG_ORE;

    /* Check incomplete frames even when no bytes arrive. */
    Server_HandleFrame(
        frame_check_timeout(&receiver, HAL_GetTick()));

    if ((READ_REG(huart1.Instance->ISR) & error_flags) != 0u)
    {
        Server_RecoverUart();
        return;
    }

    uint8_t byte;

    /* Timeout zero makes this a nonblocking receive attempt. */
    HAL_StatusTypeDef status =
        HAL_UART_Receive(&huart1, &byte, 1u, 0u);

    if (status == HAL_OK)
    {
        if ((READ_REG(huart1.Instance->ISR) & error_flags) != 0u)
        {
            Server_RecoverUart();
            return;
        }

        Server_HandleFrame(
            frame_receive_byte(&receiver,
                               byte,
                               HAL_GetTick()));
    }
    else if (status != HAL_TIMEOUT)
    {
        Server_RecoverUart();
    }

    /* HAL_TIMEOUT normally means no byte was available. */
}

/* USER CODE END 4 */

void Error_Handler(void)
{
    /* USER CODE BEGIN Error_Handler_Debug */
    __disable_irq();

    while (1)
    {
    }
    /* USER CODE END Error_Handler_Debug */
}

#ifdef USE_FULL_ASSERT
void assert_failed(uint8_t *file, uint32_t line)
{
    /* USER CODE BEGIN 6 */
    (void)file;
    (void)line;
    /* USER CODE END 6 */
}
#endif /* USE_FULL_ASSERT 