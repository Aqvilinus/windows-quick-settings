import * as DFL from "@decky/ui";
import { useEffect, useRef, useState } from "react";
import { jsx, jsxs } from "react/jsx-runtime";
import { be, call, lazy } from "./backend.js";
import { T, errText, toast } from "./strings.js";

// ---------------------------------------------------------------- icons
// Steam's own icon components (the module that also exports `Information`), the ones its Quick Access Menu draws.
// They have a viewBox but no size, so each sits in a 1em box like text. A missing icon renders nothing.
export const steamIcons = lazy(() => DFL.findModule((m) => m && typeof m === "object" && typeof m.Information === "function"
    && Object.keys(m).length > 100), "Steam's icons not found");
function SteamIcon({ name, style, ...props }) {
    const C = steamIcons()?.[name];
    return C ? jsx("span", { style: { display: "block", width: "1em", height: "1em", ...style }, children: jsx(C, props) }) : null;
}
export const icon = (name, props) => jsx(SteamIcon, { name, ...props });
const DEVICE_ICONS = { audio: "Headphones", peripheral: "Keyboard", phone: "Mobile" };
export const deviceIcon = (type) => icon(DEVICE_ICONS[type] || "Bluetooth");
// Steam's strength 1..4 = lit bars
export const signalIcon = (signal) => icon("WirelessNetwork", { strength: signal >= 75 ? 4 : signal >= 50 ? 3 : signal >= 25 ? 2 : 1 });
export const chevron = () => icon("Chevron", { direction: "right", style: { opacity: 0.7 } });

// ---------------------------------------------------------------- shared store
export const store = { state: null, error: null, pending: {}, listeners: new Set() };
export function emit() { store.listeners.forEach((f) => f()); }
// Re-renders the component whenever one of `subs` is called.
export function useSubscription(subs) {
    const [, force] = useState(0);
    useEffect(() => {
        const f = () => force((x) => x + 1);
        subs.add(f);
        return () => { subs.delete(f); };
    }, []);
}
export const useStore = () => useSubscription(store.listeners);
let inflight = null;
let lastStateJson = "";
export function refresh() {
    if (inflight) return inflight;
    inflight = (async () => {
        let changed = false;
        try {
            const next = await call(be.getState);
            const json = JSON.stringify(next);
            if (json !== lastStateJson || store.error !== null) {
                lastStateJson = json;
                store.state = next;
                store.error = null;
                changed = true;
            }
        }
        catch (e) {
            const msg = errText(e);
            changed = msg !== store.error;
            store.error = msg;
        }
        finally {
            inflight = null;
            if (changed) emit(); // a poll that brings nothing new does not re-render the panel
        }
    })();
    return inflight;
}
let activeCount = 0;
let pollTimer = null;
export function useAutoRefresh(active) {
    useEffect(() => {
        if (!active) return undefined;
        activeCount++;
        refresh();
        if (!pollTimer) pollTimer = setInterval(refresh, 4000);
        return () => {
            activeCount--;
            if (activeCount === 0) {
                clearInterval(pollTimer);
                pollTimer = null;
            }
        };
    }, [active]);
}
// Marks `key` as pending (the UI shows the wanted value, or a spinner) while fn runs, then reloads the state.
// Returns fn's result, or null after an error (shown as a toast).
export async function withPending(key, value, fn) {
    store.pending[key] = value;
    emit();
    try { return await fn(); }
    catch (e) { toast(errText(e)); return null; }
    finally {
        delete store.pending[key];
        await refresh();
        emit(); // pending flag cleared even if the state itself did not change
    }
}
// set_wifi / set_bluetooth return Windows' radio access status
export const checkAccess = (status) => { if (status !== "allowed") toast(T.accessDenied + " (" + status + ")"); };
export const pending = (k) => store.pending[k];
// A backend action from a dialog: toasts the message it returns (or the error), reloads the state, then `after`.
export async function act(fn, after) {
    try {
        const msg = await fn();
        if (msg) toast(msg);
    }
    catch (e) { toast(errText(e)); }
    await refresh();
    after?.();
}

// ---------------------------------------------------------------- UI pieces
export const Row = (child, key) => jsx(DFL.PanelSectionRow, { children: child }, key);
export const spinner = () => jsx(DFL.Spinner, { style: { height: "1.2em" } });
// props of a row the gamepad and the mouse can press
export const pressable = (f) => ({ focusable: true, highlightOnFocus: true, onActivate: f, onClick: f });
export const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
// The dialog layout every dialog of the plugin uses
export const dialog = (closeModal, title, body, footer) => jsxs(DFL.ModalRoot, {
    closeModal, onCancel: closeModal,
    children: [
        jsx(DFL.DialogHeader, { children: title }),
        jsxs(DFL.DialogBody, { children: body }),
        jsx(DFL.DialogFooter, { children: footer }),
    ],
});
// Keeps rows where they are while a dialog is open (no jumping under the cursor); new rows go last.
export function useStableOrder(keyOf) {
    const order = useRef([]);
    return (list) => {
        const pos = new Map(order.current.map((k, i) => [k, i]));
        const out = list.filter((x) => pos.has(keyOf(x))).sort((a, b) => pos.get(keyOf(a)) - pos.get(keyOf(b)))
            .concat(list.filter((x) => !pos.has(keyOf(x))));
        order.current = out.map(keyOf);
        return out;
    };
}

// Slider that sends values to the backend without flooding it ("latest value wins"),
// and ignores polled values for a moment after the user touched it.
const lastTouch = {};
export function ValueSlider({ id, value, icon, send }) {
    const [local, setLocal] = useState(value);
    const sending = useRef(false);
    const wanted = useRef(null);
    useEffect(() => {
        if (Date.now() - (lastTouch[id] || 0) > 1500) setLocal(value);
    }, [value]);
    const pump = async () => {
        if (sending.current) return;
        sending.current = true;
        try {
            while (wanted.current !== null) {
                const v = wanted.current;
                wanted.current = null;
                try { await send(v); }
                catch (e) { toast(errText(e)); }
            }
        }
        finally { sending.current = false; }
    };
    return jsx(DFL.SliderField, {
        value: local, min: 0, max: 100, step: 1, showValue: false, icon: typeof icon === "function" ? icon(local) : icon,
        onChange: (v) => {
            setLocal(v);
            lastTouch[id] = Date.now();
            wanted.current = v;
            pump();
        },
    });
}

// Connected items are dimmed, available ones are white (Steam Deck style).
export const DIM = { color: "#8b929a" };
export const dimIf = (cond, text) => (cond ? jsx("span", { style: DIM, children: text }) : text);
export const sep = (isLast) => (isLast ? "standard" : "none");
// Dialogs open in the window that has the gamepad. DFL.showModal defaults to the main Big Picture window,
// which sits behind the game while the Quick Access Menu is open in the in-game overlay: the dialog would be
// invisible there and the gamepad would stay in the overlay.
export function modalParent() {
    try {
        const nav = DFL.getFocusNavController();
        const w = (nav?.GetActiveContext?.() || nav?.FindAnActiveContext?.())?.m_rootWindow;
        if (w && !w.closed) return w;
    }
    catch { }
    return undefined; // DFL falls back to the main window
}
export function showModalHere(el) { return DFL.showModal(el, modalParent()); }
