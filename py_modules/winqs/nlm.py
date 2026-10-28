"""Internet status the way the Windows network icon shows it: WinRT Windows.Networking.Connectivity (pywinrt).

NetworkConnectivityLevel is Windows' own verdict from its connectivity probe (NCSI). ConstrainedInternetAccess means
the probe was answered by a sign-in page (hotel / cafe Wi-Fi).

Reading it costs ~1.7 ms, so the answer is kept until Windows reports a network change (NetworkStatusChanged, which
also fires when the connectivity level changes), and at most 30 s as a safety net.
"""
import time

from winrt.windows.networking.connectivity import NetworkConnectivityLevel as Level, NetworkInformation

STATUS = {Level.INTERNET_ACCESS: "online", Level.CONSTRAINED_INTERNET_ACCESS: "portal",
          Level.LOCAL_ACCESS: "no_internet"}
MAX_AGE = 30  # s

_cached = None   # (status, time read)
_watching = False


def _changed(_sender):
    global _cached
    _cached = None


def status():
    """'online' | 'portal' (sign-in page needed) | 'no_internet' (local network only) | 'offline'."""
    global _cached, _watching
    if not _watching:
        NetworkInformation.add_network_status_changed(_changed)  # for the life of the process
        _watching = True
    cached = _cached
    if cached is None or time.monotonic() - cached[1] > MAX_AGE:
        cached = _cached = (_read(), time.monotonic())
    return cached[0]


def _read():
    profile = NetworkInformation.get_internet_connection_profile()
    level = profile.get_network_connectivity_level() if profile is not None else Level.NONE
    if level == Level.NONE:
        # no profile is used for the internet: a network may still be connected without it
        levels = [p.get_network_connectivity_level() for p in NetworkInformation.get_connection_profiles()]
        level = max(levels, default=Level.NONE)
    return STATUS.get(level, "offline")
