// @vitest-environment jsdom

import { describe, expect, it, vi } from 'vitest';
import Review from '@/components/SceneContextReviewInline.vue';
import PromptsView from '@/components/prompts/PromptsView.vue';
import { createApp, defineComponent, h, nextTick, reactive } from 'vue';

function review({ sceneId = 'scene-1' } = {}) {
  const sent = [];
  const handlers = new Set();
  const vm = {
    ...Review.data(), visible: true, connected: true, sceneId, sent, handlers,
    getWebsocket: () => ({ send: text => sent.push(JSON.parse(text)) }),
    registerMessageHandler: vi.fn(fn => handlers.add(fn)),
    unregisterMessageHandler: vi.fn(fn => handlers.delete(fn)),
  };
  for (const [key, method] of Object.entries(Review.methods)) vm[key] = method.bind(vm);
  for (const [key, getter] of Object.entries(Review.computed)) Object.defineProperty(vm, key, { get: () => getter.call(vm) });
  vm.receive = frame => [...handlers].forEach(fn => fn(frame));
  return vm;
}

function response(request, extra = {}) {
  return { type: 'summarizer', action: 'context_review', request_id: request.request_id, data: {
    perspective: request.character, characters: ['Alice', 'Bob'], sections: [], exclusions: [],
    budget: { total: 8192 }, summary: { total_tokens: 10, max_budget: 8192, dialogue_ratio: 50, summary_detail_ratio: 50, enforce_boundary: false, best_fit: true, best_fit_min_dialogue: 3, best_fit_max_dialogue: 250 }, ...extra,
  } };
}

describe('character context review', () => {
  it('loads when the local Scene Context tab opens and hides with Prompts', async () => {
    const Container = defineComponent({ setup: (_, { slots }) => () => h('div', slots.default?.()) });
    const Preview = defineComponent({ props: ['visible'], setup: props => () => h('div', { 'data-preview-visible': String(props.visible) }) });
    const props = reactive({ visible: true });
    const Subject = { ...PromptsView, components: Object.fromEntries(Object.keys(PromptsView.components).map(name => [name, name === 'SceneContextReviewInline' ? Preview : Container])) };
    const app = createApp({ render: () => h(Subject, { ...props, ref: 'subject' }) });
    const host = document.createElement('div');
    const errors = [];
    app.config.errorHandler = error => errors.push(error);
    for (const name of ['VCard', 'VCardTitle', 'VCardSubtitle', 'VCardText', 'VCardActions', 'VIcon', 'VTabs', 'VTab', 'VChip', 'VWindow', 'VWindowItem', 'VProgressCircular', 'VBtn', 'VTooltip', 'VSpacer', 'VDialog', 'VForm', 'VTextField', 'VSnackbar']) app.component(name, Container);
    app.provide('getWebsocket', () => ({ send: vi.fn() }));
    app.provide('registerMessageHandler', vi.fn());
    app.provide('unregisterMessageHandler', vi.fn());
    app.provide('scene', {});
    const root = app.mount(host);
    try {
      expect(host.querySelector('[data-preview-visible]').dataset.previewVisible).toBe('false');
      root.$refs.subject.onMainTabChange('context-review');
      await nextTick();
      expect(root.$refs.subject.mainTab).toBe('prompts');
      expect(host.querySelector('[data-preview-visible]').dataset.previewVisible).toBe('true');
      props.visible = false;
      await nextTick();
      expect(host.querySelector('[data-preview-visible]').dataset.previewVisible).toBe('false');
      expect(errors).toEqual([]);
    } finally {
      app.unmount();
    }
  });

  it('starts with Scene and offers the returned active characters', () => {
    const vm = review();
    vm.fetchPreview();
    expect(vm.sent[0].character).toBeNull();
    vm.receive(response(vm.sent[0]));
    expect(vm.characterOptions).toEqual([{ title: 'Scene (default)', value: null }, { title: 'Alice', value: 'Alice' }, { title: 'Bob', value: 'Bob' }]);
    expect(vm.loading).toBe(false);
    expect(vm.handlers.size).toBe(1);
  });

  it('selection and refresh preserve the character and budget edits', () => {
    const vm = review();
    vm.fetchPreview();
    vm.receive(response(vm.sent[0]));
    vm.overrides.max_budget = 512;
    vm.selectedCharacter = 'Bob';
    Review.watch.selectedCharacter.call(vm);
    expect(vm.preview).toBeNull();
    expect(vm.sent[1].character).toBe('Bob');
    expect(vm.sent[1].overrides.max_budget).toBe(512);
    vm.receive(response(vm.sent[1]));
    vm.fetchPreview();
    expect(vm.sent[2].character).toBe('Bob');
    expect(vm.sent[2].overrides.max_budget).toBe(512);
  });

  it('adopts effective history controls for a character perspective', () => {
    const vm = review();
    vm.selectedCharacter = 'Bob';
    vm.fetchPreview();
    vm.receive(response(vm.sent[0], { summary: {
      total_tokens: 45, max_budget: 1024, dialogue_ratio: 35,
      summary_detail_ratio: 70, enforce_boundary: true, best_fit: true,
      best_fit_min_dialogue: 7, best_fit_max_dialogue: 15,
    } }));
    expect(vm.overrides).toEqual({
      dialogue_ratio: 35,
      summary_detail_ratio: 70,
      max_budget: 1024,
      enforce_boundary: true,
      best_fit: true,
      best_fit_min_dialogue: 7,
      best_fit_max_dialogue: 15,
    });
  });

  it('a stale response cannot replace the selected character preview', () => {
    const vm = review();
    vm.fetchPreview();
    const first = vm.sent[0];
    vm.selectedCharacter = 'Bob';
    Review.watch.selectedCharacter.call(vm);
    expect(vm.handlers.size).toBe(2);
    vm.receive(response(first));
    expect(vm.preview).toBeNull();
    expect(vm.loading).toBe(true);
    vm.receive(response(vm.sent[1]));
    expect(vm.preview.perspective).toBe('Bob');
  });

  it('releases old request ownership and refetches on scene switch', () => {
    const vm = review();
    vm.preview = { perspective: null, sections: [], summary: {} };
    vm.fetchPreview();
    const old = vm.sent[0];
    vm.sceneId = 'scene-2';
    Review.watch.sceneId.call(vm);
    expect(vm.preview).toBeNull();
    expect(vm.loading).toBe(true);
    expect(vm.sent).toHaveLength(2);
    vm.receive(response(old));
    expect(vm.preview).toBeNull();
    vm.receive(response(vm.sent[1]));
    expect(vm.preview).not.toBeNull();
    expect(vm.loading).toBe(false);
  });

  it('settles on disconnect and starts one fresh request on reconnect', () => {
    const vm = review();
    vm.fetchPreview();
    vm.connected = false;
    Review.watch.connected.call(vm, false);
    expect(vm.loading).toBe(false);
    expect(vm.preview).toBeNull();
    vm.connected = true;
    Review.watch.connected.call(vm, true);
    expect(vm.sent).toHaveLength(2);
    expect(vm.loading).toBe(true);
  });

  it('Apply sends only scene-wide budget settings', () => {
    const vm = review();
    vm.selectedCharacter = 'Bob';
    vm.overrides.max_budget = 2048;
    vm.applyConfig();
    expect(vm.sent[0]).toEqual({ type: 'summarizer', action: 'apply_context_history_config', config: { ...vm.overrides } });
    expect(vm.sent[0]).not.toHaveProperty('character');
  });

  it('correlated errors clear loading and do not change selection', () => {
    const vm = review();
    vm.selectedCharacter = 'Bob';
    vm.fetchPreview();
    vm.receive({ type: 'summarizer', action: 'operation_done', request_id: 'unrelated', error: { message: 'Ignore' } });
    expect(vm.error).toBeNull();
    vm.receive({ type: 'summarizer', action: 'operation_done', request_id: vm.sent[0].request_id, error: { message: 'Select an active character' } });
    expect(vm.error).toBe('Select an active character');
    expect(vm.selectedCharacter).toBe('Bob');
    expect(vm.loading).toBe(false);
    expect(vm.handlers.size).toBe(1);
  });

  it('unmount removes the pending response handler', () => {
    const vm = review();
    vm.fetchPreview();
    Review.beforeUnmount.call(vm);
    expect(vm.handlers.size).toBe(0);
  });

  it('shows typed deferred status without clearing a previous preview', () => {
    const vm = review();
    vm.selectedCharacter = 'Bob';
    vm.preview = { sections: [], summary: {} };
    vm.fetchPreview();
    vm.receive({
      type: 'summarizer', action: 'context_review_status', request_id: vm.sent[0].request_id,
      data: { scene_id: 'scene-1', message_id: 7, character: 'Bob', state: 'deferred', message: 'Analyze perceptions now.' },
    });
    expect(vm.preview).not.toBeNull();
    expect(vm.perceptionStatus.state).toBe('deferred');
    expect(vm.waitingPerceptionMessageId).toBe(7);
    expect(vm.loading).toBe(false);
  });

  it('refreshes once for the correlated completion and ignores stale sources', () => {
    const vm = review();
    vm.selectedCharacter = 'Bob';
    vm.fetchPreview();
    vm.receive({
      type: 'summarizer', action: 'context_review_status', request_id: vm.sent[0].request_id,
      data: { scene_id: 'scene-1', message_id: 7, character: 'Bob', state: 'running', message: 'Still running.' },
    });
    const complete = { type: 'perception_status', data: { scene_id: 'scene-1', message_id: 7, audiences: ['Bob'], state: 'ready', message: 'Ready.' } };
    vm.receive({ ...complete, data: { ...complete.data, scene_id: 'old-scene' } });
    vm.receive({ ...complete, data: { ...complete.data, message_id: 8 } });
    vm.receive({ ...complete, data: { ...complete.data, audiences: ['Alice'] } });
    expect(vm.sent).toHaveLength(1);
    vm.receive(complete);
    expect(vm.sent).toHaveLength(2);
    vm.receive(complete);
    expect(vm.sent).toHaveLength(2);
    expect(vm.sent[1].character).toBe('Bob');
  });

  it('expands full evidence locally without sending a request', () => {
    const vm = review();
    vm.toggleFullEvidence(3);
    expect(vm.fullEvidenceOpen[3]).toBe(true);
    vm.toggleFullEvidence(3);
    expect(vm.fullEvidenceOpen[3]).toBe(false);
    expect(vm.sent).toEqual([]);
  });

  it('labels the exclusion reasons for readers', () => {
    const vm = review();
    expect(vm.exclusionReason('absent')).toBe('Absent');
    expect(vm.exclusionReason('not_in_audience')).toBe('Not in audience');
    expect(vm.exclusionReason('chronology_floor')).toBe('Below chronology floor');
    expect(vm.exclusionReason('superseded')).toBe('Superseded');
    expect(vm.exclusionReason('budget')).toBe('Over token budget');
  });
});
