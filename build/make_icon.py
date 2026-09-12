"""Generate the application icon.

Two drawings, not one scaled drawing: at 16 and 24 pixels the chip outline and
the bolt merge into a smudge, so the small frames carry the bolt alone. Windows
picks the nearest frame, so the taskbar and Alt-Tab stay legible.

    python build/make_icon.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRectF, Qt  # noqa: E402
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

ASSETS = Path(__file__).resolve().parent.parent / "src/rprm_flasher/ui/assets"

SLATE = QColor("#5A6E7E")
CYAN = QColor("#01B4EA")

#: Frames Windows expects in an .ico, and whether each keeps the chip outline.
FRAMES = [(256, True), (128, True), (64, True), (48, True), (32, False), (16, False)]


def bolt_path(u: float) -> QPainterPath:
    path = QPainterPath()
    path.moveTo(37 * u, 20 * u)
    path.lineTo(26 * u, 34.5 * u)
    path.lineTo(32.5 * u, 34.5 * u)
    path.lineTo(27 * u, 45 * u)
    path.lineTo(38.5 * u, 30 * u)
    path.lineTo(32 * u, 30 * u)
    path.closeSubpath()
    return path


def draw(size: int, with_chip: bool) -> QImage:
    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    u = size / 64.0

    if with_chip:
        pen = QPen(SLATE, 3.4 * u)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(QRectF(16 * u, 16 * u, 32 * u, 32 * u), 7 * u, 7 * u)
        for x in (25, 39):
            painter.drawLine(int(x * u), int(9 * u), int(x * u), int(16 * u))
            painter.drawLine(int(x * u), int(48 * u), int(x * u), int(55 * u))
        for y in (25, 39):
            painter.drawLine(int(9 * u), int(y * u), int(16 * u), int(y * u))
            painter.drawLine(int(48 * u), int(y * u), int(55 * u), int(y * u))
        path = bolt_path(u)
    else:
        # Bolt only, scaled up to fill the frame.
        painter.translate(size / 2, size / 2)
        painter.scale(1.85, 1.85)
        painter.translate(-32 * u, -32 * u)
        path = bolt_path(u)

    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(CYAN)
    painter.drawPath(path)
    painter.end()
    return image


def main() -> int:
    # Held in a local: a QApplication that gets garbage collected while a
    # QPainter is still alive takes the interpreter down with it.
    app = QApplication([])
    ASSETS.mkdir(parents=True, exist_ok=True)

    frames = [draw(size, with_chip) for size, with_chip in FRAMES]
    icon = ASSETS / "app.ico"
    # Qt's ICO writer only stores one image, so the container is built by hand.
    _write_ico(icon, frames)
    draw(256, True).save(str(ASSETS / "logo.png"))
    print(f"wrote {icon} with {len(frames)} frames")
    del app
    return 0


def _write_ico(path: Path, frames: list[QImage]) -> None:
    """Assemble a multi-frame .ico from PNG-encoded images.

    Every size above 0 is stored PNG-compressed, which Windows Vista and later
    accept and which keeps the file small.
    """
    import struct
    from PySide6.QtCore import QBuffer, QByteArray

    blobs = []
    for frame in frames:
        # The QByteArray must outlive the QBuffer that writes into it. Passing
        # a temporary here segfaults the interpreter: PySide6 does not take a
        # reference, so it is freed while the buffer still points at it.
        data = QByteArray()
        buffer = QBuffer(data)
        buffer.open(QBuffer.OpenModeFlag.WriteOnly)
        frame.save(buffer, "PNG")
        buffer.close()
        blobs.append(bytes(data))

    header = struct.pack("<HHH", 0, 1, len(blobs))
    offset = len(header) + 16 * len(blobs)
    entries, payload = b"", b""
    for frame, blob in zip(frames, blobs):
        side = 0 if frame.width() >= 256 else frame.width()
        entries += struct.pack(
            "<BBBBHHII", side, side, 0, 0, 1, 32, len(blob), offset
        )
        offset += len(blob)
        payload += blob
    path.write_bytes(header + entries + payload)


if __name__ == "__main__":
    raise SystemExit(main())
