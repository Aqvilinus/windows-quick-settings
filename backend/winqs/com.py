"""Minimal COM helpers on top of ctypes (WinRT goes through pywinrt in py_modules).

All COM interface calls go through `vcall`, which invokes a method by its vtable
index. Every caller documents the index it relies on.
"""
import ctypes
import uuid
from ctypes import POINTER, byref, c_int32, c_long, c_ulong, c_void_p, wintypes


class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", ctypes.c_uint32),
        ("Data2", ctypes.c_uint16),
        ("Data3", ctypes.c_uint16),
        ("Data4", ctypes.c_ubyte * 8),
    ]

    @classmethod
    def of(cls, text):
        g = cls()
        ctypes.memmove(byref(g), uuid.UUID(text).bytes_le, 16)
        return g

    def __str__(self):
        return str(uuid.UUID(bytes_le=bytes(ctypes.string_at(ctypes.addressof(self), 16)))).upper()


class ComError(OSError):
    def __init__(self, hr, where=""):
        self.hr = hr & 0xFFFFFFFF
        super().__init__("%s failed: HRESULT 0x%08X" % (where or "COM call", self.hr))


def check(hr, where=""):
    if hr < 0:
        raise ComError(hr, where)
    return hr


def vcall(ptr, index, argtypes, *args, restype=c_long):
    """Call method #index of the COM object `ptr` (a c_void_p or int)."""
    p = ptr.value if isinstance(ptr, c_void_p) else ptr
    if not p:
        raise ValueError("null COM pointer")
    vtbl = ctypes.cast(p, POINTER(POINTER(c_void_p))).contents
    fn = ctypes.WINFUNCTYPE(restype, c_void_p, *argtypes)(vtbl[index])
    return fn(p, *args)


def release(ptr):
    p = ptr.value if isinstance(ptr, c_void_p) else ptr
    if p:
        vcall(p, 2, [], restype=c_ulong)


def qi(ptr, iid_text):
    out = c_void_p()
    iid = GUID.of(iid_text)
    check(vcall(ptr, 0, [POINTER(GUID), POINTER(c_void_p)], byref(iid), byref(out)), "QueryInterface")
    return out


_ole32 = ctypes.WinDLL("ole32")
_combase = ctypes.WinDLL("combase")

_ole32.CoInitializeEx.argtypes = [c_void_p, wintypes.DWORD]
_ole32.CoInitializeEx.restype = c_long
_ole32.CoCreateInstance.argtypes = [POINTER(GUID), c_void_p, wintypes.DWORD, POINTER(GUID), POINTER(c_void_p)]
_ole32.CoCreateInstance.restype = c_long
_ole32.PropVariantClear.argtypes = [c_void_p]
_ole32.PropVariantClear.restype = c_long

_combase.RoInitialize.argtypes = [c_int32]
_combase.RoInitialize.restype = c_long

RPC_E_CHANGED_MODE = -2147417850  # 0x80010106


def high_qos():
    """Opt the calling thread out of Windows power throttling (EcoQoS).

    The plugin process has no window, so Windows treats it as background work and runs it on
    the slow efficiency cores: every call took 3-5x longer. Only this one worker thread is
    changed, and it only works while the Quick Access menu is polling."""
    class _PPT(ctypes.Structure):
        _fields_ = [("Version", wintypes.ULONG), ("ControlMask", wintypes.ULONG), ("StateMask", wintypes.ULONG)]
    k = ctypes.WinDLL("kernel32")
    k.GetCurrentThread.restype = wintypes.HANDLE
    k.SetThreadInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    k.SetThreadInformation.restype = wintypes.BOOL
    p = _PPT(1, 1, 0)  # version 1, control EXECUTION_SPEED, state 0 = never throttle
    return bool(k.SetThreadInformation(k.GetCurrentThread(), 3, ctypes.byref(p), ctypes.sizeof(p)))  # ThreadPowerThrottling


def init_worker():
    init_mta()
    try:
        high_qos()
    except Exception:  # noqa: BLE001 - only a speed hint
        pass


def init_mta():
    """Initialise COM + WinRT as multithreaded on the calling thread (idempotent)."""
    hr = _combase.RoInitialize(1)  # RO_INIT_MULTITHREADED
    if hr < 0 and hr != RPC_E_CHANGED_MODE:
        raise ComError(hr, "RoInitialize")


def co_create(clsid_text, iid_text, ctx=23):  # CLSCTX_ALL
    out = c_void_p()
    clsid, iid = GUID.of(clsid_text), GUID.of(iid_text)
    check(_ole32.CoCreateInstance(byref(clsid), None, ctx, byref(iid), byref(out)), "CoCreateInstance")
    return out


def propvariant_clear(buf):
    _ole32.PropVariantClear(buf)
