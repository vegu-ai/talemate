import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { fileURLToPath, URL } from "node:url";
import { DEFAULT_APPEARANCE_COLORS, getMessageColor } from "@/utils/messageColors";

// the unit suite runs in a node environment with no vue plugin, so the SFC
// cannot be imported — assert on its source instead
const SOURCE = readFileSync(
    fileURLToPath(new URL("../../src/components/AppConfigAppearanceScene.vue", import.meta.url)),
    "utf-8",
);

describe("AppConfigAppearanceScene color resolution", () => {
    it("resolves swatch colors through the shared helper", () => {
        expect(SOURCE).toContain("import { getMessageColor } from '@/utils/messageColors.js';");
        expect(SOURCE).toMatch(/getColor\(typ, color\) \{[\s\S]*?getMessageColor\([\s\S]*?this\.themeColors\)/);
        // the swatches diverged from the previews by resolving against the
        // built-in defaults directly, skipping the theme
        expect(SOURCE).not.toContain("DEFAULT_APPEARANCE_COLORS");
    });

    it("reaches the theme through the config prop the parent hands it", () => {
        expect(SOURCE).toMatch(/themeColors\(\) \{\s*return this\.immutableConfig\?\.theme\?\.colors/);
    });

    it("resets to a stored null so the theme applies", () => {
        expect(SOURCE).toMatch(/reset\(typ, config\) \{\s*config\.color = null;/);

        const theme = { messages: { narrator: "#00FF00" } };
        expect(getMessageColor({ scene: { narrator_messages: { color: null } } }, "narrator", theme)).toBe("#00FF00");
        expect(getMessageColor({ scene: { narrator_messages: { color: null } } }, "narrator", null)).toBe(
            DEFAULT_APPEARANCE_COLORS.narrator,
        );
    });
});
