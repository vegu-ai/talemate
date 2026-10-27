import { describe, expect, it } from "vitest";
import { fileURLToPath, URL } from "node:url";
import { lift, readSource } from "./helpers/liftMethod.js";
import { SETTINGS_GROUPS, searchSettings } from "@/utils/appSettingsRegistry.js";
import { SCENE_HEADER_SLOTS, applySlotEdit, resolveSlotItems } from "@/utils/sceneHeaderItems.js";

const read = (path) => readSource(fileURLToPath(new URL(path, import.meta.url)));
const gameplay = read("../../src/components/AppSettingsGameplay.vue");
const header = read("../../src/components/SceneHeader.vue");
const slotComponent = read("../../src/components/SceneHeaderSlot.vue");
const itemMenu = read("../../src/components/SceneHeaderItemMenu.vue");
const app = read("../../src/components/TalemateApp.vue");
const fonts = read("../../src/plugins/webfontloader.js");

const generalPage = SETTINGS_GROUPS.flatMap((group) => group.pages).find((page) => page.id === "gameplay");
const ANCHORS = ["scene_header", "scene_header_slot_a", "scene_header_slot_b"];
const [LEFT, RIGHT] = SCENE_HEADER_SLOTS;

// a component instance as far as the picker methods reach into it, plus a
// stand-in backend that applies each sent edit in order and answers it the
// way quick_settings does: the app_config broadcast first, then set_done
function picker(settings) {
    const vm = {
        settings,
        pending: { slot_a: [], slot_b: [] },
        slotDefinitions: SCENE_HEADER_SLOTS,
        sent: [],
        getWebsocket: () => ({ send: (frame) => vm.sent.push(JSON.parse(frame)) }),
    };
    for (const name of ["isShown", "toggle", "hide", "setQuickSetting", "clearPending", "handleMessage"]) {
        vm[name] = lift(header, name, "SceneHeader").bind(vm);
    }
    vm.slotIds = lift(header, "slotIds", "SceneHeader", { applySlotEdit }).bind(vm);
    let answered = 0;
    vm.echoNext = () => {
        const frame = vm.sent[answered++];
        const slot = SCENE_HEADER_SLOTS.find((definition) => definition.setting === frame.setting);
        vm.settings = { ...vm.settings, [slot.id]: applySlotEdit(vm.settings[slot.id], frame.value) };
        vm.handleMessage({ type: "quick_settings", action: "set_done", data: { setting: frame.setting, value: frame.value } });
    };
    return vm;
}

describe("scene header settings", () => {
    it("the Game > General page carries the toggle and both slot selects", () => {
        for (const anchor of ANCHORS) {
            expect(gameplay).toContain(`data-setting-anchor="${anchor}"`);
        }
        expect(gameplay).toContain('v-model="config.game.scene_header.enabled"');
        expect(gameplay).toContain('v-model="config.game.scene_header.slot_a"');
        expect(gameplay).toContain('v-model="config.game.scene_header.slot_b"');
        expect(gameplay).toContain('label="Show scene header"');
    });

    it("the settings search finds the header and each slot by its visible label", () => {
        const anchors = generalPage.entries.map((entry) => entry.anchor);
        expect(anchors).toEqual(expect.arrayContaining(ANCHORS));
        expect(searchSettings("scene header").map((result) => result.entry.anchor)).toEqual(expect.arrayContaining(ANCHORS));
        expect(searchSettings("Left of the title").map((result) => result.entry.anchor)).toEqual(["scene_header_slot_a"]);
        expect(searchSettings("Right of the title").map((result) => result.entry.anchor)).toEqual(["scene_header_slot_b"]);
        expect(searchSettings("utility")).toEqual([]);
    });

    it("the slot selects present catalog items by label with the description as subtitle", () => {
        const itemProps = lift(gameplay, "headerItemProps", "AppSettingsGameplay");
        expect(itemProps({ id: "summarizer", label: "Summarizer", description: "Tokens until summary." }))
            .toEqual({ title: "Summarizer", subtitle: "Tokens until summary.", value: "summarizer" });
    });

    it("the close button writes the same setting the settings page toggles", () => {
        const vm = picker({});
        lift(header, "hide", "SceneHeader").bind(vm)();
        expect(vm.sent).toEqual([{
            type: "quick_settings",
            action: "set",
            setting: "scene_header_enabled",
            value: false,
        }]);
        expect(header).toContain('aria-label="Hide the scene header"');
    });

    it("the scene's navigation tab reads Story now that the header carries the title", () => {
        const mainTab = /title: \(\) => \{ return 'Story' \},[\s\S]*?value: 'main'/.exec(app);
        expect(mainTab, "TalemateApp main tab title").not.toBeNull();
        expect(mainTab[0]).not.toContain("scene.title");
    });

    it("the app shows the header only with a scene and while enabled, playthrough included", () => {
        const visible = lift(app, "sceneHeaderVisible", "TalemateApp");
        const state = (overrides = {}) => ({
            sceneActive: true,
            showSceneView: true,
            playthroughActive: false,
            appConfig: { game: { scene_header: { enabled: true } } },
            ...overrides,
        });
        expect(visible.call(state())).toBe(true);
        expect(visible.call(state({ sceneActive: false }))).toBe(false);
        expect(visible.call(state({ showSceneView: false }))).toBe(false);
        expect(visible.call(state({ playthroughActive: true }))).toBe(true);
        expect(visible.call(state({ playthroughActive: true, appConfig: { game: { scene_header: { enabled: false } } } }))).toBe(false);
        expect(visible.call(state({ appConfig: { game: { scene_header: { enabled: false } } } }))).toBe(false);
        expect(visible.call(state({ appConfig: {} }))).toBe(false);
        expect(app).toContain(':settings="appConfig.game.scene_header"');
    });
});


describe("scene header document look", () => {
    it("sits on the page, not on a sheet or card", () => {
        const template = header.slice(0, header.indexOf("<script>"));
        const headerMarkup = template.slice(0, template.indexOf("</section>"));
        expect(headerMarkup + slotComponent).not.toMatch(/<v-sheet|<v-card|<v-chip/);
    });

    it("is a region named Scene header, read in the order it is shown", () => {
        const template = header.slice(0, header.indexOf("</template>\n\n<script>"));
        expect(template).toContain('<section class="scene-header" :class="{ \'scene-header--title-only\': titleOnly }" aria-label="Scene header">');
        const order = ["scene-header__actions--slot_a", "scene-header__slot--slot_a", "<h1", "scene-header__slot--slot_b", "scene-header__actions--slot_b"]
            .map((marker) => template.indexOf(marker));
        expect(order.every((index) => index > -1)).toBe(true);
        expect([...order].sort((a, b) => a - b)).toEqual(order);
        // only the narrow layout moves the title, and only visually
        expect(header.match(/(?<![\w-])order: [^;]+;/g)).toEqual(["order: -1;"]);
    });

    it("sets the title as the page heading in Lora 500 with a Georgia fallback", () => {
        expect(header).toMatch(/<h1 v-bind="props" class="scene-header__title">\{\{ title \}\}<\/h1>/);
        const rule = /\.scene-header__title \{([^}]*)\}/.exec(header)[1];
        expect(rule).toContain("font-family: 'Lora', Georgia, 'Times New Roman', serif;");
        expect(rule).toContain("font-weight: 500;");
        expect(rule).toContain("text-overflow: ellipsis;");
        // the Google Fonts request is one URL: display=swap must stay on the last family
        const families = JSON.parse(/families: (\[[^\]]*\])/.exec(fonts)[1].replace(/'/g, '"'));
        expect(families).toContain("Lora:500");
        expect(families.at(-1)).toMatch(/&display=swap$/);
        expect(families.slice(0, -1).some((family) => family.includes("&"))).toBe(false);
    });


    it("renders every text item as a focusable value with its label, due marker and spoken reason", () => {
        const items = slotComponent.match(/<span v-bind="props" class="scene-header__item"[\s\S]*?\n {24}<\/span>/g) || [];
        expect(items).toHaveLength(1);
        const [item] = items;
        expect(item).toContain('tabindex="0"');
        expect(item).toContain("'scene-header__item--muted': part.muted");
        expect(slotComponent).toMatch(/<v-tooltip v-for="part in entry\.parts"[^>]*:text="part\.tooltip"/);
        expect(slotComponent).toMatch(/entries: \{\s*type: Array,\s*default: \(\) => \[\],/);
        expect(item).toContain('<span v-if="part.value" class="scene-header__value">{{ part.value }}</span>');
        expect(item).toContain('<span v-if="part.icon" class="scene-header__icon" role="img" :aria-label="part.label"><v-icon size="small">{{ part.icon }}</v-icon></span>');
        expect(item).toContain('<span v-else class="scene-header__label">{{ part.label }}</span>');
        expect(item).toContain('<v-icon v-if="part.trailingIcon"');
        expect(item).toContain('<span v-if="part.srText" class="d-sr-only">{{ part.srText }}</span>');
        expect(header.match(/<SceneHeaderSlot [^>]*\/>/g)).toEqual([
            '<SceneHeaderSlot v-if="!titleOnly" class="scene-header__slot scene-header__slot--slot_a" :entries="slotEntries(\'slot_a\')" :scene="scene" />',
            '<SceneHeaderSlot v-if="!titleOnly" class="scene-header__slot scene-header__slot--slot_b" :entries="slotEntries(\'slot_b\')" :scene="scene" />',
        ]);
    });

    it("renders a widget item as its component instead of text parts", () => {
        expect(slotComponent).toContain('<SceneHeaderCharacters v-if="entry.widget === \'characters\'" class="scene-header__widget" :characters="entry.characters" :hidden="entry.hidden" :scene="scene" />');
        expect(slotComponent).toContain('<SceneHeaderKnowledgeEffort v-else-if="entry.widget === \'knowledge_effort\'" class="scene-header__widget" :mode="entry.mode" />');
        expect(slotComponent).toContain('<SceneHeaderTemplateSelect v-else-if="entry.widget === \'template_select\'" :item="entry" />');
        expect(slotComponent).toMatch(/<template v-else>\s*<v-tooltip v-for="part in entry\.parts"/);
    });

    it("each slot resolves its own items in slot order", () => {
        const vm = { context: { scene: { data: {} }, agentStatus: {} }, slotIds: (slotId) => ({ slot_a: ["history_stats"], slot_b: ["summarizer", "history_stats"] })[slotId] };
        const slotEntries = lift(header, "slotEntries", "SceneHeader", { resolveSlotItems }).bind(vm);
        expect(slotEntries("slot_a").map((entry) => entry.id)).toEqual(["history_stats"]);
        expect(slotEntries("slot_b").map((entry) => entry.id)).toEqual(["summarizer", "history_stats"]);
    });
});

describe("scene header item picker", () => {
    it("gives each side its own menu, fed with that side's slot only", () => {
        const menus = header.match(/<SceneHeaderItemMenu [\s\S]*?\/>/g) || [];
        expect(menus).toEqual([
            '<SceneHeaderItemMenu :definition="slotDefinitions[0]" :catalog="catalog" :shown="slotIds(\'slot_a\')" @toggle="(itemId) => toggle(slotDefinitions[0], itemId)" />',
            '<SceneHeaderItemMenu :definition="slotDefinitions[1]" :catalog="catalog" :shown="slotIds(\'slot_b\')" @toggle="(itemId) => toggle(slotDefinitions[1], itemId)" />',
        ]);
        expect(SCENE_HEADER_SLOTS.map((slot) => slot.id)).toEqual(["slot_a", "slot_b"]);
        expect(itemMenu).toContain(':close-on-content-click="false"');
        expect(itemMenu).toContain("<v-list-subheader>{{ definition.label }}</v-list-subheader>");
        expect(itemMenu).toMatch(/<v-list class="scene-header-picker"[^>]*role="menu" :aria-label="definition\.label"/);
        expect(itemMenu).toContain('role="menuitemcheckbox"');
        expect(itemMenu).toContain(':aria-label="`Choose the scene header items ${sideLabel}`"');
        expect(itemMenu).not.toMatch(/slot_b|slotDefinitions/);
    });

    it("both menu buttons follow the close button's reveal rules", () => {
        const buttons = [...(header.match(/<v-btn[\s\S]*?\/>/g) || []), ...(itemMenu.match(/<v-btn[\s\S]*?\/>/g) || [])];
        expect(buttons).toHaveLength(2);
        for (const button of buttons) {
            expect(button).toContain('class="scene-header__action"');
        }
        expect(header).toMatch(/\.scene-header:focus-within :deep\(\.scene-header__action\)/);
        expect(header).toMatch(/@media \(hover: none\) \{\s*\.scene-header :deep\(\.scene-header__action\) \{\s*opacity: 1;/);
    });

    it("listens for the answers to its edits while mounted", () => {
        expect(lift(header, "created", "SceneHeader")).toBeTypeOf("function");
        expect(header).toMatch(/created\(\) \{\s*this\.registerMessageHandler\(this\.handleMessage\);/);
        expect(header).toMatch(/beforeUnmount\(\) \{\s*this\.unregisterMessageHandler\(this\.handleMessage\);/);
        // a lost connection clears sceneActive, which unmounts the header and its pending edits
        expect(app).toMatch(/onclose = [\s\S]*?this\.sceneActive = false;/);
        expect(app).toContain(':over-backdrop="!!sceneBackdropSrc"');
    });

    it("shows the saved selection of each slot", () => {
        const vm = picker({ slot_a: ["history_stats"], slot_b: ["summarizer"] });
        expect(vm.isShown("slot_a", "history_stats")).toBe(true);
        expect(vm.isShown("slot_a", "summarizer")).toBe(false);
        expect(vm.isShown("slot_b", "summarizer")).toBe(true);
        expect(picker({}).isShown("slot_a", "summarizer")).toBe(false);
    });

    it("sends each click as an edit of one slot", () => {
        const vm = picker({ slot_a: ["later", "history_stats"], slot_b: ["summarizer"] });
        vm.toggle(LEFT, "summarizer");
        vm.toggle(RIGHT, "summarizer");
        expect(vm.sent).toEqual([
            { type: "quick_settings", action: "set", setting: "scene_header_slot_a", value: { item: "summarizer", shown: true } },
            { type: "quick_settings", action: "set", setting: "scene_header_slot_b", value: { item: "summarizer", shown: false } },
        ]);
        expect(vm.slotIds("slot_a")).toEqual(["later", "history_stats", "summarizer"]);
        expect(vm.slotIds("slot_b")).toEqual([]);
    });

    it("click, click, first echo, click: the display and the saved list end as the user asked", () => {
        const vm = picker({ slot_a: [], slot_b: [] });
        vm.toggle(LEFT, "history_stats");
        vm.toggle(LEFT, "summarizer");
        vm.echoNext();
        // the echo of the first click must not undo the second on screen
        expect(vm.slotIds("slot_a")).toEqual(["history_stats", "summarizer"]);
        vm.toggle(LEFT, "history_stats");
        expect(vm.slotIds("slot_a")).toEqual(["summarizer"]);
        vm.echoNext();
        vm.echoNext();
        expect(vm.settings.slot_a).toEqual(["summarizer"]);
        expect(vm.pending.slot_a).toEqual([]);
        expect(vm.slotIds("slot_a")).toEqual(["summarizer"]);
    });

    it("an echo for one slot leaves the pending click of the other slot on screen", () => {
        const vm = picker({ slot_a: [], slot_b: [] });
        vm.toggle(LEFT, "history_stats");
        vm.toggle(RIGHT, "summarizer");
        vm.echoNext();
        expect(vm.isShown("slot_b", "summarizer")).toBe(true);
        vm.toggle(RIGHT, "history_stats");
        vm.echoNext();
        vm.echoNext();
        expect(vm.settings).toEqual({ slot_a: ["history_stats"], slot_b: ["summarizer", "history_stats"] });
        expect(vm.slotIds("slot_b")).toEqual(["summarizer", "history_stats"]);
    });

    it("an App Settings save shows through while an edit is still pending", () => {
        const vm = picker({ slot_a: ["history_stats"], slot_b: [] });
        vm.toggle(LEFT, "summarizer");
        vm.settings = { slot_a: ["later"], slot_b: [] };
        expect(vm.slotIds("slot_a")).toEqual(["later", "summarizer"]);
    });

    it("ignores set_done for other quick settings", () => {
        const vm = picker({ slot_a: [], slot_b: [] });
        vm.toggle(LEFT, "summarizer");
        vm.handleMessage({ type: "quick_settings", action: "set_done", data: { setting: "auto_save", value: true } });
        expect(vm.pending.slot_a).toHaveLength(1);
    });

    it("drops pending edits on a quick settings error", () => {
        const vm = picker({ slot_a: [], slot_b: [] });
        vm.toggle(LEFT, "summarizer");
        vm.toggle(RIGHT, "summarizer");
        vm.handleMessage({ type: "error", plugin: "quick_settings", error: "bad value" });
        expect(vm.slotIds("slot_a")).toEqual([]);
        expect(vm.slotIds("slot_b")).toEqual([]);
    });
});
