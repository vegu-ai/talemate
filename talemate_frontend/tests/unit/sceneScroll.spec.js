import { describe, it, expect, vi } from "vitest";
import { fileURLToPath, URL } from "node:url";
import { lift, readSource } from "./helpers/liftMethod.js";
import { AT_BOTTOM_SLACK, offsetAtBottom, setBottomOffset } from "../../src/utils/sceneScroll.js";

const app = readSource(fileURLToPath(new URL("../../src/components/TalemateApp.vue", import.meta.url)));

// A scroller that clamps its scrollTop the way a browser does; `grow` adds
// content below, as a message arriving does.
function scroller({ content = 5000, height = 1000, top = 0 } = {}) {
    let scrollTop = top;
    const el = {
        scrollHeight: content,
        clientHeight: height,
        get scrollTop() { return scrollTop; },
        set scrollTop(value) { scrollTop = Math.max(0, Math.min(value, el.scrollHeight - el.clientHeight)); },
        grow(by) { el.scrollHeight += by; },
    };
    return el;
}

function host(el) {
    const vm = { $refs: { sceneScroller: el }, sceneBottomOffset: null };
    vm.rememberSceneBottom = lift(app, "rememberSceneBottom", "TalemateApp.vue", { offsetAtBottom }).bind(vm);
    vm.followSceneBottom = lift(app, "followSceneBottom", "TalemateApp.vue", { setBottomOffset }).bind(vm);
    return vm;
}

describe("offsetAtBottom", () => {
    it("measures the distance from the bottom", () => {
        expect(offsetAtBottom(scroller({ top: 4000 }))).toBe(0);
        expect(offsetAtBottom(scroller({ top: 3984 }))).toBe(16);
    });

    it("is null once the reader is further up than the slack", () => {
        expect(offsetAtBottom(scroller({ top: 4000 - AT_BOTTOM_SLACK }))).toBe(AT_BOTTOM_SLACK);
        expect(offsetAtBottom(scroller({ top: 4000 - AT_BOTTOM_SLACK - 1 }))).toBeNull();
        expect(offsetAtBottom(scroller({ top: 2000 }))).toBeNull();
    });

    it("counts a story shorter than its scroller as at the bottom", () => {
        expect(offsetAtBottom(scroller({ content: 600 }))).toBe(0);
    });
});

describe("setBottomOffset", () => {
    it("puts the scroller that far above its bottom", () => {
        const el = scroller();
        setBottomOffset(el, 16);
        expect(el.scrollTop).toBe(3984);
    });
});

describe("returning to the story", () => {
    it("follows what arrived while away when the story was left at the bottom", () => {
        const el = scroller({ top: 3984 });
        const vm = host(el);
        vm.rememberSceneBottom();
        el.grow(300);
        vm.followSceneBottom();
        expect(el.scrollTop).toBe(4284);
        expect(vm.sceneBottomOffset).toBeNull();
    });

    it("does not move a story left at the bottom when nothing arrived", () => {
        const el = scroller({ top: 3984 });
        const vm = host(el);
        vm.rememberSceneBottom();
        vm.followSceneBottom();
        expect(el.scrollTop).toBe(3984);
    });

    it("leaves a story left anywhere else where it was", () => {
        const el = scroller({ top: 2000 });
        const vm = host(el);
        vm.rememberSceneBottom();
        expect(vm.sceneBottomOffset).toBeNull();
        el.grow(300);
        el.scrollTop = 2000;
        const set = vi.spyOn(el, "scrollTop", "set");
        vm.followSceneBottom();
        expect(set).not.toHaveBeenCalled();
        expect(el.scrollTop).toBe(2000);
    });
});

describe("the tab watcher", () => {
    // the watcher's handler, lifted from the `tab:` block so another watcher's
    // handler cannot match first
    const tabWatcher = app.slice(app.indexOf("    tab: {"));
    function watch(oldTab, newTab) {
        const root = { classList: { toggle: vi.fn() } };
        const vm = {
            guardUnsavedSettings: () => false,
            flushPendingTemplateSelection: vi.fn(),
            onNodeEditorContainerResize: vi.fn(),
            rememberSceneBottom: vi.fn(),
            followSceneBottom: vi.fn(),
            $nextTick: (fn) => fn(),
        };
        const handler = lift(tabWatcher, "handler", "TalemateApp.vue tab watcher", {
            debounce: (fn) => fn,
            document: { documentElement: root },
        });
        handler.call(vm, newTab, oldTab);
        return { vm, root };
    }

    it("remembers the story's bottom on the way out", () => {
        const { vm } = watch("main", "world");
        expect(vm.rememberSceneBottom).toHaveBeenCalledOnce();
        expect(vm.followSceneBottom).not.toHaveBeenCalled();
    });

    it("follows the bottom on the way back in", () => {
        const { vm } = watch("world", "main");
        expect(vm.followSceneBottom).toHaveBeenCalledOnce();
        expect(vm.rememberSceneBottom).not.toHaveBeenCalled();
    });

    it("drops the page's scrollbar track only while the story is shown", () => {
        expect(watch("home", "main").root.classList.toggle).toHaveBeenCalledWith("story-shown", true);
        expect(watch("main", "home").root.classList.toggle).toHaveBeenCalledWith("story-shown", false);
        expect(watch("world", "settings").root.classList.toggle).toHaveBeenCalledWith("story-shown", false);
    });

    it("leaves everything alone when the unsaved-settings guard holds the view", () => {
        const root = { classList: { toggle: vi.fn() } };
        const vm = { guardUnsavedSettings: () => true, rememberSceneBottom: vi.fn(), followSceneBottom: vi.fn() };
        lift(tabWatcher, "handler", "TalemateApp.vue tab watcher", { document: { documentElement: root } }).call(vm, "main", "settings");
        expect(vm.rememberSceneBottom).not.toHaveBeenCalled();
        expect(root.classList.toggle).not.toHaveBeenCalled();
    });
});

describe("the Story tab", () => {
    function click(committedTab) {
        const scrollIntoView = vi.fn();
        const vm = {
            committedTab,
            $refs: { sceneMessageInput: { scrollIntoView } },
            $nextTick: (fn) => fn(),
        };
        lift(app, "onStoryTabClick", "TalemateApp.vue").call(vm);
        return scrollIntoView;
    }

    it("jumps to the newest message when clicked while on the story", () => {
        expect(click("main")).toHaveBeenCalledWith(false);
    });

    it("keeps the story where it was when clicked from another tab", () => {
        expect(click("world")).not.toHaveBeenCalled();
        expect(click("settings")).not.toHaveBeenCalled();
    });
});
