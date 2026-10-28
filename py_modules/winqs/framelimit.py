"""Frame limit of the Intel graphics driver (Intel Graphics Control Library, ControlLib.dll).

This is the same "Frame Rate Limiter" that Intel Graphics Software shows. It is a global driver
setting for games (the Steam interface itself is not limited), it needs no administrator rights,
no RTSS and nothing injected into games. Value 0 means "off". Games usually pick up a change
when they start, so a running game may need a restart.

Structures follow include/igcl_api.h from github.com/intel/drivers.gpu.control-library.
"""
import ctypes
import os
import time
from ctypes import (POINTER, Structure, Union, byref, c_bool, c_char_p, c_float, c_int8, c_int16, c_int32, c_int64,
                    c_uint8, c_uint16, c_uint32, c_uint64, c_void_p, sizeof)

CTL_3D_FEATURE_FRAME_LIMIT = 2
CTL_PROPERTY_VALUE_TYPE_INT32 = 2
CTL_API_VERSION = (1 << 16) | 1


class _RangeF(Structure):
    _fields_ = [("min", c_float), ("max", c_float), ("step", c_float), ("default", c_float)]


class _RangeI(Structure):
    _fields_ = [("min", c_int32), ("max", c_int32), ("step", c_int32), ("default", c_int32)]


class _RangeU(Structure):
    _fields_ = [("min", c_uint32), ("max", c_uint32), ("step", c_uint32), ("default", c_uint32)]


class _InfoB(Structure):
    _fields_ = [("DefaultState", c_bool)]


class _InfoF(Structure):
    _fields_ = [("DefaultEnable", c_bool), ("Range", _RangeF)]


class _InfoI(Structure):
    _fields_ = [("DefaultEnable", c_bool), ("Range", _RangeI)]


class _InfoE(Structure):
    _fields_ = [("SupportedTypes", c_uint64), ("DefaultType", c_uint32)]


class _InfoU(Structure):
    _fields_ = [("DefaultEnable", c_bool), ("Range", _RangeU)]


class _PropInfo(Union):
    _fields_ = [("B", _InfoB), ("F", _InfoF), ("I", _InfoI), ("E", _InfoE), ("U", _InfoU)]


class _PropB(Structure):
    _fields_ = [("Enable", c_bool)]


class _PropF(Structure):
    _fields_ = [("Enable", c_bool), ("Value", c_float)]


class _PropI(Structure):
    _fields_ = [("Enable", c_bool), ("Value", c_int32)]


class _PropE(Structure):
    _fields_ = [("EnableType", c_uint32)]


class _PropU(Structure):
    _fields_ = [("Enable", c_bool), ("Value", c_uint32)]


class _Prop(Union):
    _fields_ = [("B", _PropB), ("F", _PropF), ("I", _PropI), ("E", _PropE), ("U", _PropU)]


class _AppId(Structure):
    _fields_ = [("Data1", c_uint32), ("Data2", c_uint16), ("Data3", c_uint16), ("Data4", c_uint8 * 8)]


class _InitArgs(Structure):
    _fields_ = [("Size", c_uint32), ("Version", c_uint8), ("AppVersion", c_uint32), ("flags", c_uint32),
                ("SupportedVersion", c_uint32), ("ApplicationUID", _AppId)]


class _FeatDetails(Structure):
    _fields_ = [("FeatureType", c_int32), ("ValueType", c_int32), ("Value", _PropInfo), ("CustomValueSize", c_int32),
                ("pCustomValue", c_void_p), ("PerAppSupport", c_bool), ("ConflictingFeatures", c_int64),
                ("FeatureMiscSupport", c_int16), ("Reserved", c_int16), ("Reserved1", c_int16), ("Reserved2", c_int16)]


class _FeatCaps(Structure):
    _fields_ = [("Size", c_uint32), ("Version", c_uint8), ("NumSupportedFeatures", c_uint32),
                ("pFeatureDetails", POINTER(_FeatDetails))]


class _GetSet(Structure):
    _fields_ = [("Size", c_uint32), ("Version", c_uint8), ("FeatureType", c_int32), ("ApplicationName", c_char_p),
                ("ApplicationNameLength", c_int8), ("bSet", c_bool), ("ValueType", c_int32), ("Value", _Prop),
                ("CustomValueSize", c_int32), ("pCustomValue", c_void_p)]


class IntelFrameLimit:
    """One IGCL session, opened lazily and kept for the life of the worker thread."""

    def __init__(self):
        self._lib = None
        self._api = c_void_p()
        self._dev = None
        self.range = None  # (min, max)
        self.error = None
        self._error_time = 0.0

    RETRY_AFTER = 30  # s; a failed open (e.g. during a driver update) is tried again later, not cached forever

    def _open(self):
        if self._dev is not None:
            return
        if self.error is not None:
            if time.monotonic() - self._error_time < self.RETRY_AFTER:
                return
            self.error = None
        try:
            self._open_once()
        finally:
            if self._dev is None:
                self.close()  # a session opened before the failure, so a retry doesn't leak one
                if self.error is None:
                    self.error = "frame limit unavailable"
            if self.error is not None:
                self._error_time = time.monotonic()

    def close(self):
        """End the IGCL session (on the worker thread, which owns it)."""
        if self._lib is not None and self._api.value:
            try:
                self._lib.ctlClose(self._api)
            except Exception:  # noqa: BLE001 - driver gone: nothing left to close
                pass
        self._lib, self._api, self._dev = None, c_void_p(), None

    def _open_once(self):
        path = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "ControlLib.dll")
        if not os.path.exists(path):
            self.error = "Intel graphics driver not found"
            return
        lib = ctypes.CDLL(path)
        for name in ("ctlInit", "ctlEnumerateDevices", "ctlGetSupported3DCapabilities", "ctlGetSet3DFeature", "ctlClose"):
            getattr(lib, name).restype = c_uint32
        lib.ctlInit.argtypes = [POINTER(_InitArgs), POINTER(c_void_p)]
        lib.ctlEnumerateDevices.argtypes = [c_void_p, POINTER(c_uint32), c_void_p]
        lib.ctlGetSupported3DCapabilities.argtypes = [c_void_p, POINTER(_FeatCaps)]
        lib.ctlGetSet3DFeature.argtypes = [c_void_p, POINTER(_GetSet)]
        lib.ctlClose.argtypes = [c_void_p]
        args = _InitArgs(Size=sizeof(_InitArgs), Version=0, AppVersion=CTL_API_VERSION, flags=0)
        r = lib.ctlInit(byref(args), byref(self._api))
        if r:
            self.error = "ctlInit failed (0x%08x)" % r
            return
        self._lib = lib  # session open: close() ends it; it is used only once _dev is set
        n = c_uint32(0)
        lib.ctlEnumerateDevices(self._api, byref(n), None)
        if not n.value:
            self.error = "no Intel GPU found"
            return
        devs = (c_void_p * n.value)()
        lib.ctlEnumerateDevices(self._api, byref(n), devs)
        for dev in devs:
            caps = _FeatCaps(Size=sizeof(_FeatCaps), Version=0)
            if lib.ctlGetSupported3DCapabilities(c_void_p(dev), byref(caps)) or not caps.NumSupportedFeatures:
                continue
            arr = (_FeatDetails * caps.NumSupportedFeatures)()
            caps.pFeatureDetails = arr
            if lib.ctlGetSupported3DCapabilities(c_void_p(dev), byref(caps)):
                continue
            for d in arr:
                if d.FeatureType == CTL_3D_FEATURE_FRAME_LIMIT:
                    self._dev = c_void_p(dev)
                    self.range = (int(d.Value.I.Range.min) or 30, int(d.Value.I.Range.max) or 300)
                    return
        self.error = "the driver has no frame limit"

    def _getset(self, set_=False, enable=False, value=0):
        self._open()
        if self._dev is None:
            raise RuntimeError(self.error or "frame limit unavailable")
        g = _GetSet(Size=sizeof(_GetSet), Version=0, FeatureType=CTL_3D_FEATURE_FRAME_LIMIT, ApplicationName=b"",
                    ApplicationNameLength=0, bSet=set_, ValueType=CTL_PROPERTY_VALUE_TYPE_INT32)
        g.Value.I.Enable = enable
        g.Value.I.Value = value
        r = self._lib.ctlGetSet3DFeature(self._dev, byref(g))
        if r:
            raise OSError("ctlGetSet3DFeature failed (0x%08x)" % r)
        return bool(g.Value.I.Enable), int(g.Value.I.Value)

    def get(self):
        """{'supported', 'fps' (0 = off), 'min', 'max', 'error'}"""
        try:
            enabled, value = self._getset()
        except Exception as e:  # noqa: BLE001 - reported to the UI
            return {"supported": False, "fps": 0, "min": 30, "max": 300, "error": str(e)}
        return {"supported": True, "fps": value if enabled else 0, "min": self.range[0], "max": self.range[1]}

    def set(self, fps):
        fps = int(fps)
        if fps <= 0:
            self._getset(True, False, 0)
        else:
            lo, hi = self.range or (30, 300)
            self._getset(True, True, max(lo, min(hi, fps)))
        return self.get()
