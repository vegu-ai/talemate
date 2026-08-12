import { describe, it, expect } from "vitest";
import { newUuid } from "@/utils/uuid";

const UUID_V4 = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

describe("newUuid", () => {
    it("returns a v4 UUID string", () => {
        const uuid = newUuid();
        expect(uuid).toBeTypeOf("string");
        expect(uuid).toMatch(UUID_V4);
    });

    it("returns a different UUID on every call", () => {
        const uuids = new Set(Array.from({ length: 100 }, () => newUuid()));
        expect(uuids.size).toBe(100);
    });

    // the tests above run on the native path: this environment is a secure
    // context, and the uuid package short-circuits to crypto.randomUUID when
    // it exists. Plain HTTP is the case the helper is for, and there
    // randomUUID is absent — so take it away and check the fallback.
    /* eslint-disable no-restricted-properties -- taking the banned API away is
       the point of this test; it is the one place allowed to name it */
    it("still works where crypto.randomUUID does not exist", () => {
        const proto = Object.getPrototypeOf(globalThis.crypto);
        const saved = proto.randomUUID;
        delete proto.randomUUID;
        try {
            expect(globalThis.crypto.randomUUID).toBeUndefined();
            expect(newUuid()).toMatch(UUID_V4);
        } finally {
            proto.randomUUID = saved;
        }
    });
    /* eslint-enable no-restricted-properties */
});
