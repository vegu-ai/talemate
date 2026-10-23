import { describe, expect, it, vi } from 'vitest';
import { resolve } from 'node:path';
import { lift, readSource } from './helpers/liftMethod.js';
import { createConfigSaveQueue } from '@/utils/configSaveQueue';
import { replyAfterAll } from '@/utils/writeReply';

const aiAgent = readSource(resolve(process.cwd(), 'src/components/AIAgent.vue'));

function summarizer(value = 'movie_script') {
  return {
    name: 'summarizer',
    data: { scene_overrides: {} },
    actions: { manage_scene_history: { config: { format: { value } } } },
  };
}

// the drawer's global write path on the real config save queue
function setup(stored = 'movie_script') {
  const sent = [];
  const queue = createConfigSaveQueue({
    send: frame => sent.push(frame),
    getConfig: () => ({ agents: { summarizer: { actions: { manage_scene_history: { config: { format: { value: stored } } } } } } }),
    notifyError: vi.fn(),
    resetPendingSaves: vi.fn(),
  });
  const agent = summarizer(stored);
  const applyActionValues = lift(aiAgent, 'applyActionValues', 'AIAgent.vue', { replyAfterAll });
  const drawer = {
    sceneOverlay: () => ({}),
    isEnabledOverridden: () => false,
    isConfigOverridden: () => false,
    saveSceneOverrideSlice: vi.fn(),
    saveAgent: (target, reply) => queue.saveAppConfig((config) => {
      config.agents.summarizer.actions.manage_scene_history.config.format.value =
        target.actions.manage_scene_history.config.format.value;
    }, { label: 'agents', onComplete: reply?.onComplete, onError: reply?.onError }),
  };
  const write = (value, reply = null) => applyActionValues.call(drawer, agent, 'manage_scene_history', { config: { format: value } }, reply);
  const field = () => agent.actions.manage_scene_history.config.format.value;
  return { queue, sent, write, field };
}

describe('stacked writes of one field', () => {
  it('a refused first save returns the field to the stored value', () => {
    const t = setup('movie_script');
    t.write('narrative');
    t.write('chat');
    expect(t.field()).toBe('chat');

    t.queue.handleMessage({ action: 'operation_done', request_id: t.sent[0].request_id, error: { message: 'refused' } });

    expect(t.field()).toBe('movie_script');
  });

  it('a refused second save returns the field to the first value, which the first save stores', () => {
    const t = setup('movie_script');
    t.write('narrative');
    t.write('chat');

    t.queue.handleMessage({ action: 'operation_done', request_id: t.sent[1].request_id, error: { message: 'refused' } });
    expect(t.field()).toBe('narrative');

    t.queue.handleMessage({ action: 'save_complete', request_id: t.sent[0].request_id });
    expect(t.field()).toBe('narrative');
  });

  it('three stacked writes unwind to the stored value', () => {
    const t = setup('movie_script');
    t.write('narrative');
    t.write('chat');
    t.write('ai_aware');

    t.queue.handleMessage({ action: 'operation_done', request_id: t.sent[0].request_id, error: { message: 'refused' } });

    expect(t.field()).toBe('movie_script');
  });

  it('every refused save hears its error', () => {
    const t = setup('movie_script');
    const first = { onComplete: vi.fn(), onError: vi.fn() };
    const second = { onComplete: vi.fn(), onError: vi.fn() };
    t.write('narrative', first);
    t.write('chat', second);

    t.queue.handleMessage({ action: 'operation_done', request_id: t.sent[0].request_id, error: { message: 'refused' } });

    expect(first.onError.mock.calls[0][0]).toBe('refused');
    expect(second.onError.mock.calls[0][0]).toBe('refused');
  });
});

describe('stacked writes when the connection closes', () => {
  it('dropAll returns the field to the stored value', () => {
    const t = setup('movie_script');
    t.write('narrative');
    t.write('chat');

    t.queue.dropAll('The connection to the backend was lost before the save was answered.');

    expect(t.field()).toBe('movie_script');
  });
});
