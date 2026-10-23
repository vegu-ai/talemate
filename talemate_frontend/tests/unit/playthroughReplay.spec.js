import { describe, it, expect, vi } from "vitest";
import PlaythroughMixin from "@/components/PlaythroughMixin.js";

const CLEAR_SCREEN = { type: "clear_screen" };
const REPLAY_COMPLETE = { type: "playthrough", action: "replay_complete" };

// The mixin is a plain options object, so a fake host is enough to drive the
// replay protocol frame by frame - no component mount.
function makeHost(messageCount = 20) {
    const messages = Array.from({ length: messageCount }, (_, index) => ({
        id: index + 1,
        type: "narrator",
        text: `message ${index + 1}`,
    }));
    const sent = [];
    const host = {
        ...PlaythroughMixin.data(),
        websocket: { send: (frame) => sent.push(JSON.parse(frame)) },
        $refs: {
            sceneMessages: { messages, messageAt: (index) => messages[index] || null },
            audioQueue: { stopAndClear: vi.fn() },
        },
        scene: { data: {} },
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
    return { host, sent, messages };
}

const starts = (sent) =>
    sent.filter((frame) => frame.type === "playthrough" && frame.action === "start");

/** What the backend does for one `start`: the replay's clear_screen, then its end. */
function answerReplay(host, answered) {
    answered.count += 1;
    host.handlePlaythroughMessage(CLEAR_SCREEN);
    host.handlePlaythroughMessage(REPLAY_COMPLETE);
}

/**
 * Answer every replay the client asked for, and every replay those answers
 * provoke, up to `limit`. A protocol that settles stops asking; one that does
 * not runs to the limit, which is the runaway this pins.
 */
function answerUntilSettled(host, sent, answered, limit = 12) {
    while (starts(sent).length > answered.count && answered.count < limit) {
        answerReplay(host, answered);
    }
    return starts(sent).length;
}

function enterAndAdvanceTo(cursor) {
    const { host, sent, messages } = makeHost();
    const answered = { count: 0 };
    host.startPlaythrough();
    answerReplay(host, answered);
    // what SceneMessages reports once the replay has rendered
    host.onSceneMessagesChanged({ count: messages.length, chapters: [] });
    host.setPlaythroughReveal(cursor);
    return { host, sent, messages, answered };
}

describe("the playthrough replay protocol", () => {
    it("replays once when the history is replaced under the cursor", () => {
        const { host, sent, answered } = enterAndAdvanceTo(10);

        host.handlePlaythroughMessage(CLEAR_SCREEN);
        const total = answerUntilSettled(host, sent, answered);

        // the entry replay plus exactly one for the replaced history
        expect(total).toBe(2);
        expect(host.playthroughRevealCount).toBe(10);
    });

    it("does not restart the narration of the message the cursor is on", () => {
        const { host, sent, answered } = enterAndAdvanceTo(10);
        host.onPlaythroughRevealed = vi.fn();

        host.handlePlaythroughMessage(CLEAR_SCREEN);
        answerUntilSettled(host, sent, answered);

        expect(host.onPlaythroughRevealed).not.toHaveBeenCalled();
        expect(host.playthroughRevealCount).toBe(10);
    });

    it("re-paces when the message the cursor was on is gone", () => {
        const { host, sent, messages, answered } = enterAndAdvanceTo(10);
        host.onPlaythroughRevealed = vi.fn();

        host.handlePlaythroughMessage(CLEAR_SCREEN);
        messages.splice(0, messages.length); // the edit that replaced the history deleted it
        answerUntilSettled(host, sent, answered);

        expect(host.playthroughRevealCount).toBe(1);
        expect(host.onPlaythroughRevealed).toHaveBeenCalled();
    });

    it("settles after two history-replacing emits land back to back", () => {
        // the frame the client's own replay opens with is indistinguishable
        // from a second foreign one; the flag this pins used to go permanently
        // out of phase there, and every replay's own clear_screen asked for
        // another - silently, and without end
        const { host, sent, answered } = enterAndAdvanceTo(10);

        host.handlePlaythroughMessage(CLEAR_SCREEN);
        host.handlePlaythroughMessage(CLEAR_SCREEN);
        const total = answerUntilSettled(host, sent, answered);

        expect(total).toBe(3);
        expect(host.playthroughRevealCount).toBe(10);
    });

    it("anchors on the list the cursor was an index into, not the one that replaced it", () => {
        const { host, messages } = enterAndAdvanceTo(10);

        host.handlePlaythroughMessage(CLEAR_SCREEN); // captures the cursor's message
        messages.splice(0, 5); // the capped tail the world editor emitted
        host.handlePlaythroughMessage(CLEAR_SCREEN); // taken for our own replay opening
        host.handlePlaythroughMessage(CLEAR_SCREEN); // which is what this one really is

        expect(host.playthroughResumeAnchor).toBe(10);
    });

    it("asks for nothing more once the mode is left", () => {
        const { host, sent, answered } = enterAndAdvanceTo(10);
        host.setPlaythroughActive(false);

        host.handlePlaythroughMessage(CLEAR_SCREEN);

        expect(starts(sent).length).toBe(1);
    });
});
