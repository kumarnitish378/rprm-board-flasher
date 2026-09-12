"""Colours, fonts and the stylesheet.

The palette is taken from raphe.com: ``--brand-background: #0a131a``,
``--white: #fcfcfc`` and the accent ``#01b4ea`` are the company's own published
values. The intermediate surfaces are derived from them, because a website
needs two surface levels and a desktop window needs four.

Three details carry the brand across: half-pixel cyan hairlines on focus,
white-to-cyan gradients on the wordmark and progress bar, and mint ``#00ffb2``
as the second accent, which is why "verified" is mint rather than a generic
green.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Palette:
    bg: str
    surface: str
    raised: str
    border: str
    text: str
    dim: str
    faint: str
    accent: str
    accent_hi: str
    accent_deep: str
    success: str
    warning: str
    danger: str
    log_bg: str


DARK = Palette(
    bg="#0A131A",          # raphe.com --brand-background
    surface="#101C25",
    raised="#16242F",
    border="#22323F",
    text="#FCFCFC",        # raphe.com --white
    dim="#848484",         # raphe.com grey
    faint="#505050",       # raphe.com grey
    accent="#01B4EA",      # raphe.com accent
    accent_hi="#3DCBF5",
    accent_deep="#0193C4",
    success="#00FFB2",     # raphe.com gradient mint
    warning="#F59E0B",
    danger="#EA384C",
    log_bg="#060D12",
)

LIGHT = Palette(
    bg="#F7F9FA",
    surface="#FFFFFF",
    raised="#EDF1F4",
    border="#D6DEE4",
    text="#0A131A",
    dim="#5A6773",
    faint="#8A97A3",
    accent="#0193C4",
    accent_hi="#01B4EA",
    accent_deep="#017CA6",
    success="#00A874",     # mint fails contrast on white
    warning="#B45309",
    danger="#C92A3C",
    log_bg="#F0F3F6",
)

#: Preferred families, in order. Qt falls back silently, so each list ends with
#: something Windows is guaranteed to have.
FONT_DISPLAY = '"Bebas Neue", "Oswald", "Segoe UI Semibold", sans-serif'
FONT_UI = '"Poppins", "Segoe UI", sans-serif'
FONT_BODY = '"Inter", "Segoe UI Variable Text", "Segoe UI", sans-serif'
FONT_MONO = '"JetBrains Mono", "Cascadia Mono", Consolas, monospace'


def stylesheet(p: Palette) -> str:
    """The whole application's QSS, built from one palette."""
    return f"""
    QWidget {{
        background: {p.bg};
        color: {p.text};
        font-family: {FONT_BODY};
        font-size: 13px;
    }}
    QToolTip {{
        background: {p.raised};
        color: {p.text};
        border: 1px solid {p.border};
        padding: 6px;
    }}

    /* ---- header and status bar ---- */
    #Header, #StatusBar {{ background: {p.surface}; }}
    #Header QLabel, #StatusBar QLabel {{ background: transparent; }}
    #Header {{ border-bottom: 1px solid {p.border}; }}
    #StatusBar {{ border-top: 1px solid {p.border}; }}
    #Wordmark {{
        font-family: {FONT_DISPLAY};
        font-size: 21px;
        letter-spacing: 2px;
        color: {p.text};
        background: transparent;
    }}
    #VersionPill {{
        font-family: {FONT_MONO};
        font-size: 11px;
        color: {p.dim};
        background: {p.raised};
        border-radius: 10px;
        padding: 3px 9px;
    }}
    #Credit {{ font-size: 11px; color: {p.faint}; background: transparent; }}
    #StatusText {{ font-size: 11px; color: {p.dim}; background: transparent; }}

    /* ---- cards ---- */
    #Card {{
        background: {p.surface};
        border: 1px solid {p.border};
        border-radius: 12px;
    }}
    #Card:disabled {{ color: {p.faint}; }}
    #StepBadge {{
        background: {p.accent};
        color: {p.bg};
        border-radius: 12px;
        font-family: {FONT_UI};
        font-size: 12px;
        font-weight: 600;
        min-width: 24px;
        max-width: 24px;
        min-height: 24px;
        max-height: 24px;
    }}
    #StepLabel {{
        font-family: {FONT_UI};
        font-size: 11px;
        font-weight: 600;
        letter-spacing: 1.2px;
        color: {p.dim};
        background: transparent;
    }}
    #FieldLabel {{ font-size: 11px; color: {p.dim}; background: transparent; }}
    #Meta {{ font-size: 11px; color: {p.dim}; background: transparent; }}
    #MetaGood {{ font-size: 11px; color: {p.success}; background: transparent; }}
    #MetaBad {{ font-size: 11px; color: {p.danger}; background: transparent; }}
    #Hint {{ font-size: 11px; color: {p.warning}; background: transparent; }}

    /* ---- inputs ---- */
    QComboBox {{
        background: {p.raised};
        border: 1px solid {p.border};
        border-radius: 8px;
        padding: 0 10px;
        min-height: 36px;
        color: {p.text};
    }}
    QComboBox:hover {{ border-color: {p.accent_deep}; }}
    QComboBox:focus {{ border: 1px solid {p.accent}; }}
    QComboBox:disabled {{ color: {p.faint}; }}
    QComboBox::drop-down {{ border: 0; width: 22px; }}
    QComboBox::down-arrow {{ image: none; }}
    QComboBox QAbstractItemView {{
        background: {p.raised};
        border: 1px solid {p.border};
        selection-background-color: {p.accent_deep};
        selection-color: {p.text};
        outline: 0;
        padding: 4px;
    }}

    QLineEdit {{
        background: {p.raised};
        border: 1px solid {p.border};
        border-radius: 8px;
        padding: 0 10px;
        min-height: 36px;
    }}
    QLineEdit:focus {{ border: 1px solid {p.accent}; }}

    QCheckBox {{ font-size: 12px; color: {p.dim}; spacing: 7px; background: transparent; }}
    QCheckBox::indicator {{
        width: 15px; height: 15px;
        border: 1px solid {p.border};
        border-radius: 4px;
        background: {p.raised};
    }}
    QCheckBox::indicator:checked {{
        background: {p.accent};
        border-color: {p.accent};
    }}
    QCheckBox::indicator:hover {{ border-color: {p.accent}; }}

    /* ---- buttons ---- */
    QPushButton {{
        background: {p.raised};
        border: 1px solid {p.border};
        border-radius: 8px;
        padding: 0 16px;
        min-height: 36px;
        font-family: {FONT_UI};
        font-size: 13px;
        color: {p.text};
    }}
    QPushButton:hover {{ border-color: {p.accent_deep}; }}
    QPushButton:pressed {{ background: {p.border}; }}
    QPushButton:disabled {{ color: {p.faint}; border-color: {p.border}; }}

    QPushButton#Primary {{
        background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                                    stop:0 {p.accent}, stop:1 {p.accent_deep});
        color: {p.bg};
        border: 0;
        border-radius: 10px;
        min-height: 52px;
        font-size: 15px;
        font-weight: 600;
        letter-spacing: 0.5px;
    }}
    QPushButton#Primary:hover {{
        background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                                    stop:0 {p.accent_hi}, stop:1 {p.accent});
    }}
    QPushButton#Primary:disabled {{
        background: {p.raised};
        color: {p.faint};
    }}
    QPushButton#Danger {{
        background: transparent;
        border: 2px solid {p.danger};
        color: {p.danger};
        border-radius: 10px;
        min-height: 52px;
        font-size: 15px;
        font-weight: 600;
    }}
    QPushButton#Danger:hover {{ background: rgba(234, 56, 76, 0.12); }}

    QPushButton#Icon {{
        background: transparent;
        border: 0;
        min-height: 32px;
        max-height: 32px;
        min-width: 32px;
        max-width: 32px;
        padding: 0;
        color: {p.dim};
        font-size: 15px;
    }}
    QPushButton#Icon:hover {{ background: {p.raised}; border-radius: 8px; color: {p.text}; }}

    QPushButton#Link {{
        background: transparent;
        border: 0;
        color: {p.accent};
        font-size: 11px;
        padding: 0;
        min-height: 18px;
        text-align: left;
    }}
    QPushButton#Link:hover {{ color: {p.accent_hi}; }}

    QPushButton#Ghost {{
        background: transparent;
        min-height: 30px;
        font-size: 12px;
        color: {p.dim};
    }}
    QPushButton#Ghost:hover {{ color: {p.text}; }}

    /* ---- segmented source toggle ---- */
    QPushButton#Segment {{
        background: transparent;
        border: 0;
        border-radius: 6px;
        min-height: 26px;
        font-size: 12px;
        color: {p.dim};
        padding: 0 8px;
    }}
    QPushButton#Segment:checked {{
        background: {p.accent};
        color: {p.bg};
        font-weight: 600;
    }}
    #Segmented {{ background: {p.raised}; border-radius: 8px; }}

    /* ---- drop zone and file chip ---- */
    #DropZone {{
        border: 2px dashed {p.border};
        border-radius: 10px;
        background: transparent;
    }}
    #DropZone[dragging="true"] {{
        border: 2px solid {p.accent};
        background: rgba(1, 180, 234, 0.07);
    }}
    #DropTitle {{ font-size: 13px; color: {p.text}; background: transparent; }}
    #DropOr {{ font-size: 11px; color: {p.faint}; background: transparent; }}
    #FileChip {{ background: {p.raised}; border-radius: 10px; }}
    #FileName {{ font-size: 13px; font-weight: 500; background: transparent; }}

    /* ---- banners ---- */
    #Warn {{
        background: rgba(245, 158, 11, 0.10);
        border-left: 3px solid {p.warning};
        border-radius: 8px;
    }}
    #WarnText {{ font-size: 12px; color: {p.text}; background: transparent; }}
    #WarnIcon {{ color: {p.warning}; font-size: 15px; background: transparent; }}

    #ResultOk {{
        background: rgba(0, 255, 178, 0.09);
        border-left: 3px solid {p.success};
        border-radius: 10px;
    }}
    #ResultBad {{
        background: rgba(234, 56, 76, 0.10);
        border-left: 3px solid {p.danger};
        border-radius: 10px;
    }}
    #ResultTitle {{ font-size: 13px; font-weight: 600; background: transparent; }}
    #ResultDetail {{ font-size: 11px; color: {p.dim}; background: transparent; }}

    /* ---- progress ---- */
    QProgressBar {{
        background: {p.raised};
        border: 0;
        border-radius: 4px;
        max-height: 8px;
        min-height: 8px;
        text-align: center;
    }}
    QProgressBar::chunk {{
        border-radius: 4px;
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                                    stop:0 {p.text}, stop:1 {p.accent});
    }}

    /* ---- log ---- */
    QPlainTextEdit#Log {{
        background: {p.log_bg};
        border: 1px solid {p.border};
        border-radius: 8px;
        font-family: {FONT_MONO};
        font-size: 12px;
        color: {p.dim};
        padding: 8px;
    }}

    QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0; }}
    QScrollBar::handle:vertical {{
        background: {p.border}; border-radius: 5px; min-height: 30px;
    }}
    QScrollBar::handle:vertical:hover {{ background: {p.dim}; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
    QScrollArea {{ border: 0; }}

    /* ---- dialogs ---- */
    QDialog {{ background: {p.surface}; }}
    #DialogTitle {{
        font-family: {FONT_UI};
        font-size: 15px;
        font-weight: 600;
        background: transparent;
    }}
    QTableWidget {{
        background: transparent;
        border: 0;
        gridline-color: {p.border};
        font-family: {FONT_MONO};
        font-size: 12px;
    }}
    QHeaderView::section {{
        background: transparent;
        border: 0;
        border-bottom: 1px solid {p.border};
        color: {p.dim};
        font-family: {FONT_UI};
        font-size: 10px;
        font-weight: 600;
        padding: 4px 0;
        text-align: left;
    }}
    """
