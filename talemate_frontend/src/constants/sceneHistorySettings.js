// The Summarizer's Scene History settings as the Scene Context view shows them:
// order and control type here; labels, ranges and notes come from the agent.
import { effectiveConfigValue } from '@/constants/sceneAgentSettings';
import { buildOwnership } from '@/utils/sceneOverrideOwnership';

export const SCENE_HISTORY_AGENT = 'summarizer';
export const SCENE_HISTORY_ACTION = 'manage_scene_history';

// `when`: the Best Fit Mode value a row belongs to; absent = both modes
export const SCENE_HISTORY_SETTINGS = Object.freeze([
  { key: 'format', control: 'select' },
  { key: 'best_fit', control: 'bool' },
  { key: 'best_fit_min_dialogue', control: 'slider', when: true },
  { key: 'best_fit_max_dialogue', control: 'slider', when: true },
  { key: 'dialogue_ratio', control: 'slider', when: false, unit: '%' },
  { key: 'summary_detail_ratio', control: 'slider', when: false, unit: '%' },
  { key: 'max_budget', control: 'number' },
  { key: 'enforce_boundary', control: 'bool', when: false },
]);

export const SCENE_HISTORY_KEYS = Object.freeze(SCENE_HISTORY_SETTINGS.map(({ key }) => key));

export const SCENE_HISTORY_OWNED = buildOwnership(
  SCENE_HISTORY_KEYS.map((key) => ({ agent: SCENE_HISTORY_AGENT, action: SCENE_HISTORY_ACTION, key })),
);

/** The value the loaded scene runs on: its override when set, else the global value. */
export function sceneHistoryValue(summarizer, key) {
  if (!summarizer?.actions) return undefined;
  return effectiveConfigValue(summarizer.actions, summarizer.scene_overrides, `${SCENE_HISTORY_ACTION}.config.${key}`);
}
