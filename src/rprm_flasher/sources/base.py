"""Where firmware comes from.

v1 ships two sources, both local. A remote source is a third implementation of
this interface: ``fetch`` downloads to a cache directory and returns the local
path, and every caller above stays the same.
"""

from __future__ import annotations

import binascii
import re
from abc import ABC, abstractmethod
from pathlib import Path

from ..core.errors import FlasherError
from ..core.models import Firmware, FirmwareFormat

#: Refuse anything implausibly large before reading it. The biggest AVR part
#: has 256 KB of flash; 8 MB leaves room for other families later.
MAX_FIRMWARE_BYTES = 8 * 1024 * 1024

_HEX_LINE = re.compile(r"^:([0-9A-Fa-f]{2})([0-9A-Fa-f]{4})([0-9A-Fa-f]{2})([0-9A-Fa-f]*)$")


class FirmwareSource(ABC):
    """A place firmware can be listed and fetched from."""

    id: str = ""
    label: str = ""

    @abstractmethod
    def list(self) -> list[Firmware]:
        """Everything this source currently offers. May be empty."""

    @abstractmethod
    def fetch(self, identifier: str) -> Firmware:
        """Resolve one entry to a validated image on local disk."""


def inspect(path: Path, label: str = "") -> Firmware:
    """Validate a firmware file and measure it.

    Raises :class:`FlasherError` with an operator-readable message rather than
    letting a malformed file reach avrdude, where the error would be cryptic.
    """
    path = Path(path)
    if not path.exists():
        raise FlasherError(
            "That firmware file is not there",
            f"Nothing was found at {path}. Choose the file again.",
        )
    if not path.is_file():
        raise FlasherError(
            "That is a folder, not a firmware file",
            "Pick a .hex or .bin file inside it.",
        )

    fmt = FirmwareFormat.from_suffix(path)
    if fmt is None:
        raise FlasherError(
            "That file type cannot be flashed",
            f"{path.suffix or 'The file'} is not a firmware image. "
            "Use a .hex or .bin file.",
        )
    if fmt is FirmwareFormat.ELF:
        raise FlasherError(
            "ELF files are not supported yet",
            "Export the build as a .hex file instead.",
        )

    size = path.stat().st_size
    if size == 0:
        raise FlasherError(
            "That firmware file is empty",
            "The build may have failed. Get a fresh copy of the file.",
        )
    if size > MAX_FIRMWARE_BYTES:
        raise FlasherError(
            "That firmware file is far too large",
            f"It is {size / 1048576:.1f} MB. Check you picked the right file.",
        )

    raw = path.read_bytes()
    crc = f"{binascii.crc32(raw) & 0xFFFFFFFF:08X}"

    if fmt is FirmwareFormat.INTEL_HEX:
        program_bytes, warnings = _inspect_intel_hex(raw, path)
    else:
        program_bytes, warnings = size, (
            "A .bin file carries no address information, so it is written from "
            "0x0000. That is correct for a full firmware image and wrong for "
            "anything else.",
        )

    return Firmware(
        path=path,
        fmt=fmt,
        size_bytes=size,
        crc32=crc,
        program_bytes=program_bytes,
        label=label,
        warnings=warnings,
    )


def _inspect_intel_hex(raw: bytes, path: Path) -> tuple[int, tuple[str, ...]]:
    """Count the bytes an Intel HEX file will put in flash, validating as it goes."""
    try:
        text = raw.decode("ascii")
    except UnicodeDecodeError:
        raise FlasherError(
            "That .hex file is not valid Intel HEX",
            "It contains binary data. If this is a raw image, rename it to .bin.",
        ) from None

    total = 0
    saw_eof = False
    warnings: list[str] = []

    for number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        match = _HEX_LINE.match(stripped)
        if not match:
            raise FlasherError(
                "That .hex file is damaged",
                f"Line {number} is not a valid Intel HEX record. "
                "Get a fresh copy of the build.",
            )

        count = int(match.group(1), 16)
        record_type = int(match.group(3), 16)
        payload = match.group(4)

        if len(payload) != (count + 1) * 2:
            raise FlasherError(
                "That .hex file is damaged",
                f"Line {number} declares {count} data bytes but does not carry "
                "that many. Get a fresh copy of the build.",
            )

        body = bytes.fromhex(stripped[1:])
        if sum(body) & 0xFF:
            raise FlasherError(
                "That .hex file is damaged",
                f"Line {number} fails its own checksum. The file was corrupted "
                "in transit. Get a fresh copy of the build.",
            )

        if record_type == 0x00:
            total += count
        elif record_type == 0x01:
            saw_eof = True
            break

    if total == 0:
        raise FlasherError(
            "That .hex file contains no program",
            f"{path.name} has no data records. The build may have failed.",
        )
    if not saw_eof:
        warnings.append(
            "The file has no end-of-file record, so it may have been truncated."
        )

    return total, tuple(warnings)
