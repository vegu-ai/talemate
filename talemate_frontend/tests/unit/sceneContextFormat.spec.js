// @vitest-environment jsdom

import { describe, expect, it, vi } from 'vitest';
import { resolve } from 'node:path';
import { createApp, defineComponent, h, nextTick } from 'vue';
import UxNote from '@/components/UxNote.vue';
import { lift, readSource } from './helpers/liftMethod.js';
import { replyAfterAll } from '@/utils/writeReply';
import { sectionOverrideCounts, setActionOverrideSlice } from '@/constants/sceneAgentSettings';
import { effortMode } from '@/utils/knowledgeEffort';
import { perspectivesEnabled } from '@/utils/sceneSettings';

// jsdom gives import.meta.url an http scheme, so the source is found from the vitest root
const aiAgent = readSource(resolve(process.cwd(), 'src/components/AIAgent.vue'));
const talemateApp = readSource(resolve(process.cwd(), 'src/components/TalemateApp.vue'));

const CHOICES = [
  { label: 'Screenplay', value: 'movie_script' },
  { label: 'Chat (legacy)', value: 'chat' },
  { label: 'Narrative', value: 'narrative' },
  { label: 'AI Aware', value: 'ai_aware' },
];

function summarizerStatus(value = 'movie_script', sceneOverrides = {}) {
  return {
    actions: { manage_scene_history: { container: true, config: { format: { type: 'text', label: 'Format', choices: CHOICES, value } } } },
    scene_overrides: sceneOverrides,
  };
}

function formatOverride(value) {
  return { actions: { manage_scene_history: { config: { format: { value } } } } };
}

const Container = defineComponent({ setup: (_, { slots }) => () => h('div', slots.default?.()) });

describe('the drawer answers a single agent write', () => {
  const deps = { replyAfterAll };

  it('sends an overridden value to the scene override with a request id and answers on its reply', () => {
    const applyActionValues = lift(aiAgent, 'applyActionValues', 'AIAgent.vue', deps);
    const saveSceneOverrideSlice = lift(aiAgent, 'saveSceneOverrideSlice', 'AIAgent.vue', { setActionOverrideSlice });
    const handleMessage = lift(aiAgent, 'handleMessage', 'AIAgent.vue', { effortMode, perspectivesEnabled, PENDING_EFFORT_TTL: 30000 });
    const sent = [];
    const agent = { name: 'summarizer', data: { scene_overrides: formatOverride('chat') }, actions: summarizerStatus().actions };
    const self = {
      sliceReplies: {}, sliceSeq: 0, saveAgent: vi.fn(), state: { agents: [agent] },
      getWebsocket: () => ({ send: text => sent.push(JSON.parse(text)) }),
      sceneOverlay: a => a.data.scene_overrides, isEnabledOverridden: () => false,
      isConfigOverridden: (a, action, key) => key === 'format',
    };
    self.saveSceneOverrideSlice = saveSceneOverrideSlice.bind(self);
    const reply = { onComplete: vi.fn(), onError: vi.fn() };

    applyActionValues.call(self, agent, 'manage_scene_history', { config: { format: 'narrative' } }, reply);

    expect(self.saveAgent).not.toHaveBeenCalled();
    expect(sent[0]).toMatchObject({ action: 'save_scene_overrides', agent_type: 'summarizer',
      override: formatOverride('narrative') });
    expect(sent[0].request_id).toBeTruthy();
    handleMessage.call(self, { type: 'agent_config', action: 'operation_done', request_id: 'someone-else' });
    expect(reply.onComplete).not.toHaveBeenCalled();
    handleMessage.call(self, { type: 'agent_config', action: 'operation_done', request_id: sent[0].request_id, data: {} });
    expect(reply.onComplete).toHaveBeenCalledTimes(1);
    expect(reply.onError).not.toHaveBeenCalled();
  });

  it('reports a refused scene override', () => {
    const handleMessage = lift(aiAgent, 'handleMessage', 'AIAgent.vue', { effortMode, perspectivesEnabled, PENDING_EFFORT_TTL: 30000 });
    const reply = { onComplete: vi.fn(), onError: vi.fn() };
    const self = { sliceReplies: { r1: reply }, state: { agents: [] } };
    handleMessage.call(self, { type: 'agent_config', action: 'operation_done', request_id: 'r1', error: { message: 'Failed to write agent-settings file' } });
    expect(reply.onError).toHaveBeenCalledWith('Failed to write agent-settings file');
    expect(self.sliceReplies).toEqual({});
  });

  it('hands a global write and its reply to the config save', () => {
    const applyActionValues = lift(aiAgent, 'applyActionValues', 'AIAgent.vue', deps);
    const agent = { name: 'summarizer', data: { scene_overrides: {} }, actions: summarizerStatus().actions };
    const self = { saveAgent: vi.fn(), saveSceneOverrideSlice: vi.fn(), sceneOverlay: () => ({}), isEnabledOverridden: () => false, isConfigOverridden: () => false };
    const reply = { onComplete: vi.fn(), onError: vi.fn() };

    applyActionValues.call(self, agent, 'manage_scene_history', { config: { format: 'chat' } }, reply);

    expect(agent.actions.manage_scene_history.config.format.value).toBe('chat');
    const [, answer] = self.saveAgent.mock.calls[0];
    answer.onComplete();
    expect(reply.onComplete).toHaveBeenCalledTimes(1);
  });

  it('passes the reply to the config save queue, and refuses when nothing is sent', () => {
    const saveAgents = lift(talemateApp, 'saveAgents', 'TalemateApp.vue', { buildNameKeyedPayload: () => ({}) });
    const reply = { onComplete: vi.fn(), onError: vi.fn() };
    const self = { saveAppConfig: vi.fn(() => 'cfg-1') };
    saveAgents.call(self, [], reply);
    expect(self.saveAppConfig.mock.calls[0][1]).toMatchObject({ label: 'agents', onComplete: reply.onComplete, onError: reply.onError });
    expect(reply.onError).not.toHaveBeenCalled();

    self.saveAppConfig = vi.fn(() => null);
    saveAgents.call(self, [], reply);
    expect(reply.onError).toHaveBeenCalledTimes(1);
  });
});

describe('replyAfterAll', () => {
  it('completes after every write and settles once', () => {
    const reply = { onComplete: vi.fn(), onError: vi.fn() };
    const answer = replyAfterAll(reply, 2);
    answer.onComplete();
    expect(reply.onComplete).not.toHaveBeenCalled();
    answer.onComplete();
    answer.onError('late');
    expect(reply.onComplete).toHaveBeenCalledTimes(1);
    expect(reply.onError).not.toHaveBeenCalled();
  });

  it('reports the first refusal only', () => {
    const reply = { onComplete: vi.fn(), onError: vi.fn() };
    const answer = replyAfterAll(reply, 2);
    answer.onError('first');
    answer.onError('second');
    answer.onComplete();
    answer.onComplete();
    expect(reply.onError).toHaveBeenCalledWith('first');
    expect(reply.onError).toHaveBeenCalledTimes(1);
    expect(reply.onComplete).not.toHaveBeenCalled();
  });

  it('passes the apply flag of a refusal through', () => {
    const reply = { onComplete: vi.fn(), onError: vi.fn() };
    replyAfterAll(reply, 1).onError('applying failed', true);
    expect(reply.onError).toHaveBeenCalledWith('applying failed', true);
  });

  it('completes at once when nothing is written, and is null without a reply', () => {
    const reply = { onComplete: vi.fn(), onError: vi.fn() };
    expect(replyAfterAll(reply, 0)).toBeNull();
    expect(reply.onComplete).toHaveBeenCalledTimes(1);
    expect(replyAfterAll(null, 1)).toBeNull();
  });
});

describe('the Scene History section counts a format override', () => {
  it('counts the override in its own section', () => {
    const schema = { manage_scene_history: { container: true }, archive: { container: true } };
    expect(sectionOverrideCounts(formatOverride('chat'), schema)).toEqual({ manage_scene_history: 1 });
  });
});

describe('an action note', () => {
  it('shows its text and runs its action', async () => {
    const callAgentTool = vi.fn();
    const note = {
      text: "The scene context format moved to the Summarizer agent's Scene History section.",
      color: 'primary', icon: 'mdi-information-outline',
      actions: [{ action_name: 'openAgentSettings', arguments: ['summarizer', 'manage_scene_history'], label: 'Open Scene History', icon: 'mdi-arrow-split-vertical' }],
    };
    const app = createApp({ render: () => h(UxNote, { note }) });
    app.component('VAlert', Container);
    app.component('VBtn', defineComponent({ emits: ['click'], setup: (_, { slots, emit }) => () => h('button', { onClick: () => emit('click') }, slots.default?.()) }));
    app.provide('callAgentTool', callAgentTool);
    const host = document.createElement('div');
    app.mount(host);
    expect(host.textContent).toContain('Scene History section');
    const button = host.querySelector('button');
    expect(button.textContent).toBe('Open Scene History');
    button.click();
    await nextTick();
    expect(callAgentTool).toHaveBeenCalledWith('openAgentSettings', ['summarizer', 'manage_scene_history']);
    app.unmount();
  });
});
