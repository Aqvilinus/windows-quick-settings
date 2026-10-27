"""Windows Quick Settings - Decky Loader backend.

Pure Python (ctypes) access to Wi-Fi, Bluetooth, radios and display brightness on Windows.
Every system call runs on a single dedicated thread; see backend/winqs/service.py.
"""
import asyncio
import os
import sys

import decky

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "backend"))

from winqs.hotkeys import MenuHotkeys  # noqa: E402
from winqs.service import SystemService  # noqa: E402


class Plugin:
    svc = None
    hotkeys = None
    loop = None

    async def _run(self, fn, *args, timeout=40):
        if self.svc is None:
            self.svc = SystemService(decky.DECKY_PLUGIN_SETTINGS_DIR, log=decky.logger.warning)
        fut = self.svc.submit(fn, *args)
        return await asyncio.wait_for(asyncio.wrap_future(fut), timeout)

    async def _call(self, name, fn, *args, timeout=40):
        try:
            return {"ok": True, "result": await self._run(fn, *args, timeout=timeout)}
        except Exception as e:  # noqa: BLE001 - surface every failure to the UI
            decky.logger.error("%s failed: %r", name, e)
            return {"ok": False, "error": str(e)}

    # ---- API used by the frontend ---------------------------------------------------
    async def get_state(self):
        return await self._call("get_state", lambda: self.svc.state())

    async def set_wifi(self, on):
        return await self._call("set_wifi", lambda: self.svc.set_radio("wifi", bool(on)))

    async def set_bluetooth(self, on):
        return await self._call("set_bluetooth", lambda: self.svc.set_radio("bluetooth", bool(on)))

    async def set_airplane(self, on):
        return await self._call("set_airplane", lambda: self.svc.set_airplane(bool(on)))

    async def set_brightness(self, value):
        return await self._call("set_brightness", lambda: self.svc.set_brightness(int(value)), timeout=10)

    async def set_night(self, on):
        return await self._call("set_night", lambda: self.svc.set_night(bool(on)), timeout=10)

    async def set_volume(self, flow, value):
        return await self._call("set_volume", lambda: self.svc.set_volume(str(flow), int(value)), timeout=10)

    async def set_audio_device(self, flow, dev_id):
        return await self._call("set_audio_device", lambda: self.svc.set_audio_device(str(flow), str(dev_id)), timeout=10)

    async def wifi_networks(self, rescan=True):
        """Network list; with rescan, start a scan and wait (here, not on the worker) until Windows reports it done."""
        try:
            if rescan:
                await self._run(lambda: self.svc.wifi_scan_start(), timeout=10)
                done = self.svc.scan_event()
                loop = asyncio.get_running_loop()
                deadline = loop.time() + (4.0 if done is not None else 3.0)
                while loop.time() < deadline and not (done is not None and done.is_set()):
                    await asyncio.sleep(0.1)
            return {"ok": True, "result": await self._run(lambda: self.svc.wifi_networks(), timeout=10)}
        except Exception as e:  # noqa: BLE001
            decky.logger.error("wifi_networks failed: %r", e)
            return {"ok": False, "error": str(e)}

    async def wifi_connect(self, ssid, password=None):
        """Start the connection on the worker, then wait here for Windows' connect notification (or poll the
        list once a second if notifications are unavailable). The worker stays free meanwhile."""
        ssid = str(ssid)
        try:
            prep = await self._run(lambda: self.svc.wifi_connect_start(ssid, password or None), timeout=15)
            if prep.get("done"):
                return {"ok": True, "result": prep["result"]}
            loop = asyncio.get_running_loop()
            deadline = loop.time() + 20
            next_poll = loop.time() + 1
            ok, reason = False, None
            while loop.time() < deadline:
                await asyncio.sleep(0.25)
                outcome = self.svc.wifi_connect_result(ssid)
                if outcome is not None:
                    ok, reason = outcome
                    break
                if not self.svc.wlan_notifications() and loop.time() >= next_poll:
                    next_poll = loop.time() + 1
                    if await self._run(lambda: self.svc.wifi_is_connected(ssid), timeout=10):
                        ok = True
                        break
            result = await self._run(lambda: self.svc.wifi_connect_finish(ssid, prep, ok, reason), timeout=15)
            return {"ok": True, "result": result}
        except Exception as e:  # noqa: BLE001
            decky.logger.error("wifi_connect failed: %r", e)
            return {"ok": False, "error": str(e)}

    async def wifi_forget(self, ssid):
        return await self._call("wifi_forget", lambda: self.svc.wifi_forget(str(ssid)), timeout=15)

    async def wifi_disconnect(self):
        return await self._call("wifi_disconnect", lambda: self.svc.wifi_disconnect())

    async def bluetooth_devices(self):
        return await self._call("bluetooth_devices", lambda: self.svc.bluetooth_devices())

    async def bluetooth_audio(self, name, connect):
        return await self._call("bluetooth_audio", lambda: self.svc.bluetooth_audio(str(name), bool(connect)), timeout=20)

    async def bt_scan(self, on):
        return await self._call("bt_scan", lambda: self.svc.bt_scan(bool(on)), timeout=15)

    async def bt_scan_results(self):
        return await self._call("bt_scan_results", lambda: self.svc.bt_scan_results(), timeout=10)

    async def bt_pair(self, device_id):
        return await self._call("bt_pair", lambda: self.svc.bt_pair(str(device_id)), timeout=15)

    async def bt_pair_answer(self, accept):
        return await self._call("bt_pair_answer", lambda: self.svc.bt_pair_answer(bool(accept)), timeout=10)

    async def bt_pair_cancel(self):
        return await self._call("bt_pair_cancel", lambda: self.svc.bt_pair_cancel(), timeout=10)

    async def bt_forget(self, device_id):
        return await self._call("bt_forget", lambda: self.svc.bt_forget(str(device_id)), timeout=20)

    async def perf_state(self):
        return await self._call("perf_state", lambda: self.svc.perf_state(), timeout=10)

    async def set_hdr(self, on):
        return await self._call("set_hdr", lambda: self.svc.set_hdr(bool(on)), timeout=15)

    async def setup_rtss(self):
        return await self._call("setup_rtss", lambda: self.svc.setup_rtss(), timeout=15)

    async def battery_state(self):
        return await self._call("battery_state", lambda: self.svc.battery_state(), timeout=5)

    async def set_frame_limit(self, fps):
        return await self._call("set_frame_limit", lambda: self.svc.set_frame_limit(int(fps)), timeout=15)

    async def set_active_game(self, appid):
        return await self._call("set_active_game", lambda: self.svc.set_active_game(appid), timeout=15)

    async def set_game_profile(self, on):
        return await self._call("set_game_profile", lambda: self.svc.set_game_profile(bool(on)), timeout=15)

    # Ctrl+1 / Ctrl+2 (OneXConsole D-pad + M1) while a game runs: see backend/winqs/hotkeys.py
    def _on_hotkey(self, menu, overlay_pid=None):
        emit = getattr(decky, "emit", None)
        if emit and self.loop:
            asyncio.run_coroutine_threadsafe(emit("winqs_menu_hotkey", menu, overlay_pid), self.loop)

    async def menu_hotkey_test(self, menu, overlay_pid=None):
        """Diagnostics: the same path as a real hotkey press, fired from another thread."""
        import threading
        threading.Thread(target=self._on_hotkey, args=(str(menu), overlay_pid), daemon=True).start()
        return {"ok": True, "result": {"emit": bool(getattr(decky, "emit", None))}}

    async def set_game_overlays(self, overlay_pids):
        """PIDs of Steam's per-game overlay processes. Idempotent: the frontend sends the full list on every change."""
        if self.hotkeys is None:
            return {"ok": False, "error": "hotkeys unavailable"}
        self.hotkeys.set_overlays(list(overlay_pids or []))
        if overlay_pids:
            self.svc.submit(self.svc.rtss_keepalive)  # fire and forget, on the worker
        await asyncio.sleep(0.05)
        return {"ok": True, "result": self.hotkeys.status()}

    async def open_settings(self, page):
        return await self._call("open_settings", lambda: SystemService.open_settings(str(page)))

    # ---- lifecycle --------------------------------------------------------------------
    async def _main(self):
        self.svc = SystemService(decky.DECKY_PLUGIN_SETTINGS_DIR, log=decky.logger.warning)
        self.loop = asyncio.get_running_loop()
        try:
            self.hotkeys = MenuHotkeys(self._on_hotkey, log=decky.logger.warning)
        except Exception as e:  # noqa: BLE001
            decky.logger.error("menu hotkeys unavailable: %r", e)
        decky.logger.info("Windows Quick Settings backend started")

    async def _unload(self):
        if self.hotkeys is not None:
            self.hotkeys.close()
            self.hotkeys = None
        if self.svc is not None:
            self.svc.shutdown()
            self.svc = None
        decky.logger.info("Windows Quick Settings backend stopped")
