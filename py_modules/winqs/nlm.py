"""Internet status the way the Windows network icon shows it: WinRT Windows.Networking.Connectivity (pywinrt).

NetworkConnectivityLevel is Windows' own verdict from its connectivity probe (NCSI). ConstrainedInternetAccess means
the probe was answered by a sign-in page (hotel / cafe Wi-Fi).
"""
from winrt.windows.networking.connectivity import NetworkConnectivityLevel as Level, NetworkInformation

STATUS = {Level.INTERNET_ACCESS: "online", Level.CONSTRAINED_INTERNET_ACCESS: "portal",
          Level.LOCAL_ACCESS: "no_internet"}


def status():
    """'online' | 'portal' (sign-in page needed) | 'no_internet' (local network only) | 'offline'."""
    profile = NetworkInformation.get_internet_connection_profile()
    level = profile.get_network_connectivity_level() if profile is not None else Level.NONE
    if level == Level.NONE:
        # no profile is used for the internet: a network may still be connected without it
        levels = [p.get_network_connectivity_level() for p in NetworkInformation.get_connection_profiles()]
        level = max(levels, default=Level.NONE)
    return STATUS.get(level, "offline")
