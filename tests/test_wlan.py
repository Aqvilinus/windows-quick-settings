"""Wi-Fi logic that needs no adapter: profile XML and the merge of same-SSID entries (python -m unittest discover tests)."""
import ctypes
import sys
import types
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "py_modules"))
try:
    from winqs import wlan  # loads wlanapi.dll
except OSError as e:  # e.g. a Windows Server image without the WLAN client
    raise unittest.SkipTest("wlanapi.dll not available: %s" % e) from e

NS = "{http://www.microsoft.com/networking/WLAN/profile/v1}"


def ssid(raw):
    s = wlan.DOT11_SSID()
    s.uSSIDLength = len(raw)
    for i, b in enumerate(raw):
        s.ucSSID[i] = b
    return s


def network(name, secured, auth, known, profile=None, connected=False, quality=50):
    flags = (wlan.WLAN_AVAILABLE_NETWORK_HAS_PROFILE if known else 0) | \
        (wlan.WLAN_AVAILABLE_NETWORK_CONNECTED if connected else 0)
    return types.SimpleNamespace(
        dot11Ssid=ssid(name.encode()), dot11BssType=1, wlanSignalQuality=quality, bSecurityEnabled=secured,
        dot11DefaultAuthAlgorithm=auth, dot11DefaultCipherAlgorithm=4 if secured else 0, dwFlags=flags,
        strProfileName=profile or "")


class ProfileXml(unittest.TestCase):
    def parse(self, raw, name=None, password="pass\x00word&<>"):
        s = ssid(raw)
        return ET.fromstring(wlan.profile_xml(s.text(), s.raw().hex().upper(), 7, 4, password, name))

    def test_raw_ssid_bytes_kept(self):
        for raw in (b"Caf\xe9", "Кафе".encode(), b"A&B <x>"):
            root = self.parse(raw)
            hex_ssid = root.find(NS + "SSIDConfig/" + NS + "SSID/" + NS + "hex").text
            self.assertEqual(bytes.fromhex(hex_ssid), raw)

    def test_control_characters_dropped(self):
        root = self.parse(b"Home\x01\x07Net")
        self.assertEqual(root.find(NS + "name").text, "HomeNet")
        self.assertEqual(root.find(".//" + NS + "keyMaterial").text, "password&<>")

    def test_saved_profile_name(self):
        self.assertEqual(self.parse(b"A&B <x>", name="A&B <x> 2").find(NS + "name").text, "A&B <x> 2")

    def test_raw_key(self):
        root = self.parse(b"Lab", password="ab" * 32)
        self.assertEqual(root.find(".//" + NS + "keyType").text, "networkKey")


class MergeSameSsid(unittest.TestCase):
    def merged(self, items):
        old = wlan._wlan, wlan._items
        wlan._wlan = types.SimpleNamespace(WlanGetAvailableNetworkList=lambda *a: 0, WlanFreeMemory=lambda p: None)
        wlan._items = lambda *a: iter(items)
        try:
            w = wlan.Wlan.__new__(wlan.Wlan)  # no handle: the list call is replaced above
            w.handle, w.dirty = None, False
            (entry,) = w.networks(ctypes.c_int())
            return entry
        finally:
            wlan._wlan, wlan._items = old

    def test_open_twin_cannot_downgrade_saved_network(self):
        for items in ([network("Home", False, 1, False, quality=90), network("Home", True, 7, True, "Home")],
                      [network("Home", True, 7, True, "Home"), network("Home", False, 1, False, quality=90)]):
            e = self.merged(items)
            self.assertTrue(e["known"] and e["secured"])
            self.assertEqual(e["auth"], 7)

    def test_secured_entry_wins_for_a_new_network(self):
        e = self.merged([network("Cafe", False, 1, False), network("Cafe", True, 7, False)])
        self.assertTrue(e["secured"])

    def test_connected_and_best_signal_kept(self):
        e = self.merged([network("Lab", True, 7, False, quality=80),
                         network("Lab", True, 7, True, "Lab", connected=True, quality=40)])
        self.assertTrue(e["connected"] and e["known"])
        self.assertEqual(e["signal"], wlan.signal_bucket(80))


if __name__ == "__main__":
    unittest.main()
