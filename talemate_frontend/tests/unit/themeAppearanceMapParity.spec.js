import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { fileURLToPath, URL } from "node:url";
import { THEME_APPEARANCE_MAP } from "@/utils/templateMappings";

function read(path) {
    return readFileSync(fileURLToPath(new URL(path, import.meta.url)), "utf-8");
}

// the backend map is the source of truth — parse it instead of mirroring it, so
// a type added, renamed or dropped there fails here
function backendMap() {
    const source = read("../../../src/talemate/world_state/manager.py");
    const dict = source.match(/^THEME_APPEARANCE_MAP = \{\n([\s\S]*?)^\}$/m);
    expect(dict, "manager.py has no THEME_APPEARANCE_MAP dict").not.toBeNull();

    const body = dict[1].split("\n").filter(line => line.trim() !== "");
    const pairs = [...dict[1].matchAll(/^ {4}"(\w+)": "(\w+)",$/gm)].map(match => [
        match[1],
        match[2],
    ]);
    // an entry written in another form is not drift, but this test can no
    // longer see it — fail loudly rather than pass on a partial read
    expect(pairs.length, "an entry escaped the pair parse").toBe(body.length);

    return Object.fromEntries(pairs);
}

describe("theme appearance map parity", () => {
    const backend = backendMap();

    it("parses the backend map", () => {
        expect(Object.keys(backend).length).toBeGreaterThan(0);
    });

    it("maps exactly the theme keys the backend maps", () => {
        expect(new Set(Object.keys(THEME_APPEARANCE_MAP))).toEqual(new Set(Object.keys(backend)));
    });

    it("maps every theme key to the config key the backend does", () => {
        expect(THEME_APPEARANCE_MAP).toEqual(backend);
    });
});
