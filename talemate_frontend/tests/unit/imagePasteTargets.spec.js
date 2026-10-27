// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createApp, h } from "vue";
import ImagePasteTargetMixin from "@/components/ImagePasteTargetMixin.js";
import VisualAssetsMixin from "@/components/VisualAssetsMixin.js";

const mounted = [];

// jsdom lays nothing out, so every mounted root is given a rectangle and the
// hit test answers from paint order, last on top.
let painted = [];

beforeEach(() => {
    painted = [];
    document.elementFromPoint = (x, y) => {
        for (let i = painted.length - 1; i >= 0; i--) {
            const rect = painted[i].getBoundingClientRect();
            if (x >= rect.left && x < rect.right && y >= rect.top && y < rect.bottom) return painted[i];
        }
        return null;
    };
});

afterEach(() => {
    while (mounted.length) {
        const { app, host } = mounted.pop();
        app.unmount();
        host.remove();
    }
    document.body.innerHTML = "";
});

// VisualAssetsMixin injects these without a default; a consumer of it warns
// without them.
const PROVIDES = {
    getWebsocket: () => ({ send: vi.fn() }),
    registerMessageHandler: vi.fn(),
    unregisterMessageHandler: vi.fn(),
    requestSceneAssets: vi.fn(),
};

function mount(options, rect = { left: 0, top: 0, right: 200, bottom: 200 }) {
    const host = document.createElement("div");
    document.body.appendChild(host);
    const app = createApp({ render: () => h("div", { class: "zone" }), ...options });
    for (const [key, value] of Object.entries(PROVIDES)) app.provide(key, value);
    const instance = app.mount(host);
    instance.$el.getBoundingClientRect = () => ({
        ...rect,
        width: rect.right - rect.left,
        height: rect.bottom - rect.top,
    });
    painted.push(instance.$el);
    mounted.push({ app, host });
    return instance;
}

function pasteImage(target = document.body) {
    const file = new File(["binary"], "pasted.png", { type: "image/png" });
    const event = new Event("paste", { bubbles: true, cancelable: true });
    Object.defineProperty(event, "clipboardData", { value: { files: [file], items: [] } });
    target.dispatchEvent(event);
    return file;
}

describe("ImagePasteTargetMixin", () => {
    it("hands a pasted image to the component while it is mounted", () => {
        const handlePastedImage = vi.fn();
        mount({ mixins: [ImagePasteTargetMixin], methods: { handlePastedImage } });

        const file = pasteImage();

        expect(handlePastedImage).toHaveBeenCalledWith(file);
    });

    it("stops taking pastes once the component unmounts", () => {
        const handlePastedImage = vi.fn();
        mount({ mixins: [ImagePasteTargetMixin], methods: { handlePastedImage } });

        const { app, host } = mounted.pop();
        app.unmount();
        host.remove();

        pasteImage();

        expect(handlePastedImage).not.toHaveBeenCalled();
    });

    it("withholds the zone while pasteTargetEnabled is falsy", () => {
        const enabled = vi.fn();
        const disabled = vi.fn();
        mount({ mixins: [ImagePasteTargetMixin], methods: { handlePastedImage: enabled } });
        mount({
            mixins: [ImagePasteTargetMixin],
            computed: { pasteTargetEnabled: () => undefined },
            methods: { handlePastedImage: disabled },
        }, { left: 300, top: 0, right: 500, bottom: 200 });

        pasteImage();

        expect(disabled).not.toHaveBeenCalled();
        expect(enabled).toHaveBeenCalled();
    });
});

describe("VisualAssetsMixin as a paste target", () => {
    it("routes a pasted image into the file upload path", () => {
        const handleFileUpload = vi.fn();
        mount({
            mixins: [VisualAssetsMixin],
            computed: { uploadConfig: () => ({ vis_type: "CHARACTER_PORTRAIT", namePrefix: "avatar" }) },
            methods: { handleFileUpload },
        });

        const file = pasteImage();

        expect(handleFileUpload).toHaveBeenCalledWith(file);
    });

    it("never takes a paste in a consumer that offers no upload", () => {
        const withUpload = vi.fn();
        const withoutUpload = vi.fn();
        mount({
            mixins: [VisualAssetsMixin],
            computed: { uploadConfig: () => ({ vis_type: "SCENE_BACKGROUND", namePrefix: "scene" }) },
            methods: { handleFileUpload: withUpload },
        });
        // a consumer without uploadConfig offers no upload: SceneMessages,
        // WorldState and the character tools menu use the mixin for its asset
        // helpers alone
        mount({ mixins: [VisualAssetsMixin], methods: { handleFileUpload: withoutUpload } },
            { left: 300, top: 0, right: 500, bottom: 200 });

        pasteImage();

        expect(withoutUpload).not.toHaveBeenCalled();
        expect(withUpload).toHaveBeenCalled();
    });
});
