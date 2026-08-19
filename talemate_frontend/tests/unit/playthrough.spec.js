import { describe, it, expect } from "vitest";
import {
    anchorForReveal,
    chunkIsAbandoned,
    chapterBoundaries,
    chapterLabel,
    clampReveal,
    currentChapter,
    INTRO_ANCHOR,
    revealForAnchor,
    speakRequest,
    visibleMessages,
} from "@/utils/playthrough";

const messages = [
    { id: 1, type: "narrator", text: "intro" },
    { id: 2, type: "character", text: "hello" },
    { id: 3, type: "time", text: "a day later", title: "The Reckoning" },
    { id: 4, type: "character", text: "back again" },
    { id: 5, type: "time", text: "an hour later" },
    { id: 6, type: "narrator", text: "the end" },
];

describe("visibleMessages", () => {
    it("renders the whole list when no cursor is set", () => {
        expect(visibleMessages(messages, null)).toHaveLength(6);
        expect(visibleMessages(messages, undefined)).toHaveLength(6);
    });

    it("reveals only up to the cursor", () => {
        expect(visibleMessages(messages, 2).map((m) => m.id)).toEqual([1, 2]);
    });

    it("shrinks again on a backward jump", () => {
        expect(visibleMessages(messages, 5)).toHaveLength(5);
        expect(visibleMessages(messages, 1)).toHaveLength(1);
    });

    it("never overshoots a list that has not fully arrived yet", () => {
        expect(visibleMessages(messages.slice(0, 3), 40)).toHaveLength(3);
    });

    it("survives an empty list", () => {
        expect(visibleMessages([], 1)).toEqual([]);
    });
});

describe("clampReveal", () => {
    it("keeps at least the first message revealed", () => {
        expect(clampReveal(0, 6)).toBe(1);
        expect(clampReveal(-3, 6)).toBe(1);
    });

    it("stops at the end of the list", () => {
        expect(clampReveal(99, 6)).toBe(6);
    });

    it("reports nothing to reveal for an empty list", () => {
        expect(clampReveal(1, 0)).toBe(0);
    });
});

describe("chapterBoundaries", () => {
    it("opens with the scene start and adds every time passage", () => {
        expect(chapterBoundaries(messages)).toEqual([
            { index: 0, title: null, text: null },
            { index: 2, title: "The Reckoning", text: "a day later" },
            { index: 4, title: null, text: "an hour later" },
        ]);
    });

    it("is just the scene start when nothing marks time", () => {
        expect(chapterBoundaries([{ id: 1, type: "narrator" }])).toEqual([
            { index: 0, title: null, text: null },
        ]);
    });
});

describe("chapterLabel", () => {
    const chapters = chapterBoundaries(messages);

    it("prefers the title", () => {
        expect(chapterLabel(chapters[1], 2)).toBe("The Reckoning");
    });

    it("falls back to the time text with its chapter number", () => {
        expect(chapterLabel(chapters[2], 3)).toBe("3. an hour later");
    });

    it("names the opening chapter", () => {
        expect(chapterLabel(chapters[0], 1)).toBe("1. Scene start");
    });
});

describe("currentChapter", () => {
    const chapters = chapterBoundaries(messages);

    it("stays in the opening chapter until the first time passage is revealed", () => {
        expect(currentChapter(chapters, 1)).toBe(0);
        expect(currentChapter(chapters, 2)).toBe(0);
    });

    it("moves on once the time passage itself is revealed", () => {
        expect(currentChapter(chapters, 3)).toBe(1);
        expect(currentChapter(chapters, 5)).toBe(2);
    });
});

describe("speakRequest", () => {
    const narrator = { id: 7, type: "narrator", text: "the wind rises" };

    it("asks the TTS agent for the revealed message", () => {
        expect(speakRequest(narrator, true)).toEqual({
            type: "tts",
            action: "generate_for_scene_message",
            message_id: 7,
        });
    });

    it("stays silent when the TTS agent is not available", () => {
        expect(speakRequest(narrator, false)).toBeNull();
    });

    it("skips message types the TTS agent refuses", () => {
        expect(speakRequest({ id: 1, type: "time", text: "a day later" }, true)).toBeNull();
        expect(speakRequest({ id: 2, type: "director", text: "do the thing" }, true)).toBeNull();
    });

    it("skips a cursor that points past the end of the list", () => {
        expect(speakRequest(null, true)).toBeNull();
    });
});

describe("speakRequest — the scene intro", () => {
    // the intro is emitted alongside the history without an id and is not
    // part of it; the backend knows it under a sentinel
    const intro = { id: undefined, type: "narrator", text: "the ministry's letter had been exact" };

    it("names the intro instead of sending a null id", () => {
        expect(speakRequest(intro, true)).toEqual({
            type: "tts",
            action: "generate_for_scene_message",
            message_id: "intro",
        });
    });

    it("does the same for an explicit null id", () => {
        expect(speakRequest({ ...intro, id: null }, true).message_id).toBe("intro");
    });

    it("stays silent for a message with no text to speak", () => {
        expect(speakRequest({ id: 4, type: "narrator", text: "" }, true)).toBeNull();
    });
});

describe("revealForAnchor", () => {
    it("resumes on the message the anchor names", () => {
        expect(revealForAnchor(messages, 3)).toBe(3);
        expect(revealForAnchor(messages, 6)).toBe(6);
    });

    it("has nothing to resume to when nothing was saved", () => {
        // null rather than 1: the caller must be able to tell "no saved
        // position" from "resume at the first message", or resolving a saved
        // position late would send the player back to the start
        expect(revealForAnchor(messages, null)).toBeNull();
        expect(revealForAnchor(messages, undefined)).toBeNull();
    });

    it("has nothing to resume to while the message has not arrived yet", () => {
        expect(revealForAnchor(messages.slice(0, 2), 6)).toBeNull();
    });

    it("has nothing to resume to when the message is gone from the history", () => {
        expect(revealForAnchor(messages, 999)).toBeNull();
    });

    it("follows the message rather than the index when history shifts", () => {
        // a message was inserted ahead of it, so its index moved
        const shifted = [{ id: 99, type: "narrator", text: "new" }, ...messages];
        expect(revealForAnchor(shifted, 3)).toBe(4);
    });
});

describe("anchorForReveal", () => {
    it("names the intro rather than reporting nothing to save", () => {
        // position 1 is the intro, which carries no id - without the sentinel
        // a Restart followed by an Exit would leave the old position saved
        expect(anchorForReveal([{ type: "narrator", text: "intro" }, ...messages], 1))
            .toBe(INTRO_ANCHOR);
    });

    it("resumes at the beginning from the intro sentinel", () => {
        expect(revealForAnchor(messages, INTRO_ANCHOR)).toBe(1);
    });

    it("reports nothing to save for an empty replay", () => {
        expect(anchorForReveal([], 1)).toBeNull();
    });

    it("names the message the cursor sits on", () => {
        expect(anchorForReveal(messages, 3)).toBe(3);
        expect(anchorForReveal(messages, 1)).toBe(1);
    });

    it("clamps a cursor past the end", () => {
        expect(anchorForReveal(messages, 999)).toBe(6);
    });

    it("has nothing to anchor to in an empty list", () => {
        expect(anchorForReveal([], 1)).toBeNull();
    });

    it("round-trips with revealForAnchor", () => {
        for (const reveal of [1, 2, 3, 4, 5, 6]) {
            expect(revealForAnchor(messages, anchorForReveal(messages, reveal))).toBe(reveal);
        }
    });
});

describe("chunkIsAbandoned", () => {
    it("drops a chunk of a narration the cursor moved on from", () => {
        expect(chunkIsAbandoned(4, [4])).toBe(true);
    });

    it("keeps the chunk it is waiting for", () => {
        expect(chunkIsAbandoned(5, [4])).toBe(false);
    });

    it("keeps audio that belongs to nobody in particular", () => {
        // the voice test in the agent settings sends no message id, and agent
        // settings stay usable during a playthrough
        expect(chunkIsAbandoned(null, [4])).toBe(false);
        expect(chunkIsAbandoned(undefined, [4])).toBe(false);
    });

    it("keeps a message played by hand while a narration is pending", () => {
        expect(chunkIsAbandoned(9, [4, "intro"])).toBe(false);
    });

    it("drops the intro sentinel like any other id", () => {
        expect(chunkIsAbandoned("intro", ["intro"])).toBe(true);
    });

    it("keeps everything when nothing was abandoned", () => {
        expect(chunkIsAbandoned(4, [])).toBe(false);
        expect(chunkIsAbandoned(4, undefined)).toBe(false);
    });
});
