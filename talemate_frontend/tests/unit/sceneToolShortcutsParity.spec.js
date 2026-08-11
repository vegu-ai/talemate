import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { fileURLToPath, URL } from "node:url";

const SECTION_COMPONENTS = {
    narrator: "SceneToolsNarrator.vue",
    actor: "SceneToolsActor.vue",
    director: "SceneToolsDirector.vue",
    visual: "SceneToolsVisual.vue",
};

// visual cases differ only in their VIS_TYPE constant, so a copy-paste that
// leaves the wrong one still dispatches every id — each case must name its own
const VISUAL_CASE_CONSTANTS = {
    "visual.visualize_environment_card": "VIS_TYPE.SCENE_CARD",
    "visual.visualize_environment_background": "VIS_TYPE.SCENE_BACKGROUND",
    "visual.visualize_character_card": "VIS_TYPE.CHARACTER_CARD",
    "visual.visualize_character_portrait": "VIS_TYPE.CHARACTER_PORTRAIT",
};

function read(path) {
    return readFileSync(fileURLToPath(new URL(path, import.meta.url)), "utf-8");
}

// the backend catalog is the single source of truth — parse it instead of
// mirroring it, so a new SceneToolAction with no frontend case fails here
function backendCatalog() {
    const source = read("../../../src/talemate/scene_tools.py");
    return {
        entries: [...source.matchAll(/id="([^"]+)",\s*section="([^"]+)"/g)].map(match => ({
            id: match[1],
            section: match[2],
        })),
        declared: [...source.matchAll(/(?<!class )SceneToolAction\(/g)].length,
    };
}

function runShortcutSwitch(component) {
    const source = read(`../../src/components/${component}`);

    const method = source.indexOf("runShortcut(");
    expect(method, `${component} has no runShortcut method`).toBeGreaterThan(-1);

    const switchIndex = source.indexOf("switch (", method);
    expect(switchIndex, `${component} runShortcut has no switch`).toBeGreaterThan(-1);

    const start = source.indexOf("{", switchIndex);
    let depth = 0;
    for (let i = start; i < source.length; i++) {
        if (source[i] === "{") {
            depth++;
        } else if (source[i] === "}") {
            depth--;
            if (depth === 0) {
                return source.slice(start, i + 1);
            }
        }
    }

    throw new Error(`${component} runShortcut switch is unbalanced`);
}

function caseBodies(switchBody) {
    const marks = [...switchBody.matchAll(/(?:case\s+'([^']+)'|default)\s*:/g)];
    const bodies = {};
    for (let i = 0; i < marks.length; i++) {
        const id = marks[i][1];
        if (!id) {
            continue;
        }
        const from = marks[i].index + marks[i][0].length;
        const to = i + 1 < marks.length ? marks[i + 1].index : switchBody.length;
        bodies[id] = switchBody.slice(from, to);
    }
    return bodies;
}

describe("scene tool shortcut dispatch parity", () => {
    const { entries: catalog, declared } = backendCatalog();

    it("parses the backend catalog", () => {
        expect(catalog.length).toBeGreaterThan(0);
        expect(catalog.length, "an entry escaped the id/section parse").toBe(declared);
        expect(new Set(catalog.map(entry => entry.section))).toEqual(
            new Set(Object.keys(SECTION_COMPONENTS)),
        );
    });

    for (const [section, component] of Object.entries(SECTION_COMPONENTS)) {
        it(`${component} handles every ${section} action in the catalog`, () => {
            const actions = catalog.filter(entry => entry.section === section).map(entry => entry.id);
            expect(actions.length, `no ${section} actions parsed from scene_tools.py`).toBeGreaterThan(0);

            const body = runShortcutSwitch(component);
            const cases = [...body.matchAll(/case\s+'([^']+)':/g)].map(match => match[1]);

            for (const action of actions) {
                expect(cases, action).toContain(action);
            }
        });

        it(`${component} warns about actions it does not know`, () => {
            expect(runShortcutSwitch(component)).toMatch(/default:\s*console\.warn\(/);
        });
    }

    it("SceneToolsVisual dispatches each action with its own vis type", () => {
        const bodies = caseBodies(runShortcutSwitch("SceneToolsVisual.vue"));
        const allConstants = Object.values(VISUAL_CASE_CONSTANTS);

        for (const [id, expected] of Object.entries(VISUAL_CASE_CONSTANTS)) {
            expect(bodies[id], `no case body for ${id}`).toBeDefined();
            expect(bodies[id], `${id} should dispatch with ${expected}`).toContain(expected);
            for (const other of allConstants) {
                if (other !== expected) {
                    expect(bodies[id], `${id} must not also reference ${other}`).not.toContain(other);
                }
            }
        }
    });
});
