"""Paired Bluetooth devices via bthprops (classic Bluetooth API)."""
import ctypes
from ctypes import POINTER, byref, c_void_p, wintypes


class SYSTEMTIME(ctypes.Structure):
    _fields_ = [(n, wintypes.WORD) for n in ("wYear", "wMonth", "wDayOfWeek", "wDay", "wHour", "wMinute", "wSecond", "wMilliseconds")]


class BLUETOOTH_DEVICE_SEARCH_PARAMS(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("fReturnAuthenticated", wintypes.BOOL),
        ("fReturnRemembered", wintypes.BOOL),
        ("fReturnUnknown", wintypes.BOOL),
        ("fReturnConnected", wintypes.BOOL),
        ("fIssueInquiry", wintypes.BOOL),
        ("cTimeoutMultiplier", ctypes.c_ubyte),
        ("hRadio", wintypes.HANDLE),
    ]


class BLUETOOTH_DEVICE_INFO(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("Address", ctypes.c_ulonglong),
        ("ulClassofDevice", wintypes.ULONG),
        ("fConnected", wintypes.BOOL),
        ("fRemembered", wintypes.BOOL),
        ("fAuthenticated", wintypes.BOOL),
        ("stLastSeen", SYSTEMTIME),
        ("stLastUsed", SYSTEMTIME),
        ("szName", wintypes.WCHAR * 248),
    ]


_bt = ctypes.WinDLL("bthprops.cpl", use_last_error=True)
_bt.BluetoothFindFirstDevice.argtypes = [POINTER(BLUETOOTH_DEVICE_SEARCH_PARAMS), POINTER(BLUETOOTH_DEVICE_INFO)]
_bt.BluetoothFindFirstDevice.restype = c_void_p
_bt.BluetoothFindNextDevice.argtypes = [c_void_p, POINTER(BLUETOOTH_DEVICE_INFO)]
_bt.BluetoothFindNextDevice.restype = wintypes.BOOL
_bt.BluetoothFindDeviceClose.argtypes = [c_void_p]
_bt.BluetoothFindDeviceClose.restype = wintypes.BOOL

MAJOR = {1: "computer", 2: "phone", 3: "network", 4: "audio", 5: "peripheral", 6: "imaging", 7: "wearable", 8: "toy", 9: "health"}


def paired_devices():
    params = BLUETOOTH_DEVICE_SEARCH_PARAMS()
    params.dwSize = ctypes.sizeof(params)
    params.fReturnAuthenticated = True
    params.fReturnRemembered = True
    params.fReturnConnected = True
    params.fReturnUnknown = False
    params.fIssueInquiry = False
    info = BLUETOOTH_DEVICE_INFO()
    info.dwSize = ctypes.sizeof(info)
    h = _bt.BluetoothFindFirstDevice(byref(params), byref(info))
    if not h:
        return []  # no radio, radio off, or no devices
    out, seen = [], set()
    try:
        while True:
            if info.fAuthenticated or info.fRemembered:
                addr = "%012X" % info.Address
                if addr not in seen:
                    seen.add(addr)
                    major = (info.ulClassofDevice >> 8) & 0x1F
                    out.append({
                        "address": addr,
                        "name": info.szName or addr,
                        "connected": bool(info.fConnected),
                        "type": MAJOR.get(major, "other"),
                    })
            info = BLUETOOTH_DEVICE_INFO()
            info.dwSize = ctypes.sizeof(info)
            if not _bt.BluetoothFindNextDevice(h, byref(info)):
                break
    finally:
        _bt.BluetoothFindDeviceClose(h)
    out.sort(key=lambda d: (not d["connected"], d["name"].lower()))
    return out
