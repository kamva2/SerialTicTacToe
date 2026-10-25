#include "hardware.h"
#include "main.h"

#define GAME_BUTTON_PORT GPIOA
#define GAME_BUTTON_PIN  GPIO_PIN_0

#define TURN_LED_PORT    GPIOB
#define TURN_LED_PIN     GPIO_PIN_0

#define BUTTON_DEBOUNCE_MS 20u

static GPIO_PinState button_candidate;
static GPIO_PinState button_stable;
static uint32_t button_changed_ms;
static bool button_armed;

void hardware_init(void)
{
    GPIO_InitTypeDef gpio = {0};

    __HAL_RCC_GPIOA_CLK_ENABLE();
    __HAL_RCC_GPIOB_CLK_ENABLE();

    /* Set the LED output latch low before enabling output mode. */
    HAL_GPIO_WritePin(TURN_LED_PORT,
                      TURN_LED_PIN,
                      GPIO_PIN_RESET);

    gpio.Pin = TURN_LED_PIN;
    gpio.Mode = GPIO_MODE_OUTPUT_PP;
    gpio.Pull = GPIO_NOPULL;
    gpio.Speed = GPIO_SPEED_FREQ_LOW;

    HAL_GPIO_Init(TURN_LED_PORT, &gpio);

    /* SW0 connects PA0 to ground when pressed. */
    gpio.Pin = GAME_BUTTON_PIN;
    gpio.Mode = GPIO_MODE_INPUT;
    gpio.Pull = GPIO_PULLUP;

    HAL_GPIO_Init(GAME_BUTTON_PORT, &gpio);

    button_candidate = HAL_GPIO_ReadPin(GAME_BUTTON_PORT,
                                        GAME_BUTTON_PIN);

    /*
     * Require a stable released level before accepting a press.
     * Holding the button during boot must not start a game.
     */
    button_stable = GPIO_PIN_RESET;
    button_armed = false;
    button_changed_ms = HAL_GetTick();
}

void hardware_service(TttGame *game, uint32_t now_ms)
{
    GPIO_PinState raw = HAL_GPIO_ReadPin(GAME_BUTTON_PORT,
                                        GAME_BUTTON_PIN);

    /* Restart the debounce interval whenever the raw level changes. */
    if (raw != button_candidate)
    {
        button_candidate = raw;
        button_changed_ms = now_ms;
    }

    uint32_t stable_time = now_ms - button_changed_ms;

    if (button_candidate != button_stable &&
        stable_time >= BUTTON_DEBOUNCE_MS)
    {
        button_stable = button_candidate;

        if (button_stable == GPIO_PIN_SET)
        {
            /* A stable release allows the next press. */
            button_armed = true;
        }
        else
        {
            bool accept_press = button_armed;

            /* Consume this press, even if its action is unavailable. */
            button_armed = false;

            if (accept_press &&
                game != NULL &&
                game->connected &&
                (game->phase == TTT_IDLE ||
                 game->phase == TTT_GAME_OVER))
            {
                /*
                 * Local NEW uses the same game-engine operation
                 * as a serial NEW command.
                 */
                (void)ttt_new(game);
            }
        }
    }

    /* Derive the LED directly from authoritative game state. */
    GPIO_PinState led_state = GPIO_PIN_RESET;

    if (game != NULL &&
        game->connected &&
        game->phase == TTT_IN_PROGRESS &&
        game->turn == 'X')
    {
        led_state = GPIO_PIN_SET;
    }

    HAL_GPIO_WritePin(TURN_LED_PORT,
                      TURN_LED_PIN,
                      led_state);
}