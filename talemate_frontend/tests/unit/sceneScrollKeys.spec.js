// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { readFileSync } from "node:fs";
import { lift } from "./helpers/liftMethod.js";
import { forwardsScrollKey, forwardsWheel, scrollByKey, scrollByWheel } from "@/utils/sceneScroll";

const app = readFileSync("src/components/TalemateApp.vue", "utf-8");

let scroller;
beforeEach(() => {
    document.body.innerHTML = `
        <div class="v-app-bar"><button id="tab">Story</button><input id="search"><input id="number" type="number"></div>
        <div id="drawer"><input id="checkbox" type="checkbox"><input id="radio" type="radio"><input id="button" type="button"><select id="choice"></select><div id="editor" contenteditable="true"></div></div>
        <div id="scroller"><button id="inside">Fork</button><textarea id="message"></textarea></div>
        <div id="panel" style="overflow-y: auto"><span id="panel-text">client</span></div>
        <div id="still" style="overflow-y: auto"><span id="still-text">agent</span></div>
        <div class="v-overlay"><button id="menu-item">Item</button></div>`;
    // jsdom does no layout: the panel overflows, the other one does not
    const panel = document.getElementById("panel");
    Object.defineProperty(panel, "scrollHeight", { value: 900 });
    Object.defineProperty(panel, "clientHeight", { value: 300 });
    scroller = document.getElementById("scroller");
});
afterEach(() => {
    document.body.innerHTML = "";
});

function key(key, target, extra = {}) {
    return { key, target: document.getElementById(target) || document.body, defaultPrevented: false, ...extra };
}

describe("keys that scrolled the page scroll the story", () => {
    it("from the body", () => {
        for (const name of ["PageUp", "PageDown", "Home", "End", " ", "ArrowUp", "ArrowDown"]) {
            expect(forwardsScrollKey(key(name), scroller), name).toBe(true);
        }
    });

    it("from a focused button outside the story, for the page keys only", () => {
        expect(forwardsScrollKey(key("PageDown", "tab"), scroller)).toBe(true);
        expect(forwardsScrollKey(key(" ", "tab"), scroller)).toBe(false);
        expect(forwardsScrollKey(key("ArrowDown", "tab"), scroller)).toBe(false);
    });

    it("after a press on a part of the page that does not scroll", () => {
        const pressed = document.getElementById("still-text");
        expect(forwardsScrollKey(key("PageDown"), scroller, { pressed })).toBe(true);
    });

    it("but not other keys", () => {
        expect(forwardsScrollKey(key("a"), scroller)).toBe(false);
        expect(forwardsScrollKey(key("Enter"), scroller)).toBe(false);
    });
});

describe("keys from inputs that take no text scroll the story", () => {
    it("from a checkbox, a radio or an input button", () => {
        for (const id of ["checkbox", "radio", "button"]) {
            expect(forwardsScrollKey(key("PageDown", id), scroller), id).toBe(true);
        }
    });
});

describe("keys stay where something else takes them", () => {
    it("inside the story, where the browser scrolls it already", () => {
        expect(forwardsScrollKey(key("PageDown", "inside"), scroller)).toBe(false);
        expect(forwardsScrollKey(key("PageDown", "message"), scroller)).toBe(false);
        expect(forwardsScrollKey(key("PageDown"), scroller, { pressed: document.getElementById("inside") })).toBe(false);
    });

    it("in an element that takes text", () => {
        for (const id of ["search", "number", "choice", "editor"]) {
            expect(forwardsScrollKey(key("Home", id), scroller), id).toBe(false);
        }
    });

    it("in a menu", () => {
        expect(forwardsScrollKey(key("PageDown", "menu-item"), scroller)).toBe(false);
    });

    it("in another panel that scrolls", () => {
        const pressed = document.getElementById("panel-text");
        expect(forwardsScrollKey(key("PageDown", "panel-text"), scroller)).toBe(false);
        expect(forwardsScrollKey(key("PageDown"), scroller, { pressed })).toBe(false);
    });

    it("when a handler already took the key, or with a modifier", () => {
        expect(forwardsScrollKey(key("End", "tab", { defaultPrevented: true }), scroller)).toBe(false);
        expect(forwardsScrollKey(key("PageDown", null, { ctrlKey: true }), scroller)).toBe(false);
        expect(forwardsScrollKey(key("PageDown", null, { altKey: true }), scroller)).toBe(false);
        expect(forwardsScrollKey(key("PageDown", null, { metaKey: true }), scroller)).toBe(false);
    });

    it("Space while replay answers it", () => {
        expect(forwardsScrollKey(key(" "), scroller, { spaceTaken: true })).toBe(false);
        expect(forwardsScrollKey(key("PageDown"), scroller, { spaceTaken: true })).toBe(true);
    });

    it("from a pressed element that left the page", () => {
        const pressed = document.getElementById("inside");
        pressed.remove();
        expect(forwardsScrollKey(key("PageDown"), scroller, { pressed })).toBe(true);
    });
});

describe("scrollByKey", () => {
    // browsers that animate key scrolls report scrollend; jsdom does not
    beforeEach(() => { window.onscrollend = null; });
    afterEach(() => { delete window.onscrollend; });

    // an instant scroll lands at once; a smooth one keeps running, with
    // scrollTop where it was, until the test moves or ends it
    function target(scrollTop = 0) {
        const listeners = {};
        const fire = (type) => (listeners[type] || []).forEach((fn) => fn());
        const el = {
            clientHeight: 1000,
            scrollHeight: 9000,
            scrollTop,
            scrollTo: vi.fn(({ top, behavior }) => {
                if (behavior === "auto") el.scrollTop = top;
            }),
            scrollBy: vi.fn(({ top }) => { el.scrollTop += top; }),
            addEventListener: vi.fn((type, fn) => (listeners[type] ||= []).push(fn)),
            moveTo(at) { el.scrollTop = at; fire("scroll"); },
            endScroll(at) { el.moveTo(at); fire("scrollend"); },
            fire,
        };
        return el;
    }
    const tops = (el) => el.scrollTo.mock.calls.map(([options]) => options.top);

    it("pages by the browser's own step", () => {
        for (const [press, top] of [[{ key: "PageDown" }, 2875], [{ key: "PageUp" }, 1125], [{ key: " " }, 2875], [{ key: " ", shiftKey: true }, 1125]]) {
            const el = target(2000);
            scrollByKey(el, press);
            expect(tops(el), press.key).toEqual([top]);
        }
    });

    it("steps a line with the arrows", () => {
        const down = target(2000);
        scrollByKey(down, { key: "ArrowDown" });
        const up = target(2000);
        scrollByKey(up, { key: "ArrowUp" });
        expect([...tops(down), ...tops(up)]).toEqual([2040, 1960]);
    });

    it("goes to either end with Home and End", () => {
        const el = target(2000);
        scrollByKey(el, { key: "Home" });
        el.endScroll(0);
        scrollByKey(el, { key: "End" });
        expect(tops(el)).toEqual([0, 8000]);
    });

    it("steps on from where a running scroll is headed, however long it runs", () => {
        const el = target();
        scrollByKey(el, { key: "End" });
        el.moveTo(3000);
        scrollByKey(el, { key: "PageUp" });
        el.moveTo(5000);
        scrollByKey(el, { key: "ArrowUp", repeat: true });
        scrollByKey(el, { key: "ArrowUp", repeat: true });
        expect(tops(el)).toEqual([8000, 7125, 7085, 7045]);
    });

    it("steps from the position once the scroll has ended", () => {
        const el = target();
        scrollByKey(el, { key: "PageDown" });
        el.endScroll(300);
        scrollByKey(el, { key: "ArrowDown" });
        expect(tops(el)).toEqual([875, 340]);
    });

    it("forgets the target when the reader scrolls the story", () => {
        for (const type of ["wheel", "pointerdown", "touchstart"]) {
            const el = target();
            scrollByKey(el, { key: "End" });
            el.moveTo(922);
            el.fire(type);
            scrollByKey(el, { key: "PageUp" });
            expect(tops(el), type).toEqual([8000, 47]);
        }
    });

    it("forgets the target when something else scrolls the story away from it", () => {
        const el = target(6000);
        scrollByKey(el, { key: "ArrowUp" });
        el.moveTo(5990);
        el.moveTo(7000);
        scrollByKey(el, { key: "ArrowUp" });
        expect(tops(el)).toEqual([5960, 6960]);
    });

    it("forgets the target when a forwarded wheel turn scrolls the story", () => {
        const el = target();
        scrollByKey(el, { key: "End" });
        el.moveTo(1000);
        scrollByWheel(el, { deltaY: -100, deltaMode: WheelEvent.DOM_DELTA_PIXEL });
        scrollByKey(el, { key: "ArrowDown" });
        expect(tops(el)).toEqual([8000, 940]);
    });

    it("stays inside the story", () => {
        const el = target(7900);
        scrollByKey(el, { key: "PageDown" });
        el.endScroll(8000);
        scrollByKey(el, { key: "ArrowUp" });
        el.endScroll(7960);
        const top = target(20);
        scrollByKey(top, { key: "PageUp" });
        expect([...tops(el), ...tops(top)]).toEqual([8000, 7960, 0]);
    });

    it("animates a single press and steps a held key at once", () => {
        const el = target(2000);
        scrollByKey(el, { key: "ArrowDown" });
        scrollByKey(el, { key: "ArrowDown", repeat: true });
        expect(el.scrollTo.mock.calls.map(([options]) => options.behavior)).toEqual(["smooth", "auto"]);
    });

    it("steps at once where scrollend is missing", () => {
        delete window.onscrollend;
        const el = target(2000);
        scrollByKey(el, { key: "PageDown" });
        scrollByKey(el, { key: "PageDown" });
        expect(el.scrollTo.mock.calls.map(([options]) => [options.top, options.behavior])).toEqual([[2875, "auto"], [3750, "auto"]]);
    });
});

describe("forwardsWheel", () => {
    function wheel(target, deltaY, extra = {}) {
        return { target: document.getElementById(target), deltaY, deltaMode: 0, defaultPrevented: false, ctrlKey: false, ...extra };
    }

    it("scrolls the story from the app bar and from panels that do not scroll", () => {
        expect(forwardsWheel(wheel("tab", 100), scroller)).toBe(true);
        expect(forwardsWheel(wheel("still-text", -100), scroller)).toBe(true);
    });

    it("leaves the story to the browser", () => {
        expect(forwardsWheel(wheel("inside", 100), scroller)).toBe(false);
    });

    it("leaves a panel that can still scroll that way, and passes on one at its end", () => {
        expect(forwardsWheel(wheel("panel-text", 100), scroller)).toBe(false);
        expect(forwardsWheel(wheel("panel-text", -100), scroller)).toBe(true);
    });

    it("leaves menus, zoom and handled turns alone", () => {
        expect(forwardsWheel(wheel("menu-item", 100), scroller)).toBe(false);
        expect(forwardsWheel(wheel("tab", 100, { ctrlKey: true }), scroller)).toBe(false);
        expect(forwardsWheel(wheel("tab", 100, { defaultPrevented: true }), scroller)).toBe(false);
        expect(forwardsWheel(wheel("tab", 0), scroller)).toBe(false);
    });
});

describe("scrollByWheel", () => {
    it("turns lines and pages into pixels", () => {
        const el = { clientHeight: 1000, scrollBy: vi.fn() };
        scrollByWheel(el, { deltaY: 120, deltaMode: WheelEvent.DOM_DELTA_PIXEL });
        scrollByWheel(el, { deltaY: 3, deltaMode: WheelEvent.DOM_DELTA_LINE });
        scrollByWheel(el, { deltaY: -1, deltaMode: WheelEvent.DOM_DELTA_PAGE });
        expect(el.scrollBy.mock.calls.map(([options]) => options.top)).toEqual([120, 120, -1000]);
    });
});

describe("replay's hold on Space", () => {
    const mixin = readFileSync("src/components/PlaythroughMixin.js", "utf-8");
    const takesSpace = lift(mixin, "playthroughTakesSpace", "PlaythroughMixin.js");
    const state = (extra) => ({ playthroughActive: true, busy: false, playthroughRevealCount: 3, playthroughMessageCount: 10, ...extra });

    it("holds Space while replay would advance on it", () => {
        expect(takesSpace.call(state())).toBe(true);
    });

    it("lets Space scroll while replay is busy, at its end, or off", () => {
        expect(takesSpace.call(state({ busy: true }))).toBe(false);
        expect(takesSpace.call(state({ playthroughRevealCount: 10 }))).toBe(false);
        expect(takesSpace.call(state({ playthroughActive: false }))).toBe(false);
    });
});

describe("the app's key handler", () => {
    function handler(vm) {
        const forwards = vi.fn(() => true);
        const scroll = vi.fn();
        const run = lift(app, "onDocumentKeydown", "TalemateApp.vue", { forwardsScrollKey: forwards, scrollByKey: scroll });
        return { forwards, scroll, run: (event) => run.call(vm, event) };
    }

    it("scrolls the story only while it is shown", () => {
        const event = { preventDefault: vi.fn() };
        const away = handler({ tab: "world", $refs: { sceneScroller: {} } });
        away.run(event);
        expect(away.scroll).not.toHaveBeenCalled();

        const pressed = {};
        const shown = handler({ tab: "main", $refs: { sceneScroller: {} }, playthroughTakesSpace: true, _lastPressed: pressed });
        shown.run(event);
        expect(shown.forwards).toHaveBeenCalledWith(event, {}, { spaceTaken: true, pressed });
        expect(event.preventDefault).toHaveBeenCalled();
        expect(shown.scroll).toHaveBeenCalledWith({}, event);
    });

    it("forwards wheel turns only while the story is shown", () => {
        const forwards = vi.fn(() => true);
        const scroll = vi.fn();
        const run = lift(app, "onDocumentWheel", "TalemateApp.vue", { forwardsWheel: forwards, scrollByWheel: scroll });
        const event = {};
        run.call({ tab: "settings", $refs: { sceneScroller: {} } }, event);
        expect(scroll).not.toHaveBeenCalled();
        run.call({ tab: "main", $refs: { sceneScroller: {} } }, event);
        expect(scroll).toHaveBeenCalledWith({}, event);
    });
});
