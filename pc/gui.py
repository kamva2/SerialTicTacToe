"""Tkinter client for the STM32 serial Tic-Tac-Toe server."""

from __future__ import annotations

import queue
import tkinter as tk
from tkinter import ttk

from gui_worker import SerialWorker

POLL_INTERVAL_MS = 250
EVENT_INTERVAL_MS = 40


class TicTacToeApp:
    def __init__(self, root, worker_factory=SerialWorker):
        self.root = root
        self.worker = worker_factory()

        self.pending = False
        self.port_open = False
        self.connected = False
        self.faulted = False
        self.closing = False
        self.stop_sent = False
        self.worker_dead_reported = False

        self.phase = "IDLE"
        self.snapshot = None
        self.port_labels = {}
        self.last_poll_error = None

        self.port_choice = tk.StringVar()
        self.status = tk.StringVar(
            value="Finding serial ports..."
        )
        self.game_status = tk.StringVar(
            value="No game connected."
        )

        self._build_widgets()

        self.port_choice.trace_add(
            "write",
            lambda *_: self._update_controls(),
        )

        self.worker.start()

        self.root.protocol(
            "WM_DELETE_WINDOW",
            self._on_close,
        )

        self.root.after(
            EVENT_INTERVAL_MS,
            self._drain_events,
        )

        self.root.after(
            POLL_INTERVAL_MS,
            self._poll_state,
        )

        self._refresh_ports()

    def _build_widgets(self):
        self.root.title(
            "EEE3095S - Serial Tic-Tac-Toe"
        )
        self.root.minsize(700, 680)

        outer = ttk.Frame(
            self.root,
            padding=16,
        )
        outer.pack(
            fill="both",
            expand=True,
        )

        ttk.Label(
            outer,
            text="Serial Tic-Tac-Toe",
            font=("Segoe UI", 20, "bold"),
        ).pack(anchor="w")

        ports = ttk.Frame(outer)
        ports.pack(
            fill="x",
            pady=(14, 8),
        )
        ports.columnconfigure(1, weight=1)

        ttk.Label(
            ports,
            text="Port:",
        ).grid(
            row=0,
            column=0,
            padx=(0, 6),
        )

        self.port_combo = ttk.Combobox(
            ports,
            textvariable=self.port_choice,
            state="readonly",
            width=36,
        )
        self.port_combo.grid(
            row=0,
            column=1,
            sticky="ew",
        )

        self.refresh_button = ttk.Button(
            ports,
            text="Refresh",
            command=self._refresh_ports,
        )
        self.refresh_button.grid(
            row=0,
            column=2,
            padx=5,
        )

        self.connect_button = ttk.Button(
            ports,
            text="Connect",
            command=self._connect,
        )
        self.connect_button.grid(
            row=0,
            column=3,
            padx=5,
        )

        self.disconnect_button = ttk.Button(
            ports,
            text="Disconnect",
            command=lambda: self._send_command(
                "DISCONNECT"
            ),
        )
        self.disconnect_button.grid(
            row=0,
            column=4,
            padx=(5, 0),
        )

        actions = ttk.Frame(outer)
        actions.pack(
            fill="x",
            pady=6,
        )

        self.new_button = ttk.Button(
            actions,
            text="New Game",
            command=lambda: self._send_command("NEW"),
        )
        self.new_button.pack(side="left")

        self.resign_button = ttk.Button(
            actions,
            text="Resign",
            command=self._resign,
        )
        self.resign_button.pack(
            side="left",
            padx=8,
        )

        ttk.Label(
            outer,
            textvariable=self.game_status,
            font=("Segoe UI", 13, "bold"),
        ).pack(
            anchor="w",
            pady=10,
        )

        board = ttk.Frame(outer)
        board.pack(
            fill="both",
            expand=True,
        )

        self.cells = []

        for index in range(9):
            button = tk.Button(
                board,
                text="",
                font=("Segoe UI", 28, "bold"),
                background="white",
                activebackground="#e8eef5",
                relief="groove",
                borderwidth=1,
                command=lambda cell=index: self._move(
                    cell
                ),
            )
            button.grid(
                row=index // 3,
                column=index % 3,
                sticky="nsew",
                padx=3,
                pady=3,
            )

            self.cells.append(button)

        for index in range(3):
            board.rowconfigure(
                index,
                weight=1,
                minsize=70,
            )
            board.columnconfigure(
                index,
                weight=1,
            )

        ttk.Label(
            outer,
            textvariable=self.status,
            wraplength=660,
        ).pack(
            anchor="w",
            fill="x",
            pady=(12, 8),
        )

        self.log = tk.Text(
            outer,
            height=6,
            state="disabled",
            font=("Consolas", 9),
            wrap="word",
        )
        self.log.pack(fill="x")

    def _log(self, message):
        self.log.configure(state="normal")
        self.log.insert("end", message + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _update_controls(self):
        ready = (
            not self.pending
            and not self.closing
            and self.worker.is_alive()
        )

        healthy_session = (
            self.connected
            and not self.faulted
        )

        playing = (
            healthy_session
            and self.phase == "IN_PROGRESS"
        )

        def enable(widget, condition):
            widget.configure(
                state=(
                    "normal"
                    if condition
                    else "disabled"
                )
            )

        self.port_combo.configure(
            state=(
                "readonly"
                if ready and not self.port_open
                else "disabled"
            )
        )

        enable(
            self.refresh_button,
            ready and not self.port_open,
        )

        enable(
            self.connect_button,
            ready
            and not self.port_open
            and self.port_choice.get() in self.port_labels,
        )

        enable(
            self.disconnect_button,
            ready and self.port_open,
        )

        enable(
            self.new_button,
            ready
            and healthy_session
            and self.phase in {"IDLE", "GAME_OVER"},
        )

        enable(
            self.resign_button,
            ready and playing,
        )

        # The server decides whether a cell is occupied.
        for button in self.cells:
            enable(
                button,
                ready and playing,
            )

    def _submit(
        self,
        operation,
        command="",
        port_name="",
        automatic=False,
    ):
        if (
            self.pending
            or self.closing
            or not self.worker.is_alive()
        ):
            return False

        accepted = self.worker.submit(
            operation,
            command=command,
            port_name=port_name,
            automatic=automatic,
        )

        if not accepted:
            return False

        self.pending = True

        if not automatic:
            if operation == "CONNECT":
                self.status.set(
                    f"Connecting to {port_name}..."
                )
                self._log(
                    f"> CONNECT ({port_name})"
                )

            elif operation == "COMMAND":
                self.status.set(
                    f"Waiting for {command}..."
                )
                self._log(f"> {command}")

        self._update_controls()
        return True

    def _refresh_ports(self):
        self._submit("PORTS")

    def _connect(self):
        port_name = self.port_labels.get(
            self.port_choice.get()
        )

        if port_name is None:
            self.status.set(
                "Select the USB-to-UART adapter's port first."
            )
            return

        self._submit(
            "CONNECT",
            port_name=port_name,
        )

    def _send_command(self, command):
        if not self.port_open or self.faulted:
            return

        if (
            command != "DISCONNECT"
            and not self.connected
        ):
            return

        self._submit(
            "COMMAND",
            command=command,
        )

    def _move(self, index):
        if (
            self.connected
            and not self.faulted
            and self.phase == "IN_PROGRESS"
            and self.snapshot is not None
        ):
            self._send_command(
                f"MOVE:{self.snapshot.turn}:{index}"
            )

    def _resign(self):
        if (
            self.snapshot is not None
            and self.phase == "IN_PROGRESS"
        ):
            self._send_command(
                f"RESIGN:{self.snapshot.turn}"
            )

    def _poll_state(self):
        if (
            self.connected
            and not self.faulted
            and not self.pending
            and not self.closing
        ):
            self._submit(
                "COMMAND",
                command="STATE",
                automatic=True,
            )

        self.root.after(
            POLL_INTERVAL_MS,
            self._poll_state,
        )

    def _clear_confirmed_game(self):
        self.snapshot = None
        self.phase = "IDLE"

        for button in self.cells:
            button.configure(text="")

        self.game_status.set(
            "Connected - start a new game."
            if self.connected
            else "No game connected."
        )

    @staticmethod
    def _describe_snapshot(snapshot):
        if not snapshot.game_over:
            return f"{snapshot.turn} to move"

        if snapshot.result == "DRAW":
            return "Draw"

        if snapshot.result.startswith("RESIGN_"):
            player = snapshot.result[-1]

            return (
                f"{player} resigned - "
                f"{snapshot.winner} wins"
            )

        return f"{snapshot.winner} wins"

    def _render_snapshot(self, snapshot):
        self.snapshot = snapshot
        self.phase = snapshot.phase

        for button, cell in zip(
            self.cells,
            snapshot.board,
        ):
            colour = (
                "#17324d"
                if cell == "X"
                else "#087f8c"
            )

            button.configure(
                text="" if cell == "." else cell,
                foreground=colour,
                disabledforeground=colour,
            )

        self.game_status.set(
            self._describe_snapshot(snapshot)
        )

    def _mark_fault(self, message):
        self.pending = False
        self.connected = False
        self.port_open = False
        self.faulted = True

        self.status.set(
            f"Communication error: {message} "
            "Reset the board before reconnecting."
        )

        self._log(f"! {message}")

        if self.snapshot is not None:
            self.game_status.set(
                "Last confirmed: "
                + self._describe_snapshot(self.snapshot)
            )

    def _apply_event(self, event):
        self.port_open = event.port_open
        self.connected = event.session_connected

        if event.error is not None:
            self._mark_fault(
                event.error or "Unknown serial error."
            )
            return

        if event.operation == "PORTS":
            previous = self.port_choice.get()

            self.port_labels = {
                f"{name} - {description}": name
                for name, description in event.ports
            }

            labels = tuple(self.port_labels)

            self.port_combo.configure(values=labels)

            self.port_choice.set(
                previous
                if previous in labels
                else ""
            )

            if self.faulted:
                self.status.set(
                    "Reset the board, select its UART port, "
                    "then Connect."
                )

            elif labels:
                self.status.set(
                    "Select the USB-to-UART adapter's port."
                )

            else:
                self.status.set(
                    "No serial ports found. "
                    "Connect the adapter and Refresh."
                )

            return

        reply = event.reply

        if reply is None:
            self._mark_fault(
                "The worker returned no response."
            )
            return

        if event.operation == "CONNECT":
            self.faulted = False

        if reply.kind == "OK":
            self.last_poll_error = None
            self._clear_confirmed_game()

            self.status.set(
                "Connected."
                if self.connected
                else "Disconnected."
            )

            self._log("< OK")

        elif reply.kind == "SNAPSHOT":
            self.last_poll_error = None
            self._render_snapshot(reply.snapshot)

            if not event.automatic:
                command_name = event.command.split(
                    ":",
                    1,
                )[0]

                self.status.set(
                    f"{command_name} accepted."
                )

                self._log(
                    f"< {reply.snapshot}"
                )

        else:
            quiet_idle_poll = (
                event.automatic
                and event.command == "STATE"
                and self.phase == "IDLE"
                and reply.error_code == "NOGAME"
            )

            if not quiet_idle_poll:
                self.status.set(reply.message)

                if (
                    not event.automatic
                    or self.last_poll_error != reply.error_code
                ):
                    self._log(
                        f"< NACK:{reply.error_code} "
                        f"- {reply.message}"
                    )

                if event.automatic:
                    self.last_poll_error = reply.error_code

            if (
                not self.connected
                and self.snapshot is not None
            ):
                self.game_status.set(
                    "Last confirmed: "
                    + self._describe_snapshot(self.snapshot)
                )

            if (
                event.operation == "CONNECT"
                and reply.error_code == "BUSY"
            ):
                self.status.set(
                    "The board retains a game. "
                    "Disconnect explicitly to end that session "
                    "before connecting again."
                )

    def _drain_events(self):
        while True:
            try:
                event = self.worker.events.get_nowait()

            except queue.Empty:
                break

            self.pending = False

            if event.operation == "STOP":
                if event.error is not None:
                    print(
                        "Session shutdown was not confirmed: "
                        f"{event.error}"
                    )

                self.root.destroy()
                return

            self._apply_event(event)

        if (
            not self.worker.is_alive()
            and not self.stop_sent
            and not self.worker_dead_reported
        ):
            self.worker_dead_reported = True

            self._mark_fault(
                "The serial worker stopped. "
                "Restart the application."
            )

        if self.closing and self._request_stop():
            return

        self._update_controls()

        self.root.after(
            EVENT_INTERVAL_MS,
            self._drain_events,
        )

    def _on_close(self):
        if self.closing:
            return

        self.closing = True

        self.status.set(
            "Closing the serial session..."
        )

        self._update_controls()

        # Wait for a pending transaction before submitting STOP.
        if not self.pending:
            self._request_stop()

    def _request_stop(self):
        if self.stop_sent or self.pending:
            return False

        if not self.worker.is_alive():
            self.root.destroy()
            return True

        if self.worker.submit("STOP"):
            self.stop_sent = True
            self.pending = True

            self.status.set(
                "Closing the serial session..."
            )

        return False


if __name__ == "__main__":
    root = tk.Tk()
    app = TicTacToeApp(root)
    root.mainloop()