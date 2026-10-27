"""Minimal COM / WinRT helpers on top of ctypes (no comtypes, no pywinrt).

All COM interface calls go through `vcall`, which invokes a method by its vtable
index. Every caller documents the index it relies on.
"""
import ctypes
import time
import uuid
from ctypes import POINTER, byref, c_int32, c_long, c_uint32, c_ulong, c_void_p, wintypes


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
_combase.WindowsCreateString.argtypes = [wintypes.LPCWSTR, c_uint32, POINTER(c_void_p)]
_combase.WindowsCreateString.restype = c_long
_combase.WindowsDeleteString.argtypes = [c_void_p]
_combase.WindowsDeleteString.restype = c_long
_combase.WindowsGetStringRawBuffer.argtypes = [c_void_p, POINTER(c_uint32)]
_combase.WindowsGetStringRawBuffer.restype = wintypes.LPCWSTR
_combase.RoGetActivationFactory.argtypes = [c_void_p, POINTER(GUID), POINTER(c_void_p)]
_combase.RoGetActivationFactory.restype = c_long

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


class HString:
    def __init__(self, text):
        self.h = c_void_p()
        check(_combase.WindowsCreateString(text, len(text), byref(self.h)), "WindowsCreateString")

    def __enter__(self):
        return self.h

    def __exit__(self, *exc):
        _combase.WindowsDeleteString(self.h)


def hstring_to_str(h):
    if not h:
        return ""
    n = c_uint32()
    s = _combase.WindowsGetStringRawBuffer(h, byref(n)) or ""
    _combase.WindowsDeleteString(h)
    return s


def activation_factory(class_name, iid_text):
    out = c_void_p()
    iid = GUID.of(iid_text)
    with HString(class_name) as h:
        check(_combase.RoGetActivationFactory(h, byref(iid), byref(out)), "RoGetActivationFactory(%s)" % class_name)
    return out


IID_IAsyncInfo = "00000036-0000-0000-C000-000000000046"


def await_async(op, timeout=20.0):
    """Block until a WinRT IAsyncOperation/IAsyncAction finishes.

    IAsyncInfo vtable: 0-5 IInspectable, 6 get_Id, 7 get_Status, 8 get_ErrorCode.
    AsyncStatus: 0 Started, 1 Completed, 2 Canceled, 3 Error.
    """
    info = qi(op, IID_IAsyncInfo)
    try:
        deadline = time.monotonic() + timeout
        status = c_int32()
        delay = 0.002  # quick operations finish within a few ms; slow ones (radio switch ~1-2 s) back off to 50 ms
        while True:
            check(vcall(info, 7, [POINTER(c_int32)], byref(status)), "IAsyncInfo.get_Status")
            if status.value == 1:
                return
            if status.value == 3:
                code = c_long()
                vcall(info, 8, [POINTER(c_long)], byref(code))
                raise ComError(code.value, "async operation")
            if status.value == 2:
                raise RuntimeError("async operation canceled")
            if time.monotonic() > deadline:
                raise TimeoutError("async operation timed out")
            time.sleep(delay)
            delay = min(delay * 1.5, 0.05)
    finally:
        release(info)


def async_result_int(op):
    """IAsyncOperation<enum/int>: vtable 8 = GetResults(out int)."""
    r = c_int32()
    check(vcall(op, 8, [POINTER(c_int32)], byref(r)), "IAsyncOperation.GetResults")
    return r.value


def async_result_ptr(op):
    r = c_void_p()
    check(vcall(op, 8, [POINTER(c_void_p)], byref(r)), "IAsyncOperation.GetResults")
    return r
