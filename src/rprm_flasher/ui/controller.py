"""The bridge between the Qt main thread and the flashing engine.

Every long operation - flashing, detecting, pre-flight - spawns a subprocess and
must never run on the GUI thread. They run on worker threads and report back as
Qt signals, which Qt delivers to the main thread automatically because the
emitting thread differs from the receiver's.

The window therefore only ever connects to signals; it never waits on anything.
"""

from __future__ import annotations

import threading

from PySide6.QtCore import QObject, Signal

from ..core.diagnostics import SelfTestResult, self_test
from ..core.engine import FlashEngine
from ..core.errors import FlasherError
from ..core.events import ProgressEvent
from ..core.models import DetectResult, FlashJob, JobResult, Target
from ..core.preflight import PreflightReport, run_preflight
from ..core.registry import get_programmer


class FlashController(QObject):
    """Owns the engine and turns its callbacks into Qt signals."""

    progress = Signal(object)          # ProgressEvent
    finished = Signal(object)          # JobResult
    preflightFinished = Signal(object, object)   # PreflightReport, FlashJob
    detectFinished = Signal(object)    # DetectResult
    selfTestFinished = Signal(object)  # SelfTestResult
    failed = Signal(str, str)          # title, fix - for problems before launch
    busyChanged = Signal(bool)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._engine = FlashEngine(max_workers=1)
        self._job: FlashJob | None = None
        self._busy = False

    # -- state -------------------------------------------------------------

    @property
    def busy(self) -> bool:
        return self._busy

    def _set_busy(self, value: bool) -> None:
        if value != self._busy:
            self._busy = value
            self.busyChanged.emit(value)

    # -- operations --------------------------------------------------------

    def start(self, job: FlashJob, check_signature: bool = True) -> None:
        """Run pre-flight, then flash if nothing blocks.

        Pre-flight talks to the board in ISP mode, so the whole sequence runs
        off the GUI thread and the window stays responsive throughout.
        """
        if self._busy:
            return
        self._job = job
        self._set_busy(True)
        self._spawn(self._run_sequence, job, check_signature)

    def detect(self, target: Target) -> None:
        if self._busy:
            return
        self._set_busy(True)
        self._spawn(self._run_detect, target)

    def run_self_test(self, port: str | None = None, board_id: str | None = None,
                      mode_id: str | None = None) -> None:
        if self._busy:
            return
        self._set_busy(True)
        self._spawn(self._run_self_test, port, board_id, mode_id)

    def cancel(self) -> None:
        if self._job is not None:
            self._engine.cancel(self._job.job_id)

    def shutdown(self) -> None:
        self._engine.shutdown(wait=False)

    # -- worker bodies -----------------------------------------------------

    def _run_sequence(self, job: FlashJob, check_signature: bool) -> None:
        try:
            report = run_preflight(job, check_signature=check_signature)
            self.preflightFinished.emit(report, job)
            if not report.ok:
                blocker = report.blockers[0]
                self.finished.emit(
                    JobResult(
                        job_id=job.job_id,
                        ok=False,
                        duration=0.0,
                        title=blocker.detail or blocker.name,
                        detail=blocker.fix,
                        log=_preflight_log(report),
                    )
                )
                return

            result = self._engine.run_blocking(
                job, lambda _id, event: self.progress.emit(event)
            )
            self.finished.emit(result)
        except FlasherError as exc:
            self.failed.emit(exc.title, exc.fix)
        except Exception as exc:  # noqa: BLE001 - surfaced, never swallowed
            self.failed.emit(
                "Something went wrong inside the tool", f"{type(exc).__name__}: {exc}"
            )
        finally:
            self._set_busy(False)

    def _run_detect(self, target: Target) -> None:
        try:
            programmer = get_programmer(target.family)
            self.detectFinished.emit(programmer.detect(target))
        except FlasherError as exc:
            self.detectFinished.emit(
                DetectResult(ok=False, title=exc.title, detail=exc.fix)
            )
        except Exception as exc:  # noqa: BLE001
            self.detectFinished.emit(
                DetectResult(
                    ok=False,
                    title="Could not read the board",
                    detail=f"{type(exc).__name__}: {exc}",
                )
            )
        finally:
            self._set_busy(False)

    def _run_self_test(self, port, board_id, mode_id) -> None:
        try:
            self.selfTestFinished.emit(self_test(port, board_id, mode_id))
        except Exception as exc:  # noqa: BLE001
            self.failed.emit("Self-test could not run", f"{type(exc).__name__}: {exc}")
        finally:
            self._set_busy(False)

    @staticmethod
    def _spawn(target, *args) -> None:
        threading.Thread(target=target, args=args, daemon=True).start()


def _preflight_log(report: PreflightReport) -> str:
    """Give a blocked run a log too, so Save log is never empty."""
    return "Pre-flight checks stopped this run before anything was written.\n\n" + (
        report.as_text()
    )


__all__ = ["FlashController", "SelfTestResult"]
