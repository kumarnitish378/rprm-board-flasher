"""The three step cards: Firmware, Target, Flash.

Each card owns its own validity and reports it upward with a ``changed``
signal; the window is responsible only for combining them into the enabled
state of one button. Cards never touch the engine.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..core.errors import FlasherError
from ..core.models import BoardCatalog, BoardProfile, Firmware, UploadMode
from ..hardware import port_scanner
from ..sources.base import inspect as inspect_firmware
from ..sources.local import LocalLibrarySource

FIRMWARE_FILTER = "Firmware (*.hex *.bin);;Intel HEX (*.hex);;Binary (*.bin);;All files (*)"


def _label(text: str, name: str = "") -> QLabel:
    label = QLabel(text)
    if name:
        label.setObjectName(name)
    return label


class Card(QFrame):
    """A titled step panel."""

    def __init__(self, number: str, title: str) -> None:
        super().__init__()
        self.setObjectName("Card")

        self._body = QVBoxLayout(self)
        self._body.setContentsMargins(20, 16, 20, 18)
        self._body.setSpacing(12)

        head = QHBoxLayout()
        head.setSpacing(10)
        badge = _label(number, "StepBadge")
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        head.addWidget(badge)
        head.addWidget(_label(title.upper(), "StepLabel"))
        head.addStretch(1)
        self._head = head
        self._body.addLayout(head)

    def add(self, item) -> None:
        if isinstance(item, QWidget):
            self._body.addWidget(item)
        else:
            self._body.addLayout(item)

    def add_to_header(self, widget: QWidget) -> None:
        self._head.addWidget(widget)


# -- 1. Firmware -----------------------------------------------------------


class DropZone(QFrame):
    """Dashed target that accepts a dragged .hex or .bin."""

    fileDropped = Signal(str)
    browseRequested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("DropZone")
        self.setAcceptDrops(True)
        self.setMinimumHeight(88)

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(4)

        title = _label("Drag a .hex or .bin file here", "DropTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        separator = _label("or", "DropOr")
        separator.setAlignment(Qt.AlignmentFlag.AlignCenter)

        browse = QPushButton("Browse…")
        browse.setObjectName("Ghost")
        browse.setCursor(Qt.CursorShape.PointingHandCursor)
        browse.clicked.connect(self.browseRequested)
        browse.setFixedWidth(120)

        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(browse)
        row.addStretch(1)

        layout.addWidget(title)
        layout.addWidget(separator)
        layout.addLayout(row)

    def _is_firmware(self, event) -> bool:
        urls = event.mimeData().urls() if event.mimeData().hasUrls() else []
        return len(urls) == 1 and urls[0].toLocalFile().lower().endswith((".hex", ".bin"))

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if self._is_firmware(event):
            event.acceptProposedAction()
            self._set_dragging(True)

    def dragLeaveEvent(self, event) -> None:
        self._set_dragging(False)

    def dropEvent(self, event: QDropEvent) -> None:
        self._set_dragging(False)
        if self._is_firmware(event):
            event.acceptProposedAction()
            self.fileDropped.emit(event.mimeData().urls()[0].toLocalFile())

    def _set_dragging(self, value: bool) -> None:
        self.setProperty("dragging", "true" if value else "false")
        self.style().unpolish(self)
        self.style().polish(self)


class FirmwareCard(Card):
    changed = Signal()

    def __init__(self, library: LocalLibrarySource) -> None:
        super().__init__("1", "Firmware")
        self.library = library
        self.firmware: Firmware | None = None
        self._error = ""

        self._segmented = QFrame()
        self._segmented.setObjectName("Segmented")
        self._segmented.setFixedSize(260, 32)
        seg_layout = QHBoxLayout(self._segmented)
        seg_layout.setContentsMargins(3, 3, 3, 3)
        seg_layout.setSpacing(3)

        self.btn_library = QPushButton("From library")
        self.btn_file = QPushButton("From file")
        group = QButtonGroup(self)
        for index, button in enumerate((self.btn_library, self.btn_file)):
            button.setObjectName("Segment")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            group.addButton(button, index)
            seg_layout.addWidget(button)
        self.btn_file.setChecked(True)
        self.btn_library.toggled.connect(self._mode_changed)

        self.library_box = QComboBox()
        self.library_box.currentIndexChanged.connect(self._library_picked)
        self.library_box.hide()

        self.drop = DropZone()
        self.drop.fileDropped.connect(self.load_path)
        self.drop.browseRequested.connect(self.browse)

        self.chip = QFrame()
        self.chip.setObjectName("FileChip")
        self.chip.hide()
        chip_layout = QHBoxLayout(self.chip)
        chip_layout.setContentsMargins(14, 10, 12, 10)
        chip_layout.setSpacing(12)
        text_column = QVBoxLayout()
        text_column.setSpacing(2)
        self.chip_name = _label("", "FileName")
        self.chip_meta = _label("", "Meta")
        self.chip_meta.setWordWrap(True)
        text_column.addWidget(self.chip_name)
        text_column.addWidget(self.chip_meta)
        chip_layout.addLayout(text_column, 1)
        clear = QPushButton("✕")
        clear.setObjectName("Icon")
        clear.setToolTip("Choose a different file")
        clear.setCursor(Qt.CursorShape.PointingHandCursor)
        clear.clicked.connect(self.clear)
        chip_layout.addWidget(clear)

        self.error_label = _label("", "MetaBad")
        self.error_label.setWordWrap(True)
        self.error_label.hide()

        self.add(self._segmented)
        self.add(self.library_box)
        self.add(self.drop)
        self.add(self.chip)
        self.add(self.error_label)

        self._load_library()

    # -- state ------------------------------------------------------------

    @property
    def is_valid(self) -> bool:
        return self.firmware is not None

    @property
    def problem(self) -> str:
        if self._error:
            return self._error
        return "" if self.firmware else "Choose a firmware file to continue"

    def describe(self, board: BoardProfile | None) -> str:
        """The meta line under the file name, sized against the chosen board."""
        if self.firmware is None:
            return ""
        fw = self.firmware
        size = f"{fw.size_bytes / 1024:.0f} KB"
        parts = [size, f"CRC32 {fw.crc32}", fw.fmt.value.upper()]
        if board is not None:
            parts.append(
                f"{fw.usage_percent(board):.0f}% of {board.flash_bytes // 1024} KB flash"
            )
        return "  ·  ".join(parts)

    def refresh_meta(self, board: BoardProfile | None) -> None:
        self.chip_meta.setText(self.describe(board))

    # -- actions ----------------------------------------------------------

    def browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose firmware", str(Path.home()), FIRMWARE_FILTER
        )
        if path:
            self.load_path(path)

    def load_path(self, path: str) -> None:
        try:
            self.firmware = inspect_firmware(Path(path))
            self._error = ""
        except FlasherError as exc:
            self.firmware = None
            self._error = f"{exc.title}. {exc.fix}"
        self._sync()

    def clear(self) -> None:
        self.firmware = None
        self._error = ""
        self._sync()

    def _load_library(self) -> None:
        self.library_box.blockSignals(True)
        self.library_box.clear()
        entries = self.library.list() if self.library.exists() else []
        for item in entries:
            self.library_box.addItem(item.name, item.path)
        self.btn_library.setEnabled(bool(entries))
        self.btn_library.setToolTip(
            "" if entries else f"No firmware found in {self.library.directory}"
        )
        self.library_box.blockSignals(False)

    def _mode_changed(self, use_library: bool) -> None:
        self.library_box.setVisible(use_library)
        self.drop.setVisible(not use_library and self.firmware is None)
        self.clear()
        if use_library and self.library_box.count():
            self._library_picked(self.library_box.currentIndex())

    def _library_picked(self, index: int) -> None:
        path = self.library_box.itemData(index)
        if path:
            self.load_path(str(path))

    def _sync(self) -> None:
        has_file = self.firmware is not None
        using_library = self.btn_library.isChecked()
        self.chip.setVisible(has_file)
        self.drop.setVisible(not has_file and not using_library)
        if has_file:
            self.chip_name.setText(self.firmware.path.name)
            self.chip_meta.setText(self.describe(None))
        self.error_label.setVisible(bool(self._error))
        self.error_label.setText(self._error)
        self.changed.emit()


# -- 2. Target -------------------------------------------------------------


class TargetCard(Card):
    changed = Signal()
    detectRequested = Signal()
    wiringRequested = Signal()

    def __init__(self, catalog: BoardCatalog) -> None:
        super().__init__("2", "Target")
        self.catalog = catalog

        self.board_box = QComboBox()
        for board in catalog:
            self.board_box.addItem(board.name, board.id)
        self.board_box.currentIndexChanged.connect(self._board_changed)

        self.mode_box = QComboBox()
        self.mode_box.currentIndexChanged.connect(self._mode_changed)

        self.wiring_link = QPushButton("ⓘ  Show wiring")
        self.wiring_link.setObjectName("Link")
        self.wiring_link.setCursor(Qt.CursorShape.PointingHandCursor)
        self.wiring_link.clicked.connect(self.wiringRequested)

        left = QVBoxLayout()
        left.setSpacing(6)
        left.addWidget(_label("Board", "FieldLabel"))
        left.addWidget(self.board_box)

        right = QVBoxLayout()
        right.setSpacing(6)
        right.addWidget(_label("Upload method", "FieldLabel"))
        right.addWidget(self.mode_box)
        right.addWidget(self.wiring_link)

        columns = QHBoxLayout()
        columns.setSpacing(16)
        columns.addLayout(left, 1)
        columns.addLayout(right, 1)

        self.port_box = QComboBox()
        self.port_box.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self.port_box.currentIndexChanged.connect(lambda _i: self.changed.emit())

        # A word, not a glyph: the operator is not assumed to read icons.
        refresh = QPushButton("Refresh")
        refresh.setFixedWidth(88)
        refresh.setToolTip("Look for boards again")
        refresh.setCursor(Qt.CursorShape.PointingHandCursor)
        refresh.clicked.connect(self.refresh_ports)

        self.detect_button = QPushButton("Detect board")
        self.detect_button.setToolTip("Read the chip id. Writes nothing.")
        self.detect_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.detect_button.clicked.connect(self.detectRequested)

        port_row = QHBoxLayout()
        port_row.setSpacing(8)
        port_row.addWidget(self.port_box, 1)
        port_row.addWidget(refresh)
        port_row.addWidget(self.detect_button)

        self.port_note = _label("", "Meta")
        self.port_note.setWordWrap(True)

        port_column = QVBoxLayout()
        port_column.setSpacing(6)
        port_column.addWidget(_label("Port", "FieldLabel"))
        port_column.addLayout(port_row)
        port_column.addWidget(self.port_note)

        self.warning = QFrame()
        self.warning.setObjectName("Warn")
        warn_layout = QHBoxLayout(self.warning)
        warn_layout.setContentsMargins(14, 12, 14, 12)
        warn_layout.setSpacing(10)
        warn_layout.addWidget(_label("⚠", "WarnIcon"))
        warn_text = _label(
            "ISP flashing erases the bootloader. This board won't accept USB "
            "uploads until it is re-burned.",
            "WarnText",
        )
        warn_text.setWordWrap(True)
        warn_layout.addWidget(warn_text, 1)
        self.acknowledge = QCheckBox("I understand")
        self.acknowledge.toggled.connect(lambda _v: self.changed.emit())
        warn_layout.addWidget(self.acknowledge)

        self.add(columns)
        self.add(port_column)
        self.add(self.warning)

        self._board_changed(0)
        self.refresh_ports()

    # -- state ------------------------------------------------------------

    @property
    def board(self) -> BoardProfile:
        return self.catalog.get(self.board_box.currentData())

    @property
    def mode(self) -> UploadMode | None:
        mode_id = self.mode_box.currentData()
        return self.board.modes.get(mode_id) if mode_id else None

    @property
    def port(self) -> str:
        return self.port_box.currentData() or ""

    @property
    def is_valid(self) -> bool:
        if not self.port or self.mode is None:
            return False
        if self.mode.erases_bootloader and not self.acknowledge.isChecked():
            return False
        return True

    @property
    def problem(self) -> str:
        if not self.port:
            return "Connect a board and choose its port"
        if self.mode is None:
            return "Choose an upload method"
        if self.mode.erases_bootloader and not self.acknowledge.isChecked():
            return "Tick 'I understand' to confirm the bootloader will be erased"
        return ""

    # -- actions ----------------------------------------------------------

    def refresh_ports(self) -> None:
        previous = self.port
        self.port_box.blockSignals(True)
        self.port_box.clear()
        ports = port_scanner.list_ports()
        for info in ports:
            suffix = "  —  not a board" if port_scanner.is_bluetooth(info) else ""
            self.port_box.addItem(info.label + suffix, info.device)
        if not ports:
            self.port_box.addItem("No serial ports found", "")
        if previous:
            index = self.port_box.findData(previous)
            if index >= 0:
                self.port_box.setCurrentIndex(index)
        self.port_box.blockSignals(False)
        self._update_port_note()
        self.changed.emit()

    def set_detect_result(self, text: str, good: bool) -> None:
        self.port_note.setObjectName("MetaGood" if good else "MetaBad")
        self.port_note.setText(text)
        self._restyle(self.port_note)

    def _update_port_note(self) -> None:
        info = port_scanner.find(self.port) if self.port else None
        if info is None:
            self.port_note.setObjectName("Meta")
            self.port_note.setText("")
        elif port_scanner.is_bluetooth(info):
            self.port_note.setObjectName("MetaBad")
            self.port_note.setText(
                "This is a Bluetooth port, not a board. Windows creates these "
                "automatically."
            )
        else:
            self.port_note.setObjectName("Meta")
            self.port_note.setText("")
        self._restyle(self.port_note)

    def _board_changed(self, _index: int) -> None:
        board = self.board
        self.mode_box.blockSignals(True)
        self.mode_box.clear()
        for mode in board.modes.values():
            self.mode_box.addItem(mode.label, mode.id)
        self.mode_box.blockSignals(False)
        self._mode_changed(0)

    def _mode_changed(self, _index: int) -> None:
        mode = self.mode
        erases = bool(mode and mode.erases_bootloader)
        self.warning.setVisible(erases)
        if not erases:
            self.acknowledge.setChecked(False)
        self.wiring_link.setVisible(bool(mode and self.board.wiring.get(mode.id)))
        self.detect_button.setEnabled(bool(mode and mode.port_belongs_to == "programmer"))
        self.detect_button.setToolTip(
            "Read the chip id. Writes nothing."
            if self.detect_button.isEnabled()
            else "Only available in ISP mode - a bootloader cannot be asked "
            "for a chip id without engaging it."
        )
        self.changed.emit()

    @staticmethod
    def _restyle(widget: QWidget) -> None:
        widget.style().unpolish(widget)
        widget.style().polish(widget)


# -- 3. Flash --------------------------------------------------------------


class ActionCard(Card):
    flashRequested = Signal()
    cancelRequested = Signal()
    showLogRequested = Signal()

    def __init__(self) -> None:
        super().__init__("3", "Flash")

        self.button = QPushButton("FLASH BOARD")
        self.button.setObjectName("Primary")
        self.button.setFixedWidth(280)
        self.button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.button.clicked.connect(self._clicked)

        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(self.button)
        row.addStretch(1)

        self.hint = _label("", "Hint")
        self.hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.hint.setWordWrap(True)

        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setTextVisible(False)
        self.bar.hide()

        self.phase = _label("", "Meta")
        self.percent = _label("", "Meta")
        self.percent.setAlignment(Qt.AlignmentFlag.AlignRight)
        progress_row = QHBoxLayout()
        progress_row.addWidget(self.phase, 1)
        progress_row.addWidget(self.percent)
        self._progress_row = progress_row
        self.phase.hide()
        self.percent.hide()

        self.result = QFrame()
        self.result.setObjectName("ResultOk")
        self.result.hide()
        result_layout = QHBoxLayout(self.result)
        result_layout.setContentsMargins(14, 12, 14, 12)
        result_layout.setSpacing(12)
        text_column = QVBoxLayout()
        text_column.setSpacing(2)
        self.result_title = _label("", "ResultTitle")
        self.result_detail = _label("", "ResultDetail")
        self.result_detail.setWordWrap(True)
        text_column.addWidget(self.result_title)
        text_column.addWidget(self.result_detail)
        result_layout.addLayout(text_column, 1)
        self.view_log = QPushButton("View log →")
        self.view_log.setObjectName("Link")
        self.view_log.setCursor(Qt.CursorShape.PointingHandCursor)
        self.view_log.clicked.connect(self.showLogRequested)
        result_layout.addWidget(self.view_log)

        self.add(row)
        self.add(self.hint)
        self.add(self.bar)
        self.add(progress_row)
        self.add(self.result)

        self._running = False

    # -- state ------------------------------------------------------------

    def set_ready(self, ready: bool, reason: str) -> None:
        if self._running:
            return
        self.button.setEnabled(ready)
        self.hint.setText("" if ready else reason)
        self.hint.setVisible(not ready)

    def set_running(self, running: bool) -> None:
        self._running = running
        self.button.setObjectName("Danger" if running else "Primary")
        self.button.setText("Cancel" if running else "FLASH BOARD")
        self.button.setEnabled(True)
        self.button.style().unpolish(self.button)
        self.button.style().polish(self.button)
        self.bar.setVisible(running)
        self.phase.setVisible(running)
        self.percent.setVisible(running)
        if running:
            self.result.hide()
            self.hint.hide()
            self.bar.setValue(0)
            self.phase.setText("Starting…")
            self.percent.setText("0%")

    def set_progress(self, overall: float, message: str) -> None:
        self.bar.setValue(int(overall * 10))
        if message:
            self.phase.setText(message)
        self.percent.setText(f"{overall:.0f}%")

    def show_result(self, ok: bool, title: str, detail: str, has_log: bool) -> None:
        self.result.setObjectName("ResultOk" if ok else "ResultBad")
        self.result.style().unpolish(self.result)
        self.result.style().polish(self.result)
        self.result_title.setText(("✓  " if ok else "✕  ") + title)
        self.result_detail.setText(detail)
        self.view_log.setVisible(has_log and not ok)
        self.result.show()
        self.bar.hide()
        self.phase.hide()
        self.percent.hide()

    def clear_result(self) -> None:
        self.result.hide()

    def _clicked(self) -> None:
        if self._running:
            self.cancelRequested.emit()
        else:
            self.flashRequested.emit()
