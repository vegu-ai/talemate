import { describe, it, expect, vi } from "vitest";
import { effect, reactive } from "vue";
import {
    buildNameKeyedPayload,
    cloneNameKeyedMap,
    hasOwnName,
    isReservedName,
    REACTIVITY_RESERVED_NAMES,
} from "@/utils/nameKeyedMap";
import { createConfigSaveQueue } from "@/utils/configSaveQueue";

// nothing stops a user from naming a client after a property of Object.prototype
const CLIENT_NAMES = ["__proto__", "constructor", "ok"];

function clientRows() {
    return CLIENT_NAMES.map((name, index) => ({
        name: name,
        type: "openai",
        max_token_length: 8192 + index,
    }));
}

describe("buildNameKeyedPayload", () => {
    it("gives every row its own key, whatever it is named", () => {
        const payload = buildNameKeyedPayload(clientRows(), (client) => ({ ...client }));

        expect(Object.keys(payload)).toEqual(CLIENT_NAMES);
        for (const name of CLIENT_NAMES) {
            expect(Object.prototype.hasOwnProperty.call(payload, name)).toBe(true);
        }
    });

    it("carries the row under '__proto__' instead of reassigning the prototype", () => {
        const payload = buildNameKeyedPayload(clientRows(), (client) => ({ ...client }));

        expect(Object.getPrototypeOf(payload)).toBe(null);
        expect(payload["__proto__"]).toEqual({
            name: "__proto__",
            type: "openai",
            max_token_length: 8192,
        });
    });

    it("stores what the entry mapper returns", () => {
        const payload = buildNameKeyedPayload(clientRows(), (client) => ({
            enabled: true,
            client: client.name,
        }));

        expect(payload.ok).toEqual({ enabled: true, client: "ok" });
    });

    it("survives the clone the config save makes of the payload", () => {
        const send = vi.fn();
        const queue = createConfigSaveQueue({
            send: send,
            getConfig: () => ({ clients: {}, agents: {} }),
            notifyError: vi.fn(),
            resetPendingSaves: vi.fn(),
        });

        queue.saveAppConfig((config) => {
            config.clients = buildNameKeyedPayload(clientRows(), (client) => ({ ...client }));
        }, { label: "clients" });

        const sent = send.mock.calls[0][0].config;
        expect(Object.keys(sent.clients)).toEqual(CLIENT_NAMES);
        expect(sent.clients["__proto__"].max_token_length).toBe(8192);
    });
});

describe("hasOwnName", () => {
    it("reports only the names the map actually carries", () => {
        const map = { ok: 1 };

        expect(hasOwnName(map, "ok")).toBe(true);
        expect(hasOwnName(map, "missing")).toBe(false);
    });

    it("does not report Object.prototype members as taken", () => {
        for (const name of ["__proto__", "constructor", "toString", "valueOf"]) {
            expect(hasOwnName({ ok: 1 }, name)).toBe(false);
        }
    });

    it("finds a name the map does carry, even a prototype member name", () => {
        const map = buildNameKeyedPayload(clientRows(), (client) => client);

        expect(hasOwnName(map, "__proto__")).toBe(true);
        expect(hasOwnName(map, "constructor")).toBe(true);
    });

    it("treats a missing map as empty", () => {
        expect(hasOwnName(undefined, "ok")).toBe(false);
        expect(hasOwnName(null, "toString")).toBe(false);
    });
});

describe("cloneNameKeyedMap", () => {
    it("keeps every entry under its own key, whatever it is named", () => {
        const source = buildNameKeyedPayload(clientRows(), (client) => client);
        const clone = cloneNameKeyedMap(source);

        expect(Object.keys(clone)).toEqual(CLIENT_NAMES);
        expect(Object.getPrototypeOf(clone)).toBe(null);
    });

    it("preserves a key that differs from the entry's own name", () => {
        // a hand-edited config can carry one; re-keying by `name` would drop
        // the original key, and the backend deletes by omission
        const clone = cloneNameKeyedMap({ oldKey: { name: "renamed" } });

        expect(Object.keys(clone)).toEqual(["oldKey"]);
        expect(clone.oldKey.name).toBe("renamed");
    });

    it("treats a missing map as empty", () => {
        expect(Object.keys(cloneNameKeyedMap(undefined))).toEqual([]);
    });
});

// Derived from Vue rather than restated: a blocklist written out by hand
// agrees with itself by construction and stays silent when Vue gains a key or
// the pin moves. For each candidate name this puts one entry in a config-shaped
// map, makes it reactive the way the settings pages do, and asks the four
// questions the pages depend on.
const VUE_INTERNAL_KEYS = [
    "__isVue", "__v_isRef", "__v_isReactive", "__v_isReadonly",
    "__v_isShallow", "__v_raw", "__v_skip",
];
const CANDIDATE_NAMES = [
    ...Object.getOwnPropertyNames(Object.prototype),
    ...VUE_INTERNAL_KEYS,
];

function usableAsName(name) {
    // the settings working copy is a JSON clone of the config
    const raw = JSON.parse(JSON.stringify({
        [name]: { name: name, max_token_length: 8192 },
        other: { name: "other", max_token_length: 1 },
    }));
    const map = reactive(raw);

    let runs = 0;
    effect(() => { runs++; JSON.stringify(map); });

    const entry = map[name];
    if (!entry || typeof entry !== "object" || entry.name !== name) {
        return false;                                   // lookup returns something else
    }

    const beforeEdit = runs;
    entry.max_token_length = 4096;
    if (runs === beforeEdit) {
        return false;                                   // the edit never arms Save
    }

    const beforeOther = runs;
    map.other.max_token_length = 99;
    if (runs === beforeOther) {
        return false;                                   // it broke tracking for everyone
    }

    // what the save would actually carry
    return Object.prototype.hasOwnProperty.call(JSON.parse(JSON.stringify(map)), name);
}

describe("isReservedName", () => {
    it("bans exactly the names a reactive config map cannot carry", () => {
        const unusable = CANDIDATE_NAMES.filter((name) => !usableAsName(name));

        expect(unusable.sort()).toEqual([...REACTIVITY_RESERVED_NAMES].sort());
    });

    it("agrees with the constant", () => {
        for (const name of REACTIVITY_RESERVED_NAMES) {
            expect(isReservedName(name)).toBe(true);
        }
        expect(isReservedName("ok")).toBe(false);
    });

    it("leaves the prototype member names that do work alone", () => {
        // these need only the null-prototype handling, not a ban
        for (const name of ["constructor", "toString", "valueOf", "isPrototypeOf"]) {
            expect(isReservedName(name)).toBe(false);
        }
    });
});
