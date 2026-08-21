import { describe, it, expect, vi } from "vitest";
import PlaythroughMixin from "@/components/PlaythroughMixin.js";
import { playthroughBlocksNavigation } from "@/utils/playthrough";

// The mixin is a plain options object, so a fake host is enough - no component
// mount. The first message is the scene intro, which the backend emits without
// an id.
function makeHost({ active = true, savedAnchor = null } = {}) {
    const messages = [
        { type: "narrator", text: "the intro" },
        ...Array.from({ length: 5 }, (_, index) => ({
            id: index + 1,
            type: "narrator",
            text: `message ${index + 1}`,
        })),
    ];
    const sent = [];
    const host = {
        ...PlaythroughMixin.data(),
        websocket: { send: (frame) => sent.push(JSON.parse(frame)) },
        $refs: {
            sceneMessages: { messages, messageAt: (index) => messages[index] || null },
            audioQueue: { stopAndClear: vi.fn() },
        },
        scene: { data: { immutable_save: false, playthrough_progress: savedAnchor } },
        agentStatus: {},
        scrollInputIntoView: vi.fn(),
        $nextTick: (fn) => fn && fn(),
    };
    for (const [name, method] of Object.entries(PlaythroughMixin.methods)) {
        host[name] = method.bind(host);
    }
    for (const [name, getter] of Object.entries(PlaythroughMixin.computed || {})) {
        Object.defineProperty(host, name, { get: getter.bind(host) });
    }
    host.playthroughActive = active;
    host.playthroughMessageCount = messages.length;
    return { host, sent };
}

const progressSaves = (sent) =>
    sent.filter((frame) => frame.type === "playthrough" && frame.action === "save_progress");

describe("leaving a playthrough", () => {
    it("records the position and leaves the mode", () => {
        const { host, sent } = makeHost();
        host.setPlaythroughReveal(4);

        host.stopPlaythrough();

        expect(progressSaves(sent)).toEqual([{
            type: "playthrough",
            action: "save_progress",
            message_id: 3,
        }]);
        expect(host.playthroughActive).toBe(false);
    });

    it("records nothing when no playthrough is running", () => {
        // loading a scene ends the mode this way, whether one was running or
        // not; a cursor that is on nothing still resolves to the first message
        const { host, sent } = makeHost({ active: false });

        host.stopPlaythrough();

        expect(progressSaves(sent)).toEqual([]);
    });

    it("leaves the position alone when it has not moved", () => {
        const { host, sent } = makeHost({ savedAnchor: 3 });
        host.setPlaythroughReveal(4);

        host.stopPlaythrough();

        expect(progressSaves(sent)).toEqual([]);
        expect(host.playthroughActive).toBe(false);
    });
});

describe("playthroughBlocksNavigation", () => {
    it("refuses the director console while a replay runs", () => {
        expect(playthroughBlocksNavigation("directorConsole", true)).toBe(true);
    });

    it("offers it again once the replay is over", () => {
        expect(playthroughBlocksNavigation("directorConsole", false)).toBe(false);
    });

    it("leaves the drawers the mode keeps alone", () => {
        for (const drawer of ["game", "settings", "debug", "help"]) {
            expect(playthroughBlocksNavigation(drawer, true)).toBe(false);
        }
    });
});
