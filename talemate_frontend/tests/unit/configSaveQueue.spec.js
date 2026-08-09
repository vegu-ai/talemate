import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { createConfigSaveQueue } from "@/utils/configSaveQueue";

function makeQueue(config = { game: { general: { auto_save: true } } }) {
    const deps = {
        send: vi.fn(),
        // hands out the shared object, like the production wiring
        // (`getConfig: () => this.appConfig`) — cloning here would make the
        // no-mutation test pass against an implementation that corrupts it
        getConfig: vi.fn(() => config),
        notifyError: vi.fn(),
        resetPendingSaves: vi.fn(),
    };
    return { queue: createConfigSaveQueue(deps), ...deps };
}

function sentConfig(send, callIndex = 0) {
    return send.mock.calls[callIndex][0].config;
}

function complete(queue, requestId) {
    queue.handleMessage({ type: "config", action: "save_complete", request_id: requestId });
}

function refuse(queue, requestId, message = "validation failed") {
    queue.handleMessage({
        type: "config",
        action: "operation_done",
        request_id: requestId,
        error: { message },
    });
}

function applyFailed(queue, requestId, message = "config saved, but applying it failed") {
    queue.handleMessage({
        type: "config",
        action: "operation_done",
        request_id: requestId,
        stage: "apply",
        error: { message },
    });
}

describe("sendConfigSave", () => {
    it("sends a config/save carrying the returned request id", () => {
        const { queue, send } = makeQueue();

        const requestId = queue.sendConfigSave({ game: {} }, { label: "game" });

        expect(send).toHaveBeenCalledTimes(1);
        expect(send.mock.calls[0][0]).toEqual({
            type: "config",
            action: "save",
            request_id: requestId,
            config: { game: {} },
        });
    });

    it("deep-clones the payload so later edits of the caller's object are not sent", () => {
        const { queue, send } = makeQueue();
        const working = { game: { general: { auto_save: true } } };

        queue.sendConfigSave(working);
        working.game.general.auto_save = false;
        working.clients = { added: "later" };

        expect(sentConfig(send)).toEqual({ game: { general: { auto_save: true } } });
    });

    it("hands out a unique request id per save", () => {
        const { queue } = makeQueue();

        const ids = [
            queue.sendConfigSave({ game: {} }),
            queue.sendConfigSave({ game: {} }),
            queue.sendConfigSave({ game: {} }),
        ];

        expect(new Set(ids).size).toBe(3);
    });
});

describe("saveAppConfig", () => {
    it("builds the payload on the stored config", () => {
        const { queue, send, getConfig } = makeQueue({ game: { general: { auto_save: true } } });

        queue.saveAppConfig(config => {
            config.game.general.auto_save = false;
        });

        expect(getConfig).toHaveBeenCalledTimes(1);
        expect(sentConfig(send)).toEqual({ game: { general: { auto_save: false } } });
    });

    it("returns the request id of the save it sent", () => {
        const { queue, send } = makeQueue();

        const requestId = queue.saveAppConfig(() => {});

        expect(requestId).toBe(send.mock.calls[0][0].request_id);
    });

    it("does not mutate the stored config", () => {
        const stored = { game: { general: { auto_save: true } } };
        const { queue } = makeQueue(stored);

        queue.saveAppConfig(config => {
            config.game.general.auto_save = false;
        });

        expect(stored.game.general.auto_save).toBe(true);
    });

    it("stacks a second save on the pending payload while the first is in flight", () => {
        const { queue, send, getConfig } = makeQueue({ game: {} });

        queue.saveAppConfig(config => {
            config.first = true;
        });
        queue.saveAppConfig(config => {
            config.second = true;
        });

        expect(getConfig).toHaveBeenCalledTimes(1);
        expect(sentConfig(send, 1)).toEqual({ game: {}, first: true, second: true });
    });

    it("returns to the stored config once every in-flight save is answered", () => {
        const { queue, send, getConfig } = makeQueue({ game: {} });

        const first = queue.saveAppConfig(config => {
            config.first = true;
        });
        const second = queue.saveAppConfig(config => {
            config.second = true;
        });
        complete(queue, first);
        complete(queue, second);
        queue.saveAppConfig(config => {
            config.third = true;
        });

        expect(getConfig).toHaveBeenCalledTimes(2);
        expect(sentConfig(send, 2)).toEqual({ game: {}, third: true });
    });

    it("keeps stacking while any save is still unanswered", () => {
        const { queue, send } = makeQueue({ game: {} });

        const first = queue.saveAppConfig(config => {
            config.first = true;
        });
        queue.saveAppConfig(config => {
            config.second = true;
        });
        complete(queue, first);
        queue.saveAppConfig(config => {
            config.third = true;
        });

        expect(sentConfig(send, 2)).toEqual({ game: {}, first: true, second: true, third: true });
    });

    it("stacks on a payload the settings page sent, not on the stored config", () => {
        const { queue, send, getConfig } = makeQueue({ game: {}, stored: true });

        queue.sendConfigSave({ game: {}, fromSettings: true });
        queue.saveAppConfig(config => {
            config.fromDrawer = true;
        });

        expect(getConfig).not.toHaveBeenCalled();
        expect(sentConfig(send, 1)).toEqual({ game: {}, fromSettings: true, fromDrawer: true });
    });
});

describe("saveAppConfig with an empty base", () => {
    let warn;

    beforeEach(() => {
        warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    });

    afterEach(() => {
        warn.mockRestore();
    });

    it("skips the save when the config is not available yet", () => {
        const { queue, send } = makeQueue(null);

        const requestId = queue.saveAppConfig(config => {
            config.game = {};
        });

        expect(requestId).toBeNull();
        expect(send).not.toHaveBeenCalled();
    });

    it("skips the save when the config has no sections", () => {
        const { queue, send } = makeQueue({});

        const requestId = queue.saveAppConfig(config => {
            config.game = {};
        });

        expect(requestId).toBeNull();
        expect(send).not.toHaveBeenCalled();
    });
});

describe("request id attribution", () => {
    it("ignores a save_complete for an unknown request id", () => {
        const { queue } = makeQueue({ game: {} });
        const onComplete = vi.fn();

        queue.saveAppConfig(() => {}, { onComplete });
        complete(queue, "cfg-from-another-window");

        expect(onComplete).not.toHaveBeenCalled();
    });

    it("keeps the stacking base after a save_complete for an unknown request id", () => {
        const { queue, send, getConfig } = makeQueue({ game: {} });

        queue.saveAppConfig(config => {
            config.first = true;
        });
        complete(queue, "cfg-from-another-window");
        queue.saveAppConfig(config => {
            config.second = true;
        });

        expect(getConfig).toHaveBeenCalledTimes(1);
        expect(sentConfig(send, 1)).toEqual({ game: {}, first: true, second: true });
    });

    it("calls onComplete of the matching save only", () => {
        const { queue } = makeQueue({ game: {} });
        const onFirst = vi.fn();
        const onSecond = vi.fn();

        const first = queue.saveAppConfig(() => {}, { onComplete: onFirst });
        queue.saveAppConfig(() => {}, { onComplete: onSecond });
        complete(queue, first);

        expect(onFirst).toHaveBeenCalledTimes(1);
        expect(onSecond).not.toHaveBeenCalled();
    });

    it("ignores an operation_done that carries no error", () => {
        const { queue, notifyError } = makeQueue({ game: {} });
        const onError = vi.fn();

        const requestId = queue.saveAppConfig(() => {}, { onError });
        queue.handleMessage({ type: "config", action: "operation_done", request_id: requestId });

        expect(onError).not.toHaveBeenCalled();
        expect(notifyError).not.toHaveBeenCalled();
    });
});

describe("refused save", () => {
    function threeInFlight(labels = ["A", "B", "C"]) {
        const harness = makeQueue({ game: {} });
        const handlers = labels.map(() => ({ onError: vi.fn(), onComplete: vi.fn() }));
        const ids = labels.map((label, index) =>
            harness.queue.saveAppConfig(config => {
                config[label] = true;
            }, { label, ...handlers[index] }),
        );
        return { ...harness, ids, handlers };
    }

    it("fails the refused save and everything stacked on it", () => {
        const { queue, ids, handlers } = threeInFlight();

        refuse(queue, ids[1], "validation failed");

        expect(handlers[1].onError).toHaveBeenCalledWith("validation failed");
        expect(handlers[2].onError).toHaveBeenCalledWith("validation failed");
    });

    it("leaves saves sent before the refused one untouched", () => {
        const { queue, ids, handlers } = threeInFlight();

        refuse(queue, ids[1]);

        expect(handlers[0].onError).not.toHaveBeenCalled();

        complete(queue, ids[0]);

        expect(handlers[0].onComplete).toHaveBeenCalledTimes(1);
    });

    it("reports every affected label in one error", () => {
        const { queue, ids, notifyError } = threeInFlight();

        refuse(queue, ids[1], "validation failed");

        expect(notifyError).toHaveBeenCalledTimes(1);
        expect(notifyError).toHaveBeenCalledWith("Settings save failed (B, C): validation failed");
    });

    it("names a label shared by several affected saves once", () => {
        const { queue, ids, notifyError } = threeInFlight(["A", "agents", "agents"]);

        refuse(queue, ids[1], "validation failed");

        expect(notifyError).toHaveBeenCalledWith("Settings save failed (agents): validation failed");
    });

    it("falls back to a generic message when the error carries none", () => {
        const { queue, ids, notifyError } = threeInFlight();

        queue.handleMessage({
            type: "config",
            action: "operation_done",
            request_id: ids[1],
            error: {},
        });

        expect(notifyError).toHaveBeenCalledWith("Settings save failed (B, C): unknown error");
    });

    it("resets the optimistic rows of the drawer", () => {
        const { queue, ids, resetPendingSaves } = threeInFlight();

        refuse(queue, ids[1]);

        expect(resetPendingSaves).toHaveBeenCalledTimes(1);
    });

    // documents current behavior, not the intended contract: suspected bug reported separately (PR #221)
    it("stops stacking on the refused payload", () => {
        const { queue, ids, send, getConfig } = threeInFlight();

        refuse(queue, ids[1]);
        queue.saveAppConfig(config => {
            config.next = true;
        });

        expect(getConfig).toHaveBeenCalledTimes(2);
        expect(sentConfig(send, 3)).toEqual({ game: {}, next: true });
    });
});

describe("apply-failed save", () => {
    function twoInFlight() {
        const harness = makeQueue({ game: {} });
        const first = { onError: vi.fn(), onComplete: vi.fn() };
        const second = { onError: vi.fn(), onComplete: vi.fn() };
        const firstId = harness.queue.saveAppConfig(config => {
            config.first = true;
        }, { label: "clients", ...first });
        const secondId = harness.queue.saveAppConfig(config => {
            config.second = true;
        }, { label: "agents", ...second });
        return { ...harness, firstId, secondId, first, second };
    }

    it("fails only the save whose apply failed", () => {
        const { queue, firstId, first, second } = twoInFlight();

        applyFailed(queue, firstId);

        expect(first.onError).toHaveBeenCalledTimes(1);
        expect(second.onError).not.toHaveBeenCalled();
    });

    it("marks the failure as apply-failed for its onError", () => {
        const { queue, firstId, first } = twoInFlight();

        applyFailed(queue, firstId, "saved, but applying it failed");

        expect(first.onError).toHaveBeenCalledWith("saved, but applying it failed", true);
    });

    it("keeps the stacked save in flight and completes it normally", () => {
        const { queue, firstId, secondId, second } = twoInFlight();

        applyFailed(queue, firstId);
        complete(queue, secondId);

        expect(second.onComplete).toHaveBeenCalledTimes(1);
        expect(second.onError).not.toHaveBeenCalled();
    });

    it("reports the backend message unprefixed", () => {
        const { queue, firstId, notifyError } = twoInFlight();

        applyFailed(queue, firstId, "saved, but applying it failed");

        expect(notifyError).toHaveBeenCalledTimes(1);
        expect(notifyError).toHaveBeenCalledWith("saved, but applying it failed");
    });

    it("leaves the optimistic rows of the drawer alone", () => {
        const { queue, firstId, resetPendingSaves } = twoInFlight();

        applyFailed(queue, firstId);

        expect(resetPendingSaves).not.toHaveBeenCalled();
    });

    it("keeps the stacking base while another save is in flight", () => {
        const { queue, firstId, send, getConfig } = twoInFlight();

        applyFailed(queue, firstId);
        queue.saveAppConfig(config => {
            config.third = true;
        });

        expect(getConfig).toHaveBeenCalledTimes(1);
        expect(sentConfig(send, 2)).toEqual({ game: {}, first: true, second: true, third: true });
    });

    it("clears the stacking base once the queue empties", () => {
        const { queue, firstId, secondId, send, getConfig } = twoInFlight();

        applyFailed(queue, firstId);
        complete(queue, secondId);
        queue.saveAppConfig(config => {
            config.third = true;
        });

        expect(getConfig).toHaveBeenCalledTimes(2);
        expect(sentConfig(send, 2)).toEqual({ game: {}, third: true });
    });

    it("ignores an apply failure for an unknown request id", () => {
        const { queue, first, second, notifyError } = twoInFlight();

        applyFailed(queue, "cfg-from-another-window");

        expect(first.onError).not.toHaveBeenCalled();
        expect(second.onError).not.toHaveBeenCalled();
        expect(notifyError).not.toHaveBeenCalled();
    });
});

describe("dropAll", () => {
    it("fails every in-flight save with the given message", () => {
        const { queue } = makeQueue({ game: {} });
        const onFirst = vi.fn();
        const onSecond = vi.fn();

        queue.saveAppConfig(() => {}, { onError: onFirst });
        queue.saveAppConfig(() => {}, { onError: onSecond });
        queue.dropAll("connection lost");

        expect(onFirst).toHaveBeenCalledWith("connection lost");
        expect(onSecond).toHaveBeenCalledWith("connection lost");
    });

    // documents current behavior, not the intended contract: suspected bug reported separately (PR #221)
    it("reports nothing and leaves the drawer rows to the caller", () => {
        const { queue, notifyError, resetPendingSaves } = makeQueue({ game: {} });

        queue.saveAppConfig(() => {}, { onError: vi.fn() });
        queue.dropAll("connection lost");

        expect(notifyError).not.toHaveBeenCalled();
        expect(resetPendingSaves).not.toHaveBeenCalled();
    });

    it("ignores late answers for the dropped saves", () => {
        const { queue, notifyError } = makeQueue({ game: {} });
        const handlers = { onError: vi.fn(), onComplete: vi.fn() };

        const requestId = queue.saveAppConfig(() => {}, handlers);
        queue.dropAll("connection lost");
        handlers.onError.mockClear();
        complete(queue, requestId);
        refuse(queue, requestId);

        expect(handlers.onComplete).not.toHaveBeenCalled();
        expect(handlers.onError).not.toHaveBeenCalled();
        expect(notifyError).not.toHaveBeenCalled();
    });

    it("forgets the stacking base", () => {
        const { queue, send, getConfig } = makeQueue({ game: {} });

        queue.saveAppConfig(config => {
            config.first = true;
        }, { onError: vi.fn() });
        queue.dropAll("connection lost");
        queue.saveAppConfig(config => {
            config.second = true;
        });

        expect(getConfig).toHaveBeenCalledTimes(2);
        expect(sentConfig(send, 1)).toEqual({ game: {}, second: true });
    });
});
