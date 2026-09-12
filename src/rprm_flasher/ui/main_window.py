"""The application window.

Layout follows UI_SPEC.md: a 64px header, three step cards, a collapsible log,
and a 32px status bar. The window holds no flashing logic - it reads the cards,
builds a job, hands it to the controller, and renders what comes back.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from .. import __author__, __version__
from ..core.diagnostics import SelfTestResult, support_report
from ..core.events import Phase, ProgressEvent
from ..core.models import DetectResult, FlashJob, JobResult, Target
from ..core.preflight import PreflightReport
from ..core.registry import load_catalog
from ..sources.local import LocalLibrarySource
from ..config.settings import Settings
from .cards import ActionCard, FirmwareCard, TargetCard
from .controller import FlashController
from .dialogs import AboutDialog, ReportDialog, SettingsDialog, WiringDialog
from .theme import DARK, LIGHT, Palette, stylesheet

#: Where the firmware library and saved reports live: beside the executable, so
#: a portable copy carries them and nothing is hidden in AppData.
def app_dir() -> Path:
    import sys

    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path.cwd()


PALETTES = {"dark": DARK, "light": LIGHT}


class MainWindow(QMainWindow):
    def __init__(self, settings: Settings | None = None) -> None:
        super().__init__()
        self.settings = settings or Settings.load()
        self.palette_ = PALETTES.get(self.settings.theme, DARK)
        self.catalog = load_catalog()
        self.controller = FlashController(self)
        self._last_result: JobResult | None = None
        self._last_job: FlashJob | None = None
        self._last_preflight: PreflightReport | None = None

        self.setWindowTitle("Raphe Board Flasher")
        self.resize(980, 760)
        self.setMinimumSize(880, 620)

        self._build()
        self._connect()
        self._apply_settings()
        self._sync_ready()

        # Boards get plugged in after the window opens, so keep looking.
        self._port_timer = QTimer(self)
        self._port_timer.timeout.connect(self._rescan_ports)
        self._port_timer.start(2500)

    # -- construction ------------------------------------------------------

    def _build(self) -> None:
        root = QWidget()
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        root_layout.addWidget(self._build_header())

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(24, 20, 24, 20)
        body_layout.setSpacing(14)

        self.firmware_card = FirmwareCard(LocalLibrarySource(self.settings.firmware_path()))
        self.target_card = TargetCard(self.catalog)
        self.action_card = ActionCard()

        body_layout.addWidget(self.firmware_card)
        body_layout.addWidget(self.target_card)
        body_layout.addWidget(self.action_card)
        body_layout.addLayout(self._build_log())
        body_layout.addStretch(1)

        scroll.setWidget(body)
        root_layout.addWidget(scroll, 1)
        root_layout.addWidget(self._build_status_bar())

        self.setCentralWidget(root)

    def _build_header(self) -> QWidget:
        header = QFrame()
        header.setObjectName("Header")
        header.setFixedHeight(64)

        layout = QHBoxLayout(header)
        layout.setContentsMargins(24, 0, 24, 0)
        layout.setSpacing(12)

        # QWidget's base rule paints the window background on every child, which
        # would put a dark rectangle over the header. Labels that sit on the
        # header therefore clear it explicitly.
        mark = QLabel()
        mark.setStyleSheet("background: transparent;")
        mark.setFixedSize(32, 32)
        logo = Path(__file__).parent / "assets" / "logo.png"
        if logo.exists():
            from PySide6.QtGui import QPixmap

            mark.setPixmap(
                QPixmap(str(logo)).scaled(
                    32, 32,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        layout.addWidget(mark)

        wordmark = QLabel("RAPHE BOARD FLASHER")
        wordmark.setObjectName("Wordmark")
        layout.addWidget(wordmark)

        version = QLabel(f"v{__version__}")
        version.setObjectName("VersionPill")
        version.setFixedHeight(22)   # otherwise the pill stretches the header
        layout.addWidget(version, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addStretch(1)

        self.selftest_button = QPushButton("Self-test")
        self.selftest_button.setObjectName("Ghost")
        self.selftest_button.setToolTip(
            "Check the tool and the connection. Writes nothing to the board."
        )
        self.selftest_button.setCursor(Qt.CursorShape.PointingHandCursor)
        layout.addWidget(self.selftest_button)

        # A word again, not a glyph: Windows renders U+2699 through its emoji
        # font in a fixed purple that ignores the stylesheet.
        self.settings_button = QPushButton("Settings")
        self.settings_button.setObjectName("Ghost")
        self.settings_button.setToolTip("Settings")
        self.settings_button.setCursor(Qt.CursorShape.PointingHandCursor)
        layout.addWidget(self.settings_button)

        self.about_button = QPushButton("?")
        self.about_button.setObjectName("Icon")
        self.about_button.setToolTip("About")
        self.about_button.setCursor(Qt.CursorShape.PointingHandCursor)
        layout.addWidget(self.about_button)

        return header

    def _build_log(self) -> QVBoxLayout:
        column = QVBoxLayout()
        column.setSpacing(10)

        self.log_toggle = QPushButton("▸  Show details")
        self.log_toggle.setObjectName("Link")
        self.log_toggle.setCursor(Qt.CursorShape.PointingHandCursor)

        self.save_log_button = QPushButton("Save report")
        self.save_log_button.setObjectName("Ghost")
        self.save_log_button.setEnabled(False)
        self.save_log_button.setToolTip(
            "Write one file with everything needed to diagnose this run."
        )
        self.save_log_button.setCursor(Qt.CursorShape.PointingHandCursor)

        row = QHBoxLayout()
        row.addWidget(self.log_toggle)
        row.addStretch(1)
        row.addWidget(self.save_log_button)

        self.log_view = QPlainTextEdit()
        self.log_view.setObjectName("Log")
        self.log_view.setReadOnly(True)
        self.log_view.setMinimumHeight(200)
        self.log_view.hide()

        column.addLayout(row)
        column.addWidget(self.log_view)
        return column

    def _build_status_bar(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("StatusBar")
        bar.setFixedHeight(32)

        layout = QHBoxLayout(bar)
        layout.setContentsMargins(24, 0, 24, 0)
        layout.setSpacing(8)

        credit = QLabel(__author__.replace("|", "·"))
        credit.setObjectName("Credit")
        layout.addWidget(credit)
        layout.addStretch(1)

        self.status_dot = QLabel("●")
        self.status_text = QLabel("Ready")
        self.status_text.setObjectName("StatusText")
        layout.addWidget(self.status_dot)
        layout.addWidget(self.status_text)
        self._set_status("Ready", self.palette_.faint)

        return bar

    def _connect(self) -> None:
        self.firmware_card.changed.connect(self._sync_ready)
        self.target_card.changed.connect(self._sync_ready)
        self.target_card.detectRequested.connect(self._detect)
        self.target_card.wiringRequested.connect(self._show_wiring)

        self.action_card.flashRequested.connect(self._flash)
        self.action_card.cancelRequested.connect(self.controller.cancel)
        self.action_card.showLogRequested.connect(lambda: self._set_log_visible(True))

        self.log_toggle.clicked.connect(
            lambda: self._set_log_visible(not self.log_view.isVisible())
        )
        self.save_log_button.clicked.connect(self._save_report)
        self.selftest_button.clicked.connect(self._self_test)
        self.about_button.clicked.connect(lambda: AboutDialog(self).exec())
        self.settings_button.clicked.connect(self._open_settings)

        self.controller.progress.connect(self._on_progress)
        self.controller.finished.connect(self._on_finished)
        self.controller.preflightFinished.connect(self._on_preflight)
        self.controller.detectFinished.connect(self._on_detect)
        self.controller.selfTestFinished.connect(self._on_self_test)
        self.controller.failed.connect(self._on_failed)
        self.controller.busyChanged.connect(self._on_busy)

    # -- state -------------------------------------------------------------

    def _sync_ready(self) -> None:
        self.firmware_card.refresh_meta(self.target_card.board)
        problem = self.firmware_card.problem or self.target_card.problem

        firmware = self.firmware_card.firmware
        board = self.target_card.board
        if not problem and firmware and not firmware.fits(board):
            problem = (
                f"This firmware needs {firmware.program_bytes:,} bytes; "
                f"{board.name} has {board.flash_bytes:,}"
            )

        self.action_card.set_ready(not problem, problem)

    def _rescan_ports(self) -> None:
        if not self.controller.busy:
            self.target_card.refresh_ports()

    def _set_status(self, text: str, colour: str) -> None:
        self.status_text.setText(text)
        self.status_dot.setStyleSheet(f"color: {colour}; font-size: 10px;")

    def _set_log_visible(self, visible: bool) -> None:
        self.log_view.setVisible(visible)
        self.log_toggle.setText(
            "▾  Hide details" if visible else "▸  Show details"
        )

    def _current_job(self) -> FlashJob | None:
        firmware = self.firmware_card.firmware
        mode = self.target_card.mode
        if firmware is None or mode is None or not self.target_card.port:
            return None
        target = Target(
            board=self.target_card.board, mode=mode, port=self.target_card.port
        )
        return FlashJob(
            target=target,
            firmware=firmware,
            verify=self.settings.verify_after_write,
        )

    # -- actions -----------------------------------------------------------

    def _flash(self) -> None:
        job = self._current_job()
        if job is None:
            return
        self._last_job = job
        self._last_result = None
        self._last_preflight = None
        self.log_view.setPlainText("")
        self.action_card.clear_result()
        self.action_card.set_running(True)
        self._set_status("Flashing…", self.palette_.accent)
        self._append_log("Checking the board before writing…")
        self.controller.start(job, check_signature=self.settings.check_signature)

    def _detect(self) -> None:
        mode = self.target_card.mode
        if mode is None or not self.target_card.port:
            return
        self.target_card.set_detect_result("Reading the chip…", True)
        self._set_status("Reading chip…", self.palette_.accent)
        self.controller.detect(
            Target(board=self.target_card.board, mode=mode, port=self.target_card.port)
        )

    def _self_test(self) -> None:
        mode = self.target_card.mode
        use_port = bool(
            self.target_card.port and mode and mode.port_belongs_to == "programmer"
        )
        self._set_status("Self-test…", self.palette_.accent)
        self.controller.run_self_test(
            port=self.target_card.port if use_port else None,
            board_id=self.target_card.board.id,
            mode_id=mode.id if mode else None,
        )

    def _apply_settings(self) -> None:
        """Push settings into the widgets that care about them."""
        index = self.target_card.board_box.findData(self.settings.default_board)
        if index >= 0:
            self.target_card.board_box.setCurrentIndex(index)
        if self.settings.default_mode:
            index = self.target_card.mode_box.findData(self.settings.default_mode)
            if index >= 0:
                self.target_card.mode_box.setCurrentIndex(index)
        self.firmware_card.library.directory = self.settings.firmware_path()
        self.firmware_card._load_library()

    def _open_settings(self) -> None:
        dialog = SettingsDialog(self.settings, self.catalog, self)
        if dialog.exec() != SettingsDialog.DialogCode.Accepted:
            return
        dialog.apply_to_settings()
        self._apply_theme()
        self._apply_settings()
        self._sync_ready()

    def _apply_theme(self) -> None:
        """Re-skin the running application without restarting it."""
        from PySide6.QtWidgets import QApplication

        self.palette_ = PALETTES.get(self.settings.theme, DARK)
        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(stylesheet(self.palette_))
        # The status dot is coloured inline, so it has to be repainted by hand.
        current = self.status_text.text()
        colours = {
            "Done": self.palette_.success,
            "Failed": self.palette_.danger,
            "Cancelled": self.palette_.warning,
        }
        self._set_status(current, colours.get(current, self.palette_.faint))

    def _show_wiring(self) -> None:
        mode = self.target_card.mode
        if mode:
            WiringDialog(self.target_card.board, mode, self).exec()

    def _save_report(self) -> None:
        default = app_dir() / "logs" / (
            datetime.now().strftime("%Y%m%d-%H%M%S") + "-report.txt"
        )
        default.parent.mkdir(parents=True, exist_ok=True)
        path, _ = QFileDialog.getSaveFileName(
            self, "Save report", str(default), "Text files (*.txt)"
        )
        if not path:
            return
        Path(path).write_text(self._report_text(), encoding="utf-8")
        QMessageBox.information(
            self,
            "Report saved",
            f"Saved to:\n{path}\n\nSend this file to whoever gave you the tool.",
        )

    def _report_text(self) -> str:
        return support_report(
            job=self._last_job,
            result=self._last_result,
            preflight=self._last_preflight,
            extra_log=self.log_view.toPlainText(),
        )

    # -- controller callbacks ----------------------------------------------

    def _on_busy(self, busy: bool) -> None:
        self.firmware_card.setEnabled(not busy)
        self.target_card.setEnabled(not busy)
        self.selftest_button.setEnabled(not busy)

    def _on_progress(self, event: ProgressEvent) -> None:
        self.action_card.set_progress(event.overall, event.message)
        if event.raw:
            self._append_log(event.raw)
        elif event.message and event.phase in (Phase.STARTING, Phase.CONNECTING):
            self._append_log(event.message)

    def _on_preflight(self, report: PreflightReport, _job: FlashJob) -> None:
        self._last_preflight = report
        self._append_log(report.as_text())
        if report.ok:
            self._append_log("\nChecks passed. Writing…\n")

    def _on_finished(self, result: JobResult) -> None:
        self._last_result = result
        self.action_card.set_running(False)
        if result.log:
            self._append_log("\n" + result.log.strip())
        self.action_card.show_result(
            result.ok, result.title, result.detail, has_log=True
        )
        self.save_log_button.setEnabled(True)
        if result.ok:
            self._set_status("Done", self.palette_.success)
        elif result.cancelled:
            self._set_status("Cancelled", self.palette_.warning)
        else:
            self._set_status("Failed", self.palette_.danger)
            self._set_log_visible(True)
        self._sync_ready()

    def _on_detect(self, result: DetectResult) -> None:
        if not result.ok:
            self.target_card.set_detect_result(
                f"{result.title}. {result.detail}", good=False
            )
            self._set_status("Failed", self.palette_.danger)
            self._append_log(result.log)
            self.save_log_button.setEnabled(True)
            return

        matches = self.catalog.by_signature(result.signature or "")
        selected = self.target_card.board
        if any(b.id == selected.id for b in matches):
            self.target_card.set_detect_result(
                f"✓ Detected {result.chip or result.signature} — "
                f"matches {selected.name}",
                good=True,
            )
            self._set_status("Ready", self.palette_.faint)
            return

        name = ", ".join(sorted({b.name for b in matches})) or "an unknown chip"
        self.target_card.set_detect_result(
            f"✕ Detected {name} ({result.signature}), not {selected.name}. "
            "Pick the right board.",
            good=False,
        )
        self._set_status("Ready", self.palette_.faint)

    def _on_self_test(self, result: SelfTestResult) -> None:
        self._set_status("Ready", self.palette_.faint)
        body = support_report(self_test_result=result)
        self._append_log(result.report.as_text())
        self.save_log_button.setEnabled(True)
        ReportDialog(
            "Self-test " + ("passed" if result.ok else "found a problem"), body, self
        ).exec()

    def _on_failed(self, title: str, fix: str) -> None:
        self.action_card.set_running(False)
        self.action_card.show_result(False, title, fix, has_log=True)
        self._set_status("Failed", self.palette_.danger)
        self.save_log_button.setEnabled(True)

    def _append_log(self, text: str) -> None:
        if not text:
            return
        self.log_view.appendPlainText(text.rstrip())
        bar = self.log_view.verticalScrollBar()
        bar.setValue(bar.maximum())

    # -- lifecycle ---------------------------------------------------------

    def closeEvent(self, event) -> None:
        if self.controller.busy:
            answer = QMessageBox.question(
                self,
                "Flashing in progress",
                "A board is being written to. Closing now may leave it with "
                "half a firmware.\n\nClose anyway?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
        self._port_timer.stop()
        self.controller.shutdown()
        event.accept()


def load_bundled_fonts() -> None:
    """Register any fonts shipped in assets/ so the PC need not have them."""
    folder = Path(__file__).parent / "assets" / "fonts"
    if folder.is_dir():
        for font in folder.glob("*.ttf"):
            QFontDatabase.addApplicationFont(str(font))
