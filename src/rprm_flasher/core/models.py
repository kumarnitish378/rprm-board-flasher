"""Domain types shared by every backend.

Nothing here mentions avrdude, Qt, or AVR specifics. A board is described by a
JSON profile; a backend interprets the ``options`` of the mode it is handed.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Iterator


class FirmwareFormat(str, Enum):
    INTEL_HEX = "hex"
    RAW_BINARY = "bin"
    ELF = "elf"

    @classmethod
    def from_suffix(cls, path: Path) -> "FirmwareFormat | None":
        return {
            ".hex": cls.INTEL_HEX,
            ".eep": cls.INTEL_HEX,
            ".bin": cls.RAW_BINARY,
            ".elf": cls.ELF,
        }.get(path.suffix.lower())


@dataclass(frozen=True)
class UploadMode:
    """One way of reaching a board, e.g. "via an UNO running ArduinoISP".

    ``options`` is an opaque bag the owning backend understands. For AVR it
    carries the avrdude programmer id and baud rate.
    """

    id: str
    label: str
    description: str = ""
    #: True when this mode erases the chip, destroying any bootloader present.
    erases_bootloader: bool = False
    #: Which board the operator should plug into: "target" or "programmer".
    port_belongs_to: str = "target"
    options: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class BoardProfile:
    """A flashable board, loaded from ``config/boards/<family>.json``."""

    id: str
    name: str
    family: str
    chip: str
    flash_bytes: int
    signature: str | None = None
    modes: dict[str, UploadMode] = field(default_factory=dict)
    #: Pin map for the wiring-help dialog: list of (from_pin, to_pin) per mode id.
    wiring: dict[str, list[tuple[str, str]]] = field(default_factory=dict)
    notes: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any], family: str) -> "BoardProfile":
        modes = {
            mode_id: UploadMode(
                id=mode_id,
                label=m["label"],
                description=m.get("description", ""),
                erases_bootloader=m.get("erases_bootloader", False),
                port_belongs_to=m.get("port_belongs_to", "target"),
                options=m.get("options", {}),
            )
            for mode_id, m in data.get("modes", {}).items()
        }
        wiring = {
            mode_id: [(row[0], row[1]) for row in rows]
            for mode_id, rows in data.get("wiring", {}).items()
        }
        return cls(
            id=data["id"],
            name=data["name"],
            family=data.get("family", family),
            chip=data["chip"],
            flash_bytes=int(data["flash_bytes"]),
            signature=data.get("signature"),
            modes=modes,
            wiring=wiring,
            notes=data.get("notes", ""),
        )


class BoardCatalog:
    """All board profiles found in a directory of per-family JSON files."""

    def __init__(self, boards: list[BoardProfile]) -> None:
        self._boards = boards
        self._by_id = {b.id: b for b in boards}

    @classmethod
    def load(cls, directory: Path) -> "BoardCatalog":
        boards: list[BoardProfile] = []
        for path in sorted(directory.glob("*.json")):
            payload = json.loads(path.read_text(encoding="utf-8"))
            family = payload.get("family", path.stem)
            for entry in payload["boards"]:
                boards.append(BoardProfile.from_dict(entry, family))
        return cls(boards)

    def __iter__(self) -> Iterator[BoardProfile]:
        return iter(self._boards)

    def __len__(self) -> int:
        return len(self._boards)

    def get(self, board_id: str) -> BoardProfile:
        try:
            return self._by_id[board_id]
        except KeyError:
            raise KeyError(f"unknown board {board_id!r}") from None

    def families(self) -> set[str]:
        return {b.family for b in self._boards}

    def for_family(self, family: str) -> list[BoardProfile]:
        return [b for b in self._boards if b.family == family]

    def by_signature(self, signature: str) -> list[BoardProfile]:
        want = signature.lower().replace("_", "").replace(" ", "")
        return [b for b in self._boards if b.signature and b.signature.lower() == want]


@dataclass(frozen=True)
class Firmware:
    """A validated firmware image on local disk."""

    path: Path
    fmt: FirmwareFormat
    size_bytes: int
    crc32: str
    #: Bytes that will actually land in flash; differs from file size for hex.
    program_bytes: int
    label: str = ""
    warnings: tuple[str, ...] = ()

    @property
    def name(self) -> str:
        return self.label or self.path.name

    def fits(self, board: BoardProfile) -> bool:
        return self.program_bytes <= board.flash_bytes

    def usage_percent(self, board: BoardProfile) -> float:
        if not board.flash_bytes:
            return 0.0
        return 100.0 * self.program_bytes / board.flash_bytes


@dataclass(frozen=True)
class SerialPortInfo:
    device: str
    description: str = ""
    manufacturer: str = ""
    vid: int | None = None
    pid: int | None = None

    @property
    def label(self) -> str:
        if self.description and self.description != "n/a":
            return f"{self.device} — {self.description}"
        return self.device


@dataclass(frozen=True)
class Target:
    """Where to flash: a board, how to reach it, and on which port."""

    board: BoardProfile
    mode: UploadMode
    port: str

    @property
    def family(self) -> str:
        return self.board.family


@dataclass(frozen=True)
class FlashJob:
    target: Target
    firmware: Firmware
    verify: bool = True
    #: Stable id so a multi-board run can tell rows apart.
    job_id: str = ""

    def __post_init__(self) -> None:
        if not self.job_id:
            object.__setattr__(self, "job_id", self.target.port)


@dataclass(frozen=True)
class JobResult:
    job_id: str
    ok: bool
    duration: float
    bytes_written: int = 0
    verified: bool = False
    title: str = ""
    detail: str = ""
    log: str = ""
    exit_code: int | None = None
    cancelled: bool = False


@dataclass(frozen=True)
class DetectResult:
    ok: bool
    signature: str | None = None
    chip: str | None = None
    matched_board: BoardProfile | None = None
    title: str = ""
    detail: str = ""
    log: str = ""


@dataclass(frozen=True)
class Capabilities:
    """What a backend can do, so the UI can hide controls it cannot honour."""

    can_detect: bool = False
    can_verify: bool = False
    can_erase: bool = False
    can_read_back: bool = False
    can_write_fuses: bool = False
    supported_formats: tuple[FirmwareFormat, ...] = (FirmwareFormat.INTEL_HEX,)
