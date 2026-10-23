import { describe, it, expect } from "vitest";
import { fileURLToPath, URL } from "node:url";
import { lift, readSource } from "./helpers/liftMethod.js";

const SOURCE = readSource(
    fileURLToPath(new URL("../../src/components/AppConfigPresetsEmbeddings.vue", import.meta.url)),
);

function stub(preset) {
    const page = {
        config: { embeddings: {} },
        selected: [],
        newPreset: {
            model: "",
            client: null,
            local: true,
            custom: true,
            changed: true,
            ...preset,
        },
        formNewPresetValid: true,
        $refs: { formNewPreset: { validate: () => {} } },
    };
    page.commit = lift(SOURCE, "commitNewPreset", "AppConfigPresetsEmbeddings.vue");
    return page;
}

function committed(page) {
    page.commit.call(page);
    return page.config.embeddings[page.selected[0]];
}

describe("the embeddings driver list", () => {
    it("offers OpenRouter beside the other drivers", () => {
        const block = /embeddings: (\[[\s\S]*?\n {12}\])/.exec(SOURCE);
        expect(block, "AppConfigPresetsEmbeddings.vue has no embeddings list").not.toBeNull();
        const drivers = new Function(`return ${block[1]};`)().map(entry => entry.value);

        expect(drivers).toEqual([
            "sentence-transformer",
            "openai",
            "openrouter",
            "client-api",
        ]);
    });
});

describe("commitNewPreset", () => {
    it("keys an openrouter preset by driver and model", () => {
        const page = stub({ embeddings: "openrouter", model: "openai/text-embedding-3-small" });

        committed(page);

        expect(page.selected).toEqual(["openrouter/openai/text-embedding-3-small"]);
    });

    it.each(["openrouter", "openai", "client-api"])(
        "does not mark a %s preset as local",
        (embeddings) => {
            const page = stub({ embeddings, model: "some-model", client: "some-client" });

            expect(committed(page).local).toBe(false);
        },
    );

    it("leaves a sentence-transformer preset local", () => {
        const page = stub({ embeddings: "sentence-transformer", model: "all-MiniLM-L6-v2" });

        expect(committed(page).local).toBe(true);
    });

    it("commits nothing while the form is invalid", () => {
        const page = stub({ embeddings: "openrouter", model: "openai/text-embedding-3-small" });
        page.formNewPresetValid = false;

        page.commit.call(page);

        expect(page.config.embeddings).toEqual({});
    });
});
