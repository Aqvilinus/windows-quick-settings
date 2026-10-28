"""Default output / input device and volume through Windows Core Audio, with pycaw (comtypes).

Switching the default device goes through pycaw's AudioUtilities.SetDefaultDevice (the undocumented
IPolicyConfig.SetDefaultEndpoint that Windows' own sound settings use).
"""
from . import com  # noqa: F401 - must come before comtypes: COM in this process is multithreaded (pywinrt needs it)

from ctypes import byref, c_void_p, c_wchar_p, cast

import comtypes
from comtypes import CLSCTX_ALL, COMError, GUID
from comtypes.malloc import _CoTaskMemFree
from pycaw.api.endpointvolume import IAudioEndpointVolume
from pycaw.api.mmdeviceapi import IMMDeviceEnumerator
from pycaw.api.mmdeviceapi.depend.structures import PROPERTYKEY
from pycaw.constants import CLSID_MMDeviceEnumerator, ERole
from pycaw.utils import AudioUtilities

FLOW = {"output": 0, "input": 1}  # eRender, eCapture
E_MULTIMEDIA = 1
E_NOTFOUND = -2147023728  # 0x80070490: no default device of this kind
DEVICE_STATE_ACTIVE = 1
STGM_READ = 0
VT_LPWSTR = 31
ROLES = [ERole.eConsole, ERole.eMultimedia, ERole.eCommunications]  # switch all three, like Windows does
PKEY_Device_FriendlyName = ("{A45C254E-DF1C-4EFD-8020-67D146A850E0}", 14)


_enumerator = None


def enumerator():
    """One MMDeviceEnumerator for the process (it is free-threaded; creating one per call cost ~0.2 ms each, five
    times per poll). reset() drops it after a COM error, e.g. when the audio service was restarted."""
    global _enumerator
    if _enumerator is None:
        _enumerator = comtypes.CoCreateInstance(CLSID_MMDeviceEnumerator, IMMDeviceEnumerator, CLSCTX_ALL)
    return _enumerator


def reset():
    global _enumerator
    _enumerator = None


def device_id(dev):
    """IMMDevice.GetId. comtypes would return the string without freeing Windows' copy, and this runs on every
    poll, so the raw method (comtypes' __com_ form) is called and the string freed with CoTaskMemFree."""
    p = c_wchar_p()
    dev._IMMDevice__com_GetId(byref(p))
    try:
        return p.value or ""
    finally:
        _CoTaskMemFree(cast(p, c_void_p))


def prop_string(dev, key):
    """A string property of an endpoint ('' if missing)."""
    try:
        pv = dev.OpenPropertyStore(STGM_READ).GetValue(PROPERTYKEY(GUID(key[0]), key[1]))
    except COMError:
        return ""
    try:
        return (pv.GetValue() or "") if pv.vt == VT_LPWSTR else ""
    finally:
        pv.clear()


def _default_device(flow):
    try:
        return enumerator().GetDefaultAudioEndpoint(FLOW[flow], E_MULTIMEDIA)
    except COMError as e:
        if e.hresult == E_NOTFOUND:
            return None
        reset()  # e.g. the audio service restarted: the next call gets a new enumerator
        raise


def _devices(flow, default):
    default_id = device_id(default).lower() if default is not None else None
    coll = enumerator().EnumAudioEndpoints(FLOW[flow], DEVICE_STATE_ACTIVE)
    out = []
    for i in range(coll.GetCount()):
        dev = coll.Item(i)
        dev_id = device_id(dev)
        out.append({"id": dev_id, "name": prop_string(dev, PKEY_Device_FriendlyName) or dev_id,
                    "default": dev_id.lower() == default_id})
    out.sort(key=lambda d: (not d["default"], d["name"].lower()))
    return out


def devices(flow):
    """Active endpoints of a flow: [{'id', 'name', 'default'}], default device first."""
    return _devices(flow, _default_device(flow))


def get(flow):
    """({'volume': 0-100, 'muted': bool} or None without a default device, devices(flow)): one lookup of the
    default device for both, as the poll needs them together."""
    default = _default_device(flow)
    devs = _devices(flow, default)
    if default is None:
        return None, devs
    vol = _endpoint_volume(default)
    return {"volume": int(round(vol.GetMasterVolumeLevelScalar() * 100)), "muted": bool(vol.GetMute())}, devs


def set_default(flow, dev_id):
    """Make dev_id the default device of its flow for every role; returns the default id read back."""
    if dev_id.lower() not in {d["id"].lower() for d in devices(flow)}:
        raise ValueError("audio device is not active: %s" % dev_id)
    AudioUtilities.SetDefaultDevice(dev_id, roles=ROLES)
    now = next((d for d in devices(flow) if d["default"]), None)
    if not now or now["id"].lower() != dev_id.lower():
        raise RuntimeError("Windows did not switch the default %s device" % flow)
    return now["id"]


def _endpoint_volume(dev):
    return dev.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None).QueryInterface(IAudioEndpointVolume)


def set_volume(flow, value):
    """Set default device volume 0-100. 0 mutes, anything above unmutes (like the Steam Deck slider)."""
    value = max(0, min(100, int(value)))
    dev = _default_device(flow)
    if dev is None:
        raise RuntimeError("no default %s device" % flow)
    vol = _endpoint_volume(dev)
    vol.SetMasterVolumeLevelScalar(value / 100.0, None)
    vol.SetMute(1 if value == 0 else 0, None)
    return value
