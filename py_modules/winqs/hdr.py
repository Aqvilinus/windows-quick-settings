"""HDR on/off for the built-in display through the Windows display configuration API (user32, no admin).

Reads DISPLAYCONFIG_DEVICE_INFO_GET_ADVANCED_COLOR_INFO_2 (type 15, Windows 11 24H2+) and falls back to
GET_ADVANCED_COLOR_INFO (type 9). Writes SET_HDR_STATE (type 16), falling back to SET_ADVANCED_COLOR_STATE
(type 10). The change is read back, as Windows can refuse it (e.g. on battery saver or by policy).
"""
import ctypes
from ctypes import byref, sizeof, wintypes

_user32 = ctypes.WinDLL("user32")

ERROR_INSUFFICIENT_BUFFER = 122
QDC_ONLY_ACTIVE_PATHS = 0x2
OUTPUT_TECH_INTERNAL = 0x80000000
GET_ADVANCED_COLOR_INFO, SET_ADVANCED_COLOR_STATE = 9, 10
GET_ADVANCED_COLOR_INFO_2, SET_HDR_STATE = 15, 16
COLOR_MODE_HDR = 2


class LUID(ctypes.Structure):
    _fields_ = [("LowPart", wintypes.DWORD), ("HighPart", wintypes.LONG)]


class PATH_SOURCE(ctypes.Structure):
    _fields_ = [("adapterId", LUID), ("id", ctypes.c_uint32), ("modeInfoIdx", ctypes.c_uint32),
                ("statusFlags", ctypes.c_uint32)]


class RATIONAL(ctypes.Structure):
    _fields_ = [("Numerator", ctypes.c_uint32), ("Denominator", ctypes.c_uint32)]


class PATH_TARGET(ctypes.Structure):
    _fields_ = [("adapterId", LUID), ("id", ctypes.c_uint32), ("modeInfoIdx", ctypes.c_uint32),
                ("outputTechnology", ctypes.c_uint32), ("rotation", ctypes.c_uint32), ("scaling", ctypes.c_uint32),
                ("refreshRate", RATIONAL), ("scanLineOrdering", ctypes.c_uint32), ("targetAvailable", wintypes.BOOL),
                ("statusFlags", ctypes.c_uint32)]


class PATH_INFO(ctypes.Structure):
    _fields_ = [("sourceInfo", PATH_SOURCE), ("targetInfo", PATH_TARGET), ("flags", ctypes.c_uint32)]


class MODE_INFO(ctypes.Structure):
    _fields_ = [("infoType", ctypes.c_uint32), ("id", ctypes.c_uint32), ("adapterId", LUID),
                ("data", ctypes.c_byte * 48)]


class HEADER(ctypes.Structure):
    _fields_ = [("type", ctypes.c_uint32), ("size", ctypes.c_uint32), ("adapterId", LUID), ("id", ctypes.c_uint32)]


class COLOR_INFO_2(ctypes.Structure):
    _fields_ = [("header", HEADER), ("value", ctypes.c_uint32), ("colorEncoding", ctypes.c_uint32),
                ("bitsPerColorChannel", ctypes.c_uint32), ("activeColorMode", ctypes.c_uint32)]


class COLOR_INFO(ctypes.Structure):
    _fields_ = [("header", HEADER), ("value", ctypes.c_uint32), ("colorEncoding", ctypes.c_uint32),
                ("bitsPerColorChannel", ctypes.c_uint32)]


class SET_STATE(ctypes.Structure):
    _fields_ = [("header", HEADER), ("value", ctypes.c_uint32)]


assert sizeof(PATH_INFO) == 72 and sizeof(MODE_INFO) == 64 and sizeof(COLOR_INFO_2) == 36 and sizeof(SET_STATE) == 24

_user32.GetDisplayConfigBufferSizes.argtypes = [ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint32), ctypes.POINTER(ctypes.c_uint32)]
_user32.GetDisplayConfigBufferSizes.restype = ctypes.c_long
_user32.QueryDisplayConfig.argtypes = [ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint32), ctypes.c_void_p,
                                       ctypes.POINTER(ctypes.c_uint32), ctypes.c_void_p, ctypes.c_void_p]
_user32.QueryDisplayConfig.restype = ctypes.c_long
_user32.DisplayConfigGetDeviceInfo.argtypes = [ctypes.c_void_p]
_user32.DisplayConfigGetDeviceInfo.restype = ctypes.c_long
_user32.DisplayConfigSetDeviceInfo.argtypes = [ctypes.c_void_p]
_user32.DisplayConfigSetDeviceInfo.restype = ctypes.c_long


def _target():
    """(adapterId, target id) of the built-in panel, else of the first active display."""
    t = active_path().targetInfo
    return t.adapterId, t.id


def active_path():
    """DisplayConfig path (PATH_INFO) of the built-in panel, else of the first active display."""
    for _ in range(3):  # the path count can change between the two calls
        n_path, n_mode = ctypes.c_uint32(), ctypes.c_uint32()
        rc = _user32.GetDisplayConfigBufferSizes(QDC_ONLY_ACTIVE_PATHS, byref(n_path), byref(n_mode))
        if rc:
            raise OSError(rc, "GetDisplayConfigBufferSizes failed")
        paths, modes = (PATH_INFO * n_path.value)(), (MODE_INFO * n_mode.value)()
        rc = _user32.QueryDisplayConfig(QDC_ONLY_ACTIVE_PATHS, byref(n_path), paths, byref(n_mode), modes, None)
        if rc == ERROR_INSUFFICIENT_BUFFER:
            continue
        if rc:
            raise OSError(rc, "QueryDisplayConfig failed")
        active = paths[: n_path.value]
        if not active:
            raise RuntimeError("no active display")
        return next((x for x in active if x.targetInfo.outputTechnology == OUTPUT_TECH_INTERNAL), active[0])
    raise RuntimeError("display configuration kept changing")


def state():
    """{'supported', 'on'} for HDR on the built-in display."""
    adapter, tid = _target()
    info2 = COLOR_INFO_2(HEADER(GET_ADVANCED_COLOR_INFO_2, sizeof(COLOR_INFO_2), adapter, tid))
    if _user32.DisplayConfigGetDeviceInfo(byref(info2)) == 0:
        v = info2.value
        supported = bool(v & (1 << 4))                      # highDynamicRangeSupported
        on = bool(v & (1 << 5)) or info2.activeColorMode == COLOR_MODE_HDR  # highDynamicRangeUserEnabled
        return {"supported": supported, "on": on and supported}
    info = COLOR_INFO(HEADER(GET_ADVANCED_COLOR_INFO, sizeof(COLOR_INFO), adapter, tid))
    rc = _user32.DisplayConfigGetDeviceInfo(byref(info))
    if rc:
        raise OSError(rc, "DisplayConfigGetDeviceInfo failed")
    return {"supported": bool(info.value & 1), "on": bool(info.value & 2)}


def set_enabled(on):
    """Switch HDR. Windows' call blocks for about a second and the new state can show a moment later; main.py runs
    it on a thread of its own and confirms it with state(), so the worker thread isn't held up meanwhile."""
    adapter, tid = _target()
    st = SET_STATE(HEADER(SET_HDR_STATE, sizeof(SET_STATE), adapter, tid), 1 if on else 0)
    if _user32.DisplayConfigSetDeviceInfo(byref(st)) != 0:
        st = SET_STATE(HEADER(SET_ADVANCED_COLOR_STATE, sizeof(SET_STATE), adapter, tid), 1 if on else 0)
        rc = _user32.DisplayConfigSetDeviceInfo(byref(st))
        if rc:
            raise OSError(rc, "DisplayConfigSetDeviceInfo failed")
    return state()
