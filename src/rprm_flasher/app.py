"""Entry point for the GUI.

    python -m rprm_flasher.app
"""

from __future__ import annotations

import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox

from .config.settings import Settings
from .core.errors import FlasherError
from .core.registry import get_programmer
from .ui.main_window import MainWindow, load_bundled_fonts
from .ui.main_window import PALETTES
from .ui.theme import DARK, stylesheet


def main(argv: list[str] | None = None) -> int:
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_DontUseNativeMenuBar, True)
    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName("Raphe Board Flasher")
    app.setOrganizationName("Raphe mPhibr")

    load_bundled_fonts()
    settings = Settings.load()
    app.setStyleSheet(stylesheet(PALETTES.get(settings.theme, DARK)))

    # Fail loudly and early rather than at the moment someone presses Flash.
    try:
        ok, reason = get_programmer("avr").available()
    except FlasherError as exc:
        ok, reason = False, f"{exc.title}. {exc.fix}"
    if not ok:
        QMessageBox.critical(
            None,
            "Raphe Board Flasher cannot start",
            f"{reason}\n\nThe zip file was probably not fully extracted. "
            "Extract it again, keeping every file together.",
        )
        return 1

    window = MainWindow(settings)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
