import { callable } from "@decky/api";

export const LOG = "[WinQS]";

// ---------------------------------------------------------------- backend
export const be = {
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
export async function call(fn, ...args) {
    const r = await fn(...args);
    if (!r?.ok) throw new Error(r?.error || "backend error");
    return r.result;
}
// The first call runs fn; its result (null on a miss or an error) is kept for the plugin's lifetime.
export function lazy(fn, warning) {
    let value;
    const get = () => {
        if (value === undefined) {
            value = null;
            try { value = fn() ?? null; }
            catch (e) { if (warning) console.warn(LOG, warning, e); }
        }
        return value;
    };
    // Look it up ahead of time, keeping only a hit: a miss is not remembered, so something Steam loads later is still
    // found on first use.
    get.warm = () => {
        if (value !== undefined) return;
        try { value = fn() ?? undefined; }
        catch { }
    };
    return get;
}
