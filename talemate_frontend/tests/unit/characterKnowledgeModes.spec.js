import { describe, expect, it, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import { fileURLToPath, URL } from 'node:url';
import {
    CHARACTER_KNOWLEDGE_MODES,
    CHARACTER_KNOWLEDGE_MODES_COMPARE_LABEL,
    CHARACTER_KNOWLEDGE_MODES_COMPARE_TITLE,
    characterKnowledgeMode,
} from '@/constants/characterKnowledgeModes';
import Comparison from '@/components/CharacterKnowledgeModeComparison.vue';
import { MODEL_EXPECTATIONS_DOCS_URL } from '@/constants/modelExpectations';

const read = (relative) => readFileSync(fileURLToPath(new URL(relative, import.meta.url)), 'utf-8');
const docsPage = read('../../../docs/user-guide/world-editor/knowledge.md');
const mode = (key) => CHARACTER_KNOWLEDGE_MODES.find((entry) => entry.key === key);

const OLD_HINT = 'Give each character their own view of events';

// the five points of choice and where each shows the comparison: a narrow host
// takes it compact, one line and a popover
const SITES = [
    { file: 'NewSceneSetupModal.vue', compact: false },
    { file: 'CharacterCardImport.vue', compact: false },
    { file: 'WorldStateManagerSceneSettings.vue', compact: true },
    { file: 'CharacterKnowledgeHub.vue', compact: true },
    { file: 'WorldStateManagerSceneSharedWorld.vue', compact: true },
];

describe('the shared constant', () => {
    it('describes exactly the two modes', () => {
        expect(CHARACTER_KNOWLEDGE_MODES.map((mode) => mode.key)).toEqual(['legacy', 'perception']);
        expect(mode('legacy').title).toBe('Standard');
        expect(mode('perception').title).toBe('Character perspectives');
    });
    it.each(CHARACTER_KNOWLEDGE_MODES)('$title carries a summary, 3-4 pros, 3-4 cons and a pick-this-if line', (mode) => {
        expect(mode.summary.length).toBeGreaterThan(40);
        expect(mode.pros.length).toBeGreaterThanOrEqual(3);
        expect(mode.pros.length).toBeLessThanOrEqual(4);
        expect(mode.cons.length).toBeGreaterThanOrEqual(3);
        expect(mode.cons.length).toBeLessThanOrEqual(4);
        expect(mode.pickIf).toMatch(/\.$/);
    });
    it('names the mode the scene flag selects', () => {
        expect(characterKnowledgeMode(true)).toBe(mode('perception'));
        expect(characterKnowledgeMode(false)).toBe(mode('legacy'));
        expect(characterKnowledgeMode(undefined).title).toBe('Standard');
    });
    it('both cards weigh the cast size, in the pick-this-if line and the summary', () => {
        expect(mode('legacy').pickIf).toContain('the scene is mostly you and one character');
        expect(mode('legacy').summary).toContain('a small cast');
        expect(mode('perception').pickIf).toContain('several characters are active who know different things');
        expect(mode('perception').summary).toContain('several active characters who know different things');
    });
    it('the perspectives card names the lock once and links the model guidance', () => {
        const perception = mode('perception');
        const lockMentions = [...perception.pros, ...perception.cons, perception.summary, perception.pickIf]
            .filter((text) => /once the story has history/i.test(text));
        expect(lockMentions).toEqual(['Cannot be turned off once the story has history']);
        expect(perception.modelGuidanceUrl).toBe(MODEL_EXPECTATIONS_DOCS_URL);
        expect(mode('legacy').modelGuidanceUrl).toBeUndefined();
    });
});

describe('every point of choice shows the comparison from the constant', () => {
    it.each(SITES)('$file renders CharacterKnowledgeModeComparison ($compact compact) and no copy of its own', ({ file, compact }) => {
        const source = read(`../../src/components/${file}`);
        const tag = source.match(/<CharacterKnowledgeModeComparison[^>]*>/);
        expect(tag, `${file} has no comparison`).not.toBeNull();
        expect(tag[0].includes(' compact')).toBe(compact);
        expect(tag[0]).toMatch(/:perspectives=/);
        expect(tag[0]).not.toMatch(/'perception'|'legacy'/);
        expect(source).not.toContain(OLD_HINT);
        for (const mode of CHARACTER_KNOWLEDGE_MODES) {
            for (const item of [...mode.pros, ...mode.cons, mode.pickIf]) {
                expect(source, `${file} carries its own copy of "${item}"`).not.toContain(item);
            }
        }
    });
    it('the cards read the constant and the wrapper takes its trigger label from it', () => {
        const cards = read('../../src/components/CharacterKnowledgeModeCards.vue');
        expect(cards).toContain("from '@/constants/characterKnowledgeModes'");
        expect(cards).toMatch(/mode\.pros/);
        expect(cards).toMatch(/mode\.cons/);
        expect(cards).toMatch(/mode\.pickIf/);
        // where the callout lands is pinned on the rendered DOM, in characterKnowledgeModeCards.spec.js
        const wrapper = read('../../src/components/CharacterKnowledgeModeComparison.vue');
        expect(wrapper).toContain('CHARACTER_KNOWLEDGE_MODES_COMPARE_LABEL');
        expect(wrapper).toContain('CHARACTER_KNOWLEDGE_MODES_COMPARE_TITLE');
        expect(wrapper).not.toContain(CHARACTER_KNOWLEDGE_MODES_COMPARE_LABEL);
        expect(wrapper).not.toContain(CHARACTER_KNOWLEDGE_MODES_COMPARE_TITLE);
        expect(CHARACTER_KNOWLEDGE_MODES_COMPARE_LABEL).toBe('Compare modes');
        expect(CHARACTER_KNOWLEDGE_MODES_COMPARE_TITLE).toBe('Compare the two modes');
    });

    it('keeps the cards out of the compact hosts and behind a popover of its own', () => {
        const wrapper = read('../../src/components/CharacterKnowledgeModeComparison.vue');
        expect(wrapper).not.toContain('v-expansion-panel');
        expect(wrapper).toContain('<v-menu');
        expect(wrapper).not.toContain('<v-dialog');
        const compact = wrapper.slice(wrapper.indexOf('v-if="compact"'), wrapper.indexOf('</v-menu>'));
        expect(compact).toContain('<CharacterKnowledgeModeCards');
        expect(compact).toContain(':close-on-content-click="false"');
    });

    it('keeps selection and collapsed details opt-in at the shared wrapper', () => {
        const wrapper = read('../../src/components/CharacterKnowledgeModeComparison.vue');
        expect(wrapper).toContain(':selectable="selectable"');
        expect(wrapper).toContain(':collapse-details="collapseDetails"');
        expect(wrapper).toContain("default: false");
        expect(wrapper).toContain("this.$emit('update:perspectives', key === 'perception')");
    });

    it('enables selection and collapsed details at only the two creation callers', () => {
        for (const file of ['NewSceneSetupModal.vue', 'CharacterCardImport.vue']) {
            const source = read(`../../src/components/${file}`);
            const tag = source.match(/<CharacterKnowledgeModeComparison[\s\S]*?\/>/)[0];
            expect(tag).toContain('selectable');
            expect(tag).toContain('collapse-details');
        }
        for (const file of ['WorldStateManagerSceneSettings.vue', 'CharacterKnowledgeHub.vue', 'WorldStateManagerSceneSharedWorld.vue']) {
            const source = read(`../../src/components/${file}`);
            const tag = source.match(/<CharacterKnowledgeModeComparison[^>]*>/)[0];
            expect(tag).not.toContain('selectable');
            expect(tag).not.toContain('collapse-details');
        }
    });

    it('maps shared card keys back to the existing boolean host state', () => {
        const vm = { selectable: true, $emit: vi.fn() };
        Comparison.methods.selectMode.call(vm, 'legacy');
        Comparison.methods.selectMode.call(vm, 'perception');
        expect(vm.$emit.mock.calls).toEqual([
            ['update:perspectives', false],
            ['update:perspectives', true],
        ]);
        vm.selectable = false;
        Comparison.methods.selectMode.call(vm, 'perception');
        expect(vm.$emit).toHaveBeenCalledTimes(2);
    });
});

describe('the Choosing a mode docs section repeats the constant', () => {
    it('sits at the top of the Knowledge page', () => {
        expect(docsPage.indexOf('## Choosing a mode')).toBeLessThan(docsPage.indexOf('## Character perspectives (opt-in)'));
        expect(docsPage.indexOf('## Choosing a mode')).toBeLessThan(docsPage.indexOf('## Standard mode'));
    });
    it.each(CHARACTER_KNOWLEDGE_MODES)('states the $title summary, pros, cons and pick-this-if line', (mode) => {
        const section = docsPage.slice(docsPage.indexOf('## Choosing a mode'), docsPage.indexOf('## Character perspectives (opt-in)'));
        expect(section).toContain(mode.summary);
        for (const item of [...mode.pros, ...mode.cons]) {
            expect(section, `docs miss "${item}"`).toContain(`- ${item}`);
        }
        expect(section).toContain(`Pick this if: ${mode.pickIf}`);
    });
    it('carries the four-row pick-this-if table, the cast row included, and the model guidance link', () => {
        const section = docsPage.slice(docsPage.indexOf('## Choosing a mode'), docsPage.indexOf('## Character perspectives (opt-in)'));
        const rows = section.split('\n').filter((line) => /^\| Your /.test(line));
        expect(rows.length).toBe(4);
        expect(rows.find((row) => row.startsWith('| Your cast |'))).toBeTruthy();
        expect(section).toContain('/talemate/getting-started/model-expectations/');
    });
});
