"""COM set-up for the backend, plus the GUID structure the ctypes modules (wlan, brightness) pass to Windows.

COM in this process is multithreaded (MTA): pywinrt's blocking calls refuse to run on a single-threaded apartment.
comtypes / pycaw initialise COM on import with sys.coinit_flags, which defaults to single-threaded, so it is set
here, and modules that use comtypes import this module first.
"""
import ctypes
import sys
import uuid
from ctypes import c_int32, c_long, wintypes

sys.coinit_flags = 0  # COINIT_MULTITHREADED

RPC_E_CHANGED_MODE = -2147417850  # 0x80010106
_combase = ctypes.WinDLL("combase")
_combase.RoInitialize.argtypes = [c_int32]
_combase.RoInitialize.restype = c_long


def sig(func, restype, *argtypes):
    """Declare a ctypes function's return and argument types."""
    func.restype, func.argtypes = restype, list(argtypes)


def check(rc, what):
    """Raise OSError for a Windows error code (0 = success), e.g. check(WlanScan(...), "WlanScan")."""
    if rc:
        raise OSError(rc, what + " failed")


class GUID(ctypes.Structure):
    _fields_ = [("Data1", ctypes.c_uint32), ("Data2", ctypes.c_uint16), ("Data3", ctypes.c_uint16),
                ("Data4", ctypes.c_ubyte * 8)]

    @classmethod
    def of(cls, text):
        return cls.from_buffer_copy(uuid.UUID(text).bytes_le)

    def __str__(self):
        return str(uuid.UUID(bytes_le=bytes(self))).upper()


def high_qos():
    """Opt the calling thread out of Windows power throttling (EcoQoS).

    The plugin process has no window, so Windows treats it as background work and runs it on the slow efficiency
    cores: every call took 3-5x longer. Only this one worker thread is changed, and it only works while the Quick
    Access menu is polling."""
    class _PPT(ctypes.Structure):
        _fields_ = [("Version", wintypes.ULONG), ("ControlMask", wintypes.ULONG), ("StateMask", wintypes.ULONG)]
    k = ctypes.WinDLL("kernel32")
    k.GetCurrentThread.restype = wintypes.HANDLE
    k.SetThreadInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    k.SetThreadInformation.restype = wintypes.BOOL
    p = _PPT(1, 1, 0)  # version 1, control EXECUTION_SPEED, state 0 = never throttle
    return bool(k.SetThreadInformation(k.GetCurrentThread(), 3, ctypes.byref(p), ctypes.sizeof(p)))  # ThreadPowerThrottling


def init_mta():
    """Initialise COM + WinRT as multithreaded on the calling thread (idempotent)."""
    hr = _combase.RoInitialize(1)  # RO_INIT_MULTITHREADED
    if hr < 0 and hr != RPC_E_CHANGED_MODE:
        raise OSError("RoInitialize failed: HRESULT 0x%08X" % (hr & 0xFFFFFFFF))


def init_worker():
    init_mta()
    try:
        high_qos()
    except Exception:  # noqa: BLE001 - only a speed hint
        pass
