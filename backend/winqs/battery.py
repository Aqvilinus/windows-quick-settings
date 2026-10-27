"""Battery charge / discharge rate, as Windows reports it (CallNtPowerInformation SystemBatteryState, no admin)."""
import ctypes
from ctypes import byref, sizeof, wintypes

_powrprof = ctypes.WinDLL("powrprof")
_powrprof.CallNtPowerInformation.argtypes = [ctypes.c_int, ctypes.c_void_p, wintypes.ULONG, ctypes.c_void_p, wintypes.ULONG]
_powrprof.CallNtPowerInformation.restype = ctypes.c_long
SystemBatteryState = 5


class SYSTEM_BATTERY_STATE(ctypes.Structure):
    _fields_ = [("AcOnLine", ctypes.c_ubyte), ("BatteryPresent", ctypes.c_ubyte), ("Charging", ctypes.c_ubyte),
                ("Discharging", ctypes.c_ubyte), ("Spare1", ctypes.c_ubyte * 3), ("Tag", ctypes.c_ubyte),
                ("MaxCapacity", wintypes.ULONG), ("RemainingCapacity", wintypes.ULONG), ("Rate", ctypes.c_int32),
                ("EstimatedTime", wintypes.ULONG), ("DefaultAlert1", wintypes.ULONG), ("DefaultAlert2", wintypes.ULONG)]


def state():
    """{'present', 'ac', 'charging', 'watts'}: watts > 0 while discharging, < 0 while charging, None if unknown."""
    s = SYSTEM_BATTERY_STATE()
    if _powrprof.CallNtPowerInformation(SystemBatteryState, None, 0, byref(s), sizeof(s)) != 0:
        return None
    rate = s.Rate  # mW, negative while discharging
    watts = None if rate in (0, -0x80000000) else round(-rate / 1000.0, 1)
    return {"present": bool(s.BatteryPresent), "ac": bool(s.AcOnLine), "charging": bool(s.Charging), "watts": watts}
