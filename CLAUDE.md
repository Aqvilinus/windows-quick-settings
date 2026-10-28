# CLAUDE.md

Decky Loader plugin that adds SteamOS-style system controls to Steam Big Picture's Quick Access Menu (QAM) on Windows.

## Environment

- OneXPlayer 3 (Core Ultra, Arc B390), Windows 11 in Xbox full-screen mode, home app OmniConsole. The panel is 1920x1200 with VRR, 30–144 Hz.
- OneXConsole (vendor app, elevated) owns TDP, fans, buttons and its own RTSS OSD.
- Decky Loader 3.3.1 for Windows (official release exe, installed 2026-10-28 over the Decky Manager build; the old exe is in `homebrew\services-backup-v3.3.0-py311`), unelevated, started by Decky Manager. Settings are in `%USERPROFILE%\homebrew\settings\windows-quick-settings`, logs in `homebrew\logs\windows-quick-settings`.
- The backend runs on Decky's frozen Python 3.14 (no pip). `py_modules/` is on `sys.path` (appended by Decky): the plugin's own `winqs/` package and `LICENSES/` are in git; the third-party packages are installed there by `scripts/build.py` from `requirements.txt` and are git-ignored. `psutil` is abi3, so it loads `python3.dll`; Decky's exe has none, the build adds the one from python.org's embeddable package of the same Python version. The rest uses `ctypes` for Win32 / vendor DLLs.
- Steam CEF DevTools: `http://127.0.0.1:8080`. Decky runs in the `SharedJSContext` target.

## Layout

- `main.py`: backend entry. `Plugin` methods are the callables; `_call("<SystemService method>", *args)` runs it on the worker thread and wraps the result / error for the UI.
- `py_modules/winqs/` (one module per Windows feature, see each docstring):
  - `com.py`: sets `sys.coinit_flags = 0` (comtypes initialises COM on import; the process is MTA for pywinrt), `GUID`, `init_worker` (MTA, EcoQoS off). Import it before comtypes.
  - `wlan.py` (Native Wifi API over ctypes): WinRT can't delete profiles, so it stays.
  - `audio.py` / `btaudio.py`: `IMMDevice.GetId` goes through comtypes' raw `__com_GetId` so the string is freed (it runs on every poll).
- `src/index.js`: the whole frontend (plain JavaScript), built into `dist/index.js` (git-ignored) by `pnpm run build` (see `rollup.config.js`).

## Workflow

- Build: `python scripts/build.py` (options in its docstring). The zip's top folder must stay `windows-quick-settings/`: Decky keys settings and logs by folder name. `--local` refreshes this checkout's `py_modules/` (Decky loads the checkout); locked DLLs of the running plugin are renamed `*.old` and deleted by the next build. Restart the plugin's backend afterwards.
- Node: portable v24 LTS in `C:\Users\Ivan\Tools\node` (not on PATH; `.nvmrc` = 24), pnpm through corepack (`packageManager` in package.json). pnpm 12 refuses packages younger than a day (minimumReleaseAge).
- Releases: run the manual `Release` workflow on GitHub with a version.
- Testing on the device over Steam's CEF DevTools (reload the plugin, call the backend, open QAM tabs, gamepad buttons): see the `steam-cdp` skill.
- Performance budget: `get_state` ~8 ms warm, idle CPU 0.

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
- **Steam's Performance panel:** `G() → H() → [M battery, Q FPS rows]`. G, H and Q are plain `function(){return jsx}`; M and its time column B have hooks.
  - `patchSteamPerfPanel()` expands G/H, drops `Q` (identified by its `QuickAccess_Tab_Perf_FPS_*` row components) and wraps M.
  - The wrappers call Steam's M / B (found by `BatterySectionContainer` / `BatteryProjectedValue` in their source). Steam's look is kept as is.
  - While charging Windows gives Steam no time to full, so B shows "?h ?m". Only that is replaced, in Steam's `%1$sh %2$sm` format, with `full_seconds` from `battery.py`: smoothed rate, constant power to 80 %, then an exponential CV taper until C/20.
  - Any mismatch leaves that part as Steam renders it.
- **Icons:** Steam's own icon components (`icon("WiFi")`, the module that exports `Information`; it has 490 icons, list them over CDP). They carry no size, so `SteamIcon` puts them in a 1em box. No hand-drawn SVGs. `WirelessNetwork` takes `strength` 1–4, `AudioVolumeIcon` takes `flVolume` 0–1, `Lock` takes `locked`.
- **Read-only rows** must not be focusable (`DFL.Field` always is; an empty nav node breaks navigation). Use `DFL.gamepadDialogClasses` markup. CSS hiding doesn't remove an element from navigation.
- **Dialogs:** use `showModalHere()` (active nav context's root window). `DFL.showModal` opens behind the game.
- **Footer hints:** the QAM footer is ~350 px wide. A long `onOptionsActionDescription` wraps Steam's own hint ("Adjust slider") onto a second row, so use short Steam tokens (`L("Settings")`).
- **Overlay Settings:** Y on "Performance Overlay Level" opens the plugin's dialog (position, text size, contrast, opacity, graphs). The owner wants it; keep it.
- **Passwords:** Steam `TextField` stays `type=text`; mask with `-webkit-text-security: disc`.
- **Captive portals:**
  - Steam's probe via `SteamClient.System.Network.RegisterForConnectivityTestChanges` (result 2, `strCaptivePortalURL`), plus Windows' own `ConstrainedInternetAccess` connectivity level.
  - Open Steam's own login dialog: a `findModuleExport` function containing `strManualCaptivePortalURL`.
  - Steam's Chromium HTTPS-upgrades `http://` URLs.
  - Test with `SetFakeLocalSystemState(2)` and reset to 0.
- **Client settings:** `settingsStore.GetClientSetting(k)` returns `[value, setter]`; Steam mirrors writes back 0.03–3 s later.
- Steam's Performance Monitor is native (`gameoverlayrenderer64.dll`) and can't be extended.
- **Checked dead ends** (2026-10-28): Steam's `SteamClient.System.Display.SetBrightness` reports success on Windows but doesn't change the panel; `BrightnessOverride.GetDefaultForSystem` fails unpackaged; WinRT has no HDR toggle, no endpoint volume / default audio device, no Wi-Fi profile removal. pywinrt can't call classic COM (audio goes through comtypes/pycaw). No proven library wraps powrprof, DisplayConfig, WLAN, IGCL, RTSSHooks or SetWinEventHook, so `brightness.py`, `hdr.py`, `wlan.py`, `framelimit.py`, `rtss.py` and part of `hotkeys.py` stay on ctypes.
- **CDP trap:** `connect(2, name)` from DevTools replaces the plugin's event listeners. Save and restore `DeckyPluginLoader.pluginEventListeners.get(name)`.
- **Bluetooth** (`bt.py`, "Add Device" dialog, Y = Forget on paired rows, by endpoint id):
  - Paired list: DeviceWatchers over the "paired" selectors with `System.Devices.Aep.IsConnected`, kept running; a poll reads the snapshot (0 ms). It includes LE devices.
  - Search: DeviceWatchers over Windows' own `GetDeviceSelectorFromPairingState(False)` selectors (classic + LE), AEP kind; stops after 30 s or when the dialog closes.
  - Pairing on its own thread with `DeviceInformationCustomPairing`: ConfirmOnly / DisplayPin accepted at once, ConfirmPinMatch answered later through the request's deferral. ProvidePin isn't supported.
  - The PIN / code dialog is closed by the next pairing step and by closing "Add Device" (`showModal(...).Close()` is idempotent and doesn't fire `onCancel`).
  - Steam on Windows has no Bluetooth API (`SteamClient.System.Bluetooth` is absent).
- **WLAN:**
  - Error 5 means Location is off.
  - `retry_password` only for MSMSEC reasons (0x40000–0x4FFFF).
  - Delete only profiles the plugin created.

## Frame limit

- **RTSS** (all APIs): `RTSSHooks64.dll` `LoadProfile("")` → `SetProfileProperty("FramerateLimit")` → `SaveProfile` → `UpdateProfiles`.
  - Works unelevated after `setup_rtss.ps1` (Profiles ACL + "WinQS RTSS" logon task; it gets `-RtssDir` from the registry lookup in `rtss.py`). Only the owner runs it, from the Performance tab (UAC, `os.startfile(..., "runas")`).
  - `RTSSHooks64.dll` is loaded by full path (its folder is searched for dependencies); don't add it to the process DLL path.
  - OneXConsole writes the same limit and kills RTSS when its OSD is turned off; `rtss_keepalive()` restarts it.
  - Keep RTSS's D3D12 OSD renderer enabled.
- **Intel IGCL** fallback: DX9/DX11 only. It is set to 0 whenever RTSS is active.
- **Per-game profiles** (Steam Deck's "Use per-game profile"):
  - `state.json` `frame_profiles` = `{default: {fps, last}, games: {appid: {fps, last}}}`. Turning a game's profile on copies the current settings into it; turning it off deletes it.
  - The frontend sends `SteamUIStore.MainRunningAppID` to `set_active_game` on change (MobX reaction) and every 30 s while a game runs.
  - A switch applies the limit only if the old or the new context has a game profile, so a limit set elsewhere (OneXConsole) isn't undone between two default contexts.
  - The heading ("Performance Settings ⓘ" / "Using default profile" / "Using <game> profile") is Steam Deck's markup with Steam's classes (`PerfProfileInfo`, `SubHeading`…), the `Information` icon and Steam's app icon component. Steam's own Deck components read a SteamOS-only profile store and can't be used.

## Testing

- Don't join other Wi-Fi networks or drop the current connection.
- Restore whatever a test changes: brightness, HDR, RTSS limit, fake network state, dialogs, and the overlay route (`NavigateToRunningApp(true)`).
- A game may be running: avoid display mode changes, and ask for a save before risky tests.
- Report what was verified in the real UI and what wasn't.
