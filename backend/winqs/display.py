"""Refresh rate of the primary display through user32 (EnumDisplaySettingsEx / ChangeDisplaySettingsEx).

Only the refresh rate changes; resolution and colour depth stay as they are. The new rate is
saved to the registry (CDS_UPDATEREGISTRY), the same as picking it in Windows display settings.
No administrator rights are needed.
"""
import ctypes
from ctypes import byref, sizeof, wintypes

_user32 = ctypes.WinDLL("user32", use_last_error=True)

ENUM_CURRENT_SETTINGS = -1
DM_DISPLAYFREQUENCY = 0x00400000
DM_PELSWIDTH = 0x00080000
DM_PELSHEIGHT = 0x00100000
CDS_UPDATEREGISTRY = 0x00000001
DISP_CHANGE = {0: "ok", 1: "restart required", -1: "failed", -2: "bad mode", -3: "not updated", -4: "bad flags",
               -5: "bad parameter", -6: "bad dual view"}


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


assert sizeof(DEVMODEW) == 220

_user32.EnumDisplaySettingsExW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(DEVMODEW), wintypes.DWORD]
_user32.EnumDisplaySettingsExW.restype = wintypes.BOOL
_user32.ChangeDisplaySettingsExW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(DEVMODEW), wintypes.HWND,
                                            wintypes.DWORD, ctypes.c_void_p]
_user32.ChangeDisplaySettingsExW.restype = wintypes.LONG


def _mode(index):
    dm = DEVMODEW()
    dm.dmSize = sizeof(DEVMODEW)
    if not _user32.EnumDisplaySettingsExW(None, index & 0xFFFFFFFF, byref(dm), 0):
        return None
    return dm


def current():
    dm = _mode(ENUM_CURRENT_SETTINGS)
    if dm is None:
        raise OSError("EnumDisplaySettingsEx failed")
    return dm


_rates_cache = {}  # (device, width, height, bpp) -> sorted rates; the mode list only changes with the display


def _rates(cur):
    key = (cur.dmDeviceName, int(cur.dmPelsWidth), int(cur.dmPelsHeight), int(cur.dmBitsPerPel))
    if key not in _rates_cache:
        rates = set()
        i = 0
        while True:
            dm = _mode(i)
            if dm is None:
                break
            if (dm.dmPelsWidth, dm.dmPelsHeight, dm.dmBitsPerPel) == key[1:] and dm.dmDisplayFrequency > 1:
                rates.add(int(dm.dmDisplayFrequency))
            i += 1
        _rates_cache[key] = sorted(rates)
    return _rates_cache[key]


def info():
    """{'hz': current rate, 'rates': rates available at the current resolution, 'width', 'height'}."""
    cur = current()
    return {"hz": int(cur.dmDisplayFrequency), "rates": list(_rates(cur)),
            "width": int(cur.dmPelsWidth), "height": int(cur.dmPelsHeight)}


def set_rate(hz):
    hz = int(hz)
    cur = current()
    if int(cur.dmDisplayFrequency) == hz:
        return hz
    if hz not in info()["rates"]:
        raise ValueError("%d Hz is not available at %dx%d" % (hz, cur.dmPelsWidth, cur.dmPelsHeight))
    cur.dmDisplayFrequency = hz
    cur.dmFields = DM_DISPLAYFREQUENCY | DM_PELSWIDTH | DM_PELSHEIGHT
    r = _user32.ChangeDisplaySettingsExW(None, byref(cur), None, CDS_UPDATEREGISTRY, None)
    if r != 0:
        raise OSError("ChangeDisplaySettingsEx: %s (%d)" % (DISP_CHANGE.get(r, "error"), r))
    return int(current().dmDisplayFrequency)
