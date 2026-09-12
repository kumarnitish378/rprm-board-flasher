"""The avrdude backend.

Everything avrdude-specific lives here and in :mod:`.parser`. The rest of the
application talks to this class only through :class:`Programmer`.
"""

from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path

from ...core.errors import FlasherError, explain
from ...core.events import Phase, ProgressEvent
from ...core.models import (
    Capabilities,
    DetectResult,
    FirmwareFormat,
    FlashJob,
    JobResult,
    Target,
)
from ..base import Emit, Programmer
from .parser import AvrdudeParser

TOOLS_DIR = Path(__file__).resolve().parent / "tools"

#: avrdude's ``-U`` format character per firmware format.
_FORMAT_CHAR = {
    FirmwareFormat.INTEL_HEX: "i",
    FirmwareFormat.RAW_BINARY: "r",
    FirmwareFormat.ELF: "e",
}

#: Keeps a console window from flashing up when the GUI spawns avrdude.
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0

#: How long to wait for a terminated avrdude to exit before killing it.
_KILL_GRACE = 2.0

#: Seconds of total silence before we assume avrdude is wedged. Opening a
#: Bluetooth COM port blocks forever on Windows, and an operator can easily
#: pick one out of the port list, so a watchdog is not optional. During a real
#: flash avrdude redraws its progress bar constantly, so silence this long
#: means it is stuck rather than busy.
STALL_TIMEOUT = 25.0

#: Absolute ceiling. A 256 KB ISP write at 19200 baud is genuinely slow, so
#: this is deliberately generous.
TOTAL_TIMEOUT = 900.0

#: Detection either answers quickly or is not going to.
DETECT_STALL_TIMEOUT = 15.0
DETECT_TOTAL_TIMEOUT = 60.0


def _bundled(name: str) -> Path:
    """Resolve a bundled tool, working both from source and from PyInstaller."""
    frozen_base = getattr(sys, "_MEIPASS", None)
    if frozen_base:
        packaged = Path(frozen_base) / "tools" / "avr" / name
        if packaged.exists():
            return packaged
    return TOOLS_DIR / name


class AvrdudeProgrammer(Programmer):
    """Flashes AVR parts using a bundled avrdude."""

    family = "avr"

    def __init__(
        self,
        executable: Path | None = None,
        config: Path | None = None,
        extra_args: list[str] | None = None,
        launch_prefix: list[str] | None = None,
    ) -> None:
        self.executable = Path(executable) if executable else _bundled("avrdude.exe")
        self.config = Path(config) if config else _bundled("avrdude.conf")
        self.extra_args = list(extra_args or [])
        #: Prepended to every command line. Lets the test suite run a stand-in
        #: avrdude under the Python interpreter.
        self.launch_prefix = list(launch_prefix or [])

    # -- Programmer interface ---------------------------------------------

    def capabilities(self) -> Capabilities:
        return Capabilities(
            can_detect=True,
            can_verify=True,
            can_erase=True,
            can_read_back=True,
            can_write_fuses=False,  # deliberately withheld until v2
            supported_formats=(FirmwareFormat.INTEL_HEX, FirmwareFormat.RAW_BINARY),
        )

    def available(self) -> tuple[bool, str]:
        if not self.executable.exists():
            return False, f"avrdude is missing from {self.executable}"
        if not self.config.exists():
            return False, f"avrdude.conf is missing from {self.config}"
        return True, ""

    def version(self) -> str:
        """The bundled avrdude's version string, for the About box."""
        proc = self._run_blocking(
            [*self.launch_prefix, str(self.executable), "-C", str(self.config), "-?"]
        )
        for line in (proc.stderr or "").splitlines():
            if "version" in line.lower():
                return line.strip()
        return "unknown"

    def flash(
        self,
        job: FlashJob,
        emit: Emit,
        cancel: threading.Event,
    ) -> JobResult:
        ok, reason = self.available()
        if not ok:
            raise FlasherError("The flashing tool is missing", reason)

        started = time.monotonic()
        emit(ProgressEvent(Phase.STARTING, 0.0, message="Starting avrdude"))

        argv = self.build_flash_argv(job)
        parser = AvrdudeParser()
        code, log, timed_out = self._stream(argv, parser, emit, cancel)
        duration = time.monotonic() - started

        if cancel.is_set():
            emit(ProgressEvent(Phase.CANCELLED, 0.0, message="Cancelled"))
            return JobResult(
                job_id=job.job_id,
                ok=False,
                duration=duration,
                title="Cancelled",
                detail="The board may hold a partial firmware. Flash it again "
                "before using it.",
                log=log,
                exit_code=code,
                cancelled=True,
            )

        if timed_out:
            emit(ProgressEvent(Phase.FAILED, 0.0, message="No response"))
            return JobResult(
                job_id=job.job_id,
                ok=False,
                duration=duration,
                title=f"{job.target.port} never answered",
                detail=self._stall_hint(job.target.port),
                log=log,
                exit_code=code,
            )

        # A write is only successful if avrdude said so AND exited cleanly.
        succeeded = code == 0 and (parser.verified or not job.verify)
        if succeeded:
            written = parser.bytes_verified or parser.bytes_written
            emit(ProgressEvent(Phase.DONE, 100.0, message="Done"))
            return JobResult(
                job_id=job.job_id,
                ok=True,
                duration=duration,
                bytes_written=written,
                verified=parser.verified,
                title="Flash complete",
                detail=self._success_detail(written, parser.verified, duration),
                log=log,
                exit_code=code,
            )

        friendly = explain(log)
        emit(ProgressEvent(Phase.FAILED, 0.0, message=friendly.title))
        return JobResult(
            job_id=job.job_id,
            ok=False,
            duration=duration,
            title=friendly.title,
            detail=friendly.fix,
            log=log,
            exit_code=code,
        )

    def detect(
        self, target: Target, cancel: threading.Event | None = None
    ) -> DetectResult:
        ok, reason = self.available()
        if not ok:
            raise FlasherError("The flashing tool is missing", reason)

        argv = self.build_detect_argv(target)
        parser = AvrdudeParser()
        _code, log, timed_out = self._stream(
            argv,
            parser,
            lambda _e: None,
            cancel or threading.Event(),
            stall_timeout=DETECT_STALL_TIMEOUT,
            total_timeout=DETECT_TOTAL_TIMEOUT,
        )

        if timed_out:
            return DetectResult(
                ok=False,
                title=f"{target.port} never answered",
                detail=self._stall_hint(target.port),
                log=log,
            )

        if parser.signature:
            return DetectResult(
                ok=True,
                signature=parser.signature,
                chip=parser.detected_chip,
                title="Chip found",
                detail=f"Signature {parser.signature}",
                log=log,
            )

        friendly = explain(log)
        return DetectResult(
            ok=False, title=friendly.title, detail=friendly.fix, log=log
        )

    # -- command construction ---------------------------------------------

    def build_flash_argv(self, job: FlashJob) -> list[str]:
        """The exact avrdude command line for ``job``.

        Kept separate from execution so it can be shown in the log panel and
        asserted on in tests without spawning anything.
        """
        target = job.target
        options = target.mode.options
        fmt = _FORMAT_CHAR.get(job.firmware.fmt)
        if fmt is None:
            raise FlasherError(
                "That firmware format is not supported",
                f"{job.firmware.path.suffix} files cannot be flashed to an AVR board.",
            )

        argv = self._base_argv(target)
        if options.get("chip_erase"):
            argv.append("-e")
        argv.extend(options.get("extra", []))
        if not job.verify:
            argv.append("-V")  # avrdude verifies by default; -V turns it off
        argv.extend(self.extra_args)
        argv += ["-U", f"flash:w:{job.firmware.path}:{fmt}"]
        return argv

    def build_detect_argv(self, target: Target) -> list[str]:
        """Read the chip signature without writing anything.

        ``-n`` blocks all writes; ``-F`` stops avrdude bailing out when the
        signature does not match the part we guessed, which is exactly the case
        we want to report.
        """
        return self._base_argv(target) + ["-n", "-F"]

    def _base_argv(self, target: Target) -> list[str]:
        options = target.mode.options
        programmer = options.get("programmer")
        if not programmer:
            raise FlasherError(
                "Internal configuration problem",
                f"Board profile {target.board.id!r} has no programmer set for "
                f"mode {target.mode.id!r}.",
            )
        argv = [
            *self.launch_prefix,
            str(self.executable),
            "-C", str(self.config),
            "-p", target.board.chip,
            "-c", str(programmer),
            "-P", target.port,
        ]
        baud = options.get("baud")
        if baud:
            argv += ["-b", str(baud)]
        bitclock = options.get("bitclock")
        if bitclock:
            argv += ["-B", str(bitclock)]
        return argv

    @staticmethod
    def _stall_hint(port: str) -> str:
        """Windows Bluetooth ports are the usual cause, so name them first."""
        return (
            f"{port} accepted the connection but sent nothing back. If it is a "
            "Bluetooth port, pick the board's own port instead — they look "
            "identical in the list. Otherwise unplug the board, plug it back in, "
            "and press refresh."
        )

    @staticmethod
    def _success_detail(written: int, verified: bool, duration: float) -> str:
        size = f"{written / 1024:.0f} KB" if written >= 1024 else f"{written} bytes"
        checked = "written and verified" if verified else "written"
        return f"{size} {checked} in {duration:.1f} s · you can unplug the board"

    # -- process plumbing --------------------------------------------------

    def _stream(
        self,
        argv: list[str],
        parser: AvrdudeParser,
        emit: Emit,
        cancel: threading.Event,
        stall_timeout: float = STALL_TIMEOUT,
        total_timeout: float = TOTAL_TIMEOUT,
    ) -> tuple[int, str, bool]:
        """Run avrdude, feeding its output to ``parser`` as it arrives.

        Returns ``(exit_code, transcript, timed_out)``. The transcript opens
        with the command we ran, so a saved log is self-explanatory.
        """
        transcript: list[str] = ["$ " + " ".join(argv), "\n\n"]

        proc = subprocess.Popen(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=_NO_WINDOW,
        )

        chunks: queue.Queue[bytes | None] = queue.Queue()

        def pump(stream) -> None:
            try:
                while True:
                    data = stream.read(256)
                    if not data:
                        break
                    chunks.put(data)
            finally:
                chunks.put(None)

        readers = [
            threading.Thread(target=pump, args=(s,), daemon=True)
            for s in (proc.stderr, proc.stdout)
            if s is not None
        ]
        for reader in readers:
            reader.start()

        open_streams = len(readers)
        started = time.monotonic()
        last_output = started
        killed_at: float | None = None
        timed_out = False

        while open_streams > 0:
            now = time.monotonic()
            stalled = now - last_output > stall_timeout
            overran = now - started > total_timeout

            if killed_at is None and (cancel.is_set() or stalled or overran):
                timed_out = not cancel.is_set()
                proc.terminate()
                killed_at = now
            if killed_at is not None and now - killed_at > _KILL_GRACE:
                proc.kill()
                killed_at = now  # keep waiting for the pipes to close

            try:
                item = chunks.get(timeout=0.1)
            except queue.Empty:
                continue

            if item is None:
                open_streams -= 1
                continue

            last_output = time.monotonic()
            text = item.decode("utf-8", errors="replace")
            transcript.append(text)
            for event in parser.feed(text):
                emit(event)

        for event in parser.finish():
            emit(event)

        for reader in readers:
            reader.join(timeout=1.0)
        code = proc.wait()

        if timed_out:
            transcript.append(
                f"\n[the tool gave up after {time.monotonic() - started:.0f}s "
                "with no response from avrdude]\n"
            )

        return code, "".join(transcript), timed_out

    @staticmethod
    def _run_blocking(argv: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            argv,
            capture_output=True,
            text=True,
            errors="replace",
            creationflags=_NO_WINDOW,
            check=False,
        )
