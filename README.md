# Windows Quick Settings

A [Decky Loader](https://github.com/SteamDeckHomebrew/decky-loader) plugin for **Steam Big Picture on Windows**
handhelds. It adds the system controls Steam Deck users get on SteamOS, right inside Steam's own Quick Access Menu,
so you never have to leave Big Picture (or the game) for the Windows desktop.

Built and tested on a OneXPlayer 3 (Intel Core Ultra, Arc graphics) running Windows 11 in Xbox full screen mode with
OmniConsole as the home app, and the Windows build of Decky Loader.

## What it adds

**Quick Settings tab** (Steam's gear tab), in Steam's own style:

- Airplane mode, Wi-Fi and Bluetooth toggles
- Wi-Fi network list with signal and security, connect / disconnect / forget, password entry with a show-password
  toggle, retry after a wrong password, internet status, and network sign-in pages (captive portals) through
  Steam's own "Log in to the network" dialog
- Bluetooth devices: connect / disconnect audio devices, "Add Device" opens the Windows pairing page
- Brightness, output / input volume and audio device pickers
- Night mode and HDR

**Performance tab:**

- Performance Overlay Level slider (Steam's performance monitor), with Steam's duplicate FPS corner / contrast rows
  removed
- Projected charging time in Steam's battery block (Windows gives Steam none, so it shows "?h ?m")
- Frame Limit toggle with an FPS slider, through RivaTuner Statistics Server (all graphics APIs) or, without RTSS,
  the Intel graphics driver limiter (DX9 / DX11 only)

**In games:** Steam's left and right side menus open with Ctrl+1 / Ctrl+2 (for example mapped to D-pad + M1 in
OneXConsole) even while the game has focus.

The plugin's own Decky page is intentionally empty: everything lives in Steam's tabs.

## Requirements

- Windows 10/11 with Steam Big Picture and the Windows build of Decky Loader
- Optional: [RivaTuner Statistics Server](https://www.guru3d.com/download/rtss-rivatuner-statistics-server-download/)
  for the frame limit in DX12 / Vulkan games. RTSS needs administrator rights, the plugin does not: the first time,
  the Performance tab offers a one-time setup (a Windows UAC prompt) that lets your account change RTSS profiles and
  registers a scheduled task that starts RTSS at logon.

## How it works

- `main.py` is the Decky backend entry point; `backend/winqs/` talks to Windows directly with `ctypes` (WLAN API,
  Windows Runtime radios, Core Audio, DisplayConfig, Network List Manager, Intel IGCL, RTSS hooks API). No extra
  Python packages are needed.
- `dist/index.js` is the frontend. It injects its sections into Steam's Quick Access Menu tabs and uses Steam's own
  components and localization strings wherever they exist.

## Install

Copy this folder to `%USERPROFILE%\homebrew\plugins\windows-quick-settings` and restart Decky Loader (or reload the
plugin from Decky's developer settings).

## License

[MIT](LICENSE)
