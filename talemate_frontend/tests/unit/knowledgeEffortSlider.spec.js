// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { createApp, defineComponent, h, nextTick, reactive } from 'vue';
import Slider from '@/components/KnowledgeEffortSlider.vue';
import { EFFORT_STOPS } from '@/constants/knowledgeEffort';
import { effortPatch } from '@/utils/knowledgeEffort';
import { agentsAt } from './helpers/effortAgents.js';

const Container = defineComponent({ setup: (_, { slots }) => () => h('div', slots.default?.()) });

const index = (stop, mode = 'legacy') => EFFORT_STOPS[mode].indexOf(stop);
const SEND_DEBOUNCE = 250;

// what every immediate host does in the same tick as the emit:
// AIAgent.applyActionValues writes the preset into the objects the slider reads
function applyStop(agents, mode, stop) {
    for (const entry of effortPatch(agents, mode, stop)) {
        const action = agents.find((agent) => agent.name === entry.agent).actions[entry.action];
        if (entry.enabled !== undefined) action.enabled = entry.enabled;
        for (const [key, value] of Object.entries(entry.config)) action.config[key].value = value;
    }
}

let app, host, state, applied, handlers, vm;

function mount({ immediate = true, pin = false } = {}) {
    state = reactive({ agents: agentsAt('legacy', 'minimal'), mode: 'legacy' });
    applied = [];
    handlers = [];
    host = document.createElement('div');
    document.body.appendChild(host);
    const Host = defineComponent({
        setup: () => () => h(Slider, {
            mode: state.mode,
            agents: state.agents,
            immediate,
            pin,
            onApply: (stop) => {
                applied.push(stop);
                if (immediate) applyStop(state.agents, state.mode, stop);
            },
            ref: 'slider',
        }),
    });
    app = createApp(Host);
    app.provide('registerMessageHandler', (fn) => handlers.push(fn));
    app.provide('unregisterMessageHandler', (fn) => handlers.splice(handlers.indexOf(fn), 1));
    for (const name of ['VSlider', 'VChip', 'VSpacer']) app.component(name, Container);
    vm = app.mount(host).$refs.slider;
    return vm;
}

beforeEach(() => mount());

afterEach(() => {
    vi.useRealTimers();
    app?.unmount();
    host?.remove();
});

// An agent_status frame carries that agent's own state at the moment it was
// emitted, and AIAgent replaces the whole action set from it. `agents` is the
// state the frame reports: leave it out for a frame that reports what the
// agents already hold.
function deliver(name, agents = null) {
    const source = agents || state.agents;
    const agent = source.find((candidate) => candidate.name === name);
    const payload = {
        type: 'agent_status',
        name,
        data: {
            actions: JSON.parse(JSON.stringify(agent.actions)),
            scene_overrides: agent.data.scene_overrides,
        },
    };
    if (agents) state.agents = agents;
    for (const handler of [...handlers]) handler(payload);
}

// the drag Vuetify reports when the press lands on the thumb
function dragTo(stop) {
    vm.startDrag();
    vm.pick(index(stop));
    vm.finish(index(stop));
}

describe('the effort slider against the status frames of its own write', () => {
    it('starts on the stop the agents report', () => {
        expect(vm.shownStop).toBe('minimal');
        expect(vm.index).toBe(index('minimal'));
        expect(vm.stops[0]).toBe('off');
    });

    it('writes the Off stop and holds until the agents report it', async () => {
        dragTo('off');
        expect(applied).toEqual(['off']);
        await nextTick();
        expect(vm.shownStop).toBe('off');
        expect(vm.custom).toBe(false);
        expect(vm.cost).toBe('No extra requests.');
        deliver('conversation');
        deliver('memory');
        deliver('summarizer');
        await nextTick();
        expect(vm.heldStop).toBeNull();
        expect(vm.shownStop).toBe('off');
    });

    it('has no Off stop in Character perspectives', async () => {
        state.mode = 'perception';
        await nextTick();
        expect(vm.stops).toEqual(EFFORT_STOPS.perception);
        expect(vm.shownStop).not.toBe('off');
        expect(() => vm.cost).not.toThrow();
    });

    it('carries an Off pick that is still in its debounce to Minimal, the nearest stop the other table has', async () => {
        vi.useFakeTimers();
        state.agents = agentsAt('legacy', 'ultra');
        await nextTick();
        vm.pick(index('off'));
        state.mode = 'perception';
        await nextTick();
        expect(applied, 'the Off pick was dropped, or landed on the top stop').toEqual(['minimal']);
    });

    it('holds the knob where the drag left it while a stale frame arrives', async () => {
        vm.startDrag();
        vm.pick(index('ultra'));
        await nextTick();
        expect(vm.shownStop).toBe('ultra');

        deliver('conversation', agentsAt('legacy', 'light'));
        await nextTick();
        expect(vm.shownStop, 'a frame from before the drag moved the knob').toBe('ultra');
        expect(vm.custom).toBe(false);
    });

    it('holds it after the drag ends, until a frame carries the values that were sent', async () => {
        state.agents = agentsAt('legacy', 'light');
        await nextTick();
        dragTo('balanced');
        expect(applied).toEqual(['balanced']);
        // Light→Balanced is one key on one agent: the receipt cannot lean on
        // the other two agents reporting
        expect([...vm.awaiting.keys()]).toEqual(['conversation.character_knowledge']);
        await nextTick();
        expect(vm.shownStop).toBe('balanced');

        // the conversation agent starts an action and reports its pre-save state
        deliver('conversation', agentsAt('legacy', 'light'));
        await nextTick();
        expect(vm.shownStop, 'a busy frame from before the save released the hold').toBe('balanced');
        expect(vm.awaiting.size).toBe(1);
    });

    it('follows the agents again once a frame reports the values that were sent', async () => {
        state.agents = agentsAt('legacy', 'light');
        await nextTick();
        dragTo('balanced');
        await nextTick();
        deliver('conversation', agentsAt('legacy', 'balanced'));
        await nextTick();
        expect(vm.heldStop).toBeNull();
        expect(vm.shownStop).toBe('balanced');

        deliver('conversation', agentsAt('legacy', 'minimal'));
        await nextTick();
        expect(vm.shownStop).toBe('minimal');
    });

    it('keeps the knob under the finger when the previous send is answered mid-drag', async () => {
        state.agents = agentsAt('legacy', 'light');
        await nextTick();
        dragTo('balanced');
        await nextTick();
        expect([...vm.awaiting.keys()]).toEqual(['conversation.character_knowledge']);

        // the user starts a second drag before the first write is answered
        vm.startDrag();
        vm.pick(index('ultra'));
        await nextTick();
        expect(vm.shownStop).toBe('ultra');

        deliver('conversation', agentsAt('legacy', 'balanced'));
        await nextTick();
        expect(vm.shownStop, 'the first write\'s answer moved the knob under the finger').toBe('ultra');
        expect(vm.heldStop).toBe('ultra');
    });

    it('sends nothing while the drag is in progress, however long it rests on a stop', () => {
        vi.useFakeTimers();
        vm.startDrag();
        vm.pick(index('light'));
        vi.advanceTimersByTime(2000);
        expect(applied, 'a stop the drag only passed over was saved').toEqual([]);
        vm.pick(index('balanced'));
        vi.advanceTimersByTime(2000);
        expect(applied).toEqual([]);
        vm.finish(index('ultra'));
        expect(applied).toEqual(['ultra']);
    });

    it('sends once for a press on the track, which reports the move before the drag starts', () => {
        vi.useFakeTimers();
        // Vuetify's handleStart: onSliderMove, then onSliderStart
        vm.pick(index('light'));
        vm.startDrag();
        vi.advanceTimersByTime(2000);
        expect(applied, 'the stop the press landed on was saved on its own').toEqual([]);
        vm.pick(index('ultra'));
        vm.finish(index('ultra'));
        expect(applied).toEqual(['ultra']);
    });

    it('keeps a second keyboard step when the first one is answered inside its debounce', async () => {
        vi.useFakeTimers();
        state.agents = agentsAt('legacy', 'light');
        await nextTick();
        // an arrow key reaches pick() without a drag start
        vm.pick(index('balanced'));
        vi.advanceTimersByTime(SEND_DEBOUNCE);
        expect(applied).toEqual(['balanced']);

        vm.pick(index('thorough'));
        deliver('conversation', agentsAt('legacy', 'balanced'));
        await nextTick();
        vi.advanceTimersByTime(SEND_DEBOUNCE);
        expect(applied, 'the answer to the first step swallowed the second').toEqual(['balanced', 'thorough']);
    });

    it('waits for every action a patch touches on one agent', async () => {
        // Minimal to Light writes memory.topics and memory.retrieval
        dragTo('light');
        await nextTick();
        expect([...vm.awaiting.keys()]).toEqual(
            expect.arrayContaining(['memory.topics', 'memory.retrieval']),
        );

        // the write reached one of the two actions when this frame was emitted
        deliver('memory', agentsAt('legacy', 'light', { 'memory.retrieval.similarity_gate': false }));
        await nextTick();
        expect([...vm.awaiting.keys()]).toContain('memory.retrieval');
        expect([...vm.awaiting.keys()]).not.toContain('memory.topics');

        deliver('memory', agentsAt('legacy', 'light'));
        await nextTick();
        expect([...vm.awaiting.keys()]).not.toContain('memory.retrieval');
    });

    it('debounces the tick-click path and sends once', () => {
        vi.useFakeTimers();
        vm.pick(index('light'));
        vm.pick(index('balanced'));
        vi.advanceTimersByTime(100);
        expect(applied).toEqual([]);
        vi.advanceTimersByTime(250);
        expect(applied).toEqual(['balanced']);
    });

    it('neither sends nor holds when the stop is the one the agents already sit on', () => {
        vi.useFakeTimers();
        vm.pick(index('minimal'));
        vi.advanceTimersByTime(500);
        expect(applied).toEqual([]);
        expect(vm.heldStop).toBeNull();
    });

    it('carries a pick that is still in its debounce into the mode the user switched to', async () => {
        vi.useFakeTimers();
        vm.pick(index('ultra'));
        state.mode = 'perception';
        await nextTick();
        expect(applied, 'the pick was dropped by the mode switch').toEqual(['thorough']);
        expect(EFFORT_STOPS.perception).toContain(applied[0]);
    });

    it('clamps a held stop the mode has no row for', async () => {
        state.mode = 'perception';
        await nextTick();
        vm.heldStop = 'ultra';
        await nextTick();
        expect(EFFORT_STOPS.perception).not.toContain('ultra');
        expect(vm.shownStop).not.toBe('ultra');
        expect(() => vm.cost).not.toThrow();
    });

    it('takes no hold where the host writes a working copy it saves later', () => {
        app.unmount();
        host.remove();
        mount({ immediate: false });
        vi.useFakeTimers();
        dragTo('thorough');
        expect(applied).toEqual(['thorough']);
        expect(vm.heldStop, 'a hold no frame can answer was armed').toBeNull();
        expect(vm.awaiting).toBeNull();
    });

    it('lets go of a stop the agents never report, so the knob cannot freeze', () => {
        vi.useFakeTimers();
        dragTo('ultra');
        expect(vm.heldStop).toBe('ultra');
        vi.advanceTimersByTime(4000);
        expect(vm.heldStop).toBeNull();
    });

    it('prices a Custom state by what is actually on, not the nearest stop', async () => {
        state.agents = agentsAt('legacy', 'thorough', { 'conversation.character_knowledge.ledger': false });
        await nextTick();
        expect(vm.custom).toBe(true);
        expect(vm.cost).not.toContain('after a character line');
        expect(vm.cost).toContain('uncached retrieved memories');
    });

    it('answers a pinned scene write by override presence, not a matching value', async () => {
        app.unmount();
        host.remove();
        mount({ pin: true });
        state.agents = agentsAt('legacy', 'light');
        await nextTick();
        dragTo('balanced');
        expect(applied).toEqual(['balanced']);
        expect([...vm.awaiting.keys()]).toContain('conversation.character_knowledge');

        // the same values read off the globals are not the receipt
        deliver('conversation');
        await nextTick();
        expect([...vm.awaiting.keys()]).toContain('conversation.character_knowledge');

        const pinned = agentsAt('legacy', 'balanced');
        pinned[0].data.scene_overrides = { actions: { character_knowledge: { enabled: true, config: {
            perspective_filter: { value: true },
            absence_block: { value: true },
            awareness_line: { value: true },
            absence_limit: { value: 5 },
            absence_window: { value: 30 },
            memory_pass: { value: false },
            ledger: { value: true },
        } } } };
        deliver('conversation', pinned);
        await nextTick();
        expect([...vm.awaiting.keys()]).not.toContain('conversation.character_knowledge');
    });
});
