#include "game.h"
#include <string.h>

void ttt_init(TttGame *game)
{
    memset(game->board, '.', TTT_BOARD_SIZE);
    game->board[TTT_BOARD_SIZE] = '\0';

    game->turn = '-';
    game->connected = false;
    game->phase = TTT_IDLE;
    game->result = TTT_RESULT_NONE;
}

TttStatus ttt_connect(TttGame *game)
{
    if (game->phase != TTT_IDLE)
    {
        return TTT_ERR_BUSY;
    }

    game->connected = true;

    return TTT_OK;
}

TttStatus ttt_new(TttGame *game)
{
    if (!game->connected)
    {
        return TTT_ERR_NOTCONNECTED;
    }

    if (game->phase == TTT_IN_PROGRESS)
    {
        return TTT_ERR_BUSY;
    }

    memset(game->board, '.', TTT_BOARD_SIZE);
    game->board[TTT_BOARD_SIZE] = '\0';

    game->turn = 'X';
    game->phase = TTT_IN_PROGRESS;
    game->result = TTT_RESULT_NONE;

    return TTT_OK;
}

bool ttt_has_won(const TttGame *game, char player)
{
    static const unsigned char winning_lines[8][3] =
    {
        {0, 1, 2},  // Top row 
        {3, 4, 5},  // Middle row 
        {6, 7, 8},  // Bottom row

        {0, 3, 6},  // Left column 
        {1, 4, 7},  // Middle column 
        {2, 5, 8},  // Right column 

        {0, 4, 8},  // Main diagonal 
        {2, 4, 6}   // Other diagonal 
    };

    if (player != 'X' && player != 'O')
    {
        return false;
    }

    for (unsigned int i = 0; i < 8u; i++)
    {
        const unsigned char *line = winning_lines[i];

        if (game->board[line[0]] == player &&
            game->board[line[1]] == player &&
            game->board[line[2]] == player)
        {
            return true;
        }
    }

    return false;
}

bool ttt_is_board_full(const TttGame *game)
{
    for (unsigned int i = 0; i < TTT_BOARD_SIZE; i++)
    {
        if (game->board[i] == '.')
        {
            return false;
        }
    }

    return true;
}

TttStatus ttt_move(TttGame *game, char player, int index)
{
    /* Validate before changing any game state. */
    if (player != 'X' && player != 'O')
    {
        return TTT_ERR_BADCMD;
    }

    if (!game->connected)
    {
        return TTT_ERR_NOTCONNECTED;
    }

    if (game->phase != TTT_IN_PROGRESS)
    {
        return TTT_ERR_NOGAME;
    }

    if (player != game->turn)
    {
        return TTT_ERR_NOTURN;
    }

    if (index < 0 || index >= (int)TTT_BOARD_SIZE)
    {
        return TTT_ERR_RANGE;
    }

    if (game->board[index] != '.')
    {
        return TTT_ERR_OCCUPIED;
    }

    /* Every check passed: commit exactly one mark. */
    game->board[index] = player;

    /* Check for a win before checking for a draw. */
    if (ttt_has_won(game, player))
    {
        game->phase = TTT_GAME_OVER;
        game->turn = '-';

        game->result = (player == 'X')
                     ? TTT_RESULT_WIN_X
                     : TTT_RESULT_WIN_O;
    }
    else if (ttt_is_board_full(game))
    {
        game->phase = TTT_GAME_OVER;
        game->turn = '-';
        game->result = TTT_RESULT_DRAW;
    }
    else
    {
        game->turn = (player == 'X') ? 'O' : 'X';
    }

    return TTT_OK;
}

TttStatus ttt_resign(TttGame *game, char player)
{
    if (player != 'X' && player != 'O')
    {
        return TTT_ERR_BADCMD;
    }

    if (!game->connected)
    {
        return TTT_ERR_NOTCONNECTED;
    }

    if (game->phase != TTT_IN_PROGRESS)
    {
        return TTT_ERR_NOGAME;
    }

    if (player != game->turn)
    {
        return TTT_ERR_NOTURN;
    }

    /* Retain the board and record who resigned. */
    game->phase = TTT_GAME_OVER;
    game->turn = '-';

    game->result = (player == 'X')
                 ? TTT_RESULT_RESIGN_X
                 : TTT_RESULT_RESIGN_O;

    return TTT_OK;
}

TttStatus ttt_disconnect(TttGame *game)
{
    ttt_init(game);

    return TTT_OK;
}