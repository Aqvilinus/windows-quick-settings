"""Estimated time to a full charge: WinRT Windows.Devices.Power (pywinrt), no admin.

Battery.AggregateBattery combines all batteries the way the Windows battery icon does. Its report gives the rate
(mW; positive while charging, negative while discharging) and the capacities (mWh).
"""
import math
import time

from winrt.windows.devices.power import Battery
from winrt.windows.system.power import BatteryStatus

CV_KNEE = 0.8      # Li-ion: about constant power up to ~80 % (CC), then constant voltage (CV) with a falling current
CV_END = 0.05      # the charger stops when the power falls to about C/20
SMOOTHING_S = 20   # time constant of the rate average: the same result however often the frontend polls
_rate_avg = None   # smoothed charge rate in mW while charging
_rate_time = 0.0


def _cv_hours(gap_mwh, p_mw, full_mwh):
    """Hours for the CV phase: the power decays in proportion to the missing charge (P = k * gap) until C/20."""
    p_end = CV_END * full_mwh  # mW
    if p_mw <= p_end:
        return gap_mwh / p_mw
    return math.log(p_mw / p_end) * gap_mwh / p_mw  # t = ln(P / P_end) / k, k = P / gap


def _time_to_full(full_mwh, now_mwh, rate_mw):
    """Seconds to a full charge: the smoothed power up to the knee, then the CV taper."""
    global _rate_avg, _rate_time
    now = time.monotonic()
    if _rate_avg is None:
        _rate_avg = rate_mw
    else:  # exponential average over time: a sample's weight grows with the time since the last one
        _rate_avg += (1 - math.exp(-(now - _rate_time) / SMOOTHING_S)) * (rate_mw - _rate_avg)
    _rate_time = now
    p = _rate_avg
    knee = CV_KNEE * full_mwh
    if now_mwh < knee:
        hours = (knee - now_mwh) / p + _cv_hours(full_mwh - knee, p, full_mwh)
    else:
        hours = _cv_hours(full_mwh - now_mwh, p, full_mwh)
    return int(hours * 3600)


def state():
    """{'full_seconds'}: the estimated time to a full charge (Windows reports none, so Steam shows "?h ?m"), None when
    not charging."""
    global _rate_avg
    report = Battery.aggregate_battery.get_report()
    rate = report.charge_rate_in_milliwatts  # None when unknown
    full, now = report.full_charge_capacity_in_milliwatt_hours, report.remaining_capacity_in_milliwatt_hours
    full_seconds = None
    if report.status == BatteryStatus.CHARGING and rate and rate > 0 and full and now is not None and full > now:
        full_seconds = _time_to_full(full, now, rate)
    else:
        _rate_avg = None
    return {"full_seconds": full_seconds}
