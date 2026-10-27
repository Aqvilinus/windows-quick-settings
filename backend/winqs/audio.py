"""Default output / input device and volume through Windows Core Audio, with pycaw's interfaces (comtypes).

IPolicyConfig.SetDefaultEndpoint is undocumented; it is what Windows' own sound settings use to switch devices.
"""
from . import com  # noqa: F401 - must come before comtypes: COM in this process is multithreaded (pywinrt needs it)

from ctypes import byref, c_void_p, c_wchar_p, cast

import comtypes
from comtypes import CLSCTX_ALL, COMError, GUID
from comtypes.malloc import _CoTaskMemFree
from pycaw.api.endpointvolume import IAudioEndpointVolume
from pycaw.api.mmdeviceapi import IMMDeviceEnumerator
from pycaw.api.mmdeviceapi.depend.structures import PROPERTYKEY
from pycaw.api.policyconfig import IPolicyConfig, IPolicyConfigVista
from pycaw.constants import CLSID_CPolicyConfigClient, CLSID_MMDeviceEnumerator

FLOW = {"output": 0, "input": 1}  # eRender, eCapture
E_MULTIMEDIA = 1
E_NOTFOUND = -2147023728  # 0x80070490: no default device of this kind
DEVICE_STATE_ACTIVE = 1
STGM_READ = 0
VT_LPWSTR = 31
ROLES = (0, 1, 2)  # eConsole, eMultimedia, eCommunications: switch all three, like Windows does
CLSID_PolicyConfigVista = GUID("{294935CE-F637-4E7C-A41B-AB255460B862}")
PKEY_Device_FriendlyName = ("{A45C254E-DF1C-4EFD-8020-67D146A850E0}", 14)


def enumerator():
    return comtypes.CoCreateInstance(CLSID_MMDeviceEnumerator, IMMDeviceEnumerator, CLSCTX_ALL)


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


def _default_device(flow, enum=None):
    try:
        return (enum or enumerator()).GetDefaultAudioEndpoint(FLOW[flow], E_MULTIMEDIA)
    except COMError as e:
        if e.hresult == E_NOTFOUND:
            return None
        raise


def devices(flow):
    """Active endpoints of a flow: [{'id', 'name', 'default'}], default device first."""
    enum = enumerator()
    default = _default_device(flow, enum)
    default_id = device_id(default).lower() if default is not None else None
    coll = enum.EnumAudioEndpoints(FLOW[flow], DEVICE_STATE_ACTIVE)
    out = []
    for i in range(coll.GetCount()):
        dev = coll.Item(i)
        dev_id = device_id(dev)
        out.append({"id": dev_id, "name": prop_string(dev, PKEY_Device_FriendlyName) or dev_id,
                    "default": dev_id.lower() == default_id})
    out.sort(key=lambda d: (not d["default"], d["name"].lower()))
    return out


def set_default(flow, dev_id):
    """Make dev_id the default device of its flow for every role; returns the default id read back."""
    if dev_id.lower() not in {d["id"].lower() for d in devices(flow)}:
        raise ValueError("audio device is not active: %s" % dev_id)
    try:
        cfg = comtypes.CoCreateInstance(CLSID_CPolicyConfigClient, IPolicyConfig, CLSCTX_ALL)
    except COMError:
        cfg = comtypes.CoCreateInstance(CLSID_PolicyConfigVista, IPolicyConfigVista, CLSCTX_ALL)
    for role in ROLES:
        cfg.SetDefaultEndpoint(dev_id, role)
    now = next((d for d in devices(flow) if d["default"]), None)
    if not now or now["id"].lower() != dev_id.lower():
        raise RuntimeError("Windows did not switch the default %s device" % flow)
    return now["id"]


def _endpoint_volume(dev):
    return dev.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None).QueryInterface(IAudioEndpointVolume)


def get(flow):
    """{'volume': 0-100, 'muted': bool, 'name': str} for the default device, or None if there is none."""
    dev = _default_device(flow)
    if dev is None:
        return None
    vol = _endpoint_volume(dev)
    return {"volume": int(round(vol.GetMasterVolumeLevelScalar() * 100)), "muted": bool(vol.GetMute()),
            "name": prop_string(dev, PKEY_Device_FriendlyName)}


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
