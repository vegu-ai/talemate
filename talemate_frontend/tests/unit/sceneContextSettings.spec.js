// @vitest-environment jsdom

import { describe, expect, it, vi } from 'vitest';
import { resolve } from 'node:path';
import { createApp, defineComponent, h, nextTick, reactive } from 'vue';
import Review from '@/components/SceneContextReviewInline.vue';
import { SCENE_HISTORY_KEYS } from '@/constants/sceneHistorySettings';
import { lift, readSource } from './helpers/liftMethod.js';
import { replyAfterAll } from '@/utils/writeReply';
import { sectionOverrideCounts } from '@/constants/sceneAgentSettings';
import { sceneOverlayFor } from '@/utils/sceneOverrideCommit';

const aiAgent = readSource(resolve(process.cwd(), 'src/components/AIAgent.vue'));

const CHOICES = [
  { label: 'Screenplay', value: 'movie_script' },
  { label: 'Chat (legacy)', value: 'chat' },
  { label: 'Narrative', value: 'narrative' },
  { label: 'AI Aware', value: 'ai_aware' },
];

function summarizerStatus({ format = 'movie_script', budget = 8192, bestFit = true } = {}, sceneOverrides = {}) {
  const config = {
    format: { type: 'text', label: 'Format', choices: CHOICES, value: format },
    best_fit: { type: 'bool', label: 'Best Fit Mode', value: bestFit },
    best_fit_min_dialogue: { type: 'number', label: 'Min. Dialogue Messages', value: 5, min: 0, max: 15, step: 1 },
    best_fit_max_dialogue: { type: 'number', label: 'Max. Dialogue Messages', value: 250, min: 10, max: 500, step: 10 },
    dialogue_ratio: { type: 'number', label: 'Dialogue Ratio', value: 50, min: 10, max: 90, step: 5 },
    summary_detail_ratio: { type: 'number', label: 'Summary Detail Ratio', value: 50, min: 10, max: 90, step: 5 },
    max_budget: { type: 'number', label: 'Max. Budget', value: budget, min: 0, max: 262144, step: 512 },
    enforce_boundary: { type: 'bool', label: 'Enforce Summary Boundary', value: false },
  };
  return { actions: { manage_scene_history: { container: true, config } }, scene_overrides: sceneOverrides };
}

function override(values) {
  const config = Object.fromEntries(Object.entries(values).map(([key, value]) => [key, { value }]));
  return { actions: { manage_scene_history: { config } } };
}

const Container = defineComponent({ setup: (_, { slots }) => () => h('div', slots.default?.()) });

// controls stand-ins, read as controls['<row>:<kind>']; the row is resolved on
// read, because Vue sets a parent's attributes after it mounts the children
const mounted = [];
const controls = new Proxy({}, {
  get(target, name) {
    if (typeof name !== 'string' || !name.includes(':')) return target[name];
    const [row, kind] = name.split(':');
    return mounted.find(entry => entry.kind === kind && entry.el.isConnected
      && entry.el.closest('[data-testid^="scene-history-"]')?.dataset.testid === `scene-history-${row}`);
  },
});
function control(kind) {
  return defineComponent({
    props: ['modelValue', 'items', 'disabled', 'label', 'ariaLabel'],
    emits: ['update:modelValue', 'start', 'end', 'update:focused', 'change', 'keydown', 'click'],
    setup(props, { emit, slots }) {
      return () => h('div', {
        'data-control': kind,
        'data-value': String(props.modelValue),
        'data-disabled': String(!!props.disabled),
        ref: (el) => {
          if (el && !mounted.some(entry => entry.el === el)) mounted.push({ el, kind, props, emit });
        },
      }, slots.default?.());
    },
  });
}
const Chip = defineComponent({
  props: ['value', 'ariaLabel'],
  emits: ['click'],
  setup(props, { emit, slots, attrs }) {
    return () => h('button', { 'data-chip': String(props.value ?? ''), 'aria-label': props.ariaLabel, onClick: (event) => emit('click', event), ...attrs }, slots.default?.());
  },
});
const ChipGroup = defineComponent({
  props: ['modelValue'],
  emits: ['update:modelValue'],
  setup(props, { emit, slots }) {
    return () => {
      controls.perspective = { props, pick: (value) => emit('update:modelValue', value) };
      return h('div', slots.default?.());
    };
  },
});
const Tooltip = defineComponent({ setup: (_, { slots }) => () => h('span', slots.activator?.({ props: {} })) });

const VUETIFY = ['VCard', 'VCardItem', 'VCardTitle', 'VCardSubtitle', 'VCardText', 'VCardActions', 'VRow', 'VCol', 'VDivider',
  'VIcon', 'VAlert', 'VSpacer', 'VProgressCircular', 'VProgressLinear', 'VExpansionPanels', 'VExpansionPanel',
  'VExpansionPanelTitle', 'VExpansionPanelText'];

function mountReview({ status = summarizerStatus(), overridesState = { busy: false, error: null } } = {}) {
  mounted.length = 0;
  const sent = [];
  const handlers = new Set();
  const applyAgentValues = vi.fn(() => true);
  const applySceneAgentValues = vi.fn();
  const clearSceneAgentValues = vi.fn();
  const props = reactive({ visible: true, connected: true, sceneId: 'scene-1', agentStatus: { summarizer: status } });
  const app = createApp({ render: () => h(Review, { ...props, ref: 'review' }) });
  for (const name of VUETIFY) app.component(name, Container);
  app.component('VSelect', control('select'));
  app.component('VSlider', control('slider'));
  app.component('VNumberInput', control('number'));
  app.component('VCheckboxBtn', control('bool'));
  app.component('VChip', Chip);
  app.component('VChipGroup', ChipGroup);
  app.component('VBtn', Chip);
  app.component('VTooltip', Tooltip);
  app.provide('getWebsocket', () => ({ send: text => sent.push(JSON.parse(text)) }));
  app.provide('registerMessageHandler', fn => handlers.add(fn));
  app.provide('unregisterMessageHandler', fn => handlers.delete(fn));
  app.provide('appConfig', {});
  app.provide('applyAgentValues', applyAgentValues);
  app.provide('applySceneAgentValues', applySceneAgentValues);
  app.provide('clearSceneAgentValues', clearSceneAgentValues);
  app.provide('sceneOverridesState', () => overridesState);
  app.provide('openAgentSettings', vi.fn());
  app.provide('retrySceneOverrides', vi.fn());
  app.provide('discardSceneOverrides', vi.fn());
  const host = document.createElement('div');
  document.body.appendChild(host);
  app.mount(host);
  const reviews = () => sent.filter(frame => frame.action === 'context_review');
  const answer = () => {
    const request = reviews().at(-1);
    [...handlers].forEach(fn => fn({ type: 'summarizer', action: 'context_review', request_id: request.request_id, data: {
      characters: ['Mara', 'Edwin'], sections: [], exclusions: [], budget: { total: 8192 },
      summary: { total_tokens: 0, max_budget: 8192, best_fit: true },
    } }));
  };
  const row = key => host.querySelector(`[data-testid="scene-history-${key}"]`);
  const unmount = () => { app.unmount(); host.remove(); };
  return { host, props, sent, reviews, answer, row, unmount, applyAgentValues, applySceneAgentValues, clearSceneAgentValues };
}

function setStatus(props, status) {
  // what TalemateApp does with an agent_status frame
  props.agentStatus = { ...props.agentStatus, summarizer: status };
}

const origin = (t, key) => {
  const head = t.row(key).querySelector('.setting-head');
  if (head.querySelector('[aria-label^="Use global settings for"]')) return 'scene';
  if (head.querySelector('[aria-label^="Override"]')) return 'global';
  return null;
};
const click = el => el.dispatchEvent(new MouseEvent('click', { bubbles: true }));
const tick = () => new Promise(resolve => setTimeout(resolve, 0));
const wait = ms => new Promise(resolve => setTimeout(resolve, ms));

describe('view controls and settings', () => {
  it('keeps the perspective and the one Refresh out of the settings card', async () => {
    const t = mountReview();
    t.answer();
    await nextTick();
    const toolbar = t.host.querySelector('[data-testid="scene-context-view-controls"]');
    const card = t.host.querySelector('[data-testid="scene-history-settings"]');
    expect(toolbar.textContent).toContain('Preview for');
    expect(toolbar.textContent).toContain('Edwin');
    expect(t.host.querySelectorAll('[data-testid="scene-context-refresh"]')).toHaveLength(1);
    expect(card.textContent).not.toContain('Refresh');
    expect(card.textContent).not.toContain('Apply');
    expect([...t.host.querySelectorAll('button')].filter(b => b.textContent.trim() === 'Refresh')).toHaveLength(1);

    controls.perspective.pick('Edwin');
    await nextTick();
    expect(t.reviews().at(-1)).toMatchObject({ character: 'Edwin' });
    expect(t.reviews().at(-1).overrides).toBeUndefined();
    t.unmount();
  });

  it('shows the empty state call to action only while there is no preview', async () => {
    const t = mountReview();
    t.props.connected = false;
    await nextTick();
    expect(t.host.querySelector('[data-testid="scene-context-empty"]')).not.toBeNull();
    t.props.connected = true;
    await nextTick();
    t.answer();
    await nextTick();
    expect(t.host.querySelector('[data-testid="scene-context-empty"]')).toBeNull();
    t.unmount();
  });

  it('shows the rows of the current mode, each with its origin', async () => {
    const t = mountReview({ status: summarizerStatus({}, override({ format: 'chat' })) });
    await nextTick();
    expect(t.row('best_fit_min_dialogue')).not.toBeNull();
    expect(t.row('dialogue_ratio')).toBeNull();
    expect(origin(t, 'format')).toBe('scene');
    expect(origin(t, 'max_budget')).toBe('global');
    expect(controls['format:select'].props.modelValue).toBe('chat');
    expect(t.host.querySelector('[data-testid="scene-history-origin-summary"]').textContent).toContain('1 scene override');
    t.unmount();
  });
});

describe('the Summarizer settings page and the view stay in sync', () => {
  it('follows a value and an override made on the page, and refreshes once', async () => {
    const t = mountReview();
    t.answer();
    await nextTick();

    setStatus(t.props, summarizerStatus({ budget: 4096 }));
    await nextTick();
    expect(controls['max_budget:number'].props.modelValue).toBe(4096);
    expect(t.reviews()).toHaveLength(2);

    // the page's Scene tab saved an override of the format
    setStatus(t.props, summarizerStatus({ budget: 4096 }, override({ format: 'narrative' })));
    await nextTick();
    expect(origin(t, 'format')).toBe('scene');
    expect(controls['format:select'].props.modelValue).toBe('narrative');
    expect(t.reviews()).toHaveLength(3);

    // the same values again are not a change
    setStatus(t.props, summarizerStatus({ budget: 4096 }, override({ format: 'narrative' })));
    await nextTick();
    expect(t.reviews()).toHaveLength(3);
    t.unmount();
  });

  it('an override made in the view is counted on the page section header', async () => {
    const t = mountReview();
    await nextTick();
    click(t.row('max_budget').querySelector('[aria-label^="Override"]'));
    const [entries] = t.applySceneAgentValues.mock.calls[0];
    expect(entries).toEqual([{ agent: 'summarizer', action: 'manage_scene_history', config: { max_budget: 8192 } }]);

    // the backend stores the patch and reports the agent; the page reads that status
    const stored = override({ max_budget: 8192 });
    const live = { summarizer: { data: { scene_overrides: stored } } };
    const pageOverlay = sceneOverlayFor({ buffer: {}, liveAgents: live }, 'summarizer');
    expect(sectionOverrideCounts(pageOverlay, { manage_scene_history: { container: true } })).toEqual({ manage_scene_history: 1 });

    setStatus(t.props, summarizerStatus({}, stored));
    t.applySceneAgentValues.mock.calls[0][2].onComplete();
    await nextTick();
    expect(origin(t, 'max_budget')).toBe('scene');
    t.unmount();
  });
});

describe('a write goes to the origin the row shows', () => {
  it('writes a global value through the agent write path and refreshes after the answer', async () => {
    const t = mountReview();
    t.answer();
    await nextTick();
    controls['format:select'].emit('update:modelValue', 'chat');
    await nextTick();

    expect(t.applyAgentValues).toHaveBeenCalledWith('summarizer', 'manage_scene_history', { config: { format: 'chat' } }, expect.any(Object));
    expect(t.applySceneAgentValues).not.toHaveBeenCalled();
    expect(controls['format:select'].props.modelValue).toBe('chat');
    expect(controls['format:select'].props.disabled).toBe(true);

    // the status echo arrives before the answer
    setStatus(t.props, summarizerStatus({ format: 'chat' }));
    await nextTick();
    expect(t.reviews()).toHaveLength(1);

    t.applyAgentValues.mock.calls[0][3].onComplete();
    await nextTick();
    expect(t.reviews()).toHaveLength(2);
    expect(controls['format:select'].props.disabled).toBe(false);
    t.unmount();
  });

  it('writes an overridden value to the scene override through the hub writer', async () => {
    const t = mountReview({ status: summarizerStatus({}, override({ max_budget: 4096 })) });
    t.answer();
    await nextTick();
    controls['max_budget:number'].emit('update:modelValue', 2048);
    controls['max_budget:number'].emit('update:focused', false);
    await tick();

    expect(t.applyAgentValues).not.toHaveBeenCalled();
    const [entries, label, reply] = t.applySceneAgentValues.mock.calls[0];
    expect(entries).toEqual([{ agent: 'summarizer', action: 'manage_scene_history', config: { max_budget: 2048 } }]);
    expect(label).toBe('Scene history: Max. Budget');

    setStatus(t.props, summarizerStatus({}, override({ max_budget: 2048 })));
    reply.onComplete();
    await nextTick();
    expect(controls['max_budget:number'].props.modelValue).toBe(2048);
    expect(t.reviews()).toHaveLength(2);
    t.unmount();
  });

  it('a slider writes when it is released, not while it moves', async () => {
    const t = mountReview();
    await nextTick();
    controls['best_fit_min_dialogue:slider'].emit('start', 5);
    controls['best_fit_min_dialogue:slider'].emit('update:modelValue', 7);
    controls['best_fit_min_dialogue:slider'].emit('update:modelValue', 8);
    await nextTick();
    expect(t.applyAgentValues).not.toHaveBeenCalled();
    controls['best_fit_min_dialogue:slider'].emit('end', 8);
    await nextTick();
    expect(t.applyAgentValues).toHaveBeenCalledTimes(1);
    expect(t.applyAgentValues.mock.calls[0][2]).toEqual({ config: { best_fit_min_dialogue: 8 } });
    t.unmount();
  });

  it('a refused scene write returns the row to the confirmed value and shows the error', async () => {
    const t = mountReview({ status: summarizerStatus({}, override({ format: 'chat' })) });
    t.answer();
    await nextTick();
    controls['format:select'].emit('update:modelValue', 'narrative');
    await nextTick();
    expect(controls['format:select'].props.modelValue).toBe('narrative');

    t.applySceneAgentValues.mock.calls[0][2].onError('Failed to write agent-settings file');
    await nextTick();
    expect(controls['format:select'].props.modelValue).toBe('chat');
    expect(t.host.querySelector('[data-testid="scene-history-error"]').textContent).toContain('Format was not saved: Failed to write agent-settings file');
    expect(t.reviews()).toHaveLength(1);

    // a second selection sends the write again
    controls['format:select'].emit('update:modelValue', 'narrative');
    await nextTick();
    expect(t.applySceneAgentValues).toHaveBeenCalledTimes(2);
    t.unmount();
  });
});

describe('scene overrides from the view', () => {
  it('makes an override with the current value, and goes back to global for one and for all', async () => {
    const t = mountReview({ status: summarizerStatus({}, override({ format: 'chat', max_budget: 4096 })) });
    await nextTick();

    click(t.row('best_fit').querySelector('[aria-label^="Override"]'));
    expect(t.applySceneAgentValues.mock.calls[0][0]).toEqual([{ agent: 'summarizer', action: 'manage_scene_history', config: { best_fit: true } }]);

    click(t.row('format').querySelector('[aria-label="Use global settings for Format"]'));
    expect(t.clearSceneAgentValues.mock.calls[0][0]).toEqual([{ agent: 'summarizer', action: 'manage_scene_history', config: 'format' }]);

    click(t.host.querySelector('[aria-label="Use global settings for all scene history settings"]'));
    const cleared = t.clearSceneAgentValues.mock.calls[1][0].map(entry => entry.config).sort();
    expect(cleared).toEqual([...SCENE_HISTORY_KEYS].sort());
    t.unmount();
  });

  it('locks the overridden rows while the hub writer is busy', async () => {
    const t = mountReview({ status: summarizerStatus({}, override({ format: 'chat' })), overridesState: { busy: true, error: null } });
    await nextTick();
    expect(controls['format:select'].props.disabled).toBe(true);
    expect(controls['max_budget:number'].props.disabled).toBe(false);
    t.unmount();
  });
});

// the app's global write path: the drawer's own applyActionValues on the status objects both views read
function throughDrawer(t) {
  const applyActionValues = lift(aiAgent, 'applyActionValues', 'AIAgent.vue', { replyAfterAll });
  const saves = [];
  const drawer = {
    saveAgent: (agent, reply) => saves.push(reply), saveSceneOverrideSlice: vi.fn(),
    sceneOverlay: () => ({}), isEnabledOverridden: () => false, isConfigOverridden: () => false,
  };
  t.applyAgentValues.mockImplementation((name, action, values, reply) =>
    applyActionValues.call(drawer, { name, actions: t.props.agentStatus.summarizer.actions }, action, values, reply));
  return saves;
}
const sharedFormat = t => t.props.agentStatus.summarizer.actions.manage_scene_history.config.format.value;

describe('a failed global write', () => {
  it('returns both views to the confirmed value and a second selection sends the write', async () => {
    const t = mountReview();
    const saves = throughDrawer(t);
    t.answer();
    await nextTick();
    controls['format:select'].emit('update:modelValue', 'narrative');
    await nextTick();
    expect(sharedFormat(t)).toBe('narrative');

    saves[0].onError('disk full');
    await nextTick();
    expect(sharedFormat(t)).toBe('movie_script');
    expect(controls['format:select'].props.modelValue).toBe('movie_script');
    expect(t.host.querySelector('[data-testid="scene-history-error"]').textContent).toContain('Format was not saved: disk full');
    expect(t.reviews()).toHaveLength(1);

    controls['format:select'].emit('update:modelValue', 'narrative');
    await nextTick();
    expect(saves).toHaveLength(2);
    saves[1].onComplete();
    await nextTick();
    expect(sharedFormat(t)).toBe('narrative');
    expect(t.reviews()).toHaveLength(2);
    expect(t.host.querySelector('[data-testid="scene-history-error"]')).toBeNull();
    t.unmount();
  });

  it('a failed apply keeps the stored value and shows the backend message as is', async () => {
    const t = mountReview();
    const saves = throughDrawer(t);
    t.answer();
    await nextTick();
    controls['format:select'].emit('update:modelValue', 'chat');
    await nextTick();
    saves[0].onError('Configuration was saved, but applying it failed.', true);
    await nextTick();
    expect(sharedFormat(t)).toBe('chat');
    const alert = t.host.querySelector('[data-testid="scene-history-error"]').textContent;
    expect(alert).toContain('Configuration was saved, but applying it failed.');
    expect(alert).not.toContain('not saved');
    t.unmount();
  });
});


describe('changes that are not a drag or a typed value', () => {
  it('a press on the track writes once, at the release', async () => {
    const t = mountReview();
    await nextTick();
    // Vuetify reports the move of a track press before the start of the drag
    controls['best_fit_min_dialogue:slider'].emit('update:modelValue', 8);
    controls['best_fit_min_dialogue:slider'].emit('start', 8);
    controls['best_fit_min_dialogue:slider'].emit('update:modelValue', 9);
    controls['best_fit_min_dialogue:slider'].emit('update:modelValue', 10);
    await wait(300);
    expect(t.applyAgentValues).not.toHaveBeenCalled();
    expect(controls['best_fit_min_dialogue:slider'].props.modelValue).toBe(10);
    controls['best_fit_min_dialogue:slider'].emit('end', 10);
    await nextTick();
    expect(t.applyAgentValues).toHaveBeenCalledTimes(1);
    expect(t.applyAgentValues.mock.calls[0][2]).toEqual({ config: { best_fit_min_dialogue: 10 } });
    t.unmount();
  });

  it('a burst of arrow keys writes once, and a key pressed while the row waits is written after it', async () => {
    const t = mountReview();
    await nextTick();
    controls['best_fit_min_dialogue:slider'].emit('update:modelValue', 6);
    controls['best_fit_min_dialogue:slider'].emit('update:modelValue', 7);
    await nextTick();
    expect(t.applyAgentValues).not.toHaveBeenCalled();
    await wait(300);
    expect(t.applyAgentValues).toHaveBeenCalledTimes(1);
    expect(t.applyAgentValues.mock.calls[0][2]).toEqual({ config: { best_fit_min_dialogue: 7 } });

    // the slider stays usable while its row waits
    expect(controls['best_fit_min_dialogue:slider'].props.disabled).toBe(false);
    controls['best_fit_min_dialogue:slider'].emit('update:modelValue', 8);
    await wait(300);
    expect(t.applyAgentValues).toHaveBeenCalledTimes(1);

    t.props.agentStatus.summarizer.actions.manage_scene_history.config.best_fit_min_dialogue.value = 7;
    t.applyAgentValues.mock.calls[0][3].onComplete();
    await nextTick();
    expect(t.applyAgentValues).toHaveBeenCalledTimes(2);
    expect(t.applyAgentValues.mock.calls[1][2]).toEqual({ config: { best_fit_min_dialogue: 8 } });
    t.unmount();
  });

  it('a stepper click writes the stepped value', async () => {
    const t = mountReview();
    await nextTick();
    controls['max_budget:number'].emit('update:modelValue', 8704);
    controls['max_budget:number'].emit('change');
    await tick();
    expect(t.applyAgentValues.mock.calls[0][2]).toEqual({ config: { max_budget: 8704 } });
    t.unmount();
  });

  it('a typed value out of range writes the value the field settles on', async () => {
    const t = mountReview();
    await nextTick();
    // the field keeps the last in-range keystroke, then clamps in its blur handler
    controls['max_budget:number'].emit('update:modelValue', 30000);
    controls['max_budget:number'].emit('update:focused', false);
    controls['max_budget:number'].emit('update:modelValue', 262144);
    await tick();
    expect(t.applyAgentValues).toHaveBeenCalledTimes(1);
    expect(t.applyAgentValues.mock.calls[0][2]).toEqual({ config: { max_budget: 262144 } });
    t.unmount();
  });

  it('Enter writes the typed text, clamped to the range', async () => {
    const t = mountReview();
    await nextTick();
    controls['max_budget:number'].emit('update:modelValue', 30000);
    controls['max_budget:number'].emit('keydown', { key: 'Enter', target: { value: '300000' } });
    await nextTick();
    expect(t.applyAgentValues).toHaveBeenCalledTimes(1);
    expect(t.applyAgentValues.mock.calls[0][2]).toEqual({ config: { max_budget: 262144 } });
    t.unmount();
  });
});

describe('a row waits for the agent status', () => {
  it('stays on the sent value when the answer arrives before the status', async () => {
    const t = mountReview({ status: summarizerStatus({}, override({ format: 'chat' })) });
    t.answer();
    await nextTick();
    controls['format:select'].emit('update:modelValue', 'narrative');
    await nextTick();
    t.applySceneAgentValues.mock.calls[0][2].onComplete();
    await nextTick();
    expect(controls['format:select'].props.modelValue).toBe('narrative');
    expect(controls['format:select'].props.disabled).toBe(true);
    expect(t.reviews()).toHaveLength(1);

    setStatus(t.props, summarizerStatus({}, override({ format: 'narrative' })));
    await nextTick();
    expect(controls['format:select'].props.modelValue).toBe('narrative');
    expect(controls['format:select'].props.disabled).toBe(false);
    expect(t.reviews()).toHaveLength(2);
    t.unmount();
  });

  it('keeps a new override locked until its status, so no change goes to the global value', async () => {
    const t = mountReview();
    await nextTick();
    click(t.row('max_budget').querySelector('[aria-label^="Override"]'));
    t.applySceneAgentValues.mock.calls[0][2].onComplete();
    await nextTick();
    expect(controls['max_budget:number'].props.disabled).toBe(true);
    controls['max_budget:number'].emit('update:modelValue', 4096);
    controls['max_budget:number'].emit('update:focused', false);
    await tick();
    expect(t.applyAgentValues).not.toHaveBeenCalled();

    // a value made during the origin change belongs to neither origin
    setStatus(t.props, summarizerStatus({}, override({ max_budget: 8192 })));
    await nextTick();
    await tick();
    expect(origin(t, 'max_budget')).toBe('scene');
    expect(t.applySceneAgentValues).toHaveBeenCalledTimes(1);
    expect(t.applyAgentValues).not.toHaveBeenCalled();
    t.unmount();
  });
});

describe('the card follows the scene', () => {
  it('shows a lost answer as it is, and clears it when the connection returns', async () => {
    const t = mountReview({ status: summarizerStatus({}, override({ max_budget: 4096 })) });
    await nextTick();
    controls['max_budget:number'].emit('keydown', { key: 'Enter', target: { value: '2048' } });
    await nextTick();
    const lost = 'The connection closed before the answer arrived; the change may have been saved.';
    t.applySceneAgentValues.mock.calls[0][2].onError(lost, false, true);
    await nextTick();
    expect(t.host.querySelector('[data-testid="scene-history-error"]').textContent.trim()).toBe(lost);

    t.props.connected = false;
    await nextTick();
    t.props.connected = true;
    await nextTick();
    expect(t.host.querySelector('[data-testid="scene-history-error"]')).toBeNull();
    t.unmount();
  });

  it('clears an error and a draft of the previous scene', async () => {
    const t = mountReview({ status: summarizerStatus({}, override({ format: 'chat' })) });
    await nextTick();
    controls['format:select'].emit('update:modelValue', 'narrative');
    await nextTick();
    t.applySceneAgentValues.mock.calls[0][2].onError('The change was discarded.');
    await nextTick();
    expect(t.host.querySelector('[data-testid="scene-history-error"]')).not.toBeNull();

    t.props.sceneId = 'scene-2';
    await nextTick();
    expect(t.host.querySelector('[data-testid="scene-history-error"]')).toBeNull();
    t.unmount();
  });

  it('shows an override of the other Best Fit mode', async () => {
    const t = mountReview({ status: summarizerStatus({ bestFit: true }, override({ dialogue_ratio: 30 })) });
    await nextTick();
    expect(t.row('dialogue_ratio')).not.toBeNull();
    expect(origin(t, 'dialogue_ratio')).toBe('scene');
    expect(t.row('summary_detail_ratio')).toBeNull();
    t.unmount();
  });

  it('names every control by its row label', async () => {
    const t = mountReview();
    await nextTick();
    for (const [key, kind] of [['format', 'select'], ['max_budget', 'number']]) {
      const id = t.row(key).querySelector(`[data-control="${kind}"]`).getAttribute('aria-labelledby');
      expect(t.host.querySelector(`#${id}`).textContent).toBe(key === 'format' ? 'Format' : 'Max. Budget');
    }
    expect(controls['best_fit_min_dialogue:slider'].props.ariaLabel).toBe('Min. Dialogue Messages');
    t.unmount();
  });
});

// a real thumb ignores keys and the pointer while it is disabled
const userMoves = (ctrl, ...args) => { if (!ctrl.props.disabled) ctrl.emit(...args); };

describe('a slider draft and an origin change', () => {
  it('a key on a Scene row, then Scene within the debounce: nothing goes to the global value', async () => {
    const t = mountReview({ status: summarizerStatus({}, override({ best_fit_min_dialogue: 5 })) });
    await nextTick();
    controls['best_fit_min_dialogue:slider'].emit('update:modelValue', 6);
    click(t.row('best_fit_min_dialogue').querySelector('[aria-label="Use global settings for Min. Dialogue Messages"]'));
    expect(t.clearSceneAgentValues).toHaveBeenCalledTimes(1);
    await wait(300);

    setStatus(t.props, summarizerStatus({}));
    t.clearSceneAgentValues.mock.calls[0][1].onComplete();
    await nextTick();
    await wait(300);
    expect(origin(t, 'best_fit_min_dialogue')).toBe('global');
    expect(t.applyAgentValues).not.toHaveBeenCalled();
    expect(t.applySceneAgentValues).not.toHaveBeenCalled();
    t.unmount();
  });

  it('a key on a Global row, then Global within the debounce: only the override is written', async () => {
    const t = mountReview();
    await nextTick();
    controls['best_fit_min_dialogue:slider'].emit('update:modelValue', 6);
    click(t.row('best_fit_min_dialogue').querySelector('[aria-label^="Override"]'));
    await wait(300);
    setStatus(t.props, summarizerStatus({}, override({ best_fit_min_dialogue: 5 })));
    t.applySceneAgentValues.mock.calls[0][2].onComplete();
    await nextTick();
    await wait(300);
    expect(t.applySceneAgentValues).toHaveBeenCalledTimes(1);
    expect(t.applySceneAgentValues.mock.calls[0][0][0].config).toEqual({ best_fit_min_dialogue: 5 });
    expect(t.applyAgentValues).not.toHaveBeenCalled();
    t.unmount();
  });

  it('a slider is locked while its origin changes', async () => {
    const t = mountReview();
    await nextTick();
    click(t.row('best_fit_min_dialogue').querySelector('[aria-label^="Override"]'));
    await nextTick();
    expect(controls['best_fit_min_dialogue:slider'].props.disabled).toBe(true);
    t.unmount();
  });

  it('a key on a Scene row while its own scene write is in flight is kept and written after it', async () => {
    const overridesState = reactive({ busy: false, error: null });
    const t = mountReview({ status: summarizerStatus({}, override({ best_fit_min_dialogue: 5 })), overridesState });
    await nextTick();
    const slider = () => controls['best_fit_min_dialogue:slider'];
    userMoves(slider(), 'update:modelValue', 6);
    await wait(300);
    expect(t.applySceneAgentValues).toHaveBeenCalledTimes(1);
    overridesState.busy = true;
    await nextTick();

    expect(slider().props.disabled).toBe(false);
    userMoves(slider(), 'update:modelValue', 7);
    await wait(300);
    expect(t.applySceneAgentValues).toHaveBeenCalledTimes(1);

    overridesState.busy = false;
    setStatus(t.props, summarizerStatus({}, override({ best_fit_min_dialogue: 6 })));
    t.applySceneAgentValues.mock.calls[0][2].onComplete();
    await nextTick();
    expect(t.applySceneAgentValues).toHaveBeenCalledTimes(2);
    expect(t.applySceneAgentValues.mock.calls[1][0][0].config).toEqual({ best_fit_min_dialogue: 7 });
    expect(t.applyAgentValues).not.toHaveBeenCalled();
    t.unmount();
  });
});

describe('slider drafts at the edges of a write', () => {
  it('a write refused during a drag keeps the drag: one write, at the release', async () => {
    const t = mountReview();
    await nextTick();
    const slider = () => controls['best_fit_min_dialogue:slider'];
    slider().emit('update:modelValue', 6);
    await wait(300);
    expect(t.applyAgentValues).toHaveBeenCalledTimes(1);

    // a track press and a drag while 6 is in flight
    slider().emit('update:modelValue', 8);
    slider().emit('start', 8);
    t.applyAgentValues.mock.calls[0][3].onError('refused');
    await nextTick();
    slider().emit('update:modelValue', 9);
    await wait(300);
    expect(t.applyAgentValues).toHaveBeenCalledTimes(1);
    expect(t.host.querySelector('[data-testid="scene-history-error"]').textContent).toContain('refused');

    slider().emit('end', 10);
    await nextTick();
    expect(t.applyAgentValues).toHaveBeenCalledTimes(2);
    expect(t.applyAgentValues.mock.calls[1][2]).toEqual({ config: { best_fit_min_dialogue: 10 } });
    t.unmount();
  });

  it('a key on a Scene row, then Use global within the debounce: nothing is written', async () => {
    const t = mountReview({ status: summarizerStatus({}, override({ best_fit_min_dialogue: 5 })) });
    await nextTick();
    controls['best_fit_min_dialogue:slider'].emit('update:modelValue', 6);
    click(t.host.querySelector('[aria-label="Use global settings for all scene history settings"]'));
    expect(t.clearSceneAgentValues).toHaveBeenCalledTimes(1);
    await wait(300);
    setStatus(t.props, summarizerStatus({}));
    t.clearSceneAgentValues.mock.calls[0][1].onComplete();
    await nextTick();
    await wait(300);
    expect(t.applyAgentValues).not.toHaveBeenCalled();
    expect(t.applySceneAgentValues).not.toHaveBeenCalled();
    t.unmount();
  });

  it('Use global while a row waits for its status does not bring the override back', async () => {
    const t = mountReview({ status: summarizerStatus({}, override({ best_fit_min_dialogue: 5 })) });
    await nextTick();
    const slider = () => controls['best_fit_min_dialogue:slider'];
    slider().emit('update:modelValue', 6);
    await wait(300);
    expect(t.applySceneAgentValues).toHaveBeenCalledTimes(1);
    slider().emit('update:modelValue', 7);
    t.applySceneAgentValues.mock.calls[0][2].onComplete();
    await nextTick();

    // before the status of 6 arrives
    click(t.host.querySelector('[aria-label="Use global settings for all scene history settings"]'));
    expect(t.clearSceneAgentValues).toHaveBeenCalledTimes(1);
    setStatus(t.props, summarizerStatus({}, override({ best_fit_min_dialogue: 6 })));
    await nextTick();
    await wait(300);
    expect(t.applySceneAgentValues).toHaveBeenCalledTimes(1);
    expect(t.applyAgentValues).not.toHaveBeenCalled();
    t.unmount();
  });
});
