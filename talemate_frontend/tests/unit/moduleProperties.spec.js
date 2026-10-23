import { describe, it, expect } from "vitest";
import { EDITABLE_MODULE_PROPERTY_TYPES, hasEditableProperties } from "@/utils/moduleProperties";

describe("EDITABLE_MODULE_PROPERTY_TYPES", () => {
    it("covers every type the properties panel renders an input for", () => {
        expect(EDITABLE_MODULE_PROPERTY_TYPES).toEqual([
            "str",
            "color",
            "int",
            "float",
            "bool",
            "text",
            "icon",
        ]);
    });
});

describe("hasEditableProperties", () => {
    it("finds an editable field among non-editable ones", () => {
        expect(hasEditableProperties({
            state: { type: "dict" },
            label: { type: "str" },
        })).toBe(true);
    });

    it("recognizes the types the toolbar button used to miss", () => {
        expect(hasEditableProperties({ icon: { type: "icon" } })).toBe(true);
        expect(hasEditableProperties({ color: { type: "color" } })).toBe(true);
    });

    it("returns false when no field is editable", () => {
        expect(hasEditableProperties({
            state: { type: "dict" },
            items: { type: "list" },
        })).toBe(false);
    });

    it("survives missing fields and malformed entries", () => {
        expect(hasEditableProperties({})).toBe(false);
        expect(hasEditableProperties(null)).toBe(false);
        expect(hasEditableProperties(undefined)).toBe(false);
        expect(hasEditableProperties({ broken: null })).toBe(false);
    });
});
