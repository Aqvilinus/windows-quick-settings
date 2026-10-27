"""All system calls run on one dedicated thread (one COM/WinRT apartment, one wlan handle)."""
import concurrent.futures
import json
import os
import time

from . import audio, battery, brightness, bt, btaudio, display, hdr, nightlight, nlm, radios
from .framelimit import IntelFrameLimit
from .rtss import RtssFrameLimit
from .com import init_worker
from .wlan import SUPPORTED_NEW, WLAN_PROFILE_GROUP_POLICY, LocationBlocked, Wlan, profile_xml, reason_text

# WLAN errors after which the client handle is useless (service restarted, RPC broken): reopen once.
WLAN_REOPEN_ERRORS = {6, 1702, 1722, 1726, 1727, 1753}
SCAN_EVERY = 30         # s; only while Wi-Fi is on but not connected (a scan disturbs a connected link)
NETWORKS_MAX_AGE = 20   # s; with notifications the list is re-read on changes, this is only a safety net


class SystemService:
    def __init__(self, state_dir, log=None):
        self.state_file = os.path.join(state_dir, "state.json")
        self.log = log or (lambda *a: None)
        self.pool = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="winqs-sys",
                                                          initializer=init_worker)
        self._wlan = None
        self._guid = None
        self._nets = []
        self._nets_time = 0.0
        self._last_scan = 0.0
        self._frames = IntelFrameLimit()  # used on the worker thread only
        self._rtss = RtssFrameLimit()       # DX12 / Vulkan too, once backend/setup_rtss.ps1 has run
        self._intel_cleared = False

    # ---- infrastructure -------------------------------------------------------------
    def submit(self, fn, *args):
        return self.pool.submit(fn, *args)

    def shutdown(self):
        def _close():
            if self._wlan:
                self._wlan.close()
                self._wlan = None
        try:
            self.pool.submit(_close).result(timeout=5)
        except Exception:
            pass
        self.pool.shutdown(wait=False, cancel_futures=True)

    def _wl(self):
        if self._wlan is None:
            self._wlan = Wlan()
        return self._wlan

    def _reset_wlan(self):
        if self._wlan is not None:
            try:
                self._wlan.close()
            except Exception:  # noqa: BLE001
                pass
        self._wlan, self._guid, self._nets_time = None, None, 0.0

    def _wifi(self, fn):
        """Run a WLAN operation; if the handle went bad (e.g. the WLAN service restarted), reopen and retry once."""
        try:
            return fn()
        except OSError as e:
            if e.errno not in WLAN_REOPEN_ERRORS:
                raise
            self.log("WLAN handle reset after error %s" % e.errno)
            self._reset_wlan()
            return fn()

    def _iface(self):
        wl = self._wl()
        if self._guid is None or wl.interface_changed:
            wl.interface_changed = False
            info = wl.interface()
            self._guid = info[0] if info else None
        if self._guid is None:
            raise RuntimeError("no Wi-Fi adapter")
        return self._guid

    def _networks(self, max_age=NETWORKS_MAX_AGE):
        """Network list, re-read only when Windows reported a change (or it is older than max_age)."""
        wl = self._wl()
        guid = self._iface()
        if wl.dirty or not wl.notifications or time.monotonic() - self._nets_time > max_age:
            self._nets = wl.networks(guid)
            self._nets_time = time.monotonic()
        return self._nets

    def wlan_notifications(self):
        return bool(self._wlan is not None and self._wlan.notifications)

    def scan_event(self):
        return self._wlan.scan_done if self._wlan is not None and self._wlan.notifications else None

    def _load(self):
        try:
            with open(self.state_file, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    def _save(self, data):
        os.makedirs(os.path.dirname(self.state_file), exist_ok=True)
        tmp = self.state_file + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f)
        os.replace(tmp, self.state_file)

    # ---- state --------------------------------------------------------------------
    def state(self):
        out = {"radios": {"wifi": None, "bluetooth": None}, "bluetooth": [], "brightness": None,
               "airplane": False, "errors": {}}
        try:
            out["radios"] = radios.get_states()
        except Exception as e:  # noqa: BLE001 - report, keep going
            out["errors"]["radios"] = str(e)
        out["wifi_networks"] = []
        try:
            if out["radios"].get("wifi") == "on":
                nets = self._wifi(self._networks)
                if not any(n["connected"] for n in nets) and time.monotonic() - self._last_scan > SCAN_EVERY:
                    self._wifi(lambda: self._wl().scan(self._iface()))  # result arrives as a notification
                    self._last_scan = time.monotonic()
                out["wifi_networks"] = nets
                if any(n["connected"] for n in nets):
                    try:
                        out["internet"] = nlm.status()  # ~1 ms
                    except Exception as e:  # noqa: BLE001
                        out["errors"]["internet"] = str(e)
        except LocationBlocked:
            out["wifi_location_off"] = True
        except Exception as e:  # noqa: BLE001
            out["errors"]["wifi"] = str(e)
        out["bt_devices"] = []
        if out["radios"].get("bluetooth") == "on":
            try:
                out["bt_devices"] = self.bluetooth_devices()
                out["bluetooth"] = [d for d in out["bt_devices"] if d["connected"]]
            except Exception as e:  # noqa: BLE001
                out["errors"]["bluetooth"] = str(e)
        try:
            h = hdr.state()  # ~1 ms; shown in Quick Settings next to Night mode
            out["hdr"] = h if h.get("supported") else None
        except Exception as e:  # noqa: BLE001
            out["hdr"] = None
            out["errors"]["hdr"] = str(e)
        try:
            out["night"] = nightlight.is_enabled()
        except Exception as e:  # noqa: BLE001
            out["night"] = None
            out["errors"]["night"] = str(e)
        try:
            out["brightness"] = brightness.get_level()
        except Exception as e:  # noqa: BLE001
            out["errors"]["brightness"] = str(e)
        out["audio"] = {}
        out["audio_devices"] = {}
        for flow in ("output", "input"):
            try:
                out["audio"][flow] = audio.get(flow)
            except Exception as e:  # noqa: BLE001
                out["audio"][flow] = None
                out["errors"]["audio_" + flow] = str(e)
            try:
                out["audio_devices"][flow] = [{"id": d["id"], "name": d["name"], "default": d["default"]}
                                              for d in audio.devices(flow)]
            except Exception as e:  # noqa: BLE001
                out["audio_devices"][flow] = []
                out["errors"]["audio_devices_" + flow] = str(e)
        r = out["radios"]
        present = [v for v in r.values() if v is not None]
        out["airplane"] = bool(present) and all(v == "off" for v in present) and bool(self._load().get("airplane"))
        return out

    # ---- radios / airplane mode ----------------------------------------------------------
    def set_radio(self, kind, on):
        status = radios.set_state(kind, on)
        if on:
            data = self._load()
            if data.get("airplane"):
                data["airplane"] = False
                self._save(data)
        return status

    def set_airplane(self, on):
        current = radios.get_states()
        data = self._load()
        if on:
            data["before_airplane"] = {k: v for k, v in current.items() if v is not None}
            data["airplane"] = True
            self._save(data)
            for kind, state in current.items():
                if state == "on":
                    radios.set_state(kind, False)
        else:
            before = data.get("before_airplane") or {}
            data["airplane"] = False
            self._save(data)
            for kind, state in current.items():
                if state is None:
                    continue
                want_on = before.get(kind, "on") == "on"
                if want_on and state != "on":
                    radios.set_state(kind, True)
        return radios.get_states()

    # ---- Wi-Fi ----------------------------------------------------------------------
    # Nothing here waits: scanning and connecting are started on the worker and their outcome is
    # awaited in main.py (asyncio), so brightness/volume calls never queue behind a slow Wi-Fi action.
    def wifi_scan_start(self):
        rc = self._wifi(lambda: self._wl().scan(self._iface()))
        self._last_scan = time.monotonic()
        return rc

    def wifi_networks(self):
        return self._wifi(lambda: self._networks(max_age=0))

    def wifi_connect_start(self, ssid, password=None):
        def go():
            guid = self._iface()
            wl = self._wl()
            net = {n["ssid"]: n for n in self._networks(max_age=0)}.get(ssid)
            if net is None:
                return {"done": True, "result": {"ok": False, "reason": "not_found"}}
            created = False
            profile = net["profile"] if net["known"] else None
            if profile is None or password:
                if net["auth"] not in SUPPORTED_NEW:
                    return {"done": True, "result": {"ok": False, "reason": "unsupported_security",
                                                     "security": net["security"]}}
                if net["secured"] and not password:
                    return {"done": True, "result": {"ok": False, "reason": "password_required"}}
                wl.set_profile(guid, profile_xml(ssid, net["auth"], net["cipher"], password))
                # only a profile the plugin added is removed again on failure, never an existing one
                created = profile is None
                profile = ssid
            wl.clear_connection_result(ssid)
            wl.connect_profile(guid, profile)
            return {"done": False, "created": created, "profile": profile, "secured": net["secured"],
                    "can_add": net["auth"] in SUPPORTED_NEW}
        return self._wifi(go)

    def wifi_connect_result(self, ssid):
        """Outcome reported by Windows ((ok, reason) or None). Thread-safe, makes no WLAN call."""
        wl = self._wlan
        return wl.take_connection_result(ssid) if wl is not None else None

    def wifi_is_connected(self, ssid):
        return any(n["ssid"] == ssid and n["connected"] for n in self.wifi_networks())

    def wifi_connect_finish(self, ssid, prep, ok, reason=None):
        if ok or self.wifi_is_connected(ssid):
            return {"ok": True}
        if prep.get("created"):
            self._wifi(lambda: self._wl().delete_profile(self._iface(), prep["profile"]))
        # WLAN_REASON_CODE_MSMSEC_* (0x40000-0x4FFFF): the security handshake failed, i.e. most likely the key
        security = reason is not None and 0x40000 <= reason < 0x50000
        if prep.get("created") and prep.get("secured") and (reason is None or security):
            return {"ok": False, "reason": "wrong_password", "retry_password": True}
        out = {"ok": False, "reason": "timeout" if reason is None else "failed",
               # a saved network whose password changed fails the same way: offer to type it again
               "retry_password": bool(security and prep.get("secured") and prep.get("can_add"))}
        if reason is not None:
            out["code"] = reason
            out["text"] = reason_text(reason) or "error %d" % reason
        return out

    def wifi_forget(self, ssid):
        """Delete the saved profile of a network (not one set by group policy)."""
        def go():
            guid = self._iface()
            wl = self._wl()
            net = {n["ssid"]: n for n in self._networks(max_age=0)}.get(ssid)
            name = net["profile"] if net and net.get("profile") else ssid
            flags = wl.profile_flags(guid)
            if name not in flags:
                return {"ok": False, "reason": "not_saved"}
            if flags[name] & WLAN_PROFILE_GROUP_POLICY:
                return {"ok": False, "reason": "group_policy"}
            rc = wl.delete_profile(guid, name)
            wl.dirty = True
            return {"ok": rc == 0, "reason": None if rc == 0 else "error %d" % rc}
        return self._wifi(go)

    def wifi_disconnect(self):
        self._wifi(lambda: self._wl().disconnect(self._iface()))
        return True

    # ---- Bluetooth -------------------------------------------------------------------
    def bluetooth_devices(self):
        devices = bt.paired_devices()
        try:
            audio = {a["name"]: a for a in btaudio.list_audio_devices()}
        except Exception as e:  # noqa: BLE001
            self.log("audio endpoint enumeration failed: %s" % e)
            audio = {}
        for d in devices:
            a = audio.get(d["name"])
            d["audio_control"] = a is not None
            if a is not None:
                d["audio_connected"] = a["connected"]
        return devices

    def bluetooth_audio(self, name, connect):
        btaudio.set_connected(name, connect)
        return True

    # ---- brightness / audio -----------------------------------------------------------
    def set_brightness(self, value):
        return brightness.set_level(value)

    @staticmethod
    def set_night(on):
        return nightlight.set_enabled(on)

    def set_audio_device(self, flow, dev_id):
        if flow not in ("output", "input"):
            raise ValueError("flow must be output or input")
        return audio.set_default(flow, dev_id)

    def set_volume(self, flow, value):
        if flow not in ("output", "input"):
            raise ValueError("flow must be output or input")
        return audio.set_volume(flow, value)

    # ---- refresh rate / frame limit (Performance tab) ------------------------------------------
    def perf_state(self):
        out = {"errors": {}}
        try:
            out["display"] = display.info()
        except Exception as e:  # noqa: BLE001
            out["display"] = None
            out["errors"]["display"] = str(e)
        try:
            out["rtss"] = self._rtss.status()
        except Exception as e:  # noqa: BLE001
            out["rtss"] = "missing"
            out["errors"]["rtss"] = str(e)
        try:
            out["frame_limit"] = self._limiter().get()
            fl = out["frame_limit"]
            if fl.get("method") == "rtss" and fl.get("fps") and not fl.get("running"):
                self._rtss.ensure_running()  # RTSS was closed: the limit only works while it runs
        except Exception as e:  # noqa: BLE001
            out["frame_limit"] = {"supported": False, "fps": 0, "min": 30, "max": 300, "error": str(e)}
        out["last_frame_limit"] = self._load().get("last_frame_limit")
        return out

    @staticmethod
    def set_hdr(on):
        return hdr.set_enabled(bool(on))

    def _limiter(self):
        """RTSS once it is set up (works for every graphics API); the Intel driver limiter otherwise (DX9/DX11 only
        on current drivers). With RTSS in charge the driver limit is switched off so two limiters never stack."""
        if self._rtss.status() == "ready":
            if not self._intel_cleared:
                try:
                    if self._frames.get().get("fps"):
                        self._frames.set(0)
                except Exception:  # noqa: BLE001 - no Intel GPU / driver: nothing to clear
                    pass
                self._intel_cleared = True
            return self._rtss
        self._intel_cleared = False
        return self._frames

    def rtss_keepalive(self):
        """While games run (called with the game-overlay list, about every 30 s): if a limit is set but RTSS is not
        running, e.g. OneXConsole closed it when its own OSD was switched off, start it again. ~1 ms otherwise."""
        from . import rtss as _rtss
        if self._rtss.status() == "ready" and (_rtss.saved_limit() or 0) > 0 and not _rtss.running():
            self._rtss.ensure_running()

    def setup_rtss(self):
        """Start the one-time RTSS setup elevated. Windows shows its UAC prompt; returns without waiting."""
        import ctypes
        import subprocess
        script = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "setup_rtss.ps1")
        sid = subprocess.run(["whoami", "/user", "/fo", "csv", "/nh"], capture_output=True, text=True,
                             creationflags=0x08000000, timeout=10).stdout.strip().split(",")[-1].strip('"')
        log = os.path.join(os.path.dirname(self.state_file), "setup_rtss.log")
        args = '-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "%s" -UserSid %s -Log "%s"' % (script, sid, log)
        shell = ctypes.WinDLL("shell32")
        shell.ShellExecuteW.restype = ctypes.c_ssize_t
        rc = shell.ShellExecuteW(None, "runas", "powershell.exe", args, None, 0)
        self._rtss.forget_status()
        if rc <= 32:
            raise OSError(rc, "the setup was not started (cancelled?)")
        return {"started": True}

    @staticmethod
    def battery_state():
        return battery.state()

    def set_frame_limit(self, fps):
        """fps 0 = no limit. The refresh rate is left alone: the panel has VRR and follows the game."""
        result = self._limiter().set(fps)
        if fps and fps > 0:
            data = self._load()
            data["last_frame_limit"] = int(fps)
            self._save(data)
        return result

    # ---- misc ----------------------------------------------------------------------------
    @staticmethod
    def open_settings(page):
        uri = {"bluetooth": "ms-settings:bluetooth", "wifi": "ms-settings:network-wifi",
               "display": "ms-settings:display", "location": "ms-settings:privacy-location"}.get(page, "ms-settings:")
        os.startfile(uri)  # noqa: S606 - fixed ms-settings URIs only
        return True
