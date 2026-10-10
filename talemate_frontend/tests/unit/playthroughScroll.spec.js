import { describe, it, expect } from "vitest";
import { fileURLToPath, URL } from "node:url";
import { lift, readSource } from "./helpers/liftMethod.js";

const source = readSource(
    fileURLToPath(new URL("../../src/components/SceneMessages.vue", import.meta.url)));

// the story's scroller, below a 48px app bar
const SCROLLER_TOP = 48;
const SCROLLER_HEIGHT = 1032;
// the toolbar and the margins around it, below the message in the story
const TRAILING = 162;
// what is left of the scroller for a message to be read in
const BAND = SCROLLER_HEIGHT - TRAILING;
const MESSAGE_TOP = 1200;

// A story with the reveal cursor's message at MESSAGE_TOP and the sticky
// toolbar below it, in a scroller that clamps its scrollTop the way a browser
// does.
function story(messageHeight) {
    const contentHeight = MESSAGE_TOP + messageHeight + TRAILING;
    let scrollTop = 0;
    const scroller = {
        scrollHeight: contentHeight,
        clientHeight: SCROLLER_HEIGHT,
        get scrollTop() { return scrollTop; },
        set scrollTop(value) { scrollTop = Math.max(0, Math.min(value, contentHeight - SCROLLER_HEIGHT)); },
        getBoundingClientRect: () => ({ top: SCROLLER_TOP }),
    };
    const revealed = {
        getBoundingClientRect: () => ({ top: SCROLLER_TOP + MESSAGE_TOP - scroller.scrollTop }),
    };
    const host = {
        $refs: { messageContainer: { lastElementChild: revealed } },
        sceneScroller: () => scroller,
    };
    lift(source, "scrollRevealIntoView", "SceneMessages.vue").call(host);
    return { scroller, contentHeight, messageTopInScroller: MESSAGE_TOP - scroller.scrollTop };
}

describe("following the reveal cursor", () => {
    it("scrolls the story to its end, where the toolbar is not over the message", () => {
        const { scroller, contentHeight } = story(300);
        expect(scroller.scrollTop).toBe(contentHeight - SCROLLER_HEIGHT);
    });

    it("starts a message too tall for the scroller at its top", () => {
        expect(story(2000).messageTopInScroller).toBe(0);
    });

    it("starts a message taller than the reading band but shorter than the scroller at its top", () => {
        const messageHeight = BAND + 20;
        expect(messageHeight).toBeLessThan(SCROLLER_HEIGHT);
        expect(story(messageHeight).messageTopInScroller).toBe(0);
    });

    it("leaves a message that fits where the end of the story puts it", () => {
        expect(story(BAND - 20).messageTopInScroller).toBeGreaterThan(0);
    });

    it("survives a list that has not rendered yet", () => {
        const scroll = lift(source, "scrollRevealIntoView", "SceneMessages.vue");
        expect(() => scroll.call({ $refs: {}, sceneScroller: () => ({}) })).not.toThrow();
    });
});
