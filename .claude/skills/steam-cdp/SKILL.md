---
name: steam-cdp
description: Drive Steam Big Picture and Decky over CEF DevTools (http://127.0.0.1:8080) to test the plugin on the device - reload the plugin, call backend methods, open Quick Access tabs, press gamepad buttons. Use before any on-device check of this plugin.
---

# Testing the plugin through Steam's CEF DevTools

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
