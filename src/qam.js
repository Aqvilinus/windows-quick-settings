import manifest from "@decky/manifest";
import * as DFL from "@decky/ui";
import * as R from "react";
import { useEffect } from "react";
import { Fragment, jsx, jsxs } from "react/jsx-runtime";
import { LOG } from "./backend.js";
import { FrameSection } from "./frame.js";
import { PerfSection, PerfVisible, patchSteamPerfPanel } from "./overlay.js";
import { QuickSettings } from "./quick.js";
import { errText } from "./strings.js";
import { Row, useSubscription } from "./ui.js";

// ---------------------------------------------------------------- error boundary
class ErrorBoundary extends R.Component {
    constructor(props) { super(props); this.state = { err: null }; }
    static getDerivedStateFromError(err) { return { err }; }
    componentDidCatch(err) { console.error(LOG, "render error", err); }
    render() {
        if (this.state.err) {
            return jsx(DFL.PanelSection, { children: Row(jsx(DFL.Field, { label: manifest.name, description: errText(this.state.err) })) });
        }
        return this.props.children;
    }
}

// ---------------------------------------------------------------- Quick Access injection
// Same entry point as Decky's own TabsHook (afterPatch on the QuickAccessMenu renderer + tree patcher),
// with these rules (learned from Decky, decky-bluetooth-order and Playhub):
// - Steam's tab objects are never modified: each render gets a derived copy of the tabs array, and every
//   element that consumes that array (tab header and content) is pointed at the copy.
// - Each QAM instance (Big Picture's and every in-game overlay's) passes its own `visible` prop down.
// - Fail open: an unknown layout or an exception leaves Steam's QAM untouched and is shown as status.
// - A render-burst guard switches the injection off instead of risking a render loop (Big Picture has no
//   error boundary above the QAM).
// - Unload restores the renderer and the already mounted fibers, and live wrappers fall back to Steam's
//   own panel without remounting it.
const QAM_SETTINGS_TAB = DFL.QuickAccessTab?.Settings ?? 4;
const QAM_PERF_TAB = DFL.QuickAccessTab?.Perf ?? 5;
const WRAP = Symbol.for("winqs.qam-wrapper"); // the same symbol in every reload of the plugin
let patches = [];        // { renderer, patch }
export let stopped = false;     // set on unload
let tripped = false;     // set by the render-burst guard

const wakeSubs = new Set();
function wakePanels() { wakeSubs.forEach((f) => f()); }

// diagnostics, read from the console as window.__WINQS.status
export const injectStatus = { settings: "waiting for Quick Access", perf: "waiting for Quick Access", error: null };
export function setStatus(key, value) { injectStatus[key] = value; }
// Peel off our own wrappers, including ones left by an older copy of the plugin in this Steam session.
function unwrapPanel(el) {
    for (let i = 0; i < 8 && el && el.type && el.props && "original" in el.props &&
        (el.type[WRAP] || /^Injected(Perf)?Panel$/.test(el.type.name || "")); i++) el = el.props.original;
    return el;
}

// Re-renders on unload / the render-burst guard; returns true while the injection is switched off.
function useInjectionOff(statusKey) {
    useSubscription(wakeSubs);
    const off = stopped || tripped;
    useEffect(() => { if (!off) setStatus(statusKey, "active"); }, [off]);
    return off;
}
// Steam re-renders the Quick Access menu often; our sections read the store themselves and only need `active`
const QuickSettingsMemo = R.memo(QuickSettings), PerfSectionMemo = R.memo(PerfSection),
    FrameSectionMemo = R.memo(FrameSection);
function InjectedPanel({ original, visible }) {
    const off = useInjectionOff("settings");
    // the same two child slots in every state, so Steam's own panel never remounts
    return jsxs(Fragment, {
        children: [
            off ? null : jsx(ErrorBoundary, { children: jsx(QuickSettingsMemo, { active: visible }) }),
            original,
        ],
    });
}
InjectedPanel[WRAP] = true;

function InjectedPerfPanel({ original, visible }) {
    const off = useInjectionOff("perf");
    const r = off ? null : patchSteamPerfPanel(original);
    useEffect(() => {
        if (r && !(r.fps && r.battery)) console.warn(LOG, "Steam's Performance panel only partly patched", { fps: r.fps, battery: r.battery });
    }, [r?.fps, r?.battery]);
    return jsx(PerfVisible.Provider, {
        value: !!visible,
        children: jsxs(Fragment, {
            children: [
                off ? original : r.tree,
                off ? null : jsx(ErrorBoundary, { children: jsx(PerfSectionMemo, { active: visible }) }),
                off ? null : jsx(ErrorBoundary, { children: jsx(FrameSectionMemo, { active: visible }) }),
            ],
        }),
    });
}
InjectedPerfPanel[WRAP] = true;

const derivedTabs = new WeakMap(); // Steam's tabs array -> { visible, items, tabs }
function deriveTabs(src, visible) {
    const hit = derivedTabs.get(src);
    // Decky pushes its own tab into the same array in place, so compare the items too, not only identity
    if (hit && hit.visible === visible && hit.items.length === src.length && hit.items.every((t, i) => t === src[i])) {
        return hit.tabs;
    }
    const pick = (key) => {
        const m = src.filter((t) => t && t.key === key && t.panel);
        return m.length === 1 ? m[0] : null;
    };
    const st = pick(QAM_SETTINGS_TAB);
    const pf = pick(QAM_PERF_TAB);
    if (!st) setStatus("settings", "unknown layout: Quick Settings tab not found");
    if (!pf) setStatus("perf", "unknown layout: Performance tab not found");
    const tabs = src.map((t) => {
        if (t === st) return { ...t, panel: jsx(InjectedPanel, { original: unwrapPanel(t.panel), visible }) };
        if (t === pf) return { ...t, panel: jsx(InjectedPerfPanel, { original: unwrapPanel(t.panel), visible }) };
        return t;
    });
    derivedTabs.set(src, { visible, items: src.slice(), tabs });
    return tabs;
}
function collectTabsConsumers(node, src, out, depth, seen) {
    if (!node || typeof node !== "object" || depth > 80 || seen.has(node)) return out;
    seen.add(node);
    if (Array.isArray(node)) {
        for (const n of node) collectTabsConsumers(n, src, out, depth + 1, seen);
        return out;
    }
    const props = node.props;
    if (props) {
        if (props.tabs === src) out.push(node);
        collectTabsConsumers(props.children, src, out, depth + 1, seen);
    }
    return out;
}

let burstStart = 0;
let burstCount = 0;
function onQamRender(args, ret) {
    if (stopped || tripped) return ret;
    const now = Date.now();
    if (now - burstStart > 1000) { burstStart = now; burstCount = 0; }
    if (++burstCount > 120) {
        tripped = true;
        setStatus("error", "render-loop guard tripped: injection switched off until the plugin reloads");
        queueMicrotask(wakePanels);
        return ret;
    }
    try {
        const props = (args && args[0]) || {};
        const visible = props.visible === undefined ? true : !!props.visible;
        const first = DFL.findInReactTree(ret, (x) => Array.isArray(x?.props?.tabs));
        if (!first) {
            setStatus("settings", "unknown layout: no tab list");
            return ret;
        }
        const src = first.props.tabs;
        const next = deriveTabs(src, visible);
        for (const el of collectTabsConsumers(ret, src, [], 0, new Set())) el.props.tabs = next;
    }
    catch (e) {
        setStatus("error", errText(e));
        console.error(LOG, "Quick Access patch failed; Steam's layout left as is", e);
    }
    return ret;
}

function walkFibers(fiber, visit) {
    const stack = fiber ? [fiber] : [];
    let n = 0;
    while (stack.length && n++ < 200000) {
        const f = stack.pop();
        visit(f);
        if (f.sibling) stack.push(f.sibling);
        if (f.child) stack.push(f.child);
    }
}
function retypeMountedQams() {
    // Memo fibers keep the type they resolved; point mounted QAMs at the renderer's current type.
    const root = DFL.getReactRoot(document.getElementById("root"));
    if (!root) return;
    walkFibers(root, (f) => {
        const p = patches.find((x) => x.renderer === f.elementType);
        if (!p) return;
        for (const x of [f, f.alternate]) if (x && x.type !== p.renderer.type) x.type = p.renderer.type;
    });
}

export function installPatch() {
    const isQam = (e) => {
        const src = e?.type?.toString?.() || "";
        return src.includes("QuickAccessMenuBrowserView") || src.includes("QuickAccessMenuEmbedded");
    };
    const mod = DFL.findModuleByExport((e) => e?.type?.toString?.()?.includes("QuickAccessMenuBrowserView"));
    if (!mod) throw new Error("Quick Access module not found");
    const renderers = Object.values(mod).filter(isQam);
    if (!renderers.length) throw new Error("Quick Access renderer not found");
    const handler = DFL.createReactTreePatcher(
        [(tree) => DFL.findInReactTree(tree, (n) => n?.props?.onFocusNavDeactivated)], onQamRender, "WinQS");
    patches = renderers.map((r) => ({ renderer: r, patch: DFL.afterPatch(r, "type", handler) }));
    retypeMountedQams();
}

export function uninstallPatch() {
    if (stopped) return;
    stopped = true;
    for (const { patch } of patches) {
        try { patch.unpatch(); } catch (e) { console.warn(LOG, "unpatch failed", e); }
    }
    try { retypeMountedQams(); } catch (e) { console.warn(LOG, "fiber restore failed", e); }
    patches = [];
    wakePanels(); // live wrappers render Steam's panel alone
}
