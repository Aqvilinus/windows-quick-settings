"""Connect / disconnect paired Bluetooth audio devices (experimental).

Same mechanism as the Windows sound settings "Connect" button: the Bluetooth audio
KS filter behind an audio endpoint accepts the one-shot properties
KSPROPERTY_ONESHOT_RECONNECT (0) / KSPROPERTY_ONESHOT_DISCONNECT (1) of
KSPROPSETID_BtAudio.

Vtables used:
  IMMDeviceEnumerator: 3 EnumAudioEndpoints
  IMMDeviceCollection: 3 GetCount, 4 Item
  IMMDevice:           3 Activate, 4 OpenPropertyStore, 5 GetId, 6 GetState
  IPropertyStore:      5 GetValue
  IDeviceTopology:     3 GetConnectorCount, 4 GetConnector
  IConnector:          8 GetConnectedTo
  IPart:               13 Activate
  IKsControl:          3 KsProperty
"""
import ctypes
from ctypes import POINTER, byref, c_int32, c_uint32, c_void_p

from .com import GUID, check, co_create, propvariant_clear, qi, release, vcall

CLSID_MMDeviceEnumerator = "BCDE0395-E52F-467C-8E3D-C4579291692E"
IID_IMMDeviceEnumerator = "A95664D2-9614-4F35-A746-DE8DB63617E6"
IID_IDeviceTopology = "2A07407E-6497-4A18-9787-32F79BD0D98F"
IID_IPart = "AE2DE0E4-5BCA-4F2D-AA46-5D13F8FDB3A9"
IID_IKsControl = "28F54685-06FD-11D2-B27A-00A0C9223196"
KSPROPSETID_BtAudio = "7FA06C40-B8F6-4C7E-8556-E8C33A12E54D"

PKEY_DeviceInterface_FriendlyName = ("026E516E-B814-414B-83CD-856D6FEF4822", 2)
PKEY_Device_EnumeratorName = ("A45C254E-DF1C-4EFD-8020-67D146A850E0", 24)

DEVICE_STATE_ACTIVE = 0x1
DEVICE_STATE_UNPLUGGED = 0x8
E_RENDER, E_CAPTURE = 0, 1


class PROPERTYKEY(ctypes.Structure):
    _fields_ = [("fmtid", GUID), ("pid", ctypes.c_uint32)]


class KSPROPERTY(ctypes.Structure):
    _fields_ = [("Set", GUID), ("Id", ctypes.c_uint32), ("Flags", ctypes.c_uint32)]


def _prop_string(store, key):
    pk = PROPERTYKEY(GUID.of(key[0]), key[1])
    buf = (ctypes.c_ubyte * 32)()  # PROPVARIANT is 24 bytes on x64
    hr = vcall(store, 5, [POINTER(PROPERTYKEY), c_void_p], byref(pk), ctypes.addressof(buf))
    if hr < 0:
        return ""
    try:
        vt = ctypes.c_uint16.from_buffer(buf, 0).value
        if vt == 31:  # VT_LPWSTR
            p = c_void_p.from_buffer(buf, 8).value
            return ctypes.wstring_at(p) if p else ""
        return ""
    finally:
        propvariant_clear(ctypes.addressof(buf))


def _bt_endpoints():
    """Yield (IMMDevice ptr, interface friendly name, enumerator, state). Caller releases pointers."""
    enum = co_create(CLSID_MMDeviceEnumerator, IID_IMMDeviceEnumerator)
    try:
        for flow in (E_RENDER, E_CAPTURE):
            coll = c_void_p()
            if vcall(enum, 3, [c_int32, c_uint32, POINTER(c_void_p)], flow,
                     DEVICE_STATE_ACTIVE | DEVICE_STATE_UNPLUGGED, byref(coll)) < 0:
                continue
            try:
                n = c_uint32()
                check(vcall(coll, 3, [POINTER(c_uint32)], byref(n)), "IMMDeviceCollection.GetCount")
                for i in range(n.value):
                    dev = c_void_p()
                    if vcall(coll, 4, [c_uint32, POINTER(c_void_p)], i, byref(dev)) < 0:
                        continue
                    store = c_void_p()
                    keep = False
                    try:
                        if vcall(dev, 4, [c_uint32, POINTER(c_void_p)], 0, byref(store)) >= 0:  # STGM_READ
                            enumerator = _prop_string(store, PKEY_Device_EnumeratorName).upper()
                            name = _prop_string(store, PKEY_DeviceInterface_FriendlyName)
                            if enumerator.startswith("BTH"):
                                state = c_uint32()
                                vcall(dev, 6, [POINTER(c_uint32)], byref(state))
                                keep = True
                                yield dev, name, enumerator, state.value
                    finally:
                        release(store)
                        if not keep:
                            release(dev)
            finally:
                release(coll)
    finally:
        release(enum)


def list_audio_devices():
    """Names of paired Bluetooth audio devices known to the audio stack, with connection state."""
    devices = {}
    for dev, name, enumerator, state in _bt_endpoints():
        release(dev)
        d = devices.setdefault(name, {"name": name, "connected": False, "profiles": []})
        d["connected"] = d["connected"] or state == DEVICE_STATE_ACTIVE
        d["profiles"].append("A2DP" if enumerator == "BTHENUM" else "HFP" if "HF" in enumerator else enumerator)
    return sorted(devices.values(), key=lambda d: d["name"].lower())


def _oneshot(dev, prop_id):
    topo, conn, other, part, ks = c_void_p(), c_void_p(), c_void_p(), c_void_p(), c_void_p()
    try:
        iid = GUID.of(IID_IDeviceTopology)
        check(vcall(dev, 3, [POINTER(GUID), c_uint32, c_void_p, POINTER(c_void_p)], byref(iid), 23, None, byref(topo)),
              "IMMDevice.Activate(IDeviceTopology)")
        check(vcall(topo, 4, [c_uint32, POINTER(c_void_p)], 0, byref(conn)), "IDeviceTopology.GetConnector")
        check(vcall(conn, 8, [POINTER(c_void_p)], byref(other)), "IConnector.GetConnectedTo")
        part = qi(other, IID_IPart)
        iid_ks = GUID.of(IID_IKsControl)
        check(vcall(part, 13, [c_uint32, POINTER(GUID), POINTER(c_void_p)], 23, byref(iid_ks), byref(ks)), "IPart.Activate(IKsControl)")
        prop = KSPROPERTY(GUID.of(KSPROPSETID_BtAudio), prop_id, 1)  # KSPROPERTY_TYPE_GET
        returned = c_uint32()
        check(vcall(ks, 3, [POINTER(KSPROPERTY), c_uint32, c_void_p, c_uint32, POINTER(c_uint32)],
                    byref(prop), ctypes.sizeof(prop), None, 0, byref(returned)), "IKsControl.KsProperty")
    finally:
        for p in (ks, part, other, conn, topo):
            release(p)


def set_connected(name, connect):
    """Connect (True) or disconnect (False) the paired Bluetooth audio device called `name`."""
    targets = []
    for dev, ep_name, enumerator, state in _bt_endpoints():
        if ep_name == name:
            targets.append((0 if enumerator == "BTHENUM" else 1, dev))  # prefer the A2DP endpoint
        else:
            release(dev)
    if not targets:
        raise RuntimeError("no Bluetooth audio endpoint named %r" % name)
    targets.sort(key=lambda t: t[0])
    last_error = None
    done = False
    for _prio, dev in targets:
        try:
            if not done:
                _oneshot(dev, 0 if connect else 1)
                done = True
        except OSError as e:
            last_error = e
        finally:
            release(dev)
    if not done:
        raise last_error or RuntimeError("connect failed")
    return True
