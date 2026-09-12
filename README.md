# Raphe Board Flasher

Portable Windows tool for writing firmware to Arduino/AVR boards, either through
an **Arduino UNO acting as an ISP programmer** or through a board's **USB
bootloader**. Built for an operator who should not have to know what avrdude is.

**Raphe mPhibr | Nitish Sharma**

---

## Status

| Milestone | State |
|---|---|
| **M1** — engine, AVR backend, headless CLI | **done** |
| **M1.5** — simulator, pre-flight, self-test, support reports | **done** |
| **M2** — PySide6 GUI | **done** |
| **M3** — bundled fonts, settings, light theme | **done** |
| **M4** — PyInstaller build, packaging, docs | **done** |

Design documents: [PLAN.md](PLAN.md) (architecture, avrdude output contract),
[UI_SPEC.md](UI_SPEC.md) (pixel spec), [design/ui-mockup.html](design/ui-mockup.html)
(rendered mockup of all five screen states).

---

## Running it now

```bash
pip install -r requirements.txt
set PYTHONPATH=src          # PowerShell: $env:PYTHONPATH = "src"

python -m rprm_flasher.cli ports
python -m rprm_flasher.cli boards
python -m rprm_flasher.cli inspect firmware/SAMPLE-random-test-pattern.hex --board mega2560
python -m rprm_flasher.cli detect --board mega2560 --port COM5
python -m rprm_flasher.cli flash  --board mega2560 --port COM5 --file firmware/fw.hex
```

Useful flags: `--dry-run` prints the avrdude command without running it,
`--verbose` shows raw avrdude output, `--mode usb_bootloader` switches from ISP
to the bootloader route, `-y` skips the ISP confirmation, `--skip-checks`
bypasses pre-flight (not recommended).

```bash
python -m rprm_flasher.app     # the GUI
python -m pytest tests -q      # 168 tests, no hardware and no display needed
python build/package.py        # build the shippable zip
```

---

## Shipping without hardware to test on

This tool goes to a site nobody here can visit, so the question is not "does it
work on my bench" but "what happens when it doesn't". Four things address that.

### 1. A simulated avrdude

[tests/fake_avrdude.py](tests/fake_avrdude.py) reproduces avrdude 8.0's output
byte for byte, including the carriage-return progress redraws, and picks a
failure mode from the port name. The integration suite drives the real
`FlashEngine` against it, so every path an operator can hit is executed on every
test run:

| Scenario | What it simulates |
|---|---|
| `COM_OK` | a clean flash that verifies |
| `COM_SLOW` | a long write, for cancel and watchdog tests |
| `COM_NOSYNC` | ISP not answering — bad wiring or missing capacitor |
| `COM_WRONGCHIP` | a different AVR than the one selected |
| `COM_VERIFYFAIL` | written, but reads back wrong |
| `COM_BUSY` / `COM_MISSING` | port held by another program / gone |
| `COM_STALL` | opens then says nothing, like a Bluetooth port |
| `COM_GARBAGE` | output no rule has seen, to prove the fallback |

### 2. Pre-flight checks that refuse a bad write

Before any byte is written, [core/preflight.py](src/rprm_flasher/core/preflight.py)
confirms the tool is intact, the firmware fits, the port exists and is not a
Bluetooth port, and — in ISP mode — **reads the chip signature and refuses the
write if it is not the board that was selected**. A mismatch names the board
that is actually connected rather than quoting hex.

### 3. A self-test the remote user runs first

```bash
python -m rprm_flasher.cli selftest                          # tool only
python -m rprm_flasher.cli selftest --port COM5 --board mega2560   # + wiring
```

The second form is **read-only** — it reads the chip signature and writes
nothing — so it is safe to hand to anybody. Both forms save a report.

### 4. One-file support reports

Every failure, and every self-test, writes `logs/<timestamp>-<kind>.txt`
containing the exact command, full tool output, board/port/firmware details,
CRC32, Windows version, and every serial port with its USB ids. The operator
emails that one file; no screenshots, no phone calls.

### What still cannot be proven without a board

The serial and ISP transaction itself: whether a particular Mega, on a
particular PC, with a particular USB driver, actually syncs. Everything above
that layer is covered. The first-run self-test is what closes the gap, and it
should be run before anyone flashes anything.

---

## Shipping it

```bash
python build/package.py        # build + stage + zip
python build/package.py --no-build
```

Produces `dist/RapheBoardFlasher_v1.0.0.zip` — **73 MB unpacked, 30 MB zipped**,
containing two executables that share one set of dependencies:

| | |
|---|---|
| `RapheBoardFlasher.exe` | windowed — what the operator double-clicks |
| `rprm-flasher.exe` | console — diagnostics and support |

Both run `rprm_flasher/__main__.py`, which opens the window when given no
arguments and runs the command line otherwise. Also in the zip: `README.txt`
written for the operator, `Check-This-PC-First.cmd`, and `firmware/` and
`logs/` folders.

### ⚠ Windows Smart App Control will block this build

**This is the biggest remaining risk to a remote rollout, and it is not a bug
in the code.** Smart App Control is on by default on new Windows 11 installs.
It refuses to run unsigned executables that have no established reputation —
exactly what a PyInstaller build is. It was observed blocking `rprm-flasher.exe`
on the development machine (`VerifiedAndReputablePolicyState = 1`) while
`RapheBoardFlasher.exe` ran normally; the block follows the file hash, so it is
per-binary and changes every time the build changes.

The operator cannot add an exception. Their only options are to turn Smart App
Control off — which **cannot be undone without reinstalling Windows** — or to
be given a signed binary.

Mitigations in place:

- `Check-This-PC-First.cmd` reads the policy state and says what to do. It is a
  `.cmd` deliberately: when the `.exe` is blocked, a script still runs and can
  explain why.
- The GUI's own **Self-test** button produces the same report as the console
  tool, so a blocked `rprm-flasher.exe` costs no diagnostic ability.

The real fix is **code signing**. An OV certificate builds reputation over a few
weeks; an EV certificate is trusted immediately. Until then, expect some PCs to
refuse the build.

### Also tell the operator to unblock the zip

Windows marks emailed and downloaded files, and the program may refuse to start.
Right-click the ZIP → Properties → tick **Unblock** → then extract. This is step
one of `README.txt`, and `Check-This-PC-First.cmd` detects it.

---

## Wiring the UNO as an ISP programmer

Upload the **ArduinoISP** sketch to the UNO first, then:

| UNO | Mega 2560 | UNO / Nano target |
|---|---|---|
| D10 | RESET | RESET |
| D11 (MOSI) | D51 | D11 |
| D12 (MISO) | D50 | D12 |
| D13 (SCK) | D52 | D13 |
| 5V | 5V | 5V |
| GND | GND | GND |

Fit a **10 µF capacitor between the UNO's RESET and GND** after uploading the
sketch. Without it the UNO resets itself when avrdude connects and flashing
fails with a sync error.

> **ISP flashing chip-erases the target, destroying its bootloader.** The board
> will not accept USB uploads again until the bootloader is re-burned. Burning
> bootloaders is a v2 feature; until then, use the bootloader mode if you need
> to keep it.

---

## Layout

```
src/rprm_flasher/
  core/          MCU-agnostic: models, events, errors, engine, registry
  backends/
    base.py      the one interface a new MCU family implements
    avr/         avrdude command building + output parsing
    avr/tools/   bundled avrdude 8.0-arduino.1 + avrdude.conf
  sources/       where firmware comes from (local file, local library)
  hardware/      serial port discovery
  config/boards/ board profiles as JSON data
  ui/            PySide6: theme, controller, cards, dialogs, main window
  ui/assets/     drawn logo + bundled Bebas Neue and Poppins (OFL)
  config/        board profiles and portable settings.json
  app.py         GUI entry point
  cli.py         headless front end
tests/           168 tests + a simulated avrdude; none need hardware or a display
build/           PyInstaller spec, icon generator, packaging script, operator docs
```

Three seams carry the planned growth:

- **New microcontrollers** — subclass `Programmer`, add a board JSON, register it.
  No UI change.
- **Remote firmware** — a third `FirmwareSource` whose `fetch()` downloads to a
  cache and returns a local path.
- **Flashing several boards at once** — `FlashEngine` is already a worker pool;
  v1 runs it with one worker. Each job owns its port, parser, cancel flag and
  event stream, and shares nothing.

### Adding a board

Edit [src/rprm_flasher/config/boards/avr.json](src/rprm_flasher/config/boards/avr.json)
— copy an entry, change `chip`, `signature`, `flash_bytes` and the mode options.
No rebuild. `avrdude -p ?` lists all 172 supported AVR parts.

---

## Third-party components

| Component | Version | Licence | Source |
|---|---|---|---|
| avrdude | 8.0-arduino.1 | GPL | [avrdudes/avrdude](https://github.com/avrdudes/avrdude) — see `tools/avr/README-avrdude.txt` |
| PySide6 (Qt) | 6.11 | LGPL v3 | dynamically linked, unmodified |
| pyserial | 3.5 | BSD | |
| Bebas Neue, Poppins | — | SIL OFL | licences ship beside the fonts |

avrdude is invoked as a separate process, not linked, so it stays under the GPL
while this project's own code is not placed under it.

**This repository has no LICENSE file**, which means all rights reserved by
default. Add one if it is meant to be reused.

---

## Notes for whoever picks this up

- **avrdude verifies by default.** `-V` *disables* it. The "verify after write"
  setting controls whether that flag is passed; success is the
  `N bytes of flash verified` line plus exit code 0.
- **`Avrdude done.  Thank you.` is not a success signal** — it prints on failure
  too.
- **Progress bars redraw with `\r`, not `\n`.** Write and verify both draw a bar
  and the verify bar is labelled "Reading"; only its position distinguishes it.
  See `backends/avr/parser.py`.
- **Bluetooth COM ports hang avrdude forever** rather than failing. There is a
  stall watchdog in `backends/avr/programmer.py` and the port list sorts them
  last and labels them.
- **A healthy `Device signature = 0x...` line is printed on every good
  connection.** An early error rule matched it and reported unrelated failures
  as "wrong board selected". The signature rules now require mismatch context;
  see `TestMisdiagnosisRegressions` in [tests/test_parser.py](tests/test_parser.py).
- **Progress is clamped to never decrease.** avrdude prints the signature before
  `Processing -U`, which would otherwise make the bar jump to 2% then back to 0.
- **Board profiles are validated against the real avrdude** in the test suite
  (`-p <chip>/s` needs no serial port), so a typo in avr.json fails here rather
  than on someone's desk. avrdude accepts both `atmega328p` and `m328p`.
- **The UI thread never blocks.** `ui/controller.py` runs flashing, detection
  and pre-flight on worker threads and reports back as Qt signals, which Qt
  delivers to the main thread automatically. The window only connects to
  signals; it never waits.
- **Qt's base `QWidget` rule paints the window background on every child**, so
  labels sitting on the header or status bar must clear it explicitly, or they
  punch dark rectangles through.
- **Emoji glyphs ignore your colours.** Windows renders U+26A1 and U+2699
  through Segoe UI Emoji in a fixed orange and purple that no stylesheet can
  override. Controls use words instead ("Refresh", "Settings"), and the header
  mark is a PNG drawn at the brand colours.
- **Settings live beside the executable**, falling back to AppData only if that
  folder is read-only. A corrupt settings file is ignored field by field rather
  than stopping startup, because a remote operator cannot fix one.
- **PyInstaller runs `__main__.py` as a top-level script, not as part of the
  package.** Relative imports there fail only in the frozen build, with
  "attempted relative import with no known parent package". `__main__.py` uses
  absolute imports, and a test enforces it.
- **`QBuffer(QByteArray())` segfaults.** PySide6 does not take a reference, so
  the temporary is freed while the buffer still points at it. The same applies
  to a `QApplication` with no local holding it. Both crashed the icon generator.
- **The build prunes ~35 MB of DLLs** Qt and Python pull in but this tool never
  calls: software OpenGL, two copies of OpenSSL, Qt6Network. Only Qt6Core,
  Qt6Gui and Qt6Widgets remain.
- **Not yet supported:** ATmega32U4 boards (Leonardo, Micro, Pro Micro). Their
  bootloader needs a 1200-baud touch-reset before avrdude runs. Deliberately
  left out rather than shipped broken.
