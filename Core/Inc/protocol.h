#ifndef PROTOCOL_H
#define PROTOCOL_H

#include "game.h"
#include <stdbool.h>
#include <stddef.h>

#define PROTOCOL_MAX_FRAME_LENGTH 96u

/* Maximum payload + LF + null terminator. */
#define PROTOCOL_RESPONSE_SIZE \
    (PROTOCOL_MAX_FRAME_LENGTH + 2u)

const char *protocol_status_response(TttStatus status);

bool protocol_format_snapshot(const TttGame *game,
                              bool include_ok,
                              char *response,
                              size_t capacity);

/*
 * Processes one complete, null-terminated command.
 * The UART frame parser must remove LF and optional trailing CR.
 *
 * Use separate command and response buffers.
 * Response capacity must be at least PROTOCOL_RESPONSE_SIZE.
 *
 * Returns true when a response was produced, including a NACK.
 * Returns false for invalid arguments or response-formatting failure.
 */
bool protocol_handle_command(TttGame *game,
                             const char *command,
                             char *response,
                             size_t capacity);

#endif /* PROTOCOL_H */