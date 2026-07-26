import { getProperty } from 'dot-prop';
import { conditionMet } from '@/utils/uxConditions';

/**
 * Validation rules for the scene agent-settings filename input
 * (used by the RequestInput dialog in AgentModal).
 *
 * Mirrors the server-side `is_safe_settings_filename` guard so the user
 * gets inline feedback in the dialog instead of round-tripping a doomed
 * save through the websocket. Each rule is a Vuetify-style validator:
 * returns true on success or an error message string.
 *
 * Files live in the dedicated `agent-settings/` subdir of the scene's
 * project folder, so the filename itself just needs to be a safe `.json`
 * name — no prefix is required.
 */
export const SCENE_AGENT_SETTINGS_FILENAME_RULES = [
  v => (v || '').endsWith('.json') || 'Filename must end in .json',
  v => (v || '').length > '.json'.length || 'Filename is required',
  v => !(v || '').includes('/') || 'No path separators allowed',
  v => !(v || '').includes('\\') || 'No path separators allowed',
  v => !(v || '').includes('\0') || 'Invalid characters in filename',
];

export const DEFAULT_SCENE_AGENT_SETTINGS_FILENAME = 'agent-settings.json';

/** Subdirectory under the scene's project folder that holds settings files. */
export const SCENE_AGENT_SETTINGS_DIRNAME = 'agent-settings';

/**
 * Count active scene overrides in an overlay shaped like
 * `{actions: {[key]: {enabled?, config?: {[key]: {value}}}}}`. Counts
 * overridden config fields + container-enabled overrides.
 */
export function countSceneOverrides(overlay) {
  const actions = overlay?.actions || {};
  let n = 0;
  for (const k in actions) {
    const a = actions[k];
    if (hasEnabledOverride(a)) n += 1;
    if (a.config) n += Object.keys(a.config).length;
  }
  return n;
}

/**
 * Replace one action's slice in an overlay's `actions` map, keeping the
 * overlay sparse: an empty per-action override (no enabled flag, no config
 * keys) removes the entry instead of storing it. Returns a new map.
 */
export function setActionOverrideSlice(actions, actionKey, perActionOverride) {
  const next = { ...actions };
  const isEmpty =
    !hasEnabledOverride(perActionOverride) &&
    (!perActionOverride?.config || Object.keys(perActionOverride.config).length === 0);
  if (isEmpty) {
    delete next[actionKey];
  } else {
    next[actionKey] = perActionOverride;
  }
  return next;
}

/**
 * Resolve a condition attribute (e.g. "character_creation.config.fast") to the
 * value scene mode should judge it by: the overlay first, the agent's global
 * action values second. The sparse overlay mirrors the actions map shape, so
 * the same dotted path addresses both.
 */
export function effectiveConfigValue(actions, overlay, attribute) {
  const path = attribute + '.value';
  const overridden = getProperty(overlay?.actions ?? {}, path);
  if (overridden !== undefined) return overridden;
  return getProperty(actions ?? {}, path);
}

/**
 * Evaluate a UX visibility condition against the scene's effective values —
 * the condition's source field may itself be overridden for this scene.
 */
export function effectiveConditionMet(condition, actions, overlay) {
  if (condition == null) return true;
  return conditionMet(condition, effectiveConfigValue(actions, overlay, condition.attribute));
}

/**
 * The per-action override slice for `actionKey` in a sparse overlay, or null
 * when the scene overrides nothing on that action.
 */
export function actionOverrideSlice(overlay, actionKey) {
  return overlay?.actions?.[actionKey] || null;
}

/** True when a per-action override slice pins the action's enable flag. */
export function hasEnabledOverride(slice) {
  return !!slice && slice.enabled !== undefined && slice.enabled !== null;
}

/** True when the scene overrides an action's container-level enable flag. */
export function enabledOverrideActive(overlay, actionKey) {
  return hasEnabledOverride(actionOverrideSlice(overlay, actionKey));
}

/** True when the scene overrides one of an action's config fields. */
export function configOverrideActive(overlay, actionKey, configKey) {
  return !!actionOverrideSlice(overlay, actionKey)?.config?.[configKey];
}

/**
 * An action's enable flag as the scene sees it — the override when one is
 * active, the agent's global flag otherwise. Mirrors `Agent.resolve_enabled`.
 */
export function effectiveActionEnabled(actions, overlay, actionKey) {
  if (enabledOverrideActive(overlay, actionKey)) {
    return !!overlay.actions[actionKey].enabled;
  }
  return !!actions?.[actionKey]?.enabled;
}

/** True if a per-action override slice holds anything at all. */
function actionHasActiveOverride(overrides) {
  if (!overrides) return false;
  if (hasEnabledOverride(overrides)) return true;
  return Object.keys(overrides.config || {}).length > 0;
}

/**
 * True if an action schema has at least one scene-overridable surface —
 * either its container-level `enabled` flag or any config field. Used by
 * AgentModal (with the extra container guard) and AgentSceneSettings to
 * decide whether the scene tab / panel should render.
 *
 * @param conditionContext {actions, overlay, overrides} — the effective values
 *   conditions resolve against, plus this action's own override slice. An
 *   already-set override keeps its surface even when the gate is off: the
 *   backend applies stored overrides without evaluating conditions, so hiding
 *   one would leave it in effect and unreachable.
 */
export function actionHasOverridable(actionSchema, conditionContext) {
  if (!actionSchema) return false;
  const { actions, overlay, overrides } = conditionContext;
  if (actionHasActiveOverride(overrides)) return true;
  if (!effectiveConditionMet(actionSchema.condition, actions, overlay)) return false;
  // enabled_scene_overridable only matters when the action can actually be
  // disabled globally; otherwise there's no enable flag to override.
  if (actionSchema.enabled_scene_overridable && actionSchema.can_be_disabled) return true;
  const cfg = actionSchema.config || {};
  for (const ck in cfg) {
    if (!cfg[ck]?.scene_overridable) continue;
    if (!effectiveConditionMet(cfg[ck].condition, actions, overlay)) continue;
    return true;
  }
  return false;
}
