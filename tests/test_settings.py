"""Settings persistence and the light theme.

A corrupt or unwritable settings file must never stop the tool starting: an
operator at a remote site has no way to fix one.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from rprm_flasher.config.settings import Settings  # noqa: E402
from rprm_flasher.ui.theme import DARK, LIGHT, stylesheet  # noqa: E402


class TestDefaults:
    def test_the_cautious_options_are_the_defaults(self):
        # Someone who never opens Settings gets the safest behaviour.
        settings = Settings()
        assert settings.verify_after_write
        assert settings.check_signature
        assert settings.theme == "dark"

    def test_missing_file_gives_defaults(self, tmp_path):
        settings = Settings.load(tmp_path / "nothing.json")
        assert settings.default_board == "mega2560"


class TestRoundTrip:
    def test_saved_settings_come_back(self, tmp_path):
        target = tmp_path / "settings.json"
        original = Settings.load(target)
        original.theme = "light"
        original.verify_after_write = False
        original.default_board = "uno"
        original.firmware_dir = "builds"
        original.save(target)

        reloaded = Settings.load(target)
        assert reloaded.theme == "light"
        assert reloaded.verify_after_write is False
        assert reloaded.default_board == "uno"
        assert reloaded.firmware_dir == "builds"

    def test_the_file_is_readable_json(self, tmp_path):
        target = tmp_path / "settings.json"
        Settings().save(target)
        payload = json.loads(target.read_text(encoding="utf-8"))
        assert payload["theme"] == "dark"
        assert "source" not in payload  # internal, not persisted


class TestResilience:
    def test_corrupt_file_does_not_stop_startup(self, tmp_path):
        target = tmp_path / "settings.json"
        target.write_text("{ this is not json", encoding="utf-8")
        settings = Settings.load(target)
        assert settings.theme == "dark"

    def test_a_json_array_is_ignored(self, tmp_path):
        target = tmp_path / "settings.json"
        target.write_text("[1, 2, 3]", encoding="utf-8")
        assert Settings.load(target).default_board == "mega2560"

    def test_wrong_types_are_ignored_field_by_field(self, tmp_path):
        target = tmp_path / "settings.json"
        target.write_text(
            json.dumps({"verify_after_write": "yes please", "default_board": "uno"}),
            encoding="utf-8",
        )
        settings = Settings.load(target)
        assert settings.verify_after_write is True   # bad value rejected
        assert settings.default_board == "uno"       # good value kept

    def test_an_unknown_theme_falls_back_to_dark(self, tmp_path):
        target = tmp_path / "settings.json"
        target.write_text(json.dumps({"theme": "neon"}), encoding="utf-8")
        assert Settings.load(target).theme == "dark"

    def test_an_empty_firmware_folder_is_replaced(self, tmp_path):
        settings = Settings.load(tmp_path / "s.json")
        settings.firmware_dir = "   "
        settings.normalise()
        assert settings.firmware_dir == "firmware"


class TestPaths:
    def test_a_relative_firmware_folder_resolves_beside_the_program(self):
        settings = Settings(firmware_dir="firmware")
        assert settings.firmware_path().is_absolute()
        assert settings.firmware_path().name == "firmware"

    def test_an_absolute_firmware_folder_is_used_as_given(self, tmp_path):
        settings = Settings(firmware_dir=str(tmp_path))
        assert settings.firmware_path() == tmp_path

    def test_blank_avrdude_means_use_the_bundled_one(self):
        assert Settings().avrdude() is None

    def test_a_bad_avrdude_override_is_ignored(self, tmp_path):
        settings = Settings(avrdude_path=str(tmp_path / "not-here.exe"))
        assert settings.avrdude() is None


class TestLightTheme:
    def test_every_token_differs_from_dark(self):
        for name in ("bg", "surface", "raised", "text", "dim"):
            assert getattr(LIGHT, name) != getattr(DARK, name), name

    def test_mint_is_darkened_for_white_backgrounds(self):
        # #00FFB2 is unreadable on white, so light theme uses a darker green.
        assert LIGHT.success != DARK.success

    def test_both_stylesheets_cover_the_same_selectors(self):
        dark_css = stylesheet(DARK)
        light_css = stylesheet(LIGHT)
        for selector in (
            "#Card", "#Header", "#StatusBar", "QPushButton#Primary",
            "QPushButton#Danger", "QProgressBar::chunk", "#ResultOk",
            "#ResultBad", "#Warn", "QPlainTextEdit#Log",
        ):
            assert selector in dark_css, selector
            assert selector in light_css, selector

    def test_the_light_theme_paints_a_light_ground(self):
        # Not a plain "is this hex absent" check: LIGHT.text is deliberately
        # the same navy as DARK.bg, so only the background rules matter.
        light_css = stylesheet(LIGHT)
        assert f"background: {LIGHT.bg};" in light_css
        assert f"background: {DARK.bg};" not in light_css
        assert f"background: {DARK.surface};" not in light_css


class TestBundledFonts:
    FONTS = ROOT / "src/rprm_flasher/ui/assets/fonts"

    def test_the_brand_faces_are_shipped(self):
        names = {p.name for p in self.FONTS.glob("*.ttf")}
        assert "BebasNeue-Regular.ttf" in names
        assert "Poppins-SemiBold.ttf" in names

    def test_they_are_real_truetype_files(self):
        for font in self.FONTS.glob("*.ttf"):
            assert font.read_bytes()[:4] in (b"\x00\x01\x00\x00", b"OTTO"), font.name

    def test_their_licences_travel_with_them(self):
        licences = list(self.FONTS.glob("OFL*.txt"))
        assert len(licences) >= 2
        for licence in licences:
            assert "SIL OPEN FONT LICENSE" in licence.read_text(encoding="utf-8").upper()

    def test_qt_actually_loads_them(self):
        pytest.importorskip("PySide6")
        from PySide6.QtGui import QFontDatabase
        from PySide6.QtWidgets import QApplication

        QApplication.instance() or QApplication([])
        from rprm_flasher.ui.main_window import load_bundled_fonts

        load_bundled_fonts()
        families = set(QFontDatabase.families())
        assert "Bebas Neue" in families
        assert "Poppins" in families
