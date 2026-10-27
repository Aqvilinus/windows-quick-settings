"""Default output / input volume through Windows Core Audio (IAudioEndpointVolume), raw ctypes COM.

Vtables used:
  IMMDeviceEnumerator:  3 EnumAudioEndpoints(dataFlow, stateMask, IMMDeviceCollection**),
                        4 GetDefaultAudioEndpoint(dataFlow, role, IMMDevice**)
  IMMDeviceCollection:  3 GetCount(UINT*), 4 Item(UINT, IMMDevice**)
  IMMDevice:            3 Activate, 4 OpenPropertyStore, 5 GetId(LPWSTR*)
  IPolicyConfig:        13 SetDefaultEndpoint(LPCWSTR, ERole)  (undocumented; what Windows' sound settings use)
  IPropertyStore:       5 GetValue
  IAudioEndpointVolume: 7 SetMasterVolumeLevelScalar(float, LPCGUID), 9 GetMasterVolumeLevelScalar(float*),
                        14 SetMute(BOOL, LPCGUID), 15 GetMute(BOOL*)
"""
import ctypes
from ctypes import POINTER, byref, c_float, c_int32, c_uint32, c_void_p, c_wchar_p

from .btaudio import CLSID_MMDeviceEnumerator, IID_IMMDeviceEnumerator, PROPERTYKEY, _prop_string
from .com import GUID, check, co_create, release, vcall

IID_IAudioEndpointVolume = "5CDF2C82-841E-4546-9722-0CF74078229A"
PKEY_Device_FriendlyName = ("A45C254E-DF1C-4EFD-8020-67D146A850E0", 14)
FLOW = {"output": 0, "input": 1}  # eRender, eCapture
E_MULTIMEDIA = 1
E_NOTFOUND = -2147023728  # 0x80070490: no default device of this kind
DEVICE_STATE_ACTIVE = 1
ROLES = (0, 1, 2)  # eConsole, eMultimedia, eCommunications: switch all three, like Windows does
CLSID_PolicyConfigClient = "870AF99C-171D-4F9E-AF0D-E63DF40C2BC9"
IID_IPolicyConfig = "F8679F50-850A-41CF-9C72-430F290290C8"          # Windows 7+
IID_IPolicyConfigVista = "568B9108-44BF-40B4-9006-86AFE5B5A620"     # fallback, SetDefaultEndpoint at slot 12
CLSID_PolicyConfigVista = "294935CE-F637-4E7C-A41B-AB255460B862"
_ole32 = ctypes.WinDLL("ole32")
_ole32.CoTaskMemFree.argtypes = [c_void_p]
_ole32.CoTaskMemFree.restype = None


def _device_id(dev):
    p = c_void_p()
    check(vcall(dev, 5, [POINTER(c_void_p)], byref(p)), "IMMDevice.GetId")
    try:
        return ctypes.wstring_at(p.value)
    finally:
        _ole32.CoTaskMemFree(p)


def _device_name(dev):
    store = c_void_p()
    try:
        if vcall(dev, 4, [c_uint32, POINTER(c_void_p)], 0, byref(store)) >= 0:
            return _prop_string(store, PKEY_Device_FriendlyName)
        return ""
    finally:
        release(store)


def devices(flow):
    """Active endpoints of a flow: [{'id', 'name', 'default'}], default device first."""
    enum = co_create(CLSID_MMDeviceEnumerator, IID_IMMDeviceEnumerator)
    coll = c_void_p()
    out = []
    try:
        default_id = None
        dev = c_void_p()
        if vcall(enum, 4, [c_int32, c_int32, POINTER(c_void_p)], FLOW[flow], E_MULTIMEDIA, byref(dev)) >= 0:
            try:
                default_id = _device_id(dev).lower()
            finally:
                release(dev)
        check(vcall(enum, 3, [c_int32, c_uint32, POINTER(c_void_p)], FLOW[flow], DEVICE_STATE_ACTIVE, byref(coll)),
              "EnumAudioEndpoints")
        n = c_uint32()
        check(vcall(coll, 3, [POINTER(c_uint32)], byref(n)), "IMMDeviceCollection.GetCount")
        for i in range(n.value):
            item = c_void_p()
            if vcall(coll, 4, [c_uint32, POINTER(c_void_p)], i, byref(item)) < 0:
                continue
            try:
                dev_id = _device_id(item)
                out.append({"id": dev_id, "name": _device_name(item) or dev_id,
                            "default": dev_id.lower() == default_id})
            finally:
                release(item)
    finally:
        release(coll)
        release(enum)
    out.sort(key=lambda d: (not d["default"], d["name"].lower()))
    return out


def set_default(flow, dev_id):
    """Make dev_id the default device of its flow for every role; returns the default id read back."""
    known = {d["id"].lower(): d for d in devices(flow)}
    if dev_id.lower() not in known:
        raise ValueError("audio device is not active: %s" % dev_id)
    try:
        cfg, slot = co_create(CLSID_PolicyConfigClient, IID_IPolicyConfig), 13
    except OSError:
        cfg, slot = co_create(CLSID_PolicyConfigVista, IID_IPolicyConfigVista), 12
    try:
        for role in ROLES:
            check(vcall(cfg, slot, [c_wchar_p, c_int32], dev_id, role), "IPolicyConfig.SetDefaultEndpoint")
    finally:
        release(cfg)
    now = next((d for d in devices(flow) if d["default"]), None)
    if not now or now["id"].lower() != dev_id.lower():
        raise RuntimeError("Windows did not switch the default %s device" % flow)
    return now["id"]


def _default_device(flow):
    enum = co_create(CLSID_MMDeviceEnumerator, IID_IMMDeviceEnumerator)
    try:
        dev = c_void_p()
        hr = vcall(enum, 4, [c_int32, c_int32, POINTER(c_void_p)], FLOW[flow], E_MULTIMEDIA, byref(dev))
        if hr == E_NOTFOUND:
            return None
        check(hr, "GetDefaultAudioEndpoint")
        return dev
    finally:
        release(enum)


def _endpoint_volume(dev):
    vol = c_void_p()
    iid = GUID.of(IID_IAudioEndpointVolume)
    check(vcall(dev, 3, [POINTER(GUID), c_uint32, c_void_p, POINTER(c_void_p)], byref(iid), 23, None, byref(vol)),
          "IMMDevice.Activate(IAudioEndpointVolume)")
    return vol


def get(flow):
    """{'volume': 0-100, 'muted': bool, 'name': str} for the default device, or None if there is none."""
    dev = _default_device(flow)
    if dev is None:
        return None
    vol, store = c_void_p(), c_void_p()
    try:
        vol = _endpoint_volume(dev)
        level, muted = c_float(), ctypes.c_int()
        check(vcall(vol, 9, [POINTER(c_float)], byref(level)), "GetMasterVolumeLevelScalar")
        check(vcall(vol, 15, [POINTER(ctypes.c_int)], byref(muted)), "GetMute")
        name = ""
        if vcall(dev, 4, [c_uint32, POINTER(c_void_p)], 0, byref(store)) >= 0:
            name = _prop_string(store, PKEY_Device_FriendlyName)
        return {"volume": int(round(level.value * 100)), "muted": bool(muted.value), "name": name}
    finally:
        release(store)
        release(vol)
        release(dev)


def set_volume(flow, value):
    """Set default device volume 0-100. 0 mutes, anything above unmutes (like the Steam Deck slider)."""
    value = max(0, min(100, int(value)))
    dev = _default_device(flow)
    if dev is None:
        raise RuntimeError("no default %s device" % flow)
    vol = c_void_p()
    try:
        vol = _endpoint_volume(dev)
        check(vcall(vol, 7, [c_float, c_void_p], c_float(value / 100.0), None), "SetMasterVolumeLevelScalar")
        check(vcall(vol, 14, [ctypes.c_int, c_void_p], 1 if value == 0 else 0, None), "SetMute")
        return value
    finally:
        release(vol)
        release(dev)
