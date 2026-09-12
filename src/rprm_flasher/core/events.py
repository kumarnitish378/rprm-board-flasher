"""Progress events emitted by a flashing backend.

Deliberately MCU-agnostic: an STM32 or ESP backend emits the same events, so the
UI never learns which tool produced them.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum


class Phase(str, Enum):
    """Stages of a flash job, in the order they occur."""

    STARTING = "starting"
    CONNECTING = "connecting"
    READING_INPUT = "reading_input"
    ERASING = "erasing"
    WRITING = "writing"
    VERIFYING = "verifying"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


#: Fraction of the overall progress bar each phase owns. avrdude reports write
#: and verify as two separate 0-100% passes; the operator should see one
#: continuous bar instead of a bar that appears to restart.
PHASE_WEIGHTS: dict[Phase, tuple[float, float]] = {
    Phase.STARTING: (0.0, 0.0),
    Phase.CONNECTING: (0.0, 2.0),
    Phase.READING_INPUT: (2.0, 5.0),
    Phase.ERASING: (5.0, 8.0),
    Phase.WRITING: (8.0, 80.0),
    Phase.VERIFYING: (80.0, 100.0),
}


@dataclass(frozen=True)
class ProgressEvent:
    """One observation about a running job.

    ``overall`` is what a progress bar should display; ``phase_percent`` is the
    backend's own 0-100 figure for the current phase only.
    """

    phase: Phase
    overall: float = 0.0
    phase_percent: float | None = None
    message: str = ""
    raw: str | None = None
    elapsed: float | None = None
    at: float = field(default_factory=time.monotonic)

    @classmethod
    def in_phase(
        cls,
        phase: Phase,
        phase_percent: float,
        message: str = "",
        raw: str | None = None,
        elapsed: float | None = None,
    ) -> "ProgressEvent":
        """Build an event, mapping a phase-local percentage onto the overall bar."""
        start, end = PHASE_WEIGHTS.get(phase, (0.0, 100.0))
        pct = max(0.0, min(100.0, phase_percent))
        return cls(
            phase=phase,
            overall=start + (end - start) * pct / 100.0,
            phase_percent=pct,
            message=message,
            raw=raw,
            elapsed=elapsed,
        )
