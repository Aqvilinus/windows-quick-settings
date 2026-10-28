import * as DFL from "@decky/ui";
import { useEffect, useRef, useState } from "react";
import { jsx, jsxs } from "react/jsx-runtime";
import { LOG, be, call, lazy } from "./backend.js";
import { L, S, T, errText, toast } from "./strings.js";
import { DIM, act, dialog, dimIf, emit, icon, modalParent, pending, pressable, refresh, showModalHere, signalIcon, spinner, store, useStableOrder, useStore, withPending } from "./ui.js";

// ---------------------------------------------------------------- Wi-Fi modal
// Steam's TextField leaves the input as type="text" whatever bIsPassword says, so the dots come from a CSS rule
// on a wrapper React does not touch (the same fix decky-control-center uses). The <style> sits inside the dialog,
// so it lands in whichever window the dialog opened in (Big Picture or the in-game overlay).
const PW_CSS = ".winqs-pw-hidden input { -webkit-text-security: disc; }";
const passwordOk = (p) => (p.length >= 8 && p.length <= 63) || /^[0-9a-fA-F]{64}$/.test(p);
function PasswordModal({ closeModal, ssid, onSubmit, error }) {
    const [pwd, setPwd] = useState("");
    const [show, setShow] = useState(false);
    const submit = () => { if (!passwordOk(pwd)) return; closeModal(); onSubmit(pwd); };
    return dialog(closeModal, ssid, [
        jsx("style", { children: PW_CSS }),
        error && jsx("div", { style: { color: "#ff6b6b", marginBottom: "0.6em" }, children: error }),
        jsx("div", {
            className: show ? undefined : "winqs-pw-hidden",
            children: jsx(DFL.TextField, {
                label: T.password, value: pwd, bIsPassword: !show, focusOnMount: true, description: T.passwordRule,
                onChange: (e) => setPwd(e.target.value),
                onKeyDown: (e) => { if (e.key === "Enter") submit(); },
            }),
        }),
        jsx(DFL.ToggleField, { label: T.showPassword, checked: show, onChange: setShow, bottomSeparator: "none" }),
    ], jsx(DFL.DialogButton, { disabled: !passwordOk(pwd), onClick: submit, children: S.connect() }));
}
export const MAX_INLINE_NETWORKS = 3;

function reasonText(r) {
    if (r.reason === "failed" && r.text) return r.text;
    return ({ wrong_password: T.wrongPassword, timeout: T.timeout, not_found: T.notFound,
        password_required: T.passwordRequired, unsupported_security: T.unsupported(r.security || "") })[r.reason] || r.reason;
}
async function connectNetwork(n, password) {
    const key = "wifi:" + n.ssid;
    if (pending(key) !== undefined) return null;
    return withPending(key, true, async () => {
        const r = await call(be.wifiConnect, n.ssid, password || null);
        if (!r.ok && !r.retry_password) toast(reasonText(r));
        return r;
    });
}

// ---------------------------------------------------------------- network sign-in pages (captive portals)
// Steam handles these itself, on Windows too. steamclient probes http://steamconnecttest.com/204 natively (so
// Chromium's automatic http->https upgrade never gets in the way), reports the result to the UI
// (EConnectivityTestResult, 2 = CaptivePortal) together with the portal's own address taken from the redirect
// (strCaptivePortalURL), and the Steam UI has its "Log in to the network" dialog with an embedded browser: the one
// SteamOS opens after joining such a network. We reuse both. Windows' NLM WEBHIJACK flag (state.internet ===
// "portal") is a second signal; Windows itself cannot tell apps the portal address.
const CONNECTIVITY_CAPTIVE_PORTAL = 2;
const STEAM_PORTAL_URL = "http://steamconnecttest.com/"; // what Steam's own "Force show captive portal browser" opens
let connectivityEvent = null; // the latest RegisterForConnectivityTestChanges payload
let connectivitySeq = 0;
let connectivityReg = null;
const steamNetStore = lazy(() => DFL.findModule((m) => m?.SystemNetworkStore)?.SystemNetworkStore);
// fn(ownerWindow, manualUrl?) that shows Steam's CaptivePortalDialog (found by its prop name, not a minified id)
const steamPortalDialog = lazy(() => DFL.findModuleExport((e) => {
    if (typeof e !== "function") return false;
    const src = Function.prototype.toString.call(e);
    return src.length < 400 && src.includes("strManualCaptivePortalURL");
}));
const connectivity = () => steamNetStore()?.connectivityTestState || connectivityEvent;
const portalNeeded = () => connectivity()?.eConnectivityTestResult === CONNECTIVITY_CAPTIVE_PORTAL
    || store.state?.internet === "portal";
export function startPortalWatch() {
    try {
        connectivityReg = SteamClient.System.Network.RegisterForConnectivityTestChanges((c) => {
            connectivityEvent = c;
            connectivitySeq++;
            emit();
        });
    }
    catch (e) { console.warn(LOG, "no connectivity events", e); }
}
export function stopPortalWatch() {
    try { connectivityReg?.unregister(); } catch { }
    connectivityReg = null;
}
function recheckConnectivity() {
    try { SteamClient.System.Network.ForceTestConnectivity(); return true; } catch { return false; }
}
function openSignInPage() {
    const owner = modalParent() || SteamUIStore.WindowStore.GamepadUIMainWindowInstance.BrowserWindow;
    const c = connectivity();
    // Steam's dialog loads the portal address Steam found itself; only without one do we pass Steam's probe page
    const manual = c?.strCaptivePortalURL ? undefined : STEAM_PORTAL_URL;
    try { DFL.Navigation.CloseSideMenus(); } catch { }
    const show = steamPortalDialog();
    if (show) {
        try { show(owner, manual); return; }
        catch (e) { console.warn(LOG, "Steam's sign-in dialog failed", e); }
    }
    // the portal address comes from the network itself: only a web page is opened, never another URL scheme
    const url = c?.strCaptivePortalURL;
    DFL.Navigation.NavigateToExternalWeb(/^https?:\/\//i.test(url || "") ? url : STEAM_PORTAL_URL);
}
// After joining a network: let Steam probe again and, like SteamOS, open the sign-in dialog if the network wants one.
async function signInIfNeeded() {
    const seq = connectivitySeq;
    if (!recheckConnectivity()) return;
    const until = Date.now() + 10000;
    while (Date.now() < until) {
        await DFL.sleep(400);
        const c = connectivity();
        if (connectivitySeq !== seq && c && !c.bChecking) {
            if (c.eConnectivityTestResult === CONNECTIVITY_CAPTIVE_PORTAL) openSignInPage();
            return;
        }
    }
}
function pickNetwork(n, after, closeParent) {
    const done = () => after?.();
    if (pending("wifi:" + n.ssid) !== undefined) return;
    const disconnect = () => act(async () => { await call(be.wifiDisconnect); }, done);
    if (n.connected && portalNeeded()) {
        showModalHere(jsx(DFL.ConfirmModal, {
            strTitle: L("Settings_Internet_Captive_Portal_Header_Title", n.ssid),
            strDescription: L("Settings_Internet_Captive_Portal_Detected", T.portal),
            strOKButtonText: L("Settings_Internet_Captive_Portal_Login_Button", "Log in"),
            onOK: () => { closeParent?.(); openSignInPage(); },
            strMiddleButtonText: S.disconnect(), onMiddleButton: disconnect,
        }));
    }
    else if (n.connected) {
        showModalHere(jsx(DFL.ConfirmModal, {
            strTitle: n.ssid, strDescription: T.disconnectQ, strOKButtonText: S.disconnect(), onOK: disconnect,
        }));
    }
    else if (n.known || !n.secured) {
        connectNetwork(n).then((r) => afterConnect(n, r, done));
    }
    else if (!n.can_add) {
        toast(T.unsupported(n.security));
    }
    else {
        askPassword(n, done);
    }
}
function askPassword(n, done, error) {
    showModalHere(jsx(PasswordModal, {
        ssid: n.ssid, error, onSubmit: (pwd) => connectNetwork(n, pwd).then((r) => afterConnect(n, r, done)),
    }));
}
// A password that Windows rejected (a new network, or a saved one whose password changed): ask again,
// with the reason, instead of dropping the user back to the list.
function afterConnect(n, r, done) {
    if (r && !r.ok && r.retry_password) askPassword(n, done, r.reason === "wrong_password" ? T.wrongPasswordShort : reasonText(r));
    if (r && r.ok) signInIfNeeded();
    done();
}
function forgetNetwork(n, after) {
    showModalHere(jsx(DFL.ConfirmModal, {
        strTitle: n.ssid, strDescription: T.forgetQ, strOKButtonText: T.forget,
        onOK: () => act(async () => {
            const r = await call(be.wifiForget, n.ssid);
            return r.ok ? T.forgotten : ({ group_policy: T.groupPolicy, not_saved: T.notSaved })[r.reason] || r.reason;
        }, after),
    }));
}
// The caption under a network. In the All networks dialog (full): state and security for every row. Inline in the
// QAM: only what needs attention (no internet / sign-in page, or a network the plugin can't join).
function internetText() {
    if (portalNeeded()) return L("Settings_Internet_Captive_Portal_Detected", T.portal);
    const i = store.state?.internet;
    return i === "online" ? T.online : i === "no_internet" ? T.noInternet : null;
}
function netCaption(n, full) {
    if (n.connected) {
        const net = internetText();
        if (full) return [S.connected(), net].filter(Boolean).join(" · ");
        return net && net !== T.online ? net : null;
    }
    if (n.secured && !n.known && !n.can_add) return T.viaWindows(n.security);
    if (!full) return null;
    return [n.known ? T.saved : null, n.secured ? T.secured + (n.security ? " · " + n.security : "") : T.open]
        .filter(Boolean).join(" · ");
}
export function NetworkRow({ n, indent, after, separator, full, closeParent }) {
    const working = pending("wifi:" + n.ssid) !== undefined;
    const unusable = n.secured && !n.known && !n.can_add && !n.connected;
    return jsx(DFL.Field, {
        label: dimIf(n.connected || unusable, n.ssid), description: netCaption(n, full),
        indentLevel: indent ? 1 : 0, bottomSeparator: separator || (indent ? "none" : "standard"),
        ...pressable(() => pickNetwork(n, after, closeParent)),
        onOptionsButton: n.known ? () => forgetNetwork(n, after) : undefined,
        onOptionsActionDescription: n.known ? T.forget : undefined,
        children: working ? spinner()
            : jsxs("div", {
                style: { display: "flex", alignItems: "center", gap: "0.6em", ...(n.connected ? DIM : {}) },
                children: [n.secured && icon("Lock", { locked: true, style: { opacity: 0.7 } }), signalIcon(n.signal)],
            }),
    });
}

function WifiModal({ closeModal }) {
    useStore();
    const [nets, setNets] = useState(null);
    const [scanning, setScanning] = useState(false);
    const alive = useRef(true);
    const stable = useStableOrder((n) => n.ssid);
    useEffect(() => () => { alive.current = false; }, []);
    const loading = useRef(false);
    const load = async (rescan, quiet) => {
        if (loading.current && quiet) return;
        loading.current = true;
        if (!quiet) setScanning(true);
        try {
            refresh(); // connected / internet status shown in the rows comes from the shared state
            const list = await call(be.wifiNetworks, rescan);
            if (alive.current) setNets(stable(list));
        }
        catch (e) { if (!quiet) toast(errText(e)); }
        finally {
            loading.current = false;
            if (alive.current && !quiet) setScanning(false);
        }
    };
    useEffect(() => {
        load(false).then(() => load(true));
        recheckConnectivity();
        // like the Deck's list: keeps itself current. A scan disturbs a connected link (lag in games), so while
        // connected it only re-reads the list Windows keeps current with its own scans; Rescan still scans.
        const connected = () => (store.state?.wifi_networks || []).some((n) => n.connected);
        const t = setInterval(() => load(!connected(), true), 10000);
        return () => clearInterval(t);
    }, []);
    return dialog(closeModal, S.networksFound(), [
        jsx(DFL.Focusable, {
            style: { display: "flex", flexDirection: "column" },
            children: (nets || []).map((n) => jsx(NetworkRow, { n, full: true, after: () => load(false), closeParent: closeModal }, n.ssid)),
        }),
        (scanning || !nets) && jsx(DFL.Field, { label: T.scanning, children: spinner() }),
    ], jsx(DFL.DialogButton, { onClick: () => load(true), disabled: scanning, children: T.rescan }));
}
export function openWifiModal() { showModalHere(jsx(WifiModal, {})); }
