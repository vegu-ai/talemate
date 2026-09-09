import { describe, it, expect } from "vitest";
import { statusTransition } from "@/utils/statusNotification";

function status(statusValue, message = "", data = null) {
    return { type: "status", status: statusValue, message, data };
}

describe("statusTransition", () => {
    it("shows an incoming status", () => {
        expect(statusTransition("", status("busy", "Generating..."))).toEqual({
            op: "show",
            text: "Generating...",
            parts: [{ text: "Generating...", name: false }],
            type: "busy",
            cancellable: false,
        });
    });

    it("carries the chunks of a label the backend split, so the names can be painted", () => {
        const label = [
            { text: "Looking at ", name: false },
            { text: "Mara", name: true },
        ];
        expect(statusTransition("", status("busy", "Looking at Mara", { label })).parts).toEqual(label);
    });

    it("shows a message the backend did not split as one plain chunk", () => {
        for (const data of [null, {}, { label: [] }, { label: "Looking at Mara" }]) {
            expect(statusTransition("", status("busy", "Looking at Mara", data)).parts)
                .toEqual([{ text: "Looking at Mara", name: false }]);
        }
    });

    it("reads a chunk that carries no text as empty and no name", () => {
        const label = [{ name: true }, { text: "!", name: "yes" }];
        expect(statusTransition("", status("busy", "x", { label })).parts).toEqual([
            { text: "", name: true },
            { text: "!", name: true },
        ]);
    });

    it("carries the cancellable flag of the message", () => {
        expect(statusTransition("", status("busy", "Generating...", { cancellable: true })).cancellable).toBe(true);
        expect(statusTransition("", status("busy", "Generating...", { cancellable: false })).cancellable).toBe(false);
    });

    it("clears a busy toast on the trailing idle empty", () => {
        expect(statusTransition("busy", status("idle"))).toEqual({ op: "clear" });
        expect(statusTransition("", status("idle"))).toEqual({ op: "clear" });
    });

    it("leaves a terminal toast alone on the trailing idle empty", () => {
        for (const type of ["success", "error", "warning", "info"]) {
            expect(statusTransition(type, status("idle"))).toEqual({ op: "ignore" });
        }
    });

    it("still shows an idle status that carries a message", () => {
        expect(statusTransition("success", status("idle", "Done")).op).toBe("show");
    });

    it("ignores a status that is rendered as a scene message", () => {
        expect(statusTransition("busy", status("success", "Saved", { as_scene_message: true }))).toEqual({ op: "ignore" });
    });

    it("ignores messages that are not statuses", () => {
        expect(statusTransition("busy", { type: "scene_status", status: "idle", message: "" })).toEqual({ op: "ignore" });
        expect(statusTransition("busy", null)).toEqual({ op: "ignore" });
        expect(statusTransition("busy", undefined)).toEqual({ op: "ignore" });
    });
});
