"""Steam's Ctrl+1 / Ctrl+2 menu shortcuts inside games.

Big Picture turns Ctrl+1 / Ctrl+2 into the Steam and Quick Access buttons only while its own
window has keyboard focus. In a game the keys go to the game, so the shortcuts OneXConsole sends
(D-pad + M1) did nothing there.

This module registers both combos as system-wide hotkeys (RegisterHotKey) only while the
foreground window belongs to a game that has a Steam overlay. Everywhere else (Big Picture,
the desktop, a browser) nothing is registered and the keys behave as usual.

- The frontend reports the PIDs of Steam's overlay processes (gameoverlayui64.exe, one per game);
  each one's command line names the game process ("-pid <game pid>").
- A WinEvent hook (EVENT_SYSTEM_FOREGROUND, out of context) tells us when the foreground window
  changes. Both run on one thread that sleeps in GetMessage: no polling, no CPU while idle.
- A press is reported as (menu, overlay pid) so the frontend opens the menu in that game's overlay.
"""
import ctypes
import re
import threading
from ctypes import wintypes

import psutil

from .com import sig

_user32 = ctypes.WinDLL("user32", use_last_error=True)

WINEVENTPROC = ctypes.WINFUNCTYPE(None, wintypes.HANDLE, wintypes.DWORD, wintypes.HWND, wintypes.LONG,
                                  wintypes.LONG, wintypes.DWORD, wintypes.DWORD)

sig(_user32.RegisterHotKey, wintypes.BOOL, wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT)
sig(_user32.UnregisterHotKey, wintypes.BOOL, wintypes.HWND, ctypes.c_int)
sig(_user32.GetMessageW, wintypes.BOOL, ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT)
sig(_user32.PeekMessageW, wintypes.BOOL,
    ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT, wintypes.UINT)
sig(_user32.PostThreadMessageW, wintypes.BOOL, wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
sig(_user32.SetWinEventHook, wintypes.HANDLE,
    wintypes.DWORD, wintypes.DWORD, wintypes.HMODULE, WINEVENTPROC, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD)
sig(_user32.UnhookWinEvent, wintypes.BOOL, wintypes.HANDLE)
_user32.GetForegroundWindow.restype = wintypes.HWND
sig(_user32.GetWindowThreadProcessId, wintypes.DWORD, wintypes.HWND, ctypes.POINTER(wintypes.DWORD))

WM_HOTKEY = 0x0312
WM_QUIT = 0x0012
WM_APP_OVERLAYS = 0x8000 + 1   # the overlay list changed (stored in self._pending_overlays)
MOD_CONTROL = 0x0002
MOD_NOREPEAT = 0x4000
EVENT_SYSTEM_FOREGROUND = 0x0003
WINEVENT_OUTOFCONTEXT = 0x0000
WINEVENT_SKIPOWNPROCESS = 0x0002
HOTKEYS = {1: ("main", 0x31), 2: ("qam", 0x32)}  # id -> (menu, VK '1' / '2')
_PID_ARG = re.compile(r"(?:^|\s)-pid\s+(\d+)")


def _command_line(pid):
    try:
        return " ".join(psutil.Process(pid).cmdline())
    except (psutil.Error, OSError):  # gone, or not ours to read
        return None


def game_pid_of_overlay(overlay_pid):
    """gameoverlayui64.exe is started as '... -pid <game pid> -steampid <steam pid> ... -gameid <appid>'."""
    m = _PID_ARG.search(_command_line(overlay_pid) or "")
    return int(m.group(1)) if m else None


class MenuHotkeys:
    def __init__(self, on_press, log=None):
        self._on_press = on_press
        self._log = log or (lambda *a: None)
        self._tid = None
        self._ready = threading.Event()
        self._lock = threading.Lock()
        self._pending_overlays = None
        self._games = {}           # game pid -> overlay pid
        self._target = None        # overlay pid of the game in the foreground while registered
        self.active = False
        self.errors = {}
        self._hook = None
        self._hook_proc = WINEVENTPROC(self._on_foreground)  # keep a reference while hooked
        self._thread = threading.Thread(target=self._run, name="winqs-hotkeys", daemon=True)
        self._thread.start()
        self._ready.wait(5)

    # ---- runs on the hotkey thread ----------------------------------------------------
    def _set_registered(self, on):
        if on == self.active:
            return
        for hid in HOTKEYS:
            _user32.UnregisterHotKey(None, hid)
        self.active = False
        self.errors = {}
        if on:
            for hid, (name, vk) in HOTKEYS.items():
                if not _user32.RegisterHotKey(None, hid, MOD_CONTROL | MOD_NOREPEAT, vk):
                    self.errors[name] = ctypes.get_last_error()  # 1409: another program owns this combo
            self.active = not self.errors
            if not self.active:
                for hid in HOTKEYS:
                    _user32.UnregisterHotKey(None, hid)

    def _evaluate(self):
        pid = wintypes.DWORD(0)
        hwnd = _user32.GetForegroundWindow()
        if hwnd:
            _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        self._target = self._games.get(pid.value)
        self._set_registered(self._target is not None)

    def _apply_overlays(self):
        with self._lock:
            overlays, self._pending_overlays = self._pending_overlays, None
        if overlays is None:
            return
        # the frontend resends the list every 30 s: only overlays not resolved yet have their command line read
        known = {opid: gpid for gpid, opid in self._games.items()}
        games = {}
        for opid in overlays:
            gpid = known.get(opid) or game_pid_of_overlay(opid)
            if gpid:
                games[gpid] = opid
        self._games = games
        if games and not self._hook:
            self._hook = _user32.SetWinEventHook(EVENT_SYSTEM_FOREGROUND, EVENT_SYSTEM_FOREGROUND, None,
                                                 self._hook_proc, 0, 0,
                                                 WINEVENT_OUTOFCONTEXT | WINEVENT_SKIPOWNPROCESS)
        elif not games and self._hook:
            _user32.UnhookWinEvent(self._hook)
            self._hook = None
        self._evaluate()

    def _on_foreground(self, _hook, _event, _hwnd, _obj, _child, _thread, _time):
        try:
            self._evaluate()
        except Exception as e:  # noqa: BLE001 - never raise into the hook
            self._log("foreground check failed: %r" % e)

    def _run(self):
        msg = wintypes.MSG()
        _user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 0)  # create this thread's message queue
        self._tid = threading.get_native_id()  # the Win32 thread id PostThreadMessageW needs
        self._ready.set()
        while _user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            try:
                if msg.message == WM_APP_OVERLAYS:
                    self._apply_overlays()
                elif msg.message == WM_HOTKEY and msg.wParam in HOTKEYS:
                    self._on_press(HOTKEYS[msg.wParam][0], self._target)
            except Exception as e:  # noqa: BLE001 - never kill the loop
                self._log("hotkey thread: %r" % e)
        if self._hook:
            _user32.UnhookWinEvent(self._hook)
            self._hook = None
        self._set_registered(False)

    # ---- called from other threads -------------------------------------------------
    def set_overlays(self, overlay_pids):
        """PIDs of Steam's game overlay processes; an empty list turns everything off."""
        with self._lock:
            self._pending_overlays = [int(p) for p in overlay_pids or [] if int(p) > 0]
        if self._tid:
            _user32.PostThreadMessageW(self._tid, WM_APP_OVERLAYS, 0, 0)

    def status(self):
        return {"games": len(self._games), "active": self.active, "errors": dict(self.errors)}

    def close(self):
        if self._tid:
            _user32.PostThreadMessageW(self._tid, WM_QUIT, 0, 0)
            self._thread.join(2)
