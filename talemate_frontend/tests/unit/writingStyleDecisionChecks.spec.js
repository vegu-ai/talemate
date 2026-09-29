// @vitest-environment jsdom

import { afterEach, describe, expect, it, vi } from 'vitest';
import { createApp, defineComponent, h, nextTick, ref } from 'vue';
import Editor from '@/components/WritingStyleDecisionChecks.vue';
import WritingStyle from '@/components/TemplateWritingStyle.vue';

vi.mock('@/components/ContextualGenerate.vue', () => ({ default: { template: '<div />' } }));

let app, host;
afterEach(() => { app?.unmount(); host?.remove(); });
const question = (id, kind = 'style') => ({ id, question: `Check {passage_id} for ${id}?`, true_criteria: 'Present', false_criteria: 'Absent', kind, instructions: `Correct ${id}.` });
const defaults = () => [
    { name: 'Repeated beats and description reuse', active: true, threshold: 0.8, requires_style: false, questions: [question('repetition', 'repetition'), question('description_reuse', 'repetition')] },
    { name: 'Writing style and unwanted prose', active: true, threshold: 0.8, requires_style: true, questions: [question('style')] },
];

const Container = defineComponent({ setup: (_, { slots }) => () => h('div', slots.default?.()) });
const Field = defineComponent({
    props: ['modelValue', 'label'], emits: ['update:modelValue'],
    setup: (props, { emit }) => () => h('input', { 'aria-label': props.label, value: props.modelValue, onInput: event => emit('update:modelValue', event.target.value) }),
});
const Checkbox = defineComponent({
    props: ['modelValue', 'label'], emits: ['update:modelValue'],
    setup: (props, { emit }) => () => h('input', { type: 'checkbox', 'aria-label': props.label, checked: props.modelValue, onChange: event => emit('update:modelValue', event.target.checked) }),
});

function mount(component, props) {
    host = document.createElement('div');
    document.body.appendChild(host);
    app = createApp(component, props);
    for (const name of ['VCard', 'VCardText', 'VCardTitle', 'VCardActions', 'VIcon', 'VChip', 'VAlert', 'VRow', 'VCol', 'VDivider', 'VTable', 'VForm']) app.component(name, Container);
    app.component('VBtn', defineComponent({ setup: (_, { slots, attrs }) => () => h('button', attrs, slots.default?.()) }));
    for (const name of ['VTextField', 'VTextarea', 'VSelect']) app.component(name, Field);
    app.component('VCheckbox', Checkbox);
    return app.mount(host);
}

function setup(checks = [], supplied = defaults(), defaultThreshold = 0.8) {
    const model = ref(checks);
    const changes = vi.fn(value => { model.value = value; });
    const editing = vi.fn();
    mount(defineComponent({ setup: () => () => h(Editor, { modelValue: model.value, defaults: supplied, defaultThreshold, 'onUpdate:modelValue': changes, onEditing: editing }) }));
    return { model, changes, editing };
}
function button(text) { return [...host.querySelectorAll('button')].find(node => node.textContent.trim() === text); }
async function click(text) { button(text).click(); await nextTick(); }
async function fill(label, value, index = 0) {
    const field = host.querySelectorAll(`input[aria-label="${label}"]`)[index];
    field.value = value;
    field.dispatchEvent(new Event('input'));
    await nextTick();
}

describe('writing style decision checks', () => {
    it('adds both common defaults with one action in a NEW style', async () => {
        const supplied = defaults();
        const saved = vi.fn();
        const vm = mount(WritingStyle, { immutableTemplate: { name: 'New style', template_type: 'writing_style', phrases: [] }, defaultDecisionChecks: supplied, onUpdate: saved });
        expect(host.textContent).toContain('No decision checks');
        await click('Add default checks');
        expect(saved).toHaveBeenCalledTimes(1);
        const payload = saved.mock.calls[0][0];
        expect(payload.uid).toBeUndefined();
        expect(payload.decision_checks).toEqual(supplied);
        expect(payload.decision_checks).not.toBe(supplied);
        expect(vm.template.decision_checks).toHaveLength(2);
        expect(button('Add default checks').disabled).toBe(true);
    });

    it('appends missing defaults without replacing customized questions or duplicating IDs', async () => {
        const original = defaults()[0];
        original.questions = [question('repetition')];
        original.threshold = 0.97;
        const { model } = setup([original]);
        await click('Add default checks');
        expect(model.value[0]).toEqual(original);
        expect(model.value.map(check => check.name)).toEqual([original.name, `${original.name} (2)`, 'Writing style and unwanted prose']);
        expect(host.querySelectorAll(`button[aria-label="Edit ${original.name}"]`)).toHaveLength(1);
        expect(model.value.flatMap(check => check.questions.map(q => q.id))).toEqual(['repetition', 'description_reuse', 'style']);
        expect(button('Add default checks').disabled).toBe(true);
    });

    it('edits question, criteria, routing and threshold without mutating the incoming style', async () => {
        const incoming = defaults();
        const { model, editing } = setup(incoming);
        await click('Edit');
        await fill('Probability threshold', '0.92');
        await fill('Question', 'Does {passage_id} use a stale image?');
        await fill('What counts as yes', 'The same image.');
        await fill('What counts as no', 'A fresh image.');
        await fill('Finding type', 'style');
        await fill('Rewrite instruction', 'Replace only the image.');
        expect(incoming[0].threshold).toBe(0.8);
        expect(editing).toHaveBeenLastCalledWith(true);
        await click('Apply check');
        expect(model.value[0].threshold).toBe(0.92);
        expect(model.value[1].threshold).toBe(0.8);
        expect(model.value[0].questions[0]).toMatchObject({ question: 'Does {passage_id} use a stale image?', true_criteria: 'The same image.', false_criteria: 'A fresh image.', kind: 'style', instructions: 'Replace only the image.' });
        expect(editing).toHaveBeenLastCalledWith(false);
    });

    it('keeps a draft dirty when another writing-style field saves', async () => {
        const vm = mount(WritingStyle, { immutableTemplate: { name: 'Draft', phrases: [], decision_checks: defaults() }, defaultDecisionChecks: defaults() });
        await click('Edit');
        expect(vm.dirty).toBe(true);
        vm.save();
        await nextTick();
        expect(vm.dirty).toBe(true);
        await click('Cancel');
        expect(vm.dirty).toBe(false);
    });

    it('clears an unfinished check edit when selecting another writing style', async () => {
        const selected = ref({ uid: 'first', name: 'First', phrases: [], decision_checks: defaults() });
        const editor = ref();
        mount(defineComponent({ setup: () => () => h(WritingStyle, { ref: editor, immutableTemplate: selected.value }) }));
        await click('Edit');
        expect(editor.value.dirty).toBe(true);
        selected.value = { uid: 'second', name: 'Second', phrases: [], decision_checks: [] };
        await nextTick();
        expect(editor.value.dirty).toBe(false);
        expect(host.querySelector('[data-testid="decision-check-editor"]')).toBeNull();
        expect(host.textContent).toContain('No decision checks');
    });

    it('opens More options when a short name is not valid, the only reason Apply check is off', async () => {
        const vm = mount(Editor, { modelValue: defaults(), defaults: defaults() });
        await click('Edit');
        expect(vm.moreOptions).toEqual([]);

        await fill('Short name', '2nd check', 1);

        expect(button('Apply check').disabled).toBe(true);
        expect(vm.moreOptions[1]).toBe('more');
        expect(vm.moreOptions[0]).toBeUndefined();

        await click('Remove question');
        expect(vm.moreOptions).toEqual(['more']);
    });

    it('rejects invalid thresholds and duplicate IDs before a save', async () => {
        const { changes } = setup(defaults());
        await click('Edit');
        for (const invalid of ['', '-0.1', '1.1', 'not a number']) {
            await fill('Probability threshold', invalid);
            expect(button('Apply check').disabled).toBe(true);
        }
        await fill('Probability threshold', '0.85');
        await fill('Short name', 'style');
        expect(button('Apply check').disabled).toBe(true);
        expect(host.textContent).toContain('Each question needs its own short name');
        expect(changes).not.toHaveBeenCalled();
    });

    it('creates a custom check and preserves an explicitly empty list after removal', async () => {
        const { model } = setup();
        await click('Add custom check');
        await fill('Check name', 'Concrete imagery');
        await fill('Question', 'Is {passage_id} abstract?');
        await fill('Rewrite instruction', 'Use a physical detail.');
        await click('Apply check');
        expect(model.value[0].name).toBe('Concrete imagery');
        await click('Remove');
        expect(model.value).toEqual([]);
        expect(host.textContent).toContain('Revision will use its usual detection.');
    });

    it('deactivates a check and cancels edits without dropping its questions', async () => {
        const { model } = setup(defaults());
        const toggle = host.querySelector('input[type="checkbox"]');
        toggle.checked = false;
        toggle.dispatchEvent(new Event('change'));
        await nextTick();
        expect(model.value[0].active).toBe(false);
        await click('Edit');
        await fill('Question', 'Uncommitted change');
        await click('Cancel');
        expect(model.value[0].questions).toEqual(defaults()[0].questions);
    });

    it('sets the scope of a check and shows it in the list', async () => {
        const { model } = setup(defaults());
        expect(host.textContent).not.toContain('Prose only');
        await click('Edit');
        expect(host.querySelector('input[aria-label="Applies to"]').value).toBe('');
        await fill('Applies to', 'prose');
        await click('Apply check');
        expect(model.value[0].scope).toBe('prose');
        expect(model.value[1].scope).toBeUndefined();
        expect(host.textContent).toContain('Prose only');
        expect(host.textContent).not.toContain('Dialogue only');
    });

    it('starts a custom check on all text', async () => {
        const { model } = setup();
        await click('Add custom check');
        expect(host.querySelector('input[aria-label="Applies to"]').value).toBe('all');
        await fill('Check name', 'Concrete imagery');
        await fill('Question', 'Is {passage_id} abstract?');
        await fill('Rewrite instruction', 'Use a physical detail.');
        await click('Apply check');
        expect(model.value[0].scope).toBe('all');
        expect(host.textContent).not.toContain('All text');
    });

    it('starts a custom check at the threshold the backend sends', async () => {
        const { model } = setup([], defaults(), 0.65);
        await click('Add custom check');
        expect(host.querySelector('input[aria-label="Probability threshold"]').value).toBe('0.65');
        await fill('Check name', 'Concrete imagery');
        await fill('Question', 'Is {passage_id} abstract?');
        await fill('Rewrite instruction', 'Use a physical detail.');
        await click('Apply check');
        expect(model.value[0].threshold).toBe(0.65);
    });

    it('explains the More options fields at the top of the section', async () => {
        setup(defaults());
        await click('Edit');
        const help = host.querySelector('[data-testid="more-options-help"]').textContent.replace(/\s+/g, ' ').trim();
        expect(help).toBe('Optional refinements: say what counts as yes and as no when the question alone leaves room for doubt (fill in both). The short name labels this question in the Decision Log.');
    });
});
