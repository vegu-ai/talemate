// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
    clipboardImageFile,
    isEditableTarget,
    isElementReachable,
    registerImagePasteTarget,
    selectPasteTarget,
} from "@/utils/imagePaste";

const unregisters = [];

// jsdom lays nothing out and implements no hit test, so the layout is modelled
// here: `painted` is paint order, last on top, `clipped` holds the scrollports,
// and elementFromPoint answers from both the way a browser would.
let painted = [];
let clipped = [];

const inside = (rect, x, y) => x >= rect.left && x < rect.right && y >= rect.top && y < rect.bottom;

beforeEach(() => {
    painted = [];
    clipped = [];
    document.elementFromPoint = (x, y) => {
        for (let i = painted.length - 1; i >= 0; i--) {
            const el = painted[i];
            if (!inside(el.getBoundingClientRect(), x, y)) continue;
            const outOfPort = clipped.some(
                (port) => port !== el && port.contains(el) && !inside(port.getBoundingClientRect(), x, y)
            );
            if (outOfPort) continue;
            return el;
        }
        return null;
    };
});

afterEach(() => {
    while (unregisters.length) unregisters.pop()();
    document.body.innerHTML = "";
});

const FULL_SCREEN = { left: 0, top: 0, right: 1024, bottom: 768 };

function place(el, rect) {
    el.getBoundingClientRect = () => ({
        ...rect,
        width: rect.right - rect.left,
        height: rect.bottom - rect.top,
    });
    painted.push(el);
    return el;
}

function cover(rect = FULL_SCREEN) {
    // what a dialog scrim or an open temporary navigation drawer puts over the
    // page: it takes the hit, and changes nothing about what is underneath
    const el = document.createElement("div");
    document.body.appendChild(el);
    return place(el, rect);
}

function scrollport(rect) {
    const el = document.createElement("div");
    el.style.overflowY = "auto";
    document.body.appendChild(el);
    place(el, rect);
    for (const [prop, value] of [
        ["clientLeft", 0],
        ["clientTop", 0],
        ["clientWidth", rect.right - rect.left],
        ["clientHeight", rect.bottom - rect.top],
    ]) {
        Object.defineProperty(el, prop, { value, configurable: true });
    }
    clipped.push(el);
    return el;
}

function zone(options = {}) {
    const {
        parent = document.body,
        enabled = true,
        handler = vi.fn(),
        rect = { left: 0, top: 0, right: 200, bottom: 200 },
        paint = true,
    } = options;
    const el = document.createElement("div");
    el.tabIndex = 0;
    parent.appendChild(el);
    el.getBoundingClientRect = () => ({
        ...rect,
        width: rect.right - rect.left,
        height: rect.bottom - rect.top,
    });
    if (paint) place(el, rect);
    return { el, handler, isEnabled: () => enabled, getElement: () => el };
}

function register(target) {
    const unregister = registerImagePasteTarget(target);
    unregisters.push(unregister);
    return unregister;
}

function imageFile(name = "pasted.png") {
    return new File(["binary"], name, { type: "image/png" });
}

function clipboard({ files = [], items = [] } = {}) {
    return { files, items };
}

function paste(clipboardData, target = document.body) {
    const event = new Event("paste", { bubbles: true, cancelable: true });
    Object.defineProperty(event, "clipboardData", { value: clipboardData });
    target.dispatchEvent(event);
    return event;
}

describe("clipboardImageFile", () => {
    it("takes the first image from clipboardData.files", () => {
        const file = imageFile();
        expect(clipboardImageFile(clipboard({ files: [file] }))).toBe(file);
    });

    it("falls back to a file item when files is empty", () => {
        const file = imageFile();
        const items = [
            { kind: "string", type: "text/plain", getAsFile: () => null },
            { kind: "file", type: "image/png", getAsFile: () => file },
        ];
        expect(clipboardImageFile(clipboard({ items }))).toBe(file);
    });

    it("ignores a clipboard that carries no image", () => {
        const items = [{ kind: "string", type: "text/plain", getAsFile: () => null }];
        expect(clipboardImageFile(clipboard({ items }))).toBeNull();
        expect(clipboardImageFile(clipboard())).toBeNull();
        expect(clipboardImageFile(null)).toBeNull();
    });

    it("ignores a non-image file", () => {
        const zipped = new File(["binary"], "scene.zip", { type: "application/zip" });
        expect(clipboardImageFile(clipboard({ files: [zipped] }))).toBeNull();
    });
});

describe("isEditableTarget", () => {
    it("recognizes the elements that take a paste of their own", () => {
        const editable = document.createElement("div");
        editable.setAttribute("contenteditable", "true");
        document.body.appendChild(editable);

        // what vue-codemirror renders: the editable surface carries the
        // attribute, the paste lands on a line inside it
        const codeEditor = document.createElement("div");
        codeEditor.className = "cm-content";
        codeEditor.setAttribute("contenteditable", "true");
        const codeLine = document.createElement("span");
        codeEditor.appendChild(codeLine);
        document.body.appendChild(codeEditor);

        expect(isEditableTarget(document.createElement("input"))).toBe(true);
        expect(isEditableTarget(document.createElement("textarea"))).toBe(true);
        expect(isEditableTarget(document.createElement("select"))).toBe(true);
        expect(isEditableTarget(editable)).toBe(true);
        expect(isEditableTarget(codeLine)).toBe(true);
        expect(isEditableTarget(document.body)).toBe(false);
        expect(isEditableTarget(null)).toBe(false);
    });
});

describe("isElementReachable", () => {
    it("rejects an element that is not in the document", () => {
        expect(isElementReachable(document.createElement("div"))).toBe(false);
        expect(isElementReachable(null)).toBe(false);
    });

    it("rejects an element inside an inert subtree", () => {
        const drawer = document.createElement("div");
        drawer.setAttribute("inert", "");
        document.body.appendChild(drawer);
        const child = zone({ parent: drawer });

        expect(isElementReachable(child.el)).toBe(false);
    });

    it("rejects an element that is not drawn", () => {
        const hidden = zone({ rect: { left: 0, top: 0, right: 0, bottom: 0 }, paint: false });
        expect(isElementReachable(hidden.el)).toBe(false);
    });

    it("rejects an element outside the viewport", () => {
        const offScreen = zone({ rect: { left: -400, top: 0, right: -100, bottom: 300 } });
        expect(isElementReachable(offScreen.el)).toBe(false);
    });

    it("rejects an element under a surface that covers the page", () => {
        const panel = zone();
        cover();
        expect(isElementReachable(panel.el)).toBe(false);
    });

    it("accepts an element drawn over that surface", () => {
        cover();
        const drawer = zone({ rect: { left: 0, top: 0, right: 300, bottom: 768 } });
        expect(isElementReachable(drawer.el)).toBe(true);
    });

    it("accepts an element whose middle alone is covered", () => {
        const panel = zone({ rect: { left: 0, top: 0, right: 400, bottom: 400 } });
        cover({ left: 150, top: 150, right: 250, bottom: 250 });
        expect(isElementReachable(panel.el)).toBe(true);
    });

    it("accepts the strip of an element its scrollport still shows", () => {
        // the visual library upload card near the top of a scrolled dialog
        // card: 24px of it are left, and they are there to be clicked
        const port = scrollport({ left: 50, top: 200, right: 350, bottom: 500 });
        const scrolled = zone({ parent: port, rect: { left: 50, top: 124, right: 350, bottom: 224 } });

        expect(isElementReachable(scrolled.el)).toBe(true);
    });

    it("rejects an element scrolled out of its scrollport", () => {
        const port = scrollport({ left: 50, top: 200, right: 350, bottom: 500 });
        const scrolled = zone({ parent: port, rect: { left: 50, top: 90, right: 350, bottom: 190 } });

        expect(isElementReachable(scrolled.el)).toBe(false);
    });

    it("accepts an element that is drawn and reachable", () => {
        const panel = zone();
        expect(isElementReachable(panel.el)).toBe(true);
    });
});

describe("selectPasteTarget", () => {
    it("prefers the zone that holds the focus", () => {
        const first = zone({ rect: { left: 0, top: 0, right: 200, bottom: 200 } });
        const second = zone({ rect: { left: 300, top: 0, right: 500, bottom: 200 } });
        expect(selectPasteTarget([first, second], [first.el])).toBe(first);
    });

    it("prefers a zone that contains the focused node", () => {
        const target = zone();
        const button = document.createElement("button");
        target.el.appendChild(button);
        const other = zone({ rect: { left: 300, top: 0, right: 500, bottom: 200 } });
        expect(selectPasteTarget([target, other], [button])).toBe(target);
    });

    it("prefers the most recently registered zone containing the focus", () => {
        const outer = zone();
        const inner = zone({ parent: outer.el });
        expect(selectPasteTarget([outer, inner], [inner.el])).toBe(inner);
    });

    it("falls back to the zone that registered last", () => {
        const first = zone({ rect: { left: 0, top: 0, right: 200, bottom: 200 } });
        const second = zone({ rect: { left: 300, top: 0, right: 500, bottom: 200 } });
        expect(selectPasteTarget([first, second], [document.body])).toBe(second);
    });

    it("hands the paste to the open drawer rather than the panel it covers", () => {
        // the world editor below vuetify's lg threshold: the drawer holds the
        // cover panel, its scrim covers the scene visuals grid, and the grid
        // registered last
        const coverPanel = zone({ rect: { left: 0, top: 0, right: 300, bottom: 768 } });
        const grid = zone({ rect: { left: 320, top: 0, right: 1000, bottom: 700 } });
        cover();
        place(coverPanel.el, { left: 0, top: 0, right: 300, bottom: 768 });

        expect(selectPasteTarget([coverPanel, grid], [])).toBe(coverPanel);
    });

    it("withholds every zone a dialog covers", () => {
        const panel = zone();
        cover();

        expect(selectPasteTarget([panel], [])).toBeNull();
        expect(selectPasteTarget([panel], [panel.el])).toBeNull();
    });

    it("skips a zone that is not drawn", () => {
        const visible = zone();
        const closed = zone({ rect: { left: 0, top: 0, right: 0, bottom: 0 }, paint: false });

        expect(selectPasteTarget([visible, closed], [])).toBe(visible);
    });

    it("skips a disabled zone", () => {
        const enabled = zone();
        const disabled = zone({ enabled: false, rect: { left: 300, top: 0, right: 500, bottom: 200 } });
        expect(selectPasteTarget([enabled, disabled], [])).toBe(enabled);
    });

    it("returns null when no zone can take the image", () => {
        expect(selectPasteTarget([zone({ enabled: false })], [])).toBeNull();
        expect(selectPasteTarget([], [])).toBeNull();
    });
});

describe("registerImagePasteTarget", () => {
    it("hands a pasted image to one zone and consumes the event", () => {
        const first = zone({ rect: { left: 0, top: 0, right: 200, bottom: 200 } });
        const second = zone({ rect: { left: 300, top: 0, right: 500, bottom: 200 } });
        register(first);
        register(second);

        const file = imageFile();
        const event = paste(clipboard({ files: [file] }));

        expect(second.handler).toHaveBeenCalledWith(file);
        expect(first.handler).not.toHaveBeenCalled();
        expect(event.defaultPrevented).toBe(true);
    });

    it("hands the image to the zone the paste landed in", () => {
        const first = zone({ rect: { left: 0, top: 0, right: 200, bottom: 200 } });
        const second = zone({ rect: { left: 300, top: 0, right: 500, bottom: 200 } });
        register(first);
        register(second);

        const file = imageFile();
        paste(clipboard({ files: [file] }), first.el);

        expect(first.handler).toHaveBeenCalledWith(file);
        expect(second.handler).not.toHaveBeenCalled();
    });

    it("hands the image to the focused zone when the paste lands elsewhere", () => {
        const first = zone({ rect: { left: 0, top: 0, right: 200, bottom: 200 } });
        const second = zone({ rect: { left: 300, top: 0, right: 500, bottom: 200 } });
        register(first);
        register(second);
        first.el.focus();

        const file = imageFile();
        paste(clipboard({ files: [file] }), document.body);

        expect(first.handler).toHaveBeenCalledWith(file);
        expect(second.handler).not.toHaveBeenCalled();
    });

    it("ignores a paste that carries no image", () => {
        const target = zone();
        register(target);

        const items = [{ kind: "string", type: "text/plain", getAsFile: () => null }];
        const event = paste(clipboard({ items }));

        expect(target.handler).not.toHaveBeenCalled();
        expect(event.defaultPrevented).toBe(false);
    });

    it("ignores a paste into a text field", () => {
        const target = zone();
        register(target);
        const input = document.createElement("textarea");
        document.body.appendChild(input);

        const event = paste(clipboard({ files: [imageFile()] }), input);

        expect(target.handler).not.toHaveBeenCalled();
        expect(event.defaultPrevented).toBe(false);
    });

    it("leaves the event alone when no zone can take the image", () => {
        const target = zone({ enabled: false });
        register(target);

        const event = paste(clipboard({ files: [imageFile()] }));

        expect(target.handler).not.toHaveBeenCalled();
        expect(event.defaultPrevented).toBe(false);
    });

    it("stops listening once the last zone unregisters", () => {
        const addSpy = vi.spyOn(document, "addEventListener");
        const removeSpy = vi.spyOn(document, "removeEventListener");

        const first = zone();
        const second = zone({ rect: { left: 300, top: 0, right: 500, bottom: 200 } });
        const unregisterFirst = registerImagePasteTarget(first);
        const unregisterSecond = registerImagePasteTarget(second);

        expect(addSpy.mock.calls.filter(([type]) => type === "paste")).toHaveLength(1);

        unregisterFirst();
        expect(removeSpy.mock.calls.filter(([type]) => type === "paste")).toHaveLength(0);

        unregisterSecond();
        expect(removeSpy.mock.calls.filter(([type]) => type === "paste")).toHaveLength(1);

        addSpy.mockRestore();
        removeSpy.mockRestore();
    });
});
