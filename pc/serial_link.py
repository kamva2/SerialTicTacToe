"""Bounded UART transactions. Players have no thinking-time limit."""

import threading
import time

import serial
from serial.tools import list_ports

MAX_FRAME_LENGTH = 96
RESPONSE_TIMEOUT = 2.0
WRITE_TIMEOUT = 1.0
QUIET_SECONDS = 0.2
DRAIN_LIMIT = 1.5


class LinkError(RuntimeError):
    pass


class SerialLink:
    def __init__(self):
        self._port = None
        self._faulted = False
        self._last_command = None
        self._state_recovery_allowed = False
        self._recovery_sample = bytearray()
        self._request_lock = threading.Lock()

    @staticmethod
    def available_ports():
        return sorted(
            (p.device, p.description or "Serial port")
            for p in list_ports.comports()
        )

    @property
    def is_open(self):
        return self._port is not None and self._port.is_open

    @property
    def faulted(self):
        return self._faulted

    @property
    def recovery_sample(self):
        return bytes(self._recovery_sample)

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
        self._last_command = None
        self._state_recovery_allowed = False
        self._recovery_sample.clear()

    def close(self):
        connection, self._port = self._port, None
        self._faulted = False
        self._last_command = None
        self._state_recovery_allowed = False

        if connection is not None:
            try:
                connection.close()
            except (serial.SerialException, OSError) as exc:
                raise LinkError(
                    f"Cannot close serial port: {exc}"
                ) from exc

    def _acquire(self):
        if not self.is_open:
            raise LinkError("Open the UART adapter's port first.")

        if not self._request_lock.acquire(blocking=False):
            raise LinkError(
                "Another serial request is already pending."
            )

    def _exchange_locked(self, command, payload):
        connection = self._port

        if connection.in_waiting:
            raise LinkError(
                "Unexpected serial input before the request."
            )

        self._last_command = command
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
                    raise LinkError("Received an empty response.")

                return response.decode("ascii")

            if len(response) >= MAX_FRAME_LENGTH:
                raise LinkError(
                    "The response exceeded 96 bytes."
                )

            if not 0x20 <= byte[0] <= 0x7E:
                raise LinkError(
                    f"Invalid response byte 0x{byte[0]:02X}; "
                    f"received prefix {bytes(response[:32])!r}."
                )

            response.extend(byte)

    def request(self, command):
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

        if any(
            not 0x20 <= byte <= 0x7E
            for byte in payload
        ):
            raise ValueError(
                "Do not include CR, LF or control characters."
            )

        if self._faulted:
            raise LinkError(
                "Reconnect to synchronise the uncertain session."
            )

        self._acquire()

        try:
            # A blocked request cannot enable recovery.
            self._state_recovery_allowed = command == "STATE"

            return self._exchange_locked(command, payload)

        except (
            serial.SerialException,
            OSError,
            LinkError,
        ) as exc:
            self._faulted = True
            raise LinkError(str(exc)) from exc

        finally:
            self._request_lock.release()

    def resynchronise(self):
        """A known frame NACK may require a terminating LF."""
        if self._faulted:
            raise LinkError(
                "Reconnect to synchronise the uncertain session."
            )

        self._acquire()

        try:
            if self._port.in_waiting:
                raise LinkError(
                    "Unexpected input before resynchronisation."
                )

            if self._port.write(b"\n") != 1:
                raise LinkError(
                    "Could not write the resynchronisation LF."
                )

        except (
            serial.SerialException,
            OSError,
            LinkError,
        ) as exc:
            self._faulted = True
            raise LinkError(str(exc)) from exc

        finally:
            self._request_lock.release()

    def _drain_until_quiet(self):
        deadline = time.monotonic() + DRAIN_LIMIT
        quiet_since = time.monotonic()

        while True:
            now = time.monotonic()
            quiet_left = (
                QUIET_SECONDS - (now - quiet_since)
            )

            if quiet_left <= 0:
                return

            if now >= deadline:
                raise LinkError(
                    "Serial input did not become quiet."
                )

            self._port.timeout = min(
                0.05,
                quiet_left,
                deadline - now,
            )

            data = self._port.read(
                min(
                    MAX_FRAME_LENGTH + 1,
                    self._port.in_waiting or 1,
                )
            )

            if data:
                room = max(
                    0,
                    32 - len(self._recovery_sample),
                )

                self._recovery_sample.extend(data[:room])
                quiet_since = time.monotonic()

    def _state_fence(self):
        self._acquire()

        try:
            self._faulted = True
            self._recovery_sample.clear()

            self._drain_until_quiet()

            if self._port.write(b"\n") != 1:
                raise LinkError(
                    "Could not write the recovery LF."
                )

            self._drain_until_quiet()

            text = self._exchange_locked(
                "STATE",
                b"STATE",
            )

            self._faulted = False
            return text

        except (
            serial.SerialException,
            OSError,
            LinkError,
        ) as exc:
            self._faulted = True
            raise LinkError(str(exc)) from exc

        finally:
            self._request_lock.release()

    def probe_state(self):
        """Read the retained game after opening a fresh port."""
        if (
            self._faulted
            or self._last_command is not None
        ):
            raise LinkError(
                "A fresh connection is required for this probe."
            )

        return self._state_fence()

    def recover_state(self):
        """Retry STATE once; never replay a game action."""
        if not self._state_recovery_allowed:
            raise LinkError(
                "Only a failed STATE request may be recovered."
            )

        # Recovery cannot repeatedly enable itself.
        self._state_recovery_allowed = False

        return self._state_fence()


if __name__ == "__main__":
    for name, description in SerialLink.available_ports():
        print(f"{name}: {description}")