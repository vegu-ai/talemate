import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { fileURLToPath, URL } from 'node:url';
import {
    CONTEXT_LENGTH_FLOOR,
    CONTEXT_LENGTH_RECOMMENDED_PERSPECTIVES,
    KNOWN_GOOD_MODELS,
    MODEL_BAR,
    MODEL_EXPECTATIONS_DOCS_URL,
    MODEL_EXPECTATIONS_INTRO,
    MODEL_EXPECTATIONS_POINTER,
    STRUGGLES_WITHOUT_THE_BAR,
    WORKS_WITHOUT_THE_BAR,
    contextLengthWarning,
    formatKnownGoodModels,
} from '@/constants/modelExpectations';

const read = (relative) => readFileSync(fileURLToPath(new URL(relative, import.meta.url)), 'utf-8');
const docsPage = read('../../../docs/getting-started/model-expectations.md');
const wizard = read('../../src/components/OnboardingWizard.vue');
const clientEditor = read('../../src/components/ClientConfigEditor.vue');
const panel = read('../../src/components/ModelExpectationsPanel.vue');

describe('context length warning', () => {
    it.each([16384, 32768, 100000])('is silent at %s tokens', (value) => {
        expect(contextLengthWarning(value)).toBeNull();
    });
    it.each([undefined, null, '', 0, -1, 'abc'])('is silent for an unset or unusable value %s', (value) => {
        expect(contextLengthWarning(value)).toBeNull();
    });
    it.each([8192, 16383, '4096'])('warns below the floor for %s and names the value and the fix', (value) => {
        const text = contextLengthWarning(value);
        expect(text).toContain(`Context Length is ${Number(value)} tokens`);
        expect(text).toContain(String(CONTEXT_LENGTH_FLOOR));
        expect(text).toMatch(/raise it in the client settings/i);
    });
    it('reads nothing but the context length: the model name is never an input', () => {
        expect(contextLengthWarning.length).toBe(1);
        const source = read('../../src/constants/modelExpectations.js');
        expect(source).not.toMatch(/model_name|modelName|family|parameter size/i);
        expect(clientEditor).toMatch(/contextLengthWarning\(\) \{\s*return contextLengthWarning\(this\.values\.max_token_length\);\s*\}/);
        expect(panel).not.toMatch(/contextLengthWarning|model_name|modelName/);
        expect(wizard).not.toMatch(/contextLengthWarning|KNOWN_GOOD_MODELS/);
        expect(clientEditor).not.toMatch(/KNOWN_GOOD_MODELS/);
    });
});

describe('the constant', () => {
    it('states the bar with the floor and the perspectives recommendation', () => {
        expect(CONTEXT_LENGTH_FLOOR).toBe(16384);
        expect(CONTEXT_LENGTH_RECOMMENDED_PERSPECTIVES).toBe(32768);
        expect(MODEL_BAR.join(' ')).toContain('16k');
        expect(MODEL_BAR.join(' ')).toContain('32k');
        expect(MODEL_EXPECTATIONS_POINTER).toContain('16k');
    });
    it('the panel renders its sentences from the constant, not from copies', () => {
        expect(panel).toContain('MODEL_EXPECTATIONS_INTRO');
        expect(panel).toContain('MODEL_EXPECTATIONS_POINTER');
        expect(panel).not.toMatch(/16k|32k|16384/);
        expect(panel).not.toContain(MODEL_EXPECTATIONS_INTRO);
    });
    it('carries known good examples for both provider types', () => {
        expect(KNOWN_GOOD_MODELS.hosted.length).toBeGreaterThan(0);
        expect(KNOWN_GOOD_MODELS.selfHosted.length).toBeGreaterThan(0);
        expect(formatKnownGoodModels([{ name: 'a' }, { name: 'b', note: 'n' }])).toBe('a, b (n)');
    });
});

describe('the docs page repeats the constant', () => {
    it('is the page the app links to', () => {
        expect(MODEL_EXPECTATIONS_DOCS_URL).toMatch(/\/getting-started\/model-expectations\/$/);
    });
    it.each(MODEL_BAR)('states the bar item "%s"', (item) => {
        expect(docsPage).toContain(item);
    });
    it.each([...KNOWN_GOOD_MODELS.hosted, ...KNOWN_GOOD_MODELS.selfHosted])('names the known good model %s', ({ name }) => {
        expect(docsPage).toContain(name);
    });
    it('states the floor as the default and repeats what works without the bar', () => {
        expect(docsPage).toContain(String(CONTEXT_LENGTH_FLOOR));
        expect(docsPage).toContain(WORKS_WITHOUT_THE_BAR);
        expect(docsPage).toContain(STRUGGLES_WITHOUT_THE_BAR);
    });
});

describe('where the guidance shows', () => {
    it('the wizard shows the full panel on step 1 and the pointer on step 2', () => {
        const step1 = wizard.slice(wizard.indexOf('<!-- Step 1'), wizard.indexOf('<!-- Step 2'));
        const step2 = wizard.slice(wizard.indexOf('<!-- Step 2'), wizard.indexOf('<!-- Step 3'));
        expect(step1).toMatch(/<ModelExpectationsPanel \/>/);
        expect(step2).toMatch(/<ModelExpectationsPanel compact/);
    });
    it('the client editor warns from the context length in the full field set only and links the guidance', () => {
        const simple = clientEditor.slice(clientEditor.indexOf('<!-- SIMPLE MODE'), clientEditor.indexOf('<!-- FULL MODE'));
        const full = clientEditor.slice(clientEditor.indexOf('<!-- FULL MODE'), clientEditor.indexOf('<script>'));
        // the wizard draft only spreads the type defaults, which never sit below the floor
        expect(simple).not.toContain('contextLengthWarning');
        expect(full).toMatch(/<v-col v-if="contextLengthWarning" cols="12"/);
        expect(clientEditor).toMatch(/<ModelExpectationsPanel compact/);
    });
});
