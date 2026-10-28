import * as DFL from "@decky/ui";
import * as R from "react";
import { useEffect, useState } from "react";
import { jsx } from "react/jsx-runtime";
import { LOG, be, call, lazy } from "./backend.js";
import { L, T } from "./strings.js";
import { Row, clamp, dialog, latestWins, showModalHere } from "./ui.js";

// ---------------------------------------------------------------- Performance tab: overlay level
// Steam for Windows has a full performance monitor (detail levels, text size, contrast,
// background opacity, graphs) but only exposes it in Settings > In Game. These client
// settings are read/written through settingsStore.GetClientSetting(key) -> [value, setter].
const PERF_KEYS = {
    corner: "overlay_fps_counter_corner",          // 0 = off, 1..4 = corner
    level: "overlay_fps_counter_detail_level",     // 1..4
    scale: "overlay_fps_counter_scale_factor",     // 0.2..1.4
    saturation: "overlay_fps_counter_saturation_factor", // 0..1
    opacity: "overlay_fps_counter_bgopacity",      // 0..1
    fpsGraph: "overlay_fps_counter_fps_graph",
    cpuGraph: "overlay_fps_counter_cpu_graph",
};
function getClientSetting(k) {
    try { return window.settingsStore.GetClientSetting(k)[0]; }
    catch { return undefined; }
}
// Steam applies a client setting asynchronously (SteamClient.Settings.SetSetting) and only
// later mirrors it back into settingsStore: 40-300 ms usually, sometimes ~3 s. So the UI shows
// the value just written right away, until Steam reports the same value (or 5 s pass), and each
// key has at most one write in flight: dragging OFF->4 sends only the latest notch, not 1,2,3,4.
const perfShown = {};   // key -> { v, t } value shown before Steam confirms it
const perfWriters = {};  // key -> latestWins writer
function setClientSetting(k, v) {
    perfShown[k] = { v, t: Date.now() };
    perfWriters[k] ??= latestWins((x) => window.settingsStore.GetClientSetting(k)[1](x));
    perfWriters[k](v);
}
function readPerfKey(k) {
    const real = getClientSetting(k);
    const shown = perfShown[k];
    if (shown) {
        if (real === shown.v || Date.now() - shown.t > 5000) delete perfShown[k];
        else return shown.v;
    }
    return real;
}
function readPerf() {
    const o = {};
    for (const [name, key] of Object.entries(PERF_KEYS)) o[name] = readPerfKey(key);
    return o;
}
const round1 = (v) => Math.round(Number(v) * 10) / 10;
const perfLevel = (p) => (p.corner > 0 ? clamp(p.level || 1, 1, 4) : 0); // 0 = overlay off
let lastPerfCorner = 2;
function perfLevelNames() {
    return [
        L("QuickAccess_Tab_Perf_Overlay_Level_OFF", "off"),
        L("Settings_InGame_PerfOverlay_ClassicFPSOnly", "FPS Single Value"),
        L("Settings_InGame_PerfOverlay_FPSDetailsAndGraph", "FPS Details"),
        L("Settings_InGame_PerfOverlay_FPSCPUGPUSummary", "FPS Details, CPU & GPU Utilization"),
        L("Settings_InGame_PerfOverlay_FPSCPUGPURAMDetails", "FPS, CPU, GPU & RAM Full Details"),
    ];
}

// Steam's own QAM rows "Show FPS in Corner" and "FPS High Contrast" duplicate the overlay controls (position is a
// setting of the overlay, contrast is covered by "Text contrast/saturation"), so they are dropped from Steam's
// Performance panel at render time. Steam's panel (G -> H) and the small component holding those two rows (Q) are
// plain "return <jsx>" functions without state, so their output can be expanded and filtered. Q is recognised by
// rendering only Steam's FPS corner/contrast row components, found by their localization tokens. Anything
// unexpected -> Steam's panel is rendered untouched.
const steamFpsRowTypes = lazy(() => {
    const has = (tok) => (e) => typeof e === "function" && Function.prototype.toString.call(e).includes(tok);
    const corner = DFL.findModuleExport(has("QuickAccess_Tab_Perf_FPS_Corner"));
    const contrast = DFL.findModuleExport(has("QuickAccess_Tab_Perf_FPS_Contrast"));
    return corner && contrast ? new Set([corner, contrast]) : null;
});
const isPureRenderFn = (t) => typeof t === "function" && !(t.prototype && t.prototype.isReactComponent)
    && /^function\s*\w*\(\)\s*\{\s*return\b/.test(Function.prototype.toString.call(t));
function onlyFpsRows(el, rows) { // true if this element tree renders nothing but Steam's FPS rows (at least one)
    let found = 0;
    const walk = (n) => {
        if (n == null || typeof n === "boolean" || typeof n === "string" || typeof n === "number") return true;
        if (Array.isArray(n)) return n.every(walk);
        if (!R.isValidElement(n)) return false;
        if (rows.has(n.type)) { found++; return true; }
        if (typeof n.type === "string" || (typeof n.type === "function" && !(n.props && "children" in n.props))) {
            return typeof n.type !== "function" && walk(n.props && n.props.children);
        }
        return walk(n.props && n.props.children); // fragments and wrapper rows
    };
    return walk(el) && found > 0;
}
// Projected charging time in Steam's battery block. On Windows Steam gets no time to full and shows "?h ?m" while
// charging; the backend estimates it (battery.py) and only that "?h ?m" is replaced, in Steam's own format.
// Steam's battery panel and its time column are components with hooks, recognised by their class-name keys
// (BatterySectionContainer, BatteryProjectedValue). The panel's wrapper calls Steam's render function and swaps the
// time column for one that calls Steam's. Steam's hooks run in the same order inside the wrappers, so its state and
// updates are unchanged.
export const PerfVisible = R.createContext(false);
const srcHits = new WeakMap(); // component -> { [needle]: bool }
function srcHas(t, needle) {
    if (typeof t !== "function") return false;
    let hit = srcHits.get(t);
    if (!hit) srcHits.set(t, (hit = {}));
    if (!(needle in hit)) hit[needle] = Function.prototype.toString.call(t).includes(needle);
    return hit[needle];
}
const isBatteryPanel = (t) => srcHas(t, "BatterySectionContainer") && !isPureRenderFn(t);
const isBatteryDetails = (t) => srcHas(t, "BatteryProjectedValue");
// Rebuilds an element tree with every element whose type matches `pred` re-typed to `map(type)`.
function swapTypes(n, pred, map, state) {
    if (Array.isArray(n)) {
        const next = n.map((c) => swapTypes(c, pred, map, state));
        return next.some((c, i) => c !== n[i]) ? next : n;
    }
    if (!R.isValidElement(n)) return n;
    if (pred(n.type)) { state.hit = true; return jsx(map(n.type), n.props, n.key ?? undefined); }
    const kids = n.props && n.props.children;
    if (kids === undefined) return n;
    const next = swapTypes(kids, pred, map, state);
    return next === kids ? n : R.cloneElement(n, undefined, ...(Array.isArray(next) ? next : [next]));
}
function useChargeTime(needed) {
    const visible = R.useContext(PerfVisible) && needed;
    const [sec, setSec] = useState(null);
    useEffect(() => {
        if (!visible) return undefined;
        let alive = true;
        const poll = async () => {
            try {
                const b = await call(be.batteryState);
                const v = b && typeof b.full_seconds === "number" ? Math.round(b.full_seconds / 60) * 60 : null;
                if (alive) setSec(v);
            }
            catch { }
        };
        poll();
        const t = setInterval(poll, 10000); // shown in whole minutes; the backend averages the rate over time
        return () => { alive = false; clearInterval(t); setSec(null); };
    }, [visible]);
    return sec;
}
const batteryWrappers = new WeakMap(); // Steam component -> our wrapper, stable so React never remounts it
function wrapperOf(type, make) {
    let w = batteryWrappers.get(type);
    if (!w) batteryWrappers.set(type, (w = make(type)));
    return w;
}
let warnedBattery = false;
function batteryWithChargeTime(Panel) {
    return function WinQSBattery(props) {
        const out = Panel(props);
        const state = { hit: false };
        const tree = swapTypes(out, isBatteryDetails, (D) => wrapperOf(D, detailsWithChargeTime), state);
        if (!state.hit && out && !warnedBattery) { warnedBattery = true; console.warn(LOG, "Steam's battery time column not found"); }
        return tree;
    };
}
function detailsWithChargeTime(Details) {
    return function WinQSBatteryDetails(props) {
        const out = Details(props);
        const [value, ...rest] = R.isValidElement(out) ? [].concat(out.props.children) : [];
        const unknown = R.isValidElement(value) && typeof value.props.children === "string" && value.props.children.includes("?");
        const sec = useChargeTime(unknown);
        if (!unknown || sec === null) return out;
        // Steam's own format and rounding: "%1$sh %2$sm" with whole hours and minutes, no padding
        const text = L("QuickAccess_Tab_Perf_BatteryTimeRemaining", "%1$sh %2$sm")
            .replace("%1$s", String(Math.floor(sec / 3600))).replace("%2$s", String(Math.floor(sec / 60) % 60));
        return R.cloneElement(out, undefined, R.cloneElement(value, undefined, text), ...rest);
    };
}
// Returns Steam's Performance panel without its FPS rows and with the charging time filled in the battery block. Parts it can't
// recognise are left as Steam renders them.
export function patchSteamPerfPanel(original) {
    if (!R.isValidElement(original)) return { tree: original, fps: false, battery: false };
    const rows = steamFpsRowTypes();
    let fps = false, battery = false;
    const transform = (n, depth) => {
        if (Array.isArray(n)) return n.map((c) => transform(c, depth));
        if (!R.isValidElement(n)) return n;
        if (isBatteryPanel(n.type)) { battery = true; return jsx(wrapperOf(n.type, batteryWithChargeTime), n.props, n.key ?? undefined); }
        if (isPureRenderFn(n.type) && !Object.keys(n.props || {}).length) {
            const out = n.type();
            if (rows && onlyFpsRows(out, rows)) { fps = true; return null; }
            return depth < 3 ? transform(out, depth + 1) : n;
        }
        const kids = n.props && n.props.children;
        if (kids === undefined || typeof n.type === "function" && depth >= 3) return n;
        const next = transform(kids, depth);
        return next === kids ? n : R.cloneElement(n, undefined, ...(Array.isArray(next) ? next : [next]));
    };
    try {
        const out = transform(original, 0);
        return fps || battery ? { tree: out, fps, battery } : { tree: original, fps, battery };
    }
    catch (e) {
        console.warn(LOG, "could not patch Steam's Performance panel", e);
        return { tree: original, fps: false, battery: false };
    }
}

function usePerf(active) {
    const [p, setP] = useState(readPerf);
    useEffect(() => {
        if (!active) return undefined;
        const sync = () => setP((old) => {
            const next = readPerf();
            return JSON.stringify(next) === JSON.stringify(old) ? old : next; // same object = no re-render
        });
        sync();
        // follow changes made elsewhere (Steam settings): Steam's settings-change event, plus a slow safety poll
        let reg = null;
        try {
            reg = SteamClient.Settings.RegisterForSettingsChanges(() => { setTimeout(sync, 50); setTimeout(sync, 400); });
        }
        catch { reg = null; }
        const t = setInterval(sync, reg ? 3000 : 500);
        return () => { clearInterval(t); try { reg?.unregister(); } catch { } };
    }, [active]);
    return [p, setP];
}
// The overlay's look and position: the gamepad Options button on the level slider opens it.
function OverlaySettingsModal({ closeModal }) {
    const [p, setP] = usePerf(true);
    const level = perfLevel(p);
    const setVal = (name, v) => { setClientSetting(PERF_KEYS[name], v); setP(readPerf()); };
    const corner = p.corner > 0 ? p.corner : lastPerfCorner;
    const slider = (name, label, min, max) => jsx(DFL.SliderField, {
        label, value: round1(p[name] ?? min), min, max, step: 0.1, showValue: false, layout: "below",
        onChange: (v) => setVal(name, round1(v)),
    }, name);
    return dialog(closeModal, L("QuickAccess_Tab_Perf_Overlay", "Performance Overlay"), [
        jsx(DFL.DropdownItem, {
            label: T.overlayPosition,
            rgOptions: [
                { data: 1, label: L("QuickAccess_Tab_Perf_FPS_Corner_TopLeft", "Top Left") },
                { data: 2, label: L("QuickAccess_Tab_Perf_FPS_Corner_TopRight", "Top Right") },
                { data: 4, label: L("QuickAccess_Tab_Perf_FPS_Corner_BottomLeft", "Bottom Left") },
                { data: 3, label: L("QuickAccess_Tab_Perf_FPS_Corner_BottomRight", "Bottom Right") },
            ],
            selectedOption: corner,
            onChange: (o) => {
                if (!o) return;
                lastPerfCorner = o.data;
                if (p.corner > 0) setVal("corner", o.data); // while the overlay is off, used when it is turned on
                else setP({ ...p });
            },
        }, "position"),
        slider("scale", L("Settings_InGame_PerfOverlay_TextSize", "Text size scaling"), 0.2, 1.4),
        slider("saturation", L("Settings_InGame_PerfOverlay_Saturation", "Text contrast/saturation"), 0, 1),
        slider("opacity", L("Settings_InGame_PerfOverlay_BGOpacity", "Background opacity"), 0, 1),
        level > 1 && jsx(DFL.ToggleField, {
            label: L("Settings_InGame_PerfOverlayShowFPSGraph", "Show FPS Avg/Min Graph"), checked: !!p.fpsGraph,
            onChange: (v) => setVal("fpsGraph", v),
        }, "fpsGraph"),
        level > 2 && jsx(DFL.ToggleField, {
            label: L("Settings_InGame_PerfOverlayShowCPUGraph", "Show CPU Utilization Per-Core Graph"), checked: !!p.cpuGraph,
            onChange: (v) => setVal("cpuGraph", v),
        }, "cpuGraph"),
    ], jsx(DFL.DialogButton, { onClick: closeModal, children: L("Button_Close", "Close") }));
}
function openOverlaySettings() { showModalHere(jsx(OverlaySettingsModal, {})); }
export function PerfSection({ active }) {
    const [p, setP] = usePerf(active);
    if (p.corner === undefined) return null;
    const level = perfLevel(p);
    if (p.corner > 0) lastPerfCorner = p.corner;
    const names = perfLevelNames();
    const notches = [0, 1, 2, 3, 4].map((i) => ({ notchIndex: i, label: i === 0 ? names[0] : String(i), value: i }));
    const setLevel = (v) => {
        if (v === 0) {
            setClientSetting(PERF_KEYS.corner, 0);
        }
        else {
            if (!(p.corner > 0)) setClientSetting(PERF_KEYS.corner, lastPerfCorner || 2);
            setClientSetting(PERF_KEYS.level, v);
        }
        setP(readPerf());
    };
    return jsx(DFL.PanelSection, {
        children: Row(jsx(DFL.SliderField, {
            label: L("QuickAccess_Tab_Perf_Overlay_Level", "Performance Overlay Level"),
            description: level > 0 ? names[level] : null,
            value: level, min: 0, max: 4, step: 1, layout: "below",
            notchCount: 5, notchLabels: notches, notchTicksVisible: false, showValue: false,
            onChange: setLevel,
            // Steam's short "Settings" label: the QAM footer is narrow, and a longer hint wraps Steam's own
            // "Adjust slider" hint onto a second row
            onOptionsButton: openOverlaySettings, onOptionsActionDescription: L("Settings", "Settings"),
        }), "level"),
    });
}
