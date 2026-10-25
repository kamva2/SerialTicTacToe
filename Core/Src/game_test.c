#include "game_test.h"
#include "game.h"
#include <string.h>

#define CHECK(condition)           \
    do                             \
    {                              \
        if (!(condition))          \
        {                          \
            return __LINE__;       \
        }                          \
    } while (0)

unsigned int ttt_run_tests(void)
{
    TttGame game;
    TttStatus status;

    /* Check the boot state. */
    ttt_init(&game);

    CHECK(strcmp(game.board, ".........") == 0);
    CHECK(!game.connected);
    CHECK(game.phase == TTT_IDLE);
    CHECK(game.turn == '-');
    CHECK(game.result == TTT_RESULT_NONE);

    /* Starting without a connection must fail. */
    status = ttt_new(&game);
    CHECK(status == TTT_ERR_NOTCONNECTED);

    /* Connect and start a game. */
    status = ttt_connect(&game);
    CHECK(status == TTT_OK);
    CHECK(game.connected);

    status = ttt_new(&game);
    CHECK(status == TTT_OK);
    CHECK(strcmp(game.board, ".........") == 0);
    CHECK(game.phase == TTT_IN_PROGRESS);
    CHECK(game.turn == 'X');

    /* X makes a legal move. */
    status = ttt_move(&game, 'X', 0);
    CHECK(status == TTT_OK);
    CHECK(strcmp(game.board, "X........") == 0);
    CHECK(game.turn == 'O');

    /* An occupied-cell rejection must preserve every field. */
    TttGame before = game;

    status = ttt_move(&game, 'O', 0);
    CHECK(status == TTT_ERR_OCCUPIED);

    CHECK(memcmp(game.board, before.board,
                 sizeof(game.board)) == 0);
    CHECK(game.connected == before.connected);
    CHECK(game.phase == before.phase);
    CHECK(game.turn == before.turn);
    CHECK(game.result == before.result);

    /* Complete a top-row win for X. */
    status = ttt_move(&game, 'O', 3);
    CHECK(status == TTT_OK);

    status = ttt_move(&game, 'X', 1);
    CHECK(status == TTT_OK);

    status = ttt_move(&game, 'O', 4);
    CHECK(status == TTT_OK);

    status = ttt_move(&game, 'X', 2);
    CHECK(status == TTT_OK);

    CHECK(strcmp(game.board, "XXXOO....") == 0);
    CHECK(game.phase == TTT_GAME_OVER);
    CHECK(game.result == TTT_RESULT_WIN_X);
    CHECK(game.turn == '-');

    /* Further moves must be refused. */
    status = ttt_move(&game, 'O', 8);
    CHECK(status == TTT_ERR_NOGAME);

    return 0;
}

#undef CHECK