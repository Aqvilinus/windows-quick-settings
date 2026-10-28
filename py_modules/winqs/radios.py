"""Wi-Fi / Bluetooth radio on-off through WinRT Windows.Devices.Radios (pywinrt)."""
import functools
import time

from winrt.windows.devices.radios import Radio, RadioKind, RadioState

KIND = {RadioKind.WI_FI: "wifi", RadioKind.BLUETOOTH: "bluetooth"}
CACHE_SECONDS = 30   # re-enumerate radios now and then (adapter added/removed)

_cache = {}          # kind -> Radio
_cache_time = 0.0


def _name(enum_value):
    """RadioState.DENIED_BY_USER -> 'denied_by_user' (the names the frontend uses)."""
    return enum_value.name.lower()


@functools.cache
def request_access():
    return _name(Radio.request_access_async().get())


def _fill_cache():
    """Radio objects are kept between polls and their State is read directly, which skips the asynchronous
    GetRadiosAsync enumeration on every refresh."""
    global _cache_time
    _cache.clear()
    for r in Radio.get_radios_async().get():
        if r.kind in KIND:
            _cache.setdefault(KIND[r.kind], r)
    _cache_time = time.monotonic()


def get_states():
    """{'wifi': 'on'|'off'|'disabled'|'unknown', 'bluetooth': ...}; a missing radio is reported as None."""
    global _cache_time
    request_access()
    if not _cache_time or time.monotonic() - _cache_time > CACHE_SECONDS:
        _fill_cache()
    result = {"wifi": None, "bluetooth": None}
    for kind, r in list(_cache.items()):
        try:
            result[kind] = _name(r.state)
        except Exception:  # noqa: BLE001 - stale object: enumerate again next time
            _cache_time = 0.0
            raise
    return result


def set_state(kind, on):
    """Turn the first radio of `kind` ('wifi' | 'bluetooth') on or off. Returns the access status."""
    global _cache_time
    request_access()
    _fill_cache()
    r = _cache.get(kind)
    if r is None:
        raise RuntimeError("no %s radio found" % kind)
    status = _name(r.set_state_async(RadioState.ON if on else RadioState.OFF).get())
    _cache_time = 0.0  # read fresh objects after a change
    return status
