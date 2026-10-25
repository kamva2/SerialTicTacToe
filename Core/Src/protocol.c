#include "protocol.h"
#include <stdio.h>
#include <string.h>

const char *protocol_status_response(TttStatus status)
{
    switch (status)
    {
        case TTT_OK:
            return "OK\n";

        case TTT_ERR_BADCMD:
            return "NACK:BADCMD\n";

        case TTT_ERR_NOTCONNECTED:
            return "NACK:NOTCONNECTED\n";

        case TTT_ERR_NOGAME:
            return "NACK:NOGAME\n";

        case TTT_ERR_BUSY:
            return "NACK:BUSY\n";

        case TTT_ERR_NOTURN:
            return "NACK:NOTURN\n";

        case TTT_ERR_RANGE:
            return "NACK:RANGE\n";

        case TTT_ERR_OCCUPIED:
            return "NACK:OCCUPIED\n";

        default:
            return "NACK:BADCMD\n";
    }
}

static const char *protocol_phase_text(TttPhase phase)
{
    switch (phase)
    {
        case TTT_IN_PROGRESS:
            return "IN_PROGRESS";

        case TTT_GAME_OVER:
            return "GAME_OVER";

        default:
            return NULL;
    }
}

static const char *protocol_result_text(TttResult result)
{
    switch (result)
    {
        case TTT_RESULT_NONE:
            return "NONE";

        case TTT_RESULT_WIN_X:
            return "WIN_X";

        case TTT_RESULT_WIN_O:
            return "WIN_O";

        case TTT_RESULT_DRAW:
            return "DRAW";

        case TTT_RESULT_RESIGN_X:
            return "RESIGN_X";

        case TTT_RESULT_RESIGN_O:
            return "RESIGN_O";

        default:
            return NULL;
    }
}

bool protocol_format_snapshot(const TttGame *game,
                              bool include_ok,
                              char *response,
                              size_t capacity)
{
    if (response == NULL || capacity == 0u)
    {
        return false;
    }

    response[0] = '\0';

    if (game == NULL || !game->connected)
    {
        return false;
    }

    const char *phase = protocol_phase_text(game->phase);
    const char *result = protocol_result_text(game->result);

    if (phase == NULL || result == NULL)
    {
        return false;
    }

    for (unsigned int i = 0; i < TTT_BOARD_SIZE; i++)
    {
        char cell = game->board[i];

        if (cell != '.' && cell != 'X' && cell != 'O')
        {
            return false;
        }
    }

    if (game->phase == TTT_IN_PROGRESS)
    {
        if ((game->turn != 'X' && game->turn != 'O') ||
            game->result != TTT_RESULT_NONE)
        {
            return false;
        }
    }
    else
    {
        if (game->turn != '-' ||
            game->result == TTT_RESULT_NONE)
        {
            return false;
        }
    }

    int written = snprintf(
        response,
        capacity,
        "%sBOARD:%.9s:TURN:%c:PHASE:%s:RESULT:%s\n",
        include_ok ? "OK:" : "",
        game->board,
        game->turn,
        phase,
        result
    );

    if (written < 0 ||
        (size_t)written >= capacity ||
        (size_t)written > PROTOCOL_MAX_FRAME_LENGTH + 1u)
    {
        response[0] = '\0';
        return false;
    }

    return true;
}

static bool protocol_copy_response(const char *text,
                                   char *response,
                                   size_t capacity)
{
    size_t length = strlen(text);

    if (length >= capacity)
    {
        response[0] = '\0';
        return false;
    }

    memcpy(response, text, length + 1u);

    return true;
}

static bool protocol_parse_move(const char *command,
                                size_t length,
                                char *player,
                                int *index)
{
    /* Shortest valid form is MOVE:X:0, containing eight characters. */
    if (length < 8u ||
        (command[5] != 'X' && command[5] != 'O') ||
        command[6] != ':')
    {
        return false;
    }

    size_t position = 7u;
    bool negative = false;

    if (command[position] == '-')
    {
        negative = true;
        position++;
    }

    if (position == length)
    {
        return false;
    }

    unsigned int value = 0u;

    for (; position < length; position++)
    {
        char digit = command[position];

        if (digit < '0' || digit > '9')
        {
            return false;
        }

        /*
         * Preserve values 0-8 and saturate larger values at 9.
         * This avoids overflow even for a very long number.
         *
         * Continue checking every remaining character so malformed
         * numbers still produce BADCMD.
         */
        if (value < 9u)
        {
            value = value * 10u + (unsigned int)(digit - '0');

            if (value > 9u)
            {
                value = 9u;
            }
        }
    }

    *player = command[5];

    if (negative && value != 0u)
    {
        *index = -1;
    }
    else
    {
        *index = (int)value;
    }

    return true;
}

bool protocol_handle_command(TttGame *game,
                             const char *command,
                             char *response,
                             size_t capacity)
{
    if (response == NULL || capacity == 0u)
    {
        return false;
    }

    response[0] = '\0';

    /*
     * Reserve enough response space before any game operation
     * can change state.
     */
    if (game == NULL ||
        command == NULL ||
        capacity < PROTOCOL_RESPONSE_SIZE)
    {
        return false;
    }

    size_t length = 0u;

    while (length <= PROTOCOL_MAX_FRAME_LENGTH &&
           command[length] != '\0')
    {
        length++;
    }

    if (length > PROTOCOL_MAX_FRAME_LENGTH)
    {
        return protocol_copy_response(
            "NACK:TOOLONG\n", response, capacity);
    }

    /* The frame parser removes terminators before this function. */
    for (size_t i = 0u; i < length; i++)
    {
        unsigned char character = (unsigned char)command[i];

        if (character < 0x20u || character > 0x7Eu)
        {
            return protocol_copy_response(
                "NACK:BADCMD\n", response, capacity);
        }
    }

    TttStatus status;
    bool snapshot_required = false;

    if (strcmp(command, "CONNECT") == 0)
    {
        status = ttt_connect(game);
    }
    else if (strcmp(command, "DISCONNECT") == 0)
    {
        status = ttt_disconnect(game);
    }
    else if (strcmp(command, "NEW") == 0)
    {
        status = ttt_new(game);
        snapshot_required = true;
    }
    else if (strcmp(command, "STATE") == 0)
    {
        if (!game->connected)
        {
            return protocol_copy_response(
                "NACK:NOTCONNECTED\n", response, capacity);
        }

        if (game->phase != TTT_IN_PROGRESS &&
            game->phase != TTT_GAME_OVER)
        {
            return protocol_copy_response(
                "NACK:NOGAME\n", response, capacity);
        }

        return protocol_format_snapshot(
            game, false, response, capacity);
    }
    else if (strncmp(command, "MOVE:", 5u) == 0)
    {
        char player;
        int index;

        if (!protocol_parse_move(command, length, &player, &index))
        {
            return protocol_copy_response(
                "NACK:BADCMD\n", response, capacity);
        }

        status = ttt_move(game, player, index);
        snapshot_required = true;
    }
    else if (strncmp(command, "RESIGN:", 7u) == 0)
    {
        if (length != 8u ||
            (command[7] != 'X' && command[7] != 'O'))
        {
            return protocol_copy_response(
                "NACK:BADCMD\n", response, capacity);
        }

        status = ttt_resign(game, command[7]);
        snapshot_required = true;
    }
    else
    {
        return protocol_copy_response(
            "NACK:BADCMD\n", response, capacity);
    }

    if (status != TTT_OK)
    {
        return protocol_copy_response(
            protocol_status_response(status),
            response,
            capacity);
    }

    if (snapshot_required)
    {
        return protocol_format_snapshot(
            game, true, response, capacity);
    }

    return protocol_copy_response(
        protocol_status_response(TTT_OK),
        response,
        capacity);
}