"""Checks that run before anything is written to a board.

The tool is used by people who cannot read an avrdude error, at sites nobody
here can visit. So every condition that can be detected up front is detected up
front, and a blocking failure stops the write rather than producing a confusing
message halfway through.

The signature check is the important one: it makes "flashed the wrong board"
impossible in ISP mode, which is the mistake that costs a board.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field

from ..hardware import port_scanner
from .errors import FlasherError
from .models import FlashJob
from .registry import get_programmer


class Severity:
    BLOCK = "block"
    WARN = "warn"
    INFO = "info"


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    severity: str = Severity.BLOCK
    detail: str = ""
    fix: str = ""

    @property
    def blocking(self) -> bool:
        return not self.ok and self.severity == Severity.BLOCK


@dataclass
class PreflightReport:
    checks: list[Check] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not any(c.blocking for c in self.checks)

    @property
    def blockers(self) -> list[Check]:
        return [c for c in self.checks if c.blocking]

    @property
    def warnings(self) -> list[Check]:
        return [c for c in self.checks if not c.ok and c.severity == Severity.WARN]

    def raise_if_blocked(self) -> None:
        if self.ok:
            return
        first = self.blockers[0]
        raise FlasherError(first.detail or f"{first.name} failed", first.fix)

    def as_text(self) -> str:
        lines = []
        for check in self.checks:
            mark = "OK  " if check.ok else ("STOP" if check.blocking else "WARN")
            lines.append(f"  [{mark}] {check.name}" + (f" - {check.detail}" if check.detail else ""))
            if not check.ok and check.fix:
                lines.append(f"         {check.fix}")
        return "\n".join(lines)


def run_preflight(
    job: FlashJob,
    check_signature: bool = True,
    cancel: threading.Event | None = None,
) -> PreflightReport:
    """Everything worth knowing before a byte is written.

    ``check_signature`` costs a couple of seconds and only works in modes that
    can read the chip without engaging a bootloader, i.e. ISP.
    """
    report = PreflightReport()
    target = job.target

    # 1. Is the flashing tool itself intact?
    try:
        programmer = get_programmer(target.family)
    except FlasherError as exc:
        report.checks.append(
            Check("Backend", False, Severity.BLOCK, exc.title, exc.fix)
        )
        return report

    available, reason = programmer.available()
    report.checks.append(
        Check(
            "Flashing tool",
            available,
            Severity.BLOCK,
            "avrdude is bundled and readable" if available else reason,
            "Re-extract the tool's zip file; a file is missing." if not available else "",
        )
    )
    if not available:
        return report

    # 2. Does the firmware fit?
    fits = job.firmware.fits(target.board)
    report.checks.append(
        Check(
            "Firmware size",
            fits,
            Severity.BLOCK,
            f"{job.firmware.program_bytes:,} bytes, "
            f"{job.firmware.usage_percent(target.board):.0f}% of "
            f"{target.board.name} flash",
            f"This firmware needs more space than {target.board.name} has. "
            "Check the board selection and the firmware file." if not fits else "",
        )
    )

    for warning in job.firmware.warnings:
        report.checks.append(Check("Firmware note", False, Severity.WARN, warning))

    # 3. Does the port exist, and is it a sane choice?
    port = port_scanner.find(target.port)
    report.checks.append(
        Check(
            "Serial port",
            port is not None,
            Severity.BLOCK,
            port.label if port else f"{target.port} is not present",
            "Plug the board in and press refresh, then pick the port again."
            if port is None else "",
        )
    )
    if port is None:
        return report

    if port_scanner.is_bluetooth(port):
        report.checks.append(
            Check(
                "Port type",
                False,
                Severity.BLOCK,
                f"{target.port} is a Bluetooth port, not a board",
                "Windows creates these automatically and they look like board "
                "ports. Pick the one named after your adapter (Arduino, CH340 "
                "or FTDI).",
            )
        )
        return report

    report.checks.append(
        Check(
            "Port type",
            port_scanner.is_likely_board(port),
            Severity.WARN,
            port.label,
            "This does not look like an Arduino or USB-serial adapter. Check "
            "you picked the right port." if not port_scanner.is_likely_board(port) else "",
        )
    )

    # 4. Is the chip on the other end the one that was selected?
    can_read_signature = (
        check_signature
        and programmer.capabilities().can_detect
        and target.mode.port_belongs_to == "programmer"
    )
    if not can_read_signature:
        report.checks.append(
            Check(
                "Chip identity",
                True,
                Severity.INFO,
                "not checked in this mode - avrdude will verify it during the write",
            )
        )
        return report

    result = programmer.detect(target, cancel)
    if not result.ok:
        report.checks.append(
            Check("Chip identity", False, Severity.BLOCK, result.title, result.detail)
        )
        return report

    expected = (target.board.signature or "").lower()
    actual = (result.signature or "").lower()
    matches = not expected or expected == actual

    report.checks.append(
        Check(
            "Chip identity",
            matches,
            Severity.BLOCK,
            f"{actual} on the board" + (f", expected {expected}" if not matches else ""),
            _mismatch_fix(actual) if not matches else "",
        )
    )
    return report


def _mismatch_fix(actual: str) -> str:
    """Name the board they probably meant, rather than quoting hex at them."""
    from .registry import load_catalog

    matches = load_catalog().by_signature(actual)
    if matches:
        names = " or ".join(sorted({b.name for b in matches}))
        return (
            f"The connected board is a {names}. Select it in the board list, "
            "or connect the board you meant to flash."
        )
    return (
        "The connected chip is not one this tool knows. Check the ISP wiring "
        "and that the target board has power."
    )
