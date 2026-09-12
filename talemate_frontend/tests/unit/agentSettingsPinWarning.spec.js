// @vitest-environment jsdom
import { afterEach, describe, expect, it } from 'vitest';
import { createApp, defineComponent, h } from 'vue';
import AgentConfigSection from '@/components/AgentConfigSection.vue';
import AgentSceneSettings from '@/components/AgentSceneSettings.vue';
import { WORLD_STATE_PIN_WARNING, worldStatePinField } from '@/utils/worldStatePinWarning';

let app;
let host;
afterEach(() => {
  app?.unmount();
  host?.remove();
});

const schema = {
  container: true,
  can_be_disabled: true,
  enabled_scene_overridable: true,
  label: 'Update world state',
  config: {
    turns: { type: 'number', label: 'Turns', value: 10, scene_overridable: true },
    inject_as_scene_memory: { type: 'bool', label: 'Pin to context', value: false, scene_overridable: true },
  },
};

function values(enabled, pin, turns) {
  return {
    enabled,
    config: {
      turns: { value: turns },
      inject_as_scene_memory: { value: pin },
    },
  };
}

function mount(component, props) {
  host = document.createElement('div');
  document.body.appendChild(host);
  app = createApp(component, props);
  const passthrough = defineComponent({ setup: (_, { slots }) => () => h('div', slots.default?.()) });
  for (const tag of ['VSheet', 'VCheckbox', 'VNumberInput', 'VAlert', 'VIcon', 'VBtn', 'VSlider', 'VSelect', 'VTextarea', 'VCombobox', 'VSwitch', 'VRow', 'VCol', 'VMenu', 'VList', 'VListItem']) {
    app.component(tag, passthrough);
  }
  app.provide('callAgentTool', () => {});
  app.config.warnHandler = () => {};
  app.mount(host);
  return host.textContent;
}

describe('pinned world snapshot warning', () => {
  it.each([
    [false, false, 1, false],
    [true, false, 1, true],
    [true, true, 1, false],
    [true, true, 2, true],
    [false, true, 2, false],
  ])('evaluates pin=%s enabled=%s turns=%s', (pin, enabled, turns, warned) => {
    const field = worldStatePinField({
      actionKey: 'update_world_state',
      configKey: 'inject_as_scene_memory',
      field: schema.config.inject_as_scene_memory,
      enabled,
      pin,
      turns,
    });
    expect(field.note?.text === WORLD_STATE_PIN_WARNING).toBe(warned);
    expect(schema.config.inject_as_scene_memory.note).toBeUndefined();
  });

  it('renders from the unsaved global working copy', () => {
    const text = mount(AgentConfigSection, {
      actionKey: 'update_world_state',
      schema,
      values: values(false, true, 1),
      actions: {},
    });
    expect(text).toContain(WORLD_STATE_PIN_WARNING);
  });

  it('renders from the edited scene overlay over contradictory globals', () => {
    const global = values(true, false, 1);
    const overrides = {
      enabled: false,
      config: { inject_as_scene_memory: { value: true }, turns: { value: 1 } },
    };
    const text = mount(AgentSceneSettings, {
      actionKey: 'update_world_state',
      action: global,
      actionSchema: schema,
      overrides,
      agentActions: { update_world_state: global },
      overlay: { actions: { update_world_state: overrides } },
    });
    expect(text).toContain(WORLD_STATE_PIN_WARNING);
  });
});
