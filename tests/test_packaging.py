"""Guards on the build, so packaging problems fail here and not on a desk.

Every assertion here corresponds to something that actually broke while M4 was
being built, or to something whose absence would only show up in a frozen
build on someone else's machine.
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
PKG = SRC / "rprm_flasher"
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(ROOT / "build"))

from rprm_flasher import __version__  # noqa: E402

SPEC = (ROOT / "build" / "flasher.spec").read_text(encoding="utf-8")


class TestFrozenEntryPoint:
    """PyInstaller runs __main__.py as a top-level script, not as part of the
    package, so a relative import there fails only in the frozen build with
    "attempted relative import with no known parent package"."""

    SOURCE = (PKG / "__main__.py").read_text(encoding="utf-8")

    def test_no_relative_imports(self):
        for line in self.SOURCE.splitlines():
            stripped = line.strip()
            assert not stripped.startswith("from ."), stripped

    def test_it_imports_by_absolute_package_name(self):
        assert "from rprm_flasher.cli import" in self.SOURCE
        assert "from rprm_flasher.app import" in self.SOURCE

    def test_no_arguments_means_the_gui(self):
        # The windowed exe is launched with no arguments; the console one is
        # given a command. One entry point has to route both.
        assert "if args:" in self.SOURCE


class TestSpec:
    def test_every_bundled_file_exists_in_the_source_tree(self):
        for relative in (
            "backends/avr/tools/avrdude.exe",
            "backends/avr/tools/avrdude.conf",
            "backends/avr/tools/LICENSE.txt",
            "config/boards",
            "ui/assets/logo.png",
            "ui/assets/app.ico",
            "ui/assets/fonts",
        ):
            assert (PKG / relative).exists(), relative
            assert relative in SPEC or relative.split("/")[-1] in SPEC, relative

    def test_pyserial_backend_is_declared_hidden(self):
        # PyInstaller cannot see this import statically; without it the frozen
        # build finds no serial ports at all.
        assert "serial.tools.list_ports" in SPEC

    def test_it_is_a_onedir_build(self):
        # --onefile unpacks to temp on every launch: slow, and the main reason
        # antivirus flags PyInstaller output.
        assert "COLLECT(" in SPEC
        assert "exclude_binaries=True" in SPEC

    def test_upx_is_off(self):
        assert "upx=True" not in SPEC

    def test_both_executables_are_produced(self):
        assert 'name="RapheBoardFlasher"' in SPEC   # windowed
        assert 'name="rprm-flasher"' in SPEC        # console
        assert "console=False" in SPEC
        assert "console=True" in SPEC

    def test_the_heavy_unused_dlls_are_pruned(self):
        for name in ("opengl32sw", "libcrypto-3", "libssl-3"):
            assert name in SPEC, name


class TestVersionResource:
    PATH = ROOT / "build" / "version_info.txt"

    def test_it_exists(self):
        assert self.PATH.is_file()

    def test_it_matches_the_package_version(self):
        text = self.PATH.read_text(encoding="utf-8")
        assert f'"FileVersion", "{__version__}"' in text
        major, minor, patch = __version__.split(".")
        assert f"filevers=({major}, {minor}, {patch}, 0)" in text

    def test_it_credits_the_authors_and_the_gpl_tool(self):
        text = self.PATH.read_text(encoding="utf-8")
        assert "Raphe mPhibr" in text
        assert "Nitish Sharma" in text
        assert "GPL" in text  # avrdude is GPL and is redistributed


class TestIcon:
    PATH = PKG / "ui" / "assets" / "app.ico"

    def test_it_exists_and_is_an_icon(self):
        raw = self.PATH.read_bytes()
        reserved, kind, count = struct.unpack("<HHH", raw[:6])
        assert reserved == 0 and kind == 1
        assert count >= 4

    def test_every_frame_is_a_valid_png(self):
        raw = self.PATH.read_bytes()
        _, _, count = struct.unpack("<HHH", raw[:6])
        for index in range(count):
            entry = raw[6 + 16 * index: 22 + 16 * index]
            *_head, size, offset = struct.unpack("<BBBBHHII", entry)
            assert raw[offset:offset + 4] == b"\x89PNG", index
            assert size > 0

    def test_it_carries_the_small_sizes_windows_actually_uses(self):
        raw = self.PATH.read_bytes()
        _, _, count = struct.unpack("<HHH", raw[:6])
        sizes = set()
        for index in range(count):
            width = raw[6 + 16 * index]
            sizes.add(width or 256)
        # 16 and 32 are the taskbar and Alt-Tab frames; without them Windows
        # downscales the 256 and the mark turns to mush.
        assert {16, 32, 256} <= sizes, sizes


class TestPackagingScript:
    def test_it_checks_for_every_file_that_must_ship(self):
        import package

        required = set(package.REQUIRED)
        assert "RapheBoardFlasher.exe" in required
        assert "README.txt" in required
        assert "Check-This-PC-First.cmd" in required
        assert any("avrdude.exe" in name for name in required)
        assert any("avr.json" in name for name in required)

    def test_the_zip_name_keeps_the_full_version(self):
        # Path.with_suffix on "..._v1.0.0" eats the ".0"; the script must not
        # use it. This caught a real mis-named archive.
        import package

        source = Path(package.__file__).read_text(encoding="utf-8")
        assert "with_suffix" not in source or "Not Path.with_suffix" in source
        assert f'RapheBoardFlasher_v{{__version__}}.zip' in source


class TestOperatorDocs:
    README = ROOT / "build" / "package" / "README.txt"
    CHECK = ROOT / "build" / "package" / "Check-This-PC-First.cmd"

    def test_the_readme_ships(self):
        assert self.README.is_file()

    def test_it_tells_them_to_unblock_the_zip(self):
        # Windows marks emailed files, and the program then refuses to start.
        assert "Unblock" in self.README.read_text(encoding="utf-8")

    def test_it_warns_that_isp_wipes_the_bootloader(self):
        text = self.README.read_text(encoding="utf-8").lower()
        assert "bootloader" in text
        assert "capacitor" in text

    def test_the_pc_check_looks_for_smart_app_control(self):
        # An unsigned PyInstaller exe can be blocked outright on Windows 11.
        # A .cmd still runs when the .exe does not, so it can say why.
        text = self.CHECK.read_text(encoding="utf-8")
        assert "VerifiedAndReputablePolicyState" in text
        assert "Smart App Control" in text

    def test_the_pc_check_looks_for_the_download_marker(self):
        assert "Zone.Identifier" in self.CHECK.read_text(encoding="utf-8")

    def test_no_unescaped_ampersand_reaches_the_operator(self):
        # cmd needs & escaped, and the escape survived into the printed text.
        assert "^&" not in self.CHECK.read_text(encoding="utf-8")


@pytest.mark.skipif(
    not (ROOT / "dist" / "RapheBoardFlasher").is_dir(),
    reason="no build present; run python build/package.py first",
)
class TestBuiltPackage:
    STAGE = ROOT / "dist" / "RapheBoardFlasher"

    def test_everything_required_is_present(self):
        import package

        assert package.verify() == []

    def test_the_bundled_avrdude_is_the_real_one(self):
        built = self.STAGE / "_internal/rprm_flasher/backends/avr/tools/avrdude.exe"
        assert built.read_bytes()[:2] == b"MZ"
        assert built.stat().st_size == (
            PKG / "backends/avr/tools/avrdude.exe"
        ).stat().st_size

    def test_the_pruned_dlls_did_not_come_back(self):
        for name in ("opengl32sw.dll", "libcrypto-3-x64.dll", "libssl-3-x64.dll"):
            assert not list(self.STAGE.rglob(name)), name
