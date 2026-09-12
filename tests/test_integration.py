"""End-to-end tests against a stand-in avrdude.

These drive the real code path an operator hits - ``FlashEngine`` spawning a
process, streaming its output through the parser, diagnosing failures - with
:mod:`fake_avrdude` in place of the real binary. That covers everything above
the serial wire, which is the part no amount of bench testing can substitute
for and the part most likely to contain a bug.

The scenario is chosen by port name; see :mod:`fake_avrdude`.
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from rprm_flasher.backends.avr.programmer import AvrdudeProgrammer  # noqa: E402
from rprm_flasher.core import registry  # noqa: E402
from rprm_flasher.core.diagnostics import support_report  # noqa: E402
from rprm_flasher.core.engine import FlashEngine  # noqa: E402
from rprm_flasher.core.events import Phase  # noqa: E402
from rprm_flasher.core.models import FlashJob, SerialPortInfo, Target  # noqa: E402
from rprm_flasher.core.preflight import run_preflight  # noqa: E402
from rprm_flasher.hardware import port_scanner  # noqa: E402
from rprm_flasher.sources.base import inspect  # noqa: E402

FAKE = Path(__file__).resolve().parent / "fake_avrdude.py"


@pytest.fixture
def fake_programmer(monkeypatch):
    """Swap the bundled avrdude for the simulator, everywhere."""
    programmer = AvrdudeProgrammer(
        executable=FAKE,
        config=ROOT / "src/rprm_flasher/backends/avr/tools/avrdude.conf",
        launch_prefix=[sys.executable],
    )
    monkeypatch.setitem(registry._CACHE, "avr", programmer)
    return programmer


@pytest.fixture
def firmware(tmp_path):
    records = []
    for offset in range(0, 2048, 16):
        body = bytes([16, (offset >> 8) & 0xFF, offset & 0xFF, 0]) + bytes(16)
        records.append(":" + (body + bytes([(-sum(body)) & 0xFF])).hex().upper())
    records.append(":00000001FF")
    path = tmp_path / "fw.hex"
    path.write_text("\n".join(records) + "\n", encoding="ascii")
    return inspect(path)


@pytest.fixture
def make_job(firmware):
    catalog = registry.load_catalog()

    def build(port: str, board_id: str = "mega2560", mode: str = "isp_uno", verify=True):
        board = catalog.get(board_id)
        target = Target(board=board, mode=board.modes[mode], port=port)
        return FlashJob(target=target, firmware=firmware, verify=verify)

    return build


def run(job, engine: FlashEngine | None = None):
    """Flash, collecting every event as well as the result."""
    events: list = []
    own = engine is None
    engine = engine or FlashEngine(max_workers=1)
    try:
        result = engine.run_blocking(job, lambda _id, e: events.append(e))
    finally:
        if own:
            engine.shutdown()
    return result, events


# -- the happy path --------------------------------------------------------


class TestSuccessfulFlash:
    def test_reports_success(self, fake_programmer, make_job):
        result, _ = run(make_job("COM_OK"))
        assert result.ok, result.log
        assert result.verified
        assert result.bytes_written == 2048
        assert result.title == "Flash complete"
        assert result.exit_code == 0

    def test_detail_is_a_sentence_not_a_dump(self, fake_programmer, make_job):
        result, _ = run(make_job("COM_OK"))
        assert "verified" in result.detail
        assert "unplug" in result.detail
        assert "avrdude" not in result.detail.lower()

    def test_progress_climbs_to_a_hundred_without_going_back(
        self, fake_programmer, make_job
    ):
        _, events = run(make_job("COM_OK"))
        overalls = [e.overall for e in events]
        assert overalls == sorted(overalls), overalls
        assert overalls[-1] == 100.0

    def test_both_phases_are_seen(self, fake_programmer, make_job):
        _, events = run(make_job("COM_OK"))
        phases = {e.phase for e in events}
        assert Phase.WRITING in phases
        assert Phase.VERIFYING in phases
        assert Phase.DONE in phases

    def test_log_opens_with_the_command(self, fake_programmer, make_job):
        result, _ = run(make_job("COM_OK"))
        assert result.log.startswith("$ ")
        assert "-c stk500v1" in result.log
        assert "\n\n" in result.log[:600]  # command is separated from output

    def test_bootloader_mode_also_works(self, fake_programmer, make_job):
        result, _ = run(make_job("COM_OK", mode="usb_bootloader"))
        assert result.ok, result.log

    def test_verify_disabled_still_succeeds(self, fake_programmer, make_job):
        result, _ = run(make_job("COM_OK", verify=False))
        assert result.ok
        assert not result.verified  # avrdude was told not to check


# -- every failure mode ----------------------------------------------------


class TestFailureModes:
    def test_isp_not_wired_up(self, fake_programmer, make_job):
        result, _ = run(make_job("COM_NOSYNC"))
        assert not result.ok
        assert "programmer" in result.title.lower()
        assert "capacitor" in result.detail.lower()

    def test_wrong_chip(self, fake_programmer, make_job):
        result, _ = run(make_job("COM_WRONGCHIP"))
        assert not result.ok
        assert "not the board you selected" in result.title
        assert "0x1e950f" in result.detail

    def test_verify_failure_is_not_reported_as_success(
        self, fake_programmer, make_job
    ):
        # The most dangerous possible bug: telling someone a bad flash worked.
        result, _ = run(make_job("COM_VERIFYFAIL"))
        assert not result.ok
        assert "read back wrong" in result.title
        assert "0x0200" in result.detail

    def test_port_held_by_another_program(self, fake_programmer, make_job):
        result, _ = run(make_job("COM_BUSY"))
        assert not result.ok
        assert "in use" in result.title

    def test_port_gone(self, fake_programmer, make_job):
        result, _ = run(make_job("COM_MISSING"))
        assert not result.ok
        assert "COM_MISSING" in result.title

    def test_unknown_error_still_gives_the_real_message(
        self, fake_programmer, make_job
    ):
        result, _ = run(make_job("COM_GARBAGE"))
        assert not result.ok
        assert "flux capacitor" in result.detail

    def test_every_failure_has_both_a_cause_and_a_fix(
        self, fake_programmer, make_job
    ):
        for port in ("COM_NOSYNC", "COM_WRONGCHIP", "COM_VERIFYFAIL",
                     "COM_BUSY", "COM_MISSING", "COM_GARBAGE"):
            result, _ = run(make_job(port))
            assert result.title, port
            assert result.detail, port
            assert result.log, port

    def test_failures_never_claim_bytes_were_verified(
        self, fake_programmer, make_job
    ):
        for port in ("COM_NOSYNC", "COM_WRONGCHIP", "COM_VERIFYFAIL", "COM_BUSY"):
            result, _ = run(make_job(port))
            assert not result.verified, port


# -- cancelling and hanging ------------------------------------------------


class TestInterruption:
    def test_cancel_stops_a_running_flash(self, fake_programmer, make_job):
        engine = FlashEngine(max_workers=1)
        try:
            job = make_job("COM_SLOW")
            running = engine.submit(job, lambda _id, _e: None)
            time.sleep(1.5)
            assert engine.cancel(job.job_id)
            result = running.future.result(timeout=20)
        finally:
            engine.shutdown()

        assert result.cancelled
        assert not result.ok
        assert "again" in result.detail  # tells them the board is half-written

    def test_a_silent_port_is_given_up_on(self, fake_programmer, make_job):
        # The Bluetooth failure mode: opens fine, then says nothing forever.
        job = make_job("COM_STALL")
        parser_started = time.monotonic()
        code, log, timed_out = fake_programmer._stream(
            fake_programmer.build_flash_argv(job),
            __import__(
                "rprm_flasher.backends.avr.parser", fromlist=["AvrdudeParser"]
            ).AvrdudeParser(),
            lambda _e: None,
            threading.Event(),
            stall_timeout=2.0,
            total_timeout=20.0,
        )
        elapsed = time.monotonic() - parser_started
        assert timed_out
        assert elapsed < 15, f"watchdog took {elapsed:.1f}s"
        assert "gave up" in log

    def test_nothing_is_left_running_afterwards(self, fake_programmer, make_job):
        before = threading.active_count()
        run(make_job("COM_OK"))
        time.sleep(0.5)
        assert threading.active_count() <= before + 1


# -- pre-flight ------------------------------------------------------------


@pytest.fixture
def fake_ports(monkeypatch):
    """Pretend the simulator's scenario ports are real serial ports."""
    def fake_find(device: str):
        if device.upper().startswith("COM_BT"):
            return SerialPortInfo(device, "Standard Serial over Bluetooth link")
        if device.upper().startswith("COM_"):
            return SerialPortInfo(device, "Arduino Uno", "Arduino LLC", 0x2341, 0x0043)
        return None

    monkeypatch.setattr(port_scanner, "find", fake_find)


class TestPreflight:
    def test_passes_when_everything_is_right(
        self, fake_programmer, fake_ports, make_job
    ):
        report = run_preflight(make_job("COM_OK"))
        assert report.ok, report.as_text()

    def test_refuses_to_write_to_the_wrong_chip(
        self, fake_programmer, fake_ports, make_job
    ):
        report = run_preflight(make_job("COM_WRONGCHIP"))
        assert not report.ok
        blocker = report.blockers[0]
        assert blocker.name == "Chip identity"
        # Names the board they actually connected, not a hex signature.
        assert "UNO" in blocker.fix or "Nano" in blocker.fix

    def test_refuses_a_bluetooth_port(self, fake_programmer, fake_ports, make_job):
        report = run_preflight(make_job("COM_BT1"))
        assert not report.ok
        assert any("Bluetooth" in c.detail for c in report.blockers)

    def test_refuses_a_missing_port(self, fake_programmer, fake_ports, make_job):
        report = run_preflight(make_job("NOPE1"))
        assert not report.ok
        assert any(c.name == "Serial port" for c in report.blockers)

    def test_refuses_firmware_that_does_not_fit(
        self, fake_programmer, fake_ports, make_job, tmp_path
    ):
        job = make_job("COM_OK", board_id="atmega168")  # 16 KB part
        big = tmp_path / "big.bin"
        big.write_bytes(b"\xff" * 20000)
        job = FlashJob(target=job.target, firmware=inspect(big))
        report = run_preflight(job, check_signature=False)
        assert not report.ok
        assert any(c.name == "Firmware size" for c in report.blockers)

    def test_reports_when_a_board_does_not_answer(
        self, fake_programmer, fake_ports, make_job
    ):
        report = run_preflight(make_job("COM_NOSYNC"))
        assert not report.ok
        assert any(c.name == "Chip identity" for c in report.blockers)

    def test_skipped_in_bootloader_mode(self, fake_programmer, fake_ports, make_job):
        # The bootloader cannot be asked for a signature without engaging it.
        report = run_preflight(make_job("COM_OK", mode="usb_bootloader"))
        assert report.ok
        identity = [c for c in report.checks if c.name == "Chip identity"][0]
        assert "not checked" in identity.detail

    def test_text_output_marks_blockers(self, fake_programmer, fake_ports, make_job):
        text = run_preflight(make_job("COM_WRONGCHIP")).as_text()
        assert "[STOP]" in text
        assert "[OK  ]" in text


# -- detection -------------------------------------------------------------


class TestDetect:
    def test_reads_the_signature(self, fake_programmer, make_job):
        target = make_job("COM_OK").target
        result = fake_programmer.detect(target)
        assert result.ok
        assert result.signature == "0x1e9801"
        assert result.chip == "m2560"

    def test_reports_a_different_chip_rather_than_failing(
        self, fake_programmer, make_job
    ):
        target = make_job("COM_WRONGCHIP").target
        result = fake_programmer.detect(target)
        assert result.ok
        assert result.signature == "0x1e950f"

    def test_detect_writes_nothing(self, fake_programmer, make_job):
        argv = fake_programmer.build_detect_argv(make_job("COM_OK").target)
        assert "-n" in argv and "-U" not in argv


# -- support report --------------------------------------------------------


class TestSupportReport:
    def test_carries_everything_needed_to_diagnose(
        self, fake_programmer, make_job
    ):
        job = make_job("COM_NOSYNC")
        result, _ = run(job)
        text = support_report(job=job, result=result)

        for expected in (
            "Raphe Board Flasher",
            "Arduino Mega 2560",
            "atmega2560",
            "UNO as ISP programmer",
            "COM_NOSYNC",
            job.firmware.crc32,
            "Command:",
            "-c stk500v1",
            "FAILED",
            "not in sync",
        ):
            assert expected in text, f"missing {expected!r} from the report"

    def test_works_with_nothing_to_report(self, fake_programmer):
        text = support_report()
        assert "Raphe Board Flasher" in text
        assert "Serial ports" in text

    def test_success_reports_are_also_complete(self, fake_programmer, make_job):
        job = make_job("COM_OK")
        result, _ = run(job)
        text = support_report(job=job, result=result)
        assert "SUCCESS" in text
        assert "bytes of flash verified" in text
