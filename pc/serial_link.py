"""Serial transport for the EEE3095S Tic-Tac-Toe protocol."""

from __future__ import annotations

import threading
import time

import serial
from serial.tools import list_ports

MAX_FRAME_LENGTH = 96
RESPONSE_TIMEOUT = 2.0
WRITE_TIMEOUT = 1.0


class LinkError(RuntimeError):
    """The serial link could not complete a reliable transaction."""


class SerialLink:
    """Use from one worker thread; only one request may be outstanding."""

    def __init__(self):
        self._port = None
        self._faulted = False
        self._request_lock = threading.Lock()

    @staticmethod
    def available_ports():
        return sorted(
            (port.device, port.description or "Serial port")
            for port in list_ports.comports()
        )

    @property
    def is_open(self):
        return self._port is not None and self._port.is_open

    @property
    def faulted(self):
        return self._faulted

    def open(self, port_name):
        if self.is_open:
            raise LinkError("A serial port is already open.")

        connection = serial.Serial(
            port=None,
            baudrate=115200,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=0.05,
            write_timeout=WRITE_TIMEOUT,
            xonxoff=False,
            rtscts=False,
            dsrdtr=False,
        )

        connection.dtr = False
        connection.rts = False
        connection.port = port_name

        try:
            connection.open()
            connection.reset_input_buffer()
        except (serial.SerialException, OSError) as exc:
            connection.close()
            raise LinkError(
                f"Cannot open {port_name}: {exc}"
            ) from exc

        self._port = connection
        self._faulted = False

    def close(self):
        connection = self._port
        self._port = None
        self._faulted = False

        if connection is not None:
            try:
                connection.close()
            except (serial.SerialException, OSError) as exc:
                raise LinkError(
                    f"Cannot close serial port: {exc}"
                ) from exc

    def resynchronise(self):
        """After a known frame NACK, send one bare LF."""
        if not self.is_open:
            raise LinkError("The serial port is not open.")

        if self._faulted:
            raise LinkError(
                "Restart the uncertain board/session first."
            )

        if not self._request_lock.acquire(blocking=False):
            raise LinkError(
                "Another serial request is already pending."
            )

        try:
            if self._port.in_waiting:
                raise LinkError(
                    "Unexpected input before resynchronisation."
                )

            if self._port.write(b"\n") != 1:
                raise LinkError(
                    "The resynchronisation LF could not be written."
                )

        except (serial.SerialException, OSError, LinkError) as exc:
            self._faulted = True
            raise LinkError(str(exc)) from exc

        finally:
            self._request_lock.release()

    def request(self, command):
        """Send a command without LF; return a response without LF."""
        try:
            payload = command.encode("ascii")
        except UnicodeEncodeError as exc:
            raise ValueError(
                "Commands must contain ASCII characters."
            ) from exc

        if not payload or len(payload) > MAX_FRAME_LENGTH:
            raise ValueError(
                "Command length must be 1 to 96 bytes."
            )

        if any(byte < 0x20 or byte > 0x7E for byte in payload):
            raise ValueError(
                "Do not include CR, LF or control characters."
            )

        if not self.is_open:
            raise LinkError(
                "Open the UART adapter's serial port first."
            )

        if self._faulted:
            raise LinkError(
                "Link outcome is uncertain. Restart the board/session "
                "before continuing."
            )

        if not self._request_lock.acquire(blocking=False):
            raise LinkError(
                "Another serial request is already pending."
            )

        try:
            connection = self._port

            if connection.in_waiting:
                raise LinkError(
                    "Unexpected serial input before the request."
                )

            frame = payload + b"\n"

            if connection.write(frame) != len(frame):
                raise LinkError(
                    "The complete request could not be written."
                )

            deadline = time.monotonic() + RESPONSE_TIMEOUT
            response = bytearray()

            while True:
                remaining = deadline - time.monotonic()

                if remaining <= 0:
                    raise LinkError(
                        "Response timed out; the command outcome "
                        "is unknown."
                    )

                connection.timeout = min(0.05, remaining)
                byte = connection.read(1)

                if not byte:
                    continue

                if byte == b"\n":
                    if not response:
                        raise LinkError(
                            "Received an empty response."
                        )

                    return response.decode("ascii")

                if len(response) >= MAX_FRAME_LENGTH:
                    raise LinkError(
                        "The response exceeded 96 bytes."
                    )

                if byte[0] < 0x20 or byte[0] > 0x7E:
                    raise LinkError(
                        "The response contained an invalid byte."
                    )

                response.extend(byte)

        except (serial.SerialException, OSError, LinkError) as exc:
            self._faulted = True
            raise LinkError(str(exc)) from exc

        finally:
            self._request_lock.release()


if __name__ == "__main__":
    ports = SerialLink.available_ports()

    if not ports:
        print("No serial ports detected.")
    else:
        print("Detected serial ports:")

        for name, description in ports:
            print(f"  {name}: {description}")