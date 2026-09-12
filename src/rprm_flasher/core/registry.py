"""Maps a board family to the backend that can flash it.

This is the seam for new microcontrollers. Supporting STM32 means writing an
``StmProgrammer``, calling ``register("stm32", StmProgrammer)``, and adding
``config/boards/stm32.json``. Nothing else in the application changes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from ..backends.base import Programmer
from .errors import FlasherError
from .models import BoardCatalog

ProgrammerFactory = Callable[[], Programmer]

_FACTORIES: dict[str, ProgrammerFactory] = {}
_CACHE: dict[str, Programmer] = {}

CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"
BOARDS_DIR = CONFIG_DIR / "boards"


def register(family: str, factory: ProgrammerFactory) -> None:
    _FACTORIES[family] = factory
    _CACHE.pop(family, None)


def get_programmer(family: str) -> Programmer:
    """The backend for ``family``, created once and reused."""
    if family not in _CACHE:
        factory = _FACTORIES.get(family)
        if factory is None:
            raise FlasherError(
                "That board is not supported yet",
                f"No backend is registered for the {family!r} family.",
            )
        _CACHE[family] = factory()
    return _CACHE[family]


def families() -> list[str]:
    return sorted(_FACTORIES)


def load_catalog(directory: Path | None = None) -> BoardCatalog:
    """Load every board profile shipped with the tool.

    A ``boards/`` folder beside the executable takes precedence, so an operator
    can be sent a new board profile without a new build.
    """
    return BoardCatalog.load(directory or BOARDS_DIR)


def _install_builtin_backends() -> None:
    from ..backends.avr.programmer import AvrdudeProgrammer

    register("avr", AvrdudeProgrammer)


_install_builtin_backends()
