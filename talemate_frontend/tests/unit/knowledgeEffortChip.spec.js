// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { createApp, defineComponent, h, nextTick, reactive } from 'vue';
import Chip from '@/components/KnowledgeEffortChip.vue';
import { agentsAt } from './helpers/effortAgents.js';

const Container = defineComponent({ setup: (_, { slots }) => () => h('div', slots.default?.()) });
const Tooltip = defineComponent({
    setup: (_, { slots }) => () => h('div', [slots.activator?.({ props: { 'data-activator': 'tooltip' } }), h('div', { class: 'tooltip-content' }, slots.default?.())]),
});

let app, host, state, vm, opened;

function mount() {
    state = reactive({ agents: agentsAt('legacy', 'minimal'), mode: 'legacy', notice: null });
    opened = [];
    host = document.createElement('div');
    document.body.appendChild(host);
    const Host = defineComponent({
        setup: () => () => h(Chip, {
            mode: state.mode,
            agents: state.agents,
            notice: state.notice,
            activatorProps: { onClick: () => opened.push('menu') },
            ref: 'chip',
        }),
    });
    app = createApp(Host);
    for (const name of ['VChip']) app.component(name, Container);
    app.component('VTooltip', Tooltip);
    vm = app.mount(host).$refs.chip;
    return vm;
}

beforeEach(() => mount());

afterEach(() => {
    vi.useRealTimers();
    app?.unmount();
    host?.remove();
});

const chip = () => host.querySelector('.knowledge-effort-stop');
const tooltip = () => host.querySelector('.tooltip-content');

describe('the knowledge effort chip', () => {
    it('shows the stop the agents sit on, with the explanation only in its tooltip', () => {
        expect(chip().textContent.trim()).toBe('Minimal');
        expect(tooltip().textContent).toContain('Character knowledge effort: Minimal');
        expect(tooltip().textContent).toContain(`Requests: ${vm.explanation.cost}`);
        expect(tooltip().textContent).toContain(`Benefit: ${vm.explanation.benefit}`);
    });

    it('labels a Custom state as Custom', async () => {
        state.agents = agentsAt('legacy', 'thorough', { 'conversation.character_knowledge.perspective_filter': false });
        await nextTick();
        expect(chip().textContent.trim()).toBe('Custom');
        expect(vm.stopColor).toBe('secondary');
    });

    it('prices the default stop while no agent has reported', async () => {
        state.agents = [];
        await nextTick();
        expect(vm.live.stop).toBeNull();
        expect(vm.stop).toBe('minimal');
        expect(vm.explanation.cost).toBe('No extra requests.');
        expect(chip().textContent.trim()).toBe('Minimal');
    });

    it('adds the host notice below the explanation', async () => {
        expect(tooltip().textContent).not.toContain('Waiting for the agents');
        state.notice = 'Waiting for the agents to report.';
        await nextTick();
        expect(tooltip().textContent).toContain('Waiting for the agents to report.');
    });

    it('carries the tooltip and the host activator on the one chip, which keeps a tab stop', () => {
        expect(chip().dataset.activator).toBe('tooltip');
        expect(chip().getAttribute('tabindex')).toBe('0');
        expect(host.querySelectorAll('[data-activator]')).toHaveLength(1);
        chip().click();
        expect(opened).toEqual(['menu']);
    });
});
