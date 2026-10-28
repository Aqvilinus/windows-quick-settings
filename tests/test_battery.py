"""The time-to-full estimate (python -m unittest discover tests).

The estimate itself is plain arithmetic; the two pywinrt imports of battery.py are replaced by empty modules, so the
test runs on any Python without the packages built for Decky's.
"""
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "py_modules"))
for _name in ("winrt", "winrt.windows", "winrt.windows.devices", "winrt.windows.system"):
    sys.modules.setdefault(_name, types.ModuleType(_name))
sys.modules["winrt.windows.devices.power"] = types.SimpleNamespace(Battery=None)
sys.modules["winrt.windows.system.power"] = types.SimpleNamespace(BatteryStatus=None)
from winqs import battery  # noqa: E402

FULL = 92_600  # mWh, this device's battery


class TimeToFull(unittest.TestCase):
    def setUp(self):
        battery._rate_avg = None

    def test_constant_power_then_taper(self):
        seconds = battery._time_to_full(FULL, 0.49 * FULL, 38_000)  # measured on the device: 1h46m
        self.assertTrue(106 * 60 <= seconds < 107 * 60, seconds)

    def test_taper_only_near_full(self):
        seconds = battery._time_to_full(FULL, 0.97 * FULL, 5_000)
        self.assertTrue(2 * 60 <= seconds < 3 * 60, seconds)

    def test_average_depends_on_time_not_on_polls(self):
        with mock.patch.object(battery.time, "monotonic", side_effect=[0.0, battery.SMOOTHING_S]):
            battery._time_to_full(FULL, 0.5 * FULL, 38_000)
            battery._time_to_full(FULL, 0.5 * FULL, 19_000)
        # one time constant later the average has moved 1 - 1/e of the way
        self.assertAlmostEqual(battery._rate_avg, 38_000 - (1 - 1 / 2.718281828459045) * 19_000, delta=1)


if __name__ == "__main__":
    unittest.main()
