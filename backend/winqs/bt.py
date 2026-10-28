"""Bluetooth devices through WinRT (Windows.Devices.Enumeration), with pywinrt from py_modules. No admin rights needed.

- Paired devices: DeviceWatchers over Windows' own "paired" selectors for classic Bluetooth and Bluetooth LE, kept
  running, so Windows reports devices being added, connected, disconnected or removed and a poll only reads the list.
- Search: two DeviceWatchers over Windows' own "not paired" selectors for classic Bluetooth and Bluetooth LE (these
  start an inquiry). Devices are kept as they are added and updated; the search stops by itself when both watchers
  have finished their first pass, or after SCAN_SECONDS.
- Pairing: DeviceInformationCustomPairing.PairAsync on its own thread. "Confirm only" and "Display PIN" requests are
  accepted at once; for "Confirm PIN match" the handler takes a deferral (the documented way to answer later) and the
  user's answer accepts or declines it.
- Removal: DeviceInformationPairing.UnpairAsync.
"""
import re
import threading
import time

from winrt.windows.devices.bluetooth import BluetoothDevice, BluetoothLEDevice
from winrt.windows.devices.enumeration import (
    DeviceInformation, DeviceInformationKind, DevicePairingKinds, DevicePairingResultStatus, DeviceUnpairingResultStatus,
    DeviceWatcherStatus,
)
from winrt.system import unbox_boolean
from winrt.windows.foundation import IPropertyValue, PropertyType

from .com import init_mta

AEP = DeviceInformationKind.ASSOCIATION_ENDPOINT
P_CATEGORY = "System.Devices.Aep.Category"
P_MAJOR = "System.Devices.Aep.Bluetooth.Cod.Major"
P_CONNECTED = "System.Devices.Aep.IsConnected"
PROPS = [P_CATEGORY, P_MAJOR]
PAIRED_PROPS = [P_CATEGORY, P_MAJOR, P_CONNECTED]
SCAN_SECONDS = 30
PIN_SECONDS = 60
# Major device classes of classic Bluetooth
MAJOR = {1: "computer", 2: "phone", 3: "network", 4: "audio", 5: "peripheral", 6: "imaging", 7: "wearable", 8: "toy",
         9: "health"}
CATEGORY = (("Audio", "audio"), ("Input", "peripheral"), ("Communication.Phone", "phone"), ("Computer", "computer"),
            ("Display", "imaging"), ("Imaging", "imaging"), ("Wearable", "wearable"))


# Association endpoint ids, e.g. Bluetooth#Bluetootha8:72:4d:6b:c4:fb-dc:2c:26:42:13:bc
_MAC = r"(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}"
_DEVICE_ID = re.compile(r"Bluetooth(?:LE)?#Bluetooth(?:LE)?%s-%s" % (_MAC, _MAC))


def is_device_id(device_id):
    return isinstance(device_id, str) and bool(_DEVICE_ID.fullmatch(device_id))


def _prop(info, key):
    try:
        props = info.properties
        return props.lookup(key) if props.has_key(key) else None
    except Exception:  # noqa: BLE001 - a missing or odd property only loses the device type
        return None


def _device_type(info):
    major = _prop(info, P_MAJOR)
    if major is not None:
        try:
            pv = major.as_(IPropertyValue)
            getter = {PropertyType.UINT8: pv.get_uint8, PropertyType.UINT16: pv.get_uint16,
                      PropertyType.UINT32: pv.get_uint32}.get(pv.type)
            t = MAJOR.get(int(getter())) if getter else None
            if t:
                return t
        except Exception:  # noqa: BLE001
            pass
    cat = _prop(info, P_CATEGORY)
    if cat is not None:
        try:
            for c in cat.as_(IPropertyValue).get_string_array():
                for prefix, t in CATEGORY:
                    if c.startswith(prefix):
                        return t
        except Exception:  # noqa: BLE001
            pass
    return "other"


def _describe(info):
    return {"id": info.id, "name": info.name, "type": _device_type(info), "le": info.id.startswith("BluetoothLE#")}


def _connected(info):
    v = _prop(info, P_CONNECTED)
    try:
        return bool(unbox_boolean(v)) if v is not None else False
    except Exception:  # noqa: BLE001
        return False


class _Watch:
    """DeviceWatchers over some selectors, with the devices they report. Windows calls the handlers on its own
    threads, so everything goes through the lock."""

    def __init__(self, selectors, props, log=None):
        self._selectors, self._props = selectors, props
        self._log = log or (lambda *a: None)
        self._lock = threading.Lock()
        self._watchers = []
        self._infos = {}  # id -> DeviceInformation
        self._completed = 0
        self._first_pass = threading.Event()

    def _start(self):
        """Call with the lock held."""
        self._infos.clear()
        self._completed = 0
        self._first_pass.clear()
        for selector in self._selectors():
            w = DeviceInformation.create_watcher(selector, self._props, AEP)
            w.add_added(self._added)
            w.add_updated(self._updated)
            w.add_removed(self._removed)
            w.add_enumeration_completed(self._enumerated)
            self._watchers.append(w)
        for w in self._watchers:
            w.start()

    def stop(self):
        with self._lock:
            watchers, self._watchers = self._watchers, []
        for w in watchers:
            try:
                w.stop()
            except Exception:  # noqa: BLE001 - already stopped
                pass

    def _snapshot(self):
        with self._lock:
            return list(self._infos.values())

    def _added(self, watcher, info):
        with self._lock:
            self._infos[info.id] = info

    def _updated(self, watcher, update):
        with self._lock:
            info = self._infos.get(update.id)
            if info is not None:
                info.update(update)

    def _removed(self, watcher, update):
        with self._lock:
            self._infos.pop(update.id, None)

    def _enumerated(self, watcher, _):
        with self._lock:
            self._completed += 1
            if self._completed >= len(self._watchers):
                self._first_pass.set()


def _selectors(paired):
    return lambda: (BluetoothDevice.get_device_selector_from_pairing_state(paired),
                    BluetoothLEDevice.get_device_selector_from_pairing_state(paired))


def _address(device_id):
    """The device's own address from its endpoint id, as 12 hex digits."""
    return device_id.rsplit("-", 1)[-1].replace(":", "").upper()


class PairedDevices(_Watch):
    """The paired devices, kept current by Windows. The first call waits for the first pass (well under a second)."""

    def __init__(self, log=None):
        super().__init__(_selectors(True), PAIRED_PROPS, log)

    def devices(self):
        with self._lock:
            running = [w for w in self._watchers if w.status in (DeviceWatcherStatus.STARTED,
                                                                 DeviceWatcherStatus.ENUMERATION_COMPLETED)]
            if len(running) != len(self._watchers) or not self._watchers:
                self._watchers = []  # never started, or stopped / aborted by Windows: start over
                self._start()
        self._first_pass.wait(3)
        out = [{"id": i.id, "address": _address(i.id), "name": i.name or _address(i.id), "connected": _connected(i),
                "type": _device_type(i), "le": i.id.startswith("BluetoothLE#")} for i in self._snapshot()]
        out.sort(key=lambda d: (not d["connected"], d["name"].lower()))
        return out


class Scanner(_Watch):
    """Search for devices that can be paired (an inquiry). It stops by itself after SCAN_SECONDS or when the
    watchers have finished their first pass."""

    def __init__(self, log=None):
        super().__init__(_selectors(False), PROPS, log)
        self._until = 0.0

    def start(self):
        with self._lock:
            self._until = time.monotonic() + SCAN_SECONDS
            if not self._watchers:
                self._start()

    def results(self):
        if self._watchers and (time.monotonic() > self._until or self._first_pass.is_set()):
            self.stop()
        devices = [_describe(i) for i in self._snapshot()]
        named = [d for d in devices if d["name"].strip()]  # nameless LE beacons are not something to pair with
        named.sort(key=lambda d: (d["le"], d["name"].lower()))
        return {"scanning": bool(self._watchers), "devices": named}


class Pairing:
    """One pairing at a time, on its own thread. state() is polled by the frontend."""

    KINDS = DevicePairingKinds.CONFIRM_ONLY | DevicePairingKinds.DISPLAY_PIN | DevicePairingKinds.CONFIRM_PIN_MATCH

    def __init__(self, log=None):
        self._log = log or (lambda *a: None)
        self._lock = threading.Lock()
        self._state = {"state": "idle"}
        self._op = None
        self._request = None  # (args, deferral) waiting for the user's answer
        self._thread = None

    def state(self):
        with self._lock:
            return dict(self._state)

    def start(self, device_id):
        with self._lock:
            if self._thread and self._thread.is_alive():
                raise RuntimeError("a pairing is already in progress")
            self._state = {"state": "pairing", "id": device_id}
            self._thread = threading.Thread(target=self._run, args=(device_id,), name="winqs-bt-pair", daemon=True)
            self._thread.start()

    def answer(self, accept):
        """The user's answer to "Confirm PIN match"."""
        with self._lock:
            req, self._request = self._request, None
            if self._state.get("state") == "confirm":
                self._state = dict(self._state, state="pairing")
        if req is None:
            return False
        args, deferral = req
        try:
            if accept:
                args.accept()
        finally:
            deferral.complete()
        return True

    def cancel(self):
        self.answer(False)
        with self._lock:
            op = self._op
        if op is not None:
            try:
                op.cancel()
            except Exception:  # noqa: BLE001 - already finished
                pass

    def _set(self, **kw):
        with self._lock:
            self._state = dict(self._state, **kw)

    def _on_request(self, custom, args):
        kind = args.pairing_kind
        pin = args.pin or ""
        if kind == DevicePairingKinds.CONFIRM_ONLY:
            args.accept()
        elif kind == DevicePairingKinds.DISPLAY_PIN:
            args.accept()  # the PIN is typed on the other device
            self._set(state="display_pin", pin=pin)
        elif kind == DevicePairingKinds.CONFIRM_PIN_MATCH:
            deferral = args.get_deferral()
            with self._lock:
                self._request = (args, deferral)
                self._state = dict(self._state, state="confirm", pin=pin)
            timer = threading.Timer(PIN_SECONDS, self._expire, args=(deferral,))
            timer.daemon = True  # never holds up the plugin's exit
            timer.start()
        # other kinds (e.g. "Provide PIN") are left unanswered, which declines them

    def _expire(self, deferral):
        with self._lock:
            mine = self._request is not None and self._request[1] is deferral
        if mine:
            self.answer(False)

    def _run(self, device_id):
        init_mta()
        custom = token = None
        try:
            info = DeviceInformation.create_from_id_async(device_id, PROPS, AEP).get()
            self._set(name=info.name)
            if info.pairing.is_paired:
                self._set(state="done", status="AlreadyPaired")
                return
            custom = info.pairing.custom
            token = custom.add_pairing_requested(self._on_request)
            op = custom.pair_async(self.KINDS)
            with self._lock:
                self._op = op
            result = op.get()
            status = DevicePairingResultStatus(result.status)
            ok = status in (DevicePairingResultStatus.PAIRED, DevicePairingResultStatus.ALREADY_PAIRED)
            cancelled = status == DevicePairingResultStatus.PAIRING_CANCELED
            self._set(state="done" if ok else ("cancelled" if cancelled else "failed"), status=status.name)
        except Exception as e:  # noqa: BLE001 - a cancelled operation raises too
            with self._lock:
                was_cancel = self._op is not None and self._state.get("state") in ("pairing", "confirm")
            self._log("bluetooth pairing failed: %r" % e)
            self._set(state="cancelled" if was_cancel and "cancel" in repr(e).lower() else "failed", status=str(e))
        finally:
            with self._lock:
                self._op = None
                req, self._request = self._request, None
            if req is not None:
                try:
                    req[1].complete()
                except Exception:  # noqa: BLE001
                    pass
            if custom is not None and token is not None:
                try:
                    custom.remove_pairing_requested(token)
                except Exception:  # noqa: BLE001
                    pass


def unpair(device_id):
    """Remove a paired device by its endpoint id."""
    info = DeviceInformation.create_from_id_async(device_id, PROPS, AEP).get()
    if not info.pairing.is_paired:
        return "NotPaired"
    status = DeviceUnpairingResultStatus(info.pairing.unpair_async().get().status)
    if status not in (DeviceUnpairingResultStatus.UNPAIRED, DeviceUnpairingResultStatus.ALREADY_UNPAIRED):
        raise OSError("unpairing failed: %s" % status.name)
    return status.name
