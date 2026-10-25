#include "frame.h"

void frame_init(FrameReceiver *receiver)
{
    if (receiver == NULL)
    {
        return;
    }

    receiver->buffer[0] = '\0';
    receiver->length = 0u;
    receiver->started_ms = 0u;
    receiver->mode = FRAME_MODE_EMPTY;
}

static FrameEvent frame_reject(FrameReceiver *receiver,
                               FrameEvent reason)
{
    receiver->buffer[0] = '\0';
    receiver->length = 0u;
    receiver->started_ms = 0u;
    receiver->mode = FRAME_MODE_DISCARDING;

    return reason;
}

FrameEvent frame_check_timeout(FrameReceiver *receiver,
                               uint32_t now_ms)
{
    if (receiver == NULL)
    {
        return FRAME_EVENT_NONE;
    }

    if (receiver->mode == FRAME_MODE_COLLECTING)
    {
        /*
         * Unsigned subtraction handles the timer wrapping around.
         * The deadline runs from the first byte of this frame.
         */
        uint32_t elapsed = now_ms - receiver->started_ms;

        if (elapsed >= FRAME_TIMEOUT_MS)
        {
            return frame_reject(receiver, FRAME_EVENT_TIMEOUT);
        }
    }

    return FRAME_EVENT_NONE;
}

FrameEvent frame_receive_byte(FrameReceiver *receiver,
                              uint8_t byte,
                              uint32_t now_ms)
{
    if (receiver == NULL)
    {
        return FRAME_EVENT_NONE;
    }

    /*
     * Check the deadline before accepting this byte.
     * A late LF rejects the old frame, then ends discard mode.
     */
    FrameEvent timeout = frame_check_timeout(receiver, now_ms);

    if (timeout == FRAME_EVENT_TIMEOUT)
    {
        if (byte == '\n')
        {
            frame_init(receiver);
        }

        return timeout;
    }

    /* Ignore the remainder of a previously rejected frame. */
    if (receiver->mode == FRAME_MODE_DISCARDING)
    {
        if (byte == '\n')
        {
            frame_init(receiver);
        }

        return FRAME_EVENT_NONE;
    }

    /* LF completes a frame, or is ignored when no frame exists. */
    if (byte == '\n')
    {
        if (receiver->mode == FRAME_MODE_EMPTY)
        {
            return FRAME_EVENT_NONE;
        }

        size_t command_length = receiver->length;

        /* Strip one optional CR immediately before LF. */
        if (command_length > 0u &&
            receiver->buffer[command_length - 1u] == '\r')
        {
            command_length--;
        }

        receiver->buffer[command_length] = '\0';

        /*
         * Prepare for another frame while preserving the completed
         * command in buffer for the caller to process immediately.
         */
        receiver->length = 0u;
        receiver->started_ms = 0u;
        receiver->mode = FRAME_MODE_EMPTY;

        if (command_length == 0u)
        {
            return FRAME_EVENT_BADCMD;
        }

        return FRAME_EVENT_COMMAND;
    }

    /* Start timing when the first non-LF byte arrives. */
    if (receiver->mode == FRAME_MODE_EMPTY)
    {
        receiver->buffer[0] = '\0';
        receiver->length = 0u;
        receiver->started_ms = now_ms;
        receiver->mode = FRAME_MODE_COLLECTING;
    }

    /* Never write beyond the 96-byte payload limit. */
    if (receiver->length >= PROTOCOL_MAX_FRAME_LENGTH)
    {
        return frame_reject(receiver, FRAME_EVENT_TOOLONG);
    }

    /* Accept printable ASCII and a provisional trailing CR. */
    if (byte != '\r' &&
        (byte < 0x20u || byte > 0x7Eu))
    {
        return frame_reject(receiver, FRAME_EVENT_BADCMD);
    }

    /* Once CR is received, only LF may follow it. */
    if (receiver->length > 0u &&
        receiver->buffer[receiver->length - 1u] == '\r')
    {
        return frame_reject(receiver, FRAME_EVENT_BADCMD);
    }

    receiver->buffer[receiver->length] = (char)byte;
    receiver->length++;

    receiver->buffer[receiver->length] = '\0';

    return FRAME_EVENT_NONE;
}

const char *frame_error_response(FrameEvent event)
{
    switch (event)
    {
        case FRAME_EVENT_BADCMD:
            return "NACK:BADCMD\n";

        case FRAME_EVENT_TOOLONG:
            return "NACK:TOOLONG\n";

        case FRAME_EVENT_TIMEOUT:
            return "NACK:TIMEOUT\n";

        default:
            return NULL;
    }
}