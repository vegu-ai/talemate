import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { fileURLToPath, URL } from 'node:url';
import { CHARACTER_KNOWLEDGE_MODES, CHARACTER_KNOWLEDGE_MODES_EXPANDER_LABEL } from '@/constants/characterKnowledgeModes';
import { MODEL_EXPECTATIONS_DOCS_URL } from '@/constants/modelExpectations';

const read = (relative) => readFileSync(fileURLToPath(new URL(relative, import.meta.url)), 'utf-8');
const docsPage = read('../../../docs/user-guide/world-editor/knowledge.md');
const mode = (key) => CHARACTER_KNOWLEDGE_MODES.find((entry) => entry.key === key);

const OLD_HINT = 'Give each character their own view of events';

// the five points of choice and where each shows the comparison
const SITES = [
    { file: 'NewSceneSetupModal.vue', collapsed: false },
    { file: 'CharacterCardImport.vue', collapsed: false },
    { file: 'WorldStateManagerSceneSettings.vue', collapsed: true },
    { file: 'CharacterKnowledgeHub.vue', collapsed: true },
    { file: 'WorldStateManagerSceneSharedWorld.vue', collapsed: true },
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
    it.each(SITES)('$file renders CharacterKnowledgeModeComparison ($collapsed collapsed) and no copy of its own', ({ file, collapsed }) => {
        const source = read(`../../src/components/${file}`);
        const tag = source.match(/<CharacterKnowledgeModeComparison[^>]*>/);
        expect(tag, `${file} has no comparison`).not.toBeNull();
        expect(tag[0].includes(' collapsed')).toBe(collapsed);
        expect(tag[0]).toMatch(/:perspectives=/);
        expect(tag[0]).not.toMatch(/'perception'|'legacy'/);
        expect(source).not.toContain(OLD_HINT);
        for (const mode of CHARACTER_KNOWLEDGE_MODES) {
            for (const item of [...mode.pros, ...mode.cons, mode.pickIf]) {
                expect(source, `${file} carries its own copy of "${item}"`).not.toContain(item);
            }
        }
    });
    it('the cards read the constant and the wrapper takes its expander label from it', () => {
        const cards = read('../../src/components/CharacterKnowledgeModeCards.vue');
        expect(cards).toContain("from '@/constants/characterKnowledgeModes'");
        expect(cards).toMatch(/mode\.pros/);
        expect(cards).toMatch(/mode\.cons/);
        expect(cards).toMatch(/mode\.pickIf/);
        const wrapper = read('../../src/components/CharacterKnowledgeModeComparison.vue');
        expect(wrapper).toContain('CHARACTER_KNOWLEDGE_MODES_EXPANDER_LABEL');
        expect(wrapper).not.toContain(CHARACTER_KNOWLEDGE_MODES_EXPANDER_LABEL);
        expect(CHARACTER_KNOWLEDGE_MODES_EXPANDER_LABEL).toBe('About the two modes');
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
    it('carries the three-row pick-this-if table and the model guidance link', () => {
        const section = docsPage.slice(docsPage.indexOf('## Choosing a mode'), docsPage.indexOf('## Character perspectives (opt-in)'));
        const rows = section.split('\n').filter((line) => /^\| Your /.test(line));
        expect(rows.length).toBe(3);
        expect(section).toContain('/talemate/getting-started/model-expectations/');
    });
});
