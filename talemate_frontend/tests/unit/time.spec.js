import { describe, it, expect } from "vitest";
import { UNIT_SECONDS, amountUnitToSeconds, secondsToAmountUnit } from "@/utils/time";

const UNITS = ["minutes", "hours", "days", "weeks", "months", "years"];

describe("UNIT_SECONDS", () => {
    it("pins the second counts the backend uses and stays frozen", () => {
        expect(UNIT_SECONDS).toEqual({
            minutes: 60,
            hours: 3600,
            days: 86400,
            weeks: 604800,
            months: 2592000,
            years: 31536000,
        });
        expect(Object.isFrozen(UNIT_SECONDS)).toBe(true);
    });
});

describe("amountUnitToSeconds", () => {
    it("multiplies the amount by the unit", () => {
        expect(amountUnitToSeconds(5, "minutes")).toBe(300);
        expect(amountUnitToSeconds(12, "hours")).toBe(43200);
        expect(amountUnitToSeconds(2, "weeks")).toBe(1209600);
        expect(amountUnitToSeconds(10, "years")).toBe(315360000);
    });

    it("always yields a non-negative integer", () => {
        expect(amountUnitToSeconds(-3, "hours")).toBe(10800);
        expect(amountUnitToSeconds(1.5, "hours")).toBe(7200);
        expect(amountUnitToSeconds(null, "hours")).toBe(0);
        expect(amountUnitToSeconds(undefined, "days")).toBe(0);
    });

    it("rejects a unit the picker does not offer", () => {
        expect(() => amountUnitToSeconds(1, "fortnights")).toThrow("Invalid unit: fortnights");
        expect(() => amountUnitToSeconds(1, "seconds")).toThrow("Invalid unit: seconds");
    });
});

describe("secondsToAmountUnit", () => {
    it("round-trips what the user picked, so editing a passage shows it back", () => {
        for (const unit of UNITS) {
            for (const amount of [1, 2, 3, 5, 11]) {
                expect(secondsToAmountUnit(amountUnitToSeconds(amount, unit))).toEqual({ amount, unit });
            }
        }
    });

    it("cannot tell a duration apart from its larger equivalent", () => {
        expect(secondsToAmountUnit(amountUnitToSeconds(30, "days"))).toEqual({ amount: 1, unit: "months" });
        expect(secondsToAmountUnit(amountUnitToSeconds(24, "hours"))).toEqual({ amount: 1, unit: "days" });
        expect(secondsToAmountUnit(amountUnitToSeconds(7, "days"))).toEqual({ amount: 1, unit: "weeks" });
    });

    it("picks the largest unit that divides evenly", () => {
        expect(secondsToAmountUnit(7200)).toEqual({ amount: 2, unit: "hours" });
        expect(secondsToAmountUnit(259200)).toEqual({ amount: 3, unit: "days" });
        expect(secondsToAmountUnit(1209600)).toEqual({ amount: 2, unit: "weeks" });
        expect(secondsToAmountUnit(31536000)).toEqual({ amount: 1, unit: "years" });
    });

    it("falls back to the next unit down when the larger one leaves a remainder", () => {
        expect(secondsToAmountUnit(5400)).toEqual({ amount: 90, unit: "minutes" });
        expect(secondsToAmountUnit(90000)).toEqual({ amount: 25, unit: "hours" });
        expect(secondsToAmountUnit(3888000)).toEqual({ amount: 45, unit: "days" });
    });

    it("rounds a sub-minute duration up to a whole minute", () => {
        expect(secondsToAmountUnit(30)).toEqual({ amount: 1, unit: "minutes" });
        expect(secondsToAmountUnit(1)).toEqual({ amount: 1, unit: "minutes" });
        expect(secondsToAmountUnit(95)).toEqual({ amount: 2, unit: "minutes" });
    });

    it("treats a missing or empty duration as zero minutes", () => {
        expect(secondsToAmountUnit(0)).toEqual({ amount: 0, unit: "minutes" });
        expect(secondsToAmountUnit(null)).toEqual({ amount: 0, unit: "minutes" });
        expect(secondsToAmountUnit(undefined)).toEqual({ amount: 0, unit: "minutes" });
        expect(secondsToAmountUnit("not a duration")).toEqual({ amount: 0, unit: "minutes" });
    });

    it("reads a numeric string the way the websocket would send it", () => {
        expect(secondsToAmountUnit("3600")).toEqual({ amount: 1, unit: "hours" });
    });

    it("ignores the sign of a negative duration", () => {
        expect(secondsToAmountUnit(-86400)).toEqual({ amount: 1, unit: "days" });
    });
});
