# Raphe Board Flasher — Design Plan v1

**By: Raphe mPhibr | Nitish Sharma**

A portable Windows GUI tool that flashes `.hex` / `.bin` firmware to Arduino/AVR boards,
either through an **Arduino UNO acting as an ISP programmer** or through a board's
**USB bootloader**. Built so a non-technical operator can do it: pick file → pick port →
press one button.

---

## 1. Decisions locked

| Area | Decision |
|---|---|
| Stack | Python 3.11+ / PySide6 (Qt), packaged with PyInstaller |
| avrdude | **Bundled** inside the tool — no Arduino IDE needed on the target PC |
| Upload modes | **Both**: "UNO as ISP" and "Direct USB bootloader" |
| Firmware source | Browse/drag-drop **+** optional `firmware/` library folder |
| Board select | Dropdown **+** "Detect" button (reads chip signature) |
| v1 features | Verify after write (on by default — see §7) · live log + save log · `.bin` support |
| Deferred to v2 | Multi-board parallel flashing · remote firmware fetch · burn bootloader/fuses · non-AVR MCUs |

---

## 2. The command correction that matters

Your example was:

```
avrdude -p atmega2560 -c arduino -P COMx -b 115200 -U flash:w:firmware.hex:i
```

That is a **bootloader upload over the Mega's own USB port** — it does not use the UNO at all.
(And for a Mega the correct bootloader programmer is `wiring`, not `arduino`.)

The tool generates the right command per mode:

**Mode A — UNO as ISP** (talks to the UNO's COM port; the Mega's bootloader is not involved)

```
avrdude -C <bundled>\avrdude.conf -p atmega2560 -c stk500v1 -P COM5 -b 19200 \
        -U flash:w:firmware.hex:i
```

**Mode B — Direct USB bootloader** (talks to the Mega's own COM port)

```
avrdude -C <bundled>\avrdude.conf -p atmega2560 -c wiring -P COM7 -b 115200 -D \
        -U flash:w:firmware.hex:i
```

### ISP side effect the UI must warn about

Flashing over ISP performs a **chip erase**, which **destroys the bootloader**. After an ISP
flash, that Mega will no longer accept normal USB uploads until the bootloader is re-burned.
Mode A therefore shows a one-line warning plus a confirm checkbox. "Burn bootloader" is in v2
precisely to provide the way back.

---

## 3. Architecture

The rule: **the UI knows nothing about avrdude, and the engine knows nothing about Qt.**
Everything MCU-specific lives behind one interface, so STM32/ESP becomes a new folder, not a
rewrite.

```
rprm_board_flasher/
├─ app.py                    entry point
│
├─ ui/                       PySide6 only — zero flashing logic
│   ├─ main_window.py
│   ├─ widgets/              firmware_picker · target_panel · progress_card · log_panel
│   ├─ dialogs/              settings · about · wiring_help
│   ├─ theme.py              dark/light QSS
│   └─ assets/               logo.png · app.ico
│
├─ core/                     MCU-agnostic domain layer
│   ├─ models.py             BoardProfile · Firmware · FlashJob · JobResult · SerialPort
│   ├─ engine.py             job queue + worker pool  ← multi-board plugs in here
│   ├─ events.py             ProgressEvent(phase, percent, message, raw_line)
│   ├─ registry.py           family ("avr") → Programmer implementation
│   └─ errors.py             error taxonomy → plain-English messages
│
├─ backends/
│   ├─ base.py               abstract Programmer
│   └─ avr/
│       ├─ programmer.py     builds argv, runs subprocess, streams output
│       ├─ parser.py         avrdude stderr → ProgressEvent
│       └─ tools/            avrdude.exe + avrdude.conf  (bundled, v8.0.0)
│
├─ sources/                  where firmware comes from
│   ├─ base.py               FirmwareSource: list() / fetch() -> local path
│   ├─ local_file.py         browse / drag-drop
│   ├─ local_library.py      ./firmware folder + manifest.json
│   └─ (v2) remote_http.py   ← future remote fetch drops in here, UI unchanged
│
├─ hardware/
│   └─ port_scanner.py       pyserial enumeration + friendly names + hot-plug refresh
│
├─ config/
│   ├─ boards/avr.json       board profiles as DATA, not code
│   └─ settings.py           settings.json stored next to the .exe (portable)
│
└─ build/                    PyInstaller spec, version info, icon
```

### The one interface that makes it scalable

```python
class Programmer(ABC):
    family: str                                  # "avr", later "stm32", "esp32"

    def capabilities(self) -> Capabilities: ...  # verify? erase? fuses? read-back?
    def detect(self, target: Target) -> DetectResult: ...
    def flash(self, job: FlashJob,
              emit: Callable[[ProgressEvent], None],
              cancel: threading.Event) -> JobResult: ...
```

Adding a new MCU family = one new `backends/<family>/` package + one board JSON file + one
line in the registry. **No UI change.**

### Board profiles are data

```json
{
  "id": "mega2560",
  "name": "Arduino Mega 2560",
  "family": "avr",
  "mcu": "atmega2560",
  "signature": "0x1e9801",
  "flash_bytes": 262144,
  "modes": {
    "isp_uno":        { "programmer": "stk500v1", "baud": 19200,  "chip_erase": true },
    "usb_bootloader": { "programmer": "wiring",   "baud": 115200, "extra": ["-D"] }
  }
}
```

Ships with 8 profiles: Mega 2560, Mega 1280, UNO, Nano (old + new bootloader), Pro Mini,
ATmega168 boards, bare ATmega328P. A new board is a JSON edit — no rebuild.

ATmega32U4 boards (Leonardo, Micro, Pro Micro) are **deliberately absent**: their bootloader
needs a 1200-baud touch-reset before avrdude runs, which is not implemented. Better missing
than shipped broken.

### Threading

The Qt main thread never blocks. `engine.py` owns a worker pool (size 1 in v1, N in v2); each
worker spawns avrdude as a subprocess, a reader thread pumps stderr line-by-line into the
parser, and `ProgressEvent`s are marshalled back to the UI via Qt signals. Cancel terminates
the process tree and reports cleanly.

---

## 4. UI — three steps, one button

```
┌────────────────────────────────────────────────────────────────┐
│ ◆ RAPHE BOARD FLASHER                            v1.0  ⚙  ?    │
├────────────────────────────────────────────────────────────────┤
│  1  FIRMWARE                                                   │
│     ( ) Library   [ MainBoard v2.3            ▾ ]              │
│     (•) File      [ D:\builds\firmware.hex     ] [ Browse ]    │
│         firmware.hex · 248 KB · CRC32 9A3F21E8 · valid HEX     │
│                                                                │
│  2  TARGET                                                     │
│     Board  [ Arduino Mega 2560  ▾ ]                            │
│     Method [ UNO as ISP programmer ▾ ]      ⓘ Show wiring      │
│     Port   [ COM5 — Arduino Uno  ▾ ] [ ⟳ ] [ Detect board ]    │
│     ⚠ ISP flashing erases the bootloader.  [ ] I understand    │
│                                                                │
│  3            ┌──────────────────────────┐                     │
│               │     ⚡  FLASH BOARD       │                     │
│               └──────────────────────────┘                     │
│     ████████████████████░░░░░░░░  Writing… 62%                 │
│     ✔ Done — 248 KB written and verified in 41.2 s             │
│                                                                │
│  ▾ Show details                              [ Save log ]      │
├────────────────────────────────────────────────────────────────┤
│ Raphe mPhibr · Nitish Sharma                        ● Ready    │
└────────────────────────────────────────────────────────────────┘
```

Non-technical affordances:

- **Flash button stays disabled** until firmware + board + port are all valid, with a one-line
  reason for whatever is missing.
- **Result banner** is green/red with a sentence, not a stack trace. The raw log stays collapsed.
- **"Show wiring"** dialog draws the UNO→Mega ISP pin map and the 10 µF capacitor reminder.
- Every avrdude failure maps to an instruction:

| avrdude says | Operator sees |
|---|---|
| `can't open device "\\.\COM5"` | "COM5 is in use. Close Arduino IDE / Serial Monitor and try again." |
| `not in sync: resp=0x00` | "No reply from the UNO. Check the ArduinoISP sketch is loaded and the 10 µF capacitor is fitted between UNO RESET and GND." |
| `Expected signature … Double check chip` | "Wrong board selected, or the ISP wiring is off. The detected chip is not an Arduino Mega 2560." |
| `verification error` | "Verify failed — the board was written but read back wrong. Usually a loose wire or weak power supply." |

---

## 5. Build and distribution

- **PyInstaller `--onedir`**, zipped as `RapheBoardFlasher_v1.0.0.zip`. Preferred over
  `--onefile`: it starts instantly and is far less likely to be flagged by antivirus, which
  matters when emailing this to field staff.
- Contents: `RapheBoardFlasher.exe` · `_internal/` · `tools/avr/` · `boards/` · `firmware/` ·
  `README.txt`
- No installer, no admin rights, no registry. Settings live in `settings.json` beside the exe.
- The only prerequisite on the operator's PC is the **USB serial driver** (CH340 / FTDI) for
  their clone board. The Help dialog links to it.

---

## 6. Milestones

| # | Deliverable | Why this order |
|---|---|---|
| **M1** | `core/` + `backends/avr` + a headless CLI smoke test | **Done.** Proved the real avrdude invocation and the output parser before a pixel was drawn |
| **M2** | PySide6 window, single-board happy path end to end | **Done.** |
| **M3** | Error taxonomy, detect, CRC32, wiring help, log save, theme | **Done.** Plus bundled fonts and portable settings |
| **M4** | PyInstaller build, icon, README, packaging | **Done.** 30 MB zip. See the Smart App Control warning in README.md |
| **v2** | Multi-board parallel · remote firmware · burn bootloader · new MCU backend | All pre-slotted above |

---

## 7. avrdude 8.0 output contract (verified)

Calibrated against the bundled `avrdude 8.0-arduino.1` (probed directly) plus the official
8.0 documentation. This is the contract `backends/avr/parser.py` implements.

### Success output (stderr)

```
Processing -U flash:w:firmware.hex:i
Reading 19278 bytes for flash from input file firmware.hex
Writing 19278 bytes to flash
Writing | ################################################## | 100% 7.60 s
Reading | ################################################## | 100% 6.81 s
19278 bytes of flash verified

Avrdude done.  Thank you.
```

### Parser rules

| Rule | Detail |
|---|---|
| Stream | Everything above is on **stderr**, not stdout |
| Line splitting | Progress bars redraw with `\r`, not `\n`. The reader must split on **both**, or the bar arrives as one giant line at the end |
| Phase state machine | `Writing N bytes to flash` → next bar is the **write**. `N bytes of flash verified` is preceded by a second `Reading \| … \|` bar, which is the **verify**. Same bar glyph, different meaning — position is what disambiguates |
| Percent | `^(Writing\|Reading)\s*\|[#\s]*\|\s*(\d+)%\s*([\d.]+)\s*s` — note v8 puts a **space** before `s` where v6 did not; the regex tolerates both |
| UI mapping | write 0–100% → bar 0–80%, verify 0–100% → bar 80–100%, so the operator sees one continuous bar |
| Success signal | the `N bytes of flash verified` line **and** exit code 0 |
| Errors | prefixed `Error: ` (confirmed on 8.0-arduino.1). Collect all of them; map the first to a friendly message, keep the rest in the log |
| Terminator | `Avrdude done.  Thank you.` — two spaces. Useful as an end-of-run marker but **not** a success signal; it prints on failure too |

Real failure output captured from the bundled binary:

```
Error: cannot open port \\.\COM99: The system cannot find the file specified.

Error: unable to open port COM99 for programmer stk500v1

Avrdude done.  Thank you.
```

### Two things this changed in the plan

1. **Verify is already on by default.** avrdude auto-verifies after every `-U ...:w:...`;
   `-V` *disables* it. So the "Verify after write" feature is *not* an extra pass to add —
   it is a checkbox that controls whether we pass `-V`, and the parser treats
   `N bytes of flash verified` as the authoritative success line. Default: on, no `-V`.
2. **avrdude can enumerate ports itself** (`-P ?s`) and knows 172 AVR parts (`-p ?`),
   including `m2560`, `m328p`, `m32u4`, `m1280`, `m168*`. Port listing still uses pyserial
   (it gives friendly names like "Arduino Uno (COM5)"), but `-p ?` output is a ready-made
   source for a future "Advanced: any AVR part" mode beyond the curated board dropdown.

### Residual uncertainty

Two strings are still unconfirmed on real hardware, because both require a board to be
attached: the **device-signature line** (expected `Device signature = 0x1e9801 …`) and the
exact **`not in sync`** wording for a non-responding ISP. Both are parsed with tolerant
regexes and both fall back to showing the raw avrdude text rather than a wrong friendly
message, so a mismatch degrades gracefully. I will tighten them the first time you run the
tool against your rig.

---

## 8. Logo

Supplied: chip outline in slate `#1E2A38` with a cyan `#1BA8F0` bolt, transparent background.

Needed in `ui/assets/`:

| File | Size | Use |
|---|---|---|
| `app_512.png` | 512×512 | source |
| `app.ico` | 256/128/64/48/32/16 multi-size | window icon + built `.exe` icon |
| `logo_wide.png` | 1200×300 | header lockup: mark + "RAPHE BOARD FLASHER", "Raphe mPhibr" beneath |

At 16–32 px the thin bolt will start to disappear against the chip outline; the `.ico` should
use a **bolt-only** variant for the 16 and 32 px frames.

