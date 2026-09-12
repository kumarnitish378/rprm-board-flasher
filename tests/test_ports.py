"""Port classification.

Bluetooth ports get their own test because picking one is the fastest way for
an operator to wedge the tool: Windows blocks on opening them rather than
failing, so avrdude hangs with no output at all.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rprm_flasher.core.models import SerialPortInfo  # noqa: E402
from rprm_flasher.hardware import port_scanner  # noqa: E402

ARDUINO = SerialPortInfo("COM7", "Arduino Uno (COM7)", "Arduino LLC", 0x2341, 0x0043)
CLONE = SerialPortInfo("COM3", "USB-SERIAL CH340 (COM3)", "wch.cn", 0x1A86, 0x7523)
FTDI = SerialPortInfo("COM12", "USB Serial Port (COM12)", "FTDI", 0x0403, 0x6001)
BLUETOOTH = SerialPortInfo("COM5", "Standard Serial over Bluetooth link (COM5)")
MYSTERY = SerialPortInfo("COM1", "Communications Port (COM1)")


class TestClassification:
    def test_genuine_arduino(self):
        assert port_scanner.is_likely_board(ARDUINO)

    def test_ch340_clone(self):
        assert port_scanner.is_likely_board(CLONE)

    def test_ftdi_adapter(self):
        assert port_scanner.is_likely_board(FTDI)

    def test_bluetooth_is_not_a_board(self):
        assert port_scanner.is_bluetooth(BLUETOOTH)
        assert not port_scanner.is_likely_board(BLUETOOTH)

    def test_plain_serial_port_is_not_a_board(self):
        assert not port_scanner.is_likely_board(MYSTERY)

    def test_vendor_names(self):
        assert port_scanner.vendor_name(CLONE) == "CH340 clone"
        assert port_scanner.vendor_name(BLUETOOTH) == ""


class TestOrdering:
    def test_boards_first_bluetooth_last(self, monkeypatch):
        monkeypatch.setattr(
            port_scanner, "list_ports", port_scanner.list_ports
        )  # keep the real function; we sort by hand below
        ordered = sorted(
            [BLUETOOTH, MYSTERY, CLONE, ARDUINO],
            key=lambda p: (
                not port_scanner.is_likely_board(p),
                port_scanner.is_bluetooth(p),
                p.device,
            ),
        )
        assert ordered[0] in (ARDUINO, CLONE)
        assert ordered[-1] is BLUETOOTH

    def test_com2_sorts_before_com10(self):
        assert port_scanner._port_number("COM2") < port_scanner._port_number("COM10")


class TestLabels:
    def test_label_includes_the_description(self):
        assert "Arduino Uno" in ARDUINO.label
        assert ARDUINO.label.startswith("COM7")

    def test_label_falls_back_to_the_device(self):
        assert SerialPortInfo("COM9").label == "COM9"
