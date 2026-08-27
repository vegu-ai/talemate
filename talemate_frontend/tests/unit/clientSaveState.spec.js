import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
    createClientSaveState,
    SAVE_DELAY_MS,
    SAVE_ECHO_GRACE_MS,
} from "@/utils/clientSaveState";
import { createConfigSaveQueue } from "@/utils/configSaveQueue";

function makeClient(name, fields = {}) {
    return { name, dirty: false, ...fields };
}

// a client_status message whose data echoes the given fields
function statusEcho(fields = {}) {
    const { max_token_length, api_url, ...dataFields } = fields;
    return { max_token_length, api_url, data: { ...dataFields } };
}

beforeEach(() => {
    vi.useFakeTimers();
});

afterEach(() => {
    vi.useRealTimers();
});

describe("scheduleSave", () => {
    it("marks the row dirty and fires the save after the delay", () => {
        const state = createClientSaveState();
        const client = makeClient("A");
        const save = vi.fn();

        state.scheduleSave(client, save);

        expect(client.dirty).toBe(true);
        expect(save).not.toHaveBeenCalled();
        vi.advanceTimersByTime(SAVE_DELAY_MS);
        expect(save).toHaveBeenCalledTimes(1);
    });

    it("debounces repeated edits into one save", () => {
        const state = createClientSaveState();
        const client = makeClient("A");
        const save = vi.fn();

        state.scheduleSave(client, save);
        vi.advanceTimersByTime(SAVE_DELAY_MS - 100);
        state.scheduleSave(client, save);
        vi.advanceTimersByTime(SAVE_DELAY_MS - 100);

        expect(save).not.toHaveBeenCalled();
        vi.advanceTimersByTime(100);
        expect(save).toHaveBeenCalledTimes(1);
    });

    it("keeps separate timers per row", () => {
        const state = createClientSaveState();
        const saveA = vi.fn();
        const saveB = vi.fn();

        state.scheduleSave(makeClient("A"), saveA);
        vi.advanceTimersByTime(200);
        state.scheduleSave(makeClient("B"), saveB);
        vi.advanceTimersByTime(SAVE_DELAY_MS - 200);

        expect(saveA).toHaveBeenCalledTimes(1);
        expect(saveB).not.toHaveBeenCalled();
    });
});

describe("reset", () => {
    it("clears the dirty flag of a row whose save was sent", () => {
        const state = createClientSaveState();
        const client = makeClient("A", { api_url: "http://edited" });

        state.recordSent(client);
        state.reset([client]);

        expect(client.dirty).toBe(false);
    });

    it("drops the echo snapshot of a row whose save was sent", () => {
        const state = createClientSaveState();
        const client = makeClient("A", { api_url: "http://edited" });

        state.recordSent(client);
        state.reset([client]);
        client.dirty = true;

        // without a snapshot any status resolves the dirty state
        expect(state.echoResolves(client, statusEcho({ api_url: "http://backend" }))).toBe(true);
    });

    // an armed timer is an unsent edit, not optimistic row state — the
    // reset must not cancel it
    it("keeps an armed debounce timer, which fires its own save", () => {
        const state = createClientSaveState();
        const client = makeClient("B");
        const save = vi.fn();

        state.scheduleSave(client, save);
        state.reset([client]);
        vi.advanceTimersByTime(SAVE_DELAY_MS);

        expect(save).toHaveBeenCalledTimes(1);
    });

    it("drops the snapshot but keeps the timer of a row edited again after its save", () => {
        const state = createClientSaveState();
        const client = makeClient("A", { api_url: "http://edited" });
        const save = vi.fn();

        state.recordSent(client);
        state.scheduleSave(client, save);
        state.reset([client]);

        expect(client.dirty).toBe(true);
        vi.advanceTimersByTime(SAVE_DELAY_MS);
        expect(save).toHaveBeenCalledTimes(1);
        // snapshot gone: once the timer is spent, any status resolves the row
        expect(state.echoResolves(client, statusEcho({ api_url: "http://other" }))).toBe(true);
    });

    it("keeps the dirty flag of a row with an armed timer", () => {
        const state = createClientSaveState();
        const client = makeClient("B");

        state.scheduleSave(client, vi.fn());
        state.reset([client]);

        expect(client.dirty).toBe(true);
    });

    // the tables are keyed by user-chosen names — a name that exists on
    // Object.prototype must not read as an armed timer or a pending save
    it("treats a row named after a prototype property like any other row", () => {
        const state = createClientSaveState();
        const client = makeClient("constructor", { api_url: "http://edited" });
        const save = vi.fn();

        client.dirty = true;
        state.reset([client]);
        expect(client.dirty).toBe(false);
        expect(state.echoResolves(client, statusEcho({ api_url: "http://backend" }))).toBe(true);

        state.scheduleSave(client, save);
        state.reset([client]);
        expect(client.dirty).toBe(true);
        vi.advanceTimersByTime(SAVE_DELAY_MS);
        expect(save).toHaveBeenCalledTimes(1);

        state.recordSent(client);
        state.reset([client]);
        expect(client.dirty).toBe(false);
    });

    // `reset` reads "no timer entry" as "edit already sent" — that holds only
    // because the timer key is deleted before `save()` runs, and in the app
    // the reset runs synchronously inside that callback
    it("clears the fired row when the reset runs inside its save callback", () => {
        const state = createClientSaveState();
        const client = makeClient("A");

        state.scheduleSave(client, () => {
            state.recordSent(client);
            state.reset([client]);
        });
        vi.advanceTimersByTime(SAVE_DELAY_MS);

        expect(client.dirty).toBe(false);
    });

    it("handles the refused-save scenario: the sent row resets, the unsent row retries", () => {
        const state = createClientSaveState();
        const clientA = makeClient("A");
        const clientB = makeClient("B");
        const saveB = vi.fn();

        state.scheduleSave(clientA, vi.fn());
        vi.advanceTimersByTime(200);
        state.scheduleSave(clientB, saveB);
        vi.advanceTimersByTime(SAVE_DELAY_MS - 200);
        // A's timer fired; pretend its save was sent and then refused
        state.recordSent(clientA);
        state.reset([clientA, clientB]);

        expect(clientA.dirty).toBe(false);
        expect(clientB.dirty).toBe(true);
        vi.advanceTimersByTime(200);
        expect(saveB).toHaveBeenCalledTimes(1);
    });
});

describe("echoResolves", () => {
    it("ignores a status while the row is still debouncing", () => {
        const state = createClientSaveState();
        const client = makeClient("A", { api_url: "http://edited" });

        state.scheduleSave(client, vi.fn());

        expect(state.echoResolves(client, statusEcho({ api_url: "http://edited" }))).toBe(false);
        expect(client.dirty).toBe(true);
    });

    it("resolves when the echo carries the sent values back", () => {
        const state = createClientSaveState();
        const client = makeClient("A", { api_url: "http://edited", rate_limit: 5 });

        state.recordSent(client);
        const resolved = state.echoResolves(client, statusEcho({ api_url: "http://edited", rate_limit: 5 }));

        expect(resolved).toBe(true);
        expect(client.dirty).toBe(false);
    });

    it("ignores a stale echo inside the grace window", () => {
        const state = createClientSaveState();
        const client = makeClient("A", { api_url: "http://edited" });

        state.recordSent(client);
        const resolved = state.echoResolves(client, statusEcho({ api_url: "http://stale" }));

        expect(resolved).toBe(false);
        expect(client.dirty).toBe(true);
    });

    // the drawer writes preset_group on the row when a group is created from
    // the preset menu, and the status the backend emits until that save is
    // applied carries the group the client had before it
    it("ignores a stale preset_group echo inside the grace window", () => {
        const state = createClientSaveState();
        const client = makeClient("A", { preset_group: "fast" });

        state.recordSent(client);
        const resolved = state.echoResolves(client, statusEcho({ preset_group: "" }));

        expect(resolved).toBe(false);
        expect(client.dirty).toBe(true);
    });

    it("resolves once the echo carries the new preset_group", () => {
        const state = createClientSaveState();
        const client = makeClient("A", { preset_group: "fast" });

        state.recordSent(client);
        const resolved = state.echoResolves(client, statusEcho({ preset_group: "fast" }));

        expect(resolved).toBe(true);
        expect(client.dirty).toBe(false);
    });

    it("resolves a mismatched echo once the grace window expires", () => {
        const state = createClientSaveState();
        const client = makeClient("A", { api_url: "http://edited" });

        state.recordSent(client);
        vi.advanceTimersByTime(SAVE_ECHO_GRACE_MS + 1);

        expect(state.echoResolves(client, statusEcho({ api_url: "http://stale" }))).toBe(true);
        expect(client.dirty).toBe(false);
    });

    it("treats fields the client type does not carry as confirmed", () => {
        const state = createClientSaveState();
        const client = makeClient("A", { api_url: "http://edited" });

        state.recordSent(client);

        // rate_limit is undefined on the row, mismatch in the echo is fine
        expect(state.echoResolves(client, statusEcho({ api_url: "http://edited", rate_limit: 9 }))).toBe(true);
    });

    it("treats empty string, null and undefined as the same echoed value", () => {
        const state = createClientSaveState();
        const client = makeClient("A", { api_url: "" });

        state.recordSent(client);

        expect(state.echoResolves(client, statusEcho({ api_url: null }))).toBe(true);
    });
});

// the save state wired to a real config save queue, the way TalemateApp and
// AIClient compose them — no stubbed resetPendingSaves
describe("integration with the config save queue", () => {
    function makeHarness(clients) {
        const state = createClientSaveState();
        const connected = { value: true };
        const send = vi.fn();
        const notifyError = vi.fn();
        const queue = createConfigSaveQueue({
            send,
            getConfig: () => ({ game: {} }),
            notifyError,
            resetPendingSaves: () => state.reset(clients),
            isConnected: () => connected.value,
        });
        // the component glue: a fired timer records the row as sent and
        // saves the whole client map under the shared 'clients' label
        const fire = (client) => () => {
            state.recordSent(client);
            queue.saveAppConfig((config) => {
                config.clients = Object.fromEntries(clients.map(c => [c.name, { ...c }]));
            }, { label: "clients" });
        };
        return { state, queue, connected, send, notifyError, fire };
    }

    it("rescues the unsent edit when the connection returns inside its window", () => {
        const clients = [makeClient("A"), makeClient("B")];
        const { state, connected, send, notifyError, fire } = makeHarness(clients);

        state.scheduleSave(clients[0], fire(clients[0]));
        vi.advanceTimersByTime(200);
        state.scheduleSave(clients[1], fire(clients[1]));
        connected.value = false;
        vi.advanceTimersByTime(SAVE_DELAY_MS - 200);

        // A's save was refused under its own label; B's edit is still armed
        expect(send).not.toHaveBeenCalled();
        expect(notifyError).toHaveBeenCalledTimes(1);
        expect(notifyError).toHaveBeenCalledWith("Settings save failed (clients): not connected");
        expect(clients[1].dirty).toBe(true);

        connected.value = true;
        vi.advanceTimersByTime(200);

        expect(send).toHaveBeenCalledTimes(1);
        // the whole map goes out, A's refused content riding along — by design
        expect(send.mock.calls[0][0].config.clients).toEqual({
            A: expect.objectContaining({ name: "A" }),
            B: expect.objectContaining({ name: "B" }),
        });
        expect(notifyError).toHaveBeenCalledTimes(1);
    });

    it("reports each refused edit under its own attempt while disconnected", () => {
        const clients = [makeClient("A"), makeClient("B")];
        const { state, connected, send, notifyError, fire } = makeHarness(clients);

        state.scheduleSave(clients[0], fire(clients[0]));
        vi.advanceTimersByTime(200);
        state.scheduleSave(clients[1], fire(clients[1]));
        connected.value = false;
        vi.advanceTimersByTime(SAVE_DELAY_MS);

        expect(send).not.toHaveBeenCalled();
        expect(notifyError).toHaveBeenCalledTimes(2);
        expect(clients[0].dirty).toBe(false);
        expect(clients[1].dirty).toBe(false);
    });
});

describe("forget", () => {
    it("cancels the row's timer", () => {
        const state = createClientSaveState();
        const save = vi.fn();

        state.scheduleSave(makeClient("A"), save);
        state.forget("A");
        vi.advanceTimersByTime(SAVE_DELAY_MS);

        expect(save).not.toHaveBeenCalled();
    });

    it("drops the row's echo snapshot", () => {
        const state = createClientSaveState();
        const client = makeClient("A", { api_url: "http://edited" });

        state.recordSent(client);
        state.forget("A");

        expect(state.echoResolves(client, statusEcho({ api_url: "http://other" }))).toBe(true);
    });
});
