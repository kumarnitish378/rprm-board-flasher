"""Command construction, board profiles and firmware validation.

These assert the thing most likely to silently ruin a board: the exact avrdude
argument list. None of them spawn a process.
"""

from __future__ import annotations

import binascii
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rprm_flasher.backends.avr.programmer import AvrdudeProgrammer  # noqa: E402
from rprm_flasher.core.errors import FlasherError  # noqa: E402
from rprm_flasher.core.models import FlashJob, Target  # noqa: E402
from rprm_flasher.core.registry import load_catalog  # noqa: E402
from rprm_flasher.sources.base import inspect  # noqa: E402


@pytest.fixture(scope="module")
def catalog():
    return load_catalog()


@pytest.fixture(scope="module")
def programmer():
    return AvrdudeProgrammer()


def hex_file(tmp_path: Path, records: list[str], name: str = "fw.hex") -> Path:
    path = tmp_path / name
    path.write_text("\n".join(records) + "\n", encoding="ascii")
    return path


def hex_record(address: int, payload: bytes, record_type: int = 0x00) -> str:
    body = bytes([len(payload), address >> 8, address & 0xFF, record_type]) + payload
    checksum = (-sum(body)) & 0xFF
    return ":" + (body + bytes([checksum])).hex().upper()


EOF_RECORD = ":00000001FF"


# -- board catalog ---------------------------------------------------------


class TestCatalog:
    def test_profiles_load(self, catalog):
        assert len(catalog) >= 7
        assert catalog.families() == {"avr"}

    def test_mega_profile(self, catalog):
        mega = catalog.get("mega2560")
        assert mega.chip == "atmega2560"
        assert mega.flash_bytes == 262144
        assert mega.signature == "0x1e9801"
        assert {"isp_uno", "usb_bootloader"} <= set(mega.modes)

    def test_every_mode_names_a_programmer(self, catalog):
        for board in catalog:
            for mode in board.modes.values():
                assert mode.options.get("programmer"), f"{board.id}/{mode.id}"

    def test_isp_modes_are_flagged_as_destroying_the_bootloader(self, catalog):
        for board in catalog:
            mode = board.modes.get("isp_uno")
            if mode:
                assert mode.erases_bootloader
                assert mode.port_belongs_to == "programmer"

    def test_signature_lookup(self, catalog):
        assert any(b.id == "mega2560" for b in catalog.by_signature("0x1e9801"))

    def test_unknown_board_is_rejected(self, catalog):
        with pytest.raises(KeyError):
            catalog.get("esp32")


# -- avrdude command line --------------------------------------------------


class TestFlashCommand:
    def _job(self, catalog, tmp_path, board_id="mega2560", mode="isp_uno", verify=True):
        path = hex_file(tmp_path, [hex_record(0, b"\x0c\x94"), EOF_RECORD])
        board = catalog.get(board_id)
        target = Target(board=board, mode=board.modes[mode], port="COM5")
        return FlashJob(target=target, firmware=inspect(path), verify=verify)

    def test_isp_mode_uses_stk500v1_at_19200(self, catalog, programmer, tmp_path):
        argv = programmer.build_flash_argv(self._job(catalog, tmp_path))
        assert argv[argv.index("-c") + 1] == "stk500v1"
        assert argv[argv.index("-b") + 1] == "19200"
        assert argv[argv.index("-p") + 1] == "atmega2560"
        assert argv[argv.index("-P") + 1] == "COM5"

    def test_isp_mode_chip_erases(self, catalog, programmer, tmp_path):
        argv = programmer.build_flash_argv(self._job(catalog, tmp_path))
        assert "-e" in argv
        assert "-D" not in argv  # -D would defeat the erase

    def test_bootloader_mode_uses_wiring_at_115200(self, catalog, programmer, tmp_path):
        job = self._job(catalog, tmp_path, mode="usb_bootloader")
        argv = programmer.build_flash_argv(job)
        # A Mega bootloader speaks 'wiring', not 'arduino'.
        assert argv[argv.index("-c") + 1] == "wiring"
        assert argv[argv.index("-b") + 1] == "115200"
        assert "-D" in argv
        assert "-e" not in argv

    def test_uno_bootloader_uses_arduino(self, catalog, programmer, tmp_path):
        job = self._job(catalog, tmp_path, board_id="uno", mode="usb_bootloader")
        argv = programmer.build_flash_argv(job)
        assert argv[argv.index("-c") + 1] == "arduino"

    def test_write_spec_is_last_and_well_formed(self, catalog, programmer, tmp_path):
        job = self._job(catalog, tmp_path)
        argv = programmer.build_flash_argv(job)
        assert argv[-2] == "-U"
        assert argv[-1].startswith("flash:w:")
        assert argv[-1].endswith(":i")

    def test_bin_firmware_uses_raw_format(self, catalog, programmer, tmp_path):
        path = tmp_path / "fw.bin"
        path.write_bytes(b"\x0c\x94\x00\x00" * 16)
        board = catalog.get("mega2560")
        job = FlashJob(
            target=Target(board=board, mode=board.modes["isp_uno"], port="COM5"),
            firmware=inspect(path),
        )
        assert programmer.build_flash_argv(job)[-1].endswith(":r")

    def test_verify_is_on_by_default(self, catalog, programmer, tmp_path):
        # avrdude verifies unless told not to, so -V must be absent.
        argv = programmer.build_flash_argv(self._job(catalog, tmp_path))
        assert "-V" not in argv

    def test_no_verify_adds_the_disable_flag(self, catalog, programmer, tmp_path):
        argv = programmer.build_flash_argv(self._job(catalog, tmp_path, verify=False))
        assert "-V" in argv

    def test_config_file_is_always_passed(self, catalog, programmer, tmp_path):
        argv = programmer.build_flash_argv(self._job(catalog, tmp_path))
        assert argv[argv.index("-C") + 1].endswith("avrdude.conf")


class TestDetectCommand:
    def test_detect_never_writes(self, catalog, programmer):
        board = catalog.get("mega2560")
        target = Target(board=board, mode=board.modes["isp_uno"], port="COM5")
        argv = programmer.build_detect_argv(target)
        assert "-n" in argv          # no writes
        assert "-F" in argv          # report a mismatched signature instead of bailing
        assert "-U" not in argv
        assert "-e" not in argv


class TestBundledTool:
    def test_avrdude_is_bundled(self, programmer):
        ok, reason = programmer.available()
        assert ok, reason

    def test_reports_its_version(self, programmer):
        assert "8.0" in programmer.version()


# -- firmware validation ---------------------------------------------------


class TestFirmwareInspection:
    def test_counts_program_bytes_not_file_bytes(self, tmp_path):
        path = hex_file(
            tmp_path,
            [hex_record(0, bytes(16)), hex_record(16, bytes(16)), EOF_RECORD],
        )
        firmware = inspect(path)
        assert firmware.program_bytes == 32
        assert firmware.size_bytes > 32  # the text form is much larger

    def test_crc32_matches_the_file(self, tmp_path):
        path = hex_file(tmp_path, [hex_record(0, b"\x01\x02"), EOF_RECORD])
        expected = f"{binascii.crc32(path.read_bytes()) & 0xFFFFFFFF:08X}"
        assert inspect(path).crc32 == expected

    def test_bad_checksum_is_caught(self, tmp_path):
        good = hex_record(0, b"\x01\x02")
        corrupted = good[:-2] + "00"
        path = hex_file(tmp_path, [corrupted, EOF_RECORD])
        with pytest.raises(FlasherError, match="damaged"):
            inspect(path)

    def test_garbage_line_is_caught(self, tmp_path):
        path = hex_file(tmp_path, ["this is not intel hex", EOF_RECORD])
        with pytest.raises(FlasherError, match="damaged"):
            inspect(path)

    def test_truncated_record_is_caught(self, tmp_path):
        path = hex_file(tmp_path, [":10000000AABB", EOF_RECORD])
        with pytest.raises(FlasherError, match="damaged"):
            inspect(path)

    def test_missing_eof_warns_but_still_loads(self, tmp_path):
        path = hex_file(tmp_path, [hex_record(0, b"\x01\x02")])
        firmware = inspect(path)
        assert firmware.program_bytes == 2
        assert any("truncated" in w for w in firmware.warnings)

    def test_empty_file_is_rejected(self, tmp_path):
        path = tmp_path / "empty.hex"
        path.write_text("", encoding="ascii")
        with pytest.raises(FlasherError, match="empty"):
            inspect(path)

    def test_hex_with_no_data_records_is_rejected(self, tmp_path):
        path = hex_file(tmp_path, [EOF_RECORD])
        with pytest.raises(FlasherError, match="no program"):
            inspect(path)

    def test_wrong_extension_is_rejected(self, tmp_path):
        path = tmp_path / "firmware.zip"
        path.write_bytes(b"PK\x03\x04")
        with pytest.raises(FlasherError, match="cannot be flashed"):
            inspect(path)

    def test_missing_file_is_rejected(self, tmp_path):
        with pytest.raises(FlasherError, match="not there"):
            inspect(tmp_path / "nope.hex")

    def test_bin_carries_the_address_warning(self, tmp_path):
        path = tmp_path / "fw.bin"
        path.write_bytes(b"\xff" * 64)
        assert any("0x0000" in w for w in inspect(path).warnings)

    def test_fit_check_against_a_board(self, tmp_path, catalog):
        path = hex_file(tmp_path, [hex_record(0, bytes(16)), EOF_RECORD])
        firmware = inspect(path)
        assert firmware.fits(catalog.get("uno"))
        assert firmware.usage_percent(catalog.get("uno")) == pytest.approx(
            100 * 16 / 32768
        )


class TestProfilesAgainstRealAvrdude:
    """Validate every profile against the bundled binary, not against belief.

    A typo in avr.json would otherwise surface as a cryptic avrdude error on a
    remote user's desk, long after anyone could debug it.
    """

    def _known(self, programmer, part: str) -> bool:
        # -p <part>/s prints the part definition and needs no serial port, so
        # an unknown part produces no output at all.
        proc = programmer._run_blocking(
            [str(programmer.executable), "-C", str(programmer.config), "-p", f"{part}/s"]
        )
        return "#---" in (proc.stdout or "") + (proc.stderr or "")

    def test_every_chip_id_is_real(self, catalog, programmer):
        for board in catalog:
            assert self._known(programmer, board.chip), (
                f"{board.id} names chip {board.chip!r}, which this avrdude "
                "does not know"
            )

    def test_the_check_itself_works(self, programmer):
        assert not self._known(programmer, "notarealchip")

    def test_every_programmer_id_is_real(self, catalog, programmer):
        proc = programmer._run_blocking(
            [str(programmer.executable), "-C", str(programmer.config), "-c", "?"]
        )
        listing = (proc.stdout or "") + (proc.stderr or "")
        for board in catalog:
            for mode in board.modes.values():
                name = mode.options["programmer"]
                assert f"{name} " in listing or f"{name}=" in listing, (
                    f"{board.id}/{mode.id} names programmer {name!r}, which "
                    "this avrdude does not know"
                )
