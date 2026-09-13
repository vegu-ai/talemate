import { describe, expect, it } from "vitest";
import { fileURLToPath, URL } from "node:url";
import { lift, readSource } from "./helpers/liftMethod.js";
import { SETTINGS_GROUPS, searchSettings } from "@/utils/appSettingsRegistry.js";

const gameplay = readSource(fileURLToPath(new URL(
    "../../src/components/AppSettingsGameplay.vue", import.meta.url)));
const bar = readSource(fileURLToPath(new URL(
    "../../src/components/SceneUtilityBar.vue", import.meta.url)));
const app = readSource(fileURLToPath(new URL(
    "../../src/components/TalemateApp.vue", import.meta.url)));

const generalPage = SETTINGS_GROUPS.flatMap((group) => group.pages).find((page) => page.id === "gameplay");

describe("scene utility bar settings", () => {
    it("the Game > General page carries the toggle and both slot selects", () => {
        for (const anchor of ["scene_utility_bar", "scene_utility_bar_slot_a", "scene_utility_bar_slot_b"]) {
            expect(gameplay).toContain(`data-setting-anchor="${anchor}"`);
        }
        expect(gameplay).toContain('v-model="config.game.scene_utility_bar.enabled"');
        expect(gameplay).toContain('v-model="config.game.scene_utility_bar.slot_a"');
        expect(gameplay).toContain('v-model="config.game.scene_utility_bar.slot_b"');
    });

    it("the settings search finds the bar and each slot by its visible label", () => {
        const anchors = generalPage.entries.map((entry) => entry.anchor);
        expect(anchors).toEqual(expect.arrayContaining(["scene_utility_bar", "scene_utility_bar_slot_a", "scene_utility_bar_slot_b"]));
        expect(searchSettings("utility bar").map((result) => result.entry.anchor))
            .toEqual(expect.arrayContaining(["scene_utility_bar", "scene_utility_bar_slot_a", "scene_utility_bar_slot_b"]));
        expect(searchSettings("Left of the title").map((result) => result.entry.anchor)).toEqual(["scene_utility_bar_slot_a"]);
        expect(searchSettings("Right of the title").map((result) => result.entry.anchor)).toEqual(["scene_utility_bar_slot_b"]);
    });

    it("the slot selects present catalog items by label with the description as subtitle", () => {
        const itemProps = lift(gameplay, "utilityItemProps", "AppSettingsGameplay");
        expect(itemProps({ id: "summarizer", label: "Summarizer", description: "Tokens until summary." }))
            .toEqual({ title: "Summarizer", subtitle: "Tokens until summary.", value: "summarizer" });
    });

    it("the close button writes the same setting the settings page toggles", () => {
        const sent = [];
        const hide = lift(bar, "hide", "SceneUtilityBar").bind({
            getWebsocket: () => ({ send: (frame) => sent.push(JSON.parse(frame)) }),
        });
        hide();
        expect(sent).toEqual([{
            type: "quick_settings",
            action: "set",
            setting: "scene_utility_bar_enabled",
            value: false,
        }]);
        expect(bar).toContain('aria-label="Hide the scene utility bar"');
    });

    it("both slot templates expose the due state to assistive technology and the keyboard", () => {
        const chips = bar.match(/<v-chip v-bind="props"[^>]*>[\s\S]*?<\/v-chip>/g) || [];
        expect(chips).toHaveLength(2);
        for (const chip of chips) {
            expect(chip).toContain('tabindex="0"');
            expect(chip).toContain('<span v-if="part.srText" class="d-sr-only">{{ part.srText }}</span>');
            expect(chip).toContain('<v-icon v-if="part.trailingIcon" end size="x-small">{{ part.trailingIcon }}</v-icon>');
        }
    });

    it("the scene's navigation tab reads Story now that the bar carries the title", () => {
        const mainTab = /title: \(\) => \{ return 'Story' \},[\s\S]*?value: 'main'/.exec(app);
        expect(mainTab, "TalemateApp main tab title").not.toBeNull();
        expect(mainTab[0]).not.toContain("scene.title");
    });

    it("the app shows the bar only with a scene, outside playthrough, and while enabled", () => {
        const visible = lift(app, "sceneUtilityBarVisible", "TalemateApp");
        const state = (overrides = {}) => ({
            sceneActive: true,
            showSceneView: true,
            playthroughActive: false,
            appConfig: { game: { scene_utility_bar: { enabled: true } } },
            ...overrides,
        });
        expect(visible.call(state())).toBe(true);
        expect(visible.call(state({ sceneActive: false }))).toBe(false);
        expect(visible.call(state({ showSceneView: false }))).toBe(false);
        expect(visible.call(state({ playthroughActive: true }))).toBe(false);
        expect(visible.call(state({ appConfig: { game: { scene_utility_bar: { enabled: false } } } }))).toBe(false);
        expect(visible.call(state({ appConfig: {} }))).toBe(false);
    });
});
