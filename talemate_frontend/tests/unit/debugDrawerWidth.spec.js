import { describe, expect, it } from "vitest";
import { readSource } from "./helpers/liftMethod.js";

const app = readSource("src/components/TalemateApp.vue");

describe("the debug tools drawer", () => {
    it("has a fixed width of 450 px", () => {
        const drawer = /<v-navigation-drawer v-model="debugDrawer"[^>]*>/.exec(app)?.[0];
        expect(drawer, "debug tools drawer").toBeTruthy();
        expect(drawer).toContain('width="450"');
        expect(drawer).toContain("disable-resize-watcher");
        expect(drawer).not.toMatch(/:width=|resizable/);
    });
});
