"""Headless front end.

This exists so the engine can be proven against real hardware before any UI is
written, and so a failure in the field can be reproduced with one command. The
GUI will call exactly the same ``FlashEngine``.

    python -m rprm_flasher.cli ports
    python -m rprm_flasher.cli boards
    python -m rprm_flasher.cli inspect firmware.hex
    python -m rprm_flasher.cli detect --board mega2560 --port COM5
    python -m rprm_flasher.cli flash --board mega2560 --port COM5 --file fw.hex
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

from . import __author__, __version__
from .core.diagnostics import self_test, write_support_report
from .core.engine import FlashEngine
from .core.errors import FlasherError
from .core.events import Phase, ProgressEvent
from .core.models import FlashJob, Target
from .core.preflight import run_preflight
from .core.registry import get_programmer, load_catalog
from .hardware import port_scanner
from .sources.base import inspect as inspect_firmware

BANNER = f"Raphe Board Flasher {__version__} — {__author__}"

#: Reports land beside the tool so a remote user can find them without being
#: told where Windows hides temp folders.
REPORT_DIR = Path("logs")


# -- commands -------------------------------------------------------------


def cmd_ports(_args: argparse.Namespace) -> int:
    ports = port_scanner.list_ports()
    if not ports:
        print("No serial ports found.")
        print("Plug the board in, and install its USB driver (CH340 or FTDI) if new.")
        return 1
    print(f"{len(ports)} serial port(s):\n")
    for port in ports:
        mark = "*" if port_scanner.is_likely_board(port) else " "
        vendor = port_scanner.vendor_name(port)
        notes = [n for n in (vendor, "Bluetooth - avoid" if port_scanner.is_bluetooth(port) else "") if n]
        suffix = f"  [{', '.join(notes)}]" if notes else ""
        print(f" {mark} {port.device:<8} {port.description}{suffix}")
    print("\n* = looks like a board")
    if not any(port_scanner.is_likely_board(p) for p in ports):
        print("\nNone of these look like a board. Plug it in, and install its USB "
              "driver (CH340 or FTDI) if it is new.")
    return 0


def cmd_boards(_args: argparse.Namespace) -> int:
    catalog = load_catalog()
    print(f"{len(catalog)} board profile(s):\n")
    for board in catalog:
        flash_kb = board.flash_bytes // 1024
        print(f"  {board.id:<20} {board.name}")
        print(f"  {'':<20} {board.chip}  {flash_kb} KB  {board.signature or ''}")
        for mode in board.modes.values():
            erases = "  (erases bootloader)" if mode.erases_bootloader else ""
            print(f"  {'':<20}   - {mode.id:<16} {mode.label}{erases}")
        print()
    return 0


def cmd_inspect(args: argparse.Namespace) -> int:
    firmware = inspect_firmware(Path(args.file))
    print(f"File      {firmware.path}")
    print(f"Format    {firmware.fmt.value}")
    print(f"Size      {firmware.size_bytes:,} bytes on disk")
    print(f"Program   {firmware.program_bytes:,} bytes to flash")
    print(f"CRC32     {firmware.crc32}")

    if args.board:
        board = load_catalog().get(args.board)
        fits = "fits" if firmware.fits(board) else "TOO BIG"
        print(
            f"Target    {board.name}: {firmware.usage_percent(board):.0f}% "
            f"of {board.flash_bytes // 1024} KB — {fits}"
        )
    for warning in firmware.warnings:
        print(f"\nNote: {warning}")
    return 0


def cmd_detect(args: argparse.Namespace) -> int:
    target = _build_target(args)
    programmer = get_programmer(target.family)

    print(f"Reading the chip on {target.port} via {target.mode.label}...\n")
    result = programmer.detect(target)

    if not result.ok:
        print(f"FAILED: {result.title}")
        print(f"        {result.detail}")
        if args.verbose:
            print("\n--- avrdude output ---\n" + result.log)
        return 1

    print(f"Signature   {result.signature}")
    if result.chip:
        print(f"Chip        {result.chip}")

    matches = load_catalog().by_signature(result.signature or "")
    if matches:
        print("Matches     " + ", ".join(b.name for b in matches))
    if result.signature and target.board.signature:
        same = result.signature.lower() == target.board.signature.lower()
        print(f"Selected    {target.board.name} — {'match' if same else 'MISMATCH'}")
        return 0 if same else 2
    return 0


def cmd_selftest(args: argparse.Namespace) -> int:
    print(BANNER)
    print("\nChecking this copy of the tool", end="")
    print(" and the connected board..." if args.port else "...")
    print()

    result = self_test(port=args.port, board_id=args.board, mode_id=args.mode)
    print(result.report.as_text())

    print()
    if result.ok:
        print("All checks passed.")
        if not args.port:
            print("Re-run with --port COM5 --board mega2560 to test the wiring too.")
    else:
        print("Something is wrong. The [STOP] lines above say what and how to fix it.")

    path = write_support_report(
        _report_path("selftest"), self_test_result=result
    )
    print(f"\nReport saved: {path}")
    print("Send this file to whoever gave you the tool if anything failed.")
    return 0 if result.ok else 1


def cmd_flash(args: argparse.Namespace) -> int:
    target = _build_target(args)
    firmware = inspect_firmware(Path(args.file))
    job = FlashJob(target=target, firmware=firmware, verify=not args.no_verify)

    if not firmware.fits(target.board):
        raise FlasherError(
            "This firmware is too big for the board",
            f"{firmware.program_bytes:,} bytes will not fit in "
            f"{target.board.flash_bytes:,} bytes of flash.",
        )

    programmer = get_programmer(target.family)
    argv = programmer.build_flash_argv(job)

    print(BANNER)
    print(f"\nFirmware  {firmware.path.name}  "
          f"({firmware.program_bytes:,} bytes, CRC32 {firmware.crc32})")
    print(f"Board     {target.board.name} ({target.board.chip})")
    print(f"Method    {target.mode.label}")
    print(f"Port      {target.port}")
    print(f"\n$ {' '.join(argv)}\n")

    if target.mode.erases_bootloader and not args.yes:
        print("WARNING: this mode erases the chip, destroying its bootloader.")
        print("         The board will not accept USB uploads until it is re-burned.")
        if input("Continue? [y/N] ").strip().lower() not in ("y", "yes"):
            print("Cancelled.")
            return 1

    if args.dry_run:
        print("Dry run: nothing was written.")
        return 0

    preflight = None
    if not args.skip_checks:
        print("Pre-flight checks:")
        preflight = run_preflight(job, check_signature=not args.no_signature_check)
        print(preflight.as_text())
        print()
        if not preflight.ok:
            blocker = preflight.blockers[0]
            print(f"STOPPED  {blocker.detail or blocker.name}")
            print(f"         {blocker.fix}")
            print("\nNothing was written to the board.")
            path = write_support_report(
                _report_path("blocked"), job=job, preflight=preflight
            )
            print(f"Report saved: {path}")
            return 1

    engine = FlashEngine(max_workers=1)
    try:
        result = engine.run_blocking(job, _make_printer(args.verbose))
    finally:
        engine.shutdown()

    print()
    if result.ok:
        print(f"OK   {result.title}")
        print(f"     {result.detail}")
        return 0

    print(f"FAILED   {result.title}")
    print(f"         {result.detail}")
    if args.verbose:
        print("\n--- full output ---\n" + result.log)

    path = write_support_report(
        _report_path("failed"), job=job, result=result, preflight=preflight
    )
    print(f"\nReport saved: {path}")
    print("Send this file to whoever gave you the tool.")
    return 1


def _report_path(kind: str) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return REPORT_DIR / f"{stamp}-{kind}.txt"


# -- helpers --------------------------------------------------------------


def _build_target(args: argparse.Namespace) -> Target:
    board = load_catalog().get(args.board)
    if not board.modes:
        raise FlasherError(
            "That board has no upload methods",
            f"The profile for {board.id!r} is incomplete.",
        )

    mode_id = args.mode or next(iter(board.modes))
    mode = board.modes.get(mode_id)
    if mode is None:
        raise FlasherError(
            f"{board.name} cannot be flashed by {mode_id!r}",
            "Available: " + ", ".join(board.modes),
        )
    return Target(board=board, mode=mode, port=args.port)


def _make_printer(verbose: bool):
    """A listener that redraws one progress line, like avrdude itself."""
    state = {"phase": None}

    def listen(_job_id: str, event: ProgressEvent) -> None:
        if verbose and event.raw:
            print(f"  | {event.raw}")
            return
        if event.phase in (Phase.WRITING, Phase.VERIFYING):
            bar = int(event.overall / 2)
            sys.stdout.write(
                f"\r  [{'#' * bar}{' ' * (50 - bar)}] {event.overall:5.1f}%  "
                f"{event.message:<28}"
            )
            sys.stdout.flush()
        elif event.phase != state["phase"]:
            if state["phase"] in (Phase.WRITING, Phase.VERIFYING):
                print()
            if event.message:
                print(f"  {event.message}")
        state["phase"] = event.phase

    return listen


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rprm-flasher",
        description=BANNER,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=BANNER)
    subs = parser.add_subparsers(dest="command", required=True)

    subs.add_parser("ports", help="list serial ports").set_defaults(func=cmd_ports)
    subs.add_parser("boards", help="list board profiles").set_defaults(func=cmd_boards)

    p_inspect = subs.add_parser("inspect", help="validate and measure a firmware file")
    p_inspect.add_argument("file")
    p_inspect.add_argument("--board", help="also check it fits this board")
    p_inspect.set_defaults(func=cmd_inspect)

    p_detect = subs.add_parser("detect", help="read the chip signature (writes nothing)")
    _add_target_args(p_detect)
    p_detect.set_defaults(func=cmd_detect)

    p_flash = subs.add_parser("flash", help="write firmware to a board")
    _add_target_args(p_flash)
    p_flash.add_argument("--file", required=True, help="the .hex or .bin to write")
    p_flash.add_argument("--no-verify", action="store_true", help="skip the verify pass")
    p_flash.add_argument("--skip-checks", action="store_true",
                         help="skip all pre-flight checks (not recommended)")
    p_flash.add_argument("--no-signature-check", action="store_true",
                         help="do not read the chip id before writing")
    p_flash.add_argument("--dry-run", action="store_true", help="print the command only")
    p_flash.add_argument("-y", "--yes", action="store_true", help="skip the ISP warning")
    p_flash.set_defaults(func=cmd_flash)

    p_self = subs.add_parser(
        "selftest",
        help="check the tool is intact, and optionally that a board answers",
    )
    p_self.add_argument("--port", help="also test the wiring on this port (read-only)")
    p_self.add_argument("--board", help="board id to test against")
    p_self.add_argument("--mode", help="upload method id")
    p_self.set_defaults(func=cmd_selftest)

    return parser


def _add_target_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--board", required=True, help="board id (see: boards)")
    parser.add_argument("--port", required=True, help="serial port, e.g. COM5")
    parser.add_argument("--mode", help="upload method id; defaults to the first")
    parser.add_argument("-v", "--verbose", action="store_true", help="show raw output")


def main(argv: list[str] | None = None) -> int:
    # The Windows console defaults to cp1252, which mangles the en dashes and
    # middots this tool prints.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass

    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except FlasherError as exc:
        print(f"\n{exc.title}", file=sys.stderr)
        if exc.fix:
            print(f"{exc.fix}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
