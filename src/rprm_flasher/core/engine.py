"""Runs flash jobs on worker threads.

v1 uses a pool of one, so the behaviour is a simple queue. Raising
``max_workers`` is all that stands between this and flashing a bench of boards
at once: each job already carries its own port, parser, cancel flag and event
stream, and nothing is shared between them.
"""

from __future__ import annotations

import threading
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from typing import Callable

from .errors import FlasherError
from .events import Phase, ProgressEvent
from .models import FlashJob, JobResult
from .registry import get_programmer

#: Called as ``listener(job_id, event)`` from a worker thread. A Qt UI should
#: marshal onto the main thread here; the CLI just prints.
Listener = Callable[[str, ProgressEvent], None]


@dataclass
class RunningJob:
    job: FlashJob
    future: Future[JobResult]
    cancel: threading.Event

    @property
    def job_id(self) -> str:
        return self.job.job_id


class FlashEngine:
    """Owns the worker pool and the in-flight jobs."""

    def __init__(self, max_workers: int = 1) -> None:
        self.max_workers = max_workers
        self._pool = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="flash"
        )
        self._jobs: dict[str, RunningJob] = {}
        self._lock = threading.Lock()

    def submit(self, job: FlashJob, listener: Listener) -> RunningJob:
        """Queue ``job``. Returns immediately; progress arrives via ``listener``."""
        with self._lock:
            if job.job_id in self._jobs and not self._jobs[job.job_id].future.done():
                raise FlasherError(
                    "That board is already being flashed",
                    f"A job is still running on {job.job_id}. Wait for it to "
                    "finish, or cancel it first.",
                )
            cancel = threading.Event()
            future = self._pool.submit(self._run, job, listener, cancel)
            running = RunningJob(job=job, future=future, cancel=cancel)
            self._jobs[job.job_id] = running
            return running

    def run_blocking(self, job: FlashJob, listener: Listener) -> JobResult:
        """Convenience for the CLI and for tests."""
        return self.submit(job, listener).future.result()

    def cancel(self, job_id: str) -> bool:
        with self._lock:
            running = self._jobs.get(job_id)
        if running is None or running.future.done():
            return False
        running.cancel.set()
        return True

    def cancel_all(self) -> int:
        with self._lock:
            jobs = list(self._jobs.values())
        stopped = 0
        for running in jobs:
            if not running.future.done():
                running.cancel.set()
                stopped += 1
        return stopped

    def active(self) -> list[RunningJob]:
        with self._lock:
            return [j for j in self._jobs.values() if not j.future.done()]

    def shutdown(self, wait: bool = True) -> None:
        self.cancel_all()
        self._pool.shutdown(wait=wait)

    # -- worker body -------------------------------------------------------

    def _run(
        self, job: FlashJob, listener: Listener, cancel: threading.Event
    ) -> JobResult:
        def emit(event: ProgressEvent) -> None:
            try:
                listener(job.job_id, event)
            except Exception:  # noqa: BLE001 - a broken listener must not kill the job
                pass

        try:
            programmer = get_programmer(job.target.family)
            return programmer.flash(job, emit, cancel)
        except FlasherError as exc:
            emit(ProgressEvent(Phase.FAILED, 0.0, message=exc.title))
            return JobResult(
                job_id=job.job_id,
                ok=False,
                duration=0.0,
                title=exc.title,
                detail=exc.fix,
            )
        except Exception as exc:  # noqa: BLE001 - surfaced, never swallowed
            emit(ProgressEvent(Phase.FAILED, 0.0, message="Unexpected error"))
            return JobResult(
                job_id=job.job_id,
                ok=False,
                duration=0.0,
                title="Something went wrong inside the tool",
                detail=f"{type(exc).__name__}: {exc}",
            )
