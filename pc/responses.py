"""Interpret server replies without duplicating the game rules."""

from __future__ import annotations

from dataclasses import dataclass
import re

MAX_FRAME_LENGTH = 96

ERROR_MESSAGES = {
    "BADCMD": "The board rejected an unknown or malformed command.",
    "NOTCONNECTED": "A connection must be established first.",
    "NOGAME": "The command is unavailable in the current game phase.",
    "BUSY": "The command is unavailable while this game is retained.",
    "NOTURN": "The specified player is not the current player.",
    "RANGE": "The cell index must be between 0 and 8.",
    "OCCUPIED": "That cell is already occupied.",
    "TOOLONG": "The command frame exceeded the 96-byte limit.",
    "TIMEOUT": "An incomplete command exceeded the board's frame deadline.",
}

TERMINAL_RESULTS = {
    "WIN_X",
    "WIN_O",
    "DRAW",
    "RESIGN_X",
    "RESIGN_O",
}

WINNERS = {
    "WIN_X": "X",
    "WIN_O": "O",
    "RESIGN_X": "O",
    "RESIGN_O": "X",
}

MOVE_PATTERN = re.compile(r"MOVE:([XO]):-?[0-9]+")
RESIGN_PATTERN = re.compile(r"RESIGN:([XO])")


class ProtocolError(ValueError):
    """A reply is malformed or does not match the pending command."""


@dataclass(frozen=True)
class Snapshot:
    board: str
    turn: str
    phase: str
    result: str

    @property
    def game_over(self):
        return self.phase == "GAME_OVER"

    @property
    def winner(self):
        """Interpret the server's result; do not inspect winning lines."""
        return WINNERS.get(self.result)


@dataclass(frozen=True)
class Reply:
    kind: str
    snapshot: Snapshot | None = None
    error_code: str | None = None

    @property
    def message(self):
        if self.error_code is not None:
            return ERROR_MESSAGES[self.error_code]

        return "OK"

    @property
    def frame_error(self):
        """The receiver may need an LF boundary before another command."""
        return self.error_code in {
            "BADCMD",
            "TOOLONG",
            "TIMEOUT",
        }


def _parse_snapshot(payload):
    fields = payload.split(":")

    if (
        len(fields) != 8
        or fields[0] != "BOARD"
        or fields[2] != "TURN"
        or fields[4] != "PHASE"
        or fields[6] != "RESULT"
    ):
        raise ProtocolError(
            "The snapshot fields or their order are invalid."
        )

    board, turn, phase, result = (
        fields[1],
        fields[3],
        fields[5],
        fields[7],
    )

    if len(board) != 9 or any(cell not in ".XO" for cell in board):
        raise ProtocolError(
            "The board must contain nine .XO characters."
        )

    if phase == "IN_PROGRESS":
        if turn not in {"X", "O"} or result != "NONE":
            raise ProtocolError(
                "The active-game fields are inconsistent."
            )

    elif phase == "GAME_OVER":
        if turn != "-" or result not in TERMINAL_RESULTS:
            raise ProtocolError(
                "The completed-game fields are inconsistent."
            )

    else:
        raise ProtocolError(
            "A snapshot must be IN_PROGRESS or GAME_OVER."
        )

    return Snapshot(board, turn, phase, result)


def parse_response(command, text):
    """
    command: full command sent, without its LF.
    text: response returned by SerialLink.request(), without its LF.

    Known NACKs are accepted even for malformed outgoing commands.
    Success responses must match the command and snapshot format.
    """
    if not isinstance(command, str):
        raise ProtocolError(
            "The pending command must be text."
        )

    if (
        not isinstance(text, str)
        or not 1 <= len(text) <= MAX_FRAME_LENGTH
    ):
        raise ProtocolError(
            "The response length is invalid."
        )

    if any(
        ord(character) < 0x20 or ord(character) > 0x7E
        for character in text
    ):
        raise ProtocolError(
            "The response must be printable ASCII without LF."
        )

    if text.startswith("NACK:"):
        code = text[5:]

        if code not in ERROR_MESSAGES:
            raise ProtocolError(
                "The board returned an unknown NACK code."
            )

        return Reply(
            kind="NACK",
            error_code=code,
        )

    if command in {"CONNECT", "DISCONNECT"}:
        if text != "OK":
            raise ProtocolError(
                f"{command} must return exactly OK."
            )

        return Reply(kind="OK")

    move = MOVE_PATTERN.fullmatch(command)
    resign = RESIGN_PATTERN.fullmatch(command)

    if command == "STATE":
        if not text.startswith("BOARD:"):
            raise ProtocolError(
                "STATE must return BOARD: without OK:."
            )

        payload = text

    elif command == "NEW" or move is not None or resign is not None:
        if not text.startswith("OK:BOARD:"):
            raise ProtocolError(
                "This command must return OK:BOARD:."
            )

        payload = text[3:]

    else:
        raise ProtocolError(
            "Success was returned for an invalid command."
        )

    snapshot = _parse_snapshot(payload)

    if command == "NEW":
        if (
            snapshot.board != "........."
            or snapshot.turn != "X"
            or snapshot.phase != "IN_PROGRESS"
            or snapshot.result != "NONE"
        ):
            raise ProtocolError(
                "NEW did not return the specified empty game."
            )

    if resign is not None:
        expected_result = f"RESIGN_{resign.group(1)}"

        if (
            not snapshot.game_over
            or snapshot.result != expected_result
        ):
            raise ProtocolError(
                "RESIGN returned an inconsistent result."
            )

    if move is not None and snapshot.game_over:
        allowed_results = {
            f"WIN_{move.group(1)}",
            "DRAW",
        }

        if snapshot.result not in allowed_results:
            raise ProtocolError(
                "MOVE returned an inconsistent terminal result."
            )

    return Reply(
        kind="SNAPSHOT",
        snapshot=snapshot,
    )


if __name__ == "__main__":
    example = (
        "OK:BOARD:.........:TURN:X:"
        "PHASE:IN_PROGRESS:RESULT:NONE"
    )

    reply = parse_response("NEW", example)

    print("Offline response-format example:")
    print(f"Board:  {reply.snapshot.board}")
    print(f"Turn:   {reply.snapshot.turn}")
    print(f"Phase:  {reply.snapshot.phase}")
    print(f"Result: {reply.snapshot.result}")