"""All system calls run on one dedicated thread (one COM/WinRT apartment, one wlan handle)."""
import base64
import concurrent.futures
import contextlib
import json
import os
import re
import subprocess
import threading
import time

from . import audio, battery, brightness, bt, btaudio, display, hdr, nightlight, nlm, radios, rtss
from .framelimit import IntelFrameLimit
from .rtss import RtssFrameLimit
from .com import init_worker
from .wlan import (SUPPORTED_NEW, WLAN_PROFILE_GROUP_POLICY, LocationBlocked, Wlan, profile_name, profile_xml,
                   reason_text)

# WLAN errors after which the client handle is useless (service restarted, RPC broken): reopen once.
WLAN_REOPEN_ERRORS = {6, 1702, 1722, 1726, 1727, 1753}
SCAN_EVERY = 30         # s; only while Wi-Fi is on but not connected (a scan disturbs a connected link)
NETWORKS_MAX_AGE = 20   # s; with notifications the list is re-read on changes, this is only a safety net
BT_AUDIO_MAX_AGE = 10   # s; Bluetooth audio endpoints, otherwise re-read when a paired device's connection changes


FLOWS = ("output", "input")

SID_RE = re.compile(r"S-1-\d+(-\d+)+")
APPID_RE = re.compile(r"\d{1,10}")
# Read once at backend start (see setup_rtss): the elevated step never runs a file from the user-writable folder.
with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "setup_rtss.ps1"), encoding="utf-8-sig") as _f:
    SETUP_RTSS_SCRIPT = _f.read()


def _system32(*parts):
    return os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", *parts)


def _collect(errors, key, fn, default=None):
    """fn(), or `default` with the failure reported in errors[key]: one broken part never hides the rest."""
    try:
        return fn()
    except Exception as e:  # noqa: BLE001
        errors[key] = str(e)
        return default


def _for_ui(nets):
    """The network list without what only the backend uses (profile XML inputs), so each poll sends less."""
    return [{k: v for k, v in n.items() if k not in ("auth", "cipher", "profile", "ssid_hex")} for n in nets]


class SystemService:
    def __init__(self, state_dir, log=None):
        self.state_file = os.path.join(state_dir, "state.json")
        self.log = log or (lambda *a: None)
        self.pool = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="winqs-sys",
                                                          initializer=self._init_worker)
        self._wlan = None
        self._guid = None
        self._nets = []
        self._nets_time = 0.0
        self._last_scan = 0.0
        self._frames = IntelFrameLimit()  # used on the worker thread only
        self._rtss = RtssFrameLimit()       # DX12 / Vulkan too, once setup_rtss.ps1 has run
        self._intel_cleared = False
        self._game = None  # Steam appid of the running game (str), as the frontend reports it
        self._bt_paired = bt.PairedDevices(self.log)  # kept current by Windows once first read
        self._bt_scan = bt.Scanner(self.log)
        self._bt_pairing = bt.Pairing(self.log)
        self._bt_audio, self._bt_audio_key, self._bt_audio_time = {}, None, 0.0
        self.on_wlan_event = None  # main.py: wakes its waits for a scan / connect outcome (called on Windows' thread)

    # ---- infrastructure -------------------------------------------------------------
    def _init_worker(self):
        """A failing initializer would break the pool for good (every call: BrokenThreadPool until Decky restarts).
        Log it instead; the calls that need COM then report their own errors."""
        try:
            init_worker()
        except Exception as e:  # noqa: BLE001
            self.log("worker thread set-up failed: %r" % e)

    def submit(self, fn, *args):
        return self.pool.submit(fn, *args)

    def shutdown(self):
        """Blocks for up to 5 s: call it off the event loop (main.py uses asyncio.to_thread)."""
        def _close():
            for step in (self._bt_pairing.cancel, self._bt_scan.stop, self._bt_paired.stop, self._frames.close):
                try:
                    step()
                except Exception as e:  # noqa: BLE001 - close the rest anyway
                    self.log("shutdown: %s failed: %r" % (getattr(step, "__qualname__", step), e))
            if self._wlan:
                self._wlan.close()
                self._wlan = None
        with contextlib.suppress(Exception):
            self.pool.submit(_close).result(timeout=5)
        self.pool.shutdown(wait=False, cancel_futures=True)

    def _wl(self):
        if self._wlan is None:
            self._wlan = Wlan(on_event=lambda: self.on_wlan_event and self.on_wlan_event())
        return self._wlan

    def _reset_wlan(self):
        if self._wlan is not None:
            with contextlib.suppress(Exception):
                self._wlan.close()
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
        out = {"radios": {"wifi": None, "bluetooth": None}, "brightness": None,
               "airplane": False, "errors": {}}
        err = out["errors"]
        out["radios"] = _collect(err, "radios", radios.get_states, out["radios"])
        out["wifi_networks"] = []
        try:
            if out["radios"].get("wifi") == "on":
                nets = self._wifi(self._networks)
                if not any(n["connected"] for n in nets) and time.monotonic() - self._last_scan > SCAN_EVERY:
                    self._wifi(lambda: self._wl().scan(self._iface()))  # result arrives as a notification
                    self._last_scan = time.monotonic()
                out["wifi_networks"] = _for_ui(nets)
                if any(n["connected"] for n in nets):
                    out["internet"] = _collect(err, "internet", nlm.status)
        except LocationBlocked:
            out["wifi_location_off"] = True
        except Exception as e:  # noqa: BLE001
            out["errors"]["wifi"] = str(e)
        out["bt_devices"] = []
        if out["radios"].get("bluetooth") == "on":
            out["bt_devices"] = _collect(err, "bluetooth", self.bluetooth_devices, [])
        h = _collect(err, "hdr", hdr.state) or {}  # ~1 ms; shown in Quick Settings next to Night mode
        out["hdr"] = h if h.get("supported") else None
        out["night"] = _collect(err, "night", nightlight.is_enabled)
        out["brightness"] = _collect(err, "brightness", brightness.get_level)
        out["audio"], out["audio_devices"] = {}, {}
        for f in FLOWS:
            out["audio"][f], out["audio_devices"][f] = _collect(err, "audio_" + f, lambda f=f: audio.get(f),
                                                                (None, []))
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
        return _for_ui(self._wifi(lambda: self._networks(max_age=0)))

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
                if profile is not None and not net["secured"]:
                    # a new password for a saved network: never rewrite its profile as an open one
                    return {"done": True, "result": {"ok": False, "reason": "unsupported_security",
                                                     "security": net["security"]}}
                if net["auth"] not in SUPPORTED_NEW:
                    return {"done": True, "result": {"ok": False, "reason": "unsupported_security",
                                                     "security": net["security"]}}
                if net["secured"] and not password:
                    return {"done": True, "result": {"ok": False, "reason": "password_required"}}
                # a new password rewrites the saved profile itself (its name can differ from the SSID)
                name = profile if profile is not None else profile_name(ssid)
                wl.set_profile(guid, profile_xml(ssid, net["ssid_hex"], net["auth"], net["cipher"], password, name))
                # only a profile the plugin added is removed again on failure, never an existing one
                created = profile is None
                profile = name
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
        if prep.get("created"):  # remove the profile the attempt added; a failure here must not hide the outcome
            try:
                self._wifi(lambda: self._wl().delete_profile(self._iface(), prep["profile"]))
            except OSError as e:
                self.log("removing the new Wi-Fi profile failed: %s" % e)
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
            wl.delete_profile(guid, name)
            wl.dirty = True
            return {"ok": True}
        return self._wifi(go)

    def wifi_disconnect(self):
        self._wifi(lambda: self._wl().disconnect(self._iface()))
        return True

    # ---- Bluetooth -------------------------------------------------------------------
    def bluetooth_devices(self):
        devices = self._bt_paired.devices()
        # the audio endpoints (~0.6 ms to list) are read again only when a paired device connects / disconnects,
        # after an audio connect from the panel, or every BT_AUDIO_MAX_AGE seconds
        key = tuple((d["id"], d["connected"]) for d in devices)
        if key != self._bt_audio_key or time.monotonic() - self._bt_audio_time > BT_AUDIO_MAX_AGE:
            try:
                self._bt_audio = {a["name"]: a for a in btaudio.list_audio_devices()}
            except Exception as e:  # noqa: BLE001
                self.log("audio endpoint enumeration failed: %s" % e)
                self._bt_audio = {}
            self._bt_audio_key, self._bt_audio_time = key, time.monotonic()
        bt_audio = self._bt_audio
        for d in devices:
            a = bt_audio.get(d["name"])
            d["audio_control"] = a is not None
            if a is not None:
                d["audio_connected"] = a["connected"]
        return devices

    def bluetooth_audio(self, name, connect):
        btaudio.set_connected(name, connect)
        self._bt_audio_key = None  # read the endpoints again on the next poll
        return True

    # ---- Bluetooth search / pairing / removal (see bt.py) ----------------------------------------------------------
    def bt_scan(self, on):
        if on:
            self._bt_scan.start()
        else:
            self._bt_scan.stop()
        return self._bt_scan.results()

    def bt_scan_results(self):
        out = self._bt_scan.results()
        out["pairing"] = self._bt_pairing.state()
        return out

    def bt_pair(self, device_id):
        if not bt.is_device_id(device_id):
            raise ValueError("not a Bluetooth device id")
        self._bt_scan.stop()  # an inquiry running alongside slows pairing down
        self._bt_pairing.start(device_id)
        return self._bt_pairing.state()

    def bt_pair_answer(self, accept):
        return self._bt_pairing.answer(bool(accept))

    def bt_pair_cancel(self):
        self._bt_pairing.cancel()
        return self._bt_pairing.state()

    def bt_forget(self, device_id):
        if not bt.is_device_id(device_id):
            raise ValueError("not a Bluetooth device id")
        return bt.unpair(device_id)

    # ---- brightness / audio -----------------------------------------------------------
    def set_brightness(self, value):
        return brightness.set_level(value)

    @staticmethod
    def set_night(on):
        return nightlight.set_enabled(on)

    def set_audio_device(self, flow, dev_id):
        if flow not in FLOWS:
            raise ValueError("flow must be output or input")
        return audio.set_default(flow, dev_id)

    def set_volume(self, flow, value):
        if flow not in FLOWS:
            raise ValueError("flow must be output or input")
        return audio.set_volume(flow, value)

    # ---- refresh rate / frame limit (Performance tab) ------------------------------------------
    def perf_state(self):
        out = {"errors": {}}
        out["display"] = _collect(out["errors"], "display", display.info)
        out["rtss"] = _collect(out["errors"], "rtss", self._rtss.status, "missing")
        try:
            out["frame_limit"] = self._limiter().get()
            fl = out["frame_limit"]
            if fl.get("method") == "rtss" and fl.get("fps") and not fl.get("running"):
                self._rtss.ensure_running()  # RTSS was closed: the limit only works while it runs
        except Exception as e:  # noqa: BLE001
            out["frame_limit"] = {"supported": False, "fps": 0, "min": 30, "max": 300, "error": str(e)}
        data = self._load()
        fresh = "frame_profiles" not in data
        prof, per_game = self._active_profile(data)
        if fresh:
            self._save(data)
        out["last_frame_limit"] = prof.get("last")
        out["profile"] = {"game": self._game, "per_game": per_game}
        return out

    @staticmethod
    def set_hdr(on):
        return hdr.set_enabled(bool(on))

    @staticmethod
    def hdr_state():
        return hdr.state()

    def _limiter(self):
        """RTSS once it is set up (works for every graphics API); the Intel driver limiter otherwise (DX9/DX11 only
        on current drivers). With RTSS in charge the driver limit is switched off so two limiters never stack."""
        if self._rtss.status() == "ready":
            if not self._intel_cleared:
                with contextlib.suppress(Exception):  # no Intel GPU / driver: nothing to clear
                    if self._frames.get().get("fps"):
                        self._frames.set(0)
                self._intel_cleared = True
            return self._rtss
        self._intel_cleared = False
        return self._frames

    def rtss_keepalive(self):
        """While games run (called with the game-overlay list, about every 30 s): if a limit is set but RTSS is not
        running, e.g. OneXConsole closed it when its own OSD was switched off, start it again. ~1 ms otherwise."""
        if self._rtss.status() == "ready" and (rtss.saved_limit() or 0) > 0 and not rtss.running():
            self._rtss.ensure_running()

    def setup_rtss(self):
        """Start the one-time RTSS setup elevated. Windows shows its UAC prompt; returns without waiting.

        The elevated PowerShell gets the script text itself (-EncodedCommand, read when the backend started), not a
        path: the plugin folder is user-writable, so a file run from there could be swapped just before the prompt."""
        sid = subprocess.run([_system32("whoami.exe"), "/user", "/fo", "csv", "/nh"], capture_output=True, text=True,
                             creationflags=subprocess.CREATE_NO_WINDOW, timeout=10).stdout.strip().split(",")[-1].strip('"')
        if not SID_RE.fullmatch(sid):
            raise RuntimeError("could not read the user's SID")
        command = "& {\n%s\n} -UserSid '%s'" % (SETUP_RTSS_SCRIPT, sid)
        args = ("-NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -EncodedCommand "
                + base64.b64encode(command.encode("utf-16-le")).decode("ascii"))
        self._rtss.forget_status()
        powershell = _system32("WindowsPowerShell", "v1.0", "powershell.exe")

        def launch():  # ShellExecute "runas" returns only once the UAC prompt is answered: not on the worker thread
            try:
                os.startfile(powershell, "runas", args, None, 0)
            except OSError as e:
                self.log("RTSS setup not started (UAC prompt cancelled?): %s" % e)
        threading.Thread(target=launch, name="winqs-rtss-setup", daemon=True).start()
        return {"started": True}

    @staticmethod
    def battery_state():
        return battery.state()

    def set_frame_limit(self, fps):
        """fps 0 = no limit, stored in the active profile. The refresh rate is left alone: the panel has VRR."""
        fps = max(0, int(fps))
        result = self._limiter().set(fps)
        if fps:  # store what the limiter applies, not an out-of-range request
            fps = max(int(result.get("min") or 30), min(int(result.get("max") or 300), fps))
        data = self._load()
        prof, _ = self._active_profile(data)
        prof["fps"] = fps
        if fps:
            prof["last"] = fps
        self._save(data)
        return result

    # ---- frame limit profiles: default + per game, like Steam Deck's "Use per-game profile" ------------------
    def _active_profile(self, data):
        """(profile dict, per_game) for the running game; creates the store on first use from the current limit."""
        store = data.get("frame_profiles")
        if not isinstance(store, dict) or not isinstance(store.get("default"), dict):
            try:
                fps = int(self._limiter().get().get("fps") or 0)
            except Exception:  # noqa: BLE001 - no limiter: start without a limit
                fps = 0
            store = {"default": {"fps": fps, "last": data.pop("last_frame_limit", None)}, "games": {}}
            data["frame_profiles"] = store
        games = store.setdefault("games", {})
        if self._game and isinstance(games.get(self._game), dict):
            return games[self._game], True
        return store["default"], False

    def set_active_game(self, appid):
        """The running game changed (None = no game). Its profile (or the default one) is applied when either side
        has a per-game profile; between two default contexts the limit is left alone, so a limit set elsewhere
        (OneXConsole) is not undone. Idempotent: the frontend also resends it as a heartbeat."""
        game = str(appid) if appid not in (None, "", 0, "0") else None
        if game is not None and not APPID_RE.fullmatch(game):  # a Steam appid (shortcuts too) is a 32-bit number
            raise ValueError("not a Steam app id")
        if game == self._game:
            return {"game": game}
        data = self._load()
        _, was_per_game = self._active_profile(data)
        self._game = game
        prof, per_game = self._active_profile(data)
        self._save(data)
        if was_per_game or per_game:
            self._apply_fps(int(prof.get("fps") or 0))
        return {"game": game, "per_game": per_game}

    def set_game_profile(self, on):
        """Turn the per-game profile of the running game on (starting as a copy of the current settings) or off
        (deleted; the default profile applies again)."""
        if not self._game:
            raise ValueError("no game is running")
        data = self._load()
        cur, per_game = self._active_profile(data)
        games = data["frame_profiles"]["games"]
        if on and not per_game:
            games[self._game] = {"fps": int(cur.get("fps") or 0), "last": cur.get("last")}
        elif not on and per_game:
            games.pop(self._game, None)
            prof, _ = self._active_profile(data)
            self._apply_fps(int(prof.get("fps") or 0))
        self._save(data)
        return {"game": self._game, "per_game": bool(on)}

    def _apply_fps(self, fps):
        lim = self._limiter()
        with contextlib.suppress(Exception):  # set() below reports the real error
            if int(lim.get().get("fps") or 0) == fps:
                return
        lim.set(fps)

    # ---- misc ----------------------------------------------------------------------------
    @staticmethod
    def open_settings(page):
        uri = {"bluetooth": "ms-settings:bluetooth", "wifi": "ms-settings:network-wifi",
               "display": "ms-settings:display", "location": "ms-settings:privacy-location"}.get(page, "ms-settings:")
        os.startfile(uri)  # noqa: S606 - fixed ms-settings URIs only
        return True
