"""Wi-Fi / Bluetooth radio on-off through WinRT Windows.Devices.Radios, called via raw ctypes.

IRadioStatics vtable: 0-5 IInspectable, 6 GetRadiosAsync, 7 GetDeviceSelector,
                      8 FromIdAsync, 9 RequestAccessAsync
IRadio vtable:        0-5 IInspectable, 6 SetStateAsync, 7 add_StateChanged,
                      8 remove_StateChanged, 9 get_State, 10 get_Name, 11 get_Kind
IVectorView<T>:       0-5 IInspectable, 6 GetAt, 7 get_Size
"""
import time
from ctypes import POINTER, byref, c_int32, c_uint32, c_void_p

from .com import (activation_factory, async_result_int, async_result_ptr, await_async, check,
                  hstring_to_str, release, vcall)

RADIO_CLASS = "Windows.Devices.Radios.Radio"
IID_IRadioStatics = "5FB6A12E-67CB-46AE-AAE9-65919F86EFF4"

KIND = {0: "other", 1: "wifi", 2: "mobile", 3: "bluetooth", 4: "fm"}
STATE = {0: "unknown", 1: "on", 2: "off", 3: "disabled"}
ACCESS = {0: "unspecified", 1: "allowed", 2: "denied_by_user", 3: "denied_by_system"}

_statics = None
_access = None
_cache = {}          # kind -> IRadio pointer we own (one reference)
_cache_time = 0.0
CACHE_SECONDS = 30   # re-enumerate radios now and then (adapter added/removed)


def _get_statics():
    global _statics
    if _statics is None:
        _statics = activation_factory(RADIO_CLASS, IID_IRadioStatics)
    return _statics


def request_access():
    global _access
    if _access is None:
        op = c_void_p()
        check(vcall(_get_statics(), 9, [POINTER(c_void_p)], byref(op)), "Radio.RequestAccessAsync")
        try:
            await_async(op)
            _access = ACCESS.get(async_result_int(op), "unknown")
        finally:
            release(op)
    return _access


def _radios():
    """Return a list of (IRadio pointer, kind, state, name). Caller must release pointers."""
    op = c_void_p()
    check(vcall(_get_statics(), 6, [POINTER(c_void_p)], byref(op)), "Radio.GetRadiosAsync")
    try:
        await_async(op)
        vec = async_result_ptr(op)
    finally:
        release(op)
    out = []
    try:
        n = c_uint32()
        check(vcall(vec, 7, [POINTER(c_uint32)], byref(n)), "IVectorView.get_Size")
        for i in range(n.value):
            item = c_void_p()
            check(vcall(vec, 6, [c_uint32, POINTER(c_void_p)], i, byref(item)), "IVectorView.GetAt")
            kind, state, name = c_int32(), c_int32(), c_void_p()
            vcall(item, 11, [POINTER(c_int32)], byref(kind))
            vcall(item, 9, [POINTER(c_int32)], byref(state))
            vcall(item, 10, [POINTER(c_void_p)], byref(name))
            out.append((item, KIND.get(kind.value, "other"), STATE.get(state.value, "unknown"), hstring_to_str(name)))
    finally:
        release(vec)
    return out


def _drop_cache():
    global _cache_time
    for item in _cache.values():
        release(item)
    _cache.clear()
    _cache_time = 0.0


def _fill_cache():
    global _cache_time
    _drop_cache()
    for item, kind, _state, _name in _radios():
        if kind in ("wifi", "bluetooth") and kind not in _cache:
            _cache[kind] = item
        else:
            release(item)
    _cache_time = time.monotonic()


def get_states():
    """{'wifi': 'on'|'off'|..., 'bluetooth': ...}; a missing radio is reported as None.

    Radio objects are kept between polls and their State is read directly, which skips the
    asynchronous GetRadiosAsync enumeration (about 20 ms) on every refresh."""
    request_access()
    if not _cache_time or time.monotonic() - _cache_time > CACHE_SECONDS:
        _fill_cache()
    result = {"wifi": None, "bluetooth": None}
    state = c_int32()
    for kind, item in list(_cache.items()):
        try:
            check(vcall(item, 9, [POINTER(c_int32)], byref(state)), "IRadio.get_State")
        except Exception:  # noqa: BLE001 - stale object: enumerate again next time
            _drop_cache()
            raise
        result[kind] = STATE.get(state.value, "unknown")
    return result


def set_state(kind, on):
    """Turn the first radio of `kind` ('wifi' | 'bluetooth') on or off. Returns the access status."""
    request_access()
    status = None
    for item, k, _state, _name in _radios():
        if k == kind and status is None:
            op = c_void_p()
            try:
                check(vcall(item, 6, [c_int32, POINTER(c_void_p)], 1 if on else 2, byref(op)), "Radio.SetStateAsync")
                await_async(op)
                status = ACCESS.get(async_result_int(op), "unknown")
            finally:
                release(op)
        release(item)
    _drop_cache()  # read fresh objects after a change
    if status is None:
        raise RuntimeError("no %s radio found" % kind)
    return status
