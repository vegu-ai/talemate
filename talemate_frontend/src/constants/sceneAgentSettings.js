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
    if (a.enabled !== undefined && a.enabled !== null) n += 1;
    if (a.config) n += Object.keys(a.config).length;
  }
  return n;
}

/**
 * True if an action schema has at least one scene-overridable surface —
 * either its container-level `enabled` flag or any config field. Used by
 * AgentModal (with the extra container guard) and AgentSceneSettings to
 * decide whether the scene tab / panel should render.
 */
export function actionHasOverridable(actionSchema) {
  if (!actionSchema) return false;
  // enabled_scene_overridable only matters when the action can actually be
  // disabled globally; otherwise there's no enable flag to override.
  if (actionSchema.enabled_scene_overridable && actionSchema.can_be_disabled) return true;
  const cfg = actionSchema.config || {};
  for (const ck in cfg) {
    if (cfg[ck]?.scene_overridable) return true;
  }
  return false;
}
