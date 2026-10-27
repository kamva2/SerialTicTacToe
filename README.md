# Serial Tic-Tac-Toe — STM32 Authoritative Game Server

**EEE3095S Embedded Systems II · CS Project 2026 · University of Cape Town**  
**Team:** Kamva Poswa and Mbali Mboto

A two-player Tic-Tac-Toe system in which an **STM32F051C6** microcontroller acts as the authoritative game server and a **Python Tkinter** application acts as the PC graphical client. The devices exchange newline-terminated messages over a **115200-baud UART** link.

The STM32 owns the board, connection state, current turn, game phase, and result. The GUI sends player requests and renders only state confirmed by the board; it does **not** decide whether a move is legal.

- **Source:** [GitHub — kamva2/SerialTicTacToe](https://github.com/kamva2/SerialTicTacToe)
- **Demonstration:** [STM32 Tic-Tac-Toe video](https://www.youtube.com/watch?v=hkqDFUS9O1k)

## 1. Features

- Two local players (**X** and **O**) sharing a single PC GUI; X plays first.
- STM32-side validation of session, game phase, player turn, index range, and cell occupancy.
- All eight winning lines, draws, resignation, and preservation of the final board.
- Three game phases: `IDLE`, `IN_PROGRESS`, and `GAME_OVER`.
- ASCII command/response protocol with specific `NACK` error messages.
- Bounded UART frame parsing, partial-frame timeout, malformed-frame rejection, and resynchronisation at the next newline.
- Tkinter GUI with COM-port selection, connection controls, board rendering, status/error messages, and a background serial worker.
- On-board **PA0 / SW0 button** to start a game when eligible, and **PB0 / D0 LED** to indicate X's turn.
- Automated Windows-host tests for the C game engine and command handler.

**Scope:** There is no AI opponent, remote multiplayer, checksum, or exactly-once command retry in this version.

## 2. Project structure

The important repository files are:

```text
SerialTicTacToe/
├── .project                     # STM32CubeIDE project metadata
├── .cproject                    # STM32CubeIDE C/build settings
├── SerialTicTacToe.ioc          # STM32CubeMX peripheral configuration
├── STM32F051C6TX_FLASH.ld      # STM32 linker script
├── Core/
│   ├── Inc/
│   │   ├── game.h
│   │   ├── protocol.h
│   │   ├── frame.h
│   │   └── hardware.h
│   └── Src/
│       ├── main.c               # HAL setup and UART service loop
│       ├── game.c               # Authoritative game state/rules
│       ├── protocol.c           # Command parsing and replies
│       ├── frame.c              # Serial frame parser
│       ├── hardware.c           # Button debounce and LED
│       └── game_test.c          # Additional C game test code
├── Drivers/                     # STM32 HAL and CMSIS dependencies
└── pc/
    ├── gui.py                  # GUI entry point (Tkinter)
    ├── gui_worker.py           # Background serial worker
    ├── serial_link.py          # pySerial link and transaction deadlines
    ├── responses.py            # Server-response validation
    ├── test_commands.py        # Windows-host pytest suite
    ├── requirements.txt        # GUI Python dependencies
    ├── Board.jpeg              # Board graphic
    ├── X_modified.png          # X graphic
    └── O_modified.png          # O graphic
```

The repository ZIP may also contain a `Debug/` folder. Those files are generated build outputs; **rebuild locally** rather than relying on the archived `.elf` or Makefiles. The GUI image files must stay alongside `pc/gui.py` because it loads them by relative script location.

## 3. Required hardware and software

### Hardware

- UCT STM32 development board with **STM32F051C6** microcontroller.
- **ST-LINK** compatible programming/debug connection.
- **3.3 V-compatible USB-to-UART adapter** connected to USART1 (for example, the fitted STM32USB2UART adapter).
- USB cables and the board's existing safe regulated power arrangement.
- Windows PC for the documented setup and host-based tests.

### Software

- **STM32CubeIDE** for importing, building, and flashing the firmware.
- **Python 3.10** (the recorded automated run used Python **3.10.11**).
- **Tkinter** (provided by a typical Windows Python installation; confirm it is available).
- Python GUI dependencies: **pySerial 3.5** and **Pillow 12.1.0**, as pinned in `pc/requirements.txt`.
- **pytest** for the automated host-based tests.
- **GCC for Windows**, available on `PATH`, to compile the actual `game.c` and `protocol.c` into a temporary DLL during pytest. A compatible MinGW-w64 GCC can be used.
- Optional: **PuTTY** or another serial terminal for manual communication checks.

## 4. UART wiring and settings

The **ST-LINK programming connection is separate** from the UART connection used by the game.

| STM32 connection | USB-to-UART connection | Purpose |
|---|---|---|
| **PA9 / USART1_TX** | **RX** | STM32 responses to PC |
| **PA10 / USART1_RX** | **TX** | PC commands to STM32 |
| **GND** | **GND** | Common signal reference |
| **PA0 / SW0** | Existing on-board button | Active-low local game start |
| **PB0 / D0** | Existing on-board LED/resistor | High = LED on for X's turn |

Use **115200 baud, 8 data bits, no parity, 1 stop bit (8N1), no flow control**. UART signals must be **3.3 V-compatible**; do not treat USB's 5 V supply as a UART logic level. Follow the board/adapter documentation before changing jumpers or connecting additional power sources.

On Windows, find the adapter's port in **Device Manager → Ports (COM & LPT)**. `COM10` was used during the team's manual demonstration.

## 5. Import, build, and flash the STM32 firmware

1. Download/clone the repository and extract it if necessary.
2. Start **STM32CubeIDE** and select a workspace.
3. Choose **File → Import → General → Existing Projects into Workspace**.
4. Select the directory containing the project's **`.project`**, **`.cproject`**, and **`SerialTicTacToe.ioc`** files, then click **Finish**. The imported project is named `SerialTicTacToe` in the supplied metadata.
5. In Project Explorer, confirm that `Core/` and `Drivers/` appear directly under the project. If a second project folder is nested inside, re-import the **inner folder** that contains `.project`.
6. Select the **Debug** build configuration. Choose **Project → Clean**, then **Build Project** (or click the hammer icon).
7. Confirm that the build completes without errors and produces a fresh firmware image, normally `Debug/SerialTicTacToe.elf`.
8. Connect the STM32 board to the **ST-LINK** programming interface and supply power safely.
9. With the STM32 project selected, choose **Debug As → STM32 C/C++ Application** . Select the correct probe and target configuration if prompted.
10. Wait for successful firmware download/verification. If execution pauses at `main()`, click **Resume** or press **F8**.

**If the build fails with `No rule to make target 'all'`:** check that an existing STM32CubeIDE project—not a generic C project—was imported, that the active configuration is `Debug`, and that the build directory points to this project. Then clean and rebuild. Do not use an old archived `Debug/` folder as proof of a successful build.

## 6. Install and run the Python GUI

Open **PowerShell** in the repository root (the folder containing `Core/` and `pc/`):

```powershell
python --version
python -m pip install -r pc/requirements.txt
python pc/gui.py
```

The GUI relies on `pc/Board.jpeg`, `pc/X_modified.png`, and `pc/O_modified.png`. Keep these images in `pc/` with the Python files.

In the application:

1. Connect and power the STM32, and make sure its firmware is running.
2. Attach the USB-to-UART adapter, then select the correct port from the GUI's port selector. Click **REFRESH PORTS** if needed.
3. Click **CONNECT** to establish a session.
4. Click **NEW GAME** to clear the board and begin with X.
5. Players take turns clicking empty squares. The GUI sends a `MOVE` request and displays the board **only after the server confirms it**.
6. A win, draw, or resignation ends the game; move submission is disabled until a new game starts.
7. Use **DISCONNECT** to close the session cleanly, or close the GUI window.

The GUI performs serial I/O in a **background worker thread**, so the Tkinter event loop is not blocked while waiting for replies. It validates incoming snapshots before updating the display and preserves the last confirmed board if an error occurs.

**Important:** Close PuTTY or any other serial application before opening the GUI. Only one program should own the adapter's COM port at a time.

## 7. UART protocol reference

Requests and responses are **case-sensitive printable ASCII** frames ending in **LF (`\n`)**. The board accepts an optional **CR immediately before LF**. The maximum frame length is **96 bytes before LF**.

The supplied `Core/Inc/frame.h` sets:

```c
#define FRAME_TIMEOUT_MS 1000u
```

Thus an incomplete request is rejected after **1,000 ms** from the first byte in this repository version. The Python link's `pc/serial_link.py` has a **2-second response deadline**. The GUI's current background `STATE` polling interval is **1,000 ms**. These are distinct settings. Earlier interactive PuTTY work used a local 10,000 ms.

### Commands

| PC request | Server action / success response |
|---|---|
| `CONNECT` | Establish session in `IDLE`; returns `OK`. |
| `NEW` | Start an empty game when connected in `IDLE` or `GAME_OVER`; returns `OK:` followed by a snapshot. |
| `MOVE:<player>:<index>` | Validate player (`X`/`O`) and index (`0`–`8`); return `OK:` followed by a snapshot. |
| `STATE` | Return the current `BOARD:` snapshot without changing it (during a game or after game over). |
| `RESIGN:<player>` | Current player forfeits; returns `OK:` and the final snapshot. |
| `DISCONNECT` | Clear the session/game and return `OK`. |

### Board encoding and examples

The nine cells are numbered row by row:

```text
0 | 1 | 2
--+---+--
3 | 4 | 5
--+---+--
6 | 7 | 8
```

`.` means empty. A game starts with an empty board and X's turn:

```text
PC  -> STM32: CONNECT
STM32 -> PC:  OK
PC  -> STM32: NEW
STM32 -> PC:  OK:BOARD:.........:TURN:X:PHASE:IN_PROGRESS:RESULT:NONE
PC  -> STM32: MOVE:X:0
STM32 -> PC:  OK:BOARD:X........:TURN:O:PHASE:IN_PROGRESS:RESULT:NONE
PC  -> STM32: MOVE:O:0
STM32 -> PC:  NACK:OCCUPIED
PC  -> STM32: STATE
STM32 -> PC:  BOARD:X........:TURN:O:PHASE:IN_PROGRESS:RESULT:NONE
```

All messages shown above are individual LF-terminated frames; the final LF is omitted for readability. Each valid snapshot contains `BOARD`, `TURN`, `PHASE`, and `RESULT`. Terminal results can be `WIN_X`, `WIN_O`, `DRAW`, `RESIGN_X`, or `RESIGN_O`. Terminal responses carry the final board and use `PHASE:GAME_OVER` with `TURN:-`.

### Error responses

| Response | Meaning |
|---|---|
| `NACK:BADCMD` | Unknown command, invalid syntax, wrong case, or invalid frame character. |
| `NACK:NOTCONNECTED` | A session is required but not established. |
| `NACK:NOGAME` | The requested game operation is unavailable in the current game phase. |
| `NACK:BUSY` | For example, `NEW` during `IN_PROGRESS` or `CONNECT` during an active/completed game. |
| `NACK:NOTURN` | A `MOVE` or `RESIGN` names the wrong player. |
| `NACK:RANGE` | A syntactically valid move index is outside `0`–`8`. |
| `NACK:OCCUPIED` | The selected square is already marked. |
| `NACK:TOOLONG` | A frame exceeds 96 bytes before LF. |
| `NACK:TIMEOUT` | A partial frame has not ended before the configured deadline. |

Every rejected request is intended to preserve all authoritative game fields. Bad or incomplete frames are not dispatched to the game engine. On a malformed/oversized/timed-out frame, the parser discards bytes through the next LF to re-establish a clear frame boundary. There is **no checksum** or command identifier in protocol version 1.0; do not automatically retry a potentially accepted state-changing move if its reply was lost.

## 8. Hardware button and LED

- **SW0 / PA0** is active-low with an internal pull-up. One debounced press (20 ms stable time) requests a new game only when connected in `IDLE` or `GAME_OVER`. It is ignored during `IN_PROGRESS` and while disconnected. Holding the button does not repeatedly trigger the action.
- **D0 / PB0 LED** is on during **X's turn** in `IN_PROGRESS` and off otherwise.
- The **hardware RESET** input is not the same as SW0: RESET restarts the firmware and returns the system to its initial disconnected state.
- A button-started game produces **no unsolicited serial message**; the GUI discovers the new state through `STATE` polling.

## 9. Run the automated tests

The automated suite is **`pc/test_commands.py`**. It does **not** communicate through COM10 or the physical STM32. Instead, on **Windows**, pytest invokes GCC to compile the **actual** `Core/Src/game.c` and `Core/Src/protocol.c` into a temporary DLL and calls their functions using Python `ctypes`.

Install pytest, confirm Windows GCC is accessible, and run from the repository root:

```powershell
python -m pip install pytest
python --version
gcc --version
python -m pytest -v pc/test_commands.py
```

The supplied team log records:

```text
170 passed in 3.00s
```

These **170 passing host-based cases** cover connection requirements, valid and invalid moves, turn precedence, unchanged-state rejections, winning lines, draws, resignation, game-over restrictions, malformed command syntax, numeric boundary cases, and command-response buffer limits. They do **not** by themselves prove UART electrical communication, interrupt/driver behaviour, or the serial frame assembler on the physical board.

The separate `Core/Src/game_test.c` contains additional embedded-style checks, but the supplied firmware `main.c` does **not** invoke `ttt_run_tests()` at startup.
### Manual test on the physical board

With the STM32 flashed and running, close the GUI and open PuTTY on the adapter's COM port using the UART settings above. Send one command at a time, terminated by LF; in PuTTY **Ctrl+J** sends LF. With the repository's 1-second frame deadline, **paste the command and send LF promptly** rather than typing slowly. Try `CONNECT`, `NEW`, `MOVE:X:0`, and `STATE`

The team separately observed successful programming, two-way PuTTY communication, and a GUI game ending in a server-reported `WIN_O` result.

## 10. Troubleshooting

| Symptom | What to check |
|---|---|
| **No serial ports in GUI** | USB adapter connected, Windows driver installed, correct COM port, refresh list. |
| **Port cannot open / access denied** | Close PuTTY and other programs using that port; select the adapter's port, not the ST-LINK debug interface. |
| **`CONNECT` gives no response** | STM32 firmware running (resume debugger if paused), correct 115200/8N1 settings, TX/RX crossed, shared GND, LF terminator. |
| **`NACK:TIMEOUT` in PuTTY** | Complete the command with LF quickly; the repository firmware's incomplete-frame timeout is 1 second. Send a boundary LF to resynchronise if needed. |
| **`NACK:BUSY` on `NEW` or `CONNECT`** | A game is already active. Finish the game or use `DISCONNECT`, then `CONNECT` and `NEW`; do not assume `CONNECT` resets an active game. |
| **GUI reports uncertain response / communication failure** | Avoid automatically resending the last `MOVE`; close/reconnect and re-establish a known session, restarting/resetting the board when necessary. |
| **GUI image-loading error** | Ensure `Board.jpeg`, `X_modified.png`, and `O_modified.png` remain in `pc/`; install Pillow from `requirements.txt`. |
| **`gcc` not found when running pytest** | Install a compatible Windows GCC toolchain and add its `bin` directory to `PATH`; re-open PowerShell and run `gcc --version`. |
| **STM32 build/import errors** | Import the inner directory containing `.project` and `.cproject`, activate `Debug`, clean and rebuild from source. |


## 11. Project demonstration and attribution

- **Demo video:** https://www.youtube.com/watch?v=hkqDFUS9O1k
- **Course:** EEE3095S, University of Cape Town, 2026
- **Team:** Kamva Poswa (STM32 firmware and hardware focus); Mbali Mboto (GUI, testing, and report focus). Design, integration, and demonstration were shared.
- **Relevant documentation:** [STM32CubeIDE](https://www.st.com/en/development-tools/stm32cubeide.html), [Tkinter](https://docs.python.org/3/library/tkinter.html), [pySerial](https://pyserial.readthedocs.io/), [pytest](https://docs.pytest.org/).

STM32 HAL/CMSIS files in `Drivers/` retain their upstream licence notices. No separate project-wide software licence is declared in this archive.
