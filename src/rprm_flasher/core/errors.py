"""Turning tool output into something an operator can act on.

Each rule maps a pattern in a backend's output to a *cause* and a *fix*. The UI
shows the cause as the headline and the fix as the sub-line; the raw text stays
in the log. Rules are ordered: the first match wins, so put specific patterns
above general ones.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class FriendlyError:
    """A diagnosis. ``title`` says what went wrong, ``fix`` says what to do."""

    title: str
    fix: str
    raw: str = ""


@dataclass(frozen=True)
class ErrorRule:
    pattern: re.Pattern[str]
    title: str
    fix: str

    def apply(self, text: str) -> FriendlyError | None:
        match = self.pattern.search(text)
        if not match:
            return None
        groups = {k: v for k, v in (match.groupdict() or {}).items() if v}
        return FriendlyError(
            title=self.title.format(**groups) if groups else self.title,
            fix=self.fix.format(**groups) if groups else self.fix,
            raw=match.group(0).strip(),
        )


def _rule(pattern: str, title: str, fix: str) -> ErrorRule:
    return ErrorRule(re.compile(pattern, re.IGNORECASE | re.MULTILINE), title, fix)


#: Ordered most-specific first. Patterns verified against avrdude 8.0-arduino.1
#: where the comment says so; the rest are tolerant by design and fall back to
#: showing raw output rather than guessing wrongly.
AVRDUDE_RULES: list[ErrorRule] = [
    # Verified live against avrdude 8.0-arduino.1.
    _rule(
        r"cannot open port \\\\\.\\(?P<port>\w+):.*cannot find the file",
        "{port} is not there any more",
        "The board was unplugged, or Windows gave it a different port. "
        "Press the refresh button and pick the port again.",
    ),
    _rule(
        r"cannot open port \\\\\.\\(?P<port>\w+):.*(access is denied|being used)",
        "{port} is in use by another program",
        "Close the Arduino IDE, any Serial Monitor, or other terminal holding "
        "the port, then try again.",
    ),
    _rule(
        r"unable to open (?:port|programmer).*?(?P<port>COM\d+)",
        "Could not open {port}",
        "Check the board is plugged in and that no other program is using the port.",
    ),
    # ISP link problems.
    _rule(
        r"programmer is not responding|not in sync|stk500_recv|stk500_getsync",
        "No reply from the programmer",
        "Check the ArduinoISP sketch is loaded on the UNO and that a 10 uF "
        "capacitor sits between the UNO's RESET and GND. Then confirm the six "
        "ISP wires are in the right pins.",
    ),
    _rule(
        r"initialization failed|failed to enter programming mode",
        "The target board did not answer",
        "The wiring is the usual cause. Open 'Show wiring' and check every jumper, "
        "and make sure the target board has power.",
    ),
    # Write / verify problems. These sit ABOVE the signature rules because
    # avrdude prints a harmless "Device signature = ..." line on every
    # successful connection, and a verify failure must not be reported as a
    # wrong-board error.
    _rule(
        r"verification error.*?0x(?P<addr>[0-9a-f]+)",
        "The board read back wrong",
        "The firmware was written but did not verify at address 0x{addr}. This is "
        "usually a loose wire or a weak power supply. Re-seat the jumpers and retry.",
    ),
    _rule(
        r"verification error|verify error|content mismatch",
        "The board read back wrong",
        "The firmware was written but did not verify. Re-seat the jumpers, use a "
        "powered USB port, and retry.",
    ),
    # Wrong chip. Both patterns demand mismatch context: a bare
    # "Device signature = 0x..." is what a HEALTHY connection prints, so
    # matching on it alone misdiagnoses every other failure as a wrong board.
    _rule(
        r"expected signature[\s\S]{0,300}?device signature\s*=\s*(?P<sig>0x[0-9a-f]{6})",
        "This is not the board you selected",
        "The chip reports signature {sig}. Pick the matching board in the list, "
        "or press 'Detect board' to select it automatically.",
    ),
    _rule(
        r"device signature\s*=\s*(?P<sig>0x[0-9a-f]{6})[\s\S]{0,120}?double check chip",
        "This is not the board you selected",
        "The chip reports signature {sig}. Pick the matching board in the list, "
        "or press 'Detect board' to select it automatically.",
    ),
    _rule(
        r"double check chip|wrong device|signature mismatch",
        "This is not the board you selected",
        "Press 'Detect board' to identify the chip, or check the ISP wiring.",
    ),
    _rule(
        r"flash memory.*?(too large|exceeds|larger than)|address .* out of range",
        "This firmware is too big for the board",
        "The file needs more flash than the selected board has. Check you picked "
        "the right board and the right firmware file.",
    ),
    # Input file problems.
    _rule(
        r"can't open input file|unable to open input file|no such file",
        "The firmware file could not be read",
        "The file may have been moved, renamed, or deleted. Choose it again.",
    ),
    _rule(
        r"invalid file format|error reading intel hex|checksum mismatch",
        "The firmware file is damaged",
        "The .hex file failed its own checksum. Get a fresh copy of the build.",
    ),
    # Configuration problems (our bug, not the operator's).
    _rule(
        r"(?:part|programmer) .* not found|invalid part|unknown programmer",
        "Internal configuration problem",
        "The board profile is wrong. Send the log to the tool maintainer.",
    ),
]


def diagnose(text: str, rules: list[ErrorRule] | None = None) -> FriendlyError | None:
    """Return the best explanation for ``text``, or None if no rule matches."""
    for rule in rules or AVRDUDE_RULES:
        found = rule.apply(text)
        if found:
            return found
    return None


def fallback(text: str) -> FriendlyError:
    """Used when no rule matches: show the tool's own first error verbatim.

    Better an unpolished true message than a confident wrong one.
    """
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.lower().startswith(("error:", "avrdude: error")):
            return FriendlyError(
                title="Flashing failed",
                fix=stripped.split(":", 1)[-1].strip() or stripped,
                raw=stripped,
            )
    return FriendlyError(
        title="Flashing failed",
        fix="Open 'Show details' for the full output, then send the log to the "
        "tool maintainer.",
        raw=text.strip()[-400:],
    )


def explain(text: str, rules: list[ErrorRule] | None = None) -> FriendlyError:
    """``diagnose`` with a guaranteed answer."""
    return diagnose(text, rules) or fallback(text)


class FlasherError(Exception):
    """Raised for problems detected before a tool is even launched."""

    def __init__(self, title: str, fix: str = "") -> None:
        super().__init__(title)
        self.title = title
        self.fix = fix

    def as_friendly(self) -> FriendlyError:
        return FriendlyError(title=self.title, fix=self.fix)
