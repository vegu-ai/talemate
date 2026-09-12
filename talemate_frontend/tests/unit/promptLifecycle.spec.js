// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from 'vitest';
import { createApp, h, nextTick, reactive } from 'vue';
import { resolve } from 'node:path';
import { capturePrompt, clearFinishedPrompts, promptMetric, syncPromptDraft } from '@/utils/promptLog';
import { lift, readSource } from './helpers/liftMethod';
import PromptDetailView from '@/components/prompts/PromptDetailView.vue';
import PromptLogItem from '@/components/prompts/PromptLogItem.vue';

vi.mock('@/utils/codeEditorTheme.js', () => ({ codeEditorExtensions: () => [] }));
vi.mock('vue-codemirror', () => ({
    Codemirror: { props: ['modelValue'], render() { return h('pre', this.modelValue); } },
}));

function snapshot(request_id, overrides = {}) {
    return {
        request_id, status: 'active', prompt: 'shared prompt ' + request_id,
        response: null, prompt_tokens: 10, response_tokens: null, time: null,
        attempts: 1, error: null, agent_type: 'narrator', agent_action: 'narrate',
        agent_stack: ['Narrator.narrate'], client_name: 'test', kind: 'conversation',
        template_uid: 'narrator.test', generation_parameters: { temperature: 0.7 },
        ...overrides,
    };
}

function state(maxPrompts = 100) {
    return reactive({ prompts: [], promptTotal: 0, maxPrompts });
}

const mounted = [];
afterEach(() => {
    for (const [app, element] of mounted.splice(0)) {
        app.unmount();
        element.remove();
    }
});

function mount(component, props) {
    const element = document.createElement('div');
    document.body.appendChild(element);
    const app = createApp({ render: () => h(component, props()) });
    app.config.warnHandler = () => {};
    const handlers = new Set();
    app.provide('registerMessageHandler', handler => handlers.add(handler));
    app.provide('unregisterMessageHandler', handler => handlers.delete(handler));
    app.provide('getWebsocket', () => ({ send: vi.fn() }));
    app.provide('settingsDirty', () => false);
    app.mount(element);
    mounted.push([app, element]);
    return { element, app, handlers };
}

describe('shared prompt capture', () => {
    it('keeps identity, order, and independent metadata through reversed completion', () => {
        const log = state();
        capturePrompt(log, snapshot('first'));
        const first = log.prompts[0];
        capturePrompt(log, snapshot('second'));
        capturePrompt(log, snapshot('second', { status: 'completed', response: 'second answer', response_tokens: 22, time: 1 }));
        expect(first.status).toBe('active');
        capturePrompt(log, snapshot('first', { status: 'completed', response: 'first answer', response_tokens: 11, time: 2 }));
        expect(log.prompts.map(p => p.request_id)).toEqual(['second', 'first']);
        expect(log.prompts[1]).toBe(first);
        expect(log.prompts.map(p => p.response_tokens)).toEqual([22, 11]);
        expect(log.promptTotal).toBe(2);
        capturePrompt(log, snapshot('first'));
        expect(first.status).toBe('completed');
    });

    it('clear preserves active objects and their eventual updates', () => {
        const log = state();
        capturePrompt(log, snapshot('finished', { status: 'failed', error: 'Failed' }));
        capturePrompt(log, snapshot('running'));
        const running = log.prompts[0];
        const list = log.prompts;
        clearFinishedPrompts(log.prompts);
        expect(log.prompts).toBe(list);
        expect(log.prompts).toEqual([running]);
        capturePrompt(log, snapshot('running', { status: 'cancelled', error: 'Cancelled' }));
        expect(log.prompts[0]).toBe(running);
        expect(running.status).toBe('cancelled');
        clearFinishedPrompts(log.prompts);
        expect(log.prompts).toEqual([]);
    });

    it('prunes finished history while retaining every active request', () => {
        const log = state(1);
        capturePrompt(log, snapshot('first'));
        capturePrompt(log, snapshot('second'));
        expect(log.prompts).toHaveLength(2);
        capturePrompt(log, snapshot('first', { status: 'completed' }));
        expect(log.prompts.map(p => p.request_id)).toEqual(['second']);
    });

    it('exports pending and terminal values without inventing zero usage', () => {
        const log = state();
        capturePrompt(log, snapshot('active'));
        capturePrompt(log, snapshot('done', { status: 'completed', response_tokens: 0, time: 0 }));
        const source = readSource(resolve('src/components/DebugToolPromptLog.vue'));
        const sent = [];
        lift(source, 'dumpPromptLog').call({
            prompts: log.prompts,
            getWebsocket: () => ({ send: raw => sent.push(JSON.parse(raw)) }),
        });
        expect(sent[0].action).toBe('dump_prompt_log');
        expect(sent[0].prompts[0].response_tokens).toBe(0);
        expect(sent[0].prompts[1]).toMatchObject({ status: 'active', response: null, response_tokens: null, time: null });
    });
});

describe('live inspection', () => {
    it('Debug navigation follows identity when a newer request arrives', () => {
        const source = readSource(resolve('src/components/DebugToolPromptView.vue'));
        const first = snapshot('first');
        const second = snapshot('second');
        const context = { prompt: first, prompts: [first] };
        Object.defineProperty(context, 'index', { get: () => lift(source, 'index').call(context) });
        context.prompts.unshift(second);
        expect(context.index).toBe(1);
        lift(source, 'loadNextPrompt').call(context);
        expect(context.prompt).toBe(second);
        lift(source, 'loadPreviousPrompt').call(context);
        expect(context.prompt).toBe(first);
    });

    it('Prompt Manager tabs deduplicate by request identity', () => {
        const source = readSource(resolve('src/components/prompts/PromptsView.vue'));
        const open = lift(source, 'handleOpenPrompt');
        const context = { openPrompts: [], activePromptIndex: 0, $emit: vi.fn() };
        const first = snapshot('first', { num: 0 });
        const second = snapshot('second', { num: 0 });
        open.call(context, first);
        open.call(context, second);
        open.call(context, first);
        expect(context.openPrompts).toEqual([first, second]);
        expect(context.activePromptIndex).toBe(0);
    });

    it('renders a mid-request mount and updates the existing list and detail views', async () => {
        const log = state();
        capturePrompt(log, snapshot('live'));
        const prompt = log.prompts[0];
        const row = mount(PromptLogItem, () => ({ prompt }));
        const detail = mount(PromptDetailView, () => ({ prompt }));
        expect(row.element.textContent).toContain('Active');
        expect(row.element.textContent).toContain('Pending');
        expect(detail.element.textContent).toContain('Response pending.');
        expect(detail.element.textContent).toContain('shared prompt live');
        capturePrompt(log, snapshot('live', { status: 'completed', response: 'Final answer', response_tokens: 5, time: 3 }));
        await nextTick();
        expect(row.element.textContent).toContain('Completed');
        expect(detail.element.textContent).toContain('Completed');
        expect(detail.element.textContent).toContain('Final answer');
        expect(detail.element.textContent).not.toContain('Response pending.');
        expect(detail.handlers.size).toBe(1);
        detail.app.unmount();
        mounted.splice(mounted.findIndex(([app]) => app === detail.app), 1);
        detail.element.remove();
        expect(detail.handlers.size).toBe(0);
    });

    it('keeps prompt and parameter edits while incorporating the terminal response', () => {
        const log = state();
        capturePrompt(log, snapshot('edit'));
        let draft = syncPromptDraft(null, log.prompts[0]);
        draft.prompt = 'edited prompt';
        draft.generation_parameters.temperature = 0.1;
        capturePrompt(log, snapshot('edit', { status: 'completed', response: 'answer', reasoning: 'thoughts' }));
        draft = syncPromptDraft(draft, log.prompts[0]);
        expect(draft.prompt).toBe('edited prompt');
        expect(draft.original_prompt).toBe('shared prompt edit');
        expect(draft.generation_parameters.temperature).toBe(0.1);
        expect(draft.original_generation_parameters.temperature).toBe(0.7);
        expect(draft.response).toBe('answer');
        expect(draft.original_response).toBe('answer');
        expect(draft.reasoning).toBe('thoughts');
    });

    it.each(['failed', 'cancelled'])('renders actual %s outcome and unavailable usage', async status => {
        const log = state();
        capturePrompt(log, snapshot('terminal'));
        const detail = mount(PromptDetailView, () => ({ prompt: log.prompts[0] }));
        capturePrompt(log, snapshot('terminal', { status, error: 'Actual outcome', time: 1 }));
        await nextTick();
        expect(detail.element.textContent).toContain(status === 'failed' ? 'Failed' : 'Cancelled');
        expect(detail.element.textContent).toContain('Actual outcome');
        expect(detail.element.textContent).toContain('Unavailable');
        expect(detail.element.textContent).not.toContain('Response pending.');
    });

    it('distinguishes pending, unavailable and legitimate zero metrics', () => {
        expect(promptMetric(null, 'active')).toBe('Pending');
        expect(promptMetric(null, 'failed')).toBe('Unavailable');
        expect(promptMetric(0, 'completed')).toBe('0');
    });
});
