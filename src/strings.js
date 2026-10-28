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
// Own strings, each as [English, Russian], so the two can't drift apart; the UI language picks one.
const byLanguage = (pairs) => Object.fromEntries(Object.entries(pairs).map(([k, v]) => [k, v[IS_RU ? 1 : 0]]));
export const T = byLanguage({
    loading: ["Loading…", "Загрузка…"],
    saved: ["Saved", "Сохранена"],
    open: ["Open", "Открытая"],
    scanning: ["Searching for networks…", "Поиск сетей…"],
    rescan: ["Refresh", "Обновить"],
    password: ["Password", "Пароль"],
    wrongPassword: ["Could not connect: check the password", "Не удалось подключиться: проверьте пароль"],
    timeout: ["Could not connect (timed out)", "Не удалось подключиться (таймаут)"],
    locationOff: ["Wi-Fi networks hidden", "Сети Wi-Fi скрыты"],
    locationHint: [
        "Windows hides networks from apps while Location is off. Press to open the setting",
        "Windows не показывает сети приложениям, пока выключена геолокация. Нажмите, чтобы открыть настройки"],
    radioDisabled: ["Disabled in Windows (Device Manager)", "Отключено в Windows (диспетчер устройств)"],
    forget: ["Forget network", "Забыть сеть"],
    forgetQ: ["Remove this saved network and its password?", "Удалить сохранённую сеть и её пароль?"],
    forgotten: ["Network removed", "Сеть удалена"],
    notSaved: ["This network is not saved", "Эта сеть не сохранена"],
    groupPolicy: ["Set by policy, can't be removed", "Сеть задана политикой, её нельзя удалить"],
    passwordRule: ["8-63 characters or 64 hex digits", "8–63 символа или 64 шестнадцатеричные цифры"],
    notFound: ["The network is no longer visible", "Сеть больше не видна"],
    unsupported: [
        (s) => `${s} security is not supported, connect in Windows settings`,
        (s) => `Тип защиты ${s} не поддерживается, подключитесь через настройки Windows`],
    passwordRequired: ["Password required", "Нужен пароль"],
    disconnectQ: ["Disconnect from this network?", "Отключиться от этой сети?"],
    btNoControl: [
        "This device connects by itself; Windows has no connect button for it",
        "Это устройство подключается само, отдельной кнопки подключения у Windows для него нет"],
    btPairing: ["Pairing…", "Сопряжение…"],
    btNoneFound: [
        "No devices found. Put the device in pairing mode",
        "Устройства не найдены. Включите на устройстве режим сопряжения"],
    btPinMatch: [
        (name, pin) => `Make sure ${name} shows the code ${pin}`,
        (name, pin) => `Убедитесь, что на устройстве «${name}» показан код ${pin}`],
    btTypePin: [
        (pin) => `Type ${pin} on the device, then press Enter`,
        (pin) => `Введите на устройстве код ${pin} и нажмите Enter`],
    btForgetQ: [
        "Remove this device? You will need to pair it again to use it",
        "Удалить это устройство? Чтобы снова пользоваться им, понадобится повторное сопряжение"],
    btForgotten: ["Device removed", "Устройство удалено"],
    accessDenied: ["Windows did not allow switching the radio", "Windows не разрешила переключить радиомодуль"],
    allNetworks: ["All networks", "Все сети"],
    showPassword: ["Show password", "Показать пароль"],
    wrongPasswordShort: ["Wrong password, try again", "Неверный пароль, попробуйте ещё раз"],
    secured: ["Secured", "Защищена"],
    online: ["Internet", "Есть интернет"],
    noInternet: ["No internet", "Без интернета"],
    portal: ["The network requires additional login information.", "Сеть требует дополнительных данных для входа"],
    viaWindows: [(s) => `${s}: connect in Windows settings`, (s) => `${s}: подключайтесь через настройки Windows`],
    rtssSetup: ["Frame limit in all games", "Лимит FPS во всех играх"],
    rtssSetupHint: [
        "The Intel driver limit is in use and does not apply to DX12 games. Press to set up RTSS once: Windows will ask for administrator permission",
        "Сейчас работает лимит драйвера Intel, в DX12-играх он не действует. Нажмите, чтобы один раз настроить RTSS: Windows попросит разрешение администратора"],
    rtssMissing: [
        "The Intel driver limit does not apply to DX12 games. Install RTSS to limit every game",
        "Лимит драйвера Intel не действует в DX12-играх. Чтобы ограничивать все игры, установите RTSS"],
    rtssConfirm: ["Confirm the Windows prompt", "Подтвердите запрос Windows"],
    rtssWorking: ["Setting up…", "Настраивается…"],
    overlayPosition: ["Position", "Положение"],
});
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
