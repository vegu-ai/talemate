import { describe, it, expect } from "vitest";
import {
    argFields,
    buildArgs,
    groupByMenu,
    menuCommands,
} from "@/utils/sceneCommands";

function command(name, menu, args = []) {
    return {
        name,
        label: `${name} label`,
        icon: "mdi-sword",
        menu,
        args,
    };
}

const CATALOG = [
    command("attack", "combat", [{ name: "target", typ: "str" }]),
    command("defend", "combat"),
    command("rest", "camp"),
    command("debug", ""),
];

describe("menuCommands", () => {
    it("keeps only the commands that declare a menu", () => {
        expect(menuCommands(CATALOG).map(entry => entry.name)).toEqual(["attack", "defend", "rest"]);
    });

    it("treats a missing menu like an empty one", () => {
        const commands = [command("a", undefined), command("b", null), command("c", "tools")];

        expect(menuCommands(commands).map(entry => entry.name)).toEqual(["c"]);
    });

    it("survives an empty catalog", () => {
        expect(menuCommands([])).toEqual([]);
        expect(menuCommands(null)).toEqual([]);
        expect(menuCommands(undefined)).toEqual([]);
    });
});

describe("groupByMenu", () => {
    it("groups by menu id, alphabetically, keeping catalog order inside a group", () => {
        const groups = groupByMenu(CATALOG);

        expect(groups.map(group => group.menu)).toEqual(["camp", "combat"]);
        expect(groups[0].commands.map(entry => entry.name)).toEqual(["rest"]);
        expect(groups[1].commands.map(entry => entry.name)).toEqual(["attack", "defend"]);
    });

    it("drops typed-only commands", () => {
        const groups = groupByMenu(CATALOG);

        expect(groups.some(group => group.commands.some(entry => entry.name === "debug"))).toBe(false);
    });

    it("yields nothing for an empty or typed-only catalog", () => {
        expect(groupByMenu([])).toEqual([]);
        expect(groupByMenu(null)).toEqual([]);
        expect(groupByMenu([command("debug", ""), command("other", "")])).toEqual([]);
    });
});

describe("argFields", () => {
    it("maps every declared type onto its input", () => {
        const fields = argFields(command("x", "combat", [
            { name: "who", typ: "str" },
            { name: "count", typ: "int" },
            { name: "chance", typ: "float" },
            { name: "loud", typ: "bool" },
            { name: "items", typ: "list" },
            { name: "payload", typ: "any" },
        ]));

        expect(fields).toEqual([
            { name: "who", typ: "str", input: "text" },
            { name: "count", typ: "int", input: "number" },
            { name: "chance", typ: "float", input: "number" },
            { name: "loud", typ: "bool", input: "checkbox" },
            { name: "items", typ: "list", input: "textarea" },
            { name: "payload", typ: "any", input: "text" },
        ]);
    });

    it("falls back to a text input for an unknown or missing type", () => {
        const fields = argFields(command("x", "combat", [
            { name: "a", typ: "dict" },
            { name: "b" },
        ]));

        expect(fields.map(field => field.input)).toEqual(["text", "text"]);
    });

    it("survives a command without args", () => {
        expect(argFields(command("x", "combat"))).toEqual([]);
        expect(argFields({ name: "x" })).toEqual([]);
        expect(argFields(null)).toEqual([]);
    });
});

describe("buildArgs", () => {
    const fields = argFields(command("x", "combat", [
        { name: "who", typ: "str" },
        { name: "count", typ: "int" },
        { name: "chance", typ: "float" },
        { name: "loud", typ: "bool" },
        { name: "items", typ: "list" },
    ]));

    it("coerces number inputs and passes everything else through", () => {
        expect(buildArgs(fields, {
            who: "guard",
            count: "3",
            chance: "0.5",
            loud: true,
            items: "sword\nshield",
        })).toEqual({
            who: "guard",
            count: 3,
            chance: 0.5,
            loud: true,
            items: "sword\nshield",
        });
    });

    it("omits blank values so the backend defaults apply", () => {
        expect(buildArgs(fields, {
            who: "",
            count: null,
            chance: undefined,
            items: "",
        })).toEqual({});
    });

    it("never turns an empty number field into a zero", () => {
        expect(buildArgs(fields, { count: "" })).toEqual({});
        expect(buildArgs(fields, { count: null })).toEqual({});
        expect(buildArgs(fields, { count: 0 })).toEqual({ count: 0 });
    });

    it("passes a false checkbox through", () => {
        expect(buildArgs(fields, { loud: false })).toEqual({ loud: false });
    });

    it("keeps whitespace-only text as the caller typed it", () => {
        expect(buildArgs(fields, { who: " " })).toEqual({ who: " " });
    });

    it("ignores values that no field declares", () => {
        expect(buildArgs(fields, { who: "guard", stowaway: "nope" })).toEqual({ who: "guard" });
    });

    it("survives missing fields and values", () => {
        expect(buildArgs(null, { who: "guard" })).toEqual({});
        expect(buildArgs([], null)).toEqual({});
        expect(buildArgs(fields, null)).toEqual({});
    });
});
