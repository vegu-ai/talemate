import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { fileURLToPath, URL } from "node:url";

function read(path) {
    return readFileSync(fileURLToPath(new URL(path, import.meta.url)), "utf-8");
}

const APP_SETTINGS = read("../../src/components/AppSettings.vue");

// the suite runs in a node environment with no vue plugin, so the component
// cannot be mounted - lift the method bodies out of the source and run them
// against a stub, so this pins the component's own code rather than a copy of it
function methodSource(name) {
    const declaration = new RegExp(`(?:^|[^\\w.$])${name}\\(([^)]*)\\) \\{`);
    const match = declaration.exec(APP_SETTINGS);
    expect(match, `AppSettings.vue has no ${name}() method`).not.toBeNull();

    const start = APP_SETTINGS.indexOf("{", match.index + match[0].length - 1);
    let depth = 0;
    let end = -1;
    for (let i = start; i < APP_SETTINGS.length; i++) {
        if (APP_SETTINGS[i] === "{") depth++;
        if (APP_SETTINGS[i] === "}") depth--;
        if (depth === 0) {
            end = i;
            break;
        }
    }
    expect(end, `${name}() in AppSettings.vue is not brace balanced`).toBeGreaterThan(-1);

    const body = APP_SETTINGS.slice(start + 1, end);
    expect(body.trim().length, `${name}() in AppSettings.vue lifted an empty body`).toBeGreaterThan(0);
    return { params: match[1], body };
}

function lift(name) {
    const { params, body } = methodSource(name);
    return new Function(`return function (${params}) {${body}};`)();
}

function theme(primary) {
    return {
        name: "Midnight",
        dark: true,
        colors: { app: { primary }, chat: { narrator: "#aaaaaa" } },
        appearance: { narrator: { italic: true, bold: false } },
    };
}

// a config payload as the backend dumps it: the theme id belongs to the config
// (and so to the draft), the resolved theme rides along outside of it
function payload(resolved, themeId = "group__theme") {
    const config = {
        appearance: {
            theme: themeId,
            scene: { narrator_messages: { color: "#111111", italic: false } },
        },
        game: { default_player_character: { name: "Player" } },
        system_prompt_defaults: { conversation: "be nice" },
    };
    if (resolved !== undefined) {
        config.theme = resolved;
    }
    return config;
}

function settingsStub() {
    const stub = {
        app_config: null,
        snapshot: null,
        pendingConfig: null,
        externalChange: false,
        saving: false,
        applyFailed: false,
        pendingSaveId: null,
        saveError: null,
        setSaveError(error) {
            this.saveError = error;
        },
        normalizedPayload: lift("normalizedPayload"),
        adoptConfig: lift("adoptConfig"),
        adoptTheme: lift("adoptTheme"),
        handleMessage: lift("handleMessage"),
    };
    Object.defineProperty(stub, "configDirty", { get: lift("configDirty") });
    return stub;
}

// the settings view sitting on an adopted config with an unsaved edit in it
function dirtyStub(resolved = theme("#111111")) {
    const stub = settingsStub();
    stub.adoptConfig(payload(resolved));
    stub.app_config.appearance.scene.narrator_messages.color = "#999999";
    expect(stub.configDirty).toBe(true);
    return stub;
}

describe("adoptConfig carrying the resolved theme", () => {
    it("carries the theme forward when a payload omits it", () => {
        const stub = settingsStub();
        stub.adoptConfig(payload(theme("#123456")));

        stub.adoptConfig(payload());

        expect(stub.app_config.theme).toEqual(theme("#123456"));
        // and as part of the baseline, or the next broadcast reads as a change
        expect(JSON.parse(stub.snapshot).theme).toEqual(theme("#123456"));
        expect(stub.configDirty).toBe(false);
    });

    it("takes the incoming theme when the payload carries one", () => {
        const stub = settingsStub();
        stub.adoptConfig(payload(theme("#123456")));

        stub.adoptConfig(payload(theme("#654321")));

        expect(stub.app_config.theme.colors.app.primary).toBe("#654321");
    });

    it("adopts a themeless payload when there is nothing to carry", () => {
        const stub = settingsStub();

        stub.adoptConfig(payload());

        expect(stub.app_config.theme).toBeUndefined();
        expect(stub.configDirty).toBe(false);
    });
});

describe("a stashed app_config still hands over its theme", () => {
    it("adopts the fresh theme over unsaved edits", () => {
        const stub = dirtyStub();
        const incoming = payload(theme("#654321"));

        stub.handleMessage({ type: "app_config", data: incoming });

        expect(stub.app_config.theme.colors.app.primary).toBe("#654321");
        // the edits are still held back, unadopted
        expect(stub.pendingConfig).toBe(incoming);
        expect(stub.app_config.appearance.scene.narrator_messages.color).toBe("#999999");
        expect(stub.app_config.appearance.theme).toBe("group__theme");
        expect(stub.configDirty).toBe(true);
    });

    it("does not alias the shared payload", () => {
        const stub = dirtyStub();
        const incoming = payload(theme("#654321"));

        stub.handleMessage({ type: "app_config", data: incoming });

        expect(stub.app_config.theme).not.toBe(incoming.theme);
    });

    it("leaves nothing dirty behind once the edit is taken back", () => {
        const stub = dirtyStub();

        stub.handleMessage({ type: "app_config", data: payload(theme("#654321")) });
        stub.app_config.appearance.scene.narrator_messages.color = "#111111";

        expect(stub.configDirty).toBe(false);
    });

    it("does not flag a theme-only change as an external change", () => {
        const stub = dirtyStub();

        stub.handleMessage({ type: "app_config", data: payload(theme("#654321")) });

        expect(stub.externalChange).toBe(false);
    });

    it("still flags a change beyond the theme", () => {
        const stub = dirtyStub();
        const incoming = payload(theme("#654321"));
        incoming.game.default_player_character.name = "Somebody Else";

        stub.handleMessage({ type: "app_config", data: incoming });

        expect(stub.externalChange).toBe(true);
    });

    it("leaves the draft alone when the payload carries no theme", () => {
        const stub = dirtyStub();
        const before = JSON.stringify(stub.app_config);

        stub.handleMessage({ type: "app_config", data: payload() });

        expect(JSON.stringify(stub.app_config)).toBe(before);
    });
});

// applying a theme commits the new id server-side while a dirty settings view
// holds the broadcast back - the id must still reach the draft and the
// baseline, or the picker's Active chip goes stale and a later save reverts it
describe("a stashed app_config still hands over its theme id", () => {
    it("adopts the applied theme id over unsaved edits", () => {
        const stub = dirtyStub();

        stub.handleMessage({ type: "app_config", data: payload(theme("#654321"), "group__other") });

        expect(stub.app_config.appearance.theme).toBe("group__other");
        expect(JSON.parse(stub.snapshot).appearance.theme).toBe("group__other");
        // the edits themselves are still held back
        expect(stub.app_config.appearance.scene.narrator_messages.color).toBe("#999999");
        expect(stub.configDirty).toBe(true);
    });

    it("does not flag an applied theme as an external change", () => {
        const stub = dirtyStub();

        stub.handleMessage({ type: "app_config", data: payload(theme("#654321"), "group__other") });

        expect(stub.externalChange).toBe(false);
    });

    it("saves the applied id, not the stale one", () => {
        const stub = dirtyStub();
        stub.handleMessage({ type: "app_config", data: payload(theme("#654321"), "group__other") });

        // what sendConfigSave would put on the wire
        expect(stub.app_config.appearance.theme).toBe("group__other");
    });

    it("adopts an id-only change without touching the resolved theme", () => {
        const stub = dirtyStub();
        const resolvedBefore = stub.app_config.theme;

        stub.handleMessage({ type: "app_config", data: payload(undefined, "group__other") });

        expect(stub.app_config.appearance.theme).toBe("group__other");
        expect(stub.app_config.theme).toBe(resolvedBefore);
        expect(stub.configDirty).toBe(true);
    });
});

// the baseline is compared to incoming payloads as raw JSON, so a carried-forward
// key landing in a different position than an emitter puts it reads as an outside
// change even when the content is identical
describe("key order of a carried-forward payload", () => {
    it("does not flag a broadcast that only differs in key order", () => {
        // the sequence that produces it: a full payload on load, then a payload
        // that omits system_prompt_defaults (so it is carried forward), then an
        // edit, then any later broadcast
        const stub = settingsStub();
        stub.adoptConfig(payload(theme("#111111")));

        const handlerShaped = payload(theme("#111111"));
        delete handlerShaped.system_prompt_defaults;
        stub.adoptConfig(handlerShaped);

        stub.app_config.appearance.scene.narrator_messages.color = "#999999";
        expect(stub.configDirty).toBe(true);

        // an emitter's own payload: system_prompt_defaults, then theme
        stub.handleMessage({ type: "app_config", data: payload(theme("#111111")) });

        expect(
            stub.externalChange,
            "a payload deep-equal to the baseline was flagged as an outside change",
        ).toBe(false);
    });

    it("does not flag an emitter that orders the two extras the other way", () => {
        const stub = settingsStub();
        stub.adoptConfig(payload(theme("#111111")));
        stub.app_config.appearance.scene.narrator_messages.color = "#999999";
        expect(stub.configDirty).toBe(true);

        // same content, extras emitted theme-first
        const base = payload(theme("#111111"));
        const oddOrder = {};
        Object.keys(base)
            .filter((key) => key !== "system_prompt_defaults" && key !== "theme")
            .forEach((key) => { oddOrder[key] = base[key]; });
        oddOrder.theme = base.theme;
        oddOrder.system_prompt_defaults = base.system_prompt_defaults;
        expect(JSON.stringify(oddOrder)).not.toBe(JSON.stringify(base));

        stub.handleMessage({ type: "app_config", data: oddOrder });

        expect(
            stub.externalChange,
            "the same config in another key order was flagged as an outside change",
        ).toBe(false);
    });
});
