import { describe, it, expect } from "vitest";
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath, URL } from "node:url";
import { THEME_COLOR_GROUPS, hydrateThemeTemplate, vuetifySlotName } from "@/utils/templateMappings";
import vuetify, { flattenThemeColors } from "@/plugins/vuetify";

function read(path) {
    return readFileSync(fileURLToPath(new URL(path, import.meta.url)), "utf-8");
}

const THEME_SOURCE = read("../../../src/talemate/world_state/templates/theme.py");

// the class body is every line up to the next top-level statement
function classBody(className) {
    const lines = THEME_SOURCE.split("\n");
    const start = lines.findIndex(line => line.startsWith(`class ${className}(`));
    expect(start, `theme.py has no class ${className}`).toBeGreaterThan(-1);

    const body = [];
    for (let i = start + 1; i < lines.length; i++) {
        if (lines[i].trim() !== "" && !/^\s/.test(lines[i])) {
            break;
        }
        body.push(lines[i]);
    }
    return body.join("\n");
}

function fieldNames(body) {
    return [...body.matchAll(/^ {4}(\w+)\s*:/gm)].map(match => match[1]);
}

// the backend models are the source of truth — parse them instead of mirroring
// them, so a slot added there with no frontend entry fails here
function backendGroups() {
    const body = classBody("ThemeColors");
    const groups = [...body.matchAll(/^ {4}(\w+)\s*:\s*([A-Z]\w+)\s*=/gm)].map(match => ({
        key: match[1],
        model: match[2],
    }));
    expect(groups.map(group => group.key), "a ThemeColors field escaped the group parse").toEqual(
        fieldNames(body),
    );

    for (const group of groups) {
        const groupBody = classBody(group.model);
        group.slots = [...groupBody.matchAll(/^ {4}(\w+)\s*:\s*str\s*=\s*"#[0-9A-Fa-f]{6}"/gm)].map(
            match => match[1],
        );
        // a slot declared in another form is not drift, but this test can no
        // longer see it — fail loudly rather than pass on a partial read
        expect(group.slots, `a field in ${group.model} escaped the slot parse`).toEqual(
            fieldNames(groupBody),
        );
    }

    return groups;
}

describe("theme color slot parity", () => {
    const groups = backendGroups();

    it("parses the backend color models", () => {
        expect(groups.length).toBeGreaterThan(0);
        for (const group of groups) {
            expect(group.slots.length, `no slots parsed from ${group.model}`).toBeGreaterThan(0);
        }
    });

    it("the theme editor renders every group and slot the backend ships", () => {
        expect(new Set(THEME_COLOR_GROUPS.map(group => group.key))).toEqual(
            new Set(groups.map(group => group.key)),
        );

        for (const group of groups) {
            const editor = THEME_COLOR_GROUPS.find(candidate => candidate.key === group.key);
            expect(new Set(editor.slots), `${group.key} slots differ from ${group.model}`).toEqual(
                new Set(group.slots),
            );
        }
    });

    it("vuetify merges every slot the backend ships, under the name vuetify knows", () => {
        for (const group of groups) {
            const payload = Object.fromEntries(group.slots.map(slot => [slot, "#010203"]));
            const flat = flattenThemeColors({ colors: { [group.key]: payload } });
            for (const slot of group.slots) {
                const name = vuetifySlotName(group.key, slot);
                expect(
                    flat?.[name],
                    `${group.key}.${slot} is missing from the vuetify merge as "${name}"`,
                ).toBe("#010203");
            }
        }
    });

    // the surface slots are the one group whose backend field names are not the
    // vuetify slot names - an underscore reaching vuetify paints nothing
    it("the surface slots reach vuetify hyphenated", () => {
        const surfaces = groups.find(group => group.key === "surfaces");
        expect(surfaces, "theme.py has no surfaces color group").toBeDefined();

        const payload = Object.fromEntries(surfaces.slots.map(slot => [slot, "#010203"]));
        const flat = flattenThemeColors({ colors: { surfaces: payload } });
        expect(Object.keys(flat).sort()).toEqual(
            surfaces.slots.map(slot => slot.replace(/_/g, "-")).sort(),
        );
    });

    // a slot name inside a `:color` prop is a free string that nothing checks,
    // so a component can name a slot the fallback theme never declares. until
    // the first app_config arrives, vuetify generates no rule for it and the
    // element draws uncolored. asserting the resolved value rather than the
    // source text also rejects a declared slot that resolves to undefined,
    // which is what a mistyped `colors.<name>.<shade>` produces.
    it("the fallback theme resolves every slot the backend ships to a color", () => {
        const fallback = vuetify.theme.themes.value.dark.colors;

        for (const group of groups) {
            for (const slot of group.slots) {
                const name = vuetifySlotName(group.key, slot);
                expect(
                    fallback[name],
                    `${group.key}.${slot} does not resolve to a color in the fallback theme`,
                ).toMatch(/^#[0-9a-fA-F]{6}$/);
            }
        }
    });

    // every one of these is a free string: vuetify puts the prop value straight
    // into a class name, so a slot that does not exist paints nothing at all and
    // the element silently falls back to its component default. a contrast walk
    // cannot see that - an element painting nothing usually measures a better
    // ratio than the wrong color it replaced.
    //
    // WHAT A GREEN RUN DOES NOT MEAN. This reads two shapes: a color attribute
    // in the template, and a `color:` key in a script block. It cannot follow a
    // color a function computes and returns, or one assembled from parts, and it
    // never sees the python side. Green means no dead literal in the shapes
    // below - not that the tree holds no dead binding.
    it("every color literal in the markup resolves to a real slot", () => {
        const componentDir = fileURLToPath(new URL("../../src", import.meta.url));
        const files = [];
        (function walk(dir) {
            for (const entry of readdirSync(dir, { withFileTypes: true })) {
                const full = join(dir, entry.name);
                if (entry.isDirectory()) walk(full);
                else if (entry.name.endsWith(".vue")) files.push(full);
            }
        })(componentDir);

        const resolved = vuetify.theme.themes.value.dark.colors;
        // vuetify's `isCssColor` accepts only `#`, `var(--`, `rgb(`, `rgba(`,
        // `hsl(` and `hsla(`; anything else becomes a class name. so `inherit`
        // and `currentColor` would be dead bindings too, and only these three
        // are real: no color at all, and vuetify's own bundled utilities
        const ALLOWED = new Set(["transparent", "", "white", "black"]);
        const CSS_COLOR = /^(#|var\(--|rgba?\(|hsla?\()/;
        const PROP = /(?:^|\s)(:?)(?:color|bg-color|track-color)="([^"]*)"/g;
        // a `color:` key in a script block - the map or options object a
        // component reads its color out of
        const SCRIPT_COLOR = /\bcolor:\s*'([^']*)'/g;
        // a `?` that opens a ternary, not the one in `?.` or `??`
        const TERNARY = /\?(?![.?])/;

        function literalsOf(raw, bound) {
            if (!bound) {
                return [raw];
            }
            const ternary = raw.match(TERNARY);
            if (ternary) {
                // only the branches are colors; the condition on the left may
                // hold a quoted string that is not one
                return quoted(raw.slice(ternary.index + 1));
            }
            if (raw.includes("||")) {
                // `expr || 'fallback'` - the fallback is a color
                return quoted(raw.slice(raw.indexOf("||")));
            }
            // a call hands its arguments to a helper: those strings are not
            // colors, and what the helper returns cannot be read from here
            if (raw.includes("(")) {
                return [];
            }
            if (raw.startsWith("'")) {
                return [raw.replace(/'/g, "")];
            }
            // a bare identifier is a variable holding the color
            return [];
        }

        function quoted(expr) {
            // a branch that is itself a call is opaque, so drop its arguments
            return [...expr.replace(/\w+\([^)]*\)/g, "").matchAll(/'([^']*)'/g)].map(m => m[1]);
        }

        const dead = [];
        for (const file of files) {
            const source = readFileSync(file, "utf-8");
            const found = [];
            for (const match of source.matchAll(PROP)) {
                found.push(...literalsOf(match[2].trim(), match[1] === ":"));
            }
            for (const match of source.matchAll(SCRIPT_COLOR)) {
                found.push(match[1]);
            }
            for (const value of found) {
                if (ALLOWED.has(value) || CSS_COLOR.test(value)) continue;
                if (resolved[value] === undefined) {
                    dead.push(`${file.slice(componentDir.length + 1)}: "${value}"`);
                }
            }
        }

        expect(
            dead,
            `color values vuetify cannot resolve - a palette name it does not ship, ` +
            `a theme slot that does not exist, or a word that is no color at all:\n${dead.join("\n")}`,
        ).toEqual([]);
    });

    it("the theme editor carries the backend's mode flag", () => {
        expect(classBody("Theme"), "theme.py Theme has no `dark` flag").toMatch(
            /^ {4}dark\s*:\s*bool\s*=/m,
        );
        expect(hydrateThemeTemplate({}, {}).dark).toBe(true);
        // an assignment, not the getter's comparison
        expect(read("../../src/components/TemplateTheme.vue")).toMatch(
            /this\.template\.dark\s*=(?!=)/,
        );
    });
});
