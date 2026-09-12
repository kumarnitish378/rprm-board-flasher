"""The window driven end to end against the simulated avrdude.

These prove what unit tests cannot: that results produced on a worker thread
actually reach the Qt main thread and get rendered. Everything runs on the
offscreen platform, so the suite still needs no display and no hardware.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from rprm_flasher.backends.avr.programmer import AvrdudeProgrammer  # noqa: E402
from rprm_flasher.core import registry  # noqa: E402
from rprm_flasher.core.models import SerialPortInfo  # noqa: E402
from rprm_flasher.hardware import port_scanner  # noqa: E402
from rprm_flasher.ui.main_window import MainWindow  # noqa: E402
from rprm_flasher.ui.theme import DARK, LIGHT, stylesheet  # noqa: E402

FAKE = Path(__file__).resolve().parent / "fake_avrdude.py"


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    app.setStyleSheet(stylesheet(DARK))
    yield app


@pytest.fixture
def window(qapp, monkeypatch):
    monkeypatch.setitem(
        registry._CACHE,
        "avr",
        AvrdudeProgrammer(
            executable=FAKE,
            config=ROOT / "src/rprm_flasher/backends/avr/tools/avrdude.conf",
            launch_prefix=[sys.executable],
        ),
    )
    # Pretend the simulator's scenario ports are real, so pre-flight gets past
    # its "does this port exist" check.
    monkeypatch.setattr(
        port_scanner,
        "find",
        lambda device: (
            SerialPortInfo(device, "Arduino Uno", "Arduino LLC", 0x2341, 0x43)
            if device.upper().startswith("COM_")
            else None
        ),
    )

    win = MainWindow()
    win._port_timer.stop()
    # Shown, so isVisible() reflects reality: a child of a hidden window always
    # reports False however its own flag is set.
    win.show()
    qapp.processEvents()
    yield win
    win.controller.shutdown()
    win.close()


@pytest.fixture
def firmware_file(tmp_path):
    records = []
    for offset in range(0, 1024, 16):
        body = bytes([16, (offset >> 8) & 0xFF, offset & 0xFF, 0]) + bytes(16)
        records.append(":" + (body + bytes([(-sum(body)) & 0xFF])).hex().upper())
    records.append(":00000001FF")
    path = tmp_path / "fw.hex"
    path.write_text("\n".join(records) + "\n", encoding="ascii")
    return path


def use_port(window, port: str) -> None:
    window.target_card.port_box.clear()
    window.target_card.port_box.addItem(port, port)


def pump(qapp, predicate, timeout: float = 40.0) -> bool:
    """Spin the Qt event loop until ``predicate`` holds."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        qapp.processEvents()
        if predicate():
            return True
        time.sleep(0.02)
    return False


class TestInitialState:
    def test_opens_with_the_button_disabled_and_says_why(self, window):
        assert not window.action_card.button.isEnabled()
        assert "firmware" in window.action_card.hint.text().lower()

    def test_all_boards_are_offered(self, window):
        assert window.target_card.board_box.count() == len(window.catalog)

    def test_the_default_mode_is_flagged_as_erasing_the_bootloader(self, window):
        assert window.target_card.mode.erases_bootloader

    def test_log_starts_collapsed_with_nothing_to_save(self, window):
        assert not window.log_view.isVisible()
        assert not window.save_log_button.isEnabled()


class TestReadiness:
    def test_button_enables_only_when_everything_is_set(self, window, firmware_file):
        window.firmware_card.load_path(str(firmware_file))
        assert not window.action_card.button.isEnabled()  # no port yet

        use_port(window, "COM_OK")
        window.target_card.acknowledge.setChecked(True)
        window._sync_ready()
        assert window.action_card.button.isEnabled()

    def test_unacknowledged_isp_warning_blocks(self, window, firmware_file):
        window.firmware_card.load_path(str(firmware_file))
        use_port(window, "COM_OK")
        window.target_card.acknowledge.setChecked(False)
        window._sync_ready()
        assert not window.action_card.button.isEnabled()
        assert "understand" in window.action_card.hint.text().lower()

    def test_oversized_firmware_is_refused_with_a_reason(self, window, tmp_path):
        big = tmp_path / "big.bin"
        big.write_bytes(b"\xff" * 40000)
        window.target_card.board_box.setCurrentIndex(
            window.target_card.board_box.findData("uno")
        )
        window.firmware_card.load_path(str(big))
        use_port(window, "COM_OK")
        window.target_card.acknowledge.setChecked(True)
        window._sync_ready()
        assert not window.action_card.button.isEnabled()
        assert "needs" in window.action_card.hint.text()

    def test_a_damaged_file_is_rejected_in_the_card(self, window, tmp_path):
        bad = tmp_path / "bad.hex"
        bad.write_text(":10000000FFFF\n", encoding="ascii")
        window.firmware_card.load_path(str(bad))
        assert window.firmware_card.firmware is None
        assert window.firmware_card.error_label.isVisible()
        assert "damaged" in window.firmware_card.error_label.text()


class TestFlashRoundTrip:
    def _run(self, window, qapp, firmware_file, port):
        window.firmware_card.load_path(str(firmware_file))
        use_port(window, port)
        window.target_card.acknowledge.setChecked(True)
        window._sync_ready()
        window._flash()
        assert pump(qapp, lambda: window._last_result is not None), "never finished"
        return window._last_result

    def test_a_good_flash_reaches_the_window(self, window, qapp, firmware_file):
        result = self._run(window, qapp, firmware_file, "COM_OK")
        assert result.ok, result.log
        assert "complete" in window.action_card.result_title.text().lower()
        assert window.status_text.text() == "Done"
        assert window.save_log_button.isEnabled()

    def test_progress_was_rendered_not_just_the_result(
        self, window, qapp, firmware_file
    ):
        self._run(window, qapp, firmware_file, "COM_OK")
        assert window.action_card.bar.value() > 0

    def test_a_failure_shows_the_cause_and_opens_the_log(
        self, window, qapp, firmware_file
    ):
        result = self._run(window, qapp, firmware_file, "COM_NOSYNC")
        assert not result.ok
        assert "programmer" in window.action_card.result_title.text().lower()
        assert window.status_text.text() == "Failed"
        assert window.log_view.isVisible(), "the log should open itself on failure"
        assert window.log_view.toPlainText()

    def test_wrong_chip_is_blocked_before_any_write(self, window, qapp, firmware_file):
        result = self._run(window, qapp, firmware_file, "COM_WRONGCHIP")
        assert not result.ok
        assert result.bytes_written == 0
        assert "Chip identity" in window.log_view.toPlainText()

    def test_a_bad_verify_is_never_shown_as_success(
        self, window, qapp, firmware_file
    ):
        result = self._run(window, qapp, firmware_file, "COM_VERIFYFAIL")
        assert not result.ok
        assert "✓" not in window.action_card.result_title.text()

    def test_inputs_are_locked_while_running_and_freed_after(
        self, window, qapp, firmware_file
    ):
        window.firmware_card.load_path(str(firmware_file))
        use_port(window, "COM_SLOW")
        window.target_card.acknowledge.setChecked(True)
        window._sync_ready()
        window._flash()
        assert pump(qapp, lambda: window.controller.busy, timeout=15)
        assert not window.firmware_card.isEnabled()
        assert not window.target_card.isEnabled()
        window.controller.cancel()
        assert pump(qapp, lambda: window._last_result is not None)
        assert window.firmware_card.isEnabled()
        assert window.target_card.isEnabled()

    def test_the_report_is_complete_after_a_run(self, window, qapp, firmware_file):
        self._run(window, qapp, firmware_file, "COM_NOSYNC")
        report = window._report_text()
        assert "COM_NOSYNC" in report
        assert "Arduino Mega 2560" in report
        assert "Pre-flight checks" in report
        assert window.firmware_card.firmware.crc32 in report


class TestDetect:
    def test_a_match_is_reported_in_green(self, window, qapp):
        use_port(window, "COM_OK")
        window._detect()
        assert pump(qapp, lambda: "Detected" in window.target_card.port_note.text())
        assert window.target_card.port_note.objectName() == "MetaGood"

    def test_a_mismatch_names_the_board_actually_connected(self, window, qapp):
        use_port(window, "COM_WRONGCHIP")
        window._detect()
        assert pump(qapp, lambda: "not" in window.target_card.port_note.text())
        assert window.target_card.port_note.objectName() == "MetaBad"


class TestTheme:
    def test_both_palettes_produce_a_stylesheet(self):
        for palette in (DARK, LIGHT):
            css = stylesheet(palette)
            assert palette.accent in css
            assert "QPushButton#Primary" in css

    def test_no_colour_is_left_unset(self):
        for palette in (DARK, LIGHT):
            for name, value in vars(palette).items():
                assert value.startswith("#"), f"{name} is not a colour"
