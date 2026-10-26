"""Hand-drawn Tkinter client for the STM32 Tic-Tac-Toe server."""

from __future__ import annotations

import queue
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox

from PIL import Image, ImageOps, ImageTk

from gui_worker import SerialWorker


POLL_INTERVAL_MS = 1000
EVENT_INTERVAL_MS = 40

ASSETS = Path(__file__).resolve().parent

PAPER = "#f5f1eb"
WHITE = "#ffffff"
INK = "#181513"
RED = "#aa0000"
MUTED = "#766e67"
BORDER = "#e1d9d0"

# Coordinates in the current 523 x 452 Board.jpeg.
X_EDGES = (55, 184, 324, 451)
Y_EDGES = (30, 159, 293, 423)


def load_art(filename, trim=False):
    path = ASSETS / filename

    with Image.open(path) as source:
        image = ImageOps.exif_transpose(source).convert("RGBA")

    paper = Image.new("RGBA", image.size, "white")
    paper.alpha_composite(image)
    image = paper.convert("RGB")

    if trim:
        mask = image.convert("L").point(
            lambda value: 255 if value < 250 else 0
        )
        bounds = mask.getbbox()

        if bounds is None:
            raise ValueError(
                f"{filename} contains no visible mark."
            )

        image = image.crop(bounds)

    return image


class CanvasCell:
    """Connect the image board to the GUI controller."""

    def __init__(self, board, index):
        self.board = board
        self.index = index
        self.text = ""
        self.state = "disabled"

    def configure(self, **options):
        if "text" in options and options["text"] != self.text:
            self.text = options["text"]
            self.board.schedule_marks()

        if "state" in options and options["state"] != self.state:
            self.state = options["state"]
            self.board.update_hover()

    def cget(self, option):
        if option == "state":
            return self.state

        if option == "text":
            return self.text

        raise KeyError(option)


class ImageBoard(tk.Canvas):
    def __init__(self, parent, on_move):
        super().__init__(
            parent,
            background=WHITE,
            highlightthickness=0,
            borderwidth=0,
        )

        self.on_move = on_move
        self.board_art = load_art("Board.jpeg")

        self.symbols = {
            "X": load_art("X_modified.png", trim=True),
            "O": load_art("O_modified.png", trim=True),
        }

        if self.board_art.size != (523, 452):
            raise ValueError(
                "This layout expects the current "
                "523 x 452 Board.jpeg."
            )

        self.cells = [
            CanvasCell(self, index)
            for index in range(9)
        ]

        self.scale_x = self.scale_y = 0.0
        self.origin_x = self.origin_y = 0.0

        self.hover = None
        self.board_photo = None
        self.mark_photos = {}

        self.resize_job = None
        self.mark_job = None

        self.bind("<Configure>", self.schedule_redraw)
        self.bind("<Motion>", self._motion)
        self.bind("<Leave>", self._leave)
        self.bind("<Button-1>", self._click)

    def schedule_redraw(self, _event=None):
        if self.resize_job is None:
            self.resize_job = self.after_idle(
                self._redraw
            )

    def schedule_marks(self):
        if self.mark_job is None:
            self.mark_job = self.after_idle(
                self._draw_marks
            )

    def _redraw(self):
        self.resize_job = None

        if self.mark_job is not None:
            self.after_cancel(self.mark_job)
            self.mark_job = None

        width = max(1, self.winfo_width() - 20)
        height = max(1, self.winfo_height() - 20)

        fitted = ImageOps.contain(
            self.board_art,
            (width, height),
            method=Image.Resampling.LANCZOS,
        )

        self.origin_x = (
            self.winfo_width() - fitted.width
        ) / 2

        self.origin_y = (
            self.winfo_height() - fitted.height
        ) / 2

        self.scale_x = fitted.width / self.board_art.width
        self.scale_y = fitted.height / self.board_art.height

        self.delete("all")
        self.mark_photos.clear()

        self.board_photo = ImageTk.PhotoImage(
            fitted,
            master=self,
        )

        self.create_image(
            self.origin_x,
            self.origin_y,
            image=self.board_photo,
            anchor="nw",
            tags="background",
        )

        self.hover = None
        self._draw_marks()
        self.update_hover()

    def _draw_marks(self):
        self.mark_job = None
        self.delete("marks")

        if self.scale_x <= 0 or self.scale_y <= 0:
            return

        for cell in self.cells:
            if cell.text not in self.symbols:
                continue

            row, column = divmod(cell.index, 3)

            x1, x2 = X_EDGES[column:column + 2]
            y1, y2 = Y_EDGES[row:row + 2]

            limit = max(
                1,
                int(
                    0.72 * min(
                        (x2 - x1) * self.scale_x,
                        (y2 - y1) * self.scale_y,
                    )
                ),
            )

            key = (cell.text, limit)

            if key not in self.mark_photos:
                fitted = ImageOps.contain(
                    self.symbols[cell.text],
                    (limit, limit),
                    method=Image.Resampling.LANCZOS,
                )

                self.mark_photos[key] = ImageTk.PhotoImage(
                    fitted,
                    master=self,
                )

            self.create_image(
                self.origin_x
                + (x1 + x2) * self.scale_x / 2,
                self.origin_y
                + (y1 + y2) * self.scale_y / 2,
                image=self.mark_photos[key],
                tags="marks",
            )

        self.update_hover()

    def hit_test(self, x, y):
        if self.scale_x <= 0 or self.scale_y <= 0:
            return None

        left = self.origin_x + X_EDGES[0] * self.scale_x
        right = self.origin_x + X_EDGES[-1] * self.scale_x
        top = self.origin_y + Y_EDGES[0] * self.scale_y
        bottom = self.origin_y + Y_EDGES[-1] * self.scale_y

        if not (left <= x < right and top <= y < bottom):
            return None

        image_x = (x - self.origin_x) / self.scale_x
        image_y = (y - self.origin_y) / self.scale_y

        if any(
            abs(image_x - edge) < 10
            for edge in X_EDGES[1:-1]
        ):
            return None

        if any(
            abs(image_y - edge) < 10
            for edge in Y_EDGES[1:-1]
        ):
            return None

        column = next(
            index for index in range(3)
            if image_x < X_EDGES[index + 1]
        )

        row = next(
            index for index in range(3)
            if image_y < Y_EDGES[index + 1]
        )

        return row * 3 + column

    def _motion(self, event):
        self.hover = self.hit_test(event.x, event.y)
        self.update_hover()

    def _leave(self, _event=None):
        self.hover = None
        self.update_hover()

    def update_hover(self):
        self.delete("hover")

        active = (
            self.hover is not None
            and self.cells[self.hover].state == "normal"
        )

        self.configure(
            cursor="hand2" if active else "arrow"
        )

        if active:
            row, column = divmod(self.hover, 3)

            x1, x2 = X_EDGES[column:column + 2]
            y1, y2 = Y_EDGES[row:row + 2]

            self.create_rectangle(
                self.origin_x + (x1 + 12) * self.scale_x,
                self.origin_y + (y1 + 12) * self.scale_y,
                self.origin_x + (x2 - 12) * self.scale_x,
                self.origin_y + (y2 - 12) * self.scale_y,
                outline="#ce8d8d",
                width=2,
                dash=(4, 4),
                tags="hover",
            )

    def _click(self, event):
        index = self.hit_test(event.x, event.y)

        if (
            index is not None
            and self.cells[index].state == "normal"
        ):
            # Draw only after receiving the server snapshot.
            self.on_move(index)


class TicTacToeApp:
    def __init__(self, root, worker_factory=SerialWorker):
        self.root = root
        self.worker = worker_factory()

        self.pending = False
        self.pending_automatic = False
        self.queued_command = None

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

    def _button(self, parent, text, command, primary=False):
        return tk.Button(
            parent,
            text=text,
            command=command,
            font=("Segoe UI", 10, "bold"),
            background=RED if primary else "#eee8e1",
            foreground=WHITE if primary else INK,
            activebackground=(
                "#8d0000" if primary else "#e1d8ce"
            ),
            activeforeground=WHITE if primary else INK,
            disabledforeground="#b6aaa0",
            relief="flat",
            borderwidth=0,
            padx=15,
            pady=10,
            cursor="hand2",
        )

    def _build_widgets(self):
        self.root.title("Tic Tac Toe - Ink and Paper")
        self.root.configure(background=PAPER)

        width = min(
            1100,
            self.root.winfo_screenwidth() - 60,
        )

        height = min(
            820,
            self.root.winfo_screenheight() - 90,
        )

        self.root.geometry(f"{width}x{height}")

        self.root.minsize(
            min(940, width),
            min(650, height),
        )

        style = ttk.Style(self.root)
        style.theme_use("clam")

        style.configure(
            "Ink.TCombobox",
            fieldbackground=WHITE,
            background=PAPER,
            foreground=INK,
            padding=6,
        )

        outer = tk.Frame(self.root, background=PAPER)
        outer.pack(
            fill="both",
            expand=True,
            padx=22,
            pady=18,
        )

        header = tk.Frame(outer, background=PAPER)
        header.pack(fill="x")

        tk.Label(
            header,
            text="tic tac toe",
            font=("Segoe Print", 30, "bold"),
            background=PAPER,
            foreground=INK,
        ).pack(anchor="w")

        underline = tk.Canvas(
            header,
            height=10,
            background=PAPER,
            highlightthickness=0,
        )

        underline.pack(fill="x")

        underline.create_line(
            2, 5, 95, 3, 195, 6, 285, 4,
            fill=RED,
            width=5,
            smooth=True,
            capstyle="round",
        )

        content = tk.Frame(outer, background=PAPER)
        content.pack(
            fill="both",
            expand=True,
            pady=(16, 0),
        )

        content.columnconfigure(0, weight=1)
        content.columnconfigure(1, minsize=285)
        content.rowconfigure(0, weight=1)

        play = tk.Frame(
            content,
            background=WHITE,
            highlightbackground=BORDER,
            highlightthickness=1,
        )

        play.grid(
            row=0,
            column=0,
            sticky="nsew",
            padx=(0, 16),
        )

        tk.Label(
            play,
            textvariable=self.game_status,
            font=("Segoe Print", 16, "bold"),
            background=WHITE,
            foreground=RED,
        ).pack(
            anchor="w",
            padx=18,
            pady=(16, 4),
        )

        self.image_board = ImageBoard(play, self._move)
        self.image_board.pack(
            fill="both",
            expand=True,
            padx=8,
            pady=8,
        )

        self.cells = self.image_board.cells

        actions = tk.Frame(play, background=WHITE)
        actions.pack(
            fill="x",
            padx=18,
            pady=(0, 18),
        )

        self.new_button = self._button(
            actions,
            "NEW GAME",
            lambda: self._send_command("NEW"),
            primary=True,
        )

        self.new_button.pack(side="left")

        self.resign_button = self._button(
            actions,
            "RESIGN",
            self._resign,
        )

        self.resign_button.pack(
            side="left",
            padx=10,
        )

        side = tk.Frame(
            content,
            background=WHITE,
            width=285,
            highlightbackground=BORDER,
            highlightthickness=1,
        )

        side.grid(
            row=0,
            column=1,
            sticky="nsew",
        )

        side.pack_propagate(False)

        panel = tk.Frame(side, background=WHITE)
        panel.pack(
            fill="both",
            expand=True,
            padx=16,
            pady=16,
        )

        def label(text):
            tk.Label(
                panel,
                text=text,
                font=("Segoe Print", 15, "bold"),
                background=WHITE,
                foreground=INK,
            ).pack(
                anchor="w",
                pady=(0, 10),
            )

        label("Connection")

        self.port_combo = ttk.Combobox(
            panel,
            textvariable=self.port_choice,
            state="readonly",
            style="Ink.TCombobox",
            font=("Segoe UI", 9),
            width=26,
        )

        self.port_combo.pack(
            fill="x",
            pady=(0, 8),
        )

        self.refresh_button = self._button(
            panel,
            "REFRESH PORTS",
            self._refresh_ports,
        )

        self.refresh_button.pack(
            fill="x",
            pady=(0, 8),
        )

        row = tk.Frame(panel, background=WHITE)
        row.pack(fill="x")

        self.connect_button = self._button(
            row,
            "CONNECT",
            self._connect,
            primary=True,
        )

        self.connect_button.pack(
            side="left",
            fill="x",
            expand=True,
        )

        self.disconnect_button = self._button(
            row,
            "DISCONNECT",
            lambda: self._send_command("DISCONNECT"),
        )

        self.disconnect_button.pack(
            side="left",
            fill="x",
            expand=True,
            padx=(6, 0),
        )

        tk.Frame(
            panel,
            height=1,
            background=BORDER,
        ).pack(
            fill="x",
            pady=18,
        )

        label("Status")

        tk.Label(
            panel,
            textvariable=self.status,
            background=WHITE,
            foreground=MUTED,
            font=("Segoe UI", 10),
            wraplength=245,
            justify="left",
            anchor="w",
        ).pack(
            fill="x",
            pady=(0, 20),
        )

        label("Activity")

        self.log = tk.Text(
            panel,
            height=8,
            state="disabled",
            background="#faf7f3",
            foreground=INK,
            font=("Consolas", 9),
            wrap="word",
            relief="flat",
            borderwidth=0,
            highlightbackground=BORDER,
            highlightthickness=1,
        )

        self.log.pack(
            fill="both",
            expand=True,
        )

    def _log(self, message):
        self.log.configure(state="normal")
        self.log.insert("end", message + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _update_controls(self):
        ready = (
            not self.closing
            and self.worker.is_alive()
            and self.queued_command is None
            and (not self.pending or self.pending_automatic)
        )

        healthy_session = (
            self.connected and not self.faulted
        )

        playing = (
            healthy_session
            and self.phase == "IN_PROGRESS"
        )

        def enable(widget, condition):
            current = str(widget.cget("state"))

            if condition:
                if current == "disabled":
                    widget.configure(state="normal")

            elif current != "disabled":
                widget.configure(state="disabled")

        port_state = (
            "readonly"
            if ready and not self.port_open
            else "disabled"
        )

        if str(self.port_combo.cget("state")) != port_state:
            self.port_combo.configure(state=port_state)

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

        for cell in self.cells:
            enable(cell, ready and playing)

    def _submit(
        self,
        operation,
        command="",
        port_name="",
        automatic=False,
    ):
        if self.closing or not self.worker.is_alive():
            return False

        if self.pending:
            if (
                self.pending_automatic
                and not automatic
                and operation == "COMMAND"
                and self.queued_command is None
            ):
                self.queued_command = (
                    command,
                    (self.phase, self.snapshot),
                )

                self.status.set(
                    f"Waiting for {command}..."
                )

                self._update_controls()
                return True

            return False

        if self.queued_command is not None:
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
        self.pending_automatic = automatic

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

    def _dispatch_queued(self):
        if (
            self.queued_command is None
            or self.pending
            or self.closing
        ):
            return False

        command, previous_view = self.queued_command
        self.queued_command = None

        if not self.port_open or self.faulted:
            return False

        if command != "DISCONNECT":
            if not self.connected:
                return False

            if (self.phase, self.snapshot) != previous_view:
                self.status.set(
                    "The board changed. "
                    "Please choose your action again."
                )

                self._log(
                    "! Action cancelled because the board changed."
                )
                return False

            name = command.split(":", 1)[0]

            if name == "NEW":
                available = self.phase in {
                    "IDLE",
                    "GAME_OVER",
                }

            elif name in {"MOVE", "RESIGN"}:
                player = command.split(":")[1]

                available = (
                    self.phase == "IN_PROGRESS"
                    and self.snapshot is not None
                    and player == self.snapshot.turn
                )

            else:
                available = True

            if not available:
                self.status.set(
                    "That action is no longer available."
                )
                return False

        return self._submit(
            "COMMAND",
            command=command,
        )

    def _poll_state(self):
        # Check the connection without limiting thinking time.
        if (
            self.connected
            and not self.faulted
            and not self.pending
            and self.queued_command is None
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
        self.queued_command = None
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
        description = self._describe_snapshot(snapshot)
        self.phase = snapshot.phase

        if self.game_status.get() != description:
            self.game_status.set(description)

        if snapshot == self.snapshot:
            return

        self.snapshot = snapshot

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

    def _mark_fault(self, message):
        self.pending = False
        self.pending_automatic = False
        self.queued_command = None

        self.connected = False
        self.port_open = False
        self.faulted = True

        next_step = (
            "Select the UART port and Connect to synchronise."
            if self.worker.is_alive()
            else "Restart the application."
        )

        self.status.set(
            f"Communication error: {message} {next_step}"
        )

        self._log(f"! {message}")

        self.game_status.set(
            "Last confirmed: "
            + self._describe_snapshot(self.snapshot)
            if self.snapshot is not None
            else "No game connected."
        )

    def _apply_event(self, event):
        self.port_open = event.port_open
        self.connected = event.session_connected

        recovered = (
            event.automatic
            and event.recovery_error is not None
        )

        if recovered:
            if (
                self.queued_command is not None
                and self.queued_command[0] != "DISCONNECT"
            ):
                self.queued_command = None

                self._log(
                    "! Pending action cancelled during recovery."
                )

            self._log(
                "! Background STATE failed: "
                f"{event.recovery_error}"
            )

        if event.error is not None:
            self._mark_fault(event.error)
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
                previous if previous in labels else ""
            )

            if self.faulted:
                self.status.set(
                    "Select the UART port and "
                    "Connect to synchronise."
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

        connecting = event.operation == "CONNECT"

        if connecting:
            self.faulted = False
            self.last_poll_error = None

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
                name = event.command.split(":", 1)[0]

                self.status.set(
                    "Connected. Retained game restored."
                    if connecting
                    else f"{name} accepted."
                )

                self._log(
                    f"< STATE: {reply.snapshot}"
                    if connecting
                    else f"< {reply.snapshot}"
                )

        elif (
            reply.error_code == "NOGAME"
            and self.connected
            and (
                connecting
                or event.command == "STATE"
            )
        ):
            self.last_poll_error = None

            if (
                connecting
                or self.phase != "IDLE"
                or self.snapshot is not None
            ):
                queued = self.queued_command
                self._clear_confirmed_game()

                if not connecting:
                    self.queued_command = queued

            if connecting:
                self.status.set(
                    "Connected. Start a new game."
                )

                self._log(
                    "< STATE: NACK:NOGAME (connected, IDLE)"
                )

        else:
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

            if not self.connected:
                self.game_status.set(
                    "Last confirmed: "
                    + self._describe_snapshot(self.snapshot)
                    if self.snapshot is not None
                    else "No game connected."
                )

        if event.notice:
            self._log(f"* {event.notice}")
            self.status.set(event.notice)

    def _drain_events(self):
        while True:
            try:
                event = self.worker.events.get_nowait()

            except queue.Empty:
                break

            self.pending = False
            self.pending_automatic = False

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
                event.automatic
                and self.queued_command is not None
            ):
                command, _view = self.queued_command
                reply = event.reply

                usable_poll = (
                    event.error is None
                    and reply is not None
                    and (
                        reply.kind == "SNAPSHOT"
                        or (
                            reply.kind == "NACK"
                            and reply.error_code == "NOGAME"
                            and self.phase == "IDLE"
                        )
                    )
                )

                if (
                    command != "DISCONNECT"
                    and not usable_poll
                ):
                    self.queued_command = None

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

        if self.closing:
            self.queued_command = None

            if self._request_stop():
                return

        else:
            self._dispatch_queued()

        self._update_controls()

        self.root.after(
            EVENT_INTERVAL_MS,
            self._drain_events,
        )

    def _on_close(self):
        if self.closing:
            return

        self.closing = True
        self.queued_command = None

        self.status.set(
            "Closing the serial session..."
        )

        self._update_controls()

        if not self.pending:
            self._request_stop()

    def _request_stop(self):
        if self.stop_sent or self.pending:
            return False

        if not self.worker.is_alive():
            self.root.destroy()
            return True

        if self.worker.submit("STOP"):
            self.pending_automatic = False
            self.stop_sent = True
            self.pending = True

            self.status.set(
                "Closing the serial session..."
            )

        return False


if __name__ == "__main__":
    root = tk.Tk()

    try:
        app = TicTacToeApp(root)

    except (OSError, ValueError) as exc:
        print(f"GUI startup failed: {exc}")

        try:
            messagebox.showerror(
                "Theme images could not load",
                str(exc),
                parent=root,
            )

        except tk.TclError:
            pass

        finally:
            try:
                root.destroy()

            except tk.TclError:
                pass

    else:
        root.mainloop()