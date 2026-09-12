"""The two local firmware sources.

``LocalFileSource`` backs Browse and drag-and-drop. ``LocalLibrarySource``
reads a ``firmware/`` folder beside the executable, so a zip can be shipped
with the right builds already in it.
"""

from __future__ import annotations

import json
from pathlib import Path

from ..core.errors import FlasherError
from ..core.models import Firmware
from .base import FirmwareSource, inspect

FIRMWARE_SUFFIXES = (".hex", ".bin")

#: Optional file in the library folder giving builds readable names and an
#: order. Absent is fine: the folder listing is used instead.
MANIFEST_NAME = "manifest.json"


class LocalFileSource(FirmwareSource):
    """Whatever file the operator points at."""

    id = "file"
    label = "From file"

    def list(self) -> list[Firmware]:
        return []  # nothing to enumerate; the operator supplies the path

    def fetch(self, identifier: str) -> Firmware:
        return inspect(Path(identifier))


class LocalLibrarySource(FirmwareSource):
    """Firmware shipped alongside the tool.

    This is the slot a remote source will occupy later: same ``list``/``fetch``
    shape, with ``fetch`` downloading into a cache instead of reading a folder.
    """

    id = "library"
    label = "From library"

    def __init__(self, directory: Path) -> None:
        self.directory = Path(directory)

    def exists(self) -> bool:
        return self.directory.is_dir()

    def list(self) -> list[Firmware]:
        if not self.exists():
            return []

        labels = self._manifest_labels()
        found: list[Firmware] = []
        for path in sorted(self.directory.iterdir()):
            if path.suffix.lower() not in FIRMWARE_SUFFIXES:
                continue
            try:
                found.append(inspect(path, label=labels.get(path.name, "")))
            except FlasherError:
                # A damaged file in the library should not hide the good ones.
                continue
        return found

    def fetch(self, identifier: str) -> Firmware:
        candidate = self.directory / identifier
        if not candidate.exists():
            raise FlasherError(
                "That firmware is not in the library",
                f"{identifier} was not found in {self.directory}.",
            )
        return inspect(candidate, label=self._manifest_labels().get(identifier, ""))

    def _manifest_labels(self) -> dict[str, str]:
        manifest = self.directory / MANIFEST_NAME
        if not manifest.is_file():
            return {}
        try:
            payload = json.loads(manifest.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
        return {
            entry["file"]: entry.get("name", "")
            for entry in payload.get("firmware", [])
            if isinstance(entry, dict) and "file" in entry
        }
