"""Connect / disconnect paired Bluetooth audio devices (experimental).

Same mechanism as the Windows sound settings "Connect" button: the Bluetooth audio KS filter behind an audio
endpoint accepts the one-shot properties KSPROPERTY_ONESHOT_RECONNECT (0) / KSPROPERTY_ONESHOT_DISCONNECT (1) of
KSPROPSETID_BtAudio. Endpoint -> IDeviceTopology -> connector -> the filter's IPart -> IKsControl.

pycaw has no device topology interfaces, so the four used here are declared below (comtypes), in the order of
devicetopology.h / ks.h; methods we don't call are placeholders that keep the vtable order.
"""
from . import com  # noqa: F401 - must come before comtypes: COM in this process is multithreaded (pywinrt needs it)

import ctypes
from ctypes import HRESULT, POINTER, c_void_p
from ctypes.wintypes import DWORD, UINT, ULONG

from comtypes import CLSCTX_ALL, COMError, COMMETHOD, GUID, IUnknown

from .audio import enumerator, prop_string

KSPROPSETID_BtAudio = GUID("{7FA06C40-B8F6-4C7E-8556-E8C33A12E54D}")
KSPROPERTY_TYPE_GET = 1
PKEY_DeviceInterface_FriendlyName = ("{026E516E-B814-414B-83CD-856D6FEF4822}", 2)
PKEY_Device_EnumeratorName = ("{A45C254E-DF1C-4EFD-8020-67D146A850E0}", 24)
DEVICE_STATE_ACTIVE = 0x1
DEVICE_STATE_UNPLUGGED = 0x8
E_RENDER, E_CAPTURE = 0, 1


def _unused(n):
    return COMMETHOD([], HRESULT, "Unused%d" % n)


class KSPROPERTY(ctypes.Structure):
    _fields_ = [("Set", GUID), ("Id", ULONG), ("Flags", ULONG)]


class IKsControl(IUnknown):
    _iid_ = GUID("{28F54685-06FD-11D2-B27A-00A0C9223196}")
    _methods_ = [
        COMMETHOD([], HRESULT, "KsProperty", (["in"], POINTER(KSPROPERTY), "Property"), (["in"], ULONG, "PropertyLength"),
                  (["in"], c_void_p, "PropertyData"), (["in"], ULONG, "DataLength"),
                  (["out"], POINTER(ULONG), "BytesReturned")),
        _unused(1),  # KsMethod
        _unused(2),  # KsEvent
    ]


class IPart(IUnknown):
    _iid_ = GUID("{AE2DE0E4-5BCA-4F2D-AA46-5D13F8FDB3A9}")
    _methods_ = [_unused(i) for i in range(10)] + [  # GetName ... GetTopologyObject
        COMMETHOD([], HRESULT, "Activate", (["in"], DWORD, "dwClsContext"), (["in"], POINTER(GUID), "refiid"),
                  (["out"], POINTER(POINTER(IUnknown)), "ppvObject")),
    ]


class IConnector(IUnknown):
    _iid_ = GUID("{9C2C4058-23F5-41DE-877A-DF3AF236A09E}")


IConnector._methods_ = [_unused(i) for i in range(5)] + [  # GetType, GetDataFlow, ConnectTo, Disconnect, IsConnected
    COMMETHOD([], HRESULT, "GetConnectedTo", (["out"], POINTER(POINTER(IConnector)), "ppConTo")),
]


class IDeviceTopology(IUnknown):
    _iid_ = GUID("{2A07407E-6497-4A18-9787-32F79BD0D98F}")
    _methods_ = [
        COMMETHOD([], HRESULT, "GetConnectorCount", (["out"], POINTER(UINT), "pCount")),
        COMMETHOD([], HRESULT, "GetConnector", (["in"], UINT, "nIndex"), (["out"], POINTER(POINTER(IConnector)), "ppConnector")),
    ]


def _bt_endpoints():
    """Yield (IMMDevice, interface friendly name, enumerator name, state) for Bluetooth audio endpoints."""
    enum = enumerator()
    for flow in (E_RENDER, E_CAPTURE):
        try:
            coll = enum.EnumAudioEndpoints(flow, DEVICE_STATE_ACTIVE | DEVICE_STATE_UNPLUGGED)
        except COMError:
            continue
        for i in range(coll.GetCount()):
            dev = coll.Item(i)
            enumerator_name = prop_string(dev, PKEY_Device_EnumeratorName).upper()
            if enumerator_name.startswith("BTH"):
                yield dev, prop_string(dev, PKEY_DeviceInterface_FriendlyName), enumerator_name, dev.GetState()


def list_audio_devices():
    """Names of paired Bluetooth audio devices known to the audio stack, with connection state."""
    devices = {}
    for _dev, name, _enumerator_name, state in _bt_endpoints():
        d = devices.setdefault(name, {"name": name, "connected": False})
        d["connected"] = d["connected"] or state == DEVICE_STATE_ACTIVE
    return sorted(devices.values(), key=lambda d: d["name"].lower())


def _oneshot(dev, prop_id):
    topo = dev.Activate(IDeviceTopology._iid_, CLSCTX_ALL, None).QueryInterface(IDeviceTopology)
    part = topo.GetConnector(0).GetConnectedTo().QueryInterface(IPart)
    ks = part.Activate(CLSCTX_ALL, IKsControl._iid_).QueryInterface(IKsControl)
    prop = KSPROPERTY(KSPROPSETID_BtAudio, prop_id, KSPROPERTY_TYPE_GET)
    ks.KsProperty(prop, ctypes.sizeof(prop), None, 0)


def set_connected(name, connect):
    """Connect (True) or disconnect (False) the paired Bluetooth audio device called `name`."""
    targets = sorted(((0 if enum_name == "BTHENUM" else 1), i, dev)  # prefer the A2DP endpoint
                     for i, (dev, ep_name, enum_name, _state) in enumerate(_bt_endpoints()) if ep_name == name)
    if not targets:
        raise RuntimeError("no Bluetooth audio endpoint named %r" % name)
    last_error = None
    for _prio, _i, dev in targets:
        try:
            _oneshot(dev, 0 if connect else 1)
            return True
        except COMError as e:
            last_error = e
    raise last_error or RuntimeError("connect failed")
