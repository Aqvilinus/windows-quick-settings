import manifest from "@decky/manifest";
import * as DFL from "@decky/ui";
import { Fragment, jsx, jsxs } from "react/jsx-runtime";
import { be, call } from "./backend.js";
import { BtDeviceRow, addBtDevice, openSettingsPage } from "./bluetooth.js";
import { IS_RU, L, S, T } from "./strings.js";
import { Row, ValueSlider, chevron, icon, checkAccess, pending, pressable, sep, spinner, store, useAutoRefresh, useStore, withPending } from "./ui.js";
import { MAX_INLINE_NETWORKS, NetworkRow, openWifiModal } from "./wifi.js";

export function QuickSettings({ active }) {
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
    const toggle = (key, label, iconName, checked, send) => Row(jsx(DFL.ToggleField, {
        label, icon: icon(iconName), checked: pending(key) ?? checked, disabled: pending(key) !== undefined,
        onChange: (v) => withPending(key, v, () => send(v)),
    }), key);

    return jsxs(Fragment, {
        children: [
            s.brightness != null && jsx(DFL.PanelSection, {
                title: S.brightness(),
                children: Row(jsx(ValueSlider, { id: "brightness", value: s.brightness, icon: icon("Brightness"),
                    // each change re-applies the power scheme, which Windows announces to the whole system
                    send: (v) => call(be.setBrightness, v), minGapMs: 150 })),
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
                        onChange: (v) => withPending("airplane", v, () => call(be.setAirplane, v)),
                    }), "airplane"),
                    wifiPresent && Row(jsx(DFL.ToggleField, {
                        label: S.wifi(), icon: icon("WiFi"), checked: wifiOn, bottomSeparator: sep(!wifiOn),
                        disabled: busy || radios.wifi === "disabled",
                        description: radios.wifi === "disabled" ? T.radioDisabled : null,
                        onChange: (v) => withPending("wifi", v, () => call(be.setWifi, v).then(checkAccess)),
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
                        onChange: (v) => withPending("bluetooth", v, () => call(be.setBluetooth, v).then(checkAccess)),
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
        onChange: (o) => { if (o && o.data !== current) withPending(key, o.data, () => call(be.setAudioDevice, flow, o.data)); },
    }));
}
