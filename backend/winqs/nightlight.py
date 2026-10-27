"""Windows Night light on/off.

Windows has no public API for Night light. Its on/off state lives in a CloudStore
blob that the shell watches and applies immediately; every known tool toggles it by
rewriting that blob. Layout (all multi-byte numbers are unsigned LEB128):

  43 42 01 00 | 0A 02 01 00 | 2A 06 <unix seconds> | 2A 2B 0E <len> <inner> | 00 00 00
  inner:  43 42 01 00 | [10 00 when ON] | D0 0A 02 | C6 14 <FILETIME of change> | 00

The blob is rebuilt from scratch with the current time, so a never-used (13-byte)
default value works too.
"""
import time
import winreg

KEY = (r"Software\Microsoft\Windows\CurrentVersion\CloudStore\Store\DefaultAccount\Current"
       r"\default$windows.data.bluelightreduction.bluelightreductionstate"
       r"\windows.data.bluelightreduction.bluelightreductionstate")
HEADER = bytes([0x43, 0x42, 0x01, 0x00])


def _leb128(n):
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)


def _read():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, KEY) as k:
            data, kind = winreg.QueryValueEx(k, "Data")
            return bytes(data) if kind == winreg.REG_BINARY else None
    except OSError:
        return None


def is_enabled():
    """True / False, or None when the blob is missing or has an unknown layout."""
    data = _read()
    if data is None:
        return None
    marker = bytes([0x2A, 0x2B, 0x0E])
    i = data.find(marker)
    if i < 0:
        return False if data.startswith(HEADER) else None  # never-used default value = off
    inner = data[i + 4:]
    if not inner.startswith(HEADER):
        return None
    return inner[4:6] == bytes([0x10, 0x00])


def build(on, now=None):
    now = time.time() if now is None else now
    unix = int(now)
    filetime = (unix + 11644473600) * 10_000_000
    inner = HEADER + (bytes([0x10, 0x00]) if on else b"") + bytes([0xD0, 0x0A, 0x02, 0xC6, 0x14]) + _leb128(filetime) + b"\x00"
    return (HEADER + bytes([0x0A, 0x02, 0x01, 0x00, 0x2A, 0x06]) + _leb128(unix)
            + bytes([0x2A, 0x2B, 0x0E, len(inner)]) + inner + b"\x00\x00\x00")


def set_enabled(on):
    blob = build(bool(on))
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, KEY, 0, winreg.KEY_SET_VALUE) as k:
        winreg.SetValueEx(k, "Data", 0, winreg.REG_BINARY, blob)
    return bool(on)
