"""Internet status the way the Windows network icon shows it, from the Network List Manager (COM, no admin).

  INetworkListManager (IDispatch-based): 9 GetNetworkConnections, 13 GetConnectivity(NLM_CONNECTIVITY*)
  IEnumNetworkConnections:               8 Next(ULONG, INetworkConnection**, ULONG*)
  INetworkConnection:                    10 GetConnectivity, QueryInterface -> IPropertyBag
  IPropertyBag:                          3 Read(LPCOLESTR, VARIANT*, IErrorLog*)

The connection property bag's NA_InternetConnectivityV4/V6 carries NLM_INTERNET_CONNECTIVITY_WEBHIJACK when
Windows' connectivity probe was answered by a sign-in page (hotel / cafe Wi-Fi).
"""
import ctypes
from ctypes import POINTER, byref, c_uint32, c_void_p, c_wchar_p

from .com import check, co_create, qi, release, vcall

CLSID_NetworkListManager = "DCB00C01-570F-4A9B-8D69-199FDBA5723B"
IID_INetworkListManager = "DCB00000-570F-4A9B-8D69-199FDBA5723B"
IID_IPropertyBag = "55272A00-42CB-11CE-8135-00AA004BB851"

IPV4_INTERNET, IPV6_INTERNET = 0x40, 0x400
LOCAL = 0x10 | 0x20 | 0x100 | 0x200  # subnet / local network, IPv4 and IPv6
WEBHIJACK = 0x1
VT_UI4 = 19


class VARIANT(ctypes.Structure):
    _fields_ = [("vt", ctypes.c_ushort), ("r1", ctypes.c_ushort), ("r2", ctypes.c_ushort), ("r3", ctypes.c_ushort),
                ("value", ctypes.c_uint64), ("extra", ctypes.c_uint64)]


def _bag_flags(conn):
    """NA_InternetConnectivityV4 | V6 of one connection (0 if unavailable)."""
    flags = 0
    try:
        bag = qi(conn, IID_IPropertyBag)
    except OSError:
        return 0
    try:
        for name in ("NA_InternetConnectivityV4", "NA_InternetConnectivityV6"):
            v = VARIANT()
            if vcall(bag, 3, [c_wchar_p, POINTER(VARIANT), c_void_p], name, byref(v), None) >= 0 and v.vt == VT_UI4:
                flags |= v.value & 0xFFFFFFFF
    finally:
        release(bag)
    return flags


def _sign_in_needed(nlm):
    enum = c_void_p()
    if vcall(nlm, 9, [POINTER(c_void_p)], byref(enum)) < 0 or not enum:
        return False
    try:
        for _ in range(16):
            conn, got = c_void_p(), c_uint32()
            if vcall(enum, 8, [c_uint32, POINTER(c_void_p), POINTER(c_uint32)], 1, byref(conn), byref(got)) != 0 or not got.value:
                return False
            try:
                if _bag_flags(conn) & WEBHIJACK:
                    return True
            finally:
                release(conn)
    finally:
        release(enum)
    return False


def status():
    """'online' | 'portal' (sign-in page needed) | 'no_internet' (local network only) | 'offline'."""
    nlm = co_create(CLSID_NetworkListManager, IID_INetworkListManager)
    try:
        c = c_uint32()
        check(vcall(nlm, 13, [POINTER(c_uint32)], byref(c)), "INetworkListManager.GetConnectivity")
        flags = c.value
        if flags & (IPV4_INTERNET | IPV6_INTERNET):
            return "online"
        if flags & LOCAL:
            return "portal" if _sign_in_needed(nlm) else "no_internet"
        return "offline"
    finally:
        release(nlm)
