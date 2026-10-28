// Windows Quick Settings — Decky Loader frontend (hand-written, no build step).
// Injects Wi-Fi / Bluetooth / airplane mode / brightness controls into the
// Quick Settings tab (gear icon) of the Steam Big Picture Quick Access Menu.

const manifest = { name: "Windows Quick Settings" };
const API_VERSION = 2;
const internalAPIConnection = window.__DECKY_SECRET_INTERNALS_DO_NOT_USE_OR_YOU_WILL_BE_FIRED_deckyLoaderAPIInit;
if (!internalAPIConnection) {
    throw new Error("[WinQS] Decky loader API is not initialized");
}
let api;
try {
    api = internalAPIConnection.connect(API_VERSION, manifest.name);
}
catch {
    api = internalAPIConnection.connect(1, manifest.name);
}
const callable = api.callable;
const toaster = api.toaster;
const definePlugin = (fn) => (...args) => fn(...args);

const { jsx, jsxs, Fragment } = SP_JSX;
const R = SP_REACT;
const { useState, useEffect, useRef } = R;
const LOG = "[WinQS]";

// ---------------------------------------------------------------- backend
const be = {
    getState: callable("get_state"),
    setWifi: callable("set_wifi"),
    setBluetooth: callable("set_bluetooth"),
    setAirplane: callable("set_airplane"),
    setBrightness: callable("set_brightness"),
    setVolume: callable("set_volume"),
    setAudioDevice: callable("set_audio_device"),
    setNight: callable("set_night"),
    wifiNetworks: callable("wifi_networks"),
    wifiConnect: callable("wifi_connect"),
    wifiDisconnect: callable("wifi_disconnect"),
    wifiForget: callable("wifi_forget"),
    btScan: callable("bt_scan"),
    btScanResults: callable("bt_scan_results"),
    btPair: callable("bt_pair"),
    btPairAnswer: callable("bt_pair_answer"),
    btPairCancel: callable("bt_pair_cancel"),
    btForget: callable("bt_forget"),
    bluetoothAudio: callable("bluetooth_audio"),
    openSettings: callable("open_settings"),
    perfState: callable("perf_state"),
    setFrameLimit: callable("set_frame_limit"),
    setActiveGame: callable("set_active_game"),
    setGameProfile: callable("set_game_profile"),
    batteryState: callable("battery_state"),
    setGameOverlays: callable("set_game_overlays"),
    setupRtss: callable("setup_rtss"),
    setHdr: callable("set_hdr"),
};
async function call(fn, ...args) {
    const r = await fn(...args);
    if (!r?.ok) throw new Error(r?.error || "backend error");
    return r.result;
}
// The first call runs fn; its result (null on a miss or an error) is kept for the plugin's lifetime.
function lazy(fn, warning) {
    let value;
    return () => {
        if (value === undefined) {
            value = null;
            try { value = fn() ?? null; }
            catch (e) { if (warning) console.warn(LOG, warning, e); }
        }
        return value;
    };
}

// ---------------------------------------------------------------- strings
// Steam's own localization first (same labels as on Steam Deck), own fallback second.
function L(token, fallback) {
    try {
        const s = window.LocalizationManager?.LocalizeString?.("#" + token);
        if (s && !s.startsWith("#")) return s;
    }
    catch { /* ignore */ }
    return fallback;
}
const IS_RU = (() => {
    try {
        const l = String(window.LocalizationManager?.m_rgLocalesToUse?.[0] || document.documentElement.lang || navigator.language || "");
        return /^ru|russian/i.test(l);
    }
    catch { return false; }
})();
const T = IS_RU ? {
    loading: "Загрузка…", saved: "Сохранена", open: "Открытая", scanning: "Поиск сетей…", rescan: "Обновить",
    password: "Пароль",
    wrongPassword: "Не удалось подключиться: проверьте пароль", timeout: "Не удалось подключиться (таймаут)",
    locationOff: "Сети Wi-Fi скрыты", locationHint: "Windows не показывает сети приложениям, пока выключена геолокация. Нажмите, чтобы открыть настройки",
    radioDisabled: "Отключено в Windows (диспетчер устройств)", forget: "Забыть сеть", forgetQ: "Удалить сохранённую сеть и её пароль?",
    forgotten: "Сеть удалена", notSaved: "Эта сеть не сохранена", groupPolicy: "Сеть задана политикой, её нельзя удалить",
    passwordRule: "8–63 символа или 64 шестнадцатеричные цифры",
    notFound: "Сеть больше не видна", unsupported: (s) => `Тип защиты ${s} не поддерживается, подключитесь через настройки Windows`,
    passwordRequired: "Нужен пароль", disconnectQ: "Отключиться от этой сети?",
    btNoControl: "Это устройство подключается само, отдельной кнопки подключения у Windows для него нет",
    btPairing: "Сопряжение…", btNoneFound: "Устройства не найдены. Включите на устройстве режим сопряжения",
    btPinMatch: (name, pin) => `Убедитесь, что на устройстве «${name}» показан код ${pin}`,
    btTypePin: (pin) => `Введите на устройстве код ${pin} и нажмите Enter`,
    btForgetQ: "Удалить это устройство? Чтобы снова пользоваться им, понадобится повторное сопряжение",
    btForgotten: "Устройство удалено",
    accessDenied: "Windows не разрешила переключить радиомодуль", allNetworks: "Все сети",
    showPassword: "Показать пароль", wrongPasswordShort: "Неверный пароль, попробуйте ещё раз", secured: "Защищена",
    online: "Есть интернет", noInternet: "Без интернета", portal: "Сеть требует дополнительных данных для входа",
    viaWindows: (s) => `${s}: подключайтесь через настройки Windows`,
    rtssSetup: "Лимит FPS во всех играх",
    rtssSetupHint: "Сейчас работает лимит драйвера Intel, в DX12-играх он не действует. Нажмите, чтобы один раз настроить RTSS: Windows попросит разрешение администратора",
    rtssMissing: "Лимит драйвера Intel не действует в DX12-играх. Чтобы ограничивать все игры, установите RTSS",
    rtssConfirm: "Подтвердите запрос Windows", rtssWorking: "Настраивается…",
    overlayPosition: "Положение",
} : {
    loading: "Loading…", saved: "Saved", open: "Open", scanning: "Searching for networks…", rescan: "Refresh",
    password: "Password",
    wrongPassword: "Could not connect: check the password", timeout: "Could not connect (timed out)",
    locationOff: "Wi-Fi networks hidden", locationHint: "Windows hides networks from apps while Location is off. Press to open the setting",
    radioDisabled: "Disabled in Windows (Device Manager)", forget: "Forget network", forgetQ: "Remove this saved network and its password?",
    forgotten: "Network removed", notSaved: "This network is not saved", groupPolicy: "Set by policy, can't be removed",
    passwordRule: "8-63 characters or 64 hex digits",
    notFound: "The network is no longer visible", unsupported: (s) => `${s} security is not supported, connect in Windows settings`,
    passwordRequired: "Password required", disconnectQ: "Disconnect from this network?",
    btNoControl: "This device connects by itself; Windows has no connect button for it",
    btPairing: "Pairing…", btNoneFound: "No devices found. Put the device in pairing mode",
    btPinMatch: (name, pin) => `Make sure ${name} shows the code ${pin}`,
    btTypePin: (pin) => `Type ${pin} on the device, then press Enter`,
    btForgetQ: "Remove this device? You will need to pair it again to use it",
    btForgotten: "Device removed",
    accessDenied: "Windows did not allow switching the radio", allNetworks: "All networks",
    showPassword: "Show password", wrongPasswordShort: "Wrong password, try again", secured: "Secured",
    online: "Internet", noInternet: "No internet", portal: "The network requires additional login information.",
    viaWindows: (s) => `${s}: connect in Windows settings`,
    rtssSetup: "Frame limit in all games",
    rtssSetupHint: "The Intel driver limit is in use and does not apply to DX12 games. Press to set up RTSS once: Windows will ask for administrator permission",
    rtssMissing: "The Intel driver limit does not apply to DX12 games. Install RTSS to limit every game",
    rtssConfirm: "Confirm the Windows prompt", rtssWorking: "Setting up…",
    overlayPosition: "Position",
};
const S = {
    airplane: () => L("QuickAccess_Tab_Settings_Section_Shortcuts_AirplaneMode", "Airplane mode"),
    wifi: () => L("QuickAccess_Tab_Settings_Section_Shortcuts_Wifi", "Wi-Fi"),
    bluetooth: () => L("QuickAccess_Tab_Bluetooth_ToggleLabel", "Bluetooth"),
    brightness: () => L("QuickAccess_Tab_Settings_Section_Brightness_Title", "Brightness"),
    audio: () => L("QuickAccess_Tab_Settings_Section_Audio_Title", "Audio"),
    other: () => L("QuickAccess_Tab_Settings_Section_Other_Title", "Other"),
    nightMode: () => L("QuickAccess_Tab_Settings_Section_Shortcuts_NightMode", "Night mode"),
    networksFound: () => L("Settings_Internet_Networks_Found", "Networks Found"),
    connect: () => L("Settings_Internet_Connect", "Connect"),
    disconnect: () => L("Settings_Internet_Disconnect", "Disconnect"),
    connected: () => L("Settings_Bluetooth_Connected", "Connected"),
    btAdd: () => L("QuickAccess_Tab_Bluetooth_AddDevice", "Add Device"),
    btAvailable: () => L("QuickAccess_Tab_Bluetooth_Available_To_Pair", "Available to pair"),
    btSearching: () => L("QuickAccess_Tab_Bluetooth_Searching", "Searching for devices..."),
    btPair: () => L("QuickAccess_Tab_Bluetooth_Pair", "Pair"),
    btPaired: () => L("QuickAccess_Tab_Bluetooth_Paired", "Paired"),
    btCancelPair: () => L("QuickAccess_Tab_Bluetooth_CancelPair", "Cancel Pairing"),
    btForget: () => L("QuickAccess_Tab_Bluetooth_Forget", "Forget"),
    btForgetDevice: () => L("QuickAccess_Tab_Bluetooth_Unpair", "Forget Device"),
    pairFailed: () => L("RemotePlay_PairWifiAPResult_Fail", "Pairing Failed"),
};
function toast(body) {
    try { toaster.toast({ title: manifest.name, body: String(body) }); }
    catch (e) { console.warn(LOG, body, e); }
}
const errText = (e) => String((e && e.message) || e);

// ---------------------------------------------------------------- icons
// Steam's own icon components (the module that also exports `Information`), the ones its Quick Access Menu draws.
// They have a viewBox but no size, so each sits in a 1em box like text. A missing icon renders nothing.
const steamIcons = lazy(() => DFL.findModule((m) => m && typeof m === "object" && typeof m.Information === "function"
    && Object.keys(m).length > 100), "Steam's icons not found");
function SteamIcon({ name, style, ...props }) {
    const C = steamIcons()?.[name];
    return C ? jsx("span", { style: { display: "block", width: "1em", height: "1em", ...style }, children: jsx(C, props) }) : null;
}
const icon = (name, props) => jsx(SteamIcon, { name, ...props });
const DEVICE_ICONS = { audio: "Headphones", peripheral: "Keyboard", phone: "Mobile" };
const deviceIcon = (type) => icon(DEVICE_ICONS[type] || "Bluetooth");
// Steam's strength 1..4 = lit bars
const signalIcon = (signal) => icon("WirelessNetwork", { strength: signal >= 75 ? 4 : signal >= 50 ? 3 : signal >= 25 ? 2 : 1 });
const chevron = () => icon("Chevron", { direction: "right", style: { opacity: 0.7 } });

// ---------------------------------------------------------------- shared store
const store = { state: null, error: null, pending: {}, listeners: new Set() };
function emit() { store.listeners.forEach((f) => f()); }
// Re-renders the component whenever one of `subs` is called.
function useSubscription(subs) {
    const [, force] = useState(0);
    useEffect(() => {
        const f = () => force((x) => x + 1);
        subs.add(f);
        return () => { subs.delete(f); };
    }, []);
}
const useStore = () => useSubscription(store.listeners);
let inflight = null;
let lastStateJson = "";
function refresh() {
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
function useAutoRefresh(active) {
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
async function withPending(key, value, fn) {
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
// A radio switch returns Windows' access status
const runAction = (key, value, fn) => withPending(key, value, async () => {
    const res = await fn();
    if (typeof res === "string" && res !== "allowed") toast(T.accessDenied + " (" + res + ")");
});
const pending = (k) => store.pending[k];
// A backend action from a dialog: toasts the message it returns (or the error), reloads the state, then `after`.
async function act(fn, after) {
    try {
        const msg = await fn();
        if (msg) toast(msg);
    }
    catch (e) { toast(errText(e)); }
    await refresh();
    after?.();
}

// ---------------------------------------------------------------- UI pieces
const Row = (child, key) => jsx(DFL.PanelSectionRow, { children: child }, key);
const spinner = () => jsx(DFL.Spinner, { style: { height: "1.2em" } });
// props of a row the gamepad and the mouse can press
const pressable = (f) => ({ focusable: true, highlightOnFocus: true, onActivate: f, onClick: f });
const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
// The dialog layout every dialog of the plugin uses
const dialog = (closeModal, title, body, footer) => jsxs(DFL.ModalRoot, {
    closeModal, onCancel: closeModal,
    children: [
        jsx(DFL.DialogHeader, { children: title }),
        jsxs(DFL.DialogBody, { children: body }),
        jsx(DFL.DialogFooter, { children: footer }),
    ],
});
// Keeps rows where they are while a dialog is open (no jumping under the cursor); new rows go last.
function useStableOrder(keyOf) {
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
function ValueSlider({ id, value, icon, send }) {
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

function QuickSettings({ active }) {
    useStore();
    useAutoRefresh(active);
    const s = store.state;
    if (!s) {
        return jsx(DFL.PanelSection, {
            children: Row(store.error
                ? jsx(DFL.Field, { label: manifest.name, description: store.error })
                : jsx(DFL.Field, { label: T.loading, children: spinner() })),
        });
    }
    const radios = s.radios || {};
    const wifiPresent = radios.wifi != null;
    const btPresent = radios.bluetooth != null;
    const pw = pending("wifi"), pb = pending("bluetooth"), pa = pending("airplane");
    const wifiOn = pw ?? radios.wifi === "on";
    const btOn = pb ?? radios.bluetooth === "on";
    const airplaneOn = pa ?? !!s.airplane;
    const busy = pw !== undefined || pb !== undefined || pa !== undefined;
    const wifiList = wifiPresent && wifiOn; // the network rows under the Wi-Fi switch

    const nets = s.wifi_networks || [];
    const shownNets = nets.slice(0, MAX_INLINE_NETWORKS);
    // the "All networks" row is always there: while connected, Windows lists only what it last saw, and the
    // full list (which starts a scan) is the way to look for other networks
    const moreNets = !s.wifi_location_off;
    const btDevices = s.bt_devices || [];
    // the void wrappers keep runAction from reading the result as a radio access status
    const toggle = (key, label, iconName, checked, send) => Row(jsx(DFL.ToggleField, {
        label, icon: icon(iconName), checked: pending(key) ?? checked, disabled: pending(key) !== undefined,
        onChange: (v) => runAction(key, v, async () => { await send(v); }),
    }), key);

    return jsxs(Fragment, {
        children: [
            s.brightness != null && jsx(DFL.PanelSection, {
                title: S.brightness(),
                children: Row(jsx(ValueSlider, { id: "brightness", value: s.brightness, icon: icon("Brightness"),
                    send: (v) => call(be.setBrightness, v) })),
            }),
            (s.audio?.output || s.audio?.input) && jsxs(DFL.PanelSection, {
                title: S.audio(),
                children: [
                    s.audio.output && Row(jsx(ValueSlider, {
                        id: "out", value: s.audio.output.muted ? 0 : s.audio.output.volume,
                        icon: (v) => icon("AudioVolumeIcon", { flVolume: v / 100 }),
                        send: (v) => call(be.setVolume, "output", v),
                    }), "out"),
                    jsx(AudioDevicePicker, { flow: "output", list: s.audio_devices?.output }, "out-dev"),
                    s.audio.input && Row(jsx(ValueSlider, {
                        id: "in", value: s.audio.input.muted ? 0 : s.audio.input.volume, icon: icon("Microphone"),
                        send: (v) => call(be.setVolume, "input", v),
                    }), "in"),
                    jsx(AudioDevicePicker, { flow: "input", list: s.audio_devices?.input }, "in-dev"),
                ],
            }),
            jsxs(DFL.PanelSection, {
                title: S.other(),
                children: [
                    (wifiPresent || btPresent) && Row(jsx(DFL.ToggleField, {
                        label: S.airplane(), icon: icon("AirplaneMode"), checked: airplaneOn, disabled: busy,
                        onChange: (v) => runAction("airplane", v, async () => { await call(be.setAirplane, v); }),
                    }), "airplane"),
                    wifiPresent && Row(jsx(DFL.ToggleField, {
                        label: S.wifi(), icon: icon("WiFi"), checked: wifiOn, bottomSeparator: sep(!wifiOn),
                        disabled: busy || radios.wifi === "disabled",
                        description: radios.wifi === "disabled" ? T.radioDisabled : null,
                        onChange: (v) => runAction("wifi", v, () => call(be.setWifi, v)),
                    }), "wifi"),
                    wifiList && s.wifi_location_off && Row(jsx(DFL.Field, {
                        label: T.locationOff, description: T.locationHint, indentLevel: 1, bottomSeparator: "standard",
                        ...pressable(() => openSettingsPage("location")),
                    }), "net-location"),
                    ...(wifiList ? shownNets.map((n, i) => Row(jsx(NetworkRow, { n, indent: true, separator: sep(!moreNets && i === shownNets.length - 1) }), "net-" + n.ssid)) : []),
                    wifiList && nets.length === 0 && !s.wifi_location_off && Row(jsx(DFL.Field, {
                        label: s.errors?.wifi || T.scanning, indentLevel: 1, bottomSeparator: "standard",
                        children: s.errors?.wifi ? null : spinner(),
                    }), "net-scan"),
                    wifiList && moreNets && Row(jsx(DFL.Field, {
                        label: T.allNetworks, indentLevel: 1, bottomSeparator: "standard", ...pressable(openWifiModal), children: chevron(),
                    }), "net-all"),
                    btPresent && Row(jsx(DFL.ToggleField, {
                        label: S.bluetooth(), icon: icon("Bluetooth"), checked: btOn, bottomSeparator: sep(!btOn),
                        disabled: busy || radios.bluetooth === "disabled",
                        description: radios.bluetooth === "disabled" ? T.radioDisabled : s.errors?.bluetooth || null,
                        onChange: (v) => runAction("bluetooth", v, () => call(be.setBluetooth, v)),
                    }), "bt"),
                    ...(btPresent && btOn ? btDevices.map((d) => Row(jsx(BtDeviceRow, { device: d }), "bt-" + d.address)) : []),
                    btPresent && btOn && Row(jsx(DFL.Field, {
                        label: S.btAdd(), icon: icon("Add"), indentLevel: 1, bottomSeparator: "standard", ...pressable(addBtDevice),
                    }), "bt-add"),
                    toggle("night", S.nightMode(), "NightMode", !!s.night, (v) => call(be.setNight, v)),
                    s.hdr && toggle("hdr", "HDR", "HDR", !!s.hdr.on, (v) => call(be.setHdr, v)),
                ],
            }),
        ],
    });
}

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

// Output / input device dropdown under the volume sliders (like Steam Deck's Audio section). Shown only when
// there is more than one active device to choose from.
function AudioDevicePicker({ flow, list }) {
    if (!list || list.length < 2) return null;
    const key = "audiodev:" + flow;
    const current = pending(key) ?? (list.find((d) => d.default) || list[0]).id;
    return Row(jsx(DFL.DropdownItem, {
        label: flow === "output" ? L("Audio_OutputDevice", IS_RU ? "Устройство вывода" : "Output Device")
            : L("Audio_InputDevice", IS_RU ? "Устройство ввода" : "Input Device"),
        rgOptions: list.map((d) => ({ data: d.id, label: d.name })),
        selectedOption: current,
        bottomSeparator: "none",
        onChange: (o) => { if (o && o.data !== current) runAction(key, o.data, () => call(be.setAudioDevice, flow, o.data)); },
    }));
}

// Connected items are dimmed, available ones are white (Steam Deck style).
const DIM = { color: "#8b929a" };
const dimIf = (cond, text) => (cond ? jsx("span", { style: DIM, children: text }) : text);
const MAX_INLINE_NETWORKS = 3;
const sep = (isLast) => (isLast ? "standard" : "none");

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
// Dialogs open in the window that has the gamepad. DFL.showModal defaults to the main Big Picture window,
// which sits behind the game while the Quick Access Menu is open in the in-game overlay: the dialog would be
// invisible there and the gamepad would stay in the overlay.
function modalParent() {
    try {
        const nav = window.FocusNavController;
        const w = (nav?.GetActiveContext?.() || nav?.FindAnActiveContext?.())?.m_rootWindow;
        if (w && !w.closed) return w;
    }
    catch { }
    return undefined; // DFL falls back to the main window
}
function showModalHere(el) { return DFL.showModal(el, modalParent()); }

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
function startPortalWatch() {
    try {
        connectivityReg = SteamClient.System.Network.RegisterForConnectivityTestChanges((c) => {
            connectivityEvent = c;
            connectivitySeq++;
            emit();
        });
    }
    catch (e) { console.warn(LOG, "no connectivity events", e); }
}
function stopPortalWatch() {
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
    DFL.Navigation.NavigateToExternalWeb(c?.strCaptivePortalURL || STEAM_PORTAL_URL);
}
// After joining a network: let Steam probe again and, like SteamOS, open the sign-in dialog if the network wants one.
async function signInIfNeeded() {
    const seq = connectivitySeq;
    if (!recheckConnectivity()) return;
    const until = Date.now() + 10000;
    while (Date.now() < until) {
        await new Promise((r) => setTimeout(r, 400));
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
function NetworkRow({ n, indent, after, separator, full, closeParent }) {
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
        const t = setInterval(() => load(true, true), 10000); // like the Deck's list: keeps itself current
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
function openWifiModal() { showModalHere(jsx(WifiModal, {})); }

// ---------------------------------------------------------------- Bluetooth device rows
function BtDeviceRow({ device: d }) {
    const key = "bt:" + d.address;
    const working = pending(key) !== undefined;
    const isConnected = d.connected || d.audio_connected;
    const activate = () => {
        if (working) return;
        if (!d.audio_control) { toast(T.btNoControl); return; }
        const connect = !isConnected;
        runAction(key, connect, async () => {
            await call(be.bluetoothAudio, d.name, connect);
            await new Promise((r) => setTimeout(r, 2500));
        });
    };
    return jsx(DFL.Field, {
        label: dimIf(isConnected, d.name),
        icon: jsx("span", { style: isConnected ? DIM : undefined, children: deviceIcon(d.type) }),
        indentLevel: 1, bottomSeparator: "none", ...pressable(activate),
        onOptionsButton: () => forgetBtDevice(d), onOptionsActionDescription: S.btForget(),
        children: working ? spinner() : null,
    });
}
function forgetBtDevice(d) {
    showModalHere(jsx(DFL.ConfirmModal, {
        strTitle: d.name, strDescription: T.btForgetQ, strOKButtonText: S.btForgetDevice(),
        onOK: () => act(async () => { await call(be.btForget, d.id); return T.btForgotten; }),
    }));
}
async function openSettingsPage(page) {
    try {
        DFL.Navigation.CloseSideMenus();
        await call(be.openSettings, page);
    }
    catch (e) { toast(errText(e)); }
}
// ---------------------------------------------------------------- Bluetooth pairing ("Add Device")
// Search and pairing run in the backend (WinRT, bt.py); the dialog polls their state. Steam's own strings where
// Steam has them (Available to pair, Searching for devices..., Pair, Cancel Pairing, Paired).
const PAIR_ACTIVE = new Set(["pairing", "confirm", "display_pin"]);
function BtPairModal({ closeModal }) {
    const [res, setRes] = useState(null); // { scanning, devices, pairing }
    const alive = useRef(true);
    const handled = useRef(null); // the pairing step already shown (prompt, toast)
    const stable = useStableOrder((d) => d.id);
    const lastPairing = useRef(null);
    const prompt = useRef(null);  // the code dialog of the current step; the next step closes it
    const closePrompt = () => {
        try { prompt.current?.Close(); } catch { }
        prompt.current = null;
    };
    const onPairing = (pr, first) => {
        if (!pr) return;
        const step = [pr.state, pr.id, pr.pin || ""].join("|");
        if (step === handled.current) return;
        handled.current = step;
        if (first) return; // a result left over from before the dialog opened
        closePrompt();
        const name = pr.name || "";
        if (pr.state === "confirm") {
            prompt.current = showModalHere(jsx(DFL.ConfirmModal, {
                strTitle: name, strDescription: T.btPinMatch(name, pr.pin), strOKButtonText: S.btPair(),
                onOK: () => call(be.btPairAnswer, true).catch(() => { }),
                onCancel: () => call(be.btPairAnswer, false).catch(() => { }),
            }));
        }
        else if (pr.state === "display_pin") {
            prompt.current = showModalHere(jsx(DFL.ConfirmModal, { bAlertDialog: true, strTitle: name, strDescription: T.btTypePin(pr.pin) }));
        }
        else if (pr.state === "done") {
            toast(name + " · " + S.btPaired());
            refresh();
            closeModal();
        }
        else if (pr.state === "failed") {
            toast(S.pairFailed() + (pr.status ? " (" + pr.status + ")" : ""));
        }
    };
    const apply = (r, first) => {
        if (!alive.current || !r) return;
        setRes({ ...r, devices: stable(r.devices || []) });
        lastPairing.current = r.pairing || null;
        onPairing(r.pairing, first);
    };
    const poll = async (first) => {
        try { apply(await call(be.btScanResults), first); }
        catch (e) { if (first) toast(errText(e)); }
    };
    const scan = async () => {
        try { await call(be.btScan, true); }
        catch (e) { toast(errText(e)); }
        await poll(false);
    };
    useEffect(() => {
        poll(true).then(scan);
        const t = setInterval(() => poll(false), 1000);
        return () => {
            alive.current = false;
            clearInterval(t);
            closePrompt();
            call(be.btScan, false).catch(() => { });
            // a prompt can't be answered once the dialog is gone, so a pairing in progress stops with it
            if (lastPairing.current && PAIR_ACTIVE.has(lastPairing.current.state)) call(be.btPairCancel).catch(() => { });
        };
    }, []);
    const pr = res?.pairing || {};
    const busy = PAIR_ACTIVE.has(pr.state);
    const devices = (res?.devices || []).filter((d) => !(pr.state === "done" && pr.id === d.id));
    const pair = async (d) => {
        if (busy) return;
        handled.current = null;
        try { apply({ ...res, pairing: await call(be.btPair, d.id) }, false); }
        catch (e) { toast(errText(e)); }
    };
    const scanning = !res || res.scanning;
    return dialog(closeModal, S.btAvailable(), [
        jsx(DFL.Focusable, {
            style: { display: "flex", flexDirection: "column" },
            children: devices.map((d) => {
                const mine = busy && pr.id === d.id;
                return jsx(DFL.Field, {
                    label: d.name, icon: deviceIcon(d.type), description: mine ? T.btPairing : null,
                    disabled: busy && !mine, ...pressable(() => pair(d)),
                    children: mine ? spinner() : null,
                }, d.id);
            }),
        }),
        scanning && jsx(DFL.Field, { label: S.btSearching(), children: spinner() }),
        !scanning && devices.length === 0 && jsx(DFL.Field, { label: T.btNoneFound }),
    ], busy
        ? jsx(DFL.DialogButton, { onClick: () => call(be.btPairCancel).catch((e) => toast(errText(e))), children: S.btCancelPair() })
        : jsx(DFL.DialogButton, { onClick: scan, disabled: scanning, children: T.rescan }));
}
const addBtDevice = () => showModalHere(jsx(BtPairModal, {}));

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
const perfShown = {};    // key -> { v, t } value shown before Steam confirms it
const perfWanted = {};   // key -> value waiting to be sent
const perfSending = {};  // key -> write in flight
function setClientSetting(k, v) {
    perfShown[k] = { v, t: Date.now() };
    perfWanted[k] = v;
    if (!perfSending[k]) sendClientSetting(k);
}
async function sendClientSetting(k) {
    perfSending[k] = true;
    try {
        while (k in perfWanted) {
            const v = perfWanted[k];
            delete perfWanted[k];
            try { await window.settingsStore.GetClientSetting(k)[1](v); }
            catch (e) { toast(errText(e)); }
        }
    }
    finally { perfSending[k] = false; }
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
const PerfVisible = R.createContext(false);
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
        const t = setInterval(poll, 2000);
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
function patchSteamPerfPanel(original) {
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
function PerfSection({ active }) {
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

// ---------------------------------------------------------------- Performance tab: frame limit + per-game profiles
// "Frame Limit" works like Steam Deck's TDP Limit: a toggle, and the FPS slider under it while it is on. The cap is
// RTSS (all graphics APIs) or the Intel driver limiter; the refresh rate is never touched (the panel has VRR).
// "Use per-game profile" works like Steam Deck's: the backend keeps a default profile and one per game and applies
// the running game's one (set_active_game in service.py). The heading row and its explainer are Steam Deck's own
// markup and strings (QuickAccess_Tab_Perf_*) with Steam's classes; Steam's own components for them read Steam's
// SteamOS-only profile store, so they can't be used as they are.
const deckPerfParts = lazy(() => {
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

function FrameSection({ active }) {
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
let stopped = false;     // set on unload
let tripped = false;     // set by the render-burst guard

const wakeSubs = new Set();
function wakePanels() { wakeSubs.forEach((f) => f()); }

// diagnostics, read from the console as window.__WINQS.status
const injectStatus = { settings: "waiting for Quick Access", perf: "waiting for Quick Access", error: null };
function setStatus(key, value) { injectStatus[key] = value; }
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
function InjectedPanel({ original, visible }) {
    const off = useInjectionOff("settings");
    // the same two child slots in every state, so Steam's own panel never remounts
    return jsxs(Fragment, {
        children: [
            off ? null : jsx(ErrorBoundary, { children: jsx(QuickSettings, { active: visible }) }),
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
                off ? null : jsx(ErrorBoundary, { children: jsx(PerfSection, { active: visible }) }),
                off ? null : jsx(ErrorBoundary, { children: jsx(FrameSection, { active: visible }) }),
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

function installPatch() {
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

function uninstallPatch() {
    if (stopped) return;
    stopped = true;
    for (const { patch } of patches) {
        try { patch.unpatch(); } catch (e) { console.warn(LOG, "unpatch failed", e); }
    }
    try { retypeMountedQams(); } catch (e) { console.warn(LOG, "fiber restore failed", e); }
    patches = [];
    wakePanels(); // live wrappers render Steam's panel alone
}

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
const findMobxReaction = lazy(() => DFL.findModuleExport((e) => typeof e === "function"
    && /!=null\?\w+:"Reaction"/.test(String(e)) && String(e).includes("compareStructural")));
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
    try { api.addEventListener("winqs_menu_hotkey", onMenuHotkey); }
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
    try { api.removeEventListener("winqs_menu_hotkey", onMenuHotkey); } catch { }
    try { stopOverlayWatch?.(); } catch { }
    try { lifetimeReg?.unregister(); } catch { }
    clearTimeout(overlayRetry);
    clearInterval(overlayHeartbeat);
    stopOverlayWatch = lifetimeReg = overlayHeartbeat = null;
    if (sentOverlays) call(be.setGameOverlays, []).catch(() => { });
    sentOverlays = null;
}

var index = definePlugin(() => {
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
    return {
        name: manifest.name,
        titleView: jsx("div", { className: DFL.staticClasses?.Title, children: manifest.name }),
        // nothing here: the controls live in Steam's Quick Settings and Performance tabs, the plugin has no settings
        content: jsx(Fragment, {}),
        icon: icon("WiFi"),
        onDismount() {
            uninstallPatch();
            restoreScalingSection();
            stopMenuHotkeys();
            stopGameWatchNow();
            stopPortalWatch();
            if (window.__WINQS?.stop === uninstallPatch) delete window.__WINQS;
        },
    };
});

export { index as default };
