import { describe, expect, it } from "vitest";
import { readSource } from "./helpers/liftMethod.js";
import { colorForTemplate, iconForTemplate } from "@/utils/templateMappings.js";
import { templateTypeHelp, templateTypeItems, templateTypeTitle } from "@/utils/templateTypes.js";

const page = readSource("src/components/Templates.vue");

describe("template type list", () => {
    it("lists every type once, sorted by the name the user reads", () => {
        const items = templateTypeItems();
        expect(items.map((item) => item.title)).toEqual([
            "Agent persona",
            "Character attribute",
            "Character detail",
            "Scene tool shortcut",
            "Scene type",
            "Spice collection",
            "State reinforcement",
            "Theme",
            "Visual prompt finalizer",
            "Visual style",
            "Writing style",
        ]);
        expect(new Set(items.map((item) => item.value)).size).toBe(items.length);
    });

    it("gives each type the icon and colour of the shared template mappings", () => {
        for (const item of templateTypeItems()) {
            expect(item.icon).toBe(iconForTemplate({ template_type: item.value }));
            expect(item.color).toBe(colorForTemplate({ template_type: item.value }));
            expect(item.icon, `${item.value} falls back to the default icon`).not.toBe("mdi-cube-scan");
            expect(item.color, `${item.value} falls back to the default colour`).not.toBe("muted");
        }
        const spices = templateTypeItems().find((item) => item.value === "spices");
        expect(spices).toMatchObject({ title: "Spice collection", icon: "mdi-chili-mild", color: "highlight4" });
    });

    it("carries the help text and the name for a type, and the id for an unknown one", () => {
        expect(templateTypeHelp("theme")).toMatch(/^Theme templates hold a complete set of colors/);
        expect(templateTypeHelp("later")).toBeUndefined();
        expect(templateTypeTitle("visual_finalizer")).toBe("Visual prompt finalizer");
        expect(templateTypeTitle("later")).toBe("later");
    });
});

describe("the Templates page", () => {
    it("feeds the type selector and the overview from the same list", () => {
        expect(page).toContain("templateTypes: templateTypeItems(),");
        const select = /<v-select\s+v-model="template\.template_type"[\s\S]*?<\/v-select>/.exec(page)[0];
        expect(select).toContain(':items="templateTypes"');
        expect(page).toContain('v-for="templateType in templateTypes"');
        expect(page).not.toMatch(/helpMessages|sortedHelpMessages/);
    });

    it("shows the type icon in its colour on each selector item and on the selected value", () => {
        const select = /<v-select\s+v-model="template\.template_type"[\s\S]*?<\/v-select>/.exec(page)[0];
        const item = /<template v-slot:item="\{ props, item \}">[\s\S]*?<\/v-list-item>/.exec(select)[0];
        // opacity-100: a list item dims prepend icons, which would dull the type colour
        expect(item).toContain('<v-icon :color="item.color" class="opacity-100">{{ item.icon }}</v-icon>');
        const selection = /<template v-slot:selection="\{ item \}">[\s\S]*?<\/template>/.exec(select)[0];
        expect(selection).toContain('<v-icon :color="item.color" size="small" class="mr-2">{{ item.icon }}</v-icon>');
        expect(selection).toContain("{{ item.title }}");
    });
});
