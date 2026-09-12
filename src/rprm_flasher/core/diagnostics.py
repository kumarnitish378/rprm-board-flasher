"""Self-test and support reporting.

Two jobs, both aimed at a user nobody here can look over the shoulder of:

* :func:`self_test` answers "is this copy of the tool intact and is the board
  reachable?" without writing anything. It is what the remote user runs first.
* :func:`support_report` produces one text file carrying everything needed to
  diagnose a failure remotely, so nobody has to ask "which port did you use?".
"""

from __future__ import annotations

import platform
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .. import __author__, __version__
from ..hardware import port_scanner
from .errors import FlasherError
from .models import FlashJob, JobResult, Target
from .preflight import Check, PreflightReport, Severity
from .registry import get_programmer, load_catalog


@dataclass
class SelfTestResult:
    report: PreflightReport = field(default_factory=PreflightReport)
    board_signature: str | None = None

    @property
    def ok(self) -> bool:
        return self.report.ok


def self_test(
    port: str | None = None,
    board_id: str | None = None,
    mode_id: str | None = None,
) -> SelfTestResult:
    """Verify this copy of the tool, and optionally reach a real board.

    Without ``port`` nothing touches hardware. With one, a read-only signature
    check runs: it writes nothing, so it is safe to hand to anybody.
    """
    result = SelfTestResult()
    checks = result.report.checks

    # 1. Is the bundled tooling there and does it run?
    try:
        programmer = get_programmer("avr")
    except FlasherError as exc:
        checks.append(Check("Flashing tool", False, Severity.BLOCK, exc.title, exc.fix))
        return result

    available, reason = programmer.available()
    checks.append(
        Check(
            "Flashing tool present",
            available,
            Severity.BLOCK,
            "avrdude and avrdude.conf found" if available else reason,
            "The zip was not fully extracted. Extract it again, keeping every "
            "file together." if not available else "",
        )
    )
    if not available:
        return result

    try:
        version = programmer.version()
        runs = "8.0" in version or "version" in version.lower()
    except OSError as exc:
        version, runs = str(exc), False
    checks.append(
        Check(
            "Flashing tool runs",
            runs,
            Severity.BLOCK,
            version,
            "Windows blocked the bundled avrdude. Allow it in your antivirus, "
            "or unblock the zip file before extracting (right-click the zip, "
            "Properties, Unblock)." if not runs else "",
        )
    )
    if not runs:
        return result

    # 2. Are the board profiles valid? A typo here breaks flashing at the worst
    #    possible moment, so every profile is command-built now, not later.
    try:
        catalog = load_catalog()
        broken: list[str] = []
        for board in catalog:
            for mode in board.modes.values():
                if not mode.options.get("programmer"):
                    broken.append(f"{board.id}/{mode.id}: no programmer set")
        checks.append(
            Check(
                "Board profiles",
                not broken,
                Severity.BLOCK,
                f"{len(catalog)} boards loaded" if not broken else "; ".join(broken),
                "boards/avr.json has been edited incorrectly." if broken else "",
            )
        )
    except (OSError, ValueError, KeyError) as exc:
        checks.append(
            Check(
                "Board profiles",
                False,
                Severity.BLOCK,
                f"{type(exc).__name__}: {exc}",
                "boards/avr.json is missing or malformed.",
            )
        )
        return result

    # 3. Can we see serial ports at all?
    ports = port_scanner.list_ports()
    boards_seen = [p for p in ports if port_scanner.is_likely_board(p)]
    checks.append(
        Check(
            "Serial ports",
            bool(ports),
            Severity.WARN if ports else Severity.BLOCK,
            f"{len(ports)} found: " + ", ".join(p.label for p in ports)
            if ports else "none found",
            "Plug the board in. If it is new, install its USB driver: CH340 for "
            "most clones, FTDI for older ones." if not ports else "",
        )
    )
    checks.append(
        Check(
            "Board detected on USB",
            bool(boards_seen),
            Severity.WARN,
            ", ".join(p.label for p in boards_seen) if boards_seen
            else "no Arduino or USB-serial adapter recognised",
            "Windows can see a port but not recognise it as a board. That is "
            "usually a missing driver." if not boards_seen else "",
        )
    )

    # 4. Optional: talk to the board. Read-only.
    if not port:
        checks.append(
            Check(
                "Board responds",
                True,
                Severity.INFO,
                "not tested - re-run with a port to check the wiring",
            )
        )
        return result

    board = catalog.get(board_id or "mega2560")
    mode = board.modes.get(mode_id or "isp_uno") or next(iter(board.modes.values()))
    detect = programmer.detect(Target(board=board, mode=mode, port=port))

    if not detect.ok:
        checks.append(
            Check("Board responds", False, Severity.BLOCK, detect.title, detect.detail)
        )
        return result

    result.board_signature = detect.signature
    matches = catalog.by_signature(detect.signature or "")
    names = ", ".join(sorted({b.name for b in matches})) if matches else "unrecognised chip"
    checks.append(
        Check(
            "Board responds",
            True,
            Severity.BLOCK,
            f"{detect.signature} - {names}",
        )
    )
    expected = (board.signature or "").lower()
    checks.append(
        Check(
            "Matches selected board",
            not expected or expected == (detect.signature or "").lower(),
            Severity.WARN,
            f"selected {board.name} ({expected or 'any'})",
            "The connected board is not the one selected. That is fine for a "
            "wiring test, but pick the right one before flashing.",
        )
    )
    return result


def support_report(
    job: FlashJob | None = None,
    result: JobResult | None = None,
    preflight: PreflightReport | None = None,
    self_test_result: SelfTestResult | None = None,
    extra_log: str = "",
) -> str:
    """One text file that answers every question a remote diagnosis needs."""
    lines: list[str] = []

    def section(title: str) -> None:
        lines.extend(["", title, "-" * len(title)])

    lines.append(f"Raphe Board Flasher support report")
    lines.append(f"Generated {datetime.now(timezone.utc).astimezone():%Y-%m-%d %H:%M:%S %z}")

    section("Tool")
    lines.append(f"Version        {__version__}")
    lines.append(f"By             {__author__}")
    lines.append(f"Python         {sys.version.split()[0]}")
    lines.append(f"Frozen build   {bool(getattr(sys, 'frozen', False))}")
    lines.append(f"Location       {Path(sys.argv[0]).resolve()}")
    try:
        lines.append(f"avrdude        {get_programmer('avr').version()}")
    except (FlasherError, OSError) as exc:
        lines.append(f"avrdude        UNAVAILABLE: {exc}")

    section("Computer")
    lines.append(f"OS             {platform.platform()}")
    lines.append(f"Machine        {platform.machine()}")
    lines.append(f"Processor      {platform.processor() or 'unknown'}")

    section("Serial ports")
    ports = port_scanner.list_ports()
    if not ports:
        lines.append("none found")
    for port in ports:
        tags = []
        if port_scanner.is_likely_board(port):
            tags.append("looks like a board")
        if port_scanner.is_bluetooth(port):
            tags.append("bluetooth")
        vid_pid = (
            f"VID:PID {port.vid:04X}:{port.pid:04X}"
            if port.vid is not None and port.pid is not None
            else "no USB id"
        )
        suffix = f"  [{', '.join(tags)}]" if tags else ""
        lines.append(f"{port.device:<8} {port.description}  {vid_pid}{suffix}")

    if job is not None:
        section("What was attempted")
        lines.append(f"Board          {job.target.board.name} ({job.target.board.chip})")
        lines.append(f"Method         {job.target.mode.label} ({job.target.mode.id})")
        lines.append(f"Port           {job.target.port}")
        lines.append(f"Verify         {'on' if job.verify else 'off'}")
        lines.append(f"Firmware       {job.firmware.path}")
        lines.append(f"  format       {job.firmware.fmt.value}")
        lines.append(f"  file size    {job.firmware.size_bytes:,} bytes")
        lines.append(f"  to flash     {job.firmware.program_bytes:,} bytes "
                     f"({job.firmware.usage_percent(job.target.board):.1f}% of board)")
        lines.append(f"  CRC32        {job.firmware.crc32}")
        for warning in job.firmware.warnings:
            lines.append(f"  note         {warning}")
        try:
            argv = get_programmer(job.target.family).build_flash_argv(job)
            lines.append("")
            lines.append("Command:")
            lines.append("  " + " ".join(argv))
        except (FlasherError, OSError) as exc:
            lines.append(f"  command could not be built: {exc}")

    if preflight is not None:
        section("Pre-flight checks")
        lines.append(preflight.as_text() or "  (none run)")

    if self_test_result is not None:
        section("Self-test")
        lines.append(self_test_result.report.as_text() or "  (none run)")

    if result is not None:
        section("Outcome")
        lines.append(f"Result         {'SUCCESS' if result.ok else 'FAILED'}")
        lines.append(f"Message        {result.title}")
        lines.append(f"Detail         {result.detail}")
        lines.append(f"Duration       {result.duration:.1f} s")
        lines.append(f"Bytes written  {result.bytes_written:,}")
        lines.append(f"Verified       {result.verified}")
        lines.append(f"Exit code      {result.exit_code}")
        lines.append(f"Cancelled      {result.cancelled}")

    log = (result.log if result else "") or extra_log
    if log:
        section("Full tool output")
        lines.append(log.rstrip())

    lines.extend(["", "-- end of report --", ""])
    return "\n".join(lines)


def write_support_report(path: Path, **kwargs) -> Path:
    """Save a report, creating parent folders. Returns the path written."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(support_report(**kwargs), encoding="utf-8")
    return path
