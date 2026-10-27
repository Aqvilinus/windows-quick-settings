"""Current refresh rate of the primary display (user32 EnumDisplaySettingsEx), read only.

The Frame Limit slider goes up to it. The plugin never changes the refresh rate (see CLAUDE.md).
"""
import ctypes
from ctypes import byref, sizeof, wintypes

_user32 = ctypes.WinDLL("user32")

ENUM_CURRENT_SETTINGS = 0xFFFFFFFF


class DEVMODEW(ctypes.Structure):
    _fields_ = [
        ("dmDeviceName", wintypes.WCHAR * 32), ("dmSpecVersion", wintypes.WORD), ("dmDriverVersion", wintypes.WORD),
        ("dmSize", wintypes.WORD), ("dmDriverExtra", wintypes.WORD), ("dmFields", wintypes.DWORD),
        ("dmPositionX", wintypes.LONG), ("dmPositionY", wintypes.LONG),
        ("dmDisplayOrientation", wintypes.DWORD), ("dmDisplayFixedOutput", wintypes.DWORD),
        ("dmColor", ctypes.c_short), ("dmDuplex", ctypes.c_short), ("dmYResolution", ctypes.c_short),
        ("dmTTOption", ctypes.c_short), ("dmCollate", ctypes.c_short), ("dmFormName", wintypes.WCHAR * 32),
        ("dmLogPixels", wintypes.WORD), ("dmBitsPerPel", wintypes.DWORD), ("dmPelsWidth", wintypes.DWORD),
        ("dmPelsHeight", wintypes.DWORD), ("dmDisplayFlags", wintypes.DWORD), ("dmDisplayFrequency", wintypes.DWORD),
        ("dmICMMethod", wintypes.DWORD), ("dmICMIntent", wintypes.DWORD), ("dmMediaType", wintypes.DWORD),
        ("dmDitherType", wintypes.DWORD), ("dmReserved1", wintypes.DWORD), ("dmReserved2", wintypes.DWORD),
        ("dmPanningWidth", wintypes.DWORD), ("dmPanningHeight", wintypes.DWORD),
    ]


_user32.EnumDisplaySettingsExW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(DEVMODEW), wintypes.DWORD]
_user32.EnumDisplaySettingsExW.restype = wintypes.BOOL


def info():
    """{'hz': current refresh rate}."""
    dm = DEVMODEW()
    dm.dmSize = sizeof(DEVMODEW)
    if not _user32.EnumDisplaySettingsExW(None, ENUM_CURRENT_SETTINGS, byref(dm), 0):
        raise OSError("EnumDisplaySettingsEx failed")
    return {"hz": int(dm.dmDisplayFrequency)}
