import { describe, it, expect, vi } from "vitest";
import PlaythroughMixin from "@/components/PlaythroughMixin.js";

// The mixin is a plain options object, so a fake host is enough to drive the
// fork - no component mount. The first message is the scene intro, which the
// backend emits without an id.
function makeHost({ immutable = false, savedAnchor = null, tts = false } = {}) {
    const messages = [
        { type: "narrator", text: "the intro" },
        ...Array.from({ length: 5 }, (_, index) => ({
            id: index + 1,
            type: "narrator",
            text: `message ${index + 1}`,
        })),
        { id: 6, type: "time", text: "an hour later" },
        { id: 7, type: "context_investigation", text: "what the ledger said" },
    ];
    const sent = [];
    const host = {
        ...PlaythroughMixin.data(),
        websocket: { send: (frame) => sent.push(JSON.parse(frame)) },
        $refs: {
            sceneMessages: { messages, messageAt: (index) => messages[index] || null },
            audioQueue: { stopAndClear: vi.fn() },
        },
        scene: {
            data: { immutable_save: immutable, playthrough_progress: savedAnchor },
        },
        agentStatus: tts ? { tts: { available: true } } : {},
        scrollInputIntoView: vi.fn(),
        $nextTick: (fn) => fn && fn(),
    };
    for (const [name, method] of Object.entries(PlaythroughMixin.methods)) {
        host[name] = method.bind(host);
    }
    for (const [name, getter] of Object.entries(PlaythroughMixin.computed || {})) {
        Object.defineProperty(host, name, { get: getter.bind(host) });
    }
    host.playthroughActive = true;
    host.playthroughMessageCount = messages.length;
    return { host, sent, messages };
}

const forks = (sent) =>
    sent.filter((frame) => frame.type === "assistant" && frame.action === "fork_new_scene");

const progressSaves = (sent) =>
    sent.filter((frame) => frame.type === "playthrough" && frame.action === "save_progress");

const speakRequests = (sent) =>
    sent.filter((frame) => frame.type === "tts");

const finishFork = (host, frame, error = null) => host.handlePlaythroughMessage({
    type: "assistant",
    action: "operation_done",
    request_id: frame.request_id,
    ...(error ? { error: { message: error } } : { data: {} }),
});

describe("forking from a playthrough", () => {
    it("forks at the message the toolbar asked for the name at", () => {
        const { host, sent } = makeHost();
        host.setPlaythroughReveal(4);

        host.forkPlaythrough("a new save", host.playthroughForkTarget().id);

        expect(forks(sent)).toEqual([{
            type: "assistant",
            action: "fork_new_scene",
            message_id: 3,
            save_name: "a new save",
            request_id: expect.any(String),
        }]);
    });

    it("does not follow the cursor the pacing moved while the name was typed", () => {
        // auto-advance and narration keep stepping behind the modal; the fork
        // belongs to the message the reader picked, not to where they ended up
        const { host, sent } = makeHost();
        host.setPlaythroughReveal(4);
        const picked = host.playthroughForkTarget().id;
        host.setPlaythroughReveal(6);

        host.forkPlaythrough("a new save", picked);
        finishFork(host, forks(sent)[0]);

        expect(forks(sent)[0].message_id).toBe(3);
        expect(progressSaves(sent)[0].message_id).toBe(3);
    });

    it("records the position on the source scene, as leaving does", () => {
        const { host, sent } = makeHost();
        host.setPlaythroughReveal(4);

        host.forkPlaythrough("a new save", 3);
        finishFork(host, forks(sent)[0]);

        expect(progressSaves(sent)).toEqual([{
            type: "playthrough",
            action: "save_progress",
            message_id: 3,
        }]);
    });

    it("leaves a read-only scene without a position to record", () => {
        const { host, sent } = makeHost({ immutable: true });
        host.setPlaythroughReveal(4);

        host.forkPlaythrough("a new save", 3);

        expect(progressSaves(sent)).toEqual([]);
        expect(forks(sent).length).toBe(1);
    });

    it("leaves the mode only after the accepted fork completes", () => {
        const { host, sent } = makeHost();
        host.setPlaythroughReveal(4);

        host.forkPlaythrough("a new save", 3);
        expect(host.playthroughActive).toBe(true);
        finishFork(host, forks(sent)[0]);

        expect(host.playthroughActive).toBe(false);
    });

    it("keeps the mode and dialog state alive for a refused name, then retries", () => {
        const { host, sent } = makeHost();
        host.setPlaythroughReveal(4);
        host.promptPlaythroughFork();
        host.forkPlaythrough("taken", 3);
        const firstFork = forks(sent)[0];

        expect(host.playthroughPaused).toBe(true);
        expect(finishFork(host, firstFork, "A save named 'taken' already exists")).toBe(true);
        expect(host.playthroughActive).toBe(true);
        expect(host.playthroughPaused).toBe(true);
        expect(host.playthroughForkRequestId).toBeNull();
        expect(host.playthroughForkError).toContain("already exists");

        host.forkPlaythrough("available", 3);
        const secondFork = forks(sent)[1];
        expect(secondFork.request_id).not.toBe(firstFork.request_id);
        expect(host.playthroughForkError).toBe("");
        expect(finishFork(host, secondFork)).toBe(true);
        expect(host.playthroughActive).toBe(false);
        expect(progressSaves(sent).at(-1).message_id).toBe(3);
    });

    it("ignores another caller's completion", () => {
        const { host, sent } = makeHost();
        host.forkPlaythrough("a new save", 3);
        const pending = forks(sent)[0];

        expect(host.handlePlaythroughMessage({
            type: "assistant",
            action: "operation_done",
            request_id: "another-request",
            error: { message: "ignore me" },
        })).toBe(false);
        expect(host.playthroughForkRequestId).toBe(pending.request_id);
        expect(host.playthroughActive).toBe(true);
    });

    it("has nothing to fork from while the cursor is on the scene intro", () => {
        const { host, sent } = makeHost();

        expect(host.playthroughForkTarget()).toBe(null);
        host.forkPlaythrough("a new save", null);

        expect(forks(sent)).toEqual([]);
        expect(host.playthroughActive).toBe(true);
    });

    it("offers nothing to fork at the types the scene view has no Fork on", () => {
        // a time passage carries no revision of its own, and a context
        // investigation is not even sent with one - the revision gate cannot
        // see that forking there would silently fall back to a shallow copy
        const { host } = makeHost();

        host.setPlaythroughReveal(7);
        expect(host.playthroughForkTarget()).toBe(null);

        host.setPlaythroughReveal(8);
        expect(host.playthroughForkTarget()).toBe(null);
    });

    it("offers the message the cursor is on as the fork target", () => {
        const { host, messages } = makeHost();
        host.setPlaythroughReveal(2);

        expect(host.playthroughForkTarget()).toBe(messages[1]);
    });
});

describe("pacing while the fork dialog is open", () => {
    it("holds the cursor still", () => {
        vi.useFakeTimers();
        try {
            const { host } = makeHost();
            host.playthroughAutoAdvance = true;
            host.setPlaythroughReveal(3);

            host.pausePlaythroughPacing();
            vi.advanceTimersByTime(60000);

            expect(host.playthroughRevealCount).toBe(3);
        } finally {
            vi.useRealTimers();
        }
    });

    it("picks the pacing back up when the reader backs out", () => {
        vi.useFakeTimers();
        try {
            const { host } = makeHost();
            host.playthroughAutoAdvance = true;
            host.setPlaythroughReveal(3);

            host.pausePlaythroughPacing();
            host.resumePlaythroughPacing();
            vi.advanceTimersByTime(60000);

            expect(host.playthroughRevealCount).toBeGreaterThan(3);
        } finally {
            vi.useRealTimers();
        }
    });

    it("leaves the narration that is playing alone", () => {
        vi.useFakeTimers();
        try {
            const { host, sent } = makeHost({ tts: true });
            host.setPlaythroughReveal(3);
            vi.advanceTimersByTime(1000); // past the narration debounce
            expect(speakRequests(sent).length).toBe(1);

            // the reveal that started the narration cleared the queue on its
            // way in; what this pins is what the pause does after that
            host.$refs.audioQueue.stopAndClear.mockClear();
            host.pausePlaythroughPacing();
            host.resumePlaythroughPacing();

            // cutting the audio and asking for it again is what the reader
            // would hear as the fork dialog restarting the message
            expect(host.$refs.audioQueue.stopAndClear).not.toHaveBeenCalled();
            expect(host.playthroughStaleMessageIds).toEqual([]);
            expect(speakRequests(sent).length).toBe(1);
        } finally {
            vi.useRealTimers();
        }
    });

    it("does not let a narration that ends behind the dialog step the cursor", () => {
        vi.useFakeTimers();
        try {
            const { host } = makeHost({ tts: true });
            host.playthroughAutoAdvance = true;
            host.setPlaythroughReveal(3);
            vi.advanceTimersByTime(1000);
            const awaited = host.playthroughAwaitedMessageId;

            host.pausePlaythroughPacing();
            host.onPlaythroughMessageSpoken(awaited);
            expect(host.playthroughRevealCount).toBe(3);

            // and the step it was holding is not lost
            host.resumePlaythroughPacing();
            vi.advanceTimersByTime(60000);
            expect(host.playthroughRevealCount).toBeGreaterThan(3);
        } finally {
            vi.useRealTimers();
        }
    });
});
