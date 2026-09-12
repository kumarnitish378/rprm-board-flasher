"""Serial port discovery.

pyserial rather than avrdude's own ``-P ?s``, because pyserial gives the
friendly name Windows shows in Device Manager ("Arduino Uno", "USB-SERIAL
CH340"), which is what lets an operator pick the right port without counting.
"""

from __future__ import annotations

from ..core.models import SerialPortInfo

#: USB vendor ids worth floating to the top of the list.
_KNOWN_VENDORS = {
    0x2341: "Arduino",
    0x2A03: "Arduino (.org)",
    0x1A86: "CH340 clone",
    0x0403: "FTDI",
    0x10C4: "CP210x",
    0x067B: "PL2303",
}


def list_ports(likely_first: bool = True) -> list[SerialPortInfo]:
    """Every serial port present, boards most likely to be ours first."""
    try:
        from serial.tools import list_ports as pyserial_ports
    except ImportError:  # pragma: no cover - dependency is declared
        return []

    ports = [
        SerialPortInfo(
            device=p.device,
            description=(p.description or "").strip(),
            manufacturer=(p.manufacturer or "").strip(),
            vid=p.vid,
            pid=p.pid,
        )
        for p in pyserial_ports.comports()
    ]

    if likely_first:
        ports.sort(
            key=lambda p: (not is_likely_board(p), is_bluetooth(p), _port_number(p.device))
        )
    else:
        ports.sort(key=lambda p: _port_number(p.device))
    return ports


def is_likely_board(port: SerialPortInfo) -> bool:
    """True for USB-serial adapters of the kind Arduino boards use."""
    if is_bluetooth(port):
        return False
    if port.vid in _KNOWN_VENDORS:
        return True
    haystack = f"{port.description} {port.manufacturer}".lower()
    return any(
        needle in haystack
        for needle in ("arduino", "ch340", "ch910", "cp210", "ftdi", "usb-serial", "usb serial")
    )


def is_bluetooth(port: SerialPortInfo) -> bool:
    """True for Windows' Bluetooth serial ports.

    Worth singling out: opening one blocks indefinitely when no device is
    paired on the other end, so avrdude hangs rather than failing. They sit at
    the bottom of the list and the UI warns before using one.
    """
    haystack = f"{port.description} {port.manufacturer}".lower()
    return "bluetooth" in haystack


def vendor_name(port: SerialPortInfo) -> str:
    return _KNOWN_VENDORS.get(port.vid or -1, "")


def find(device: str) -> SerialPortInfo | None:
    wanted = device.strip().upper()
    for port in list_ports(likely_first=False):
        if port.device.upper() == wanted:
            return port
    return None


def _port_number(device: str) -> tuple[int, str]:
    """Sort COM2 before COM10, which a plain string sort gets wrong."""
    digits = "".join(ch for ch in device if ch.isdigit())
    return (int(digits) if digits else 9999, device)
