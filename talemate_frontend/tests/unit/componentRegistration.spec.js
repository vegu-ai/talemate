import { describe, it, expect } from "vitest";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath, URL } from "node:url";

const SRC = fileURLToPath(new URL("../../src", import.meta.url));

// registered on the component through a mixin's `components` option instead of
// its own, so the SFC that mounts it carries no import
const REGISTERED_BY_MIXIN = new Set(["EntityTooltip", "EntitySelectionAction"]);

const VUE_BUILT_INS = new Set([
    "Component",
    "KeepAlive",
    "Slot",
    "Suspense",
    "Teleport",
    "Transition",
    "TransitionGroup",
]);

function vueFiles(dir) {
    return readdirSync(dir).flatMap((entry) => {
        const path = join(dir, entry);
        if (statSync(path).isDirectory()) {
            return vueFiles(path);
        }
        return path.endsWith(".vue") ? [path] : [];
    });
}

function templateOf(source) {
    const match = source.match(/<template>([\s\S]*)<\/template>/);
    return (match ? match[1] : "").replace(/<!--[\s\S]*?-->/g, "");
}

function pascalCase(tag) {
    return tag
        .split("-")
        .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
        .join("");
}

/**
 * Every tag name the template opens.
 *
 * Walked rather than matched: quoting only means something between a tag's
 * `<` and its `>`, so an attribute hint like `messages="…<SECTION>…"` must not
 * read as a mount while an apostrophe in body text ("the scene's history")
 * must not swallow the markup that follows it.
 */
function mountedTags(template) {
    const tags = new Set();
    let i = 0;

    while (i < template.length) {
        if (template[i] !== "<") {
            i += 1;
            continue;
        }

        const opening = /^<([A-Za-z][A-Za-z0-9_-]*)/.exec(template.slice(i));
        if (!opening) {
            i += 1;
            continue;
        }

        tags.add(opening[1]);
        i += opening[0].length;

        let quote = null;
        while (i < template.length) {
            const char = template[i];
            i += 1;
            if (quote) {
                if (char === quote) quote = null;
            } else if (char === '"' || char === "'") {
                quote = char;
            } else if (char === ">") {
                break;
            }
        }
    }

    return tags;
}

// both casings Vue accepts for a registered component; `v-` is Vuetify's, whose
// components are registered globally by the plugin
function customTags(template) {
    const components = new Set();

    for (const tag of mountedTags(template)) {
        if (/^[A-Z]/.test(tag)) {
            components.add(tag);
        } else if (tag.includes("-") && !tag.startsWith("v-")) {
            components.add(pascalCase(tag));
        }
    }

    for (const builtIn of VUE_BUILT_INS) {
        components.delete(builtIn);
    }

    return [...components];
}

function componentsOf(path) {
    return customTags(templateOf(readFileSync(path, "utf8")));
}

describe("component registration", () => {
    it.each(vueFiles(SRC))("%s resolves every component it mounts", (path) => {
        const source = readFileSync(path, "utf8");
        const script = source.slice(source.indexOf("<script"));

        const missing = customTags(templateOf(source)).filter(
            (tag) =>
                !REGISTERED_BY_MIXIN.has(tag) &&
                !new RegExp(`\\b${tag}\\b`).test(script),
        );

        expect(missing).toEqual([]);
    });

    // the check above passes just as happily when the scan sees nothing, so
    // pin what it must see: a mount after body-text apostrophes, a mount whose
    // tag follows an attribute carrying angle brackets, and a kebab-case mount
    it.each([
        ["components/TalemateApp.vue", "SceneRevisions"],
        ["components/TalemateApp.vue", "SceneMessages"],
        ["components/ClientConfigEditor.vue", "AppConfigPresetsSystemPrompts"],
        ["components/DirectorConsoleSceneDirection.vue", "ConfirmActionInline"],
    ])("%s is scanned deeply enough to see %s", (file, component) => {
        expect(componentsOf(join(SRC, file))).toContain(component);
    });
});
