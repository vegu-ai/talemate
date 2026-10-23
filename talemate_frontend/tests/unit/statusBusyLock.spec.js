import { describe, it, expect, vi } from "vitest";
import { fileURLToPath } from "node:url";
import { lift, readSource } from "./helpers/liftMethod.js";

const source = readSource(fileURLToPath(new URL("../../src/components/TalemateApp.vue", import.meta.url)));
const handleMessage = lift(source, "handleMessage", "TalemateApp.vue");
const isInputDisabled = lift(source, "isInputDisabled", "TalemateApp.vue");

const app = () => ({
    notificatioonBusy: false,
    busy: false,
    playthroughActive: false,
    inputDisabled: false,
    messageHandlers: [],
    handlePlaythroughMessage: () => false,
    handleAutocompleteMessage: () => false,
});

const send = (state, payload) => handleMessage.call(state, { data: JSON.stringify(payload) });

describe("the busy lock that a cancel has to clear", () => {
    it("locks the input while a cancellable operation reports busy", () => {
        const state = app();
        send(state, { type: "status", status: "busy", message: "Determining character name", data: { cancellable: true } });
        expect(state.notificatioonBusy).toBe(true);
        expect(isInputDisabled.call(state)).toBe(true);
    });

    it("clears on the idle status a cancelled creation sends", () => {
        const state = app();
        send(state, { type: "status", status: "busy", message: "Determining character name" });
        send(state, { type: "status", status: "idle", message: "Character creation cancelled" });
        expect(state.notificatioonBusy).toBe(false);
        expect(isInputDisabled.call(state)).toBe(false);
    });

    it("does not clear on the operation_done envelope alone", () => {
        // the envelope carries no status, so the backend has to emit one:
        // a cancel that only sends this leaves the scene input disabled
        const state = app();
        send(state, { type: "status", status: "busy", message: "Determining character name" });
        send(state, { type: "director", action: "operation_done", data: {} });
        expect(state.notificatioonBusy).toBe(true);
        expect(isInputDisabled.call(state)).toBe(true);
    });
});
