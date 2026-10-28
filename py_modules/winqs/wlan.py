"""Wi-Fi status, scan, connect and disconnect through the Native Wifi API (wlanapi.dll)."""
import ctypes
import threading
from ctypes import POINTER, byref, c_void_p, wintypes
from xml.sax.saxutils import escape

from .com import GUID

_wlan = ctypes.WinDLL("wlanapi")

ERROR_SUCCESS = 0
ERROR_ACCESS_DENIED = 5


class LocationBlocked(OSError):
    """Windows 11 hides Wi-Fi networks from desktop apps while Location access is off."""


class DOT11_SSID(ctypes.Structure):
    _fields_ = [("uSSIDLength", wintypes.ULONG), ("ucSSID", ctypes.c_ubyte * 32)]

    def text(self):
        raw = bytes(self.ucSSID[: self.uSSIDLength])
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            return raw.decode("latin-1")


class WLAN_INTERFACE_INFO(ctypes.Structure):
    _fields_ = [("InterfaceGuid", GUID), ("strInterfaceDescription", wintypes.WCHAR * 256), ("isState", wintypes.DWORD)]


class WLAN_INTERFACE_INFO_LIST(ctypes.Structure):
    _fields_ = [("dwNumberOfItems", wintypes.DWORD), ("dwIndex", wintypes.DWORD), ("InterfaceInfo", WLAN_INTERFACE_INFO * 1)]


class WLAN_AVAILABLE_NETWORK(ctypes.Structure):
    _fields_ = [
        ("strProfileName", wintypes.WCHAR * 256),
        ("dot11Ssid", DOT11_SSID),
        ("dot11BssType", wintypes.DWORD),
        ("uNumberOfBssids", wintypes.ULONG),
        ("bNetworkConnectable", wintypes.BOOL),
        ("wlanNotConnectableReason", wintypes.DWORD),
        ("uNumberOfPhyTypes", wintypes.ULONG),
        ("dot11PhyTypes", wintypes.DWORD * 8),
        ("bMorePhyTypes", wintypes.BOOL),
        ("wlanSignalQuality", wintypes.ULONG),
        ("bSecurityEnabled", wintypes.BOOL),
        ("dot11DefaultAuthAlgorithm", wintypes.DWORD),
        ("dot11DefaultCipherAlgorithm", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("dwReserved", wintypes.DWORD),
    ]


class WLAN_AVAILABLE_NETWORK_LIST(ctypes.Structure):
    _fields_ = [("dwNumberOfItems", wintypes.DWORD), ("dwIndex", wintypes.DWORD), ("Network", WLAN_AVAILABLE_NETWORK * 1)]


class WLAN_CONNECTION_PARAMETERS(ctypes.Structure):
    _fields_ = [
        ("wlanConnectionMode", wintypes.DWORD),
        ("strProfile", wintypes.LPCWSTR),
        ("pDot11Ssid", c_void_p),
        ("pDesiredBssidList", c_void_p),
        ("dot11BssType", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
    ]


class WLAN_NOTIFICATION_DATA(ctypes.Structure):
    _fields_ = [("NotificationSource", wintypes.DWORD), ("NotificationCode", wintypes.DWORD),
                ("InterfaceGuid", GUID), ("dwDataSize", wintypes.DWORD), ("pData", c_void_p)]


class WLAN_CONNECTION_NOTIFICATION_DATA(ctypes.Structure):
    _fields_ = [("wlanConnectionMode", wintypes.DWORD), ("strProfileName", wintypes.WCHAR * 256),
                ("dot11Ssid", DOT11_SSID), ("dot11BssType", wintypes.DWORD), ("bSecurityEnabled", wintypes.BOOL),
                ("wlanReasonCode", wintypes.DWORD), ("dwFlags", wintypes.DWORD)]


WLAN_NOTIFICATION_CALLBACK = ctypes.WINFUNCTYPE(None, POINTER(WLAN_NOTIFICATION_DATA), c_void_p)
WLAN_NOTIFICATION_SOURCE_NONE = 0
WLAN_NOTIFICATION_SOURCE_ACM = 0x8
# wlan_notification_acm_* codes
ACM_SCAN_COMPLETE, ACM_SCAN_FAIL = 7, 8
ACM_CONNECTION_COMPLETE, ACM_CONNECTION_ATTEMPT_FAIL = 10, 11
ACM_INTERFACE_ARRIVAL, ACM_INTERFACE_REMOVAL = 13, 14
ACM_DISCONNECTED = 21
ACM_SCAN_LIST_REFRESH = 26
_DIRTY_CODES = {ACM_SCAN_COMPLETE, ACM_SCAN_FAIL, ACM_CONNECTION_COMPLETE, ACM_CONNECTION_ATTEMPT_FAIL,
                ACM_INTERFACE_ARRIVAL, ACM_INTERFACE_REMOVAL, ACM_DISCONNECTED, ACM_SCAN_LIST_REFRESH}

_wlan.WlanRegisterNotification.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.BOOL, WLAN_NOTIFICATION_CALLBACK,
                                           c_void_p, c_void_p, POINTER(wintypes.DWORD)]
_wlan.WlanRegisterNotification.restype = wintypes.DWORD
_wlan.WlanOpenHandle.argtypes = [wintypes.DWORD, c_void_p, POINTER(wintypes.DWORD), POINTER(wintypes.HANDLE)]
_wlan.WlanCloseHandle.argtypes = [wintypes.HANDLE, c_void_p]
_wlan.WlanEnumInterfaces.argtypes = [wintypes.HANDLE, c_void_p, POINTER(c_void_p)]
_wlan.WlanFreeMemory.argtypes = [c_void_p]
_wlan.WlanFreeMemory.restype = None
_wlan.WlanQueryInterface.argtypes = [wintypes.HANDLE, POINTER(GUID), wintypes.DWORD, c_void_p,
                                     POINTER(wintypes.DWORD), POINTER(c_void_p), POINTER(wintypes.DWORD)]
_wlan.WlanScan.argtypes = [wintypes.HANDLE, POINTER(GUID), c_void_p, c_void_p, c_void_p]
_wlan.WlanGetAvailableNetworkList.argtypes = [wintypes.HANDLE, POINTER(GUID), wintypes.DWORD, c_void_p, POINTER(c_void_p)]
_wlan.WlanConnect.argtypes = [wintypes.HANDLE, POINTER(GUID), POINTER(WLAN_CONNECTION_PARAMETERS), c_void_p]
_wlan.WlanDisconnect.argtypes = [wintypes.HANDLE, POINTER(GUID), c_void_p]
_wlan.WlanSetProfile.argtypes = [wintypes.HANDLE, POINTER(GUID), wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR,
                                 wintypes.BOOL, c_void_p, POINTER(wintypes.DWORD)]
_wlan.WlanDeleteProfile.argtypes = [wintypes.HANDLE, POINTER(GUID), wintypes.LPCWSTR, c_void_p]
_wlan.WlanGetProfileList.argtypes = [wintypes.HANDLE, POINTER(GUID), c_void_p, POINTER(c_void_p)]
_wlan.WlanReasonCodeToString.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.LPWSTR, c_void_p]
_wlan.WlanReasonCodeToString.restype = wintypes.DWORD


def reason_text(code):
    """Windows' own (localized) description of a WLAN_REASON_CODE, or None."""
    buf = ctypes.create_unicode_buffer(512)
    if _wlan.WlanReasonCodeToString(code, len(buf), buf, None) != ERROR_SUCCESS:
        return None
    return buf.value.strip() or None


class WLAN_PROFILE_INFO(ctypes.Structure):
    _fields_ = [("strProfileName", wintypes.WCHAR * 256), ("dwFlags", wintypes.DWORD)]


class WLAN_PROFILE_INFO_LIST(ctypes.Structure):
    _fields_ = [("dwNumberOfItems", wintypes.DWORD), ("dwIndex", wintypes.DWORD), ("ProfileInfo", WLAN_PROFILE_INFO * 1)]


WLAN_PROFILE_GROUP_POLICY = 1
for _f in ("WlanOpenHandle", "WlanCloseHandle", "WlanEnumInterfaces", "WlanQueryInterface", "WlanScan",
           "WlanGetAvailableNetworkList", "WlanConnect", "WlanDisconnect", "WlanSetProfile", "WlanDeleteProfile",
           "WlanGetProfileList"):
    getattr(_wlan, _f).restype = wintypes.DWORD

# DOT11_AUTH_ALGORITHM -> (profile <authentication>, label)
AUTH = {
    1: ("open", "Open"),
    2: ("shared", "WEP"),
    3: ("WPA", "WPA Enterprise"),
    4: ("WPAPSK", "WPA"),
    6: ("WPA2", "WPA2 Enterprise"),
    7: ("WPA2PSK", "WPA2"),
    8: ("WPA3ENT192", "WPA3 Enterprise"),
    9: ("WPA3SAE", "WPA3"),
    10: ("OWE", "OWE"),
    11: ("WPA3ENT", "WPA3 Enterprise"),
}
# auth algorithms we can create a profile for from the plugin (personal / open)
SUPPORTED_NEW = {1, 4, 7, 9}

WLAN_AVAILABLE_NETWORK_CONNECTED = 1
WLAN_AVAILABLE_NETWORK_HAS_PROFILE = 2


def signal_bucket(q):
    """0-100 signal quality -> the 4 levels the UI draws, so a polled list only changes when the icon would."""
    return 100 if q >= 75 else 75 if q >= 50 else 50 if q >= 25 else 25


def _items(p, list_type, field, item_type):
    """The items of a WLAN_*_LIST that Windows returned at `p`: dwNumberOfItems entries of `item_type` starting at
    the `field` member (declared with length 1, as in wlanapi.h)."""
    lst = list_type.from_address(p.value)
    return (item_type * lst.dwNumberOfItems).from_address(p.value + getattr(list_type, field).offset)


class Wlan:
    def __init__(self):
        self.handle = wintypes.HANDLE()
        ver = wintypes.DWORD()
        rc = _wlan.WlanOpenHandle(2, None, byref(ver), byref(self.handle))
        if rc != ERROR_SUCCESS:
            raise OSError(rc, "WlanOpenHandle failed")
        # Change notifications: the callback runs on a WLAN service thread and only records what
        # happened, so the network list is re-read only when something actually changed.
        self.dirty = True                 # network list / interface may have changed
        self.interface_changed = True
        self.scan_done = threading.Event()
        self._conn_lock = threading.Lock()
        self._conn_result = {}            # ssid -> (ok, reason code)
        self.notifications = False
        self._cb = WLAN_NOTIFICATION_CALLBACK(self._on_notification)  # keep a reference while registered
        prev = wintypes.DWORD()
        rc = _wlan.WlanRegisterNotification(self.handle, WLAN_NOTIFICATION_SOURCE_ACM, True, self._cb, None, None,
                                            byref(prev))
        self.notifications = rc == ERROR_SUCCESS

    def _on_notification(self, data, _ctx):
        try:
            d = data.contents
            code = d.NotificationCode
            if d.NotificationSource != WLAN_NOTIFICATION_SOURCE_ACM or code not in _DIRTY_CODES:
                return
            self.dirty = True
            if code in (ACM_INTERFACE_ARRIVAL, ACM_INTERFACE_REMOVAL):
                self.interface_changed = True
            elif code in (ACM_SCAN_COMPLETE, ACM_SCAN_FAIL):
                self.scan_done.set()
            elif code in (ACM_CONNECTION_COMPLETE, ACM_CONNECTION_ATTEMPT_FAIL) and d.pData and                     d.dwDataSize >= ctypes.sizeof(WLAN_CONNECTION_NOTIFICATION_DATA):
                c = ctypes.cast(d.pData, POINTER(WLAN_CONNECTION_NOTIFICATION_DATA)).contents
                ok = code == ACM_CONNECTION_COMPLETE and c.wlanReasonCode == 0
                with self._conn_lock:
                    self._conn_result[c.dot11Ssid.text()] = (ok, int(c.wlanReasonCode))
        except Exception:  # noqa: BLE001 - never raise into the WLAN service thread
            self.dirty = True

    def take_connection_result(self, ssid):
        """(ok, reason) once Windows reported the outcome of connecting to ssid, else None."""
        with self._conn_lock:
            return self._conn_result.pop(ssid, None)

    def clear_connection_result(self, ssid):
        with self._conn_lock:
            self._conn_result.pop(ssid, None)

    def close(self):
        if self.handle:
            if self.notifications:
                _wlan.WlanRegisterNotification(self.handle, WLAN_NOTIFICATION_SOURCE_NONE, True,
                                               WLAN_NOTIFICATION_CALLBACK(), None, None, None)
                self.notifications = False
            _wlan.WlanCloseHandle(self.handle, None)
            self.handle = wintypes.HANDLE()

    def interface(self):
        """Return (GUID, description, state) of the first Wi-Fi interface, or None."""
        p = c_void_p()
        rc = _wlan.WlanEnumInterfaces(self.handle, None, byref(p))
        if rc != ERROR_SUCCESS:
            raise OSError(rc, "WlanEnumInterfaces failed")
        try:
            arr = _items(p, WLAN_INTERFACE_INFO_LIST, "InterfaceInfo", WLAN_INTERFACE_INFO)
            if not arr:
                return None
            info = arr[0]
            return GUID.from_buffer_copy(info.InterfaceGuid), info.strInterfaceDescription, info.isState
        finally:
            _wlan.WlanFreeMemory(p)

    def scan(self, guid):
        """Start a scan and return at once; scan_done is set when Windows reports the result."""
        self.scan_done.clear()
        return _wlan.WlanScan(self.handle, byref(guid), None, None, None)

    def networks(self, guid):
        self.dirty = False  # before reading: a change reported meanwhile marks it dirty again
        p = c_void_p()
        rc = _wlan.WlanGetAvailableNetworkList(self.handle, byref(guid), 0, None, byref(p))
        if rc == ERROR_ACCESS_DENIED:
            raise LocationBlocked(rc, "Location access is off for desktop apps")
        if rc != ERROR_SUCCESS:
            raise OSError(rc, "WlanGetAvailableNetworkList failed")
        best = {}
        try:
            for net in _items(p, WLAN_AVAILABLE_NETWORK_LIST, "Network", WLAN_AVAILABLE_NETWORK):
                ssid = net.dot11Ssid.text()
                if not ssid or net.dot11BssType != 1:  # skip hidden and ad-hoc
                    continue
                entry = {
                    "ssid": ssid,
                    "signal": signal_bucket(int(net.wlanSignalQuality)),
                    "secured": bool(net.bSecurityEnabled),
                    "auth": int(net.dot11DefaultAuthAlgorithm),
                    "security": AUTH.get(net.dot11DefaultAuthAlgorithm, ("", "?"))[1],
                    "cipher": int(net.dot11DefaultCipherAlgorithm),
                    "connected": bool(net.dwFlags & WLAN_AVAILABLE_NETWORK_CONNECTED),
                    "known": bool(net.dwFlags & WLAN_AVAILABLE_NETWORK_HAS_PROFILE),
                    "profile": net.strProfileName or None,
                }
                entry["can_add"] = entry["auth"] in SUPPORTED_NEW
                old = best.get(ssid)
                if old is None:
                    best[ssid] = entry
                else:  # merge the profile entry and the plain entries of the same SSID
                    old["connected"] = old["connected"] or entry["connected"]
                    old["signal"] = max(old["signal"], entry["signal"])
                    # The security comes from the entry that matched the saved profile, else from a secured entry:
                    # an open access point with the same name must not decide how a saved WPA network is rewritten.
                    if (entry["known"] and not old["known"]) or \
                            (entry["known"] == old["known"] and entry["secured"] and not old["secured"]):
                        for k in ("known", "profile", "secured", "auth", "security", "cipher", "can_add"):
                            old[k] = entry[k]
        finally:
            _wlan.WlanFreeMemory(p)
        return sorted(best.values(), key=lambda e: (not e["connected"], not e["known"], -e["signal"], e["ssid"].lower()))

    def connect_profile(self, guid, profile):
        params = WLAN_CONNECTION_PARAMETERS(0, profile, None, None, 1, 0)  # wlan_connection_mode_profile, infrastructure
        rc = _wlan.WlanConnect(self.handle, byref(guid), byref(params), None)
        if rc != ERROR_SUCCESS:
            raise OSError(rc, "WlanConnect failed")

    def disconnect(self, guid):
        rc = _wlan.WlanDisconnect(self.handle, byref(guid), None)
        if rc != ERROR_SUCCESS:
            raise OSError(rc, "WlanDisconnect failed")

    def set_profile(self, guid, xml):
        reason = wintypes.DWORD()
        rc = _wlan.WlanSetProfile(self.handle, byref(guid), 0, xml, None, True, None, byref(reason))
        if rc != ERROR_SUCCESS:
            raise OSError(rc, "WlanSetProfile failed (reason %d)" % reason.value)

    def delete_profile(self, guid, name):
        return _wlan.WlanDeleteProfile(self.handle, byref(guid), name, None)

    def profile_flags(self, guid):
        """{profile name: flags} of the saved Wi-Fi profiles (flag 1 = set by group policy, read-only)."""
        p = c_void_p()
        rc = _wlan.WlanGetProfileList(self.handle, byref(guid), None, byref(p))
        if rc != ERROR_SUCCESS:
            raise OSError(rc, "WlanGetProfileList failed")
        try:
            return {i.strProfileName: int(i.dwFlags)
                    for i in _items(p, WLAN_PROFILE_INFO_LIST, "ProfileInfo", WLAN_PROFILE_INFO)}
        finally:
            _wlan.WlanFreeMemory(p)


def profile_xml(ssid, auth, cipher, password):
    """WLAN profile for an open / WPA-PSK / WPA2-PSK / WPA3-SAE network."""
    hex_ssid = ssid.encode("utf-8").hex().upper()
    authentication = AUTH[auth][0]
    if auth == 1:
        encryption, key = "none", ""
    else:
        encryption = "TKIP" if cipher == 2 else "AES"
        pwd = "".join(ch for ch in (password or "") if ch >= " ")  # no control characters in the XML
        # 64 hex digits is a raw key, 8-63 characters a passphrase (WPA rules)
        raw = len(pwd) == 64 and all(c in "0123456789abcdefABCDEF" for c in pwd)
        key = ("<sharedKey><keyType>%s</keyType><protected>false</protected>"
               "<keyMaterial>%s</keyMaterial></sharedKey>" % ("networkKey" if raw else "passPhrase", escape(pwd)))
    return (
        '<?xml version="1.0"?>'
        '<WLANProfile xmlns="http://www.microsoft.com/networking/WLAN/profile/v1">'
        "<name>%s</name>"
        "<SSIDConfig><SSID><hex>%s</hex><name>%s</name></SSID></SSIDConfig>"
        "<connectionType>ESS</connectionType><connectionMode>auto</connectionMode>"
        "<MSM><security><authEncryption><authentication>%s</authentication>"
        "<encryption>%s</encryption><useOneX>false</useOneX></authEncryption>%s</security></MSM>"
        "</WLANProfile>"
    ) % (escape(ssid), hex_ssid, escape(ssid), authentication, encryption, key)
