import { describe, it, expect } from "vitest";
import { createConfigSaveQueue } from "@/utils/configSaveQueue";

describe("test setup", () => {
    it("resolves modules through the @ alias", () => {
        expect(createConfigSaveQueue).toBeTypeOf("function");
    });
});
