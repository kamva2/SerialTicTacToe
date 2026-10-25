#ifndef FRAME_H
#define FRAME_H

#include "protocol.h"
#include <stddef.h>
#include <stdint.h>

#define FRAME_TIMEOUT_MS 1000u

typedef enum
{
    FRAME_MODE_EMPTY,
    FRAME_MODE_COLLECTING,
    FRAME_MODE_DISCARDING
} FrameMode;

typedef enum
{
    FRAME_EVENT_NONE,
    FRAME_EVENT_COMMAND,
    FRAME_EVENT_BADCMD,
    FRAME_EVENT_TOOLONG,
    FRAME_EVENT_TIMEOUT
} FrameEvent;

typedef struct
{
    char buffer[PROTOCOL_MAX_FRAME_LENGTH + 1u];
    size_t length;
    uint32_t started_ms;
    FrameMode mode;
} FrameReceiver;

void frame_init(FrameReceiver *receiver);

/*
 * Feed one received byte to the parser.
 *
 * On FRAME_EVENT_COMMAND, buffer contains the complete command
 * without LF or its optional preceding CR.
 *
 * Process that command before feeding another byte.
 */
FrameEvent frame_receive_byte(FrameReceiver *receiver,
                              uint8_t byte,
                              uint32_t now_ms);

/* Call regularly, including when no UART bytes arrive. */
FrameEvent frame_check_timeout(FrameReceiver *receiver,
                               uint32_t now_ms);

/* Returns an LF-terminated error response, or NULL for non-errors. */
const char *frame_error_response(FrameEvent event);

#endif /* FRAME_H */