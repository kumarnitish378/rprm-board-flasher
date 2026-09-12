"""User settings, stored portably.

The file lives beside the executable so a copied folder carries its settings
with it and nothing is hidden in AppData. If that location is read-only - the
tool run from a locked-down share or a write-protected stick - it falls back to
AppData rather than failing, and says which it used.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

FILE_NAME = "settings.json"


def app_dir() -> Path:
    """The folder the tool was started from."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path.cwd()


def fallback_dir() -> Path:
    base = os.environ.get("APPDATA") or os.environ.get("LOCALAPPDATA")
    root = Path(base) if base else Path.home()
    return root / "RapheBoardFlasher"


@dataclass
class Settings:
    """Everything the operator can change, with safe defaults.

    Defaults are deliberately the cautious choice: verification on, signature
    checking on. Someone who never opens Settings gets the safest behaviour.
    """

    theme: str = "dark"                 # "dark" | "light"
    verify_after_write: bool = True
    check_signature: bool = True
    default_board: str = "mega2560"
    default_mode: str = ""              # blank = the board's first mode
    firmware_dir: str = "firmware"
    avrdude_path: str = ""              # blank = the bundled copy
    keep_logs: bool = True

    #: Where this was loaded from; not persisted.
    source: Path | None = field(default=None, compare=False, repr=False)

    # -- persistence -------------------------------------------------------

    @classmethod
    def path(cls) -> Path:
        beside = app_dir() / FILE_NAME
        if beside.exists():
            return beside
        other = fallback_dir() / FILE_NAME
        return other if other.exists() else beside

    @classmethod
    def load(cls, path: Path | None = None) -> "Settings":
        """Read settings, ignoring anything malformed.

        A corrupt settings file must never stop the tool starting: an operator
        with no way to fix it would be stuck.
        """
        target = Path(path) if path else cls.path()
        settings = cls()
        settings.source = target
        if not target.is_file():
            return settings

        try:
            payload = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return settings
        if not isinstance(payload, dict):
            return settings

        known = {f.name for f in fields(cls)} - {"source"}
        for key, value in payload.items():
            if key in known and isinstance(value, type(getattr(settings, key))):
                setattr(settings, key, value)
        settings.normalise()
        return settings

    def save(self, path: Path | None = None) -> Path:
        """Write settings, falling back to AppData if the folder is read-only."""
        self.normalise()
        payload = {k: v for k, v in asdict(self).items() if k != "source"}
        blob = json.dumps(payload, indent=2)

        for candidate in filter(None, (path, self.source, app_dir() / FILE_NAME,
                                       fallback_dir() / FILE_NAME)):
            candidate = Path(candidate)
            try:
                candidate.parent.mkdir(parents=True, exist_ok=True)
                candidate.write_text(blob, encoding="utf-8")
                self.source = candidate
                return candidate
            except OSError:
                continue
        raise OSError("settings could not be written to any location")

    # -- validation --------------------------------------------------------

    def normalise(self) -> None:
        if self.theme not in ("dark", "light"):
            self.theme = "dark"
        if not self.firmware_dir.strip():
            self.firmware_dir = "firmware"

    def firmware_path(self) -> Path:
        folder = Path(self.firmware_dir)
        return folder if folder.is_absolute() else app_dir() / folder

    def avrdude(self) -> Path | None:
        """An override path, or None to use the bundled binary."""
        if not self.avrdude_path.strip():
            return None
        candidate = Path(self.avrdude_path)
        return candidate if candidate.is_file() else None
