// Windows Quick Settings — Decky Loader frontend, built into dist/index.js by `pnpm run build` (@decky/rollup).
// Injects Wi-Fi / Bluetooth / audio / display controls into the Quick Settings tab (gear icon) and frame limit /
// overlay controls into the Performance tab of the Steam Big Picture Quick Access Menu.
// @decky/ui and React are not bundled: the build maps them to the copies Steam and Decky already loaded.
//
// This file: the plugin entry, Steam's "<model> Display Scaling" title, Steam menus in games (Ctrl+1 / Ctrl+2).
//   backend.js  backend calls, lazy()          strings.js  Steam tokens and own strings
//   ui.js       icons, shared store, UI pieces quick.js    the Quick Settings section
//   wifi.js     Wi-Fi dialogs, sign-in pages   bluetooth.js  device rows, "Add Device"
//   overlay.js  Performance overlay, Steam's Performance panel patch
//   frame.js    frame limit, per-game profiles qam.js      the Quick Access injection
import { addEventListener, definePlugin, removeEventListener } from "@decky/api";
import manifest from "@decky/manifest";
import * as DFL from "@decky/ui";
import { Fragment, jsx } from "react/jsx-runtime";
import { LOG, be, call, fnSrc, lazy } from "./backend.js";
import { deckPerfParts } from "./frame.js";
import { steamFpsRowTypes } from "./overlay.js";
import { injectStatus, installPatch, setStatus, stopped, uninstallPatch } from "./qam.js";
import { errText } from "./strings.js";
import { icon, steamIcons } from "./ui.js";
import { openWifiModal, startPortalWatch, steamPortalDialog, stopPortalWatch } from "./wifi.js";

// ---------------------------------------------------------------- "<model> Display Scaling" -> "Display Scaling"
// Steam titles its own display-scaling section with the panel's model name using this
// localization token; swap it for Steam's own plain "Display Scaling" string while loaded.
const SCALING_TITLE_TOKEN = "Settings_Display_DisplayScaling_ScalingForTVName";
let savedScalingTitle = null;
let ownedScalingTitle = null;
function renameScalingSection() {
    try {
        const m = window.LocalizationManager?.m_mapTokens;
        if (!m || !m.has(SCALING_TITLE_TOKEN)) return;
        const current = m.get(SCALING_TITLE_TOKEN);
        if (savedScalingTitle === null) savedScalingTitle = current;
        const plain = (m.get("Settings_Display_DisplayScaling_Scaling") || String(current).replace(/%1\$s/g, "")).trim();
        m.set(SCALING_TITLE_TOKEN, plain);
        ownedScalingTitle = plain;
    }
    catch (e) { console.warn(LOG, "rename scaling section failed", e); }
}
function restoreScalingSection() {
    try {
        // look the map up again (a language switch replaces it) and only undo our own value
        const m = window.LocalizationManager?.m_mapTokens;
        if (m && savedScalingTitle !== null && m.get(SCALING_TITLE_TOKEN) === ownedScalingTitle) {
            m.set(SCALING_TITLE_TOKEN, savedScalingTitle);
        }
        savedScalingTitle = ownedScalingTitle = null;
    }
    catch (e) { console.warn(LOG, "restore scaling section failed", e); }
}

// ---------------------------------------------------------------- Steam menus in games (Ctrl+1 / Ctrl+2)
// Big Picture reads Ctrl+1 / Ctrl+2 (sent by OneXConsole for D-pad + M1) only while its own window
// has focus. We tell the backend which Steam overlay processes exist (one per game with an overlay);
// it registers the combos only while such a game is the foreground window and reports a press with
// that game's overlay PID. We then press Steam's own Steam / Quick Access button handler on that
// game's overlay window, exactly what the hardware buttons do on a Steam Deck (toggling, last QAM
// tab, double press, and Steam's own "buttons disabled" state included). Event driven, no polling.
const isGameOverlay = (w) => !!w?.IsGamepadUIOverlayWindow?.();
function overlayWindowFor(overlayPid) {
    try {
        const ws = window.SteamUIStore.WindowStore;
        const byPid = ws.m_mapOverlayPopupByPID;
        let w = overlayPid != null ? byPid?.get?.(Number(overlayPid)) : null;
        if (!w && ws.GetOverlayInstances) {
            const appid = window.SteamUIStore.MainRunningAppID;
            if (appid != null) w = ws.GetOverlayInstances(appid).find(isGameOverlay);
        }
        return w || null;
    }
    catch { return null; }
}
function onMenuHotkey(menu, overlayPid) {
    const w = overlayWindowFor(overlayPid) || window.SteamUIStore?.WindowStore?.GamepadUIMainWindowInstance;
    if (!w) return;
    try {
        if (menu === "qam") w.OnQuickAccessButtonPressed();
        else w.OnHomeButtonPressed();
    }
    catch (e) { console.warn(LOG, "menu hotkey failed", e); }
}
function gameOverlayPids() {
    try {
        const byPid = window.SteamUIStore.WindowStore.m_mapOverlayPopupByPID;
        if (!byPid?.entries) return [];
        return [...byPid.entries()].filter(([, w]) => isGameOverlay(w)).map(([pid]) => Number(pid)).sort((a, b) => a - b);
    }
    catch { return []; }
}
// Steam's own MobX `reaction` (Steam ships one MobX instance; never bundle a second one).
const findMobxReaction = lazy(() => DFL.findModuleExport((e) => {
    const src = fnSrc(e);
    return /!=null\?\w+:"Reaction"/.test(src) && src.includes("compareStructural");
}));
let sentOverlays = null;
let overlayRetry = null;
async function syncOverlays(force) {
    const pids = gameOverlayPids();
    const key = pids.join(",");
    if (!force && key === sentOverlays) return;
    clearTimeout(overlayRetry);
    try {
        await call(be.setGameOverlays, pids);
        sentOverlays = key; // only remembered once the backend has it
    }
    catch (e) {
        sentOverlays = null;
        overlayRetry = setTimeout(() => syncOverlays(true), 3000);
        console.warn(LOG, "set_game_overlays failed, retrying", e);
    }
}
// The running game for per-game frame limit profiles: Steam's MainRunningAppID, sent when it changes, and resent
// every 30 s while a game runs (a backend restart forgets it; the backend ignores repeats).
let sentGame;
let gameRetry = null;
function runningGameId() {
    try { const id = window.SteamUIStore.MainRunningAppID; return id ? String(id) : null; }
    catch { return null; }
}
async function syncGame(force) {
    const id = runningGameId();
    if (!force && id === sentGame) return;
    clearTimeout(gameRetry);
    try {
        await call(be.setActiveGame, id);
        sentGame = id;
    }
    catch (e) {
        sentGame = undefined;
        gameRetry = setTimeout(() => syncGame(false), 3000);
        console.warn(LOG, "set_active_game failed, retrying", e);
    }
}
let stopGameWatch = null;
let gameHeartbeat = null;
function startGameWatch() {
    const reaction = findMobxReaction();
    if (reaction) stopGameWatch = reaction(() => runningGameId(), () => syncGame(false), { fireImmediately: true });
    else syncGame(false);
    gameHeartbeat = setInterval(() => { if (!reaction || sentGame) syncGame(true); }, 30000);
}
function stopGameWatchNow() {
    try { stopGameWatch?.(); } catch { }
    clearTimeout(gameRetry);
    clearInterval(gameHeartbeat);
    stopGameWatch = gameHeartbeat = null;
    sentGame = undefined;
}
let stopOverlayWatch = null;
let lifetimeReg = null;
let overlayHeartbeat = null;
function startMenuHotkeys() {
    try { addEventListener("winqs_menu_hotkey", onMenuHotkey); }
    catch (e) { console.warn(LOG, "no backend events", e); }
    const reaction = findMobxReaction();
    if (reaction) {
        // fires when an overlay window appears or disappears (later than the game's start event)
        stopOverlayWatch = reaction(() => gameOverlayPids().join(","), () => syncOverlays(false), { fireImmediately: true });
    }
    else {
        syncOverlays(false);
    }
    try {
        // fallback and backend-restart safety: re-sync around game start/stop
        lifetimeReg = SteamClient.GameSessions.RegisterForAppLifetimeNotifications(() => {
            setTimeout(() => syncOverlays(true), 1000);
            setTimeout(() => syncOverlays(!reaction), 5000);
        });
    }
    catch (e) { console.warn(LOG, "no app lifetime notifications", e); }
    // a backend restart forgets the list; while games run, resend it now and then (idempotent, cheap)
    overlayHeartbeat = setInterval(() => { if (sentOverlays) syncOverlays(true); }, 30000);
}
function stopMenuHotkeys() {
    try { removeEventListener("winqs_menu_hotkey", onMenuHotkey); } catch { }
    try { stopOverlayWatch?.(); } catch { }
    try { lifetimeReg?.unregister(); } catch { }
    clearTimeout(overlayRetry);
    clearInterval(overlayHeartbeat);
    stopOverlayWatch = lifetimeReg = overlayHeartbeat = null;
    if (sentOverlays) call(be.setGameOverlays, []).catch(() => { });
    sentOverlays = null;
}

export default definePlugin(() => {
    try { window.__WINQS?.stop?.(); } catch { } // a stale copy, if any
    window.__WINQS = { stop: uninstallPatch, status: injectStatus, openWifi: openWifiModal }; // diagnostics from the console
    renameScalingSection();
    startMenuHotkeys();
    startGameWatch();
    startPortalWatch();
    const tryInstall = (attempt) => {
        if (stopped) return;
        try {
            installPatch();
        }
        catch (e) {
            if (attempt < 5) { setTimeout(() => tryInstall(attempt + 1), 2000); return; } // Steam may still be loading
            setStatus("error", errText(e));
            console.error(LOG, "could not patch Quick Access", e);
        }
    };
    tryInstall(0);
    // The first scan of Steam's ~40k webpack exports costs ~0.1 s: do these lookups while idle, not on the first open
    // of a tab. warm() keeps only hits, so a lookup that misses now still runs on first use.
    const warmUp = setTimeout(() => [steamIcons, steamFpsRowTypes, deckPerfParts, steamPortalDialog].forEach((f) => f.warm()),
        5000);
    return {
        name: manifest.name,
        titleView: jsx("div", { className: DFL.staticClasses?.Title, children: manifest.name }),
        // nothing here: the controls live in Steam's Quick Settings and Performance tabs, the plugin has no settings
        content: jsx(Fragment, {}),
        icon: icon("WiFi"),
        onDismount() {
            clearTimeout(warmUp);
            uninstallPatch();
            restoreScalingSection();
            stopMenuHotkeys();
            stopGameWatchNow();
            stopPortalWatch();
            if (window.__WINQS?.stop === uninstallPatch) delete window.__WINQS;
        },
    };
});
