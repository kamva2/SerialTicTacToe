#ifndef TTT_HARDWARE_H
#define TTT_HARDWARE_H

#include "game.h"
#include <stdint.h>

/* Configure the button, LED and debounce state. */
void hardware_init(void);

/* Call regularly from the main loop. */
void hardware_service(TttGame *game, uint32_t now_ms);

#endif /* TTT_HARDWARE_H */