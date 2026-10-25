#ifndef GAME_H
#define GAME_H

#include <stdbool.h>

#define TTT_BOARD_SIZE 9u

typedef enum
{
    TTT_IDLE,
    TTT_IN_PROGRESS,
    TTT_GAME_OVER
} TttPhase;

typedef enum
{
    TTT_RESULT_NONE,
    TTT_RESULT_WIN_X,
    TTT_RESULT_WIN_O,
    TTT_RESULT_DRAW,
    TTT_RESULT_RESIGN_X,
    TTT_RESULT_RESIGN_O
} TttResult;

// Return values for game operations.
typedef enum
{
    TTT_OK,
    TTT_ERR_BADCMD,
    TTT_ERR_NOTCONNECTED,
    TTT_ERR_NOGAME,
    TTT_ERR_BUSY,
    TTT_ERR_NOTURN,
    TTT_ERR_RANGE,
    TTT_ERR_OCCUPIED
} TttStatus;

typedef struct
{
    /* Nine cells plus a null terminator for response formatting. */
    char board[TTT_BOARD_SIZE + 1u];

    /* 'X' or 'O' during play; '-' otherwise. */
    char turn;

    bool connected;
    TttPhase phase;
    TttResult result;
} TttGame;

void ttt_init(TttGame *game);
TttStatus ttt_connect(TttGame *game);
TttStatus ttt_new(TttGame *game);
bool ttt_has_won(const TttGame *game, char player);
bool ttt_is_board_full(const TttGame *game);
TttStatus ttt_move(TttGame *game, char player, int index);
TttStatus ttt_resign(TttGame *game, char player);
TttStatus ttt_disconnect(TttGame *game);
#endif /* GAME_H */