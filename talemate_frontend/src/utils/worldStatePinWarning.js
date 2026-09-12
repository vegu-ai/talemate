export const WORLD_STATE_PIN_WARNING = 'The pinned snapshot may include outdated information until the next update. Enable Update world state and set Turns to 1 to refresh it every turn.';

export function worldStatePinField({ actionKey, configKey, field, enabled, pin, turns }) {
  if (actionKey !== 'update_world_state' || configKey !== 'inject_as_scene_memory') return field;
  if (!pin || (enabled && Number(turns) === 1)) return field;
  return {
    ...field,
    note: {
      color: 'warning',
      icon: 'mdi-alert-circle-outline',
      text: WORLD_STATE_PIN_WARNING,
    },
  };
}
