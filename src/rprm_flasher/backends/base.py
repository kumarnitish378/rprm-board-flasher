"""The single interface every MCU family implements.

Adding STM32 or ESP support means writing one subclass of :class:`Programmer`,
dropping a board JSON next to the existing ones, and registering the class. No
UI code changes.
"""

from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from typing import Callable

from ..core.events import ProgressEvent
from ..core.models import Capabilities, DetectResult, FlashJob, JobResult, Target

Emit = Callable[[ProgressEvent], None]


class Programmer(ABC):
    """Drives one family of microcontrollers.

    Implementations must be safe to use from a worker thread and must honour
    ``cancel`` promptly, leaving no orphaned child processes behind.
    """

    #: Matches ``BoardProfile.family``.
    family: str = ""

    @abstractmethod
    def capabilities(self) -> Capabilities:
        """What this backend supports, so the UI can hide what it cannot do."""

    @abstractmethod
    def flash(
        self,
        job: FlashJob,
        emit: Emit,
        cancel: threading.Event,
    ) -> JobResult:
        """Write ``job.firmware`` to ``job.target`` and return the outcome.

        Must not raise for ordinary failures; report them in the ``JobResult``.
        """

    def detect(self, target: Target, cancel: threading.Event | None = None) -> DetectResult:
        """Identify the chip on ``target.port`` without writing to it."""
        raise NotImplementedError(f"{self.family} backend cannot detect chips")

    def available(self) -> tuple[bool, str]:
        """Whether the backend's tooling is present. Returns (ok, reason)."""
        return True, ""
