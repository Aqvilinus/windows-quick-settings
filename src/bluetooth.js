import * as DFL from "@decky/ui";
import { useEffect, useRef, useState } from "react";
import { jsx } from "react/jsx-runtime";
import { be, call } from "./backend.js";
import { S, T, errText, toast } from "./strings.js";
import { DIM, act, deviceIcon, dialog, dimIf, pending, pressable, refresh, runAction, showModalHere, spinner, useStableOrder } from "./ui.js";

// ---------------------------------------------------------------- Bluetooth device rows
export function BtDeviceRow({ device: d }) {
    const key = "bt:" + d.address;
    const working = pending(key) !== undefined;
    const isConnected = d.connected || d.audio_connected;
    const activate = () => {
        if (working) return;
        if (!d.audio_control) { toast(T.btNoControl); return; }
        const connect = !isConnected;
        runAction(key, connect, async () => {
            await call(be.bluetoothAudio, d.name, connect);
            await DFL.sleep(2500);
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
export async function openSettingsPage(page) {
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
export const addBtDevice = () => showModalHere(jsx(BtPairModal, {}));
