import { describe, it, expect } from "vitest";
import { fileURLToPath, URL } from "node:url";
import { lift, readSource } from "./helpers/liftMethod.js";

const source = readSource(
    fileURLToPath(new URL("../../src/components/SceneMessages.vue", import.meta.url)));

const VIEWPORT = 1080;
const APP_BAR = 48;
// the toolbar and the margins around it, below the message in the document
const TRAILING = 162;
// what is left of the screen for a message to be read in
const BAND = VIEWPORT - APP_BAR - TRAILING;
const MESSAGE_TOP = 1200;

// A page with the reveal cursor's message at MESSAGE_TOP and the sticky toolbar
// below it, scrolled by a window that clamps at the end of the document the way
// a browser does.
function page(messageHeight) {
    const documentHeight = MESSAGE_TOP + messageHeight + TRAILING;
    const win = {
        scrollY: 0,
        innerHeight: VIEWPORT,
        scrollTo: ({ top }) => {
            win.scrollY = Math.max(0, Math.min(top, documentHeight - VIEWPORT));
        },
    };
    const revealed = {
        offsetHeight: messageHeight,
        getBoundingClientRect: () => ({ top: MESSAGE_TOP - win.scrollY }),
    };
    const container = { lastElementChild: revealed };
    const doc = { documentElement: { scrollHeight: documentHeight } };
    const host = { $refs: { messageContainer: container } };
    host.appBarOffset = lift(source, "appBarOffset", "SceneMessages.vue", {
        getComputedStyle: () => ({ getPropertyValue: () => `${APP_BAR}px` }),
    }).bind(host);
    const scroll = lift(source, "scrollRevealIntoView", "SceneMessages.vue", {
        window: win, document: doc,
    });
    scroll.call(host);
    return { win, documentHeight, messageTopOnScreen: MESSAGE_TOP - win.scrollY };
}

describe("following the reveal cursor", () => {
    it("scrolls the page to its end, where the toolbar is not over the message", () => {
        const { win, documentHeight } = page(300);
        expect(win.scrollY).toBe(documentHeight - VIEWPORT);
    });

    it("starts a message too tall for the screen at its top, clear of the app bar", () => {
        expect(page(2000).messageTopOnScreen).toBe(APP_BAR);
    });

    it("starts a message taller than the reading band but shorter than the window at its top", () => {
        const messageHeight = BAND + 20;
        expect(messageHeight).toBeLessThan(VIEWPORT);
        expect(page(messageHeight).messageTopOnScreen).toBe(APP_BAR);
    });

    it("leaves a message that fits where the end of the page puts it", () => {
        const { messageTopOnScreen } = page(BAND - 20);
        expect(messageTopOnScreen).toBeGreaterThan(APP_BAR);
    });

    it("survives a list that has not rendered yet", () => {
        const scroll = lift(source, "scrollRevealIntoView", "SceneMessages.vue", {
            window: { innerHeight: VIEWPORT, scrollY: 0, scrollTo: () => {} },
            document: { documentElement: { scrollHeight: 0 } },
        });
        expect(() => scroll.call({ $refs: {} })).not.toThrow();
    });
});

describe("the app bar offset", () => {
    const appBarOffset = (value) => lift(source, "appBarOffset", "SceneMessages.vue", {
        getComputedStyle: () => ({ getPropertyValue: () => value }),
    }).call({ $refs: { messageContainer: {} } });

    it("reads vuetify's layout offset", () => {
        expect(appBarOffset("48px")).toBe(48);
    });

    it("covers nothing when the layout has not set one", () => {
        expect(appBarOffset("")).toBe(0);
    });
});
