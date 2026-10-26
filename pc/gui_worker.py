"""Background serial worker. Never accesses Tkinter widgets."""

from __future__ import annotations

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

    def _request(self, command):
        text = self._link.request(command)
        reply = parse_response(command, text)

        if reply.frame_error:
            self._link.resynchronise()

        if reply.kind == "OK":
            if command == "CONNECT":
                self._session_connected = True

            elif command == "DISCONNECT":
                self._session_connected = False
                self._link.close()

        elif reply.error_code == "NOTCONNECTED":
            self._session_connected = False

        return reply

    def _process(self, task):
        if task.operation == "PORTS":
            return self._event(
                task,
                ports=tuple(self._link.available_ports()),
            )

        if task.operation == "CONNECT":
            self._link.open(task.port_name)
            reply = self._request("CONNECT")

            return self._event(
                task,
                reply=reply,
            )

        if task.operation == "COMMAND":
            reply = self._request(task.command)

            return self._event(
                task,
                reply=reply,
            )

        # STOP: finish a known session cleanly.
        if self._link.is_open and self._session_connected:
            reply = self._request("DISCONNECT")

            if reply.kind != "OK":
                raise ProtocolError(
                    "DISCONNECT was not acknowledged."
                )

        # CONNECT/BUSY leaves an unattached port.
        # Close it locally without silently clearing the retained game.
        # The user can explicitly request DISCONNECT before closing.
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

            # Allow the GUI to submit another job after it receives
            # this completion event.
            self._slot.release()
            self.events.put(event)
            self._tasks.task_done()

            if task.operation == "STOP":
                return