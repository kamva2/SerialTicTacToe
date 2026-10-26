"""Pytest tests for the actual C command handler. No serial port is used."""

import ctypes as C
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

import pytest


ROOT = Path(__file__).resolve().parents[1]


class Game(C.Structure):
    _fields_ = [
        ("board", C.c_char * 10),
        ("turn", C.c_char),
        ("connected", C.c_bool),
        ("phase", C.c_int),
        ("result", C.c_int),
    ]


def state(game):
    return (
        bytes(game.board),
        game.turn,
        game.connected,
        game.phase,
        game.result,
    )


def snapshot(
    board=".........",
    turn="X",
    phase="IN_PROGRESS",
    result="NONE",
    ok=True,
):
    return (
        ("OK:" if ok else "")
        + f"BOARD:{board}:TURN:{turn}:PHASE:{phase}:RESULT:{result}\n"
    )


@pytest.fixture(scope="session")
def native():
    """Build the real firmware logic for Windows, not the STM32."""
    compiler = shutil.which("gcc")

    if compiler is None:
        pytest.fail(
            "GCC was not found. Run 'gcc --version' in PowerShell."
        )

    if sys.platform != "win32":
        pytest.fail(
            "This test build is configured for Windows."
        )

    with tempfile.TemporaryDirectory(
        prefix="eee3095_pytest_"
    ) as folder:
        output = Path(folder) / "commands.dll"

        built = subprocess.run(
            [
                compiler,
                "-shared",
                "-std=c11",
                "-O2",
                "-Wall",
                "-Wextra",
                "-Werror",
                "-static-libgcc",
                "-I",
                str(ROOT / "Core" / "Inc"),
                str(ROOT / "Core" / "Src" / "game.c"),
                str(ROOT / "Core" / "Src" / "protocol.c"),
                "-o",
                str(output),
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )

        if built.returncode:
            pytest.fail(
                "C test build failed:\n"
                + built.stdout
                + built.stderr
            )

        library = C.CDLL(str(output))

        try:
            library.ttt_init.argtypes = [
                C.POINTER(Game)
            ]
            library.ttt_init.restype = None

            library.protocol_handle_command.argtypes = [
                C.POINTER(Game),
                C.c_char_p,
                C.POINTER(C.c_char),
                C.c_size_t,
            ]
            library.protocol_handle_command.restype = C.c_bool

            yield library

        finally:
            # Release the DLL before deleting its temporary folder.
            from _ctypes import FreeLibrary

            FreeLibrary(library._handle)


@pytest.fixture
def game(native):
    instance = Game()
    native.ttt_init(C.byref(instance))
    return instance


def command(native, game, text, expected=None):
    before = state(game)
    response = C.create_string_buffer(98)

    produced = native.protocol_handle_command(
        C.byref(game),
        text.encode("ascii"),
        response,
        len(response),
    )

    assert produced, f"No response to {text!r}"

    reply = response.value.decode("ascii")

    assert reply.endswith("\n")
    assert reply.count("\n") == 1
    assert len(reply) <= 97

    # Rejections and STATE must preserve every game field.
    if reply.startswith("NACK:") or text == "STATE":
        assert state(game) == before, (
            f"{text!r} unexpectedly changed the game"
        )

    if expected is not None:
        assert reply == expected, (
            f"Incorrect response to {text!r}"
        )

    return reply


def start(native, game):
    command(native, game, "CONNECT", "OK\n")
    command(native, game, "NEW", snapshot())


@pytest.fixture
def active(native, game):
    start(native, game)
    return game


def play(native, game, moves):
    reply = None

    for index in moves:
        player = game.turn.decode("ascii")

        reply = command(
            native,
            game,
            f"MOVE:{player}:{index}",
        )

        assert reply.startswith("OK:BOARD:")

    return reply


def set_phase(native, game, phase):
    if phase != "disconnected":
        command(native, game, "CONNECT", "OK\n")

    if phase in {"active", "over"}:
        command(native, game, "NEW", snapshot())

    if phase == "over":
        command(
            native,
            game,
            "RESIGN:X",
            snapshot(
                turn="-",
                phase="GAME_OVER",
                result="RESIGN_X",
            ),
        )


def test_boot_state(game):
    assert state(game) == (
        b".........", b"-", False, 0, 0
    )


@pytest.mark.parametrize(
    "text",
    ["NEW", "STATE", "MOVE:X:0", "RESIGN:X"],
)
def test_requires_connection(native, game, text):
    command(
        native,
        game,
        text,
        "NACK:NOTCONNECTED\n",
    )


def test_connect_repeatable_in_idle(native, game):
    command(native, game, "CONNECT", "OK\n")

    before = state(game)

    command(native, game, "CONNECT", "OK\n")

    assert state(game) == before


@pytest.mark.parametrize(
    "text",
    ["STATE", "MOVE:X:0", "RESIGN:X"],
)
def test_connected_idle_has_no_game(native, game, text):
    command(native, game, "CONNECT", "OK\n")
    command(native, game, text, "NACK:NOGAME\n")


def test_new_and_state(native, active):
    command(
        native,
        active,
        "STATE",
        snapshot(ok=False),
    )


@pytest.mark.parametrize("text", ["NEW", "CONNECT"])
def test_active_game_is_busy(native, active, text):
    command(native, active, text, "NACK:BUSY\n")


@pytest.mark.parametrize(
    "text,error",
    [
        ("MOVE:O:9", "NOTURN"),
        ("MOVE:X:9", "RANGE"),
        ("MOVE:X:-1", "RANGE"),
        ("MOVE:O:-1", "NOTURN"),
        ("MOVE:X:bad", "BADCMD"),
        ("RESIGN:O", "NOTURN"),
    ],
)
def test_rejection_order(native, active, text, error):
    command(
        native,
        active,
        text,
        f"NACK:{error}\n",
    )


def test_legal_moves_and_occupied_cell(native, active):
    command(
        native,
        active,
        "MOVE:X:0",
        snapshot("X........", "O"),
    )

    command(
        native, active,
        "MOVE:X:0", "NACK:NOTURN\n",
    )

    command(
        native, active,
        "MOVE:O:0", "NACK:OCCUPIED\n",
    )

    command(
        native,
        active,
        "MOVE:O:4",
        snapshot("X...O....", "X"),
    )


BAD_COMMANDS = [
    "",
    "connect",
    "NEW ",
    " STATE",
    "PING",
    "CONNECT:EXTRA",
    "DISCONNECT:EXTRA",
    "MOVE",
    "MOVE:",
    "MOVE:X",
    "MOVE:X:",
    "MOVE:Z:0",
    "MOVE:x:0",
    "MOVE:XX:0",
    "MOVE:X:+1",
    "MOVE:X:1.0",
    "MOVE:X: 1",
    "MOVE:X:--1",
    "MOVE:X:-",
    "MOVE:X:0:1",
    "MOVE:X:999bad",
    "RESIGN",
    "RESIGN:",
    "RESIGN:Z",
    "RESIGN:XX",
    "RESIGN:X:0",
    "STATE\n",
    "STATE\r",
    "MOVE:X:\t0",
]


@pytest.mark.parametrize(
    "phase",
    ["disconnected", "idle", "active", "over"],
)
@pytest.mark.parametrize("text", BAD_COMMANDS)
def test_bad_syntax_in_every_phase(
    native, game, phase, text
):
    set_phase(native, game, phase)

    command(
        native,
        game,
        text,
        "NACK:BADCMD\n",
    )


@pytest.mark.parametrize(
    "index",
    ["0", "00", "-0", "-000", "00000000"],
)
def test_zero_spellings(native, active, index):
    command(
        native,
        active,
        f"MOVE:X:{index}",
        snapshot("X........", "O"),
    )


@pytest.mark.parametrize(
    "text,expected",
    [
        (
            "MOVE:X:" + "0" * 89,
            snapshot("X........", "O"),
        ),
        (
            "MOVE:X:" + "9" * 89,
            "NACK:RANGE\n",
        ),
        (
            "MOVE:X:-" + "9" * 88,
            "NACK:RANGE\n",
        ),
        (
            "A" * 96,
            "NACK:BADCMD\n",
        ),
        (
            "A" * 97,
            "NACK:TOOLONG\n",
        ),
    ],
)
def test_numeric_and_length_boundaries(
    native, active, text, expected
):
    command(native, active, text, expected)


@pytest.mark.parametrize(
    "line",
    [
        (0, 1, 2),
        (3, 4, 5),
        (6, 7, 8),
        (0, 3, 6),
        (1, 4, 7),
        (2, 5, 8),
        (0, 4, 8),
        (2, 4, 6),
    ],
)
def test_all_eight_x_winning_lines(
    native, active, line
):
    other = [
        i for i in range(9)
        if i not in line
    ]

    reply = play(
        native,
        active,
        [
            line[0],
            other[0],
            line[1],
            other[1],
            line[2],
        ],
    )

    board = ["."] * 9

    for index in line:
        board[index] = "X"

    board[other[0]] = "O"
    board[other[1]] = "O"

    board = "".join(board)

    assert reply == snapshot(
        board, "-", "GAME_OVER", "WIN_X"
    )

    command(
        native,
        active,
        "STATE",
        snapshot(
            board, "-", "GAME_OVER", "WIN_X",
            ok=False,
        ),
    )


@pytest.mark.parametrize(
    "moves,board,result",
    [
        (
            [0, 3, 1, 4, 8, 5],
            "XX.OOO..X",
            "WIN_O",
        ),
        (
            [0, 1, 2, 4, 3, 5, 7, 6, 8],
            "XOXXOOOXX",
            "DRAW",
        ),
        (
            [0, 1, 2, 3, 4, 5, 7, 6, 8],
            "XOXOXOOXX",
            "WIN_X",
        ),
    ],
)
def test_o_win_draw_and_ninth_move_win(
    native, active, moves, board, result
):
    assert play(native, active, moves) == snapshot(
        board, "-", "GAME_OVER", result
    )


@pytest.mark.parametrize(
    "text,error",
    [
        ("MOVE:O:8", "NOGAME"),
        ("RESIGN:X", "NOGAME"),
        ("CONNECT", "BUSY"),
    ],
)
def test_commands_after_game_over(
    native, active, text, error
):
    play(native, active, [0, 3, 1, 4, 2])

    command(
        native,
        active,
        text,
        f"NACK:{error}\n",
    )


def test_restart_completed_game(native, active):
    play(native, active, [0, 3, 1, 4, 2])

    command(
        native,
        active,
        "NEW",
        snapshot(),
    )


@pytest.mark.parametrize("player", ["X", "O"])
def test_resignation_retains_board(
    native, active, player
):
    board = "........."

    if player == "O":
        command(
            native,
            active,
            "MOVE:X:4",
            snapshot("....X....", "O"),
        )

        board = "....X...."

    command(
        native,
        active,
        f"RESIGN:{player}",
        snapshot(
            board,
            "-",
            "GAME_OVER",
            f"RESIGN_{player}",
        ),
    )


@pytest.mark.parametrize(
    "phase",
    ["disconnected", "idle", "active", "over"],
)
def test_disconnect_in_every_phase(
    native, game, phase
):
    set_phase(native, game, phase)

    command(native, game, "DISCONNECT", "OK\n")
    command(native, game, "DISCONNECT", "OK\n")

    assert state(game) == (
        b".........", b"-", False, 0, 0
    )


def test_reset_ends_session(native, active):
    command(
        native,
        active,
        "MOVE:X:0",
        snapshot("X........", "O"),
    )

    # Simulate the game initialisation performed on reset.
    native.ttt_init(C.byref(active))

    command(
        native,
        active,
        "STATE",
        "NACK:NOTCONNECTED\n",
    )


@pytest.mark.parametrize("capacity", [0, 1, 97])
def test_small_response_buffer_cannot_commit_move(
    native, active, capacity
):
    before = state(active)
    response = C.create_string_buffer(98)

    assert not native.protocol_handle_command(
        C.byref(active),
        b"MOVE:X:0",
        response,
        capacity,
    )

    assert state(active) == before