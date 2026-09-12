"""A stand-in for avrdude, so the whole stack can be exercised without a board.

It reproduces ``avrdude 8.0-arduino.1``'s output byte for byte, including the
carriage-return progress redraws, and picks a scenario from the port name:

    COM_OK           a clean flash that verifies
    COM_SLOW         the same, drawn out, for cancel and watchdog tests
    COM_NOSYNC       the ISP is not answering (bad wiring, missing capacitor)
    COM_WRONGCHIP    a different AVR than the one selected
    COM_VERIFYFAIL   written, but reads back wrong
    COM_BUSY         the port is held by another program
    COM_MISSING      the port does not exist
    COM_STALL        opens and then says nothing, like a Bluetooth port
    COM_GARBAGE      output no rule has ever seen, to prove the fallback

Run it the way the programmer does::

    python tests/fake_avrdude.py -C conf -p atmega2560 -c stk500v1 -P COM_OK ...
"""

from __future__ import annotations

import argparse
import sys
import time

BAR_WIDTH = 50
DONE = "\nAvrdude done.  Thank you.\n"

#: What each scenario's chip reports, so signature checks can be tested.
SIGNATURES = {
    "atmega2560": ("0x1e9801", "m2560"),
    "atmega1280": ("0x1e9703", "m1280"),
    "atmega328p": ("0x1e950f", "m328p"),
    "atmega168": ("0x1e9406", "m168"),
}


def err(text: str) -> None:
    sys.stderr.write(text)
    sys.stderr.flush()


def draw_bar(verb: str, seconds: float, steps: int = 10) -> None:
    """Redraw a progress bar in place, exactly as avrdude does."""
    for step in range(1, steps + 1):
        percent = int(100 * step / steps)
        hashes = int(BAR_WIDTH * step / steps)
        elapsed = seconds * step / steps
        err(
            f"\r{verb} | {'#' * hashes}{' ' * (BAR_WIDTH - hashes)} | "
            f"{percent}% {elapsed:.2f} s"
        )
        if seconds:
            time.sleep(seconds / steps)
    err("\n")


def scenario_of(port: str) -> str:
    return (port or "").upper().replace("\\\\.\\", "")


def emit_signature(chip: str) -> None:
    signature, name = SIGNATURES.get(chip, ("0x1e9801", "m2560"))
    err(f"Device signature = {signature} (probably {name})\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("-C")
    parser.add_argument("-p", default="atmega2560")
    parser.add_argument("-c", default="stk500v1")
    parser.add_argument("-P", default="")
    parser.add_argument("-b")
    parser.add_argument("-B")
    parser.add_argument("-U", action="append", default=[])
    parser.add_argument("-e", action="store_true")
    parser.add_argument("-D", action="store_true")
    parser.add_argument("-V", action="store_true")
    parser.add_argument("-n", action="store_true")
    parser.add_argument("-F", action="store_true")
    parser.add_argument("-v", action="count", default=0)
    parser.add_argument("-?", dest="help", action="store_true")
    args, _unknown = parser.parse_known_args(argv if argv is not None else sys.argv[1:])

    if args.help:
        err("avrdude version 8.0-arduino.1, https://github.com/avrdudes/avrdude\n")
        return 0

    port = scenario_of(args.P)

    # -- failures that happen before the port is even usable ---------------

    if port == "COM_MISSING":
        err(
            f"Error: cannot open port \\\\.\\{args.P}: "
            "The system cannot find the file specified.\n\n"
            f"Error: unable to open port {args.P} for programmer {args.c}\n"
        )
        err(DONE)
        return 1

    if port == "COM_BUSY":
        err(
            f"Error: cannot open port \\\\.\\{args.P}: Access is denied.\n\n"
            f"Error: unable to open port {args.P} for programmer {args.c}\n"
        )
        err(DONE)
        return 1

    if port == "COM_STALL":
        # Opens, then never speaks. This is the Bluetooth failure mode, and the
        # only way out is the caller's watchdog.
        time.sleep(600)
        return 0

    if port == "COM_GARBAGE":
        err("Error: the flux capacitor is misaligned at 1.21 GW\n")
        err(DONE)
        return 1

    if port == "COM_NOSYNC":
        err("Error: stk500_getsync() attempt 1 of 10: not in sync: resp=0x00\n")
        err("Error: stk500_recv(): programmer is not responding\n")
        err(f"Error: unable to open programmer {args.c} on port {args.P}\n")
        err(DONE)
        return 1

    # -- the port is alive; report the chip --------------------------------

    if port == "COM_WRONGCHIP":
        err("Error: Expected signature for ATmega2560 is 1E 98 01\n")
        err("       Device signature = 0x1e950f, double check chip, "
            "or use -F to override this check\n")
        if not args.F:
            err(DONE)
            return 1
        err("Device signature = 0x1e950f (probably m328p)\n")
    else:
        emit_signature(args.p)

    if args.n or not args.U:
        err(DONE)
        return 0

    # -- the write -----------------------------------------------------

    spec = args.U[0]
    try:
        path = _path_from_spec(spec)
    except ValueError:
        err(f"Error: invalid memory specification {spec!r}\n")
        err(DONE)
        return 1

    try:
        size = _measure(path)
    except OSError:
        err(f"Error: can't open input file {path}: No such file or directory\n")
        err(DONE)
        return 1

    slow = port == "COM_SLOW"
    pace = 6.0 if slow else 0.0

    if args.e:
        err("Erasing chip\n")

    err(f"Processing -U {spec}\n")
    err(f"Reading {size} bytes for flash from input file {path}\n")
    err(f"Writing {size} bytes to flash\n")
    draw_bar("Writing", pace or 0.4, steps=20 if slow else 10)

    if args.V:
        err(DONE)
        return 0

    if port == "COM_VERIFYFAIL":
        draw_bar("Reading", pace or 0.2, steps=5)
        err("Error: verification error, first mismatch at byte 0x0200\n")
        err("       0x0c != 0xff\n")
        err("Error: verification error; content mismatch\n")
        err(DONE)
        return 1

    draw_bar("Reading", pace or 0.3, steps=10)
    err(f"{size} bytes of flash verified\n")
    err(DONE)
    return 0


#: Format characters avrdude accepts at the end of a -U spec.
_FORMATS = set("iravdmsIhbo")


def _path_from_spec(spec: str) -> str:
    """Pull the filename out of ``flash:w:C:\\builds\\fw.hex:i``.

    Splitting on ":" from the left eats the Windows drive letter, so the
    trailing format is stripped from the right first. The suffix is optional -
    ``-U flash:w:fw.hex`` is valid and means "work the format out".
    """
    parts = spec.split(":", 2)
    if len(parts) < 3:
        raise ValueError(spec)
    rest = parts[2]
    if len(rest) > 2 and rest[-2] == ":" and rest[-1] in _FORMATS:
        rest = rest[:-2]
    if not rest:
        raise ValueError(spec)
    return rest


def _measure(path: str) -> int:
    """Count the bytes an Intel HEX file puts in flash, like avrdude reports."""
    with open(path, "rb") as handle:
        raw = handle.read()
    if not raw.lstrip().startswith(b":"):
        return len(raw)
    total = 0
    for line in raw.decode("ascii", errors="replace").splitlines():
        line = line.strip()
        if len(line) < 11 or not line.startswith(":"):
            continue
        if int(line[7:9], 16) == 0x00:
            total += int(line[1:3], 16)
    return total


if __name__ == "__main__":
    raise SystemExit(main())
