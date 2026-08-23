import { describe, it, expect } from "vitest";
import { fileURLToPath, URL } from "node:url";
import { lift, readSource } from "./helpers/liftMethod.js";

function read(path) {
    return readSource(fileURLToPath(new URL(path, import.meta.url)));
}

const TEMPLATES = read("../../src/components/Templates.vue");
const APP = read("../../src/components/TalemateApp.vue");

// the templates tab as the help agent sees it: its own flag plus the flag of
// whichever template editor is mounted, which is where keystrokes since the
// last blur and an open color picker live
function templatesStub({ dirty = false, editorDirty = null, groupDirty = false, selected = null, template = null } = {}) {
    const sent = [];
    return {
        dirty,
        groupDirty,
        selected,
        template,
        group: null,
        templates: null,
        deferredSelect: null,
        externalChange: false,
        adoptedSnapshot: null,
        formValid: true,
        sent,
        $refs: {
            form: { validate: () => {} },
            ...(editorDirty === null ? {} : { templateEditor: { dirty: editorDirty } }),
        },
        getWebsocket: () => ({ send: (payload) => sent.push(JSON.parse(payload)) }),
        uxSnapshot: lift(TEMPLATES, "uxSnapshot", "Templates.vue"),
        editorDirty: lift(TEMPLATES, "editorDirty", "Templates.vue"),
        onTemplatesPushed: lift(TEMPLATES, "onTemplatesPushed", "Templates.vue"),
        adoptSelection: lift(TEMPLATES, "adoptSelection", "Templates.vue"),
        rememberAdopted: lift(TEMPLATES, "rememberAdopted", "Templates.vue"),
        saveTemplate: lift(TEMPLATES, "saveTemplate", "Templates.vue"),
        selectTemplate: lift(TEMPLATES, "selectTemplate", "Templates.vue"),
        selectedGroups: [],
        $emit: () => {},
    };
}

// one group holding one theme, the shape the backend pushes
function tree(narrator) {
    return {
        managed: {
            groups: [
                {
                    uid: "group-1",
                    name: "My Themes",
                    templates: {
                        "theme-1": {
                            uid: "theme-1",
                            name: "Midnight",
                            template_type: "theme",
                            colors: { messages: { narrator } },
                        },
                    },
                },
            ],
        },
    };
}

// the tab sitting on a selected theme, as after a selectTemplate
function editingStub(options = {}) {
    const stub = templatesStub(options);
    const initial = tree("#A180AE");
    stub.onTemplatesPushed(initial);
    stub.group = initial.managed.groups[0];
    stub.template = initial.managed.groups[0].templates["theme-1"];
    stub.rememberAdopted();
    return stub;
}

describe("Templates.vue uxSnapshot", () => {
    it("reports a clean tab as not dirty", () => {
        const snapshot = templatesStub().uxSnapshot();

        expect(snapshot.tab).toBe("templates");
        expect(snapshot.dirty).toBe(false);
    });

    it("reports the tab's own pending save", () => {
        expect(templatesStub({ dirty: true }).uxSnapshot().dirty).toBe(true);
    });

    it("reports an unsaved edit held by the mounted template editor", () => {
        // the editors save through the parent, so the parent's flag stays false
        // while a picker is open - reading only that would disarm the guard
        const stub = templatesStub({ editorDirty: true });

        expect(stub.uxSnapshot().dirty).toBe(true);
    });

    it("carries the selected template and its type", () => {
        const stub = templatesStub({
            selected: ["group__theme"],
            template: { template_type: "theme" },
        });

        const snapshot = stub.uxSnapshot();

        expect(snapshot.selected).toBe("group__theme");
        expect(snapshot.template_type).toBe("theme");
    });
});

describe("TalemateApp buildUxSnapshot", () => {
    function appStub(templatesSnapshot) {
        return {
            tab: "templates",
            sceneDrawer: false,
            drawer: false,
            debugDrawer: false,
            directorConsoleDrawer: false,
            sceneActive: false,
            scene: null,
            ready: true,
            waitingForInput: false,
            $refs: {
                appSettings: null,
                templates: templatesSnapshot
                    ? { uxSnapshot: () => templatesSnapshot }
                    : null,
            },
            buildUxSnapshot: lift(APP, "buildUxSnapshot", "TalemateApp.vue"),
        };
    }

    it("carries the templates tab into the snapshot the help chat sends", () => {
        const snapshot = appStub({ tab: "templates", dirty: true }).buildUxSnapshot();

        expect(snapshot.templates_view).toEqual({ tab: "templates", dirty: true });
    });

    it("reports no templates view when the tab was never mounted", () => {
        expect(appStub(null).buildUxSnapshot().templates_view).toBeNull();
    });
});

describe("a theme write from the help chat reaching the open editor", () => {
    it("hands the editor the written template when nothing is unsaved", () => {
        const stub = editingStub();

        // the agent wrote the greener narrator; the backend pushed the tree
        stub.onTemplatesPushed(tree("#8FBC8F"));

        // the object the editor saves from is the written one, so its next save
        // cannot put the pre-write color back
        expect(stub.template.colors.messages.narrator).toBe("#8FBC8F");
        expect(stub.externalChange).toBe(false);
    });

    it("keeps the user's unsaved copy and flags the collision", () => {
        const stub = editingStub({ editorDirty: true });

        stub.onTemplatesPushed(tree("#8FBC8F"));

        expect(stub.template.colors.messages.narrator).toBe("#A180AE");
        expect(stub.externalChange).toBe(true);
    });

    it("does not flag the push that echoes this view's own save", () => {
        // the sequence that reaches the comparison: this view saves, the user
        // starts the next edit, and only then does the echo of that save arrive
        const stub = editingStub();
        stub.template.colors.messages.narrator = "#8FBC8F";
        stub.saveTemplate();
        expect(stub.sent).toHaveLength(1);
        stub.$refs.templateEditor = { dirty: true };

        stub.onTemplatesPushed(tree("#8FBC8F"));

        expect(stub.externalChange).toBe(false);
        // and the user's in-flight edit is still theirs
        expect(stub.template.colors.messages.narrator).toBe("#8FBC8F");
    });

    it("flags a foreign write that lands between this view's save and its echo", () => {
        const stub = editingStub();
        stub.template.colors.messages.narrator = "#8FBC8F";
        stub.saveTemplate();
        stub.$refs.templateEditor = { dirty: true };

        stub.onTemplatesPushed(tree("#123456"));

        expect(stub.externalChange).toBe(true);
    });

    it("re-adopts the group so a group edit is not saved from a stale copy", () => {
        const stub = editingStub();
        const pushed = tree("#8FBC8F");
        pushed.managed.groups[0].name = "Renamed";

        stub.onTemplatesPushed(pushed);

        expect(stub.group.name).toBe("Renamed");
    });
});

// any get_templates from anywhere in the app pushes this tree - DirectorConsole,
// the world editor and the app shell all send one - so the adoption has to hold
// for every editor, not only the one the help agent writes to
function attributeTree(question, groupName = "My Templates") {
    return {
        managed: {
            groups: [
                {
                    uid: "group-1",
                    name: groupName,
                    description: "",
                    templates: {
                        "attr-1": {
                            uid: "attr-1",
                            name: "Motivation",
                            template_type: "character_attribute",
                            question,
                        },
                        "attr-2": {
                            uid: "attr-2",
                            name: "Age",
                            template_type: "character_attribute",
                            question: "how old are they",
                        },
                    },
                },
            ],
        },
    };
}

function editingAttributeStub(options = {}) {
    const stub = templatesStub(options);
    const initial = attributeTree("what drives them");
    stub.onTemplatesPushed(initial);
    stub.group = initial.managed.groups[0];
    stub.template = initial.managed.groups[0].templates["attr-1"];
    stub.rememberAdopted();
    return stub;
}

describe("a push while another editor or the group form holds typed input", () => {
    it("keeps an unsaved edit in a non-theme editor", () => {
        const stub = editingAttributeStub({ editorDirty: true });
        stub.template.question = "what drives them, at length, unsaved";

        stub.onTemplatesPushed(attributeTree("what drives them"));

        expect(stub.template.question).toBe("what drives them, at length, unsaved");
    });

    it("adopts into a non-theme editor once it is clean", () => {
        const stub = editingAttributeStub();

        stub.onTemplatesPushed(attributeTree("what drives them, rewritten elsewhere"));

        expect(stub.template.question).toBe("what drives them, rewritten elsewhere");
    });

    it("keeps text typed into the group form", () => {
        // the group form has no editor of its own - it binds onto this.group and
        // saves on blur, so an unadopted push is the only thing protecting it
        const stub = editingAttributeStub({ groupDirty: true });
        stub.group.description = "Themes I use for late night play";

        stub.onTemplatesPushed(attributeTree("what drives them"));

        expect(stub.group.description).toBe("Themes I use for late night play");
    });

    it("adopts the group once the form is clean", () => {
        const stub = editingAttributeStub();

        stub.onTemplatesPushed(attributeTree("what drives them", "Renamed elsewhere"));

        expect(stub.group.name).toBe("Renamed elsewhere");
    });
});

describe("flags that would otherwise read clean while typing is unsaved", () => {
    it("re-arms when the form refuses to send", () => {
        // every editor clears its own flag before it emits, so a save the parent
        // then refuses on validation leaves the typed value recorded nowhere
        const stub = editingAttributeStub({ editorDirty: false });
        stub.formValid = false;
        stub.template.question = "typed, and the form is invalid";

        stub.saveTemplate();

        expect(stub.sent).toHaveLength(0);
        expect(stub.editorDirty()).toBe(true);

        stub.onTemplatesPushed(attributeTree("what drives them"));

        expect(stub.template.question).toBe("typed, and the form is invalid");
    });

    it("does not carry a flag into the next selection", () => {
        // otherwise an invalid form latches the flag on for the session and no
        // push is ever adopted again
        const stub = editingAttributeStub();
        stub.formValid = false;
        stub.saveTemplate();
        stub.groupDirty = true;
        expect(stub.editorDirty()).toBe(true);

        stub.selectTemplate("group-1__attr-2");

        expect(stub.dirty).toBe(false);
        expect(stub.groupDirty).toBe(false);
        expect(stub.template.uid).toBe("attr-2");
    });
});

describe("the markup the gate is carried by", () => {
    it("puts the shared editor ref on every template editor branch", () => {
        // the specs above drive lifted method bodies against a hand-built $refs,
        // so a branch that loses the attribute fails nothing else
        const branches = TEMPLATES.match(/v-(?:else-)?if="template\.template_type === '/g) || [];
        const refs = TEMPLATES.match(/ref="templateEditor"/g) || [];

        expect(branches.length).toBeGreaterThan(10);
        expect(refs).toHaveLength(branches.length);
    });
});
