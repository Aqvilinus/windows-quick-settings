"""Frame limit through RivaTuner Statistics Server (works for DX9/11/12, Vulkan and OpenGL games).

Uses RTSS's own profile API in RTSSHooks64.dll (LoadProfile / Get/SetProfileProperty / SaveProfile /
UpdateProfiles), the sequence Handheld Companion, steam-deck-tools and Universal x86 Tuning Utility use. The
global profile's FramerateLimit applies to every game; UpdateProfiles makes the running RTSS reload it, so a
running game picks up the change at once.

RTSS needs administrator rights, the plugin doesn't run with them: setup_rtss.ps1 next to this file (run once, elevated)
lets this user write the Profiles folder and registers the "WinQS RTSS" task that starts RTSS elevated at logon
and can be started on demand by this user (schtasks /run) without a UAC prompt.
"""
import ctypes
import os
import re
import subprocess
import time
import winreg

import psutil
from ctypes import byref, c_bool, c_char_p, c_int32, c_uint32, c_void_p

TASK = "WinQS RTSS"


def _install_dir():
    """RTSS's own record of where it is installed (what Handheld Companion reads), else the default folder."""
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Unwinder\RTSS") as k:
            d = winreg.QueryValueEx(k, "InstallDir")[0]
            if d and os.path.isdir(d):
                return d
    except OSError:
        pass
    return os.path.join(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"), "RivaTuner Statistics Server")


DIR = _install_dir()
HOOKS = os.path.join(DIR, "RTSSHooks64.dll")
GLOBAL = os.path.join(DIR, "Profiles", "Global")

def running():
    return any((p.info["name"] or "").lower() == "rtss.exe" for p in psutil.process_iter(["name"]))


SCHTASKS = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "schtasks.exe")


def _run(args, timeout=10):
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout, creationflags=subprocess.CREATE_NO_WINDOW)


def task_exists():
    return _run([SCHTASKS, "/query", "/tn", TASK]).returncode == 0


def profiles_writable():
    try:
        with open(GLOBAL, "r+b"):
            return True
    except OSError:
        return False


def saved_limit():
    """[Framerate] Limit= in the global profile file, or None if unreadable."""
    try:
        with open(GLOBAL, encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError:
        return None
    m = re.search(r"^\[Framerate\][^\[]*?^Limit=(\d+)", text, re.M | re.S)
    return int(m.group(1)) if m else None


class RtssFrameLimit:
    MIN, MAX = 30, 300

    TASK_CACHE = 5  # s: schtasks costs ~50 ms, the Performance tab polls every 5 s

    def __init__(self):
        self._dll = None
        self._task = None
        self._task_time = 0.0

    def _hooks(self):
        if self._dll is None:
            # a full path: Windows also looks for its dependencies in RTSS's folder, without changing the process-wide
            # DLL search path. Kept loaded; the profile calls only touch the 64-bit hooking context.
            d = ctypes.WinDLL(HOOKS)
            d.LoadProfile.argtypes = [c_char_p]
            d.SaveProfile.argtypes = [c_char_p]
            d.GetProfileProperty.argtypes = [c_char_p, c_void_p, c_uint32]
            d.GetProfileProperty.restype = c_bool
            d.SetProfileProperty.argtypes = [c_char_p, c_void_p, c_uint32]
            d.SetProfileProperty.restype = c_bool
            d.UpdateProfiles.argtypes = []
            self._dll = d
        return self._dll

    def status(self):
        """'missing' (RTSS not installed) | 'setup' (one-time setup needed) | 'ready'."""
        if not os.path.exists(HOOKS):
            return "missing"
        if self._task is None or (not self._task and time.monotonic() - self._task_time > self.TASK_CACHE):
            self._task = task_exists()
            self._task_time = time.monotonic()
        if not profiles_writable() or not self._task:
            return "setup"
        return "ready"

    def forget_status(self):
        self._task = None

    def ensure_running(self):
        if not running():
            _run([SCHTASKS, "/run", "/tn", TASK])

    def get(self):
        st = self.status()
        out = {"method": "rtss", "status": st, "min": self.MIN, "max": self.MAX, "fps": 0,
               "supported": st == "ready", "running": running()}
        if st == "missing":
            return out
        d = self._hooks()
        d.LoadProfile(b"")
        v = c_int32(0)
        if d.GetProfileProperty(b"FramerateLimit", byref(v), 4):
            out["fps"] = max(0, int(v.value))
        return out

    def set(self, fps):
        if self.status() != "ready":
            raise RuntimeError("RTSS is not set up")
        fps = 0 if fps <= 0 else max(self.MIN, min(self.MAX, int(fps)))
        d = self._hooks()
        d.LoadProfile(b"")
        v = c_int32(fps)
        if not d.SetProfileProperty(b"FramerateLimit", byref(v), 4):
            raise RuntimeError("RTSS refused the frame limit")
        d.SaveProfile(b"")  # returns nothing: confirmed from the file below
        d.UpdateProfiles()  # the running RTSS reloads the profile; hooked games pick it up live
        saved = saved_limit()
        if saved is not None and saved != fps:
            raise RuntimeError("RTSS did not save the frame limit (Profiles folder not writable?)")
        if fps:
            self.ensure_running()
        return self.get()
