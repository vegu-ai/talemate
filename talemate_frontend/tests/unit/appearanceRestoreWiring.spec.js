import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { fileURLToPath, URL } from "node:url";
import { restoreAppearanceFromTheme } from "@/utils/appearanceTheme";

function read(path) {
    return readFileSync(fileURLToPath(new URL(path, import.meta.url)), "utf-8");
}

const APP_SETTINGS = read("../../src/components/AppSettings.vue");
const SCENE = read("../../src/components/AppConfigAppearanceScene.vue");
const ASSETS = read("../../src/components/AppConfigAppearanceAssets.vue");

// the suite runs in a node environment with no vue plugin, so the components
// cannot be mounted - lift the method bodies out of the sources and run them
// against stubs, so this pins the components' own code rather than a copy of it
function methodSource(source, name, label) {
    const declaration = new RegExp(`(?:^|[^\\w.$])${name}\\(([^)]*)\\) \\{`);
    const match = declaration.exec(source);
    expect(match, `${label} has no ${name}() method`).not.toBeNull();

    const start = source.indexOf("{", match.index + match[0].length - 1);
    let depth = 0;
    let end = -1;
    for (let i = start; i < source.length; i++) {
        if (source[i] === "{") depth++;
        if (source[i] === "}") depth--;
        if (depth === 0) {
            end = i;
            break;
        }
    }
    expect(end, `${name}() in ${label} is not brace balanced`).toBeGreaterThan(-1);

    const body = source.slice(start + 1, end);
    expect(body.trim().length, `${name}() in ${label} lifted an empty body`).toBeGreaterThan(0);
    return { params: match[1], body };
}

function lift(source, name, label, deps = {}) {
    const { params, body } = methodSource(source, name, label);
    const names = Object.keys(deps);
    const factory = new Function(...names, `return function (${params}) {${body}};`);
    return factory(...names.map(dep => deps[dep]));
}

// the trigger button and the dialog it opens, as the template declares them
function restoreTrigger() {
    const button = SCENE.match(/<v-btn([^>]*)>\s*Restore from theme\s*<\/v-btn>/);
    expect(button, "the messages page has no 'Restore from theme' button").not.toBeNull();
    const click = button[1].match(/@click="([^"]+)"/);
    expect(click, "the 'Restore from theme' button has no click handler").not.toBeNull();
    return { attrs: button[1], click: click[1] };
}

function confirmDialog(ref) {
    const dialog = SCENE.match(new RegExp(`<ConfirmActionPrompt([^>]*ref="${ref}"[^>]*)/>`));
    expect(dialog, `the messages page has no ConfirmActionPrompt ref="${ref}"`).not.toBeNull();
    const confirm = dialog[1].match(/@confirm="([^"]+)"/);
    expect(confirm, `ConfirmActionPrompt ref="${ref}" has no confirm handler`).not.toBeNull();
    return { attrs: dialog[1], handler: confirm[1] };
}

// the shared color picker and the state the template binds it to
function colorPicker() {
    const picker = SCENE.match(/<v-color-picker([^>]*)>/);
    expect(picker, "the messages page has no color picker").not.toBeNull();
    const model = picker[1].match(/v-model="(\w+)"/);
    expect(model, "the color picker binds no model").not.toBeNull();
    const handler = picker[1].match(/@update:model-value="(\w+)"/);
    expect(handler, "the color picker has no change handler").not.toBeNull();
    return { model: model[1], handler: handler[1] };
}

function restoreMethodName() {
    const promptedRef = restoreTrigger().click.match(/\$refs\.([\w-]+)\.initiateAction\(/);
    expect(promptedRef, "the 'Restore from theme' button opens no confirmation prompt").not.toBeNull();
    return confirmDialog(promptedRef[1]).handler;
}

function messageStyle(color) {
    return { italic: false, bold: false, color };
}

function staleAssets() {
    return {
        avatar: { cadence: "always", size: "medium" },
        card: { cadence: "always", size: "medium" },
        scene_illustration: { cadence: "always", size: "medium", auto_backdrop: false },
        scene_background: { cadence: "always", size: "big", auto_backdrop: false },
    };
}

function freshAssets() {
    return {
        avatar: { cadence: "never", size: "small" },
        card: { cadence: "never", size: "big" },
        scene_illustration: { cadence: "on_change", size: "medium", auto_backdrop: true },
        scene_background: { cadence: "never", size: "big", auto_backdrop: true },
    };
}

function userScene() {
    return {
        narrator_messages: messageStyle("#111111"),
        actor_messages: messageStyle("#222222"),
        quotes: { ...messageStyle("#333333"), show: true, override_color: true },
        // the messages page holds a stale copy of what the visuals page owns
        message_assets: staleAssets(),
        auto_attach_assets: true,
        backdrop_panel_opacity: 0.25,
        backdrop_text_shadow: false,
    };
}

function themeAppearance() {
    return {
        narrator: { italic: true, bold: true },
        actor: { italic: true, bold: true },
        quotes: { italic: true, bold: true, show: true, override_color: true },
        backdrop_panel_opacity: 0.9,
        backdrop_text_shadow: true,
    };
}

// the settings view with both appearance pages mounted: the messages page has
// the user's edits, the visuals page owns the assets and the backdrop values
function settingsStub() {
    const app_config = {
        appearance: { scene: userScene() },
        theme: { appearance: themeAppearance() },
    };

    const visuals = {
        immutableConfig: app_config,
        config: freshAssets(),
        autoAttachAssets: false,
        backdropPanelOpacity: 0.25,
        backdropTextShadow: false,
        syncBackdropSettings: lift(ASSETS, "syncBackdropSettings", "AppConfigAppearanceAssets.vue"),
        get_config: lift(ASSETS, "get_config", "AppConfigAppearanceAssets.vue"),
        get_auto_attach_assets: lift(ASSETS, "get_auto_attach_assets", "AppConfigAppearanceAssets.vue"),
        get_backdrop_settings: lift(ASSETS, "get_backdrop_settings", "AppConfigAppearanceAssets.vue"),
    };

    const settings = {
        app_config,
        previews: [],
        $refs: { "appearance-visuals": visuals },
        mergeSubcomponentConfigs: lift(APP_SETTINGS, "mergeSubcomponentConfigs", "AppSettings.vue"),
        onAppearanceChanged: lift(APP_SETTINGS, "onAppearanceChanged", "AppSettings.vue"),
        onAppearanceRestoredFromTheme: lift(APP_SETTINGS, "onAppearanceRestoredFromTheme", "AppSettings.vue"),
        emitAppearancePreview() {
            this.previews.push(this.app_config.appearance);
        },
    };

    const messages = {
        immutableConfig: app_config,
        config: JSON.parse(JSON.stringify(app_config.appearance.scene)),
        emitted: [],
        [restoreMethodName()]: lift(SCENE, restoreMethodName(), "AppConfigAppearanceScene.vue", {
            restoreAppearanceFromTheme,
        }),
        $emit(event, payload) {
            this.emitted.push([event, payload]);
            const handler = restoreEventHandler();
            if (event === handler.event) {
                settings[handler.method](payload);
            }
        },
    };
    settings.$refs["appearance-messages"] = messages;

    return { settings, messages, visuals, app_config };
}

// the event the messages page fires on confirm, and the AppSettings method
// bound to it
function restoreEventHandler() {
    const emit = SCENE.match(/\$emit\('(restore-from-theme)'/);
    expect(emit, "the messages page emits no restore-from-theme event").not.toBeNull();
    const binding = APP_SETTINGS.match(
        /<AppConfigAppearanceScene[^>]*@restore-from-theme="(\w+)"/,
    );
    expect(binding, "AppSettings does not handle restore-from-theme").not.toBeNull();
    return { event: emit[1], method: binding[1] };
}

describe("restore from theme confirmation", () => {
    it("the button opens a confirmation prompt instead of restoring", () => {
        const { settings, messages } = settingsStub();
        const before = JSON.parse(JSON.stringify(messages.config));
        const prompted = [];

        const trigger = restoreTrigger();
        const stub = {
            ...messages,
            $refs: {
                [restoreTrigger().click.match(/\$refs\.([\w-]+)\./)?.[1] || "missing"]: {
                    initiateAction: (params) => prompted.push(params ?? null),
                },
            },
        };
        new Function(`const { $refs, ${restoreMethodName()} } = this; ${trigger.click};`).call(stub);

        expect(prompted.length, "the button did not open the confirmation prompt").toBe(1);
        expect(stub.config, "the button restored without a confirmation").toEqual(before);
        expect(messages.emitted, "the button emitted before the confirmation").toEqual([]);
        expect(settings.previews).toEqual([]);
    });

    it("the restore runs as the prompt's confirm handler", () => {
        const { messages } = settingsStub();
        expect(restoreMethodName(), "the prompt confirms into no restore method").toBe("restoreFromTheme");

        messages[restoreMethodName()]();

        expect(messages.config.narrator_messages.color, "confirming did not restore").toBeNull();
        expect(messages.emitted.map(([event]) => event)).toEqual([restoreEventHandler().event]);
    });

    it("names the edits it discards", () => {
        const description = confirmDialog(
            restoreTrigger().click.match(/\$refs\.([\w-]+)\.initiateAction\(/)[1],
        ).attrs.match(/description="([^"]+)"/);
        expect(description, "the confirmation prompt has no description").not.toBeNull();
        expect(description[1]).toMatch(/discards your own appearance edits/);
    });
});

describe("restore from theme and an open color picker", () => {
    it("the picker cannot write the discarded override back onto the restored config", () => {
        const { messages, app_config } = settingsStub();
        const picker = colorPicker();
        messages.colorPicker = null;
        messages.colorPickerTarget = null;
        messages[picker.model] = "#000000";
        messages.openColorPicker = lift(SCENE, "openColorPicker", "AppConfigAppearanceScene.vue");
        messages[picker.handler] = lift(SCENE, picker.handler, "AppConfigAppearanceScene.vue");

        // the user has the picker open on a row, holding their own override
        messages.openColorPicker("narrator_messages", "#111111");
        expect(messages.colorPickerTarget, "the picker did not target the row").toBe("narrator_messages");
        expect(messages[picker.model], "the picker did not take the row's color").toBe("#111111");

        messages[restoreMethodName()]();

        expect(messages.colorPickerTarget, "the restore left the row targeted by the picker").toBeNull();
        expect(messages[picker.model], "the picker still holds the discarded override").not.toBe("#111111");

        // any touch of the picker runs its change handler
        messages[picker.handler]();

        expect(
            messages.config.narrator_messages.color,
            "the picker wrote the discarded override back onto the restored config",
        ).toBeNull();
        expect(
            app_config.appearance.scene.narrator_messages.color,
            "the picker wrote the discarded override back into the app config",
        ).toBeNull();
    });
});

describe("restore from theme merge", () => {
    it("keeps the restored backdrop values and the visuals page's assets", () => {
        const { settings, messages, visuals, app_config } = settingsStub();

        messages[restoreMethodName()]();

        const scene = app_config.appearance.scene;
        expect(scene.backdrop_panel_opacity, "the restored opacity was lost to the visuals page").toBe(0.9);
        expect(scene.backdrop_text_shadow, "the restored text shadow was lost to the visuals page").toBe(true);
        expect(scene.message_assets, "the visuals page's assets were lost to the messages page").toEqual(
            freshAssets(),
        );
        expect(scene.auto_attach_assets, "the visuals page's asset attachment was lost").toBe(false);
        expect(scene.narrator_messages).toEqual({ italic: true, bold: true, color: null });
        expect(visuals.backdropPanelOpacity, "the visuals page still shows the discarded opacity").toBe(0.9);
        expect(settings.previews.length, "the restore emitted no appearance preview").toBe(1);
    });

    it("restores while the visuals page has never been rendered", () => {
        const { settings, messages, app_config } = settingsStub();
        // the settings pages render lazily - a user who opens Appearance on the
        // messages page and restores never mounted the visuals page
        delete settings.$refs["appearance-visuals"];

        messages[restoreMethodName()]();

        const scene = app_config.appearance.scene;
        expect(scene.backdrop_panel_opacity, "the restored opacity was lost without the visuals page").toBe(0.9);
        expect(scene.backdrop_text_shadow, "the restored text shadow was lost without the visuals page").toBe(true);
        expect(scene.message_assets, "the assets changed without the visuals page").toEqual(staleAssets());
        expect(scene.auto_attach_assets, "the asset attachment changed without the visuals page").toBe(true);
        expect(scene.narrator_messages).toEqual({ italic: true, bold: true, color: null });
        expect(settings.previews.length, "the restore emitted no appearance preview").toBe(1);
    });

    it("still lets the visuals page own its own settings on a plain change", () => {
        const { settings, visuals, app_config } = settingsStub();
        visuals.backdropPanelOpacity = 0.4;
        visuals.backdropTextShadow = true;

        settings.onAppearanceChanged();

        const scene = app_config.appearance.scene;
        expect(scene.backdrop_panel_opacity).toBe(0.4);
        expect(scene.backdrop_text_shadow).toBe(true);
        expect(scene.message_assets).toEqual(freshAssets());
        expect(scene.auto_attach_assets).toBe(false);
    });
});
