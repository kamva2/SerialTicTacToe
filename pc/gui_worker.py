"""Serial worker: bounded reads, no Tkinter calls or action retries."""

from dataclasses import dataclass
import queue
import threading

from responses import ProtocolError, Reply, parse_response
from serial_link import LinkError, SerialLink


@dataclass(frozen=True)
class Task:
    operation: str
    command: str = ""
    port_name: str = ""
    automatic: bool = False


@dataclass(frozen=True)
class WorkerEvent:
    operation: str
    command: str = ""
    automatic: bool = False
    reply: Reply | None = None
    ports: tuple[tuple[str, str], ...] = ()
    error: str | None = None
    port_open: bool = False
    session_connected: bool = False
    notice: str | None = None
    recovery_error: str | None = None


class SerialWorker(threading.Thread):
    def __init__(self, link_factory=SerialLink):
        super().__init__(daemon=True)

        self.events = queue.Queue()
        self._tasks = queue.Queue(maxsize=1)
        self._slot = threading.BoundedSemaphore(1)
        self._stop_requested = threading.Event()

        self._link_factory = link_factory
        self._link = None
        self._session_connected = False

    def submit(
        self,
        operation,
        command="",
        port_name="",
        automatic=False,
    ):
        if operation not in {
            "PORTS",
            "CONNECT",
            "COMMAND",
            "STOP",
        }:
            raise ValueError("Unknown worker operation.")

        if self._stop_requested.is_set():
            return False

        if not self._slot.acquire(blocking=False):
            return False

        task = Task(
            operation,
            command,
            port_name,
            automatic,
        )

        if operation == "STOP":
            self._stop_requested.set()

        self._tasks.put_nowait(task)
        return True

    def _event(self, task, **details):
        return WorkerEvent(
            operation=task.operation,
            command=(
                "CONNECT"
                if task.operation == "CONNECT"
                else task.command
            ),
            automatic=task.automatic,
            port_open=self._link.is_open,
            session_connected=self._session_connected,
            **details,
        )

    def _interpret(self, command, text):
        reply = parse_response(command, text)

        if reply.frame_error and command != "STATE":
            self._link.resynchronise()

        if reply.kind == "OK":
            if command == "CONNECT":
                self._session_connected = True

            elif command == "DISCONNECT":
                self._session_connected = False
                self._link.close()

        elif reply.error_code == "NOTCONNECTED":
            self._session_connected = False

        elif command == "STATE" and (
            reply.kind == "SNAPSHOT"
            or reply.error_code == "NOGAME"
        ):
            self._session_connected = True

        return reply

    def _request(self, command):
        return self._interpret(
            command,
            self._link.request(command),
        )

    def _read_state(self, mode="normal"):
        if mode == "probe":
            text = self._link.probe_state()

        elif mode == "recover":
            text = self._link.recover_state()

        else:
            text = self._link.request("STATE")

        reply = self._interpret("STATE", text)

        if (
            reply.kind != "SNAPSHOT"
            and reply.error_code not in {
                "NOGAME",
                "NOTCONNECTED",
            }
        ):
            raise ProtocolError(
                f"Unexpected STATE reply: {text!r}"
            )

        return reply

    def _close_if_unconnected(self, reply):
        if reply.error_code == "NOTCONNECTED":
            self._link.close()

    def _automatic_state(self, task):
        try:
            reply = self._read_state()

        except (LinkError, ProtocolError) as original:
            try:
                reply = self._read_state("recover")

            except (LinkError, ProtocolError) as recovery:
                sample = self._link.recovery_sample

                raise LinkError(
                    f"Background STATE failed: {original}; "
                    f"one recovery failed: {recovery}; "
                    f"discarded bytes: {sample!r}"
                ) from recovery

            detail = (
                f"{original}; discarded bytes: "
                f"{self._link.recovery_sample!r}"
            )

            self._close_if_unconnected(reply)

            return self._event(
                task,
                reply=reply,
                recovery_error=detail,
                notice=(
                    "Communication restored. "
                    "STM32 state synchronised."
                    if self._session_connected
                    else
                    "The STM32 has no session. "
                    "Connect to start again."
                ),
            )

        self._close_if_unconnected(reply)

        return self._event(
            task,
            reply=reply,
            notice=(
                "The STM32 has no session. "
                "Connect to start again."
                if not self._session_connected
                else None
            ),
        )

    def _process(self, task):
        if task.operation == "PORTS":
            return self._event(
                task,
                ports=tuple(
                    self._link.available_ports()
                ),
            )

        if task.operation == "CONNECT":
            self._link.open(task.port_name)

            # Read first so reconnecting can retain the game.
            reply = self._read_state("probe")

            if reply.error_code == "NOTCONNECTED":
                reply = self._request("CONNECT")

                if reply.kind != "OK":
                    raise ProtocolError(
                        "CONNECT was not acknowledged."
                    )

                notice = "Connected."

            elif reply.kind == "SNAPSHOT":
                notice = (
                    "Reconnected. "
                    "Game restored from the STM32."
                )

            else:
                notice = "Connected. Start a new game."

            return self._event(
                task,
                reply=reply,
                notice=notice,
            )

        if task.operation == "COMMAND":
            if task.automatic and task.command == "STATE":
                return self._automatic_state(task)

            # User actions are sent once only.
            reply = self._request(task.command)
            self._close_if_unconnected(reply)

            return self._event(
                task,
                reply=reply,
            )

        # STOP: explicitly close a confirmed session.
        if self._link.is_open and self._session_connected:
            reply = self._request("DISCONNECT")

            if reply.kind != "OK":
                raise ProtocolError(
                    "DISCONNECT was not acknowledged."
                )

        self._link.close()
        self._session_connected = False

        return self._event(task)

    def _failure(self, task, exc):
        message = str(exc)

        try:
            self._link.close()

        except (LinkError, OSError) as close_error:
            message += (
                " Closing the port also failed: "
                f"{close_error}"
            )

        self._session_connected = False

        return self._event(
            task,
            error=message,
        )

    def run(self):
        self._link = self._link_factory()

        while True:
            task = self._tasks.get()

            try:
                event = self._process(task)

            except (
                LinkError,
                ProtocolError,
                ValueError,
                OSError,
            ) as exc:
                event = self._failure(task, exc)

            self._slot.release()
            self.events.put(event)
            self._tasks.task_done()

            if task.operation == "STOP":
                return