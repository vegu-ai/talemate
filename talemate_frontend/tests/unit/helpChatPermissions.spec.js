import { describe, it, expect } from "vitest";
import { fileURLToPath, URL } from "node:url";
import { lift, readSource } from "./helpers/liftMethod.js";

function read(path) {
    return readSource(fileURLToPath(new URL(path, import.meta.url)));
}

const HELP_CHAT = read("../../src/components/HelpChat.vue");

// one entry of TalemateApp's agentStatus map, which flattens an agent_status
// frame: `actions` sits on the entry, not under a `data` key
function agentStatus({ settings = false, templates = false, warning = "Use a strong model." } = {}) {
    return {
        help: {
            name: "help",
            available: true,
            actions: {
                permissions: {
                    warning,
                    config: {
                        allow_settings_changes: {
                            label: "Allow changes to settings",
                            description: "Lets the help chat change your settings.",
                            value: settings,
                        },
                        allow_template_changes: {
                            label: "Allow changes to templates",
                            description: "Lets the help chat change your templates.",
                            value: templates,
                        },
                    },
                },
            },
        },
    };
}

const PERMISSION_CHIPS = [
    { key: "allow_settings_changes", label: "Settings", icon: "mdi-cog-outline" },
    { key: "allow_template_changes", label: "Templates", icon: "mdi-cube-scan" },
];

function chatStub(status, { canSave = true } = {}) {
    const saves = [];
    const stub = {
        agentStatus: status,
        saves,
        pendingPermissions: {},
        permissionError: null,
        saveAppConfig: (mutate, options) => {
            if(!canSave) return null;
            const config = { agents: { help: { actions: {} } } };
            mutate(config);
            saves.push({ config, options });
            return `req-${saves.length}`;
        },
        permissionGranted: lift(HELP_CHAT, "permissionGranted", "HelpChat.vue"),
        togglePermission: lift(HELP_CHAT, "togglePermission", "HelpChat.vue"),
        clearPendingPermission: lift(HELP_CHAT, "clearPendingPermission", "HelpChat.vue"),
        adoptPermissionState: lift(HELP_CHAT, "adoptPermissionState", "HelpChat.vue"),
    };

    // the computeds re-evaluate on read, the way Vue re-evaluates them, and
    // the methods reach each other through `this`
    for(const [name, deps] of [
        ["permissionConfig", {}],
        ["permissionChips", { PERMISSION_CHIPS }],
        ["permissionWarning", {}],
    ]) {
        const fn = lift(HELP_CHAT, name, "HelpChat.vue", deps);
        Object.defineProperty(stub, name, { get: () => fn.call(stub) });
    }
    for(const name of ["permissionGranted", "togglePermission", "clearPendingPermission", "adoptPermissionState"]) {
        const fn = stub[name];
        stub[name] = (...args) => fn.apply(stub, args);
    }
    return stub;
}

describe("help chat permission chips", () => {
    it("marks a granted permission and leaves the other alone", () => {
        const stub = chatStub(agentStatus({ templates: true }));
        const [settings, templates] = stub.permissionChips;

        expect(settings.granted).toBe(false);
        expect(templates.granted).toBe(true);
        expect(templates.label).toBe("Templates");
    });

    it("only a real true reads as granted", () => {
        const stub = chatStub(agentStatus({ settings: "false" }));

        expect(stub.permissionChips[0].granted).toBe(false);
    });

    it("takes the wording from the agent's own action config", () => {
        const stub = chatStub(agentStatus({ settings: true }));
        const [settings] = stub.permissionChips;

        expect(settings.tooltip).toContain("Allow changes to settings");
        expect(settings.tooltip).toContain("Lets the help chat change your settings.");
        expect(settings.tooltip).toContain("Click to revoke");
    });

    it("survives a status payload that carries no permissions yet", () => {
        const stub = chatStub({});

        expect(stub.permissionChips.every(chip => chip.granted === false)).toBe(true);
    });
});

describe("the note the chat shows while anything is granted", () => {
    it("stays away while both permissions are off", () => {
        const stub = chatStub(agentStatus());

        expect(stub.permissionWarning).toBeNull();
    });

    it("shows once - not per permission - and carries the agent's own text", () => {
        const stub = chatStub(
            agentStatus({ settings: true, templates: true, warning: "Use a strong model." })
        );

        expect(stub.permissionWarning).toBe("Use a strong model.");
    });

    it("shows when only one of the two is granted", () => {
        const stub = chatStub(agentStatus({ templates: true }));

        expect(stub.permissionWarning).toBe("Use a strong model.");
    });
});

describe("a click that has not been echoed yet", () => {
    it("a second click revokes rather than re-sending the first value", () => {
        const stub = chatStub(agentStatus());

        stub.togglePermission("allow_template_changes");
        // the agent status has not caught up - the chip is the only state
        stub.togglePermission("allow_template_changes");

        const written = stub.saves.map(
            (save) => save.config.agents.help.actions.permissions.config.allow_template_changes.value
        );
        expect(written).toEqual([true, false]);
    });

    it("shows the asked-for value until the agent reports it", () => {
        const stub = chatStub(agentStatus());

        stub.togglePermission("allow_settings_changes");
        expect(stub.permissionGranted("allow_settings_changes")).toBe(true);

        // the frame lands carrying the new value
        stub.adoptPermissionState({ allow_settings_changes: { value: true } });
        expect(stub.pendingPermissions).toEqual({});
        stub.agentStatus = agentStatus({ settings: true });
        expect(stub.permissionGranted("allow_settings_changes")).toBe(true);
    });

    it("keeps waiting while the frame still carries the old value", () => {
        const stub = chatStub(agentStatus());

        stub.togglePermission("allow_settings_changes");
        stub.adoptPermissionState({ allow_settings_changes: { value: false } });

        expect(stub.pendingPermissions).toEqual({ allow_settings_changes: true });
    });

    it("falls back to the agent's value when the save is refused", () => {
        const stub = chatStub(agentStatus());

        stub.togglePermission("allow_template_changes");
        stub.saves[0].options.onError();

        expect(stub.pendingPermissions).toEqual({});
        expect(stub.permissionGranted("allow_template_changes")).toBe(false);
    });

    it("says so when the save could not be sent at all", () => {
        const stub = chatStub(agentStatus(), { canSave: false });

        stub.togglePermission("allow_settings_changes");

        expect(stub.pendingPermissions).toEqual({});
        expect(stub.permissionError).toMatch(/not ready yet/);
    });
});

describe("toggling a permission from the chat", () => {
    it("writes the flipped value into the agent's config", () => {
        const stub = chatStub(agentStatus({ templates: true }));

        stub.togglePermission("allow_template_changes");

        const { config, options } = stub.saves[0];
        expect(
            config.agents.help.actions.permissions.config.allow_template_changes.value
        ).toBe(false);
        expect(options.label).toBe("help agent permissions");
    });

    it("grants a permission that was never persisted", () => {
        const stub = chatStub({});

        stub.togglePermission("allow_settings_changes");

        expect(
            stub.saves[0].config.agents.help.actions.permissions.config
                .allow_settings_changes.value
        ).toBe(true);
    });
});
