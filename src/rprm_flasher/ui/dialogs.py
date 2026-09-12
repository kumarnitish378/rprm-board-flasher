"""Wiring help, self-test and About.

The wiring dialog reads its pin map from the board's JSON profile, so a board
added to ``avr.json`` brings its own diagram without any code change.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from .. import __author__, __version__
from ..core.errors import FlasherError
from ..core.models import BoardProfile, UploadMode
from ..core.registry import get_programmer


def _title(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("DialogTitle")
    return label


class WiringDialog(QDialog):
    """How to connect the UNO to the board being flashed."""

    def __init__(self, board: BoardProfile, mode: UploadMode, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Wiring")
        self.setMinimumWidth(520)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(16)
        layout.addWidget(_title(f"Wiring for {board.name}"))

        rows = board.wiring.get(mode.id, [])
        table = QTableWidget(len(rows), 2)
        table.setHorizontalHeaderLabels(["From — Arduino UNO", f"To — {board.name}"])
        table.verticalHeader().hide()
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        table.setShowGrid(False)
        for row, (source, destination) in enumerate(rows):
            table.setItem(row, 0, QTableWidgetItem(source))
            table.setItem(row, 1, QTableWidgetItem(destination))
        table.setFixedHeight(34 + 30 * max(len(rows), 1))
        layout.addWidget(table)

        note = QFrame()
        note.setObjectName("Warn")
        note_layout = QHBoxLayout(note)
        note_layout.setContentsMargins(14, 12, 14, 12)
        note_layout.setSpacing(10)
        icon = QLabel("⚠")
        icon.setObjectName("WarnIcon")
        icon.setAlignment(Qt.AlignmentFlag.AlignTop)
        note_layout.addWidget(icon)
        text = QLabel(
            "Upload the <b>ArduinoISP</b> sketch to the UNO first, then fit a "
            "<b>10 µF capacitor between the UNO's RESET and GND</b>. Without "
            "the capacitor the UNO resets itself when flashing starts and you "
            "get a sync error."
        )
        text.setObjectName("WarnText")
        text.setWordWrap(True)
        note_layout.addWidget(text, 1)
        layout.addWidget(note)

        if board.notes:
            hint = QLabel(board.notes)
            hint.setObjectName("Meta")
            hint.setWordWrap(True)
            layout.addWidget(hint)

        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        close.setFixedWidth(110)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(close)
        layout.addLayout(buttons)


class ReportDialog(QDialog):
    """Shows a self-test or support report, with a copy button."""

    def __init__(self, title: str, body: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(720, 560)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(14)
        layout.addWidget(_title(title))

        view = QPlainTextEdit(body)
        view.setObjectName("Log")
        view.setReadOnly(True)
        layout.addWidget(view, 1)

        copy = QPushButton("Copy to clipboard")
        copy.clicked.connect(lambda: self._copy(body, copy))
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        close.setFixedWidth(110)

        buttons = QHBoxLayout()
        buttons.addWidget(copy)
        buttons.addStretch(1)
        buttons.addWidget(close)
        layout.addLayout(buttons)

    @staticmethod
    def _copy(text: str, button: QPushButton) -> None:
        from PySide6.QtWidgets import QApplication

        QApplication.clipboard().setText(text)
        button.setText("Copied")


class AboutDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("About")
        self.setFixedWidth(460)

        try:
            avrdude = get_programmer("avr").version()
        except (FlasherError, OSError) as exc:
            avrdude = f"unavailable: {exc}"

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(12)
        layout.addWidget(_title("Raphe Board Flasher"))

        for line in (
            f"Version {__version__}",
            f"By {__author__}",
            "",
            f"Flashing engine: {avrdude}",
            "avrdude is free software under the GNU GPL; its licence is in "
            "tools/avr/LICENSE.txt.",
        ):
            label = QLabel(line)
            label.setObjectName("Meta")
            label.setWordWrap(True)
            layout.addWidget(label)

        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        close.setFixedWidth(110)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(close)
        layout.addLayout(buttons)


class SettingsDialog(QDialog):
    """Everything the operator can change, and nothing they cannot undo.

    Fuse and bootloader options are deliberately absent until v2: there is no
    setting here that can brick a board.
    """

    def __init__(self, settings, catalog, parent=None) -> None:
        super().__init__(parent)
        from PySide6.QtWidgets import QCheckBox, QComboBox, QFileDialog, QLineEdit

        self.settings = settings
        self.catalog = catalog
        self.setWindowTitle("Settings")
        self.setMinimumWidth(520)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(16)
        layout.addWidget(_title("Settings"))

        def row(label_text, widget, note=""):
            box = QVBoxLayout()
            box.setSpacing(5)
            caption = QLabel(label_text)
            caption.setObjectName("FieldLabel")
            box.addWidget(caption)
            if isinstance(widget, list):
                line = QHBoxLayout()
                line.setSpacing(8)
                for item in widget:
                    line.addWidget(item, 1 if item is widget[0] else 0)
                box.addLayout(line)
            else:
                box.addWidget(widget)
            if note:
                hint = QLabel(note)
                hint.setObjectName("Meta")
                hint.setWordWrap(True)
                box.addWidget(hint)
            layout.addLayout(box)

        self.theme_box = QComboBox()
        for label, value in (("Dark", "dark"), ("Light", "light")):
            self.theme_box.addItem(label, value)
        index = self.theme_box.findData(settings.theme)
        self.theme_box.setCurrentIndex(max(index, 0))
        row("Appearance", self.theme_box)

        self.board_box = QComboBox()
        for board in catalog:
            self.board_box.addItem(board.name, board.id)
        index = self.board_box.findData(settings.default_board)
        self.board_box.setCurrentIndex(max(index, 0))
        row("Board selected at startup", self.board_box)

        self.firmware_edit = QLineEdit(settings.firmware_dir)
        browse = QPushButton("Browse…")
        browse.setFixedWidth(110)

        def pick_folder():
            chosen = QFileDialog.getExistingDirectory(
                self, "Firmware folder", self.firmware_edit.text()
            )
            if chosen:
                self.firmware_edit.setText(chosen)

        browse.clicked.connect(pick_folder)
        row(
            "Firmware library folder",
            [self.firmware_edit, browse],
            "Firmware files here appear in the 'From library' list. A relative "
            "path is read from beside the program.",
        )

        self.verify_box = QCheckBox("Check the board after writing")
        self.verify_box.setChecked(settings.verify_after_write)
        layout.addWidget(self.verify_box)

        self.signature_box = QCheckBox(
            "Read the chip id before writing, and refuse a mismatch"
        )
        self.signature_box.setChecked(settings.check_signature)
        layout.addWidget(self.signature_box)

        warning = QLabel(
            "Both checks are recommended. Turning either off makes it possible "
            "to write the wrong firmware to a board without being told."
        )
        warning.setObjectName("Meta")
        warning.setWordWrap(True)
        layout.addWidget(warning)

        try:
            engine = get_programmer("avr").version()
        except (FlasherError, OSError) as exc:
            engine = f"unavailable: {exc}"
        footer = QLabel(
            f"Raphe Board Flasher v{__version__}  ·  {engine}\n"
            f"Settings file: {settings.source or 'not yet written'}"
        )
        footer.setObjectName("Meta")
        footer.setWordWrap(True)
        layout.addWidget(footer)

        save = QPushButton("Save")
        save.setFixedWidth(110)
        save.clicked.connect(self.accept)
        cancel = QPushButton("Cancel")
        cancel.setFixedWidth(110)
        cancel.clicked.connect(self.reject)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(cancel)
        buttons.addWidget(save)
        layout.addLayout(buttons)

    def apply_to_settings(self):
        """Copy the controls back onto the settings object and save it."""
        self.settings.theme = self.theme_box.currentData()
        self.settings.default_board = self.board_box.currentData()
        self.settings.firmware_dir = self.firmware_edit.text().strip() or "firmware"
        self.settings.verify_after_write = self.verify_box.isChecked()
        self.settings.check_signature = self.signature_box.isChecked()
        self.settings.save()
        return self.settings
