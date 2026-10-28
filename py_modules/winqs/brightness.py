"""Built-in display brightness.

Read/write path: the "Display brightness" power setting of the active power scheme
(the same value the Windows brightness slider stores), applied with
PowerSetActiveScheme. Reading also tries the panel's actual level through the video
IOCTL on \\\\.\\LCD, which reflects changes made by other tools.
"""
import ctypes
from ctypes import POINTER, byref, c_void_p, wintypes

from winrt.windows.system.power import PowerManager, PowerSupplyStatus

from .com import GUID, check, sig

_powr = ctypes.WinDLL("powrprof")
_k32 = ctypes.WinDLL("kernel32", use_last_error=True)

GUID_VIDEO_SUBGROUP = "7516B95F-F776-4464-8C53-06167F40CC99"
GUID_VIDEO_BRIGHTNESS = "ADED5E82-B909-4619-9949-F5D71DAC0BCB"

sig(_powr.PowerGetActiveScheme, wintypes.DWORD, c_void_p, POINTER(POINTER(GUID)))
sig(_powr.PowerSetActiveScheme, wintypes.DWORD, c_void_p, POINTER(GUID))
for _name in ("PowerReadACValueIndex", "PowerReadDCValueIndex"):
    getattr(_powr, _name).argtypes = [c_void_p, POINTER(GUID), POINTER(GUID), POINTER(GUID), POINTER(wintypes.DWORD)]
    getattr(_powr, _name).restype = wintypes.DWORD
for _name in ("PowerWriteACValueIndex", "PowerWriteDCValueIndex"):
    getattr(_powr, _name).argtypes = [c_void_p, POINTER(GUID), POINTER(GUID), POINTER(GUID), wintypes.DWORD]
    getattr(_powr, _name).restype = wintypes.DWORD
sig(_k32.LocalFree, c_void_p, c_void_p)


def _on_ac():
    """The AC and battery brightness values are stored separately; a weak charger still counts as AC."""
    return PowerManager.power_supply_status != PowerSupplyStatus.NOT_PRESENT


def _active_scheme():
    p = POINTER(GUID)()
    check(_powr.PowerGetActiveScheme(None, byref(p)), "PowerGetActiveScheme")
    g = GUID()
    ctypes.memmove(byref(g), p, ctypes.sizeof(GUID))
    _k32.LocalFree(p)
    return g


def get_power_setting():
    scheme, sub, setting = _active_scheme(), GUID.of(GUID_VIDEO_SUBGROUP), GUID.of(GUID_VIDEO_BRIGHTNESS)
    v = wintypes.DWORD()
    fn = _powr.PowerReadACValueIndex if _on_ac() else _powr.PowerReadDCValueIndex
    check(fn(None, byref(scheme), byref(sub), byref(setting), byref(v)), "PowerRead*ValueIndex")
    return int(v.value)


# --- actual panel level through the video miniport IOCTL ---------------------------------
IOCTL_VIDEO_QUERY_DISPLAY_BRIGHTNESS = 0x00230498


class DISPLAY_BRIGHTNESS(ctypes.Structure):
    _fields_ = [("ucDisplayPolicy", ctypes.c_ubyte), ("ucACBrightness", ctypes.c_ubyte), ("ucDCBrightness", ctypes.c_ubyte)]


sig(_k32.CreateFileW, wintypes.HANDLE,
    wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE)
sig(_k32.DeviceIoControl, wintypes.BOOL,
    wintypes.HANDLE, wintypes.DWORD, c_void_p, wintypes.DWORD, c_void_p, wintypes.DWORD, POINTER(wintypes.DWORD),
    c_void_p)
_k32.CloseHandle.argtypes = [wintypes.HANDLE]
INVALID_HANDLE = wintypes.HANDLE(-1).value


def get_panel_level():
    h = _k32.CreateFileW("\\\\.\\LCD", 0, 3, None, 3, 0, None)  # no access rights needed for query
    if not h or h == INVALID_HANDLE:
        return None
    try:
        db, ret = DISPLAY_BRIGHTNESS(), wintypes.DWORD()
        if not _k32.DeviceIoControl(h, IOCTL_VIDEO_QUERY_DISPLAY_BRIGHTNESS, None, 0, byref(db), ctypes.sizeof(db), byref(ret), None):
            return None
        return int(db.ucACBrightness if _on_ac() else db.ucDCBrightness)
    finally:
        _k32.CloseHandle(h)


def get_level():
    """Current brightness 0-100, or None when the panel is not controllable."""
    level = get_panel_level()
    if level is not None:
        return level
    try:
        return get_power_setting()
    except OSError:
        return None


def set_level(value):
    value = max(0, min(100, int(value)))
    scheme, sub, setting = _active_scheme(), GUID.of(GUID_VIDEO_SUBGROUP), GUID.of(GUID_VIDEO_BRIGHTNESS)
    fn = _powr.PowerWriteACValueIndex if _on_ac() else _powr.PowerWriteDCValueIndex
    check(fn(None, byref(scheme), byref(sub), byref(setting), value), "PowerWrite*ValueIndex")
    check(_powr.PowerSetActiveScheme(None, byref(scheme)), "PowerSetActiveScheme")
    return value
