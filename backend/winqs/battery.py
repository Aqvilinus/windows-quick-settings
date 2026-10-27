"""Battery charge / discharge rate, as Windows reports it (CallNtPowerInformation SystemBatteryState, no admin)."""
import ctypes
import math
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


CV_KNEE = 0.8      # Li-ion: about constant power up to ~80 % (CC), then constant voltage (CV) with a falling current
CV_END = 0.05      # the charger stops when the power falls to about C/20
SMOOTHING = 0.2    # weight of a new rate sample (polled every 2 s, so ~10 s to settle)
_rate_avg = None   # smoothed charge rate in mW while charging


def _cv_hours(gap_mwh, p_mw, full_mwh):
    """Hours for the CV phase: the power decays in proportion to the missing charge (P = k * gap) until C/20."""
    p_end = CV_END * full_mwh  # mW
    if p_mw <= p_end:
        return gap_mwh / p_mw
    return math.log(p_mw / p_end) * gap_mwh / p_mw  # t = ln(P / P_end) / k, k = P / gap


def _time_to_full(full_mwh, now_mwh, rate_mw):
    """Seconds to a full charge: the smoothed power up to the knee, then the CV taper."""
    global _rate_avg
    _rate_avg = rate_mw if _rate_avg is None else _rate_avg + SMOOTHING * (rate_mw - _rate_avg)
    p = _rate_avg
    knee = CV_KNEE * full_mwh
    if now_mwh < knee:
        hours = (knee - now_mwh) / p + _cv_hours(full_mwh - knee, p, full_mwh)
    else:
        hours = _cv_hours(full_mwh - now_mwh, p, full_mwh)
    return int(hours * 3600)


def state():
    """{'present', 'ac', 'charging', 'watts', 'full_seconds'}.

    watts > 0 while discharging, < 0 while charging, None if unknown. full_seconds is the estimated time to a full
    charge (Windows reports none, so Steam shows "?h ?m"), None when not charging.
    """
    global _rate_avg
    s = SYSTEM_BATTERY_STATE()
    if _powrprof.CallNtPowerInformation(SystemBatteryState, None, 0, byref(s), sizeof(s)) != 0:
        return None
    rate = s.Rate  # mW, negative while discharging
    watts = None if rate in (0, -0x80000000) else round(-rate / 1000.0, 1)
    full = None
    if s.Charging and rate > 0 and s.MaxCapacity > s.RemainingCapacity:
        full = _time_to_full(s.MaxCapacity, s.RemainingCapacity, rate)
    else:
        _rate_avg = None
    return {"present": bool(s.BatteryPresent), "ac": bool(s.AcOnLine), "charging": bool(s.Charging), "watts": watts,
            "full_seconds": full}
