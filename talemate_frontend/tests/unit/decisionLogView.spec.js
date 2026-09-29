// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest';
import { createApp, defineComponent, h, nextTick } from 'vue';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { applyDecisionFrame, decisionLog } from '@/utils/decisionLog';
import DebugTools from '@/components/DebugTools.vue';
import PromptsMenu from '@/components/prompts/PromptsMenu.vue';

vi.mock('@/utils/codeEditorTheme.js', () => ({ codeEditorExtensions: () => [] }));
vi.mock('vue-codemirror', () => ({
    Codemirror: { props: ['modelValue'], render() { return h('pre', this.modelValue); } },
}));

const { scenarios } = JSON.parse(
    readFileSync(resolve('tests/unit/fixtures/decisionLifecycle.json')),
);

// Match Vuetify's lazy dialog mounting so hidden detail cannot satisfy an assertion.
const VDialog = defineComponent({
    props: ['modelValue'],
    setup(props, { slots }) {
        return () => props.modelValue ? h('div', { role: 'dialog' }, slots.default?.()) : null;
    },
});
const VListItem = defineComponent({
    setup(_, { slots }) { return () => h('button', slots.default?.()); },
});

const mounted = [];
const sent = [];

afterEach(() => {
    for (const [app, element] of mounted.splice(0)) {
        app.unmount();
        element.remove();
    }
    sent.length = 0;
    applyDecisionFrame(decisionLog, { event: 'snapshot', requests: [], invocations: [] });
});

function mount(component, props = {}) {
    const element = document.createElement('div');
    document.body.appendChild(element);
    const app = createApp({ render: () => h(component, props) });
    app.config.warnHandler = () => {};
    app.provide('registerMessageHandler', () => {});
    app.provide('unregisterMessageHandler', () => {});
    app.provide('setWaitingForInput', () => {});
    app.provide('getWebsocket', () => ({ send: raw => sent.push(JSON.parse(raw)) }));
    app.component('VDialog', VDialog);
    app.component('VListItem', VListItem);
    app.mount(element);
    mounted.push([app, element]);
    return element;
}

function replay(name) {
    for (const frame of scenarios[name]) applyDecisionFrame(decisionLog, frame);
}

function tabsOf(element) {
    return [...element.querySelectorAll('v-tabs v-tab')].map(tab => tab.getAttribute('aria-label'));
}

async function openDecision(element, id = 'request-1') {
    element.querySelector(`[data-entry-id="${id}"]`).click();
    await nextTick();
    return element.textContent;
}

describe('both surfaces show one shared log', () => {
    it('renders the same row in Debug Tools and in the Prompt Manager', async () => {
        const debugTools = mount(DebugTools);
        const promptsMenu = mount(PromptsMenu);
        expect(debugTools.textContent).toContain('No decisions yet');

        replay('below_threshold');
        await nextTick();

        const result = 'repeats · probability 0.74';
        expect(debugTools.textContent).toContain(result);
        expect(promptsMenu.textContent).toContain(result);
        expect(debugTools.textContent).not.toContain('No decisions yet');
    });

    it('clears from either surface through the backend log', async () => {
        replay('below_threshold');
        for (const element of [mount(DebugTools), mount(PromptsMenu)]) {
            element.querySelector('[data-testid="decision-log-clear"]').click();
        }
        expect(sent).toEqual([
            { type: 'decisions', action: 'clear' },
            { type: 'decisions', action: 'clear' },
        ]);

        applyDecisionFrame(decisionLog, {
            event: 'removed',
            request_ids: [decisionLog.requests[Object.keys(decisionLog.requests)[0]].id],
            invocation_ids: [],
        });
        await nextTick();
        expect(mounted[0][1].textContent).toContain('No decisions yet');
    });

    it('offers a Decisions tab beside Prompts on both surfaces', () => {
        // the strips carry icons only, so a tab is found by its accessible name
        expect(tabsOf(mount(DebugTools))).toEqual(['Prompts', 'Decisions', 'Memory', 'Vars']);
        expect(tabsOf(mount(PromptsMenu))).toEqual(['Prompts', 'Decisions', 'Templates']);
    });

    it('keeps the old label of each tab in its tooltip', () => {
        for (const surface of [DebugTools, PromptsMenu]) {
            const tabs = [...mount(surface).querySelectorAll('v-tabs v-tab')];
            expect(tabs.length).toBeGreaterThan(2);
            for (const tab of tabs) {
                expect(tab.querySelector('v-tooltip')?.textContent.trim())
                    .toBe(tab.getAttribute('aria-label'));
                expect(tab.querySelector('v-icon')).not.toBeNull();
            }
        }
    });
});

describe('a decision detail dialog', () => {
    it('keeps the detail closed until the row is opened', async () => {
        replay('below_threshold');
        const element = mount(DebugTools);
        expect(element.querySelector('[role=dialog]')).toBe(null);
        expect(element.textContent).not.toContain('What happened');
        expect(element.textContent).not.toContain('Does this passage repeat');

        expect(await openDecision(element)).toContain('What happened');
    });

    it('pairs each ask with its answer while keeping raw state and JSON behind a toggle', async () => {
        replay('below_threshold');
        const element = mount(DebugTools);
        const text = await openDecision(element);
        expect(text).toContain('Does this passage repeat an earlier story beat?');
        expect(text).toContain('repeats');
        expect(text).not.toContain('noul');
        expect(text).toContain('Probability 0.74');
        expect(element.querySelectorAll('[data-decision-id] pre')).toHaveLength(0);
        expect(text).toContain('No action (below 0.80)');
        const toggle = element.querySelector('[data-testid="decision-raw-toggle"]');
        expect(toggle.getAttribute('aria-expanded')).toBe('false');
        toggle.click();
        await nextTick();
        expect(toggle.getAttribute('aria-expanded')).toBe('true');
        expect(element.textContent).toContain('"p_true": 0.74');
        expect(element.textContent).toContain('"type": "noul"');
        expect(element.textContent).toContain('"passage": "original"');
        expect(element.textContent).toContain('"threshold": 0.8');
        toggle.click();
        await nextTick();
        expect(element.querySelectorAll('[data-decision-id] pre')).toHaveLength(0);
    });

    it('keeps one request of several questions on one row, each ask beside its answer', async () => {
        replay('question_types');
        const element = mount(DebugTools);
        expect(element.querySelectorAll('[data-entry-id]')).toHaveLength(1);
        await openDecision(element);

        const asks = [...element.querySelectorAll('[data-decision-id="request-1"] .decision-question')]
            .map(node => node.textContent);
        expect(asks).toHaveLength(3);
        expect(asks[0]).toContain('repeats');
        expect(asks[0]).toContain('Probability 0.74');
        expect(asks[1]).toContain('tone');
        expect(asks[1]).toContain('warm');
        expect(asks[2]).toContain('tension');
        expect(asks[2]).toContain('1.50 of 2');
    });

    it('separates the action from the model response and claims no text change', async () => {
        replay('action_taken');
        const element = mount(DebugTools);
        const text = await openDecision(element);
        expect(text).toContain('Revision rewrite completed · 820 ms');
        expect(text).toContain('A completed action does not mean the text changed.');
        element.querySelector('[data-testid="decision-raw-toggle"]').click();
        await nextTick();
        expect(element.textContent).toContain('Request request-1');
        expect(element.textContent).toContain('Invocation invocation-1');
    });

    it('names a failure and the continuation the feature used', async () => {
        replay('request_not_sent');
        const text = await openDecision(mount(DebugTools));
        expect(text).toContain('Request not sent');
        expect(text).toContain('Request not sent — the decision model is off.');
        expect(text).toContain('Disabled path completed');
        expect(text).not.toMatch(/api_key|authorization/i);
    });

    it('marks an action no request of the policy claimed', async () => {
        replay('unassociated_action');
        const text = await openDecision(mount(DebugTools));
        expect(text).toContain('not linked to this request');
        expect(text).not.toContain('No action; reason unspecified');
    });

    it('leaves a sibling request\'s action off this row', async () => {
        replay('two_asks');
        const element = mount(DebugTools);
        await openDecision(element, 'request-2');
        const panel = element.querySelector('[data-decision-id="request-2"]');
        expect(panel.textContent).not.toContain('Revision rewrite');
        expect(panel.textContent).not.toContain('not linked to this request');
    });

    it.each([DebugTools, PromptsMenu])('shows each shared instruction once with the exact passage and probability on both surfaces', async (surface) => {
        replay('readable_checks');
        const element = mount(surface);
        await openDecision(element);
        expect(element.querySelectorAll('.decision-check')).toHaveLength(3);
        expect(element.querySelectorAll('.decision-instruction')).toHaveLength(3);
        expect(element.querySelectorAll('.decision-question')).toHaveLength(6);
        expect(element.querySelectorAll('[data-decision-id] pre')).toHaveLength(0);
        const flagged = element.querySelector('[data-question-id="s1_repetition"]');
        expect(flagged.textContent).toContain('She paid the clerk again.');
        expect(flagged.textContent).toContain('Probability 0.91');
        expect(flagged.textContent).toContain('Threshold 0.91');
        expect(flagged.textContent).toContain('Flagged');
        expect(flagged.classList.contains('decision-question-flagged')).toBe(true);
        const below = element.querySelector('[data-question-id="s2_style"]');
        expect(below.textContent).toContain('The clock showed eleven.');
        expect(below.textContent).toContain('Probability 0.7599999');
        expect(below.textContent).toContain('Threshold 0.76');
        expect(below.textContent).toContain('Not flagged');
        expect(element.querySelector('[data-question-id="s2_repetition"]').textContent).toContain('Probability 0.00');
        expect(element.querySelector('.decision-result').textContent).toContain('Revision rewrite completed');
        element.querySelector('[data-testid="decision-raw-toggle"]').click();
        await nextTick();
        expect(element.textContent).toContain('"diagnostic": "provider reply"');
        expect(element.textContent).toContain('"true_criteria"');
    });

    it('updates the open report as answers and actions arrive, then closes on removal', async () => {
        const frame = scenarios.readable_checks.find(item => item.event === 'request' && item.entry.dispatched && item.entry.status === 'pending');
        applyDecisionFrame(decisionLog, frame);
        const element = mount(DebugTools);
        await openDecision(element);
        expect(element.querySelector('[role=dialog]').textContent).toContain('Pending');
        replay('readable_checks');
        await nextTick();
        expect(element.querySelector('[role=dialog]').textContent).toContain('Probability 0.91');
        expect(element.querySelector('[role=dialog]').textContent).toContain('Revision rewrite completed');
        applyDecisionFrame(decisionLog, { event: 'removed', request_ids: ['request-1'], invocation_ids: [] });
        await nextTick();
        expect(element.querySelector('[role=dialog]')).toBeNull();
    });

    it.each([
        ['below_threshold', 'answered in 140 ms'],
        ['action_failed', 'answered in 140 ms'],
        ['request_failed', 'took 140 ms'],
        ['request_not_sent', 'took 140 ms'],
        ['cancelled', 'took 140 ms'],
    ])('names the duration of %s from the request status, not the row status', async (name, label) => {
        replay(name);
        const element = mount(DebugTools);
        await openDecision(element);
        const header = element.querySelector('[role=dialog]').textContent;
        expect(header).toContain(label);
        expect(header).not.toContain(label.startsWith('took') ? 'answered in' : 'took ');
    });

    it('keeps compact rows concise and navigates reports with raw details collapsed', async () => {
        replay('two_asks');
        const element = mount(DebugTools);
        await openDecision(element, 'request-2');
        element.querySelector('[data-testid="decision-raw-toggle"]').click();
        await nextTick();
        expect(element.querySelector('[data-decision-id] pre')).not.toBeNull();
        element.querySelector('[data-testid="decision-previous"]').click();
        await nextTick();
        expect(element.querySelector('[data-decision-id]').getAttribute('data-decision-id')).toBe('request-1');
        expect(element.querySelector('[data-decision-id] pre')).toBeNull();
        element.querySelector('[data-testid="decision-next"]').click();
        await nextTick();
        expect(element.querySelector('[data-decision-id]').getAttribute('data-decision-id')).toBe('request-2');
    });

    it('shows the deciding passage in a compact row with an outcome and timestamp', () => {
        replay('readable_checks');
        const element = mount(DebugTools);
        const row = element.querySelector('[data-entry-id]');
        expect(row.textContent).toContain('Editor checks');
        expect(row.textContent).toContain('Revision rewrite completed');
        expect(row.textContent).toContain('Flagged s1 · 0.91 (threshold 0.91)');
        expect(row.querySelector('[title="2026-09-21T09:00:01+00:00"]')).not.toBeNull();
        expect(row.textContent).not.toContain('She paid the clerk again.');
        expect(row.querySelector('pre')).toBeNull();
    });

    it.each([
        ['failed', true, 'Failed', 'Talemate could not reach the provider'],
        ['failed', false, 'Not sent', 'The decision model is off'],
        ['cancelled', true, 'Cancelled', '6 questions'],
    ])('renders %s requests with presentation context (dispatched=%s)', async (status, dispatched, label, result) => {
        const snapshot = structuredClone(scenarios.readable_checks.at(-1));
        const request = snapshot.requests[0];
        Object.assign(request, {
            status, dispatched, answers: null, actions: [], outcomes: [],
            failure: status === 'failed' ? { code: dispatched ? 'transport' : 'disabled', message: result } : null,
        });
        Object.assign(snapshot.invocations[0], { status: 'completed', actions: [] });
        applyDecisionFrame(decisionLog, snapshot);
        for (const surface of [DebugTools, PromptsMenu]) {
            const element = mount(surface);
            const row = element.querySelector('[data-entry-id]');
            expect(row.querySelector('.decision-outcome').textContent).toBe(label);
            expect(row.querySelector('.decision-row-result').textContent).toBe(result);
            await openDecision(element);
            const dialog = element.querySelector('[role=dialog]');
            expect(dialog.textContent).toContain('She paid the clerk again.');
            expect(dialog.textContent).toContain('No answer returned');
            expect(dialog.querySelector('.decision-summary').textContent).toContain(label);
            expect(dialog.querySelectorAll('.decision-question-flagged, [role=meter]')).toHaveLength(0);
        }
    });

    it('shows the policy source beside the template in the report\'s technical details only', async () => {
        const snapshot = structuredClone(scenarios.readable_checks.at(-1));
        snapshot.requests[0].source_group = 'user';
        applyDecisionFrame(decisionLog, snapshot);
        const element = mount(DebugTools);
        expect(element.querySelector('[data-entry-id] [data-testid="decision-source-group"]')).toBeNull();
        await openDecision(element);
        expect(element.querySelector('[data-testid="decision-source-group"]')).toBeNull();
        expect(element.querySelector('[role=dialog]').textContent).not.toContain('editor.readable-checks');
        element.querySelector('[data-testid="decision-raw-toggle"]').click();
        await nextTick();
        expect(element.querySelector('[data-testid="decision-source-group"]').textContent).toBe('user');
        expect(element.querySelector('[role=dialog]').textContent).toContain('editor.readable-checks');
    });

    it('shows the override verdict when equality is not flagged', async () => {
        const snapshot = structuredClone(scenarios.readable_checks.at(-1));
        snapshot.requests[0].outcomes[0].details.flagged_question_ids = [];
        applyDecisionFrame(decisionLog, snapshot);
        const element = mount(DebugTools);
        await openDecision(element);
        const question = element.querySelector('[data-question-id="s1_repetition"]');
        expect(question.textContent).toContain('Probability 0.91');
        expect(question.textContent).toContain('Threshold 0.91');
        expect(question.textContent).toContain('Not flagged');
        expect(question.classList.contains('decision-question-flagged')).toBe(false);
        expect(question.querySelector('[role=meter]').getAttribute('aria-valuetext')).toContain('not flagged');
    });

    it('shows pending checks without inventing probabilities or flags', async () => {
        const frame = scenarios.readable_checks.find(item => item.event === 'request' && item.entry.dispatched && item.entry.status === 'pending');
        applyDecisionFrame(decisionLog, frame);
        const element = mount(DebugTools);
        await openDecision(element);
        expect(element.querySelectorAll('.decision-question')).toHaveLength(6);
        expect(element.querySelectorAll('.decision-question-flagged')).toHaveLength(0);
        expect(element.querySelector('.decision-question').textContent).toContain('Pending');
        expect(element.querySelector('.decision-question').textContent).toContain('She paid the clerk again.');
        expect(element.querySelector('.decision-question').textContent).not.toContain('Probability');
    });

    it('shows the scope of a check and names the passages it skipped', async () => {
        replay('scoped_checks');
        const element = mount(DebugTools);
        await openDecision(element);
        const card = element.querySelector('.decision-check');
        expect(card.textContent).toContain('Filler prose');
        expect(card.textContent).toContain('Prose only');
        expect(card.querySelectorAll('.decision-question')).toHaveLength(1);
        expect(card.querySelector('[data-question-id="s2_filler"]').textContent).toContain('The ladder shifted.');
        expect(card.querySelector('[data-testid="decision-skipped"] span').textContent.trim())
            .toBe('Skipped s1: no prose in this passage.');
    });

    it('explains a row whose passages were all out of scope', async () => {
        replay('nothing_in_scope');
        const element = mount(DebugTools);
        const row = element.querySelector('[data-entry-id]');
        expect(row.querySelector('.decision-row-result').textContent).toBe('Nothing in scope · every passage skipped');
        await openDecision(element, 'invocation-1');
        const dialog = element.querySelector('[role=dialog]');
        expect(dialog.textContent).toContain('No action (nothing in scope)');
        expect(dialog.textContent).not.toContain('reason unspecified');
        expect(dialog.textContent).not.toContain('The feature asked no questions');
        expect(dialog.querySelector('.decision-check').textContent).toContain('Prose only');
        expect(dialog.querySelector('[data-testid="decision-skipped"] span').textContent.trim())
            .toBe('Skipped s1: no prose in this passage.');
    });

    it('shows an outcome recorded before the request on the request row', async () => {
        replay('outcome_before_request');
        const element = mount(DebugTools);
        expect(element.querySelectorAll('[data-entry-id]')).toHaveLength(1);
        await openDecision(element);
        const lines = [...element.querySelectorAll('.decision-result > div')].map(node => node.textContent.trim());
        expect(lines).toContain('Note (checked first)');
        expect(lines).toContain('No action (below 0.80)');
        expect(lines.indexOf('Note (checked first)')).toBeLessThan(lines.indexOf('No action (below 0.80)'));
    });
});
