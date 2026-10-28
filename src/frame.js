import * as DFL from "@decky/ui";
import { useEffect, useRef, useState } from "react";
import { Fragment, jsx, jsxs } from "react/jsx-runtime";
import { be, call, lazy } from "./backend.js";
import { L, T, errText, toast } from "./strings.js";
import { Row, chevron, clamp, pressable, showModalHere, spinner, steamIcons } from "./ui.js";

// ---------------------------------------------------------------- Performance tab: frame limit + per-game profiles
// "Frame Limit" works like Steam Deck's TDP Limit: a toggle, and the FPS slider under it while it is on. The cap is
// RTSS (all graphics APIs) or the Intel driver limiter; the refresh rate is never touched (the panel has VRR).
// "Use per-game profile" works like Steam Deck's: the backend keeps a default profile and one per game and applies
// the running game's one (set_active_game in service.py). The heading row and its explainer are Steam Deck's own
// markup and strings (QuickAccess_Tab_Perf_*) with Steam's classes; Steam's own components for them read Steam's
// SteamOS-only profile store, so they can't be used as they are.
export const deckPerfParts = lazy(() => {
    const css = DFL.findModule((m) => m && typeof m === "object" && m.PerfProfileInfo && m.SubHeading && m.GameName);
    const AppImage = DFL.findModuleExport((e) => {
        const t = e && (e.type || e);
        return typeof t === "function" && !!t.prototype && typeof t.prototype.RegisterForAppDetails === "function";
    });
    return css ? { css, Info: steamIcons()?.Information || null, AppImage: AppImage || null } : null;
}, "Steam's per-game profile parts not found");
const APP_ICON = 4; // Steam's EAppAssetType icon
function appOverview(appid) {
    if (!appid) return null;
    try {
        const run = window.SteamUIStore.MainRunningApp;
        if (run && String(run.appid) === String(appid)) return run;
        return window.appStore.GetAppOverviewByAppID(Number(appid)) || null;
    }
    catch { return null; }
}
// Steam's "%1$s" strings with a React element in place of the argument
function localizeWith(token, fallback, el) {
    const str = L(token, fallback);
    const i = str.indexOf("%1$s");
    return i < 0 ? str : jsxs(Fragment, { children: [str.slice(0, i), el, str.slice(i + 4)] });
}
function showProfileExplainer() {
    const parts = deckPerfParts();
    showModalHere(jsx(DFL.ConfirmModal, {
        bAlertDialog: true, className: parts ? parts.css.PerfProfileExplainerModal : undefined,
        strTitle: L("QuickAccess_Tab_Perf_GameProfileExplainer_Title", "Default and game specific settings"),
        strDescription: L("QuickAccess_Tab_Perf_GameProfileExplainer_Description", ""),
        strOKButtonText: L("QuickAccess_Tab_Perf_GameProfileExplainer_Dismiss", "Got it"),
    }));
}
// Steam Deck's "Performance Settings (i)" heading with "Using default profile" / "[icon] Using <game> profile" under it
function ProfileHeading({ app, perGame }) {
    const { css, Info, AppImage } = deckPerfParts();
    const label = jsxs("div", { className: css.Heading, children: [
        jsx("span", { className: css.Text, children: L("QuickAccess_Tab_Perf_PerformanceSettings", "Performance Settings") }),
        Info ? jsx(Info, { className: css.Icon }) : null,
    ] });
    const text = perGame
        ? localizeWith("QuickAccess_Tab_Perf_GameSpecificSettings", "Using %1$s profile", jsx("span", { className: css.GameName, children: app.display_name }))
        : L("QuickAccess_Tab_Perf_DefaultSettings", "Using default profile");
    return jsx(DFL.Field, {
        className: css.PerfProfileInfo, label, focusable: true, onActivate: showProfileExplainer, onClick: showProfileExplainer,
        childrenLayout: "below", bottomSeparator: "none", padding: "none",
        children: jsxs("div", { className: css.SubHeading, children: [
            perGame && AppImage ? jsx(AppImage, { app, eAssetType: APP_ICON, className: css.Icon, bShortDisplay: true }) : null,
            jsx("div", { className: css.Text, children: text }),
        ] }),
    });
}
const APPLY_DELAY_MS = 700; // same debounce as Steam's own sliders; a refresh change blinks the screen

export function FrameSection({ active }) {
    const [info, setInfo] = useState(null);
    const [shown, setShown] = useState(null); // value shown while a change is waiting/applying
    const [rtssBusy, setRtssBusy] = useState(false);
    const timer = useRef(null);
    const busy = useRef(false);
    const load = async () => {
        if (busy.current) return;
        try { setInfo(await call(be.perfState)); }
        catch (e) { setInfo({ errors: { load: errText(e) } }); }
    };
    useEffect(() => {
        if (!active) return undefined;
        load();
        const t = setInterval(load, 5000);
        return () => clearInterval(t);
    }, [active]);
    useEffect(() => () => clearTimeout(timer.current), []);
    if (!info || !info.display || !info.frame_limit) return null;
    const fl = info.frame_limit;
    // FPS limit range: 30 .. current refresh rate (a cap above it changes nothing), 1 FPS steps. With VRR the panel
    // follows the game's frame rate, so any value paces evenly and the refresh rate is never touched by the limit.
    const fpsMin = fl.min || 30;
    const fpsMax = clamp(info.display.hz || 300, fpsMin, fl.max || 300);
    const cur = shown || { fps: fl.fps, hz: info.display.hz };
    const limited = fl.supported && cur.fps > 0;
    // one change at a time; polls wait for it, and the shown value goes once the new state is loaded
    const run = async (fn) => {
        busy.current = true;
        try { await fn(); }
        catch (e) { toast(errText(e)); }
        finally {
            busy.current = false;
            await load();
            setShown(null);
        }
    };
    const later = (fn) => {
        clearTimeout(timer.current);
        timer.current = setTimeout(() => run(fn), APPLY_DELAY_MS);
    };
    const setFps = (fps) => {
        setShown({ fps, hz: cur.hz });
        later(() => call(be.setFrameLimit, fps));
    };
    const toggleLimit = (on) => {
        if (!on) { setFps(0); return; }
        const want = info.last_frame_limit || Math.round(cur.hz / 2);
        setFps(clamp(want, fpsMin, fpsMax));
    };
    const rows = [];
    const parts = deckPerfParts();
    const prof = info.profile || {};
    const app = appOverview(prof.game);
    const perGame = !!(prof.per_game && app);
    const setPerGame = (on) => {
        clearTimeout(timer.current);
        run(() => call(be.setGameProfile, on));
    };
    if (parts && fl.supported) {
        rows.push(Row(jsx(ProfileHeading, { app, perGame }), "profileinfo"));
        rows.push(Row(jsx(DFL.ToggleField, {
            label: L("QuickAccess_Tab_Perf_ToggleGameSettings", "Use per-game profile"),
            checked: perGame, disabled: !app, onChange: setPerGame,
            explainer: L("QuickAccess_Tab_Perf_GameProfileExplainer_Description", undefined),
        }), "pergame"));
    }
    if (fl.supported) {
        rows.push(Row(jsx(DFL.ToggleField, {
            label: L("QuickAccess_Tab_Perf_FrameLimit", "Frame Limit"), checked: limited, onChange: toggleLimit,
            bottomSeparator: limited ? "none" : "standard",
        }), "fpslimit"));
        if (limited) {
            rows.push(Row(jsx(DFL.SliderField, {
                value: clamp(cur.fps, fpsMin, fpsMax), min: fpsMin, max: fpsMax, step: 1, showValue: true, valueSuffix: " FPS",
                notchCount: 2, notchTicksVisible: false,
                notchLabels: [{ notchIndex: 0, label: String(fpsMin), value: fpsMin }, { notchIndex: 1, label: String(fpsMax), value: fpsMax }],
                onChange: setFps,
            }), "fps"));
        }
    }
    else {
        rows.push(Row(jsx(DFL.Field, { label: L("QuickAccess_Tab_Perf_FrameLimit", "Frame Limit"), description: fl.error || "unavailable" }), "fpslimit"));
    }
    // RTSS limits every graphics API; until its one-time setup has run only the Intel driver limit (DX9/DX11) is used
    if (fl.method !== "rtss" && info.rtss === "setup") {
        const startSetup = async () => {
            if (rtssBusy) return;
            setRtssBusy(true);
            try { await call(be.setupRtss); toast(T.rtssConfirm); }
            catch (e) { toast(errText(e)); }
            setTimeout(() => setRtssBusy(false), 15000);
        };
        rows.push(Row(jsx(DFL.Field, {
            label: T.rtssSetup, description: rtssBusy ? T.rtssWorking : T.rtssSetupHint,
            ...pressable(startSetup), children: rtssBusy ? spinner() : chevron(),
        }), "rtss"));
    }
    else if (fl.method !== "rtss" && info.rtss === "missing" && fl.supported) {
        rows.push(Row(jsx(DFL.Field, { label: T.rtssSetup, description: T.rtssMissing }), "rtss"));
    }
    return jsxs(DFL.PanelSection, {
        title: parts && fl.supported ? undefined : L("QuickAccess_Tab_Perf_PerformanceSettings", "Performance Settings"),
        children: rows,
    });
}
