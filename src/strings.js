import { toaster } from "@decky/api";
import manifest from "@decky/manifest";
import { LOG } from "./backend.js";

// ---------------------------------------------------------------- strings
// Steam's own localization first (same labels as on Steam Deck), own fallback second.
export function L(token, fallback) {
    try {
        const s = window.LocalizationManager?.LocalizeString?.("#" + token);
        if (s && !s.startsWith("#")) return s;
    }
    catch { /* ignore */ }
    return fallback;
}
export const IS_RU = (() => {
    try {
        const l = String(window.LocalizationManager?.m_rgLocalesToUse?.[0] || document.documentElement.lang || navigator.language || "");
        return /^ru|russian/i.test(l);
    }
    catch { return false; }
})();
export const T = IS_RU ? {
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
export const S = {
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
export function toast(body) {
    try { toaster.toast({ title: manifest.name, body: String(body) }); }
    catch (e) { console.warn(LOG, body, e); }
}
export const errText = (e) => String((e && e.message) || e);
