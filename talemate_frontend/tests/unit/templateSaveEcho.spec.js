import { describe, it, expect } from "vitest";
import { adoptedTemplateUid } from "@/utils/templateSaveEcho";

const CREATE_FORM = {
    template_type: "scene_tool_shortcut",
    name: "Push the plot",
    group: "group-uid",
    priority: 1,
};

function echo(extra = {}) {
    return { ...CREATE_FORM, uid: "minted-uid", ...extra };
}

describe("adoptedTemplateUid", () => {
    it("hands the create form the uid the backend minted for it", () => {
        expect(adoptedTemplateUid(CREATE_FORM, echo())).toBe("minted-uid");
    });

    it("leaves a template that already has a uid alone", () => {
        expect(adoptedTemplateUid({ ...CREATE_FORM, uid: "own-uid" }, echo())).toBe(null);
    });

    it("ignores the echo of a template saved elsewhere", () => {
        expect(adoptedTemplateUid(CREATE_FORM, echo({ name: "Somebody else's" }))).toBe(null);
        expect(adoptedTemplateUid(CREATE_FORM, echo({ template_type: "writing_style" }))).toBe(null);
        expect(adoptedTemplateUid(CREATE_FORM, echo({ group: "other-group-uid" }))).toBe(null);
    });

    it("never adopts a uid the echo does not carry", () => {
        expect(adoptedTemplateUid(CREATE_FORM, echo({ uid: null }))).toBe(null);
        expect(adoptedTemplateUid(CREATE_FORM, {})).toBe(null);
        expect(adoptedTemplateUid(CREATE_FORM, null)).toBe(null);
        expect(adoptedTemplateUid(CREATE_FORM, undefined)).toBe(null);
    });

    it("survives having no template open", () => {
        expect(adoptedTemplateUid(null, echo())).toBe(null);
        expect(adoptedTemplateUid(undefined, echo())).toBe(null);
    });

    it("ignores an echo that carries no identity at all", () => {
        expect(adoptedTemplateUid(CREATE_FORM, { uid: "minted-uid" })).toBe(null);
    });
});
