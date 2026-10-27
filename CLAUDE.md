# CLAUDE.md

Decky Loader plugin that adds SteamOS-style system controls to Steam Big Picture's Quick Access Menu (QAM) on Windows.

## Environment

- OneXPlayer 3 (Core Ultra, Arc B390), Windows 11 in Xbox full-screen mode, home app OmniConsole. The panel is 1920x1200 with VRR, 30–144 Hz.
- OneXConsole (vendor app, elevated) owns TDP, fans, buttons and its own RTSS OSD.
- Decky Loader 3.3.0 for Windows, unelevated. Settings are in `%USERPROFILE%\homebrew\settings\windows-quick-settings`, logs in `homebrew\logs\windows-quick-settings`.
- The backend runs on Decky's frozen Python 3.11: stdlib + `ctypes` only, no pip packages.
- Steam CEF DevTools: `http://127.0.0.1:8080`. Decky runs in the `SharedJSContext` target.

## Layout

- `main.py`: backend entry. `Plugin` methods are the callables, run on one worker thread via `_call`.
- `backend/winqs/`:
  - `service.py`: `state()` for the Quick Settings tab, `perf_state()` for the Performance tab, all actions.
  - `com.py`: COM/WinRT over ctypes, plus `init_worker` (MTA, EcoQoS off).
  - `radios.py`, `wlan.py`, `nlm.py`: radios; Wi-Fi scan, connect, forget; internet status.
  - `bt.py`, `btaudio.py`, `audio.py`: Bluetooth devices and audio.
  - `brightness.py`, `nightlight.py`, `hdr.py`, `display.py`, `battery.py`: brightness, Night light, HDR, the current refresh rate (read only), battery draw.
  - `rtss.py` + `../setup_rtss.ps1`, `framelimit.py`: frame limit through RTSS; Intel IGCL fallback.
  - `hotkeys.py`: Ctrl+1 / Ctrl+2 for Steam's side menus in games.
- `dist/index.js`: the whole frontend, hand-written, no build step, split by `// ------` banners.

## Workflow

- Reload, from `SharedJSContext`:
  - backend: `await DeckyBackend.call("utilities/enable_plugin", "Windows Quick Settings")`;
  - frontend: `await DeckyPluginLoader.importPlugin("Windows Quick Settings", "0.1.0")`.
- Call a backend method: `DeckyBackend.call("loader/call_plugin_method", "Windows Quick Settings", "<method>", ...args)`. Arguments are spread.
- Evaluate over CDP with `Runtime.evaluate` (`awaitPromise`, `returnByValue`). For long work, store the result in `window.__probe` and read it in a second call.
- Open a QAM tab: `SteamUIStore.WindowStore.GamepadUIMainWindowInstance.MenuStore.OpenQuickAccessMenu(4 | 5)`, close with `CloseSideMenus()`. Wait for the nav tree matching `/QuickAccess/` in `FocusNavController.m_rgAllContexts[0].m_rgGamepadNavigationTrees`.
- Gamepad navigation: `FocusNavController.DispatchVirtualButtonClick(btn, el)`.
  - Buttons: OK 1, CANCEL 2, OPTIONS 4, UP 9, DOWN 10, LEFT 11, RIGHT 12. Focus is `.gpfocus`.
  - CDP key events bypass gamepad routing and prove nothing.
- Diagnostics: `window.__WINQS.status`, `.openWifi()`, `.stop()`.
- Never `Page.captureScreenshot` a hidden Steam page: it hangs. Big Picture is hidden whenever a game or another window is in front.
- Performance budget: `get_state` ~15–20 ms, idle CPU 0.

## Rules

- Steam Deck look and feel: compact, Steam components (DFL), Steam localization tokens (`L(token, fallback)`), Steam dialogs and APIs. Look for a native mechanism first (Steam, then Windows, then other plugins).
- Fix causes, no workarounds: no hidden-but-focusable elements, no third-party URLs, no fallback UI copies.
- Don't duplicate Steam settings. The plugin's own Decky page stays empty.
- Never change the refresh rate. With VRR the frame limit is FPS only; a mode change crashes some games (Death Stranding + OptiScaler XeFG + RTSS).
- No Windows power mode or TDP controls: they fight OneXConsole and Intel Platform Framework.
- Propose big UX changes before building them.

## Steam / Decky internals

- **QAM injection:**
  - Decky TabsHook technique (afterPatch + tree patcher).
  - Steam's tab objects are never mutated, wrappers are tagged `Symbol.for("winqs.qam-wrapper")`, and unload restores the fibers.
  - Sections reappear on the next QAM open after a reload.
- **Steam's FPS rows:** the Windows Performance panel is `G() → H() → [M battery, Q FPS rows]`, all plain `function(){return jsx}`.
  - `withoutSteamFpsRows()` expands them and replaces `Q` (identified by its `QuickAccess_Tab_Perf_FPS_*` row components) with the power row.
  - Any mismatch renders Steam's panel untouched.
- **Read-only rows** must not be focusable (`DFL.Field` always is; an empty nav node breaks navigation). Use `DFL.gamepadDialogClasses` markup. CSS hiding doesn't remove an element from navigation.
- **Dialogs:** use `showModalHere()` (active nav context's root window). `DFL.showModal` opens behind the game.
- **Passwords:** Steam `TextField` stays `type=text`; mask with `-webkit-text-security: disc`.
- **Captive portals:**
  - Steam's probe via `SteamClient.System.Network.RegisterForConnectivityTestChanges` (result 2, `strCaptivePortalURL`), plus NLM WEBHIJACK.
  - Open Steam's own login dialog: a `findModuleExport` function containing `strManualCaptivePortalURL`.
  - Steam's Chromium HTTPS-upgrades `http://` URLs.
  - Test with `SetFakeLocalSystemState(2)` and reset to 0.
- **Client settings:** `settingsStore.GetClientSetting(k)` returns `[value, setter]`; Steam mirrors writes back 0.03–3 s later.
- Steam's Performance Monitor is native (`gameoverlayrenderer64.dll`) and can't be extended.
- **CDP trap:** `connect(2, name)` from DevTools replaces the plugin's event listeners. Save and restore `DeckyPluginLoader.pluginEventListeners.get(name)`.
- **WLAN:**
  - Error 5 means Location is off.
  - `retry_password` only for MSMSEC reasons (0x40000–0x4FFFF).
  - Delete only profiles the plugin created.

## Frame limit

- **RTSS** (all APIs): `RTSSHooks64.dll` `LoadProfile("")` → `SetProfileProperty("FramerateLimit")` → `SaveProfile` → `UpdateProfiles`.
  - Works unelevated after `setup_rtss.ps1` (Profiles ACL + "WinQS RTSS" logon task). Only the owner runs it, from the Performance tab (UAC).
  - OneXConsole writes the same limit and kills RTSS when its OSD is turned off; `rtss_keepalive()` restarts it.
  - Keep RTSS's D3D12 OSD renderer enabled.
- **Intel IGCL** fallback: DX9/DX11 only. It is set to 0 whenever RTSS is active.

## Testing

- Don't join other Wi-Fi networks or drop the current connection.
- Restore whatever a test changes: brightness, HDR, RTSS limit, fake network state, dialogs, and the overlay route (`NavigateToRunningApp(true)`).
- A game may be running: avoid display mode changes, and ask for a save before risky tests.
- Report what was verified in the real UI and what wasn't.
