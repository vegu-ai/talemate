// The scene overrides a view owns: the keys its "use global settings" controls
// clear and its origin markers read, so a reset of one group and a reset of the
// whole view clear the same keys and nothing outside them.
//
// The knowledge hub owns the toggles it shows and every key of both effort
// tables; other views build their own set with `buildOwnership`.
import { EFFORT_PRESETS, EFFORT_STOPS } from '@/constants/knowledgeEffort';
import { KNOWLEDGE_TOGGLES } from '@/utils/knowledgeHub';
import { effortKey, effortValueOf } from '@/utils/knowledgeEffort';
import { configOverrideActive, enabledOverrideActive } from '@/constants/sceneAgentSettings';

/** entries: [{ agent, action, key }] — `key` is a config name or 'enabled'. */
export function buildOwnership(entries) {
    const owned = {};
    for (const { agent, action, key } of entries) {
        const id = `${agent}.${action}`;
        if (!owned[id]) owned[id] = { agent, action, keys: new Set() };
        owned[id].keys.add(key);
    }
    return Object.freeze(owned);
}

function knowledgeEntries() {
    const entries = KNOWLEDGE_TOGGLES.map((spec) => ({ agent: spec.agent, action: spec.action, key: spec.config ?? 'enabled' }));
    for (const mode of Object.keys(EFFORT_PRESETS)) {
        for (const stop of EFFORT_STOPS[mode]) {
            for (const key of Object.keys(EFFORT_PRESETS[mode][stop])) {
                const [agent, action, config] = key.split('.');
                entries.push({ agent, action, key: config });
            }
        }
    }
    return entries;
}

export const HUB_OWNED_OVERRIDES = buildOwnership(knowledgeEntries());

/** The keys owned on one action, or an empty list for an unknown one. */
export function ownedKeys(agent, action, owned = HUB_OWNED_OVERRIDES) {
    return [...(owned[`${agent}.${action}`]?.keys || [])];
}

/** The owned keys of one action that the overlay actually overrides. */
export function overriddenOwnedKeys(overlay, agent, action, owned = HUB_OWNED_OVERRIDES) {
    const keys = owned[`${agent}.${action}`]?.keys;
    if (!keys) return [];
    const result = [];
    for (const key of keys) {
        if (key === 'enabled' ? enabledOverrideActive(overlay, action) : configOverrideActive(overlay, action, key)) {
            result.push(key);
        }
    }
    return result;
}

/** True when any owned key on that action is currently overridden. */
export function groupHasOwnedOverride(overlay, agent, action, owned = HUB_OWNED_OVERRIDES) {
    return overriddenOwnedKeys(overlay, agent, action, owned).length > 0;
}

/** True when the action's own enable override is active — the master chip's case. */
export function masterOverrideActive(overlay, agent, action, owned = HUB_OWNED_OVERRIDES) {
    if (!owned[`${agent}.${action}`]?.keys.has('enabled')) return false;
    return enabledOverrideActive(overlay, action);
}

/** True when one owned config key is overridden, keyed the hub way. */
function effortKeyOverridden(agents, key) {
    const { agent: agentName, action: actionName, config } = effortKey(key);
    const agent = (agents || []).find((candidate) => candidate.name === agentName);
    const overlay = agent?.data?.scene_overrides || {};
    if (config === null) return enabledOverrideActive(overlay, actionName);
    return configOverrideActive(overlay, actionName, config);
}

/**
 * Where the current mode's effort controls come from. `present` is how many of
 * the mode's preset keys the status carries; `overridden` how many of those the
 * scene pins. `any` drives the "Scene override" chip, `complete` its "all"
 * tooltip; a partially global state is never relabelled as entirely owned.
 */
export function effortOverrideState(agents, mode) {
    const keys = new Set();
    for (const stop of EFFORT_STOPS[mode] || []) {
        for (const key of Object.keys(EFFORT_PRESETS[mode]?.[stop] || {})) keys.add(key);
    }
    let present = 0;
    let overridden = 0;
    for (const key of keys) {
        if (effortValueOf(agents, key) === undefined) continue;
        present += 1;
        if (effortKeyOverridden(agents, key)) overridden += 1;
    }
    return { present, overridden, any: overridden > 0, complete: present > 0 && overridden === present };
}

/** The clear entries that drop a whole group's owned overrides. */
export function groupClearEntries(agent, action, owned = HUB_OWNED_OVERRIDES) {
    return ownedKeys(agent, action, owned).map((key) => (
        key === 'enabled' ? { agent, action } : { agent, action, config: key }
    ));
}

export function settingClearEntry(agent, action, config) {
    return { agent, action, config };
}

/** The clear entries that drop every owned override — for the hub, across both modes. */
export function clearEntriesFor(owned = HUB_OWNED_OVERRIDES) {
    return Object.values(owned).flatMap(({ agent, action }) => groupClearEntries(agent, action, owned));
}

/** True when anything owned — hidden keys included — is overridden. */
export function hasOverridesFor(agents, owned = HUB_OWNED_OVERRIDES) {
    for (const { agent, action } of Object.values(owned)) {
        const entry = (agents || []).find((candidate) => candidate.name === agent);
        if (groupHasOwnedOverride(entry?.data?.scene_overrides || {}, agent, action, owned)) return true;
    }
    return false;
}
