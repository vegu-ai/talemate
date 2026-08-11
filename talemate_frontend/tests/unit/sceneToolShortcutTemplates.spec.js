import { describe, it, expect } from "vitest";
import {
    applyShortcutTemplateMessage,
    shortcutAsTemplate,
    shortcutTemplatesForSection,
    templateGroupByName,
    templateSaveTransition,
    validateGroupName,
} from "@/utils/sceneToolShortcuts";

const CATALOG = [
    { id: "narrator.progress", section: "narrator", label: "Progress Story", per_character: false, include_unbound: false },
    { id: "narrator.look_at_character", section: "narrator", label: "Look at Character", per_character: true, include_unbound: false },
    { id: "conversation.request_actor_action", section: "actor", label: "Actor Action", per_character: true, include_unbound: true },
];

function template(uid, action_id, extra = {}) {
    return {
        uid,
        name: `${uid} template`,
        template_type: "scene_tool_shortcut",
        group: "group-uid",
        action_id,
        label: `${uid} label`,
        icon: "mdi-sword-cross",
        instructions: "",
        ...extra,
    };
}

describe("shortcutTemplatesForSection", () => {
    it("keeps the section's templates, paired with their action and keyed by the collection id", () => {
        const templates = {
            "g__a": template("a", "narrator.progress"),
            "g__b": template("b", "conversation.request_actor_action"),
            "g__c": template("c", "narrator.look_at_character"),
        };

        const rows = shortcutTemplatesForSection(templates, CATALOG, "narrator");

        expect(rows.map(row => row.key)).toEqual(["g__a", "g__c"]);
        expect(rows.map(row => row.template.uid)).toEqual(["a", "c"]);
        expect(rows.map(row => row.entry.id)).toEqual(["narrator.progress", "narrator.look_at_character"]);
    });

    it("hides a template whose action no longer exists", () => {
        const templates = {
            "g__a": template("a", "narrator.gone"),
            "g__b": template("b", "narrator.progress"),
        };

        expect(shortcutTemplatesForSection(templates, CATALOG, "narrator").map(row => row.template.uid)).toEqual(["b"]);
    });

    it("survives missing templates and an empty catalog", () => {
        expect(shortcutTemplatesForSection(null, CATALOG, "narrator")).toEqual([]);
        expect(shortcutTemplatesForSection({}, CATALOG, "narrator")).toEqual([]);
        expect(shortcutTemplatesForSection({ "g__a": template("a", "narrator.progress") }, null, "narrator")).toEqual([]);
    });
});

describe("shortcutAsTemplate", () => {
    const shortcut = {
        uid: "shortcut-uid",
        action_id: "narrator.progress",
        label: "  Push the plot  ",
        icon: "mdi-fire",
        instructions: "Move things along.",
    };

    it("maps the shortcut onto the template fields the backend expects", () => {
        expect(shortcutAsTemplate(shortcut, "group-uid", "template-uid")).toEqual({
            uid: "template-uid",
            name: "Push the plot",
            template_type: "scene_tool_shortcut",
            group: "group-uid",
            action_id: "narrator.progress",
            label: "Push the plot",
            icon: "mdi-fire",
            instructions: "Move things along.",
            favorite: false,
            priority: 1,
        });
    });

    it("never carries the shortcut uid over", () => {
        expect(shortcutAsTemplate(shortcut, "group-uid", "template-uid").uid).not.toBe(shortcut.uid);
    });

    it("defaults instructions to an empty string", () => {
        expect(shortcutAsTemplate({ ...shortcut, instructions: null }, "group-uid", "template-uid").instructions).toBe("");
        expect(shortcutAsTemplate({ ...shortcut, instructions: undefined }, "group-uid", "template-uid").instructions).toBe("");
    });
});

describe("applyShortcutTemplateMessage", () => {
    it("installs the template without running its action", () => {
        const shortcutTemplate = template("a", "narrator.progress");

        expect(applyShortcutTemplateMessage(shortcutTemplate)).toEqual({
            type: "world_state_manager",
            action: "apply_template",
            template: shortcutTemplate,
            character_name: null,
            run_immediately: false,
        });
    });
});

describe("templateSaveTransition", () => {
    const pendingWithGroup = {
        template: template("a", "narrator.progress"),
        groupName: "Human",
        requestId: "request-uid",
    };
    const pendingWithoutGroup = {
        template: template("a", "narrator.progress", { group: null }),
        groupName: "My Shortcuts",
        groupUid: "new-group-uid",
        requestId: "request-uid",
    };

    function groupEcho(name, uid = "new-group-uid") {
        return {
            type: "world_state_manager",
            action: "template_group_saved",
            data: { group: { uid, name } },
        };
    }

    function templateEcho(uid) {
        return {
            type: "world_state_manager",
            action: "template_saved",
            data: { template: { uid } },
        };
    }

    function failureEcho(request_id, message = "Error during save_template: boom") {
        return {
            type: "world_state_manager",
            action: "operation_done",
            error: { message },
            request_id,
            failed_action: "save_template",
        };
    }

    it("sends the pending template once its group comes back, uid filled in", () => {
        const transition = templateSaveTransition(pendingWithoutGroup, groupEcho("My Shortcuts"));

        expect(transition.op).toBe("send-template");
        expect(transition.template).toEqual({ ...pendingWithoutGroup.template, group: "new-group-uid" });
        expect(pendingWithoutGroup.template.group).toBe(null);
    });

    it("matches the group echo on the uid the request minted, not the name", () => {
        expect(templateSaveTransition(pendingWithoutGroup, groupEcho("renamed on the way back")).op).toBe("send-template");
        expect(templateSaveTransition(pendingWithoutGroup, groupEcho("My Shortcuts", "somebody-elses-uid"))).toEqual({ op: "ignore" });
    });

    it("ignores the echo of a group somebody else saved", () => {
        expect(templateSaveTransition(pendingWithoutGroup, groupEcho("Their Shortcuts", "their-group-uid"))).toEqual({ op: "ignore" });
        expect(templateSaveTransition(pendingWithoutGroup, { type: "world_state_manager", action: "template_group_saved", data: {} })).toEqual({ op: "ignore" });
    });

    it("ignores a group echo when the pending save minted no group uid", () => {
        const pending = { ...pendingWithoutGroup, groupUid: null };
        expect(templateSaveTransition(pending, groupEcho("My Shortcuts"))).toEqual({ op: "ignore" });
    });

    it("ignores a group echo when the pending save already has its group", () => {
        expect(templateSaveTransition(pendingWithGroup, groupEcho("Human"))).toEqual({ op: "ignore" });
    });

    it("fails on an error envelope answering our request", () => {
        expect(templateSaveTransition(pendingWithGroup, failureEcho("request-uid"))).toEqual({
            op: "fail",
            message: "Error during save_template: boom",
        });
    });

    it("ignores an error envelope answering somebody else's request", () => {
        expect(templateSaveTransition(pendingWithGroup, failureEcho("other-request-uid"))).toEqual({ op: "ignore" });
        expect(templateSaveTransition(pendingWithGroup, failureEcho(undefined))).toEqual({ op: "ignore" });
    });

    it("never treats a bare operation_done as terminal", () => {
        expect(templateSaveTransition(pendingWithGroup, {
            type: "world_state_manager",
            action: "operation_done",
            data: {},
        })).toEqual({ op: "ignore" });
    });

    it("completes on the echo of the pending template", () => {
        expect(templateSaveTransition(pendingWithGroup, templateEcho("a"))).toEqual({ op: "complete" });
    });

    it("ignores the echo of another template", () => {
        expect(templateSaveTransition(pendingWithGroup, templateEcho("b"))).toEqual({ op: "ignore" });
        expect(templateSaveTransition(pendingWithGroup, { type: "world_state_manager", action: "template_saved", data: {} })).toEqual({ op: "ignore" });
    });

    it("ignores messages of other types and other world state manager actions", () => {
        expect(templateSaveTransition(pendingWithGroup, { type: "config", action: "template_saved", data: { template: { uid: "a" } } })).toEqual({ op: "ignore" });
        expect(templateSaveTransition(pendingWithGroup, { type: "world_state_manager", action: "templates" })).toEqual({ op: "ignore" });
    });

    it("ignores everything while nothing is pending", () => {
        expect(templateSaveTransition(null, templateEcho("a"))).toEqual({ op: "ignore" });
        expect(templateSaveTransition(undefined, groupEcho("My Shortcuts"))).toEqual({ op: "ignore" });
    });
});

describe("templateGroupByName", () => {
    const groups = [
        { uid: "uid-default", name: "default" },
        { uid: "uid-human", name: "Human" },
        { uid: "uid-mine", name: "My Shortcuts" },
    ];

    it("finds a group regardless of case and surrounding whitespace", () => {
        expect(templateGroupByName(groups, "Human").uid).toBe("uid-human");
        expect(templateGroupByName(groups, "  human ").uid).toBe("uid-human");
        expect(templateGroupByName(groups, "DEFAULT").uid).toBe("uid-default");
    });

    it("finds a group by the file name its name derives to", () => {
        expect(templateGroupByName(groups, "my-shortcuts").uid).toBe("uid-mine");
        expect(templateGroupByName(groups, "My  Shortcuts")).toBe(null);
        expect(templateGroupByName([{ uid: "uid-a", name: "a b c" }], "a-b-c").uid).toBe("uid-a");
    });

    it("returns null for a name no group carries", () => {
        expect(templateGroupByName(groups, "Their Shortcuts")).toBe(null);
    });

    it("returns null for an empty name or no groups", () => {
        expect(templateGroupByName(groups, "")).toBe(null);
        expect(templateGroupByName(groups, "   ")).toBe(null);
        expect(templateGroupByName(groups, null)).toBe(null);
        expect(templateGroupByName(null, "Human")).toBe(null);
    });
});

describe("validateGroupName", () => {
    it("passes a name that can become a file", () => {
        expect(validateGroupName("My Shortcuts")).toBe(true);
        expect(validateGroupName("my-shortcuts_2")).toBe(true);
        expect(validateGroupName("")).toBe(true);
        expect(validateGroupName(null)).toBe(true);
        expect(validateGroupName(undefined)).toBe(true);
    });

    it("rejects characters a file name may not carry", () => {
        for (const name of ['a/b', 'a\\b', 'a:b', 'a*b', 'a?b', 'a"b', 'a<b', 'a>b', 'a|b']) {
            expect(validateGroupName(name)).toBe("Name contains invalid characters");
        }
    });

    it("rejects a name that is only dots or whitespace", () => {
        expect(validateGroupName(".")).toBe("Name contains invalid characters");
        expect(validateGroupName("..")).toBe("Name contains invalid characters");
        expect(validateGroupName("   ")).toBe("Name contains invalid characters");
        expect(validateGroupName(" . ")).toBe("Name contains invalid characters");
    });
});
